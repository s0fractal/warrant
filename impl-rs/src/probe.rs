//! The `warrant-conformance/1` candidate contract (conformance/CONTRACT.md).
//!
//! `conformance` is this binary checking itself against files in this checkout.
//! `probe` is the inverse: it makes this binary a CANDIDATE an external runner
//! can drive without ever seeing this repository. One JSON request on stdin, one
//! JSON response on stdout, exit 0 whenever an answer was produced.
//!
//! This implementation is SPEC §6 BASE grade by design — no settlement, no key
//! state, no ski@v1 re-execution — so it declares `grade: "base"` and answers
//! `unsupported` for the settlement-grade classes. That asymmetry is real and
//! the contract exists partly to make it legible: a runner must report those
//! classes as UNRUN, never as passed and never as failed.

use super::*;
use std::io::Read;

pub const PROTOCOL: &str = "1";

const BASE_CLASSES: &[&str] = &[
    "capabilities",
    "canon",
    "validate",
    "blob-hash",
    "sig-message",
    "verify-sig",
    "parse",
    "verify-store",
];

fn b64_decode(s: &str) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    let mut acc: u32 = 0;
    let mut bits = 0u32;
    let mut pad = 0usize;
    for ch in s.bytes() {
        if ch == b'\n' || ch == b'\r' {
            continue;
        }
        let v = match ch {
            b'A'..=b'Z' => ch - b'A',
            b'a'..=b'z' => ch - b'a' + 26,
            b'0'..=b'9' => ch - b'0' + 52,
            b'+' => 62,
            b'/' => 63,
            b'=' => {
                pad += 1;
                continue;
            }
            _ => return None,
        };
        if pad > 0 {
            return None; // data after padding
        }
        acc = (acc << 6) | v as u32;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((acc >> bits) as u8);
        }
    }
    Some(out)
}

fn s(v: &str) -> Json {
    Json::Str(v.to_string())
}

fn obj(pairs: Vec<(&str, Json)>) -> Json {
    let mut m = BTreeMap::new();
    for (k, v) in pairs {
        m.insert(k.to_string(), v);
    }
    Json::Object(m)
}

fn get<'a>(input: &'a Json, key: &str) -> Option<&'a Json> {
    as_obj(input).and_then(|m| m.get(key))
}

fn get_str<'a>(input: &'a Json, key: &str) -> Result<&'a str, String> {
    get(input, key)
        .and_then(as_str)
        .ok_or_else(|| format!("input.{key} must be a string"))
}

fn get_bytes(input: &Json, key: &str) -> Result<Vec<u8>, String> {
    b64_decode(get_str(input, key)?).ok_or_else(|| format!("input.{key} is not valid base64"))
}

/// Ok(Some(output)) = answered; Ok(None) = unsupported; Err = protocol failure.
fn answer(class: &str, input: &Json) -> Result<Option<Json>, String> {
    match class {
        "capabilities" => Ok(Some(obj(vec![
            ("name", s("warrant-rs (independent implementation)")),
            ("version", s("body-format/0.2")),
            ("grade", s("base")),
            (
                "classes",
                Json::Array(BASE_CLASSES.iter().map(|c| s(c)).collect()),
            ),
        ]))),

        "canon" => {
            let body = get(input, "body").ok_or("input.body is required")?;
            let mut bytes = Vec::new();
            match canon(body, &mut bytes) {
                Err(e) => Ok(Some(obj(vec![("error", Json::Str(e))]))),
                Ok(()) => Ok(Some(obj(vec![
                    ("canon_hex", Json::Str(encode_hex(&bytes))),
                    ("warrant_id", Json::Str(encode_hex(&sha256(&bytes)))),
                ]))),
            }
        }

        "validate" => {
            let body = get(input, "body").ok_or("input.body is required")?;
            let errs = if as_obj(body).is_some() {
                validate_body(body)
            } else {
                vec!["body is not a JSON object".to_string()]
            };
            Ok(Some(obj(vec![
                ("valid", Json::Bool(errs.is_empty())),
                ("errors", Json::Array(errs.into_iter().map(Json::Str).collect())),
            ])))
        }

        "blob-hash" => {
            let data = get_bytes(input, "bytes_base64")?;
            Ok(Some(obj(vec![(
                "hash",
                Json::Str(encode_hex(&sha256(&data))),
            )])))
        }

        "sig-message" => {
            let wid = get_str(input, "warrant_id")?;
            match sig_message(wid) {
                None => Ok(Some(obj(vec![(
                    "error",
                    s("WarrantID is not 64 lowercase hex characters"),
                )]))),
                Some(m) => Ok(Some(obj(vec![(
                    "message_hex",
                    Json::Str(encode_hex(&m)),
                )]))),
            }
        }

        "verify-sig" => {
            let wid = get_str(input, "warrant_id")?.to_string();
            let mut sig = BTreeMap::new();
            sig.insert("key".to_string(), s(get_str(input, "key")?));
            sig.insert("sig".to_string(), s(get_str(input, "sig")?));
            Ok(Some(obj(vec![(
                "valid",
                Json::Bool(verify_sig(&wid, &sig)),
            )])))
        }

        "parse" => {
            let data = get_bytes(input, "bytes_base64")?;
            // Strictly the parser's own answer. The "top level is an object"
            // rule is NOT applied here: the three reference implementations
            // enforce it at three different layers and agree on the outcome, so
            // the pack does not vector it and this probe must not invent a
            // stricter parser than the binary actually has.
            Ok(Some(match Parser::parse(&data) {
                Ok(_) => obj(vec![("ok", Json::Bool(true))]),
                Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
            }))
        }

        "verify-store" => {
            // SPEC §6, base grade. A settlement-grade request is REFUSED rather
            // than answered with base-grade counts: this binary derives no key
            // state and reads no trust configuration, so returning "0 errors"
            // here would report a verification that never happened — which is
            // the exact failure SPEC §12.3 forbids. Refusing makes the runner
            // score it UNRUN, and the grade line then says `base`, truthfully.
            if get(input, "grade").and_then(as_str) == Some("settlement") {
                return Ok(None);
            }
            let store = get_str(input, "store_path")?;
            match verify_counts(store, true) {
                None => Ok(Some(obj(vec![("error", s("not a store"))]))),
                Some((errs, warns)) => Ok(Some(obj(vec![
                    ("errors", Json::Int(errs.to_string())),
                    ("warnings", Json::Int(warns.to_string())),
                ]))),
            }
        }

        _ => Ok(None),
    }
}

pub fn main() -> ExitCode {
    let mut raw = Vec::new();
    if let Err(e) = std::io::stdin().read_to_end(&mut raw) {
        eprintln!("probe: {e}");
        return ExitCode::from(2);
    }
    let req = match Parser::parse(&raw) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("probe: malformed request: {e}");
            return ExitCode::from(2);
        }
    };
    if get(&req, "warrant_conformance").and_then(as_str) != Some(PROTOCOL) {
        eprintln!("probe: unsupported request protocol");
        return ExitCode::from(2);
    }
    // The contract requires `id` to be a string, so echoing it needs no clone
    // of an arbitrary value.
    let id = get(&req, "id").and_then(as_str).unwrap_or("").to_string();
    let class = get(&req, "class").and_then(as_str).unwrap_or("").to_string();
    let empty = Json::Object(BTreeMap::new());
    let input = get(&req, "input").unwrap_or(&empty);

    let mut resp = BTreeMap::new();
    resp.insert("warrant_conformance".to_string(), s(PROTOCOL));
    resp.insert("id".to_string(), Json::Str(id));
    match answer(&class, input) {
        Err(e) => {
            eprintln!("probe: {e}");
            return ExitCode::from(2);
        }
        Ok(None) => {
            resp.insert(
                "unsupported".to_string(),
                Json::Str(format!(
                    "class \"{class}\" is not implemented by this candidate \
                     (warrant-rs is SPEC §6 base grade)"
                )),
            );
        }
        Ok(Some(out)) => {
            resp.insert("output".to_string(), out);
        }
    }
    let mut bytes = Vec::new();
    if let Err(e) = canon(&Json::Object(resp), &mut bytes) {
        eprintln!("probe: {e}");
        return ExitCode::from(2);
    }
    println!("{}", String::from_utf8_lossy(&bytes));
    ExitCode::SUCCESS
}
