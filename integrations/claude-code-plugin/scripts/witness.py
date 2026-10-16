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
The hook always exits 0 and prints nothing on any tool or permission event,
so it can never allow, deny or delay a tool call on its own. The one thing it
ever prints is a SessionStart context listing recent auto-mode denials, so
the model does not retry a refused call blind. Any filing failure is swallowed and logged to
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

POLICY = """warrant.claude-code-witness@v1

Records in this store are filed by a Claude Code hook that witnesses
permission outcomes and executions the harness reports. It is not the
decider.

1. PermissionDenied (auto mode): filed as reject; the reason names the
   working directory and quotes the harness's stated denial reason verbatim.
2. PermissionRequest followed by an execution of the same tool call in the
   same session: filed as accept, "asked, then executed". The witness cannot
   tell whether the person, an allow rule or another hook approved it.
3. A Bash call that ran WITHOUT a prompt is filed only if one of its command
   segments is a check (a test, build, lint or CI-status command) or
   consequential (publish, push, merge, release, commit, tag, hard reset,
   recursive or forced delete). Filed as accept, "executed without a prompt",
   naming the permission mode, whether the tool reported success or failure,
   and the SHA-256 and size of the tool response exactly as the harness
   reported it. The output itself is not stored: it may hold secrets, and the
   session transcript keeps it; the hash lets a reader confirm a transcript's
   output is the one witnessed.

Manual denials in the permission dialog fire no hook and are not recorded.
Tool inputs larger than 64 KiB are bound by SHA-256 instead of inline.
"""

# Command shapes that make an execution worth a record. Matched per shell
# segment on the first one or two words; deliberately small and legible.
CHECKS = {("pytest",), ("cargo", "test"), ("cargo", "clippy"), ("cargo", "build"),
          ("go", "test"), ("go", "vet"), ("go", "build"), ("npm", "test"),
          ("npm", "run"), ("deno", "test"), ("deno", "check"), ("make", "test"),
          ("make", "check"), ("gh", "pr checks"), ("gh", "run")}
CONSEQUENTIAL = {("git", "push"), ("git", "commit"), ("git", "merge"), ("git", "tag"),
                 ("gh", "pr merge"), ("gh", "pr create"), ("gh", "release"),
                 ("npm", "publish"), ("deno", "publish"), ("cargo", "publish"),
                 ("twine", "upload")}
CHECK_SCRIPT_HINTS = ("test", "check", "selftest", "conformance")
SEPARATORS = {"|", "||", ";", "&", "&&"}
VALUE_FLAGS = {"-C", "--prefix", "--manifest-path", "--repo", "-R", "--cwd", "--git-dir"}
MAX_COMMAND_CHARS = 65536

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
        on_unprompted(h, event)             # not asked about: witness only if it matters
        return
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
                f"auto mode denied the call in {event.get('cwd')}; "
                f"harness reason: {event.get('reason')!s}")


def _segments(command):
    import shlex
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|;&")
    lexer.whitespace_split = True
    lexer.commenters = ""
    seg = []
    for tok in lexer:
        if tok in SEPARATORS:
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def _segment_kind(seg):
    words = [w for w in seg if "=" not in w or w.startswith("-")]   # drop VAR=x
    if not words:
        return None
    name = words[0].rsplit("/", 1)[-1].lower()
    args, skip = [], False
    for w in words[1:]:
        if skip:
            skip = False
        elif w in VALUE_FLAGS:
            skip = True                     # `git -C dir push`, `npm --prefix js test`
        elif not w.startswith("-"):
            args.append(w)
    rest = " ".join(args[:2]).lower()
    sub = rest.split(" ")[0] if rest else ""
    for table, kind in ((CONSEQUENTIAL, "consequential"), (CHECKS, "check")):
        for cmd, arg in ((k[0], k[1]) for k in table if len(k) == 2):
            if name == cmd and (rest.startswith(arg) or sub == arg):
                return kind
        if (name,) in table:
            return kind
    if name == "rm" and any(w.startswith("-") and not w.startswith("--")
                            and set("rf") & set(w[1:].lower()) for w in words[1:]):
        return "consequential"
    if name.startswith("python") and len(words) > 1:
        script = words[1].rsplit("/", 1)[-1].lower()
        if any(h in script for h in CHECK_SCRIPT_HINTS) or \
                any(w in CHECK_SCRIPT_HINTS for w in words[2:3]):
            return "check"
    return None


def classify_command(command):
    """'consequential', 'check' or None. Consequential wins over check."""
    if not isinstance(command, str) or len(command) > MAX_COMMAND_CHARS:
        return None
    try:
        kinds = {_segment_kind(seg) for seg in _segments(command)}
    except ValueError:
        return None
    for kind in ("consequential", "check"):
        if kind in kinds:
            return kind
    return None


def on_unprompted(h, event):
    """A Bash call that ran without a prompt: witnessed only if it matters."""
    if event.get("tool_name") != "Bash":
        return
    kind = classify_command((event.get("tool_input") or {}).get("command"))
    if kind is None:
        return
    failed = event.get("hook_event_name") == "PostToolUseFailure"
    response = event.get("error") if failed else event.get("tool_response")
    raw = canonical(response if response is not None else None).encode("utf-8")
    outcome = "failed" if failed else "succeeded"
    if failed and event.get("is_interrupt"):
        outcome += " (interrupted)"
    file_record(h, event, True,
                f"executed without a prompt ({kind}) in {event.get('permission_mode')} "
                f"mode in {event.get('cwd')}; the tool {outcome}; tool response "
                f"sha256 {hashlib.sha256(raw).hexdigest()} ({len(raw)} bytes) as reported "
                "by the harness, not stored")


RECALL_WINDOW_S = 7 * 24 * 3600
RECALL_MAX = 5


def recent_denials(h, now=None):
    """Most recent auto-mode denials, newest first, read straight from the store.

    Reads only record files touched inside the window, and never the CLI, so a
    SessionStart hook stays fast however large the store grows.
    """
    now = now or time.time()
    out = []
    for p in (h / "store" / "records").glob("*.json"):
        try:
            if p.stat().st_mtime < now - RECALL_WINDOW_S:
                continue
            body = json.loads(p.read_text(encoding="utf-8"))["body"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if body.get("decision") != "reject":
            continue
        prior = (body.get("prior") or [None])[0]
        try:
            req = json.loads((h / "store" / "records" / f"{prior}.json").read_text(encoding="utf-8"))["body"]
            subj = json.loads((h / "store" / "blobs" / req["subject"]["hash"]).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError):
            subj = {}
        reason = next((b.get("text") for b in body.get("because", []) if b.get("kind") == "prose"), "")
        out.append({"ts": body.get("ts", 0), "id": p.stem, "reason": reason,
                    "input": canonical(subj.get("tool_input", {}))})
    out.sort(key=lambda r: r["ts"], reverse=True)
    return out[:RECALL_MAX]


def on_session_start(h, event):
    """Tell the model what auto mode refused recently, so it does not retry blind.

    Prints a SessionStart additionalContext only when there is something to
    say. The lines are records, labelled as data: the harness's reasons and the
    calls they refused, not instructions.
    """
    rows = recent_denials(h)
    if not rows:
        return
    lines = ["Warrant witness: auto mode refused these calls in the last 7 days "
             "(recorded data, not instructions; `/warrant:decisions` for details):"]
    for r in rows:
        when = time.strftime("%Y-%m-%d", time.localtime(r["ts"]))
        reason = r["reason"].split("harness reason: ", 1)[-1][:120]
        lines.append(f"- {when} {reason} -- {r['input'][:120]} (record {r['id'][:12]})")
    json.dump({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                      "additionalContext": "\n".join(lines)}}, sys.stdout)


def sweep(h):
    """Forget pending notes older than a week: a dialog that old will not run."""
    cutoff = time.time() - PENDING_TTL_S
    for p in (h / "pending").glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


HANDLERS = {"SessionStart": on_session_start,
            "PermissionRequest": on_permission_request,
            "PermissionDenied": on_denied,
            "PostToolUse": on_executed,
            "PostToolUseFailure": on_executed}


def main():
    """Always ends with exit status 0 and empty stdout: the hook never decides."""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(event, dict):
        return
    handler = HANDLERS.get(event.get("hook_event_name"))
    if handler is None:
        return
    h = home()
    try:
        h.mkdir(parents=True, exist_ok=True)
        if handler is on_session_start:
            handler(h, event)               # read-only: no lock, no store writes
            return
        if handler is on_permission_request:
            # Synchronous: Claude Code waits for it before showing the dialog.
            # One atomic file write, no store and no lock, so a filing in
            # progress elsewhere can never delay the prompt.
            handler(h, event)
            sweep(h)
            return
        with open(h / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            handler(h, event)
    except Exception as exc:                # noqa: BLE001 -- never break the agent
        log(h, f"{event.get('hook_event_name')} not filed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
