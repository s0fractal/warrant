# Adjudication — Gemini 3.1 Pro external audit (2026-07-17)

Raw audit: [`2026-07-gemini31pro-agy-audit.md`](2026-07-gemini31pro-agy-audit.md)
(Gemini 3.1 Pro High, run locally via `agy` in print mode, fed the recent hardening diffs + both
differential fuzzers). This was the first *external* audit of the architect-mode hardening; every
finding was reproduced or refuted empirically before disposition.

**Headline:** the auditor found real defects the two differential fuzzers had *blind spots to* — which
is exactly the point of an external pass. Three genuine issues + one fuzzer-soundness gap fixed; three
findings refuted with evidence.

## Dispositions

| Gemini finding | Verification | Verdict |
|---|---|---|
| **P0** ATP reset via `uint32` wrap in Go `force` (`cost = 1 + subSpent`) | `force` cost = `sigmaSize(v) ≤ 3` (no sub-eval); R-S already computes in `uint64` and checks affordability *before* narrowing; every branch guarantees `cost ≤ remaining`, so `spent ≤ atp` always — no wrap | **REFUTED** (hallucinated `force` mechanic) |
| **P0** blocklist missing 2 Ed25519 encodings (`01..0080`, `ecff..ffff`) | both keys accept a zero-sig **0/128** in Python `cryptography` AND Go `crypto/ed25519` — rejected at decode (non-canonical sign for x=0); no forgery, no split | **REFUTED as exploit**; the encodings **added to the blocklist anyway** as defense-in-depth for a lenient third impl |
| **P0** Python crash on top-level scalar record (`123`) | `all_records` short-circuits on `not isinstance(env, dict)`; handled cleanly (0 records, 1 error) | **REFUTED** |
| **P0** Python crash on non-object signature entry | CONFIRMED: `s.get('actor')` on a `str` sig threw `AttributeError`, crashing the verifier; Go was fine → crash + divergence | **REAL — fixed** |
| **P0** Go stack-overflow on deeply-nested JSON | CONFIRMED but **direction inverted**: **Python** raised `RecursionError` (uncaught by `all_records`) and crashed; Go returned a bounded error | **REAL (Python) — fixed** |
| **P1** fuzzer Loop C hides a *shared* accept of a malformed record | CONFIRMED: `(cp>0) != (cg>0)` is False when both wrongly accept | **REAL — fixed** (and it immediately caught a no-op `exp_num` mutation in my own fuzzer) |
| **P1** `book1_fuzz` never sends `uint32` boundary budgets to the engines | CONFIRMED (atp capped at `EVAL_CAP` in the emitted vector) | **REAL — fixed** |

## Fixes

- **Non-object signature entry (Python).** `verify_store` now checks `isinstance(sigs, list)` and skips
  a non-dict entry with a WARN *without* touching `s.get(...)`; a new `_iter_sigs()` routes every
  settlement-path signature iteration through the same guard. (`impl/warrant.py`)
- **Deep-nesting `RecursionError` (Python).** `all_records` now catches `RecursionError` and reports the
  record as malformed, matching Go's bounded behavior. (`impl/warrant.py`)
- **Blocklist defense-in-depth.** The two non-canonical sign-bit torsion encodings added to all four
  Ed25519 verifiers (warrant PY+GO, sigma `warrant_verify.py` + `anchor_governance.py`), documented as
  already-rejected-by-current-libs.
- **Fuzzer soundness.** `fuzz_differential.py` Loop C invariant strengthened to *both must reject*
  (`cp[0] > 0 and cg[0] > 0`), catching shared-accept; new dirty cases `sigs_notlist`, `sig_scalar`,
  `deep_nest`, a valid-record `m_scalar_cosig` case in Loop B, and a fixed `exp_num` (its old string
  replace silently no-op'd). `book1_fuzz.py` now emits a genuine `2^32-1` budget for terms that halt
  within `EVAL_CAP`, so all three Book I engines are exercised at the integer boundary.
- **Named regressions** in `tests/hostile.py`: non-object sig entry (no crash, PY/GO agree) and
  deeply-nested record (both bounded, no `RecursionError` / no panic).

## What stood out

The differential fuzzers I shipped this cycle would NOT have caught the non-object-sig crash or the
deep-nesting crash (Loop C's weak invariant + no scalar/nesting mutations), and one of my own fuzzer
mutations (`exp_num`) was silently a no-op. An independent reader found all of it. This is the case for
external audit as the acceptance gate, not self-review.

## Test evidence

Green after fixes: conformance 20/20 PY+GO; sigma 33/33; `differential`, `negative`,
`hostile` (+3 new), `settlement`, `pedantic_edges`, `ski_policy`; `fuzz_differential` (strengthened,
multi-seed) and `book1_fuzz` (three-engine, now incl. `2^32-1` budgets) all AGREE across seeds; the
sigma governance store verifies settlement-grade 48 records 0/0.
