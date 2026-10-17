#!/usr/bin/env python3
"""Each mutant of a proved file (impl-rs/src/hexcanon.rs, bounds.rs) must make
`cargo creusot` fail.

    python3 mutants.py

A proof that still closes on broken code proves nothing about the code. Each
mutant is applied to a COPY of this crate and of the proved files (the shipped
files are never touched), then proved. KILLED = the proof failed. Exit 0 only if the
unmutated copy proves and every mutant is killed.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "impl-rs" / "src"
FILES = ["hexcanon.rs", "bounds.rs"]

# (file, what the mutant does, exact text, replacement)
HEX = [
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
BOUNDS = [
    ("ed25519 L: one byte off in the table",
     "    0x14, 0xde, 0xf9, 0xde,", "    0x14, 0xde, 0xf9, 0xdf,"),
    ("ed25519 p: last byte 0xee (p + 1)",
     "0xff, 0xff, 0xff, 0xed,\n];\nconst P256_P_BE", "0xff, 0xff, 0xff, 0xee,\n];\nconst P256_P_BE"),
    ("P-256 p: a middle byte off",
     "    0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x01,", "    0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x02,"),
    ("P-256 n: last byte off",
     "0xfc, 0x63, 0x25, 0x51,", "0xfc, 0x63, 0x25, 0x50,"),
    ("P-256 n/2: rounded up instead of down",
     "0x7e, 0x31, 0x92, 0xa8,", "0x7e, 0x31, 0x92, 0xa9,"),
    ("equal counts as less (<= instead of <)",
     "    #[cfg(creusot)]\n    proof_assert! { a@.subsequence(0, a@.len()) == a@ && b@.subsequence(0, b@.len()) == b@ };\n    false\n",
     "    #[cfg(creusot)]\n    proof_assert! { a@.subsequence(0, a@.len()) == a@ && b@.subsequence(0, b@.len()) == b@ };\n    true\n"),
    ("compare the wrong way at the first difference",
     "            return a[i] < b[i];", "            return a[i] > b[i];"),
    ("low-S strict: refuse s = n/2",
     "&& !lt_be(&half_n, s)", "&& lt_be(s, &half_n)"),
    ("accept r = 0", "    lt_be(&zero, r) && lt_be(r, &n)", "    lt_be(r, &n)"),
    ("clear two top bits of y, not one",
     "    y[31] %= 128;", "    y[31] %= 64;"),
    ("read S big-endian (no reversal)",
     "    lt_be(&reversed(s), &l)", "    lt_be(s, &l)"),
]
MUTANTS = [("hexcanon.rs", *m) for m in HEX] + [("bounds.rs", *m) for m in BOUNDS]


def prove(texts):
    with tempfile.TemporaryDirectory() as tmp:
        crate = Path(tmp) / "crate"
        shutil.copytree(HERE, crate, ignore=shutil.ignore_patterns("target", "verif", ".why3find"))
        lib = crate / "src" / "lib.rs"
        lib_text = lib.read_text()
        for name, text in texts.items():
            (crate / name).write_text(text)
            lib_text = lib_text.replace(f'#[path = "../../../impl-rs/src/{name}"]', f'#[path = "../{name}"]')
        lib.write_text(lib_text)
        env = dict(os.environ, CARGO_TARGET_DIR=str(HERE / "target" / "mutants"))
        r = subprocess.run(["cargo", "creusot"], cwd=crate, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, check=False)
        return r.returncode == 0, (r.stdout + r.stderr)


def main():
    original = {name: (SRC / name).read_text() for name in FILES}
    ok, out = prove(original)
    print(("ok  " if ok else "FAIL"), "unmutated files prove:", ", ".join(FILES))
    if not ok:
        print(out[-2000:])
        return 1
    all_killed = True
    for name, what, old, new in MUTANTS:
        if original[name].count(old) != 1:
            print("FAIL", f"mutant site not unique or missing: {name}: {what}")
            all_killed = False
            continue
        proved, out = prove(dict(original, **{name: original[name].replace(old, new)}))
        failed = [ln for ln in out.splitlines() if "✘" in ln]
        print(("KILLED  " if not proved else "SURVIVED"), f"{name}: {what}", "|", (failed[0] if failed else "")[:60])
        all_killed &= not proved
    print("CREUSOT MUTANTS:", f"ALL {len(MUTANTS)} KILLED" if all_killed else "SOME SURVIVED")
    return 0 if all_killed else 1


if __name__ == "__main__":
    sys.exit(main())
