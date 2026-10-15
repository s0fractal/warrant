#!/usr/bin/env python3
"""What a trace can't tell you, and a warrant can: one agent session, six questions.

An agent session makes three tool calls through Claude Code's PreToolUse hook:
a destructive delete (refused), a directory listing (the hook has no opinion),
and a deploy (allowed by a permission policy whose rule is a compiled, re-runnable
check). Afterwards someone reviews the session from its OpenTelemetry export.

Each scene below changes ONE thing a real deployment can see happen -- an edited
export, a refusal the API trace never records, a dropped batch, a relabelled
pointer, edited evidence -- and shows what the trace alone says next to what the
auditor says once it also reads the warrant store. Then it asks the question a
trace cannot answer at all: *why* was the deploy allowed? -- and re-runs the
answer.

HONEST ABOUT ITS INPUTS: the refusal and the deferral go through the real hook
binding as a subprocess, and the store is real. The TELEMETRY IS SYNTHESISED from
the event shapes Claude Code and the Claude API document (read 2026-10-15), not
captured from a live session. The output says so too.

Every scene asserts its expected outcome; the script exits 1 if any differs, so
it cannot quietly turn into a story about code that no longer behaves this way.

RUN
    python3 demos/otel-vs-warrant/demo.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "integrations" / "approval"))
sys.path.insert(0, str(ROOT / "impl"))
import otel_audit as A                                        # noqa: E402
from warrant_approval import Boundary, tool_call_subject      # noqa: E402
import warrant as W                                           # noqa: E402
import ski_policy as sp                                       # noqa: E402

HOOK = ROOT / "integrations" / "approval" / "examples" / "pretooluse_hook.py"
CLI = [sys.executable, str(ROOT / "impl" / "warrant.py")]
RULE = "deploy allowed iff a rollback target exists and the prod database is untouched"
FAILED = []


def say(text=""):
    print(text)


def scene(title):
    say("\n" + "─" * 78)
    say(title)
    say("─" * 78)


def expect(row, want, what):
    got = row["class"] if row else "(no row)"
    mark = "ok  " if got == want else "FAIL"
    say(f"  {mark} auditor: {got}" + (f"   (expected {want})" if got != want else ""))
    for n in (row or {}).get("notes", []):
        say(f"         · {n}")
    if got != want:
        FAILED.append(what)


def trace_view(logs, spans, tid):
    """What a dashboard reading only the export shows for this call."""
    calls = A.load_telemetry([write_export(logs, spans)])
    c = calls.get(tid)
    if not c or (not c["decisions"] and not c["executed"]):
        return "nothing — no event, no span for this call"
    parts = [f"{d['decision']} (source {d['source']})" for d in c["decisions"]]
    if c["executed"]:
        parts.append("tool ran")
    return ", ".join(parts)


def write_export(logs, spans=()):
    write_export.n += 1
    f = TMP / f"export-{write_export.n}.jsonl"
    lines = [json.dumps(A.export_request([r])) for r in logs]
    if spans:
        lines.append(json.dumps(A.export_request(spans=spans)))
    f.write_text("\n".join(lines) + "\n")
    return f


write_export.n = 0


def audit_row(logs, tid, spans=()):
    res = A.audit(STORE, [write_export(logs, spans)])
    return next((r for r in res["rows"] if r["tool_use_id"] == tid), None), res


def main():
    global TMP, STORE
    TMP = Path(tempfile.mkdtemp(prefix="otel-vs-warrant-"))
    STORE, keys = TMP / "store", TMP / "keys"
    try:
        say("TELEMETRY IN THIS DEMO IS SYNTHESISED FROM DOCUMENTED EVENT SHAPES,")
        say("NOT CAPTURED FROM A LIVE SESSION. The store and the hook are real.")

        # -- the session ----------------------------------------------------
        env = dict(os.environ, WARRANT_APPROVAL_STORE=str(STORE),
                   WARRANT_APPROVAL_KEYS=str(keys))

        def hook(tid, command):
            r = subprocess.run([sys.executable, str(HOOK)], env=env, text=True,
                               capture_output=True,
                               input=json.dumps({"hook_event_name": "PreToolUse",
                                                 "tool_name": "Bash",
                                                 "tool_input": {"command": command},
                                                 "tool_use_id": tid,
                                                 "session_id": "sess_demo"}))
            return json.loads(r.stdout)["hookSpecificOutput"]

        rm = hook("toolu_rm", "rm -rf /srv/customer-data")
        ls = hook("toolu_ls", "ls -la")
        short = re.search(r"\[warrant ([0-9a-f]{12})\]", rm["permissionDecisionReason"])
        rm_id = next(p.stem for p in (STORE / "records").glob("*.json")
                     if short and p.stem.startswith(short.group(1)))

        policy = Boundary(store=STORE, policy_text=RULE + "\n",
                          requester_key=keys / "agent.key",
                          decider_key=keys / "policy.key")
        compiled = sp.compile_check(sp.And(sp.Fact("has_rollback_target", True),
                                           sp.Not(sp.Fact("touches_prod_db", False))),
                                    W.Store(str(STORE)).put_blob)
        deploy = policy.record_approval(
            tool_call_subject("Bash", {"command": "deploy web --rollback 8e1a"},
                              "toolu_deploy", "sess_demo"),
            requester="agent:sess_demo", decider="harness:permission-policy",
            decision_reasons=[f"allowed: {RULE}"],
            check=compiled.blob, runtime="ski@v1", verdict="pass", allowed=True)

        scene("The session")
        say(f"  rm -rf /srv/customer-data   hook: {rm['permissionDecision']:<6} "
            f"warrant {rm_id[:12]} (prose reason)")
        say(f"  ls -la                      hook: {ls['permissionDecision']:<6} "
            "no record filed (the hook had no opinion)")
        say(f"  deploy web --rollback 8e1a  policy: allow  warrant "
            f"{deploy['decision'][:12]} (reason: compiled ski@v1 check)")
        say(f"  requester and decider hold different keys: {deploy['sanction_independent']}"
            " (both on this one host: one custody, reported, not solved)")

        L = A.log_record
        honest = {
            "rm": [L("claude_code.tool_decision", tool_use_id="toolu_rm",
                     decision="reject", source="hook", tool_name="Bash")],
            "ls": [L("claude_code.tool_decision", tool_use_id="toolu_ls",
                     decision="accept", source="config", tool_name="Bash"),
                   L("claude_code.tool_result", tool_use_id="toolu_ls", success="true")],
            "deploy": [L("claude_code.tool_decision", tool_use_id="toolu_deploy",
                         decision="accept", source="hook", tool_name="Bash"),
                       L("claude_code.tool_result", tool_use_id="toolu_deploy",
                         success="true")],
        }

        def logs(**override):
            d = dict(honest, **override)
            return [r for k in sorted(d) for r in d[k]]

        scene("0. The honest export, read together with the store")
        res = A.audit(STORE, [write_export(logs())])
        for r in res["rows"]:
            say(f"  {r['class']:<18} {r['tool_use_id']}")
        want = {"toolu_rm": "corroborated", "toolu_ls": "not-hook",
                "toolu_deploy": "corroborated"}
        if {r["tool_use_id"]: r["class"] for r in res["rows"]} != want:
            FAILED.append("baseline")
            say("  FAIL  baseline differs")

        scene("1. Someone edits the export: the refusal becomes an approval")
        edited = logs(rm=[L("claude_code.tool_decision", tool_use_id="toolu_rm",
                            decision="accept", source="hook", tool_name="Bash")])
        say(f"  trace alone says : {trace_view(edited, (), 'toolu_rm')}")
        say("                     (nothing in the export can tell you it was edited)")
        expect(audit_row(edited, "toolu_rm")[0], "contradiction", "edited export")

        scene("2. The refusal in an API-shaped trace")
        say("  The Claude API emits a tool span only for a tool use that runs; a denied")
        say("  use gets none. The export below has the deploy's span and nothing else.")
        api_spans = [A.tool_span("toolu_deploy")]
        say(f"  trace alone says : {trace_view([], api_spans, 'toolu_rm')}")
        expect(audit_row([], "toolu_rm", api_spans)[0], "telemetry-missing",
               "api refusal")
        expect(audit_row([], "toolu_deploy", api_spans)[0], "corroborated",
               "api deploy span")

        scene("3. A batch is sampled away (export is best-effort)")
        dropped = logs(deploy=[])
        say(f"  trace alone says : {trace_view(dropped, (), 'toolu_deploy')}")
        expect(audit_row(dropped, "toolu_deploy")[0], "telemetry-missing",
               "dropped batch")

        scene("4. A pointer in the export is relabelled to another valid record")
        relabelled = logs(rm=honest["rm"] + [L("warrant.sanction", **{
            "warrant.id": deploy["decision"], "warrant.tool_use_id": "toolu_rm",
            "warrant.decision": "accept"})])
        say("  trace alone says : the delete carries a warrant id, and that id verifies")
        expect(audit_row(relabelled, "toolu_rm")[0], "misbound", "relabelled pointer")

        scene("5. Someone edits the evidence itself: the refusal becomes an approval")
        rec = STORE / "records" / f"{rm_id}.json"
        original = rec.read_text()
        doc = json.loads(original)
        doc["body"]["decision"] = "accept"
        rec.write_text(json.dumps(doc))
        row, res = audit_row(logs(), "toolu_rm")
        say(f"  store verifies   : {res['store_ok']}")
        expect(row, "store-invalid", "edited evidence")
        rec.write_text(original)

        scene("6. Why was the deploy allowed?")
        say(f"  trace alone says : {trace_view(logs(), (), 'toolu_deploy')}"
            " — that a hook decided, never which rule or why")
        r = subprocess.run(CLI + ["--store", str(STORE), "check", compiled.blob],
                           capture_output=True, text=True)
        say(f"  the warrant says : rule pinned under policy {deploy['policy'][:12]}:")
        say(f"                     \"{RULE}\"")
        say(f"  re-run, here, now: warrant check {compiled.blob[:12]}…  ->  {r.stdout.strip()}")
        say("  what re-ran      : the rule over the facts recorded in the check")
        say("                     (has_rollback_target=true, touches_prod_db=false).")
        say("                     Re-execution proves the rule gives this verdict on")
        say("                     those facts; it does not prove the facts were true.")
        if not r.stdout.startswith("pass"):
            FAILED.append("ski re-run")
            say("  FAIL  the reason did not re-execute to pass")
        rm_row = audit_row(logs(), "toolu_rm")[0]
        say("  the refusal's reason, by contrast, is prose: "
            + ("reported prose-only" if any("prose-only" in n for n in rm_row["notes"])
               else "NOT reported prose-only"))
        if not any("prose-only" in n for n in rm_row["notes"]):
            FAILED.append("prose flag")

        scene("What this does not show")
        for line in (
                "· The telemetry is synthesised; field names are the documented ones, a",
                "  live export may differ (docs/telemetry-correlation.md, P4).",
                "· Both keys sit on this host: one custody. Separating them is deployment.",
                "· A corroborated row means two records agree and one is signed. It does",
                "  not prove the harness enforced anything, or that the prose is true.",
                "· No independent gate has reviewed any of this."):
            say(f"  {line}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

    say("\nOTEL-VS-WARRANT: " + ("ALL SCENES AS EXPECTED" if not FAILED
                                 else f"{len(FAILED)} UNEXPECTED: {', '.join(FAILED)}"))
    say("(telemetry synthesised from documentation, not captured)")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
