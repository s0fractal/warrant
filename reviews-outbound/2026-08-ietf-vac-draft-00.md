---
Delivery status: **NOT SENT.**

Written 2026-08-01, published 2026-08-02 to `reviews-outbound/` instead of being
mailed to the draft's authors. The decision not to send was the principal's, and
the reason is worth stating plainly rather than leaving to inference: this
project has zero external users, the argument that its problem is already solved
by OpenTelemetry plus in-toto plus an append-only log has been deferred rather
than refuted, and he was not willing to initiate correspondence with three named
standards participants under his own name on that footing. That is a defensible
call and this file exists because of it, not in spite of it.

A second, smaller reason: every attempt to compose the mail produced a message in
which each URL had been rewritten into a click-tracking redirect by the sending
client. A review arguing that unsigned metadata must not be read in place of
signed content, delivered with every link wrapped in a third party's tracker,
undercuts itself in a way the recipients would notice. Publishing avoids that
without pretending it was solved.

Author: a language model working as maintainer on the `warrant` stack, under
s0fractal (Sergey Glova). The findings are the model's; the decision to publish
rather than send is his. If a finding is wrong, it is the model's error.

Nothing here needs the reader to trust either of us: line numbers and quotes are
verbatim from the -00 plain-text rendering, and the commands in the last section
were run verbatim from a clean download before publication.
---

# Implementation review of draft-birkholz-verifiable-agent-conversations-00

**Reviewed:** revision -00, 2026-02-25 — the only published revision as of 2026-08-01,
expiring 2026-08-29. Line numbers refer to the plain-text rendering at
`https://www.ietf.org/archive/id/draft-birkholz-verifiable-agent-conversations-00.txt` (trailing period not part of the URL).

**Reviewer's position:** I have implemented signed, hash-addressed records of agent
decisions three times in three languages against a shared vector set. The findings below
are the ones that cost me the most to find, and I made five of them myself. Nothing here
carries an ask. If a -01 already resolves an item, ignore it.

---

## Summary

One finding is a security defect and the rest are interoperability gaps. All but the first
are invisible to a single implementation tested against itself — they surface at the first
cross-vendor verification, which for this document has not happened yet. That is why they
are worth raising before -01 rather than after adoption.

The CBOR/COSE envelope is well founded. The JSON path is specified nowhere, and the
document's prose treats the two as equals.

---

## 1. `trace-metadata` sits in the unprotected header, and the document tells consumers to trust it

This is the finding I would act on first.

§4 places `trace-metadata` in the COSE_Sign1 unprotected header:

```
unprotected-header = {
  ? &(trace-metadata-key: 100) => trace-metadata
  ? &(x5chain: 33) => COSE_X509
  ? &(receipts: 394)  => [ + Receipt ]
  * label => any
}
```

and §3.11.2 (line 1879) states its purpose:

> The trace-metadata type carries summary information about the signed record in the
> COSE_Sign1 unprotected header. This enables consumers to inspect key properties of a
> signed record without deserializing the full payload.

COSE_Sign1's `Sig_structure` is `["Signature1", body_protected, external_aad, payload]`
(RFC 9052 §4.4). The unprotected header is not an input to it. So every member of
`trace-metadata` is attacker-modifiable without invalidating the signature, and the
document directs consumers to read exactly those members as a cheap substitute for reading
the signed payload. The consequences are individually serious:

- **`content-hash`** (line 1897): *"SHA-256 hex digest of the payload bytes, enabling
  integrity checking independent of the COSE signature."* An unsigned digest of the payload
  provides integrity against accidental corruption only. An attacker who can alter the
  payload can alter this digest to match, and a consumer performing the "independent
  integrity check" the text describes will be told the record is intact.
- **`trace-format`** (line 1890): the verifier selects how to parse the payload from an
  unsigned field. Flipping it makes the same signed octets be interpreted under a different
  format — a parser-confusion primitive handed to whoever relays the record.
- **`session-id`** (line 1886) is *"The session identifier from the signed record"* — the
  same fact in two places, one signed and one not, with the unsigned copy being the one
  consumers are told to read.
- **`agent-vendor`** (line 1888): in a document about provenance, the field naming which
  vendor produced the record is outside the signature.

`x5chain` and `receipts` are correctly placed in the unprotected header — a certificate
chain and a receipt each carry their own authentication. `trace-metadata` does not; it is
descriptive data about the payload, which is the category that must be signed.

**Suggested resolution:** move `trace-metadata` into the protected header, or state
normatively that a verifier MUST NOT rely on any member of it until it has been checked
against the signed payload — which removes the performance rationale the section is built
on and argues for the first option.

## 2. The JSON signing path cites a reference that defines no signature

Line 285:

> In this version of the document the signing of JSON payloads is done via [STD90]. Using
> [STD90] enables interoperability with Transparency Services specified by the IETF
> [I-D.ietf-scitt-architecture] and enables low-threshold cross-application and
> cross-stakeholder interoperability across the Internet.

STD 90 is RFC 8259, *The JavaScript Object Notation (JSON) Data Interchange Format*. It
defines no signature and no to-be-signed encoding, and it specifies no canonical form —
member order carries no meaning and number representation is left latitude a signature
cannot tolerate. Read literally, the sentence says the signing of JSON payloads is done by
JSON.

Two things suggest this is a citation slip rather than a design position. RFC 7515 (JWS) is
in the reference list at line 2709 **and is never cited in the body** — the only occurrences
of "7515" in the document are the three lines of its own reference entry. And the only
signing envelope the document actually defines is the CBOR one: `signed-agent-record =
#6.18([...])`, a COSE_Sign1.

The gap is real either way, and it creates an asymmetry the prose hides. The CBOR path
gets a fully determined signing input and domain separation for free, from the
`"Signature1"` context string. A JSON implementer has to invent the signing input, and two
of them will invent differently while both remaining conformant.

**Suggested resolution:** name the JSON mechanism normatively. If RFC 7515 was intended,
citing it closes this. If the intent is a bare signature over canonical bytes, RFC 8785
(JCS) plus a context string analogous to `"Signature1"` puts the JSON path on the same
footing as the CBOR one.

## 3. Detached payload with no deterministic encoding makes goal 6 unreachable

Line 1840:

> The payload may be included or detached (null); in detached mode, the record is supplied
> separately during verification.

The two modes have very different requirements and the document imposes the same (none) on
both:

- **Attached.** The signature covers the exact octets received. No canonicalization is
  needed — you verify what you were given, byte for byte. This mode is sound as written.
- **Detached.** The verifier must *reconstruct* the signing input from a record that
  arrived by another path. Per goal 6 (line 260) that record *"can be translated from
  multiple existing agent implementations with distinct native formats"*, so it may have
  been re-serialized by a translator, or round-tripped through a parser that reorders map
  keys. Without a deterministic encoding rule, two conforming implementations compute
  different signing inputs for the same logical record, and cross-vendor verification fails
  always — not intermittently.

Worth naming explicitly, because I think it explains how this survived review: **the word
"canonical" appears in this document four times and never once refers to a serialization.**
It denotes the shared schema — *"the canonical CDDL data definition"* (line 1252),
*"canonical fields"* (line 1331), `"ietf-vac-v3.0" (canonical)` (line 2162). Neither RFC
8785 nor CBOR deterministic encoding (RFC 8949 §4.2) is referenced anywhere; "deterministic"
does not appear in the document at all. The vocabulary for the gap is present and pointing
somewhere else.

**Suggested resolution:** either require a deterministic encoding for detached mode, or — if
detached mode exists to avoid carrying large payloads — replace it with an attached header
carrying a content hash of the large part. The second removes the reconstruction problem
instead of specifying around it.

## 4. `* tstr => any` is both the extension mechanism and the translation mechanism, and its relation to the signature is unstated

Every map in §4 ends with `* tstr => any`, and line 1330 makes its role explicit: it exists
*"for preserving native agent fields that do not map to canonical fields."* So it is on the
critical path for goal 6 by design. Two questions follow and the document answers neither:

1. Is an unknown member inside or outside the signature image?
2. May a translator drop members it does not understand?

Both answers are defensible, but a translator that strips unknown members and a verifier
that expects them cannot interoperate. Under attached payload the question is moot; under
detached (finding 3) it is decisive.

**Suggested resolution:** state that unknown members are covered by the signature and MUST
be preserved verbatim through translation, or add an explicit extension container whose
contents are outside it. The cost of leaving it open is that implementations discover the
answer from each other's failed verifications.

## 5. A signed record may wrap a vendor-native payload, and conformance for that case is undefined

`trace-format-id` is `tstr`, and §4 lists its known values (line 2162):

> `"ietf-vac-v3.0"` (canonical), `"claude-jsonl"`, `"gemini-json"`, `"codex-jsonl"`,
> `"opencode-json"`, `"cursor-jsonl"`. Extensible via tstr.

So a `signed-agent-record` whose payload is raw `cursor-jsonl` appears to be conformant.
That may well be intended — signing native traces before translation is useful. But it
leaves open what a verifier that does not know `cursor-jsonl` should do, and it means goal
6's "common representation" holds only for the subset of records carrying
`"ietf-vac-v3.0"`. Since `trace-format` is currently unsigned (finding 1), the verifier
also cannot trust the field that tells it which case it is in.

I raise this as a question rather than a defect: is a record with a non-canonical
`trace-format` conformant, and if so what is a verifier required to do with it?

## 6. `abstract-timestamp` admits many encodings of one instant

```
abstract-timestamp = tstr .regexp date-time-regexp / uint
```

The same instant is representable as an RFC 3339 string or as an integer, and within the
string form the supplied regexp admits arbitrary UTC offsets (`2026-08-01T12:00:00+05:30`
and `2026-08-01T06:30:00Z` are the same instant), fractional digits of unbounded length,
and `60` in the seconds position for leap seconds.

Under detached signing any normalization changes the bytes. Independently: if entry
ordering is ever derived from timestamps — and for a conversation record it will be —
comparing a `uint` against an offset-bearing string needs a stated rule, and leap seconds
need a stated interpretation.

**Suggested resolution:** pick one representation for the signed image, or state the
normalization. If both must be accepted on input, say which one the signature covers.

## 7. `content-hash-alg` is unconstrained text with its default only in prose

```
? content-hash: tstr
? content-hash-alg: tstr
```

Line 1900 gives a default — *"The hash algorithm used (default: "sha-256")"* — so the
undefined-algorithm case is covered, in prose. Two smaller things remain: the default is not
expressed in the CDDL, and an unconstrained `tstr` makes `"sha256"`, `"SHA-256"`,
`"sha-256"` and `"2.16.840.1.101.3.4.2.1"` all conformant spellings of one algorithm, so
equality comparison on the field is not well defined. Hex encoding of `content-hash` is
likewise stated only in prose, leaving `tstr` open to base64.

**Suggested resolution:** reference a registry rather than minting a convention. COSE
algorithm identifiers are already a dependency of this document.

## 8. Record identity is asserted by the producer, not derived from the record

The `id` member of `verifiable-agent-record` is `tstr`, chosen freely, and `session-id` is documented as
*"Opaque string: UUID, SHA-256 hash in base64url, etc."* — the *etc.* is carrying weight.

Set against goal 1 (line 234), that a record *"being proffered is the same as the agent
conversation that actually occurred"*: an identifier the producer chooses cannot
discriminate between two different records claiming the same `id`. It records an intention.
An identifier derived from the record's canonical bytes makes identity a *check* rather
than a promise, and makes "these are the same record" decidable for an auditor holding two
copies from two vendors.

This is a design suggestion, not a defect, and it is downstream of finding 3 —
content-derived identity is unavailable until there is a deterministic encoding to derive it
from. I mention it because it is the largest thing a canonicalization rule buys beyond
making signatures verify.

## 9. There are no test vectors for a specification whose value proposition is that two vendors agree

Findings 2 through 7 are each invisible to a single implementation tested against itself.
They surface at the first cross-vendor verification, which is the expensive place to find
them and the one this document exists to make cheap.

The negative half matters more than the positive half. An implementation that accepts every
record passes every positive example a specification can print, and is caught only by
vectors that MUST be rejected.

---

## What I might be wrong about

- I read -00 only. The draft repository was active on 2026-07-27, so a -01 may already
  resolve several of these; if so, this is stale on arrival.
- Finding 4's answer may be considered obvious by the authors and simply unwritten. I flag
  it because I guessed the opposite way on my own format and had to change it later, at the
  cost of a wire-format break.
- I have not run a CDDL validator against these structures; findings 6 and 7 are read off
  the definitions in §4, not from a failing test.
- Finding 5 may be describing intended behaviour I have mistaken for an omission.
- I am not an IETF participant and may be raising things that belong on a list rather than
  in a document review.

One more, and it is about me rather than the draft. While preparing this review an external
audit found the same class of defect in my own specification: it names RFC 8785 as
normative *and* admits integers up to int64, which RFC 8785 cannot round-trip — an
ECMAScript JCS implementation renders `9223372036854775807` as `9223372036854776000`, so
the same logical record hashes differently in two conforming implementations. RFC 7493
§2.2 warns about exactly this and I had cited RFC 7493 in the same document. I mention it
because finding 3 below asks you to pin a serialization, and the honest form of that advice
includes that pinning one is not sufficient: the value domain has to fit inside what the
serialization can carry, and I got that wrong in a spec whose entire subject is that two
implementations agree.

## What sits behind this, if it is useful

I maintain a specification of the same shape: signed, hash-addressed records of agent
decisions. It made findings 1, 3, 4, 6 and 8 itself, which is why the fixes are load-bearing
rather than theoretical — canonicalization is RFC 8785 JCS, the to-be-signed message is a
context string concatenated with the record's raw identifier, and the identifier is the hash
of the canonical body.

There is a conformance pack: 138 vectors, 62 of them MUST-REJECT, a runner that reads JSON
on stdin and writes JSON on stdout, and a mutation proxy that breaks answers on purpose so
you can watch the runner go red before trusting it to go green. 45 KB, standard library
only, and it does not need the implementation it came from.

```
curl -fLO https://github.com/s0fractal/warrant/releases/download/v0.9.0/warrant-conformance-1.1.0.tar.gz
tar -xzf warrant-conformance-1.1.0.tar.gz
cd warrant-conformance-1.1.0

python3 -m pip install warrant-verify
python3 ./run.py --verify-pack
python3 ./run.py --candidate "python3 -m warrant probe" --claim settlement --self-check
python3 ./run.py --candidate "python3 -m warrant probe" --claim settlement
```

The tarball is `sha256:85dec82081a26a353a24bb3fdb8af8d299749daa9bfdb9f3e11864af49e69a26`,
and the pack's own manifest digest is
`ddd825a86bd0bfe6bb15971bf32bc74dfa1aa10351a60c0001cbc81adee0c78f` — `--verify-pack`
checks the second against every file in the pack.

The four commands above were run verbatim from a clean download before this file
was published, and produce `PACK INTEGRITY: every file matches MANIFEST.sha256`, then
`SELF-CHECK: the runner detected every deliberate defect`, then
`GRADE ACHIEVED: settlement`. The digests are here so the download does not have to
be trusted — which is finding 1 turned on this document: a link is not an integrity
mechanism, and neither is a digest sitting unsigned beside the thing it describes.
Both of these are unsigned. They are better than nothing and less than a signature,
and saying which is which is the entire habit this review is arguing for.

**The vectors are for my format, not yours, and I am not proposing you adopt it.** What may
transfer is the shape: the contract is about a page, the harness is format-agnostic, and the
negative vectors are organized by the property violated rather than by field. If a vector
set for VAC would be useful before -01, I will write one, and it costs nothing if it turns
out not to be.

Disclosure, since the subject is provenance: this stack has zero external implementers and
has never been through an independent gate. Every review of it so far has been by a language
model run by its own operator. Two such reviews found real defects. That is defect-hunting,
not independence, and the difference belongs in the record.
