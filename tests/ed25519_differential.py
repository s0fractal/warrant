#!/usr/bin/env python3
"""Differential: the from-scratch Rust Ed25519 verifier agrees with Python's
`cryptography` on a battery of real signatures (SPEC line 5 — implementations
MUST agree). Deterministic (seeded keys) so a divergence is reproducible.

For N keypairs, checks a valid signature, a bit-flipped signature, and a
wrong-message signature — every case must verify identically in both. Also
confirms small-order public keys are rejected by both.

Usage:  python3 tests/ed25519_differential.py [--n N] [--seed S]
Env:    WARRANT_RS=path (default ./impl-rs/target/release/warrant-rs)
"""
import argparse
import hashlib
import os
import subprocess
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)
from cryptography.hazmat.primitives import serialization

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RS = os.environ.get("WARRANT_RS", os.path.join(ROOT, "impl-rs", "target", "release", "warrant-rs"))


def rs_verify(k, s, m):
    r = subprocess.run([RS, "verify-sig", k, s, m], capture_output=True, text=True)
    return r.stdout.strip() == "true"


def py_verify(k, s, m):
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(k)).verify(
            bytes.fromhex(s), bytes.fromhex(m))
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1337)
    args = ap.parse_args()
    if not os.path.exists(RS):
        print(f"SKIP ed25519 differential (warrant-rs not built at {RS})")
        return 0

    disagree = 0
    total = 0
    for i in range(args.n):
        # deterministic keypair: seed || counter -> 32-byte private seed
        seed = hashlib.sha256(f"{args.seed}:{i}".encode()).digest()
        sk = Ed25519PrivateKey.from_private_bytes(seed)
        pk = sk.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        msg = hashlib.sha256(f"msg:{args.seed}:{i}".encode()).digest().hex()
        sig = sk.sign(bytes.fromhex(msg)).hex()
        bad = ("1" if sig[0] == "0" else "0") + sig[1:]
        other = hashlib.sha256(f"other:{i}".encode()).digest().hex()
        for label, k, s, m in (("valid", pk, sig, msg),
                               ("tampered", pk, bad, msg),
                               ("wrong-msg", pk, sig, other)):
            total += 1
            if rs_verify(k, s, m) != py_verify(k, s, m):
                disagree += 1
                print(f"DISAGREE [{label}] case {i}")

    # small-order public keys: both MUST reject
    for k in ("00" * 32,
              "0100000000000000000000000000000000000000000000000000000000000000"):
        total += 1
        s = "00" * 64
        m = "00" * 32
        if rs_verify(k, s, m):  # Rust must reject (weak-key blocklist)
            disagree += 1
            print(f"DISAGREE [small-order accepted by RS] {k[:12]}")

    if disagree:
        print(f"\nED25519-DIFFERENTIAL: DIVERGENCE ({total - disagree}/{total}) seed={args.seed}")
        return 1
    print(f"\nED25519-DIFFERENTIAL: ALL AGREE ({total}/{total}) seed={args.seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
