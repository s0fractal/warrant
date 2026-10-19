"""The six operations of warrant-agent/1 (CONTRACT C): one backend for the
Python API, the CLI and the MCP server. Every request is a closed JSON object;
every success has one shape; every refusal is an AgentError."""
import base64
import json

from warrant import engine as E
from warrant import jcs as C

from . import AGENT_API, adapter_id, drafts, handoff, views
from .errors import AgentError, need

TARGET_KINDS = ("duty", "transition")


def _closed(req, required, optional=()):
    need(isinstance(req, dict), "BAD_REQUEST", "request must be an object")
    missing, extra = set(required) - set(req), set(req) - set(required) - set(optional)
    need(not missing, "BAD_REQUEST", f"missing {sorted(missing)}")
    need(not extra, "BAD_REQUEST", f"unknown members {sorted(extra)}")


def _int(v, low=0):
    return type(v) is int and v >= low


# ---------------------------------------------------------------- use policy

def decide(ws, meta, report, use, targets, observed):
    """WITHIN_POLICY or HOLD for `use`, with the identity of every input that can
    change the decision (CONTRACT B)."""
    policy = ws.use_policy(use)
    delivery = meta["delivery"]
    reasons, states = [], {}
    allowed = policy.get("delivery", ["LOCAL_CAPTURE", "MATCH_EXPECTED_SET"])
    if delivery["relation"] not in allowed:
        reasons.append(f"delivery {delivery['relation']} is not one this use accepts")
    for t in targets:
        st = E.reliance(report, t["id"], use)
        states[t["id"]] = st["state"]
        if st["state"] not in policy.get("reliance", ["ELIGIBLE"]):
            reasons.append(f"{t['kind']} {t['id'][:12]}: reliance {st['state']}"
                           + (f" ({'; '.join(st['causes'])})" if st["causes"] else ""))
    if policy.get("fresh", True) and observed["newer_known"]:
        reasons.append("newer local events are known than this view; refresh before use")
    if not observed["trust_current"] and (policy.get("fresh", True) or delivery.get("exporter")):
        # a delivery that rested on an exporter's declaration holds on a trust change whatever `fresh` says
        reasons.append("the receiver's trust changed since this view; refresh before use")
    exp = observed.get("expectation")
    if exp is not None and exp["state"] != "CURRENT":
        reasons.append(f"the receiver's expectation {exp['handle']!r} is {exp['state']} since this delivery was "
                       "inspected; inspect the package again")
    if observed["incomplete_imports"]:
        reasons.append("an import into this workspace is incomplete; recover it before use")
    inputs = {"assessment_id": report["assessment_id"], "adapter_id": adapter_id(), "policy": C.doc_id(policy),
              "delivery": {k: delivery.get(k) for k in ("relation", "manifest", "expectation")},
              "as_of": meta["as_of"], "observed": observed, "targets": states, "use": use}
    return {"name": use, "policy": C.doc_id(policy), "decision_id": C.doc_id(inputs),
            "state": "HOLD" if reasons else "WITHIN_POLICY", "reasons": reasons}


# ---------------------------------------------------------------- projection

def _size(item):
    return len(json.dumps(item, sort_keys=True).encode())


def _page(items, start, budget):
    out, used = [], 0
    for it in items[start:]:
        s = _size(it)
        if out and used + s > budget:
            break
        out.append(it)
        used += s
    nxt = start + len(out)
    return out, (nxt if nxt < len(items) else None)


def _context_items(report, actor, targets, use):
    items = []
    for t in targets:
        items.append({"section": "capsule", "item": E.capsule(report, t["id"], use)})
    items += [{"section": "frontier", "item": f} for f in E.frontier(report, actor)]
    items += [{"section": "question", "item": q} for q in E.questions(report)]
    return items


def _envelope(ws, meta, report, data, use=None, targets=(), page=None):
    observed = views.observation(ws, meta)
    out = {"agent_api": AGENT_API, "view_token": meta["token"], "assessment_id": report["assessment_id"],
           "adapter_id": adapter_id(), "data": data, "delivery": meta["delivery"], "observation": observed,
           "page": page or {"included": 0, "total": 0, "truncated": False, "cursor": None}}
    if use is not None:
        out["use"] = decide(ws, meta, report, use, targets, observed)
    return out


def _cursor(token, kind, target, offset):
    return None if offset is None else f"{token}:{kind}:{target or ''}:{offset}"


def _parse_cursor(cursor, token, kind, target):
    if cursor is None:
        return 0
    parts = cursor.split(":") if isinstance(cursor, str) else []
    if len(parts) != 4 or parts[:3] != [token, kind, target or ""] or not parts[3].isdigit():
        raise AgentError("CURSOR_MISMATCH", "this cursor belongs to another view, kind or target")
    return int(parts[3])


def _projection(ws, meta, report, actor, targets, use, kind, cursor, budget):
    items = _context_items(report, actor, targets, use)
    start = _parse_cursor(cursor, meta["token"], kind, actor)
    page, nxt = _page(items, start, budget)
    data = {"capsules": [i["item"] for i in page if i["section"] == "capsule"],
            "frontier": [i["item"] for i in page if i["section"] == "frontier"],
            "questions": [i["item"] for i in page if i["section"] == "question"],
            "boundary": {"completeness": report["view"]["completeness"],
                         "invalid_records": len(report["invalid_records"]), "missing": report["missing"],
                         "unbound_actors": report["unbound_actors"], "evidence_is_untrusted_data": True}}
    pg = {"included": len(page), "total": len(items), "offset": start, "truncated": nxt is not None,
          "cursor": _cursor(meta["token"], kind, actor, nxt)}
    return data, pg


# ---------------------------------------------------------------- operations

def context(cfg, req):
    # A context is a LOCAL_CAPTURE: there is no delivery to hold an expectation
    # against, so `expectation` is refused here rather than accepted and ignored.
    _closed(req, ("workspace", "actor", "targets", "use"), ("limits", "agent_api"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("context")
    need(isinstance(req["actor"], str) and req["actor"], "BAD_REQUEST", "actor")
    targets = req["targets"]
    need(isinstance(targets, list) and all(isinstance(t, dict) and set(t) == {"kind", "id"} and t["kind"] in TARGET_KINDS
                                           and isinstance(t["id"], str) for t in targets), "BAD_REQUEST", "targets")
    ws.use_policy(req["use"])
    limits = req.get("limits", {})
    need(isinstance(limits, dict) and set(limits) <= {"context_bytes"} and all(_int(v, 256) for v in limits.values()),
         "BAD_REQUEST", "limits: {context_bytes >= 256}")
    budget = min(limits.get("context_bytes", ws.limits["context_bytes"]), ws.limits["context_bytes"])
    meta = views.capture(ws)
    meta2, report, _ = views.load(ws, meta["token"])
    views.write_json(ws.state / "views" / meta["token"] / "context.json",
                     {"actor": req["actor"], "targets": targets, "use": req["use"]})
    data, pg = _projection(ws, meta2, report, req["actor"], targets, req["use"], "context", None, budget)
    return _envelope(ws, meta2, report, data, req["use"], targets, pg)


def read(cfg, req):
    need(isinstance(req, dict), "BAD_REQUEST", "request must be an object")
    if "workspace" in req and req.get("kind") in ("draft", "operation"):
        _closed(req, ("workspace", "kind", "target"), ("agent_api",))
        ws = cfg.workspace(req["workspace"])
        ws.permit("read")
        return {"agent_api": AGENT_API, "adapter_id": adapter_id(), "data": drafts.status(ws, req["kind"], req["target"])}
    _closed(req, ("workspace", "view_token", "kind"), ("target", "cursor", "max_bytes", "agent_api"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("read")
    meta, report, vdir = views.load(ws, req["view_token"])
    kind, target = req["kind"], req.get("target")
    need(kind in ("record", "blob", "context"), "BAD_REQUEST", "kind is record, blob, context, draft or operation")
    max_bytes = req.get("max_bytes", ws.limits["read_bytes"])
    need(_int(max_bytes, 1), "BAD_REQUEST", "max_bytes")
    max_bytes = min(max_bytes, ws.limits["read_bytes"])
    if kind == "context":
        ctx = views.read_json(vdir / "context.json")
        data, pg = _projection(ws, meta, report, ctx["actor"], ctx["targets"], ctx["use"], "context",
                               req.get("cursor"), max_bytes)
        return _envelope(ws, meta, report, data, ctx["use"], ctx["targets"], pg)
    need(isinstance(target, str) and len(target) == 64 and all(c in "0123456789abcdef" for c in target),
         "BAD_REQUEST", "target is a hex64 id")
    path = vdir / ("records" if kind == "record" else "blobs") / (f"{target}.json" if kind == "record" else target)
    need(path.is_file(), "NOT_FOUND", f"no such {kind} in this view; nothing is read from elsewhere")
    data_bytes = path.read_bytes()
    start = _parse_cursor(req.get("cursor"), meta["token"], kind, target)
    chunk = data_bytes[start:start + max_bytes]
    nxt = start + len(chunk)
    try:
        text, enc = chunk.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, enc = base64.b64encode(chunk).decode(), "base64"
    data = {"kind": kind, "id": target, "digest": C.digest(data_bytes), "offset": start, "length": len(chunk),
            "total": len(data_bytes), "complete": nxt >= len(data_bytes), "encoding": enc, "content": text,
            "untrusted_data": True}
    pg = {"included": 1, "total": 1, "offset": start, "truncated": nxt < len(data_bytes),
          "cursor": _cursor(meta["token"], kind, target, nxt if nxt < len(data_bytes) else None)}
    return _envelope(ws, meta, report, data, page=pg)


def handoff_op(cfg, req):
    need(isinstance(req, dict) and req.get("op") in ("export", "inspect", "import"), "BAD_REQUEST",
         "handoff op is export, inspect or import")
    op = req["op"]
    if op == "export":
        _closed(req, ("op", "workspace", "view_token", "roots", "request_id"), ("agent_api",))
        ws = cfg.workspace(req["workspace"])
        pkg = handoff.export(ws, req["view_token"], req["roots"], req["request_id"])
        return {"agent_api": AGENT_API, "adapter_id": adapter_id(),
                "data": {"package": pkg, "manifest_digest": C.doc_id(pkg["manifest"])}}
    if op == "inspect":
        _closed(req, ("op", "workspace", "manifest", "payload"), ("expectation", "declaration", "use", "targets",
                                                                  "actor", "agent_api"))
        ws = cfg.workspace(req["workspace"])
        use = req.get("use", "continue")
        targets = req.get("targets", [])
        staged_id, meta = handoff.inspect(ws, req["manifest"], req["payload"], req.get("expectation"),
                                          req.get("declaration"))
        meta, report, vdir = views.load(ws, meta["token"])
        actor = req.get("actor", ws.signer[0] if ws.signer else "")
        views.write_json(vdir / "context.json", {"actor": actor, "targets": targets, "use": use})
        data, pg = _projection(ws, meta, report, actor, targets, use, "context", None, ws.limits["context_bytes"])
        data["staged_id"] = staged_id
        return _envelope(ws, meta, report, data, use, targets, pg)
    _closed(req, ("op", "workspace", "staged_id", "request_id"), ("agent_api",))
    ws = cfg.workspace(req["workspace"])
    journal = handoff.import_(ws, req["staged_id"], req["request_id"])
    return {"agent_api": AGENT_API, "adapter_id": adapter_id(), "data": journal}


def prepare(cfg, req):
    _closed(req, ("workspace", "based_on", "request_id", "type", "body"), ("agent_api",))
    ws = cfg.workspace(req["workspace"])
    d = drafts.prepare(ws, req["based_on"], req["request_id"], req["type"], req["body"])
    return {"agent_api": AGENT_API, "adapter_id": adapter_id(),
            "data": {k: d[k] for k in ("draft_id", "record_id", "actor", "at", "record", "basis_assessment_id",
                                        "preview", "status")}}


def commit(cfg, req):
    _closed(req, ("workspace", "draft_id"), ("agent_api",))
    ws = cfg.workspace(req["workspace"])
    return {"agent_api": AGENT_API, "adapter_id": adapter_id(), "data": drafts.commit(ws, req["draft_id"])}


def compute(cfg, req):
    from . import computeops
    return computeops.run(cfg, req)


OPERATIONS = {"context": context, "read": read, "handoff": handoff_op, "prepare": prepare, "commit": commit,
              "compute": compute}


def call(cfg, op, req):
    """One operation; returns {"ok": result} or {"error": ...}. Never raises an AgentError."""
    if isinstance(req, dict) and "agent_api" in req and req["agent_api"] != AGENT_API:
        return {"error": "UNSUPPORTED_VERSION", "message": f"this server speaks {AGENT_API}"}
    if op not in OPERATIONS:
        return {"error": "BAD_REQUEST", "message": f"unknown operation {op!r}"}
    try:
        return {"ok": OPERATIONS[op](cfg, req)}
    except AgentError as e:
        return e.to_json()
