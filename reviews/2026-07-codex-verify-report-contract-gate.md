# Codex gate: `docs/verify-report-contract`

Date: 2026-07-27
Candidate: `8febf8c148db6a2658dc5d3f4325d3725a60516d`
Verdict: **AMEND**

## Finding

### P2 — New producer guarantees have no owner-side regression assertions

`README.md` now promises that:

1. `errors`/`warnings` exactly equal the corresponding finding counts and every
   emitted finding is `ERR` or `WARN`; and
2. `warrant.verify-report@v0` has exactly seven top-level keys and exactly three
   keys per finding.

The current Python and Go implementations satisfy both promises, and the Sigma
consumer correctly rejects violations. However, `tests/verify_report.py` does
not assert either exact key set or the counts-to-findings equality. A later
producer change can therefore violate the published machine contract while the
Warrant suite remains green; the failure would surface only after a downstream
consumer updates its pinned Warrant revision.

Add a shared report-contract assertion to the Warrant-owned suite and apply it
to every Python and Go JSON vector, including no-store/fail-closed reports:

- exact top-level key set;
- exact finding key set;
- `errors == count(level == "ERR")`;
- `warnings == count(level == "WARN")`;
- no other finding level.

This is a test-ownership amendment, not a request to change the report format.

## Verification

- `python3 tests/verify_report.py`: **ALL PASS**
- `./tests/agree_check.sh`: **ALL PASS**
- static inspection confirms both implementations currently emit the promised
  closed shape and count every `ERR`/`WARN` finding.
