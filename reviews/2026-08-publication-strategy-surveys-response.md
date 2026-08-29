# Response — the two publication-strategy surveys (Gemini, Qwen)

**Date:** 2026-08-27. One response for both, because they answer the same
question ("what papers does this repository hold, and where do they go?") and
are best adjudicated against each other. Neither survey is a gate; this
response corrects their factual errors, records where three independent
scouts converge, and turns the converging advice into dispositions.

## Factual corrections (so the ledger does not launder them)

| Claim | Source | Correction |
| --- | --- | --- |
| ATP = "Algorithmic Turing Pricing" | Qwen | **Invented expansion.** In Σ-GLYPH Book I, *ATP* is the budget's proper name, not an initialism the spec defines; no document in either repository expands it. A confident gloss on a term the reviewer never saw defined is exactly the failure mode warrants exist to pin down, so it stays here as an exhibit. |
| "Відсутність formal verification" listed as a top weakness | Qwen | **Half-wrong.** The `ski@v1` runtime's determinism, termination and size ≤ ATP+1 memory bound are mechanized in Lean 4 (sigma-glyph, 36 guarded theorems; deposited at DOI 10.5281/zenodo.22069651). What is *not* formally verified is the Warrant layer itself — canonicalization, signature acceptance, settlement — and THREAT-MODEL SA-8 additionally scopes the `native_decide` trusted base. The true statement is "the verified core is below the format, not in it." |
| "77 змагальних аудитів від 6 сімейств" | Gemini | The 77 counted `reviews/README.md`; the honest census at the time was 76 = 61 reviews/gates + 15 responses (already corrected in the flagship paper, which now carries the live number and a checker that goes red when it drifts). |
| "10+ Security Assumptions, 6+ Non-Goals" | Qwen | Exactly 11 SA and 6 NG at time of writing (`tools/doc_counts.py` pins this). Right order of magnitude, needlessly hedged — the counts are checkable. |
| Venue acceptance probabilities (e.g. "USENIX 30–40%") | Qwen | Unverifiable numerics with no stated base rate or method; recorded as the reviewer's flavor, relied on for nothing. |
| "SKI combinator calculus" | Qwen | Close enough to note only for precision: Book I is a hash-thunk combinator machine over content-addressed terms; "SKI calculus" undersells the part that matters here (redex recognition by hash, priced peak memory). |

## Where three independent scouts converge

Gemini (5 papers), Qwen (6 papers), and the earlier chatgpt-web review were
produced without sight of each other, and they agree on the same three loads:

1. **The flagship format paper** — Gemini's Paper 1 = Qwen's Paper 1 =
   PR #30, already drafted and in adversarial review.
2. **The audit experience report** — Gemini's Paper 4 = Qwen's Paper 3
   ("quick win, highest acceptance odds") = the companion this repository's
   `papers/README.md` already lists. The chatgpt-web response adds the
   precondition the scouts miss: **per-review manifests first** (vendor,
   model, prompt hash, context hash, blindness, stopping criterion), or the
   paper inherits the census≠independence finding wholesale. Quick win it is
   not, until the manifests exist for at least the reviews it counts.
3. **The Σ-GLYPH+Warrant integration story** — Qwen's Paper 6 (OSDI/SOSP
   framing) is the one genuinely new proposal in either survey: neither
   Gemini nor the existing `papers/README.md` roadmap has an end-to-end
   verified-stack paper. Recorded as a candidate companion. Its honest
   blocker is stated in the flagship paper already: the correspondence
   between the Lean model and the running implementations is empirical
   (differential bridges), so "verified stack" would need scare quotes or a
   verified-extraction step it does not have.

Both surveys also flag the same two real gaps the flagship paper's §8 owns:
**no performance evaluation** (no benchmark suite is committed anywhere in
this repository; any "overhead is low" sentence would be unbacked and none
has been written) and **no external adopter beyond `oaip`** (whose adoption
experience is SA-2's sharpest evidence *against* the identity layer, and is
reported as such rather than as a case study).

## Dispositions

- Qwen's **venue framing** (peer-reviewed conferences) vs. the current
  **Zenodo-deposit track** (Gemini's, and the one in motion): not a
  contradiction. The deposit fixes priority and a citable artifact now;
  venue submission is a later act that the deposit does not preclude. What
  the venue track *additionally* requires is exactly Qwen's list —
  performance evaluation, real-world case studies, a formal-verification
  story for the format layer — and none of it exists yet, which is why the
  deposit comes first.
- Qwen's Paper 5 (policy-binding workshop short) and Paper 4 (multi-party
  governance): folded into the existing companion list rather than added —
  Paper 5 is a section of the flagship stretched to a paper, and Paper 4 is
  Gemini's Paper 2+3 under a distributed-systems label.
- The **"це просто audit logs з crypto"** novelty objection Qwen predicts
  from reviewers: the flagship paper's answer is the re-execution asymmetry
  (§5) and the settlement calculus (§5.2) — and, after review round 1, the
  honest statement of where that asymmetry runs out (the expect-flip). If
  the objection still lands after that section, it lands.
- Neither survey is counted toward any gate, threshold, or "reviewed-by"
  claim; both are counted in the ledger census as documents, under their
  vendor labels, which is all a census claims.
