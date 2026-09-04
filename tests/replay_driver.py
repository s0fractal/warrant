#!/usr/bin/env python3
"""Replay-driver regressions: the air-canada replay must not go green for the
wrong reason.

Exact-head review of 29aecf8 (Codex) produced two executable false-green
paths in demos/air-canada/replay.py:

  P1-1  the driver compared per-record findings and discarded the verify
        report's own grade, ok, error count and exit status — an installed CLI
        that returned 1 with ok=false for the clean positive reports still
        yielded exit 0 with "2 record vectors reproduced";
  P1-2  the closing "N controls refused" counted manifest entries, not
        executions — a `never-executed` control added to the manifest was
        reported as refused without ever running.

This file holds both closed, three ways:

  1. in-process: `report_problems` on synthetic reports (no CLI);
  2. driver-only: mutated manifests are REFUSED (`manifest`, exit 3) before
     any CLI runs — an unknown control, and a missing one;
  3. the complete CLI path: a venv-style installation is assembled from THIS
     tree's modules (no network, no pip: the modules are copied into a fresh
     venv's site-packages beside a `warrant-verify` dist-info and a console
     script), the replay must pass through it, and then the installed
     `warrant.py` is patched exactly as the review did — clean positive
     reports rewritten to grade='wrong-grade', ok=false, errors=99, exit 1 —
     and the replay must FAIL (exit 1), naming the inconsistency.

What the installation here is NOT: the wheel. `replay-clean.sh` builds and
installs the wheel; this test establishes that the driver reads the CLI's
refusal, which needs a real `warrant` process and a real venv layout, not a
particular packaging path. The evaluator module is byte-identical to the
bundled one, so the driver's pin check is exercised for real.

Exit 3 (UNRUN) if a venv cannot be created or `cryptography` is not importable
by the venv interpreter: the CLI path could not be exercised, which is not a
pass.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demos" / "air-canada"
EXIT_UNRUN = 3

spec = importlib.util.spec_from_file_location("replay_driver", DEMO / "replay.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

results = []


def chk(cond, label, detail=""):
    results.append(bool(cond))
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")
    return cond


def rc(code):
    return SimpleNamespace(returncode=code, stdout="", stderr="")


# ------------------------------------------------- 1. in-process consistency --
def clean_report(grade="base", **over):
    rep = {"report": R.REPORT_TAG, "grade": grade, "ok": True, "records": 2, "errors": 0, "warnings": 1,
           "findings": [{"level": "WARN", "subject": "abc", "message": "binding unverified"}]}
    rep.update(over)
    return rep


def in_process():
    print("in-process: report_problems")
    chk(R.report_problems(rc(0), clean_report(), "base") == [], "a consistent clean base report has no problems")
    err = clean_report("settlement", ok=False, errors=1, warnings=1,
                       findings=[{"level": "ERR", "subject": "settlement", "message": "x"},
                                 {"level": "WARN", "subject": "abc", "message": "y"}])
    chk(R.report_problems(rc(1), err, "settlement") == [], "a consistent settlement ERR report (exit 1) has no problems")
    # the review's mutation: wrong grade, ok=false, errors=99, exit 1 on a clean report
    p = R.report_problems(rc(1), clean_report(grade="wrong-grade", ok=False, errors=99), "base")
    chk(len(p) == 4 and any("grade=" in x for x in p) and any("errors=99" in x for x in p)
        and any("ok=False" in x for x in p) and any("exit 1" in x for x in p),
        "review mutation (grade/ok/errors/exit) names all four inconsistencies", str(p))
    chk(R.report_problems(rc(0), clean_report(ok=False), "base") == ["ok=False with 0 ERR finding(s)"],
        "ok=false with no ERR finding is a problem", str(R.report_problems(rc(0), clean_report(ok=False), "base")))
    chk(R.report_problems(rc(1), clean_report(), "base") == ["exit 1 with 0 ERR finding(s)"],
        "exit 1 with no ERR finding is a problem")
    chk(R.report_problems(rc(0), err, "settlement") == ["exit 0 with 1 ERR finding(s)"],
        "exit 0 with an ERR finding is a problem")
    chk(R.report_problems(rc(0), clean_report(), "settlement") == ["grade='base', requested `settlement`"],
        "a base report consumed as settlement is a problem")
    chk(R.report_problems(rc(0), clean_report(errors=True), "base") != [],
        "a boolean error count is not a count")
    chk(R.report_problems(rc(0), clean_report(findings=[{"level": "INFO", "subject": "a", "message": "m"}]), "base")
        == ["findings is not a list of {level: ERR|WARN, subject, message}"],
        "an unknown finding level is a problem, not normalized")
    chk(R.report_problems(rc(0), None, "base") == [f"did not print exactly one {R.REPORT_TAG} object"],
        "no report is a problem, not a refusal")
    chk(R.report_problems(rc(0), clean_report(records=-1), "base") == ["records=-1"],
        "a negative record count is a problem")


# ---------------------------------------------- 2. driver-only manifest checks --
def run_driver(warrant, pack, manifest, cwd):
    env = dict(os.environ)
    for k in ("SIGMA_GLYPH", "WARRANT_SIGMA_DIFFERENTIAL", "PYTHONPATH"):
        env.pop(k, None)
    return subprocess.run([sys.executable, str(DEMO / "replay.py"), "--warrant", str(warrant),
                           "--pack", str(pack), "--manifest", str(manifest)],
                          capture_output=True, text=True, cwd=str(cwd), env=env, timeout=600)


def manifest_variants(scratch, warrant, pack):
    print("driver-only: the control set is closed")
    base = json.loads((DEMO / "replay.json").read_text(encoding="utf-8"))
    chk(list(base["controls"]) == list(R.CONTROLS), "replay.json names exactly the supported controls, in order",
        f"{list(base['controls'])} vs {list(R.CONTROLS)}")

    extra = json.loads(json.dumps(base))
    extra["controls"]["never-executed"] = {"why": "negative control"}
    m = scratch / "extra.json"
    m.write_text(json.dumps(extra), encoding="utf-8")
    r = run_driver(warrant, pack, m, scratch)
    chk(r.returncode == R.EXIT_REFUSED and "REPLAY: REFUSED manifest:" in r.stdout and "never-executed" in r.stdout
        and "controls refused" not in r.stdout,
        "an unknown control is REFUSED manifest (exit 3), never counted", f"rc={r.returncode} {r.stdout[-300:]}")

    fewer = json.loads(json.dumps(base))
    del fewer["controls"]["cas-nested"]
    m = scratch / "fewer.json"
    m.write_text(json.dumps(fewer), encoding="utf-8")
    r = run_driver(warrant, pack, m, scratch)
    chk(r.returncode == R.EXIT_REFUSED and "REPLAY: REFUSED manifest:" in r.stdout and "cas-nested" in r.stdout,
        "a missing control is REFUSED manifest (exit 3), coverage is not silently reduced",
        f"rc={r.returncode} {r.stdout[-300:]}")


# ------------------------------------------------------- 3. complete CLI path --
def assemble_install(scratch):
    """A venv whose site-packages holds this tree's `warrant` and evaluator
    modules, a `warrant-verify` dist-info, and a console script — the layout
    the driver's preflight interrogates. Returns the console script, or None
    with a reason when the host cannot provide it (UNRUN, not pass)."""
    venv = scratch / "venv"
    r = subprocess.run([sys.executable, "-m", "venv", "--without-pip", "--system-site-packages", str(venv)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, f"venv creation failed: {r.stderr.strip()[:200]}"
    python = venv / "bin" / "python"
    if not python.exists():
        return None, "venv has no bin/python (unsupported layout on this host)"
    r = subprocess.run([str(python), "-I", "-c",
                        "import sysconfig, cryptography; print(sysconfig.get_paths()['purelib'])"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, f"venv interpreter cannot import cryptography: {r.stderr.strip()[:200]}"
    site = Path(r.stdout.strip())
    site.mkdir(parents=True, exist_ok=True)
    for mod in ("warrant.py", "sigma_glyph_v05.py", "ski_policy.py", "policy_lang.py"):
        shutil.copy(ROOT / "impl" / mod, site / mod)
    dist = site / "warrant_verify-0.0.0+replay-driver-test.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: warrant-verify\n"
                                   "Version: 0.0.0+replay-driver-test\n", encoding="utf-8")
    script = venv / "bin" / "warrant"
    script.write_text(f"#!{python}\nimport sys\nfrom warrant import main\nsys.exit(main())\n", encoding="utf-8")
    os.chmod(script, 0o755)
    return script, site / "warrant.py"


MUTATION = '''

# --- replay_driver.py regression: the exact-head review's false-green mutation.
# Clean positive reports (no errors, no `ski@v1 unverified` finding) are
# rewritten to a wrong grade, ok=false and errors=99; `verify --json` then
# exits 1 for them. The driver must FAIL, not reproduce the vector.
_replay_driver_orig_verify_report = verify_report


def verify_report(store, settlement=None):
    rep = _replay_driver_orig_verify_report(store, settlement)
    if rep["errors"] == 0 and not any("ski@v1 unverified" in f["message"] for f in rep["findings"]):
        rep.update(grade="wrong-grade", ok=False, errors=99)
    return rep
'''


def cli_path(scratch, warrant, installed_warrant_py):
    print("complete CLI path: positive replay, then the review's mutation")
    pack = scratch / "pack"
    shutil.copytree(DEMO / "pack", pack)
    manifest = DEMO / "replay.json"
    cwd = scratch / "cwd"
    cwd.mkdir()

    r = run_driver(warrant, pack, manifest, cwd)
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    n_ctl = len(R.CONTROLS)
    chk(r.returncode == 0 and last.startswith(f"REPLAY: 2 record vectors reproduced; {n_ctl} controls refused as frozen")
        and "BAD " not in r.stdout,
        f"positive: the assembled installation reproduces the vector ({n_ctl} executed controls counted)",
        f"rc={r.returncode} last={last!r} stderr={r.stderr.strip()[-300:]!r}")
    chk(f"control {R.CONTROLS[-1]}: executed" in r.stdout and "agree with its findings" in r.stdout,
        "positive: execution lines and report-consistency lines are present", r.stdout[-400:])

    original = installed_warrant_py.read_bytes()
    installed_warrant_py.write_bytes(original + MUTATION.encode())
    try:
        r = run_driver(warrant, pack, manifest, cwd)
    finally:
        installed_warrant_py.write_bytes(original)
    chk(r.returncode == R.EXIT_FAIL and "REPLAY: FAIL" in r.stdout
        and "grade, ok, counts and exit agree with its findings" in r.stdout
        and "as the frozen vector implies" in r.stdout
        and "record vectors reproduced" not in r.stdout,
        "mutation (wrong grade/ok=false/errors=99/exit 1 on clean reports): REPLAY: FAIL, exit 1",
        f"rc={r.returncode} tail={r.stdout[-500:]!r}")
    chk("wrong-grade" in r.stdout and "errors=99" in r.stdout,
        "mutation: the BAD lines name the inconsistent fields", r.stdout[-500:])

    r = run_driver(warrant, pack, manifest, cwd)
    chk(r.returncode == 0, "restored installation reproduces the vector again", f"rc={r.returncode}")


def main():
    in_process()
    scratch = Path(tempfile.mkdtemp(prefix="replay-driver-"))
    try:
        warrant, note = assemble_install(scratch)
        if warrant is None:
            print(f"\nREPLAY-DRIVER: UNRUN (CLI path) — {note}")
            print("the in-process checks above ran; the complete CLI path did not")
            return EXIT_UNRUN if all(results) else 1
        manifest_variants(scratch, warrant, DEMO / "pack")
        cli_path(scratch, warrant, note)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    ok = all(results)
    print("\n" + ("REPLAY-DRIVER: ALL PASS" if ok else "REPLAY-DRIVER: FAILURES PRESENT"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
