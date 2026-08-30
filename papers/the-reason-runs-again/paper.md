---
title: "The Reason Runs Again: Content-Addressed Decision Records with Checks a Stranger Can Re-Run"
author: "Serhii Glova (independent) — sergey.glova@gmail.com"
date: 2026-08-30
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
reader re-executes offline*, so the stated reason's computation is
*re-executed* rather than believed. We are precise, from the abstract onward,
about the proposition a verified record establishes: **integrity** (these bytes
hash to this identity), **signature validity** (this signature is valid under
this key; binding that key to an actor needs a trust configuration), and
**replay** (this computation re-executes to this result). It does **not**
establish that the computation interprets the pinned policy, that its facts
derive from the cited evidence, or that its result entails the decision — that
semantic binding is an authoring convention today, not a format invariant, and
closing it normatively is future work. Records
form a DAG; on top of it the format defines key rotation and threshold
governance derived from the DAG rather than from wall-clock time, a
closed-schema machine-readable verification report that fails closed, and an
*experimental* settlement layer whose current honest result is partly negative
(§5.2): mechanically checkable *semantic* novelty for adversarial
re-litigation is hard, and a repair is drafted but unadopted — though the
narrow rule that survives four adversarial rounds has its invariants
mechanized in Lean 4.

The format is specified to a design rule that anything two independent
implementations cannot agree on byte-exactly stays out of the document. Three
implementations — Python, Go, and a from-scratch Rust verifier written without
external crates as a trusted-base-diversification experiment, not as a
production-hardening claim (§6) — agree byte-exactly on the surfaces they claim:
Python and Go at settlement grade, Rust deliberately at base grade. A third party can
check any of them, or an implementation we have never seen, against 138
vectors in a runner-driven pack (134 base-grade, 4 settlement-grade),
including normative *negative* batteries (14 weak Ed25519 keys that must
fail verification, 15 bodies that must fail validation, 10 signature
constructions that must not verify). We report the engineering findings that
produced those batteries — an integer domain the declared canonicalization
could not carry, cross-implementation JSON leniency splits, torsion-point and
scalar-reduction defects in the hand-rolled Ed25519, and a conformance suite
that reported `ALL PASS` while silently skipping a third of its vectors — as
measured events from a review ledger of 92 documents spanning six model
vendors, of which one is unattributed, carrying no reviewer label: a
label census under this repository's own naming convention, not a validation
score, and — a distinction its reviewers forced us to make — not a claim of
reviewer independence, since every attributed gate to date is LLM-authored and
none is cross-paradigm. We state with equal precision what the
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
answerable. The operator's logs were the operator's logs. We flag at the
outset a distinction we develop in Section 5.5: pinning *which policy a record
claims governed a decision* is within a self-contained store's reach; proving
which policy was in force *at a past instant* is not, and needs an external
time witness. This paper is honest about which half each mechanism buys.

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
the policy the record claims governed the decision, the evidence the record cites,
the check offered as its reason — is cited by the SHA-256 of the exact bytes. Nothing
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
budget that bounds both the work performed and the peak *materialized
semantic state* [@glova2026sigma]. A verifier re-runs the check against
content-addressed blobs and compares result hashes. A false claim is detected,
not litigated; and because the budget meters work and materialized state,
re-running a *stranger's* check is far safer than re-running a stranger's
shell script. (We say "far safer", not "safe by construction": the bound is
*semantic*, and a concrete binary must still enforce its own local resource
fences — Section 5.1.)

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
had not read our code, and this paper has had no human peer review. Section 8
returns to what that limits.

## 1.2 What a verified Warrant proves, and what it does not

A whole-paper adversarial review (Section 7) observed that the paragraphs
above, and the title, can be read to promise more than the format delivers, so
we state the proposition exactly and hold every later section to it. A verified
record establishes three things and no more:

- **Integrity** — these bytes hash to this identity; nothing pinned by hash
  (the policy in `under`, the `subject`, the `evidence`, the `check`) has
  changed relative to its identifier.
- **Signature validity under a key** — this signature is valid under this
  **key** (key-relative cryptographic authorship); that the key belongs to a
  named **actor** is a separate claim, true only relative to a supplied trust
  configuration (Section 5.3, Section 8). We do not call this "authenticity"
  unqualified, because that word invites the actor-binding the format does not
  supply.
- **Replay** — for a `ski@v1` reason, this deterministic computation, over
  this store, re-executes to this result.

It does **not** establish that the check *interprets* the policy in `under`,
that the check's facts *derive from* the `evidence`, that the check *pertains
to* the `subject`, or that its result *entails* the `decision`. A malicious
filer can pin policy `P`, cite evidence `E`, record `accept`, and attach a
term equivalent to a constant whose expected result it correctly reproduces;
a verifier confirms every cryptographic and computational fact while no
semantic thread connects `P`, `E`, and `accept`. We call this the
**justification-binding gap**, and it is a first-class non-goal of the core
format (NG-7, Section 8). Today the gap is narrowed only as an *authoring
convention* — the policy-language toolchain pins its source as evidence and
recompiles deterministically — not as a verifier-checkable invariant. Closing
it normatively is a reason-binding profile that commits the policy-source
hash, a fact manifest, the evidence hashes, and an explicit result→decision
mapping alongside the check; it is drafted as an **unmerged reason-binding
(declaration-coherence) candidate, carried in the frozen pull request #30 and
not present in the master tree**, with a working prototype that reports a reason
*bound* or *unbound* and whose negative controls show a constant-equivalent term
failing the binding — unadopted, and named here so the reader does not mistake
replay for entailment. Even in its
target form that profile proves *declaration coherence* (the term is this
policy's compilation over facts committed as cited evidence, yielding a result
consistent with the decision under a committed map), not authorization: who may
define the decision-mapping, and whether the facts describe reality, stay
outside it (Section 8). The honest one-line claim is therefore:
**Warrant provides tamper-evident decision records with replayable
justification computations; the semantic relevance of a justification to the
governing policy and the decision is, for now, an external property.**

# 2. Related work

**Signed transcripts.** The closest related work is the IETF draft on
verifiable agent conversations [@vac2026] (an individual submission, now an
expired and archived Internet-Draft rather than an active one), which
normalizes and signs the
session logs coding agents already write — messages, tool calls, tool
results — so a transcript offered later can be shown to be the transcript
that happened. Warrant sits one layer below: not the conversation but the
decision, with a justification that re-executes. The two compose rather than
compete — a signed transcript establishes what was said; a warrant
records and asserts what was decided and lets a stranger re-execute the stated
reason's computation and compare its result, without establishing that the
result is relevant to, or entails, the decision.

**Software supply chain.** in-toto [@torresarias2019], SLSA [@slsa], DSSE
[@dsse], Sigstore's Rekor transparency log [@sigstore], and TUF
[@samuel2010] pin *artifacts and build steps* by hash and signature. Warrant
borrows the layering discipline and interoperates with it (records can be
wrapped as in-toto statements), but its subject differs: an attestation says
"this artifact was produced by this step"; a warrant says "this decision was
taken under this policy for this reason", and its reason can carry its own
re-executable evaluation (a replayable computation, not a proof of
entailment). Certificate Transparency [@rfc6962] contributes the
append-only Merkle discipline our anchoring tool reuses. DSSE earns a second
mention in Section 4: its PAE encoding is *prior art for* the domain
separation Warrant adopts — not, as an earlier draft of this paper implied,
an example of the hazard. The in-toto attestation framework's Software
Verification Result predicate — which identifies a verifier policy by digest
and records verification properties — is the nearest attestation to a Warrant
record, and narrows the "an attestation only says an artifact was built by a
step" distance we would otherwise claim; the remaining difference is Warrant's
replayable reason object and durable decision DAG, not the mere presence of a
policy digest.

**Proof-carrying authentication.** The clearest intellectual ancestor of the
justification-binding gap (Section 1.2) is Proof-Carrying Authentication
[@appel1999pca], where a requester supplies a proof that a verifier checks
against an authorization logic. Warrant is not that: it emphasizes durable
content-addressed decision records and a replayable *computation* rather than
a proof object in higher-order logic, and — crucially — its core format does
*not* check that the computation entails the decision, which is exactly the
property PCA's proofs do carry. Stating the adjacency is what makes Warrant's
current scope honest: a Warrant reason is a replayable attached computation,
not yet a proof of authorization, and the proposed reason-binding profile
(Section 1.2) is the step that would move it toward PCA's guarantee.

**Policy engines.** Open Policy Agent decision logs [@opa] already record the
policy query, inputs, result, a decision identifier, and the policy-bundle
revision, and OPA bundles can be signed and content-checked. Warrant's
distinct offerings are offline self-containment, immutable content identity,
and a reason object a third party re-executes without the policy engine — but
those are differences to *demonstrate on concrete requirements*, not to obtain
by defining the comparison class as "logs". We name the comparison here and
leave the requirement-by-requirement study as work the paper does not yet do.

**Transparency and non-equivocation.** SCITT [@scitt2026] (RFC 9943) addresses
signed statements, issuer identity, an externally maintained verifiable
data structure, receipts, inclusion proofs, and non-equivocation — very nearly
the properties Warrant discovers, in Section 8, that it needs *externally* to
turn content integrity into historical evidence. Rather than treat SCITT as a
competitor, we position Warrant as the decision/justification payload and its
replay semantics, with SCITT (or an equivalent transparency service) supplying
registration time and non-equivocation around those records (Section 5.4).
That composition is the paper's honest answer to "which policy was in force at
time T", which content addressing alone cannot give.

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
  status is the verdict. The chain is explicit: the **filer** ran the command
  and **recorded** the exit status into the record; a later **verifier** checks
  only that the record is intact, canonical, and signed, and re-computes nothing
  of the command — it must **trust** the filer's recorded verdict and the
  container that produced it. A `cmd@v1` reason is therefore **not
  stranger-replayable**: a reader who does not trust that filer has no way to
  reproduce the verdict from the bytes. This is an honest engineering trade and
  a bounded one — the spec says so rather than implying otherwise — but it means
  `cmd@v1` re-introduces exactly the "believe the operator's log" property the
  introduction sets out to remove, for that reason class. Only `ski@v1` below is
  re-executed by the verifier.
- **`ski@v1`** — the check blob is a canonical JSON object
  `{ski: 1, term, atp, expect}` naming a combinator term in Σ-GLYPH Book I
  [@glova2026sigma], a budget, and an expected result hash. Verification
  re-runs the reduction against the store's blobs — the warrant blob store
  *is* the evaluation's content-addressed store — and compares node hashes.
  Determinism, termination, and the bound $\mathit{size} \le \mathit{atp}+1$
  on peak *materialized semantic state* are mechanized in Lean 4 in the
  sibling repository. Two precisions a reviewer rightly required. First, that
  bound is *semantic*: it bounds the work metered and the state materialized
  by the model, not the resource behaviour of a concrete binary — the
  from-scratch Rust evaluator needed an added fence after hostile input
  overflowed its host stack, so an implementation must enforce its own local
  resource limits and refusal behaviour separately, and this format requires
  it (the over-budget refusal below is one such fence). Second, evaluation is
  a function of $(\mathit{term}, \mathit{atp}, \mathit{store})$, not of
  $(\mathit{term}, \mathit{atp})$ alone: a missing referenced blob yields a
  distinct canonical *unresolved* result, which is why the store is part of
  the identity of what was computed. With those two statements in hand,
  re-running an untrusted party's `ski@v1` check is bounded in metered work
  and materialized state by construction — which a stranger's shell script
  never is — while remaining, like all software, subject to the host limits
  the implementation must fence.

A verifier must bound the work it will spend on strangers: a reason whose
budget exceeds the local re-execution limit (default $10^8$ ATP) is
reported **unverified — never `pass`, never `fail`, and never a silent
skip**. "Re-ran and matched" and "was not executed" must not be
observationally equivalent; a suite that reports them identically is
non-conformant, and Section 6 reports the day our own tooling violated
exactly this rule.

One distinction the format demands and a reader can easily miss: a check
`verdict` of `pass`/`fail` means *the computation reproduced the expected
result*, not *the policy permitted the action*. A policy expression may reduce
to Boolean false while the enclosing check reports `pass`, because the check
proved reproduction, not permission. `pass` is a statement about the
computation; whether the computation's result *authorizes* the decision is the
justification-binding gap of Section 1.2, which the core format does not
close.

## 5.2 Settlement: an experiment, and a mostly-negative result

We present settlement as an **experimental extension, not a settled
contribution** — and a reviewer was right to insist on the distinction,
because the honest result here is largely *negative*. An `accept` or `reject`
over a question blob settles it, and the format then faces the question every
decision system eventually does: when may a settled matter be re-opened? A
purely syntactic answer is easy to state and, we now know, easy to defeat; a
*semantic* answer — "only a genuinely new consequence re-opens" — turns out to
be hard to obtain from filer-controlled syntax at all. What this section
actually establishes is that difficulty, demonstrated by attack, and the
narrow rule that survives it. The mechanism, then the evidence that it is a
mechanism and not yet a guarantee.

A settling record's **tunnel** is itself plus the transitive closure of its
`prior` edges, together with every blob those records cite. A blob **forecloses**
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
what the specification says — and the repair, a fingerprint constrained to
be a pure function of the computation the verifier performed, is drafted as
proposal **WRT-005** (`proposals/WRT-005-outcome-fingerprint-purity.md` in the
master tree) and sent through its own adversarial gate rather than
adopted here. That gate has already earned its place across three rounds: the
first found two further re-openers the first draft missed — a budget the filer
starves until the honest computation exhausts, and a semantic no-op that wraps
the settled term into a fresh identity, one of which the draft had certified
as its *positive* novelty control; the second broke the identity the second
draft had *recommended*, then out-argued its case; and the third — the first
from a different vendor — broke the eligibility rule at its root/nested seam,
declined one over-strong objection with a reproduction, and forced the repair
to state what it had quietly given up. The rule that survives is a fingerprint
that is the hash of the result value alone, admitted only when that value
carries no trace of a computation's failure — and the honest theorem beside
it: false-positive novelty is now impossible, and false-negative novelty (two
routes to one value are one consequence) is guaranteed and intended. The
repair is at its fourth revision, still unadopted; the point of recording this
is not that it is finished but that the same adversarial loop that found the
defect is the one deciding when it is closed — and that the loop has now
recorded, as an open need (NEED-001), the evidence class it cannot itself
supply: a *semantic* review by an independent human logician **or** a
context-isolated agent. That review is useful but optional — not a blocker on
adoption — and the project does not wait on human participation that may never
arrive.

One thing the loop did produce that a model round could not: the narrow rule
that survived is now *mechanized*. Its two acceptance invariants — a
fingerprint is a function of the eligible result value and nothing a filer
writes, and a settled matter cannot be re-opened without a new demonstrated
value — are proved theorems in Lean 4 (`proofs/Settlement.lean`, a sound axiom
cone, no `sorry`), so the four attack families fail *for all inputs* rather
than on the harness's concrete ones, and a genuinely new result is proved
admissible so the guarantee is not vacuous. Three honesties about the scope,
because a proof that overclaims is worse than none. The theorems are about the
rule's **algebra given a result value**; they model the evaluator abstractly
as a deterministic function, which is the rule's stated precondition, and do
*not* re-mechanize Book I. One further guarantee — that no budget the filer
picks yields a *different* eligible result — is stated conditionally on a Book
I stability fact that the sibling repository has not yet proved, and is carried
as an explicit hypothesis rather than assumed away; the four families' closure
does not depend on it (a starved run produces a DISSONANCE, ineligible
unconditionally). And a proof that the rule has this shape is not a proof that
the running Python/Go code computes this rule — that refinement is the standing
implementation gap (Section 6). What the mechanization does buy is that the
rule is *exactly what it says* — its structural algebra over a result value, and
no claim about semantic relevance, settlement-policy correctness, the
Python/Go refinement, evaluator correctness, or authorization; whether
"consequence = result value" is the *right* semantics is left open (NEED-001).

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

## 5.5 Two grades of evidence: integrity now, historicity only with a witness

The motivating dispute — *which policy was in force when the bot answered?* —
forces a distinction the earlier framing blurred, and a reviewer was right to
make us name it as part of the system model rather than bury it in the limits.
Content addressing proves *these bytes have not changed relative to this
identifier*. It does **not** prove *these were the bytes that existed on date
T*, nor *this is the complete history a party would have seen on date T*. A
Warrant store establishes only its own internal DAG relationships; timestamps
are attacker-writable, signature-creation time is unrepresented, a
formerly-valid key can sign into an old DAG position after it is compromised,
and deletion or withholding is not detected as a completeness failure
(Section 8). So there are two grades of evidence, and only the first is
self-contained:

- **Self-contained integrity and replay** — provided by a Warrant store
  alone: the records say what they say, the keys signed them, the `ski@v1`
  reasons re-execute.
- **Historical existence and non-equivocation** — provided *only* when records
  or periodic checkpoints carry independently verifiable external receipts: a
  transparency-log inclusion (SCITT [@scitt2026] is designed for exactly this),
  an OpenTimestamps anchor, or an archive snapshot, made *before* the dispute.

The composition is the honest answer to the Air Canada question. A bare
Warrant store demonstrates a record that *would have been* useful if honestly
created at the time; a Warrant store plus a pre-dispute transparency receipt
demonstrates a record that can *prove it existed* at the time. Those are
different evidentiary products, and only the second closes the motivating
scenario — which is why anchoring belongs in the system model here, not only
in the residuals.

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
holds 92 documents — 70 inbound reviews and gates plus 22 written
responses. Of the inbound reviews, all but one fall under fourteen reviewer
labels drawn from six model vendors (OpenAI, Google, Anthropic, DeepSeek,
Moonshot, Alibaba); the remaining review is unattributed. That **one
unattributed review** has its author, model, and vendor recorded literally as
*unrecorded* in its manifest — counted in the total, claimed for no label or
vendor, so it cannot silently drop out of the census. The corpus spans specification audits,
cryptographic attacks, release-surface gates, governance-proposal adversarial
rounds, three design-gate rounds on the settlement repair, and whole-paper
adversarial model reviews — each of which, like every entry here, is
LLM-authored or unattributed, and none of which is the human peer review the
paper still lacks.

We are careful about what that number is and is not. It is a **label
census**: the labels are a filename convention this repository controls, the
vendor mapping is a table in the claims checker where it can be disputed, and
none of it measures reviewer *independence*. Every reviewing family was
operated by one person on one account, through one orchestration layer that
chose what each model saw, in what order, and when each review stopped, so —
in the format's own language — six vendors are not six epistemic custodians,
for the same reason two co-located keys are not two custodies (Section 8).
**Zero gates have been authored by a human domain expert; none is
cross-paradigm.** The ledger therefore supports a claim of *sustained
adversarial engineering that repeatedly found real defects*, and does **not**
support a claim of *independent validation of the specification* — the
clean-room implementation that would supply the latter has not happened, and
we say so rather than let the document count imply otherwise.

Three observations from the corpus shape how we read any single green result.
First, correlational and stated as such: in one governance-review sequence a
single family iterating produced eight consecutive amendments and no critical
finding, while the first three-family round on the same artifact returned six
critical findings — one episode, with confounders (the artifact moved between
rounds, prompts differed, the orchestrator chose the stopping points), read as
a reason to buy diversity, not a proof that diversity beats depth. Second, and
sharper because it points at *target* rather than vendor: three consecutive
design-gate rounds attacked the settlement repair and got steadily narrower,
each finding a padding one layer down; the *first review aimed at the whole
paper* found a larger issue underneath all of them — that a re-executable
reason is not, in the core format, bound to the policy or decision it
accompanies (Section 1.2). Depth on one target is not breadth across targets.
Third, the audits repeatedly found
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
implementer. A distinct and stronger evidence class the ledger cannot supply
is a from-scratch implementation of the spec by a party — a person **or** a
context-isolated agent — that has never read this code (recorded as the open
need NEED-002). It has not happened; it would strengthen a 1.0 claim, but it is
an evidence boundary, not a blocker on merge, adoption, release, or version
number, and the project does not wait on it. The review of this paper's own first draft is
itself a data point for the method: it predicted the `expect`-flip of
Section 5.2 from the fingerprint definition alone, the reproduction
confirmed it against both implementations, and the finding travelled back
into this text and into the ledger before the draft left the repository.

# 8. What Warrant does not provide

Each item below is a scoped assumption or an explicit non-goal, stated
here because leaving any of them out would make Section 1's claim false.
The repository's threat model states them as an attacker-capability matrix;
we compress the load-bearing rows.

**A reason is not bound to the decision it accompanies (NG-7, the
justification-binding gap).** This is the residual a whole-paper review put at
the centre, and it belongs first. The core format pins the policy, subject,
evidence, and check into one signed record, and verifies that the check
re-executes — but it does not require the check to *consume* the policy, the
subject, or the evidence, nor to *entail* the decision. A filer can attach a
term equivalent to a constant that reproduces its own declared result, and a
verifier confirms every fact while no semantic thread connects policy,
evidence, and `accept` (Section 1.2). Today the gap is narrowed only by an
authoring convention (the policy toolchain pins its source as evidence and
recompiles deterministically), not by a verifier-checkable invariant. Closing
it is a reason-binding profile — commit the policy-source hash, a fact
manifest, the evidence hashes, and a result→decision mapping alongside the
check — drafted as an **unmerged reason-binding (declaration-coherence)
candidate carried in the frozen pull request #30, not present in the master
tree**, with a running prototype and negative controls, unadopted. (It must not
be confused with WRT-004, which is the closed verify-report work; see `MAP.md`.)
Until a verifier enforces it, **"reason" is in part a promise the filer makes**,
and cryptography does not detect promises.

**Key identity is not actor identity.** Anyone
with a keypair can file a record claiming any actor id; at base grade the
verifier reports the binding unverified and exits successfully with a
warning. A base Warrant establishes *this signature verifies under this public
key*, never *this real-world or system actor made this decision*; actor
identity emerges only relative to a supplied trust configuration, and we keep
the two terms distinct throughout. This is disclosed, and it was measured rather than theorized: the
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
was found by that same consumer and fixed. To state the boundary without
euphemism: Warrant establishes **signature validity under a key**
(key-relative cryptographic authorship), **not** that an `actor.id` belongs to
a real person or organization. It is **not an identity-federation protocol**,
requires a local/pinned trust configuration for any actor attribution, and is
**not proposed as a replacement for DID, X.509, or OIDC**. There is no
identity-federation path (no DID, no X.509, no OIDC-bound ephemeral keys) and no
design for one in this format.

**`cmd@v1` verdicts are trusted by specification, and that trust reaches
settlement** (Section 5.2). The drafted repair (**WRT-005**,
`proposals/WRT-005-outcome-fingerprint-purity.md`, DRAFT / not adopted) **would
close this if adopted, by *scope reduction***, not by fixing it: a
container-executed check the verifier cannot re-run would be made unable to
contribute settlement novelty at all, so `cmd@v1` re-litigation would become
evidence-gated only. We make no claim
about how common `cmd@v1` is across deployments — this repository has no basis
to measure that — so the honest statement is bounded: for any decision whose
reason is a `cmd@v1` check, that reason is not stranger-replayable and gains at
most evidence-only settlement novelty. The room with the hole is closed off;
the hole itself is not repairable without a runtime the verifier can
re-execute.

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
of its security argument, not merely its archival one — a row the threat
model has since gained (SA-12).

**The most novel layer is the least proven implementable.** Three-way
parity is a base-grade claim; settlement-grade parity is two-way;
multi-root behaviour is vectored only as far as root admission. The
from-scratch Rust cryptography — written without external crates as a
deliberate trusted-base-diversification experiment, **not** as a security
virtue — is differentially and conformance tested, which finds divergences but
does **not** prove the absence of cryptographic defects; two were in fact found
after a 452-case random differential had passed (Section 6). A hand-rolled
Ed25519 is **not a production recommendation**: a production deployment should
use a maintained, audited cryptographic implementation while preserving the
normative reject behaviour this format pins (the torsion/scalar acceptance set
of Section 4). Part of the mechanized proof chain in the sibling repository
rests on `native_decide`, which places the Lean compiler in the trusted base,
and that condition is not discharged.

**Deposited is not reviewed.** Once deposited at a DOI, this paper is a frozen
artifact at a permanent address. It is not a venue, a peer review, or an
endorsement, and nothing in it should be cited as though it were.

# 9. Conclusion

The gap this format addresses is narrow and, we think, real: between
telemetry that records what an agent did on the operator's word, and a
record asserting a decision whose content identity and governing-policy
reference can be recomputed and whose stated justification — for one
reason class — can be re-executed by a stranger from the bytes alone. We are precise about that verb, because it is the whole
honesty of the paper: a verified Warrant proves integrity, signature validity
under a key, and replay (Section 1.2); it does not prove that the replayed
computation is an interpretation of the policy or an entailment of the decision,
and where an earlier draft let "reason" imply the latter, this one does not. The
contribution is best named as **replayable decision-justification receipts**,
not machine reasoning — and the discipline connecting the mechanisms: anything
two independent implementations cannot agree on byte-exactly stays out of the
specification, an unexecuted check is never a passed check, every residual is
written where a reader meets it, and the settlement layer is presented as the
experiment it is rather than the feature it is not. Around that core sit two
compositions we now state plainly instead of understating: a transparency
service (SCITT) for the historicity a self-contained store cannot supply, and
a drafted-and-prototyped reason-binding (declaration-coherence) candidate —
unmerged, carried in the frozen pull request #30, not a canonical WRT in the
master tree — for the policy-to-decision entailment the core format leaves open.

Two further evidence classes would strengthen the format, and the project
treats both as useful-but-optional open needs rather than gates it waits on: an
implementation by a party — a person **or** a context-isolated agent — who has
only the text (the conformance pack is the standing invitation, NEED-002), and
a semantic review of the justification-binding gap and the settlement calculus
by an independent human logician or context-isolated agent (NEED-001), which
the model-gate loop has said it cannot itself substitute for. Neither is a
blocker on merge, adoption, or deposit.

# Availability

The specification, all three implementations, the conformance pack, the
review ledger, the threat model, the settlement-rule Lean mechanization
(`proofs/Settlement.lean`), and the settlement outcome-fingerprint proposal
(**WRT-005**, `proposals/WRT-005-outcome-fingerprint-purity.md`) with its
counter-vector fixtures, plus every vector cited here, are at
<https://github.com/s0fractal/warrant> (MIT). The reason-binding
(declaration-coherence) candidate is **unmerged** — it is carried in the frozen
pull request #30, not in the master tree — and is named here as a direction,
not an available file; `MAP.md` records the historical WRT-003 (verification
receipts) and WRT-004 (verify-report) as closed, unrelated work. The `ski@v1` runtime and its
Lean 4 mechanization are at <https://github.com/s0fractal/sigma-glyph>.
Software Heritage holds snapshots of both repositories from 2026-07-28;
archival of the exact deposited commit is requested at deposit time and is
stated here only once confirmed, not implied in advance. Disclosure manifests
are timestamped via OpenTimestamps. This paper's Zenodo DOI is
[`10.5281/zenodo.22172098`](https://doi.org/10.5281/zenodo.22172098) — reserved
before the final build so the identifier appears in this artifact, and
resolving to the deposited version once that version is published. This is
**version 1.0.0 of the paper** — a deposit version, not a Warrant software or
protocol release and not a v1.0 adoption of the format; a claims checker
deposited beside this paper recomputes its countable numbers from the repository
commit this version was built from.
