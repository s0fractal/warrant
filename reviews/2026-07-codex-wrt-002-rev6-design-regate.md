# WRT-002 rev 6 — executable-readiness model re-gate

**Reviewed:** `dfde613` on `feat/wrt-002-keystate-r1`
**Scope:** whether §§2–6 define one machine precisely enough to encode as a
hermetic executable reference model; no wire-byte, implementation, adoption, or
governance review
**Verdict:** **AMEND — not yet executable-model ready**

Rev 6 correctly recognizes the four rev-5 seams and moves in the right
directions: immutable authorization witnesses rather than self-signing state,
causal strata rather than a naïve root fixed point, lineage-aware effect, and
parameterized capabilities rather than scalar authority. The previous cut,
manifest, ACI carrier, authorization/effect distinction, and resolver topology
still survive.

The new definitions do not yet compose into one executable machine. Encoding
them now would force the implementer to invent semantics at four points and
would turn those choices into accidental specification.

## Findings

### P1 — The two-stage checkpoint has no finite immutable authorization closure

The proposed authorization records are ordinary Warrants. Their WIDs hash their
bodies, not their envelopes. Therefore this rev-6 claim is false:

> A late-appended signature or a new authorization record is a new WID.

A new authorization **record** has a new WID, but an actor-filing or
co-signature appended to an already-pinned authorization record does not.
Consider:

1. Authorization-record body `A` names proposal digest `P` and has WID `a`.
2. A binding wave citation pins `a`, but `A` initially lacks a valid
   `body.actor.id` signature.
3. That actor signature is appended later to `A`'s envelope.
4. The pinned set of WIDs is unchanged, while `A` flips from ineligible to
   eligible.

Pinning authorization-record WIDs is therefore insufficient; the binder must
freeze the exact signature witness bytes. Rev 6 says §3 does this, but §3 is a
manifest over a checkpoint cut. A wave citation has no such manifest in
WRT-001, and the next checkpoint can freeze only its predecessor, leaving the
current tip dependent on another future binder.

This also introduces identity and dependency conflicts:

- WRT-001 §6 requires the stored check to carry an authorized **checkpoint
  WarrantID**; rev 6's checkpoint identity is a proposal **blob digest**.
- The text still requires `checkpoint.body.prior == frontier` and replay to
  “resolve the accept”, although the checkpoint is now a blob with no body.
- If a wave citation is what freezes checkpoint authorization, the citation's
  settlement validity depends on the checkpoint whose authorization depends on
  that citation: a trust cycle.
- If checkpoint `n+1` is the binder, checkpoint `n+1` remains mutable until
  `n+2`; the latest checkpoint never has self-contained immutable
  authorization.
- Different binders may pin different authorization-record sets for the same
  proposal digest, so “the checkpoint is authorized” is context-dependent.

**Required closure:** make each authorization witness itself an immutable
content-addressed object whose hash covers actor, key, policy context, and a
signature over the stable proposal digest. Then define one finite checkpoint
certificate identity, such as `(proposal_digest, authorization_set_root)`, that
is independently verifiable without a wave citation or future successor.
Synchronize that identity and vehicle with WRT-001 before byte-freeze.

**Required vectors:**

- pinned authorization-record WID + late actor signature → no verdict change;
- current chain tip verifies without a future checkpoint or consumer citation;
- the same proposal with two authorization sets has unambiguous identities;
- no `checkpoint ↔ wave-citation` dependency cycle;
- WRT-001 names the exact same object type and identity as WRT-002.

### P1 — Basis-gating is neither sufficient for losing branches nor well-founded for revocation

Rev 6 defines:

```text
effective(S) requires every transition in auth_basis(S) to be effective
```

This has two independent failures.

First, a policy-conflict resolver does not lifecycle-supersede the losing
policy-succession record. Under the generic definition, both competing
succession records remain active, authorized, and not targeted by an effective
supersede. The resolver changes the selected `policy-state`, but the text never
makes the losing transition's **record** ineffective. Consequently an event
whose basis names that losing transition still passes condition (c). The stated
losing-branch fix does not follow from the rules.

The same issue applies to a losing key-rotation branch after key-conflict
resolution: “not selected into derived key-state” and “record is ineffective”
are different predicates.

Second, if “effective basis” is strengthened to mean the selected transition,
the canonical revocation vector has no Boolean solution:

1. Rotation `R: K0→K1` supplies the key that authorizes revocation `S`.
2. `S` supersedes `R`.
3. Lifecycle gives `effective(R) = not effective(S)`.
4. Basis-gating gives `effective(S) = effective(R)`.

Thus `R = ¬S` and `S = R`: neither assignment satisfies both. Authorization
being permanent does not fix an effect-level negation cycle.

**Required closure:** distinguish at least:

- immutable causal authorization evidence (“this capability was valid when
  exercised”);
- membership in the resolver-selected state lineage;
- lifecycle effectiveness of the record being acted on.

Specify which predicate gates which downstream effects. A revocation must be
able to consume a historically valid capability without requiring the revoked
transition to remain currently effective, while a losing concurrent branch
must not continue to govern after resolution. This likely needs an explicit
selected-lineage relation produced by each resolver, not blanket
`effective(basis)`.

**Required vectors:**

- `R:K0→K1`, then `K1`-authorized revocation of `R`;
- `P1/P2` conflict, resolver selects `P2`, action authorized only by `P1`;
- key-rotation conflict, resolver selects one key, action signed on the losing
  branch;
- an action whose basis is later lifecycle-superseded but was not part of a
  conflict;
- all vectors terminate with one result, not a chosen fixed-point convention.

### P1 — Genesis-distance does not agree with global `effective(record)`

The lesser-distance rule says a root cannot participate in its own activation
or deactivation. The global recurrence still says an adoption record `D` is
effective iff no effective supersede targets it.

Use the rev-5 oscillation vector:

1. Pinned root `A` carries adoption `D: adopt(B)`.
2. Root `B` carries supersede `S: supersede(D)`.
3. Lesser-distance derivation activates `B` using `D` while ignoring `S` for
   `B`'s activation decision.
4. Once `B` is active, global `active_cut(S)` holds. If `S` is effective, global
   `effective(D)` is false.
5. But the rule defining active `B` requires an **effective** `D`.

So rev 6 simultaneously needs `D` effective to activate `B` and ineffective
after `B` activates. If `D` is included in `S`'s root authorization basis,
blanket basis-gating reproduces the same `D = ¬S`, `S = D` contradiction. If
`S` is simply ignored at this stratum, the model has two meanings of
“effective adoption” without naming them.

“Authority lineage reaches genesis without passing through B” does not by
itself solve this. A supersede record may be filed on `B` while using a
jurisdiction-policy capability independently rooted at `A`; its authority
lineage and its record reachability are different dependencies.

Genesis-distance is also not defined when a root has multiple adoption paths:
minimum distance, all-path distance, and path-specific activation produce
different reversal eligibility.

**Required closure:** define a separate, path-aware root-admission derivation
whose inputs and reversal rules are explicit, then define how its result feeds
ordinary lifecycle effectiveness. Do not use the same unqualified
`effective(D)` on both sides of the stratum boundary. Define distance under
multiple paths and whether an independently anchored capability can exercise a
record filed on the adopted root.

**Required vectors:**

- `A` adopts `B`; reversal on `B` with authority independently rooted at `A`;
- the same reversal whose authority also depends on `B`;
- `A→B→C` with a reversal on each distance;
- `B` adopted through two paths of different lengths, one later reversed;
- parent and path permutations produce one byte-identical result.

### P1 — `may_reverse` is declared total but only partially defined

The structured capability tuple is the right representation, but the prose
does not yet define a total relation over its declared domain.

Examples left without a unique answer:

- The kind set still contains `ADOPTION-AUTHORITY` and
  `RESOLUTION-QUORUM`, while the target matrix emits
  `JURISDICTION-POLICY` for adoption and resolution. It is unclear whether the
  former kinds are aliases, unreachable values, or distinct capabilities.
- The “jurisdiction quorum dominates what it governs” rule can overlap the
  same-kind-quorum rule, but the precedence and exact governed-target relation
  are not defined.
- `ROTATION-POLICY` specifies the emergency-rotation example, but not the
  result for every `ROTATION-POLICY × ROTATION-POLICY` pair with different
  actor slots, policy successors, or jurisdictions.
- “same principal (or its authorized succession)” requires a formal policy
  lineage relation, especially across a conflict and resolution.
- No default rejection rule or exhaustive case table turns malformed,
  mismatched, stale, or unreachable capability tuples into one result.

Stating that all triples have one result is a conformance requirement, not the
algorithm that produces the result. Two executable models can satisfy every
listed bullet and disagree on unlisted triples.

**Required closure:** provide executable pseudocode or a closed decision table
for `may_reverse`, including tuple well-formedness, rule precedence, policy
lineage comparison, all five kinds, scope mismatch, and a fail-closed default.
Remove unreachable kinds or define their constructors and comparisons.

**Required vectors:** enumerate the finite role/kind product and property-test
principal, jurisdiction, governed-target, and policy-lineage mismatches. The
test must derive its expected result from a normative table/function, not merely
assert that the implementation returns a Boolean.

## What survives this gate

- The immutable, downward-closed input cut remains sound.
- The total per-cut manifest and its three non-collapsing outcomes remain sound.
- The ACI provenance carrier remains sound.
- Authorization and effect remain necessary distinct layers.
- The move from scalar authority to parameterized capability is correct.
- The checkpoint must use detached immutable authorization evidence; rev 6
  correctly rejects self-signing bytes even though its binder is not yet closed.
- Conflict resolution needs explicit lineage semantics; rev 6 correctly locates
  that concern in effect rather than retroactive authorization.

## Next step

Do **not** build the full executable algebra yet. Rev 7 should first close the
four definitions above using small transition equations or pseudocode. Then
build the hermetic executable model immediately — before wire-byte freeze — and
use it to test:

1. termination and uniqueness of revocation/root equations;
2. resolver-selected lineage behavior;
3. exhaustive `may_reverse`;
4. finite, consumer-independent checkpoint authorization.

That is the methodological handoff from prose to executable countervectors.
The remaining prose work should define the machine, not add rationale.

No code, signature, runtime registration, adoption, merge, push, or governance
action was performed by this review.
