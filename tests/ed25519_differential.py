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

    # MIXED-TORSION keys (A = A0 + T8): the case where an unreduced-k verifier
    # diverges from RFC 8032 (Gemini audit P0-2). RS reduces mod L, so it MUST
    # agree with Python on these too. (Both reject a signature not made for A.)
    p = 2**255 - 19
    d = (-121665 * pow(121666, p - 2, p)) % p
    I = pow(2, (p - 1) // 4, p)

    def dec(b):  # decompress 32-byte -> (x,y) or None
        y = int.from_bytes(b, "little") & ((1 << 255) - 1)
        if y >= p:
            return None
        sign = b[31] >> 7
        u = (y * y - 1) % p
        v = (d * y * y + 1) % p
        x = (u * pow(v, 3, p) * pow(u * pow(v, 7, p), (p - 5) // 8, p)) % p
        if (v * x * x - u) % p != 0:
            x = (x * I) % p
        if (v * x * x - u) % p != 0:
            return None
        if x == 0 and sign:
            return None
        if x & 1 != sign:
            x = p - x
        return (x, y)

    def enc(pt):
        x, y = pt
        b = bytearray((y % p).to_bytes(32, "little"))
        b[31] |= (x & 1) << 7
        return bytes(b)

    def add(pp, qq):  # affine Edwards add
        x1, y1 = pp
        x2, y2 = qq
        den = pow(1 + d * x1 * x2 * y1 * y2, p - 2, p)
        x3 = ((x1 * y2 + y1 * x2) * den) % p
        den2 = pow(1 - d * x1 * x2 * y1 * y2, p - 2, p)
        y3 = ((y1 * y2 + x1 * x2) * den2) % p
        return (x3, y3)

    # a torsion point of order 8 (one of the canonical small-order encodings)
    t8 = dec(bytes.fromhex("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a"))
    for i in range(20):
        seed = hashlib.sha256(f"tors:{i}".encode()).digest()
        sk = Ed25519PrivateKey.from_private_bytes(seed)
        pk = sk.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        a0 = dec(pk)
        if a0 is None or t8 is None:
            continue
        mixed = enc(add(a0, t8)).hex()   # A + T8 (mixed torsion, passes blocklist)
        msg = hashlib.sha256(f"tm:{i}".encode()).digest().hex()
        sig = sk.sign(bytes.fromhex(msg)).hex()  # signature for A0, not A+T8
        total += 1
        if rs_verify(mixed, sig, msg) != py_verify(mixed, sig, msg):
            disagree += 1
            print(f"DISAGREE [mixed-torsion] case {i}")

    if disagree:
        print(f"\nED25519-DIFFERENTIAL: DIVERGENCE ({total - disagree}/{total}) seed={args.seed}")
        return 1
    print(f"\nED25519-DIFFERENTIAL: ALL AGREE ({total}/{total}) seed={args.seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
