//! The range checks that make an encoding canonical, and nothing else.
//!
//! - Ed25519 (RFC 8032): S < L, and y < p with bit 255 set aside.
//! - P-256 (WRT-019): x < p for a key; 0 < r < n and 0 < s <= n/2 for a signature.
//!
//! Signature vectors cannot see these checks: a vector that breaks one usually
//! fails some other way too (measured on warrant's Rust P-256 decoder,
//! 2026-10-16). So they are proved instead. proofs/creusot compiles this file and
//! Creusot shows that each function's result equals the numeric statement in its
//! contract. The moduli in those contracts are written in their published forms
//! (2^255 - 19, 2^252 + ..., the FIPS 186 primes), not copied from the byte
//! tables below, so the proof also checks every byte of every table.
//! Under a normal build `cfg(creusot)` is off and this is plain Rust.

#[cfg(creusot)]
use creusot_std::prelude::*;

/// The big-endian value of a byte string.
#[cfg(creusot)]
#[logic(open)]
#[variant(s.len())]
pub fn be(s: Seq<u8>) -> Int {
    pearlite! {
        if s.len() == 0 { 0 } else { be(s.subsequence(0, s.len() - 1)) * 256 + s[s.len() - 1]@ }
    }
}

/// The little-endian value of a byte string.
#[cfg(creusot)]
#[logic(open)]
pub fn le(s: Seq<u8>) -> Int {
    pearlite! { be(s.reverse()) }
}

/// 2^64. Pearlite literals stop at i128, so the moduli are built from it.
#[cfg(creusot)]
#[logic(open)]
pub fn w() -> Int {
    pearlite! { 18446744073709551616 }
}

#[cfg(creusot)]
#[logic(open)]
pub fn ed25519_l() -> Int {
    // 2^252 + 27742317777372353535851937790883648493 (RFC 8032), as 2^124 * w^2 + c:
    // provers evaluate products of literals, not `pow`.
    pearlite! { 21267647932558653966460912964485513216 * w() * w() + 27742317777372353535851937790883648493 }
}

#[cfg(creusot)]
#[logic(open)]
pub fn ed25519_p() -> Int {
    // 2^255 - 19 = 2^63 * w^3 - 19
    pearlite! { 9223372036854775808 * w() * w() * w() - 19 }
}

#[cfg(creusot)]
#[logic(open)]
pub fn p256_p() -> Int {
    // 2^256 - 2^224 + 2^192 + 2^96 - 1, with w = 2^64
    pearlite! {
        w() * w() * w() * w() - 4294967296 * w() * w() * w()
        + w() * w() * w() + 4294967296 * w() - 1
    }
}

#[cfg(creusot)]
#[logic(open)]
pub fn p256_n() -> Int {
    // 115792089210356248762697446949407573529996955224135760342422259061068512044369
    // (FIPS 186-5) = 2^256 - 2^224 + 2^192 - c, with w = 2^64
    pearlite! {
        w() * w() * w() * w() - 4294967296 * w() * w() * w()
        + w() * w() * w() - 89188191075325690597107910205041859247
    }
}

/// The same value, by index (Horner form): `hb(s, k) == be(s[..k])`.
#[cfg(creusot)]
#[logic(open)]
#[variant(k)]
pub fn hb(s: Seq<u8>, k: Int) -> Int {
    pearlite! { if k <= 0 { 0 } else { hb(s, k - 1) * 256 + s[k - 1]@ } }
}

#[cfg(creusot)]
#[logic]
#[requires(0 <= j && j <= k && k <= s.len())]
#[ensures(s.subsequence(0, k).subsequence(0, j) == s.subsequence(0, j))]
pub fn sub_sub(s: Seq<u8>, j: Int, k: Int) {}

/// One more byte: `be(s[..k]) == be(s[..k-1]) * 256 + s[k-1]`.
#[cfg(creusot)]
#[logic]
#[requires(0 < k && k <= s.len())]
#[ensures(be(s.subsequence(0, k)) == be(s.subsequence(0, k - 1)) * 256 + s[k - 1]@)]
pub fn be_step(s: Seq<u8>, k: Int) {
    pearlite! { sub_sub(s, k - 1, k) }
}

#[cfg(creusot)]
#[logic]
#[requires(0 <= k && k <= s.len())]
#[ensures(be(s.subsequence(0, k)) == hb(s, k))]
#[variant(k)]
pub fn be_is_hb(s: Seq<u8>, k: Int) {
    pearlite! { if k > 0 { be_is_hb(s, k - 1); be_step(s, k) } }
}

#[cfg(creusot)]
#[logic]
#[ensures(s.subsequence(0, s.len()) == s)]
pub fn sub_all(s: Seq<u8>) {}

/// A prefix that is already smaller stays smaller, whatever follows.
#[cfg(creusot)]
#[logic]
#[requires(a.len() == b.len() && 0 <= m && m <= k && k <= a.len())]
#[requires(be(a.subsequence(0, m)) < be(b.subsequence(0, m)))]
#[ensures(be(a.subsequence(0, k)) < be(b.subsequence(0, k)))]
#[variant(k - m)]
pub fn lt_extends(a: Seq<u8>, b: Seq<u8>, m: Int, k: Int) {
    pearlite! { if m < k { lt_extends(a, b, m, k - 1); be_step(a, k); be_step(b, k) } }
}

/// `a < b` as big-endian numbers of the same length.
#[cfg_attr(creusot, requires(a@.len() == b@.len()))]
#[cfg_attr(creusot, ensures(result == (be(a@) < be(b@))))]
pub fn lt_be(a: &[u8], b: &[u8]) -> bool {
    let mut i = 0;
    #[cfg_attr(creusot, invariant(i@ <= a@.len()))]
    #[cfg_attr(creusot, invariant(be(a@.subsequence(0, i@)) == be(b@.subsequence(0, i@))))]
    while i < a.len() {
        if a[i] != b[i] {
            #[cfg(creusot)]
            proof_assert! {
                a@.subsequence(0, i@ + 1).subsequence(0, i@) == a@.subsequence(0, i@)
                && b@.subsequence(0, i@ + 1).subsequence(0, i@) == b@.subsequence(0, i@)
            };
            #[cfg(creusot)]
            proof_assert! { a@.subsequence(0, a@.len()) == a@ && b@.subsequence(0, b@.len()) == b@ };
            #[cfg(creusot)]
            proof_assert! { lt_extends(a@, b@, i@ + 1, a@.len()); lt_extends(b@, a@, i@ + 1, a@.len()); true };
            return a[i] < b[i];
        }
        #[cfg(creusot)]
        proof_assert! {
            a@.subsequence(0, i@ + 1).subsequence(0, i@) == a@.subsequence(0, i@)
            && b@.subsequence(0, i@ + 1).subsequence(0, i@) == b@.subsequence(0, i@)
        };
        i += 1;
    }
    #[cfg(creusot)]
    proof_assert! { a@.subsequence(0, a@.len()) == a@ && b@.subsequence(0, b@.len()) == b@ };
    false
}

/// The 32 bytes in reverse order: a little-endian number as a big-endian one.
#[cfg_attr(creusot, ensures(result@ == s@.reverse()))]
fn reversed(s: &[u8; 32]) -> [u8; 32] {
    let mut out = [0u8; 32];
    let mut i = 0;
    #[cfg_attr(creusot, invariant(i@ <= 32))]
    #[cfg_attr(creusot, invariant(forall<j> 0 <= j && j < i@ ==> out@[j] == s@[31 - j]))]
    while i < 32 {
        out[i] = s[31 - i];
        i += 1;
    }
    #[cfg(creusot)]
    proof_assert! { out@.ext_eq(s@.reverse()) };
    out
}

const ED25519_L_BE: [u8; 32] = [
    0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x14, 0xde, 0xf9, 0xde, 0xa2, 0xf7, 0x9c, 0xd6, 0x58, 0x12, 0x63, 0x1a, 0x5c, 0xf5, 0xd3, 0xed,
];
const ED25519_P_BE: [u8; 32] = [
    0x7f, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
    0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xed,
];
const P256_P_BE: [u8; 32] = [
    0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
];
const P256_N_BE: [u8; 32] = [
    0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
    0xbc, 0xe6, 0xfa, 0xad, 0xa7, 0x17, 0x9e, 0x84, 0xf3, 0xb9, 0xca, 0xc2, 0xfc, 0x63, 0x25, 0x51,
];
const P256_HALF_N_BE: [u8; 32] = [
    0x7f, 0xff, 0xff, 0xff, 0x80, 0x00, 0x00, 0x00, 0x7f, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
    0xde, 0x73, 0x7d, 0x56, 0xd3, 0x8b, 0xcf, 0x42, 0x79, 0xdc, 0xe5, 0x61, 0x7e, 0x31, 0x92, 0xa8,
];
const ZERO: [u8; 32] = [0; 32];

// Each table is bound to a local before the proof talks about it: Creusot knows a
// constant's bytes only where the program evaluates it.

/// RFC 8032 §5.1.7: a signature's S, read little-endian, is below the group order L.
#[cfg_attr(creusot, ensures(result == (le(s@) < ed25519_l())))]
pub fn ed25519_scalar_canonical(s: &[u8; 32]) -> bool {
    let l = ED25519_L_BE;
    #[cfg(creusot)]
    proof_assert! { hb(l@, 8) == 1152921504606846976 };
    #[cfg(creusot)]
    proof_assert! { hb(l@, 16) == 1152921504606846976 * w() + 0 };
    #[cfg(creusot)]
    proof_assert! { hb(l@, 24) == (1152921504606846976 * w() + 0) * w() + 1503914060200516822 };
    #[cfg(creusot)]
    proof_assert! { hb(l@, 32) == ((1152921504606846976 * w() + 0) * w() + 1503914060200516822) * w() + 6346243789798364141 };
    #[cfg(creusot)]
    proof_assert! { hb(l@, 32) == ed25519_l() };
    #[cfg(creusot)]
    proof_assert! { be_is_hb(l@, 32); sub_all(l@); be(l@) == ed25519_l() };
    lt_be(&reversed(s), &l)
}

/// RFC 8032 §5.1.3: the y of a point encoding is below p. In the RFC's words, y is
/// the encoding read little-endian after bit 255 (the sign of x) is cleared: `y`
/// below is every byte string that agrees with `s` except for that bit.
#[cfg_attr(creusot, ensures(forall<y: Seq<u8>>
    y.len() == 32 && y[31]@ == s@[31]@ % 128 && (forall<i> 0 <= i && i < 31 ==> y[i] == s@[i])
    ==> result == (le(y) < ed25519_p())))]
pub fn ed25519_y_canonical(s: &[u8; 32]) -> bool {
    let p = ED25519_P_BE;
    #[cfg(creusot)]
    proof_assert! { hb(p@, 8) == 9223372036854775807 };
    #[cfg(creusot)]
    proof_assert! { hb(p@, 16) == 9223372036854775807 * w() + 18446744073709551615 };
    #[cfg(creusot)]
    proof_assert! { hb(p@, 24) == (9223372036854775807 * w() + 18446744073709551615) * w() + 18446744073709551615 };
    #[cfg(creusot)]
    proof_assert! { hb(p@, 32) == ((9223372036854775807 * w() + 18446744073709551615) * w() + 18446744073709551615) * w() + 18446744073709551597 };
    #[cfg(creusot)]
    proof_assert! { hb(p@, 32) == ed25519_p() };
    #[cfg(creusot)]
    proof_assert! { be_is_hb(p@, 32); sub_all(p@); be(p@) == ed25519_p() };
    let mut y = *s;
    y[31] %= 128;
    #[cfg(creusot)]
    proof_assert! { forall<z: Seq<u8>> z.len() == 32 && z[31]@ == s@[31]@ % 128
    && (forall<i> 0 <= i && i < 31 ==> z[i] == s@[i]) ==> z.ext_eq(y@) };
    lt_be(&reversed(&y), &p)
}

/// WRT-019: the x of a compressed P-256 key (32 bytes, big-endian) is below p.
#[cfg_attr(creusot, requires(x@.len() == 32))]
#[cfg_attr(creusot, ensures(result == (be(x@) < p256_p())))]
pub fn p256_x_in_range(x: &[u8]) -> bool {
    let p = P256_P_BE;
    #[cfg(creusot)]
    proof_assert! { hb(p@, 8) == 18446744069414584321 };
    #[cfg(creusot)]
    proof_assert! { hb(p@, 16) == 18446744069414584321 * w() + 0 };
    #[cfg(creusot)]
    proof_assert! { hb(p@, 24) == (18446744069414584321 * w() + 0) * w() + 4294967295 };
    #[cfg(creusot)]
    proof_assert! { hb(p@, 32) == ((18446744069414584321 * w() + 0) * w() + 4294967295) * w() + 18446744073709551615 };
    #[cfg(creusot)]
    proof_assert! { hb(p@, 32) == p256_p() };
    #[cfg(creusot)]
    proof_assert! { be_is_hb(p@, 32); sub_all(p@); be(p@) == p256_p() };
    lt_be(x, &p)
}

/// WRT-019: a 64-byte r || s has 0 < r < n and 0 < s <= n/2 (low-S).
#[cfg_attr(creusot, requires(sig@.len() == 64))]
#[cfg_attr(creusot, ensures(result == (
    0 < be(sig@.subsequence(0, 32)) && be(sig@.subsequence(0, 32)) < p256_n()
    && 0 < be(sig@.subsequence(32, 64)) && be(sig@.subsequence(32, 64)) <= p256_n() / 2)))]
pub fn p256_sig_in_range(sig: &[u8]) -> bool {
    let (n, half_n, zero) = (P256_N_BE, P256_HALF_N_BE, ZERO);
    #[cfg(creusot)]
    proof_assert! { hb(n@, 8) == 18446744069414584320 };
    #[cfg(creusot)]
    proof_assert! { hb(n@, 16) == 18446744069414584320 * w() + 18446744073709551615 };
    #[cfg(creusot)]
    proof_assert! { hb(n@, 24) == (18446744069414584320 * w() + 18446744073709551615) * w() + 13611842547513532036 };
    #[cfg(creusot)]
    proof_assert! { hb(n@, 32) == ((18446744069414584320 * w() + 18446744073709551615) * w() + 13611842547513532036) * w() + 17562291160714782033 };
    #[cfg(creusot)]
    proof_assert! { hb(n@, 32) == p256_n() };
    #[cfg(creusot)]
    proof_assert! { be_is_hb(n@, 32); sub_all(n@); be(n@) == p256_n() };
    #[cfg(creusot)]
    proof_assert! { hb(half_n@, 8) == 9223372034707292160 };
    #[cfg(creusot)]
    proof_assert! { hb(half_n@, 16) == 9223372034707292160 * w() + 9223372036854775807 };
    #[cfg(creusot)]
    proof_assert! { hb(half_n@, 24) == (9223372034707292160 * w() + 9223372036854775807) * w() + 16029293310611541826 };
    #[cfg(creusot)]
    proof_assert! { hb(half_n@, 32) == ((9223372034707292160 * w() + 9223372036854775807) * w() + 16029293310611541826) * w() + 8781145580357391016 };
    #[cfg(creusot)]
    proof_assert! { hb(half_n@, 32) == p256_n() / 2 };
    #[cfg(creusot)]
    proof_assert! { be_is_hb(half_n@, 32); sub_all(half_n@); be(half_n@) == p256_n() / 2 };
    #[cfg(creusot)]
    proof_assert! { hb(zero@, 8) == 0 };
    #[cfg(creusot)]
    proof_assert! { hb(zero@, 16) == 0 * w() + 0 };
    #[cfg(creusot)]
    proof_assert! { hb(zero@, 24) == (0 * w() + 0) * w() + 0 };
    #[cfg(creusot)]
    proof_assert! { hb(zero@, 32) == ((0 * w() + 0) * w() + 0) * w() + 0 };
    #[cfg(creusot)]
    proof_assert! { hb(zero@, 32) == 0 };
    #[cfg(creusot)]
    proof_assert! { be_is_hb(zero@, 32); sub_all(zero@); be(zero@) == 0 };
    let (r, s) = sig.split_at(32);
    lt_be(&zero, r) && lt_be(r, &n) && lt_be(&zero, s) && !lt_be(&half_n, s)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn edges() {
        let mut l = ED25519_L_BE;
        l.reverse();
        assert!(!ed25519_scalar_canonical(&l));
        l[0] -= 1;
        assert!(ed25519_scalar_canonical(&l));
        let mut p = ED25519_P_BE;
        p.reverse();
        assert!(!ed25519_y_canonical(&p));
        p[31] |= 0x80; // the sign bit is not part of y
        assert!(!ed25519_y_canonical(&p));
        p[0] -= 1;
        assert!(ed25519_y_canonical(&p));
        assert!(!p256_x_in_range(&P256_P_BE));
        let mut sig = [0u8; 64];
        sig[..32].copy_from_slice(&P256_N_BE);
        sig[32..].copy_from_slice(&P256_HALF_N_BE);
        assert!(!p256_sig_in_range(&sig)); // r = n
        sig[31] -= 1;
        assert!(p256_sig_in_range(&sig)); // r = n - 1, s = n/2
        sig[63] += 1;
        assert!(!p256_sig_in_range(&sig)); // s = n/2 + 1: high S
    }
}
