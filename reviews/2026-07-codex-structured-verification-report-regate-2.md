# Codex re-gate 2: structured verification report

**Date:** 2026-07-27
**Reviewer:** Codex / OpenAI
**Branch:** `feat/structured-verification-report`
**Base:** `master` at `bbf73f102be890714c229f20f262a5c123aa197f`
**Candidate:** `b0ac369b9c2d3a6c1037c0d487de852380f9d440`
**Verdict:** **AMEND**

Both literal findings from the previous re-gate are closed:

- Go text and JSON now select the same verifier for `examples/`, an empty flat
  directory, and a missing path.
- `SliceBomb` and `FormatBomb` are rejected before mutation; loud, quiet, and
  report modes all produce the same bounded error.

The closure exposes two next-order contract seams. They are not failures of the
new literal vectors; they arise when the two repaired boundaries are composed
with the public machine contract and with handler exception control.

## P1 — Go's implicit flat/store choice makes an uninitialized store `ok:true`

Preserving flat mode in both renderers fixes renderer-independence, but Go still
infers input mode only from the presence of `records/`. The structured report
does not commit which mode ran.

For the same paths passed as the documented store argument:

```text
case                  Python --json          Go --json
missing path          rc=1, ok=false         rc=1, ok=false
empty directory       rc=1, ok=false         rc=0, ok=true
records is a file     rc=1, ok=false         rc=0, ok=true
blobs/ only           rc=1, ok=false         rc=0, ok=true
```

The successful Go reports are indistinguishable from an initialized empty store:

```json
{"grade":"base","ok":true,"records":0,"errors":0,"warnings":0,"findings":[]}
```

This contradicts the public contract in README lines 71–88:

- the positional Go argument is described as the store;
- a missing/uninitialized store is said to fail closed;
- Python and Go are said to agree on normative report fields.

It also contradicts invariants 3 and 5 in `tests/verify_report.py`. The new tests
avoid the contradiction by putting Python non-stores and Go flat inputs into
separate batteries, but the machine report has no field or invocation contract
that tells an agent which interpretation occurred.

This is a fail-open ambiguity for the documented `... | jq -e '.ok'` consumer:
a typo that resolves to an existing empty directory succeeds in Go.

### Required closure

Make input mode explicit rather than inferred from an ambiguous empty shape.
One compatible route is:

- preserve legacy positional auto/flat verification;
- add an explicit Go store-mode option for machine/store callers;
- make the README Evidence Pack command use that option;
- ensure text and JSON with the same explicit mode remain identical;
- run the four non-store vectors above through explicit store mode and require
  Python/Go parity.

Alternatively, commit `input_mode` in the report and provide a fail-closed
documented store invocation. Merely documenting that Go may silently choose
flat mode is insufficient for `.ok` to be a safe store-verification predicate.

## P1 — A handler can swallow reporter rejection and restore `ok:true`

Exact-type validation is correct, but fail-closed behavior currently depends on
the boundary exception escaping the runtime handler into the dispatcher:

```python
def handler(view, mode, out, wid, reason):
    try:
        out("INFO", wid, "invalid level")
    except ValueError:
        pass
```

Observed:

```text
loud verify_store:  (0 errors, 1 warning)
quiet verify_store: (0 errors, 1 warning)
verify_report:      (0 errors, 1 warning), ok=true
```

The only warning is the unrelated unbound-key warning. A variant catches a
`SliceBomb` rejection and then emits a valid warning; it also returns
`ok:true`. This is not an exotic Python escape: a runtime handler with an
ordinary broad `try/except` defeats the boundary's stated guarantee that a
malformed reporter call becomes one stable fail-closed error.

### Required closure

- Latch a reporter-boundary violation in verifier-owned per-dispatch state
  before raising.
- After the handler returns or raises, fold exactly one dispatcher ERR if either
  the handler escaped with an exception or the violation latch was set.
- Do not let handler exception control clear the verifier-owned latch.
- Add permanent vectors for:
  - invalid reporter call caught and ignored by the handler;
  - caught invalid call followed by a valid WARN;
  - multiple caught violations still producing a bounded deterministic result.

## Evidence run

Passing on candidate `b0ac369`:

- Python selftest.
- Go selftest: 7/7.
- `tests/verify_report.py`.
- `tests/agree_check.sh`: differential 45/45, settlement, runtime hook, and
  pedantic 15/15.
- `tests/hostile.py`.
- differential fuzz: 1350/1350 observations (`450` iterations, seed
  `20260727`).
- evidence-pack tests.
- MCP-seal tests.
- Air Canada pack commands for Python and Go both produce one JSON line and
  satisfy `jq -e '.ok'`.
- `git diff --check master..HEAD` is clean.

No implementation files were changed during this re-gate.
