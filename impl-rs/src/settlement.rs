//! Settlement (SPEC §5.1, §7, §9): tunnels, outcome fingerprints, re-litigation
//! admissibility, trust configs, threshold policies, and the settlement context
//! (settlement-active roots and records, DAG-ordered key state, conflicts).
//!
//! Every function here is total over the records a store can hold, including
//! schema-invalid ones reached as ancestors of valid records: a type-confused
//! field contributes nothing rather than aborting the verifier.

use crate::hash::{blob_hash, is_hex64};
use crate::json::{canon_eq, parse_ijson, parse_plain_bytes, py_eq, py_hashable, Json, Obj};
use crate::schema::{int_domain_violation, validate_body};
use crate::sig::verify_sig;
use crate::ski::run_ski_check;
use crate::ski::validate_ski_blob;
use crate::store::{Records, Store};
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet, HashMap};

pub const WARN_RELITIGATION: &str = "re-litigation cites nothing new";
pub const WARN_UNADOPTED_ROOT: &str = "unadopted root";
pub const WARN_GENESIS_UNVERIFIED: &str = "genesis.json unverified";
pub const ERR_INVALID_THRESHOLD: &str = "invalid threshold policy";
pub const WARN_KEY_CONFLICT: &str = "key-state conflict";
pub const ERR_SETTLEMENT_TRUST: &str = "settlement trust config unavailable";

/// Python truthiness of a decoded JSON value.
pub fn truthy(v: Option<&Json>) -> bool {
    match v {
        None | Some(Json::Null) => false,
        Some(Json::Bool(b)) => *b,
        Some(Json::Int(t)) => t != "0",
        Some(Json::Float(f)) => *f != 0.0,
        Some(Json::Str(s) | Json::BadStr(s, _)) => !s.is_empty(),
        Some(Json::Array(a)) => !a.is_empty(),
        Some(Json::Object(o)) => !o.is_empty(),
    }
}

/// The string members of a list-valued field; anything else contributes nothing.
fn str_list<'a>(body: &'a Json, key: &str) -> Vec<&'a str> {
    body.get(key)
        .and_then(Json::as_arr)
        .map(|a| a.iter().filter_map(Json::as_str).collect())
        .unwrap_or_default()
}

fn obj_list<'a>(body: &'a Json, key: &str) -> Vec<&'a Obj> {
    body.get(key)
        .and_then(Json::as_arr)
        .map(|a| a.iter().filter_map(Json::as_obj).collect())
        .unwrap_or_default()
}

fn is(v: Option<&Json>, s: &str) -> bool {
    v.is_some_and(|x| py_eq(x, &Json::str(s)))
}

/// Blobs a body cites: under, evidence, subject, and each check's blob and
/// transcript.
pub fn cited_blobs(body: &Json) -> BTreeSet<String> {
    let mut refs: BTreeSet<String> = BTreeSet::new();
    refs.extend(str_list(body, "under").into_iter().map(String::from));
    refs.extend(str_list(body, "evidence").into_iter().map(String::from));
    if let Some(h) = body
        .get("subject")
        .and_then(|s| s.get("hash"))
        .and_then(Json::as_str)
    {
        refs.insert(h.to_string());
    }
    for r in obj_list(body, "because") {
        if is(r.get("kind"), "check") {
            for k in ["check", "transcript"] {
                if let Some(h) = r.get(k).and_then(Json::as_str) {
                    refs.insert(h.to_string());
                }
            }
        }
    }
    refs
}

/// Every record reachable from `wid` along `prior` edges (not `wid` itself,
/// unless a cycle leads back to it).
pub fn prior_closure(recs: &Records, wid: &str) -> BTreeSet<String> {
    let mut seen = BTreeSet::new();
    let mut stack: Vec<String> = recs
        .body(wid)
        .map(|b| str_list(b, "prior").into_iter().map(String::from).collect())
        .unwrap_or_default();
    while let Some(cur) = stack.pop() {
        if seen.contains(&cur) || !recs.contains(&cur) {
            continue;
        }
        stack.extend(
            str_list(recs.body(&cur).unwrap(), "prior")
                .into_iter()
                .map(String::from),
        );
        seen.insert(cur);
    }
    seen
}

pub struct Tunnel {
    pub records: BTreeSet<String>,
    pub blobs: BTreeSet<String>,
}

pub fn tunnel(recs: &Records, wid: &str) -> Tunnel {
    let records = prior_closure(recs, wid);
    let mut blobs = BTreeSet::new();
    for r in &records {
        blobs.extend(cited_blobs(recs.body(r).unwrap()));
    }
    Tunnel { records, blobs }
}

/// A blob's JSON value iff its bytes are exactly that value's canonical form.
pub fn read_json_blob_if_canonical(store: &Store, h: &str) -> Option<Json> {
    if !is_hex64(h) {
        return None;
    }
    let raw = store.blob_bytes(h)?;
    let doc = parse_plain_bytes(&raw).ok()?;
    canon_eq(&doc, &raw).then_some(doc)
}

/// SPEC §7 outcome fingerprint: what a check RE-RUNS to, never what its filer
/// said it ran to.
#[derive(Clone, Debug)]
pub enum Fingerprint {
    Cmd {
        evidence: Vec<String>,
        verdict: Json,
        transcript: String,
    },
    Ski {
        term: String,
        expect: String,
        verdict: String,
        result: String,
    },
}

impl PartialEq for Fingerprint {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (
                Fingerprint::Cmd {
                    evidence: a,
                    verdict: v,
                    transcript: t,
                },
                Fingerprint::Cmd {
                    evidence: b,
                    verdict: w,
                    transcript: u,
                },
            ) => a == b && py_eq(v, w) && t == u,
            (
                Fingerprint::Ski {
                    term: a,
                    expect: b,
                    verdict: c,
                    result: d,
                },
                Fingerprint::Ski {
                    term: e,
                    expect: f,
                    verdict: g,
                    result: h,
                },
            ) => a == e && b == f && c == g && d == h,
            _ => false,
        }
    }
}

pub fn fingerprint(reason: &Obj, body: &Json, store: &Store) -> Option<Fingerprint> {
    if !is(reason.get("kind"), "check") {
        return None;
    }
    let verdict = reason.get("verdict").cloned().unwrap_or(Json::Null);
    if is(reason.get("runtime"), "cmd@v1") {
        if !truthy(reason.get("transcript")) {
            return None;
        }
        let transcript = reason.get("transcript")?.as_str()?.to_string();
        let ev = body
            .get("evidence")
            .map(|v| v.as_arr())
            .unwrap_or(Some(&[]))?;
        let mut evidence = Vec::new();
        for h in ev {
            evidence.push(h.as_str()?.to_string());
        }
        let check = reason.get("check").and_then(Json::as_str)?;
        if !py_hashable(&verdict) {
            return None;
        }
        let ok = |h: &str| !h.is_empty() && store.has_blob(h);
        if !(evidence.iter().all(|h| ok(h)) && ok(check) && ok(&transcript)) {
            return None;
        }
        evidence.sort();
        return Some(Fingerprint::Cmd {
            evidence,
            verdict,
            transcript,
        });
    }
    if is(reason.get("runtime"), "ski@v1") {
        let check = reason.get("check").and_then(Json::as_str)?;
        let doc = read_json_blob_if_canonical(store, check)?;
        if validate_ski_blob(&doc).is_some() {
            return None;
        }
        let (rerun, result, _) = run_ski_check(&store.blobs, check).ok()?;
        let o = doc.as_obj().unwrap();
        return Some(Fingerprint::Ski {
            term: o.get("term").unwrap().as_str().unwrap().to_string(),
            expect: o.get("expect").unwrap().as_str().unwrap().to_string(),
            verdict: rerun,
            result,
        });
    }
    None
}

fn add_fp(set: &mut Vec<Fingerprint>, fp: Fingerprint) {
    if !set.contains(&fp) {
        set.push(fp);
    }
}

pub fn tunnel_fingerprints(store: &Store, recs: &Records, wid: &str) -> Vec<Fingerprint> {
    let mut fps = Vec::new();
    for r in tunnel(recs, wid).records {
        let body = recs.body(&r).unwrap();
        for reason in obj_list(body, "because") {
            if let Some(fp) = fingerprint(reason, body, store) {
                add_fp(&mut fps, fp);
            }
        }
    }
    fps
}

/// SPEC §7: may `candidate` re-open what `settling` decided?
pub fn settlement_admissibility(
    store: &Store,
    settling: &str,
    candidate: &Json,
    recs: &Records,
) -> String {
    let errs = validate_body(candidate);
    if let Some(first) = errs.first() {
        return format!("invalid candidate: {first}");
    }
    let tun = tunnel(recs, settling);
    let settling_body = recs.body(settling).filter(|b| truthy(Some(b)));
    let mut known = tun.blobs.clone();
    if let Some(b) = settling_body {
        known.extend(cited_blobs(b));
    }
    let mut ev: Vec<&str> = str_list(candidate, "evidence");
    ev.sort();
    if ev.iter().any(|h| !known.contains(*h)) {
        return "admissible: (a) new evidence".into();
    }
    let mut old = tunnel_fingerprints(store, recs, settling);
    if let Some(b) = settling_body {
        for r in obj_list(b, "because") {
            if let Some(fp) = fingerprint(r, b, store) {
                add_fp(&mut old, fp);
            }
        }
    }
    for r in obj_list(candidate, "because") {
        if let Some(fp) = fingerprint(r, candidate, store) {
            if !old.contains(&fp) {
                return "admissible: (b) new outcome fingerprint".into();
            }
        }
    }
    "inadmissible: cites nothing new".into()
}

// -------------------------------------------------------------- trust ----

/// A validated trust config (SPEC §9): closed schema, nested types checked.
#[derive(Default, Clone)]
pub struct Trust {
    pub genesis_roots: Vec<String>,
    pub actors: Vec<(String, Vec<String>)>,
    pub genesis_json_sha256: Option<String>,
}

pub fn validate_trust_config(doc: &Json) -> Result<Trust, String> {
    let o = doc.as_obj().ok_or("trust config must be a JSON object")?;
    if o.keys()
        .any(|k| !["genesis_roots", "actors", "genesis_json_sha256"].contains(&k.as_str()))
    {
        return Err("trust config has unknown fields".into());
    }
    let mut t = Trust::default();
    if let Some(gr) = o.get("genesis_roots") {
        let a = gr
            .as_arr()
            .filter(|a| a.iter().all(|x| x.as_str().is_some_and(is_hex64)));
        t.genesis_roots = a
            .ok_or("genesis_roots must be a list of hex64")?
            .iter()
            .map(|x| x.as_str().unwrap().to_string())
            .collect();
    }
    if let Some(ac) = o.get("actors") {
        let ac = ac.as_obj().ok_or("actors must be an object")?;
        for (a, keys) in ac.iter() {
            if a.is_empty() {
                return Err("actors keys must be nonempty actor-id strings".into());
            }
            let ks = keys
                .as_arr()
                .filter(|k| k.iter().all(|x| x.as_str().is_some_and(is_hex64)));
            let ks = ks.ok_or("each actor's keys must be a list of hex64")?;
            t.actors.push((
                a.clone(),
                ks.iter().map(|x| x.as_str().unwrap().to_string()).collect(),
            ));
        }
    }
    if let Some(gh) = o.get("genesis_json_sha256") {
        t.genesis_json_sha256 = Some(
            gh.as_str()
                .filter(|s| is_hex64(s))
                .ok_or("genesis_json_sha256 must be hex64")?
                .to_string(),
        );
    }
    Ok(t)
}

/// Read, parse (I-JSON) and validate a trust config file.
pub fn load_trust_config(path: &str) -> Result<Trust, String> {
    let raw = std::fs::read(path).map_err(|e| e.to_string())?;
    let doc = parse_ijson(&raw).map_err(|e| e.to_string())?;
    validate_trust_config(&doc)
}

/// Trusted genesis roots: explicit ones, the config's, and a hash-pinned
/// `genesis.json`. Returns the roots and any store-level warnings.
pub fn trust_roots(
    store: &Store,
    trust: &Trust,
    explicit: &[String],
) -> (BTreeSet<String>, Vec<(String, String)>) {
    let mut roots: BTreeSet<String> = explicit.iter().cloned().collect();
    roots.extend(trust.genesis_roots.iter().cloned());
    let mut warnings = Vec::new();
    let g = store.root.join("genesis.json");
    if g.exists() {
        let raw = std::fs::read(&g).ok();
        match raw {
            Some(raw) if trust.genesis_json_sha256.as_deref() == Some(blob_hash(&raw).as_str()) => {
                if let Ok(doc) = parse_ijson(&raw) {
                    if let Some(rs) = doc.get("roots").and_then(Json::as_arr) {
                        roots.extend(
                            rs.iter()
                                .filter_map(Json::as_str)
                                .filter(|r| is_hex64(r))
                                .map(String::from),
                        );
                    }
                }
            }
            _ => warnings.push(("store".to_string(), WARN_GENESIS_UNVERIFIED.to_string())),
        }
    }
    (roots, warnings)
}

// ------------------------------------------------------------ policies ----

#[derive(Clone)]
pub struct Policy {
    pub min_sigs: usize,
    pub actors: Vec<String>,
}

/// A blob that declares itself a `warrant_policy: "0.3"` and is not a valid one.
#[derive(Debug)]
pub struct InvalidPolicy;

/// A `warrant_policy: "0.3"` threshold blob: Ok(Some) valid, Ok(None) not a
/// policy at all, Err(InvalidPolicy) a policy that is invalid.
pub fn parse_policy_blob(store: &Store, h: &Json) -> Result<Option<Policy>, InvalidPolicy> {
    let Some(h) = h.as_str().filter(|h| is_hex64(h)) else {
        return Ok(None);
    };
    if !store.blobs.join(h).is_file() {
        return Ok(None);
    }
    let Some(raw) = store.blob_bytes(h) else {
        return Ok(None);
    };
    let Ok(doc) = parse_plain_bytes(&raw) else {
        return Ok(None);
    };
    let Some(o) = doc.as_obj() else {
        return Ok(None);
    };
    if !is(o.get("warrant_policy"), "0.3") {
        return Ok(None);
    }
    if !canon_eq(&doc, &raw) || !o.has_exactly(&["warrant_policy", "threshold"]) {
        return Err(InvalidPolicy);
    }
    let th = o
        .get("threshold")
        .and_then(Json::as_obj)
        .filter(|t| t.has_exactly(&["min_sigs", "actors"]))
        .ok_or(InvalidPolicy)?;
    let min_sigs = match th.get("min_sigs") {
        Some(Json::Int(t)) => t.parse::<i128>().unwrap_or(i128::MAX),
        _ => return Err(InvalidPolicy),
    };
    let actors = th
        .get("actors")
        .and_then(Json::as_arr)
        .ok_or(InvalidPolicy)?;
    if actors.is_empty()
        || !actors
            .iter()
            .all(|a| a.as_str().is_some_and(|s| !s.is_empty()))
    {
        return Err(InvalidPolicy);
    }
    let actors: Vec<String> = actors
        .iter()
        .map(|a| a.as_str().unwrap().to_string())
        .collect();
    let distinct: BTreeSet<&String> = actors.iter().collect();
    if distinct.len() != actors.len()
        || min_sigs < 1
        || min_sigs > actors.len() as i128
        || int_domain_violation(&doc).is_some()
    {
        return Err(InvalidPolicy);
    }
    Ok(Some(Policy {
        min_sigs: min_sigs as usize,
        actors,
    }))
}

/// The valid policies a body is `under`, and whether any is invalid.
pub fn record_policy(store: &Store, body: &Json) -> (Vec<Policy>, bool) {
    let mut valid = Vec::new();
    let mut invalid = false;
    for h in body.get("under").and_then(Json::as_arr).unwrap_or(&[]) {
        match parse_policy_blob(store, h) {
            Ok(Some(p)) => valid.push(p),
            Ok(None) => {}
            Err(InvalidPolicy) => invalid = true,
        }
    }
    (valid, invalid)
}

/// The well-formed (object) signature entries of an envelope.
pub fn iter_sigs(env: &Json) -> Vec<&Obj> {
    obj_list(env, "sigs")
}

pub type KeyState = BTreeMap<String, BTreeSet<String>>;

/// Actors with a valid signature (by a key bound to them, when key state is
/// given). Only string actors can ever satisfy a policy, so only they count.
fn valid_sig_actors(wid: &str, env: &Json, keys: Option<&KeyState>) -> BTreeSet<String> {
    let mut actors = BTreeSet::new();
    for s in iter_sigs(env) {
        if !verify_sig(wid, s) {
            continue;
        }
        let Some(actor) = s.get("actor").and_then(Json::as_str) else {
            continue;
        };
        if let Some(keys) = keys {
            let key = s.get("key").and_then(Json::as_str).unwrap_or("");
            if !keys.get(actor).is_some_and(|ks| ks.contains(key)) {
                continue;
            }
        }
        actors.insert(actor.to_string());
    }
    actors
}

fn threshold_satisfied(wid: &str, env: &Json, p: &Policy, keys: Option<&KeyState>) -> bool {
    if p.actors.is_empty() {
        return false;
    }
    let min_sigs = p.min_sigs.min(p.actors.len());
    let signers = valid_sig_actors(wid, env, keys);
    p.actors.iter().filter(|a| signers.contains(*a)).count() >= min_sigs
}

fn policies_satisfied(store: &Store, wid: &str, env: &Json, keys: Option<&KeyState>) -> bool {
    let (policies, invalid) = record_policy(store, env.get("body").unwrap());
    if invalid {
        return false;
    }
    if policies.is_empty() {
        return iter_sigs(env).iter().any(|s| verify_sig(wid, s));
    }
    policies
        .iter()
        .all(|p| threshold_satisfied(wid, env, p, keys))
}

fn parse_key_blob(store: &Store, h: &str) -> Option<(String, String)> {
    let doc = read_json_blob_if_canonical(store, h)?;
    let o = doc.as_obj()?;
    if !o.has_exactly(&["actor", "key"]) {
        return None;
    }
    let actor = match o.get("actor")? {
        Json::Str(s) => s.clone(),
        _ => return None,
    };
    let key = o.get("key")?.as_str().filter(|k| is_hex64(k))?.to_string();
    Some((actor, key))
}

/// SPEC §9: schema-valid and signed by body.actor.id.
pub fn well_signed(wid: &str, env: &Json) -> bool {
    let body = env.get("body").cloned().unwrap_or(Json::Object(Obj::new()));
    if !validate_body(&body).is_empty() {
        return false;
    }
    let id = body
        .get("actor")
        .and_then(|a| a.get("id"))
        .cloned()
        .unwrap();
    iter_sigs(env)
        .iter()
        .any(|s| verify_sig(wid, s) && s.get("actor").is_some_and(|a| py_eq(a, &id)))
}

// ------------------------------------------------------------- context ----

pub struct Context<'a> {
    store: &'a Store,
    pub recs: &'a Records,
    pub roots: BTreeSet<String>,
    pub active_roots: BTreeSet<String>,
    pub active_records: BTreeSet<String>,
    pub invalid_policy: BTreeSet<String>,
    pub global_warnings: Vec<(String, String)>,
    pub conflict_actors: BTreeSet<String>,
    genesis_keys: KeyState,
    ancestors_cache: RefCell<HashMap<String, BTreeSet<String>>>,
    rotation_cache: RefCell<HashMap<String, Option<(String, String)>>>,
    keys_cache: RefCell<HashMap<String, KeyState>>,
    rotation_auth_cache: RefCell<HashMap<String, bool>>,
}

impl<'a> Context<'a> {
    pub fn build(
        store: &'a Store,
        recs: &'a Records,
        trust: &Trust,
        explicit_roots: &[String],
    ) -> Context<'a> {
        let (genesis, global_warnings) = trust_roots(store, trust, explicit_roots);
        let roots: BTreeSet<String> = recs
            .iter()
            .filter(|(_, e)| !truthy(e.get("body").unwrap().get("prior")))
            .map(|(w, _)| w.clone())
            .collect();
        let well: BTreeSet<String> = recs
            .iter()
            .filter(|(w, e)| well_signed(w, e))
            .map(|(w, _)| w.clone())
            .collect();
        let active_roots: BTreeSet<String> = genesis.intersection(&well).cloned().collect();
        let invalid_policy: BTreeSet<String> = recs
            .iter()
            .filter(|(_, e)| record_policy(store, e.get("body").unwrap()).1)
            .map(|(w, _)| w.clone())
            .collect();
        let genesis_keys: KeyState = trust
            .actors
            .iter()
            .map(|(a, ks)| (a.clone(), ks.iter().cloned().collect()))
            .collect();
        let mut ctx = Context {
            store,
            recs,
            roots,
            active_roots,
            active_records: BTreeSet::new(),
            invalid_policy,
            global_warnings,
            conflict_actors: BTreeSet::new(),
            genesis_keys,
            ancestors_cache: RefCell::new(HashMap::new()),
            rotation_cache: RefCell::new(HashMap::new()),
            keys_cache: RefCell::new(HashMap::new()),
            rotation_auth_cache: RefCell::new(HashMap::new()),
        };
        // Fixpoint: adoption thresholds count only keys bound at the adopting
        // warrant's DAG position, and key state depends on the active set.
        let mut sorted_recs: Vec<&(String, Json)> = recs.iter().collect();
        sorted_recs.sort_by(|a, b| a.0.cmp(&b.0));
        loop {
            ctx.active_records = recs
                .wids()
                .filter(|w| {
                    !ctx.record_roots(w).is_disjoint(&ctx.active_roots)
                        && !ctx.invalid_policy.contains(*w)
                        && well.contains(*w)
                })
                .cloned()
                .collect();
            ctx.keys_cache.borrow_mut().clear();
            ctx.rotation_auth_cache.borrow_mut().clear();
            let mut grew = false;
            let pending: Vec<String> = ctx.roots.difference(&ctx.active_roots).cloned().collect();
            for root in pending {
                if !well.contains(&root) {
                    continue;
                }
                for (wid, env) in &sorted_recs {
                    let body = env.get("body").unwrap();
                    if ctx.active_records.contains(wid)
                        && is(body.get("decision"), "accept")
                        && body
                            .get("subject")
                            .and_then(|s| s.get("hash"))
                            .is_some_and(|h| py_eq(h, &Json::Str(root.clone())))
                        && policies_satisfied(store, wid, env, Some(&ctx.keys_before(wid)))
                    {
                        ctx.active_roots.insert(root.clone());
                        grew = true;
                        break;
                    }
                }
            }
            if !grew {
                break;
            }
        }
        let mut by_depth: Vec<String> = ctx.active_records.iter().cloned().collect();
        by_depth.sort_by_key(|w| (ctx.depth(w), w.clone()));
        let mut authorized: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for wid in &by_depth {
            if let Some((actor, _)) = ctx.rotation(wid) {
                if ctx.rotation_authorized(wid) {
                    authorized.entry(actor).or_default().insert(wid.clone());
                }
            }
        }
        for (actor, wids) in &authorized {
            let maximal = wids
                .iter()
                .filter(|a| {
                    !wids
                        .iter()
                        .any(|b| *a != b && ctx.ancestors(b).contains(*a))
                })
                .count();
            if maximal > 1 {
                ctx.conflict_actors.insert(actor.clone());
            }
        }
        ctx
    }

    /// The roots a record descends from (iterative, cycle-safe, shape-defensive).
    pub fn record_roots(&self, wid: &str) -> BTreeSet<String> {
        let mut roots = BTreeSet::new();
        let mut seen = BTreeSet::new();
        let mut stack = vec![wid.to_string()];
        while let Some(cur) = stack.pop() {
            if !seen.insert(cur.clone()) {
                continue;
            }
            let Some(body) = self.recs.body(&cur) else {
                continue;
            };
            let Some(prior) = body.get("prior").and_then(Json::as_arr) else {
                continue;
            };
            if prior.is_empty() {
                roots.insert(cur);
            } else {
                stack.extend(prior.iter().filter_map(Json::as_str).map(String::from));
            }
        }
        roots
    }

    pub fn ancestors(&self, wid: &str) -> BTreeSet<String> {
        if let Some(a) = self.ancestors_cache.borrow().get(wid) {
            return a.clone();
        }
        let a = prior_closure(self.recs, wid);
        self.ancestors_cache
            .borrow_mut()
            .insert(wid.to_string(), a.clone());
        a
    }

    fn depth(&self, wid: &str) -> usize {
        self.ancestors(wid).len()
    }

    /// A key rotation: an accept whose subject is a canonical {actor, key} blob.
    fn rotation(&self, wid: &str) -> Option<(String, String)> {
        if let Some(r) = self.rotation_cache.borrow().get(wid) {
            return r.clone();
        }
        let mut r = None;
        if let Some(body) = self.recs.body(wid) {
            if is(body.get("decision"), "accept") {
                if let Some(h) = body
                    .get("subject")
                    .and_then(|s| s.get("hash"))
                    .and_then(Json::as_str)
                {
                    r = parse_key_blob(self.store, h);
                }
            }
        }
        self.rotation_cache
            .borrow_mut()
            .insert(wid.to_string(), r.clone());
        r
    }

    /// SPEC §5.1: key state at a record's DAG position — genesis keys, then each
    /// authorized rotation among its ancestors in (depth, WarrantID) order.
    pub fn keys_before(&self, wid: &str) -> KeyState {
        if let Some(k) = self.keys_cache.borrow().get(wid) {
            return k.clone();
        }
        let mut keys = self.genesis_keys.clone();
        let mut anc: Vec<String> = self.ancestors(wid).into_iter().collect();
        anc.sort_by_key(|w| (self.depth(w), w.clone()));
        for a in anc {
            if let Some((actor, key)) = self.rotation(&a) {
                if self.rotation_authorized(&a) {
                    keys.insert(actor, BTreeSet::from([key]));
                }
            }
        }
        self.keys_cache
            .borrow_mut()
            .insert(wid.to_string(), keys.clone());
        keys
    }

    fn rotation_authorized(&self, wid: &str) -> bool {
        if let Some(&r) = self.rotation_auth_cache.borrow().get(wid) {
            return r;
        }
        self.rotation_auth_cache
            .borrow_mut()
            .insert(wid.to_string(), false);
        let Some((actor, incoming)) = self.rotation(wid) else {
            return false;
        };
        if self.invalid_policy.contains(wid) || !self.active_records.contains(wid) {
            return false;
        }
        let env = self.recs.get(wid).unwrap();
        let sigs = iter_sigs(env);
        let by = |s: &Obj, actor: &str| s.get("actor").is_some_and(|a| py_eq(a, &Json::str(actor)));
        let proof = sigs
            .iter()
            .any(|s| verify_sig(wid, s) && by(s, &actor) && is(s.get("key"), &incoming));
        if !proof {
            return false;
        }
        let prior_keys = self.keys_before(wid);
        let (policies, bad) = record_policy(self.store, env.get("body").unwrap());
        if bad {
            return false;
        }
        let ok = if !policies.is_empty() {
            policies
                .iter()
                .all(|p| threshold_satisfied(wid, env, p, Some(&prior_keys)))
        } else {
            sigs.iter().any(|s| {
                verify_sig(wid, s)
                    && by(s, &actor)
                    && s.get("key")
                        .and_then(Json::as_str)
                        .is_some_and(|k| prior_keys.get(&actor).is_some_and(|ks| ks.contains(k)))
            })
        };
        self.rotation_auth_cache
            .borrow_mut()
            .insert(wid.to_string(), ok);
        ok
    }
}
