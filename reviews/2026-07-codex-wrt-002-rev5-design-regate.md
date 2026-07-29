# WRT-002 rev 5 — independent model re-gate

**Reviewed:** `b8cec01` on `feat/wrt-002-keystate-r1`
**Scope:** model only, especially §§2–6; no wire-byte review, implementation
review, adoption, or governance claim
**Verdict:** **AMEND**

Rev 5 closes the literal rev-4 countervectors: lifecycle supersedes are now
typed, reversal consults causally current governance, mutual untrusted adoption
is rejected by intent, and emergency rotation separates filer from target.
The immutable cut, total per-cut manifest, ACI provenance carrier,
authorization/effect split, and distinct resolver shapes still survive.

Byte-freeze is nevertheless premature. Composition of those individually sound
pieces exposes four model-level seams.

## Findings

### P1 — The checkpoint's own authorization is outside the frozen witness domain

Section 2 deliberately excludes checkpoint `C` from `cut(C.frontier)`. Section 3
makes the witness manifest total **only over that cut**. Section 6 nevertheless
authorizes `C` using signatures on the enclosing `accept`.

Those envelope signatures are appendable without changing the WarrantID. The
document already identifies this mutability for every cut record, but the same
problem remains at the outermost checkpoint:

1. Construct `C` with one valid signature where its frontier policy requires
   two.
2. `C` is initially unverified.
3. Append the second signature to `C`'s envelope after later store growth.
4. The same checkpoint WID, subject, frontier, witness root, and four committed
   state roots now become verified.

A late co-signature can therefore retroactively authorize a checkpoint or turn
an old same-sequence checkpoint into a new competitor. Growth immunity and
historical replay do not hold at the object that vouches for the frozen history.

The §3 list mentioning a checkpoint `threshold` witness does not close this:
there is no manifest entry for `C`, because `C ∉ cut(F)`. Putting `C`'s own
signatures inside `witness_root` is also not a direct fix: `witness_root` affects
the subject hash, which affects `C`'s body/WID, which is what those signatures
sign. That is a self-reference cycle.

**Required model closure:** choose a non-self-referential authorization vehicle,
for example a causally prior/resolvable authorization certificate followed by a
checkpoint that commits it, or an explicit two-stage proposal/authorization
construction. Specify which frozen bytes prove checkpoint authorization and
make late envelope growth semantically invisible.

**Required vectors:**

- below-threshold checkpoint + late co-signature → unchanged replay result;
- late signatures cannot create a same-sequence competitor;
- frozen checkpoint authorization survives unrelated envelope growth;
- the authorization witness is causally and cryptographically bound without a
  WID/signature cycle.

### P1 — `active_roots` asks for a least fixed point of a non-monotone operator

The proposed stratification is circular:

1. `active_roots` includes targets of **effective** adoptions;
2. `effective(adoption)` depends on effective supersedes;
3. a supersede is effective only when its record passes `active_cut`;
4. `active_cut` depends on `active_roots`.

Because lifecycle reversal can remove an adoption, the root operator is not
monotone. A concrete two-cycle exists:

1. `A` is the only pinned root.
2. Effective adoption `D`, filed on `A`, adopts root `B`.
3. Authorized supersede `S`, filed on `B`, targets `D`.
4. At roots `{A}`, `S` is inactive, so `D` is effective and the next root set is
   `{A,B}`.
5. At roots `{A,B}`, `S` becomes active/effective, so `D` is ineffective and
   the next root set is `{A}`.

There is no fixed point, least or otherwise. The sentence “an event on a
not-yet-active root never contributes” does not solve this; it creates the
oscillation when that same event becomes active because of the adoption it
revokes.

**Required model closure:** make the operator monotone or replace it with an
explicit well-founded causal derivation. One possible constraint is that a
reversal of an adoption must itself be rooted in authority active independently
of the adoption being reversed. Whatever rule is chosen must specify the exact
causal stratum used for both adoption and reversal.

**Required vectors:**

- pinned `A` adopts `B`; `B` files the reversal of that adoption;
- the same reversal filed on independently active `A`;
- nested `A→B→C` adoption with reversals filed on each of the three roots;
- every permutation terminates with one byte-identical result.

### P1 — Policy-conflict resolution does not resolve effects produced by the losing branch

“Current policy at `preEvents(S)`” is causally well-defined on a single branch,
but permanent authorization preserves branch-local acts after that policy loses
a later conflict resolution:

1. `P0` concurrently authorizes policy successions `P1` and `P2`.
2. A lifecycle event `S1` descends only `P1` and is authorized by `P1` (for
   example it reverses a root adoption).
3. The branches merge and produce a policy-conflict marker.
4. A valid resolver descends both branches and selects `P2`.
5. `authorized(S1)` remains permanently true; absent another supersede, `S1`
   remains effective even though its authorizing policy branch lost.

The current text deterministically selects the policy for future operations but
does not say whether it also selects, rejects, or reconciles policy-dependent
effects created on competing branches. Thus a losing policy can leave permanent
lifecycle changes in the checkpoint state selected by the winner.

This may be an intentional causal-authority rule, but it must be an explicit
security decision rather than an accidental consequence of “authorization is
permanent.” If losing-branch effects survive, the resolver's meaning and threat
model must say so. If they do not, effectiveness needs policy-lineage gating or
the resolver must commit an attributable reconciliation of branch effects.

**Required vectors:**

- `P1/P2` fork, `P1` reverses an adoption, resolver selects `P2`;
- symmetric vector with the resolver selecting `P1`;
- both branches supersede the same target differently;
- resolver and parent-order permutations produce the same effective root,
  key, and lifecycle state.

### P1 — “Authorization class” is a tag, not yet a total authority algebra

Rev 5 names five classes and requires “authority no weaker than” the class on
the target lifecycle edge. It does not define:

- the principal and scope carried by a class (which actor, jurisdiction, or
  governed target);
- the policy-state reference used by a parameterized class;
- a preorder or an explicit allowed-reversal matrix between the five classes;
- how two authorities of the same tag but different principals compare.

This is observable, not merely a future byte-layout issue. For example, an
emergency rotation for actor `A` may be filed by quorum actor `Q`. A revocation
of that rotation carries `rotation-policy`. When another lifecycle supersede
targets that revocation, “rotation-policy” alone does not say whether to consult
`A`'s key policy, `Q`'s key policy, or jurisdiction `J`'s policy. Conforming
implementations can choose different authorities while agreeing on every class
tag.

Likewise, SELF is not globally comparable: SELF-of-`A` is not SELF-of-`B`.
“Quorum” is not a scalar strength either; two quorums can have different
principals and scopes.

**Required model closure:** replace the bare class with a parameterized
authorization capability/provenance value, for example `(kind, principal,
jurisdiction, governed-target, policy-state-ref)`, and define a total
`may_reverse(new_capability, prior_capability, prestate)` relation. The wire
encoding can remain deferred, but the model relation cannot.

**Required vectors:**

- cross-actor emergency rotation: target actor differs from filer;
- SELF-of-`A` attempting to reverse SELF-of-`B`;
- two jurisdictions with structurally identical quorum policies;
- policy succession between two same-tag quorum capabilities;
- every `target-role × carried-capability × new-capability` case has exactly one
  result.

## What survives this gate

- The checkpoint cut is immutable and self-excluding.
- The per-cut witness manifest is total and has non-collapsing negative claims.
- ACI union remains a sound provenance carrier.
- Authorization and effectiveness are correctly distinct concepts.
- Root, key-policy, policy, and checkpoint conflicts require different resolver
  shapes.
- The rev-4 SELF-versus-quorum laundering example is closed at the intended
  category level.
- Emergency rotation no longer accidentally requires the target's outgoing key.

## Gate to byte-freeze

Before freezing bytes, rev 6 should:

1. close checkpoint authorization without self-reference or mutable-envelope
   replay;
2. replace the non-monotone root “least fixed point” with a terminating,
   deterministic derivation;
3. decide and specify the fate of losing-policy-branch effects;
4. define parameterized authority capabilities and their reversal relation.

Then the wire-object review can attack canonical schemas, domain separation,
root encodings, manifest linkage, and validation severity independently.

No code, signature, runtime registration, adoption, merge, push, or governance
action was performed by this review.
