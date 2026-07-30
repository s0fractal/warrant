#!/usr/bin/env python3
"""DRAFT PROTOTYPE — signature domain separation. NOTHING HERE IS IN FORCE.

READ THIS FIRST
---------------
SPEC §5 says the signature is "pure Ed25519 (RFC 8032, no context, no pre-hash):
the message is the 32-byte WarrantID itself". That is what all three shipped
implementations do and what this file does NOT change. No verb, no verifier and
no test in this repository calls anything below; `impl/warrant.py`,
`impl-go/main.go` and `impl-rs` are untouched by it.

This script exists to make one open decision concrete instead of theoretical:
`proposals/DEC-001-domain-separation.md`. It computes, for the SPEC §8 demo key,
the same WarrantIDs signed BOTH ways, and cross-verifies all four combinations,
so a maintainer can look at the actual bytes before deciding.

THE PROPOSED CONSTRUCTION (option A in DEC-001)

    legacy (in force today):   msg = WarrantID_raw                    (32 bytes)
    proposed:                  msg = b"warrant-sig-v1:" || WarrantID_raw
                                                                      (47 bytes)

Still pure RFC 8032 Ed25519 over a byte string — NOT Ed25519ctx, NOT Ed25519ph.
That is deliberate: Ed25519ctx would be the more orthodox answer and is a
portability trap here, because the from-scratch Rust verifier and the Python
`cryptography` binding do not both expose it, and this project's first law is
that independent implementations agree byte-exactly. A fixed ASCII prefix is
implementable in four lines in any language that can already verify Ed25519.

WHAT THE VECTORS SHOW, AND WHY IT MATTERS FOR MIGRATION

The four cross-verifications establish that the two constructions are cleanly
disjoint: a legacy signature does not verify under the new rule and a new
signature does not verify under the legacy rule. There is no window in which a
verifier could accept both without giving up the separation entirely.

The migration fact that decides the cost: **the envelope is not hashed** (SPEC
§5), so re-signing a record does NOT change its WarrantID, its `prior` edges, or
any hash that cites it. Migration is re-signing in place, and the vectors below
demonstrate that on the real §8 accept vector.

USAGE
    python3 tools/domain_separation_prototype.py            # verify the vectors
    python3 tools/domain_separation_prototype.py --emit     # regenerate them
"""
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "draft" / "domain-separation-vectors.json"
TAG = "warrant.draft-domain-separation-vectors@v0"

# The proposed domain separator. Fixed-length ASCII, so prefix || 32-byte digest
# is unambiguous without a length field.
DOMAIN = b"warrant-sig-v1:"

# SPEC §8 demo seed and public key.
DEMO_SEED = b"warrant-demo-seed-000000000000000"[:32]
DEMO_PUB = "5e06999f4dd20f375c9292e39f722a77a67a5c5cf8a5fd74bbb35f99dc4a8cc5"

spec = importlib.util.spec_from_file_location("warrant_impl", ROOT / "impl" / "warrant.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey, Ed25519PublicKey)


def msg_legacy(wid_hex):
    """SPEC §5 as it stands: the message is the raw WarrantID."""
    return bytes.fromhex(wid_hex)


def msg_proposed(wid_hex):
    """DEC-001 option A: a fixed context prefix ahead of the same digest."""
    return DOMAIN + bytes.fromhex(wid_hex)


def sign(sk, message):
    return sk.sign(message).hex()


def verifies(pub_hex, sig_hex, message):
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(
            bytes.fromhex(sig_hex), message)
        return True
    except Exception:
        return False


def build():
    sk = Ed25519PrivateKey.from_private_bytes(DEMO_SEED)
    pub = W.pubkey_hex(sk)
    assert pub == DEMO_PUB, f"demo key mismatch: {pub}"

    cases = []
    for name in ("propose", "reject", "accept"):
        env = json.loads((ROOT / "examples" / f"{name}.warrant.json").read_text())
        body = env["body"]
        wid = W.warrant_id(body)
        stored = next(s for s in env["sigs"] if s["actor"] == body["actor"]["id"])
        legacy, proposed = msg_legacy(wid), msg_proposed(wid)
        sig_legacy = sign(sk, legacy)
        sig_proposed = sign(sk, proposed)
        cases.append({
            "vector": f"examples/{name}.warrant.json",
            "warrant_id": wid,
            "key": pub,
            "message_legacy_hex": legacy.hex(),
            "message_proposed_hex": proposed.hex(),
            "sig_legacy": sig_legacy,
            "sig_proposed": sig_proposed,
            # Ed25519 is deterministic (RFC 8032), so the signature recomputed
            # here MUST be byte-identical to the one committed in examples/.
            # If it is not, this whole comparison is meaningless.
            "sig_legacy_equals_stored_signature": sig_legacy == stored["sig"],
            "cross": {
                "legacy_sig_under_legacy_rule": verifies(pub, sig_legacy, legacy),
                "legacy_sig_under_proposed_rule": verifies(pub, sig_legacy, proposed),
                "proposed_sig_under_legacy_rule": verifies(pub, sig_proposed, legacy),
                "proposed_sig_under_proposed_rule": verifies(pub, sig_proposed, proposed),
            },
            # Migration: re-signing changes the envelope only. The WarrantID is
            # SHA-256 of the canonical BODY, so it is unchanged by construction —
            # recomputed here rather than asserted.
            "warrant_id_after_resign": hashlib.sha256(W.canon(body)).hexdigest(),
        })

    # A cross-protocol replay illustration, which is the whole point of the
    # change: any other protocol whose signed message happens to be a bare
    # 32-byte SHA-256 digest produces signatures that a Warrant verifier accepts.
    # Here "the other protocol" is literally SHA-256 of a text file.
    foreign_payload = b"a message signed under some other protocol\n"
    foreign_digest = hashlib.sha256(foreign_payload).hexdigest()
    foreign_sig = sign(sk, bytes.fromhex(foreign_digest))
    replay = {
        "explanation": ("The signer intended to sign a digest in an unrelated "
                        "protocol. Under SPEC §5 as written, that signature is a "
                        "valid Warrant signature for the record whose WarrantID "
                        "equals that digest. No such record exists today, and "
                        "finding a body that canonicalizes to a CHOSEN digest is "
                        "a second-preimage problem — this is a cross-protocol "
                        "hazard, not a forgery recipe."),
        "foreign_payload_utf8": foreign_payload.decode(),
        "foreign_digest": foreign_digest,
        "foreign_sig": foreign_sig,
        "accepted_as_warrant_signature_today": verifies(
            DEMO_PUB, foreign_sig, msg_legacy(foreign_digest)),
        "accepted_as_warrant_signature_under_proposal": verifies(
            DEMO_PUB, foreign_sig, msg_proposed(foreign_digest)),
    }

    return {
        "draft_vectors": TAG,
        "status": ("DRAFT. NOT ADOPTED, NOT IMPLEMENTED. SPEC §5 is unchanged and "
                   "all three implementations sign and verify the LEGACY message. "
                   "See proposals/DEC-001-domain-separation.md."),
        "domain_separator_ascii": DOMAIN.decode(),
        "domain_separator_hex": DOMAIN.hex(),
        "construction_legacy": "msg = WarrantID_raw (32 bytes)",
        "construction_proposed": 'msg = b"warrant-sig-v1:" || WarrantID_raw (47 bytes)',
        "cases": cases,
        "cross_protocol_replay_illustration": replay,
    }


def main():
    doc = build()
    if "--emit" in sys.argv[1:]:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")

    fails = []

    def chk(name, cond, detail=""):
        print(("OK   " if cond else "FAIL ") + name + ("" if cond else "  <<< " + detail))
        if not cond:
            fails.append(name)

    for c in doc["cases"]:
        x = c["cross"]
        chk(f"[{c['vector']}] recomputed legacy signature == the one in examples/",
            c["sig_legacy_equals_stored_signature"],
            "Ed25519 is deterministic; a mismatch invalidates the comparison")
        chk(f"[{c['vector']}] legacy sig verifies under the legacy rule",
            x["legacy_sig_under_legacy_rule"])
        chk(f"[{c['vector']}] legacy sig REJECTED under the proposed rule",
            not x["legacy_sig_under_proposed_rule"])
        chk(f"[{c['vector']}] proposed sig REJECTED under the legacy rule",
            not x["proposed_sig_under_legacy_rule"])
        chk(f"[{c['vector']}] proposed sig verifies under the proposed rule",
            x["proposed_sig_under_proposed_rule"])
        chk(f"[{c['vector']}] re-signing leaves the WarrantID unchanged (migration cost)",
            c["warrant_id_after_resign"] == c["warrant_id"])
        chk(f"[{c['vector']}] the two messages differ",
            c["message_legacy_hex"] != c["message_proposed_hex"])

    r = doc["cross_protocol_replay_illustration"]
    chk("[replay] a foreign 32-byte-digest signature IS accepted today",
        r["accepted_as_warrant_signature_today"])
    chk("[replay] and is NOT accepted under the proposal",
        not r["accepted_as_warrant_signature_under_proposal"])

    if OUT.exists():
        committed = json.loads(OUT.read_text(encoding="utf-8"))
        chk("committed vectors reproduce byte-exactly", committed == doc,
            "run --emit deliberately; this is a draft artifact, not test churn")
    else:
        chk("committed vectors exist", False, str(OUT))

    print()
    if fails:
        print(f"DOMAIN-SEPARATION (DRAFT): {len(fails)} FAIL(S): " + ", ".join(fails[:4]))
        return 1
    print("DOMAIN-SEPARATION (DRAFT): ALL PASS — and nothing here is in force. "
          "SPEC §5 is unchanged; the decision is open in "
          "proposals/DEC-001-domain-separation.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
