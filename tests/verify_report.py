#!/usr/bin/env python3
"""Vectors for the NON-NORMATIVE structured verify report (warrant.verify-report@v0).

Invariants (per the integration-API brief):
  1. `warrant verify --json` (Py) and `warrant-go verify --json` (Go) each print
     EXACTLY ONE JSON object, no human text.
  2. Text output and exit code are byte-identical whether or not --json is used;
     the JSON `errors`/`warnings`/exit match the text counts/exit exactly.
  3. `ok == (errors == 0)`; `warnings` is always present; `grade` is base|settlement.
  4. Findings are in a deterministic order (records iterate in sorted-WarrantID
     order), so a re-run is byte-identical.
  5. Python and Go agree SEMANTICALLY: same report/grade/ok/records/errors/
     warnings and the same multiset of (level, subject) findings. Finding MESSAGE
     prose may differ where a tracked P2 already allows it (e.g. a malformed
     ski@v1 blob) — that is compared loosely.
  6. quiet does not change truth: verify_store(quiet=True) counts == quiet=False.
  7. No byte-domain input raises: adversarial fixtures produce a bounded report.
"""
import importlib.util
import json
import os
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

FAILS = []


def sh(args):
    return subprocess.run(args, capture_output=True, text=True)


def store_with(records=(), blobs=(), key_byte=1):
    """records: iterable of (name.json, raw_str). blobs: iterable of raw bytes ->
    returns hashes list via out param not needed here; use W.Store to put."""
    d = tempfile.mkdtemp()
    st = W.Store(d)
    st.init()
    kp = os.path.join(d, "k")
    open(kp, "w").write((bytes([key_byte]) * 32).hex() + "\n")
    hashes = [st.put_blob(b) for b in blobs]
    for name, raw in records:
        (st.records / name).write_text(raw)
    return d, st, kp, hashes


def signed_record(st, kp, subject, under, actor="a@t", because=None, decision="accept",
                  ts=1, version="0.2"):
    body = {"warrant": version, "decision": decision, "subject": {"hash": subject},
            "under": list(under), "because": list(because or []), "evidence": [],
            "actor": {"id": actor}, "prior": [], "ts": ts}
    env = {"body": body, "sigs": [W.sign_envelope(body, actor, kp)]}
    return st.put_record(env)


def trust_for(d, kp, actor="a@t", extra=None):
    tp = os.path.join(d, "trust.json")
    doc = {"actors": {actor: [W.pubkey_hex(W.load_key(kp))]}}
    if extra:
        doc.update(extra)
    open(tp, "w").write(json.dumps(doc))
    return tp


def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else "  <<< " + detail))
    if not cond:
        FAILS.append(name)
    return cond


def one_json_object(out):
    lines = out.strip().splitlines()
    if len(lines) != 1:
        return None
    try:
        return json.loads(lines[0])
    except ValueError:
        return None


def semantic(o):
    return (o["report"], o["grade"], o["ok"], o["records"], o["errors"], o["warnings"],
            sorted((f["level"], f["subject"]) for f in o["findings"]))


def run_vector(name, d, settlement_args):
    """Run the full invariant battery for one store fixture."""
    py_text = sh(PY + ["--store", d, "verify"] + settlement_args)
    py_json = sh(PY + ["--store", d, "verify", "--json"] + settlement_args)
    go_args = [GO, "verify"] + settlement_args + ["--json", d]
    go_json = sh(go_args)

    pj = one_json_object(py_json.stdout)
    gj = one_json_object(go_json.stdout)

    ok = True
    ok &= check(f"[{name}] PY --json is exactly one JSON object", pj is not None,
                repr(py_json.stdout[:200]) + " ERR:" + py_json.stderr[:120])
    ok &= check(f"[{name}] GO --json is exactly one JSON object", gj is not None,
                repr(go_json.stdout[:200]) + " ERR:" + go_json.stderr[:120])
    if pj is None or gj is None:
        return
    # counts + exit parity between text and JSON (Python)
    import re
    m = re.search(r"(\d+) records, (\d+) errors, (\d+) warnings", py_text.stdout)
    text_counts = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    ok &= check(f"[{name}] text/JSON same counts (PY)",
                text_counts == (pj["records"], pj["errors"], pj["warnings"]),
                f"text={text_counts} json={(pj['records'], pj['errors'], pj['warnings'])}")
    ok &= check(f"[{name}] text/JSON same exit (PY)",
                py_text.returncode == py_json.returncode,
                f"{py_text.returncode} vs {py_json.returncode}")
    ok &= check(f"[{name}] ok == (errors==0)", pj["ok"] == (pj["errors"] == 0))
    ok &= check(f"[{name}] warnings field present", "warnings" in pj)
    ok &= check(f"[{name}] report tag + grade",
                pj["report"] == "warrant.verify-report@v0"
                and pj["grade"] == ("settlement" if settlement_args else "base"))
    # determinism: a re-run is byte-identical
    py_json2 = sh(PY + ["--store", d, "verify", "--json"] + settlement_args)
    ok &= check(f"[{name}] PY --json deterministic (byte-identical re-run)",
                py_json.stdout == py_json2.stdout)
    # exit-code parity Py/Go
    ok &= check(f"[{name}] PY/GO same exit", py_json.returncode == go_json.returncode,
                f"{py_json.returncode} vs {go_json.returncode}")
    # semantic parity Py/Go
    ok &= check(f"[{name}] PY/GO semantic parity", semantic(pj) == semantic(gj),
                f"\n   PY={semantic(pj)}\n   GO={semantic(gj)}")
    return pj


def main():
    HEX = "0" * 64
    # 1. clean base: one valid signed record, no settlement
    d, st, kp, _ = store_with(blobs=[b"the-policy", b"subj-bytes"])
    pol, subj = W.blob_hash(b"the-policy"), W.blob_hash(b"subj-bytes")
    signed_record(st, kp, subj, [pol])
    pj = run_vector("clean-base", d, [])
    check("[clean-base] ok True (no errors)", pj and pj["ok"] and pj["errors"] == 0)

    # 2. clean settlement: same, with a trust config binding the actor
    d, st, kp, _ = store_with(blobs=[b"pol2", b"subj2"])
    pol, subj = W.blob_hash(b"pol2"), W.blob_hash(b"subj2")
    signed_record(st, kp, subj, [pol])
    tp = trust_for(d, kp)
    pj = run_vector("clean-settlement", d, ["--settlement", "--trust-config", tp])
    check("[clean-settlement] 0 errors", pj and pj["errors"] == 0)

    # 3. malformed record
    d, st, kp, _ = store_with(records=[("f" * 64 + ".json", "{ bad")])
    pj = run_vector("malformed-record", d, [])
    check("[malformed-record] an ERR unloadable finding",
          pj and any(f["level"] == "ERR" and "unloadable" in f["message"]
                     for f in pj["findings"]))

    # 4. unavailable trust config (settlement fail-closed)
    d, st, kp, _ = store_with(blobs=[b"p", b"s"])
    signed_record(st, kp, W.blob_hash(b"s"), [W.blob_hash(b"p")])
    pj = run_vector("unavailable-trust", d,
                    ["--settlement", "--trust-config", os.path.join(d, "nope.json")])
    check("[unavailable-trust] one global settlement ERR",
          pj and pj["errors"] == 1
          and any(f["subject"] == "settlement" for f in pj["findings"]))

    # 5. lone surrogate in a record body (must be bounded, not a crash)
    raw = ('{"body":{"warrant":"0.2","decision":"accept","subject":{"hash":"' + "c" * 64
           + '"},"under":["' + "d" * 64 + '"],"because":[],"evidence":[],"actor":{"id":'
           '"\\ud800evil"},"prior":[],"ts":1},"sigs":[]}')
    d, st, kp, _ = store_with(records=[("e" * 64 + ".json", raw)])
    pj = run_vector("lone-surrogate", d, [])
    check("[lone-surrogate] bounded (report produced, not a crash)", pj is not None)

    # 6. invalid threshold policy (settlement): a policy-claiming blob that is not
    #    a valid canonical threshold policy
    d, st, kp, _ = store_with()
    badpol = st.put_blob(b'{"warrant_policy":"0.3","threshold":{"min_sigs":1,"actors":[]}}')
    subj = st.put_blob(b"s6")
    signed_record(st, kp, subj, [badpol])
    tp = trust_for(d, kp)
    pj = run_vector("invalid-threshold-policy", d, ["--settlement", "--trust-config", tp])
    check("[invalid-threshold-policy] the ERR is present",
          pj and any("threshold policy" in f["message"] for f in pj["findings"]))

    # 7. unresolved ski@v1 check reason (exercises the runtime-hook dispatch path)
    d, st, kp, _ = store_with(blobs=[b"s7"])
    subj = st.put_blob(b"s7")
    signed_record(st, kp, subj, [W.blob_hash(b"s7")], decision="reject",
                  because=[{"kind": "check", "check": "a" * 64, "runtime": "ski@v1",
                            "verdict": "pass"}])
    pj = run_vector("ski-unresolved", d, [])
    check("[ski-unresolved] bounded finding, no crash", pj is not None)

    # 8. malformed ski@v1 check blob (non-canonical): present but not JCS
    d, st, kp, _ = store_with()
    badcheck = st.put_blob(b'{"check":"ski@v1", "atp": 1}')  # spaces => non-canonical
    subj = st.put_blob(b"s8")
    signed_record(st, kp, subj, [subj], decision="reject",
                  because=[{"kind": "check", "check": badcheck, "runtime": "ski@v1",
                            "verdict": "pass"}])
    pj = run_vector("ski-malformed", d, [])
    check("[ski-malformed] bounded finding, no crash", pj is not None)

    # 9. quiet does not change truth (Python API level)
    d, st, kp, _ = store_with(blobs=[b"pq", b"sq"])
    signed_record(st, kp, W.blob_hash(b"sq"), [W.blob_hash(b"pq")])
    e1, w1 = W.verify_store(W.Store(d), quiet=True)
    e2, w2 = W.verify_store(W.Store(d), quiet=False)
    check("[quiet-invariance] quiet==loud counts", (e1, w1) == (e2, w2), f"{(e1,w1)} vs {(e2,w2)}")
    rep = {}
    W.verify_store(W.Store(d), quiet=True, report_out=rep)
    check("[quiet-invariance] report_out counts match return",
          (rep["errors"], rep["warnings"]) == (e1, w1))

    print()
    if FAILS:
        print(f"VERIFY-REPORT: {len(FAILS)} FAIL(S): " + ", ".join(FAILS))
        sys.exit(1)
    print("VERIFY-REPORT: ALL PASS")


if __name__ == "__main__":
    main()
