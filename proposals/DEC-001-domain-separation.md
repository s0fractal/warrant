# DEC-001 — Signature domain separation: adopt now, or decline permanently

**Status: OPEN. A recommendation, not a decision. Option A is IMPLEMENTED on a
branch, which is not the same thing.** This document was written by the
maintainer actor (`claude-fable-5`) on 2026-07-30 and decides nothing.

As of 2026-07-31 the branch `feat/domain-separation` implements option A across
SPEC §5, all three implementations, the conformance vectors and a migration
verb. **Adoption is a threshold warrant signed by roster keys (`AGENTS.md` rule
2); a branch is not adoption and this document does not record one.** The
prototype named below was replaced there by `tools/signature_vectors.py`.

**One factual claim in §4.3 and §6 of this document turned out to be false, and
it is the claim the cost argument rests on** — see §4.3 point 4 and the
correction appended to §7. The maintainer decides in front of that, too.

**The maintainer decides.** This document exists so that the decision is made
once, in front of the actual bytes, rather than defaulted into by silence.

---

## 1. The question

SPEC §5:

> `sig` = Ed25519 signature over the 32 raw bytes of the WarrantID. Verification
> is pure Ed25519 (RFC 8032, no context, no pre-hash): the message is the
> 32-byte WarrantID itself.

There is no context string, no prefix, no protocol identifier anywhere in the
signed message. The signed message is *indistinguishable from any other 32-byte
SHA-256 digest*.

IETF practice — and the reason RFC 8032 defines Ed25519ctx at all — is that a
key used in more than one protocol should not produce signatures that are valid
in both. The hazard has a name (cross-protocol replay) and a standard shape:
sign a domain-separated message.

The question is not whether raw-digest signing is unusual. It is: **is it worth a
breaking change to fix, and is now the moment?**

## 2. Why now is the only moment

- **The user base is zero.** README.md states plainly that the first real user is
  the author's sibling repository. There is no third-party implementation and no
  external consumer of the signature construction.
- **Every existing warrant is re-signable at zero identity cost.** The envelope
  is **not** hashed (SPEC §5): the WarrantID is SHA-256 of the canonical *body*.
  Re-signing changes only `sigs`. No WarrantID changes, no `prior` edge breaks,
  no `under`/`evidence`/`subject` hash stops resolving, no settlement tunnel
  moves. The prototype verifies this rather than asserting it.
- **The corpus is small and wholly under one custody.** Counted 2026-07-30: 19
  records in this repository (16 in `.warrants/`, 3 demo-pack records), 4 example
  envelopes, and 50 records in the sibling `sigma-glyph` store — **73 warrants
  total**, all signed by keys held by this project.
- **After the first outside adopter, both of those stop being true**, and the
  answer becomes "decline, we have users" without anyone having decided it.

That asymmetry is the entire argument for opening the question today.

## 3. What the hazard actually is (and is not)

**It is not a forgery of a Warrant record.** To turn a foreign signature into a
signature on a *chosen* warrant, an attacker would need a body that canonicalizes
to a chosen SHA-256 digest — a second-preimage attack on SHA-256. That is not the
threat.

**It is this.** If the same Ed25519 key is ever used in another protocol whose
signed message is a bare 32-byte digest, then:

- a signature that party produced *there* is a syntactically valid Warrant
  signature *here*, for the record whose WarrantID equals that digest; and
- a Warrant signature is a valid signature *there*, over whatever that digest
  means in that protocol.

The prototype demonstrates the first direction concretely: a signature over
`SHA-256("a message signed under some other protocol\n")` is accepted today as a
Warrant signature for the (non-existent) record with that WarrantID, and is
rejected under the proposal.

Concretely plausible collisions, none hypothetical as *formats*: Sigstore/DSSE
payload digests, in-toto Statement digests, TUF metadata digests, Git object
IDs, and — closest to home — Σ-GLYPH NodeHashes, which this project already
treats as 32-byte content addresses in the same store. This repository is
actively bridging to in-toto (`tools/intoto.py`). The population of "protocols
whose signed message is a bare 32-byte digest" is not small, and the project is
walking toward it.

**Severity, honestly.** By `SECURITY.md`'s ladder this is not a P0: nothing forged
reads as verified today, and no two conforming verifiers disagree. It is a
latent hazard whose cost is bounded by a key-management discipline that is
currently unwritten ("never reuse a Warrant key elsewhere") and unenforceable —
Warrant has no key-usage policy, no key-purpose field, and §5.1's keyring binds
an actor to a key without saying what else that key may do.

## 4. Option A — adopt a domain separator now

### 4.1. The construction

    legacy (in force):   msg = WarrantID_raw                       (32 bytes)
    proposed:            msg = b"warrant-sig-v1:" || WarrantID_raw (47 bytes)
                         separator hex: 77617272616e742d7369672d76313a

Still **pure RFC 8032 Ed25519 over a byte string** — not Ed25519ctx, not
Ed25519ph.

**Why not Ed25519ctx, which is the orthodox answer.** Because this project's
first law (SPEC line 5) is that independent implementations agree byte-exactly,
and Ed25519ctx is not uniformly available: Python's `cryptography` does not
expose it, Go's `crypto/ed25519` reaches it only through `Options`, and
`impl-rs`'s from-scratch verifier would need the `dom2` prefix machinery
implemented and differentially tested from nothing. A fixed ASCII prefix is four
lines in any language that can already verify Ed25519, is testable with the same
negative vectors, and buys the same separation. The orthodox choice would be the
one more likely to produce a verifier split — which is the failure this project
ranks P0.

**Why a fixed-length ASCII prefix and no length field.** The WarrantID is always
exactly 32 bytes and the separator is always exactly 15, so the encoding is
unambiguous by construction; no length prefix or NUL terminator is needed. The
string is greppable in a hex dump, which is worth something at 03:00.

**Why `v1` inside the separator.** It versions the *signature scheme*, not the
body version. `0.1` and `0.2` bodies share one envelope; a future change to how
signing works becomes `warrant-sig-v2:` and is again cleanly disjoint.

### 4.2. Version bump

This is a **breaking change to verification**, which under this project's own
rules is not a `0.2 -> 0.3` body-schema question at all: bodies do not change.
What changes is §5. Therefore:

- **SPEC document version -> v0.4**, with §5 rewritten and the old construction
  named and forbidden.
- **Body versions `0.1` and `0.2` are unchanged.** A migrated record has the same
  `warrant` value and the same WarrantID as before.
- **Package version -> 0.6.0.** A verifier that accepts the new construction and
  an older one that does not are mutually incompatible; the Action's capability
  check must learn about it.
- The **report tag stays `@v0`** — the report shape does not change. (This is
  exactly the four-numbers-move-independently case CHANGELOG.md warns about.)

### 4.3. Migration path

**There is no dual-accept window, and that is the point.** A verifier that
accepts both constructions has no domain separation: an attacker simply uses the
legacy one. Any transition period is a period with the vulnerability intact, so
the only coherent choices are flag-day or never.

1. **Cut the flag day at the 0.6.0 release.** Before it: legacy only. After it:
   new only. Nothing accepts both, at any time, under any flag.
2. **Re-sign the 73 existing warrants in place.** For each envelope, recompute
   the signature over the new message with the same key and rewrite `sigs`. The
   WarrantID does not change, so nothing that cites the record needs touching —
   verified by the prototype on all three §8 vectors.
3. **Re-sign the §8 test vectors and the demo packs**, and rebuild
   `air-canada-pack.zip` / `cross-vendor-pack.zip`. The §8 table's five hashes
   are unchanged (they are body and blob hashes); only the signatures inside the
   envelopes change. SPEC §8 must say so explicitly, because "the vectors are
   unchanged but the signatures are different" is exactly the sentence a
   re-implementer will misread.
4. **Records whose signing key is unavailable cannot be migrated.** ~~For this
   project's corpus that set is empty (one custody, all keys held).~~ **FALSE, as
   measured 2026-07-31 — see the correction in §7.** For anyone else it would not
   be empty either, and that is the honest reason this is a now-or-never decision
   rather than an anytime one.
5. **`sigma-glyph`'s 50 records** are the only cross-repository dependency; they
   are re-signed by the same process, and the sibling repository's cross-repo
   canary (`tools/x1_cross_repo.sh`) pins the pair, so the two must move
   together in one change.

### 4.4. Cost

- Three implementations change in one place each (the message fed to
  sign/verify). `impl-rs` is verify-only, so it is a two-line change there.
- Every negative vector involving a signature must be regenerated.
- Any evidence pack already downloaded by anyone stops verifying against a 0.6.0
  verifier. Given the release-asset history — packs first shipped 0.5.0, on
  2026-07-30 — that population is approximately nobody, today.
- One more thing for a re-implementer to get exactly right, with one more
  negative vector to catch them getting it wrong.

## 5. Option B — decline permanently, in writing

Take the position that the raw-digest construction is deliberate, and write the
reasoning into SPEC §5 so it stops being an open question that every reviewer
re-raises (two independent reviews have now raised it).

The argument that would have to be made, and it is not a weak one:

- **Warrant keys are single-purpose by convention.** A key exists to sign
  warrants; §5.1's keyring binds it to an actor for that purpose.
- **The hazard requires an attacker-favourable coincidence** — the same key, in
  another protocol, whose signed message is a bare 32-byte digest — and there is
  no known deployment where that holds.
- **Simplicity is a security property here.** "The message is the WarrantID"
  is a sentence a re-implementer cannot get wrong; a prefix is one more place to
  differ, and this project ranks a verifier split as P0 and cross-protocol replay
  as, so far, hypothetical.

If declined, SPEC §5 MUST gain (a) the rationale above, (b) an explicit
**key-usage requirement** — a key used for Warrant signatures MUST NOT be used in
any other protocol that signs bare digests, stated as a MUST NOT rather than left
to convention — and (c) a note that the decision was taken deliberately on a
stated date, with a pointer here. Declining without writing it down is the one
outcome that is strictly worse than either option, because the next reviewer
raises it again and the answer is still "nobody decided".

## 6. Recommendation: **Option A, adopt now**

Three reasons, in order of weight.

1. **The cost is at its global minimum today and rises monotonically.** Zero
   external users, all keys under one custody, 73 records, and re-signing costs
   no identity because the envelope is not hashed. Every one of those facts is
   temporary, and the project's stated goal is to make them stop being true.
2. **The project's own standard is higher than "no known exploit".** This is the
   repository that blocklists eight small-order Ed25519 encodings byte-exactly
   because *libraries disagree*, that rejects a BOM in the canon, and that treats
   "the spec is silent where an implementer must guess" as a P1. Against that
   standard, "we sign a bare digest and rely on nobody reusing the key" is out of
   character — and a reviewer will notice the inconsistency before they notice
   the hazard.
3. **It is walking toward the collision.** `tools/intoto.py` bridges to in-toto,
   whose Statement digests are 32 bytes; Σ-GLYPH NodeHashes are 32 bytes and live
   in the same store; anchoring already emits RFC 6962 Merkle roots, which are 32
   bytes. The set of nearby protocols that sign bare digests is growing, not
   shrinking.

Against the recommendation, stated fairly: **the honest severity is low**, the
change breaks every artifact the project just released, and a maintainer with one
person's capacity may reasonably decide that a re-release two days after 0.5.0
costs more credibility than a latent hazard costs security. That is a legitimate
call and is why this document does not make it.

**If adopted**, the change should ship as one atomic commit series across both
repositories: SPEC §5 + three implementations + regenerated vectors + re-signed
stores + rebuilt packs + CHANGELOG, with the negative control this project
requires (revert the change; show the new-construction vectors fail).

**If declined**, the SPEC §5 text in §5 above should be written the same day.
The one unacceptable outcome is this document sitting open.

## 7. Evidence

`tools/domain_separation_prototype.py` (DRAFT; wired to nothing) produces
`examples/draft/domain-separation-vectors.json`. Run:

    python3 tools/domain_separation_prototype.py

For the SPEC §8 `accept` vector, WarrantID
`bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78`:

| | value |
|---|---|
| legacy message | `bc602a70…bc78` (32 bytes, the WarrantID) |
| proposed message | `77617272616e742d7369672d76313a` ∥ `bc602a70…bc78` (47 bytes) |
| legacy signature | `c72e16f1…0005` — byte-identical to the one committed in `examples/accept.warrant.json` |
| proposed signature | `db19ae73…6703` |

Cross-verification, all three §8 vectors:

| | legacy rule | proposed rule |
|---|---|---|
| legacy signature | **accepted** | rejected |
| proposed signature | rejected | **accepted** |

The two constructions are cleanly disjoint — which is what makes a dual-accept
window pointless and a flag day workable. And re-signing leaves every WarrantID
identical, which is what makes the migration cheap.

Cross-protocol illustration: a signature over
`SHA-256("a message signed under some other protocol\n")` is **accepted as a
Warrant signature today** and **rejected under the proposal**.

---

## 8. Correction, 2026-07-31: the corpus is NOT wholly re-signable

§2 and §4.3 assert that every existing warrant is re-signable at zero cost
because "the corpus is small and wholly under one custody". The first half is
right and was re-verified: re-signing changes only `sigs[].sig`, and all four
example vectors keep their WarrantID byte-for-byte (`tools/signature_vectors.py`
recomputes it rather than asserting it).

The second half is wrong. The private key for `claude-fable-5@warrant` /
`claude-fable-5@sigma-glyph` — public key
`3449536017e5b4a4c7e134999cbd9fe94c5354bd9132d6c1e32f024bfd90eb27`, the signer of
**all 16 records in this repository's `.warrants/`** and of part of `sigma-glyph`'s
50 — is not present on the host where this work was done. Searched: `~/.config/warrant/`
(which holds `codex.key` and `s0fractal.key` and, per `AGENTS.md` rule 6, held this
one on 2026-07-28), every file under `~/Projects`, `~/.Trash` and the agent
scratchpads, every 64-hex string in every git object of both repositories, and
every agent transcript on the host. Not found.

That does not prove the key is destroyed — the likeliest reading is that it was
deliberately moved off this host after the co-located-keys finding that produced
`AGENTS.md` rule 6, which is a *good* thing to have done. It does mean:

- the migration is **not** executable by whoever holds this checkout; it is
  executable only where that key lives;
- until it runs, this repository's own store fails verification under §5 — 16
  records, 16 errors, all three implementations agreeing exactly;
- the cost line in §6 ("re-signing costs no identity") is still true, and the
  cost line in §2 ("all signed by keys held by this project") is not established.

The generalisable lesson is the one §4.3 point 4 already stated and then
exempted itself from: **"all keys are held" is a claim about an operational
fact, and a decision that rests on it should verify it before, not after.** For
a corpus of 73 records under one nominal custody, the un-re-signable subset was
66. An outside adopter's would be worse.

Migration command, to be run where the key lives (both repositories):

    python3 impl/warrant.py --store .warrants resign --key <claude-fable-5.key>
    python3 <warrant>/impl/warrant.py --store <sigma-glyph>/.warrants \
        resign --key <claude-fable-5.key>

`resign` refuses to touch a signature made by any other key, names each record it
could not migrate, and exits non-zero if any remain — so a partial migration
cannot report success.
