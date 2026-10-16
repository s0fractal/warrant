#!/usr/bin/env python3
"""Ed25519 edge signatures that separate cofactorless from cofactored verifiers.

WHY
---
SPEC §5 pins signature acceptance by rejecting small-order public keys,
non-canonical point encodings and `S >= L`. The conformance pack, though, held
none of the signatures on which real verifiers split ("Taming the many EdDSAs",
Chalkias et al. 2020; ZIP-215):

  * a mixed-torsion key `A' = A + T8` with a signature honestly made for it:
    the cofactored equation `[8][S]B = [8]R + [8][k]A'` always holds, while the
    cofactorless `[S]B = R + [k]A'` holds only when `[k]T8 = O`, i.e. when
    `(k mod L) mod 8 == 0`;
  * a small-order commitment point `R` with `S = k*a`: cofactored verifiers
    accept it (the torsion vanishes under [8]), cofactorless ones do not;
  * the same `R` written non-canonically (`y >= p`): a verifier that reduces
    `y` mod p on decode accepts what a strict one rejects;
  * `S + L` in place of `S`: a verifier that reduces `S` accepts it.

The repository's own differential test fed mixed-torsion keys signatures made
for the *other* key, which every verifier rejects, so it never reached the
divergent case. These vectors do. A cofactored verifier now fails the pack
instead of passing all of it.

Signatures are built from the SPEC §8 demo seed, with nonces chosen here
rather than by RFC 8032's deterministic rule. A verifier never sees how a
nonce was chosen, so the vectors are reproducible from this file alone.
"""
import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
BY = 4 * pow(5, P - 2, P) % P
SEP = b"warrant-sig-v1:"


def _recover_x(y, sign):
    u = (y * y - 1) % P
    v = (D * y * y + 1) % P
    x = (u * pow(v, 3, P) * pow(u * pow(v, 7, P), (P - 5) // 8, P)) % P
    if (v * x * x - u) % P:
        x = x * SQRT_M1 % P
    if (v * x * x - u) % P:
        return None
    if x == 0 and sign:
        return None
    return P - x if (x & 1) != sign else x


B = (_recover_x(BY, 0), BY)
O = (0, 1)


def add(p1, p2):
    (x1, y1), (x2, y2) = p1, p2
    t = D * x1 * x2 * y1 * y2 % P
    return ((x1 * y2 + y1 * x2) * pow(1 + t, P - 2, P) % P,
            (y1 * y2 + x1 * x2) * pow(1 - t, P - 2, P) % P)


def mul(k, pt):
    acc = O
    while k:
        if k & 1:
            acc = add(acc, pt)
        pt = add(pt, pt)
        k >>= 1
    return acc


def enc(pt):
    x, y = pt
    b = bytearray(y.to_bytes(32, "little"))
    b[31] |= (x & 1) << 7
    return bytes(b)


def dec(b):
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= P:
        return None
    x = _recover_x(y, b[31] >> 7)
    return None if x is None else (x, y)


def h_mod_l(*parts):
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(), "little") % L


def secret_scalar(seed):
    h = bytearray(hashlib.sha512(seed).digest()[:32])
    h[0] &= 248
    h[31] &= 127
    h[31] |= 64
    return int.from_bytes(h, "little")


def cofactorless(pk, sig, msg):
    """Strict RFC 8032 single-scalar check, the rule SPEC §5 pins."""
    a, r = dec(pk), dec(sig[:32])
    s = int.from_bytes(sig[32:], "little")
    if a is None or r is None or s >= L:
        return False
    k = h_mod_l(sig[:32], pk, msg)
    return mul(s, B) == add(r, mul(k, a))


def cofactored_lenient(pk, sig, msg):
    """What a permissive verifier does: [8]-multiplied equation, reduces S and y."""
    yr = int.from_bytes(sig[:32], "little") & ((1 << 255) - 1)
    r_bytes = bytearray((yr % P).to_bytes(32, "little"))
    r_bytes[31] |= sig[31] & 0x80
    a, r = dec(pk), dec(bytes(r_bytes))
    if a is None or r is None:
        return False
    s = int.from_bytes(sig[32:], "little") % L
    k = h_mod_l(sig[:32], pk, msg)
    return mul(8, mul(s, B)) == mul(8, add(r, mul(k, a)))


def edge_vectors(seed, warrant_id_hex):
    """[(polarity, why, key_hex, sig_hex)] for one demo record."""
    a = secret_scalar(seed)
    A = mul(a, B)
    pk = enc(A)
    msg = SEP + bytes.fromhex(warrant_id_hex)
    out = []

    # 1. S + L: same signature, non-canonical scalar.
    r = h_mod_l(b"edge:s-plus-l") or 1
    R = enc(mul(r, B))
    s = (r + h_mod_l(R, pk, msg) * a) % L
    out.append(("negative", "S >= L: a valid signature with S replaced by S + L "
                "(a verifier that reduces S accepts it)",
                pk, R + (s + L).to_bytes(32, "little")))

    # 2-3. Small-order R = an order-4 point (y = 0), S = k*a.
    t4 = (_recover_x(0, 0), 0)
    for label, r_bytes in (
            ("small-order R (canonical order-4 point), S = k*a: cofactored "
             "verifiers accept, cofactorless ones do not", enc(t4)),
            ("non-canonical R encoding (y = p, an alias of an order-4 point), "
             "S = k*a: a verifier that reduces y mod p and multiplies by the "
             "cofactor accepts it", P.to_bytes(32, "little"))):
        k = h_mod_l(r_bytes, pk, msg)
        out.append(("negative", label, pk, r_bytes + (k * a % L).to_bytes(32, "little")))

    # 4-5. Mixed-torsion key A' = A + T8, signatures honestly made for A'.
    t8 = dec(bytes.fromhex("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a"))
    pk_m = enc(add(A, t8))
    found = {}
    i = 0
    while len(found) < 2:
        r = h_mod_l(b"edge:mixed:", str(i).encode())
        R = enc(mul(r, B))
        k = h_mod_l(R, pk_m, msg)
        key = "accept" if k % 8 == 0 else "reject"
        if key not in found:
            found[key] = R + ((r + k * a) % L).to_bytes(32, "little")
        i += 1
    out.append(("negative", "mixed-torsion key A + T8, signature made for that key "
                "with [k]T8 != O: cofactored verifiers accept, cofactorless ones "
                "reject", pk_m, found["reject"]))
    out.append(("positive", "mixed-torsion key A + T8, signature made for that key "
                "with [k]T8 = O: the cofactorless equation holds, so it MUST "
                "verify (a verifier that rejects every mixed-torsion key fails here)",
                pk_m, found["accept"]))
    return [(pol, why, k.hex(), sig.hex()) for pol, why, k, sig in out]


def selftest(seed, warrant_id_hex, demo_pub_hex):
    """Each vector separates the two verifiers exactly as its label says."""
    assert enc(mul(secret_scalar(seed), B)).hex() == demo_pub_hex, "demo key"
    msg = SEP + bytes.fromhex(warrant_id_hex)
    rows = []
    for pol, why, k, s in edge_vectors(seed, warrant_id_hex):
        kb, sb = bytes.fromhex(k), bytes.fromhex(s)
        strict, lax = cofactorless(kb, sb, msg), cofactored_lenient(kb, sb, msg)
        rows.append((pol, strict, lax, why[:60]))
        assert strict == (pol == "positive"), (why, strict)
        if pol == "negative":
            assert lax, f"not a separating vector: {why}"
    return rows


if __name__ == "__main__":
    SEED = b"warrant-demo-seed-000000000000000"[:32]
    WID = "bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78"
    PUB = "5e06999f4dd20f375c9292e39f722a77a67a5c5cf8a5fd74bbb35f99dc4a8cc5"
    for row in selftest(SEED, WID, PUB):
        print("%-8s strict=%-5s cofactored=%-5s %s" % row)
    print("ED25519-EDGE: every vector separates the two rules as labelled")
