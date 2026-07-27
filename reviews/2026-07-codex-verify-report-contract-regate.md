# Codex re-gate: `docs/verify-report-contract`

Date: 2026-07-27
Candidate: `48dca0879a34cf09a7ed5d2d03063cdb4db851f7`
Prior candidate: `8febf8c148db6a2658dc5d3f4325d3725a60516d`
Verdict: **APPROVE**

## Closure

The prior P2 is closed.

`report_contract_ok()` is now a Warrant-owned producer assertion for the two
documented `warrant.verify-report@v0` guarantees:

- the top-level and per-finding key sets are exact;
- every finding is `ERR` or `WARN`;
- `errors` and `warnings` equal the corresponding finding counts.

The assertion is exercised across the distinct Python and Go report-producing
paths, including clean and malformed stores, settlement preflight failure,
explicit store mode, no-store failure, empty stores, renderer-independent Go
mode, and runtime-reporter failure. The mutation battery is non-vacuous: it
rejects extra and missing keys, both count mismatches, `INFO`, and an extra
finding key while accepting the valid baseline.

No implementation or consensus semantics changed.

## Verification

- `python3 tests/verify_report.py`: **VERIFY-REPORT: ALL PASS**
- `./tests/agree_check.sh`: **ALL PASS**
  - differential canonicalization: 45/45
  - settlement differential: all agree
  - runtime hook: all pass
  - pedantic edges: 15/15

## Non-blocking hygiene

`git diff --check 8febf8c..48dca08` reports trailing Markdown line-break spaces
and an extra EOF blank line in the committed prior review document. These are
review-artifact formatting only, not contract or executable-code defects; clean
them before landing if the branch requires a zero-warning diff.
