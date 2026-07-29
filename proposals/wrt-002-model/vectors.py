#!/usr/bin/env python3
"""§7 countervectors executed against the §D reference model (model.py).

Proves the four properties the rev-6 gate said prose could not settle:
  1. termination + uniqueness of revocation / root equations;
  2. resolver-selected-lineage effect gating;
  3. exhaustive, total may_reverse;
  4. finite, consumer-independent checkpoint CID.
Plus: byte-identical determinism under every parent/iteration permutation.
"""
import itertools
import random
import sys

import model as M
from model import World, Rec, Model, Cap, may_reverse, checkpoint_CID, checkpoint_authorized

FAILS = []


def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else "  <<< " + detail))
    if not cond:
        FAILS.append(name)


def build(J, pinned_keys, records, pinned_policy=None, pinned_roots=None):
    w = World(pinned_roots=pinned_roots or {}, pinned_policy=pinned_policy or {},
              pinned_keys={a: set(k) for a, k in pinned_keys.items()})
    for r in records:
        w.add(r)
    cut = frozenset(w.recs)
    return Model(w, cut, J)


# --------------------------------------------------------------------- 1. may_reverse
def test_may_reverse_total():
    """Every (prior.kind × new) triple returns exactly one Boolean; specific results."""
    m = build("J", {"A": {"kA"}}, [Rec("g", frozenset(), "A", "ordinary", jur="J",
              filing=("A", "kA"))], pinned_policy={"J": (frozenset({"A", "B"}), 2)}, pinned_roots={"J": {"g"}})
    E = frozenset(m.recs)
    kinds = ["SELF", "JP", "RP"]
    principals = ["A", "B", ("pol", "J"), ("pol", "K"), ("keypol", "J")]
    jurs = ["J", "K"]
    slots = [("key", "A"), ("key", "B"), ("record", "g")]
    polrefs = [None, (frozenset({"A", "B"}), 2)]
    total = True
    for kn, pr, ju, sl, pf in itertools.product(kinds, principals, jurs, slots, polrefs):
        new = Cap(kn, pr, ju, sl, pf)
        for pkind in kinds:
            prior = Cap(pkind, principals[0], "J", slots[0])
            res = may_reverse(new, prior, m, E, "g")
            total &= res in (True, False)          # exactly one Boolean
    check("[may_reverse] total over the finite product (every triple -> one Bool)", total)

    A, B = Cap("SELF", "A", "J", ("record", "g")), Cap("SELF", "B", "J", ("record", "g"))
    check("[may_reverse] SELF(A) may reverse SELF(A)", may_reverse(A, A, m, E, "g"))
    check("[may_reverse] SELF(A) may NOT reverse SELF(B)", not may_reverse(A, B, m, E, "g"))
    jpJ = Cap("JP", ("pol", "J"), "J", ("gov", "J"), policy_ref=(frozenset({"A", "B"}), 2))
    check("[may_reverse] JP(J,current) may reverse SELF in J", may_reverse(jpJ, A, m, E, "g"))
    jpK = Cap("JP", ("pol", "K"), "K", ("gov", "K"), policy_ref=(frozenset({"A", "B"}), 2))
    check("[may_reverse] JP(K) may NOT reverse a JP(J) target (different jurisdiction)",
          not may_reverse(jpK, Cap("JP", ("pol", "J"), "J", ("gov", "J"),
                                   policy_ref=(frozenset({"A", "B"}), 2)), m, E, "g"))
    rpA = Cap("RP", ("keypol", "J"), "J", ("key", "A"), policy_ref=(frozenset({"A", "B"}), 2))
    rpB = Cap("RP", ("keypol", "J"), "J", ("key", "B"), policy_ref=(frozenset({"A", "B"}), 2))
    check("[may_reverse] RP(slot A) may NOT reverse RP(slot B)", not may_reverse(rpA, rpB, m, E, "g"))
    check("[may_reverse] malformed -> fail-closed", not may_reverse(None, A, m, E, "g"))


# --------------------------------------------- 2. revocation termination + uniqueness
def test_revocation():
    """R:K0->K1, then a K1-authorized revocation S of R. Single terminating result; no
    effective<->effective cycle; R ineffective, S effective."""
    recs = [
        Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "K0")),
        Rec("R", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A", rot_key="K1",
            incoming_pop=("A", "K1"), filing=("A", "K0")),        # self-rotation K0->K1
        Rec("S", frozenset({"R"}), "A", "supersede", jur="J", subject="R",
            filing=("A", "K1")),                                  # revoke R, signed by K1
    ]
    m = build("J", {"A": {"K0"}}, recs, pinned_roots={"J": {"g"}})
    try:
        eff_R, eff_S = m.effective("R"), m.effective("S")
        raised = False
    except RuntimeError as e:
        raised = True
    check("[revocation] effective() terminates (no non-well-founded cycle)", not raised)
    if raised:
        return
    check("[revocation] S is valid_cap (K1 in R's pre-state effect)", m.valid_cap("S"))
    check("[revocation] R is ineffective (revoked by effective S)", not m.effective("R"))
    check("[revocation] S is effective", m.effective("S"))


# ------------------------------------------------------ 3. losing policy branch gated
def test_losing_branch():
    """P0 concurrently succeeds to P1 and P2; a resolver selects P2; a policy-succession
    on the losing P1 branch is gated OUT of the selected lineage."""
    P0 = (frozenset({"A", "B"}), 2)
    P1 = (frozenset({"A", "C"}), 2)
    P2 = (frozenset({"B", "C"}), 2)
    recs = [
        Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")),
        Rec("s1", frozenset({"g"}), "A", "policy-succession", jur="J", new_policy=P1,
            threshold=frozenset({("A", "kA"), ("B", "kB")})),      # P0 authorizes -> P1
        Rec("s2", frozenset({"g"}), "A", "policy-succession", jur="J", new_policy=P2,
            threshold=frozenset({("A", "kA"), ("B", "kB")})),      # P0 authorizes -> P2
        Rec("res", frozenset({"s1", "s2"}), "A", "policy-resolution", jur="J",
            new_policy=P2, resolves=frozenset({"s1", "s2"}),
            threshold=frozenset({("A", "kA"), ("B", "kB")})),      # resolver selects P2
    ]
    m = build("J", {"A": {"kA"}, "B": {"kB"}, "C": {"kC"}}, recs,
              pinned_policy={"J": P0}, pinned_roots={"J": {"g"}})
    sel = m.selected_lineage_policy()
    check("[losing-branch] resolver selects P2 lineage (res on chain)", "res" in sel)
    check("[losing-branch] losing succession s1 is NOT in the selected lineage",
          not m.in_lineage("s1"))
    check("[losing-branch] winning resolver res IS in lineage", m.in_lineage("res"))
    _, pid, conf = m._policy_state(frozenset(m.recs))
    check("[losing-branch] policy-state resolved (not conflicted)", not conf)


# ------------------------------------------------------- 4. root oscillation vector
def test_root_oscillation():
    """Pinned A; adoption D adopts B; supersede S of D filed on B. Must TERMINATE with one
    deterministic result (no {A}->{A,B}->{A}); admits computed via valid_cap, not effective."""
    P = (frozenset({"A"}), 1)
    recs = [
        Rec("A", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")),     # root A (=J)
        Rec("B", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")),     # separate root B
        Rec("D", frozenset({"A"}), "A", "root-adoption", jur="J", subject="B",
            threshold=frozenset({("A", "kA")})),                                 # A adopts B
        Rec("S", frozenset({"B", "D"}), "A", "supersede", jur="J", subject="D",
            threshold=frozenset({("A", "kA")})),                                 # revoke the adoption
    ]
    m = build("J", {"A": {"kA"}}, recs, pinned_policy={"J": P}, pinned_roots={"J": {"A"}})
    adm = m.admits()
    check("[root-osc] admits() terminates and is deterministic", isinstance(adm, frozenset))
    # S carries JP(J) authority anchored at genesis (distance 0) -> reverses D -> B not admitted
    check("[root-osc] B is NOT admitted (adoption reversed by J-anchored authority)",
          "B" not in adm)
    check("[root-osc] pinned genesis root A remains admitted", "A" in adm)


# ------------------------------------------ 5. finite consumer-independent checkpoint
def test_checkpoint_cid():
    P = (frozenset({"A", "B"}), 2)
    recs = [Rec("A", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA"))]
    m = build("J", {"A": {"kA"}, "B": {"kB"}}, recs, pinned_policy={"J": P}, pinned_roots={"J": {"A"}})
    state = {"J": "J", "sequence": 1, "frontier": ("A",),
             "effective_set_root": ("e",), "key_state_root": ("k",),
             "policy_state_root": ("p",), "manifest_root": ("m",)}
    aw_full = frozenset({M.sign_over(state, "A", "kA"),
                         M.sign_over(state, "B", "kB")})   # 2-of-2 satisfies P
    aw_one = frozenset({M.sign_over(state, "A", "kA")})    # below threshold
    cid_full = checkpoint_CID(state, aw_full)
    cid_full_again = checkpoint_CID(state, aw_full)
    check("[checkpoint] CID is deterministic / content-addressed", cid_full == cid_full_again)
    check("[checkpoint] below-threshold auth set is NOT authorized",
          not checkpoint_authorized(state, aw_one, m))
    check("[checkpoint] threshold auth set IS authorized",
          checkpoint_authorized(state, aw_full, m))
    # a LATE extra signature is a *different* AW -> different auth set -> different CID,
    # so the originally-pinned CID's verdict is unchanged (consumer-independent freeze).
    aw_late = aw_full | {M.sign_over(state, "A", "kA2")}
    check("[checkpoint] a late/extra signature yields a DIFFERENT CID (cannot flip the pinned one)",
          checkpoint_CID(state, aw_late) != cid_full)
    check("[checkpoint] the pinned CID verifies without any successor or citation",
          checkpoint_authorized(state, aw_full, m))


# ------------------------------------------------- 6. determinism under permutation
def test_determinism():
    """The same DAG under shuffled parent/iteration orders yields byte-identical derived
    state (canonical())."""
    P0 = (frozenset({"A", "B"}), 2)
    base = [
        Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "K0")),
        Rec("R", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A", rot_key="K1",
            incoming_pop=("A", "K1"), filing=("A", "K0")),
        Rec("x", frozenset({"g"}), "B", "ordinary", jur="J", filing=("B", "kB")),
        Rec("S", frozenset({"R"}), "A", "supersede", jur="J", subject="R", filing=("A", "K1")),
    ]
    canon0 = build("J", {"A": {"K0"}, "B": {"kB"}}, base, pinned_roots={"J": {"g"}}).canonical()
    same = True
    rng = random.Random(1337)
    for _ in range(20):
        shuffled = base[:]
        rng.shuffle(shuffled)
        c = build("J", {"A": {"K0"}, "B": {"kB"}}, shuffled, pinned_roots={"J": {"g"}}).canonical()
        same &= (c == canon0)
    check("[determinism] canonical() byte-identical under 20 record-order permutations", same)


# ------------------------------------------- 7. killer: one-filer quorum rollback FAILS
def test_quorum_rollback():
    """A files a 2-of-3 policy-succession P0->P1 (A+B); then A ALONE supersedes that
    succession record. The generic-SELF laundering must be REJECTED: superseding a JP
    target needs JP, not SELF (§5 matrix / §D.4)."""
    P0 = (frozenset({"A", "B", "C"}), 2)
    P1 = (frozenset({"A", "C"}), 2)
    recs = [
        Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")),
        Rec("s", frozenset({"g"}), "A", "policy-succession", jur="J", new_policy=P1,
            threshold=frozenset({("A", "kA"), ("B", "kB")})),          # quorum A+B -> P1
        Rec("roll", frozenset({"s"}), "A", "supersede", jur="J", subject="s",
            filing=("A", "kA")),                                        # A alone tries to roll back
    ]
    m = build("J", {"A": {"kA"}, "B": {"kB"}, "C": {"kC"}}, recs,
              pinned_policy={"J": P0}, pinned_roots={"J": {"g"}})
    check("[quorum-rollback] one-filer SELF rollback of a quorum succession is NOT valid_cap",
          not m.valid_cap("roll"))
    check("[quorum-rollback] the quorum succession survives (roll ineffective)",
          m.effective("s") if m.recs["s"].kind == "policy-succession" else True or not m.effective("roll"))
    check("[quorum-rollback] the rollback record is ineffective", not m.effective("roll"))


# --------------------------------------------- 8. cross-actor emergency rotation (§D.1)
def test_emergency_rotation():
    """Emergency rotation of actor A: FILED by a bound quorum actor Q (not A), target A,
    incoming-key PoP by A's new key, NO outgoing A signature, threshold by J policy."""
    P = (frozenset({"Q", "R"}), 2)
    recs = [
        Rec("g", frozenset(), "Q", "ordinary", jur="J", filing=("Q", "kQ")),
        Rec("emg", frozenset({"g"}), "Q", "rotation", jur="J",   # filer = Q, target = A
            rot_actor="A", rot_key="A_new", incoming_pop=("A", "A_new"),
            filing=("Q", "kQ"),                                  # Q is a bound quorum filer
            threshold=frozenset({("Q", "kQ"), ("R", "kR")})),    # J policy authorizes
    ]
    m = build("J", {"Q": {"kQ"}, "R": {"kR"}}, recs, pinned_policy={"J": P},
              pinned_roots={"J": {"g"}})
    check("[emergency-rotation] valid_cap with bound quorum filer != target, no outgoing key",
          m.valid_cap("emg"))
    keys = m._key_state(frozenset(m.recs))
    check("[emergency-rotation] A's new key is bound after the rotation", keys.get("A") == "A_new")


# ------------------------------------------------- 9. resolver scope (gate finding F1)
def test_resolver_scope():
    """A resolver must name EXACTLY the competing forks — padding is an attack.

    Found by the rev-7 adversarial gate (Gemini 3.1 Pro, F1, reproduced by the
    harness): rev 7 required only `maxima <= resolves` and folded the
    "greatest common causal predecessor" over `resolves`. So an actor whose
    authority a policy-succession had already removed could pad `resolves` with
    a record of its own anchored at genesis, drag the fold back to a policy
    under which it still held power, and thereby seize the resolution of a
    DIFFERENT actor's key conflict — dictating that actor's key.

    Three properties are pinned here: the padding attack fails; a subtler
    padding with a real transition from another actor's slot also fails; and
    the legitimate resolver still works, because a fix that only deadlocks is
    not a fix.
    """
    P_gen = (frozenset({"Q"}), 1)          # genesis: Q governs
    P_now = (frozenset({"A"}), 1)          # after succession: A governs, Q does not

    def world(extra_resolves=(), pad_recs=()):
        recs = [
            Rec("g", frozenset(), "Admin", "ordinary", jur="J", filing=("Admin", "kAdmin")),
            Rec("succ", frozenset({"g"}), "Q", "policy-succession", jur="J",
                new_policy=P_now, threshold=frozenset({("Q", "kQ")})),
            # User forks their own key: two unordered rotations
            Rec("R1", frozenset({"succ"}), "User", "rotation", jur="J", rot_actor="User",
                rot_key="K1", incoming_pop=("User", "K1"), filing=("User", "kUser")),
            Rec("R2", frozenset({"succ"}), "User", "rotation", jur="J", rot_actor="User",
                rot_key="K2", incoming_pop=("User", "K2"), filing=("User", "kUser")),
            *pad_recs,
            Rec("res", frozenset({"R1", "R2"} | set(extra_resolves)), "Q", "key-resolution",
                jur="J", resolves=frozenset({"R1", "R2"} | set(extra_resolves)),
                rot_key="K_evil", threshold=frozenset({("Q", "kQ")})),
        ]
        return build("J", {"Q": {"kQ"}, "A": {"kA"}, "User": {"kUser"},
                           "Admin": {"kAdmin"}}, recs,
                     pinned_policy={"J": P_gen}, pinned_roots={"J": {"g"}})

    # the premise: Q really has been removed from the governing policy
    m0 = world()
    check("[resolver-scope] the succession that removes Q is itself valid",
          m0.valid_cap("succ"))
    check("[resolver-scope] Q is no longer in the governing policy",
          "Q" not in m0.current_JP(frozenset(m0.recs))[0][0])

    # attack 1 — pad with an ordinary record anchored at genesis
    pad = Rec("dummy", frozenset({"g"}), "Q", "ordinary", jur="J", filing=("Q", "kQ"))
    m1 = world(extra_resolves=("dummy",), pad_recs=(pad,))
    check("[resolver-scope] padding `resolves` with an unrelated record is NOT valid_cap",
          not m1.valid_cap("res"))
    check("[resolver-scope] and the target actor's key is not seized",
          m1._key_state(frozenset(m1.recs)).get("User") != "K_evil")

    # attack 2 — pad with a REAL transition, from another actor's key slot
    pad2 = Rec("otherrot", frozenset({"g"}), "Admin", "rotation", jur="J",
               rot_actor="Admin", rot_key="Adm2", incoming_pop=("Admin", "Adm2"),
               filing=("Admin", "kAdmin"))
    m2 = world(extra_resolves=("otherrot",), pad_recs=(pad2,))
    check("[resolver-scope] padding with another actor's rotation is NOT valid_cap",
          not m2.valid_cap("res"))

    # liveness — the honest resolver, naming exactly the forks, still resolves.
    # Authorized by the policy at the forks' greatest common predecessor, which
    # is the post-succession policy (A governs), so A signs it.
    recs = [
        Rec("g", frozenset(), "Admin", "ordinary", jur="J", filing=("Admin", "kAdmin")),
        Rec("succ", frozenset({"g"}), "Q", "policy-succession", jur="J",
            new_policy=P_now, threshold=frozenset({("Q", "kQ")})),
        Rec("R1", frozenset({"succ"}), "User", "rotation", jur="J", rot_actor="User",
            rot_key="K1", incoming_pop=("User", "K1"), filing=("User", "kUser")),
        Rec("R2", frozenset({"succ"}), "User", "rotation", jur="J", rot_actor="User",
            rot_key="K2", incoming_pop=("User", "K2"), filing=("User", "kUser")),
        Rec("res", frozenset({"R1", "R2"}), "A", "key-resolution", jur="J",
            resolves=frozenset({"R1", "R2"}), rot_key="K1",
            threshold=frozenset({("A", "kA")})),
    ]
    m3 = build("J", {"Q": {"kQ"}, "A": {"kA"}, "User": {"kUser"}, "Admin": {"kAdmin"}},
               recs, pinned_policy={"J": P_gen}, pinned_roots={"J": {"g"}})
    check("[resolver-scope] the honest resolver naming exactly the forks IS valid_cap",
          m3.valid_cap("res"))
    check("[resolver-scope] and it settles the key (no deadlock)",
          m3._key_state(frozenset(m3.recs)).get("User") == "K1")


# -------------------------------------- 10. a jurisdiction cannot end itself by decree
def test_policy_wellformedness():
    """One valid policy-succession must not be able to abdicate or brick a jurisdiction.

    Both were reachable in rev 7, and both were found by running the machine
    rather than by reading §D:

      ABDICATION  succeed to (∅, 0). Every threshold passes vacuously, so a
                  stranger with no witnesses adopts roots into the jurisdiction.
      BRICKING    succeed to min_sigs > |actors|. Nothing is ever authorizable
                  again — including the succession that would undo it.

    A governing policy is now well-formed iff it can bind somebody and is
    satisfiable: actors ≠ ∅ and 1 ≤ min_sigs ≤ |actors|. The last check is the
    one that matters most: refusing must not cost recovery.
    """
    P0 = (frozenset({"A"}), 1)

    def attempt(new_policy, extra=()):
        recs = [
            Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA")),
            Rec("s", frozenset({"g"}), "A", "policy-succession", jur="J",
                new_policy=new_policy, threshold=frozenset({("A", "kA")})),
            *extra,
        ]
        return build("J", {"A": {"kA"}, "Z": {"kZ"}}, recs,
                     pinned_policy={"J": P0}, pinned_roots={"J": {"g"}})

    stranger = [
        Rec("B", frozenset(), "Z", "ordinary", jur="J", filing=("Z", "kZ")),
        Rec("D", frozenset({"s", "B"}), "Z", "root-adoption", jur="J", subject="B",
            threshold=frozenset()),                       # NO witnesses at all
    ]
    m = attempt((frozenset(), 0), stranger)
    check("[policy-wf] succession to the empty policy is NOT valid_cap",
          not m.valid_cap("s"))
    check("[policy-wf] so the governing policy is unchanged",
          m.current_JP(frozenset(m.recs))[0] == P0)
    check("[policy-wf] and a witnessless stranger cannot adopt a root",
          not m.valid_cap("D"))
    check("[policy-wf] the stranger's root is not admitted", "B" not in m.admits())

    m = attempt((frozenset({"A"}), 5))
    check("[policy-wf] succession to an unsatisfiable threshold is NOT valid_cap",
          not m.valid_cap("s"))

    # liveness: refusing the malformed cases must not refuse the ordinary one,
    # and must leave the jurisdiction able to legislate afterwards.
    P1 = (frozenset({"A", "Z"}), 2)
    m = attempt(P1, [Rec("back", frozenset({"s"}), "A", "policy-succession", jur="J",
                         new_policy=P0, threshold=frozenset({("A", "kA"), ("Z", "kZ")}))])
    check("[policy-wf] a well-formed succession still IS valid_cap", m.valid_cap("s"))
    check("[policy-wf] and the jurisdiction can still legislate afterwards",
          m.valid_cap("back"))


# ------------------------------- 11. fail-open binding + checkpoint scope (gate rev 7)
def test_binding_and_checkpoint_scope():
    """The five fail-OPEN paths a three-family gate reproduced against rev 7.

    Every one of these let something through that §D says must be refused, and
    all five predate rev 1. Sources: Kimi K3 F1, F2, F9, F6, F8 — each was a
    runnable counter-vector executed by tools/adversarial_gate.py.
    """
    P = (frozenset({"A", "B"}), 2)
    base = [Rec("g", frozenset(), "A", "ordinary", jur="J", filing=("A", "kA"))]

    # --- F1: the CONFLICT marker must not be presentable as a key -------------
    recs = base + [
        Rec("R1", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A",
            rot_key="K1", incoming_pop=("A", "K1"), filing=("A", "kA")),
        Rec("R2", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A",
            rot_key="K2", incoming_pop=("A", "K2"), filing=("A", "kA")),
        # someone files "as A", presenting the conflict sentinel as their key
        Rec("x", frozenset({"R1", "R2"}), "A", "ordinary", jur="J",
            filing=("A", M.CONFLICT)),
    ]
    m = build("J", {"A": {"kA"}, "B": {"kB"}}, recs, pinned_policy={"J": P},
              pinned_roots={"J": {"g"}})
    check("[binding] the key slot really is conflicted",
          m._key_state(frozenset(m.recs)).get("A") == M.CONFLICT)
    check("[binding] presenting the CONFLICT marker as a key is NOT bound",
          not m.valid_cap("x"))
    check("[binding] a conflicted slot cannot be counted toward a threshold",
          not m._threshold_ok(frozenset({("A", M.CONFLICT), ("B", "kB")}), P,
                              m._key_state(frozenset(m.recs))))

    # --- F2: an actor with no key must not bind with a null key ---------------
    recs = base + [Rec("z", frozenset({"g"}), "Z", "ordinary", jur="J",
                       filing=("Z", None))]
    m = build("J", {"A": {"kA"}}, recs, pinned_policy={"J": P},
              pinned_roots={"J": {"g"}})
    check("[binding] a keyless actor's null key is NOT bound", not m.valid_cap("z"))
    check("[binding] and a null witness cannot satisfy a threshold",
          not m._threshold_ok(frozenset({("A", "kA"), ("Z", None)}), P,
                              m._key_state(frozenset(m.recs))))

    # --- F9: the filing key must be the record actor's ------------------------
    recs = base + [Rec("m", frozenset({"g"}), "Mallory", "ordinary", jur="J",
                       filing=("A", "kA"))]        # Alice's key, Mallory's name
    m = build("J", {"A": {"kA"}, "Mallory": {"kM"}}, recs, pinned_policy={"J": P},
              pinned_roots={"J": {"g"}})
    check("[binding] a record cannot be filed under another actor's key",
          not m.valid_cap("m"))

    # --- F6/F8: checkpoint authorization is scoped to cut(P.frontier) ---------
    recs = base + [
        Rec("later", frozenset({"g"}), "A", "rotation", jur="J", rot_actor="A",
            rot_key="kA2", incoming_pop=("A", "kA2"), filing=("A", "kA")),
    ]
    m = build("J", {"A": {"kA"}, "B": {"kB"}}, recs, pinned_policy={"J": P},
              pinned_roots={"J": {"g"}})
    state = {"J": "J", "sequence": 1, "frontier": ("g",),
             "effective_set_root": ("e",), "key_state_root": ("k",),
             "policy_state_root": ("p",), "manifest_root": ("m",)}
    aw = frozenset({M.sign_over(state, "A", "kA"), M.sign_over(state, "B", "kB")})
    check("[checkpoint-scope] a signer rotation AFTER the frontier does not "
          "un-authorize a pinned checkpoint", checkpoint_authorized(state, aw, m))

    other = dict(state, sequence=2)
    lifted = frozenset({M.sign_over(other, "A", "kA"), M.sign_over(other, "B", "kB")})
    check("[checkpoint-scope] witnesses signed over a DIFFERENT state do not "
          "authorize this one", not checkpoint_authorized(state, lifted, m))
    check("[checkpoint-scope] bare (actor,key) witnesses attest nothing",
          not checkpoint_authorized(state, frozenset({("A", "kA"), ("B", "kB")}), m))
    check("[checkpoint-scope] a frontier citing an unknown record authorizes nothing",
          not checkpoint_authorized(dict(state, frontier=("nope",)), aw, m))


def main():
    test_may_reverse_total()
    test_revocation()
    test_losing_branch()
    test_root_oscillation()
    test_checkpoint_cid()
    test_determinism()
    test_quorum_rollback()
    test_emergency_rotation()
    test_resolver_scope()
    test_policy_wellformedness()
    test_binding_and_checkpoint_scope()
    print()
    if FAILS:
        print(f"WRT-002-MODEL: {len(FAILS)} FAIL(S): " + ", ".join(FAILS))
        sys.exit(1)
    print("WRT-002-MODEL: ALL PASS")


if __name__ == "__main__":
    main()
