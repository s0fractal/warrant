# The repository

This repository builds and checks Warrant with Warrant. Its own records (the specification's claims,
the roadmap, the pull request reviews) are Warrant 3 records in `.warrant/records.jsonl` and
`.warrant/blobs/`, assessed under the repository's receiver configuration `.warrant/v3.json` (the
trust: which keys are whose; the profile: who holds which role; both owner paths). None of this
machinery ships in the package (`tests/boundary_test.py`).

## Layout

| Path | What |
| --- | --- |
| `warrant/` | the core: records, store, engine, CLI (docs/V3.md) |
| `warrant_agent/` | the agent interface: Python API, CLI, stdio MCP (AGENT.md, docs/V3.md §13) |
| `warrant_pilot/` | the proof-space pilot, G9 (PILOT.md); not in the wheel |
| `.warrant/records.jsonl`, `.warrant/blobs/` | the repository's records; `merge=union -text` (`.gitattributes`) |
| `.warrant/v3.json` | trust and profile (owner path) |
| `.warrant/merge.json` | the merge gate's configuration and the owner paths (owner path) |
| `.warrant/v3/schema-accepts.jsonl` | Codex's acceptances of the bootstrap schemas, as committed at #218 |
| `tools/repo.py` | what the tools share: the store and configuration, filing as an actor, a checker's identity |
| `tools/claims.py` | the spec's claims: check, view, file, retire, the claims checker |
| `tools/roadmap.py` | goals and obligations: view, due, check, oblige, close |
| `tools/review.py` | the review loop: open, head, merged, due, gate, the replay checker, verify, view |
| `tools/gate.py` | the merge predicate and the gate's GitHub side (owner path) |
| `tools/graph.py` | queries over the record graph (around, path, why, frontier, impact) and the views |
| `tests/mutants.py` | every mutant, the cases it must fail, shards and their merge |
| `integrations/codex-plugin/` | the Codex plugin: the review skill, the MCP launcher, the review waker |

## Installing from a checkout

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[mcp]"
```

The tools run from the checkout with any Python ≥ 3.10 that has `cryptography`
(`python3 tools/claims.py check`).

## Checks

What CI runs (`.github/workflows/ci.yml`), each from the checkout:

```sh
python3 tests/core_test.py            # the engine, store and records (docs/V3.md §§2-10)
python3 tests/agent_test.py           # the agent interface (§13); M01 needs the MCP SDK
python3 tests/gate_test.py            # the merge gate (§14)
python3 tests/tools_test.py           # claims, review replay, roadmap (§14)
python3 tests/pilot_test.py           # the pilot (needs sigma-glyph 0.8.0)
python3 tests/boundary_test.py        # the public surface; python3 tests/quickstart_test.py: QUICKSTART.md
python3 integrations/codex-plugin/test_plugin.py
python3 tests/mutants.py --shard 1/4 --matrix part-1.json    # ... 4/4, then --merge
python3 tools/claims.py check && python3 tools/roadmap.py check && python3 tools/pilot.py check
python3 tools/review.py verify --base <base commit>          # replays new since the base, re-executed
python3 tools/graph.py views --check                         # build/views/*.md, deterministic
```

A pull request's store must be in canonical order (every write leaves it so; `python3 -m warrant fmt
--store .warrant` restores it after a merge), reject no line under `.warrant/v3.json`, and have every
schema at its quorum.

## The specification's claims

Each normative sentence of docs/V3.md is a `claim@1` lineage filed by `claude`: the sentence verbatim,
its section, its witnesses (`file_test:CASE`, a case the test prints) and its mutants. `tools/claims.py
check` never parses the spec: the records say where they are and the spec must hold their words.

To change a rule: change the sentence and the code, add or retarget the cases and mutants, then file
the claim's new version (`tools/claims.py file --from FILE.json --actor claude --key SEED`, where FILE
lists `{id, section, text, witnesses, mutants}`; an unchanged claim files nothing). A claim filed
`backed` waits for the claims checker: `python3 tools/claims.py replay --key -` on a clean checkout
runs every waiting claim's witnesses and mutants and accepts those that held, as `checker
sha256:<identity>` (`tools/claims.py identity`), whose key `.warrant/v3.json` must bind.

The Warrant 2 claims (source SPEC.md) are retired lineages: history, never deleted.

## The roadmap

Goals (`goal@1`, keys G1..G12) and the obligations that answer them (`obligation@1`) are records.
`python3 tools/roadmap.py view` renders them; `oblige` files an obligation and `close` its `done`
version, which a `roadmap/acceptor` (codex) accepts. `due --actor codex` is what the review waker
reads: the leaves waiting only for that actor's attest.

## Reviews as records

A pull request is a `pr-head@1` lineage: `python3 tools/review.py open --pr N --title T` files its
root, `head --pr N` a version naming the commit to review (the `HEAD` of the checkout) and its tree.
The reviewer accepts the head version or files `finding@1` challenges against it, through MCP
(integrations/codex-plugin/skills/warrant-review/SKILL.md). The review replay checker runs each
finding's test at each later head and attests the result; `review.py verify` in CI re-executes those
new since the base. After a merge, `review.py merged --pr N --merge SHA` files the observation.

### Merging on acceptance, and waking the reviewer

`.github/workflows/merge-on-acceptance.yml` runs master's `tools/review.py gate` (tools/gate.py): it
merges a pull request whose head version a `pr/acceptor` accepted, whose tail after the reviewed
commit is record lines and blobs only, whose required checks are green, and which changes no owner
path (docs/V3.md §14). Holds: the label `hold`, the repository variable `WARRANT_MERGE_GATE=hold`.

The review waker (integrations/codex-plugin/waker/waker.py, launchd, every five minutes) runs the
base tree's `review.py due` and `roadmap.py due --actor codex`, replays findings with the review
replay checker's seed (sandboxed, seed on standard input), and wakes Codex once per due head or
roadmap version. `python3 integrations/codex-plugin/install.py` installs the plugin and the waker
(the owner runs it).
