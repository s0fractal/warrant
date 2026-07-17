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
| W1 | Ed25519 residual → normative: SPEC §5 blocklist + §8 conformance vector; version/CHANGELOG note for the co-sig + weak-key behavioral changes | §8 vector gates a 3rd implementer | todo |
| W4 | §8 vectors for escaping / dup-key / trailing-content / weak-key (today only in tests, not normative vectors) | vectors pinned in SPEC §8 | todo |
| W3 | Third independent implementation (**Rust**) of the verifier, mirroring sigma's discipline | byte-exact on §8 + differential + fuzzer | todo (multi-session) |
| X1 | Combined CI: Book III / sigma store verified by the live warrant CLI, so cross-repo coupling regressions surface | CI job across both repos | todo |

**Explicitly NOT doing** (anti-gold-plating): new features, marketing, elegance
rewrites, or spec prose without a vector behind it.

## Progress log

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
