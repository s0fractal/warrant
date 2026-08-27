#!/usr/bin/env python3
"""Reproductions for the annaglova WRT-003 rev-1 gate (2026-08-27).

Attack 1 (BLOCKER): ATP starvation — same term, filer-chosen low-but-legal
budget; verifier honestly computes DISSONANCE(exhausted); fingerprint differs.
Attack 2 (MAJOR): I-wrapper — I T re-runs to the same result under a fresh
term hash.

Both are tested against the CURRENT spec (both implementations) — rev 1 of
WRT-003 is design-only, so what we can demonstrate today is (a) the attacks'
mechanics are real, and (b) starvation is admissible under the CURRENT rule
too (the tuple differs in re-run verdict/result), i.e. the blocker names a
hole rev 1 inherited and then blessed, not one it introduced.
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

# --- what the rev-1 tuple would say (computed here, since rev 1 is unimplemented)
fp_settled = ("ski@v1", term, r_full)
fp_starved = ("ski@v1", term, r_st)
fp_wrapped = ("ski@v1", wrap_h.hex(), r_w)
print(f"\nrev-1 tuples: starved differs from settled: {fp_starved != fp_settled}; "
      f"wrapped differs: {fp_wrapped != fp_settled}")
print("=> both attacks yield 'new' fingerprints under rev 1 as drafted.")
