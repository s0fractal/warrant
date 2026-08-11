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

## 3. One atomic observation — `seal()` — and `input_root` over it

The verifier loads the store's byte view **once**. `input_manifest` and the
judgement are both derived from that view and from nothing else, so they
cannot disagree about what exists. Anything the seal refuses is not judged.

*(rev 2. Round 1 had two independent producers — a filesystem walk for the
manifest and the verifier for the judgement — and they diverged on the first
adversarial input.)*

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
| `role` | `record` \| `blob` \| `genesis` \| `trust-config` \| `other` |
| `state` | `read` \| `unreadable` \| `refused` |
| `sha256` | present **iff** `state == "read"` — lowercase hex over the bytes obtained |
| `reason` | present **iff** `state == "refused"` — `symlink` \| `not-a-regular-file` |

*(rev 2 — rev 1 required failed reads to appear while making `sha256`
mandatory over "raw bytes as read". There are no bytes after a failed read,
so the contract was internally unsatisfiable. `state` is a sum type for that
reason, and an entry that was never read carries **no** digest rather than a
`null` one: a null would be a claim about bytes that do not exist.)*

**A symlink is `refused`, not followed and not skipped.** Round 1 skipped it
silently while a live verifier follows it, so `input_root` committed to `[]`
over a store whose report judged one record — the manifest did not commit the
bytes the judgement used. Refusing is visible in the observation, and because
the judgement reads **only** the sealed view, the record is not judged either.
This is a deliberate difference from `@v0`, which follows symlinks, and it is
part of why `@v1` is a different tag.

**`input_root` commits to the observed universe, not to the subset that moved
the verdict.** A file no rule inspects still changes the root, and that is
intended: two stores differing by an uninterpreted file are two different
observations. What must never happen — and what round 1 allowed — is the
manifest and the judgement disagreeing about *what exists*.

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

**Round 1 was REFUTED, and round 2 is this text.** The refutation is worth
stating exactly, because all three failures were mine and two were in the
design rather than the code:

- A live verifier follows a symlinked record. Round 1's manifest walked the
  filesystem separately and skipped symlinks, so `input_root` committed to
  `[]` while the report judged one record. **A manifest that does not commit
  the bytes the judgement used is not a manifest** — which is why §3 is now
  one sealed observation rather than two producers.
- §3.1 required failed reads to appear while making `sha256` mandatory. That
  is unsatisfiable; hence the `state` sum type.
- Go's `encoding/json` escapes U+2028 even with `SetEscapeHTML(false)`, which
  **SPEC §4 forbids outright** — and the repository already ships 47
  machine-readable escaping vectors (§8.4) that decide it. I argued about
  escaping in prose while the normative battery sat unrun. Both encoders are
  now written out, and the battery runs in the gate.

**Round 2 result: the gate passes.** `proposals/wrt-004-model/` holds the two
implementations, a raw-byte corpus, the gate, and `mutate.py` — an
**executable** mutation suite, because round 1 claimed 9/9 in a README table
with no runner, which a reader could not check. 14/14 mutants are killed, and
a missing anchor counts as a failure so the suite cannot rot into a silent
pass. The gate and the mutants both run in CI; round 1's did not, so green
checks said nothing about it.

The materialized filesystem cases — symlink, unreadable file — and U+2028 are
permanent vectors now, not corpus entries: a JSON fixture cannot carry a
filesystem state.

**Both rounds allowed by §6 are now spent.** The judgement half remains
ungated and cannot be gated until §7's issue-code registry is closed.

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
