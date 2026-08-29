#!/usr/bin/env python3
"""Fail-closed countervectors for the WRT-005 outcome-fingerprint design gates.

(This is a LIVE artifact of WRT-005. WRT-003 was this design's old working
name; it survives only in the preserved historical reviews/manifests, never in
live code — see the identifier note in
`proposals/WRT-005-outcome-fingerprint-purity.md`.)

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

FAIL-CLOSED (Codex authorization, 2026-08-28). Every claimed relation, every
settlement verdict, and every subprocess return code is ASSERTED, not printed.
Any deviation makes this exit 1. The verdicts asserted for the attack
candidates are the CURRENT spec's (which admits them — that is the demonstrated
vulnerability); the rev-4 block asserts, from the result values alone, that the
proposed rule collapses all five re-openers while keeping the positive §7(b)
control admissible. This proves the attacks and the rule's arithmetic; it does
NOT claim the running verifier implements rev-4 (it does not — the rule is
design-only).

Exit codes: 0 all assertions hold; 1 an assertion failed; 2 a prerequisite
(the Σ-GLYPH oracle, or the Go binary settlement CLI) was unavailable, so the
countervectors could not run — never silently reported as passed.
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
    print("wrt005-countervectors: UNRUN — the Σ-GLYPH oracle was not found "
          "(set SIGMA_GLYPH)", file=sys.stderr)
    sys.exit(2)

# The Go settlement CLI is a prerequisite too: this suite settles with BOTH
# implementations and compares them, so a missing Go binary must be an explicit
# UNRUN (exit 2) here — not a FileNotFoundError traceback from the first
# settle_both (which would exit 1 and read as a real failure). Codex round 2.
_go = os.environ.get("WARRANT_GO") or os.path.join(
    os.path.dirname(__file__), "..", "..", "impl-go", "warrant-go")
if not (os.path.isfile(_go) and os.access(_go, os.X_OK)):
    print("wrt005-countervectors: UNRUN — the Go settlement CLI was not found "
          "or is not executable (build impl-go/warrant-go, or set WARRANT_GO)",
          file=sys.stderr)
    sys.exit(2)

ADMISSIBLE = "admissible: (b) new outcome fingerprint"

_failures = []


def check(cond, msg):
    ok = bool(cond)
    print(f"  {'ok ' if ok else 'BAD'}  {msg}")
    if not ok:
        _failures.append(msg)
    return ok


def settle_verdict(store, settled, cand, label):
    """Run both implementations' `settle` and assert they agree on verdict AND
    return code. Returns the shared stdout verdict, or records a failure."""
    path = os.path.join(tmp, label.replace(" ", "-") + ".json")
    open(path, "w").write(json.dumps(cand, sort_keys=True))
    py, go = T.settle_both(store, settled, path)
    same_rc = py.returncode == go.returncode
    same_out = py.stdout.strip() == go.stdout.strip()
    if not check(same_rc, f"{label}: py/go return codes agree "
                          f"(py={py.returncode} go={go.returncode})"):
        return None
    if not check(same_out, f"{label}: py/go verdicts agree "
                           f"(py={py.stdout.strip()!r} go={go.stdout.strip()!r})"):
        return None
    # returncode contract (tests/settlement.py): 0 = admissible, 1 = inadmissible
    verdict = py.stdout.strip()
    expect_rc = 0 if verdict.startswith("admissible") else 1
    check(py.returncode == expect_rc,
          f"{label}: return code matches verdict "
          f"(rc={py.returncode}, verdict={verdict!r})")
    return verdict


tmp = tempfile.mkdtemp(prefix="wrt005-gate-")
store, keys, opaque = T.setup(tmp)
subject = T.put_blob(store, b"question")


def node(bs):
    T.put_blob(store, bs)          # warrant blob store keyed by sha256(bytes)
    return sg.node_hash(bs)


def opcode(h):
    b = sg.GENESIS.get(bytes.fromhex(h)) or open(os.path.join(store, "blobs", h), "rb").read()
    return sg.deser(b)["op"]


def has_dissonance(h, seen=None):
    """Does the normal form contain a DISSONANCE node ANYWHERE (rev-4 §3.2)?"""
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


# Materialize the canonical DISSONANCE outcome nodes so has_dissonance() can
# resolve a *synthesized* bottom result: eval returns `.dis rATP` (etc.) whose
# node need not be a stored blob. Storing them up front makes the recursive
# DISSONANCE-anywhere check total over every result these vectors produce.
for _atom in (sg.R_ATP, sg.R_UNRES, sg.R_INVALID):
    node(sg.ser(sg.DISSONANCE, sg.F_ATOM, atom=_atom))

# --- the settled question: (K S) K -> S with real reduction steps
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

print("settled question ((K S) K -> S):")
check(v_full == "pass", f"settled check re-runs to pass (got {v_full!r})")
check(not has_dissonance(r_full), "settled result S is DISSONANCE-free (eligible)")

# --- POSITIVE control (Qwen): a different clean result is admissible (§7(b)).
diff_check = T.put_json_blob(store, {"ski": 1, "term": sg.K_H.hex(), "atp": 5,
                                     "expect": sg.K_H.hex()})
_, r_diff, _ = W.run_ski_check(W.Store(store), diff_check)
cand_pos = T.body("reject", subject, [opaque], "a@x", prior=[settled],
                  because=[{"kind": "check", "runtime": "ski@v1",
                            "check": diff_check, "verdict": "pass"}], ts=9)
print("\nPOSITIVE §7(b) control (settle S, file K -> different clean result):")
check(r_diff != r_full, "the positive candidate reaches a DIFFERENT result")
v = settle_verdict(store, settled, cand_pos, "positive")
check(v == ADMISSIBLE, f"positive candidate is admissible (got {v!r})")

# --- Attack 1: ATP starvation (same term, budget 1 -> DISSONANCE).
starved = T.put_json_blob(store, {"ski": 1, "term": term, "atp": 1,
                                  "expect": sg.S_H.hex()})
_, r_st, _ = W.run_ski_check(W.Store(store), starved)
cand1 = T.body("reject", subject, [opaque], "a@x", prior=[settled],
               because=[{"kind": "check", "runtime": "ski@v1",
                         "check": starved, "verdict": "fail"}], ts=2)
print("\nAttack 1 — ATP starvation:")
check(r_st != r_full, "starved run yields a different (DISSONANCE) result")
check(has_dissonance(r_st), "starved result carries a DISSONANCE (rev-4 ineligible)")
v = settle_verdict(store, settled, cand1, "starvation")
check(v == ADMISSIBLE, f"CURRENT spec ADMITS starvation — the vuln (got {v!r})")

# --- Attack 2: I-wrapper (I T -> same S, fresh term hash).
WRAP = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=sg.I_H, right=term_h)
wrap_h = node(WRAP)
wrapped = T.put_json_blob(store, {"ski": 1, "term": wrap_h.hex(), "atp": 30,
                                  "expect": sg.S_H.hex()})
_, r_w, _ = W.run_ski_check(W.Store(store), wrapped)
cand2 = T.body("reject", subject, [opaque], "a@x", prior=[settled],
               because=[{"kind": "check", "runtime": "ski@v1",
                         "check": wrapped, "verdict": "pass"}], ts=3)
print("\nAttack 2 — I-wrapper:")
check(wrap_h.hex() != term, "wrapper has a fresh term hash")
check(r_w == r_full, "wrapper re-runs to the SAME result as settled")
v = settle_verdict(store, settled, cand2, "wrapper")
check(v == ADMISSIBLE, f"CURRENT spec ADMITS the wrapper — the vuln (got {v!r})")

# --- Attack 3: REF-padding (REF(S) vs REF(REF(S)) -> same S, different read-set).
R1 = sg.ser(sg.REF, sg.F_ATOM, atom=sg.S_H); r1_h = node(R1)
R2 = sg.ser(sg.REF, sg.F_ATOM, atom=r1_h);   r2_h = node(R2)
_, r_ref1, sp1 = W.run_ski_check(W.Store(store), T.put_json_blob(
    store, {"ski": 1, "term": r1_h.hex(), "atp": 10, "expect": sg.S_H.hex()}))
_, r_ref2, sp2 = W.run_ski_check(W.Store(store), T.put_json_blob(
    store, {"ski": 1, "term": r2_h.hex(), "atp": 10, "expect": sg.S_H.hex()}))
print("\nAttack 3 — REF-padding:")
check(r_ref1 == r_ref2, "REF(S) and REF(REF(S)) reach the SAME result")
check(sp1 != sp2, "they force different read-sets (atp spent differs)")

# --- Attack 4: a direct DISSONANCE node shares its hash with genuine exhaustion.
DIS = sg.ser(sg.DISSONANCE, sg.F_ATOM, atom=sg.R_ATP); dis_h = node(DIS)
_, r_direct, _ = W.run_ski_check(W.Store(store), T.put_json_blob(
    store, {"ski": 1, "term": dis_h.hex(), "atp": 10, "expect": dis_h.hex()}))
print("\nAttack 4 — direct DISSONANCE node vs genuine exhaustion:")
check(r_direct == r_st, "direct DISSONANCE node has the SAME hash as exhaustion")
check(opcode(r_direct) == sg.DISSONANCE, "its result opcode is DISSONANCE")

# --- Attack 5: nested DISSONANCE ((dis K) -> stuck APPLY with a dis inside).
DINV = sg.ser(sg.DISSONANCE, sg.F_ATOM, atom=sg.R_INVALID); dinv_h = node(DINV)
nest1 = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=dinv_h, right=sg.K_H); n1 = node(nest1)
nest2 = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=dinv_h, right=sg.I_H); n2 = node(nest2)
res_n1 = W.run_ski_check(W.Store(store), T.put_json_blob(
    store, {"ski": 1, "term": n1.hex(), "atp": 20, "expect": n1.hex()}))[1]
res_n2 = W.run_ski_check(W.Store(store), T.put_json_blob(
    store, {"ski": 1, "term": n2.hex(), "atp": 20, "expect": n2.hex()}))[1]
print("\nAttack 5 — nested DISSONANCE (defeats a root-only rule):")
check(opcode(res_n1) == sg.APPLY, "(dis K) result ROOT is APPLY, not DISSONANCE")
check(res_n1 != res_n2, "distinct nested-dis terms give distinct hashes")
check(has_dissonance(res_n1) and has_dissonance(res_n2),
      "both contain a DISSONANCE anywhere (rev-4 rule marks both ineligible)")

# --- rev-4 verdict, from the result VALUES alone (identity = result; eligible
#     iff DISSONANCE-free). This is the rule's arithmetic, not the running code.
def eligible(r):
    return not has_dissonance(r)


fp = lambda r: ("ski@v1", r)   # rev-4 identity: runtime + result value only
print("\nrev-4 rule (identity = result; eligible iff DISSONANCE-free):")
check(eligible(r_st) is False, "starvation result is INELIGIBLE")
check(eligible(res_n1) is False, "nested-dis result is INELIGIBLE")
check(eligible(r_full) is True, "the clean settled result stays ELIGIBLE")
check(fp(r_w) == fp(r_full), "wrapper collapses onto the settled fingerprint")
check(fp(r_ref2) == fp(r_ref1), "REF-padding collapses onto one fingerprint")
check(fp(r_diff) != fp(r_full), "a genuinely new clean result is a NEW fingerprint")

print(f"\n{'FAIL' if _failures else 'PASS'} — "
      f"{len(_failures)} failed assertion(s); the five re-openers are demonstrated "
      "on the current spec and collapse under the rev-4 rule.")
sys.exit(1 if _failures else 0)
