# warrant-agent/1

The application interface for handing work between agents over Warrant 2:
one backend (`warrant_agent.api.call`), three front ends over it, all of which
take the same request objects and return the same result objects.

| Front end | Entry | Install |
| --- | --- | --- |
| Python | `warrant_agent.api.call(Config.load(path), op, request)` | `warrant-loops` |
| CLI | `warrant-agent --config C.json <op> [REQUEST.json \| - \| '{...}']` (exit 0 result, 2 typed refusal) | `warrant-loops` |
| stdio MCP | `warrant-agent-mcp --config C.json` | `warrant-loops[mcp]` (official SDK, `mcp==2.3.0`) |

Computation needs the Sigma provider (`warrant-loops[compute]`, the exact
sigma-glyph commit in `pyproject.toml`). This is not a new record type, not a
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
              "provider_seconds": 600, "read_bytes": 65536, "view_ttl": 86400},
   "operations": ["context", "read", "handoff", "prepare", "commit", "compute"]}}}
```

Requests name a workspace and an expectation only by these local handles. No
request carries a path, a URL, a key, a signer, code or a package. A profile
names the providers it accepts; computing never adds one. On a shared machine
this is an application boundary, not OS isolation: an agent with a shell on
the same keys and configuration is not contained by it, and shared custody is
not independent custody.

## Operations

Every result is `{"agent_api", "adapter_id", "data", ...}`; a refusal is
`{"error": CODE, "message", ...details}`. Codes: BAD_REQUEST,
UNSUPPORTED_VERSION, NOT_PERMITTED, UNKNOWN_WORKSPACE, UNKNOWN_EXPECTATION,
VIEW_UNKNOWN, VIEW_EXPIRED, CURSOR_MISMATCH, NOT_FOUND, CONFLICT,
RESOURCE_LIMIT, NO_ASSESSMENT, IMPORT_INCOMPLETE, IMPORT_BLOCKED,
SIGNER_CHANGED, NO_SIGNER, PROVIDER, REFUSED. Unknown members are refused.

| op | request | what it does |
| --- | --- | --- |
| `context` | `{workspace, actor, use, targets:[{kind: duty\|transition, id}], limits?:{context_bytes}}` | Captures the store, trust, profile and provider bytes into a frozen view, assesses it once in a worker under `assess_seconds`, returns `view_token`, `assessment_id`, capsules, frontier, unowned questions, boundary, `delivery`, `use`, `observation`, `page`. `actor` selects whose frontier is read, not who signs. |
| `read` | `{workspace, view_token, kind: record\|blob\|context, target?, cursor?, max_bytes?}` or `{workspace, kind: draft\|operation, target}` | Reads the view's captured bytes (chunked, with `digest`, `complete`, `untrusted_data: true`) or the next context page; or a durable draft/import status, which needs no live view. |
| `handoff` | `{op: export, view_token, roots, request_id}` / `{op: inspect, manifest, payload, declaration?, expectation?, use?, actor?, targets?}` / `{op: import, staged_id, request_id}` | Export: manifest of the whole configured store (record envelope digests, blobs, snapshot digest, `completeness: UNATTESTED`), payload `{records|blobs: [{id, bytes_base64}]}`, optional declaration signed by the configured signer. Inspect: stages and assesses the union with the receiver's live store against a receiver-configured expectation. Import: journaled, add-only, idempotent. |
| `prepare` | `{workspace, based_on: view_token, request_id, type, body}` | Freezes one exact record (actor and key from configuration, `at` = first durable prepare). Same request id and inputs: the same draft. Other inputs: CONFLICT. `accept` takes `{transition, item, evidence?, support?}`; evidence defaults to the item's exact evidence in the view. Nothing is signed. |
| `commit` | `{workspace, draft_id}` | Signs and files exactly the draft. A retry after response loss or restart returns the same record; other bytes under the id: CONFLICT; another configured signer: SIGNER_CHANGED. |
| `compute` | `{workspace, op: provider\|term\|start\|resume\|cycle, ...hex64 addresses, credit?, max_actions?, max_steps?, target?}` | Runs the installed provider on bytes read once from the receiver's store; new bytes go back as blobs. A foreign checkpoint is continued only by the provider's checked `resume` (verify from the receiver's root, then advance). Reports `provider_accepted_by_profile`; files nothing. |

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

Six tools: `warrant_context`, `warrant_read`, `warrant_handoff`,
`warrant_prepare`, `warrant_commit`, `warrant_compute`. Tool descriptions are
static; nothing from a record or evidence becomes a tool, a schema, a
configuration or a signer. A refusal is a tool error whose text is the
refusal's JSON; a semantic verdict such as CHALLENGED or HOLD is an ordinary
result. stdout carries MCP messages only.

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
| `tests/agent_compute_test.py` | S01 end to end, exact acceptance retry/restart, S02-S04 negatives, S07, S08, S10 |
| `tests/agent_mcp_test.py` | M01-M05, cancellation |
| `tests/agent_mutants.py` | A01-A27, each killed on its named case |
| `examples/agent/acceptance.py --door python\|cli\|mcp` | the end-to-end run, from installed wheels outside the checkout |

## Measured cost of the provider (2026-10-19)

Each `compute` operation and each replayed receipt inside an assessment starts
the Sigma provider in a fresh interpreter (`-I -B`, module bytes on stdin).
This was measured on the acceptance run (`examples/agent/acceptance.py --door
python`, Apple Silicon, Python 3.15):
- 7 provider calls, about 31 ms each (term, start, resume, verify alike);
- 0.22 s of a 1.1 s run.

No verdict cache is kept. The cost grows with the number of computation
receipts an assessment replays, at about 31 ms each, so it matters only for
stores holding hundreds of them. A cache, if added, must be local to the
receiver and keyed by the provider identity and the exact bytes.

## Not solved here

A set signed incomplete from the start, with the receiver's expectation on
exactly that set, MATCHes (H03, and step A4 of the acceptance run). Delivery
MATCH means "the selected set arrived", nothing more: global completeness stays
UNATTESTED, and this layer does not resolve it.
