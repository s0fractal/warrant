# Codex design re-gate — WRT-002 rev 4

Date: 2026-07-27
Candidate: `dee84da77dcea92d1db9df6d17c450066f5bca7b`
Scope: model §§2–6, before wire-byte freeze
Verdict: **AMEND**

## What now holds

Rev 4 closes the rev-3 findings at their direct seams:

- manifest coverage is total and missing-entry is distinct from historical
  ineligibility;
- authorization and lifecycle effect are separate functions;
- root adoption is represented in provenance;
- key, policy, and checkpoint conflicts have separate resolution shapes;
- quorum-governed transition records cannot be rolled back through the ordinary
  SELF row.

Three role/derivation seams remain before byte freeze.

## Findings

### P1 — Supersede records do not inherit the authority class of the action they perform

The matrix classifies the **target** of a supersede, but the event vocabulary has
no general `lifecycle-supersede` role. This leaves a quorum-authorized supersede
of an ordinary record unclassified when that supersede is itself targeted.

Countervector:

1. Ordinary record `X` is superseded by `S1`, filed by actor A but authorized
   through jurisdiction policy A+B (2-of-3).
2. `S1` is effective, so `X` is retired by quorum action.
3. A files `S2` targeting `S1`, causally after it and signed only by A.
4. `S1` is neither a rotation revocation nor another named quorum-governed role.
   If treated as an ordinary actor-owned record, the SELF row authorizes `S2`.
5. `S1` becomes ineffective and `X` is reinstated: A alone has rolled back A+B.

The reverse recurrence makes this bypass mechanically effective. The same
authority-downgrade can occur at every supersede-of-supersede layer unless the
authority provenance travels with the lifecycle edge.

Add a typed `lifecycle-supersede` event carrying its authorization class
(`SELF`, jurisdiction policy, rotation policy, adoption authority, etc.).
Authorization to supersede that event must be no weaker than the authority that
made its effect valid, or must follow an explicit role-specific succession
rule. Include general supersede events in the ACI carrier, not only the special
`revocation` of rotations.

Add vectors for:

- quorum `S1`, filer-only `S2` (must fail);
- SELF `S1`, same-actor `S2` (may reinstate if intended);
- quorum `S1`, quorum `S2`, SELF `S3` (no authority laundering through depth).

### P1 — Two matrix rows resurrect historical quorums after policy succession

The `root-adoption` row authorizes reversal using "the policy under which the
adoption was authorized"; `key-conflict-resolution` uses "the same quorum that
authorized the resolution". Those are historical authorities, not necessarily
the governing authority at the superseder's pre-state.

Countervector:

1. Policy `P0 = {A,B}` authorizes adoption `D`.
2. A valid policy succession changes governance to `P1 = {C,D}`.
3. Former governors A+B later supersede `D`.
4. The root-adoption matrix row accepts them because P0 authorized the original
   adoption, even though P0 no longer governs the jurisdiction.

This gives removed actors perpetual rollback power over their historical acts.
The analogous rule lets the quorum that filed an old key-conflict resolution
undo it after governance has changed.

Use the **current effective jurisdiction policy-state at
`preEvents(superseder)`** for reversal of root adoption and governance
resolutions, unless the design explicitly intends irrevocable historical
authority. Rotation revocation should continue to use its SPEC current-policy
rule. Add policy-before/policy-after reversal vectors.

### P1 — `active_roots(J,E)` is recursive but has no selected fixed point

Root adoption is now in the event vocabulary, but the derivation says:

- an adoption contributes only if its record is active for `J`;
- a record is active only if root-reachable to `active_roots(J,E)`;
- `active_roots(J,E)` grows through effective adoptions.

That is a recursive closure, not a direct function. Without selecting the least
closure seeded only by J's pinned genesis root, a conforming implementation can
choose a self-supporting greatest closure.

Countervector: two untrusted roots A and B are not genesis-pinned; a record in A
adopts B and a record in B adopts A, with otherwise valid frozen witnesses. The
least closure activates neither; a greatest/self-supporting closure activates
both. ACI union does not choose between them.

Define `active_roots` as the **least fixed point** beginning with exactly J's
pinned roots and repeatedly adding targets of effective, authorized adoption
events whose adopting records are already reachable from the current set.
State how lifecycle effectiveness and bound filing witnesses are stratified
around this closure so an inactive-root event cannot bootstrap its own
authority.

Add mutual-untrusted-adoption, one-pinned/one-adopted, and reversible-adoption
vectors.

## P2 — Preserve emergency rotation under bound filing

Rev 4 requires every R1 `actor-filing` witness to be key-state-bound. A
threshold emergency rotation deliberately permits replacement without the
outgoing actor key. That remains possible only if the enclosing Warrant's
`body.actor.id` may be an already-bound quorum filer distinct from the actor in
the incoming-key subject blob, while the incoming actor supplies the separate
`incoming-pop`.

State this explicitly. Otherwise one implementation may require the rotated
actor to file the record, making its incoming unbound key fail `active_cut` and
silently eliminating the emergency-replacement path that the proposal promises
to preserve.

Add an emergency rotation vector with:

- bound quorum actor as filer;
- different target actor in the key blob;
- no outgoing target-actor signature;
- incoming target-key PoP plus the required quorum.

## Required closure before byte freeze

1. carry authorization class through every lifecycle-supersede edge;
2. use current policy-state rather than retired historical quorums for
   governance rollback;
3. specify least-root activation closure and its evaluation stratum;
4. pin the filer/target distinction for emergency rotation.

The cut, total manifest, ACI carrier, auth/effect split, and distinct resolver
shapes otherwise survive this re-gate.
