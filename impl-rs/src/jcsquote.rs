//! JCS string quoting (RFC 8785 §3.2.2.2) over code units, as SPEC §4 uses it.
//!
//! `"` and `\` are escaped, the five controls with short forms get them
//! (\b \t \n \f \r), the other controls below U+0020 become \u00xx in lowercase
//! hex, and every other unit passes through unchanged (lone surrogates included,
//! as `json.dumps(ensure_ascii=False)` passes them; `canon` refuses those later).
//!
//! proofs/creusot compiles this file. It proves that `quote_units` appends
//! exactly `quoted(s)`, and that a quoted string is SELF-DELIMITING:
//! `quoted(s) ++ x == quoted(t) ++ y` implies `s == t` and `x == y`. So whatever
//! text follows a string in the canonical form, no two different strings can
//! produce the same bytes. Under a normal build `cfg(creusot)` is off and this is
//! plain Rust.

#[cfg(creusot)]
use creusot_std::prelude::*;

/// Lowercase hex digit of `n` in 0..16, as a code unit.
#[cfg(creusot)]
#[logic(open)]
pub fn hex_unit(n: u32) -> u32 {
    pearlite! { if n < 10u32 { n + 48u32 } else { n + 87u32 } }
}

/// The units one source unit becomes. (A control below 0x20 has high digit 0 or 1.)
#[cfg(creusot)]
#[logic(open)]
pub fn esc(u: u32) -> Seq<u32> {
    pearlite! {
        if u == 0x22u32 { Seq::singleton(0x5cu32).concat(Seq::singleton(0x22u32)) }
        else if u == 0x5cu32 { Seq::singleton(0x5cu32).concat(Seq::singleton(0x5cu32)) }
        else if u == 0x08u32 { Seq::singleton(0x5cu32).concat(Seq::singleton(0x62u32)) }
        else if u == 0x09u32 { Seq::singleton(0x5cu32).concat(Seq::singleton(0x74u32)) }
        else if u == 0x0au32 { Seq::singleton(0x5cu32).concat(Seq::singleton(0x6eu32)) }
        else if u == 0x0cu32 { Seq::singleton(0x5cu32).concat(Seq::singleton(0x66u32)) }
        else if u == 0x0du32 { Seq::singleton(0x5cu32).concat(Seq::singleton(0x72u32)) }
        else if u < 0x20u32 {
            Seq::singleton(0x5cu32).concat(Seq::singleton(0x75u32))
                .concat(Seq::singleton(0x30u32)).concat(Seq::singleton(0x30u32))
                .concat(Seq::singleton(if u < 16u32 { 0x30u32 } else { 0x31u32 }))
                .concat(Seq::singleton(if u < 16u32 { hex_unit(u) } else { hex_unit(u - 16u32) }))
        }
        else { Seq::singleton(u) }
    }
}

/// The escaped units of `s`, without the quotes.
#[cfg(creusot)]
#[logic(open)]
#[variant(s.len())]
pub fn body(s: Seq<u32>) -> Seq<u32> {
    pearlite! { if s.len() == 0 { Seq::empty() } else { esc(s[0]).concat(body(s.tail())) } }
}

/// The JCS spelling of `s`: `"` ++ body(s) ++ `"`.
#[cfg(creusot)]
#[logic(open)]
pub fn quoted(s: Seq<u32>) -> Seq<u32> {
    pearlite! { Seq::singleton(0x22u32).concat(body(s)).concat(Seq::singleton(0x22u32)) }
}

#[cfg(creusot)]
#[logic]
#[requires(a.len() > 0)]
#[ensures(a.concat(b).tail() == a.tail().concat(b) && a.concat(b)[0] == a[0])]
pub fn tail_concat(a: Seq<u32>, b: Seq<u32>) {}

#[cfg(creusot)]
#[logic]
#[requires(a.len() == 0)]
#[ensures(a.concat(b) == b)]
pub fn empty_concat(a: Seq<u32>, b: Seq<u32>) {}

/// `body` distributes over concatenation.
#[cfg(creusot)]
#[logic]
#[ensures(body(a.concat(b)) == body(a).concat(body(b)))]
#[variant(a.len())]
pub fn body_concat(a: Seq<u32>, b: Seq<u32>) {
    pearlite! {
        if a.len() > 0 {
            tail_concat(a, b);
            body_concat(a.tail(), b);
            esc(a[0]).concat_assoc(body(a.tail()), body(b))
        } else {
            empty_concat(a, b);
            body(b).concat_empty()
        }
    }
}

#[cfg(creusot)]
#[logic]
#[requires(0 <= i && i < s.len())]
#[ensures(s.subsequence(0, i + 1) == s.subsequence(0, i).concat(Seq::singleton(s[i])))]
pub fn snoc_split(s: Seq<u32>, i: Int) {}

/// One more unit at the end.
#[cfg(creusot)]
#[logic]
#[requires(0 <= i && i < s.len())]
#[ensures(body(s.subsequence(0, i + 1)) == body(s.subsequence(0, i)).concat(esc(s[i])))]
pub fn body_snoc(s: Seq<u32>, i: Int) {
    pearlite! {
        snoc_split(s, i);
        body_concat(s.subsequence(0, i), Seq::singleton(s[i]));
        esc(s[i]).concat_empty()
    }
}

/// Equal sequences with a common prefix have equal remainders.
#[cfg(creusot)]
#[logic]
#[requires(p.concat(x) == p.concat(y))]
#[ensures(x == y)]
pub fn cancel_prefix(p: Seq<u32>, x: Seq<u32>, y: Seq<u32>) {
    pearlite! { proof_ext(x, y, p) }
}

#[cfg(creusot)]
#[logic]
#[requires(p.concat(x) == p.concat(y))]
#[ensures(x.len() == y.len() && forall<i> 0 <= i && i < x.len() ==> x[i] == y[i])]
pub fn proof_ext(x: Seq<u32>, y: Seq<u32>, p: Seq<u32>) {
    pearlite! { proof_index(p, x, y) }
}

#[cfg(creusot)]
#[logic]
#[requires(p.concat(x) == p.concat(y))]
#[ensures(forall<i> 0 <= i && i < x.len() ==> p.concat(x)[p.len() + i] == x[i] && p.concat(y)[p.len() + i] == y[i])]
pub fn proof_index(p: Seq<u32>, x: Seq<u32>, y: Seq<u32>) {}

/// The value of a lowercase hex digit unit.
#[cfg(creusot)]
#[logic(open)]
pub fn digit_value(c: u32) -> u32 {
    pearlite! { if c < 0x61u32 { c - 48u32 } else { c - 87u32 } }
}

/// Read back the unit whose escape starts `q`.
#[cfg(creusot)]
#[logic(open)]
pub fn unesc_head(q: Seq<u32>) -> u32 {
    pearlite! {
        if q[0] != 0x5cu32 { q[0] }
        else if q[1] == 0x62u32 { 0x08u32 }
        else if q[1] == 0x74u32 { 0x09u32 }
        else if q[1] == 0x6eu32 { 0x0au32 }
        else if q[1] == 0x66u32 { 0x0cu32 }
        else if q[1] == 0x72u32 { 0x0du32 }
        else if q[1] == 0x75u32 {
            if q[4] == 0x30u32 { digit_value(q[5]) } else { digit_value(q[5]) + 16u32 }
        }
        else { q[1] }
    }
}

/// Whatever follows an escape, the escape still reads back as its unit.
#[cfg(creusot)]
#[logic]
#[ensures(unesc_head(esc(u).concat(x)) == u)]
pub fn reads_back(u: u32, x: Seq<u32>) {}

/// Escapes form a prefix code: the units that follow an escape cannot change
/// which unit it was, and two escapes of different units never share a prefix.
#[cfg(creusot)]
#[logic]
#[requires(esc(a).concat(x) == esc(b).concat(y))]
#[ensures(a == b && x == y)]
pub fn esc_prefix(a: u32, b: u32, x: Seq<u32>, y: Seq<u32>) {
    pearlite! { reads_back(a, x); reads_back(b, y); cancel_prefix(esc(a), x, y) }
}

/// A body followed by the closing quote is self-delimiting.
#[cfg(creusot)]
#[logic]
#[requires(body(s).concat(Seq::singleton(0x22u32)).concat(x)
    == body(t).concat(Seq::singleton(0x22u32)).concat(y))]
#[ensures(s == t && x == y)]
#[variant(s.len())]
pub fn rest_delimits(s: Seq<u32>, t: Seq<u32>, x: Seq<u32>, y: Seq<u32>) {
    pearlite! {
        if s.len() > 0 && t.len() > 0 {
            let q = Seq::singleton(0x22u32);
            esc(s[0]).concat_assoc(body(s.tail()), q);
            esc(s[0]).concat_assoc(body(s.tail()).concat(q), x);
            esc(t[0]).concat_assoc(body(t.tail()), q);
            esc(t[0]).concat_assoc(body(t.tail()).concat(q), y);
            esc_prefix(s[0], t[0], body(s.tail()).concat(q).concat(x), body(t.tail()).concat(q).concat(y));
            rest_delimits(s.tail(), t.tail(), x, y);
            cons_tail(s, t)
        } else if s.len() == 0 && t.len() == 0 {
            empty_concat(body(s), Seq::singleton(0x22u32));
            empty_concat(body(t), Seq::singleton(0x22u32));
            cancel_prefix(Seq::singleton(0x22u32), x, y);
            both_empty(s, t)
        }
    }
}

#[cfg(creusot)]
#[logic]
#[requires(s.len() > 0 && t.len() > 0 && s[0] == t[0] && s.tail() == t.tail())]
#[ensures(s == t)]
pub fn cons_tail(s: Seq<u32>, t: Seq<u32>) {
    pearlite! { tail_index(s); tail_index(t) }
}

#[cfg(creusot)]
#[logic]
#[requires(s.len() > 0)]
#[ensures(s.tail().len() == s.len() - 1 && forall<i> 0 < i && i < s.len() ==> s.tail()[i - 1] == s[i])]
pub fn tail_index(s: Seq<u32>) {}

#[cfg(creusot)]
#[logic]
#[requires(s.len() == 0 && t.len() == 0)]
#[ensures(s == t)]
pub fn both_empty(s: Seq<u32>, t: Seq<u32>) {}

/// THEOREM: a quoted string is self-delimiting. If the canonical text continues
/// differently after two quoted strings (`x`, `y`), the strings still cannot
/// collide: `quoted(s) ++ x == quoted(t) ++ y` forces `s == t` and `x == y`.
#[cfg(creusot)]
#[logic]
#[requires(quoted(s).concat(x) == quoted(t).concat(y))]
#[ensures(s == t && x == y)]
pub fn quoted_delimits(s: Seq<u32>, t: Seq<u32>, x: Seq<u32>, y: Seq<u32>) {
    pearlite! {
        Seq::singleton(0x22u32).concat_assoc(body(s), Seq::singleton(0x22u32));
        Seq::singleton(0x22u32).concat_assoc(body(s).concat(Seq::singleton(0x22u32)), x);
        Seq::singleton(0x22u32).concat_assoc(body(t), Seq::singleton(0x22u32));
        Seq::singleton(0x22u32).concat_assoc(body(t).concat(Seq::singleton(0x22u32)), y);
        cancel_prefix(Seq::singleton(0x22u32),
            body(s).concat(Seq::singleton(0x22u32)).concat(x),
            body(t).concat(Seq::singleton(0x22u32)).concat(y));
        rest_delimits(s, t, x, y)
    }
}

#[cfg_attr(creusot, requires(n < 16u32))]
#[cfg_attr(creusot, ensures(result == hex_unit(n)))]
fn hex_unit_of(n: u32) -> u32 {
    if n < 10 {
        n + 48
    } else {
        n + 87
    }
}

/// Append the escape of one unit.
#[cfg_attr(creusot, ensures((^out)@ == out@.concat(esc(u))))]
fn push_esc(u: u32, out: &mut Vec<u32>) {
    #[cfg(creusot)]
    let before = snapshot!(out@);
    let short = match u {
        0x22 => 0x22,
        0x5c => 0x5c,
        0x08 => 0x62,
        0x09 => 0x74,
        0x0a => 0x6e,
        0x0c => 0x66,
        0x0d => 0x72,
        _ => 0,
    };
    if short != 0 {
        out.push(0x5c);
        out.push(short);
    } else if u < 0x20 {
        // u < 0x20: the high digit is 0 or 1
        out.push(0x5c);
        out.push(0x75);
        out.push(0x30);
        out.push(0x30);
        out.push(if u < 16 { 0x30 } else { 0x31 });
        out.push(hex_unit_of(if u < 16 { u } else { u - 16 }));
    } else {
        out.push(u);
    }
    #[cfg(creusot)]
    proof_assert! { out@.ext_eq(before.concat(esc(u))) };
}

/// Append the JCS spelling of `s` to `out`.
#[cfg_attr(creusot, ensures((^out)@ == out@.concat(quoted(s@))))]
pub fn quote_units(s: &[u32], out: &mut Vec<u32>) {
    #[cfg(creusot)]
    let start = snapshot!(out@);
    out.push(0x22);
    let mut i = 0;
    #[cfg_attr(creusot, invariant(i@ <= s@.len()))]
    #[cfg_attr(creusot, invariant(out@ == start.concat(Seq::singleton(0x22u32))
        .concat(body(s@.subsequence(0, i@)))))]
    while i < s.len() {
        push_esc(s[i], out);
        #[cfg(creusot)]
        proof_assert! { body_snoc(s@, i@); true };
        i += 1;
    }
    #[cfg(creusot)]
    proof_assert! { s@.subsequence(0, s@.len()).ext_eq(s@) };
    out.push(0x22);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn q(s: &str) -> String {
        let mut out = Vec::new();
        quote_units(&s.chars().map(|c| c as u32).collect::<Vec<_>>(), &mut out);
        out.into_iter()
            .map(|u| char::from_u32(u).unwrap())
            .collect()
    }

    #[test]
    fn jcs_examples() {
        assert_eq!(q("a\"b\\c"), r#""a\"b\\c""#);
        assert_eq!(q("\u{8}\t\n\u{c}\r"), r#""\b\t\n\f\r""#);
        assert_eq!(q("\u{0}\u{1f}\u{7f}é€"), "\"\\u0000\\u001f\u{7f}é€\"");
    }
}
