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
from warrant import shapes as S
from warrant.store import Store

from . import AGENT_API, adapter_id, views
from .errors import AgentError, need

RUNTIMES = {"book1": P.BOOK1, "rich": P.RICH, P.BOOK1: P.BOOK1, P.RICH: P.RICH}
OPS = {"provider": (), "term": ("expr",), "evaluate": ("expr",), "start": ("runtime", "input", "environment"),
       "resume": ("runtime", "input", "environment", "checkpoint", "state", "credit"),
       "cycle": ("runtime", "input", "environment", "max_steps")}
OPTIONAL = {"resume": ("max_actions", "target"), "cycle": ("target",), "evaluate": ("expect_expr", "credit", "runtime")}
EVALUATE_CREDIT = 10_000


def _closed(req):
    need(isinstance(req, dict) and req.get("op") in OPS, "BAD_REQUEST", f"compute op is one of {sorted(OPS)}")
    op = req["op"]
    allowed = {"op", "workspace", "agent_api"} | set(OPS[op]) | set(OPTIONAL.get(op, ()))
    missing = {"workspace", *OPS[op]} - set(req)
    need(not missing, "BAD_REQUEST", f"missing {sorted(missing)}")
    need(not set(req) - allowed, "BAD_REQUEST", f"unknown members {sorted(set(req) - allowed)}")
    _check_values(req)
    return op


def _int_at_least(low, none_ok=False):
    return lambda v: (none_ok and v is None) or (type(v) is int and v >= low)


# Each member a request may carry: its check and the refusal's message, checked in this order.
CHECKS = {**{k: (S.hex64, f"{k} is a hex64 content address") for k in ("input", "environment", "checkpoint", "state")},
          "runtime": (lambda v: isinstance(v, str) and v in RUNTIMES, "unknown runtime"),
          "credit": (_int_at_least(0), "credit is an integer >= 0"),
          "max_actions": (_int_at_least(1, none_ok=True), "max_actions is an integer >= 1"),
          "max_steps": (_int_at_least(1), "max_steps is an integer >= 1"),
          **{k: (lambda v: isinstance(v, str) and 0 < len(v) <= 10_000, f"{k} is a term, e.g. \"S K K\"")
             for k in ("expr", "expect_expr")},
          "target": (lambda v: isinstance(v, str) and 0 < len(v) <= 200, "target")}


def _check_values(req):
    """Each member the request carries has its type and bound."""
    for k, (ok, why) in CHECKS.items():
        if k in req:
            need(ok(req[k]), "BAD_REQUEST", why)


def _term(ws, provider, store, expr):
    out = _call(ws, provider, "term", {"expr": expr}, {})
    nodes = [store.put_blob(base64.b64decode(b)) for b in out["nodes"].values()]
    return {"input": out["input"], "environment": store.put_json(P.environment_doc(nodes))}


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
    if doc is None or P.environment_problem(doc) is not None:
        raise AgentError("NOT_FOUND", "the environment manifest is not in this store")
    hashes = P.environment_hashes(doc)
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
    snap = views.read_snapshot(ws, ws.store)    # read once; every byte below comes from this capture
    data = {"op": op, "provider": provider.id, "provider_accepted_by_profile": accepted}
    if op == "provider":
        data["files"] = provider.identity["files"]
    elif op == "term":
        data.update(_term(ws, provider, store, req["expr"]), runtimes=sorted({P.BOOK1, P.RICH}))
    elif op == "evaluate":
        # The receiver's own run, term -> start -> resume, under a credit: it files nothing and credits
        # nothing; Warrant credit for a filed claim is only the assessment's replay of its receipt.
        runtime = RUNTIMES[req.get("runtime", "book1")]
        t = _term(ws, provider, store, req["expr"])
        hashes, blobs = _environment(views.read_snapshot(ws, ws.store), t["environment"])
        args = {"runtime": runtime, "input": t["input"], "hashes": hashes}
        s0 = _call(ws, provider, "start", args, blobs)
        out = _call(ws, provider, "resume", dict(args, checkpoint=s0["checkpoint"], state=s0["state"],
                                                 credit=req.get("credit", EVALUATE_CREDIT)), blobs)
        seg = out.get("segment") or {}
        data.update(expr=req["expr"], runtime=runtime, input=t["input"], environment=t["environment"],
                    status=out["status"], outcome=seg.get("outcome"), result=seg.get("result"),
                    meaning="the installed provider's own run on this receiver; it files and credits nothing")
        if seg.get("checkpoint"):
            data["checkpoint"] = store.put_blob(base64.b64decode(seg["checkpoint"]))
            data["state"] = store.put_blob(base64.b64decode(seg["state"]))
        if "expect_expr" in req:
            e = _term(ws, provider, store, req["expect_expr"])
            data.update(expect_expr=req["expect_expr"], expect_input=e["input"],
                        same_normal_form=seg.get("outcome") == "NORMAL_FORM" and seg.get("result") == e["input"])
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
