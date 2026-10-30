"""Queries over the record graph of one assessment report (docs/V3.md §10: nodes and typed edges read
from `refs`, `lineage`, `guard.requires`, `prev` and an attest's or challenge's target, never from text).
Pure functions of reports: the agent operation `graph`, `warrant status` and the repository's tools/graph.py
call the same ones. Every state shown is the report's, never recomputed.

  around(rep, id)          a node, its lineage and its edges in and out
  path(rep, id)            what a record rests on (edges out, transitively; `prev` left out)
  why(rep, id)             what rests on a record (edges in, transitively)
  frontier(rep, profile, actor)   what waits for the actor: versions it may attest, its own pending
                           versions and its challenged lineages
  delta(rep0, rep1)        nodes added and removed, lineages whose state or reliance changed
  impact(rep0, rep1)       the lineages the changed records bear on, and what rests on those
  answer(rep, query, data, adapter)   {root, lens, query, data}: the same lens over the same root gives
                           the same bytes, so a result may be cached by (lens, root) and re-derived

`root` is the snapshot digest; `lens` the content address of everything else that decides a result:
the engine's code, the adapter's, the trust, the profile and the query."""
from . import jcs as C

WALK = ("lineage", "requires", "ref", "attest", "challenge")       # `prev` orders a writer's chain; it is no dependency
MAX_NODES = 2000


def index(rep):
    """({id: node}, {id: [(rel, to)]}, {id: [(rel, from)]}) of a report's graph."""
    nodes = {n[0]: {"id": n[0], "kind": n[1], "schema": n[2], "actor": n[3], "at": n[4], "basis": n[5]}
             for n in rep["graph"]["nodes"]}
    out, into = {}, {}
    for a, rel, b in rep["graph"]["edges"]:
        out.setdefault(a, []).append((rel, b))
        into.setdefault(b, []).append((rel, a))
    return nodes, out, into


def lineage_of(rep, i):
    """The root of the lineage version `i` is in, or None."""
    for root, lin in rep["lineages"].items():
        if i in lin["versions"]:
            return root
    return None


def describe(rep, nodes, i):
    n = dict(nodes.get(i) or {"id": i, "kind": "missing"})
    if i in rep["versions"]:
        n["guard"] = rep["versions"][i]
        root = lineage_of(rep, i)
        lin = rep["lineages"][root]
        n["lineage"] = {"root": root, "state": lin["state"], "reliance": lin["reliance"], "leaf": lin["leaf"],
                        "effective": lin["effective"], "verdict": lin["verdict"]}
    if i in rep["challenges"]:
        n["challenge"] = rep["challenges"][i]
    return n


def around(rep, i):
    nodes, out, into = index(rep)
    return {"node": describe(rep, nodes, i), "out": sorted([r, b] for r, b in out.get(i, [])),
            "in": sorted([r, a] for r, a in into.get(i, []))}


def _walk(rep, i, edges):
    nodes, out, into = index(rep)
    adj = out if edges == "out" else into
    seen, order, todo = {i}, [], [i]
    while todo and len(order) < MAX_NODES:
        cur = todo.pop(0)
        for rel, nxt in sorted(adj.get(cur, [])):
            if rel in WALK and nxt not in seen:
                seen.add(nxt)
                order.append(nxt)
                todo.append(nxt)
    return {"from": i, "nodes": [describe(rep, nodes, x) for x in order], "complete": not todo}


def path(rep, i):
    return _walk(rep, i, "out")


def why(rep, i):
    return _walk(rep, i, "in")


def frontier(rep, profile, actor):
    """What waits for `actor` in this report: `attest` the lineage leaves whose guard waits only for attests by roles
    the actor holds (no open requirement, not its own, not yet attested or challenged by it); `pending` its own
    leaves whose guard waits; `challenged` its lineages a counted challenge holds."""
    roles = {r for r, actors in profile["roles"].items() if actor in actors}
    nodes, _, into = index(rep)
    acted = {b for b, ins in into.items() for rel, a in ins if rel in ("attest", "challenge") and nodes[a]["actor"] == actor}
    attest, pending = [], []
    for root, lin in sorted(rep["lineages"].items()):
        v = lin["leaf"]           # the latest version: an earlier pending one was replaced by it
        g = rep["versions"].get(v) or {"guard": None}
        if g["guard"] != "PENDING":
            continue
        if nodes[v]["actor"] == actor:
            pending.append(v)
        elif v not in acted and g["short"] and not g["open"] and roles & set(g["roles"]):
            attest.append({"version": v, "lineage": root, "schema": lin["schema"], "waiting": g["waiting"]})
    challenged = [root for root, lin in sorted(rep["lineages"].items())
                  if lin["reliance"] == "CHALLENGED" and lin["actor"] == actor]
    return {"actor": actor, "roles": sorted(roles), "attest": attest, "pending": pending, "challenged": challenged}


def delta(rep0, rep1):
    n0, n1 = {n[0] for n in rep0["graph"]["nodes"]}, {n[0] for n in rep1["graph"]["nodes"]}
    changed = sorted(L for L, lin in rep1["lineages"].items() if L in rep0["lineages"]
                     and (rep0["lineages"][L]["state"], rep0["lineages"][L]["reliance"], rep0["lineages"][L]["leaf"])
                     != (lin["state"], lin["reliance"], lin["leaf"]))
    return {"added": sorted(n1 - n0), "removed": sorted(n0 - n1), "changed": changed,
            "lineages_added": sorted(set(rep1["lineages"]) - set(rep0["lineages"])),
            "lineages_removed": sorted(set(rep0["lineages"]) - set(rep1["lineages"]))}


def impact(rep0, rep1):
    """The lineages the records added or removed between two reports bear on (a version's own, an attest's or a
    challenge's target's), each with what rests on it in the later report (why), roots of other lineages only."""
    d = delta(rep0, rep1)
    touched = set(d["changed"]) | set(d["lineages_added"]) | set(d["lineages_removed"])
    for rep, ids in ((rep1, d["added"]), (rep0, d["removed"])):
        _, out, _ = index(rep)
        for i in ids:
            for x in [i] + [b for rel, b in out.get(i, []) if rel in ("attest", "challenge")]:
                root = lineage_of(rep, x)
                if root:
                    touched.add(root)
    out = []
    for L in sorted(touched):
        rep = rep1 if L in rep1["lineages"] else rep0
        lin = rep["lineages"][L]
        rests = sorted({lineage_of(rep, n["id"]) for n in why(rep, L)["nodes"]} - {None, L})
        out.append({"lineage": L, "schema": lin["schema"], "state": lin["state"], "reliance": lin["reliance"],
                    "gone": L not in rep1["lineages"], "rests_on_it": rests})
    return {"delta": d, "lineages": out}


def answer(rep, query, data, adapter):
    lens = C.doc_id({"code": rep["code"], "adapter": adapter, "trust": rep["trust"], "profile": rep["profile"],
                     "query": query})
    return {"root": rep["snapshot"], "lens": lens, "query": query, "data": data}
