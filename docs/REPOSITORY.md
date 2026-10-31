# The repository

This repository builds and checks Warrant with Warrant. Its own records (the specification's claims,
the roadmap, the pull request reviews) are Warrant 3 records in `.warrant/records.jsonl` and
`.warrant/blobs/`, assessed under the repository's receiver configuration `.warrant/v3.json` (the
trust: which keys are whose; the profile: who holds which role; both owner paths). The review loop's
commands ship in the package (`warrant.review`, `warrant.gate`, `warrant.claims`, `warrant.roadmap`),
so that another repository runs them on its own `.warrant/` ([below](#the-review-loop-in-another-repository));
this repository's records, its `tools/`, the waker and the tests do not (`tests/boundary_test.py`).

## Layout

| Path | What |
| --- | --- |
| `warrant/` | the core: records, store, engine, CLI (docs/V3.md); and the review loop's commands below |
| `warrant/repo.py` | what the commands share: the repository they run on (`--root`, else the Git checkout around the current directory), its store and configuration, filing as an actor, the code and environment a checker's attest names |
| `warrant/claims.py` | a specification's claims (`.warrant/claims.json` names the spec, the witness files and the mutant harness): check, view, file, retire, the claims checker |
| `warrant/roadmap.py` | goals and obligations: view, due, check, oblige, close |
| `warrant/review.py` | the review loop: open, head, merged, due, gate, the replay checker, verify, view |
| `warrant/gate.py` | the merge predicate and the gate's GitHub side (owner path) |
| `warrant/cli.py`, `warrant/graph.py` | the one command `warrant` (the core's verbs, `status`, and `review`, `gate`, `claims`, `roadmap`), and the queries over a report's graph that `status`, the agent's `graph` and `tools/graph.py` share |
| `warrant_agent/` | the agent interface: Python API, CLI, stdio MCP (docs/AGENT.md, docs/V3.md §13) |
| `warrant_pilot/` | the proof-space pilot, G9 (docs/PILOT.md); not in the wheel |
| `.warrant/records.jsonl`, `.warrant/blobs/` | the repository's records; `merge=union -text` (`.gitattributes`) |
| `.warrant/v3.json` | trust and profile (owner path) |
| `.warrant/merge.json` | the merge gate's configuration and the owner paths (owner path) |
| `.warrant/claims.json` | where the claims live: the spec `docs/V3.md`, the retired source `SPEC.md`, the witness files, `tests/mutants.py` |
| `.warrant/v3/schema-accepts.jsonl` | Codex's acceptances of the bootstrap schemas, as committed at #218 |
| `tools/{claims,roadmap,review,gate}.py` | shims: `python3 -m warrant.<name>` with this checkout's package, for CI and these docs; `tools/gate.py` is what the merge workflow runs (owner path) |
| `tools/graph.py` | queries over the record graph (around, path, why, frontier, impact) and the views |
| `tests/mutants.py` | every mutant, the cases it must fail, shards and their merge |
| `integrations/warrant-review/` | the Codex plugin: the review skill, the MCP launcher, the review waker |

## Installing from a checkout

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[mcp]"
```

The tools run from the checkout with any Python ≥ 3.10 that has `cryptography`
(`python3 tools/claims.py check`, or `python3 -m warrant.claims check` from the checkout's root).

## Checks

What CI runs (`.github/workflows/ci.yml`), each from the checkout:

```sh
python3 tests/core_test.py            # the engine, store and records (docs/V3.md §§2-10)
python3 tests/agent_test.py           # the agent interface (§13); M01 needs the MCP SDK
python3 tests/gate_test.py            # the merge gate (§14)
python3 tests/tools_test.py           # claims, review replay, roadmap (§14)
python3 tests/pilot_test.py           # the pilot (needs sigma-glyph 0.8.0)
python3 tests/boundary_test.py        # the public surface; python3 tests/quickstart_test.py: QUICKSTART.md
python3 integrations/warrant-review/test_plugin.py
python3 tests/mutants.py --shard 1/4 --matrix part-1.json    # ... 4/4, then --merge
python3 tools/claims.py check && python3 tools/roadmap.py check && python3 tools/pilot.py check
python3 tools/review.py verify --base <base commit>          # replays new since the base, re-executed
python3 tools/claims.py verify --base <base commit>          # claims checker acceptances new since the base, re-executed
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
`backed` waits for the claims checker: `python3 -m warrant.claims replay --key -` on a clean checkout
runs every waiting claim's witnesses and mutants and accepts those that held, as `claims-checker`,
whose key `.warrant/v3.json` binds. Each acceptance names the commit and its tree, the checker's code
(`code`, the digest of its whole import closure) and its environment (`env`: Python, cryptography);
`python3 -m warrant.claims identity` prints them for this checkout (a checker runs as `-m`: a `tools/` shim
is a module of the repository outside its code, and the identity refuses it). CI's `claims.py verify --base M`
re-executes every acceptance new since M at its commit and refuses one whose code is not that
commit's. An acceptance holds for its commit: `claims.py view` says for each accepted claim whether
the checker accepted it at the current tree (outside `.warrant/`) or only at an earlier one, and
`replay` accepts again a claim whose acceptances are all at other trees.

## Checker keys

The two checkers, `claims-checker` (role `claim/verifier`) and `review-replayer` (role `replayer`),
each have one key, bound once in `.warrant/v3.json`; a change to their code changes the `code` their
attests name, never the actor. The owner creates both seeds outside the repository (each file 0600,
its directory 0700, an existing seed refused) and binds the two public keys this prints:

```bash
cd ~/Projects/warrant && python3 -c 'import os, sys; sys.path.insert(0, "."); from pathlib import Path; from warrant.keys import Key
for actor, d in (("claims-checker", ".warrant-claims-checker"), ("review-replayer", ".warrant-review-replayer")):
    p = Path.home() / d / f"{actor}.seed"; p.parent.mkdir(mode=0o700, exist_ok=True); os.chmod(p.parent, 0o700)
    k = Key.generate(); fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.write(fd, (k.seed_hex() + "\n").encode()); os.close(fd)
    print(actor, k.public)'
```

The review waker reads `~/.warrant-review-replayer/review-replayer.seed`; the claims checker's seed
is passed on standard input (`python3 -m warrant.claims replay --key - < ~/.warrant-claims-checker/claims-checker.seed`).
The Warrant 2 checkers (`checker sha256:eed989…` and `checker sha256:c0a8c6…`) keep their roles for
the migrated records they signed and have no key: nothing new can be signed as them.

The Warrant 2 claims (source SPEC.md) are retired lineages: history, never deleted.

## The roadmap

Goals (`goal@1`, keys G1..G12) and the obligations that answer them (`obligation@1`) are records.
`python3 tools/roadmap.py view` renders them; `oblige` files an obligation and `close` its `done`
version, which a `roadmap/acceptor` (codex) accepts. `revise` files a new `open` version with a new statement
(only the actor who opened the obligation), and `release` its `released` version with the reason (only a
`roadmap/owner`: forgiveness is the creditor's). `due --actor codex` is what the review waker
reads: the leaves waiting only for that actor's attest.

## Reviews as records

A pull request is a `pr-head@1` lineage: `python3 tools/review.py open --pr N --title T` files its
root, `head --pr N` a version naming the commit to review (the `HEAD` of the checkout) and its tree.
The reviewer accepts the head version or files `finding@1` challenges against it, through MCP
(integrations/warrant-review/skills/warrant-review/SKILL.md). The review replay checker runs each
finding's test at each later head and attests the result; `review.py verify` in CI re-executes those
new since the base. After a merge, `review.py merged --pr N --merge SHA` files the observation.

### Merging on acceptance, and waking the reviewer

`.github/workflows/merge-on-acceptance.yml` runs master's `tools/gate.py` (warrant/gate.py): it
merges a pull request whose head version a `pr/acceptor` accepted, whose tail after the reviewed
commit is record lines and blobs only, whose required checks are green, and which changes no owner
path (docs/V3.md §14). Holds: the label `hold`, the repository variable `WARRANT_MERGE_GATE=hold`.

When the base moves on after an acceptance (another pull request merged first) and GitHub reports a conflict,
merge the base locally (`git merge origin/master`: the union drivers of `.gitattributes` keep both sides of
`records.jsonl`, `CHANGELOG.md` and `tests/mutants.py`), run `python -m warrant fmt`, and push. File no new head
version: the gate holds such a head to the reviewed commit's clean merge with the base, so the acceptance stands.
A merge that needed a hand resolution is new content and needs a new head version and its review.

The review waker (integrations/warrant-review/waker/waker.py, launchd, every five minutes) serves the
repositories `~/.warrant/codex-waker/repositories.json` lists, each on its own base branch with its own
mirror, state and worktrees, and refuses a base whose `.warrant/v3.json` names another repository. For
each it runs the base tree's `python -m warrant.review due` and `python -m warrant.roadmap due --actor
codex` (the base's own package when the base carries it, else the warrant-graph installed beside the
waker), replays findings with the review replay checker's seed (sandboxed, seed on standard input),
and wakes Codex once per due head or roadmap version, naming that repository and its branch. A
repository without `.warrant/merge.json` (its owner merges; `due` refuses its base) is served for its
roadmap versions only, the open verdict pull requests read from GitHub (`gh pr list`).
`python3 integrations/warrant-review/install.py` installs the plugin, the waker and its Python with this
checkout's warrant-graph, and writes `repositories.json` with this repository as the only entry when
the file is absent (the owner runs it).

## The review loop in another repository

Another repository runs the same loop on its own records with the installed package, pinned to an
exact version (and hashes), from a checkout of that repository:

- `.warrant/v3.json`: `{"warrant": "repository/3", "repository": "owner/name", "trust", "profile"}`;
  the profile names its `pr/acceptor`, `replayer` and, for claims, `claim/verifier`. Its store holds
  the schemas (`warrant bootstrap`), at the profile's quorum.
- `.warrant/merge.json`: the gate's base branch, required checks (each bound to its workflow file),
  hold label and owner paths. Nothing of warrant's own tree is read: no repository name, branch,
  check or owner path is a constant of the package.
- `.warrant/claims.json`, only for claims: `{"warrant": "claims/1", "source", "retired", "witnesses",
  "mutants"}` (`python -m warrant.claims` says what each is). The claims checker and the review
  replay run Python test files (W-2, a declared runner, is not done).

The commands are `warrant review open|head|merged|due|verify|view` (also `warrant-review` or `python -m
warrant.review`), `warrant gate gate|due`, `warrant claims check|view|file|replay|verify` and `warrant roadmap`. A
checker's `code` is the digest of the package's modules: in this repository, which carries their
source, CI holds an attest to the package at the commit it names; in a repository that does not,
to the package installed where `verify` runs, so CI re-executes with the same pinned version. The
gate decides from the base: its workflow checks out the base commit and installs the version the
base pins (here: runs the base checkout's own `warrant/gate.py`). The waker serves the repository
once an entry for it is added to `~/.warrant/codex-waker/repositories.json` (waker.py `served`).
