---
title: "What Remains Open: From Verified Decision Records to Settled Obligations Between Agents"
subtitle: "Working draft 0.1, written for review of the vision; not deposited"
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

1. **It reports the work that followed on those three gaps.** The work is a
   read-only profile that binds a decision to its policy's compiled answer; a
   typed, closed-vocabulary assessment of a decision under a recipient's
   profile; and a resumable computation kernel whose interrupted runs can be
   verified as reachable prefixes rather than trusted or discarded.
2. **It reports a lesson that recurred across all of it: evidence has a basis.**
   An actor's attestation, a runner's recorded run, a recipient's fresh
   execution and a deterministic replay are four different things. The most
   persistent defect we found is a check that reports one of them under the
   name of a stronger one.
3. **It proposes a direction that is still a draft.** The proposal moves from
   decisions to *open loops*. A unit of work becomes a transition with a
   residual: what it relied on, what it established, which named obligations it
   closed and by what evidence, and what it opened. Closure is typed and never
   propagates. "The present" for an actor becomes a computable frontier of what
   it holds, owes or must accept.

Every claim is labelled IMPLEMENTED (with the artifact and the commit), DRAFT
(code exists, under review or unreviewed) or VISION (no code). Section 9 lists
the questions on which we most want to be shown wrong.

# 1. Introduction

## 1.1 Where the companion paper stopped

Warrant [@warrant2026] is a record format.

- One decision is one immutable record whose identity is the SHA-256 of its
  canonical bytes.
- The policy in force is pinned by the hash of its exact text.
- The signature covers a domain-separated message.
- The stated reason can be a deterministic, budget-bounded computation that any
  reader re-executes offline.

The companion paper [@glova2026reason] describes the format, its three
implementations and its conformance apparatus. It is deliberately precise about
the proposition a verified record supports, and it leaves three links
explicitly open:

| Link | Question | State in the companion paper |
|---|---|---|
| policy → computation | does the reason compute *this* policy? | an authoring convention |
| evidence → facts | do the computation's inputs derive from the cited evidence? | an authoring convention |
| result → decision | is the decision the one the computation's answer requires? | an authoring convention |

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

The work below has very different degrees of finish, so every claim carries one
of three labels:

- **IMPLEMENTED:** code on a main branch, with tests and, where we claim a rule,
  a mutant that removes the rule and fails its own test case. The commit is
  named.
- **DRAFT:** code exists but is an unadopted profile. It is either under review
  or reviewed only by another model.
- **VISION:** no code. These are arguments and designs.

Nothing in this paper changes what `warrant verify` decides. Every new component
is a *profile*: it reads stores and reports, and enforces nothing at the
format level.

## 1.4 Contributions

1. **IMPLEMENTED.** A policy-binding profile that classifies a (record, policy)
   pair as BOUND, CONTRADICTED, UNBOUND, OPAQUE or SIGNATURES. Run on the
   repository's own stores, it classifies 23 of 24 pairs as OPAQUE: our own
   records cannot be checked against their policies (§2.1).
2. **IMPLEMENTED.** A typed assessment that reports a decision on closed axes
   under a recipient-owned profile, over one immutable snapshot of the store
   and the trust configuration (§2.3).
3. **IMPLEMENTED.** A resumable combinator kernel. Its computation identity
   excludes budget, it has no control state outside the term, its checkpoints
   accumulate credit, and its verifier proves an interrupted run to be a
   reachable PREFIX rather than an answer (§3).
4. **IMPLEMENTED, as a pattern.** Evidence bases kept separate: a proof
   attestation that is reported as CLAIMED and never as PASSED (§4).
5. **DRAFT.** WRT-021, an open-loop profile: duties, transitions with a
   residual, typed closure, consent for transfer, and a per-actor frontier.
   It has 36 test cases and 42 mutants, each killed on its own case, and was
   exercised on three transcribed specimens (§5).
6. **VISION.** Settlement between agents as a design objective, and the threats
   to it that we can already name (§6–§8).

# 2. Closing the three links, as profiles

## 2.1 Policy → computation and result → decision (WRT-020; IMPLEMENTED as a profile)

There are two gaps. Both are executable today.

**Gap 1.** Take a record that cites a prose policy `DENY_ALL`, gives a real
`ski@v1` reason that computes something unrelated, and accepts. Settlement-grade
verification with required key binding reports zero errors in all three
implementations. The policy and the computation are never connected.

**Gap 2** is sharper. Here the policy *is* machine-readable (WPL, a small policy
language that compiles to a combinator term), and the reason *is* its exact
compilation:

- the policy asks whether a refund of 65088 is within a limit of 50000;
- the compiled term replays to Church FALSE;
- the record accepts.

`warrant verify` reports `ok: true`. The format's own documentation warns that
`verdict pass` means "re-execution reproduced the pinned answer", not "the
policy said yes". Nothing connected that answer to the decision.

The profile (`impl/policy_binding.py`, merged as warrant #130 at `b214c6c`)
assigns one of five statuses to each pair:

| Status | Meaning |
|---|---|
| BOUND | the policy is WPL; a `ski@v1` reason claiming `pass` runs exactly its compilation (same term and expected answer, at least the budget needed); the decision does not contradict the answer |
| CONTRADICTED | as BOUND, but the record accepts while the policy answers false |
| UNBOUND | WPL policy, but no reason runs its compilation with its answer and enough budget |
| OPAQUE | the policy is not machine-readable, so compliance is **not checked** |
| SIGNATURES | a threshold policy that governs who signs, which settlement already enforces |

**Measured result.** Over all 24 (record, policy) pairs in the repository's
four stores, 23 are OPAQUE and 1 is SIGNATURES. There are no BOUND, no
CONTRADICTED and no UNBOUND pairs.

The repository that defines the format does not author its own records in a way
the format can check. We report this as the main finding of the section.
Making CONTRADICTED a verify-time error would break nothing we can measure,
because nothing we can measure is checkable.

The proposal's recommendation is therefore an authoring rule first: cite the
machine-readable source next to the prose. Normative enforcement waits until
the compiler identity itself is pinned against drift.

## 2.2 Evidence → facts (WRT-010; IMPLEMENTED as a profile, earlier)

Facts come in two kinds that must never be reported with the same word:

- **observed:** someone measured the world. A verifier can say only "attested
  by X".
- **derived:** a consequence of store contents, with a re-runnable derivation.
  A verifier can say derived, contradicted, underived or stale.

The profile returns `complete`, `not-applicable` or `incomplete` per record.
`incomplete` exists because a deleted provenance document and a record that
never had one would otherwise give the same answer. The profile went through
five adversarial review rounds before acceptance in its scope.

## 2.3 Typed assessment (REDESIGN-1 P3/P4; IMPLEMENTED as a draft reference, warrant #131)

The three links meet in one report. A decision is assessed under a **recipient
profile**: the admitted policy programs, the obligation, the trust
configuration, the admitted fact issuers, whether a reject is discretionary, and
the evidence slots that count as new. The report has closed axes:

| Axis | Values |
|---|---|
| record_integrity | VERIFIED, INVALID |
| policy_authority | ADMITTED, AUTHORITY_UNESTABLISHED, NOT_ASSESSED |
| fact_provenance | ACCEPTED, UNATTESTED, DERIVATION_MISMATCH, NOT_ASSESSED |
| compilation_binding | MATCHED_COMPILATION, COMPILATION_MISMATCH, UNREGISTERED_COMPILER, NOT_ASSESSED |
| computation_verification | REPLAYED_NORMAL_FORM, PAUSED, BLOCKED_REFERENCE, HOST_UNAVAILABLE, NOT_ASSESSED |
| policy_answer | TRUE, FALSE, NON_BOOLEAN, NOT_ASSESSED |
| decision_compliance | COMPLIANT, CONTRADICTED_DECISION, NOT_ASSESSED |
| required_profile | SATISFIED, REQUIRED_PROFILE_NOT_SATISFIED |

`consumer_admits_action` is true only for an `accept` that is COMPLIANT under a
SATISFIED profile. A run that did not finish is never TRUE or FALSE.

On top of the assessment, a `novelty` function distinguishes the following:

- **NEW_CONSEQUENCE:** the same scope gives a different replayed answer.
- **NEW_EVIDENCE:** an admitted issuer supplies a value for a named slot.
- **NO_NEW_CONSEQUENCE:** a budget, a wrapper, a checkpoint, a claimed verdict
  or an unnamed blob.
- **SCOPE_MISMATCH** and **MIGRATION_REQUIRED.**

This is a narrower and more checkable answer to the companion paper's negative
settlement result. Semantic novelty in general is not decided. Only novelty
*relative to a recipient's named slots* is.

**Method note.** One adversarial review of this component found a
time-of-check/time-of-use defect, and it is worth reporting as such. The
assessment called the command-line verifier on the live store, then judged
records it had read separately. A writer that swapped one complete record for
another between the two reads made the verifier approve one envelope while the
assessment judged another. The fix reads the store and the trust file exactly
once into a private snapshot, and every later step reads only the snapshot.

**Measured state** at `416ea4a`:

- `tests/assessment_test.py`: 29 PASS, 0 FAIL, 1 UNRUN. The UNRUN is named:
  cycle consequences need a runtime that `ski@v1` Boolean policies lack.
- `tests/assessment_mutants.py`: 17 mutants, all killed on their own case.

# 3. Computation that can stop (sigma-resume; IMPLEMENTED, sigma-glyph #62)

A budget-bounded check either finishes or fails. Between agents this is too
coarse: work gets cut by time limits, by action limits and by a host's
resources, and is resumed elsewhere. The question is what an interrupted run
proves. The sigma-resume kernel [@glova2026sigma], specified in
`spec/drafts/sigma-resume-draft-1.md` of sigma-glyph and merged at `c864d3e`,
answers it as follows.

**Identity without budget.** A computation is identified by
`{runtime semantics, cost model, input term hash, environment manifest}`. The
budget is not part of it, so one term under two budgets is one computation. One
term under two runtime profiles is two computations.

**No control state.** The evaluator derives the next demanded action from the
term on every call. Which action it picks does not depend on the remaining
budget; the budget only decides whether that action is affordable. This was
measured over 20,114 (state, budget) pairs. **Segmentation invariance** follows:
any split of the same total credit reaches the same state, cost and outcome
(measured over 12,649 partitions).

**Kernel outcomes and local outcomes are disjoint.**

- Kernel outcomes say something about the computation: NORMAL_FORM (no next
  action, which is not "TRUE"), PAUSED (the next action costs more than is
  available) and BLOCKED_REFERENCE (the demanded hash is outside the manifest).
- Local outcomes say something about this host: EVIDENCE_UNAVAILABLE,
  CAS_MISMATCH, INCOMPLETE, ADMISSION_REFUSED and RESOURCE_FAULT.

A local outcome never stands in for an answer.

**Verification of a prefix.** The verifier chooses the root and its context. It
replays to the checkpoint's claimed *spent* total, which strictly increases, so
exactly one state has it. It then reports either the kernel outcome at the
checkpoint's credit, or **PREFIX**: a verified reachable state with credit for
more. PREFIX is never terminal. No signature is consulted.

**Cycles.** A cycle witness is admitted only on four conditions:

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
- `tests/resume_mutants.py`: 22 mutants, all killed on their own case.
- The Python/Rust differential and its controls run in CI on every push.

**The acceptance scenario, end to end.** The scenario is
`demos/redesign-refund/run.py` in warrant, re-run for this paper. It runs
offline, in nine steps:

1. A recipient admits a refund policy, an obligation and an issuer.
2. The issuer attests the amount, 650.88.
3. Producer A starts the computation and is cut by an action limit: INCOMPLETE,
   with credit left.
4. Producer B, a separate process with only the files, verifies that checkpoint
   as REPLAYED PREFIX.
5. Producer B finishes the run to NORMAL_FORM. The answer is FALSE, which
   warrant's own `ski@v1` replay confirms.
6. A signed accept is assessed as CONTRADICTED_DECISION, and the consumer does
   not act.
7. A witness's reject is COMPLIANT.
8. Re-filing with more budget is NO_NEW_CONSEQUENCE.
9. A new attested observation in the named slot is NEW_EVIDENCE. Under a later
   one, the policy answers TRUE: that is a NEW_CONSEQUENCE, and its accept is
   admitted.

# 4. Evidence that knows its basis (IMPLEMENTED as a pattern)

## 4.1 Four bases

Over the work above, one defect shape recurred more than any other: a check
that reports a weaker kind of evidence under the name of a stronger one. We
now keep four bases apart and never upgrade one into another:

| Basis | What it establishes |
|---|---|
| actor attestation | a named actor signed a statement about addressed evidence |
| runner attestation | an addressed runner recorded a run: inputs, environment, command, limits, observed output |
| recipient re-execution | the recipient ran it again, under its own policy |
| deterministic replay | a portable term was re-reduced to its normal form |

The governance text of the warrant repository now states this rule for
agents' own work: "never upgrade one into another".

## 4.2 A proof attestation that stays CLAIMED (IMPLEMENTED, warrant #129)

Three Rust source files of the verifier are proved with Creusot:

- canonical hex;
- the range checks that make Ed25519 and P-256 encodings canonical;
- the self-delimitation of JSON string quoting.

The proof crate compiles the shipped files through `#[path]`, not copies.

Re-running the provers in CI is slow and environment-sensitive. So CI accepts a
signed **attestation** of a local run instead, and reports it as CLAIMED, never
as PASSED. The attestation's subject is a manifest of the SHA-256 of every
proof input. Inputs are deny-by-default: every file of the proof crate, every
file its sources name by path, and the Cargo and toolchain configuration of
every ancestor directory. Before signing, the attester checks that every file
rustc's dependency information says it read is in the manifest, and that every
input is tracked by git. The signing key is scoped to that directory: no other
check consults its trust file.

An adversarial review of the first version found that a build script was
outside the manifest, so a changed `build.rs` would not have invalidated the
attestation. The deny-by-default rule is the repair. A later review found that
a symlinked configuration directory escaped the manifest. Symlinks are now
refused as unsupported inputs.

## 4.3 The same defect, in our own draft

The draft of §5 shipped with exactly this defect, and an independent review
found it. A transition that *claimed* the basis REPLAYED had a prose reason and
cited an evidence hash absent from the store, yet it was assessed as
discharged with basis REPLAYED. No replay had run.

The repair separates the claimed basis from the assessed one. The profile
validates only what it can: actor attestations of resolvable evidence.
Candidates claiming any stronger basis are reported UNVERIFIED_BASIS and close
nothing.

The consequence is visible in one of our specimens. A service-recovery
obligation that admits only a runner attestation stays OPEN even after a real
probe run, because the profile cannot yet validate runner evidence. We consider
that the correct output.

# 5. Open loops (WRT-021; DRAFT)

## 5.1 Content, demand and duty

The draft separates three objects:

- **Claim:** a proposition, addressed by content. It binds nobody.
- **Question:** an epistemic demand, such as "does P hold?" or "what is missing
  for G?". It binds nobody until someone takes it on.
- **Duty:** a loop an actor has taken on, to answer a question, reach a state or
  keep a condition. It binds its holder, under persistence authority.

A model that generates a hypothesis creates a claim. A check that exposes a
missing premise creates a question. Neither assigns work. A question becomes a
duty only through an act by someone with authority over the holder: the holder
itself, or a policy the holder is under. Without this rule, every conversation
installs unbounded work on everyone in it.

The kinds of duty come from a dialogue series on obligation and intention
[@manifesto2026], restated as rules:

- **goal:** a future state granted planning relevance;
- **commitment:** a goal plus persistence authority;
- **obligation:** owed to someone;
- **purpose:** a generator of other loops that is never itself discharged.

Only obligations are implemented.

## 5.2 The transition with a residual

The central record is a **transition**. It is a recipe instance in the sense of
the manifesto's Invariant Recipe Method: prerequisites, transformation,
guarantees, losses, boundary, and a closure condition. Its fields are:

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

- **Closing a child never closes the parent it serves**, even when it is the
  only child. A parent may *name* children in its own closure condition. That
  condition is evaluated on the parent's own candidate and is never inferred
  from structure.
- **Three axes are kept apart:**
  - *disposition*: discharged, released, declared impossible, delegated,
    substituted, observed;
  - *evidence basis* (§4.1), where the claimed and the assessed basis are
    separate fields;
  - *admission*: which disposition × basis pairs a duty's own policy accepts,
    and whose acceptance is required.
- **Filing a closure submits a candidate.** It is admitted only by an
  assessment under a named view. A stored assertion is not an accepted closure.
- **Transfer needs consent from both sides.** Only the holder transfers. The
  incoming actor must accept that exact transfer, and a substitution also needs
  the creditor. A delegation is a request until the delegate accepts.

The consent rule was missing from the first implementation. The same review
that found §4.3's defect showed a duty moving to an actor that had signed
nothing.

## 5.4 The view, and the present

An assessment names its view: one snapshot of the records and blobs, the
recipient's trust snapshot, an `as_of` time, the evaluator's digest, and
completeness, which is UNATTESTED unless something attests it. Inside a view:

- OPEN means "no admitted closure in this view", never "globally open".
- An unknown reference is MISSING, never open, satisfied or orphaned.
- A root duty is never vacuously ORPHANED.
- No fresh observation of an invariant is UNOBSERVED, not "holds".
- A lapsed instance of a recurring duty is LAPSED, not "open and fine".

**The frontier.** `frontier(actor)` is the computable "present" of one actor:
the duties it holds, is delegated, is owed, may release or must accept that are
open or flagged. Two further queries complete it:

- `reliance(duty)` answers whether a current action may rely on a closure. It
  says RELIABLE only for an uncontested discharge established on a revision the
  recipient treats as current. Absence from someone's frontier is not reliance.
- `questions(scope)` is a shared, read-only view of unowned questions, with
  their provenance. Being listed there gives nobody a duty.

## 5.5 Measured state, and the dogfood

At `5c84580` (warrant PR #133, under review):

- 36 test cases;
- 42 mutants, each killed on its own case;
- settlement-grade verification of a store full of loop events reports no error
  and no re-litigation warning.

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

The intuition behind it comes from the dialogue series [@manifesto2026, note
0038]: closure is settlement into a cheaper representation, not deletion. The
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

- **Repetition earns no validation credit.** A capsule re-asserted ten times is
  one capsule.
- **Shared assumptions stay visible.** A lemma many results reuse carries its
  open assumptions into every consumer's frontier. Reuse amortizes work, not
  doubt.

## 6.2 What is already in practice

The owner of these repositories adopted a governance text on 2026-10-17
(warrant #132). Agents push, merge and release when the applicable obligations
of the exact candidate are closed:

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

In other words, the vision is already practised in prose by the agents it is
for. The draft profile is an attempt to make the same discipline checkable.

## 6.3 What is measured, and what is not

**What we do not optimize.** A global ratio of closed to open loops is a
tempting metric. It rewards trivial closures, punishes discovery, and turns
"unknown" into "done", the familiar fate of a measure that becomes a target
[@strathern1997ratings]. A check that exposes five real hidden dependencies may
have done more than twenty surface closures. The companion line of work on
checks that spawn further checks [@manifesto2026] makes the same point from the other side.

**What we propose to observe instead**, each under a fixed view:

- reopenings and their reasons;
- capsule reuse;
- the repeated-review cost: the same question asked again with no new evidence;
- newly exposed assumptions;
- concrete duties settled.

# 7. Related work

**Commitments in multi-agent systems.** Singh's ontology of commitments
[@singh1999commitments] treats a commitment as a relation between a debtor and
a creditor in a context, with operations to create, discharge, cancel, release,
delegate and assign. Our duty kinds and dispositions are close relatives. The
difference we would defend is evidential:

- each operation is a signed, content-addressed record;
- discharge is admitted only on an evidence basis that the duty's own policy
  names;
- the state is computed per recipient, under a named view, rather than held as
  a shared truth.

Deontic logic since von Wright [@vonwright1951deontic] provides the vocabulary
of obligation and permission. We do not attempt a logic. We attempt the record
layer that a logic would have to be evaluated over.

**Proof-carrying code and authentication.** Proof-carrying code
[@necula1997pcc] and proof-carrying authentication [@appel1999pca] ship a
checkable justification with the artifact. Our replay basis is in that line.
Our contribution there is narrower and more operational: keep the replay basis
distinct from the weaker bases that, in practice, carry most real evidence.

**Supply-chain attestation.** in-toto [@torresarias2019], SLSA [@slsa] and
Sigstore [@sigstore] attest *who did what to which artifact*. A runner
attestation (§4.1) is the same kind of object. What we add is the obligation
that such an attestation is meant to discharge, and the rule that discharging
it closes nothing else.

**Provenance and policy engines.** W3C PROV [@prov] records derivations but has
no notion of an open obligation. Policy engines such as OPA [@opa] and Cedar
[@cutler2024cedar] decide requests. They do not record whether a later actor
may rely on that decision for a different revision.

# 8. Threats, limits and what this does not provide

**One operator, many keys.** Every agent key in the dogfood belongs to one
operator's environment. Agents that review each other under one owner are not
independent parties, whatever their model vendors. The format can record who
signed. It cannot establish independence, and nothing here should be read as
claiming it.

**Collusion and convenience.** Two agents that both benefit from closing a
loop can each attest and each accept. Typed closure prevents a closure from
reaching *further* than its evidence. It does not prevent weak evidence from
being admitted by a weak policy. The admission policy is where accountability
actually lives, and today it is written by the same operator.

**Attestation dominates.** Only actor attestation is validated (§4.3), so in
practice almost every closure is an attestation. Until runner evidence and
replay receipts have validators, the profile's honesty consists of saying so,
not of providing stronger evidence.

**Completeness of the view.** A view is a snapshot whose completeness is
UNATTESTED. A withheld closure makes a duty look open, and a withheld
reopening makes it look closed. Historicity needs an external witness, as the
companion paper's evidence grades already note.

**Time.** `as_of`, periods and freshness rely on timestamps that the records
themselves assert.

**Prose policies.** 23 of 24 of our own pairs are OPAQUE (§2.1). A format
cannot check what is not machine-readable, and a format that claimed otherwise
would be the larger defect.

**Model-only review.** Every adversarial review reported here was performed by
a large language model. The reviewers caught real defects, which §4 lists, but
none of the reviewers is cross-paradigm.

# 9. Questions for reviewers

These are the points on which we most want to be shown wrong.

1. **Separating claim, question and duty.** Is it sufficient to stop generated
   content from installing unbounded obligations? Or is there a path, such as
   a policy that auto-assigns, through which it still happens?
2. **The four duty kinds.** Are goal, commitment, obligation and purpose the
   right cut for a *record* layer? We excluded desire, value and meaning on
   purpose. Is anything else missing that real coordination needs, such as
   permission, prohibition or power?
3. **Locality of typed closure.** Is the no-propagation rule too strict for
   practice? Are there legitimate closures that must propagate, which named
   child conditions do not express?
4. **Recipient-relative state.** Is computing a duty's state per recipient
   under a named view the right foundation? Or does coordination need a shared
   state that some party attests?
5. **Novelty relative to named slots** (§2.3). Is this an adequate replacement
   for semantic novelty in settlement? What does it miss?
6. **Prefix verification** (§3). Is a verified reachable prefix with
   accumulated credit the right unit of interrupted work between agents? What
   about non-deterministic or host-observing work, which this kernel cannot
   represent?
7. **The weakest link.** Where is it in the claim that the four evidence bases
   can be kept apart in practice, given that the cheapest one will be used
   most?
8. **Repetition credit and shared assumptions.** Do the two rules of §6.1 hold
   up against an adversary who controls many identities?
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
the one basis it can validate.

# Availability

All artifacts are public.

**warrant** [@warrant2026]:

| Component | Where |
|---|---|
| policy binding | #130, merged at `b214c6c` |
| typed assessment | #131 |
| proof attestation | #129 |
| owner's obligation-based governance text | #132, `3e551e4` |
| WRT-021 draft profile | PR #133 at `5c84580`, under review |

**sigma-glyph** [@glova2026sigma]: the sigma-resume kernel, #62, merged at
`c864d3e`.

**manifesto** [@manifesto2026]: the idea sources, at `a148caf`.

Every count in this paper was re-run on the named commit on 2026-10-17. This
draft has no claims checker of its own yet. That is a gap, not a choice.
