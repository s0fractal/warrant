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
  ledger(rep, recs)        the witness ledger: per actor, acceptances later refuted, challenges that replayed
  grounded(rep, id)        whether a version stands on ground: it, and every entity version it rests on by `refs`
                           and `requires`, transitively, is the effective version of an ELIGIBLE lineage
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
    n = dict(nodes.get(i) or {"id": i, "kind": "unavailable"})       # no record of it in this report: never "does not exist"
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


def frontier(rep, profile, actor, recs=None):
    """What waits for `actor` in this report: `attest` the lineage leaves whose guard waits only for attests by roles
    the actor holds (no open requirement, not its own, not yet attested or challenged by it); `pending` its own
    leaves whose guard waits; `challenged` its lineages a counted challenge holds; `asked` what was asked of it
    (asked_of: it needs the records, `recs` or the report's `_recs`)."""
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
    asked = [{"version": v, "lineage": root, "schema": rep["lineages"][root]["schema"]}
             for root, v in asked_of(rep, nodes, acted, actor, recs)]
    return {"actor": actor, "roles": sorted(roles), "attest": attest, "pending": pending, "challenged": challenged,
            "asked": asked}


def opened_for(body):
    """The actor a version's body addresses (`opened.for`, a string), or None."""
    o = body.get("opened") if isinstance(body, dict) else None
    f = o.get("for") if isinstance(o, dict) else None
    return f if isinstance(f, str) and f else None


def asked_of(rep, nodes, acted, actor, recs=None):
    """[(lineage, version)], sorted: each lineage's latest version whose body addresses `actor` (`opened.for`, any
    schema, a guard or none), not its own and not yet attested or challenged by it: what was asked of it (minds Q1
    81d731d3: a question to codex, which no guard waits on and which nothing showed it)."""
    recs = recs if recs is not None else rep.get("_recs") or {}
    out = []
    for root, lin in sorted(rep["lineages"].items()):
        v = lin["leaf"]
        if v is None or v in acted or nodes[v]["actor"] == actor:
            continue
        if opened_for((recs.get(v) or {}).get("body")) == actor:
            out.append((root, v))
    return out


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


def ledger(rep, recs=None):
    """The witness ledger, per actor: `accepted`, the versions whose guard the actor's acceptance counts toward;
    `refuted`, of those, [version, challenge] where a replayer attested `reproduces` on that challenge with `on` that
    version *later* than one of the actor's acceptances of it (an acceptance: an attest of the actor's on that version
    holding every member of the version's guard `match`, as the engine counts it; Codex challenge 049f0ec2b8c5: an
    attest short of the match was compared too). "Later" is read from citations first: the replay citing
    the acceptance, directly or through records it cites, is later whatever its date; the acceptance citing the replay
    is not; only where neither cites the other is it the dates, the acceptance's no later than the replay's (Codex
    challenge on c1cace09dd7c: an acceptance citing the refutation was read as refuted; Codex challenge caae1baae65e:
    citing a challenge not yet reproduced exempted a later refutation, and a date outranked a citation); `challenged`, the challenges the actor filed; `replayed`, of those, the
    ones a replayer reproduced on their own target. Read from the report (versions' accepted_by, challenges' replays,
    the graph, the records' refs and dates): it grants nothing, and no rule reads it. `at` is each filer's own word, which is
    why it orders only what no citation does. A challenge answered without a replay (a successor
    accepted) credits nobody here."""
    recs = rep.get("_recs", {}) if recs is None else recs     # {id: record}: a repository's report carries it
    _, _, into = index(rep)
    actor = {n[0]: n[3] for n in rep["graph"]["nodes"]}
    rows, reproduced, memo = {}, {}, {}

    def before(m, r):       # acceptance m, replay id r: a citation orders them first, `at` only where none does
        if _cites(recs, r, m["id"], memo):
            return True
        if _cites(recs, m["id"], r, memo):
            return False
        return m["at"] <= recs[r]["at"]
    row = lambda a: rows.setdefault(a, {"accepted": [], "refuted": [], "challenged": [], "replayed": []})
    for c, x in sorted(rep["challenges"].items()):
        row(actor[c])["challenged"].append(c)
        if any(on == x["target"] and v == "reproduces" for on, v, _ in x["replays"]):
            row(actor[c])["replayed"].append(c)
            replayers = {a for on, v, a in x["replays"] if on == x["target"] and v == "reproduces"}
            runs = [i for rel, i in into.get(c, []) if rel == "attest" and i in recs and recs[i]["actor"] in replayers
                    and recs[i]["body"].get("verdict") == "reproduces" and recs[i]["body"].get("on") == x["target"]]
            reproduced.setdefault(x["target"], []).append((c, runs))
    for v, g in sorted(rep["versions"].items()):
        for a in g["accepted_by"]:
            row(a)["accepted"].append(v)
            match = ((recs.get(v) or {}).get("guard") or {}).get("match")
            mine = [dict(recs[i], id=i) for rel, i in into.get(v, []) if rel == "attest" and i in recs
                    and recs[i]["actor"] == a and match is not None   # an attest the guard counts: every member of its
                    and all(recs[i]["body"].get(k, _NOWHERE) == x for k, x in match.items())]   # match (engine._attested)
            row(a)["refuted"] += [[v, c] for c, runs in reproduced.get(v, [])
                                  if any(before(m, r) for m in mine for r in runs)]
    return dict(sorted(rows.items()))


_NOWHERE = object()      # a member an attest does not have equals nothing, null included


def _cites(recs, x, y, memo):
    """Whether record `x` cites record `y`, directly or through records it cites (ids are hashes: no cycle)."""
    key = (x, y)
    if key not in memo:
        seen, todo = {x}, [x]
        while todo:
            for z in recs[todo.pop()].get("refs", []):
                if z == y:
                    seen = None
                    break
                if z in recs and z not in seen:
                    seen.add(z)
                    todo.append(z)
            if seen is None:
                break
        memo[key] = seen is None
    return memo[key]

def grounded(rep, i):
    """Whether entity version `i` is GROUNDED (minds' Grounded, proofs/Vars1/Grounded.lean, read over a Warrant report):
    it and every entity version it rests on, by `ref` and by `requires` (a required lineage through its effective
    version), transitively, is the effective version of a lineage whose reliance is ELIGIBLE. The least fixed point:
    a version on a cycle of grounds is not grounded. `failing` names each version of the closure that fails, with why:
    NOT_A_VERSION, UNAVAILABLE (no record of it here), NOT_EFFECTIVE (the version asked about is not its lineage's
    effective version, or a cited lineage has none), RELIANCE (its lineage is PENDING, CHALLENGED or FORK), CYCLE. A reference to no record of the report
    (a blob, or a record held elsewhere) is listed under `outside` and decides nothing: whether a closure's evidence
    must be present is R-EVIDENCE-PRESENCE (docs/V3.md §12). Pure, without recursion; ELIGIBLE alone does not
    propagate (a lineage is ELIGIBLE on a ground that is not), which is what this answers."""
    nodes, out, _ = index(rep)
    lineage = {v: root for root, lin in rep["lineages"].items() for v in lin["versions"]}

    recs = rep.get("_recs") or {}

    def grounds(v):
        """The grounds of v: each entity it cites by `ref`, or requires, read as its lineage (a lineage is named by any
        of its versions, its root as a rule): the lineage's effective version, or the version itself when none is. The
        ref that is v's own `answers` (the goal an obligation answers, which warrant.roadmap also cites) is a direction,
        not a ground: a met goal citing the obligations that answer it made each read CYCLE (minds: 88 failing on 18)."""
        gs, far = [], []
        answers = ((recs.get(v) or {}).get("body") or {}).get("answers")
        for rel, b in sorted(out.get(v, [])):
            if rel not in ("ref", "requires") or (rel == "ref" and b == answers):
                continue
            if b not in nodes:
                (far if rel == "ref" else gs).append(b)
            elif nodes[b]["kind"] == "entity":
                lin = rep["lineages"].get(lineage.get(b))
                gs.append((lin["effective"] or b) if lin else b)
        return sorted(set(gs)), far

    def local(v):
        if v not in nodes:
            return "UNAVAILABLE"
        if nodes[v]["kind"] != "entity" or v not in lineage:
            return "NOT_A_VERSION"
        lin = rep["lineages"][lineage[v]]
        if lin["effective"] != v:
            return "NOT_EFFECTIVE"
        return None if lin["reliance"] == "ELIGIBLE" else f"RELIANCE {lin['reliance']}"

    seen, order, outside, todo = {i}, [i], set(), [i]
    while todo:                                    # the closure, breadth first
        cur = todo.pop(0)
        if cur not in nodes:
            continue
        gs, far = grounds(cur)
        outside |= set(far)
        for g in gs:
            if g not in seen:
                seen.add(g)
                order.append(g)
                todo.append(g)
    on_cycle = set()                               # a node is on a cycle iff it reaches itself
    for v in order:
        stack, mark = [g for g in grounds(v)[0]], set()
        while stack:
            g = stack.pop()
            if g == v:
                on_cycle.add(v)
                break
            if g in mark or g not in nodes:
                continue
            mark.add(g)
            stack += grounds(g)[0]
    failing = []
    for v in order:
        why = local(v) or ("CYCLE" if v in on_cycle else None)
        if why:
            failing.append([v, why])
    return {"from": i, "grounded": not failing, "closure": len(order), "failing": failing, "outside": sorted(outside)}

SAID = ("attest", "challenge")


def frame(rep, roots):
    """The frame of lineage `roots` in a report (site/reader.mjs frame(), the same predicate, held to it by vectors):
    the sorted ids reached, breadth first, from every version of each root by (a) the graph's WALK edges outwards,
    (b) an attest or a challenge onto a member (inwards) and (c) every version of a member's lineage; only ids that
    are nodes of the view. What lies in other stores ((d) of the reader) is not this store's."""
    out, into = {}, {}
    for a, rel, b in rep["graph"]["edges"]:
        if rel not in WALK:
            continue
        out.setdefault(a, []).append(b)
        if rel in SAID:
            into.setdefault(b, []).append(a)
    root_of = {v: L for L, lin in rep["lineages"].items() for v in lin["versions"]}
    seen, todo = set(), []
    def reach(x):
        if x not in seen:
            seen.add(x)
            todo.append(x)
    for L in roots:
        for v in (rep["lineages"].get(L) or {}).get("versions", []):
            reach(v)
    k = 0
    while k < len(todo):
        cur = todo[k]
        k += 1
        for b in out.get(cur, []):
            reach(b)
        for a in into.get(cur, []):
            reach(a)
        if cur in root_of:
            for v in rep["lineages"][root_of[cur]]["versions"]:
                reach(v)
    nodes = {n[0] for n in rep["graph"]["nodes"]}
    return sorted(i for i in seen if i in nodes)


def answer(rep, query, data, adapter):
    lens = C.doc_id({"code": rep["code"], "adapter": adapter, "trust": rep["trust"], "profile": rep["profile"],
                     "query": query, **({"checkout": rep["checkout"]} if "checkout" in rep else {})})
    return {"root": rep["snapshot"], "lens": lens, "query": query, "data": data}
