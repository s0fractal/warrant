//! JSON, three ways, because the reference implementation reads JSON three ways
//! and the differences are observable in its reports.
//!
//! * [`parse_ijson`] is `loads_ijson` (SPEC §4): I-JSON over UTF-8 text —
//!   duplicate member names, `NaN`/`Infinity`, unpaired surrogates and a leading
//!   byte order mark are all refused. Records, trust configs, `genesis.json` and
//!   settle candidates are read this way.
//! * [`parse_plain_bytes`] is Python's `json.loads(bytes)`: the encoding is
//!   detected (UTF-8, UTF-8 with BOM, UTF-16, UTF-32), duplicate names keep the
//!   last value, and the non-JSON constants are accepted. Blobs are read this way
//!   — and then compared with their own canonical bytes, so everything lenient
//!   here only ever decides *which* refusal a blob earns ("not JSON" or "not
//!   JCS-canonical"), never whether it is accepted.
//! * [`parse_plain_text`] is `json.loads(str)`, used where the reference reads a
//!   file as text without the I-JSON guard (`why`, `resign`, probe requests).
//!
//! Objects keep their members in document order, as a Python `dict` does,
//! because the reference prints values with `str()`/`repr()` in its reports and
//! iterates some of them in that order.

use std::collections::HashMap;
use std::fmt::Write as _;

/// Nesting deeper than this is refused by every parser here, and by the
/// reference (`MAX_JSON_DEPTH` in impl/warrant.py). A verifier whose verdict
/// depended on the interpreter's call stack would give one store two reports.
pub const MAX_DEPTH: usize = 512;

/// CPython refuses to convert a decimal integer string of more than this many
/// digits (`sys.int_info.default_max_str_digits`), and `json.loads` surfaces that
/// as a parse error. Mirrored so the same bytes are malformed in both.
pub const MAX_INT_DIGITS: usize = 4300;

#[derive(Clone, Debug)]
pub enum Json {
    Null,
    Bool(bool),
    /// Canonical decimal text of an integer (no leading zeros, `-0` folded to `0`).
    Int(String),
    /// A JSON number with a fraction or exponent, or a non-JSON constant read
    /// by a lenient parser. Never canonical (SPEC §2).
    Float(f64),
    Str(String),
    /// A string that contained an unpaired surrogate (lenient parsers only):
    /// a U+FFFD-substituted copy for comparisons, and the exact code points
    /// (surrogates included) for everything that renders it. Such a string has
    /// no UTF-8 encoding, so it can never be canonicalized.
    BadStr(String, Vec<u32>),
    Array(Vec<Json>),
    Object(Obj),
}

/// A JSON object in document order.
#[derive(Clone, Debug, Default)]
pub struct Obj(pub Vec<(String, Json)>, pub Vec<(usize, Vec<u32>)>);

impl Obj {
    pub fn new() -> Self {
        Obj(Vec::new(), Vec::new())
    }
    /// True when some member NAME held an unpaired surrogate (lenient parsers
    /// only): such an object has no canonical form.
    pub fn lossy_keys(&self) -> bool {
        !self.1.is_empty()
    }
    /// The exact code points of the i-th member name.
    pub fn key_units(&self, i: usize) -> Vec<u32> {
        match self.1.iter().find(|(j, _)| *j == i) {
            Some((_, u)) => u.clone(),
            None => self.0[i].0.chars().map(|c| c as u32).collect(),
        }
    }
    pub fn get(&self, k: &str) -> Option<&Json> {
        self.0.iter().find(|(key, _)| key == k).map(|(_, v)| v)
    }
    pub fn get_mut(&mut self, k: &str) -> Option<&mut Json> {
        self.0.iter_mut().find(|(key, _)| key == k).map(|(_, v)| v)
    }
    pub fn contains_key(&self, k: &str) -> bool {
        self.get(k).is_some()
    }
    pub fn keys(&self) -> impl Iterator<Item = &String> {
        self.0.iter().map(|(k, _)| k)
    }
    pub fn values(&self) -> impl Iterator<Item = &Json> {
        self.0.iter().map(|(_, v)| v)
    }
    pub fn iter(&self) -> impl Iterator<Item = &(String, Json)> {
        self.0.iter()
    }
    pub fn len(&self) -> usize {
        self.0.len()
    }
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
    /// Insert or replace, keeping the original position on replace (as a dict).
    pub fn insert(&mut self, k: &str, v: Json) {
        match self.get_mut(k) {
            Some(slot) => *slot = v,
            None => self.0.push((k.to_string(), v)),
        }
    }
    /// True when the member names are exactly `names` (a set comparison).
    pub fn has_exactly(&self, names: &[&str]) -> bool {
        self.len() == names.len() && names.iter().all(|n| self.contains_key(n))
    }
}

impl Json {
    pub fn str(s: &str) -> Json {
        Json::Str(s.to_string())
    }
    pub fn as_obj(&self) -> Option<&Obj> {
        match self {
            Json::Object(o) => Some(o),
            _ => None,
        }
    }
    pub fn as_obj_mut(&mut self) -> Option<&mut Obj> {
        match self {
            Json::Object(o) => Some(o),
            _ => None,
        }
    }
    /// The string value, for both clean strings and lossy ones (a Python `str`
    /// either way).
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) | Json::BadStr(s, _) => Some(s),
            _ => None,
        }
    }
    pub fn as_arr(&self) -> Option<&[Json]> {
        match self {
            Json::Array(a) => Some(a),
            _ => None,
        }
    }
    /// `obj.get(key)` when `self` is an object, else None.
    pub fn get(&self, k: &str) -> Option<&Json> {
        self.as_obj().and_then(|o| o.get(k))
    }
    /// A Python `int` that is not a `bool`, as i128 when it fits.
    pub fn as_int(&self) -> Option<i128> {
        match self {
            Json::Int(t) => t.parse::<i128>().ok(),
            _ => None,
        }
    }
    pub fn is_int(&self) -> bool {
        matches!(self, Json::Int(_))
    }
}

/// Python `==` between two decoded JSON values: numbers compare by value across
/// int/float/bool (`True == 1 == 1.0`), containers element-wise, objects as
/// unordered maps.
pub fn py_eq(a: &Json, b: &Json) -> bool {
    fn num(v: &Json) -> Option<Num> {
        match v {
            Json::Bool(b) => Some(Num::I(*b as i128)),
            Json::Int(t) => Some(t.parse::<i128>().map(Num::I).unwrap_or(Num::Big(t.clone()))),
            Json::Float(f) => Some(Num::F(*f)),
            _ => None,
        }
    }
    enum Num {
        I(i128),
        Big(String),
        F(f64),
    }
    if let (Some(x), Some(y)) = (num(a), num(b)) {
        return match (x, y) {
            (Num::I(p), Num::I(q)) => p == q,
            (Num::Big(p), Num::Big(q)) => p == q,
            (Num::I(p), Num::F(f)) | (Num::F(f), Num::I(p)) => {
                f.is_finite() && f.fract() == 0.0 && (f as i128) == p && (p as f64) == f
            }
            (Num::F(f), Num::F(g)) => f == g,
            (Num::Big(t), Num::F(f)) | (Num::F(f), Num::Big(t)) => {
                f.is_finite() && f.fract() == 0.0 && format!("{f:.0}") == t
            }
            _ => false,
        };
    }
    match (a, b) {
        (Json::Null, Json::Null) => true,
        (Json::Str(x), Json::Str(y)) => x == y,
        (Json::BadStr(_, x), Json::BadStr(_, y)) => x == y,
        (Json::Array(x), Json::Array(y)) => {
            x.len() == y.len() && x.iter().zip(y).all(|(p, q)| py_eq(p, q))
        }
        (Json::Object(x), Json::Object(y)) => {
            x.len() == y.len() && x.iter().all(|(k, v)| y.get(k).is_some_and(|w| py_eq(v, w)))
        }
        _ => false,
    }
}

/// Is this a hashable Python value? A list or dict used as a set member or dict
/// key raises `TypeError` in the reference.
pub fn py_hashable(v: &Json) -> bool {
    !matches!(v, Json::Array(_) | Json::Object(_))
}

// ---------------------------------------------------------------- parsing ----

#[derive(Clone, Copy, PartialEq)]
enum Mode {
    /// loads_ijson: refuse dup keys, non-JSON constants, lone surrogates.
    Strict,
    /// json.loads: last dup wins, NaN/Infinity accepted, lone surrogates kept.
    Plain,
}

/// Why a parse failed. `Deep` is reported separately because the reference
/// names it ("malformed JSON (nesting too deep)").
#[derive(Debug, Clone, PartialEq)]
pub enum ParseError {
    Malformed(String),
    Deep,
    /// loads_ijson's duplicate-name refusal, carrying the name's exact code
    /// points (it may hold an unpaired surrogate the message must keep).
    Dup(Vec<u32>),
}

impl ParseError {
    /// The message as the Python string the reference would hold.
    pub fn to_json(&self) -> Json {
        match self {
            ParseError::Dup(u) => py_text("duplicate member name: ", u),
            other => Json::Str(other.to_string()),
        }
    }
}

/// A Python string `prefix + name`, where `name` is exact code points: a clean
/// `Str`, or a `BadStr` when the name holds an unpaired surrogate.
pub fn py_text(prefix: &str, units: &[u32]) -> Json {
    let mut all: Vec<u32> = prefix.chars().map(|c| c as u32).collect();
    all.extend_from_slice(units);
    let lossy: String = all
        .iter()
        .map(|&u| char::from_u32(u).unwrap_or('\u{fffd}'))
        .collect();
    if all.iter().all(|&u| char::from_u32(u).is_some()) {
        Json::Str(lossy)
    } else {
        Json::BadStr(lossy, all)
    }
}

/// `s[:n]` of a Python string value, surrogates kept.
pub fn py_slice(v: &Json, n: usize) -> Json {
    match v {
        Json::Str(s) => Json::Str(prefix(s, n)),
        Json::BadStr(_, u) => {
            let cut = &u[..u.len().min(n)];
            py_text("", cut)
        }
        other => other.clone(),
    }
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ParseError::Malformed(m) => f.write_str(m),
            ParseError::Deep => write!(f, "JSON nested deeper than {MAX_DEPTH} levels"),
            ParseError::Dup(u) => {
                let name: String = u
                    .iter()
                    .map(|&c| char::from_u32(c).unwrap_or('\u{fffd}'))
                    .collect();
                write!(f, "duplicate member name: {name}")
            }
        }
    }
}

/// The parser follows CPython's C scanner (`_json.c`) step for step, so that
/// the same bytes fail at the same position with the same message — those
/// messages reach reports (`resign`'s "unreadable envelope: ...", the probe's
/// parse errors). Positions are code-point indices, as in a Python `str`.
struct Parser<'a> {
    s: &'a [u32],
    mode: Mode,
    depth: usize,
}

/// A value scan that found no value at a position: the caller decides what
/// was expected there (CPython's `StopIteration(idx)`).
enum Scan {
    Stop(usize),
    Fail(ParseError),
}

impl From<ParseError> for Scan {
    fn from(e: ParseError) -> Self {
        Scan::Fail(e)
    }
}

fn err<T>(m: &str) -> Result<T, ParseError> {
    Err(ParseError::Malformed(m.to_string()))
}

impl<'a> Parser<'a> {
    fn ch(&self, i: usize) -> Option<char> {
        self.s
            .get(i)
            .map(|&u| char::from_u32(u).unwrap_or('\u{fffd}'))
    }

    /// `JSONDecodeError(msg, s, pos)` rendered as CPython renders it.
    fn decode_error(&self, msg: &str, pos: usize) -> ParseError {
        let nl = '\n' as u32;
        let lineno = self.s[..pos].iter().filter(|&&u| u == nl).count() + 1;
        let colno = match self.s[..pos].iter().rposition(|&u| u == nl) {
            Some(i) => pos - i,
            None => pos + 1,
        };
        ParseError::Malformed(format!("{msg}: line {lineno} column {colno} (char {pos})"))
    }

    fn ws(&self, mut i: usize) -> usize {
        while matches!(self.ch(i), Some(' ' | '\n' | '\r' | '\t')) {
            i += 1;
        }
        i
    }

    fn starts_with_at(&self, at: usize, t: &str) -> bool {
        let n = t.chars().count();
        self.s
            .get(at..at + n)
            .is_some_and(|w| w.iter().copied().eq(t.chars().map(|c| c as u32)))
    }

    /// `scan_once(s, idx)`.
    fn scan(&mut self, idx: usize) -> Result<(Json, usize), Scan> {
        let Some(c) = self.ch(idx) else {
            return Err(Scan::Stop(idx));
        };
        match c {
            '"' => {
                let (s, units, end) = self.string(idx + 1)?;
                Ok((
                    match units {
                        Some(u) => Json::BadStr(s, u),
                        None => Json::Str(s),
                    },
                    end,
                ))
            }
            '{' => self.nested(idx + 1, true),
            '[' => self.nested(idx + 1, false),
            'n' if self.starts_with_at(idx, "null") => Ok((Json::Null, idx + 4)),
            't' if self.starts_with_at(idx, "true") => Ok((Json::Bool(true), idx + 4)),
            'f' if self.starts_with_at(idx, "false") => Ok((Json::Bool(false), idx + 5)),
            'N' if self.starts_with_at(idx, "NaN") => self.constant("NaN", f64::NAN, idx + 3),
            'I' if self.starts_with_at(idx, "Infinity") => {
                self.constant("Infinity", f64::INFINITY, idx + 8)
            }
            '-' if self.starts_with_at(idx, "-Infinity") => {
                self.constant("-Infinity", f64::NEG_INFINITY, idx + 9)
            }
            _ => self.number(idx),
        }
    }

    fn constant(&self, name: &str, v: f64, end: usize) -> Result<(Json, usize), Scan> {
        if self.mode == Mode::Strict {
            return Err(Scan::Fail(ParseError::Malformed(format!(
                "invalid I-JSON constant: {name}"
            ))));
        }
        Ok((Json::Float(v), end))
    }

    fn nested(&mut self, idx: usize, is_obj: bool) -> Result<(Json, usize), Scan> {
        self.depth += 1;
        if self.depth > MAX_DEPTH {
            return Err(Scan::Fail(ParseError::Deep));
        }
        let r = if is_obj {
            self.object(idx)
        } else {
            self.array(idx)
        };
        self.depth -= 1;
        r
    }

    /// `_parse_object`: `idx` is just past the `{`.
    fn object(&mut self, idx: usize) -> Result<(Json, usize), Scan> {
        let mut o = Obj::new();
        // Indexed by exact code points: two different unpaired surrogates are
        // two different names, though both read as U+FFFD.
        let mut index: HashMap<Vec<u32>, usize> = HashMap::new();
        let mut first_dup: Option<Vec<u32>> = None;
        let mut i = self.ws(idx);
        if self.ch(i) == Some('}') {
            return Ok((Json::Object(o), i + 1));
        }
        loop {
            if self.ch(i) != Some('"') {
                return Err(self
                    .decode_error("Expecting property name enclosed in double quotes", i)
                    .into());
            }
            let (k, units, end) = self.string(i + 1)?;
            let exact: Vec<u32> = units
                .clone()
                .unwrap_or_else(|| k.chars().map(|c| c as u32).collect());
            i = self.ws(end);
            if self.ch(i) != Some(':') {
                return Err(self.decode_error("Expecting ':' delimiter", i).into());
            }
            i = self.ws(i + 1);
            let (v, end) = match self.scan(i) {
                Err(Scan::Stop(p)) => return Err(self.decode_error("Expecting value", p).into()),
                r => r?,
            };
            match index.get(&exact) {
                Some(&at) => {
                    if first_dup.is_none() {
                        first_dup = Some(exact.clone());
                    }
                    o.0[at].1 = v; // dict assignment: position kept, value replaced
                }
                None => {
                    index.insert(exact, o.0.len());
                    if let Some(u) = units {
                        o.1.push((o.0.len(), u));
                    }
                    o.0.push((k, v));
                }
            }
            i = self.ws(end);
            if self.ch(i) == Some('}') {
                i += 1;
                break;
            }
            if self.ch(i) != Some(',') {
                return Err(self.decode_error("Expecting ',' delimiter", i).into());
            }
            let comma = i;
            i = self.ws(i + 1);
            if self.ch(i) == Some('}') {
                return Err(self
                    .decode_error("Illegal trailing comma before end of object", comma)
                    .into());
            }
        }
        // loads_ijson's object_pairs_hook runs when the object is complete.
        if let (Mode::Strict, Some(k)) = (self.mode, first_dup) {
            return Err(Scan::Fail(ParseError::Dup(k)));
        }
        Ok((Json::Object(o), i))
    }

    /// `_parse_array`: `idx` is just past the `[`.
    fn array(&mut self, idx: usize) -> Result<(Json, usize), Scan> {
        let mut a = Vec::new();
        let mut i = self.ws(idx);
        if self.ch(i) == Some(']') {
            return Ok((Json::Array(a), i + 1));
        }
        loop {
            let (v, end) = match self.scan(i) {
                Err(Scan::Stop(p)) => return Err(self.decode_error("Expecting value", p).into()),
                r => r?,
            };
            a.push(v);
            i = self.ws(end);
            if self.ch(i) == Some(']') {
                return Ok((Json::Array(a), i + 1));
            }
            if self.ch(i) != Some(',') {
                return Err(self.decode_error("Expecting ',' delimiter", i).into());
            }
            let comma = i;
            i = self.ws(i + 1);
            if self.ch(i) == Some(']') {
                return Err(self
                    .decode_error("Illegal trailing comma before end of array", comma)
                    .into());
            }
        }
    }

    /// Four hex digits at `at`, if all four are there and are hex.
    fn hex4(&self, at: usize) -> Option<u32> {
        let d = self.s.get(at..at + 4)?;
        let mut v = 0u32;
        for &c in d {
            v = v * 16 + char::from_u32(c)?.to_digit(16)?;
        }
        Some(v)
    }

    /// `scanstring`: `idx` is just past the opening quote. Returns the string,
    /// whether it held an unpaired surrogate, and the index past the closing
    /// quote. Strict mode keeps the surrogate for now: loads_ijson refuses it
    /// only after the whole document has parsed.
    fn string(&mut self, idx: usize) -> Result<(String, Option<Vec<u32>>, usize), ParseError> {
        let begin = idx - 1;
        let mut out = String::new();
        let mut units: Vec<u32> = Vec::new();
        let mut lossy = false;
        let push = |out: &mut String, units: &mut Vec<u32>, lossy: &mut bool, u: u32| {
            units.push(u);
            match char::from_u32(u) {
                Some(ch) => out.push(ch),
                None => {
                    *lossy = true;
                    out.push('\u{fffd}');
                }
            }
        };
        let mut i = idx;
        loop {
            let Some(&u) = self.s.get(i) else {
                return Err(self.decode_error("Unterminated string starting at", begin));
            };
            if u == '"' as u32 {
                return Ok((out, lossy.then_some(units), i + 1));
            }
            if u < 0x20 {
                return Err(self.decode_error("Invalid control character at", i));
            }
            if u != '\\' as u32 {
                push(&mut out, &mut units, &mut lossy, u);
                i += 1;
                continue;
            }
            let bs = i;
            let Some(e) = self.ch(i + 1) else {
                return Err(self.decode_error("Unterminated string starting at", begin));
            };
            if e != 'u' {
                let c = match e {
                    '"' => '"',
                    '\\' => '\\',
                    '/' => '/',
                    'b' => '\u{8}',
                    'f' => '\u{c}',
                    'n' => '\n',
                    'r' => '\r',
                    't' => '\t',
                    _ => return Err(self.decode_error("Invalid \\escape", bs)),
                };
                push(&mut out, &mut units, &mut lossy, c as u32);
                i += 2;
                continue;
            }
            let Some(code) = self.hex4(i + 2) else {
                return Err(self.decode_error("Invalid \\uXXXX escape", i + 1));
            };
            i += 6;
            if (0xd800..=0xdbff).contains(&code)
                && self.ch(i) == Some('\\')
                && self.ch(i + 1) == Some('u')
            {
                let Some(low) = self.hex4(i + 2) else {
                    return Err(self.decode_error("Invalid \\uXXXX escape", i + 1));
                };
                if (0xdc00..=0xdfff).contains(&low) {
                    push(
                        &mut out,
                        &mut units,
                        &mut lossy,
                        0x10000 + ((code - 0xd800) << 10) + (low - 0xdc00),
                    );
                    i += 6;
                    continue;
                }
            }
            push(&mut out, &mut units, &mut lossy, code);
        }
    }

    /// `_match_number_unicode`.
    fn number(&self, start: usize) -> Result<(Json, usize), Scan> {
        let mut i = start;
        if self.ch(i) == Some('-') {
            i += 1;
        }
        match self.ch(i) {
            Some('1'..='9') => {
                i += 1;
                while self.ch(i).is_some_and(|c| c.is_ascii_digit()) {
                    i += 1;
                }
            }
            Some('0') => i += 1,
            _ => return Err(Scan::Stop(start)),
        }
        let int_end = i;
        let mut is_float = false;
        if self.ch(i) == Some('.') && self.ch(i + 1).is_some_and(|c| c.is_ascii_digit()) {
            i += 2;
            while self.ch(i).is_some_and(|c| c.is_ascii_digit()) {
                i += 1;
            }
            is_float = true;
        }
        if matches!(self.ch(i), Some('e' | 'E')) {
            let save = i;
            i += 1;
            if matches!(self.ch(i), Some('+' | '-')) {
                i += 1;
            }
            let digits = i;
            while self.ch(i).is_some_and(|c| c.is_ascii_digit()) {
                i += 1;
            }
            if i == digits {
                i = save;
            } else {
                is_float = true;
            }
        }
        let text: String = self.s[start..i]
            .iter()
            .filter_map(|&u| char::from_u32(u))
            .collect();
        if is_float {
            return Ok((Json::Float(text.parse::<f64>().unwrap_or(f64::NAN)), i));
        }
        let neg = text.starts_with('-');
        let ndigits = int_end - start - usize::from(neg);
        if ndigits > MAX_INT_DIGITS {
            return Err(Scan::Fail(ParseError::Malformed(format!(
                "Exceeds the limit ({MAX_INT_DIGITS} digits) for integer string conversion: value has {ndigits} digits; use sys.set_int_max_str_digits() to increase the limit"
            ))));
        }
        let mag = &text[usize::from(neg)..];
        Ok((
            Json::Int(if neg && mag != "0" {
                text.clone()
            } else {
                mag.to_string()
            }),
            i,
        ))
    }
}

/// The reference's explicit nesting bound, checked BEFORE parsing (so a deep
/// document is refused as deep even when it is also malformed further on):
/// count `[`/`{` outside strings, exactly as `_check_json_depth` does.
fn too_deep(s: &[u32]) -> bool {
    let (mut depth, mut in_str, mut esc) = (0i64, false, false);
    for &u in s {
        let c = char::from_u32(u).unwrap_or('\u{fffd}');
        if in_str {
            if esc {
                esc = false;
            } else if c == '\\' {
                esc = true;
            } else if c == '"' {
                in_str = false;
            }
        } else if c == '"' {
            in_str = true;
        } else if c == '[' || c == '{' {
            depth += 1;
            if depth > MAX_DEPTH as i64 {
                return true;
            }
        } else if c == ']' || c == '}' {
            depth -= 1;
        }
    }
    false
}

/// Does any string (or member name) in the value hold an unpaired surrogate?
fn has_lone_surrogate(v: &Json) -> bool {
    let mut stack = vec![v];
    while let Some(x) = stack.pop() {
        match x {
            Json::BadStr(..) => return true,
            Json::Array(a) => stack.extend(a.iter()),
            Json::Object(o) => {
                if o.lossy_keys() {
                    return true;
                }
                stack.extend(o.values());
            }
            _ => {}
        }
    }
    false
}

/// `json.loads(text)` (the decode step), over code units.
fn run(chars: &[u32], mode: Mode) -> Result<Json, ParseError> {
    if too_deep(chars) {
        return Err(ParseError::Deep);
    }
    let mut p = Parser {
        s: chars,
        mode,
        depth: 0,
    };
    let start = p.ws(0);
    let (v, end) = match p.scan(start) {
        Ok(r) => r,
        Err(Scan::Stop(at)) => return Err(p.decode_error("Expecting value", at)),
        Err(Scan::Fail(e)) => return Err(e),
    };
    let end = p.ws(end);
    if end != chars.len() {
        return Err(p.decode_error("Extra data", end));
    }
    if mode == Mode::Strict && has_lone_surrogate(&v) {
        return err("lone surrogate in string (invalid I-JSON)");
    }
    Ok(v)
}

/// `loads_ijson(text)`: the I-JSON profile of SPEC §4 over a decoded string.
pub fn parse_ijson_str(text: &str) -> Result<Json, ParseError> {
    if text.starts_with('\u{feff}') {
        return err("leading byte order mark (not canonical I-JSON)");
    }
    let units: Vec<u32> = text.chars().map(|c| c as u32).collect();
    run(&units, Mode::Strict)
}

/// `loads_ijson(raw.decode("utf-8"))`: invalid UTF-8 fails with Python's
/// codec message.
pub fn parse_ijson(raw: &[u8]) -> Result<Json, ParseError> {
    match std::str::from_utf8(raw) {
        Ok(t) => parse_ijson_str(t),
        Err(_) => Err(ParseError::Malformed(utf8_error(raw))),
    }
}

const BOM_MSG: &str = "Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)";

/// `json.loads(text)` on an already-decoded string.
pub fn parse_plain_str(text: &str) -> Result<Json, ParseError> {
    if text.starts_with('\u{feff}') {
        return err(BOM_MSG);
    }
    let units: Vec<u32> = text.chars().map(|c| c as u32).collect();
    run(&units, Mode::Plain)
}

/// `json.loads(raw.decode("utf-8"))` — the probe's request reader.
pub fn parse_plain_text(raw: &[u8]) -> Result<Json, ParseError> {
    match std::str::from_utf8(raw) {
        Ok(t) => parse_plain_str(t),
        Err(_) => Err(ParseError::Malformed(utf8_error(raw))),
    }
}

/// `json.loads(bytes)`: Python's encoding detection, `surrogatepass` decoding,
/// then the plain parser.
pub fn parse_plain_bytes(raw: &[u8]) -> Result<Json, ParseError> {
    let chars = decode_bytes(raw).ok_or(ParseError::Malformed("undecodable bytes".into()))?;
    if chars.first() == Some(&0xfeff) {
        return err(BOM_MSG);
    }
    run(&chars, Mode::Plain)
}

/// The message of the `UnicodeDecodeError` CPython's strict UTF-8 decoder
/// raises for `b`, which must not be valid UTF-8.
pub fn utf8_error(b: &[u8]) -> String {
    let mut i = 0;
    while i < b.len() {
        let c = b[i];
        let (n, lo2, hi2) = match c {
            0x00..=0x7f => {
                i += 1;
                continue;
            }
            0xc2..=0xdf => (2, 0x80, 0xbf),
            0xe0 => (3, 0xa0, 0xbf),
            0xed => (3, 0x80, 0x9f),
            0xe1..=0xef => (3, 0x80, 0xbf),
            0xf0 => (4, 0x90, 0xbf),
            0xf4 => (4, 0x80, 0x8f),
            0xf1..=0xf3 => (4, 0x80, 0xbf),
            _ => return codec_msg(b, i, i + 1, "invalid start byte"),
        };
        for k in 1..n {
            let Some(&x) = b.get(i + k) else {
                return codec_msg(b, i, b.len(), "unexpected end of data");
            };
            let (lo, hi) = if k == 1 { (lo2, hi2) } else { (0x80, 0xbf) };
            if !(lo..=hi).contains(&x) {
                return codec_msg(b, i, i + k, "invalid continuation byte");
            }
        }
        i += n;
    }
    "invalid UTF-8".into()
}

fn codec_msg(b: &[u8], start: usize, end: usize, why: &str) -> String {
    if end - start == 1 {
        format!(
            "'utf-8' codec can't decode byte 0x{:02x} in position {start}: {why}",
            b[start]
        )
    } else {
        format!(
            "'utf-8' codec can't decode bytes in position {start}-{}: {why}",
            end - 1
        )
    }
}

/// json.detect_encoding + `bytes.decode(enc, "surrogatepass")`.
fn decode_bytes(b: &[u8]) -> Option<Vec<u32>> {
    let enc = if b.starts_with(&[0, 0, 0xfe, 0xff]) || b.starts_with(&[0xff, 0xfe, 0, 0]) {
        "utf-32"
    } else if b.starts_with(&[0xfe, 0xff]) || b.starts_with(&[0xff, 0xfe]) {
        "utf-16"
    } else if b.starts_with(&[0xef, 0xbb, 0xbf]) {
        "utf-8-sig"
    } else if b.len() >= 4 {
        if b[0] == 0 {
            if b[1] != 0 {
                "utf-16-be"
            } else {
                "utf-32-be"
            }
        } else if b[1] == 0 {
            if b[2] != 0 || b[3] != 0 {
                "utf-16-le"
            } else {
                "utf-32-le"
            }
        } else {
            "utf-8"
        }
    } else if b.len() == 2 {
        if b[0] == 0 {
            "utf-16-be"
        } else if b[1] == 0 {
            "utf-16-le"
        } else {
            "utf-8"
        }
    } else {
        "utf-8"
    };
    match enc {
        "utf-8" => decode_utf8_surrogatepass(b),
        "utf-8-sig" => decode_utf8_surrogatepass(&b[3..]),
        "utf-16" => {
            let be = b[0] == 0xfe;
            decode_utf16(&b[2..], be)
        }
        "utf-16-be" => decode_utf16(b, true),
        "utf-16-le" => decode_utf16(b, false),
        "utf-32" => {
            let be = b[0] == 0;
            decode_utf32(&b[4..], be)
        }
        "utf-32-be" => decode_utf32(b, true),
        _ => decode_utf32(b, false),
    }
}

/// Strict UTF-8, except that encoded surrogates (ED A0..BF xx) decode to the
/// surrogate code unit itself, as Python's `surrogatepass` handler does.
fn decode_utf8_surrogatepass(b: &[u8]) -> Option<Vec<u32>> {
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        let c = b[i];
        if c == 0xed
            && i + 2 < b.len()
            && (0xa0..=0xbf).contains(&b[i + 1])
            && (0x80..=0xbf).contains(&b[i + 2])
        {
            out.push(0xd000 | ((b[i + 1] as u32 & 0x3f) << 6) | (b[i + 2] as u32 & 0x3f));
            i += 3;
            continue;
        }
        let n = match c {
            0x00..=0x7f => 1,
            0xc2..=0xdf => 2,
            0xe0..=0xef => 3,
            0xf0..=0xf4 => 4,
            _ => return None,
        };
        let s = std::str::from_utf8(b.get(i..i + n)?).ok()?;
        out.push(s.chars().next()? as u32);
        i += n;
    }
    Some(out)
}

fn decode_utf16(b: &[u8], be: bool) -> Option<Vec<u32>> {
    if b.len() % 2 != 0 {
        return None;
    }
    let units: Vec<u16> = b
        .chunks_exact(2)
        .map(|p| {
            if be {
                u16::from_be_bytes([p[0], p[1]])
            } else {
                u16::from_le_bytes([p[0], p[1]])
            }
        })
        .collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < units.len() {
        let u = units[i] as u32;
        if (0xd800..=0xdbff).contains(&u)
            && i + 1 < units.len()
            && (0xdc00..=0xdfff).contains(&(units[i + 1] as u32))
        {
            out.push(0x10000 + ((u - 0xd800) << 10) + (units[i + 1] as u32 - 0xdc00));
            i += 2;
        } else {
            out.push(u);
            i += 1;
        }
    }
    Some(out)
}

fn decode_utf32(b: &[u8], be: bool) -> Option<Vec<u32>> {
    if b.len() % 4 != 0 {
        return None;
    }
    let mut out = Vec::new();
    for p in b.chunks_exact(4) {
        let v = if be {
            u32::from_be_bytes([p[0], p[1], p[2], p[3]])
        } else {
            u32::from_le_bytes([p[0], p[1], p[2], p[3]])
        };
        if v > 0x10ffff {
            return None;
        }
        out.push(v);
    }
    Some(out)
}

// ------------------------------------------------------- canonicalization ----

/// Why a value has no canonical form (the reference's TypeError/ValueError).
#[derive(Debug, Clone)]
pub enum CanonError {
    /// A float or non-JSON constant: `TypeError("unsupported JSON value float")`.
    Float,
    /// The canonical text holds unpaired surrogates at code-point positions
    /// `start..end` (the first run of them), so UTF-8 encoding fails.
    Surrogate {
        start: usize,
        end: usize,
        first: u32,
    },
    /// A member NAME holds an unpaired surrogate: the reference fails while
    /// sorting the names (it orders them by their UTF-16 encoding), at the
    /// first such name in document order, at `pos` within that name.
    KeySurrogate { pos: usize, ch: u32 },
}

impl std::fmt::Display for CanonError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CanonError::Float => f.write_str("unsupported JSON value float"),
            CanonError::Surrogate { start, end, first } if end - start == 1 => write!(
                f,
                "'utf-8' codec can't encode character '\\u{first:04x}' in position {start}: surrogates not allowed"
            ),
            CanonError::KeySurrogate { pos, ch } => write!(
                f,
                "'utf-16-be' codec can't encode character '\\u{ch:04x}' in position {pos}: surrogates not allowed"
            ),
            CanonError::Surrogate { start, end, .. } => write!(
                f,
                "'utf-8' codec can't encode characters in position {start}-{}: surrogates not allowed",
                end - 1
            ),
        }
    }
}

fn units_of(v: &Json) -> Vec<u32> {
    match v {
        Json::BadStr(_, u) => u.clone(),
        Json::Str(s) => s.chars().map(|c| c as u32).collect(),
        _ => Vec::new(),
    }
}

/// SPEC §4: integer-domain RFC 8785 bytes, member names in UTF-16 order.
/// Iterative, so no input depth can exhaust a stack. Failures arrive in the
/// reference's order: values are visited depth-first in document order (an
/// object's names are sorted — by UTF-16 encoding — when it is reached), so a
/// float fails where it is visited, a surrogate in a name at that sort, and a
/// surrogate in a string value only when the finished text is encoded.
pub fn canon(v: &Json) -> Result<Vec<u8>, CanonError> {
    enum Item<'a> {
        Val(&'a Json),
        Raw(&'static str),
        Key(Vec<u32>),
    }
    let mut text: Vec<u32> = Vec::new();
    let mut stack = vec![Item::Val(v)];
    let raw = |text: &mut Vec<u32>, s: &str| text.extend(s.chars().map(|c| c as u32));
    while let Some(it) = stack.pop() {
        match it {
            Item::Raw(r) => raw(&mut text, r),
            Item::Key(k) => {
                quote_jcs_units(&k, &mut text);
                text.push(':' as u32);
            }
            Item::Val(v) => match v {
                Json::Null => raw(&mut text, "null"),
                Json::Bool(true) => raw(&mut text, "true"),
                Json::Bool(false) => raw(&mut text, "false"),
                Json::Int(t) => raw(&mut text, t),
                Json::Float(_) => return Err(CanonError::Float),
                Json::Str(_) | Json::BadStr(..) => quote_jcs_units(&units_of(v), &mut text),
                Json::Array(a) => {
                    stack.push(Item::Raw("]"));
                    for (i, item) in a.iter().enumerate().rev() {
                        stack.push(Item::Val(item));
                        if i > 0 {
                            stack.push(Item::Raw(","));
                        }
                    }
                    stack.push(Item::Raw("["));
                }
                Json::Object(o) => {
                    let mut entries: Vec<(Vec<u32>, &Json)> =
                        o.0.iter()
                            .enumerate()
                            .map(|(i, (_, val))| (o.key_units(i), val))
                            .collect();
                    for (k, _) in &entries {
                        if let Some(pos) = k.iter().position(|&u| (0xd800..=0xdfff).contains(&u)) {
                            return Err(CanonError::KeySurrogate { pos, ch: k[pos] });
                        }
                    }
                    // UTF-16 code-unit order; a lone surrogate is its own unit.
                    let utf16 = |u: &[u32]| -> Vec<u16> {
                        let mut out = Vec::new();
                        for &c in u {
                            match char::from_u32(c) {
                                Some(ch) => {
                                    let mut b = [0u16; 2];
                                    out.extend_from_slice(ch.encode_utf16(&mut b));
                                }
                                None => out.push(c as u16),
                            }
                        }
                        out
                    };
                    entries.sort_by(|(a, _), (b, _)| utf16(a).cmp(&utf16(b)));
                    stack.push(Item::Raw("}"));
                    for (i, (k, val)) in entries.into_iter().enumerate().rev() {
                        stack.push(Item::Val(val));
                        stack.push(Item::Key(k));
                        if i > 0 {
                            stack.push(Item::Raw(","));
                        }
                    }
                    stack.push(Item::Raw("{"));
                }
            },
        }
    }
    let is_sur = |u: u32| (0xd800..=0xdfff).contains(&u);
    if let Some(start) = text.iter().position(|&u| is_sur(u)) {
        let end = start + text[start..].iter().take_while(|&&u| is_sur(u)).count();
        return Err(CanonError::Surrogate {
            start,
            end,
            first: text[start],
        });
    }
    let mut out = Vec::with_capacity(text.len());
    for u in text {
        let mut buf = [0u8; 4];
        out.extend_from_slice(char::from_u32(u).unwrap().encode_utf8(&mut buf).as_bytes());
    }
    Ok(out)
}

/// JCS string escaping over code points (surrogates pass through raw, as
/// `json.dumps(ensure_ascii=False)` passes them).
fn quote_jcs_units(s: &[u32], out: &mut Vec<u32>) {
    out.push('"' as u32);
    for &u in s {
        let esc: Option<&str> = match u {
            0x22 => Some("\\\""),
            0x5c => Some("\\\\"),
            0x08 => Some("\\b"),
            0x09 => Some("\\t"),
            0x0a => Some("\\n"),
            0x0c => Some("\\f"),
            0x0d => Some("\\r"),
            _ => None,
        };
        match esc {
            Some(e) => out.extend(e.chars().map(|c| c as u32)),
            None if u < 0x20 => out.extend(format!("\\u{u:04x}").chars().map(|c| c as u32)),
            None => out.push(u),
        }
    }
    out.push('"' as u32);
}

/// `canon(doc) == raw`, where a value with no canonical form is simply not
/// canonical (the reference's `_canon_eq`).
pub fn canon_eq(doc: &Json, raw: &[u8]) -> bool {
    canon(doc).is_ok_and(|c| c == raw)
}

/// JCS string escaping (SPEC §4): short escapes incl. \b \f, lowercase \u00xx
/// for other controls, raw UTF-8 otherwise (no HTML escaping of <>&).
pub fn quote_jcs(s: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    for ch in s.chars() {
        match ch {
            '"' => out.extend_from_slice(b"\\\""),
            '\\' => out.extend_from_slice(b"\\\\"),
            '\u{8}' => out.extend_from_slice(b"\\b"),
            '\t' => out.extend_from_slice(b"\\t"),
            '\n' => out.extend_from_slice(b"\\n"),
            '\u{c}' => out.extend_from_slice(b"\\f"),
            '\r' => out.extend_from_slice(b"\\r"),
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

// ----------------------------------------------------------- serializing ----

/// `json.dumps` (ensure_ascii) of a string held as exact code points.
fn quote_ascii_units(s: &[u32], out: &mut String) {
    out.push('"');
    for &u in s {
        match char::from_u32(u) {
            Some(c) => {
                let mut one = String::new();
                quote_ascii(&c.to_string(), &mut one);
                out.push_str(&one[1..one.len() - 1]);
            }
            None => {
                let _ = write!(out, "\\u{u:04x}");
            }
        }
    }
    out.push('"');
}

/// `json.dumps(s)` with the default `ensure_ascii=True`.
pub fn quote_ascii(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    let _ = write!(out, "\\u{u:04x}");
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// Python `float.__repr__`, which `json.dumps` and `str()` both use.
pub fn py_float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if f == 0.0 {
        return if f.is_sign_negative() {
            "-0.0".into()
        } else {
            "0.0".into()
        };
    }
    let sci = format!("{:e}", f.abs()); // shortest round-trip digits: d.ddde±x
    let (mant, exp) = sci.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let digits: String = mant.chars().filter(|c| *c != '.').collect();
    let decpt = exp + 1;
    let sign = if f < 0.0 { "-" } else { "" };
    let body = if -4 < decpt && decpt <= 16 {
        let n = digits.len() as i32;
        if decpt <= 0 {
            format!("0.{}{}", "0".repeat((-decpt) as usize), digits)
        } else if decpt >= n {
            format!("{}{}.0", digits, "0".repeat((decpt - n) as usize))
        } else {
            format!(
                "{}.{}",
                &digits[..decpt as usize],
                &digits[decpt as usize..]
            )
        }
    } else {
        let e = decpt - 1;
        let m = if digits.len() > 1 {
            format!("{}.{}", &digits[..1], &digits[1..])
        } else {
            digits.clone()
        };
        format!("{}e{}{:02}", m, if e < 0 { '-' } else { '+' }, e.abs())
    };
    format!("{sign}{body}")
}

fn dumps_scalar(v: &Json, out: &mut String) {
    match v {
        Json::Null => out.push_str("null"),
        Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Json::Int(t) => out.push_str(t),
        Json::Float(f) => {
            if f.is_nan() {
                out.push_str("NaN")
            } else if f.is_infinite() {
                out.push_str(if *f > 0.0 { "Infinity" } else { "-Infinity" })
            } else {
                out.push_str(&py_float_repr(*f))
            }
        }
        Json::Str(s) => quote_ascii(s, out),
        Json::BadStr(_, u) => quote_ascii_units(u, out),
        _ => unreachable!(),
    }
}

/// `json.dumps(v, separators=(",", ":"), ensure_ascii=True)` — insertion order.
pub fn dumps_compact(v: &Json) -> String {
    let mut out = String::new();
    compact_into(v, &mut out);
    out
}

fn compact_into(v: &Json, out: &mut String) {
    match v {
        Json::Array(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                compact_into(x, out);
            }
            out.push(']');
        }
        Json::Object(o) => {
            out.push('{');
            for (i, (_, x)) in o.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                quote_ascii_units(&o.key_units(i), out);
                out.push(':');
                compact_into(x, out);
            }
            out.push('}');
        }
        _ => dumps_scalar(v, out),
    }
}

/// `json.dumps(v)` with default separators `(", ", ": ")`, insertion order.
pub fn dumps_default(v: &Json) -> String {
    let mut out = String::new();
    default_into(v, &mut out);
    out
}

fn default_into(v: &Json, out: &mut String) {
    match v {
        Json::Array(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                default_into(x, out);
            }
            out.push(']');
        }
        Json::Object(o) => {
            out.push('{');
            for (i, (_, x)) in o.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                quote_ascii_units(&o.key_units(i), out);
                out.push_str(": ");
                default_into(x, out);
            }
            out.push('}');
        }
        _ => dumps_scalar(v, out),
    }
}

/// `json.dumps(v, indent=2, sort_keys=True)` — the store's one record writer.
pub fn dumps_pretty_sorted(v: &Json) -> String {
    let mut out = String::new();
    pretty_into(v, 0, &mut out);
    out
}

fn pretty_into(v: &Json, level: usize, out: &mut String) {
    let pad = |n: usize, out: &mut String| {
        out.push('\n');
        for _ in 0..n * 2 {
            out.push(' ');
        }
    };
    match v {
        Json::Array(a) if a.is_empty() => out.push_str("[]"),
        Json::Object(o) if o.is_empty() => out.push_str("{}"),
        Json::Array(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                pad(level + 1, out);
                pretty_into(x, level + 1, out);
            }
            pad(level, out);
            out.push(']');
        }
        Json::Object(o) => {
            let mut entries: Vec<(Vec<u32>, &Json)> =
                o.0.iter()
                    .enumerate()
                    .map(|(i, (_, x))| (o.key_units(i), x))
                    .collect();
            entries.sort_by(|(a, _), (b, _)| a.cmp(b));
            out.push('{');
            for (i, (k, x)) in entries.into_iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                pad(level + 1, out);
                quote_ascii_units(&k, out);
                out.push_str(": ");
                pretty_into(x, level + 1, out);
            }
            pad(level, out);
            out.push('}');
        }
        _ => dumps_scalar(v, out),
    }
}

// -------------------------------------------------- Python str() / repr() ----

/// Is `c` printable by Python's `str.isprintable` (used by `repr`)? Exact for
/// ASCII and Latin-1; outside that, the non-printable classes a record is
/// plausibly going to contain (format and separator characters, private use,
/// noncharacters) are covered, and everything else is treated as printable.
fn py_printable(c: char) -> bool {
    let u = c as u32;
    if u < 0x20 || (0x7f..=0xa0).contains(&u) || u == 0xad {
        return false;
    }
    if u < 0x100 {
        return true;
    }
    !matches!(u,
        0x034f | 0x061c | 0x115f..=0x1160 | 0x1680 | 0x17b4..=0x17b5 | 0x180b..=0x180f
        | 0x2000..=0x200f | 0x2028..=0x202f | 0x205f..=0x206f | 0x3000 | 0x3164
        | 0xd800..=0xf8ff | 0xfe00..=0xfe0f | 0xfeff | 0xffa0 | 0xfff0..=0xfffb
        | 0xfffe..=0xffff | 0x1bca0..=0x1bca3 | 0x1d173..=0x1d17a | 0xe0000..=0xe0fff
        | 0xf0000..=0x10ffff)
}

/// Python `repr(str)`.
pub fn py_repr_str(s: &str) -> String {
    let q = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::new();
    out.push(q);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == q => {
                out.push('\\');
                out.push(c);
            }
            c if py_printable(c) => out.push(c),
            c => {
                let u = c as u32;
                if u < 0x100 {
                    let _ = write!(out, "\\x{u:02x}");
                } else if u < 0x10000 {
                    let _ = write!(out, "\\u{u:04x}");
                } else {
                    let _ = write!(out, "\\U{u:08x}");
                }
            }
        }
    }
    out.push(q);
    out
}

/// Python `repr(str)` of a string held as exact code points: an unpaired
/// surrogate is not printable, so it shows as `\udXXX`.
pub fn py_repr_units(u: &[u32]) -> String {
    let lossy: String = u
        .iter()
        .map(|&c| char::from_u32(c).unwrap_or('\u{fffd}'))
        .collect();
    let q = if lossy.contains('\'') && !lossy.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::new();
    out.push(q);
    for &c in u {
        match char::from_u32(c) {
            Some(ch) => {
                let r = py_repr_str(&ch.to_string());
                // reuse the single-character rendering, under this string's quote
                let inner = &r[1..r.len() - 1];
                if ch == q {
                    out.push('\\');
                    out.push(ch);
                } else if (ch == '\'' || ch == '"') && inner.starts_with('\\') {
                    out.push(ch);
                } else {
                    out.push_str(inner);
                }
            }
            None => {
                let _ = write!(out, "\\u{c:04x}");
            }
        }
    }
    out.push(q);
    out
}

/// Python `repr()` of a decoded JSON value.
pub fn py_repr(v: &Json) -> String {
    match v {
        Json::Null => "None".into(),
        Json::Bool(true) => "True".into(),
        Json::Bool(false) => "False".into(),
        Json::Int(t) => t.clone(),
        Json::Float(f) => py_float_repr(*f),
        Json::Str(s) => py_repr_str(s),
        Json::BadStr(_, u) => py_repr_units(u),
        Json::Array(a) => {
            let parts: Vec<String> = a.iter().map(py_repr).collect();
            format!("[{}]", parts.join(", "))
        }
        Json::Object(o) => {
            let parts: Vec<String> = o
                .0
                .iter()
                .enumerate()
                .map(|(i, (_, x))| format!("{}: {}", py_repr_units(&o.key_units(i)), py_repr(x)))
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
    }
}

/// Python `str()` (what an f-string interpolates): a string is itself.
pub fn py_str(v: &Json) -> String {
    match v {
        Json::Str(s) | Json::BadStr(s, _) => s.clone(),
        _ => py_repr(v),
    }
}

/// `str(x)` of an optional member: a missing member is Python's `None`.
pub fn py_str_opt(v: Option<&Json>) -> String {
    v.map(py_str).unwrap_or_else(|| "None".into())
}

/// `s[:n]` on a Python string (code points, not bytes).
pub fn prefix(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn float_repr_matches_python() {
        for (f, want) in [
            (1.5, "1.5"),
            (1e16, "1e+16"),
            (1e15, "1000000000000000.0"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (-2.5e-7, "-2.5e-07"),
            (123456789.125, "123456789.125"),
            (1e100, "1e+100"),
            (3.0, "3.0"),
            (0.1, "0.1"),
        ] {
            assert_eq!(py_float_repr(f), want, "{f}");
        }
    }

    #[test]
    fn strict_refuses_what_ijson_refuses() {
        assert!(parse_ijson(br#"{"a":1,"a":2}"#).is_err());
        assert!(parse_ijson(br#"[NaN]"#).is_err());
        assert!(parse_ijson(br#"["\ud800"]"#).is_err());
        assert!(parse_ijson(b"\xef\xbb\xbf{}").is_err());
        assert!(parse_ijson(br#"[1.]"#).is_err());
        assert!(parse_ijson(br#"[1e]"#).is_err());
        assert!(parse_ijson(br#"["\ud83d\ude00"]"#).is_ok());
        assert!(parse_ijson("[\"\u{1F600}\"]".as_bytes()).is_ok());
    }

    #[test]
    fn plain_keeps_last_duplicate_in_first_position() {
        let v = parse_plain_bytes(br#"{"a":1,"b":2,"a":3}"#).unwrap();
        assert_eq!(dumps_compact(&v), r#"{"a":3,"b":2}"#);
        assert!(!canon_eq(&v, br#"{"a":1,"b":2,"a":3}"#));
    }

    #[test]
    fn depth_is_bounded() {
        let deep = "[".repeat(MAX_DEPTH + 1) + &"]".repeat(MAX_DEPTH + 1);
        assert!(matches!(
            parse_ijson(deep.as_bytes()),
            Err(ParseError::Deep)
        ));
        let ok = "[".repeat(MAX_DEPTH) + &"]".repeat(MAX_DEPTH);
        assert!(parse_ijson(ok.as_bytes()).is_ok());
    }

    #[test]
    fn utf16_blob_parses_but_is_not_canonical() {
        let text = r#"{"a":1}"#;
        let mut raw = vec![0xff, 0xfe];
        for u in text.encode_utf16() {
            raw.extend_from_slice(&u.to_le_bytes());
        }
        let v = parse_plain_bytes(&raw).unwrap();
        assert!(!canon_eq(&v, &raw));
    }

    #[test]
    fn repr_quotes_like_python() {
        assert_eq!(py_repr_str("a'b"), "\"a'b\"");
        assert_eq!(py_repr_str("a'b\""), "'a\\'b\"'");
        assert_eq!(
            py_repr(&parse_plain_str(r#"{"x":[1,true,null,"y"]}"#).unwrap()),
            "{'x': [1, True, None, 'y']}"
        );
    }
}
