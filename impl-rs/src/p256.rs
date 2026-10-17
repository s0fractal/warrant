//! WRT-019: ECDSA P-256 / SHA-256 verification, written from scratch like the
//! rest of this crate (no external crates), so that agreement with the Python
//! (`cryptography`) and Go (`crypto/ecdsa`) verifiers is evidence about the
//! specification rather than about a shared library.
//!
//! Verification only. Every input is public, so nothing here aims for constant
//! time. Arithmetic is Montgomery multiplication over four little-endian 64-bit
//! limbs, shared by the field (mod p) and the scalars (mod n). Points use
//! Jacobian coordinates with the a = -3 formulas.

use crate::hash::sha256;
use std::cmp::Ordering;

type U = [u64; 4];

const P: U = [
    0xFFFF_FFFF_FFFF_FFFF,
    0x0000_0000_FFFF_FFFF,
    0,
    0xFFFF_FFFF_0000_0001,
];
const N: U = [
    0xF3B9_CAC2_FC63_2551,
    0xBCE6_FAAD_A717_9E84,
    0xFFFF_FFFF_FFFF_FFFF,
    0xFFFF_FFFF_0000_0000,
];
const B: U = [
    0x3BCE_3C3E_27D2_604B,
    0x651D_06B0_CC53_B0F6,
    0xB3EB_BD55_7698_86BC,
    0x5AC6_35D8_AA3A_93E7,
];
const GX: U = [
    0xF4A1_3945_D898_C296,
    0x7703_7D81_2DEB_33A0,
    0xF8BC_E6E5_63A4_40F2,
    0x6B17_D1F2_E12C_4247,
];
const GY: U = [
    0xCBB6_4068_37BF_51F5,
    0x2BCE_3357_6B31_5ECE,
    0x8EE7_EB4A_7C0F_9E16,
    0x4FE3_42E2_FE1A_7F9B,
];

fn cmp(a: &U, b: &U) -> Ordering {
    for i in (0..4).rev() {
        match a[i].cmp(&b[i]) {
            Ordering::Equal => continue,
            o => return o,
        }
    }
    Ordering::Equal
}

fn is_zero(a: &U) -> bool {
    a.iter().all(|&x| x == 0)
}

fn add(a: &U, b: &U) -> (U, bool) {
    let mut r = [0u64; 4];
    let mut c = false;
    for i in 0..4 {
        let (s1, o1) = a[i].overflowing_add(b[i]);
        let (s2, o2) = s1.overflowing_add(c as u64);
        r[i] = s2;
        c = o1 || o2;
    }
    (r, c)
}

fn sub(a: &U, b: &U) -> (U, bool) {
    let mut r = [0u64; 4];
    let mut bw = false;
    for i in 0..4 {
        let (d1, o1) = a[i].overflowing_sub(b[i]);
        let (d2, o2) = d1.overflowing_sub(bw as u64);
        r[i] = d2;
        bw = o1 || o2;
    }
    (r, bw)
}

fn from_be(b: &[u8]) -> U {
    let mut r = [0u64; 4];
    for (i, limb) in r.iter_mut().enumerate() {
        let off = 32 - 8 * (i + 1);
        let mut w = [0u8; 8];
        w.copy_from_slice(&b[off..off + 8]);
        *limb = u64::from_be_bytes(w);
    }
    r
}

fn bit(a: &U, i: usize) -> bool {
    (a[i / 64] >> (i % 64)) & 1 == 1
}

/// acc + x*y + c, as (low, high) 64-bit halves. Never overflows u128.
fn mac(acc: u64, x: u64, y: u64, c: u64) -> (u64, u64) {
    let v = acc as u128 + (x as u128) * (y as u128) + c as u128;
    (v as u64, (v >> 64) as u64)
}

/// Arithmetic modulo an odd 256-bit modulus m > 2^255, in Montgomery form.
struct Mont {
    m: U,
    minv: u64, // -m^-1 mod 2^64
    r2: U,     // R^2 mod m, R = 2^256
    one: U,    // R mod m
}

impl Mont {
    fn new(m: U) -> Mont {
        let mut inv: u64 = 1;
        for _ in 0..6 {
            inv = inv.wrapping_mul(2u64.wrapping_sub(m[0].wrapping_mul(inv)));
        }
        let one = sub(&[0; 4], &m).0; // 2^256 - m = R mod m, since m > 2^255
        let mut mont = Mont {
            m,
            minv: inv.wrapping_neg(),
            r2: [0; 4],
            one,
        };
        let mut x = one;
        for _ in 0..256 {
            x = mont.add(&x, &x);
        }
        mont.r2 = x;
        mont
    }
    fn add(&self, a: &U, b: &U) -> U {
        let (s, c) = add(a, b);
        if c || cmp(&s, &self.m) != Ordering::Less {
            sub(&s, &self.m).0
        } else {
            s
        }
    }
    fn sub(&self, a: &U, b: &U) -> U {
        let (d, bw) = sub(a, b);
        if bw {
            add(&d, &self.m).0
        } else {
            d
        }
    }
    fn mul(&self, a: &U, b: &U) -> U {
        let m = &self.m;
        let mut t = [0u64; 6];
        for bi in b.iter() {
            let mut c = 0u64;
            for j in 0..4 {
                let (lo, hi) = mac(t[j], a[j], *bi, c);
                t[j] = lo;
                c = hi;
            }
            let (s, o) = t[4].overflowing_add(c);
            t[4] = s;
            t[5] = o as u64;
            let q = t[0].wrapping_mul(self.minv);
            let (_, mut c) = mac(t[0], q, m[0], 0);
            for j in 1..4 {
                let (lo, hi) = mac(t[j], q, m[j], c);
                t[j - 1] = lo;
                c = hi;
            }
            let (s, o) = t[4].overflowing_add(c);
            t[3] = s;
            t[4] = t[5] + o as u64;
        }
        let r = [t[0], t[1], t[2], t[3]];
        if t[4] != 0 || cmp(&r, m) != Ordering::Less {
            sub(&r, m).0
        } else {
            r
        }
    }
    fn to(&self, a: &U) -> U {
        self.mul(a, &self.r2)
    }
    fn from(&self, a: &U) -> U {
        self.mul(a, &[1, 0, 0, 0])
    }
    fn pow(&self, a: &U, e: &U) -> U {
        let mut r = self.one;
        for i in (0..256).rev() {
            r = self.mul(&r, &r);
            if bit(e, i) {
                r = self.mul(&r, a);
            }
        }
        r
    }
    fn inv(&self, a: &U) -> U {
        self.pow(a, &sub(&self.m, &[2, 0, 0, 0]).0)
    }
}

/// A point in Jacobian coordinates over the field in Montgomery form; Z = 0 is infinity.
#[derive(Clone, Copy)]
struct Pt {
    x: U,
    y: U,
    z: U,
}

struct Curve {
    f: Mont,
}

impl Curve {
    fn new() -> Curve {
        Curve { f: Mont::new(P) }
    }
    fn inf(&self) -> Pt {
        Pt {
            x: self.f.one,
            y: self.f.one,
            z: [0; 4],
        }
    }
    fn affine(&self, x: &U, y: &U) -> Pt {
        Pt {
            x: self.f.to(x),
            y: self.f.to(y),
            z: self.f.one,
        }
    }
    fn double(&self, p: &Pt) -> Pt {
        let f = &self.f;
        if is_zero(&p.z) || is_zero(&p.y) {
            return self.inf();
        }
        // dbl-2001-b, a = -3
        let delta = f.mul(&p.z, &p.z);
        let gamma = f.mul(&p.y, &p.y);
        let beta = f.mul(&p.x, &gamma);
        let t = f.mul(&f.sub(&p.x, &delta), &f.add(&p.x, &delta));
        let alpha = f.add(&f.add(&t, &t), &t);
        let beta4 = f.add(&f.add(&beta, &beta), &f.add(&beta, &beta));
        let beta8 = f.add(&beta4, &beta4);
        let x3 = f.sub(&f.mul(&alpha, &alpha), &beta8);
        let yz = f.add(&p.y, &p.z);
        let z3 = f.sub(&f.sub(&f.mul(&yz, &yz), &gamma), &delta);
        let g2 = f.mul(&gamma, &gamma);
        let g8 = {
            let g2x2 = f.add(&g2, &g2);
            let g2x4 = f.add(&g2x2, &g2x2);
            f.add(&g2x4, &g2x4)
        };
        let y3 = f.sub(&f.mul(&alpha, &f.sub(&beta4, &x3)), &g8);
        Pt {
            x: x3,
            y: y3,
            z: z3,
        }
    }
    fn add(&self, p: &Pt, q: &Pt) -> Pt {
        let f = &self.f;
        if is_zero(&p.z) {
            return *q;
        }
        if is_zero(&q.z) {
            return *p;
        }
        // add-2007-bl
        let z1z1 = f.mul(&p.z, &p.z);
        let z2z2 = f.mul(&q.z, &q.z);
        let u1 = f.mul(&p.x, &z2z2);
        let u2 = f.mul(&q.x, &z1z1);
        let s1 = f.mul(&f.mul(&p.y, &q.z), &z2z2);
        let s2 = f.mul(&f.mul(&q.y, &p.z), &z1z1);
        if u1 == u2 {
            return if s1 == s2 { self.double(p) } else { self.inf() };
        }
        let h = f.sub(&u2, &u1);
        let h2 = f.add(&h, &h);
        let i = f.mul(&h2, &h2);
        let j = f.mul(&h, &i);
        let r = {
            let d = f.sub(&s2, &s1);
            f.add(&d, &d)
        };
        let v = f.mul(&u1, &i);
        let x3 = f.sub(&f.sub(&f.mul(&r, &r), &j), &f.add(&v, &v));
        let s1j = f.mul(&s1, &j);
        let y3 = f.sub(&f.mul(&r, &f.sub(&v, &x3)), &f.add(&s1j, &s1j));
        let zz = f.add(&p.z, &q.z);
        let z3 = f.mul(&f.sub(&f.sub(&f.mul(&zz, &zz), &z1z1), &z2z2), &h);
        Pt {
            x: x3,
            y: y3,
            z: z3,
        }
    }
    fn mul(&self, k: &U, p: &Pt) -> Pt {
        let mut r = self.inf();
        for i in (0..256).rev() {
            r = self.double(&r);
            if bit(k, i) {
                r = self.add(&r, p);
            }
        }
        r
    }
    /// The affine x of a non-infinite point, in normal (not Montgomery) form.
    fn x_affine(&self, p: &Pt) -> U {
        let f = &self.f;
        let zi = f.inv(&p.z);
        f.from(&f.mul(&p.x, &f.mul(&zi, &zi)))
    }
    /// SEC1 compressed point → affine (x, y), or None if not on the curve.
    fn decompress(&self, key: &[u8]) -> Option<(U, U)> {
        if key.len() != 33 || (key[0] != 2 && key[0] != 3) {
            return None;
        }
        if !crate::bounds::p256_x_in_range(&key[1..]) {
            return None;
        }
        let x = from_be(&key[1..]);
        let f = &self.f;
        let xm = f.to(&x);
        let x3 = f.mul(&f.mul(&xm, &xm), &xm);
        let three_x = f.add(&f.add(&xm, &xm), &xm);
        let rhs = f.add(&f.sub(&x3, &three_x), &f.to(&B));
        // p = 3 mod 4: a square root is rhs^((p+1)/4).
        let e = {
            let (p1, _) = add(&P, &[1, 0, 0, 0]);
            [
                p1[0] >> 2 | p1[1] << 62,
                p1[1] >> 2 | p1[2] << 62,
                p1[2] >> 2 | p1[3] << 62,
                p1[3] >> 2,
            ]
        };
        let ym = f.pow(&rhs, &e);
        if f.mul(&ym, &ym) != rhs {
            return None; // x^3 - 3x + b is not a square: no point with this x
        }
        let mut y = f.from(&ym);
        if (y[0] & 1) as u8 != key[0] & 1 {
            y = sub(&P, &y).0;
        }
        Some((x, y))
    }
}

/// WRT-019: the affine point of a compressed SEC1 key (33 bytes), as 32-byte
/// big-endian x and y, or None if it is not one encoding of a point on P-256.
pub fn decode_compressed(key: &[u8]) -> Option<([u8; 32], [u8; 32])> {
    let (x, y) = Curve::new().decompress(key)?;
    let be = |v: &U| {
        let mut out = [0u8; 32];
        for i in 0..4 {
            out[8 * i..8 * i + 8].copy_from_slice(&v[3 - i].to_be_bytes());
        }
        out
    };
    Some((be(&x), be(&y)))
}

/// WRT-019: true iff `sig` (64-byte r||s) is a valid low-S ECDSA P-256 / SHA-256
/// signature of `msg` under the compressed SEC1 key `key` (33 bytes).
pub fn verify(key: &[u8], sig: &[u8], msg: &[u8]) -> bool {
    if sig.len() != 64 {
        return false;
    }
    // 0 < r < n and 0 < s <= n/2 (low-S), proved in crate::bounds
    if !crate::bounds::p256_sig_in_range(sig) {
        return false;
    }
    let r = from_be(&sig[..32]);
    let s = from_be(&sig[32..]);
    let c = Curve::new();
    let Some((qx, qy)) = c.decompress(key) else {
        return false;
    };
    let sc = Mont::new(N);
    let mut e = from_be(&sha256(msg));
    if cmp(&e, &N) != Ordering::Less {
        e = sub(&e, &N).0;
    }
    let w = sc.inv(&sc.to(&s));
    let u1 = sc.from(&sc.mul(&sc.to(&e), &w));
    let u2 = sc.from(&sc.mul(&sc.to(&r), &w));
    let sum = c.add(
        &c.mul(&u1, &c.affine(&GX, &GY)),
        &c.mul(&u2, &c.affine(&qx, &qy)),
    );
    if is_zero(&sum.z) {
        return false;
    }
    let mut x = c.x_affine(&sum);
    if cmp(&x, &N) != Ordering::Less {
        x = sub(&x, &N).0;
    }
    x == r
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(s: &str) -> Vec<u8> {
        crate::hash::fromhex(s).unwrap()
    }

    #[test]
    fn generator_is_on_the_curve_and_n_g_is_infinity() {
        let c = Curve::new();
        let g = c.affine(&GX, &GY);
        assert!(is_zero(&c.mul(&N, &g).z));
        let two_g = c.double(&g);
        assert!(!is_zero(&two_g.z));
        // compressed G round-trips
        let mut key = vec![if GY[0] & 1 == 1 { 3u8 } else { 2 }];
        for i in (0..4).rev() {
            key.extend_from_slice(&GX[i].to_be_bytes());
        }
        assert_eq!(c.decompress(&key), Some((GX, GY)));
    }

    #[test]
    fn field_inverse_and_montgomery_round_trip() {
        let f = Mont::new(P);
        let a = f.to(&[12345, 0, 0, 1]);
        assert_eq!(f.from(&f.mul(&a, &f.inv(&a))), [1, 0, 0, 0]);
        let s = Mont::new(N);
        let b = s.to(&[7, 0, 0, 0]);
        assert_eq!(s.from(&s.mul(&b, &s.inv(&b))), [1, 0, 0, 0]);
    }

    #[test]
    fn decompress_accepts_one_encoding_per_point() {
        let c = Curve::new();
        let key = |prefix: u8, x: &U| {
            let mut k = vec![prefix];
            for i in (0..4).rev() {
                k.extend_from_slice(&x[i].to_be_bytes());
            }
            k
        };
        // x = 0 is on P-256 (b is a square mod p); x = p is the same x written
        // as an alias, and must not decode (two strings, one key).
        assert!(c.decompress(&key(2, &[0; 4])).is_some());
        assert!(c.decompress(&key(2, &P)).is_none(), "x = p aliases x = 0");
        // x = 1: 1 - 3 + b is not a square mod p, so no point has this x.
        assert!(
            c.decompress(&key(2, &[1, 0, 0, 0])).is_none(),
            "off the curve"
        );
        for prefix in [0u8, 1, 4, 5, 6, 7] {
            assert!(
                c.decompress(&key(prefix, &[0; 4])).is_none(),
                "prefix {prefix}"
            );
        }
        assert!(c.decompress(&key(2, &[0; 4])[..32]).is_none(), "32 bytes");
    }

    #[test]
    fn a_known_signature_verifies_and_its_mutations_do_not() {
        // Python `cryptography`, RFC 6979, key = SHA-256("impl-rs p256 unit test") mod n,
        // message "abc", s normalized low.
        let key = hex("030e6e031c48347433683a22ef38e672aadc8db04b298ffe29ba17a6c02599f46f");
        let r = hex("c99303ecb470d03371a47168ebe1a7b0f38acf5b9617ba06917df764e607665b");
        let s_low = hex("7edea9c9247756e35ae5555437b6b425aff59afdfa09b545dacde04ce8c703aa");
        let s_high = hex("81215635db88a91da51aaaabc8494bda0cf15fafad0de93f18ebea76139c21a7");
        let sig = [r.clone(), s_low.clone()].concat();
        assert!(verify(&key, &sig, b"abc"));
        assert!(!verify(&key, &sig, b"abd"), "another message");
        assert!(
            !verify(&key, &[r.clone(), s_high].concat(), b"abc"),
            "high-S"
        );
        let mut flipped = key.clone();
        flipped[0] ^= 1; // the other y: a different point
        assert!(!verify(&flipped, &sig, b"abc"), "wrong parity");
        let mut bad_r = sig.clone();
        bad_r[31] ^= 1;
        assert!(!verify(&key, &bad_r, b"abc"), "r changed");
    }
}
