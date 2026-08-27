---
title: "The Reason Runs Again: Decision Records for Machine Actors, Addressed by Their Own Hash and Justified by Checks a Stranger Can Re-Run"
author: "Serhii Glova (independent) — sergey.glova@gmail.com"
date: 2026-08-27
keywords:
  - AI agents
  - accountability
  - provenance
  - content-addressed storage
  - canonicalization
  - Ed25519
  - domain separation
  - verifiable computation
  - EU AI Act
classification: cs.CR, cs.SE, cs.AI
bibliography: references.bib
---

# Abstract

When an autonomous agent's decision is later disputed — by a customer, a
regulator, a court, or another agent — the record offered in evidence is
usually a log: mutable, operator-controlled, and structured around what the
agent *said* rather than what was *decided* and *why*. We present Warrant, a
record format in which one decision is one immutable record whose identity is
the SHA-256 hash of its canonical bytes, whose governing policy is pinned by
the hash of the exact policy text in force, whose signature covers a
domain-separated message so that a signing key cannot be replayed across
protocols, and — the property we consider the actual contribution — whose
justification can be a *deterministic, budget-bounded computation that any
reader re-executes offline*, so the stated reason is checked rather than
believed. Records form a DAG; on top of it the format defines settlement
semantics with a mechanically checkable novelty rule for re-opening a settled
question, key rotation and threshold governance derived from the DAG rather
than from wall-clock time, and a closed-schema machine-readable verification
report that fails closed.

The format is specified to a design rule that anything two independent
implementations cannot agree on byte-exactly stays out of the document. Three
implementations — Python, Go, and a from-scratch Rust verifier with no
external crates — agree byte-exactly on the surfaces they claim: Python and
Go at settlement grade, Rust deliberately at base grade. A third party can
check any of them, or an implementation we have never seen, against 138
vectors in a runner-driven pack (134 base-grade, 4 settlement-grade),
including normative *negative* batteries (14 weak Ed25519 keys that must
fail verification, 15 bodies that must fail validation, 10 signature
constructions that must not verify). We report the engineering findings that
produced those batteries — an integer domain the declared canonicalization
could not carry, cross-implementation JSON leniency splits, torsion-point and
scalar-reduction defects in the hand-rolled Ed25519, and a conformance suite
that reported `ALL PASS` while silently skipping a third of its vectors — as
measured events from a review ledger of 81 documents spanning six model
vendors: a census under this repository's own naming convention, not a claim
of reviewer independence. We state with equal precision what the
format does not provide: key–actor binding is local configuration, not a
protocol fact; one of the two check runtimes is trusted by specification and
that trust reaches settlement; and no independent party has yet implemented
the format from its text alone.

# 1. Introduction

In *Moffatt v. Air Canada* [@moffatt2024], an airline's support chatbot told
a passenger that a bereavement fare could be claimed retroactively. The
airline's defence — remarkable enough that the tribunal quoted it — was that
the chatbot was "a separate legal entity that is responsible for its own
actions." The defence failed, but the evidentiary situation underneath it is
the interesting part: neither party could produce a record establishing
*which version of which policy* the system was operating under at the moment
of the answer, because nothing in the system was built to make that question
answerable. The operator's logs were the operator's logs.

That situation is the default. The observability stack that has grown around
deployed language-model agents — transcript stores, tracing frameworks,
telemetry pipelines [@opentelemetry] — records what happened, in a form the
operator can edit, on infrastructure the operator controls, addressed by
nothing but position in a stream. For debugging, that is adequate. For the
question a dispute actually asks — *what was decided, under which rules, for
what stated reason, and does that reason hold?* — it is inadequate in three
independent ways: the record is mutable after the fact, the rules in force
are not pinned, and the stated reason, where one exists at all, is prose that
can only be believed or disbelieved.

Warrant is a record format built for the dispute rather than the debugger.
Its claim is one sentence, and everything else in this paper is either
mechanism for it or a limit on it:

> Given the bytes of a store, anyone can recompute **that these records say
> what they say**, **that these keys signed them**, and — for one class of
> reasons — **that the stated reason really does evaluate to the stated
> verdict**, without trusting whoever handed them the bytes.

Three design commitments follow.

**Identity is the hash of the content.** A record's identity — its WarrantID
— is the SHA-256 of its canonical JSON bytes. Everything a record cites —
the policy under which the decision was taken, the evidence relied on, the
check that justifies it — is cited by the SHA-256 of the exact bytes. Nothing
can be edited after the fact without changing its address, and therefore
without breaking every reference to it. This moves the trust question from
"do I trust the host that served me this log?" to "do these bytes hash to
this identity?" — a question with a mechanical answer.

**Signatures name their protocol.** Each record is signed with Ed25519, but
the signed message is not the bare digest: it is a 47-byte domain-separated
message that names this protocol inside the bytes the key covers. Section 4
explains why the obvious construction — sign the hash — is a
cross-protocol replay hazard shared by every system that signs bare 32-byte
digests, and why the fix was deployed as a breaking flag-day rather than a
compatibility window.

**Reasons can re-execute.** A record's justification may include a check: a
deterministic combinator-calculus term evaluated under a single integer
budget that bounds both the work performed and the peak memory materialized
[@glova2026sigma]. A verifier re-runs the check against content-addressed
blobs and compares result hashes. A false claim is detected, not litigated;
and because the budget bounds memory as well as time, re-running a
*stranger's* check is safe by construction — which cannot be said of
re-running a stranger's shell script.

The format is deliberately narrow. It records decisions; it does not take
them, order them across actors, transport blobs, keep secrets, or hold any
opinion about whether a decision was good. Section 8 states the residual
trust assumptions as sharply as we can state them, because several are load-
bearing and one — key–actor binding — was demonstrated to be exploitable
for free by the format's own first external consumer.

## 1.1 Provenance and standing

This paper was written by a language model working as maintainer of the
repository it describes, for a project whose explicit methodology is that
model actors do the engineering and humans hold the keys and the mandate
[@warrant2026]. Every number in it is measured from the repository at a named
commit, and a checker script deposited alongside the paper recomputes the
countable claims. What no checker supplies is independence: the format has
been adversarially reviewed (Section 7) but never implemented by a party who
had not read our code, and this paper has not been peer reviewed. Section 8
returns to what that limits.

# 2. Related work

**Signed transcripts.** The closest active work is the IETF draft on
verifiable agent conversations [@vac2026], which normalizes and signs the
session logs coding agents already write — messages, tool calls, tool
results — so a transcript offered later can be shown to be the transcript
that happened. Warrant sits one layer below: not the conversation but the
decision, with a justification that re-executes. The two compose rather than
compete — a signed transcript establishes what was said; a warrant
establishes what was decided and lets a stranger recompute whether the
stated reason holds.

**Software supply chain.** in-toto [@torresarias2019], SLSA [@slsa], DSSE
[@dsse], Sigstore's Rekor transparency log [@sigstore], and TUF
[@samuel2010] pin *artifacts and build steps* by hash and signature. Warrant
borrows the layering discipline and interoperates with it (records can be
wrapped as in-toto statements), but its subject differs: an attestation says
"this artifact was produced by this step"; a warrant says "this decision was
taken under this policy for this reason", and its reason can carry its own
proof of evaluation. Certificate Transparency [@rfc6962] contributes the
append-only Merkle discipline our anchoring tool reuses. DSSE earns a second
mention in Section 4: its PAE encoding is *prior art for* the domain
separation Warrant adopts — not, as an earlier draft of this paper implied,
an example of the hazard.

**Provenance for science.** W3C PROV [@prov] and RO-Crate
[@soilandreyes2022] give honest researchers a vocabulary for traceability. A
2026 survey of 109 agentic bioinformatics systems [@pham2026] proposes a
Function–Evidence–Validation framework whose second validation rung —
"sufficient information for replay" — is exactly the property Warrant's
re-executable reasons mechanize. We record what the survey establishes and
what it does not with some care, because it argues against this project as
much as for it: across its 47 pages the words *tamper*, *forge*, and
*threat model* do not appear. An entire discipline reached a formal
statement of the reproducibility problem without feeling any need for
cryptography, because its threat model is sloppiness, not adversaries. The
opening Warrant bets on is the regulated end — the point where a record
acquires legal weight and the honest researcher stops being the only party
with an interest in what it says. That is a hypothesis, and we label it one.

**EdDSA verification divergence.** Our signature-acceptance rules are a
direct application of the analysis in "Taming the many EdDSAs"
[@chalkias2020]: libraries disagree on small-order and non-canonical inputs,
so a format that wants two verifiers to agree must pin the acceptance set
normatively. Section 6 reports finding two such defects in our own Rust
implementation — after a 452-case random differential had passed.

**Regulation.** Article 12 of the EU AI Act [@euaiact] requires that
high-risk AI systems technically allow the automatic recording of events,
sufficient for purpose-appropriate traceability of their functioning.
Warrant explores a stronger, decision-level record model that could
contribute to such traceability — a motivational reading, and we mark it as
one rather than as what the article requires. The repository
carries a profile mapping its record fields to those requirements and a
contribution to the CEN/CENELEC JTC 21 standardization discussion; we cite
them as motivation and defer the legal analysis to a companion paper.

# 3. The record

A **warrant** is an immutable, signed, content-addressed record of one
decision — immutable in its *body*, precisely: the enclosing signature
envelope is appendable by design (Section 4), so "immutable record" without
that qualifier would overstate. The body is a JSON object with exactly nine fields — `warrant`
(format version), `decision` (`propose` | `accept` | `reject` |
`supersede`), `subject` (hash of the thing decided, plus an optional note),
`under` (one or more hashes of the policy blobs in force), `because` (reasons),
`evidence` (hashes of inputs relied on), `actor`, `prior` (WarrantIDs this
record responds to), and `ts` — and *unknown fields make the record
invalid*, recursively, at every level of the tree. Records form a DAG via
`prior`; every cited artifact is a blob addressed by SHA-256 of its bytes,
in any content-addressed store. The store is a directory; transport,
consensus and completeness are explicitly out of scope (Section 8).

Identity is:

$$\mathit{WarrantID} = \mathrm{SHA\text{-}256}\big(\mathrm{JCS}(\mathit{body})\big)$$

where JCS is RFC 8785 canonical JSON [@rfc8785] over an I-JSON [@rfc7493]
body. Because bodies admit integers only — no floats anywhere — the
canonical form is short to state: UTF-8, keys sorted, no insignificant
whitespace. The brevity is deceptive, and most of what this section has to
report is where it deceived us.

## 3.1 The integer domain, or: a schema the canonicalization could not carry

The specification originally admitted `ts` values in `0..2^63−1`. RFC 8785
serializes numbers the way ECMAScript does — through an IEEE-754 double —
so above $2^{53}-1$ the canonical bytes stop being a function of the value:

```
ts = 9223372036854775807         (int64 max — valid under the old rule)
  exact-integer implementation -> 9223372036854775807
  any conforming JCS           -> 9223372036854776000
```

Two conforming implementations, one logical record, two WarrantIDs — in a
format whose identity *is* that hash. An external review observed that the
document cited RFC 8785 and RFC 7493 while contradicting both (RFC 7493
§2.2 warns about precisely this). The repair narrows every integer anywhere
in a body or canonicalized blob to $\pm(2^{53}-1)$, with silent clamping
forbidden. Wrapping was rejected because it maps two values onto one
canonical byte string — a hash collision introduced on purpose; widening
via decimal strings was rejected because it buys range no Unix timestamp
needs at the cost of a second number syntax in every implementation.
$2^{53}-1$ seconds is the year 285428751. Every JSON file in the repository
and its siblings was scanned before the change: no record carried an
out-of-range integer, so no WarrantID moved — true at v0.x, and not a
repair that would have been available after 1.0.

The general lesson we take from this: **a specification can name a
canonicalization while admitting a value domain that canonicalization
cannot carry**, and nothing in either document flags the contradiction. We
later found the same defect class in an unrelated IETF draft while
reviewing it — and fixed our own instance before publishing the review.

## 3.2 The leniency splits

The remaining canonicalization rules exist because stock JSON libraries
disagree, and each disagreement is a way for two verifiers to accept
different stores:

- **Escaping.** Go's `encoding/json` HTML-escapes `<` `>` `&` by default;
  ECMAScript-derived serializers `\u`-escape U+2028/U+2029; libraries split
  on `\b`/`\f` short forms and hex case. The spec pins the exact escape
  table normatively and backs it with a 47-case canonicalization battery
  covering every control code point, NFC vs NFD as distinct content,
  astral-plane code points, and the 200/201-code-point boundary of the one
  length-limited field — measured in code points, never bytes, because
  byte-length and code-point-length disagree for any non-ASCII string.
- **Duplicate member names.** Python's `json` and Go's `encoding/json` keep
  the last occurrence silently; the spec requires rejection, so a dup-key
  object cannot mean "malformed" to a strict implementation and
  "last-wins" to a lenient one.
- **Trailing content.** The Go implementation originally ignored trailing
  bytes after the JSON value; the Python one rejected them. The differential
  fuzzer found the split on its first run (Section 6).
- **Unicode normalization is not applied.** Strings hash as their exact
  code-point sequence; two normalization forms are two contents with two
  addresses, as a content-addressed system requires. Producers are advised
  to emit NFC; verifiers are forbidden to normalize or to reject
  unnormalized input. Requiring NFC would have put a Unicode normalization
  database inside every from-scratch implementation.

None of these rules is clever. Collectively they are the difference between
"two implementations agree" as a slogan and as a measurement, and nearly
every one was extracted from an observed split rather than anticipated.

# 4. Signatures that name their protocol

A stored warrant is an envelope: the body plus a signature array. Ed25519
[@rfc8032] signs a message that is **not** the WarrantID. It is:

```
msg = "warrant-sig-v1:" || WarrantID_raw        (15 + 32 = 47 bytes)
```

Without the separator, the signed message is an unconstrained 32-byte
value, and the signature is therefore replayable into any other context in
which the same Ed25519 key ever signs an unconstrained 32-byte value — the
realistic such contexts being raw-digest HSM/KMS signing interfaces and
whatever ad-hoc "sign the hash" scheme a key's owner adopts later. We
deliberately do not argue this by pointing at named protocols: an earlier
draft listed DSSE, TUF, Certificate Transparency and Git object identifiers
as bare-digest signing domains, and a reviewer correctly objected that DSSE
signs a PAE-encoded, type-bound message and CT signs a versioned structure
— domain separation done right, precedents rather than victims. The
demonstrated instance is our own: the negative battery of Section 6 carries
a signature made over the bare SHA-256 of *unrelated content*, offered as a
warrant signature for the record whose WarrantID equals that digest — and
every pre-flag-day verifier accepted it. The separator names this protocol
inside the bytes the key covers; a future scheme change becomes
`warrant-sig-v2:` and is again disjoint from everything before it.

Two deployment decisions are worth recording because both cut against
convention. First, Ed25519ctx — the RFC 8032 instrument designed for
exactly this — is deliberately *not* used: Python's `cryptography` does not
expose it, Go reaches it only through options, and a from-scratch verifier
must implement the `dom2` prefix, so the orthodox choice is the one most
likely to split verifiers, which is the failure this format ranks above all
others. Plain Ed25519 over a prefixed message achieves the separation with
primitives every implementation already has. Second, the migration was a
**flag-day, not a transition window**: a verifier that accepts both the old
bare-digest message and the new one has no domain separation at all,
because an attacker simply uses the old one. The two constructions are
cleanly disjoint — exactly one verifies, never both — and a verifier that
*recognizes* a legacy signature must say so in a pinned diagnostic string
while still rejecting it. Re-signing rewrites only the envelope: the
WarrantID is the hash of the body, the envelope is outside the hash, so no
identity moves, no `prior` edge breaks, and nothing needs re-anchoring.

**Acceptance is pinned.** Verifiers must reject non-canonical scalars
($S \ge L$), malformed point encodings, and small-order or non-canonically
encoded public keys — as a byte-exact blocklist of the 8 canonical torsion
encodings plus a $y \ge p$ check, shipped as a normative negative vector,
not as a library-dependent heuristic. A small-order public key lets an
all-zero signature verify for a large fraction of messages, and libraries
disagree on which such keys they accept [@chalkias2020]; a format that
leaves acceptance to the library has left two conforming verifiers free to
disagree about a crafted envelope.

The envelope also embodies a smaller decision with an adversarial
rationale: co-signatures are outside the hash and may be appended freely,
so **an invalid co-signature is reported and excluded, never fatal** —
because anyone with store write access can append junk, and a junk
signature must not be able to invalidate a record that still carries a
valid signature by its filing actor.

# 5. Reasons, settlement, and governance

## 5.1 Two runtimes, one honest asymmetry

A reason is either prose, or a check. Checks carry a runtime tag, and the
two registered runtimes have deliberately different trust models:

- **`cmd@v1`** — the check blob is a command executed in a container; exit
  status is the verdict. The verifier does *not* re-execute it. It proves a
  claim to whoever trusts the container, which is an honest engineering
  trade and a bounded one: the spec says so rather than implying otherwise.
- **`ski@v1`** — the check blob is a canonical JSON object
  `{ski: 1, term, atp, expect}` naming a combinator term in Σ-GLYPH Book I
  [@glova2026sigma], a budget, and an expected result hash. Verification
  re-runs the reduction against the store's blobs — the warrant blob store
  *is* the evaluation's content-addressed store — and compares node hashes.
  Determinism, termination, and the bound $\mathit{size} \le \mathit{atp}+1$
  on peak materialized memory are mechanized in Lean 4 in the sibling
  repository; the practical consequence is that re-running an untrusted
  party's check is safe by construction, in both time and space.

A verifier must bound the work it will spend on strangers: a reason whose
budget exceeds the local re-execution limit (default $10^8$ ATP) is
reported **unverified — never `pass`, never `fail`, and never a silent
skip**. "Re-ran and matched" and "was not executed" must not be
observationally equivalent; a suite that reports them identically is
non-conformant, and Section 6 reports the day our own tooling violated
exactly this rule.

## 5.2 Settlement: foreclosure you can compute

An `accept` or `reject` over a question blob settles it. The format then
has to answer the question every decision system eventually faces: when may
a settled matter be re-opened? Warrant's answer is mechanical. A settling
record's **tunnel** is itself plus the transitive closure of its `prior`
edges, together with every blob those records cite. A blob **forecloses**
only the claims some check in the tunnel actually evaluated over it — mere
presence in an evidence list forecloses nothing, and an unresolvable blob
forecloses nothing, because what cannot be read cannot have been reasoned
over. A re-litigation record must carry either (a) an evidence hash absent
from the tunnel, or (b) a check, all of whose blobs resolve, that re-runs
to an **outcome fingerprint** not present in the tunnel. Prose never
re-opens anything.

The rule's boundary is stated in four words that took several review rounds
to earn: **novelty is format; relevance is policy.** The format decides
only whether an outcome is *new*; whether a novel check is relevant to the
settled subject or a strawman testing something adjacent is delegated to
the active settlement policy. The cost is disclosed rather than hidden: a
permissive policy accumulates unbounded fingerprint-distinct irrelevant
re-litigations, and bounding them is a policy choice. The rule is also
reflexive — a check demonstrating that the rule itself forces a wrong
settlement is admissible evidence against the rule.

The asymmetry of Section 5.1 reaches here, and so does a limit that
survives it. A `cmd@v1` outcome fingerprint contains the **verdict its
filer wrote**, so under `cmd@v1` a party can satisfy the novelty test by
filing the same check with the opposite verdict — by writing a different
word. The `ski@v1` fingerprint was repaired to contain the **re-run**
result instead, and an earlier draft of this paper concluded that
settlement's strongest guarantee therefore holds for reasons that
re-execute. A reviewer of that draft found the claim too strong, and a
reproduction against both implementations confirmed the objection: the
`ski@v1` fingerprint still contains the filer-chosen `expect`, so re-filing
the *same term* with a fresh `expect` — the re-run honestly returns `fail`,
the actual result hash is unchanged — produces a formally new fingerprint
and an admissible re-litigation, $2^{256}$ times over, at zero new
computation. What re-execution buys is the removal of *claimed-verdict*
arbitrariness: the verifier can no longer be lied to about what ran.
Syntactic novelty remains filer-satisfiable under **both** runtimes;
semantic novelty is a policy property, with no exception for the strong
runtime. This is a limit of the format, not of the implementations — the
settlement harness pins the `expect`-flip as *admissible*, because that is
what the specification says — and the candidate repair, a fingerprint that
is a pure function of the computation (runtime, term, result hash), is
recorded in the review ledger rather than adopted here.

## 5.3 Keys and jurisdictions as records in the same DAG

Key management does not get a side channel. A rotation is an `accept`
warrant whose subject is the new key blob, carrying proof-of-possession by
the incoming key and authorization under the current key policy; a
revocation is a `supersede` of the rotation that introduced the key. Key
validity derives from **DAG order, never from wall-clock timestamps** — a
timestamp is attacker-writable; an ancestry relation among signed records
is not. Where a threshold policy is configured, an unbound signature
satisfies nothing, the incoming key's proof-of-possession does not count
toward its own authorization, and mutually unordered authorized rotations
for one actor produce a reported conflict during which that actor's key
counts toward no quorum — a denial rather than a takeover.

Stores may carry multiple roots: separate jurisdictions sharing a blob
store, joined only by explicit adoption records satisfying the adopting
root's threshold. The store-level `genesis.json` is advisory and must not
be treated as a trust anchor — it is a mutable unsigned file, and the spec
says so instead of hoping. One consequence recurs throughout the design and
deserves its own sentence: **every input that could make two verifiers
disagree is either inside the hash, or pinned by local configuration that
fails closed.** A settlement-grade verification requested with a missing or
malformed trust configuration reports exactly one error and stops; it does
not fall open into "no trust configured, nothing found wrong."

## 5.4 The verification report

Verifiers expose a machine-readable report under a closed schema of exactly
seven members, in which `ok` means `errors == 0` and *nothing else* —
explicitly not "this store is trustworthy," a misreading the threat model
names as an attack on the reader. Counts must equal findings, order must be
deterministic, and an uninitialized store is a reported failure rather than
an empty success, because without that rule "there was nothing to verify"
and "everything verified" are the same JSON. Two implementations must agree
on the counts and the multiset of (severity, subject) pairs; human-oriented
message text is explicitly non-normative. One known divergence — a legacy
non-store mode in the Go CLI that emits an optimistic report where Python
fails closed — is disclosed in the spec as an open defect rather than
legislated away, because the design rule ("two implementations must agree
on every verification outcome") does not carve out legacy modes.

# 6. Conformance without trusting us

The specification's design rule is stated on its fifth line: two
independent implementations must agree on every WarrantID and every
verification outcome, and anything that cannot meet that bar stays out of
the document. This section reports what it cost to make that rule a
measurement.

**Three implementations.** The Python reference implements everything
including settlement; the Go implementation implements settlement-grade
verification and is differentially fuzzed against Python; the Rust
implementation is from scratch with **no external crates** — its own
SHA-256, its own strict I-JSON parser, its own 5×51-bit field arithmetic
and Edwards-curve Ed25519 — and deliberately claims only base grade.
Three-way agreement is byte-exact on the adversarial canonicalization
differential (43/43 cases at the time of that run; the committed battery
has since grown to 47) and on all pinned record hashes and signatures; the
Ed25519 differential against Python's `cryptography` runs 472 cases
including 20 mixed-torsion keys. Settlement-grade agreement is a two-way,
Python–Go claim; the base/settlement split below keeps the two claims from
blurring.

**Vectors, positive and negative.** The spec pins five hashes for a
three-record chain (propose → reject → accept) that every implementation
must reproduce byte-exactly, a 47-case canonicalization battery, and — the
part we would argue for hardest — *normative negative batteries*: 14 weak
or non-canonical Ed25519 public keys for which verification must fail, 15
bodies for which validation must return an error, and 10 signature
constructions that must **not** verify, including the bare-digest legacy
construction and, pointedly, a signature made over the bare SHA-256 of
unrelated content offered as a warrant signature for the record whose
WarrantID equals that digest. A pre-flag-day verifier accepted that last
one. What an implementation must reject is as much a part of
interoperability as what it must accept, and is far less likely to be
tested spontaneously.

**The pack.** All of it ships as a 138-vector conformance pack — 134
base-grade, 4 settlement-grade; its 51 canonicalization vectors are the
47-case battery above plus four record vectors from the spec's pinned
tables — driven by a runner speaking a one-request-one-response CLI
contract to the candidate implementation. The runner does not import, link against, or execute a
reference implementation, and the expected value is never sent to the
candidate; a declined vector is reported UNRUN — a distinct outcome from
pass and fail that withholds the conformance grade, because a vector that
did not run must not be observationally equivalent to one that passed.
Pack integrity is a manifest digest, so the comparison holds wherever the
tarball came from.

**What the harnesses caught.** We list these because a methods claim
without its casualty list is advertising:

- The differential fuzzer's first run found three defects: Go silently
  accepting trailing bytes after a JSON value; the Python verifier crashing
  with a `TypeError` on a string timestamp during prior-edge comparison;
  the Go verifier panicking on a short attacker-controlled hash it tried to
  slice for display.
- An external adversarial round found the Python verifier crashing on a
  non-object signature entry and on deeply nested JSON (`RecursionError`
  where Go was bounded) — and found a soundness gap in the fuzzer itself,
  whose disagreement-only invariant hid a *shared* wrong accept.
- A cryptography-targeted round found two defects in the from-scratch Rust
  Ed25519 that the 452-case random differential had missed: point
  decompression accepted the non-canonical identity encoding
  `0100..0080` (an array equality test missed an unreduced zero), and
  verification used the unreduced 512-bit hash as a scalar, diverging from
  RFC 8032 on mixed-torsion public keys. Random differentials do not reach
  the canonicality and cofactor edges; adversarial algebra does.
- A cross-repository gate's own negative control, once forced to name the
  step it must turn red, exposed that the Go conformance runner for the
  check-engine vectors had been silently skipping every vector whose kind
  it did not recognize — 16 of 49 — and printing `ALL PASS`. The skipped
  class was byte-level rejection, exactly where independent implementations
  diverge most. The re-run passed 49/49, so the gap was coverage rather
  than divergence — but demonstrated, now, instead of assumed.

Every fix in the repository carries a **negative control**: the fix is
removed and the attack is shown to come back. Two of the negative controls
themselves had to be fixed by being run — one had nothing to tamper with
on one side of a mirror and went green having tested nothing; one turned
red at the wrong step, which proves nothing about the step it claims to
cover. We take from this the same lesson twice: a green that cannot be
shown capable of turning red, for the stated reason, is not evidence.

# 7. The review ledger

The repository's operating rhythm is: a bounded hardening pass, then an
external adversarial audit as the acceptance oracle, then adjudication of
findings as warrants in the repository's own store. The ledger currently
holds 81 documents — 64 inbound reviews and gates plus 17 written
responses — under eleven reviewer labels drawn from six model vendors
(OpenAI, Google, Anthropic, DeepSeek, Moonshot, Alibaba), spanning
specification audits, cryptographic attacks, release-surface gates,
governance-proposal adversarial rounds, untyped publication-strategy
surveys, and, as of this revision, a review of this paper itself. A label census is exactly what this is: the labels
are a filename convention this repository controls, the vendor mapping is a
table in the claims checker where it can be disputed, and none of it
measures reviewer *independence* — every reviewing family was operated by
one person on one account, through one orchestration layer that chose what
each model saw, in what order, and when each review stopped. Six vendors
are not six epistemic custodians, for the same reason two co-located keys
are not two custodies (Section 8).

Two observations from that corpus shape how we read any single green
result — the first correlational, and stated as such. In one
governance-review sequence, a single family iterating produced eight
consecutive amendments and no critical finding, and the first three-family
round on the same artifact returned three rejections carrying six critical
findings, nearly disjoint from one another. That is one episode, with
confounders we did not control: the artifact moved between rounds, prompts
differed, and the orchestrator chose the stopping points. We read it as a
reason to buy reviewer diversity, not as a demonstration that diversity
beats depth. Second, the audits repeatedly found
defects not in the artifact but in the *apparatus that vouches for it* —
the vacuous suite, the fuzzer soundness gap, the miscalibrated negative
controls of Section 6. The companion paper in the sibling repository
[@glova2026guard] reports twenty-one instances of that class against a
proof guard and argues they are one defect in many spellings: a control
whose scope is chosen by the thing it controls. The present format's
UNRUN-is-not-PASS rules are that argument, applied normatively.

Beyond the census caveat above: runs are recorded as ungated when no
reviewing family was affordable, rather than pretending a threshold was
met; and an adversarial reviewer, however capable, is not an independent
implementer. The strongest review this project can receive — a
from-scratch implementation of the spec by someone who has never read its
code — has not yet happened, and we treat it as a graduation criterion for
any 1.0, not as future work. The review of this paper's own first draft is
itself a data point for the method: it predicted the `expect`-flip of
Section 5.2 from the fingerprint definition alone, the reproduction
confirmed it against both implementations, and the finding travelled back
into this text and into the ledger before the draft left the repository.

# 8. What Warrant does not provide

Each item below is a scoped assumption or an explicit non-goal, stated
here because leaving any of them out would make Section 1's claim false.
The repository's threat model states them as an attacker-capability matrix;
we compress the load-bearing rows.

**Key–actor binding is local configuration, not a protocol fact.** Anyone
with a keypair can file a record claiming any actor id; at base grade the
verifier reports the binding unverified and exits successfully with a
warning. This is disclosed, and it was measured rather than theorized: the
format's first external consumer reproduced it on its own store — *"the
protocol's central fact, forged for free"* — and built its own keyring and
its own enforced signer gate rather than rely on ours. A format whose only
external consumer had to implement its own identity enforcement has, at
that layer, failed to be a format; every adopter will re-solve binding
differently, and two adopters' stores will then not be mutually verifiable
at the identity layer even where they are byte-identical at the record
layer. Settlement grade with a pinned trust configuration closes the
threshold-relevant half; a related defect — the unbound-signature warning
appearing in text output but omitted from the machine-readable report —
was found by that same consumer and fixed. There is no identity-federation
path (no DID, no X.509, no OIDC-bound ephemeral keys) and no design for
one.

**`cmd@v1` verdicts are trusted by specification, and that trust reaches
settlement** (Section 5.2). The two candidate repairs are recorded,
neither adopted.

**A threshold assumes independent custody, and here it has not had it.**
In this repository no threshold has ever been exercised: the trust
configuration lists one actor and no stored record carries a second
signature. In the sibling repository a 2-of-3 policy has been satisfied
five times — twice by two distinct parties, three times by two keys in one
directory on one host, which is one custody performing a ceremony. Any
document describing this as "2-of-3 governance" without that sentence
overstates. The project's compensating design choice is that blocking power
in its own gate policy belongs to re-runnable evidence rather than to
signatures, precisely because a stranger can re-run a reproduction and
cannot re-derive a signature from a shared keyring.

**The store is a directory.** Deletion and censorship are undetected
beyond dangling references; completeness and availability are non-goals;
withholding a blob can suppress a settlement — records with unresolvable
settlement-critical references go settlement-inactive rather than
misleadingly settled. Nothing is encrypted, deliberately: do not put a
secret in a warrant.

**Novelty spam is syntactic.** Section 5.2's rule bounds *what counts as
new*, not *how much new-but-irrelevant material a permissive policy will
accumulate* — and under both runtimes, "new" itself is filer-satisfiable
(the `expect`-flip; Section 5.2).

**Signature-creation time does not exist.** Key validity derives from DAG
position (Section 5.3) precisely because timestamps are attacker-writable —
but nothing, then, establishes *when a signature was produced*. An attacker
who compromises a formerly valid key can sign today into a DAG position
where that key was bound, and because envelopes are appendable, a fresh
co-signature on an old record is not detectable as fresh from the store
alone. The mitigation is external checkpointing — transparency-log
anchoring, archive snapshots — made *before* the compromise; the review of
this paper surfaced that the project's anchoring tooling is therefore part
of its security argument, not merely its archival one, and the threat model
owes this a row of its own.

**The most novel layer is the least proven implementable.** Three-way
parity is a base-grade claim; settlement-grade parity is two-way;
multi-root behaviour is vectored only as far as root admission. The
from-scratch Rust cryptography is differentially tested, not audited. Part
of the mechanized proof chain in the sibling repository rests on
`native_decide`, which places the Lean compiler in the trusted base, and
that condition is not discharged.

**Deposited is not reviewed.** This paper, at a DOI, is a frozen artifact
at a permanent address. It is not a venue, a peer review, or an
endorsement, and nothing in it should be cited as though it were.

# 9. Conclusion

The gap this format addresses is narrow and, we think, real: between
telemetry that records what an agent did on the operator's word, and a
record of what was decided whose identity, governing policy, and — for one
reason class — stated justification can be recomputed by a stranger from
the bytes alone. The mechanisms are individually unglamorous: a hash over
pinned canonical bytes, a 47-byte signed message that names its protocol, a
check runtime whose budget bounds memory as well as work, a novelty rule a
verifier can execute, negative conformance batteries, and a report schema
in which nothing silently passes. What we would defend as the contribution
is the discipline connecting them — anything two independent
implementations cannot agree on byte-exactly stays out of the
specification, an unexecuted check is never a passed check, and every
residual trust assumption is written down where a reader will meet it —
together with the measured record of what that discipline caught: in the
implementations, in the specification, and, most often of all, in the
apparatus that vouched for both.

The format's next test is not one we can run on ourselves. It is an
implementation by someone who has only the text — and the conformance pack
is the standing invitation.

# Availability

The specification, all three implementations, the conformance pack, the
review ledger, the threat model, and every vector cited here are at
<https://github.com/s0fractal/warrant> (MIT). The `ski@v1` runtime and its
Lean 4 mechanization are at <https://github.com/s0fractal/sigma-glyph>.
Full git histories of both repositories are archived by Software Heritage;
disclosure manifests are timestamped via OpenTimestamps. A claims checker
deposited beside this paper recomputes its countable numbers from the
repository at the archived commit.
