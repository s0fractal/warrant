# Adjudication — Kimi K3 spec review (2026-07-17)

Raw review: [`2026-07-kimi-k3-spec-review.md`](2026-07-kimi-k3-spec-review.md) (Kimi K3 via
OpenRouter; the model exhausted its token budget mid-analysis, so the notes cut off in §5.1 and
never produced a ranked summary — findings were extracted and each verified against both
implementations before disposition).

**Method.** Every finding was checked against `impl/warrant.py` (reference) and `impl-go/main.go`
(independent), and the confirmed cross-impl split was reproduced empirically before fixing. Baseline
was green; the suite is green again after the changes below, with new regression tests added for each
fixed behavior.

## Dispositions

| # | Finding (K3) | Verified verdict | Disposition |
|---|---|---|---|
| A | `verify` re-execution not in SPEC §6, and impls diverge on unexecutable `ski@v1` | **CONFIRMED live PY/GO split**: PY emitted `ski@v1 unverified` WARN, GO `continue`d silently (4 vs 3 warnings) | **Fixed (Go)** + SPEC §6(7) |
| B | Bad co-signature is fatal → griefing/availability | CONFIRMED (both: any bad sig ⇒ ERR); envelope is append-friendly so a junk co-sig invalidates a good record | **Fixed (both)** + SPEC §5/§6 |
| C | `atp` ceiling 2³² ⇒ verifier DoS on re-execution | CONFIRMED (both allowed up to `2³²−1` with no re-exec cap) | **Fixed (both)** + SPEC §3.1 |
| D | §6 lists "§5.1 rotation subjects" as WarrantID-resolvable, but §5.1 says rotation subject is a *key blob* | CONFIRMED doc contradiction | **Fixed** SPEC §6 |
| E1 | Unknown-field rule not stated as recursive (nested `subject`/`actor`/reason) | Impls already reject; SPEC silent → 3rd-impl split | **Fixed** SPEC §2 |
| E2 | `note ≤200 chars` — code points vs bytes | Impls agree (both code points); SPEC ambiguous | **Fixed** SPEC §2 |
| E3 | JCS escaping (`<>&`, `\b`/`\f`, U+2028/9, HTML-escape trap) | Impls agree (Go hand-rolls `quoteJSONString`); no §8 vector, but `tests/differential.py` covers it | **Fixed** SPEC §4 (normative escaping) |
| E4 | Duplicate keys / I-JSON not enforced | CONFIRMED both used stock last-wins parsers | **Fixed (both)** + SPEC §4 |
| E5 | Unknown `runtime` in 0.2 bodies | Impls already reject; SPEC implicit | **Fixed** SPEC §3 |
| F1 | Ed25519 acceptance rules unpinned (non-canonical S, small-order, cofactor) | Real cross-lib split risk (attacker-chosen key) | **SPEC §5** pins `S<L` + malformed-encoding rejection; cofactor/small-order flagged as **known residual** (deferred hardening) |
| F2 | `ski@v1` bound to Σ-GLYPH Book I v0.5 by mutable GitHub URL | Supply-chain/governance risk | **Fixed** SPEC §3.1 (MUST pin by version+content; bundled oracle normative) |

## Code changes (both implementations, behavior kept byte-identical)

- **A — `ski@v1 unverified` is never silent.** Go `verifyDir`/`verifyDirSettlement` now emit
  `WARN ski@v1 unverified: <reason>` when a check can't be re-executed, matching Python, and escalate
  to ERR under settlement when the reason is in a settlement-active record. Closes the confirmed
  4-vs-3-warning split.
- **B — co-signature exclusion.** A signature that fails to verify is now a WARN and is excluded;
  the record errs only if no *valid* signature by `body.actor.id` remains. A lone junk co-sig can no
  longer grief an otherwise-valid record into failing. `impl/warrant.py` `verify_store`;
  `impl-go/main.go` both verify paths.
- **C — re-execution budget.** `SKI_REEXEC_MAX_ATP` / `skiReexecMaxATP` default **100,000,000**
  (env-overridable, identical default in both). Over-budget checks are reported unverified, never
  evaluated (no hang), never a verdict.
- **E4 — duplicate keys rejected.** Python `loads_ijson` (`object_pairs_hook`) on record/candidate
  ingestion; Go `jsonHasDupKeys` token-scanner in `readJSON`. A dup-key object is now malformed in
  both, not last-wins. (Schema blobs were already dup-safe via the `canon(doc)==raw` check.)

## SPEC changes

§2 recursive unknown-field rule + code-point string lengths · §3 unknown-runtime MUST-reject ·
§3.1 pin Book I by version+content, re-execution budget · §4 normative escaping rules + UTF-16 key
ordering note + duplicate-name rejection · §5 Ed25519 acceptance (S<L, malformed encodings) +
co-signature exclusion · §6 individual signature verification, rotation-subject-is-a-blob correction,
new step (7) `ski@v1` re-execution + severity model.

## Flagged for maintainer ratification

**Finding B is the one security-semantics change** (an invalid co-signature goes from ERR to WARN).
It is correct and closes a real griefing vector, but it changes a verification *outcome*, so it should
be ratified by the maintainer — ideally filed as an adjudication warrant in `.warrants/` (signing key
is off-box; not done here).

## Deferred (documented, not yet coded)

- **F1 cofactor/small-order Ed25519**: pinning `S<L` + encoding checks in SPEC is done; a differential
  vector with an attacker-chosen small-order key, and a decision on strict-cofactorless enforcement in
  both libraries, is a follow-up hardening pass.
- **§8 escaping conformance vector**: `tests/differential.py` already exercises the escaping/length
  battery across both impls; a pinned §8 vector for third implementers is a nice-to-have, not added
  here (would require regenerating signed example hashes).

## Test evidence

Green after changes: PY+GO conformance 20/20, selftest, `differential` (43/43), `negative`,
`hostile` (incl. new co-sig / over-budget-atp / dup-key / ski-agreement cases), `settlement`,
`pedantic_edges` (15/15), `anchor`, `evidence_pack`, `mcp_seal`, `ski_policy`.
New regressions: `tests/negative.py` (junk co-sig non-fatal; only-invalid-sig still errors);
`tests/hostile.py` (PY/GO agree on missing-ski-blob; over-budget atp unverified & not evaluated;
duplicate-key record bounded-ERR in both).
