"""Two views of a lineage, and what differs between them: the one form behind /changes, the lens comparison, the
sources of the floor, fragility and what-if.

A view is what a reader sees of a lineage page: what the lens draws (`lens.visible`) and the floor no lens decides
(state, reliance, the counted challenges that stand, whether it is grounded). Two views are compared by `difference`:
what appeared, what vanished, what in the floor moved; nothing differs exactly when the reader can tell the two apart
by nothing on the page (observational equivalence, relative to that reader and that lens). Every page that answers
"what would change if..." is this comparison with one thing varied:

    time       the store as the reader last marked it, and now                         (/changes)
    lens       one state, two cards                                                     (lens comparison)
    sources    one state, the authors' own records only, and all                        (the floor's sources)
    records    the store without some records (its challenges, an actor's), and now   (what_if, /fragile, /whatif)

`what_if` follows minds' (vars1.py `what_if`): the hypothesis is assessed on a candidate by the same engine, nothing
is filed and nothing moves; every lineage whose view changes is reported with its view before and after and the
witness of the change, and equal consequences give an equal digest. Here a hypothesis removes records: the store is
append-only, so a subset of it is a state the engine assesses exactly."""
import json

from warrant import jcs as C
from warrant import graph as G


def observe(serve, rep, d, card, keep=None):
    """{"visible", "floor"} of lineage page `d` under `card`; with `keep(item)`, of the page holding only the activity
    it keeps (a challenge it drops stands no more)."""
    from warrant_agent import lens as LZ
    if keep is not None:
        d = dict(d, versions=[dict(v, on=[x for x in v["on"] if keep(x)]) for v in d["versions"]])
    kept = {x["id"] for v in d["versions"] for x in v["on"]}
    g = d["grounded"]
    standing = [s for s in serve.standing(rep, d) if keep is None or s[0] in kept]
    return {"visible": LZ.visible(d, card),
            "floor": {"state": d["state"], "reliance": d["reliance"], "standing": standing,
                      "grounded": None if g is None else g["grounded"]}}


def difference(a, b):
    """{"appeared", "vanished", "moved"} from view `a` to view `b` (`a` None: the lineage is new in `b`)."""
    va, fa = (a["visible"], a["floor"]) if a else (set(), None)
    vb, fb = b["visible"], b["floor"]
    moved = {"new": (None, True)} if fa is None else {k: (fa[k], fb[k]) for k in fb if fa[k] != fb[k]}
    return {"appeared": sorted(vb - va), "vanished": sorted(va - vb), "moved": moved}


def same(diff):
    return not (diff["appeared"] or diff["vanished"] or diff["moved"])


def candidates(rep_a, rep_b, touched_from_elsewhere=()):
    """({lineage: the records of b not in a touching it}, those record ids): the lineages of `b` such a record touches
    (an entity of it, an attest or a challenge on one of its versions), those a record of another store points at
    (an observation in a reader's own store), and those whose state, reliance or leaf moved (G.delta: a record
    elsewhere can move them)."""
    new = set(rep_b["_recs"]) - set(rep_a["_recs"])
    roots = {v: L for L, lin in rep_b["lineages"].items() for v in lin["versions"]}
    out = {}
    for i in new:
        r = rep_b["_recs"][i]
        t = r["body"].get("target") if r["kind"] in ("attest", "challenge") else i
        if t in roots:
            out.setdefault(roots[t], set()).add(i)
    for i, t in touched_from_elsewhere:
        if t in roots:
            out.setdefault(roots[t], set()).add(i)
    d = G.delta(rep_a, rep_b)
    for L in set(d["changed"]) | set(d["lineages_added"]):
        out.setdefault(L, set())
    return out, new


def _with(d, foreign):
    """`d` with the items filed in other stores (`foreign(d)`: {version: [item]}) among each version's activity."""
    if d is None or foreign is None:
        return d
    extra = foreign(d)
    for v in d["versions"]:
        v["on"] = sorted(v["on"] + extra.get(v["id"], []), key=lambda x: (x["at"], x["id"]))
    return d


def delta(serve, rep_a, rep_b, card_of_schema, foreign_a=None, foreign_b=None, touched_from_elsewhere=()):
    """([{lineage, schema, title, label, appeared, vanished, floor_before, floor_after}] of the lineages whose view
    differs from state `a` to state `b`, the record ids of `b` (of this store and of others) those changes account
    for). A page shows observations filed in other stores, so each state is read with its own (foreign_a, foreign_b)."""
    touched, _ = candidates(rep_a, rep_b, touched_from_elsewhere)
    rows, accounted = [], set()
    for L in sorted(touched):
        d1 = _with(serve.lineage(rep_b, L), foreign_b)
        if d1 is None:
            continue
        card = card_of_schema(d1["schema"])
        after = observe(serve, rep_b, d1, card)
        d0 = _with(serve.lineage(rep_a, L), foreign_a) if L in rep_a["lineages"] else None
        before = observe(serve, rep_a, d0, card) if d0 else None
        diff = difference(before, after)
        if same(diff):
            continue
        accounted |= touched[L] | {i for i, _ in diff["appeared"]}
        rows.append({"lineage": L, "schema": d1["schema"], "title": d1["title"], "label": d1["label"],
                     "appeared": diff["appeared"], "vanished": diff["vanished"],
                     "floor_before": before["floor"] if before else None, "floor_after": after["floor"]})
    return rows, accounted


def digest(rows):
    """One digest of a set of consequences: equal consequences give an equal digest, whatever produced them."""
    core = [{"lineage": r["lineage"], "appeared": r["appeared"], "vanished": r["vanished"],
             "before": r["floor_before"], "after": r["floor_after"]} for r in rows]
    return C.doc_id(json.loads(json.dumps(core)))


def what_if(serve, root, snap, drop, card_of_schema, now=None):
    """What would follow if the store held none of the records `drop` names: that state, assessed by the same engine
    on a candidate (nothing filed, nothing moved), compared with the store as it is. {"rows": every lineage whose view
    differs, from the hypothesis to now; "digest"; "dropped": how many records the hypothesis removes}."""
    from warrant_agent import changes as CH
    keep = set(snap.lines) - set(drop)
    hyp = CH.report_of(root, CH.subset(snap, keep))
    now = CH.report_of(root, snap) if now is None else now
    rows, _ = delta(serve, hyp, now, card_of_schema)
    return {"rows": rows, "digest": digest(rows), "dropped": len(set(snap.lines) & set(drop))}


HYPOTHESES = {"challenges": "без жодного заперечення", "actor": "без жодного запису актора"}


def dropped(rep, without):
    """The record ids a hypothesis removes: `challenges` (every challenge), or `actor:NAME` (every record NAME signed);
    None for a hypothesis this module does not know."""
    if without == "challenges":
        return {i for i, r in rep["_recs"].items() if r["kind"] == "challenge"}
    if without.startswith("actor:") and len(without) > 6:
        return {i for i, r in rep["_recs"].items() if r["actor"] == without[6:]}
    return None
