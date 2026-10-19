# Round 1: returned artifacts locally replayed

Date: 2026-10-19. The operator relayed the receiver's report, then supplied the
downloaded `reply.json` and `receiver-report.json`. The files here preserve those
exact bytes. No remote filesystem access was used by the local verifier.

## Locally verified

- Input kit: `9282e437bfd151961bb6b6b58c013eb65da1a313`.
- Input packet SHA-256: `d370e70400e7fbcbc27c4a4a71a5d88985e5dc32dbc2e41b268d1076c1ca0140`.
- `reply.json` SHA-256: `974fef6d681e415b477327cfb811b18f1b9cd72cbeb18737615adaf662447c13`.
- `receiver-report.json` SHA-256: `65dd3b72e61991911cd05a5c825a48589de0e96785e40de109eba869630f1f88`.
- The report's base64/zlib payload decodes to exactly `reply.json`.
- Receiver public key: `714a61358c72553ab8501853b987bc94e3d787bd0d18385e7c3f2fcfeb4d6892`.
- Returned signatures authenticate under the two experimental public-key bindings.
- Delivery: `MATCH_EXPECTED_SET`.
- Returned checkpoint has the original PAUSED checkpoint as its parent.
- Signed compute condition binds the original input/environment and the locally
  derived `K I` result: `65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098`.
- Local replay: `PASS`; disposition `DISCHARGED`; basis
  `REPLAYED:sigma-resume:0caff793d00dd798`.
- The returned signed acceptance binds the original producer transition, item 0.

`local-replay.json` records the verifier output. Reproduce with an installed
Warrant from `915ca61aaec405fd33cd9dd0c781a77635bba467` and Sigma-Glyph 0.8.0:

```sh
python examples/cross-host/run.py verify \
  --packet examples/cross-host/packet.json \
  --reply examples/cross-host/round-1/reply.json \
  --reply-sha256 974fef6d681e415b477327cfb811b18f1b9cd72cbeb18737615adaf662447c13 \
  --work "$(mktemp -d)/verifier"
```

## Receiver-reported

Ubuntu 24.04.5 LTS, x86_64, Python 3.13.16; installed Warrant source
`915ca61aaec405fd33cd9dd0c781a77635bba467`; Sigma-Glyph 0.8.0. The receiver
reported `receive` exit 0, empty stderr, and PASS for damaged delivery, wrong
root, missing checkpoint, wrong state, unaccepted provider and restart/retry.
These execution/environment claims are not independently machine-attested.
The same six control paths passed in the local two-role simulation; that is a
separate local observation and does not prove their remote execution.

The receiver retained its private key. No private key is needed for this returned
artifact replay, and none is included here. Public-key possession does not
establish a real-world identity. Source completeness stays UNATTESTED; there is
no malicious-root containment or proof that the receiver did not recompute from
scratch. This is a control-term transport result, not application validation.
