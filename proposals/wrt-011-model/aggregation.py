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

WHAT REV 1 GOT WRONG, and why this file now compares two spellings.

Rev 1 wrote the threshold recurrence out naively, watched it hit WPL's 512-part
expression cap at n=8, and concluded "the SOURCE is not writable by hand". That
was a measurement of the generator, not of WPL. The review answered it with a
balanced divide-and-conquer spelling that compiles the same semantics at n=8 in
556 characters, with no new syntax and no compiler change (M1).

Rev 1 also had ONE check for three different caps whose condition accepted any
of four words, so a parser refusal counted as a budget refusal and the evaluator
was never reached at all (M2). §6 now instruments the real call count and gates
each cap separately.

Both were the same defect this repository keeps auditing in other people's work:
a conclusion wider than what its control established.

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
    """NAIVE strategy: write the recurrence out as a syntax tree.

        A[i][j] = A[i-1][j] || (P_i && A[i-1][j-1])

    A[i-1][j] appears twice, so as SOURCE this is a tree that doubles; the TERM
    is a DAG and shares it. This is one way to spell the threshold, and §5
    measures where THIS spelling stops compiling — not where WPL does.
    """
    n = len(values)
    if k <= 0 or k > n:
        return facts("v", values) + ("check true\n" if k <= 0 else "check false\n")

    def a(i, j):
        if j == 0:
            return "true"
        if i == 0:
            return "false"
        return f"({a(i-1, j)} || (v{i-1} > {threshold} && {a(i-1, j-1)}))"

    return facts("v", values) + f"check {a(n, k)}\n"


def count_src_balanced(values, threshold, k, _base=0):
    """BALANCED strategy, from the review of rev 1: split the list and combine.

        atleast(xs, k) = OR over j of (atleast(left, j) && atleast(right, k-j))

    with k=1 an OR chain and k=len an AND chain as bases. Same semantics, no
    new syntax, no compiler change — and dramatically smaller source, because
    the split shares work the naive expansion duplicates.

    Rev 1 measured only the naive spelling and concluded WPL could not express
    a hand-written threshold past n=7. That conclusion was about the generator,
    not the language. This function exists so the claim is comparative.
    """
    n = len(values)
    if k <= 0 or k > n:
        return facts("v", values) + ("check true\n" if k <= 0 else "check false\n")
    return facts("v", values) + f"check {_atleast(range(_base, _base + n), threshold, k)}\n"


def _atleast(idx, threshold, k):
    idx = list(idx)
    n = len(idx)
    if k <= 0:
        return "true"
    if k > n:
        return "false"
    if k == 1:
        return "(" + " || ".join(f"v{i} > {threshold}" for i in idx) + ")"
    if k == n:
        return "(" + " && ".join(f"v{i} > {threshold}" for i in idx) + ")"
    mid = n // 2
    left, right = idx[:mid], idx[mid:]
    parts = []
    for j in range(max(0, k - len(right)), min(k, len(left)) + 1):
        a = _atleast(left, threshold, j)
        b = _atleast(right, threshold, k - j)
        if a == "false" or b == "false":
            continue
        if a == "true":
            parts.append(b)
        elif b == "true":
            parts.append(a)
        else:
            parts.append(f"({a} && {b})")
    return "(" + " || ".join(parts) + ")" if parts else "false"


def ceiling(strategy, threshold=4, kmax=24):
    """Largest n this spelling still compiles at, with k = n//2."""
    last = None
    for n in range(2, kmax + 1):
        vals = [9 if i % 2 else 1 for i in range(n)]
        try:
            pl.compile_source(strategy(vals, threshold, max(1, n // 2)))
            last = n
        except pl.PolicyError:
            return last, n
    return last, None


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

    print("\n5. TWO SPELLINGS OF THE SAME THRESHOLD — rev 1 measured one.")
    print("   Rev 1 wrote the recurrence out naively, hit the 512-part cap at")
    print("   n=8, and concluded the SOURCE was not writable by hand. That was")
    print("   a fact about the generator, not about WPL: a balanced split")
    print("   compiles the same semantics far smaller, with no new syntax and")
    print("   no compiler change (review M1).\n")
    print(f"    {'n':>3} {'k':>3} {'naive chars':>12} {'bal chars':>10} "
          f"{'bal ATP':>8} {'bal nodes':>10}")
    for n in (4, 6, 7, 8, 10, 12):
        vals = [9 if i % 2 else 1 for i in range(n)]
        k = max(1, n // 2)
        nc = len(count_src(vals, 4, k).split("check ", 1)[1].rstrip())
        bsrc = count_src_balanced(vals, 4, k)
        bc = len(bsrc.split("check ", 1)[1].rstrip())
        try:
            _, atp, nodes = reexecute(bsrc)
            cell = f"{atp:>8} {nodes:>10}"
        except pl.PolicyError:
            cell = f"{'—':>8} {'refused':>10}"
        print(f"    {n:>3} {k:>3} {nc:>12} {bc:>10} {cell}")

    naive_last, naive_fail = ceiling(count_src)
    bal_last, bal_fail = ceiling(count_src_balanced)
    chk(naive_fail is not None and bal_last is not None
        and bal_last > naive_last,
        f"the balanced spelling reaches n={bal_last}, the naive one only "
        f"n={naive_last}",
        f"naive={naive_last}/{naive_fail} balanced={bal_last}/{bal_fail}")
    chk(True,
        f"MEASURED CEILING per spelling: naive refuses at n={naive_fail}, "
        f"balanced at n={bal_fail}. Neither is 'the WPL limit'; each is that "
        "spelling's limit")

    print("\n5b. the two spellings must agree, or the comparison means "
          "nothing:")
    bad = 0
    for bits in itertools.product([0, 1], repeat=5):
        vals = [9 if b else 1 for b in bits]
        for k in range(1, 6):
            want = sum(bits) >= k
            if reexecute(count_src(vals, 4, k))[0] != want:
                bad += 1
            if reexecute(count_src_balanced(vals, 4, k))[0] != want:
                bad += 1
    chk(bad == 0,
        "320 reductions: both spellings agree with Python on every subset of 5",
        f"{bad} disagreed")

    print("\n6. THREE CAPS, THREE CONTROLS. Rev 1 had one check that accepted")
    print("   any of four words, so a PARSER refusal counted as a budget")
    print("   refusal — and the evaluator was never reached (review M2).\n")

    # `policy_lang` binds its evaluator once, at import, as the module-level
    # `pl.sg`. Patching what `warrant.load_sigma()` returns therefore counts
    # nothing — which is how rev 1's instrumentation would have lied too.
    calls = {"n": 0}
    real_eval = pl.sg.eval_hash

    def counting(*a, **kw):
        calls["n"] += 1
        return real_eval(*a, **kw)

    def compile_counting(src, **kw):
        calls["n"] = 0
        pl.sg.eval_hash = counting
        try:
            return pl.compile_source(src, **kw), calls["n"]
        finally:
            pl.sg.eval_hash = real_eval

    # (a) EXPRESSION cap — a source too large to parse. Must not reach the
    #     evaluator, and must say `parts`, not `atp`.
    vals = [9 if i % 2 else 1 for i in range(12)]
    try:
        compile_counting(count_src(vals, 4, 6))
        chk(False, "(a) expression cap refuses an unparsable source", "compiled")
    except pl.PolicyError as e:
        chk("parts" in str(e) and "atp" not in str(e).lower(),
            "(a) expression cap refuses by NAME, and not as a budget failure",
            str(e)[:80])
        chk(calls["n"] == 0,
            "(a) and the evaluator was never called", f"{calls['n']} calls")

    # (b) NODE cap — a source that parses, refused for term size.
    small = count_src_balanced([9, 1, 9, 1], 4, 2)
    try:
        compile_counting(small, max_nodes=8)
        chk(False, "(b) node cap refuses an over-large term", "compiled")
    except pl.PolicyError as e:
        chk("node" in str(e).lower(), "(b) node cap refuses by NAME", str(e)[:80])

    # (c) ATP cap — a source that passes both earlier gates, refused on budget.
    try:
        compile_counting(small, max_atp=1)
        chk(False, "(c) ATP cap refuses an over-budget check", "compiled")
    except pl.PolicyError as e:
        chk("atp" in str(e).lower() or "budget" in str(e).lower(),
            "(c) ATP cap refuses by NAME", str(e)[:80])
        chk(calls["n"] > 0,
            "(c) and it got there THROUGH the evaluator, unlike (a)",
            f"{calls['n']} calls")

    # The same source compiles when each cap is given room — otherwise (b) and
    # (c) would pass for any reason at all.
    c, n_calls = compile_counting(small)
    chk(c.result is True and n_calls > 0,
        "positive control: the same source compiles when nothing is capped",
        f"result={c.result} calls={n_calls}")

    print("\n7. boundaries the model does not decide (review, open limits):")
    for name, src in (("any([])", "check \n"), ("all([])", "check \n")):
        try:
            pl.compile_source(src)
            chk(False, f"{name} is refused", "compiled")
        except pl.PolicyError as e:
            chk("expected an expression" in str(e),
                f"{name} is a SYNTAX error today — a future construct must "
                "choose False/True identities or a typed refusal", str(e)[:60])

    good = all(ok)
    print(f"\n{sum(ok)}/{len(ok)} checks")
    print("WRT-011 MODEL: ALL PASS" if good else "WRT-011 MODEL: FAILURES PRESENT")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
