#!/usr/bin/env python3
"""WRT-002 rev 7 — hermetic executable REFERENCE MODEL of §D.

This is NOT the Warrant implementation and has no crypto/wire bytes. It operationalizes
the §D algebra to *execute* the §7 countervectors and prove the four properties the
rev-6 gate said prose could not settle:

  1. termination + uniqueness of the revocation / root equations;
  2. resolver-selected-lineage effect gating (a losing branch does not govern);
  3. an exhaustive, total may_reverse decision table;
  4. a finite, consumer-independent checkpoint authorization identity (CID).

Modeling choices (documented so a real impl can diverge only where noted):
  * a "signature" is a (actor, key) pair; a witness key is BOUND iff it is the actor's
    key in the relevant pre-state key-state (§D.1). No real crypto.
  * "content addressing" / hashing = canonical serialization (sorted tuples). CID uses
    the exact witness bytes so a late signature is a *different* object (§D.5).
  * a policy is (frozenset(actors), min_sigs). A threshold is satisfied by a witness set
    iff >= min_sigs distinct actors in the policy each present a bound key.

Layers are computed strictly in order (valid_cap -> admits/lineage -> effective); each
uses only earlier layers + the causal past, so there is no effective<->effective cycle.
A recursion guard turns any accidental cycle into a raised error (a failed model, not a
silent fixed-point convention).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

CONFLICT = "«CONFLICT»"     # unusable slot marker (§D.2b)


# --------------------------------------------------------------------------- capability
@dataclass(frozen=True)
class Cap:
    """§D.4 capability tuple (kind, principal, jurisdiction, slot, policy_ref)."""
    kind: str                      # 'SELF' | 'JP' | 'RP'
    principal: str                 # actor id (SELF) or policy identity (JP/RP)
    jur: Optional[str] = None
    slot: Optional[tuple] = None   # e.g. ('key', actor) | ('record', wid) | ('policy', J)
    policy_ref: Optional[tuple] = None  # the effective policy it was evaluated against


def well_formed(c: Optional[Cap]) -> bool:
    return isinstance(c, Cap) and c.kind in ("SELF", "JP", "RP") and bool(c.principal)


# ------------------------------------------------------------------------------- records
@dataclass(frozen=True)
class Rec:
    wid: str
    prior: frozenset               # parent wids
    actor: str                     # body.actor.id (the FILER)
    kind: str                      # ordinary|rotation|supersede|policy-succession|
                                   # root-adoption|key-resolution|policy-resolution
    jur: Optional[str] = None
    subject: Optional[str] = None  # target wid (supersede) / adopted root / rotated actor
    filing: Optional[tuple] = None            # (actor, key) actor-filing witness
    incoming_pop: Optional[tuple] = None      # (target_actor, new_key) rotation PoP
    threshold: frozenset = frozenset()        # frozenset of (actor, key) quorum witnesses
    rot_actor: Optional[str] = None           # actor whose key-slot a rotation targets
    rot_key: Optional[str] = None             # the new key
    new_policy: Optional[tuple] = None        # (frozenset(actors), min_sigs) for succession
    resolves: frozenset = frozenset()         # wids of the maxima a resolver descends


@dataclass
class World:
    # trust config (§0/§5.5): per jurisdiction J -> pinned genesis root WIDs + governing
    # policy; actor -> pinned keys. A jurisdiction with no pinned policy is not
    # checkpoint-capable (§5.5); its policy is None.
    pinned_roots: dict = field(default_factory=dict)    # J -> set(root_wid)
    pinned_policy: dict = field(default_factory=dict)   # J -> (frozenset(actors), min_sigs) | None
    pinned_keys: dict = field(default_factory=dict)     # actor -> set(key)
    recs: dict = field(default_factory=dict)            # wid -> Rec

    def add(self, r: Rec):
        self.recs[r.wid] = r
        return r.wid


# ----------------------------------------------------------------------- causal helpers
def closure(w: str, recs: dict) -> frozenset:
    seen, stack = set(), [w]
    while stack:
        x = stack.pop()
        if x in seen or x not in recs:
            continue
        seen.add(x)
        stack.extend(recs[x].prior)
    return frozenset(seen)


def pre_events(w: str, recs: dict) -> frozenset:
    return closure(w, recs) - {w}


def toposort(recs: dict):
    order, seen = [], set()

    def visit(w):
        if w in seen or w not in recs:
            return
        seen.add(w)
        for p in sorted(recs[w].prior):      # sorted only for a stable *listing*; the
            visit(p)                         # algebra is order-independent (asserted)
        order.append(w)
    for w in sorted(recs):
        visit(w)
    return order


def descends(a: str, b: str, recs: dict) -> bool:
    """a strictly causally descends b (b in a's strict past)."""
    return b in pre_events(a, recs)


def well_formed_policy(policy) -> bool:
    """A governing policy must be able to bind somebody, and be satisfiable.

    rev 7 placed no constraint on `(actors, min_sigs)`, and a single legitimate
    policy-succession could therefore end a jurisdiction two ways, both found by
    running the machine rather than reading it:

      * ABDICATION -- succeed to `(frozenset(), 0)`. Every threshold check then
        passes vacuously: a stranger with no witnesses at all can adopt roots and
        succeed the policy again. The jurisdiction is permanently open.
      * BRICKING -- succeed to `min_sigs > |actors|`. No witness set can ever
        satisfy it, so nothing is authorizable again -- including the
        policy-succession that would undo it. This is the liveness self-destruct
        class that killed a predecessor of rev 6.

    Both are refused here, fail-closed, at the only place that matters: a policy
    that is not well-formed authorizes nothing, so a succession INTO one cannot
    be authorized by the policy it would replace either.
    """
    if not policy:
        return False
    try:
        actors, need = policy
    except (TypeError, ValueError):
        return False
    if not isinstance(need, int) or isinstance(need, bool):
        return False
    return bool(actors) and 1 <= need <= len(actors)


# ========================================================================= THE MACHINE
class Model:
    def __init__(self, world: World, cut: frozenset, J: str):
        self.w = world
        self.recs = {k: v for k, v in world.recs.items() if k in cut}
        self.J = J
        self._valid = {}
        self._eff = {}
        self._eff_stack = set()          # recursion guard (termination proof)
        self._order = toposort(self.recs)
        # Layer 1 then Layer 2, in dependency order:
        for w in self._order:
            self._valid[w] = self._compute_valid_cap(w)
        self._admits = self._compute_admits()          # Layer 2a
        # Layer 2b (selected lineage of the whole cut) is derived on demand from valid_cap.

    # ---- policy / key state over an event set (§D.2b), from valid_cap only ----
    def _policy_state(self, E: frozenset):
        """(policy, policy_id, conflicted) for J over event set E."""
        succ = [w for w in E if self.recs[w].kind == "policy-succession"
                and self.recs[w].jur == self.J and self._valid.get(w)]
        return self._resolve_slot(E, succ, base=self.w.pinned_policy.get(self.J),
                                  base_id=("pinned-policy", self.J),
                                  value=lambda w: self.recs[w].new_policy,
                                  ident=lambda w: ("policy", w))

    def _key_state(self, E: frozenset):
        """actor -> (key | CONFLICT). Latest valid_cap rotation wins; resolver breaks ties."""
        out = dict(self.w.pinned_keys)  # actor -> set(key); normalize to single below
        out = {a: (next(iter(ks)) if len(ks) == 1 else CONFLICT) for a, ks in out.items()}
        rots = [w for w in E if self.recs[w].kind == "rotation" and self._valid.get(w)]
        by_actor = {}
        for w in rots:
            by_actor.setdefault(self.recs[w].rot_actor, []).append(w)
        for actor, ws in by_actor.items():
            val, _id, conf = self._resolve_slot(
                E, ws, base=out.get(actor), base_id=("pinned-key", actor),
                value=lambda w: self.recs[w].rot_key, ident=lambda w: ("key", w),
                kind="key-resolution")
            out[actor] = CONFLICT if conf else val
        return out

    def _slot_maxima(self, E: frozenset, res_kind: str, actor=None) -> set:
        """The competing forks a resolver of `res_kind` may legitimately resolve.

        Same filtering as _policy_state / _key_state, so a resolver cannot claim
        to settle a fork set that the slot does not actually have.
        """
        if res_kind == "policy-resolution":
            trans = [w for w in E if self.recs[w].kind == "policy-succession"
                     and self.recs[w].jur == self.J and self._valid.get(w)]
        else:
            trans = [w for w in E if self.recs[w].kind == "rotation"
                     and self.recs[w].rot_actor == actor and self._valid.get(w)]
        return {w for w in trans
                if not any(w2 != w and descends(w2, w, self.recs) for w2 in trans)}

    def _resolve_slot(self, E, transitions, base, base_id, value, ident,
                      kind="policy-resolution"):
        """Shared maximal-succession + resolver logic (§D.2b). Returns (value, id, conflicted)."""
        if not transitions:
            return base, base_id, False
        maxima = [w for w in transitions
                  if not any(w2 != w and descends(w2, w, self.recs) for w2 in transitions)]
        if len(maxima) == 1:
            return value(maxima[0]), ident(maxima[0]), False
        # >=2 maximal, DAG-unordered => conflict unless a valid_cap resolver descends ALL
        resolvers = [w for w in E if self.recs[w].kind == kind and self._valid.get(w)
                     and set(maxima) == set(self.recs[w].resolves)
                     and all(descends(w, m, self.recs) for m in maxima)]
        if len(resolvers) == 1:
            return value(resolvers[0]), ident(resolvers[0]), False
        return None, None, True      # unresolved (or competing resolvers) => CONFLICT

    def selected_lineage_policy(self):
        """policy-succession wids ON the selected lineage (§D.2b): the chain to the chosen
        policy — a resolver's LOSING branch is excluded (not merely everything it descends)."""
        E = frozenset(self.recs)
        succ = [w for w in E if self.recs[w].kind == "policy-succession" and self._valid.get(w)]
        if not succ:
            return set()
        maxima = [w for w in succ
                  if not any(w2 != w and descends(w2, w, self.recs) for w2 in succ)]
        if len(maxima) == 1:
            return closure(maxima[0], self.recs) & set(succ)
        resolvers = [w for w in E if self.recs[w].kind == "policy-resolution"
                     and self._valid.get(w) and set(maxima) <= set(self.recs[w].resolves)
                     and all(descends(w, m, self.recs) for m in maxima)]
        if len(resolvers) != 1:
            return set()             # conflicted / competing resolvers
        res = resolvers[0]
        chosen = self.recs[res].new_policy
        lineage = {res}
        for m in maxima:
            if self.recs[m].new_policy == chosen:        # the SELECTED branch only
                lineage |= (closure(m, self.recs) & set(succ))
        return lineage

    def in_lineage(self, w: str) -> bool:
        """§D.2b: w's authorizing policy transition is on the selected lineage."""
        r = self.recs[w]
        if r.kind == "policy-succession":
            sel = self.selected_lineage_policy()
            return (w in sel) if sel else (not self._conflicted_policy())
        return True    # ordinary/rotation/supersede gated via their basis in effective()

    def _conflicted_policy(self):
        _, _, conf = self._policy_state(frozenset(self.recs))
        return conf

    def current_JP(self, prestate: frozenset):
        pol, pid, conf = self._policy_state(prestate)
        return None if conf else (pol, pid)

    # ---- Layer 1: valid_cap (§D.1) ----
    def _threshold_ok(self, witnesses, policy, keystate):
        if not well_formed_policy(policy):
            return False
        actors, need = policy
        good = {a for (a, k) in witnesses if a in actors and self._bound(a, k, keystate)}
        return len(good) >= need

    def _bound(self, actor, key, keystate):
        """A key is BOUND iff it IS the actor's key in the relevant pre-state (§D.1).

        Two ways this compared equal when nothing was bound at all — both found by
        an adversarial gate (Kimi K3, F1 and F2, both reproduced), both fail-OPEN,
        and both present since rev 1:

          * `keystate[actor]` is the string CONFLICT when the slot is unusable, and
            a plain `==` let a filer present CONFLICT *as their key*. §D.2b says a
            conflicted slot is UNUSABLE; instead it was usable by anyone. An
            ordinary record "signed" with the marker computed `effective`, and a
            2-of-2 policy-succession carrying the marker plus one real signature
            seized the jurisdiction.
          * `keystate.get(actor)` is `None` for an actor with no key, and
            `None == None` is True — so `(Z, None)` was "bound" for every keyless
            Z. Keyless actors authored effective records, satisfied governance
            thresholds, and counted toward checkpoint authorization.

        Binding now requires a key that exists, is not the conflict marker, and
        matches. Absence and conflict are refusals, not wildcards.
        """
        if key is None or key == CONFLICT:
            return False
        cur = keystate.get(actor)
        if cur is None or cur == CONFLICT:
            return False
        return cur == key

    def _compute_valid_cap(self, w: str) -> bool:
        r = self.recs[w]
        E = pre_events(w, self.recs)
        keys = self._key_state(E)
        pol = self.current_JP(E)
        polv = pol[0] if pol else None
        if r.kind == "ordinary":
            # The filing key must be the RECORD ACTOR's. Checking only that *some*
            # key is bound detaches authorization from identity (Kimi K3, F9,
            # reproduced): a record naming Mallory as actor was authorized by
            # Alice's key, so the SELF capability and the right to revoke attached
            # to the non-signing Mallory while Alice, who actually authorized it,
            # could not reverse it. Rotations are exempt on purpose -- a bound
            # quorum filer rotating someone else's compromised key is the
            # emergency-recovery path, and it carries RP, not SELF.
            return bool(r.filing and r.filing[0] == r.actor
                        and self._bound(*r.filing, keys))
        if r.kind == "root-adoption":
            return self._threshold_ok(r.threshold, polv, keys)
        if r.kind == "policy-succession":
            # Refuse at FILING time, not merely at use time: a succession into an
            # unusable policy would otherwise be recorded as authorized and only
            # reveal itself later as a jurisdiction that can no longer act.
            if not well_formed_policy(r.new_policy):
                return False
            return self._threshold_ok(r.threshold, polv, keys)   # current policy at pre-state
        if r.kind in ("policy-resolution", "key-resolution"):
            # A resolver is authorized by the PRE-CONFLICT (greatest common
            # causal-predecessor) policy of the maxima it resolves, NOT the
            # conflicted merged state (§D.2b).
            #
            # That fold is only sound if `resolves` names EXACTLY the competing
            # forks. rev 7 required merely `maxima <= resolves`, and computed the
            # intersection over `resolves` — so a filer could pad the set with any
            # record anchored near genesis and drag the "greatest common
            # predecessor" back to a policy-state under which they still held
            # authority. Found by an adversarial gate (Gemini 3.1 Pro, F1,
            # reproduced): an actor whose authority a policy-succession had
            # already removed padded `resolves` with one ordinary record of its
            # own, and thereby seized the resolution of ANOTHER actor's key
            # conflict, dictating that actor's key.
            #
            # So the set is now pinned three ways before the fold: same slot,
            # same jurisdiction, and exactly the maxima at the resolver's own
            # pre-state. Fail closed on every mismatch.
            if r.kind == "policy-resolution" and not well_formed_policy(r.new_policy):
                return False                      # same rule as a succession
            slot_kinds = ({"policy-succession", "policy-resolution"}
                          if r.kind == "policy-resolution" else
                          {"rotation", "key-resolution"})
            tgt = list(r.resolves)
            if not tgt or any(x not in self.recs for x in tgt):
                return False                      # names something outside the cut
            if any(self.recs[x].kind not in slot_kinds for x in tgt):
                return False                      # padding with an unrelated record
            if any(self.recs[x].jur != r.jur for x in tgt):
                return False                      # padding from another jurisdiction
            actor = None
            if r.kind == "key-resolution":
                actors = {self.recs[x].rot_actor for x in tgt}
                if len(actors) != 1:
                    return False                  # a resolver addresses ONE key slot
                actor = next(iter(actors))
            if set(tgt) != self._slot_maxima(E, r.kind, actor):
                return False                      # not exactly the competing forks
            pres = [pre_events(x, self.recs) for x in tgt]
            common = frozenset.intersection(*pres)
            pol_pre = self.current_JP(common)
            keys_pre = self._key_state(common)
            return self._threshold_ok(r.threshold, pol_pre[0] if pol_pre else None, keys_pre)
        if r.kind == "rotation":
            pop = bool(r.incoming_pop and r.incoming_pop == (r.rot_actor, r.rot_key))
            if not pop:
                return False
            # threshold by governing policy, OR a bound key of the SAME actor (self-rot)
            if self._threshold_ok(r.threshold, polv, keys):
                return True
            return bool(r.filing and r.filing[0] == r.rot_actor and self._bound(*r.filing, keys))
        if r.kind == "supersede":
            cap = self._prove_supersede_cap(w, E, keys, polv)
            return cap is not None
        return False

    def valid_cap(self, w):
        return self._valid[w]

    # ---- capability carried / proven (§D.4/§D.5) ----
    def carried_cap(self, w: str) -> Optional[Cap]:
        r = self.recs[w]
        if r.kind == "ordinary":
            return Cap("SELF", r.actor, self.J, ("record", w))
        if r.kind == "rotation":
            return Cap("RP", ("keypol", self.J), self.J, ("key", r.rot_actor))
        if r.kind in ("root-adoption", "policy-succession",
                      "policy-resolution", "key-resolution"):
            return Cap("JP", ("pol", self.J), self.J, ("gov", self.J))
        if r.kind == "supersede":
            E = pre_events(w, self.recs)
            return self._prove_supersede_cap(w, E, self._key_state(E), self._pol_val(E))
        return None

    def _pol_val(self, E):
        p = self.current_JP(E)
        return p[0] if p else None

    def _prove_supersede_cap(self, w, E, keys, polv) -> Optional[Cap]:
        """The capability this supersede exercises against its target, per the §5 TARGET
        ROLE, checked with §D.4 may_reverse (or None if it cannot authorize the reversal)."""
        r = self.recs[w]
        target = self.recs.get(r.subject)
        if target is None:
            return None
        tcap = self.carried_cap(r.subject)

        def has_self(actor):
            return bool(r.filing and r.filing[0] == actor and self._bound(*r.filing, keys))

        def has_threshold():
            return self._threshold_ok(r.threshold, polv, keys)

        cands = []
        if target.kind == "ordinary":
            if has_self(target.actor):
                cands.append(Cap("SELF", target.actor, self.J, ("record", r.subject)))
            if has_threshold():
                cands.append(Cap("JP", ("pol", self.J), self.J, ("gov", self.J), policy_ref=polv))
        elif target.kind == "rotation":
            slot = ("key", target.rot_actor)     # RP: J key-policy threshold, OR the slot
            if has_threshold() or has_self(target.rot_actor):   # actor's own bound key (no policy)
                cands.append(Cap("RP", ("keypol", self.J), self.J, slot, policy_ref=polv))
        elif target.kind in ("root-adoption", "policy-succession",
                              "policy-resolution", "key-resolution"):
            if has_threshold():
                cands.append(Cap("JP", ("pol", self.J), self.J, ("gov", self.J), policy_ref=polv))
        elif target.kind == "supersede":     # inherit: no weaker than the class X exercised
            if r.filing and self._bound(*r.filing, keys):
                cands.append(Cap("SELF", r.filing[0], self.J, tcap.slot if tcap else None))
            if has_threshold():
                cands.append(Cap("JP", ("pol", self.J), self.J, ("gov", self.J), policy_ref=polv))
                if tcap and tcap.kind == "RP":
                    cands.append(Cap("RP", ("keypol", self.J), self.J, tcap.slot, policy_ref=polv))
        for c in cands:
            if may_reverse(c, tcap, self, E, r.subject):
                return c
        return None

    # ---- Layer 2a: admits(J) path-aware distance strata (§D.2a) ----
    def _root_of(self, w):
        cl = closure(w, self.recs)
        roots = [x for x in cl if not (self.recs[x].prior & set(self.recs))]
        return roots

    def _compute_admits(self):
        dist = {r: 0 for r in self.w.pinned_roots.get(self.J, set())}  # genesis, distance 0
        adoptions = [w for w in self.recs if self.recs[w].kind == "root-adoption"
                     and self.recs[w].jur == self.J and self._valid.get(w)]
        # iterate to a distance fixpoint (monotone: distances only shrink toward min-path)
        changed = True
        while changed:
            changed = False
            for w in adoptions:
                B = self.recs[w].subject
                adopting_roots = self._root_of(w)
                d_adopt = min((dist.get(r, float("inf")) for r in adopting_roots),
                              default=float("inf"))
                if d_adopt == float("inf"):
                    continue
                nd = d_adopt + 1
                if nd < dist.get(B, float("inf")):
                    dist[B] = nd
                    changed = True
        # reversals: a valid_cap supersede of an adoption D targeting r, JP(J), whose
        # authority distance < dist(r). Authority distance = distance of the roots the
        # supersede's THRESHOLD keys are bound under — modeled as the adopting jurisdiction
        # anchor (distance 0) when it is J's governing policy.
        reversed_roots = set()
        for w in self.recs:
            r = self.recs[w]
            if r.kind != "supersede" or not self._valid.get(w):
                continue
            tgt = self.recs.get(r.subject)
            if tgt is None or tgt.kind != "root-adoption" or tgt.jur != self.J:
                continue
            B = tgt.subject
            cap = self.carried_cap(w)
            if cap and cap.kind == "JP":
                auth_dist = 0            # J's governing policy is genesis-anchored
                if auth_dist < dist.get(B, float("inf")):
                    reversed_roots.add(B)
        return frozenset({r for r, d in dist.items() if d < float("inf")} - reversed_roots)

    def admits(self):
        return self._admits

    def root_reachable(self, w):
        cl = closure(w, self.recs)
        return bool({x for x in cl if not (self.recs[x].prior & set(self.recs))} & self._admits)

    def active_cut(self, w):
        r = self.recs[w]
        if not self.root_reachable(w):
            return False
        if r.kind == "ordinary":                    # bound actor-filing (§4)
            keys = self._key_state(pre_events(w, self.recs))
            return bool(r.filing and self._bound(*r.filing, keys))
        return self._valid.get(w, False)            # transitions: valid_cap is eligibility

    # ---- Layer 3: effective (§D.3), reverse recurrence with termination guard ----
    def effective(self, w: str) -> bool:
        if w in self._eff:
            return self._eff[w]
        if w in self._eff_stack:
            raise RuntimeError(f"NON-WELL-FOUNDED effective() cycle at {w}")
        self._eff_stack.add(w)
        try:
            r = self.recs[w]
            ok = self.active_cut(w) and self._valid.get(w, False) and self.in_lineage(w)
            if ok:
                for s in self.recs:
                    S = self.recs[s]
                    if S.kind == "supersede" and S.subject == w and self._valid.get(s):
                        if not descends(s, w, self.recs):     # §5 causal rule
                            continue
                        if self.effective(s) and may_reverse(
                                self.carried_cap(s), self.carried_cap(w), self,
                                pre_events(s, self.recs), w):
                            ok = False
                            break
            self._eff[w] = ok
            return ok
        finally:
            self._eff_stack.discard(w)

    def effective_set(self):
        return frozenset(w for w in self.recs
                         if self.recs[w].kind == "ordinary" and self.effective(w))

    # ---- canonical serialization for determinism checks ----
    def canonical(self):
        E = frozenset(self.recs)
        keys = self._key_state(E)
        pol = self.current_JP(E)
        return (
            ("admits", tuple(sorted(self._admits))),
            ("keys", tuple(sorted(keys.items()))),
            ("policy", pol[1] if pol else CONFLICT),
            ("effective", tuple(sorted(self.effective_set()))),
            ("valid", tuple(sorted(w for w in self.recs if self._valid.get(w)))),
        )


# ============================================================ §D.4 may_reverse (TOTAL)
def _current_JP_id(model: "Model", prestate):
    p = model.current_JP(prestate)
    return p[1] if p else None


def _same_policy_lineage(model, a_principal, b_principal, prestate):
    # in this model all JP principals for a jurisdiction share ("pol", J); lineage identity
    # is the *current* selected policy id, so same-jurisdiction JP compares equal.
    return a_principal == b_principal


def may_reverse(new: Optional[Cap], prior: Optional[Cap], model, prestate, target_wid) -> bool:
    """§D.4 closed decision table. TOTAL: every (prior.kind × new) -> exactly one Bool."""
    if not well_formed(new) or not well_formed(prior):
        return False
    if prior.kind == "SELF":
        if new.kind == "SELF":
            return new.principal == prior.principal          # same actor ONLY
        if new.kind == "JP":
            return (new.jur == prior.jur
                    and new.policy_ref == (model.current_JP(prestate) or (None,))[0])
        return False
    if prior.kind == "JP":
        return (new.kind == "JP" and new.jur == prior.jur
                and _same_policy_lineage(model, new.principal, prior.principal, prestate)
                and new.policy_ref == (model.current_JP(prestate) or (None,))[0])
    if prior.kind == "RP":
        # same jurisdiction + same governed key-slot. "Current, not historical" is already
        # enforced upstream: the RP capability is proven against pre-state key-state.
        return new.kind == "RP" and new.jur == prior.jur and new.slot == prior.slot
    return False


# ============================================================ §D.5 checkpoint CID
def sign_over(state: dict, actor: str, key: str):
    """An authorization witness: the signature is over THIS state, and says so.

    A witness used to be a bare `(actor, key)` pair, which is a claim about
    identity and nothing about what was attested. Carrying the signed object
    makes `checkpoint_authorized` able to refuse a witness set lifted from
    another checkpoint.
    """
    return (actor, key, ("sig-over", _canon(state)))


def checkpoint_CID(state: dict, auth_witnesses: frozenset):
    """CID = hash(P, auth_root). P hashes the state; each AW hashes its (actor,key,sig-over-P)
    bytes, so a late/extra signature is a *different* AW outside auth_root. Consumer- and
    successor-independent."""
    P = _canon(state)
    auth_root = _canon(frozenset(
        _canon(("AW", aw[0], aw[1], aw[2] if len(aw) > 2 else ("sig-over", P)))
        for aw in auth_witnesses))
    return _canon(("CID", P, auth_root))


def checkpoint_authorized(state, auth_witnesses, model: "Model") -> bool:
    """The AW set must satisfy J's governing policy AS OF cut(P.frontier), with each
    signer's key BOUND at that same cut, and each signature taken over THIS P.

    Two defects an adversarial gate reproduced here (Kimi K3, F6 and F8):

      * §D.5 says "rebuild `cut(P.frontier)`", and this read the VERIFIER's whole
        cut instead. So a pinned, fully-authorized CID stopped verifying after a
        routine signer rotation, and a below-threshold set became authorized
        after a later policy-succession. The CID bytes were frozen; the verdict
        was not — which is exactly the immutability and consumer-independence
        §D.5 claims.
      * the `state` argument was never read, so a policy-satisfying witness set
        attested ANY state blob: the witnesses were bound to nothing. Only an
        external CID comparison tied content to signatures, which means the
        oracle alone could not tell a real checkpoint from a substituted one.

    Both are closed by evaluating at the frontier and requiring each witness to
    carry `("sig-over", P)` for the P being verified.
    """
    frontier = state.get("frontier") if isinstance(state, dict) else None
    if not frontier:
        return False                      # a checkpoint with no frontier authorizes nothing
    E = frozenset()
    for w in frontier:
        if w not in model.recs:
            return False                  # frontier cites a record outside the cut
        E |= closure(w, model.recs)
    pol = model.current_JP(E)
    if not pol:
        return False
    keys = model._key_state(E)

    P = _canon(state)
    plain = set()
    for aw in auth_witnesses:
        if len(aw) == 2:                  # (actor, key) — a signature over nothing
            return False
        actor, key, sig = aw
        if sig != ("sig-over", P):        # signed a DIFFERENT state
            return False
        plain.add((actor, key))
    return model._threshold_ok(frozenset(plain), pol[0], keys)


def _canon(x):
    """Deterministic content-addressing stand-in (stable across runs/orders)."""
    if isinstance(x, (frozenset, set)):
        return ("set", tuple(sorted((_canon(e) for e in x), key=repr)))
    if isinstance(x, (list, tuple)):
        return ("seq", tuple(_canon(e) for e in x))
    if isinstance(x, dict):
        return ("map", tuple(sorted((( _canon(k), _canon(v)) for k, v in x.items()), key=repr)))
    return x
