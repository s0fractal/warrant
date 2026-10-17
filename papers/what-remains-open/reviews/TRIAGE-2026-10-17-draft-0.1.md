# Triage of the DeepReview of draft 0.1 (2026-10-17)

The review is kept verbatim in `2026-10-17-deepreview-draft-0.1.md`. It is an automated review of the PDF alone; it saw no code.

Each point was checked against the artifacts before the text changed:
- warrant `3e551e4`, plus PR #133 at `5c84580`;
- sigma-glyph `c864d3e`.

Every point gets one of four dispositions:

| Disposition | Meaning |
|---|---|
| **TEXT** | The paper was wrong, inconsistent or underspecified, and the artifact is fine. The text is fixed in draft 0.2. |
| **COVERED** | The artifact already does what the reviewer asks; the paper did not say so. The text now says so, with the code location. |
| **GAP** | The reviewer found a real gap in the artifact or the design. It is recorded as open in the paper (§8, §9), not fixed here. |
| **DISAGREE** | The reviewer's premise does not hold. The reason is given. |

## Found by the triage itself, not by the reviewer

| ID | Finding | Disposition |
|---|---|---|
| T0 | The §2.3 axis table omitted `TYPE_MISMATCH` from `fact_provenance`. `impl/assessment.py` `AXES` has it, and `_fact_provenance` returns it when the fact set is not exactly the program's typed parameters. | TEXT |

## Status taxonomy and framing (review section "Introduction")

| ID | Point | Disposition |
|---|---|---|
| R1a | The label "IMPLEMENTED as a draft reference" for #131 is a hybrid. | TEXT. #131 is merged into master as part of `b214c6c`, and its own spec calls itself a draft reference. Labels are now IMPLEMENTED or DRAFT only, with a separate note on adoption status. |
| R1b | "IMPLEMENTED as a pattern" is undefined. | TEXT. Split: #129 is IMPLEMENTED, the governance rule is prose, and the WRT-021 basis checks are DRAFT. |
| R1c | Missing commits and mutant counts for IMPLEMENTED items. | TEXT. Commits are added for every row. WRT-020 `tests/policy_binding.py`: 12 cases plus a read-only check. Its rules have no mutant harness, so the IMPLEMENTED definition now states its mutant clause per item, and WRT-020's lack of one is stated. WRT-010 has its own mutation set in `tests/fact_provenance.py` (ACCEPT in scope after five rounds). |
| R2 | The contributions list skips §2.2. | TEXT |

## §2–§3

| ID | Point | Disposition |
|---|---|---|
| S3-1a | PREFIX verification costs O(spent) and does not amortize across untrusted peers. | TEXT, accepted. It amortizes only through a verifier's own cache. The paper now calls it an audit and fault-isolation primitive, not a work-saving one. |
| S3-1b | Does the verifier compare states, and what if a multi-unit action steps over the claimed spent? | COVERED. `verify` checks `state_id(state_bytes)` against the checkpoint (STATE_MISMATCH), then replays to the claimed spent and requires an equal `state_id`, `spent_total` and peak. A replay that steps over the claimed spent cannot match, which gives UNVERIFIED_PREFIX. The text now says so. |
| S3-2 | "No control state" seems to contradict "same machine state, not term hash". | TEXT. The machine state is the term tree with its thunk/materialized distinction (`SGS1` codec). A cold thunk and its materialization share a term hash with sizes 1 and 3 (probe B04). "No control state" means no stack, program counter or budget-dependent state outside that tree. The witness fields are now listed. |
| S3-3a | BLOCKED_REFERENCE resumption changes the computation identity. | TEXT plus GAP. True: the environment manifest is part of the identity, so extending it starts a new computation. Chaining computations across attested inputs is not specified, and is now an open question. |
| S3-3b | How facts are bound into the compiled term. | TEXT. In #131, the PolicyProgram has no fact values. The FactSet supplies them, and the registered compiler (`wpl@v1/policy_lang.py@<digest>`) compiles program plus facts. `compilation_binding` recompiles and compares the emitted `{check, term, expect, atp}`, so a new FactSet means a new plan whose recompilation matches. In #130, a WPL file still holds rule plus facts (WRT-020 §7 Q2). |
| S2-4a | Novelty precedence; whether a budget refile can turn PAUSED into an answer. | TEXT/COVERED. The order is fixed in code: MIGRATION_REQUIRED, then SCOPE_MISMATCH, then not-eligible (NO_NEW_CONSEQUENCE), then NEW_CONSEQUENCE, then NEW_EVIDENCE, then NO_NEW_CONSEQUENCE. A PAUSED report is not settlement-eligible, so it settles nothing; the first report with a normal form is the first consequence. |
| S2-4b | Slot churn: any changed value in a named slot is NEW_EVIDENCE, even with the answer unchanged; A→B→A cycles are possible. | GAP, accepted. `novelty` compares slots pairwise and any change counts. Recorded as open. |
| S2-4c | Novelty is blind outside the named slots. | GAP, accepted as a known boundary. Routing out-of-schema counterexamples to `questions(scope)` is recorded as a proposal. |
| S2-5a | The reject truth table, and the asymmetry between WRT-020 and #131. | TEXT. WRT-020 never gates a reject (a reject is discretion; its §7 Q3 asks whether that is right). #131 makes `discretionary_reject` the recipient's choice, with no default. NON_BOOLEAN or an unfinished run gives NOT_ASSESSED. The full table is now in the paper. |
| S2-5b | The predicate for `required_profile`. | TEXT. SATISFIED iff the record cites a PolicyProgram, a FactSet and a CompilationPlan, or the profile's required class is `witness`. |
| S2-5c | Mapping WRT-010 states onto `fact_provenance`. | TEXT. #131 does not consume WRT-010's statuses. It has its own check: observed facts must be attested by an admitted issuer, and derived facts are Boolean only, equal to a replayed answer. Unifying the two is GAP. |
| S2-5d | Compiler pinning in #130 versus #131. | TEXT. #131's registered compiler id includes the digest of `policy_lang.py`. That is #131's answer to the drift question #130 leaves open. |
| minor | Cents (650.88 vs 65088); PREFIX token; WRT-010 status case; "Book I" undefined. | TEXT |

## §4

| ID | Point | Disposition |
|---|---|---|
| S4-1 | Creusot residuals: prover versions, `why3.conf`, environment flags (`RUSTFLAGS`, `--cfg`), and cross-crate `#[path]` divergence. | TEXT plus GAP. POLICY.md already says the toolchain, the Creusot install, the provers and `~/.cargo/config.toml` are recorded in the evidence, not checked. The paper now lists these as residual assumptions of a CLAIMED attestation, and adds the environment-flag and cross-crate-context residuals the reviewer names. The proof attestation is an actor attestation by a scoped agent key, over a run log. |
| S4-2a | Downgrade pressure: honest stronger claims are blocked while attestations pass. | GAP, accepted; this is the paper's own Q7. Proposed: record a claimed basis plus a validated floor; a duty that requires the stronger basis stays open. Not implemented. |
| S4-2b | Input laundering: a replayed computation over self-attested inputs. | TEXT plus GAP. #131 keeps them on separate axes (`fact_provenance` vs `computation_verification`). WRT-021 has no composite basis yet; the `(computation basis, weakest input basis)` tuple is recorded as a proposal. |
| S4-2c | A runner attestation collapses into an actor attestation under single-operator keys. | TEXT, accepted. Without key isolation it is an actor attestation over a structured log; §8 now says so. |
| S4-2d | Why WRT-021 does not call the existing replay verifiers. | TEXT. It is an integration not yet built, not a format gap. ski@v1 replay and sigma-resume `verify` exist; WRT-021 has no receipt schema binding a transition to one. |
| S4-3 | The bases form a partial order, and recipient re-execution is view-local. | TEXT, accepted. Replay and host execution are incomparable. A stored recipient re-execution is an actor attestation to any third reader. That is already why WRT-021 records acceptor support without raising a basis; the paper now says it. |

## §5 (WRT-021)

| ID | Point | Disposition |
|---|---|---|
| S5-1 | Standing policies could turn a stream of questions into unbounded duties. | GAP. No auto-assigning policy exists in WRT-021 today, because opening needs the holder's own act. The proposed bounds (admitted issuers, quotas, an intake transition) are recorded. |
| S5-2a | Power and competence are used but not represented. | GAP, accepted. Who may open, release or accept is fixed per duty (`release_by`, `acceptance`, the holder rule). There is no general power record and no recovery path for a lost holder key. |
| S5-2b | Prohibitions differ from invariants. | GAP, accepted. Only observed invariants with freshness exist. A prohibition broken by a counterexample record is not modelled. |
| S5-3a | Dynamic children; READY_TO_CLOSE. | GAP. `closure_requires` is fixed when the duty opens. |
| S5-3b | Upward invalidation in `reliance`. | COVERED. A parent's named-child condition is evaluated on every assessment. A child that becomes CONTESTED or loses its discharge makes the parent's candidate UNMET_CONDITION, so the parent is no longer DISCHARGED and `reliance` is NOT_CLOSED. Discharge does not propagate; the parent's own condition is re-evaluated. |
| S5-3c | When a duty is ORPHANED. | COVERED. A non-root duty is ORPHANED when every parent it serves is RELEASED, ABANDONED or DECLARED_IMPOSSIBLE. A MISSING parent gives MISSING, never ORPHANED. The paper now states the rule. |
| S5-4a | Delegation versus substitution liability. | COVERED. An admitted delegation keeps the holder, who stays in its own frontier and remains liable. Substitution needs the creditor. The text now says it. |
| S5-4b | Pending, rejected or expired handoffs. | GAP. There is no reject or expiry for a transfer request; a pending request stays pending. |
| S5-5a | Split views in bilateral steps; co-signed view checkpoints. | GAP, accepted. The proposal is recorded. |
| S5-5b | Who may contest. | COVERED in part. CONTESTED arises only from two *admitted* incompatible closures, so an unauthorized filing is OVERCLAIMED and cannot contest. A general reopening record does not exist (GAP). |
| S5-5c | Revision in the view; orthogonal commits. | TEXT plus GAP. The current set is an argument to `assess`, but it is not in the view digest; it should be. A whole-commit revision makes every new commit UNASSESSED, and scoped tree hashes are not supported. |
| S5-6 | A consolidated vocabulary table; the meaning of the verify result; complexity. | TEXT. The table is added. The paper now says `warrant verify` on a loop store shows format compatibility, not loop semantics. Complexity is linear in transitions × duties per assessment, with no index. |

## §6–§7

| ID | Point | Disposition |
|---|---|---|
| S6-1 | Capsule rules against many identities, transitive laundering, flooding, and triggers. | GAP (VISION). Accepted as requirements: credit by assessed basis and admitted roles, not key count; open assumptions as a checked superset of the grounds' assumptions; consumer consent on import; machine-checkable triggers. Recorded in §6.1. |
| S6-2 | Related work: Chopra and Singh (BSPL, Cupid, Custard), UCON_ABC, XACML 3.0. | TEXT. Added. The differentiating claim is narrowed to the evidential one, as the reviewer suggests. |
| S6-3 | Converse Goodhart. | TEXT, accepted. The quantities are diagnostic telemetry, never targets. |
| minor | Invariant Recipe citation; status typography; "von Wright" form; Availability table. | TEXT |

## Not adopted

None of the points is rejected outright. The closest to a DISAGREE is S5-5b: the reviewer's denial-of-settlement by "any unprivileged actor" does not hold for CONTESTED, which needs admitted closures. The general reopening mechanism it presupposes does not exist yet, though, so the point stands as a gap.
