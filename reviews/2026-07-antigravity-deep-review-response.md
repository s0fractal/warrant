# Adjudication — Antigravity deep review (2026-07-18)

Raw: [`2026-07-antigravity-deep-review.md`](2026-07-antigravity-deep-review.md) (Antigravity/Gemini
agentic deep review of SPEC + all three implementations). Overall a strong positive assessment; three
concrete items, each checked and dispositioned.

## Dispositions

- **§2.3 unused `mut` on `c0` in `fe_mul` (the reviewer applied the edit).** VERIFIED and kept: `c0` is
  read-only after initialization, so `mut` was indeed unnecessary; the diff is a one-token cleanup.
  Confirmed it does not touch behavior — `cargo build --release` is now **0 warnings**, and the crypto
  is unchanged: `edtest` PASS, Rust conformance 36/36, Ed25519 differential green, three-way canon
  differential green. (An external agent edited the source; I re-verified it rather than trusting the
  description.)
- **§2.1 Unicode NFC normalization.** Investigated, **documented as a deliberate choice, not a bug.**
  Empirically the three implementations already agree byte-exact on both NFC and NFD forms of a string
  (none normalizes), so there is **no cross-implementation divergence**; NFC and NFD produce *different*
  WarrantIDs, which is correct for a content-addressed system (different bytes → different identity). A
  MUST-normalize/MUST-reject-non-NFC rule would force a full Unicode normalization database into every
  implementation — including the from-scratch Rust and Go paths — and would reject legitimate content,
  which is disproportionate. **SPEC §4 now states explicitly** that strings are hashed as exact code
  points, verifiers MUST NOT normalize or reject on normalization form, and PRODUCERS SHOULD emit NFC to
  avoid *external* mangling (a producer discipline, since such mangling breaks any hash-addressed format
  and is outside this spec's boundary). Locked with `nfc-precomposed` / `nfd-decomposed` cases in the
  three-way `tests/differential.py`.
- **§2.2 `cmd@v1` non-determinism / local-trust.** Already satisfied: SPEC §3.1 already says
  "`cmd@v1` proves a claim to whoever trusts the container; `ski@v1` proves it to anyone with the
  blobs … tools SHOULD treat `ski@v1` as the strongest reason kind: re-runnable without trust." No
  change needed; the reviewer's recommendation is the existing normative text.

## Roadmap (noted, not actioned)
§3.2 — more `ski@v1` conformance vectors beyond the single TV-10 fixture (ATP-limit boundary behavior).
Reasonable; a follow-up. The `ski_policy` suite and the Σ-GLYPH `book1_fuzz` three-engine differential
already exercise the evaluator broadly, but dedicated warrant-side `ski@v1` boundary vectors would
tighten the runtime's own conformance surface.

## Evidence
Three-way canon differential 45/45 (adds NFC/NFD); Rust build 0 warnings; edtest + all three
conformance + full suite green.
