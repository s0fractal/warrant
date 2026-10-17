#!/usr/bin/env python3
"""Each mutant of impl-rs/src/hexcanon.rs must make `cargo creusot` fail.

    python3 mutants.py

A proof that still closes on broken code proves nothing about the code. Each
mutant is applied to a COPY of this crate and of hexcanon.rs (the shipped file is
never touched), then proved. KILLED = the proof failed. Exit 0 only if the
unmutated copy proves and every mutant is killed.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "impl-rs" / "src" / "hexcanon.rs"

MUTANTS = [
    ("accept uppercase digits",
     "        b'a'..=b'f' => Some(c - b'a' + 10),\n",
     "        b'a'..=b'f' => Some(c - b'a' + 10),\n        b'A'..=b'F' => Some(c - b'A' + 10),\n"),
    ("accept odd length (drop the parity check)",
     "    if s.len() % 2 != 0 {\n        return None;\n    }\n", ""),
    ("write the halves in the other order",
     "        out.push(digit(bytes[i] / 16));\n        out.push(digit(bytes[i] % 16));\n",
     "        out.push(digit(bytes[i] % 16));\n        out.push(digit(bytes[i] / 16));\n"),
    ("decode the halves in the other order",
     "        out.push(hi * 16 + lo);\n", "        out.push(lo * 16 + hi);\n"),
    ("digit 'g' for 10 (an off-by-one in the letter base)",
     "        b'a' - 10 + n\n", "        b'a' - 9 + n\n"),
]


def prove(src_text):
    with tempfile.TemporaryDirectory() as tmp:
        crate = Path(tmp) / "crate"
        shutil.copytree(HERE, crate, ignore=shutil.ignore_patterns("target", "verif", ".why3find"))
        (crate / "hexcanon.rs").write_text(src_text)
        lib = crate / "src" / "lib.rs"
        lib.write_text(lib.read_text().replace('#[path = "../../../impl-rs/src/hexcanon.rs"]',
                                               '#[path = "../hexcanon.rs"]'))
        env = dict(os.environ, CARGO_TARGET_DIR=str(HERE / "target" / "mutants"))
        r = subprocess.run(["cargo", "creusot"], cwd=crate, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, check=False)
        return r.returncode == 0, (r.stdout + r.stderr)


def main():
    original = SOURCE.read_text()
    ok, out = prove(original)
    print(("ok  " if ok else "FAIL"), "unmutated hexcanon.rs proves")
    if not ok:
        print(out[-2000:])
        return 1
    all_killed = True
    for name, old, new in MUTANTS:
        if original.count(old) != 1:
            print("FAIL", f"mutant site not unique or missing: {name}")
            all_killed = False
            continue
        proved, out = prove(original.replace(old, new))
        failed = [ln for ln in out.splitlines() if "proof failed" in ln or "✘" in ln]
        print(("KILLED  " if not proved else "SURVIVED"), name, "|", (failed[1] if len(failed) > 1 else "")[:70])
        all_killed &= not proved
    print("HEXCANON MUTANTS:", "ALL KILLED" if all_killed else "SOME SURVIVED")
    return 0 if all_killed else 1


if __name__ == "__main__":
    sys.exit(main())
