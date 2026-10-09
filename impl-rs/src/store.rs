//! The plain-file store: `<root>/blobs/<sha256>` and `<root>/records/<WarrantID>.json`.

use crate::hash::{blob_hash, is_hex64};
use crate::json::{canon, dumps_pretty_sorted, parse_ijson_str, parse_plain_str, Json, ParseError};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

/// `warrant_id(body)`: SHA-256 over the canonical bytes (SPEC §4).
pub fn warrant_id(body: &Json) -> Result<String, crate::json::CanonError> {
    canon(body).map(|b| blob_hash(&b))
}

/// Records in the order the reference iterates them (sorted file names), with
/// an index by WarrantID.
#[derive(Default)]
pub struct Records {
    pub list: Vec<(String, Json)>,
    index: HashMap<String, usize>,
}

impl Records {
    pub fn push(&mut self, wid: String, env: Json) {
        self.index.insert(wid.clone(), self.list.len());
        self.list.push((wid, env));
    }
    pub fn get(&self, wid: &str) -> Option<&Json> {
        self.index.get(wid).map(|&i| &self.list[i].1)
    }
    /// The body of a record (every loaded record has an object body).
    pub fn body(&self, wid: &str) -> Option<&Json> {
        self.get(wid).and_then(|e| e.get("body"))
    }
    pub fn contains(&self, wid: &str) -> bool {
        self.index.contains_key(wid)
    }
    pub fn len(&self) -> usize {
        self.list.len()
    }
    pub fn is_empty(&self) -> bool {
        self.list.is_empty()
    }
    pub fn wids(&self) -> impl Iterator<Item = &String> {
        self.list.iter().map(|(w, _)| w)
    }
    pub fn iter(&self) -> impl Iterator<Item = &(String, Json)> {
        self.list.iter()
    }
}

/// `Path.stem`: the name without its last suffix, where a leading dot does not
/// start a suffix (`.json` has none; `..json` has stem `.`).
pub fn stem(name: &str) -> &str {
    match name.rfind('.') {
        Some(i) if i > 0 && i < name.len() - 1 => &name[..i],
        _ => name,
    }
}

pub struct Store {
    pub root: PathBuf,
    pub blobs: PathBuf,
    pub records: PathBuf,
}

impl Store {
    pub fn new(root: impl AsRef<Path>) -> Self {
        let root = root.as_ref().to_path_buf();
        Store {
            blobs: root.join("blobs"),
            records: root.join("records"),
            root,
        }
    }

    pub fn init(&self) -> std::io::Result<()> {
        fs::create_dir_all(&self.blobs)?;
        fs::create_dir_all(&self.records)
    }

    pub fn is_initialized(&self) -> bool {
        self.records.is_dir()
    }

    pub fn put_blob(&self, data: &[u8]) -> std::io::Result<String> {
        let h = blob_hash(data);
        let p = self.blobs.join(&h);
        if !p.exists() {
            fs::write(&p, data)?;
        }
        Ok(h)
    }

    /// A blob exists only if `h` is a hex64 name AND names a regular file.
    pub fn has_blob(&self, h: &str) -> bool {
        is_hex64(h) && self.blobs.join(h).is_file()
    }

    /// Do the bytes at `blobs/<h>` actually hash to `<h>`?
    pub fn blob_intact(&self, h: &str) -> bool {
        fs::read(self.blobs.join(h)).is_ok_and(|b| blob_hash(&b) == h)
    }

    pub fn blob_bytes(&self, h: &str) -> Option<Vec<u8>> {
        fs::read(self.blobs.join(h)).ok()
    }

    /// Write an envelope with the store's one writer; returns its WarrantID.
    pub fn put_record(&self, env: &Json) -> Result<String, String> {
        let body = env.get("body").ok_or("envelope has no body")?;
        let wid = warrant_id(body).map_err(|e| e.to_string())?;
        let text = dumps_pretty_sorted(env) + "\n";
        fs::write(self.records.join(format!("{wid}.json")), text).map_err(|e| e.to_string())?;
        Ok(wid)
    }

    /// `get_record`: plain `json.loads` of the file's text, or None if absent.
    pub fn get_record(&self, wid: &str) -> Result<Option<Json>, String> {
        let p = self.records.join(format!("{wid}.json"));
        if !p.exists() {
            return Ok(None);
        }
        let text =
            fs::read_to_string(&p).map_err(|e| format!("cannot read {}: {e}", p.display()))?;
        parse_plain_str(&text)
            .map(Some)
            .map_err(|e| format!("{}: {e}", p.display()))
    }

    /// Record file names in the reference's order (`sorted(glob("*.json"))`).
    pub fn record_files(&self) -> Vec<String> {
        let mut out = Vec::new();
        if let Ok(rd) = fs::read_dir(&self.records) {
            for e in rd.flatten() {
                if let Some(name) = e.file_name().to_str() {
                    if name.ends_with(".json") {
                        out.push(name.to_string());
                    }
                }
            }
        }
        out.sort();
        out
    }

    /// Parse each record independently: a malformed file never aborts the
    /// verifier. Unloadable ones are returned as (WarrantID, reason class).
    pub fn all_records(&self) -> (Records, Vec<(String, String)>) {
        let mut recs = Records::default();
        let mut errors = Vec::new();
        for name in self.record_files() {
            let wid = stem(&name).to_string();
            let text = match fs::read(self.records.join(&name))
                .ok()
                .and_then(|b| String::from_utf8(b).ok())
            {
                Some(t) => t,
                None => {
                    errors.push((wid, "unreadable or invalid UTF-8".to_string()));
                    continue;
                }
            };
            let env = match parse_ijson_str(&text) {
                Ok(v) => v,
                Err(ParseError::Deep) => {
                    errors.push((wid, "malformed JSON (nesting too deep)".to_string()));
                    continue;
                }
                Err(_) => {
                    errors.push((wid, "malformed JSON".to_string()));
                    continue;
                }
            };
            if !env.get("body").is_some_and(|b| b.as_obj().is_some()) {
                errors.push((wid, "wrong top-level shape (no body object)".to_string()));
                continue;
            }
            recs.push(wid, env);
        }
        (recs, errors)
    }
}
