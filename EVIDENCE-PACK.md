# Evidence Pack — format v0 (DRAFT)

An **evidence pack** is a portable, self-verifying bundle of an agent decision
and everything needed to check it: the signed records, the exact policy bytes
they were decided under, and the re-executable reasons. Its defining property:

> A stranger can verify a pack **offline**, trusting nothing but the source of
> the `warrant` tool. Credibility lives in the content-addressed bytes, not in
> whoever is hosting them — *trust the hash, not the host.*

The format is deliberately boring: it is a directory (optionally `.tar`/`.zip`)
whose normative core is an ordinary `warrant` store. `warrant-verify` is MIT;
the format is CC-BY-4.0. Anyone may produce, read, or re-implement a pack.

## Layout

```
pack/
├── .warrants/            REQUIRED — the portable warrant store (the truth)
│   ├── blobs/<sha256>        content-addressed: policies, subjects, ski checks,
│   │                         transcripts, Σ-GLYPH nodes — each named by its hash
│   └── records/<wid>.json    the signed decision records ({body, sigs} envelopes)
├── manifest.json         REQUIRED — what this pack is and how to check it
├── trust.json            OPTIONAL — a keyring (actor → pubkeys) + genesis roots,
│                                    for `warrant verify --settlement`
├── policies/             OPTIONAL — human-readable mirror of pinned policy blobs
├── subjects/             OPTIONAL — human-readable mirror of decision subjects
└── README.md             OPTIONAL — a human walkthrough of this pack
```

Everything outside `.warrants/` is convenience. Deleting `manifest.json` or the
mirrors cannot change what the records say — only the content-addressed store can,
and it cannot be changed without breaking a hash. The mirrors carry their blob
hash in the filename (`bereavement-policy.c8d453b05c7d.txt`) purely so a human can
match text to hash by eye; the verifier never reads them.

## `manifest.json`

```json
{
  "evidence_pack": "0",
  "title": "Air Canada — retroactive bereavement refund, refused",
  "root": "<WarrantID of the first record in the chain>",
  "decision": "<WarrantID of the record that settles the matter>",
  "records": ["<WarrantID>", "..."],
  "ski_checks": [
    { "check": "<blob hash>", "term": "<Σ-GLYPH NodeHash>",
      "expect": "<Σ-GLYPH NodeHash>", "atp": 7,
      "means": "plain-language meaning of this predicate's pinned value" }
  ],
  "expected_verification": { "errors": 0 },
  "how_to_verify": "warrant --store .warrants verify"
}
```

`evidence_pack` is the format version (`"0"`). All hashes are lowercase hex
SHA-256. `records` SHOULD list every record in `.warrants/records/`. `ski_checks`
SHOULD enumerate every `ski@v1` reason so a verifier can re-run each one by hand
(`warrant … check <check>`) and confirm its meaning. Additional keys are allowed
and MUST be ignored by verifiers that don't understand them.

## Verification contract

A pack is **valid** iff, from the pack directory:

1. `warrant --store .warrants verify` reports **0 errors** (exit 0). This
   recomputes every WarrantID, checks every signature, resolves every blob and
   `prior` link, and **re-executes every `ski@v1` reason**, failing on any
   mismatch. A bundled Σ-GLYPH Book I oracle runs the checks offline.
2. Each entry in `manifest.ski_checks` re-executes to its stated `expect`:
   `warrant --store .warrants check <check>` prints `pass  result=<expect> …`.
3. *(optional, stronger)* With the shipped keyring,
   `warrant --store .warrants verify --settlement --trust-config trust.json`
   reports **0 warnings** — every signature is *bound* to an actor the verifier's
   own keyring vouches for. Without a keyring, key↔actor bindings are reported as
   `binding unverified` (a warning, never an error): the tool refuses to invent a
   root of trust for you.

Tamper-evidence follows for free: altering one byte of any record changes its
WarrantID, so step 1 fails with `WarrantID mismatch` and a non-zero exit.

## Producing a pack

Any warrant store is already 90% of a pack — add a `manifest.json`. See
[`demos/air-canada/build.py`](demos/air-canada/build.py) for a worked producer
that pins a policy, encodes a policy predicate as a re-executable `ski@v1` check,
files a signed `propose → reject` chain, and writes the manifest and keyring.

## Not in v0 (deferred)

Batch/Merkle anchoring of many packs to a public transparency log, eIDAS
qualified timestamps, and a signed manifest are out of scope for v0 — the
per-record hash+signature already makes a pack tamper-evident on its own. These
belong to the metering/anchoring layer, not the portable format.
