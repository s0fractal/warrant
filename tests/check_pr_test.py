#!/usr/bin/env python3
"""Tests for `tools/check_pr.py` contributor pre-flight checks (`CP01..CP08`).

    python3 tests/check_pr_test.py
"""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from world import ROOT, check, run_sections

sys.path.insert(0, str(ROOT / "tools"))
import check_pr as CP  # noqa: E402


def check_pr_cases():
    # CP01: Clean file check passes with fresh warrant_verify.py and valid mutants
    rep_clean = CP.run_check(ROOT, files=["warrant/resolve.py"])
    check("CP01 check_pr passes on clean warrant/resolve.py and runs core boundary B1",
          rep_clean["ok"] is True
          and rep_clean["verify"]["ok"] is True
          and rep_clean["mutants"]["ok"] is True
          and rep_clean["boundary"]["ran"] is True
          and rep_clean["boundary"]["ok"] is True
          and "T179" in rep_clean["mutants"]["affected_mutants"],
          rep_clean)

    # CP02: Stale (missing) and ambiguous (duplicate match) mutants fail closed
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "sample.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
        fake_mutants = [
            ("M_OK", "sample.py", "x = 1\nx = 1", "x = 2", "tests/t.py", ["T1"]),
            ("M_STALE", "sample.py", "does_not_exist()", "pass", "tests/t.py", ["T1"]),
            ("M_AMB", "sample.py", "x = 1", "x = 0", "tests/t.py", ["T1"]),
        ]
        mres = CP.check_mutants_fresh(tmp, ["sample.py"], mutants=fake_mutants)
    check("CP02 check_mutants_fresh flags both missing (stale) and multi-match (ambiguous) mutants",
          mres["ok"] is False
          and [x["id"] for x in mres["stale"]] == ["M_STALE"]
          and [x["id"] for x in mres["ambiguous"]] == ["M_AMB"],
          mres)

    # CP03: Stale warrant_verify.py is detected before pushing
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        shutil.copytree(ROOT / "warrant", tmp / "warrant")
        shutil.copytree(ROOT / "tools", tmp / "tools")
        (tmp / "warrant_verify.py").write_text("# stale copy\n", encoding="utf-8")
        vres = CP.check_verify_fresh(tmp)
    check("CP03 check_verify_fresh detects stale warrant_verify.py",
          vres["ok"] is False and vres["stale"] is True,
          vres)

    # CP04: End-to-end CLI returns 0 with valid JSON on clean files
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = CP.main(["--files", "warrant/resolve.py", "--json"])
    parsed = json.loads(out_buf.getvalue()) if out_buf.getvalue().strip() else {}
    check("CP04 CLI check_pr.py --files warrant/resolve.py --json exits 0 with structured report",
          rc == 0 and parsed.get("ok") is True and "T370" in parsed.get("mutants", {}).get("affected_mutants", []),
          {"rc": rc, "parsed": parsed, "err": err_buf.getvalue()})

    # CP05: Invalid git base ref fails cleanly with exit code 2
    out_bad, err_bad = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_bad), contextlib.redirect_stderr(err_bad):
        rc_bad = CP.main(["--base", "refs/heads/no-such-base-ref-xyz"])
    check("CP05 CLI check_pr.py returns exit code 2 on unknown git base ref",
          rc_bad == 2 and "error" in err_bad.getvalue(),
          {"rc": rc_bad, "err": err_bad.getvalue()})

    # CP06: the harness's multi-replacement form (a list of (find, replace) pairs) is checked pair by pair (codex F1)
    rep_multi = CP.run_check(ROOT, files=["warrant/across.py"])
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "sample.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        pair_mutants = [("M_PAIRS", "sample.py", [("a = 1", "a = 0"), ("gone()", "pass")], None, "tests/t.py", ["T1"])]
        pres = CP.check_mutants_fresh(tmp, ["sample.py"], mutants=pair_mutants)
    check("CP06 multi-replacement mutants: real X6 checks clean, a stale second pair is reported",
          rep_multi["mutants"]["ok"] is True and "X6" in rep_multi["mutants"]["affected_mutants"]
          and [x["id"] for x in pres["stale"]] == ["M_PAIRS"] and pres["stale"][0]["reason"] == "FIND_NOT_FOUND (pair 1)",
          {"multi": rep_multi["mutants"], "pairs": pres})

    # CP07: a new core module not yet `git add`ed is part of the default discovery (codex F2)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
               "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
               "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "maintenance.auto", "GIT_CONFIG_VALUE_0": "false",
               "GIT_CONFIG_KEY_1": "gc.auto", "GIT_CONFIG_VALUE_1": "0"}
        (tmp / "warrant").mkdir()
        (tmp / "warrant" / "old.py").write_text("x = 1\n", encoding="utf-8")
        for args in (["init", "-q", "-b", "master"], ["add", "."], ["commit", "-qm", "base"]):
            subprocess.run(["git", "-C", str(tmp), *args], env=env, check=True, capture_output=True)
        (tmp / "warrant" / "new.py").write_text("y = 2\n", encoding="utf-8")
        (tmp / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        (tmp / "ignored.py").write_text("", encoding="utf-8")
        found = CP.changed_files(tmp, "master")
    check("CP07 changed_files includes untracked, not ignored, files",
          found == [".gitignore", "warrant/new.py"], found)

    # CP08: a base ref that git would read as an option is refused before git runs (exit 2)
    out_opt, err_opt = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_opt), contextlib.redirect_stderr(err_opt):
        rc_opt = CP.main(["--base=--output=/dev/null"])
    check("CP08 CLI check_pr.py refuses a base ref starting with '-'",
          rc_opt == 2 and "must not start with" in err_opt.getvalue(),
          {"rc": rc_opt, "err": err_opt.getvalue()})


if __name__ == "__main__":
    sys.exit(run_sections([check_pr_cases]))
