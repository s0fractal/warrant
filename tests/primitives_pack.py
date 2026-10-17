#!/usr/bin/env python3
"""The vendored s0fractal/primitives pack: Python, Go and Rust each pass every class.

primitives is the shared statement of behaviour (SHA-256, RFC 8785, the signature
message, Ed25519, P-256) held as vectors, not as shared code. Its p256-decode class
asks the P-256 decoder directly, which signature vectors cannot do: with impl-rs's
x < p or on-curve check removed, verify-sig still passed 50/50 while p256-decode
reported the decoder accepting what it must refuse (measured 2026-10-17).
"""
import subprocess
import sys

from three_clis import GO, PY, RS, Tally, unbuilt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "third_party" / "primitives"
T = Tally()


def main():
    missing = unbuilt()
    if missing:
        print(f"UNRUN  {missing} not built")
        return 3
    pin = subprocess.run([sys.executable, str(ROOT / "tools" / "vendor_primitives.py"), "--check"],
                         capture_output=True, text=True, check=False)
    T.check("vendored pack matches its pin", pin.returncode == 0, pin.stdout.strip())
    for name, cand in (("py", " ".join(PY + ["probe"])), ("go", f"{GO} probe"), ("rs", f"{RS} probe")):
        r = subprocess.run([sys.executable, str(PACK / "run.py"), "--candidate", cand],
                           capture_output=True, text=True, check=False)
        T.check(f"{name}: every primitives class passes", r.returncode == 0,
                "\n".join(r.stdout.strip().splitlines()[-8:]))
    print(f"\nPRIMITIVES-PACK: {'ALL PASS' if T.ok else 'FAILURES PRESENT'}")
    return 0 if T.ok else 1


if __name__ == "__main__":
    sys.exit(main())
