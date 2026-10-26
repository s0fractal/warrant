"""The record graph of one snapshot: nodes and edges read from record bodies (SPEC §3), with the
engine's report (§4) attached, shown and never recomputed.

Pure functions of (snapshot, report): the agent operation `graph` (api.py, over a frozen view) and the
repository's `tools/graph.py` (over the stores of Git commits) call the same ones, so the two answer
alike. A record is a node when the report does not list it invalid; a question a transition opens is
the node `<transition id>:<index>`; a blob a record cites is a node labelled by its `schema` member
when it is a JSON object that has one; an id an edge names that the snapshot lacks is a `missing` node.
Labels are record text: untrusted data.

  build(snap, report)        {graph, assessment_id, snapshot, nodes, edges}, sorted
  path(g, report, target)    the duties a duty, a question or a question scope leads to, prerequisites first
  frontier(report, actor)    the engine's frontier for `actor`, as it is
  delta(g0, g1)              nodes and edges added, removed or changed from g0 to g1
  impact(g0, g1, also=())    the duties and questions the records changed from g0 to g1 bear on
  dot(g)                     Graphviz text of a graph, every label escaped
  lens_id(code, assessed, query)   the content address of everything but the root that decides a result
  root_part(report), operands(report)   a report's root, and its other assessment operands
"""
import json
import platform

from warrant import jcs as C

GRAPH = "warrant-graph/graph@1"
LABEL = 200                     # characters of a label; the record holds the rest
EDGE_KEY = ("from", "to", "rel", "item")
# What a changed record bears on: from a record to the record it is about (closes, accepts, challenges,
# supersedes, revalidates, grants), then from a duty along these (impact).
ABOUT = ("closes", "accepts", "challenges", "supersedes", "revalidates", "grants")


def _label(text):
    text = " ".join(str(text).split())
    return text if len(text) <= LABEL else text[:LABEL - 1] + "…"


def _blob_label(data):
    try:
        doc = C.loads(data)
    except (ValueError, TypeError):            # jcs.NotCanonical is a ValueError
        try:
            doc = json.loads(data)
        except ValueError:                     # UnicodeDecodeError is a ValueError
            return None
    if isinstance(doc, dict) and isinstance(doc.get("schema"), str):
        tail = doc.get("id") if isinstance(doc.get("id"), str) else None
        return _label(doc["schema"] + (f" {tail}" if tail else ""))
    return None


def _record(data):
    try:
        env = C.loads(data)
    except (ValueError, TypeError):            # jcs.NotCanonical is a ValueError
        return None
    rec = env.get("record") if isinstance(env, dict) else None
    return rec if isinstance(rec, dict) and isinstance(rec.get("body"), dict) else None


def _record_label(rec):
    b, t = rec["body"], rec["type"]
    if t == "duty":
        return b["statement"]
    if t == "transition":
        return (b["established"] or b["residual"] or [f"closes {len(b['closes'])} item(s)"])[0]
    if t == "accept":
        return f"accepts item {b['item']} of {b['transition'][:12]}"
    if t == "challenge":
        return b["statement"]
    if t == "observation":
        return f"{b['target']}: {b['result']}"
    return f"grants {', '.join(b['acts'])} to {b['grantee']}"


def _edges(rid, rec):
    """[(to, rel, item)] of one record's body."""
    b, t, out = rec["body"], rec["type"], []
    if rec.get("prev"):
        out.append((rec["prev"], "prev", None))
    if t == "duty":
        out += [(x, "requires", None) for x in b["requires"]] + [(x, "serves", None) for x in b["serves"]]
        if b["answers"]:
            out.append((b["answers"], "answers", None))
    elif t == "transition":
        for i, m in enumerate(b["closes"]):
            out.append((m["duty"], "closes", i))
            out += [(x, "revalidates", i) for x in m.get("revalidates", [])]
        out += [(f"{rid}:{i}", "opens", i) for i in range(len(b["opened"]))]
        out += [(x, "evidence", None) for x in b["evidence"]] + [(x, "relies_on", None) for x in b["relied_on"]]
        out += [(x, "supersedes", None) for x in b["supersedes"]]
    elif t == "accept":
        out.append((b["transition"], "accepts", b["item"]))
        out += [(x, "evidence", None) for x in b["evidence"]] + [(x, "support", None) for x in b["support"]]
    elif t == "challenge":
        out.append((b["target"], "challenges", b["item"]))
        out += [(x, "evidence", None) for x in b["evidence"]]
    elif t == "observation":
        out += [(b["probe"], "probe", None)] + [(x, "raw", None) for x in b["raw"]]
    elif t == "grant":
        out += [(x, "grants", None) for x in b["duties"]]
        if b["parent"]:
            out.append((b["parent"], "parent", None))
    return out


def _verdicts(report):
    """{(transition, item): verdict} of every closure candidate the report judged."""
    return {(c["transition"], c["item"]): c["verdict"] for d in report["duties"].values() for c in d["candidates"]}


def _state(rid, rec, report):
    """The report's state of a record node: a duty's disposition, a transition's CURRENT or SUPERSEDED."""
    if rec["type"] == "duty" and rid in report["duties"]:
        return report["duties"][rid]["disposition"]
    if rec["type"] == "transition" and rid in report["results"]:
        return "SUPERSEDED" if report["results"][rid]["superseded_by"] else "CURRENT"
    return None


def _questions(rid, rec, questions):
    """The question nodes a transition opens, with the report's ownership of each."""
    out = []
    for i, q in enumerate(rec["body"]["opened"] if rec["type"] == "transition" else ()):
        ref = f"{rid}:{i}"
        seen = questions.get(ref)
        owned = None
        if seen is not None:
            owned = "OWNED" if seen["owned"] else "UNOWNED"
        out.append({"id": ref, "kind": "question", "actor": rec["actor"], "at": rec["at"], "label": _label(q["text"]),
                    "scope": q["scope"], "state": owned})
    return out


def _endpoint(snap, x):
    """The node of an id an edge names that is no record of the graph: a blob of the snapshot, or missing."""
    if x in snap.blobs:
        return {"id": x, "kind": "blob", "actor": None, "at": None, "label": _blob_label(snap.blobs[x]), "state": None}
    return {"id": x, "kind": "missing", "actor": None, "at": None, "label": None, "state": None}


def build(snap, report):
    """The graph of `snap` as `report` (the engine's assessment of it) judged it."""
    invalid = set(report["invalid_records"])
    recs = {}
    for rid, data in snap.records.items():
        rec = None if rid in invalid else _record(data)
        if rec is not None:
            recs[rid] = rec
    verdicts = _verdicts(report)
    questions = {q["question"]: q for q in report["questions"]}
    nodes, edges = {}, []
    for rid, rec in recs.items():
        nodes[rid] = {"id": rid, "kind": rec["type"], "actor": rec["actor"], "at": rec["at"],
                      "label": _label(_record_label(rec)), "state": _state(rid, rec, report)}
        nodes.update((q["id"], q) for q in _questions(rid, rec, questions))
        for to, rel, item in _edges(rid, rec):
            e = {"from": rid, "to": to, "rel": rel, "item": item}
            if rel == "closes":
                e["verdict"] = verdicts.get((rid, item))
            edges.append(e)
    for e in edges:
        if e["to"] not in nodes:
            nodes[e["to"]] = _endpoint(snap, e["to"])
    return {"graph": GRAPH, "assessment_id": report["assessment_id"], "snapshot": snap.digest,
            "nodes": [nodes[k] for k in sorted(nodes)],
            "edges": sorted(edges, key=lambda e: (e["from"], e["rel"], e["to"], -1 if e["item"] is None else e["item"]))}


# ---------------------------------------------------------------- reading a graph

class Index:
    """A graph's nodes by id and its edges by endpoint."""

    def __init__(self, g):
        self.g = g
        self.nodes = {n["id"]: n for n in g["nodes"]}
        self.out, self.into = {}, {}
        for e in g["edges"]:
            self.out.setdefault(e["from"], []).append(e)
            self.into.setdefault(e["to"], []).append(e)

    def kind(self, x):
        return (self.nodes.get(x) or {}).get("kind")

    def targets(self, x, rel):
        return [e["to"] for e in self.out.get(x, []) if e["rel"] == rel]

    def sources(self, x, rel):
        return [e["from"] for e in self.into.get(x, []) if e["rel"] == rel]


class Unknown(Exception):
    """A target that names nothing in the graph, or more than one thing."""


def resolve(ix, target):
    """('duty', id), ('question', ref) or ('scope', scope) of a target: a duty id or a unique prefix of at least
    8 hex digits, a question reference, or a question scope that some question of the graph has."""
    if not isinstance(target, str) or not target or len(target) > 200:
        raise Unknown("a target is a duty id, a question reference or a question scope (1 to 200 characters)")
    if ix.kind(target) == "question":
        return "question", target
    if ix.kind(target) == "duty":
        return "duty", target
    if 8 <= len(target) <= 64 and all(c in "0123456789abcdef" for c in target):
        hits = sorted(k for k, n in ix.nodes.items() if n["kind"] == "duty" and k.startswith(target))
        if len(hits) == 1:
            return "duty", hits[0]
        raise Unknown(f"{target!r} is a prefix of {len(hits)} duties" if hits else f"no duty {target!r} in the graph")
    if any(n["kind"] == "question" and n.get("scope") == target for n in ix.nodes.values()):
        return "scope", target
    raise Unknown(f"{target!r} is neither a duty, a question nor a question scope of this graph")


def _closures(ix, did):
    return [{"transition": e["from"], "item": e["item"], "verdict": e.get("verdict"),
             "actor": (ix.nodes.get(e["from"]) or {}).get("actor")}
            for e in sorted((e for e in ix.into.get(did, []) if e["rel"] == "closes"), key=lambda e: (e["from"], e["item"]))]


def _duty(ix, did):
    n = ix.nodes.get(did) or {"label": None, "state": None, "actor": None}
    return {"duty": did, "statement": n["label"], "state": n["state"], "filed_by": n["actor"],
            "requires": sorted(ix.targets(did, "requires")), "required_by": sorted(ix.sources(did, "requires")),
            "serves": sorted(ix.targets(did, "serves")), "served_by": sorted(ix.sources(did, "serves")),
            "answers": (ix.targets(did, "answers") or [None])[0], "closures": _closures(ix, did)}


def _prerequisites_first(ix, roots):
    """Every duty `roots` require (transitively), each once, a duty after the duties it requires; a cycle is cut
    where it closes (`cycle`). Iterative: an admitted chain of any depth is answered (Codex 0ad3ed6d54a1 on #209:
    the recursive walk raised RecursionError at 1200 duties)."""
    order, state, cycles = [], {}, set()
    for r in sorted(roots):
        if r in state:
            continue
        state[r] = "open"
        stack = [(r, iter(sorted(ix.targets(r, "requires"))))]
        while stack:
            d, kids = stack[-1]
            x = next(kids, None)
            if x is None:
                stack.pop()
                state[d] = "done"
                order.append(d)
            elif state.get(x) == "open":
                cycles.add(x)
            elif x not in state:
                state[x] = "open"
                stack.append((x, iter(sorted(ix.targets(x, "requires")))))
    return order, cycles


def path(g, target, ix=None):
    """What `target` leads to: its questions (one, or every question of a scope), the duties answering them (or the
    duty itself), and every duty those require, prerequisites first, each with its state, links and closures."""
    ix = ix or Index(g)
    kind, ref = resolve(ix, target)
    if kind == "duty":
        qs, roots = [], [ref]
    else:
        qs = [ref] if kind == "question" else sorted(k for k, n in ix.nodes.items()
                                                    if n["kind"] == "question" and n.get("scope") == ref)
        roots = sorted({d for q in qs for d in ix.sources(q, "answers")})
    order, cycles = _prerequisites_first(ix, roots)
    duties = [dict(_duty(ix, d), root=d in roots, cycle=d in cycles) for d in order]
    return {"target": target, "kind": kind,
            "questions": [{"question": q, "scope": ix.nodes[q].get("scope"), "text": ix.nodes[q]["label"],
                           "state": ix.nodes[q]["state"], "answered_by": sorted(ix.sources(q, "answers"))} for q in qs],
            "duties": duties,
            "open": sorted(d["duty"] for d in duties if d["state"] != "DISCHARGED")}


def frontier(report, actor):
    """The engine's frontier for `actor` (engine.frontier), as it is: each need already names its duty's statement."""
    from warrant import engine as E
    return E.frontier(report, actor)


def _edge_key(e):
    return tuple(e[k] for k in EDGE_KEY)


def delta(g0, g1):
    """Nodes and edges added, removed or changed (same id, another state or label; same edge, another verdict)."""
    a, b = {n["id"]: n for n in g0["nodes"]}, {n["id"]: n for n in g1["nodes"]}
    ea, eb = {_edge_key(e): e for e in g0["edges"]}, {_edge_key(e): e for e in g1["edges"]}
    nodes = ([{"change": "added", "node": b[k]} for k in sorted(set(b) - set(a))]
             + [{"change": "removed", "node": a[k]} for k in sorted(set(a) - set(b))]
             + [{"change": "changed", "node": b[k], "was": {f: a[k][f] for f in a[k] if a[k][f] != b[k].get(f)}}
                for k in sorted(set(a) & set(b)) if a[k] != b[k]])
    key = lambda k: tuple(-1 if x is None else x for x in k)      # noqa: E731
    edges = ([{"change": "added", "edge": eb[k]} for k in sorted(set(eb) - set(ea), key=key)]
             + [{"change": "removed", "edge": ea[k]} for k in sorted(set(ea) - set(eb), key=key)]
             + [{"change": "changed", "edge": eb[k], "was": {"verdict": ea[k].get("verdict")}}
                for k in sorted(set(ea) & set(eb), key=key) if ea[k] != eb[k]])
    return {"from": {"assessment_id": g0["assessment_id"], "snapshot": g0["snapshot"]},
            "to": {"assessment_id": g1["assessment_id"], "snapshot": g1["snapshot"]},
            "nodes": nodes, "edges": edges,
            "counts": {c: sum(x["change"] == c for x in nodes) for c in ("added", "removed", "changed")}
            | {f"edges_{c}": sum(x["change"] == c for x in edges) for c in ("added", "removed", "changed")}}


def _about(ix, x):
    """The duties record `x` is about: itself if a duty; else along ABOUT to a duty, through transitions (iterative,
    as _prerequisites_first)."""
    out, seen, todo = set(), set(), [x]
    while todo:
        y = todo.pop()
        if y in seen:
            continue
        seen.add(y)
        if ix.kind(y) == "duty":
            out.add(y)
        else:
            todo += [e["to"] for e in ix.out.get(y, []) if e["rel"] in ABOUT]
    return out


def _side(i0, i1, d):
    """The graph a node's own edges and metadata are read from: the head's while it is a record or question there,
    else the base's. A duty removed in the range still answered its question and served its duties in the base
    (Codex's challenge ed4a4e636842 of a G11 closure); a question whose opener was removed is still a `missing` node
    of the head while a surviving duty names it, with no scope or text (Codex's finding eda8f4bec1a5 on #213)."""
    return i1 if i1.kind(d) not in (None, "missing") else i0


def _reach(i0, i1, via, named):
    """Extend `via` ({duty: {why}}) from the duties in it: the ones they serve (`serves`), the ones naming a duty of
    `named` (`named`), then every duty requiring one of all these, transitively (`requires`)."""
    def note(d, why):
        via.setdefault(d, set()).add(why)
    for d in sorted(via):
        for x in _side(i0, i1, d).targets(d, "serves"):
            note(x, "serves")
    for d in sorted(named):
        for x in i1.sources(d, "serves") + i1.sources(d, "requires"):
            note(x, "named")
    todo = sorted(via)
    while todo:
        d = todo.pop()
        for x in i1.sources(d, "requires"):
            if x not in via:
                todo.append(x)
            note(x, "requires")


def impact(g0, g1, also=()):
    """What the records added or removed from g0 to g1 bear on, read in g1 (a removed one in g0): the duties they
    are about (`record`: closes, accepts, challenges, supersedes, revalidates, grants) and the duties `also` names
    ({duty: why}, e.g. `statement`: a claim backed by a mutant of a changed statement); the duties those serve
    (`serves`, one link); the duties that serve or require one `also` names (`named`: the obligations naming a
    claim, as tools/claims.py why reads them); every duty requiring one of all these, transitively (`requires`);
    and the questions all of them answer."""
    i0, i1 = Index(g0), Index(g1)
    recs = lambda g: {n["id"] for n in g["nodes"] if n["kind"] not in ("question", "blob", "missing")}  # noqa: E731
    added, removed = sorted(recs(g1) - recs(g0)), sorted(recs(g0) - recs(g1))
    via = {}
    for ix, rs in ((i1, added), (i0, removed)):
        for d in (d for r in rs for d in _about(ix, r)):
            via.setdefault(d, set()).add("record")
    named = dict(also)
    for d, why in named.items():
        via.setdefault(d, set()).add(why)
    _reach(i0, i1, via, named)
    node = lambda x: _side(i0, i1, x).nodes.get(x) or {}     # noqa: E731  (a head `missing` node has no metadata)
    duties = [{"duty": d, "statement": node(d).get("label"),
               "state": (i1.nodes.get(d) or {}).get("state"), "via": sorted(via[d]),
               "answers": (_side(i0, i1, d).targets(d, "answers") or [None])[0]} for d in sorted(via)]
    qs = sorted({d["answers"] for d in duties if d["answers"]})
    return {"records": {"added": added, "removed": removed}, "duties": duties,
            "questions": [{"question": q, "scope": node(q).get("scope"), "text": node(q).get("label"),
                           "by": sorted(d["duty"] for d in duties if d["answers"] == q)} for q in qs]}


LENS = "warrant-graph/lens@1"
ROOT = ("snapshot", "as_of")            # what a report was computed from; `completeness` is a statement, no operand


def root_part(report):
    """A report's root: the snapshot it assessed and the time it assessed it at."""
    return {k: report["view"][k] for k in ROOT}


def operands(report):
    """Every other operand of a report's assessment, read off its own identity block (trust, profile, the current
    revisions, the workspace, the engine, the provider), never listed here: an operand added to the engine's identity
    joins every lens (Codex 74a162414cb8 on #209: a base view's trust was left out)."""
    return {k: v for k, v in report["view"].items() if k not in ROOT + ("completeness",)}


def lens_id(code, assessed, query):
    """The lens of a result: the content address of the code that computed it (`code`: {name: identity}, the whole
    deciding path, never one file), the operands of every assessment it read (`assessed`: operands(report) of each,
    base first), the interpreter, and the query with its parameters resolved (a default the request left out is the
    value used, not its absence: Codex 5af55ace3344). Its root is named apart. One lens over one root, one result."""
    return C.doc_id({"lens": LENS, "code": code, "assessed": assessed, "query": query,
                     "python": f"{platform.python_implementation()} {platform.python_version()}"})


def _dot_text(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'


def dot(g):
    """Graphviz text: one node per node (its kind, its label, its state), one edge per edge; every string quoted
    and escaped, so record text cannot add a statement."""
    out = ["digraph warrant {", "  node [shape=box];"]
    for n in g["nodes"]:
        text = f"{n['kind']} {n['id'][:12]}" + (f" [{n['state']}]" if n.get("state") else "") \
            + (f"\n{n['label']}" if n.get("label") else "")
        out.append(f"  {_dot_text(n['id'])} [label={_dot_text(text)}];")
    for e in g["edges"]:
        lab = e["rel"] + ("" if e["item"] is None else f" {e['item']}") + (f" {e['verdict']}" if e.get("verdict") else "")
        out.append(f"  {_dot_text(e['from'])} -> {_dot_text(e['to'])} [label={_dot_text(lab)}];")
    return "\n".join(out) + "\n}\n"
