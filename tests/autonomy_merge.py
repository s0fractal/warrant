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
    branch = {"name": merge.DEFAULT_BRANCH, "commit": {"sha": BASE}}
    pr = {
        "number": 38, "state": "open", "draft": False, "mergeable": True,
        "base": {"ref": merge.DEFAULT_BRANCH, "sha": BASE,
                 "repo": {"full_name": merge.REPOSITORY}},
        "head": {"ref": "feat/docs", "sha": HEAD,
                 "repo": {"full_name": merge.REPOSITORY}},
    }
    protection = {
        "required_status_checks": {
            "strict": True,
            "checks": [{"context": "test", "app_id": 15368},
                       {"context": "cross-repo", "app_id": 15368}],
        },
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }
    packet = {
        "autonomy_decision": "0.1", "decision": "ELIGIBLE",
        "action": "merge", "repository": merge.REPOSITORY,
        "base_sha": BASE, "head_sha": HEAD, "policy_from": BASE,
        "policy_sha256": "c" * 64, "facts": {"files_changed": 1},
        "checks": {"test": "success", "cross-repo": "success"},
        "reasons": [],
    }
    return repo, branch, pr, protection, packet


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
    check("exact live pair, active protection and ELIGIBLE packet are READY",
          verdict(*fixtures())["decision"] == "READY")
    cases = [
        (1, ("commit", "sha"), "d" * 40, "advanced live base holds"),
        (2, ("head", "sha"), "d" * 40, "force-pushed head holds"),
        (2, ("base", "sha"), "d" * 40, "pull-request base drift holds"),
        (2, ("draft",), True, "draft pull request holds"),
        (2, ("mergeable",), None, "unknown mergeability holds"),
        (2, ("mergeable",), False, "conflicting pull request holds"),
        (3, ("required_status_checks", "strict"), False,
         "non-strict status checks hold"),
        (3, ("enforce_admins", "enabled"), False,
         "admin bypass holds"),
        (3, ("allow_force_pushes", "enabled"), True,
         "force-push permission holds"),
        (3, ("allow_deletions", "enabled"), True,
         "deletion permission holds"),
        (4, ("decision",), "HOLD", "non-ELIGIBLE packet holds"),
        (4, ("head_sha",), "d" * 40, "stale packet head holds"),
        (4, ("policy_from",), "d" * 40, "policy revision drift holds"),
        (4, ("policy_sha256",), "short", "malformed policy digest holds"),
        (4, ("checks",), {"test": "success"},
         "missing required check in packet holds"),
    ]
    for index, path, value, name in cases:
        check(name, mutation(index, path, value)["decision"] == "HOLD")

    values = list(fixtures())
    values[3]["required_status_checks"]["checks"][0]["app_id"] = 999
    check("same-named check from another app holds",
          verdict(*values)["decision"] == "HOLD")
    values = list(fixtures())
    values[3]["required_pull_request_reviews"] = None
    check("removing the pull-request requirement holds",
          verdict(*values)["decision"] == "HOLD")
    values = list(fixtures())
    values[4]["surprise"] = True
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
