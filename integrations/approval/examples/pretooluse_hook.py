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
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "integrations" / "approval"))
from warrant_approval import ApprovalError, Boundary            # noqa: E402

POLICY = """Tool calls that can destroy data outside the workspace require a
human sanction. A refusal must name the pattern that matched.
"""

# Deliberately small and legible: the point is the recording boundary, not a
# clever rule engine. The first version used several `.*` regular expressions
# over agent-controlled text. Besides being easy to evade, those expressions
# could backtrack super-linearly on a huge command and turn a permission hook
# into an agent outage. Tokenize once, bound the input, and inspect only the
# small command shapes this example claims to recognize.
MAX_COMMAND_CHARS = 65536
SHELL_SEPARATORS = {"|", "||", ";", "&", "&&"}


def _command_name(token):
    return token.rsplit("/", 1)[-1].lower()


def _tokens(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|;&")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _segment(tokens, start):
    out = []
    for value in tokens[start:]:
        if value in SHELL_SEPARATORS:
            break
        out.append(value)
    return out


def _rm_is_destructive(args):
    for option in args:
        if option == "--":
            return False
        if option in {"--recursive", "--force"}:
            return True
        if option.startswith("-") and not option.startswith("--"):
            flags = option.lstrip("-").lower()
            if "r" in flags or "f" in flags:
                return True
    return False


def _first_separator(tokens, start):
    for index, value in enumerate(tokens[start:], start=start):
        if value in SHELL_SEPARATORS:
            return index
    return None


def _curl_pipes_to_shell(tokens, start):
    separator = _first_separator(tokens, start + 1)
    if separator is None or tokens[separator] != "|":
        return False
    target = [_command_name(value) for value in _segment(tokens, separator + 1)]
    if not target:
        return False
    if target[0] in {"sh", "bash"}:
        return True
    return target[0] == "sudo" and len(target) > 1 and target[1] in {"sh", "bash"}


def _danger(tokens, command):
    compact = "".join(command.split())
    if compact.startswith(":(){") and "};:" in compact:
        return "fork bomb"

    for i, token in enumerate(tokens):
        name = _command_name(token)
        tail = _segment(tokens, i + 1)
        if name == "rm" and _rm_is_destructive(tail):
            return "recursive/forced delete"
        if name == "mkfs" or name.startswith("mkfs."):
            return "raw device write"
        if name == "dd" and any(value.startswith("of=/dev/") for value in tail):
            return "raw device write"
        if name == "curl" and _curl_pipes_to_shell(tokens, i):
            return "pipe-to-shell"
    return None


def classify(tool_name, tool_input):
    """Return (decision, reason). Pure function -- the part worth testing."""
    if tool_name != "Bash":
        return "defer", "not a shell command"
    command = (tool_input or {}).get("command", "")
    if not isinstance(command, str):
        return "deny", "blocked: malformed shell command"
    if len(command) > MAX_COMMAND_CHARS:
        return "deny", "blocked: command exceeds review limit"
    try:
        why = _danger(_tokens(command), command)
    except ValueError:
        return "deny", "blocked: malformed shell command"
    if why:
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
        return

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


if __name__ == "__main__":
    sys.exit(main())
