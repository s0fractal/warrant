#!/usr/bin/env python3
"""How writing and reading a store costs as it grows (F44).

    python3 tools/bench_store.py [--sizes 100,1000,10000] [--actors 1,10] [--grow-max N]
                                 [--probe K] [--fresh] [--verdicts] [--impl PATH] [--json OUT]

For each size N and actor count A, a fresh store in a temporary directory is filled with
N duty records, the A actors taking turns, each record extending its actor's chain.

- N <= --grow-max: every record is filed by `Store.append` and timed; the table gives the
  mean time of the first and of the last 100 appends and the total.
- N > --grow-max: N - K records are filed directly (`Store.put_record` with the `prev` an
  append would choose, untimed) and the last K by `Store.append`, timed. "first 100" is
  then the first-100 figure measured for the largest grown size with the same A, and
  the total is extrapolated as N x (first + last) / 2: per-append cost growing linearly
  in N, which is what a cold head read costs. Extrapolated totals are marked "~".

--fresh forgets, before every append, what this process remembers of earlier reads (the
verdicts in warrant.store._MEMO, where the package has them): each append then costs what a
one-shot `warrant file` costs, apart from starting Python. --verdicts gives the writer a
verdicts directory of its own (Store(root, verdicts=DIR), `warrant file --verdicts DIR`;
F44): with --fresh, what a one-shot append with that option costs.

At the end of each run the whole store is read cold (the process's memory emptied before
each): `Snapshot.read`, `authentic` under the actors' trust, `engine.assess`, each timed
once; with --verdicts also `engine.assess(verdicts=DIR)` from a receiver's index that one
earlier assessment filled (memory emptied), its report asserted equal to the cold one.
--impl names the checkout whose
`warrant` package is measured (default: this one), so the same script measures master.
Only public calls are used: Store.append, Store.put_record, Snapshot.read, authentic,
engine.assess. Nothing here is a test; tests/store_index_test.py holds the guarantees."""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ACTORS = ("claude", "codex", "owner", "probe", "gemini", "kimi", "monday", "astra", "argon", "vesta")


def body(R, actor, i):
    return R.duty(actor, f"bench duty {i}", ["reviewer"], {"attest": {}}, accept_by=["reviewer"])


def forget():
    from warrant import store as S
    getattr(S, "_MEMO", {}).clear()


def run(W, n, actors, grow_max, probe, first_of, fresh, verdicts):
    from warrant import engine as E
    from warrant import records as R
    from warrant.store import Snapshot, Store, Trust
    tmp = Path(tempfile.mkdtemp(prefix="warrant-bench-"))
    try:
        st = (Store(tmp / "store", verdicts=tmp / "verdicts") if verdicts else Store(tmp / "store")).init()
        names = ACTORS[:actors]
        keys = {a: W.Key.generate() for a in names}
        trust = Trust(Trust.document([(a, k.public) for a, k in keys.items()]))
        own = {a: Trust(Trust.document([(a, keys[a].public)])) for a in names}
        grown = n <= grow_max
        direct = 0 if grown else n - probe
        heads = {}
        for i in range(direct):
            a = names[i % actors]
            heads[a] = st.put_record(R.record("duty", a, 1000 + i, body(R, a, i), prev=heads.get(a)), keys[a])
        times = []
        for i in range(direct, n):
            a = names[i % actors]
            if fresh:
                forget()
            t = time.perf_counter()
            st.append("duty", a, 1000 + i, body(R, a, i), keys[a], own[a])
            times.append(time.perf_counter() - t)
        forget()
        t = time.perf_counter()
        snap = Snapshot.read(st.root)
        t_read = time.perf_counter() - t
        t = time.perf_counter()
        good, bad = snap.authentic(trust)
        t_auth = time.perf_counter() - t
        forget()
        t = time.perf_counter()
        rep = E.assess(snap, trust, 10 ** 9, E.profile())
        t_assess = time.perf_counter() - t
        t_indexed = None
        if verdicts:                # a receiver's own verdicts (assess(verdicts=DIR)): filled once, then read
            E.assess(snap, trust, 10 ** 9, E.profile(), verdicts=tmp / "receiver")
            forget()
            t = time.perf_counter()
            again = E.assess(snap, trust, 10 ** 9, E.profile(), verdicts=tmp / "receiver")
            t_indexed = time.perf_counter() - t
            assert again == rep, "a receiver's verdicts must not change the report"
        assert len(good) == n and not bad and not rep["chains"]["forks"] and not rep["chains"]["unanchored"], \
            "the bench store must be n authentic, anchored, unforked records"
        last = sum(times[-100:]) / len(times[-100:])
        first = sum(times[:100]) / len(times[:100]) if grown else first_of
        total = sum(times) if grown else n * (first + last) / 2
        return {"n": n, "actors": actors, "fresh": fresh, "verdicts": verdicts, "grown": grown, "appends_timed": len(times),
                "first100_ms": round(first * 1000, 2), "last100_ms": round(last * 1000, 2),
                "total_s": round(total, 2), "total_extrapolated": not grown,
                "read_ms": round(t_read * 1000, 1), "authentic_ms": round(t_auth * 1000, 1),
                "assess_ms": round(t_assess * 1000, 1),
                "assess_verdicts_ms": None if t_indexed is None else round(t_indexed * 1000, 1)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def table(rows):
    out = ["| N | actors | first 100 (ms/append) | last 100 (ms/append) | total (s) | Snapshot.read (ms) | authentic (ms) | assess (ms) | assess, receiver index (ms) |",
           "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        last = f"{r['last100_ms']}" + ("" if r["grown"] else f" (last {r['appends_timed']})")
        total = ("~" if r["total_extrapolated"] else "") + f"{r['total_s']}"
        out.append(f"| {r['n']} | {r['actors']} | {r['first100_ms']} | {last} | {total} | {r['read_ms']} | "
                   f"{r['authentic_ms']} | {r['assess_ms']} | {r.get('assess_verdicts_ms') or '—'} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="100,1000,10000")
    ap.add_argument("--actors", default="1,10")
    ap.add_argument("--grow-max", type=int, default=10000)
    ap.add_argument("--probe", type=int, default=100)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--verdicts", action="store_true")
    ap.add_argument("--impl", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--json")
    a = ap.parse_args()
    sys.path.insert(0, a.impl)
    import warrant as W
    print(f"warrant from {Path(W.__file__).parent}", file=sys.stderr)
    rows, first = [], {}
    for actors in [int(x) for x in a.actors.split(",")]:
        for n in [int(x) for x in a.sizes.split(",")]:
            r = run(W, n, actors, a.grow_max, a.probe, first.get(actors), a.fresh, a.verdicts)
            if r["grown"]:
                first[actors] = r["first100_ms"] / 1000
            rows.append(r)
            print(json.dumps(r), file=sys.stderr, flush=True)
    print(table(rows))
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1) + "\n")


if __name__ == "__main__":
    main()
