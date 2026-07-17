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
| `subject` | object | MUST | `{"hash": <hex64>, "note": <string, optional, ≤200 Unicode code points>}` — the thing decided |
| `under` | array | MUST | ≥1 hex64 hashes of the policy blobs in force |
| `because` | array | MUST* | Reasons (§3). *`reject` and `supersede` MUST have ≥1; `accept` SHOULD have ≥1; MAY be `[]` only for `propose` |
| `evidence` | array | MUST | ≥0 hex64 hashes of input blobs the decision relied on |
| `actor` | object | MUST | `{"id": <string>}` — stable actor identifier |
| `prior` | array | MUST | ≥0 WarrantIDs this record responds to or follows |
| `ts` | integer | MUST | Unix seconds, UTC, in the inclusive range `0..9223372036854775807` (int64) |

All hashes are lowercase hex, 64 chars. All numbers in a body MUST be integers (no floats anywhere — this keeps canonicalization trivial and exact). A body with a negative or out-of-int64-range integer field is schema-invalid; implementations MUST NOT silently clamp, wrap, or truncate numeric fields (an unchecked 64-bit narrowing is exactly the kind of silent verifier split this rule exists to prevent).

**The unknown-field rule is recursive (MUST).** It applies not only to the body but to every object the schema names: `subject` (exactly `hash`, optional `note`), `actor` (exactly `id`), and each reason object (§3). An unknown member anywhere in that tree makes the record invalid. Leaving nested strictness implicit is a silent verifier split: one implementation accepts an extra key another rejects, while both compute the same WarrantID.

**String lengths are measured in Unicode code points (MUST), never bytes or UTF-16 units.** `subject.note` is ≤200 code points. Byte-length and code-point-length disagree for any non-ASCII string — exactly the silent split the integers-only rule guards against for numbers.

## 3. Reasons

Each element of `because` is one of:

```json
{ "kind": "prose", "text": "<string>" }

{ "kind": "check", "check": "<hex64>", "runtime": "cmd@v1",
  "verdict": "pass" | "fail", "transcript": "<hex64, optional>" }
```

- `check` — hash of the check blob (script, test command, etc.).
- `runtime` — execution profile. `cmd@v1`: the check blob is executed as a command in an isolated container; exit 0 = `pass`, nonzero = `fail`. `ski@v1` (§3.1): available in `"0.2"` bodies; in `"0.1"` bodies it remains reserved and MUST be rejected. Any other `runtime` value makes the record invalid (MUST): a validator MUST reject an unknown runtime rather than accept-and-warn, so a forward-dated runtime cannot mean "valid" to one implementation and "invalid" to another.
- `verdict` is the actor's claim; anyone MAY re-run the check against the evidence and file their own warrant if they get a different verdict.
- `transcript` — hash of the check's output blob, so the claimed verdict is inspectable.

### 3.1. `ski@v1` — portable deterministic budget-bounded checks (v0.2)

The check blob is I-JSON (JCS-canonical, integers only — hashed like any blob):

```json
{ "ski": 1, "term": "<hex64 NodeHash>", "atp": <uint32>, "expect": "<hex64 NodeHash>" }
```

Verification re-runs the reduction and compares hashes:

1. Evaluate `eval(term, atp)` per **Σ-GLYPH Book I v0.5** (hash-thunk machine, size-priced ATP): https://github.com/s0fractal/sigma-glyph — anchored spec, two independent implementations, machine conformance vectors. The URL is a convenience, not the trust anchor: an implementation MUST pin the Book I ruleset it evaluates against by version and content (the vendored/bundled oracle it ships, or a pinned spec-document hash), so `ski@v1` semantics cannot be changed under it by an edit or force-push to a repository. `ski@v1` names Book I **v0.5** specifically; a later Book I is a different runtime tag.
2. The warrant blob store IS the Σ-GLYPH CAS: every object the evaluation demands MUST resolve among the store's blobs (Σ-GLYPH genesis axioms are intrinsic and need no blobs).
3. Verdict: `pass` iff the result's NodeHash equals `expect`, else `fail`. Canonical DISSONANCE outcomes are nodes with fixed hashes, so expecting a failure mode needs no special casing — `expect` covers it uniformly.

Why this runtime exists: `cmd@v1` proves a claim to whoever trusts the container; `ski@v1` proves it to **anyone with the blobs** — bit-exact across implementations, terminating by construction, with work AND peak memory bounded by `atp` (Σ-GLYPH's `size − 1 ≤ spent` invariant). It is safe to re-verify a stranger's ski@v1 reason on your own machine; that cannot be said of re-running a stranger's shell script. Tools SHOULD treat `ski@v1` as the strongest reason kind: re-runnable without trust.

**Re-execution budget.** `atp` is a `uint32`, so a single reason may legally demand up to ~4.3×10⁹ ATP of work and memory. Termination is guaranteed, but a verifier that re-runs arbitrary strangers' checks MUST bound the work it will spend: it MAY refuse to re-execute a reason whose `atp` exceeds a locally-configured budget, and MUST then report the reason as **unverified** (the §6 severity below) — never as `pass`/`fail`, and never as a silent skip. A refusal is not a verdict. Interoperating verifiers SHOULD share a default budget so they agree by default; two verifiers configured with different budgets MAY disagree on whether a given over-budget reason was re-executed, and that divergence is a deliberate local-policy choice, not a schema split. (The reference implementations default to 100,000,000 ATP, overridable by configuration.)

**Protocol rule (MUST):** a `reject` whose every reason is `prose` is valid but MUST be marked by tools as *unverifiable*; tools SHOULD prefer at least one `check` reason. Rhetoric is legal; it just doesn't count as proof.

## 4. Canonicalization and identity (MUST)

```
WarrantID = SHA-256( canonical_json(body) )
```

`canonical_json` is RFC 8785 (JCS). Because bodies are I-JSON with integers only, this is exactly: UTF-8, object keys sorted, no insignificant whitespace, no float formatting questions. Reference (Python): `json.dumps(body, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode('utf-8')`.

**String escaping is normative (MUST), not left to a library default.** Emit the two-character short escapes `\"` `\\` `\b` `\t` `\n` `\f` `\r`; escape every other code point below U+0020 as `\u00xx` with **lowercase** hex; emit every other character — including `<` `>` `&`, `/`, and all non-ASCII — as raw UTF-8. Do **not** escape `<` `>` `&` (Go's `encoding/json` does this by default: it MUST be disabled), do **not** `\u`-escape U+2028/U+2029, and do **not** use uppercase hex or the `\uXXXX` long form where a short escape applies. These are the classic JCS reimplementation splits; the §8 example vectors don't exercise them, so a conformant implementation MUST also agree on the escaping battery in `tests/differential.py`.

**Key ordering:** JCS sorts object member names by UTF-16 code unit. Every key this schema admits is fixed ASCII, for which UTF-16-unit order, Unicode-code-point order, and UTF-8 byte order coincide — so `sort_keys` (code point) and a bytewise sort are both correct here. Any future version that admits free-form object keys MUST sort by UTF-16 code unit per RFC 8785, not by code point.

**Duplicate member names are invalid (MUST).** Bodies and all schema blobs are I-JSON (RFC 7493): an object with a repeated member name is malformed and MUST be rejected, not silently resolved last-wins. Stock JSON parsers (Python's `json`, Go's `encoding/json`) keep the last occurrence silently; an implementation MUST detect and reject duplicates so a dup-key object cannot mean "malformed" to a strict reimplementation and "last-wins" to a lenient one.

## 5. Envelope and signatures (MUST)

A stored warrant is an envelope:

```json
{ "body": { ... }, "sigs": [ { "actor": "<id>", "key": "<hex64 Ed25519 pubkey>", "sig": "<hex128>" } ] }
```

- `sig` = Ed25519 signature over the 32 raw bytes of the WarrantID. Verification is pure Ed25519 (RFC 8032, no context, no pre-hash): the message is the 32-byte WarrantID itself.
- **Verification acceptance is pinned (MUST):** a verifier MUST reject a signature whose `S` scalar is non-canonical (`S ≥ L`) and MUST reject a malformed (non-canonical) public-key or signature-point encoding. This closes the well-known EdDSA verifier splits ("Taming the many EdDSAs") where a crafted envelope verifies under one library and not another. NOTE (known residual): libraries still differ on cofactored vs. cofactorless verification and on small-order public keys; those cases require an attacker-chosen key and are flagged here for a future hardening vector — an implementation SHOULD prefer a strict RFC 8032 cofactorless verifier.
- ≥1 signature MUST be present and MUST include one whose `actor` equals `body.actor.id` and which verifies. If no *valid* signature by `body.actor.id` is present, the record is invalid (§6 ERR).
- Additional co-signatures MAY be appended without changing the WarrantID (the envelope is not hashed; the body is). **A co-signature that fails to verify is reported and EXCLUDED, not fatal (MUST):** because anyone with store write access can append envelope signatures, a single junk co-signature MUST NOT be able to invalidate a record that still carries a valid signature by `body.actor.id`. An invalid signature is a §6 WARN; only the *absence* of a valid actor signature is an ERR. (For settlement thresholds, §5.1, an invalid signature simply does not count.)
- Key↔actor binding is out of scope for v0.1 (use your existing PKI/keyring); implementations MUST verify signatures against the stated key and report the binding as unverified if no keyring is configured.

### 5.1. Key state: binding, rotation, thresholds (v0.3)

Key state derives from key-state warrants — **any cache is an implementation detail; the warrants are the truth.** Implementations MAY derive an internal key-state cache; any such cache MUST be purely deterministic from the DAG of key-state warrants. No interchangeable keyring file format is mandated. With key state configured (genesis keys pinned in the verifier's local trust configuration plus derived rotations), verifiers MUST report each signature as `bound` or `unbound`; without it, the v0.2 unverified-binding warning stands. Bound/unbound is a report unless a v0.3 policy explicitly makes bound signatures required for settlement-grade verification.

**Rotation is a warrant:** an `accept` whose subject is the new key blob. A rotation MUST include a valid signature by the incoming key as proof of possession and MUST be authorized under the actor/store's current key policy. If that policy has a threshold, the rotation MUST satisfy it using keys already bound before the rotation; the incoming key's proof-of-possession signature does not count toward the threshold. The outgoing key's signature MAY be required by policy for ordinary rotation, but MUST NOT be sufficient authorization when the store has a multi-actor threshold policy. Emergency replacement of a suspected-compromised outgoing key SHOULD be authorized by quorum without requiring the outgoing key. **Revocation is a warrant:** a `supersede` of the rotation warrant that introduced the key, authorized under the same current-policy rule.

**Ordering:** key validity derives from accepted rotation/revocation warrants in **DAG order**, never from wall-clock trust in `ts` alone; a `ts` outside non-decreasing prior order remains a §6 warning and MUST NOT extend or resurrect a key. Only *authorized* key-state warrants can conflict — a record failing current-policy authorization is an invalid record, not a conflict. A key-state warrant is conflicting only if no later authorized warrant for the same actor is its DAG descendant: warrants ordered by the DAG are never a conflict; only maximal, mutually unordered warrants trigger this rule. On conflict, verifiers MUST report `WARN: key-state conflict`, and the conflicted actor's key MUST NOT count toward any quorum until a later warrant — authorized by the unconflicted remainder of the quorum — resolves it; if the threshold would become unsatisfiable, it is reduced to exclude the conflicted actor strictly for conflict resolution.

**Threshold policy grammar.** A v0.3 threshold policy blob MUST be JCS-canonical JSON:

```json
{ "warrant_policy": "0.3", "threshold": { "min_sigs": 2, "actors": ["a@x", "b@y", "c@z"] } }
```

`min_sigs` MUST be a positive integer ≤ `len(actors)`; `actors` MUST be nonempty and unique; unknown fields inside `threshold` make the policy invalid. **For settlement-grade threshold evaluation (including root adoption, §9), a signature counts for an actor only if it is cryptographically valid AND made by a key currently bound to that actor at that warrant's DAG position (§5.1). An actor with no configured key state contributes nothing: unbound claims MUST NOT satisfy a v0.3 threshold.** Records filed under an invalid threshold policy are settlement-inactive and MUST produce `ERR: invalid threshold policy` for settlement-grade verification. Opaque v0.1/v0.2 policy blobs MUST NOT be interpreted as threshold policies.

## 6. Verification (MUST)

`verify(store)` checks, for every envelope: (1) body is schema-valid with no unknown fields (recursively, §2); (2) WarrantID recomputes; (3) signatures are verified individually — an invalid signature is a WARN and is excluded (§5), and the record is an ERR only if no *valid* signature by `body.actor.id` remains; (4) every `prior` resolves to a stored warrant; (5) reference resolution is split by field kind: `prior` MUST resolve to stored warrants; `under`, `evidence`, `check`, `transcript` MUST resolve to **blobs** — a hash present only as a stored record does not resolve them; `subject.hash` resolves to a blob, or MAY resolve to a WarrantID only where a rule explicitly names one (supersede subjects, §7; §9 adoption subjects). A §5.1 **rotation** subject is a *key blob*, so it resolves as an ordinary blob — it is NOT one of the WarrantID cases. Unresolved is a warning, not corruption — blobs may live elsewhere; (6) `ts` is non-decreasing along each `prior` edge (violation = warning).

(7) **Re-execution of `ski@v1` reasons (MUST).** For every `ski@v1` reason, the verifier re-runs the check (§3.1) against the store's blobs and compares the result to the reason's claimed `verdict`. A mismatch (re-run disagrees with the claim) is a WARN — per §3, a false claim is a dispute to be answered by a counter-warrant, not a corruption of *this* record. A reason that **cannot** be re-executed (missing blob, malformed check, oracle unavailable, or `atp` over the local re-execution budget, §3.1) is reported as `ski@v1 unverified` — a stable WARN in base verification, escalated to ERR under settlement-grade verification (§7) when the reason participates in a settlement-active record, because an unexecuted claim cannot be trusted to settle. "Re-ran and matched" and "was not executed" MUST NOT be observationally equivalent — a silent skip is non-conformant. (`cmd@v1` reasons are not re-executed by `verify`; their trust model is the container, not the verifier.)

`why(id)` walks `prior` edges backward, printing decision → reasons → policy anchors, verifying as it goes.

## 7. Settlement (v0.3)

An `accept` or `reject` whose subject is a *question* blob settles it. `supersede` marks an earlier warrant as replaced: its `subject.hash` MUST be the superseded WarrantID (a missing subject is an ERR, §6).

**Tunnel.** A settling warrant's tunnel is **inclusive**: its record set is the settling warrant itself plus the transitive closure of its `prior` edges through stored warrants (a candidate citing the settling warrant's own check is a restatement, not novelty). The blob set is the union of `under`, `evidence`, `subject.hash`, `check`, and `transcript` hashes cited by those records. Verifiers MUST NOT recursively parse arbitrary blobs for additional tunnel links unless a runtime-specific rule explicitly says so. A blob hash that is also the WarrantID of a stored record is still a blob reference unless it appears in `prior` or a field whose rule explicitly names WarrantIDs.

**Foreclosure.** A blob forecloses only the claims some reason in the tunnel actually makes about it: mere presence in an `evidence` array forecloses nothing. An unresolvable blob forecloses nothing (what cannot be read cannot have been reasoned over); a record with unresolvable settlement-critical references is settlement-inactive until they resolve — without changing its WarrantID, base verification result, or the §6 warning status of v0.1/v0.2 records.

**Re-litigation.** A re-litigation warrant MUST carry at least one of: (a) an evidence hash absent from the tunnel's blob set, or (b) a **new demonstrable consequence** of evidence already present — a check, all of whose blobs are resolvable, that re-runs to a previously absent **outcome fingerprint** within the settling tunnel.

Outcome fingerprints: `ski@v1` — `{runtime, term, expect, verdict, result_node_hash}`; `cmd@v1` — `{runtime, sorted evidence hashes, verdict, transcript hash}`, with `transcript` REQUIRED for §7(b) use. A check whose outcome fingerprint already appears in the tunnel is not new even if the check blob hash differs. Only tunnel reasons supplying all required fields count toward the tunnel's fingerprint set — a reason lacking a required field (e.g. `transcript`) cannot block novelty. (The `evidence` array is not ordered by JCS; the fingerprint sorts hex hashes ascending lexicographically.) Prose MAY explain why a consequence matters, but prose is not part of the novelty test and alone never re-opens settlement.

**Novelty ≠ relevance.** The format layer decides only whether an outcome is new; whether a novel check is *relevant* to the settled subject — or a strawman testing something adjacent — MUST be decided by the active settlement policy, not the core format. Tools SHOULD refuse to file re-litigation warrants carrying neither (a) nor (b); verifiers SHOULD flag them `WARN: re-litigation cites nothing new`. NOTE: because novelty is purely syntactic, a permissive-policy store may accumulate unbounded fingerprint-distinct but irrelevant re-litigations; implementations SHOULD provide configurable limits — a policy choice, not a format requirement.

§7 is itself challengeable under (b): a check demonstrating that the rule forces a wrong settlement is admissible evidence against the rule.

**Report-string convention.** Where this document names verifier report strings (`key-state conflict`, `invalid threshold policy`, `unadopted root`, `genesis.json unverified`, `re-litigation cites nothing new`), the normative text is the message after the verifier's severity and record-identifier columns; CLI output MAY prepend structured fields (severity, abbreviated WarrantID).

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

| Artifact / identity | value |
| --- | --- |
| SKI term (root NodeHash; 5 APPLY object blobs `*.bin`, genesis I/K/S intrinsic — no leaf blobs needed) | `97a2eedea8d8b3419dac73f1685814e7a7ccd85f232f3d1e085fb1f1917611ad` |
| `check.json` (JCS bytes: `{"ski":1, "term":…, "atp":20, "expect":H(S)}`) | `0c30960435e9c9302a6a1538682e5864f2a754475369979bd3d635543976b2ad` |
| accept warrant **WarrantID** (`"warrant":"0.2"`, demo-seed signed) | `8c9267bccbc217db2f3f16e6928acaf062a1c78443b2317985567b238ccfe8a0` |

A v0.2 implementation with a Σ-GLYPH Book I v0.5 oracle MUST re-run the check against the object blobs and obtain `pass` with `result = H(S)` and `atp_spent = 20`. A v0.1 implementation MUST reject the warrant body (ski@v1 reserved) — that rejection is itself conformant.

## 9. Multi-root stores (v0.3)

A store is a DAG. A **root** is a record with empty `prior`. A root is **well-signed** if its filing signature is valid (and bound, where key state is configured). A root is eligible to become settlement-active only if it is well-signed and schema-valid under §6; a trusted-but-broken root is still reported under §6 but MUST be excluded from settlement and foreclosure calculations until repaired. Given eligibility, a root is **settlement-active** only if either (1) it is listed in the verifier's local trust configuration as a genesis root for this store, or (2) it is adopted by a settlement-active root through an `accept` warrant whose `subject.hash` is the WarrantID of the root to be adopted and whose signatures satisfy the adopting root's current settlement policy, including any threshold rule. Verifiers MAY verify inactive roots for local integrity but MUST exclude them from settlement and foreclosure calculations and MUST report `WARN: unadopted root`.

**Adoption is scoped:** adopting root A makes root B settlement-active for A's jurisdiction only. Two roots that never reference each other are separate jurisdictions sharing a blob store — by design.

**Portable jurisdiction:** stores SHOULD contain `genesis.json` in the store root — JCS-canonical `{"roots": ["<WarrantID>", ...]}`. The file is **advisory**; verifiers MUST NOT treat it as a trust anchor — it is mutable, unsigned, and editable by anyone with store write access. Before using its listed roots as settlement-active, a verifier MUST independently verify its authenticity (typically a pinned hash in local trust configuration, or explicit user acceptance). If present but unverified: `WARN: genesis.json unverified`, and its contents MUST NOT be used for settlement.

## 10. Non-goals

Consensus, ordering across actors, blob transport, privacy/encryption, PKI beyond §5.1's key-state warrants, and any opinion about how agents *make* decisions. Warrant records decisions; it does not take them.
