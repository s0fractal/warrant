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

## 10. Agent interface

`warrant-agent/1` is the application interface for handing work between agents
over the records of §3: one backend, `warrant_agent.api.call`, and three front
ends over it, the Python API, the `warrant-agent` command and the stdio MCP
server `warrant-agent-mcp`. Its reference implementation is the package
`warrant_agent/`, outside `warrant/`: it is not part of the engine's identity,
and its results carry `adapter_id`, the SHA-256 over its source files, instead.

The three front ends take the same request objects and return the same result
objects. Every verdict a result shows is the engine's report of the view (§4),
shown and never recomputed: the interface adds no record type and no rule of
admission, disposition or reliance.

This section is the interface's contract; `AGENT.md` is the operator's guide to
it: configuration, front ends and measured costs.

### 10.1 Requests and results

The configuration is the operator's, never a request's: stores, the signer, the
receiver's trust and profile, expectations, use policies and limits. A request
names a workspace and an expectation only by the operator's local handles: 1 to
64 characters of `a-z`, `0-9`, `_`, `.` and `-`, the first a letter or a digit. No
request member selects a signer, a key, a path or a URL.

A workspace's trust may be `{bindings, roles}` of a repository: the bindings its
`.warrant/trust.json` admits under the pins of its `.warrant/roles.json` by
`warrant/bindings.py`, the rule `tools/claims.py` admits by, read again for
every view. A roles file with any problem refuses every view of that workspace
as `BAD_REQUEST`: a dropped pin would make its name first-come.

Every request is a closed JSON object: a missing required member or an unknown
member is `BAD_REQUEST`. A request whose `agent_api` is not `warrant-agent/1` is
`UNSUPPORTED_VERSION`; MCP tools carry no version, and the backend checks it for
every front end. Every operation answers a result object carrying `agent_api`
and `adapter_id`, or a typed refusal `{error, message, details?}`; a semantic
verdict such as CHALLENGED or HOLD is an ordinary result, never a refusal.

Through MCP a typed refusal is a tool error whose text is the refusal's JSON,
and stdout carries MCP messages only. Every MCP tool takes the request's members
as flat, typed arguments; an argument left out is left out of the request, so
the backend's defaults apply. A member left out takes its default from the
operator's configuration or from the view, never an invented one: the default
use is the workspace's first configured use, the default actor the configured
signer's, and an unknown use is `BAD_REQUEST` with the configured uses in
`details.configured`.

`workspace` shows the operator's configuration by name (workspaces, the signer's
actor, permitted operations, uses and `default_use`, expectation handles,
whether a provider is installed and accepted) and an index of at most 50 duties
and transitions of the store that authenticate under the receiver's trust, as
untrusted, unassessed data; it never shows a path, a key or a URL. `explain`
gives the static meaning of a verdict, a reliance state, a delivery relation or
a refusal code and what it does not establish; every such word a result can
carry has an entry, and an unknown term lists the known ones.

Evidence and record text is returned as untrusted data (`untrusted_data: true`)
and changes no configuration and no record. Tool descriptions and schemas are
static: nothing read from a record or from evidence becomes a tool, a schema, a
configuration or a signer. Read-only tools are annotated `readOnlyHint`.

### 10.2 Views

`context` captures the store's records and blobs, the receiver's trust and
profile and the provider's module bytes into a frozen view, assesses it once in
a worker, and returns its `view_token` with the capsules, the frontier, the
unowned questions, the boundary, the delivery and the use decision. Every later
read of a view answers from its stored report and captured bytes, never from the
live store. A view is assessed with the receiver's own trust and profile. Past
the workspace's `assess_seconds` there is no report and no view:
`NO_ASSESSMENT`. The assessment worker reads only a view directory that
`capture` made.

A view token is 32 lowercase hex digits; it selects a view of its own workspace
and grants nothing, and a token no view of that workspace has is `VIEW_UNKNOWN`. A
view lives at least `view_ttl` whole seconds from the moment it is ready;
afterwards it is `VIEW_EXPIRED`.

A context's `actor` selects whose frontier is read, not who signs, and is an
actor id (§3), else `BAD_REQUEST`. A target is a duty or a transition of the
view, named by its id, `{id}` or `{kind, id}`; any other record of the view is
`BAD_REQUEST` with its type in `details.type`, and an id not in the view is
`NOT_FOUND`. A context is paged under `context_bytes`; truncation is marked, and
every cursor is bound to its view, kind and target: any other cursor is
`CURSOR_MISMATCH`.

`read` returns the captured bytes of one record or blob of a view, chunked under
`read_bytes`, with their `digest`, whether the chunk is `complete`, and
`untrusted_data: true`. Without `view_token` a record or blob is read from a new
frozen view, returned as `view_token`, never from the live store; a context page
and a cursor need the view that made them.

Each capsule is the engine's (§8) with three members taken from the same report:
`closures` on a duty, every closure attempt with its verdict and why; `closes`
on a transition, each item with its duty, the duty's statement and disposition,
the verdict and why; and `reading`, one line over those fields. A transition's
own `reliance` is about its results; whether it closes a duty is decided on the
duty, which `closes` shows.

The boundary counts the view's records that do not authenticate and names up to
20 of them, each with `claims_to_be` (type, actor and target) only when its
bytes have a record's shape; other bytes are never read as a record.

### 10.3 Use decision

`use` is the receiver's local policy decision over the assessment: `{name,
policy, state, reasons, decision_id}`, its state `WITHIN_POLICY` or `HOLD`. A
target whose reliance the use's policy does not accept, or a delivery relation
it does not accept, holds the use.

The decision id covers the assessment id, the adapter id, the policy, the
delivery, the observed time, the incomplete imports and whether a newer local
event is known: a newer event changes the decision id and holds a `fresh` use,
and never changes the historical assessment id. When the receiver's trust
changed after the view was captured, a `fresh` use holds, and so does any use of
a delivery that rested on an exporter's declaration. When the operator changes
or removes an expectation handle after an inspection, the current use of that
delivery holds with a new decision id, and the historical assessment is not
rewritten. An unfinished import holds the workspace until it completes, or until
every object its manifest declares is in the live store with the declared bytes;
the staging directory is not consulted for that set.

### 10.4 Handoff

`handoff` export packages the whole configured store of a view: a manifest of
every record's envelope digest and every blob with the snapshot digest and
`completeness: UNATTESTED`, the payload, and a declaration signed by the
configured signer when there is one. An export root that is not a duty or a
transition is `BAD_REQUEST`.

A manifest digest supplied by the sender is never an expectation: only a handle
the receiver configured is, and a delivery inspected without one is `UNPINNED`. Inspect
stages the package and assesses its union with the receiver's live store in a
frozen view, promoting nothing; a package given in one piece is the same
inspection as its parts, and its capsules default to the manifest's roots.

The delivery relation is `CONTENT_MISMATCH` when delivered bytes do not hash to
their ids, are not the canonical envelope of their id, differ from the
manifest's envelope digest, or include undeclared objects. It is
`MISSING_DECLARED_BYTES` when declared objects are missing, and the use holds
although the partial view may read ELIGIBLE. It is `WRONG_SOURCE` when the
manifest names another source than the expectation, `WRONG_SET` when it is
another manifest than the expected one, and `UNVERIFIED_EXPORTER` when no
declaration by the exporter the expectation names verifies under the receiver's
trust. `MATCH_EXPECTED_SET` means that the selected set arrived, nothing more:
`source_completeness` is always UNATTESTED, and a set signed incomplete from the
start matches an expectation on exactly that set.

Import promotes a staged package only when its relation is one the workspace's
`import` use accepts, by default `MATCH_EXPECTED_SET`; otherwise it is
`IMPORT_BLOCKED`. A promotion re-checks the expectation's current definition,
that an exporter the expectation names still verifies under the receiver's
current trust, every staged record against the manifest's envelope digest, and,
for a match, that the staged set is exactly the declared set. Records that do
not authenticate under the receiver's trust are never promoted: they stay staged
and the import is `IMPORT_BLOCKED`. Import is add-only: an object already in the
store with other bytes is `CONFLICT`, and nothing is overwritten. Import is
journaled and idempotent under its request id: an interrupted import reads
`STARTED`, and a retry completes it without duplicates.

A transfer beyond `transfer_bytes` is `RESOURCE_LIMIT` on export and on inspect,
and nothing is staged. Payload ids are content addresses, never paths; a
duplicate id is `BAD_REQUEST`, and an object under a foreign address is a
mismatch.

### 10.5 Drafts and commit

`prepare` freezes one exact record whose actor and key come from the
configuration and whose `at` is fixed by the first durable prepare; nothing is
signed. The same request id with the same inputs is the same draft, also after a
restart; with other inputs it is `CONFLICT`. Without `request_id` a draft is
named by its type and body, so the same body is the same draft.

A transition prepared without `closes` closes nothing (`closes: []`). An invalid
body is `BAD_REQUEST` with `details.template`, the smallest body of its type. An
`accept` takes `{transition, item, evidence?, support?}`; without `evidence` it
is the exact evidence of that item in the view.

`prepare` takes `blobs`, JSON documents that `commit` stores as their canonical
bytes before the record; in an evidence list of the body (a transition's and its
items', an accept's, a challenge's, an observation's `raw`) `blob:<i>` is the id
of `blobs[i]`. A blob the body does not cite, or a `blob:<i>` that names none,
is `BAD_REQUEST` and nothing is stored; the blobs are inputs of the draft, so
other blobs under one request id are `CONFLICT`, and a commit refused as
`SIGNER_CHANGED` stores none of them.

`commit` signs and files exactly the draft; a retry after a lost response or a
restart returns the same record and files nothing new. Prepare and commit extend
the signer's chain as SPEC-3-26 states: commit is a compare-and-swap on the
signer's head. A draft prepared for one signer is never signed by another: a
commit under another configured signer is `SIGNER_CHANGED` and files nothing.

Draft ids are full hex64 addresses before any path is built, and a draft is
readable and committable only in the workspace that prepared it. A draft's
status, `PREPARED` or `COMMITTED`, is read by a new request (`read` with `kind:
draft`) from any server instance, and a cancelled request is not rolled back. Recording
a challenge is not gated by the use policy.

An operation the operator did not list in the workspace's `operations` is
`NOT_PERMITTED`. A configured signer is an actor id (§3); a configuration whose
signer is not one is refused when it loads.

### 10.6 Computation

`compute` runs the installed provider on bytes read once from the receiver's
store, and new bytes go back into it as blobs. A foreign checkpoint is continued
only by the provider's checked `resume`: verified from the receiver's root, then
advanced.

`evaluate` runs term, start and resume in one call under a credit (10 000 by
default); with `expect_expr`, `same_normal_form` is true only at a NORMAL_FORM
whose result is that term's input address. Computing credits nothing: `compute`
files no duty, acceptance or closure, never adds a provider to the profile, and
reports `provider_accepted_by_profile` as the profile says. A provider stopped
by the workspace's `provider_seconds` stores nothing, and the refusal is
`PROVIDER`.

### 10.7 Refusals

The refusal codes are BAD_REQUEST, UNSUPPORTED_VERSION, NOT_PERMITTED,
UNKNOWN_WORKSPACE, UNKNOWN_EXPECTATION, VIEW_UNKNOWN, VIEW_EXPIRED,
CURSOR_MISMATCH, NOT_FOUND, CONFLICT, RESOURCE_LIMIT, NO_ASSESSMENT,
IMPORT_INCOMPLETE, IMPORT_BLOCKED, SIGNER_CHANGED, NO_SIGNER, PROVIDER and
REFUSED.

- `RESOURCE_LIMIT` for an engine admission limit (§9) carries `details: {limit,
  value, bound}`; no view is kept and no verdict is produced.
- `NOT_FOUND`: the id is not in the view or the store, and nothing is fetched
  from elsewhere.
- `UNKNOWN_WORKSPACE`, `UNKNOWN_EXPECTATION`: the name is not a handle the
  operator configured.
- `NO_SIGNER`: the workspace has no configured signer, so nothing is prepared or
  committed.
- `IMPORT_INCOMPLETE`: an object is not in the store with its staged bytes after
  promotion; the journal stays `STARTED`, and a retry with the same request id
  completes it.
- `REFUSED`: the provider refused the input, and nothing is stored.

### 10.8 What the interface does not do

No operation signs as an actor other than the configured signer: commit signs
only a draft prepared for that signer, with its key, and no request member names
another. No operation creates a key: every signing key is a file the operator
configured. No result credits what the receiver did not establish: the source's
completeness stays UNATTESTED, and evidence is untrusted data. Nothing is
exposed beyond these operations: no HTTP transport, watcher, scheduler, OAuth,
shell, package install, merge or release.

`warrant-agent-mcp init`, the operator's command and not a tool, configures a
repository checkout only for a signer whose existing seed's key is exactly the
key the repository's `.warrant/roles.json` pins for that actor and whose binding
its `.warrant/trust.json` admits; it creates no key. Its configuration, its
state and the seed lie outside the repository.

On a shared machine this is an application boundary, not OS isolation: an agent
with a shell on the same keys and configuration is not contained by it, and
shared custody is not independent custody.
