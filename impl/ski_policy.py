"""ski_policy — author re-executable `ski@v1` policy predicates.

NOTE (2026-07-31): this is now the LOW-LEVEL layer. `impl/policy_lang.py`
compiles a readable source language (WPL — comparisons, `in`, `&&`/`||`/`!`
over ints, strings and booleans) to the same `ski@v1` checks and reports what
they cost; see `docs/authoring-checks.md`. This module remains because it is
what the boolean core of that compiler emits, byte-for-byte: a boolean-only WPL
source and the equivalent `And`/`Not` expression here produce the identical
term, which `tests/policy_lang.py` pins. Write new policies in WPL; keep this
for boolean formulas built programmatically.

A policy predicate is a boolean formula over named atomic facts:

    permit = within_window AND NOT retroactive

`compile_check` turns it into a content-addressed Σ-GLYPH Book I term. Anyone
re-executes that term on their own machine (`warrant check <hash>`) and gets the
same verdict — a *reason you can re-run*, not prose you must trust. Booleans use
the Church encoding native to Book I: TRUE = `K`, FALSE = `K I`; a formula
reduces to one of those two normal forms and the check pins which.

Honest scope: this proves the formula's VERDICT given the fact VALUES baked into
the term — not that the facts are true in the world (that is what evidence and
signatures are for). It moves `ski@v1` past a single hand-built constant to real,
re-verifiable policy logic, addressing the "extend the library of ready ski@v1
controls" gap.

Depends only on the bundled Σ-GLYPH Book I oracle (`sigma_glyph`) + stdlib.
"""
import importlib.util
import json
import sys
from pathlib import Path

_impl = Path(__file__).resolve().parent
if str(_impl) not in sys.path:                 # direct file-load in tests/tools
    sys.path.insert(0, str(_impl))
import warrant as _warrant                    # noqa: E402

# Use the same digest-before-import boundary as verification.  Authoring with
# moved evaluator bytes is a refusal, never execution under the frozen tag.
sg = _warrant.load_bundled_sigma("ski@v1")
if sg is None:
    raise RuntimeError("pinned ski@v1 evaluator unavailable")


# ---------- expression DSL ----------
# An expression is a small tagged tuple; the constructors below build them.
def const(value):
    return ("const", bool(value))


def Fact(name, value):
    """A named atomic fact with a known boolean value (from evidence)."""
    return ("fact", str(name), bool(value))


def Not(e):
    return ("not", e)


def And(*es):
    if not es:
        raise ValueError("And needs >=1 operand")
    out = es[0]
    for e in es[1:]:
        out = ("and", out, e)
    return out


def Or(*es):
    if not es:
        raise ValueError("Or needs >=1 operand")
    out = es[0]
    for e in es[1:]:
        out = ("or", out, e)
    return out


# ---------- term construction (Church booleans over Book I) ----------
_TRUE = ("thunk", sg.K_H)              # TRUE  = K            (genesis-intrinsic)
_FALSE = ("thunk", sg.FALSE_H)         # FALSE = K I          (node must be stored)


def _App(l, r):
    return ("app", l, r)


def _to_term(e):
    """Compile an expression to a Σ-GLYPH term tree. Selection `p a b` is a plain
    application, so no lambda compiler is needed for closed formulas."""
    tag = e[0]
    if tag == "const":
        return _TRUE if e[1] else _FALSE
    if tag == "fact":
        return _TRUE if e[2] else _FALSE
    if tag == "not":                    # p FALSE TRUE
        p = _to_term(e[1])
        return _App(_App(p, _FALSE), _TRUE)
    if tag == "and":                    # p q FALSE
        p, q = _to_term(e[1]), _to_term(e[2])
        return _App(_App(p, q), _FALSE)
    if tag == "or":                     # p TRUE q
        p, q = _to_term(e[1]), _to_term(e[2])
        return _App(_App(p, _TRUE), q)
    raise ValueError(f"unknown expression node: {tag!r}")


def _facts(e, acc):
    if e[0] == "fact":
        acc[e[1]] = e[2]
    elif e[0] == "not":
        _facts(e[1], acc)
    elif e[0] in ("and", "or"):
        _facts(e[1], acc)
        _facts(e[2], acc)
    return acc


def _formula(e):
    tag = e[0]
    if tag == "const":
        return "TRUE" if e[1] else "FALSE"
    if tag == "fact":
        return e[1]
    if tag == "not":
        return f"NOT {_formula(e[1])}"
    if tag == "and":
        return f"({_formula(e[1])} AND {_formula(e[2])})"
    if tag == "or":
        return f"({_formula(e[1])} OR {_formula(e[2])})"
    raise ValueError(tag)


def _canon(doc):
    # Byte-identical to warrant's JCS canonicalization for these ASCII bodies.
    return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


class Check:
    """The result of compiling a predicate: the ski@v1 check doc plus metadata."""
    def __init__(self, doc, result, formula, facts, blob):
        self.doc = doc                  # {"ski":1,"term":..,"atp":..,"expect":..}
        self.result = result            # bool: what the predicate evaluates to
        self.formula = formula          # human-readable formula string
        self.facts = facts              # {name: bool} baked into the term
        self.blob = blob                # hex hash of the stored check doc (or None)

    def reason(self, verdict=None):
        """A warrant `because` check reason referencing this check. verdict
        defaults to 'pass' (re-execution reproduces the pinned result)."""
        return {"kind": "check", "check": self.blob, "runtime": "ski@v1",
                "verdict": verdict or "pass"}


_GATE = None


def _emission_gate():
    # The file beside this one wins over anything on sys.path, for the reason
    # given in `policy_lang._verifier`: an installed older copy would gate the
    # emission of a check this code, not that code, is about to write.
    global _GATE
    if _GATE is None:
        _q = Path(__file__).resolve().parent / "policy_lang.py"
        if _q.is_file():
            _s = importlib.util.spec_from_file_location("policy_lang_gate", _q)
            pl = importlib.util.module_from_spec(_s)
            _s.loader.exec_module(pl)
        else:
            import policy_lang as pl
        _GATE = pl._validate_emission
    return _GATE


def compile_check(expr, put, atp_headroom=0):
    """Compile a predicate into a stored ski@v1 check.

    `put(bytes) -> hex_hash` stores a blob at its SHA-256 (a warrant
    `Store.put_blob` fits exactly). Returns a `Check`. The check's `atp` is the
    exact spend (+ optional headroom, which must be >= 0); re-execution under it
    reaches normal form. The serialized check is validated and re-executed
    before it is written — see `policy_lang._validate_emission`.
    """
    if isinstance(atp_headroom, bool) or not isinstance(atp_headroom, int):
        raise ValueError(
            f"atp_headroom must be an integer, not {type(atp_headroom).__name__}")
    if atp_headroom < 0:
        raise ValueError(
            f"atp_headroom must be >= 0, not {atp_headroom}: a negative "
            "headroom pins an `atp` below the spend, and the verifier then "
            "reports `fail` instead of reproducing the pinned verdict")
    term = _to_term(expr)

    # Materialize every node (the FALSE leaf + each APPLY) at its NodeHash.
    put(sg.FALSE_BYTES)

    def materialize(t):
        if t[0] == "app":
            materialize(t[1])
            materialize(t[2])
            return put(sg.term_bytes(t))
        return sg.term_hash(t).hex()

    term_hex = materialize(term)

    # Evaluate on a private store to get the exact verdict + ATP.
    priv = sg.Store()
    priv.put(sg.FALSE_BYTES)

    def load(t):
        if t[0] == "app":
            load(t[1]); load(t[2]); priv.put(sg.term_bytes(t))
    load(term)
    result_term, atp = sg.eval_hash(bytes.fromhex(term_hex), 10_000, priv)
    rh = sg.term_hash(result_term).hex()
    if rh == sg.K_H.hex():
        result = True
    elif rh == sg.FALSE_H.hex():
        result = False
    else:
        raise ValueError(f"predicate did not reduce to a Church boolean ({rh[:12]})")

    doc = {"ski": 1, "term": term_hex, "atp": atp + atp_headroom,
           "expect": rh}
    # Same emission gate as the WPL compiler, for the same reason: an `atp`
    # below the spend yields a check that is well-formed, reduces correctly,
    # and that the verifier answers `fail` to. Validated on the serialized
    # bytes, and those bytes are what gets stored. The gate lives in
    # `policy_lang` — the layer above — because ONE definition of "a check this
    # store may hold" is worth an upward import; two definitions are how the
    # two emitters drift apart. Imported lazily so this module still loads
    # standalone for parsing and formula work.
    blob = put(_emission_gate()(doc, priv, atp))
    return Check(doc, result, _formula(expr), _facts(expr, {}), blob)
