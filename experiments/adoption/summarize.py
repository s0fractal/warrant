#!/usr/bin/env python3
"""The table per arm x model x task, and the two decision rules of PLAN.md evaluated, printed plainly.

    python3 summarize.py [round-1] [--entry-round round-2]

R2 (outcome) is taken on the round named first (round-1: the entry as registered), once. R1 (entry) is taken on
the same round, and, when R1's "both < 6" branch allowed a second round of arms S and A with a revised entry, on
--entry-round as well. A rule over fewer runs than it names is printed as incomplete, never decided.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COLS = ("answered", "success", "wrong_credit", "used_kit", "read_notes", "read_store", "ran_tests")


def load(name):
    return [json.loads(f.read_text()) for f in sorted((HERE / name).glob("*/score.json"))]


def table(rows):
    out = ["arm model  task   n " + " ".join(f"{c:>12}" for c in COLS) + "     cost$"]
    keys = sorted({(r["arm"], r["model_alias"], r["task"]) for r in rows}, key=lambda k: ("NSA".index(k[0]), k[1], k[2]))
    for k in keys:
        rs = [r for r in rows if (r["arm"], r["model_alias"], r["task"]) == k]
        cost = sum(r["cost_usd"] or 0 for r in rs)
        out.append(f"{k[0]:3} {k[1]:6} {k[2]:4} {len(rs):3} " + " ".join(f"{sum(r[c] for r in rs):12d}" for c in COLS)
                   + f"  {cost:8.3f}")
    for arm in "NSA":
        rs = [r for r in rows if r["arm"] == arm]
        if rs:
            out.append(f"{arm:3} {'all':6} {'all':4} {len(rs):3} " + " ".join(f"{sum(r[c] for r in rs):12d}" for c in COLS)
                       + f"  {sum(r['cost_usd'] or 0 for r in rs):8.3f}")
    return "\n".join(out)


def count(rows, arm, col):
    rs = [r for r in rows if r["arm"] == arm]
    return len(rs), sum(r[col] for r in rs)


def r1(rows):
    (ns, s), (na, a) = count(rows, "S", "used_kit"), count(rows, "A", "used_kit")
    head = f"R1 entry: used_kit S = {s}/{ns}, A = {a}/{na}."
    if ns != 18 or na != 18:
        return head + " INCOMPLETE: the rule is over 18 runs of each arm; not decided."
    if s >= 12:
        return head + " S >= 12: an agent finds the store by itself; the entry is not the bottleneck."
    if s < 6 and a >= 12:
        return head + " S < 6 and A >= 12: the entry is what makes the store visible -> ship it (`warrant init` writes the block)."
    if s < 6 and a < 6:
        return head + (" Both < 6: the candidate entry does not work; ONE revision of entry/ alone is allowed (tasks, "
                       "scorer, flags frozen) and one more round of arms S and A.")
    return head + " No rule fires (S < 6 with 6 <= A < 12, or 6 <= S < 12): inconclusive for the entry."


def r2(rows):
    (nn, n), (na, a) = count(rows, "N", "wrong_credit"), count(rows, "A", "wrong_credit")
    head = f"R2 outcome: wrong_credit N = {n}/{nn}, A = {a}/{na}."
    if nn != 18 or na != 18:
        return head + " INCOMPLETE: the rule is over 18 runs each of N and A; not decided."
    if n <= 2:
        return head + " N <= 2: the tasks do not discriminate (the baseline is already right) -> no advantage shown; nothing is claimed for agents."
    if n >= 4 and a <= n / 2:
        return head + " N >= 4 and A <= N/2: an advantage on these tasks, reported with its caveats."
    return head + " No advantage shown."


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("round", nargs="?", default="round-1")
    ap.add_argument("--entry-round")
    a = ap.parse_args()
    rows = load(a.round)
    if not rows:
        print(f"no scored runs under {a.round}/")
        return 1
    print(f"{a.round}: {len(rows)} runs, ${sum(r['cost_usd'] or 0 for r in rows):.2f}")
    print(table(rows))
    leaks = [r["run"] for r in rows if r.get("leaks")]
    errors = [r["run"] for r in rows if r.get("exit") not in (0,) or r.get("is_error")]
    print(f"runs with a leak-scan hit: {leaks or 'none'}; runs that ended in an error or timeout: {errors or 'none'}")
    print(r1(rows))
    print(r2(rows))
    if a.entry_round:
        rows2 = load(a.entry_round)
        print(f"{a.entry_round}: {len(rows2)} runs")
        print(table(rows2))
        print(r1(rows2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
