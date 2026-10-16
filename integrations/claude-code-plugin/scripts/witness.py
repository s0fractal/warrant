#!/usr/bin/env python3
"""Witness Claude Code permission outcomes into a local warrant store.

WHAT IT RECORDS
---------------
Only outcomes the harness itself reports, never the agent's account of them:

  PermissionDenied     auto mode refused a tool call. Filed as a `reject` whose
                       reason quotes the harness's `reason` verbatim.
  PermissionRequest    Claude Code was about to ask about a tool call. Nothing
  then PostToolUse /   is filed yet; a pending note is kept. If a call with the
  PostToolUseFailure   same session, tool and input then runs, an `accept` is
                       filed: "asked, then executed".

A call that ran without being asked about files nothing: volume is not
provenance, and the store is meant to hold the decisions, not the traffic.

WHAT IT CANNOT SEE
------------------
Claude Code fires no hook when a person denies a permission dialog, so a manual
refusal leaves only a pending note that never resolves. `decisions.py` reports
those as "asked, no execution observed" -- denied, interrupted or still open,
the witness cannot tell which -- rather than guessing.

"Executed" also does not say WHO allowed it: the person in the dialog, an allow
rule or another hook. The reason says exactly that.

WHO SIGNS
---------
This hook signs, with one local key, as `claude-code-witness`. It is not the
decider and does not pretend to be: the decider is named in the reason, and the
record reports `sanction_independent: false` because one custody signed both
the request and the outcome. A store of these proves what this machine's
harness reported and that nobody edited it since; it does not prove the
classifier was right or that the person read the dialog.

NEVER IN THE WAY
----------------
The hook prints nothing and always exits 0, so it can never allow, deny or
delay a tool call on its own. Any filing failure is swallowed and logged to
`witness.log`. A recorder that can break the agent is a recorder that gets
uninstalled.

CONFIGURE
    WARRANT_CC_HOME   store, key and pending notes (default ~/.warrant/claude-code)
    WARRANT_CLI       the warrant CLI (default: `warrant` on PATH,
                      from `pipx install warrant-verify`)
"""
import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

POLICY = """warrant.claude-code-witness@v0

Records in this store are filed by a Claude Code hook that witnesses
permission outcomes the harness reports. It is not the decider.

1. PermissionDenied (auto mode): filed as reject; the reason quotes the
   harness's stated denial reason verbatim.
2. PermissionRequest followed by an execution of the same tool call in the
   same session: filed as accept, "asked, then executed". The witness cannot
   tell whether the person, an allow rule or another hook approved it.

Manual denials in the permission dialog fire no hook and are not recorded.
Tool inputs larger than 64 KiB are bound by SHA-256 instead of inline.
"""

ACTOR = "claude-code-witness"
MAX_INPUT_BYTES = 65536
PENDING_TTL_S = 7 * 24 * 3600


def home():
    return Path(os.environ.get("WARRANT_CC_HOME",
                               Path.home() / ".warrant" / "claude-code"))


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def bounded_input(tool_input):
    """The tool input as bound into the signed subject, capped in size."""
    text = canonical(tool_input if tool_input is not None else {})
    raw = text.encode("utf-8")
    if len(raw) <= MAX_INPUT_BYTES:
        return tool_input if tool_input is not None else {}
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "inline": False}


def call_key(event):
    """Same session, same tool, same input -> same key. No tool_use_id: the
    PermissionRequest event does not carry one."""
    doc = {"session_id": event.get("session_id"), "tool_name": event.get("tool_name"),
           "tool_input": event.get("tool_input")}
    return hashlib.sha256(canonical(doc).encode("utf-8")).hexdigest()


def log(h, msg):
    try:
        with open(h / "witness.log", "a", encoding="utf-8") as f:
            f.write(f"{int(time.time())} {msg}\n")
    except OSError:
        pass


def file_record(h, event, allowed, reason):
    from warrant_approval import Boundary, tool_call_subject
    key = h / "keys" / "witness.key"
    b = Boundary(store=h / "store", policy_text=POLICY,
                 requester_key=key, decider_key=key)
    subject = tool_call_subject(event.get("tool_name"),
                                bounded_input(event.get("tool_input")),
                                event.get("tool_use_id"), event.get("session_id"),
                                os.environ.get("TRACEPARENT"))
    summary = f"{event.get('tool_name')}: {canonical(event.get('tool_input') or {})}"
    req = b.record_request(subject, requester=ACTOR,
                           note=f"requested: {summary[:120]}")
    dec = b.record_decision(req, allowed, decider=ACTOR, reasons=[reason])
    log(h, f"filed {'accept' if allowed else 'reject'} {dec}")
    return dec


def on_permission_request(h, event):
    pending = h / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    note = {"asked_at": int(time.time()), "session_id": event.get("session_id"),
            "tool_name": event.get("tool_name"), "cwd": event.get("cwd"),
            "summary": canonical(event.get("tool_input") or {})[:200]}
    target = pending / f"{call_key(event)}.json"
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(canonical(note), encoding="utf-8")
    os.replace(tmp, target)


def on_executed(h, event):
    note_path = h / "pending" / f"{call_key(event)}.json"
    try:
        note = json.loads(note_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return                              # not asked about: nothing to witness
    note_path.unlink(missing_ok=True)
    reason = (f"permission was requested at {note.get('asked_at')}; the call then "
              "executed (approved in the dialog, by an allow rule or by another "
              "hook -- the witness cannot tell which)")
    if event.get("hook_event_name") == "PostToolUseFailure":
        reason += "; the tool reported a failure"
        if event.get("is_interrupt"):
            reason += " (interrupted)"
    file_record(h, event, True, reason)


def on_denied(h, event):
    file_record(h, event, False,
                f"auto mode denied the call; harness reason: {event.get('reason')!s}")


def sweep(h):
    """Forget pending notes older than a week: a dialog that old will not run."""
    cutoff = time.time() - PENDING_TTL_S
    for p in (h / "pending").glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


HANDLERS = {"PermissionRequest": on_permission_request,
            "PermissionDenied": on_denied,
            "PostToolUse": on_executed,
            "PostToolUseFailure": on_executed}


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    handler = HANDLERS.get(event.get("hook_event_name"))
    if handler is None:
        return 0
    h = home()
    try:
        h.mkdir(parents=True, exist_ok=True)
        if handler is on_permission_request:
            # Synchronous: Claude Code waits for it before showing the dialog.
            # One atomic file write, no store and no lock, so a filing in
            # progress elsewhere can never delay the prompt.
            handler(h, event)
            sweep(h)
            return 0
        with open(h / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            handler(h, event)
    except Exception as exc:                # noqa: BLE001 -- never break the agent
        log(h, f"{event.get('hook_event_name')} not filed: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
