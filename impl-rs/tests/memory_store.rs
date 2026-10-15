//! File-vs-memory parity: the browser adapter cannot supply a second verifier.
use std::{collections::BTreeMap, fs};
use warrant_verify::{
    hash::blob_hash,
    json::{dumps_compact, parse_ijson},
    store::{warrant_id, Store},
    verify::{verify_report, verify_report_with_trust},
};

fn specimen() -> BTreeMap<String, Vec<u8>> {
    let mut files = BTreeMap::new();
    let raw = include_bytes!("vectors/ski/accept-ski.warrant.json");
    let env = parse_ijson(raw).unwrap();
    let id = warrant_id(env.get("body").unwrap()).unwrap();
    files.insert(format!("records/{id}.json"), raw.to_vec());
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/vectors/ski");
    for entry in fs::read_dir(dir).unwrap().flatten() {
        let p = entry.path();
        if p.extension().is_some_and(|s| s == "bin") || p.file_name().unwrap() == "check.json" {
            let bytes = fs::read(p).unwrap();
            files.insert(format!("blobs/{}", blob_hash(&bytes)), bytes);
        }
    }
    files
}

#[test]
fn raw_bytes_and_refusals_match_file_store() {
    let original = specimen();
    for variant in 0..5 {
        let mut files = original.clone();
        match variant {
            1 => {
                files.insert("records/malformed.json".into(), b"{broken".to_vec());
            }
            2 => {
                let p = files
                    .keys()
                    .find(|p| p.starts_with("records/"))
                    .unwrap()
                    .clone();
                files.insert(p, vec![0xff]);
            }
            3 => {
                let p = files
                    .keys()
                    .find(|p| p.starts_with("blobs/"))
                    .unwrap()
                    .clone();
                files.insert(p, b"changed".to_vec());
            }
            4 => {
                files.insert("genesis.json".into(), b"{broken".to_vec());
            }
            _ => {}
        }
        let path = std::env::temp_dir().join(format!(
            "warrant-memory-parity-{}-{variant}",
            std::process::id()
        ));
        let disk = Store::new(&path);
        disk.init().unwrap();
        for (p, bytes) in &files {
            fs::write(path.join(p), bytes).unwrap();
        }
        let memory = Store::from_memory(files);
        assert_eq!(
            dumps_compact(&verify_report(&disk, None)),
            dumps_compact(&verify_report(&memory, None)),
            "variant {variant}"
        );
        assert!(memory.put_blob(b"x").is_err());
        assert!(memory.init().is_err());
        fs::remove_dir_all(path).unwrap();
    }
}

#[test]
fn explicit_trust_is_separate_and_invalid_config_refuses() {
    let memory = Store::from_memory(specimen());
    let report = verify_report_with_trust(&memory, Some(Err("invalid".into())));
    assert_eq!(report.get("grade").unwrap().as_str(), Some("settlement"));
    assert_eq!(report.get("errors").unwrap().as_int(), Some(1));
    assert_eq!(report.get("warnings").unwrap().as_int(), Some(0));
}
