#!/usr/bin/env python3
"""Hand mutations of the scorer and the NOTES renderer: each must make `scorer.py --selftest` fail (PLAN.md).

    python3 mutants.py          # one line per mutant: KILLED by N case(s), or SURVIVED; exit 1 if any survived

Each mutant is applied to a copy of this directory in a temporary tree beside a link to this checkout's `warrant`
package (the self-test builds fixtures with it), never to the files here.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

MUTANTS = {
    "M1 wrong_credit never set": ("scorer.py", '"wrong_credit": int(bool(wrong))', '"wrong_credit": 0'),
    "M2 success on refusing everything (T3)": (
        "scorer.py",
        'success = (got["idempotent"], got["rerun"], got["rollback"]) == ("RELY", "DO NOT RELY", "DO NOT RELY")',
        'success = (got["rerun"], got["rollback"]) == ("DO NOT RELY", "DO NOT RELY")'),
    "M3 used_kit counts any command naming warrant (grep warrant)": (
        "scorer.py", '(n == "Bash" and any(is_kit(a) for a in simple_commands(str(i.get("command", "")))))',
        '(n == "Bash" and "warrant" in str(i.get("command", "")))'),
    "M4 answer lines matched as a prefix, not whole": ("scorer.py", "m = rx.fullmatch(s)", "m = rx.match(s)"),
    "M5 answers read from every message, not the final one": (
        "scorer.py", "    got = answers(task, final)\n",
        "    got = answers(task, '\\n'.join(c.get('text', '') for e in evs if e.get('type') == 'assistant' "
        "for c in e['message']['content'] if c.get('type') == 'text'))\n"),
    "M6 NOTES.md drops the check sentence": (
        "fixture.py", '            if f["check"]:\n                c = f["check"]\n                s +=',
        '            if False:\n                c = f["check"]\n                s +='),
    "M7 the store files no objection": (
        "fixture.py", '            put(f["by"], "challenge",', '            0 and put(f["by"], "challenge",'),
}


def main():
    survived = 0
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "warrant").symlink_to(ROOT / "warrant")
        d = Path(tmp) / "experiments" / "adoption"
        for name, (f, old, new) in MUTANTS.items():
            shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(HERE, d, ignore=shutil.ignore_patterns(".work", "round-*", "__pycache__"))
            src = (d / f).read_text()
            if src.count(old) != 1:
                print(f"{name}: NOT APPLIED (the pattern occurs {src.count(old)} times)")
                survived += 1
                continue
            (d / f).write_text(src.replace(old, new))
            p = subprocess.run([sys.executable, str(d / "scorer.py"), "--selftest"], capture_output=True, text=True)
            fails = [ln.split(":")[0][5:] for ln in p.stdout.splitlines() if ln.startswith("FAIL ")]
            if "Traceback" in p.stderr:
                print(f"{name}: CRASHED (not a kill): {p.stderr.strip().splitlines()[-1]}")
                survived += 1
            elif fails:
                print(f"{name}: KILLED by {len(fails)} case(s): {', '.join(fails[:5])}{' …' if len(fails) > 5 else ''}")
            else:
                print(f"{name}: SURVIVED")
                survived += 1
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
