//! Ed25519 signature VERIFICATION, from scratch, no external crates (RFC 8032).
//! Only verification is needed (Warrant never signs in Rust). Field is the
//! 5×51-bit representation mod p = 2^255-19; points are extended Edwards
//! coordinates. `verify` reduces the SHA-512 challenge mod L (`mod_l`) and checks
//! [S]B = R + [k]A cofactorless — RFC-exact for EVERY key, including mixed-torsion
//! ones (an earlier draft used the unreduced 512-bit hash, which the Gemini 3.1
//! Pro audit showed diverges from the RFC on mixed-torsion keys). Non-canonical
//! point encodings (y ≥ p, x=0 with sign 1) and non-canonical S (S ≥ L) are
//! rejected; small-order keys are additionally rejected upstream by the blocklist.

const MASK51: u64 = (1u64 << 51) - 1;
type Fe = [u64; 5];

// ---------- SHA-512 (FIPS 180-4) ----------
pub fn sha512(input: &[u8]) -> [u8; 64] {
    const K: [u64; 80] = [
        0x428a2f98d728ae22, 0x7137449123ef65cd, 0xb5c0fbcfec4d3b2f, 0xe9b5dba58189dbbc,
        0x3956c25bf348b538, 0x59f111f1b605d019, 0x923f82a4af194f9b, 0xab1c5ed5da6d8118,
        0xd807aa98a3030242, 0x12835b0145706fbe, 0x243185be4ee4b28c, 0x550c7dc3d5ffb4e2,
        0x72be5d74f27b896f, 0x80deb1fe3b1696b1, 0x9bdc06a725c71235, 0xc19bf174cf692694,
        0xe49b69c19ef14ad2, 0xefbe4786384f25e3, 0x0fc19dc68b8cd5b5, 0x240ca1cc77ac9c65,
        0x2de92c6f592b0275, 0x4a7484aa6ea6e483, 0x5cb0a9dcbd41fbd4, 0x76f988da831153b5,
        0x983e5152ee66dfab, 0xa831c66d2db43210, 0xb00327c898fb213f, 0xbf597fc7beef0ee4,
        0xc6e00bf33da88fc2, 0xd5a79147930aa725, 0x06ca6351e003826f, 0x142929670a0e6e70,
        0x27b70a8546d22ffc, 0x2e1b21385c26c926, 0x4d2c6dfc5ac42aed, 0x53380d139d95b3df,
        0x650a73548baf63de, 0x766a0abb3c77b2a8, 0x81c2c92e47edaee6, 0x92722c851482353b,
        0xa2bfe8a14cf10364, 0xa81a664bbc423001, 0xc24b8b70d0f89791, 0xc76c51a30654be30,
        0xd192e819d6ef5218, 0xd69906245565a910, 0xf40e35855771202a, 0x106aa07032bbd1b8,
        0x19a4c116b8d2d0c8, 0x1e376c085141ab53, 0x2748774cdf8eeb99, 0x34b0bcb5e19b48a8,
        0x391c0cb3c5c95a63, 0x4ed8aa4ae3418acb, 0x5b9cca4f7763e373, 0x682e6ff3d6b2b8a3,
        0x748f82ee5defb2fc, 0x78a5636f43172f60, 0x84c87814a1f0ab72, 0x8cc702081a6439ec,
        0x90befffa23631e28, 0xa4506cebde82bde9, 0xbef9a3f7b2c67915, 0xc67178f2e372532b,
        0xca273eceea26619c, 0xd186b8c721c0c207, 0xeada7dd6cde0eb1e, 0xf57d4f7fee6ed178,
        0x06f067aa72176fba, 0x0a637dc5a2c898a6, 0x113f9804bef90dae, 0x1b710b35131c471b,
        0x28db77f523047d84, 0x32caab7b40c72493, 0x3c9ebe0a15c9bebc, 0x431d67c49c100d4c,
        0x4cc5d4becb3e42b6, 0x597f299cfc657e2a, 0x5fcb6fab3ad6faec, 0x6c44198c4a475817,
    ];
    let mut h: [u64; 8] = [
        0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
        0x510e527fade682d1, 0x9b05688c2b3e6c1f, 0x1f83d9abfb41bd6b, 0x5be0cd19137e2179,
    ];
    let bit_len = (input.len() as u128) * 8;
    let mut m = input.to_vec();
    m.push(0x80);
    while m.len() % 128 != 112 {
        m.push(0);
    }
    m.extend_from_slice(&bit_len.to_be_bytes());
    for block in m.chunks_exact(128) {
        let mut w = [0u64; 80];
        for (i, word) in block.chunks_exact(8).enumerate() {
            w[i] = u64::from_be_bytes(word.try_into().unwrap());
        }
        for i in 16..80 {
            let s0 = w[i - 15].rotate_right(1) ^ w[i - 15].rotate_right(8) ^ (w[i - 15] >> 7);
            let s1 = w[i - 2].rotate_right(19) ^ w[i - 2].rotate_right(61) ^ (w[i - 2] >> 6);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = h;
        for i in 0..80 {
            let s1 = e.rotate_right(14) ^ e.rotate_right(18) ^ e.rotate_right(41);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(28) ^ a.rotate_right(34) ^ a.rotate_right(39);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (slot, v) in h.iter_mut().zip([a, b, c, d, e, f, g, hh]) {
            *slot = slot.wrapping_add(v);
        }
    }
    let mut out = [0u8; 64];
    for (chunk, word) in out.chunks_exact_mut(8).zip(h) {
        chunk.copy_from_slice(&word.to_be_bytes());
    }
    out
}

// ---------- field arithmetic (5×51 bits, mod 2^255-19) ----------
fn load8(b: &[u8]) -> u64 {
    let mut a = [0u8; 8];
    a.copy_from_slice(&b[..8]);
    u64::from_le_bytes(a)
}

fn fe_from_bytes(s: &[u8; 32]) -> Fe {
    [
        load8(&s[0..]) & MASK51,
        (load8(&s[6..]) >> 3) & MASK51,
        (load8(&s[12..]) >> 6) & MASK51,
        (load8(&s[19..]) >> 1) & MASK51,
        (load8(&s[24..]) >> 12) & MASK51,
    ]
}

fn fe_to_bytes(f: &Fe) -> [u8; 32] {
    // fully reduce mod p, then pack 255 bits little-endian
    let mut t = *f;
    // carry propagate a couple of times
    for _ in 0..2 {
        let mut carry = 0u64;
        for limb in t.iter_mut() {
            *limb += carry;
            carry = *limb >> 51;
            *limb &= MASK51;
        }
        t[0] += carry * 19;
    }
    // conditional subtract p: q = 1 iff t >= p
    let mut q = (t[0] + 19) >> 51;
    for i in 1..5 {
        q = (t[i] + q) >> 51;
    }
    t[0] += 19 * q;
    let mut carry = 0u64;
    for limb in t.iter_mut() {
        *limb += carry;
        carry = *limb >> 51;
        *limb &= MASK51;
    }
    // pack the 5 51-bit limbs into 255 bits, little-endian (bit-by-bit: simple
    // and correct; called only on serialization).
    let mut out = [0u8; 32];
    let mut bitpos = 0usize;
    for &limb in t.iter() {
        for i in 0..51 {
            if (limb >> i) & 1 == 1 {
                out[bitpos / 8] |= 1 << (bitpos % 8);
            }
            bitpos += 1;
        }
    }
    out
}

fn local_hex(bytes: &[u8]) -> String {
    const H: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::new();
    for &b in bytes {
        s.push(H[(b >> 4) as usize] as char);
        s.push(H[(b & 15) as usize] as char);
    }
    s
}

fn fe_add(a: &Fe, b: &Fe) -> Fe {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3], a[4] + b[4]]
}

fn fe_sub(a: &Fe, b: &Fe) -> Fe {
    // a - b + 2p (2p per-limb so no underflow), then carry
    const TWO_P: Fe = [
        0xFFFFFFFFFFFDA,
        0xFFFFFFFFFFFFE,
        0xFFFFFFFFFFFFE,
        0xFFFFFFFFFFFFE,
        0xFFFFFFFFFFFFE,
    ];
    let mut r = [
        a[0] + TWO_P[0] - b[0],
        a[1] + TWO_P[1] - b[1],
        a[2] + TWO_P[2] - b[2],
        a[3] + TWO_P[3] - b[3],
        a[4] + TWO_P[4] - b[4],
    ];
    let mut carry = 0u64;
    for limb in r.iter_mut() {
        *limb += carry;
        carry = *limb >> 51;
        *limb &= MASK51;
    }
    r[0] += carry * 19;
    r
}

fn fe_mul(a: &Fe, b: &Fe) -> Fe {
    let (a0, a1, a2, a3, a4) = (
        a[0] as u128, a[1] as u128, a[2] as u128, a[3] as u128, a[4] as u128,
    );
    let (b0, b1, b2, b3, b4) = (
        b[0] as u128, b[1] as u128, b[2] as u128, b[3] as u128, b[4] as u128,
    );
    let (b1_19, b2_19, b3_19, b4_19) = (b1 * 19, b2 * 19, b3 * 19, b4 * 19);
    let c0 = a0 * b0 + a1 * b4_19 + a2 * b3_19 + a3 * b2_19 + a4 * b1_19;
    let mut c1 = a0 * b1 + a1 * b0 + a2 * b4_19 + a3 * b3_19 + a4 * b2_19;
    let mut c2 = a0 * b2 + a1 * b1 + a2 * b0 + a3 * b4_19 + a4 * b3_19;
    let mut c3 = a0 * b3 + a1 * b2 + a2 * b1 + a3 * b0 + a4 * b4_19;
    let mut c4 = a0 * b4 + a1 * b3 + a2 * b2 + a3 * b1 + a4 * b0;
    const M: u128 = (1 << 51) - 1;
    c1 += c0 >> 51;
    c2 += c1 >> 51;
    c3 += c2 >> 51;
    c4 += c3 >> 51;
    let mut r0 = (c0 & M) as u64 + ((c4 >> 51) as u64) * 19;
    let mut r1 = (c1 & M) as u64;
    r1 += r0 >> 51;
    r0 &= MASK51;
    let mut r2 = (c2 & M) as u64;
    r2 += r1 >> 51; // keep r1 masked so every output limb is < 2^51 (Gemini audit P2)
    r1 &= MASK51;
    [r0, r1, r2, (c3 & M) as u64, (c4 & M) as u64]
}

fn fe_sq(a: &Fe) -> Fe {
    fe_mul(a, a)
}

fn fe_one() -> Fe {
    [1, 0, 0, 0, 0]
}
fn fe_zero() -> Fe {
    [0, 0, 0, 0, 0]
}

fn fe_eq(a: &Fe, b: &Fe) -> bool {
    fe_to_bytes(a) == fe_to_bytes(b)
}

fn fe_is_negative(a: &Fe) -> bool {
    fe_to_bytes(a)[0] & 1 == 1
}

fn fe_neg(a: &Fe) -> Fe {
    fe_sub(&fe_zero(), a)
}

/// a^(2^252 - 3) — used to build both the inverse and the sqrt candidate.
fn fe_pow_2252m3(a: &Fe) -> Fe {
    // standard addition chain (ref10 pow22523)
    let z2 = fe_sq(a);
    let z8 = fe_sq(&fe_sq(&z2));
    let z9 = fe_mul(a, &z8);
    let z11 = fe_mul(&z2, &z9);
    let z22 = fe_sq(&z11);
    let z_5_0 = fe_mul(&z9, &z22);
    let mut t = fe_sq(&z_5_0);
    for _ in 0..4 {
        t = fe_sq(&t);
    }
    let z_10_0 = fe_mul(&t, &z_5_0);
    t = fe_sq(&z_10_0);
    for _ in 0..9 {
        t = fe_sq(&t);
    }
    let z_20_0 = fe_mul(&t, &z_10_0);
    t = fe_sq(&z_20_0);
    for _ in 0..19 {
        t = fe_sq(&t);
    }
    let z_40_0 = fe_mul(&t, &z_20_0);
    t = fe_sq(&z_40_0);
    for _ in 0..9 {
        t = fe_sq(&t);
    }
    let z_50_0 = fe_mul(&t, &z_10_0);
    t = fe_sq(&z_50_0);
    for _ in 0..49 {
        t = fe_sq(&t);
    }
    let z_100_0 = fe_mul(&t, &z_50_0);
    t = fe_sq(&z_100_0);
    for _ in 0..99 {
        t = fe_sq(&t);
    }
    let z_200_0 = fe_mul(&t, &z_100_0);
    t = fe_sq(&z_200_0);
    for _ in 0..49 {
        t = fe_sq(&t);
    }
    let z_250_0 = fe_mul(&t, &z_50_0);
    t = fe_sq(&z_250_0);
    t = fe_sq(&t);
    fe_mul(&t, a)
}

fn fe_invert(a: &Fe) -> Fe {
    // a^(p-2) = (a^(2^252-3))^8 * a^? — use the pow22523 chain then finish
    // Simpler: a^(p-2). Build from fe_pow_2252m3: p-2 = 2^255-21.
    // (a^(2^252-3)) gives a^(2^252-3); we need a^(2^255-21).
    // Use the standard invert chain instead.
    let z2 = fe_sq(a);
    let t0 = fe_sq(&fe_sq(&z2)); // z2^4 = a^8
    let z9 = fe_mul(a, &t0);
    let z11 = fe_mul(&z2, &z9);
    let z22 = fe_sq(&z11);
    let z_5_0 = fe_mul(&z9, &z22);
    let mut t = fe_sq(&z_5_0);
    for _ in 0..4 {
        t = fe_sq(&t);
    }
    let z_10_0 = fe_mul(&t, &z_5_0);
    t = fe_sq(&z_10_0);
    for _ in 0..9 {
        t = fe_sq(&t);
    }
    let z_20_0 = fe_mul(&t, &z_10_0);
    t = fe_sq(&z_20_0);
    for _ in 0..19 {
        t = fe_sq(&t);
    }
    let z_40_0 = fe_mul(&t, &z_20_0);
    t = fe_sq(&z_40_0);
    for _ in 0..9 {
        t = fe_sq(&t);
    }
    let z_50_0 = fe_mul(&t, &z_10_0);
    t = fe_sq(&z_50_0);
    for _ in 0..49 {
        t = fe_sq(&t);
    }
    let z_100_0 = fe_mul(&t, &z_50_0);
    t = fe_sq(&z_100_0);
    for _ in 0..99 {
        t = fe_sq(&t);
    }
    let z_200_0 = fe_mul(&t, &z_100_0);
    t = fe_sq(&z_200_0);
    for _ in 0..49 {
        t = fe_sq(&t);
    }
    let z_250_0 = fe_mul(&t, &z_50_0);
    t = fe_sq(&z_250_0);
    for _ in 0..4 {
        t = fe_sq(&t);
    }
    fe_mul(&t, &z11)
}

fn d_const() -> Fe {
    fe_from_bytes(&hexbytes(
        "a3785913ca4deb75abd841414d0a700098e879777940c78c73fe6f2bee6c0352",
    ))
}
fn sqrtm1() -> Fe {
    fe_from_bytes(&hexbytes(
        "b0a00e4a271beec478e42fad0618432fa7d7fb3d99004d2b0bdfc14f8024832b",
    ))
}
fn base_xy() -> (Fe, Fe) {
    (
        fe_from_bytes(&hexbytes(
            "1ad5258f602d56c9b2a7259560c72c695cdcd6fd31e2a4c0fe536ecdd3366921",
        )),
        fe_from_bytes(&hexbytes(
            "5866666666666666666666666666666666666666666666666666666666666666",
        )),
    )
}

fn hexbytes(s: &str) -> [u8; 32] {
    let mut out = [0u8; 32];
    let b = s.as_bytes();
    for i in 0..32 {
        let hi = (b[2 * i] as char).to_digit(16).unwrap() as u8;
        let lo = (b[2 * i + 1] as char).to_digit(16).unwrap() as u8;
        out[i] = (hi << 4) | lo;
    }
    out
}

// ---------- Edwards points (extended coordinates X,Y,Z,T with x=X/Z, y=Y/Z, xy=T/Z) ----------
#[derive(Clone)]
struct Pt {
    x: Fe,
    y: Fe,
    z: Fe,
    t: Fe,
}

fn pt_identity() -> Pt {
    Pt {
        x: fe_zero(),
        y: fe_one(),
        z: fe_one(),
        t: fe_zero(),
    }
}

fn pt_add(p: &Pt, q: &Pt) -> Pt {
    // unified addition (RFC 8032 / extended twisted Edwards), a = -1
    let a = fe_mul(&fe_sub(&p.y, &p.x), &fe_sub(&q.y, &q.x));
    let b = fe_mul(&fe_add(&p.y, &p.x), &fe_add(&q.y, &q.x));
    let two_d = fe_add(&d_const(), &d_const());
    let c = fe_mul(&fe_mul(&p.t, &q.t), &two_d);
    let dd = fe_mul(&fe_add(&p.z, &p.z), &q.z);
    let e = fe_sub(&b, &a);
    let f = fe_sub(&dd, &c);
    let g = fe_add(&dd, &c);
    let h = fe_add(&b, &a);
    Pt {
        x: fe_mul(&e, &f),
        y: fe_mul(&g, &h),
        t: fe_mul(&e, &h),
        z: fe_mul(&f, &g),
    }
}

fn pt_double(p: &Pt) -> Pt {
    pt_add(p, p)
}

/// [scalar]·point, scalar given little-endian (any length: 32 or 64 bytes).
fn pt_scalarmul(scalar_le: &[u8], p: &Pt) -> Pt {
    let mut r = pt_identity();
    // process bits from most significant to least
    for byte in scalar_le.iter().rev() {
        for bit in (0..8).rev() {
            r = pt_double(&r);
            if (byte >> bit) & 1 == 1 {
                r = pt_add(&r, p);
            }
        }
    }
    r
}

fn pt_eq(p: &Pt, q: &Pt) -> bool {
    // projective equality: x1*z2 == x2*z1 && y1*z2 == y2*z1
    fe_eq(&fe_mul(&p.x, &q.z), &fe_mul(&q.x, &p.z))
        && fe_eq(&fe_mul(&p.y, &q.z), &fe_mul(&q.y, &p.z))
}

/// Decompress a 32-byte point encoding (RFC 8032 §5.1.3). Returns None on a
/// non-canonical y (y >= p) or a non-square x².
fn pt_decompress(s: &[u8; 32]) -> Option<Pt> {
    let sign = (s[31] >> 7) & 1;
    let mut yb = *s;
    yb[31] &= 0x7f;
    // reject non-canonical y >= p
    {
        let mut be = [0u8; 32];
        for i in 0..32 {
            be[i] = yb[31 - i];
        }
        const P: [u8; 32] = [
            0x7f, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
            0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
            0xff, 0xff, 0xff, 0xed,
        ];
        if be >= P {
            return None;
        }
    }
    let y = fe_from_bytes(&yb);
    let y2 = fe_sq(&y);
    let u = fe_sub(&y2, &fe_one());
    let v = fe_add(&fe_mul(&d_const(), &y2), &fe_one());
    // x = u*v^3 * (u*v^7)^((p-5)/8)
    let v3 = fe_mul(&fe_sq(&v), &v);
    let v7 = fe_mul(&fe_sq(&v3), &v);
    let mut x = fe_mul(&fe_mul(&u, &v3), &fe_pow_2252m3(&fe_mul(&u, &v7)));
    // check v*x^2 == u (else multiply by sqrt(-1); else fail)
    let vx2 = fe_mul(&v, &fe_sq(&x));
    if !fe_eq(&vx2, &u) {
        if fe_eq(&vx2, &fe_neg(&u)) {
            x = fe_mul(&x, &sqrtm1());
        } else {
            return None;
        }
    }
    if fe_eq(&x, &fe_zero()) && sign == 1 {
        // x=0 with sign 1 is a non-canonical encoding (e.g. the identity point
        // 0100..0080). MUST reduce before the zero test — a strict array compare
        // misses an unreduced 0 (= p in limbs). (Gemini 3.1 Pro audit P0.)
        return None;
    }
    if fe_is_negative(&x) != (sign == 1) {
        x = fe_neg(&x);
    }
    Some(Pt {
        t: fe_mul(&x, &y),
        x,
        y,
        z: fe_one(),
    })
}

fn scalar_lt_l(s: &[u8; 32]) -> bool {
    // s < L ? compare 32-byte little-endian to L
    const L: [u8; 32] = [
        0xed, 0xd3, 0xf5, 0x5c, 0x1a, 0x63, 0x12, 0x58, 0xd6, 0x9c, 0xf7, 0xa2, 0xde, 0xf9, 0xde,
        0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x10,
    ];
    for i in (0..32).rev() {
        if s[i] < L[i] {
            return true;
        }
        if s[i] > L[i] {
            return false;
        }
    }
    false // equal is not < L
}

// L = 2^252 + 27742317777372353535851937790883648493 (Ed25519 group order)
const L4: [u64; 4] = [
    0x5812631a5cf5d3ed,
    0x14def9dea2f79cd6,
    0x0000000000000000,
    0x1000000000000000,
];

fn ge256(a: &[u64; 4], b: &[u64; 4]) -> bool {
    for i in (0..4).rev() {
        if a[i] != b[i] {
            return a[i] > b[i];
        }
    }
    true
}

fn sub256(a: &mut [u64; 4], b: &[u64; 4]) {
    let mut borrow = 0u128;
    for i in 0..4 {
        let v = (a[i] as u128).wrapping_sub(b[i] as u128).wrapping_sub(borrow);
        a[i] = v as u64;
        borrow = (v >> 127) & 1;
    }
}

/// Reduce a 64-byte little-endian value mod L (RFC 8032 scalar reduction).
/// Bit-by-bit MSB-first; the accumulator stays < L < 2^253, so [u64;4] suffices.
fn mod_l(h: &[u8; 64]) -> [u8; 32] {
    let mut r = [0u64; 4];
    for byte_i in (0..64).rev() {
        for bit in (0..8).rev() {
            // r <<= 1
            let c0 = r[0] >> 63;
            let c1 = r[1] >> 63;
            let c2 = r[2] >> 63;
            r[0] <<= 1;
            r[1] = (r[1] << 1) | c0;
            r[2] = (r[2] << 1) | c1;
            r[3] = (r[3] << 1) | c2;
            r[0] |= ((h[byte_i] >> bit) & 1) as u64;
            if ge256(&r, &L4) {
                sub256(&mut r, &L4);
            }
        }
    }
    let mut out = [0u8; 32];
    for i in 0..4 {
        out[i * 8..i * 8 + 8].copy_from_slice(&r[i].to_le_bytes());
    }
    out
}

/// RFC 8032 verify. `pk` = 32-byte public key, `sig` = 64 bytes, `msg` = message.
pub fn verify(pk: &[u8; 32], sig: &[u8; 64], msg: &[u8]) -> bool {
    let mut r_bytes = [0u8; 32];
    r_bytes.copy_from_slice(&sig[0..32]);
    let mut s_bytes = [0u8; 32];
    s_bytes.copy_from_slice(&sig[32..64]);
    if !scalar_lt_l(&s_bytes) {
        return false; // non-canonical S
    }
    let big_r = match pt_decompress(&r_bytes) {
        Some(p) => p,
        None => return false,
    };
    let a = match pt_decompress(pk) {
        Some(p) => p,
        None => return false,
    };
    // k = SHA-512(R || A || M) as a 64-byte little-endian scalar (used in full;
    // A has order L for a legitimate key, so [k]A = [k mod L]A).
    let mut buf = Vec::with_capacity(64 + msg.len());
    buf.extend_from_slice(&r_bytes);
    buf.extend_from_slice(pk);
    buf.extend_from_slice(msg);
    let k = mod_l(&sha512(&buf)); // reduce mod L for RFC-exact consensus on ALL keys
    let (bx, by) = base_xy();
    let base = Pt {
        t: fe_mul(&bx, &by),
        x: bx,
        y: by,
        z: fe_one(),
    };
    // check [S]B == R + [k]A
    let lhs = pt_scalarmul(&s_bytes, &base);
    let rhs = pt_add(&big_r, &pt_scalarmul(&k, &a));
    pt_eq(&lhs, &rhs)
}

// ---------- self-test (field + SHA-512 + a known-good verify) ----------
pub fn selftest() -> bool {
    let mut ok = true;
    let mut chk = |name: &str, cond: bool| {
        if !cond {
            eprintln!("ed25519 selftest FAIL: {name}");
            ok = false;
        }
    };
    // SHA-512("") known digest
    let empty = sha512(b"");
    let want = "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e";
    chk("sha512(empty)", local_hex(&empty) == want);
    // field round-trip and a*inv(a)=1
    let a = fe_from_bytes(&hexbytes(
        "0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f00",
    ));
    chk("fe invert", fe_eq(&fe_mul(&a, &fe_invert(&a)), &fe_one()));
    chk("fe roundtrip", fe_from_bytes(&fe_to_bytes(&a)) == a);
    // RFC 8032 test vector 1 (empty message)
    let pk = hexbytes("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a");
    let mut sig = [0u8; 64];
    sig.copy_from_slice(&{
        let mut v = [0u8; 64];
        let hx = "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b";
        for i in 0..64 {
            let hi = (hx.as_bytes()[2 * i] as char).to_digit(16).unwrap() as u8;
            let lo = (hx.as_bytes()[2 * i + 1] as char).to_digit(16).unwrap() as u8;
            v[i] = (hi << 4) | lo;
        }
        v
    });
    chk("RFC8032 TV1 verifies", verify(&pk, &sig, b""));
    // a tampered signature must fail
    let mut bad = sig;
    bad[0] ^= 1;
    chk("tampered sig rejected", !verify(&pk, &bad, b""));
    // Gemini audit P0-1: the non-canonical identity encoding (0100..0080) as R
    // MUST NOT decompress (x=0 with sign bit set).
    let mut noncanon = [0u8; 32];
    noncanon[0] = 1;
    noncanon[31] = 0x80;
    chk("non-canonical identity (0100..80) rejected", pt_decompress(&noncanon).is_none());
    // and the canonical identity (0100..00) DOES decompress
    let mut ident = [0u8; 32];
    ident[0] = 1;
    chk("canonical identity (0100..00) decompresses", pt_decompress(&ident).is_some());
    // Gemini audit P0-2: mod_l matches the reference reduction on a known vector.
    // H = all-0xff (512 bits); (2^512-1) mod L computed by the reference:
    let all_ff = [0xffu8; 64];
    let want_mod_l = hexbytes("000f9c44e31106a447938568a71b0ed065bef517d273ecce3d9a307c1b419903");
    chk("mod_l(0xff..) matches reference", mod_l(&all_ff) == want_mod_l);
    ok
}
