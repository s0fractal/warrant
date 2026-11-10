"""What changed for a reader: the difference between two states of a store as the reader sees them.

The past state is a set of records the reader had seen (a mark: their ids, kept per reader and store), assessed by
the same engine as the present: records are never removed, so it is reproduced exactly. Two states are the same for
the reader on a lineage when its page under the reader's lens shows the same: the floor (state, reliance, the
counted challenges that stand, whether it is grounded) and what the lens draws (`lens.visible`: each body member of
each version, each attest and challenge). Records are content-addressed, so a shown member cannot change without a
new id. A lineage that differs is listed with its witness: what appeared, what vanished, what in the floor moved.
New records that change nothing the reader sees are counted, never listed one by one.

This is observational equivalence relative to the reader: under another lens the same two states may differ, or
not. It sees only the records of each store; a store's completeness stays UNATTESTED."""
import json
import os
import time
from pathlib import Path

from warrant import home as H
from warrant import repo as RP
from warrant import records as R
from warrant import engine as EN
from warrant import graph as G
from warrant.store import Snapshot

DAY = 86400


def subset(snap, keep):
    """The snapshot of the records of `snap` whose ids are in `keep`, with all its blobs."""
    lines = [raw for raw in snap.raw if _rid(raw) in keep]
    return Snapshot(lines, snap.blobs)


def _rid(raw):
    try:
        return R.rid(json.loads(raw)["record"])
    except (ValueError, KeyError, TypeError):
        return None


def before(snap, cutoff):
    """The ids of the records filed (by their own `at`) before `cutoff`: the default past when no mark exists."""
    return {i for i, envs in snap.lines.items() if envs[0]["record"]["at"] < cutoff}


def report_of(root, snap):
    trust, profile, _ = RP.Repo(root).config()
    v = EN.View(snap, trust, profile)
    rep = v.report()
    rep["_recs"], rep["_basis"] = v.recs, v.basis
    return rep


def floor(serve, rep, d):
    g = d["grounded"]
    return {"state": d["state"], "reliance": d["reliance"], "standing": serve.standing(rep, d),
            "grounded": None if g is None else g["grounded"]}


def candidates(rep0, rep1, touched_from_elsewhere=()):
    """({lineage: the new records touching it}, new record ids): the lineages of rep1 a new record touches (an entity
    of it, an attest or a challenge on one of its versions), those a new record of another store points at (a
    reaction in a reader's own store), and those whose state, reliance or leaf moved (G.delta: a record elsewhere
    can move them)."""
    new = set(rep1["_recs"]) - set(rep0["_recs"])
    roots = {v: L for L, lin in rep1["lineages"].items() for v in lin["versions"]}
    out = {}
    for i in new:
        r = rep1["_recs"][i]
        t = r["body"].get("target") if r["kind"] in ("attest", "challenge") else i
        if t in roots:
            out.setdefault(roots[t], set()).add(i)
    for i, t in touched_from_elsewhere:
        if t in roots:
            out.setdefault(roots[t], set()).add(i)
    d = G.delta(rep0, rep1)
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


def delta(serve, rep0, rep1, card_of_schema, foreign0=None, foreign1=None, touched_from_elsewhere=()):
    """([{lineage, schema, title, label, appeared, vanished, floor_before, floor_after}] of the lineages whose page
    differs for the reader, the new record ids (of this store and of others) that those changes account for): two
    states are the same for the reader on a lineage when its floor and what its lens draws are the same. A page
    shows reactions filed in other stores, so each state is read with that state's reactions (foreign0, foreign1)."""
    from warrant_agent import lens as LZ
    touched, _ = candidates(rep0, rep1, touched_from_elsewhere)
    rows, accounted = [], set()
    for L in sorted(touched):
        d1 = _with(serve.lineage(rep1, L), foreign1)
        if d1 is None:
            continue
        card = card_of_schema(d1["schema"])
        v1, f1 = LZ.visible(d1, card), floor(serve, rep1, d1)
        d0 = _with(serve.lineage(rep0, L), foreign0) if L in rep0["lineages"] else None
        v0, f0 = (LZ.visible(d0, card), floor(serve, rep0, d0)) if d0 else (set(), None)
        if v0 == v1 and f0 == f1:
            continue
        accounted |= touched[L] | {i for i, _ in v1 - v0}
        rows.append({"lineage": L, "schema": d1["schema"], "title": d1["title"], "label": d1["label"],
                     "appeared": sorted(v1 - v0), "vanished": sorted(v0 - v1), "floor_before": f0, "floor_after": f1})
    return rows, accounted


class Marks:
    """Where a reader's last look lives: {reader: {store: [record id]}} in a private file beside Home."""

    def __init__(self, path=None):
        self.path = Path(path) if path else H.path().parent / "serve-seen.json"

    def load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def get(self, reader, store):
        got = self.load().get(reader or "", {}).get(store)
        return set(got) if isinstance(got, list) else None

    def set(self, reader, marks):
        doc = self.load()
        doc[reader or ""] = {s: sorted(ids) for s, ids in marks.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(doc))
        os.replace(tmp, self.path)


def since_text(mark_at):
    return "останньої позначки" if mark_at else f"останньої доби (за датами записів, до {time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() - DAY))})"
