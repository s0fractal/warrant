# Changelog of warrant-graph

Each entry below is a version of the `warrant-graph` package on PyPI. Warrant 3 starts at 3.0.0a1;
2.0.0a1 was Warrant 2. **[protocol]** marks a change of the record format or of the assessment rules
(docs/V3.md).

## Unreleased

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

- `warrant resolve` (docs/HOME.md, W7): each hash a registered store cites gets one state, PRESENT, RESOLVED (its bytes
  found in another store of Home or a clone's minds chain, `refs/vars/heads/*` cells and atoms, hashed to the name),
  LOCATED or MISSING; bytes that do not hash to their name are refused. Over this Home: 4198 present, 3 resolved (minds
  cells), 2 missing. RV1, RV2; mutants T179–T182.

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
