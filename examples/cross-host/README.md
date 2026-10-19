# Two-host handoff smoke

Status: round 1 returned public artifacts through the operator. Their hashes and
signatures matched, and the returned computation passed local replay. External
execution and the six remote controls are **RECEIVER-REPORTED**, not machine
attested. See [round-1/README.md](round-1/README.md) for exact identities, artifacts
and the reproduction command.

The frozen `packet.json` holds a signed producer duty, its attested PAUSED
handoff, and the exact blobs of `S K K (K I)` after credit 2. The expected normal
form is `K I`. This small control term tests transport and protocol plumbing; it
does not establish application usefulness or performance.

Use the installed Warrant implementation from commit
`915ca61aaec405fd33cd9dd0c781a77635bba467`, with Sigma-Glyph 0.8.0 from PyPI.
`run.py` imports installed packages; it does not alter the runtime. Each agent
operation runs in a fresh CLI process. Work directories must be new, private,
and outside the checkout. No producer private key is present in this directory.

## Operator pins for this packet

- Whole packet SHA-256: `d370e70400e7fbcbc27c4a4a71a5d88985e5dc32dbc2e41b268d1076c1ca0140`
- Manifest digest: `83da9bbdd1ff0c4f2d06fa0a01649f07b6ea6d27484a5133e3ed5bfa3aec9287`
- Producer public key: `8ee027cb89aebe9bff8ef2b0c4dbafad9f2f8ceb9f840a32b8d5fea449e1d055`
- Provider: `0caff793d00dd798fa0af89517674c2ca562e1d517e7c969cc40617778c776c5`

The receiver obtains the whole packet digest from the operator's message, not
from a field in the delivered package. Pinning these bytes binds the contained
manifest and producer public key for this experiment. It establishes no broader
identity or authority of the producer. `--accept-provider` is an explicit local
operator choice; no transferred record can add a provider to an existing profile.
The runner creates its own experimental configuration and does not edit the
receiver's existing store, trust, keys or profile.

## Receive

With the bootstrapped venv active, use absolute paths for packet and script:

```sh
python /path/to/run.py receive \
  --packet /path/to/packet.json \
  --packet-sha256 d370e70400e7fbcbc27c4a4a71a5d88985e5dc32dbc2e41b268d1076c1ca0140 \
  --accept-provider 0caff793d00dd798fa0af89517674c2ca562e1d517e7c969cc40617778c776c5 \
  --work /new/private/receiver-dir --reply /path/to/reply.json
```

The receiver checks the package pin, signed declaration and delivery; imports
through Warrant's handoff API; verifies the foreign prefix using checked
`resume`; advances to NORMAL_FORM; files its own compute condition and REPLAYED
closure; and accepts exactly the producer's handoff item. A fresh-process retry
must return the same acceptance without creating an extra record.

Controls require refusal of a damaged delivery, another root, a missing
checkpoint and a wrong state. Removing the provider from the experimental
profile must remove discharge credit. These controls are receiver-reported until
the operator has their output; replay does not prove the controls were run.

The final stdout JSON contains `reply_sha256`, `receiver_public`, result and
control summaries, and `reply_zlib_base64`. Send that JSON via the operator.
It contains public records and blobs; never send the private work directory or
`private.key`. Preserve stdout and `reply.json` before an ephemeral host expires.

## Verify a returned packet

Decode the reported base64 with `zlib.decompress(base64.b64decode(...))` into
`reply.json`; check its SHA-256 against the receiver message, then run:

```sh
python /path/to/run.py verify --packet /path/to/packet.json \
  --reply /path/to/reply.json --reply-sha256 <digest-from-receiver-message> \
  --work /new/private/verifier-dir
```

This checks the returned signatures and receipt, binds the compute condition
to the original input/environment and independently derived expected result,
requires the returned checkpoint to extend the sent one, and replays the result
locally through Warrant. It also checks exact acceptance of the source handoff.
The returned public key is bound to the returned bytes, not to an independently
established real-world identity. Global source completeness stays UNATTESTED.
There is no machine attestation, malicious-root containment, or proof that the
remote agent did not recompute from scratch. Script, provider and frozen inputs
are visible to the receiver.

## Local control

```sh
python examples/cross-host/selftest.py
```

This executes both roles on one host and catches altered packet pins and
reply-to-receipt metadata substitution. It also checks the exact round-1 file
hashes and replays the frozen returned artifact. These are local executions;
they do not independently establish what happened on the receiver's host.
