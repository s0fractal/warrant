# Changelog of warrant-graph

Each entry below is a version of the `warrant-graph` package on PyPI. Warrant 3 starts at 3.0.0a1;
2.0.0a1 was Warrant 2. **[protocol]** marks a change of the record format or of the assessment rules
(docs/V3.md).

## Unreleased

- The publisher's rules as records (stage 2a; docs/V3.md §14): `rules@1` versions whose body, less its `state`, is
  `.warrant/v3.json` (the file their projection, canonically). Once the base holds one in force, the gate refuses a
  pull request whose head's rules in force, read under the base's trust and profile, are not its file
  (`RULES_PROJECTION`), do not succeed the base's (`RULES_CHAIN`), fork (`RULES_FORK`), are two lineages
  (`RULES_TWO`) or are challenged by the veto role (`RULES_VETO`); a version is filed by a `pr/acceptor` or `pr/owner`
  of the base, and N+1 never admits itself. The engine still reads the file: the differential against 3.0.0a7 is SAME.
  This pull request files the schema (pending until the second `schema/author` accepts it); the genesis version
  follows in a records-only one. RC1–RC10; mutants G131–G136.

- `.warrant/merge.json` watches what a receiver's `rely` rests on and the norm: `docs/V3.md`, `warrant/verify.py`, the
  single-file `warrant_verify.py`, `warrant/graph.py`, `warrant/pins.py`, `warrant/merkle.py`, `warrant/snapshot.py`.
  #393 (a new section of the specification and of the verifier) merged solo with no second family, none of its files
  being watched. With the owner present nothing waits (the brake acts after the merge); away, 24 h with two families
  or 72 h with one. Measured once: of the 98 merges of November that were not verdicts only, 17 would have been
  newly watched. E95; mutant G130.

- The bridge (`warrant/bridge.py`, `python -m warrant.bridge file|public`): a voice from someone with a GitHub account
  and nothing else. An issue opened through the form (a record id, a stance, a statement) becomes one record in a store
  of voices of the bridge's own: an objection a `challenge`, a support an `attest` with `stance: "support"` and no
  verdict, each naming the account as the bridge states it (login, id, the issue's address, the SHA-256 of the body as
  delivered). It is the bridge's statement, not the account's signature; the store gives nobody a role and no rule
  counts it. Anything but the form as opened is refused in the bridge's own words, one record per issue, and the bridge
  writes into no store but its own. The reader shows such a voice with its stance and the account, linked to the issue
  (`githubOf` in `site/reader.mjs`: shown only in its shape), and the block «Object to this version» and
  `site/object.html` have the second door. In this repository: `.github/ISSUE_TEMPLATE/voice.yml`,
  `.github/workflows/voice-bridge.yml` (the branch `voices`) and `bridge-key.yml` (the environment `bridge`).
  `site/llms.txt` tells an agent both doors, with the issue's body to write; BR6 files that body as told.
  The workflow names no concurrency group (a group cancels the run that waited: Codex on #392); runs go side by side
  and a refused push is tried again from the branch as it is. BR1–BR7, J20; mutants T221–T241.
- The reader on a phone: a paragraph or list item wraps a name with no space in it (`site/style.css`). A lineage accepted
  by an actor named by a hash (`checker sha256:…`) made the page 610 px wide at 375; measured 375 after.
- Witnessed roots (docs/V3.md §16; stage 3 of the plan): `warrant/merkle.py` gives a store two Merkle roots, its record
  ids and its reverse index (target → every attest and challenge on it), with proofs a reader checks against a root
  alone; `snapshot@1` (`warrant snapshot schema / witness / prove / show`) is a witness's lineage of what it saw, and
  a witness refuses a store that lost a record it witnessed. `warrant verify --witness FILE` answers `absence`: against
  the witnessed index root, every attest and challenge on the roots' frame is in the package, or what is missing (and
  the root is not relied on); the witness must be one the receiver's profile names `witness`; two snapshots after the
  same one are equivocation, exit 4; `--extends HELD` refuses a rollback. `completeness` stays UNATTESTED.
  `warrant/graph.py` `frame` is the reader's `frame()` (J19). The plan's stop rule (the proof larger than the frame)
  fired by its letter: a frame's proof as sent is 4.3 KB median, 1.29 times the frame, over it in 68 of 99 lineages
  (0.56 in raw bytes, the rule's unnamed basis). It is replaced: stop if the frame with its proof exceeds a tenth of
  the store for the median lineage, or if the proof needs the rest of the store; measured 0.18 % here (2.9 % at most),
  8.2 % on minds (31 % at most). WT1–WT6; mutants WM1, WM3–WM7, WM9–WM22.

- The roadmap view names every goal whatever its key (`warrant/roadmap.py`): `G<number>` keys in the order of their
  numbers, then the others by their text. A goal keyed otherwise (EXP-ADOPT-1, the adoption experiment's registration)
  ended `tools/graph.py views` in `int()`.
- A mutant runs only the sections of its test file that hold its cases (a test file's `*_cases` functions,
  `tests/world.py` `run_sections`), and its run ends at the first `FAIL` of one of its cases; the verdict is the same
  printed `FAIL <case>` line. Which section holds a case is read from clean runs of each section alone, unmutated, in
  the same copy, before any mutant: that is also the check that every section passes alone (BASELINE_RED otherwise),
  and a mutant whose case no clean run printed is NO_SECTION, never a full run. Test files without sections (core,
  shapes, the plugin's) run whole; CI's suites still run every file whole. Measured on 80 mutants (40 of tools_test,
  40 of agent_test, one laptop, 4 jobs): 496 s before, 36 s after, the map included, 80 of 80 killed both ways. CI runs
  of one pull request cancel the older one; runs on master and dispatched runs are never cancelled. Each set of two or
  more sections some mutant runs together is run so, unmutated, first (Codex on #391: two sections that pass alone
  failed together and credited a kill); a clean run past the timeout refuses as a red one does; the temporary places
  are emptied at the start (a killed run ends at os._exit). Not seen: a later section's state that would hide a kill in
  a whole run; `--whole` runs every mutant against its whole file. In CI on this pull request the mutant parts took 3 to
  4 minutes (12 to 28 before) and the whole run 7. HM1–HM5; mutants T199–T205 (the harness and `tests/world.py`
  themselves).

- A pull request of verdicts only that conflicts with the base is carried by a new one: the gate merges the base into
  its head (records only, the union of the stores) on a new branch under the same prefix, opens it as a pull request,
  starts CI, closes the old one with a comment naming the new one and deletes its branch. It no longer moves the old
  branch: GitHub held a pull_request run of the workflow token's update for the owner's approval (action_required) and
  the required check stayed expected (#379 run 43427696972, #382 run 43468860556); a pull request the token opens
  starts none. A run that failed part way is resumed with each step made once: the new pull request open, the next
  run only closes the old one; its branch made with no pull request, it opens one from it; an old branch that could
  not be deleted leaves the carry done (the analysis session on #383). Nothing is retired on a name: before the old
  pull request is closed, the carry on the branch must be the head and the base merged with the stores' union as its
  tree, and CI must have started on it (dispatched again when its dispatch failed); otherwise the old one stays open
  (Codex on #383). The carry is of the head assessed: a source whose head moved since is not carried, one that
  moves while it is carried is left open (Codex on #383 at f1da8d88: a verdict pushed after the survey was lost with
  the branch), and the source's branch is no longer deleted: GitHub deletes a ref with no expected head, so a verdict
  pushed between a read of its tip and the delete would go with it (Codex on #388 at e42e6695). The gate closes the
  old pull request, which can be undone, and deletes nothing of a branch it did not make. E84, E89, E90–E92; mutants G109–G113, G115–G120, G126.
- A dispatched CI run whose `test` passed dispatches the gate (`wake-gate` in ci.yml, nothing checked out): a run the
  workflow token starts wakes no workflow_run, and GitHub mostly skips the gate's schedule, so a green verdicts pull
  request waited for a person to dispatch the gate (#379).
  It does so after a green pull_request run of a branch of this repository too: a run approved after GitHub held it
  woke nothing either (#389).
- After a merge of verdicts only, the gate starts the claims checker when the code moved since a commit they were made at
  (its tree outside `.warrant/` differs from the base's, or Git cannot read it): #389's acceptances, made at 45f73a63,
  merged after #386 and #387 had changed the code, and nothing started the checker (75 claims read STALE). Acceptances
  made at the base's code start nothing, so there is no loop. E94; mutants G127–G129.
- `warrant --help` lists `say`.
- The gate approves a run GitHub holds for approval (action_required) at the head of a pull request it assessed as
  verdicts only (a branch of this repository, refused for nothing but its checks, its head still the one assessed),
  of a required workflow only: GitHub held such runs for the claims checker's pull requests when they were opened too
  (#389), and the owner approved each by hand. Whether GitHub lets the workflow's token approve is learnt from the
  first try: the job summary says what it answered. E93; mutants G122–G125.
- CI runs the mutants in six parts, not four: a part ran 22 to 28 minutes of its 30 (#385, #386), and every mutant
  added eats the margin; the wall time does not grow.
- The door's commands use the released package instead of a checkout (`site/voice.mjs`, `site/object.html`, the
  reader's block): a venv in the objector's empty directory, `pip install "warrant-graph>=3.0.0a7"` (the first release
  with `warrant say`), the venv's `warrant say --store voices ID "…"`. No clone is needed to object; the clone remains
  only in the optional last step, reading from a terminal with the reader's own file. Run as shown against PyPI on
  2026-11-13.

- The freshness gate (G14) reads every pinned acceptance: a signed `attest` accepting a version that names `files`,
  that the version's guard counts (its actor holds a role the guard names; `counted`), whatever the lineage's schema,
  with or without `.warrant/claims.json` (`warrant/drift.py` `pinned`); a trusted actor with no role there neither
  refreshes a pin nor makes one stale (the analysis session on this change: such an acceptance of the changed bytes
  read a stale lineage ELIGIBLE again). Until now it read the claims checker's acceptances of claims alone and only beside `claims.json`, so a
  lead's acceptance of a goal on a file's bytes stayed ELIGIBLE after the file changed, while the browser reader said
  PINS_NOT_CHECKED for any attest naming files or a commit (the analysis session, 2026-11-13). The reader now reads the
  same predicate: an acceptance at a commit alone pins nothing there either, and `--pins` reads no `claims.json`
  (its summary has no `config` member). DR30–DR32; J10, J11; mutants T184–T188, T194, T195.
- `warrant assess` applies the freshness gate to a repository's store read now, as `status`, `drift` and the agent's
  `context` do: it printed ELIGIBLE where they said STALE.
- `warrant init` in a repository (`.warrant`) leaves what the next agent reads (`warrant/entry.py`): `.warrant/v3.json`
  naming the repository (GitHub's `origin`, else the directory) with an empty trust and profile, so `warrant status`
  reads the store it just made (it refused it, W4); the block the adoption experiment measured in `AGENTS.md`, byte for
  byte between `<!-- warrant:begin -->` and `<!-- warrant:end -->`, and `@AGENTS.md` in `CLAUDE.md`, never over a file's
  own text and written once; a read-only `.warrant/agent.json` and the server `warrant` in `.mcp.json` beside the
  others (Claude Code asks the user to approve it the first time: its behaviour, not a defect). `--no-entry` skips the
  markdown files, `--no-mcp` the server; a store not named `.warrant` is made alone, as before. The experiment (#385,
  plan 4dd5fdc4, result 4f239352): with the repository as `init` left it 0 of 18 agents used the records, with the
  block and the server 18 of 18, on both models and every task; its rule R1 said ship it, so the default is the pair it
  measured. Not measured: the block without the server, the comment marks around it, agents that read no `.mcp.json`.
  `warrant status` names the receiver: how many actors are trusted and who holds which role, or that no actor holds
  one, so no acceptance counts yet; and with no schemas, that `warrant bootstrap` files them. IN1–IN3; mutants
  T189–T193, T196, T197.

## 3.0.0a7 — the owner as observer; claims on a runner; a stranger's path

Read first:
- **`code` names the Unicode version.** The engine's `code` now includes the interpreter's Unicode version, so the
  reports of this release under two Pythons with other Unicode tables have different `code` and `assessment`, on
  purpose: an actor id's verdict can differ between them (R-INTERPRETER).
- **`warrant say` and `warrant resolve` are in the package.** `warrant init --voices` and `warrant say` file a voice
  under one's own key with the package alone; `warrant resolve` says where the bytes of each cited hash are.
- **Merges are the gate's.** With the owner present the brake acts after a merge. A pre-release leaves with brakes open
  in its history (this one did: #361, #365, #374, #375); a stable release waits for every brake. The claims checker runs
  on a runner, and its acceptances name each witness's import closure.

- A pre-release (PEP 440 `aN`, `bN`, `rcN`, `.devN`, by the whole version the package declares) is released with brakes
  open; a stable release still waits for every brake (owner, 2026-11-13). `brakes --version V`; release.yml passes the
  version. A revert of a merge that a published version holds names that version in its pull request (an obligation for
  an agent, a yank the owner's act). s0fractal/warrant#376; E87, E88; mutants G104–G107.

- The reader's pages show a record's invisible direction and width controls (U+200B to U+200F, U+202A to U+202E,
  U+2066 to U+2069) as their code points in angle brackets instead of obeying them (`plain` in `site/page.mjs`,
  through `el()` and `fill()`): a right-to-left override in a statement redrew the rest of its title backwards.
  Attributes and the CLI's JSON keep the bytes.
- The browser reader says what moves toward what you watch, and where the bytes of a cited id are. Beside the watched
  answer, when the comparison was made, `watch.toward` lists the lineages of each watched lineage's cone (`cone` in
  `site/reader.mjs`: the closure, from every version, under the graph's in-edges in `warrant.graph.WALK` and every
  version of a member's lineage; with other stores read, their records with an edge to a member) that are new or
  whose floor moved since the mark, outside every watched frame, each with its distance, a shortest chain, its state
  and reliance before and after and its new records; a second sentence, «toward what you watch: N lineage(s) that
  reach it moved at this address (URL) (…) through M new record(s)». The outcome, its sentence and its exit status do
  not change; `--toward-exit` makes «silent with something toward» exit 5. The page draws «Toward what you watch»
  under the watched answer; the desk's watched line carries the count. On a lineage's page each version lists what it
  cites with a word of `resolved`: PRESENT, RESOLVED (a store read beside, named), MISSING, or NOT_FETCHED (a quick
  read: no blob asked for, never PRESENT on bytes not hashed); no LOCATED in a browser. `--resolve ID[,ID]`;
  `summary.cited` counts every cited id by its word. Not established: completeness (UNATTESTED), the other stores'
  records of a cone as lineages, and the pages in a browser (no case drives one). docs/VERIFY.md; impl_js_test J18
  (the cone against a closure computed from the Python reports; the `watch` members and `summary` equal to digests
  taken from master); no mutant (R-JS-MUTANTS): forty-two mutations run by hand, each failing a J18 case or the
  page-source case of J10 on its assertion, not held by CI.
- The browser reader gains a watch list. A reader names the lineages it relies on (`watch=ID,ID`; «Watch this
  lineage» on a lineage's page, kept per store under `reader-watch/1` and read by the desk too; `--watch`), and what
  changed is said of those first, by their frames (`frame` in `site/reader.mjs`: the closure from every version of the
  lineage under the graph's out-edges in `warrant.graph.WALK`, the in-edges attest and challenge, every version of a
  member's lineage, and other stores' attests and challenges on the closure): touched, with the witness (each new
  record in the frame, its store, a shortest chain of relations to the lineage) and the floor before and after, or
  «moved with no new record»; silent, «N new record(s) at this address (URL); none is in the frame of the K lineage(s)
  you watch (F of R records)»; or not established, with its reason (no usable mark, a value refused or no root here, a
  store beside not read, a marked record gone, a mark entry unverified, pins compared with no floor recorded). A mark
  made with a watch list records the watched floors. With `--watch` the CLI exits 0 silent, 3 touched, 4 not
  established. The store-wide listing stays, collapsed under a summary; without a watch list `changes` is answered
  byte for byte as before. The desk shows each store's watched line. Not established: completeness (UNATTESTED; the
  sentences say «at this address»), and the page and the desk in a browser (no case drives one). docs/VERIFY.md;
  impl_js_test J17; no mutant (R-JS-MUTANTS): forty-two mutations run by hand, each failing a J17 case or the
  page-source case of J10 on its assertion, not held by CI.
- The browser reader gains a door for a reader who disagrees. On an opened lineage, beside the effective version and
  the leaf, «Object to this version» gives the commands that file a voice against that version (its full id filled in;
  the checkout form, `python3 -m warrant say --store ../voices ID "…"`, since 3.0.0a6 has no `warrant say`), what the
  voice is and is not (a challenge under `key:<hex>`, admitted and removable by nobody, not counted by the publisher's
  rules, counted for a reader only when a replayer it trusts reproduces it), and a field that adds a store of voices to
  `with=`. `site/object.html` (no script) gives the steps with placeholders; `site/voice.mjs STEPS` is their one source.
  The desk shows minds' latest published release from a second kind of entry in `site/stores.json` (`{name, base,
  release}`): statement, chain tip, when published, endorsers and witnesses by roster name, «as published; not verified
  here», a link to the minds page that verifies it; an index that cannot be read is named. Not established: that anyone
  reads a store of voices (completeness UNATTESTED), the push to a public host, the release itself (the desk verifies
  nothing of it), and either page in a browser (no case drives one). docs/VERIFY.md; impl_js_test J16 (the commands
  run as shown, against a clone of the checkout under test; the release block on a served fixture); J14's default-list
  case now leaves the release entry out; no mutant (R-JS-MUTANTS): thirty-five mutations run by hand, each failing a
  J16 case or the page-source case of J10 on its assertion, not held by CI.
- The browser reader gains a desk and a frontier. `site/desk.html` (`node site/desk.mjs`) reads a list of stores
  (`store=URL`, else the list kept on the page, else `site/stores.json`: this repository's store and minds') three at
  a time and shows one block each: counts as the reader shows them, lineages with a standing counted challenge, what
  changed since that store's own mark (the reader's mark: same key, same JSON, same `changes()`), mark one, mark all;
  one that cannot be read is named and the others answer. `actor=NAME` (reader and desk; remembered) shows what waits
  for that actor under the store's rules: `warrant.graph.frontier` mirrored in `site/reader.mjs` (may attest, own
  pending, own challenged). Sonar's findings on the reader fixed with no change of output (`storage()` touches
  `length` in a statement with an effect; `unmark`, `changes` and the CLI's `main` split into named helpers; drawing
  helpers shared in `site/page.mjs`). Not established: either page in a browser (no case drives one: storage,
  buttons, layout at 375 px), the stores' completeness, and the gate's `due_for` filters (schemas, verdict OK), which
  the frontier does not apply. docs/VERIFY.md; impl_js_test J14 (against the engine and the reader's CLI), J15
  (differential against `warrant.graph.frontier`, on a fixture and on this store for codex and claude); no mutant
  (R-JS-MUTANTS): thirty-three mutations run by hand, each failing a J14, J15 or J10 case on its assertion, not held by CI.
- The browser reader says what changed for its reader (`warrant_agent/changes.py` without lenses). «Mark all as seen»
  keeps the ids of every record of the stores read, per store address and rules identity (`localStorage`; the CLI's
  `--write-mark FILE`, `--mark FILE`), as 8 bytes of each id and a SHA-256 of every 16 (exact: a record is seen only
  when its group hashes to its digest; a group that does not verify counts as new). The past is the marked subset
  assessed by the same engine under the same rules; a lineage is listed when its view (`viewOf`: floor, versions,
  guards, attests and challenges, voices from outside) differs, with what appeared, vanished and moved; the new records
  that change nothing are counted; no mark, or a mark under other rules, compares nothing and says so; `&changes=1`
  shows only that. Not established: the page and its storage in a browser (no case drives one); the overlay and pin
  rows are outside the view. docs/VERIFY.md; impl_js_test J13 (one case against `warrant.engine` on the marked
  subset); no mutant (R-JS-MUTANTS): twenty-four mutations run by hand, not held by CI.
- The browser reader reads beyond the one store. Pins on request (`--pins`, a checkbox, `&pins=1`; off by default):
  each file a claims checker's acceptance names is fetched at its path under the store's address and hashed as a Git
  blob, and each claim the freshness gate covers reads ELIGIBLE or STALE by the gate's rule (`warrant.drift`: the
  checker's signed accepts, the closure rule, any acceptance fresh); a fetch that fails other than by 404 answers
  nothing (PINS_NOT_CHECKED, the failure named); a moved file, a symlink's entry and a non-SHA-1 blob read STALE where
  the gate reads ELIGIBLE. Other stores (`--with URL`, `&with=`): each assessed alone under its own rules, one that
  cannot be read named; their admitted attests and challenges on the main store's versions shown as voices from
  outside, never counted, a rejected one counted as left out. With the reader's own rules, the overlay of
  `warrant_agent.overlay` (its receiver, #348 included) beside the store's verdict, the lineages that read otherwise
  listed; it compares no pins. Not established: that the address serves one commit's tree (a regular file replaced by
  a symlink whose bytes hash to the accepted blob reads ELIGIBLE where the gate reads STALE), and that the stores named
  hold all that was said. docs/VERIFY.md; impl_js_test J11 (against `warrant.drift.gate`), J12 (against
  `warrant_agent.overlay`); no mutant (R-JS-MUTANTS): thirty-five mutations run by hand, not held by CI.
- The board (`python -m warrant.board manifest|plan|sync`): goals and obligations as rows of a GitHub Project, one way.
  The manifest is a pure function of the stores and names their snapshots; statuses are the records' own (`Claimed,
  not accepted` apart from `Accepted`, never one "Done"); a hand edit on the board is undone and named by the next
  sync; record text lies in a code fence, so the board mentions nobody. docs/REPOSITORY.md; tools_test BD1–BD5 (a
  board in memory: GitHub's own answers are not tested), mutants BM1–BM10.
- The reader in a browser (`site/reader.html`, with the project page): a store fetched from any HTTP(S) root and
  assessed in the page by `warrant.mjs`, under the publisher's rules or the reader's own; the summary `warrant status`
  gives, the lineages, and one lineage's versions with their guards, acceptances and challenges. A quick read (the
  migration maps alone) names no root; a full read gives the store's. It never prints ELIGIBLE on pins it did not
  compare (`PINS_NOT_CHECKED`), a failed transport is a refusal, and record text is drawn as text. docs/VERIFY.md;
  impl_js_test J10 (no mutant: R-JS-MUTANTS; eleven mutations run by hand).
- **[protocol]** Reasons no longer depend on the interpreter (R-INTERPRETER narrowed): a value a reason quotes (a
  schema, an actor, a state, body member names, a duplicate member, blob names) is written as JSON with every UTF-16 unit
  outside space..~ escaped and keys in code point order, not as Python's `repr`; a package's blobs are read by the
  format's own base64 rule (RFC 4648 §4, its one padded form) with the single sentence «a blob is not base64», not by
  binascii's words of the running Python. `impl-js/` gives the same bytes; its vectors no longer depend on CPython
  3.13. Reports with no problem whose reason quotes a value are unchanged. Tests U29 (three blobs), U44; mutants UM43 (the agent's refusal
  sentence), UM54, UM55.
- A writer's chain forks taken in (`warrant/chains.py`, `warrant join --actor A`): §7 lists every fork, and a writer
  that files on two Git branches forks its own chain at every merge (warrant's store: 16 forks, 11 of claude and 5 of
  codex), so a writer showing two histories to two readers read like any merge. A `joined` attest by the writer, on
  the line its head continues, takes a branch in; `warrant status` names apart the writers with a fork still open
  (`chain_forks_open`). A joined fork stays listed; only the writer can join its own; nothing here is read by a guard
  or the gate. tools_test CJ1–CJ4 (CJ4: Codex F1, a branch its schema refuses), mutants T156–T162.
- A second client (`node impl-js/read.mjs --base URL`): a repository's records fetched over HTTP(S) from any root and
  assessed by the JavaScript implementation give the same report, byte for byte, as the store read from disk; an
  altered blob is refused, an altered line rejected. Read through GitHub, master gives the Python engine's root and
  every lineage's state. docs/VERIFY.md; impl_js_test J9 (two mutations of read.mjs run by hand, not in tests/mutants.py: R-JS-MUTANTS).
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
- Overlay key bindings (security): an actor the reader's own profile gives a role is admitted only from the reader's
  own trust. "Every source naming it agrees" could be one store, which bound a role holder to its own key and signed
  that holder's acceptances: at 78a9d4e0 a forged acceptance settled a version for the reader. Such a binding is now
  named on `/overlay`, not admitted; an actor with no role is still admitted when its sources agree (Codex review
  2026-11-12). agent_test OV6, mutants A201, A202; A155 retargeted.

- Claims freshness reads the import closure (G14; Codex's counterexample, 2026-11-13). A claims checker acceptance named
  only each witness's test file and each mutant's mutated file and test, so a change to a module the witness ran
  (`records.py`, `jcs.py`, `store.py`, `tests/world.py`) left the claim fresh. `files_of` now names the import closure
  of each of those files, resolved by the import system as the file runs (`warrant/imports.py`, the walk the gate's
  closure test already used, now with `-m`/`-c` programs); a closure that cannot be established is not accepted.
  Acceptances say `"closure": "imports/1"`; one without it reads `UNKNOWN` (STALE). `claims replay` runs again only the
  claims none of whose acceptances names the files this commit holds for them (CF1–CF4, E60; V3-15-3). `warrant status`
  in a checkout counts STALE as G14 reads it (on master it said ELIGIBLE 612 while 96 claims read STALE; CF5, V3-15-1).
- The owner becomes an observer with a brake (2026-11-13; his last positive act in warrant is merging this). The
  profile: he leaves `roadmap/acceptor` and `schema/author`, holds `challenger`, and `claude` and `codex` join him as
  `roadmap/owner` (OB1: as of the transition no lineage changes state or reliance). The gate: owner paths shrink to
  `.github/` and `.warrant/merge.json`; AGENTS.md, `.warrant/v3.json`, `.warrant/v3/` and the gate become a
  `constitutional` tier (72 h with two families, 7 days with one; a configuration where it is shorter than the
  watched tier is refused); the gate itself merges a change once its solo window passes (no agent merges under the
  owner's login), and `solo` merges an unaccepted change to no listed path once its checks are green (window 0 h); one comment names the owner when
  a constitutional window opens. The claims checker moves to a runner (`claims-key.yml`, `claims-replay.yml`, the
  environment `claims`); its acceptances arrive from `claims/verdicts/` and the gate merges them after CI re-executes
  them (the merge observation says `how`: solo, accepted, verdicts or hand; E56, E61–E66, MR1; V3-14-6, -9, -33, -38, -42, -43 new versions; V3-14-44..46). The engine still lets an actor
  release its own obligation: an obligation (G10) asks for `obligation@2`.

- The brake after the merge (owner, 2026-11-13: «ми багато не зробимо, якщо по 72 години будемо чекати»). While the
  owner is present (`presence`: a merge of his on GitHub within 14 days), a watched or constitutional change merges with
  no window once its checks are green; its merge commit carries a brake as long as the window would have been, the
  gate comments once naming him, and his `hold` label or challenge within it makes the gate open and merge the exact
  revert (records kept; `gate/revert/`, merged as `how: revert`). Away, the windows come before the merge as before.
  No release is published while a brake in its history is open (release.yml, `warrant.gate brakes`). E67–E73;
  mutants G71–G84; V3-14-41, -42 new versions, V3-14-47..50.
- Codex's review of #350 (challenge 338a305e15a4, reproduced at 8278d4a3): a merge a second family accepted was
  recorded as solo (F1), and a commenter whose login only began with `github-actions` could suppress the
  constitutional notice (F2). Solo now applies only when an acceptance or a family is missing; the notice's mark counts
  only from `github-actions[bot]`. E74, E75; mutants G85, G86.
- Presence by a touch (the analysis session): a reaction of the owner's login to a comment of the gate is a sign of
  presence as his merge is; the gate's comments say until when he counts as present, and when that ends the gate opens
  one issue naming him (the mode never changes silently). The constitutional notice is no longer posted on a change that
  also touches an owner path (observed on #356: it promised a merge the gate would not make). Brake and revert lines are
  whole lines checked by shapes (S6 on #356: the patterns copied a hex shape and ended in `$`). E76–E79; mutants
  G87–G92.
- A stranger's path, from W4's walk (.drafts/W4-STRANGER-PATH-2026-11-13.md): `warrant init --voices` makes a store of
  voices (trusting nobody, no roles) and `warrant say RECORD "text"` files a challenge into it under the agent's own
  key, with the package alone (the commons moved into the core, `warrant/commons.py`; `warrant_agent.commons` wraps
  it). `claims view` names each claim's leaf version id, the id a challenge targets. `across challenges` lists the
  voices no store counts, marked `uncounted`, beside the standing challenges. VS1, X10, DR1; mutants T171, T172, X52,
  X53 (A162–A173 now on warrant/commons.py); V3-13-23.

- Codex's three findings on #356's last head (e8508e7f), reproduced at master 58e3cc74: `brakes` read only 300
  first-parent commits, so a brake followed by more read closed for releases and for the revert (dccff737, P1); the
  gate's exact-revert check compared object ids only, so its revert with an owner path turned into a link passed
  (7a84e332, P1); an expired presence returned no deadline, so its end was never announced (cd8d1a0b, P2). The whole
  first-parent history is read in one batch; modes and types are compared; signs are read back to twice `days`.
  E80–E82 (Codex's cases); mutants G93–G95.

- `claims verify --done FILE` skips the acceptances a run of the same branch re-executed and found holding, and records
  what held; CI keeps that file per branch (actions/cache), so after the gate merges a moved base into a branch of
  verdicts only, its next run re-executes only what is new. On a branch run by dispatch CI's base is now the merge base
  with master, never the branch's previous head (which would have verified nothing after such a merge). claims-replay
  opens no second pull request of acceptances while one is open. C20; mutant T173. After Codex's review of #367: the
  done file is refused when Git tracks it (a pull request could have committed it and skipped a replay), each entry
  counts only for the checker code that wrote it, CI restores and saves it for branches of this repository only and
  reads it before the branch's finding tests run (it saves time across runs of one branch, it is no defence against
  that branch's author), and the open-PR guard counts only branches of this repository (a
  fork's claims/verdicts/* would have stopped the checker). C21; mutants T176, T177.
- A pull request of verdicts only that conflicts with the base only in its records (GitHub applies no merge=union,
  R-UNION-ON-FORGE) gets the base merged into its branch by the gate: the union of both stores in canonical order, the
  head's blobs kept, a merge commit made through GitHub's API, CI started on it. The claims checker's acceptances
  (#364) run CI for about 40 minutes, so without this the base always moved first and the pull request never merged.
  E84; mutants G98–G100.
- Codex 8caa1ce8 (P1, reproduced at 58e3cc74 and 3a0e18f8): `enforce_brakes` held back a vetoed merge's revert when
  any open pull request sat on a branch named `gate/revert/<pr>-*`, a fork's refused one by anyone included. A revert
  now counts as pending only when the gate assessed an open pull request as that merge's exact revert, and an exact
  revert must come from a branch of this repository. E83, E70; mutants G96, G97.

- Narrower claim closures (the analysis session, #364: all 136 claims STALE after one change to `warrant/gate.py`). A
  witness file's import closure is the closure of its widest case: core_test's T15 imported the CLI, which reaches the
  whole package, so every core claim named the gate. T15 moves to tools_test as K12, and `claims.py` reads the store
  at a base from Git itself instead of through the gate (`drift`, which imports it, no longer depends on the gate).
  core_test's closure is 9 files, not 24. `warrant.claims closures` prints each witness file's closure size and the
  claims on it. CF6, K12; mutant T175; V3-8-7.

- `after_merge` (`.warrant/merge.json`): after its own merge the gate starts the listed workflows on the base, as it
  starts the required ones: `pages.yml` when the merge changed `site/`, `claims-replay.yml` after every merge but one
  of verdicts only. A merge with GITHUB_TOKEN starts no push workflow, and GitHub ran 5 of 52 scheduled gate runs in
  26 hours, so the site and the checker had not run after the gate's merges. E85, E86; mutants G101–G103.
- `graph.grounded` no longer reads an obligation's `answers` (the goal it answers, which `warrant.roadmap` also cites
  in refs) as a ground: a met goal citing the obligations that answer it made each read CYCLE. In minds 18 of 19 goal
  and obligation versions read not grounded, 88 CYCLE rows; now 0 and 0 (warrant unchanged, 0 and 0). GR4; mutant T183.
- `warrant resolve` (docs/HOME.md, W7): each hash a registered store cites gets one state, PRESENT, RESOLVED (its bytes
  found in another store of Home or a clone's minds chain, `refs/vars/heads/*` cells and atoms, hashed to the name),
  LOCATED or MISSING; bytes that do not hash to their name are refused. Over this Home: 4198 present, 3 resolved (minds
  cells), 2 missing. RV1, RV2; mutants T179–T182.

- The engine's `code` names the version of the interpreter's Unicode tables (minds #94: `"\U00016D67\U00016D67"` is
  an actor id under Unicode 14 and 15, not under 16 and 17, so Python 3.11 and 3.15 gave different verdicts under one
  `code`). Every report's `code` and `assessment` change once. R-INTERPRETER names the class; an obligation asks for a
  Unicode version in the format. UC1; mutant V106.

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
