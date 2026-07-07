#!/usr/bin/env python3
"""Negative-path differential harness (Opus 4.8 review follow-up).

Builds a valid store, then breaks it in every way verification must catch —
tampered signature, forged signer actor, stripped signatures, tampered body,
dangling prior / supersede subject, ski@v1 verdict lie — and asserts BOTH
implementations agree on the damage: identical (errors, warnings) counts,
nonzero where the case demands it. Complements tests/differential.py, which
covers agreement on *valid* inputs.

Usage:  python3 tests/negative.py
Env:    WARRANT_GO=path/to/warrant-go  (default: ./impl-go/warrant-go)
"""
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
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def counts(line):
    m = re.search(r"(\d+) records, (\d+) errors, (\d+) warnings", line)
    return (int(m.group(2)), int(m.group(3))) if m else None


def verify_both(store):
    _, py_out, _ = sh(PY + ["--store", store, "verify"])
    _, go_out, _ = sh([GO, "verify", store])
    return counts(py_out.splitlines()[-1]), counts(go_out.splitlines()[-1])


def build_store(tmp):
    store = os.path.join(tmp, "warrants")
    key = os.path.join(tmp, "k.key")
    sh(PY + ["--store", store, "init"])
    sh(PY + ["--store", store, "keygen", "--out", key])
    pol = os.path.join(tmp, "policy.txt")
    open(pol, "w").write("test policy: anything verifiable goes\n")
    sub = os.path.join(tmp, "subject.txt")
    open(sub, "w").write("the subject under test\n")
    _, under, _ = sh(PY + ["--store", store, "blob", "add", pol])
    _, subj, _ = sh(PY + ["--store", store, "blob", "add", sub])
    _, w1, _ = sh(PY + ["--store", store, "accept", "--subject", subj,
                        "--note", "baseline accept", "--under", under,
                        "--reason", "all checks green in the imaginary CI",
                        "--actor", "tester@negative", "--key", key])
    _, w2, _ = sh(PY + ["--store", store, "supersede", w1, "--note", "supersedes w1",
                        "--under", under, "--reason", "superseded by better evidence",
                        "--actor", "tester@negative", "--key", key])
    return store, key, under, subj, w1, w2


def record_path(store, wid):
    return os.path.join(store, "records", wid + ".json")


def main():
    ok = True

    def case(name, py, go, want_errors=None, want_warn_min=None):
        nonlocal ok
        good = py is not None and py == go
        if good and want_errors is not None:
            good = (py[0] > 0) if want_errors else (py[0] == 0)
        if good and want_warn_min is not None:
            good = py[1] >= want_warn_min
        print(("OK   " if good else "FAIL "), name, f"py={py} go={go}")
        ok &= good

    with tempfile.TemporaryDirectory() as tmp:
        store, key, under, subj, w1, w2 = build_store(tmp)
        if not (len(w1) == 64 and len(w2) == 64):
            sys.exit(f"store build failed: w1={w1!r} w2={w2!r}")

        def fresh(mutate):
            s2 = os.path.join(tmp, "case")
            if os.path.exists(s2):
                shutil.rmtree(s2)
            shutil.copytree(store, s2)
            mutate(s2)
            return s2

        py, go = verify_both(store)
        case("baseline valid store", py, go, want_errors=False)

        def tamper_sig(s):
            p = record_path(s, w1)
            env = json.load(open(p))
            sig = env["sigs"][0]["sig"]
            env["sigs"][0]["sig"] = ("0" if sig[0] != "0" else "1") + sig[1:]
            json.dump(env, open(p, "w"), indent=2, sort_keys=True)
        py, go = verify_both(fresh(tamper_sig))
        case("tampered signature", py, go, want_errors=True)

        def forge_actor(s):
            p = record_path(s, w1)
            env = json.load(open(p))
            env["sigs"][0]["actor"] = "mallory@evil"   # crypto still valid
            json.dump(env, open(p, "w"), indent=2, sort_keys=True)
        py, go = verify_both(fresh(forge_actor))
        case("signer actor != body.actor.id", py, go, want_errors=True)

        def strip_sigs(s):
            p = record_path(s, w1)
            env = json.load(open(p))
            env["sigs"] = []
            json.dump(env, open(p, "w"), indent=2, sort_keys=True)
        py, go = verify_both(fresh(strip_sigs))
        case("signatures stripped", py, go, want_errors=True)

        def tamper_body(s):
            p = record_path(s, w1)
            env = json.load(open(p))
            env["body"]["subject"]["note"] = "quietly rewritten history"
            json.dump(env, open(p, "w"), indent=2, sort_keys=True)
        py, go = verify_both(fresh(tamper_body))
        case("body tampered (id mismatch)", py, go, want_errors=True)

        def drop_superseded(s):
            os.unlink(record_path(s, w1))   # w2's prior AND supersede subject
        py, go = verify_both(fresh(drop_superseded))
        case("dangling prior + supersede subject (SPEC s7 MUST)", py, go,
             want_errors=True)

        if W.load_sigma() is not None:
            # The CLI refuses to file a verdict it cannot reproduce (good), so an
            # honest filer can't create this record. Craft it by hand — the way an
            # attacker with store write access would — and require verify to catch it.
            def ski_lie(s):
                sg = W.load_sigma()
                check = {"ski": 1, "term": sg.S_H.hex(), "atp": 20,
                         "expect": "0" * 64}          # genesis S can never be this
                st = W.Store(s)
                ch = st.put_blob(W.canon(check))
                base = json.load(open(record_path(s, w1)))["body"]
                body = dict(base)
                body.update({
                    "warrant": "0.2", "decision": "accept", "prior": [w2],
                    "subject": {"hash": subj, "note": "lies about a ski verdict"},
                    "ts": base["ts"] + 1,
                    "because": [{"kind": "check", "runtime": "ski@v1",
                                 "check": ch, "transcript": ch, "verdict": "pass"}],
                })
                env = {"body": body,
                       "sigs": [W.sign_envelope(body, "tester@negative", key)]}
                st.put_record(env)
            py, go = verify_both(fresh(ski_lie))
            case("ski@v1 verdict lie (hand-crafted) -> re-run disagrees", py, go,
                 want_warn_min=4)   # 3 binding warnings + at least the mismatch
        else:
            print("SKIP  ski@v1 verdict lie (sigma oracle not found)")

    print(f"\nNEGATIVE: {'ALL AGREE' if ok else 'DIVERGENCE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
