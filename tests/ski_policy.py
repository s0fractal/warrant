#!/usr/bin/env python3
"""Tests for ski_policy — the re-executable boolean policy predicate library.

  A. truth table: compiled predicates evaluate to the right Church boolean.
  B. real re-execution: warrant's ski@v1 runtime reproduces each verdict.
  C. integration: a compiled check files into a warrant that verifies clean.

Run: python3 tests/ski_policy.py   (nonzero exit on any failure)
"""
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("SIGMA_GLYPH", None)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


W = _load("warrant_impl", "impl/warrant.py")
sp = _load("ski_policy", "impl/ski_policy.py")

ok = []


def chk(cond, label, detail=""):
    ok.append(cond)
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")


def new_store():
    d = tempfile.mkdtemp()
    s = W.Store(os.path.join(d, ".warrants"))
    s.init()
    return s


T, F = sp.const(True), sp.const(False)


def test_truth_table():
    cases = [
        (sp.Not(T), False, "NOT T"),
        (sp.Not(F), True, "NOT F"),
        (sp.And(T, T), True, "T AND T"),
        (sp.And(T, F), False, "T AND F"),
        (sp.Or(F, F), False, "F OR F"),
        (sp.Or(F, T), True, "F OR T"),
        (sp.And(T, T, T), True, "AND of three T"),
        (sp.Or(F, F, T), True, "OR of three, last T"),
        # a real policy: permit only within window and not retroactive
        (sp.And(sp.Fact("within_window", True), sp.Not(sp.Fact("retroactive", True))),
         False, "within_window AND NOT retroactive (retroactive=T)"),
        (sp.And(sp.Fact("within_window", True), sp.Not(sp.Fact("retroactive", False))),
         True, "within_window AND NOT retroactive (retroactive=F)"),
    ]
    for expr, expected, label in cases:
        c = sp.compile_check(expr, new_store().put_blob)
        chk(c.result == expected, f"{label} == {expected}", f"got {c.result}")


def test_real_reexecution():
    # warrant's own ski@v1 runtime must reproduce the pinned verdict.
    store = new_store()
    c = sp.compile_check(
        sp.And(sp.Fact("within_window", True), sp.Not(sp.Fact("retroactive", True))),
        store.put_blob)
    verdict, rh, spent = W.run_ski_check(store, c.blob)
    chk(verdict == "pass", "warrant re-executes the check -> pass", verdict)
    chk(rh == c.doc["expect"], "re-run result hash == pinned expect")
    chk(spent == c.doc["atp"], "re-run ATP == pinned atp", f"{spent} vs {c.doc['atp']}")
    chk(c.formula == "(within_window AND NOT retroactive)", "formula string", c.formula)
    chk(c.facts == {"within_window": True, "retroactive": True}, "facts recorded", str(c.facts))


def test_integration_warrant():
    # File a real warrant whose reason is a compiled policy predicate, then verify.
    store = new_store()
    key = os.path.join(os.path.dirname(store.root), "k.key")
    open(key, "w").write("ab" * 32 + "\n")
    subject = store.put_blob(b'{"action":"grant_refund","retroactive":true}')
    policy = store.put_blob(b"bereavement discount cannot be applied retroactively")
    c = sp.compile_check(
        sp.And(sp.Fact("within_window", True), sp.Not(sp.Fact("retroactive", True))),
        store.put_blob)
    chk(c.result is False, "policy predicate denies (False)")

    class A:
        pass
    a = A()
    a.under = [policy]
    a.evidence = []
    a.prior = []
    a.reason = ["permit = within_window AND NOT retroactive => deny"]
    a.check = c.blob            # reference the compiled ski@v1 check
    a.runtime = "ski@v1"
    a.verdict = "pass"          # re-execution reproduces the pinned FALSE
    a.transcript = None
    a.relitigates = None
    a.actor, a.key, a.ts = "guard@demo", key, 1708300800
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        wid = W.file_warrant(store, "reject", subject, a, note="retroactive refund")
    errs, _ = W.verify_store(store, quiet=True)
    chk(errs == 0, "warrant with a compiled ski policy verifies clean", f"{errs} errors")
    chk(bool(wid), "warrant filed")


def main():
    test_truth_table()
    test_real_reexecution()
    test_integration_warrant()
    print("\n" + ("SKI-POLICY: ALL PASS" if all(ok) else "SKI-POLICY: FAILURES PRESENT"))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
