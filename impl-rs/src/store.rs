//! The plain-file store: `<root>/blobs/<sha256>` and `<root>/records/<WarrantID>.json`.

use crate::hash::{blob_hash, is_hex64};
use crate::json::{canon, dumps_pretty_sorted, parse_ijson_str, parse_plain_str, Json, ParseError};
use std::collections::{BTreeMap, HashMap};
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
    memory: Option<BTreeMap<String, Vec<u8>>>,
}

impl Store {
    pub fn new(root: impl AsRef<Path>) -> Self {
        let root = root.as_ref().to_path_buf();
        Store {
            blobs: root.join("blobs"),
            records: root.join("records"),
            root,
            memory: None,
        }
    }

    /// Read-only virtual store. Paths are relative to the store root; callers
    /// supply file bytes unchanged, including malformed record bytes.
    pub fn from_memory(files: BTreeMap<String, Vec<u8>>) -> Self {
        let mut store = Self::new("");
        store.memory = Some(files);
        store
    }

    pub fn root_file_exists(&self, name: &str) -> bool {
        match &self.memory {
            Some(files) => files.contains_key(name),
            None => self.root.join(name).exists(),
        }
    }

    pub fn root_file_bytes(&self, name: &str) -> Option<Vec<u8>> {
        match &self.memory {
            Some(files) => files.get(name).cloned(),
            None => fs::read(self.root.join(name)).ok(),
        }
    }

    pub fn init(&self) -> std::io::Result<()> {
        self.require_writable()?;
        fs::create_dir_all(&self.blobs)?;
        fs::create_dir_all(&self.records)
    }

    pub fn is_initialized(&self) -> bool {
        self.memory.is_some() || self.records.is_dir()
    }

    pub fn put_blob(&self, data: &[u8]) -> std::io::Result<String> {
        self.require_writable()?;
        let h = blob_hash(data);
        let p = self.blobs.join(&h);
        if !p.exists() {
            fs::write(&p, data)?;
        }
        Ok(h)
    }

    /// A blob exists only if `h` is a hex64 name AND names a regular file.
    pub fn has_blob(&self, h: &str) -> bool {
        is_hex64(h)
            && match &self.memory {
                Some(files) => files.contains_key(&format!("blobs/{h}")),
                None => self.blobs.join(h).is_file(),
            }
    }

    /// Do the bytes at `blobs/<h>` actually hash to `<h>`?
    pub fn blob_intact(&self, h: &str) -> bool {
        self.blob_bytes(h).is_some_and(|b| blob_hash(&b) == h)
    }

    pub fn blob_bytes(&self, h: &str) -> Option<Vec<u8>> {
        match &self.memory {
            Some(files) => files.get(&format!("blobs/{h}")).cloned(),
            None => fs::read(self.blobs.join(h)).ok(),
        }
    }

    /// Write an envelope with the store's one writer; returns its WarrantID.
    pub fn put_record(&self, env: &Json) -> Result<String, String> {
        self.require_writable().map_err(|e| e.to_string())?;
        let body = env.get("body").ok_or("envelope has no body")?;
        let wid = warrant_id(body).map_err(|e| e.to_string())?;
        let text = dumps_pretty_sorted(env) + "\n";
        fs::write(self.records.join(format!("{wid}.json")), text).map_err(|e| e.to_string())?;
        Ok(wid)
    }

    /// `get_record`: plain `json.loads` of the file's text, or None if absent.
    pub fn get_record(&self, wid: &str) -> Result<Option<Json>, String> {
        if let Some(files) = &self.memory {
            return files
                .get(&format!("records/{wid}.json"))
                .map(|raw| {
                    let text = std::str::from_utf8(raw).map_err(|e| e.to_string())?;
                    parse_plain_str(text).map_err(|e| e.to_string())
                })
                .transpose();
        }
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
        if let Some(files) = &self.memory {
            return files
                .keys()
                .filter_map(|p| p.strip_prefix("records/"))
                .filter(|p| !p.contains('/') && p.ends_with(".json"))
                .map(String::from)
                .collect();
        }
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
            let text = match self
                .root_file_bytes(&format!("records/{name}"))
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

    fn require_writable(&self) -> std::io::Result<()> {
        if self.memory.is_some() {
            Err(std::io::Error::new(
                std::io::ErrorKind::Unsupported,
                "in-memory stores are read-only",
            ))
        } else {
            Ok(())
        }
    }
}
