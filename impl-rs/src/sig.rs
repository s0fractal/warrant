//! SPEC §5: keys, the signed message, and signature checks.

use crate::ed25519;
use crate::hash::{encode_hex, fromhex};
use crate::json::{Json, Obj};

/// SPEC §5 signature domain separation (`warrant-sig-v1`, DEC-001):
/// `msg = "warrant-sig-v1:" || WarrantID_raw`, 15 + 32 = 47 bytes. Pure RFC 8032
/// Ed25519 over a byte string, not Ed25519ctx.
pub const SIG_DOMAIN: &[u8] = b"warrant-sig-v1:";

/// The §6 report string for a signature made under the pre-0.6.0 bare-WarrantID
/// construction. Byte-identical in all implementations (SPEC §5).
pub const LEGACY_SIG_MESSAGE: &str = "signature does not verify (excluded): LEGACY pre-v1 signature construction (signed the bare 32-byte WarrantID; SPEC 5 requires \"warrant-sig-v1:\" || WarrantID). Re-sign with: warrant resign --key <keyfile>";

/// The exact bytes a Warrant signature covers, or an error when `wid` is not a
/// 32-byte hex digest (the reference raises ValueError there).
pub fn sig_message(wid: &str) -> Result<Vec<u8>, String> {
    let raw =
        fromhex(wid).ok_or_else(|| "non-hexadecimal number found in fromhex() arg".to_string())?;
    if raw.len() != 32 {
        return Err(format!("WarrantID must be 32 bytes, got {}", raw.len()));
    }
    let mut msg = SIG_DOMAIN.to_vec();
    msg.extend_from_slice(&raw);
    Ok(msg)
}

/// SPEC §5: small-order and non-canonically-encoded Ed25519 public keys are
/// rejected. Byte- and integer-only, so every implementation agrees.
pub fn weak_ed25519_pubkey(raw: &[u8]) -> bool {
    if raw.len() != 32 {
        return true;
    }
    const SMALL_ORDER: [&str; 10] = [
        "0100000000000000000000000000000000000000000000000000000000000000",
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
        "0000000000000000000000000000000000000000000000000000000000000080",
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
        "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
        "0000000000000000000000000000000000000000000000000000000000000000",
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
        "0100000000000000000000000000000000000000000000000000000000000080",
        "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    ];
    if SMALL_ORDER.contains(&encode_hex(raw).as_str()) {
        return true;
    }
    // non-canonical y: drop the sign bit, compare little-endian y with p = 2^255-19
    let mut be = [0u8; 32];
    for i in 0..32 {
        be[i] = raw[31 - i];
    }
    be[0] &= 0x7f;
    let mut p = [0xffu8; 32];
    p[0] = 0x7f;
    p[31] = 0xed;
    be >= p
}

/// Key and signature bytes as the reference reads them (`bytes.fromhex` on
/// whatever strings are there), screened for weak keys once.
fn sig_parts(sig: &Obj) -> Option<([u8; 32], Vec<u8>)> {
    let key = fromhex(sig.get("key")?.as_str()?)?;
    if weak_ed25519_pubkey(&key) {
        return None;
    }
    let sigb = fromhex(sig.get("sig")?.as_str()?)?;
    let mut pk = [0u8; 32];
    pk.copy_from_slice(&key);
    Some((pk, sigb))
}

fn ed_verify(pk: &[u8; 32], sig: &[u8], msg: &[u8]) -> bool {
    if sig.len() != 64 {
        return false;
    }
    let mut s = [0u8; 64];
    s.copy_from_slice(sig);
    ed25519::verify(pk, &s, msg)
}

/// A signature entry verifies over `wid` under `warrant-sig-v1`. Total: any
/// malformed input is simply "does not verify".
pub fn verify_sig(wid: &str, sig: &Obj) -> bool {
    let Some((pk, sg)) = sig_parts(sig) else {
        return false;
    };
    match sig_message(wid) {
        Ok(msg) => ed_verify(&pk, &sg, &msg),
        Err(_) => false,
    }
}

/// True if `sig` is valid over the BARE 32-byte WarrantID — the construction
/// SPEC §5 replaced. DIAGNOSIS ONLY; no caller treats it as acceptance.
pub fn legacy_sig(wid: &str, sig: &Obj) -> bool {
    let Some((pk, sg)) = sig_parts(sig) else {
        return false;
    };
    match fromhex(wid) {
        Some(raw) => ed_verify(&pk, &sg, &raw),
        None => false,
    }
}

/// A signing key: the 32-byte RFC 8032 seed, stored as hex text.
pub struct SigningKey {
    seed: [u8; 32],
}

impl SigningKey {
    pub fn from_seed(seed: [u8; 32]) -> Self {
        SigningKey { seed }
    }
    /// `load_key`: the file holds a 32-byte hex seed (surrounding whitespace ok).
    pub fn load(path: &str) -> Result<Self, String> {
        let text = std::fs::read_to_string(path)
            .map_err(|e| format!("cannot read key file {path}: {e}"))?;
        let seed = fromhex(text.trim()).ok_or("key file must contain a 32-byte hex seed")?;
        if seed.len() != 32 {
            return Err("key file must contain a 32-byte hex seed".into());
        }
        let mut s = [0u8; 32];
        s.copy_from_slice(&seed);
        Ok(SigningKey { seed: s })
    }
    pub fn public_hex(&self) -> String {
        encode_hex(&ed25519::public_key(&self.seed))
    }
    pub fn sign(&self, msg: &[u8]) -> [u8; 64] {
        ed25519::sign(&self.seed, msg)
    }
    /// `{actor, key, sig}` over `wid` under warrant-sig-v1.
    pub fn sign_entry(&self, wid: &str, actor: &str) -> Json {
        let msg = sig_message(wid).expect("a computed WarrantID is 32 bytes");
        let mut o = Obj::new();
        o.insert("actor", Json::str(actor));
        o.insert("key", Json::Str(self.public_hex()));
        o.insert("sig", Json::Str(encode_hex(&self.sign(&msg))));
        Json::Object(o)
    }
}

/// 32 bytes from the operating system's CSPRNG.
pub fn os_random_32() -> Result<[u8; 32], String> {
    use std::io::Read;
    let mut f =
        std::fs::File::open("/dev/urandom").map_err(|e| format!("no OS randomness: {e}"))?;
    let mut b = [0u8; 32];
    f.read_exact(&mut b)
        .map_err(|e| format!("no OS randomness: {e}"))?;
    Ok(b)
}
