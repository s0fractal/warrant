# Kimi K3 — independent adversarial item-0 gate (2026-07-27)

Reviewer: **Kimi K3** (local CLI, high effort), run autonomously with read-only
access to both repos on branches `wrt-001-item0-candidate` / `adr-008-rev15-candidate`.
Prompt explicitly forbade rubber-stamping (running the green suites) and required
hunting NEW reproducible counter-vectors. Verdict: **ITEM-0 GATE: AMEND**.

> Triage (Claude, 2026-07-27): every P1 below is in verifier code **byte-identical
> to `origin/master`** (git diff shows 0 changed lines in the implicated symbols;
> the genesis-as-dir crash exists in the pre-item-0 `_trust_roots` too). So these
> are **pre-existing latent verifier bugs, NOT item-0 regressions** — but the item-0
> contract text over-claimed verifier-wide parity/crash-freedom, which this gate
> correctly refuted. Disposition: narrow the item-0 contract to its actual scope
> (trust/genesis *config* parsing + single-snapshot + runtime view), fix the one
> in-scope item (genesis.json-as-directory), and route the rest to the ongoing
> verifier-hardening track (the Kimi full-audit line).

---

  # ITEM-0 ADVERSARIAL GATE — 2026-07-26

  Branches reviewed: warrant `wrt-001-item0-candidate`, sigma-glyph `adr-008-rev15-candidate`. Baselines: `warrant.py selftest`, `warrant-go selftest`, `tests/differential.py` (45/45), and the sigma join probe all green — and all findings below are **new**, none is in the "already covered" list.

  ## P1 — crash / consensus splits

  ### P1-1. Go stack-overflow crash: prior-cycle + key rotation (settlement)
  Store: trusted root `R`; record `A` (filename `11…11`): `decision=accept`, `subject.hash` = canonical `{"actor","key"}` key blob, `prior=[B]`, self-proof sig over the filename wid; record `B` (filename `22…22`): `prior=[A, R]`. The cycle puts `A` in `ancestors(A)`.
  - PY: bounded — `verify: 3 records, 2 errors, 1 warnings`, rc=1 (its `rotation_auth_cache[wid]=False` pre-seed breaks the recursion).
  - GO: `runtime: goroutine stack exceeds 1000000000-byte limit / fatal error: stack overflow`, rc=2, **no report at all**. `rotationAuthorized(A) → keysBefore(A) → rotationAuthorized(A)` has no memo.
  - Breaks: identical public report; one crafted store kills the Go verifier (availability). Note both impls' settlement ctx trust filename wids without checking `warrant_id(body) == filename`, which is what makes the cycle constructible.

  ### P1-2. Python traceback: `blobs/<hash>` is a directory (settlement)
  `under=["aa"*32]` where `blobs/aa…aa/` is a directory; valid signed record.
  - PY settlement: uncaught `IsADirectoryError` traceback (`_parse_policy_blob` → `read_bytes()`), no report. Same crash via a `ski@v1` check blob naming a directory (`run_ski_check` `read_bytes()` is outside the `except RuntimeError`).
  - GO: `verify: 1 records, 0 errors, 3 warnings`, rc=0.
  - Breaks: "bounded report, never a traceback"; parity. Base mode also diverges on the same store: PY `has_blob(dir)=True` suppresses the unresolved-blob WARN (PY 1 warn, GO 2).

  ### P1-3. Python traceback: `genesis.json` is a directory (settlement, pinned trust)
  - PY: uncaught `IsADirectoryError` in `_trust_roots` (`g.read_bytes()`), no report.
  - GO: proceeds silently — `ReadFile` error is swallowed by `if err == nil`, so **not even** `WARN genesis.json unverified`.
  - Breaks contract 3 verbatim ("bounded no-op, never a Python traceback") and contract 4.

  ### P1-4. Python traceback: lone surrogate in a body string
  Record file with `"actor": {"id": "\ud800evil"}` (legal JSON escape; Python decodes to a lone surrogate, and the body is **schema-valid** in PY).
  - PY: uncaught `UnicodeEncodeError: surrogates not allowed` in `canon()` at `warrant_id`, no report.
  - GO: bounded — `ERR WarrantID mismatch: recomputed 15c8815deb5b`, `1 records, 1 errors, 0 warnings`.
  - Breaks: crash + parity. Root cause: Go's decoder substitutes U+FFFD for unpaired surrogates; Python keeps them and `encode("utf-8")` later explodes. The strict I-JSON domain (contract 3) doesn't cover record files.

  ### P1-5. Canonicalization consensus split: `"ts": -0`
  Same record bytes (`"ts": -0`, filename = PY's wid):
  - PY: parses `-0`→`0`, canon `"ts":0` → `0 errors`, **rc=0**.
  - GO: `json.Number` keeps `"-0"`, `writeCanonical` emits `-0` → `ERR WarrantID mismatch`, **rc=1**.
  - Breaks: contract 4 on identical input; GO also violates RFC 8785 (JCS serializes -0 as `0`). Either wid choice leaves one implementation accepting a record the other rejects.

  ### P1-6. Store-shape detection: Go silently verifies nothing
  - Store with `records/` but **no `blobs/`**: PY reports `1 records, 0 errors, 3 warnings`; GO falls into flat-dir mode → `verify: 0 records, 0 errors, 0 warnings`, **rc=0** (a requested settlement verify reports a clean zero).
  - Store with `blobs/` but **no `records/`**: PY exits 1 (`no store at …`); GO again `0 records, 0 errors`, rc=0.
  - Breaks: contract 4 and the fail-closed spirit of contract 2 (Go's `storeMode = isDir(records) && isDir(blobs)` degrades to a mode that sees zero inputs).

  ## P1 — identical-summary (contract 4) count breaks

  ### P1-7. `sigs` not a list: PY 2 ERRs, GO 1
  `{"body": …, "sigs": "not-a-list"}` (wid matches): PY emits `sigs must be a list` **and** `no signatures` (it resets `sigs=[]` then re-tests), and continues the record; GO emits one ERR and `continue`s. `(1,2,0)` vs `(1,1,0)` base; `(1,2,1)` vs `(1,1,1)` settlement. Any dangling refs add a further PY-only WARN.

  ### P1-8. Sig entry without `actor` + type-confused body actor (settlement)
  `"actor": "x"` in body + a cryptographically valid sig entry `{"key","sig"}` with no `actor` field: PY `no valid signature by body.actor.id` (2 ERRs); GO's settlement path coerces both to `""`, `actor == actorID` → no ERR (1 ERR). Amusingly GO's *base* path compares the raw nil (`nil != ""`) and **does** ERR — Go disagrees with itself across modes; PY is consistent (2 ERRs both).

  ### P1-9. Schema-invalid `prior` scalar: GO invents a root
  `"prior": 5` (or `[5]`): PY treats it as no-root/no-edges; GO's `getStringArray` yields empty → marks the record a root → extra `WARN unadopted root` in settlement. `(1,2,0)` vs `(1,2,1)`.

  ### P1-10. int64 clamp flips the ts-edge WARN
  prev `ts=2^63` (schema-invalid bignum), child `ts=2^63-1`: PY compares bignums → `WARN ts decreases along prior edge`; GO's `getInt` (`strconv.ParseInt` clamps overflow to MaxInt64) compares equal → no WARN. Base `(2,3,1)` vs `(2,3,0)`; settlement likewise.

  ### P1-11. `has_blob` path traversal (PY)
  `"under": ["../records"]` (schema-invalid): PY `Store.has_blob` does a raw `Path.exists()` on the attacker string → resolves outside `blobs/` → WARN suppressed `(1,2,0)`; GO `(1,2,1)`. Besides parity, PY is a filesystem-existence oracle for arbitrary host paths.

  ## P2

  - **Message-string divergences** (counts equal, contract-4 "same strings" unmet): failed co-sig — PY `signature does not verify (excluded): actor mallory` vs GO `signature does not verify (excluded)`; non-dict sig entry — PY `signature entry is not an object (excluded)` vs GO `signature does not verify (excluded)`; PY prints `claims actor None` vs GO `claims actor ` (P1-8). Schema-error strings differ wholesale (`under must be a list of >=1 hex64 hashes` vs `… of hex64 hashes`, `unknown reason kind: 'x'` vs `"x"`, ts non-integer wording) — if contract 4 means strings literally, it's broadly unmet; likely intended scope is the stable named classes, worth a one-line clarification.
  - **`WARRANT_SKI_MAX_ATP=abc`**: PY crashes at import (`ValueError: invalid literal for int()`, no report, rc=1); GO ignores unparseable values and verifies clean (rc=0). (`-5` parses in PY → every ski check over-budget; GO rejects the sign → default — untested divergence with a valid ski blob.)

  ## Sigma side — R0 claim: verified, no new bug

  `resonant_precedent_join_probe.py` runs green. Beyond its own demo I attacked R0 (`verify_query`, raw eligibility) with four fresh lifecycle vectors: post-commit foreign supersede of the cited assertion AW, of the decision warrant D, and of the genesis root JUR — all return `unverified ("live-head effective set != view commitment")`, never a censored `pass`; an ill-signed foreign supersede of AW leaves the result byte-identical (`pass, coherence=32767`). The censorship formula (`effective_active`) is provably unused in R0; a well-signed post-commit supersede can only stale the query to `unverified` via generic universe growth — the explicitly named live-head behavior, fail-closed. Also tried: rival winning `select()` → `unverified`, not `fail`. Null result on Sigma.

  ## Verdict

  `ITEM-0 GATE: AMEND`

  P1 list: P1-1 Go recursion crash (prior-cycle+rotation); P1-2 PY crash on dir-as-blob (+base warn split); P1-3 PY crash on dir genesis.json (+GO silent skip); P1-4 PY crash on lone-surrogate body string; P1-5 `-0` canon/WarrantID split; P1-6 GO silent zero-report on half-shaped store; P1-7 sigs-non-list error count; P1-8 actorless-sig actorSigned split (GO self-inconsistent base vs settlement); P1-9 scalar-`prior` phantom root; P1-10 int64-clamp ts-edge WARN; P1-11 `has_blob` traversal/oracle. All reproducible from `/tmp/wgate` (harness + crafted stores); no repo files were modified.


