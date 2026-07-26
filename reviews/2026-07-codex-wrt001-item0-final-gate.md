# WRT-001 item 0 — final DONE-candidate gate

Date: 2026-07-27  
Scope: the two composition fixes following the previous DONE-candidate gate,
their permanent vectors, and adjacent parser/totality cases  
Verdict: **REVISE — THE TWO TARGETED CASES IMPROVED, BUT ITEM 0 IS STILL NOT
CROSS-IMPLEMENTATION CLOSED**

The intended fixes are present:

- Python now performs the trust preflight before emitting `load_errors`;
- Go routes pinned `genesis.json` through `decodeStrictJSON`;
- duplicate-key and trailing-document inputs are rejected by both implementations;
- the main Warrant and Sigma suites remain green.

However, the claimed common “strict I-JSON” domain is not yet common, and the
new composition harness masks part of the original public-report divergence.

## Reproduced baseline

- `python3 impl/warrant.py selftest`: `SELFTEST: ALL PASS`.
- `tests/agree_check.sh`: differential 45/45, settlement all agree,
  runtime-hook all pass, pedantic 15/15.
- Sigma `tools/test-all.sh`: `TEST-ALL: ALL GREEN`.
- Sigma join probe: genuine non-filing R0 and foreign-supersede R0 both pass;
  every supplied stored-path negative is caught.

## Findings

### [P1] `decodeStrictJSON` is not the same byte domain as Python `loads_ijson`

Go's `encoding/json` accepts invalid UTF-8 and substitutes U+FFFD. Python's
`Path.read_text(encoding="utf-8")` / `raw.decode("utf-8")` rejects the same
bytes. I reproduced an empty store with this trust config:

```text
{"actors":{"a<FF>":[]}}
```

where `<FF>` is the raw byte `0xff`:

```text
Python: exit 1, (1 error, 0 warnings)
        settlement trust config unavailable
Go:     exit 0, (0 errors, 0 warnings)
```

The same split is authority-bearing in a hash-pinned `genesis.json`: a valid
root plus an ignored string containing `0xff` is rejected by Python, while Go
adopts the root.

The reverse split also exists. Python's stock `json.loads` accepts `NaN` and
`Infinity`; Go rejects them. With exact hash-pinned bytes:

```text
{"roots":["<valid root WID>"],"x":NaN}
{"roots":["<valid root WID>"],"x":Infinity}
```

I reproduced:

```text
Python: root adopted, 0 warnings
Go:     root not adopted, "unadopted root"
```

Thus duplicate/trailing parity is not sufficient to call the decoders the same
I-JSON parser. Reject non-UTF-8 bytes in Go before tokenization
(`utf8.Valid(data)`), and make Python reject non-finite constants
(`parse_constant` raising `ValueError`). Add both directions as permanent
cross-language vectors. Since all current schemas use integers/strings, strict
finite-number rejection is backward-compatible for valid inputs.

### [P1] Pinned `genesis.json` is not schema-total in Python

Both implementations filter individual roots to hex64, but neither validates a
closed genesis schema. More immediately, Python iterates
`doc.get("roots", [])` without checking that it is a list. I reproduced:

```json
{"roots": null}
{"roots": 7}
```

under their exact pinned digest:

```text
Python: traceback, no verifier summary
Go:     exit 0, "unadopted root"
```

Define and share the complete portable-genesis schema, rather than only its JSON
parser:

- exact object shape `{"roots":[...]}` (or explicitly state any allowed extra
  fields);
- `roots` required and a list;
- every member is hex64;
- a specified duplicate-root policy.

Invalid pinned content must produce one stable, total outcome in both
implementations. Add null, scalar, missing, mixed-type, duplicate-root, unknown
field, and valid vectors.

### [P1] The malformed-record composition still has different public summaries

The control flow now emits one global trust error in both implementations, but
the original summary-count split remains:

```text
Python: verify: 0 records, 1 errors, 0 warnings
Go:     verify: 1 records, 1 errors, 0 warnings
```

`tests/settlement.py:counts()` captures the `records` field but discards it,
returning only `(errors, warnings)`. Consequently `assert_verify()` labels these
outputs equal. Go counts record files (`recList`); Python counts successfully
loaded records (`recs`).

Make the summary contract explicit and align it (prefer successfully loaded
records). Have the differential helper compare all three counts or the complete
normalized summary.

### [P2] The duplicate-genesis regression does not assert its named property

`case_composition_parity` names the condition “attacker root NOT adopted”, but
calls `assert_verify` without requiring `WARN_UNADOPTED_ROOT` or inspecting the
active roots. If both implementations regress to last-key-wins, the test remains
green because it checks only parity.

Assert the security property as well as parity. The malformed-record vector
similarly needs the full three-field summary comparison described above.

## Gate recommendation

Keep item 0 at **DONE-candidate**. The remaining patch is still local:

1. complete the shared byte-level JSON domain (UTF-8 and non-finite numbers);
2. add a total, closed `genesis.json` schema;
3. align and actually compare the full public summary; and
4. make the security fixtures assert their named outcomes.

The snapshot, dispatcher, fail-closed ordering, CAS, and R0 design do not need
another redesign. Do not start R1 or seek governance signatures until these
vectors pass.
