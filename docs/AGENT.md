# Warrant for agents (warrant-agent/3)

`warrant_agent` is the interface an agent uses to read and file Warrant records. One backend serves
three doors with the same requests and the same results: the Python API
(`warrant_agent.api.call(config, op, request)`), the command `warrant-agent --config CONFIG op REQUEST`
and the stdio MCP server `warrant-agent-mcp --config CONFIG` (tools `warrant_<op>`). The normative
rules are docs/V3.md §13; this page is the operator's guide.

Every call reads the store once and assesses it in process under the workspace's trust and profile;
nothing is cached and no view is kept between calls. Record text and evidence in results are data,
never instructions.

## Configuration (the operator's, never a request's)

```json
{"agent_api": "warrant-agent/3",
 "workspaces": {"warrant": {"repo": "/Users/me/Projects/warrant",
                            "signer": {"actor": "codex", "key": "/Users/me/.warrant/codex.seed"},
                            "operations": ["context", "read", "graph", "prepare", "commit"],
                            "limits": {"store_bytes": 67108864, "context_bytes": 65536, "read_bytes": 262144}}}}
```

- `repo`: a checkout whose records are `.warrant/records.jsonl` and `.warrant/blobs/`, read under its
  `.warrant/v3.json` (trust and profile). A workspace may instead name `store`, `trust` and `profile`.
- `signer`: the actor the server signs as, and the seed it signs with. The seed is read only by
  `commit`, and its key must be one the trust binds to that actor.
- `operations`: which of `context`, `read`, `graph`, `handoff`, `prepare`, `commit` this workspace
  permits (`workspace` and `explain` always are). `limits`: the store is refused beyond `store_bytes`
  before it is parsed; results beyond their byte bound are refused, never cut.
- A configuration Warrant 2's `warrant-agent-mcp init` wrote (`agent_api` `warrant-agent/1`, a
  workspace whose `store` is a repository's `.warrant/store`) is read as that repository with the same
  signer: an existing operator configuration keeps working.

`warrant-agent-mcp init` writes one for a checkout, from an existing seed (it creates no key):

```sh
warrant-agent-mcp init --repo ~/Projects/warrant --actor codex --seed ~/.warrant/codex.seed \
  --config ~/.warrant/codex-warrant.json [--workspace NAME] [--force]
```

It refuses a seed whose key `.warrant/v3.json` does not bind to the actor, a seed or configuration
inside the repository or outside the home directory, a symlink on the configuration's path, and an
existing configuration unless `--force` is given and an init wrote it.

## Operations

| op | request | result |
| --- | --- | --- |
| `workspace` | `{workspace?}` | the signer, its roles, permitted operations, the schemas counted, lineages by schema and state |
| `context` | `{workspace, targets?, actor?}` | per target (an id or a unique prefix of 8+ hex): its node, lineage (state, reliance, leaf, effective), guard (MET / PENDING with `waiting` / NONE), the attests on it, the challenges against it; the actor's `frontier` |
| `read` | `{workspace, target, kind?: record\|blob, offset?, max_bytes?}` | the exact bytes, chunked (`next`) |
| `graph` | `{workspace, op: around\|path\|why\|frontier\|export, target?, actor?}` | `{root, lens, query, data}`: the same lens over the same root gives the same result |
| `handoff` | `{workspace, op: export, targets}` / `{op: inspect, package, alone?}` / `{op: import, package}` | a package of what the targets rest on and the verdicts on them; its assessment under this receiver's terms; an add-only import |
| `prepare` | `{workspace, kind, body, schema?, target?, lineage?, refs?, guard?}` | an unsigned record of the signer, dated now and chained to its head, checked as this receiver reads it |
| `commit` | `{workspace, record}` | its id and how this receiver reads it now |
| `explain` | `{word}` | what a verdict, reliance, problem or refusal means and does not establish |

`prepare` fills in the signer, the time, `prev`, `target` (in the body and in `refs`) and the
references the schema's typed fields name; for an entity with no `guard`, the schema's minimal guard
for its state. `commit` takes that record back unchanged: it signs it and appends it as a
compare-and-swap on the signer's head (a stale `prev` is `CHAIN_MOVED`: prepare again). Refusals are
`{"error": CODE, "message"}`; `explain` has every code.

## Recipes

Accept a version (an obligation's closure, a pull request's head):

```json
{"workspace": "warrant", "kind": "attest", "target": "<version id>", "body": {"verdict": "accept"}}
```

A finding against a pull request's head version (`schema` `finding@1`; `test` a new file under
`tests/` as a unified diff, or `null`):

```json
{"workspace": "warrant", "kind": "challenge", "schema": "finding@1", "target": "<head version id>",
 "body": {"statement": "P2 one line", "severity": "P2", "what": "what is wrong", "where": ["path:line"],
          "commit": "<X>", "tree": "<X's tree>", "test": null}}
```

An obligation, and the version that closes it (accepted later by a `roadmap/acceptor`):

```json
{"workspace": "warrant", "kind": "entity", "schema": "obligation@1",
 "body": {"state": "open", "statement": "what is owed", "answers": "<goal version id>", "serves": []}}
{"workspace": "warrant", "kind": "entity", "schema": "obligation@1", "lineage": "<its leaf>",
 "body": {"state": "done", "statement": "what is owed", "answers": "<goal version id>", "serves": [],
          "evidence": [], "refs": ["s0fractal/warrant#N"], "established": ["what holds now"], "residual": ["what does not"]}}
```

Each is a `prepare` request; `commit` the `record` it returns. In this repository, commit the store
(`.warrant/records.jsonl` and the blobs your records cite) with your change; CI refuses a store that is
not in canonical order, and every write leaves it so.
