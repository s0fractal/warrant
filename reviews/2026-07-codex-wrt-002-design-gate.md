# Codex design gate — WRT-002

Date: 2026-07-27
Candidate: `fe655d06566b2a02939924efb93ad8d56bf5825b`
Scope: design only; no implementation or adoption review
Verdict: **AMEND**

## Summary

The proposal chooses the right boundary: key-state, authorized lifecycle, and an
R1 checkpoint are one Warrant-level problem, not three independent Wave
features. Its audit of the shipped implementation is useful and correctly
withdraws the naïve `active minus every supersede target` censorship primitive.

The draft does not yet define a closed replay machine, however. In particular,
the proposed checkpoint commits an output but not the complete historical input
from which that output is derived. Current Warrant envelopes also permit
co-signatures to change threshold authorization without changing any WarrantID.
Together these make the claimed growth immunity false even before the remaining
wire-format questions.

## Findings

### P1 — The checkpoint has no immutable input cut, and its stated set is self-referential

Section 4 commits `effective_set_root` and a key-state pin "at an epoch", then
asks a verifier to recompute `authorized_effective_active_for(J, checkpoint)`.
None of the committed fields identifies the closed record universe from which
that function is evaluated:

- Warrant has no global epoch or trusted timestamp cut;
- the current store head is mutable;
- an output root does not reveal the input membership needed to recompute it;
- no frontier, prior-closure rule, manifest, or eligible-set commitment is
  specified.

A verifier using live store membership loses growth immunity. A verifier using
only records selected by the filer cannot distinguish a legitimate historical
cut from omission of a rival that already existed. Threshold authorization can
authorize a cut, but the exact cut still has to be committed and replayable.

There is also a direct identity cycle: the text defines the root over
`authorized_effective_active_for(J, self)`. If the checkpoint is itself an
active record in that jurisdiction, its WarrantID is a member of a root stored
inside the body that determines that same WarrantID.

Specify one immutable pre-checkpoint universe, for example a sorted frontier
whose strict prior closure is the cut, with the checkpoint itself excluded by
construction. Commit that frontier or a resolvable manifest and define exactly
how completeness is authorized. Add vectors for an omitted already-present
rival, post-checkpoint growth, an untrusted `ts`/epoch backfill, and checkpoint
self-inclusion.

### P1 — WarrantID set roots do not freeze the authorization evidence

WarrantID hashes only the body. Per SPEC §5, envelope co-signatures may be
appended without changing the WarrantID. Threshold satisfaction is evaluated
from those mutable envelope signatures.

Countervector:

1. At checkpoint time, supersede `S` has one signature under a 2-of-3 policy, so
   `S` is not authorized and target `X` is included.
2. The checkpoint commits the same WarrantID set and key-state root proposed by
   WRT-002.
3. Afterward, a second valid co-signature is appended to `S`'s envelope. No
   WarrantID, policy blob, or checkpoint field changes.
4. Replay now treats `S` as authorized and evicts `X`; the checkpoint goes
   `unverified`.

The same seam affects rotation authorization and therefore the key-state pin.
This is ordinary allowed Warrant growth, not hash tampering.

The historical cut must commit the exact authorization witnesses used by the
derivation, or authorization must be represented by separate content-addressed
records. Later envelope signatures must not be silently imported into an older
checkpoint replay. Add exact-before/exact-after co-signature vectors.

### P1 — "The policy that admitted X" and the causal position of supersession are undefined

The shipped verifier does not threshold-admit ordinary active records.
`active_records` requires root reachability, well-signedness, and a valid policy
shape; `_policies_satisfied` is used for root adoption and rotations, not every
ordinary `X`. Consequently there is no existing singular "jurisdiction policy
that governs/admitted X" to reuse.

The draft alternates between `X.under` and "the root policy", but:

- `X.under` may contain zero, one, or several v0.3 threshold policies;
- no rule selects one, combines all, or binds a root to one lifecycle policy;
- the same record may reach more than one adopted root, so authorization can be
  jurisdiction-relative.

The supersede also need not currently cite its target in `prior`. Without a
causal requirement, an old-key fork can file `S` against a later same-actor
record `X`; `keys_before(S)` sees the old branch and can call that key current
even though `S` is not causally after `X`.

Define the exact lifecycle-policy resolution rule and require the target to be
in the superseder's committed causal past (or specify an equivalent immutable
position rule). State whether self-authorization bypasses, supplements, or must
also satisfy lifecycle policy. Add multi-policy, multi-root, and unordered
target countervectors.

### P1 — The key-state/lifecycle "fixpoint" is non-monotone and not specified as an algorithm

WRT-002 correctly says that conflict resolution must be activated, but "wire it
into the derivation fixpoint" is not enough for two implementations to agree.
The new dependency graph contains negative edges:

- SPEC §5.1 defines revocation as a supersede of a rotation;
- whether that rotation contributes a key depends on effective lifecycle;
- whether the supersede is authorized depends on that key-state;
- conflict reduction depends on which rotations were authorized.

A minimal self-invalidating vector is a rotation `R: K0 -> K1`, followed by a
same-actor supersede `S` of `R` signed by `K1`. If current-state authorization is
re-evaluated after effects, `R` enables `S`, `S` removes `R`, removal of `R`
removes the authority for `S`, and the state oscillates. A causal transition
machine can make this deterministic by authorizing `S` against its immutable
pre-state and never retroactively withdrawing that authorization, but the draft
does not choose that rule.

Conflict resolution is likewise missing:

- the exact resolving record type;
- whether it must descend from every maximal conflicting warrant;
- the exact pre-state and policy used for its authorization;
- how simultaneous conflicts among several policy actors are reduced;
- the terminal result when no unconflicted remainder exists.

The `supersede-of-supersede` prose also needs a formal recurrence and an
acyclicity/causal rule; "fixed point" alone does not select a result for a
non-monotone relation.

Specify a stratified, DAG-positioned transition algorithm, including conflict
markers in state and explicit terminal conflict outcomes. Pin it with the
rotation/revocation self-invalidation vector and multi-actor conflict vectors.

There is also an internal semantic contradiction to remove: §2 says a new key
is bound only when the rotation is signed by a key already authoritative for
that actor. Shipped SPEC §5.1 and `rotation_authorized` deliberately allow
threshold-authorized emergency replacement without the outgoing actor key;
only incoming proof-of-possession plus the governing quorum is required.

### P1 — `checkpoint@v1` and both commitments have no byte-level contract

Current SPEC explicitly says v0.3 adds no body schema; validators accept only
body versions 0.1/0.2 and the existing closed body fields. The proposal calls
the checkpoint a settlement record with candidate tag `checkpoint@v1`, but
does not choose whether that tag is:

- a new body version/decision;
- a governed runtime reason;
- a canonical subject blob carried by an existing Warrant body; or
- another object type.

Nor does it define:

- a closed checkpoint schema and canonical bytes;
- domain-separated bytes for `effective_set_root`;
- the canonical representation of key-state (including conflicts), despite
  saying "the committed key-state (or its root)";
- the governing-policy resolution bytes;
- epoch/sequence semantics and competing-checkpoint handling;
- exact validation severity and total failure behavior.

Until these are fixed, Python and Go cannot compute the same checkpoint
WarrantID or roots, and WRT-001 cannot safely bind one. Choose the versioning
vehicle and specify tagged closed objects and hashing inputs before an
implementation task.

### P2 — Correct three grounding statements

- Pinned `genesis.json` establishes roots only. Actor key seeds come from the
  validated trust config's `actors` map.
- The key map is not monotone: rotation replaces a key set. History may grow
  monotonically; the derived state changes.
- Current `conflict_actors` is live/global after the active-set fixpoint, whereas
  R1 needs conflict state derived at the committed historical cut. The draft
  should not imply the current helper already provides that as-of semantics.

## Required countervectors before the next design gate

In addition to §5:

1. checkpoint omits a rival already inside the authorized cut;
2. record with old `ts` is appended after the checkpoint;
3. checkpoint self-inclusion is impossible by construction;
4. threshold co-signature appended after checkpoint does not change replay;
5. unordered/stale-key supersede of a later target is ineffective;
6. target with zero/multiple policies and target shared by two jurisdictions;
7. rotation enables its own revocation (no oscillation);
8. resolver descends from only one of two conflicting maxima;
9. two policy actors are simultaneously conflicted;
10. competing checkpoints at one sequence/epoch.

## Gate

No implementation should start from this revision. The next revision should
first close the immutable-input/auth-witness model and provide a total
DAG-positioned derivation. Once those are fixed, the wire object can be frozen
and then attacked independently before Python/Go work.
