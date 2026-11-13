# Warrant Home

Install Warrant once for the machine, and keep one operator configuration under your home
directory. Each repository keeps only its own `.warrant/`.

```sh
pip install --pre warrant-graph          # or: uv tool install --prerelease allow warrant-graph
warrant home identity claude --seed ~/.warrant/claude.seed
warrant home add ~/Projects/warrant --signer claude
warrant home add ~/Projects/minds   --signer claude
warrant home                             # what is registered, and whether each trust binds its signer
warrant status --repo minds              # any registered repository, from any directory
warrant-agent-mcp                        # with no --config: one MCP server for every registered repository
```

## The file

`$WARRANT_HOME`, else `$XDG_CONFIG_HOME/warrant/home.json`, else `~/.config/warrant/home.json`:

```json
{"warrant": "warrant-home/1",
 "identities": {"claude": {"seed": "/Users/me/.warrant/claude.seed", "public": "fc176e4b…"}},
 "repositories": {"warrant": {"path": "/Users/me/Projects/warrant", "signer": "claude"},
                  "minds":   {"path": "/Users/me/Projects/minds",   "signer": "claude",
                              "operations": ["context", "read", "graph"]}}}
```

- **A repository** is a directory that holds `.warrant/v3.json`. It is registered under a plain
  name, which is also its workspace name for the agent interface. `signer` names the identity
  that files records there. `operations` (default: all) limits what the agent may do there.
- **An identity** is an actor and the path of its seed. `warrant home identity` reads the seed
  once, to record its public key. `warrant home` then says, for each repository, whether that
  repository's trust binds the key to the actor.

## Rules

1. **Each repository keeps its own `.warrant/`.**
   - Its records, blobs and receiver configuration (`v3.json`: trust and profile) live in it and
     are merged under its own rules.
   - Home lists where they are and who signs in each. It writes nothing into any of them and
     holds no record of its own.
2. **Home is the operator's.**
   - It is never read from a repository, and no request names it.
   - A Home that is a link, or one other users may write, is refused.
   - It is written whole with mode 0600, in a 0700 directory.
3. **A seed is named, never copied.**
   - It never lies inside a registered repository, whichever is registered first.
   - It is refused at registration when others may read or write it.
4. **`--repo NAME` and `--store DIR` exclude each other.**
   - With neither, a command uses the nearest `.warrant/` upward from the current directory.
   - With no `--trust` or `--profile`, a command uses that store's `v3.json`.

## The agent

`warrant-agent` and `warrant-agent-mcp` without `--config` read Home. Each registered repository
becomes one workspace: it uses that repository's trust and profile, signs as its signer with the
identity's seed, and offers its operations. An explicit `--config` file works as before
(docs/AGENT.md).

A review worktree needs no configuration of its own: `--repo DIR --actor A` serves that one
checkout, held in memory, with the checks `warrant-agent-mcp init` makes. The seed is `--seed`, or
else Home's identity `A`. Nothing is written: no file per pull request.

```sh
warrant-agent-mcp --repo ~/Projects/.worktrees/codex-review/238-0d1c71bc61d8 --actor codex
```

## One read across the repositories

`warrant across` and the agent's `across` (MCP `warrant_across`) answer over every registered
repository. Output is JSON, within a byte budget, with no document generated.

```sh
warrant across                   # stores: each store's lineages by schema and state
warrant across actor claude      # its records everywhere, under each store's keys for the name
warrant across open              # goals and obligations a store reads as open
warrant across challenges        # challenges standing in some store, and the voices no store counts (uncounted)
warrant across rests HASH        # what rests on a hash, across stores (an id, a prefix of 8+, or a citation)
```

Each of these takes `--schema NAME`, `--offset N` and `--max-bytes N`.

- **Trust is never merged.** Each store is assessed alone, under its own `v3.json`. A node is one
  record: its envelope (`kind`, `actor`, `at`, `schema`, `lineage`, `target`, `refs`, `requires`; these
  are the edges, and the id covers them) and `in`, one row per store holding it, with that store's
  name and that store's verdict. The same record can read `MET` in one row and `PENDING` in another.
  One store's verdict never counts for another: a guard requiring a lineage closed only elsewhere stays
  `PENDING`.
- **An actor is a name under a store's trust.** `actor` lists what each store admits as that name's,
  and each store's keys for it. A record a store rejects reads `rejected` in that store's row.
- **A store that cannot be read is named** under `unavailable`, with the reason, and the others still
  answer. A store appears only if it is registered, and one whose `operations` leave out `graph` is named
  but not read: a lens's private store stays out until its operator registers it.
- **Nothing from a repository runs.** The read takes `.warrant/records.jsonl`, `.warrant/blobs/` and
  `.warrant/v3.json`, as data, and the Git trees and history the G14 gate compares (warrant.drift): a
  claim whose acceptances all name other bytes reads `STALE` here as in `context` and `graph`. It writes
  nothing. Record text is data too (`untrusted`).
- **`no_schema`, not zero.** `open` reads `goal@1` and `obligation@1`. A store that counts neither says so.
- **Paged, never cut.** `total`, `offset` and `next` say what a page holds. Each call reads and assesses
  every store again; nothing is cached.

The answer reads a checkout's working tree: a checkout behind its remote answers as it stands. Each
store's `root` names the bytes read and `as_of` the latest time a record there claims, and the lens
binds the tree the gate read; the answer names no commit.

### Citing a record in another store

A record's id names it wherever it lies, so an edge to a record in another store is the same edge as
any other: **`refs` carries the bare id**, and the engine admits it unchanged. A record cited that way
makes no store's verdict depend on another's. To write down where the citer saw it, use the citation
`<store>:<id>` (`s0fractal/time-lab:d905d71b…`, the full id, where `<store>` is the name `v3.json` gives as
`repository`) in a body field of free strings, such as an obligation's `refs` member: it is a locator
for a reader, never an edge, and it narrows no answer, so it survives a rename: the checkout
`sokol-core` names itself `s0fractal/interdict-mesh`. `rests` also takes it as a target.

A Git commit id does not fit `refs`, which holds hex64 only. A pin of a file at a commit stays in a
body, and the graph has no edge for it.

Read across stores, a reference some store holding the citing record does not hold is listed under the
node's `foreign`:

- `ELSEWHERE`, with `held_in`: the stores read here that hold it. Each row there is that store's own.
- `UNAVAILABLE`: no store read here holds it. It does not say the record does not exist: a store not
  registered or not readable may hold it, and completeness stays `UNATTESTED`.

A single store's graph reads such a node as `{"kind": "unavailable"}`.

## Not yet

These are the next steps of the plan:

- **The waker.** It will read its repositories from Home.
- **A read of one record by its hash from Git history or another machine.** `across` resolves hashes
  over the registered stores' current files only.
- **A resolver for hashes cited across repositories.** Each cited hash will get one of four
  states, `PRESENT`, `RESOLVED`, `LOCATED` or `MISSING`, from local stores and Git history only.
