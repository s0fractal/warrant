# WRT-022: Authority, revalidation triggers and crossings — what WRT-021 left open, rethought

**Status:** DRAFT proposal, revision 2, 2026-10-18. Written by Claude at the owner's request. Nothing is implemented, and nothing in SPEC.md or `warrant verify` changes.

**Revision history.** Revision 1 (`6fa8cb8`) received an AMEND from Codex. The review is in `~/Documents/Codex/2026-10-18/wrt-022-review-6fa8cb8/REVIEW.md` and lists R22-01 to R22-07. The verdict was to accept the direction, receipt integration with view-local validation, explicit translations with their losses, and an incremental real dogfood; and to amend the authority and reliance contracts before implementing them. §8 maps each point to its answer here.

This revision is agreed locally first. It goes to GitHub together with its first implemented slice, not on its own.

It starts from the current surface:
- master `8855f7b`: WRT-021 is merged with Codex's WL03 fix, L01–L38 and 44 mutants (re-run for this proposal);
- the paper *What Remains Open*, draft 0.3, at `a391c91` on this branch.

It does **not** carry out WRT-021's "not done" list as written there. §3 restates each item.

## 1. Where this comes from

| Source | What it is | What is taken |
|---|---|---|
| **DeepReview of the paper draft 0.1**, `papers/what-remains-open/reviews/2026-10-17-deepreview-draft-0.1.md`, with `TRIAGE-2026-10-17-draft-0.1.md` beside it | an automated review of the PDF alone; the triage checked each point against the code | the GAP rows of the triage, now §8 of the paper (draft 0.3, `a391c91`): power and competence; prohibitions; late children; transfer rejection and expiry; reopening with standing; revision missing from the view; split views; downgrade pressure on evidence; novelty slot churn; chaining across attested inputs; capsule rules |
| **The meta-ontology**: manifesto `artifacts/ONTOLOGY-FORMALIZATION-0.1.md`, manifesto #17 at `dd0a74b` | a typed working compilation of the manifesto corpus; not reviewed, adopts nothing | the question operator 𝒬(T) = (Preserved, Scope, **Authority**, Evidence, Lost, **Falsifier**) (§1.2); the transfer law with zero automatic credit (§1.3); constraint and invariant as different sorts (§2, §3.4); the translation report, with "untranslatable" as a first-class result (§3.6); a proof burden that scales with ΔReach × irreversibility, and the legitimacy tuple (§7.3.4); the present as local, with consensus as sync of a shared irreversible past (§7.1.2); lineage through a meta-invariant (§7.1.3); its epistemic types (§0), *adapted* rather than transferred (§4.7) |
| **WRT-021**, merged | the obligation slice | its own lists of what it does not do (§7, §13, §14) |

**What is not taken, and why:**
- the `Conf ∈ [0,1]` field of the translation report. The ontology's own §3.5 forbids approximating discrete transitions with scalars;
- VORTEX;
- semantic mass.

**What the ontology itself warns against.** It treats authority and competence as different things, and so does this revision (R22-01). It describes the ecosystem as a braid of trajectories, not a stack. Warrant's place in that braid is the protocol of **crossings and closures**. It does not become the ontology.

## 2. The organising idea: transitions answer 𝒬, approximately

WRT-021's transition fields correspond to four components of 𝒬, though not exactly (R22-07):

| 𝒬 component | Nearest WRT-021 field | How close |
|---|---|---|
| Preserved | `established` | not identical: `established` lists new postconditions, while Preserved means what survives the transformation |
| Scope | `scope.subject` | an exact whole-commit SHA; every unrelated commit makes a closure UNASSESSED |
| **Authority** | implicit: per-duty lists and the holder rule | no record of authority, and no attenuation |
| Evidence | claimed basis plus assessed basis | only `ATTESTED` is validated |
| Lost | `not_established` | not identical: "not shown" is not "lost by the transformation" |
| **Falsifier** | none | nothing names what should trigger revalidation |

WRT-022 adds the two missing components:
- **Authority**, as attenuating grants (§4.1);
- **revalidation triggers** (§4.2). The name changed from "falsifier" in revision 1: a trigger is a declared, cheap reason to look again, not a test that could prove a closure correct.

## 3. WRT-021's open items, rethought

| WRT-021 said "not done" | Rethought as |
|---|---|
| assignment mandates | **attenuating grants** (§4.1). An assignment is valid only if the holder's own delegation, or the assignment policy that governs the holder, authorizes it. |
| goal, commitment, purpose | **Purpose stays a persistent orientation**, not a power. A standing grant can *implement one operational consequence* of a purpose, namely authority for specified self-directed work, without being its definition (R22-01). **Commitment** is an obligation whose creditor is the holder's own later self. **Goal** is unchanged. Implementing goal and commitment remains deferred. |
| validation of runner, re-execution and replay evidence | **Replay goes through a crossing** (§4.5): the recipient re-verifies the source computation, so REPLAYED is view-local and validated. **Runner** evidence is an actor attestation. A `runner` grant names who is *authorized* to attest a run; it never shows that a run occurred or was faithful. **Re-execution** is never a stored basis. |
| `closure_requires` fixed at opening | **Enrolment.** A child affects a parent's condition only if it is admitted into it by an authorized act under the parent's policy. A `serves` edge is declared intent and has no effect on the parent (R22-03). |
| applicability by a set of current revisions (F2) | **Scoped subjects plus tri-state triggers** (§4.2). The subject is a manifest of the relevant dependency slice, including compiler, toolchain and configuration inputs, not merely the files the last patch touched. |
| result capsules (VISION) | **An established claim with its axes (§4.7) and triggers**, imported elsewhere only by a crossing. |
| MCP tools | Canonical events first. Tools later; none executes received scripts. |
| a real store with each agent's own key | **Slice S1** (§6): the *current* review, recorded with keys enrolled under an explicit recipient policy. Nothing is backdated. One operator still means one custody. |

## 4. Proposed objects and rules

Every object is a closed-schema blob carried by an ordinary signed record: a profile over the existing body, with no SPEC change.

### 4.1 Grants: authorization, attenuated (R22-01)

**A grant is an authorization, not a competence record and not a duty.**
- Authority says which acts are admissible.
- A duty says what performance is owed.
- Competence, the ability to do something faithfully, needs observed evidence of its own. A grant never supplies it.

`warrant.grant@draft-2` has these fields:

- `grantor` and `grantee`;
- `acts`, a closed set: `open_for`, `release`, `accept`, `substitute`, `reassign`, `contest`, `adjudicate`, `enrol`, `runner`, `migrate_profile`, and `delegate:<act>`;
- `scope`: duty kinds, subject selectors, named parents and beneficiaries;
- `limits`: expiry, quota, and required evidence;
- `parent_grant`: the grant this one attenuates, or none for a root grant.

**Rules:**

1. **Roots are explicit.** A root grant is valid only if the recipient's profile *accepts it as a root*. That acceptance is an act recorded in the profile lineage (§4.6). A key that the trust snapshot binds to an actor authenticates that actor's records. It authorizes nothing.
2. **Every edge attenuates.** A child grant is valid only if three things hold:
   - its grantor held the acts it grants, together with `delegate:<act>` for each;
   - its acts, scope, beneficiaries and expiry are each a subset of the parent's, and its limits are at most the parent's;
   - the parent was valid at the child's admission position.

   If A holds `release` over duty D, A cannot give B `open_for` or `migrate_profile`, because A never held them.
3. **Position and conflict.** Validity, expiry and revocation are evaluated at an explicit position in the view, given by admission order through `prior` and not by self-asserted timestamps. Two conflicting grants at one position are reported as CONFLICTING_GRANTS and neither is used.
4. **`open_for` binds only through an existing authorization.** A holder acquires a duty from a grant only if its own delegation, or the assignment policy governing it, authorized that kind of assignment. Otherwise the act becomes an **intake question**: visible in `questions(scope)` and binding nobody.
5. **Quotas are view-local.** Two concurrent views with one slot left can both admit, so no global bound is claimed. A global bound would need a reservation or ordering mechanism, which is open.
6. **`reassign` keeps WL02's split.** Releasing the old holder needs the creditor or `release_by`, or a grant for that. Binding the new holder still needs the new holder's acceptance of the exact mapping. No grant ever binds a third party without its consent.

### 4.2 Revalidation triggers and reliance (R22-02, R22-03)

A closure mapping, or a capsule, may declare triggers from a closed, versioned vocabulary. Each trigger evaluates to one of three values: **FIRED**, **NOT_FIRED** or **UNEVALUABLE(reason)**.

| Trigger | FIRED when | Effect when fired |
|---|---|---|
| `subject_changed(selector, manifest_hash)` | the recipient's current manifest for the selector, a dependency slice that includes compiler, toolchain and configuration inputs, differs | revalidate for future use |
| `slot_changed(slot, occurrence)` | an accepted occurrence in that slot carries a different semantic value (§4.3) | revalidate |
| `duty_not_discharged(id)` | that duty is not DISCHARGED in the view | revalidate |
| `child_enrolled_after(parent, candidate)` | a child was *enrolled* (§3), after `candidate` in admission order | revalidate |
| `record_superseded(id)` | an admitted `supersede` of `id` exists | revalidate **for future use only**; historical validity is untouched |
| `key_retired(actor, key)` | key state retires it | as above, for future use only |
| `predicate_false(check)` | a cited check replays to FALSE | revalidate |

**Three judgments are kept apart:**

1. **Historical validity.** The closure was admitted at its view. Nothing later erases this.
2. **Present eligibility.** `reliance(duty, use)` is eligibility *for a named use under the recipient's policy*. Its inputs are all of the following:
   - a validated closure;
   - the scope and its binding;
   - freshness;
   - an evidence basis admitted *for that use*;
   - the view's completeness assumptions;
   - the trigger results.

   No fired trigger is one input. It is never proof of correctness or of the absence of unknown defeaters.
3. **Coverage.** How many triggers there are, and how many are UNEVALUABLE. An empty set is reported as **NO_DECLARED_TRIGGERS**: neutral, never "unfalsifiable".

**Reliance values:**
- **ELIGIBLE(use)**;
- **STALE(cause)**: a trigger fired;
- **UNASSESSED(cause)**: some input is UNEVALUABLE, or the view's completeness does not meet the use's requirement. Unknown never reads as fine;
- **NOT_CLOSED**;
- **CONTESTED**.

### 4.3 Novelty and challenge are separate routes (R22-03)

Three things that revision 1 conflated:

- **Automatic revalidation.** Cheap and mechanical: a declared trigger fires, and the effect in its table applies.
- **Challenge.** A new counterexample does not need to fire any declared trigger. If the closure's author omitted an assumption (atomicity, for example), a witness that shows the failure on unchanged inputs is still relevant. Any actor may file it.
  - **Admissibility** of its *binding* effect is decided by the closure tunnel's novelty test (SPEC §7: new evidence or a new outcome fingerprint) *and* by the filer's standing (§4.4).
  - **Without standing**, the counterexample is still recorded and is visible in `questions(scope)` with its provenance. Standing controls the binding dispute effect. It does not make an independently checked counterexample false.
- **Slot occurrence versus slot value.** Identical semantic values are deduplicated as *consequences*. Each occurrence is kept with its observation interval and provenance. For a slot declared `state` (a time-varying observation), a return to an earlier value is a new occurrence, and it may matter to present obligations. For a slot declared `fact`, it is not new. A fresh timestamp alone never manufactures a new semantic result.

### 4.4 Contest and adjudication (needs §4.1)

- **Standing.** A contest has binding effect (CONTESTED) only if two things hold:
  - the filer has standing: the creditor, a required acceptor, or the holder of a valid `contest` grant for that scope;
  - it passes the novelty test.

  Otherwise it is recorded as an intake question (§4.3).
- **Resolution.** An adjudication by the holder of a valid `adjudicate` grant resolves a contest as UPHELD, OVERTURNED or REPAIRED. A REPAIRED resolution carries the repair transition. The original closure is never edited.
- **Ordering.** Contest depends on grants, so in the plan it comes after grants (§6). This corrects revision 1's ordering.

### 4.5 Crossing (zero automatic credit)

`warrant.crossing@draft-2` carries:

- the source artifact at an exact revision and trajectory;
- the target profile;
- the mapping;
- a translation report: preserved, lost, introduced, approximated and unknown, with no confidence scalar;
- the transferred evidence;
- the new status (§4.7);
- the new triggers.

An incomplete report gives **BORROWED**: the crossing is visible, and it carries no credit. **UNTRANSLATABLE**, with the conflicting invariants named, is a valid outcome.

**Replay receipt.**
- **The default.** A recipient claiming REPLAYED re-verifies the source computation itself, with `sigma_resume.verify` against a root it chooses, or with `ski@v1` replay.
- **Cache reuse.** The recipient may reuse its own verified cache, keyed by exact computation, environment and verifier identity.
- **Any other shortcut** must name an accepted attestation or a verifiable certificate, and its cost. A signature or a CAS address never amortises work across peers (paper §3).

**Chaining.** Paper §3 notes that an extended manifest starts a new computation. A crossing records that the new computation's input is a verified PREFIX of the old one plus an attested fact. A chain is then a sequence of crossings, each with its own triggers.

### 4.6 Admission per act, and profile lineage (R22-04)

**Requirements follow the act, its consequence and the trust model, not a universal ladder.**

A signed release by an authorized creditor, or an owner's adoption, *is* the act. Replay cannot replace it, and attestation is exactly the right basis for it. Revision 1's ban on `ATTESTED` for irreversible duties is withdrawn.

**Tiers** (`reversible`, `costly`, `irreversible`) are recipient-controlled defaults per kind of act:
- they are assigned by the recipient's profile from the act and the duty kind, never by the producer;
- a producer cannot evade a requirement by labelling its own act reversible.

**Bases stay per input.** Each input keeps its basis, domain, provenance and assumptions. The evidence bases form a partial order, so there is no universal "weakest". A policy may derive a conservative summary only where a meet is defined for those inputs. Observed, normative and formal inputs are never flattened into one minimum.

**Profile lineage.** A profile changes only by a `migrate_profile` transition. The transition records three things:
- who held the grant to make it;
- which requirements it weakens;
- a loss report of the closures that become UNASSESSED.

Two rules bind every migration:
- **Meta-constraints survive.** The profile names the constraints that no migration may weaken.
- **Consumers opt in.** A consumer opts into a successor lineage explicitly. Leaving a bad or lost lineage is done through an explicit *new root*, never by calling a locally valid new profile a continuation.

A signed migration gives provenance, not preservation of safety properties. What it buys is that a downgrade is visible, attributable and opt-in.

### 4.7 Claims: three axes, not one enum (R22-07)

A claim carries three separate axes:

- **Evidence status:** `candidate`, `measured(domain)` or `proved(system)`.
- **Semantic force:** `descriptive`, `stipulated` or `normative`.
- **Lifecycle:** `active`, `withdrawn` or `superseded`.

A *debt* is not a claim type. It is an unresolved edge: a question or an open duty.

Each axis changes only through a transition whose admitted evidence supports that axis's change. A measured claim that is later withdrawn keeps what was measured. An adopted rule stays normative while its lifecycle changes. Any other change is an **illegal cast**.

This is an adaptation of the ontology's six classes, not a one-to-one transfer:
- what is gained: the axes no longer overwrite one another;
- what is lost: the ontology's single-label readability, and its `IDENTITY-RULE` class. That class is folded into `stipulated`, and the folding may be too coarse.

### 4.8 Prohibitions: in force versus complied with (R22-05)

A duty of shape `constraint` has two independent axes:

- **Binding state:** `ACTIVE`, `LAPSED`, `RELEASED` or `REVOKED`.
- **Observed compliance**, over a stated interval and coverage:
  - `UNKNOWN`: no observation. This is the default. It never makes the norm lapse, and it never means compliance;
  - `OBSERVED_COMPLIANT`, over the observed interval only;
  - `KNOWN_VIOLATION`, from an admitted counterexample. The norm stays ACTIVE.

A prohibition on disclosure with no leak record is `ACTIVE` and `UNKNOWN`. After a recorded leak it is `ACTIVE` and `KNOWN_VIOLATION`.

### 4.9 Joint checkpoints (R22-06)

Before an act that needs several parties and is irreversible by the recipient's tier map, the required signers co-sign a **pre-action manifest**. It contains:

- the addressed input records and blobs of the *shared relevant subgraph*;
- the trust, profile-lineage and evaluator commitments;
- the exact target action and its terms;
- the required signers.

It excludes the checkpoint itself and the resulting act, so it is not self-referential. Each party's full local view keeps its own identity separately. An unrelated record at one party does not make the checkpoint diverge.

A co-signature binds those exact bytes. It does not attest global completeness or unique consensus. Two conflicting checkpoints for the same act are a fork, and they need an ordering or conflict rule, which is **open**.

A signer is counted only after every acceptance requirement of that signer is met.

## 5. What this does not do

- Nothing here is normative: everything is a profile.
- It proves no key isolation, competence, independence or honesty.
- Semantic novelty is not decided: triggers are declared, and challenges are filed.
- No global quota or global consensus.
- Goals, commitments, VORTEX, semantic mass and numeric confidence are not implemented.
- No second registry: grants, triggers, crossings and claim axes are blobs in the same store, under the same verify.

## 6. Plan: slices, by actual dependency

Each slice goes in its own PR, together with the part of this proposal it implements. There is no single large PR.

| Slice | Content | Depends on | It fails if |
|---|---|---|---|
| **S1** | **The current real review, recorded:** Claude and Codex enrol their public keys under an explicit recipient policy. Until a real authority act is recorded, the prose policy documents are an honest prose root. **Scoped subjects and tri-state triggers:** `subject_changed` over dependency-slice manifests, plus `duty_not_discharged`. The assessment identity includes the selector, the current manifest and the profile. NO_DECLARED_TRIGGERS is neutral. Existing reliance checks are kept. | WRT-021 | an unrelated change makes a closure STALE; a relevant change does not; a missing current revision, or a withheld dependency, reads as ELIGIBLE |
| S2 | crossing and replay receipt (§4.5) | S1 | a receipt the recipient did not re-verify is assessed REPLAYED |
| S3 | minimal grants for the next consumer: explicit roots and attenuation (§4.1) | S1 | a child grant exceeds its parent, or a key binding alone authorizes an act |
| S4 | contest and adjudication (§4.4); enrolment and `child_enrolled_after` (§3, §4.2) | S3 | a party without standing makes a duty CONTESTED, or a `serves` edge alone affects a parent |
| S5 | per-act admission and per-input bases; profile lineage (§4.6) | S3 | a producer's own tier label lowers a requirement, or a migration weakens a declared meta-constraint |
| S6 | constraint axes (§4.8); claim axes (§4.7) | S1 | no observation reads as compliance, or an axis changes without supporting evidence |
| S7 | joint checkpoints (§4.9) | S3 | an unrelated local record makes identical joint inputs diverge, or the manifest includes itself |
| S8 | MCP over the canonical events | S2–S7 as needed | a tool admits what the checker refuses, or executes a received script |

## 7. Questions still open

1. What ordering rule settles conflicting joint checkpoints (§4.9) without a global consensus layer?
2. Which reservation mechanism, if any, should make quotas more than view-local (§4.1, rule 5)?
3. Is folding the ontology's `IDENTITY-RULE` into `stipulated` too coarse (§4.7)?
4. Which meta-constraints should a recipient profile name by default (§4.6)?

## 8. Review of revision 1 (Codex, `6fa8cb8`, AMEND): disposition

| Point | Answer in this revision |
|---|---|
| R22-01: rooted chains need attenuation and real roots; authority is not competence; purpose is not power | §4.1 rules 1–6; §3 on purpose |
| R22-02: an empty trigger list is not unfalsifiable; incomplete views; supersession does not erase history | NO_DECLARED_TRIGGERS; three judgments, including completeness; future-use-only effects (§4.2) |
| R22-03: declared triggers must not monopolize challenge; late children bypass standing; A → B → A | the challenge route and slot occurrences (§4.3); enrolment with admission order (§3, §4.2) |
| R22-04: no universal ban on attestation; partial order; migration is not preservation | admission per act; tiers set by the recipient; per-input bases; lineage with meta-constraints, opt-in and exit by new root (§4.6) |
| R22-05: a norm in force is not known compliance | the two constraint axes (§4.8) |
| R22-06: joint checkpoints without self-reference, over the shared slice | the pre-action manifest; forks open (§4.9) |
| R22-07: claim types are several axes; the 𝒬 mapping is approximate | the three axes and the adaptation loss (§4.7); the approximate table (§2) |
| Plan: P2 needed P3; smaller slices | §6, ordered by actual dependency, one PR per slice |
| Paper version pinned | §1: draft 0.3 at `a391c91` |
