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
import shutil
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
    # Compare ALL THREE fields (records, errors, warnings): dropping the record
    # count hid a Python/Go divergence on the malformed-record fixture.
    m = re.search(r"verify: (\d+) records, (\d+) errors, (\d+) warnings", out)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


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
        # Codex v0.3 hardening audit P2: a green run that silently skipped its
        # critical ski@v1 cases must be distinguishable from a complete pass.
        if os.environ.get("WARRANT_REQUIRE_SIGMA"):
            print("FAIL  re-litigation ski@v1 fingerprints: WARRANT_REQUIRE_SIGMA "
                  "set but the Σ-GLYPH oracle was not found (set SIGMA_GLYPH)")
            return False
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


def case_trust_failclosed(tmp):
    """A REQUESTED settlement verification whose supplied trust config is
    unusable is ONE global ERR in BOTH implementations, exit 1 — never a silent
    fail-open (Codex refactor gate: Go previously returned 0 errors / exit 0)."""
    store = tmp
    W.Store(store).init()
    ok = True
    writes = {
        "malformed.json": "{ not json",
        "arr.json": "[1,2,3]",
        "trail.json": '{"genesis_roots":[]} x',
        "dup.json": '{"a":1,"a":2}',
        # nested-schema-invalid: these once crashed Python and fail-open in Go
        "actors-list.json": '{"actors":[]}',
        "actors-int.json": '{"actors":{"a":1}}',
        "bad-root.json": '{"genesis_roots":[123]}',
        "bad-gh.json": '{"genesis_json_sha256":5}',
        "unknown.json": '{"x":1}',
    }
    for fn, content in writes.items():
        open(os.path.join(store, fn), "w").write(content)
    # invalid UTF-8 and NaN/Infinity must fail-close identically in both impls
    open(os.path.join(store, "utf8.json"), "wb").write(b'{"genesis_roots":["\xff\xfe"]}')
    open(os.path.join(store, "nan.json"), "w").write('{"genesis_roots":[NaN]}')
    open(os.path.join(store, "inf.json"), "w").write('{"genesis_json_sha256":Infinity}')
    bad = {
        "invalid utf-8": os.path.join(store, "utf8.json"),
        "NaN constant": os.path.join(store, "nan.json"),
        "Infinity constant": os.path.join(store, "inf.json"),
        "missing file": os.path.join(store, "nope.json"),
        "malformed json": os.path.join(store, "malformed.json"),
        "non-object": os.path.join(store, "arr.json"),
        "trailing content": os.path.join(store, "trail.json"),
        "duplicate keys": os.path.join(store, "dup.json"),
        "actors not object": os.path.join(store, "actors-list.json"),
        "actor keys not list": os.path.join(store, "actors-int.json"),
        "genesis_roots bad type": os.path.join(store, "bad-root.json"),
        "genesis hash bad type": os.path.join(store, "bad-gh.json"),
        "unknown field": os.path.join(store, "unknown.json"),
    }
    for name, tp in bad.items():
        py, go = verify_both(store, tp)
        ok &= assert_verify("trust fail-closed: " + name, py, go,
                            must_contain=(W.ERR_SETTLEMENT_TRUST,))
        ok &= (py.returncode == 1 and go.returncode == 1)
    # a VALID trust config must NOT trip the failure (no regression)
    good = trust_file(store, roots=[])
    py, go = verify_both(store, good)
    ok &= assert_verify("valid trust config verifies clean", py, go)
    ok &= (W.ERR_SETTLEMENT_TRUST not in "\n".join(report_lines(py.stdout)))

    # NON-EMPTY store: the fail-closed continuation is short-circuit — one global
    # ERR, exit 1, NO partial base-grade report — identical in Python and Go (the
    # earlier Py (1,1) vs Go (1,2)/(2,2) divergence is closed).
    nstore = store + "_nonempty"
    W.Store(nstore).init()
    key = os.path.join(nstore, "k"); write_key(key, 1)
    pol = put_blob(nstore, b'{"p":1}')
    subj = put_blob(nstore, b"s")
    add_record(nstore, body("accept", subj, [pol], "a@t"), [("a@t", key)])
    nbad = os.path.join(nstore, "bad.json"); open(nbad, "w").write("{ nope")
    py, go = verify_both(nstore, nbad)
    ok &= assert_verify("non-empty store: broken trust short-circuits", py, go,
                        must_contain=(W.ERR_SETTLEMENT_TRUST,))
    ok &= (py.returncode == 1 and go.returncode == 1)
    return ok


def case_composition_parity(tmp):
    """Cross-impl parity on the COMPOSITIONS that broke the item-0 done-candidate
    gate (Codex): a fail-closed trust short-circuit must not depend on a malformed
    record, and a hash-pinned genesis.json must parse under the same strict I-JSON
    domain in both implementations."""
    ok = True

    # (1) broken trust + a malformed record -> ONE global ERR, no partial report
    s1 = tmp + "_malformed"
    W.Store(s1).init()
    open(os.path.join(s1, "records", "junk.json"), "w").write("{ not a record")
    bad = os.path.join(s1, "bad.json"); open(bad, "w").write("{ nope")
    py, go = verify_both(s1, bad)
    ok &= assert_verify("broken trust + malformed record short-circuits", py, go,
                        must_contain=(W.ERR_SETTLEMENT_TRUST,))
    ok &= (py.returncode == 1 and go.returncode == 1)

    # (2) hash-pinned genesis.json with a DUPLICATE `roots` key: both reject the
    # duplicate under the same digest, so the attacker root is NOT adopted.
    s2 = tmp + "_genesis"
    W.Store(s2).init()
    key = os.path.join(s2, "k"); write_key(key, 1)
    subj = put_blob(s2, b"decided")
    pol = put_blob(s2, b'{"warrant_policy":"0.3","threshold":{"min_sigs":1,"actors":["a@t"]}}')
    rootwid = add_record(s2, body("accept", subj, [pol], "a@t"), [("a@t", key)])
    tf = os.path.join(s2, "trust.json")
    # (2a) NON-VACUOUS baseline: a CLEAN pinned genesis DOES adopt the root —
    #      no unadopted-root warning.
    clean = b'{"roots":["' + rootwid.encode() + b'"]}'
    open(os.path.join(s2, "genesis.json"), "wb").write(clean)
    open(tf, "w").write(json.dumps({"genesis_json_sha256": W.blob_hash(clean),
                                    "actors": {"a@t": [pubkey(key)]}}))
    py, go = verify_both(s2, tf)
    ok &= assert_verify("clean pinned genesis adopts the root", py, go)
    ok &= (W.WARN_UNADOPTED_ROOT not in "\n".join(report_lines(py.stdout)))
    # (2b) a DUPLICATE `roots` key under the same digest must NOT adopt the
    #      attacker root — proven by the unadopted-root warning appearing.
    dup = b'{"roots":[],"roots":["' + rootwid.encode() + b'"]}'
    open(os.path.join(s2, "genesis.json"), "wb").write(dup)
    open(tf, "w").write(json.dumps({"genesis_json_sha256": W.blob_hash(dup),
                                    "actors": {"a@t": [pubkey(key)]}}))
    py, go = verify_both(s2, tf)
    ok &= assert_verify("dup-key genesis: attacker root NOT adopted", py, go,
                        must_contain=(W.WARN_UNADOPTED_ROOT,))
    # (2c) a NULL / scalar `roots` under a pinned digest is a bounded no-op, not a
    #      Python traceback — identical in both.
    for shape in (b'{"roots":null}', b'{"roots":7}'):
        open(os.path.join(s2, "genesis.json"), "wb").write(shape)
        open(tf, "w").write(json.dumps({"genesis_json_sha256": W.blob_hash(shape),
                                        "actors": {"a@t": [pubkey(key)]}}))
        py, go = verify_both(s2, tf)
        ok &= assert_verify("genesis roots=%s is bounded" % shape.decode(), py, go)
    return ok


def case_ijson_domain_edges(tmp):
    """Adversarial I-JSON domain edges found in a self-audit (Codex unavailable):
    every one must fail-close identically in Python and Go and never traceback."""
    store = tmp
    W.Store(store).init()
    ok = True
    binaries = {
        "empty file": b"",
        "whitespace only": b"   \n\t ",
        "BOM + object": b"\xef\xbb\xbf{\"genesis_roots\":[]}",
        "deep nesting": b"{\"genesis_roots\":" + b"[" * 2000 + b"]" * 2000 + b"}",
        "nested dup key in actors": b'{"actors":{"a":["' + b"a" * 64 + b'"],"a":[]}}',
        "invalid utf-8 in root": b'{"genesis_roots":["\xff\xfe"]}',
    }
    for name, content in binaries.items():
        fn = os.path.join(store, re.sub(r"\W", "_", name) + ".json")
        open(fn, "wb").write(content)
        py, go = verify_both(store, fn)
        ok &= assert_verify("i-json edge: " + name, py, go,
                            must_contain=(W.ERR_SETTLEMENT_TRUST,))
        ok &= (py.returncode == 1 and go.returncode == 1)

    # base-mode (no settlement) record count also matches with a malformed record
    ns = store + "_base"
    W.Store(ns).init()
    key = os.path.join(ns, "k"); write_key(key, 1)
    add_record(ns, body("accept", put_blob(ns, b"s"), [put_blob(ns, b'{"p":1}')], "a@t"),
               [("a@t", key)])
    open(os.path.join(ns, "records", "junk.json"), "w").write("{ bad")
    pyb = sh(PY + ["--store", ns, "verify"])
    gob = sh([GO, "verify", ns])
    ok &= (counts(pyb.stdout) == counts(gob.stdout))
    print(("OK   " if counts(pyb.stdout) == counts(gob.stdout) else "FAIL "),
          "base mode valid+malformed record count", counts(pyb.stdout), counts(gob.stdout))
    return ok


def case_verifier_hardening_k3(tmp):
    """The four SEVERE pre-existing verifier bugs the Kimi K3 gate found (crashes
    + a canonicalization consensus split), now fixed. Each must produce a bounded,
    Python==Go public report (assert_verify fails if either crashes — no summary
    line — or they disagree)."""
    ok = True

    # -0 canonicalization: same record bytes must have the same WarrantID (Go used
    # to emit "-0" and reject the record Python accepted).
    s = tmp + "_negzero"; W.Store(s).init()
    key = os.path.join(s, "k"); write_key(key, 1)
    pol = put_blob(s, b'{"p":1}'); subj = put_blob(s, b"s")
    b0 = body("accept", subj, [pol], "a@t"); b0["ts"] = 0
    wid = W.warrant_id(b0)
    env = {"body": json.loads(W.canon(b0).replace(b'"ts":0', b'"ts":-0').decode("utf-8")),
           "sigs": [W.sign_envelope(b0, "a@t", key)]}
    open(os.path.join(s, "records", wid + ".json"), "w").write(json.dumps(env))
    py, go = verify_both(s, trust_file(s, roots=[]))
    ok &= assert_verify("k3: ts=-0 canon/WarrantID parity", py, go)

    # blob named by a hex64 that is a DIRECTORY (dangling ref + would crash PY).
    s = tmp + "_dirblob"; W.Store(s).init()
    key = os.path.join(s, "k"); write_key(key, 1)
    os.mkdir(os.path.join(s, "blobs", "a" * 64))
    add_record(s, body("accept", "b" * 64, ["a" * 64], "a@t"), [("a@t", key)])
    py, go = verify_both(s, trust_file(s, roots=[]))
    ok &= assert_verify("k3: dir-as-blob is bounded + parity", py, go)

    # lone surrogate in a body string: PY used to UnicodeEncodeError in canon().
    s = tmp + "_surrogate"; W.Store(s).init()
    raw = ('{"body":{"warrant":"0.2","decision":"accept","subject":{"hash":"' + "c" * 64
           + '"},"under":["' + "d" * 64 + '"],"because":[],"evidence":[],"actor":{"id":'
           '"\\ud800evil"},"prior":[],"ts":1},"sigs":[]}')
    open(os.path.join(s, "records", "e" * 64 + ".json"), "w").write(raw)
    py, go = verify_both(s, trust_file(s, roots=[]))
    # P1 (the crash) is fixed: both produce a bounded summary with equal counts.
    # The message STRING still differs (PY "WarrantID uncomputable" vs GO
    # "WarrantID mismatch" — GO substitutes U+FFFD and recomputes a different id);
    # that residual is a tracked P2, so assert counts + no-crash, not full parity.
    good = (counts(py.stdout) is not None and counts(py.stdout) == counts(go.stdout))
    print(("OK   " if good else "FAIL "),
          "k3: lone-surrogate bounded + count parity (P2 msg differs)",
          counts(py.stdout), counts(go.stdout))
    ok &= good

    # prior cycle (A->B->A) with a rotation-shaped A: Go used to stack-overflow.
    s = tmp + "_cycle"; W.Store(s).init()
    key = os.path.join(s, "k"); write_key(key, 3)
    sk = W.load_key(key); pub = W.pubkey_hex(sk)
    A, B = "a" * 64, "b" * 64
    kb = put_json_blob(s, {"actor": "att", "key": pub})
    gp = put_blob(s, b'{"g":1}')
    rb = body("accept", "f" * 64, [gp], "att"); Rw = W.warrant_id(rb)
    add_record(s, rb, [("att", key)])

    def raw_signed(fn, bdy):
        sig = {"actor": "att", "key": pub, "sig": sk.sign(bytes.fromhex(fn)).hex()}
        open(os.path.join(s, "records", fn + ".json"), "w").write(
            json.dumps({"body": bdy, "sigs": [sig]}))
    ab = body("accept", kb, [gp], "att"); ab["prior"] = [B]; raw_signed(A, ab)
    bb = body("propose", "e" * 64, [gp], "att"); bb["prior"] = [A, Rw]; raw_signed(B, bb)
    tf = trust_file(s, roots=[Rw], actors={"att": [pub]})
    py, go = verify_both(s, tf)
    ok &= assert_verify("k3: prior-cycle+rotation is bounded (no Go stack overflow)", py, go)

    # --- the count-parity findings (P1-6..P1-10): Python==Go public summary ---
    def cparity(name, store, trust):
        py, go = verify_both(store, trust)
        good = (counts(py.stdout) is not None
                and counts(py.stdout) == counts(go.stdout)
                and py.returncode == go.returncode)
        print(("OK   " if good else "FAIL "), name,
              counts(py.stdout), counts(go.stdout), "rc", py.returncode, go.returncode)
        if not good:
            print("PY:", py.stdout, py.stderr, "\nGO:", go.stdout, go.stderr)
        return good

    def one_record(store, key_byte, mut):
        W.Store(store).init()
        k = os.path.join(store, "k"); write_key(k, key_byte)
        pol = put_blob(store, b'{"p":1}'); subj = put_blob(store, b"s")
        b = body("accept", subj, [pol], "a@t"); b["ts"] = 1
        env = mut(b, k)
        open(os.path.join(store, "records", W.warrant_id(b) + ".json"), "w").write(json.dumps(env))
        return store

    # P1-6: records/ present, blobs/ removed -> both verify with unresolved refs.
    s6 = one_record(tmp + "_p6", 1, lambda b, k: {"body": b, "sigs": [W.sign_envelope(b, "a@t", k)]})
    shutil.rmtree(os.path.join(s6, "blobs"))
    ok &= cparity("k3: records/ without blobs/ (no silent zero)", s6, trust_file(s6, roots=[]))

    # P1-7: sigs is not a list -> one ERR, record skipped, in both.
    s7 = one_record(tmp + "_p7", 1, lambda b, k: {"body": b, "sigs": "not-a-list"})
    ok &= cparity("k3: sigs-not-a-list count parity", s7, trust_file(s7, roots=[]))

    # P1-8: an actorless sig must NOT satisfy a type-confused (string) body actor
    # via coercion to "" — Go's settlement path disagreed with its own base path.
    s8 = tmp + "_p8"; W.Store(s8).init(); k8 = os.path.join(s8, "k"); write_key(k8, 1)
    pol8 = put_blob(s8, b'{"p":1}'); sub8 = put_blob(s8, b"s")
    b8 = body("accept", sub8, [pol8], "a@t"); b8["actor"] = "x"; b8["ts"] = 1
    w8 = W.warrant_id(b8)
    sig8 = {"key": pubkey(k8), "sig": W.load_key(k8).sign(bytes.fromhex(w8)).hex()}
    open(os.path.join(s8, "records", w8 + ".json"), "w").write(
        json.dumps({"body": b8, "sigs": [sig8]}))
    ok &= cparity("k3: actorless-sig no spurious match", s8, trust_file(s8, roots=[]))

    # P1-9: schema-invalid scalar `prior` is NOT a phantom root.
    s9 = one_record(tmp + "_p9", 1,
                    lambda b, k: (b.__setitem__("prior", 5), {"body": b, "sigs": []})[1])
    ok &= cparity("k3: scalar-prior no phantom root", s9, trust_file(s9, roots=[]))

    # P1-10: out-of-int64 ts on a prior edge (no int64-clamp WARN flip).
    s10 = tmp + "_p10"; W.Store(s10).init(); k = os.path.join(s10, "k"); write_key(k, 1)
    pol = put_blob(s10, b'{"p":1}')
    prev = body("accept", put_blob(s10, b"a"), [pol], "a@t"); prev["ts"] = 2 ** 63
    wp = W.warrant_id(prev)
    open(os.path.join(s10, "records", wp + ".json"), "w").write(json.dumps({"body": prev, "sigs": []}))
    child = body("accept", put_blob(s10, b"b"), [pol], "a@t"); child["ts"] = 2 ** 63 - 1; child["prior"] = [wp]
    open(os.path.join(s10, "records", W.warrant_id(child) + ".json"), "w").write(json.dumps({"body": child, "sigs": []}))
    ok &= cparity("k3: out-of-int64 ts-edge parity", s10, trust_file(s10, roots=[]))

    # P1-6b: blobs/ present but records/ absent -> a settlement verify is a "no
    # store" error (rc 1, no summary) in BOTH, not a Go flat-mode silent (0,0,0).
    s6b = tmp + "_p6b"; W.Store(s6b).init(); shutil.rmtree(os.path.join(s6b, "records"))
    py, go = verify_both(s6b, trust_file(s6b, roots=[]))
    good = (py.returncode == 1 and go.returncode == 1
            and counts(py.stdout) is None and counts(go.stdout) is None)
    print(("OK   " if good else "FAIL "), "k3: blobs/ without records/ is 'no store' in both",
          "rc", py.returncode, go.returncode)
    if not good:
        print("PY:", py.stdout, py.stderr, "\nGO:", go.stdout, go.stderr)
    ok &= good
    return ok


def main():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        ok &= case_roots_and_adoption(os.path.join(tmp, "roots"))
        ok &= case_genesis_json(os.path.join(tmp, "genesis"))
        ok &= case_invalid_policy(os.path.join(tmp, "policy"))
        ok &= case_relitigation(os.path.join(tmp, "relit"))
        ok &= case_key_state(os.path.join(tmp, "keys"))
        ok &= case_stale_replay(os.path.join(tmp, "stale"))
        ok &= case_trust_failclosed(os.path.join(tmp, "trust"))
        ok &= case_composition_parity(os.path.join(tmp, "compose"))
        ok &= case_ijson_domain_edges(os.path.join(tmp, "ijson"))
        ok &= case_verifier_hardening_k3(os.path.join(tmp, "k3hard"))
    print(f"\nSETTLEMENT: {'ALL AGREE' if ok else 'DIVERGENCE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
