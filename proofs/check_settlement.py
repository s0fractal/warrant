#!/usr/bin/env python3
"""Guard for proofs/Settlement.lean — the WRT-005 (rev-4) fingerprint rule,
mechanized in Lean 4 core.

Runs green iff, and only iff:
  1. Settlement.lean compiles with the Lean kernel, no errors and no warnings;
  2. no theorem depends on `sorryAx`, `native_decide`'s trusted-compiler axioms,
     or anything outside the sound cone `{propext, Quot.sound, Classical.choice}`
     (the actual union used is reported: `{propext}` for the fingerprint algebra,
     `{propext, Quot.sound}` once the §7 admissibility theorems are included);
  3. the source contains no `sorry`, no `axiom`, no `native_decide`, no
     `@[implemented_by]`/`@[extern]` (the guard-bypass shapes catalogued in the
     sibling repository's twenty-one-ways paper).

Every named theorem in Settlement.lean must appear in GUARDED below; a theorem
the file proves but this guard does not list is a coverage gap and fails,
because "the scan found nothing" must not be reachable by adding a theorem the
scan never looks at. UNRUN (exit 3) if the Lean toolchain is absent.
"""
import os
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


def _source_checks(src_text):
    """(3) source-shape denylist and (coverage) every theorem is guarded."""
    for pat, label in FORBIDDEN:
        if re.search(pat, src_text, re.MULTILINE):
            fail(f"forbidden construct in Settlement.lean: {label}")
    proved = set(re.findall(r"^theorem\s+([A-Za-z_][A-Za-z0-9_']*)",
                            src_text, re.MULTILINE))
    listed = set(GUARDED)
    if proved - listed:
        fail(f"theorem(s) proved but not guarded: {sorted(proved - listed)}")
    if listed - proved:
        fail(f"guarded name(s) not found as theorems: {sorted(listed - proved)}")


def _compile(td):
    """(1) compile Settlement.lean; warnings-as-failures. Returns the .olean."""
    olean = td / "Settlement.olean"
    r = subprocess.run(["lean", "-o", str(olean), str(SRC)],
                       capture_output=True, text=True)
    if r.returncode != 0 or r.stdout.strip() or r.stderr.strip():
        fail("Settlement.lean did not compile cleanly:\n"
             + (r.stdout + r.stderr).strip())
    return olean


def _cone_of(theorem, out):
    """The axiom set a theorem's #print axioms line reports, or None if the
    theorem reported 'does not depend on any axioms'."""
    m = re.search(rf"'Warrant\.Settlement\.{re.escape(theorem)}' depends on "
                  r"axioms: \[([^\]]*)\]", out)
    if m:
        return {a.strip() for a in m.group(1).split(",") if a.strip()}
    if re.search(rf"'Warrant\.Settlement\.{re.escape(theorem)}' does not "
                 r"depend on any axioms", out):
        return set()
    return None


def _axiom_cones(td, olean):
    """(2) run `#print axioms` for every guarded theorem; assert each cone is
    within ALLOWED_AXIOMS. Returns the union actually used."""
    checker = td / "_ax.lean"
    checker.write_text(
        "import Settlement\nopen Warrant.Settlement\n"
        + "".join(f"#print axioms {t}\n" for t in GUARDED), encoding="utf-8")
    (td / "Settlement.olean").write_bytes(olean.read_bytes())
    r = subprocess.run(["lean", str(checker)], capture_output=True, text=True,
                       env={"LEAN_PATH": str(td),
                            "PATH": os.environ.get("PATH", "")})
    out = r.stdout + r.stderr
    if r.returncode != 0:
        fail("axiom check did not run:\n" + out.strip())
    used = set()
    for t in GUARDED:
        cone = _cone_of(t, out)
        if cone is None:
            fail(f"no axiom report for {t}")
        extra = cone - ALLOWED_AXIOMS
        if extra:
            fail(f"{t} depends on disallowed axioms: {sorted(extra)}")
        used |= cone
    return used


def main():
    if shutil.which("lean") is None:
        print("SETTLEMENT-GUARD: UNRUN — the Lean toolchain is not on PATH "
              "(install via elan; https://leanprover.github.io)")
        sys.exit(3)

    _source_checks(SRC.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        used = _axiom_cones(td, _compile(td))

    print(f"SETTLEMENT-GUARD: PASS — {len(GUARDED)} theorems, "
          f"axiom cone = {sorted(used)} (⊆ {sorted(ALLOWED_AXIOMS)}), "
          "no sorry/axiom/native_decide.")
    sys.exit(0)


if __name__ == "__main__":
    main()
