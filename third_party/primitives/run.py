#!/usr/bin/env python3
"""Hold an implementation to the primitives: one vector at a time, through its probe.

    python3 run.py --candidate "warrant-rs probe" [--class verify-sig,p256-decode] [--json]

The candidate is any program that reads one `warrant-conformance/1` request on
stdin and prints one response (the protocol of warrant's conformance pack):

    {"warrant_conformance": "1", "id": "...", "class": "verify-sig", "input": {...}}
    -> {"warrant_conformance": "1", "id": "...", "output": {...}}
    -> {"warrant_conformance": "1", "id": "...", "unsupported": "why"}

Outcomes per vector: PASS, FAIL, UNRUN (declined or no answer). A MUST-REJECT
vector that is accepted is reported by name. Exit 0 only when every vector of
every requested class PASSes. The pack's MANIFEST is checked before anything runs.
No reference implementation is imported or run by this file.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def verify_manifest():
    lines = (ROOT / "MANIFEST.sha256").read_text().splitlines()
    bad = []
    for line in lines:
        digest, name = line.split("  ", 1)
        p = ROOT / name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            bad.append(name)
    return bad


def compare(expect, output):
    if not isinstance(output, dict):
        return "no output object"
    for key, want in expect.items():
        if output.get(key) != want:
            return f"{key}: expected {json.dumps(want)[:80]}, got {json.dumps(output.get(key))[:80]}"
    return None


def ask(argv, vector, cls, timeout):
    req = {"warrant_conformance": "1", "id": vector["id"], "class": cls, "input": vector["input"]}
    try:
        r = subprocess.run(argv, input=json.dumps(req), capture_output=True, text=True, timeout=timeout, check=False)
        resp = json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        return "UNRUN", f"no answer: {type(e).__name__}"
    if not isinstance(resp, dict) or resp.get("id") != vector["id"]:
        return "UNRUN", "answer for another request"
    if "unsupported" in resp or "error" in resp:
        return "UNRUN", str(resp.get("unsupported") or resp.get("error"))[:120]
    why = compare(vector["expect"], resp.get("output"))
    return ("FAIL", why) if why else ("PASS", "")


def run_classes(argv, classes, timeout):
    results = {}
    for cls in classes:
        doc = json.loads((ROOT / "vectors" / f"{cls}.json").read_text())
        rows = []
        for v in doc["vectors"]:
            outcome, why = ask(argv, v, cls, timeout)
            rows.append({"id": v["id"], "polarity": v["polarity"], "outcome": outcome, "why": why})
        results[cls] = rows
    return results


def print_table(results):
    print(f"{'class':14} {'vectors':>7} {'PASS':>5} {'FAIL':>5} {'UNRUN':>6}")
    for cls, rows in results.items():
        n = {o: sum(r["outcome"] == o for r in rows) for o in ("PASS", "FAIL", "UNRUN")}
        print(f"{cls:14} {len(rows):7} {n['PASS']:5} {n['FAIL']:5} {n['UNRUN']:6}")
    for cls, rows in results.items():
        for r in (r for r in rows if r["outcome"] == "FAIL"):
            tag = "MUST-REJECT ACCEPTED" if r["polarity"] == "negative" else "FAIL"
            print(f"  {tag:22} {r['id']}  {r['why']}")
        unrun = [r for r in rows if r["outcome"] == "UNRUN"]
        if unrun:
            print(f"  UNRUN {len(unrun):3} in {cls}: {unrun[0]['why']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--class", dest="classes", default="")
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    bad = verify_manifest()
    if bad:
        print(f"PACK INTEGRITY: {len(bad)} file(s) do not match MANIFEST.sha256: {bad[:3]}")
        return 2
    catalog = json.loads((ROOT / "catalog.json").read_text())
    wanted = [c for c in args.classes.split(",") if c] or list(catalog["classes"])
    results = run_classes(args.candidate.split(), wanted, args.timeout)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_table(results)
    ok = all(r["outcome"] == "PASS" for rows in results.values() for r in rows)
    print("\nPRIMITIVES:", "ALL PASS" if ok else "NOT ALL PASS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
