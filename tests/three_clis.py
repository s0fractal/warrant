"""Shared by the cross-implementation CLI tests: the three verifiers, one tally.

Each test asserts PY = GO = RS by driving the CLIs, so a binary that is not built
must surface as UNRUN (exit 3), never as a pass or a traceback."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W  # noqa: F401  (re-exported for the tests)

PY = [sys.executable, str(ROOT / "impl" / "warrant.py")]
GO = ROOT / "impl-go" / "warrant-go"
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"


class Tally:
    def __init__(self):
        self.ok = True

    def check(self, label, cond, detail=""):
        self.ok &= bool(cond)
        print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")


def unbuilt():
    """The first missing binary, or None."""
    return next((b for b in (GO, RS) if not b.is_file()), None)
