#!/usr/bin/env python3
"""v0.3 settlement differential harness.

Builds temporary .warrants stores for the SPEC §5.1/§7/§9 settlement cases
and requires Python and Go to agree on settlement verdicts plus warning/error
message strings.
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = [sys.executable, os.path.join(ROOT, "impl", "warrant.py")]
GO = os.environ.get("WARRANT_GO", os.path.join(ROOT, "impl-go", "warrant-go"))

spec = importlib.util.spec_from_file_location(
    "warrant_impl", os.path.join(ROOT, "impl", "warrant.py"))
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def canon_file(path, doc):
    data = W.canon(doc)
    open(path, "wb").write(data)
    return hashlib.sha256(data).hexdigest()


def write_key(path, byte):
    open(path, "w").write((bytes([byte]) * 32).hex() + "\n")


def pubkey(key_path):
    return W.pubkey_hex(W.load_key(key_path))


def put_json_blob(store, doc):
    return W.Store(store).put_blob(W.canon(doc))


def put_blob(store, data):
    return W.Store(store).put_blob(data)


def add_record(store, body, signers):
    st = W.Store(store)
    env = {"body": body,
           "sigs": [W.sign_envelope(body, actor, key) for actor, key in signers]}
    return st.put_record(env)


def body(decision, subject, under, actor, prior=None, because=None,
         evidence=None, ts=1751700000, note=None):
    subj = {"hash": subject}
    if note:
        subj["note"] = note
    return {
        "warrant": "0.2",
        "decision": decision,
        "subject": subj,
        "under": list(under),
        "because": list(because or []),
        "evidence": list(evidence or []),
        "actor": {"id": actor},
        "prior": list(prior or []),
        "ts": ts,
    }


def trust_file(tmp, roots=None, actors=None, genesis_hash=None):
    path = os.path.join(tmp, "trust.json")
    doc = {}
    if roots is not None:
        doc["genesis_roots"] = roots
    if actors is not None:
        doc["actors"] = actors
    if genesis_hash is not None:
        doc["genesis_json_sha256"] = genesis_hash
    open(path, "w").write(json.dumps(doc, sort_keys=True, separators=(",", ":")))
    return path


def setup(tmp):
    store = os.path.join(tmp, "warrants")
    W.Store(store).init()
    keys = {}
    for name, byte in [("a_old", 1), ("a_new", 2), ("a_fork", 3),
                       ("b", 4), ("c", 5)]:
        path = os.path.join(tmp, name + ".key")
        write_key(path, byte)
        keys[name] = path
    opaque = put_blob(store, b"opaque policy\n")
    return store, keys, opaque


def report_lines(out):
    msgs = []
    for line in out.splitlines():
        if line.startswith(("WARN", "ERR ")):
            msgs.append(re.split(r"\s{2,}", line, maxsplit=1)[1])
    return sorted(msgs)


def counts(out):
    m = re.search(r"verify: (\d+) records, (\d+) errors, (\d+) warnings", out)
    return (int(m.group(2)), int(m.group(3))) if m else None


def verify_both(store, trust):
    py = sh(PY + ["--store", store, "verify", "--settlement",
                  "--trust-config", trust])
    go = sh([GO, "verify", "--settlement", "--trust-config", trust, store])
    return py, go


def settle_both(store, settling, candidate_path):
    py = sh(PY + ["--store", store, "settle", settling, candidate_path])
    go = sh([GO, "settle", store, settling, candidate_path])
    return py, go


def assert_verify(name, py, go, must_contain=()):
    same = (py.returncode == go.returncode
            and counts(py.stdout) == counts(go.stdout)
            and report_lines(py.stdout) == report_lines(go.stdout))
    has = all(any(needle in msg for msg in report_lines(py.stdout))
              for needle in must_contain)
    ok = same and has
    print(("OK   " if ok else "FAIL "), name,
          f"py={counts(py.stdout)} go={counts(go.stdout)}")
    if not ok:
        print("PY OUT:\n" + py.stdout + py.stderr)
        print("GO OUT:\n" + go.stdout + go.stderr)
    return ok


def assert_settle(name, py, go, text, code):
    ok = (py.returncode == go.returncode == code
          and py.stdout.strip() == go.stdout.strip() == text)
    print(("OK   " if ok else "FAIL "), name, py.stdout.strip(), go.stdout.strip())
    if not ok:
        print("PY ERR:", py.stderr)
        print("GO ERR:", go.stderr)
    return ok


def case_roots_and_adoption(tmp):
    store, keys, opaque = setup(tmp)
    subject1 = put_blob(store, b"root one")
    subject2 = put_blob(store, b"root two")
    r1 = add_record(store, body("accept", subject1, [opaque], "a@x", ts=1),
                    [("a@x", keys["a_old"])])
    r2 = add_record(store, body("accept", subject2, [opaque], "b@x", ts=2),
                    [("b@x", keys["b"])])
    trust = trust_file(tmp, [r1], {"a@x": [pubkey(keys["a_old"])],
                                  "b@x": [pubkey(keys["b"])]})
    py, go = verify_both(store, trust)
    ok = assert_verify("two roots: one genesis, one unadopted", py, go,
                       [W.WARN_UNADOPTED_ROOT])

    threshold = put_json_blob(store, {"warrant_policy": "0.3",
                                      "threshold": {"min_sigs": 2,
                                                    "actors": ["a@x", "b@x"]}})
    adopt_body = body("accept", r2, [threshold], "a@x", prior=[r1], ts=3)
    add_record(store, adopt_body, [("a@x", keys["a_old"]), ("b@x", keys["b"])])
    py, go = verify_both(store, trust)
    ok &= assert_verify("threshold adoption activates second root", py, go)
    ok &= W.WARN_UNADOPTED_ROOT not in "\n".join(report_lines(py.stdout))
    return ok


def case_genesis_json(tmp):
    store, keys, opaque = setup(tmp)
    s1 = put_blob(store, b"portable one")
    s2 = put_blob(store, b"portable two")
    r1 = add_record(store, body("accept", s1, [opaque], "a@x", ts=1),
                    [("a@x", keys["a_old"])])
    r2 = add_record(store, body("accept", s2, [opaque], "b@x", ts=2),
                    [("b@x", keys["b"])])
    g = os.path.join(store, "genesis.json")
    good_hash = canon_file(g, {"roots": [r1, r2]})
    trust = trust_file(tmp, actors={"a@x": [pubkey(keys["a_old"])],
                                    "b@x": [pubkey(keys["b"])]},
                       genesis_hash=good_hash)
    py, go = verify_both(store, trust)
    ok = assert_verify("pinned genesis.json roots are used", py, go)
    canon_file(g, {"roots": [r1]})
    py, go = verify_both(store, trust)
    ok &= assert_verify("tampered genesis.json is unused", py, go,
                        [W.WARN_GENESIS_UNVERIFIED, W.WARN_UNADOPTED_ROOT])
    return ok


def case_invalid_policy(tmp):
    store, keys, _opaque = setup(tmp)
    bad_policy = put_json_blob(store, {"warrant_policy": "0.3",
                                       "threshold": {"min_sigs": 2,
                                                     "actors": ["a@x"],
                                                     "extra": True}})
    r = add_record(store, body("accept", put_blob(store, b"bad"), [bad_policy],
                               "a@x", ts=1),
                   [("a@x", keys["a_old"])])
    trust = trust_file(tmp, [r], {"a@x": [pubkey(keys["a_old"])]})
    py, go = verify_both(store, trust)
    return assert_verify("invalid threshold policy is an error", py, go,
                         [W.ERR_INVALID_THRESHOLD])


def case_relitigation(tmp):
    sg = W.load_sigma()
    if sg is None:
        print("SKIP  re-litigation ski@v1 fingerprints (sigma oracle not found)")
        return True
    store, keys, opaque = setup(tmp)
    subject = put_blob(store, b"question")
    pass_check = put_json_blob(store, {"ski": 1, "term": sg.S_H.hex(), "atp": 20,
                                      "expect": sg.S_H.hex()})
    pass_again = put_json_blob(store, {"ski": 1, "term": sg.S_H.hex(), "atp": 21,
                                      "expect": sg.S_H.hex()})
    fail_check = put_json_blob(store, {"ski": 1, "term": sg.S_H.hex(), "atp": 20,
                                      "expect": "0" * 64})
    settled = add_record(store, body("accept", subject, [opaque], "a@x",
                                     because=[{"kind": "check", "runtime": "ski@v1",
                                                "check": pass_check,
                                                "verdict": "pass"}], ts=1),
                         [("a@x", keys["a_old"])])
    new_ev = put_blob(store, b"new evidence")
    candidates = {
        "new evidence": body("reject", subject, [opaque], "a@x", prior=[settled],
                             evidence=[new_ev], because=[{"kind": "prose", "text": "new"}], ts=2),
        "new fingerprint": body("reject", subject, [opaque], "a@x", prior=[settled],
                                because=[{"kind": "check", "runtime": "ski@v1",
                                           "check": fail_check, "verdict": "fail"}], ts=3),
        "restatement": body("accept", subject, [opaque], "a@x", prior=[settled],
                            because=[{"kind": "check", "runtime": "ski@v1",
                                       "check": pass_again, "verdict": "pass"}], ts=4),
    }
    ok = True
    for name, cand in candidates.items():
        path = os.path.join(tmp, name.replace(" ", "-") + ".json")
        open(path, "w").write(json.dumps(cand, sort_keys=True))
        py, go = settle_both(store, settled, path)
        want = {
            "new evidence": ("admissible: (a) new evidence", 0),
            "new fingerprint": ("admissible: (b) new outcome fingerprint", 0),
            "restatement": ("inadmissible: cites nothing new", 1),
        }[name]
        ok &= assert_settle("re-litigation: " + name, py, go, want[0], want[1])
    restatement = candidates["restatement"]
    add_record(store, restatement, [("a@x", keys["a_old"])])
    trust = trust_file(tmp, [settled], {"a@x": [pubkey(keys["a_old"])]})
    py, go = verify_both(store, trust)
    ok &= assert_verify("restatement warns in settlement verify", py, go,
                        [W.WARN_RELITIGATION])
    return ok


def case_key_state(tmp):
    store, keys, opaque = setup(tmp)
    subject = put_blob(store, b"key state subject")
    root = add_record(store, body("accept", subject, [opaque], "a@x", ts=1),
                      [("a@x", keys["a_old"])])
    new_key_blob = put_json_blob(store, {"actor": "a@x", "key": pubkey(keys["a_new"])})
    rot = add_record(store, body("accept", new_key_blob, [opaque], "a@x",
                                 prior=[root], ts=2),
                     [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
    add_record(store, body("propose", subject, [opaque], "a@x", prior=[rot],
                           because=[{"kind": "prose", "text": "after rotation"}], ts=3),
               [("a@x", keys["a_new"])])
    trust = trust_file(tmp, [root], {"a@x": [pubkey(keys["a_old"])]})
    py, go = verify_both(store, trust)
    ok = assert_verify("key rotation binds incoming key", py, go)
    fork_key_blob = put_json_blob(store, {"actor": "a@x", "key": pubkey(keys["a_fork"])})
    add_record(store, body("accept", fork_key_blob, [opaque], "a@x",
                           prior=[root], ts=4),
               [("a@x", keys["a_old"]), ("a@x", keys["a_fork"])])
    py, go = verify_both(store, trust)
    ok &= assert_verify("genuine forked rotation conflicts", py, go,
                        [W.WARN_KEY_CONFLICT])
    return ok


def case_stale_replay(tmp):
    """DeepSeek gate 3, ask 1: a stale once-authorized rotation on a fork is a
    DAG ancestor of the current rotation — ordered, NEVER a conflict. Pins the
    refuted attack so no implementation mistakes branch separation for
    unorderedness (SPEC s5.1 'maximal, mutually unordered')."""
    store, keys, opaque = setup(tmp)
    subject = put_blob(store, b"stale replay subject")
    root = add_record(store, body("accept", subject, [opaque], "a@x", ts=1),
                      [("a@x", keys["a_old"])])
    key2 = put_json_blob(store, {"actor": "a@x", "key": pubkey(keys["a_new"])})
    rot_old = add_record(store, body("accept", key2, [opaque], "a@x",
                                     prior=[root], ts=2),
                         [("a@x", keys["a_old"]), ("a@x", keys["a_new"])])
    key3 = put_json_blob(store, {"actor": "a@x", "key": pubkey(keys["a_fork"])})
    add_record(store, body("accept", key3, [opaque], "a@x",
                           prior=[rot_old], ts=3),
               [("a@x", keys["a_new"]), ("a@x", keys["a_fork"])])
    # the "replay": a fork branch diverging before the newest rotation, keeping
    # rot_old as its latest key-state ancestor — plus activity on that branch
    add_record(store, body("propose", subject, [opaque], "a@x", prior=[root],
                           because=[{"kind": "prose", "text": "fork branch"}],
                           ts=4),
               [("a@x", keys["a_new"])])
    trust = trust_file(tmp, [root], {"a@x": [pubkey(keys["a_old"])]})
    py, go = verify_both(store, trust)
    ok = assert_verify("stale-rotation replay on a fork", py, go)
    no_conflict = all(W.WARN_KEY_CONFLICT not in msg
                      for msg in report_lines(py.stdout))
    print(("OK   " if no_conflict else "FAIL "),
          "stale replay is DAG-ordered -> NO key-state conflict")
    return ok and no_conflict


def main():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        ok &= case_roots_and_adoption(os.path.join(tmp, "roots"))
        ok &= case_genesis_json(os.path.join(tmp, "genesis"))
        ok &= case_invalid_policy(os.path.join(tmp, "policy"))
        ok &= case_relitigation(os.path.join(tmp, "relit"))
        ok &= case_key_state(os.path.join(tmp, "keys"))
        ok &= case_stale_replay(os.path.join(tmp, "stale"))
    print(f"\nSETTLEMENT: {'ALL AGREE' if ok else 'DIVERGENCE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
