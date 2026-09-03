#!/usr/bin/env python3
"""Final fail-closed preflight for the write-capable autonomy merge actor.

This module never calls GitHub and never writes to the repository.  It consumes
fresh GitHub API responses plus an ELIGIBLE packet from ``autonomy_gate.py`` and
returns READY only when the live pull request still names the exact base/head
pair, the public branch payload says protection enforces the signed policy's
two trusted checks for everyone, and GitHub reports the candidate mergeable.
The workflow performs the actual merge with GitHub's expected-head parameter
after re-running this preflight.

The actor deliberately consumes the ordinary ``Get a branch`` response.  The
full branch-protection endpoint requires repository-administration permission,
which the workflow ``GITHUB_TOKEN`` does not have.  Fields available only from
that endpoint (for example force-push and deletion policy) are not part of this
merge predicate.  The actor proves a narrower fact: a same-repository, exact-
head pull request is mergeable at the live base while the two named checks from
the GitHub Actions app are enforced for everyone.
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


def branch_protection_reasons(branch) -> list[str]:
    reasons: list[str] = []
    if _get(branch, "protected") is not True:
        reasons.append("default branch is not protected")
    protection = _get(branch, "protection") or {}
    if not isinstance(protection, dict):
        return reasons + ["default-branch protection summary is malformed"]
    if protection.get("enabled") is not True:
        reasons.append("default-branch protection summary is not enabled")
    status = protection.get("required_status_checks") or {}
    if not isinstance(status, dict):
        return reasons + ["required-status-check summary is malformed"]
    if status.get("enforcement_level") != "everyone":
        reasons.append("required checks are not enforced for everyone")
    checks = status.get("checks")
    observed = []
    if isinstance(checks, list):
        for item in checks:
            if isinstance(item, dict) and isinstance(item.get("context"), str) \
                    and type(item.get("app_id")) is int:
                observed.append((item["context"], item["app_id"]))
    if len(observed) != len(REQUIRED_CHECKS) or set(observed) != REQUIRED_CHECKS:
        reasons.append("branch protection required checks/app identities drifted")
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


def _repository_reasons(repo, branch, base_sha: str) -> list[str]:
    reasons: list[str] = []
    if _get(repo, "full_name") != REPOSITORY or \
            _get(repo, "default_branch") != DEFAULT_BRANCH:
        reasons.append("repository identity or default branch drifted")
    if _get(_get(branch, "commit") or {}, "sha") != base_sha or \
            _get(branch, "name") != DEFAULT_BRANCH:
        reasons.append("live default-branch tip differs from the evaluated base")
    return reasons


def _pull_request_reasons(pr, pr_number: int, base_sha: str,
                          head_sha: str) -> list[str]:
    reasons: list[str] = []
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
    return reasons


def live_reasons(repo, branch, pr, pr_number: int, base_sha: str,
                 head_sha: str) -> list[str]:
    if not SHA_RE.fullmatch(base_sha) or not SHA_RE.fullmatch(head_sha):
        return ["expected base/head is not a full lowercase commit SHA"]
    reasons = _repository_reasons(repo, branch, base_sha)
    reasons.extend(_pull_request_reasons(pr, pr_number, base_sha, head_sha))
    reasons.extend(branch_protection_reasons(branch))
    return reasons


def evaluate(repo, branch, pr, packet, pr_number: int, base_sha: str,
             head_sha: str) -> dict:
    reasons = live_reasons(repo, branch, pr, pr_number, base_sha, head_sha)
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
    parser.add_argument("--decision-packet", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    try:
        # Validate every CLI-constructed path before reading or writing any of
        # them. Keeping the resolved output object separate also makes it
        # impossible for a later refactor to bypass the confinement check.
        output = _confined(args.out) if args.out else None
        packet = evaluate(
            _load(args.repo), _load(args.branch), _load(args.pull_request),
            _load(args.decision_packet), args.pr_number, args.base, args.head)
        rendered = json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n"
        if output:
            output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if packet["decision"] == "READY" else 1
    except (PreflightError, TypeError, KeyError) as exc:
        print(f"autonomy merge preflight refused (fail-closed): {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
