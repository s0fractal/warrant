"""One read over every store the operator registered (docs/HOME.md, docs/V3.md §13).

    answer(readings, request, budget, adapter) -> {warrant: across/1, query, root, lens, stores, unavailable,
                                                   total, offset, next, nodes}

Each store is read and assessed alone, under its own trust and profile (Reading); no snapshot, trust, profile or report
is ever merged. A node is one record id: its envelope (kind, actor, at, schema, lineage, target, refs, requires, which
the id covers, so it is the same wherever the record lies) and `in`, one row per store holding it, carrying that store's
name and that store's verdict alone. A store that cannot be read is named under `unavailable`, never dropped. What is
read from a repository is data only: `.warrant/records.jsonl`, `.warrant/blobs/` and `.warrant/v3.json`, and, in a
checkout, the Git trees and history the G14 gate compares (warrant.drift): a claim whose acceptances all name other
bytes reads STALE here as in context and graph, and the lens binds the tree it read.

Queries, none assuming a repository's schemas beyond the two names INTENTS gives:

    stores                  each store's lineages by schema and state
    actor {actor, schema?}  the records each store admits as that actor's, under that store's keys for the name
    open {schema?}          the lineages of a goal or an obligation a store reads as open; a store that counts neither
                            schema says so (no_schema), never zero
    challenges {schema?}    the challenges standing in some store
    rests {target, schema?} what rests on a hash, its edges (graph.WALK) followed by hash through every store

A reference some store holding the citing record does not hold reads ELSEWHERE (with the stores that do) or UNAVAILABLE
(in no store read here). Neither says the record does not exist. `<store>:<id>` (shapes.citation) writes one down: the
id names the record, the store part only says where the citer saw it. `refs` carries the bare id, as for any reference.

Rows are paged within the budget, by `offset`, `next` and `total`: a result is never cut silently."""
import json
import os

from . import drift as D
from . import engine as E
from . import graph as G
from . import home as H
from . import jcs as C
from . import shapes as S
from .store import Refused, Store, confined

FORMAT = "across/1"
QUERIES = ("stores", "actor", "open", "challenges", "rests")
MEMBERS = {"stores": (), "actor": ("actor", "schema"), "open": ("schema",), "challenges": ("schema",),
           "rests": ("target", "schema")}
INTENTS = ("goal@1", "obligation@1")
REFERENCE_STATES = ("ELSEWHERE", "UNAVAILABLE")
BUDGET = 64 << 10                # a result's bytes, as the agent's context_bytes
STORE_BYTES = 64 << 20           # a store's bytes admitted before it is parsed, as the agent's store_bytes
REF_ROWS = 32                    # references listed per node; `refs_more` counts the others
TEXT = 240                       # characters of a record's text; the record itself is one read away


class Refusal(Refused):
    """A refused request, with the agent interface's code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _short(s):
    return s if len(s) <= TEXT else s[:TEXT] + "…"


def snapshot_of(st, limit=STORE_BYTES):
    """The snapshot of a Store, its bytes admitted first. `records.jsonl` and `blobs/` lie in the store, by real path: a
    link never makes one store's records read as another's. A file that is not regular would block the whole read."""
    confined(st.file, st.root)
    confined(st.blobs, st.root)
    if st.file.exists() and not st.file.is_file():
        raise Refused(f"{st.file} is not a regular file")
    size = (st.file.stat().st_size if st.file.is_file() else 0) + \
        (sum(p.stat().st_size for p in st.blobs.iterdir()) if st.blobs.is_dir() else 0)
    if size > limit:
        raise Refusal("RESOURCE_LIMIT", f"the store holds {size} bytes; {limit} are admitted")
    return st.snapshot()


class Reading:
    """One store as one assessment, or why it could not be read. `read()` returns (snapshot, trust, profile,
    repository); whatever it or the assessment raises makes this store unavailable and leaves the others as they are.
    `root`, a checkout of the store's repository, puts the assessment through the G14 gate."""

    def __init__(self, name, read, root=None):
        self.name, self.why, self.view, self.rep, self.repository = name, None, None, None, None
        try:
            snap, trust, profile, self.repository = read()
            self.view = E.View(snap, trust, profile)
            self.rep = self.view.report()
            if root is not None:
                self.rep["_recs"], self.rep["_basis"] = self.view.recs, self.view.basis
                D.gate(self.rep, root)
                del self.rep["_recs"], self.rep["_basis"]
            self.problems = {}
            for code, i, _ in self.rep["problems"]:
                self.problems.setdefault(i, []).append(code)
        except Exception as e:           # NOSONAR S112: one store's failure of any kind is named, and never stops the others
            self.why = f"{getattr(e, 'code', type(e).__name__)}: {e}"

    def holds(self, i):
        return i in self.view.snap.lines or i in self.view.snap.blobs

    def header(self):
        rep = self.rep
        out = {"store": self.name, "root": rep["snapshot"], "as_of": rep["as_of"], "assessment": rep["assessment"], "trust": rep["trust"],
               "profile": rep["profile"], "records": len(self.view.recs), "rejected": len(rep["rejected"]),
               "problems": len(rep["problems"])}
        return out | ({"repository": _short(self.repository)} if isinstance(self.repository, str) else {})

    def verdict(self, i):
        """This store's row for `i`, read from this store's report alone; None when it does not hold `i`."""
        view, rep = self.view, self.rep
        row = {"store": self.name}
        if i in view.bad:
            return dict(row, rejected=_short(view.bad[i]))
        if i not in view.recs:
            return dict(row, blob=True) if i in view.snap.blobs else None
        row["basis"] = view.basis[i]
        if i in self.problems:
            row["problems"] = self.problems[i]
        if i in rep["versions"]:
            g, lin = rep["versions"][i], rep["lineages"][view.root_of[i]]
            row.update(state=lin["state"], reliance=lin["reliance"], guard=g["guard"])
            row.update({"root": view.root_of[i]} if view.root_of[i] != i else {})
            row.update({"waiting": g["waiting"]} if g["guard"] == E.PENDING else {})
            if lin["leaf"] not in (i, None):
                row.update(leaf=lin["leaf"], leaf_guard=rep["versions"][lin["leaf"]]["guard"])
        if i in rep["challenges"]:
            c = rep["challenges"][i]
            row.update(counted=c["counted"], stands=c["stands"], why=_short(c["why"]))
        if view.recs[i]["kind"] == "schema":
            row["counted"] = i in rep["schemas"].values()
        return row


def _body_text(r):
    """A record's words where its body has them; data, never instructions (the answer says `untrusted`)."""
    out = {"key": r["body"]["key"]} if isinstance(r["body"].get("key"), str) else {}
    text = next((r["body"][k] for k in ("statement", "text") if isinstance(r["body"].get(k), str)), None)
    return out | ({"text": _short(text)} if text is not None else {})


def _references(i, r, readings):
    """(the references of the record `i` some store admitting it does not hold, how many are not listed)."""
    target = r["body"].get("target") if r["kind"] in ("attest", "challenge") else None
    cited = sorted({*r["refs"], *(r["guard"] or {}).get("requires", []), *([r["lineage"]] if r["lineage"] else []),
                    *([target] if target else [])})
    admitting = [x for x in readings if i in x.view.recs]
    rows = []
    for h in cited:
        if all(x.holds(h) for x in admitting):
            continue
        where = [x.name for x in readings if x.holds(h)]
        rows.append({"id": h, "state": "ELSEWHERE", "held_in": where} if where else {"id": h, "state": "UNAVAILABLE"})
    return rows[:REF_ROWS], max(0, len(rows) - REF_ROWS)


def node(i, readings, text=False):
    """One row of an answer: the envelope of `i`, once, and every store's verdict on it apart."""
    out = {"id": i, "in": [v for v in (x.verdict(i) for x in readings) if v]}
    r = next((x.view.recs[i] for x in readings if i in x.view.recs), None)
    if r is None:
        return out
    target = r["body"].get("target") if r["kind"] in ("attest", "challenge") else None
    refs = [h for h in r["refs"] if h != target]
    out.update(kind=r["kind"], actor=r["actor"], at=r["at"])
    optional = {"schema": r["schema"], "lineage": r["lineage"], "target": target, "refs": refs[:REF_ROWS],
                "refs_more": max(0, len(refs) - REF_ROWS), "requires": (r["guard"] or {}).get("requires", [])[:REF_ROWS]}
    foreign, more = _references(i, r, readings)
    optional.update(foreign=foreign, foreign_more=more)
    out.update({k: v for k, v in optional.items() if v})
    return out | (_body_text(r) if text else {})


def _recent(ids, readings, schema):
    """`ids` newest first by the time each record claims (shown, not witnessed), the id breaking ties, of `schema`."""
    recs = {}
    for x in readings:
        for i in ids:
            if i in x.view.recs:
                recs.setdefault(i, x.view.recs[i])
    return sorted((i for i in ids if i in recs and schema in (None, recs[i]["schema"])), key=lambda i: (-recs[i]["at"], i))


def _lineages_by_state(rep):
    out = {}
    for lin in rep["lineages"].values():
        key = f"{lin['schema']} {lin['state']}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _of_actor(readings, actor, schema, stores):
    ids = set()
    for x, row in zip(readings, stores):
        mine = [i for i, r in x.view.recs.items() if r["actor"] == actor]
        ids.update(mine)
        counts = {}
        for i in mine:
            r = x.view.recs[i]
            key = f"{r['kind']} {r['schema']}" if r["schema"] else r["kind"]
            counts[key] = counts.get(key, 0) + 1
        row.update(keys=x.view.trust["keys"].get(actor, []), counts=dict(sorted(counts.items())))
    return _recent(ids, readings, schema)


def _open(readings, schema, stores):
    ids = set()
    for x, row in zip(readings, stores):
        found = [lin for lin in x.rep["lineages"].values() if lin["schema"] in INTENTS and lin["state"] == "open"]
        ids.update(lin["effective"] for lin in found)
        row["intents"] = {n: sum(1 for lin in found if lin["schema"] == n) for n in INTENTS if n in x.rep["schemas"]}
        missing = [n for n in INTENTS if n not in x.rep["schemas"]]
        row.update({"no_schema": missing} if missing else {})
    return _recent(ids, readings, schema)


def _standing(readings, schema):
    return _recent({c for x in readings for c, v in x.rep["challenges"].items() if v["stands"]}, readings, schema)


def _target(readings, t):
    """The id a `rests` target names: an id, an id's prefix of 8 or more characters, or a citation (whose store part
    narrows nothing). A whole id nothing here holds is still asked about: a record may cite what no store holds."""
    if S.citation(t):
        return t.rsplit(":", 1)[1]
    if S.hex64(t):
        return t
    if not (isinstance(t, str) and 8 <= len(t) < 64 and S.HEX.match(t)):
        raise Refusal("BAD_REQUEST", "a target is a record or blob id, a prefix of 8 or more lowercase hex characters, or <store>:<id>")
    ids = {i for x in readings for i in x.view.snap.lines if i.startswith(t)} | \
          {i for x in readings for i in x.view.snap.blobs if i.startswith(t)} | \
          {b for x in readings for _, _, b in x.rep["graph"]["edges"] if b.startswith(t)}
    if len(ids) != 1:
        raise Refusal("NOT_FOUND", f"{t} names {len(ids)} records or blobs in the stores read here")
    return ids.pop()


def _rests(readings, target, schema):
    """(ids resting on `target`, nearest first, target first; each id's distance; every edge followed). An edge is read
    from the citing record; it crosses stores because a hash names the same record wherever it lies."""
    into = {}
    for x in readings:
        for a, rel, b in x.rep["graph"]["edges"]:
            if rel in G.WALK:
                into.setdefault(b, set()).add(a)
    depth, todo = {target: 0}, [target]
    while todo and len(depth) < G.MAX_NODES:
        cur = todo.pop(0)
        for a in sorted(into.get(cur, ())):
            if a not in depth:
                depth[a] = depth[cur] + 1
                todo.append(a)
    ids = [target] + _recent(set(depth) - {target}, readings, schema)
    return sorted(ids, key=lambda i: depth[i]), depth, not todo


def _closed(q):
    if not (isinstance(q, dict) and q.get("query") in QUERIES):
        raise Refusal("BAD_REQUEST", f"query is one of {list(QUERIES)}")
    allowed = {"query", "offset", "max_bytes", *MEMBERS[q["query"]]}
    needed = {"actor": {"actor"}, "rests": {"target"}}.get(q["query"], set())
    if set(q) - allowed or needed - set(q):
        raise Refusal("BAD_REQUEST", f"{q['query']} takes {sorted(allowed - {'query'})} and needs {sorted(needed)}")
    if "actor" in q and not S.is_actor(q["actor"]):
        raise Refusal("BAD_REQUEST", "actor is an actor id")
    if "schema" in q and not isinstance(q["schema"], str):
        raise Refusal("BAD_REQUEST", "schema is a schema's name")
    for k, least in (("offset", 0), ("max_bytes", 1)):
        if k in q and (isinstance(q[k], bool) or not isinstance(q[k], int) or q[k] < least):
            raise Refusal("BAD_REQUEST", f"{k} is an integer of at least {least}")


def _dumped(x):
    return len(json.dumps(x, sort_keys=True))


def answer(readings, q, budget=BUDGET, adapter=None):
    """The answer to `q` over `readings`: one result within `budget` bytes, with `next` when more rows remain. The same
    lens over the same root gives the same bytes."""
    _closed(q)
    budget = min(budget, q.get("max_bytes", budget))
    read = sorted((x for x in readings if x.why is None), key=lambda x: x.name)
    unavailable = [{"store": x.name, "why": _short(x.why)} for x in sorted(readings, key=lambda x: x.name) if x.why]
    stores = [x.header() for x in read]
    query = {k: v for k, v in q.items() if k not in ("offset", "max_bytes")}
    extra, depth = {}, None
    schema = q.get("schema")
    ids = []
    if q["query"] == "stores":
        for x, row in zip(read, stores):
            row["lineages"] = _lineages_by_state(x.rep)
    elif q["query"] == "actor":
        ids = _of_actor(read, q["actor"], schema, stores)
    elif q["query"] == "open":
        ids = _open(read, schema, stores)
    elif q["query"] == "challenges":
        ids = _standing(read, schema)
    else:
        t = _target(read, q["target"])
        query["target"] = t
        ids, depth, complete = _rests(read, t, schema)
        where = [x.name for x in read if x.holds(t)]
        extra = {"target": {"id": t, "held_in": where} if where else {"id": t, "state": "UNAVAILABLE"}, "complete": complete}
    code = read[0].rep["code"] if read else E.code_identity()
    out = {"warrant": FORMAT, "completeness": "UNATTESTED", "untrusted": True, "query": query, "stores": stores,
           "unavailable": unavailable, "total": len(ids), "offset": q.get("offset", 0), "next": len(ids), **extra, "nodes": [],
           "root": C.doc_id({"stores": {x.name: x.rep["snapshot"] for x in read}, "unavailable": unavailable}),
           "lens": C.doc_id({"code": code, "adapter": adapter, "query": query,
                             "stores": {x.name: {"trust": x.rep["trust"], "profile": x.rep["profile"], "checkout": x.rep.get("checkout")} for x in read}})}
    used, pos = _dumped(out), out["offset"]
    if used > budget:
        raise Refusal("RESOURCE_LIMIT", f"the answer's header is {used} bytes; {budget} are allowed")
    text = q["query"] in ("open", "challenges")
    while pos < len(ids):
        row = node(ids[pos], read, text)
        row.update({"depth": depth[ids[pos]]} if depth else {})
        size = _dumped(row) + 2
        if used + size > budget:
            break
        out["nodes"].append(row)
        used, pos = used + size, pos + 1
    if not out["nodes"] and pos < len(ids):
        raise Refusal("RESOURCE_LIMIT", f"one row does not fit {budget} bytes")
    out["next"] = pos if pos < len(ids) else None
    return out


def home_readings(doc):
    """One Reading per repository of a Home; a repository whose operations leave out `graph` is named, not read."""
    def read(name, r):
        if "graph" not in r.get("operations", H.OPERATIONS):
            raise Refusal("NOT_PERMITTED", f"the operator did not permit `graph` for {name!r}")
        path = os.path.expanduser(r["path"])
        snap = snapshot_of(Store(H.store_of(doc, name)))
        trust, profile, repository = H.receiver(path)
        return snap, trust, profile, repository
    return [Reading(name, lambda name=name, r=r: read(name, r), os.path.expanduser(r["path"])) for name, r in sorted(doc["repositories"].items())]
