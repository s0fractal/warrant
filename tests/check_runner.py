#!/usr/bin/env python3
"""The aggregate's scheduler, checked with instrumented children.

tools/check.py became a pool (PR #61). A pool can drop a check, run a
serial-only check beside another, or launch a different order than the one it
advertises as the baseline -- none of which the checks themselves can notice.
So this runs `check.main()` in-process with `subprocess.run` replaced by a
recorder that never does real work, and asserts:

  1. --jobs 1 launches every runnable check exactly once, in CHECKS order;
  2. --jobs 4 launches every runnable check exactly once, SERIAL ones never
     overlap any other launch, and the pool really runs more than one at once;
  3. a child exit 1 is FAIL under both modes (exit 1); a child exit 3 is UNRUN
     (exit 2, or 0 under --allow-unrun);
  4. the X1 entry is launched unless X1_COVERED_BY_WORKFLOW=true, GITHUB_ACTIONS
     alone does not skip it, and the expression ci.yml sets the flag from names
     exactly the events x1-cross-repo.yml triggers on (push/PR to master).
Every relation is asserted; any deviation exits 1.
"""
import contextlib
import io
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check  # noqa: E402

ok = []
ORDER = [n for n, _, _ in check.CHECKS]
BY_ARGV = {tuple(a): n for n, a, _ in check.CHECKS}
X1 = "x1: cross-repo HEAD-vs-HEAD (regression canary, not a gate)"


def chk(cond, what, detail=""):
    ok.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + what + (f"  [{detail}]" if detail and not cond else ""))


def instrumented(argv, exit_for=None, env=None):
    """Run check.main(argv) with fake children; return (exit, launches, peak, overlaps, stdout)."""
    launches, active, peak, overlaps = [], set(), [0], []
    lock = threading.Lock()

    def fake_run(argv_, **kw):
        name = BY_ARGV.get(tuple(argv_), " ".join(argv_))
        with lock:
            for other in active:
                if name in check.SERIAL or other in check.SERIAL:
                    overlaps.append((name, other))
            active.add(name); launches.append(name); peak[0] = max(peak[0], len(active))
        time.sleep(0.01)
        with lock:
            active.discard(name)
        return subprocess.CompletedProcess(argv_, (exit_for or {}).get(name, 0), stdout=f"{name}\n", stderr="")

    saved_run, saved_needs, saved_env, saved_argv = check.subprocess.run, dict(check.NEEDS), dict(os.environ), sys.argv
    try:
        check.subprocess.run = fake_run
        for k in check.NEEDS:                      # every prerequisite "present" except the X1 gate under test
            if k != "x1-not-covered-elsewhere":
                check.NEEDS[k] = (lambda: True, saved_needs[k][1])
        os.environ.pop("X1_COVERED_BY_WORKFLOW", None)
        os.environ.update(env or {})
        sys.argv = ["check.py", *argv]
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            code = check.main()
        return code, launches, peak[0], overlaps, out.getvalue()
    finally:
        check.subprocess.run = saved_run
        check.NEEDS.clear(); check.NEEDS.update(saved_needs)
        os.environ.clear(); os.environ.update(saved_env)
        sys.argv = saved_argv


def main():
    code, launches, peak, overlaps, out = instrumented(["--jobs", "1"])
    chk(code == 0 and launches == ORDER, "1. --jobs 1 launches every check once, in CHECKS order",
        f"code={code} first={launches[:2]} n={len(launches)}/{len(ORDER)}")
    chk("sequential, original order" in out, "1. --jobs 1 says so in its summary")

    code, launches, peak, overlaps, out = instrumented(["--jobs", "4"])
    chk(code == 0 and sorted(launches) == sorted(ORDER), "2. --jobs 4 launches every check exactly once",
        f"code={code} n={len(launches)} missing={sorted(set(ORDER) - set(launches))[:3]}")
    chk(not overlaps, "2. SERIAL checks never overlap any other launch", str(overlaps[:2]))
    chk(1 < peak <= 4, "2. the pool actually ran concurrently, at most 4 wide", f"peak={peak}")

    for jobs in ("1", "4"):
        code, *_ = instrumented(["--jobs", jobs], exit_for={ORDER[5]: 1})
        chk(code == 1, f"3. a child exit 1 is FAIL under --jobs {jobs} (exit 1)", f"code={code}")
        code, *_ = instrumented(["--jobs", jobs], exit_for={ORDER[5]: check.EXIT_UNRUN})
        chk(code == 2, f"3. a child exit 3 is UNRUN under --jobs {jobs} (exit 2)", f"code={code}")
        code, *_ = instrumented(["--jobs", jobs, "--allow-unrun"], exit_for={ORDER[5]: check.EXIT_UNRUN})
        chk(code == 0, f"3. ...and exit 0 only with --allow-unrun (--jobs {jobs})", f"code={code}")

    code, launches, *_ = instrumented(["--jobs", "4"])
    chk(X1 in launches, "4. without the flag the aggregate launches X1 (feature push, PR to another base)")
    code, launches, *_ = instrumented(["--jobs", "4"], env={"GITHUB_ACTIONS": "true"})
    chk(X1 in launches, "4. GITHUB_ACTIONS alone does not skip X1")
    code, launches, _, _, out = instrumented(["--jobs", "4"], env={"X1_COVERED_BY_WORKFLOW": "true"})
    chk(X1 not in launches and "UNRUN  x1" in out and "x1-cross-repo.yml runs for this event" in out,
        "4. with X1_COVERED_BY_WORKFLOW=true X1 is UNRUN with the reason, not launched")
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    expr = re.search(r"^  X1_COVERED_BY_WORKFLOW: \$\{\{ (.*) \}\}$", ci, re.M)
    x1wf = (ROOT / ".github/workflows/x1-cross-repo.yml").read_text()
    trig = re.search(r"^on:\n  push:\n    branches: \[(\w+)\]\n  pull_request:\n    branches: \[(\w+)\]", x1wf, re.M)
    want = ("(github.event_name == 'push' && github.ref == 'refs/heads/master') || "
            "(github.event_name == 'pull_request' && github.base_ref == 'master')")
    chk(expr is not None and trig is not None and trig.group(1) == trig.group(2) == "master" and expr.group(1) == want,
        "4. ci.yml's flag names exactly x1-cross-repo.yml's push/pull_request triggers (master)",
        f"expr={expr.group(1) if expr else None} trig={trig.groups() if trig else None}")
    chk(ci.count("\nenv:\n") == 1, "4. ci.yml has one top-level env block (a duplicate key would silently drop one)")

    print(f"\n{sum(ok)}/{len(ok)} checks")
    print("CHECK-RUNNER: ALL PASS" if all(ok) else "CHECK-RUNNER: FAILURES PRESENT")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
