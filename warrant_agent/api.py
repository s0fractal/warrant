"""The one backend of warrant-agent/3: `call(cfg, op, request)` -> {"ok": result} or {"error": code, ...}.

Every operation that reads records reads the store once and assesses it in process (warrant.assess)
under the workspace's trust and profile: the store is admitted by size first (the workspace's
`store_bytes`), then by the engine's LIMITS, whose nesting bound keeps the assessment off the
interpreter's stack limit. Nothing is cached and no view is kept between calls.

  workspace  {workspace?}                              the configuration by name and a summary of each store
  context    {workspace, targets?, actor?}             per target: its node, lineage, guard, challenges and the
                                                       attests on it; the actor's frontier (default: the signer)
  read       {workspace, target, kind?, offset?, max_bytes?}   a record's line or a blob's bytes, chunked
  graph      {workspace, op, target?, actor?}          around | path | why | frontier | export, with root and lens
  handoff    {workspace, op, targets?|package}         export the records targets rest on and the verdicts on
                                                       them; inspect a package under this receiver's terms
                                                       (alone or with its store); import one (add-only)
  prepare    {workspace, kind, schema?, body, target?, lineage?, refs?, guard?}   an unsigned record of the
                                                       signer, checked as this receiver would read it
  commit     {workspace, record}                       sign it as the configured signer and append it, a
                                                       compare-and-swap on the signer's chain head (record.prev)
  explain    {word}                                    the static glossary

The signer is the operator's configuration: no request names a key, a path or another actor, and the
seed is read only by commit. A record the engine would reject or list as a problem, or after which it would
refuse the store, is refused at prepare and at commit, never filed: both assess the store with it (_refusals)."""
import base64
import json
import os
import time

from warrant import engine as E
from warrant import jcs as C
from warrant import keys as K
from warrant import records as R
from warrant import shapes as S
from warrant.store import Refused, Snapshot

from . import AGENT_API, adapter_id
from . import glossary as GL
from . import graph as G
from .config import OPERATIONS
from .errors import CODES, AgentError, need

PACKAGE = "package/3"
GRAPH_OPS = ("around", "path", "why", "frontier", "export")
HANDOFF_OPS = ("export", "inspect", "import")


def _closed(req, required, optional=()):
    need(isinstance(req, dict), "BAD_REQUEST", "a request is a JSON object")
    extra, missing = set(req) - set(required) - set(optional) - {"workspace"}, set(required) - set(req)
    need(not extra and not missing, "BAD_REQUEST", f"unknown members {sorted(extra)} or missing {sorted(missing)}")


def _assess(ws, snap=None):
    trust, profile = ws.receiver()
    try:
        snap = snap if snap is not None else ws.open().snapshot()
        return snap, E.View(snap, trust, profile), trust, profile
    except Refused as e:
        raise AgentError("RESOURCE_LIMIT" if "limit" in str(e) else "REFUSED", str(e)) from None
    except R.Invalid as e:
        raise AgentError("RESOURCE_LIMIT" if "limit" in str(e) else "BAD_REQUEST", str(e)) from None


def _resolve(snap, target):
    """A record or blob id from a full id or a unique prefix of at least 8 hex characters."""
    need(isinstance(target, str) and 8 <= len(target) <= 64 and all(c in "0123456789abcdef" for c in target),
         "BAD_REQUEST", "a target is a record or blob id, or a prefix of at least 8 lowercase hex characters")
    ids = [i for i in list(snap.lines) + list(snap.blobs) if i.startswith(target)]
    need(len(set(ids)) == 1, "NOT_FOUND", f"{target} names {len(set(ids))} records or blobs here")
    return ids[0]


def _budget(out, limit):
    data = json.dumps(out, sort_keys=True).encode()
    need(len(data) <= limit, "RESOURCE_LIMIT", f"the result is {len(data)} bytes; this workspace answers {limit} "
         "(name fewer targets, or read one)")
    return out


def _header(rep):
    return {k: rep[k] for k in ("assessment", "snapshot", "trust", "profile", "as_of", "code", "completeness",
                                "canonical", "basis")} | {"adapter": adapter_id(), "agent_api": AGENT_API,
                                                          "rejected": len(rep["rejected"]), "problems": len(rep["problems"])}


def _signer(ws):
    need(ws.signer is not None, "NO_SIGNER", f"workspace {ws.name!r} has no signer")
    return ws.signer[0]


# ---------------------------------------------------------------- operations

def workspace(cfg, req):
    _closed(req, (), ("workspace",))
    names = [cfg.workspace(req["workspace"]).name] if "workspace" in req else sorted(cfg.workspaces)
    out = []
    for n in names:
        ws = cfg.workspace(n)
        _, view, _, profile = _assess(ws)
        rep = view.report()
        counts = {}
        for lin in rep["lineages"].values():
            key = f"{lin['schema']} {lin['state']}"
            counts[key] = counts.get(key, 0) + 1
        out.append({"workspace": n, "signer": ws.signer[0] if ws.signer else None,
                    "operations": sorted(set(ws.operations) | {"workspace", "explain"}),
                    "roles": sorted(r for r, a in profile["roles"].items() if ws.signer and ws.signer[0] in a),
                    "schemas": rep["schemas"], "lineages": dict(sorted(counts.items())), **_header(rep)})
    return {"workspaces": out}


def context(cfg, req):
    _closed(req, ("workspace",), ("targets", "actor"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("context")
    snap, view, _, profile = _assess(ws)
    rep = view.report()
    targets = req.get("targets") or []
    need(isinstance(targets, list) and len(targets) <= 64, "BAD_REQUEST", "targets is a list of at most 64 ids")
    nodes, _, into = G.index(rep)
    caps = {}
    for t in targets:
        i = _resolve(snap, t)
        cap = G.describe(rep, nodes, i)
        if i in view.recs:
            cap["record"] = view.recs[i]
        cap["attests"] = sorted(a for rel, a in into.get(i, []) if rel == "attest")
        cap["challenges"] = {c: rep["challenges"][c] for rel, c in into.get(i, []) if rel == "challenge"}
        if i in rep["rejected"]:
            cap["rejected"] = rep["rejected"][i]
        caps[i] = cap
    actor = req.get("actor") or (ws.signer[0] if ws.signer else None)
    need(actor is None or S.is_actor(actor), "BAD_REQUEST", "actor is an actor id")
    out = {**_header(rep), "targets": caps, "frontier": G.frontier(rep, profile, actor) if actor else None}
    return _budget(out, ws.limits["context_bytes"])


def read(cfg, req):
    _closed(req, ("workspace", "target"), ("kind", "offset", "max_bytes"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("read")
    snap = ws.open().snapshot()
    kind = req.get("kind", "record")
    need(kind in ("record", "blob"), "BAD_REQUEST", "kind is record or blob")
    i = _resolve(snap, req["target"])
    if kind == "record":
        need(i in snap.lines, "NOT_FOUND", f"{i[:12]} is not a record")
        data = b"".join(sorted({C.canon(e) + b"\n" for e in snap.lines[i]}))
    else:
        need(i in snap.blobs, "NOT_FOUND", f"{i[:12]} is not a blob")
        data = snap.blobs[i]
    off, size = req.get("offset", 0), min(req.get("max_bytes", ws.limits["read_bytes"]), ws.limits["read_bytes"])
    need(isinstance(off, int) and off >= 0 and isinstance(size, int) and size > 0, "BAD_REQUEST", "offset >= 0, max_bytes > 0")
    chunk = data[off:off + size]
    try:
        text, enc = chunk.decode(), "utf-8"
    except UnicodeDecodeError:
        text, enc = base64.b64encode(chunk).decode(), "base64"
    return {"id": i, "kind": kind, "size": len(data), "offset": off, "encoding": enc, "content": text,
            "next": off + len(chunk) if off + len(chunk) < len(data) else None, "untrusted": True}


def graph(cfg, req):
    _closed(req, ("workspace", "op"), ("target", "actor"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("graph")
    op = req["op"]
    need(isinstance(op, str) and op in GRAPH_OPS, "BAD_REQUEST", f"op is one of {list(GRAPH_OPS)}")
    snap, view, _, profile = _assess(ws)
    rep = view.report()
    if op in ("around", "path", "why"):
        i = _resolve(snap, req.get("target"))
        data = getattr(G, op)(rep, i)
        query = {"op": op, "target": i}
    elif op == "frontier":
        actor = req.get("actor") or _signer(ws)
        need(S.is_actor(actor), "BAD_REQUEST", "actor is an actor id")
        data, query = G.frontier(rep, profile, actor), {"op": op, "actor": actor}
    else:
        data, query = rep["graph"], {"op": op}
    return _budget(G.answer(rep, query, data, adapter_id()), max(ws.limits["context_bytes"], ws.limits["read_bytes"]) * 16)


# ---------------------------------------------------------------- handoff

def _package_of(snap, view, rep, roots):
    keep = set()
    for r in roots:               # a version brings its whole lineage, and everything each version rests on
        root = G.lineage_of(rep, r)
        for x in [r] + (rep["lineages"][root]["versions"] if root else []):
            keep |= {x} | {n["id"] for n in G.path(rep, x)["nodes"]}
    _, _, into = G.index(rep)
    keep |= {i for i, r in view.recs.items() if r["kind"] == "schema" or r["schema"] == R.MIGRATION}
    # A fixpoint, not one pass: every kept record brings the attests and challenges on it, and each of those brings
    # what it rests on and, in turn, the verdicts on it (a replayer's `reproduces` on a challenge; an acceptance of a
    # schema). Bounded by the snapshot, itself within the workspace's store_bytes. (Codex AMEND 1 on #220: one pass
    # left out the replay that made a challenge count, and the receiver read CHALLENGED as ELIGIBLE.)
    todo = sorted(keep)
    while todo:
        for rel, a in into.get(todo.pop(), []):
            if rel in ("attest", "challenge") and a not in keep:
                new = ({a} | {n["id"] for n in G.path(rep, a)["nodes"]}) - keep
                keep |= new
                todo += sorted(new)
    lines = sorted({C.canon(e).decode() for i in keep if i in snap.lines for e in snap.lines[i]})
    blobs = {h: base64.b64encode(snap.blobs[h]).decode() for i in keep if i in view.recs
             for h in view.recs[i]["refs"] if h in snap.blobs}
    blobs |= {view.recs[i]["body"]["target"]: base64.b64encode(snap.blobs[view.recs[i]["body"]["target"]]).decode()
              for i in keep if i in view.recs and view.recs[i]["schema"] == R.MIGRATION
              and view.recs[i]["body"]["target"] in snap.blobs}
    return {"warrant": PACKAGE, "roots": sorted(roots), "lines": lines, "blobs": dict(sorted(blobs.items()))}


def _unpack(pkg, limit):
    need(isinstance(pkg, dict) and pkg.get("warrant") == PACKAGE and set(pkg) == {"warrant", "roots", "lines", "blobs"}
         and isinstance(pkg["lines"], list) and all(isinstance(x, str) for x in pkg["lines"])
         and isinstance(pkg["blobs"], dict) and isinstance(pkg["roots"], list) and all(S.hex64(r) for r in pkg["roots"]),
         "BAD_REQUEST", f"a package is {{warrant: {PACKAGE}, roots, lines, blobs}}")
    try:
        blobs = {h: base64.b64decode(b, validate=True) for h, b in pkg["blobs"].items()}
    except (ValueError, TypeError) as e:
        raise AgentError("BAD_REQUEST", f"a blob is not base64: {e}") from None
    lines = [x.encode() + b"\n" for x in pkg["lines"]]
    need(sum(map(len, lines)) + sum(map(len, blobs.values())) <= limit, "RESOURCE_LIMIT", "the package exceeds the workspace's store_bytes")
    need(all(S.hex64(h) and C.digest(b) == h for h, b in blobs.items()), "BAD_REQUEST", "a blob is not named by its hash")
    return lines, blobs


def handoff(cfg, req):
    op = req.get("op") if isinstance(req, dict) else None
    need(isinstance(op, str) and op in HANDOFF_OPS, "BAD_REQUEST", f"op is one of {list(HANDOFF_OPS)}")
    ws = cfg.workspace(req.get("workspace"))
    ws.permit("handoff")
    if op == "export":
        _closed(req, ("workspace", "op", "targets"))
        snap, view, _, _ = _assess(ws)
        rep = view.report()
        need(isinstance(req["targets"], list) and req["targets"], "BAD_REQUEST", "targets is a non-empty list")
        roots = [_resolve(snap, t) for t in req["targets"]]
        pkg = _package_of(snap, view, rep, roots)
        return {"package": pkg, "digest": Snapshot([x.encode() + b"\n" for x in pkg["lines"]],
                                                     {h: base64.b64decode(b) for h, b in pkg["blobs"].items()}).digest}
    _closed(req, ("workspace", "op", "package"), ("alone",) if op == "inspect" else ())
    lines, blobs = _unpack(req["package"], ws.limits["store_bytes"])
    pkg_snap = Snapshot(lines, blobs)
    need(not pkg_snap.rejected, "BAD_REQUEST", f"{len(pkg_snap.rejected)} line(s) of the package are not records")
    if op == "import":
        st = ws.open()
        for data in blobs.values():
            st.put_blob(data)
        before = set(st.lines())
        st.add_lines(lines)
        return {"added": len(set(lines) - before), "blobs": len(blobs), "digest": pkg_snap.digest}
    if req.get("alone", False):
        snap = pkg_snap
    else:
        own = ws.open().snapshot()
        snap = Snapshot(own_lines(own) + lines, {**own.blobs, **blobs})
    _, view, _, _ = _assess(ws, snap)
    rep = view.report()
    nodes, _, _ = G.index(rep)
    caps = {r: G.describe(rep, nodes, r) for r in req["package"]["roots"]}
    return _budget({**_header(rep), "package": pkg_snap.digest, "roots": caps,
                    "rejected": {i: w for i, w in rep["rejected"].items() if i in pkg_snap.lines}},
                   ws.limits["context_bytes"])


def own_lines(snap):
    return sorted({C.canon(e) + b"\n" for envs in snap.lines.values() for e in envs})


# ---------------------------------------------------------------- prepare / commit

def _refusals(snap, view, trust, profile, r):
    """Why this receiver's engine would not take `r` as its actor's next record: the store with it is assessed once
    more, `r` signed by a key made for this call and bound to its actor in a copy of the trust (nothing is written,
    the key is never kept). Refused: a store the engine would refuse, a line it would reject, a problem it did not
    have (a record it drops as INVALID is listed as one). Then the schema rules a pending proposal does not show yet (_schema_problems)."""
    key = K.Key.from_seed_hex(os.urandom(32).hex())
    _, line = R.line(r, key)
    keys = dict(trust["keys"], **{r["actor"]: sorted(set(trust["keys"].get(r["actor"], [])) | {key.public})})
    try:
        after = E.View(Snapshot(own_lines(snap) + [line], snap.blobs), dict(trust, keys=keys), profile)
    except (Refused, R.Invalid) as e:
        return [f"the store with it would be refused: {e}"]
    out = [f"{w}" for h, w in sorted(after.snap.rejected.items()) if h not in snap.rejected]
    out += [f"{c}: {d}" for c, x, d in after.problems if [c, x, d] not in view.problems]     # an INVALID record is one too
    return out + (_schema_problems(view, r) if r["kind"] == "schema" else [])


def _schema_problems(view, r):
    """A schema proposal as _schemas will read it once its quorum is met (short of it, the engine lists it as
    pending, not as a problem): filed by a schema/author, and either the root of a name no counted schema has or
    the successor of its counted leaf, by the root's actor, under the same name."""
    b = r["body"]
    if E._schema_problem(b):
        return []                                       # the engine's own SCHEMA_NOT_COUNTED says why
    out = [] if view.holds(r["actor"], "schema/author") else [f"SCHEMA_NOT_COUNTED: {r['actor']!r} holds no schema/author role here"]
    if r["lineage"] is None:
        if b["name"] in view.schemas:
            out.append(f"SCHEMA_CONFLICT: {b['name']!r} is counted already; file a successor of {view.schemas[b['name']]['id'][:12]}")
        return out
    p, root = view.recs.get(r["lineage"]), view.schema_root.get(r["lineage"])
    if p is None or p["kind"] != "schema" or root is None:
        out.append("LINEAGE_BROKEN: it succeeds no counted schema")
    elif view.recs[root]["actor"] != r["actor"]:
        out.append(f"LINEAGE_NOT_AUTHOR: the schema lineage is {view.recs[root]['actor']!r}'s")
    elif view.schemas.get(p["body"]["name"], {}).get("id") != r["lineage"]:
        out.append(f"SCHEMA_CONFLICT: {r['lineage'][:12]} is not the counted leaf of {p['body']['name']!r}; a successor of it forks")
    elif b["name"] != p["body"]["name"]:
        out.append(f"a successor keeps its schema's name {p['body']['name']!r}")
    return out


def prepare(cfg, req):
    _closed(req, ("workspace", "kind", "body"), ("schema", "target", "lineage", "refs", "guard"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("prepare")
    actor = _signer(ws)
    snap, view, trust, profile = _assess(ws)
    kind, body = req["kind"], req["body"]
    need(kind in R.KINDS and isinstance(body, dict), "BAD_REQUEST", f"kind is one of {list(R.KINDS)}; body an object")
    refs = list(req.get("refs") or [])
    if kind in ("attest", "challenge"):
        t = _resolve(snap, req.get("target") or body.get("target") or "")
        body, refs = dict(body, target=t), refs + [t]
    schema, guard = req.get("schema"), req.get("guard")
    s = view.schemas.get(schema) if isinstance(schema, str) else None
    if s is not None:
        refs += sorted(R.body_refs(s["fields"], body))
        if kind == "entity" and guard is None and isinstance(s["states"], dict):
            guard = s["states"].get(body.get("state"))            # the schema's minimal guard for the state
    lineage = req.get("lineage")
    if lineage is not None:
        lineage = _resolve(snap, lineage)
    h = E.head(snap, trust, actor)
    at = max(int(time.time()), h["at"] or 0, (view.recs.get(lineage) or {}).get("at", 0))     # never backdated
    try:
        r = R.record(kind, actor, at, body, schema=schema, lineage=lineage, refs=refs, guard=guard, prev=h["id"])
    except (R.Invalid, TypeError) as e:
        raise AgentError("INVALID_RECORD", str(e)) from None
    why = _refusals(snap, view, trust, profile, r)
    need(not why, "INVALID_RECORD", "; ".join(why), problems=why)
    return {"record": r, "id": R.rid(r), "bytes": len(R.line(r)[1]), "next": "commit with this record, unchanged"}


def commit(cfg, req):
    _closed(req, ("workspace", "record"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("commit")
    actor = _signer(ws)
    r = req["record"]
    try:
        R.check(r)
    except (R.Invalid, TypeError) as e:
        raise AgentError("INVALID_RECORD", str(e)) from None
    need(r["actor"] == actor, "NOT_PERMITTED", f"the signer of this workspace is {actor!r}, not {r['actor']!r}")
    snap, view, trust, profile = _assess(ws)
    why = _refusals(snap, view, trust, profile, r)
    need(not why, "INVALID_RECORD", "; ".join(why), problems=why)
    try:
        key = K.Key.from_seed_hex(ws.signer[1].read_text())
    except (OSError, ValueError) as e:
        raise AgentError("NO_SIGNER", f"the signer's seed cannot be read: {type(e).__name__}") from None
    need(key.public in trust["keys"].get(actor, []), "SIGNER_NOT_TRUSTED",
         f"the signer's key {key.id[:12]} is not one this workspace's trust binds to {actor!r}")
    try:
        i = ws.open().append(r, key, trust, expect_head=r["prev"] or "")
    except Refused as e:
        raise AgentError("CHAIN_MOVED" if "CHAIN_MOVED" in str(e) else "REFUSED", str(e)) from None
    snap, view, _, _ = _assess(ws)
    rep = view.report()
    nodes, _, _ = G.index(rep)
    return {"id": i, "filed": G.describe(rep, nodes, i), "rejected": rep["rejected"].get(i)}


def explain(cfg, req):
    _closed(req, ("word",))
    need(isinstance(req["word"], str) and req["word"] in GL.TERMS, "NOT_FOUND", "no such word in the glossary")
    return GL.explain(req["word"])


OPERATIONS_ = {"workspace": workspace, "context": context, "read": read, "graph": graph, "handoff": handoff,
               "prepare": prepare, "commit": commit, "explain": explain}
assert set(OPERATIONS_) == set(OPERATIONS) | {"workspace", "explain"}
assert set(GL.TERMS) >= set(CODES)


def call(cfg, op, req):
    try:
        need(op in OPERATIONS_, "BAD_REQUEST", f"operation is one of {sorted(OPERATIONS_)}")
        return {"ok": OPERATIONS_[op](cfg, req if req is not None else {})}
    except AgentError as e:
        return e.to_json()
