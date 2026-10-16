# WRT-019: ECDSA P-256 signatures, for keys that live in phone hardware

**Status:** DECIDED, 2026-10-16. The owner delegated the decision ("повна свобода дій та рішень"). Claude decided as below and implements it in Python, Go and Rust in the same change.

## Why

Warrant accepts Ed25519 only. The secure elements in phones (Apple Secure Enclave,
Android StrongBox / TEE Keymaster) generate and use **ECDSA P-256** keys, and cannot
sign Ed25519. A key that never leaves hardware therefore cannot sign a warrant
record today. The workaround, a software Ed25519 key certified by a hardware key,
is weaker than the hardware signing the record directly.

The gap was named while comparing warrant with Pakto, a two-party mobile signing
app whose keys are P-256 in the Secure Enclave/StrongBox (`warrant-pdf`,
`docs/COMPARISON.md`). It is the first of the two additions that comparison lists.
Attestation, the second, is out of scope here.

## Decision

A signature entry MAY name its algorithm:

```json
{ "actor": "a@x", "alg": "ecdsa-p256-sha256", "key": "<66 hex>", "sig": "<128 hex>" }
```

- **`alg` absent means `ed25519`.** Every existing record keeps its meaning, and
  nothing is re-signed.
- **`alg: "ecdsa-p256-sha256"`**:
  - **key**: the 33-byte **compressed** SEC1 point, `02` or `03` followed by the
    32-byte big-endian x. It MUST decode to a point on P-256 (x < p, and x³ − 3x + b
    a square). Uncompressed (`04…`), hybrid and infinity encodings MUST be rejected.
    A key has exactly one encoding, so it has exactly one string in a trust config.
  - **sig**: 64 bytes, `r ‖ s`, each 32-byte big-endian. It MUST satisfy
    1 ≤ r < n and **1 ≤ s ≤ (n − 1)/2 (low-S)**. DER and high-S MUST be rejected,
    so a signature has exactly one encoding too. Signers normalize: the Secure
    Enclave emits high-S about half the time, and `s ↦ n − s` is what to file.
  - **message**: ECDSA with SHA-256 over the same 47 bytes as Ed25519,
    `"warrant-sig-v1:" ‖ WarrantID_raw` (§5). Domain separation is unchanged.
- **Any other `alg` value** is a signature that does not verify: reported and
  excluded, with the existing §5 rule and message. It is never fatal on its own,
  and a record whose actor signed only that way has no valid actor signature
  (§6 ERR).
- **Key slots elsewhere** accept the same two encodings and nothing else: trust
  config `actors` (§12), key-state blobs, and the pre-rotation `next` commitment
  (SHA-256 of the raw key bytes, 33 bytes for P-256).
- **The algorithm is never inferred from the key's length.** The entry says which
  algorithm it claims, and the key must have that algorithm's form. An Ed25519 key
  with `alg: ecdsa-p256-sha256`, or a P-256 key without `alg`, does not verify.

## Considered

| | Option | Why not |
|---|---|---|
| A | Infer P-256 from a 66-hex key | algorithm inferred from data; the next algorithm with a 33-byte key collides |
| B | DER signatures, as hardware emits them | several encodings of one signature; every verifier must agree on DER strictness, a known split |
| C | Accept high-S, like many libraries | two valid signatures per message and key; a low-S/high-S malleability split between verifiers |
| D | A new body field or version | the body is not involved: the envelope is outside the hash, and adding a member to an entry is already defined (§5: other members are ignored) |

## Compatibility

A verifier before this change ignores `alg` and reads a 33-byte key as Ed25519,
which fails. It reports the P-256 signature as not verifying and excludes it. It
fails closed, and gives no false acceptance.

## Implementation (this change)

- **Python**: `cryptography`, already a dependency. It can also sign: `keygen --alg
  p256` writes a `p256:` key file; filing with it uses RFC 6979 deterministic
  ECDSA and normalizes to low-S.
- **Go**: the standard library (`crypto/ecdsa`, `crypto/elliptic`).
- **Rust**: from scratch, like its SHA-256 and Ed25519, because `impl-rs` takes no
  external crates so that agreement with the reference is evidence about the
  specification. It verifies only; it does not sign. P-256 field and scalar
  arithmetic, decompression and the verification equation are tested
  differentially against the other two.
- **JS/WASM** follows from Rust.
- **Conformance**: the `verify-sig` class gains an optional `alg` input and P-256
  vectors, both positive and the edges above: high-S, r or s zero or ≥ n,
  uncompressed and invalid keys, x not on the curve, wrong message, and an
  algorithm/key mismatch in both directions.
