#!/usr/bin/env python3
"""Fail-closed capability gate for agent-operated repository actions.

The candidate revision is data.  The evaluator, policy and trust root are read
from a caller-selected base revision, so a pull request cannot enlarge the
authority under which that same pull request is judged.

This tool does not merge, push, publish or change repository settings.  It emits
one content-addressable decision packet.  A separate workflow may act on an
ELIGIBLE packet only after a standing authorization is active.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = "policies/agent-autonomy-v0.1.json"
SAFE_REV = re.compile(r"^[A-Za-z0-9_./\-~^@{}]+$")
ACTIONS = {
    "branch_push", "draft_pull_request", "pull_request_update",
    "ready_for_review", "merge", "release", "governance_adoption",
    "branch_protection_admin", "history_rewrite",
}
DECISIONS = {"ELIGIBLE", "HOLD", "DENY"}
NEVER_AUTONOMOUS_V01 = {
    "release", "governance_adoption", "branch_protection_admin",
    "history_rewrite",
}
REQUIRED_PROTECTED = {
    ".github/", ".warrant/", ".warrants/", "AGENTS.md", "SECURITY.md",
    "SPEC.md", "policies/", "schemas/", "trust/", "tools/", "tests/",
    "impl/", "impl-go/", "impl-rs/", "integrations/", "proofs/",
    "conformance/", "conformance-skeletons/",
}


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=check,
                          capture_output=True, text=False)


def resolve(rev: str) -> str:
    if rev.startswith("-") or not SAFE_REV.fullmatch(rev):
        raise ValueError(f"refusing unsafe revision {rev!r}")
    run = git("rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}",
              check=False)
    if run.returncode:
        raise ValueError(f"{rev!r} does not name a commit")
    return run.stdout.decode().strip()


def blob_at(rev: str, path: str) -> bytes:
    if path.startswith("/") or ".." in Path(path).parts:
        raise ValueError(f"refusing unsafe repository path {path!r}")
    run = git("show", f"{rev}:{path}", check=False)
    if run.returncode:
        raise ValueError(f"{path} is absent from policy revision {rev[:12]}")
    return run.stdout


def exact_keys(value, required: set[str], where: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where} must be an object"]
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    out = []
    if missing:
        out.append(f"{where} missing keys: {', '.join(missing)}")
    if extra:
        out.append(f"{where} unknown keys: {', '.join(extra)}")
    return out


def policy_problems(policy) -> list[str]:
    top = {
        "agent_autonomy_policy", "status", "repository", "base_branch",
        "purpose", "actions", "bounds", "autonomous_path_prefixes",
        "protected_paths", "required_checks", "checks_required_for",
        "provenance", "authorization", "notes",
    }
    problems = exact_keys(policy, top, "policy")
    if problems:
        return problems
    if policy["agent_autonomy_policy"] != "0.1":
        problems.append("unsupported agent_autonomy_policy")
    if policy["status"] not in {"draft", "active", "revoked"}:
        problems.append("status must be draft, active, or revoked")
    if policy["repository"] != "s0fractal/warrant":
        problems.append("v0.1 is scoped exactly to s0fractal/warrant")
    if policy["base_branch"] != "master":
        problems.append("v0.1 only supports the master base branch")

    problems += exact_keys(policy["actions"], ACTIONS, "actions")
    if isinstance(policy["actions"], dict):
        for name, value in policy["actions"].items():
            if type(value) is not bool:
                problems.append(f"actions.{name} must be boolean")
        enabled_danger = sorted(name for name in NEVER_AUTONOMOUS_V01
                                if policy["actions"].get(name))
        if enabled_danger:
            problems.append("v0.1 can never grant: " + ", ".join(enabled_danger))

    bound_keys = {
        "max_commits", "max_files_changed", "max_lines_added",
        "max_lines_removed", "allow_deletions", "allow_binary",
        "allow_symlinks", "allow_submodules", "allow_merge_commits",
    }
    problems += exact_keys(policy["bounds"], bound_keys, "bounds")
    if isinstance(policy["bounds"], dict):
        for name in ("max_commits", "max_files_changed", "max_lines_added",
                     "max_lines_removed"):
            value = policy["bounds"].get(name)
            if type(value) is not int or value < 1:
                problems.append(f"bounds.{name} must be an integer >= 1")
        ceilings = {"max_commits": 12, "max_files_changed": 20,
                    "max_lines_added": 2000, "max_lines_removed": 1000}
        for name, ceiling in ceilings.items():
            value = policy["bounds"].get(name)
            if type(value) is int and value > ceiling:
                problems.append(f"bounds.{name} exceeds v0.1 ceiling {ceiling}")
        for name in bound_keys - {"max_commits", "max_files_changed",
                                 "max_lines_added", "max_lines_removed"}:
            if type(policy["bounds"].get(name)) is not bool:
                problems.append(f"bounds.{name} must be boolean")

    for name in ("autonomous_path_prefixes", "protected_paths",
                 "required_checks", "checks_required_for"):
        values = policy[name]
        if not isinstance(values, list) or not values:
            problems.append(f"{name} must be a non-empty list")
        elif any(not isinstance(v, str) or not v.strip() for v in values):
            problems.append(f"{name} contains a blank or non-string value")
        elif len(values) != len(set(values)):
            problems.append(f"{name} contains duplicates")
    if isinstance(policy["checks_required_for"], list):
        unknown = sorted(set(policy["checks_required_for"]) - ACTIONS)
        if unknown:
            problems.append(f"checks_required_for has unknown actions: {unknown}")
    prefixes = policy.get("autonomous_path_prefixes", [])
    if isinstance(prefixes, list) and any(
            not p.endswith("/") or p.startswith("/") or ".." in Path(p).parts
            for p in prefixes if isinstance(p, str)):
        problems.append("autonomous_path_prefixes must be safe directory prefixes")
    protected = policy.get("protected_paths", [])
    if isinstance(protected, list):
        missing_protected = sorted(REQUIRED_PROTECTED - set(protected))
        if missing_protected:
            problems.append("protected_paths omits mandatory anchors: " +
                            ", ".join(missing_protected))
        overlaps = sorted(p for p in prefixes if any(
            p.startswith(rule) if rule.endswith("/") else p == rule
            for rule in protected))
        if overlaps:
            problems.append("autonomous path overlaps protected path: " +
                            ", ".join(overlaps))
    if not {"test", "cross-repo"} <= set(policy.get("required_checks", [])):
        problems.append("required_checks must include test and cross-repo")
    if not {"ready_for_review", "merge"} <= set(
            policy.get("checks_required_for", [])):
        problems.append("ready_for_review and merge must require checks")

    provenance_keys = {
        "require_agent_trailer", "agent_markers", "forbidden_authority_markers"
    }
    problems += exact_keys(policy["provenance"], provenance_keys, "provenance")
    if isinstance(policy["provenance"], dict):
        if type(policy["provenance"].get("require_agent_trailer")) is not bool:
            problems.append("provenance.require_agent_trailer must be boolean")
        for name in ("agent_markers", "forbidden_authority_markers"):
            values = policy["provenance"].get(name)
            if not isinstance(values, list) or not values or any(
                    not isinstance(v, str) or not v for v in values):
                problems.append(f"provenance.{name} must be a non-empty string list")

    auth_keys = {
        "required_for_all_actions", "format", "policy_sha256_required",
        "detached_signature_required", "authorization_path", "trusted_key_path"
    }
    problems += exact_keys(policy["authorization"], auth_keys, "authorization")
    if isinstance(policy["authorization"], dict):
        for name in ("required_for_all_actions", "policy_sha256_required",
                     "detached_signature_required"):
            if policy["authorization"].get(name) is not True:
                problems.append(f"authorization.{name} must be true in v0.1")
        if policy["authorization"].get("format") != \
                "agent-autonomy-authorization@v0.1":
            problems.append("unsupported authorization format")
    if policy.get("status") != "active" and policy.get("actions", {}).get("merge"):
        problems.append("merge cannot be true unless policy status is active")
    return problems


def matches(path: str, rules: list[str]) -> bool:
    return any(path.startswith(rule) if rule.endswith("/") else path == rule
               for rule in rules)


@dataclass
class DiffFacts:
    paths: list[str]
    statuses: dict[str, str]
    lines_added: int
    lines_removed: int
    binary_paths: list[str]
    symlink_paths: list[str]
    submodule_paths: list[str]
    unsupported_mode_paths: list[str]
    commits: int
    merge_commits: int
    agent_provenance: bool
    authority_markers: list[str]

    def packet(self) -> dict:
        return {
            "paths": self.paths,
            "statuses": self.statuses,
            "files_changed": len(self.paths),
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "binary_paths": self.binary_paths,
            "symlink_paths": self.symlink_paths,
            "submodule_paths": self.submodule_paths,
            "unsupported_mode_paths": self.unsupported_mode_paths,
            "commits": self.commits,
            "merge_commits": self.merge_commits,
            "agent_provenance": self.agent_provenance,
            "authority_markers": self.authority_markers,
        }


def diff_facts(base: str, head: str, policy: dict) -> DiffFacts:
    if git("merge-base", "--is-ancestor", base, head, check=False).returncode:
        raise ValueError("head is not a descendant of base")

    raw = git("diff", "--name-status", "--no-renames", "-z",
              f"{base}...{head}").stdout.split(b"\0")
    entries = [part.decode("utf-8", "strict") for part in raw if part]
    if len(entries) % 2:
        raise ValueError("unreadable git name-status output")
    statuses = {entries[i + 1]: entries[i] for i in range(0, len(entries), 2)}
    paths = sorted(statuses)

    added = removed = 0
    binary = []
    for entry in git("diff", "--numstat", "--no-renames", "-z",
                     f"{base}...{head}").stdout.split(b"\0"):
        if not entry:
            continue
        fields = entry.decode("utf-8", "strict").split("\t", 2)
        if len(fields) != 3:
            raise ValueError("unreadable git numstat output")
        plus, minus, path = fields
        if plus == "-" or minus == "-":
            binary.append(path)
        else:
            added += int(plus)
            removed += int(minus)

    symlinks, submodules, unsupported_modes = [], [], []
    for path in paths:
        if statuses[path] == "D":
            continue
        tree = git("ls-tree", head, "--", path).stdout.decode().strip()
        if not tree:
            raise ValueError(f"changed path absent from head tree: {path}")
        mode = tree.split(None, 1)[0]
        if mode == "120000":
            symlinks.append(path)
        elif mode == "160000":
            submodules.append(path)
        elif mode != "100644":
            unsupported_modes.append(path)

    messages = git("log", "--format=%B%x00", f"{base}..{head}").stdout.decode(
        "utf-8", "replace")
    provenance = policy["provenance"]
    agent = any(marker.lower() in messages.lower()
                for marker in provenance["agent_markers"])
    false_markers = sorted(marker for marker in provenance["forbidden_authority_markers"]
                           if marker.lower() in messages.lower())
    commits = int(git("rev-list", "--count", f"{base}..{head}").stdout)
    merges = int(git("rev-list", "--count", "--merges",
                     f"{base}..{head}").stdout)
    return DiffFacts(paths, statuses, added, removed, sorted(binary),
                     sorted(symlinks), sorted(submodules),
                     sorted(unsupported_modes), commits, merges, agent,
                     false_markers)


def load_checks(path: Path | None, head: str) -> tuple[dict[str, str], list[str]]:
    if path is None:
        return {}, ["required check evidence was not supplied"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"check evidence is unreadable: {exc}"]
    if not isinstance(doc, dict) or set(doc) != {"head_sha", "checks"} or \
            doc.get("head_sha") != head:
        return {}, ["check evidence must contain only checks and the exact head_sha"]
    checks = doc.get("checks")
    if not isinstance(checks, dict) or any(
            not isinstance(k, str) or v not in {"success", "failure", "pending"}
            for k, v in checks.items()):
        return {}, ["checks must map names to success, failure, or pending"]
    return checks, []


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(dt.timezone.utc)


def verify_authorization(policy: dict, policy_bytes: bytes, revision: str,
                         action: str, now: dt.datetime) -> list[str]:
    auth_cfg = policy["authorization"]
    try:
        raw = blob_at(revision, auth_cfg["authorization_path"])
        key_raw = blob_at(revision, auth_cfg["trusted_key_path"]).strip()
        auth = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        return [f"standing authorization unavailable: {exc}"]

    keys = {
        "authorization_format", "repository", "base_branch", "policy_sha256",
        "actions", "not_before", "not_after", "signature",
    }
    problems = exact_keys(auth, keys, "standing authorization")
    if problems:
        return problems
    if auth["authorization_format"] != auth_cfg["format"]:
        problems.append("standing authorization format mismatch")
    if auth["repository"] != policy["repository"] or \
            auth["base_branch"] != policy["base_branch"]:
        problems.append("standing authorization scope mismatch")
    if auth["policy_sha256"] != sha256(policy_bytes):
        problems.append("standing authorization does not bind exact policy bytes")
    if not isinstance(auth["actions"], list) or not auth["actions"] or \
            not set(auth["actions"]) <= ACTIONS:
        problems.append("standing authorization actions are invalid")
    elif action not in auth["actions"]:
        problems.append(f"standing authorization does not grant {action}")
    try:
        start, end = parse_time(auth["not_before"]), parse_time(auth["not_after"])
        if not start <= now <= end:
            problems.append("standing authorization is not currently valid")
        if end <= start or end - start > dt.timedelta(days=366):
            problems.append("standing authorization validity must be 1..366 days")
    except (TypeError, ValueError):
        problems.append("standing authorization timestamps are invalid")
    if problems:
        return problems

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        prefix = b"ed25519:"
        if not key_raw.startswith(prefix):
            raise ValueError("trusted key must be ed25519:<base64 raw 32-byte key>")
        key = base64.b64decode(key_raw[len(prefix):], validate=True)
        signature = base64.b64decode(auth["signature"], validate=True)
        if len(key) != 32 or len(signature) != 64:
            raise ValueError("wrong Ed25519 key or signature length")
        signed = dict(auth)
        del signed["signature"]
        Ed25519PublicKey.from_public_bytes(key).verify(
            signature, canonical(signed).encode("utf-8"))
    except (ImportError, ValueError, TypeError) as exc:
        return [f"standing authorization signature unavailable or invalid: {exc}"]
    except Exception:
        return ["standing authorization signature invalid"]
    return []


def decide(policy: dict, facts: DiffFacts, action: str, checks: dict[str, str],
           check_errors: list[str], authorization_errors: list[str]) -> tuple[str, list[str]]:
    deny, hold = [], []
    if not policy["actions"].get(action, False):
        deny.append(f"action {action} is disabled")

    protected = [p for p in facts.paths if matches(p, policy["protected_paths"])]
    outside = [p for p in facts.paths
               if not matches(p, policy["autonomous_path_prefixes"])]
    if protected:
        deny.append("protected paths changed: " + ", ".join(protected))
    if outside:
        deny.append("paths outside autonomous lane: " + ", ".join(outside))
    if not facts.paths:
        deny.append("empty change")

    bounds = policy["bounds"]
    for actual, name in ((facts.commits, "max_commits"),
                         (len(facts.paths), "max_files_changed"),
                         (facts.lines_added, "max_lines_added"),
                         (facts.lines_removed, "max_lines_removed")):
        if actual > bounds[name]:
            deny.append(f"{name} exceeded: {actual} > {bounds[name]}")
    if not bounds["allow_deletions"]:
        deleted = sorted(p for p, status in facts.statuses.items() if status == "D")
        if deleted:
            deny.append("deletions are disabled: " + ", ".join(deleted))
    if facts.binary_paths and not bounds["allow_binary"]:
        deny.append("binary changes are disabled: " + ", ".join(facts.binary_paths))
    if facts.symlink_paths and not bounds["allow_symlinks"]:
        deny.append("symlinks are disabled: " + ", ".join(facts.symlink_paths))
    if facts.submodule_paths and not bounds["allow_submodules"]:
        deny.append("submodules are disabled: " + ", ".join(facts.submodule_paths))
    if facts.unsupported_mode_paths:
        deny.append("only ordinary non-executable files are allowed: " +
                    ", ".join(facts.unsupported_mode_paths))
    unsupported_status = sorted(
        path for path, status in facts.statuses.items() if status not in {"A", "M", "D"})
    if unsupported_status:
        deny.append("unsupported Git status: " + ", ".join(unsupported_status))
    if facts.merge_commits and not bounds["allow_merge_commits"]:
        deny.append(f"merge commits are disabled: {facts.merge_commits}")
    if policy["provenance"]["require_agent_trailer"] and not facts.agent_provenance:
        deny.append("no declared agent provenance marker in candidate commits")
    if facts.authority_markers:
        deny.append("commit asserts forbidden authority: " +
                    ", ".join(facts.authority_markers))

    if action in policy["checks_required_for"]:
        hold.extend(check_errors)
        for name in policy["required_checks"]:
            status = checks.get(name)
            if status is None:
                hold.append(f"required check absent: {name}")
            elif status != "success":
                hold.append(f"required check {name} is {status}")

    if policy["status"] != "active":
        hold.append(f"policy status is {policy['status']}; standing authority is inactive")
    hold.extend(authorization_errors)

    if deny:
        return "DENY", sorted(set(deny + hold))
    if hold:
        return "HOLD", sorted(set(hold))
    return "ELIGIBLE", []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--policy-from", required=True)
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS))
    parser.add_argument("--checks-file", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    try:
        base, head, policy_rev = map(resolve,
                                     (args.base, args.head, args.policy_from))
        if base != policy_rev:
            raise ValueError("policy revision must equal the exact base commit")
        policy_bytes = blob_at(policy_rev, POLICY_PATH)
        policy = json.loads(policy_bytes)
        problems = policy_problems(policy)
        if problems:
            raise ValueError("invalid policy: " + "; ".join(problems))
        facts = diff_facts(base, head, policy)
        checks, check_errors = load_checks(args.checks_file, head)
        auth_errors = verify_authorization(
            policy, policy_bytes, policy_rev, args.action,
            dt.datetime.now(dt.timezone.utc))
        decision, reasons = decide(policy, facts, args.action, checks,
                                   check_errors, auth_errors)
        packet = {
            "autonomy_decision": "0.1",
            "decision": decision,
            "action": args.action,
            "repository": policy["repository"],
            "base_sha": base,
            "head_sha": head,
            "policy_from": policy_rev,
            "policy_sha256": sha256(policy_bytes),
            "facts": facts.packet(),
            "checks": checks,
            "reasons": reasons,
        }
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError,
            UnicodeDecodeError, subprocess.CalledProcessError) as exc:
        packet = {
            "autonomy_decision": "0.1",
            "decision": "DENY",
            "action": args.action,
            "repository": None,
            "base_sha": None,
            "head_sha": None,
            "policy_from": None,
            "policy_sha256": None,
            "facts": None,
            "checks": {},
            "reasons": [str(exc)],
        }

    assert packet["decision"] in DECISIONS
    rendered = canonical(packet) + "\n"
    if args.out:
        target = args.out.resolve()
        if not target.is_relative_to(ROOT.resolve()):
            print("refusing output outside repository", file=sys.stderr)
            return 2
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if packet["decision"] == "ELIGIBLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
