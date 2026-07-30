# Threat model

**Status: DRAFT, 2026-07-30. Not adopted** (adoption is a threshold warrant
signed by roster keys — `AGENTS.md` §2 — and has not happened). This document
consolidates; it does not decide. Where it and `SPEC.md` disagree, SPEC is
normative and this file is a defect.

## Why this file exists

The threat model was real and scattered: severity ladder and scope in
`SECURITY.md`, the structural limits under `llms.txt`'s "honest gaps", the reasoning
for each fail-closed choice inline in `SPEC.md`, custody facts in
`policies/gate-settlement.json`, key-binding consequences in the sibling `oaip`
repository's source comments. A reader asking the one question that matters —
*given an attacker who can do X, what does Warrant still give me?* — had to
assemble it from five places and would miss one.

So: one attacker-capability matrix, and one formal statement of the scoped
assumptions and explicit non-goals — the same residuals, in the form a standards
reader expects, stated as plainly here as they are anywhere in the repository.
This file is where they live; the orientation files point here.

## What Warrant claims

One sentence, because everything below is a limit on it:

> Given the bytes of a store, anyone can recompute **that these records say what
> they say**, **that these keys signed them**, and — for `ski@v1` reasons —
> **that this reason really does evaluate to this verdict**, without trusting
> whoever handed them the bytes.

Everything Warrant does not claim follows from three facts: the store is a
directory anyone with write access can add to; **key↔actor binding is a local
configuration decision, not a protocol fact**; and one reason kind (`cmd@v1`) is
trusted by specification.

## The attacker-capability matrix

Read a row as: *this attacker has this capability; here is what still holds, and
here is what they get.* "Detected" means a conforming verifier reports it;
"prevented" means it cannot be produced at all.

| # | Attacker | Capability | What still holds | What they get | Where |
|---|---|---|---|---|---|
| A1 | **Store writer** | Add/modify/delete any file in `.warrants/` | Every record's identity is the hash of its body. Editing a body changes its WarrantID, so every record citing it stops resolving. Swapping a blob at its own address is detected for all five content kinds. | **Deletion and censorship.** Nothing in the format makes a store complete: a record removed leaves a dangling `prior`, which is a *warning*, not proof of what was removed. Also arbitrary **insertion** — see A2. | SPEC §4, §6 |
| A2 | **Anyone with a keypair** | File a record claiming any `actor.id` | The signature verifies against the key *stated in the envelope*. The verifier reports the binding as unverified. | **A signed record attributed to any actor**, at base grade, for free. `warrant verify` exits 0 with one WARN. This is the sharpest edge in the whole format and it is disclosed, not defended: see SA-2. | SPEC §5, §5.1 |
| A3 | **Malicious co-signer** | Append signatures to any stored envelope | Co-signatures are outside the hash, so appending one cannot change a WarrantID or invalidate a record that still carries a valid `body.actor.id` signature. An invalid co-signature is WARN-and-excluded. | **Noise, and a false appearance of endorsement to a reader who counts signatures instead of verifying them.** For §5.1 thresholds an invalid or unbound signature simply does not count — but that is settlement grade only. | SPEC §5, §5.1 |
| A4 | **Unbound key holder** | Sign as an actor the verifier's keyring does not vouch for | At **settlement** grade with a trust configuration, the signature does not satisfy any §5.1 threshold and the record is reported `signature unbound`. | At **base** grade: a WARN and nothing else. A deployment that gates on `ok` alone accepts it. | SPEC §5.1, §11 |
| A5 | **Blob transport** | Control the channel delivering blobs | Every blob is fetched by hash; a substituted blob does not match its address and is detected. Content addressing makes transport untrusted **by construction** — this is the strongest guarantee here. | **Withholding.** An unresolvable blob is a warning, and a record whose settlement-critical references do not resolve is settlement-*inactive* — so withholding a blob can suppress a foreclosure or a settlement, silently, until it resolves. | SPEC §6(5), §7 |
| A6 | **Hostile policy author** | Author the blob a record cites in `under` | The exact bytes are pinned by hash: nobody can change what a decision was made under, after the fact. | **Whatever the policy says.** Warrant pins *which* rules were in force, and takes no position on whether they were good rules. A policy blob is opaque at v0.1/v0.2; only a v0.3 threshold policy is parsed, and an invalid one is an ERR at settlement grade rather than an accident. | SPEC §2, §5.1 |
| A7 | **`cmd@v1` filer** | Claim any verdict for a container-executed check | Nothing. The verifier does not re-execute `cmd@v1`; its trust model is the container, by specification. | **A forged reason, and — worse — a re-litigation.** See SA-1. | SPEC §3, §6(7) |
| A8 | **`ski@v1` filer** | Claim any verdict for a portable check | The verifier re-runs the reduction against the store's blobs and compares hashes. A false claim is detected and reported. Work **and peak memory** are bounded by `atp`, so re-running a stranger's reason is safe by construction. | **Almost nothing** — this is the format's actual contribution. The residual: a reason whose `atp` exceeds the local budget is reported `unverified`, never `pass`, and two verifiers with different budgets may disagree about whether it *ran*. That divergence is a deliberate local-policy choice, and "was not executed" is never observationally equivalent to "re-ran and matched". | SPEC §3.1, §6(7) |
| A9 | **Genesis/root forger** | Write `genesis.json`, or file a root | `genesis.json` is advisory and MUST NOT be a trust anchor; an unpinned one is `WARN: genesis.json unverified` and its contents are unused. An unadopted root is excluded from settlement with `WARN: unadopted root`. | **Nothing at settlement grade**, provided the verifier has a trust configuration. Without one, there is no notion of an active root to attack — and no settlement either. | SPEC §9, §12 |
| A10 | **Key rotator** | File rotation/revocation warrants | Rotation requires proof-of-possession by the incoming key and authorization under the current key policy; the incoming key's PoP does not count toward a threshold; under a multi-actor threshold the outgoing key's signature is not sufficient. Key validity derives from DAG order, never from wall-clock `ts`. | **A conflict, which is a denial rather than a takeover.** Mutually unordered authorized rotations produce `WARN: key-state conflict` and the actor's key counts toward no quorum until resolved. | SPEC §5.1 |
| A11 | **Re-litigant** | File warrants to re-open a settled matter | A re-litigation must carry evidence absent from the tunnel, or a check re-running to a previously absent outcome fingerprint. Prose alone never re-opens anything. | **Unbounded but syntactic noise.** Novelty is purely syntactic; whether a novel check is *relevant* is delegated to the active settlement policy. A permissive policy accumulates fingerprint-distinct irrelevant re-litigations. And with `cmd@v1`, novelty is satisfiable by writing a different word (A7). | SPEC §7 |
| A12 | **Signature-domain attacker** | Get a Warrant key to sign in another protocol, or vice versa | Nothing at the protocol layer. | **Cross-protocol replay, if such a protocol exists.** A Warrant signature is raw Ed25519 over a bare 32-byte SHA-256 digest with no context string, so any other protocol in which the same key signs a raw 32-byte digest can produce a signature that verifies as a Warrant, and conversely. **No such protocol is known to exist today and the user base is zero**, which is exactly why the decision is open now: `proposals/DEC-001-domain-separation.md`. | SPEC §5 |
| A13 | **Verifier operator** | Run a modified verifier | Nothing protects a user from their own tooling. | **Everything, for that user only.** The mitigation is structural, not cryptographic: three independent implementations must agree byte-exactly on every WarrantID and every verification outcome, so a lying verifier is detectable by running another one. That is the reason the differential harnesses exist and the reason a Python/Go split is ranked P0. | SPEC line 5 |
| A14 | **Reader of a `verify` result** | — | `ok == (errors == 0)`, closed report schema, counts bind findings. | **A misreading, if they treat `ok:true` as "trustworthy".** `ok` means no §6 error at the requested grade. A store of records signed by keys nobody vouches for is `ok:true` with warnings. | SPEC §11 |

## Security assumptions and non-goals

What Warrant assumes of its environment, and what it declines to do. This is
where those statements live: `llms.txt` and `SECURITY.md` point here instead of
carrying their own copies, so the same item is not maintained in three places and
cannot drift between them.

Scope of that claim, because this project has been caught overstating one before:
it covers the residuals those two files used to list, plus the ones already in
this document. It is **not** a claim that every limit of Warrant is enumerated
below — `SPEC.md` states limits inline where they are normative, `CHANGELOG.md`
records what each release did and did not fix, and the `reviews/` corpus holds
findings that were never promoted to either. If you find a limit stated somewhere
else and not here, that is a defect in this file.

Read it the way a standards reader reads a security-considerations section, not
as a confession. Every item below is one of two things:

- a **scoped assumption** (`SA-n`) — a condition Warrant requires of its
  environment and does not itself establish. Stating it is what makes the
  guarantees above precise; leaving it out would make them false.
- an **explicit non-goal** (`NG-n`) — a property Warrant deliberately does not
  provide, with the reason it is out of scope.

The two together define the boundary of the threat model. Anything inside the
boundary that fails is a **defect** and is in scope for a report. Anything an
item below already states is **not** a defect — but a demonstration that reality
is *worse than the item states* is, and is the most valuable report this project
can receive. SA-2's `--json` omission and SA-5's two `impl-rs` P0s reached this
document exactly that way.

None of what follows is adopted, and none of it has passed an independent gate;
see SA-10.

### Scoped assumptions

#### SA-1. `cmd@v1` verdicts are trusted by specification — and that reaches settlement

`cmd@v1` says "this command exited 0". The verifier does not re-run it (§6(7)):
its trust model is whoever trusts the container. That much is an honest
engineering trade.

The consequence that is easy to miss: §7's re-litigation novelty test admits a
**new outcome fingerprint**, and a `cmd@v1` fingerprint is
`{runtime, sorted evidence hashes, verdict, transcript hash}` — which contains
the **verdict its filer wrote**. So a party who wants to re-open a settled matter
can satisfy the novelty test by filing the same check with the opposite verdict.
*By writing a different word.*

Settlement's strongest guarantee therefore holds only for `ski@v1` reasons, where
the fingerprint records the **re-run** verdict rather than the claimed one (fixed
in 0.5.0). This is a limit of the format, not of the code. Two paths exist and
neither is taken: require `ski@v1` for settlement-grade novelty, or make the
`cmd@v1` fingerprint depend only on the transcript hash rather than the verdict.
Recorded here, not decided here.

#### SA-2. Key↔actor binding is assumed to be solved outside the format

SPEC §5 puts key↔actor binding out of scope ("use your existing PKI/keyring").
§5.1 adds that no keyring format is mandated and that **bound/unbound is a
report** unless a v0.3 policy explicitly requires bound signatures for
settlement.

The consequence, measured rather than theorised. The sibling `oaip` project — the
first external consumer of this format — reproduced the following on its own
store and wrote it into `impl/oaip.py`:

```
warrant keygen --out attacker.key
warrant --store … accept … --actor tester@local --key attacker.key
  -> then `verify` reports: 0 errors, 1 warning ("binding unverified (no keyring)")
```

*"…for a claim NOBODY accepted. The protocol's central fact, forged for free."*

`warrant verify` cannot be configured to fail on an unbound signature, so `oaip`
built its **own** keyring and its **own** enforced signer gate rather than rely
on this one. That is a real interop finding and it belongs here rather than in a
footnote: a format whose only external consumer had to implement its own identity
enforcement has, at that layer, failed to be a format. What it costs is
reusability — every adopter re-solves binding, and they will not solve it the
same way, so two adopters' stores will not be mutually verifiable at the identity
layer even though they are byte-identical at the record layer.

Two things soften it and neither removes it: at **settlement** grade with a trust
configuration (§12), an unbound signature satisfies no §5.1 threshold and is
reported `signature unbound`; and §5.1's key-state warrants give rotation and
revocation a DAG-derived truth. Both require the operator to have pinned a
genesis keyring out of band. There is no identity-federation path — no DID, no
X.509, no Fulcio-style ephemeral-key-plus-OIDC — and no design for one.

A related defect, found and fixed on 2026-07-30, made this materially worse than
designed: the `signature unbound` WARN was emitted in text mode but **omitted
from the `--json` report**, so an integrator consuming the documented machine
boundary saw `warnings:0` and no finding for an unbound signer. `oaip` documented
that too. The report is now renderer-independent; the *design* limit above
stands.

#### SA-3. A threshold assumes independent custody; here it has not had it

As of 2026-07-28 the roster keys `claude-fable-5` and `codex` sat in one
directory on one host, so any process there could sign as both
(`policies/gate-settlement.json`, `custody`). Two such signatures are **one
custody**, and the multi-actor threshold machinery — which is correct as
specified — currently protects against nothing in practice for this repository's
own governance store. Stated in `AGENTS.md` (as a DRAFT rule) and in the gate
policy; stated here because a threat model that omits its own author's key
custody is decoration.

How little has actually been exercised, counted rather than characterised:

- **In this repository, no threshold has ever been exercised.**
  `trust-config.json` lists exactly one actor — `claude-fable-5@warrant` — and
  none of the 16 records in `.warrants/records/` carries more than one signature.
  There is no human key in this repository's own trust configuration.
- **In `sigma-glyph`, five times**: the v0.6.2 – v0.6.6 anchor-set adoptions, and
  nothing else among that store's 50 records carries a second signature. Three of
  the five pair `claude-fable-5` with `codex` — the co-located pair above, i.e.
  one custody, i.e. ceremony with a single party. The other two pair
  `claude-fable-5` with the founder key `s0fractal@sigma-glyph`.

So where a document in either repository describes "2-of-3 governance", the
correct reading is: a 2-of-3 policy, satisfied five times, twice by two distinct
parties and three times by one. Anything stronger overstates.

The project's own answer to this is worth naming because it is unusual: blocking
power in the gate policy belongs to **re-runnable evidence**, not to a signature,
precisely because a stranger can re-run a reproduction on their own machine and
cannot re-derive a signature from a shared keyring.

#### SA-4. The reviewer quorum is not independent, and is often not available

Adversarial gates are run by model families operated by one person on one
account. `policies/gate-settlement.json` records the honest state as **UNGATED**
when no gating family is affordable, rather than pretending a threshold was met.
Measured on this repository: one family iterating produced eight consecutive
AMENDs and no P0; the first three-family round returned three REJECTs and six
P0s, nearly disjoint. Diversity found them; depth did not. Treat any single-family
gate result accordingly.

#### SA-5. `impl-rs` assumes differential testing in place of an audited crypto library

`impl-rs` implements SHA-256 and Ed25519 verification from scratch, with no
crates, and is differentially tested against `cryptography` (50 random cases per
run, plus RFC 8032 TV1 and the §8.3 weak-key battery). Two P0s were found in it
by an external audit and fixed. It remains hand-rolled verification crypto in a
trust path; differential testing narrows that risk and does not eliminate it. Use
`impl/` or `impl-go/` where that matters.

#### SA-6. Three-way parity is assumed only at base grade

`impl-rs` implements SPEC §6 **base grade only**: no settlement, no key state, no
trust config, and `ski@v1` reasons are reported `unverified: runtime
unavailable`. Three-way parity is a claim about base-grade verification.
Settlement-grade parity is Python↔Go — tested in `tests/verify_three_way.py` on
nine deliberately broken stores, so the base-grade claim is that all three agree
on broken stores as well as clean ones. §9 multi-root behaviour is vectored only
as far as root admission (SA-7). The most novel layer of the format is the least
proven implementable from the text by a stranger.

#### SA-7. §9 multi-root behaviour is assumed correct beyond root admission

Multi-root stores (§9) are verified by vector only as far as **root admission**.
The threshold rule that gates adoption is exercised, including that an unbound
key claiming an actor does not satisfy it. Deeper §9 behaviour — the interaction
of several admitted roots across a settlement — has no vector here. The
assumption is that an implementation which passes root admission implements the
rest as written; nothing in this repository checks it.

#### SA-8. Part of the Lean chain assumes the compiler

Part of the proof chain rests transitively on `native_decide`, which puts the
Lean compiler in the trusted base alongside the kernel. Those theorems are
therefore *conditional on the compiler being correct*, and the condition is not
discharged anywhere. The sibling repository's `proofs/README.md` says which
fronts are affected and which are not.

#### SA-9. `settle.py` assumes nothing about claims it never re-ran

`settle.py` reports **UNRESOLVED about itself**: claims raised against superseded
revisions that were never re-run to a decision. It says so rather than assuming
its own fixes closed them. So the settled/unsettled state it reports is sound for
what it ran, and silent — deliberately, not accidentally — for what it did not.

#### SA-10. WRT-002 is design-only, and nothing here has passed an independent gate

WRT-002 is design-only. It carries open findings from three reviewer families
plus one confirmed here on 2026-07-29 — a quorum authorised only by a losing
policy branch could adopt a root; fixed, with the negative control run.

More broadly, and this bounds every claim in this document: **no independent gate
is currently available.** The reviewing families are unaffordable or restricted,
so items land UNGATED under a recorded attestation naming who took
responsibility. `policies/gate-settlement.json` defines that state. It is
disclosed rather than dressed up as a passed gate, and it is the reason
"validated" appears nowhere in this file without saying by what.

### Explicit non-goals

Properties Warrant deliberately does not provide. From SPEC §10 and
`SECURITY.md`, gathered so nobody has to rediscover them, each with the reason it
is out of scope rather than merely absent:

- **NG-1. Confidentiality.** Nothing is encrypted. Everything in a body — including
  `subject.note` and prose reasons — is intended to be readable by anyone holding
  it. Do not put a secret in a warrant.
- **NG-2. Availability / completeness of a store.** There is no consensus, no ordering
  across actors, no anti-censorship property. A store is a directory.
- **NG-3. Blob transport.** Out of scope precisely because content addressing makes it
  irrelevant to integrity.
- **NG-4. Whether a decision was correct.** Warrant records decisions; it does not take
  them, and it has no opinion about how agents make them.
- **NG-5. Resource exhaustion on a store you already control.** An attacker in
  that position already has A1; nothing is defended by also defending this.
- **NG-6. A finding that requires store write access to then claim the store is
  untrustworthy** — unless the point is that a *reader* cannot tell. That
  exception is the interesting half and is in scope.

## Severity, and how to report

`SECURITY.md` is the process; its ladder in one line: **P0** two conforming
verifiers disagree, or something forged reads as verified; **P1** the spec is
silent where an implementer must guess; **P2** clarity; **P3** roadmap.

A finding is a reproduction. A script that exits non-zero on the defect and zero
once fixed becomes a permanent regression test — and every fix in this
repository's history carries a **negative control**: the fix is removed and the
attack is shown to come back.

Two of the entries above (`A7`/SA-1 and `A2`/SA-2) are scoped assumptions, not
defects. A report showing one is **worse than stated** is in scope; one restating
it is not.
