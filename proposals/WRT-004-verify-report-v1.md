# WRT-004: `warrant.verify-report@v1` — a report that names what it read

**Status:** DRAFT rev 1 (2026-08-11) — **design only. NOT ADOPTED, NOT
REGISTERED.** No threshold warrant, no roster signature, no `@v1` bytes
emitted by any implementation in this repository. §13.3 registration requires
Specification Required, a published JSON Schema (§14.2), and a statement of
what changed — this file is the third of those and a draft of the first.

**Direction.** WRT-003 asked whether Warrant should specify a *second*
machine-readable artifact and answered **no**: one artifact family, owned by
Warrant. This is that decision made concrete. The line it holds: **each
protocol judges its own bytes; other protocols compose judgements without
appropriating them.**

**`warrant.verify-report@v0` is immutable and stays supported.** §11.4 makes
it a closed schema and forbids adding a field to it, ever. `@v1` is a
different tag, not a revision, and a consumer that asked for `@v0` never
receives `@v1` (§11.4).

---

## 1. What changed from `@v0`, and why (the §13.3 statement)

| Change | Why |
|---|---|
| **`input_manifest` + `input_root`** — the report names every file it read, ordered, with digests | `@v0` does not say which bytes it ranged over. Two `@v0` reports over two entirely different stores with the same counts and finding shapes are **indistinguishable documents** |
| **Structured issues** — `code` + `locator`, alongside the human `message` | `@v0` findings carry prose. A consumer that must act on *which* problem occurred parses English. Measured: a real adapter had to enumerate every message prefix this implementation emits and fail closed on the rest — and still missed one |
| **Per-record / per-signature / per-reason results** | `@v0` is an aggregate plus a finding list. Nothing carries per-source structure |
| **`producer`, explicitly non-authoritative** | `@v0` has no producer block at all; naming the producer without marking it unauthoritative would invite exactly the trust it cannot support |

Everything else `@v0` guarantees is kept: `ok == (errors == 0)`, `grade`,
deterministic emission order, and the same core as the text verifier.

## 2. Shape

```
warrant.verify-report@v1
├── report          "warrant.verify-report@v1"
├── input_manifest
│   ├── entries[]   ordered [{path, sha256, role}]
│   └── input_root  domain-separated hash over the manifest
├── judgement
│   ├── grade, trust_config_digest, execution_policy
│   ├── ok, errors, warnings
│   ├── records[]   per-record results, with signatures[] and reasons[]
│   └── findings[]  structured: {level, code, subject, locator, message}
└── producer        local, explicitly non-authoritative
```

## 3. `input_root` — Warrant's own, depending on nothing

```
input_root = sha256( "warrant.verify-report.input@v1:" || JCS(entries) )
```

**Domain-separated** by that ASCII prefix, so the digest of an entry list can
never be confused with a digest of anything else this project hashes.

**No dependency on `ecosystem.snapshot@v0`, or on any external bundling
format.** WRT-003 §3.1 named such a dependency as the strongest argument
against it; this design removes the argument rather than answering it. A
composer (SEV, or anything else) may *prove* that its own bundle descriptor
and this `input_manifest` cover the same bytes — that proof is a **bridge**,
computed by the composer, and it is not a new judgement and not Warrant's
concern.

### 3.1 `entries[]`

Every file the verifier **read or attempted to read**, including ones that
failed to load. A record that could not be parsed is exactly the case where
naming the bytes matters most; omitting it would let a report describe a
store it silently could not see.

| Member | Value |
|---|---|
| `path` | store-relative, `/`-separated, no `.` or `..` segment, no leading `/` |
| `sha256` | lowercase hex over the file's raw bytes as read |
| `role` | `record` \| `blob` \| `genesis` \| `trust-config` \| `other` |

**Order: ascending by the UTF-8 bytes of `path`.** Stated as bytes on
purpose. UTF-8 preserves code-point order, so a Go implementation sorting
native `string` (bytes) and a Python implementation sorting `str` (code
points) agree without either doing anything special — which is the whole
point of choosing this and not the UTF-16 code-unit order that JCS imposes on
*object keys*. Duplicate `path` values are not permitted.

## 4. Structured findings

`@v0`'s `{level, subject, message}` becomes
`{level, code, subject, locator, message}`.

- **`code`** — from a closed registry (§7 below). Adding a code is a
  registry action, not a producer's choice.
- **`locator`** — where in the named input, as
  `{kind: "path"|"json-pointer"|"global", value: …}`. A finding that cannot
  be placed uses the `global` kind with a reserved subject.
- **`message`** — human text, explicitly **non-normative**, and explicitly
  **not** a stable interface. A consumer that branches on it is wrong.

## 5. What this is not

Unsigned. No WarrantID. No settlement authority. `producer` is local, and
nothing in the report proves the named verifier existed or ran.

**A digest makes a document content-addressable; it says nothing about
provenance or truth.** Reliance requires **re-running** the verification, or
an external signed attestation binding this report to a producer. `input_root`
makes "what was judged" unambiguous — it does not make "who judged it"
believable, and `@v1` must not be described as if it did.

## 6. The kill gate

This direction is **abandoned** unless it passes, and the gate is written
before the code on purpose.

1. **Two independent implementations** — the Python and Go verifiers already
   in this repository — emit the report over a **shared raw-byte corpus**.
2. **Byte-identical** `input_manifest` + `judgement` for the same store,
   trust config, grade and execution policy. `producer` is excluded from the
   comparison, by design.
3. **Every mutation moves `input_root`**: change one byte in any file, rename
   a path, add a file, remove a file.
4. **At most two adversarial rounds.** If byte identity is not reached, the
   upstream direction closes and the receipt stays a SEV-side construction
   over `@v0`.

The gate is deliberately harsher than `@v0`'s, which requires only that two
implementations agree on *counts and exit status*. Byte identity is the whole
claim; a design that cannot reach it should not be registered.

## 7. Open, and deliberately not decided here

- **The issue-code registry** — the closed set for §4. This is exactly what
  sank WRT-003: an artifact whose codes were an "extension point" let two
  valid reports over identical inputs hash differently. It must be **closed
  before** `@v1` is registered, not after.
- **Locator grammar** — the exact JSON-pointer subset, and what `global`
  admits beyond §11.1's reserved subjects.
- **Reason results** — the shape for `because[]` outcomes, which touches
  §13.1 runtime semantics and is Σ-GLYPH's domain for `ski@v1`.
- **Parser precedence** — whether a composite malformed input reports the
  first fault or accumulates. `@v0`'s implementations short-circuit; that
  behaviour is unspecified, and two implementations can differ while passing
  every existing fixture.

## 8. What a decision looks like

Registration under §13.3 is Specification Required plus a published JSON
Schema, and adoption is a threshold warrant signed by roster keys (AGENTS.md
rule 2). Nothing in this file substitutes for either.

The next step is not a decision — it is the gate in §6. If it fails, this
file is closed the way WRT-003 was: retained for its reasoning, marked as
not taken.
