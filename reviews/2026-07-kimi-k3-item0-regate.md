# Kimi K3 — re-gate of the verifier-hardening fixes (2026-07-27)

Reviewer: **Kimi K3** (local CLI), same reviewer as the original item-0 gate
(`2026-07-kimi-k3-item0-adversarial-gate.md`, which returned `AMEND` with 11 P1).
This is a RE-GATE of the fixes on branch `verifier-hardening-k3`, tasked to
(1) confirm each of the 11 P1 is actually fixed by re-running its counter-vector,
(2) attack the fix surfaces for regressions, (3) hunt adjacent surfaces.

## Result (as observed before the run hit the Kimi usage quota)

K3 rebuilt all 11 counter-vectors from scratch and diffed OLD (built from
`origin/master`) vs NEW (this branch) for Python and Go. Per-finding:

- **P1-1 FIXED** — OLD Go: `stack overflow`, rc 2, no report → NEW: `(3,2,1)`, GO == PY.
- **P1-2 FIXED** — OLD Py: settlement traceback → NEW: `(1,0,2)`/`(1,0,3)` parity.
- **P1-3 FIXED** — OLD Py: traceback; OLD Go: silent → NEW: `(1,0,3)` == `(1,0,3)`.
- **P1-4 FIXED** — OLD Py: `UnicodeEncodeError` → NEW: `(1,1,0)`/`(1,1,1)` parity (bounded).
- **P1-5 FIXED** — OLD **consensus split** (Py accepts rc 0 vs Go rejects rc 1 on
  identical bytes) → NEW: both accept, identical `(1,0,1)`/`(1,0,2)`.
- **P1-6 FIXED** (records/-without-blobs/ direction) — NEW both verify the records
  with unresolved refs, equal summary.
- **P1-7..P1-11 FIXED with parity** — sigs-non-list, actorless-sig, scalar-prior,
  int64-ts-edge, has_blob traversal all bounded and Python == Go.

K3 found **no new P1 introduced by the fixes**. It flagged **one residual**,
classified **P3** (not gate-blocking): P1-6b, the *other* direction — a dir with
`blobs/` but no `records/` — where Python said `no store` (rc 1) while Go
flat-moded to `(0,0,0)` rc 0. K3 noted this is pre-existing, not fix-introduced,
and that the security-relevant direction (a silent clean zero on a *real* store)
was fixed.

> Follow-up (Claude, 2026-07-27): P1-6b is now also fixed — a settlement verify
> requires `records/` in both implementations (matches Python's `Store.require`),
> vectored in `case_verifier_hardening_k3`. The flat/conformance path (a dir with
> neither subdir) is unchanged.

## Honesty note on completeness

The run **exhausted the Kimi billing-cycle quota** (HTTP 403) partway through
part 2/3, so it did **not** print a final `RE-GATE:` token and did **not** finish
every adjacent-surface probe it had queued (symlink-`genesis.json`, a fully-signed
acyclic rotation chain). What it *did* complete — re-running and confirming all 11
counter-vectors, and checking the big.Int-canon / storeMode / priorIsEmpty / rotation-
cache surfaces — is recorded above. The remaining probes, plus the acknowledged
message-string P2s, are the residual for a future pass when quota refreshes.

Raw session log: `scratchpad/kimi_regate.log` (this run was read-only; no repo
files were modified by K3).
