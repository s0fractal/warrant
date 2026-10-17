//! The shipped files, not copies: `hexcanon` and `bounds` below ARE
//! impl-rs/src/hexcanon.rs and impl-rs/src/bounds.rs. Their contracts are proved
//! where they stand; the two hex theorems below follow from them.
#![allow(dead_code)]

use creusot_std::prelude::*;

#[path = "../../../impl-rs/src/hexcanon.rs"]
pub mod hexcanon;

#[path = "../../../impl-rs/src/bounds.rs"]
pub mod bounds;

#[path = "../../../impl-rs/src/jcsquote.rs"]
pub mod jcsquote;

use hexcanon::{decode, encode, encodes};

/// The value of a lowercase hex digit (the inverse of `hex_digit` on 0..16).
#[logic(open)]
pub fn digit_value(c: Int) -> Int {
    pearlite! { if c < 58 { c - 48 } else { c - 87 } }
}

/// Every byte can be read back from its two characters. Stated per byte, so
/// that the provers meet `s[2 * i]` and `s[2 * i + 1]` by name.
#[logic]
#[requires(encodes(s, b))]
#[ensures(forall<i> 0 <= i && i < b.len() ==>
    b[i]@ == 16 * digit_value(s[2 * i]@) + digit_value(s[2 * i + 1]@))]
pub fn read_back(s: Seq<u8>, b: Seq<u8>) {}

/// A byte string has at most one spelling.
#[logic]
#[requires(encodes(s1, b) && encodes(s2, b))]
#[ensures(s1.ext_eq(s2))]
pub fn one_spelling(s1: Seq<u8>, s2: Seq<u8>, b: Seq<u8>) {}

/// THEOREM (round trip): decode(encode(b)) == Some(b). The `None` arm must be
/// proved unreachable, or this function could panic.
#[requires(2 * bytes@.len() <= usize::MAX@)]
#[ensures(result@ == bytes@)]
pub fn round_trip(bytes: &[u8]) -> Vec<u8> {
    let spelled = encode(bytes);
    match decode(&spelled) {
        Some(b) => {
            proof_assert! { read_back(spelled@, b@); read_back(spelled@, bytes@); b@.ext_eq(bytes@) };
            b
        }
        None => unreachable!(),
    }
}

/// THEOREM (canonicity): if decode(s) == Some(b), then encode(b) == s. No
/// second spelling of any byte string decodes.
#[ensures(match result { Some(again) => again@ == s@, None => true })]
pub fn canonical(s: &[u8]) -> Option<Vec<u8>> {
    let b = decode(s)?;
    let again = encode(&b);
    proof_assert! { one_spelling(s@, again@, b@); again@ == s@ };
    Some(again)
}
