# Round 2: the dependency audit carried over git refs under the owner's pins

2026-10-20, runner at warrant `01b5e5619f982a75b6a6673ad1944b657c4cd77a` (PR #157
on top of #156, the replay cache). Same frozen #150 kit (manifest pin
`7d722e26…`) and reviewed encoder (`2348215116e8…`) as round 1; what changed is
the transport: nobody copied bytes or retyped digests. The one human act was
the owner's pin, twice, with the ssh key `SHA256:4dJ6IEtOAZpBdQ07gvhKTiwTqsiZnaf1Jh/GuYuTeA4`
(fingerprint `7858727e3f3e1d87` in the pin refs).

| Step | Who | Where |
|---|---|---|
| `handoff.py produce` → `carry.py send` to `refs/warrant/out/producer/receiver/5e846211…` | producer agent | macOS, Apple Silicon, Python 3.15 |
| `carry.py pin --kind packet` → `refs/warrant/pins/receiver/5e846211….7858727e3f3e1d87` | **owner**, passphrase typed in a terminal | macOS |
| `carry.py fetch` (delivered only under that pin) → `handoff.py receive` → `carry.py send` to `refs/warrant/out/receiver/producer/4cb63fd1…` | receiver agent | Linux VM `lima-sokol-lab`, Ubuntu 24.04.5, aarch64, Python 3.12.3 |
| `carry.py pin --kind reply` → `refs/warrant/pins/producer/4cb63fd1….7858727e3f3e1d87` | **owner** | macOS |
| `carry.py fetch` → `handoff.py verify` (local replay of every receipt) | producer agent | macOS |

The carrier was a bare repository on the VM (`pilot/carrier.git`, reached from
the Mac over the Lima ssh config). It is untrusted transport: the receiver's
`allowed_signers` lists the owner's public key and nothing else.

## Public bytes here

| File | SHA-256 |
|---|---|
| `packet.json` | `5e84621176a2feb7ab38bb247b31c5ae7ec2e42650785245880740391b3d2e3f` |
| `reply.json` | `4cb63fd129d4eb3772826a6e2e197cf1313cb4ca74c440f0fc00d8bc159cc6e9` |
| `pins/receiver--5e84…/pin.json` + `.sig` | the owner's pin of the packet (`at` 1792528570) |
| `pins/producer--4cb6…/pin.json` + `.sig` | the owner's pin of the reply (`at` 1792529377) |
| `allowed_signers` | the owner's public key, as the receiver configured it |

`SHA256SUMS` covers them; the command outputs of every step and the VM host
facts are beside them. Anyone can re-verify the pins offline:
`ssh-keygen -Y verify -f allowed_signers -I owner -n warrant-pin -s pins/<x>/pin.json.sig < pins/<x>/pin.json`.
`carry.py selftest` does so when this directory is present.

## Results

Verdicts TRUE / TRUE / FALSE; receiver instances byte-identical to the
producer's; every binding control refused with its expected code on the VM;
readback on the Mac: delivery `MATCH_EXPECTED_SET`, each receipt replayed
locally (`REPLAYED:sigma-resume:0caff793d00dd798`), all duties DISCHARGED. The
three receipt ids equal round 1's (`25ea9f49…`, `6b46eedb…`, `22d62dbb…`): the
same bytes from the same root give the same receipt, as they must.

Cost with the replay cache (#156) and one view per role (#155): receiver run on
the VM 1 min 35 s (round 1: 5 min 11 s); readback on the Mac 32 s (round 1: 61 s
before the cache). Rebuild + binding controls per case 15.7 / 15.1 / 2.8 s, resume
incl. replay 13.9 / 13.9 / 2.0 s on the VM.

## What this establishes, and not

Established: the packet and the reply moved between two hosts without an
operator copying bytes or relaying digests; each was delivered only after the
owner signed its exact digest for that receiver; the Warrant layer on top
behaved exactly as in round 1. Not established: independent custody (both
hosts and the signing key are the owner's; the VM shares the physical machine),
machine attestation, that the receiver did not recompute from scratch, package
safety, source/index completeness. A standing owner policy that would remove
the per-packet pin is an owner decision not taken here.
