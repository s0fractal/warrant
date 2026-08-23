#!/usr/bin/env python3
"""Can a change award itself a passing verdict?

It could. A pull request that rewrote `.warrant/gate.wpl` into a tautology got an
ACCEPT out of the gate, because the workflow ran the gate from the pull request's
own checkout. This file reproduces that, proves the fix defeats it, and then
checks that the workflow still honours the arrangement the fix depends on — a
guarantee in a Python file is worth nothing if the YAML stops obeying it.
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
    git(root, "commit", "-q", "-m", "base: the gate under test")
    base = git(root, "rev-parse", "HEAD").strip()

    (root / "big-change.txt").write_text(OVERSIZE)
    (root / ".warrant/gate.wpl").write_text(TAUTOLOGY)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m",
        "chore: routine change\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>")
    return base, git(root, "rev-parse", "HEAD").strip()


def check_workflow() -> list[str]:
    """The YAML has to keep the promise the Python relies on."""
    text = WORKFLOW.read_text()
    problems = []
    if "ref: ${{ github.event.pull_request.base.sha }}" not in text:
        problems.append("the verdict job does not check out the base revision")
    if "--policy-from" not in text:
        problems.append("the gate is invoked without --policy-from, so the rule "
                        "would come from the working tree")
    if "pull_request_target" in text:
        problems.append("pull_request_target appears; with a head checkout that is "
                        "the documented way to hand a change write capability")

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

        # 3. And the report says which bytes decided.
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
