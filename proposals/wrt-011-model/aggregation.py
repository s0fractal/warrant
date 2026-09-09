#!/usr/bin/env python3
"""WRT-011 model: does bounded aggregation lower inside WPL as it stands?

The claim this file exists to test, rather than assert:

  1. `any` is ALREADY in WPL under the name `in`. `x in [a,b,c]` lowers to a
     real chain of comparisons in the term, so a general `any` is that same
     unroll with an arbitrary predicate, not a new capability class.
  2. `all` is its dual: the same unroll with `&&`.
  3. `count(P) >= k` needs NO numeral. A threshold circuit over the n boolean
     results decides it, so this proposal does not touch Church-natural
     admission — which matters, because that is exactly where sigma-glyph's
     ADR-011 is blocked (EXP-ADR011-01, pre-registered, not started).

Method. Nothing here extends the compiler. Each aggregate is written out as
ORDINARY WPL source and compiled by the real `policy_lang`, then the verdict is
read out of an ACTUAL REDUCTION through `warrant.run_ski_check` off blobs on
disk — never from the compiler's own opinion. The expected answer comes from
Python evaluating the same predicate over the same list. If the sugar were ever
implemented, this is what it would have to compile to.

So a green run here says: the semantics is expressible today and costs what the
table says. It does NOT say the syntax should be added; that is the proposal's
argument, and this is only its operand.
"""
import importlib.util
import itertools
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "impl"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


W = _load("warrant", "impl/warrant.py")
pl = _load("policy_lang", "impl/policy_lang.py")

ok = []


def chk(cond, label, detail=""):
    ok.append(bool(cond))
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")


def reexecute(src):
    """-> (value_from_an_actual_reduction, atp_spent, nodes)."""
    d = tempfile.mkdtemp(prefix="wrt011-")
    store = W.Store(os.path.join(d, ".warrants"))
    store.init()
    c = pl.compile_source(src, store.put_blob)
    verdict, result_hash, spent = W.run_ski_check(store, c.blob)
    if verdict != "pass":
        raise AssertionError(f"re-execution did not reproduce expect: {verdict}")
    t = pl.compile_source("check true").doc["expect"]
    f = pl.compile_source("check false").doc["expect"]
    value = True if result_hash == t else False if result_hash == f else None
    if value is None:
        raise AssertionError("not a Church boolean")
    return value, spent, c.nodes


# ------------------------------------------------------------------ sources
def facts(name, values, ftype="int"):
    return "".join(f"fact {name}{i}: {ftype} = {v}\n"
                   for i, v in enumerate(values))


def any_src(values, threshold):
    """any(v > threshold for v in values) — written as a || chain."""
    body = " || ".join(f"v{i} > {threshold}" for i in range(len(values)))
    return facts("v", values) + f"check {body}\n"


def all_src(values, threshold):
    """all(v > threshold for v in values) — the dual, an && chain."""
    body = " && ".join(f"v{i} > {threshold}" for i in range(len(values)))
    return facts("v", values) + f"check {body}\n"


def count_src(values, threshold, k):
    """count(v > threshold for v in values) >= k, as a threshold circuit.

    A[i][j] = "at least j of the first i hold", by the standard recurrence

        A[i][0] = true
        A[0][j] = false            (j > 0)
        A[i][j] = A[i-1][j] || (P_i && A[i-1][j-1])

    which is O(n*k) boolean nodes and needs no numeral anywhere. WPL has no
    let-binding, so the recurrence is written out; the TERM is a DAG, so the
    repeated subexpressions share one address rather than being copied.
    """
    n = len(values)
    if k <= 0 or k > n:
        # Degenerate thresholds collapse to a constant, and WPL then refuses the
        # source: a declared fact that the check does not read "looks like it
        # constrains the decision and does not". Section 3b asserts that refusal
        # rather than working around it — it is the language being right.
        return facts("v", values) + ("check true\n" if k <= 0 else "check false\n")

    def a(i, j):
        if j == 0:
            return "true"
        if i == 0:
            return "false"
        return f"({a(i-1, j)} || (v{i-1} > {threshold} && {a(i-1, j-1)}))"

    return facts("v", values) + f"check {a(n, k)}\n"


# --------------------------------------------------------------------- runs
def main():
    print("=" * 70)
    print("  WRT-011 model — bounded aggregation inside WPL as it stands")
    print("=" * 70)

    print("\n1. `in` already IS `any` over equality. Same list, both spellings:")
    f = 'fact country: string = "MX"\n'
    src_in = f + 'check country in ["CA", "US", "MX"]\n'
    right = f + ('check country == "CA" || (country == "US" || '
                 'country == "MX")\n')
    left = f + ('check (country == "CA" || country == "US") || '
                'country == "MX"\n')
    a, r, l = (pl.compile_source(x) for x in (src_in, right, left))
    chk(a.doc["term"] == r.doc["term"],
        "`x in [..]` compiles to EXACTLY the right-associated || chain",
        f"{a.doc['term'][:16]} vs {r.doc['term'][:16]}")
    chk(a.doc["term"] != l.doc["term"],
        "and not to the left-associated one — association is observable")
    chk(a.doc["atp"] == r.doc["atp"] == l.doc["atp"],
        f"all three cost the same ({a.doc['atp']} ATP, {a.nodes} nodes): "
        "association changes the term, not the price")

    print("\n2. any / all, verdict read from a real reduction:")
    for values, thr in (([1, 5, 9], 4), ([1, 2, 3], 4), ([5, 6, 7], 4)):
        want_any, want_all = any(v > thr for v in values), all(v > thr for v in values)
        got_any, atp_any, _ = reexecute(any_src(values, thr))
        got_all, atp_all, _ = reexecute(all_src(values, thr))
        chk(got_any == want_any, f"any({values} > {thr}) = {want_any}  [{atp_any} ATP]")
        chk(got_all == want_all, f"all({values} > {thr}) = {want_all}  [{atp_all} ATP]")

    print("\n3. count(P) >= k by threshold circuit — no numeral anywhere:")
    values, thr = [1, 5, 9, 2], 4             # two of four hold
    for k in range(1, len(values) + 1):
        want = sum(v > thr for v in values) >= k
        got, atp, nodes = reexecute(count_src(values, thr, k))
        chk(got == want,
            f"count({values} > {thr}) >= {k} = {str(want):5} "
            f"[{atp:5} ATP, {nodes} nodes]")

    print("\n3b. degenerate thresholds are a COMPILE-TIME refusal, not a "
          "constant:")
    for k, why in ((0, "always true"), (len(values) + 1, "always false")):
        try:
            pl.compile_source(count_src(values, thr, k))
            chk(False, f">= {k} ({why}) is refused", "compiled instead")
        except pl.PolicyError as e:
            chk("never used" in str(e),
                f">= {k} ({why}) is refused: the facts would not constrain "
                "the decision", str(e)[:70])

    print("\n4. exhaustive over every subset of a 4-element list, k = 1..4:")
    bad = 0
    for bits in itertools.product([0, 1], repeat=4):
        vals = [9 if b else 1 for b in bits]
        for k in range(1, 5):
            want = sum(bits) >= k
            got, _, _ = reexecute(count_src(vals, 4, k))
            if got != want:
                bad += 1
    chk(bad == 0, "64 threshold cases agree with Python", f"{bad} disagreed")

    print("\n5. THE ARGUMENT FOR A CONSTRUCT: the term shares, the source "
          "does not.")
    print("   The recurrence reuses A[i-1][j] twice, so the TERM is a DAG and "
          "the")
    print("   repeated subexpression has one address. Written out in SOURCE it "
          "is a")
    print("   tree, and WPL caps a check expression at "
          f"{pl.MAX_EXPR_NODES} parts.\n")
    print(f"    {'n':>3} {'k':>3} {'src chars':>10} {'ATP':>8} {'nodes':>7}  "
          "status")
    ceiling = None
    for n in (2, 3, 4, 5, 6, 7, 8):
        vals = [9 if i % 2 else 1 for i in range(n)]
        k = max(1, n // 2)
        src = count_src(vals, 4, k)
        body = src.split("check ", 1)[1]
        try:
            _, atp, nodes = reexecute(src)
            print(f"    {n:>3} {k:>3} {len(body):>10} {atp:>8} {nodes:>7}  ok")
        except pl.PolicyError as e:
            ceiling = ceiling or n
            why = "expression cap" if "parts" in str(e) else str(e)[:30]
            print(f"    {n:>3} {k:>3} {len(body):>10} {'—':>8} {'—':>7}  "
                  f"REFUSED ({why})")
    chk(ceiling is not None,
        f"hand-written thresholds stop compiling at n={ceiling}, well below any "
        "real list", "no ceiling found in the sampled range")
    chk(ceiling is not None and ceiling <= 8,
        "so this is not sugar: the semantics is reachable and the SOURCE is "
        "not writable by hand")

    print("\n6. the compile-time budget refuses what would be unaffordable:")
    try:
        pl.compile_source(count_src([9] * 24, 4, 12), max_atp=5000)
        chk(False, "an over-budget aggregate is refused at COMPILE time",
            "compiled instead")
    except pl.PolicyError as e:
        chk("atp" in str(e).lower() or "budget" in str(e).lower()
            or "node" in str(e).lower() or "parts" in str(e).lower(),
            "an over-budget aggregate is refused at COMPILE time", str(e)[:90])

    good = all(ok)
    print(f"\n{sum(ok)}/{len(ok)} checks")
    print("WRT-011 MODEL: ALL PASS" if good else "WRT-011 MODEL: FAILURES PRESENT")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
