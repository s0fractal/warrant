//! The store-writing and store-reading verbs: filing, `why`, `resign`, `settle`.

use crate::hash::is_hex64;
use crate::json::{
    dumps_pretty_sorted, parse_ijson_str, parse_plain_str, prefix, py_repr, py_str, Json, Obj,
};
use crate::schema::{is_unverifiable, validate_body, VERSION};
use crate::settlement::{settlement_admissibility, well_signed};
use crate::sig::{legacy_sig, verify_sig, SigningKey};
use crate::ski::run_ski_check;
use crate::store::{warrant_id, Store};
use std::path::{Path, PathBuf};

/// A `sys.exit(message)`: the message goes to stderr and the status is 1.
#[derive(Debug)]
pub struct Exit {
    pub code: u8,
    pub message: Option<String>,
}

impl Exit {
    pub fn msg(m: impl Into<String>) -> Exit {
        Exit {
            code: 1,
            message: Some(m.into()),
        }
    }
    pub fn code(code: u8) -> Exit {
        Exit {
            code,
            message: None,
        }
    }
}

pub type Out = Result<(), Exit>;

/// Accept a hex64 hash or a file path (a file is added as a blob).
pub fn resolve_blob_arg(store: &Store, val: &str) -> Result<String, Exit> {
    if is_hex64(val) {
        return Ok(val.to_string());
    }
    let p = Path::new(val);
    if !val.is_empty() && p.is_file() {
        let data = std::fs::read(p).map_err(|e| Exit::msg(format!("cannot read {val}: {e}")))?;
        return store.put_blob(&data).map_err(|e| Exit::msg(e.to_string()));
    }
    Err(Exit::msg(format!(
        "not a hex64 hash or existing file: {val}"
    )))
}

/// The filing options shared by propose/accept/reject/supersede.
#[derive(Default, Clone)]
pub struct Filing {
    pub subject: Option<String>,
    pub note: Option<String>,
    pub under: Vec<String>,
    pub reason: Vec<String>,
    pub check: Option<String>,
    pub runtime: String,
    pub verdict: String,
    pub transcript: Option<String>,
    pub evidence: Vec<String>,
    pub prior: Vec<String>,
    pub relitigates: Option<String>,
    pub actor: String,
    pub key: String,
    pub ts: Option<i128>,
    /// `under` inherited from a prior record, as the values found there.
    pub under_json: Vec<Json>,
}

/// `resolve_blob_arg` on a value read from a record: a string resolves as
/// usual; anything else is not something the reference can resolve.
fn resolve_json_blob_arg(store: &Store, v: &Json) -> Result<Json, Exit> {
    match v {
        Json::Str(s) => resolve_blob_arg(store, s).map(Json::Str),
        _ => Err(Exit::msg(format!(
            "not a hex64 hash or existing file: {}",
            py_str(v)
        ))),
    }
}

fn build_reasons(store: &Store, a: &Filing) -> Result<Vec<Json>, Exit> {
    let mut reasons: Vec<Json> = a
        .reason
        .iter()
        .map(|t| {
            let mut o = Obj::new();
            o.insert("kind", Json::str("prose"));
            o.insert("text", Json::str(t));
            Json::Object(o)
        })
        .collect();
    if let Some(check) = a.check.as_deref().filter(|c| !c.is_empty()) {
        let mut r = Obj::new();
        r.insert("kind", Json::str("check"));
        let ch = resolve_blob_arg(store, check)?;
        r.insert("check", Json::Str(ch.clone()));
        r.insert("runtime", Json::str(&a.runtime));
        r.insert("verdict", Json::str(&a.verdict));
        if let Some(t) = a.transcript.as_deref().filter(|t| !t.is_empty()) {
            r.insert("transcript", Json::Str(resolve_blob_arg(store, t)?));
        }
        if a.runtime == "ski@v1" {
            // Verify the claim at filing time.
            let (got, rh, spent) = run_ski_check(&store.blobs, &ch)
                .map_err(|e| Exit::msg(format!("ski@v1 unverified: {e}")))?;
            if got != a.verdict {
                return Err(Exit::msg(format!(
                    "refusing to file: ski@v1 check re-run gives {got} (result {}, {spent} ATP), you claimed {}",
                    prefix(&rh, 16),
                    a.verdict
                )));
            }
        }
        reasons.push(Json::Object(r));
    }
    Ok(reasons)
}

fn now() -> i128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i128)
        .unwrap_or(0)
}

/// File, sign and store one warrant; prints and returns its WarrantID.
pub fn file_warrant(
    store: &Store,
    decision: &str,
    subject: Json,
    a: &Filing,
    note: Option<Json>,
) -> Result<String, Exit> {
    let mut subj = Obj::new();
    subj.insert("hash", subject);
    if let Some(n) = note.filter(|n| crate::settlement::truthy(Some(n))) {
        subj.insert("note", n);
    }
    let under = a
        .under
        .iter()
        .map(|u| resolve_blob_arg(store, u).map(Json::Str))
        .collect::<Result<Vec<_>, _>>()?;
    let under: Vec<Json> = under
        .into_iter()
        .chain(
            a.under_json
                .iter()
                .map(|u| resolve_json_blob_arg(store, u))
                .collect::<Result<Vec<_>, _>>()?,
        )
        .collect();
    let because = build_reasons(store, a)?;
    let evidence = a
        .evidence
        .iter()
        .map(|e| resolve_blob_arg(store, e).map(Json::Str))
        .collect::<Result<Vec<_>, _>>()?;
    let mut actor = Obj::new();
    actor.insert("id", Json::str(&a.actor));
    let mut body = Obj::new();
    body.insert("warrant", Json::str(VERSION));
    body.insert("decision", Json::str(decision));
    body.insert("subject", Json::Object(subj));
    body.insert("under", Json::Array(under));
    body.insert("because", Json::Array(because));
    body.insert("evidence", Json::Array(evidence));
    body.insert("actor", Json::Object(actor));
    body.insert(
        "prior",
        Json::Array(a.prior.iter().map(|p| Json::str(p)).collect()),
    );
    body.insert("ts", Json::Int(a.ts.unwrap_or_else(now).to_string()));
    let body = Json::Object(body);
    let errors = validate_body(&body);
    if !errors.is_empty() {
        return Err(Exit::msg(format!(
            "invalid warrant:\n  {}",
            errors.join("\n  ")
        )));
    }
    if let Some(rel) = a.relitigates.as_deref().filter(|r| !r.is_empty()) {
        let (recs, _) = store.all_records();
        if settlement_admissibility(store, rel, &body, &recs).starts_with("inadmissible") {
            return Err(Exit::msg("refusing to file: cites nothing new"));
        }
    }
    let key = SigningKey::load(&a.key).map_err(Exit::msg)?;
    let wid = warrant_id(&body).map_err(|e| Exit::msg(e.to_string()))?;
    let mut env = Obj::new();
    env.insert("body", body.clone());
    env.insert("sigs", Json::Array(vec![key.sign_entry(&wid, &a.actor)]));
    let wid = store.put_record(&Json::Object(env)).map_err(Exit::msg)?;
    if is_unverifiable(&body) {
        eprintln!(
            "warning: UNVERIFIABLE reject (prose-only reasons); add a --check to make it provable"
        );
    }
    println!("{wid}");
    Ok(wid)
}

/// accept/reject/supersede: respond to a prior warrant, or file without one.
pub fn respond(
    store: &Store,
    decision: &str,
    prior_id: Option<&str>,
    a: &Filing,
) -> Result<String, Exit> {
    let note_arg = a.note.clone().filter(|n| !n.is_empty()).map(Json::Str);
    let Some(prior_id) = prior_id else {
        let subject = resolve_blob_arg(store, a.subject.as_deref().unwrap_or(""))?;
        return file_warrant(store, decision, Json::Str(subject), a, note_arg);
    };
    let prior_env = store.get_record(prior_id).map_err(Exit::msg)?;
    let Some(prior_env) = prior_env else {
        return Err(Exit::msg(format!("prior warrant {prior_id} not in store")));
    };
    let shape = || Exit::msg(format!("prior warrant {prior_id} is malformed"));
    let pbody = prior_env.get("body").ok_or_else(shape)?;
    let mut a = a.clone();
    let mut prior = vec![prior_id.to_string()];
    prior.extend(a.prior.iter().cloned());
    a.prior = prior;
    let subject = if decision == "supersede" {
        Json::str(prior_id)
    } else if let Some(s) = a.subject.as_deref().filter(|s| !s.is_empty()) {
        Json::Str(resolve_blob_arg(store, s)?)
    } else {
        pbody
            .get("subject")
            .and_then(|s| s.as_obj())
            .and_then(|s| s.get("hash"))
            .cloned()
            .ok_or_else(shape)?
    };
    if a.under.is_empty() {
        let u = pbody
            .get("under")
            .and_then(Json::as_arr)
            .ok_or_else(shape)?;
        a.under_json = u.to_vec();
    }
    let note = match note_arg {
        Some(n) => Some(n),
        None => pbody
            .get("subject")
            .and_then(|s| s.as_obj())
            .ok_or_else(shape)?
            .get("note")
            .cloned(),
    };
    file_warrant(store, decision, subject, &a, note)
}

// ------------------------------------------------------------------- why ----

pub const WHY_MAX_DEPTH: usize = 4096;

/// `x[:n]` for the values `why` slices: a string's prefix, a list's prefix
/// (printed as a list), anything else has no slice.
fn slice(v: Option<&Json>, n: usize) -> Result<String, Exit> {
    match v {
        Some(Json::Str(s) | Json::BadStr(s, _)) => Ok(prefix(s, n)),
        Some(Json::Array(a)) => Ok(py_repr(&Json::Array(a.iter().take(n).cloned().collect()))),
        _ => Err(Exit::msg(
            "why: malformed record (a field the walk prints has the wrong type)",
        )),
    }
}

fn field<'a>(v: &'a Json, k: &str) -> Result<&'a Json, Exit> {
    v.get(k)
        .ok_or_else(|| Exit::msg(format!("why: malformed record (no {k:?})")))
}

/// One step of the walk behind `why` and `why --json`, in print order.
pub enum WhyStep<'a> {
    Node {
        wid: &'a str,
        depth: usize,
        env: &'a Json,
        ok: bool,
    },
    Missing {
        wid: &'a str,
        depth: usize,
    },
    /// The node just visited had been visited before; its priors are not followed.
    Cycle {
        depth: usize,
    },
    /// The node just visited is at the depth bound; its priors are not followed.
    MaxDepth {
        depth: usize,
    },
}

/// The one walk both renderers consume, so the text and the JSON cannot
/// disagree about which records were walked or which of them verified.
pub fn why_walk(
    store: &Store,
    wid: &str,
    visit: &mut dyn FnMut(WhyStep) -> Result<(), Exit>,
) -> Result<(), Exit> {
    let mut seen = std::collections::BTreeSet::new();
    let mut stack: Vec<(String, usize)> = vec![(wid.to_string(), 0)];
    while let Some((cur, d)) = stack.pop() {
        let Some(env) = store.get_record(&cur).map_err(Exit::msg)? else {
            visit(WhyStep::Missing {
                wid: &cur,
                depth: d,
            })?;
            continue;
        };
        let body = field(&env, "body")?;
        let sigs = field(&env, "sigs")?;
        let ok = warrant_id(body).is_ok_and(|w| w == cur)
            && crate::settlement::truthy(Some(sigs))
            && well_signed(&cur, &env);
        visit(WhyStep::Node {
            wid: &cur,
            depth: d,
            env: &env,
            ok,
        })?;
        if !seen.insert(cur.clone()) {
            visit(WhyStep::Cycle { depth: d })?;
            continue;
        }
        if d >= WHY_MAX_DEPTH {
            visit(WhyStep::MaxDepth { depth: d })?;
            continue;
        }
        for p in field(body, "prior")?
            .as_arr()
            .ok_or_else(|| Exit::msg("why: malformed record (prior)"))?
            .iter()
            .rev()
        {
            match p.as_str() {
                Some(p) => stack.push((p.to_string(), d + 1)),
                None => return Err(Exit::msg("why: malformed record (a prior is not a string)")),
            }
        }
    }
    Ok(())
}

/// Print a decision's chain of reasons. Returns (missing, failed) counts.
pub fn why(store: &Store, wid: &str) -> Result<(usize, usize), Exit> {
    let (mut missing, mut failed) = (0, 0);
    why_walk(store, wid, &mut |step| {
        match step {
            WhyStep::Missing { wid, depth } => {
                println!(
                    "{}?? {} (not in store)",
                    "  ".repeat(depth),
                    prefix(wid, 16)
                );
                missing += 1;
            }
            WhyStep::Cycle { depth } => println!("{}  (cycle)", "  ".repeat(depth)),
            WhyStep::MaxDepth { depth } => {
                println!(
                    "{}  (max depth {WHY_MAX_DEPTH} reached)",
                    "  ".repeat(depth)
                )
            }
            WhyStep::Node {
                wid,
                depth,
                env,
                ok,
            } => {
                if !ok {
                    failed += 1;
                }
                print_why_node(store, wid, depth, env, ok)?;
            }
        }
        Ok(())
    })?;
    Ok((missing, failed))
}

fn print_why_node(store: &Store, cur: &str, d: usize, env: &Json, ok: bool) -> Result<(), Exit> {
    let pad = "  ".repeat(d);
    let body = field(env, "body")?;
    let mark = if ok { "" } else { "  [VERIFY FAILED]" };
    let unv = if is_unverifiable(body) {
        "  [unverifiable]"
    } else {
        ""
    };
    let subject = field(body, "subject")?;
    let note = subject
        .as_obj()
        .ok_or_else(|| Exit::msg("why: malformed record (subject)"))?
        .get("note")
        .map(py_str)
        .unwrap_or_default();
    let decision = match field(body, "decision")? {
        Json::Str(s) | Json::BadStr(s, _) => s.to_uppercase(),
        _ => return Err(Exit::msg("why: malformed record (decision)")),
    };
    let actor = py_str(field(field(body, "actor")?, "id")?);
    println!(
        "{pad}{decision} {} by {actor}  subject={} {note}{mark}{unv}",
        prefix(cur, 16),
        slice(subject.get("hash"), 12)?
    );
    for r in field(body, "because")?
        .as_arr()
        .ok_or_else(|| Exit::msg("why: malformed record (because)"))?
    {
        if crate::json::py_eq(field(r, "kind")?, &Json::str("prose")) {
            println!("{pad}  - prose: {}", py_str(field(r, "text")?));
        } else {
            println!(
                "{pad}  - check {} [{}] -> {}",
                slice(r.get("check"), 12)?,
                py_str(field(r, "runtime")?),
                py_str(field(r, "verdict")?)
            );
        }
    }
    for h in field(body, "under")?
        .as_arr()
        .ok_or_else(|| Exit::msg("why: malformed record (under)"))?
    {
        let hs = slice(Some(h), 12)?;
        let resolved = store.has_blob(
            h.as_str()
                .ok_or_else(|| Exit::msg("why: malformed record (under)"))?,
        );
        println!(
            "{pad}  under policy {hs}{}",
            if resolved { "" } else { " (unresolved)" }
        );
    }
    Ok(())
}

pub const WHY_REPORT_VERSION: &str = "warrant.why@v0";

/// `why --json`: the same walk as `why`, as one object an agent can read.
/// NON-NORMATIVE: `verified` is `why`'s predicate (the name recomputes and a
/// valid signature by `body.actor.id` is present), not a key binding and not
/// a settlement verdict. Each node carries the record's whole body as stored.
pub fn why_report(store: &Store, wid: &str) -> Result<Json, Exit> {
    let mut nodes: Vec<Json> = Vec::new();
    let (mut missing, mut failed) = (0usize, 0usize);
    why_walk(store, wid, &mut |step| {
        match step {
            WhyStep::Missing { wid, depth } => {
                missing += 1;
                let mut o = Obj::new();
                o.insert("warrant_id", Json::str(wid));
                o.insert("depth", Json::Int(depth.to_string()));
                o.insert("status", Json::str("missing"));
                nodes.push(Json::Object(o));
            }
            WhyStep::Cycle { .. } => {
                if let Some(o) = nodes.last_mut().and_then(Json::as_obj_mut) {
                    o.insert("cycle", Json::Bool(true));
                }
            }
            WhyStep::MaxDepth { .. } => {
                if let Some(o) = nodes.last_mut().and_then(Json::as_obj_mut) {
                    o.insert("truncated", Json::Bool(true));
                }
            }
            WhyStep::Node {
                wid,
                depth,
                env,
                ok,
            } => {
                if !ok {
                    failed += 1;
                }
                let body = field(env, "body")?;
                let unresolved: Vec<Json> = match body.get("under") {
                    Some(Json::Array(a)) => a
                        .iter()
                        .filter(|h| {
                            !h.as_str()
                                .is_some_and(|s| matches!(h, Json::Str(_)) && store.has_blob(s))
                        })
                        .cloned()
                        .collect(),
                    _ => Vec::new(),
                };
                let mut o = Obj::new();
                o.insert("warrant_id", Json::str(wid));
                o.insert("depth", Json::Int(depth.to_string()));
                o.insert(
                    "status",
                    Json::str(if ok { "verified" } else { "verify_failed" }),
                );
                o.insert("unverifiable", Json::Bool(is_unverifiable(body)));
                o.insert("unresolved_under", Json::Array(unresolved));
                o.insert("body", body.clone());
                nodes.push(Json::Object(o));
            }
        }
        Ok(())
    })?;
    let mut r = Obj::new();
    r.insert("why", Json::str(WHY_REPORT_VERSION));
    r.insert("warrant_id", Json::str(wid));
    r.insert("ok", Json::Bool(missing == 0 && failed == 0));
    r.insert("missing", Json::Int(missing.to_string()));
    r.insert("failed", Json::Int(failed.to_string()));
    r.insert("nodes", Json::Array(nodes));
    Ok(Json::Object(r))
}

// ----------------------------------------------------------------- trust ----

/// `warrant trust add|root`: add one key binding or one genesis root to a
/// local trust configuration (SPEC §12), creating the file if absent. It
/// writes only what it is told; an existing file that does not validate is
/// refused, never rewritten.
pub fn trust_edit(
    path: &str,
    store: &Store,
    add: Option<(&str, &str)>,
    root: Option<&str>,
) -> Result<(), Exit> {
    let p = Path::new(path);
    let mut doc = Json::Object(Obj::new());
    if p.exists() {
        let text = std::fs::read_to_string(p).map_err(|e| {
            Exit::msg(format!(
                "{path}: not a readable trust config ({e}); refusing to rewrite it"
            ))
        })?;
        doc = parse_ijson_str(&text).map_err(|e| {
            Exit::msg(format!(
                "{path}: not a readable trust config ({e}); refusing to rewrite it"
            ))
        })?;
        if let Err(e) = crate::settlement::validate_trust_config(&doc) {
            return Err(Exit::msg(format!(
                "{path}: not a valid trust config ({e}); refusing to rewrite it"
            )));
        }
    }
    let o = doc.as_obj_mut().expect("validated as an object");
    let msg = if let Some((actor, pubkey)) = add {
        if actor.is_empty() {
            return Err(Exit::msg("an actor id must be a nonempty string"));
        }
        let ok = is_hex64(pubkey)
            && !crate::sig::weak_ed25519_pubkey(&crate::hash::fromhex(pubkey).unwrap_or_default());
        if !ok {
            return Err(Exit::msg(format!(
                "not an acceptable Ed25519 public key (SPEC §5): {pubkey}"
            )));
        }
        if !o.contains_key("actors") {
            o.insert("actors", Json::Object(Obj::new()));
        }
        let actors = o.get_mut("actors").and_then(Json::as_obj_mut).unwrap();
        if !actors.contains_key(actor) {
            actors.insert(actor, Json::Array(Vec::new()));
        }
        let Some(Json::Array(keys)) = actors.get_mut(actor) else {
            unreachable!()
        };
        if keys.iter().any(|k| k.as_str() == Some(pubkey)) {
            println!(
                "key {} for actor {actor} already in {path}",
                prefix(pubkey, 12)
            );
            return Ok(());
        }
        keys.push(Json::str(pubkey));
        format!(
            "trusted key {} for actor {actor} in {path}",
            prefix(pubkey, 12)
        )
    } else {
        let root = root.unwrap_or_default();
        if !is_hex64(root) {
            return Err(Exit::msg(format!(
                "not a WarrantID (64 lowercase hex): {root}"
            )));
        }
        if !o.contains_key("genesis_roots") {
            o.insert("genesis_roots", Json::Array(Vec::new()));
        }
        let Some(Json::Array(roots)) = o.get_mut("genesis_roots") else {
            unreachable!()
        };
        if roots.iter().any(|r| r.as_str() == Some(root)) {
            println!("genesis root {} already in {path}", prefix(root, 12));
            return Ok(());
        }
        if store.records.is_dir() && !store.records.join(format!("{root}.json")).is_file() {
            eprintln!(
                "warning: {} is not a record in {}; a root must be a stored, well-signed record to become active",
                prefix(root, 12),
                crate::cli::py_path(&store.root.display().to_string())
            );
        }
        roots.push(Json::str(root));
        format!("trusted genesis root {} in {path}", prefix(root, 12))
    };
    std::fs::write(p, dumps_pretty_sorted(&doc) + "\n")
        .map_err(|e| Exit::msg(format!("{path}: {e}")))?;
    println!("{msg}");
    Ok(())
}

// ---------------------------------------------------------------- resign ----

#[derive(Default)]
pub struct Resign {
    pub files: usize,
    pub resigned: usize,
    pub already_current: usize,
    pub unmigratable: Vec<(String, Option<String>, String)>,
    pub unchanged_files: usize,
    pub id_moved: Vec<(String, String, String)>,
}

/// Re-sign envelopes under SPEC §5 `warrant-sig-v1`. Exactly one field may
/// change: the `sig` of an entry whose key is this key AND whose existing
/// signature verifies over the bare WarrantID. The WarrantID cannot move (the
/// envelope is not hashed), and that is checked rather than assumed.
pub fn resign_envelopes(paths: &[PathBuf], key: &SigningKey, dry_run: bool) -> Resign {
    let pubk = key.public_hex();
    let mut res = Resign::default();
    for p in paths {
        let ps = p.display().to_string();
        let raw = match std::fs::read(p)
            .map_err(|e| e.to_string())
            .and_then(|b| String::from_utf8(b).map_err(|e| e.to_string()))
        {
            Ok(t) => t,
            Err(e) => {
                res.unmigratable
                    .push((ps, None, format!("unreadable envelope: {e}")));
                continue;
            }
        };
        let mut env = match parse_plain_str(&raw) {
            Ok(v) => v,
            Err(e) => {
                res.unmigratable
                    .push((ps, None, format!("unreadable envelope: {e}")));
                continue;
            }
        };
        let shaped = env.get("body").is_some_and(|b| b.as_obj().is_some())
            && env.get("sigs").is_some_and(|s| s.as_arr().is_some());
        if !shaped {
            res.unmigratable
                .push((ps, None, "not a {body, sigs} envelope".into()));
            continue;
        }
        res.files += 1;
        let wid = match warrant_id(env.get("body").unwrap()) {
            Ok(w) => w,
            Err(e) => {
                res.unmigratable
                    .push((ps, None, format!("WarrantID uncomputable: {e}")));
                continue;
            }
        };
        let mut changed = false;
        let sigs = match env.as_obj_mut().unwrap().get_mut("sigs") {
            Some(Json::Array(a)) => a,
            _ => unreachable!(),
        };
        for s in sigs.iter_mut() {
            let Some(so) = s.as_obj_mut() else {
                res.unmigratable.push((
                    ps.clone(),
                    Some(wid.clone()),
                    "signature entry is not an object".into(),
                ));
                continue;
            };
            if verify_sig(&wid, so) {
                res.already_current += 1;
                continue;
            }
            let actor = so
                .get("actor")
                .map(py_repr)
                .unwrap_or_else(|| "None".into());
            if !legacy_sig(&wid, so) {
                res.unmigratable.push((
                    ps.clone(),
                    Some(wid.clone()),
                    format!("signature by actor {actor} verifies under NEITHER construction; not this migration's business"),
                ));
                continue;
            }
            if !so
                .get("key")
                .is_some_and(|k| crate::json::py_eq(k, &Json::Str(pubk.clone())))
            {
                let k = so.get("key").map(py_str).unwrap_or_else(|| "None".into());
                res.unmigratable.push((
                    ps.clone(),
                    Some(wid.clone()),
                    format!(
                        "legacy signature by actor {actor} was made with key {}..., not the supplied {}... - re-run where that key lives",
                        prefix(&k, 16),
                        prefix(&pubk, 16)
                    ),
                ));
                continue;
            }
            let msg = crate::sig::sig_message(&wid).unwrap();
            so.insert("sig", Json::Str(crate::hash::encode_hex(&key.sign(&msg))));
            changed = true;
            res.resigned += 1;
        }
        if !changed {
            res.unchanged_files += 1;
            continue;
        }
        let after = warrant_id(env.get("body").unwrap()).unwrap_or_default();
        if after != wid {
            res.id_moved.push((ps, wid, after));
            continue;
        }
        if !dry_run {
            let text = dumps_pretty_sorted(&env) + if raw.ends_with('\n') { "\n" } else { "" };
            if let Err(e) = std::fs::write(p, text) {
                res.unmigratable.push((
                    ps.clone(),
                    Some(wid.clone()),
                    format!("cannot write: {e}"),
                ));
                continue;
            }
        }
        println!(
            "{} {}  {}",
            if dry_run {
                "would re-sign"
            } else {
                "re-signed"
            },
            prefix(&wid, 12),
            ps
        );
    }
    res
}

// ---------------------------------------------------------------- settle ----

/// `settle <settling_wid> <candidate_body>`: print the §7 admissibility.
pub fn settle(store: &Store, settling: &str, candidate_path: &str) -> Result<bool, Exit> {
    let text = std::fs::read_to_string(candidate_path)
        .map_err(|e| Exit::msg(format!("cannot read {candidate_path}: {e}")))?;
    let body = parse_ijson_str(&text).map_err(|e| Exit::msg(format!("{candidate_path}: {e}")))?;
    let (recs, _) = store.all_records();
    let verdict = settlement_admissibility(store, settling, &body, &recs);
    println!("{verdict}");
    Ok(!(verdict.starts_with("inadmissible") || verdict.starts_with("invalid candidate")))
}
