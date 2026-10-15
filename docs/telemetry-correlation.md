# Warrant beside telemetry, not inside it

**Status: a design synthesis. Nothing here is built or adopted.** No independent
gate ran. It revisits Candidate 2 of [`integration-study.md`](integration-study.md)
("OpenTelemetry GenAI semantic conventions — declined") in light of two external
drafts that proposed an OTel bridge, and of vendor telemetry read on 2026-10-15.
Vendor facts below were **read from documentation, not executed**; each names
its page so a reader can re-check it, and each is a beta surface that can move.

## The question

Two drafts (one from Grok, one from Qwen, both given to this session by the
owner) proposed the same thing in different words: put a WarrantID on an
OpenTelemetry span, so an agent trace carries a cryptographic anchor, and let a
dashboard verify it in the browser with the WASM build that now exists in `web/`.

The aim is right: show, in the tools people already watch, what a warrant gives
that a trace cannot. The mechanism both drafts chose is the one the study
already declined, for a reason neither draft addresses. This document keeps the
aim, replaces the mechanism, and says what would be built.

## What the drafts got right, and what they got wrong

| Draft idea | Keep? | Why |
| --- | --- | --- |
| Pointer, not payload: the span carries an id, the record lives in a store (Grok §3.3) | **keep** | Telemetry is lossy and size-capped; a record must not depend on surviving export. |
| Opt-in, only for decisions that matter: refusals, side effects, overrides (Grok §3.2) | **keep** | Same rule the hook binding already enforces: a deferral files nothing ("volume is not provenance"). |
| Zero breakage of existing pipelines (Grok §2) | **keep** | Strengthened below: no change to the agent, the collector or the backend at all. |
| Click a span, verify in the browser, green or red (Qwen §3) | **keep** | Now cheap: `web/client.js` and the WASM verifier exist. This is the demo surface. |
| A decorator or `attach_warrant(span, w)` *inside the agent's code* signs and attaches (both) | **replace** | Objection 4 of the study: the agent signs its own self-report. That proves the log was not edited in transit, not that anyone with standing sanctioned anything. |
| `settlement_grade` as a span attribute (Qwen §2) | **drop** | Grade is a property of a *verification run* with a trust config, not of a record. Putting it on an unsigned span asserts a verification result nobody can check. |
| `evidence_hash` beside `id`, "MUST be identical" (Grok §3.1) | **drop** | Two fields that must agree are a disagreement waiting to happen. One key. |
| `ai.warrant.*` namespace, later an OTel semantic convention (Grok §3.1, §6) | **drop for now** | `ai.` is not this project's namespace (same objection `tools/intoto.py` records against minting a TypeURI under someone else's domain), and the GenAI conventions are still in development status. |
| "Collectors MUST treat unknown `ai.warrant.*` as strings" (Grok §3.1) | **drop** | This project cannot impose MUSTs on collectors. |
| "Bank-transaction-level audit trail", "prove it was not a hallucination" (Qwen) | **drop** | Warrant proves integrity, custody and that a stated reason re-executes. It does not prove the prose is true or that the action was enforced (`integration-study.md`, "Limits, stated"). |
| Red badge "TAMPERED" when a log is edited (Qwen §3) | **sharpen** | A signature catches an edited *record*. It does not catch a span relabelled to point at a *different valid* record. That needs a two-way binding (below). |

## What changed since the study declined this

The study's four objections, against what is documented now.

1. **No decision point in the conventions.** Still true of the GenAI
   conventions, and still irrelevant: the decision point is not in OTel, it is
   in the harness. What is new is that vendor telemetry now *names* that point.
   Claude Code emits `claude_code.tool_decision` with `decision` (`accept` |
   `reject`) and `source`, where `source = "hook"` means "a `PreToolUse` or
   `PermissionRequest` hook returned the decision"
   (code.claude.com/docs/en/monitoring-usage).
2. **A `SpanProcessor` cannot write the id back onto a finished span.** Still
   true, and no longer needed. Both records already carry the same key:
   `tool_use_id` on the Claude Code events "matches the `tool_use_id` passed to
   hooks" (same page), and on Claude API / SDK tool spans `gen_ai.tool.call.id`
   is "the `id` of the block in which the model asked to use the tool"
   (platform.claude.com/docs/en/api/opentelemetry/spans). If the warrant binds
   that id, correlation runs both ways without touching a span.
3. **The namespace is mid-migration.** Still true; the span reference itself
   says "span names and attributes can change during the beta". The design
   below depends on **one id field per source**, held in a small mapping table,
   not on the GenAI vocabulary.
4. **It would sign the agent's self-report.** Answered by moving the signer.
   The hook is a harness subprocess: the agent neither chooses to file nor can
   suppress the record. Same-host keys are still one custody, and the record
   says so (`sanction_independent`), as today.

The verdict on a *bridge that puts warrants into spans* stands. What follows is
a different thing: a record made at the sanction point, joined to telemetry by
an id both sides already carry, and an auditor that reads both.

## Why this is the strongest demonstration available

The vendor documentation states, in its own words, the gaps a warrant fills.
These are quotations, not inferences:

- **Refusals are where the trace goes quiet.** The Claude API "doesn't emit a
  tool span" when "the server denies the use under the `auto` permission
  policy, or the application denies it in a `user.tool_confirmation` event"
  (span reference). In Claude Code, `tool_result` is "not emitted if the tool
  call was rejected" (monitoring page); only the `tool_decision` event remains.
  The decision an auditor most wants to see is the one with the least telemetry.
- **Telemetry is not a complete record.** "Exported spans aren't guaranteed to
  be a complete record of your API usage. Their delivery is best effort … A
  caller can also leave out a request's spans by turning off the sampled flag"
  (platform.claude.com/docs/en/manage-claude/opentelemetry).
- **Telemetry carries no reason.** `tool_decision` says *that* a hook decided,
  not *which rule* or *why*; a reason, if any, lives only in the hook's reply to
  the model.
- **Nothing on a span is signed.** Integrity is whatever the backend's access
  control provides.

None of these is a defect in OpenTelemetry. Telemetry is observation, built to
be cheap, lossy and sampled. A warrant is evidence, built to be complete for
what it covers, signed, and re-runnable. The demonstration is that they are
different records of the same moment, made by different parties, and that
holding both lets an auditor say things neither can say alone.

## The design

```text
 agent ──tool_use──▶ harness ──PreToolUse/PermissionRequest──▶ hook (subprocess)
                        │                                          │
                        │ OTel: claude_code.tool_decision          │ warrant: propose + accept/reject
                        │   {tool_use_id, decision, source}        │   body binds tool_use_id, session_id,
                        ▼                                          │   traceparent (if given), input digest
                   collector ──▶ backend                           ▼
                        │                                      .warrants store
                        └──────────── export (OTLP/JSON) ──┐       │
                                                           ▼       ▼
                                              otel_audit: join on tool_use_id,
                                              verify store, re-run ski, classify
```

### 1. Record at the sanction point (exists; one change)

The PreToolUse binding (`integrations/approval/examples/pretooluse_hook.py`)
already files a request and a sanction for every non-deferred decision. Today it
puts `tool_use_id=…` into a **prose reason**. It must move into the **signed
subject** as structured fields, because the join and the two-way binding check
read it:

```json
{"tool_name": "Bash",
 "tool_use_id": "toolu_…",
 "session_id": "…",
 "traceparent": "00-<trace>-<span>-01",
 "tool_input_sha256": "…"}
```

`traceparent` is included only when the hook process actually receives one
(**unverified**: the monitoring page says Agent SDK and `-p` sessions honour
`TRACEPARENT` for event records; whether hooks inherit it must be checked by
running). The tool input is bound by digest, not copied; see open decision 2.

The same boundary serves the Claude API: on Managed Agents the *application*
answers `user.tool_confirmation`, so the application is the sanctioner and the
join key is the `gen_ai.tool.call.id` of that tool use.

### 2. Correlate without touching telemetry (new, the core)

`tools/otel_audit.py`, standard library only, the same shape as
`tools/intoto.py` (a projection plus a `check` that recomputes everything from
the store and trusts nothing it is handed). Input: an OTLP/JSON export (the
collector's file exporter output) and a store, optionally a trust config.
Output: one row per `tool_use_id`, each in exactly one class.

| Class | Telemetry | Warrant | What it means |
| --- | --- | --- | --- |
| `corroborated` | decision present | sanction bound to this id, same decision, store verifies | the two records agree, and one of them is signed |
| `reason-reruns` | as above | reason is a `ski@v1` check that re-executes | a stranger can recompute *why*, offline |
| `prose-only` | as above | reason is prose | integrity and custody only; flagged, as `verify` flags it today |
| `invisible-refusal` | no tool span / no `tool_result` | signed `reject` | the refusal the trace dropped by design |
| `unwarranted` | `source = hook`, no warrant | none | the hook decided but nothing was filed (recorder failed, or bypassed) |
| `contradiction` | `accept` | signed `reject` (or the reverse) | one of the two records is wrong; the signed one names its signer |
| `misbound` | span or event names `warrant.id` X | X binds a different `tool_use_id` | a pointer relabelled to another valid record |
| `store-invalid` | any | record fails verification | the evidence itself was altered |

`contradiction` and `misbound` are the classes no trace-only tool can produce,
because producing them needs a record the telemetry pipeline cannot write.

The report is a new **non-normative** tag, `warrant.otel-audit@v0`, the same
status `warrant.why@v0` has: a tool output, not a SPEC section.

### 3. Optional pointer, emitted by the hook (new, gated)

The hook cannot set attributes on the harness's spans, and does not need to. When
`WARRANT_OTEL_ENDPOINT` is set it may emit **its own** OTLP/HTTP-JSON log record
(stdlib `urllib`, no SDK dependency), parented by `traceparent` when present:

```text
event.name        = "warrant.sanction"
warrant.id        = "<WarrantID of the sanction>"
warrant.tool_use_id = "<tool_use_id>"
warrant.decision  = "accept" | "reject"     # a hint; the auditor checks it
```

`warrant.*` is a project-local prefix, not a semantic convention. `decision` is
denormalised for dashboard filtering only: the auditor compares it with the
signed record and a mismatch is a finding, not a display bug. Emission is
best-effort and never blocks the hook, for the reason the hook already states:
an audit trail must not become an outage.

### 4. Verify where the trace is read (later)

Extend the browser lab: drop an OTLP/JSON export and a `.warrants` folder, get
the audit table with the same classes, each row expandable to the existing
`warrant.verify-report@v0` and the `ski@v1` re-run. The join runs in `client.js`;
verification stays in the WASM core. A Grafana/Tempo panel is a later
packaging of the same function, not a separate verifier.

## The demonstration, end to end

`demos/otel-vs-warrant/`, one script, offline, run by `tools/check.py`:

1. Three tool calls through the PreToolUse binding: a benign read (deferred,
   nothing filed), `rm -rf` (denied), and a deploy allowed under a **compiled
   `ski@v1` rule**, so one reason re-executes.
2. Telemetry fixtures shaped exactly as documented (`tool_decision`,
   `tool_result`), stating in their header that they are synthesised from the
   documented schema, not captured.
3. The audit table, then five controls, each of which must change exactly the
   row it targets:
   - flip a telemetry `reject` to `accept` → `contradiction`;
   - delete a telemetry record (what sampling or a lost batch does) → the warrant
     still stands, the row says telemetry is missing;
   - the denied call has no `tool_result` by design → `invisible-refusal`;
   - relabel a `warrant.id` pointer → `misbound`;
   - flip one byte in the store → `store-invalid`.
4. `warrant check <id>` re-executes the allowed call's reason and prints the
   same verdict on any machine.

The fixture is honest only if a **real capture** replaces it: run Claude Code
with telemetry to a file exporter and the hook installed, commit the redacted
export with the Claude Code version that produced it. That step needs the owner
(a real session, real telemetry config), and until it happens the demo says
"synthesised from documentation" in its output, not only in a comment.

## Phases

| Phase | Deliverable | Done means | Testable on a clean checkout |
| --- | --- | --- | --- |
| P0 | structured binding in the hook's subject | `test_pretooluse_hook.py` asserts the bound fields and that a changed `tool_use_id` changes the WarrantID | yes |
| P1 | `tools/otel_audit.py` + fixtures + every class above with a negative control | each control flips exactly its row; wired into `tools/check.py` | yes, stdlib only |
| P2 | gated OTLP/JSON emission from the hook | a local stdlib HTTP server receives the record; hook latency unchanged with the variable unset; a dead endpoint does not block the hook | yes |
| P3 | browser audit view | the same fixture gives the same table in WASM as in Python | yes (Node + WASM, as `web/` tests now) |
| P4 | a real captured export replaces the synthetic fixture | version-stamped, redacted, reproduced by the audit | **no** — needs the owner and a live session |

## Not in scope

- Signing spans, or any change to the OTel data model or a collector.
- Proposing a semantic convention. Revisit only when the GenAI conventions leave
  development status and a decision/approval concept exists there.
- A Grafana plugin, a LangSmith/Langfuse/Arize adapter, or any framework
  adapter (the study's M×N argument is unchanged).
- Enforcement. The harness enforces; the record records.
- Key custody. Same-host keys stay one custody, reported, not solved.

## Open decisions for the owner

1. **Does this amend the study's verdict?** Proposed reading: the OTel *bridge*
   stays declined; a *correlation auditor beside telemetry* is a new candidate
   that passes the study's four-part test (decision point: the hook; independent
   sanctioner: the harness; contract: one id field per source plus a JSON export
   format; reason re-executes: in the `ski@v1` path).
2. **Tool input binding.** A digest of a low-entropy input (a short shell
   command) is guessable by enumeration, so it is not confidential; copying the
   input is worse. Options: digest (proposed, with that limit stated), keyed
   digest (needs a key policy), or no binding of the input at all.
3. **Attribute prefix.** `warrant.*` (proposed) versus a URI-qualified prefix.
   Neither is a convention; the choice only affects collision risk.
4. **Which vendor first.** Claude Code (hooks + `tool_decision`; documented
   join key; the binding already exists) is proposed. Managed Agents
   `user.tool_confirmation` second.

## Limits, stated

- Every vendor field named here is beta and can be renamed; the mapping table is
  the cost of that, and it is a standing obligation.
- The join key is chosen by the model's runtime (`toolu_…`), not by the
  sanctioner. Binding it proves the warrant was made *for* that id; it does not
  prove the harness enforced the decision on that call.
- `unwarranted` cannot distinguish "the recorder failed" from "the recorder was
  bypassed" from telemetry alone; it only says a sanction exists without
  evidence.
- Nothing above has been executed. The vendor quotations were read on
  2026-10-15. Green suites, when they exist, will be necessary and not
  sufficient; an adversarial gate is still owed.
