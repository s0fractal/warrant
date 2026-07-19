# Adjudication — Kimi K3 full audit: verifier totality (2026-07-18)

Raw: [`2026-07-kimi-full-audit.md`](2026-07-kimi-full-audit.md). Kimi's multi-agent
run was interrupted before it wrote its review or filed a fix; the finding was
recovered from the session wire transcript, **re-confirmed independently against
HEAD `707b2c9`**, and fixed here. This is the same *verifier-totality* class as the
Gemini 3.1 Pro round, on the one code path that pass had not reached:
`verify_store`'s post-schema semantic block.

## Root cause

`verify_store` reports `validate_body` errors and then **continues** into a
semantic/DAG block that assumes well-*typed* `prior` / `under` / `evidence` /
`because` / `subject` / `actor`. A schema-invalid record can type-confuse those
fields, so the dereference raised an uncaught `TypeError`/`KeyError`. Because the
exception propagates out of the whole-store loop, one malformed record aborted
verification of every other record — an **availability** failure, not only a
PY/GO divergence.

## Dispositions

- **P1 — type-confused bodies crash the verifier.** CONFIRMED (10 shapes,
  incl. `actor:"x"`+valid-sig). **Fixed** with type-guards that are *transparent
  to well-typed input* (so the fuzzer's well-typed mutations still flow through
  and PY/GO counts stay identical), and skip only the report fragments a wrong
  *type* makes meaningless:
  - `for p in body["prior"]` → iterate only if `prior` is a list of `str`;
  - `blob_refs` → guard `under`/`evidence` are lists, `because` entries are dicts,
    each ref is a `str`;
  - `subject` → dereference `.hash` only when `subject` is a dict with a str hash;
  - the actor-signed check → precompute `body_actor_id` defensively;
  - `is_unverifiable(body)` → made shape-defensive at its own definition (it is
    also called from `why`/`cmd`).
  The schema `ERR` still fires; the record simply no longer crashes the run.
  A **blanket `continue`-on-schema-error was tried first and rejected** — it
  suppressed the `unresolved blob` warnings a *well-typed-but-bad-value* record
  (e.g. a wrong-length hash) legitimately earns, which broke `fuzz_differential`
  (`m_badhash` → PY `(4,3)` vs GO `(4,4)`). The type-guarded version keeps PY/GO
  in lockstep: **fuzz 450/450, three-way differential 45/45.**

- **P1 availability — one bad record aborts the store.** CONFIRMED and **fixed**
  as a consequence of the above (no exception escapes the loop). Regression:
  `tests/hostile.py` now asserts a good+hostile store reports **both** records.

- **P2 — settlement KeyError on a schema-invalid ancestor.** CONFIRMED. **Fixed:**
  `rotation()` is now shape-defensive — a malformed ancestor (`env["body"]` not a
  dict, or missing `decision`/`subject.hash`) simply carries **no rotation**
  instead of raising, matching the already-defensive `record_roots`.

- **P2 — `why` RecursionError on a deep linear chain.** CONFIRMED. **Fixed:**
  `why()` rewritten as an **iterative** pre-order DAG walk (explicit stack, same
  indentation and `(cycle)` output, plus a `WHY_MAX_DEPTH` guard). The recursion
  limit no longer bounds how deep a legitimate chain may be.

## Verification

- All ten type-confusion shapes + the availability case + `why` on a 1600-deep
  chain: **0 crashes**, every one a bounded report.
- Regression locked in `tests/hostile.py` (18 new checks: `totality <shape>`,
  `totality availability`, `totality why(deep linear chain)`) — **HOSTILE: ALL PASS.**
- Full battery unchanged: conformance PY/GO/RS `ALL PASS (45/45)`,
  `fuzz_differential 450/450`, `ed25519_differential 622/622`, three-way
  `differential 45/45`, negative/settlement/pedantic/anchor/ski_policy/
  evidence_pack/mcp_seal all green.

## Files

- `impl/warrant.py` — `verify_store` semantic block type-guards; defensive
  `body_actor_id`; shape-defensive `is_unverifiable`; shape-defensive settlement
  `rotation()`; iterative `why()` + `WHY_MAX_DEPTH`.
- `tests/hostile.py` — totality / availability / deep-`why` regression block.
