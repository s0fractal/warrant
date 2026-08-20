#!/usr/bin/env python3
"""Regression tests for parsing untrusted reviewer output."""
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "adversarial_gate", ROOT / "tools" / "adversarial_gate.py")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def main():
    text = '''prose
```repro severity=P1 id=F1 clause="D.3" title=first draft
print("first")
```
```python
repro id=F2 severity='P0' closes=Q7 title="quoted title"
print("second")
```
```py
repro id=F1 severity=P2 title=repaired draft
print("repaired")
```
```repro id=SKETCH severity=P3 title=not executable
...
```
'''
    got = GATE.parse_repros(text)
    assert len(got) == 2, got
    by_id = {meta["id"]: (meta, code) for meta, code in got}
    assert by_id["F1"][0] == {
        "id": "F1", "severity": "P2", "title": "repaired draft"
    }, by_id["F1"]
    assert 'print("repaired")' in by_id["F1"][1]
    assert by_id["F2"][0] == {
        "id": "F2", "severity": "P0", "closes": "Q7",
        "title": "quoted title"
    }, by_id["F2"]

    mixed = GATE.parse_repros('''```repro id=M1 title="prefix" remaining words
pass
```
''')
    assert mixed[0][0]["title"] == '"prefix" remaining words', mixed

    # A fence-looking string inside code is not a closing fence unless it is a
    # line by itself, and an unterminated block is never partially executed.
    edge = '''```repro id=E1 title=fence text
print("``` is data")
```
```repro id=E2 title=unterminated
print("never execute")
'''
    parsed = GATE.parse_repros(edge)
    assert len(parsed) == 1 and parsed[0][0]["id"] == "E1", parsed

    # Large attacker-controlled prose is consumed by a bounded line scan.
    assert GATE.parse_repros("x" * 1_000_000) == []

    with tempfile.TemporaryDirectory(prefix="adversarial-gate-test-") as raw:
        workdir = Path(raw)
        cases = [
            ("from harness import violation\nviolation(1, 2)\n", "violation"),
            ("from harness import refuted\nrefuted('property held')\n", "refuted"),
            ("raise RuntimeError('boom')\n", "unrunnable"),
            ("print('no verdict')\n", "inconclusive"),
        ]
        for index, (code, expected) in enumerate(cases):
            result = GATE.run_repro(workdir, code, f"nonce{index}")
            assert result["outcome"] == expected, result
    print("ADVERSARIAL-GATE-PARSER: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
