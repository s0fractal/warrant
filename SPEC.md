# Warrant Format — Specification v0.3

**Status:** DRAFT. Key words MUST / MUST NOT / SHOULD / MAY per RFC 2119.
**Versioning:** a body declares its format in the `warrant` field (`"0.1"` or `"0.2"`). Validators MUST validate a body against the rules of its declared version; unknown versions make the record invalid. v0.2 added exactly one thing: the `ski@v1` check runtime (§3.1). **v0.3 adds no body schema at all** — it specifies settlement semantics (§7), multi-root stores (§9), and key state (§5.1): document-level rules that activate only through v0.3 policy blobs and verifier configuration. Every v0.1/v0.2 record remains schema-valid under its declared version, and v0.3 rules MUST NOT turn any of them into a schema error. (Adopted from GOV-001 rev 4 after a three-family adversarial gate: Codex, Gemini 3.1 Pro, DeepSeek v4 Pro — see `proposals/` and `reviews/`.)
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

### 5.1. Key state: binding, rotation, thresholds (v0.3)

Key state derives from key-state warrants — **any cache is an implementation detail; the warrants are the truth.** Implementations MAY derive an internal key-state cache; any such cache MUST be purely deterministic from the DAG of key-state warrants. No interchangeable keyring file format is mandated. With key state configured (genesis keys pinned in the verifier's local trust configuration plus derived rotations), verifiers MUST report each signature as `bound` or `unbound`; without it, the v0.2 unverified-binding warning stands. Bound/unbound is a report unless a v0.3 policy explicitly makes bound signatures required for settlement-grade verification.

**Rotation is a warrant:** an `accept` whose subject is the new key blob. A rotation MUST include a valid signature by the incoming key as proof of possession and MUST be authorized under the actor/store's current key policy. If that policy has a threshold, the rotation MUST satisfy it using keys already bound before the rotation; the incoming key's proof-of-possession signature does not count toward the threshold. The outgoing key's signature MAY be required by policy for ordinary rotation, but MUST NOT be sufficient authorization when the store has a multi-actor threshold policy. Emergency replacement of a suspected-compromised outgoing key SHOULD be authorized by quorum without requiring the outgoing key. **Revocation is a warrant:** a `supersede` of the rotation warrant that introduced the key, authorized under the same current-policy rule.

**Ordering:** key validity derives from accepted rotation/revocation warrants in **DAG order**, never from wall-clock trust in `ts` alone; a `ts` outside non-decreasing prior order remains a §6 warning and MUST NOT extend or resurrect a key. Only *authorized* key-state warrants can conflict — a record failing current-policy authorization is an invalid record, not a conflict. A key-state warrant is conflicting only if no later authorized warrant for the same actor is its DAG descendant: warrants ordered by the DAG are never a conflict; only maximal, mutually unordered warrants trigger this rule. On conflict, verifiers MUST report `WARN: key-state conflict`, and the conflicted actor's key MUST NOT count toward any quorum until a later warrant — authorized by the unconflicted remainder of the quorum — resolves it; if the threshold would become unsatisfiable, it is reduced to exclude the conflicted actor strictly for conflict resolution.

**Threshold policy grammar.** A v0.3 threshold policy blob MUST be JCS-canonical JSON:

```json
{ "warrant_policy": "0.3", "threshold": { "min_sigs": 2, "actors": ["a@x", "b@y", "c@z"] } }
```

`min_sigs` MUST be a positive integer ≤ `len(actors)`; `actors` MUST be nonempty and unique; unknown fields inside `threshold` make the policy invalid. Records filed under an invalid threshold policy are settlement-inactive and MUST produce `ERR: invalid threshold policy` for settlement-grade verification. Opaque v0.1/v0.2 policy blobs MUST NOT be interpreted as threshold policies.

## 6. Verification (MUST)

`verify(store)` checks, for every envelope: (1) body is schema-valid with no unknown fields; (2) WarrantID recomputes; (3) all signatures verify; (4) every `prior` resolves to a stored warrant; (5) every `under`, `check`, `evidence`, `subject.hash` either resolves in the blob store or is reported as `unresolved` (unresolved is a warning, not corruption — blobs may live elsewhere); (6) `ts` is non-decreasing along each `prior` edge (violation = warning).

`why(id)` walks `prior` edges backward, printing decision → reasons → policy anchors, verifying as it goes.

## 7. Settlement (v0.3)

An `accept` or `reject` whose subject is a *question* blob settles it. `supersede` marks an earlier warrant as replaced: its `subject.hash` MUST be the superseded WarrantID (a missing subject is an ERR, §6).

**Tunnel.** A settling warrant's tunnel has a record set and a blob set. The record set is the transitive closure of `prior` edges through stored warrants. The blob set is the union of `under`, `evidence`, `subject.hash`, `check`, and `transcript` hashes cited by those records. Verifiers MUST NOT recursively parse arbitrary blobs for additional tunnel links unless a runtime-specific rule explicitly says so. A blob hash that is also the WarrantID of a stored record is still a blob reference unless it appears in `prior` or a field whose rule explicitly names WarrantIDs.

**Foreclosure.** A blob forecloses only the claims some reason in the tunnel actually makes about it: mere presence in an `evidence` array forecloses nothing. An unresolvable blob forecloses nothing (what cannot be read cannot have been reasoned over); a record with unresolvable settlement-critical references is settlement-inactive until they resolve — without changing its WarrantID, base verification result, or the §6 warning status of v0.1/v0.2 records.

**Re-litigation.** A re-litigation warrant MUST carry at least one of: (a) an evidence hash absent from the tunnel's blob set, or (b) a **new demonstrable consequence** of evidence already present — a check, all of whose blobs are resolvable, that re-runs to a previously absent **outcome fingerprint** within the settling tunnel.

Outcome fingerprints: `ski@v1` — `{runtime, term, expect, verdict, result_node_hash}`; `cmd@v1` — `{runtime, sorted evidence hashes, verdict, transcript hash}`, with `transcript` REQUIRED for §7(b) use. A check whose outcome fingerprint already appears in the tunnel is not new even if the check blob hash differs. Only tunnel reasons supplying all required fields count toward the tunnel's fingerprint set — a reason lacking a required field (e.g. `transcript`) cannot block novelty. (The `evidence` array is not ordered by JCS; the fingerprint sorts hex hashes ascending lexicographically.) Prose MAY explain why a consequence matters, but prose is not part of the novelty test and alone never re-opens settlement.

**Novelty ≠ relevance.** The format layer decides only whether an outcome is new; whether a novel check is *relevant* to the settled subject — or a strawman testing something adjacent — MUST be decided by the active settlement policy, not the core format. Tools SHOULD refuse to file re-litigation warrants carrying neither (a) nor (b); verifiers SHOULD flag them `WARN: re-litigation cites nothing new`. NOTE: because novelty is purely syntactic, a permissive-policy store may accumulate unbounded fingerprint-distinct but irrelevant re-litigations; implementations SHOULD provide configurable limits — a policy choice, not a format requirement.

§7 is itself challengeable under (b): a check demonstrating that the rule forces a wrong settlement is admissible evidence against the rule.

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

## 9. Multi-root stores (v0.3)

A store is a DAG. A **root** is a record with empty `prior`. A root is **well-signed** if its filing signature is valid (and bound, where key state is configured). A root is **settlement-active** only if either (1) it is listed in the verifier's local trust configuration as a genesis root for this store, or (2) it is adopted by a settlement-active root through an `accept` warrant whose `subject.hash` is the WarrantID of the root to be adopted and whose signatures satisfy the adopting root's current settlement policy, including any threshold rule. Verifiers MAY verify inactive roots for local integrity but MUST exclude them from settlement and foreclosure calculations and MUST report `WARN: unadopted root`.

**Adoption is scoped:** adopting root A makes root B settlement-active for A's jurisdiction only. Two roots that never reference each other are separate jurisdictions sharing a blob store — by design.

**Portable jurisdiction:** stores SHOULD contain `genesis.json` in the store root — JCS-canonical `{"roots": ["<WarrantID>", ...]}`. The file is **advisory**; verifiers MUST NOT treat it as a trust anchor — it is mutable, unsigned, and editable by anyone with store write access. Before using its listed roots as settlement-active, a verifier MUST independently verify its authenticity (typically a pinned hash in local trust configuration, or explicit user acceptance). If present but unverified: `WARN: genesis.json unverified`, and its contents MUST NOT be used for settlement.

## 10. Non-goals

Consensus, ordering across actors, blob transport, privacy/encryption, PKI beyond §5.1's key-state warrants, and any opinion about how agents *make* decisions. Warrant records decisions; it does not take them.
