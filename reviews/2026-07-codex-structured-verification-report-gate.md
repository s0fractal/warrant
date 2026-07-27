# Codex gate — structured verification report

**Date:** 2026-07-27
**Reviewer:** Codex / OpenAI
**Branch:** `feat/structured-verification-report`
**Base:** `master` at `bbf73f102be890714c229f20f262a5c123aa197f`
**Candidate:** `4640bf2afe38243ed26a37467da99685b44a73e8`
**Scope:** the NON-NORMATIVE `warrant.verify-report@v0` Python API and Python/Go
`verify --json` integration surface. No Warrant SPEC or settlement-semantics
adoption is reviewed here.

## Verdict

**AMEND — 2 P1 findings.**

The core design is sound: structured findings are collected by the same reporter
that computes the text counts, default text mode is additive rather than
re-derived, trust failure is represented in the report, ordering is deterministic
on the committed fixtures, and the branch preserves all existing verification
suites.

The new integration boundary is not yet fail-closed, however. A missing store is
reported as a successful verification by the public Python API; and the generic
runtime reporter can make text and JSON modes return different error counts (or
make JSON serialization crash). Both violate the feature's central contract:
the renderer must not change verification truth.

---

## P1-1 — `verify_report()` turns “no store” into `ok:true`; JSON CLIs emit no report

`verify_report()` calls `verify_store()` directly
(`impl/warrant.py:1252–1271`). Unlike the CLI, it never checks that
`store.records` is an initialized store. `Store.all_records()` globs a missing
directory as an empty sequence, so the new public API converts absence into a
clean empty verification:

```text
verify_report(Store("/tmp/definitely-no-such-warrant-store"))
→ {
    "report": "warrant.verify-report@v0",
    "grade": "base",
    "ok": true,
    "records": 0,
    "errors": 0,
    "warnings": 0,
    "findings": []
  }
```

This is fail-open at the exact machine-consumption boundary the feature adds. An
agent cannot distinguish “verified empty initialized store” from “path does not
exist / is not a store”.

The CLI direction is inconsistent in the opposite way:

```text
python3 impl/warrant.py --store /tmp/no-such verify --json
→ rc 1, stdout empty, human stderr "no store at ..."

./impl-go/warrant-go verify --json /tmp/no-such
→ rc 1, stdout empty, human stderr "open ... no such file ..."
```

Python exits through `Store.require()` before `verify_report`
(`impl/warrant.py:1628–1637`). Go returns before initializing `verifyReport`
(`impl-go/main.go:2175–2183`, `2425–2429`), and `main` serializes only when
`report.Report != ""` (`impl-go/main.go:123`). Thus both break the advertised
“exactly one JSON object” contract on a normal verifier preflight failure, and
they break it differently from the Python API.

### Required closure

Choose and state one contract, then pin it in both implementations. Recommended:

- an initialized empty store remains `ok:true`;
- a missing path, a path without `records/`, or `records` that is not a
  directory returns one `warrant.verify-report@v0` object with `ok:false`,
  `errors:1`, and one stable `ERR` finding whose subject is `store`;
- JSON mode emits no human diagnostic on stdout; preferably the report is also
  the only diagnostic for an expected verification failure;
- direct Python `verify_report()` and both CLIs agree on the classification and
  exit status.

Permanent vectors: missing path, ordinary non-store directory,
`records`-as-file, `blobs/` without `records/`, and a genuinely initialized empty
store.

---

## P1-2 — an unvalidated runtime reporter makes the renderer change the verdict

Python's `out(level, wid, msg)` appends raw reporter arguments to `findings`, but
formats `wid[:12]` only in non-quiet text mode
(`impl/warrant.py:979–991`). `verify_report()` always invokes the core with
`quiet=True`. Therefore invalid reporter values behave differently depending on
the renderer.

A registered, schema-valid runtime handler calling:

```python
out("WARN", 7, {"structured": "not a string"})
```

produced:

```text
text verify_store(quiet=False): 1 error, 2 warnings
JSON verify_report():           0 errors, 2 warnings, ok:true

last JSON finding:
{"level":"WARN","subject":7,"message":{"structured":"not a string"}}
```

In text mode, `wid[:12]` raises; the dispatcher catches the handler failure and
adds its fail-closed ERR. In JSON mode, no formatting occurs, so the invalid
finding silently escapes and the ERR disappears. Verification truth now depends
on presentation.

Two adjacent countervectors:

- `out("WARN", wid, b"not-json-serializable")` returns a report that crashes
  `json.dumps()` with `TypeError` outside the bounded dispatcher;
- `out("INFO", wid, "extension info")` places `level:"INFO"` in `findings`,
  although the report contract and Go type explicitly define findings as
  `ERR|WARN` only. Go's comment says INFO is text-only; Python does not enforce
  that boundary.

This is not adequately dismissed as a malicious plugin: registered runtimes are
governed TCB extensions, but the generic hook intentionally catches an extension
mistake and turns it into one bounded fail-closed ERR. The JSON renderer must not
silently remove that guard.

### Required closure

Validate the reporter boundary before mutating counts or findings:

- `level` is exactly `ERR` or `WARN`;
- `subject` and `message` are strings;
- an invalid reporter call raises before partial count mutation, so the existing
  dispatcher catch produces exactly one stable ERR attributed to the current
  record in both quiet and loud modes;
- every value returned by `verify_report()` is JSON-serializable by construction.

Alternatively expose a handler-specific reporter already bound to the current
WarrantID, so an extension cannot substitute the subject.

Permanent vectors must register a real test runtime and cover invalid level,
non-string subject, dict/bytes message, and a handler that writes a valid
WARN. Require text counts, quiet counts, report counts, `ok`, and serialization
to agree.

---

## P2-1 — the only documented external command is invalid for Python and points at the wrong directory

README adds:

```sh
warrant verify --json ./evidence-pack | jq -e '.ok'
```

The Python CLI has no positional store argument after `verify`; `--store` is a
global option. The command exits `2`:

```text
warrant: error: unrecognized arguments: ./evidence-pack
```

Also, an Evidence Pack's store is `pack/.warrants/`, not the pack root
(`EVIDENCE-PACK.md`). The working command is:

```sh
warrant --store ./evidence-pack/.warrants verify --json | jq -e '.ok'
```

Go's intentionally different positional syntax should be documented separately:

```sh
warrant-go verify --json ./evidence-pack/.warrants
```

The machine-readable feature's shortest adoption path must itself be executable
and should be pinned by a documentation smoke test.

---

## P2-2 — “same report” overstates the cross-implementation contract

README says Python and Go “emit the same report”, while
`tests/verify_report.py` explicitly permits finding-message differences and
compares only:

```text
report, grade, ok, records, errors, warnings,
sorted multiset of (level, subject)
```

The implementations already emit different `ski@v1` error prose, so the JSON
objects are not the same. Either:

- document the actual semantic parity boundary and declare `message`
  non-portable human prose; or
- add a stable machine-readable finding `code` and compare that across
  implementations.

External agents should not be invited to branch on prose that the project knows
is implementation-specific.

---

## P2-3 — the new suite misses the generic hook and does not test what several comments claim

`tests/verify_report.py` calls the unresolved core `ski@v1` case a
“runtime-hook dispatch path”, but it never registers a generic runtime handler.
That omission is why P1-2 stayed invisible.

Other gaps:

- no missing/non-store preflight vector;
- no Go text-vs-JSON count comparison;
- cross-implementation comparison sorts findings and drops messages, so it does
  not establish identical finding order or identical reports;
- `one_json_object()` requires `splitlines()` length 1. A valid actor containing
  `U+2028` makes Python's `ensure_ascii=False` output split as two Unicode lines,
  while Go escapes it, although both parse to the same JSON value. Decide whether
  the contract is one JSON **value** or one physical JSONL line and test that
  contract directly;
- normal-case stderr purity is not asserted.

The `U+2028` countervector produced semantically identical parsed messages but:

```text
Python stdout splitlines: 2   (raw U+2028)
Go stdout splitlines:     1   (\u2028 escaped)
```

This is P2 because both outputs remain valid single JSON values; it becomes a
contract bug only if a physical one-line/JSONL promise is intended.

---

## What passed

All green results below are necessary baseline evidence, not the independent
gate verdict:

```text
python3 tests/verify_report.py
  VERIFY-REPORT: ALL PASS

python3 impl/warrant.py selftest
  SELFTEST: ALL PASS

./impl-go/warrant-go selftest examples
  SELFTEST: ALL PASS (7/7)

./tests/agree_check.sh
  DIFFERENTIAL: ALL AGREE (45/45)
  NEGATIVE: ALL AGREE
  SETTLEMENT: ALL AGREE
  RUNTIME-HOOK: ALL PASS
  PEDANTIC-EDGES: ALL AGREE (15/15)

python3 tests/hostile.py
  HOSTILE: ALL PASS

python3 tests/fuzz_differential.py
  FUZZ-DIFFERENTIAL: ALL AGREE (450/450), seed=1337

python3 tests/evidence_pack.py
  EVIDENCE-PACKS: ALL PASS

python3 tests/mcp_seal.py
  MCP-SEAL: ALL PASS
```

`go build`, `git diff --check master...4640bf2`, and the default branch diff are
clean. The existing untracked `scratchpad/` was not read as implementation input,
modified, or included.

## Re-gate

Re-gate the two P1 compositions, not just the happy report fixtures:

1. no-store/non-store inputs must never become `ok:true` and JSON mode must
   return one parseable report;
2. a registered handler's malformed reporter calls must be renderer-independent,
   bounded, schema-valid, and JSON-serializable.

After those close, rerun the documented Evidence Pack command literally in
addition to the full regression suite.
