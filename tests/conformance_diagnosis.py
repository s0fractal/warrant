#!/usr/bin/env python3
"""What the conformance runner TELLS a partial implementation, and whether
`--self-check` can still go red while saying it.

WHY THIS SUITE EXISTS
---------------------
`tests/conformance_skeletons.py` asserts the runner produces the right OUTCOMES
for an honestly incomplete candidate — canon green, the rest UNRUN, grade
withheld, exit 2. All of that was already true when the report ended:

    GRADE ACHIEVED: none
      Not even base grade. See the failures above.

with zero failures anywhere above it, and when `--self-check` — the command the
pack's README tells every newcomer to run first — printed `MISSED` twice and
`SELF-CHECK: FAILED — the runner missed a defect`. Both statements were false,
both were produced by a runner behaving correctly, and both told a first-time
implementer that the tooling was broken at the exact moment they were deciding
whether to continue.

Outcomes are therefore not enough: the DIAGNOSIS is a product surface, and it is
asserted here.

  * a candidate with no FAIL and no ERROR is told it is incomplete, is told
    nothing failed, and is pointed at named classes it can actually write next —
    and the report never refers to failures that are not in it;
  * a candidate that IS wrong is still told so, in those words, pointing at the
    failures that are genuinely listed. Softening the runner into always saying
    "keep going" would be the worse defect;
  * `--self-check` distinguishes a mutation that could not apply from one that
    applied and was missed, and STILL FAILS, loudly and nonzero, when a mutation
    applies and the runner does not react, when the proxy corrupts nothing it
    ought to have corrupted, and when nothing could be applied at all.

The three red directions are driven in-process against a doctored case list,
because there is no way to make the shipped mutations slip past a correct runner
— which is the point of them. Everything else is driven exactly as a stranger
would drive it: the shipped runner, over the shipped pack, against the shipped
skeletons.

MISSING TOOLCHAIN IS NOT A PASS
-------------------------------
Needs `go` and `node`, for the same reason `tests/conformance_skeletons.py` does:
the real partial candidates in this repository are those two skeletons, and a
contrived stand-in would prove the runner is kind to a fixture written to be
treated kindly.
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "conformance" / "run.py"
PACK = ROOT / "conformance"
MUTATE = PACK / "stub" / "mutate.py"
SKELETONS = ROOT / "conformance-skeletons"

EXIT_OK, EXIT_FAIL, EXIT_GRADE_NOT_MET, EXIT_PROTOCOL = 0, 1, 2, 3

# The real day-one implementations: one file each, `canon` and nothing else.
# Filled in by main(), which compiles the Go one first -- this suite drives a
# candidate up to nine times over 138 vectors, and `go run` recompiles on every
# one of the ~1200 invocations. It is the same program either way;
# `tests/conformance_skeletons.py` is where `go run` itself is exercised.
PARTIAL = []

# A proxy that corrupts the one class the skeletons DO implement, so the same
# skeleton can be driven down the "you are wrong" branch of the diagnosis. This
# is how the incomplete branch is proved to be a branch and not a blanket.
CORRUPT = '''
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

ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")


def run_text(candidate, extra=()):
    """The runner as a stranger runs it: human report on stdout."""
    argv = [sys.executable, str(RUN), "--candidate", candidate, "--claim", "base",
            *extra]
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                          env=dict(os.environ))
    return proc.stdout, proc.returncode


def run_json(candidate):
    argv = [sys.executable, str(RUN), "--candidate", candidate, "--json",
            "--claim", "base"]
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                          env=dict(os.environ))
    if not proc.stdout.strip():
        raise SystemExit(f"runner produced no JSON for {candidate}:\n{proc.stderr}")
    return json.loads(proc.stdout), proc.returncode


def load_runner():
    spec = importlib.util.spec_from_file_location("_conformance_run", RUN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------- defect 1: the diagnosis
def check_incomplete_diagnosis():
    for label, candidate in PARTIAL:
        report, code = run_text(candidate)
        data, _ = run_json(candidate)
        counts = data["counts"]

        # Precondition: this really is the honest-partial case, or the rest of
        # these assertions are about something else.
        check(f"{label}: is the partial case (0 FAIL, 0 ERROR, UNRUN present)",
              counts["FAIL"] == 0 and counts["ERROR"] == 0 and counts["UNRUN"] > 0,
              json.dumps(counts))
        check(f"{label}: grade withheld and exit {EXIT_GRADE_NOT_MET}",
              data["grade_achieved"] is None and code == EXIT_GRADE_NOT_MET,
              f"grade={data['grade_achieved']} exit={code}")

        # THE REGRESSION. Before the fix this report ended "Not even base grade.
        # See the failures above." with no failures above it.
        check(f"{label}: never sends the reader to failures that are not there",
              "See the failures above" not in report
              and "Not even base grade" not in report,
              "the report still points at absent output")
        check(f"{label}: names the cause as incomplete, not wrong",
              "WITHHELD BECAUSE INCOMPLETE" in report
              and "nothing failed" in report,
              "no incompleteness diagnosis in the report")
        check(f"{label}: says outright that what was answered was correct",
              f"{counts['PASS']} of {counts['PASS']}" in report,
              f"expected 'N of N' for {counts['PASS']} passes")
        check(f"{label}: counts the UNRUN vectors in the diagnosis",
              f"{counts['UNRUN']} vectors are UNRUN" in report,
              f"expected the figure {counts['UNRUN']}")

        # Advice that names a class the candidate already implements, or one the
        # pack does not have, is worse than no advice.
        unrun_classes = {r["class"] for r in data["results"]
                         if r["outcome"] == "UNRUN"}
        after = report.split("cheapest first", 1)
        check(f"{label}: offers a cheapest-first next step", len(after) == 2,
              "no next-step section")
        if len(after) == 2:
            named = [c for c in unrun_classes if f"    {c:<14}" in after[1]]
            check(f"{label}: names 3 classes to write next, all really UNRUN",
                  len(named) == 3, f"named {sorted(named)}")
            check(f"{label}: accounts for the rest rather than dropping them",
                  "… then " in after[1], "no tail of remaining classes")
        check(f"{label}: explains exit 2 rather than leaving it to be guessed",
              "Exit status 2 means" in report, "exit status unexplained")


def check_wrong_diagnosis():
    """The other branch must still exist and still accuse. A runner that always
    says "you are doing fine" is the failure this repository ships most often."""
    with tempfile.TemporaryDirectory() as td:
        proxy = Path(td) / "corrupt.py"
        proxy.write_text(CORRUPT, encoding="utf-8")
        for label, candidate in PARTIAL:
            broken = f"{sys.executable} {proxy} {candidate}"
            report, code = run_text(broken)
            data, _ = run_json(broken)
            check(f"{label} (corrupted): the FAILs are real",
                  data["counts"]["FAIL"] > 0, json.dumps(data["counts"]))
            check(f"{label} (corrupted): diagnosed as WRONG, not as incomplete",
                  "WITHHELD BECAUSE WRONG" in report
                  and "WITHHELD BECAUSE INCOMPLETE" not in report,
                  "wrong answers were not diagnosed as wrong")
            check(f"{label} (corrupted): sends the reader to the listed failures",
                  "listed above" in report, "no pointer to the failure list")
            check(f"{label} (corrupted): exit {EXIT_FAIL}", code == EXIT_FAIL,
                  f"got {code}")


# ------------------------------------------------------- defect 2: --self-check
def check_self_check_on_partial():
    for label, candidate in PARTIAL:
        report, code = run_text(candidate, extra=("--self-check",))
        check(f"{label}: --self-check does not accuse itself of being broken",
              "MISSED" not in report and "SELF-CHECK: FAILED" not in report
              and "THIS RUNNER DID NOT NOTICE" not in report,
              "self-check still reports itself broken")
        check(f"{label}: mutations with nothing to corrupt are INAPPLICABLE",
              report.count("INAPPLICABLE") == 3,
              f"{report.count('INAPPLICABLE')} inapplicable, expected 3")
        check(f"{label}: says WHY each was inapplicable, naming the classes",
              "nothing to corrupt" in report
              and "which this candidate declines" in report,
              "no reason given for inapplicability")
        check(f"{label}: the mutation that DOES apply is still detected",
              "DETECTED      mutation=crash" in report,
              "crash was not detected")
        check(f"{label}: the summary states how much was actually proved",
              "1 of 4" in report, "no count of applied mutations")
        check(f"{label}: --self-check exits 0", code == EXIT_OK, f"got {code}")


def check_self_check_still_fails():
    """Three red directions, driven in-process over the real pack.

    A shipped mutation cannot be made to slip past a correct runner, so the case
    list is doctored instead: what is under test is the VERDICT logic, which is
    what changed. The pack, the proxy and the candidate are the real ones.
    """
    run = load_runner()
    _, docs = run.load_vectors(PACK)
    # One small class the skeletons decline plus the one they answer: enough for
    # a baseline with both shapes in it, small enough to run in seconds.
    docs = [d for d in docs if d["class"] in ("canon", "blob-hash")]
    candidate = ["node", str(SKELETONS / "ts" / "main.ts")]
    real_cases = run.SELF_CHECK_CASES
    real_targets = run.mutation_targets

    def drive(cases, targets=None):
        out = io.StringIO()
        run.SELF_CHECK_CASES = cases
        if targets is not None:
            run.mutation_targets = lambda *a, **k: targets
        try:
            code = run.self_check(candidate, docs, "base", 30.0, PACK, out=out)
        finally:
            run.SELF_CHECK_CASES = real_cases
            run.mutation_targets = real_targets
        return out.getvalue(), code

    # 1. A mutation that APPLIES and is not reacted to. `crash` corrupts every
    #    answer; the detector here refuses to see it, standing in for a runner
    #    that has gone blind.
    blind = [("crash", "exits nonzero instead of answering", lambda res: [])]
    report, code = drive(blind)
    check("still red: an applied mutation that is not caught is MISSED",
          "MISSED" in report and "THIS RUNNER DID NOT NOTICE" in report,
          report.strip().splitlines()[-1] if report.strip() else "(no output)")
    check("still red: a missed mutation fails the verdict line",
          "SELF-CHECK: FAILED" in report, "verdict was not FAILED")
    check(f"still red: a missed mutation exits {EXIT_FAIL}", code == EXIT_FAIL,
          f"got {code}")

    # 2. A mutation that corrupts NOTHING while targeting a class the candidate
    #    does answer. That is a broken negative control, and it must never be
    #    filed under the same calm heading as "you have not written this yet".
    inert = [("legacy-sig", "builds the signed message the pre-0.6.0 way",
              lambda res: [r for r in res if r["outcome"] == run.FAIL])]
    report, code = drive(inert, targets={"legacy-sig": ["canon"]})
    check("still red: a control that fires at nothing it targets is INERT",
          "INERT" in report and "THE NEGATIVE CONTROL IS BROKEN" in report,
          "an inert control was not reported")
    check(f"still red: an inert control exits {EXIT_FAIL}",
          code == EXIT_FAIL and "SELF-CHECK: FAILED" in report, f"got {code}")

    # 3. Nothing applied at all. Zero mutations landed means zero was proved,
    #    and a green line there would be the decoration this command exists to
    #    rule out -- UNRUN is not a pass, including for the self-check itself.
    none_apply = [c for c in real_cases if c[0] in ("legacy-sig", "accept-all")]
    report, code = drive(none_apply)
    check("still red: nothing applicable is INCONCLUSIVE, not green",
          "SELF-CHECK: INCONCLUSIVE" in report
          and "establishes nothing" in report,
          "an empty self-check reported as a success")
    check(f"still red: an inconclusive self-check exits {EXIT_FAIL}",
          code == EXIT_FAIL, f"got {code}")


def check_worked_minimum():
    """The program CONTRACT.md §8 tells a newcomer to start from.

    It implements nothing: every vector UNRUN, no grade, exit 2, and the document
    says so in as many words. It is therefore the most literal first contact this
    project has, and it was the harshest case of both defects — told to read
    failures that did not exist, and then told by `--self-check` that the runner
    was broken, because a candidate whose vectors are ALL already declined has no
    answer left for `crash` to take away.

    The source is lifted out of CONTRACT.md rather than copied here, so a change
    to the document that breaks the example turns this suite red instead of
    leaving a worked minimum that does not work.
    """
    doc = (PACK / "CONTRACT.md").read_text(encoding="utf-8")
    body = doc.split("## 8. A worked minimum", 1)
    check("contract: §8 still publishes a worked minimum", len(body) == 2,
          "no worked-minimum section in CONTRACT.md")
    if len(body) != 2:
        return
    source = body[1].split("```python", 1)[1].split("```", 1)[0]
    with tempfile.TemporaryDirectory() as td:
        prog = Path(td) / "minimum.py"
        prog.write_text(source, encoding="utf-8")
        candidate = f"{sys.executable} {prog}"

        data, code = run_json(candidate)
        check("minimum: implements nothing, exits 2, no grade",
              data["counts"]["PASS"] == 0 and data["counts"]["FAIL"] == 0
              and data["grade_achieved"] is None and code == EXIT_GRADE_NOT_MET,
              json.dumps(data["counts"]) + f" exit={code}")

        report, _ = run_text(candidate)
        check("minimum: told it is incomplete, not told to read failures",
              "WITHHELD BECAUSE INCOMPLETE" in report
              and "See the failures above" not in report,
              "the emptiest candidate is still mis-diagnosed")
        check("minimum: pointed at the first class to write",
              "cheapest first" in report and "    canon" in report,
              "no starting point offered to a candidate with nothing")

        report, code = run_text(candidate, extra=("--self-check",))
        # UNRUN -> ERROR is a change for the worse. Scoring it as "no change"
        # made the self-check accuse itself against exactly this candidate.
        check("minimum: --self-check still detects the one applicable mutation",
              "DETECTED      mutation=crash" in report, "crash not detected")
        check("minimum: --self-check does not call itself broken",
              "MISSED" not in report and "SELF-CHECK: FAILED" not in report
              and code == EXIT_OK,
              f"exit {code}: " + "; ".join(l for l in report.splitlines()
                                           if "MISSED" in l or "FAILED" in l))


def check_applied_log():
    """`applied` must mean the answer CHANGED, not that a branch was taken.

    This is the fact the whole three-way distinction rests on: if the proxy
    logged an application for a class the candidate already declines, an
    inapplicable mutation would be scored MISSED again, exactly as before.
    """
    request = {"warrant_conformance": "1", "id": "verify-sig/x",
               "class": "verify-sig",
               "input": {"warrant_id": "00" * 32, "key": "11" * 32, "sig": "22" * 64}}
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "applied.log"
        argv = [sys.executable, str(MUTATE), "--mutation", "false-unsupported",
                "--applied-log", str(log), "--",
                "node", str(SKELETONS / "ts" / "main.ts")]
        proc = subprocess.run(argv, input=json.dumps(request).encode(),
                              capture_output=True)
        resp = json.loads(proc.stdout.decode())
        check("mutate: withholding a class the candidate already declines "
              "logs nothing",
              not log.exists() or not log.read_text().strip(),
              log.read_text() if log.exists() else "")
        check("mutate: and forwards the candidate's own answer unchanged",
              "unsupported" in resp
              and "mutation=false-unsupported" not in str(resp["unsupported"]),
              json.dumps(resp))

    # The mirror: a class the candidate DOES answer is withheld, and logged.
    canon = {"warrant_conformance": "1", "id": "canon/x", "class": "canon",
             "input": {"body": {}}}
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "applied.log"
        argv = [sys.executable, str(MUTATE), "--mutation", "accept-all",
                "--applied-log", str(log), "--",
                "node", str(SKELETONS / "ts" / "main.ts")]
        subprocess.run(argv, input=json.dumps(canon).encode(), capture_output=True)
        check("mutate: a canon answer has no validity verdict to flip, "
              "so nothing is logged",
              not log.exists() or not log.read_text().strip(),
              log.read_text() if log.exists() else "")

    # And `--describe` is the single published copy of what each mutation reaches.
    proc = subprocess.run([sys.executable, str(MUTATE), "--describe"],
                          capture_output=True, text=True)
    described = json.loads(proc.stdout)["targets"]
    check("mutate: --describe publishes the classes each mutation reaches",
          described.get("legacy-sig") == ["sig-message"]
          and set(described.get("false-unsupported", [])) == {"verify-sig", "parse"},
          json.dumps(described))
    index = json.loads((PACK / "vectors" / "index.json").read_text(encoding="utf-8"))
    known = set(index["grades"]["settlement"])
    stray = sorted({c for cs in described.values() for c in cs} - known)
    check("mutate: every targeted class exists in the pack", not stray, str(stray))


def main():
    missing = [t for t in ("go", "node") if shutil.which(t) is None]
    if missing:
        print(f"DIAGNOSIS: cannot run — {', '.join(missing)} not on PATH.")
        print("  The partial candidates are the real skeletons. This is a gap, "
              "not a pass.")
        return 1
    with tempfile.TemporaryDirectory() as td:
        binary = Path(td) / "skeleton-go"
        built = subprocess.run(["go", "build", "-o", str(binary),
                                str(SKELETONS / "go" / "main.go")],
                               capture_output=True, text=True)
        if built.returncode != 0:
            print("DIAGNOSIS: the Go skeleton does not compile — "
                  "that is its own defect.")
            print(built.stderr.strip()[:400])
            return 1
        PARTIAL.extend([("go", str(binary)),
                        ("ts", f"node {SKELETONS / 'ts' / 'main.ts'}")])
        check_incomplete_diagnosis()
        check_wrong_diagnosis()
        check_self_check_on_partial()
        check_self_check_still_fails()
        check_worked_minimum()
        check_applied_log()
    print(f"\nCONFORMANCE DIAGNOSIS: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
