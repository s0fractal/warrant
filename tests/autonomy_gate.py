#!/usr/bin/env python3
"""Countervectors for the agent autonomy capability envelope.

Framework-free so the control runs in the same clean environment as the gate.
Every dangerous shape below must produce HOLD or DENY; a surviving mutation is
an executable false-authority finding, not a prose disagreement.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "autonomy_gate", REPO / "tools" / "autonomy_gate.py")
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)

passed = 0


def check(name, condition):
    global passed
    if not condition:
        raise AssertionError(name)
    passed += 1
    print(f"ok  {name}")


def policy():
    return json.loads((REPO / gate.POLICY_PATH).read_text(encoding="utf-8"))


def facts(path="docs/note.md", status="A", **overrides):
    values = dict(
        paths=[path], statuses={path: status}, lines_added=3, lines_removed=0,
        binary_paths=[], symlink_paths=[], submodule_paths=[],
        unsupported_mode_paths=[], commits=1, merge_commits=0,
        agent_provenance=True, authority_markers=[])
    values.update(overrides)
    return gate.DiffFacts(**values)


def decision(pol, fact, action="draft_pull_request", checks=None,
             check_errors=None, auth_errors=None):
    return gate.decide(pol, fact, action, checks or {}, check_errors or [],
                       auth_errors or [])


def run(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(cwd, message):
    run("git", "add", ".", cwd=cwd)
    run("git", "commit", "-m", message, cwd=cwd)
    return run("git", "rev-parse", "HEAD", cwd=cwd)


def signature_fixture(tmp: Path, pol: dict):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    (tmp / "policies").mkdir()
    (tmp / "trust").mkdir()
    pol["status"] = "active"
    pol["actions"]["merge"] = True
    raw = (json.dumps(pol, indent=2, ensure_ascii=False) + "\n").encode()
    (tmp / gate.POLICY_PATH).write_bytes(raw)

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    (tmp / pol["authorization"]["trusted_key_path"]).write_text(
        "ed25519:" + base64.b64encode(public).decode() + "\n")
    now = dt.datetime.now(dt.timezone.utc)
    auth = {
        "authorization_format": pol["authorization"]["format"],
        "repository": pol["repository"],
        "base_branch": pol["base_branch"],
        "policy_sha256": gate.sha256(raw),
        "actions": ["merge"],
        "not_before": (now - dt.timedelta(minutes=1)).isoformat(),
        "not_after": (now + dt.timedelta(days=30)).isoformat(),
    }
    signature = private.sign(gate.canonical(auth).encode())
    auth["signature"] = base64.b64encode(signature).decode()
    (tmp / pol["authorization"]["authorization_path"]).write_text(
        json.dumps(auth, indent=2) + "\n")
    return raw, now


def main():
    pol = policy()
    check("shipped bootstrap policy has a valid closed shape",
          gate.policy_problems(pol) == [])

    state, reasons = decision(pol, facts())
    check("draft policy grants no standing action", state == "HOLD" and
          any("inactive" in r for r in reasons))

    active = copy.deepcopy(pol)
    active["status"] = "active"
    state, reasons = decision(active, facts(), auth_errors=[])
    check("active bounded draft-PR action can become eligible", state == "ELIGIBLE")

    state, reasons = decision(active, facts("tools/autonomy_gate.py"))
    check("a candidate cannot change its evaluator", state == "DENY" and
          any("protected" in r for r in reasons))

    state, reasons = decision(
        active, facts(".github/workflows/autonomy-advisory.yml"))
    check("a candidate cannot change its authorizing workflow", state == "DENY")

    state, reasons = decision(active, facts("policies/agent-autonomy-v0.1.json"))
    check("a candidate cannot change its own policy", state == "DENY")

    state, reasons = decision(active, facts("README.md"))
    check("a path outside the autonomous lane is denied", state == "DENY")

    state, reasons = decision(active, facts(status="D"))
    check("deletion is denied", state == "DENY" and
          any("deletions" in r for r in reasons))

    state, reasons = decision(active, facts(binary_paths=["docs/note.md"]))
    check("binary diff is denied", state == "DENY")

    state, reasons = decision(active, facts(symlink_paths=["docs/note.md"]))
    check("symlink is denied", state == "DENY")

    state, reasons = decision(active, facts(submodule_paths=["docs/note.md"]))
    check("submodule is denied", state == "DENY")

    state, reasons = decision(
        active, facts(unsupported_mode_paths=["docs/run-me.md"]))
    check("executable or special mode is denied", state == "DENY")

    state, reasons = decision(active, facts(status="T"))
    check("Git type change is denied", state == "DENY")

    state, reasons = decision(active, facts(merge_commits=1))
    check("merge commit in candidate is denied", state == "DENY")

    state, reasons = decision(active, facts(agent_provenance=False))
    check("undeclared agent provenance is denied", state == "DENY")

    state, reasons = decision(active, facts(), auth_errors=["signature absent"])
    check("active policy without standing signature is held", state == "HOLD")

    state, reasons = decision(
        active, facts(authority_markers=["Reviewed-by:"]))
    check("agent-authored review authority is denied", state == "DENY")

    merge_pol = copy.deepcopy(active)
    merge_pol["actions"]["merge"] = True
    state, reasons = decision(
        merge_pol, facts(), "merge", {"test": "success"})
    check("missing required check holds merge", state == "HOLD" and
          any("cross-repo" in r for r in reasons))

    state, reasons = decision(
        merge_pol, facts(), "merge",
        {"test": "success", "cross-repo": "failure"})
    check("failed required check holds merge", state == "HOLD")

    state, reasons = decision(
        merge_pol, facts(), "merge",
        {"test": "success", "cross-repo": "success"})
    check("all bounded facts and checks can make merge eligible",
          state == "ELIGIBLE")

    disabled = copy.deepcopy(active)
    disabled["actions"]["draft_pull_request"] = False
    state, reasons = decision(disabled, facts())
    check("disabled action is denied rather than held", state == "DENY")

    malformed = copy.deepcopy(pol)
    malformed["surprise"] = True
    check("unknown policy field is rejected",
          any("unknown" in r for r in gate.policy_problems(malformed)))

    vacuous = copy.deepcopy(pol)
    vacuous["bounds"]["max_files_changed"] = 0
    check("vacuous numeric bound is rejected",
          gate.policy_problems(vacuous) != [])

    overbroad = copy.deepcopy(pol)
    overbroad["bounds"]["max_files_changed"] = 10000
    check("v0.1 rejects an accidentally unbounded envelope",
          gate.policy_problems(overbroad) != [])

    self_grant = copy.deepcopy(pol)
    self_grant["actions"]["release"] = True
    check("v0.1 cannot be configured to release",
          gate.policy_problems(self_grant) != [])

    unprotected = copy.deepcopy(pol)
    unprotected["protected_paths"].remove(".github/")
    check("policy cannot omit its workflow protection",
          gate.policy_problems(unprotected) != [])

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        run("git", "init", "-q", cwd=tmp)
        run("git", "config", "user.email", "test@example.invalid", cwd=tmp)
        run("git", "config", "user.name", "Autonomy Test", cwd=tmp)
        signed_policy = copy.deepcopy(pol)
        raw, now = signature_fixture(tmp, signed_policy)
        base = commit(tmp, "bootstrap trust root")
        old_root = gate.ROOT
        gate.ROOT = tmp
        try:
            errors = gate.verify_authorization(
                signed_policy, raw, base, "merge", now)
            check("exact policy has a valid detached standing authorization",
                  errors == [])

            errors = gate.verify_authorization(
                signed_policy, raw + b" ", base, "merge", now)
            check("one-byte policy drift invalidates authorization",
                  any("exact policy" in r for r in errors))

            errors = gate.verify_authorization(
                signed_policy, raw, base, "release", now)
            check("signature cannot grant an unlisted action",
                  any("does not grant" in r for r in errors))

            auth_path = tmp / signed_policy["authorization"]["authorization_path"]
            auth = json.loads(auth_path.read_text())
            auth["signature"] = base64.b64encode(b"x" * 64).decode()
            auth_path.write_text(json.dumps(auth) + "\n")
            tampered = commit(tmp, "tamper authorization")
            errors = gate.verify_authorization(
                signed_policy, raw, tampered, "merge", now)
            check("tampered signature is rejected", errors != [])
        finally:
            gate.ROOT = old_root

    checks, errors = gate.load_checks(None, "a" * 40)
    check("missing check packet is named, not treated as green",
          checks == {} and errors)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "checks.json"
        p.write_text(json.dumps({
            "head_sha": "b" * 40,
            "checks": {"test": "success", "cross-repo": "success"},
        }))
        checks, errors = gate.load_checks(p, "a" * 40)
        check("stale check packet cannot authorize a new head",
              checks == {} and errors)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "checks.json"
        p.write_text("[]\n")
        checks, errors = gate.load_checks(p, "a" * 40)
        check("non-object check packet is rejected without crashing",
              checks == {} and errors)

    real_git_diff_countervectors(pol)

    print(f"AUTONOMY GATE: ALL PASS ({passed}/{passed})")
    return 0


def real_git_diff_countervectors(pol):
    """Drive diff_facts through actual git plumbing, not synthetic DiffFacts.

    The other cases build DiffFacts by hand, so they never exercise the mode,
    symlink, status and ancestry parsing where a real regression would hide. A
    stranger who edited diff_facts and broke executable-mode detection would see
    every synthetic case still pass; this one would go red.
    """
    active = copy.deepcopy(pol)
    active["status"] = "active"

    def init(tmp):
        run("git", "init", "-q", cwd=tmp)
        run("git", "config", "user.email", "test@example.invalid", cwd=tmp)
        run("git", "config", "user.name", "Autonomy Test", cwd=tmp)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        init(tmp)
        (tmp / "README.md").write_text("base\n")
        base = commit(tmp, "base")
        docs = tmp / "docs"
        docs.mkdir()
        (docs / "normal.md").write_text("hi\n")
        (docs / "with space.md").write_text("sp\n")
        script = docs / "run.sh"
        script.write_text("#!/bin/sh\n")
        os.chmod(script, 0o755)
        head = commit(tmp, "candidate Co-Authored-By: Claude")
        old_root = gate.ROOT
        gate.ROOT = tmp
        try:
            facts = gate.diff_facts(base, head, pol)
            check("real git: an executable-mode file in the lane is detected",
                  facts.unsupported_mode_paths == ["docs/run.sh"])
            check("real git: a path containing a space is parsed intact",
                  "docs/with space.md" in facts.paths)
            state, reasons = decision(active, facts)
            check("real git: an executable mode forces DENY", state == "DENY"
                  and any("ordinary non-executable" in r for r in reasons))

            os.symlink("normal.md", docs / "link.md")
            head2 = commit(tmp, "symlink Co-Authored-By: Claude")
            facts2 = gate.diff_facts(base, head2, pol)
            check("real git: a symlink is detected from its git mode",
                  "docs/link.md" in facts2.symlink_paths)
            state2, _ = decision(active, facts2)
            check("real git: a symlink forces DENY", state2 == "DENY")
        finally:
            gate.ROOT = old_root

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        init(tmp)
        (tmp / "a").write_text("1\n")
        unrelated_base = commit(tmp, "base")
        run("git", "checkout", "-q", "--orphan", "detached", cwd=tmp)
        (tmp / "b").write_text("2\n")
        unrelated_head = commit(tmp, "orphan Co-Authored-By: Claude")
        old_root = gate.ROOT
        gate.ROOT = tmp
        try:
            rejected = False
            try:
                gate.diff_facts(unrelated_base, unrelated_head, pol)
            except ValueError:
                rejected = True
            check("real git: a head that does not descend base is rejected",
                  rejected)
        finally:
            gate.ROOT = old_root


if __name__ == "__main__":
    raise SystemExit(main())
