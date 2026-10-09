//! SPEC §6 store verification (base grade) and SPEC §5.1/§7/§9 settlement grade,
//! plus the `warrant.verify-report@v0` machine report (SPEC §11).
//!
//! One derivation: the text report, the counts, the exit status and the JSON
//! findings all come from the same pass, so they cannot disagree.

use crate::json::{dumps_compact, prefix, py_eq, py_str, py_str_opt, Json, Obj};
use crate::schema::{is_unverifiable, validate_body};
use crate::settlement::{
    load_trust_config, prior_closure, settlement_admissibility, Context, Trust,
    ERR_INVALID_THRESHOLD, ERR_SETTLEMENT_TRUST, WARN_KEY_CONFLICT, WARN_RELITIGATION,
    WARN_UNADOPTED_ROOT,
};
use crate::sig::{legacy_sig, verify_sig, LEGACY_SIG_MESSAGE};
use crate::ski::run_ski_check;
use crate::store::{warrant_id, Store};

pub const VERIFY_REPORT_VERSION: &str = "warrant.verify-report@v0";

/// What settlement-grade verification is given.
#[derive(Default, Clone)]
pub struct Settlement {
    pub genesis_roots: Vec<String>,
    pub trust_config: Option<String>,
}

pub struct Finding {
    pub level: &'static str,
    pub subject: String,
    pub message: String,
}

/// The verifier's single reporter: counts, findings, and (unless quiet) text.
pub struct Report {
    pub quiet: bool,
    pub records: usize,
    pub errors: usize,
    pub warnings: usize,
    pub findings: Vec<Finding>,
    pub text: String,
}

impl Report {
    fn new(quiet: bool) -> Self {
        Report {
            quiet,
            records: 0,
            errors: 0,
            warnings: 0,
            findings: Vec::new(),
            text: String::new(),
        }
    }

    fn out(&mut self, level: &'static str, subject: &str, msg: String) {
        if level == "ERR" {
            self.errors += 1;
        } else {
            self.warnings += 1;
        }
        if !self.quiet {
            self.text
                .push_str(&format!("{:4} {}  {}\n", level, prefix(subject, 12), msg));
        }
        self.findings.push(Finding {
            level,
            subject: subject.to_string(),
            message: msg,
        });
    }

    fn info(&mut self, subject: &str, msg: String) {
        if !self.quiet {
            self.text
                .push_str(&format!("INFO {}  {}\n", prefix(subject, 12), msg));
        }
    }

    fn summary(&mut self) {
        if !self.quiet {
            self.text.push_str(&format!(
                "\nverify: {} records, {} errors, {} warnings\n",
                self.records, self.errors, self.warnings
            ));
        }
    }
}

/// An integer `ts` (never a bool or float), as its canonical text.
fn int_ts(v: Option<&Json>) -> Option<&str> {
    match v {
        Some(Json::Int(t)) => Some(t),
        _ => None,
    }
}

/// Numeric `a > b` on canonical integer texts of any size.
fn int_gt(a: &str, b: &str) -> bool {
    let (na, ma) = (a.starts_with('-'), a.trim_start_matches('-'));
    let (nb, mb) = (b.starts_with('-'), b.trim_start_matches('-'));
    let mag = (ma.len(), ma).cmp(&(mb.len(), mb));
    match (na, nb) {
        (false, true) => true,
        (true, false) => false,
        (false, false) => mag.is_gt(),
        (true, true) => mag.is_lt(),
    }
}

/// `verify_store`: verify every record. The returned report holds the counts,
/// the ordered findings and (unless `quiet`) the exact text the CLI prints.
pub fn verify_store(store: &Store, quiet: bool, settlement: Option<&Settlement>) -> Report {
    let mut rep = Report::new(quiet);
    let (recs, load_errors) = store.all_records();
    rep.records = recs.len() + load_errors.len();

    // Trust preflight runs BEFORE any per-record report, so a fail-closed
    // short-circuit is exactly one global ERR.
    let mut trust = Trust::default();
    if let Some(s) = settlement {
        if let Some(path) = s.trust_config.as_deref().filter(|p| !p.is_empty()) {
            match load_trust_config(path) {
                Ok(t) => trust = t,
                Err(_) => {
                    rep.out("ERR", "settlement", ERR_SETTLEMENT_TRUST.to_string());
                    rep.summary();
                    return rep;
                }
            }
        }
    }
    let mut load_errors = load_errors;
    load_errors.sort();
    for (wid, reason) in &load_errors {
        rep.out("ERR", wid, format!("unloadable record: {reason}"));
    }
    let ctx = settlement.map(|s| Context::build(store, &recs, &trust, &s.genesis_roots));
    if let Some(ctx) = &ctx {
        for (wid, msg) in &ctx.global_warnings {
            rep.out("WARN", wid, msg.clone());
        }
        for root in ctx.roots.difference(&ctx.active_roots) {
            rep.out("WARN", root, WARN_UNADOPTED_ROOT.to_string());
        }
    }

    for (wid, env) in recs.iter() {
        let eo = env.as_obj().unwrap();
        if !eo.has_exactly(&["body", "sigs"]) {
            rep.out("ERR", wid, "envelope must be {body, sigs}".to_string());
            continue;
        }
        let body = eo.get("body").unwrap();
        if ctx.as_ref().is_some_and(|c| c.invalid_policy.contains(wid)) {
            rep.out("ERR", wid, ERR_INVALID_THRESHOLD.to_string());
        }
        for m in validate_body(body) {
            rep.out("ERR", wid, format!("schema: {m}"));
        }
        match warrant_id(body) {
            Err(_) => {
                rep.out(
                    "ERR",
                    wid,
                    "WarrantID uncomputable (record contains invalid characters)".to_string(),
                );
                continue;
            }
            Ok(got) if &got != wid => {
                rep.out(
                    "ERR",
                    wid,
                    format!("WarrantID mismatch: recomputed {}", prefix(&got, 12)),
                );
                continue;
            }
            Ok(_) => {}
        }
        let Some(sigs) = eo.get("sigs").unwrap().as_arr() else {
            rep.out("ERR", wid, "sigs must be a list".to_string());
            continue;
        };
        if sigs.is_empty() {
            rep.out("ERR", wid, "no signatures".to_string());
        }
        let mut actor_signed = false;
        let body_actor_id = body
            .get("actor")
            .and_then(|a| a.as_obj())
            .and_then(|a| a.get("id"))
            .filter(|v| !matches!(v, Json::Null));
        for s in sigs {
            let Some(s) = s.as_obj() else {
                rep.out(
                    "WARN",
                    wid,
                    "signature entry is not an object (excluded)".to_string(),
                );
                continue;
            };
            let actor = s.get("actor");
            if !verify_sig(wid, s) {
                if legacy_sig(wid, s) {
                    rep.out(
                        "WARN",
                        wid,
                        format!("{LEGACY_SIG_MESSAGE}: actor {}", py_str_opt(actor)),
                    );
                } else {
                    rep.out(
                        "WARN",
                        wid,
                        format!(
                            "signature does not verify (excluded): actor {}",
                            py_str_opt(actor)
                        ),
                    );
                }
                continue;
            }
            let key = s.get("key").map(py_str).unwrap_or_default();
            match &ctx {
                None => rep.out(
                    "WARN",
                    wid,
                    format!(
                        "binding unverified (no keyring): key {} claims actor {}",
                        prefix(&key, 12),
                        py_str_opt(actor)
                    ),
                ),
                Some(c) => {
                    let keys = c.keys_before(wid);
                    let bound = match actor.and_then(Json::as_str) {
                        Some(a) if matches!(actor, Some(Json::Str(_))) => {
                            !c.conflict_actors.contains(a)
                                && keys.get(a).is_some_and(|ks| ks.contains(&key))
                        }
                        _ => false,
                    };
                    let line = format!(
                        "key {} claims actor {}",
                        prefix(&key, 12),
                        py_str_opt(actor)
                    );
                    if bound {
                        rep.info(wid, format!("signature bound: {line}"));
                    } else {
                        rep.out("WARN", wid, format!("signature unbound: {line}"));
                    }
                }
            }
            if let (Some(id), Some(a)) = (body_actor_id, actor) {
                if py_eq(a, id) {
                    actor_signed = true;
                }
            }
        }
        if !sigs.is_empty() && !actor_signed {
            rep.out(
                "ERR",
                wid,
                "no valid signature by body.actor.id".to_string(),
            );
        }

        // prior MUST resolve (§6(4)); ts non-decreasing along each edge is a
        // WARNING, because a clock is not authority (§5.1).
        let my_ts = int_ts(body.get("ts"));
        for p in body.get("prior").and_then(Json::as_arr).unwrap_or(&[]) {
            let Some(p) = p.as_str() else { continue };
            match recs.body(p) {
                None => rep.out("ERR", wid, format!("prior {} not in store", prefix(p, 12))),
                Some(prev) => {
                    if let (Some(a), Some(b)) = (int_ts(prev.get("ts")), my_ts) {
                        if int_gt(a, b) {
                            rep.out(
                                "WARN",
                                wid,
                                format!("ts decreases along prior edge {}", prefix(p, 12)),
                            );
                        }
                    }
                }
            }
        }

        // Reference resolution by field kind (SPEC §6/§7).
        let list = |k: &str| body.get(k).and_then(Json::as_arr).unwrap_or(&[]);
        let because: Vec<&Obj> = list("because").iter().filter_map(Json::as_obj).collect();
        let is_check = |r: &Obj| r.get("kind").is_some_and(|k| py_eq(k, &Json::str("check")));
        let mut blob_refs: Vec<&str> = list("under")
            .iter()
            .chain(list("evidence"))
            .filter_map(Json::as_str)
            .collect();
        blob_refs.extend(
            because
                .iter()
                .filter(|r| is_check(r))
                .filter_map(|r| r.get("check").and_then(Json::as_str)),
        );
        blob_refs.extend(
            because
                .iter()
                .filter(|r| is_check(r))
                .filter_map(|r| r.get("transcript").and_then(Json::as_str)),
        );
        for h in blob_refs {
            if !store.has_blob(h) {
                rep.out("WARN", wid, format!("unresolved blob {}", prefix(h, 12)));
            } else if !store.blob_intact(h) {
                let s = prefix(h, 12);
                rep.out("ERR", wid, format!("blob {s} content does not match its address (store claims these bytes are SHA-256 {s}…)"));
            }
        }
        let decision = body.get("decision");
        let dec_is = |d: &str| decision.is_some_and(|x| py_eq(x, &Json::str(d)));
        if let Some(subj) = body
            .get("subject")
            .and_then(|s| s.as_obj())
            .and_then(|s| s.get("hash"))
            .and_then(|h| match h {
                Json::Str(s) | Json::BadStr(s, _) => Some(s.as_str()),
                _ => None,
            })
        {
            let may_be_record = dec_is("supersede") || dec_is("accept");
            if !(store.has_blob(subj) || may_be_record && recs.contains(subj)) {
                rep.out("WARN", wid, format!("unresolved blob {}", prefix(subj, 12)));
            } else if store.has_blob(subj) && !store.blob_intact(subj) {
                rep.out(
                    "ERR",
                    wid,
                    format!(
                        "subject blob {} content does not match its address",
                        prefix(subj, 12)
                    ),
                );
            }
            if dec_is("supersede") && !recs.contains(subj) {
                rep.out(
                    "ERR",
                    wid,
                    "supersede subject MUST be the superseded WarrantID (SPEC s7)".to_string(),
                );
            }
        }
        if is_unverifiable(body) {
            rep.out(
                "WARN",
                wid,
                "UNVERIFIABLE: reject with prose-only reasons".to_string(),
            );
        }
        let settle_active = ctx.as_ref().is_some_and(|c| c.active_records.contains(wid));
        for r in &because {
            if is_check(r)
                && r.get("runtime")
                    .is_some_and(|x| py_eq(x, &Json::str("ski@v1")))
            {
                let check = r.get("check").and_then(Json::as_str).unwrap_or("");
                match run_ski_check(&store.blobs, check) {
                    Ok((got, rh, _)) => {
                        let claimed = r.get("verdict");
                        if !claimed.is_some_and(|v| py_eq(v, &Json::Str(got.clone()))) {
                            rep.out(
                                "WARN",
                                wid,
                                format!(
                                    "ski@v1 verdict mismatch: claimed {}, re-run gives {} ({})",
                                    py_str_opt(claimed),
                                    got,
                                    prefix(&rh, 12)
                                ),
                            );
                        }
                    }
                    Err(reason) => {
                        let lvl = if settle_active { "ERR" } else { "WARN" };
                        rep.out(lvl, wid, format!("ski@v1 unverified: {reason}"));
                    }
                }
            }
        }
        if let Some(c) = &ctx {
            if settle_active {
                let id = body
                    .get("actor")
                    .and_then(|a| a.get("id"))
                    .and_then(Json::as_str)
                    .unwrap_or("");
                if c.conflict_actors.contains(id) {
                    rep.out("WARN", wid, WARN_KEY_CONFLICT.to_string());
                }
                if dec_is("accept") || dec_is("reject") {
                    let subj = body.get("subject").and_then(|s| s.get("hash"));
                    for prior in prior_closure(&recs, wid) {
                        let pb = recs.body(&prior).unwrap();
                        let pdec = pb.get("decision").and_then(Json::as_str);
                        if c.active_records.contains(&prior)
                            && matches!(pdec, Some("accept" | "reject"))
                            && pb
                                .get("subject")
                                .and_then(|s| s.get("hash"))
                                .zip(subj)
                                .is_some_and(|(a, b)| py_eq(a, b))
                        {
                            if settlement_admissibility(store, &prior, body, &recs)
                                .starts_with("inadmissible")
                            {
                                rep.out("WARN", wid, WARN_RELITIGATION.to_string());
                            }
                            break;
                        }
                    }
                }
            }
        }
    }
    rep.summary();
    rep
}

/// `verify_report`: the SPEC §11 machine report, fail-closed on a non-store.
pub fn verify_report(store: &Store, settlement: Option<&Settlement>) -> Json {
    let grade = if settlement.is_some() {
        "settlement"
    } else {
        "base"
    };
    let mut o = Obj::new();
    o.insert("report", Json::str(VERIFY_REPORT_VERSION));
    o.insert("grade", Json::str(grade));
    if !store.is_initialized() {
        let mut f = Obj::new();
        f.insert("level", Json::str("ERR"));
        f.insert("subject", Json::str("store"));
        f.insert(
            "message",
            Json::str("no store (records/ is missing or not a directory)"),
        );
        o.insert("ok", Json::Bool(false));
        o.insert("records", Json::Int("0".into()));
        o.insert("errors", Json::Int("1".into()));
        o.insert("warnings", Json::Int("0".into()));
        o.insert("findings", Json::Array(vec![Json::Object(f)]));
        return Json::Object(o);
    }
    let rep = verify_store(store, true, settlement);
    o.insert("ok", Json::Bool(rep.errors == 0));
    o.insert("records", Json::Int(rep.records.to_string()));
    o.insert("errors", Json::Int(rep.errors.to_string()));
    o.insert("warnings", Json::Int(rep.warnings.to_string()));
    let findings = rep
        .findings
        .iter()
        .map(|f| {
            let mut x = Obj::new();
            x.insert("level", Json::str(f.level));
            x.insert("subject", Json::Str(f.subject.clone()));
            x.insert("message", Json::Str(f.message.clone()));
            Json::Object(x)
        })
        .collect();
    o.insert("findings", Json::Array(findings));
    Json::Object(o)
}

/// The report as the CLI prints it: one physical line of ASCII JSON.
pub fn verify_report_line(store: &Store, settlement: Option<&Settlement>) -> (String, bool) {
    let r = verify_report(store, settlement);
    let ok = matches!(r.get("errors"), Some(Json::Int(t)) if t == "0");
    (dumps_compact(&r), ok)
}
