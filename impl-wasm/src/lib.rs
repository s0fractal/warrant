//! Browser transport only. Verification belongs to warrant-verify.
#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use warrant_verify::{hash, json, settlement, ski, store::Store, verify};
use wasm_bindgen::prelude::*;

const MAX_FILES: usize = 2048;
const MAX_BYTES: usize = 8 * 1024 * 1024;

fn error(s: impl ToString) -> JsValue {
    JsValue::from_str(&s.to_string())
}

fn decode_hex(s: &str) -> Result<Vec<u8>, JsValue> {
    if !s.len().is_multiple_of(2) || !s.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(error("File bytes must be hexadecimal pairs"));
    }
    hash::fromhex(s).ok_or_else(|| error("Invalid file bytes"))
}

/// `require_records`: verification needs a record to verify; re-running a
/// check does not (native `warrant check` reads blobs only), so it may pass
/// blobs alone.
fn read_store(input: &str, require_records: bool) -> Result<Store, JsValue> {
    // The transport is not a Warrant format. Raw file bytes are never parsed
    // and re-serialized by JS before the actual verifier reads them.
    if input.len() > MAX_BYTES * 2 + 512 * 1024 {
        return Err(error("Store exceeds the browser's 8 MiB limit"));
    }
    let doc = json::parse_ijson(input.as_bytes()).map_err(error)?;
    let files = doc
        .as_obj()
        .ok_or_else(|| error("Expected a path-to-hex file map"))?;
    if files.iter().count() > MAX_FILES {
        return Err(error("Store exceeds 2048 files"));
    }
    let mut loaded = BTreeMap::new();
    let mut total = 0;
    let mut records = 0;
    for (path, value) in files.iter() {
        let valid = if let Some(name) = path.strip_prefix("records/") {
            records += 1;
            name.len() <= 200 && !name.contains(['/', '\\']) && name.ends_with(".json")
        } else if let Some(h) = path.strip_prefix("blobs/") {
            hash::is_hex64(h)
        } else {
            path == "genesis.json"
        };
        if !valid {
            return Err(error(format!("Unsupported store path: {path}")));
        }
        let bytes = decode_hex(
            value
                .as_str()
                .ok_or_else(|| error("File bytes must be hex strings"))?,
        )?;
        total += bytes.len();
        if total > MAX_BYTES {
            return Err(error("Store exceeds the browser's 8 MiB limit"));
        }
        loaded.insert(path.clone(), bytes);
    }
    if require_records && records == 0 {
        return Err(error("Select at least one records/*.json file"));
    }
    Ok(Store::from_memory(loaded))
}

#[wasm_bindgen]
pub fn verify_store(
    input: &str,
    trust_config: Option<String>,
    require_bound: Option<bool>,
) -> Result<String, JsValue> {
    if trust_config.as_ref().is_some_and(|t| t.len() > 256 * 1024) {
        return Err(error("Trust configuration exceeds 256 KiB"));
    }
    let require_bound = require_bound.unwrap_or(false);
    if require_bound && trust_config.is_none() {
        // WRT-018: binding is derived from the reader's trust; without it there is
        // nothing to require. The CLI refuses the same request without --settlement.
        return Err(error("requireBound needs a trust configuration"));
    }
    let store = read_store(input, true)?;
    let trust = trust_config.map(|text| {
        json::parse_ijson(text.as_bytes())
            .map_err(|e| e.to_string())
            .and_then(|v| settlement::validate_trust_config(&v))
    });
    Ok(json::dumps_compact(&verify::verify_report_with_trust_opts(
        &store,
        trust,
        require_bound,
    )))
}

#[wasm_bindgen]
pub fn record_id(raw_hex: &str) -> Result<String, JsValue> {
    if raw_hex.len() > MAX_BYTES * 2 {
        return Err(error("Record exceeds 8 MiB"));
    }
    let raw = decode_hex(raw_hex)?;
    let env = json::parse_ijson(&raw).map_err(error)?;
    let body = env.get("body").ok_or_else(|| error("Record has no body"))?;
    warrant_verify::store::warrant_id(body).map_err(error)
}

#[wasm_bindgen]
pub fn run_check(input: &str, check: &str) -> Result<String, JsValue> {
    let store = read_store(input, false)?;
    let (verdict, result, spent) = ski::run_store_ski_check(&store, check).map_err(error)?;
    let mut out = json::Obj::new();
    out.insert("verdict", json::Json::str(&verdict));
    out.insert("result", json::Json::str(&result));
    out.insert("atp_spent", json::Json::Int(spent.to_string()));
    Ok(json::dumps_compact(&json::Json::Object(out)))
}
