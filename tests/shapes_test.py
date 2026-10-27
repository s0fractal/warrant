#!/usr/bin/env python3
"""The shapes of warrant/shapes.py, each against the same vectors, and the guard that keeps
them defined once.

Every predicate gets the vectors of the `$`-anchor family (a trailing "\\n", a trailing
"\\r\\n"), non-ASCII digits (\\d would match them), uppercase hex, one character too few and
one too many, and values that are not strings. A predicate must answer False for each one and
must never raise. S6 reads the source of warrant/, warrant_agent/ and tools/. A hex pattern
written anywhere outside shapes.py is a second definition, and S6 fails on it even when the
copy is correct: fourteen copies of one `$` defect (warrant #164) are why.

    python3 tests/shapes_test.py
"""
import ast
import os
import sys
from pathlib import Path

from world import ROOT, check, finish
from warrant import shapes as S

H64, H128, H32 = "a1" * 32, "b2" * 64, "c3" * 16
NOT_STR = {"integer": 5, "null": None, "list": ["a"], "bytes": b"a"}
# Hex patterns that are other shapes, not copies: none since Warrant 3 (a commit id is shapes.hex_of(v, 40)).
OTHER_SHAPES = set()


def answer(pred, v):
    """pred(v), or the exception it raised (a predicate must never raise)."""
    try:
        return pred(v)
    except Exception as e:      # noqa: BLE001
        return f"raised {type(e).__name__}"


def hex_vectors(valid):
    n = len(valid)
    return {"\\n": valid + "\n", "\\r\\n": valid + "\r\n", "\\n inside": valid[:n // 2] + "\n" + valid[n // 2 + 1:],
            "uppercase": valid.upper(), "mixed case": "A" + valid[1:], "short by one": valid[:-1],
            "long by one": valid + "a", "arabic-indic digits": "١" * n, "fullwidth digits": "０" * n,
            "non-ASCII letter": "é" * n, "non-hex": "g" * n, "leading space": " " + valid[1:], "empty": "",
            **NOT_STR}


def table(pred, valid, bad):
    """(ok, wrong): pred is True on every value of `valid` and False on every value of `bad`."""
    wrong = {f"valid {v!r}"[:60]: answer(pred, v) for v in valid if answer(pred, v) is not True}
    wrong.update({k: answer(pred, v) for k, v in bad.items() if answer(pred, v) is not False})
    return not wrong, wrong


def source_roots():
    """The directories S6 reads: the copy under test (WARRANT_IMPL) where it has one."""
    impl = Path(os.environ["WARRANT_IMPL"]) if os.environ.get("WARRANT_IMPL") else None
    return {d: (impl / d if impl is not None and (impl / d).is_dir() else ROOT / d) for d in ("warrant", "warrant_agent", "tools")}


def hex_patterns():
    """[(file, pattern)]: every string constant passed to a call, in the Python source of
    warrant/, warrant_agent/ and tools/, that spells a hex character class."""
    out = []
    for name, d in source_roots().items():
        for p in sorted(d.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            rel = f"{name}/{p.relative_to(d).as_posix()}"
            for node in ast.walk(ast.parse(p.read_text())):
                if isinstance(node, ast.Call):
                    for a in node.args:
                        if isinstance(a, ast.Constant) and isinstance(a.value, str) and "0-9a-f" in a.value:
                            out.append((rel, a.value))
    return out


def main():
    ok, wrong = table(S.hex64, [H64, "0" * 64, "f" * 64], hex_vectors(H64))
    check("S1", ok and S.HEX64.pattern.endswith(r"\Z"), "hex64: exactly 64 lowercase hex digits; no newline, CRLF, "
          "uppercase, non-ASCII digit, wrong length or non-string passes, and none raises", wrong)
    ok, wrong = table(S.hex128, [H128], hex_vectors(H128))
    check("S2", ok, "hex128 (a signature): the same vectors at 128 digits", wrong)
    ok, wrong = table(lambda v: isinstance(v, str) and S.HEX32.match(v) is not None, [H32], hex_vectors(H32))
    check("S3", ok, "HEX32 (a view token): the same vectors at 32 digits", wrong)
    bad = {f"id {k}": f"{v}:0" if isinstance(v, str) else v for k, v in hex_vectors(H64).items()}
    bad.update({"index \\n": f"{H64}:0\n", "index \\r\\n": f"{H64}:0\r\n", "leading zero": f"{H64}:01",
                "double zero": f"{H64}:00", "five digits": f"{H64}:10000", "arabic-indic index": f"{H64}:١",
                "negative": f"{H64}:-1", "no index": f"{H64}:", "no colon": H64, "space": f"{H64}: 1"})
    ok, wrong = table(lambda v: S.hex_of(v, 40), ["ab" * 20], hex_vectors("ab" * 20))
    check("S7", ok and not S.hex_of("ab" * 20, 64) and S.hex_of("", 0), "hex_of(v, n): exactly n lowercase hex "
          "digits (a git object id), the same vectors at 40", wrong)
    ok, wrong = table(S.qref, [f"{H64}:0", f"{H64}:7", f"{H64}:9999"], bad)
    check("S4", ok, "qref: <hex64>:<index 0-9999 without leading zeros>, the same hex vectors and the index's own", wrong)
    valid = ["claude", "codex", "checker sha256:" + H64, "Ünïcödé", "a" * 200, "\U0001f600" * 200, "a b"]
    bad = {"\\n": "codex\n", "\\r\\n": "codex\r\n", "\\n inside": "co\ndex", "tab": "co\tdex", "NUL": "co\x00dex",
           "201 code points": "a" * 201, "201 astral": "\U0001f600" * 201, "not NFC": "é",
           "leading space": " codex", "trailing space": "codex ", "trailing NBSP": "codex ",
           "line separator": "codex ", "paragraph separator": " codex", "empty": "", **NOT_STR}
    ok, wrong = table(S.is_actor, valid, bad)
    check("S5", ok and S.actor_problem("a" * 201) == "must be a string ≤ 200", "actor ids (SPEC-3-21): at most 200 code "
          "points, NFC, no Cc, no white space at the ends; a checker named by its code's hash is one", wrong)
    found = hex_patterns()
    outside = sorted({(f, p) for f, p in found if f != "warrant/shapes.py"} - OTHER_SHAPES)
    dollar = sorted((f, p) for f, p in found if p.endswith("$"))
    check("S6", not outside and not dollar and any(f == "warrant/shapes.py" for f, _ in found),
          "every hex shape is defined once, in warrant/shapes.py; no other module writes a copy, and none ends in `$`",
          {"copies": outside, "$": dollar})
    return finish("SHAPES")


if __name__ == "__main__":
    sys.exit(main())
