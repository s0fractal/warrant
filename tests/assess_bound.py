#!/usr/bin/env python3
"""R-AGENT-CLOCK: how long the agent's assessment takes on a store at or below its store_bytes bound (64 MiB), for three
shapes: flat (many short lineages, each attested), long (lineages of thousands of versions), refs (records that each cite
as many others as a line holds). A measurement run by hand, not a suite: the numbers belong to the machine that ran it.

Each store is built to at most the bound (a line that would cross it is not written), then read and assessed the way the
agent does: a repository workspace whose limits set store_bytes to the bound, admitted by Workspace.open (records and
blobs counted before a byte is parsed), read by Store.snapshot (the engine's LIMITS), assessed by the agent's _assess and
View.report. A store the agent refuses is reported as refused, with its code, and never timed: the run then exits 1.
agent_test.py (B01, B02) runs this at a small bound.

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
from warrant_agent import api
from warrant_agent.config import Config
from warrant_agent.errors import AgentError

BOUND = 64 << 20
OPEN = next(s for s in B.SCHEMAS if s["name"] == "obligation@1")["states"]["open"]


class Full(Exception):
    """The next line would carry the store past the bound."""


class Writer:
    """Signed lines appended to one store's records.jsonl, never past `limit` bytes of records and blobs together (the
    sum the agent admits): each actor's chain kept here."""

    def __init__(self, r, limit):
        self.r, self.t, self.limit = r, r.t + 1, limit
        self.bytes = stored(r)
        self.heads = {a: E.head(r.store.snapshot(), r.trust, a)["id"] for a in ("alice", "bob")}
        self.out = open(r.dot / "records.jsonl", "ab")

    def file(self, actor, kind, body, schema=None, lineage=None, refs=(), guard=None):
        rec = R.record(kind, actor, self.t, body, schema, lineage, refs, guard)
        rid, line = R.line(dict(rec, prev=self.heads[actor]), KEYS[actor])
        if self.bytes + len(line) > self.limit:
            raise Full
        self.heads[actor] = rid
        self.out.write(line)
        self.bytes += len(line)
        return rid


def stored(r):
    """records.jsonl and the blobs, in bytes: what Workspace.open sums."""
    blobs = sum(p.stat().st_size for p in r.store.blobs.iterdir()) if r.store.blobs.is_dir() else 0
    return (r.store.file.stat().st_size if r.store.file.is_file() else 0) + blobs


def entity(w, text, lineage=None):
    return w.file("alice", "entity", {"state": "open", "statement": text, "serves": []}, "obligation@1", lineage, guard=OPEN)


def flat(w):
    i = 0
    while True:
        x = entity(w, f"s{i} " + "x" * 200)
        w.file("bob", "attest", {"verdict": "accept", "target": x}, refs=[x])
        i += 1


def long(w):
    while True:
        cur = None
        for i in range(ST.LIMITS["depth"] // 2):
            cur = entity(w, f"v{i} " + "x" * 200, cur)


def refs(w):
    ids = [entity(w, f"s{i}") for i in range(800)]
    i = 0
    while True:
        w.file("bob", "attest", {"verdict": "accept", "target": ids[i % 800], "note": i}, refs=sorted(ids))
        i += 1


SHAPES = (("flat", flat), ("long", long), ("refs", refs))


def measure(make, limit):
    """One store built by `make` up to `limit`, then admitted, read and assessed as the agent does it: the timings, or
    {"refused": code} when the agent refuses the store (nothing is timed then)."""
    r = Repo()
    try:
        w = Writer(r, limit)
        try:
            make(w)
        except Full:
            pass
        finally:
            w.out.close()
        size = stored(r)
        ws = Config({"agent_api": "warrant-agent/3",
                     "workspaces": {"w": {"repo": str(r.root), "limits": {"store_bytes": limit}}}}).workspaces["w"]
        try:
            t1 = time.time()
            snap = ws.open().snapshot()              # the agent's size admission, then the engine's LIMITS
            t2 = time.time()
            _, view, _, _ = api._assess(ws, snap)
            rep = view.report()
            t3 = time.time()
        except (AgentError, ST.Refused, R.Invalid) as e:
            return {"refused": getattr(e, "code", type(e).__name__), "store_bytes": size, "bound_bytes": limit}
        return {"records": len(snap.lines), "store_bytes": size, "bound_bytes": limit, "read_s": round(t2 - t1, 2),
                "assess_s": round(t3 - t2, 2), "lineages": len(rep["lineages"]), "rejected": len(rep["rejected"])}
    finally:
        r.tmp.cleanup()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bytes", type=int, default=BOUND)
    a = ap.parse_args()
    out = {"bound_bytes": a.bytes, "python": platform.python_version(), "machine": platform.machine(),
           "platform": platform.platform(), "processor": platform.processor(), "shapes": {}}
    for name, make in SHAPES:
        got = measure(make, a.bytes)
        out["shapes"][name] = got
        print(name, got, file=sys.stderr, flush=True)
    print(json.dumps(out, indent=1, sort_keys=True))
    return 1 if any("refused" in g for g in out["shapes"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
