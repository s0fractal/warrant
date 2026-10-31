# Changelog of warrant-graph

Each entry below is a version of the `warrant-graph` package on PyPI. Warrant 3 starts at 3.0.0a1;
2.0.0a1 was Warrant 2. **[protocol]** marks a change of the record format or of the assessment rules
(docs/V3.md).

## Unreleased

- The review plugin's directory is `integrations/warrant-review` (was `integrations/codex-plugin`): it is no agent's.
  Reinstall with `python3 integrations/warrant-review/install.py`. In this repository's profile `claude` is a
  `pr/acceptor` beside `codex` (`.warrant/v3.json`): either reviews the other's pull requests, and neither its own (an
  attest by the head version's own actor never counts toward its guard).
- The review waker wakes a roster: an entry of `repositories.json` may list `reviewers` (`{actor, agent: codex|claude,
  seed?}`), and each due head goes to the first that is not its author, kept across retries. `claude` runs `claude -p`
  with the plugin in the wake's worktree. Without a roster, codex reviews, as before. Roadmap verdicts stay with
  codex: the gate admits verdict branches under `codex/verdicts/` only.
- The review plugin (`integrations/warrant-review`, 0.2.0) is an Agent Plugins 1.0.0 package: a portable `plugin.json`
  and `mcp.json` (the server is `warrant-agent-mcp`, serving the operator's Home), with Codex's and Claude Code's
  manifests beside them. The review skill names no agent: it is written for the actor the waker names, and its stdio
  client moved under it (`skills/warrant-review/scripts/warrant-mcp-call`).
- `warrant put --kind schema` refuses a body that is not a schema body (`SCHEMA_NOT_COUNTED`), as the agent
  interface's `prepare` does: it used to file it for good, never counted (time-lab's N6).
- `warrant-agent-mcp --repo DIR --actor A [--seed SEED]` (and `warrant-agent`) serve one checkout with the
  configuration `warrant-agent-mcp init` would write for it, held in memory: init's checks, init's refusal codes,
  no file. With no `--seed`, the Home identity's seed. The Codex plugin's `warrant-mcp-call` passes `--repo`
  through, and exits 2 when the server refuses its configuration; the review skill uses it, so a review no longer
  writes `~/.warrant/codex-review-N.json`, and keeps its working files in `~/.warrant/codex-work/<N>-<H12>`.
- Warrant Home (docs/HOME.md): the operator's one configuration, `~/.config/warrant/home.json` (`$WARRANT_HOME`,
  `$XDG_CONFIG_HOME`), listing the repositories of this machine and the identities that sign in them.
  `warrant home [list|add DIR|identity ACTOR --seed FILE|remove NAME]` keeps it; `--repo NAME` names a registered
  repository's store to every command; `warrant-agent` and `warrant-agent-mcp` with no `--config` serve one
  workspace per registered repository. Each repository keeps its own `.warrant/`: Home writes nothing into one.
  A Home that is a link or that others may write is refused; a seed is never inside a registered repository and
  is refused when others may read it.
  Every change of Home (`warrant.home.update`) reads, changes and writes it under an exclusive lock: two changes
  made at once both take effect (Codex finding 773e7e02f857).
  A Home, and its directory, must belong to the user and be writable by no one else (as OpenSSH's StrictModes):
  whoever may write the directory may replace the Home (Codex finding 3f75f9921074).
- The merge gate holds a head that merged base commits after its reviewed commit X to X's clean merge with the
  newest base commit it holds (`git merge-tree`, the repository's merge attributes applied), and to X itself
  when that merge conflicts: catching up with the base after an acceptance no longer needs a new review.
  `CHANGELOG.md` and `tests/mutants.py` merge as union, and `tests/mutants.py` refuses an id named twice.
- One command. `warrant review|gate|claims|roadmap ARGS` run those modules' commands (`warrant-review` and the
  others stay). `warrant status [--actor A] [--json]` is a reader's summary of a store: the snapshot, the schemas,
  lineages by schema and state, reliance, chain forks, problems and, with `--actor`, what waits for A.
- The store is the nearest `.warrant/` from the current directory upward (or WARRANT_REPO_ROOT's), and the trust
  and profile default to that store's `v3.json`: `warrant assess` in a repository needs no flag. `--store`,
  `--trust` and `--profile` still name others; `init` still creates the store in the current directory.
  A store found by default is confined by real path to the directory it is found in, as `--store` is to the
  current one: a `.warrant` link leading out of its repository is refused (Codex finding 24b91d75f065).
- A repository's `.warrant/v3.json` is read from its store only, by every reader (the `warrant` command, the
  review loop's commands through `warrant.repo`, the agent interface): a link to a file outside the store is
  refused (Codex finding d6127c0fd71d).
- A repository's store directory is its own: `warrant.store.dot_of` confines `<repo>/.warrant` by real path to the
  repository for the review loop's commands (`warrant.repo`), Home's registration and listing, and the agent's
  workspaces (the store a call opens and the receiver it reads, also after the workspace was created): a
  `.warrant` link out of the repository is refused (Codex finding 1c3f12bcf1a9).
- The record graph's queries (`around`, `path`, `why`, `frontier`, `delta`, `impact`, `answer`) move from
  `warrant_agent.graph` to the core as `warrant.graph`; the agent interface and `tools/graph.py` import them there.
- `warrant.roadmap revise --obligation ID --statement S` files a new `open` version of an obligation with a new
  statement, and `release --obligation ID --reason TEXT` its `released` version with the reason as the residual.
  Each refuses before signing an actor the lineage rule would exclude: `revise` anyone but the actor who opened
  the obligation (`AUTHOR`), `release` an actor without `roadmap/owner` (`ROLE`).
- The repository's root holds what a reader starts from: the agent interface's guide, the proof-space
  pilot's contract, the history of earlier generations and the name policy moved to `docs/` (`docs/AGENT.md`,
  `docs/PILOT.md`, `docs/HISTORY.md`, `docs/TRADEMARK.md`); the empty `sonar-project.properties` is removed,
  and this changelog keeps Warrant 3 (earlier generations at the tag `history/warrant-2-2026-10-27`).
- The code a checker's result is checked against (`warrant.repo.code_tree`, `code_at`, `checker_code`) is read
  with `git ls-tree --full-tree`: from a directory inside the checkout (the mutant harness's copy under
  `build/`) the listing was empty, so every acceptance seemed to be at the current tree.
- `warrant.review due` and `warrant.review gate` refuse with exit 2 (`REFUSED <code> ...`) when the merge
  gate refuses the base, e.g. a repository with no `.warrant/merge.json`; they exited 1 with a traceback.
  The review waker counts exit 2 as a refusal and goes on to the repository's roadmap closures (a
  repository whose owner merges by hand is served for its closures).
- The review waker reads a repository's open verdict pull requests from GitHub (`gh pr list`) when `due`
  refuses its base: a repository without a merge gate had its roadmap versions held for good ("the open
  pull requests were not read").
- No change of behaviour: the open SonarCloud issues are resolved (long functions of the engine, the gate,
  the review loop's commands, the CLI and the waker split into named helpers; repeated literals named once),
  and the README ends with the SonarCloud quality-gate badge.

## 3.0.0a2 — the review loop in the package

Prepared for PyPI; published when the owner pushes the tag `v3.0.0a2` (`release.yml`). An alpha
(PEP 440): pip installs it only with `--pre`. Records and assessment rules are those of 3.0.0a1.

- The review loop's commands are part of the package, so that another repository runs them on its own
  `.warrant/` with the installed `warrant-graph`: `warrant.review` (open, head, merged, due, gate, the
  replay checker, verify, view), `warrant.gate`, `warrant.claims` (check, view, file, replay, verify)
  and `warrant.roadmap`, as `python -m warrant.<name>` or the commands `warrant-review`, `warrant-gate`,
  `warrant-claims`, `warrant-roadmap`. They run on the repository `--root` names, else the Git checkout
  around the current directory. Everything repository-specific comes from that repository:
  `.warrant/v3.json` (name, trust, profile), `.warrant/merge.json` (base branch, required checks, owner
  paths) and the new `.warrant/claims.json` (the specification, retired sources, witness files and
  mutant harness of its claims). A checker's `code` is the digest of the package's modules: at the
  attested commit where its tree carries the package's source, else the package installed where it is
  re-executed.

This repository (not part of the package):

- `tools/{review,gate,claims,roadmap}.py` are shims of the package's modules; `tools/repo.py` is gone
  (`warrant/repo.py`). `warrant/gate.py` is an owner path beside `tools/gate.py`.
- The review waker serves the repositories `~/.warrant/codex-waker/repositories.json` lists, each with
  its own base branch, mirror, state and worktrees, and refuses a base whose `.warrant/v3.json` names
  another repository; `install.py` writes that file with this repository as the only entry and installs
  this checkout's package into the waker's Python.

## 3.0.0a1 — the first Warrant 3 release

Published to PyPI on 2026-10-27 from the tag `v3.0.0a1` (1740fd75) by `release.yml` run 40556221850,
whose readback found the built digests. An alpha (PEP 440): pip installs it only with `--pre`.

- **[protocol] Warrant 3 replaces Warrant 2.** One record envelope with four kinds (schema, entity,
  attest, challenge), native lineage with FORK as a core verdict, schemas as records under a k-of-n
  schema quorum, one guard, and one store file, `.warrant/records.jsonl` (union-merged) with
  `.warrant/blobs/` (docs/V3.md, the normative specification). The package `warrant` is Warrant 3
  (jcs, keys and shapes kept from Warrant 2); `warrant_agent` (warrant-agent/3) is one in-process
  assessment per call with a stateless prepare/commit and a compare-and-swap on the signer's head;
  Warrant 2's `warrant-agent-mcp init` output still loads. 2.0.0a1 does not read Warrant 3 stores.
- **[protocol]** Guards and effective versions are resolved together as one least fixpoint, so a
  verdict no longer depends on record-id order; only schema-less attests back a schema; a valid schema
  short of its quorum is a proposal, not a store problem; `canonical` is false whenever a line is
  rejected; a non-attest `migration@1` record is INVALID instead of crashing the assessment.
- The agent's `prepare` and `commit` assess the store with the candidate record and refuse one the
  engine would refuse, reject or list as a new problem; `commit` decides under the writers' lock over
  every raw line.
- The `mcp` extra accepts the MCP SDK 2.x from 2.3 (`mcp>=2.3,<3`); CI and the release test 2.3.0.

This repository (not part of the package):

- The Warrant 2 records were migrated, not re-signed: 1 446 records vouched for by one `migration@1`
  attest, replayed IDENTICAL at the tag `history/warrant-2-2026-10-27` (HISTORY.md). The 362 Warrant 2
  claims are retired; docs/V3.md's normative sentences are `claim@1` records.
- The checkers have stable actor ids, `claims-checker` and `review-replayer`, each with one key bound
  once; every attest they sign names the code that ran (`code`, the digest of the checker's whole
  import closure) and its `env`. CI re-executes every new checker attest at its commit and refuses one
  whose code is not that commit's (`CODE_DIFFERS`). Replaces the actors named `checker sha256:<code,
  python, cryptography>`, which every code change and every interpreter renamed.
- Removed from the tree (kept at the history tags): the Warrant 0.x governance records `.warrants/`
  and `trust-config.json`, `MODEL-ACTORS.md`, `MAINTAINER-LEASE.md`.
- Merges without the owner: the review waker wakes Codex after green CI, and the merge gate merges a
  pull request Codex accepted (#221 was the first Warrant 3 pull request merged that way).

---

## Earlier generations (warrant-verify 0.x, Warrant 2)

The changelog of Warrant 2 (`warrant-graph` 2.0.0a1 and its unreleased successors) and of the retired 0.x
generation (`warrant-verify` up to 0.12.0) is kept at the tag `history/warrant-2-2026-10-27`
(`git show history/warrant-2-2026-10-27:CHANGELOG.md`); docs/HISTORY.md says what each generation was.
