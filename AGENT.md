# warrant-agent/1

The application interface for handing work between agents over Warrant 2:
one backend (`warrant_agent.api.call`), three front ends over it, all of which
take the same request objects and return the same result objects.

| Front end | Entry | Install |
| --- | --- | --- |
| Python | `warrant_agent.api.call(Config.load(path), op, request)` | `warrant-graph` |
| CLI | `warrant-agent --config C.json <op> [REQUEST.json \| - \| '{...}']` (exit 0 result, 2 typed refusal) | `warrant-graph` |
| stdio MCP | `warrant-agent-mcp --config C.json` | `warrant-graph[mcp]` (official SDK, `mcp==2.3.0`) |

**The contract is [SPEC.md §10](SPEC.md#10-agent-interface)**, generated from
signed claim records like the rest of SPEC.md (`tools/claims.py`): what each
operation guarantees, the refusal codes, what a view token, a draft and an
expectation mean, and what the interface does not do. Each normative sentence
there is BACKED by a case of `tests/agent_*_test.py` and an agent mutant killed
on it, or UNBACKED with the reason nothing witnesses it (SPEC-CLAIMS.md). This
file is the operator's guide: configuration, request shapes, front ends and
measured costs. Where the two differ, §10 holds.

Computation needs the Sigma provider (`warrant-graph[compute]`, the exact
sigma-glyph release in `pyproject.toml`, PyPI 0.8.0). The interface adds no
record type and no rule of assessment (SPEC-10-4), and it is not an extension of
MCP. `agent_api` is the interface version; it is not Warrant `"2"`, not
`sigma_provider:1` and not an MCP revision.

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

`trust` is a trust/2 file, or `{"bindings": PATH, "roles": PATH}` of a
repository (`init` below). Requests name a workspace and an expectation only by these local handles
(SPEC §10.1); on a shared machine this is an application boundary, not OS
isolation (SPEC §10.8).

The last six limits are the engine's admission limits (SPEC §9), shown at
their defaults. A store or view beyond one is refused as `RESOURCE_LIMIT` with
`details: {limit, value, bound}` before it is assessed; no view is kept and no
verdict is produced. A malformed one (unknown name, not a positive integer) is
refused when the configuration loads.

## A repository checkout: `init`

```sh
warrant-agent-mcp init --repo ~/Projects/warrant --actor codex --seed ~/keys/codex.seed \
    --config ~/.warrant/warrant-codex.json [--state DIR] [--workspace NAME] \
    [--operations context,read,prepare,commit] [--force]
warrant-agent-mcp --config ~/.warrant/warrant-codex.json
```

`init` is the operator's command, not a tool, and the server never runs it. It
writes a configuration of one workspace (default name: the checkout's directory
name) for a repository that keeps its records in `.warrant/` the way
`tools/claims.py` and `tools/roadmap.py` do:

- the store is `.warrant/store`;
- the trust is `{"bindings": ".warrant/trust.json", "roles": ".warrant/roles.json"}`:
  the bindings that file admits under those pins, by `warrant/bindings.py`, the
  rule `tools/claims.py` admits by, read again for every view (a binding merged
  later is in the next view, and an older view's `observation.trust_current`
  turns false). A roles file with any problem refuses every view as
  `BAD_REQUEST`, since a dropped pin would make its name first-come;
- the profile (`<state>/<workspace>/profile.json`) counts results acceptances
  by `.warrant/roadmap.json`'s `results_accept_by`, with one use, `continue`;
  run `init --force` again if that file changes;
- the signer is the operator's existing seed for `--actor`, accepted only if its
  key is exactly the key `.warrant/roles.json` pins for that actor and
  `.warrant/trust.json` admits that binding. `init` creates, copies and binds
  no key (`tools/claims.py keygen`, `pin` and `bind` are the operator's);
- operations default to `context, read, prepare, commit`; `handoff` and
  `compute` are enabled only by `--operations`.

The configuration, the state directory and the seed must lie outside the
repository, and all of them, the repository too, in the operator's home
directory. Every check runs before anything is written; only the
repository's JSON files are read, none of its code is run. A refusal prints
`REFUSED <CODE> <detail>` on stderr and exits 2:

| Code | When |
| --- | --- |
| `INIT_ACTOR_SHAPE` | `--actor` is not an actor id (SPEC §3) |
| `INIT_NOT_A_REPOSITORY` | no `.warrant/store` with `trust.json`, `roles.json`, `roadmap.json` |
| `INIT_INSIDE_REPOSITORY` | the configuration, the state or the seed is inside the repository |
| `INIT_OUTSIDE_HOME` | the repository, configuration, state or seed is outside the operator's home directory |
| `INIT_OPERATIONS` | an operation is unknown or given twice, or none is given |
| `INIT_WORKSPACE_NAME` | the workspace name is not a handle (SPEC §10.1) |
| `INIT_CONFIG_EXISTS` | the configuration exists and `--force` is not given |
| `INIT_NO_SEED` | no file at `--seed` (none is created) |
| `INIT_SEED_SHAPE` | the seed is not a hex Ed25519 seed |
| `INIT_TRUST_SHAPE` | `roles.json` has a problem, or `trust.json` is not a bindings document |
| `INIT_ACTOR_NOT_PINNED` | `roles.json` gives the actor no key (reserved, collective, or no role) |
| `INIT_KEY_NOT_PINNED` | the seed's key is not the one `roles.json` pins for the actor |
| `INIT_NOT_ADMITTED` | `trust.json` admits no binding of the actor to that key |
| `INIT_ROADMAP_SHAPE` | `roadmap.json` has no list of actor ids as `results_accept_by` |
| `INIT_SYMLINK` | a path init would write, or one the server writes under the state, has a symlink (dangling ones too) on a component within the home directory |
| `INIT_PATH_CHANGED` | a component became a symlink or a non-directory after the check, before the write |

The paths checked before the first write are the configuration, its directory,
the state directory (given or the default `<config>-state`),
`<state>/<workspace>`, its `profile.json`, the directories the server creates
under it (`views`, `staging`, `imports`, `drafts`, `requests`, `exports`) and the
ones the views and the store create (`verdicts`, `replay-cache`): each by its
real path (in the home directory, outside the repository), with no symlink on it
below the home directory. They are then created and written by descriptors
opened from the home directory one component at a time with `O_NOFOLLOW`, so a
link planted between the check and the write is refused, not followed; a
process of the operator's own renaming a directory init has already opened is
not defended against (SPEC §10.8). When a configuration loads, a workspace whose
state tree holds a symlink is refused (`BAD_REQUEST`, `details.links`).

`tests/agent_repo_test.py` I01-I19, T01-T04, agent mutants A87-A96, A104-A108.

## The roadmap through the interface

`tools/roadmap.py` files obligations, closures and acceptances as ordinary
records (README.md, "The roadmap"). Through MCP they are `warrant_prepare`
then `warrant_commit` with these arguments; `<…>` is a slot, a whole-string
slot takes any JSON value. They file exactly the bytes `roadmap.py oblige`,
`done` and `accept` file (`tests/agent_repo_test.py` Q01 compares the stores
byte for byte and ROADMAP.md as bytes, and reads this block; Q02 runs it
through the stdio server):

- **oblige**: the goal ref is the `question` of `warrant_context` with
  `scope: "roadmap:G<n>"` (the formulation whose transition no accepted
  supersession replaced, if there are several); `owed_to` and `accept_by` are the lists of
  `.warrant/roadmap.json` (`roadmap.py check` refuses other terms as
  OBLIGATION_TERMS); `requires`/`serves` are duty ids.
- **done**: the closure of a duty you hold, its evidence a
  `warrant-roadmap/evidence@1` blob given with the prepare (`blob:0`, SPEC
  §10.5) naming the pull request and commits; `subject` is the merge commit or
  null.
- **accept**: the acceptor (`accept_by`) accepts exactly the closure's item:
  `transition` and `item` are a `closures` entry of the duty's capsule in
  `warrant_context` (verdict PENDING, `waiting_for` you). Read its evidence
  blob (`warrant_read kind=blob`) and review the work it names first.

The tool's own refusals (the holder files `done`, a duty with a pending
closure, an empty `--ref`, one-line texts) are not the interface's: through
MCP the agent keeps them itself, and `roadmap.py check` reads the result.

<!-- roadmap-recipe -->
```json
{
 "oblige": {"type": "duty", "body": {"holder": "<your actor>", "statement": "<one line>",
   "owed_to": "<owed_to of .warrant/roadmap.json>", "accept_by": "<accept_by of .warrant/roadmap.json>",
   "condition": {"attest": {}}, "requires": "<required duty ids>", "serves": "<served duty ids>",
   "answers": "<goal ref>"}},
 "done": {"type": "transition", "body": {"basis": "ATTESTED", "established": ["<what is now true, one line>"],
   "residual": ["the evidence blob names pull requests and commits; this record does not replay them"],
   "closes": [{"duty": "<duty id>", "act": "discharge", "evidence": ["blob:0"]}], "evidence": ["blob:0"],
   "subject": "<merge commit, hex40>"},
  "blobs": [{"schema": "warrant-roadmap/evidence@1", "duty": "<duty id>", "refs": ["<pull request>", "<commit>"]}]},
 "accept": {"type": "accept", "body": {"transition": "<closure transition id>", "item": "<item>"}}
}
```

## Operations

Every result is `{"agent_api", "adapter_id", "data", ...}`; a refusal is
`{"error": CODE, "message", ...details}` (SPEC §10.1, codes in §10.7). Members
marked `?` may be left out; the defaults are in §10.1 and in the section of
each operation.

| op | request | SPEC |
| --- | --- | --- |
| `workspace` | `{workspace?}` | §10.1 |
| `context` | `{workspace, actor?, use?, targets?:[id \| {id} \| {kind: duty\|transition, id}], limits?:{context_bytes}, scope?}`; with `scope` the questions of that scope, owned or not, come before the frontier | §10.2, §10.3 |
| `read` | `{workspace, view_token?, kind?: record\|blob\|context, target?, cursor?, max_bytes?}` or `{workspace, kind: draft\|operation, target}` | §10.2, §10.5 |
| `handoff` | `{op: export, view_token?, roots?, request_id?}` / `{op: inspect, package \| (manifest, payload, declaration?), expectation?, use?, actor?, targets?}` / `{op: import, staged_id, request_id?}` | §10.4 |
| `prepare` | `{workspace, type, body, based_on?: view_token, request_id?, blobs?: [JSON]}`; `accept` takes `{transition, item, evidence?, support?}`; `blob:<i>` in an evidence list is the id of `blobs[i]` | §10.5 |
| `commit` | `{workspace, draft_id}` | §10.5 |
| `compute` | `{workspace, op: provider\|term\|evaluate\|start\|resume\|cycle, ...hex64 addresses, expr?, expect_expr?, credit?, max_actions?, max_steps?, target?}`; `evaluate {expr, expect_expr?, credit? (10000), runtime? (book1)}` | §10.6 |
| `explain` | `{term}` | §10.1 |

Capsules, the boundary and `claims_to_be` are SPEC §10.2; the delivery
relations, expectations and promotion are §10.4; `use`, its decision id and
what holds it are §10.3.

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
`warrant_explain`. `warrant_context` takes `context_bytes` for
`limits.context_bytes`; `warrant_handoff` inspect takes the package in one
piece only, the split form stays in the Python API and the CLI. The server
reports `warrant-agent/1` as its version, and its instructions say where to
start and what a result does not establish. How a tool's arguments become a
request, how a refusal travels and what stdout carries are SPEC §10.1.

These choices were measured with fresh agents before and after
(`examples/mcp-first-contact/RESULTS.md`).

Measured with `mcp==2.3.0` (`tests/agent_mcp_test.py`, raw JSON-RPC client and
the SDK client):

| Client request | Negotiated |
| --- | --- |
| initialize 2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25 | the same revision |
| initialize with an unknown revision (1999-01-01) | 2025-11-25 (the server's latest handshake revision) |
| SDK `discover()` | 2026-07-28 |

## Checks

| Suite | Cases |
| --- | --- |
| `tests/agent_handoff_test.py` | H01-H17, V01-V12 |
| `tests/agent_write_test.py` | W01-W13 |
| `tests/agent_compute_test.py` | S01 end to end, exact acceptance retry/restart, S02-S04 negatives, S07, S08, S10, S11 (a contradicted receipt closes nothing; both capsules say why), S12 (evaluate) |
| `tests/agent_mcp_test.py` | M01-M05, cancellation, M06-M16 (overview, targets, closures, defaults, export roots, package inspect, read without a view, prepare defaults, explain, malformed stored records, every word a result carries has an explain entry) |
| `tests/agent_repo_test.py` | I01-I19 (`init`; I12-I19 symlinks, AMEND 1), T01-T04 (a repository's trust; a symlinked state tree), B01-B04 (`blobs`), Q03 (`scope`), Q01 (the roadmap recipe files the bytes `roadmap.py` files), Q02 (the recipe through the stdio server, DISCHARGED in ROADMAP.md) |
| `tests/agent_mutants.py` | A01-A64, A66-A108, each killed on its named case; the SPEC §10 claims cite them |
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

The other cost that grows with the store is authentication: every view and every
`prepare` checks each record's signature, about 150 µs a record, so 1.5 s at
10 000 records (F44). Since 2026-10-22 the workspace also keeps its own
**authentication verdicts** under `<state>/verdicts` (store.Verdicts, SPEC §3).
A verdict is keyed by the trust digest, the record id, the sha256 of the file's
bytes and the package's code identity; every file is still read and hashed on
every view, so a new, changed or removed file is seen, and each index line
carries a MAC under a random secret in that directory, so a forged, edited or
moved line is skipped and costs a fresh authentication. The `warrant` CLI takes
`--verdicts DIR` on `assess` and its read commands and on the signing commands
(`file`, `accept`, `observe`). `tests/store_index_test.py` V1-V17 and mutants
M430-M437 pin this down; `tools/bench_store.py` measures it.

## Not solved here

A set signed incomplete from the start, with the receiver's expectation on
exactly that set, MATCHes (H03, and step A4 of the acceptance run; SPEC §10.4). Delivery
MATCH means "the selected set arrived", nothing more: global completeness stays
UNATTESTED, and this layer does not resolve it.
