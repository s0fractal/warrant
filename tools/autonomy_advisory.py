#!/usr/bin/env python3
"""Trusted pre-processing for the autonomy advisory workflow.

The advisory workflow is loaded from the default branch, but the base revision
it would otherwise trust is chosen by the pull request.  This module turns the
raw GitHub event and API payloads into a base/head pair and a required-check
packet, or refuses -- fail-closed, before anything from the base or head is
read or executed.  It exists so the trust-binding decisions are ordinary Python
with countervectors, not unreviewable YAML heredocs.

Three binding properties, each with an executable countervector in
``tests/autonomy_advisory.py``:

  P1a  the base must be the repository's DEFAULT BRANCH, not merely same-repo.
       A same-repo feature branch used as a PR base would otherwise supply the
       evaluator, policy and trust bytes that judge that same pull request.
  P1b  the evaluated head is the immutable ``workflow_run.head_sha`` -- the exact
       commit the required checks ran on.  Live drift (a force-push, or the base
       branch advancing) is detected and withholds the check evidence, so a
       green packet can never describe a different revision pair than the one
       the checks actually observed.
  P1c  required-check evidence is bound to trusted workflow IDENTITY -- the
       default-branch workflow file, the github-actions app, this head, this
       pull request, and a pull_request event -- never to a bare check-run name
       that any app or a candidate workflow could mint.

This module never merges, pushes or checks out anything.  On refusal it exits
non-zero so the caller stops before it would read base-owned bytes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TRUSTED_APP = "github-actions"

# The required checks and the exact default-branch workflow file each must come
# from.  Binding name -> path is what makes a name collision from another app or
# workflow inert: a check called "test" only counts if it belongs to a check
# suite produced by ci.yml on this head and pull request.
REQUIRED_CHECK_WORKFLOW = {
    "test": ".github/workflows/ci.yml",
    "cross-repo": ".github/workflows/x1-cross-repo.yml",
}


class AdvisoryRefusal(Exception):
    """A fail-closed refusal raised before any base/head bytes are trusted."""


def _get(obj, key):
    return obj.get(key) if isinstance(obj, dict) else None


def _is_sha(value) -> bool:
    return isinstance(value, str) and bool(SHA_RE.fullmatch(value))


def _app_slug(check) -> str | None:
    return _get(_get(check, "app") or {}, "slug")


def _suite_id(check):
    return _get(_get(check, "check_suite") or {}, "id")


def _run_pr_numbers(run) -> set:
    prs = _get(run, "pull_requests")
    if not isinstance(prs, list):
        return set()
    return {p.get("number") for p in prs if isinstance(p, dict)}


def _refuse(msg: str):
    raise AdvisoryRefusal(msg)


def _snapshot(workflow_run, default_branch: str) -> tuple[int, str, str]:
    """Extract (pr_number, base_sha, head_sha) from the immutable run snapshot."""
    if _get(workflow_run, "event") != "pull_request":
        _refuse("workflow_run event is not pull_request")
    run_head = _get(workflow_run, "head_sha")
    if not _is_sha(run_head):
        _refuse("workflow_run.head_sha is not a commit sha")
    prs = _get(workflow_run, "pull_requests")
    if not isinstance(prs, list) or not prs:
        _refuse("workflow_run carries no pull request snapshot")
    snap = prs[0]
    snap_num = _get(snap, "number")
    snap_base = _get(snap, "base") or {}
    snap_base_sha = _get(snap_base, "sha")
    snap_head_sha = _get(_get(snap, "head") or {}, "sha")
    if not isinstance(snap_num, int):
        _refuse("workflow_run snapshot has no pull request number")
    if not _is_sha(snap_base_sha):
        _refuse("workflow_run snapshot base sha is not a commit sha")
    if snap_head_sha != run_head:
        _refuse("workflow_run snapshot head does not match its head_sha")
    if _get(snap_base, "ref") != default_branch:
        _refuse(f"snapshot base ref {_get(snap_base, 'ref')!r} is not {default_branch!r}")
    return snap_num, snap_base_sha, run_head


def _require_live_identity(live_pr, snap_num: int, repo: str,
                           default_branch: str) -> tuple[dict, dict]:
    """Validate the live pull request identity; return (base, head) objects.

    P1a lives here: same-repo is not enough; the live base must BE the default
    branch, checked against the authoritative current pull request.
    """
    if _get(live_pr, "number") != snap_num:
        _refuse("live pull request number does not match the run snapshot")
    live_base = _get(live_pr, "base") or {}
    live_head = _get(live_pr, "head") or {}
    if _get(_get(live_base, "repo") or {}, "full_name") != repo:
        _refuse("live pull request base repository is not this repository")
    if _get(_get(live_head, "repo") or {}, "full_name") != repo:
        _refuse("live pull request head is a fork, not this repository")
    if _get(live_base, "ref") != default_branch:
        _refuse(f"live pull request base ref is not {default_branch!r}")
    return live_base, live_head


def resolve_refs(workflow_run, live_pr, repo: str,
                 default_branch: str) -> tuple[str, str, list[str]]:
    """Return (base_sha, head_sha, drift_reasons) or raise AdvisoryRefusal.

    base_sha is the run's snapshot base (proven, by the caller, to be an
    ancestor of the default branch); head_sha is the immutable commit the
    required checks ran on.  drift_reasons is non-empty when the live pull
    request no longer matches that snapshot.
    """
    if not isinstance(default_branch, str) or not default_branch:
        _refuse("no default branch was supplied")
    if not isinstance(repo, str) or "/" not in repo:
        _refuse("no repository was supplied")

    snap_num, base_sha, head_sha = _snapshot(workflow_run, default_branch)
    live_base, live_head = _require_live_identity(
        live_pr, snap_num, repo, default_branch)

    drift = []
    if _get(live_head, "sha") != head_sha:
        drift.append("candidate head advanced since the required checks ran")
    if _get(live_base, "sha") != base_sha:
        drift.append("base branch advanced since the required checks ran")
    return base_sha, head_sha, drift


def _trusted_suites(runs, path: str, head_sha: str, pr_number: int) -> set:
    return {
        _get(r, "check_suite_id")
        for r in runs
        if _get(r, "path") == path
        and _get(r, "head_sha") == head_sha
        and _get(r, "event") == "pull_request"
        and pr_number in _run_pr_numbers(r)
        and _get(r, "check_suite_id") is not None
    }


def select_checks(runs, check_runs, head_sha: str,
                  pr_number: int) -> dict[str, str]:
    """Map each required check to success/failure/pending from TRUSTED evidence.

    A check counts only if it is produced by the github-actions app and belongs
    to a check suite owned by the required workflow file, on this head and pull
    request.  Anything else -- a same-named check from another app, another
    workflow, another head -- is simply absent, which the gate treats as a HOLD.
    """
    out: dict[str, str] = {}
    if not isinstance(runs, list) or not isinstance(check_runs, list):
        return out
    for name, path in REQUIRED_CHECK_WORKFLOW.items():
        suites = _trusted_suites(runs, path, head_sha, pr_number)
        matched = [c for c in check_runs
                   if _get(c, "name") == name
                   and _app_slug(c) == TRUSTED_APP
                   and _suite_id(c) in suites]
        if not matched:
            continue
        if any(_get(c, "status") != "completed" for c in matched):
            out[name] = "pending"
        elif all(_get(c, "conclusion") == "success" for c in matched):
            out[name] = "success"
        else:
            out[name] = "failure"
    return out


def _load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build(args) -> int:
    workflow_run = _load(args.workflow_run)
    live_pr = _load(args.live_pr)
    runs_doc = _load(args.runs)
    check_doc = _load(args.check_runs)
    runs = runs_doc.get("workflow_runs") if isinstance(runs_doc, dict) else None
    check_runs = check_doc.get("check_runs") if isinstance(check_doc, dict) else None

    base_sha, head_sha, drift = resolve_refs(
        workflow_run, live_pr, args.repo, args.default_branch)
    checks = select_checks(runs or [], check_runs or [], head_sha,
                           _get(live_pr, "number"))
    if drift:
        # The evidence no longer describes the current pull request: withhold it
        # so the gate HOLDs.  The evaluated pair stays the immutable one.
        checks = {}
        for reason in drift:
            print(f"drift: {reason}", file=sys.stderr)

    Path(args.out_refs).write_text(
        f"base={base_sha}\nhead={head_sha}\n", encoding="utf-8")
    Path(args.out_checks).write_text(
        json.dumps({"head_sha": head_sha, "checks": checks},
                   sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8")
    print(f"base={base_sha} head={head_sha} checks={checks} drift={bool(drift)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--live-pr", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--check-runs", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--default-branch", required=True)
    parser.add_argument("--out-refs", required=True)
    parser.add_argument("--out-checks", required=True)
    args = parser.parse_args()
    try:
        return build(args)
    except AdvisoryRefusal as exc:
        print(f"autonomy-advisory refused (fail-closed): {exc}", file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"autonomy-advisory error (fail-closed): {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
