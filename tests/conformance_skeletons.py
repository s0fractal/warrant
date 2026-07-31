#!/usr/bin/env python3
"""Drive the conformance pack against the Go and TypeScript starter skeletons.

WHY THIS SUITE EXISTS
---------------------
`conformance-skeletons/` is the answer to "how do I start?" for a stranger
implementing `warrant-conformance/1`. A starting point that has silently stopped
compiling is worse than none: it is the first thing an outsider runs, and it
would fail in their hands, not ours. So the skeletons are executed here, by the
same runner and against the same pack a stranger downloads.

WHAT IT ASSERTS, AND WHY NOT MERELY "EXIT 0"
--------------------------------------------
The skeletons are DELIBERATELY incomplete: they implement `canon` and decline the
other seven classes. Their correct result is therefore exit 2 with the grade
withheld — so "the runner exited 0" would be a broken skeleton, and "the runner
exited nonzero" is satisfied by one that does not run at all. Neither is an
assertion. What is asserted instead:

  * every `canon` vector in the pack PASSES — read from the pack's own index, so
    a skeleton that started answering `unsupported` for canon goes red rather
    than quietly reporting fewer passes;
  * nothing FAILS and nothing ERRORs — a skeleton that crashes, times out or
    prints unparseable output is a contract violation, not an incomplete answer;
  * the remaining base classes are UNRUN, the settlement classes are NOT-CLAIMED,
    the achieved grade is `none`, and the exit status is exactly 2;
  * and the whole thing is proved able to go RED: each skeleton is re-run through
    a proxy that corrupts one hex digit of its canonical output, and this suite
    fails unless the runner reports that as a FAIL. A check nobody has watched
    fail is not a check, and this repository has shipped that mistake before.

MISSING TOOLCHAIN IS NOT A PASS
-------------------------------
If `go` or `node` is absent this exits nonzero and says so. `tools/check.py`
gates it on both being present and reports UNRUN; what must never happen is a
green line whose meaning is "we did not look".
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "conformance" / "run.py"
SKELETONS = ROOT / "conformance-skeletons"

EXIT_FAIL, EXIT_GRADE_NOT_MET = 1, 2

# (label, the class this skeleton implements, the candidate command line)
CASES = [
    ("go", "canon", f"go run {SKELETONS / 'go' / 'main.go'}"),
    ("ts", "canon", f"node {SKELETONS / 'ts' / 'main.ts'}"),
]

# The corrupting proxy. It speaks the contract faithfully in both directions and
# changes exactly one thing: the leading hex digit of each hex field it sees.
# That is the smallest edit that makes a correct skeleton wrong, which is what a
# negative control has to be — if the runner cannot see this, it cannot see
# anything. Both fields are corrupted because the canon battery pins the
# canonical BYTES while the four SPEC §8 vectors pin only the WarrantID, and a
# control that touched one of them would leave the other class of vector passing.
PROXY = '''
import json, subprocess, sys
raw = sys.stdin.read()
proc = subprocess.run(sys.argv[1:], input=raw.encode(), stdout=subprocess.PIPE)
resp = json.loads(proc.stdout.decode())
out = resp.get("output") or {}
for field in ("canon_hex", "warrant_id"):
    h = out.get(field)
    if isinstance(h, str) and h:
        out[field] = ("f" if h[0] != "f" else "0") + h[1:]
print(json.dumps(resp))
'''


def pack_vector_counts():
    """How many vectors each class holds, per the pack's own index.

    Read rather than hard-coded: a number written into a test is a number that
    drifts silently when the pack grows, and this repository has watched exactly
    that happen to two different counts.
    """
    index = json.loads((ROOT / "conformance" / "vectors" / "index.json")
                       .read_text(encoding="utf-8"))
    by_class, by_grade = {}, {}
    for entry in index["files"]:
        by_class[entry["class"]] = by_class.get(entry["class"], 0) + entry["vectors"]
        by_grade[entry["grade"]] = by_grade.get(entry["grade"], 0) + entry["vectors"]
    return by_class, by_grade


def run_json(candidate, extra=()):
    argv = [sys.executable, str(RUN), "--candidate", candidate, "--json",
            "--claim", "base", *extra]
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                          env=dict(os.environ))
    if not proc.stdout.strip():
        raise SystemExit(f"runner produced no JSON for {candidate}:\n{proc.stderr}")
    return json.loads(proc.stdout), proc.returncode


def main():
    missing = [tool for tool in ("go", "node") if shutil.which(tool) is None]
    if missing:
        print(f"SKELETONS: cannot run — {', '.join(missing)} not on PATH.")
        print("  An unexercised skeleton is not a working one. This is a gap, "
              "not a pass.")
        return 1

    by_class, by_grade = pack_vector_counts()
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")

    for label, implements, candidate in CASES:
        report, code = run_json(candidate)
        c = report["counts"]
        passes_by_class = {}
        for row in report["results"]:
            if row["outcome"] == "PASS":
                passes_by_class[row["class"]] = passes_by_class.get(row["class"], 0) + 1

        check(f"{label}: declares base grade and only {implements}",
              report["declared"]["grade"] == "base"
              and report["declared"]["classes"] == [implements],
              json.dumps(report["declared"]))
        # The load-bearing one. Every vector of the implemented class must pass;
        # a skeleton that declined them would otherwise look like a skeleton that
        # is merely incomplete, which is the whole failure mode being guarded.
        check(f"{label}: all {by_class[implements]} {implements} vectors PASS",
              passes_by_class.get(implements) == by_class[implements],
              f"{passes_by_class.get(implements, 0)} passed")
        check(f"{label}: passes nothing else", set(passes_by_class) <= {implements},
              json.dumps(passes_by_class))
        check(f"{label}: no failures or contract errors",
              c["FAIL"] == 0 and c["ERROR"] == 0, json.dumps(c))
        check(f"{label}: the other base classes are UNRUN, by name",
              c["UNRUN"] == by_grade["base"] - by_class[implements],
              f"{c['UNRUN']} unrun of an expected "
              f"{by_grade['base'] - by_class[implements]}")
        check(f"{label}: settlement vectors reported NOT-CLAIMED",
              c["NOT-CLAIMED"] == by_grade["settlement"],
              f"{c['NOT-CLAIMED']} not-claimed of {by_grade['settlement']}")
        # An honest incomplete implementation reaches no grade and says exit 2.
        # Exit 0 here would mean the pack had stopped asking for the seven
        # classes the skeleton does not implement.
        check(f"{label}: grade withheld, exit {EXIT_GRADE_NOT_MET}",
              report["grade_achieved"] is None and code == EXIT_GRADE_NOT_MET,
              f"grade={report['grade_achieved']} exit={code}")
        check(f"{label}: MUST-REJECT vectors were still sent",
              report["negatives_run"] > 0, "zero negative vectors ran")

    # Negative control: prove these assertions can fail. Without this the suite
    # above is compatible with a runner that stopped comparing canon at all.
    with tempfile.TemporaryDirectory() as td:
        proxy = Path(td) / "corrupt_canon.py"
        proxy.write_text(PROXY, encoding="utf-8")
        for label, implements, candidate in CASES:
            broken = f"{sys.executable} {proxy} {candidate}"
            report, code = run_json(broken)
            c = report["counts"]
            check(f"{label}: a corrupted leading hex digit is caught as FAIL",
                  c["FAIL"] == by_class[implements] and code == EXIT_FAIL,
                  f"{c['FAIL']} failed, exit {code} "
                  f"(expected {by_class[implements]} and {EXIT_FAIL})")

    print(f"\nCONFORMANCE SKELETONS: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
