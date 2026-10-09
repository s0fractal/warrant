//! `conformance` (SPEC §8: this implementation against the pinned vectors in a
//! checkout), `selftest` (a live round-trip), and `probe` (the
//! `warrant-conformance/1` candidate contract an external runner drives).

use crate::hash::{blob_hash, encode_hex, fromhex, sha256};
use crate::json::{
    canon, dumps_compact, parse_ijson, parse_plain_bytes, parse_plain_text, prefix, Json, Obj,
};
use crate::ops::{file_warrant, Filing};
use crate::schema::{validate_body, VERSION};
use crate::sig::{sig_message, verify_sig, weak_ed25519_pubkey};
use crate::ski::run_ski_check;
use crate::store::{warrant_id, Store};
use crate::verify::{verify_store, Settlement};
use std::path::{Path, PathBuf};

const SPEC_VECTORS: [(&str, &str); 5] = [
    (
        "policy.txt",
        "cb3a0afe6ee6219867b9c3f9b860080918fe1042f315fe02ff62300f780beb73",
    ),
    (
        "check.sh",
        "05d234bec21803c6fa007d848c1773b9fd05cfdf852d6d09542ed3b127c02b6c",
    ),
    (
        "propose.warrant.json",
        "00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1",
    ),
    (
        "reject.warrant.json",
        "5f5d4035a4ae04a3eec255105eee7dda7c98daaf9962c92cbbbad38ac21509d8",
    ),
    (
        "accept.warrant.json",
        "bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78",
    ),
];

fn vector(name: &str) -> &'static str {
    SPEC_VECTORS.iter().find(|(n, _)| *n == name).unwrap().1
}

/// A scratch directory removed on drop.
pub struct TempDir(pub PathBuf);

impl TempDir {
    pub fn new(tag: &str) -> std::io::Result<TempDir> {
        let rnd = crate::sig::os_random_32().map_err(std::io::Error::other)?;
        let p = std::env::temp_dir().join(format!("warrant-rs-{tag}-{}", &encode_hex(&rnd)[..16]));
        std::fs::create_dir_all(&p)?;
        Ok(TempDir(p))
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn read_json(path: &Path) -> Result<Json, String> {
    let raw = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    parse_plain_bytes(&raw).map_err(|e| format!("{}: {e}", path.display()))
}

fn sigs_of(env: &Json) -> Vec<&Obj> {
    env.get("sigs")
        .and_then(Json::as_arr)
        .map(|a| a.iter().filter_map(Json::as_obj).collect())
        .unwrap_or_default()
}

pub fn conformance(dir: &str) -> Result<bool, String> {
    let d = Path::new(dir);
    let mut ok: Vec<bool> = Vec::new();
    let mut chk = |name: &str, cond: bool, detail: &str| {
        ok.push(cond);
        if cond {
            println!("OK   {name} ");
        } else {
            println!("FAIL {name} {detail}");
        }
    };
    for name in ["policy.txt", "check.sh"] {
        let got = blob_hash(&std::fs::read(d.join(name)).map_err(|e| format!("{name}: {e}"))?);
        chk(&format!("blob {name}"), got == vector(name), &got);
    }
    let mut chain: Vec<(String, Json)> = Vec::new();
    for name in [
        "propose.warrant.json",
        "reject.warrant.json",
        "accept.warrant.json",
    ] {
        let env = read_json(&d.join(name))?;
        let body = env.get("body").cloned().unwrap_or(Json::Null);
        let errs = validate_body(&body);
        chk(&format!("schema {name}"), errs.is_empty(), &errs.join("; "));
        let wid = warrant_id(&body).map_err(|e| e.to_string())?;
        chk(&format!("WarrantID {name}"), wid == vector(name), &wid);
        for s in sigs_of(&env) {
            let actor = s.get("actor").map(crate::json::py_str).unwrap_or_default();
            chk(&format!("sig {name} by {actor}"), verify_sig(&wid, s), "");
        }
        chain.push((wid, body));
    }
    let prior_is = |i: usize, want: &str| {
        chain[i]
            .1
            .get("prior")
            .and_then(Json::as_arr)
            .is_some_and(|a| a.len() == 1 && a[0].as_str() == Some(want))
    };
    let c1 = prior_is(1, &chain[0].0);
    let c2 = prior_is(2, &chain[1].0);
    chk("chain reject.prior -> propose", c1, "");
    chk("chain accept.prior -> reject", c2, "");
    let ts: Vec<i128> = chain
        .iter()
        .map(|(_, b)| b.get("ts").and_then(Json::as_int).unwrap_or(i128::MIN))
        .collect();
    chk("ts non-decreasing", ts.windows(2).all(|w| w[0] <= w[1]), "");

    let ski_dir = d.join("ski");
    if ski_dir.is_dir() {
        let env = read_json(&ski_dir.join("accept-ski.warrant.json"))?;
        let body = env.get("body").cloned().unwrap_or(Json::Null);
        let wid = warrant_id(&body).map_err(|e| e.to_string())?;
        chk(
            "ski: warrant id",
            wid == "8c9267bccbc217db2f3f16e6928acaf062a1c78443b2317985567b238ccfe8a0",
            &wid,
        );
        let errs = validate_body(&body);
        chk("ski: schema (0.2 body)", errs.is_empty(), &errs.join("; "));
        for s in sigs_of(&env) {
            let actor = s.get("actor").map(crate::json::py_str).unwrap_or_default();
            chk(&format!("ski: sig by {actor}"), verify_sig(&wid, s), "");
        }
        let cb = std::fs::read(ski_dir.join("check.json")).map_err(|e| e.to_string())?;
        let ch = blob_hash(&cb);
        chk(
            "ski: check blob hash",
            ch == "0c30960435e9c9302a6a1538682e5864f2a754475369979bd3d635543976b2ad",
            &ch,
        );
        let mut v01 = body.clone();
        if let Some(o) = v01.as_obj_mut() {
            o.insert("warrant", Json::str("0.1"));
        }
        chk(
            "ski: 0.1 body MUST reject ski@v1",
            validate_body(&v01).iter().any(|m| m.contains("reserved")),
            "",
        );
        // The evaluator is compiled in: there is no "runtime unavailable" here.
        let td = TempDir::new("conformance").map_err(|e| e.to_string())?;
        let st = Store::new(&td.0);
        st.init().map_err(|e| e.to_string())?;
        let mut bins: Vec<PathBuf> = std::fs::read_dir(&ski_dir)
            .map_err(|e| e.to_string())?
            .flatten()
            .map(|e| e.path())
            .collect();
        bins.sort();
        for f in bins
            .iter()
            .filter(|p| p.extension().is_some_and(|x| x == "bin"))
        {
            st.put_blob(&std::fs::read(f).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
        }
        st.put_blob(&cb).map_err(|e| e.to_string())?;
        match run_ski_check(&st.blobs, &ch) {
            Err(e) => chk("ski: runtime re-run refused", false, &e),
            Ok((verdict, rh, spent)) => chk(
                "ski: re-run -> pass, H(S), 20 ATP",
                verdict == "pass"
                    && spent == 20
                    && rh == "887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6",
                &format!("{verdict} {rh} {spent}"),
            ),
        }
    }

    let neg = d.join("conformance-negatives.json");
    if neg.exists() {
        let doc = read_json(&neg)?;
        for k in doc
            .get("weak_ed25519_pubkeys")
            .and_then(Json::as_arr)
            .unwrap_or(&[])
        {
            let ks = k.as_str().unwrap_or("");
            let mut sig = Obj::new();
            sig.insert("actor", Json::str("x"));
            sig.insert("key", Json::str(ks));
            sig.insert("sig", Json::Str("00".repeat(64)));
            let weak = fromhex(ks)
                .map(|b| weak_ed25519_pubkey(&b))
                .unwrap_or(false);
            chk(
                &format!("neg: weak Ed25519 key {} rejected", prefix(ks, 12)),
                weak && !verify_sig(&"00".repeat(64), &sig),
                "",
            );
        }
        for case in doc
            .get("schema_invalid")
            .and_then(Json::as_arr)
            .unwrap_or(&[])
        {
            let why = case.get("why").map(crate::json::py_str).unwrap_or_default();
            let body = case.get("body").cloned().unwrap_or(Json::Null);
            chk(
                &format!("neg: schema-invalid ({why})"),
                !validate_body(&body).is_empty(),
                "",
            );
        }
    }

    let sv = d.join("signature-vectors.json");
    if sv.exists() {
        let doc = read_json(&sv)?;
        let s = |v: &Json, k: &str| v.get(k).and_then(Json::as_str).unwrap_or("").to_string();
        for m in doc.get("message").and_then(Json::as_arr).unwrap_or(&[]) {
            let got = sig_message(&s(m, "warrant_id"))
                .map(|b| encode_hex(&b))
                .unwrap_or_default();
            chk(
                &format!("sig-msg: {}", s(m, "why")),
                got == s(m, "message_hex"),
                "",
            );
        }
        for (field, expect) in [("accept", true), ("reject", false)] {
            for c in doc.get(field).and_then(Json::as_arr).unwrap_or(&[]) {
                let o = c.as_obj().cloned().unwrap_or_default();
                chk(
                    &format!("sig-{field}: {}", prefix(&s(c, "why"), 60)),
                    verify_sig(&s(c, "warrant_id"), &o) == expect,
                    "",
                );
            }
        }
    }
    let passed = ok.iter().filter(|&&v| v).count();
    let all = passed == ok.len();
    println!(
        "\n{} ({}/{})",
        if all {
            "CONFORMANCE: ALL PASS"
        } else {
            "CONFORMANCE: FAILURES PRESENT"
        },
        passed,
        ok.len()
    );
    Ok(all)
}

// -------------------------------------------------------------- selftest ----

/// A live round-trip in a scratch store: file, verify, tamper, re-verify.
pub fn selftest() -> Result<bool, String> {
    let td = TempDir::new("selftest").map_err(|e| e.to_string())?;
    let st = Store::new(td.0.join(".warrants"));
    st.init().map_err(|e| e.to_string())?;
    let key = td.0.join("k.key");
    std::fs::write(&key, encode_hex(&crate::sig::os_random_32()?)).map_err(|e| e.to_string())?;
    let policy = st
        .put_blob(b"POLICY: selftest v1\n1. be verifiable\n")
        .map_err(|e| e.to_string())?;
    let check = st
        .put_blob(b"#!/bin/sh\ntrue\n")
        .map_err(|e| e.to_string())?;
    let subject = st
        .put_blob(b"the change under decision\n")
        .map_err(|e| e.to_string())?;
    let key = key.display().to_string();
    let base = Filing {
        under: vec![policy.clone()],
        actor: "tester@self".into(),
        key: key.clone(),
        runtime: "cmd@v1".into(),
        verdict: "pass".into(),
        ..Default::default()
    };
    let exit = |e: crate::ops::Exit| e.message.unwrap_or_default();
    let a1 = Filing {
        reason: vec!["needed".into()],
        ts: Some(1751700000),
        ..base.clone()
    };
    let w1 = file_warrant(
        &st,
        "propose",
        Json::Str(subject.clone()),
        &a1,
        Some(Json::str("selftest")),
    )
    .map_err(exit)?;
    let a2 = Filing {
        prior: vec![w1.clone()],
        check: Some(check),
        ts: Some(1751700001),
        ..base
    };
    let w2 = file_warrant(&st, "accept", Json::Str(subject), &a2, None).map_err(exit)?;
    let r = verify_store(&st, true, None);
    if r.errors != 0 {
        return Err(format!("selftest: verify errors {}", r.errors));
    }
    let rec2 = st.get_record(&w2)?.ok_or("selftest: record missing")?;
    if !rec2
        .get("body")
        .and_then(|b| b.get("prior"))
        .and_then(Json::as_arr)
        .is_some_and(|p| p.len() == 1 && p[0].as_str() == Some(&w1))
    {
        return Err("selftest: prior edge not recorded".into());
    }
    // tamper: one byte of meaning in the stored body must break identity
    let mut env = st.get_record(&w1)?.ok_or("selftest: record missing")?;
    if let Some(ts) = env
        .as_obj_mut()
        .and_then(|o| o.get_mut("body"))
        .and_then(|b| b.as_obj_mut())
        .and_then(|b| b.get_mut("ts"))
    {
        *ts = Json::Int("1751700001".into());
    }
    std::fs::write(
        st.records.join(format!("{w1}.json")),
        crate::json::dumps_default(&env),
    )
    .map_err(|e| e.to_string())?;
    if verify_store(&st, true, None).errors < 1 {
        return Err("selftest: tampering not detected".into());
    }
    println!("SELFTEST: ALL PASS");
    Ok(true)
}

// ----------------------------------------------------------------- probe ----

pub const PROBE_PROTOCOL: &str = "1";
const PROBE_CLASSES: [&str; 9] = [
    "capabilities",
    "canon",
    "validate",
    "blob-hash",
    "sig-message",
    "verify-sig",
    "parse",
    "verify-store",
    "ski-run",
];

/// `base64.b64decode(s, validate=True)`.
pub fn b64_decode(s: &str) -> Option<Vec<u8>> {
    let b = s.as_bytes();
    if b.len() % 4 != 0 {
        return None;
    }
    let mut out = Vec::with_capacity(b.len() / 4 * 3);
    for (ci, chunk) in b.chunks_exact(4).enumerate() {
        let last = ci == b.len() / 4 - 1;
        let mut acc = 0u32;
        let mut pad = 0;
        for (i, &c) in chunk.iter().enumerate() {
            let v = match c {
                b'A'..=b'Z' => c - b'A',
                b'a'..=b'z' => c - b'a' + 26,
                b'0'..=b'9' => c - b'0' + 52,
                b'+' => 62,
                b'/' => 63,
                b'=' if last && i >= 2 => {
                    pad += 1;
                    0
                }
                _ => return None,
            };
            if pad > 0 && c != b'=' {
                return None;
            }
            acc = (acc << 6) | v as u32;
        }
        let bytes = acc.to_be_bytes();
        out.extend_from_slice(&bytes[1..4 - pad]);
    }
    Some(out)
}

fn obj(pairs: Vec<(&str, Json)>) -> Json {
    let mut o = Obj::new();
    for (k, v) in pairs {
        o.insert(k, v);
    }
    Json::Object(o)
}

fn input_str<'a>(inp: &'a Json, k: &str) -> Result<&'a str, String> {
    inp.get(k)
        .and_then(Json::as_str)
        .ok_or_else(|| format!("input.{k} must be a string"))
}

fn input_b64(inp: &Json, k: &str) -> Result<Vec<u8>, String> {
    b64_decode(input_str(inp, k)?).ok_or_else(|| format!("input.{k} is not valid base64"))
}

fn trunc(s: &str) -> Json {
    Json::Str(prefix(s, 200))
}

/// Ok(Ok(output)) answered; Ok(Err(reason)) unsupported; Err = protocol failure.
pub fn probe_answer(class: Option<&Json>, inp: &Json) -> Result<Result<Json, String>, String> {
    // Only a clean string can name a class; anything else is refused by name.
    let cls = match class {
        Some(Json::Str(s)) => s.as_str(),
        _ => "",
    };
    Ok(Ok(match cls {
        "capabilities" => obj(vec![
            ("name", Json::str("warrant-rs (independent implementation)")),
            ("version", Json::Str(format!("body-format/{VERSION}"))),
            ("grade", Json::str("settlement")),
            (
                "classes",
                Json::Array(PROBE_CLASSES.iter().map(|c| Json::str(c)).collect()),
            ),
        ]),
        "canon" => {
            let body = inp.get("body").ok_or("input.body is required")?;
            match canon(body) {
                Err(e) => obj(vec![("error", trunc(&e.to_string()))]),
                Ok(raw) => obj(vec![
                    ("canon_hex", Json::Str(encode_hex(&raw))),
                    ("warrant_id", Json::Str(encode_hex(&sha256(&raw)))),
                ]),
            }
        }
        "validate" => {
            let body = inp.get("body").ok_or("input.body is required")?;
            if body.as_obj().is_none() {
                obj(vec![
                    ("valid", Json::Bool(false)),
                    (
                        "errors",
                        Json::Array(vec![Json::str("body is not a JSON object")]),
                    ),
                ])
            } else {
                let errs = crate::schema::validate_body_json(body);
                obj(vec![
                    ("valid", Json::Bool(errs.is_empty())),
                    ("errors", Json::Array(errs)),
                ])
            }
        }
        "blob-hash" => obj(vec![(
            "hash",
            Json::Str(blob_hash(&input_b64(inp, "bytes_base64")?)),
        )]),
        "sig-message" => match sig_message(input_str(inp, "warrant_id")?) {
            Ok(m) => obj(vec![("message_hex", Json::Str(encode_hex(&m)))]),
            Err(e) => obj(vec![("error", trunc(&e))]),
        },
        "verify-sig" => {
            let mut sig = Obj::new();
            sig.insert("actor", Json::str("probe"));
            sig.insert(
                "key",
                inp.get("key").cloned().ok_or("input.key is required")?,
            );
            sig.insert(
                "sig",
                inp.get("sig").cloned().ok_or("input.sig is required")?,
            );
            let wid = inp
                .get("warrant_id")
                .ok_or("input.warrant_id is required")?;
            let valid = wid.as_str().is_some_and(|w| verify_sig(w, &sig));
            obj(vec![("valid", Json::Bool(valid))])
        }
        "parse" => match parse_ijson(&input_b64(inp, "bytes_base64")?) {
            Ok(_) => obj(vec![("ok", Json::Bool(true))]),
            Err(e) => obj(vec![
                ("ok", Json::Bool(false)),
                ("error", crate::json::py_slice(&e.to_json(), 200)),
            ]),
        },
        "verify-store" => {
            let store = Store::new(input_str(inp, "store_path")?);
            if !store.is_initialized() {
                obj(vec![("error", Json::str("not a store"))])
            } else {
                let settlement = (inp.get("grade").and_then(Json::as_str) == Some("settlement"))
                    .then(|| Settlement {
                        genesis_roots: inp
                            .get("genesis")
                            .and_then(Json::as_arr)
                            .map(|a| {
                                a.iter()
                                    .filter_map(Json::as_str)
                                    .map(String::from)
                                    .collect()
                            })
                            .unwrap_or_default(),
                        trust_config: inp
                            .get("trust_config_path")
                            .and_then(Json::as_str)
                            .map(String::from),
                    });
                let r = verify_store(&store, true, settlement.as_ref());
                obj(vec![
                    ("errors", Json::Int(r.errors.to_string())),
                    ("warnings", Json::Int(r.warnings.to_string())),
                ])
            }
        }
        "ski-run" => {
            let td = TempDir::new("probe").map_err(|e| e.to_string())?;
            let st = Store::new(&td.0);
            st.init().map_err(|e| e.to_string())?;
            if let Some(blobs) = inp.get("blobs_base64").and_then(Json::as_obj) {
                for v in blobs.values() {
                    let b = v
                        .as_str()
                        .and_then(b64_decode)
                        .ok_or("input.blobs_base64 holds invalid base64")?;
                    st.put_blob(&b).map_err(|e| e.to_string())?;
                }
            }
            let check = st
                .put_blob(&input_b64(inp, "check_base64")?)
                .map_err(|e| e.to_string())?;
            match run_ski_check(&st.blobs, &check) {
                Err(e) => obj(vec![("error", trunc(&e))]),
                Ok((verdict, rh, spent)) => obj(vec![
                    ("verdict", Json::Str(verdict)),
                    ("result_node_hash", Json::Str(rh)),
                    ("atp_spent", Json::Int(spent.to_string())),
                ]),
            }
        }
        _ => {
            let shown = class
                .map(crate::json::py_repr)
                .unwrap_or_else(|| "None".into());
            return Ok(Err(format!(
                "class {shown} is not implemented by this candidate"
            )));
        }
    }))
}

/// Read one request from stdin, write one response. The exit status is NOT the
/// verdict: nonzero means only that no answer was produced.
pub fn probe() -> Result<(), String> {
    use std::io::Read;
    let mut raw = Vec::new();
    std::io::stdin()
        .read_to_end(&mut raw)
        .map_err(|e| e.to_string())?;
    let req = parse_plain_text(&raw).map_err(|e| format!("malformed request: {e}"))?;
    let ro = req.as_obj().ok_or("request must be a JSON object")?;
    if !ro
        .get("warrant_conformance")
        .is_some_and(|v| crate::json::py_eq(v, &Json::str(PROBE_PROTOCOL)))
    {
        return Err(format!(
            "unsupported request protocol {}",
            ro.get("warrant_conformance")
                .map(crate::json::py_repr)
                .unwrap_or_else(|| "None".into())
        ));
    }
    let empty = Json::Object(Obj::new());
    let inp = match ro.get("input") {
        Some(v) if crate::settlement::truthy(Some(v)) => v,
        _ => &empty,
    };
    let answer = probe_answer(ro.get("class"), inp)?;
    let mut resp = Obj::new();
    resp.insert("warrant_conformance", Json::str(PROBE_PROTOCOL));
    resp.insert("id", ro.get("id").cloned().unwrap_or(Json::Null));
    match answer {
        Ok(out) => resp.insert("output", out),
        Err(reason) => resp.insert("unsupported", Json::Str(reason)),
    }
    println!("{}", dumps_compact(&Json::Object(resp)));
    Ok(())
}
