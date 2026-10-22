# Warrant 2 — Specification

**Status:** current. This document replaces the record format of Warrant 0.x
(SPEC v0.4, settlement, `ski@v1` reasons, threshold policies, key state). That
generation is historical: it is preserved at the git tag
`history/warrant-0.x-2026-10-18`; `HISTORY.md` maps what was retired and what
replaced it. Key words MUST / MUST NOT / SHOULD / MAY per RFC 2119.

The reference implementation is the Python package in `warrant/`. It is the only
implementation of this document. Earlier Go, Rust, WASM and JS implementations
implement Warrant 0.x and are not implementations of this document.

## 1. Purpose

Warrant records transitions of work so that the next agent can use what was done
without rereading a conversation, and without crediting it with more than its
grounds support. A transition says what was done, on what basis, what it
established, which exact conditions it closes, which questions it opens and what
it leaves unestablished. Assessment answers, for one fixed view: which conditions
are closed, by whom and on what basis; what a given use may rely on now; and what
is still open, for whom.

Review is one application. So are ordinary decisions, running services, periodic
obligations and reproducible computations.

## 2. Encoding

- **JSON values.** Objects with string keys, arrays, strings, booleans, `null` and
  integers in −(2^53−1)..2^53−1. No floats. Strings MUST NOT contain lone
  surrogates. Every object named below has a closed set of members: an unknown
  member, a missing required member, or a value of the wrong JSON type makes the
  record invalid. Type is checked before membership in any enumeration.
- **Canonical bytes** are RFC 8785 (JCS) over that domain: members ordered by
  UTF-16 code units, no whitespace. `canon(x)` denotes them.
- **Hashes** are lowercase hex SHA-256, 64 characters. A **blob** is any byte
  string, addressed by `sha256(bytes)`.
- **Time** is integer Unix seconds.

## 3. Records

A record is

```json
{"warrant": "2", "type": "<type>", "actor": "<actor id>", "at": <int>, "prev": <record id or null>, "body": {...}}
```

Its id is `sha256(canon(record))`. It is stored as the canonical bytes of
`{"record": <record>, "sig": {"key": <hex64 key id>, "ed25519": <hex128>}}` in
`records/<id>.json`. The signature is Ed25519 (RFC 8032, cofactorless; small-order
and non-canonical public keys rejected) over the 47 bytes
`"warrant-sig-v1:" || id_raw`, where `id_raw` is the 32-byte id. A key id is the
SHA-256 of the 32-byte public key.

A record is **authentic** iff its stored bytes are canonical, its id matches, and
its signature verifies under a key that the recipient's trust file binds to the
record's `actor`. A trust file binds keys to actors; it authenticates and
authorizes nothing else (§6).

An **actor id** is a non-empty string of at most 200 code points, in Unicode
Normalization Form C, with no control character (general category Cc) and no
white space (Unicode White_Space) at either end. An actor may be a person, a
model, a program or a rule (for example, a checker named by the hash of its
code); Warrant does not assess what an actor is (§6).

`prev` is the id of the record the same actor filed before this one, or null for
the actor's first record: each actor's records form its **chain**. A record
without `prev` is **unchained**: it is valid, and no chain orders it; every
record filed before chains is one. A writer takes `prev` from its actor's head
in the store: of the records the writer's trust authenticates as the actor's and
that are chained back to a genesis, the latest one no other names as its `prev`.
It reads the head under a lock on `records/` and refuses to date a record before
it; a record the reader rejects, or an unanchored one, is never a head. `warrant-agent`
prepares a draft on the signer's head under the workspace's trust and commits it
only while that head is unchanged, a compare-and-swap; otherwise it answers
`CONFLICT` with reason `CHAIN_MOVED` and files nothing. A reader or a writer may
remember the verdict of authenticating a record file, keyed by the trust's
digest, the record's id and the digest of the file's bytes: every file is still
read and hashed, and a remembered verdict changes the cost of a read, never
which records count. Verdicts kept across processes are their owner's, outside
every store: each entry carries a MAC, over its key, its verdict and the
identity of the code that computed it, under a secret only the owner reads; an
entry that does not verify is ignored, and no snapshot, digest or handoff
includes them.

There are six types. They are distinct so that a claim, a permission, an
execution observation and an acceptance can never be read as one another.

| type | body says | filed by |
| --- | --- | --- |
| `duty` | a condition someone owes someone | its holder |
| `transition` | work done: basis, results, closures, questions, residual | whoever did it |
| `accept` | acceptance of one exact closure, or of a transition's results | the accepting party |
| `observation` | what an observer saw, when, how, within which bounds | the observer |
| `grant` | permission to perform a named act on named duties | the grantor |
| `challenge` | a counterexample against a transition's closure or results | anyone |

`prior` edges do not exist: every relation is a typed field below.

### 3.1 duty

```
statement   string ≤ 400 code points
holder      actor; MUST equal the record's actor
owed_to     non-empty list of actors
accept_by   list of actors whose acceptance a closure needs
release_by  list of actors who may release it (owed_to may always release)
condition   one of:
  {"attest": {}}
  {"observe": {"observers": [actor…], "probe": hex64, "expect": string, "fresh_for": int|null}}
  {"compute": {"runtime": <runtime id, §7>, "input": hex64, "environment": hex64, "expect": hex64}}
schedule    null | {"start": int, "every": int > 0}
requires    list of duty ids that MUST be discharged before this one
serves      list of duty ids this one serves (a purpose link; it grants nothing)
answers     null | question reference (§3.2)
subject     null | hex40|hex64: the exact revision or blob the duty is about
```

A duty whose condition is `attest` MUST name at least one `accept_by` actor other
than the holder: an attestation that nobody else must accept would close itself.

### 3.2 transition

```
basis        "ATTESTED" | "OBSERVED" | "REPLAYED"
evidence     list of hex64: blobs or record ids the transition relies on as evidence
relied_on    list of record ids of earlier transitions whose results it uses
established  list of strings: what this transition establishes
residual     list of strings: what it explicitly does not establish
opened       list of {"text": string, "scope": null|string}: new questions
closes       list of items (below)
subject      null | hex40|hex64: the revision the results were established on
supersedes   list of transition ids whose results these replace
triggers     list of triggers (§5) on the transition's own results
```

A **question reference** is `<transition id>:<index into opened>`. Opening a
question assigns it to nobody.

An **item** closes, transfers or revalidates one duty:

```
duty         duty id
act          "discharge" | "impossible" | "release" | "delegate" | "substitute" | "revalidate"
evidence     list of hex64, a subset of the transition's evidence
period       int, required iff the duty has a schedule and act is discharge
to           actor, required iff act is delegate or substitute
revalidates  non-empty list of transition ids, required iff act is revalidate
triggers     list of triggers (§5) (discharge, impossible, revalidate only)
```

### 3.3 accept

```
transition   transition id
item         int index into closes, or null to accept the transition's results
evidence     the exact evidence list of that item (or of the transition, for null)
support      list of hex64: the acceptor's own references
```

An acceptance binds exactly one (transition, item, evidence set). An acceptance of
another transition, another item or another evidence set is not this one.

### 3.4 observation

```
target   string: what was observed (service, endpoint, artifact)
probe    hex64: blob describing the method (request, command, criterion)
window   [from, to]: when the observation ran, from ≤ to ≤ the record's at
result   string: what was observed, verbatim
raw      list of hex64: captured outputs
```

### 3.5 grant

The grantor is the record's actor.

```
grantee    actor
acts       non-empty sorted list from {"release"}
delegable  sorted subset of acts the grantee may grant on
duties     non-empty sorted list of duty ids
expires    int | null (exclusive)
parent     null | grant id this one attenuates
```

### 3.6 challenge

```
target     transition id
item       int | null
statement  string
evidence   list of hex64
```

A challenge with an integer `item` concerns the closure of that item of its
target only; one with `item` null concerns the transition's results, not its
closures.

## 4. Assessment

An assessment is a pure function of one **view**: the snapshot (the set of record
and blob bytes, read once), the recipient's trust file, the recipient's profile
(§4.6), the time `as_of`, the set of revisions the recipient treats as current,
the recipient's workspace (repository and commit, for §5) and the identity of the
evaluating code and provider (§7). Records with `at > as_of` are not in the view.
Unauthentic or malformed records are listed and excluded; they never abort the
assessment and never count.

The **assessment id** is the SHA-256 of the canonical description of all those
operands. Changing any operand that can change a verdict changes it; moving the
same bytes to another directory does not. A snapshot cannot attest its own
completeness: every report states `completeness: UNATTESTED`, and a reference to a
record or blob that is not in the view is reported as missing, never as absence.

**Position** of a record is `(at, rank, id)`: records with the same `at` are
ordered by id, except that a record chained to a predecessor with the same `at`
follows it; positions are totally ordered.

A record is **chained** to its `prev` iff that record is in the view, was filed
by the same actor and is not dated after it; otherwise it is **unanchored**, and
the report lists it under `chains` with the reason (a `prev` not in the view is
also missing). The chain orders an actor's records: one is before another iff it
is reached from the other along chained `prev` links. Two records of one actor
naming the same `prev` are a **fork**, listed under `chains`; no record is
excluded for it, and the chain orders neither branch against the other. `at` is
what its signer claims: the records witness only each actor's chain, and between
two actors' records positions follow the `at`s they claim.

### 4.1 Who may file an item

| act | filer | also needs |
| --- | --- | --- |
| discharge, impossible, revalidate | the holder or a delegate **at the item's position** | condition met (§4.2), required acceptances |
| delegate | the holder at its position and at its effect position | acceptance by `to` |
| substitute | the holder at its position and at its effect position | acceptance by `to` and by one of owed_to ∪ release_by |
| release | an actor in owed_to ∪ release_by, or the grantee of a valid grant (§4.5) | — |

A transfer takes effect at its **effect position**: the latest of its own position
and the earliest qualifying acceptances. Transfers are applied in order of effect
position. Holder and delegates at a position are
those after every admitted transfer whose effect position is not after it. A
later transfer neither authorizes an earlier filing nor invalidates an earlier
admitted one. `serves`, a key binding, or being named in a duty grant no authority.

For a filing, its filer's own records are ordered by the chain, not by `at`: an
acceptance by `to` makes `to` the holder or a delegate for `to`'s filing only if
the acceptance is before that filing in `to`'s chain. An admitted transfer filed
by the filer itself is in effect for every filing of the filer that the chain
does not order against the transfer.

### 4.2 When a closure is admitted

An item `discharge` (or `revalidate`) for duty D is **admitted** iff:

1. its filer may file it (§4.1);
2. every evidence hash resolves in the view to bytes with that hash;
3. the transition's basis matches D's condition:
   - `attest`: basis `ATTESTED`;
   - `observe`: basis `OBSERVED`, and the item's evidence names an observation
     record in the view, by an actor in `observers` who is not the filer, whose
     `probe` equals the condition's, whose `result` equals `expect`, and — for a
     scheduled duty — whose window lies inside the period;
   - `compute`: basis `REPLAYED`, and the recipient's own replay (§7) of the receipt
     the item cites reproduces `expect`;
4. every duty in D's `requires` is DISCHARGED in this view;
5. every actor in `accept_by` has accepted exactly this item (§3.3);
6. for `revalidate`: every transition in `revalidates` is an admitted closure of D
   whose **admission position** is strictly before this item's admission position.

The **admission position** of an item is the latest of its transition's position
and the earliest acceptance position of each required acceptor. Filing early and
being accepted late admits late.

`impossible` is admitted under the same rules, except for 6; for a `compute`
condition its basis is a replayed cycle (§7), otherwise `ATTESTED`, and then it
also needs the acceptance of at least one owed_to actor. `release` is admitted
per §4.1.

For a scheduled duty, an item discharges one period `n` (window
`[start + n·every, start + (n+1)·every)`); its transition MUST NOT be earlier than
the window's start, and an observation it relies on MUST lie inside the window.
`impossible` and `revalidate` are not defined for scheduled duties.

A candidate that is not admitted has a verdict, kept in the report:
`PENDING` (an acceptance is missing), `OVERCLAIMED` (wrong filer, wrong basis,
order), `MISSING_EVIDENCE`, `UNMET_CONDITION`, `UNVERIFIED` (the basis could not
be validated here). None of them closes anything.

### 4.3 Disposition

A one-off duty is `OPEN`, `DISCHARGED`, `IMPOSSIBLE`, `RELEASED`, or `CONTESTED`
when admitted closures disagree. A scheduled duty is `SCHEDULED` (or `RELEASED`)
and has, for every period n whose
start `start + n·every ≤ as_of`: `COVERED` (a discharge for n is admitted),
`OPEN` (the period has not ended) or `LAPSED` (it ended uncovered). A discharge of
one period covers no other.

Admitted closures are history. Nothing later — a challenge, a fired trigger, a
supersession, a revalidation — rewrites a disposition or erases a closure.

### 4.4 Reliance

`reliance(target, use)` answers whether a present action may rely on a duty's
closure or a transition's results for a named use. States:

- `ELIGIBLE` — closed (a DISCHARGED duty; or a transition whose results every
  required acceptor accepted, §4.6), not superseded, no current trigger FIRED or
  UNEVALUABLE, no standing challenge, fresh (`fresh_for`), and a revision basis:
  established on a current revision, or covered by a `subject_changed` trigger
  that evaluated NOT_FIRED;
- `STALE` — a current trigger FIRED, or an observation is older than `fresh_for`;
- `CHALLENGED` — a challenge targets a current closure and either its actor
  counts (§4.6) or it is **evidence-weighted**: the duty's condition is `observe`
  and the challenge's evidence names an observation record, by any actor other
  than the closure's filer, whose `probe` equals the condition's, whose `result`
  differs from `expect`, and whose window ends no earlier than the latest
  observation that met the condition. Who filed such a challenge does not
  matter: the probe ran again and disagreed. A `compute` closure is settled by
  the recipient's own replay and admits no counter-evidence; an `attest` closure
  has no mechanical counter and stays actor-weighted. A revalidation of the
  challenged closure, admitted with the same acceptances, supersedes it, and the
  challenge stays in the record;
- `SUPERSEDED` — the transition's results were replaced (§4.7);
- `UNASSESSED` — something needed could not be evaluated here (a trigger is
  UNEVALUABLE, the use is not in the profile, the use requires declared triggers
  and none are current, no revision basis);
- `NOT_CLOSED`, `CONTESTED`, `MISSING`.

Only current closures count: those no admitted revalidation names. A revalidation
supersedes, for present reliance only, the closures it names; their triggers stay
in the report as history with `current: false`. An empty trigger list is neutral:
it is reported as `NONE_DECLARED`, never as "cannot be falsified".

### 4.5 Grants

A grant is **valid** at a position iff its record is in the view at or before it,
it has not expired there, and either it is a root that the recipient's profile
lists in `grant_roots`, or it attenuates a parent valid at the child's own
position: the child's grantor is the parent's grantee, its acts are within the
parent's `delegable`, its `delegable` within both, its duties within the parent's,
and it expires no later. A grant record not signed by its grantor is invalid.

### 4.6 Profile

The recipient's profile is its own choice, never inferred from records:

```
uses         {name: {"requires_triggers": bool}}
accept_by    {"results": [actor…]}: whose acceptance closes a transition's results
targets      list of crossing targets the recipient accepts a receipt into
grant_roots  list of grant ids the recipient accepts as roots
challengers  list of actors whose challenges count (owed_to and accept_by of the
             duty concerned always count; an evidence-weighted challenge, §4.4,
             counts whoever filed it)
providers    list of provider identities (§7) whose replays the recipient accepts
```

### 4.7 Supersession

A transition may supersede earlier transitions' results. The superseded results
remain historically valid as of their time; reliance on them is `SUPERSEDED`. A
superseding transition counts only while it is itself admitted as results
(accepted per the profile) and present: if C supersedes B and B superseded A, and
C is absent, B is current — A never returns without a record that says so. A
supersession that names a transition not in the view is reported missing.

## 5. Triggers

Each trigger evaluates in one view to exactly one of `FIRED`, `NOT_FIRED`,
`UNEVALUABLE`. Unknown never reads as `NOT_FIRED`.

- `{"kind": "subject_changed", "baseline": hex64}` — the baseline blob is a
  manifest `{"selector": [path…], "entries": {path: {"mode", "sha256"}}}` of
  explicit, sorted, repository-relative file paths (no globs, directories,
  symlinks or submodules). FIRED if any entry differs at the workspace commit,
  NOT_FIRED if none does, UNEVALUABLE if the workspace, a path or the manifest
  cannot be read.
- `{"kind": "duty_not_discharged", "duty": id}` — FIRED if that duty is OPEN,
  RELEASED or IMPOSSIBLE; NOT_FIRED if DISCHARGED; otherwise UNEVALUABLE.

## 6. Authority, keys and competence

A key binding says who signed. A grant (§4.5) or the duty itself (holder,
owed_to, release_by, accept_by) says who may act. Nothing says who is competent:
competence is not assessed. Delegation by a holder admits closures by the
delegate; it cannot widen what the holder could do. Generated claims, green CI or
access to a key do not create authority.

## 7. Computation

Σ-GLYPH owns evaluation, resume, replay and cycles; Warrant owns the condition,
the recipient's acceptance and the credit. The provider is the `sigma-glyph`
distribution's modules `sigma_glyph`, `sigma_resume` and `sigma_provider`
(installed from a wheel; Warrant does not ship them). Its **identity** is
SHA-256 over the canonical JSON `{"provider": "sigma-resume", "files":
{"<module>.py": sha256(bytes)}}` of the three modules, the formula
`sigma_provider.identity_of` documents. A replay counts only if the identity of
the bytes that ran is in the recipient's `providers` (§4.6); a provider's report
about itself grants nothing. Runtime ids are the kernel's own:
`sigma-book1-0.6.0/hash-thunk/leftmost-outermost` (Book I) and
`sigma-resume-draft/ski+Y+M+W/hash-thunk/leftmost-outermost` (a draft profile with
Y, M, W, under which cycles exist). An environment is the blob of Sigma's own manifest
`{"schema": "sigma-resume.environment@draft-1", "hashes": [sorted lowercase node hashes]}`
in canonical JSON, so its blob address is `sigma_resume`'s `environment_id` for
the same hash set. The provider identity is part of
the assessment identity. Execution reads the provider's module bytes once,
computes the identity from them, and executes exactly those bytes in a separate
interpreter (`-I -B`, the bytes passed on stdin, no file reopened), through the
`sigma_provider` request protocol. The process boundary isolates module names;
it is not an OS sandbox. Without an installed provider every REPLAYED basis is
`UNVERIFIED`.

A REPLAYED item cites one **receipt** blob:

```
{"receipt": "sigma-resume", "target": string, "input": hex64, "environment": hex64,
 "checkpoint": hex64, "state": hex64, "claimed": hex64, "lost": [string…]}
```

The recipient admits it iff `target` is in its profile's `targets`, `lost` is
empty, `(input, environment)` equal the duty's condition, the receipt's bytes are
in the view, and its own replay from the root yields `NORMAL_FORM` with result
hash equal to both `claimed` and the condition's `expect`. A paused computation
(`PAUSED`) is not an answer; it may be resumed later and the final checkpoint
replayed. Replay verifies the whole chain; a verified-replay cache keyed by
verifier identity changes cost, never the answer or the task.

An `impossible` item for a `compute` condition cites a **cycle** blob
`{"cycle": "sigma-resume", "target", "input", "environment", "witness": hex64, "lost": []}`;
the recipient verifies the witness. It establishes that this root, under this
runtime and environment, does not reach a normal form. It says nothing about
other uses of the term.

Outcomes that are about the host — bytes the environment names but that are not
delivered (`EVIDENCE_UNAVAILABLE`), resource limits — are `UNVERIFIED`, never an
answer. A reference outside the fixed environment is the kernel answer
`BLOCKED_REFERENCE`, distinct from missing bytes.

## 8. Next-session capsule

`capsule(target)` returns, for one duty or transition in one assessment: the
result (established statements, disposition), its basis (assessed basis, acceptors,
observations, replays), its limits (residual, scope, subject, completeness), the
conditions under which it must be revisited (triggers with their current results,
challenges, freshness) and the ids of its evidence, which are fetched on demand.
For a duty it also names who it is owed to, whose acceptance closes it
(`accept_by`) and whose acceptance a filed closure still waits for
(`waiting_for`). `frontier(actor)` lists what is open for that actor: duties it
holds or is delegated, periods lapsed or open, acceptances it owes (each with
the item's `waiting_for` and whether this acceptance is the last one,
`last_acceptance`), results acceptances it owes under the profile's
`accept_by.results` (marked `under`), and challenges against its closures. When
any one of several actors suffices (a substitution's one of owed_to ∪
release_by, an attested `impossible`'s one owed_to actor), `waiting_for` names
each of them and `awaiting` lists each missing acceptance as the actors any one
of whom gives it; an acceptance that another missing one implies is not listed,
and `last_acceptance` is true only for an actor named in every missing one. Unowned questions are listed by `questions()` and are in nobody's
frontier.

## 9. Limits

Not in this version, and refused rather than approximated: threshold (k-of-n)
adoption, key rotation and revocation, P-256 signatures, `cmd@v1` and `ski@v1`
checks, policy compilation (WPL), settlement tunnels, goals/commitments as
distinct kinds, grants for acts other than `release`, revocation of grants.

**Admission limits.** These are operational limits of an implementation, not
semantics: they change no record rule, verdict, disposition or reliance state
(§3–§7), and they are not an operand of the assessment identity (§4). A view
within every limit is assessed exactly as without limits. A view beyond one is
refused with a typed resource refusal before the unbounded work: no report, no
partial report, no truncated period list and no verdict. A recipient that wants
such a view assessed raises the limit; it never reads a refusal as an answer.

| limit | bounds | default |
| --- | --- | --- |
| `snapshot_records` | files under `records/` while a store is read, and records in a snapshot | 100 000 |
| `snapshot_blobs` | files under `blobs/` while a store is read, and blobs in a snapshot | 100 000 |
| `snapshot_bytes` | all record and blob bytes of a snapshot together; a store read stops before the file that would exceed it | 1 GiB |
| `requires_edges` | `requires` entries the dependency traversal follows (the sum over the view's duties) | 1 000 000 |
| `duty_periods` | period entries of one scheduled duty at `as_of` (§4.3) | 10 000 |
| `report_periods` | period entries of all scheduled duties of one report | 100 000 |

Each file is also bounded by 64 MiB (§3); that bound is not a bound on the
store. In the Python implementation the refusal is `warrant.limits.LimitExceeded`
(a `ValueError`) with the limit, the value and the bound; `engine.assess` and
`Snapshot.read` take `limits=` overrides, the `warrant` command exits 3, and
`warrant-agent` takes them from the workspace `limits` and answers
`RESOURCE_LIMIT`. The dependency traversal is iterative: the depth of a valid
`requires` chain is bounded only by `requires_edges`.
