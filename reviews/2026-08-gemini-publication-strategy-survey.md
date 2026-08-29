# Gemini — publication-potential survey (untyped, not a gate)

**Date:** 2026-08-27 (delivered in-session before `papers/` existed; filed
retroactively the same day, when the Qwen survey of the same genre was filed —
registering one scouting report and not its twin is the mirror-blindness this
project keeps having to name).
**Reviewer label:** `gemini` (agentic IDE session with repository access — it
read SPEC, THREAT-MODEL, proposals, profiles, the reviews corpus, and the
sigma-glyph papers pipeline before reporting). Vendor: Google.
**Genre:** scouting survey — no severities, no verdict, not an adversarial
gate.
**Provenance:** relayed by the operator; condensed here by the maintainer
from the in-session report (tool-call log and file inventory trimmed; every
substantive claim kept). The original prompted the creation of `papers/`.
**Response (joint, with the Qwen survey):**
[`2026-08-publication-strategy-surveys-response.md`](2026-08-publication-strategy-surveys-response.md)

---

## Overall assessment (as received)

The repository has "виключно високу готовність до публікації
науково-технічних статей на Zenodo": 3 independent implementations (Python,
Go, Rust-from-scratch), conformance vectors ("138+"), normative negative
batteries, a formal threat model, "77 змагальних аудитів від 6 сімейств LLM",
and legal analysis (EU AI Act, CEN/CENELEC, *Air Canada*).

## Proposed papers (5)

1. **Flagship — protocol & architecture.** *"Warrant: Signed,
   Content-Addressed Decision Records with Deterministic Re-Executable
   Reasons for Autonomous AI Agents"* (alt: *"Trust the Hash, Not the
   Host"*). cs.DC/cs.SE/cs.AI/cs.CR. Thesis: observability records what an
   agent did, in operator-editable form; Warrant inverts to what was decided,
   under which byte-pinned policy, with signatures and JCS/SHA-256 identity.
   Apparatus: WarrantID; ski@v1 re-executable reasons (Σ-GLYPH Book I,
   size ≤ ATP+1); domain-separated 47-byte signature message; ±(2^53−1)
   integer domain; three-implementation byte-exact consensus.
2. **Settlement theory.** *"Settlement Semantics and Algorithmic Foreclosure
   in Content-Addressed Decision DAGs"* (alt: *"Novelty is Format, Relevance
   is Policy"*). cs.MA/cs.DC/cs.LO. Tunnels, syntactic foreclosure,
   re-litigation novelty, multi-root adoption.
3. **AI governance.** *"Governing the Expiring Delegate: Key State, Threshold
   Succession, and Bounded Authority for Machine Actors"*. cs.AI/cs.CY/cs.CR.
   Models as delegates, vendor-scheduled EOL, DAG-order key state, N−M≥1
   thresholds.
4. **Empirical hardening report** (companion to sigma-glyph's
   *Twenty-One Ways Past a Proof Guard*). *"Auditing the Verifier: What 77
   Cross-Model Adversarial Rounds and Three Independent Implementations
   Taught Us About Decision Record Integrity"*. Defect taxonomy: JCS vs
   double precision; Ed25519 torsion/scalar anomalies; parser leniency
   splits; vacuous suites; miscalibrated negative controls; cross-protocol
   digest collisions.
5. **Legal/regulatory.** *"Beyond Mutable Logs: Technical Implementation of
   EU AI Act Article 12 via Content-Addressed Verifiable Decision Records"*.
   Air Canada deconstruction, telemetry-vs-decision-records split,
   first-class rejects, evidence packs.

## Prior-art positioning (as received)

IETF VAC fixes the *conversation*; Warrant the *decision* (complementary).
Pham & Hy's V2 (replayable deterministic verification) is what ski@v1
mechanizes. in-toto/SLSA/Rekor: Warrant layers above via the in-toto
statement wrapper. CEN JTC 21 prEN 18229-1: Warrant contributes the
third-party independent-verifiability criterion.

## Infrastructure readiness (as received)

pandoc + tectonic present; the sigma-glyph `papers/one-integer` pipeline
(paper.md / references.bib / build.sh / README with DOI+commit) is the proven
pattern; CITATION.cff exists; a claims-checking script should verify every
number in a paper against the repository before deposit.

## Recommended roadmap (as received)

Create `papers/` in warrant on the sigma-glyph pattern → write Paper 1
(systemic, fixes protocol priority) or Paper 4 (empirical, richest material)
first → integrate a claims checker into CI → build the PDF → deposit on
Zenodo (concept DOI + version DOI, tag-pinned tarball) → cascade to
JOSS / IETF draft / arXiv tracks.

---

*Disposition note: the roadmap's first three steps were executed the same day
(PR #30 — `papers/the-reason-runs-again`, flagship variant chosen,
check_claims.py in the build); the census figures above were corrected in
that paper ("77 audits" counted `reviews/README.md`; the honest count at the
time was 76 = 61 + 15). See the joint response for the rest.*
