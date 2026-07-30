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
| `actor` | object | MUST | `{"id": <nonempty string>}` — stable actor identifier |
| `prior` | array | MUST | ≥0 WarrantIDs this record responds to or follows |
| `ts` | integer | MUST | Unix seconds, UTC, in the inclusive range `0..9223372036854775807` (int64) |

All hashes are lowercase hex, 64 chars. All numbers in a body MUST be integers (no floats anywhere — this keeps canonicalization trivial and exact). A body with a negative or out-of-int64-range integer field is schema-invalid; implementations MUST NOT silently clamp, wrap, or truncate numeric fields (an unchecked 64-bit narrowing is exactly the kind of silent verifier split this rule exists to prevent).

**The unknown-field rule is recursive (MUST).** It applies not only to the body but to every object the schema names: `subject` (exactly `hash`, optional `note`), `actor` (exactly `id`), and each reason object (§3). An unknown member anywhere in that tree makes the record invalid. Leaving nested strictness implicit is a silent verifier split: one implementation accepts an extra key another rejects, while both compute the same WarrantID.

**`actor.id` MUST be a nonempty string.** (Spec gap closed 2026-07-30: this table said `<string>` while all three implementations rejected `""` — Python, Go and Rust each answer `actor must be {id: <nonempty string>}`. Three implementations agreeing is not authority to write a spec from code, so it is recorded here as what it was: the document was silent where an implementer had to guess, and the guess they would have made — `""` is a string, therefore valid — would have produced a record every existing verifier rejects. `§6`'s rule that a valid signature by `body.actor.id` must exist gives the requirement its meaning: an empty actor id names nobody.)

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

**String escaping is normative (MUST), not left to a library default.** Emit the two-character short escapes `\"` `\\` `\b` `\t` `\n` `\f` `\r`; escape every other code point below U+0020 as `\u00xx` with **lowercase** hex; emit every other character — including `<` `>` `&`, `/`, and all non-ASCII — as raw UTF-8. Do **not** escape `<` `>` `&` (Go's `encoding/json` does this by default: it MUST be disabled), do **not** `\u`-escape U+2028/U+2029, and do **not** use uppercase hex or the `\uXXXX` long form where a short escape applies. These are the classic JCS reimplementation splits; the §8 example vectors don't exercise them, so a conformant implementation MUST also reproduce the escaping battery in **`examples/canon-vectors.json` (§8.4)** — machine-readable vectors, not a test script. (Before 2026-07-30 this clause pointed at `tests/differential.py`, which made a Python file normative and required a third-party implementer to read it; the harness is now the runner and the vectors are the artifact.)

**Key ordering:** JCS sorts object member names by UTF-16 code unit. Every key this schema admits is fixed ASCII, for which UTF-16-unit order, Unicode-code-point order, and UTF-8 byte order coincide — so `sort_keys` (code point) and a bytewise sort are both correct here. Any future version that admits free-form object keys MUST sort by UTF-16 code unit per RFC 8785, not by code point.

**Duplicate member names are invalid (MUST).** Bodies and all schema blobs are I-JSON (RFC 7493): an object with a repeated member name is malformed and MUST be rejected, not silently resolved last-wins. Stock JSON parsers (Python's `json`, Go's `encoding/json`) keep the last occurrence silently; an implementation MUST detect and reject duplicates so a dup-key object cannot mean "malformed" to a strict reimplementation and "last-wins" to a lenient one.

**Unicode normalization is NOT applied (MUST NOT).** Strings are canonicalized and hashed as their exact sequence of Unicode code points; a verifier MUST NOT apply NFC/NFD (or any) normalization, and MUST NOT reject a string for not being normalized. Two strings that differ only by normalization form (e.g. `й` as U+0439 vs. `и`+U+0306) are different content and hash to different WarrantIDs — as a content-addressed system requires. The reference implementations agree byte-exact on both forms (they never normalize). Requiring NFC would force a full Unicode normalization database into every implementation (including the from-scratch ones) and would reject legitimate content; the deliberate choice is to hash exactly what was written. PRODUCERS SHOULD emit NFC so that a string mangled by an *external* system (an editor, a database, a filesystem that silently normalizes) does not later fail to resolve — but that is a producer discipline, not a verifier rule, because such external mangling would break any hash-addressed format and is outside this spec's boundary.

## 5. Envelope and signatures (MUST)

A stored warrant is an envelope:

```json
{ "body": { ... }, "sigs": [ { "actor": "<id>", "key": "<hex64 Ed25519 pubkey>", "sig": "<hex128>" } ] }
```

- `sig` = Ed25519 signature over the 32 raw bytes of the WarrantID. Verification is pure Ed25519 (RFC 8032, no context, no pre-hash): the message is the 32-byte WarrantID itself.
- **Verification acceptance is pinned (MUST):** a verifier MUST reject a signature whose `S` scalar is non-canonical (`S ≥ L`), MUST reject a malformed (non-canonical) public-key or signature-point encoding, and **MUST reject a small-order or non-canonically-encoded public key** before verifying. A small-order public key (the 8 torsion points, e.g. all-zero) lets an all-zero signature verify for a large fraction of messages, and libraries disagree on which such keys they accept — so a crafted envelope would verify under one library and not another ("Taming the many EdDSAs"). The rejection set is a byte-exact blocklist of the 8 canonical torsion encodings plus a non-canonical check (`y ≥ p` after clearing the sign bit), so every implementation agrees by construction; it is a normative negative-conformance vector (§8.3), not a library-dependent heuristic. Implementations SHOULD additionally prefer a strict RFC 8032 cofactorless verifier.
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

### 8.3. Negative conformance vectors (MUST REJECT)

The positive vectors above pin what a conforming implementation MUST *accept*; equally normative is what it MUST *reject*. `examples/conformance-negatives.json` is a machine-readable battery every implementation MUST pass:

- **`weak_ed25519_pubkeys`** — signature verification MUST fail for each listed public key, for any message and signature (§5): the 8 canonical small-order torsion encodings, their non-canonical sign-bit variants, and a `y ≥ p` non-canonical key.
- **`schema_invalid`** — `validate(body)` MUST return ≥1 error for each listed body: a float `ts`, a missing field, an unknown body field, an unknown *nested* field (§2 recursive), a non-hex subject hash, a `reject` with zero reasons, `ski@v1` in a `"0.1"` body, a `note` over 200 code points (§2), and an unknown `runtime` (§3).

Both reference implementations' `conformance` command loads and checks this file. Behaviors that are rejection-of-malformed-*bytes* rather than schema (duplicate member names, trailing content after the JSON value, non-JCS-canonical blobs — §4) are exercised by the cross-implementation harnesses (`tests/hostile.py`, `tests/fuzz_differential.py`) since they concern the parse layer, not a body value; a third implementation MUST agree there too.

### 8.4. Canonicalization vectors (MUST REPRODUCE, `examples/canon-vectors.json`)

The §8/§8.2 vectors pin *records*; §8.3 pins what MUST be rejected. `examples/canon-vectors.json` pins the **§4 canonicalization surface** those never reach: a `warrant.canon-vectors@v0` document whose `cases` array carries, for each case, an input `body`, the canonical bytes as `canon_hex`, and the resulting `warrant_id`.

For every case, an implementation MUST produce `canonical_json(body)` equal byte-for-byte to `canon_hex` and a WarrantID equal to `warrant_id`. The battery covers every control code point U+0000–U+001F (the `\b`/`\f` short-form trap that split Go's `encoding/json`), `<` `>` `&` `/` and U+2028/U+2029 emitted **raw** (§4), NFC vs NFD as distinct content, astral-plane code points, C1/DEL, control characters in `actor.id` and in a prose reason, a 9007199254740991 `ts`, the 200/201-code-point `note` boundary (the byte-vs-code-point split), and key-order insensitivity.

The bodies are stored with `\uXXXX` transport escaping so the file is pure ASCII; that escaping is a property of *this file*, not of canonical output — canonical output is what `canon_hex` says.

`tests/differential.py` is the harness that drives each implementation's `canon` command over these vectors; it compares implementations against each other **and** against the pinned bytes, so a drift shared by all of them is still a failure. Running it is not required for conformance; reproducing the vectors is.

## 9. Multi-root stores (v0.3)

A store is a DAG. A **root** is a record with empty `prior`. A root is **well-signed** if its filing signature is valid (and bound, where key state is configured). A root is eligible to become settlement-active only if it is well-signed and schema-valid under §6; a trusted-but-broken root is still reported under §6 but MUST be excluded from settlement and foreclosure calculations until repaired. Given eligibility, a root is **settlement-active** only if either (1) it is listed in the verifier's local trust configuration as a genesis root for this store, or (2) it is adopted by a settlement-active root through an `accept` warrant whose `subject.hash` is the WarrantID of the root to be adopted and whose signatures satisfy the adopting root's current settlement policy, including any threshold rule. Verifiers MAY verify inactive roots for local integrity but MUST exclude them from settlement and foreclosure calculations and MUST report `WARN: unadopted root`.

**Adoption is scoped:** adopting root A makes root B settlement-active for A's jurisdiction only. Two roots that never reference each other are separate jurisdictions sharing a blob store — by design.

**Portable jurisdiction:** stores SHOULD contain `genesis.json` in the store root — JCS-canonical `{"roots": ["<WarrantID>", ...]}`. The file is **advisory**; verifiers MUST NOT treat it as a trust anchor — it is mutable, unsigned, and editable by anyone with store write access. Before using its listed roots as settlement-active, a verifier MUST independently verify its authenticity (typically a pinned hash in local trust configuration, or explicit user acceptance). If present but unverified: `WARN: genesis.json unverified`, and its contents MUST NOT be used for settlement.

## 10. Non-goals

Consensus, ordering across actors, blob transport, privacy/encryption, PKI beyond §5.1's key-state warrants, and any opinion about how agents *make* decisions. Warrant records decisions; it does not take them.

---

*Sections 11–14 were added on 2026-07-30 and are appended rather than interleaved so that every existing cross-reference to §1–§10 keeps its number. They specify surfaces that already existed and were interoperated against — a report contract, a trust-configuration file, a runtime tag set — but were specified in a README, in two implementations, or nowhere.*

## 11. Verification report — `warrant.verify-report@v0`

A verifier MAY expose its result as a machine-readable **verification report**. Emitting one is OPTIONAL (a conformant verifier may have a text interface only — `impl-rs` does). **Emitting the tag `warrant.verify-report@v0` is what is normative:** a producer that prints that string commits to everything in this section, and a consumer that reads that string may rely on it.

A report is **not a Warrant**: it is unsigned, has no WarrantID, is not stored, and carries no settlement authority. It is the verifier's answer about a store at a moment, not a record of a decision. Nothing in this section changes what `verify` (§6) *decides*; it fixes only how that answer is serialized. (Until 2026-07-30 the contract lived in `README.md` and both implementations' source called it "non-normative", meaning "not part of the record format". That was true and was read as "not specified", which is why a consumer had to read a README to integrate.)

### 11.1. Shape (MUST)

Exactly these seven top-level members, no others:

```json
{"report":"warrant.verify-report@v0","grade":"base","ok":true,
 "records":3,"errors":0,"warnings":1,
 "findings":[{"level":"WARN","subject":"<WarrantID>","message":"..."}]}
```

| Member | Type | Meaning |
| --- | --- | --- |
| `report` | string | Exactly `"warrant.verify-report@v0"` |
| `grade` | string | `"base"` or `"settlement"` — the verification grade that was **requested** (§6 vs §7/§5.1/§9), not a claim about what succeeded |
| `ok` | boolean | `errors == 0`, and nothing else |
| `records` | integer | Number of records considered, **including records that could not be loaded** |
| `errors` | integer | Number of `ERR` findings |
| `warnings` | integer | Number of `WARN` findings |
| `findings` | array | Every `ERR` and `WARN` event, each an object of exactly `level`, `subject`, `message` |

- `level` MUST be `"ERR"` or `"WARN"`. `INFO` and any other level MUST NOT appear: a report carries the two severities §6 defines and nothing else.
- `subject` MUST be the full 64-character lowercase-hex WarrantID of the record the finding is about, or one of the reserved non-hash subjects **`"store"`** (a finding about the store as a whole, e.g. the fail-closed no-store report of §11.3) and **`"settlement"`** (a finding about the requested settlement context as a whole, e.g. an unusable trust configuration). Consumers MUST NOT assume `subject` is hex64. Further reserved subjects are registered under §13.3.
- `message` is human-oriented prose. It is **NOT normative** and **MAY differ between conformant implementations** for the same input. A consumer MUST NOT branch on it. (It differs today: an unloadable record is `unloadable record: malformed JSON` in Python and `invalid character 'b'` in Go.)
- **Counts bind findings (MUST):** `errors` MUST equal the number of `ERR` findings and `warnings` MUST equal the number of `WARN` findings, in every report, always. A consumer MAY recompute both and MUST be permitted to reject a report where they disagree — that is a producer defect, not an ambiguity to tolerate.
- **`ok` binds errors (MUST):** `ok == (errors == 0)`. `ok` is a statement about §6 errors only. A report MAY be `ok:true` with many warnings — including `binding unverified`, which is what an unconfigured keyring produces (§5.1). `ok:true` is not "this store is trustworthy"; it is "this verifier found no §6 error at the requested grade".

### 11.2. Serialization and process contract (MUST)

- The report MUST be exactly **one JSON value on stdout**, occupying exactly **one physical line**. In particular U+2028 and U+2029 inside a `message` or an `actor.id`-derived `subject` MUST NOT be emitted as raw line separators in a way that splits the output — a consumer reading one line MUST get the whole report. (Both implementations pass this vector; §4's raw-emission rule is about *canonical body bytes*, not about this transport.)
- In report mode the verifier MUST NOT write human text to stdout, and MUST NOT write diagnostics to stderr: a preflight failure is expressed as the report itself (§11.3), never as a stderr message with no report.
- Exit status MUST be `0` if and only if `ok` is `true`, and MUST equal the exit status the same invocation produces in text mode.
- The counts in the report MUST equal the counts the same invocation reports in text mode. The report is a rendering of one verification, never a second derivation of it.
- Findings MUST be emitted in an order that is **deterministic and stable**: re-running the same verifier over the same store MUST produce a byte-identical report. Two *different* implementations MUST agree on `report`, `grade`, `ok`, `records`, `errors`, `warnings` and on the **multiset of `(level, subject)` pairs**; they are NOT required to agree on finding order or on any `message`. That, and not byte-equality of the whole object, is the interoperable surface.

### 11.3. Store mode and failing closed (MUST)

A report is only interoperable when the verifier has been asked to treat its argument as a **store** (`--store-mode` in both reference CLIs). In store mode:

- A path that is not an initialized store — missing, a `records/` that is not a directory, a `blobs/` with no `records/` — MUST produce `ok:false`, `records:0`, `errors:1`, `warnings:0`, and exactly one finding at level `ERR` with subject `store`. It MUST NOT be treated as an empty successful verification. This is what makes `.ok` a safe predicate: without it, "there was nothing to verify" and "everything verified" are the same JSON.
- An **initialized but empty** store is a successful verification: `ok:true`, `records:0`, `errors:0`.

**Known divergence (not resolved by this text).** *Without* `--store-mode`, the Go CLI retains a legacy flat-directory mode: on an uninitialized directory it emits `ok:true, records:0` while Python emits the fail-closed `ok:false` report — the same tag carrying opposite verdicts about the same path in two conformant implementations. That is disclosed in `README.md`, but the §5 design rule ("two independent implementations MUST agree on every verification outcome") does not carve out a legacy mode. The correct repair is for legacy flat mode to emit no `warrant.verify-report@v0` object at all, since flat mode is not a store verification; that is a behaviour change to a released surface and is recorded here as an open defect rather than legislated away. Consumers MUST pass `--store-mode`.

### 11.4. Versioning and extension (MUST)

`warrant.verify-report@v0` is a **closed schema**. Unknown top-level members and unknown finding members are not permitted, and a strict consumer MAY reject a report that carries any. Consequently:

- A producer MUST NOT add a field to `@v0`, ever, including an "obviously harmless" one. Any additional field, any additional finding member, any additional `level`, and any change to the meaning of an existing member ships under a **new report tag** (`warrant.verify-report@v1`), registered per §13.3.
- A consumer MUST gate on the exact `report` tag it understands and MUST NOT pattern-match a prefix.
- A producer MAY emit a `@v1` report only when the consumer asked for it; the tag a consumer did not ask for is not a compatible substitute for the one it did.

`schemas/verify-report-v0.schema.json` is the JSON Schema for this section (§14.2). Where schema and prose disagree, this prose is normative.

## 12. Trust configuration (`trust-config.json`)

§5.1 states that no interchangeable keyring format is mandated, and that remains true of *key state*, whose truth is the DAG of key-state warrants. But a verifier still needs somewhere to put the two things that cannot come from inside the store — which keys start bound, and which roots are settlement-active — and both reference implementations already read the identical file. Two implementations agreeing on a file format is an interop surface whether or not a document admits it, so this section specifies the file they read. It is **local verifier configuration, not protocol state**: it is unsigned, is never hashed into a WarrantID, and MUST NOT be shipped as authority. Supplying one is OPTIONAL; a verifier MAY offer a different mechanism, or none. Reading a file that claims this shape is what is specified.

### 12.1. Shape (MUST)

JSON object with a **closed** member set — an unknown member makes the configuration invalid:

```json
{ "actors": { "<actor-id>": ["<hex64 Ed25519 pubkey>", "..."] },
  "genesis_roots": ["<hex64 WarrantID>", "..."],
  "genesis_json_sha256": "<hex64>" }
```

| Member | Req | Meaning |
| --- | --- | --- |
| `actors` | MAY | Object mapping a **nonempty** actor id string to an array of hex64 Ed25519 public keys **genesis-bound** to that actor. Array MAY be empty. |
| `genesis_roots` | MAY | Array of hex64 WarrantIDs the operator pins as settlement-active roots for this store (§9(1)). |
| `genesis_json_sha256` | MAY | hex64 SHA-256 of the exact `genesis.json` bytes the operator has accepted (§9). |

All three members are optional; `{}` is valid and means "no local trust", which is not the same as "no trust configuration supplied" (§12.3).

### 12.2. Parsing and validation (MUST)

- The file MUST be parsed in the same I-JSON domain as every other trust-bearing input (§4): duplicate member names, trailing content after the JSON value, invalid UTF-8 and unpaired surrogate escapes MUST be rejected. A trust input parsed more leniently than a record is a way to make two verifiers disagree about who is bound.
- Validation is **closed and recursive**: an unknown top-level member, a non-object `actors`, an empty actor id, a non-array key list, or any element of `actors[*]`/`genesis_roots` that is not hex64, or a non-hex64 `genesis_json_sha256`, makes the configuration invalid. (Nested types are named explicitly because they were the actual split: `{"actors":[]}` and `{"actors":{"a":1}}` once crashed one implementation while the other returned zero errors.)
- The file MUST NOT be canonicalized, hashed, or otherwise treated as content-addressed; it is not a blob.

### 12.3. Fail-closed semantics (MUST)

If a settlement-grade verification is **requested** with a trust configuration that is missing, unreadable, malformed, or schema-invalid, the verifier MUST report exactly one `ERR` with subject `settlement`, MUST NOT continue into a partial base-grade verification, and MUST NOT silently fall open to "no trust configured". A requested settlement verification that could not construct its trust did not happen, and MUST NOT be reported as one that found nothing wrong.

If **no** trust configuration is supplied, key↔actor binding is reported as unverified (§5.1, §5 last bullet) — a WARN, never an ERR, and never a silent pass.

`genesis_json_sha256` gates §9's advisory `genesis.json`: the file's bytes are read once, digested, and used only if the digest matches; otherwise `WARN: genesis.json unverified` and its contents MUST NOT be used. A `genesis.json` whose pinned digest matches but whose `roots` member is absent or not an array contributes no roots and MUST NOT be an error — a hostile shape behind a matching digest must be a bounded no-op in every implementation.

`schemas/trust-config.schema.json` is the JSON Schema for this section (§14.2).

## 13. Registries

Three of this format's extension points are closed sets today: a new value requires editing this document, which means a new runtime cannot be tried without a spec change. This section says how each set grows and what a registration must contain. **There is no registry operator.** Until one exists (a neutral IANA-style registry is out of scope for a DRAFT spec by one maintainer), a registration is a pull request against this repository containing the fields below, and the registry is the tables in this document. Saying that plainly is the point: an unstaffed registry described as if it were staffed is worse than none.

### 13.1. Reason-runtime tags (`because[].runtime`)

Policy: **Specification Required** in the IETF sense — a registration MUST cite a stable, publicly readable document sufficient for an independent implementer, and MUST NOT be granted for a private or unstable one. A runtime tag is a promise about *verification*, so the bar is what a second implementer needs.

| Tag | Body versions | Status | Defined in |
| --- | --- | --- | --- |
| `cmd@v1` | `0.1`, `0.2` | current | §3 |
| `ski@v1` | `0.2` | current | §3.1 (Σ-GLYPH Book I **v0.5**) |

A registration MUST supply: the tag, the body versions it is valid in, whether a verifier is expected to re-execute it (§6(7)) and with what budget unit, the exact outcome-fingerprint tuple for §7 novelty, the pinning rule for whatever ruleset it evaluates (as §3.1 requires of `ski@v1`), and a normative negative vector set (§8.3).

Rules that hold regardless of registration:

- Tags are `name@vN`. **A tag is immutable.** A semantic change — including evaluating a later revision of the same external ruleset — is a NEW tag, never a redefinition. `ski@v1` names Book I v0.5; Book I v0.6 would be `ski@v2`.
- An unregistered `runtime` value makes the record invalid (§3, MUST). Unknown-means-invalid is what stops a forward-dated runtime from meaning "valid" to one verifier and "invalid" to another, and it is the reason this registry has to exist at all.
- Adding a tag to a body version that already exists is a change to that version's validity surface, so a new tag MUST be introduced in a **new body version** (as `ski@v1` was introduced in `0.2` and remains reserved-and-rejected in `0.1`).
- Experimental and private-use tags MUST use the prefix `x-` (e.g. `x-mycorp-wasm@v1`). Records carrying an `x-` tag are not interoperable by construction and MUST NOT be used in a store intended to be verified by anyone else. A registered tag MUST NOT begin with `x-`.

### 13.2. Body format versions (`warrant`)

| Value | Status | Adds |
| --- | --- | --- |
| `0.1` | current | base schema (§2, §3) |
| `0.2` | current | `ski@v1` runtime (§3.1) |

Policy: maintainer action recorded in `CHANGELOG.md` (§14.3), with the §8 vectors extended in the same change. A new body version MUST NOT invalidate any record valid under an earlier one (§4 of the version preamble), and MUST state, for every runtime tag in §13.1, whether it is admitted or reserved-and-rejected. Document-level versions that add no body schema (as v0.3 did) do NOT consume a `warrant` value.

### 13.3. Report tags and reserved report subjects

Report tags (`warrant.verify-report@vN`, §11) are registered here. Policy: **Specification Required**, same bar as §13.1, plus a published JSON Schema (§14.2) and a statement of what changed from the previous tag.

| Tag | Status | Defined in |
| --- | --- | --- |
| `warrant.verify-report@v0` | current | §11 |

Reserved non-hash `subject` values (§11.1) are registered here; a new one MUST be added by the same process, because a consumer distinguishing "a finding about a record" from "a finding about the run" does so by this list.

| Subject | Meaning |
| --- | --- |
| `store` | the store as a whole (§11.3) |
| `settlement` | the requested settlement context as a whole (§12.3) |

Any other machine-readable document tag this project defines (`warrant.canon-vectors@v0`, §8.4; `conformance_negatives`, §8.3; `evidence_pack`, `EVIDENCE-PACK.md`) follows the same rule: closed schema, new tag for any additive change, never a new field inside an existing tag.

## 14. Media type and schemas

### 14.1. IANA considerations — `application/warrant+json` (DRAFT REGISTRATION, NOT FILED)

**Status: this registration has NOT been submitted to IANA.** No expert review has been requested, no `application/warrant+json` registration exists, and until one does, the media type MUST be treated as unregistered. It is written out here so that the shape of the commitment is on the record before anyone depends on it, and so a future submission does not silently change the format to fit a form. Producers MAY use it on a private network today; nothing SHOULD depend on it being registered.

Registration template (RFC 6838 §5.6, structured suffix per RFC 6839):

- **Type name:** application
- **Subtype name:** warrant+json
- **Required parameters:** none
- **Optional parameters:** `version` — the value of the body's `warrant` member (e.g. `version="0.2"`). Absent means the recipient MUST read the member itself. The parameter is a routing convenience and is NOT authoritative: where the parameter and the member disagree, the member wins, because only the member is inside the hash.
- **Encoding considerations:** binary; UTF-8 per RFC 8259 and RFC 7493 (I-JSON). Content is exchanged as the exact bytes; any re-encoding, re-indentation, BOM insertion, or Unicode normalization changes the WarrantID and MUST NOT be performed by intermediaries (§4).
- **Security considerations:** those of RFC 8259, RFC 7493 and RFC 8785, plus: a warrant is a *claim* until verified per §6; `ok` from a verifier is not a statement that the claim is true, only that the record is well-formed and signed. Signature acceptance is pinned (§5) — small-order and non-canonical Ed25519 public keys MUST be rejected. Consumers MUST NOT execute a `cmd@v1` check blob merely because it arrived in a record (its trust model is a container the recipient chose); `ski@v1` re-execution is bounded in work and memory by construction (§3.1) and is the only reason kind safe to re-run from an untrusted source. Recursive `prior` resolution over attacker-supplied data MUST be bounded. The format carries no confidentiality: everything in a body, including `subject.note` and prose reasons, is intended to be readable and quotable by anyone holding it.
- **Interoperability considerations:** unknown members make a record invalid (§2, recursively). Duplicate member names MUST be rejected (§4). Recipients MUST NOT round-trip through a JSON library that reorders, re-escapes, HTML-escapes, or normalizes, and MUST NOT assume a lenient parser's last-wins behaviour.
- **Published specification:** this document (`SPEC.md`), cited by the versioned permalink convention of §14.3.
- **Applications that use this media type:** decision-record stores for AI agents and CI systems; audit and evidence-pack tooling.
- **Fragment identifier considerations:** none defined. A WarrantID is not a fragment identifier.
- **Additional information:** magic numbers — none. File extension — `.warrant.json` (records are conventionally stored as `<WarrantID>.json`). Macintosh file type code — none.
- **Person & email address to contact for further information / Intended usage / Restrictions on usage / Author / Change controller:** the maintainer of `https://github.com/s0fractal/warrant`; intended usage COMMON; no usage restrictions; change controller the same, pending any transfer recorded in the change log.

Two shapes deliberately do **not** get a media type here: the envelope (§5) is carried under the same type as the body it wraps, and the verification report (§11) is a tool output, not an interchange format — if it ever needs one it will be `application/warrant-report+json` under a report tag, registered per §13.3.

### 14.2. JSON Schemas (`schemas/`)

Published, versioned JSON Schema (draft 2020-12) files:

| File | Covers |
| --- | --- |
| `schemas/warrant-body.schema.json` | the body, §2–§3.1, both `0.1` and `0.2` |
| `schemas/warrant-envelope.schema.json` | the stored envelope, §5 |
| `schemas/verify-report-v0.schema.json` | `warrant.verify-report@v0`, §11 |
| `schemas/trust-config.schema.json` | trust configuration, §12 |
| `schemas/evidence-pack-manifest.schema.json` | `manifest.json`, `EVIDENCE-PACK.md` |

The schemas are **derivative and secondary**. Where a schema and this document disagree, this document is normative and the schema is a defect. Passing a schema is necessary and NOT sufficient for conformance: JSON Schema cannot express canonicalization (§4), signature acceptance (§5), re-execution (§6(7)), or settlement (§7), and a validator that only ran a schema would accept a record no verifier here would. `tools/schema_check.py` checks the schemas against the `examples/` corpus in both directions — every positive vector MUST validate, and every §8.3 negative vector MUST NOT — so a schema that has drifted from the vectors fails rather than reassuring.

### 14.3. Citing a version of this document

This specification has, until now, been citable only as "SPEC.md", which is a moving target: the sentence a reader quotes and the sentence in force can differ by a force-push. That is an odd property for a format whose whole argument is that a policy must be pinned by the hash of its exact bytes.

The convention, from 2026-07-30:

- **`CHANGELOG.md`** (Keep-a-Changelog shape, this repository's root) is the record of what changed in each release, reconstructed from git history for everything before it existed. Protocol-visible changes are marked; a release with no protocol-visible change says so.
- **Cite this document by commit, not by branch.** The stable citation form is
  `https://github.com/s0fractal/warrant/blob/<full-40-char-commit-sha>/SPEC.md#<anchor>`.
  A `blob/master/SPEC.md` link is a convenience for a reader and MUST NOT be used where the exact text matters — in a `under` policy blob, a conformance claim (`TRADEMARK.md`), an audit report, or a registration.
- **Pin by hash where a hash is available.** `SHA-256` of the exact `SPEC.md` bytes is the strongest citation and is what a `ski@v1`-style pinning rule (§3.1) expects of any ruleset it evaluates against. A tagged release commit is the second-strongest; a branch name is not a citation.
- **A release tag is `vMAJOR.MINOR.PATCH` on the tooling**, which is *not* the protocol version. Four numbers coexist deliberately: the body version (`warrant`, §13.2), the document version in this file's title, the report tag (§13.3), and the package version. `CHANGELOG.md` states, per release, which of them moved. Conflating them is the single most common misreading of this project's status.
