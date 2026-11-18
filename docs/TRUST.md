# What a store proves, and what it does not

A Warrant store is a file of signed records. Reading it gives a verdict for each
lineage: what may be relied on now, what still waits, for whom. This page says
which parts of that verdict rest on cryptography and arithmetic, which rest on a
choice the reader makes, and which the store cannot give at all. The normative
text is [V3.md](V3.md); the open questions are its §12.

## What it proves

- **Who signed each record.** Every record is signed by an Ed25519 key over its
  id. A line whose signature does not verify is rejected and counts for nothing.
  One exception, by the reader's choice: a record carried over from Warrant 2
  (`basis: MIGRATED`, `sig: null`) counts on the word of a migrator the reader's
  profile names, not on its author's signature (V3.md §9). This repository's
  store holds 1,446 of them. A reader whose profile names no migrator rejects
  them; one that names it trusts that migrator for what they say, and the report
  marks each such record's basis.
- **What a version needs before it counts.** A version's guard names who must
  attest it (roles, a quorum, a verdict to match, lineages it requires). The
  version is effective only when its guard is met under the reader's profile,
  and its own actor never meets it.
- **That the verdict is recomputable.** `assess` is a pure function of the
  records, the trust and the profile. Anyone holding the same bytes and the same
  receiver gets the same report, byte for byte; nobody has to be trusted to have
  computed it (the JavaScript reader in `site/` recomputes it in a browser).
- **What a version rests on.** References, lineages and requirements are hashes;
  `grounded` says whether a version and everything it rests on is effective and
  ELIGIBLE, transitively.

## What the reader decides

- **Which key is whose (trust) and who holds which role (profile).** These are
  the receiver's, not the store's. The store's `.warrant/v3.json` is the
  publisher's own receiver: reading under it shows what the publisher counts,
  and a reader who pins its own trust and profile gets its own verdicts from the
  same bytes. A name means only what a trust binds it to: `claude` in two stores
  is one source only when one key is bound to both.
- **Which stores to read.** An overlay reads several stores under the reader's
  rules, so a challenge the publisher never took in still counts for the reader
  who found it.

## What no store can give

- **That this copy is the only one.** A writer can hand two readers two
  histories, each consistent alone. Equivocation is seen only where both meet:
  a reader keeps what it accepted before and checks the next copy extends it
  (`warrant verify --extends`), or compares copies with another reader.
- **Completeness.** A store cannot show that it holds every record that exists;
  every report says `completeness: UNATTESTED`. A publisher can leave out a
  challenge it received. What is absent is not "there is none".
- **The truth of what records say.** A statement, a piece of evidence, a reason
  are data a signer chose to sign. Warrant records who stands behind them and
  who objected, not whether they are true. An agent reads them as data, never as
  instructions.
- **Time.** `at` is the signer's own clock, and claimed time orders nothing:
  the ids witness the order. A successor dated before what it succeeds still
  counts and is flagged LINEAGE_BACKDATED; the store refuses to append a record
  dated before its writer's chain head, but within that a signer dates its
  records as it likes.
- **That accepted files are still the bytes.** An acceptance names the files it
  ran on. Beside a checkout, the freshness gate compares them with the tree and
  reads a claim whose files changed as STALE; a reader with no checkout reads
  PINS_NOT_CHECKED, never ELIGIBLE.
- **That a blob is available.** A reference to a blob or a record held
  elsewhere is a hash; `warrant resolve` says where its bytes are found, or that
  they are missing.

## Threats it is built against

| Threat | What stops it |
| --- | --- |
| a forged record | the signature; a bad line is rejected, never repaired |
| a version that accepts itself | its own actor never meets its guard |
| an impostor binding a known name to its own key | the reader's own trust; in an overlay a binding the sources disagree on is not admitted |
| a challenge kept out of the publisher's store | an overlay over the stores the reader chooses |
| a writer showing two histories | its chain forks once both are read together, and `warrant status` lists the fork; one history read alone shows none, so a reader must hold what it saw before (its last accepted snapshot, `--extends`, V3.md §16) or read the other copy |
| a store too large to read | admission limits, refused as RESOURCE_LIMIT, never answered in part |
| text in a record steering an agent | every answer is marked untrusted; records are data |
| a store copying another's name | its identity is the root of its rules@1 lineage, signed under its own binding, not its `repository` string |

## Known limits

- **Repository self-governance.** The merge gate merges a pull request on a
  recorded acceptance; one model family can merge after a solo window while
  the owner is away, and the owner's brake can revert a merge only while its
  files have not changed again. Both are named in the roadmap, not hidden.
- **One cryptographic dependency.** Ed25519 comes from `cryptography`; a defect
  there is a defect here.
- **Formats are alpha.** Warrant 3 is a pre-release: record formats and
  interfaces may still change (see the README).
