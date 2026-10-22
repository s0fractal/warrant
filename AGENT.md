# warrant-agent/1

The application interface for handing work between agents over Warrant 2:
one backend (`warrant_agent.api.call`), three front ends over it, all of which
take the same request objects and return the same result objects.

| Front end | Entry | Install |
| --- | --- | --- |
| Python | `warrant_agent.api.call(Config.load(path), op, request)` | `warrant-graph` |
| CLI | `warrant-agent --config C.json <op> [REQUEST.json \| - \| '{...}']` (exit 0 result, 2 typed refusal) | `warrant-graph` |
| stdio MCP | `warrant-agent-mcp --config C.json` | `warrant-graph[mcp]` (official SDK, `mcp==2.3.0`) |

Computation needs the Sigma provider (`warrant-graph[compute]`, the exact
sigma-glyph release in `pyproject.toml`, PyPI 0.8.0). This is not a new record type, not a
SPEC extension and not an extension of MCP. `agent_api` is the interface
version; it is not Warrant `"2"`, not `sigma_provider:1` and not an MCP revision.

## Configuration (the operator's, never a request's)

```json
{"agent_api": "warrant-agent/1", "state": "/path/state",
 "workspaces": {"rcv": {
   "store": "/path/store", "trust": "/path/trust.json", "profile": "/path/profile.json",
   "signer": {"actor": "receiver", "key": "/path/receiver.key"},
   "source_name": "rcv", "current": [], "repo": null,
   "expectations": {"src-full": {"manifest": "<hex64>", "source": "src", "exporter": "producer"}},
   "uses": {"continue": {"delivery": ["MATCH_EXPECTED_SET", "LOCAL_CAPTURE"], "reliance": ["ELIGIBLE"], "fresh": true},
            "import": {"delivery": ["MATCH_EXPECTED_SET"]}},
   "limits": {"context_bytes": 16384, "transfer_bytes": 16777216, "assess_seconds": 120,
              "provider_seconds": 600, "read_bytes": 65536, "view_ttl": 86400,
              "snapshot_records": 100000, "snapshot_blobs": 100000, "snapshot_bytes": 1073741824,
              "requires_edges": 1000000, "duty_periods": 10000, "report_periods": 100000},
   "operations": ["context", "read", "handoff", "prepare", "commit", "compute"]}}}
```

Requests name a workspace and an expectation only by these local handles. No
request carries a path, a URL, a key, a signer, code or a package. A profile
names the providers it accepts; computing never adds one. On a shared machine
this is an application boundary, not OS isolation: an agent with a shell on
the same keys and configuration is not contained by it, and shared custody is
not independent custody.

The last six limits are the engine's admission limits (SPEC §9), shown at
their defaults. A store or view beyond one is refused as `RESOURCE_LIMIT` with
`details: {limit, value, bound}` before it is assessed; no view is kept and no
verdict is produced. A malformed one (unknown name, not a positive integer) is
refused when the configuration loads.

## Operations

Every result is `{"agent_api", "adapter_id", "data", ...}`; a refusal is
`{"error": CODE, "message", ...details}`. Codes: BAD_REQUEST,
UNSUPPORTED_VERSION, NOT_PERMITTED, UNKNOWN_WORKSPACE, UNKNOWN_EXPECTATION,
VIEW_UNKNOWN, VIEW_EXPIRED, CURSOR_MISMATCH, NOT_FOUND, CONFLICT,
RESOURCE_LIMIT, NO_ASSESSMENT, IMPORT_INCOMPLETE, IMPORT_BLOCKED,
SIGNER_CHANGED, NO_SIGNER, PROVIDER, REFUSED. Unknown members are refused.

Members marked `?` may be left out; the default is the one named in the row.
Defaults are taken from the operator's configuration or from the view, never
invented: the default use is the workspace's first configured use, the default
actor is the configured signer's.

| op | request | what it does |
| --- | --- | --- |
| `workspace` | `{workspace?}` | The operator's configuration by name: workspaces, the signer's actor, permitted operations, use policies and `default_use`, expectation handles (`manifest`, `source`, `exporter`), whether the provider is installed and accepted by the profile, and an `index` of the duties and transitions in the live store (at most 50 rows, newest first, `untrusted_data: true`, `assessed: false`). No path, key or URL. Needs no permission: it shows what the configuration already names. |
| `context` | `{workspace, actor?, use?, targets?:[id \| {id} \| {kind: duty\|transition, id}], limits?:{context_bytes}}` | Captures the store, trust, profile and provider bytes into a frozen view, assesses it once in a worker under `assess_seconds`, returns `view_token`, `assessment_id`, capsules, frontier, unowned questions, boundary, `delivery`, `use`, `observation`, `page`. `actor` selects whose frontier is read, not who signs. A target without its kind is resolved in the view: a duty or a transition; any other record id is BAD_REQUEST with `details.type`, an id not in the view NOT_FOUND. An unknown use is BAD_REQUEST with `details.configured`. |
| `read` | `{workspace, view_token?, kind?: record\|blob\|context, target?, cursor?, max_bytes?}` or `{workspace, kind: draft\|operation, target}` | Reads the view's captured bytes (chunked, with `digest`, `complete`, `untrusted_data: true`) or the next context page; or a durable draft/import status, which needs no live view. `kind` defaults to `record`. Without `view_token` a record or blob is read from a new frozen view (returned as `view_token`), never from the live store; a context page or a cursor needs the view that made it. |
| `handoff` | `{op: export, view_token?, roots?, request_id?}` / `{op: inspect, package \| (manifest, payload, declaration?), expectation?, use?, actor?, targets?}` / `{op: import, staged_id, request_id?}` | Export: manifest of the whole configured store (record envelope digests, blobs, snapshot digest, `completeness: UNATTESTED`), payload `{records\|blobs: [{id, bytes_base64}]}`, optional declaration signed by the configured signer; `view_token` defaults to a new view, `roots` to that view's context targets, `request_id` to one derived from view and roots (returned). A root that is not a duty or transition is BAD_REQUEST. Inspect: stages and assesses the union with the receiver's live store against a receiver-configured expectation; `package` is the exported object in one piece (the same inspection as its parts); capsules default to the manifest's roots. Import: journaled, add-only, idempotent; `request_id` defaults to one derived from `staged_id`. |
| `prepare` | `{workspace, type, body, based_on?: view_token, request_id?}` | Freezes one exact record (actor and key from configuration, `at` = first durable prepare). Same request id and inputs: the same draft. Other inputs: CONFLICT. Without `based_on` the record is checked against a new view; without `request_id` the draft is named by type and body, so the same body is the same draft. A transition without `closes` closes nothing (`closes: []`, `evidence: []`). `accept` takes `{transition, item, evidence?, support?}`; evidence defaults to the item's exact evidence in the view. An invalid body is BAD_REQUEST with `details.template`, the smallest body of that type. Nothing is signed. |
| `commit` | `{workspace, draft_id}` | Signs and files exactly the draft. A retry after response loss or restart returns the same record; other bytes under the id: CONFLICT; another configured signer: SIGNER_CHANGED. |
| `compute` | `{workspace, op: provider\|term\|evaluate\|start\|resume\|cycle, ...hex64 addresses, expr?, expect_expr?, credit?, max_actions?, max_steps?, target?}` | Runs the installed provider on bytes read once from the receiver's store; new bytes go back as blobs. A foreign checkpoint is continued only by the provider's checked `resume` (verify from the receiver's root, then advance). `evaluate {expr, expect_expr?, credit? (10000), runtime? (book1)}` is term, start and resume in one call: `outcome`, `result`, and with `expect_expr` `same_normal_form` (true only at a NORMAL_FORM whose result is that term's input address). Reports `provider_accepted_by_profile`; files nothing and credits nothing. |
| `explain` | `{term}` | The static meaning of a reliance state, verdict, delivery relation or refusal code and what it does not establish (`warrant_agent/glossary.py`); an unknown term lists the known ones. |

### Capsules

Each capsule is the engine's (`warrant.engine.capsule`) plus three members
taken from the same report: `closures` on a duty (every closure attempt:
`transition, item, act, filer, basis, verdict, why, waiting_for?`), `closes` on
a transition (each item with its `duty`, the duty's `statement` and
`duty_disposition`, `verdict`, `why`), and `reading`, one line over those
fields. A transition's own `reliance` is about its results (often UNASSESSED);
whether it closes a duty is decided on the duty, which `closes` shows. The
boundary names up to 20 `invalid` records (`id`, `why`, and `claims_to_be`:
type, actor and target read from bytes that do not authenticate). None of this
adds a rule: it is the report the engine already produced, shown.

### Delivery and use

`delivery.relation` is one of MATCH_EXPECTED_SET, UNPINNED (no receiver
expectation), MISSING_DECLARED_BYTES, CONTENT_MISMATCH, WRONG_SET, WRONG_SOURCE,
UNVERIFIED_EXPORTER, or LOCAL_CAPTURE for a context without a transfer.
`source_completeness` is always UNATTESTED. A manifest digest supplied by the
sender is never an expectation: only a configured handle is.

The definition behind the expectation handle is part of what is observed now.
`observation.expectation` is `{handle, state: CURRENT|CHANGED|REMOVED, definition}`:
if the operator changes or removes the handle after an inspection, current use
holds with a new decision id and the staged package is not promoted
(IMPORT_BLOCKED, inspect again). The historical assessment of that view is not
rewritten, and a completed import stays reported as completed history. A
promotion also re-checks every staged record against the manifest's envelope
digest and, for a MATCH, that the staged set is exactly the declared set, and
that an exporter the expectation names still verifies under the receiver's
CURRENT trust. `observation.trust_current` is false when the trust file changed
after the view was captured; a `fresh` use then holds, and so does any use of
a delivery that rested on an exporter's declaration. An unfinished import stops
holding the workspace once every object its manifest declares is in the live
store with the declared bytes (for example through a later, larger import); the
staging directory is not consulted for that set.

Draft ids and record ids in requests are full hex64 addresses before any path
is built, and a draft is readable and committable only in the workspace that
prepared it.

`use` is the receiver's local policy decision over the core assessment:
`{name, policy, state: WITHIN_POLICY|HOLD, reasons, decision_id}`. The
decision id covers the assessment id, adapter id, policy, delivery, the
observed time, incomplete imports and whether a newer local event is known. A
newer event changes the decision id and holds a `fresh` use; it never changes
the historical assessment id.

### Implementation choices against the design contract

- `read` pages the whole context (`kind: context`) instead of separate
  `capsule`/`frontier`/`questions` kinds; truncation is marked and every
  cursor is bound to its view, kind and target.
- A cancelled MCP request is not rolled back: the status of a draft is read
  by a new request (`read {kind: draft}`), from any server instance.
- A view lives at least `view_ttl` whole seconds from the moment it is ready.

## MCP

Eight tools: `warrant_workspace`, `warrant_context`, `warrant_read`,
`warrant_handoff`, `warrant_prepare`, `warrant_commit`, `warrant_compute`,
`warrant_explain`. Every tool takes the request's members as flat, typed
arguments with a description each (`warrant_context` takes `context_bytes`
for `limits.context_bytes`); an argument left out is left out of the request.
The interface version is checked by the backend (`agent_api` in a Python or
CLI request); MCP tools carry none, the server reports `warrant-agent/1` as
its version. The server's instructions say where to start and what a result
does not establish; read-only tools are annotated `readOnlyHint`. Tool
descriptions are static; nothing from a record or evidence becomes a tool, a
schema, a configuration or a signer. A refusal is a tool error whose text is
the refusal's JSON; a semantic verdict such as CHALLENGED or HOLD is an
ordinary result. stdout carries MCP messages only.

These choices were measured with fresh agents before and after
(`examples/mcp-first-contact/RESULTS.md`).

Measured with `mcp==2.3.0` (`tests/agent_mcp_test.py`, raw JSON-RPC client and
the SDK client):

| Client request | Negotiated |
| --- | --- |
| initialize 2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25 | the same revision |
| initialize with an unknown revision (1999-01-01) | 2025-11-25 (the server's latest handshake revision) |
| SDK `discover()` | 2026-07-28 |

No HTTP transport, watcher, scheduler, OAuth, shell, package install, merge or
release is exposed.

## Checks

| Suite | Cases |
| --- | --- |
| `tests/agent_handoff_test.py` | H01-H14, V01-V08 |
| `tests/agent_write_test.py` | W01-W09 |
| `tests/agent_compute_test.py` | S01 end to end, exact acceptance retry/restart, S02-S04 negatives, S07, S08, S10, S11 (a contradicted receipt closes nothing; both capsules say why), S12 (evaluate) |
| `tests/agent_mcp_test.py` | M01-M05, cancellation, M06-M14 (overview, targets, closures, defaults, export roots, package inspect, read without a view, prepare defaults, explain) |
| `tests/agent_mutants.py` | A01-A35, A41-A53, each killed on its named case |
| `examples/mcp-first-contact/` | fresh headless agents on three tasks, frozen scorer, round 1 vs round 2 |
| `examples/agent/acceptance.py --door python\|cli\|mcp` | the end-to-end run, from installed wheels outside the checkout |

## Measured cost of the provider (2026-10-19)

Each `compute` operation and each replayed receipt inside an assessment starts
the Sigma provider in a fresh interpreter (`-I -B`, module bytes on stdin).
This was measured on the acceptance run (`examples/agent/acceptance.py --door
python`, Apple Silicon, Python 3.15):
- 7 provider calls, about 31 ms each (term, start, resume, verify alike);
- 0.22 s of a 1.1 s run.

The cost grows with the number of computation receipts an assessment replays
and with their size: the dependency-audit receipts of `examples/dependency-audit`
cost about 14 s each on the round-1 hosts, and every `context`, `inspect` and
`prepare` opens a view that replays every receipt in the store. Since
2026-10-20 the workspace keeps a **replay cache** under `<state>/replay-cache`
(SPEC §7: it changes cost, never the answer or the task). It is the receiver's
own, keyed by the provider identity and the exact chain (runtime, input,
environment, checkpoint, state); an entry is consulted only when every byte the
uncached replay would read is in the view, only REPLAYED results are kept, and
the cache is not part of the assessment identity. The `warrant` CLI takes
`--replay-cache DIR` for the same purpose. `tests/compute_test.py` C16-C18 and
mutants M44-M45 pin this down.

## Not solved here

A set signed incomplete from the start, with the receiver's expectation on
exactly that set, MATCHes (H03, and step A4 of the acceptance run). Delivery
MATCH means "the selected set arrived", nothing more: global completeness stays
UNATTESTED, and this layer does not resolve it.
