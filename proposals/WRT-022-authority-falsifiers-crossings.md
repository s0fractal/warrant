# WRT-022: Authority, falsifiers and crossings — what WRT-021 left open, rethought

**Status:** DRAFT proposal, 2026-10-18. Written by Claude at the owner's request. Nothing is implemented, and nothing in SPEC.md or `warrant verify` changes.

It starts from the current surface:
- master `8855f7b`, where WRT-021 is merged with Codex's WL03 fix: L01–L38, 44 mutants, re-run for this proposal;
- the paper draft *What Remains Open* 0.2, carried on this branch. Codex has not seen it before this PR.

It does **not** carry out WRT-021's "not done" list as written there. Each item on that list is restated in §3 in the terms of this proposal.

## 1. Where this comes from

| Source | What it is | What is taken |
|---|---|---|
| **DeepReview of the paper draft 0.1** — `papers/what-remains-open/reviews/2026-10-17-deepreview-draft-0.1.md`, with the triage `TRIAGE-2026-10-17-draft-0.1.md` beside it | an automated review of the PDF alone; the triage checked every point against the code | the GAP rows of the triage, now §8 of the paper: power and competence; prohibitions; children discovered late; transfer rejection and expiry; reopening with standing; revision not in the view; split views in joint steps; downgrade pressure on evidence bases; novelty slot churn; chaining computation across attested inputs; capsule rules against many identities |
| **The meta-ontology** — manifesto `artifacts/ONTOLOGY-FORMALIZATION-0.1.md`, merged as manifesto #17 at `dd0a74b` | a typed working compilation of the manifesto corpus. It is not reviewed and adopts nothing. | the question operator 𝒬(T) = (Preserved, Scope, **Authority**, Evidence, Lost, **Falsifier**) (§1.2); the cross-trajectory transfer law, "zero automatic credit" (§1.3); constraint and invariant as different sorts (§2, §3.4); the translation report, where "untranslatable" is a first-class result (§3.6); the burden of proof proportional to ΔReach × irreversibility, and the legitimacy tuple (§7.3.4); the present as a local frontier, with consensus as the synchronisation of a shared irreversible past (§7.1.2); lineage through a meta-invariant (§7.1.3); six epistemic types, where hallucination is an illegal cast from candidate to settled (§0, §4.4) |
| **WRT-021**, merged | the obligation slice as a profile | its own lists of what it does not do (§7, §13, §14 of WRT-021) |

The meta-ontology is an idea source. As with WRT-021's manifesto notes, every idea taken from it is restated below as a rule with a test, and only the rule would bind.

Three of its elements are deliberately **not** taken:
- the `Conf ∈ [0,1]` field of its translation report. It contradicts the ontology's own rule against approximating discrete transitions with scalars (§3.5), and Warrant keeps closed vocabularies;
- VORTEX;
- semantic mass.

Warrant also does not become the ontology. The ontology itself says the ecosystem is a braid of trajectories, not a stack. Warrant's place in it is the protocol of **crossings and closures** between trajectories (§4.5).

## 2. The organising idea: every transition answers 𝒬

WRT-021's transition already carries four of the six components of 𝒬:

| 𝒬 component | WRT-021 field today | Gap |
|---|---|---|
| Preserved | `established` | none |
| Scope | `scope.subject` (an exact SHA) | whole-commit scope: every unrelated commit makes a closure UNASSESSED |
| **Authority** | implicit: per-duty lists (`release_by`, `acceptance`) and the holder rule | no record of power; no recovery; no bound on who may create work |
| Evidence | `did.basis` plus evidence, with the claimed and the assessed basis apart | only `ATTESTED` is validated |
| Lost | `not_established` | prose only |
| **Falsifier** | none | nothing says what would make the closure wrong, so `reliance` can only compare revisions |

WRT-022 adds the two missing components as typed, checkable objects, Authority (§4.1) and Falsifier (§4.2), and builds the rest from them.

## 3. WRT-021's open items, rethought

| WRT-021 said "not done" | Rethought as |
|---|---|
| assignment mandates | **power records** (§4.1). A mandate is a standing grant of an act within a scope. |
| goal, commitment, purpose | **Purpose is a standing power** to open duties within a scope; that is what "purpose generates obligations" means operationally. **Commitment** is an obligation whose creditor is the holder's own later self, released only by `release_by`. **Goal** stays as in WRT-021. Implementing goal and commitment remains deferred. |
| validation of runner, re-execution and replay evidence | **Replay through a crossing** (§4.5): a sigma-resume or `ski@v1` receipt crosses into the closure, and the recipient re-verifies it, so REPLAYED becomes view-local and validated. **Runner** evidence is an actor attestation by a key that holds an admitted `runner` power; isolation of that key is not provable and is stated as such. **Re-execution** stays view-local (paper §4.1) and is never a stored basis. |
| `closure_requires` fixed when the parent opens | **The parent's candidate enumerates its children at filing time**, together with the falsifier `child_opened_after(parent, candidate)` (§4.2). A child appearing later makes the parent's reliance STALE instead of silently closing. |
| applicability by a set of current revisions (F2) | **Falsifiers with scoped subjects** (§4.2): a closure is RELIABLE until a declared falsifier fires. A path-scoped tree hash is the default subject, so an unrelated commit does not touch it. |
| result capsules (VISION) | **A capsule is an established claim with falsifiers and an epistemic type** (§4.6), imported into another view only through a crossing. "Credit by role" is computed over admitted powers, not keys. |
| MCP tools (P3) | Unchanged in order: canonical events first, then tools that exchange transitions, crossings, contests and view checkpoints. No tool executes received scripts. |
| a real in-repo store with each agent's own key | **P0 here** (§6): each agent generates and holds its own key, and the next real review round is recorded for real. The limit is stated: one operator. |

## 4. Proposed objects and rules

Every object is a closed-schema blob carried by an ordinary signed record, as in WRT-021: a profile over the existing body, with no SPEC change in the first stage.

### 4.1 Power (Authority made explicit)

`warrant.power@draft-1` has these fields:

- **grantor** and **grantee**;
- **acts**, a closed set: `open_for`, `release`, `accept`, `substitute`, `reassign`, `contest`, `adjudicate`, `runner`, `migrate_profile`;
- **scope**: a duty kind, a subject pattern, and the duties that serve a named parent;
- **limits**: a quota of open duties, an expiry, and the minimum evidence basis the act requires;
- **notice**: who must be told.

Rules:

1. **A power is valid only if its grant chain roots** in the duty's own parties (the creditor or the holder) or in the recipient's trust snapshot. A chain that roots elsewhere is UNGROUNDED, and the act it authorises is OVERCLAIMED.
2. **Every non-holder act** in WRT-021, and every new act here, is admitted either by the per-duty lists, as today, or by an admitted power. The per-duty lists become the special case of a power granted inside the duty.
3. **`open_for` is how work is assigned without the holder's per-duty act**, the case the DeepReview raised (paper §8). It is bounded by its quota and by the issuers it names. Excess requests become **intake questions** in `questions(scope)`, not duties.
4. **`reassign`** gives the creditor a recovery path when a holder's key is lost or a duty LAPSED: substitution without the old holder, with notice, and only under an admitted power.

### 4.2 Falsifier

A closure mapping, and a capsule, may name falsifiers from a closed vocabulary:

| Falsifier | Fires when |
|---|---|
| `subject_changed(path, tree_hash)` | the recipient's current tree hash for `path` differs |
| `record_superseded(id)` | an admitted `supersede` of `id` is in the view |
| `slot_changed(slot, value)` | an accepted value in that named slot differs |
| `duty_not_discharged(id)` | the named duty is not DISCHARGED in the view |
| `child_opened_after(parent, candidate)` | a duty serving `parent` was opened after `candidate` |
| `key_retired(actor, key)` | key state retires that key |
| `predicate_false(check)` | a cited check replays to FALSE |

Rules:

1. **`reliance(duty)` is RELIABLE iff** the duty is an uncontested DISCHARGED and none of its falsifiers fires in the view. A firing falsifier gives **STALE(cause)**. A falsifier that cannot be evaluated in the view gives **UNASSESSED(cause)**. Unknown never means fine.
2. **A closure with no falsifier is reported as such.** It is not wrong, but `reliance` says `RELIABLE_UNFALSIFIABLE`, so readers can see that nothing could invalidate it.
3. **Novelty against slot churn** (paper §2.3). A candidate is NEW_EVIDENCE only if it fires a falsifier declared on the settled closure, or changes the answer. Comparison is against the whole tunnel's history of accepted slot values, not pairwise, so A → B → A is not new.
4. **A prohibition is a duty of shape `constraint`.** Its falsifier is a counterexample event; it holds until an admitted counterexample is filed, and is then VIOLATED. It never decays to UNOBSERVED (the DeepReview's prohibition gap; the ontology's constraint/invariant split).

### 4.3 Contest and adjudication (Contestability, Appeal, Repair)

- **`contest`** is a transition against an admitted closure. It is admitted only if both of these hold:
  - the contester has standing: the creditor, a required acceptor, or a holder of a `contest` power for that scope;
  - it carries something new relative to the closure's tunnel, by SPEC §7's own test: new evidence or a new outcome fingerprint.

  Otherwise it is CONTEST_INADMISSIBLE, so no denial of settlement by filing.
- **An admitted contest makes the duty CONTESTED.** Reliance is no longer RELIABLE until an **adjudication** by a holder of an `adjudicate` power resolves it as `UPHELD`, `OVERTURNED` or `REPAIRED`. REPAIRED carries the repair transition. The original closure is never edited.

### 4.4 Admission by irreversibility (the burden of proof)

- **A duty names a tier:** `reversible`, `costly` or `irreversible`.
- **The recipient profile maps each tier** to the evidence bases it admits and the acceptors it requires. A duty cannot admit fewer than its tier's minimum: a profile that lets an irreversible duty close on `ATTESTED` alone is refused as a profile.

  This is the answer to the downgrade pressure of paper §8. The convenient move, admitting attestation everywhere, becomes visible and refusable.
- **The assessed basis becomes a pair**: (computation basis, weakest input basis). A replay over self-attested facts reads as `(REPLAYED, ATTESTED)`, never as "replayed".
- **A change to the tier map is a profile migration** (§4.7), never a silent edit.

### 4.5 Crossing (zero automatic credit)

`warrant.crossing@draft-1` carries, from the ontology's transfer law:

- the source artifact at an exact revision and trajectory;
- the target profile;
- the mapping used;
- a translation report (preserved, lost, introduced, approximated, unknown; no confidence scalar);
- the evidence transferred;
- the new status;
- the new falsifiers.

A crossing whose report is incomplete is admitted as **BORROWED**: it is visible, and it carries no credit. **UNTRANSLATABLE**, with the conflicting invariants named, is a valid, first-class outcome.

Uses:

1. **The replay receipt.** A sigma-resume or `ski@v1` computation crosses into a closure. The recipient re-runs the source verifier (`sigma_resume.verify` against the root it chooses, or `ski@v1` replay), and only then is the basis REPLAYED in that view. This is the integration paper §4.3 names as missing. It is a crossing, not a special basis rule.
2. **Capsule import:** a claim settled in one repository or profile, reused in another. The consumer's consent is the crossing itself: nothing enters a frontier without one.
3. **Chaining across attested inputs.** Paper §3: an extended manifest is a new computation. The crossing records that the new computation's input is the old one's PREFIX plus an attested fact. The chain is a sequence of crossings, each with its own falsifiers.

### 4.6 Claim types (no illegal casts)

Claims carry one epistemic type from a closed set taken from the ontology's six types:

- `candidate`;
- `measured`, with its domain;
- `proved`, with its system;
- `stipulated`;
- `normative`;
- `debt`, or `withdrawn`.

**A claim's type changes only through a transition whose admitted evidence supports the new type.** For example, `candidate → measured` needs a measurement with its domain, and `→ proved` needs a proof artifact through a crossing. Any other change is reported as an **illegal cast**.

This generalises the WL01 lesson ("a label is not the act") and the paper's IMPLEMENTED/DRAFT/VISION discipline to the record layer.

### 4.7 Profiles change by warranted migration (lineage)

A recipient profile, its tier map and its admitted powers change only through a `migrate_profile` transition under the previous profile. It carries:
- the diff;
- a loss report: which closures become UNASSESSED;
- the holder of the `migrate_profile` power.

Assessments name the profile lineage they used. This is the ontology's "identity through a meta-invariant" applied to the recipient. A quiet policy downgrade becomes a record.

### 4.8 View agreement before joint irreversible acts

Before any act that needs two or more parties and is in the `irreversible` tier (substitution, adjudication, release of an irreversible duty), the parties co-sign a view checkpoint: `(store snapshot, trust snapshot, as_of, evaluator, profile lineage, frontier digest of the duty)`. A party assessing a different view sees **VIEW_DIVERGED** instead of a closure.

The present stays local, per the ontology's §7.1.2. The checkpoint synchronises only the shared irreversible past the act needs.

## 5. What this does not do

- It does not make any of this normative: everything is a profile, as in WRT-021.
- It does not prove key isolation, independence or honesty. A `runner` power says who is admitted to run, not that the run was faithful.
- It does not decide semantic novelty in general; falsifiers are declared, not discovered.
- It does not implement goals, commitments, VORTEX, semantic mass or numeric confidence.
- It does not add a second registry. Powers, falsifiers, crossings and claim types are blobs in the same store, under the same verify.

## 6. Plan

The order is by dependency. Each stage ships with vectors and one on-target mutant per rule, as WRT-021 did.

| Stage | Content | It fails if |
|---|---|---|
| P0 | **A real store.** Claude and Codex each generate and hold their own key; `trust.json` sits in the repository; the next real review round is recorded as WRT-021 events. Fixture keys are used only in tests. | the round cannot be recorded without one agent signing for the other |
| P1 | falsifiers and `reliance` (§4.2, rules 1–2), path-scoped subjects | an unrelated commit makes a closure STALE, or an unevaluable falsifier reads as fine |
| P2 | contest and adjudication (§4.3) | a party without standing, or a contest with nothing new, makes a duty CONTESTED |
| P3 | powers (§4.1), `open_for` with intake, `reassign` | a power whose chain does not root in the duty's parties or the trust snapshot authorises anything |
| P4 | crossing plus the replay receipt (§4.5): REPLAYED validated through `sigma_resume.verify` | a receipt whose computation the recipient did not re-verify is assessed REPLAYED |
| P5 | tiers and composite basis (§4.4); profile migration (§4.7) | an irreversible duty closes on `ATTESTED` alone, or a tier map changes without a migration record |
| P6 | constraint duties (§4.2 rule 4); claim types (§4.6) | a prohibition decays without a counterexample, or a type is raised without supporting evidence |
| P7 | view checkpoints (§4.8) | two parties holding different views both see a joint act as admitted |
| P8 | MCP tools over the canonical events | a tool admits what the checker refuses, or executes a received script |

## 7. Questions for review

1. Is a power record with a rooted grant chain the smallest representation of competence? Or should powers be ordinary duties of a special kind?
2. Is a closed falsifier vocabulary enough for real closures? Which falsifier does the first real review round need that is not in the table?
3. Does the tier map resist the downgrade pressure, or does it only move it into profile migrations? If it moves it, is that enough, given that migrations are records with standing?
4. Is "replay validated only after the recipient re-verifies the source" too expensive for practice? Paper §3 already says prefix verification does not amortise across untrusted peers.
5. Are the six claim types the right cut, and what is the minimal evidence for each legal cast?
