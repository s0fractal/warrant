#!/usr/bin/env python3
"""What can the holder of a RETIRED key do? (DeepReview 2026-10-16, R13)

Pinned as current behaviour, so any change to it is deliberate. It is not
pinned as the right behaviour: see THREAT-MODEL A10 and the triage.

a@x: genesis key a_old -> legitimate rotation to a_new. Later a_old leaks.
The attacker files a rotation a_old -> a_fork at the ROOT position (where
a_old was current), then signs records on that branch with a_fork. Questions:
  Q1. is the fork rotation authorized (counts as a key-state warrant)?
  Q2. does it make a@x conflicted store-wide (the denial A10 records)?
  Q3. are records signed by a_fork on the fork branch settlement-active and
      reported bound to a@x (a takeover of that branch, not just a denial)?
  Q4. does the legitimate a_new branch keep working?
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settlement as T

W = T.W
tmp = tempfile.mkdtemp(prefix="r13-")
store, keys, opaque = T.setup(tmp)
subject = T.put_blob(store, b"r13 subject")
root = T.add_record(store, T.body("accept", subject, [opaque], "a@x", ts=1), [("a@x", keys["a_old"])])
k_new = T.put_json_blob(store, {"actor": "a@x", "key": T.pubkey(keys["a_new"])})
rot = T.add_record(store, T.body("accept", k_new, [opaque], "a@x", prior=[root], ts=2),
                   [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
legit = T.add_record(store, T.body("propose", subject, [opaque], "a@x", prior=[rot],
                     because=[{"kind": "prose", "text": "legit after rotation"}], ts=3),
                     [("a@x", keys["a_new"])])
trust = T.trust_file(tmp, [root], {"a@x": [T.pubkey(keys["a_old"])]})

ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")


def report():
    py, go = T.verify_both(store, trust)
    lines = [l for l in py.stdout.strip().splitlines() if l.startswith(("WARN", "ERR", "INFO"))]
    check("Python and Go report the same lines", T.report_lines(py.stdout) == T.report_lines(go.stdout))
    return lines


before = report()
check("before the leak: no key-state conflict", not any("key-state conflict" in l for l in before), before)
check("before the leak: the legitimate record's a_new signature is bound",
      any(l.startswith("INFO") and legit[:12] in l and "bound" in l for l in before), before)
# --- the leak: a_old signs a rotation to a_fork at the root position
k_fork = T.put_json_blob(store, {"actor": "a@x", "key": T.pubkey(keys["a_fork"])})
fork = T.add_record(store, T.body("accept", k_fork, [opaque], "a@x", prior=[root], ts=4),
                    [("a@x", keys["a_old"]), ("a@x", keys["a_fork"])])
evil = T.add_record(store, T.body("propose", subject, [opaque], "a@x", prior=[fork],
                    because=[{"kind": "prose", "text": "attacker branch"}], ts=5),
                    [("a@x", keys["a_fork"])])
after = report()

ctx = W._settlement_context(W.Store(store), trust_config=trust)
check("Q1: a rotation signed by the retired key at the root position is authorized",
      fork in ctx["active_records"])
check("Q2: a@x becomes conflicted store-wide", "a@x" in ctx["conflict_actors"])
conflicted = {l.split()[1] for l in after if "key-state conflict" in l}
check("RETROACTIVE: the genesis root and the legitimate branch now report a conflict",
      {root[:12], rot[:12], legit[:12]} <= conflicted, sorted(conflicted))
check("RETROACTIVE: no signature by a@x is reported bound anywhere",
      not any(l.startswith("INFO") and "signature bound" in l for l in after), after)
check("Q3: no takeover in the report: the attacker's own record is unbound too",
      any(l.startswith("WARN") and evil[:12] in l and "unbound" in l for l in after), after)
print(f"\nR13-RETIRED-KEY: {'AS PINNED' if ok else 'BEHAVIOUR CHANGED'}")
sys.exit(0 if ok else 1)
