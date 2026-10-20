# Ref transport: packets move on their own, pins do not

In round 1 of [the dependency audit](../dependency-audit/round-1/README.md) the
operator copied the packet to the receiver by hand and relayed its digest in a
message. `carry.py` lets the bytes travel on their own over a shared git remote
while keeping the one act that must not be automated away: the pin.

- A party **sends** a packet to `refs/warrant/out/<from>/<to>/<sha256>`.
- The **owner pins** it: `refs/warrant/pins/<to>/<sha256>.<signer fingerprint>`
  holds a small document signed with `ssh-keygen -Y sign` in the namespace
  `warrant-pin`. Pins are keyed by signer, so nobody can occupy the owner's ref.
- The receiver **fetches**: a packet is written out only when a pin for exactly
  that digest, that receiver and a kind it expects verifies against the
  principals in the receiver's `allowed_signers`. Unpinned, mispinned, damaged
  or substituted packets are reported, never delivered. Refs are published once.

This follows sokol-core ADR-0023: agents move bytes and do the work, the owner
pins, the gate refuses what is not pinned. The remote is untrusted transport.
The carrier knows nothing about Warrant: the receiving workspace still applies
its own expectation, trust, profile and provider to the delivered packet.

```sh
# producer host
python examples/ref-transport/carry.py send --repo /private/carrier-a --remote $CARRIER \
  --from producer --to receiver --file packet.json
# owner, anywhere with the carrier and the owner key
python examples/ref-transport/carry.py pin --repo /private/carrier-o --remote $CARRIER \
  --signer ~/.ssh/owner_key --to receiver --from producer --sha256 <digest> --kind packet
# receiver host
python examples/ref-transport/carry.py fetch --repo /private/carrier-b --remote $CARRIER \
  --me receiver --allowed-signers allowed_signers --out inbox/
```

`allowed_signers` is the OpenSSH format: `owner ssh-ed25519 AAAA…`. The pin
carries `{kind, sha256, to, from, at}`; the receiver takes the packet digest it
hands to `handoff.py --packet-sha256` from the verified pin, not from the ref
name or the packet.

`python examples/ref-transport/carry.py selftest` runs nine controls against a
local bare remote with ephemeral keys: unpinned, pinned by an unlisted key, a
stranger's pin not blocking the owner's, publish-once, byte-exact delivery,
addressing, a pin without its packet, tampered bytes, and a pin signed for
another receiver. What a standing owner policy (pin a class of packets in
advance) would look like is an owner decision, not something this tool grants.
