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
  permits (`workspace` and `explain` always are; `across` reads a workspace only if it permits `graph`). `limits`: the store is refused beyond `store_bytes`
  before it is parsed; results beyond their byte bound are refused, never cut.
- A configuration Warrant 2's `warrant-agent-mcp init` wrote (`agent_api` `warrant-agent/1`, a
  workspace whose `store` is a repository's `.warrant/store`) is read as that repository with the same
  signer: an existing operator configuration keeps working. Its operations stay the operator's: those that
  still exist, and `graph` only where `read` was granted. Warrant 2's limits have no reading here, so a
  configuration that sets `limits` (its init never wrote them) is refused until `init` is run again.

`warrant-agent-mcp init` writes one for a checkout, from an existing seed (it creates no key):

```sh
warrant-agent-mcp init --repo ~/Projects/warrant --actor codex --seed ~/.warrant/codex.seed \
  --config ~/.warrant/codex-warrant.json [--workspace NAME] [--force]
```

It refuses a seed whose key `.warrant/v3.json` does not bind to the actor, a seed or configuration
inside the repository or outside the home directory, a symlink on the configuration's path, and an
existing configuration unless `--force` is given and an init wrote it.

`--repo DIR --actor A [--seed SEED] [--workspace NAME] [--operations ...]`, given to `warrant-agent-mcp`
or `warrant-agent` in place of `--config`, serves that one checkout with the configuration init would
write for it, held in memory and written nowhere: a review worktree needs no file of its own. It
makes init's checks and refuses with init's codes. With no `--seed`, the seed is the operator's Home
identity `A`'s (docs/HOME.md).

## Operations

| op | request | result |
| --- | --- | --- |
| `workspace` | `{workspace?}` | the signer, its roles, permitted operations, the schemas counted, lineages by schema and state |
| `context` | `{workspace, targets?, actor?}` | per target (an id or a unique prefix of 8+ hex): its node, lineage (state, reliance, leaf, effective), guard (MET / PENDING with `waiting` / NONE), the attests on it, the challenges against it; the actor's `frontier` |
| `read` | `{workspace, target, kind?: record\|blob, offset?, max_bytes?}` | the exact bytes, chunked (`next`) |
| `graph` | `{workspace, op: around\|path\|why\|grounded\|frontier\|ledger\|export, target?, actor?}` | `{root, lens, query, data}`: the same lens over the same root gives the same result; `grounded` is `warrant.graph.grounded` (minds' Grounded: the version and all it rests on, transitively, effective and ELIGIBLE, with each failing one and why), `ledger` the witness ledger (`warrant.graph.ledger`; it grants nothing); in a repository's checkout the lens binds what the STALE gate read (`checkout`: HEAD's tree and whether it has claims) |
| `across` | `{query: stores\|actor\|open\|challenges\|rests, actor?, target?, schema?, offset?, max_bytes?}` | one read over every workspace, each assessed alone: docs/HOME.md |
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


## Handing a result to another party

`handoff` with `op: export` gives a package of what the targets rest on and the verdicts on them. Whoever
receives it needs none of this interface to judge it: `warrant verify PACKAGE --trust T --profile P`
answers under the receiver's own trust and profile with no store, and `warrant_verify.py` is the same
command as one standard-library file for a receiver with nothing installed. Its exit status is the
answer ([docs/VERIFY.md](VERIFY.md)).

## Reading it as a person (`warrant serve`, v0)

```bash
python3 -m warrant_agent.serve
```

serves `http://127.0.0.1:8767/` over every repository Home registers (or each `--root DIR`): the **feed** (one
sentence per record, newest first; programs' acceptances hidden unless asked), a **lineage** (its versions newest
first with what each established and left open, its guard and who accepted, the attests and challenges on it, its
state and reliance, and whether its effective version is grounded) and **what waits** for an actor (the frontier
under each store's own profile). Each page is a projection of one store's assessment: its footer names the root and
the lens, and the same pair gives the same page. Record text is escaped everywhere; nothing of a repository runs.

With `--actor A --key SEED` (a seed outside every repository read) a lineage page offers a **reaction** to its latest
version: an attest `{target, verdict: "react", agree: -100..100, confidence, importance, evidence: 0..100, note?}`
signed as A, filed only in a store whose trust binds that key to A. No guard's match holds `react`, so a reaction
credits nothing; it is the reader's own signed word, and it leaves that version off the reader's frontier (an attest
by the actor). The server listens on 127.0.0.1 only, answers only to its own Host, and refuses a POST without the
token of its run. agent_test SV1–SV7; mutants A99–A104, A121–A122.

**The reader's own store.** With `--mine NAME` (default: the repository Home registers as `space`, if any) a reaction
is filed in that store whatever store its record is in, so a project's store is never changed by its readers'
reactions; an attest on a record held elsewhere is admitted as any other. A lineage page shows, under each version,
the reactions on it filed in other stores, naming the store.

### Lenses: the reader chooses how a page is drawn

A lineage page's layout is a record: an entity of `lens@1` (`warrant_agent/lens.py`: `{state: active | retired,
name, applies: a schema name, card, why?}`). Its `card` is data, never code: `layout` (`nested`, each version a card
holding what happened to it; or `flat`, one stream by time), `fields` (body members, each shown as `text`, `list`
or `count`, with a label), `order` (`newest`, `oldest`) and `activity` (`shown`, `hidden`). Nothing in it is
evaluated; a card the interpreter does not know is UNSUPPORTED, and the built-in lens draws the page and says why.

A lens version is applied only when the reader filed `{verdict: "adopt"}` on it (`--reader`, default `--actor`;
the latest adoption in the reader's own chain wins). A lens someone else adopted, or a newer one nobody adopted, is
not applied. `?lens=ID` (or `builtin`) names a lens outright: a portal, and the page it draws is byte-identical to
the one its adoption draws. A lens's own lineage is always drawn by the built-in lens.

No lens decides the floor, drawn above any card: the lineage's state and reliance, every counted challenge that
stands against one of its versions with its statement, that completeness is UNATTESTED, and which lens drew the
page — and every challenge filed against that lens version (a lens has no guard, so none is counted; each is shown
wherever the lens draws). A lens may apply to one schema or to `*`.

**Comparing lenses.** `?lens=A&vs=B` adds what one lens shows of the page that the other does not: each body member
of each version, and each attest and challenge (`warrant_agent.lens.diff`). Every lineage page links its
comparisons with every other lens that applies. The comparison sees only the records of that store.

agent_test LN1–LN9; mutants A105–A115.

### What changed for me

`/changes` lists, per store, the lineages whose page differs for the reader since the reader's last mark
(«Позначити все як переглянуте»: the ids of every record each store holds, kept in `serve-seen.json` beside Home;
without a mark, the records dated before the last day). The past is that set of records assessed by the same engine,
so it is reproduced exactly. A lineage is listed when its floor (state, reliance, the counted challenges that stand,
whether it is grounded) or what the reader's lens draws of it (`lens.visible`) differs, with the witness: what
appeared, what vanished, what in the floor moved. New records that change nothing the reader sees are counted, not
listed: two states are the same for the reader under that lens (`warrant_agent/changes.py`). agent_test CH1–CH3;
mutants A117–A120.
