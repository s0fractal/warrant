# The repository

This repository builds and checks Warrant with Warrant. Its own records (the specification's claims,
the roadmap, the pull request reviews) are Warrant 3 records in `.warrant/records.jsonl` and
`.warrant/blobs/`, assessed under the repository's receiver configuration `.warrant/v3.json` (the
trust: which keys are whose; the profile: who holds which role; both constitutional paths). The review loop's
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
| `warrant/board.py` | the roadmap as rows of a public project board (GitHub Projects), one way: manifest, plan, sync |
| `warrant/review.py` | the review loop: open, head, merged, due, gate, the replay checker, verify, view |
| `warrant/gate.py` | the merge predicate and the gate's GitHub side (constitutional path) |
| `warrant/cli.py`, `warrant/graph.py` | the one command `warrant` (the core's verbs, `status`, and `review`, `gate`, `claims`, `roadmap`), and the queries over a report's graph that `status`, the agent's `graph` and `tools/graph.py` share |
| `warrant/bridge.py` | the bridge: an issue opened through the form becomes one record in a store of voices of the bridge's own (below) |
| `warrant/across.py` | one read over every registered store, each assessed alone (docs/HOME.md, `warrant across`, the agent's `across`) |
| `warrant_agent/` | the agent interface: Python API, CLI, stdio MCP (docs/AGENT.md, docs/V3.md §13) |
| `.warrant/records.jsonl`, `.warrant/blobs/` | the repository's records; `merge=union -text` (`.gitattributes`) |
| `.warrant/v3.json` | trust and profile (constitutional path) |
| `.warrant/merge.json` | the merge gate's configuration: owner paths, tiers, solo rule (owner path) |
| `.warrant/claims.json` | where the claims live: the spec `docs/V3.md`, the retired source `SPEC.md`, the witness files, `tests/mutants.py` |
| `.warrant/v3/schema-accepts.jsonl` | Codex's acceptances of the bootstrap schemas, as committed at #218 |
| `tools/{claims,roadmap,review,gate}.py` | shims: `python3 -m warrant.<name>` with this checkout's package, for CI and these docs; `tools/gate.py` is what the merge workflow runs (constitutional path) |
| `tools/graph.py` | queries over the record graph (around, path, why, frontier, impact) and the views |
| `tests/mutants.py` | every mutant, the cases it must fail, shards and their merge; a mutant runs only the sections (`*_cases` functions, `tests/world.py` `run_sections`) that hold its cases, read from clean runs of each section alone (and of each set of sections a mutant runs together), and stops at its case's `FAIL`; a mutant killed so is not also run against the whole file, and a later section's state that would hide the kill in a whole run is not seen (the residual; `--whole` runs every mutant against its whole file, when time does not press) |
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
python3 tests/boundary_test.py        # the public surface; python3 tests/quickstart_test.py: QUICKSTART.md
python3 integrations/warrant-review/test_plugin.py
python3 tests/mutants.py --shard 1/6 --matrix part-1.json    # ... 6/6, then --merge
python3 tools/claims.py check && python3 tools/roadmap.py check
python3 tools/review.py verify --base <base commit>          # replays new since the base, re-executed
python3 tools/claims.py verify --base <base commit>          # claims checker acceptances new since the base, re-executed
python3 tools/graph.py views --check                         # build/views/*.md, deterministic
```

A pull request's store must be in canonical order (every write leaves it so; `python3 -m warrant fmt
--store .warrant` restores it after a merge), reject no line under `.warrant/v3.json`, and have every
schema at its quorum.

## The specification's claims

A normative sentence of docs/V3.md is filed as a `claim@1` lineage by `claude` (not yet every one, docs/V3.md §15): the sentence verbatim,
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

## The board: the roadmap where people already look

`python3 -m warrant.board` shows goals and obligations on a GitHub Project, one way. The records stay the source and
the board decides nothing: a row is one lineage as its store's own assessment reads it, and the board's description
names the snapshot and assessment of every store it was drawn from. A row carries only its own lineage and version,
so it changes when its lineage does, not with every record filed elsewhere.

```bash
python3 -m warrant.board manifest --root . --root ../minds --reader https://s0fractal.github.io/warrant/reader.html
```

```bash
python3 -m warrant.board plan --owner s0fractal --project N --root . --root ../minds
```

```bash
python3 -m warrant.board sync --owner s0fractal --project N --root . --root ../minds
```

- **`manifest`** is a pure function of the stores, with no clock and no network: the same stores give the same bytes.
- **`plan`** reads the board and says what a sync would change; **`sync`** does it. Both go through the `gh` of whoever
  runs them; a workflow's own token cannot reach a project, and this module handles no token. A project of an
  organization and one of a user are read alike (`--owner` names either). The narrowest token is a fine-grained one
  bound to the one organization that owns the board, with the organization permission Projects and nothing else; a
  user-owned project needs the classic `project` scope, which reaches every organization the user belongs to.
- **Statuses** are the records' own, never one green "Done": `Open`, `Claimed, not accepted` (the author filed the
  closing version; no acceptor has accepted it), `Accepted` (its guard is met), `Released`, `Withdrawn`,
  `Challenged` (a counted challenge stands against its effective version or its leaf), `Forked`. None says verified:
  a roadmap item has no checker, and claims are not on the board.
- **GitHub's own `Status` is not ours.** A new project fills it with "Todo" for every item added; a sync clears it on
  our rows, whose status is `Warrant status`.
- **A hand edit is no record.** A sync puts every cell back and its plan names the cells that differed. An item with
  no `Warrant ID` is a person's own: counted, never touched. A row the manifest no longer holds is archived.
- **Record text is data.** In a row's body it lies inside a code fence longer than any run of backticks in it, so the
  board mentions nobody and links nothing from it; only a reference of the exact shape `owner/name#N` becomes a link.
  Each row links to the reader (docs/VERIFY.md), where the same lineage is assessed in the visitor's own browser.

Not established: tools_test BD1–BD5 run against a board in memory, so what GitHub's API answers to these calls is held
by no test; the board's views (which columns, grouped how) are made by hand on GitHub and can hide a column; a board's field named as one of ours and of another type refuses the sync (GitHub's own
`Repository` is why ours is `Store`); and the
board shows no `Grounded` column, because `warrant.graph.grounded` reads an obligation's `answers` as a ground (a met
goal citing its obligations is a cycle with each of them).

## A release against the published one

Roadmap G12: release n+1 is admitted by the published release n. `python -m warrant.differential --python N_PYTHON`
has the published n (a Python whose site-packages hold it, from PyPI) and this checkout's package assess one store
under its `.warrant/v3.json`, and compares the reports as canonical bytes but for the engine's identity (`code`, and
`assessment`, the digest of the operands, `code` among them, each checked to be that digest). Any other difference
is refused unless a `differential/1` declaration (`--declared FILE`: `{warrant, differs: [member, ...], because}`)
names exactly the members that differ. A declared difference is a migration the release says it makes; whether a
receiver relies on what changed stays that receiver's question (a challenge, a revalidation), never a rewrite of n's
history.

```bash
uv venv ~/Projects/.worktrees/venv-wg-n && uv pip install --prerelease allow --python ~/Projects/.worktrees/venv-wg-n/bin/python warrant-graph
```

```bash
python -m warrant.differential --python ~/Projects/.worktrees/venv-wg-n/bin/python --root .
```

`release.yml` runs it on the tagged commit, against the version PyPI publishes, with `--release VERSION`: n's own
engine must also find a release duty of this version closed and accepted, and n's history must still be here: every
record line and blob of the store at n's tag (`v` + n's version) is in the tagged commit's store. A missing one is
refused (n+1 may challenge a record of n, never rewrite it); a missing tag makes no verdict. A release is therefore
made in this order:

1. `python -m warrant.roadmap oblige --goal G12 --statement "Release warrant-graph VERSION: ..."` and a pull request
   that sets `version` in pyproject.toml (and `.warrant/differential.json` when the reports will differ);
2. once merged, `python -m warrant.roadmap close --obligation ID --ref warrant-graph==VERSION --evidence ...`,
   which the roadmap acceptor accepts (the waker wakes Codex for it);
3. the owner tags `vVERSION` on master after that acceptance merged.

## The owner as observer: who merges what

Since 2026-11-13 the owner is an observer with a brake: nothing waits for his signature, and he can stop anything.
In `.warrant/v3.json` he holds `challenger` and `pr/owner` (his challenge counts against any record; it vetoes a
merge), and stays `roadmap/owner` beside `claude` and `codex` (the profile has no time: removing him would make
his 26 earlier releases `LINEAGE_NOT_AUTHOR`). `tests/tools_test.py` OB1 assesses the store as of that day under
his former roles and his present ones: no lineage changes state or reliance. A known hole, recorded as an
obligation, not closed here: the engine does not forbid an actor releasing its own obligation.
Named too (an obligation under G3): after this profile `roadmap/acceptor` is `codex` alone and the `schema/author`
quorum is `claude` and `codex`, 2 of 2. Without Codex no roadmap closure becomes effective and no new schema
(`obligation@2` among them) is admitted; with one family the only way out is a constitutional pull request on
`.warrant/v3.json`, merged after the 168 h solo window.

`.warrant/merge.json` splits what decides merging in tiers (docs/V3.md §14, AGENTS.md rule 1). Every merge is the
gate's (the workflow's bot), never an agent's `gh pr merge` under the owner's login:

| tier | paths | two families | one family (`solo_ready`) |
|---|---|---|---|
| owner | `.github/`, `.warrant/merge.json` (the brake itself) | the owner merges | the owner merges |
| constitutional | `AGENTS.md`, `.warrant/v3.json`, `.warrant/v3/`, `warrant/gate.py`, `tools/gate.py` | after 72 h | after 168 h (7 days) |
| watched | the modules the gate imports (engine, store, records, keys, jcs, shapes, `__init__`) | after 24 h | after 72 h |
| everything else | | at once, when accepted | `solo`: once the checks are green (`window_hours` 0), its author a `pr/acceptor` |

The table's windows apply while the owner is away. While he is present (`presence`: a merge of his made on GitHub,
author his login and committer GitHub's web-flow, within 14 days and since #350's merge, when agents stopped merging
under his login), a watched or constitutional change merges as soon as its checks are green, and its merge commit
carries its brake (`warrant-gate brake until T: #N head version V`) for the window it would have waited. Within it, his
`hold` label on the merged pull request or his challenge on its head version makes the gate open the merge's exact
revert from `gate/revert/` (the store's records kept), which it merges once its checks are green. A path changed again
since makes no automatic revert: the gate says so in its summary. A stable release is published only after every brake in the tagged commit's history has closed (release.yml, `python
-m warrant.gate brakes --at C --version V`). A pre-release (PEP 440 `aN`, `bN`, `rcN`, `.devN`, by the whole version
the package declares) goes with brakes open (owner, 2026-11-13: «в нас нема клієнтів — ми обслуговуємо своє
майбутнє»); a revert of a merge a published version holds names that version in its pull request, an agent records an
obligation for it (closed by the next pre-release), and a yank is the owner's act if he wants one.

A window counts from when the required checks completed at the head; no `hold` label and no challenge by
`pr/owner` on the head version may stand. When a constitutional window opens the gate comments once on the pull
request, naming `@s0fractal` (`constitutional.notify`), with the paths, the end of each window and how to stop it.
The pull request needs its review lineage (`tools/review.py open --pr N --title T`, then `head --pr N`); the gate's
reading of it:

```bash
python3 tools/gate.py gate --base "$(git rev-parse origin/master)" --pr N --json
```

(`facts.solo_ready`, `facts.solo_from`: when the solo window opens). A place a listed file implies (a package of its
module's name, a module added where the interpreter searches) is still the owner's. The owner reads every merge on
`warrant serve`'s «Що змінилось» and vetoes with the `hold` label or a challenge.

The claims checker runs on a runner (`.github/workflows/claims-replay.yml`, started by the gate after each of its merges but one of verdicts only (`after_merge` in `.warrant/merge.json`; a merge with the workflow's token starts no push workflow), on each push to master, and on a schedule GitHub mostly skips), under a key
made there (`claims-key.yml`, the environment `claims`); its acceptances arrive as a pull request of verdicts only
from `claims/verdicts/`, which CI re-executes and the gate merges.

## The bridge: a voice with a GitHub account alone

`warrant say` asks its speaker for Python, a key and a repository of their own. The bridge asks for a GitHub account:
an issue opened through the form `.github/ISSUE_TEMPLATE/voice.yml` (a record id, a stance, a statement) is filed by
`.github/workflows/voice-bridge.yml` as one record in a store of voices on the branch `voices`, published at
`https://raw.githubusercontent.com/s0fractal/warrant/voices/`, and the issue is answered with the record's id
(`warrant/bridge.py`; cases BR1–BR6 and J19).

- **What a record says.** The bridge's key states that GitHub delivered this issue, opened by this account (login, id,
  kind of account, the issue's address, the SHA-256 of its body as delivered). It is not the account's signature:
  whoever holds the bridge's key, or the account, can make one. "Account" means whoever controls it, a person or an
  agent acting under a person's login.
- **What it counts for.** Nothing. The store trusts the one name `github-bridge` and gives nobody a role; an objection
  is a `challenge`, a support an `attest` with `stance: "support"` and no `verdict`. A reader who reads the store beside
  another sees them as voices from outside, with the account the store states and a link to the issue.
- **What is read.** The issue as opened, once: the body must be exactly the form's three fields in order. Anything else
  is answered with a refusal in the bridge's own words; no text of the issue reaches an answer, a command or a
  workflow expression. One record per issue.
- **The key.** `bridge-key.yml` makes it once on a runner and keeps it as `WARRANT_BRIDGE_SEED` of the environment
  `bridge`, deployable from master alone (the owner makes the environment and a one-time token, as for `claims`). No
  trust of this repository binds it. Whoever can change master's code can read it, which is the gate's guard; a key
  that leaked signs voices only.
- **Limits.** Every issue through the form is filed: the brakes are GitHub's own limits, the owner blocking an
  account, and disabling the workflow. Records are never removed. The door is hosted here and can be closed here; a
  voice under one's own key (`warrant say`) needs nobody.
- **Not established.** That the body GitHub delivers for the form is byte for byte what `FORM` expects was read from
  GitHub's documentation and not from a delivery: the first issue through the form is that check, and a body of
  another shape is refused with an answer, not filed wrong.

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
An owner path covers what the interpreter could load in a listed module's place (a package or an extension
module of its name, the `__pycache__` beside it), and the two directories the gate's interpreter searches
before the standard library, the root and `tools/`, take nothing new from the gate: a new tool script, a new
top-level directory or a `.gitattributes` change is the owner's to merge.

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
exact version (and hashes), from a checkout of that repository. `warrant init` in it starts the store and leaves
what the next agent reads (`warrant/entry.py`): `.warrant/v3.json` with an empty trust and profile, the block of
`warrant/entry.py` in `AGENTS.md` between `<!-- warrant:begin -->` and `<!-- warrant:end -->` (a file of the
repository's own keeps every byte outside them), `@AGENTS.md` in `CLAUDE.md`, a read-only `.warrant/agent.json` and
the server `warrant` in `.mcp.json` (Claude Code asks the user to approve a project's server the first time it opens it:
that is its behaviour, not a defect). `--no-entry` leaves the two markdown files alone, `--no-mcp` the server. The
block and the server are what the adoption experiment measured, together (experiments/adoption, #385: 0 of 18 agents
used the records without them, 18 of 18 with them), and the block changes only with a new measurement. Not measured:
the block without the server, the comment marks around it, and agents that read no `.mcp.json` (they have the block's
CLI commands only). `warrant status` on such a store says that no actor holds a role, so no acceptance counts yet.

- `.warrant/v3.json`: `{"warrant": "repository/3", "repository": "owner/name", "trust", "profile"}`;
  the profile names its `pr/acceptor`, `replayer` and, for claims, `claim/verifier`. Its store holds
  the schemas (`warrant bootstrap`), at the profile's quorum.
- `.warrant/merge.json`: the gate's base branch, required checks (each bound to its workflow file),
  hold label and owner paths. Nothing of warrant's own tree is read: no repository name, branch,
  check or owner path is a constant of the package.
- `.warrant/claims.json`, only for claims: `{"warrant": "claims/1", "source", "retired", "witnesses",
  "mutants", "coverage"?}` (`python -m warrant.claims` says what each is). `source` is one specification or a list of them; each
  claim names its own and its sentence is checked there. With `coverage` (a list of RFC 2119 keywords),
  `check` also refuses a keyword outside a heading that lies in no live claim's sentence (`UNCLAIMED_KEYWORD`);
  a sentence that states no rule is filed as an `informative` claim with its reason. The claims checker and the review
  replay run Python test files (W-2, a declared runner, is not done).

The commands are `warrant review open|head|merged|due|verify|view` (also `warrant-review` or `python -m
warrant.review`), `warrant gate gate|due`, `warrant claims check|view|file|replay|verify`, `warrant roadmap` and
`warrant drift` (whether the bytes each acceptance names are still HEAD's; a claim whose are not reads `STALE`,
docs/V3.md §15). A
checker's `code` is the digest of the package's modules: in this repository, which carries their
source, CI holds an attest to the package at the commit it names; in a repository that does not,
to the package installed where `verify` runs, so CI re-executes with the same pinned version. The
gate decides from the base: its workflow checks out the base commit and installs the version the
base pins (here: runs the base checkout's own `warrant/gate.py`). The waker serves the repository
once an entry for it is added to `~/.warrant/codex-waker/repositories.json` (waker.py `served`). An entry may name
`replay_python`, an interpreter whose warrant-graph is the version the repository pins: the review replays then
carry the `code` its CI installs, so `warrant review verify` there can re-execute them.
