# Adjudication — GPT-OSS 120B external audit (2026-07-17)

Raw: [`2026-07-gptoss120b-agy-audit.md`](2026-07-gptoss120b-agy-audit.md) (GPT-OSS 120B via `agy`,
inline). Second external round, a different model *family* from the Gemini pass, aimed at the newest
surface: the C1 Lean proof, the §8.3 negative battery, and the fuzzer changes.

## Dispositions

- **P0 / P1 — none.** The auditor independently confirmed the C1 mechanization is **sound and
  non-vacuous** (real properties, no hidden axioms beyond `propext`, faithful A-2/A-3 order, the bridge
  ties model to oracle), and that the §8.3 negatives are correctly implemented in both impls. This is a
  clean bill on the two things I most wanted a second pair of eyes on (is the proof real, is the
  blocklist right).
- **P2 — negative-battery coverage gaps.** Partially real:
  - **wrong-length public keys** (a `len ≠ 32` key MUST fail verification) were not pinned. **Added**
    (`00`, `00×31`, `00×33`). Adding them immediately **caught a real panic** in my own conformance
    harness — `k[:12]` on a 2-hex key overflowed in Go (Python slicing is safe). Fixed with `sh12`
    (the same panic-safe helper from the Gemini round; my earlier fix hadn't covered this newly-added
    harness code). Exactly the value of widening the battery.
  - **missing `warrant` / `decision` top-level fields** — **added** for completeness (validate already
    checks all missing fields uniformly; one was tested, now three).
  - "syntactic JSON errors" — already covered by `tests/hostile.py` (malformed-JSON records → bounded
    ERR) and pointed there by §8.3; not a body-validation vector, so left in the harness layer.
  - "high-order-bits-cleared weak-key class" — vague and not a distinct class beyond the 8 torsion
    points + `y ≥ p`; not actioned.
- **P3 — roadmap comment in the Lean file.** Not actioned; the file is self-documenting and the
  roadmap lives in `ARCHITECT.md`.

## Net

A no-P0/P1 audit that still paid for itself: the coverage it prompted exposed a panic in the conformance
harness I'd just written. Two independent external models (Gemini 3.1 Pro, GPT-OSS 120B) now agree the
core hardening holds; the recurring lesson is that short-string slicing in Go is a standing panic
hazard — every new display path must go through `sh12`.

## Evidence
Both `conformance` commands 45/45; hostile/negative/fuzz green.
