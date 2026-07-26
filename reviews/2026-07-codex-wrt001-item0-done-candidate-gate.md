# WRT-001 item 0 DONE-candidate — independent gate

Date: 2026-07-27  
Scope: revised Warrant Python/Go refactor, permanent vectors, WRT-001, and
Sigma ADR-008 rev 13  
Verdict: **REVISE — SIX RECHECK-2 FIXES SUBSTANTIALLY LAND, BUT ITEM 0 IS NOT
YET CROSS-IMPLEMENTATION CLOSED**

This iteration closes most of the previous concrete findings:

- the re-litigation path now threads the original `recs` snapshot and the
  supplied two-record fixture observes exactly one `all_records()` call;
- ordinary non-empty bad-trust verification short-circuits to `(1, 0)` in
  Python and Go;
- Python hashes and parses the same `genesis.json` byte string;
- the handler view no longer retains the verifier's live record map, and the
  document now honestly declares registered handlers governed TCB code rather
  than sandboxed plugins;
- present wrong-digest CAS reads return `None` and increment the private meter;
- non-filing R0 now operates over raw eligibility and remains `pass` under the
  supplied foreign-supersede vector.

Two uncovered compositions still split the public Python and Go verifiers.

## Reproduced baseline

- `python3 impl/warrant.py selftest`: `SELFTEST: ALL PASS`.
- `tests/agree_check.sh`: differential 45/45, settlement all agree,
  runtime-hook all pass, pedantic 15/15.
- Sigma `tools/test-all.sh`: `TEST-ALL: ALL GREEN`.
- Sigma join probe: non-filing R0 has `CW=False`, record count `4/4`, and both
  normal/foreign-supersede queries return `pass`.

## Findings

### [P1] Bad-trust short-circuit diverges when record loading also found an error

Python emits `load_errors` before validating trust:

- records are loaded and their errors reported at `impl/warrant.py:920-923`;
- only afterwards does the trust failure return at `impl/warrant.py:925-954`.

Go also loads the directory first, but defers per-record reporting until after
the trust preflight. Therefore a malformed record file plus a missing trust
file gives:

```text
Python:
  ERR unloadable record: malformed JSON
  ERR settlement trust config unavailable
  verify: 0 records, 2 errors, 0 warnings

Go:
  ERR settlement trust config unavailable
  verify: 1 records, 1 errors, 0 warnings
```

This violates the chosen contract—one global ERR, no partial report—and the
claimed Python↔Go parity. It also exposes a second disagreement: the summary
counts successfully parsed records in Python but record files in Go.

Collecting record errors before trust validation is fine; emitting them is not.
Delay Python `load_errors` reporting until after a valid settlement context
exists, matching Go's short-circuit. Define the summary's `records` count once
and use it in both implementations (prefer successfully loaded records). Add a
bad-trust fixture containing malformed JSON, wrong-top-level shape, and one
valid record, and compare the complete output/counts—not only the presence of
`ERR_SETTLEMENT_TRUST`.

### [P1] Hash-pinned `genesis.json` still has parser-domain divergence

The byte-level TOCTOU is fixed, but Python and Go do not validate those same
bytes in the same JSON domain:

- Python uses duplicate-rejecting `loads_ijson`;
- Go uses a stock `json.Decoder`, performs one `Decode`, does not reject
  duplicate members, and does not require EOF.

With a real self-signed root and a trust config pinning the exact bytes:

```json
{"roots":[],"roots":["<root WarrantID>"]}
```

I reproduced:

```text
Python: (0 errors, 1 warning)  unadopted root
Go:     (0 errors, 0 warnings) root used as genesis
```

Thus the same out-of-band digest authorizes different jurisdiction roots across
implementations. A trailing-document variant has the same parser-domain risk.
This is a trust-authority split, not an editorial difference.

Create one shared `genesis.json` parser contract in both languages:

- one JSON object and EOF;
- duplicate-key rejection / I-JSON;
- exact permitted field set;
- `roots` is a list of WarrantID hex64 values (with a specified duplicate
  policy);
- parse exactly the bytes whose digest matched.

Invalid pinned content must be ignored with one stable outcome in both
implementations. Add duplicate-key, trailing-content, wrong-shape, bad-root,
and valid canonical vectors.

### [P2] The “all six countervectors have permanent tests” claim is overstated

The new tests permanently cover re-litigation reads, ordinary non-empty trust
failure, present wrong-digest CAS behavior, mode dispatch, and raw-R0 foreign
supersede. They do not contain:

- the actual pinned-genesis swap/read-count regression;
- malformed-record plus failed-trust composition;
- duplicate/trailing `genesis.json` parity;
- an assertion that attempted wrong-digest work incremented the private meter
  (the code increments it, but the test observes only `None`);
- a direct mutation of the handler's private snapshot proving it cannot affect
  core verification.

Not all of these need to expose implementation-private counters, but the
security/parity countervectors should be permanent before item 0 is called
DONE.

### [P2] The RuntimeView authority wording remains stronger than the implementation

The new TCB statement is the correct trust model. However, `_RuntimeView`
retains `_blob`, a Python closure whose default arguments include the raw
`Store` and mutable meter. Governed code can introspect those values. This is
not a live-record alias and does not reproduce the former core crash, so it is
not a blocker under the declared TCB model.

Adjust “retains no raw store” / “only path” to mean **public supported API**, not
an in-process security property. The current prose otherwise contradicts its
own accurate statement that Python cannot sandbox extension code.

## Gate recommendation

Keep item 0 at **DONE-candidate**. The remaining implementation patch is narrow:

1. make trust-failure short-circuit precede all per-record output in both
   implementations and align the summary count;
2. give hash-pinned `genesis.json` one strict cross-language parser/schema; and
3. add the two composition vectors above.

No need to redesign the registry, snapshot threading, R0 mechanics, or handler
TCB model again. Do not begin R1 or seek governance signatures until these
public-verifier parity vectors pass.
