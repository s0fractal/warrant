#!/usr/bin/env python3
"""EXAMPLE: warrant at a harness tool-permission hook (Claude Code PreToolUse).

The second binding of the same framework-free boundary, and the reason the study
recommends building the boundary rather than a framework adapter. Compare it to
`langgraph_approval.py`: different world, different vendor, no shared code beyond
`warrant_approval.Boundary`, and **zero third-party imports here** -- because the
contract is a wire format, not a Python API.

THE CONTRACT
------------
Claude Code runs this as a subprocess before a tool call. It reads one JSON
object on stdin:

    {"hook_event_name": "PreToolUse", "tool_name": "Bash",
     "tool_input": {"command": "rm -rf /"}, "tool_use_id": "toolu_...",
     "session_id": "...", "cwd": "...", "permission_mode": "default"}

and writes one on stdout:

    {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": "..."}}

`permissionDecision` is one of allow | deny | ask | defer.
Documented at https://code.claude.com/docs/en/hooks (checked 2026-07-31).

WHY THIS BOUNDARY IS WORTH RECORDING
------------------------------------
The sanctioner is the harness, not the agent. The agent does not choose to file
this record and cannot suppress it -- which is exactly what the MCP server, where
the agent elects to call `warrant_file_decision`, can never give you. A store of
these is a log of what an independent policy allowed and refused, signed by a key
the agent does not hold if you configure it that way.

WHAT IT DOES NOT DO
-------------------
It records; the harness enforces. If this process dies the harness applies its
own default, and nothing here can make a refusal stick. A hook that blocks on a
slow signature is also a hook that hangs the agent, so filing is best-effort and
a filing failure DEFERS rather than denying: an audit trail must not become an
outage, and a recorder that fails closed on a tool call is a recorder that gets
uninstalled.

CONFIGURE
    // .claude/settings.json
    {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
      "command": "python3 /path/to/integrations/approval/examples/pretooluse_hook.py"}]}]}}

    WARRANT_APPROVAL_STORE  where to file      (default ~/.warrant-approvals)
    WARRANT_APPROVAL_KEYS   key directory      (default alongside the store)

RUN THE TESTS
    python3 integrations/approval/examples/test_pretooluse_hook.py
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "integrations" / "approval"))
from warrant_approval import ApprovalError, Boundary            # noqa: E402

POLICY = """Tool calls that can destroy data outside the workspace require a
human sanction. A refusal must name the pattern that matched.
"""

# Deliberately small and legible: the point is the recording boundary, not a
# clever rule engine. A real deployment puts its own policy here -- or better,
# calls one and records what it answered.
DENY = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rf]", re.I), "recursive/forced delete"),
    (re.compile(r":\s*\(\s*\)\s*\{.*\}\s*;\s*:", re.S), "fork bomb"),
    (re.compile(r"\bmkfs\b|\bdd\s+.*of=/dev/", re.I), "raw device write"),
    (re.compile(r"\bcurl\b.*\|\s*(ba)?sh\b", re.I), "pipe-to-shell"),
]


def classify(tool_name, tool_input):
    """Return (decision, reason). Pure function -- the part worth testing."""
    if tool_name != "Bash":
        return "defer", "not a shell command"
    command = (tool_input or {}).get("command", "")
    for pattern, why in DENY:
        if pattern.search(command):
            return "deny", f"blocked: {why}"
    return "defer", "no rule matched"


def emit(decision, reason):
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason}}, sys.stdout)
    sys.stdout.write("\n")


def record(event, decision, reason):
    """File the request and the sanction. Returns ids, or None if unavailable.

    Never raises into the hook path: see the module docstring on why a recorder
    must not be able to take the agent down.
    """
    store = Path(os.environ.get("WARRANT_APPROVAL_STORE",
                                Path.home() / ".warrant-approvals"))
    keys = Path(os.environ.get("WARRANT_APPROVAL_KEYS", str(store.parent / "keys")))
    try:
        b = Boundary(store=store, policy_text=POLICY,
                     requester_key=keys / "agent.key",
                     decider_key=keys / "harness.key")
        action = (f"{event.get('tool_name')}: "
                  f"{json.dumps(event.get('tool_input') or {}, sort_keys=True)}")
        req = b.record_request(
            action, requester=f"agent:{event.get('session_id', 'unknown')[:12]}",
            reasons=[f"tool_use_id={event.get('tool_use_id', '?')}"])
        dec = b.record_decision(req, decision != "deny", decider="harness:pretooluse",
                                reasons=[reason])
        return {"request": req, "decision": dec,
                "independent": b.sanction_independent}
    except (ApprovalError, OSError, ValueError):
        return None


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        emit("defer", "hook received unparseable input")
        return 0

    decision, reason = classify(event.get("tool_name"),
                                event.get("tool_input"))

    # Only a real decision is worth a record. Filing a warrant for every deferred
    # tool call would bury the refusals in noise and make the store useless as
    # evidence -- volume is not provenance.
    if decision != "defer":
        filed = record(event, decision, reason)
        if filed:
            reason += f" [warrant {filed['decision'][:12]}]"

    emit(decision, reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
