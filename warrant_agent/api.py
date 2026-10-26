"""The operations of warrant-agent/1 (CONTRACT C): one backend for the
Python API, the CLI and the MCP server. Every request is a closed JSON object;
every success has one shape; every refusal is an AgentError."""
import base64
import json

from warrant import engine as E
from warrant import jcs as C
from warrant import shapes as S
from warrant.store import code_identity

from . import AGENT_API, adapter_id, drafts, graph, handoff, views
from .errors import AgentError, need, need_op

TARGET_KINDS = ("duty", "transition")
CONTEXT_FILE = "context.json"          # a view's actor, targets and use, written by the call that made it


def _record_shape(data):
    """The record inside stored envelope bytes if it has the shape these reports read (an object whose
    `type` is a string and whose `body` is an object), else None. The bytes are untrusted: they may be
    exactly what the engine rejected, so nothing below dereferences a record this did not return."""
    try:
        env = C.loads(data)
    except (C.NotCanonical, ValueError, TypeError):
        return None
    rec = env.get("record") if isinstance(env, dict) else None
    if isinstance(rec, dict) and isinstance(rec.get("type"), str) and isinstance(rec.get("body"), dict):
        return rec
    return None
TARGET_FORMS = ("targets is a list; each target is a record id (hex64) of a duty or transition, "
                "{\"id\": id} or {\"kind\": \"duty\"|\"transition\", \"id\": id}")


def _target_shapes(raw):
    """The request's targets as [(kind or None, id)]; the shape is checked before anything is read."""
    need(isinstance(raw, list), "BAD_REQUEST", TARGET_FORMS)
    out = []
    for t in raw:
        if isinstance(t, str):
            t = {"id": t}
        need(isinstance(t, dict) and set(t) in ({"id"}, {"kind", "id"}) and S.hex64(t["id"])
             and t.get("kind", "duty") in TARGET_KINDS, "BAD_REQUEST", TARGET_FORMS)
        out.append((t.get("kind"), t["id"]))
    return out


def _kind_in_view(tid, report, view):
    """A duty or a transition of THIS view; any other id is refused by what it is, never shown as a capsule of
    something else."""
    if tid in report["duties"]:
        return "duty"
    if tid in report["results"]:
        return "transition"
    data = view.record(tid)
    if data is None:
        raise AgentError("NOT_FOUND", f"{tid[:12]} is not a record of this view", target=tid)
    rec = _record_shape(data)
    rtype = rec["type"] if rec else "unreadable"
    raise AgentError("BAD_REQUEST", f"{tid[:12]} is a record of type {rtype} in this view, not a duty or a "
                     "transition; read it with warrant_read", target=tid, type=rtype)


def _resolve_targets(shapes, report, view):
    """[{kind, id}]: a target given without its kind is resolved in the view; a given kind is kept as given."""
    return [{"kind": kind or _kind_in_view(tid, report, view), "id": tid} for kind, tid in shapes]


def _use(ws, use):
    """The named use, or the operator's first configured use when none is named."""
    if use is None:
        need(bool(ws.uses), "BAD_REQUEST", "this workspace configures no use")
        return next(iter(ws.uses))
    need(isinstance(use, str) and use in ws.uses, "BAD_REQUEST",
         f"use {use!r} is not configured; configured uses: {', '.join(ws.uses) or 'none'}", configured=list(ws.uses))
    return use


def _actor(ws, actor):
    """The named actor (whose frontier is read), or the configured signer's actor."""
    if actor is None:
        need(ws.signer is not None, "BAD_REQUEST", "actor: this workspace has no signer to default to")
        return ws.signer[0]
    need(S.is_actor(actor), "BAD_REQUEST", "actor: not an actor id (SPEC §3)")
    return actor


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


CLOSURE = ("transition", "item", "act", "filer", "basis", "verdict", "why", "waiting_for", "awaiting")


def _reading(cap):
    """One line over the capsule's own fields; it adds no judgement of its own."""
    if cap["reliance"] == "ELIGIBLE":
        head = (f"ELIGIBLE: this receiver's assessment of this view lets use {cap['use']!r} rely on it "
                "(completeness of the source stays UNATTESTED)")
    else:
        head = f"{cap['reliance']}: not established for use {cap['use']!r}: " + "; ".join(cap["revisit_because"] or ["-"])
    if cap.get("kind") == "transition" and cap.get("closes"):
        # A transition's own reliance is about its results; what it closes is decided on each duty.
        head += ". Its items, as this receiver assessed them: " + "; ".join(
            f"item {c['item']} ({c['act']}) of duty {c['statement']!r}: {c['verdict']}"
            + (f" ({c['why']})" if c.get("why") else "") + f", duty {c['duty_disposition']}" for c in cap["closes"])
    elif cap.get("kind") == "duty" and cap["reliance"] != "ELIGIBLE" and cap.get("closures"):
        head += ". Closure attempts: " + "; ".join(
            f"{c['filer']} (transition {c['transition'][:12]} item {c['item']}): {c['verdict']}"
            + (f" ({c['why']})" if c.get("why") else "") for c in cap["closures"])
    return head


def _capsule(report, tid, use):
    """The engine's capsule plus, from the same report, every closure attempt with its verdict and why."""
    cap = E.capsule(report, tid, use)
    if tid in report["duties"]:
        cap["closures"] = [{k: c[k] for k in CLOSURE if k in c} for c in report["duties"][tid]["candidates"]]
    elif tid in report["results"]:
        cap["closes"] = [dict({k: c[k] for k in CLOSURE if k in c and k != "transition"}, duty=did,
                              statement=d["statement"], duty_disposition=d["disposition"])
                         for did, d in sorted(report["duties"].items()) for c in d["candidates"]
                         if c["transition"] == tid]
    cap["reading"] = _reading(cap)
    return cap


def _context_items(report, actor, targets, use, scope=None):
    """Capsules, then the actor's frontier and the unowned questions; with a `scope`, every question of that
    scope, owned or not (the engine's `owned`, `taken_by`), before the frontier: a goal an obligation answers
    is found by its scope however long the frontier is."""
    items = [{"section": "capsule", "item": _capsule(report, t["id"], use)} for t in targets]
    if scope is not None:
        items += [{"section": "question", "item": q} for q in E.questions(report, scope=scope, owned=True)]
    items += [{"section": "frontier", "item": f} for f in E.frontier(report, actor)]
    if scope is None:
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


def _invalid(view, rid, why):
    """An invalid record of the view, with what its bytes claim to be (untrusted: it does not authenticate)
    when they have a record's shape at all."""
    out = {"id": rid, "why": why}
    data = view.record(rid)
    rec = None if data is None else _record_shape(data)
    if rec is not None:
        b = rec["body"]
        out["claims_to_be"] = {"type": rec["type"], "actor": rec.get("actor") if isinstance(rec.get("actor"), str) else None,
                               **{k: b[k] for k in ("transition", "target", "item") if k in b}}
    return out


def _projection(view, meta, report, actor, targets, use, kind, cursor, budget, scope=None):
    items = _context_items(report, actor, targets, use, scope)
    start = _parse_cursor(cursor, meta["token"], kind, actor)
    page, nxt = _page(items, start, budget)
    data = {"capsules": [i["item"] for i in page if i["section"] == "capsule"],
            "frontier": [i["item"] for i in page if i["section"] == "frontier"],
            "questions": [i["item"] for i in page if i["section"] == "question"],
            "boundary": {"completeness": report["view"]["completeness"],
                         "invalid_records": len(report["invalid_records"]),
                         "invalid": [_invalid(view, i, w) for i, w in sorted(report["invalid_records"].items())][:20],
                         "missing": report["missing"],
                         "unbound_actors": report["unbound_actors"], "evidence_is_untrusted_data": True}}
    pg = {"included": len(page), "total": len(items), "offset": start, "truncated": nxt is not None,
          "cursor": _cursor(meta["token"], kind, actor, nxt)}
    return data, pg


# ---------------------------------------------------------------- operations

def context(cfg, req):
    # A context is a LOCAL_CAPTURE: there is no delivery to hold an expectation
    # against, so `expectation` is refused here rather than accepted and ignored.
    _closed(req, ("workspace",), ("actor", "targets", "use", "limits", "scope", "agent_api"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("context")
    actor, use = _actor(ws, req.get("actor")), _use(ws, req.get("use"))
    scope = req.get("scope")
    need(scope is None or (isinstance(scope, str) and 0 < len(scope) <= 200), "BAD_REQUEST",
         "scope is a question scope, a string of 1 to 200 characters")
    shapes = _target_shapes(req.get("targets", []))
    limits = req.get("limits", {})
    need(isinstance(limits, dict) and set(limits) <= {"context_bytes"} and all(_int(v, 256) for v in limits.values()),
         "BAD_REQUEST", "limits: {context_bytes >= 256}")
    budget = min(limits.get("context_bytes", ws.limits["context_bytes"]), ws.limits["context_bytes"])
    meta = views.capture(ws)
    meta2, report, view = views.load(ws, meta["token"])
    targets = _resolve_targets(shapes, report, view)
    views.write_json(view.dir / CONTEXT_FILE, {"actor": actor, "targets": targets, "use": use, "scope": scope})
    data, pg = _projection(view, meta2, report, actor, targets, use, "context", None, budget, scope)
    return _envelope(ws, meta2, report, data, use, targets, pg)


def read(cfg, req):
    need(isinstance(req, dict), "BAD_REQUEST", "request must be an object")
    if "workspace" in req and req.get("kind") in ("draft", "operation"):
        _closed(req, ("workspace", "kind", "target"), ("agent_api",))
        ws = cfg.workspace(req["workspace"])
        ws.permit("read")
        return {"agent_api": AGENT_API, "adapter_id": adapter_id(), "data": drafts.status(ws, req["kind"], req["target"])}
    _closed(req, ("workspace",), ("view_token", "kind", "target", "cursor", "max_bytes", "agent_api"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("read")
    kind, target = req.get("kind", "record"), req.get("target")
    need(kind in ("record", "blob", "context"), "BAD_REQUEST", "kind is record, blob, context, draft or operation")
    if req.get("view_token") is None:
        # No view named: a record or blob is read from a new frozen view (returned as view_token), never
        # from the live store; a context page belongs to the view that made it.
        need(kind != "context", "BAD_REQUEST", "a context page needs the view_token of warrant_context")
        need(req.get("cursor") is None, "BAD_REQUEST", "a cursor belongs to the view_token it came with")
        req = dict(req, view_token=views.capture(ws)["token"])
    meta, report, view = views.load(ws, req["view_token"])
    max_bytes = req.get("max_bytes", ws.limits["read_bytes"])
    need(_int(max_bytes, 1), "BAD_REQUEST", "max_bytes")
    max_bytes = min(max_bytes, ws.limits["read_bytes"])
    if kind == "context":
        ctx = views.read_json(view.dir / CONTEXT_FILE)
        data, pg = _projection(view, meta, report, ctx["actor"], ctx["targets"], ctx["use"], "context",
                               req.get("cursor"), max_bytes, ctx.get("scope"))
        return _envelope(ws, meta, report, data, ctx["use"], ctx["targets"], pg)
    need(isinstance(target, str) and len(target) == 64 and all(c in "0123456789abcdef" for c in target),
         "BAD_REQUEST", "target is a hex64 id")
    data_bytes = view.record(target) if kind == "record" else view.blob(target)
    need(data_bytes is not None, "NOT_FOUND", f"no such {kind} in this view; nothing is read from elsewhere")
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


def _view(ws, token):
    """The named view, or a new frozen view of the workspace when none is named."""
    return views.load(ws, views.capture(ws)["token"] if token is None else token)


def _export(cfg, req):
    _closed(req, ("op", "workspace"), ("view_token", "roots", "request_id", "agent_api"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("handoff")
    meta, report, view = _view(ws, req.get("view_token"))
    if "roots" in req:
        roots = _resolve_targets(_target_shapes(req["roots"]), report, view)
    else:                                       # the targets of the context that made the view, if any
        ctx = view.dir / CONTEXT_FILE
        roots = views.read_json(ctx)["targets"] if ctx.is_file() else []
    request_id = req.get("request_id") or f"export:{meta['token']}:{C.doc_id(roots)[:32]}"
    pkg = handoff.export(ws, meta["token"], roots, request_id)
    return {"agent_api": AGENT_API, "adapter_id": adapter_id(),
            "data": {"package": pkg, "manifest_digest": C.doc_id(pkg["manifest"]), "request_id": request_id}}


def _unpack(req):
    """A package given in one piece (the exported object as it was received) as manifest/payload/declaration."""
    if "package" not in req:
        return req
    pkg = req["package"]
    need(isinstance(pkg, dict) and {"manifest", "payload"} <= set(pkg)
         and set(pkg) <= {"manifest", "manifest_bytes", "payload", "declaration"}
         and not ({"manifest", "payload", "declaration"} & set(req)), "BAD_REQUEST",
         "package is the exported object {manifest, payload, declaration?, manifest_bytes?}, given instead of "
         "manifest/payload/declaration")
    return dict({k: v for k, v in req.items() if k != "package"}, manifest=pkg["manifest"],
                payload=pkg["payload"], **({"declaration": pkg["declaration"]} if "declaration" in pkg else {}))


def _inspect(cfg, req):
    _closed(req, ("op", "workspace"), ("package", "manifest", "payload", "expectation", "declaration", "use",
                                       "targets", "actor", "agent_api"))
    req = _unpack(req)
    need("manifest" in req and "payload" in req, "BAD_REQUEST", "inspect needs package, or manifest and payload")
    ws = cfg.workspace(req["workspace"])
    use, actor = _use(ws, req.get("use")), _actor(ws, req.get("actor"))
    shapes = _target_shapes(req["targets"]) if "targets" in req else None
    staged_id, meta = handoff.inspect(ws, req["manifest"], req["payload"], req.get("expectation"),
                                      req.get("declaration"))
    meta, report, view = views.load(ws, meta["token"])
    if shapes is None:                          # the package's own roots, read from its checked manifest
        shapes = [(r["kind"], r["id"]) for r in req["manifest"]["roots"]]
    targets = _resolve_targets(shapes, report, view)
    views.write_json(view.dir / CONTEXT_FILE, {"actor": actor, "targets": targets, "use": use})
    data, pg = _projection(view, meta, report, actor, targets, use, "context", None, ws.limits["context_bytes"])
    data["staged_id"] = staged_id
    return _envelope(ws, meta, report, data, use, targets, pg)


def _import(cfg, req):
    _closed(req, ("op", "workspace", "staged_id"), ("request_id", "agent_api"))
    ws = cfg.workspace(req["workspace"])
    journal = handoff.import_(ws, req["staged_id"], req.get("request_id") or f"import:{req['staged_id']}")
    return {"agent_api": AGENT_API, "adapter_id": adapter_id(), "data": journal}


HANDOFF_OPS = {"export": _export, "inspect": _inspect, "import": _import}


def handoff_op(cfg, req):
    return HANDOFF_OPS[need_op(req, HANDOFF_OPS, "handoff op is export, inspect or import")](cfg, req)


def prepare(cfg, req):
    _closed(req, ("workspace", "type", "body"), ("based_on", "request_id", "blobs", "agent_api"))
    ws = cfg.workspace(req["workspace"])
    d = drafts.prepare(ws, req.get("based_on"), req.get("request_id"), req["type"], req["body"], req.get("blobs"))
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


INDEX_ROWS = 50


def _summary(rec):
    """A short text of a duty or transition record (its statement or first established line)."""
    b = rec["body"]
    for k in ("statement", "established"):
        v = b.get(k)
        if isinstance(v, str):
            return v[:200]
        if isinstance(v, list) and v:
            return str(v[0])[:200]
    return ""


def _workspace_view(ws):
    """What an agent needs to start: the operator's handles and choices by name, never a path, a key or a URL,
    and an index of the duties and transitions in the live store (untrusted text, not an assessment)."""
    from warrant import compute as P
    try:
        prov = P.Provider.capture()
        provider = {"installed": True, "id": prov.id, "accepted_by_profile": prov.id in ws.profile().get("providers", [])}
    except P.ProviderError:                   # absent or broken provider: say so, nothing else
        provider = {"installed": False, "id": None, "accepted_by_profile": False}
    snap = views.read_snapshot(ws, ws.store)
    # only records that authenticate under the receiver's trust are indexed; the rest are counted, never read
    good, bad = snap.authentic(ws.trust())
    rows, by_type = [], {}
    for rid, rec in good.items():
        by_type[rec["type"]] = by_type.get(rec["type"], 0) + 1
        if rec["type"] in TARGET_KINDS:
            rows.append({"id": rid, "type": rec["type"], "actor": rec["actor"], "at": rec["at"],
                         "text": _summary(rec)})
    rows.sort(key=lambda r: (-r["at"], r["id"]))
    return {"name": ws.name, "signer": ws.signer[0] if ws.signer else None, "operations": list(ws.operations),
            "uses": ws.uses, "default_use": next(iter(ws.uses), None),
            "expectations": {h: {k: e[k] for k in ("manifest", "source", "exporter") if k in e}
                             for h, e in ws.expectations.items()},
            "provider": provider,
            "store": {"records": len(snap.records), "blobs": len(snap.blobs), "by_type": by_type,
                      "invalid_records": len(bad)},
            "index": {"rows": rows[:INDEX_ROWS], "total": len(rows), "truncated": len(rows) > INDEX_ROWS,
                      "untrusted_data": True, "assessed": False}}


# ---------------------------------------------------------------- the record graph (graph.py)

GRAPH_OPS = {"path": ("target",), "frontier": (), "impact": ("base_view_token",), "delta": ("base_view_token",),
             "export": ()}
GRAPH_OPTIONAL = {"frontier": ("actor",), "export": ("format",)}


def _graph_items(op, ws, g, report, req, base):
    """[{section, ...}] of one graph operation over `g` (and the base view's graph `base`)."""
    if op == "path":
        try:
            d = graph.path(g, req["target"])
        except graph.Unknown as e:
            raise AgentError("NOT_FOUND", str(e), target=str(req["target"])[:200]) from None
        return ({"target": d["target"], "kind": d["kind"], "open": d["open"]},
                [dict(q, section="question") for q in d["questions"]] + [dict(x, section="duty") for x in d["duties"]])
    if op == "frontier":
        actor = _actor(ws, req.get("actor"))
        items = graph.frontier(report, actor)
        return {"actor": actor, "open": len(items)}, [dict(x, section="need") for x in items]
    if op == "impact":
        d = graph.impact(base, g)
        rows = ([{"section": "record", "change": c, "id": r} for c in ("added", "removed") for r in d["records"][c]]
                + [dict(x, section="duty") for x in d["duties"]] + [dict(q, section="question") for q in d["questions"]])
        return {"records_added": len(d["records"]["added"]), "records_removed": len(d["records"]["removed"]),
                "duties": len(d["duties"]), "questions": len(d["questions"])}, rows
    if op == "delta":
        d = graph.delta(base, g)
        return dict(d["counts"], **{"from": d["from"], "to": d["to"]}), (
            [dict(x, section="node") for x in d["nodes"]] + [dict(x, section="edge") for x in d["edges"]])
    fmt = req.get("format", "json")
    need(fmt in ("json", "dot"), "BAD_REQUEST", "export format is json or dot")
    if fmt == "dot":
        return {"format": "dot", "nodes": len(g["nodes"]), "edges": len(g["edges"])}, [
            {"section": "dot", "line": line} for line in graph.dot(g).splitlines()]
    return {"format": "json", "graph": g["graph"], "nodes": len(g["nodes"]), "edges": len(g["edges"])}, (
        [dict(n, section="node") for n in g["nodes"]] + [dict(e, section="edge") for e in g["edges"]])


def graph_op(cfg, req):
    """The record graph of a frozen view (graph.py): `path` to a target, the actor's `frontier`, the `impact`
    and `delta` of a base view to this one, or the whole graph (`export`, json or dot). Permitted wherever `read`
    is; every state shown is the view's report; pages by bytes, continued by a cursor bound to the view and the
    request."""
    op = need_op(req, GRAPH_OPS, f"graph op is one of {', '.join(GRAPH_OPS)}")
    need(op != "path" or isinstance(req.get("target"), str), "BAD_REQUEST",
         "path's target is a duty id or prefix, a question reference or a question scope (a string)")
    _closed(req, ("op", "workspace") + GRAPH_OPS[op],
            ("view_token", "cursor", "max_bytes", "agent_api") + GRAPH_OPTIONAL.get(op, ()))
    ws = cfg.workspace(req["workspace"])
    ws.permit("read")
    max_bytes = req.get("max_bytes", ws.limits["context_bytes"])
    need(_int(max_bytes, 256), "BAD_REQUEST", "max_bytes >= 256")
    budget = min(max_bytes, ws.limits["context_bytes"])
    need(req.get("cursor") is None or req.get("view_token") is not None, "BAD_REQUEST",
         "a cursor belongs to the view_token it came with")
    meta, report, view = _view(ws, req.get("view_token"))
    g = graph.build(view.snapshot(), report)
    base = None
    if op in ("impact", "delta"):
        _, report0, view0 = views.load(ws, req["base_view_token"])
        base = graph.build(view0.snapshot(), report0)
    summary, items = _graph_items(op, ws, g, report, req, base)
    # root: what the result was computed from (the view's snapshot and time, and the base view's); lens: everything
    # else that decides it (this package and the engine's code, the view's trust and profile, the query).
    reports = [report] if base is None else [report0, report]
    root = graph.root_part(report) if base is None else {"base": graph.root_part(report0), "head": graph.root_part(report)}
    query = {k: v for k, v in req.items() if k not in ("workspace", "view_token", "base_view_token", "cursor",
                                                        "max_bytes", "agent_api")}
    query.update({k: summary[k] for k in ("actor", "format") if k in summary})       # the defaults as resolved
    lens = graph.lens_id({"agent": adapter_id(), "engine": code_identity()}, [graph.operands(r) for r in reports], query)
    # The cursor names the view, the operation and a digest of the request's other members: a page of one
    # request is never read as a page of another. view_token is left out of the digest: the cursor names the view
    # already, and a first page read without one is continued with the token it returned (Codex 51541256eeb7).
    key = C.digest(C.canon({k: v for k, v in req.items()
                            if k not in ("cursor", "max_bytes", "agent_api", "view_token")}))[:16]
    start = _parse_cursor(req.get("cursor"), meta["token"], f"graph-{op}", key)
    page, nxt = _page(items, start, budget)
    data = {"op": op, "summary": summary, "items": page, "root": root, "lens": lens, "untrusted_data": True}
    more = nxt is not None
    pg = {"included": len(page), "total": len(items), "offset": start, "truncated": more,
          "cursor": _cursor(meta["token"], f"graph-{op}", key, nxt)}
    return _envelope(ws, meta, report, data, page=pg)


def workspace(cfg, req):
    _closed(req, (), ("workspace", "agent_api"))
    names = [req["workspace"]] if "workspace" in req else sorted(cfg.workspaces)
    return {"agent_api": AGENT_API, "adapter_id": adapter_id(),
            "data": {"workspaces": [_workspace_view(cfg.workspace(n)) for n in names]}}


def explain(cfg, req):
    from . import glossary
    _closed(req, ("term",), ("agent_api",))
    need(isinstance(req["term"], str), "BAD_REQUEST", "term")
    return {"agent_api": AGENT_API, "adapter_id": adapter_id(), "data": glossary.explain(req["term"])}


OPERATIONS = {"context": context, "read": read, "handoff": handoff_op, "prepare": prepare, "commit": commit,
              "compute": compute, "workspace": workspace, "explain": explain, "graph": graph_op}


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
