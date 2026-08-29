#!/usr/bin/env python3
"""Countervectors for the autonomy advisory trust-binding (P1a/P1b/P1c).

Framework-free.  Each dangerous payload below must refuse before any base/head
byte is trusted, or withhold the check evidence.  A surviving case is an
executable trust-binding finding, not a prose disagreement.  The reproductions
of the *old* name-only / same-repo / live-read behaviour are kept as explicit
contrasts so the closed holes stay visible.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = "s0fractal/warrant"
DEFAULT = "master"
BASE = "a" * 40           # snapshot base = master tip the checks ran against
HEAD = "b" * 40           # workflow_run.head_sha = the commit the checks ran on
OTHER = "c" * 40          # a drifted / force-pushed commit
CI = ".github/workflows/ci.yml"
X1 = ".github/workflows/x1-cross-repo.yml"

SPEC = importlib.util.spec_from_file_location(
    "autonomy_advisory", Path(__file__).resolve().parents[1] /
    "tools" / "autonomy_advisory.py")
adv = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adv
SPEC.loader.exec_module(adv)

passed = 0


def check(name, condition):
    global passed
    if not condition:
        raise AssertionError(name)
    passed += 1
    print(f"ok  {name}")


def workflow_run(head=HEAD, base_sha=BASE, base_ref=DEFAULT, event="pull_request",
                 number=38, prs=None):
    if prs is None:
        prs = [{"number": number,
                "base": {"ref": base_ref, "sha": base_sha},
                "head": {"ref": "feat", "sha": head}}]
    return {"event": event, "head_sha": head, "pull_requests": prs}


def live_pr(number=38, base_ref=DEFAULT, base_sha=BASE, head_sha=HEAD,
            base_repo=REPO, head_repo=REPO):
    return {
        "number": number,
        "base": {"ref": base_ref, "sha": base_sha,
                 "repo": {"full_name": base_repo}},
        "head": {"ref": "feat", "sha": head_sha,
                 "repo": {"full_name": head_repo}},
    }


def run_for(path, suite, base=BASE, head=HEAD, number=38, base_ref=DEFAULT):
    return {"path": path, "head_sha": head, "event": "pull_request",
            "check_suite_id": suite,
            "pull_requests": [{"number": number,
                               "base": {"ref": base_ref, "sha": base},
                               "head": {"sha": head}}]}


def trusted_runs(head=HEAD, number=38, base=BASE, base_ref=DEFAULT):
    return [run_for(CI, 111, base=base, head=head, number=number,
                    base_ref=base_ref),
            run_for(X1, 222, base=base, head=head, number=number,
                    base_ref=base_ref)]


def check_run(name, suite, app="github-actions", status="completed",
              conclusion="success"):
    return {"name": name, "app": {"slug": app},
            "check_suite": {"id": suite}, "status": status,
            "conclusion": conclusion}


def trusted_check_runs():
    return [check_run("test", 111), check_run("cross-repo", 222)]


def refuses(wr, pr, msg_part=""):
    try:
        adv.resolve_refs(wr, pr, REPO, DEFAULT)
        return False
    except adv.AdvisoryRefusal as exc:
        return msg_part in str(exc)


def main():
    # -- positive control ---------------------------------------------------
    base, head, drift = adv.resolve_refs(workflow_run(), live_pr(), REPO, DEFAULT)
    check("consistent same-default-branch PR resolves to the run's pair",
          base == BASE and head == HEAD and drift == [])
    checks = adv.select_checks(trusted_runs(), trusted_check_runs(),
                               BASE, HEAD, 38, DEFAULT)
    check("trusted evidence yields both required checks green",
          checks == {"test": "success", "cross-repo": "success"})

    # -- P1a: same-repo is not the default branch ---------------------------
    check("P1a: a same-repo non-default base ref is refused before any checkout",
          refuses(workflow_run(base_ref="evil-evaluator"),
                  live_pr(base_ref="evil-evaluator"), "base ref"))
    check("P1a: a live base repository mismatch is refused",
          refuses(workflow_run(), live_pr(base_repo="attacker/warrant"),
                  "base repository"))
    # contrast: the old logic (same-repo only) would have accepted the attack.
    old_ok = (live_pr(base_ref="evil-evaluator")["base"]["repo"]["full_name"]
              == REPO)
    check("P1a contrast: the retired same-repo-only test would have accepted it",
          old_ok is True)

    # -- P1b: the evaluated pair is the immutable run snapshot ---------------
    _, _, drift_head = adv.resolve_refs(
        workflow_run(), live_pr(head_sha=OTHER), REPO, DEFAULT)
    check("P1b: a force-pushed live head is reported as drift", drift_head)
    _, _, drift_base = adv.resolve_refs(
        workflow_run(), live_pr(base_sha=OTHER), REPO, DEFAULT)
    check("P1b: an advanced base is reported as drift", drift_base)
    check("P1b: a snapshot whose head disagrees with head_sha is refused",
          refuses(workflow_run(prs=[{"number": 38,
                                     "base": {"ref": DEFAULT, "sha": BASE},
                                     "head": {"ref": "feat", "sha": OTHER}}]),
                  live_pr(), "snapshot head"))
    check("P1b: a non-pull_request workflow_run is refused",
          refuses(workflow_run(event="push"), live_pr(), "event"))
    check("P1b: a workflow_run with no PR snapshot is refused",
          refuses(workflow_run(prs=[]), live_pr(), "no pull request"))

    # -- P1c: check evidence is bound to trusted workflow identity ----------
    foreign_app = [check_run("test", 111, app="attacker-app"),
                   check_run("cross-repo", 222, app="attacker-app")]
    check("P1c: same-named checks from a foreign app do not count",
          adv.select_checks(trusted_runs(), foreign_app,
                            BASE, HEAD, 38, DEFAULT) == {})
    # A github-actions check whose suite is NOT one of the required workflows.
    untrusted_suite = [check_run("test", 999), check_run("cross-repo", 999)]
    check("P1c: a github-actions check from an untrusted suite does not count",
          adv.select_checks(trusted_runs(), untrusted_suite,
                            BASE, HEAD, 38, DEFAULT) == {})
    # A run of an untrusted workflow file, even if it mints suite 111.
    untrusted_workflow = [run_for(".github/workflows/attacker.yml", 111)]
    check("P1c: a suite owned by an untrusted workflow file does not count",
          adv.select_checks(untrusted_workflow, [check_run("test", 111)],
                            BASE, HEAD, 38, DEFAULT) == {})
    # A trusted suite but for a DIFFERENT head is not credited to this head.
    check("P1c: trusted evidence bound to another head does not count",
          adv.select_checks(trusted_runs(head=OTHER), trusted_check_runs(),
                            BASE, HEAD, 38, DEFAULT) == {})
    # A trusted suite but for a DIFFERENT pull request number.
    check("P1c: trusted evidence bound to another PR does not count",
          adv.select_checks(trusted_runs(number=999), trusted_check_runs(),
                            BASE, HEAD, 38, DEFAULT) == {})

    # -- P1b': check evidence is bound to the EXACT base, not just head ------
    # The mixed-base attack: test passed against base B0, cross-repo against B1
    # (master advanced in between), both on head H, PR 38. A packet for either
    # base must never carry both.
    B0, B1 = BASE, OTHER
    mixed_runs = [run_for(CI, 111, base=B0), run_for(X1, 222, base=B1)]
    mixed_checks = [check_run("test", 111), check_run("cross-repo", 222)]
    at_b1 = adv.select_checks(mixed_runs, mixed_checks, B1, HEAD, 38, DEFAULT)
    at_b0 = adv.select_checks(mixed_runs, mixed_checks, B0, HEAD, 38, DEFAULT)
    check("P1b': test@B0 + cross-repo@B1 evaluated at B1 yields only cross-repo",
          at_b1 == {"cross-repo": "success"})
    check("P1b': test@B0 + cross-repo@B1 evaluated at B0 yields only test",
          at_b0 == {"test": "success"})
    check("P1b': the mixed-base pair is never both-green for either base",
          not ({"test", "cross-repo"} <= set(at_b1))
          and not ({"test", "cross-repo"} <= set(at_b0)))
    check("P1b': a run whose snapshot base sha differs does not count",
          adv.select_checks(trusted_runs(base=OTHER), trusted_check_runs(),
                            BASE, HEAD, 38, DEFAULT) == {})
    check("P1b': a run whose snapshot base ref differs does not count",
          adv.select_checks(trusted_runs(base_ref="release-x"),
                            trusted_check_runs(), BASE, HEAD, 38, DEFAULT) == {})
    check("P1b': the correct exact base/head for both checks is green",
          adv.select_checks(trusted_runs(base=BASE, head=HEAD),
                            trusted_check_runs(), BASE, HEAD, 38, DEFAULT)
          == {"test": "success", "cross-repo": "success"})
    # contrast: name-only matching (the retired logic) would have accepted the
    # foreign-app forgery.
    name_only = {c["name"] for c in foreign_app} >= {"test", "cross-repo"}
    check("P1c contrast: retired name-only matching would have accepted it",
          name_only is True)

    # -- end to end: build() writes files on success, blanks on drift -------
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _dump(tmp, workflow_run(), live_pr(), trusted_runs(),
                      trusted_check_runs())
        rc = _run_build(tmp, files)
        packet = json.loads((tmp / "checks.json").read_text())
        refs = (tmp / "refs.env").read_text()
        check("build: clean payloads exit 0 with the bound pair and checks",
              rc == 0 and f"base={BASE}" in refs and f"head={HEAD}" in refs
              and packet == {"head_sha": HEAD,
                             "checks": {"test": "success",
                                        "cross-repo": "success"}})

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _dump(tmp, workflow_run(), live_pr(head_sha=OTHER),
                      trusted_runs(), trusted_check_runs())
        rc = _run_build(tmp, files)
        packet = json.loads((tmp / "checks.json").read_text())
        check("build: drift withholds the evidence (empty checks -> HOLD)",
              rc == 0 and packet["checks"] == {} and packet["head_sha"] == HEAD)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _dump(tmp, workflow_run(base_ref="evil"),
                      live_pr(base_ref="evil"), trusted_runs(),
                      trusted_check_runs())
        rc = _run_build(tmp, files)
        check("build: a non-default base ref exits non-zero (fail-closed)",
              rc == 3 and not (tmp / "refs.env").exists())

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _dump(tmp, workflow_run(), live_pr(), trusted_runs(),
              trusted_check_runs())
        rc = _run_build(tmp, None, out_refs="../escape.env")
        escaped = (Path(td).parent / "escape.env")
        check("build: an --out path outside the working dir is refused",
              rc == 3 and not escaped.exists())

    print(f"AUTONOMY ADVISORY: ALL PASS ({passed}/{passed})")
    return 0


def _dump(tmp, wr, pr, runs, check_runs):
    (tmp / "wr.json").write_text(json.dumps(wr))
    (tmp / "pr.json").write_text(json.dumps(pr))
    (tmp / "runs.json").write_text(json.dumps({"workflow_runs": runs}))
    (tmp / "checkruns.json").write_text(json.dumps({"check_runs": check_runs}))
    return tmp


def _run_build(tmp, _files, out_refs="refs.env", out_checks="checks.json"):
    import subprocess
    # Run with cwd=tmp and repo-relative filenames: the tool confines every
    # path it touches to the working directory, so the temp dir IS that root.
    argv = [sys.executable,
            str(Path(__file__).resolve().parents[1] / "tools" /
                "autonomy_advisory.py"),
            "--workflow-run", "wr.json",
            "--live-pr", "pr.json",
            "--runs", "runs.json",
            "--check-runs", "checkruns.json",
            "--repo", REPO, "--default-branch", DEFAULT,
            "--out-refs", out_refs,
            "--out-checks", out_checks]
    return subprocess.run(argv, cwd=tmp, capture_output=True,
                          text=True).returncode


if __name__ == "__main__":
    raise SystemExit(main())
