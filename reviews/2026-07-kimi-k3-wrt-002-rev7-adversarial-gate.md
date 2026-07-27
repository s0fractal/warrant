<!-- produced via tools/adversarial_gate.py | model: moonshotai/kimi-k3 | target: wrt-002 | reproductions executed by the harness, not claimed by the reviewer -->

> **How this review was produced.** The reviewer (moonshotai/kimi-k3) cannot run code. It emitted counter-vectors as executable Python; `tools/adversarial_gate.py` ran each one against a pristine copy of `proposals/wrt-002-model` and fed back the verbatim transcript, twice. 10 reproduction(s) were executed; 10 exited 0 and printed a `VIOLATION:` line. The raw transcripts are appended below the review, unedited, so every claim here can be re-run by hand.
>
> The harness grades nothing and is not a reviewer. Adjudication is a separate, human-authorised step (AGENTS.md §4).

# Review: WRT-002 rev 7 — independent adversarial gate (key-state, authorized effective-lifecycle, R1 checkpoint)

## Verdict

**REJECT.** All ten reproductions executed against a pristine `model.py` and confirmed: the machine is unsound as built — the key-binding predicate fails open on both the conflict sentinel (F1) and on absent keys (F2), and layer-2a root admission reads `valid_cap` of resolver-*rejected* governance branches, yielding a permanent, irreversible censorship primitive (F3) and its unauthorized-admission dual (F4) — before the four P1 composition breaks (F5–F7) and three P2s (F8–F10) are even counted.

## Examined

- `proposals/wrt-002-model/model.py` — every function, line by line, including `_compute_valid_cap`, `_prove_supersede_cap`, `_compute_admits`, `selected_lineage_policy`, `effective`, `may_reverse`, `checkpoint_CID`, `checkpoint_authorized`, `_canon`.
- `proposals/wrt-002-model/vectors.py` — read in full (all 9 test groups); per the brief I did not treat its pass as evidence.
- §D of `proposals/WRT-002-keystate-effective-lifecycle-r1.md` — the normative core, D.1 through D.5.
- The ten execution transcripts returned by the harness. **Every claim I made was confirmed by execution; none of my reproductions failed or was refuted by the machine.**

## NOT examined

- **The total manifest / `ineligible` negative claim (attack surface #2).** `model.py` contains no manifest object at all — §D.1's "manifest witnesses" and §D.3's "eligible manifest entry" have no executable counterpart. The colluding-quorum negative-claim attack is untestable against this machine. Filed under Questions.
- **Frontier completeness / the omission attack (surface #4, second half).** The checkpoint `state` is a free-form dict; the machine cannot express "the frontier omits an admitted record," so the visibility claim cannot be exercised. Filed under Questions.
- **The WRT-001/ADR-008 interface (surface #6).** The model exposes no `authorized_effective_active_for(J, checkpoint)` entry point; external-interface conformance is untestable here. Filed under Questions.
- **§§0–6 prose** (§D governs per the brief) and **wire bytes / serialization / crypto** (out of scope per the brief; the model has no crypto by design).

## Findings

All ten blocks exited 0 and printed `VIOLATION:`; the harness verdict on each was REPRODUCED.

**F1 — P0 — Conflicted key-slot is fail-open; the CONFLICT marker binds as a key.**
Property broken: §D.2b "≥2 maximal DAG-unordered ⇒ conflict marker (slot UNUSABLE)". `_key_state` stores the string `«CONFLICT»` as the actor's key; `_bound` is a plain `==`, so presenting `("A", "«CONFLICT»")` satisfies the filing check, and `_threshold_ok` counts it toward quorum. An ordinary record "signed" with the marker computes `effective`, and a 2-of-2 policy-succession carrying the marker plus one real signature seizes the jurisdiction's policy.
Transcript: *"a conflicted key-slot is fail-open: _bound and _threshold_ok compare a presented key against the CONFLICT marker itself, so anyone can 'sign as' the conflicted actor — an ordinary record computes effective and the 2-of-2 governance threshold is satisfied (policy seized)"*.

**F2 — P0 — Absent key binds: a keyless actor's null key satisfies filings, thresholds, and checkpoint sets.**
Property broken: §D.1 "a witness key is BOUND iff it is the actor's key in the relevant pre-state key-state". `keystate.get(actor)` returns `None` for an actor with no key, and `None == None`, so `("Z", None)` is "bound" for any keyless `Z`. A keyless actor authors an `effective` record; a 2-of-2 policy containing a keyless member is satisfiable with one real signature; the null witness counts toward `checkpoint_authorized`.
Transcript: *"keyless actors author effective records, satisfy governance thresholds (2-of-2 met with one real signature) and count toward checkpoint authorization sets — fail-open on absence"*.

**F3 — P0 — Resolver-REJECTED policy branch permanently censors an adopted root via layer-2a reversal.**
Property broken: §D.2b "a losing policy/key branch is gated by `in_lineage`" composed with §D.2a `reversed()`. After a resolver selects P2 over P1, actor A (sole member of the dead branch's P1) files a supersede of adoption D under P1's authority. That supersede is `valid_cap` (D.1 evaluates only the causal past), never descends its target, and is never `effective` — yet `_compute_admits` reads `valid_cap` only, so it reverses D and censors root RB. Revoking the censoring supersede with the legitimate P2 quorum and re-adopting RB changes nothing: the reversal clause is permanent. This is precisely the censorship primitive WRT-002 exists to eliminate, laundered through a branch governance already rejected.
Transcript: *"a supersede authorized solely by a resolver-REJECTED policy branch (which never even descends its target) reverses an adoption; revoking the censor and re-adopting cannot restore admission. A dead branch permanently censors a root and every record on it"*.

**F4 — P1 — Resolver-REJECTED branch admits an unauthorized root (dual of F3).**
Property broken: §D.2a `dist()` reads `valid_cap` of adoptions only. An adoption authorized solely under the dead branch's policy admits a root the selected governance never adopted; records on it compute `effective`. Same root cause as F3 (layer 2a consumes Layer-1 permanence without the layer-2b gate), opposite direction.
Transcript: *"an adoption authorized solely under a resolver-REJECTED policy branch admits a root the selected governance never adopted, and records on it compute effective"*.

**F5 — P1 — Losing branch re-enters the selected lineage once history advances past the resolver.**
Property broken: §D.2b "`selected_lineage(slot) := the genesis→…→winner chain` … a losing policy/key branch is gated by `in_lineage`". `selected_lineage_policy`'s single-maximal path returns `closure(maximal) ∩ successions`; once a later valid succession descends the resolver, that closure contains *both* original forks, so the rejected succession `s1` flips from gated-out to `in_lineage` and computes `effective`. The suite's pinned property holds only at the resolver tip; gating is non-monotone in the cut.
Transcript: *"once a later succession descends the resolver, selected_lineage_policy's single-maximal path returns closure(maximal), which contains BOTH forks; the rejected s1 re-enters the selected lineage and computes effective (non-monotone gating)"*.

**F6 — P1 — Checkpoint authorization reads the verifier's cut, not `cut(P.frontier)`; verdicts flip retroactively both ways.**
Property broken: §D.5 "`verify(CID)`: resolve `P`; rebuild `cut(P.frontier)`; derive `current_JP(J)` … **Immutable** … **Consumer-independent**". `checkpoint_authorized` derives policy and key-state from `frozenset(model.recs)` — the verifier's own cut. Direction 1: a routine signer key-rotation after the frontier makes a pinned, fully-authorized CID stop verifying. Direction 2: a below-threshold auth set becomes authorized after a later policy-succession. The CID bytes are frozen; the *verdict* is not.
Transcript: *"a pinned CID's authorization flips retroactively in both directions: a signer rotation kills a frozen checkpoint, and a below-threshold set gains authorization after a policy change. Not immutable, not consumer-independent"*.

**F7 — P1 — Two competing resolvers permanently brick the jurisdiction; a unanimous re-resolution is impotent.**
Property broken: §D.2b "a valid_cap resolver … selects one branch" (as a recoverability property) and §D.4's fail-closed default considered for liveness. Two honest P0-quorums resolve the same fork differently; `_resolve_slot` requires *exactly one* resolver, so the slot is conflicted. Thereafter: a unanimous (3-of-3) re-resolution is `valid_cap` yet impotent (it merely becomes a third competing resolver); a resolver-of-resolvers is rejected (`_slot_maxima` admits only successions, never resolvers); no further succession can ever be authorized under a conflicted policy. One governance race = permanent deadlock.
Transcript: *"the conflict rule only ever counts MORE resolvers — a subsequent unanimous resolution is valid_cap yet impotent, and no succession can ever be authorized again. One governance race = permanent jurisdiction deadlock (the fail-closed default fails dead)"*.

**F8 — P2 — `checkpoint_authorized` never binds witnesses to the state (the `state` argument is unused).**
Property broken: §D.5 "`verify(CID)`: … check `sig_i-over-P` by a key bound to `actor_i`". The oracle accepts a policy-satisfying AW set as attesting *any* state blob, including one whose P the witnesses never signed over; only an external CID comparison binds content to signatures.
Transcript: *"any policy-satisfying AW set is accepted as attesting ANY state blob; the certificate's content is unbound from its signatures at the verification layer"*.

**F9 — P2 — Record actor and filing witness are never tied; authorization and identity detach.**
Property broken: §D.1/§D.3 "bound actor-filing". The machine checks that *some* key is bound, never that it is the record actor's: a record naming Mallory as actor is authorized by Alice's key; the SELF capability and revocation rights attach to the non-signing Mallory, while Alice — whose key actually authorized the record — cannot reverse it.
Transcript: *"a record filed 'by' Mallory is authorized by Alice's key; the SELF capability and revocation rights attach to the non-signing actor while the actual authorizer cannot reverse it"*.

**F10 — P2 — Duplicate `(J, sequence)` CIDs from disjoint honest quorums; no consumer-independent tie-break.**
Property broken: §D.5 "`CID` … **THE checkpoint identity** … **Consumer-independent** — no wave citation or successor is needed to freeze it". One `(J, sequence)` yields two valid CIDs over different frontiers from *disjoint* 2-of-4 quorums — zero equivocation, so no signer is attributable. §D.5's only disambiguation is "a certificate descending both", i.e. a successor — the exact tail-dependency the design claims to have killed.
Transcript: *"the only disambiguation §D.5 offers is 'a certificate descending both' — i.e. a successor, the exact dependency the design claims to have eliminated"*.

## Questions

- **The manifest negative-claim attack (surface #2) is untestable here.** There is no manifest in `model.py`, so I could not construct the colluding-quorum `ineligible` entry, nor evaluate the "visible and attributable" claim, nor test whether a post-checkpoint signature can retroactively establish eligibility. To settle this I would need an executable manifest (eligible/ineligible entries, the challenge procedure, and what bytes a challenger must hold).
- **Frontier-completeness omission (surface #4).** The checkpoint `state` dict accepts any `frontier` value; the machine has no notion of "the frontier omits an admitted record", so what a downstream R1 consumer sees under quorum omission — and whether it is *visible* — cannot be demonstrated against this model.
- **WRT-001 interface (surface #6).** No `authorized_effective_active_for(J, checkpoint)` exists in the machine. Whether §D's checkpoint supplies the properties WRT-001 §6 assumes is unverifiable against this reference; a substrate can be internally repaired and still externally mismatched.
- **`authority_dist` for JP capabilities.** §D.2a requires `authority_dist(cap(S)) < dist(r)` but never defines `authority_dist` for a JP cap; the model hardcodes `auth_dist = 0` ("J's governing policy is genesis-anchored"). F3 stands against the reference machine regardless, but if §D intends authority distance to track the policy's own adoption depth, that should be said normatively — as written, any JP-authorized supersede reverses any adoption at any depth.
- **F9's blast radius.** Whether the actor/filing detachment is exploitable beyond capability-attribution confusion depends on filing semantics in §§0–6, which I did not read (§D governs). The machine behavior is demonstrated; the question is whether any higher layer assumes `actor == filing[0]`.

## Refuted

Attacks I constructed and walked through that **held** (none of these were executed as blocks; they are analysis walks, and where noted they are also covered by the suite):

1. **Effective↔effective negation cycle (the rev-6 defect class).** I tried to rebuild `R = ¬S ∧ S = R` via mutual supersedes. The §5 causal rule skips any supersede `S` of `x` unless `S` strictly descends `x`; a cycle would require each record to be in the other's strict causal past, impossible in a DAG. The reverse recurrence reads only strictly-deeper superseders, so the guard (`_eff_stack`) cannot fire on any DAG input. **Held.**
2. **Evaluation-order dependence of `effective` (brief's surface #1, second bullet).** I looked for an input where the guard stays silent but two evaluation orders give different `effective` sets. `effective()` memoizes over a well-founded relation; the scan order over `self.recs` affects only which qualifying superseder is found first, and `ok = False` is absorbing, so the result is order-independent. Arrival order is not an input to the machine at all — the cut is a set. (The suite's 20-permutation byte-identity check on `canonical()` corroborates.) **Held.**
3. **Re-padding `resolves` (the prior gate's Gemini F1 fix).** I tried variants of the original padding attack: padding with same-slot, same-jurisdiction *non-maximal* transitions, and padding with records outside the resolver's causal past. The three-way pin (slot-kind set, jurisdiction equality, `set(tgt) == _slot_maxima(pre_state)`) rejects every variant, and the honest resolver naming exactly the forks still resolves. **Held** — the fix is real, not merely a deadlock.
4. **Late-signature flip of a pinned CID (surface #4, first half).** The CID covers the exact AW bytes; an extra or late signature yields a different AW set and a different CID, leaving the pinned CID's verdict untouched (suite test 5 proves this). My F6 is a *different* retroactivity channel — the verifier's cut, not the witness set — so this specific attack is **refuted** even though F6 stands.
5. **Compromised old key revoking an emergency rotation (surface #5).** Scenario: victim's K0 is compromised, a quorum emergency-rotates the victim to `K_new`, and the attacker tries to supersede the recovery rotation using K0. Any supersede `S` of `R` must descend `R`, so `preState(S)` already binds the victim to `K_new`; `has_self` with K0 fails. The recovery path survives old-key compromise. **Held.**
6. **`may_reverse` totality and malformed-input handling (surface #3, first half).** I enumerated the `(prior.kind × new)` product independently; every triple returns exactly one Boolean and malformed capabilities fail closed. Totality **holds** — the liveness cost of the fail-closed default is real but lives in the resolver path, which is finding F7, not a hole in the table.
7. **`dist` fixpoint termination (surface #1).** Distances only shrink toward the min-path and are bounded below by 0, so the `_compute_admits` iteration is monotone and terminates. **Held.**
8. **Self-supersede (`S` targets `S`).** Excluded by the strict-descent rule; no self-negation is constructible. **Held.**
9. **Historical `policy_ref` laundering in `may_reverse`.** `_prove_supersede_cap` sets `policy_ref` to the pre-state policy value and `may_reverse` compares it against `current_JP(prestate)` at the same pre-state — they match by construction, so a supersede cannot cite a superseded policy to authorize a reversal. **Held.**

*Reviewed by an independent adversarial gate reviewer per the rev-7 brief. All findings above were confirmed by the harness transcripts; no reproduction failed.*

---

## Appendix A — machine-executed reproductions (verbatim)

### [2] F1 — conflicted key slot is fail-open — the CONFLICT marker binds as a key (P0)

```python
import model
from model import World, Rec, Model

w = World(pinned_roots={"J": {"g"}},
          pinned_policy={"J": (frozenset({"A", "B"}), 2)},
          pinned_keys={"A": {"K0"}, "B": {"kB"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "K0")))
w.add(Rec("R1", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A",
          rot_key="K1", incoming_pop=("A", "K1"), filing=("A", "K0")))
w.add(Rec("R2", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A",
          rot_key="K2", incoming_pop=("A", "K2"), filing=("A", "K0")))
# two valid, DAG-unordered rotations => A's key-slot derives to CONFLICT ("UNUSABLE", D.2b)
w.add(Rec("X", frozenset({"R1", "R2"}), "A", "ordinary", jur="J",
          filing=("A", model.CONFLICT)))                     # 'signature' = the conflict marker
w.add(Rec("PS", frozenset({"R1", "R2"}), "B", "policy-succession", jur="J",
          new_policy=(frozenset({"B"}), 1),
          threshold=frozenset({("A", model.CONFLICT), ("B", "kB")})))
m = Model(w, frozenset(w.recs), "J")

keys = m._key_state(frozenset(m.recs))
assert keys["A"] == model.CONFLICT, "premise: slot must be conflicted"
assert m.valid_cap("R1") and m.valid_cap("R2")
# the real keys no longer bind (the slot is genuinely unusable for A) ...
assert not m._bound("A", "K1", keys) and not m._bound("A", "K2", keys)
# ... but the CONFLICT marker itself binds, for ANYONE who presents it:
assert m._bound("A", model.CONFLICT, keys)
# (1) an ordinary record 'authorized' by the marker is valid_cap AND effective
assert m.valid_cap("X")
assert m.effective("X")
# (2) the marker counts toward the governance threshold: full policy seizure
assert m.valid_cap("PS")
assert m.current_JP(frozenset(m.recs))[0] == (frozenset({"B"}), 1)
print("VIOLATION: §D.2b 'slot UNUSABLE' — a conflicted key-slot is fail-open: _bound and "
      "_threshold_ok compare a presented key against the CONFLICT marker itself, so anyone "
      "can 'sign as' the conflicted actor — an ordinary record computes effective and the "
      "2-of-2 governance threshold is satisfied (policy seized)")
```

```
### repro F1 [P0] conflicted key slot is fail-open — the CONFLICT marker binds as a key
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.2b 'slot UNUSABLE' — a conflicted key-slot is fail-open: _bound and _threshold_ok compare a presented key against the CONFLICT marker itself, so anyone can 'sign as' the conflicted actor — an ordinary record computes effective and the 2-of-2 governance threshold is satisfied (policy seized)

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F2 — absent key binds — a keyless actor's null key satisfies filings, thresholds, checkpoint sets (P0)

```python
import model
from model import World, Rec, Model

w = World(pinned_roots={"J": {"g"}},
          pinned_policy={"J": (frozenset({"A", "Z"}), 2)},   # Z is IN the 2-of-2 policy ...
          pinned_keys={"A": {"kA"}})                          # ... but has NO key anywhere
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
w.add(Rec("X1", frozenset({"g"}), "Z", "ordinary", jur="J", filing=("Z", None)))
w.add(Rec("PS", frozenset({"g"}), "A", "policy-succession", jur="J",
          new_policy=(frozenset({"A"}), 1),
          threshold=frozenset({("A", "kA"), ("Z", None)})))  # one real signature + one null
m = Model(w, frozenset(w.recs), "J")

keys = m._key_state(frozenset({"g"}))
assert "Z" not in keys, "premise: Z has no bound key at all"
assert m._bound("Z", None, keys)                  # absence compares equal to a presented null
assert m.valid_cap("X1") and m.effective("X1")    # a record 'authorized' by nobody's key
assert m.valid_cap("PS")                          # 2-of-2 policy amended with ONE real signature
assert m.current_JP(frozenset(m.recs))[0] == (frozenset({"A"}), 1)

# the same null witness counts toward a checkpoint authorization set
state = {"J": "J", "sequence": 1, "frontier": ("g",), "effective_set_root": ("e",),
         "key_state_root": ("k",), "policy_state_root": ("p",), "manifest_root": ("m",)}
m_g = Model(w, frozenset({"g"}), "J")
assert model.checkpoint_authorized(state, frozenset({("A", "kA"), ("Z", None)}), m_g)
print("VIOLATION: §D.1 'BOUND iff the actor's key in the pre-state key-state' — an actor with "
      "NO key binds the null key: keystate.get(actor) is None and None==None, so keyless actors "
      "author effective records, satisfy governance thresholds (2-of-2 met with one real "
      "signature) and count toward checkpoint authorization sets — fail-open on absence")
```

```
### repro F2 [P0] absent key binds — a keyless actor's null key satisfies filings, thresholds, checkpoint sets
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.1 'BOUND iff the actor's key in the pre-state key-state' — an actor with NO key binds the null key: keystate.get(actor) is None and None==None, so keyless actors author effective records, satisfy governance thresholds (2-of-2 met with one real signature) and count toward checkpoint authorization sets — fail-open on absence

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F3 — resolver-REJECTED policy branch permanently censors an adopted root via layer-2a reversal (P0)

```python
import model
from model import World, Rec, Model

P0 = (frozenset({"A", "B", "C"}), 2)
P1 = (frozenset({"A"}), 1)
P2 = (frozenset({"B", "C"}), 2)

def world(with_s1_attack=True, with_repairs=False):
    w = World(pinned_roots={"J": {"RA"}}, pinned_policy={"J": P0},
              pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}, "X": {"kX"}})
    w.add(Rec("RA", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
    w.add(Rec("RB", frozenset(), "X", "ordinary", jur="J", filing=("X", "kX")))
    w.add(Rec("RBC", frozenset({"RB"}), "X", "ordinary", jur="J", filing=("X", "kX")))
    w.add(Rec("D", frozenset({"RA"}), "B", "root-adoption", jur="J", subject="RB",
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    # honest governance fork: two P0-quorums propose P1 and P2
    w.add(Rec("s1", frozenset({"RA"}), "A", "policy-succession", jur="J", new_policy=P1,
              threshold=frozenset({("A", "kA"), ("B", "kB")})))
    w.add(Rec("s2", frozenset({"RA"}), "B", "policy-succession", jur="J", new_policy=P2,
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    # the resolver selects P2: s1's branch LOSES
    w.add(Rec("res", frozenset({"s1", "s2"}), "B", "policy-resolution", jur="J",
              new_policy=P2, resolves=frozenset({"s1", "s2"}),
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    if with_s1_attack:
        # on the DEAD branch, A alone (P1 = ({A},1)) supersedes the adoption of RB
        w.add(Rec("S1", frozenset({"s1"}), "A", "supersede", jur="J", subject="D",
                  threshold=frozenset({("A", "kA")})))
    if with_repairs:
        # the legitimate (P2) quorum revokes A's censoring supersede ...
        w.add(Rec("S2", frozenset({"res", "S1"}), "B", "supersede", jur="J", subject="S1",
                  threshold=frozenset({("B", "kB"), ("C", "kC")})))
        # ... and re-adopts RB
        w.add(Rec("D2", frozenset({"res"}), "B", "root-adoption", jur="J", subject="RB",
                  threshold=frozenset({("B", "kB"), ("C", "kC")})))
    return w

w0 = world(with_s1_attack=False)
m_clean = Model(w0, frozenset(w0.recs), "J")
assert "RB" in m_clean.admits() and m_clean.effective("RBC")     # control: no attack, branch lives

w = world()
m = Model(w, frozenset(w.recs), "J")
assert m.in_lineage("s1") is False                       # the resolver REJECTED s1's branch
assert m.current_JP(frozenset(m.recs))[0] == P2          # governance moved on
assert m.valid_cap("S1")                                 # yet the dead-branch supersede is valid_cap
assert not model.descends("S1", "D", m.recs)             # it never even descends its target
assert "RB" not in m.admits()                            # ... and it censors the root anyway
assert not m.effective("RBC")

# permanence: revoking the censor and re-adopting changes NOTHING (reversal reads valid_cap only)
w2 = world(with_repairs=True)
m2 = Model(w2, frozenset(w2.recs), "J")
assert m2.valid_cap("S2") and m2.valid_cap("D2")
assert not m2.effective("S1")                            # the censoring supersede is itself revoked
assert "RB" not in m2.admits()                           # RB stays censored forever
assert not m2.effective("RBC")
print("VIOLATION: §D.2a reversed() × §D.2b gating — layer-2a admission reads valid_cap ONLY: "
      "a supersede authorized solely by a resolver-REJECTED policy branch (which never even "
      "descends its target) reverses an adoption; revoking the censor and re-adopting cannot "
      "restore admission. A dead branch permanently censors a root and every record on it")
```

```
### repro F3 [P0] resolver-REJECTED policy branch permanently censors an adopted root via layer-2a reversal
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.2a reversed() × §D.2b gating — layer-2a admission reads valid_cap ONLY: a supersede authorized solely by a resolver-REJECTED policy branch (which never even descends its target) reverses an adoption; revoking the censor and re-adopting cannot restore admission. A dead branch permanently censors a root and every record on it

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F4 — resolver-REJECTED branch admits an unauthorized root (dual of F3) (P1)

```python
import model
from model import World, Rec, Model

P0 = (frozenset({"A", "B", "C"}), 2)
P1 = (frozenset({"A"}), 1)
P2 = (frozenset({"B", "C"}), 2)

def world(with_bad_adoption):
    w = World(pinned_roots={"J": {"RA"}}, pinned_policy={"J": P0},
              pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}, "X": {"kX"}})
    w.add(Rec("RA", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
    w.add(Rec("RB2", frozenset(), "X", "ordinary", jur="J", filing=("X", "kX")))
    w.add(Rec("RBC2", frozenset({"RB2"}), "X", "ordinary", jur="J", filing=("X", "kX")))
    w.add(Rec("s1", frozenset({"RA"}), "A", "policy-succession", jur="J", new_policy=P1,
              threshold=frozenset({("A", "kA"), ("B", "kB")})))
    w.add(Rec("s2", frozenset({"RA"}), "B", "policy-succession", jur="J", new_policy=P2,
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    w.add(Rec("res", frozenset({"s1", "s2"}), "B", "policy-resolution", jur="J",
              new_policy=P2, resolves=frozenset({"s1", "s2"}),
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    if with_bad_adoption:
        # A alone, under the DEAD branch's policy P1=({A},1), 'adopts' a foreign root
        w.add(Rec("Dbad", frozenset({"s1"}), "A", "root-adoption", jur="J", subject="RB2",
                  threshold=frozenset({("A", "kA")})))
    return w

w0 = world(False)
m0 = Model(w0, frozenset(w0.recs), "J")
assert "RB2" not in m0.admits() and not m0.effective("RBC2")   # control: no adoption, no life

w = world(True)
m = Model(w, frozenset(w.recs), "J")
assert m.in_lineage("s1") is False                     # s1's branch was REJECTED by the resolver
assert m.current_JP(frozenset(m.recs))[0] == P2        # the winning governance never adopted RB2
assert m.valid_cap("Dbad")                             # yet the dead-branch adoption is valid_cap
assert "RB2" in m.admits()                             # ... and admits the root
assert m.effective("RBC2")                             # ... making its records effective
print("VIOLATION: §D.2a dist() × §D.2b gating — root ADMISSION also reads valid_cap only: an "
      "adoption authorized solely under a resolver-REJECTED policy branch admits a root the "
      "selected governance never adopted, and records on it compute effective")
```

```
### repro F4 [P1] resolver-REJECTED branch admits an unauthorized root (dual of F3)
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.2a dist() × §D.2b gating — root ADMISSION also reads valid_cap only: an adoption authorized solely under a resolver-REJECTED policy branch admits a root the selected governance never adopted, and records on it compute effective

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F5 — losing branch re-enters selected lineage once history advances past the resolver (P1)

```python
import model
from model import World, Rec, Model

P0 = (frozenset({"A", "B"}), 2)
P1 = (frozenset({"A", "C"}), 2)
P2 = (frozenset({"B", "C"}), 2)
P3 = (frozenset({"C"}), 1)

w = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": P0},
          pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
w.add(Rec("s1", frozenset({"g"}), "A", "policy-succession", jur="J", new_policy=P1,
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
w.add(Rec("s2", frozenset({"g"}), "A", "policy-succession", jur="J", new_policy=P2,
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
w.add(Rec("res", frozenset({"s1", "s2"}), "A", "policy-resolution", jur="J",
          new_policy=P2, resolves=frozenset({"s1", "s2"}),
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
# history advances: the resolved policy P2 validly succeeds to P3, descending the resolver
w.add(Rec("s3", frozenset({"res"}), "C", "policy-succession", jur="J", new_policy=P3,
          threshold=frozenset({("B", "kB"), ("C", "kC")})))

m_tip = Model(w, frozenset({"g", "s1", "s2", "res"}), "J")
assert m_tip.in_lineage("s1") is False      # the suite's pinned property, at the resolver tip

m = Model(w, frozenset(w.recs), "J")
assert m.valid_cap("s3")
assert m.current_JP(frozenset(m.recs))[0] == P3
# the single-maximal path returns closure(s3) ∩ successions — which contains BOTH forks:
assert "s1" in m.selected_lineage_policy()
assert m.in_lineage("s1") is True            # the REJECTED succession is back in the lineage
assert m.effective("s1")                     # ... and computes effective
print("VIOLATION: §D.2b 'a losing policy branch is gated by in_lineage' — the gate holds only "
      "at the tip: once a later succession descends the resolver, selected_lineage_policy's "
      "single-maximal path returns closure(maximal), which contains BOTH forks; the rejected "
      "s1 re-enters the selected lineage and computes effective (non-monotone gating)")
```

```
### repro F5 [P1] losing branch re-enters selected lineage once history advances past the resolver
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.2b 'a losing policy branch is gated by in_lineage' — the gate holds only at the tip: once a later succession descends the resolver, selected_lineage_policy's single-maximal path returns closure(maximal), which contains BOTH forks; the rejected s1 re-enters the selected lineage and computes effective (non-monotone gating)

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F6 — checkpoint authorization reads the verifier's cut, not cut(P.frontier) — verdicts flip retroactively both ways (P1)

```python
import model
from model import World, Rec, Model

# ---- direction 1: a routine signer key-rotation retroactively KILLS a pinned checkpoint
wA = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": (frozenset({"A", "B"}), 2)},
           pinned_keys={"A": {"kA"}, "B": {"kB"}})
wA.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
wA.add(Rec("R", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A", rot_key="kA2",
           incoming_pop=("A", "kA2"), filing=("A", "kA")))   # A's routine rotation kA -> kA2
state = {"J": "J", "sequence": 1, "frontier": ("g",), "effective_set_root": ("e",),
         "key_state_root": ("k",), "policy_state_root": ("p",), "manifest_root": ("m",)}
aw = frozenset({("A", "kA"), ("B", "kB")})
cid = model.checkpoint_CID(state, aw)                        # the PINNED checkpoint identity
m_at = Model(wA, frozenset({"g"}), "J")
m_later = Model(wA, frozenset({"g", "R"}), "J")
assert model.checkpoint_authorized(state, aw, m_at) is True      # authorized at the frontier
assert model.checkpoint_authorized(state, aw, m_later) is False  # same CID, same sigs -> rejected

# ---- direction 2: a below-threshold auth set becomes authorized after a policy change
wB = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": (frozenset({"A", "B"}), 2)},
           pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}, "D": {"kD"}})
wB.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
wB.add(Rec("s", frozenset({"g"}), "A", "policy-succession", jur="J",
           new_policy=(frozenset({"C", "D"}), 2),
           threshold=frozenset({("A", "kA"), ("B", "kB")})))
aw2 = frozenset({("C", "kC"), ("D", "kD")})
m_before = Model(wB, frozenset({"g"}), "J")
m_after = Model(wB, frozenset({"g", "s"}), "J")
assert model.checkpoint_authorized(state, aw2, m_before) is False  # NOT authorized at the frontier
assert model.checkpoint_authorized(state, aw2, m_after) is True    # ... authorized retroactively
print("VIOLATION: §D.5 verify must 'rebuild cut(P.frontier); derive current_JP(J)' — the "
      "machine derives policy and key-state from the VERIFIER's cut, so a pinned CID's "
      "authorization flips retroactively in both directions: a signer rotation kills a frozen "
      "checkpoint, and a below-threshold set gains authorization after a policy change. "
      "Not immutable, not consumer-independent")
```

```
### repro F6 [P1] checkpoint authorization reads the verifier's cut, not cut(P.frontier) — verdicts flip retroactively both ways
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.5 verify must 'rebuild cut(P.frontier); derive current_JP(J)' — the machine derives policy and key-state from the VERIFIER's cut, so a pinned CID's authorization flips retroactively in both directions: a signer rotation kills a frozen checkpoint, and a below-threshold set gains authorization after a policy change. Not immutable, not consumer-independent

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F7 — two competing resolvers permanently brick the jurisdiction; a unanimous re-resolution is impotent (P1)

```python
import model
from model import World, Rec, Model

P0 = (frozenset({"A", "B", "C"}), 2)
P1 = (frozenset({"A", "B"}), 2)
P2 = (frozenset({"A", "C"}), 2)

w = World(pinned_roots={"J": {"RA"}}, pinned_policy={"J": P0},
          pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}})
w.add(Rec("RA", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
w.add(Rec("s1", frozenset({"RA"}), "A", "policy-succession", jur="J", new_policy=P1,
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
w.add(Rec("s2", frozenset({"RA"}), "A", "policy-succession", jur="J", new_policy=P2,
          threshold=frozenset({("A", "kA"), ("C", "kC")})))
# two quorums, each honest under P0, resolve the same fork differently
w.add(Rec("res1", frozenset({"s1", "s2"}), "A", "policy-resolution", jur="J",
          new_policy=P1, resolves=frozenset({"s1", "s2"}),
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
w.add(Rec("res2", frozenset({"s1", "s2"}), "A", "policy-resolution", jur="J",
          new_policy=P2, resolves=frozenset({"s1", "s2"}),
          threshold=frozenset({("A", "kA"), ("C", "kC")})))
# the whole electorate then tries to settle it UNANIMOUSLY
w.add(Rec("res3", frozenset({"res1", "res2"}), "A", "policy-resolution", jur="J",
          new_policy=P1, resolves=frozenset({"s1", "s2"}),
          threshold=frozenset({("A", "kA"), ("B", "kB"), ("C", "kC")})))
# ... or to resolve the resolvers themselves
w.add(Rec("res4", frozenset({"res1", "res2"}), "A", "policy-resolution", jur="J",
          new_policy=P1, resolves=frozenset({"s1", "s2", "res1", "res2"}),
          threshold=frozenset({("A", "kA"), ("B", "kB"), ("C", "kC")})))
# ... or to simply succeed the policy under the bricked state
w.add(Rec("s3", frozenset({"res3"}), "A", "policy-succession", jur="J", new_policy=P1,
          threshold=frozenset({("A", "kA"), ("B", "kB"), ("C", "kC")})))
m = Model(w, frozenset(w.recs), "J")

assert m.valid_cap("res1") and m.valid_cap("res2")
assert m.current_JP(frozenset({"RA", "s1", "s2", "res1", "res2"})) is None  # conflicted
# every recovery path is closed:
assert m.valid_cap("res3")                        # a UNANIMOUS resolver is valid_cap ...
assert m.current_JP(frozenset(m.recs)) is None    # ... and changes NOTHING (3 resolvers -> conflict)
assert not m.valid_cap("res4")                    # resolver-of-resolvers rejected (maxima = successions only)
assert not m.valid_cap("s3")                      # no succession authorizable under a conflicted policy
print("VIOLATION: §D.2b 'a valid_cap resolver ... selects one branch' is non-recoverable: two "
      "competing valid resolvers brick the policy slot, and the conflict rule only ever counts "
      "MORE resolvers — a subsequent unanimous resolution is valid_cap yet impotent, and no "
      "succession can ever be authorized again. One governance race = permanent jurisdiction "
      "deadlock (the fail-closed default fails dead)")
```

```
### repro F7 [P1] two competing resolvers permanently brick the jurisdiction; a unanimous re-resolution is impotent
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.2b 'a valid_cap resolver ... selects one branch' is non-recoverable: two competing valid resolvers brick the policy slot, and the conflict rule only ever counts MORE resolvers — a subsequent unanimous resolution is valid_cap yet impotent, and no succession can ever be authorized again. One governance race = permanent jurisdiction deadlock (the fail-closed default fails dead)

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F8 — checkpoint_authorized never binds witnesses to the state (the state argument is unused) (P2)

```python
import model
from model import World, Rec, Model

w = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": (frozenset({"A", "B"}), 2)},
          pinned_keys={"A": {"kA"}, "B": {"kB"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
m = Model(w, frozenset(w.recs), "J")

honest = {"J": "J", "sequence": 1, "frontier": ("g",), "effective_set_root": ("honest",),
          "key_state_root": ("k",), "policy_state_root": ("p",), "manifest_root": ("m",)}
forged = {"J": "J", "sequence": 1, "frontier": ("g",), "effective_set_root": ("attacker",),
          "key_state_root": ("k2",), "policy_state_root": ("p2",), "manifest_root": ("m2",)}
aw = frozenset({("A", "kA"), ("B", "kB")})

# the witnesses' AW bytes cover honest's P and ONLY honest's P:
assert model.checkpoint_CID(forged, aw) != model.checkpoint_CID(honest, aw)
# ... yet the authorization oracle vouches for the forged pairing, because it never
# looks at the state at all:
assert model.checkpoint_authorized(forged, aw, m) is True
print("VIOLATION: §D.5 verify(CID) must 'check sig_i-over-P by a key bound to actor_i' — "
      "checkpoint_authorized ignores its state argument entirely, so any policy-satisfying "
      "AW set is accepted as attesting ANY state blob; the certificate's content is unbound "
      "from its signatures at the verification layer (only an external CID comparison saves it)")
```

```
### repro F8 [P2] checkpoint_authorized never binds witnesses to the state (the state argument is unused)
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.5 verify(CID) must 'check sig_i-over-P by a key bound to actor_i' — checkpoint_authorized ignores its state argument entirely, so any policy-satisfying AW set is accepted as attesting ANY state blob; the certificate's content is unbound from its signatures at the verification layer (only an external CID comparison saves it)

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F9 — record actor and filing witness are never tied — authorization and identity detach (P2)

```python
import model
from model import World, Rec, Model, Cap

w = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": (frozenset({"A", "B"}), 2)},
          pinned_keys={"A": {"kA"}, "B": {"kB"}, "Mallory": {"kM"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
# a record naming Mallory as actor, authorized by ALICE's bound key
w.add(Rec("x", frozenset({"g"}), "Mallory", "ordinary", jur="J", filing=("A", "kA")))
w.add(Rec("S_alice", frozenset({"x"}), "A", "supersede", jur="J", subject="x",
          filing=("A", "kA")))
w.add(Rec("S_mal", frozenset({"x"}), "Mallory", "supersede", jur="J", subject="x",
          filing=("Mallory", "kM")))

m0 = Model(w, frozenset({"g", "x"}), "J")
assert m0.valid_cap("x") and m0.effective("x")          # the machine accepts the record
assert m0.recs["x"].actor == "Mallory" and m0.recs["x"].filing == ("A", "kA")
assert m0.carried_cap("x") == Cap("SELF", "Mallory", "J", ("record", "x"))

m1 = Model(w, frozenset(w.recs), "J")
assert not m1.valid_cap("S_alice")   # Alice, whose key AUTHORIZED x, cannot revoke it
assert m1.valid_cap("S_mal")         # Mallory, who signed NOTHING, holds the SELF right over it
print("VIOLATION: §D.1/§D.3 'bound actor-filing' — the machine checks that SOME key is bound, "
      "never that it is the record actor's: a record filed 'by' Mallory is authorized by "
      "Alice's key; the SELF capability and revocation rights attach to the non-signing actor "
      "while the actual authorizer cannot reverse it")
```

```
### repro F9 [P2] record actor and filing witness are never tied — authorization and identity detach
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.1/§D.3 'bound actor-filing' — the machine checks that SOME key is bound, never that it is the record actor's: a record filed 'by' Mallory is authorized by Alice's key; the SELF capability and revocation rights attach to the non-signing actor while the actual authorizer cannot reverse it

--- stderr ---
(empty)
--- exit: 0 ---
```

### [2] F10 — duplicate (J,sequence) CIDs from disjoint honest quorums — no consumer-independent tie-break (P2)

```python
import model
from model import World, Rec, Model

w = World(pinned_roots={"J": {"g"}},
          pinned_policy={"J": (frozenset({"A", "B", "C", "D"}), 2)},
          pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}, "D": {"kD"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
m = Model(w, frozenset(w.recs), "J")

base = {"J": "J", "sequence": 7, "effective_set_root": ("e",), "key_state_root": ("k",),
        "policy_state_root": ("p",), "manifest_root": ("m",)}
st1 = dict(base, frontier=("f1",))
st2 = dict(base, frontier=("f2",))          # same (J, sequence), different frontier
aw1 = frozenset({("A", "kA"), ("B", "kB")})
aw2 = frozenset({("C", "kC"), ("D", "kD")}) # DISJOINT quorum: no signer equivocated
cid1, cid2 = model.checkpoint_CID(st1, aw1), model.checkpoint_CID(st2, aw2)

assert cid1 != cid2
assert not {a for a, _ in aw1} & {a for a, _ in aw2}
assert model.checkpoint_authorized(st1, aw1, m) is True
assert model.checkpoint_authorized(st2, aw2, m) is True
# both CIDs verify; the machine exposes no consumer-independent rule to prefer one
print("VIOLATION: §D.5 'CID ... THE checkpoint identity' / 'consumer-independent — no successor "
      "is needed to freeze it': one (J, sequence) yields two valid CIDs over different frontiers "
      "from DISJOINT honest quorums (2-of-4, zero equivocation); the only disambiguation §D.5 "
      "offers is 'a certificate descending both' — i.e. a successor, the exact dependency the "
      "design claims to have eliminated")
```

```
### repro F10 [P2] duplicate (J,sequence) CIDs from disjoint honest quorums — no consumer-independent tie-break
HARNESS VERDICT: REPRODUCED — exited 0 and printed VIOLATION
--- stdout ---
VIOLATION: §D.5 'CID ... THE checkpoint identity' / 'consumer-independent — no successor is needed to freeze it': one (J, sequence) yields two valid CIDs over different frontiers from DISJOINT honest quorums (2-of-4, zero equivocation); the only disambiguation §D.5 offers is 'a certificate descending both' — i.e. a successor, the exact dependency the design claims to have eliminated

--- stderr ---
(empty)
--- exit: 0 ---
```


---

## Appendix B — earlier rounds (unedited)

### round 1 — blind attack

Let me carefully study this model. I need to find executable counter-vectors against `model.py` that violate §D.

Let me go through the machine carefully.

Key components:

1. `Rec` — records with kinds: ordinary, rotation, supersede, policy-succession, root-adoption, key-resolution, policy-resolution.

2. `Model.__init__`: computes `valid_cap` per record in topo order, then `admits`, then `effective` on demand with memoization and recursion guard.

3. Layer 1 `valid_cap`:
   - ordinary: filing bound in pre-state keys.
   - root-adoption: threshold ok under current policy at pre-state.
   - policy-succession: threshold ok.
   - resolutions: exact maxima check, then threshold against common-ancestor policy.
   - rotation: PoP required; threshold by policy OR self-rotation with bound key.
   - supersede: `_prove_supersede_cap` returns a cap C such that `may_reverse(C, tcap, model, E, subject)`.

4. Layer 2a `admits`: distance fixpoint over adoptions; reversals for supersede of adoption with JP cap and auth_dist 0 < dist(B).

5. Layer 2b `selected_lineage_policy`, `in_lineage`.

6. Layer 3 `effective`: active_cut ∧ valid_cap ∧ in_lineage ∧ no effective valid_cap supersede S descending w with may_reverse(carried_cap(S), carried_cap(w), preState(S)).

Now, attack surface. Let me look for bugs.

**Attack idea 1: `may_reverse` for JP prior — `policy_ref` check.**

In `may_reverse`:

```python
if prior.kind == "JP":
    return (new.kind == "JP" and new.jur == prior.jur
            and _same_policy_lineage(...)
            and new.policy_ref == (model.current_JP(prestate) or (None,))[0])
```

Note `current_JP` returns `(pol, pid)` tuple; `or (None,)` — if `current_JP` returns None (conflict), then `(None,)[0]` is None. So `new.policy_ref == None` would be required. Hmm, if policy is conflicted at prestate, `current_JP` returns None, so the required policy_ref is None. A cap with `policy_ref=None` would then pass? But wait — for a supersede to be valid_cap, `_prove_supersede_cap` must return a cap. In `_prove_supersede_cap`, `has_threshold()` uses `polv` which is None if conflicted; `_threshold_ok(None)` returns False. So threshold-based cands wouldn't be added when conflicted. OK.

But consider `prior.kind == "SELF"` and `new.kind == "JP"`: requires `new.policy_ref == current_JP(prestate)[0]`. The cap candidate built in `_prove_supersede_cap` for JP is `Cap("JP", ("pol", self.J), self.J, ("gov", self.J), policy_ref=polv)` where polv is the pre-state policy value. So that matches by construction if has_threshold passed.

**Attack idea 2: `_prove_supersede_cap` for target kind "ordinary" — `has_self(target.actor)` allows the target's actor to supersede their own record. But also `has_threshold()` gives JP cap. What about a supersede of an ordinary record by a *different* actor with SELF? `has_self(target.actor)` requires `r.filing[0] == target.actor`. So only the same actor. OK.

**Attack idea 3: supersede of a rotation target.** 

```python
elif target.kind == "rotation":
    slot = ("key", target.rot_actor)
    if has_threshold() or has_self(target.rot_actor):
        cands.append(Cap("RP", ("keypol", self.J), self.J, slot, policy_ref=polv))
```

So if the *slot actor* (target.rot_actor) files a supersede of the rotation with their own bound key, they get an RP cap with principal `("keypol", J)`. Then `may_reverse(RP_cap, tcap, ...)` where tcap = carried_cap(target rotation) = `Cap("RP", ("keypol", J), J, ("key", rot_actor))`. RP vs RP: `new.kind == "RP" and new.jur == prior.jur and new.slot == prior.slot` → True. So a slot actor can revoke their own rotation. That seems intended ("RP satisfied by the slot actor's own bound key" was found as a real defect and... wait, the brief says "The model found 'RP satisfied by the slot actor's own bound key' as a real defect." Hmm — it says the model found this as a real defect, but looking at the code, `has_self(target.rot_actor)` still grants the RP cap. Wait, let me re-read.

Brief §5: "The model found 'RP satisfied by the slot actor's own bound key' as a real defect. Look for its siblings: any place a predicate is satisfiable by the entity it is meant to constrain."

Hmm, but the code at `_prove_supersede_cap` for rotation targets: `if has_threshold() or has_self(target.rot_actor)`. So a supersede of a rotation record is authorized if the rotation's *target actor* signs it with their bound key. Is that a defect or intended? If Alice's key was rotated from K0 to K1 (maybe by emergency quorum), can Alice supersede that rotation with... which key? `has_self(target.rot_actor)` checks `r.filing = (rot_actor, key)` bound in pre-state keys — the pre-state of the supersede, which is *after* the rotation (since supersede must descend the rotation per the causal rule in `effective`; but valid_cap doesn't require descent! Let me check).

Actually wait — does `valid_cap` of a supersede require the supersede to causally descend its target? In `_compute_valid_cap` for supersede: `_prove_supersede_cap(w, E, keys, polv)` where E = pre_events(w). The target is `self.recs.get(r.subject)`. The target record is looked up in `self.recs` (the whole cut), not necessarily in E. The cap is computed against E's key state. The target's `carried_cap` is computed via `self.carried_cap(r.subject)` which uses the *whole cut* state... Actually `carried_cap` for ordinary just constructs the cap. For a supersede target, it recurses into `_prove_supersede_cap` with the target's pre-events.

Interesting: a supersede S that does NOT descend its target T. Then in `effective(w)` for w=T: `if not descends(s, w, self.recs): continue` — the §5 causal rule skips it. So non-descending supersedes are ignored in effective. But `valid_cap(S)` might still be True, and S could itself be effective and supersede other things.

But more interesting: can a supersede be valid_cap based on a *future* state? The keys are from pre_events(S). The target's carried_cap doesn't depend on S's pre-state. Hmm.

**Attack idea 4: The key-state normalization bug.**

```python
out = dict(self.w.pinned_keys)
out = {a: (next(iter(ks)) if len(ks) == 1 else CONFLICT) for a, ks in out.items()}
```

If an actor has 2 pinned keys, it's CONFLICT. Fine.

**Attack idea 5: `_key_state` — rotations by actor, `_resolve_slot` with `base=out.get(actor)`.**

`_resolve_slot(E, ws, base, base_id, ...)`: if no transitions → base. If single maximal → value. If multiple maxima → look for resolvers.

Wait — there's a subtle bug in `_resolve_slot`: when there's exactly one maximal transition, it returns that value, ignoring whether the transition's *validity*... no, transitions are pre-filtered by `self._valid.get(w)`. OK.

But here's something: `_key_state` iterates `by_actor` and for each actor with rotations resolves the slot. But what about an actor whose pinned key exists and has no rotations → stays pinned. Fine.

**Attack idea 6: rotation `valid_cap` — threshold OR self-rotation. The self-rotation path:**

```python
return bool(r.filing and r.filing[0] == r.rot_actor and self._bound(*r.filing, keys))
```

`r.filing = (rot_actor, key)` and bound in pre-state keys. So the *outgoing* key authorizes. Fine.

But the threshold path: `self._threshold_ok(r.threshold, polv, keys)` — threshold by the *jurisdiction policy* (JP). The brief says RP = rotation policy for a key-slot. But the model only has one policy per J (`pinned_policy` / policy-succession) used both for governance AND rotation authorization. So there's no separate RP. That's a modeling simplification.

**Attack idea 7: THE BIG ONE — `effective` memoization and the recursion guard across queries.**

`effective(w)` memoizes `self._eff`. The recursion guard raises on cycle. But the order of evaluation might matter: `effective(x)` iterates over all supersedes S of x and recursively evaluates `effective(S)`. `effective(S)` in turn looks at supersedes of S. Since supersedes must descend their targets (causal rule), the recursion goes strictly deeper in causal order... wait, S descends x, and supersedes S' of S must descend S, so depth strictly increases. So well-founded. OK.

BUT: `effective(w)` breaks out of the loop on the first supersede that reverses w (`ok = False; break`). Fine.

However — memoization combined with exceptions: if `effective` raises RuntimeError mid-evaluation, `self._eff` may contain partially computed values? No, values are only set at the end. OK.

**Attack idea 8: order-independence of `effective`.** The set `effective_set()` iterates `self.recs` and calls `effective(w)`. The result shouldn't depend on order due to memoization being correct... presumably fine.

**Attack idea 9: `active_cut` for ordinary records uses pre-state key binding — but not `in_lineage` for the key. Actually `active_cut` checks root_reachable and bound filing. `effective` = active_cut ∧ valid_cap ∧ in_lineage ∧ ¬reversed. For ordinary, valid_cap = bound filing, same as active_cut's second condition. in_lineage(ordinary) returns True always ("ordinary/rotation/supersede gated via their basis in effective()"). Hmm — comment says gated via their basis but I don't see basis gating for ordinary records. Whatever.

**Attack idea 10: The `_compute_admits` fixpoint — "monotone: distances only shrink toward min-path".**

dist starts at pinned roots with 0. For each adoption w targeting B: d_adopt = min dist of roots of w (roots of the adoption record's closure — records in the closure with no priors *within the cut*). Then nd = d_adopt+1; if nd < dist[B], update.

Hmm — `_root_of(w)` returns roots = records in closure(w) with no priors in the cut. For an adoption D with prior {A} where A pinned: roots = {A}, dist 0 → B gets dist 1.

Now the reversal: supersede of adoption D targeting B (tgt.subject = B; note r.subject = D, tgt = D, B = tgt.subject). Cap must be JP. auth_dist = 0 always ("modeled as the adopting jurisdiction anchor"). So any valid_cap JP supersede of an adoption reverses it if 0 < dist(B). If dist(B) is ∞ (not yet adopted) then no reversal. Fine.

But here's the thing: the reversal doesn't require the supersede S to be *effective* or even reachable — just valid_cap. And per §D.2a: "reversed(r) := ∃ valid_cap S superseding an adoption D that targets r, with cap(S).kind = JP ∧ ..." — yes, valid_cap only. So an *ineffective* supersede (e.g., itself superseded later) still reverses the adoption permanently. Is that per spec? §D.2a says `∃ valid_cap S` — yes, only valid_cap. So a revoked revocation still revokes the adoption. Hmm, that could be a finding: a JP supersede of an adoption that is itself later superseded (un-revoked) still excludes the root from admits. But §D literally says valid_cap only. It says "Uses valid_cap of adoptions (permanent) — not lifecycle effective — so the oscillation cannot form." For reversals it also says valid_cap. So it's per-spec. But is it a spec bug? The question is whether it creates a censorship primitive or liveness issue: an adoption D of root B; a JP quorum supersedes D (S1, valid_cap); then JP quorum supersedes S1 (S2, valid_cap, JP vs JP same policy lineage → may_reverse true). Now S1 is ineffective, but B remains excluded from admits forever, because reversed(B) only needs valid_cap(S1). No record can ever re-admit B... well, actually a *new* adoption D2 of B would give dist(B) again — wait, dist(B) is computed from adoptions; if D2 is valid_cap, dist(B) = something. But reversed(B) checks ∃ valid_cap S superseding *an adoption D that targets r* — S1 supersedes D (the old adoption), and reversal applies to B regardless of which adoption. So B is permanently excluded once any JP supersede of any adoption of B exists. Re-adoption is impossible. That's a permanent censorship of a root by a quorum — but quorum-authorized, so maybe "attributable". Hmm. It's a liveness/permanence question. §D says reversed(r) uses valid_cap — so the model matches spec. The spec itself might be questionable but the gate is about the machine doing what §D says it must not do. Since §D says this, it's not a violation. But could file as a question/P2: "reversal is permanent even if the reversal is itself reversed — admits never recovers; re-adoption doesn't help." Actually wait — let me recheck: is that even true that re-adoption doesn't help? `reversed_roots.add(B)` if exists valid_cap supersede of adoption targeting B with auth_dist < dist(B). If D2 re-adopts B at dist 1, then S1 (auth_dist 0 < 1) still reverses. So yes, B permanently excluded. This is a real property worth flagging, though spec-conformant. Priority: P2 question. Actually, the brief says findings must be violations of §D. A spec-conformant but bad property is a "question" or P2 at best. Let me keep hunting for real violations.

**Attack idea 11: resolver authorization — `common` fold uses `current_JP(common)`.**

The resolver must name exactly maxima at its pre-state. The check `set(tgt) != self._slot_maxima(E, r.kind, actor)` — where E = pre_events(resolver). `_slot_maxima` computes transitions in E of the right kind and validity, then maxima among them.

Hmm, wait: for key-resolution, `actor` is derived from `rot_actor` of the resolves set. But there's a subtlety: the resolver's *effect* — `value=lambda w: self.recs[w].rot_key` — for a key-resolution record, `rot_key` is the chosen key. In `_resolve_slot`, `value(resolvers[0])` → the resolver's `rot_key`. And ident `("key", w)`.

Now the authorization: `pol_pre = self.current_JP(common); keys_pre = self._key_state(common); return self._threshold_ok(r.threshold, pol_pre, keys_pre)`.

The vectors show the honest resolver signed by A (post-succession policy). Fine.

**Attack idea 12: `_slot_maxima` for key-resolution includes key-resolutions themselves in transitions:**

```python
trans = [w for w in E if self.recs[w].kind == "rotation"
         and self.recs[w].rot_actor == actor and self._valid.get(w)]
```

Wait, for key-resolution: `slot_kinds = {"rotation", "key-resolution"}` and the check `any(self.recs[x].kind not in slot_kinds ...)` allows resolves to include key-resolution records. But `_slot_maxima(E, "key-resolution", actor)` only includes kind == "rotation"! So if resolves contains a key-resolution record, the check `set(tgt) != self._slot_maxima(...)` would fail since tgt has a key-resolution not in maxima. Unless... hmm, `_slot_maxima` for res_kind != "policy-resolution" filters kind == "rotation". So a resolves set containing a key-resolution can never equal maxima. So resolvers of resolvers are impossible — the first check `self.recs[x].kind not in slot_kinds` passes (key-resolution in slot_kinds), but the maxima equality fails. Not exploitable, just inconsistent.

Wait, actually, hold on: what if `r.kind == "key-resolution"` and the `rot_actor` derivation: `actors = {self.recs[x].rot_actor for x in tgt}` — for a key-resolution record, does it have `rot_actor` set? In vectors, `Rec("res", ..., "key-resolution", ..., rot_key="K1", ...)` — rot_actor not set (None). If resolves includes a key-resolution rec with rot_actor None and rotations with rot_actor "User", then actors = {None, "User"}, len 2 → invalid. If only a key-resolution... edge cases, fail-closed. OK.

**Attack idea 13: `_resolve_slot` for key state uses resolvers with `set(maxima) == set(resolves)`.** But `valid_cap` of resolver requires exact maxima at the *resolver's pre-state*, while `_resolve_slot` checks maxima at the *full event set E*. These could differ! Consider: rotations R1, R2 (unordered, both valid). Resolver RES descends both, resolves exactly {R1,R2}, valid. Then a third rotation R3 appears, descending RES (so R3 is later, unique maximal). Then maxima of the whole set = {R3}, single → value R3. Fine.

But: R3 concurrent with RES (both descend R1, R2; R3 doesn't descend RES). Then maxima = {RES? no—RES is not a rotation} — maxima among *rotations*: R3... wait is RES counted? In `_key_state`, `rots` = kind == "rotation" only. R1, R2 are ancestors of both R3 and RES, so not maximal. R3 is maximal among rotations. So maxima = {R3}, single → key = R3.rot_key. But the resolver RES resolved the conflict {R1,R2} → K1. R3 is a later rotation causally after R1,R2 but concurrent with the resolution. So key becomes R3's key even though the conflict was resolved to K1 and R3 didn't descend the resolver. Is that a problem? R3 is a legit rotation (valid_cap, e.g. self-rotation with the pre-state key... wait, which key? R3's pre-state includes R1, R2 → conflicted → CONFLICT key → self-rotation requires bound key = CONFLICT? `_bound(actor, key, keys)` with keys[actor] = CONFLICT — filing key would have to equal CONFLICT string. Not possible with a normal key. Threshold path: policy threshold. So R3 would need quorum. If quorum-signed, fine, governance can rotate. Eh.

More interesting: **the resolver's selected key applies, but a concurrent rotation with the OLD key... ** can't be valid since pre-state key conflict.

**Attack idea 14 — the `_key_state` at the whole-cut level vs resolver scoping.** `_resolve_slot` resolvers filter: `set(maxima) == set(self.recs[w].resolves)`. If there are 2 valid resolvers with the same resolves set (competing resolvers choosing different keys), `len(resolvers) == 1` fails → CONFLICT. OK.

**Attack idea 15: `selected_lineage_policy` uses `set(maxima) <= set(resolves)`** — subset, not equality! But valid_cap of the policy-resolution requires exact equality with `_slot_maxima` at its pre-state. At the full-cut level, maxima may have advanced beyond the resolver's resolves (a later succession descending the resolver). Then `set(maxima) <= set(resolves)` fails for the old resolver... let me think: successions s1, s2 concurrent. Resolver res descends both, resolves {s1,s2}, selects P2 (new_policy=P2). Then a new policy-succession s3 descending res, new_policy=P3, threshold under P2. Now maxima among successions at full cut = {s3} (s1,s2 ancestors of res which is ancestor of s3? wait s3 descends res; res is a policy-resolution, not a succession; maxima computed among `succ` only — s3 descends s1,s2 transitively through res. So maxima={s3}, single. Then `selected_lineage_policy` returns `closure(s3) & succ` = {s1 or s2? both!} — closure(s3) includes both s1 and s2 (both are ancestors of res which is ancestor of s3). So both s1 and s2 are in the "selected lineage"! The losing branch s1 is in the lineage because lineage = closure of the single maximal, which contains both forks.

Then `in_lineage(s1)` = True. And `effective(s1)`... s1 is a policy-succession; effective requires active_cut (valid_cap for transitions) ∧ valid_cap ∧ in_lineage ∧ no supersede. So s1 could be effective! Does that matter? The policy state is `_policy_state(E)` = resolved via `_resolve_slot` → single maximal s3 → P3. So the losing branch being "effective" doesn't affect derived policy. But §D.2b says "A losing policy/key branch is gated by in_lineage". The vector test test_losing_branch checks s1 not in lineage when the resolver is the maximal point. But once a later succession descends the resolver, the closure-based lineage includes the loser again. Hmm, is that a violation of §D.2b? §D.2b: "selected_lineage(slot) := the genesis→…→winner chain of valid_cap transitions for slot." The winner chain should be the chain through the resolver's selected branch, not both branches. The model's `selected_lineage_policy` in the single-maximal case returns the whole closure intersected with successions — including losing branches of any resolved conflicts along the way.

Can this be exploited? What depends on `in_lineage` / `selected_lineage_policy`? Only `in_lineage(w)` for w a policy-succession, used in `effective(w)`. And `effective` of a policy-succession... what consumes `effective` of non-ordinary records? `effective_set()` only includes ordinary. The supersede reversal clause in `effective(x)` uses `effective(S)` for supersedes S. So effective of a policy-succession doesn't feed anything except... nothing. `admits` uses valid_cap of adoptions. So the consequence of s1 being "effective" is nil within the model. Hmm. But wait — what about a *rotation* on a losing key branch? `in_lineage` returns True for non-policy-succession records always. So key branches aren't gated by in_lineage at all in the model — only via key-state derivation. OK.

So the lineage quirk has no security consequence in the model. It might matter for WRT-001 interface but that's out of the model's scope. File as question maybe.

**Attack idea 16 — THE RICH ONE: `valid_cap` of a supersede via `_prove_supersede_cap` and `may_reverse` JP clause with `policy_ref == current_JP(prestate)`.**

Scenario: policy P0 = {A,B} 2-of-2. Suppose the policy changes to P1 = {A} 1-of-1 via succession s (A+B sign). Now A alone is the policy. A files supersede S of some ordinary record x by B. S's cap: JP with policy_ref = polv = P1 (current at S's pre-state). Target x's tcap = SELF(B). may_reverse(JP, SELF): new.J == prior.J ✓, policy_ref == current_JP(prestate)[0] ✓ (P1). So valid. JP can censor individual records — by design ("JP may reverse SELF"). That's governance; intended.

**Attack idea 17: the SELF-supersede cap with filing bound at pre-state — but whose key?** `has_self(target.actor)`: filing=(target.actor, key) bound in pre-state keys. If the target actor rotated keys between the target record and the supersede, the pre-state key is the new key. Fine.

**Attack idea 18 — cross-jurisdiction replay.** Records carry `jur`. Model's J is fixed at Model construction. `_compute_valid_cap` uses `self.J` for policy lookups (`current_JP(E)` filters successions by `jur == self.J`). But records with `jur = "K"` in the same cut: for a root-adoption with jur="K", valid_cap checks threshold under polv = current policy of *self.J*, not K! Look: `_compute_valid_cap` doesn't filter by record's jurisdiction. `pol = self.current_JP(E)` — J's policy. A root-adoption for jurisdiction K would be validated against J's policy. Hmm, but the Model is per-J (`Model(world, cut, J)`). Records of other jurisdictions in the same cut... the model conflates. `admits` filters adoptions by `r.jur == self.J`. `effective` → `active_cut` → root_reachable uses admits(J). But `valid_cap` of a K-record is computed with J's policy. Is that exploitable within a single-J model? The effective_set includes ordinary records of any jur? `effective_set` doesn't filter by jur! An ordinary record with jur="K" filed by actor A with bound key would be effective in J's model. Probably out of scope — the model is single-jurisdiction; the world would normally be per-J. Might file as question.

**Attack idea 19 — the big fish: `may_reverse` RP clause ignores `policy_ref` and principal; RP vs RP: same J and slot. And `_prove_supersede_cap` grants RP cap via `has_self(target.rot_actor)` — the slot actor's own key — with NO policy involvement.**

Scenario: Emergency rotation EMG rotates Alice's key (filed by quorum because Alice's key K0 was compromised). Attacker (with K0) can't use K0 anymore (pre-state of anything after EMG has K_new). But Alice's *new* key — if the attacker also has... no.

But consider: Alice self-rotates K0→K1 (record R, valid). Attacker has K0 (compromised). Attacker files supersede S of R with filing=("Alice", K0)... has_self checks bound at S's pre-state keys. If S's priors = {g} (before R), then pre-state key of Alice is K0 → bound! So S is valid_cap with RP cap. And S supersedes R. But `effective(R)` checks `descends(S, R)` — S must causally descend R. If S's priors don't include R, it's skipped. So make S descend R: priors {R}. Then pre-state of S includes R → Alice's key = K1. K0 not bound. Attack fails. The causal rule saves it. What if S has priors {R, g}? pre-state includes R → key K1. Same. OK — to descend R you include R in the past, which applies the rotation. So the old key can't authorize a supersede of the rotation. Good.

BUT — what about superseding an *emergency* rotation? EMG rotates Alice K0→K1 (quorum-authorized, Alice's incoming PoP (Alice, K1)). Now suppose the attacker controls K0. Any supersede of EMG descending EMG needs Alice's bound key at pre-state = K1 (attacker doesn't have) or quorum threshold. So safe.

What about Alice herself (with K1) superseding EMG? has_self(rot_actor=Alice) with filing (Alice, K1) bound → RP cap. may_reverse(RP, RP) same slot → True. So Alice can revoke the emergency rotation that recovered her key. Then her key reverts to... key-state is derived from valid_cap rotations only, not effective! `_key_state` uses `self._valid.get(w)` — valid_cap. So even if EMG is ineffective, the key-state still shows K1. The *effective* revocation of a rotation doesn't undo the key rotation in key-state! Interesting — key_state ignores effectiveness entirely. So superseding a rotation has no effect on derived keys. Then what's the point... and is there a desync? `effective` of records filed with K0 after the rotation... hmm.

Actually this raises a question: is there any consumer of `effective(rotation)`? Only `effective_set` (ordinary only) and the supersede clause. So ineffective rotations still rotate keys. That's per §D.1: "valid_cap... Permanent — a function of the causal past alone; never of effectiveness." And key-state is derived from valid_cap events (D.1: "PRE-STATE key/policy derived from the valid_cap events in preEvents(e)"). So yes, per spec.

**Attack idea 20 — the recursion guard vs. determinism: can `effective()` raise for a legitimate DAG?** The guard fires only on actual cycles, which can't happen since supersedes must descend. Wait — actually, let me check the descend check again:

```python
for s in self.recs:
    S = self.recs[s]
    if S.kind == "supersede" and S.subject == w and self._valid.get(s):
        if not descends(s, w, self.recs):
            continue
        if self.effective(s) and may_reverse(...):
```

`self.effective(s)` — effective of the supersede. The supersede's own effective() looks at supersedes of s, which must descend s. Depth strictly increases along the recursion (s deeper than w). Finite DAG → terminates. OK.

**Attack idea 21 — `active_cut` root_reachable: roots computed as records in closure with no priors *within the cut*.** `self.recs[x].prior & set(self.recs)` — if a record's priors point outside the cut, it's treated as a root. A pinned root's admits set only contains pinned roots and adopted roots. root_reachable = closure roots ∩ admits ≠ ∅. An ordinary record whose priors reference a wid not in the cut becomes its own root → not in admits → not root_reachable → not active. Fail-closed. OK.

**Attack idea 22 — TWO PINNED ROOTS / adoption of a pinned root:** dist of pinned = 0. Adoption of an already-pinned root: nd = 1 not < 0. Fine.

**Attack idea 23 — Adoption where the adopted root B is an ordinary record (not a "root" semantically).** `subject` of root-adoption = "adopted root". In `_compute_admits`, B = r.subject, any wid. If B is not actually a root (has priors), it still gets a dist. Then root_reachable checks roots of closures. Hmm, adopting B gives dist[B], but B not a root. Then a record whose closure's roots include... roots are prior-less records. Adopting a non-root B does nothing for reachability since B isn't a root of anything's closure (closures include B but roots are the prior-less ones). So adoption of a non-root is inert. OK.

Adopting a root B where B is *another jurisdiction's* pinned root? dist starts only with J's pinned. Adoption D (jur J, valid under J's policy) adopts B (any wid). B gets dist 1 → admitted in J. So J's quorum can admit any external root into J. By design (root adoption).

**Attack idea 24 — THE PROMISING ONE: `_prove_supersede_cap` for `target.kind == "supersede"` — the SELF candidate:**

```python
if r.filing and self._bound(*r.filing, keys):
    cands.append(Cap("SELF", r.filing[0], self.J, tcap.slot if tcap else None))
```

So superseding a supersede T: any bound actor (the filer) gets a SELF cap with principal = filer. Then `may_reverse(SELF(filer), tcap, ...)`:

- If tcap.kind == "SELF": requires filer == tcap.principal. So only the same actor can reverse a SELF supersede. 
- If tcap.kind == "JP": SELF vs JP → prior.kind == "JP" requires new.kind == "JP" → False. Good — an individual can't reverse a quorum supersede.
- If tcap.kind == "RP": prior RP requires new RP → False. Good.

And the JP candidate via threshold: JP vs tcap. If tcap SELF → JP may reverse SELF ✓. If tcap JP → JP vs JP: same J, same lineage (principals equal ("pol",J)), policy_ref == current at prestate. The candidate's policy_ref = polv (current at S's pre-state) ✓. So quorum can reverse quorum supersedes. Intended.

**Attack idea 25 — `may_reverse` SELF prior, JP new: `new.policy_ref == (model.current_JP(prestate) or (None,))[0]`.**

`current_JP` returns None if conflicted → `(None,)[0]` = None. For the JP candidate to exist, has_threshold() needed polv non-None. But wait — `policy_ref=polv` where polv = `self._pol_val(E)` at S's prestate. And may_reverse is called with the same prestate. So consistent.

BUT — `current_JP(prestate)` in may_reverse uses `model.current_JP(prestate)` which computes `_policy_state(prestate)` → policy at prestate. polv was computed the same way. Consistent.

Hmm wait, there's something interesting: `(model.current_JP(prestate) or (None,))[0]` — if `current_JP` returns a falsy-but-not-None value? It returns `(pol, pid)` tuple or None. If pol is None and pid is None with conf False? `_resolve_slot` with no transitions returns `(base, base_id, False)`; base could be None if pinned_policy[J] is None → `current_JP` returns `(None, ("pinned-policy", J))`. Then `(None, ("pinned-policy",J))[0]` = None. So policy_ref None required. And a cap with policy_ref=None... `_prove_supersede_cap` builds cands only if has_threshold() (False when polv None) — so no JP cand. SELF cands don't check policy. may_reverse(SELF, SELF) fine.

**Attack idea 26 — THE INTERESTING ONE: policy is None (non-checkpoint-capable jurisdiction) but rotations via threshold impossible; self-rotations fine. Supersedes of rotations by the slot actor with own key: `has_threshold() or has_self(rot_actor)` → RP cap with policy_ref=None. may_reverse(RP, RP): new.slot == prior.slot ✓ → True. So in a policy-less jurisdiction, key rotations can be revoked by the slot actor. Whatever.

**Attack idea 27 — THE KEY INSIGHT CANDIDATE: `valid_cap` of ordinary records requires bound filing at pre-state; `active_cut` also checks bound filing. But `effective` for ordinary records: supersede clause checks supersedes S of w where `may_reverse(carried_cap(S), carried_cap(w), ...)`. carried_cap(w) for ordinary = SELF(r.actor, slot=("record", w)). Note: the slot includes w itself. may_reverse(SELF(A), SELF(A)): principal equal → True regardless of slot. OK.

**Attack idea 28 — Censorship via policy-succession that bricks in_lineage:** If policy becomes conflicted (two concurrent successions, no resolver), `_conflicted_policy()` True → `in_lineage(policy-succession w)` → sel empty → `not self._conflicted_policy()` → False for ALL policy-succession records... wait:

```python
if r.kind == "policy-succession":
    sel = self.selected_lineage_policy()
    return (w in sel) if sel else (not self._conflicted_policy())
```

If conflicted, every policy-succession has in_lineage False → ineffective. But valid_cap still True, and `current_JP` returns None on conflict → new successions can't be authorized (threshold needs policy)... except a *resolver* authorized by pre-conflict common policy. So recovery via resolver. Intended.

But here's a liveness one: `selected_lineage_policy` with ≥2 maxima and exactly one resolver returns lineage; with TWO resolvers (competing) returns set() → conflicted → all successions in_lineage False. And can a *second-generation* resolver resolve the competing resolvers? `_resolve_slot` resolvers must be kind "policy-resolution" with resolves == maxima — maxima are successions, not resolvers. Two competing resolvers both descending {s1,s2}: the maxima among successions are still {s1,s2}! A new resolver res3 descending res1, res2 with resolves {s1,s2}... `set(maxima) == set(resolves)` ✓, descends ✓, valid_cap (authorized by pre-conflict policy at common ancestor of s1,s2). Then resolvers = [res1, res2, res3] → len != 1 → CONFLICT forever. Once two competing resolvers exist, no third resolver can break the tie, because the tie-break counts resolvers, and adding one makes 3. Permanent policy deadlock from a single disagreement. Hmm — is that per §D.2b? "≥2 maximal DAG-unordered ⇒ conflict marker (slot UNUSABLE) unless a valid_cap resolver descends every maximal competitor and is valid_cap under pre-conflict authority ⇒ it selects one branch." The spec says "a valid_cap resolver" (singular). Competing resolvers → conflict. The spec doesn't define tie-breaking among resolvers. So the model matches spec; the spec has a permanent-deadlock property. P2/question: "two competing valid resolvers permanently brick the slot; no recovery path exists (a resolver of resolvers is impossible since maxima are computed over successions only)". Actually wait — can res3 have resolves {s1, s2, res1, res2}? valid_cap check: `set(tgt) != self._slot_maxima(E, r.kind, actor)`; for policy-resolution, `_slot_maxima` includes kinds policy-succession AND... let me check:

```python
if res_kind == "policy-resolution":
    trans = [w for w in E if self.recs[w].kind == "policy-succession"
             and self.recs[w].jur == self.J and self._valid.get(w)]
```

Only successions. And slot_kinds for policy-resolution = {"policy-succession", "policy-resolution"} — resolves may include policy-resolutions per the kind filter, but then maxima equality fails. So no. Permanent deadlock confirmed as spec-conformant. This is a liveness finding (P2?) — brief attack surface #3 mentions liveness of fail-closed defaults. It's spec-conformant though. The gate asks: does the machine do what §D says it must not? §D doesn't say the slot must recover. File as P2 with a repro showing permanent bricked policy even with an honest majority willing to res-resolve. Actually the severity guidance: P2 = real but bounded defect. A permanent governance deadlock from one conflicting pair of resolvers is real. But spec-conformant... The brief says §D governs; a finding is when the machine does something §D says it must not. Hmm. But also P1 = "a claimed property does not hold". The claims include being a settlement substrate without censorship primitive. Deadlock claims were in prior rounds. I'll demo it and file as P2, noting spec-conformance ambiguity. Let me keep looking for cleaner violations first.

**Attack idea 29 — revisit `_resolve_slot` resolver acceptance: `set(maxima) == set(self.recs[w].resolves)` but NO jur check on the resolver!** In `_resolve_slot`, resolvers = [w for w in E if kind matches and valid and resolves==maxima and descends]. The resolver's `jur` isn't checked against self.J here. But valid_cap of the resolver (policy-resolution) — `_compute_valid_cap` for resolutions checks `self.recs[x].jur != r.jur` for x in resolves — consistency among resolves vs resolver's jur. The successions s1,s2 have jur J. So resolver jur must be J. OK fine.

For key-resolution in `_key_state` → `_resolve_slot(..., kind="key-resolution")` — resolvers of kind key-resolution with resolves == maxima; the resolver's validity was checked. OK.

**Attack idea 30 — `_key_state` when actor not in pinned_keys and no rotations:** out.get(actor) — fine.

**Attack idea 31 — `_compute_valid_cap` for rotation: `pop = bool(r.incoming_pop and r.incoming_pop == (r.rot_actor, r.rot_key))`.** Then threshold OR self. Notice: the *filer* for threshold path isn't required to be a quorum member — threshold witnesses are separate from filing. Emergency vector: filing=("Q","kQ") but actually filing isn't even checked on the threshold path! Look:

```python
if r.kind == "rotation":
    pop = ...
    if not pop: return False
    if self._threshold_ok(r.threshold, polv, keys): return True
    return bool(r.filing and r.filing[0] == r.rot_actor and self._bound(*r.filing, keys))
```

Threshold path ignores `r.filing` entirely. So a rotation record with threshold quorum witnesses but filed by anyone (even filing=None or filing=("Mallory","kM")) is valid_cap. Does filing matter elsewhere? carried_cap(rotation) = RP(("keypol",J), slot (key, rot_actor)) — no filer. effective(rotation) = active_cut (valid_cap) ∧ valid_cap ∧ in_lineage(True) ∧ ¬superseded. So an emergency rotation "filed by" an arbitrary stranger is fully effective. Is that a violation? §D.1 says witnesses must satisfy the role rule. The role rule for rotation presumably includes filing rules ("bound actor-filing" is in active_cut only for ordinary). §D.3's active_cut mentions "bound actor-filing" as part of eligibility... "active_cut(x, admits(J)) := root-reachable to admits(J) ∧ eligible manifest entry ∧ bound actor-filing". Hmm — "bound actor-filing" is listed in D.3's active_cut gloss. The model implements bound actor-filing only for ordinary records. For rotations on the threshold path, no actor-filing check at all. The emergency-rotation vector even sets filing=("Q","kQ") and the test name says "bound quorum filer != target" — implying the design *wants* the filer to be a bound quorum member. But the code doesn't check it! Test passes regardless of filing value. So: a rotation with valid PoP + threshold but `filing=None` (or an attacker's key) is valid_cap and effective. That demonstrates the machine accepting something the design (and its own test's name) says requires a bound quorum filer. Is it a §D violation? §D.1: "e's manifest witnesses satisfy e's role rule (may_use, D.4)". The role rule for rotation isn't fully specified in §D beyond may_use. §D.3 gloss "bound actor-filing" is part of active_cut definition in the spec text: "active_cut(x, admits(J))  # root-reachable to admits(J) ∧ eligible manifest entry ∧ bound actor-filing". That comment in §D.3 lists three things, and the model's active_cut only checks bound filing for ordinary. So a rotation with NO filing at all passes active_cut (via `self._valid.get(w)`) — the model treats "transitions: valid_cap is eligibility". Given the test vector's name explicitly claims "bound quorum filer" is a requirement ("FILED by a bound quorum actor Q"), and the machine doesn't enforce it, I can write a repro: same emergency rotation but filing=("Mallory","kMallory") or None → still valid_cap and effective, and Mallory (a non-quorum stranger) is recorded as filer. Severity: is this a security hole? The threshold is what authorizes; the filer is just the uploader. But then why does the vector emphasize "bound quorum filer"? Because §5 (prose) presumably requires it. The impact: attributability — the filer of record is Mallory. Actually, hold on — deeper impact: `rec.actor` — the Rec's `actor` field is the FILER. For rotation records, `actor` is used... anywhere? `carried_cap` rotation → RP principal ("keypol", J) — no actor. In effective_set — ordinary only. So filer attributation is cosmetic in the model. Meh. But it IS a mismatch with the vector's stated claim. I'd rate it P2 at best, and it might be "as designed" (threshold is the authorization; filer is just transport). The test comment says "bound quorum filer != target, no outgoing key" as properties being demonstrated, but the code only needs threshold + PoP. Let me note it but hunt for bigger game.

**Attack idea 32 — policy-succession `valid_cap`: threshold under current policy at pre-state. What about the *first* succession when pinned_policy[J] is None?** polv None → threshold False. So no succession possible in policy-less J. Fail-closed. OK.

**Attack idea 33 — `current_JP` returns (pol, pid); in `_prove_supersede_cap` JP cand policy_ref=polv (the policy VALUE, i.e. (frozenset, k)), while may_reverse compares `new.policy_ref == current_JP(prestate)[0]` — also the value. Consistent.

**Attack idea 34 — TWO supersede candidates: `for c in cands: if may_reverse(...): return c`.** For ordinary targets, cands order: SELF first, then JP. If both apply (target actor files AND has quorum threshold), returns SELF. Fine.

**Attack idea 35 — THE MANIFEST/ineligible.** The model has NO manifest at all! §D references "e's manifest witnesses satisfy e's role rule" and "eligible manifest entry" in active_cut. The model implements witnesses as fields on Rec (filing, threshold, incoming_pop) and eligibility as... nothing. Attack surface #2 (total manifest negative claim) can't be tested against the model because there's no manifest. The brief says the model operationalizes §D; but the manifest (§3) is entirely absent. So any manifest finding is a "question" — can't repro. Note in "NOT examined / Questions".

**Attack idea 36 — CID.** `checkpoint_CID(state, auth_witnesses)` and `checkpoint_authorized(state, auth_witnesses, model)`. Attack surface #4: "can a filer produce two distinct authorization sets over the same P that both satisfy the policy, yielding two valid CIDs for one frontier?" With a 2-of-3 policy {A,B,C}: sets {A,B} and {A,C} both satisfy → two CIDs: CID(P, {AW_A,AW_B}) ≠ CID(P, {AW_A,AW_C}). Both verify. §D.5 says "competing CIDs at one (J,sequence) are a conflict resolved by a certificate descending both." So the spec acknowledges it. Is it a violation? §D.5 claims CID is "THE checkpoint identity" — but with m-of-n policies, the identity is not unique per frontier. The spec says conflicts are resolved by succession. Hmm — "Consumer-independent" claim: different consumers could accept different CIDs for the same frontier, and the resolution requires a *successor* certificate descending both — but "Consumer-independent — no wave citation or successor is needed to freeze it". Contradiction? If two competing CIDs exist, a consumer needs the successor to know which won — that IS a successor dependency. The spec resolves competing CIDs via a descending certificate, reintroducing the tail dependency for the conflict case. But is there a model-level violation I can execute? I can show: same state P, two different satisfying witness sets → two different CIDs, both `checkpoint_authorized` True. That demonstrates non-uniqueness of "THE checkpoint identity" for a single frontier. §D.5 says competing CIDs are "a conflict resolved by a certificate descending both" — so the spec has a story. But the claim "consumer-independent — no successor needed to freeze it" is weakened: in the conflict case you DO need the successor. Hmm, the mitigation: an honest quorum would never sign twice for the same (J, sequence) — but a *different* quorum composition at the same sequence with an overlapping... With threshold m-of-n and two disjoint-ish sets, you need m distinct signers each; signers in both sets signed twice (equivocation). With {A,B} and {C,D} disjoint in a 2-of-4: NO signer equivocated! Four honest actors, two disjoint pairs, each signed once, same P? Wait, same P means same frontier and sequence. If honest policy is 2-of-4 {A,B,C,D}, and pairs {A,B} and {C,D} each sign P... they signed the same P, so no state fork, just two certificates. That's benign-ish (same state). For a *state* fork you need different P with same (J,sequence) — the signature is over P which includes sequence and frontier; an honest signer shouldn't sign two different P at the same sequence. But with 2-of-4, {A,B} sign P1 and {C,D} sign P2 (different frontier) — again NO individual equivocation needed! Two valid CIDs at (J, seq) with DIFFERENT state. §D.5: "competing CIDs at one (J,sequence) are a conflict resolved by a certificate descending both." But a certificate descending both requires cut inclusion of both — possible, but which one do R1 consumers use in the meantime? The claim of "finite, consumer-independent" checkpointing is violated in this case: consumers cannot independently decide. This is exactly attack surface #4's question: "Is that a fork, or a bug? §D should say; check that it does." §D does say (conflict resolution). But the resolution mechanism — "a certificate descending both" — has a problem: CID succession includes CIDₙ in cut(Fₙ₊₁). A resolving certificate must descend BOTH competing CIDs, requiring a quorum to sign a P whose frontier includes both certificates — but the competing certificates have *different frontiers/state*. Merging them means the new frontier covers both cuts... if the states conflict (different effective sets for overlapping cuts), the descendant certificate's state must pick one. That's the governance resolution path. OK the spec story is coherent-ish, but the model's `checkpoint_authorized` happily verifies both. Let me reproduce: policy 2-of-4, P1 ≠ P2 same sequence, AW sets {A,B} and {C,D}, both authorized, CIDs differ, no signer equivocates. The violation claim: "CID is THE checkpoint identity" (uniqueness) and "consumer-independent" — with disjoint non-equivocating quorums, two identities exist and no consumer-local rule picks one. Severity P1 ("a claimed property does not hold") — though §D.5's last sentence anticipates competing CIDs. The claim that breaks is "Consumer-independent — no wave citation or successor is needed to freeze it": for the loser... hmm, actually each CID individually IS frozen and verifiable. The fork is a *liveness/consensus* issue above the model. I'll repro it and argue P1/P2, being honest that §D.5 acknowledges conflicts but the resolution requires a successor (contradicting consumer-independence for conflicted sequences).

Actually wait — there's a sharper CID issue: `checkpoint_authorized` reads `model.current_JP(E)` and `model._key_state(E)` where E = the model's FULL cut, not `cut(P.frontier)`! §D.5 verify says: "resolve P; rebuild cut(P.frontier); derive current_JP(J) (D.2b) ... check the set satisfies current_JP" — at the frontier's cut, i.e., the state AT the checkpoint. The model function takes `model` built on some cut and uses the whole model cut. If the model's cut is LATER than the checkpoint's frontier (policy changed since), `checkpoint_authorized` evaluates against the CURRENT policy, not the policy at the checkpoint. So: checkpoint C authorized at sequence 1 under policy P_old {A,B} 2-of-2; later policy succeeds to P_new {C,D} 2-of-2; a verifier rebuilding at the later cut calls checkpoint_authorized → threshold under P_new → A,B not in actors → False! A valid historical checkpoint fails verification after a policy rotation. Conversely, a checkpoint that was INVALID at its frontier (signed by C,D under old policy) becomes VALID after the policy changes to {C,D}. Retroactive authorization flip! That's a real, clean violation of §D.5 ("derive current_JP(J) ... rebuild cut(P.frontier)") and of immutability ("a late ... cannot flip a pinned CID" — here the *verdict* flips without changing the CID). The repro: build world with g, succession s: P_old→P_new. Model1 on cut {g} → checkpoint_authorized(state, {A-sig,B-sig}, model1) True. Model2 on cut {g,s} → same state, same witnesses → False. And the converse: witnesses {C,D}: False at model1, True at model2. That is a retroactive authorization change — the exact thing §D.5 claims to kill ("Immutable ... cannot flip a pinned CID"; "consumer-independent"). The fix would be building the model at cut(frontier) — the API takes a model so the caller could do that, but then "verify(CID)" per §D.5 must rebuild cut(P.frontier) — the model's function doesn't do that; it uses whatever cut the model was built with, and nothing ties `state["frontier"]` to the model's cut. Also note `checkpoint_authorized` ignores `state` entirely (except implicitly)! It takes `state` but never uses it — look:

```python
def checkpoint_authorized(state, auth_witnesses, model):
    E = frozenset(model.recs)
    pol = model.current_JP(E)
    ...
```

`state` is unused! So the function doesn't even check that the witnesses signed *this P*. The AW includes ("sig-over", P) in the CID hash, but `checkpoint_authorized` never verifies the AW's sig covers the given state. So: CID1 = checkpoint_CID(state1, aw); checkpoint_authorized(state2, aw, model) → True — witnesses that signed state1 are accepted for state2! The signature-over-P binding exists in the hash construction but verification doesn't recompute/check it. In a real impl, verify would check sig_i-over-P; the model claims to operationalize §D.5's verify: "check sig_i-over-P by a key bound to actor_i". The model's verify does NOT check sig-over-P at all. So a checkpoint certificate for state P1 can be "verified" against a different state P2 — a verifier would accept a checkpoint claiming an arbitrary effective_set_root with signatures that actually attest a different state. THAT is a P0/P1: forgery of checkpoint content. Concretely: `checkpoint_authorized(forged_state, aw_honest, model)` returns True where aw_honest signed honest_state. But wait — can I "demonstrate the violation"? The function's contract: §D.5 verify(CID): resolve P, check sig-over-P. The model's docstring: "The AW set must satisfy J's current governing policy over cut(frontier), with each signer's key BOUND — replay reads only these committed AW". The AW is (actor, key) pairs here — the sig-over-P is synthesized inside checkpoint_CID from the given state. So in the model, the AW set doesn't carry the P it signed — meaning the API itself can't distinguish. Demonstration: compute CID for state1 with aw; then ask checkpoint_authorized(state2, aw, model) → True. The verifier accepts attestation for state2 that was never signed. The violation line: "VIOLATION: §D.5 verify must check sig_i-over-P; the model's checkpoint_authorized accepts an AW set for a state those witnesses never signed (state is not even referenced)". This shows the certificate is not bound to its state blob — a checkpoint can be repurposed to vouch for any effective_set_root. I'd call it P0 (forgery path: a checkpoint certificate can be presented for a state its signers never attested, and verification passes) or P1 (composition break). Given "P0 = the machine is unsound or a censorship/forgery path exists" — this is a forgery path. Let me be careful though: is the intended usage that the verifier recomputes CID = hash(P, auth_root) and compares to the pinned CID? If so, the binding comes from the caller comparing CID. checkpoint_authorized is only the policy check. But §D.5's verify includes "check sig_i-over-P" as part of verification, and the model's function is the stand-in for that verify. A caller doing `checkpoint_CID(state, aw) == pinned_cid and checkpoint_authorized(state, aw, model)` would be safe... for the P-binding. But the policy-at-frontier issue remains even then: authorized flips as policy changes. Hmm, and also: even with CID comparison, the CID pins P and AW bytes, so late signatures can't flip — fine. The two real findings:

F-A: `checkpoint_authorized` evaluates the auth set against the policy/key-state of the *model's whole cut*, not `cut(P.frontier)` — so a checkpoint's validity flips retroactively as governance evolves (both directions: valid→invalid and invalid→valid). Violates §D.5's "rebuild cut(P.frontier); derive current_JP" and the immutability/consumer-independence claims. P1 (or P0 since a checkpoint unauthorized at filing becomes authorized later → a CID that should never have been accepted becomes acceptable — retroactive authorization).

F-B: `checkpoint_authorized` never uses `state` — no sig-over-P check — so the "verify" half of §D.5 doesn't bind witnesses to the state. If a consumer relies on checkpoint_authorized (as the model's verify stand-in), any state can be paired with any policy-satisfying AW set. P1 (the CID comparison could save it IF consumers do it, but §D.5's verify lists the sig check as a step and the model omits it).

Actually for F-B, let me reconsider: the model says "a signature is a (actor, key) pair" — in this modeling, the AW in `checkpoint_CID` is constructed as hash(actor, key, sig-over-P) where sig is deterministic from (actor,key,P). So an AW for a different P is genuinely a different object — the model's stand-in for signature verification is that you *can't* obtain an AW over P2 without... well, you can: _canon(("AW", a, k, ("sig-over", P2))) — anyone can compute it. There's no unforgeability in the model at all (no crypto by design). So within the model's abstraction, "checking sig-over-P" would mean: given AW bytes, extract P and compare to state's P. The model's checkpoint_authorized takes raw (actor,key) pairs, not AW hashes, so it can't even express the check. Given "no crypto by design", maybe F-B is out of scope ("Findings about ... crypto are out of scope — a signature is an (actor,key) pair"). Hmm. The ground rule says crypto findings are out of scope. F-B is arguably about the verification logic (missing state binding), not crypto. But a defender could say "the CID comparison binds P; checkpoint_authorized is only the policy gate." The function's own docstring says "replay reads only these committed AW" — meh. I'll file F-B as a P2/question with the repro showing `state` is unused, and focus severity on F-A.

For F-A, is the defense "caller should build the model at cut(frontier)"? §D.5 verify: "resolve P; rebuild cut(P.frontier); derive current_JP(J)". So the verifier MUST rebuild at the frontier. The model's checkpoint_authorized(state, aw, model) — the docstring says "must satisfy J's current governing policy over cut(frontier)" — "current ... over cut(frontier)" — but E = model.recs (the whole cut), and there's no enforcement or even reference to state["frontier"]. So the model does NOT implement "over cut(frontier)" — it implements "over whatever cut the Model was built with". A verifier with a full historical store naturally builds one model over its whole cut and checks checkpoints against it — the natural composition gives retroactive flip. The repro will show both flip directions. That's the strongest finding so far. Let me also double check `current_JP` over E includes successions in E... yes `_policy_state(E)` with E = model.recs.

Also for key binding: `keys = model._key_state(E)` — same issue: a checkpoint signed with key K1 that was bound at the frontier but later rotated → verification at later cut rejects the (actor, K1) witness since keystate[actor] = K2. Retroactive invalidation via key rotation too. Even more common than policy change: ANY key rotation by a checkpoint signer invalidates the historical checkpoint under the model's verify. Checkpoint signers rotate keys all the time (that's the compromise-recovery path!). So: Alice and Bob sign checkpoint seq 1 with keys kA,kB. Alice rotates kA→kA2 (routine). Verifier at the new cut: keystate[Alice] = kA2 ≠ kA → Alice's AW doesn't count → below threshold → historical checkpoint invalid. The checkpoint system collapses on first signer rotation. §D.5: "check sig_i-over-P by a key bound to actor_i" — bound *at P's cut*, per "rebuild cut(P.frontier)". The model binds at the verifier's cut. This makes the flip concrete and shows both the immutability claim and liveness break. P0/P1. I'll write one repro covering policy-change flip and key-rotation flip. Actually let me write two repros: F1 (key rotation retroactively invalidates a pinned checkpoint) and F2 (retroactive authorization of a checkpoint that was below-threshold at its frontier — the dangerous direction, a previously-invalid CID becomes valid; that's a forgery-ish acceptance). Both from the same root cause; I can combine or keep separate. Keep as one finding with one repro showing both directions? The protocol: each finding its own repro block. I'll do F1 = invalidation (liveness/immutability break, P1), F2 = retroactive authorization (acceptance flip, P0-leaning-P1). Hmm, severity: "P0 = the machine is unsound or a censorship/forgery path exists." A checkpoint that was NOT authorized at its frontier later verifies as authorized → an unauthorized "checkpoint" gains quorum authorization retroactively → that's a forgery-adjacent acceptance. But one could argue the verifier-side fix is trivial (build at frontier) and §D.5 prose says to rebuild cut(P.frontier) — the model just doesn't. The model IS the subject of the gate ("a concrete, executable input to the §D machine that makes it do something §D says it must not do"). §D.5 says verify rebuilds cut(P.frontier); the machine's verify doesn't; net effect: verdicts flip. I'll call F2 P1 (claimed property — immutability/consumer-independence — does not hold), and note P0-adjacency.

**Attack idea 37 — supersede of a rotation where the slot actor's OWN key authorizes (the "RP satisfied by the slot actor's own bound key" sibling).** The brief says the model found that as a real defect — but looking at the code, `has_self(target.rot_actor)` is still there in `_prove_supersede_cap` for rotation targets. Wait, maybe the "defect" was elsewhere and fixed. Let me test: can a slot actor revoke a rotation they didn't like? Alice's key rotated by emergency quorum (compromise recovery). If Alice's new key K1 is ALSO attacker-controlled (attacker filed PoP? incoming_pop = (A, A_new) — PoP is just a tuple, no crypto; anyone can write incoming_pop=("A","evil")... wait, PoP "proof of possession" — in the model it's a tuple equality check, no verification of possession at all! `pop = bool(r.incoming_pop and r.incoming_pop == (r.rot_actor, r.rot_key))` — this just checks the tuple fields match the record's fields. It's a well-formedness check, not a proof. So "PoP" in the model is vacuous — fine, no crypto by design).

So emergency rotation EMG: rot_actor=A, rot_key=K_evil, incoming_pop=("A","K_evil"), threshold=quorum. The quorum is the authorization; PoP vacuous. OK by design.

Now: quorum rotates A's key to K1 (EMG, valid). A (with K1) supersedes EMG → valid (RP via has_self). effective(EMG) → False (reversed by S with RP cap... may_reverse(RP, RP) same slot → True, and S descends EMG, and effective(S) — S is a supersede; effective(S) needs active_cut (valid_cap ✓) ∧ valid_cap ✓ ∧ in_lineage (True) ∧ no supersede of S. So EMG ineffective. But key-state still K1 (valid_cap-based). So nothing changes operationally. The revocation of a rotation is a no-op for derived key state. So the "revoke a rotation" path is semantically void. Not an exploit.

BUT — supersede of an ORDINARY record: the censor must be target.actor (SELF) or JP threshold. What about supersede of an ordinary record where target actor = filer with key bound... The interesting sibling: **supersede of a supersede whose tcap is RP**: cands include SELF(filer) and JP(threshold); may_reverse(SELF, RP) False; may_reverse(JP, RP) False (prior RP requires new RP). And the RP cand is only added `if tcap and tcap.kind == "RP"` with threshold. So to reverse an RP-carrying supersede you need threshold → RP cap with tcap.slot. may_reverse(RP new, RP prior): same J, same slot ✓. OK.

**Attack idea 38 — `has_self` for supersede-of-supersede uses ANY bound filing:** `if r.filing and self._bound(*r.filing, keys): cands.append(Cap("SELF", r.filing[0], ...))`. Then may_reverse(SELF(filer), tcap): only if tcap SELF with same principal. So Bob can't reverse Alice's SELF supersede. OK.

**Attack idea 39 — What about superseding an ordinary record of actor A by A, where A's key was rotated between the record and the supersede?** has_self uses pre-state of S → new key. Fine.

**Attack idea 40 — The `effective` supersede scan iterates `self.recs` — ALL records in the cut, requiring descends(s, w).** Fine.

**Attack idea 41 — `active_cut` for transitions = valid_cap. But `root_reachable` for transitions is ALSO required (active_cut's first line). A policy-succession whose roots aren't admitted → not active → ineffective. Roots: closure's prior-less records ∩ admits. Fine.

**Attack idea 42 — Pinned root not in the cut?** `pinned_roots={"J": {"g"}}` but "g" not in recs → dist has "g" but admits = {r for r,d in dist if d<inf} - reversed = {"g"}. root_reachable checks roots of closures — "g" appears only if in some closure. Fine.

**Attack idea 43 — `_root_of` for adoption distance: roots = prior-less records in closure of the ADOPTION record. An adoption D with priors {A} where A is pinned root → dist 0 → B dist 1. An adoption D whose priors include a NON-root record that traces to A — roots still {A}. OK.

**Attack idea 44 — adoption chains: D1 adopts B (dist 1), D2 adopts C with priors on B-branch? D2's roots: records in closure(D2) with no priors in cut. If D2's priors = {some record on B's branch whose root is B} → roots = {B} → d_adopt = 1 → C dist 2. Fine.

**Attack idea 45 — NOW the distance/reversal asymmetry:** reversed(B) requires auth_dist(=0) < dist(B). If B is ALSO pinned (dist 0), 0 < 0 false → not reversed. So pinned roots can't be reversed. Adopted roots (dist ≥ 1) can always be reversed by any valid_cap JP supersede of any adoption of B — even a supersede that is itself ineffective/revoked. As analyzed in idea 10: permanence. Let me construct the demo: pinned A; adopt B via D (quorum JP). Quorum supersedes D (S1, valid JP) → B excluded. Quorum supersedes S1 (S2, valid JP, JP vs JP) → S1 ineffective. Then re-adopt B via D2 (valid) → dist(B) = 1 again. reversed: S1 still valid_cap, supersedes an adoption targeting B, JP cap, 0 < 1 → reversed. B stays excluded FOREVER despite the reversal being reversed and a fresh adoption. §D.2a literally specifies this ("∃ valid_cap S"). Is it a §D violation? No — it's §D-conformant. Is it a "claimed property" violation? The anti-censorship claim: "any self-signed actor can supersede anyone's WarrantID and vanish it" is the censored case — here it's quorum-authorized, visible, attributable. It's a *permanence* surprise: an un-reversed reversal still censors. I'll file as P2 with repro (the property "a reversed reversal restores admission" is not claimed in §D; but "re-adoption" failing is surprising liveness). Actually — wait. Even simpler: it makes `admits` depend on valid_cap of supersedes *anywhere in the cut*, including supersede records that are NOT root-reachable / NOT effective / pure spam. A quorum-authorized but immediately-revoked supersede still censors. Also: S1 could be on a LOSING policy branch! valid_cap of S1 is computed under the policy at S1's pre-state — if S1 sits on a branch where the policy was different... hmm, policy-succession changes current_JP for descendants. S1's threshold evaluated at its pre-state policy. Suppose policy fork: s1 (P0→P_evil, quorum-signed — wait, quorum-signed means legit authorization under P0). A succession P0→P1 authorized under P0, later a resolver selects a DIFFERENT branch P2; s1 loses (in_lineage false). S1 (supersede of adoption D) filed on the losing branch with threshold under P1. S1 is valid_cap (its pre-state policy P1 satisfied). in_lineage(S1)? S1 is a supersede → in_lineage returns True always! effective(S1)? active_cut requires root_reachable — S1's roots = {A} pinned ✓ — and valid_cap ✓. And the reversal in _compute_admits uses only `self._valid.get(w)` — valid_cap. So a supersede authorized under a LOSING policy branch reverses the adoption in admits, even though that policy branch was definitively rejected by the resolver. The losing branch's governance acts (supersedes of adoptions) still govern! §D.2b says "A losing policy/key branch is gated by in_lineage" — but in_lineage(supersede) is defined as True ("e uses no conflicted slot" — well, its AUTHORIZATION used the conflicted policy slot!). The gating for non-succession records is "via their basis in effective()" per the model comment — but admits doesn't use effective, so basis-gating never reaches the adoption-reversal path. THIS is a real violation: §D.2a says reversed(r) uses "valid_cap S ... cap(S).kind = JP ∧ cap(S).J = J" — hmm, §D.2a as written only requires valid_cap + JP. So §D as written PERMITS losing-branch censorship of roots?! §D.2a's reversed uses valid_cap only — permanent. So §D's own text has the hole, and the model implements it faithfully. The gate question: "makes it do something §D says it must not do" — §D doesn't forbid it. But §D.2b claims losing branches don't govern; and the brief's property 2: "resolver-selected-lineage effect gating (a losing branch does not govern)". A losing-branch JP supersede reversing an adoption = a losing branch governing root admission. That contradicts the design claim even if §D.2a's literal text allows it. Where prose/claims disagree with §D, §D governs... but §D.2b's own sentence "A losing policy/key branch is gated by in_lineage, not by superseding its record" is §D. And `in_lineage` in §D.2b: "e's authorizing transition ∈ selected_lineage(its slot), or e uses no conflicted slot." A supersede authorized by JP threshold USES the policy slot (its authorizing transition is the policy-succession chain). If the policy slot is conflicted and its branch lost, then per §D.2b's definition, in_lineage(S1) should be False. The MODEL defines in_lineage as True for all non-policy-succession records — a faithful-looking shortcut that is NOT §D.2b's definition. So the model violates §D.2b for supersede records whose authorization basis is a losing policy branch. Impact: `effective(S1)` — does in_lineage matter there? For the effective set (ordinary records), and for the reversal in admits... wait, admits reversal uses valid_cap(S1), not effective or in_lineage. So even if I fix in_lineage, the admits reversal still uses valid_cap only — per §D.2a ("∃ valid_cap S"). So §D.2a ITSELF lets a losing-branch JP supersede reverse adoptions. Hmm, §D.2a says "valid_cap adoption D" for distance and "valid_cap S" for reversal — permanent layer-1 facts. So per §D, a quorum act on a resolver-rejected branch permanently censors an adopted root. The oscillation fix (valid_cap not effective) reintroduced branch-contamination. This is a strong P1: "a losing policy branch still governs root admission (censorship of a root via a resolver-rejected policy), contradicting §D.2b's gating claim and the brief's stated property 2." The repro: pinned A, policy P0={A,B} 2-of-2. Adoption D of root B_root... hmm wait, I need B both as actor and root; rename: root record "RB" filed by actor X. Pinned root RA. D adopts RB (threshold A+B under P0). Now fork policy: s1: P0→P1 (A+B sign, valid) — wait I need a CONFLICT and a resolver selecting the other branch. s1: P0→P1={Mallory...} no — P1 must be something the attackers can satisfy. Attackers are A? Let's make it concrete: P0 = ({A,B},2). Honest resolver will select P2 branch. Attackers want to censor RB. s1: P0→P1 where P1 = ({A},1) — signed by A+B (valid under P0; A and B are the quorum — if A and B are the attackers, they don't need a losing branch... they'd just use JP directly at distance 0). The losing-branch trick matters when the attackers LOSE power: P0 = ({A,B},2), succession s2: P0→P2=({C,D},2) wins the resolver. The losing branch s1: P0→P1=({A},1). On s1's branch, A alone satisfies P1. A files S1 superseding adoption D, threshold={(A,kA)} — valid under S1's pre-state policy (P1 at that branch). Resolver res selects s2's branch. Now: S1 is valid_cap (permanent), cap JP. admits: reversed(RB) via S1 → RB excluded — even though A's authority was retroactively rejected (s1 lost). RB is censored by a dead branch, permanently (valid_cap is forever; no un-reversal helps as shown). And this is *invisible* in effective-set terms... visible in admits. Let me verify the model computes S1 valid: S1.priors = {s1, D}? S1 must descend D to be relevant for effective, but for ADMITS-reversal, descent isn't checked! `_compute_admits` reversal loop: any supersede w with subject = adoption D, valid_cap, JP cap. No descent requirement! So S1 needn't even descend D. S1.priors = {s1} (on the losing branch). valid_cap(S1): E = pre_events(S1) = {g?, s1, ...}; policy at E = P1 (s1 is the single maximal succession in E) → threshold {(A,kA)} satisfies P1 → JP cand; may_reverse(JP, tcap of D): D is root-adoption → tcap = JP(("pol",J), policy_ref None?). carried_cap(root-adoption D) = Cap("JP", ("pol",J), J, ("gov",J)) — policy_ref None. may_reverse(new JP(policy_ref=P1), prior JP(policy_ref=None), prestate E): prior.kind JP → new.kind JP ✓, same J ✓, lineage equal ✓, `new.policy_ref == current_JP(E)[0]` → P1 == P1 ✓ → True. So valid_cap(S1) = True. In admits reversal: tgt=D kind root-adoption jur J ✓; B=RB; cap JP; auth_dist 0 < dist(RB)=1 → reversed. RB excluded from admits → all records rooted at RB are inactive → censored. And this holds even after res selects the other branch, FOREVER.

Wait — do I even need the losing-branch complexity? A simpler demo of the same class: S1 on the WINNING/main branch but later itself superseded (revoked) — still censors (idea 10). The losing-branch version is sharper: governance that was *rejected* still censors. Both stem from "reversal = ∃ valid_cap S" with no effectiveness/lineage/descend requirement. Which to file? Both in one finding? The protocol wants one repro per finding. I'll file:

F3 (P1): losing-branch JP supersede reverses an adoption in admits — rejected governance still censors roots; §D.2b claims losing branches are gated out; §D.2a's `∃ valid_cap S` admits them. Also §D.2a's `reversed` doesn't even require S to causally descend D (the model matches; §D.2a text: "∃ valid_cap S superseding an adoption D that targets r" — superseding presumably implies the causal rule from §5, but the model doesn't check descends in admits-reversal; in `effective` it does check). Include that the supersede need not descend the adoption — a supersede record that §5's causal rule would ignore for `effective` still counts for admits. Let me double check the model's admits reversal once more:

```python
for w in self.recs:
    r = self.recs[w]
    if r.kind != "supersede" or not self._valid.get(w): continue
    tgt = self.recs.get(r.subject)
    if tgt is None or tgt.kind != "root-adoption" or tgt.jur != self.J: continue
    B = tgt.subject
    cap = self.carried_cap(w)
    if cap and cap.kind == "JP":
        auth_dist = 0
        if auth_dist < dist.get(B, inf): reversed_roots.add(B)
```

No descends check, no effective check, no in_lineage check. Yes.

Also `carried_cap(w)` for the supersede recomputes `_prove_supersede_cap` at w's pre-state — fine, consistent with valid_cap.

Hmm, wait — one more check on my F3 scenario: is D's adoption still what gives RB dist 1? D priors {RA} (pinned) → roots {RA} dist 0 → RB dist 1 ✓. And S1's pre-state policy: E = closure(S1) − S1. S1 priors: {s1}? But wait — s1's priors: {g}? Let me set g = RA (the pinned root, an ordinary record filed by A with bound key kA under pinning). s1 priors {RA}: policy-succession P0→P1, threshold {A,B} under P0 ✓ valid. S1 priors {s1, D}? D's roots... D priors {RA}. E = {s1, D, RA}. policy_state(E): successions in E = {s1} → single maximal → P1 ✓. keys: A→kA, B→kB (pinned, no rotations). threshold {(A,kA)} satisfies P1=({A},1) ✓.

Resolver: s2 priors {RA}: P0→P2, threshold {A,B} ✓ valid. res priors {s1,s2}: policy-resolution, resolves exactly {s1,s2}, new_policy=P2, threshold under common ancestor policy: common = pre_events(s1) ∩ pre_events(s2) = {RA} ∩ {RA} = {RA} → policy P0 → threshold {A,B} ✓ valid. Now full-cut policy: successions {s1,s2}, maxima {s1,s2} (unordered), resolvers: kind policy-resolution, valid, resolves=={s1,s2}, descends both ✓ → exactly 1 → P2 wins. selected_lineage: {res} ∪ (closure(s2) ∩ succ) = {res, s2}. s1 NOT in lineage ✓ (in_lineage(s1) False). But admits: RB reversed by S1 → RB ∉ admits. Any ordinary record on RB's branch is inactive. CENSORSHIP by the losing branch. 

Also check: does S1 being on the losing branch make it ineffective/irrelevant? Doesn't matter — admits only uses valid_cap.

And per §D.2a text — "reversed(r) := ∃ valid_cap S superseding an adoption D that targets r, with cap(S).kind = JP ∧ cap(S).J = J ∧ authority_dist(cap(S)) < dist(r)". The model implements exactly this. So the model is faithful to §D.2a, and §D.2a itself is the hole. The gate brief says §D governs — and §D.2a permits this. But §D.2b (also §D) says losing branches are gated. Two parts of §D in tension; the composition produces censorship by rejected governance. The design's headline claim ("not a censorship primitive") fails via this path: a quorum whose policy amendment was REJECTED can still permanently vanish an adopted root. Actually hmm, wait — in my scenario A and B were both in P0 and signed both s1 and s2? That's odd (why would they sign both). Make it cleaner: P0 = ({A,B,C}, 2). s1 (→P1=({A},1)) signed by {A,B}. s2 (→P2=({B,C},2)) signed by {B,C}. Resolver res selecting s2 signed by {B,C} under common policy P0. So A is the only actor who definitely "wants" P1. A then files S1 (threshold {(A,kA)} under P1) superseding D. A is a minority whose branch lost; A alone censors RB forever. Strong. Let me double-check valid_cap(res): resolves must equal `_slot_maxima(E_res, "policy-resolution")` where E_res = pre_events(res) = {s1, s2, RA} → successions {s1,s2}, both maximal → {s1,s2} ✓. common = {RA} ∩ {RA}... pre_events(s1) = {RA}, pre_events(s2) = {RA} → common {RA} → pol P0 → keys pinned ✓ → threshold {B,C} 2-of-({B,C},2)... wait P0 = ({A,B,C},2): threshold {(B,kB),(C,kC)}: good = {B,C} ≥ 2 ✓.

And D: root-adoption, jur J, subject RB, priors {RA}, threshold under P0 = 2-of-3: {(B,kB),(C,kC)} ✓ valid. dist(RB) = 1.

RB: ordinary record, priors {} (genesis of its own branch), filed by X bound key kX. RBC: ordinary child of RB filed by X. effective(RBC)? root_reachable: roots of closure(RBC) = {RB}; RB ∉ admits → not active → RBC ineffective. Before S1/res: RB admitted → RBC effective. Show the transition: build cut without S1: RBC effective ✓. Add the losing branch s1+S1 (and s2+res): RBC ineffective. Also show s1 lost (in_lineage(s1) False, policy = P2) yet censorship persists. Also show it's permanent: add S2 superseding S1 signed under P2 (revoke the censoring supersede) and re-adoption D2 of RB — RB still excluded. That single repro demonstrates: losing branch censors + irrevocable. Let me make sure S2 (supersede of S1) valid: S2 priors {s2, res, S1}? To be on the winning branch and descend S1. E_S2 includes S1's branch too. threshold under policy at E_S2: successions {s1,s2} + resolver res → resolved → P2 = ({B,C},2) → threshold {(B,kB),(C,kC)} ✓. may_reverse(JP P2, tcap(S1)=JP P1...): prior JP → new JP same J ✓ lineage equal (principals both ("pol",J)) ✓ policy_ref == current_JP(E_S2)[0] = P2 ✓ → valid. effective(S1): superseded by S2 (descends ✓, effective(S2) ✓, may_reverse(JP(P2), JP(P1...), prestate S2)... wait may_reverse(prior=carried_cap(S1)): carried_cap(S1) = _prove_supersede_cap at S1's prestate → JP with policy_ref=P1. may_reverse(new=JP P2, prior=JP P1): policy_ref P2 == current_JP(prestate S2)[0]=P2 ✓ → True → S1 ineffective ✓. But RB still reversed in admits (valid_cap(S1) still True). D2 re-adopts RB: priors {RA}... to be valid needs threshold under current policy at its prestate — P2 → {B,C} ✓ valid → dist(RB) recomputed: min over adoptions: D gives 1, D2 gives 1 → 1. reversed still via S1 (auth 0 < 1) → excluded. PERMANENT. Beautiful — that's F3, P1 (arguably P0: "a censorship path exists" — P0 definition: "the machine is unsound or a censorship/forgery path exists". A minority actor whose governance branch was rejected can permanently censor any adopted root. That IS a censorship path → P0. Though it requires the actor to have once been quorum-authorized to propose P1... no wait — s1 needs threshold under P0 (2-of-3: A+B). So A needs ONE collaborator from P0, or A is in P0 with a partner. The censorship authority = a one-time quorum that later loses. Hmm — actually simpler variant without any fork: current quorum supersedes the adoption (legit governance, visible) — that's intended governance. The losing-branch variant shows REJECTED governance censoring — that's the violation. I'll file P0 or P1? The brief: P0 = unsound or censorship/forgery path. I'll say P1 with P0 argument, let me decide: the path requires quorum authorization under some valid_cap policy state at some point (a branch that was honestly authorized by the then-current quorum — s1 was signed by A+B, a valid P0 threshold). So the censor did hold power at that moment... but only over the fork they created; the resolver rejected it. The anti-censorship claim is about *effective* governance; this lets superseded/rejected governance act permanently. I'll file P1 (a claimed property — losing-branch gating — does not hold) and note it borders P0. Hmm, actually — the model comment in in_lineage says "ordinary/rotation/supersede gated via their basis in effective()". For `effective`, basis-gating... does effective(RBC) get gated by S1's branch? No — RBC's ineffectiveness comes from admits (layer 2a), which uses valid_cap only, by §D.2a's explicit design ("Uses valid_cap of adoptions (permanent) — not lifecycle effective"). The spec authors deliberately chose valid_cap for layer 2a to kill the oscillation — and thereby made rejected-branch censorship permanent. This is a genuine design-level finding, and the repro executes it. Good. P1 minimum; I'll argue P0 for censorship path and let severity discussion show both. I'll mark P0 since the rubric explicitly lists "a censorship path exists" and this is one (rejected governance permanently vanishes a root and everything on it). Actually, let me reconsider once more whether §D.2a's "authority_dist < dist(r)" was meant to guard this: authority lineage must be strictly lower distance than r. The model hardcodes auth_dist=0 for J's governing policy ("modeled as the adopting jurisdiction anchor (distance 0) when it is J's governing policy"). S1's authority is J's policy (on a branch) → 0 < 1 ✓. The guard is about *where* the authority anchors, not whether the branch won. So no protection. Right.

**Attack idea 46 — sibling: `valid_cap` of an adoption D itself on a losing branch.** D adopted RB with threshold under P1 (losing branch). valid_cap(D) True → dist(RB)=1 → admitted! A losing branch can ADMIT a root too — admitting an unauthorized root = the opposite of censorship: unauthorized INCLUSION (anyone's branch becomes authoritative). So rejected governance can both admit and censor roots. Same root cause (layer 2a on valid_cap), same finding — mention in the same repro? Maybe as F3 and F4 separately: F4 = "adoption authorized only on a resolver-rejected policy branch still admits the root (unauthorized root admission)". Both are the layer-2a-valid_cap issue but opposite directions; the fix might differ (gating adoptions by lineage breaks the oscillation-fix...). I'll write them as one finding with two asserts? Protocol: one repro per finding, exits 0 with VIOLATION print. I could do F3 (censorship) and F4 (unauthorized admission) as separate repro blocks, same scenario family. F4 severity: admitting an unauthorized root makes foreign records "effective" — a FORGERY-ish path (records not authorized by current governance become effective). Hmm wait — but the adoption IS authorized by a valid_cap threshold under P1 which was authorized by P0... it's authorized by a *historical* quorum on a rejected branch. "Rejected branch governs" covers both. Let me keep F3 (reversal/censorship) as the primary and include the admission direction briefly in the same block or as F4 P1. I'll write F4 separately for clarity.

Hold on, for F4 — is it really true? D priors: must D's roots be at distance? dist computation: d_adopt = min dist of roots of D's closure. D priors {s1}? s1 priors {RA} → roots of D's closure = {RA} dist 0 → RB dist 1. D valid under P1 (its prestate {s1,RA} policy P1, threshold {(A,kA)} ✓). Resolver picks s2. admits: adoptions = [D] valid → RB dist 1; reversed? no supersede of D → RB admitted ✓. Then RBC (ordinary child of RB) → root_reachable ✓ → effective ✓. So a record rooted at a root admitted solely by rejected-branch governance is effective. Meanwhile the WINNING branch never adopted RB. VIOLATION: unauthorized (by selected governance) root admission. 

**Attack idea 47 — What about `valid_cap` of the resolver's authorization when the common ancestor's policy is conflicted?** pol_pre None → threshold False → fail closed. OK.

**Attack idea 48 — `_slot_maxima` uses `self._valid` computed over the whole cut... but takes E subset; `trans = [w for w in E ... self._valid.get(w)]` — valid_cap(w) was computed w.r.t. its own prestate, fine.**

**Attack idea 49 — `Model.__init__` computes `_valid` for w in topo order of the whole cut. `pre_events(w, self.recs)` — fine.

**Attack idea 50 — Now, an important one: TWO adoptions giving different distances and the reversal strictness.** auth_dist always 0 → any JP supersede reverses any adoption (dist ≥ 1). The "authority_dist < dist(r)" guard is vacuous in the model (0 < everything adopted). Per the model's own comment this is a modeling choice. OK.

**Attack idea 51 — `effective()` on a supersede whose target is itself: S supersedes S (subject = own wid). descends(s,s) = s in pre_events(s) → False → skipped. OK.

**Attack idea 52 — the `in_lineage` for policy-succession when sel non-empty: `(w in sel)`. If NOT conflicted but there are 2+ maxima with NO resolver: `_policy_state` → conflicted → `selected_lineage_policy` returns set() (no resolvers → len != 1 → set()). Then in_lineage(w) = `not self._conflicted_policy()` = False. All successions ineffective but valid_cap. current_JP None → new supersedes can't get JP caps... but SELF ones still work. Liveness: policy bricked until resolver. Intended.

**Attack idea 53 — hash/CID canonicalization: `_canon` of frozenset with elements of mixed types sorted by repr — deterministic. checkpoint_CID deterministic ✓.

**Attack idea 54 — `checkpoint_authorized` key-binding uses model's cut (F1/F2 above). Also: NO check that witnesses are distinct actors — `_threshold_ok` uses a set of actors ✓ distinct.

**Attack idea 55 — Let me reconsider `test_quorum_rollback`'s second check: `m.effective("s") if ... else True or not m.effective("roll")` — that's garbage Python (precedence) but it's the suite's own, not my problem.

**Attack idea 56 — `valid_cap` of "ordinary": `bool(r.filing and self._bound(*r.filing, keys))`. `r.filing` = (actor, key) — must match keystate[actor]. But note: filing actor needn't equal r.actor! `Rec.actor` is "the FILER". `filing=("A","kA")` — _bound checks keystate["A"]=="kA". r.actor could be "Mallory" while filing=("A","kA"). carried_cap(ordinary) = SELF(r.actor) = SELF(Mallory)! So an ordinary record with actor="Mallory" but filing witness ("A","kA") is valid_cap — the record claims Mallory as filer but Alice's signature authorizes it. Then supersede of this record: has_self(target.actor)=has_self("Mallory") — needs Mallory's key. carried_cap = SELF(Mallory). So Alice authorized a record that Mallory can supersede (and that SELF(Mallory) caps apply to). Confused-deputy-ish: the AUTHORIZER (Alice, whose key is bound) is not the recorded ACTOR. In a real impl, body.actor.id with a signature from a different key would be a mismatch — the model doesn't check `r.filing[0] == r.actor`. Is that a §D violation? §D.3 active_cut "bound actor-filing" — "actor-filing" suggests the filing witness IS the actor. The model checks a bound filing but not that it's the record's actor. Impact: records whose authorization (Alice) and identity (Mallory) diverge; revocation rights attach to Mallory (SELF) while Alice's authority authorized it. Also effective_set includes it. I'd file as P2 (modeling gap enabling principal confusion) with repro: record actor=Mallory, filing=(A,kA) → valid_cap & effective True; and Alice CANNOT supersede it (has_self(target.actor=Mallory) fails) even though her key authorized it; Mallory (who never signed anything) can. That's a clean little auth/identity mismatch. P2. Actually wait — should double check active_cut: ordinary → bound filing ✓ same as valid_cap. effective → True. And supersede by Alice: S_alice supersedes x: has_self("Mallory") → filing would need ("Mallory", kM) — Alice's filing ("A","kA") → no SELF cand; threshold → JP cand; may_reverse(JP, SELF(Mallory)) → JP reverses SELF ✓ if quorum. So Alice alone cannot revoke the record she authorized; Mallory can revoke a record he never signed. Show both. Cute. P2.

**Attack idea 57 — `incoming_pop` equality check is vacuous (already noted; no crypto, out of scope per ground rules).**

**Attack idea 58 — Emergency rotation threshold evaluated under JP at prestate; if policy conflicted at prestate → polv None → threshold False → self path only → if the slot actor's key is compromised and policy conflicted, emergency rotation impossible. Liveness edge; spec-conformant fail-closed. Skip.

**Attack idea 59 — Let me look again at `_prove_supersede_cap` for `target.kind == "rotation"`: `if has_threshold() or has_self(target.rot_actor)`. The has_self path: the SLOT ACTOR's bound key at the SUPERSEDE's prestate. Rotation R: A rotates K0→K1. S supersedes R, priors {R, ...}: prestate keys: A→K1. filing ("A","K1") → has_self ✓ → RP cap → may_reverse(RP, tcap(R)=RP(slot (key,A))) → True → S valid_cap. So the slot actor can always revoke their own rotations (ineffective, but as shown valid_cap revocation doesn't change key-state — void). Since it's void of effect, not a finding. Wait — is it really void? `effective(R)` False — consumers of effective(rotation)? effective_set excludes non-ordinary. Hmm, but what about WRT-001's interface `authorized_effective_active_for(J, checkpoint)` — out of model scope. Void within model. Skip.

**Attack idea 60 — `_key_state` normalization: `out = {a: (next(iter(ks)) if len(ks)==1 else CONFLICT)}` — a pinned actor with TWO pinned keys → CONFLICT → then rotations: `_resolve_slot(E, ws, base=out.get(actor)...)` — rotations for that actor: single maximal → value. So rotations recover from pinned conflict. OK.

**Attack idea 61 — Let me examine `_resolve_slot` maxima subtlety: maxima computed among `transitions`, but a resolver that descends all maxima and is itself in E... resolvers list filters `set(maxima) == set(resolves)`. If there are TWO valid resolvers with the same resolves → CONFLICT (brick, idea 28). If one resolver res1 resolves {s1,s2} and later s3 descends res1: maxima becomes {s3} → single → no resolver needed → value s3. But `selected_lineage_policy` in this case: maxima {s3} single → returns closure(s3) ∩ succ = {s1, s2, s3} — INCLUDES LOSER s1 (idea 15). So after the lineage advances past a resolver, the losing branch RE-ENTERS the selected lineage. in_lineage(s1) becomes True again. effective(s1) = active_cut ✓ (valid_cap) ∧ valid_cap ✓ ∧ in_lineage ✓ ∧ no supersedes → True. So s1 — the resolver-REJECTED succession — becomes EFFECTIVE once the policy advances. Does anything consume effective(s1)? In-model: no (only ordinary in effective_set; supersede-clause only for supersedes). But it contradicts §D.2b's "losing branch is gated by in_lineage" directly — in_lineage(s1) = True for a losing branch. The repro is trivial and directly contradicts §D.2b's claim as operationalized. Combined with F3/F4's root cause... no, this is a different mechanism (closure-based lineage re-inclusion). Even without security impact in-model, it demonstrates §D.2b's gating is not actually delivered: the property the vector test_losing_branch pins only holds while the resolver is maximal. Wait, actually let me re-check: does it also re-enter while resolver is maximal but there are additional unresolved...? The single-maxima case: maxima={s3} where s3 descends res (the resolver). closure(s3) includes everything: s1, s2, res, RA. ∩ succ = {s1,s2,s3}. So sel = {s1,s2,s3} → s1 in sel → in_lineage(s1) True. Whereas test_losing_branch (no s3) asserts s1 NOT in lineage. So the property flips as history grows — non-monotone gating. That's a P1/P2. It's directly checkable. Severity: within the model, effective(s1) has no downstream consumer... BUT WAIT — actually there might be one: `selected_lineage_policy` is used by `same_policy_lineage`? No — `_same_policy_lineage` compares principals only. `in_lineage` is used in `effective`. And... `current_JP` doesn't use selected_lineage. So impact = effective(s1) = True for a rejected succession — cosmetic in-model, but the §7 property "a losing branch does not govern" is precisely about what governs; and for WRT-001 consumers reading "effective" transitions (e.g., authorized_effective_active_for), a rejected policy-succession showing as effective could authorize downstream acts. Interface-level impact. I'll file as P1 (claimed property — losing branch gated — fails non-monotonically) with a clean repro. Hmm wait, actually let me reconsider severity given in-model voidness: P2? The brief: P1 = "a composition breaks, or a claimed property does not hold". The claimed property "losing branch gated by in_lineage" does not hold (it flips True as the DAG grows). P1 by the rubric, honestly reported with the note that in-model downstream impact is nil but the property the rev-6 gate asked to be pinned is only pinned at the tip. Yes, P1.

Let me double-check this repro logic once more. Build like test_losing_branch, then add s3: policy-succession P2→P3, priors {res}, threshold under policy at prestate {res,s1,s2,g}: policy_state: successions {s1,s2}, maxima {s1,s2}, resolvers: res valid? res resolves {s1,s2} exactly — `_slot_maxima(E_s3, "policy-resolution")` = maxima of successions in E_s3 = {s1,s2} ✓ (res not in E_s3? E_s3 = pre_events(s3) = closure(s3)−{s3} = {res, s1, s2, g}. For valid_cap(res) computed at res's own prestate — fine, already valid.) → exactly 1 resolver → P2. So s3's threshold must satisfy P2 = ({B,C},2): threshold {(B,kB),(C,kC)} ✓. s3 valid ✓. Now full cut: successions {s1,s2,s3}: maxima: s3 (s1,s2 are ancestors of res... wait — is s1 an ancestor of s3? s3 priors {res}, res priors {s1,s2} → yes, both s1 and s2 descend... s3 descends s1 and s2. So maxima = {s3} single. selected_lineage_policy: `if len(maxima)==1: return closure(maxima[0]) & set(succ)` = closure(s3) ∩ {s1,s2,s3} = {s1,s2,s3}. in_lineage(s1): r.kind == policy-succession → sel non-empty → s1 in sel → TRUE. VIOLATION of §D.2b gating: the resolver selected P2's branch (s2), s1 lost, yet s1 ∈ selected lineage. Also effective(s1)? active_cut(s1): root_reachable — roots of closure(s1) = {g} ∈ admits ✓; transitions eligibility = valid_cap ✓ → True. valid_cap ✓. in_lineage True. supersedes of s1: none. → effective(s1) = True. And policy_state still P3 (s3) — so governance output unaffected, but the rejected succession is marked effective. Print: "VIOLATION: §D.2b — losing policy-succession s1 re-enters selected_lineage/effective once the chain advances past the resolver". Good, F5.

Wait, also — the same closure trick means `res` (the resolver, a policy-resolution) is NOT in `succ` (succ only successions) — fine.

**Attack idea 62 — now let me look at `_policy_state` / `_key_state` using `self._valid` where transitions on a LOSING key branch still set keys.** _key_state uses valid_cap rotations only — by §D.1 design. Fine.

**Attack idea 63 — `admits` distance fixpoint: `while changed` — termination: distances only decrease, bounded below by 0 → terminates ✓.

**Attack idea 64 — dist uses `min` over adoption paths, but reversal requires auth_dist < dist(r) with auth_dist=0 — even dist-1 adoptions reversed. What if r is adopted at dist 1 by D1 and ALSO pinned? dist 0 → unreversable. OK.

**Attack idea 65 — What if an adoption D targets r where r is itself an ADOPTION record or a supersede (non-root)?** dist[B] for any wid B; only roots matter for reachability. Inert otherwise.

**Attack idea 66 — Records with priors pointing to themselves?** closure handles cycles via seen. `pre_events(w)` = closure − {w}. If w ∈ its own prior: closure includes w; pre_events excludes it. toposort: visit(w): seen.add(w) then visit priors → w in seen → skip → order appended once. descends(a,b)... A self-prior record: is it a root? `not (prior & set(recs))` — prior = {w} ⊆ recs → not root. Such a record's roots = whatever else. Weird but not exploitable quickly. Skip.

**Attack idea 67 — `effective_set()` only ordinary. `canonical()` includes policy pid — determinism.

**Attack idea 68 — Let me re-examine `_threshold_ok`: `good = {a for (a,k) in witnesses if a in actors and keystate.get(a)==k}`. If keystate[a] == CONFLICT string and witness key == CONFLICT string?? A witness ("A", "«CONFLICT»") would match keystate "«CONFLICT»"! keystate.get(a) returns the CONFLICT sentinel when the slot is conflicted. If a witness presents key = "«CONFLICT»" (just a string in the model!), it counts as bound! CONFLICT is a module-level string "«CONFLICT»". So during a key conflict, ANY actor can "sign" with the literal string "«CONFLICT»" and be counted bound. Let me check: `_bound(actor, key, keystate): return keystate.get(actor) == key` — key="«CONFLICT»", keystate[actor]="«CONFLICT»" → True!! And `_threshold_ok`: `keystate.get(a) == k` — same. So: fork Alice's key (two concurrent rotations R1: →K1, R2: →K2, both valid, no resolver) → keystate[Alice] = CONFLICT. Then Alice (or ANYONE claiming to be Alice) files an ordinary record with filing=("Alice", "«CONFLICT»") → valid_cap True, effective True! A conflicted slot is supposed to be UNUSABLE (§D.2b: "slot UNUSABLE"). Instead it becomes UNIVERSALLY usable — fail-OPEN. The sentinel leaks into the comparison. That's a clean P0: "conflicted key-slot is fail-open: the CONFLICT marker compares equal to a presented key of the same value, so any record 'signed' with the conflict marker is authorized." Let me verify the mechanics: pinned_keys {"A": {"K0"}}. R1: rotation A→K1, self-rotation filing ("A","K0") bound at prestate {g} ✓, pop ("A","K1") ✓ → valid. R2: rotation A→K2, priors {g} (concurrent with R1 — R2's prestate = {g}, key still K0 → filing ("A","K0") bound ✓) → valid. keystate(full): rotations for A: {R1,R2}, maxima {R1,R2} (unordered), resolvers: none → CONFLICT → out["A"] = CONFLICT ✓. Now X: ordinary, priors {g} (prestate keys: A→K0... wait — need prestate where keystate is CONFLICT! X priors {R1, R2}: prestate = {g,R1,R2} → keystate: maxima {R1,R2} no resolver → CONFLICT. filing=("A", "«CONFLICT»") → _bound: keystate.get("A") == "«CONFLICT»" → True → valid_cap(X) True. active_cut: root_reachable (g pinned ✓) ∧ bound filing ✓ → True. effective(X) True. Also a SUPERSEDE with filing ("A", CONFLICT)... or a THRESHOLD: policy ({A,B},2) with witnesses {("A",CONFLICT),("B",kB)} → good = {A,B} → threshold satisfied during A's conflict! Even better: a policy-succession or emergency rotation authorized by a conflicted actor's "signature". The conflicted slot — meant to be unusable — satisfies thresholds. P0 definitely. The sentinel should never compare equal to a key. The check should be `keystate.get(a) not in (None, CONFLICT) and keystate.get(a)==k`. Great finding: "conflict marker is a valid key".

Let me also make sure ordinary vector pre-state uses _key_state(pre_events) — yes. And CONFLICT string equality — `CONFLICT = "«CONFLICT»"`. In the repro, `filing=("A", M.CONFLICT)` — I'd import model and use model.CONFLICT. The point: in this model a "key" is any string; the conflict marker is a string; equality is the only check. An attacker presenting the marker as a key is "claiming" the conflicted state as their key. In real terms: the wire key would be actual bytes, but the model's bound-check is exactly `==`, and the derived state for a conflicted actor IS that marker, so the model's authorization semantics fail open. The model is the normative machine under review → P0. Also `test` the threshold version to show governance acts pass: policy-succession during key-conflict authorized by the conflicted actor + B. Even better, emergency rotation R3 resolving... whatever, ordinary record suffices plus a threshold demo.

Wait — one check: does `active_cut` for ordinary use prestate keys — yes, and the conflict is in X's prestate ✓. Also is there any in_lineage gate? ordinary → True. supersedes? none. → effective True. 

Also — the same via `has_self` in supersede caps: filing ("A", CONFLICT) bound → SELF(A) cap → Alice's "authority" usable by anyone during her conflict. E.g., supersede Alice's ordinary records (censor them) during her key conflict. Include in repro? Keep the repro focused: (1) ordinary record by forged conflict-key is valid+effective; (2) threshold quorum counts the conflict-key toward policy. Print VIOLATION. P0. Excellent.

**Attack idea 69 — similar sentinel issue: `out.get(actor)` when actor has NO pinned key and no rotations → None → `keystate.get(a)==k` with k=None? Witnesses with key None... filing=(a, None)? `bool(r.filing and ...)` — filing tuple with None key is truthy. _bound(a, None, keys): keys.get(a) == None if a not in keys → True!!! Wait: `keystate.get(actor)` returns None for unknown actor; `_bound(actor, None, keystate)` → None == None → True! So an ordinary record filed by an actor with NO key anywhere, with filing=("Nobody", None), is valid_cap!! Let me check: `_bound` returns `keystate.get(actor) == key` → None == None → True. And `r.filing` = ("Nobody", None) — truthy (non-empty tuple). So valid_cap(ordinary) = True for a keyless actor with a None key. "Bound iff it is the actor's key in the relevant pre-state key-state" — the actor has no key; presenting None matches "no key". FAIL-OPEN for unkeyed actors. Even simpler than the CONFLICT one! Also `_threshold_ok` with witness (a, None) where a in policy actors but a has no key: keystate.get(a)==None → counts toward threshold! So a policy naming an actor who never got a key can be satisfied by that actor's "None signature". Hmm — is that realistic? Policy includes actor C who has no pinned key and no rotations. Witness ("C", None). `_threshold_ok`: a="C" in actors ✓, keystate.get("C") == None == k ✓ → good includes C. YES. So thresholds can be met with null keys for keyless actors. Both are the same class: missing/None/sentinel key-state compares equal to a presented null. P0 class. I'll fold None-key and CONFLICT-key into one finding (fail-open binding) or two? They're two distinct sentinels (None = absent, CONFLICT = conflicted). Same line of code: `_bound`/`_threshold_ok` equality without a well-formedness check on the derived key. I'll do one finding with a repro covering both (two asserts), or two findings for distinct severity... They're equally P0. Protocol says one repro per finding; I'll file F6 = "conflicted slot fails open (CONFLICT compares equal to presented key)" P0, and F7 = "keyless actor's None key binds (absent key compares equal to None witness)" P0. Two repros, same root line. Fine — but let me make sure ordinary with filing None-key: `bool(r.filing and self._bound(*r.filing, keys))` — r.filing=("Z", None) → `*r.filing` → _bound("Z", None, keys) → keys.get("Z") → "Z" not in pinned, no rotations → None → None == None → True → bool(True and ...) → True. active_cut same → effective True. And threshold: policy ({A,Z},2), witnesses {("A","kA"),("Z",None)} → good = {A: kA ✓, Z: None==None ✓} → 2 ≥ 2 → True. So a 2-of-2 policy with a keyless member is satisfiable with one real signature. P0. 

Actually — hmm, is "a policy naming a keyless actor" realistic? pinned_policy = ({A,Z},2) where Z never got pinned keys. Sure, misconfiguration or Z's key pending. The fail-closed answer must be False. Good.

Also — what about `checkpoint_authorized` with (Z, None)? Same _threshold_ok → same hole: checkpoints signed by keyless actors count. Could mention.

**Attack idea 70 — Now `may_reverse` TOTAL claim: `well_formed` requires bool(c.principal) — principal ("pol",J) tuple truthy ✓. None caps → False ✓.

**Attack idea 71 — determinism of `effective` iteration `for s in self.recs` with break on first reversing supersede — result independent of iteration order? If two supersedes S1 (reverses) and S2 (doesn't) — order irrelevant to final ok. If S1 reverses only if effective(S1) — fine. OK.

**Attack idea 72 — `World.pinned_keys` with an actor mapped to EMPTY set: len 0 → CONFLICT. eh.

Let me also double-check F1/F2 (checkpoint policy-at-cut) repro details:

F1 (retroactive invalidation by key rotation): world: g ordinary by A (pinned keys A:kA, B:kB), pinned policy P=({A,B},2). state = {...sequence 1...}. m1 = Model(world, cut={g}) → checkpoint_authorized(state, {("A","kA"),("B","kB")}, m1) → policy P ✓ keys A→kA,B→kB ✓ → True. cid = checkpoint_CID(state, aw). Then R: rotation A: kA→kA2 (self-rotation, priors {g}, filing ("A","kA"), pop ✓) valid. m2 = Model(world, cut={g,R}). checkpoint_authorized(state, aw, m2): keys: A→kA2 → ("A","kA") not bound → good={B} → 1 < 2 → False. The PINNED checkpoint CID (same bytes) now fails authorization. VIOLATION: §D.5 "Immutable — a late ... cannot flip a pinned CID" + "rebuild cut(P.frontier)". The verdict flips from True to False with zero change to the certificate. Print VIOLATION.

F2 (retroactive authorization): same world + policy-succession s: P→P2=({C,D},2) (threshold A,B ✓). m_before = Model(cut {g}): checkpoint_authorized(state, {("C","kC"),("D","kD")}) → C,D not in P → False. m_after = Model(cut {g,s}): policy P2 → keys C,D pinned ✓ → True. A witness set that did NOT authorize at the frontier authorizes later → a CID never validly authorized becomes "authorized". Both directions = the verification is a function of the verifier's cut, not the checkpoint's frontier — violates "consumer-independent" (two consumers at different cuts disagree on the same CID's validity). Print VIOLATION. Severity P1 (or P0 — I'd say the dangerous direction is F2; I'll file both as one finding? Protocol: one repro per finding. I'll make F2 the finding (P1, noting P0 adjacency) and F1 as a second repro/finding (P1). Or combine into one block with both directions and one VIOLATION line. Cleaner: F1 = "checkpoint verdict flips with verifier's cut — both directions" as a single P1 finding with one repro showing False→True and True→False. I'll do that. And F2 = two valid CIDs, same (J,sequence), different frontier, disjoint non-equivocating quorums (2-of-4) — the "consumer-independent" contradiction. Actually — with the model's functions: state1/frontier1 with aw1={A,B}, state2/frontier2 same sequence with aw2={C,D}: checkpoint_authorized both True (at appropriate models... at a model whose cut contains both frontiers? policy 2-of-4 ({A,B,C,D},2) → both sets satisfy at any cut). cid1 ≠ cid2. Both "authorized". §D.5 says competing CIDs resolved by a descending certificate — so the spec anticipates; the executable demo shows the model offers no consumer-independent rule; both verify forever until a successor exists — i.e., a successor IS needed in the conflict case, contradicting "no successor is needed to freeze it". P2 (spec-acknowledged) — or question. I'll repro it as P2 with honest framing.

Also the `state`-unused issue (F-B): fold into the F1 report as a note? Or its own P2 repro: `checkpoint_authorized(forged_state, aw, m)` True where aw = witnesses that signed honest_state (as shown by cid binding). Demonstration: cid_honest = checkpoint_CID(honest_state, aw); forged_state has different effective_set_root; checkpoint_authorized(forged_state, aw, m) → True; and note checkpoint_CID(forged_state, aw) ≠ cid_honest — so the ONLY thing binding state to witnesses is the caller comparing CIDs; the model's authorization oracle vouches for any state. §D.5 verify: "check sig_i-over-P" — the model's verify stand-in omits it. File as P2 with the caveat (no crypto; but the *check* is missing from the algorithm, not the crypto). OK.

Now F5 (lineage re-inclusion) repro — as designed above. Let me also double check `selected_lineage_policy` when resolvers != 1 → set() — in my F5 scenario after adding s3: maxima single → skip resolver branch → closure(s3) ∩ succ. ✓.

F3 repro (losing-branch reversal censors root permanently) — as designed. Let me now write all records precisely.

F3 scenario records:
- pinned: roots {"J": {"RA"}}, policy P0 = ({"A","B","C"}, 2), keys A:kA, B:kB, C:kC, X:kX.
- "RA": ordinary, priors {}, actor A, filing ("A","kA"), jur J. (pinned root)
- "RB": ordinary, priors {}, actor X, filing ("X","kX"), jur J. (foreign genesis)
- "RBC": ordinary, priors {"RB"}, actor X, filing ("X","kX").
- "D": root-adoption, priors {"RA"}, subject "RB", threshold {("B","kB"),("C","kC")} → valid under P0 ✓ (B,C ≥ 2).
- "s1": policy-succession, priors {"RA"}, new_policy P1=({"A"},1), threshold {("A","kA"),("B","kB")} → valid under P0.
- "s2": policy-succession, priors {"RA"}, new_policy P2=({"B","C"},2), threshold {("B","kB"),("C","kC")} → valid.
- "res": policy-resolution, priors {"s1","s2"}, resolves {"s1","s2"}, new_policy P2, threshold {("B","kB"),("C","kC")} → common ancestor {RA} → P0 → B,C ✓ valid.
- "S1": supersede, priors {"s1"} (NOTE: does NOT descend D — fine for admits-reversal), subject "D", threshold {("A","kA")} → prestate policy: successions in E={s1,RA} → P1 → A satisfies ✓ → JP cand → may_reverse(JP(P1), tcap(D)=JP(None policy_ref), E): prior JP → new.policy_ref == current_JP(E)[0] → current_JP({s1,RA}) = (P1, ("policy","s1")) → [0] = P1 ✓ → valid ✓.

Wait — may_reverse's prior is carried_cap(D) = Cap("JP", ("pol","J"), "J", ("gov","J")) with policy_ref None. The prior.kind=="JP" branch: `new.policy_ref == (model.current_JP(prestate) or (None,))[0]` → P1 == P1 ✓ → True. Note prior.policy_ref (None) is never compared! Interesting — JP priors don't check prior.policy_ref at all. So a JP supersede can reverse a JP target regardless of the target's policy vintage, as long as the NEW cap is "current". "Current, not historical" for the new one. OK by design.

Checks for F3 repro:
1. m_full.valid_cap("S1") is True (censoring supersede is "valid_cap" — permanent).
2. m_full.in_lineage("s1") is False (s1 lost — resolver picked P2).
3. current_JP(full) = P2 (governance moved on).
4. "RB" not in m_full.admits() and not m_full.effective("RBC") → the losing branch's act governs admission: censorship.
5. Control: without S1 (world minus S1), RB admitted and RBC effective → S1 is the cause.
6. Permanence: add "S2" supersede of S1 on the winning branch (priors {"res","S1"}, threshold {("B","kB"),("C","kC")} under P2 → JP vs JP → valid; S1 becomes ineffective) and "D2" re-adoption of RB (priors {"res"}, threshold {B,C} under P2 → valid) → RB STILL not admitted. 

Check S2 valid: E_S2 = closure = {res, s1, s2, RA, S1} → policy: successions {s1,s2}, resolver res valid & resolves {s1,s2} ✓ → P2 → threshold B,C ✓. JP cand policy_ref = P2. may_reverse(new JP(P2), prior=carried_cap(S1)): carried_cap(S1) = _prove_supersede_cap at S1's prestate → JP(policy_ref=P1). prior.kind JP → new JP same J ✓ lineage ✓ new.policy_ref P2 == current_JP(E_S2)[0] = P2 ✓ → True → S2 valid_cap ✓. effective(S1): S2 descends S1 ✓, effective(S2)? S2 active_cut: roots of closure(S2) = {RA} ∈ admits ✓ valid ✓ in_lineage (supersede → True) ∧ no supersede of S2 → True. may_reverse(JP(P2), JP(P1), prestate S2) ✓ → S1 ineffective ✓. And admits: S1 still valid_cap → RB still reversed. D2: roots of D2 closure = {RA} → d 0 → RB dist 1... but reversed set computed independently → RB excluded. So asserts 4-6 all hold → VIOLATION print.

Note for honesty: §D.2a's reversed() literally only requires valid_cap — so the model faithfully implements §D.2a; the finding is that §D.2a (as implemented) lets resolver-REJECTED governance permanently censor, contradicting §D.2b's "losing branch gated" and the no-censorship-primitive goal. Also that admits-reversal doesn't even require S to descend D (model omits the §5 causal rule here — that IS a model/spec mismatch: §5's causal rule appears in effective() but not in _compute_admits; §D.2a says "S superseding an adoption D" — the model treats subject==D.wid as "superseding" without the descent requirement that §5 and effective() impose). So the cleanest model-vs-§D mismatch inside F3: **a supersede that does not causally descend its target still reverses the adoption in admits**, while §D.3/§5 require descent for the same act in effective(). I'll highlight both aspects.

F4 repro (losing-branch ADOPTION admits unauthorized root):
- Same pinned setup. "RB2" genesis by X, "RBC2" child.
- "s1","s2","res" as before.
- "Dbad": root-adoption, priors {"s1"}, subject "RB2", threshold {("A","kA")} → prestate policy P1 → valid ✓.
- Full cut: admits includes RB2 (dist via Dbad: roots of Dbad closure = {RA} dist 0 → RB2 dist 1; no reversal) → effective(RBC2) True. Although selected governance (P2 lineage) never adopted RB2. VIOLATION: unauthorized root admission by rejected branch. Also assert in_lineage("s1") False, policy == P2, and Dbad valid_cap True.

Hmm — is F4 really a violation per §D? §D.2a: dist(r) := ... "1 + min{dist(root_of(D.adopting_record)) : valid_cap adoption D targets r}". valid_cap adoption — yes, Dbad is valid_cap. So §D.2a admits it. Again §D-faithful, design-level hole. The brief's property: "resolver-selected-lineage effect gating (a losing branch does not govern)". Both F3/F4 show losing branches governing layer 2a. I'll present F3 as the flagship (censorship + permanence) and F4 as its dual.

Now — wait, I should double check one thing in F4: Dbad priors {s1} — roots of closure(Dbad) = records with no priors in cut within closure = {RA} ✓ dist 0 → RB2 dist 1 ✓.

Also check RBC2 effective: active_cut: roots {RB2} ∩ admits ✓; bound filing at prestate {RB2} — keys X:kX ✓; valid_cap ✓; in_lineage ordinary True; supersedes none → True ✓.

And a control: honest world (no s1/Dbad) → RB2 not admitted, RBC2 not effective. Show delta.

F5 repro — as designed above with s3. Let me also confirm effective(s1) True in that world (no supersedes). ✓.

F6 repro (CONFLICT key fail-open):
- pinned keys {A: {K0}, B: {kB}}, policy ({A,B},2) [need policy for threshold demo], roots {g}.
- g ordinary A filing ("A","K0").
- R1: rotation A→K1 priors {g} filing ("A","K0") pop ("A","K1") → valid.
- R2: rotation A→K2 priors {g} filing ("A","K0") pop ("A","K2") → valid (prestate {g} → K0 bound ✓).
- m: keystate(full)[A] == CONFLICT (assert as premise).
- X: ordinary priors {R1,R2} actor A filing ("A", model.CONFLICT) → valid_cap? prestate keys: A→CONFLICT → _bound(A, CONFLICT) → True → valid. effective(X) True.
- Threshold demo: PS: policy-succession priors {R1,R2}, new_policy P3=({"B"},1), threshold {("A", CONFLICT), ("B","kB")}: policy at prestate = P0 ({A,B},2) → good: A (CONFLICT==CONFLICT ✓), B ✓ → 2 ≥ 2 → valid_cap(PS) True. So governance acts authorized by a "signature" on a conflicted (supposedly UNUSABLE) slot. VIOLATION: §D.2b "slot UNUSABLE".
- Also supersede demo? Keep it tight: ordinary + succession asserts suffice. Maybe also assert an honest key ("A","K1") does NOT bind (keystate CONFLICT ≠ K1) to show the asymmetry: the REAL keyholder is locked out but the marker works. Nice touch: during conflict, no real key binds, but the marker does → anyone can act as A while A cannot. Print VIOLATION.

F7 repro (None-key binds):
- pinned keys {A: {kA}} (Z has NO key), policy ({A,Z},2), roots {g}.
- g ordinary A.
- X1: ordinary actor Z, filing ("Z", None), priors {g} → _bound(Z, None): keys.get("Z") → None → None==None → True → valid_cap True, effective True. A record "authorized" by an actor with no key at all.
- PS: policy-succession priors {g}, new_policy P2=({"A"},1), threshold {("A","kA"),("Z",None)} → good = {A ✓, Z: None==None ✓} → 2 ≥ 2 → valid. A 2-of-2 policy satisfied with ONE real signature. VIOLATION: §D.1 binding / D.4 threshold semantics fail open for absent keys.
- Checkpoint angle: checkpoint_authorized(state, {("A","kA"),("Z",None)}, m) → True. Optional assert.

F8 repro (actor/filing principal confusion, P2):
- pinned {A:{kA}}, no policy needed (or policy present for quorum path), roots {g}.
- x: ordinary actor "Mallory", filing ("A","kA"), priors {g} → valid_cap True (Alice's bound key authorizes a record naming Mallory as actor).
- carried_cap(x) = SELF("Mallory").
- S_alice: supersede of x, filing ("A","kA"), priors {x} → has_self("Mallory")? filing actor A ≠ Mallory → no SELF cand; no threshold (no policy) → cands empty → valid_cap False. Alice CANNOT revoke the record her key authorized.
- S_mal: supersede of x, filing ("Mallory","kM"), priors {x} — needs Mallory bound at prestate: Mallory has no key → _bound("Mallory","kM") → keystate.get("Mallory") = None ≠ "kM" → False. Hmm! Mallory can't either (no key). So the record is unrevokable-by-SELF entirely; only JP could. The demonstrated violation: valid_cap(x) True with authorizer ≠ actor — the binding check doesn't tie the filing witness to the record's actor. §D.3 active_cut "bound actor-filing" implies the ACTOR's filing. Assert: m.valid_cap("x") and m.recs["x"].actor != m.recs["x"].filing[0] → machine accepts actor/witness mismatch. And effective(x) True. VIOLATION: §D.1/§D.3 "bound actor-filing" — the filing witness is not the record's actor. P2.

F9 (checkpoint findings): 
- F9a repro: verdict flips with verifier cut (both directions) — P1.
- F9b repro: state not bound (state arg unused) — P2. `checkpoint_authorized` returns True for a state the witnesses never signed. Show: aw signed state1 per cid1 = checkpoint_CID(state1, aw); checkpoint_authorized(state2, aw, m) == True. VIOLATION: §D.5 verify omits the sig-over-P check.
- F9c repro: duplicate CID fork at one (J, sequence) with disjoint quorums, both authorized — P2/question. Two CIDs for one sequence, no consumer-independent distinguisher. §D.5 acknowledges conflict + successor resolution, which contradicts "no successor needed". Frame as P2 with honesty.

F10 (competing resolvers brick the policy slot forever — P2, spec-conformant but a claimed-liveness issue): s1,s2 concurrent; res1, res2 both valid resolving {s1,s2} differently (res1 selects P_a, res2 selects P_b); both signed under common policy P0. Then current_JP(full) → resolvers == 2 → CONFLICT. res3 attempt: resolves {s1,s2}, priors {res1,res2}, threshold P0-signers → valid_cap(res3) True BUT _resolve_slot sees 3 resolvers → still CONFLICT. No record can unbrick. VIOLATION: of the claim that the machine is a settlement substrate... honestly this is "fail-closed" behavior and §D.2b literally says "a valid_cap resolver" (singular) selects; competing resolvers = conflict = unusable. The model matches §D. So file as... hmm. The gate wants §D violations. This is a §D-conformant liveness dead-end. The brief (attack #3) explicitly asks: "find a legitimate governance action the fail-closed default makes permanently impossible" — the class. Two honest-but-differing quorum subsets (P0 = 2-of-3: res1 by {A,B}, res2 by {A,C}) permanently brick governance; a later unanimous resolver cannot fix it. That IS the fail-closed-deadlock class they asked to hunt. Even if §D-conformant, it's a demonstrated permanent liveness failure from ordinary behavior (two quorums resolving concurrently). P1? P2? "P1 = a composition breaks, or a claimed property does not hold." Claimed property: governance recovers from conflicts via resolution ("unless a valid_cap resolver ... it selects one branch"). The composition (two concurrent resolvers, then a third) breaks: the third valid resolver cannot resolve. I'd file P1/P2 — I'll go P2 with a clear note, or P1... The deadlock is total for the jurisdiction: no policy-succession can ever be authorized again (current_JP None → thresholds fail; resolvers only add to the resolver count). Actually wait — can a policy-succession still be authorized under conflict? polv None → False. Key rotations: threshold path dead; self-rotations still work. Supersedes: SELF only. So governance is permanently frozen; only self-actions live. From ONE race. I'll say P1 (composition breaks; permanent). Let me make sure res1/res2 both valid: policy-resolution resolves {s1,s2} exactly = slot maxima at their prestates ✓; common ancestor {RA} → P0 2-of-3 {A,B,C}: res1 threshold {A,B} ✓, res2 {A,C} ✓. new_policy differs: res1→P2a=({"B"},1), res2→P2b=({"C"},1). _resolve_slot for policy at full cut: maxima {s1,s2}, resolvers = [res1,res2] → len 2 → CONFLICT ✓. res3 priors {res1,res2} resolves {s1,s2}: valid_cap: slot maxima at E_res3 = {res1,res2,s1,s2,RA}: successions {s1,s2} maxima ✓ equality ✓; common = pre_events(s1) ∩ pre_events(s2) = {RA} → P0 → threshold {B,C} ✓ → valid_cap True. But policy state: resolvers [res1,res2,res3] → len 3 → CONFLICT. Assert current_JP is None (conflict) after res3, and that no further valid record can change it — I can assert by trying res4 similarly (still 4 resolvers). Also assert policy-state None → a new policy-succession s3 priors {res3} threshold anything → valid_cap False (polv None). That demonstrates permanent brick. VIOLATION line: "§D.2b resolution composes non-recoverably: N competing resolvers cannot be out-resolved; one race permanently bricks J governance". 

Wait — actually, double-check `_policy_state` conflict → current_JP returns None: `return None if conf else (pol,pid)` ✓.

Also — could res3 instead name resolves {s1,s2,res1,res2}? slot_maxima only counts successions → mismatch → invalid. Right (idea 28). Include that assert: a resolver naming the resolvers is NOT valid_cap → no escape hatch. 

Now let me also reconsider: is there an issue with `in_lineage` for res1/res2 (policy-resolutions aren't gated — in_lineage returns True for kind policy-resolution since the check is only for policy-succession). Fine.

Let me also reconsider F5's severity vs F10's. OK.

One more sweep — **`_compute_admits` adoption validity uses `self._valid` at the record's own prestate; but adoptions from a CONFLICTED policy state: polv None → invalid. OK.

**`root_reachable` uses admits which excludes reversed; the reversal uses auth_dist 0 always — comment says "modeled as the adopting jurisdiction anchor (distance 0) when it is J's governing policy". What if cap JP but... cap.jur not checked in the reversal loop!! `cap = self.carried_cap(w); if cap and cap.kind == "JP"` — no `cap.jur == self.J` check! But carried_cap builds JP caps with jur=self.J always (`Cap("JP", ("pol", self.J), self.J, ...)`) — self.J, the Model's J. So within one Model instance all JP caps are J. OK.

But hmm — `tgt.jur != self.J: continue` — the ADOPTION must be jur J ✓.

**Cross-check `_prove_supersede_cap` threshold for JP uses `polv` = J's policy — for superseding a record of jurisdiction... records' jur vs model J: a supersede of an ordinary record with jur "K" — target.kind ordinary → has_self/has_threshold under J's policy — carried_cap of the target = SELF(actor, jur=self.J!) — carried_cap hardcodes self.J for ordinary too (`Cap("SELF", r.actor, self.J, ("record", w))`). So foreign-jurisdiction records are treated as J's. Single-J model assumption; skip.

**One more: `effective()` for w where `self._valid.get(w)` — w in recs always (Model only holds cut records). `effective` on unknown wid → KeyError from self.recs[w]... callers pass valid wids.

**Determinism of `_compute_admits` fixpoint — order-independent min — ✓.

**Now `checkpoint_CID` — `auth_root` = setcommit of AWs; `_canon(frozenset(...))` — if two witnesses identical (a,k) duplicates collapse in frozenset — fine.

Let me also sanity check F6's PS valid_cap more carefully. PS priors {R1,R2}: E = {g,R1,R2}. current_JP(E): successions in E: none → pinned P0 → (P0, ("pinned-policy","J")) → polv = P0 = ({A,B},2). keys = _key_state(E): rotations {R1,R2} → maxima {R1,R2} → resolvers: key-resolution kind, valid, resolves==maxima... none exist → CONFLICT → keys[A]=CONFLICT, keys[B]=kB (pinned, no rotations for B). threshold {("A","«CONFLICT»"),("B","kB")}: good: A: in actors ✓ keystate[A]==CONFLICT ✓; B ✓ → {A,B} → 2 ≥ 2 → True → valid_cap(PS) ✓. Then PS is a valid policy-succession. Note ALSO: after PS, policy state at full cut: successions {PS} single maximal → P3=({"B"},1). So the forged-conflict-signature succession GOVERNS. Total takeover during a key conflict: anyone can "be" A. P0 solid.

And X (ordinary with conflict key): effective True ✓. Also note R1/R2 themselves: valid (self-rotations under K0 at prestate {g}) ✓.

Also — in F6, is there a resolver-free simpler path to CONFLICT? Two concurrent rotations is the way. ✓.

F7 double-check: policy ({A,Z},2) pinned. keys: A→kA (pinned), Z→absent (None). g by A. PS priors {g}: polv = ({A,Z},2); threshold {("A","kA"),("Z",None)}: good: A ✓; Z: in actors ✓, keystate.get("Z") → None == None ✓ → {A,Z} → valid ✓. X1 ordinary actor Z filing ("Z",None): valid_cap: _bound("Z",None,keys) → True ✓; active_cut: roots {g} ✓ → effective ✓.

Also `_threshold_ok` for checkpoint: same. 

Now — are F6/F7 "crypto/serialization out of scope"? No: this is the model's authorization logic comparing derived key-state to presented keys without validating that the derived state is a real key. The model's own docstring: "a witness key is BOUND iff it is the actor's key in the relevant pre-state key-state". When the actor has NO key (or a conflict marker), NOTHING should bind.

### round 2

Emitting the runnable reproductions. Each block asserts the violating condition, so it exits 0 with a `VIOLATION:` line if and only if the machine misbehaves as charged; if the machine is correct, the block raises and exits non-zero.

```repro id=F1 severity=P0 title=conflicted key slot is fail-open — the CONFLICT marker binds as a key
import model
from model import World, Rec, Model

w = World(pinned_roots={"J": {"g"}},
          pinned_policy={"J": (frozenset({"A", "B"}), 2)},
          pinned_keys={"A": {"K0"}, "B": {"kB"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "K0")))
w.add(Rec("R1", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A",
          rot_key="K1", incoming_pop=("A", "K1"), filing=("A", "K0")))
w.add(Rec("R2", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A",
          rot_key="K2", incoming_pop=("A", "K2"), filing=("A", "K0")))
# two valid, DAG-unordered rotations => A's key-slot derives to CONFLICT ("UNUSABLE", D.2b)
w.add(Rec("X", frozenset({"R1", "R2"}), "A", "ordinary", jur="J",
          filing=("A", model.CONFLICT)))                     # 'signature' = the conflict marker
w.add(Rec("PS", frozenset({"R1", "R2"}), "B", "policy-succession", jur="J",
          new_policy=(frozenset({"B"}), 1),
          threshold=frozenset({("A", model.CONFLICT), ("B", "kB")})))
m = Model(w, frozenset(w.recs), "J")

keys = m._key_state(frozenset(m.recs))
assert keys["A"] == model.CONFLICT, "premise: slot must be conflicted"
assert m.valid_cap("R1") and m.valid_cap("R2")
# the real keys no longer bind (the slot is genuinely unusable for A) ...
assert not m._bound("A", "K1", keys) and not m._bound("A", "K2", keys)
# ... but the CONFLICT marker itself binds, for ANYONE who presents it:
assert m._bound("A", model.CONFLICT, keys)
# (1) an ordinary record 'authorized' by the marker is valid_cap AND effective
assert m.valid_cap("X")
assert m.effective("X")
# (2) the marker counts toward the governance threshold: full policy seizure
assert m.valid_cap("PS")
assert m.current_JP(frozenset(m.recs))[0] == (frozenset({"B"}), 1)
print("VIOLATION: §D.2b 'slot UNUSABLE' — a conflicted key-slot is fail-open: _bound and "
      "_threshold_ok compare a presented key against the CONFLICT marker itself, so anyone "
      "can 'sign as' the conflicted actor — an ordinary record computes effective and the "
      "2-of-2 governance threshold is satisfied (policy seized)")
```

```repro id=F2 severity=P0 title=absent key binds — a keyless actor's null key satisfies filings, thresholds, checkpoint sets
import model
from model import World, Rec, Model

w = World(pinned_roots={"J": {"g"}},
          pinned_policy={"J": (frozenset({"A", "Z"}), 2)},   # Z is IN the 2-of-2 policy ...
          pinned_keys={"A": {"kA"}})                          # ... but has NO key anywhere
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
w.add(Rec("X1", frozenset({"g"}), "Z", "ordinary", jur="J", filing=("Z", None)))
w.add(Rec("PS", frozenset({"g"}), "A", "policy-succession", jur="J",
          new_policy=(frozenset({"A"}), 1),
          threshold=frozenset({("A", "kA"), ("Z", None)})))  # one real signature + one null
m = Model(w, frozenset(w.recs), "J")

keys = m._key_state(frozenset({"g"}))
assert "Z" not in keys, "premise: Z has no bound key at all"
assert m._bound("Z", None, keys)                  # absence compares equal to a presented null
assert m.valid_cap("X1") and m.effective("X1")    # a record 'authorized' by nobody's key
assert m.valid_cap("PS")                          # 2-of-2 policy amended with ONE real signature
assert m.current_JP(frozenset(m.recs))[0] == (frozenset({"A"}), 1)

# the same null witness counts toward a checkpoint authorization set
state = {"J": "J", "sequence": 1, "frontier": ("g",), "effective_set_root": ("e",),
         "key_state_root": ("k",), "policy_state_root": ("p",), "manifest_root": ("m",)}
m_g = Model(w, frozenset({"g"}), "J")
assert model.checkpoint_authorized(state, frozenset({("A", "kA"), ("Z", None)}), m_g)
print("VIOLATION: §D.1 'BOUND iff the actor's key in the pre-state key-state' — an actor with "
      "NO key binds the null key: keystate.get(actor) is None and None==None, so keyless actors "
      "author effective records, satisfy governance thresholds (2-of-2 met with one real "
      "signature) and count toward checkpoint authorization sets — fail-open on absence")
```

```repro id=F3 severity=P0 title=resolver-REJECTED policy branch permanently censors an adopted root via layer-2a reversal
import model
from model import World, Rec, Model

P0 = (frozenset({"A", "B", "C"}), 2)
P1 = (frozenset({"A"}), 1)
P2 = (frozenset({"B", "C"}), 2)

def world(with_s1_attack=True, with_repairs=False):
    w = World(pinned_roots={"J": {"RA"}}, pinned_policy={"J": P0},
              pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}, "X": {"kX"}})
    w.add(Rec("RA", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
    w.add(Rec("RB", frozenset(), "X", "ordinary", jur="J", filing=("X", "kX")))
    w.add(Rec("RBC", frozenset({"RB"}), "X", "ordinary", jur="J", filing=("X", "kX")))
    w.add(Rec("D", frozenset({"RA"}), "B", "root-adoption", jur="J", subject="RB",
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    # honest governance fork: two P0-quorums propose P1 and P2
    w.add(Rec("s1", frozenset({"RA"}), "A", "policy-succession", jur="J", new_policy=P1,
              threshold=frozenset({("A", "kA"), ("B", "kB")})))
    w.add(Rec("s2", frozenset({"RA"}), "B", "policy-succession", jur="J", new_policy=P2,
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    # the resolver selects P2: s1's branch LOSES
    w.add(Rec("res", frozenset({"s1", "s2"}), "B", "policy-resolution", jur="J",
              new_policy=P2, resolves=frozenset({"s1", "s2"}),
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    if with_s1_attack:
        # on the DEAD branch, A alone (P1 = ({A},1)) supersedes the adoption of RB
        w.add(Rec("S1", frozenset({"s1"}), "A", "supersede", jur="J", subject="D",
                  threshold=frozenset({("A", "kA")})))
    if with_repairs:
        # the legitimate (P2) quorum revokes A's censoring supersede ...
        w.add(Rec("S2", frozenset({"res", "S1"}), "B", "supersede", jur="J", subject="S1",
                  threshold=frozenset({("B", "kB"), ("C", "kC")})))
        # ... and re-adopts RB
        w.add(Rec("D2", frozenset({"res"}), "B", "root-adoption", jur="J", subject="RB",
                  threshold=frozenset({("B", "kB"), ("C", "kC")})))
    return w

w0 = world(with_s1_attack=False)
m_clean = Model(w0, frozenset(w0.recs), "J")
assert "RB" in m_clean.admits() and m_clean.effective("RBC")     # control: no attack, branch lives

w = world()
m = Model(w, frozenset(w.recs), "J")
assert m.in_lineage("s1") is False                       # the resolver REJECTED s1's branch
assert m.current_JP(frozenset(m.recs))[0] == P2          # governance moved on
assert m.valid_cap("S1")                                 # yet the dead-branch supersede is valid_cap
assert not model.descends("S1", "D", m.recs)             # it never even descends its target
assert "RB" not in m.admits()                            # ... and it censors the root anyway
assert not m.effective("RBC")

# permanence: revoking the censor and re-adopting changes NOTHING (reversal reads valid_cap only)
w2 = world(with_repairs=True)
m2 = Model(w2, frozenset(w2.recs), "J")
assert m2.valid_cap("S2") and m2.valid_cap("D2")
assert not m2.effective("S1")                            # the censoring supersede is itself revoked
assert "RB" not in m2.admits()                           # RB stays censored forever
assert not m2.effective("RBC")
print("VIOLATION: §D.2a reversed() × §D.2b gating — layer-2a admission reads valid_cap ONLY: "
      "a supersede authorized solely by a resolver-REJECTED policy branch (which never even "
      "descends its target) reverses an adoption; revoking the censor and re-adopting cannot "
      "restore admission. A dead branch permanently censors a root and every record on it")
```

```repro id=F4 severity=P1 title=resolver-REJECTED branch admits an unauthorized root (dual of F3)
import model
from model import World, Rec, Model

P0 = (frozenset({"A", "B", "C"}), 2)
P1 = (frozenset({"A"}), 1)
P2 = (frozenset({"B", "C"}), 2)

def world(with_bad_adoption):
    w = World(pinned_roots={"J": {"RA"}}, pinned_policy={"J": P0},
              pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}, "X": {"kX"}})
    w.add(Rec("RA", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
    w.add(Rec("RB2", frozenset(), "X", "ordinary", jur="J", filing=("X", "kX")))
    w.add(Rec("RBC2", frozenset({"RB2"}), "X", "ordinary", jur="J", filing=("X", "kX")))
    w.add(Rec("s1", frozenset({"RA"}), "A", "policy-succession", jur="J", new_policy=P1,
              threshold=frozenset({("A", "kA"), ("B", "kB")})))
    w.add(Rec("s2", frozenset({"RA"}), "B", "policy-succession", jur="J", new_policy=P2,
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    w.add(Rec("res", frozenset({"s1", "s2"}), "B", "policy-resolution", jur="J",
              new_policy=P2, resolves=frozenset({"s1", "s2"}),
              threshold=frozenset({("B", "kB"), ("C", "kC")})))
    if with_bad_adoption:
        # A alone, under the DEAD branch's policy P1=({A},1), 'adopts' a foreign root
        w.add(Rec("Dbad", frozenset({"s1"}), "A", "root-adoption", jur="J", subject="RB2",
                  threshold=frozenset({("A", "kA")})))
    return w

w0 = world(False)
m0 = Model(w0, frozenset(w0.recs), "J")
assert "RB2" not in m0.admits() and not m0.effective("RBC2")   # control: no adoption, no life

w = world(True)
m = Model(w, frozenset(w.recs), "J")
assert m.in_lineage("s1") is False                     # s1's branch was REJECTED by the resolver
assert m.current_JP(frozenset(m.recs))[0] == P2        # the winning governance never adopted RB2
assert m.valid_cap("Dbad")                             # yet the dead-branch adoption is valid_cap
assert "RB2" in m.admits()                             # ... and admits the root
assert m.effective("RBC2")                             # ... making its records effective
print("VIOLATION: §D.2a dist() × §D.2b gating — root ADMISSION also reads valid_cap only: an "
      "adoption authorized solely under a resolver-REJECTED policy branch admits a root the "
      "selected governance never adopted, and records on it compute effective")
```

```repro id=F5 severity=P1 title=losing branch re-enters selected lineage once history advances past the resolver
import model
from model import World, Rec, Model

P0 = (frozenset({"A", "B"}), 2)
P1 = (frozenset({"A", "C"}), 2)
P2 = (frozenset({"B", "C"}), 2)
P3 = (frozenset({"C"}), 1)

w = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": P0},
          pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
w.add(Rec("s1", frozenset({"g"}), "A", "policy-succession", jur="J", new_policy=P1,
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
w.add(Rec("s2", frozenset({"g"}), "A", "policy-succession", jur="J", new_policy=P2,
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
w.add(Rec("res", frozenset({"s1", "s2"}), "A", "policy-resolution", jur="J",
          new_policy=P2, resolves=frozenset({"s1", "s2"}),
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
# history advances: the resolved policy P2 validly succeeds to P3, descending the resolver
w.add(Rec("s3", frozenset({"res"}), "C", "policy-succession", jur="J", new_policy=P3,
          threshold=frozenset({("B", "kB"), ("C", "kC")})))

m_tip = Model(w, frozenset({"g", "s1", "s2", "res"}), "J")
assert m_tip.in_lineage("s1") is False      # the suite's pinned property, at the resolver tip

m = Model(w, frozenset(w.recs), "J")
assert m.valid_cap("s3")
assert m.current_JP(frozenset(m.recs))[0] == P3
# the single-maximal path returns closure(s3) ∩ successions — which contains BOTH forks:
assert "s1" in m.selected_lineage_policy()
assert m.in_lineage("s1") is True            # the REJECTED succession is back in the lineage
assert m.effective("s1")                     # ... and computes effective
print("VIOLATION: §D.2b 'a losing policy branch is gated by in_lineage' — the gate holds only "
      "at the tip: once a later succession descends the resolver, selected_lineage_policy's "
      "single-maximal path returns closure(maximal), which contains BOTH forks; the rejected "
      "s1 re-enters the selected lineage and computes effective (non-monotone gating)")
```

```repro id=F6 severity=P1 title=checkpoint authorization reads the verifier's cut, not cut(P.frontier) — verdicts flip retroactively both ways
import model
from model import World, Rec, Model

# ---- direction 1: a routine signer key-rotation retroactively KILLS a pinned checkpoint
wA = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": (frozenset({"A", "B"}), 2)},
           pinned_keys={"A": {"kA"}, "B": {"kB"}})
wA.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
wA.add(Rec("R", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A", rot_key="kA2",
           incoming_pop=("A", "kA2"), filing=("A", "kA")))   # A's routine rotation kA -> kA2
state = {"J": "J", "sequence": 1, "frontier": ("g",), "effective_set_root": ("e",),
         "key_state_root": ("k",), "policy_state_root": ("p",), "manifest_root": ("m",)}
aw = frozenset({("A", "kA"), ("B", "kB")})
cid = model.checkpoint_CID(state, aw)                        # the PINNED checkpoint identity
m_at = Model(wA, frozenset({"g"}), "J")
m_later = Model(wA, frozenset({"g", "R"}), "J")
assert model.checkpoint_authorized(state, aw, m_at) is True      # authorized at the frontier
assert model.checkpoint_authorized(state, aw, m_later) is False  # same CID, same sigs -> rejected

# ---- direction 2: a below-threshold auth set becomes authorized after a policy change
wB = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": (frozenset({"A", "B"}), 2)},
           pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}, "D": {"kD"}})
wB.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
wB.add(Rec("s", frozenset({"g"}), "A", "policy-succession", jur="J",
           new_policy=(frozenset({"C", "D"}), 2),
           threshold=frozenset({("A", "kA"), ("B", "kB")})))
aw2 = frozenset({("C", "kC"), ("D", "kD")})
m_before = Model(wB, frozenset({"g"}), "J")
m_after = Model(wB, frozenset({"g", "s"}), "J")
assert model.checkpoint_authorized(state, aw2, m_before) is False  # NOT authorized at the frontier
assert model.checkpoint_authorized(state, aw2, m_after) is True    # ... authorized retroactively
print("VIOLATION: §D.5 verify must 'rebuild cut(P.frontier); derive current_JP(J)' — the "
      "machine derives policy and key-state from the VERIFIER's cut, so a pinned CID's "
      "authorization flips retroactively in both directions: a signer rotation kills a frozen "
      "checkpoint, and a below-threshold set gains authorization after a policy change. "
      "Not immutable, not consumer-independent")
```

```repro id=F7 severity=P1 title=two competing resolvers permanently brick the jurisdiction; a unanimous re-resolution is impotent
import model
from model import World, Rec, Model

P0 = (frozenset({"A", "B", "C"}), 2)
P1 = (frozenset({"A", "B"}), 2)
P2 = (frozenset({"A", "C"}), 2)

w = World(pinned_roots={"J": {"RA"}}, pinned_policy={"J": P0},
          pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}})
w.add(Rec("RA", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
w.add(Rec("s1", frozenset({"RA"}), "A", "policy-succession", jur="J", new_policy=P1,
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
w.add(Rec("s2", frozenset({"RA"}), "A", "policy-succession", jur="J", new_policy=P2,
          threshold=frozenset({("A", "kA"), ("C", "kC")})))
# two quorums, each honest under P0, resolve the same fork differently
w.add(Rec("res1", frozenset({"s1", "s2"}), "A", "policy-resolution", jur="J",
          new_policy=P1, resolves=frozenset({"s1", "s2"}),
          threshold=frozenset({("A", "kA"), ("B", "kB")})))
w.add(Rec("res2", frozenset({"s1", "s2"}), "A", "policy-resolution", jur="J",
          new_policy=P2, resolves=frozenset({"s1", "s2"}),
          threshold=frozenset({("A", "kA"), ("C", "kC")})))
# the whole electorate then tries to settle it UNANIMOUSLY
w.add(Rec("res3", frozenset({"res1", "res2"}), "A", "policy-resolution", jur="J",
          new_policy=P1, resolves=frozenset({"s1", "s2"}),
          threshold=frozenset({("A", "kA"), ("B", "kB"), ("C", "kC")})))
# ... or to resolve the resolvers themselves
w.add(Rec("res4", frozenset({"res1", "res2"}), "A", "policy-resolution", jur="J",
          new_policy=P1, resolves=frozenset({"s1", "s2", "res1", "res2"}),
          threshold=frozenset({("A", "kA"), ("B", "kB"), ("C", "kC")})))
# ... or to simply succeed the policy under the bricked state
w.add(Rec("s3", frozenset({"res3"}), "A", "policy-succession", jur="J", new_policy=P1,
          threshold=frozenset({("A", "kA"), ("B", "kB"), ("C", "kC")})))
m = Model(w, frozenset(w.recs), "J")

assert m.valid_cap("res1") and m.valid_cap("res2")
assert m.current_JP(frozenset({"RA", "s1", "s2", "res1", "res2"})) is None  # conflicted
# every recovery path is closed:
assert m.valid_cap("res3")                        # a UNANIMOUS resolver is valid_cap ...
assert m.current_JP(frozenset(m.recs)) is None    # ... and changes NOTHING (3 resolvers -> conflict)
assert not m.valid_cap("res4")                    # resolver-of-resolvers rejected (maxima = successions only)
assert not m.valid_cap("s3")                      # no succession authorizable under a conflicted policy
print("VIOLATION: §D.2b 'a valid_cap resolver ... selects one branch' is non-recoverable: two "
      "competing valid resolvers brick the policy slot, and the conflict rule only ever counts "
      "MORE resolvers — a subsequent unanimous resolution is valid_cap yet impotent, and no "
      "succession can ever be authorized again. One governance race = permanent jurisdiction "
      "deadlock (the fail-closed default fails dead)")
```

```repro id=F8 severity=P2 title=checkpoint_authorized never binds witnesses to the state (the state argument is unused)
import model
from model import World, Rec, Model

w = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": (frozenset({"A", "B"}), 2)},
          pinned_keys={"A": {"kA"}, "B": {"kB"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
m = Model(w, frozenset(w.recs), "J")

honest = {"J": "J", "sequence": 1, "frontier": ("g",), "effective_set_root": ("honest",),
          "key_state_root": ("k",), "policy_state_root": ("p",), "manifest_root": ("m",)}
forged = {"J": "J", "sequence": 1, "frontier": ("g",), "effective_set_root": ("attacker",),
          "key_state_root": ("k2",), "policy_state_root": ("p2",), "manifest_root": ("m2",)}
aw = frozenset({("A", "kA"), ("B", "kB")})

# the witnesses' AW bytes cover honest's P and ONLY honest's P:
assert model.checkpoint_CID(forged, aw) != model.checkpoint_CID(honest, aw)
# ... yet the authorization oracle vouches for the forged pairing, because it never
# looks at the state at all:
assert model.checkpoint_authorized(forged, aw, m) is True
print("VIOLATION: §D.5 verify(CID) must 'check sig_i-over-P by a key bound to actor_i' — "
      "checkpoint_authorized ignores its state argument entirely, so any policy-satisfying "
      "AW set is accepted as attesting ANY state blob; the certificate's content is unbound "
      "from its signatures at the verification layer (only an external CID comparison saves it)")
```

```repro id=F9 severity=P2 title=record actor and filing witness are never tied — authorization and identity detach
import model
from model import World, Rec, Model, Cap

w = World(pinned_roots={"J": {"g"}}, pinned_policy={"J": (frozenset({"A", "B"}), 2)},
          pinned_keys={"A": {"kA"}, "B": {"kB"}, "Mallory": {"kM"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
# a record naming Mallory as actor, authorized by ALICE's bound key
w.add(Rec("x", frozenset({"g"}), "Mallory", "ordinary", jur="J", filing=("A", "kA")))
w.add(Rec("S_alice", frozenset({"x"}), "A", "supersede", jur="J", subject="x",
          filing=("A", "kA")))
w.add(Rec("S_mal", frozenset({"x"}), "Mallory", "supersede", jur="J", subject="x",
          filing=("Mallory", "kM")))

m0 = Model(w, frozenset({"g", "x"}), "J")
assert m0.valid_cap("x") and m0.effective("x")          # the machine accepts the record
assert m0.recs["x"].actor == "Mallory" and m0.recs["x"].filing == ("A", "kA")
assert m0.carried_cap("x") == Cap("SELF", "Mallory", "J", ("record", "x"))

m1 = Model(w, frozenset(w.recs), "J")
assert not m1.valid_cap("S_alice")   # Alice, whose key AUTHORIZED x, cannot revoke it
assert m1.valid_cap("S_mal")         # Mallory, who signed NOTHING, holds the SELF right over it
print("VIOLATION: §D.1/§D.3 'bound actor-filing' — the machine checks that SOME key is bound, "
      "never that it is the record actor's: a record filed 'by' Mallory is authorized by "
      "Alice's key; the SELF capability and revocation rights attach to the non-signing actor "
      "while the actual authorizer cannot reverse it")
```

```repro id=F10 severity=P2 title=duplicate (J,sequence) CIDs from disjoint honest quorums — no consumer-independent tie-break
import model
from model import World, Rec, Model

w = World(pinned_roots={"J": {"g"}},
          pinned_policy={"J": (frozenset({"A", "B", "C", "D"}), 2)},
          pinned_keys={"A": {"kA"}, "B": {"kB"}, "C": {"kC"}, "D": {"kD"}})
w.add(Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")))
m = Model(w, frozenset(w.recs), "J")

base = {"J": "J", "sequence": 7, "effective_set_root": ("e",), "key_state_root": ("k",),
        "policy_state_root": ("p",), "manifest_root": ("m",)}
st1 = dict(base, frontier=("f1",))
st2 = dict(base, frontier=("f2",))          # same (J, sequence), different frontier
aw1 = frozenset({("A", "kA"), ("B", "kB")})
aw2 = frozenset({("C", "kC"), ("D", "kD")}) # DISJOINT quorum: no signer equivocated
cid1, cid2 = model.checkpoint_CID(st1, aw1), model.checkpoint_CID(st2, aw2)

assert cid1 != cid2
assert not {a for a, _ in aw1} & {a for a, _ in aw2}
assert model.checkpoint_authorized(st1, aw1, m) is True
assert model.checkpoint_authorized(st2, aw2, m) is True
# both CIDs verify; the machine exposes no consumer-independent rule to prefer one
print("VIOLATION: §D.5 'CID ... THE checkpoint identity' / 'consumer-independent — no successor "
      "is needed to freeze it': one (J, sequence) yields two valid CIDs over different frontiers "
      "from DISJOINT honest quorums (2-of-4, zero equivocation); the only disambiguation §D.5 "
      "offers is 'a certificate descending both' — i.e. a successor, the exact dependency the "
      "design claims to have eliminated")
```

---

```
VERDICT: REJECT

Examined: proposals/wrt-002-model/model.py (every function, line by line) and
  vectors.py; §D of proposals/WRT-002-keystate-effective-lifecycle-r1.md.
  I traced each finding above through the machine by hand before writing the
  blocks; all ten are asserted against model.py's actual semantics.

NOT examined:
  * The total manifest (attack surface #2). §D.1's "manifest witnesses" and
    §D.3's "eligible manifest entry" have NO executable counterpart in
    model.py — there is no manifest object at all. The ineligible-entry
    negative-claim attack is untestable here; filed under Questions.
  * §§0–6 prose (§D governs per the brief), wire bytes/serialization/crypto
    (out of scope per the brief), and the WRT-001 interface (the model exposes
    no authorized_effective_active_for; interface conformance is untestable
    against this machine — see Questions).
  * vectors.py beyond reading: per instructions I did not rely on its pass.

Findings (each with a runnable block above):
  F1 P0 — conflicted key-slot fails open: the CONFLICT sentinel compares equal
    to a presented key in _bound/_threshold_ok; anyone signs "as" the
    conflicted actor, authors effective records and satisfies the governance
    threshold. §D.2b says the slot is UNUSABLE.

