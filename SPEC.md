# Warrant Format — Specification v0.2

**Status:** DRAFT. Key words MUST / MUST NOT / SHOULD / MAY per RFC 2119.
**Versioning:** a body declares its format in the `warrant` field (`"0.1"` or `"0.2"`). Validators MUST validate a body against the rules of its declared version; unknown versions make the record invalid. v0.2 adds exactly one thing: the `ski@v1` check runtime (§3.1). Everything else — fields, canonicalization, envelopes, verification, settlement — is unchanged, and every v0.1 record remains valid under v0.1 rules.
**Design rule:** two independent implementations MUST agree on every WarrantID and every verification outcome. Anything that cannot meet that bar stays out of this document.

## 1. Model

A **warrant** is an immutable, signed, content-addressed record of one decision. Records form a DAG via `prior`. All referenced artifacts (policies, checks, evidence, subjects) are blobs addressed by `SHA-256(bytes)`, stored in any content-addressed store (files, git objects, S3 — out of scope).

## 2. Body

The body is a JSON object with exactly these fields (unknown fields MUST make the record invalid):

| Field | Type | Req | Meaning |
| --- | --- | --- | --- |
| `warrant` | string | MUST | Format version, `"0.1"` or `"0.2"` |
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
- `runtime` — execution profile. `cmd@v1`: the check blob is executed as a command in an isolated container; exit 0 = `pass`, nonzero = `fail`. `ski@v1` (§3.1): available in `"0.2"` bodies; in `"0.1"` bodies it remains reserved and MUST be rejected.
- `verdict` is the actor's claim; anyone MAY re-run the check against the evidence and file their own warrant if they get a different verdict.
- `transcript` — hash of the check's output blob, so the claimed verdict is inspectable.

### 3.1. `ski@v1` — portable deterministic budget-bounded checks (v0.2)

The check blob is I-JSON (JCS-canonical, integers only — hashed like any blob):

```json
{ "ski": 1, "term": "<hex64 NodeHash>", "atp": <uint32>, "expect": "<hex64 NodeHash>" }
```

Verification re-runs the reduction and compares hashes:

1. Evaluate `eval(term, atp)` per **Σ-GLYPH Book I v0.5** (hash-thunk machine, size-priced ATP): https://github.com/s0fractal/sigma-glyph — anchored spec, two independent implementations, machine conformance vectors.
2. The warrant blob store IS the Σ-GLYPH CAS: every object the evaluation demands MUST resolve among the store's blobs (Σ-GLYPH genesis axioms are intrinsic and need no blobs).
3. Verdict: `pass` iff the result's NodeHash equals `expect`, else `fail`. Canonical DISSONANCE outcomes are nodes with fixed hashes, so expecting a failure mode needs no special casing — `expect` covers it uniformly.

Why this runtime exists: `cmd@v1` proves a claim to whoever trusts the container; `ski@v1` proves it to **anyone with the blobs** — bit-exact across implementations, terminating by construction, with work AND peak memory bounded by `atp` (Σ-GLYPH's `size − 1 ≤ spent` invariant). It is safe to re-verify a stranger's ski@v1 reason on your own machine; that cannot be said of re-running a stranger's shell script. Tools SHOULD treat `ski@v1` as the strongest reason kind: re-runnable without trust.

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

### 8.2. ski@v1 vectors (v0.2, `examples/ski/`)

A real portable check: *"`C1[λxy.x] S K` reduces to `S` within 20 ATP"* — Σ-GLYPH's TV-10, filed as a warrant whose reason anyone can re-run.

| Artifact | SHA-256 |
| --- | --- |
| SKI term (root NodeHash; 5 APPLY object blobs `*.bin`, genesis I/K/S intrinsic — no leaf blobs needed) | `97a2eedea8d8b3419dac73f1685814e7a7ccd85f232f3d1e085fb1f1917611ad` |
| `check.json` (JCS bytes: `{"ski":1, "term":…, "atp":20, "expect":H(S)}`) | `0c30960435e9c9302a6a1538682e5864f2a754475369979bd3d635543976b2ad` |
| accept warrant (`"warrant":"0.2"`), demo-seed signed | `8c9267bccbc217db2f3f16e6928acaf062a1c78443b2317985567b238ccfe8a0` |

A v0.2 implementation with a Σ-GLYPH Book I v0.5 oracle MUST re-run the check against the object blobs and obtain `pass` with `result = H(S)` and `atp_spent = 20`. A v0.1 implementation MUST reject the warrant body (ski@v1 reserved) — that rejection is itself conformant.

## 9. Non-goals (v0.1)

Consensus, ordering across actors, key distribution, blob transport, privacy/encryption, and any opinion about how agents *make* decisions. Warrant records decisions; it does not take them.
