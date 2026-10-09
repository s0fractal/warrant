//! SPEC §2/§3: the record schema, with the reference's exact error strings.

use crate::hash::is_hex64;
use crate::json::{py_eq, py_repr, py_text, Json};

/// Version written into new records.
pub const VERSION: &str = "0.2";
/// Versions this implementation validates.
pub const ACCEPTED: [&str; 2] = ["0.1", "0.2"];
pub const DECISIONS: [&str; 4] = ["propose", "accept", "reject", "supersede"];
pub const BODY_FIELDS: [&str; 9] = [
    "warrant", "decision", "subject", "under", "because", "evidence", "actor", "prior", "ts",
];
/// SPEC §2: the largest integer any canonicalized JSON in this format may carry.
pub const JCS_SAFE_INT_MAX: i128 = 9007199254740991;

/// Runtimes a check reason may name, per body version (SPEC §3.1).
pub fn runtimes(version: &str) -> &'static [&'static str] {
    match version {
        "0.1" => &["cmd@v1"],
        _ => &["cmd@v1", "ski@v1"],
    }
}

fn tuple_repr(items: &[&str]) -> String {
    let parts: Vec<String> = items.iter().map(|s| format!("'{s}'")).collect();
    if parts.len() == 1 {
        format!("({},)", parts[0])
    } else {
        format!("({})", parts.join(", "))
    }
}

/// Python `x in (str, ...)`: equality, never hashing.
fn str_in(v: &Json, items: &[&str]) -> bool {
    v.as_str().is_some_and(|s| items.contains(&s))
}

pub fn hex64_val(v: &Json) -> bool {
    v.as_str().is_some_and(is_hex64)
}

/// SPEC §2: the first integer outside ±(2^53−1), in the reference's traversal
/// order (an explicit stack; objects push their values in document order and
/// pop from the end), or None.
pub fn int_domain_violation(v: &Json) -> Option<String> {
    let mut stack = vec![v];
    while let Some(cur) = stack.pop() {
        match cur {
            Json::Int(t) => {
                let ok = t
                    .parse::<i128>()
                    .is_ok_and(|n| (-JCS_SAFE_INT_MAX..=JCS_SAFE_INT_MAX).contains(&n));
                if !ok {
                    return Some(t.clone());
                }
            }
            Json::Object(o) => stack.extend(o.values()),
            Json::Array(a) => stack.extend(a.iter()),
            _ => {}
        }
    }
    None
}

/// Errors in a body; empty means schema-valid.
pub fn validate_body(v: &Json) -> Vec<String> {
    validate_body_json(v)
        .into_iter()
        .map(|m| m.as_str().unwrap_or_default().to_string())
        .collect()
}

/// [`validate_body`], with each message as the Python string the reference
/// builds: an unknown member name is quoted with its exact code points, which a
/// leniently parsed body (the conformance probe's) may give unpaired surrogates.
pub fn validate_body_json(v: &Json) -> Vec<Json> {
    let b = match v.as_obj() {
        Some(o) => o,
        None => return vec![Json::str("body is not an object")],
    };
    let mut unknown: Vec<Vec<u32>> = (0..b.len())
        .filter(|&i| !BODY_FIELDS.contains(&b.0[i].0.as_str()))
        .map(|i| b.key_units(i))
        .collect();
    unknown.sort();
    let mut head: Vec<Json> = unknown
        .iter()
        .map(|k| py_text("unknown field: ", k))
        .collect();
    head.extend(validate_known(v, b).into_iter().map(Json::Str));
    head
}

fn validate_known(v: &Json, b: &crate::json::Obj) -> Vec<String> {
    let mut e = Vec::new();
    let unknown_present = b.keys().any(|k| !BODY_FIELDS.contains(&k.as_str()));
    let mut missing: Vec<&str> = BODY_FIELDS
        .iter()
        .copied()
        .filter(|f| !b.contains_key(f))
        .collect();
    missing.sort();
    for k in missing {
        e.push(format!("missing field: {k}"));
    }
    if !e.is_empty() || unknown_present {
        return e;
    }
    let f = |k: &str| b.get(k).unwrap();
    if !str_in(f("warrant"), &ACCEPTED) {
        e.push(format!(
            "warrant version must be one of {}",
            tuple_repr(&ACCEPTED)
        ));
    }
    if !str_in(f("decision"), &DECISIONS) {
        e.push(format!(
            "decision must be one of {}",
            tuple_repr(&DECISIONS)
        ));
    }
    match f("subject").as_obj() {
        Some(s) if s.keys().all(|k| k == "hash" || k == "note") && s.contains_key("hash") => {
            if !hex64_val(s.get("hash").unwrap()) {
                e.push("subject.hash must be hex64".into());
            }
            if let Some(note) = s.get("note") {
                if !note.as_str().is_some_and(|t| t.chars().count() <= 200) {
                    e.push("subject.note must be a string of <=200 chars".into());
                }
            }
        }
        _ => e.push("subject must be {hash, note?}".into()),
    }
    if !f("under")
        .as_arr()
        .is_some_and(|a| !a.is_empty() && a.iter().all(hex64_val))
    {
        e.push("under must be a list of >=1 hex64 hashes".into());
    }
    if !f("evidence")
        .as_arr()
        .is_some_and(|a| a.iter().all(hex64_val))
    {
        e.push("evidence must be a list of hex64 hashes".into());
    }
    let actor_ok = f("actor").as_obj().is_some_and(|a| {
        a.len() == 1
            && matches!(a.get("id"), Some(Json::Str(s) | Json::BadStr(s, _)) if !s.is_empty())
    });
    if !actor_ok {
        e.push("actor must be {id: <nonempty string>}".into());
    }
    if !f("prior").as_arr().is_some_and(|a| a.iter().all(hex64_val)) {
        e.push("prior must be a list of WarrantIDs (hex64)".into());
    }
    let ts_ok = f("ts")
        .as_int()
        .is_some_and(|n| (0..=JCS_SAFE_INT_MAX).contains(&n));
    if !ts_ok {
        e.push("ts must be an integer (unix seconds) in 0..2^53-1".into());
    }
    if let Some(bad) = int_domain_violation(v) {
        e.push(format!(
            "integer {bad} is outside the §2 domain of +/-(2^53-1)"
        ));
    }
    let empty: Vec<Json> = Vec::new();
    let bc = match f("because").as_arr() {
        Some(a) => a,
        None => {
            e.push("because must be a list".into());
            &empty[..]
        }
    };
    let ver = match f("warrant").as_str() {
        Some(s) if ACCEPTED.contains(&s) => s,
        _ => VERSION,
    };
    for (i, r) in bc.iter().enumerate() {
        for m in validate_reason(r, ver) {
            e.push(format!("because[{i}]: {m}"));
        }
    }
    if let Some(d) = f("decision").as_str() {
        if (d == "reject" || d == "supersede") && bc.is_empty() {
            e.push(format!("{d} requires >=1 reason"));
        }
    }
    e
}

pub fn validate_reason(v: &Json, version: &str) -> Vec<String> {
    let r = match v.as_obj() {
        Some(o) => o,
        None => return vec!["reason is not an object".into()],
    };
    let kind = r.get("kind");
    if kind.is_some_and(|k| py_eq(k, &Json::str("prose"))) {
        if !r.has_exactly(&["kind", "text"]) || r.get("text").and_then(Json::as_str).is_none() {
            return vec!["prose reason must be {kind, text}".into()];
        }
        return vec![];
    }
    if kind.is_some_and(|k| py_eq(k, &Json::str("check"))) {
        const ALLOWED: [&str; 5] = ["kind", "check", "runtime", "verdict", "transcript"];
        if r.keys().any(|k| !ALLOWED.contains(&k.as_str())) {
            return vec!["check reason has unknown fields".into()];
        }
        let mut e = Vec::new();
        if !r.get("check").is_some_and(hex64_val) {
            e.push("check must be hex64".into());
        }
        let allowed = runtimes(version);
        let rt = r.get("runtime");
        let is = |name: &str| rt.is_some_and(|x| py_eq(x, &Json::str(name)));
        if is("ski@v1") && !allowed.contains(&"ski@v1") {
            e.push("runtime ski@v1 is reserved and MUST be rejected in v0.1".into());
        } else if !rt.is_some_and(|x| str_in(x, allowed)) {
            e.push(format!("runtime must be one of {}", tuple_repr(allowed)));
        }
        if !r
            .get("verdict")
            .is_some_and(|x| str_in(x, &["pass", "fail"]))
        {
            e.push("verdict must be pass|fail".into());
        }
        if let Some(t) = r.get("transcript") {
            if !hex64_val(t) {
                e.push("transcript must be hex64".into());
            }
        }
        return e;
    }
    vec![format!(
        "unknown reason kind: {}",
        kind.map(py_repr).unwrap_or_else(|| "None".into())
    )]
}

/// SPEC §3: a reject whose every reason is prose. Shape-defensive.
pub fn is_unverifiable(body: &Json) -> bool {
    let Some(b) = body.as_obj() else { return false };
    let Some(because) = b.get("because").and_then(Json::as_arr) else {
        return false;
    };
    if because.is_empty() {
        return false;
    }
    b.get("decision")
        .is_some_and(|d| py_eq(d, &Json::str("reject")))
        && because
            .iter()
            .all(|r| r.get("kind").is_some_and(|k| py_eq(k, &Json::str("prose"))))
}
