#!/usr/bin/env python3
"""Drive the conformance pack against all three implementations and the stub.

WHAT THIS ASSERTS, AND WHY EACH ASSERTION IS HERE
-------------------------------------------------
Running the runner and checking it exits 0 would be a rubber stamp: exit 0 is
also what a runner that asks nothing returns. So each implementation is checked
against the shape of result it should produce, not merely against success:

  * the grade ACHIEVED is the one that implementation actually implements —
    settlement for Python and Go, base for Rust. Rust reaching base is a pass
    here, not a failure to reach settlement, and the suite fails if the runner
    ever reports Rust as settlement-grade;
  * MUST-REJECT vectors actually RAN. A run whose negative half was skipped is
    passed by an implementation that accepts everything, so a zero here is a
    failure even when nothing failed;
  * nothing is UNRUN inside a claimed grade, and Rust's above-grade vectors are
    reported NOT-CLAIMED rather than silently omitted;
  * the negative control is detected. `--self-check` corrupts each
    implementation on purpose and the runner must go red for every mutation.

THE PERMISSIVE CONTROL IS THE POINT
-----------------------------------
`accept-all` wraps the real Python implementation and answers "yes" to every
validity question. It still passes every positive vector in the pack — 59 of
them — which is exactly why this suite asserts that the runner reports it as
PERMISSIVE and withholds every grade. A conformance pack whose positive half
cannot tell those two implementations apart is decoration.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "conformance" / "run.py"
GO = ROOT / "impl-go" / "warrant-go"
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"
PY = f"{sys.executable} {ROOT / 'impl' / 'warrant.py'} probe"

EXIT_OK, EXIT_FAIL, EXIT_GRADE_NOT_MET = 0, 1, 2


def env():
    e = dict(os.environ)
    e.setdefault("SIGMA_GLYPH", str(ROOT / "impl"))
    return e


def run_json(candidate, extra=()):
    argv = [sys.executable, str(RUN), "--candidate", candidate, "--json", *extra]
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, env=env())
    if not proc.stdout.strip():
        raise SystemExit(f"runner produced no JSON for {candidate}:\n{proc.stderr}")
    return json.loads(proc.stdout), proc.returncode


def main():
    for name, path in (("warrant-go", GO), ("warrant-rs", RS)):
        if not path.is_file():
            print(f"SKIP  conformance runner: {name} not built ({path})")
            return 0

    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")

    cases = [
        ("python", PY, "settlement", EXIT_OK),
        ("go", f"{GO} probe", "settlement", EXIT_OK),
        # Rust implements SPEC §6 and not §7. Base IS its correct result.
        ("rust", f"{RS} probe", "base", EXIT_OK),
    ]
    for label, candidate, want_grade, want_exit in cases:
        report, code = run_json(candidate)
        c = report["counts"]
        check(f"{label}: reaches {want_grade} grade",
              report["grade_achieved"] == want_grade,
              f"achieved {report['grade_achieved']!r}")
        check(f"{label}: exit status {want_exit}", code == want_exit, f"got {code}")
        check(f"{label}: no failures or contract errors",
              c["FAIL"] == 0 and c["ERROR"] == 0, json.dumps(c))
        check(f"{label}: nothing UNRUN inside the claimed grade",
              c["UNRUN"] == 0, f"{c['UNRUN']} unrun")
        # A pack run whose MUST-REJECT half never executed proves nothing.
        check(f"{label}: MUST-REJECT vectors actually ran",
              report["negatives_run"] > 0, "zero negative vectors ran")
        check(f"{label}: accepted nothing it must reject",
              report["negatives_accepted"] == 0,
              f"{report['negatives_accepted']} accepted")

    # The asymmetry must be VISIBLE, not smoothed over: Rust's settlement-grade
    # vectors are reported as not claimed rather than quietly dropped.
    rs_report, _ = run_json(f"{RS} probe")
    check("rust: above-grade vectors reported NOT-CLAIMED",
          rs_report["counts"]["NOT-CLAIMED"] > 0,
          "settlement vectors vanished from the report")
    check("rust: declares base grade for itself",
          rs_report["declared"]["grade"] == "base",
          rs_report["declared"].get("grade"))

    # Forcing a base-only implementation to claim settlement must surface the
    # gap as UNRUN and withhold the grade -- never as a quiet pass.
    forced, code = run_json(f"{RS} probe", extra=("--claim", "settlement"))
    check("rust forced to claim settlement: gap reported as UNRUN",
          forced["counts"]["UNRUN"] > 0 and forced["counts"]["FAIL"] == 0,
          json.dumps(forced["counts"]))
    check("rust forced to claim settlement: grade withheld, exit 2",
          forced["grade_achieved"] == "base" and code == EXIT_GRADE_NOT_MET,
          f"grade={forced['grade_achieved']} exit={code}")

    # The permissive control: passes every positive vector, must still be red.
    stub = (f"{sys.executable} {ROOT / 'conformance' / 'stub' / 'mutate.py'} "
            f"--mutation accept-all -- {PY}")
    perm, code = run_json(stub)
    check("permissive stub: every MUST-REJECT vector accepted",
          perm["negatives_accepted"] == perm["negatives_run"] > 0,
          f"{perm['negatives_accepted']}/{perm['negatives_run']}")
    check("permissive stub: still passes the positive vectors",
          perm["counts"]["PASS"] > 0, "no positives passed -- control is too broken")
    check("permissive stub: achieves no grade, exit 1",
          perm["grade_achieved"] is None and code == EXIT_FAIL,
          f"grade={perm['grade_achieved']} exit={code}")

    # The runner's own negative control, over each real implementation.
    for label, candidate in (("python", PY), ("go", f"{GO} probe"), ("rust", f"{RS} probe")):
        proc = subprocess.run(
            [sys.executable, str(RUN), "--candidate", candidate, "--self-check"],
            cwd=ROOT, capture_output=True, text=True, env=env())
        missed = [l for l in proc.stdout.splitlines() if "MISSED" in l]
        check(f"{label}: runner detects every deliberate defect",
              proc.returncode == 0 and not missed,
              "; ".join(missed) or f"exit {proc.returncode}")

    print(f"\nCONFORMANCE RUNNER: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
