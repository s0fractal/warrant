# Kimi K3 full audit-review — verifier totality (recovered)

**Model:** Kimi K3 (Kimi Code CLI, `thinkingEffort: max`), multi-agent run
`session_ccff46ce-a2b2-49fd-9e4d-adbe5556b68d`, 2026-07-18.
**Status of the source run:** *interrupted.* Kimi ran the full test battery
(conformance PY/GO/RS, ed25519 differential 622/622, fuzz 450/450, the whole
`tests/` suite, the CLI smoke cycle, and the air-canada EVIDENCE-PACK contract —
all green), read `impl/warrant.py` end to end, then hand-crafted a battery of
type-confused hostile records and confirmed a class of crashes. The session was
cut off **before it wrote this review or filed any fix** — this file recovers the
finding from the session wire transcript; the confirmation and dispositions are
in the companion `-response.md`.

## (A) VERDICT

The spec, the crypto, and every existing vector are sound. But the reference
verifier `verify_store` is **not total**: after it reports a body's schema
errors it keeps going and dereferences the very fields it just flagged as
wrong-*typed*. On a type-confused record (`prior: 5`, `subject: "x"`, …) that
raises an uncaught `TypeError`/`KeyError` — where the Go implementation returns a
bounded report. Worse, because the crash aborts the whole run, **a single
malformed record denies verification of every other record in the store** — an
availability vector, not just a cosmetic divergence.

This is the same *verifier-totality* class the Gemini 3.1 Pro audit targeted
(non-object sig entry; deep-nesting `RecursionError`), but a distinct code path:
those were fixed at the parse/sig boundary; `verify_store`'s **post-schema
semantic block** was never made defensive.

## (B) FINDINGS

**P1 — `verify_store` crashes on type-confused bodies (PY diverges from GO; store-wide availability).**
*Location:* `impl/warrant.py`, `verify_store` semantic block (the `for p in
body["prior"]`, `list(body["under"])`, `body["because"]`, `body["subject"]["hash"]`
accesses that follow the `validate_body` error report).
*Concrete inputs* (each a single record in an otherwise-empty store; Python
raises, Go prints `verify: 1 records, 2 errors, N warnings`):

| body mutation        | Python (before)                              |
|----------------------|----------------------------------------------|
| `prior: 5`           | `TypeError: 'int' object is not iterable`     |
| `prior: [5]`         | `TypeError: 'int' object is not subscriptable`|
| `under: 5`           | `TypeError: 'int' object is not iterable`     |
| `evidence: 5`        | `TypeError: 'int' object is not iterable`     |
| `because: {}`        | `AttributeError` / non-list iteration         |
| `subject: "x"`       | `TypeError: string indices must be integers`  |
| `actor: "x"` + a valid signature | `TypeError: string indices …` (reached via the actor-signed check) |

**P1 (availability sub-case) — one hostile record aborts the whole store.**
A store with one well-formed signed record **and** one `prior: 5` record:
Python emits two report lines, then dies with `TypeError` — the good record is
never adjudicated. Go reports both. A store is multi-writer (co-signatures may be
appended by anyone with write access, per SPEC §5/§6), so a single griefing
record must not be able to deny verification of the set.

**P2 — settlement: an active record with a schema-invalid *ancestor* crashes.**
*Location:* `_settlement_context.rotation()` — `env["body"]["decision"]`.
An active record whose prior-closure contains a body missing `"decision"` raises
`KeyError: 'decision'` in Python; Go returns a bounded report. `rotation()` is
called for **every** ancestor in a closure, so a malformed ancestor anywhere
poisons settlement of its descendants.

**P2 — `why` on a deep linear prior-chain raises `RecursionError`.**
*Location:* `why()` — recursive over `body["prior"]`. `seen` cuts cycles but a
1500-deep *acyclic* chain exhausts Python's call stack. `why` on hostile input
should print a bounded tree, not crash.

## (C) NOT bugs (checked, holds)

- Conformance PY/GO/RS, ed25519 differential, fuzz differential, three-way
  `differential.py`, negative/settlement/pedantic/hostile/anchor/ski_policy,
  evidence_pack, mcp_seal — all green at HEAD `707b2c9`.
- The CLI cycle (init → keygen → blob add → propose → verify) and the
  air-canada EVIDENCE-PACK contract (base verify 0 errors; settlement-grade with
  keyring 0 warnings; `check` re-executes to the stated `expect`) both hold.
- SPEC §2–§8: the earlier Kimi-K3 spec findings (recursive unknown fields,
  code-point lengths, atp cap, rotation subjects, JCS escaping, dup keys,
  unknown runtime) are all present in the text.
