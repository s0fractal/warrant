---
title: "What Remains Open: From Verified Decision Records to Settled Obligations Between Agents"
subtitle: "Working draft 0.2, written for review of the vision; not deposited"
author: "Serhii Glova (independent) — sergey.glova@gmail.com"
date: 2026-10-17
keywords:
  - AI agents
  - accountability
  - obligations
  - commitments
  - provenance
  - verifiable computation
  - multi-agent coordination
classification: cs.MA, cs.SE, cs.CR
bibliography: references.bib
---

# Abstract

A verified decision record establishes less than its readers tend to assume.
The companion paper [@glova2026reason] establishes three things about a
Warrant record:

- **integrity:** these bytes hash to this identity;
- **signature validity:** this signature is valid under this key;
- **replay:** this computation re-executes to this result.

It names what such a record does *not* establish: that the computation
interprets the cited policy, that its facts derive from the cited evidence, and
that the decision is the one the policy's answer requires.

This paper does three things.

1. **It reports the work that followed on those three gaps.** The work
   comprises:
   - a read-only profile that binds a decision to its policy's compiled answer;
   - a fact-provenance profile;
   - a typed, closed-vocabulary assessment of a decision under a recipient's
     profile;
   - a resumable computation kernel whose interrupted runs can be verified as
     reachable prefixes rather than trusted or discarded.
2. **It reports a lesson that recurred across all of it: evidence has a basis.**
   An actor's attestation, a runner's recorded run, a recipient's fresh
   execution and a deterministic replay are different things, and they form a
   partial order, not a ladder. The most persistent defect we found is a check
   that reports one of them under the name of a stronger one.
3. **It proposes a direction that is still a draft.** The proposal moves from
   decisions to *open loops*. A unit of work becomes a transition with a
   residual: what it relied on, what it established, which named obligations it
   closed and by what evidence, and what it opened. Closure is typed and never
   propagates. "The present" for an actor becomes a computable frontier of what
   it holds, owes or must accept.

Every claim is labelled IMPLEMENTED, DRAFT or VISION (§1.3). Section 8 lists
the gaps we know of, including those an automated review of draft 0.1 found.
Section 9 lists the questions on which we most want to be shown wrong.

# 1. Introduction

## 1.1 Where the companion paper stopped

Warrant [@warrant2026] is a record format.

- One decision is one immutable record whose identity is the SHA-256 of its
  canonical bytes.
- The policy in force is pinned by the hash of its exact text.
- The signature covers a domain-separated message.
- The stated reason can be a deterministic, budget-bounded computation that any
  reader re-executes offline.

The companion paper describes the format, its three implementations and its
conformance apparatus. It is deliberately precise about the proposition a
verified record supports, and it leaves three links explicitly open:

| Link | Question | In this paper |
|---|---|---|
| policy → computation | does the reason compute *this* policy? | §2.1 (WRT-020), §2.3 |
| evidence → facts | do the computation's inputs derive from the cited evidence? | §2.2 (WRT-010), §2.3 |
| result → decision | is the decision the one the computation's answer requires? | §2.1 (WRT-020), §2.3 |

It also reported a mostly negative result on settlement: mechanically checkable
*semantic* novelty, for adversarial re-litigation, is hard.

## 1.2 What changed in the question

The companion paper asked what a stranger can check about one decision. Working
with the format between AI agents changed the question. The author's two coding
agents review each other's changes, and the author mostly relays between them.

The decisions were rarely the hard part. The hard part was everything around
them:

- a finding raised against an exact commit;
- a fix that claims to close it;
- a re-review that accepts or amends;
- a question the fix exposed that nobody was asked to answer;
- a merge that happened on a different branch than everyone assumed.

None of this has a record of its own today. It lives in chat, in files outside
any repository, and in "done" columns. The owner is the only place where the
pieces meet.

This paper argues that the next object of an accountability format is not the
decision but the **loop**, the thing a decision is for:

- what was asked;
- what someone took on;
- what was closed, and on what basis;
- what remains open.

## 1.3 Status labels

The work below has very different degrees of finish, so every claim carries
exactly one label. The labels are mutually exclusive.

- **IMPLEMENTED:** code on the main branch of its repository, with tests. The
  merge commit is named. Whether its rules also have a mutation harness, where
  each mutant removes one rule and must fail that rule's own test case, is
  stated per item, because not all of them do. IMPLEMENTED says nothing about
  *adoption*: every component in §2 calls itself a profile or a draft
  reference, and none is part of the format's specification.
- **DRAFT:** code exists on an unmerged branch that is under review.
- **VISION:** no code. These are arguments and designs.

Nothing in this paper changes what `warrant verify` decides. Every component
is a *profile*: it reads stores and reports, and enforces nothing at the format
level.

## 1.4 Contributions

1. **IMPLEMENTED**, warrant #130, `b214c6c`: a policy-binding profile (WRT-020).
   - It classifies a (record, policy) pair as BOUND, CONTRADICTED, UNBOUND,
     OPAQUE or SIGNATURES.
   - On the repository's own stores, 23 of 24 pairs are OPAQUE (§2.1).
   - It has 12 test cases and no mutation harness.
2. **IMPLEMENTED**, warrant #70, `059ba25` (before this paper): a fact-provenance
   profile (WRT-010) that never reports an observed fact and a derived fact
   with the same word (§2.2).
3. **IMPLEMENTED**, warrant #131, on master via `b214c6c`: a typed assessment.
   - It reports a decision on closed axes under a recipient-owned profile.
   - It works over one immutable snapshot of the store and the trust
     configuration (§2.3).
   - It has 29 cases passing, 1 named as unrun, and 17 mutants, each killed on
     its own case.
4. **IMPLEMENTED**, sigma-glyph #62, `c864d3e`: a resumable combinator kernel.
   - Its computation identity excludes the budget.
   - It has no control state outside the machine-state tree.
   - Its checkpoints accumulate credit.
   - Its verifier proves an interrupted run to be a reachable PREFIX rather
     than an answer (§3).
   - It has 46 cases passing, 3 named as unrun, and 22 mutants, each killed on
     its own case.
5. **IMPLEMENTED**, warrant #129, `ca53e64`: a proof attestation reported as
   CLAIMED and never as PASSED (§4.2). The *separation of evidence bases* is
   otherwise a rule in prose (§4.1), and checked only in the DRAFT of
   contribution 6.
6. **DRAFT**, warrant PR #133 at `5c84580`: WRT-021, an open-loop profile.
   - It covers duties, transitions with a residual, typed closure, consent for
     transfer, and a per-actor frontier.
   - It has 36 test cases and 42 mutants, each killed on its own case.
   - It was exercised on three transcribed specimens (§5).
7. **VISION:** settlement between agents as a design objective, and the threats
   to it that we can already name (§6, §8).

# 2. Closing the three links, as profiles

## 2.1 Policy → computation and result → decision (WRT-020; IMPLEMENTED)

There are two gaps. Both are executable today.

**Gap 1.** Take a record that cites a prose policy `DENY_ALL`, gives a real
`ski@v1` reason that computes something unrelated, and accepts. Settlement-grade
verification with required key binding reports zero errors in all three
implementations. The policy and the computation are never connected.

**Gap 2** is sharper. Here the policy *is* machine-readable (WPL, a small policy
language that compiles to a combinator term), and the reason *is* its exact
compilation:

- the policy asks whether a refund of 65088 (integer cents, that is 650.88) is
  within a limit of 50000;
- the compiled term replays to Church FALSE;
- the record accepts.

`warrant verify` reports `ok: true`. The format's own documentation warns that
`verdict pass` means "re-execution reproduced the pinned answer", not "the
policy said yes". Nothing connected that answer to the decision.

The profile (`impl/policy_binding.py`) assigns one of five statuses to each
pair:

| Status | Meaning |
|---|---|
| BOUND | the policy is WPL; a `ski@v1` reason claiming `pass` runs exactly its compilation (same term and expected answer, at least the budget needed); the decision does not contradict the answer |
| CONTRADICTED | as BOUND, but the record *accepts* while the policy answers false |
| UNBOUND | WPL policy, but no reason runs its compilation with its answer and enough budget |
| OPAQUE | the policy is not machine-readable, so compliance is **not checked** |
| SIGNATURES | a threshold policy that governs who signs, which settlement already enforces |

**Only `accept` is gated.** A `reject` where the policy would allow is treated
as discretion, never as a contradiction. Whether that is right is the profile's
own open question: a jurisdiction may require acceptance when its rule is met,
and the format has no polarity to say so. §2.3 makes the same choice explicit
per recipient.

**Measured result.** Over all 24 (record, policy) pairs in the repository's
four stores, 23 are OPAQUE and 1 is SIGNATURES. There are no BOUND, no
CONTRADICTED and no UNBOUND pairs.

The repository that defines the format does not author its own records in a way
the format can check. We report this as the main finding of the section.
Making CONTRADICTED a verify-time error would break nothing we can measure,
because nothing we can measure is checkable.

The profile's recommendation is therefore an authoring rule first: cite the
machine-readable source next to the prose. Normative enforcement would wait
until the compiler identity is pinned, and §2.3 shows one way to pin it. In
WRT-020's WPL, a file still holds the rule *and* its facts, so the "policy" is
per decision. §2.3 separates them.

## 2.2 Evidence → facts (WRT-010; IMPLEMENTED, before this paper)

Facts come in two kinds that must never be reported with the same word:

- **observed:** someone measured the world. A verifier can say only "attested
  by X".
- **derived:** a consequence of store contents, with a re-runnable derivation.
  A verifier can say derived, contradicted, underived or stale.

Per record, the profile returns `complete`, `not-applicable` or `incomplete`.
These are its literal lower-case values. `incomplete` exists because a deleted
provenance document and a record that never had one would otherwise give the
same answer: when any cited evidence blob is missing or off-address, the
absence of a provenance document cannot be told from its loss.

The profile went through five adversarial review rounds before acceptance in
its scope, and its test file includes its own mutations. The typed assessment
of §2.3 does not yet consume these statuses. It applies its own, narrower fact
check, and unifying the two is open (§8).

## 2.3 Typed assessment (REDESIGN-1 P3/P4; IMPLEMENTED)

The three links meet in one report. A decision is assessed under a **recipient
profile**. The profile holds:

- the admitted policy programs;
- the obligation;
- the trust configuration;
- the admitted fact issuers;
- whether a reject is discretionary, with no default (the recipient must
  choose);
- the evidence slots that count as new;
- the required profile class;
- the semantics class.

The decision itself cites three typed blobs:

- a **PolicyProgram**: the rule, with typed parameters and no fact values;
- a **FactSet**: each fact either observed (with the record of its attestation)
  or derived (with the record and check it comes from);
- a **CompilationPlan**: the registered compiler, the declared options, and
  what was emitted (`{check, term, expect, atp}`).

The registered compiler's identity includes the digest of the compiler's own
source file, `policy_lang.py`. This pins the compiler against drift,
which is the question §2.1 leaves open. A compiler named in a package is never
executed. The assessment recompiles program plus facts with the registered
compiler and compares every emitted value.

The report has closed axes:

| Axis | Values |
|---|---|
| record_integrity | VERIFIED, INVALID |
| policy_authority | ADMITTED, AUTHORITY_UNESTABLISHED, NOT_ASSESSED |
| fact_provenance | ACCEPTED, UNATTESTED, DERIVATION_MISMATCH, TYPE_MISMATCH, NOT_ASSESSED |
| compilation_binding | MATCHED_COMPILATION, COMPILATION_MISMATCH, UNREGISTERED_COMPILER, NOT_ASSESSED |
| computation_verification | REPLAYED_NORMAL_FORM, PAUSED, BLOCKED_REFERENCE, HOST_UNAVAILABLE, NOT_ASSESSED |
| policy_answer | TRUE, FALSE, NON_BOOLEAN, NOT_ASSESSED |
| decision_compliance | COMPLIANT, CONTRADICTED_DECISION, NOT_ASSESSED |
| required_profile | SATISFIED, REQUIRED_PROFILE_NOT_SATISFIED |

What the axis values mean:

- **`fact_provenance` is ACCEPTED** only if three things hold:
  - the FactSet names exactly the program's parameters with their exact types
    (TYPE_MISMATCH otherwise);
  - each observed fact is attested, about exactly its value, by an admitted
    issuer's bound record;
  - each derived fact is a Boolean equal to a replayed answer of the record it
    cites.
- **`required_profile` is SATISFIED** iff the record cites all three typed
  blobs, or the recipient's required class is `witness`.
- **`decision_compliance`** is decided as follows:
  - an `accept` is COMPLIANT if the answer is TRUE and CONTRADICTED_DECISION if
    it is FALSE;
  - a `reject` is COMPLIANT if the answer is FALSE; if the answer is TRUE, it is
    COMPLIANT when the recipient set `discretionary_reject`, and
    CONTRADICTED_DECISION otherwise;
  - NON_BOOLEAN, or no normal form, gives NOT_ASSESSED for either decision.

`consumer_admits_action` is true only for an `accept` that is COMPLIANT under a
SATISFIED profile. A run that did not finish is never TRUE or FALSE.

**Novelty.** A report is a **consequence** only if all of the following hold:

- it is under this recipient's profile;
- the record verified;
- the facts are ACCEPTED;
- the profile is SATISFIED;
- the authority is ADMITTED;
- the compilation matched;
- a normal form was replayed to TRUE or FALSE.

Compliance is not required: a correctly obtained FALSE is a consequence even
when an accept contradicts it.

`novelty(settled, candidate)` returns exactly one value, checked in this order:

1. MIGRATION_REQUIRED, if the candidate is under another semantics class;
2. SCOPE_MISMATCH, if it addresses another obligation;
3. NO_NEW_CONSEQUENCE, if either report is not a consequence;
4. NEW_CONSEQUENCE, if the replayed answer differs;
5. NEW_EVIDENCE, if the answer is the same but an accepted value in a named
   slot differs;
6. NO_NEW_CONSEQUENCE otherwise. This covers progress, wrappers, budget,
   checkpoints, claimed verdicts, unnamed blobs and renamed tuples.

A PAUSED report is not a consequence, so it settles nothing. The first report
that reaches a normal form is the first consequence.

This is a narrower and more checkable answer to the companion paper's negative
settlement result. Semantic novelty in general is not decided. Only novelty
*relative to a recipient's named slots* is. Two weaknesses follow from that
narrowness, and both are open (§8):

- **Slot churn.** Any changed accepted value in a named slot is NEW_EVIDENCE,
  even one that leaves the answer unchanged. That includes cycles such as
  A → B → A, because comparison is pairwise.
- **Out-of-schema discoveries.** A new defect class, a trust change or a stale
  derivation that is not in a named slot is NO_NEW_CONSEQUENCE.

**Method note.** One adversarial review of this component found a
time-of-check/time-of-use defect. The assessment called the command-line
verifier on the live store, then judged records it had read separately. A
writer that swapped one complete record for another between the two reads made
the verifier approve one envelope while the assessment judged another. The fix
reads the store and the trust file exactly once into a private snapshot, and
every later step reads only the snapshot.

**Measured state** at `416ea4a`:

- `tests/assessment_test.py`: 29 PASS, 0 FAIL, 1 UNRUN. The UNRUN is named:
  cycle consequences need a runtime that `ski@v1` Boolean policies lack.
- 17 mutants, all killed on their own case.

# 3. Computation that can stop (sigma-resume; IMPLEMENTED)

A budget-bounded check either finishes or fails. Between agents this is too
coarse: work gets cut by time limits, by action limits and by a host's
resources, and is resumed elsewhere. The question is what an interrupted run
proves. The sigma-resume kernel answers it. The kernel runs on Σ-GLYPH
[@glova2026sigma], a content-addressed combinator machine. Its *Book I*
profile is the base S/K/I reduction with size-priced actions. The kernel is
specified in sigma-glyph's `spec/drafts/sigma-resume-draft-1.md` and was merged
at `c864d3e`.

**Identity without budget.** A computation is identified by
`{runtime semantics, cost model, input term hash, environment manifest}`. The
budget is not part of it, so one term under two budgets is one computation. One
term under two runtime profiles is two computations. Because the environment
manifest is part of the identity, *extending* the manifest starts a new
computation, not a continuation (see BLOCKED_REFERENCE below).

**Machine state, and no control state.** The machine state is the term *tree*,
serialized canonically. Its tag carries the computation identity, and the tree
is written in preorder: application nodes, plus thunks, literals, references
and dissonance nodes, each with its 32-byte hash. A thunk and its
materialization are different machine states that share a term hash. For
example, a cold thunk and the materialized `APPLY(I, K)` have the same term
hash with sizes 1 and 3.

"No control state" means that nothing else exists: no stack, no program
counter, no budget-dependent mode. The evaluator derives the next demanded
action from the tree on every call. Which action it picks does not depend on
the remaining budget; the budget only decides whether that action is
affordable. This was measured over 20,114 (state, budget) pairs.

**Segmentation invariance** follows from determinism plus pre-checked, atomic
charging: any split of the same total credit reaches the same state, cost and
outcome (measured over 12,649 partitions). Both properties are measured, not
mechanically proved. Unlike the parser modules in §4.2, the kernel has no
Creusot or Lean proof.

**Kernel outcomes and local outcomes are disjoint.**

- Kernel outcomes say something about the computation:
  - NORMAL_FORM: no next action, which is not "TRUE";
  - PAUSED: the next action costs more than is available;
  - BLOCKED_REFERENCE: the demanded hash is outside the manifest, and is named.
- Local outcomes say something about this host: EVIDENCE_UNAVAILABLE,
  CAS_MISMATCH, INCOMPLETE, ADMISSION_REFUSED and RESOURCE_FAULT.

A local outcome never stands in for an answer.

**Verification of a prefix.** The verifier chooses the root and its context
(environment, runtime and cost model; anything else is CONTEXT_MISMATCH). It
then does the following:

1. It checks that the state bytes hash to the checkpoint's `state_id`
   (STATE_MISMATCH otherwise).
2. It replays from the root, or from a checkpoint this verifier itself replayed
   before, to the checkpoint's claimed *spent* total.
3. It requires the replayed state id, spent total and peak size to be equal to
   the claimed ones. Because spent strictly increases, at most one state has a
   given spent total. A claimed total that a multi-unit action steps over
   cannot be matched, so it is UNVERIFIED_PREFIX.
4. On a match, the checkpoint is REPLAYED. Its kind at its own credit is either
   the kernel outcome, if no further action fits, or **PREFIX**: a verified
   reachable state with credit for more. PREFIX is never terminal.

No signature is consulted. In the assessment of §2.3, an unfinished
computation is reported on its own axis (PAUSED and the like), never as an
answer.

**Cost, and what PREFIX is for.** Verifying a prefix replays it, so it costs as
much as producing it. Across untrusted peers, prefix verification therefore
does not *save* work: *k* untrusted hand-offs that each verify from the root
cost O(*k*·*C*). The only amortization is a verifier's own cache of prefixes it
replayed itself. PREFIX is an audit and fault-isolation primitive. It confirms
that a runner reached a valid intermediate state before more budget is
allocated, and it lets a verifier resume from its own verified states. It is
not a way for one peer to inherit another's work on trust.

**BLOCKED_REFERENCE and host-observing work.** The kernel is pure. It cannot
represent a test run, a network probe or model inference. The natural boundary
is BLOCKED_REFERENCE:

- pure reduction pauses at a demanded hash the manifest lacks;
- an issuer or runner attests the missing input;
- reduction continues under an extended manifest.

But an extended manifest is a new computation identity. *Chaining* computations
across attested inputs is not specified, and it is open (§8, §9).

**Cycles.** A cycle witness names the entry spent total, the entry state id, a
period action count and a period cost. It is admitted only on four conditions:

- at least one priced action;
- the exact claimed cost;
- no terminal state on the way;
- the identical machine state at the end, not merely the identical term hash.

Under the Book I profile no cyclic term is known: an exhaustive search of all
3.1 million SKI terms with at most eight leaves found none. This is a
measurement, not a proof. A richer profile with Y, M and W primitives has real
cycles (`Y I` with period 2, `M M` with period 1).

**Measured state** at `c864d3e`:

- `tests/resume_test.py`: 46 PASS, 0 FAIL, 3 UNRUN, each named.
- 22 mutants, all killed on their own case.
- The Python/Rust differential and its controls run as a CI step.

**The acceptance scenario, end to end.** The scenario is
`demos/redesign-refund/run.py` in warrant, re-run for this paper. It runs
offline, in nine steps:

1. A recipient admits a refund policy, an obligation and an issuer.
2. The issuer attests the amount: 65088 cents.
3. Producer A starts the computation and is cut by an action limit: INCOMPLETE,
   with credit left.
4. Producer B, a separate process with only the files, verifies that checkpoint
   as REPLAYED, of kind PREFIX.
5. Producer B finishes the run to NORMAL_FORM. The answer is FALSE, which
   warrant's own `ski@v1` replay confirms.
6. A signed accept is assessed as CONTRADICTED_DECISION, and the consumer does
   not act.
7. A witness's reject is COMPLIANT.
8. Re-filing with more budget is NO_NEW_CONSEQUENCE.
9. A new attested observation that leaves the answer FALSE is NEW_EVIDENCE.
   Under a later observation, the policy answers TRUE: that is a
   NEW_CONSEQUENCE, and its accept is admitted.

# 4. Evidence that knows its basis

## 4.1 Four bases, partially ordered

Over the work above, one defect shape recurred more than any other: a check
that reports a weaker kind of evidence under the name of a stronger one. We
keep four bases apart and never upgrade one into another:

| Basis | Profile token (WRT-021) | What it establishes | Who can establish it |
|---|---|---|---|
| actor attestation | `ATTESTED` | a named actor signed a statement about addressed evidence | any producer |
| runner attestation | `RUNNER_ATTESTED` | an addressed runner recorded a run: inputs, environment, command, limits, observed output | a producer holding a runner key; without key isolation it is an actor attestation over a structured log (§8) |
| recipient re-execution | `RECIPIENT_REEXECUTED` | the recipient ran it again, under its own policy | only the assessing recipient, in its own view |
| deterministic replay | `REPLAYED` | a portable term was re-reduced to its normal form | any verifier, for pure computation only |

The bases are **partially ordered, not a ladder**. Replay is stronger than
attestation for pure computation, but it cannot observe the world, where a run
or a re-execution is what is needed. Two of them are also **view-local**:

- A recipient's re-execution is a re-execution *for that recipient*. Stored
  where others can read it, it is that recipient's attestation, not a
  re-execution for the next reader.
- A replay counts for the verifier that performed it.

This is why the WRT-021 draft records an acceptor's own re-execution as
*support* without raising any basis (§5).

The governance text of the warrant repository states the rule for agents' own
work: "never upgrade one into another".

## 4.2 A proof attestation that stays CLAIMED (IMPLEMENTED, warrant #129)

Three Rust source files of the verifier are proved with Creusot:

- canonical hex;
- the range checks that make Ed25519 and P-256 encodings canonical;
- the self-delimitation of JSON string quoting.

The proof crate compiles the shipped files through `#[path]`, not copies. The
contracts sit under `cfg_attr(creusot, ...)`, so a normal build drops them.

Re-running the provers in CI is slow and environment-sensitive. So CI accepts a
signed **attestation** of a local run instead, and reports it as CLAIMED, never
as PASSED. In the vocabulary of §4.1 it is an *actor attestation* by an agent
key over a run log, scoped so that no other check consults its trust file.

The attestation's subject is a manifest of the SHA-256 of every proof input.
Inputs are deny-by-default:

- every file of the proof crate;
- every file its sources name by path;
- the Cargo and toolchain configuration of every ancestor directory.

Before signing, the attester checks that every file rustc's dependency
information says it read is in the manifest, and that every input is tracked
by git.

An adversarial review of the first version found that a build script was
outside the manifest. The deny-by-default rule is the repair. A later review
found that a symlinked configuration directory escaped it. Symlinks are now
refused as unsupported inputs.

**Residual assumptions** of a CLAIMED attestation are recorded in its evidence
but **not checked**:

- the Rust toolchain;
- the Creusot installation;
- the Why3 configuration;
- the SMT solvers and their settings;
- the user-level Cargo configuration.

An automated review of this paper's previous draft added three more that we
had not listed:

- environment flags such as `RUSTFLAGS` and `--cfg`, which change compilation
  without changing a file;
- the proof crate's own dependency and feature context, which can differ from
  the production crate that compiles the same files;
- whether the solvers discharged every goal, as distinct from the translation
  completing. This one is checked indirectly: the attester's mutation run
  requires each mutant to be caught.

## 4.3 The same defect, in our own draft

The draft of §5 shipped with exactly this defect, and an independent review
found it. A transition that *claimed* the basis `REPLAYED` had a prose reason
and cited an evidence hash absent from the store, yet it was assessed as
discharged with basis `REPLAYED`. No replay had run.

The repair separates the claimed basis from the assessed one. The profile
validates only what it can: actor attestations of evidence that resolves to its
exact bytes. Candidates claiming any other basis are reported UNVERIFIED_BASIS
and close nothing.

**Why not call the existing replay verifiers?** `ski@v1` replay and
sigma-resume's `verify` both exist. What is missing is a receipt schema that
binds a transition's closure to a specific replayable computation and its
root. It is an integration not yet built, not a format gap.

The consequence is visible in one of our specimens. A service-recovery
obligation that admits only a runner attestation stays OPEN even after a real
probe run, because the profile cannot yet validate runner evidence. We consider
that the correct output. We also name the pressure it creates (§8): with only
attestation validated, the convenient move is to admit attestation everywhere.

# 5. Open loops (WRT-021; DRAFT)

## 5.1 Content, demand and duty

The draft separates three objects:

- **Claim:** a proposition, addressed by content. It binds nobody.
- **Question:** an epistemic demand, such as "does P hold?" or "what is missing
  for G?". It binds nobody until someone takes it on.
- **Duty:** a loop an actor has taken on, to answer a question, reach a state or
  keep a condition. It binds its holder, under persistence authority.

A model that generates a hypothesis creates a claim. A check that exposes a
missing premise creates a question. Neither assigns work.

In the draft as implemented, a duty is opened only by its holder's own signed
act. There is no policy that assigns duties automatically. Allowing one would
reintroduce the problem the separation exists to stop, unless it is bounded
(§8).

The kinds of duty come from a dialogue series on obligation and intention
[@manifesto2026], restated as rules:

- **goal:** a future state granted planning relevance;
- **commitment:** a goal plus persistence authority;
- **obligation:** owed to someone;
- **purpose:** a generator of other loops that is never itself discharged.

Only obligations are implemented.

## 5.2 The transition with a residual

The central record is a **transition**. It is an instance of a recipe in the
sense of the manifesto's Invariant Recipe Method [@manifesto2026]:
prerequisites, transformation, guarantees, losses, boundary, and a closure
condition. Its fields are:

- what it relied on;
- what it addressed;
- what was done, with a *claimed* evidence basis;
- what it established;
- an explicit list of closure mappings, each naming one duty, a disposition and
  the evidence that supports that mapping;
- what it opened;
- what it does not establish;
- its scope.

One review round can close two findings, establish a reusable lemma and expose
three assumptions, and all of that is one transition.

## 5.3 Typed closure

The draft's central rule is that a closure mapping closes exactly the duty it
names, with exactly the disposition its evidence supports.

- **Discharge never propagates.** Closing a child never closes the parent it
  serves, even when it is the only child.
- **A parent may name children in its own closure condition.** That condition
  is evaluated on the parent's own candidate *at every assessment*. If a named
  child later becomes contested or loses its discharge, the parent's candidate
  becomes UNMET_CONDITION again, and `reliance` no longer reports it. So
  *invalidation* is reflected upward through re-evaluation, while discharge
  never is. The children must be named when the parent is opened; children
  discovered later cannot yet be added (§8).
- **Three axes are kept apart:**
  - *disposition*: discharged, released, declared impossible, delegated,
    substituted, observed;
  - *evidence basis* (§4.1), where the claimed and the assessed basis are
    separate fields;
  - *admission*: which disposition × basis pairs a duty's own policy accepts,
    and whose acceptance is required.
- **Filing a closure submits a candidate.** It is admitted only by an
  assessment under a named view. A stored assertion is not an accepted closure.
- **Transfer needs consent from both sides, and liability depends on the
  kind.**
  - Only the holder transfers.
  - Under **delegation**, the delegate must accept, the holder remains the
    holder and stays liable to the creditor, and the duty stays in the holder's
    frontier.
  - Under **substitution**, the incoming actor *and* the creditor must accept,
    and only then does the holder change.

  A request that is never accepted stays pending. There is no rejection or
  expiry yet (§8). The consent rule was missing from the first implementation:
  the same review that found §4.3's defect showed a duty moving to an actor
  that had signed nothing.

## 5.4 The view, the states, and the present

An assessment names its view:

- one snapshot of the records and blobs;
- the recipient's trust snapshot;
- an `as_of` time;
- the evaluator's digest;
- completeness, which is UNATTESTED unless something attests it.

The set of revisions the recipient treats as current is an argument to the
assessment. It belongs in the view's identity, and it is not there yet (§8).

**States and candidate verdicts** (closed vocabulary):

| Name | Kind | When |
|---|---|---|
| OPEN | disposition | no admitted closure in this view; never "globally open" |
| DISCHARGED, RELEASED, DECLARED_IMPOSSIBLE | disposition | one admitted closure of that kind |
| RECURRING | disposition | a recurring duty; each instance is COVERED, LAPSED or OPEN |
| STANDING | disposition | an invariant duty, judged by fresh observations |
| NOT_IMPLEMENTED | disposition | a goal, commitment or purpose |
| CONTESTED | flag | two *admitted* closures of different kinds; an unauthorized filing cannot cause it |
| MISSING | flag | a referenced duty is not in the view; never read as open, satisfied or orphaned |
| ORPHANED | flag | every parent the duty serves is RELEASED, ABANDONED or DECLARED_IMPOSSIBLE; a root duty never is, and a DISCHARGED parent orphans nobody |
| LAPSED | flag | a recurring instance ended without a closure |
| UNOBSERVED, BREACHED | flag | an invariant without a fresh observation; with a fresh false one |
| PENDING_ACCEPTANCE, OVERCLAIMED_CANDIDATE, UNVERIFIED_CANDIDATE | flag | some candidate has that verdict |
| ADMITTED | candidate verdict | the candidate counts |
| PENDING | candidate verdict | a required acceptance or consent is missing |
| OVERCLAIMED | candidate verdict | filed by someone without authority, or with a disposition × basis pair the duty does not admit |
| UNVERIFIED_BASIS | candidate verdict | the claimed basis is one the profile cannot validate |
| MISSING_EVIDENCE | candidate verdict | cited evidence does not resolve to its exact bytes, or an attestation names none |
| UNMET_CONDITION | candidate verdict | a named child is not discharged |

An overclaimed candidate is history. It stays in the report and does not keep
an otherwise closed duty in anyone's frontier.

**The frontier.** `frontier(actor)` is the computable "present" of one actor:
the duties it holds, is delegated, is owed, may release or must accept that are
open or flagged. Two further queries complete it:

- `reliance(duty)` answers whether a current action may rely on a closure. It
  says RELIABLE only for an uncontested DISCHARGED established on a revision the
  recipient treats as current. Applicability follows the revision on which the
  *closure* was established, not the one on which the defect was found. Absence
  from someone's frontier is not reliance.
- `questions(scope)` is a shared, read-only view of unowned questions, with
  their provenance. Being listed there gives nobody a duty.

**Cost.** One assessment is linear in the number of transitions times the
number of duties, with no index, plus one settlement-grade verification of the
snapshot.

## 5.5 Measured state, and the dogfood

At `5c84580` (warrant PR #133, under review):

- 36 test cases;
- 42 mutants, each killed on its own case.

`warrant verify` at settlement grade, run on a store full of loop events,
reports no error and no re-litigation warning. This shows that the events are
*compatible with the format*. It says nothing about loop semantics, which the
verifier does not read.

Three specimens were transcribed with fixture keys whose actor names say
`*@transcribed`. No record there is anyone's own signature.

1. **A real review finding, as a frozen historical slice.**
   - The reviewer's AMEND opens a question, not a duty.
   - The author takes it on.
   - The author's attested run is a candidate, which the reviewer accepts,
     citing its own re-execution as support.
   - Closing the finding does not close the review round.
   - The merge of the reviewed branch is a separate duty. It went into a
     feature branch, not the main line.
   - The closure is UNASSESSED for the final revision until revalidated.
2. **A service recovery.** "Ticket set to Done" is OVERCLAIMED. The probe run
   is UNVERIFIED_BASIS (§4.3), and the invariant "service functional" is
   UNOBSERVED once the probe goes stale.
3. **A recurring maintenance duty.** Period 0 is covered, period 1 lapsed and
   period 2 is open.

**What the transcription found.**

- An earlier overclaim kept a closed duty in the frontier forever. This was
  fixed.
- Applicability followed the revision where a defect was found, not the one
  where its fix was established. This was fixed.
- Unowned questions were invisible. This was fixed with the shared view.
- An acceptance could not cite the acceptor's own work. This was fixed: the
  support is recorded but never raises a basis.
- A parent's condition over its children was implicit. This was fixed with
  named children.

# 6. Settlement between agents (VISION)

## 6.1 The objective

We call the objective, informally, an *anti-entropy reactor*. Generative
activity produces candidates. Settlement converts selected candidates into
reusable results with explicit conditions, residual obligations and
accountability. The point is to reduce repeated interpretive work without
pretending that uncertainty has vanished.

The intuition comes from the dialogue series [@manifesto2026, note 0038]:
closure is settlement into a cheaper representation, not deletion. The
representation we propose is a **result capsule**. It holds:

- the claim;
- its grounds, as addresses;
- the scope and view it was established under;
- its losses;
- what it may be used to close;
- the assumptions that remain;
- the changes that should trigger re-examination.

A new session, another agent or the owner continues from the capsules and the
residual frontier, and fetches the evidence on demand. Re-reading the whole
history becomes something you do for a stated reason.

Two rules guard against false compression:

- **Repetition earns no validation credit.**
- **Shared assumptions stay visible.**

The review of draft 0.1 showed that both rules, as stated, fail against an
adversary with many identities or long capsule chains. We now hold them to four
requirements that any implementation must meet:

- **Credit by role.** Validation credit counts by assessed evidence basis and by
  the recipient's admitted roles, never by the number of keys or capsule
  hashes. Ten keys re-asserting one claim count as one assertion per admitted
  role.
- **No dropped assumptions.** A capsule's open assumptions must be checked, at
  admission, to include every unresolved assumption of its grounds. Otherwise a
  chain launders them.
- **Consent on import.** Importing a capsule's assumptions into a consumer's
  frontier needs the consumer's consent, as transfer does in §5.3. Otherwise a
  widely reused lemma can flood every frontier.
- **Machine-checkable triggers.** Re-examination triggers come from a closed,
  machine-checkable vocabulary: pinned hashes, named slots, duty identifiers.
  Triggers written in prose are not triggers.

## 6.2 What is already in practice

The owner of these repositories adopted a governance text on 2026-10-17
(warrant #132, `3e551e4`). Agents push, merge and release when the applicable
obligations of the exact candidate are closed:

- review;
- regression and counterexample records;
- required CI;
- no blocking finding in that scope.

The evidence and the policy that accepts each closure must be identified. The
text keeps the boundary this paper keeps:

- a closure record supplies evidence that prerequisites were met, not new
  authority;
- green CI, a self-declared closure or access to a key cannot enlarge the
  delegation;
- the WRT-021 checker must not be pretended to exist, nor made a prerequisite
  for ordinary work.

The vision is already practised in prose by the agents it is for. The draft
profile is an attempt to make the same discipline checkable.

## 6.3 What is measured, and what is not

**What we do not optimize.** A global ratio of closed to open loops is a
tempting metric. It rewards trivial closures, punishes discovery, and turns
"unknown" into "done", the familiar fate of a measure that becomes a target
[@strathern1997ratings]. A check that exposes five real hidden dependencies may
have done more than twenty surface closures. The companion line of work on
checks that spawn further checks [@manifesto2026] makes the same point from the
other side.

**What we propose to observe instead**, each under a fixed view, as
**diagnostic telemetry, never as targets**:

- reopenings and their reasons;
- capsule reuse;
- the repeated-review cost: the same question asked again with no new evidence;
- newly exposed assumptions;
- concrete duties settled.

Each of these has its own converse failure if rewarded:

- fragmenting one premise into many "new assumptions";
- settling trivial lemmas to cite them;
- suppressing legitimate reopenings.

# 7. Related work

**Commitments in multi-agent systems.** Singh's ontology of commitments
[@singh1999commitments] treats a commitment as a relation between a debtor and
a creditor in a context, with operations to create, discharge, cancel, release,
delegate and assign. Our duty kinds and dispositions are close relatives, and
our consent rules for delegation and substitution follow the same distinction.

Later work by Chopra and Singh moved commitments away from a shared global
state:

- interaction protocols over agents' local information [@singh2011bspl];
- commitment states computed as queries over relational event data
  [@chopra2015cupid];
- norm states computed over information stores [@chopra2016custard].

Computing state locally, over an agent's own view, is therefore not new, and we
do not claim it. What we would defend as different is **evidential**:

- each event is a signed, content-addressed record;
- a closure is admitted only on an evidence basis that the duty's own policy
  names, with claimed and assessed bases kept apart;
- typed closure never propagates discharge.

Deontic logic since von Wright [@vonwright1951deontic] provides the vocabulary
of obligation and permission. We do not attempt a logic. We attempt the record
layer that a logic would have to be evaluated over.

**Obligations in access and usage control.** UCON~ABC~ [@park2004ucon] models
obligations and continuous usage decisions. XACML 3.0 [@xacml3] returns
decisions together with obligations a policy enforcement point must fulfil.
Both are stateful obligation models, and they are closer to WRT-021 than the
stateless request engines OPA [@opa] and Cedar [@cutler2024cedar]. The
difference is where the obligation's discharge is judged:

- in UCON and XACML, by the enforcement point that holds the session;
- in WRT-021, by any recipient, from signed, addressed evidence, under its own
  view.

**Proof-carrying code and authentication.** Proof-carrying code
[@necula1997pcc] and proof-carrying authentication [@appel1999pca] ship a
checkable justification with the artifact. Our replay basis is in that line.
Our contribution there is narrower: keep the replay basis distinct from the
weaker bases that, in practice, carry most real evidence.

**Supply-chain attestation.** in-toto [@torresarias2019], SLSA [@slsa] and
Sigstore [@sigstore] attest *who did what to which artifact*. A runner
attestation (§4.1) is the same kind of object. What we add is the obligation
that such an attestation is meant to discharge, and the rule that discharging
it closes nothing else.

**Provenance.** W3C PROV [@prov] records derivations but has no notion of an
open obligation.

# 8. Threats, limits and known gaps

**One operator, many keys.** Every agent key in the dogfood belongs to one
operator's environment. Agents that review each other under one owner are not
independent parties, whatever their model vendors. Without key isolation, a
"runner attestation" is an actor attestation over a structured log. The format
can record who signed. It cannot establish independence, and nothing here
should be read as claiming it.

**Collusion and convenience.** Two agents that both benefit from closing a
loop can each attest and each accept. Typed closure prevents a closure from
reaching *further* than its evidence. It does not prevent weak evidence from
being admitted by a weak policy.

**Attestation dominates, and downgrade is tempting.** Only actor attestation is
validated (§4.3). An honest claim of a stronger basis is therefore blocked,
while an attestation over the same artifact passes wherever the duty admits
attestation. The pressure is to admit attestation everywhere. Two measures are
proposed and not implemented:

- record a validated *floor* basis next to the claimed one;
- report a composite basis (computation basis, weakest input basis), so that a
  replayed computation over self-attested facts never reads as "replayed".

**Completeness and split views.** A view is a snapshot whose completeness is
UNATTESTED. A withheld closure makes a duty look open, and a withheld
reopening makes it look closed. Two parties to a transfer can assess different
views, and each can believe the other is working. Co-signed view checkpoints
over `(store snapshot, trust snapshot, as_of, evaluator)` before an
irreversible joint step are proposed and not implemented. Historicity needs an
external witness, as the companion paper's evidence grades already note.

**Revision and time.**

- The revisions a recipient treats as current are not in the view's identity
  yet.
- Whole-commit revisions make every unrelated commit UNASSESSED.
- `as_of`, periods and freshness rely on timestamps the records assert.

**Novelty** (§2.3) suffers slot churn and is blind outside its named slots.
Routing out-of-schema counterexamples to `questions(scope)` is proposed.

**Expressiveness of WRT-021.** These are not represented:

- **Power and competence:** who may open, release or accept is fixed per duty,
  with no general power record and no recovery when a holder's key is lost.
- **Prohibitions,** as distinct from observed invariants: a prohibition is
  broken by one counterexample and does not decay.
- **Children discovered after the parent opens,** and a READY_TO_CLOSE
  indication.
- **Rejection or expiry of a transfer request.**
- **A general reopening record,** with standing.
- **Bounds on policy-assigned duties,** should such policies be allowed:
  admitted issuers, quotas, or an explicit intake step.

**Computation across attested inputs.** BLOCKED_REFERENCE gives a pure kernel a
boundary for host observations, but an extended manifest is a new computation
(§3), and chaining is not specified. WRT-010's fact statuses are not yet
consumed by the typed assessment.

**Prose policies.** 23 of 24 of our own pairs are OPAQUE (§2.1).

**Model-only review.** Every adversarial review reported here was performed by
a large language model, including the automated review of this paper's draft
0.1. The reviewers caught real defects, but none of the reviewers is
cross-paradigm.

# 9. Questions for reviewers

These are the points on which we most want to be shown wrong. Questions 1 to 9
were asked in draft 0.1. The review answered several of them with gaps that
§8 now records. The questions stay open as questions.

1. **Separating claim, question and duty.** Is it sufficient to stop generated
   content from installing unbounded obligations, once standing policies are
   allowed to assign duties?
2. **The duty kinds.** Are goal, commitment, obligation and purpose the right
   cut for a record layer? The review argues that power and prohibition are
   already needed. What is the smallest addition that would represent them?
3. **Locality of typed closure.** Is the rule (no propagation of discharge,
   re-evaluation of named conditions) right? Or are there closures that must
   propagate?
4. **Recipient-relative state.** Given Chopra and Singh's local-view
   commitments, what does an evidential layer add, and what must it borrow?
5. **Novelty relative to named slots.** How should slot churn be bounded
   without reintroducing semantic judgement?
6. **Prefix verification.** Is a verified reachable prefix the right unit of
   interrupted *pure* work? How should computations chain across attested
   inputs?
7. **The weakest link.** Are a floor basis and a composite basis enough to keep
   the bases apart under convenience pressure?
8. **Capsules.** Are the four requirements of §6.1 sufficient against many
   identities?
9. **Overclaiming.** Which claim in this paper is labelled more strongly than
   its evidence supports?

# 10. Conclusion

A verified record answers what was decided and whether the reason re-runs.
Between agents, the question that keeps coming back is a different one: what
may now be relied on, by whom, for which revision, and what remains open?

The pieces we can already check are:

- a decision's binding to its policy's answer;
- a typed assessment under a recipient's profile;
- the verification of interrupted computation as a reachable prefix;
- the separation of evidence bases.

The open-loop layer that would tie them into settlement between agents is a
draft. It has been reviewed twice and amended twice, and it is honest about
the one basis it can validate. Its known gaps are listed in §8 rather than
left for the reader to find.

# Changes since draft 0.1

Draft 0.1 received one automated review of the PDF. It is kept verbatim, with
a point-by-point triage against the code, in `reviews/`.

**Text that was wrong or underspecified, now fixed:**

- the status taxonomy;
- the reject truth table;
- the `required_profile` predicate;
- the novelty order;
- the machine-state definition;
- the checks in prefix verification;
- the partial order of evidence bases;
- the residuals of the proof attestation;
- the duty-state vocabulary;
- the delegation liability;
- the `ORPHANED` rule;
- the meaning of the verify result;
- related work.

**Found by the triage itself:** the §2.3 table omitted `TYPE_MISMATCH`.

**Covered by the code but not described:**

- the state-equality check, and the stepped-over-spent case;
- upward invalidation through re-evaluation of named children;
- delegation keeping the holder liable.

**Real gaps, now listed in §8:** about a dozen, none fixed here.

# Availability

All artifacts are public.

**warrant** [@warrant2026]:

| Component | Label | Where |
|---|---|---|
| WRT-020 policy binding | IMPLEMENTED | #130, merged at `b214c6c` |
| WRT-010 fact provenance | IMPLEMENTED | #70, merged at `059ba25` |
| typed assessment (REDESIGN-1) | IMPLEMENTED | #131, head `416ea4a`; on master via `b214c6c` |
| proof attestation | IMPLEMENTED | #129, merged at `ca53e64` |
| obligation-based governance text | prose | #132, merged at `3e551e4` |
| WRT-021 open loops | DRAFT | PR #133, head `5c84580`, under review |

**sigma-glyph** [@glova2026sigma]: the sigma-resume kernel, #62, merged at
`c864d3e` (IMPLEMENTED).

**manifesto** [@manifesto2026]: the idea sources, at `a148caf`.

Every count in this paper was re-run on the named commit on 2026-10-17. This
draft has no claims checker of its own yet. That is a gap, not a choice.
