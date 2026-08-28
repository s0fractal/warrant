#!/usr/bin/env python3
"""Mutation self-test for the WRT-005 fingerprint countervector.

A fail-closed test is only evidence if it can be shown to FAIL for the stated
reason. This runs the countervector three ways and asserts:

  1. Go prerequisite present — the countervector settles with BOTH Python and
     Go, so a missing Go binary must be an explicit UNRUN (exit 2), never a
     silent green. Checked here before anything else.
  2. A controlled mutant (one asserted relation flipped) exits NONZERO — the
     countervector's assertions actually bite.
  3. The unmodified countervector exits ZERO.

Exit 0 iff all three hold; 1 if the mutant passed or the clean run failed;
2 if the Go binary (or the Σ-GLYPH oracle) is unavailable.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
COUNTERVECTOR = HERE / "wrt005_gate_countervectors.py"


def go_binary():
    env = os.environ.get("WARRANT_GO")
    if env and Path(env).is_file():
        return env
    default = HERE.parents[1] / "impl-go" / "warrant-go"
    return str(default) if default.is_file() else None


def run(path):
    return subprocess.run([sys.executable, str(path)],
                          capture_output=True, text=True, env=os.environ)


def main():
    # (1) Go prerequisite, explicit. The countervector needs both settlement
    # CLIs; without Go it cannot compare implementations and must not pass.
    if go_binary() is None:
        print("wrt005-selftest: UNRUN — the Go settlement CLI was not found "
              "(build impl-go/warrant-go, or set WARRANT_GO)", file=sys.stderr)
        sys.exit(2)

    src = COUNTERVECTOR.read_text(encoding="utf-8")

    # (2) the mutant: flip exactly one asserted collapse relation. If the
    # countervector still exits 0, its assertions are decoration.
    mutant_src, n = re.subn(
        r"check\(fp\(r_w\) == fp\(r_full\),",
        "check(fp(r_w) != fp(r_full),", src, count=1)
    if n != 1:
        print("wrt005-selftest: FAIL — could not locate the assertion to "
              "mutate; the countervector changed shape.", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as td:
        mutant = Path(td) / "mutant.py"
        # copy the whole fixtures dir context by importing from the real dir:
        # the mutant imports `settlement` via sys.path relative to its own
        # location, so run it from the real fixtures dir instead of the tmp one.
        mutant = COUNTERVECTOR.with_name("_wrt005_mutant.py")
        try:
            mutant.write_text(mutant_src, encoding="utf-8")
            m = run(mutant)
            if m.returncode == 0:
                print("wrt005-selftest: FAIL — the MUTANT (a flipped relation) "
                      "exited 0; the countervector cannot go red.",
                      file=sys.stderr)
                print(m.stdout[-800:], file=sys.stderr)
                sys.exit(1)
        finally:
            mutant.unlink(missing_ok=True)

    # (3) the unmodified countervector must be green.
    clean = run(COUNTERVECTOR)
    if clean.returncode != 0:
        print("wrt005-selftest: FAIL — the unmodified countervector did not "
              f"pass (exit {clean.returncode}).", file=sys.stderr)
        print(clean.stdout[-800:] + clean.stderr[-800:], file=sys.stderr)
        sys.exit(clean.returncode or 1)

    print("wrt005-selftest: PASS — Go prerequisite enforced; the mutant exits "
          "nonzero; the clean countervector exits zero.")
    sys.exit(0)


if __name__ == "__main__":
    main()
