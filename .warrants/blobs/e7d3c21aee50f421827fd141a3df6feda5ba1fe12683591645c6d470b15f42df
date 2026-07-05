# Warrant Format — Specification v0.1

**Status:** DRAFT. Key words MUST / MUST NOT / SHOULD / MAY per RFC 2119.
**Design rule:** two independent implementations MUST agree on every WarrantID and every verification outcome. Anything that cannot meet that bar stays out of this document.

## 1. Model

A **warrant** is an immutable, signed, content-addressed record of one decision. Records form a DAG via `prior`. All referenced artifacts (policies, checks, evidence, subjects) are blobs addressed by `SHA-256(bytes)`, stored in any content-addressed store (files, git objects, S3 — out of scope).

## 2. Body

The body is a JSON object with exactly these fields (unknown fields MUST make the record invalid):

| Field | Type | Req | Meaning |
| --- | --- | --- | --- |
| `warrant` | string | MUST | Format version, `"0.1"` |
| `decision` | string | MUST | `"propose"` \| `"accept"` \| `"reject"` \| `"supersede"` |
| `subject` | object | MUST | `{"hash": <hex64>, "note": <string, optional, ≤200 chars>}` — the thing decided |
| `under` | array | MUST | ≥1 hex64 hashes of the policy blobs in force |
| `because` | array | MUST* | Reasons (§3). *`reject` and `supersede` MUST have ≥1; `accept` SHOULD have ≥1; MAY be `[]` only for `propose` |
| `evidence` | array | MUST | ≥0 hex64 hashes of input blobs the decision relied on |
| `actor` | object | MUST | `{"id": <string>}` — stable actor identifier |
| `prior` | array | MUST | ≥0 WarrantIDs this record responds to or follows |
| `ts` | integer | MUST | Unix seconds, UTC |

All hashes are lowercase hex, 64 chars. All numbers in a body MUST be integers (no floats anywhere — this keeps canonicalization trivial and exact).

## 3. Reasons

Each element of `because` is one of:

```json
{ "kind": "prose", "text": "<string>" }

{ "kind": "check", "check": "<hex64>", "runtime": "cmd@v1",
  "verdict": "pass" | "fail", "transcript": "<hex64, optional>" }
```

- `check` — hash of the check blob (script, test command, etc.).
- `runtime` — execution profile. v0.1 defines `cmd@v1`: the check blob is executed as a command in an isolated container; exit 0 = `pass`, nonzero = `fail`. `ski@v1` (portable deterministic budget-bounded checks) is **reserved** and MUST be rejected by v0.1 implementations.
- `verdict` is the actor's claim; anyone MAY re-run the check against the evidence and file their own warrant if they get a different verdict.
- `transcript` — hash of the check's output blob, so the claimed verdict is inspectable.

**Protocol rule (MUST):** a `reject` whose every reason is `prose` is valid but MUST be marked by tools as *unverifiable*; tools SHOULD prefer at least one `check` reason. Rhetoric is legal; it just doesn't count as proof.

## 4. Canonicalization and identity (MUST)

```
WarrantID = SHA-256( canonical_json(body) )
```

`canonical_json` is RFC 8785 (JCS). Because bodies are I-JSON with integers only, this is exactly: UTF-8, object keys sorted by code point, no insignificant whitespace, no float formatting questions. Reference (Python): `json.dumps(body, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode('utf-8')`.

## 5. Envelope and signatures (MUST)

A stored warrant is an envelope:

```json
{ "body": { ... }, "sigs": [ { "actor": "<id>", "key": "<hex64 Ed25519 pubkey>", "sig": "<hex128>" } ] }
```

- `sig` = Ed25519 signature over the 32 raw bytes of the WarrantID.
- ≥1 signature MUST be present and MUST include one whose `actor` equals `body.actor.id`.
- Additional co-signatures MAY be appended without changing the WarrantID (the envelope is not hashed; the body is).
- Key↔actor binding is out of scope for v0.1 (use your existing PKI/keyring); implementations MUST verify signatures against the stated key and report the binding as unverified if no keyring is configured.

## 6. Verification (MUST)

`verify(store)` checks, for every envelope: (1) body is schema-valid with no unknown fields; (2) WarrantID recomputes; (3) all signatures verify; (4) every `prior` resolves to a stored warrant; (5) every `under`, `check`, `evidence`, `subject.hash` either resolves in the blob store or is reported as `unresolved` (unresolved is a warning, not corruption — blobs may live elsewhere); (6) `ts` is non-decreasing along each `prior` edge (violation = warning).

`why(id)` walks `prior` edges backward, printing decision → reasons → policy anchors, verifying as it goes.

## 7. Settlement (protocol, not format)

An `accept` or `reject` whose subject is a *question* blob settles it. Re-opening a settled subject MUST be done via a new warrant whose `evidence` contains at least one hash absent from the entire prior tunnel of the settling warrant. Tools SHOULD refuse to file re-litigation warrants that cite nothing new. `supersede` marks an earlier warrant as replaced: its `subject.hash` MUST be the superseded WarrantID.

## 8. Test vectors (MUST PASS)

Deterministic vectors; full envelopes in `examples/`. Seed for the demo Ed25519 key: ASCII `warrant-demo-seed-000000000000000` (first 32 bytes); pubkey `5e06999f4dd20f375c9292e39f722a77a67a5c5cf8a5fd74bbb35f99dc4a8cc5`.

| Artifact | SHA-256 |
| --- | --- |
| `examples/policy.txt` | `cb3a0afe6ee6219867b9c3f9b860080918fe1042f315fe02ff62300f780beb73` |
| `examples/check.sh` | `05d234bec21803c6fa007d848c1773b9fd05cfdf852d6d09542ed3b127c02b6c` |
| propose WarrantID | `00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1` |
| reject WarrantID | `5f5d4035a4ae04a3eec255105eee7dda7c98daaf9962c92cbbbad38ac21509d8` |
| accept WarrantID | `bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78` |

The three example warrants form the chain propose → reject (failing check + clause citation) → accept (passing check), each `prior`-linked, each signature verifying against the WarrantID. An implementation MUST reproduce all five hashes byte-exactly and MUST verify all three signatures.

## 9. Non-goals (v0.1)

Consensus, ordering across actors, key distribution, blob transport, privacy/encryption, and any opinion about how agents *make* decisions. Warrant records decisions; it does not take them.
