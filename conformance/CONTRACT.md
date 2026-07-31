# The `warrant-conformance/1` candidate contract

This is everything your implementation must do to be testable by `run.py`. It is
deliberately short: one process, one JSON object in, one JSON object out. If it
takes you more than an afternoon in any language that can read stdin and print
JSON, the contract is at fault and that is a bug worth reporting.

You do **not** need this repository, our Python, or any Warrant library to
satisfy it. The runner never imports, links against, or executes a reference
implementation — it only knows how to speak to yours.

---

## 1. The invocation

The runner is given one command line and runs it **once per vector**:

```
python3 run.py --candidate "./my-verifier probe"
```

For each vector the runner:

1. starts your command exactly as given (no shell, argv split once by shell rules),
2. writes one JSON **request** object to stdin and closes stdin,
3. reads stdout to EOF and parses it as exactly one JSON **response** object.

Each invocation is independent. Nothing is carried between them; your program may
be a script, a compiled binary, or a shell wrapper. stderr is ignored except when
your program fails, in which case its last line is quoted in the report — put
diagnostics there freely.

## 2. The exit status is NOT the verdict

**Exit 0 whenever you produced an answer, including an answer of "no".**

"This signature does not verify" and "I crashed before deciding" are different
facts about your implementation, and a contract that encodes both as a nonzero
exit lets a broken program impersonate a strict one. So the verdict travels
inside the response body, and a nonzero exit means only: *no answer was
produced*. The runner scores that as `ERROR`, never as a pass and never as a
legitimate skip.

Exit nonzero only for genuine protocol failures — a malformed request, an
unreadable input, an internal panic.

## 3. The request

```json
{
  "warrant_conformance": "1",
  "id": "verify-sig/reject-04",
  "class": "verify-sig",
  "input": { "warrant_id": "…", "key": "…", "sig": "…" }
}
```

| field | type | meaning |
| --- | --- | --- |
| `warrant_conformance` | string | protocol version, always `"1"` |
| `id` | string | opaque vector identifier; echo it back verbatim |
| `class` | string | which question is being asked (§5) |
| `input` | object | the operands, shaped per class |

**The expected answer is never sent.** The runner keeps every expectation, so
there is nothing in the request for a candidate to echo back, and passing
requires actually computing the answer.

## 4. The response

Exactly one JSON object on stdout. Surrounding whitespace is fine; a second
object is not.

```json
{"warrant_conformance": "1", "id": "verify-sig/reject-04", "output": {"valid": false}}
```

or, if you do not implement this class:

```json
{"warrant_conformance": "1", "id": "verify-sig/reject-04",
 "unsupported": "no Ed25519 verification in this build"}
```

`id` MUST echo the request's `id`. Exactly one of `output` or `unsupported` MUST
be present.

`unsupported` is the **only** way to decline a vector. The runner scores it
`UNRUN` and names it in the report, and an UNRUN vector does not count toward a
grade. Silence, an empty stdout, or a crash are *not* ways to skip — they are
scored `ERROR`. This asymmetry is the point: a scan that finds nothing must not
look like a scan that never ran.

## 5. The classes

### `capabilities` — MANDATORY

Every candidate must answer this one; declaring it unsupported is a contract
violation.

* input: `{}`
* output:

```json
{"name": "my-verifier", "version": "1.2.0", "grade": "base",
 "classes": ["canon", "validate", "blob-hash", "sig-message", "verify-sig",
             "parse", "verify-store"]}
```

| field | meaning |
| --- | --- |
| `name`, `version` | free-form, printed in the report, never compared |
| `grade` | `"base"` or `"settlement"` — what you claim (§6) |
| `classes` | which classes you implement; declarative, printed in the report |

The runner tests the grade you claim. `classes` is informational — you may still
answer `unsupported` per request, and a class you list but decline is still
scored UNRUN.

### Base-grade classes

All hashes are lowercase hex. All byte strings are standard base64.

#### `canon` — SPEC §4, §8, §8.4

* input: `{"body": <JSON value>}`
* output: `{"canon_hex": "<hex of the canonical UTF-8 bytes>", "warrant_id": "<hex>"}`
* on a body that cannot be canonicalized (e.g. a non-integer number): `{"error": "<why>"}`

The WarrantID is `SHA-256(canonical_json(body))`. Canonicalization is the RFC 8785
JCS subset of SPEC §4: keys sorted by UTF-16 code unit, no insignificant
whitespace, integers only, `\b` and `\f` short escapes, lowercase `\u00xx` for
other controls, and `<` `>` `&` `/` U+2028 U+2029 emitted **raw**.

#### `validate` — SPEC §2, §3, §8.3

* input: `{"body": <JSON value>}`
* output: `{"valid": <bool>, "errors": ["<message>", …]}`

Only `valid` is compared; `errors` is for humans reading the report. Unknown
fields are invalid **recursively**, and `note` is bounded in code points, not
bytes.

#### `blob-hash` — SPEC §1, §8

* input: `{"bytes_base64": "<base64>"}`
* output: `{"hash": "<hex>"}` — plain `SHA-256` over the raw bytes, no framing.

#### `sig-message` — SPEC §5, §8.5

* input: `{"warrant_id": "<hex>"}`
* output: `{"message_hex": "<hex of the exact bytes a key signs>"}`
* on a malformed WarrantID: `{"error": "<why>"}`

47 bytes: the ASCII separator `warrant-sig-v1:` followed by the WarrantID's 32
**raw** bytes — not its hex text. Every way of building this wrong still
reproduces all five SPEC §8 WarrantIDs correctly, which is why it is vectored
separately.

#### `verify-sig` — SPEC §5, §8.3, §8.5

* input: `{"warrant_id": "<hex>", "key": "<hex>", "sig": "<hex>"}`
* output: `{"valid": <bool>}`

Verify the Ed25519 signature over the `sig-message` bytes. Small-order and
non-canonically-encoded public keys MUST fail for **any** message and signature.
Never raise — a malformed key, a short signature and a wrong key are all
`{"valid": false}`.

#### `parse` — SPEC §4 / RFC 7493 I-JSON

* input: `{"bytes_base64": "<base64>"}`
* output: `{"ok": <bool>}`, optionally with `"error"`

Would your record loader accept these raw bytes? Duplicate member names,
trailing content after the JSON value, a leading byte order mark, unpaired
surrogate escapes, `NaN`/`Infinity`, invalid UTF-8 and raw control characters in
strings are all MUST-REJECT. Stock JSON parsers accept several of these.

#### `verify-store` — SPEC §6

* input: `{"store_path": "<absolute path>", "grade": "base"}`
* output: `{"errors": <int>, "warnings": <int>}`
* on a path that is not a store: `{"error": "<why>"}`

A store directory holds `records/<WarrantID>.json` (each an envelope
`{"body": …, "sigs": [...]}`) and `blobs/<sha256>` (raw bytes at their own
address). Only `errors` is compared, and mostly as "at least one": SPEC §6 fixes
*which* conditions are errors, not how many any implementation reports for one
broken record, and pinning a number the spec does not fix would test our taste
rather than the format.

The runner copies each fixture to a temporary directory first, so you may read
freely and cannot damage the pack.

### Settlement-grade classes

Claim `"settlement"` only if you implement these. Claiming `"base"` and reaching
base is a complete, honest result — one of the three reference implementations
(`impl-rs`) is deliberately base-only.

#### `verify-store` at settlement grade — SPEC §7, §9, §12

* input: `{"store_path": "…", "grade": "settlement", "trust_config_path": "…"}`
* output: as above

`trust_config_path` may point at a file that does not exist or does not parse.
SPEC §12.3 requires you to **fail closed**: report exactly one error, do not
continue into a partial base-grade verification, and do not fall open to "no
trust configured". A requested settlement verification that could not construct
its trust did not happen and must not be reported as one that found nothing
wrong.

If you verify stores at base grade only, answer `unsupported` for
`grade: "settlement"` requests. Returning base-grade counts instead would report
a verification that never happened — which is the very failure §12.3 forbids.

#### `ski-run` — SPEC §3.1, §8.2

* input: `{"check_base64": "<base64>", "blobs_base64": {"<label>": "<base64>", …}}`
* output: `{"verdict": "pass"|"fail", "result_node_hash": "<hex>", "atp_spent": <int>}`

Re-execute the `ski@v1` check against the supplied object blobs. Address the
blobs by what their bytes actually hash to — the labels are the runner's, not
trusted addresses.

## 6. Grades

| grade | classes |
| --- | --- |
| `base` | `canon`, `validate`, `blob-hash`, `sig-message`, `verify-sig`, `parse`, `verify-store` |
| `settlement` | everything in base, plus `ski-run` and settlement-grade `verify-store` |

Store verification is SPEC §6, which is **base** grade. What settlement adds is
§7 tunnels and novelty, §5.1 key state, and §12's fail-closed trust
configuration.

The runner reports the grade **achieved**, which may be lower than the one
claimed. A grade is achieved only when every vector at or below it passed — one
`FAIL`, `ERROR` or `UNRUN` is enough to withhold it.

## 7. Exit statuses of the runner

| status | meaning |
| --- | --- |
| 0 | the claimed grade was achieved |
| 1 | at least one vector failed |
| 2 | nothing failed, but the claimed grade was not reached (something was UNRUN) |
| 3 | the candidate violated this contract |
| 4 | the pack does not match its own manifest |

2 is distinct from 0 on purpose. A run with gaps is not a clean run, and the
status has to say so or a scripted `run && publish` records a partial result as a
complete one.

## 8. A worked minimum

A candidate that implements nothing still runs, and reports honestly:

```python
#!/usr/bin/env python3
import json, sys
req = json.load(sys.stdin)
out = {"warrant_conformance": "1", "id": req["id"]}
if req["class"] == "capabilities":
    out["output"] = {"name": "stub", "version": "0", "grade": "base", "classes": []}
else:
    out["unsupported"] = "not implemented yet"
print(json.dumps(out))
```

That scores every vector `UNRUN`, achieves no grade, and exits 2 — which is the
correct description of it. Fill in one class at a time and watch the grade line
move.
