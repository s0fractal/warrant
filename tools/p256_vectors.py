#!/usr/bin/env python3
"""WRT-019 P-256 signature vectors, and a selftest that each negative one bites.

Every vector is reproducible from this file: the key is a fixed scalar, and
signing uses RFC 6979 (deterministic). The selftest proves, for each negative
vector, that a LENIENT verifier (plain ECDSA, DER, uncompressed keys, high-S
accepted) would accept it or that it is malformed for a stated reason, so a
vector that stops separating the WRT-019 rule from a lenient one fails here.

    python3 tools/p256_vectors.py --selftest
"""
import hashlib
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W  # noqa: E402

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
N = W._P256_N
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
ALG = W.ALG_P256


def key(label):
    d = int.from_bytes(hashlib.sha256(label.encode()).digest(), "big") % N
    return ec.derive_private_key(d, ec.SECP256R1())


def compressed(sk):
    return sk.public_key().public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.CompressedPoint).hex()


def uncompressed(sk):
    return sk.public_key().public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint).hex()


def native_rs(sk, msg):
    """RFC 6979 signature as the library produces it: s may be high."""
    return decode_dss_signature(sk.sign(msg, ec.ECDSA(hashes.SHA256(), deterministic_signing=True)))


def rs_hex(r, s):
    return r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex()


def lenient_ok(key_hex, r, s, msg):
    """Plain ECDSA as most libraries do it: any encoding, high-S accepted."""
    try:
        pk = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes.fromhex(key_hex))
        pk.verify(encode_dss_signature(r, s), msg, ec.ECDSA(hashes.SHA256()))
        return True
    except (ValueError, InvalidSignature):
        return False


def not_on_curve_x():
    """The smallest x whose x^3 - 3x + b is not a square mod p."""
    x = 1
    while pow((x ** 3 - 3 * x + B) % P, (P - 1) // 2, P) == 1:
        x += 1
    return x


def vectors(wid, demo_ed25519_key, demo_ed25519_sig):
    """[(polarity, why, entry_without_warrant_id, lenient_witness)] for one WarrantID.
    lenient_witness: True if a lenient verifier accepts the negative (it bites),
    or a short reason the bytes are malformed in a way the rule must name."""
    msg = W.sig_message(wid)
    sk = key("warrant WRT-019 demo key")
    k = compressed(sk)
    r, s = native_rs(sk, msg)
    low = min(s, N - s)
    out = [("positive", "a P-256 signature, compressed key, low-S r||s", {"alg": ALG, "key": k, "sig": rs_hex(r, low)}, None)]
    # A key whose deterministic signature is natively high-S: the filed one is normalized.
    i = 0
    while True:
        sk2 = key(f"warrant WRT-019 high-S demo {i}")
        r2, s2 = native_rs(sk2, msg)
        if s2 > N // 2:
            break
        i += 1
    out.append(("positive", "a natively high-S signature after normalization (s -> n - s), as a Secure Enclave signer must file it",
                {"alg": ALG, "key": compressed(sk2), "sig": rs_hex(r2, N - s2)}, None))
    out += [
        ("negative", "high-S: the same signature with s replaced by n - s (valid ECDSA, rejected by WRT-019's low-S rule)",
         {"alg": ALG, "key": k, "sig": rs_hex(r, N - low)}, lenient_ok(k, r, N - low, msg)),
        ("negative", "r = 0", {"alg": ALG, "key": k, "sig": rs_hex(0, low)}, "r outside [1, n)"),
        ("negative", "s = 0", {"alg": ALG, "key": k, "sig": rs_hex(r, 0)}, "s outside [1, (n-1)/2]"),
        ("negative", "r = n", {"alg": ALG, "key": k, "sig": rs_hex(N, low)}, "r outside [1, n)"),
        ("negative", "s = n", {"alg": ALG, "key": k, "sig": rs_hex(r, N)}, "s outside [1, (n-1)/2]"),
        ("negative", "the key in UNCOMPRESSED form (04 || x || y) with a valid signature: one key, one encoding",
         {"alg": ALG, "key": uncompressed(sk), "sig": rs_hex(r, low)}, lenient_ok(uncompressed(sk), r, low, msg)),
        ("negative", "a key with prefix 05", {"alg": ALG, "key": "05" + k[2:], "sig": rs_hex(r, low)}, "prefix not 02/03"),
        ("negative", "a compressed key whose x = p (not a field element)",
         {"alg": ALG, "key": "02" + P.to_bytes(32, "big").hex(), "sig": rs_hex(r, low)}, "x >= p"),
        ("negative", "a compressed key whose x is not on P-256 (x^3 - 3x + b is not a square)",
         {"alg": ALG, "key": "02" + not_on_curve_x().to_bytes(32, "big").hex(), "sig": rs_hex(r, low)}, "not on the curve"),
        ("negative", "a P-256 signature over the bare WarrantID (no warrant-sig-v1 separator)",
         {"alg": ALG, "key": k, "sig": rs_hex(*_low(native_rs(sk, bytes.fromhex(wid))))},
         lenient_ok(k, *_low(native_rs(sk, bytes.fromhex(wid))), bytes.fromhex(wid))),
        ("negative", "a valid P-256 key and signature WITHOUT alg: read as Ed25519, which a 33-byte key cannot be",
         {"key": k, "sig": rs_hex(r, low)}, lenient_ok(k, r, low, msg)),
        ("negative", "a valid Ed25519 key and signature labelled alg ecdsa-p256-sha256",
         {"alg": ALG, "key": demo_ed25519_key, "sig": demo_ed25519_sig}, "Ed25519 key under the P-256 label"),
        ("negative", "a valid P-256 key and signature under an unknown alg",
         {"alg": "ecdsa-p384-sha384", "key": k, "sig": rs_hex(r, low)}, lenient_ok(k, r, low, msg)),
        ("negative", "the signature DER-encoded instead of 64-byte r||s",
         {"alg": ALG, "key": k, "sig": encode_dss_signature(r, low).hex()}, "not 64 bytes"),
        ("negative", "the key in UPPERCASE hex: one key, one string",
         {"alg": ALG, "key": k.upper(), "sig": rs_hex(r, low)}, lenient_ok(k, r, low, msg)),
    ]
    return out


def _low(rs):
    r, s = rs
    return r, min(s, N - s)


def selftest():
    wid = "00" * 31 + "01"
    sk_ed = W.Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    ed_key = W.pubkey_hex(sk_ed)
    ed_sig = sk_ed.sign(W.sig_message(wid)).hex()
    ok = True
    for polarity, why, entry, lenient in vectors(wid, ed_key, ed_sig):
        got = W.verify_sig(wid, entry)
        want = polarity == "positive"
        bites = lenient is None or lenient is True or isinstance(lenient, str)
        good = got is want and bites
        ok &= good
        print(("ok  " if good else "FAIL"), polarity, "|", why[:90], "|",
              "lenient accepts" if lenient is True else (lenient or ""))
    print("P256 VECTORS:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else __doc__ and print(__doc__) or 0)
