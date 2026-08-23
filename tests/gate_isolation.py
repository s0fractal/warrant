#!/usr/bin/env python3
"""Can a change award itself a passing verdict?

Twice it could, at two different levels.

A pull request that rewrote `.warrant/gate.wpl` into a tautology got an ACCEPT,
because the workflow ran the gate from the pull request's own checkout. Reading
the rule from the base revision fixed that — and moved the hole up: on
`pull_request`, GitHub takes the *workflow* from the pull request, so a change
could rewrite `agent-gate.yml`, restore a head checkout and fabricate a comment.
The defendant had stopped editing the judge and was still editing the courtroom.

This file reproduces the first attack, proves the fix defeats it, reproduces the
second as a rewritten workflow, and then checks the arrangement both fixes depend
on: a guarantee in Python is worth nothing if the YAML stops obeying it.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-gate.yml"

TAUTOLOGY = """# Looks ordinary. Is not.
fact proposed_by_agent: bool = {{proposed_by_agent}}
fact touches_ci:        bool = {{touches_ci}}

check proposed_by_agent || !proposed_by_agent || touches_ci
"""

OVERSIZE = "\n".join(f"line {n} of a change too large for the rule" for n in range(400))


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(root), *arguments],
                          capture_output=True, text=True, check=True).stdout


def gate(cwd: Path, *arguments: str) -> tuple[int, str]:
    result = subprocess.run([sys.executable, str(cwd / "tools/gate.py"), *arguments],
                            capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout + result.stderr


def scenario(root: Path) -> tuple[str, str]:
    """A repository whose head rewrites the rule it will be judged by."""
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(root)],
                   check=True, capture_output=True)
    git(root, "config", "user.email", "isolation@example.invalid")
    git(root, "config", "user.name", "isolation test")

    # The base carries the gate as it stands in the working tree, so this tests
    # the code under review rather than whatever was last committed.
    for path in ("tools/gate.py", ".warrant/gate.wpl"):
        (root / path).write_text((ROOT / path).read_text())
    git(root, "add", "-A")
    # In CI the copies are identical to HEAD and there is nothing to commit; the
    # point is to have a base revision, not to have a change in it.
    git(root, "commit", "-q", "--allow-empty", "-m", "base: the gate under test")
    base = git(root, "rev-parse", "HEAD").strip()

    (root / "big-change.txt").write_text(OVERSIZE)
    (root / ".warrant/gate.wpl").write_text(TAUTOLOGY)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m",
        "chore: routine change\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>")
    return base, git(root, "rev-parse", "HEAD").strip()


def check_workflow(path: Path = WORKFLOW) -> list[str]:
    """The YAML has to keep the promise the Python relies on."""
    text = path.read_text()
    problems = []
    if "ref: ${{ github.event.pull_request.base.sha }}" not in text:
        problems.append("the verdict job does not check out the base revision")
    if "--policy-from" not in text:
        problems.append("the gate is invoked without --policy-from, so the rule "
                        "would come from the working tree")
    if re.search(r"^on:\s*$", text, re.M) and "pull_request_target:" not in text:
        problems.append("the workflow triggers on pull_request, so GitHub takes the "
                        "workflow itself from the change — the control plane belongs "
                        "to the base branch")
    if re.search(r"^\s+pull_request:\s*$", text, re.M):
        problems.append("a bare pull_request trigger is present")
    head_checkout = re.search(r"actions/checkout[\s\S]{0,200}?ref:\s*\$\{\{[^}]*head", text)
    if head_checkout:
        problems.append("a checkout step takes the head revision; under "
                        "pull_request_target that hands the change a write-capable "
                        "token, which is the failure this trigger is infamous for")
    if "refs/pull/" not in text:
        problems.append("the head is fetched by SHA rather than refs/pull/<n>/head, "
                        "which does not exist in this repository for a fork")

    # The job that can write must not check out the repository at all.
    jobs = re.split(r"\n  (?=\w[\w-]*:\n)", text)
    for job in jobs:
        writes = "pull-requests: write" in job
        checks_out = "actions/checkout" in job
        if writes and checks_out:
            problems.append("a job with pull-requests: write also checks out the "
                            "repository — write capability and repository code must "
                            "stay in different jobs")
    return problems


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "repo"
        base, head = scenario(root)

        # 1. The attack, as it worked: the gate reads the rule from the change.
        code, output = gate(root, "--base", base, "--head", head)
        if "# Gate report — ACCEPT" not in output:
            failures.append("the attack no longer reproduces, so this test has "
                            "stopped testing anything — check why before deleting it")
        else:
            print("OK   reproduced: reading the rule from the change yields ACCEPT")

        # 2. The fix: the rule comes from the base revision instead.
        code, output = gate(root, "--base", base, "--head", head,
                            "--policy-from", base)
        if "# Gate report — REJECT" not in output:
            failures.append(f"--policy-from {base[:12]} did not restore the base "
                            f"rule's verdict; got:\n{output[:400]}")
        else:
            print("OK   the base revision's rule decides, and rejects the change")

        # 3. The second attack: the change rewrites the workflow itself.
        hostile = (root / ".github/workflows/agent-gate.yml")
        hostile.write_text(WORKFLOW.read_text()
                           .replace("pull_request_target:", "pull_request:")
                           .replace("ref: ${{ github.event.pull_request.base.sha }}",
                                    "ref: ${{ github.event.pull_request.head.sha }}"))
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "ci: adjust the workflow")
        problems = check_workflow(hostile)
        if len(problems) < 2:
            failures.append("a workflow rewritten to run head code on pull_request "
                            f"was not caught; found only {problems}")
        else:
            print("OK   a workflow rewritten to run the change's own code is caught")

        # 4. And the report says which bytes decided.
        report = (root / "gate-report.md").read_text()
        if f"at {base[:12]}" not in report:
            failures.append("the report does not name the revision the rule came from")
        else:
            print("OK   the report names the revision the rule was read from")

    for problem in check_workflow():
        failures.append(f"workflow: {problem}")
    if not [f for f in failures if f.startswith("workflow:")]:
        print("OK   the workflow runs base code and keeps write capability apart")

    for failure in failures:
        print("FAIL", failure, file=sys.stderr)
    if failures:
        return 1
    print("\nGATE-ISOLATION: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
