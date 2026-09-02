#!/usr/bin/env python3
"""Tests for policy_lang — WPL v1, the readable front end for ski@v1 checks.

WHAT THIS HARNESS IS BUILT TO AVOID
-----------------------------------
Two defect shapes this stack has produced repeatedly, and which a compiler test
suite is unusually good at reproducing:

  * *a gate with the shape of a check and none of its substance.* Comparing the
    compiler's output against the compiler's own idea of the answer proves
    nothing. So the verdict every differential asserts on is read out of an
    ACTUAL REDUCTION — `warrant.run_ski_check`, off blobs on disk, the same
    code path a stranger's verifier runs — and never from `Compiled.result`.

  * *a check that supplies the input it is testing.* `compile_source` already
    refuses to emit a term that disagrees with `policy_lang`'s own interpreter,
    so asserting that agreement re-tests nothing. The expected verdict in the
    differential (section E) therefore comes from a program generated as a
    Python expression FIRST and rendered to WPL text SECOND: the expectation is
    produced by Python's own operators, and the lexer, parser, type checker and
    lowering all sit between it and the answer.

And because a harness that cannot fail is the same defect one level up,
section F mutates the compiler on purpose and FAILS IF THE MUTANT SURVIVES.

  A. refusals: every construct outside WPL is rejected, by name
  B. precedence: hand-written expectations, independent of the parser
  C. combinators: STEP/EQSTEP truth tables, reduced by the Σ-GLYPH oracle
  D. comparisons: exhaustive over a small range, verdict read from reduction
  E. differential: generated programs, Python's answer vs the re-run term
  F. negative controls: injected mis-compilations must be caught
  G. budget: cost is pinned, reported, and refused when too large
  G2. size: the inputs that crashed instead of refusing (found by probing)
  L. emission: the SERIALIZED blob is re-executed under its own pinned `atp`
     before it is written -- the term being right is not the same as the
     artifact being acceptable
  H. Air Canada: the README's check, rewritten, byte-for-byte
  I. reproducible compilation: same source -> same term hash
  J. integration: a warrant citing a WPL check verifies clean
  K. documentation: every command in docs/authoring-checks.md is executed

Run: python3 tests/policy_lang.py   (nonzero exit on any failure)
"""
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("SIGMA_GLYPH", None)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


pl = _load("policy_lang", "impl/policy_lang.py")
sg = _load("sigma_glyph_t", "impl/sigma_glyph_v05.py")   # the ski@v1 engine
W = _load("warrant_impl", "impl/warrant.py")
sp = _load("ski_policy", "impl/ski_policy.py")

ok = []
_TMP = []


def chk(cond, label, detail=""):
    ok.append(bool(cond))
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")


def new_store():
    d = tempfile.mkdtemp(prefix="wpl-test-")
    _TMP.append(d)
    s = W.Store(os.path.join(d, ".warrants"))
    s.init()
    return s


# The one function every differential in this file reads its answer from: it
# compiles, writes the blobs, and re-runs the stored check the way SPEC §6(7)
# says a verifier must. The boolean comes out of the result NodeHash, not out
# of anything the compiler asserted.
def reexecute(src, store=None, **kw):
    """-> (value_from_reduction, atp_spent, Compiled)."""
    store = store or new_store()
    c = pl.compile_source(src, store.put_blob, **kw)
    verdict, result_hash, spent = W.run_ski_check(store, c.blob)
    if verdict != "pass":
        raise AssertionError(f"re-execution did not reproduce `expect`: {verdict}")
    if result_hash == sg.K_H.hex():
        return True, spent, c
    if result_hash == sg.FALSE_H.hex():
        return False, spent, c
    raise AssertionError(f"reduced to a non-boolean node {result_hash[:12]}")


# ---------------------------------------------------------------- A. refusals
REFUSALS = [
    ("check a + b", "arithmetic"),
    ("fact x: int = 1\ncheck x <= 1 - 0", "arithmetic"),
    ("fact x: int = 1\ncheck x * 2 <= 4", "arithmetic"),
    ("fact x: int = 1\ncheck x <= 650.88", "floating point"),
    ("fact x: int = 1\ncheck size(x) <= 2", "function calls are not in WPL"),
    ("fact x: int = 1\ncheck x", "must be a bool"),
    ("fact x: int = 1\nfact y: int = 2\ncheck x <= 1", "never used"),
    ("fact x: int = 1\ncheck y <= 1", "unknown fact"),
    ("fact x: int = 1\ncheck X <= 1", "did you mean"),
    ('fact c: string = "CA"\ncheck c < "US"', "orders integers only"),
    ('fact x: int = 1\ncheck x == "a"', "cannot compare int with string"),
    ("fact x: int = 1\nfact x: int = 2\ncheck x <= 1", "declared twice"),
    ("fact x: bool = true\ncheck x && true ? x : x", "conditional operator"),
    ("fact x: bool = true\ncheck x & x", "`&` alone is not an operator"),
    ("fact x: int = 1\ncheck x < 2 < 3", "do not chain"),
    ("fact x: int = 1", "no `check` expression"),
    ("fact x: bool = true\ncheck x\ncheck x", "exactly one `check`"),
    ('fact s: string = "a\\x00b"', "unsupported string escape"),
    ('fact s: string = "' + "x" * 40 + '"\ncheck s == "a"', "UTF-8 bytes"),
    ("fact x: int = 9223372036854775808\ncheck x <= 1", "int64 range"),
    ("fact x: int = 1\ncheck x in []", "empty list"),
    ('fact x: int = 1\ncheck x in ["a"]', "`in` compares int"),
    ("fact x: bool = true\nfact y: int = 2\ncheck x && y", "applies to bools"),
    ("fact fact: int = 1\ncheck fact <= 1", "reserved word"),
    ("fact x: int = 1\ncheck x <= 1 && (x <= 2", "expected `)`"),
    ('fact x: string = "a\nb"', "unterminated string"),
    ("fact x: int = 1\ncheck x <= 1kg", "followed by a letter"),
    ("fact x: int = 1\ncheck {x} ", "maps are not in WPL"),
    ("fact x: int = 1\ncheck 'a' == 'a'", "double quotes"),
]


def test_refusals():
    for src, needle in REFUSALS:
        try:
            pl.compile_source(src)
            chk(False, f"refuses: {needle}", "compiled instead of refusing")
        except pl.PolicyError as e:
            chk(needle in str(e), f"refuses: {needle}", str(e)[:110])
        except Exception as e:                       # a crash is not a refusal
            chk(False, f"refuses: {needle}",
                f"{type(e).__name__} instead of PolicyError: {e}")
    # A NUL byte cannot be written as an escape, so reach it through the raw
    # character -- the padding-collision guard must still fire.
    try:
        pl.compile_source('fact s: string = "a\x00b"\ncheck s == "x"')
        chk(False, "refuses: NUL byte in a string", "compiled")
    except pl.PolicyError as e:
        chk("NUL byte" in str(e), "refuses: NUL byte in a string", str(e)[:90])


# ------------------------------------------------------------- B. precedence
# Hand-written from the language definition, NOT from the parser: `!` binds
# tighter than a comparison, which binds tighter than `&&`, which binds
# tighter than `||`. `formula()` fully parenthesises, so these expectations
# pin the tree the parser actually built.
PRECEDENCE = [
    ("a || b && c", "(a || (b && c))"),
    ("a && b || c", "((a && b) || c)"),
    ("!a && b", "(!a && b)"),
    ("!(a && b)", "!(a && b)"),
    ("a && b && c", "((a && b) && c)"),
    ("a || b || c", "((a || b) || c)"),
    ("(a || b) && c", "((a || b) && c)"),
    ("x <= 1 && a", "((x <= 1) && a)"),
    ("a || x <= 1 || b", "((a || (x <= 1)) || b)"),
    ("!a || !b && !c", "(!a || (!b && !c))"),
]


def test_precedence():
    def head(expr):     # declare exactly the facts used: WPL refuses spares
        decl = {"a": "bool", "b": "bool", "c": "bool", "x": "int"}
        used = set(re.findall(r"\b[abcx]\b", expr))
        return "".join(f"fact {n}: {t} = {'true' if t == 'bool' else '1'}\n"
                       for n, t in decl.items() if n in used)

    for expr, expected in PRECEDENCE:
        prog = pl.parse(head(expr) + "check " + expr)
        chk(prog.formula() == expected, f"precedence: {expr}",
            f"got {prog.formula()}")
    # Multi-line expressions are one expression, not two statements.
    prog = pl.parse(head("a b c") + "check a\n      && b\n      && c")
    chk(prog.formula() == "((a && b) && c)", "an expression may span lines",
        prog.formula())


# ------------------------------------------------------------ C. combinators
def test_combinators():
    """STEP and EQSTEP, exhaustively, reduced by the oracle -- not by argument.

    Everything ordering-related in this compiler rests on these two terms, so
    they are checked against all eight input triples by actually evaluating
    them, on a store, through Σ-GLYPH Book I."""
    st = sg.Store()

    def put_tree(t):
        if t[0] == "app":
            put_tree(t[1])
            put_tree(t[2])
            return st.put(sg.term_bytes(t))
        return sg.term_hash(t)

    def value(term):
        h = put_tree(term)
        r, _ = sg.eval_hash(h, 100000, st)
        rh = sg.term_hash(r).hex()
        return True if rh == sg.K_H.hex() else (
            False if rh == sg.FALSE_H.hex() else None)

    for x in (False, True):
        for y in (False, True):
            for acc in (False, True):
                xt = pl.TRUE if x else pl.FALSE
                yt = pl.TRUE if y else pl.FALSE
                at = pl.TRUE if acc else pl.FALSE
                got = value(pl._App(pl.STEP, xt, yt, at))
                want = acc if x == y else (y and not x)
                chk(got == want, f"STEP {int(x)} {int(y)} {int(acc)} = {want}",
                    f"got {got}")
                got = value(pl._App(pl.EQSTEP, xt, yt, at))
                want = acc if x == y else False
                chk(got == want, f"EQSTEP {int(x)} {int(y)} {int(acc)} = {want}",
                    f"got {got}")


# ------------------------------------------------------------ D. comparisons
def test_comparisons_exhaustive():
    """Every ordering and equality over a small range, plus the signed and
    string edges. The expected answer is Python's operator; the actual answer
    is the Church boolean the stored term reduces to."""
    store = new_store()
    bad = []
    for a in range(-4, 5):
        for b in range(-4, 5):
            for op, f in (("<", lambda p, q: p < q), ("<=", lambda p, q: p <= q),
                          (">", lambda p, q: p > q), (">=", lambda p, q: p >= q),
                          ("==", lambda p, q: p == q), ("!=", lambda p, q: p != q)):
                src = f"fact a: int = {a}\nfact b: int = {b}\ncheck a {op} b"
                got, _, _ = reexecute(src, store)
                if got != f(a, b):
                    bad.append(f"{a} {op} {b} -> {got}")
    chk(not bad, f"int comparisons: {6 * 81} cases over [-4,4]", "; ".join(bad[:4]))

    edges = [(-(2 ** 63), 2 ** 63 - 1, "<", True),
             (2 ** 63 - 1, 2 ** 63 - 1, "<=", True),
             (2 ** 63 - 1, -(2 ** 63), ">", True),
             (0, -1, ">", True), (-1, 0, ">=", False),
             (-(2 ** 63), -(2 ** 63), "==", True),
             (65088, 50000, "<=", False)]
    for a, b, op, want in edges:
        src = f"fact a: int = {a}\nfact b: int = {b}\ncheck a {op} b"
        got, _, _ = reexecute(src, store)
        chk(got == want, f"int64 edge: {a} {op} {b} == {want}", f"got {got}")

    strs = [("CA", "CA", True), ("CA", "US", False), ("a", "ab", False),
            ("", "", True), ("", "a", False), ("é", "é", True),
            ("é", "e", False), ("bereavement", "bereavement", True),
            ("gold", "platinum", False)]
    for a, b, want in strs:
        # WPL has no \u escape on purpose, so a literal carries raw UTF-8.
        src = (f"fact a: string = {json.dumps(a, ensure_ascii=False)}\n"
               f"fact b: string = {json.dumps(b, ensure_ascii=False)}\n"
               "check a == b")
        got, _, _ = reexecute(src, store)
        chk(got == want, f"string equality: {a!r} == {b!r} is {want}", f"got {got}")

    # A zero-padded encoding must not let a short string impersonate a long one.
    got, _, _ = reexecute('fact a: string = "A"\nfact b: string = "\\tA"\n'
                          'check a == b', store)
    chk(got is False, "padding cannot collide two different strings", str(got))


# ------------------------------------------------------------ E. differential
# A generated program is built as a Python expression tree first. `to_python`
# renders it for Python's own operators (fully parenthesised, so its meaning is
# not in question); `to_wpl` renders WPL text with the language's precedence
# and no redundant parentheses, so the parser has to rebuild the same tree.
# Nothing in policy_lang contributes to the expectation.
_P_OR, _P_AND, _P_CMP, _P_NOT = 1, 2, 3, 4


class Gen:
    def __init__(self, rng):
        self.rng = rng
        self.facts = {}

    def fact(self, kind):
        rng = self.rng
        if kind == "int":
            v = rng.choice([rng.randint(-8, 8), rng.randint(-70000, 70000)])
        elif kind == "string":
            v = "".join(rng.choice("abcXY") for _ in range(rng.randint(0, 4)))
        else:
            v = rng.choice([True, False])
        name = f"{kind[0]}{len(self.facts)}"
        self.facts[name] = (kind, v)
        return name

    def expr(self, depth):
        rng = self.rng
        pick = rng.random()
        if depth <= 0 or pick < 0.30:
            return self.atom()
        if pick < 0.50:
            return ("not", self.expr(depth - 1))
        if pick < 0.75:
            return ("and", self.expr(depth - 1), self.expr(depth - 1))
        return ("or", self.expr(depth - 1), self.expr(depth - 1))

    def atom(self):
        rng = self.rng
        r = rng.random()
        if r < 0.25:
            return ("factref", self.fact("bool"), "bool")
        if r < 0.55:
            op = rng.choice(["<", "<=", ">", ">=", "==", "!="])
            a = ("factref", self.fact("int"), "int")
            b = (("factref", self.fact("int"), "int") if rng.random() < 0.5
                 else ("lit", rng.randint(-8, 8), "int"))
            return ("cmp", op, a, b)
        if r < 0.8:
            op = rng.choice(["==", "!="])
            a = ("factref", self.fact("string"), "string")
            b = (("factref", self.fact("string"), "string") if rng.random() < 0.5
                 else ("lit", "".join(rng.choice("abcXY")
                                      for _ in range(rng.randint(0, 3))), "string"))
            return ("cmp", op, a, b)
        kind = rng.choice(["int", "string"])
        items = [rng.randint(-8, 8) if kind == "int" else
                 "".join(rng.choice("abcXY") for _ in range(rng.randint(0, 3)))
                 for _ in range(rng.randint(1, 3))]
        return ("in", ("factref", self.fact(kind), kind), items, kind)


def to_python(e):
    t = e[0]
    if t == "factref":
        return e[1]
    if t == "lit":
        return repr(e[1])
    if t == "not":
        return "(not " + to_python(e[1]) + ")"
    if t == "and":
        return "(" + to_python(e[1]) + " and " + to_python(e[2]) + ")"
    if t == "or":
        return "(" + to_python(e[1]) + " or " + to_python(e[2]) + ")"
    if t == "cmp":
        return "(" + to_python(e[2]) + " " + e[1] + " " + to_python(e[3]) + ")"
    if t == "in":
        return "(" + to_python(e[1]) + " in " + repr(e[2]) + ")"
    raise AssertionError(t)


def to_wpl(e, ctx=0):
    t = e[0]
    if t == "factref":
        return e[1]
    if t == "lit":
        return json.dumps(e[1]) if e[2] == "string" else str(e[1])
    if t == "not":
        return "!" + to_wpl(e[1], _P_NOT)
    if t in ("and", "or"):
        p = _P_AND if t == "and" else _P_OR
        s = (to_wpl(e[1], p) + (" && " if t == "and" else " || ")
             + to_wpl(e[2], p + 1))          # left-assoc: right side binds tighter
        return f"({s})" if ctx > p else s
    if t == "cmp":
        s = f"{to_wpl(e[2], _P_CMP)} {e[1]} {to_wpl(e[3], _P_CMP)}"
        return f"({s})" if ctx >= _P_CMP else s
    if t == "in":
        items = ", ".join(json.dumps(x) if e[3] == "string" else str(x)
                          for x in e[2])
        s = f"{to_wpl(e[1], _P_CMP)} in [{items}]"
        return f"({s})" if ctx >= _P_CMP else s
    raise AssertionError(t)


def _lit_wpl(kind, v):
    if kind == "bool":
        return "true" if v else "false"
    if kind == "string":
        return json.dumps(v)
    return str(v)


def test_differential(n=250, seed=20260731):
    """Generated programs: Python's verdict vs the re-run term's verdict."""
    rng = random.Random(seed)
    store = new_store()
    bad, trues, falses, widths = [], 0, 0, 0
    for i in range(n):
        g = Gen(rng)
        while True:
            tree = g.expr(rng.randint(0, 3))
            used = set(re.findall(r"\b[bis]\d+\b", to_python(tree)))
            if used:
                break
            g.facts.clear()
        # A generated tree may allocate a fact it then discards; WPL refuses
        # unused facts, so declare exactly the ones the expression mentions.
        head = "".join(f"fact {n}: {k} = {_lit_wpl(k, v)}\n"
                       for n, (k, v) in g.facts.items() if n in used)
        src = head + "check " + to_wpl(tree)
        env = {n: v for n, (k, v) in g.facts.items()}
        want = bool(eval(to_python(tree), {"__builtins__": {}}, env))  # noqa: S307
        try:
            got, spent, c = reexecute(src, store)
        except Exception as e:
            bad.append(f"[{i}] {type(e).__name__}: {e}\n{src}")
            continue
        widths = max(widths, c.atp)
        trues += want
        falses += not want
        if got != want:
            bad.append(f"[{i}] python={want} reduction={got}\n{src}")
    chk(not bad, f"differential: {n} generated programs re-executed",
        (bad[0] if bad else "")[:400])
    chk(trues >= n // 8 and falses >= n // 8,
        f"differential exercised both verdicts ({trues} true, {falses} false)",
        f"{trues}/{falses}")
    print(f"     (worst generated check cost {widths} ATP)")


# ------------------------------------------------------- F. negative controls
def test_negative_controls():
    """Mutate the compiler; a surviving mutant means the harness is decoration.

    F1 patches only the lowering: the compile-time round-trip against the
    oracle must catch it. F2 patches the lowering AND policy_lang's own
    interpreter in the same direction, so the round-trip is fooled -- and the
    differential in E, whose expectation comes from Python, must catch it."""
    src_le = "fact a: int = 3\nfact b: int = 5\ncheck a <= b"

    # F1a: `<=` compiled with the equality comparator.
    saved = pl.STEP
    try:
        pl.STEP = pl.EQSTEP
        try:
            pl.compile_source(src_le)
            chk(False, "F1a mutant caught: `<=` lowered as `==`", "SURVIVED")
        except pl.CompilerBug as e:
            chk("refusing to emit" in str(e),
                "F1a mutant caught: `<=` lowered as `==`", str(e)[:80])
    finally:
        pl.STEP = saved

    # F1b: the fold seed inverted (`<=` becomes `<`).
    saved_fold = pl._fold
    try:
        pl._fold = lambda comb, xs, ys, seed: saved_fold(
            comb, xs, ys, pl.FALSE if seed is pl.TRUE else pl.TRUE)
        try:
            pl.compile_source("fact a: int = 5\nfact b: int = 5\ncheck a <= b")
            chk(False, "F1b mutant caught: inverted fold seed", "SURVIVED")
        except pl.CompilerBug:
            chk(True, "F1b mutant caught: inverted fold seed")
    finally:
        pl._fold = saved_fold

    # F1c: `&&` lowered as `||`.
    saved_term = pl._Lowering.term

    def swapped(self, e):
        if e[0] == "and":
            return saved_term(self, ("or", e[1], e[2]))
        return saved_term(self, e)
    try:
        pl._Lowering.term = swapped
        try:
            pl.compile_source("fact a: bool = true\nfact b: bool = false\n"
                              "check a && b")
            chk(False, "F1c mutant caught: `&&` lowered as `||`", "SURVIVED")
        except pl.CompilerBug:
            chk(True, "F1c mutant caught: `&&` lowered as `||`")
    finally:
        pl._Lowering.term = saved_term

    # F1d: one bit of an operand flipped.
    saved_bits = pl._bits
    try:
        pl._bits = lambda v, w: saved_bits(v ^ 1, w)
        try:
            pl.compile_source("fact a: int = 4\nfact b: int = 5\ncheck a <= b")
            chk(False, "F1d mutant caught: operand bit flipped", "SURVIVED")
        except pl.CompilerBug:
            chk(True, "F1d mutant caught: operand bit flipped")
    finally:
        pl._bits = saved_bits

    # F2: lowering AND interpreter mutated together -- the built-in round-trip
    # cannot see it, so the differential has to.
    saved_ev, saved_step = pl._ev, pl.STEP

    def ev_eq(e, facts):
        if e[0] == "cmp" and e[1] == "<=":
            return saved_ev(("cmp", "==", e[2], e[3]), facts)
        return saved_ev(e, facts)
    try:
        pl._ev, pl.STEP = ev_eq, pl.EQSTEP
        c = pl.compile_source(src_le)               # no CompilerBug: consistent
        chk(c.result is False,
            "F2 setup: consistent mutant passes the built-in round-trip",
            f"result={c.result}")
        store = new_store()
        got, _, _ = reexecute(src_le, store)
        py = bool(eval("a <= b", {"__builtins__": {}}, {"a": 3, "b": 5}))
        chk(got != py, "F2 mutant caught by the Python-side differential",
            "SURVIVED: reduction agreed with Python anyway")
    finally:
        pl._ev, pl.STEP = saved_ev, saved_step

    # And with the mutants reverted, the same source must be right again.
    got, _, _ = reexecute(src_le)
    chk(got is True, "compiler restored after mutation", str(got))


# ---------------------------------------------------------------- G. budget
def test_budget():
    src = "fact a: int = 3\nfact b: int = 5\ncheck a <= b"
    store = new_store()
    before = len(os.listdir(str(store.blobs)))
    got, spent, c = reexecute(src, store)
    written = len(os.listdir(str(store.blobs))) - before - 1   # -1: the check doc
    chk(spent == c.doc["atp"], "pinned atp == atp actually spent on re-run",
        f"{spent} vs {c.doc['atp']}")
    chk(c.nodes == written,
        f"the reported node count is the blobs actually written ({written})",
        f"reported {c.nodes}, wrote {written}")

    # Refusal, not an over-budget check emitted for someone else's verifier.
    try:
        pl.compile_source(src, max_atp=100)
        chk(False, "refuses a check over the ATP budget", "compiled")
    except pl.PolicyError as e:
        chk("costs more than the 100 ATP" in str(e),
            "refuses a check over the ATP budget", str(e)[:100])
    try:
        pl.compile_source(src, max_nodes=5)
        chk(False, "refuses a check over the node budget", "compiled")
    except pl.PolicyError as e:
        chk("node limit" in str(e), "refuses a check over the node budget",
            str(e)[:100])
    try:
        pl.compile_source(src, max_depth=3)
        chk(False, "refuses a check deeper than the depth limit", "compiled")
    except pl.PolicyError as e:
        chk("nodes deep" in str(e), "refuses a check deeper than the depth limit",
            str(e)[:100])
    # The depth refusal guards something real: Σ-GLYPH's `max_node_depth` is a
    # local resource control, and a term over it FAULTS on the verifier rather
    # than returning a verdict. Reproduce that on a term shaped like a WPL
    # conjunction, so the refusal above is not decoration.
    deep = pl.TRUE
    for _ in range(2000):
        deep = pl._App(deep, pl.TRUE, pl.FALSE)
    blobs, root, depth = pl._walk(deep)
    st = sg.Store()
    for _h, b in blobs:
        st.put(b)
    try:
        sg.eval_hash(root, 10 ** 7, st,
                     limits=dict(max_node_depth=64,
                                 max_materialized_nodes=10 ** 6,
                                 max_store_fetches=10 ** 6))
        chk(False, "an over-deep term faults instead of answering", "returned")
    except sg.ResourceFault:
        chk(True, "an over-deep term faults instead of answering "
                  f"(depth {depth} vs max_node_depth 64)")

    # ...and the boundary is inclusive, so a check costing exactly the budget
    # is not refused.
    exact = pl.compile_source(src, max_atp=c.atp)
    chk(exact.atp == c.atp, "a check costing exactly the budget is allowed",
        f"{exact.atp} vs {c.atp}")

    # Headroom widens the pinned budget without changing what is spent.
    store = new_store()
    h = pl.compile_source(src, store.put_blob, atp_headroom=50)
    verdict, _, spent2 = W.run_ski_check(store, h.blob)
    chk(h.doc["atp"] == c.atp + 50 and verdict == "pass" and spent2 == c.atp,
        "headroom raises the pinned atp, not the spend",
        f"pinned={h.doc['atp']} spent={spent2}")

    # The cost report must track the real cost, not a constant.
    cheap = pl.compile_source("fact a: int = 1\nfact b: int = 0\ncheck a <= b")
    dear = pl.compile_source('fact a: string = "aaaaaaaaaaaaaaaa"\n'
                             'fact b: string = "aaaaaaaaaaaaaaaa"\n'
                             'check a == b')
    chk(dear.atp > 20 * cheap.atp, "reported cost scales with the work asked for",
        f"{cheap.atp} vs {dear.atp}")
    chk(dear.atp < W.SKI_REEXEC_MAX_ATP,
        "a 16-byte string equality stays inside the reference re-exec budget",
        str(dear.atp))


# ------------------------------------------------------------- L. emission
def _blob_count(store):
    return len(list(store.blobs.iterdir()))


def test_emission():
    """The compiler must not emit a check its own verifier rejects.

    Sections A-G all validate the TERM. This one validates the BLOB, because
    the two came apart: `--headroom` reached the `atp` field unchecked, and a
    wrong `atp` does not make a check malformed -- it makes the verifier run
    out of budget and answer `fail`. Correct term, wrong verdict.

    Reproduced by Codex, 2026-07-31, and re-run here before the fix:
      --headroom=-1          -> compiled atp=494, verifier `fail` (spent 492)
      --headroom=5000000000  -> compiled atp=5000000495, verifier
                                "atp must be a uint32"

    Every refusal below also asserts the store is untouched: a compiler that
    refuses AFTER writing has not refused."""
    src = "fact refund: int = 65088\nfact cap: int = 50000\ncheck refund <= cap"
    exact = pl.compile_source(src).atp

    # L1/L2 -- the two reported reproductions, as refusals.
    for headroom, want, label in (
            (-1, "must be >= 0", "L1 negative headroom is refused"),
            (5_000_000_000, "uint32",
             "L2 headroom past uint32 is refused")):
        store = new_store()
        before = _blob_count(store)
        try:
            pl.compile_source(src, store.put_blob, atp_headroom=headroom)
            chk(False, label, "EMITTED -- compiler accepted it")
        except pl.PolicyError as e:
            chk(want in str(e) and _blob_count(store) == before,
                label, f"{str(e)[:70]} / blobs {_blob_count(store)-before}")

    # L3 -- the ceilings, at the boundary rather than near it. warrant rejects
    # `atp` outside uint32 and refuses to re-execute past SKI_REEXEC_MAX_ATP,
    # so the last accepted pin is exactly that budget.
    ceiling = W.SKI_REEXEC_MAX_ATP
    at_ceiling = pl.compile_source(src, atp_headroom=ceiling - exact)
    chk(at_ceiling.atp == ceiling,
        "L3a a pin at exactly the re-execution budget is allowed",
        str(at_ceiling.atp))
    for pin, label in ((ceiling + 1, "L3b one ATP past the re-exec budget"),
                       (2 ** 32 - 1, "L3c the top of uint32"),
                       (2 ** 32, "L3d the first value outside uint32")):
        try:
            pl.compile_source(src, atp_headroom=pin - exact)
            chk(False, label + " is refused", f"EMITTED atp={pin}")
        except pl.PolicyError:
            chk(True, label + " is refused")

    # L4 -- THE ONE THAT MATTERS. The gate must read the bytes being written,
    # not the compiler's own variables. Tampering with `_canon` corrupts the
    # doc AFTER every term-level check has passed and at the exact point of
    # serialization, so only a gate that re-executes the serialized blob can
    # see it. Each mutant that SURVIVES is a check written to disk that the
    # verifier disagrees with.
    saved_canon = pl._canon

    def tamper(field, f):
        def _c(doc):
            return saved_canon({**doc, field: f(doc[field])})
        return _c

    mutants = [
        ("L4a atp silently lowered below the spend", "atp", lambda a: a - 1),
        ("L4b atp raised out of uint32", "atp", lambda a: 2 ** 32 + 7),
        ("L4c expect pointing at another node", "expect",
         lambda e: ("0" if e[0] != "0" else "1") + e[1:]),
    ]
    for label, field, f in mutants:
        store = new_store()
        before = _blob_count(store)
        pl._canon = tamper(field, f)
        try:
            c = pl.compile_source(src, store.put_blob)
        except (pl.PolicyError, pl.CompilerBug) as e:
            chk(_blob_count(store) == before, label + " -> refused",
                f"refused but wrote {_blob_count(store)-before} blobs")
            continue
        finally:
            pl._canon = saved_canon
        # Survived. Show precisely what the verifier makes of what was written.
        try:
            verdict, _rh, spent = W.run_ski_check(store, c.blob)
            detail = f"SURVIVED -> verifier says {verdict} (spent {spent})"
        except RuntimeError as e:
            detail = f"SURVIVED -> verifier says {e}"
        chk(False, label + " -> refused", detail)

    # L5 -- the compiler's acceptance boundary IS the verifier's. Not a
    # restatement of "uint32" here: the two are compared by running both.
    for pin in (exact, exact + 1, ceiling, ceiling + 1, 2 ** 32 - 1, 2 ** 32):
        try:
            emitted = pl.compile_source(src, atp_headroom=pin - exact).doc
            compiler_ok = True
        except pl.PolicyError:
            emitted, compiler_ok = {"ski": 1, "term": "0" * 64, "atp": pin,
                                    "expect": "0" * 64}, False
        verifier_ok = (W.validate_ski_blob(emitted) is None
                       and pin <= W.SKI_REEXEC_MAX_ATP)
        chk(compiler_ok == verifier_ok,
            f"L5 compiler and verifier agree about atp={pin}",
            f"compiler {compiler_ok} vs verifier {verifier_ok}")

    # L6 -- the low-level emitter (`ski_policy.compile_check`) has the same
    # `atp + headroom` line and now the same gate.
    store = new_store()
    before = _blob_count(store)
    expr = sp.And(sp.Fact("within_window", True), sp.Not(sp.Fact("retro", True)))
    try:
        sp.compile_check(expr, store.put_blob, atp_headroom=-1)
        chk(False, "L6 ski_policy refuses negative headroom too", "EMITTED")
    except ValueError as e:
        chk("must be >= 0" in str(e) and _blob_count(store) == before,
            "L6 ski_policy refuses negative headroom too", str(e)[:70])

    # ...and still emits a check the verifier reproduces.
    store = new_store()
    c = sp.compile_check(expr, store.put_blob, atp_headroom=25)
    verdict, _, spent = W.run_ski_check(store, c.blob)
    chk(verdict == "pass" and c.doc["atp"] == spent + 25,
        "L6b ski_policy headroom still widens the pin, not the spend",
        f"{verdict} pinned={c.doc['atp']} spent={spent}")


# ------------------------------------------------------------ H. Air Canada
AC_SOURCE_PATH = "demos/air-canada/policy.wpl"
# From demos/air-canada/README.md, which a reader is invited to reproduce:
#   warrant --store .warrants check b423b6a8... -> pass result=65cd957f... atp_spent=17
AC_CHECK = "b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f"
AC_RESULT = "65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098"
AC_ATP = 17


def test_air_canada():
    src = open(os.path.join(ROOT, AC_SOURCE_PATH), encoding="utf-8").read()
    store = new_store()
    got, spent, c = reexecute(src, store)
    chk(got is False, "air canada: the policy denies the retroactive claim",
        str(got))
    chk(c.blob == AC_CHECK, "air canada: same check blob as the README prints",
        f"{c.blob} != {AC_CHECK}")
    chk(c.doc["expect"] == AC_RESULT, "air canada: same result NodeHash",
        c.doc["expect"])
    chk(spent == AC_ATP and c.doc["atp"] == AC_ATP,
        f"air canada: same atp_spent={AC_ATP}", f"{spent}/{c.doc['atp']}")

    # ...and byte-for-byte what the hand-built ski_policy expression produced,
    # which is why the demo pack did not have to be re-signed.
    old = sp.compile_check(
        sp.And(sp.Fact("within_window", True), sp.Not(sp.Fact("retroactive", True))),
        new_store().put_blob)
    chk(old.doc == c.doc, "air canada: identical ski@v1 doc to the old helper",
        f"{old.doc} vs {c.doc}")

    # The demo pack on disk must be the one this source compiles to.
    pack = os.path.join(ROOT, "demos/air-canada/pack/manifest.json")
    man = json.load(open(pack, encoding="utf-8"))
    entry = man["ski_checks"][0]
    chk(entry["check"] == c.blob and entry["atp"] == c.doc["atp"]
        and entry["term"] == c.doc["term"],
        "air canada: the shipped pack cites exactly this compiled check",
        json.dumps(entry))


# ------------------------------------------------- I. reproducible compilation
def test_reproducible():
    src = open(os.path.join(ROOT, "examples/policies/3-two-inputs.wpl"),
               encoding="utf-8").read()
    a = pl.compile_source(src, new_store().put_blob)
    b = pl.compile_source(src, new_store().put_blob)
    chk(a.doc == b.doc and a.blob == b.blob,
        "same source bytes -> same term and same check hash")

    # Comments and layout are not part of the meaning...
    noisy = "# a different comment\n\n" + src.replace("\n\n", "\n\n\n")
    chk(pl.compile_source(noisy).doc["term"] == a.doc["term"],
        "comments and blank lines do not change the term")
    # ...but a fact value is.
    changed = src.replace("= -12", "= 12")
    chk(pl.compile_source(changed).doc["term"] != a.doc["term"],
        "changing a pinned fact changes the term")

    # Reproducing the compile is how a reader audits it, so the CLI must agree
    # with the library, in a separate process.
    out = subprocess.run([sys.executable, "impl/policy_lang.py", "compile",
                          "examples/policies/3-two-inputs.wpl", "--json"],
                         cwd=ROOT, capture_output=True, text=True)
    doc = json.loads(out.stdout)["doc"]
    chk(doc == a.doc, "the CLI reproduces the library's term", json.dumps(doc))


# ------------------------------------------------------------ J. integration
def test_integration():
    store = new_store()
    src = open(os.path.join(ROOT, "examples/policies/1-threshold.wpl"),
               encoding="utf-8").read()
    c = pl.compile_source(src, store.put_blob)
    source_blob = store.put_blob(src.encode("utf-8"))   # so it can be recompiled
    key = os.path.join(os.path.dirname(str(store.root)), "k.key")
    open(key, "w").write("cd" * 32 + "\n")
    subject = store.put_blob(b'{"action":"auto_refund","amount_cents":65088}')
    policy = store.put_blob(b"auto-refund limit: 50000 cents")

    class A:
        pass
    a = A()
    a.under, a.prior, a.transcript, a.relitigates = [policy], [], None, None
    a.evidence = [source_blob]
    a.reason = ["over the desk limit: " + c.program.formula()]
    a.check, a.runtime, a.verdict = c.blob, "ski@v1", "pass"
    a.actor, a.key, a.ts = "desk@demo", key, 1708300800
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        wid = W.file_warrant(store, "reject", subject, a, note="refund over limit")
    errs, warns = W.verify_store(store, quiet=True)
    chk(errs == 0, "a warrant citing a WPL check verifies with 0 errors",
        f"{errs} errors")
    chk(bool(wid), "warrant filed")

    # The source blob in `evidence` is what makes the compiler auditable:
    # fetch it, recompile, and the record's own check hash must come back.
    fetched = (store.blobs / source_blob).read_bytes().decode("utf-8")
    again = pl.compile_source(fetched, new_store().put_blob)
    chk(again.blob == c.blob,
        "recompiling the evidence blob reproduces the cited check", again.blob)

    # Tampering with the term must not still read as `pass`.
    doc = dict(c.doc)
    doc["expect"] = sg.K_H.hex()                 # claim it reduced to TRUE
    tampered = store.put_blob(pl._canon(doc))
    verdict, _, _ = W.run_ski_check(store, tampered)
    chk(verdict == "fail", "a check claiming the wrong result re-runs as fail",
        verdict)


# --------------------------------------------------------- K. documentation
DOC = "docs/authoring-checks.md"


def test_documentation():
    """Every claim the tutorial makes about output is executed here.

    A fenced block whose first line starts with `$ ` is a command and its
    expected output. A ```wpl block whose first line is `# <path>` must be that
    file, verbatim."""
    text = open(os.path.join(ROOT, DOC), encoding="utf-8").read()
    blocks = re.findall(r"```(\w*)\n(.*?)```", text, re.S)
    cmds = files = 0
    for lang, body in blocks:
        lines = body.rstrip("\n").split("\n")
        if lines[0].startswith("$ "):
            cmds += 1
            cmd = lines[0][2:]
            want = "\n".join(lines[1:]).rstrip()
            r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True,
                               text=True)
            got = (r.stdout + r.stderr).rstrip()
            chk(got == want, f"doc command reproduces its output: {cmd[:64]}",
                "got:\n" + got[:600] + "\nwant:\n" + want[:600])
        elif lang == "wpl" and lines[0].startswith(("# examples/", "# demos/")):
            files += 1
            path = lines[0][2:].strip()
            on_disk = open(os.path.join(ROOT, path), encoding="utf-8").read()
            chk(on_disk.rstrip("\n") == body.rstrip("\n"),
                f"doc quotes {path} verbatim", "the doc and the file differ")
    chk(cmds >= 6, f"the tutorial runs {cmds} commands", str(cmds))
    chk(files >= 4, f"the tutorial quotes {files} policy files verbatim",
        str(files))


# ---------------------------------------------- G2. size, found the hard way
def test_large_inputs():
    """Regression: three inputs that CRASHED rather than refused.

    All three were found by probing rather than by design, and each produced a
    Python traceback out of a compiler whose entire contract is "refuse what
    you cannot compile":

      * a 300-clause conjunction died of `RecursionError` inside
        `sigma_glyph.term_hash`, which re-hashes a whole subtree per call, so
        the node walk was quadratic AND recursive. The walk is now iterative
        and hashes bottom-up.
      * the same shape at 900 clauses overflowed the type checker and the
        interpreter, which walk the tree recursively -> MAX_EXPR_NODES.
      * 2000 nested parentheses overflowed the parser at six stack frames per
        level, long before the node budget noticed -> MAX_PAREN_DEPTH.

    A crash is not a refusal: it tells an author nothing and, in a build,
    looks like a broken tool rather than an unauthorable policy."""
    def clauses(n):
        return ("".join(f"fact b{i}: bool = true\n" for i in range(n))
                + "check " + " && ".join(f"b{i}" for i in range(n)))

    # 250 clauses is inside every limit and must still compile and re-run.
    got, spent, c = reexecute(clauses(250), max_nodes=100000)
    chk(got is True and spent == c.atp,
        f"a 250-clause conjunction compiles and re-runs ({c.nodes} nodes, "
        f"{c.atp} ATP)", f"{got}/{spent}")

    for n in (300, 900, 3000):
        try:
            pl.compile_source(clauses(n), max_nodes=100000)
            chk(False, f"{n} clauses is refused, not crashed", "compiled")
        except pl.PolicyError as e:
            chk("more than 512 parts" in str(e),
                f"{n} clauses is refused, not crashed", str(e)[:90])
        except Exception as e:
            chk(False, f"{n} clauses is refused, not crashed",
                f"{type(e).__name__}: {e}")

    for n in (200, 5000):
        src = "fact b0: bool = true\ncheck " + "(" * n + "b0" + ")" * n
        try:
            pl.compile_source(src)
            chk(False, f"{n} nested parens is refused, not crashed", "compiled")
        except pl.PolicyError as e:
            chk("nested parentheses" in str(e),
                f"{n} nested parens is refused, not crashed", str(e)[:90])
        except Exception as e:
            chk(False, f"{n} nested parens is refused, not crashed",
                type(e).__name__)

    # A large but legal membership test: still a refusal-free path, and the
    # cost report has to stay truthful at that size.
    big = ('fact c: string = "zz"\ncheck c in ['
           + ", ".join(f'"{chr(97 + i // 26)}{chr(97 + i % 26)}"'
                       for i in range(150)) + "]")
    got, spent, c = reexecute(big, max_nodes=100000)
    chk(got is False and spent == c.atp,
        f"a 150-element set membership re-runs ({c.atp} ATP, {c.nodes} nodes)",
        f"{got}/{spent} vs {c.atp}")


def main():
    try:
        test_refusals()
        test_precedence()
        test_combinators()
        test_comparisons_exhaustive()
        test_differential()
        test_negative_controls()
        test_budget()
        test_emission()
        test_large_inputs()
        test_air_canada()
        test_reproducible()
        test_integration()
        test_documentation()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    good = all(ok)
    print(f"\n{sum(ok)}/{len(ok)} checks")
    print("POLICY-LANG: ALL PASS" if good else "POLICY-LANG: FAILURES PRESENT")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
