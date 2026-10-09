//! `ski@v1` (SPEC §3.1): Σ-GLYPH Book I v0.5 hash-thunk evaluation, re-executed
//! against the Warrant blob store, which IS a Σ-GLYPH content-addressed store.
//!
//! The evaluator is a port of `impl/sigma_glyph_v05.py` — the module the
//! reference pins by digest for this tag — including its non-canonical local
//! limits (the resource faults of Book I §3.6) and the cadence at which they are
//! checked, because a limit checked at a different moment produces a different
//! report on the same store.

use crate::hash::{blob_hash, encode_hex, is_hex64, sha256, Hash};
use crate::json::{canon_eq, parse_plain_bytes, Json};
use std::rc::Rc;

/// SPEC §3.1 local re-execution budget (`WARRANT_SKI_MAX_ATP`, default 1e8).
/// Operators MAY raise it, accepting the divergence that implies.
pub fn reexec_max_atp() -> Result<i128, String> {
    match std::env::var("WARRANT_SKI_MAX_ATP") {
        Err(_) => Ok(100_000_000),
        Ok(v) => py_int(&v).ok_or_else(|| format!("invalid literal for int() with base 10: {v:?}")),
    }
}

/// Python `int(str)`: surrounding whitespace, an optional sign, decimal digits
/// with single underscores between them. Saturates far beyond any uint32 atp.
fn py_int(s: &str) -> Option<i128> {
    let t = s.trim();
    let (neg, digits) = match t.as_bytes().first() {
        Some(b'-') => (true, &t[1..]),
        Some(b'+') => (false, &t[1..]),
        _ => (false, t),
    };
    if digits.is_empty()
        || digits.starts_with('_')
        || digits.ends_with('_')
        || digits.contains("__")
    {
        return None;
    }
    let clean: String = digits.chars().filter(|c| *c != '_').collect();
    if !clean.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let mag = clean.parse::<i128>().unwrap_or(i128::MAX / 2);
    Some(if neg { -mag } else { mag })
}

/// One stable, path-free reason for every Identity-by-Hash violation.
pub const REASON_CAS_MISMATCH: &str = "content does not match its address";

// ------------------------------------------------------------- Book I ----

const LITERAL: u8 = 0x00;
const REF: u8 = 0x01;
const APPLY: u8 = 0x02;
const DISSONANCE: u8 = 0xff;
const F_ATOM: u8 = 0x01;
const F_LEFT: u8 = 0x02;
const F_RIGHT: u8 = 0x04;

fn ser(op: u8, flags: u8, parts: &[&Hash]) -> Vec<u8> {
    let mut b = vec![op, flags];
    for p in parts {
        b.extend_from_slice(&p[..]);
    }
    b
}

struct Genesis {
    i: Hash,
    k: Hash,
    s: Hash,
    i_bytes: Vec<u8>,
    k_bytes: Vec<u8>,
    s_bytes: Vec<u8>,
    r_invalid: Hash,
    r_atp: Hash,
    r_unres: Hash,
}

fn genesis() -> Genesis {
    let i_bytes = ser(LITERAL, F_ATOM, &[&sha256(b"I")]);
    let k_bytes = ser(LITERAL, F_ATOM, &[&sha256(b"K")]);
    let s_bytes = ser(LITERAL, F_ATOM, &[&sha256(b"S")]);
    Genesis {
        i: sha256(&i_bytes),
        k: sha256(&k_bytes),
        s: sha256(&s_bytes),
        i_bytes,
        k_bytes,
        s_bytes,
        r_invalid: sha256(b"Invalid Object"),
        r_atp: sha256(b"ATP Exhausted"),
        r_unres: sha256(b"Unresolved Reference"),
    }
}

/// A term of the hash-thunk machine. Children are shared, exactly as the
/// reference's tuples are, so R-S duplication costs no copying.
pub enum Term {
    Thunk(Hash),
    Lit(Hash),
    Ref(Hash),
    Dis(Hash),
    App(Rc<Term>, Rc<Term>),
}

fn term_hash(t: &Term) -> Hash {
    match t {
        Term::Thunk(h) => *h,
        Term::Lit(a) => sha256(&ser(LITERAL, F_ATOM, &[a])),
        Term::Ref(a) => sha256(&ser(REF, F_ATOM, &[a])),
        Term::Dis(a) => sha256(&ser(DISSONANCE, F_ATOM, &[a])),
        Term::App(l, r) => sha256(&ser(
            APPLY,
            F_LEFT | F_RIGHT,
            &[&term_hash(l), &term_hash(r)],
        )),
    }
}

/// Hash-leaf size model; saturating, so a pathological term compares as huge
/// rather than wrapping.
fn size(t: &Term) -> u64 {
    match t {
        Term::App(l, r) => 1u64.saturating_add(size(l)).saturating_add(size(r)),
        Term::Ref(_) => 2,
        _ => 1,
    }
}

fn depth(t: &Term) -> u64 {
    match t {
        Term::App(l, r) => 1 + depth(l).max(depth(r)),
        _ => 1,
    }
}

fn glyph_eq(t: &Term, gh: &Hash) -> bool {
    match t {
        Term::Thunk(h) => h == gh,
        Term::Lit(a) => &sha256(&ser(LITERAL, F_ATOM, &[a])) == gh,
        _ => false,
    }
}

/// The store side of evaluation: bytes for a hash, or None when absent.
/// An `Err` is a store that returned bytes not at their address.
pub trait Cas {
    fn get(&mut self, h: &Hash) -> Result<Option<Vec<u8>>, CasMismatch>;
}

pub struct CasMismatch;

/// Local, non-canonical faults (Book I §3.6), and the store's address lie.
enum Fault {
    Resource(&'static str),
    Cas,
}

enum Stop {
    Budget,
    Unresolved,
    Fault(Fault),
}

struct Limits {
    max_node_depth: u64,
    max_materialized_nodes: u64,
    max_store_fetches: u64,
}

struct Machine<'a> {
    g: &'a Genesis,
    store: &'a mut dyn Cas,
    fetches: u64,
    limits: Limits,
}

fn deser(b: &[u8]) -> Option<(u8, Vec<Hash>)> {
    if b.len() < 2 {
        return None;
    }
    let (op, flags) = (b[0], b[1]);
    if flags & !0x07 != 0 {
        return None;
    }
    let req = match op {
        LITERAL | REF | DISSONANCE => F_ATOM,
        APPLY => F_LEFT | F_RIGHT,
        _ => return None,
    };
    if flags != req {
        return None;
    }
    let n = flags.count_ones() as usize;
    if b.len() != 2 + 32 * n {
        return None;
    }
    let parts = (0..n)
        .map(|i| b[2 + 32 * i..2 + 32 * (i + 1)].try_into().unwrap())
        .collect();
    Some((op, parts))
}

impl<'a> Machine<'a> {
    fn is_genesis(&self, h: &Hash) -> bool {
        h == &self.g.i || h == &self.g.k || h == &self.g.s
    }

    fn force(&mut self, h: &Hash) -> Result<Term, Stop> {
        self.fetches += 1;
        if self.fetches > self.limits.max_store_fetches {
            return Err(Stop::Fault(Fault::Resource("fetches")));
        }
        let bytes = if h == &self.g.i {
            self.g.i_bytes.clone()
        } else if h == &self.g.k {
            self.g.k_bytes.clone()
        } else if h == &self.g.s {
            self.g.s_bytes.clone()
        } else {
            match self.store.get(h) {
                Err(CasMismatch) => return Err(Stop::Fault(Fault::Cas)),
                Ok(None) => return Err(Stop::Unresolved),
                Ok(Some(b)) => {
                    // Book I §4.1 Identity by Hash, enforced inside the
                    // evaluator too (the reference's "CAS key mismatch").
                    if &sha256(&b) != h {
                        return Err(Stop::Fault(Fault::Cas));
                    }
                    b
                }
            }
        };
        Ok(match deser(&bytes) {
            None => Term::Dis(self.g.r_invalid),
            Some((LITERAL, p)) => Term::Lit(p[0]),
            Some((REF, p)) => Term::Ref(p[0]),
            Some((DISSONANCE, p)) => Term::Dis(p[0]),
            Some((_, p)) => Term::App(Rc::new(Term::Thunk(p[0])), Rc::new(Term::Thunk(p[1]))),
        })
    }

    /// One priced action, leftmost-outermost with lazy spine resolution:
    /// Ok(None) = normal form, Ok(Some((term, cost))) = a step.
    fn step(&mut self, t: &Rc<Term>, remaining: u64) -> Result<Option<(Rc<Term>, u64)>, Stop> {
        match &**t {
            Term::Thunk(h) => {
                if self.is_genesis(h) {
                    return Ok(None);
                }
                if remaining < 1 {
                    return Err(Stop::Budget);
                }
                let v = self.force(h)?;
                let c = size(&v);
                if c > remaining {
                    return Err(Stop::Budget);
                }
                Ok(Some((Rc::new(v), c)))
            }
            Term::Ref(h) => {
                if remaining < 1 {
                    return Err(Stop::Budget);
                }
                Ok(Some((Rc::new(Term::Thunk(*h)), 1)))
            }
            Term::App(f, a) => {
                let g = self.g;
                if glyph_eq(f, &g.i) {
                    if remaining < 1 {
                        return Err(Stop::Budget);
                    }
                    return Ok(Some((a.clone(), 1)));
                }
                if let Term::App(f1, f2) = &**f {
                    if glyph_eq(f1, &g.k) {
                        if remaining < 1 {
                            return Err(Stop::Budget);
                        }
                        return Ok(Some((f2.clone(), 1)));
                    }
                    if let Term::App(s0, x) = &**f1 {
                        if glyph_eq(s0, &g.s) {
                            let (y, z) = (f2, a);
                            let c = 1u64.saturating_add(size(z));
                            if c > remaining {
                                return Err(Stop::Budget);
                            }
                            let xz = Rc::new(Term::App(x.clone(), z.clone()));
                            let yz = Rc::new(Term::App(y.clone(), z.clone()));
                            return Ok(Some((Rc::new(Term::App(xz, yz)), c)));
                        }
                    }
                }
                if let Some((nf, c)) = self.step(f, remaining)? {
                    return Ok(Some((Rc::new(Term::App(nf, a.clone())), c)));
                }
                if let Some((na, c)) = self.step(a, remaining)? {
                    return Ok(Some((Rc::new(Term::App(f.clone(), na)), c)));
                }
                Ok(None)
            }
            _ => Ok(None),
        }
    }

    fn resource_check(&self, t: &Term) -> Result<(), Stop> {
        if size(t) > self.limits.max_materialized_nodes {
            return Err(Stop::Fault(Fault::Resource("term growth")));
        }
        if depth(t) > self.limits.max_node_depth {
            return Err(Stop::Fault(Fault::Resource("term depth")));
        }
        Ok(())
    }
}

/// What a re-execution can end in that is NOT a verdict.
#[derive(Debug, Clone, PartialEq)]
pub enum EvalFault {
    /// `resource fault: <what>` — a local limit (Book I §3.6).
    Resource(String),
    /// The store returned bytes not at their address.
    CasMismatch,
}

/// `eval_hash(term, atp, store)`: the result term's hash and the ATP spent.
pub fn eval_hash(term: &Hash, atp: u64, store: &mut dyn Cas) -> Result<(Hash, u64), EvalFault> {
    let g = genesis();
    let mut m = Machine {
        g: &g,
        store,
        fetches: 0,
        limits: Limits {
            max_node_depth: 4096,
            max_materialized_nodes: 1_000_000,
            max_store_fetches: 1_000_000,
        },
    };
    let mut t: Rc<Term> = Rc::new(Term::Thunk(*term));
    let mut spent: u64 = 0;
    let mut steps: u64 = 0;
    let fault = |f: Fault| match f {
        Fault::Resource(w) => EvalFault::Resource(w.to_string()),
        Fault::Cas => EvalFault::CasMismatch,
    };
    loop {
        steps += 1;
        if steps % 256 == 0 {
            if let Err(Stop::Fault(f)) = m.resource_check(&t) {
                return Err(fault(f));
            }
        }
        match m.step(&t, atp - spent) {
            Err(Stop::Budget) => return Ok((term_hash(&Term::Dis(g.r_atp)), spent)),
            Err(Stop::Unresolved) => return Ok((term_hash(&Term::Dis(g.r_unres)), spent)),
            Err(Stop::Fault(f)) => return Err(fault(f)),
            Ok(None) => {
                if let Err(Stop::Fault(f)) = m.resource_check(&t) {
                    return Err(fault(f));
                }
                return Ok((term_hash(&t), spent));
            }
            Ok(Some((next, c))) => {
                t = next;
                spent += c;
            }
        }
    }
}

// --------------------------------------------------- the Warrant side ----

/// A ski@v1 check blob (SPEC §3.1), validated.
pub struct SkiDoc {
    pub term: Hash,
    pub atp: u64,
    pub expect: String,
}

/// SPEC §3.1's check-blob shape, with the reference's messages.
pub fn validate_ski_blob(doc: &Json) -> Option<String> {
    let o = match doc.as_obj() {
        Some(o) if o.has_exactly(&["ski", "term", "atp", "expect"]) => o,
        _ => return Some("ski check blob must be exactly {ski, term, atp, expect}".into()),
    };
    // An integer 1, not merely something equal to it: `true == 1` in Python,
    // and a `"ski": true` blob is not a v1 document (the reference is fixed to
    // agree, as Go always did).
    if !matches!(o.get("ski"), Some(Json::Int(t)) if t == "1") {
        return Some("ski field must be 1".into());
    }
    let hx = |k: &str| o.get(k).and_then(Json::as_str).is_some_and(is_hex64);
    if !(hx("term") && hx("expect")) {
        return Some("term and expect must be hex64 NodeHashes".into());
    }
    if !o
        .get("atp")
        .unwrap()
        .as_int()
        .is_some_and(|n| (0..1i128 << 32).contains(&n))
    {
        return Some("atp must be a uint32".into());
    }
    None
}

fn hash_from_hex(s: &str) -> Hash {
    let b = crate::hash::fromhex(s).unwrap();
    b.try_into().unwrap()
}

/// Blobs of a Warrant store, as a Σ-GLYPH CAS that refuses bytes not at their
/// address (defence in depth at the adapter, as the reference does).
pub struct BlobCas<'a> {
    pub dir: &'a std::path::Path,
}

impl Cas for BlobCas<'_> {
    fn get(&mut self, h: &Hash) -> Result<Option<Vec<u8>>, CasMismatch> {
        let p = self.dir.join(encode_hex(h));
        if !p.is_file() {
            // Absent, or not a regular file: unresolved, as `has_blob` says.
            return Ok(None);
        }
        match std::fs::read(&p) {
            Ok(b) if &sha256(&b) == h => Ok(Some(b)),
            Ok(_) => Err(CasMismatch),
            // Present but unreadable: it cannot be shown to be the addressed bytes.
            Err(_) => Err(CasMismatch),
        }
    }
}

/// `_load_ski_doc`: resolve and validate the check blob AT ITS ADDRESS.
pub fn load_ski_doc(
    blobs: &std::path::Path,
    check_hex: &str,
    max_atp: i128,
) -> Result<SkiDoc, String> {
    let p = blobs.join(check_hex);
    if !(is_hex64(check_hex) && p.is_file()) {
        return Err("check blob missing".into());
    }
    let raw = std::fs::read(&p).map_err(|_| "check blob missing".to_string())?;
    if blob_hash(&raw) != check_hex {
        return Err(REASON_CAS_MISMATCH.into());
    }
    let doc = match parse_plain_bytes(&raw) {
        Ok(d) => d,
        Err(_) => return Err("malformed check blob (not JSON)".into()),
    };
    if !canon_eq(&doc, &raw) {
        return Err("malformed check blob (not JCS-canonical)".into());
    }
    if let Some(e) = validate_ski_blob(&doc) {
        return Err(format!("invalid ski check blob: {e}"));
    }
    let o = doc.as_obj().unwrap();
    let atp = o.get("atp").unwrap().as_int().unwrap();
    if atp > max_atp {
        return Err("atp exceeds re-execution budget".into());
    }
    Ok(SkiDoc {
        term: hash_from_hex(o.get("term").unwrap().as_str().unwrap()),
        atp: atp as u64,
        expect: o.get("expect").unwrap().as_str().unwrap().to_string(),
    })
}

/// The outcome of re-running a check: (verdict, result NodeHash hex, ATP spent).
pub type SkiOutcome = (String, String, u64);

/// `run_ski_check`: re-execute a ski@v1 check against the blob store. An `Err`
/// is a bounded reason class — never a verdict.
pub fn run_ski_check(blobs: &std::path::Path, check_hex: &str) -> Result<SkiOutcome, String> {
    let max_atp = reexec_max_atp()?;
    let doc = load_ski_doc(blobs, check_hex, max_atp)?;
    let mut cas = BlobCas { dir: blobs };
    match eval_on_big_stack(doc.term, doc.atp, &mut cas) {
        Ok((rh, spent)) => {
            let rh = encode_hex(&rh);
            let verdict = if rh == doc.expect { "pass" } else { "fail" };
            Ok((verdict.to_string(), rh, spent))
        }
        Err(EvalFault::CasMismatch) => Err(REASON_CAS_MISMATCH.into()),
        Err(EvalFault::Resource(w)) => Err(format!("resource fault: {w}")),
    }
}

/// Evaluation recurses along the left spine and through term size/depth, up to
/// the 4096-node depth limit plus one sampling interval. Give it a stack sized
/// for that regardless of the caller's thread.
pub fn eval_on_big_stack(
    term: Hash,
    atp: u64,
    cas: &mut (dyn Cas + Send),
) -> Result<(Hash, u64), EvalFault> {
    std::thread::scope(|s| {
        std::thread::Builder::new()
            .stack_size(512 << 20)
            .spawn_scoped(s, move || eval_hash(&term, atp, cas))
            .expect("spawn evaluator thread")
            .join()
            .unwrap_or(Err(EvalFault::Resource("evaluator panic".into())))
    })
}

/// An in-memory CAS, for tests and the conformance probe's scratch stores.
pub struct MemCas(pub std::collections::HashMap<Hash, Vec<u8>>);

impl Cas for MemCas {
    fn get(&mut self, h: &Hash) -> Result<Option<Vec<u8>>, CasMismatch> {
        Ok(self.0.get(h).cloned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn put(m: &mut MemCas, b: Vec<u8>) -> Hash {
        let h = sha256(&b);
        m.0.insert(h, b);
        h
    }

    #[test]
    fn book_one_vectors() {
        let g = genesis();
        assert_eq!(
            encode_hex(&g.i),
            "2f33694d09810641fa5b8c47a7c0dc42e1b99eb8c9784a00aaee9a66330f4162"
        );
        assert_eq!(
            encode_hex(&g.s),
            "887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6"
        );
        let mut st = MemCas(HashMap::new());
        let app = |l: &Hash, r: &Hash| ser(APPLY, 6, &[l, r]);
        // I·K -> K, 4 ATP; budget 2 -> exhausted with nothing spent
        let ik = put(&mut st, app(&g.i, &g.k));
        assert_eq!(eval_hash(&ik, 4, &mut st).ok(), Some((g.k, 4)));
        let atp = term_hash(&Term::Dis(g.r_atp));
        assert_eq!(eval_hash(&ik, 2, &mut st).ok(), Some((atp, 0)));
        // SKK·I -> I, 12 ATP
        let sk = put(&mut st, app(&g.s, &g.k));
        let skk = put(&mut st, app(&sk, &g.k));
        let skki = put(&mut st, app(&skk, &g.i));
        assert_eq!(eval_hash(&skki, 100, &mut st).ok(), Some((g.i, 12)));
        // Omega exhausts deterministically
        let si = put(&mut st, app(&g.s, &g.i));
        let w = put(&mut st, app(&si, &g.i));
        let om = put(&mut st, app(&w, &w));
        let (r, sp) = eval_hash(&om, 500, &mut st).ok().unwrap();
        assert_eq!(r, atp);
        assert!(sp <= 500);
        // a missing child: R-I fires, then the ghost is unresolved (4 spent)
        let ghost = sha256(b"this node was never stored");
        let hb = put(&mut st, app(&g.i, &ghost));
        let unres = term_hash(&Term::Dis(g.r_unres));
        assert_eq!(eval_hash(&hb, 10, &mut st).ok(), Some((unres, 4)));
    }

    #[test]
    fn deep_spine_faults_not_crashes() {
        let g = genesis();
        let mut st = MemCas(HashMap::new());
        let mut hd = g.i;
        for _ in 0..5000 {
            hd = put(&mut st, ser(APPLY, 6, &[&hd, &g.i]));
        }
        let r = std::thread::Builder::new()
            .stack_size(512 << 20)
            .spawn(move || eval_hash(&hd, 1_000_000, &mut st))
            .unwrap()
            .join()
            .unwrap();
        assert_eq!(r, Err(EvalFault::Resource("term depth".into())));
    }
}
