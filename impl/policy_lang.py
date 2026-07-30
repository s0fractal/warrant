#!/usr/bin/env python3
"""policy_lang — WPL v1, a readable front end for `ski@v1` policy checks.

WHY THIS EXISTS
---------------
`ski@v1` is the only reason kind in this format that a stranger can safely
re-run (SPEC §3.1). Until now, authoring one meant hand-building Σ-GLYPH
combinator terms: `impl/ski_policy.py` gave you `And(Fact(...), Not(...))` over
booleans you had already decided yourself. No working engineer writes policy
that way, and a frontend nobody can use is a differentiator nobody evaluates.

WPL v1 is the smallest surface that covers real policy predicates:

    fact  refund_amount_cents : int    = 65088
    fact  max_auto_refund     : int    = 50000
    fact  retroactive         : bool   = true

    check refund_amount_cents <= max_auto_refund && !retroactive

It compiles to a closed Σ-GLYPH Book I term, which the verifier re-runs.

WHAT THE COMPILER IS AND IS NOT (read this before trusting it)
--------------------------------------------------------------
The compiler is NOT trusted code. A verifier never runs it: it re-runs the
*term*, per SPEC §3.1, and compares the result NodeHash to `expect`. That is
what makes a claimed verdict unfalsifiable-by-assertion.

What the verifier's re-run does NOT establish is that the term means what the
source text says. Four things make a mis-compilation detectable instead:

  1. **Every compile is checked against the oracle before it is emitted.**
     `compile_source` evaluates the term it just built on the Σ-GLYPH Book I
     oracle and compares the Church boolean it reduces to against an
     independent, plain-Python interpreter of the same source. They disagree ->
     `CompilerBug` is raised and nothing is emitted. Because a WPL check is a
     CLOSED term over facts pinned in the source, that one comparison covers
     the check's ENTIRE input space — there is no other input it could be run
     on. (`tests/policy_lang.py` widens this to randomly generated programs
     and a third, independently written evaluator.)

  2. **Compilation is reproducible.** Same source bytes -> same term hash. Pin
     the source as a blob and list it in the warrant's `evidence`; anyone can
     re-run the compiler and check they get the term the record cites. The
     compiler is then auditable rather than trusted.

  3. **The compiler evaluates nothing the verifier does not re-evaluate.** WPL
     has no arithmetic and no functions, so every operand is a literal or a
     pinned fact, and every operator — `&&`, `||`, `!`, `==`, `!=`, `<`, `<=`,
     `>`, `>=`, `in` — is lowered to term structure that the verifier reduces.
     The compiler never folds a comparison into its answer.

  4. **The bytes that get written are the bytes that were checked.** (1)–(3)
     validate the *term*; for a while nothing validated the *blob*. The check
     document also carries `atp` — the compiler's promise about what a verifier
     may spend — and a wrong `atp` does not make the check malformed, it makes
     the verifier run out of budget and answer `fail`. A wrong verdict, from a
     term that is entirely correct. So `_validate_emission` serializes the doc,
     decodes it back, puts it through `warrant.validate_ski_blob` — the
     verifier's own acceptance predicate, imported rather than restated — and
     reduces `term` under the PINNED `atp`, comparing against `expect`. Only
     then, and only those exact bytes, are stored. (Codex, 2026-07-31:
     `--headroom=-1` emitted a check its own verifier answered `fail` to.)

WHAT IT COSTS (SPEC §3.1 budget)
--------------------------------
`atp` bounds work AND peak memory (Σ-GLYPH's `size − 1 ≤ spent`). Every compile
reports the exact ATP the verifier will spend and the number of blobs the check
adds to the store. A program that would exceed `max_atp` (default 1,000,000 —
two orders of magnitude under the reference verifiers' 100,000,000 re-execution
budget) is REFUSED at compile time with the measured cost, never emitted as
something that will exhaust ATP at verification. Node count, term depth,
expression size, string length and parenthesis nesting are refused the same
way: a compiler whose contract is "refuse what you cannot compile" must not
answer with a traceback, and three of those limits exist because it did.

ENCODING (so the numbers above are checkable, not magic)
--------------------------------------------------------
Booleans are Church booleans, the encoding Book I is native to: TRUE = `K`,
FALSE = `K I`. `!p` is `p FALSE TRUE`, `p && q` is `p q FALSE`, `p || q` is
`p TRUE q` — plain applications, exactly as `ski_policy` did, so boolean-only
policies compile to byte-identical terms.

Ordering and equality are folds over a fixed-width bit vector, most significant
bit first, driven by two closed combinators:

    STEP   x y acc = x (y acc FALSE) (y TRUE acc)   -- x>y -> F, x<y -> T, else acc
    EQSTEP x y acc = x (y acc FALSE) (y FALSE acc)  -- x=y -> acc, else F

Both are stored once and shared by content address across every comparison in
every check in a store, so a comparison costs ~1 new blob per bit. Widths are
the minimum that distinguishes the operands, so `a <= 50000` is 17 bits, not 64.
Integers are encoded `v + 2**(W-1)` (two's complement with the sign bit flipped
— order-preserving, so one unsigned comparator serves signed values). Strings
are their UTF-8 bytes, left-padded to the longer operand, read big-endian; NUL
bytes are refused so padding cannot make two different strings equal.

Depends on the bundled Σ-GLYPH Book I oracle (`sigma_glyph`) + stdlib, and — at
emission time only — on `warrant`, for the acceptance predicate an emitted check
must satisfy. Both are modules of this same distribution. Parsing, evaluating
and reporting need neither.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

try:
    import sigma_glyph as sg
except ModuleNotFoundError:                                   # in-repo fallback
    _p = Path(__file__).resolve().parent / "sigma_glyph.py"
    _spec = importlib.util.spec_from_file_location("sigma_glyph", _p)
    sg = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(sg)

LANG_VERSION = "wpl@v1"

DEFAULT_MAX_ATP = 1_000_000
DEFAULT_MAX_NODES = 4096
# Well under Σ-GLYPH's default `max_node_depth` of 4096, which is a LOCAL
# resource control: a term over it faults on the verifier's machine instead of
# returning a verdict, and a verifier may configure it lower than the default.
DEFAULT_MAX_DEPTH = 1024
MAX_STRING_BYTES = 32
# The type checker, the interpreter and the lowering all walk the expression
# tree recursively, so an unbounded expression is an interpreter stack overflow
# waiting to happen — an ugly crash where a refusal belongs. A policy with more
# clauses than this wants to be several checks anyway.
MAX_EXPR_NODES = 512
# Parentheses are the one construct that nests the recursive-descent parser
# without spending the node budget fast enough to stop it: each level costs six
# stack frames, so 512 of them overflow the interpreter before MAX_EXPR_NODES
# fires. Nobody writes 64 nested parentheses; a term that does is hostile input.
MAX_PAREN_DEPTH = 64
INT64_MIN, INT64_MAX = -(2 ** 63), 2 ** 63 - 1


# ---------------------------------------------------------------- diagnostics
class PolicyError(Exception):
    """A refusal the author can act on: a syntax, type, or budget problem.

    Refusing loudly is the whole point. A construct WPL cannot compile within
    the ATP model is rejected here, at authoring time, rather than emitted as a
    check that dies of ATP exhaustion in somebody else's verifier."""

    def __init__(self, msg, line=None, col=None):
        self.msg, self.line, self.col = msg, line, col
        where = f" (line {line}, column {col})" if line else ""
        super().__init__(msg + where)


class CompilerBug(Exception):
    """The compiled term disagreed with the reference interpreter.

    This is never the author's fault and is never emitted as a check: the
    compiler refuses to hand a verifier a term it cannot itself reproduce."""


# --------------------------------------------------------------------- lexer
KEYWORDS = {"fact", "check", "in", "true", "false", "bool", "int", "string",
            "list"}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_INT = re.compile(r"[0-9]+")

# Constructs deliberately absent from WPL v1, each refused by name rather than
# by a generic "unexpected character" — an author who reaches for one deserves
# to be told why it is not there and what to do instead.
_REFUSED_CHARS = {
    "+": "arithmetic (`+`) is not in WPL v1",
    "*": "arithmetic (`*`) is not in WPL v1",
    "/": "arithmetic (`/`) is not in WPL v1",
    "%": "arithmetic (`%`) is not in WPL v1",
    "?": "the conditional operator `? :` is not in WPL v1 (write it with "
         "`&&`, `||` and `!`)",
    "'": "strings use double quotes",
    "{": "maps are not in WPL v1",
    "}": "maps are not in WPL v1",
}
_ARITH_HINT = ("WPL has no arithmetic on purpose: every operand must be a "
               "literal or a pinned fact, so the verifier re-executes every "
               "step of the decision instead of trusting a number the "
               "compiler worked out. Compute the value where the facts are "
               "gathered and pin the result as a fact.")


def tokenize(src):
    """-> [(kind, value, line, col)]; kinds: kw ident int str op eof."""
    toks, i, line, bol = [], 0, 1, 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "\n":
            line, i, bol = line + 1, i + 1, i + 1
            continue
        if ch in " \t\r":
            i += 1
            continue
        col = i - bol + 1
        if ch == "#":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == '"':
            j, out = i + 1, []
            while True:
                if j >= n or src[j] == "\n":
                    raise PolicyError("unterminated string literal", line, col)
                c = src[j]
                if c == '"':
                    j += 1
                    break
                if c == "\\":
                    if j + 1 >= n:
                        raise PolicyError("unterminated escape", line, col)
                    e = src[j + 1]
                    if e not in '"\\ntr':
                        raise PolicyError(
                            f"unsupported string escape \\{e} "
                            "(WPL v1 allows \\\" \\\\ \\n \\t \\r)", line, col)
                    out.append({'"': '"', "\\": "\\", "n": "\n", "t": "\t",
                                "r": "\r"}[e])
                    j += 2
                    continue
                out.append(c)
                j += 1
            toks.append(("str", "".join(out), line, col))
            i = j
            continue
        m = _INT.match(src, i)
        if m:
            end = m.end()
            if end < n and src[end] == "." and end + 1 < n and src[end + 1].isdigit():
                raise PolicyError(
                    "floating point is not in WPL v1 — a warrant body is "
                    "integers only (SPEC §2), and a float has no exact binary "
                    "policy meaning. Use integer units (cents, seconds, "
                    "basis points).", line, col)
            if end < n and (src[end].isalpha() or src[end] == "_"):
                raise PolicyError("a number may not be followed by a letter "
                                  "(no suffixes or units in WPL v1)", line, col)
            toks.append(("int", int(m.group()), line, col))
            i = end
            continue
        m = _IDENT.match(src, i)
        if m:
            word = m.group()
            toks.append((("kw" if word in KEYWORDS else "ident"), word, line, col))
            i = m.end()
            continue
        for op in ("&&", "||", "==", "!=", "<=", ">="):
            if src.startswith(op, i):
                toks.append(("op", op, line, col))
                i += 2
                break
        else:
            if ch in "&|":
                raise PolicyError(f"`{ch}` alone is not an operator; WPL uses "
                                  f"`{ch}{ch}`", line, col)
            if ch in _REFUSED_CHARS:
                hint = _ARITH_HINT if ch in "+-*/%" else ""
                raise PolicyError(_REFUSED_CHARS[ch] + (". " + hint if hint else ""),
                                  line, col)
            if ch in "()[],:=<>!-":
                toks.append(("op", ch, line, col))
                i += 1
                continue
            raise PolicyError(f"unexpected character {ch!r}", line, col)
    toks.append(("eof", None, line, i - bol + 1))
    return toks


# -------------------------------------------------------------------- parser
# AST:
#   ("bool", v) ("int", v) ("str", v) ("list", [e...]) ("fact", name)
#   ("not", e) ("and", a, b) ("or", a, b) ("cmp", op, a, b) ("in", e, list)
class Fact:
    __slots__ = ("name", "type", "value", "line")

    def __init__(self, name, type_, value, line):
        self.name, self.type, self.value, self.line = name, type_, value, line


class Program:
    """A parsed, type-checked WPL source: pinned facts + one check expression."""

    def __init__(self, facts, expr, source):
        self.facts = facts          # ordered dict name -> Fact
        self.expr = expr            # AST of the `check` expression
        self.source = source        # exact source text

    def formula(self):
        return unparse(self.expr)


class _P:
    def __init__(self, toks):
        self.t, self.i, self.n, self.paren = toks, 0, 0, 0

    def node(self):
        """Count one expression node, and refuse before the recursive descent
        that builds it can overflow an interpreter stack."""
        self.n += 1
        if self.n > MAX_EXPR_NODES:
            _, _, ln, co = self.peek()
            raise PolicyError(
                f"this expression has more than {MAX_EXPR_NODES} parts. Every "
                "later pass walks it recursively, so WPL caps it rather than "
                "crash; a policy this large should be several checks, each "
                "cited as its own reason.", ln, co)

    def peek(self, k=0):
        return self.t[min(self.i + k, len(self.t) - 1)]

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def at(self, kind, val=None):
        k, v, _, _ = self.peek()
        return k == kind and (val is None or v == val)

    def expect(self, kind, val=None, what=None):
        k, v, ln, co = self.peek()
        if k != kind or (val is not None and v != val):
            got = "end of file" if k == "eof" else repr(v)
            raise PolicyError(f"expected {what or val or kind}, got {got}", ln, co)
        return self.next()


def parse(src):
    """Parse WPL source into a type-checked Program (raises PolicyError)."""
    p = _P(tokenize(src))
    facts, expr = {}, None
    while not p.at("eof"):
        k, v, ln, co = p.peek()
        if k == "kw" and v == "fact":
            p.next()
            name = _parse_name(p)
            if name in facts:
                raise PolicyError(f"fact {name!r} is declared twice", ln, co)
            p.expect("op", ":", "`:` after the fact name")
            ftype = _parse_type(p)
            p.expect("op", "=", "`=` after the fact type")
            value = _parse_literal(p, ftype)
            facts[name] = Fact(name, ftype, value, ln)
        elif k == "kw" and v == "check":
            if expr is not None:
                raise PolicyError("a WPL source has exactly one `check` "
                                  "expression", ln, co)
            p.next()
            expr = _parse_expr(p)
            k2, v2, ln2, co2 = p.peek()
            if k2 == "op" and v2 == "-":
                raise PolicyError("arithmetic (`-`) is not in WPL v1. "
                                  + _ARITH_HINT, ln2, co2)
        else:
            got = "end of file" if k == "eof" else repr(v)
            raise PolicyError(f"expected `fact` or `check`, got {got}", ln, co)
    if expr is None:
        raise PolicyError("no `check` expression: a WPL source must end with "
                          "`check <expression>`")
    prog = Program(facts, expr, src)
    _typecheck(prog)
    return prog


def _parse_name(p):
    k, v, ln, co = p.peek()
    if k == "ident":
        p.next()
        return v
    if k == "kw":
        raise PolicyError(f"{v!r} is a reserved word and cannot be a fact name",
                          ln, co)
    raise PolicyError("expected a fact name", ln, co)


def _parse_type(p):
    k, v, ln, co = p.peek()
    if k != "kw" or v not in ("bool", "int", "string", "list"):
        raise PolicyError("expected a type: bool, int, string, list<int> or "
                          "list<string>", ln, co)
    p.next()
    if v != "list":
        return v
    p.expect("op", "<", "`<` after `list`")
    k2, v2, ln2, co2 = p.peek()
    if k2 != "kw" or v2 not in ("int", "string", "bool"):
        raise PolicyError("list element type must be int, string or bool",
                          ln2, co2)
    p.next()
    p.expect("op", ">", "`>` closing the list type")
    return f"list<{v2}>"


def _parse_literal(p, ftype):
    k, v, ln, co = p.peek()
    if ftype.startswith("list<"):
        elem = ftype[5:-1]
        p.expect("op", "[", "`[` starting a list value")
        items = []
        if not p.at("op", "]"):
            while True:
                items.append(_parse_literal(p, elem))
                if p.at("op", ","):
                    p.next()
                    continue
                break
        p.expect("op", "]", "`]` closing the list value")
        if not items:
            raise PolicyError("an empty list can never match; give it at "
                              "least one element", ln, co)
        return items
    if ftype == "bool":
        if k == "kw" and v in ("true", "false"):
            p.next()
            return v == "true"
        raise PolicyError("expected `true` or `false`", ln, co)
    if ftype == "int":
        sign = 1
        if k == "op" and v == "-":       # a negative literal, not subtraction
            p.next()
            sign = -1
            k, v, ln, co = p.peek()
        if k == "int":
            p.next()
            return _check_int(sign * v, ln, co)
        raise PolicyError("expected an integer literal", ln, co)
    if ftype == "string":
        if k == "str":
            p.next()
            return _check_str(v, ln, co)
        raise PolicyError("expected a quoted string", ln, co)
    raise PolicyError(f"unknown type {ftype}", ln, co)     # unreachable


def _check_int(v, ln, co):
    if not (INT64_MIN <= v <= INT64_MAX):
        raise PolicyError("integer out of int64 range (SPEC §2 bounds every "
                          "number in a warrant body to int64)", ln, co)
    return v


def _check_str(s, ln, co):
    b = s.encode("utf-8")
    if b"\x00" in b:
        raise PolicyError("a NUL byte in a string is refused: strings are "
                          "compared as zero-padded byte vectors, and a leading "
                          "NUL would make two different strings compare equal",
                          ln, co)
    if len(b) > MAX_STRING_BYTES:
        raise PolicyError(
            f"string is {len(b)} UTF-8 bytes; WPL v1 compares strings up to "
            f"{MAX_STRING_BYTES} bytes (a longer one costs more ATP than it is "
            "worth — pin a short tag or an identifier instead)", ln, co)
    return s


_CMP_OPS = ("==", "!=", "<", "<=", ">", ">=")


def _parse_expr(p):
    return _parse_or(p)


def _parse_or(p):
    left = _parse_and(p)
    while p.at("op", "||"):
        p.node()
        p.next()
        left = ("or", left, _parse_and(p))
    return left


def _parse_and(p):
    left = _parse_cmp(p)
    while p.at("op", "&&"):
        p.node()
        p.next()
        left = ("and", left, _parse_cmp(p))
    return left


def _parse_cmp(p):
    left = _parse_unary(p)
    k, v, ln, co = p.peek()
    if k == "op" and v == "-":
        raise PolicyError("arithmetic (`-`) is not in WPL v1. " + _ARITH_HINT,
                          ln, co)
    if k == "op" and v in _CMP_OPS:
        p.node()
        p.next()
        right = _parse_unary(p)
        k2, v2, ln2, co2 = p.peek()
        if k2 == "op" and v2 in _CMP_OPS:
            raise PolicyError("comparisons do not chain (`a < b < c`); write "
                              "`a < b && b < c`", ln2, co2)
        return ("cmp", v, left, right)
    if k == "kw" and v == "in":
        p.node()
        p.next()
        return ("in", left, _parse_unary(p))
    return left


def _parse_unary(p):
    if p.at("op", "!"):
        p.node()
        p.next()
        return ("not", _parse_unary(p))
    return _parse_primary(p)


def _parse_primary(p):
    p.node()
    k, v, ln, co = p.peek()
    if k == "op" and v == "(":
        p.paren += 1
        if p.paren > MAX_PAREN_DEPTH:
            raise PolicyError(
                f"more than {MAX_PAREN_DEPTH} nested parentheses. WPL refuses "
                "here rather than overflow its own parser.", ln, co)
        p.next()
        e = _parse_expr(p)
        p.expect("op", ")", "`)`")
        p.paren -= 1
        return e
    if k == "op" and v == "[":
        p.next()
        items = []
        if not p.at("op", "]"):
            while True:
                items.append(_parse_primary(p))
                if p.at("op", ","):
                    p.next()
                    continue
                break
        p.expect("op", "]", "`]`")
        if not items:
            raise PolicyError("an empty list can never match; give it at "
                              "least one element", ln, co)
        return ("list", items)
    if k == "int":
        p.next()
        return ("int", _check_int(v, ln, co))
    if k == "op" and v == "-" and p.peek(1)[0] == "int":
        # A negative literal, never subtraction: `_parse_primary` is only
        # reached where an expression must start, so no left operand exists.
        # `a - b` peeks `-` after a complete operand and is refused there.
        p.next()
        return ("int", _check_int(-p.next()[1], ln, co))
    if k == "str":
        p.next()
        return ("str", _check_str(v, ln, co))
    if k == "kw" and v in ("true", "false"):
        p.next()
        return ("bool", v == "true")
    if k == "ident":
        p.next()
        if p.at("op", "("):
            raise PolicyError(f"function calls are not in WPL v1 (`{v}(...)`). "
                              "The language is comparisons and boolean "
                              "connectives only, so that every step is "
                              "re-executable inside the ATP bound.", ln, co)
        return ("fact", v, ln, co)
    if k == "kw":
        raise PolicyError(f"`{v}` cannot start an expression", ln, co)
    got = "end of file" if k == "eof" else repr(v)
    raise PolicyError(f"expected an expression, got {got}", ln, co)


# --------------------------------------------------------------- type checker
def _typecheck(prog):
    used = set()
    t = _type_of(prog.expr, prog.facts, used)
    if t != "bool":
        raise PolicyError(f"the `check` expression must be a bool, not {t}")
    unused = [n for n in prog.facts if n not in used]
    if unused:
        raise PolicyError(
            "fact(s) declared but never used in the check: "
            + ", ".join(sorted(unused))
            + " — an unused fact looks like it constrains the decision and "
              "does not, so WPL refuses it rather than pin a lie")


def _type_of(e, facts, used):
    tag = e[0]
    if tag == "bool":
        return "bool"
    if tag == "int":
        return "int"
    if tag == "str":
        return "string"
    if tag == "fact":
        name, ln, co = e[1], e[2], e[3]
        if name not in facts:
            near = [n for n in facts if n.lower() == name.lower()]
            hint = f" (did you mean {near[0]!r}?)" if near else ""
            raise PolicyError(f"unknown fact {name!r}{hint} — declare it with "
                              f"`fact {name}: <type> = <value>`", ln, co)
        used.add(name)
        return facts[name].type
    if tag == "list":
        ts = {_type_of(x, facts, used) for x in e[1]}
        if len(ts) != 1:
            raise PolicyError("a list literal must be all one type, got "
                              + ", ".join(sorted(ts)))
        return f"list<{ts.pop()}>"
    if tag == "not":
        if _type_of(e[1], facts, used) != "bool":
            raise PolicyError("`!` applies to a bool")
        return "bool"
    if tag in ("and", "or"):
        for side in (e[1], e[2]):
            if _type_of(side, facts, used) != "bool":
                raise PolicyError(f"`{'&&' if tag == 'and' else '||'}` applies "
                                  "to bools; compare a value first, e.g. "
                                  "`amount <= 100`")
        return "bool"
    if tag == "cmp":
        op, lt, rt = e[1], _type_of(e[2], facts, used), _type_of(e[3], facts, used)
        if lt != rt:
            raise PolicyError(f"cannot compare {lt} with {rt} — WPL has no "
                              "implicit conversions")
        if lt.startswith("list<"):
            raise PolicyError("lists compare only with `in`")
        if op in ("<", "<=", ">", ">=") and lt != "int":
            raise PolicyError(f"`{op}` orders integers only; {lt} supports "
                              "`==`, `!=` and `in`")
        return "bool"
    if tag == "in":
        lt = _type_of(e[1], facts, used)
        rt = _type_of(e[2], facts, used)
        if not rt.startswith("list<"):
            raise PolicyError("the right side of `in` must be a list, e.g. "
                              '`country in ["CA", "US"]`')
        if rt[5:-1] != lt:
            raise PolicyError(f"`in` compares {lt} against a {rt}")
        return "bool"
    raise PolicyError(f"internal: unknown node {tag!r}")


# -------------------------------------------------- reference interpreter (1)
def evaluate(prog):
    """Plain-Python meaning of the source. The oracle must agree with this."""
    return _ev(prog.expr, prog.facts)


def _ev(e, facts):
    tag = e[0]
    if tag in ("bool", "int", "str"):
        return e[1]
    if tag == "fact":
        return facts[e[1]].value
    if tag == "list":
        return [_ev(x, facts) for x in e[1]]
    if tag == "not":
        return not _ev(e[1], facts)
    if tag == "and":
        return bool(_ev(e[1], facts)) and bool(_ev(e[2], facts))
    if tag == "or":
        return bool(_ev(e[1], facts)) or bool(_ev(e[2], facts))
    if tag == "cmp":
        a, b = _ev(e[2], facts), _ev(e[3], facts)
        return {"==": lambda: a == b, "!=": lambda: a != b,
                "<": lambda: a < b, "<=": lambda: a <= b,
                ">": lambda: a > b, ">=": lambda: a >= b}[e[1]]()
    if tag == "in":
        return _ev(e[1], facts) in _ev(e[2], facts)
    raise PolicyError(f"internal: unknown node {tag!r}")


def unparse(e):
    tag = e[0]
    if tag == "bool":
        return "true" if e[1] else "false"
    if tag == "int":
        return str(e[1])
    if tag == "str":
        return json.dumps(e[1], ensure_ascii=False)
    if tag == "fact":
        return e[1]
    if tag == "list":
        return "[" + ", ".join(unparse(x) for x in e[1]) + "]"
    if tag == "not":
        return "!" + unparse(e[1])
    if tag == "and":
        return f"({unparse(e[1])} && {unparse(e[2])})"
    if tag == "or":
        return f"({unparse(e[1])} || {unparse(e[2])})"
    if tag == "cmp":
        return f"({unparse(e[2])} {e[1]} {unparse(e[3])})"
    if tag == "in":
        return f"({unparse(e[1])} in {unparse(e[2])})"
    raise PolicyError(f"internal: unknown node {tag!r}")


# ------------------------------------------------- lowering to Σ-GLYPH terms
TRUE = sg.KG                      # K            (genesis, intrinsic)
FALSE = ("app", sg.KG, sg.IG)     # K I          (one stored node)


def _App(f, *args):
    for a in args:
        f = ("app", f, a)
    return f


# --- bracket abstraction, local to this module ------------------------------
# `sigma_glyph.c1` is the canonical Profile C1 compiler and is left untouched
# (it is a vendored oracle). This is the same algorithm plus the two standard
# SKI contractions, which halve the combinator and its ATP cost:
#     S (K M) I     -> M            S (K M) (K N) -> K (M N)
# Correctness is not asserted here: `STEP`/`EQSTEP` are checked exhaustively
# against the oracle over all eight input triples in tests/policy_lang.py, and
# every compile re-checks its whole term against the reference interpreter.
def _fv(t):
    k = t[0]
    if k == "var":
        return {t[1]}
    if k == "lam":
        return _fv(t[2]) - {t[1]}
    if k in ("lapp", "app"):
        return _fv(t[1]) | _fv(t[2])
    return set()


def _compile_lambda(t):
    k = t[0]
    if k == "var":
        return t
    if k == "lapp":
        return ("app", _compile_lambda(t[1]), _compile_lambda(t[2]))
    if k == "lam":
        return _abstract(t[1], _compile_lambda(t[2]))
    return t


def _abstract(x, m):
    if m == ("var", x):
        return sg.IG
    if x not in _fv(m):
        return ("app", sg.KG, m)
    if m[0] == "app":
        l, r = _abstract(x, m[1]), _abstract(x, m[2])
        if l[0] == "app" and l[1] == sg.KG and r == sg.IG:
            return l[2]                                   # S (K M) I     -> M
        if l[0] == "app" and l[1] == sg.KG and r[0] == "app" and r[1] == sg.KG:
            return ("app", sg.KG, ("app", l[2], r[2]))    # S(KM)(KN) -> K(MN)
        return ("app", ("app", sg.SG, l), r)
    raise CompilerBug("free variable escapes abstraction")


def _lam(v, b):
    return ("lam", v, b)


def _var(v):
    return ("var", v)


def _lapp(f, *args):
    for a in args:
        f = ("lapp", f, a)
    return f


# STEP x y acc : x>y -> FALSE, x<y -> TRUE, x=y -> acc   (unsigned, MSB first)
STEP = _compile_lambda(_lam("x", _lam("y", _lam("a", _lapp(
    _var("x"),
    _lapp(_var("y"), _var("a"), FALSE),
    _lapp(_var("y"), TRUE, _var("a")))))))

# EQSTEP x y acc : x=y -> acc, else FALSE
EQSTEP = _compile_lambda(_lam("x", _lam("y", _lam("a", _lapp(
    _var("x"),
    _lapp(_var("y"), _var("a"), FALSE),
    _lapp(_var("y"), FALSE, _var("a")))))))


def _bits(value, width):
    """MSB-first Church-boolean leaves for an unsigned `width`-bit value."""
    if not 0 <= value < (1 << width):
        raise CompilerBug(f"value {value} does not fit {width} bits")
    return [TRUE if (value >> (width - 1 - i)) & 1 else FALSE
            for i in range(width)]


def _encode_pair(a, b, kind):
    """(bits_a, bits_b, width) for two same-typed operand values."""
    if kind == "bool":
        return _bits(int(a), 1), _bits(int(b), 1), 1
    if kind == "int":
        width = max(_int_width(a), _int_width(b))
        off = 1 << (width - 1)
        return _bits(a + off, width), _bits(b + off, width), width
    if kind == "string":
        ba, bb = a.encode("utf-8"), b.encode("utf-8")
        nbytes = max(len(ba), len(bb), 1)
        width = 8 * nbytes
        return (_bits(int.from_bytes(ba.rjust(nbytes, b"\x00"), "big"), width),
                _bits(int.from_bytes(bb.rjust(nbytes, b"\x00"), "big"), width),
                width)
    raise CompilerBug(f"no encoding for {kind}")


def _int_width(v):
    """Smallest w with -2**(w-1) <= v <= 2**(w-1) - 1."""
    return (v.bit_length() + 1) if v >= 0 else ((-v - 1).bit_length() + 1)


def _fold(comb, xs, ys, seed):
    acc = seed
    for i in range(len(xs) - 1, -1, -1):
        acc = _App(comb, xs[i], ys[i], acc)
    return acc


class _Lowering:
    def __init__(self, facts):
        self.facts = facts
        self.comparisons = []       # (formula, width) for the cost report

    def term(self, e):
        tag = e[0]
        if tag == "bool":
            return TRUE if e[1] else FALSE
        if tag == "fact":
            f = self.facts[e[1]]
            if f.type != "bool":
                raise CompilerBug("non-bool fact in boolean position")
            return TRUE if f.value else FALSE
        if tag == "not":
            return _App(self.term(e[1]), FALSE, TRUE)
        if tag == "and":
            return _App(self.term(e[1]), self.term(e[2]), FALSE)
        if tag == "or":
            return _App(self.term(e[1]), TRUE, self.term(e[2]))
        if tag == "cmp":
            return self.compare(e[1], e[2], e[3])
        if tag == "in":
            items = e[2][1] if e[2][0] == "list" else \
                [("__val", v) for v in _ev(e[2], self.facts)]
            eqs = [self.compare("==", e[1], item) for item in items]
            out = eqs[-1]
            for one in reversed(eqs[:-1]):      # p || (q || (...)) — lazy: a
                out = _App(one, TRUE, out)      # later member is never forced
            return out                          # once an earlier one matches
        raise CompilerBug(f"cannot lower {tag!r}")

    def compare(self, op, lhs, rhs):
        a, b = self._value(lhs), self._value(rhs)
        kind = ("bool" if isinstance(a, bool) else
                "int" if isinstance(a, int) else "string")
        shown = f"{_show(lhs)} {op} {_show(rhs)}"
        if op in (">", ">="):                 # one comparator, operands swapped
            a, b = b, a
            op = "<" if op == ">" else "<="
        xs, ys, width = _encode_pair(a, b, kind)
        self.comparisons.append((shown, width))
        if op in ("<", "<="):
            return _fold(STEP, xs, ys, TRUE if op == "<=" else FALSE)
        eq = _fold(EQSTEP, xs, ys, TRUE)
        return eq if op == "==" else _App(eq, FALSE, TRUE)

    def _value(self, e):
        if e[0] == "__val":
            return e[1]
        return _ev(e, self.facts)


def _show(e):
    return unparse(e) if e[0] != "__val" else json.dumps(e[1])


# ------------------------------------------------------------------ compiler
class Compiled:
    """A compiled WPL check: the `ski@v1` blob plus everything an author or a
    reviewer needs to see what it will cost and what it means."""

    def __init__(self, program, doc, result, blob, nodes, comparisons,
                 max_atp):
        self.program = program
        self.doc = doc              # {"ski":1,"term":..,"atp":..,"expect":..}
        self.result = result        # bool: what the check expression says
        self.blob = blob            # hex hash of the stored check doc
        self.nodes = nodes          # blobs this check adds to a store
        self.comparisons = comparisons
        self.max_atp = max_atp

    @property
    def atp(self):
        return self.doc["atp"]

    @property
    def term(self):
        return self.doc["term"]

    def reason(self, verdict="pass"):
        """A `because` entry citing this check. `verdict` is what re-execution
        reproduces (`pass`), NOT the policy answer — see `result`."""
        if self.blob is None:
            raise PolicyError("this check was compiled without a store, so "
                              "there is no blob to cite; pass `put` to "
                              "compile_source/compile_file")
        return {"kind": "check", "check": self.blob, "runtime": "ski@v1",
                "verdict": verdict}

    def report(self, name=None):
        p = self.program
        lines = [f"language  {LANG_VERSION}"]
        if name:
            lines.insert(0, f"policy    {name}")
        lines.append(f"formula   {p.formula()}")
        first = True
        for f in p.facts.values():
            lines.append(("facts     " if first else "          ")
                         + f"{f.name}: {f.type} = {_lit(f.value)}")
            first = False
        if first:
            lines.append("facts     (none)")
        lines.append(f"result    {'true' if self.result else 'false'}")
        lines.append(f"term      {self.doc['term']}")
        lines.append(f"expect    {self.doc['expect']}  "
                     f"({'Church TRUE' if self.result else 'Church FALSE'})")
        lines.append(f"atp       {self.doc['atp']}  (budget {self.max_atp})")
        lines.append(f"nodes     {self.nodes}")
        for formula, width in self.comparisons:
            lines.append(f"          compare {formula}  ({width} bits)")
        lines.append("check     " + (self.blob if self.blob else
                                     "(not stored — pass --store to write it)"))
        return "\n".join(lines)

    def to_json(self):
        return {"language": LANG_VERSION, "formula": self.program.formula(),
                "facts": {n: f.value for n, f in self.program.facts.items()},
                "result": self.result, "check": self.blob, "doc": self.doc,
                "nodes": self.nodes,
                "comparisons": [{"formula": f, "bits": w}
                                for f, w in self.comparisons]}


def _lit(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(_lit(x) for x in v) + "]"
    return json.dumps(v, ensure_ascii=False)


def _canon(doc):
    # Byte-identical to warrant's JCS canonicalization for these ASCII bodies.
    return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


_VERIFIER = None


def _verifier():
    """The verifier module — imported, never restated.

    `warrant.validate_ski_blob` IS the boundary an emitted check must clear,
    and `warrant.SKI_REEXEC_MAX_ATP` IS the budget it will be re-run under. A
    second copy of "atp is a uint32" living here would be free to drift out of
    agreement with the code that does the rejecting — which is the exact
    failure this function exists to prevent. Both modules ship in one
    distribution (`py-modules` in pyproject.toml).

    THE FILE NEXT TO THIS ONE WINS, and that ordering is the point rather than
    a detail: `import warrant` resolves against sys.path, which during
    development is an older *installed* release. Validating an artifact against
    a verifier that is not the one shipped beside the compiler certifies
    nothing about the pair a user actually gets. (Caught by the test harness,
    which had a pip-installed copy on sys.path.)

    A missing verifier is a hard failure, not a skipped check: a compiler whose
    contract is "refuse what you cannot compile" cannot certify an artifact
    against a contract it is unable to read."""
    global _VERIFIER
    if _VERIFIER is not None:
        return _VERIFIER
    p = Path(__file__).resolve().parent / "warrant.py"
    if p.is_file():
        spec = importlib.util.spec_from_file_location("warrant_verifier", p)
        w = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(w)
    else:
        try:
            import warrant as w
        except ModuleNotFoundError:
            raise CompilerBug(
                "cannot emit a check: the verifier module (warrant) is neither "
                "beside this file nor importable, so the artifact cannot be "
                "validated against the rules that will judge it") from None
    _VERIFIER = w
    return w


def _validate_emission(doc, priv, exact_atp):
    """Re-run the SERIALIZED check, under the PINNED atp, before writing a byte.

    (4) of the module docstring. The three guarantees above all concern the
    *term*: it is walked, reduced and compared against two independent
    interpreters. None of them looked at the `atp` field of the blob, which is
    the compiler's own promise about what the verifier is allowed to spend —
    so a bad `atp` produced a check that reduced correctly in the compiler and
    reported `fail` in the verifier. (Reproduced 2026-07-31: `--headroom=-1`
    pinned 494 against a 495 ATP spend; the verifier answered `fail`, not
    "malformed".)

    So this re-decodes the canonical bytes and works only from what came back:
    the fields the verifier will read, checked by `validate_ski_blob`, then an
    actual reduction of `term` under `atp` compared against `expect`. Nothing
    the compiler computed is consulted; `exact_atp` is carried in for the error
    message alone. Returns the validated bytes, which are the bytes the caller
    must store — revalidating a doc and then serializing it again would be the
    same gap one level down.
    """
    w = _verifier()
    raw = _canon(doc)
    emitted = json.loads(raw.decode("utf-8"))

    err = w.validate_ski_blob(emitted)
    if err:
        raise PolicyError(
            f"refusing to emit a check the verifier would reject: {err}. "
            f"Pinned atp {doc['atp']} = {exact_atp} spent + "
            f"{doc['atp'] - exact_atp} headroom.")
    if emitted["atp"] > w.SKI_REEXEC_MAX_ATP:
        raise PolicyError(
            f"the pinned atp ({emitted['atp']}) is over the "
            f"{w.SKI_REEXEC_MAX_ATP} ATP a reference verifier will re-execute "
            "(SPEC §3.1), which reports the check as unverified rather than "
            "returning a verdict. Lower --headroom.")

    r, spent = sg.eval_hash(bytes.fromhex(emitted["term"]), emitted["atp"], priv)
    if r == ("dis", sg.R_ATP):
        raise PolicyError(
            f"the pinned atp ({emitted['atp']}) is below the {exact_atp} ATP "
            "this check spends, so a verifier re-running it would exhaust the "
            "budget and report `fail` — a wrong verdict rather than an error. "
            "Refusing to emit it.")
    rh = sg.term_hash(r).hex()
    if rh != emitted["expect"]:
        raise CompilerBug(
            f"the serialized check does not reproduce its own `expect`: "
            f"re-running term under atp={emitted['atp']} gives {rh[:12]}, the "
            f"blob pins {emitted['expect'][:12]} ({spent} ATP spent)")
    return raw


def _walk(t):
    """-> ([(hash, bytes)] children-first and deduplicated, root_hash, depth).

    Iterative and memoised on purpose. `sigma_glyph.term_hash` re-hashes a
    whole subtree on every call, so the obvious recursive version is quadratic
    AND recurses once per level of the term — a 300-clause policy died of
    `RecursionError` inside the hash function before any budget check could
    refuse it. Hashes are therefore built bottom-up from child hashes, and the
    traversal uses an explicit stack.

    Depth is returned because Σ-GLYPH's `max_node_depth` is a LOCAL resource
    control: breaching it raises a ResourceFault on the verifier's machine
    rather than returning a canonical outcome, and a fault is neither a pass
    nor a fail."""
    hashes, depths, blobs, seen = {}, {}, [], set()
    stack = [(t, False)]
    while stack:
        u, expanded = stack.pop()
        if id(u) in hashes:
            continue
        if u[0] != "app":
            hashes[id(u)], depths[id(u)] = sg.term_hash(u), 1
            continue
        if not expanded:
            stack.append((u, True))
            stack.append((u[2], False))
            stack.append((u[1], False))
            continue
        b = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT,
                   left=hashes[id(u[1])], right=hashes[id(u[2])])
        h = sg.node_hash(b)
        hashes[id(u)] = h
        depths[id(u)] = 1 + max(depths[id(u[1])], depths[id(u[2])])
        if h not in seen:
            seen.add(h)
            blobs.append((h, b))
    return blobs, hashes[id(t)], depths[id(t)]


def compile_source(src, put=None, *, name=None, atp_headroom=0,
                   max_atp=DEFAULT_MAX_ATP, max_nodes=DEFAULT_MAX_NODES,
                   max_depth=DEFAULT_MAX_DEPTH):
    """Compile WPL source into a stored `ski@v1` check.

    `put(bytes) -> hex_hash` stores a blob at its SHA-256 (warrant's
    `Store.put_blob` fits exactly); omit it to compile without writing
    anything. Raises `PolicyError` for anything the author must fix —
    including a check that would cost more than `max_atp` — and `CompilerBug`
    if the emitted term disagrees with the reference interpreter."""
    if isinstance(atp_headroom, bool) or not isinstance(atp_headroom, int):
        raise PolicyError(
            f"headroom must be an integer, not {type(atp_headroom).__name__}")
    if atp_headroom < 0:
        raise PolicyError(
            f"headroom must be >= 0, not {atp_headroom}. Negative headroom pins "
            "an `atp` BELOW what the check actually spends, so the verifier "
            "re-runs it out of budget, the term dissipates instead of reducing "
            "to the pinned `expect`, and the check reports `fail` — a WRONG "
            "VERDICT, not an error. Use --max-atp to lower the compile budget; "
            "headroom only ever widens what the verifier may spend.")
    prog = parse(src)
    expected = evaluate(prog)

    low = _Lowering(prog.facts)
    term = low.term(prog.expr)
    nodes, term_hash, term_depth = _walk(term)
    if len(nodes) > max_nodes:
        raise PolicyError(
            f"this check needs {len(nodes)} stored nodes, over the {max_nodes} "
            "node limit. Every node is a blob a verifier must hold; shorten "
            "the strings, narrow the ranges, or split the policy into several "
            "checks.")
    if term_depth > max_depth:
        raise PolicyError(
            f"this check is {term_depth} nodes deep, over the {max_depth} "
            "limit. A verifier's Σ-GLYPH `max_node_depth` is a local resource "
            "control, and breaching it is a fault rather than a verdict — so a "
            "deep check is refused here instead of becoming unverifiable there. "
            "Split the policy into several checks.")

    # Evaluate on a private store first: never emit a check we cannot run.
    priv = sg.Store()
    for _h, b in nodes:
        priv.put(b)
    try:
        result_term, atp = sg.eval_hash(term_hash, max_atp, priv)
    except (sg.ResourceFault, RecursionError) as exc:      # local, not a verdict
        raise PolicyError(
            f"this check breached a Σ-GLYPH resource limit while compiling "
            f"({exc}). That is a local fault, not a verdict, so no check is "
            "emitted; split the policy into several smaller ones.") from None
    rh = sg.term_hash(result_term).hex()
    if result_term == ("dis", sg.R_ATP):
        raise PolicyError(
            f"this check costs more than the {max_atp} ATP compile budget. "
            "Raise --max-atp only if the verifiers that will re-run it agree "
            "to spend that much (SPEC §3.1: a verifier MAY refuse an "
            "over-budget reason, and then reports it as unverified, not as a "
            "verdict).")
    if result_term == ("dis", sg.R_UNRES):
        raise CompilerBug("compiled term referenced a node the compiler did "
                          "not store")
    if rh == sg.K_H.hex():
        result = True
    elif rh == sg.FALSE_H.hex():
        result = False
    else:
        raise CompilerBug(f"term did not reduce to a Church boolean ({rh[:12]})")

    # (1) of the module docstring: the emitted term is checked against the
    # reference interpreter BEFORE anything is written. The term is closed and
    # the facts are pinned, so this covers the check's entire input space.
    if result != expected:
        raise CompilerBug(
            f"compiled term reduces to {result} but the source means "
            f"{expected} — refusing to emit. Formula: {prog.formula()}")

    doc = {"ski": 1, "term": term_hash.hex(),
           "atp": atp + atp_headroom, "expect": rh}

    # (4) of the module docstring. Everything above validated what the compiler
    # MEANT to emit; this validates the bytes it is about to write.
    raw = _validate_emission(doc, priv, atp)

    blob = None
    if put is not None:
        for _h, b in nodes:
            put(b)
        blob = put(raw)          # exactly the bytes `_validate_emission` ran
    return Compiled(prog, doc, result, blob, len(nodes), low.comparisons,
                    max_atp)


def compile_file(path, put=None, **kw):
    p = Path(path)
    kw.setdefault("name", p.name)
    return compile_source(p.read_text(encoding="utf-8"), put, **kw)


# ----------------------------------------------------------------------- CLI
def _cli_verify(args):
    """Compile into a throwaway store, then re-run the check the way a verifier
    does — through `warrant.run_ski_check`, off the stored blobs. Nothing here
    reads the compiler's own answer: the verdict comes out of the reduction."""
    import tempfile
    warrant_py = Path(__file__).resolve().parent / "warrant.py"
    spec = importlib.util.spec_from_file_location("warrant_impl", warrant_py)
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    import shutil
    tmp = tempfile.mkdtemp(prefix="wpl-verify-")
    try:
        store = w.Store(str(Path(tmp) / ".warrants"))
        store.init()
        out = compile_file(args.file, store.put_blob, max_atp=args.max_atp)
        verdict, result_hash, spent = w.run_ski_check(store, out.blob)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"check     {out.blob}")
    print(f"verdict   {verdict}")
    print(f"result    {result_hash}  "
          f"({'Church TRUE' if result_hash == sg.K_H.hex() else 'Church FALSE'})")
    print(f"atp_spent {spent}  (pinned atp {out.doc['atp']})")
    return 0 if verdict == "pass" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="policy_lang",
        description="compile a WPL policy check to a ski@v1 term")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compile", help="compile a .wpl file and report its cost")
    c.add_argument("file")
    c.add_argument("--store", help="warrant store to write the blobs into "
                                   "(omit: compile without writing anything)")
    c.add_argument("--max-atp", type=int, default=DEFAULT_MAX_ATP)
    c.add_argument("--headroom", type=int, default=0,
                   help="ATP added to the exact spend when pinning `atp` "
                        "(>= 0; the sum must stay a uint32 and within the "
                        "verifier's re-execution budget)")
    c.add_argument("--json", action="store_true")
    e = sub.add_parser("explain", help="parse and evaluate without compiling")
    e.add_argument("file")
    v = sub.add_parser("verify", help="compile, then re-run the check through "
                                      "the verifier's own ski@v1 path")
    v.add_argument("file")
    v.add_argument("--max-atp", type=int, default=DEFAULT_MAX_ATP)
    args = ap.parse_args(argv)

    try:
        if args.cmd == "verify":
            return _cli_verify(args)
        if args.cmd == "explain":
            prog = parse(Path(args.file).read_text(encoding="utf-8"))
            print(f"formula   {prog.formula()}")
            for f in prog.facts.values():
                print(f"fact      {f.name}: {f.type} = {_lit(f.value)}")
            print(f"result    {'true' if evaluate(prog) else 'false'}")
            return 0
        put = None
        if args.store:
            root = Path(args.store) / "blobs"
            root.mkdir(parents=True, exist_ok=True)

            def put(data, _r=root):
                h = sg.sha(data).hex()
                p = _r / h
                if not p.exists():
                    p.write_bytes(data)
                return h
        out = compile_file(args.file, put, max_atp=args.max_atp,
                           atp_headroom=args.headroom)
    except PolicyError as exc:
        print(f"REFUSED   {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(out.to_json(), indent=2, sort_keys=True))
    else:
        print(out.report(Path(args.file).name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
