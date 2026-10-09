//! SPEC §8: the pinned vectors, reproduced through the public API.
//!
//! The vector files are byte copies of the repository's `examples/` (kept
//! identical by tests/rs_parity.py), so this suite runs from the published
//! crate as well as from a checkout.

use std::collections::HashMap;
use std::path::PathBuf;
use warrant_verify::hash::{blob_hash, sha256};
use warrant_verify::json::{parse_ijson, Json};
use warrant_verify::schema::validate_body;
use warrant_verify::sig::{sig_message, verify_sig, SigningKey};
use warrant_verify::ski::{eval_hash, MemCas};
use warrant_verify::store::{warrant_id, Store};
use warrant_verify::verify::{verify_store, Settlement};

const PROPOSE: &[u8] = include_bytes!("vectors/propose.warrant.json");
const REJECT: &[u8] = include_bytes!("vectors/reject.warrant.json");
const ACCEPT: &[u8] = include_bytes!("vectors/accept.warrant.json");
const SKI_ACCEPT: &[u8] = include_bytes!("vectors/ski/accept-ski.warrant.json");
const SKI_CHECK: &[u8] = include_bytes!("vectors/ski/check.json");
const SKI_NODES: [&[u8]; 5] = [
    include_bytes!(
        "vectors/ski/89bf5669baa47176938fd5d514c097c4dcdd710da8f4f62e2e0d1748bc2d2798.bin"
    ),
    include_bytes!(
        "vectors/ski/97a2eedea8d8b3419dac73f1685814e7a7ccd85f232f3d1e085fb1f1917611ad.bin"
    ),
    include_bytes!(
        "vectors/ski/bed95fbc7ccd2cf53d3562138a69a90a9c38de9f7a23d9015eef1b6638d4eb1d.bin"
    ),
    include_bytes!(
        "vectors/ski/c004c81972ff1f9b517157a44bb7ee266ae74de5ea94088ce17037072896c9c1.bin"
    ),
    include_bytes!(
        "vectors/ski/d1b6a6982b4a8c4b04c83d3adbf7aba04f587891f67b5ddb81d95bcd83cb6843.bin"
    ),
];

fn scratch(tag: &str) -> PathBuf {
    let p = std::env::temp_dir().join(format!("warrant-verify-test-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&p);
    std::fs::create_dir_all(&p).unwrap();
    p
}

#[test]
fn warrant_ids_and_signatures_reproduce() {
    for (raw, want) in [
        (
            PROPOSE,
            "00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1",
        ),
        (
            REJECT,
            "5f5d4035a4ae04a3eec255105eee7dda7c98daaf9962c92cbbbad38ac21509d8",
        ),
        (
            ACCEPT,
            "bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78",
        ),
        (
            SKI_ACCEPT,
            "8c9267bccbc217db2f3f16e6928acaf062a1c78443b2317985567b238ccfe8a0",
        ),
    ] {
        let env = parse_ijson(raw).unwrap();
        let body = env.get("body").unwrap();
        assert!(validate_body(body).is_empty(), "{want}");
        assert_eq!(warrant_id(body).unwrap(), want);
        for s in env.get("sigs").unwrap().as_arr().unwrap() {
            assert!(verify_sig(want, s.as_obj().unwrap()), "sig on {want}");
        }
    }
}

#[test]
fn a_ski_reason_in_a_v01_body_is_refused() {
    let env = parse_ijson(SKI_ACCEPT).unwrap();
    let mut body = env.get("body").unwrap().clone();
    body.as_obj_mut()
        .unwrap()
        .insert("warrant", Json::str("0.1"));
    assert!(validate_body(&body).iter().any(|m| m.contains("reserved")));
}

#[test]
fn the_ski_check_reruns_to_s_in_20_atp() {
    assert_eq!(
        blob_hash(SKI_CHECK),
        "0c30960435e9c9302a6a1538682e5864f2a754475369979bd3d635543976b2ad"
    );
    let doc = parse_ijson(SKI_CHECK).unwrap();
    let term: [u8; 32] = warrant_verify::hash::fromhex(doc.get("term").unwrap().as_str().unwrap())
        .unwrap()
        .try_into()
        .unwrap();
    let mut cas = MemCas(HashMap::new());
    for n in SKI_NODES {
        cas.0.insert(sha256(n), n.to_vec());
    }
    let atp = doc.get("atp").unwrap().as_int().unwrap() as u64;
    let (result, spent) = eval_hash(&term, atp, &mut cas).unwrap();
    assert_eq!(
        warrant_verify::hash::encode_hex(&result),
        "887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6"
    );
    assert_eq!(spent, 20);
}

#[test]
fn the_signed_message_is_domain_separated() {
    let wid = "00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1";
    let msg = sig_message(wid).unwrap();
    assert_eq!(&msg[..15], b"warrant-sig-v1:");
    assert_eq!(msg.len(), 47);
    assert!(sig_message("00").is_err());
}

#[test]
fn a_stored_vector_chain_verifies_and_a_tampered_one_does_not() {
    let dir = scratch("chain");
    let store = Store::new(dir.join("s"));
    store.init().unwrap();
    for (raw, wid) in [
        (
            PROPOSE,
            "00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1",
        ),
        (
            REJECT,
            "5f5d4035a4ae04a3eec255105eee7dda7c98daaf9962c92cbbbad38ac21509d8",
        ),
        (
            ACCEPT,
            "bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78",
        ),
    ] {
        std::fs::write(store.records.join(format!("{wid}.json")), raw).unwrap();
    }
    let base = verify_store(&store, true, None);
    assert_eq!((base.records, base.errors), (3, 0));
    // Settlement grade with no trust config: nothing is adopted, nothing fails.
    let settled = verify_store(&store, true, Some(&Settlement::default()));
    assert_eq!(settled.errors, 0);
    assert!(settled
        .findings
        .iter()
        .any(|f| f.message == "unadopted root"));
    // One changed byte of meaning: the record no longer is what its name says.
    let p = store
        .records
        .join("00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1.json");
    let text = std::fs::read_to_string(&p)
        .unwrap()
        .replace("1751673600", "1751673601");
    std::fs::write(&p, text).unwrap();
    assert!(verify_store(&store, true, None).errors >= 1);
    let _ = std::fs::remove_dir_all(dir);
}

#[test]
fn signing_round_trips_through_verification() {
    let key = SigningKey::from_seed([7u8; 32]);
    let wid = "5f5d4035a4ae04a3eec255105eee7dda7c98daaf9962c92cbbbad38ac21509d8";
    let entry = key.sign_entry(wid, "someone@example");
    assert!(verify_sig(wid, entry.as_obj().unwrap()));
    let other = "bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78";
    assert!(!verify_sig(other, entry.as_obj().unwrap()));
}
