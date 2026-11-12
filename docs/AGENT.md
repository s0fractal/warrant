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

**A view** («Прочитав»): `{target, verdict: "seen", lens, root}`, the reader's signed word that they saw a version
under that lens at that root of its store, filed in the reader's own store like a reaction. It credits nothing (no
guard's match holds `seen`). The floor counts who saw apart from who spoke ("бачили: N · заперечень: M"), so a
silence after views reads apart from a silence with no reader, and tells the reader which version they saw last
(SV9). Views are private while the reader's store is unpublished, and counted only from keys some store's trust
binds.

**What the page rests on outside, and how you saw it then.** «Обґрунтоване» names the records the lineage rests on
that this store does not hold (grounded's `outside`), unchecked. Beside «ти бачив версію N з M» a link rebuilds the page
as the reader's last view saw it: the records dated no later than that view, assessed by the same engine, under the
lens the view names; the root the view recorded decides whether it reads «відтворено точно» or «наближено» (filers'
dates are their own word). A fresh and a warmed server render every page byte for byte the same. agent_test TL1–TL3.

**What a page binds and what it admits it cannot see** (Codex's observer pack, 2026-11-11). A page's lens names the
whole interpreter (every module of `warrant_agent`, by bytes) and, for every other store it read, that store's root,
trust and profile. Its floor says what the reader's lens leaves out of it (counted against the built-in view) and which
stores the server could not read; `/changes` says when the reader's lens changed since the mark. No page runs a
script: the policy is `script-src 'none'`. An adoption is filed in the reader's own store like any observation, so a
reader adopts a lens of a store it cannot write to. agent_test AU1–AU4, LN10.

**The reader's own store.** With `--mine NAME` (default: the repository Home registers as `space`, if any) a reaction
is filed in that store whatever store its record is in, so a project's store is never changed by its readers'
reactions; an attest on a record held elsewhere is admitted as any other. A lineage page shows, under each version,
the reactions on it filed in other stores, naming the store. A `--mine` store that is not read refuses the reaction:
nothing is filed anywhere (fail closed; agent_test CH6).

**A page is a function of every store it reads.** The lens chosen, the reactions filed elsewhere and the challenges
against that lens come from other stores, so a lineage page's lens names their roots (`with`), and its footer counts
them (CH4). `/changes` reads each state with that state's reactions from other stores, and a new reaction elsewhere
lists the lineage it points at (CH5). A lens comparison also names how two lenses draw what both show: layout, order
of versions and of members, labels and forms (`lens.presentation`, CH7).

### Two general forms under every page

Everything a reader does or reads here is one of two forms; a new idea is one more instance, not one more code path.

**An observation** (`warrant_agent/observe.py`): an observer that signs what it observed becomes a witness. A reaction
(`react`), a view (`seen`) and an adoption of a lens (`adopt`) are one record, `{target, verdict: KIND, ...}`, that no
guard's match holds, so none credits anything; each kind names its fields and where it is filed (the reader's own
store, or the store holding the record). A new kind is one entry in `KINDS`.

**A difference of views** (`warrant_agent/view.py`): what a reader sees of a lineage is a view (what the lens draws and
the floor); two views are compared by `difference` (what appeared, what vanished, what in the floor moved), and two
states are the same for the reader when nothing differs. Each page varies one thing:

| varied | the two views | page |
|---|---|---|
| time | the store as the reader last marked it, and now | `/changes` |
| lens | one state, two cards | `?lens=A&vs=B` |
| sources | the authors' own records only, and all | the floor's «джерела» |
| records | the store without some records, and now | `/whatif`, the moves on `/fragile` |

`/whatif` («Що було б») follows minds' `what_if` (vars1.py): a store without its challenges, or without one actor's
records, is assessed by the same engine on a candidate (nothing filed, nothing moved); every lineage whose view changes
is named with its witness, from the hypothesis to the store as it is, and equal consequences give an equal digest
(agent_test WI1–WI3). `/fragile` shows, for each lineage, what its objections move (without them → with them).

### Before lenses: what already exists, and what is ours

Separating data from its presentation is not new, and neither is signing claims. Read this before the lenses below,
so the emphasis falls where the novelty is.

| What exists | What it already does | What we take from it |
|---|---|---|
| **Solid** (W3C Solid CG) | data in stores the user controls, applications apart from storage, access rules per resource | the reader's own store (`space`, `--mine`): a reader's records live with the reader, not with the project |
| **AT Protocol** (Bluesky) | per-user signed repositories of typed records (Lexicons); independent App Views index and present them; users pick custom feeds | records travel without HTML/CSS/JS; a reader chooses how they are selected and ordered |
| **Verifiable Credentials 2.0** (W3C) | signed statements of an issuer about a subject, checked by a verifier | a record is a signed statement whose author is checked by key, never by the host |
| **PROV-O** (W3C) | provenance as entities, activities and agents | every record names its author, its time and what it rests on (`refs`, lineage) |
| **WoT Thing Description** (W3C) | the actions a thing offers, their inputs and effects, apart from any UI | an action can be described as data; describing it grants no right to run it |

What none of them does, and the combination this repository builds:

1. **State is the receiver's, not the record's.** The same records are ELIGIBLE for one receiver and PENDING or
   CHALLENGED for another, each under its own trust and profile (docs/V3.md); trust is never merged across stores. A
   credential is valid or not; here a lineage is relied on *by someone*.
2. **Objection is first-class.** A challenge is a record, counted or not by the receiver's rules; a reproduced
   counterexample (a replay) refutes, and the witness ledger credits whoever found it (`warrant.graph.ledger`).
3. **A lens is a record, and so is choosing it.** A feed or an App View is a service someone runs; a lens here is
   declarative data, applied only when the reader adopted it, reproducible (`root` + `lens`), comparable with another
   (what each shows, how each draws) and open to challenge like any claim.
4. **A floor no lens decides.** Whatever the lens, the page shows the state, the reliance, every counted challenge that
   stands, who stands behind the lineage (a single voice is named), and that completeness is UNATTESTED.
5. **Incompleteness is shown, not hidden.** A view is a signed record too, so silence after many views reads apart
   from silence with no reader.
6. **Evidence executes.** A normative sentence of the specification is a claim backed by test cases and mutants a
   checker re-runs (docs/REPOSITORY.md).

None of this asks anyone to leave Solid, the AT Protocol or W3C credentials: an adapter can carry their records in,
keeping who signed what; this layer records what was attested, objected to and how it was seen.

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
page, who stands behind the lineage (its authors, every other actor who filed on it here or in another store read,
the number of stores; «лише автор» when nobody else spoke: completeness cannot be shown, a single voice can, SV8),
and every challenge filed against that lens version (a lens has no guard, so none is counted; each is shown
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

### Maps (`/s/STORE/ID`, `warrant_agent/scene.py`)

A lineage drawn as a map under the reader's lens: its versions left to right in time, what was filed on each below
it (reactions from other stores included), each node a portal to its record's page. A lens's card may hold a
`scene` binding each channel to a named field from a fixed list (`x`: time | order; `y`: version | kind; `size`:
standing | attests | none; `color`: reliance | kind | actor; `shape`: kind | none); the legend is derived from the
bindings, and the layout is deterministic (no force, no chance), so the same page gives the same SVG and "why is this
here" is answered by the legend. The SVG is generated from data: no script, no external resource, every text escaped.

No scene decides the floor: every node carries its kind's glyph (◆ ✓ ✗: meaning is never colour alone), a counted
challenge that stands is never smaller than what it stands against, the legend is always drawn, and nodes folded
away by the budget (300) are named with their count. `?vs=` sets a second lens's map beside it and names how many
nodes moved and which bindings differ; the lens comparison names scene bindings too. agent_test SC1–SC7; mutants
A128–A133.

### A page's contract (`warrant_agent/contract.py`)

Each page names what it promises and is checked against it as it is drawn; a broken promise is named on the page
and replayed by `python -m warrant_agent.contract` (exit 1). The promise is computed from the records, not from the
renderer's own list. The lineage page keeps what its lens promises (each declared member that has a value, the
activity it shows) and the floor (KC1–KC3). The map (`--map`) draws every node of the lineage or names how many it
folded, over the same floor; beside a second lens's map each is read alone (MC1–MC3). The feed (`--feed [STORE] [--actor A] [--machines]`) draws the newest 300
records of its scope and names, with how many, what it leaves out: records of automatic actors (unless asked),
migration records, those past the limit, and every store it could not read; a count it names where nothing
was left out is a breach too (FC1–FC3). What a kept contract does not
establish: that the marks are where a reader looks, or that the page reads well.

### Fragile popularity (`/fragile`, `warrant_agent/fragile.py`)

The lineages someone objected to, the most attended first. A lineage's attention is how many actors other than its
authors signed that they saw it, accepted it or reacted to it (here and in the other stores read; a challenge itself is
no attention). Beside it, each challenge and its fate: counted or not, standing, reproduced by a replayer on its own
target. One reproduced counterexample outweighs any number of agreements: the page sets them side by side and never
adds them into one score.

«Хто вказав»: whoever filed a challenge reproduced on its own target, or counted and standing, is named with each
lineage it held against and that lineage's attention. It is recognition read from the records, not a rank or a reward:
no guard reads it, an objection nobody reproduced and no role counts is shown and not credited, and attention counts
only keys some store's trust binds. agent_test FR1–FR3; mutants A140–A143.

### For me: other stores, my rules (`/overlay`, `warrant_agent/overlay.py`)

A publisher's store holds a claim; another store holds a challenge the publisher never took in; a third, a replay that
reproduces it. Each store alone is assessed under its own receiver, and that verdict stands. The reader composes the
stores it chooses (`?store=X&with=A,B`, default every store read) and assesses the union under its own rules, the trust
and profile of its own store (`--mine`): `assess(X ∪ O_R, T_R, P_R)`, beside `assess(X, T_X, P_X)`, never in its place.
The page lists each lineage of X that reads otherwise for the reader (X's verdict → the reader's, with the witness) and
the overlay's identity (each store's records, the trust, the profile, the engine).

The reader's roles are the reader's alone: no source's profile is merged. A key binding is admitted only as the
reader's own or as every chosen source naming that actor agrees; a binding they disagree on is named and not admitted
(an impostor store cannot sign as another actor). The page names the roles X's guards ask that the reader's rules give
nobody. What is in no chosen store is not counted: the overlay is honest, not complete. agent_test OV1–OV5; mutants
A155–A161.

### The commons: «фе» from an agent with no rights (`warrant_agent/commons.py`)

```bash
python3 -m warrant_agent.commons say RECORD_ID "why it is wrong"
```

An agent needs no key any store binds, no role and no part in the record it objects to. Its identity is its own key
(`key:<public key>`, docs/V3.md §5): the signature verifies under that key whether or not any trust binds it, so nobody
can sign in its name and nobody's admission is needed; only a challenge may be named so (an acceptance under a key's own
name is rejected). The agent names its key (`--as NAME`); its seed is `~/.config/warrant/commons/NAME.seed` (0600, made on
first use), so no argument can point it at another file; the
commons store (`~/Projects/commons`) trusts nobody and gives nobody a role: it holds voices, never a verdict.

Every lineage page shows the challenges filed against it in other stores (the commons among them) as voices from
outside, which that store's rules do not count; the floor counts them among those who spoke, `/fragile` lists them
uncounted, and a reader's overlay counts one only when the reader's own rules do, by a replayer the reader trusts
reproducing it. No voice moves a store's verdict; no store can keep a voice off the pages of the readers who read the
commons. agent_test CM1–CM5; mutants A162–A166.
