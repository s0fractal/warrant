# Redesign draft 1: the Warrant side, as implemented (DRAFT, not reviewed)

**Status:** DRAFT. This is a description of the reference code in this branch, not
an adopted specification. Nothing here changes SPEC.md or any verdict of
`warrant verify`. "Reviewed" in the redesign's P6 means an independent adversarial
gate, and the author cannot give that to their own text.

**Source:** the Codex redesign package of 2026-10-17
(`Documents/Codex/2026-10-17/sigma-warrant-redesign`) and its review
(`~/Projects/SIGMA-WARRANT-REDESIGN-REVIEW-2026-10-17.md`). The Sigma side, the
resumable kernel, is the sigma-glyph branch `resume/p1-p2-reference`. That branch
is local and not pushed; the demo vendors its files with a pin.

## 1. Records of the draft current path

A decision cites three typed blobs in `under` and runs one check:

| Blob | Schema | Holds |
|---|---|---|
| PolicyProgram | `warrant.policy-program@draft-1` | obligation, typed params, rule, `output: boolean`; **no fact values** |
| FactSet | `warrant.fact-set@draft-1` | obligation, and per fact: `observed {value, attested_by}` or `derived {value, from {record, check}}` |
| CompilationPlan | `warrant.compilation-plan@draft-1` | program id, fact set id, **registered** compiler id, declared options, runtime, emitted `{check, term, expect, atp}` |
| Observation | `warrant.observation@draft-1` | what an issuer attests: `{obligation, fact, value}` (the subject of the issuer's `accept`) |

`assessment.write_decision` is the only writer. There is no way to write the old
shape. `assessment.read_current` refuses any other shape as
`UNSUPPORTED_HISTORICAL_PROFILE`, names its WarrantID and the SHA-256 of its bytes,
and leaves the bytes as they are. The old shape is verified by the historical
pack (§4), never by the current path.

## 2. Assessment: one closed vocabulary per axis

| Axis | Values |
|---|---|
| record_integrity | VERIFIED, INVALID (`warrant verify --settlement --require-bound` under the recipient's trust) |
| policy_authority | ADMITTED, AUTHORITY_UNESTABLISHED, NOT_ASSESSED |
| fact_provenance | ACCEPTED, UNATTESTED, DERIVATION_MISMATCH, NOT_ASSESSED |
| compilation_binding | MATCHED_COMPILATION, COMPILATION_MISMATCH, UNREGISTERED_COMPILER, NOT_ASSESSED |
| computation_verification | REPLAYED_NORMAL_FORM, PAUSED, BLOCKED_REFERENCE, HOST_UNAVAILABLE, NOT_ASSESSED |
| policy_answer | TRUE, FALSE, NON_BOOLEAN, NOT_ASSESSED |
| decision_compliance | COMPLIANT, CONTRADICTED_DECISION, NOT_ASSESSED |
| required_profile | SATISFIED, REQUIRED_PROFILE_NOT_SATISFIED |

What each axis guarantees:

- **The profile belongs to the recipient.** It names the admitted programs, the
  obligation, the trust config, the fact issuers, `discretionary_reject`, the
  required profile, the evidence slots and the semantics class. Nothing in a
  record or a store widens it.
- **ACCEPTED is an attestation, not a truth claim.** It means an admitted issuer
  vouched for the value.
- **Compilation is checked by recompiling with a registered compiler.** A
  compiler named in a package is never executed. The binding is the emitted
  check, with the plan's declared options.
- **A run that did not finish is never TRUE or FALSE.**
- **`consumer_admits_action` is true only for an `accept` that is COMPLIANT** under
  a SATISFIED profile.

**Boolean profile** (decision against answer):

| Decision | Policy answer TRUE | Policy answer FALSE | Not assessed |
|---|---|---|---|
| accept | COMPLIANT | CONTRADICTED_DECISION | NOT_ASSESSED |
| reject | COMPLIANT if `discretionary_reject`, else CONTRADICTED_DECISION | COMPLIANT | NOT_ASSESSED |

## 3. Settlement (P4)

`consequence(report)` is `(semantics_class, obligation, replayed answer)`. It
exists only when the computation reached a replayed normal form of a matched
compilation in an admitted scope.

`novelty(settled, candidate)` returns one of these:

| Result | When |
|---|---|
| NEW_CONSEQUENCE | the same scope, a different replayed answer |
| NEW_EVIDENCE | a named slot, an admitted issuer |
| NO_NEW_CONSEQUENCE | budget, wrappers, headroom, checkpoints, a claimed verdict, or an unnamed blob |
| SCOPE_MISMATCH | an invented obligation |
| MIGRATION_REQUIRED | another semantics class |

## 4. Historical verifier pack

`tools/historical_pack.py build OUT` extracts the warrant verifier and its pinned
Sigma evaluators from git at the redesign baseline `ca53e64`, and records each
file's SHA-256 in `MANIFEST.json`. `verify PACK STORE` refuses a pack whose files
do not match. Otherwise it runs the pack's own verifier with `python3 -I` from the
pack directory.

## 5. X1: proposed replacement map (redesign §21)

Every row below is **proposed**. Removing an X1 obligation is the owner's decision;
this branch removes nothing.

| Today (X1 / cross-repo) | Proposed owner | State in this branch |
|---|---|---|
| Book I vectors and differential fuzz | sigma-glyph kernel conformance, Python + Rust | resume corpus exists: `tests/resume_differential.py` (sigma branch), 2268/2268 Python = Rust, 60/60 wasm = native |
| historical Sigma `.warrants` store | the frozen historical verifier | `tools/historical_pack.py` (§4) |
| current policy/decision connector | the assessment over the new body | `impl/assessment.py`, `tests/assessment_test.py` |
| "no silent substitution of the evaluator" | runtime-identity and unknown-profile negative controls | sigma: the computation id carries the runtime (CONTEXT_MISMATCH, N04); warrant: UNREGISTERED_COMPILER (N44), UNSUPPORTED_HISTORICAL_PROFILE (N66) |
| roster/anchor configuration of the old bundle | historical replay under a fixed context | pack + its pinned files; **not** wired to anchors here |
| byte-identical copies of the X1 harness | a versioned shared test pack with source/digest | **not done**: the demo vendors the kernel with `vendor/sigma/PIN.json`, a pattern, not the pack |

`tools/x1_cross_repo.sh` and its negative control stay as they are until the owner
accepts a map like this one.

## 6. Matrix status (redesign TEST-MATRIX.md)

| Range | Where | Result |
|---|---|---|
| N01–N37 | sigma `tests/resume_test.py` | PASS except N05, N15, N27 (UNRUN, named) |
| N38–N60 | warrant `tests/assessment_test.py` | PASS except N59 (UNRUN: no cycles under ski@v1) |
| N61, N62, N69 | sigma `tests/resume_differential.py` | PASS (plus wasm route and worker deadline) |
| N63–N65 | warrant #130 attestation vectors | PASS |
| N66–N68 | warrant `tests/redesign_p6_test.py` | PASS |
| N70 | warrant `tests/check_omission_control.py`: `tools/check.py` names REQUIRED_SCRIPTS; a copy with one dropped is red and names it (independent review: the general UNRUN mechanism alone was not this control) | PASS |

## 7. Not done, deliberately

- **Publication.** No release, no package and no push of the sigma branch. The
  sigma repository's AGENTS.md requires the owner's explicit authorization.
- **Normative adoption.** Making any assessment axis an error of `warrant verify`
  is a SPEC change and needs the gate.
- **A Rust engine for the rich Y/M/W profile** (added by another session, sigma
  `f371005`). The differential covers the Book I profile only, and says so.

## 8. Independent review (Codex, 2026-10-17): AMEND, and what changed

Report: `Documents/Codex/2026-10-17/sigma-warrant-redesign/INDEPENDENT-REVIEW.md`.
Verdicts: 4 ACCEPT, 10 AMEND, 0 REJECT. Every finding has a regression, and each
regression fails on the reviewed head on the review's own reason.

| Finding | Fix | Where |
|---|---|---|
| SG01 a cycle proven under another environment | one shared context check for both verifiers | sigma #62 `8398ce8` |
| SG02 an INCOMPLETE prefix could not be verified | replay to the claimed spent; PREFIX is not terminal | sigma #62 `8398ce8` |
| SG03 a malformed parent crashed the cached verify | exact id formats; INVALID_ENCODING | sigma #62 `8398ce8` |
| SG04 a host exception, and NORMAL_FORM over the size ceiling | fenced first measurement; the completed return is checked | sigma #62 `ad54abc` |
| PA01 a symlinked `.cargo` was missed by the manifest | symlinks refused as unsupported inputs; config read from the crate itself | warrant #130 `8e6401d` |
| WA01 an int "derived" from a Boolean answer | exact types (bool is not int); only Boolean derivation, equal to the replayed answer | #131 |
| WA02 unattested facts produced a consequence | a consequence needs integrity, ACCEPTED facts, a SATISFIED profile and the same profile id | #131 |
| WA03 NEW_EVIDENCE from a tuple, scope checked late | `novelty(settled_report, candidate_report)`: scope first, then answer, then accepted slot values | #131 |
| WA04 context_id ignored the trust bytes | trust read once; verification uses that snapshot; the context names its digest and each envelope snapshot | #131 |
| WA05 MATCHED with a false runtime, expect or atp | closed plan schema; every emitted value equals the recompilation | #131 |
| WA06 a pack ran a substituted verifier | expected manifest digest chosen by the recipient (pinned or `--expect-manifest`); exact file set | #131 |
| D14 the demo transferred only PAUSED, and NEW_EVIDENCE was a tuple | INCOMPLETE transfer verified as PREFIX; NEW_EVIDENCE from a real new observation | #131 |
| reject discretion defaulted to true | `discretionary_reject` has no default: the recipient must choose | #131 |
| N70 was claimed from the general UNRUN mechanism | a named harness-omission control | #131 |

This response is the author's. Whether these fixes hold is for the next review
round, which covers the changed boundaries. ACCEPTs from the previous round do not
carry over automatically.
