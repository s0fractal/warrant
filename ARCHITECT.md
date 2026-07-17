# Architecture roadmap — Warrant

Living document for driving Warrant to world-class engineering and academic
rigor. Companion to `SPEC.md` (the contract). Sibling repo: `sigma-glyph`
(Book I is Warrant's `ski@v1` runtime; its `ARCHITECT.md` mirrors this).

## Definition of "world-class" (the bar we measure against)

1. **Every normative claim is backed by an executable vector or a machine
   proof** — not prose alone. Prose that no test pins is a liability.
2. **Every consensus invariant is held by ≥2 independent implementations AND a
   differential fuzzer** — curated vectors catch known splits; the fuzzer
   catches the ones we didn't think of.
3. **Every bug class we ever fixed by hand becomes an automatic gate** so it
   cannot regress (uint-narrowing, small-order keys, escaping, dup-keys,
   trailing content, verifier panics…).
4. **The verifier is total**: no input — however hostile — produces a crash,
   panic, hang, or unbounded work; only a bounded, deterministic report.

## Operating rhythm

`harden (bounded pass) → independent external audit (the acceptance oracle) →
adjudicate findings as warrants in .warrants/ → repeat`. "Done" for a round =
an external audit returns 0×P0/P1. Self-review is a substrate, never the gate.

## Backlog (ranked; status)

| id | item | done-criterion | status |
|----|------|----------------|--------|
| W2 | Differential **fuzzer** PY↔GO over canon + verify + dirty-input reject | CI gate, multi-seed, 0 divergences | **done** (`tests/fuzz_differential.py`, in CI) |
| W1 | Ed25519 residual → normative: SPEC §5 small-order MUST + §8.3 negative conformance vector | §8.3 vector gates a 3rd implementer | **done** |
| W4 | §8.3 negative battery (weak-key + schema-invalid) checked by both `conformance` commands; parse-layer rejections (dup-key/trailing/canonicality) referenced to the cross-impl harnesses | `examples/conformance-negatives.json`, both impls 40/40 | **done** |
| W3 | Third independent implementation (**Rust**) of the verifier, mirroring sigma's discipline | byte-exact on §8 + differential | **done** (canon/schema/WarrantID/weak-key **+ from-scratch Ed25519**; verifies all three §8 signatures; 3-way canon differential 43/43; Ed25519 differential vs Python 452/452; no external crates) |
| X1 | Combined CI: Book III / sigma store verified by the live warrant CLI, so cross-repo coupling regressions surface | CI job across both repos | todo |

**Explicitly NOT doing** (anti-gold-plating): new features, marketing, elegance
rewrites, or spec prose without a vector behind it.

## Progress log

- **2026-07-17 — external audit round 3 (Gemini 3.1 Pro, Ed25519 crypto).**
  Targeted the from-scratch Rust Ed25519. Found **two real P0s** the RFC-TV1 +
  452-case differential missed: `pt_decompress` accepted the non-canonical
  identity `0100..0080` (strict array `==` missed an unreduced zero -> use
  `fe_eq`), and `verify` used the unreduced 512-bit hash as scalar, diverging
  from RFC on mixed-torsion keys (`A=A0+T8`) -> added `mod_l` and reduce k mod L.
  Plus a benign P2 (`fe_mul` r1 mask). Re-validated: `edtest` PASS, §8 sigs
  verify, Ed25519 differential now 472/472 incl. 20 mixed-torsion cases. See
  `reviews/2026-07-gemini31pro-ed25519-audit{,-response}.md`. Lesson: a random
  differential can't reach the canonicality/cofactor edges; adversarial algebra
  can. **Three external models across three rounds now back the codebase.**
- **2026-07-17 — W3 increment 2 (from-scratch Ed25519 in Rust) — W3 COMPLETE.**
  `impl-rs/src/ed25519.rs`: SHA-512, the 5×51-bit field mod 2^255-19 (mul/sq/
  invert/sqrt), extended-coordinate Edwards points (add/double/scalarmul),
  point decompression, and RFC 8032 verification — all from scratch, no crates.
  Validated three ways: the RFC 8032 official test vector 1; **all three §8
  warrant signatures verify** (agreeing with PY/GO on the real pinned sigs);
  and a **452-case differential vs Python `cryptography`** (200 keypairs ×
  valid/tampered/wrong-message + small-order rejection), 0 divergences. `verify`
  uses the full 512-bit SHA-512 output as the scalar for [H]A (valid for a
  legitimate order-L key), avoiding a separate mod-L reduction; small-order and
  non-canonical keys are pre-rejected by the weak-key blocklist + the S<L check.
  `warrant-rs` is now a full third verifier of the canon/schema/WarrantID/
  weak-key/signature layer. CI runs the selftest + the Ed25519 differential.
- **2026-07-17 — W3 increment 1 (Rust third implementation).** `impl-rs/`
  (`warrant-rs`, from scratch, no external crates — mirrors sigma's Rust
  discipline) implements the layer where consensus-split bugs live: a from-scratch
  SHA-256, an I-JSON parser (rejecting duplicate keys, trailing content, raw
  control bytes, and — added this pass — decoding UTF-16 surrogate pairs), JCS
  canonicalization, schema validation, and the weak-Ed25519 blocklist. It
  recomputes all three §8 WarrantIDs byte-exact and passes the §8.3 negatives
  (`conformance` 33/33), and `tests/differential.py` is now **three-way
  (PY/GO/RS), 43/43** across the adversarial escaping/unicode battery. CI builds
  it and runs both. Ed25519 signature verification (SHA-512 + curve, from
  scratch) is increment 2.
- **2026-07-17 — external audit round 2 (GPT-OSS 120B via `agy`).** Different
  model family; targeted the newest surface (C1 Lean proof, §8.3 negatives).
  **No P0/P1** — independently confirmed the C1 proof is sound/non-vacuous
  (propext-only, faithful A-2/A-3) and the negatives are correctly implemented.
  One real P2: wrong-length pubkeys weren't pinned — adding them **caught a panic
  in my own conformance harness** (`k[:12]` on a short key, Go), fixed with
  `sh12`. Battery now 45/45 both impls. See
  `reviews/2026-07-gptoss120b-agy-audit{,-response}.md`.
- **2026-07-17 — W1 + W4 shipped (normative negatives).** `examples/conformance-negatives.json`
  is a machine-readable §8.3 battery every implementation MUST reject: 11 weak
  Ed25519 keys (signature verification must fail) + 9 schema-invalid bodies
  (validate must error). Both `conformance` commands load and check it (now
  40/40 each). SPEC §5 upgrades the small-order rejection from "known residual"
  to a normative MUST tied to that vector; §8.3 documents the battery and points
  parse-layer rejections (dup-key/trailing/canonicality) at the cross-impl
  harnesses. Closes the "prose without a vector" gap for the recent crypto/schema
  hardening.
- **2026-07-17 — external audit round (Gemini 3.1 Pro via `agy`).** First external
  acceptance-gate pass. It found real defects the fuzzers had blind spots to:
  a Python verifier crash on a non-object signature entry (`s.get` on a str), a
  Python `RecursionError` crash on deeply-nested JSON (Go was bounded), and a
  **fuzzer-soundness** gap — Loop C's `!=` invariant hid a *shared* accept of a
  malformed record (and caught a no-op `exp_num` mutation once strengthened).
  All fixed; Loop C now requires both-reject; `book1_fuzz` now sends `2^32-1`
  budgets; new hostile.py regressions. Three other findings (ATP `force` wrap,
  2 missing blocklist keys, scalar-record crash) were refuted empirically; the
  2 keys were blocklisted anyway as defense-in-depth. See
  `reviews/2026-07-gemini31pro-agy-audit{,-response}.md`. Lesson recorded:
  external audit is the gate, self-review is the substrate.
- **2026-07-17 (Fable 5, architect):** shipped **W2**. The fuzzer immediately
  found three real defects, all fixed the same pass:
  - GO `readJSON` silently ignored **trailing content** after the JSON value
    (Python rejected it) — a consensus split GOV-anchors 1.0.2 already forbids.
  - PY verifier **crashed** (`TypeError`) comparing a string `ts` on a
    prior-edge — the §6 ts check now runs only on integer `ts`.
  - GO verifier **panicked** (`slice bounds out of range`) formatting a short
    attacker-controlled hash — all display slices now go through `sh12`.
  Full suite + fuzzer (1800+ checks/seed, multiple seeds) green.
