#!/usr/bin/env python3
"""Countervectors for the write-capable autonomy merge preflight."""

from __future__ import annotations

import copy
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "autonomy_merge", Path(__file__).resolve().parents[1] /
    "tools" / "autonomy_merge.py")
merge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = merge
SPEC.loader.exec_module(merge)

BASE = "a" * 40
HEAD = "b" * 40
passed = 0


def check(name, condition):
    global passed
    if not condition:
        raise AssertionError(name)
    passed += 1
    print(f"ok  {name}")


def fixtures():
    repo = {"full_name": merge.REPOSITORY,
            "default_branch": merge.DEFAULT_BRANCH}
    branch = {
        "name": merge.DEFAULT_BRANCH,
        "commit": {"sha": BASE},
        "protected": True,
        "protection": {
            "enabled": True,
            "required_status_checks": {
                "enforcement_level": "everyone",
                "contexts": ["test", "cross-repo"],
                "checks": [{"context": "test", "app_id": 15368},
                           {"context": "cross-repo", "app_id": 15368}],
            },
        },
    }
    pr = {
        "number": 38, "state": "open", "draft": False, "mergeable": True,
        "base": {"ref": merge.DEFAULT_BRANCH, "sha": BASE,
                 "repo": {"full_name": merge.REPOSITORY}},
        "head": {"ref": "feat/docs", "sha": HEAD,
                 "repo": {"full_name": merge.REPOSITORY}},
    }
    packet = {
        "autonomy_decision": "0.1", "decision": "ELIGIBLE",
        "action": "merge", "repository": merge.REPOSITORY,
        "base_sha": BASE, "head_sha": HEAD, "policy_from": BASE,
        "policy_sha256": "c" * 64, "facts": {"files_changed": 1},
        "checks": {"test": "success", "cross-repo": "success"},
        "reasons": [],
    }
    return repo, branch, pr, packet


def verdict(*items):
    return merge.evaluate(*items, 38, BASE, HEAD)


def mutation(index, path, value):
    values = [copy.deepcopy(x) for x in fixtures()]
    target = values[index]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return verdict(*values)


def main():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" /
                "autonomy-merge.yml").read_text(encoding="utf-8")
    check("workflow uses the accessible branch summary, not the admin endpoint",
          'branches/$DEFAULT_BRANCH" > branch.json' in workflow and
          'branches/$DEFAULT_BRANCH/protection' not in workflow)
    check("exact live pair, active protection and ELIGIBLE packet are READY",
          verdict(*fixtures())["decision"] == "READY")
    cases = [
        (1, ("commit", "sha"), "d" * 40, "advanced live base holds"),
        (2, ("head", "sha"), "d" * 40, "force-pushed head holds"),
        (2, ("base", "sha"), "d" * 40, "pull-request base drift holds"),
        (2, ("draft",), True, "draft pull request holds"),
        (2, ("mergeable",), None, "unknown mergeability holds"),
        (2, ("mergeable",), False, "conflicting pull request holds"),
        (1, ("protected",), False, "unprotected branch holds"),
        (1, ("protection", "enabled"), False,
         "disabled protection summary holds"),
        (1, ("protection", "required_status_checks", "enforcement_level"),
         "non_admins", "checks not enforced for everyone hold"),
        (3, ("decision",), "HOLD", "non-ELIGIBLE packet holds"),
        (3, ("head_sha",), "d" * 40, "stale packet head holds"),
        (3, ("policy_from",), "d" * 40, "policy revision drift holds"),
        (3, ("policy_sha256",), "short", "malformed policy digest holds"),
        (3, ("checks",), {"test": "success"},
         "missing required check in packet holds"),
    ]
    for index, path, value, name in cases:
        check(name, mutation(index, path, value)["decision"] == "HOLD")

    values = list(fixtures())
    values[1]["protection"]["required_status_checks"]["checks"][0]["app_id"] = 999
    check("same-named check from another app holds",
          verdict(*values)["decision"] == "HOLD")
    values = list(fixtures())
    values[1]["protection"] = "enabled"
    check("malformed protection summary holds without crashing",
          verdict(*values)["decision"] == "HOLD")
    values = list(fixtures())
    values[1]["protection"]["required_status_checks"] = ["test"]
    check("malformed required-check summary holds without crashing",
          verdict(*values)["decision"] == "HOLD")
    values = list(fixtures())
    values[3]["surprise"] = True
    check("a non-canonical packet shape holds",
          verdict(*values)["decision"] == "HOLD")
    check("unsafe expected SHA holds",
          merge.evaluate(*fixtures(), 38, "master", HEAD)["decision"] == "HOLD")

    with tempfile.TemporaryDirectory() as td:
        previous = Path.cwd()
        os.chdir(td)
        try:
            refused = False
            try:
                merge._confined("../escape.json")
            except merge.PreflightError:
                refused = True
            check("CLI output cannot escape its working directory", refused)
        finally:
            os.chdir(previous)

    print(f"AUTONOMY MERGE PREFLIGHT: ALL PASS ({passed}/{passed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
