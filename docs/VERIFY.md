# Verifying a package (`warrant verify`)

One party hands another a result. The receiver may be a person or an agent, with no store, no
history shared with the sender and nothing installed. It asks one question: may I rely on this?

What is handed over is a `package/3` file: the records the result rests on and the verdicts on them
(the agent interface's `handoff` with `op: export` returns `{package, digest}`; the file is the
`package` object). The receiver brings what no package can carry: its own **trust** (which keys are
whose) and its own **profile** (who holds which role). Nothing in a package can grant a role.

```sh
warrant verify PACKAGE --trust TRUST.json --profile PROFILE.json [--require ROOT ...] [--checkout DIR] [--as-of N]
warrant verify PACKAGE --config V3.json        # one file holding both: {trust, profile}
```

It reads the package alone, runs the same assessment a store gets (docs/V3.md §10), and writes
nothing.

## The exit status is the answer

| exit | means |
| --- | --- |
| 0 | every root asked for is one this receiver may rely on now |
| 1 | a root is not relied on, or the package was refused; the answer says which and why |
| 2 | the command line, or a file of the receiver's own that it names, cannot be read |
| 3 | an error of the verifier itself; never the code of a refusal |

A root is a record id: the version of a thing that was handed over. The roots are the ones
`--require` names; without it, the ones the package names, and the answer says that the sender chose
them. A root is relied on when all of this holds under the receiver's trust and profile:

- it is the **effective version** of its lineage (docs/V3.md §3): its guard is met, and no later
  version has replaced it. A lineage that forks has no effective version. A version whose guard
  waits is not it, whatever the sender's profile said.
- no counted challenge in the package stands against it;
- with `--checkout DIR`: the files its acceptances name (`files`, {path: git blob}) are still those
  bytes in the tree of DIR's HEAD. A file moved with its bytes unchanged is still those bytes. An
  acceptance made again at the new bytes makes the root fresh again; an older one stays in the
  package and reads stale. Without `--checkout` the files are listed as `NOT_CHECKED` and do not
  decide the exit. With `--checkout` and no `git` to read the tree, they read `NOT_CHECKED` and the
  exit is 1: a comparison that was asked for and not made is never read as fresh.

The gate is the exit status because an advisory answer is not enough: a model under deadline
pressure acted on a stale conclusion beside an honest freshness note in 72 of 72 runs (docs/V3.md §15).

## The answer

Standard output is one line of canonical JSON (docs/V3.md §1), the same members every time:

```
{"warrant": "verify/3",
 "rely": true | false,                         the exit status, 0 or 1
 "refused": null | {"code", "why"},            a package that was not read at all
 "package": <its digest> | null,
 "receiver": {"trust": <digest>, "profile": <digest>, "as_of": N},
 "asked": {"by": "receiver" | "package", "roots": [ID ...]},
 "checkout": null | {"tree": <git tree> | null},
 "integrity":    {"records", "blobs", "bytes"},
 "authenticity": {"signed", "migrated", "named_keys", "migrations": [{"attest", "actor", "records"}],
                  "rejected": {ID: "BAD_SIGNATURE" | "UNSIGNED"}, "duplicates": [ID ...]},
 "completeness": {"attested": "UNATTESTED", "later", "unavailable": [ID ...], "unanchored", "chain_forks"},
 "execution":    {"schemas": {NAME: ID}, "quorum", "schemas_pending": {ID: NAME}, "invalid": [ID ...],
                  "problems": [[CODE, ID] ...]},
 "roots": {ID: {"rely", "why_not": [...], "kind", "schema", "actor", "at", "basis", "rejected",
                "lineage": {"root", "state", "reliance", "verdict", "leaf", "effective", "forks"} | null,
                "guard": {"guard", "waiting", "accepted_by", "roles", "short", "open", "challenged_by"} | null,
                "accepted": [{"attest", "actor", "roles"}],
                "challenges": {ID: {"actor", "target", "counted", "why", "replays", "stands"}},
                "pins": {"verdict": "NONE" | "NOT_CHECKED" | "FRESH" | "STALE",
                         "acceptances": [{"attest", "actor", "commit", "verdict", "files": [{"path", "blob", "verdict", "detail"}]}]},
                "unavailable": [ID ...]}},
 "established": [sentence ...],
 "not_established": [sentence ...]}
```

Five things are kept apart and never folded into one word:

- **integrity**: the bytes are the bytes their names hash. A package with a line that is not a
  record, a blob not named by its hash, a member named twice, or more bytes than `--max-bytes` is
  refused whole (`refused.code`: `NOT_JSON`, `NOT_A_PACKAGE`, `BAD_BASE64`, `BAD_BLOB`, `BAD_LINE`,
  `TOO_LARGE`, `LIMITS`), exit 1.
- **authenticity**: which records carry a signature that verifies under a key the receiver's trust
  binds to their actor; which are unsigned and vouched for by a migration (the migrator's word, not
  the writers' signatures); which count for nothing.
- **completeness**: what the slice does not hold. `attested` is always `UNATTESTED`.
- **execution**: the schemas and the rules as this receiver counts them: which schemas reach its
  quorum of schema authors, what the engine lists as a problem.
- **the right to rely**, per root: `rely`, and `why_not` when it is false: `UNAVAILABLE` (the
  package holds no admitted record of that id), `NOT_A_VERSION` (an attest, a challenge, a schema),
  `NOT_EFFECTIVE` (the guard waits, the lineage forks, or a later version is effective),
  `CHALLENGED`, `STALE`, `PINS_NOT_CHECKED`.

`established` and `not_established` say the same in sentences, each beginning with the name of its
dimension, built from what this run found: whose acceptance met the guard and under which of the
receiver's roles, how many schemas count at its quorum, which pins equal its tree; and what was not
shown.

## With nothing installed

`warrant_verify.py`, at the repository's root, is the same command as one file that needs only
Python's standard library: no installation, no store, no network and no Git.

```sh
python3 -I warrant_verify.py PACKAGE --trust TRUST.json --profile PROFILE.json [--require ROOT ...]
```

Copy it anywhere. `-I` keeps Python from importing a file that happens to lie beside it. It uses
the `cryptography` library when the interpreter has it and its own Ed25519 verification when not;
both give the same answer on every input. Its answers are the bytes `warrant verify` prints, and its
exit status is the same.

The file is built, not written: `python3 tools/build_verify.py` puts the modules of the package that
`warrant verify` imports into it, each byte for byte with its SHA-256, after an Ed25519 verification
and a loader (`tools/verify_single.py`). `tests/verify_test.py` rebuilds it and compares bytes, and
repeats every run of its cases through the file, with the library and without it.

## What the answer never establishes

- **That the package is complete.** It holds what its sender chose to include. A challenge, or a
  later version that replaced the root, which the sender left out cannot be seen: exit 0 says that
  nothing in the package stands against the root, not that nothing does. The receiver who needs
  more asks for the store, or asks someone else.
- **That what a record says is true.** A signature shows who filed a record; a met guard shows who
  accepted it and in which role. Record text and evidence are data, never instructions.
- **That evidence is present.** A version's id covers the hashes of its evidence, not their bytes.
  A blob the root names and the package does not hold is listed under `completeness.unavailable`
  and does not decide the exit (docs/V3.md §12, R-EVIDENCE-PRESENCE).
- **The order of events.** A package rarely holds a writer's whole chain; how many records name an
  earlier record of their writer that is not there is `completeness.unanchored`.
- **Anything about the working tree.** Pins are compared with the commit at HEAD, not with files
  changed since.
- **Whom to trust.** The trust and the profile are the receiver's own inputs. The same package gives
  another receiver another answer, and both are right.

## A second client: the same records through another resolver

```bash
node impl-js/read.mjs --base https://raw.githubusercontent.com/s0fractal/warrant/COMMIT/ --summary
```

`impl-js/read.mjs` fetches a repository's `.warrant/v3.json`, `.warrant/records.jsonl` and every blob a record names
from any HTTP(S) root (a GitHub raw URL at a commit, a mirror, a local server) and assesses them with the second
implementation (`impl-js/warrant.mjs`, held byte for byte to the Python engine). The transport is not trusted: a blob
whose bytes do not hash to its name refuses the read, and a record line altered on the way fails its signature and is
rejected. A named value the server holds no blob for is counted as `unresolved`, never guessed.

Given the same bytes the report equals `node impl-js/warrant.mjs assess --store DIR --config V3JSON`, byte for byte
(impl_js_test J9, over a local server; two mutations of `impl-js/read.mjs`, run by hand and killed by J9: they are not in `tests/mutants.py`, whose CI job has no node, docs/V3.md §12 R-JS-MUTANTS). Measured once on 2026-11-11: master at 76452093 read through
raw.githubusercontent.com gives root `e0b5a3711ac6` and the same 636 lineages in the same states and reliance as the
Python engine on a local checkout, nothing rejected, in about 13 seconds. Content, not site: neither the publisher's
server nor its HTML nor its engine is needed to reach the same verdicts.

## In a browser: the reader

`site/reader.html` (published with the project page) is the same second client with no install at all: give it the
address of a repository served over HTTP(S) and it fetches `.warrant/v3.json` and `.warrant/records.jsonl`, assesses
them in the page with `warrant.mjs` (the file the vectors hold, linked into `site/`, not copied) and shows the store's
summary, its lineages and, for one lineage, its versions with their guards, acceptances and challenges. Nothing of
ours serves or computes any of it; `?base=URL` makes a page a link, `&l=ID` one lineage.

- **Whose rules.** The publisher's own `v3.json` unless the reader pastes a trust and a profile; the page says which.
- **Quick and full.** A quick read fetches only the blobs the assessment reads (each migration's map): every state and
  reliance is the full store's, and the page names no root, because the root covers every blob. A full read fetches
  every blob a record names (a 64-hex value that is no record's id) and gives the store's root, the one `warrant status`
  prints. Measured once on 2026-11-13, master through raw.githubusercontent.com: quick 2.1 s, full 18 s for 485 blobs.
- **No ELIGIBLE on pins it did not compare.** A browser reads no Git objects, so it cannot say whether an acceptance
  still names a checkout's bytes (`STALE`, docs/V3.md §15). A lineage whose effective version carries an attest naming
  `files` or a `commit` reads `PINS_NOT_CHECKED` there, never `ELIGIBLE`: every lineage the freshness gate can read
  `STALE` is among them.
- **Pins compared with the tree at the address (opt-in).** `--pins`, the page's checkbox or `&pins=1`: the store's
  address is a tree's root too, so each file a claims checker's acceptance names (`{path: git blob}`) is fetched at
  that path, once per path, and hashed as Git hashes a blob (SHA-1 of `blob <length>\0` and the bytes). The rule is
  the gate's (`warrant/drift.py drift`, `gate`; `warrant/claims.py acceptances`, `live`): only when the address serves
  `.warrant/claims.json`, only live `claim@1` lineages, only attests by `claims-checker` that are SIGNED in the view and
  say `accept`; an acceptance without `closure: imports/1`, or whose files are not a non-empty `{path: blob}`, is not
  fresh; a claim is fresh when any acceptance on its effective version has every file fresh; only an engine `ELIGIBLE`
  is lowered. Fresh reads `ELIGIBLE`, not fresh `STALE`. A file whose fetch fails other than by 404 answers nothing:
  an acceptance it could decide is not compared and its claim keeps `PINS_NOT_CHECKED` (a file of that acceptance
  known to differ still decides it), and the summary names the failure (`pins.refused`); a failure to fetch
  `claims.json` compares nothing. A lineage the gate does not cover keeps the rule above. impl_js_test J11 holds this
  to `warrant.drift.gate` at HEAD on claims repositories accepted by the checker's replay.
- **Where the comparison differs from the gate.** The reader says `STALE` where the gate says `ELIGIBLE`, in these
  cases, by design: a file moved with its bytes unchanged (the gate lists the whole tree and reads it MOVED; HTTP lists
  none, so 404 at the named path is not fresh); a symlink's entry (`link:<blob>`: HTTP serves a link as its target's
  name or its target's bytes, never as a link, so it is never fresh here); a path no Git tree holds (`.`, `..`, `.git`
  or empty segments: never fetched) or a blob that is no 40-hex SHA-1 id (a SHA-256 repository). Not established:
  that the address serves one commit's tree. The comparison is with what it serves, not with a checkout's HEAD; the
  transport is trusted for which tree that is (records and blobs authenticate themselves, a tree does not). It equals
  the gate when the address serves exactly a commit's tree as Git stores it, as `raw.githubusercontent.com` at a
  branch or commit does (a symlink served as its target's name, checked 2026-11-13; a branch is cached up to 300 s, and
  `records.jsonl` and the files are separate requests). A directory served from a working tree can differ in either
  direction (modified or untracked files, symlinks followed). One case can read `ELIGIBLE` here and `STALE` in the gate
  even on a commit's tree: a regular file later replaced by a symlink whose served bytes hash to the accepted blob
  (the gate reads the mode; HTTP cannot).
- **Other stores beside the one read (`--with URL`, repeatable; the page's second textarea, one address a line;
  `&with=URL`, repeatable).** Each is fetched as the main store is (quick) and assessed alone under its own
  `.warrant/v3.json`. One that cannot be read is named with its reason and the others still answer. On a lineage of the
  main store the reader lists, as voices from outside, every attest and challenge another store holds whose
  `body.target` is a version of that lineage and which that store's own assessment admits (in its view), with the
  store's `repository` name and address, the actor as that store names it, the kind, the verdict or statement and the
  time. The main store's rules count none of them: its state and reliance are unchanged, the floor counts the voices
  apart (how many, in how many stores), and the list marks a lineage that has some. A line its own store rejects is no
  voice; how many were left out is counted. A record the main store holds too is the main store's, not a voice. Unlike
  `warrant_agent/observe.py elsewhere` (observations and challenges), every attest is listed.
- **For me: the overlay.** Only when the reader gave its own trust and profile: the union of every line of the main
  store and of each store read (`warrant_agent/overlay.py compose`, the blobs each quick read fetched) is assessed under
  the reader's rules, with the keys `overlay.receiver` admits: the reader's own bindings, then a binding every store
  naming that actor agrees on (each store's own `v3.json` trust), never one for an actor the reader's own profile gives
  a role (#348); a binding held back is named, `role` or `disagree`. Beside the main store's verdict under its own rules,
  never in its place, each of its lineages whose state or reliance reads otherwise is listed, store → reader, with the
  challenges that stand for the reader and not in the store and the actors who accept a version for the reader and
  not in the store; the identity is `overlay.identity` over the stores named by their addresses. Without the reader's
  own rules there is no overlay and the answer says why. The overlay compares no pins: on both sides ELIGIBLE on an
  attest naming files or a commit reads PINS_NOT_CHECKED. Not established: that the stores named are all that was said
  (the overlay is honest, not complete); the rows are (state, reliance) of the engine, not the lens-drawn difference
  `/overlay` in `warrant_agent/serve.py` shows (`view.delta`); and the main store's view and the pin comparison stay
  under the rules the reader chose, as before.
- **What changed for me (a mark, `--mark FILE`, `&changes=1`).** «Mark all as seen» keeps, in the browser's
  `localStorage`, one mark per store address and rules identity (the digest of `{trust, profile}`, whoever gave them):
  the ids of every record the main store and each other store read hold. `--write-mark FILE` writes the same JSON,
  `--mark FILE` reads it. With a mark, the past is the marked subset of each store's lines assessed again by the same
  engine (the main store under the same rules, each other store under its own; with `--pins`, compared with the tree
  served now), as `warrant_agent/changes.py` does. A lineage is listed when its view differs (`viewOf` in
  `site/reader.mjs` is the definition: the floor's state, reliance as shown, standing counted challenges, forks,
  effective version and number of versions, named as moved; and the versions, their guards, acceptors and waits, the
  attests and challenges on them with a challenge's counted and stands, the voices from outside, named as appeared or
  vanished), new lineages as new; the new records that change no lineage's view are counted, not listed, and silence
  is said: «N new record(s) changed nothing you see». Without a mark nothing is compared and the page offers one; a
  mark under other rules is not used. `&changes=1` shows that section and the changed lineages alone. The mark keeps 8
  bytes of each sorted id and a SHA-256 of every 16 full ids (10 bytes an id; 1.33 M characters for 100 000 records,
  where whole ids in base64 are 4.3 M, near the ~5 M a browser keeps per origin); a record is seen only when its group
  is found whole and hashes to its digest, so no new record is called seen unless SHA-256 collides. A group that does
  not verify (a marked record no longer served, a new record sharing a prefix) counts its present records as new: more
  is listed, nothing hidden; gone and unverified records are counted and said. Where it differs from `/changes`: no
  lens (the view is the reader's own lineage view, so an attest by anyone on a version is a change, as under the
  built-in lens), no `grounded` member, no default past without a mark (it says there is none instead of using the
  last day), no overlay and no pin rows in the view, and an other store absent from the mark counts as wholly new.
  Not established: that the stores served are all that was said; storage that the browser drops loses the mark.
- **A watch list (`watch=ID,ID`, `--watch ID[,ID…]`).** The lineages a reader relies on, named by their roots: in the
  address, or kept in this browser per store address under `reader-watch/1` (a lineage's page has «Watch this
  lineage» / «Stop watching»; the desk reads the same key; the address wins). A value that is not 64 lowercase hex
  characters, or an id that is no lineage root here (a version of one is named with its root), is refused by name,
  never dropped. With a watch list, what changed is said of the watched lineages first, by their **frames**; the
  store-wide listing stays, collapsed under a summary. The frame of a lineage (`frame` in `site/reader.mjs` is the
  definition) is the set of record ids a reliance on it can be moved through: the closure, from every version of the
  lineage, under (a) the graph's out-edges whose relation is in `warrant/graph.py` `WALK` (lineage, requires, ref,
  attest, challenge), (b) the in-edges attest and challenge (what was said on a member), and (c) every version of the
  lineage of any member; its records of the view are the frame; and (d), with other stores read, each attest or
  challenge another store's own graph holds on an id of the closure, named with that store's address. Measured on the
  live stores, one lineage's frame is a median 0.1–0.3 % of warrant's 3065 records (6.8 % at most) and 2–15 % of
  minds' 141. Three outcomes, each in one sentence and in `watch.outcome`: **touched** — a watched lineage has a new
  record in its frame (the witness: each such record, its store, and a shortest chain of relations from it to the
  lineage, so a record three steps away says why it matters), or its own floor moved (state, reliance as shown,
  standing challenges, leaf; before and after), or its view differs; with no new record in its frame that is said as
  «moved with no new record»; **silent** — «N new record(s) at this address (URL); none is in the frame of the K
  lineage(s) you watch (F of R records)», naming every address read; **not established** — silence could not be said,
  and why: no mark this read can use (none, unreadable, of another store, of other rules), a watched value refused or
  no root here, an empty list, a store beside this one not read now, a marked record no longer served, a mark entry
  that does not verify, or pins compared with no floor of a watched lineage recorded in the mark (a mark made with a
  watch list records the floor the reader saw of each watched lineage, `floors`, so a pinned file that changed since is
  seen; without it a pins-only move would not be). With `--watch` the CLI's exit status is the gate: 0 silent, 3
  touched, 4 not established (2 stays a refused read). Without a watch list nothing changes (`changes` is answered byte
  for byte as before). Not established by silence: that nothing was said elsewhere (completeness `UNATTESTED`: only the
  records the addresses read serve now), that a lineage outside the frame cannot matter to the reader for reasons the
  graph does not hold (text, a commit, a blob's contents), or anything about a store not read.
- **Toward what you watch (`watch.toward`, `--toward-exit`).** The frame answers whether a reliance was touched; a
  goal's frame is a few records, so a reader watching goals hears silence while the work citing them moves. Beside the
  watched answer, and only when the comparison was made (never under not established), the reader lists the lineages
  of each watched lineage's **cone** (`cone` in `site/reader.mjs` is the definition: the record ids from which it is
  reachable; the closure, from every version of the lineage, under (a) the graph's in-edges whose relation is in
  `WALK` and (b) every version of the lineage of any member, graph nodes only; with other stores read, each record of
  another store with an out-edge of its own graph to a member, named with its address, the closure not going on from
  it) that are new since the mark or whose floor moved (state, reliance as shown, standing challenges, leaf), except
  the watched lineages and every lineage with a version in a watched frame (reported once, as the frame's). Each with
  its distance and a shortest chain from its nearest version, its state and reliance before and after, and the new
  records of this store touching it; newest first; with counts and a second sentence, «toward what you watch: N
  lineage(s) that reach it moved at this address (URL) (by schema) through M new record(s)». It never changes the
  outcome or the first sentence: silence is about reliance, toward about attention. Measured on the live store, a
  goal's cone is a median 22 records, at most 162 of 3070 (5.3 %); on minds at most 32 of 141. The exit status with
  `--watch` is unchanged; `--toward-exit` makes «silent with a lineage toward it» exit 5, for an agent that wants to be
  woken by work and not only by risk. The desk's watched line carries toward's count and sentence. Not established:
  the other stores' records of a cone are not listed as lineages (they are not this store's), and completeness stays
  `UNATTESTED`.
- **Where the bytes of a cited id are (`--resolve ID[,ID…]`, a lineage's page, `summary.cited`).** Each id a record
  points to (the graph's edges: lineage, prev, an attest's or challenge's target, requires, refs) gets one word from
  `resolved` in `site/reader.mjs`, over what was read: `PRESENT`, a record of this store or a blob of it fetched and
  hashed to its name (a link to its lineage when it is a version of one); `RESOLVED`, a record (its id recomputed from
  its bytes) or a hashed blob of a store read beside (`with=`), naming that address (a link to the reader there);
  `MISSING`, neither, on a full read; and `NOT_FETCHED`, the reader's own word, neither on a quick read, where no blob
  of this store was asked for (never `PRESENT` on bytes not hashed, never `MISSING` on a question not asked). There is
  no `LOCATED`: the reader fetches whole stores and has no place that names an id without holding it. A store beside
  that could not be read is named (`unread`) on an answer that did not find the bytes, never guessed `RESOLVED`. The
  CLI prints `{resolve: {ids, refused, completeness: "UNATTESTED"}}`; a value that is not 64 lowercase hex is refused
  by name. The floor summary counts every cited id by its word (`cited`); the rest of the summary is as before.
- **What waits for whom (`actor=NAME`, `--actor NAME`).** For an actor the reader names (an input on the page,
  remembered in `localStorage` for both pages; the address wins), under the rules the store was read with, the reader
  shows `warrant.graph.frontier` as Python computes it (`frontier` in `site/reader.mjs`): the roles the profile gives
  the actor; of each lineage only its leaf (a fork has none), when its guard is `PENDING`: the actor's own version is
  pending; any other it may attest when the actor filed no attest or challenge on it (the graph's `attest` and
  `challenge` edges: a line its signature rejects is no act), the guard is still short of attests, requires no lineage
  still open, and one of its roles is the actor's; and the lineages the actor wrote whose engine reliance is
  `CHALLENGED`. Each item links to its lineage. The words are the engine's, not the reader's (no pins comparison). The
  observer mostly asks it of the agents, so the actor is never assumed to be the reader; with no actor named nothing
  is computed. Not established: that the store holds every act of the actor's (completeness `UNATTESTED`); the gate's
  `due_for` adds a schema filter and a lineage verdict of `OK`, which this does not.
- **The desk (`site/desk.html`; `node site/desk.mjs`).** Several stores on one screen, one block each: name, whose rules
  (the publisher's own), records and rejected, the reliance counts (the rule above: never `ELIGIBLE` on pins not
  compared), how many lineages have a standing counted challenge, what changed since that store's mark (the reader's
  own mark: the same `localStorage` key, `markKey` in `site/page.mjs`, the same JSON and the same `changes()`; the
  changed lineages as links into the reader), a button to mark one store and one to mark all, and with an actor named
  how much waits for it there (linking to the reader with `actor=`). The stores: `store=URL` in the address
  (repeatable), else the list the reader kept on the page, else `site/stores.json` (a list of `{name, base}`, http(s)
  only, an address listed twice read once); a list that cannot be used is named, never silently replaced. Stores are
  read three at a time, each as the reader reads it (quick); one that cannot be read is named with its reason and the
  others still answer; a block is whole or a refusal. The CLI keeps a mark file per store in `--marks DIR`, named by
  the SHA-256 of the store's address (`--write-mark URL`, `--write-marks`); `--plan` prints the selection alone. Not
  established: the page itself in a browser (layout at 375 px, buttons, storage), and the stores' completeness.
- **The door: objecting to a version (`site/voice.mjs`; `site/object.html`).** On an opened lineage, beside the effective
  version and the leaf (one block when they are one version), a collapsed block «Object to this version» gives the
  commands that file a voice against exactly that version, with its full id filled in, from an empty directory and the
  released package (`python3 -m venv .venv`, `.venv/bin/pip install "warrant-graph>=3.0.0a7"`, `.venv/bin/warrant say
  --store voices ID "…"`, the directory `voices` committed as a git repository): 3.0.0a7 is the first release with
  `warrant say`, and nothing is installed into the system's interpreter. The block is built from the version's id
  alone (`targets`: an id that is not 64 lowercase hex gives no command), says what a voice is and is not (a challenge
  under the objector's own key's name, `key:<hex>`; nobody admits or removes it; not counted by the publisher's rules,
  the lineage's verdict in its store does not move; counted for a reader only when a replayer that reader trusts
  reproduces it), and offers a field that adds the address of a published store of voices to the page's `with=` list
  (`withAdded`: http(s), no credentials, once). A copy button exists where the browser offers the Clipboard API.
  `site/object.html` (no script, a policy allowing none) shows the same steps with placeholders, in
  `<pre class="command" data-step>`, and the read step (`node site/reader.mjs --base STORE_URL --with VOICES_URL
  --lineage LINEAGE_ID`). `voice.mjs STEPS` is the one source; impl_js_test J16 holds object.html to it word for word
  and runs the commands as shown in an empty directory (a clone of the checkout under test in place of GitHub, its
  own `HOME` for the key's seed, no global git configuration): the voice appears on its lineage's effective version,
  uncounted, under its `key:` actor, the store's state and reliance unchanged. Not established: that anyone reads the
  store of voices (completeness is never attested: a voice nobody reads is seen by nobody), who holds the key, the
  push to a public host (stood in for by a local HTTP server), and the block, its copy button and its field in a
  browser.
- **The desk: a published release, as data.** A second kind of entry in `site/stores.json`, `{name, base, release}`:
  `release` names the format published at `base` (one is known, `minds.published-bundles@1`; its index is
  `<base>index.json`). The desk fetches the index and shows, as published, the attestation's statement (as text), the
  chain and its tip, when it was published, the endorsers and the projection's witnesses by the roster's names (the
  publisher's word; a key the roster does not name is said so), the sentence «as published; not verified here» and a
  link to the minds page that verifies it (`?index=<the index address>`). It verifies nothing and draws no verdict: no
  pill, no word of one. An index that is not fetched, answers other than 200, is not JSON, is of another format or
  lacks a member is named with its reason and prints no release; the stores still answer. Releases are read from the
  list unless the address names the stores (`store=`). The entry keeps a `base` so that a `desk.mjs` of an earlier
  release reads it as a store it cannot read rather than refusing the list. Not established: the release itself (the
  bundles' hashes, signatures and the chain are minds' verifier's to check), and the block in a browser.
- **A transport that fails is a refusal.** Only HTTP 404 reads as absent; any other failure refuses the read whole, and
  a blob whose bytes do not hash to its name refuses it too. Nothing partial is drawn.
- **Record text is text.** The page builds no markup from a string, runs one script of its own origin and allows no
  other (`script-src 'self'`).

impl_js_test J10 holds the data the page draws to the Python engine, through node, by the functions the page runs; J11
holds the pin comparison to `warrant.drift.gate` at HEAD; J12 holds the voices and the overlay to
`warrant_agent.overlay` on the same three stores and the same reader rules; J13 holds what changed for me on a store
built in steps (one mark a step) and, from the first mark, the lineages whose (state, reliance, standing) it lists as
moved to the Python assessments of the marked subset and of the whole store; J14 holds the desk (several stores, one
unreachable and one answering HTTP 500, marks per store and equal to the reader's, a change listed in its own block
only, mark all, the default list and the selection rule) to the Python engine and to the reader's CLI; J15 holds the
frontier to `warrant.graph.frontier` for every actor of a fixture that reaches each branch of its rule, and for codex
and claude on this repository's own store; J16 holds the door (object.html equal to `voice.mjs STEPS`, the block's id
for the effective version and the leaf, hostile lineage text kept out of every command, the `with=` field, the
commands run as shown) and the desk's release block (a served fixture: well-formed, another format, not JSON, a member
missing, HTTP 500; no word of a verdict in any of them); J17 holds the watch list (the frame of every lineage of a
fixture, with another store's voice, to a closure computed from the Python report; 1000 machine records outside the
frames silent and one record three steps inside touching exactly its lineage, its witness and chain; a voice in
another store read and not read; moved with no new record under pins; each reason for not established, with its exit
status and no silence said; malformed values refused; the desk's watched line; and `changes` without a watch list
equal to a digest taken before the watch list existed); J18 holds the cone of every lineage of a fixture, with another
store and a record both stores hold, to a closure computed from the Python reports, toward on a goal (silent, two
lineages toward it with distances and chains checked by a Python breadth-first search, exit 0 and 5 with
`--toward-exit`; a lineage in both frame and cone reported once, as the frame's; no toward for any reason of not
established), the desk's toward count, `resolve` (each word, a store beside unread, malformed values) and `cited`
against a classification computed here, and the existing `watch` members and `summary` equal to digests taken from
master. No case drives a browser (neither `localStorage` nor the pages' buttons are
exercised), and the layout is checked by eye. No mutant targets these files (docs/V3.md §12 R-JS-MUTANTS), so CI does
not hold the tests to their mutants: eleven mutations of the reader were run by hand for J10, thirty-five more for J11
and J12, twenty-four for J13, and thirty-three for J14, J15 and the page-source case of J10, thirty-five for J16 and the page-source case of J10
extended to the door's files, forty-two for J17 and the page-source case of J10, forty-two for J18, each failing a case of its own on its assertion; the list is in the pull request that
added them.
