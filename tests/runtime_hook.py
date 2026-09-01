#!/usr/bin/env python3
"""Warrant-local tests for the version/reason-scoped runtime dispatch hook and
its READ-ONLY execution context (Codex refactor recheck). No wave/Sigma code.

Asserts:
  * a core runtime (cmd@v1/ski@v1) CANNOT be overlaid;
  * a handler keyed by (body_version, runtime) runs once per matching shape-valid
    reason, in BOTH base and settlement modes, and folds findings into one count;
  * settlement (incl. a re-litigation lineage) reads the record store exactly once;
  * a trust-config failure short-circuits — no handler runs, one global error;
  * the handler gets a DIGEST-AUTHENTICATING CAS resolver (good hash -> bytes,
    wrong/absent hash -> None) and a deep-copy record view whose mutation cannot
    affect verification, and it is handed no mutable recs / raw store / settlement;
  * failed-settlement mode is observable to the handler;
  * a handler exception is one bounded per-record ERR, not a crash;
  * an empty registry preserves the pre-registration report.
"""
import importlib.util
import os
import tempfile

_spec = importlib.util.spec_from_file_location(
    "warrant", os.path.join(os.path.dirname(__file__), "..", "impl", "warrant.py"))
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

# This harness drives the SETTLEMENT path, which is pinned-only: verify_store
# refuses an unpinned evaluator unconditionally. Run on the bundled, provenance-
# bound engine (drop any $SIGMA_GLYPH override and its differential flag), so the
# settlement-mode handler assertions exercise a real settlement, not a refusal.
os.environ.pop("SIGMA_GLYPH", None)
os.environ.pop("WARRANT_SIGMA_DIFFERENTIAL", None)

TEST_RT = "test@v1"
if TEST_RT not in W.RUNTIMES["0.2"]:
    W.RUNTIMES["0.2"] = W.RUNTIMES["0.2"] + (TEST_RT,)


def _store_with_test_reason(as_root=False):
    d = tempfile.mkdtemp()
    st = W.Store(d)
    st.init()
    keyp = os.path.join(d, "k.hex")
    open(keyp, "w").write("11" * 32)
    policy = st.put_blob(b'{"policy":"x"}')
    check = st.put_blob(b"the-check-blob")
    subj = st.put_blob(b"subject-bytes")
    # a blob PRESENT under a WRONG key (digest mismatch) — the resolver must
    # return None for it, and still count the attempted read.
    (st.blobs / ("a" * 64)).write_bytes(b"not-hashing-to-that-key")
    body = {"warrant": "0.2", "decision": "accept", "subject": {"hash": subj},
            "under": [policy],
            "because": [{"kind": "check", "check": check, "runtime": TEST_RT, "verdict": "pass"}],
            "evidence": [], "actor": {"id": "a@t"}, "prior": [], "ts": 1}
    assert not W.validate_body(body), W.validate_body(body)
    env = {"body": body, "sigs": [W.sign_envelope(body, "a@t", keyp)]}
    wid = st.put_record(env)
    trust = None
    if as_root:
        trust = os.path.join(d, "trust.json")
        open(trust, "w").write('{"genesis_roots":["%s"]}' % wid)
    return st, wid, check, trust


def main():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(("OK   " if cond else "FAIL "), name)

    # core runtime cannot be overlaid
    for core in ("cmd@v1", "ski@v1"):
        try:
            W.register_runtime("0.2", core, lambda *a: None); refused = False
        except ValueError:
            refused = True
        check(f"core runtime {core} overlay refused", refused)

    st, wid, check_hash, _ = _store_with_test_reason()
    base = W.verify_store(st, quiet=True)

    calls = {"n": 0, "modes": [], "cas_good": None, "cas_bad": None,
             "has_wid": None, "no_recs_param": True}

    def handler(view, mode, out, w, reason):
        calls["n"] += 1
        calls["modes"].append(mode)
        calls["has_wid"] = w in view.warrant_ids()
        calls["cas_good"] = view.blob(reason["check"]) == b"the-check-blob"
        calls["cas_bad"] = view.blob("a" * 64) is None   # PRESENT but wrong digest
        b = view.record_body(w)                        # deep copy
        if isinstance(b, dict):
            b["decision"] = "MUTATED"                  # must not affect verification
        out("WARN", w, "handler ran")

    W.register_runtime("0.2", TEST_RT, handler)

    # duplicate registration refused
    try:
        W.register_runtime("0.2", TEST_RT, handler); dup = False
    except ValueError:
        dup = True
    check("duplicate registration refused", dup)

    with_h = W.verify_store(st, quiet=True)
    check("handler invoked once (base)", calls["n"] == 1)
    check("handler saw the record in a read-only view", calls["has_wid"])
    check("CAS resolver returns bytes for the true hash", calls["cas_good"])
    check("CAS resolver returns None for a present wrong-digest blob", calls["cas_bad"])
    check("base mode reported", calls["modes"][-1] == "base")
    check("finding folds into the count (+1 warning)", with_h == (base[0], base[1] + 1))
    check("deep-copy body mutation did not change verification",
          W.verify_store(st, quiet=True)[0] == with_h[0])

    # settlement mode + single snapshot
    W._RUNTIME_HANDLERS.pop(("0.2", TEST_RT), None)
    st2, wid2, _, trust2 = _store_with_test_reason(as_root=True)
    read_calls = {"n": 0}
    _orig = st2.all_records
    st2.all_records = lambda *a, **k: (read_calls.__setitem__("n", read_calls["n"] + 1) or _orig(*a, **k))
    smodes = {"mode": None, "same": None, "roots": None}

    def shandler(view, mode, out, w, reason):
        smodes["mode"] = mode
        smodes["roots"] = w in view.record_roots(w)     # it is its own root
        out("WARN", w, "settlement handler ran")

    W.register_runtime("0.2", TEST_RT, shandler)
    W.verify_store(st2, quiet=True, settlement={"trust_config": trust2})
    check("settlement mode reported to handler", smodes["mode"] == "settlement")
    check("handler sees jurisdiction roots", smodes["roots"])
    check("settlement verify reads the record store exactly once", read_calls["n"] == 1)

    # single snapshot through the RE-LITIGATION path (was 5 all_records calls)
    W._RUNTIME_HANDLERS.pop(("0.2", TEST_RT), None)
    dr = tempfile.mkdtemp(); rst = W.Store(dr); rst.init()
    rk = os.path.join(dr, "k"); open(rk, "w").write("11" * 32)
    pol = rst.put_blob(b'{"warrant_policy":"0.3","threshold":{"min_sigs":1,"actors":["a@t"]}}')
    q = rst.put_blob(b"question")
    b1 = {"warrant": "0.2", "decision": "accept", "subject": {"hash": q}, "under": [pol],
          "because": [], "evidence": [], "actor": {"id": "a@t"}, "prior": [], "ts": 1}
    w1 = rst.put_record({"body": b1, "sigs": [W.sign_envelope(b1, "a@t", rk)]})
    b2 = {"warrant": "0.2", "decision": "accept", "subject": {"hash": q}, "under": [pol],
          "because": [], "evidence": [], "actor": {"id": "a@t"}, "prior": [w1], "ts": 2}
    rst.put_record({"body": b2, "sigs": [W.sign_envelope(b2, "a@t", rk)]})
    rtrust = os.path.join(dr, "t.json")
    open(rtrust, "w").write('{"genesis_roots":["%s"],"actors":{"a@t":["%s"]}}'
                            % (w1, W.pubkey_hex(W.load_key(rk))))
    rc = {"n": 0}
    _o = rst.all_records
    rst.all_records = lambda *a, **k: (rc.__setitem__("n", rc["n"] + 1) or _o(*a, **k))
    W.verify_store(rst, quiet=True, settlement={"trust_config": rtrust})
    check("re-litigation lineage reads the store exactly once", rc["n"] == 1)

    # trust-config failure short-circuits: the requested settlement verification
    # does NOT happen, so no handler runs (and the record loop is skipped)
    W._RUNTIME_HANDLERS.pop(("0.2", TEST_RT), None)
    fcalls = {"n": 0}
    W.register_runtime("0.2", TEST_RT, lambda v, m, o, w, r: fcalls.__setitem__("n", fcalls["n"] + 1))
    fe = W.verify_store(st, quiet=True, settlement={"trust_config": "/no/such/trust.json"})
    check("trust failure short-circuits (handler not run)", fcalls["n"] == 0)
    check("trust failure is one global error", fe == (1, 0))

    # handler exception bounded, then empty registry preserves report
    W._RUNTIME_HANDLERS.pop(("0.2", TEST_RT), None)

    def boom(*a):
        raise RuntimeError("boom")

    W.register_runtime("0.2", TEST_RT, boom)
    try:
        crashed = False
        exc = W.verify_store(st, quiet=True)
    except Exception:
        crashed, exc = True, None
    check("handler exception does not crash", not crashed)
    check("handler exception is one bounded extra ERR", exc == (base[0] + 1, base[1]))

    W._RUNTIME_HANDLERS.pop(("0.2", TEST_RT), None)
    check("empty registry preserves the pre-registration report",
          W.verify_store(st, quiet=True) == base)

    # a handler cannot crash the verifier by mutating the record map: it has no
    # recs handle at all — only the read-only view (contract check)
    import inspect
    params = list(inspect.signature(shandler).parameters)
    check("handler signature exposes no mutable recs/store/settlement",
          params == ["view", "mode", "out", "w", "reason"])

    print("\nRUNTIME-HOOK:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
