#!/usr/bin/env python3
"""Pedantic edge fixtures (Codex v0.3 pedantic audit follow-ups).

Pins the boundaries the main suites skipped: numeric ts bounds (the P0),
schema-level note bounds, blob-vs-record resolution, unbound-threshold
adoption, settle candidate schema validity. Every case compares BOTH
implementations where an outcome is observable.

Usage:  python3 tests/pedantic_edges.py
Env:    WARRANT_GO=path/to/warrant-go  (default: ./impl-go/warrant-go)
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("WARRANT_GO", os.path.join(ROOT, "impl-go", "warrant-go"))
import settlement as S  # reuse helpers: setup/body/add_record/trust_file/verify_both

spec = importlib.util.spec_from_file_location(
    "warrant_impl", os.path.join(ROOT, "impl", "warrant.py"))
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

GO = os.environ["WARRANT_GO"]
checks = []


def chk(name, cond, detail=""):
    print(("OK   " if cond else "FAIL "), name, "" if cond else detail)
    checks.append(cond)


def go_validate(body):
    """Both impls agree on schema validity via the canon path (Go validates
    on verify; use a store round-trip for the observable outcome)."""
    return None  # schema parity is asserted through verify below


def main():
    base = {"warrant": "0.1", "decision": "propose",
            "subject": {"hash": "a" * 64}, "under": ["b" * 64],
            "because": [], "evidence": [], "actor": {"id": "x@y"},
            "prior": [], "ts": 1}

    # --- ts bounds (the P0) ---
    for ts, valid in ((0, True), (9223372036854775807, True),
                      (9223372036854775808, False), (10 ** 100, False), (-1, False)):
        b = dict(base); b["ts"] = ts
        errs = W.validate_body(b)
        chk(f"py ts={ts} {'valid' if valid else 'invalid'}",
            (not errs) == valid, str(errs))

    # go parity on the observable path: a store with an oversized-ts record
    # must ERR in both verifiers identically
    with tempfile.TemporaryDirectory() as tmp:
        store, keys, opaque = S.setup(tmp)
        wid = S.add_record(store, S.body("propose", opaque, [opaque], "a@x",
                                         because=[{"kind": "prose", "text": "t"}],
                                         ts=1),
                           [("a@x", keys["a_old"])])
        # hand-craft an oversized-ts record (CLI would refuse)
        body = S.body("propose", opaque, [opaque], "a@x",
                      because=[{"kind": "prose", "text": "big"}], ts=10 ** 100)
        env = {"body": body, "sigs": [W.sign_envelope(body, "a@x", keys["a_old"])]}
        W.Store(store).put_record(env)
        py = subprocess.run([sys.executable, os.path.join(ROOT, "impl/warrant.py"),
                             "--store", store, "verify"], capture_output=True, text=True)
        go = subprocess.run([GO, "verify", store], capture_output=True, text=True)
        py_err = "ts must be an integer (unix seconds) in 0..2^63-1" in py.stdout
        go_err = "ts must be an integer (unix seconds) in 0..2^63-1" in go.stdout
        chk("oversized ts is schema ERR in BOTH (no silent clamp)", py_err and go_err,
            f"py={py_err} go={go_err}")
        chk("oversized-ts verify verdict parity",
            py.returncode == go.returncode
            and py.stdout.strip().splitlines()[-1] == go.stdout.strip().splitlines()[-1])

    # --- note schema bounds: 200 multibyte chars valid, 201 invalid ---
    for n, valid in ((200, True), (201, False)):
        b = dict(base); b["subject"] = {"hash": "a" * 64, "note": "б" * n}
        chk(f"py note {n} multibyte chars {'valid' if valid else 'invalid'}",
            (not W.validate_body(b)) == valid)

    # --- blob-vs-record: evidence naming a stored WarrantID resolves NOTHING ---
    with tempfile.TemporaryDirectory() as tmp:
        store, keys, opaque = S.setup(tmp)
        w1 = S.add_record(store, S.body("propose", opaque, [opaque], "a@x",
                                        because=[{"kind": "prose", "text": "t"}], ts=1),
                          [("a@x", keys["a_old"])])
        b2 = S.body("propose", opaque, [opaque], "a@x",
                    because=[{"kind": "prose", "text": "cites a record as evidence"}],
                    ts=2)
        b2["evidence"] = [w1]                     # a record hash, NOT a blob
        env = {"body": b2, "sigs": [W.sign_envelope(b2, "a@x", keys["a_old"])]}
        W.Store(store).put_record(env)
        py = subprocess.run([sys.executable, os.path.join(ROOT, "impl/warrant.py"),
                             "--store", store, "verify"], capture_output=True, text=True)
        go = subprocess.run([GO, "verify", store], capture_output=True, text=True)
        chk("record-as-evidence -> unresolved blob in BOTH (s6 split)",
            "unresolved blob" in py.stdout and "unresolved blob" in go.stdout)
        chk("record-as-evidence warning parity",
            py.stdout.strip().splitlines()[-1] == go.stdout.strip().splitlines()[-1])

    # --- unbound-threshold adoption rejected in BOTH (s5.1/s9) ---
    with tempfile.TemporaryDirectory() as tmp:
        store, keys, opaque = S.setup(tmp)
        pol = S.put_json_blob(store, {"warrant_policy": "0.3",
                                      "threshold": {"min_sigs": 2,
                                                    "actors": ["a@x", "b@x"]}})
        subj = S.put_blob(store, b"root1 subject")
        root1 = S.add_record(store, S.body("accept", subj, [pol], "a@x", ts=1),
                             [("a@x", keys["a_old"])])
        root2 = S.add_record(store, S.body("accept", subj, [opaque], "c@z", ts=2),
                             [("c@z", keys["a_fork"])])
        S.add_record(store, S.body("accept", root2, [pol], "a@x",
                                   prior=[root1], ts=3),
                     [("a@x", keys["a_new"]), ("b@x", keys["a_fork"])])
        trust = S.trust_file(tmp, [root1], {"a@x": [S.pubkey(keys["a_old"])],
                                            "b@x": [S.pubkey(keys["a_old"])]})
        py, go = S.verify_both(store, trust)
        chk("unbound claims never satisfy adoption threshold (BOTH warn unadopted)",
            "unadopted root" in py.stdout and "unadopted root" in go.stdout)
        chk("unbound-adoption warning parity",
            py.stdout.strip().splitlines()[-1] == go.stdout.strip().splitlines()[-1])

    # --- settle candidate must be schema-valid before admissibility ---
    with tempfile.TemporaryDirectory() as tmp:
        store, keys, opaque = S.setup(tmp)
        settled = S.add_record(store, S.body("accept", opaque, [opaque], "a@x",
                                             because=[{"kind": "prose", "text": "s"}],
                                             ts=1),
                               [("a@x", keys["a_old"])])
        bad = {"warrant": "0.1", "decision": "reject", "nonsense": True}
        cand = os.path.join(tmp, "cand.json")
        json.dump(bad, open(cand, "w"))
        py = subprocess.run([sys.executable, os.path.join(ROOT, "impl/warrant.py"),
                             "--store", store, "settle", settled, cand],
                            capture_output=True, text=True)
        go = subprocess.run([GO, "settle", store, settled, cand],
                            capture_output=True, text=True)
        chk("schema-invalid settle candidate rejected (py)",
            py.returncode == 1 and py.stdout.startswith("invalid candidate:"),
            py.stdout + py.stderr)
        # first-error ORDER is diagnostic, not normative: both must reject
        # with rc=1 and the "invalid candidate:" prefix; texts may differ
        chk("schema-invalid settle candidate rejected (go)",
            go.returncode == 1 and go.stdout.startswith("invalid candidate:"),
            f"py {py.stdout.strip()!r} go {go.stdout.strip()!r}")

    ok = all(checks)
    print(f"\nPEDANTIC-EDGES: {'ALL AGREE' if ok else 'FAILURES'} "
          f"({sum(checks)}/{len(checks)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
