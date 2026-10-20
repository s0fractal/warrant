# Round 3: the receiver on a host the owner does not control

2026-10-21 (UTC 2026-10-20 21:27–21:29). The receiver of the dependency-audit
handoff ran on a **GitHub-hosted runner** (`Linux 6.17.0-1022-azure x86_64`,
Ubuntu 24.04.5, Python 3.12.15), not on any machine of the owner. The carrier
was this repository's own `refs/warrant/*` namespace. Workflow
`.github/workflows/github-receiver.yml` at commit `cc63ab81…`
(branch `pilot/github-receiver`), triggered by pushing the selector branch
`receiver/github-runner/15f2d3d6…`.

| Step | Who | Where |
|---|---|---|
| `handoff.py produce` → `carry.py send` to `refs/warrant/out/producer/github-runner/15f2d3d6…` | producer agent | macOS, Apple Silicon |
| pin of the packet (`refs/warrant/pins/github-runner/15f2d3d6….7858727e3f3e1d87`) | **owner**, ssh key `SHA256:4dJ6IEtOAZpBdQ07gvhKTiwTqsiZnaf1Jh/GuYuTeA4` | macOS |
| fetch under that pin → `handoff.py receive` (fresh key, own provider and profile) → `carry.py send` to `refs/warrant/out/github-runner/producer/18623533…` → Sigstore attestation of `reply.json` | receiver agent | GitHub-hosted runner, run `39500473701` |
| pin of the reply (`refs/warrant/pins/producer/18623533….7858727e3f3e1d87`) | **owner** | macOS |
| fetch under that pin → `handoff.py verify` (local replay of every receipt) → `gh attestation verify` | producer agent | macOS |

## Public bytes here

| File | SHA-256 |
|---|---|
| `packet.json` | `15f2d3d6283834cd13fb56f49aa492fcd4f9660415ccc559de624d1cb7847af9` |
| `reply.json` | `186235335a8c93546577958e12dae5b0dc894dc24616fe968ab3a49d88710fff` |
| `pins/github-runner--15f2…/pin.json` + `.sig`, `pins/producer--1862…/pin.json` + `.sig` | the owner's two pins |
| `attestation-verify.json` | the output of `gh attestation verify reply.json --repo s0fractal/warrant --format json` |
| `runner/` | the runner's own `fetch`, `receive` and `send` outputs and host facts, from the run's artifact |

`SHA256SUMS` covers the packet, the reply, the pins and the attestation record;
`run.txt` names the run. `carry.py selftest` re-verifies the pins offline
against `../allowed_signers`.

## Attestation

`gh attestation verify` accepted the reply bytes against this repository:
SLSA provenance v1, subject `18623533…`, builder
`https://github.com/s0fractal/warrant/.github/workflows/github-receiver.yml@refs/heads/receiver/github-runner/15f2d3d6283834cd13fb56f49aa492fcd4f9660415ccc559de624d1cb7847af9`, invocation `https://github.com/s0fractal/warrant/actions/runs/39500473701/attempts/1`. That is GitHub's Sigstore signature over the
statement that this workflow, at that commit, produced exactly these bytes in
that run. Re-check any time with the command above (needs network for the
Sigstore trust root).

## Results

| Case | Verdict | Rebuild + binding controls | Resume incl. replay |
|---|---|---:|---:|
| base | TRUE | 22.0 s | 18.9 s |
| compute | TRUE | 20.7 s | 20.7 s |
| transitive-prohibited | FALSE | 4.1 s | 2.8 s |

Instances byte-identical to the producer's; every binding control refused with
its expected code on the runner; `wrong_root_resume = REFUSED`,
`insufficient_budget = [PAUSED, no receipt]`, `unaccepted_provider = OPEN`,
`damaged_delivery = [MISSING_DECLARED_BYTES, IMPORT_BLOCKED]`. Whole job
2 min 35 s including installs and wheel fetch. Readback on the Mac: delivery
`MATCH_EXPECTED_SET`, three receipts replayed locally
(`REPLAYED:sigma-resume:0caff793d00dd798`), all duties DISCHARGED; receipt ids
equal rounds 1 and 2.

## What this establishes, and not

Established, beyond rounds 1–2: the receiver host was not the owner's, and
GitHub's provenance names the run and commit that produced the reply bytes the
producer later replayed. The owner's two pins remained the only human acts.

Not established: that GitHub's runner is independent of GitHub (the
attestation is GitHub's word about its own runner, signed through Sigstore);
hardware attestation; that the receiver did not recompute from scratch (it can,
by design); package safety; source/index completeness. The producer and the
owner's key stay on the owner's machine. The selector branch
`receiver/github-runner/15f2d3d6…` is part of the recorded builder id and is
kept.

run https://github.com/s0fractal/warrant/actions/runs/39500473701
head cc63ab81144fa72d54abd05e427a1684cb658332
created 2026-10-20T21:27:14Z
updated 2026-10-20T21:29:49Z
conclusion success
