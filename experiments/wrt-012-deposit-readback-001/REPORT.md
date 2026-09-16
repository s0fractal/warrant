# Institutional subject retention: Zenodo readback 001

The public PDF in Zenodo record 22172098 was downloaded from a fixed HTTPS
endpoint and SHA-256 matched against the expected digest pinned by this caller.
The same digest is the subject of existing WRT-012 commitment
`402f1a6bbfec84201316135e3dd4cd0b03476e22e3e474d3521151c758b87cbe`;
that commitment's own address was rehashed before recording the relationship.
The local deposited/SHA256SUMS at papers/the-reason-runs-again also agrees.

Result: DEPOSIT_BYTES_OBSERVED. Six live-run endpoints passed, including altered
bytes, wrong record, absent/duplicate filename and oversized input. Two offline
unit tests also exercise metadata-checksum laundering: a correct checksum claim
in the record cannot make different downloaded bytes pass. These are self-tests,
not an independent gate. No API mutation, deposit or publication was performed.

The first metadata request timed out after 30 seconds. Its protocol remains in
its original output directory, with first-attempt.json documenting the failure.
The driver now records NOT_OBSERVED on network/parser failure. The second bounded
read-only attempt succeeded; evidence preserves its exact metadata and results.

## What this establishes

An existing subject of a Warrant commitment is retrievable through an institutional
storage service and matches caller-pinned bytes. Verification depends on the
caller's digest and HTTPS trust, not the record's metadata checksum. Remote
metadata links are not used to choose the download endpoint. The download is
bounded to 16 MiB, with 30-second socket timeouts (not a total process deadline).
PDF bytes were hashed, never executed; the report makes no PDF semantic claim.

## What it does not establish

The commitment itself and its successor chain were NOT deposited. Zenodo has not
issued a WRT-012 holder receipt. This is not latest-head discovery, authenticated
historical timing, guaranteed future availability or resistance to institutional
removal. Freshness stays UNKNOWN; holder_receipt stays NONE. This read-only
retention adapter therefore does not open WRT-012's rollout gate.

Next external experiment: publish a reviewed, frozen commitment-chain bundle as
its own research dataset, download it back by record/file pins, and demonstrate
recovery of the commitment bytes themselves. Keep DEPOSIT_BYTES_OBSERVED separate
from a holder's signed receipt. An independently operated signing holder remains
a different experiment.

## Reproduce

```sh
python3 -B experiments/wrt-012-deposit-readback-001/test_readback.py
python3 -B experiments/wrt-012-deposit-readback-001/readback.py --output /tmp/wrt012-deposit-new
```

The output directory must not exist. The first command is offline; the second
makes two read-only HTTPS requests. Source API documentation:
https://developers.zenodo.org/ . Results and metadata hashes are in evidence/.
