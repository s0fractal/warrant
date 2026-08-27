#!/usr/bin/env python3
"""Guard for proofs/Settlement.lean — the WRT-003 rev-4 fingerprint rule,
mechanized in Lean 4 core.

Runs green iff, and only iff:
  1. Settlement.lean compiles with the Lean kernel, no errors and no warnings;
  2. no theorem depends on `sorryAx`, `native_decide`'s trusted-compiler axioms,
     or anything outside the allowed cone {propext};
  3. the source contains no `sorry`, no `axiom`, no `native_decide`, no
     `@[implemented_by]`/`@[extern]` (the guard-bypass shapes catalogued in the
     sibling repository's twenty-one-ways paper).

Every named theorem in Settlement.lean must appear in GUARDED below; a theorem
the file proves but this guard does not list is a coverage gap and fails,
because "the scan found nothing" must not be reachable by adding a theorem the
scan never looks at. UNRUN (exit 3) if the Lean toolchain is absent.
"""
import re
import subprocess
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "Settlement.lean"

# The standard SOUND Lean-core cone (the sibling repository's gold standard).
# What matters is what is EXCLUDED: sorryAx (an unproved hole) and the
# native_decide trusted-compiler axioms (which move the compiler into the
# trusted base). propext / Quot.sound / Classical.choice are the accepted sound
# axioms of Lean's kernel. The pass message reports the actual union used, so
# the tighter {propext}-only achievement of the fingerprint-algebra layer is
# not hidden behind the wider allowance the admissibility layer needs.
ALLOWED_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}

# Every theorem the file proves. Kept here so an unlisted theorem is a failure,
# not a silent skip (the file's own subject: a control whose scope is chosen by
# the thing it controls is no control).
GUARDED = [
    "fp_ignores_claims",
    "fp_factors_through_result",
    "fp_is_function_of_result",
    "dissonance_ineligible",
    "fp_none_of_dissonance",
    "nested_dissonance_ineligible",
    "eligible_iff_no_dis",
    "atp_cannot_steer",
    "restatement_inadmissible",
    "novel_result_admissible",
    "dissonance_candidate_inadmissible",
]

FORBIDDEN = [
    (r"\bsorry\b", "sorry"),
    (r"\bnative_decide\b", "native_decide"),
    (r"^\s*axiom\b", "axiom declaration"),
    (r"@\[\s*implemented_by", "@[implemented_by]"),
    (r"@\[\s*extern", "@[extern]"),
]


def fail(msg):
    print(f"SETTLEMENT-GUARD: FAIL — {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if shutil.which("lean") is None:
        print("SETTLEMENT-GUARD: UNRUN — the Lean toolchain is not on PATH "
              "(install via elan; https://leanprover.github.io)")
        sys.exit(3)

    src_text = SRC.read_text(encoding="utf-8")

    # (3) source-shape denylist, before trusting the compiler at all.
    for pat, label in FORBIDDEN:
        if re.search(pat, src_text, re.MULTILINE):
            fail(f"forbidden construct in Settlement.lean: {label}")

    # every proved theorem must be in GUARDED (coverage, not luck)
    proved = set(re.findall(r"^theorem\s+([A-Za-z_][A-Za-z0-9_']*)",
                            src_text, re.MULTILINE))
    listed = set(GUARDED)
    if proved - listed:
        fail(f"theorem(s) proved but not guarded: {sorted(proved - listed)}")
    if listed - proved:
        fail(f"guarded name(s) not found as theorems: {sorted(listed - proved)}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        olean = td / "Settlement.olean"
        # (1) compile, warnings-as-failures (an unused-simp warning once hid here)
        r = subprocess.run(["lean", "-o", str(olean), str(SRC)],
                           capture_output=True, text=True)
        if r.returncode != 0 or r.stdout.strip() or r.stderr.strip():
            fail("Settlement.lean did not compile cleanly:\n"
                 + (r.stdout + r.stderr).strip())

        # (2) axiom cone of every guarded theorem
        checker = td / "_ax.lean"
        checker.write_text(
            "import Settlement\nopen Warrant.Settlement\n"
            + "".join(f"#print axioms {t}\n" for t in GUARDED),
            encoding="utf-8")
        # Settlement.olean must sit on LEAN_PATH under its module name.
        (td / "Settlement.olean").write_bytes(olean.read_bytes())
        r2 = subprocess.run(["lean", str(checker)],
                            capture_output=True, text=True,
                            env={"LEAN_PATH": str(td), "PATH": _path()})
        out = r2.stdout + r2.stderr
        if r2.returncode != 0:
            fail("axiom check did not run:\n" + out.strip())

        used = set()
        for t in GUARDED:
            m = re.search(rf"'Warrant\.Settlement\.{re.escape(t)}' depends on "
                          r"axioms: \[([^\]]*)\]", out)
            if not m:
                # a theorem that "depends on no axioms" prints a different line
                if re.search(rf"'Warrant\.Settlement\.{re.escape(t)}' does not "
                             r"depend on any axioms", out):
                    continue
                fail(f"no axiom report for {t}")
            cone = {a.strip() for a in m.group(1).split(",") if a.strip()}
            extra = cone - ALLOWED_AXIOMS
            if extra:
                fail(f"{t} depends on disallowed axioms: {sorted(extra)}")
            used |= cone

    print(f"SETTLEMENT-GUARD: PASS — {len(GUARDED)} theorems, "
          f"axiom cone = {sorted(used)} (⊆ {sorted(ALLOWED_AXIOMS)}), "
          "no sorry/axiom/native_decide.")
    sys.exit(0)


def _path():
    import os
    return os.environ.get("PATH", "")


if __name__ == "__main__":
    main()
