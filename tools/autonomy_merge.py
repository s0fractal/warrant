#!/usr/bin/env python3
"""Final fail-closed preflight for the write-capable autonomy merge actor.

This module never calls GitHub and never writes to the repository.  It consumes
fresh GitHub API responses plus an ELIGIBLE packet from ``autonomy_gate.py`` and
returns READY only when the live pull request still names the exact base/head
pair, branch protection still enforces the signed policy's two trusted checks,
and GitHub reports the candidate mergeable.  The workflow performs the actual
merge with GitHub's expected-head parameter after re-running this preflight.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPOSITORY = "s0fractal/warrant"
DEFAULT_BRANCH = "master"
GITHUB_ACTIONS_APP_ID = 15368
REQUIRED_CHECKS = {
    ("test", GITHUB_ACTIONS_APP_ID),
    ("cross-repo", GITHUB_ACTIONS_APP_ID),
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PreflightError(ValueError):
    """Malformed input or unsafe path; distinct from an ordinary HOLD."""


def _get(obj, key):
    return obj.get(key) if isinstance(obj, dict) else None


def _confined(path_str: str) -> Path:
    root = Path.cwd().resolve()
    path = (root / path_str).resolve()
    if not path.is_relative_to(root):
        raise PreflightError(f"refusing path outside working directory: {path_str!r}")
    return path


def _load(path_str: str):
    try:
        return json.loads(_confined(path_str).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"unreadable JSON {path_str!r}: {exc}") from exc


def _enabled(obj, key) -> bool:
    value = _get(obj, key)
    return value is True or (isinstance(value, dict) and value.get("enabled") is True)


def protection_reasons(protection) -> list[str]:
    reasons: list[str] = []
    status = _get(protection, "required_status_checks") or {}
    if status.get("strict") is not True:
        reasons.append("branch protection does not require an up-to-date base")
    checks = status.get("checks")
    observed = set()
    if isinstance(checks, list):
        for item in checks:
            if isinstance(item, dict) and isinstance(item.get("context"), str) \
                    and type(item.get("app_id")) is int:
                observed.add((item["context"], item["app_id"]))
    if observed != REQUIRED_CHECKS:
        reasons.append("branch protection required checks/app identities drifted")
    reviews = _get(protection, "required_pull_request_reviews")
    if not isinstance(reviews, dict):
        reasons.append("branch protection no longer requires a pull request")
    elif reviews.get("required_approving_review_count") != 0:
        reasons.append("branch protection human-review count drifted from zero")
    if not _enabled(protection, "enforce_admins"):
        reasons.append("branch protection is not enforced for administrators")
    if _enabled(protection, "allow_force_pushes"):
        reasons.append("branch protection permits force pushes")
    if _enabled(protection, "allow_deletions"):
        reasons.append("branch protection permits deletion")
    return reasons


def packet_reasons(packet, base_sha: str, head_sha: str) -> list[str]:
    reasons: list[str] = []
    required = {
        "autonomy_decision", "decision", "action", "repository", "base_sha",
        "head_sha", "policy_from", "policy_sha256", "facts", "checks", "reasons",
    }
    if not isinstance(packet, dict) or set(packet) != required:
        return ["autonomy decision packet has a non-canonical shape"]
    expected = {
        "autonomy_decision": "0.1", "decision": "ELIGIBLE", "action": "merge",
        "repository": REPOSITORY, "base_sha": base_sha, "head_sha": head_sha,
        "policy_from": base_sha,
    }
    for key, value in expected.items():
        if packet.get(key) != value:
            reasons.append(f"autonomy decision {key} is not the expected exact value")
    if not isinstance(packet.get("policy_sha256"), str) or \
            not re.fullmatch(r"[0-9a-f]{64}", packet["policy_sha256"]):
        reasons.append("autonomy decision has no exact policy digest")
    if packet.get("checks") != {"test": "success", "cross-repo": "success"}:
        reasons.append("autonomy decision does not bind exactly both required checks")
    if not isinstance(packet.get("facts"), dict):
        reasons.append("autonomy decision has no measured diff facts")
    if packet.get("reasons") != []:
        reasons.append("autonomy decision still contains refusal reasons")
    return reasons


def live_reasons(repo, branch, pr, protection, pr_number: int,
                 base_sha: str, head_sha: str) -> list[str]:
    reasons: list[str] = []
    if not SHA_RE.fullmatch(base_sha) or not SHA_RE.fullmatch(head_sha):
        return ["expected base/head is not a full lowercase commit SHA"]
    if _get(repo, "full_name") != REPOSITORY or \
            _get(repo, "default_branch") != DEFAULT_BRANCH:
        reasons.append("repository identity or default branch drifted")
    if _get(_get(branch, "commit") or {}, "sha") != base_sha or \
            _get(branch, "name") != DEFAULT_BRANCH:
        reasons.append("live default-branch tip differs from the evaluated base")
    if _get(pr, "number") != pr_number or _get(pr, "state") != "open":
        reasons.append("pull request is not the expected open pull request")
    if _get(pr, "draft") is not False:
        reasons.append("pull request is draft or draft state is unavailable")
    base = _get(pr, "base") or {}
    head = _get(pr, "head") or {}
    if _get(base, "ref") != DEFAULT_BRANCH or _get(base, "sha") != base_sha:
        reasons.append("live pull-request base differs from the evaluated base")
    if _get(head, "sha") != head_sha:
        reasons.append("live pull-request head differs from the evaluated head")
    if _get(_get(base, "repo") or {}, "full_name") != REPOSITORY or \
            _get(_get(head, "repo") or {}, "full_name") != REPOSITORY:
        reasons.append("pull request is not same-repository on both sides")
    if _get(pr, "mergeable") is not True:
        reasons.append("GitHub does not currently report the pull request mergeable")
    reasons.extend(protection_reasons(protection))
    return reasons


def evaluate(repo, branch, pr, protection, packet, pr_number: int,
             base_sha: str, head_sha: str) -> dict:
    reasons = live_reasons(repo, branch, pr, protection, pr_number,
                           base_sha, head_sha)
    reasons.extend(packet_reasons(packet, base_sha, head_sha))
    reasons = sorted(set(reasons))
    return {
        "autonomy_merge_preflight": "0.1",
        "decision": "READY" if not reasons else "HOLD",
        "repository": REPOSITORY,
        "pull_request": pr_number,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--pull-request", required=True)
    parser.add_argument("--protection", required=True)
    parser.add_argument("--decision-packet", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    try:
        packet = evaluate(
            _load(args.repo), _load(args.branch), _load(args.pull_request),
            _load(args.protection), _load(args.decision_packet),
            args.pr_number, args.base, args.head)
        rendered = json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n"
        if args.out:
            _confined(args.out).write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if packet["decision"] == "READY" else 1
    except (PreflightError, TypeError, KeyError) as exc:
        print(f"autonomy merge preflight refused (fail-closed): {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
