# Codex design re-gate — WRT-002 rev 2

Date: 2026-07-27
Candidate: `92bc4111c33f0cc9ad770e349caa5fabe4a2df46`
Scope: §§2–5 model, before wire-byte freeze
Verdict: **AMEND**

## What rev 2 closes

Rev 2 materially improves the model:

- a causal cut replaces the undefined global epoch;
- the checkpoint is excluded from its own committed set;
- supersession must causally descend its target;
- authorization is evaluated against immutable pre-state rather than
  retroactively withdrawn;
- emergency rotation without the outgoing key is preserved;
- `X.under` is correctly rejected as an implicit lifecycle authority.

Those are real closures. Four model seams remain before byte freeze.

## Findings

### P1 — The witness manifest still leaves ordinary eligibility mutable

Section 3 freezes signatures only for "authorized state transitions": root
adoptions, rotations, and effective supersedes. Section 4 nevertheless defines
`active_cut(X)` using the shipped `active_records` predicate, whose
well-signedness gate depends on the mutable envelope signature of **every**
ordinary record.

Countervector:

1. Ordinary record `X` is inside `cut(F)` but has no valid actor signature when
   the checkpoint is made, so `X` is not in `active_cut`.
2. `X` has no witness entry because it is not a state transition.
3. After checkpointing, append a valid `body.actor.id` signature to `X`'s
   envelope. This is permitted by SPEC §5 and does not change `X`'s WarrantID.
4. Live well-signedness now admits `X`; replay changes
   `effective_set_root` without changing the frontier, WIDs, or witness root.

The same applies to the well-signedness of roots and other non-transition
records. If replay instead treats an omitted witness as absence, manifest
completeness must be part of the authorized model; otherwise a checkpoint can
omit an already-valid ordinary actor signature and censor that record.

Freeze every signature-dependent predicate used by replay, not only transition
thresholds. A straightforward model is one manifest entry per record whose
eligibility or transition authorization is used, with typed witness roles:
`actor-filing`, `incoming-pop`, and `threshold`. Replay must never consult a
live envelope for a record inside the historical cut.

The manifest must also be a resolvable committed input. A bare `witness_root`
does not provide its preimage; specify that the canonical manifest is embedded
or content-addressed by a blob reference available to replay.

Add vectors for an ordinary actor signature and a root actor signature appended
after checkpoint, plus an omitted already-valid filing witness.

### P1 — `merge(AS(parent...))` is not a total merge algorithm

Rev 2 moves authorization to causal pre-state, but its load-bearing operation is
still only named:

```
preAS(w) = merge(AS(p) for p in w.prior)
```

No merge law says how collapsed key maps, conflict markers, revocations, and
effective markers combine. The result cannot be obtained by an ordinary map
merge:

- one branch rotates `K0→K1`, while another retains `K0`;
- two branches rotate the same actor to different keys;
- one branch contains a supersede and another does not;
- one branch revokes a rotation and a later join reinstates it through a
  supersede-of-supersede.

These require causal provenance, not just the state values at each parent.
Python and Go can legitimately implement different merge rules while satisfying
the current prose.

Define authority state as a set of immutable, already-authorized transition
events plus their causal relation. Make merge an explicit
associative/commutative/idempotent union of event provenance, followed by one
specified derivation of maximal rotations, conflict markers, and effective
status. Then define forward authorization and reverse lifecycle evaluation as
separate ordered passes.

Conflict resolution is also not yet a record-level transition: `Q` is called an
"authorized record", but the proposal does not say whether it is a rotation
accept, which actor/key it resolves to, whether incoming proof-of-possession is
required, or what exact state update clears the marker. Choose the transition
shape and require it to descend every conflicting maximum.

Add merge-permutation vectors (same DAG, every parent/list/iteration order) and
assert byte-identical state, not just the same final error count.

### P1 — The jurisdiction governing policy still has no derivation

Section 5 says the lifecycle/checkpoint policy is "the same threshold that
governs root-adoption / makes J settlement-active", resolved to one policy per
jurisdiction. Shipped settlement has no such persistent singular policy:

- a genesis-pinned root is active without any threshold policy;
- an adoption warrant supplies policies through its own `under`;
- one root may have multiple adoption paths with different policies;
- current trust config binds actors and roots, not a policy per jurisdiction.

The fallback "only SELF supersession" handles lifecycle ambiguity, but it makes
R1 impossible for a pinned genesis jurisdiction: §6 simultaneously requires
every checkpoint to be threshold-authorized by the missing governing policy.
For multiply-adopted roots, "resolved to a single policy" remains an assertion,
not a resolution function.

WRT-002 therefore needs an explicit policy-state primitive: an initial
jurisdiction-policy anchor and a causal, threshold-authorized succession rule,
or a deliberately narrower rule that the checkpoint names exactly one policy
whose authority is independently pinned for `J`. Define how genesis gets its
first policy, how adoption affects it, how policy rotation/conflict works, and
whether this policy state is inside the checkpoint cut/witness model.

Add pinned-genesis-without-policy, two-valid-adoption-policies, policy succession,
and policy-fork vectors.

### P1 — The checkpoint record is not causally bound to its advertised frontier

Section 2 says the checkpoint is filed after and "cites `F`", but the chosen
vehicle in §6 only places `frontier` inside the subject blob. It does not require
the enclosing checkpoint Warrant's `body.prior` to equal (or cover) `F`.

This permits two different causal positions in one checkpoint:

- replay and `key_state_root` are derived from the blob's frontier `F`;
- checkpoint signature authorization under shipped `keys_before(checkpoint)`
  is derived from the enclosing body's actual `prior`.

A checkpoint can therefore advertise cut `F₁` while being threshold-authorized
against unrelated pre-state `F₂`. Self-exclusion alone does not close this.

Require `checkpoint.body.prior == frontier` (after the same sorted/dedup
validation), or define one exact equivalent binding, and use that single cut for
both checkpoint authorization and replay.

Checkpoint succession is likewise only named a "monotone counter". Require a
sequence successor to causally descend the previous accepted checkpoint and its
cut to extend the previous cut; otherwise sequence `n+1` can roll history back
to an unrelated frontier. Define genesis sequence, gaps, forks, and conflict
scope before freezing bytes.

Add advertised-frontier/body-prior mismatch and higher-sequence rollback
vectors.

## P2 clarifications

- `cut(F)` is called a **strict** prior closure while its formula explicitly
  includes every `w ∈ F`. Call it inclusive closure of the frontier (and strict
  only relative to the later checkpoint) to avoid two conforming readings.
- Antichain plus threshold signature does not mechanically prove global
  completeness; it makes frontier completeness a quorum-authorized claim.
  Say that directly. It prevents unilateral filer omission, not omission by the
  governing quorum.
- The well-founded lifecycle recurrence should state its evaluation direction:
  authorization is forward in causal order; effectiveness is evaluated from
  causally later superseders back toward their targets.

## Required next closure

Before rev 3 byte freeze:

1. broaden the frozen witness domain to every signature-dependent replay input;
2. define a resolvable manifest;
3. specify an ACI provenance merge and a concrete conflict-resolution
   transition;
4. introduce or pin jurisdiction policy-state;
5. bind checkpoint `prior`, frontier, and sequence into one causal chain.

No implementation should start until these model choices survive another
design re-gate.
