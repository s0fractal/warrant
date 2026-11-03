#!/usr/bin/env python3
"""R-AGENT-CLOCK: how long an assessment takes on a store at the agent's store_bytes bound (64 MiB), for three shapes:
flat (many short lineages, each attested), long (lineages of thousands of versions), refs (records that each cite as many
others as a line holds). A measurement run by hand, not a suite: the numbers belong to the machine that ran it.

    python3 tests/assess_bound.py [--bytes N]"""
import argparse
import json
import platform
import sys
import time

from world import KEYS, Repo                # world puts the checkout on the path

from warrant import bootstrap as B
from warrant import engine as E
from warrant import records as R
from warrant import store as ST

BOUND = 64 << 20
OPEN = next(s for s in B.SCHEMAS if s["name"] == "obligation@1")["states"]["open"]


class Writer:
    """Signed lines appended to one store's records.jsonl: each actor's chain kept here, one write per batch."""

    def __init__(self, r):
        self.r, self.t, self.bytes = r, r.t + 1, sum(map(len, r.store.lines()))
        self.heads = {a: E.head(r.store.snapshot(), r.trust, a)["id"] for a in ("alice", "bob")}
        self.out = open(r.dot / "records.jsonl", "ab")

    def file(self, actor, kind, body, schema=None, lineage=None, refs=(), guard=None):
        rec = R.record(kind, actor, self.t, body, schema, lineage, refs, guard)
        rid, line = R.line(dict(rec, prev=self.heads[actor]), KEYS[actor])
        self.heads[actor] = rid
        self.out.write(line)
        self.bytes += len(line)
        return rid


def entity(w, text, lineage=None):
    return w.file("alice", "entity", {"state": "open", "statement": text, "serves": []}, "obligation@1", lineage, guard=OPEN)


def flat(w, limit):
    i = 0
    while w.bytes < limit:
        x = entity(w, f"s{i} " + "x" * 200)
        w.file("bob", "attest", {"verdict": "accept", "target": x}, refs=[x])
        i += 1


def long(w, limit):
    while w.bytes < limit:
        cur = None
        for i in range(ST.LIMITS["depth"] // 2):
            cur = entity(w, f"v{i} " + "x" * 200, cur)


def refs(w, limit):
    ids = [entity(w, f"s{i}") for i in range(800)]
    i = 0
    while w.bytes < limit:
        w.file("bob", "attest", {"verdict": "accept", "target": ids[i % 800], "note": i}, refs=sorted(ids))
        i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bytes", type=int, default=BOUND)
    a = ap.parse_args()
    out = {"bound_bytes": a.bytes, "python": platform.python_version(), "machine": platform.machine(), "shapes": {}}
    for name, make in (("flat", flat), ("long", long), ("refs", refs)):
        r = Repo()
        w = Writer(r)
        make(w, a.bytes)
        w.out.close()
        t1 = time.time()
        snap = r.store.snapshot()
        t2 = time.time()
        rep = E.assess(snap, r.trust, r.profile)
        t3 = time.time()
        got = {"records": len(snap.lines), "store_bytes": w.bytes, "read_s": round(t2 - t1, 2), "assess_s": round(t3 - t2, 2),
               "lineages": len(rep["lineages"]), "rejected": len(rep["rejected"])}
        out["shapes"][name] = got
        print(name, got, file=sys.stderr, flush=True)
        r.tmp.cleanup()
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
