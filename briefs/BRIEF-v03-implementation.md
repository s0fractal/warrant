# Brief: SPEC v0.3 implementation gate

**For:** an implementation agent working in an isolated clone.
**Normative sources:** `SPEC.md` §5.1, §7, §9 (v0.3) — adopted from
`proposals/GOV-001-settlement-at-scale.md` rev 4 after a three-family
review gate. Where this brief and SPEC.md disagree, SPEC.md wins.
**Prime directive:** two implementations MUST agree on every WarrantID
and every verification outcome — including every new v0.3 outcome. Every
feature below lands with differential coverage or it doesn't land.

## Milestone A — Python reference (`impl/warrant.py`) + tests

### A1. Settlement analysis (`§7`)

- `tunnel(store, wid)` → `{records: set[WarrantID], blobs: set[hex64]}`
  per SPEC §7 (prior-closure records; cited-blob set; NO recursive blob
  parsing; blob-vs-WarrantID disambiguation).
- `fingerprint(reason, body)` → tuple per §7, or `None` if the reason
  lacks a required field (`transcript` for cmd@v1). ski@v1 fingerprint
  includes `result_node_hash` — obtained by re-running the check (oracle
  required; if the oracle is unavailable, the fingerprint is
  uncomputable and the reason contributes nothing).
- `tunnel_fingerprints(store, wid)` → set of computable fingerprints.
- New CLI verb: `warrant settle <settling-wid> <candidate-body.json>` →
  prints `admissible: (a) new evidence` / `admissible: (b) new outcome
  fingerprint` / `inadmissible: cites nothing new`, exit 0/0/1. Filing
  verbs gain `--relitigates <wid>`: tools MUST refuse to file when
  inadmissible (SPEC "Tools SHOULD refuse" — we choose MUST for our own
  CLI).
- `verify` gains: for every accept/reject whose prior chain contains a
  settlement of the same subject, flag
  `WARN: re-litigation cites nothing new` when neither (a) nor (b)
  holds.

### A2. Multi-root + genesis (`§9`)

- `verify --settlement` (new mode; plain `verify` behavior unchanged):
  - local trust configuration: `--genesis <wid>` (repeatable) and/or
    `--trust-config <file>` (JCS JSON
    `{"genesis_roots": [...], "genesis_json_sha256": "<hex64>"}`).
  - settlement-active set: configured genesis roots + policy-authorized
    adoptions (accept whose subject.hash is the adopted root's
    WarrantID, signatures satisfying the adopting root's threshold
    policy if any). Inactive roots: `WARN: unadopted root`, excluded
    from settlement/foreclosure calculations.
  - `genesis.json` handling: if present and its SHA-256 matches
    `genesis_json_sha256` from trust config → its roots join the
    genesis set; present but unpinned/mismatched →
    `WARN: genesis.json unverified`, contents unused.

### A3. Key state + thresholds (`§5.1`)

- Threshold policy parsing: blobs that are JCS-canonical JSON with
  `"warrant_policy": "0.3"`. Invalid threshold → records under it are
  settlement-inactive + `ERR: invalid threshold policy` (settlement
  mode only). Opaque blobs are never interpreted as policies.
- Key-state derivation (settlement mode): genesis keys from trust
  config (`{"actors": {"a@x": ["<pubkey>", ...]}}` in the same file);
  rotations = accepts whose subject is a key blob and which satisfy
  §5.1 authorization; revocations = supersedes of rotation warrants.
  DAG-order only; `ts` never extends/resurrects. Conflict = two
  authorized, mutually-unordered MAXIMAL key-state warrants for one
  actor → `WARN: key-state conflict` + that actor's key excluded from
  quorum counting (threshold reduced for resolution per §5.1).
- Signature reporting in settlement mode: `bound` / `unbound` per
  derived key state; plain mode keeps the v0.2 warning.

### A4. Tests

- Extend `tests/differential.py`: canon agreement is already covered;
  add nothing there unless a new canonical structure appears
  (trust-config files are local, not canonical artifacts).
- New `tests/settlement.py` (same style as `tests/negative.py`: build
  temp stores with the CLI, break things, compare BOTH implementations'
  settlement verdicts and warning/error counts):
  1. baseline: two-root store, one root configured genesis, other
     unadopted → WARN parity, exclusion parity.
  2. adoption with satisfied threshold → root becomes active in both.
  3. genesis.json pinned-hash match → roots used; tampered
     genesis.json → `WARN: genesis.json unverified` in both, unused.
  4. invalid threshold policy (min_sigs > len(actors); unknown field)
     → ERR parity, settlement-inactive.
  5. re-litigation: (a) new-evidence admissible; (b) new-fingerprint
     admissible (opposite-verdict ski check); restatement (same
     fingerprint, different check bytes) → inadmissible/WARN in both.
  6. key rotation happy path (quorum) → bound flips; stale-rotation
     replay on a fork → NO conflict (DAG-ordered, per SPEC); genuine
     fork conflict (two authorized maximal rotations) → WARN +
     exclusion + reduced-threshold resolution.

## Milestone B — Go parity (`impl-go/main.go`)

Same outcomes for every A1–A3 behavior exercised by `tests/settlement.py`
(the harness runs both). Go remains verify-only: it needs `verify
--settlement` (or `verify -settlement <store>` flag syntax consistent
with its CLI), `settle`, and the same trust-config file format. No
filing paths.

## Ground rules

- No body schema changes. No new envelope fields. v0.1/v0.2 records
  MUST verify exactly as before in plain mode (regression: existing
  selftest/conformance/differential/negative all stay green,
  byte-identical outputs).
- Warning/error STRINGS for new outcomes must be identical across
  implementations (the settlement harness compares them).
- Determinism: no wall-clock, no map-iteration-order leaks (sort
  everything you print).
- Keep `impl/warrant.py` single-file; keep Go stdlib-only.
- Write focused commits per milestone; do not touch SPEC.md,
  proposals/, reviews/, or .warrants/.

## Acceptance (the maintainer will run these cold)

```
python3 impl/warrant.py selftest && python3 impl/warrant.py conformance
./impl-go/warrant-go selftest && ./impl-go/warrant-go conformance
python3 tests/differential.py && python3 tests/negative.py
python3 tests/settlement.py        # new; ALL AGREE required
```

Plus adversarial spot-checks the maintainer will not disclose in
advance. Every claim in your handoff notes must be reproducible by
running a command you provide.
