"""warrant_compute (CONTRACT C.6): the receiver's computation operations.

ops: provider, term, start, resume, cycle. Bytes come from the receiver's own
store, are read once and handed to the operator-installed provider; new bytes go
back into the store as content-addressed blobs. A foreign checkpoint is only
ever continued through the provider's checked `resume` (verify from the
receiver's root, then advance), never raw advance. Nothing here files a duty,
an acceptance or a closure, and a provider is never added to the receiver's
profile: Warrant credit still needs the receiver-accepted identity and the
engine's own replay of a final receipt."""
import base64

from warrant import compute as P
from warrant import jcs as C
from warrant.store import Snapshot, Store

from . import AGENT_API, adapter_id
from .errors import AgentError, need

RUNTIMES = {"book1": P.BOOK1, "rich": P.RICH, P.BOOK1: P.BOOK1, P.RICH: P.RICH}
OPS = {"provider": (), "term": ("expr",), "start": ("runtime", "input", "environment"),
       "resume": ("runtime", "input", "environment", "checkpoint", "state", "credit"),
       "cycle": ("runtime", "input", "environment", "max_steps")}
OPTIONAL = {"resume": ("max_actions", "target"), "cycle": ("target",)}


def _hex(v):
    return isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)


def _closed(req):
    need(isinstance(req, dict) and req.get("op") in OPS, "BAD_REQUEST", f"compute op is one of {sorted(OPS)}")
    op = req["op"]
    allowed = {"op", "workspace", "agent_api"} | set(OPS[op]) | set(OPTIONAL.get(op, ()))
    missing = {"workspace", *OPS[op]} - set(req)
    need(not missing, "BAD_REQUEST", f"missing {sorted(missing)}")
    need(not set(req) - allowed, "BAD_REQUEST", f"unknown members {sorted(set(req) - allowed)}")
    for k in ("input", "environment", "checkpoint", "state"):
        if k in req:
            need(_hex(req[k]), "BAD_REQUEST", f"{k} is a hex64 content address")
    if "runtime" in req:
        need(isinstance(req["runtime"], str) and req["runtime"] in RUNTIMES, "BAD_REQUEST", "unknown runtime")
    for k, low in (("credit", 0), ("max_actions", 1), ("max_steps", 1)):
        if k in req and not (k == "max_actions" and req[k] is None):
            need(type(req[k]) is int and req[k] >= low, "BAD_REQUEST", f"{k} is an integer >= {low}")
    if "target" in req:
        need(isinstance(req["target"], str) and 0 < len(req["target"]) <= 200, "BAD_REQUEST", "target")
    return op


def _provider():
    try:
        return P.Provider.capture()
    except P.ProviderError as e:
        raise AgentError("PROVIDER", str(e)) from None


def _call(ws, provider, op, args, blobs):
    try:
        out = provider.call(op, args, blobs, timeout=ws.limits["provider_seconds"])
    except P.ProviderError as e:
        # A hard stop returns no state: nothing is stored, nothing is invented.
        raise AgentError("PROVIDER", str(e)) from None
    if "refused" in out:
        raise AgentError("REFUSED", f"provider refused: {out['refused']}")
    return out


def _environment(snap, h):
    doc = snap.json_blob(h)
    need(doc is not None and P.environment_problem(doc) is None, "NOT_FOUND",
         "the environment manifest is not in this store")
    hashes = doc["sigma-environment"]
    return hashes, {x: snap.blobs[x] for x in hashes if x in snap.blobs}


def _bytes(snap, h, what):
    need(h in snap.blobs, "NOT_FOUND", f"the {what} is not in this store; nothing is read from elsewhere")
    return snap.blobs[h]


def run(cfg, req):
    op = _closed(req)
    ws = cfg.workspace(req["workspace"])
    ws.permit("compute")
    provider = _provider()
    accepted = provider.id in ws.profile().get("providers", [])
    store = Store(ws.store).init()
    snap = Snapshot.read(ws.store)          # read once; every byte below comes from this capture
    data = {"op": op, "provider": provider.id, "provider_accepted_by_profile": accepted}
    if op == "provider":
        data["files"] = provider.identity["files"]
    elif op == "term":
        need(isinstance(req["expr"], str) and len(req["expr"]) <= 10_000, "BAD_REQUEST", "expr")
        out = _call(ws, provider, "term", {"expr": req["expr"]}, {})
        nodes = [store.put_blob(base64.b64decode(b)) for b in out["nodes"].values()]
        data.update(input=out["input"], environment=store.put_json(P.environment_doc(nodes)),
                    runtimes=sorted({P.BOOK1, P.RICH}))
    else:
        runtime = RUNTIMES[req["runtime"]]
        hashes, blobs = _environment(snap, req["environment"])
        args = {"runtime": runtime, "input": req["input"], "hashes": hashes}
        if op == "start":
            out = _call(ws, provider, "start", args, blobs)
            data.update(checkpoint=store.put_blob(base64.b64decode(out["checkpoint"])),
                        state=store.put_blob(base64.b64decode(out["state"])), status="STARTED")
        elif op == "resume":
            ck, st = _bytes(snap, req["checkpoint"], "checkpoint"), _bytes(snap, req["state"], "state")
            args.update(checkpoint=base64.b64encode(ck).decode(), state=base64.b64encode(st).decode(),
                        credit=req["credit"])
            if req.get("max_actions") is not None:
                args["max_actions"] = req["max_actions"]
            out = _call(ws, provider, "resume", args, blobs)
            data.update(status=out["status"], base_verification=out["base_verification"],
                        parent={"checkpoint": req["checkpoint"], "state": req["state"]}, credit=req["credit"])
            for k in ("code", "result", "diagnostic"):
                if k in out:
                    data[k] = out[k]
            seg = out.get("segment")
            if seg:
                c2 = store.put_blob(base64.b64decode(seg["checkpoint"]))
                s2 = store.put_blob(base64.b64decode(seg["state"]))
                data["segment"] = {"outcome": seg["outcome"], "checkpoint": c2, "state": s2,
                                   "result": seg.get("result"), "missing": seg.get("missing")}
                if seg["outcome"] == "NORMAL_FORM" and req.get("target"):
                    data["receipt"] = store.put_json({"receipt": "sigma-resume", "target": req["target"],
                                                      "input": req["input"], "environment": req["environment"],
                                                      "checkpoint": c2, "state": s2, "claimed": seg["result"],
                                                      "lost": []})
        else:
            out = _call(ws, provider, "find_cycle", dict(args, max_steps=req["max_steps"]), blobs)
            if "witness" in out:
                w = store.put_blob(base64.b64decode(out["witness"]))
                data["witness"] = w
                if req.get("target"):
                    data["cycle"] = store.put_json({"cycle": "sigma-resume", "target": req["target"],
                                                    "input": req["input"], "environment": req["environment"],
                                                    "witness": w, "lost": []})
            else:
                data["outcome"] = out.get("outcome")
    data["store_snapshot_before"] = snap.digest
    return {"agent_api": AGENT_API, "adapter_id": adapter_id(), "data": data,
            "request_digest": C.doc_id({k: v for k, v in req.items() if k != "agent_api"})}
