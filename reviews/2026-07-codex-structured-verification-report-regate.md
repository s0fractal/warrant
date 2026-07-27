# Codex re-gate: structured verification report

**Date:** 2026-07-27
**Reviewer:** Codex / OpenAI
**Branch:** `feat/structured-verification-report`
**Base:** `master` at `bbf73f102be890714c229f20f262a5c123aa197f`
**Candidate:** `3c5c471af05410fff1ff4cdec9772b5a1ab24362`
**Verdict:** **AMEND**

The ordinary closure cases are fixed: Python `verify_report()` and both JSON
CLIs now fail closed on the tested missing/uninitialized-store shapes; ordinary
non-string reporter values become one bounded dispatcher error; README syntax,
stderr purity, and U+2028/U+2029 one-line output are corrected.

Two composition countervectors still violate the central promise that JSON is a
renderer of the same verification result.

## P1 — Go `--json` changes the input mode and therefore the verdict

`verifyDir()` uses the presence of the report sink as a semantic input:

```go
if report != nil && !storeMode {
    fillNoStore(report, "base")
    return 1, 0
}
```

Text mode retains the pre-existing flat-directory verifier, while JSON mode
reclassifies the same bytes as an invalid store.

### Reproduction

An empty existing directory:

```text
warrant-go verify <empty-dir>
  rc=0, verify: 0 records, 0 errors, 0 warnings

warrant-go verify --json <empty-dir>
  rc=1, ok=false, records=0, errors=1, subject=store
```

The repository's real flat `examples/` input:

```text
warrant-go verify examples
  rc=0, verify: 3 records, 0 errors, 10 warnings

warrant-go verify --json examples
  rc=1, ok=false, records=0, errors=1, subject=store
```

This directly contradicts README line 85 ("counts and exit status are identical
to text mode"). It also means adding a renderer changes which verifier runs.

The new no-store battery is vacuous for this composition: it invokes only Go
JSON mode. The shared helper does not assert Go text/JSON exit parity, and the
no-store fixtures do not go through that helper.

### Required closure

- A report sink / `--json` must not participate in input classification.
- Preserve flat mode in both renderers, or intentionally remove it in both
  renderers as a separately reviewed compatibility change.
- Add permanent text-vs-JSON count **and exit** vectors for an empty flat
  directory and the real `examples/` directory.
- Keep the missing-path JSON guarantee: exactly one fail-closed object, clean
  stderr, exit 1.

## P1 — Python reporter still executes hostile `str` subclasses after mutation

The new boundary uses `isinstance(value, str)`. A governed Python runtime can
therefore pass a `str` subclass whose slicing or formatting executes code.
Loud rendering touches those methods after incrementing the warning count;
quiet/report mode does not.

### Reproduction

```python
class SliceBomb(str):
    def __getitem__(self, key):
        raise RuntimeError("slice bomb")

handler = lambda view, mode, out, wid, reason: (
    out("WARN", SliceBomb(wid), "handler warning")
)
```

Observed result on a one-record fixture:

```text
loud verify_store:  (1 error, 2 warnings)
quiet verify_store: (0 errors, 2 warnings)
verify_report:      (0 errors, 2 warnings), ok=true
```

The equivalent message countervector also works:

```python
class FormatBomb(str):
    def __format__(self, spec):
        raise RuntimeError("format bomb")
```

Passing `FormatBomb("handler warning")` produces the same divergence. In loud
mode, rendering raises after WARN mutation and the dispatcher adds ERR; in
quiet/report mode, the hostile method is never called and the report remains
`ok:true`.

### Required closure

- Accept exact built-in strings at the reporter boundary, not executable
  subclasses. Check `type(x) is str` before membership/rendering and before any
  count/finding mutation.
- Prefer a stable generic boundary exception; do not format attacker-controlled
  values while rejecting them.
- Add permanent `str`-subclass vectors for hostile subject slicing and hostile
  message formatting. Assert loud == quiet == report and `ok:false`.

## Non-blocking hygiene

`git diff --check master..HEAD` reports trailing whitespace and an extra final
blank line in the earlier review document. This does not affect verifier
semantics, but the branch is not diff-clean.

## Evidence run

Passing on candidate `3c5c471`:

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
- Corrected Air Canada pack commands for Python and Go both produce one JSON
  line and satisfy `jq -e '.ok'`.

These green suites establish regression preservation, but the two countervectors
above demonstrate that the renderer-independence closure is not complete.
