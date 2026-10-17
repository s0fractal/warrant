# WRT-021: Transitions with a residual: claims, questions, duties, and what closes them

**Status:** DRAFT, revision 4, 2026-10-17. Written by Claude at the owner's request. Nothing in SPEC.md or `warrant verify` changes. P1 and P2 are implemented as a profile on this branch (§13), with Codex's review of `0815959` addressed (§14).

Revision 1 (`764affa`) received an AMEND from Codex: REVIEW.md plus MANIFESTO-ADDENDUM.md, in `~/Documents/Codex/2026-10-17/wrt-021-review/`. Revision 2 (`7a11247`) answered it; §12 maps every point. D1–D5 are now engineering decisions for the experiment (§10, Codex's ENGINEERING-DECISIONS.md in the same folder), not owner choices.

## 1. Why

Warrant records the past: a decision that was taken, under a policy, for reasons, with evidence. Three kinds of thing that decisions exist for have no record of their own:

- what was **asked**;
- what someone **took on** to do;
- what the work **left open**.

These live in chat, in PR descriptions, in review files outside any repository, and in "done" columns.

The aim is portable settlement of epistemic and practical loops between heterogeneous actors (manifesto README, thesis 7). Code review between Codex and Claude is the first specimen, not the protocol's domain.

A finished piece of work should leave a compact support behind it:

- the result;
- its grounds and limits;
- what it allows to be treated as closed;
- what it opened;
- what change would require looking at it again.

A next actor (a new session, another agent, the owner) continues from that support. Re-reading the whole history is then needed only for a stated reason.

This is the working meaning of the owner's "anti-entropy reactor": spent work becomes structure that lowers the cost of the next work. It is a design objective, not a thermodynamic theorem.

Observed this month:

1. **The owner is the relay between two agents.** A Codex review round already has a warrant-like shape: a finding against an exact SHA, a reproducer, a fix, a regression and a mutant, then a re-review. But it is carried by pasted text, and nothing records which findings are still open.
2. **Closure is by assertion.** Today "fixed" closes a finding, whatever the evidence.
3. **The present cannot be queried.** `warrant why` walks backwards from a decision. Nothing answers what is open, what rests on something since replaced, or what an actor still owes.

## 2. What this rests on

| Source | What is taken | What it is used for |
|---|---|---|
| manifesto `quotes/Monday/chat-0001/0040_Monday.md` (manifesto `a148caf`) | obligation as memory with an open edge (§1–6); completion is settlement, not stopping (§10); release, abandonment and failure as closures (§11, §47–48); **persistence authority** (§13–15); orphans and parent provenance (§20–21); closure is typed, and overclaiming is unauthorized closure propagation (§30–31); an explicit closure condition (§36–38); recurring and invariant loops (§39–40); expiry and revalidation (§44–46); asymmetric completion (§50–51) | duties and their closures (§4.3, §5); no propagation (§6.1); authority (§6.3) |
| `0041_Monday.md` | goal = a future state granted planning relevance (§3); commitment = goal + persistence authority (§4); deontic is not teleological (§13–14); purpose generates obligations and is non-terminal (§16–17, §31) | the four duty kinds (§4.3); a desire or a generated claim installs no duty (§4.1) |
| `0038_Monday.md` §45–48 | causal debt; repeated reprocessing without compression; **closure is settlement into a cheaper representation**, not deletion | the result capsule (§4.5) |
| `0003_Monday.md` | grounding / claim / reachability / intent; intent proves nothing; backward and forward cones; the forward attack | intent as a `serves` relation (§4.4); queries both ways, including "what is missing" (§7) |
| `0010_Monday.md` | the present is the active surface of settlement, local to an agent | `frontier` is per actor and per view (§7) |
| `INVARIANT-RECIPES.md` | `R = (P, T, G, L, B)`: prerequisites, transformation, guarantees, losses, boundary; 0040 §38 adds `C`, a closure condition | the transition record (§4.2) is a recipe instance with its residual |
| `papers/every-check-spawns-more/paper-v0.2-draft.md` | a check generates further checkable obligations; its numbers have a bounded experimental scope | a rising count of open questions can be progress, so the metrics are in §9 |
| `drafts/embedded-claims-poc/README.md` | claim, plan, dependency, binding, occurrence, value and evaluation identities are kept separate | §4: one hash per relation kind, not one hash for everything |
| SPEC.md §2 (body), §7 (settlement) | the existing body and settlement semantics | §8, the encoding and its open §7 interaction |
| REDESIGN-1 (warrant #131, merged into the #130 branch at `c5ea176`, head `416ea4a`) | PolicyProgram as a predicate; the recipient profile; closed-vocabulary axes; an assessment over one store snapshot | closure conditions and the assessment view (§6.2) |
| WRT-016, WRT-017 | conflict scoped to the fork; an operation specified that no implementation performed | CONTESTED is scoped to the loop; nothing is specified without a vector |
| warrant `cmd@v1`; `tools/settle.py`; sigma `tools/hermes_review.py`; the runtime-hook seam | host runs recorded as transcripts, reproducer accounting | ingredients of the execution contract (§5.2), not a finished runtime |
| AGENTS.md; `history/AUTONOMY-ENVELOPE-0.1-RETIREMENT.md` | records carry only the authority they were given | §3 |

The manifesto notes are idea sources, not protocol law. Every idea taken from them is restated here as a rule with a test, and only the rule binds.

## 3. Boundaries

- **No record is verified as true or right.** A goal is "authored, open, by whom". A result capsule is "these grounds, under this view".
- **Warrant still does not take decisions** (SPEC §10). Nothing here plans, schedules or prioritizes. Producers can propose transitions; the checker validates a proposed transition and does not claim to discover all possible ones.
- **Closing grants nothing.** A DISCHARGED review duty authorizes no merge, release or publication. Those stay with each repository's governance.
- **Sigma and Warrant stay separate.** Sigma evaluates portable terms. Warrant binds host observations, attestations, authority and closure.
- **No automatic execution.** No verifier and no MCP tool runs a received script because a record names it.

## 4. Objects and relations

### 4.1. Content, demand and duty are three things

| Object | What it is | Who it binds |
|---|---|---|
| **claim** | a proposition P, addressed by content | nobody |
| **question** | an epistemic demand: does P hold? what is missing for G? | nobody, until it is taken on |
| **duty** | an actor's taken-on loop: to answer a question, reach a state, or keep a condition | its holder, under persistence authority |

A model that generates a hypothesis creates a claim. A check that exposes a missing premise creates a question. Neither puts work on anyone. A question becomes a duty only through an act by someone with authority: the holder takes it on, or a policy the holder is under assigns it (0040 §13–15, 0041 §2–4). Without this rule, every conversation installs unlimited work on everyone in it.

### 4.2. The transition: the central record

Codex's first addendum point is that a piece of work is a transition with a residual, not a single closure. A transition record (`warrant.transition@draft-2`) states:

| Field | Meaning | Recipe slot |
|---|---|---|
| `relied_on` | results, claims and evidence taken as grounds | P |
| `addresses` | the questions and duties this work was aimed at | (intent) |
| `did` | what was done: a check, a run, an argument, with its evidence basis (§5.2) | T |
| `established` | result capsules (§4.5) | G |
| `closes` | explicit mappings, each `{duty or question, closure kind, the part of the evidence that discharges it}`; many-to-many is allowed, and each mapping is checked on its own | C |
| `opened` | new questions and claims (not duties, §4.1), including exposed assumptions | |
| `not_established` | what this work does not show | L |
| `scope` | the boundary: revision, environment, profile | B |

One review can close two findings, establish one reusable lemma and expose three assumptions. All of that is one transition, not five unrelated records.

### 4.3. Duty kinds and shapes

| Kind | Source | Without discharge, who can end it |
|---|---|---|
| goal | 0041 §3 | its holder, freely (ABANDONED) |
| commitment | 0041 §4 | only its `release_by` |
| obligation (owed to someone) | 0040 §2–6 | its creditor (`owed_to`) or `release_by` |
| purpose | 0041 §16–17 | `release_by`; a purpose is never DISCHARGED, since it generates other loops |

**Order of work.** Codex recommends implementing the obligation slice first and keeping the other three as concepts. I agree.

**Desire, value and meaning stay out.** A desire has no authority. A value shapes the space and is already expressed by the policies in `under`.

**Shapes:**
- **`one_shot`.**
- **`recurring`.** It has **instances** with their own ids, such as a period index, and each instance carries its own coverage bound (review 4).
- **`invariant`.** It is evaluated at a named observation. Absence of a breach record is not evidence that the invariant holds (review 4).

### 4.4. Typed relations

`prior` in the body stays a traversal edge. The meaning of each relation lives in typed profile blobs and is never inferred from `prior` alone (review 5). The relations are:

- `serves`: intent; this advances that;
- `assumes`;
- `supersedes`;
- `accepts`;
- `closes`;
- `opens`;
- `delegates`;
- `substitutes`.

The immutable references form a DAG. Processes such as maintenance, mutual coordination or resumption can be cyclic, and are represented as successive events in that DAG (addendum 6).

### 4.5. The result capsule: closure as compression

Following 0038 §45–48, a settled result is exported as a capsule:

- the claim;
- the grounds, as addresses;
- the scope and the view it was established under (§6.2);
- the losses;
- what it may be used to close;
- the remaining assumptions;
- the **revalidation triggers**: which changes require a fresh assessment.

A new session reads capsules and the residual frontier, and fetches evidence on demand. Two rules guard against false compression:

- **Repetition earns no validation credit.** A capsule re-asserted ten times is one capsule.
- **Shared assumptions stay visible.** A lemma that many results reuse carries its open assumptions into every consumer's frontier. Reuse amortizes work, not doubt.

## 5. Closure: three separate axes

Revision 1 used one word for two things. It filed DISCHARGED with `predicate: null` as ATTESTED in §5, and called the same record OVERCLAIMED in §6.1 (review 1). Revision 2 keeps three axes apart. The names are design axes, not final wire values.

### 5.1. Disposition (what the record claims happened)

OPEN, DISCHARGED, RELEASED, ABANDONED, DECLARED_IMPOSSIBLE, DELEGATED, SUBSTITUTED.

- **FAILED is split** (review 4). A failed attempt is a transition whose `closes` is empty and which records the failure; the duty stays open. **DECLARED_IMPOSSIBLE** is a separate, authorized declaration. Impossibility is claimed as replayed only for a named bounded predicate, and never as a general reachability result.
- **DELEGATED vs SUBSTITUTED** (review 3). Under DELEGATED, A asks C to do the work and A still owes B. SUBSTITUTED replaces A by C and needs the creditor's or `release_by`'s act, so A and C alone cannot end A's obligation to B.

### 5.2. Evidence basis (how the discharge is supported)

| Basis | What it is |
|---|---|
| ATTESTED | a named actor's signed statement |
| RUNNER_ATTESTED | an addressed runner's recorded run: exact inputs, environment, argv, limits, and observed output |
| RECIPIENT_REEXECUTED | the recipient ran it again under its own profile |
| REPLAYED | a portable term (ski@v1, sigma-resume) replayed to its normal form |

**DISCHARGED is not reserved for REPLAYED** (addendum, cli section). A duty's closure condition names the bases it admits. If an obligation says "discharged by an accepted run of runner R", a RUNNER_ATTESTED record is a full discharge under that rule. The basis stays explicit, so nobody reads it as an independent replay. Conversely, a REPLAYED result is not adequate merely because it is replayed: its bindings and facts must meet the closure condition.

**Contract for host execution** (a prospective `cli@v1`; the literal tag does not exist, and `cmd@v1` is not redefined):

| Part | Content |
|---|---|
| inputs | the exact source tree and dependency material |
| environment | an addressed environment description or image, and the runner identity |
| invocation | argv, cwd, stdin and declared environment variables |
| permissions | the effects the recipient allows |
| limits | time and resource limits |
| outputs | exit status, stdout and stderr, and output artifacts |
| result | a typed result, compared to the closure condition by a declared rule |

Timeout, refusal and host failure are not a negative answer to the proposition. Side effects need their own observation or enforcement claims. A producer's run, a recipient's re-execution, and the acceptance of either are three separate events.

### 5.3. Admission (what a recipient accepts)

Filing a closure is submitting a **candidate**. Whether it closes the duty is decided by an **assessment** under a view (§6.2). A validly stored assertion is not an accepted closure (review 6).

The profile states which combinations of disposition and evidence basis it admits for which duty kinds. One example: an obligation owed to a reviewer admits DISCHARGED with RUNNER_ATTESTED only with the creditor's acceptance.

## 6. Rules

### 6.1. Typed closure, no propagation

A closure mapping closes exactly the duty or question it names, with the disposition its evidence supports. A mapping whose basis the profile does not admit for that duty is reported as **OVERCLAIMED** and closes nothing. The record is still stored; it is simply not admitted. There is no second reading of the same record.

Closing a child never closes a parent it `serves`, even an only child. The parent closes by its own condition or its own release (0040 §31).

### 6.2. The assessment view

An assessment names its view (review 2):

- the set of records and blobs;
- the recipient profile;
- the trust snapshot;
- `as_of`;
- the freshness rules;
- the evaluator build.

The redesign's snapshot assessment (`impl/assessment.py`, `416ea4a`) already does this for decisions.

Inside a view:

- **OPEN means "no admitted closure in this view".** It never means "globally open". A view that cannot establish its own completeness says INCOMPLETE_VIEW. Completeness authority, such as a store that attests to being append-complete, is a separate claim.
- **A missing reference is reported as MISSING.** Unknown never becomes OPEN, satisfied, orphaned or current.
- **A root duty with an empty `serves` is never ORPHANED.** Vacuous universal quantification is excluded by definition.
- **The flags are independent.** STALE, CONTESTED, ORPHANED, EXPIRED/LAPSED, BREACHED, INCOMPLETE_VIEW and MISSING do not depend on one another, and none overrides the disposition. Precedence is applied only when the report is rendered, never in storage.

### 6.3. Authority is bound to exact ids

- **An acceptance binds** the duty id, the candidate closure id, the evidence ids and the view or policy where the profile requires it. B accepting C1 does not accept C2 (review 3).
- **Opening a duty for a holder** needs the holder's act or a policy the holder is under. Nobody creates an obligation for someone else unilaterally (0040 §15).
- **Substitution** needs the creditor or `release_by` (§5.1).

### 6.4. Replacement is not invalidation

Three judgments are kept apart (review 5):

1. **Valid at its view.** The original assessment stays as it was: history is not rewritten. Revision 1's #131 AMEND remains an AMEND.
2. **Eligible for reliance now.** This is the recipient's freshness policy. A validly signed but stale report does not admit present action.
3. **Applicable to a new revision.** It is UNASSESSED until the profile's revalidation rule produces a result.

Replacing a policy or adding an observation sets these flags. It does not delete or overturn earlier results. `assumes` names the kind of each reference, so that the revalidation trigger is precise.

## 7. Queries

- **`frontier(actor, view)`, the present (0010).** It returns the actor's duties that are open or flagged, the candidate closures waiting for the actor's acceptance, and the questions in scope of the actor's duties. Unowned questions do not appear in anyone's frontier until someone takes them on. This is what keeps generation free without causing eutrophication (`0020_Monday.md`).
- **`grounds(id)`** returns the backward cone. **`supports(id)`** returns the forward cone: what this result may legitimately be used for, and what currently relies on it.
- **`stale(view)`** returns everything flagged in §6.2 and §6.4, each with its chain of causes.
- **`gaps(grounds, target)`** is the constructive direction (0003; Invariant Recipes). Given established capsules and a target duty, it returns the closure-condition inputs not yet established. Proposing the transitions that fill them is producer work; the checker then validates what is proposed.

## 8. Encoding: a profile first

**Stage 1: a profile over the existing body.** No SPEC change. Transitions, duties, acceptances and capsules are closed-schema blobs. A signed body places them in `subject` or `evidence`, and its `prior` gives the traversal. The profile checker (`impl/loops.py`) computes §5.3, §6 and §7 under a view, in the same way that `impl/assessment.py` does.

**Before any MCP tool:** canonical event schemas, their identities, their signatures and their conflict and supersession behaviour, with vectors (review 6). Tool names come after.

**SPEC §7 must be tested, not assumed.** An `accept` of a question blob is a settlement under §7. Whether a candidate closure filed as `accept` interacts correctly with tunnels and re-litigation novelty needs a vector that runs `settle`. "The body schema is unchanged" does not establish settlement compatibility (review 6). If it does not fit, stage 1 uses `propose` for every candidate and keeps settlement for admitted assessments only. Which of the two applies is an open question for P1.

**Stage 2 (only if P2 shows the need):** a body version with first-class transitions, in Python, Go and Rust with vectors (WRT-017's lesson).

## 9. What is measured, and what is not

**A global closed-to-open ratio is not a target.** It rewards trivial closures, punishes discovery, and turns unknown into done. A check that exposes five real hidden dependencies may have done more than twenty surface closures.

Measured instead, each under a fixed view:

- reopenings and their reasons;
- capsule reuse;
- repeated review cost, meaning the same question asked again with no new evidence (0038 §47);
- newly exposed assumptions;
- concrete duties settled.

The every-check paper's offspring counts are motivation, within their stated limits. They are not a law.

## 10. Engineering decisions for the experiment (D1–D5)

The owner asked whether the agents can decide these themselves. Codex recorded the following as reversible engineering defaults (ENGINEERING-DECISIONS.md, 2026-10-17), and they match this draft's recommendations. They are not an owner signature, a roster adoption, or authority to push, merge or release. Scope, obligations actually imposed on someone, the owner's purpose and external publication remain separate decisions when they arise.

| # | Decision | Reconsider when |
|---|---|---|
| D1 | a profile first; the core may change if the experiment shows it is needed; backward compatibility is not a constraint here | a P2 case cannot be expressed without a body change |
| D2 | four conceptual kinds; the obligation slice implemented first; desire, value and meaning are not implemented | a real case needs a goal or a commitment closed |
| D3 | an explicit per-duty acceptance policy; no implicit beneficiary consent | the policy turns out to be the same for every duty |
| D4 | in-tree, addressed, append-only records; exact subjects; corrections are new events | in-tree storage causes an operational problem (then consider Git refs) |
| D5 | the Codex–Claude review round, service recovery and two maintenance periods | |

## 11. Plan

| Stage | Content | It fails if |
|---|---|---|
| P0 | this revision; Codex re-review | a point in §12 is not actually answered |
| P1 | event schemas + `impl/loops.py` + vectors for every row of §5 and §6; one on-target mutant per rule; the SPEC §7 settlement vector (§8) | a mutant survives, or a real case needs a field the schemas lack |
| P2a | #131 finding N1 as separate immutable events (Codex's timeline, verified against git): the finding at `cda525e`; the amendment at `e2f679c`; reproduction at `e2f679c` and final at `416ea4a`; a reviewer-attested completion for exactly that scope; and, separately, human authorization, CI and the merge of #131 at `c5ea176`. That merge is **into the #130 branch, not master**. Closing N1 must not close the review, any merge authority, #130 or master integration. | the frontier after transcription disagrees with what the owner knows is open, or closing N1 closes anything else |
| P2b | a non-review specimen: a service-recovery obligation whose closure condition is "service functional" (0040 §36), not "an engineer clicked done" | it can only be expressed by prose |
| P2c | a recurring maintenance duty with two instances, one covered and one lapsed | a lapsed instance reads as open-and-fine |
| P3 | MCP: exchange transitions, evidence, assessments and the residual frontier, with names fitted to the P1 contracts; no automatic execution | a tool admits a closure that the checker reports as OVERCLAIMED |
| P4 | D1 revisited with P2's evidence | |

**Starting point for review findings.** Their tests run host programs. ski@v1 neither supplies these host observations nor models Python, Rust or OS execution, and evaluating a signed transcript is not reproducing it. P2a therefore uses reviewer attestations bound to the transcript, the exact heads and the scope (ATTESTED or RUNNER_ATTESTED). It does not pretend to REPLAYED.

## 12. Disposition of the revision-1 review

| Codex point | Answer in revision 2 |
|---|---|
| R1 ATTESTED vs OVERCLAIMED on one record | three axes (§5); OVERCLAIMED = basis not admitted, no reinterpretation (§6.1) |
| R2 view and time; unknown ≠ open; vacuous orphan | the view (§6.2); INCOMPLETE_VIEW, MISSING; root never orphaned; flags orthogonal |
| R3 acceptance binding; transfer bypassing release | ids bound (§6.3); DELEGATED vs SUBSTITUTED (§5.1) |
| R4 failure ≠ impossibility; recurrence instances; invariants by absence | FAILED split; instances; observation-bound invariants (§4.3, §5.1) |
| R5 supersession ≠ invalidation; typed relations, not `prior` | three judgments (§6.4); typed relations (§4.4) |
| R6 events before MCP; §7 compatibility; candidate ≠ accepted | §8, §5.3; P1 settlement vector |
| A1 transition with residual | §4.2 |
| A2 claim ≠ question ≠ duty | §4.1 |
| A3 closure as compression, no repetition credit | §4.5 |
| A4 both directions, `gaps` | §7 |
| A5 do not optimize the closed-to-open ratio | §9 |
| A6 DAG of references ≠ acyclic process | §4.4 |
| cli: DISCHARGED not SKI-only; execution contract; no auto-execution | §5.2, §3 |
| N1 experiment | P2a, with one correction: `c5ea176` merges #131 into the #130 branch, not master |

**Where I add to the review rather than follow it.** Unowned questions stay out of every frontier (§7). Without that, rule A2 alone still lets generated questions flood a shared view, even though they bind nobody.

## 13. P1 and P2 results (revision 3)

**P1, the obligation slice, as a profile.**

| Part | What it does |
|---|---|
| `impl/loops.py` | closed schemas for `warrant.duty@draft-2`, `warrant.transition@draft-2` and `warrant.acceptance@draft-2`; `assess(store, trust, as_of, current)` over one snapshot of the store and the trust file, with settlement-grade `verify --require-bound` deciding which records are in the view; `frontier(report, actor)` |
| `tests/loops_test.py` | 28 cases, L01–L28; each case names the rule it checks |
| `tests/loops_mutants.py` | 31 mutants, each undoing one rule; each must fail its own case: 31/31 killed on target |
| `demos/wrt-021-dogfood/run.py` | P2a, P2b, P2c, 12 checks |

All three are wired into `tools/check.py`.

Two rules have no mutant, and the harness says why:
- **L09, a failed attempt closes nothing.** No code could close it, so the rule is an absence.
- **L24, settlement compatibility.** It is a property of the encoding: every acceptance has its own subject, so no two `accept` records share one. L24 runs the real verifier on a loop store at settlement grade and finds no error and no re-litigation warning. That answers the open §7 question of §8 for this encoding.

**P2, the transcription.** Every actor signs with a fixture key named `*@transcribed`. No record is Codex's, Claude's or the owner's own signature. The git SHAs are the real ones.

- **P2a, #131 N1.** Codex's AMEND opens a question, not a duty. Claude takes it on. Claude's run at `e2f679c` is a candidate, and Codex's acceptance binds that exact candidate. At `as_of` with `current = {416ea4a, c5ea176}`:
  - N1 is DISCHARGED, and its applicability is UNASSESSED because its scope is `cda525e`;
  - the review round stays OPEN;
  - integrating #131 is a separate duty, DISCHARGED at `c5ea176`;
  - "#130 into master" stays OPEN;
  - the AMEND record is kept;
  - the question Claude's run exposed binds nobody.
- **P2b, service recovery.** "Ticket set to Done" (ATTESTED) is OVERCLAIMED, and the probe run (RUNNER_ATTESTED) discharges the restore. The invariant "service functional" is UNOBSERVED once the probe is older than its freshness. It is not "fine".
- **P2c, maintenance.** Period 0 is covered, period 1 lapsed, period 2 open.

**What the transcription found.** These are the findings P2 exists to produce.

| # | Finding | State |
|---|---|---|
| F1 | A closed duty's earlier overclaim kept it in the frontier forever, so the restore duty never left ops' list. | Fixed: OVERCLAIMED_CANDIDATE on a closed duty stays in the report, not the frontier. L28, plus a mutant. |
| F2 | A DISCHARGED duty whose scope is not current (N1 at `cda525e`) leaves the frontier. Whether it should come back as "revalidate" depends on the recipient's freshness policy, which the profile does not express yet. | Open. Needs a profile field (§6.4, judgment 2). |
| F3 | An unowned question (the genesis.json one) is correctly in nobody's frontier, but then nobody sees it unless they read `unowned_questions`. A shared, read-only view per scope is needed, without making it anyone's duty (addendum A2). | Open. |
| F4 | Codex's re-execution is a transition of its own, but the acceptance that follows cannot cite it: the acceptance blob binds Claude's evidence and has no field for the acceptor's support. The link exists only through `prior`. | Open. A candidate is an optional `support` list in the acceptance. |
| F5 | "Answer the re-review" closes only by its own closure, as §6.1 requires. Nothing records which child duties its closure condition covers, so an acceptor has to know. | Open. A closure condition that names child duties, checked and not propagated, is the candidate. |

**Not done.**
- The real in-repo store, with each agent signing its own events with its own key. The transcription shows that the format can express the round. Real use needs Codex's key, generated and held by Codex.
- MCP tools (P3).
- Any change to `warrant verify`.

## 14. Review of `0815959` (Codex, AMEND): WL01, WL02 and F2–F5

The review is in `~/Documents/Codex/2026-10-17/wrt-021-review-0815959/`, with `repro.py` and `RESULTS.json`. Both P1 findings reproduced on the reviewed head before the fix. On the fixed head, `repro.py` now stops at its first assertion, the WL01 one. Its WL02 half, run on its own, shows the holder unchanged.

| Finding | What was wrong | Fix | Regression | Mutants |
|---|---|---|---|---|
| WL01 (P1) | A claimed basis became the assessed one. `REPLAYED` with a prose reason and a missing evidence hash came out as DISCHARGED / REPLAYED, though no replay ran. | The claimed basis and the assessed basis are separate fields. `VALIDATED_BASES = {ATTESTED}` lists the bases this profile can validate; a candidate claiming any other basis is UNVERIFIED_BASIS and closes nothing. Mapping evidence must resolve to exact bytes, and an attestation must name its evidence. The assessed basis now says what was validated: `ACTOR_ATTESTATION:<actor>` or `RELEASE_BY:<actor>`. | L29, L30 | 4 |
| WL02 (P1) | A substitution with the creditor's acceptance gave the duty to `absent@unconsented`, an actor that had signed nothing. | Only the holder transfers. The incoming actor must accept the exact duty, transition, mapping and evidence, and a substitution also needs the creditor or `release_by`. A delegation is a request until the delegate accepts it. Assignment under a pre-existing mandate is not implemented: there is no mandate record yet. | L13 (full consent path), L31, L32 | 4 |
| F2 | Applicability followed the revision where the defect was found. | Applicability now follows the revision the closure was established on (`closure_scope`). `reliance()` returns RELIABLE only for an uncontested DISCHARGED whose closure scope is current. Absence from a frontier is not reliance. | L22, L34 | 3 |
| F3 | Unowned questions were invisible. | `questions(rep, scope)` is a shared, read-only view. Each entry carries the transition that opened it, the actor and the scope. Being listed there gives nobody a duty. | L35 | 1 |
| F4 | The acceptance could not cite the acceptor's own work. | Acceptances take an optional `support`, which must resolve or the acceptance is refused. It is reported per acceptor and never raises a basis: a producer's transcript is not a recipient's execution. | L33 | 1 |
| F5 | A parent's condition over its children was implicit. | Duties take an optional `closure_requires`. A parent's own DISCHARGED candidate is UNMET_CONDITION until every named child is DISCHARGED. The condition is evaluated, never inferred from `serves`. Children are assessed first; a cycle stays unmet. | L36 | 1 |

**Effect on the dogfood.** It is now 13 checks.

- **P2b.** The probe run claims a runner attestation, which this profile cannot validate, so the restore stays OPEN. That is the true state of the profile, and it is reported as such.
- **P2a.** It is labelled a frozen slice ending before `b214c6c`, the merge of #130 into master. Codex's re-execution is now the support of its acceptance.

**Totals:** 36 cases, 42 mutants, each killed on its own case.

**Still not implemented, on purpose:**
- validation of runner, re-execution or replay evidence (`cli@v1` and a replay receipt);
- assignment mandates;
- goal, commitment and purpose.

## 15. Follow-up of #133 at 5c845805 (Codex, 2026-10-18)

WL01 and WL02 are closed on this head: unvalidated bases do not discharge a
duty, evidence must resolve, and transfer requires the incoming actor's exact
acceptance. The follow-up found WL03 (P2), a profile validation boundary defect.

A correctly signed, settlement-grade core-valid event whose duty JSON contains
`kind: []`, `shape: {}` or an array-valued admits entry makes `assess()` raise
TypeError at set membership. One malformed profile event therefore suppresses
the entire report, including unrelated valid duties. An unknown string in the
same slot is correctly refused, and removing the malformed event restores the
report. The witness was observed on 5c8458056619402533fd58a6ef6405635beb26f4.
A malformed transition scope subject can similarly reach an unhashable value
in closure aggregation or be incorrectly reported as an applicability scope.

The fix checks JSON string types before enum membership and validates the
optional transition subject as an exact address. L37 exercises arrays, objects,
null, Boolean, integer and unknown-string values across six enum positions;
L38 checks malformed scope subjects. Both assert per-event refusal and
continued assessment of an unrelated valid duty. The new regressions fail on
the reviewed head. Two targeted mutants remove these guards and must fail their
respective cases; the suite now has L01–L38 and 44 mutants. No SPEC or core
verifier behavior changes. This correction is a Codex-authored fix following
the independent review of Claude's candidate, not a claim of independent
review of Codex's own patch.
