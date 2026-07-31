# The `warrant-conformance/1` candidate contract

This is everything your implementation must do to be testable by `run.py`. It is
deliberately short: one process, one JSON object in, one JSON object out.

**How long this actually takes**, measured by writing both skeletons rather than
estimated: the wire format plus `capabilities` and `canon` is an afternoon, and
that afternoon ends with a running program and one class green. `blob-hash` and
`sig-message` are minutes each. `parse` is a second afternoon, because stock JSON
parsers fail roughly half of its twenty MUST-REJECT vectors and you will end up
writing a scanner. `verify-sig` is about half a day, most of it discovering that
your crypto library does not reject small-order public keys. `verify-store` is a
day. `validate` cannot be done from this pack at all — it needs SPEC §2 and §3,
which the pack does not ship. `ski-run` is not an afternoon by any measure.

So: **base grade is a few days, and the first afternoon is real.** If any single
step takes far longer than that, the contract is at fault and that is a bug worth
reporting.

You do **not** need this repository, our Python, or any Warrant library to
satisfy it. The runner never imports, links against, or executes a reference
implementation — it only knows how to speak to yours.

## 0. What this document does and does not fix

This contract fixes the **protocol**: how the runner talks to your program, and
the exact shape of every request and response. For four of the nine classes that
is the whole job — `capabilities`, `blob-hash`, `sig-message` and `canon` are
specified here completely, and you can write them without reading anything else.

The remaining classes ask a question this document only *names*. `validate` needs
the record schema, `verify-store` needs the list of conditions that are errors,
`parse` needs the I-JSON profile, and `ski-run` needs the `ski@v1` evaluator —
all of which live in the Warrant specification, not here:

> **SPEC.md** — <https://github.com/s0fractal/warrant/blob/master/SPEC.md>
> at the revision whose §8.6 pins this pack's digest. Every `SPEC §n` reference
> below and in each vector's `spec` field points into that file.

Two things make the gap smaller than it looks. Every vector carries a `why` line
naming exactly what it is testing (`python3 run.py --list`, or read
`vectors/*.json` — they are plain JSON), and the classes are independent: you can
reach a real, honest report with `capabilities` alone and fill the rest in one at
a time. Working skeletons in Go and TypeScript, each implementing `canon` and
declining the rest, are in the repository under `conformance-skeletons/`.

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

**Once per vector** means 133 process starts, so per-process startup is paid 133
times. Each gets 30 seconds by default (`--timeout`); exceeding it is scored
`ERROR`, not `UNRUN`. A compile-on-demand command (`go run main.go`) or an
interpreter with a warm-up (`npx tsx`) is comfortably inside that — measured on a
laptop, the whole pack against `go run` is about 6 seconds and against `node`
about 7 — but a candidate that fetches anything over the network per invocation
is not, and should be wrapped in a prebuilt binary instead.

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

**Encodings.** A field whose name ends in `_base64` carries standard base64 with
padding; a field whose name ends in `_hex`, and every hash, key and signature,
carries **lowercase** hex with no prefix and no separators. Comparison is exact
string equality, so uppercase hex is a wrong answer, not a formatting choice.

#### `canon` — SPEC §4, §8, §8.4

* input: `{"body": <JSON value>}`
* output: `{"canon_hex": "<lowercase hex of the canonical UTF-8 bytes>", "warrant_id": "<hex>"}`
* on a body that cannot be canonicalized (e.g. a non-integer number): `{"error": "<why>"}`

The WarrantID is `SHA-256(canonical_json(body))` — the hash is over the canonical
**bytes**, never over their hex text. Canonicalization is the RFC 8785 (JCS)
subset SPEC §4 admits: UTF-8 output, object member names sorted by **UTF-16 code
unit**, no insignificant whitespace, integers only (a non-integer number is an
`error`, not a rounded value).

String escaping is normative and is where reimplementations actually split, so it
is spelled out rather than delegated to a library:

* emit the seven two-character short escapes `\"` `\\` `\b` `\t` `\n` `\f` `\r`
  — **all seven**. A serializer that writes `\u0009` `\u000a` `\u000d`
  for tab, newline and carriage return is wrong here, and three §8.4 vectors
  say so;
* escape every **other** code point below U+0020 as `\u00xx` with **lowercase**
  hex — and only those: U+007F (DEL) and the C1 block U+0080–U+009F are emitted
  raw;
* emit everything else raw as UTF-8, specifically including `<` `>` `&` `/`
  (Go's `encoding/json` escapes the first three unless you disable it) and
  U+2028 / U+2029 (JavaScript-oriented serializers escape these by habit);
* apply **no** Unicode normalization. NFC and NFD forms of the same text are
  different content and MUST hash differently; the pack vectors both.

Three of these — the short-escape set, the raw `<` `>` `&`, and the NFC/NFD pair
— are invisible to the SPEC §8 record vectors and are the reason the §8.4
battery exists.

#### `validate` — SPEC §2, §3, §8.3

* input: `{"body": <JSON value>}`
* output: `{"valid": <bool>, "errors": ["<message>", …]}`

Only `valid` is compared; `errors` is for humans reading the report. Unknown
fields are invalid **recursively**, and `note` is bounded in code points, not
bytes.

**This class is not implementable from this document.** The schema — required
members, permitted `decision` values, reason `kind`s and runtime tags, the hex64
fields, the `note` bound — is SPEC §2 and §3. Read those, then work through the
sixteen vectors in `vectors/validate.json`: each MUST-REJECT case names the rule
it violates in its `why`, so they double as a checklist. Write the twelve
negatives first. An implementation whose `validate` returns `true`
unconditionally passes all four positives here, and the runner gives that its own
headline for exactly that reason.

#### `blob-hash` — SPEC §1, §8

* input: `{"bytes_base64": "<base64>"}`
* output: `{"hash": "<hex>"}` — plain `SHA-256` over the raw bytes, no framing.

#### `sig-message` — SPEC §5, §8.5

* input: `{"warrant_id": "<64 lowercase hex characters>"}`
* output: `{"message_hex": "<hex of the exact bytes a key signs>"}`
* on a malformed WarrantID: `{"error": "<why>"}`

47 bytes: the 15 ASCII bytes of the separator `warrant-sig-v1:` — including the
trailing colon — followed by the WarrantID's 32 **raw** bytes, obtained by
hex-decoding the input, never its 64 bytes of hex text. Nothing is appended, and
nothing is hashed afterwards: the message is those 47 bytes.

    message = b"warrant-sig-v1:" || unhex(warrant_id)      # 15 + 32 = 47

Every way of building this wrong still reproduces all five SPEC §8 WarrantIDs
correctly, which is why it is vectored separately.

#### `verify-sig` — SPEC §5, §8.3, §8.5

* input: `{"warrant_id": "<hex>", "key": "<hex>", "sig": "<hex>"}` — `key` is a
  raw 32-byte Ed25519 public key as hex (no DER, no PEM, no multibase), `sig` is
  the raw 64-byte signature as hex. Both may be the wrong length on purpose.
* output: `{"valid": <bool>}`

Verify the Ed25519 signature over the `sig-message` bytes. Small-order and
non-canonically-encoded public keys MUST fail for **any** message and signature —
a check that neither Go's `crypto/ed25519` nor Node's `crypto` performs for you,
so if you delegate verification to a stock library you must add the key test in
front of it. Never raise — a malformed key, a short signature and a wrong key are
all `{"valid": false}`.

#### `parse` — SPEC §4 / RFC 7493 I-JSON

* input: `{"bytes_base64": "<base64>"}`
* output: `{"ok": <bool>}`, optionally with `"error"`

Would your record loader **accept** these raw bytes? This is a question about
acceptance, not about canonical form: insignificant whitespace and `\uXXXX`
escapes are legal *input* and MUST parse, even though canonical *output* has
neither. `ok` is about the bytes as a whole; where in your stack the rejection
happens is your business.

MUST-REJECT, and each is vectored:

* duplicate member names, at the top level and nested (RFC 7493; stock parsers
  silently keep the last, which is a canonicalization attack);
* a second JSON value, or any non-whitespace content, after the first value;
* a leading UTF-8 byte order mark (RFC 8259 says a receiver MAY ignore one —
  "MAY" is what a content-addressed format cannot afford);
* an unpaired surrogate escape, high or low (a valid surrogate **pair** is one
  astral code point and MUST parse);
* `NaN`, `Infinity`, `-Infinity` (Python's stock parser accepts all three);
* invalid UTF-8 anywhere;
* an unescaped control character inside a string;
* and the plain JSON-grammar violations: a number with a leading zero, a
  trailing comma, single-quoted names, truncated input.

Stock JSON parsers accept several of these, which is why the class exists.

#### `verify-store` — SPEC §6

* input: `{"store_path": "<absolute path>", "grade": "base"}`
* output: `{"errors": <int>, "warnings": <int>}`
* on a path that is not a store: `{"error": "<why>"}`

A store directory holds `records/<WarrantID>.json` (each an envelope
`{"body": …, "sigs": [...]}`) and `blobs/<sha256>` (raw bytes at their own
address). Only `errors` is compared, and mostly as "at least one": SPEC §6 fixes
*which* conditions are errors, not how many any implementation reports for one
broken record, and pinning a number the spec does not fix would test our taste
rather than the format. `warnings` is required in the response and is never
compared — report it honestly anyway, since it is what tells a human whether you
looked.

**Which conditions are errors** is the part you cannot guess, so here is the
split SPEC §6 fixes. An **ERR** is: a record that will not load or is not
schema-valid (§6(1)); a record whose body does not recompute to the WarrantID it
is filed under (§6(2)); a record left with no *valid* signature by its own
`body.actor.id` (§6(3)); and a `prior` edge naming a record the store does not
hold (§6(4)). A **WARN** — which does **not** raise `errors` — is: one invalid
signature among several that still leaves a valid one (§6(3)); an `under`,
`evidence`, `check`, `transcript` or `subject.hash` reference that resolves
nowhere, because blobs may legitimately live elsewhere (§6(5)); a `ts` that
decreases along a `prior` edge (§6(6)); and a `ski@v1` reason that was not
re-executed (§6(7)) — at base grade only.

One condition is an error and is not in that list, because it is §1 rather than
§6: a blob whose bytes do not hash to the filename it sits under. Both shipped
reference implementations once reported the `swapped-blob` fixture clean —
someone had replaced a cited policy blob wholesale and left it at the original
address. Recompute every blob address you read.

Going the other way: the pack ships no keyring, so a verifier that checks
key-to-actor binding (§5.1) cannot check it here. That is a WARN and MUST NOT
raise `errors` — the `clean` fixture expects exactly zero. "I could not check
this" is not "I checked this and it was fine", and it is also not an error.

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
wrong. Note the shape of the expectation: `{"errors": 1}` exactly, not "at least
one", because §12.3 fixes this count where §6 does not.

A trust config that is present and *parses* is a different case, even when it
configures nothing: `{"genesis_roots": []}` is a valid configuration, trust was
constructed, and the clean store verifies with zero errors. Missing and
unparseable fail closed; empty does not.

If you verify stores at base grade only, answer `unsupported` for
`grade: "settlement"` requests. Returning base-grade counts instead would report
a verification that never happened — which is the very failure §12.3 forbids.

#### `ski-run` — SPEC §3.1, §8.2

* input: `{"check_base64": "<base64>", "blobs_base64": {"<label>": "<base64>", …}}`
* output: `{"verdict": "pass"|"fail", "result_node_hash": "<hex>", "atp_spent": <int>}`

Re-execute the `ski@v1` check against the supplied object blobs. Address the
blobs by what their bytes actually hash to — the labels are the runner's, not
trusted addresses.

**This class is not implementable from this document either, and it is the
largest single piece of work in the pack**: `ski@v1` is a combinator evaluator
with a metered reduction budget, specified in SPEC §3.1, and `atp_spent` is a
count of reduction steps that your evaluator must agree on exactly — a verdict
reached by any other route is the defect SPEC §6(7) exists to forbid. There is
one vector. Leave it `unsupported` and claim `base` until you want it; `impl-rs`
does.

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

They are checked in the order 4, 3, 1, 2 — a run containing both an `ERROR` and a
`FAIL` exits 3, because "your program did not answer" has to be read before "your
program answered wrongly".

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
