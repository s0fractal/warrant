# Warrant beside telemetry, not inside it

**Status: a design synthesis; phases P0 and P1 are built, nothing is adopted.**
No independent gate ran: what exists is self-tested, with mutation checks of
the selftest itself (see "What P1 actually checks"). It revisits Candidate 2 of [`integration-study.md`](integration-study.md)
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
files a request and a sanction for every non-deferred decision. It used to put
`tool_use_id=…` into a **prose reason**; it now writes a **signed subject**
built by `warrant_approval.tool_call_subject`, because the join and the two-way
binding check read it:

```json
{"type": "warrant.tool-call@v0",
 "tool_name": "Bash",
 "tool_input": {"command": "rm -rf /srv/data"},
 "tool_use_id": "toolu_…",
 "session_id": "…",
 "traceparent": "00-<trace>-<span>-01"}
```

`traceparent` is bound only when the hook process actually receives one in
`TRACEPARENT` (**unverified** for Claude Code: the monitoring page says Agent SDK
and `-p` sessions honour `TRACEPARENT` for event records; whether hooks inherit
it must be checked by running). The tool input is kept whole (decision 2 below).

The same boundary serves the Claude API: on Managed Agents the *application*
answers `user.tool_confirmation`, so the application is the sanctioner and the
join key is the `gen_ai.tool.call.id` of that tool use.

### 2. Correlate without touching telemetry (new, the core)

`tools/otel_audit.py` (built), standard library only, the same shape as
`tools/intoto.py`: it recomputes from the store and trusts nothing it is handed,
including the subject blob that carries the join key (it re-hashes that blob
itself, not only through `verify`). Input: OTLP/JSON exports (the collector's
file exporter output, one request per line or one document) and a store,
optionally `--settlement --trust-config`. Output: one row per `tool_use_id`, in
exactly one class, checked in this order:

| Class | Telemetry | Warrant | What it means | Exit |
| --- | --- | --- | --- | --- |
| `store-invalid` | any | a bound record fails verification, or its subject blob does not hash to its name | the evidence itself was altered | 1 |
| `misbound` | a `warrant.sanction` pointer names X | X does not bind this call, or holds another decision | a pointer relabelled to another valid record, or a lying hint | 1 |
| `contradiction` | a decision that differs, or a `tool_result`/tool span after a signed `reject` | — or two signed sanctions that disagree | one record is wrong; the signed one names its signer | 1 |
| `unwarranted` | `source = hook` | none | the hook decided; nothing was filed (recorder failed or bypassed) | 1 |
| `telemetry-missing` | nothing about this call | signed sanction | sampled, lost, or a refusal the trace does not record (API: no tool span for a denied call) | 0 |
| `corroborated` | decision present, or the tool ran after a signed `accept` | signed sanction, same decision | the two records agree, and one is signed | 0 |
| `not-hook` | decided by `config` or a person | none | outside this boundary; no warrant expected | 0 |

Each sanction also carries a **reason** status: `reruns` (a `ski@v1` check
re-executed by the CLI reproduced its claimed verdict), `fails`, `unverified`
(the check could not run), `cmd-unrun` (`cmd@v1` is never executed here), or
`prose-only`. That column is what a trace can never have.

`contradiction`, `misbound` and `telemetry-missing` are the classes no
trace-only tool can produce, because producing them needs a record the
telemetry pipeline cannot write or delete.

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

Built as `demos/otel-vs-warrant/demo.py` (wired into `tools/check.py`; every
scene asserts its outcome). The plan it implements:

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
| P0 | structured binding in the hook's subject | **built**: `test_pretooluse_hook.py` asserts the bound fields, that a changed `tool_use_id` changes the subject, and that a handed `TRACEPARENT` is bound | yes |
| P1 | `tools/otel_audit.py` + fixtures + every class above with a negative control | **built**: each control flips exactly its row; wired into `tools/check.py` | yes, stdlib only |
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

## Decisions taken (owner, 2026-10-15)

1. **The study's verdict is amended, not reversed.** The OTel *bridge* stays
   declined; a *correlation auditor beside telemetry* is a new candidate that
   passes the study's four-part test (decision point: the hook; independent
   sanctioner: the harness; contract: one id field per source plus a JSON export
   format; reason re-executes: in the `ski@v1` path).
2. **The tool input stays whole in the subject.** The owner left this open; the
   reasoning that settled it: the store is the operator's own evidence and the
   hook already kept the full input there; a digest of a short command is
   guessable, so it would hide nothing while losing *what was refused*. Nothing
   from the store goes into telemetry except ids (P2). Sharing a store shares the
   commands in it, as it always did.
3. **Attribute prefix `warrant.*`** (owner delegated). Not a convention.
4. **Claude Code first** (owner delegated): hooks + `tool_decision`, a documented
   join key, and a binding that already exists. Managed Agents
   `user.tool_confirmation` second.

## What P1 actually checks

The selftest drives the real hook as a subprocess for the refusal and the
deferral, files the allowed call with a compiled `ski@v1` reason, synthesises
telemetry in the documented event shapes, and asserts the baseline table. Then
each control must change **exactly** its target row: telemetry flipped to
`accept`; a refusal shown executing; B's telemetry lost; an API-shaped trace
where the denied call has no span (and B is known only by its `execute_tool`
span); a pointer relabelled to another valid record; a pointer hint that lies;
a second signed sanction that disagrees; a rewritten record; a subject blob
edited to rebind another call, also under a stub verifier that reports
everything ok. The reason column is tested directly for `reruns`, `fails`,
`unverified` and `cmd-unrun`.

The selftest was itself mutation-tested before commit: twelve single-line
breakages of the auditor (ignore a disagreement, skip the pointer check, trust
the blob, stop comparing the ski verdict, ignore spans, …). The first run let
three survive; the controls above were strengthened until every one fails the
selftest. That is a check of the tests, not an independent gate.

## Limits, stated

- Every vendor field named here is beta and can be renamed; the mapping table is
  the cost of that, and it is a standing obligation.
- The join key is chosen by the model's runtime (`toolu_…`), not by the
  sanctioner. Binding it proves the warrant was made *for* that id; it does not
  prove the harness enforced the decision on that call.
- `unwarranted` cannot distinguish "the recorder failed" from "the recorder was
  bypassed" from telemetry alone; it only says a sanction exists without
  evidence.
- The telemetry the selftest reads is **synthesised from documentation**, not
  captured from a live harness (P4). Field names, `event.name` values and the
  OTLP/JSON envelope are the documented ones; a real export may differ in ways
  only a capture will show. The vendor quotations were read on 2026-10-15.
- Green suites are necessary and not sufficient; an adversarial gate is still
  owed.
