# WRT-012 e2e-001 — one stream, one real timestamp, a same-custody holder, three freshness controls

2026-09-10, branch `wrt-012-ownerless-root`, tool `tools/witness.py`, harness `tests/witness.py` (49/49, five mutants killed).
Protocol predeclared in `protocol.json` (sha256 in `results.json`) before any step ran. Zero model calls.

## What ran

| Step | Result |
|---|---|
| C1 = commitment to the deposited flagship PDF `da2f5506…` under verifier closure `ddde1fcd…` (`check_claims.py`) | `402f1a6b…`, sequence 0, canonical bytes re-hash to the digest (E1) |
| `ots stamp` of C1: one digest to the public calendars | initial receipt `b08f9557…`; classify = `FILE_BOUND_PENDING`, four calendars pending, `time_verified: false`; the same receipt against C1+1 byte is refused `OTS_FILE_DIGEST` (E2) |
| same-host holder receives C1 and signs a receipt in its own store | holding `EXTERNALLY_OBSERVED(same-host-holder, custody github:s0fractal)` (E3) |
| report before any run | `verification: method=EXTERNAL_CLOSURE result=NOT_RUN` (E4) |
| `run-verifier`: `check_claims.py --ref d83984f`, script bytes must hash to the closure | `result=PASS`, scope named; every other axis byte-identical between report-1 and report-2; proof inputs identical (E4b) |
| C2 = commitment to WRT-012 rev 3 text, prev = C1 | `1d158cb9…`, sequence 1 |
| Control A: local stream truncated at C1, holder snapshot taken before C2 | `freshness: UNKNOWN`, notes empty (E5A) |
| Control B: same truncated stream, live holder store holding C2 | `LATER_STATE_WITNESSED(same-host-holder, path 402f1a6b→1d158cb9, steps 1)` (E5B) |
| Control C: a branch on the same stream (different subjects), sequence 1, no path to C1, held by a second same-host holder | `UNKNOWN`, note `DISCONNECTED (sequence_reached_without_meeting_local)`, no `PATH_INCOMPLETE` (E5C) |
| External half | **`NOT_DEMONSTRATED`**: both holders are on this host under custody `github:s0fractal` (E6) |

All nine endpoints met. `results.json` carries expected vs observed per endpoint; `SHA256SUMS` (written by the driver) covers every run artifact; this REPORT.md was written afterwards and is outside it.

## What this establishes

- The three objects stay apart in practice: the commitment bytes contain nothing about proofs; the `.ots` is about the commitment bytes and nothing else; the report is recomputed from commitment + proofs + the verifier's holder configuration and was reproduced byte-identical on resume.
- Freshness runs in one direction and only along a verified `prev` path. An always-`UNKNOWN` implementation fails control B; a `sequence`-trusting implementation fails control C (both are also killed as mutants in `tests/witness.py`).
- A pinned verifier closure names code, not an outcome: `NOT_RUN` until the run happened, `PASS` after, and the other axes did not move.

## What this does not establish

- **No separation of control was demonstrated.** Both holders are the committer's own host and account. The mechanics work; the property WRT-012 is for has not been shown. That is why the external half is `NOT_DEMONSTRATED` and §5 (spread to the four repos) stays closed.
- **No time was verified.** `FILE_BOUND_PENDING` is a calendar promise. A later `upgrade` on a copy may yield `BLOCK_ATTESTATION_PRESENT_UNVERIFIED`; `BITCOIN_VERIFIED` needs a named chain-header source this tool does not have and never emits.
- **No latest-head discovery.** Control B found C2 only because the verifier's configuration pointed at a store that held it.
- **No calendar authenticity.** The four calendar URLs are reported, never fetched by `report`.

## Resume note (honest record)

The first attempt ran on `master`, where the C2 subject file (WRT-012, on the branch) does not exist, and stopped at step 5 with `FileNotFoundError` after steps 1–4b had completed and the stamp had been submitted. The store, the initial receipt, the holder store, `report-1` and `report-2` were kept untouched. The driver was made resumable: it asserts `protocol.json` is byte-identical to what it would write, reuses C1, never re-stamps, re-derives E1–E4b from the stored artifacts, recomputes report-2 and requires it to equal the stored one, then runs step 5. `results.json` records `resumed: true` with this note.

## Keys

Holder secret keys were generated outside the repository (`/private/tmp/wrt012-e2e-001-keys/`) and are not tracked; only public keys appear in `holders*.json`. They are throwaway keys for same-custody holders and carry no independence.

## Next bounded steps

1. Later, on a copy: `witness.py upgrade` C1; classify; if a block attestation appears, choose and name a header source before any chain-time claim (same rule as `.triad` followup-003).
2. A holder outside custody `github:s0fractal`. Candidates in WRT-012 §4.3: a Zenodo adapter (`DEPOSITED`, institutional bytes, not a §3 receipt), or a party running `witness.py receive` on their own machine with their own key, whose public key enters our configuration by a channel we can name.
3. Only after 2: revisit §5 per repository, each under its own acceptance.

Maintenance after the recorded run: the driver default key directory now uses
the operator home rather than a predictable shared temporary path. Recorded
outputs are unchanged; the original driver is available at commit 8bb3fdf.
