# Round 1: two hosts, real wheel audit

2026-10-20. The dependency-audit handoff ran across two hosts with the runner at
warrant commit `faefe2dd1aa9a56a30b104d58d9314403227f5ba` (PR #155), the frozen
#150 kit (manifest pin `7d722e2664dc57f1618b3bd7c47d3ffbb77d775f770315a8ebc1dcf0b6645653`)
and the reviewed encoder (`2348215116e81f6fdd492077e2491252ae8a968cb72e303886084fdbbf29d16e`).

| Role | Host | Runtime |
|---|---|---|
| producer, then readback (`verify`) | macOS, Apple Silicon (arm64) | Python 3.15.0, sigma-glyph 0.8.0 from PyPI |
| receiver | Linux VM `lima-sokol-lab`, Ubuntu 24.04.5, kernel 6.8.0-147, aarch64 | Python 3.12.3, sigma-glyph 0.8.0 from PyPI |

The operator (the same person's session, relaying by file copy) carried the
packet to the receiver and its digest separately, and the reply and its digest
back. The receiver fetched the four public wheels by exact URL and hash itself
(`WHEEL_BYTES_VERIFIED`, provider `MATCHED_REVIEWED_BYTES`).

## Public bytes in this directory

| File | SHA-256 | What |
|---|---|---|
| `packet.json` | `5d82d2a2b4e3226549f1a16d6beaf99d2c51d3b892ba371bbf9f64e5577503f6` | the producer's signed handoff: three paused cases, their instances, evidence, public workloads, checkpoints |
| `reply.json` | `89548834cc4d8920558bf9274670be329b6ee1361bd8d0ea7aae4942e1363e61` | the receiver's signed return: duties, REPLAYED closures, receipts, acceptances, controls |
| `produce-stdout.json`, `receive-stdout.json`, `verify-stdout.json` | | the three commands' outputs, as recorded |
| `vm-host.txt` | | the receiver host's `uname`, Python and OS release, and its own digest of `reply.json` |

Producer public key `dc707cf3fd334f29dc400f04ca2afed85b02bc125754d85233cfdb08f859ea59`,
receiver public key `f374a896f0ec7c3e86fa0128536781882e749403670286e5a02e02e1dfa4a847`:
experiment keys generated for this round, bound to these bytes only.

## Results

| Case | Verdict | Receipt | Receiver duty | Acceptance of the handoff | Rebuild + controls | Resume incl. replay |
|---|---|---|---|---|---:|---:|
| base | TRUE | `25ea9f49f46bc01a…` | `12a49a5f6e07e4c7…` | `55784e78be5720fd…` | 17.7 s | 13.6 s |
| compute | TRUE | `6b46eedb27e33f56…` | `1c1e3beefe6f4697…` | `6a9670ab8b257b56…` | 17.3 s | 13.3 s |
| transitive-prohibited | FALSE | `22d62dbbcdf6d08a…` | `80fa5f69a420aac9…` | `86b129e1651a5c4e…` | 3.8 s | 2.0 s |

The receiver's instances equal the producer's byte for byte (`b5f458624ef3c2ca…`
for base, the same ids the local selftest produces), so the binding survived the
host change. Every binding control refused with its expected code on the
receiver; `wrong_root_resume = REFUSED`, `insufficient_budget = [PAUSED, no
receipt]`, `unaccepted_provider = OPEN`, `damaged_delivery =
[MISSING_DECLARED_BYTES, IMPORT_BLOCKED]`. The whole receiver run took 5 min 11 s
of wall time on the VM, including fetching wheels and the controls.

Readback on the producer's host: delivery `MATCH_EXPECTED_SET`; for each case the
receiver's compute condition names the locally rebuilt instance, the returned
checkpoint extends the sent one, closure and acceptance are bound to the exact
items, and the producer host's own replay of each receipt gives `DISCHARGED`
with basis `REPLAYED:sigma-resume:0caff793d00dd798`.

## What this does and does not establish

Established: one real wheel-derived audit (two real cases, one synthetic
transitive-negative control) was paused on one host, rebuilt and continued on
another host under that host's own provider and profile, accepted exactly, and
replayed again on the first host; the prescribed refusal cases have recorded
results from the receiver host.

Not established: machine attestation of the receiver (the VM runs on the same
physical machine as the producer, under the same person's custody, so this is
two hosts and two key pairs, not independent custody); that the receiver did not
recompute from scratch; package safety; source/index completeness
(UNATTESTED); general encoder correctness. The receiver's controls are
receiver-reported; `handoff.py selftest` replays the frozen `reply.json` locally
and checks these file digests.
