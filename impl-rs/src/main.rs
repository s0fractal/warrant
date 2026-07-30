//! Third independent Warrant implementation (Rust, from scratch, no external
//! crates) — the canonicalization + schema + WarrantID + weak-key layer where
//! the cross-implementation consensus-split bugs live. Mirrors sigma-glyph's
//! impl-rs discipline. Commands:
//!   warrant-rs canon <body.json>        -> {"warrant_id":..,"canon_hex":..}
//!   warrant-rs conformance [examples]   -> SPEC §8 WarrantIDs + §8.3 negatives
//! Ed25519 signature verification is a separate increment.

mod ed25519;

use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::Path;
use std::process::ExitCode;

type Hash = [u8; 32];

// ---------- SHA-256 (FIPS 180-4, from scratch — shared with sigma impl-rs) ----------
fn sha256(input: &[u8]) -> Hash {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut state: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let bit_len = (input.len() as u64).wrapping_mul(8);
    let mut padded = input.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_len.to_be_bytes());
    for block in padded.chunks_exact(64) {
        let mut w = [0u32; 64];
        for (i, word) in block.chunks_exact(4).enumerate() {
            w[i] = u32::from_be_bytes(word.try_into().unwrap());
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = state;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (slot, value) in state.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *slot = slot.wrapping_add(value);
        }
    }
    let mut out = [0u8; 32];
    for (chunk, word) in out.chunks_exact_mut(4).zip(state) {
        chunk.copy_from_slice(&word.to_be_bytes());
    }
    out
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 15) as usize] as char);
    }
    out
}

fn decode_hex(text: &str) -> Option<Vec<u8>> {
    if text.len() % 2 != 0 {
        return None;
    }
    fn nibble(b: u8) -> Option<u8> {
        match b {
            b'0'..=b'9' => Some(b - b'0'),
            b'a'..=b'f' => Some(b - b'a' + 10),
            b'A'..=b'F' => Some(b - b'A' + 10),
            _ => None,
        }
    }
    text.as_bytes()
        .chunks_exact(2)
        .map(|p| Some((nibble(p[0])? << 4) | nibble(p[1])?))
        .collect()
}

fn is_hex64(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

// ---------- JSON model + parser (I-JSON: dup keys and trailing content rejected) ----------
enum Json {
    Null,
    Bool(bool),
    Int(String),   // canonical integer text (JCS: no leading zeros, no '+')
    Float(String), // a non-integer number: parseable but never canonical (SPEC §2)
    Str(String),
    Array(Vec<Json>),
    Object(BTreeMap<String, Json>), // sorted (JCS order for ASCII keys) + dup-detecting
}

struct Parser<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> Parser<'a> {
    fn parse(b: &'a [u8]) -> Result<Json, String> {
        let mut p = Self { b, i: 0 };
        let v = p.value()?;
        p.ws();
        if p.i != b.len() {
            return Err("trailing content after JSON value".into());
        }
        Ok(v)
    }
    fn ws(&mut self) {
        while matches!(self.b.get(self.i), Some(b' ' | b'\n' | b'\r' | b'\t')) {
            self.i += 1;
        }
    }
    fn value(&mut self) -> Result<Json, String> {
        self.ws();
        match self.b.get(self.i).copied() {
            Some(b'{') => self.object(),
            Some(b'[') => self.array(),
            Some(b'"') => Ok(Json::Str(self.string()?)),
            Some(b't') => self.lit(b"true", Json::Bool(true)),
            Some(b'f') => self.lit(b"false", Json::Bool(false)),
            Some(b'n') => self.lit(b"null", Json::Null),
            Some(b'-') | Some(b'0'..=b'9') => self.number(),
            _ => Err("expected a JSON value".into()),
        }
    }
    fn lit(&mut self, t: &[u8], v: Json) -> Result<Json, String> {
        if self.b.get(self.i..self.i + t.len()) == Some(t) {
            self.i += t.len();
            Ok(v)
        } else {
            Err("invalid literal".into())
        }
    }
    fn object(&mut self) -> Result<Json, String> {
        self.i += 1; // '{'
        let mut m = BTreeMap::new();
        self.ws();
        if self.b.get(self.i) == Some(&b'}') {
            self.i += 1;
            return Ok(Json::Object(m));
        }
        loop {
            self.ws();
            if self.b.get(self.i) != Some(&b'"') {
                return Err("expected object key".into());
            }
            let k = self.string()?;
            self.ws();
            if self.b.get(self.i) != Some(&b':') {
                return Err("expected ':'".into());
            }
            self.i += 1;
            let v = self.value()?;
            if m.insert(k, v).is_some() {
                return Err("duplicate member name (invalid I-JSON)".into());
            }
            self.ws();
            match self.b.get(self.i) {
                Some(b',') => self.i += 1,
                Some(b'}') => {
                    self.i += 1;
                    return Ok(Json::Object(m));
                }
                _ => return Err("expected ',' or '}'".into()),
            }
        }
    }
    fn array(&mut self) -> Result<Json, String> {
        self.i += 1; // '['
        let mut a = Vec::new();
        self.ws();
        if self.b.get(self.i) == Some(&b']') {
            self.i += 1;
            return Ok(Json::Array(a));
        }
        loop {
            a.push(self.value()?);
            self.ws();
            match self.b.get(self.i) {
                Some(b',') => self.i += 1,
                Some(b']') => {
                    self.i += 1;
                    return Ok(Json::Array(a));
                }
                _ => return Err("expected ',' or ']'".into()),
            }
        }
    }
    fn string(&mut self) -> Result<String, String> {
        self.i += 1; // opening quote
        let mut out = String::new();
        loop {
            let byte = *self.b.get(self.i).ok_or("unterminated string")?;
            self.i += 1;
            match byte {
                b'"' => return Ok(out),
                b'\\' => {
                    let e = *self.b.get(self.i).ok_or("unterminated escape")?;
                    self.i += 1;
                    match e {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{0008}'),
                        b'f' => out.push('\u{000c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let code = self.u4()?;
                            if (0xd800..=0xdbff).contains(&code) {
                                // high surrogate: MUST be followed by \uXXXX low surrogate
                                // (astral chars are written this way when ensure_ascii=True)
                                if self.b.get(self.i) == Some(&b'\\')
                                    && self.b.get(self.i + 1) == Some(&b'u')
                                {
                                    self.i += 2;
                                    let low = self.u4()?;
                                    if !(0xdc00..=0xdfff).contains(&low) {
                                        return Err("invalid low surrogate".into());
                                    }
                                    let c = 0x10000
                                        + ((code as u32 - 0xd800) << 10)
                                        + (low as u32 - 0xdc00);
                                    out.push(char::from_u32(c).ok_or("invalid surrogate pair")?);
                                } else {
                                    return Err("lone high surrogate".into());
                                }
                            } else if (0xdc00..=0xdfff).contains(&code) {
                                return Err("lone low surrogate".into());
                            } else {
                                out.push(char::from_u32(code as u32).ok_or("invalid \\u escape")?);
                            }
                        }
                        _ => return Err("invalid string escape".into()),
                    }
                }
                0x00..=0x1f => return Err("raw control byte in string".into()),
                0x20..=0x7f => out.push(byte as char),
                _ => {
                    self.i -= 1;
                    let tail = std::str::from_utf8(&self.b[self.i..]).map_err(|_| "invalid UTF-8")?;
                    let ch = tail.chars().next().ok_or("invalid UTF-8")?;
                    out.push(ch);
                    self.i += ch.len_utf8();
                }
            }
        }
    }
    fn u4(&mut self) -> Result<u16, String> {
        let d = self.b.get(self.i..self.i + 4).ok_or("short \\u escape")?;
        self.i += 4;
        let t = std::str::from_utf8(d).map_err(|_| "bad \\u escape")?;
        u16::from_str_radix(t, 16).map_err(|_| "bad \\u escape".to_string())
    }
    fn number(&mut self) -> Result<Json, String> {
        let start = self.i;
        if self.b.get(self.i) == Some(&b'-') {
            self.i += 1;
        }
        let int_start = self.i;
        while self.b.get(self.i).is_some_and(|b| b.is_ascii_digit()) {
            self.i += 1;
        }
        if self.i == int_start {
            return Err("expected digits in number".into());
        }
        if self.i - int_start > 1 && self.b[int_start] == b'0' {
            return Err("leading zero in number".into());
        }
        let mut is_float = false;
        if self.b.get(self.i) == Some(&b'.') {
            is_float = true;
            self.i += 1;
            while self.b.get(self.i).is_some_and(|b| b.is_ascii_digit()) {
                self.i += 1;
            }
        }
        if matches!(self.b.get(self.i), Some(b'e' | b'E')) {
            is_float = true;
            self.i += 1;
            if matches!(self.b.get(self.i), Some(b'+' | b'-')) {
                self.i += 1;
            }
            while self.b.get(self.i).is_some_and(|b| b.is_ascii_digit()) {
                self.i += 1;
            }
        }
        let text = std::str::from_utf8(&self.b[start..self.i]).unwrap().to_string();
        if is_float {
            Ok(Json::Float(text))
        } else if text == "-0" {
            Ok(Json::Int("0".into())) // JCS canonicalizes -0 to 0
        } else {
            Ok(Json::Int(text))
        }
    }
}

// ---------- canonicalization (RFC 8785 JCS subset, SPEC §4) ----------
fn canon(v: &Json, out: &mut Vec<u8>) -> Result<(), String> {
    match v {
        Json::Null => out.extend_from_slice(b"null"),
        Json::Bool(true) => out.extend_from_slice(b"true"),
        Json::Bool(false) => out.extend_from_slice(b"false"),
        Json::Int(s) => out.extend_from_slice(s.as_bytes()),
        Json::Float(s) => return Err(format!("non-integer JSON number: {s}")),
        Json::Str(s) => quote_jcs(s, out),
        Json::Array(a) => {
            out.push(b'[');
            for (i, item) in a.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                canon(item, out)?;
            }
            out.push(b']');
        }
        Json::Object(m) => {
            out.push(b'{');
            for (i, (k, val)) in m.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                quote_jcs(k, out);
                out.push(b':');
                canon(val, out)?;
            }
            out.push(b'}');
        }
    }
    Ok(())
}

/// JCS string escaping (SPEC §4): short escapes incl. \b \f, lowercase \u00xx
/// for other controls, raw UTF-8 otherwise (no HTML escaping of <>&).
fn quote_jcs(s: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    for ch in s.chars() {
        match ch {
            '"' => out.extend_from_slice(b"\\\""),
            '\\' => out.extend_from_slice(b"\\\\"),
            '\u{0008}' => out.extend_from_slice(b"\\b"),
            '\u{0009}' => out.extend_from_slice(b"\\t"),
            '\u{000a}' => out.extend_from_slice(b"\\n"),
            '\u{000c}' => out.extend_from_slice(b"\\f"),
            '\u{000d}' => out.extend_from_slice(b"\\r"),
            c if (c as u32) < 0x20 => {
                out.extend_from_slice(format!("\\u{:04x}", c as u32).as_bytes());
            }
            c => {
                let mut buf = [0u8; 4];
                out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
            }
        }
    }
    out.push(b'"');
}

fn warrant_id(body: &Json) -> Result<String, String> {
    let mut bytes = Vec::new();
    canon(body, &mut bytes)?;
    Ok(encode_hex(&sha256(&bytes)))
}

// ---------- schema validation (SPEC §2/§3) ----------
fn as_obj(v: &Json) -> Option<&BTreeMap<String, Json>> {
    if let Json::Object(m) = v {
        Some(m)
    } else {
        None
    }
}
fn as_str(v: &Json) -> Option<&str> {
    if let Json::Str(s) = v {
        Some(s)
    } else {
        None
    }
}
fn as_arr(v: &Json) -> Option<&[Json]> {
    if let Json::Array(a) = v {
        Some(a)
    } else {
        None
    }
}
fn hex64_val(v: &Json) -> bool {
    as_str(v).is_some_and(is_hex64)
}

fn validate_body(v: &Json) -> Vec<String> {
    let mut e = Vec::new();
    let b = match as_obj(v) {
        Some(m) => m,
        None => return vec!["body is not an object".into()],
    };
    const FIELDS: [&str; 9] = [
        "warrant", "decision", "subject", "under", "because", "evidence", "actor", "prior", "ts",
    ];
    for k in b.keys() {
        if !FIELDS.contains(&k.as_str()) {
            e.push(format!("unknown field: {k}"));
        }
    }
    for f in FIELDS {
        if !b.contains_key(f) {
            e.push(format!("missing field: {f}"));
        }
    }
    if !e.is_empty() {
        return e;
    }
    match as_str(&b["warrant"]) {
        Some("0.1") | Some("0.2") => {}
        _ => e.push("warrant version must be 0.1 or 0.2".into()),
    }
    let version = as_str(&b["warrant"]).unwrap_or("0.2");
    match as_str(&b["decision"]) {
        Some("propose") | Some("accept") | Some("reject") | Some("supersede") => {}
        _ => e.push("decision must be propose|accept|reject|supersede".into()),
    }
    // subject
    match as_obj(&b["subject"]) {
        Some(s) if s.keys().all(|k| k == "hash" || k == "note") && s.contains_key("hash") => {
            if !hex64_val(&s["hash"]) {
                e.push("subject.hash must be hex64".into());
            }
            if let Some(note) = s.get("note") {
                match as_str(note) {
                    Some(t) if t.chars().count() <= 200 => {}
                    _ => e.push("subject.note must be a string of <=200 code points".into()),
                }
            }
        }
        _ => e.push("subject must be {hash, note?}".into()),
    }
    // under (>=1 hex64)
    match as_arr(&b["under"]) {
        Some(a) if !a.is_empty() && a.iter().all(hex64_val) => {}
        _ => e.push("under must be a list of >=1 hex64 hashes".into()),
    }
    // evidence (>=0 hex64)
    match as_arr(&b["evidence"]) {
        Some(a) if a.iter().all(hex64_val) => {}
        _ => e.push("evidence must be a list of hex64 hashes".into()),
    }
    // actor {id: nonempty string}
    match as_obj(&b["actor"]) {
        Some(a) if a.len() == 1 && a.get("id").and_then(as_str).is_some_and(|s| !s.is_empty()) => {}
        _ => e.push("actor must be {id: <nonempty string>}".into()),
    }
    // prior (>=0 hex64)
    match as_arr(&b["prior"]) {
        Some(a) if a.iter().all(hex64_val) => {}
        _ => e.push("prior must be a list of WarrantIDs (hex64)".into()),
    }
    // ts: integer in 0..2^63-1
    match &b["ts"] {
        Json::Int(s) => {
            let ok = s.parse::<i128>().map(|n| (0..=9223372036854775807i128).contains(&n));
            if ok != Ok(true) {
                e.push("ts must be an integer in 0..2^63-1".into());
            }
        }
        _ => e.push("ts must be an integer (unix seconds)".into()),
    }
    // because
    let because = as_arr(&b["because"]);
    match because {
        Some(a) => {
            for (i, r) in a.iter().enumerate() {
                for m in validate_reason(r, version) {
                    e.push(format!("because[{i}]: {m}"));
                }
            }
            let dec = as_str(&b["decision"]);
            if (dec == Some("reject") || dec == Some("supersede")) && a.is_empty() {
                e.push(format!("{} requires >=1 reason", dec.unwrap()));
            }
        }
        None => e.push("because must be a list".into()),
    }
    e
}

fn validate_reason(v: &Json, version: &str) -> Vec<String> {
    let r = match as_obj(v) {
        Some(m) => m,
        None => return vec!["reason is not an object".into()],
    };
    match r.get("kind").and_then(as_str) {
        Some("prose") => {
            if r.len() != 2 || !r.get("text").is_some_and(|t| as_str(t).is_some()) {
                return vec!["prose reason must be {kind, text}".into()];
            }
            vec![]
        }
        Some("check") => {
            let mut e = Vec::new();
            for k in r.keys() {
                if !["kind", "check", "runtime", "verdict", "transcript"].contains(&k.as_str()) {
                    e.push("check reason has unknown fields".into());
                    break;
                }
            }
            if !r.get("check").is_some_and(hex64_val) {
                e.push("check must be hex64".into());
            }
            let runtime = r.get("runtime").and_then(as_str);
            let allowed: &[&str] = if version == "0.2" {
                &["cmd@v1", "ski@v1"]
            } else {
                &["cmd@v1"]
            };
            if runtime == Some("ski@v1") && version == "0.1" {
                e.push("runtime ski@v1 is reserved and MUST be rejected in v0.1".into());
            } else if !runtime.is_some_and(|rt| allowed.contains(&rt)) {
                e.push("runtime must be an allowed value".into());
            }
            match r.get("verdict").and_then(as_str) {
                Some("pass") | Some("fail") => {}
                _ => e.push("verdict must be pass|fail".into()),
            }
            if let Some(t) = r.get("transcript") {
                if !hex64_val(t) {
                    e.push("transcript must be hex64".into());
                }
            }
            e
        }
        _ => vec!["unknown reason kind".into()],
    }
}

// ---------- weak Ed25519 public keys (SPEC §5) ----------
fn weak_ed25519_pubkey(raw: &[u8]) -> bool {
    if raw.len() != 32 {
        return true;
    }
    const TORSION: [&str; 10] = [
        "0100000000000000000000000000000000000000000000000000000000000000",
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
        "0000000000000000000000000000000000000000000000000000000000000080",
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
        "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
        "0000000000000000000000000000000000000000000000000000000000000000",
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
        "0100000000000000000000000000000000000000000000000000000000000080",
        "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    ];
    let hex = encode_hex(raw);
    if TORSION.contains(&hex.as_str()) {
        return true;
    }
    // non-canonical y: big-endian, sign bit cleared, compared to p = 2^255-19
    let mut be = [0u8; 32];
    for i in 0..32 {
        be[i] = raw[31 - i];
    }
    be[0] &= 0x7f;
    const P: [u8; 32] = [
        0x7f, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
        0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
        0xff, 0xed,
    ];
    be >= P
}

// SPEC §5 -- signature domain separation (`warrant-sig-v1`), adopted 2026-07-31
// under proposals/DEC-001-domain-separation.md.
//
//     msg = "warrant-sig-v1:" || WarrantID_raw          15 + 32 = 47 bytes
//
// Still pure RFC 8032 Ed25519 over a byte string -- NOT Ed25519ctx. This
// verifier is written from scratch, so Ed25519ctx would mean implementing and
// differentially testing RFC 8032's dom2 prefix here from nothing; a fixed
// ASCII prefix buys the same separation with no new primitive. See
// impl/warrant.py for the full argument.
pub const SIG_DOMAIN: &[u8] = b"warrant-sig-v1:";

/// The §6 report string for a signature made under the pre-0.6.0 bare-WarrantID
/// construction. Byte-identical in all three implementations (SPEC §5).
pub const LEGACY_SIG_MESSAGE: &str = "signature does not verify (excluded): LEGACY pre-v1 signature construction (signed the bare 32-byte WarrantID; SPEC 5 requires \"warrant-sig-v1:\" || WarrantID). Re-sign with: warrant resign --key <keyfile>";

/// The exact bytes a Warrant signature covers, or None when `wid_hex` is not a
/// 32-byte hex digest.
fn sig_message(wid_hex: &str) -> Option<Vec<u8>> {
    let raw = decode_hex(wid_hex).filter(|m| m.len() == 32)?;
    let mut msg = Vec::with_capacity(SIG_DOMAIN.len() + 32);
    msg.extend_from_slice(SIG_DOMAIN);
    msg.extend_from_slice(&raw);
    Some(msg)
}

/// Key and signature bytes, screened exactly once, so `verify_sig` and
/// `legacy_sig` cannot drift on which keys they reject.
fn sig_parts(sig: &BTreeMap<String, Json>) -> Option<([u8; 32], [u8; 64])> {
    let key = sig.get("key").and_then(as_str).and_then(decode_hex)?;
    if key.len() != 32 || weak_ed25519_pubkey(&key) {
        return None;
    }
    let sigb = sig.get("sig").and_then(as_str).and_then(decode_hex)?;
    if sigb.len() != 64 {
        return None;
    }
    let mut pk = [0u8; 32];
    pk.copy_from_slice(&key);
    let mut sg = [0u8; 64];
    sg.copy_from_slice(&sigb);
    Some((pk, sg))
}

fn verify_sig(wid_hex: &str, sig: &BTreeMap<String, Json>) -> bool {
    let (pk, sg) = match sig_parts(sig) {
        Some(v) => v,
        None => return false,
    };
    match sig_message(wid_hex) {
        Some(msg) => ed25519::verify(&pk, &sg, &msg),
        None => false,
    }
}

/// True if `sig` is valid over the BARE 32-byte WarrantID -- the construction
/// SPEC §5 replaced. DIAGNOSIS ONLY; no caller treats it as acceptance. A
/// verifier accepting both messages would have no separation at all, since an
/// attacker would just use the legacy one (DEC-001 §4.3).
fn legacy_sig(wid_hex: &str, sig: &BTreeMap<String, Json>) -> bool {
    let (pk, sg) = match sig_parts(sig) {
        Some(v) => v,
        None => return false,
    };
    match decode_hex(wid_hex).filter(|m| m.len() == 32) {
        Some(msg) => ed25519::verify(&pk, &sg, &msg),
        None => false,
    }
}

// ---------- commands ----------
fn read(path: &str) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|err| format!("cannot read {path}: {err}"))
}

fn cmd_canon(path: &str) -> Result<(), String> {
    let data = read(path)?;
    let body = Parser::parse(&data)?;
    let mut bytes = Vec::new();
    canon(&body, &mut bytes)?;
    let id = encode_hex(&sha256(&bytes));
    // matches the Python/Go `canon` output shape for tests/differential.py
    println!(
        "{{\"warrant_id\":\"{}\",\"canon_hex\":\"{}\"}}",
        id,
        encode_hex(&bytes)
    );
    Ok(())
}

fn cmd_conformance(dir: &str) -> bool {
    let mut ok = Vec::new();
    let mut chk = |name: &str, cond: bool| {
        ok.push(cond);
        println!("{} {}", if cond { "OK  " } else { "FAIL" }, name);
    };
    // §8 blobs
    for (name, want) in [
        ("policy.txt", "cb3a0afe6ee6219867b9c3f9b860080918fe1042f315fe02ff62300f780beb73"),
        ("check.sh", "05d234bec21803c6fa007d848c1773b9fd05cfdf852d6d09542ed3b127c02b6c"),
    ] {
        let got = read(&format!("{dir}/{name}")).map(|d| encode_hex(&sha256(&d)));
        chk(&format!("blob {name}"), got.as_deref() == Ok(want));
    }
    // §8 positive WarrantIDs
    for (name, want) in [
        ("propose.warrant.json", "00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1"),
        ("reject.warrant.json", "5f5d4035a4ae04a3eec255105eee7dda7c98daaf9962c92cbbbad38ac21509d8"),
        ("accept.warrant.json", "bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78"),
    ] {
        match read(&format!("{dir}/{name}")).and_then(|d| Parser::parse(&d)) {
            Ok(env) => {
                let body = as_obj(&env).and_then(|m| m.get("body"));
                let id = body.map(warrant_id);
                chk(&format!("schema {name}"), body.map(validate_body).is_some_and(|e| e.is_empty()));
                chk(&format!("WarrantID {name}"), matches!(&id, Some(Ok(h)) if h == want));
                // verify every signature over the WarrantID (independent Ed25519)
                if let Some(sigs) = as_obj(&env).and_then(|m| m.get("sigs")).and_then(as_arr) {
                    for s in sigs.iter().filter_map(as_obj) {
                        let actor = s.get("actor").and_then(as_str).unwrap_or("?");
                        chk(&format!("sig {name} by {actor}"), verify_sig(want, s));
                    }
                }
            }
            Err(err) => chk(&format!("read {name}: {err}"), false),
        }
    }
    // §8.3 negative battery
    if let Ok(neg) = read(&format!("{dir}/conformance-negatives.json")).and_then(|d| Parser::parse(&d)) {
        if let Some(m) = as_obj(&neg) {
            if let Some(keys) = m.get("weak_ed25519_pubkeys").and_then(as_arr) {
                for k in keys.iter().filter_map(as_str) {
                    // a non-hex/odd-length key string is also "must reject"
                    let weak = decode_hex(k).map(|b| weak_ed25519_pubkey(&b)).unwrap_or(true);
                    let short: String = k.chars().take(12).collect();
                    chk(&format!("neg: weak key {short} rejected"), weak);
                }
            }
            if let Some(cases) = m.get("schema_invalid").and_then(as_arr) {
                for c in cases.iter().filter_map(as_obj) {
                    let why = c.get("why").and_then(as_str).unwrap_or("?");
                    let invalid = c.get("body").map(validate_body).is_some_and(|e| !e.is_empty());
                    chk(&format!("neg: schema-invalid ({why})"), invalid);
                }
            }
        }
    }
    // SPEC §8.5 signature-construction battery. The message bytes are pinned
    // because every way of building them wrong still reproduces all five §8
    // WarrantIDs -- nothing else in this command would notice.
    if let Ok(sv) = read(&format!("{dir}/signature-vectors.json")).and_then(|d| Parser::parse(&d)) {
        if let Some(m) = as_obj(&sv) {
            if let Some(cases) = m.get("message").and_then(as_arr) {
                for c in cases.iter().filter_map(as_obj) {
                    let why: String = c.get("why").and_then(as_str).unwrap_or("?").chars().take(60).collect();
                    let wid = c.get("warrant_id").and_then(as_str).unwrap_or("");
                    let want = c.get("message_hex").and_then(as_str).unwrap_or("");
                    let got = sig_message(wid).map(|b| encode_hex(&b));
                    chk(&format!("sig-msg: {why}"), got.as_deref() == Some(want));
                }
            }
            for (field, expect) in [("accept", true), ("reject", false)] {
                if let Some(cases) = m.get(field).and_then(as_arr) {
                    for c in cases.iter().filter_map(as_obj) {
                        let why: String = c.get("why").and_then(as_str).unwrap_or("?").chars().take(60).collect();
                        let wid = c.get("warrant_id").and_then(as_str).unwrap_or("").to_string();
                        chk(&format!("sig-{field}: {why}"), verify_sig(&wid, c) == expect);
                    }
                }
            }
        }
    }
    let passed = ok.iter().filter(|&&v| v).count();
    if passed == ok.len() {
        println!("\nRUST-WARRANT CONFORMANCE: ALL PASS ({}/{})", passed, ok.len());
        true
    } else {
        println!("\nRUST-WARRANT CONFORMANCE: FAILURES ({}/{})", passed, ok.len());
        false
    }
}


// ---------- store verification (SPEC §6, BASE grade) ----------
//
// The third implementation verified canonicalization and conformance but not
// stores, so the strongest claim this project could make was that TWO
// implementations agree on a verification outcome. On the surface where being
// wrong matters most -- does this store verify -- parity was a pair, not a trio.
//
// Scope is deliberately narrow and stated rather than implied: §6 base checks
// only. No settlement grade, no key state, no trust config. `ski@v1` reasons are
// reported as `ski@v1 unverified: runtime unavailable`, which is exactly what the
// Python verifier prints when its oracle is absent -- so parity is testable
// against `warrant verify` rather than approximately similar to it.
struct Rec {
    wid: String,
    env: Json,
}

fn list_dir(path: &str) -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(entries) = fs::read_dir(path) {
        for e in entries.flatten() {
            if let Some(name) = e.file_name().to_str() {
                out.push(name.to_string());
            }
        }
    }
    out.sort();
    out
}

fn cmd_verify(store: &str) -> ExitCode {
    let records_dir = format!("{store}/records");
    let blobs_dir = format!("{store}/blobs");
    if !Path::new(&records_dir).is_dir() {
        // Fail closed, and in the same SHAPE as the other two: a diagnostic and a
        // non-zero status, with no summary line. Printing "0 records, 1 errors"
        // here made this implementation the only one to summarise a store that
        // does not exist, which reads as a verification that ran.
        eprintln!("no store at {store} (run: warrant init)");
        return ExitCode::from(1);
    }

    // Blob names are addresses. A file whose bytes hash elsewhere is different
    // bytes wearing the real ones' address, so integrity is recorded up front.
    let mut blob_ok: BTreeMap<String, bool> = BTreeMap::new();
    for name in list_dir(&blobs_dir) {
        if !is_hex64(&name) {
            continue;
        }
        let intact = read(&format!("{blobs_dir}/{name}"))
            .map(|d| encode_hex(&sha256(&d)) == name)
            .unwrap_or(false);
        blob_ok.insert(name, intact);
    }

    let mut errs = 0usize;
    let mut warns = 0usize;
    let mut recs: Vec<Rec> = Vec::new();
    let mut unloadable: Vec<(String, String)> = Vec::new();
    for name in list_dir(&records_dir) {
        if !name.ends_with(".json") {
            continue;
        }
        let wid = name.trim_end_matches(".json").to_string();
        match read(&format!("{records_dir}/{name}")).and_then(|d| Parser::parse(&d)) {
            Ok(env) => recs.push(Rec { wid, env }),
            Err(e) => unloadable.push((wid, e)),
        }
    }
    let known: BTreeSet<String> = recs.iter().map(|r| r.wid.clone()).collect();

    let mut out = |lvl: &str, wid: &str, msg: String| {
        let short: String = wid.chars().take(12).collect();
        println!("{lvl} {short}  {msg}");
    };

    for (wid, why) in &unloadable {
        out("ERR ", wid, format!("unloadable record: {why}"));
        errs += 1;
    }

    for r in &recs {
        let obj = match as_obj(&r.env) {
            Some(o) if o.contains_key("body") && o.contains_key("sigs") => o,
            _ => {
                out("ERR ", &r.wid, "envelope must be {body, sigs}".to_string());
                errs += 1;
                continue;
            }
        };
        let body = &obj["body"];
        for m in validate_body(body) {
            out("ERR ", &r.wid, format!("schema: {m}"));
            errs += 1;
        }
        // A record whose id does not recompute is not the record its name claims,
        // so every further check against that name is meaningless. One error, then
        // skip -- matching the other two implementations, which learned this from a
        // gate finding about exactly the extra warnings the alternative produces.
        match warrant_id(body) {
            Ok(got) if got == r.wid => {}
            Ok(got) => {
                let s: String = got.chars().take(12).collect();
                out("ERR ", &r.wid, format!("WarrantID mismatch: recomputed {s}"));
                errs += 1;
                continue;
            }
            Err(_) => {
                out("ERR ", &r.wid,
                    "WarrantID uncomputable (record contains invalid characters)".to_string());
                errs += 1;
                continue;
            }
        }

        // Signatures: each is judged on its own. An invalid one is excluded with a
        // warning rather than condemning the record, so one bad co-signature
        // cannot be used to invalidate somebody else's good record; the record
        // errors only if no valid signature by its own actor remains.
        let bm = as_obj(body);
        let actor = bm
            .and_then(|m| m.get("actor"))
            .and_then(as_obj)
            .and_then(|m| m.get("id"))
            .and_then(as_str)
            .unwrap_or("");
        match obj.get("sigs").and_then(as_arr) {
            None => {
                out("ERR ", &r.wid, "sigs must be a list".to_string());
                errs += 1;
            }
            Some(sigs) if sigs.is_empty() => {
                out("ERR ", &r.wid, "no signatures".to_string());
                errs += 1;
            }
            Some(sigs) => {
                let mut actor_ok = false;
                for s in sigs {
                    match as_obj(s) {
                        None => {
                            out("WARN", &r.wid,
                                "signature entry is not an object (excluded)".to_string());
                            warns += 1;
                        }
                        Some(sm) => {
                            let who = sm.get("actor").and_then(as_str).unwrap_or("?");
                            if verify_sig(&r.wid, sm) {
                                if who == actor {
                                    actor_ok = true;
                                }
                                let key: String = sm
                                    .get("key")
                                    .and_then(as_str)
                                    .unwrap_or("")
                                    .chars()
                                    .take(12)
                                    .collect();
                                // No keyring here by construction: this
                                // implementation has no trust config, so the
                                // key<->actor binding is unproven and says so.
                                out("WARN", &r.wid,
                                    format!("binding unverified (no keyring): key {key} claims actor {who}"));
                                warns += 1;
                            } else if legacy_sig(&r.wid, sm) {
                                // Diagnosis, not acceptance (SPEC §5): the one
                                // failure a verifier can name, it names.
                                out("WARN", &r.wid,
                                    format!("{LEGACY_SIG_MESSAGE}: actor {who}"));
                                warns += 1;
                            } else {
                                out("WARN", &r.wid,
                                    format!("signature does not verify (excluded): actor {who}"));
                                warns += 1;
                            }
                        }
                    }
                }
                if !actor_ok {
                    out("ERR ", &r.wid, "no valid signature by body.actor.id".to_string());
                    errs += 1;
                }
            }
        }

        // prior MUST resolve to a stored warrant (§6(4)); and along each edge `ts`
        // must not decrease, which is a WARNING because a clock is not authority --
        // §5.1 makes key validity derive from DAG order, never from trusting `ts`.
        //
        // This check was missing from the first version of this function, and the
        // three-way differential caught it as a one-warning gap on the
        // filename-swap case: fourteen against fifteen. A missing check does not
        // look like a missing check, it looks like a divergence somewhere else.
        // Json::Int holds canonical integer TEXT, so compare numerically: a
        // lexicographic compare would call 9 later than 10.
        fn ts_of(v: Option<&Json>) -> Option<i128> {
            match v {
                Some(Json::Int(t)) => t.parse::<i128>().ok(),
                _ => None,
            }
        }
        let my_ts = ts_of(bm.and_then(|m| m.get("ts")));
        if let Some(prior) = bm.and_then(|m| m.get("prior")).and_then(as_arr) {
            for p in prior.iter().filter_map(as_str) {
                let s: String = p.chars().take(12).collect();
                if !known.contains(p) {
                    out("ERR ", &r.wid, format!("prior {s} not in store"));
                    errs += 1;
                    continue;
                }
                let prev_ts = ts_of(recs.iter().find(|q| q.wid == p)
                    .and_then(|q| as_obj(&q.env))
                    .and_then(|m| m.get("body"))
                    .and_then(as_obj)
                    .and_then(|m| m.get("ts")));
                if let (Some(prev), Some(mine)) = (prev_ts, my_ts) {
                    if prev > mine {
                        out("WARN", &r.wid, format!("ts decreases along prior edge {s}"));
                        warns += 1;
                    }
                }
            }
        }

        // Blob references: absent is a warning (they may live elsewhere), present
        // with the wrong bytes is an error (the store contradicts its addressing).
        let mut refs: Vec<String> = Vec::new();
        for key in ["under", "evidence"] {
            if let Some(a) = bm.and_then(|m| m.get(key)).and_then(as_arr) {
                refs.extend(a.iter().filter_map(as_str).map(|s| s.to_string()));
            }
        }
        let mut ski_reasons = 0usize;
        if let Some(bc) = bm.and_then(|m| m.get("because")).and_then(as_arr) {
            for reason in bc.iter().filter_map(as_obj) {
                for key in ["check", "transcript"] {
                    if let Some(h) = reason.get(key).and_then(as_str) {
                        refs.push(h.to_string());
                    }
                }
                if reason.get("runtime").and_then(as_str) == Some("ski@v1") {
                    ski_reasons += 1;
                }
            }
        }
        for h in &refs {
            let s: String = h.chars().take(12).collect();
            match blob_ok.get(h) {
                None => {
                    out("WARN", &r.wid, format!("unresolved blob {s}"));
                    warns += 1;
                }
                Some(false) => {
                    out("ERR ", &r.wid,
                        format!("blob {s} content does not match its address"));
                    errs += 1;
                }
                Some(true) => {}
            }
        }
        if let Some(subj) = bm
            .and_then(|m| m.get("subject"))
            .and_then(as_obj)
            .and_then(|m| m.get("hash"))
            .and_then(as_str)
        {
            let s: String = subj.chars().take(12).collect();
            let decision = bm.and_then(|m| m.get("decision")).and_then(as_str).unwrap_or("");
            let may_be_record = decision == "supersede" || decision == "accept";
            match blob_ok.get(subj) {
                None if !(may_be_record && known.contains(subj)) => {
                    out("WARN", &r.wid, format!("unresolved blob {s}"));
                    warns += 1;
                }
                Some(false) => {
                    out("ERR ", &r.wid,
                        format!("subject blob {s} content does not match its address"));
                    errs += 1;
                }
                _ => {}
            }
        }

        // Not executed here, and it must not look like it was: "re-ran and
        // matched" and "was not executed" must never be observationally equal.
        for _ in 0..ski_reasons {
            out("WARN", &r.wid, "ski@v1 unverified: runtime unavailable".to_string());
            warns += 1;
        }
    }

    println!("\nverify: {} records, {} errors, {} warnings",
             recs.len() + unloadable.len(), errs, warns);
    if errs > 0 { ExitCode::from(1) } else { ExitCode::SUCCESS }
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("canon") => match args.get(2) {
            Some(path) => match cmd_canon(path) {
                Ok(()) => ExitCode::SUCCESS,
                Err(err) => {
                    eprintln!("canon: {err}");
                    ExitCode::from(2)
                }
            },
            None => {
                eprintln!("usage: warrant-rs canon <body.json>");
                ExitCode::from(2)
            }
        },
        Some("verify") => {
            let store = args.get(2).map(String::as_str).unwrap_or(".warrants");
            cmd_verify(store)
        }
        Some("conformance") => {
            let dir = args.get(2).map(String::as_str).unwrap_or("examples");
            if cmd_conformance(dir) {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            }
        }
        Some("verify-sig") => {
            // verify-sig <pubkey_hex> <sig_hex> <msg_hex> -> prints true|false
            let ok = (|| {
                let key = decode_hex(args.get(2)?)?;
                let sigb = decode_hex(args.get(3)?)?;
                let msg = decode_hex(args.get(4)?)?;
                if key.len() != 32 || sigb.len() != 64 {
                    return Some(false);
                }
                if weak_ed25519_pubkey(&key) {
                    return Some(false);
                }
                let mut pk = [0u8; 32];
                pk.copy_from_slice(&key);
                let mut sg = [0u8; 64];
                sg.copy_from_slice(&sigb);
                Some(ed25519::verify(&pk, &sg, &msg))
            })()
            .unwrap_or(false);
            println!("{ok}");
            ExitCode::SUCCESS
        }
        Some("edtest") => {
            if ed25519::selftest() {
                println!("ED25519 SELFTEST: ALL PASS");
                ExitCode::SUCCESS
            } else {
                println!("ED25519 SELFTEST: FAILURES");
                ExitCode::FAILURE
            }
        }
        _ => {
            eprintln!("usage: warrant-rs canon <body.json> | conformance [examples_dir] \
| verify <store>  (verify is SPEC s6 BASE grade: no settlement, no key state)");
            ExitCode::from(2)
        }
    }
}
