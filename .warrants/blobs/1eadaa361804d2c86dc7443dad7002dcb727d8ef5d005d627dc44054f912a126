# Adjudication — Gemini 3.1 Pro Ed25519 crypto audit (2026-07-17)

Raw: [`2026-07-gemini31pro-ed25519-audit.md`](2026-07-gemini31pro-ed25519-audit.md). Third external
round, targeting the highest-risk new artifact: the from-scratch Ed25519 verifier in `impl-rs/`
(SHA-512 + 2^255-19 field + Edwards curve, written in one session). It found **two real P0s** the
RFC-TV1 + 452-case differential had not caught — exactly why from-scratch crypto must be audited.

## Dispositions

- **P0 — `pt_decompress` accepts the non-canonical identity encoding `0100..0080`.** CONFIRMED. The
  `x == fe_zero()` **strict array** compare missed an *unreduced* zero (`u = y²-1` came out as `p` in
  limbs, not `[0;5]`), so the `x=0 ∧ sign=1` rejection was bypassed and a non-canonical `R` a reference
  rejects would decompress. **Fixed:** `fe_eq(&x, &fe_zero())` (reduces before comparing). Verified:
  RS now rejects it, agreeing with Python (`rs=false py=false`).
- **P0 — `verify` used the unreduced 512-bit hash as the scalar, diverging from RFC 8032 on
  mixed-torsion keys.** CONFIRMED (this was the documented shortcut). For `A = A0 + T8` (passes the
  weak-key blocklist, which only blocks *pure* small-order points), `[H]A ≠ [H mod L]A` because
  `L ≡ 5 (mod 8)`. **Fixed:** added `mod_l` (bit-by-bit 512-bit reduction mod L) and reduce the
  challenge before `[k]A`; `verify` is now the exact RFC cofactorless equation for **every** key.
  Verified: `mod_l` matches the reference on `(2^512-1) mod L`, and a new **20-case mixed-torsion
  differential** (build `A0 + T8`, compare RS vs Python) agrees.
- **P2 — `fe_mul` left `r1` unmasked.** Benign (bounded, u128 headroom) but fixed: mask `r1`, carry
  into `r2`, so every output limb is `< 2^51`.
- **P3 — bit-by-bit `fe_to_bytes`.** Left as-is; it is called once per point and correctness beats the
  micro-optimization here.

The auditor ruled out (with stated reasoning) field overflow, wrong sqrt/invert addition chains, and
`pt_add` unification failure — matching my own overflow analysis.

## Validation after fixes
`edtest` (RFC 8032 TV1 + field + SHA-512 + both P0 regressions) ALL PASS; all three §8 signatures still
verify; the Ed25519 differential vs Python is **472/472** (200 keypairs × valid/tampered/wrong-msg +
small-order + 20 mixed-torsion); three-way canon differential 43/43; full suite green.

## Lesson
From-scratch crypto passing a large random differential is necessary but not sufficient — the bugs live
in the *canonicality* and *cofactor* edges that random legitimate inputs never hit. An adversarial
reader who reasons about the algebra (unreduced-zero equality; `L mod 8`) found both in minutes.
