"""ski_policy — author re-executable `ski@v1` policy predicates.

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
from pathlib import Path

try:
    import sigma_glyph as sg
except ModuleNotFoundError:                                   # in-repo fallback
    _p = Path(__file__).resolve().parent / "sigma_glyph.py"
    _spec = importlib.util.spec_from_file_location("sigma_glyph", _p)
    sg = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(sg)


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


def compile_check(expr, put, atp_headroom=0):
    """Compile a predicate into a stored ski@v1 check.

    `put(bytes) -> hex_hash` stores a blob at its SHA-256 (a warrant
    `Store.put_blob` fits exactly). Returns a `Check`. The check's `atp` is the
    exact spend (+ optional headroom); re-execution under it reaches normal form.
    """
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

    doc = {"ski": 1, "term": term_hex, "atp": atp + int(atp_headroom),
           "expect": rh}
    blob = put(_canon(doc))
    return Check(doc, result, _formula(expr), _facts(expr, {}), blob)
