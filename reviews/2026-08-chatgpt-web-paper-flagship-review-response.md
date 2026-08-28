# Response — ChatGPT (web) review of the flagship paper (PR #30)

**Date:** 2026-08-27. Adjudicated by the maintainer model (Claude); every
CONFIRMED verdict below was verified against the repository, not accepted on
the reviewer's word. Paper fixes land in the same PR; findings against SPEC
and MODEL-ACTORS are recorded here with their disposition.

## Adjudication

| # | Finding | Verdict | Disposition |
| --- | --- | --- | --- |
| 1 | ski@v1 expect-flip novelty | **CONFIRMED — by reproduction, and by design** | Paper §5.2 rewritten; SPEC-level defect recorded below (open, not fixed here) |
| 2 | Abstract: 3 impls × 138 vectors | **CONFIRMED** | Abstract and §6 now state 134 base / 4 settlement and per-implementation grades |
| 3 | DSSE/CT/TUF/Git as bare-digest domains | **CONFIRMED (paper and SPEC §5 rationale both overstate)** | Paper §2/§4 reargued without protocol strawmen; SPEC §5 prose defect recorded below |
| 4 | Diversity-vs-depth causal claim | **CONFIRMED** | §7 downgraded to a single-observation report with confounders named |
| 5 | No signature-creation-time row | **CONFIRMED (real gap)** | Added to paper §8; recorded below as a proposed SA for THREAT-MODEL |
| 6 | Labels ≠ identities ≠ independence | **CONFIRMED** | Paper now says "reviewer labels (a filename convention this repository controls)"; census kept, framed as census |
| 7 | Immutable record / mutable envelope | **CONFIRMED** | §3 wording fixed |
| 8 | EU AI Act Art. 12 paraphrase too strong | **CONFIRMED** | §2 rephrased to "automatic recording of events … traceability" |
| 9 | VAC title/expiry | **CONFIRMED (independently re-verified against datatracker 2026-08-27)** | references.bib corrected; expiry noted |
| 10 | check_claims scope / build pinning | **PARTIALLY ACCEPTED** | build.sh now fails on unpinned pandoc/tectonic; tier split and citation-expiry gate recorded as follow-ups, not silently absorbed |

## 1. The expect-flip, reproduced

The reviewer predicted it from the fingerprint tuple; we ran it. Store with a
settled `accept` whose reason is `{ski:1, term:S, atp:20, expect:S}` →
re-litigation candidates citing the **same term**, each with a fresh
`expect`:

```
expect=11111111..  py: 'admissible: (b) new outcome fingerprint'  go: same
expect=22222222..  py: 'admissible: (b) new outcome fingerprint'  go: same
expect=33333333..  py: 'admissible: (b) new outcome fingerprint'  go: same
3/3 expect-flips admitted by BOTH implementations;
same term, same evidence, same actual reduction result each time.
```

Two sharpenings the reviewer could not see from outside:

1. **It is not an implementation bug.** `tests/settlement.py`
   `case_relitigation`'s "new fingerprint" case *is* an expect-flip
   (`fail_check` = same term, same atp, `expect="0"*64`) and the harness pins
   it **admissible** as the expected verdict. Both implementations implement
   SPEC §7 as written; the defect is the §7 fingerprint definition itself:
   `expect` (and the verdict it induces) are filer-chosen coordinates in a
   tuple that is supposed to measure *what the computation demonstrated*.
   With 2^256 choices of `expect`, novelty is unbounded at zero new
   computation.
2. **What the 0.5.0 fix actually bought.** Building the fingerprint from the
   re-run verdict (the 2026-07-29 fix) removed *claimed-verdict* arbitrariness
   — the verifier can no longer be lied to about what ran. It did not, and
   could not, make syntactic novelty mean semantic novelty. The reviewer's
   proposed core, `(runtime, term, actual_result_node_hash)`, would make the
   fingerprint a pure function of the computation; whether §7(b) should also
   admit predicate-level novelty (a genuinely *new question* asked of an old
   result) is exactly the "novelty is format; relevance is policy" boundary,
   and moving `expect` out of the format-level tuple moves that boundary.
   **Disposition: SPEC §7 change, gate-worthy, NOT made in this PR.** The
   paper now states the limit honestly instead of claiming ski@v1 escapes it.

## 3. The prior-art strawmen (also a SPEC defect)

Confirmed: DSSE signs `PAE(type, payload)` — it is a domain-separation
*precedent*, not a bare-digest victim; RFC 6962 signs a versioned structure;
TUF signs role metadata; a Git object id is a name, not a signature message.
The honest argument needs no named victims: bare-WarrantID signing would be
replayable into any context where the same key signs an unconstrained
32-byte value (raw-digest HSM/KMS signing interfaces are the realistic such
context), and the demonstrated instance is our own §8.5 reject vector — a
signature over the bare SHA-256 of unrelated content, accepted by every
pre-0.6.0 verifier as a warrant signature. The paper now argues it that way.
**SPEC §5's rationale paragraph carries the same overstated list** ("DSSE/
in-toto payload digests, TUF metadata, … RFC 6962 roots, Git object ids");
recorded here as a P2 prose defect against SPEC — the normative rule is
unaffected, the *because* under it is partly wrong, which this project's own
format says matters.

## 5. Signature-creation time (accepted as a new scoped assumption)

Correct, and not currently a THREAT-MODEL row: key validity derives from DAG
position; nothing establishes *when a signature was produced*. Compromise of
a formerly-valid key allows signing today into a DAG position where the key
was bound, and envelopes are appendable (A3), so a fresh co-signature on an
old record is undetectable as fresh. Proposed SA text (for THREAT-MODEL, via
its own process): *"Warrant does not establish when a signature was created.
Compromise of a formerly valid key can produce signatures valid relative to
an earlier DAG position unless that history was externally checkpointed
(OpenTimestamps / transparency log / archive snapshot) before the
compromise."* This promotes the existing anchoring tooling from archival
convenience to part of the security argument — the reviewer is right that it
already was, undeclared.

## 6. Census vs. independence

Accepted in full. The checker's vendor map verifies our ontology, not
reviewer independence — which is why the map lives in the checker, where it
can be disputed, and why the paper now names the census as a census. The
per-review manifest (vendor, model, session, prompt hash, context hash,
blindness, pre-registered stopping criterion) and the better metrics (defect
classes, cross-family rediscovery, overlap, post-adjudication FP rate) are
recorded as the design for the *audit experience report* companion paper —
that paper should not be written until the manifests exist, or it inherits
this finding wholesale.

## The systemic critique

Accepted without reservation, and it is the best sentence anyone has written
about this project's methodology: **six vendors ≠ six epistemic custodians.**
It is SA-3/SA-4 applied to ourselves at the orchestration layer, which is
where mirror blindness lives. The two proposed mechanisms — orchestration as
an audited object, and stranger-implements-from-SPEC-alone as a 1.0
graduation criterion (not "future work") — are adopted as positions; the
paper's §9 already ends on the second, and the first belongs in AGENTS.md /
gate policy, via their own adoption process.

## MODEL-ACTORS drift

Confirmed against the file: §1's heading overstates (an uncited leaf record
deletes cleanly; A1 says so) and §3's "Authorship is verifiable" is
base-grade-false (SA-2). Fixed in this PR with minimal edits that point at
the threat model instead of contradicting it — the philosophy document must
never be looser than the threat model.

## What was NOT accepted

- **Dropping the ledger census entirely from the abstract.** The count is
  kept, one clause long, framed as a census; the abstract's job includes
  saying what the evidence base *is*, and "76 documents, our own convention"
  is that statement. (The number moves to 78 with this review and response —
  and check_claims.py went red on the stale number exactly as designed,
  which is the tripwire doing its job, noted here because the reviewer asked
  whether the green can turn red.)
- **Citation-expiry as a build gate.** Right idea, wrong layer for this PR:
  it needs network access in a build that must stay reproducible offline.
  Recorded as a follow-up (`check_sources.py`, run in CI, not in build.sh).
