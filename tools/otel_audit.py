#!/usr/bin/env python3
"""Join exported agent telemetry to a warrant store, and say where they disagree.

WHY
---
Telemetry and a warrant are two records of the same moment, made by different
parties. The harness's OpenTelemetry export says *that* a tool call was accepted
or rejected and by which mechanism; it is best-effort, may be sampled away, is
unsigned, carries no reason, and drops refusals from tool spans by design. A
warrant filed at the harness's permission hook says *who* sanctioned the call,
*under which pinned rule*, signed, and with a reason that may re-execute.

Neither record is evidence about the other until something reads both. This is
that reader. It writes nothing to telemetry and needs no OTel package: the join
key is the `tool_use_id` the harness already hands its hooks and already writes
into its own events, bound into the warrant's signed subject by
`warrant_approval.tool_call_subject`. The design and its limits are in
docs/telemetry-correlation.md.

WHAT IT CLASSIFIES (one class per tool_use_id)
    store-invalid      a record bound to this call fails verification
    misbound           a `warrant.sanction` pointer names a record that does
                       not bind this call, or claims a decision it does not hold
    contradiction      telemetry and the signed record disagree, two signed
                       records disagree, or a signed refusal was executed
    unwarranted        the harness says a hook decided; no sanction is filed
    telemetry-missing  a signed sanction; the harness reported nothing about it
    corroborated       both records exist and agree
    not-hook           decided by configuration or a person; no warrant expected

The first four exit 1. `telemetry-missing` does not: sampling and lost batches
make it routine, and it is exactly the case a warrant exists to cover.

WHAT IT DOES NOT DO
-------------------
It does not make telemetry trustworthy, and a `corroborated` row does not prove
the harness enforced anything -- it proves two parties' records agree and one is
signed. It never runs a `cmd@v1` reason. Same-host keys are one custody; this
tool inherits that limit from the store it reads.

TELEMETRY IT READS (a mapping table, and a standing obligation)
---------------------------------------------------------------
OTLP/JSON as the OpenTelemetry Collector's file exporter writes it: one export
request per line (or one JSON document), with `resourceLogs` and/or
`resourceSpans`. Field names below were read from vendor documentation on
2026-10-15 and are beta surfaces there; change them HERE, nowhere else.

USAGE
    python3 tools/otel_audit.py audit --store .warrants --telemetry export.jsonl [--json]
    python3 tools/otel_audit.py selftest
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REPORT = "warrant.otel-audit@v0"          # non-normative, like warrant.why@v0
SUBJECT_TYPE = "warrant.tool-call@v0"     # integrations/approval/warrant_approval.py

# -- the mapping table -----------------------------------------------------
# Claude Code log events (code.claude.com/docs/en/monitoring-usage):
#   tool_decision: tool_use_id, decision accept|reject, source config|hook|user_*
#   tool_result:   tool_use_id; "not emitted if the tool call was rejected"
# Claude API / SDK tool spans (platform.claude.com/docs/en/api/opentelemetry/spans):
#   gen_ai.operation.name = execute_tool, gen_ai.tool.call.id = the tool_use id;
#   no span when the use is denied.
# Claude Code's own `claude_code.tool*` spans are NOT read: their attributes
# were not verified, and a tool span exists there even for a blocked call.
DECISION_EVENT = "tool_decision"
RESULT_EVENT = "tool_result"
POINTER_EVENT = "warrant.sanction"        # emitted by our hook, optional
SPAN_TOOL_ID = "gen_ai.tool.call.id"
SPAN_OPERATION = ("gen_ai.operation.name", "execute_tool")

FAILING = ("store-invalid", "misbound", "contradiction", "unwarranted")
CLASSES = FAILING + ("telemetry-missing", "corroborated", "not-hook")


# -- reading telemetry -----------------------------------------------------
def _any_value(v):
    """OTLP/JSON AnyValue -> a Python value (ints arrive as strings)."""
    if not isinstance(v, dict):
        return v
    for k in ("stringValue", "boolValue", "doubleValue"):
        if k in v:
            return v[k]
    if "intValue" in v:
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return v["intValue"]
    if "arrayValue" in v:
        return [_any_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return _attrs(v["kvlistValue"].get("values", []))
    return None


def _attrs(kvs):
    out = {}
    for kv in kvs or []:
        if isinstance(kv, dict) and isinstance(kv.get("key"), str):
            out[kv["key"]] = _any_value(kv.get("value"))
    return out


def _event_name(rec, attrs):
    for cand in (attrs.get("event.name"), rec.get("eventName"),
                 _any_value(rec.get("body"))):
        if isinstance(cand, str) and cand:
            return cand[len("claude_code."):] if cand.startswith("claude_code.") else cand
    return None


def load_telemetry(paths):
    """Return {tool_use_id: facts} from OTLP/JSON files. Unknown records are skipped."""
    docs = []
    for p in paths:
        text = Path(p).read_text(encoding="utf-8")
        try:
            docs.append(json.loads(text))
        except ValueError:
            for n, line in enumerate(text.splitlines(), 1):
                if line.strip():
                    try:
                        docs.append(json.loads(line))
                    except ValueError as ex:
                        raise SystemExit(f"{p}:{n}: not JSON ({ex})")
    calls = {}

    def call(tid):
        return calls.setdefault(tid, {"decisions": [], "executed": False,
                                      "pointers": []})

    for doc in docs:
        for rl in doc.get("resourceLogs", []) if isinstance(doc, dict) else []:
            for sl in rl.get("scopeLogs", []):
                for rec in sl.get("logRecords", []):
                    a = _attrs(rec.get("attributes"))
                    name = _event_name(rec, a)
                    if name == DECISION_EVENT and isinstance(a.get("tool_use_id"), str):
                        call(a["tool_use_id"])["decisions"].append(
                            {"decision": a.get("decision"), "source": a.get("source")})
                    elif name == RESULT_EVENT and isinstance(a.get("tool_use_id"), str):
                        call(a["tool_use_id"])["executed"] = True
                    elif name == POINTER_EVENT and isinstance(a.get("warrant.tool_use_id"), str):
                        call(a["warrant.tool_use_id"])["pointers"].append(
                            {"warrant_id": a.get("warrant.id"),
                             "decision": a.get("warrant.decision")})
        for rs in doc.get("resourceSpans", []) if isinstance(doc, dict) else []:
            for ss in rs.get("scopeSpans", []):
                for span in ss.get("spans", []):
                    a = _attrs(span.get("attributes"))
                    tid = a.get(SPAN_TOOL_ID)
                    if isinstance(tid, str) and a.get(SPAN_OPERATION[0]) == SPAN_OPERATION[1]:
                        call(tid)["executed"] = True
    return calls


# -- reading the store -------------------------------------------------------
def _cli(explicit=None):
    cand = explicit or os.environ.get("WARRANT_CLI")
    if cand:
        return [sys.executable, str(cand)] if str(cand).endswith(".py") else [str(cand)]
    local = ROOT / "impl" / "warrant.py"
    if local.is_file():
        return [sys.executable, str(local)]
    found = shutil.which("warrant")
    if found:
        return [found]
    raise SystemExit("no warrant CLI: set WARRANT_CLI or install `warrant`")


def _verify(cli, store, settlement_args):
    r = subprocess.run(cli + ["--store", str(store), "verify", "--store-mode",
                              "--json"] + settlement_args,
                       capture_output=True, text=True)
    line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    try:
        return json.loads(line)
    except ValueError:
        raise SystemExit(f"verify produced no report: {r.stderr.strip()[:300]}")


def _reason_status(cli, store, body):
    """How the sanction's reason can be checked: reruns | fails | unverified | cmd-unrun | prose-only."""
    checks = [r for r in body.get("because", [])
              if isinstance(r, dict) and r.get("kind") == "check"]
    if not checks:
        return "prose-only"
    statuses = []
    for r in checks:
        if r.get("runtime") != "ski@v1":
            statuses.append("cmd-unrun")
            continue
        p = subprocess.run(cli + ["--store", str(store), "check", str(r.get("check"))],
                           capture_output=True, text=True)
        got = (p.stdout.split() or [""])[0]
        if got not in ("pass", "fail"):
            statuses.append("unverified")
        else:
            statuses.append("reruns" if got == r.get("verdict") else "fails")
    for s in ("fails", "unverified", "cmd-unrun"):
        if s in statuses:
            return s
    return "reruns"


def load_store(store, cli, settlement_args, verify=None):
    """Return (report, {tool_use_id: [bound records]})."""
    store = Path(store)
    report = (verify or _verify)(cli, store, settlement_args)
    bad = {f["subject"] for f in report.get("findings", []) if f.get("level") == "ERR"}
    bound = {}
    for p in sorted((store / "records").glob("*.json")):
        wid = p.stem
        try:
            body = json.loads(p.read_text(encoding="utf-8")).get("body", {})
            h = body["subject"]["hash"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue                     # verify already reports it, store-wide
        if not (isinstance(h, str) and HEX64.match(h)):
            continue
        try:
            raw = (store / "blobs" / h).read_bytes()
        except OSError:
            continue
        intact = hashlib.sha256(raw).hexdigest() == h   # recomputed, not trusted
        try:
            subj = json.loads(raw)
        except ValueError:
            subj = None
        if not isinstance(subj, dict) or subj.get("type") != SUBJECT_TYPE:
            continue
        tid = subj.get("tool_use_id")
        if not isinstance(tid, str):
            continue
        rec = {"id": wid, "decision": body.get("decision"),
               "valid": intact and wid not in bad,
               "problem": None if intact else "subject blob does not hash to its name"}
        if wid in bad:
            rec["problem"] = "; ".join(f["message"] for f in report["findings"]
                                       if f.get("subject") == wid and f.get("level") == "ERR")
        if rec["decision"] in ("accept", "reject"):
            rec["reason"] = _reason_status(cli, store, body) if rec["valid"] else None
        bound.setdefault(tid, []).append(rec)
    return report, bound


# -- the join ----------------------------------------------------------------
def classify(tid, tel, records):
    tel = tel or {"decisions": [], "executed": False, "pointers": []}
    records = records or []
    sanctions = [r for r in records if r["decision"] in ("accept", "reject")]
    valid = [r for r in sanctions if r["valid"]]
    notes = []

    def row(cls):
        return {"tool_use_id": tid, "class": cls,
                "telemetry": tel, "warrant": records, "notes": notes}

    broken = [r for r in records if not r["valid"]]
    if broken:
        notes += [f"{r['id'][:12]}: {r['problem']}" for r in broken]
        return row("store-invalid")

    by_id = {r["id"]: r for r in valid}
    for ptr in tel["pointers"]:
        target = by_id.get(ptr["warrant_id"])
        if target is None:
            notes.append(f"pointer names {str(ptr['warrant_id'])[:12]}, "
                         "which is not a sanction bound to this call")
        elif ptr["decision"] is not None and ptr["decision"] != target["decision"]:
            notes.append(f"pointer claims {ptr['decision']}, "
                         f"the signed record holds {target['decision']}")
    if notes:
        return row("misbound")

    signed = {r["decision"] for r in valid}
    if len(signed) > 1:
        notes.append("two signed sanctions disagree about one call")
        return row("contradiction")
    harness = [d for d in tel["decisions"] if d.get("decision") in ("accept", "reject")]

    if signed:
        (decision,) = signed
        for d in harness:
            if d["decision"] != decision:
                notes.append(f"telemetry says {d['decision']} (source {d.get('source')}), "
                             f"the signed sanction says {decision}")
        if decision == "reject" and tel["executed"]:
            notes.append("signed refusal, but telemetry shows the tool ran")
        if notes:
            return row("contradiction")
        for r in valid:
            notes.append(f"{r['id'][:12]} {r['decision']}, reason {r.get('reason')}")
        if not harness and not tel["executed"]:
            notes.append("no harness telemetry for this call (sampled, lost, "
                         "or a refusal the trace does not record)")
            return row("telemetry-missing")
        sources = {d.get("source") for d in harness}
        if harness and "hook" not in sources:
            notes.append(f"telemetry attributes the decision to {sorted(map(str, sources))}")
        if decision == "reject" and not tel["executed"]:
            notes.append("no tool_result/span: telemetry records refusals only as a decision")
        return row("corroborated")

    if any(d.get("source") == "hook" for d in harness):
        if any(r["decision"] == "propose" for r in records):
            notes.append("a request was filed, its sanction was not")
        return row("unwarranted")
    return row("not-hook")


def audit(store, telemetry_paths, cli=None, settlement_args=(), verify=None):
    cli = _cli(cli)
    calls = load_telemetry(telemetry_paths)
    report, bound = load_store(store, cli, list(settlement_args), verify)
    rows = [classify(t, calls.get(t), bound.get(t))
            for t in sorted(set(calls) | set(bound))]
    counts = {c: sum(1 for r in rows if r["class"] == c) for c in CLASSES}
    return {"report": REPORT, "store_ok": bool(report.get("ok")),
            "store_errors": report.get("errors"), "grade": report.get("grade"),
            "counts": counts, "rows": rows,
            "ok": bool(report.get("ok")) and not any(counts[c] for c in FAILING)}


def print_text(res):
    for r in res["rows"]:
        print(f"{r['class']:<18} {r['tool_use_id']}")
        for n in r["notes"]:
            print(f"{'':<18}   {n}")
    shown = ", ".join(f"{c} {n}" for c, n in res["counts"].items() if n)
    print(f"\nstore: {'ok' if res['store_ok'] else 'FAILS VERIFICATION'} "
          f"({res['store_errors']} errors, {res['grade']} grade); {shown or 'no calls'}")


# -- fixtures (selftest and demos/otel-vs-warrant) ----------------------------
def log_record(name, **attrs):
    def val(v):
        if isinstance(v, bool):
            return {"boolValue": v}
        if isinstance(v, int):
            return {"intValue": str(v)}
        return {"stringValue": str(v)}
    return {"timeUnixNano": "1792100000000000000",
            "body": {"stringValue": name},
            "attributes": [{"key": "event.name", "value": {"stringValue": name}}]
            + [{"key": k, "value": val(v)} for k, v in attrs.items()]}


def export_request(logs=(), spans=()):
    doc = {}
    if logs:
        doc["resourceLogs"] = [{"resource": {"attributes": []},
                                "scopeLogs": [{"scope": {"name": "fixture"},
                                               "logRecords": list(logs)}]}]
    if spans:
        doc["resourceSpans"] = [{"resource": {"attributes": []},
                                 "scopeSpans": [{"scope": {"name": "fixture"},
                                                 "spans": list(spans)}]}]
    return doc


def tool_span(tool_use_id):
    """An API/SDK execute_tool span: the shape of a tool call that ran."""
    return {"name": "anthropic.custom_tool_use deploy", "kind": 1,
            "attributes": [{"key": "gen_ai.operation.name",
                            "value": {"stringValue": "execute_tool"}},
                           {"key": SPAN_TOOL_ID, "value": {"stringValue": tool_use_id}}]}


# -- selftest ----------------------------------------------------------------
def selftest():
    sys.path.insert(0, str(ROOT / "integrations" / "approval"))
    sys.path.insert(0, str(ROOT / "impl"))
    from warrant_approval import Boundary, tool_call_subject     # noqa: E402
    import warrant as W                                          # noqa: E402
    import ski_policy as sp                                      # noqa: E402

    failed = []

    def chk(cond, label, detail=""):
        print(f"  {'ok  ' if cond else 'FAIL'}  {label}")
        if not cond:
            failed.append(label)
            if detail:
                print(f"          {detail}")

    tmp = Path(tempfile.mkdtemp(prefix="warrant-otel-audit-"))
    try:
        store, keys = tmp / "store", tmp / "keys"
        env = dict(os.environ, WARRANT_APPROVAL_STORE=str(store),
                   WARRANT_APPROVAL_KEYS=str(keys))
        hook = ROOT / "integrations" / "approval" / "examples" / "pretooluse_hook.py"

        def run_hook(tid, command):
            r = subprocess.run([sys.executable, str(hook)], env=env, text=True,
                               capture_output=True,
                               input=json.dumps({"hook_event_name": "PreToolUse",
                                                 "tool_name": "Bash",
                                                 "tool_input": {"command": command},
                                                 "tool_use_id": tid,
                                                 "session_id": "sess_fixture"}))
            return json.loads(r.stdout)["hookSpecificOutput"]

        # A: refused by the real hook binding, prose reason.
        a = run_hook("toolu_A", "rm -rf /srv/data")
        # C: benign; the hook defers and files nothing.
        c = run_hook("toolu_C", "ls -la")
        chk(a["permissionDecision"] == "deny" and c["permissionDecision"] == "defer",
            "fixture: the real hook denies A and defers C")
        a_id = re.search(r"\[warrant ([0-9a-f]{12})\]", a["permissionDecisionReason"])
        a_id = next(p.stem for p in (store / "records").glob("*.json")
                    if a_id and p.stem.startswith(a_id.group(1)))

        # B: allowed by a permission policy whose reason is a COMPILED ski@v1
        # check -- the one reason telemetry can never carry, re-executed below.
        b = Boundary(store=store, policy_text="deploys need a rollback target\n",
                     requester_key=keys / "agent.key", decider_key=keys / "policy.key")
        compiled = sp.compile_check(sp.And(sp.Fact("has_rollback", True),
                                           sp.Not(sp.Fact("touches_prod_db", False))),
                                    W.Store(str(store)).put_blob)
        granted = b.record_approval(
            tool_call_subject("Bash", {"command": "deploy --rollback 8e1a"},
                              "toolu_B", "sess_fixture"),
            requester="agent:sess_fixture", decider="harness:permission-policy",
            decision_reasons=["allowed: rollback target present"],
            check=compiled.blob, runtime="ski@v1", verdict="pass", allowed=True)
        b_id = granted["decision"]

        base_logs = {
            "A": [log_record("claude_code.tool_decision", tool_use_id="toolu_A",
                       decision="reject", source="hook", tool_name="Bash"),
                  log_record(POINTER_EVENT, **{"warrant.id": a_id,
                                         "warrant.tool_use_id": "toolu_A",
                                         "warrant.decision": "reject"})],
            "B": [log_record("tool_decision", tool_use_id="toolu_B", decision="accept",
                       source="hook", tool_name="Bash"),
                  log_record("tool_result", tool_use_id="toolu_B", success="true",
                       decision_source="hook", duration_ms=12)],
            "C": [log_record("tool_decision", tool_use_id="toolu_C", decision="accept",
                       source="config", tool_name="Bash"),
                  log_record("tool_result", tool_use_id="toolu_C", success="true")],
            "D": [log_record("tool_decision", tool_use_id="toolu_D", decision="reject",
                       source="hook", tool_name="Bash")],
        }

        def run(logs, spans=(), as_lines=True, verify=None):
            f = tmp / "export.jsonl"
            if as_lines:
                # The collector's file exporter: one request per line, and real
                # files have blank lines and split batches.
                f.write_text("\n".join(json.dumps(export_request([x])) for x in logs) + "\n\n"
                             + (json.dumps(export_request(spans=spans)) + "\n" if spans else ""))
            else:
                f.write_text(json.dumps(export_request(logs, spans)))
            return audit(store, [f], verify=verify)

        def classes(res):
            return {r["tool_use_id"]: r["class"] for r in res["rows"]}

        def flat(d, drop=()):
            return [x for k, v in sorted(d.items()) if k not in drop for x in v]

        base = run(flat(base_logs))
        bc = classes(base)
        want = {"toolu_A": "corroborated", "toolu_B": "corroborated",
                "toolu_C": "not-hook", "toolu_D": "unwarranted"}
        chk(bc == want, "baseline: A, B corroborated; C not-hook; D unwarranted", str(bc))
        rows = {r["tool_use_id"]: r for r in base["rows"]}
        chk(any("reason reruns" in n for n in rows["toolu_B"]["notes"]),
            "B's ski@v1 reason re-executed to its claimed verdict",
            str(rows["toolu_B"]["notes"]))
        chk(any("reason prose-only" in n for n in rows["toolu_A"]["notes"]),
            "A's prose reason is reported as prose-only, not as re-run")
        chk(base["store_ok"] and base["ok"] is False,
            "store verifies; the report fails because D is unwarranted")
        chk(classes(run(flat(base_logs), as_lines=False)) == bc,
            "one JSON document and JSON lines give the same table")

        def control(label, target, expect, logs, spans=()):
            got = classes(run(logs, spans))
            others = {k: v for k, v in got.items() if k != target}
            base_others = {k: v for k, v in bc.items() if k != target}
            chk(got.get(target) == expect and others == base_others,
                f"control: {label} -> {target} {expect}, every other row unchanged",
                str(got))

        flipped = dict(base_logs, A=[log_record("tool_decision", tool_use_id="toolu_A",
                                          decision="accept", source="hook")]
                       + base_logs["A"][1:])
        control("telemetry edited reject->accept", "toolu_A", "contradiction",
                flat(flipped))
        ran = dict(base_logs, A=base_logs["A"] + [log_record("tool_result", tool_use_id="toolu_A",
                                                       success="true")])
        control("a signed refusal that telemetry shows executing", "toolu_A",
                "contradiction", flat(ran))
        control("telemetry for B lost (sampling, dropped batch)", "toolu_B",
                "telemetry-missing", flat(base_logs, drop=("B",)))
        relabel = dict(base_logs, A=base_logs["A"][:1]
                       + [log_record(POINTER_EVENT, **{"warrant.id": b_id,
                                                 "warrant.tool_use_id": "toolu_A",
                                                 "warrant.decision": "accept"})])
        control("pointer relabelled to another valid record", "toolu_A", "misbound",
                flat(relabel))
        hint = dict(base_logs, A=base_logs["A"][:1]
                    + [log_record(POINTER_EVENT, **{"warrant.id": a_id,
                                              "warrant.tool_use_id": "toolu_A",
                                              "warrant.decision": "accept"})])
        control("pointer hint disagrees with the signed record", "toolu_A", "misbound",
                flat(hint))
        # The API/SDK shape: a tool span exists only for a call that ran, so the
        # refusal is simply absent from the trace -- the warrant still holds it.
        # B is given ONLY its span (no Claude Code decision event), so B stays
        # corroborated only if an execute_tool span is actually read.
        control("API-shaped trace: denied call has no span", "toolu_A",
                "telemetry-missing", flat(base_logs, drop=("A", "B")),
                spans=[tool_span("toolu_B")])

        # Tampering with the evidence itself.
        rec = store / "records" / f"{a_id}.json"
        original = rec.read_text()
        doc = json.loads(original)
        doc["body"]["decision"] = "accept"
        rec.write_text(json.dumps(doc))
        res = run(flat(base_logs))
        chk(classes(res)["toolu_A"] == "store-invalid" and not res["store_ok"],
            "control: sanction rewritten reject->accept -> A store-invalid, store fails")
        rec.write_text(original)
        blob = store / "blobs" / json.loads(original)["body"]["subject"]["hash"]
        braw = blob.read_bytes()
        blob.write_bytes(braw.replace(b"toolu_A", b"toolu_X"))
        res = run(flat(base_logs))
        got = classes(res)
        # The edited blob now NAMES toolu_X. Read without recomputing its hash it
        # would bind both records to toolu_X as valid sanctions -- a forged join.
        # A keeps its telemetry pointer, which now names a record bound
        # elsewhere: misbound, not quietly unwarranted.
        chk(got.get("toolu_X") == "store-invalid" and got.get("toolu_A") == "misbound",
            "control: subject blob edited to rebind another call -> the forged "
            "binding is store-invalid, A's pointer is misbound", str(got))
        # Defence in depth: the join key is read from a blob, so the auditor
        # recomputes that blob's hash itself rather than lean on `verify` alone.
        # Prove it with a verifier that reports everything ok.
        got = classes(run(flat(base_logs), verify=lambda *a: {
            "ok": True, "errors": 0, "grade": "base", "findings": []}))
        chk(got.get("toolu_X") == "store-invalid",
            "control: with a verifier that says ok, the auditor still refuses the "
            "rebound blob (it recomputes the hash itself)", str(got))
        blob.write_bytes(braw)
        chk(classes(run(flat(base_logs))) == bc, "restoring the bytes restores the table")

        before = set((store / "records").glob("*.json"))
        b.record_approval(tool_call_subject("Bash", {"command": "rm -rf /srv/data"},
                                            "toolu_A", "sess_other"),
                          requester="agent:sess_other", decider="human:override",
                          decision_reasons=["allowed after all"], allowed=True)
        control("a second signed sanction allows what the first refused", "toolu_A",
                "contradiction", flat(base_logs))
        for p in set((store / "records").glob("*.json")) - before:
            p.unlink()

        # The reason column, against reasons no honest CLI would file (`accept`
        # refuses a check whose verdict does not reproduce), so the classifier
        # cannot be tested through filing -- only directly.
        cli = _cli()

        def reason(**r):
            return _reason_status(cli, store, {"because": [dict(kind="check", **r)]})
        chk(reason(check=compiled.blob, runtime="ski@v1", verdict="pass") == "reruns",
            "reason: a ski@v1 check that reproduces its verdict -> reruns")
        chk(reason(check=compiled.blob, runtime="ski@v1", verdict="fail") == "fails",
            "reason: a ski@v1 check claiming the wrong verdict -> fails")
        chk(reason(check="0" * 64, runtime="ski@v1", verdict="pass") == "unverified",
            "reason: a ski@v1 check whose blob is absent -> unverified")
        chk(reason(check=compiled.blob, runtime="cmd@v1", verdict="pass") == "cmd-unrun",
            "reason: a cmd@v1 check is never run -> cmd-unrun")

        # The command line, end to end: exit status follows the failing classes.
        f = tmp / "ok.jsonl"
        f.write_text(json.dumps(export_request(flat(base_logs, drop=("D",)))))
        p = subprocess.run([sys.executable, __file__, "audit", "--store", str(store),
                            "--telemetry", str(f), "--json"],
                           capture_output=True, text=True)
        out = json.loads(p.stdout) if p.stdout.strip() else {}
        chk(p.returncode == 0 and out.get("report") == REPORT and out.get("ok") is True,
            "CLI: no failing class -> exit 0 and a warrant.otel-audit@v0 report",
            p.stderr[-300:])
        f.write_text(json.dumps(export_request(flat(base_logs))))
        p = subprocess.run([sys.executable, __file__, "audit", "--store", str(store),
                            "--telemetry", str(f)], capture_output=True, text=True)
        chk(p.returncode == 1 and "unwarranted" in p.stdout,
            "CLI: an unwarranted hook decision -> exit 1, named in the text")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nOTEL-AUDIT: " + ("ALL PASS" if not failed else f"{len(failed)} FAILED"))
    return not failed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="join a telemetry export to a store")
    a.add_argument("--store", required=True)
    a.add_argument("--telemetry", required=True, action="append",
                   help="OTLP/JSON export (file exporter output); repeatable")
    a.add_argument("--json", action="store_true")
    a.add_argument("--settlement", action="store_true")
    a.add_argument("--trust-config")
    sub.add_parser("selftest")
    args = ap.parse_args()
    if args.cmd == "selftest":
        sys.exit(0 if selftest() else 1)
    extra = (["--settlement"] if args.settlement else []) + (
        ["--trust-config", args.trust_config] if args.trust_config else [])
    res = audit(args.store, args.telemetry, settlement_args=extra)
    if args.json:
        print(json.dumps(res, sort_keys=True))
    else:
        print_text(res)
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
