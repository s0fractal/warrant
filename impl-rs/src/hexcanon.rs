//! Canonical lowercase hex: the one spelling WRT-019 allows for P-256 keys and
//! signatures. Unlike `hash::fromhex` (Python's lenient `bytes.fromhex`: either
//! case, whitespace), `decode` accepts exactly the strings `encode` writes.
//!
//! The contracts below are machine-checked by Creusot (proofs/creusot/, which
//! compiles this very file). Under a normal build `cfg(creusot)` is off: the
//! attributes vanish and this is plain, dependency-free Rust.
//!
//! Proved: `encode` writes `encodes(out, bytes)`; `decode` returns `Some(b)`
//! only if `encodes(s, b)`, and `None` only if no `b` at all is encoded by `s`.
//! Since `encodes` is a function in both directions, `decode(encode(b)) ==
//! Some(b)` and `decode(s) == Some(b)` implies `s == encode(b)`: one byte
//! string, one spelling.

#[cfg(creusot)]
use creusot_std::prelude::*;

/// The ASCII code of the lowercase hex digit for `n` in 0..16.
#[cfg(creusot)]
#[logic(open)]
pub fn hex_digit(n: Int) -> Int {
    pearlite! { if n < 10 { 48 + n } else { 87 + n } }
}

/// The 4-bit value that character `k` of a spelling of `b` stands for: the
/// high half of byte `k / 2` at even `k`, the low half at odd `k`.
#[cfg(creusot)]
#[logic(open)]
pub fn nibble(b: Seq<u8>, k: Int) -> Int {
    pearlite! { if k % 2 == 0 { b[k / 2]@ / 16 } else { b[k / 2]@ % 16 } }
}

/// `s` is the canonical spelling of `b`: two lowercase digits per byte, high first.
#[cfg(creusot)]
#[logic(open)]
pub fn encodes(s: Seq<u8>, b: Seq<u8>) -> bool {
    pearlite! {
        s.len() == 2 * b.len()
        && forall<k> 0 <= k && k < s.len() ==> s[k]@ == hex_digit(nibble(b, k))
    }
}

#[cfg_attr(creusot, requires(n@ < 16))]
#[cfg_attr(creusot, ensures(result@ == hex_digit(n@)))]
fn digit(n: u8) -> u8 {
    if n < 10 {
        b'0' + n
    } else {
        b'a' - 10 + n
    }
}

#[cfg_attr(creusot, ensures(match result {
    Some(v) => v@ < 16 && hex_digit(v@) == c@,
    None => forall<v: Int> 0 <= v && v < 16 ==> hex_digit(v) != c@,
}))]
fn value(c: u8) -> Option<u8> {
    match c {
        b'0'..=b'9' => Some(c - b'0'),
        b'a'..=b'f' => Some(c - b'a' + 10),
        _ => None,
    }
}

/// Lowercase hex of `bytes`.
#[cfg_attr(creusot, requires(2 * bytes@.len() <= usize::MAX@))]
#[cfg_attr(creusot, ensures(encodes(result@, bytes@)))]
pub fn encode(bytes: &[u8]) -> Vec<u8> {
    let mut out: Vec<u8> = Vec::new();
    let mut i = 0;
    #[cfg_attr(creusot, invariant(i@ <= bytes@.len() && out@.len() == 2 * i@))]
    #[cfg_attr(creusot, invariant(forall<k> 0 <= k && k < out@.len() ==>
        out@[k]@ == hex_digit(nibble(bytes@, k))))]
    while i < bytes.len() {
        out.push(digit(bytes[i] / 16));
        out.push(digit(bytes[i] % 16));
        i += 1;
    }
    out
}

/// The bytes `s` spells, if `s` is canonical lowercase hex; otherwise `None`.
#[cfg_attr(creusot, ensures(match result {
    Some(b) => encodes(s@, b@),
    None => forall<b: Seq<u8>> !encodes(s@, b),
}))]
pub fn decode(s: &[u8]) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    let mut out: Vec<u8> = Vec::new();
    let mut i = 0;
    #[cfg_attr(creusot, invariant(2 * i@ <= s@.len() && out@.len() == i@))]
    #[cfg_attr(creusot, invariant(forall<k> 0 <= k && k < 2 * i@ ==>
        s@[k]@ == hex_digit(nibble(out@, k))))]
    while i < s.len() / 2 {
        let hi = value(s[2 * i])?;
        let lo = value(s[2 * i + 1])?;
        out.push(hi * 16 + lo);
        i += 1;
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn one_spelling() {
        assert_eq!(encode(&[0x00, 0xab, 0xff]), b"00abff".to_vec());
        assert_eq!(decode(b"00abff"), Some(vec![0x00, 0xab, 0xff]));
        assert_eq!(decode(b""), Some(vec![]));
        for bad in [&b"AB"[..], b"0", b"0g", b" a", b"a b", b"00ABff"] {
            assert_eq!(decode(bad), None, "{:?}", std::str::from_utf8(bad));
        }
        for b in 0..=255u8 {
            assert_eq!(decode(&encode(&[b])), Some(vec![b]));
        }
    }
}
