# Changelog of warrant-graph

Each entry below is a version of the `warrant-graph` package on PyPI. Warrant 3 starts at 3.0.0a1;
2.0.0a1 was Warrant 2. **[protocol]** marks a change of the record format or of the assessment rules
(docs/V3.md).

## Unreleased

- Warrant Home (docs/HOME.md): the operator's one configuration, `~/.config/warrant/home.json` (`$WARRANT_HOME`,
  `$XDG_CONFIG_HOME`), listing the repositories of this machine and the identities that sign in them.
  `warrant home [list|add DIR|identity ACTOR --seed FILE|remove NAME]` keeps it; `--repo NAME` names a registered
  repository's store to every command; `warrant-agent` and `warrant-agent-mcp` with no `--config` serve one
  workspace per registered repository. Each repository keeps its own `.warrant/`: Home writes nothing into one.
  A Home that is a link or that others may write is refused; a seed is never inside a registered repository and
  is refused when others may read it.
- One command. `warrant review|gate|claims|roadmap ARGS` run those modules' commands (`warrant-review` and the
  others stay). `warrant status [--actor A] [--json]` is a reader's summary of a store: the snapshot, the schemas,
  lineages by schema and state, reliance, chain forks, problems and, with `--actor`, what waits for A.
- The store is the nearest `.warrant/` from the current directory upward (or WARRANT_REPO_ROOT's), and the trust
  and profile default to that store's `v3.json`: `warrant assess` in a repository needs no flag. `--store`,
  `--trust` and `--profile` still name others; `init` still creates the store in the current directory.
  A store found by default is confined by real path to the directory it is found in, as `--store` is to the
  current one: a `.warrant` link leading out of its repository is refused (Codex finding 24b91d75f065).
- The record graph's queries (`around`, `path`, `why`, `frontier`, `delta`, `impact`, `answer`) move from
  `warrant_agent.graph` to the core as `warrant.graph`; the agent interface and `tools/graph.py` import them there.
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
