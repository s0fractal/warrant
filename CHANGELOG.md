# Changelog of warrant-graph

Each entry below is a version of the `warrant-graph` package on PyPI. Warrant 3 starts at 3.0.0a1;
2.0.0a1 was Warrant 2. **[protocol]** marks a change of the record format or of the assessment rules
(docs/V3.md).

## Unreleased

- A second client (`node impl-js/read.mjs --base URL`): a repository's records fetched over HTTP(S) from any root and
  assessed by the JavaScript implementation give the same report, byte for byte, as the store read from disk; an
  altered blob is refused, an altered line rejected. Read through GitHub, master gives the Python engine's root and
  every lineage's state. docs/VERIFY.md; impl_js_test J9, mutants JS1, JS3.
- Who a voice is (`warrant_agent/voices.py`, R04 of the observer pack in part): the floor joins voices by the keys
  their store's trust binds to their names, not by the names. Two names on one key are one source (the author's key
  under another name is never an independent voice); one name on different keys in two stores is two; a record its
  store admitted unsigned (a migration's word) is no one's key. The floor counts the voices independent of the author
  and names where names mislead. Tests VO1–VO4, mutants A180–A185.
- The map's and the feed's contracts (P05 of the observer pack, completed): the map draws every node of a lineage
  (`data-n`) or names how many it folded; the feed draws the newest records of its scope and names, with how many,
  what it leaves out (automatic actors, migration records, those past the limit of 300) and every store it could not
  read. The promise is computed from the records, not from the renderer's list. Before, the feed left all of that out
  silently: on the registered stores 1216 records of automatic actors, 139 migration records and 2259 past the limit.
  `python -m warrant_agent.contract STORE LINEAGE --map` and `--feed [STORE] [--actor A] [--machines]` replay them;
  all 942 maps of the registered stores and the feed keep them. Each map of a comparison is read alone, and the
  omission counts are compared both ways (Codex findings F1, F2 on #345). Tests FC1–FC3, MC1–MC3, mutants A186–A200.
- A lens's contract (`warrant_agent/contract.py`, P05 of the observer pack): what a card promises of a lineage page
  (each declared member that has a value, the activity it shows) and what the floor promises (state, reliance, every
  counted challenge that stands, UNATTESTED, the lens) are read back from the marks of the page drawn. A broken promise
  is named on the page («сторінка не тримає контракт лінзи») and replayed by `python -m warrant_agent.contract STORE
  LINEAGE [--lens ID]` (exit 1). The renderer no longer drops a member whose value is not in the card's `as` form,
  nor a root's statement the heading cut. Every lineage page of the registered stores under four lenses keeps its
  contract. Tests KC1–KC3, mutants A174–A179.
- Small tails of the observer pack: a page names what its lineage rests on outside the store (P09); «як бачив тоді»
  rebuilds the page as the reader's last view saw it and says whether its root matches (R06); a warm cache renders
  the same bytes as a cold one (P10). Tests TL1–TL3, mutants A169–A172.

- The commons (`python -m warrant_agent.commons say RECORD "…"`): an agent with no key any store binds and no role
  says «фе» to any record, under its own key's name (`key:<hex>`); the commons store trusts nobody and holds voices,
  never verdicts. Every lineage page shows challenges from other stores as voices from outside, uncounted by that
  store; `/fragile` lists them; a reader's overlay counts one when the reader's rules do. Tests CM1–CM5, mutants
  A162–A166.

- `/overlay` («Для мене»): a store read together with the stores the reader chose, under the reader's own trust and
  roles (`overlay.py`): a challenge the publisher never took in counts for a reader whose rules count it, beside the
  store's own verdict, never in its place; each result has its own identity; key bindings the sources disagree on are
  not admitted. Tests OV1–OV5, mutants A155–A161.

- Codex's observer pack, audited: an adoption is filed in the reader's own store (a reader adopts a lens it cannot
  write to); a page's lens names the whole interpreter and every other store's root, trust and profile; the floor
  says what the lens leaves out and which stores were not read; `/changes` says when the reader's lens changed; no
  page runs a script (`script-src 'none'`). Tests LN10, AU1–AU4, mutants A148–A154.

- Two general forms under `warrant serve`: observations (`observe.py`: reactions, views and adoptions are one record
  kind registry) and differences of views (`view.py`: `/changes`, the lens comparison, the floor's sources and
  fragility are one comparison with time, lens, sources or records varied). New: `/whatif` («Що було б»), after
  minds' `what_if`: a store without its challenges or one actor's records, assessed on a candidate by the same
  engine, every changed lineage with its witness and one digest (equal consequences, equal digest); `/fragile` shows
  what each lineage's objections move. Pages are byte-identical before and after but for what is new. Tests
  WI1–WI3, mutants A144–A147; ten mutants retargeted to the lines' new homes.

- `/fragile`: the lineages someone objected to, the most attended first, each objection beside the attention it met
  and its fate (counted, standing, reproduced); «Хто вказав» names whoever filed a reproduced or standing challenge
  with the attention of what it held against. Recognition read from the records, never a score a guard reads. Tests
  FR1–FR3, mutants A140–A143.

- Views: «Прочитав» signs `{verdict: "seen", lens, root}` in the reader's own store; it credits nothing. The floor
  counts who saw apart from who spoke and tells the reader which version they saw last. docs/AGENT.md gains
  «Before lenses»: what Solid, the AT Protocol, Verifiable Credentials, PROV-O and the WoT Thing Description already
  do, and the combination this repository adds. Test SV9, mutants A136–A139.

- The floor of every lineage page names who stands behind it: its authors, every other actor who filed an attest or a
  challenge on it (here or in another store read), the number of stores; «лише автор» when nobody else spoke.
  Completeness cannot be shown; a single voice can. Test SV8, mutants A134–A135.

- **Watched paths** (`.warrant/merge.json` `watched`): the modules the gate imports are merged by the models, the
  owner watching: by the gate after two model families accepted and a 24-hour window with no veto; with one family
  only, by an agent once the gate says `solo_ready` (72 hours). The trust, the rules, the gate and CI stay owner
  paths, and every place a watched file implies stays the owner's. Gate cases E53–E59, mutants G45–G54; claims
  V3-14-33 (new text) and V3-14-38..43.

- `python -m warrant_agent.serve` (v0): the records as pages a person reads, over every repository Home registers:
  the feed (one sentence per record), a lineage (versions, what each established and left open, guard, who
  accepted, challenges, groundedness) and what waits for an actor; each page names its root and lens. A reader with
  a key signs a reaction (`verdict: "react"`, integer dimensions and a note), which credits nothing. Localhost only,
  Host-checked, a per-run token on POST. docs/AGENT.md; tests SV1–SV6, mutants A99–A104.
- Lenses (`warrant_agent/lens.py`): a lineage page's layout is a `lens@1` record (a declarative card: nested or flat,
  which members, order, activity shown or hidden), applied only when the reader adopted it (`verdict: "adopt"`);
  an unknown card is UNSUPPORTED and the built-in draws; `?lens=ID` reproduces a view. No lens hides the floor:
  state, reliance, every counted challenge that stands, UNATTESTED, the lens's name, and every challenge against the
  lens. `?lens=A&vs=B` compares two lenses: what each shows of the page that the other does not. Tests LN1–LN9,
  mutants A105–A115.
- `--mine` (default: the store registered as `space`): reactions are filed in the reader's own store, whatever store
  their record is in, and shown on that record's page with the store named. Test SV7, mutants A121–A122.
- Maps (`/s/STORE/ID`): a lineage as a static, script-free SVG whose every channel is bound to a named field from a
  fixed list (a lens's `card.scene`); deterministic, the legend derived from the bindings, each node a portal; the
  floor keeps every kind's glyph, never shrinks a standing challenge, always draws the legend and names what the
  budget folds; two maps side by side name what moved. Tests SC1–SC7, mutants A128–A133.
- A lineage page's lens names the roots of every other store it read; `/changes` sees reactions filed in other
  stores; a lens comparison names differences of presentation; an explicit `--mine` not read files nothing
  (Codex review of #328). Tests CH4–CH7, mutants A123–A127.
- `/changes`: what changed for the reader since the last mark, under the reader's lenses: only the lineages whose
  floor or drawn members differ, each with its witness; the rest of the new records are counted. Tests CH1–CH3,
  mutants A117–A120.

## 3.0.0a6 — one package, one receiver

Prepared for PyPI; published when an agent pushes the tag `v3.0.0a6` (delegated 2026-11-01, `release.yml`), admitted by
the published 3.0.0a5 (roadmap G12: the reports agree but for the engine's identity, this release's duty is accepted,
the store at `v3.0.0a5` is kept whole). An alpha (PEP 440).

- `warrant verify PACKAGE` (warrant/verify.py, and `warrant_verify.py`, the same as one standard-library file built by
  `tools/build_verify.py`): one `package/3`, assessed by one receiver under its own trust and profile; the exit status
  is the answer (0 rely, 1 do not, 2 no verdict, 3 refused). docs/VERIFY.md; docs/V3.md §13 "One package, one
  receiver". Tests U01–U47, mutants UM01–UM53.
- A second implementation of the assessment, `impl-js/warrant.mjs`, held byte for byte to the Python one by
  `tests/impl_js_test.py` (J1–J8); no declared departure is left. CI runs it under node 24.
- **[protocol]** Defects of the assessment, each with the case that failed first and its mutant (#303): a root's `pinned`
  is read by presence (`pinned: ""` was admitted and never enforced); under a pin, a closure guard of `quorum: 0` is
  INVALID; a guard's `match` member absent from an attest equals nothing (it equalled `null`); a schema whose `closed`
  holds other than strings is not counted, and a migration map with a 5,000-digit integer reads MIGRATION_MAP (both made
  every receiver's assessment raise); a counted challenge against a version of a forked lineage stands; a store whose
  lineage links deeper than `LIMITS["depth"]` is refused before it is assessed (verdicts depended on id order). The
  reports of the warrant, time-lab, minds, sokol-core and sigma-glyph stores are unchanged by them.
- The merge gate derives the places an owner path guards (same-name packages, other suffixes, `__pycache__`, modules
  added where the interpreter searches, links and submodules there, `.gitattributes`, case folding); a head or base path
  that is not UTF-8 is HEAD_UNREADABLE or BASE_CONFIG, not a crash. Every module the gate imports is an owner path.
- A lineage's root can pin what closes it (G15); a challenge can be filed under its own key's name (G1).
- `warrant drift --impact` (what a change bears on), with `--across` through every store of Home; CHANGED names the
  first commit at which the bytes changed, a mode change never counts (G14).
- `warrant.graph.grounded` (minds' Grounded over a report) and `warrant.graph.ledger`, the witness ledger
  (`build/views/WITNESSES.md`): an acceptance is refuted only by a reproduction after it, a citation ordering the two
  before any date. The agent's `graph` gains `op=grounded` and `op=ledger`.
- R-AGENT-CLOCK is measured on stores the agent admits (`tests/assess_bound.py`; docs/V3.md §12). Two limits are named,
  not closed: R-INTERPRETER and R-CHECKER-CACHE.
- `tests/mutants.py` runs a shard's mutants in parallel, each in its own copy (`MUTANT_JOBS`).

- The proof-space pilot (`warrant_pilot/`, the `pilot` extra, docs/PILOT.md) is retired, at the tag `history/warrant-pilot-2026-11-02`: nothing used it but its own
  tests, and it was the only reason Warrant 3 installed sigma-glyph. The `pilot` extra is gone.
- `warrant across` and the agent's `across` (MCP `warrant_across`): one read over every repository registered in Home
  (`stores`, `actor`, `open`, `challenges`, `rests`), each store assessed alone under its own trust and profile. A node is
  one record with one row per store holding it, and trust is never merged. A store that cannot be read is named. Nothing
  from a repository runs. A foreign reference reads `ELSEWHERE` or `UNAVAILABLE`, and a single store's graph no longer calls
  such a node `missing`. The citation form `<store>:<id>` (docs/HOME.md); `refs` carries the bare id, and what the engine
  admits is unchanged. Tests X01–X24, S8, mutants X1–X51.
- G14: a claims checker acceptance speaks of the bytes it ran on, and now names them: `files`, {path: git blob} of
  each witness's test file and each mutant's mutated file and test file (`claims replay` signs them, `claims verify`
  holds them to the commit). `warrant drift` (warrant/drift.py) compares them with HEAD's tree and answers with the
  verdict on the bytes first: unchanged, moved with its bytes unchanged (at its new path), CHANGED since the first
  commit that changed it, or UNKNOWN for an acceptance naming no files. A claim whose every acceptance names other
  bytes reads `STALE`, not `ELIGIBLE`, in `claims view` and in the agent's `context` and `graph` until the checker
  accepts it again (a gate: time-lab Q10 H3, 72 of 72 under pressure); every acceptance signed before this reads
  UNKNOWN until one `claims replay`. It runs no code of the repository's. A graph answer's lens and the agent's
  header bind what the gate read (`checkout`). The engine's reliance is unchanged. Tests DR1-DR15, mutants T96-T120.

- The review waker carries a reviewer's verdict that the reviewer signed in its review worktree and could not
  commit (Codex's sandbox denied Git's lock files on sigma-glyph#80, twice) to the pull request's branch: only
  record lines and blobs new in the worktree's store, checked under the base's keys as that reviewer's acceptance
  or challenge of exactly the head version woken, one commit of the waker's, pushed while the branch is still at
  the head reviewed. The waker signs nothing; a worktree the reviewer committed in is left alone. Test W20,
  mutants P30–P33.

## 3.0.0a5 — claims cover the specification's keywords

Prepared for PyPI; published when the owner pushes the tag `v3.0.0a5` (`release.yml`), admitted by the published
3.0.0a4 (roadmap G12: the reports agree but for the engine's identity, this release's duty is accepted, the store at
`v3.0.0a4` is kept whole). An alpha (PEP 440). Records and assessment rules are those of 3.0.0a1. Its stated limits
are those of 3.0.0a3 (docs/V3.md §12, each by name); none is closed by this release.

- `.warrant/claims.json` may name `coverage`, a list of RFC 2119 keywords (`["MUST", "SHALL", "REQUIRED"]`). Then
  `warrant claims check` also refuses every occurrence of one outside a heading line that lies in no live claim's
  sentence (`UNCLAIMED_KEYWORD`, with its line): the registry is checked against the document, not only the
  document against the registry. A sentence that states no rule is filed as an `informative` claim with its reason.
  Codex's finding 5c401f4c on sigma-glyph#78 (the claims did not cover every MUST, and nothing said so); test C22,
  mutants T85–T95; a keyword only partly inside a claim (one ending in `MU`, or covering `MUST` of `MUST NOT`)
  is not covered (Codex finding e51aaef3 on #259), and the words of `MUST NOT` match across a line break or
  repeated spaces (Codex finding cceaee70 on #259). warrant's own docs/V3.md does not enable it yet (7 keywords outside a claim).
- The review waker runs a repository's review replays under the interpreter its entry names (`replay_python`, an
  absolute path), else the waker's own: a repository that pins warrant-graph (sigma-glyph) gets replays whose `code`
  is the pinned package's, which its CI's `warrant review verify` re-executes. The waker's own build named another
  code, so sigma-glyph's CI refused them (REPLAY_DIFFERS on sigma-glyph#77).

## 3.0.0a4 — claims in more than one specification

Prepared for PyPI; published when the owner pushes the tag `v3.0.0a4` (`release.yml`), admitted by the published
3.0.0a3 (roadmap G12: the reports agree but for the engine's identity, this release's duty is accepted, the store at
`v3.0.0a3` is kept whole). An alpha (PEP 440). Records and assessment rules are those of 3.0.0a1. Its stated limits
are those of 3.0.0a3 (docs/V3.md §12, each by name); none is closed by this release.

- `.warrant/claims.json`'s `source` may be a list of specifications: each claim names its own (`claims file` takes
  a `source` per entry, by default the first), its sentence is checked in that document, and a claim of a source the
  list does not name is refused (`CLAIM_SOURCE`). A repository whose claims live in more than one document (sigma-glyph:
  Book I and the resume draft) needs no second configuration.

## 3.0.0a3 — a release the published one admits

Prepared for PyPI; published when the owner pushes the tag `v3.0.0a3` (`release.yml`), the first release that
3.0.0a2, the published one, must admit (roadmap G12). An alpha (PEP 440): pip installs it only with `--pre`. Records
and assessment rules are those of 3.0.0a1: 3.0.0a2 and this release assess this repository's store, minds',
time-lab's and interdict-mesh's to the same report but for the engine's identity.

Its stated limits are those of docs/V3.md §12, each by name: R-FORK-RECOVERY, R-EVIDENCE-PRESENCE, R-IMPOSSIBLE,
R-REPLAY-SCOPE, R-LIVE-SCOPE-DROPS, R-GATE-CLOSURE, R-UNION-ON-FORGE, R-AGENT-CLOCK, R-PILOT-V2 and no
remembered-verdict cache. None is closed by this release.

- `python -m warrant.differential --release` also refuses a release whose store lost a record line or a blob of the
  store at n's tag (`v` + the version n names): release n+1 may challenge a record of n's history (a challenge, a
  new version, the receiver's reliance answers it), never rewrite it. Without that tag it makes no verdict (UNMADE).
  3.0.0a1's and 3.0.0a2's stores are in this one whole.
- `release.yml` publishes n+1 only when release n admits it (roadmap G12): the version PyPI publishes and the built
  wheel assess this store and agree but for the engine's identity (or as `.warrant/differential.json` declares), and
  n's own engine finds a release duty of this version closed and accepted (`python -m warrant.differential --release`).
- The review plugin's directory is `integrations/warrant-review` (was `integrations/codex-plugin`): it is no agent's.
  Reinstall with `python3 integrations/warrant-review/install.py`. In this repository's profile `claude` is a
  `pr/acceptor` beside `codex` (`.warrant/v3.json`): either reviews the other's pull requests, and neither its own (an
  attest by the head version's own actor never counts toward its guard).
- `python -m warrant.differential --python N_PYTHON [--root DIR] [--declared FILE]` (roadmap G12): the published
  release n and the head assess one store; the reports must be the same bytes but for the engine's identity, any
  other difference declared member by member (`differential/1`), else refused. First run, 3.0.0a2 against this
  head: warrant, minds, time-lab and interdict-mesh SAME.
- Roadmap: G13 (records against prose where the referent changed, a pre-registered comparison), G14 (freshness by
  content: `warrant drift`), G15 (predictions: time-lab's N1, N3, N7), and under G11 the cross-repository "what rests
  on X", once a record cites another repository.
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
