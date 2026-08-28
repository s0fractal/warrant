#!/usr/bin/env python3
"""Reproductions for the WRT-003 design gates (2026-08-27).

Round 1 (annaglova, rev-1 gate):
  Attack 1 (BLOCKER): ATP starvation — same term, low-but-legal budget;
    verifier honestly computes DISSONANCE(exhausted); fingerprint differs.
  Attack 2 (MAJOR): I-wrapper — I T re-runs to the same result, fresh term.
Round 2 (gpt56sol, rev-2 gate):
  Attack 3 (BLOCKER): REF-padding — REF(S) vs REF(REF(S)) reach the same
    result with different forced read-sets; defeats identity (B).
  Attack 4 (MAJOR): a direct DISSONANCE node has the same result hash as a
    genuine exhaustion; pins node-class vs execution-origin eligibility.
Round 3 (Qwen, rev-3 gate):
  POSITIVE: settle S, file K -> different clean result IS admissible; §7(b)
    is not a dead letter under identity (A).
  Attack 5 (BLOCKER): nested DISSONANCE — (dis·K) normalizes to a stuck APPLY
    (root != DIS) containing a dis; distinct such terms give distinct hashes,
    a re-opener family under a ROOT-only rule. Fixed by "DISSONANCE anywhere".

Tested against the CURRENT spec (both implementations): the attacks' mechanics
are real, and the last block computes the rev-4 verdict (identity = result
only; eligible iff the result is DISSONANCE-free), under which all five
re-openers collapse and the positive §7(b) control stays admissible.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settlement as T  # noqa: E402

W = T.W
sg = W.load_sigma()
if sg is None:
    print("sigma oracle not found"); sys.exit(2)

tmp = tempfile.mkdtemp(prefix="wrt003-gate-")
store, keys, opaque = T.setup(tmp)
subject = T.put_blob(store, b"question")

# --- a term that actually needs work: (K S) K -> S with real reduction steps
def node(bs):
    T.put_blob(store, bs)          # warrant blob store keyed by sha256(bytes)
    return sg.node_hash(bs)
KS = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=sg.K_H, right=sg.S_H)
ks_h = node(KS)
TERM = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=ks_h, right=sg.K_H)
term_h = node(TERM)
term = term_h.hex()

full = T.put_json_blob(store, {"ski": 1, "term": term, "atp": 20,
                               "expect": sg.S_H.hex()})
settled = T.add_record(store, T.body("accept", subject, [opaque], "a@x",
                       because=[{"kind": "check", "runtime": "ski@v1",
                                 "check": full, "verdict": "pass"}], ts=1),
                       [("a@x", keys["a_old"])])

v_full, r_full, spent = W.run_ski_check(W.Store(store), full)
print(f"settled run: verdict={v_full} result={r_full[:12]}.. atp_spent={spent}")

# --- POSITIVE control (rev-3 gate, Qwen): §7(b) is NOT empty under (A).
#     A different term reaching a DIFFERENT clean result stays admissible.
diff_check = T.put_json_blob(store, {"ski": 1, "term": sg.K_H.hex(), "atp": 5,
                                     "expect": sg.K_H.hex()})
_, r_diff, _ = W.run_ski_check(W.Store(store), diff_check)
cand_pos = T.body("reject", subject, [opaque], "a@x", prior=[settled],
                  because=[{"kind": "check", "runtime": "ski@v1",
                            "check": diff_check, "verdict": "pass"}], ts=9)
pp = os.path.join(tmp, "positive.json"); open(pp, "w").write(json.dumps(cand_pos, sort_keys=True))
pyp, gop = T.settle_both(store, settled, pp)
print(f"POSITIVE §7(b) (settled S, file K -> different result {r_diff[:12]}..): "
      f"py={pyp.stdout.strip()!r}  go={gop.stdout.strip()!r}")
print("  => a newly demonstrated value IS admissible; §7(b) is not a dead letter.")

# --- Attack 1: same term, starved budget (legal, locally executable)
starved = T.put_json_blob(store, {"ski": 1, "term": term, "atp": 1,
                                  "expect": sg.S_H.hex()})
v_st, r_st, _ = W.run_ski_check(W.Store(store), starved)
print(f"starved run: verdict={v_st} result={r_st[:12]}.. "
      f"(same term, atp=1; result is DISSONANCE: {r_st != r_full})")
cand = T.body("reject", subject, [opaque], "a@x", prior=[settled],
              because=[{"kind": "check", "runtime": "ski@v1",
                        "check": starved, "verdict": "fail"}], ts=2)
p = os.path.join(tmp, "starved.json"); open(p, "w").write(json.dumps(cand, sort_keys=True))
py, go = T.settle_both(store, settled, p)
print(f"ATP-starvation candidate:  py={py.stdout.strip()!r}  go={go.stdout.strip()!r}")

# --- Attack 2: I-wrapper — I applied to TERM reduces to the same S
WRAP = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=sg.I_H, right=term_h)
wrap_h = node(WRAP)
wrapped = T.put_json_blob(store, {"ski": 1, "term": wrap_h.hex(), "atp": 30,
                                  "expect": sg.S_H.hex()})
v_w, r_w, _ = W.run_ski_check(W.Store(store), wrapped)
print(f"wrapper run: verdict={v_w} result={r_w[:12]}.. "
      f"(fresh term hash, same result as settled: {r_w == r_full})")
cand2 = T.body("reject", subject, [opaque], "a@x", prior=[settled],
               because=[{"kind": "check", "runtime": "ski@v1",
                         "check": wrapped, "verdict": "pass"}], ts=3)
p2 = os.path.join(tmp, "wrapped.json"); open(p2, "w").write(json.dumps(cand2, sort_keys=True))
py2, go2 = T.settle_both(store, settled, p2)
print(f"I-wrapper candidate:       py={py2.stdout.strip()!r}  go={go2.stdout.strip()!r}")

# --- Attack 3 (rev-2 gate, gpt56sol): REF-padding defeats identity (B).
#     REF(S) and REF(REF(S)) both -> S with different forced read-sets.
R1 = sg.ser(sg.REF, sg.F_ATOM, atom=sg.S_H); r1_h = node(R1)
R2 = sg.ser(sg.REF, sg.F_ATOM, atom=r1_h);   r2_h = node(R2)
ref_settled = T.put_json_blob(store, {"ski": 1, "term": r1_h.hex(), "atp": 10,
                                      "expect": sg.S_H.hex()})
_, r_ref1, sp1 = W.run_ski_check(W.Store(store), ref_settled)
ref_pad = T.put_json_blob(store, {"ski": 1, "term": r2_h.hex(), "atp": 10,
                                  "expect": sg.S_H.hex()})
_, r_ref2, sp2 = W.run_ski_check(W.Store(store), ref_pad)
print(f"\nREF(S)     -> result={r_ref1[:12]}.. spent={sp1}")
print(f"REF(REF(S))-> result={r_ref2[:12]}.. spent={sp2} "
      f"(same result: {r_ref1 == r_ref2}, different read-set: {sp1 != sp2})")
print("  => identity (B) {forced-read-set,...} would call REF(REF(S)) novel; "
      "(A) result-only does not.")

# --- Attack 4 (rev-2 gate, gpt56sol): a direct DISSONANCE node has the same
#     result hash as a genuine exhaustion — node-class vs execution-origin.
DIS = sg.ser(sg.DISSONANCE, sg.F_ATOM, atom=sg.R_ATP); dis_h = node(DIS)
direct = T.put_json_blob(store, {"ski": 1, "term": dis_h.hex(), "atp": 10,
                                 "expect": dis_h.hex()})
_, r_direct, _ = W.run_ski_check(W.Store(store), direct)
print(f"\ndirect DISSONANCE(R_ATP) node -> result={r_direct[:12]}..")
print(f"genuine exhaustion           -> result={r_st[:12]}.. "
      f"(same result hash: {r_direct == r_st})")
print("  => the node-class rule (result opcode == DISSONANCE) marks BOTH "
      "ineligible from the hash alone; no provenance channel needed.")

# --- Attack 5 (rev-3 gate, Qwen): nested DISSONANCE defeats a ROOT-only rule.
#     (dis · K) normalizes to a stuck APPLY (root != DIS) containing a dis;
#     distinct such terms give distinct hashes -> a re-opener family.
DINV = sg.ser(sg.DISSONANCE, sg.F_ATOM, atom=sg.R_INVALID); dinv_h = node(DINV)
nest1 = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=dinv_h, right=sg.K_H); n1 = node(nest1)
nest2 = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=dinv_h, right=sg.I_H); n2 = node(nest2)
res_n1 = W.run_ski_check(W.Store(store), T.put_json_blob(
    store, {"ski": 1, "term": n1.hex(), "atp": 20, "expect": n1.hex()}))[1]
res_n2 = W.run_ski_check(W.Store(store), T.put_json_blob(
    store, {"ski": 1, "term": n2.hex(), "atp": 20, "expect": n2.hex()}))[1]


def opcode(h):
    b = sg.GENESIS.get(bytes.fromhex(h)) or open(os.path.join(store, "blobs", h), "rb").read()
    return sg.deser(b)["op"]


def has_dissonance(h, seen=None):
    """Recursive: does the normal form contain a DISSONANCE node anywhere?"""
    seen = seen if seen is not None else set()
    if h in seen:
        return False
    seen.add(h)
    b = sg.GENESIS.get(bytes.fromhex(h)) or open(os.path.join(store, "blobs", h), "rb").read()
    n = sg.deser(b)
    if n["op"] == sg.DISSONANCE:
        return True
    if n["op"] == sg.APPLY:
        return has_dissonance(n["left"].hex(), seen) or has_dissonance(n["right"].hex(), seen)
    return False


print(f"\n(dis · K) -> result={res_n1[:12]}.. root_opcode={opcode(res_n1)} "
      f"(APPLY={sg.APPLY}, not DIS)")
print(f"(dis · I) -> result={res_n2[:12]}.. distinct from (dis·K): {res_n1 != res_n2}")
print(f"  root-only rule: both eligible (root=APPLY) -> re-opener family.")
print(f"  rev-4 'DISSONANCE anywhere' rule: (dis·K) has_dis={has_dissonance(res_n1)}, "
      f"(dis·I) has_dis={has_dissonance(res_n2)} -> both INELIGIBLE.")

# --- rev-4 verdict: identity=(runtime,result); eligible iff DISSONANCE-free
def eligible(r):
    return not has_dissonance(r)
fp = lambda r: ("ski@v1", r)
print("\nrev-4 (A + DISSONANCE-free eligibility):")
print(f"  starved eligible:        {eligible(r_st)} (expect False)")
print(f"  nested-dis eligible:     {eligible(res_n1)} (expect False)")
print(f"  clean result S eligible: {eligible(r_full)} (expect True)")
print(f"  wrapper fp == settled:   {fp(r_w) == fp(r_full)} (expect True)")
print(f"  REF-pad fp == settled:   {fp(r_ref2) == fp(r_ref1)} (expect True)")
print("=> under rev 4 all five re-openers collapse to the same rule,")
print("   and a genuinely different clean result (positive §7(b)) stays eligible.")
