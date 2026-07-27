# Codex re-gate 3: structured verification report

**Date:** 2026-07-27
**Reviewer:** Codex / OpenAI
**Branch:** `feat/structured-verification-report`
**Base:** `master` at `bbf73f102be890714c229f20f262a5c123aa197f`
**Candidate:** `fdb771e8b977d188b1db1570cd0cc4f221fe15c8`
**Verdict:** **APPROVE TO MERGE**

No blocking findings remain in the reviewed integration boundary.

## Closure confirmed

### Explicit store mode

`--store-mode` is a semantic selector independent of the renderer:

- Python accepts it as a portable no-op because Python verification is already
  store-only.
- Go uses it to require an initialized `records/` directory.
- Text and JSON with the same mode return the same verdict.
- Legacy Go flat-directory verification remains available without the flag.
- The documented machine command now uses `--store-mode`, making `.ok` a safe
  store-verification predicate rather than an ambiguous flat/store result.

The four previous non-store countervectors now agree in both implementations:

```text
missing path       Py text/json rc=1   Go text/json rc=1
empty directory    Py text/json rc=1   Go text/json rc=1
records as file    Py text/json rc=1   Go text/json rc=1
blobs/ only        Py text/json rc=1   Go text/json rc=1
```

Every JSON result is one object with `ok:false`, one store error, and clean
stderr. A real empty initialized store remains `ok:true`. Go flag ordering does
not change the report. `examples/` remains a valid legacy flat input without
the flag and is correctly rejected as a store when the flag is present.

### Reporter fault latch

The runtime handler no longer receives the trusted core reporter. It receives a
per-dispatch validating wrapper that:

- accepts only exact built-in strings and `ERR`/`WARN`;
- ignores invalid emissions without touching core counts/findings;
- latches any violation in verifier-owned state;
- folds exactly one fail-closed ERR after the handler returns or raises.

The following independent compositions all preserve loud == quiet == report:

- invalid call caught/ignored by the handler;
- valid WARN followed by invalid call and handler exception;
- twenty invalid calls in one dispatch;
- invalid call followed by a normal return;
- two separate reason dispatches, each failing independently.

The latch is bounded per dispatch: invalid call plus handler exception produces
one dispatcher ERR, not two; separate reason invocations each receive their own
latch.

## Scope boundary

A registered runtime handler is explicitly documented as governed in-process
TCB code, not an adversarial Python sandbox. This gate therefore reviews the
synchronous handler/reporter contract and does not invent process-isolation
requirements for item 0. Within that stated boundary, the connector is
fail-closed and renderer-independent.

## Evidence run

Passing on candidate `fdb771e`:

- Python selftest.
- Go selftest: 7/7.
- `tests/verify_report.py`.
- `tests/agree_check.sh`: differential 45/45, negative, settlement, runtime
  hook, and pedantic 15/15.
- `tests/hostile.py`.
- differential fuzz: 1350/1350 observations (`450` iterations, seed
  `20260727`).
- evidence-pack tests.
- MCP-seal tests.
- Literal Air Canada `--store-mode --json | jq -e '.ok'` commands pass in
  Python and Go.
- `git diff --check master..HEAD` is clean.

This is a technical merge approval for candidate `fdb771e`; it does not perform
the merge/push or substitute for any repository governance/adoption authority.
