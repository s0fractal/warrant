#!/usr/bin/env python3
"""WRT-015 pre-rotation: a retired key can no longer rotate (DeepReview R13).

THE DEFECT THIS CLOSES
----------------------
Rotation authorization is judged at the record's DAG position while key-state
conflict is store-wide. So once `a@x` had rotated `a_old -> a_new`, a leaked
`a_old` could sign a rotation `a_old -> a_fork` at the root position. That
rotation was authorized, `a@x` became conflicted everywhere, and every
signature `a@x` ever made reported `unbound`: one retired key denied a whole
history.

THE RULE (WRT-015, SPEC §5.1)
Each key state commits to the SHA-256 of its successor (`next` in the key
blob; `next` in the trust config for genesis keys). A rotation is authorized
only if its incoming key matches the commitment of the actor's key state at
the rotation's DAG position. A key state without a commitment is terminal.

WHAT IS ASSERTED, FOR PYTHON, GO AND RUST, REPORT FOR REPORT
  1. A committed chain a_old -> a_new -> a_newer binds each key in turn.
  2. R13 closed: a fork rotation signed by the retired a_old alone, at the root
     position, is NOT authorized. No key-state conflict; the root and the
     legitimate branch stay bound; the attacker's record is unbound.
  3. Terminal key: with no genesis commitment, a rotation is not authorized,
     whatever the outgoing key signs.
  4. Residual, pinned: a holder of a_old AND its committed successor a_new can
     still fork at the root (same successor, different `next`). That is a
     conflict, as before. Closing it needs an external order (WRT-012).
  5. The same residual after two rotations: both keys of the forking pair are
     retired, and the store-wide conflict unbinds the current key's records
     too. Pinned as current behaviour; WRT-016 proposes scoping it.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settlement as T  # noqa: E402

W = T.W
RS = os.environ.get("WARRANT_RS", os.path.join(T.ROOT, "impl-rs", "target", "release", "warrant-rs"))
ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")


def commit(key_path):
    return hashlib.sha256(bytes.fromhex(T.pubkey(key_path))).hexdigest()


def key_blob(store, key_path, next_path=None):
    doc = {"actor": "a@x", "key": T.pubkey(key_path)}
    if next_path:
        doc["next"] = commit(next_path)
    return T.put_json_blob(store, doc)


def world(name, genesis_next=True):
    tmp = tempfile.mkdtemp(prefix=f"wrt015-{name}-")
    store, keys, opaque = T.setup(tmp)
    newer = os.path.join(tmp, "a_newer.key")
    T.write_key(newer, 6)
    keys["a_newer"] = newer
    subject = T.put_blob(store, f"{name} subject".encode())
    root = T.add_record(store, T.body("accept", subject, [opaque], "a@x", ts=1),
                        [("a@x", keys["a_old"])])
    doc = {"genesis_roots": [root], "actors": {"a@x": [T.pubkey(keys["a_old"])]}}
    if genesis_next:
        doc["next"] = {"a@x": commit(keys["a_new"])}
    trust = os.path.join(tmp, "trust.json")
    open(trust, "w").write(json.dumps(doc, sort_keys=True, separators=(",", ":")))
    return tmp, store, keys, opaque, subject, root, trust


def run_all(store, trust):
    py = T.sh(T.PY + ["--store", store, "verify", "--settlement", "--trust-config", trust])
    go = T.sh([T.GO, "verify", "--settlement", "--trust-config", trust, store])
    rs = T.sh([RS, "--store", store, "verify", "--settlement", "--trust-config", trust])
    return py, go, rs


def lines(out):
    return [l for l in out.strip().splitlines() if l.startswith(("WARN", "ERR", "INFO"))]


def agree(label, py, go, rs):
    a, b, c = (T.report_lines(x.stdout) for x in (py, go, rs))
    check(f"{label}: Python, Go and Rust give the same findings", a == b == c,
          {"py": a, "go": b, "rs": c})


def bound(out, wid, key_path=None):
    return any(l.startswith("INFO") and wid[:12] in l and "signature bound" in l
               and (key_path is None or T.pubkey(key_path)[:12] in l) for l in lines(out))


def conflicted(out):
    return any("key-state conflict" in l for l in lines(out))


def errors(out):
    c = T.counts(out)
    return c[1] if c else None


def case_chain():
    tmp, store, keys, opaque, subject, root, trust = world("chain")
    rot1 = T.add_record(store, T.body("accept", key_blob(store, keys["a_new"], keys["a_newer"]),
                                      [opaque], "a@x", prior=[root], ts=2),
                        [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
    rot2 = T.add_record(store, T.body("accept", key_blob(store, keys["a_newer"]),
                                      [opaque], "a@x", prior=[rot1], ts=3),
                        [("a@x", keys["a_new"]), ("a@x", keys["a_newer"])])
    rec = T.add_record(store, T.body("propose", subject, [opaque], "a@x", prior=[rot2],
                                     because=[{"kind": "prose", "text": "after two"}], ts=4),
                       [("a@x", keys["a_newer"])])
    py, go, rs = run_all(store, trust)
    agree("chain", py, go, rs)
    check("1. a committed chain binds each key in turn (a_newer bound after two rotations)",
          errors(py.stdout) == 0 and bound(py.stdout, rec, keys["a_newer"]) and not conflicted(py.stdout),
          lines(py.stdout))


def legit_then(tmp, store, keys, opaque, subject, root):
    rot = T.add_record(store, T.body("accept", key_blob(store, keys["a_new"], keys["a_newer"]),
                                     [opaque], "a@x", prior=[root], ts=2),
                       [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
    legit = T.add_record(store, T.body("propose", subject, [opaque], "a@x", prior=[rot],
                                       because=[{"kind": "prose", "text": "legit"}], ts=3),
                         [("a@x", keys["a_new"])])
    return rot, legit


def case_retired_key():
    tmp, store, keys, opaque, subject, root, trust = world("retired")
    rot, legit = legit_then(tmp, store, keys, opaque, subject, root)
    fork = T.add_record(store, T.body("accept", key_blob(store, keys["a_fork"], keys["a_fork"]),
                                      [opaque], "a@x", prior=[root], ts=4),
                        [("a@x", keys["a_old"]), ("a@x", keys["a_fork"])])
    evil = T.add_record(store, T.body("propose", subject, [opaque], "a@x", prior=[fork],
                                      because=[{"kind": "prose", "text": "attacker"}], ts=5),
                        [("a@x", keys["a_fork"])])
    py, go, rs = run_all(store, trust)
    agree("retired key", py, go, rs)
    out = py.stdout
    check("2. R13 closed: a retired key alone cannot rotate -- 0 errors, no key-state conflict",
          errors(out) == 0 and not conflicted(out), lines(out))
    check("2. the genesis root and the legitimate branch stay bound",
          bound(out, root, keys["a_old"]) and bound(out, legit, keys["a_new"]), lines(out))
    check("2. the attacker's record is unbound",
          not bound(out, evil) and any(evil[:12] in l and "unbound" in l for l in lines(out)),
          lines(out))


def case_terminal():
    tmp, store, keys, opaque, subject, root, trust = world("terminal", genesis_next=False)
    rot = T.add_record(store, T.body("accept", key_blob(store, keys["a_new"]),
                                     [opaque], "a@x", prior=[root], ts=2),
                       [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
    rec = T.add_record(store, T.body("propose", subject, [opaque], "a@x", prior=[rot],
                                     because=[{"kind": "prose", "text": "after"}], ts=3),
                       [("a@x", keys["a_new"])])
    py, go, rs = run_all(store, trust)
    agree("terminal", py, go, rs)
    check("3. with no commitment the key is terminal: the rotation binds nothing",
          bound(py.stdout, root, keys["a_old"]) and not bound(py.stdout, rec)
          and T.counts(py.stdout) is not None, lines(py.stdout))


def case_residual():
    tmp, store, keys, opaque, subject, root, trust = world("residual")
    rot, legit = legit_then(tmp, store, keys, opaque, subject, root)
    T.add_record(store, T.body("accept", key_blob(store, keys["a_new"], keys["a_fork"]),
                               [opaque], "a@x", prior=[root], ts=4),
                 [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
    py, go, rs = run_all(store, trust)
    agree("residual", py, go, rs)
    check("4. residual: a_old AND its committed successor can still fork -> conflict",
          errors(py.stdout) == 0 and conflicted(py.stdout), lines(py.stdout))


def case_multihop_residual():
    """Pinned as CURRENT behaviour, not as the right one (WRT-016).

    After a_old -> a_new -> a_newer, the holder of the two RETIRED keys a_old
    and a_new forks at the root. The uncompromised current key's record is
    unbound by the store-wide conflict along with everything else. Found by the
    DeepReview of paper 1.1.0.
    """
    tmp, store, keys, opaque, subject, root, trust = world("multihop")
    rot1 = T.add_record(store, T.body("accept", key_blob(store, keys["a_new"], keys["a_newer"]),
                                      [opaque], "a@x", prior=[root], ts=2),
                        [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
    rot2 = T.add_record(store, T.body("accept", key_blob(store, keys["a_newer"]),
                                      [opaque], "a@x", prior=[rot1], ts=3),
                        [("a@x", keys["a_new"]), ("a@x", keys["a_newer"])])
    cur = T.add_record(store, T.body("propose", subject, [opaque], "a@x", prior=[rot2],
                                     because=[{"kind": "prose", "text": "current key"}], ts=4),
                       [("a@x", keys["a_newer"])])
    py, go, rs = run_all(store, trust)
    check("5. before the fork: the current key's record is bound, no conflict",
          bound(py.stdout, cur, keys["a_newer"]) and not conflicted(py.stdout), lines(py.stdout))
    T.add_record(store, T.body("accept", key_blob(store, keys["a_new"], keys["a_fork"]),
                               [opaque], "a@x", prior=[root], ts=5),
                 [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
    py, go, rs = run_all(store, trust)
    agree("multihop residual", py, go, rs)
    check("5. residual, pinned: two RETIRED keys fork at the root -> store-wide conflict "
          "that unbinds the uncompromised current key's record and the genesis root",
          errors(py.stdout) == 0 and conflicted(py.stdout)
          and not bound(py.stdout, cur) and not bound(py.stdout, root), lines(py.stdout))


def case_no_revocation():
    """WRT-017, decided A: there is no revocation operation. A supersede of the
    introducing rotation is an ordinary record and MUST NOT change key state,
    so the key stays bound. (Before the decision this case pinned the same
    behaviour as an unimplemented promise of SPEC.)"""
    tmp, store, keys, opaque, subject, root, trust = world("no-revocation")
    rot = T.add_record(store, T.body("accept", key_blob(store, keys["a_new"], keys["a_newer"]),
                                     [opaque], "a@x", prior=[root], ts=2),
                       [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
    sup = T.add_record(store, T.body("supersede", rot, [opaque], "a@x", prior=[rot],
                                     because=[{"kind": "prose", "text": "revoke a_new"}], ts=3),
                       [("a@x", keys["a_new"])])
    after = T.add_record(store, T.body("propose", subject, [opaque], "a@x", prior=[sup],
                                       because=[{"kind": "prose", "text": "after revocation"}], ts=4),
                         [("a@x", keys["a_new"])])
    py, go, rs = run_all(store, trust)
    agree("no revocation", py, go, rs)
    check("6. no revocation (WRT-017 A): a supersede of a rotation leaves the key bound",
          errors(py.stdout) == 0 and bound(py.stdout, after, keys["a_new"]), lines(py.stdout))


def main():
    for binary in (T.GO, RS):
        if not os.path.isfile(binary):
            print(f"UNRUN  {binary} not built")
            return 3
    case_chain()
    case_retired_key()
    case_terminal()
    case_residual()
    case_multihop_residual()
    case_no_revocation()
    print(f"\nWRT-015-PRE-ROTATION: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
