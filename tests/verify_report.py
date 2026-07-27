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

TEST_RT = "test@v1"
if TEST_RT not in W.RUNTIMES["0.2"]:
    W.RUNTIMES["0.2"] = W.RUNTIMES["0.2"] + (TEST_RT,)

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


REPORT_TOP_KEYS = {"report", "grade", "ok", "records", "errors", "warnings", "findings"}
FINDING_KEYS = {"level", "subject", "message"}


def report_contract_ok(rep):
    """The OWNER-SIDE producer contract the README now promises (Codex contract
    gate): warrant.verify-report@v0 is a CLOSED schema and its counts bind its
    findings. Returns (ok, reason). A later producer change that drifts from the
    published shape MUST fail here, not only in a downstream consumer."""
    if not isinstance(rep, dict):
        return False, "report is not an object"
    if set(rep) != REPORT_TOP_KEYS:
        return False, f"top-level keys {sorted(rep)} != documented v0 set"
    err_c = warn_c = 0
    for f in rep["findings"]:
        if not isinstance(f, dict) or set(f) != FINDING_KEYS:
            return False, "a finding is not exactly {level, subject, message}"
        if f["level"] not in ("ERR", "WARN"):
            return False, f"finding level {f['level']!r} is not ERR/WARN"
        err_c += f["level"] == "ERR"
        warn_c += f["level"] == "WARN"
    if err_c != rep["errors"]:
        return False, f"errors {rep['errors']} != |ERR findings| {err_c}"
    if warn_c != rep["warnings"]:
        return False, f"warnings {rep['warnings']} != |WARN findings| {warn_c}"
    return True, "ok"


def contract(name, rep):
    """Assert report_contract_ok on one report and register a pass/fail line."""
    good, why = report_contract_ok(rep)
    return check(f"[contract:{name}] closed v0 schema + counts bind findings", good, why)


def counts_from_text(out):
    import re
    m = re.search(r"(\d+) records, (\d+) errors, (\d+) warnings", out)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def run_vector(name, d, settlement_args):
    """Run the full invariant battery for one store fixture."""
    py_text = sh(PY + ["--store", d, "verify"] + settlement_args)
    py_json = sh(PY + ["--store", d, "verify", "--json"] + settlement_args)
    go_text = sh([GO, "verify"] + settlement_args + [d])
    go_json = sh([GO, "verify"] + settlement_args + ["--json", d])

    pj = one_json_object(py_json.stdout)
    gj = one_json_object(go_json.stdout)

    ok = True
    ok &= check(f"[{name}] PY --json is exactly one physical line / JSON object",
                pj is not None, repr(py_json.stdout[:200]) + " ERR:" + py_json.stderr[:120])
    ok &= check(f"[{name}] GO --json is exactly one physical line / JSON object",
                gj is not None, repr(go_json.stdout[:200]) + " ERR:" + go_json.stderr[:120])
    # JSON mode emits NO human text on stdout beyond the object, and nothing on
    # stderr (a preflight failure is the report itself, not a stderr diagnostic).
    ok &= check(f"[{name}] PY --json stderr is empty", py_json.stderr == "",
                repr(py_json.stderr[:160]))
    ok &= check(f"[{name}] GO --json stderr is empty", go_json.stderr == "",
                repr(go_json.stderr[:160]))
    if pj is None or gj is None:
        return
    # OWNER-SIDE producer contract on every Python and Go report (Codex contract gate)
    contract(f"{name}/py", pj)
    contract(f"{name}/go", gj)
    # counts + exit parity between text and JSON (Python)
    text_counts = counts_from_text(py_text.stdout)
    ok &= check(f"[{name}] text/JSON same counts (PY)",
                text_counts == (pj["records"], pj["errors"], pj["warnings"]),
                f"text={text_counts} json={(pj['records'], pj['errors'], pj['warnings'])}")
    ok &= check(f"[{name}] text/JSON same exit (PY)",
                py_text.returncode == py_json.returncode,
                f"{py_text.returncode} vs {py_json.returncode}")
    # counts + exit parity between text and JSON (Go). Go base text mode uses flat
    # mode on a non-store, so only compare when Go text actually produced a summary.
    go_text_counts = counts_from_text(go_text.stdout)
    if go_text_counts is not None:
        ok &= check(f"[{name}] text/JSON same counts (GO)",
                    go_text_counts == (gj["records"], gj["errors"], gj["warnings"]),
                    f"text={go_text_counts} json={(gj['records'], gj['errors'], gj['warnings'])}")
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

    # 10a. Python is store-only (Store.require checks records/): verify_report + the
    #      --json CLI fail closed on EVERY non-store shape, and Python text/JSON agree
    #      on exit. (Codex gate P1-1.)
    py_nonstore = {
        "missing-path": os.path.join(tempfile.mkdtemp(), "does-not-exist"),
        "non-store-dir": tempfile.mkdtemp(),
    }
    rf = tempfile.mkdtemp(); open(os.path.join(rf, "records"), "w").write("x")
    py_nonstore["records-as-file"] = rf
    bw = tempfile.mkdtemp(); os.mkdir(os.path.join(bw, "blobs"))
    py_nonstore["blobs-no-records"] = bw
    for label, path in py_nonstore.items():
        api = W.verify_report(W.Store(path))
        pj = sh(PY + ["--store", path, "verify", "--json"])
        pt = sh(PY + ["--store", path, "verify"])
        pjo = one_json_object(pj.stdout)
        good = (api["ok"] is False and api["errors"] == 1
                and any(f["subject"] == "store" for f in api["findings"])
                and pjo is not None and pjo["ok"] is False
                and pj.returncode == 1 and pt.returncode == pj.returncode
                and pj.stderr == "")
        check(f"[py-nonstore:{label}] fail-closed ok:false, one report, text/json same exit",
              good, f"api={api.get('ok')} json={pjo and pjo.get('ok')}/{pj.returncode} "
              f"text-rc={pt.returncode} stderr={pj.stderr[:60]!r}")
        contract(f"py-nonstore:{label}/api", api)
        if pjo is not None:
            contract(f"py-nonstore:{label}/cli", pjo)

    # 10b. Renderer-independence for Go (Codex re-gate P1): the report sink MUST NOT
    #      reclassify the input. Go text and Go --json select the SAME verifier —
    #      flat mode is preserved in both. Compare exit AND (when text emits a
    #      summary) counts on the real flat examples/, an empty dir, and a missing
    #      path; the missing path is the only fail-closed case (rc 1, one report).
    empty_dir = tempfile.mkdtemp()
    for label, path, expect_report in [("examples", "examples", False),
                                       ("empty-flat-dir", empty_dir, False),
                                       ("missing-path", py_nonstore["missing-path"], True)]:
        gt = sh([GO, "verify", path])
        gj = sh([GO, "verify", "--json", path])
        gjo = one_json_object(gj.stdout)
        gt_counts = counts_from_text(gt.stdout)
        good = (gt.returncode == gj.returncode and gjo is not None and gj.stderr == ""
                and (gt_counts is None
                     or gt_counts == (gjo["records"], gjo["errors"], gjo["warnings"])))
        if expect_report:
            good = good and gjo["ok"] is False and gt.returncode == 1
        check(f"[go-renderer-indep:{label}] Go text and --json select the same verifier",
              good, f"text rc{gt.returncode} {gt_counts} | json rc{gj.returncode} "
              f"{gjo and (gjo['records'],gjo['errors'],gjo['warnings'])} stderr={gj.stderr[:60]!r}")
        if gjo is not None:
            contract(f"go-renderer-indep:{label}", gjo)

    # 10c. an initialized EMPTY store is a successful verification (ok:true), both.
    es = tempfile.mkdtemp(); W.Store(es).init()
    api = W.verify_report(W.Store(es))
    ge = sh([GO, "verify", "--json", es]); geo = one_json_object(ge.stdout)
    check("[empty-store] initialized empty store is ok:true records:0 (Py API + Go)",
          api["ok"] is True and api["records"] == 0 and api["errors"] == 0
          and geo is not None and geo["ok"] is True and geo["records"] == 0)
    contract("empty-store/api", api)
    if geo is not None:
        contract("empty-store/go", geo)

    # 10d. explicit --store-mode disambiguates the empty-shape (Codex re-gate 2 P1):
    #      the four non-store shapes fail closed IDENTICALLY in Python and Go and in
    #      BOTH renderers, and an empty flat dir is no longer a silent ok:true. The
    #      flag (not the renderer) selects the verifier, so text == JSON.
    for label, path in py_nonstore.items():
        pj = sh(PY + ["--store", path, "verify", "--json", "--store-mode"])
        pt = sh(PY + ["--store", path, "verify", "--store-mode"])
        gj = sh([GO, "verify", "--store-mode", "--json", path])
        gt = sh([GO, "verify", "--store-mode", path])
        pjo, gjo = one_json_object(pj.stdout), one_json_object(gj.stdout)
        good = (pjo is not None and gjo is not None
                and pjo["ok"] is False and gjo["ok"] is False        # Py == Go
                and pj.returncode == pt.returncode == 1              # Py text == json exit
                and gj.returncode == gt.returncode == 1              # Go text == json exit
                and gj.stderr == "" and pj.stderr == ""
                and any(f["subject"] == "store" for f in gjo["findings"]))
        check(f"[store-mode:{label}] Py/Go parity, renderer-independent, fail-closed", good,
              f"py={pjo and pjo.get('ok')}/{pj.returncode} go={gjo and gjo.get('ok')}/{gj.returncode} "
              f"goText={gt.returncode}")
        if pjo is not None:
            contract(f"store-mode:{label}/py", pjo)
        if gjo is not None:
            contract(f"store-mode:{label}/go", gjo)
    # a real store under --store-mode is unchanged (ok:true), both renderers/impls
    esj = sh([GO, "verify", "--store-mode", "--json", es]); esjo = one_json_object(esj.stdout)
    check("[store-mode:empty-store] a real (empty) store still verifies ok:true",
          esjo is not None and esjo["ok"] is True and esjo["records"] == 0)
    if esjo is not None:
        contract("store-mode:empty-store/go", esjo)

    # 11. generic runtime reporter (Codex gate P1-2): a registered handler making a
    #     malformed reporter call must be renderer-INDEPENDENT (text==quiet==report),
    #     bounded to one dispatcher ERR, schema-valid (levels subset ERR|WARN), and
    #     JSON-serializable. A valid WARN must fold into the count in all renderers.
    def rt_store(handler):
        W._RUNTIME_HANDLERS.pop(("0.2", TEST_RT), None)
        W.register_runtime("0.2", TEST_RT, handler)
        dd = tempfile.mkdtemp(); st = W.Store(dd); st.init()
        kp = os.path.join(dd, "k.hex"); open(kp, "w").write("11" * 32)
        chk = st.put_blob(b"cb"); subj = st.put_blob(b"sb"); pol = st.put_blob(b'{"p":"x"}')
        body = {"warrant": "0.2", "decision": "accept", "subject": {"hash": subj},
                "under": [pol], "because": [{"kind": "check", "check": chk,
                "runtime": TEST_RT, "verdict": "pass"}], "evidence": [],
                "actor": {"id": "a@t"}, "prior": [], "ts": 1}
        st.put_record({"body": body, "sigs": [W.sign_envelope(body, "a@t", kp)]})
        return dd
    # hostile str SUBCLASSES (Codex re-gate P1): isinstance(x, str) would admit
    # these; their __getitem__/__format__ execute code only during loud rendering,
    # AFTER a count mutation — making text and JSON disagree. The exact-type check
    # must reject them BEFORE any mutation/rendering.
    class SliceBomb(str):
        def __getitem__(self, k):
            raise RuntimeError("slice bomb")

    class FormatBomb(str):
        def __format__(self, spec):
            raise RuntimeError("format bomb")

    # handlers that SWALLOW the boundary rejection (Codex re-gate 2 P1): the fault
    # must be latched in verifier-owned state, so a broad try/except in the handler
    # cannot restore ok:true. The verifier-owned reporter no longer raises, so there
    # is nothing to catch — but even a handler that expects/handles an exception
    # must still yield exactly one fail-closed ERR.
    def swallow_invalid(v, m, o, w, r):
        try:
            o("INFO", w, "invalid")
        except Exception:
            pass

    def swallow_then_valid(v, m, o, w, r):
        try:
            o("WARN", SliceBomb(w), "x")
        except Exception:
            pass
        o("WARN", w, "legit")               # a valid WARN after a swallowed violation

    def multi_swallow(v, m, o, w, r):
        for _ in range(5):
            try:
                o("INFO", w, "bad")
            except Exception:
                pass

    reporters = {
        "invalid-level": lambda v, m, o, w, r: o("INFO", w, "x"),
        "nonstr-subject": lambda v, m, o, w, r: o("WARN", 7, "x"),
        "dict-message": lambda v, m, o, w, r: o("WARN", w, {"x": "y"}),
        "bytes-message": lambda v, m, o, w, r: o("WARN", w, b"bytes"),
        "slicebomb-subject": lambda v, m, o, w, r: o("WARN", SliceBomb(w), "hw"),
        "formatbomb-message": lambda v, m, o, w, r: o("WARN", w, FormatBomb("hw")),
        "swallow-invalid": swallow_invalid,
        "swallow-then-valid": swallow_then_valid,
        "multi-swallow": multi_swallow,
        "valid-warn": lambda v, m, o, w, r: o("WARN", w, "handler ran"),
    }
    for label, handler in reporters.items():
        dd = rt_store(handler)
        te, tw = W.verify_store(W.Store(dd), quiet=False)
        qe, qw = W.verify_store(W.Store(dd), quiet=True)
        r2 = {}
        W.verify_store(W.Store(dd), quiet=True, report_out=r2)
        try:
            json.dumps(r2); ser = True
        except TypeError:
            ser = False
        # a malformed reporter call fails closed (>=1 error) in EVERY renderer;
        # a valid WARN keeps errors==0. Either way loud == quiet == report.
        errs_ok = (r2["errors"] == 0) if label == "valid-warn" else (r2["errors"] >= 1)
        good = ((te, tw) == (qe, qw) == (r2["errors"], r2["warnings"]) and ser and errs_ok
                and all(f["level"] in ("ERR", "WARN") for f in r2["findings"]))
        check(f"[reporter:{label}] renderer-independent, serializable, schema-valid, fail-closed",
              good, f"text={(te,tw)} quiet={(qe,qw)} report={(r2['errors'],r2['warnings'])} ser={ser}")
        # the FULL machine report for this fixture must also honour the closed
        # schema + counts binding (a fault ERR still keeps errors==|ERR findings|).
        contract(f"reporter:{label}", W.verify_report(W.Store(dd)))
    W._RUNTIME_HANDLERS.pop(("0.2", TEST_RT), None)

    # 12. U+2028 / U+2029 must not split the output: exactly ONE physical line in
    #     both implementations (Codex gate P2-3). Actor id carries the separator.
    d = tempfile.mkdtemp(); st = W.Store(d); st.init()
    kp = os.path.join(d, "k"); open(kp, "w").write((bytes([1]) * 32).hex() + "\n")
    pol = st.put_blob(b"p"); subj = st.put_blob(b"s")
    sep_actor = "a\u2028b\u2029c"  # U+2028 LINE SEP + U+2029 PARAGRAPH SEP in the id
    body = {"warrant": "0.2", "decision": "accept", "subject": {"hash": subj},
            "under": [pol], "because": [], "evidence": [],
            "actor": {"id": sep_actor}, "prior": [], "ts": 1}
    st.put_record({"body": body, "sigs": [W.sign_envelope(body, sep_actor, kp)]})
    pj = sh(PY + ["--store", d, "verify", "--json"])
    gj = sh([GO, "verify", "--json", d])
    check("[u2028] PY output is exactly one physical line",
          len(pj.stdout.rstrip("\n").splitlines()) == 1 and one_json_object(pj.stdout) is not None,
          f"lines={len(pj.stdout.rstrip(chr(10)).splitlines())}")
    check("[u2028] GO output is exactly one physical line",
          len(gj.stdout.rstrip("\n").splitlines()) == 1 and one_json_object(gj.stdout) is not None,
          f"lines={len(gj.stdout.rstrip(chr(10)).splitlines())}")

    # 13. the contract assertion has TEETH: it must REJECT a drifted producer, not
    #     pass vacuously (Codex contract gate).
    base = {"report": "warrant.verify-report@v0", "grade": "base", "ok": True,
            "records": 1, "errors": 0, "warnings": 0, "findings": []}
    def mut(**kw):
        r = dict(base); r.update(kw); return r
    violations = {
        "extra top-level key": mut(extra=1),
        "missing top-level key": {k: v for k, v in base.items() if k != "grade"},
        "errors != |ERR findings|": mut(errors=1),
        "warnings != |WARN findings|": mut(warnings=1),
        "INFO finding level": mut(errors=0, findings=[{"level": "INFO", "subject": "x", "message": "y"}]),
        "finding extra key": mut(errors=1, findings=[{"level": "ERR", "subject": "x", "message": "y", "code": 9}]),
    }
    for label, bad in violations.items():
        good, _ = report_contract_ok(bad)
        check(f"[contract-teeth] rejects: {label}", not good)
    check("[contract-teeth] accepts the valid baseline", report_contract_ok(base)[0])

    print()
    if FAILS:
        print(f"VERIFY-REPORT: {len(FAILS)} FAIL(S): " + ", ".join(FAILS))
        sys.exit(1)
    print("VERIFY-REPORT: ALL PASS")


if __name__ == "__main__":
    main()
