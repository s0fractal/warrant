# Codex design re-gate — WRT-002 rev 3

Date: 2026-07-27
Candidate: `6d4acbac6dd0e2921821988c8435b59c9aad3251`
Scope: model §§2–5.5, before wire-byte freeze
Verdict: **AMEND**

## What now holds

Rev 3 closes the four rev-2 findings at their original seams:

- replay no longer needs live envelope signatures for ordinary eligibility;
- the merge carrier is immutable event provenance and merge is ACI set union;
- jurisdiction policy is no longer inferred from `X.under` or adoption records;
- checkpoint authorization and replay use one frontier, and checkpoint cuts form
  an extending causal chain.

The model is much closer to a closed machine. Composition among the newly
introduced event roles exposes four remaining P1s.

## Findings

### P1 — Manifest completeness has two contradictory failure semantics

Section 3 says:

- every cut record whose eligibility is read must have an `actor-filing` entry;
- a cut record with no manifest witness is treated as **not eligible**;
- omission of an already-valid filing witness is attributable to the quorum.

Section 6 instead says any **missing witness** makes the entire checkpoint
`unverified`.

These are different state machines. The distinction matters for a schema-valid
record inside the cut that had no valid filing signature at checkpoint time:
there is no positive `actor-filing` witness to include. If every record requires
one, such a cut can never checkpoint. If omission means "ineligible", omission
of an actually valid filing signature becomes a quorum-authorized eligibility
decision rather than a mechanically complete manifest.

Make the manifest total over `cut(F)` with an explicit per-record eligibility
claim, for example:

- `eligible` plus the exact `actor-filing` witness; or
- `ineligible` plus a closed reason class (`schema-invalid`,
  `no-filing-witness`, etc.).

The quorum authorizes negative historical claims because signature absence
cannot be proved from a mutable envelope. Missing, duplicate, or out-of-cut
record entries should then unambiguously invalidate the checkpoint. Later live
signatures remain ignored.

Add three separate vectors: explicit historical ineligibility, omitted manifest
entry, and omitted valid filing witness. They must not collapse to one outcome.

### P1 — Generic SELF supersession can roll back quorum-governed transitions

Section 5 applies the same SELF rule to any target `X`: a currently-authoritative
key for `X.actor.id` is sufficient to supersede it. That is safe for an ordinary
actor-owned decision, but not for records whose effect was authorized by a
quorum.

Countervector:

1. Under policy `P0` (2-of-3), actor A files a `policy-succession` to `P1` with
   valid A+B threshold witnesses.
2. A later files a supersede of that succession record, causally descending it
   and signed only by A.
3. The generic SELF path authorizes the supersede because the target record's
   `body.actor.id` is A.
4. If effectiveness controls event application, A has unilaterally rolled
   policy-state back from a quorum decision.

The same role-confusion applies to:

- revocation of a threshold-authorized rotation, which SPEC §5.1 requires to
  follow the same current-policy rule;
- root-adoption records;
- conflict-resolution records;
- checkpoint records.

If "once authorized, never withdrawn" instead keeps those events active despite
their record being superseded, then generic supersession no longer implements
rotation revocation or policy rollback at all. The draft must choose per target
role, not inherit ordinary SELF lifecycle.

Define an authorization matrix:

- ordinary actor-owned record: SELF or jurisdiction policy;
- rotation/revocation: the SPEC current-policy rule;
- policy succession/resolution: the appropriate policy quorum;
- root adoption: adopting-jurisdiction authority;
- checkpoint: checkpoint succession/conflict rules, not ordinary SELF.

Add a one-filer rollback vector for every quorum-governed target role.

### P1 — The event algebra omits root adoption and the boundness rule for filing witnesses

`Events` contains rotation, revocation, policy succession, and conflict
resolution. Yet `active_cut` depends on jurisdiction-scoped active roots, and
the manifest explicitly freezes root-adoption thresholds. Root adoption is not
present in the event carrier or in the "one derivation from an event set", so
ACI merge does not currently derive which roots/records are active for `J`.

This is especially visible when the cut joins:

- an adoption warrant in the adopting root's branch; and
- the separately rooted branch being adopted.

The adoption points to the new root through `subject.hash`, not through that
root's `prior` ancestry. A pure union of the listed event kinds has no rule that
activates the second branch for `J`.

Add `root-adoption` as a typed authorized event, define its causal/reference
requirements, and derive `active_roots(J,E)` before `active_cut`. State whether
adoption is reversible and, if so, only through the target-role authorization
matrix above.

The `actor-filing` role also needs one explicit semantic choice. SPEC §9 calls a
root well-signed only when its filing signature is valid and bound where
key-state is configured, while shipped `_well_signed` currently checks
cryptographic actor signature but not key binding. WRT-002 must say whether an
R1 filing witness must be authoritative in `derived(preEvents(record))`.
Otherwise implementations following SPEC and the current helper can derive
different effective sets from the same manifest.

Add adopted-root merge and bound-vs-unbound filing vectors.

### P1 — Conflict resolution is defined only for keys, not policy or checkpoint state

The concrete §4 resolver is a rotation accept naming an incoming actor key. That
correctly resolves a **key** conflict. Section 5.5 then says policy conflict is
resolved by the "§4 resolver shape", but a key rotation cannot select a governing
policy, and concurrent policy successors may define different actor sets and
thresholds.

For policy forks, specify:

- the concrete policy-resolution transition and subject;
- which non-conflicted policy authorizes it (for example, the greatest common
  causal predecessor policy);
- what happens when the competing policies have no single authorized common
  predecessor inside the cut;
- how its witnesses and conflict marker enter provenance.

Checkpoint succession has the analogous unresolved branch. Section 6 requires
`n+1` to descend "the previous accepted checkpoint", singular, while the prior
sentence permits multiple competing accepted checkpoints at sequence `n`.
After such a conflict there is no singular predecessor. Define whether a
resolver checkpoint must descend every maximal competitor and extend the union
of their cuts, or whether the chain is terminal. Its authorization also requires
a non-conflicted policy-state; checkpoint conflict cannot silently choose one.

Add policy-fork resolution and `C_n^A/C_n^B -> C_{n+1}` vectors, including the
case where policy-state and checkpoint-state are conflicted simultaneously.

## P2 — Clarify two state boundaries

- Say explicitly whether an authorized event contributes to derived state only
  while its record is effective. The current prose simultaneously says
  authorization is never withdrawn and defines revocation through
  supersession. Event authorization may be permanent while event **effect** is
  lifecycle-dependent, but those must be separate fields/functions.
- `body.prior == frontier` is a good binding. For adopted-root cuts, note that a
  multi-root frontier makes the checkpoint record reachable from multiple
  roots under shipped `record_roots`; special checkpoint semantics must remain
  scoped only to the `jurisdiction` named in its subject.

## Required closure before byte freeze

1. make witness coverage a total per-cut-record manifest with explicit negative
   eligibility;
2. replace generic lifecycle authorization with a target-role matrix;
3. include root adoption and filing-key boundness in the event derivation;
4. define distinct key, policy, and checkpoint conflict-resolution
   transitions.

The ACI carrier itself is sound; the remaining work is to close the event
vocabulary and role semantics that ride on it.
