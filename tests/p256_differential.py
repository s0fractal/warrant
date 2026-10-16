#!/usr/bin/env python3
"""WRT-019: Python, Go and Rust agree on P-256 signature verification.

Three independent verifiers: Python uses `cryptography`, Go the standard library,
Rust code written from scratch in impl-rs/src/p256.rs. Each is asked through the
conformance probe (the same `verify-sig` request a stranger's runner sends), over:

  * N seeded random keys and WarrantIDs, each signed (RFC 6979) and normalized
    to low-S: every verifier must accept;
  * for each of those, mutations a verifier must reject: high-S, one flipped bit
    in r, in s, in the key's x, the other y parity, another WarrantID.

A disagreement prints the request. Seeded, so a failure reproduces.
"""
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W  # noqa: E402

N = W._P256_N
CANDIDATES = {
    "py": [sys.executable, str(ROOT / "impl" / "warrant.py"), "probe"],
    "go": [str(ROOT / "impl-go" / "warrant-go"), "probe"],
    "rs": [str(ROOT / "impl-rs" / "target" / "release" / "warrant-rs"), "probe"],
}


def probe(cmd, inp):
    req = {"warrant_conformance": "1", "id": "p256", "class": "verify-sig", "input": inp}
    out = subprocess.run(cmd, input=json.dumps(req), capture_output=True, text=True, check=False)
    try:
        return json.loads(out.stdout)["output"]["valid"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return f"no answer: {out.stdout.strip()[:120]} {out.stderr.strip()[:120]}"


def flip(hexs, byte_index):
    b = bytearray(bytes.fromhex(hexs))
    b[byte_index] ^= 1
    return b.hex()


def cases(n, seed):
    rnd = random.Random(seed)
    for i in range(n):
        d = rnd.randrange(1, N)
        sk = ec.derive_private_key(d, ec.SECP256R1())
        key = sk.public_key().public_bytes(serialization.Encoding.X962,
                                           serialization.PublicFormat.CompressedPoint).hex()
        wid = hashlib.sha256(f"wid {seed} {i}".encode()).hexdigest()
        r, s = decode_dss_signature(sk.sign(W.sig_message(wid), ec.ECDSA(hashes.SHA256(), deterministic_signing=True)))
        s = min(s, N - s)
        sig = r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex()
        base = {"warrant_id": wid, "alg": W.ALG_P256, "key": key, "sig": sig}
        yield True, "valid", base
        yield False, "high-S", dict(base, sig=r.to_bytes(32, "big").hex() + (N - s).to_bytes(32, "big").hex())
        yield False, "r bit", dict(base, sig=flip(sig, rnd.randrange(32)))
        yield False, "s bit", dict(base, sig=flip(sig, 32 + rnd.randrange(32)))
        yield False, "key x bit", dict(base, key=flip(key, 1 + rnd.randrange(32)))
        yield False, "other parity", dict(base, key=("03" if key[:2] == "02" else "02") + key[2:])
        yield False, "other wid", dict(base, warrant_id=hashlib.sha256(wid.encode()).hexdigest())


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    for name, cmd in CANDIDATES.items():
        if name != "py" and not Path(cmd[0]).is_file():
            print(f"UNRUN  {cmd[0]} not built")
            return 3
    bad = 0
    total = 0
    for want, label, inp in cases(n, seed=19):
        total += 1
        answers = {name: probe(cmd, inp) for name, cmd in CANDIDATES.items()}
        if set(answers.values()) != {want}:
            bad += 1
            print("FAIL", label, answers, json.dumps(inp)[:200])
    print(f"\nP256-DIFFERENTIAL: {total} requests x 3 verifiers, "
          f"{'ALL AGREE with the expected verdict' if not bad else f'{bad} DISAGREEMENTS'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
