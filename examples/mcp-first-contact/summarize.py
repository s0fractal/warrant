#!/usr/bin/env python3
"""Aggregate the per-run scores of one round: python3 summarize.py ROUND [--json]."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def rows(rnd):
    return [json.loads(p.read_text()) for p in sorted((HERE / f"round-{rnd}").glob("*.score.json"))]


def table(rnd):
    out = {}
    for s in rows(rnd):
        k = (s["task"], s["model"])
        g = out.setdefault(k, {"n": 0, "success": 0, "wrong_credit": 0, "grounded": 0, "tool_calls": 0,
                               "tool_errors": 0, "schema_errors": 0, "repeated_errors": 0, "stuck": 0,
                               "cost_usd": 0.0, "duration_s": 0.0, "output_tokens": 0})
        g["n"] += 1
        for f in ("success", "wrong_credit", "stuck"):
            g[f] += bool(s[f])
        if "grounded" in s:
            g["grounded"] = g.get("grounded") or 0
            g["grounded"] += bool(s["grounded"])
        else:
            g["grounded"] = None
        for f in ("tool_calls", "tool_errors", "repeated_errors", "output_tokens"):
            g[f] += s[f] or 0
        g["schema_errors"] += sum(c.endswith(":SCHEMA") for c in s["error_codes"])
        g["cost_usd"] += s["cost_usd"] or 0
        g["duration_s"] += s["duration_s"] or 0
    return out


def main():
    rnd = sys.argv[1]
    t = table(rnd)
    if "--json" in sys.argv:
        print(json.dumps({f"{a}/{b}": v for (a, b), v in sorted(t.items())}, indent=1))
        return
    print(f"| round {rnd} | n | success | wrong credit | grounded | calls/run | errors/run | repeated/run | "
          "stuck | cost $ | s/run |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    tot = {"cost": 0.0}
    for (task, model), g in sorted(t.items()):
        n = g["n"]
        grounded = "-" if g["grounded"] is None else f"{g['grounded']}/{n}"
        tot["cost"] += g["cost_usd"]
        print(f"| {task} {model} | {n} | {g['success']}/{n} | {g['wrong_credit']}/{n} | {grounded} | "
              f"{g['tool_calls'] / n:.1f} | {g['tool_errors'] / n:.1f} | {g['repeated_errors'] / n:.1f} | "
              f"{g['stuck']}/{n} | {g['cost_usd']:.3f} | {g['duration_s'] / n:.0f} |")
    print(f"\ntotal cost ${tot['cost']:.3f}")


if __name__ == "__main__":
    main()
