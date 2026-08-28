<!--
LEDGER HEADER.
Reviewer label: `codex` (OpenAI Codex, run against PR #30 HEAD 4751844).
Genre: whole-PR review — governance/CI hygiene + technical + philosophical.
  Not a settlement gate; a merge-readiness review of the entire branch.
Verdict: do NOT merge; convert to Draft, freeze, split into reviewable PRs.
Response: reviews/2026-08-codex-pr30-full-review-response.md
Manifest: reviews/manifests/2026-08-codex-pr30-full-review.manifest.json
Independence class: same vendor family (OpenAI) as several prior gates;
  LLM-authored; NOT human. But the first review to look at PR HYGIENE and the
  CI/governance plane rather than the artifact's content — and it found live
  defects (unparseable governance workflow, a WRT-004 hole) the green suite
  did not see, precisely because they live outside what the suite checks.
-->

# Codex — whole-PR review of #30 (HEAD 4751844)

Relayed verbatim by the operator. Verdict: **do not merge; Draft + freeze +
split.** GitHub state unchanged by the reviewer.

## Critical findings (as received)

1. **Governance gate effectively does not exist.** `agent-gate.yml:49` does not
   parse as YAML (unquoted `--only-binary :all:`); every recent run finishes
   `failure` with no job; it is not shown as a required check; `master` has no
   branch protection; and the intended run carries `|| true`. For a repository
   whose thesis includes a governance control plane, a first hotfix PR should
   fix the YAML, add self-validation/negative control, and decide whether the
   verdict actually blocks merge.

2. **WRT-004 can report `BOUND` for a profile that is not signed into the
   record.** `check_binding()` receives a pre-parsed profile and never checks
   its hash, canonical bytes, or presence in `body.evidence`; even the positive
   fixture omits the profile from evidence. Repro: a perverse map
   (`false → accept`), profile not in evidence, profile bytes not even in the
   store — `checker result: True []`. Plus the filer defines `decision_map`, so
   L3 proves conformance to a filer-chosen table, not entailment. A design
   blocker, though the proposal is non-normative.

3. **Lean mechanization proves a weaker claim than the paper states.**
   `atp_cannot_steer` takes budget-stability as a precondition; the sibling
   proof has totality, budget bound, and settled normal form but no proved
   inter-budget stability. So the paper's "fail for all inputs" is overstated:
   the formalization checks the abstract rule's algebra under assumptions, not
   the refinement of the real evaluator → settlement implementation.

4. **Claim-checking apparatus still claims more than it checks.** The paper
   README promises to recount "every countable number"; the checker honestly
   names four unchecked classes; the papers index still says a stale
   "76-document review ledger" (now 89); the paper README references a
   nonexistent `tools/test-all.sh`; and if the vendor-pattern ever vanishes the
   checker adds a false success via `if m … else checked`.

5. **Paper status internally contradictory.** It says the paper "has not been
   peer reviewed" and later calls a model review a "full peer review"; by its
   own methodology (zero human experts, one orchestrator, no epistemic
   independence) this should be "whole-paper adversarial model review". The PDF
   builds cleanly, 15 pages, no clipping — but the TOC shows §1.2 before §1.1
   because the source is in that order.

## Philosophical review (as received)

The strong core is a tamper-evident, content-addressed decision receipt with a
replayable attached check — a real, well-engineered contribution. But "reason",
"justification", and "warrant" carry normative weight the core format does not
yet provide: replay is not entailment; an evidence blob is not a true fact; key
identity is not actor identity; a hash does not prove historical existence or
completeness; the same result is not necessarily the same legal or epistemic
reason. WRT-003 makes a *policy* choice for extensional closure (two arguments
with one result are one consequence) — a useful anti-spam rule, not neutral
"new reason" semantics; better described as a foreclosure policy. WRT-004 as it
stands is a *declaration-coherence* profile, not a reason-binding proof. The
review ledger proves adversarial intensity, not external validity: 89
internally orchestrated documents do not substitute for a clean-room
implementer or a human domain reviewer. Related work is largely correct
(RFC 9943 is a June 2026 Proposed Standard; the VAC `-00` is valid today but
expires 2026-08-29 — "closest active work" will need updating or historical
fixing).

## Recommendation for PR #30 (as received)

Do not merge; mark Draft and freeze. Separate hotfix PR for `agent-gate` and a
real merge-enforcement policy. Split WRT-003 + fixtures + Lean proofs into one
PR (fix the formal claims); split WRT-004 + prototype into another (hash-bind
the profile to `body.evidence`; close schema/canonicalization; remove or name
filer-defined semantics as policy-controlled; add post-hoc-profile and
perverse-map negative vectors). Keep #30 paper-only (fix terminology,
numbering, claims checker, stale counts, PR description). Before deposit,
require two external gates: a clean-room implementation from the SPEC and a
human review of logic/authorization/governance.
