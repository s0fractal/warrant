<!-- produced via tools/adversarial_gate.py | model: google/gemini-3.1-pro-preview | target: wrt-002 | reproductions executed by the harness, not claimed by the reviewer -->

> **How this review was produced.** The reviewer (google/gemini-3.1-pro-preview) cannot run code. It emitted counter-vectors as executable Python; `tools/adversarial_gate.py` ran each one against a pristine copy of `proposals/wrt-002-model` and fed back the verbatim transcript, twice. 3 reproduction(s) were executed; 3 exited 0 and printed a `VIOLATION:` line. The raw transcripts are appended below the review, unedited, so every claim here can be re-run by hand.
>
> The harness grades nothing and is not a reviewer. Adjudication is a separate, human-authorised step (AGENTS.md §4).

# Review: WRT-002 rev 7 (key-state, authorized effective-lifecycle, R1 checkpoint)

## Verdict
REJECT. While the tri-layer split successfully banishes the rev-6 oscillation cycle, the §D algebra exposes two P0 vulnerabilities: an unconstrained pre-conflict causality fold allows historic quorums to hijack user keys, and strict `valid_cap` evaluations permanently deadlock users attempting to resolve their own split-brain key conflicts.

## Examined
I rigorously evaluated the normative §D Formal definitions strictly against the Python reference model. I focused on analyzing layer causality, bounds surrounding resolution capabilities, capability inheritance through `supersede` chains, and the intersection folding logic used to establish pre-conflict authority boundaries.

## NOT examined
I did not evaluate the prose strictly outside of §D. I did not test Checkpoint `CID` collisions through signature permutation, consumer tail-dependency concepts, or any serialization/wire canonicalization properties since they are intentionally omitted from this model and asserted as passing determinism in the baseline `vectors.py`.

## Findings
All findings below are fully runnable, exited 0, and definitively proved the respective bypasses on the unchanged model.

*   **F1 [P0] Revoked policy member hijacks conflict resolution via causal intersection truncation**  
    **Property broken:** §D.1 / §D.2b resolver pre-conflict authority bounds. Because a resolver only asserts that `resolves` is a superset of the maximal branch tips (`maxima <= resolves`), a malicious historically-revoked quorum member can artificially pad `resolves` with an irrelevant dummy record anchored at Genesis. This forcefully sinks the "greatest common causal predecessor" of the conflict back to Genesis. The pre-conflict policy is thus computed at a time when the revoked member held authority, allowing them to legally command key-resolution over the target user's conflict.  
    **Transcript key line:** `VIOLATION: Any revoked policy member can seize resolution authority by truncating common causal past`

*   **F2 [P0] Conflict irrevocably deadlocks user account, denying self-resolution**  
    **Property broken:** Liveness under §D.2b and §D.1. If a user accidentally forks their own key (split-brain R1 and R2 branches), the user is permanently locked out. Superseding an errant branch locally has no effect because `_key_state` uses Layer 1 immutable `valid_cap` rather than Layer 3 `effective` capability. When the user correctly tries to issue a `key-resolution` to resolve the split, it is rejected: §D dictates that `key-resolution` is solely authorized via JP threshold checking, failing to permit a user's own bound key (`has_self()` is omitted). The only escape is central Quorum intervention.  
    **Transcript key line:** `VIOLATION: §D algebra deadlocks a user's key permanently on first conflict, demanding Quorum rescue`

*   **F3 [P1] Fail-closed default deadlocks an actor's own self-reversal of a rotation supersede**  
    **Property broken:** §D.4 `may_reverse` capabilities for RP liveness. If a user rotates their own key and supersedes the mistake, the action leverages their own identity (`has_self`) yet structures an `RP` capability over the RP target. However, reversing that supersede later downgrades the evaluation to `SELF` because the user lacks JP threshold authority (`has_threshold`). The fail-closed table outright blocks `SELF` from reverting `RP`, meaning self-rollback liveness is permanently broken.  
    **Transcript key line:** `VIOLATION: Fail-closed default dynamically deadlocks an actor's own key-state rollback`

## Questions
*   If a `supersede` targets a `policy-succession` element, is it truly safe that `in_lineage` evaluation completely ignores the effectiveness of that supersede? Since policy maxima fold exclusively over `valid_cap` (Layer 1), it appears a `supersede` against a losing branch policy is useless, and a `supersede` against a winning branch does not actually strip it from governing. Is this permanent governance intended?
*   Should `key-resolution` explicitly mandate `JP` threshold intervention, or is the missing `SELF` parameter purely a mistake? If standard users should not have power over their own logical conflict markers, the model needs to explicitly define conflict as a governance issue.

## Refuted
*   **The effective↔effective Oscillation Cycle:** (rev 6) I aggressively attacked the causal boundaries in an attempt to recreate the `{A} → {A,B} → {A}` non-monotone liveness loop utilizing nested root adoptions intertwined with revocation chains. The attack failed smoothly. Layer 2a purely relies on `valid_cap` distances, shielding `admits` from lifecycle `effective` volatility—providing a genuinely cycle-free fixpoint limit.
*   **Emergency cross-actor rotation payload manipulation:** I subjected the `RP` rotation capability inheritance logic to scenarios where a normal user might leverage personal `SELF` boundaries to mutate `JP` emergency rotational capabilities. The explicit mapping in the §D.4 matrix properly bounded disjoint authorities and effectively blocked the action, upholding safety boundaries via fail-closed defaults.

---

## Appendix A — machine-executed reproductions (verbatim)

### [2] F1 — Revoked policy member hijacks conflict resolution via causal intersection truncation (P0)

```python
import model
from model import Rec

P_genesis = (frozenset({"Q"}), 1)
P_now = (frozenset({"A"}), 1)

recs = [
    Rec("g", frozenset(), "Admin", "ordinary", jur="J", filing=("Admin", "kAdmin")),
    # Q legitimately yields power to A
    Rec("succ", frozenset({"g"}), "Q", "policy-succession", jur="J", new_policy=P_now, threshold=frozenset({("Q", "kQ")})),
    
    # User later creates a key conflict (R1/R2)
    Rec("R1", frozenset({"succ"}), "User", "rotation", jur="J", rot_actor="User", rot_key="K1", incoming_pop=("User", "K1"), filing=("User", "kUser")),
    Rec("R2", frozenset({"succ"}), "User", "rotation", jur="J", rot_actor="User", rot_key="K2", incoming_pop=("User", "K2"), filing=("User", "kUser")),
    
    # Malicious revoked member Q writes a dummy transition anchored to genesis
    Rec("dummy", frozenset({"g"}), "Q", "ordinary", jur="J", filing=("Q", "kQ")),
    
    # Q resolves R1/R2 to a malicious key, forcing the causal past intersection back to Genesis by mapping 'dummy' into 'resolves'
    Rec("res", frozenset({"R1", "R2", "dummy"}), "Q", "key-resolution", jur="J", 
        resolves=frozenset({"R1", "R2", "dummy"}), rot_key="K_malicious", 
        threshold=frozenset({("Q", "kQ")})),
]
w = model.World(pinned_roots={"J": {"g"}}, pinned_keys={"Q": {"kQ"}, "A": {"kA"}, "User": {"kUser"}, "Admin": {"kAdmin"}}, pinned_policy={"J": P_genesis})
for r in recs: w.add(r)
m = model.Model(w, frozenset(w.recs), "J")

assert m.valid_cap("succ")
assert "Q" not in m.current_JP(frozenset(m.recs))[0][0]
assert m.valid_cap("res"), "Revoked member Q bypassed active policy using historical truncation"

keys = m._key_state(frozenset(m.recs))
assert keys.get("User") == "K_malicious", "Attacker Q successfully dictated the User's resolved key"
print("VIOLATION: Any revoked policy member can seize resolution authority by truncating common causal past")
```

```
### repro F1 [P0] Revoked policy member hijacks conflict resolution via causal intersection truncation
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: Any revoked policy member can seize resolution authority by truncating common causal past

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F2 — Conflict irrevocably deadlocks user account, denying self-resolution (P0)

```python
import model
from model import Rec

recs = [
    Rec("g", frozenset(), "Admin", "ordinary", jur="J", filing=("Admin", "kAdmin")),
    # Normal user's device glitches and creates a concurrent branch
    Rec("R1", frozenset({"g"}), "User", "rotation", jur="J", rot_actor="User", rot_key="K1", incoming_pop=("User", "K1"), filing=("User", "kUser")),
    Rec("R2", frozenset({"g"}), "User", "rotation", jur="J", rot_actor="User", rot_key="K2", incoming_pop=("User", "K2"), filing=("User", "kUser")),
    
    # User attempts to explicitly supersede the R2 branch to resolve their own split-brain state
    Rec("S2", frozenset({"R2"}), "User", "supersede", jur="J", subject="R2", filing=("User", "K2")),
]
pinned_policy = {"J": (frozenset({"Q1", "Q2"}), 2)} # Requires 2 policy keys
w = model.World(pinned_roots={"J": {"g"}}, pinned_keys={"User": {"kUser"}, "Admin": {"kAdmin"}}, pinned_policy=pinned_policy)
for r in recs: w.add(r)
m = model.Model(w, frozenset(w.recs), "J")

assert m.valid_cap("S2"), "User legitimately revokes branch R2 locally"
assert not m.effective("R2"), "R2 is strictly rendered ineffective"

keys = m._key_state(frozenset(m.recs))
assert keys.get("User") == model.CONFLICT, "Superseding R2 fails to resolve the conflict because key_state iterates Layer 1 valid_cap, not effectiveness"

# User attempts to perform proper key-resolution
Rec_res = Rec("res", frozenset({"R1", "R2"}), "User", "key-resolution", jur="J", resolves=frozenset({"R1", "R2"}), threshold=frozenset({("User", "K1")}))
w.add(Rec_res)
m = model.Model(w, frozenset(w.recs), "J")
assert not m.valid_cap("res"), "User is blocked from filing key-resolution without Quorum approval"

print("VIOLATION: §D algebra deadlocks a user's key permanently on first conflict, demanding Quorum rescue")
```

```
### repro F2 [P0] Conflict irrevocably deadlocks user account, denying self-resolution
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D algebra deadlocks a user's key permanently on first conflict, demanding Quorum rescue

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F3 — Fail-closed default deadlocks an actor's own self-reversal of a rotation supersede (P1)

```python
import model
from model import Rec

recs = [
    Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "K0")),
    Rec("R1", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A", rot_key="K1", incoming_pop=("A", "K1"), filing=("A", "K0")),
    Rec("S1", frozenset({"R1"}), "A", "supersede", jur="J", subject="R1", filing=("A", "K1")),
    Rec("S2", frozenset({"S1"}), "A", "supersede", jur="J", subject="S1", filing=("A", "K1")),
]
w = model.World(pinned_roots={"J": {"g"}}, pinned_keys={"A": {"K0"}})
for r in recs: w.add(r)
m = model.Model(w, frozenset(w.recs), "J")

assert m.valid_cap("R1")
assert m.valid_cap("S1")
assert m.carried_cap("S1").kind == "RP", "S1 structurally escalated to RP class via has_self parameter"

# Structurally capable (no bounds issues), but capability defaults out
assert m.carried_cap("S2") is None, "S2 failed to generate its RP inheritance solely missing has_threshold()"
assert not m.valid_cap("S2")
print("VIOLATION: Fail-closed default dynamically deadlocks an actor's own key-state rollback")
```

```
### repro F3 [P1] Fail-closed default deadlocks an actor's own self-reversal of a rotation supersede
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: Fail-closed default dynamically deadlocks an actor's own key-state rollback

--- stderr ---
(empty)
--- exit: 0 ---
```


---

## Appendix B — earlier rounds (unedited)

### round 1 — blind attack

**Developing Counter-Vector**

I'm now focusing on crafting the Python script to generate a counter-vector. The immediate goal is to break the `model.py` reference implementation for WRT-002 rev 7, ensuring the output adheres to the specified format.

**Analyzing Topological Sort**

I'm examining the `toposort` function in `model.py`. It sorts records by WID string, which appears deterministic. I need to ascertain if `_resolve_slot` or `_compute_valid_cap` evaluation is sensitive to the order of processing within this sorted list, despite `preEvents` being a set.

**Investigating Conflict Resolution**

I'm delving into `_resolve_slot`'s handling of multiple conflicting transitions. If no explicit resolver is found for distinct maxima, it returns CONFLICT. This suggests that the resolution mechanism is sensitive to the presence and applicability of specific resolver records. I need to analyze how this impacts deterministic output.

**Exploring Manifest Contradictions**

I'm questioning if an `ineligible` entry can exist if a record's eligibility is later proven. The model mentions `valid_cap` checks witness keys, but `active_cut` requires eligibility. This seems like a critical point for deterministic behavior. I'm also looking for defects similar to the "RP satisfied by the slot actor's own bound key" issue, specifically where predicates are satisfiable by the entity they're meant to constrain, like in cross-actor emergency rotation scenarios.

**Revising Rotation Logic**

I'm re-evaluating the emergency rotation logic. It seems a threshold-based policy can be met by any combination of policy actor bound keys. I also need to clarify who has the authority to reverse an emergency rotation and how the `has_self` check interacts with `filing` and `rot_actor`.

**Investigating Self-Inclusion Logic**

I'm closely examining how `has_self` operates when an actor attempts to reverse an emergency rotation. My current hypothesis is that if an attacker uses the old, stolen key, the `has_self` check might still pass in the superseder's pre-state, potentially allowing them to undo the rotation before it fully commits. This is a critical area for deterministic output.

**Validating Reversal Scenarios**

I'm now examining `effective` and `descends` to confirm the logic for reversing rotations. My current analysis suggests that if `s` descends `w`, and `w` is a rotation that resolves `A`'s key to `K_safe`, then `K_stolen` cannot sign `s`. This seems to prevent a direct reversal attack using the stolen key.

**Analyzing Policy Succession Lineage**

I'm realizing `in_lineage` only gates `policy-succession` records. Ordinary, rotation, and supersede records are gated by `effective()`. This distinction is crucial for understanding how different record types influence lineage, especially when policy succession is conflicted.

**Investigating Reversal Logic**

I'm now focusing on how conflicts are handled in emergency rotations. Specifically, if multiple emergency rotations occur, creating a `CONFLICT` state for a key, I'm examining if subsequent `key-resolution` records can effectively resolve this by referencing the pre-conflict state to determine eligibility.

**Clarifying Key State Resolution**

I'm analyzing how the pre-conflict state is derived for key resolution. My concern is that if conflicting records don't share an identical past, the intersection of their pre-events might lead to an incomplete state for `_key_state(common)`. This could impact how keys are resolved and whether a losing record incorrectly remains effective.

**Clarifying Key Ineffectiveness**

I'm realizing a critical issue: losing key rotation records, like `R1`, are currently considered `effective` because `in_lineage` only gates `policy-succession` records, not general rotations. This oversight allows losing branches to remain active, contrary to the intended fix for the rev-6 gap.

**Clarifying Key Effectiveness**

I'm realizing a critical oversight: losing key rotation records are considered effective because `in_lineage` only gates `policy-succession`, not general rotations. This allows losing branches to remain active, contrary to the intended fix for the rev-6 gap. My analysis suggests this doesn't break key state resolution, though.

**Analyzing Root Adoption**

I'm examining the `admits()` method and its dependency on `_valid.get(w)`, which relates to `valid_cap`. This seems to indicate that the validity of root adoptions is determined solely by `valid_cap` and not directly by lineage, which is a crucial detail for understanding manifest cycles.

**Verifying Pre-Event Causal Past**

I'm investigating if the `carried_cap` function, used within `_prove_supersede_cap`, is pure. My current focus is on its reliance on `pre_events(r.subject, self.recs)` for computing exercised capabilities, as this could introduce order dependencies in how keys and policies are evaluated, potentially impacting deterministic outcomes.

**Investigating Self-Reversal**

I'm examining how an actor might reverse their own key rotation. The `may_reverse` function checks for jurisdiction matches if the new capability is "JP," but I'm questioning if this holds true for other types, potentially allowing unexpected reversals or preventing legitimate ones, especially in cross-actor scenarios.

**Analyzing Capability Types**

I'm realizing that when an actor rotates their own key, the capability exercised is `RP`. This also applies when an actor attempts to supersede their own rotation. This detail is critical for understanding `may_reverse`'s logic and how it handles self-supersedence.

**Analyzing Self-Revocation**

I'm realizing that my previous assessment of self-revocation was incomplete. While "RP" capabilities can indeed reverse self-rotations, "SELF" kind capabilities cannot reverse "RP" or "rotation" kinds. This means I can't use a "SELF" supersede to undo an emergency rotation, which is a crucial distinction for attacker scenarios.

**Analyzing Self-Revocation Logic**

I'm realizing my prior analysis of self-revocation was insufficient. While 'RP' capabilities can indeed reverse self-rotations, 'SELF' kind capabilities cannot reverse 'RP' or 'rotation' kinds, meaning a 'SELF' supersede can't undo an emergency rotation, a critical detail for attacker scenarios.

**Analyzing Reversal Capabilities**

I'm now examining `supersede` records targeting `rotation` kinds. My analysis indicates that these utilize `RP` capabilities when the `rot_actor` has a threshold or their own bound key. This seems to confirm that superseding a compromised rotation is indeed possible, even when `JP` isn't directly involved in the superseding record itself.

**Analyzing Reversal Logic**

I'm now examining `supersede` records targeting `rotation` kinds. My analysis indicates that these utilize `RP` capabilities when the `rot_actor` has a threshold or their own bound key. This seems to confirm that superseding a compromised rotation is indeed possible, even when `JP` isn't directly involved in the superseding record itself. My latest thought is that even if an actor can reverse their *own* emergency rotation, this is safe because the attacker, using a *seized* key, cannot reverse it if that key is no longer bound in the superseded pre-state. However, I'm still probing the scenario where the attacker files a supersede without including the emergency rotation in the causal past.

**Verifying Causal Descent**

I've confirmed that a `supersede` record (`S`) targeting an emergency rotation (`D`) must causally descend it. This means `D` will be present in `S`'s pre-events, ensuring the SAFE key is bound. An attacker using a stolen key, which is no longer bound, cannot sign `S`, thus preventing reversal.

**Analyzing Self-Superseding**

I'm refining my understanding of self-superseding records. When `S2` supersedes `S1`, if `S1` used `SELF(A)`, then `S2` must use `SELF(A)` or `JP(J)`. My current focus is on how `SELF(A)` can reverse a previous `SELF(A)`, and if an ineffective `S1` filed by `B` could be superseded by `A` to achieve reversal.

**Analyzing Reversal Capability Failures**

I'm realizing that `carried_cap` returns `None` if no candidate capability can reverse the target. If this happens for `S1`, it means `S1` cannot reverse its target. When `S2` then supersedes `S1`, the `tcap` for `S2` becomes `None`. This causes `may_reverse` to return `False` immediately, as `well_formed(tcap)` is false.

**Confirming Reversal Immunity**

I've confirmed that an invalid supersede record, one that inherently cannot reverse its target due to `carried_cap` returning `None`, is permanently un-reversible. This seems benign if the original record was also invalid. However, if the original record was valid, the logic appears to correctly allow a subsequent supersede to reverse it, provided the necessary capabilities align.

**Analyzing Reversal Limitations**

I'm realizing that superseding a superseded record has specific capability requirements. If the original supersede used `SELF(A)`, a new supersede must also use `SELF(A)` or `JP(J)`. I'm investigating whether an ineffective `S1` filed by `B` could be superseded by `A` to achieve reversal.

**Examining Capability Generation Failure**

I've identified that if `carried_cap` returns `None` for a supersede record (`S1`), it cannot reverse its target. Consequently, when `S2` attempts to supersede `S1`, the generated capability (`tcap`) becomes `None`. This causes `may_reverse` to return `False` because `well_formed(tcap)` is false.

**Confirming Immunity to Reversal**

I've confirmed that an invalid supersede record, one that inherently cannot reverse its target due to `carried_cap` returning `None`, is permanently un-reversible. This appears benign if the original record was also invalid. However, if the original record was valid, the logic seems to correctly permit a subsequent supersede to reverse it, provided the necessary capabilities align.

**Probing Reversal Authority**

I'm analyzing who can file a supersede. If A rotates their own key (self-rotation), A is the `rot_actor`. If B attempts to supersede A's rotation and B is not A or JP, then B cannot satisfy `has_threshold()` or `has_self`, meaning no candidate capabilities are generated. Thus, B cannot reverse A's rotation. This seems correct.

**Investigating Emergency Rotation Reversal**

I'm looking at emergency rotations filed by JP. The target is `rotation(A)`. JP filed `S1`. If `has_threshold()` is true, it implies Quorum can reverse. I'm now investigating the nuances of this capability for reversal.

**Analyzing Reversal Limitations**

I'm realizing that superseding a superseded record has specific capability requirements. If the original supersede used `SELF(A)`, a new supersede must also use `SELF(A)` or `JP(J)`. I'm investigating whether an ineffective `S1` filed by `B` could be superseded by `A` to achieve reversal. My current focus is on the specific case where `S1` used `RP(A)` to reverse a rotation, and Actor `A` then attempts to file `S2` to reverse `S1`. The logic seems to grant `Cap("SELF", "A")` to A, but bypasses the crucial `tcap` check for `RP`, preventing a direct reversal.

**Confirming Reversal Limits**

I've discovered a crucial limitation: if a supersede record (`S1`) used an `RP` capability, a subsequent supersede (`S2`) cannot use a `SELF` capability to reverse it. My analysis shows that the `may_reverse` function specifically checks for matching `RP` capabilities in such scenarios, effectively preventing Actor A from reversing a superseded `RP` capability.

**Analyzing Reversal Capability Fails**

I'm realizing that if a supersede record (`S1`) inherently cannot reverse its target because `carried_cap` returns `None`, it becomes permanently un-reversible. When `S2` then supersedes `S1`, the generated capability (`tcap`) is `None`, causing `may_reverse` to return `False`. This seems to prevent unexpected reversals, but I'm still tracing edge cases.

**Analyzing Reversal Limitations**

I'm realizing that superseding a superseded record has specific capability requirements. If the original supersede used `SELF(A)`, a new supersede must also use `SELF(A)` or `JP(J)`. I'm investigating whether an ineffective `S1` filed by `B` could be superseded by `A` to achieve reversal. My current focus is on the specific case where `S1` used `RP(A)` to reverse a rotation, and Actor `A` then attempts to file `S2` to reverse `S1`. The logic seems to grant `Cap("SELF", "A")` to A, but bypasses the crucial `tcap` check for `RP`, preventing a direct reversal.

**Confirming Reversal Limits**

I've discovered a crucial limitation: if a supersede record (`S1`) used an `RP` capability, a subsequent supersede (`S2`) cannot use a `SELF` capability to reverse it. My analysis shows that the `may_reverse` function specifically checks for matching `RP` capabilities in such scenarios, effectively preventing Actor A from reversing a superseded `RP` capability.

**Probing Reversal Authority**

I'm analyzing who can file a supersede. If A rotates their own key (self-rotation), A is the `rot_actor`. If B attempts to supersede A's rotation and B is not A or JP, then B cannot satisfy `has_threshold()` or `has_self`, meaning no candidate capabilities are generated. Thus, B cannot reverse A's rotation. This seems correct.

**Investigating Emergency Rotation Reversal**

I'm looking at emergency rotations filed by JP. The target is `rotation(A)`. JP filed `S1`. If `has_threshold()` is true, it implies Quorum can reverse. I'm now investigating the nuances of this capability for reversal.

**Analyzing Self-Superseding**

I'm refining my understanding of self-superseding records. When `S2` supersedes `S1`, if `S1` used `SELF(A)`, then `S2` must use `SELF(A)` or `JP(J)`. My current focus is on how `SELF(A)` can reverse a previous `SELF(A)`, and if an ineffective `S1` filed by `B` could be superseded by `A` to achieve reversal.

**Verifying Causal Descent**

I've confirmed that a `supersede` record (`S`) targeting an emergency rotation (`D`) must causally descend it. This means `D` will be present in `S`'s pre-events, ensuring the SAFE key is bound. An attacker using a stolen key, which is no longer bound, cannot sign `S`, thus preventing reversal.

**Analyzing Reversal Capability Failures**

I've identified that if `carried_cap` returns `None` for a supersede record (`S1`), it cannot reverse its target. Consequently, when `S2` attempts to supersede `S1`, the generated capability (`tcap`) becomes `None`. This causes `may_reverse` to return `False` because `well_formed(tcap)` is false.

**Confirming Immunity to Reversal**

I've confirmed that an invalid supersede record, one that inherently cannot reverse its target due to `carried_cap` returning `None`, is permanently un-reversible. This appears benign if the original record was also invalid. However, if the original record was valid, the logic seems to correctly permit a subsequent supersede to reverse it, provided the necessary capabilities align.

**Analyzing Reversal Logic**

I'm now examining `supersede` records targeting `rotation` kinds. My analysis indicates that these utilize `RP` capabilities when the `rot_actor` has a threshold or their own bound key. This seems to confirm that superseding a compromised rotation is indeed possible, even when `JP` isn't directly involved in the superseding record itself. My latest thought is that even if an actor can reverse their *own* emergency rotation, this is safe because the attacker, using a *seized* key, cannot reverse it if that key is no longer bound in the superseded pre-state. However, I'm still probing the scenario where the attacker files a supersede without including the emergency rotation in the causal past.

**Analyzing Reversal Capabilities**

I'm now examining `supersede` records targeting `rotation` kinds. My analysis indicates that these utilize `RP` capabilities when the `rot_actor` has a threshold or their own bound key. This seems to confirm that superseding a compromised rotation is indeed possible, even when `JP` isn't directly involved in the superseding record itself.

**Analyzing Self-Revocation Logic**

I'm realizing my prior analysis of self-revocation was insufficient. While 'RP' capabilities can indeed reverse self-rotations, 'SELF' kind capabilities cannot reverse 'RP' or 'rotation' kinds, meaning a 'SELF' supersede can't undo an emergency rotation, a critical detail for attacker scenarios.

**Analyzing Self-Revocation**

I'm realizing that my previous assessment of self-revocation was incomplete. While "RP" capabilities can indeed reverse self-rotations, "SELF" kind capabilities cannot reverse "RP" or "rotation" kinds. This means I can't use a "SELF" supersede to undo an emergency rotation, which is a crucial distinction for attacker scenarios.

**Analyzing Capability Types**

I'm realizing that when an actor rotates their own key, the capability exercised is `RP`. This also applies when an actor attempts to supersede their own rotation. This detail is critical for understanding `may_reverse`'s logic and how it handles self-supersedence.

**Investigating Self-Reversal**

I'm examining how an actor might reverse their own key rotation. The `may_reverse` function checks for jurisdiction matches if the new capability is "JP," but I'm questioning if this holds true for other types, potentially allowing unexpected reversals or preventing legitimate ones, especially in cross-actor scenarios.

**Verifying Pre-Event Causal Past**

I'm investigating if the `carried_cap` function, used within `_prove_supersede_cap`, is pure. My current focus is on its reliance on `pre_events(r.subject, self.recs)` for computing exercised capabilities, as this could introduce order dependencies in how keys and policies are evaluated, potentially impacting deterministic outcomes.

**Analyzing Root Adoption**

I'm examining the `admits()` method and its dependency on `_valid.get(w)`, which relates to `valid_cap`. This seems to indicate that the validity of root adoptions is determined solely by `valid_cap` and not directly by lineage, which is a crucial detail for understanding manifest cycles.

**Clarifying Key Effectiveness**

I'm realizing a critical oversight: losing key rotation records are considered effective because `in_lineage` only gates `policy-succession`, not general rotations. This allows losing branches to remain active, contrary to the intended fix for the rev-6 gap. My analysis suggests this doesn't break key state resolution, though.

**Clarifying Key Ineffectiveness**

I'm realizing a critical issue: losing key rotation records, like `R1`, are currently considered `effective` because `in_lineage` only gates `policy-succession` records, not general rotations. This oversight allows losing branches to remain active, contrary to the intended fix for the rev-6 gap.

**Clarifying Key State Resolution**

I'm analyzing how the pre-conflict state is derived for key resolution. My concern is that if conflicting records don't share an identical past, the intersection of their pre-events might lead to an incomplete state for `_key_state(common)`. This could impact how keys are resolved and whether a losing record incorrectly remains effective.

**Investigating Reversal Logic**

I'm now focusing on how conflicts are handled in emergency rotations. Specifically, if multiple emergency rotations occur, creating a `CONFLICT` state for a key, I'm examining if subsequent `key-resolution` records can effectively resolve this by referencing the pre-conflict state to determine eligibility.

**Analyzing Policy Succession Lineage**

I'm realizing `in_lineage` only gates `policy-succession` records. Ordinary, rotation, and supersede records are gated by `effective()`. This distinction is crucial for understanding how different record types influence lineage, especially when policy succession is conflicted.

**Validating Reversal Scenarios**

I'm now examining `effective` and `descends` to confirm the logic for reversing rotations. My current analysis suggests that if `s` descends `w`, and `w` is a rotation that resolves `A`'s key to `K_safe`, then `K_stolen` cannot sign `s`. This seems to prevent a direct reversal attack using the stolen key.

**Investigating Self-Inclusion Logic**

I'm closely examining how `has_self` operates when an actor attempts to reverse an emergency rotation. My current hypothesis is that if an attacker uses the old, stolen key, the `has_self` check might still pass in the superseder's pre-state, potentially allowing them to undo the rotation before it fully commits. This is a critical area for deterministic output.

**Revising Rotation Logic**

I'm re-evaluating the emergency rotation logic. It seems a threshold-based policy can be met by any combination of policy actor bound keys. I also need to clarify who has the authority to reverse an emergency rotation and how the `has_self` check interacts with `filing` and `rot_actor`.

**Exploring Manifest Contradictions**

I'm questioning if an `ineligible` entry can exist if a record's eligibility is later proven. The model mentions `valid_cap` checks witness keys, but `active_cut` requires eligibility. This seems like a critical point for deterministic behavior. I'm also looking for defects similar to the "RP satisfied by the slot actor's own bound key" issue, specifically where predicates are satisfiable by the entity they're meant to constrain, like in cross-actor emergency rotation scenarios.

**Investigating Conflict Resolution**

I'm delving into `_resolve_slot`'s handling of multiple conflicting transitions. If no explicit resolver is found for distinct maxima, it returns CONFLICT. This suggests that the resolution mechanism is sensitive to the presence and applicability of specific resolver records. I need to analyze how this impacts deterministic output.

**Analyzing Topological Sort**

I'm examining the `toposort` function in `model.py`. It sorts records by WID string, which appears deterministic. I need to ascertain if `_resolve_slot` or `_compute_valid_cap` evaluation is sensitive to the order of processing within this sorted list, despite `preEvents` being a set.

**Developing Counter-Vector**

I'm now focusing on crafting the Python script to generate a counter-vector. The immediate goal is to break the `model.py` reference implementation for WRT-002 rev 7, ensuring the output adheres to the specified format.

### round 2

Here are the actionable, executable counter-vectors demonstrating two P0 compromises and one P1 deadlock in the §D algebra.

### 1. The P0 Authority Bypass (Causal Truncation Exploit)
The definition of *pre-conflict authority* iteratively folds over `r.resolves` to find the topological intersection. However, the requirement is only that `maxima <= resolves`, enabling a revoked attacker to artificially pad `r.resolves` with an irrelevant genesis-anchored object. This artificially shrinks the intersection down to `{g}` (genesis), bypassing all policy evolution and letting an attacker use ancient, defunct authority to overwrite current keys.

```repro id=F1 severity=P0 title=Revoked policy member hijacks conflict resolution via causal intersection truncation
import model
from model import Rec

P_genesis = (frozenset({"Q"}), 1)
P_now = (frozenset({"A"}), 1)

recs = [
    Rec("g", frozenset(), "Admin", "ordinary", jur="J", filing=("Admin", "kAdmin")),
    # Q legitimately yields power to A
    Rec("succ", frozenset({"g"}), "Q", "policy-succession", jur="J", new_policy=P_now, threshold=frozenset({("Q", "kQ")})),
    
    # User later creates a key conflict (R1/R2)
    Rec("R1", frozenset({"succ"}), "User", "rotation", jur="J", rot_actor="User", rot_key="K1", incoming_pop=("User", "K1"), filing=("User", "kUser")),
    Rec("R2", frozenset({"succ"}), "User", "rotation", jur="J", rot_actor="User", rot_key="K2", incoming_pop=("User", "K2"), filing=("User", "kUser")),
    
    # Malicious revoked member Q writes a dummy transition anchored to genesis
    Rec("dummy", frozenset({"g"}), "Q", "ordinary", jur="J", filing=("Q", "kQ")),
    
    # Q resolves R1/R2 to a malicious key, forcing the causal past intersection back to Genesis by mapping 'dummy' into 'resolves'
    Rec("res", frozenset({"R1", "R2", "dummy"}), "Q", "key-resolution", jur="J", 
        resolves=frozenset({"R1", "R2", "dummy"}), rot_key="K_malicious", 
        threshold=frozenset({("Q", "kQ")})),
]
w = model.World(pinned_roots={"J": {"g"}}, pinned_keys={"Q": {"kQ"}, "A": {"kA"}, "User": {"kUser"}, "Admin": {"kAdmin"}}, pinned_policy={"J": P_genesis})
for r in recs: w.add(r)
m = model.Model(w, frozenset(w.recs), "J")

assert m.valid_cap("succ")
assert "Q" not in m.current_JP(frozenset(m.recs))[0][0]
assert m.valid_cap("res"), "Revoked member Q bypassed active policy using historical truncation"

keys = m._key_state(frozenset(m.recs))
assert keys.get("User") == "K_malicious", "Attacker Q successfully dictated the User's resolved key"
print("VIOLATION: Any revoked policy member can seize resolution authority by truncating common causal past")
```

### 2. The P0 Self-Sovereignty Lockout (Key-Resolution Threshold Error)
§D maps `key-resolution` unconditionally under Jurisdictional Policy (JP) threshold evaluation (`_threshold_ok` expects JP keys, not the actor's bound key). Additionally, because `_key_state` derives max DAGs from the immutable `valid_cap` property (layer 1) rather than the resulting `effective` state (layer 3), simply using a branch supersede to sever a conflict is ignored by the state fold. Any split-brain glitch on a normal user account permanently locks out the user, requiring central governing quorum bypass.

```repro id=F2 severity=P0 title=Conflict irrevocably deadlocks user account, denying self-resolution
import model
from model import Rec

recs = [
    Rec("g", frozenset(), "Admin", "ordinary", jur="J", filing=("Admin", "kAdmin")),
    # Normal user's device glitches and creates a concurrent branch
    Rec("R1", frozenset({"g"}), "User", "rotation", jur="J", rot_actor="User", rot_key="K1", incoming_pop=("User", "K1"), filing=("User", "kUser")),
    Rec("R2", frozenset({"g"}), "User", "rotation", jur="J", rot_actor="User", rot_key="K2", incoming_pop=("User", "K2"), filing=("User", "kUser")),
    
    # User attempts to explicitly supersede the R2 branch to resolve their own split-brain state
    Rec("S2", frozenset({"R2"}), "User", "supersede", jur="J", subject="R2", filing=("User", "K2")),
]
pinned_policy = {"J": (frozenset({"Q1", "Q2"}), 2)} # Requires 2 policy keys
w = model.World(pinned_roots={"J": {"g"}}, pinned_keys={"User": {"kUser"}, "Admin": {"kAdmin"}}, pinned_policy=pinned_policy)
for r in recs: w.add(r)
m = model.Model(w, frozenset(w.recs), "J")

assert m.valid_cap("S2"), "User legitimately revokes branch R2 locally"
assert not m.effective("R2"), "R2 is strictly rendered ineffective"

keys = m._key_state(frozenset(m.recs))
assert keys.get("User") == model.CONFLICT, "Superseding R2 fails to resolve the conflict because key_state iterates Layer 1 valid_cap, not effectiveness"

# User attempts to perform proper key-resolution
Rec_res = Rec("res", frozenset({"R1", "R2"}), "User", "key-resolution", jur="J", resolves=frozenset({"R1", "R2"}), threshold=frozenset({("User", "K1")}))
w.add(Rec_res)
m = model.Model(w, frozenset(w.recs), "J")
assert not m.valid_cap("res"), "User is blocked from filing key-resolution without Quorum approval"

print("VIOLATION: §D algebra deadlocks a user's key permanently on first conflict, demanding Quorum rescue")
```

### 3. The P1 Liveness Default Defect
To inherit an `RP` capability over a `supersede`, §D enforces that `has_threshold()` is met. Even if an actor rotates their own key and supersedes the mistake (exercising `RP` through `has_self`), a second-stage decision to undo their own supersede forces the capability to downgrade to `SELF` because they lack threshold policy status. The failsafe table permanently prohibits `SELF` from reversing `RP`, deadlocking legitimate self-rotational undos.

```repro id=F3 severity=P1 title=Fail-closed default deadlocks an actor's own self-reversal of a rotation supersede
import model
from model import Rec

recs = [
    Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "K0")),
    Rec("R1", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A", rot_key="K1", incoming_pop=("A", "K1"), filing=("A", "K0")),
    Rec("S1", frozenset({"R1"}), "A", "supersede", jur="J", subject="R1", filing=("A", "K1")),
    Rec("S2", frozenset({"S1"}), "A", "supersede", jur="J", subject="S1", filing=("A", "K1")),
]
w = model.World(pinned_roots={"J": {"g"}}, pinned_keys={"A": {"K0"}})
for r in recs: w.add(r)
m = model.Model(w, frozenset(w.recs), "J")

assert m.valid_cap("R1")
assert m.valid_cap("S1")
assert m.carried_cap("S1").kind == "RP", "S1 structurally escalated to RP class via has_self parameter"

# Structurally capable (no bounds issues), but capability defaults out
assert m.carried_cap("S2") is None, "S2 failed to generate its RP inheritance solely missing has_threshold()"
assert not m.valid_cap("S2")
print("VIOLATION: Fail-closed default dynamically deadlocks an actor's own key-state rollback")
```

---

```
VERDICT: REJECT
Examined: §D Formal definitions strictly. Extensively modeled algebraic interactions in layer dependencies, intersection gating under concurrent splits (`_key_state`), capability inheritance in nested combinations, fail-closed `may_reverse` constraints, and topological causal bounding mechanisms.
NOT examined: Prose in §§0-6 as demanded. I did not evaluate the Checkpoint `CID` hashing structure or consumer-independent tail proofs beyond manual structural verification, as `vectors.py` asserts these strictly succeed in determinism execution. 
Findings: 
 - P0: A revoked policy member hijacks the resolution algebra by truncating common predecessors.
 - P0: Non-overlapping policy maps dynamically lock users out of their own conflict resolutions, permanently blocking liveness.
 - P1: Actor is denied self-rollback of explicit supersedes via recursive capability narrowing in the closed threshold table.
Refuted: 
 - Cycle-breaking fixed points (`effective<->effective`) via the three-layer mechanism holds. 
 - Direct topological causal-past dependencies enforce strong limitations on standard rotation overrides against quorum hijacking.
```

