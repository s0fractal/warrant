# Cross-repository source, verifier, and transported history — experiment 001

Research integration, not adoption or an independent review. The subject bytes
come from Black-heart commit `816d36bed9e156ca1913ac45adbbe2b1ec8d2048`;
the checker is Warrant's merged WRT-012 prototype. Both source files were downloaded
from their exact public GitHub commit and SHA-256 compared with the operands:
2/2 matched (`evidence/source-readback.json`).

The driver creates three disposable stores, signs three sequential commitments,
commits the holder's public bytes in a fixture Git repository, then clones it
without hardlinks into the successor checkout. Every transported JSON file is
compared byte for byte. Private signing keys exist only in a temporary directory
and are removed when signing completes; they are not included in evidence.

The successor's local history really contains only C0; its tip is rolled back.
C1 and C2 must be recovered from the cloned holder store. These are test stores,
not deployments in the canonical Black-heart or Warrant repositories.

## Predeclared controls and observations

`protocol.json` is written before signing and assertions. The initial exploratory
run used a different-stream fork. The recorded run strengthens C to a valid signed
fork in the SAME stream, with a larger sequence and a different genesis.

| Control | Observed |
| --- | --- |
| A: no holder | UNKNOWN |
| B: cloned holder, complete two-link path | LATER_STATE_WITNESSED, 2 steps |
| C: signed same-stream fork | UNKNOWN, DISCONNECTED |
| D: missing intermediate and its receipt | UNKNOWN, PATH_INCOMPLETE |
| E: altered intermediate under its old address | UNKNOWN, LINK_TAMPERED |
| F: wrong configured public key | UNKNOWN, RECEIPT_REFUSED |
| G: sender AND holder rolled back together | UNKNOWN |
| H: run the bound byte checker | PASS; freshness identical to B |

Eight endpoints passed. Two checker mutations fail at their intended assertions:
always-UNKNOWN at B, trust-sequence at C. The existing ten binding regression tests
also pass. The recorded verification scope is ONLY byte equality to the pinned
expected SHA-256, not truth of Black-heart's prose or correctness of its code.

## Reproduce

From Warrant, with Black-heart's pinned commit available in the supplied checkout:

```sh
python3 -B experiments/wrt-012-cross-repo-001/run.py --black-heart ../black-heart --output /tmp/wrt012-cross-fresh
python3 -B experiments/wrt-012-cross-repo-001/mutations.py --black-heart ../black-heart
```

Output must be a new directory. No network or remote writes occur in these
commands. Signing keys, timestamps on the fixture Git commit, absolute paths and
receipt signatures vary on replay; assertions and content-addressed commitments
are the reproducible endpoints. Evidence reports retain their original absolute
input paths; SHA256SUMS covers the saved evidence, not a claim that those paths
exist on another host.

## Root boundary and next deployment

All stores and keys are under one operator, `s0fractal`. Independent custody remains
NOT_DEMONSTRATED; joint rollback remains undetectable. There is no Bitcoin proof,
latest-state discovery, or newly deployed holder. WRT-012 rollout remains closed.

The next deployable experiment is to publish the public commitment/receipt bundle
in a second repository, fetch it at a pinned Git object, and repeat A–H after
removing the local holder. That demonstrates network transport, still one custody.
An independent holder must retain and serve its OWN receipt under a separately
controlled key. A Zenodo deposit is a separate institutional retention adapter,
not a signed holder receipt and not evidence of latest state. Its implementation
must verify downloaded bytes against the caller's expected SHA-256, not rely on a
metadata checksum or a DOI alone. API reference: https://developers.zenodo.org/ .
No Zenodo upload was attempted; no Zenodo credential was present in the checked
standard environment variables, and no logged-in browser session was inspected.

## Actual public readback follow-up

The bundle was pushed to Warrant's experiment branch at the full commit in
`published-source.txt`. `network_readback.py` downloaded all six holder JSON files
from GitHub into a fresh store, checked SHA-256 against locally pinned expected
bytes, then recomputed signatures and the two-link path using the locally pinned
holder key. No local later commitments are available in the successor store.
Before: UNKNOWN. After: LATER_STATE_WITNESSED, two steps.
`evidence/network/` preserves protocol, URLs, digests and both reports.
This completes the network transport step proposed above, still one custody.

```sh
python3 -B experiments/wrt-012-cross-repo-001/network_readback.py --output /tmp/wrt012-network-fresh
```

This follow-up makes six bounded public HTTP reads; it performs no remote writes.
The receiver's expected manifest and public key remain local trusted inputs.
It cannot detect their joint rollback and does not discover a newest GitHub head.

## Git invocation repair

Sonar flagged the CLI repository path flowing into command arguments. The driver
now resolves an existing directory and passes it as subprocess cwd; Git command
arguments remain fixed by the driver. Git calls have a 30-second deadline.
The updated driver passes all eight endpoints and both mutation assertions.
Historical evidence retains its original driver pin; it has not been relabelled.
