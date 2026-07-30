#!/usr/bin/env python3
"""Generate and check `examples/signature-vectors.json` — the SPEC §8.5 battery
that pins the `warrant-sig-v1` signature construction.

WHAT THIS PINS, AND WHY IT IS NOT THE §8 TABLE
----------------------------------------------
SPEC §8 pins WarrantIDs: what a body hashes to. It says nothing about the bytes
a key actually signs, because until 2026-07-31 there was nothing to say — the
message WAS the WarrantID, and an implementation that got the identity right got
the signature message right for free.

That is no longer true. §5 now signs `"warrant-sig-v1:" || WarrantID_raw`, and
every way of getting that wrong produces a verifier that disagrees with the
other two while every WarrantID still matches. So the message itself is pinned
here, byte-for-byte, alongside signatures that MUST verify and signatures that
MUST NOT — including the exact mistakes a re-implementer makes:

  * the pre-v1 construction (the bare WarrantID) — the migration case;
  * the separator and the digest concatenated in the wrong order;
  * the separator followed by the WarrantID's ASCII HEX rather than its bytes;
  * the separator without its trailing colon;
  * and the one that motivated the whole change: a signature made in an
    UNRELATED protocol over a bare 32-byte SHA-256 digest, which a pre-0.6.0
    Warrant verifier accepted as a valid Warrant signature for the record whose
    WarrantID equals that digest (DEC-001 §3).

This file is the ancestor of `tools/domain_separation_prototype.py`, which was
the DRAFT that made DEC-001 decidable. The prototype cross-verified both rules
because neither was in force. One is now, so the vectors changed shape: they no
longer compare two candidate rules, they pin the adopted one.

All three implementations read `examples/signature-vectors.json` from their
`conformance` command. A vector file only one implementation reads is a coverage
claim that does not cover.

USAGE
    python3 tools/signature_vectors.py            # check the committed vectors
    python3 tools/signature_vectors.py --emit     # regenerate them
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "signature-vectors.json"
TAG = "warrant.signature-vectors@v0"

spec = importlib.util.spec_from_file_location("warrant_impl", ROOT / "impl" / "warrant.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

# SPEC §8 demo seed and public key. Deterministic Ed25519 (RFC 8032) means every
# signature below is reproducible by anyone, from the spec, with no secret.
DEMO_SEED = b"warrant-demo-seed-000000000000000"[:32]
DEMO_PUB = "5e06999f4dd20f375c9292e39f722a77a67a5c5cf8a5fd74bbb35f99dc4a8cc5"

VECTOR_FILES = ("propose.warrant.json", "reject.warrant.json",
                "accept.warrant.json", "ski/accept-ski.warrant.json")


def build():
    sk = Ed25519PrivateKey.from_private_bytes(DEMO_SEED)
    assert W.pubkey_hex(sk) == DEMO_PUB, "demo key mismatch"

    messages, accept, reject = [], [], []
    for name in VECTOR_FILES:
        env = json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))
        wid = W.warrant_id(env["body"])
        raw = bytes.fromhex(wid)
        msg = W.sig_message(wid)
        messages.append({
            "why": f"examples/{name}",
            "warrant_id": wid,
            "message_hex": msg.hex(),
        })
        stored = next(s for s in env["sigs"] if s["actor"] == env["body"]["actor"]["id"])
        # Ed25519 is deterministic, so the committed signature MUST be exactly
        # what signing the pinned message produces. If it is not, either the
        # envelope or this file is stale and the battery is meaningless.
        assert stored["sig"] == sk.sign(msg).hex(), f"{name}: committed sig is stale"
        accept.append({
            "why": f"examples/{name}: the committed signature by {stored['actor']}",
            "warrant_id": wid,
            "key": stored["key"],
            "sig": stored["sig"],
        })
        reject.append({
            "why": f"examples/{name}: pre-v1 construction (signed the bare WarrantID)",
            "warrant_id": wid,
            "key": DEMO_PUB,
            "sig": sk.sign(raw).hex(),
        })

    # One WarrantID carries the re-implementer's mistakes, so the battery does
    # not depend on which vector a reader happens to look at.
    wid = messages[2]["warrant_id"]            # the §8 accept vector
    raw = bytes.fromhex(wid)
    for why, message in (
        ("separator and digest concatenated in the WRONG ORDER",
         raw + W.SIG_DOMAIN),
        ("separator followed by the WarrantID's ASCII HEX, not its 32 bytes",
         W.SIG_DOMAIN + wid.encode()),
        ("separator without its trailing colon",
         b"warrant-sig-v1" + raw),
        ("separator only, no WarrantID", W.SIG_DOMAIN),
        ("a v2 separator that does not exist yet", b"warrant-sig-v2:" + raw),
    ):
        reject.append({"why": why, "warrant_id": wid, "key": DEMO_PUB,
                       "sig": sk.sign(message).hex()})

    # DEC-001 §3, the hazard this change exists to close. The signer intended to
    # sign a digest in some other protocol; before 0.6.0 that signature was a
    # syntactically valid Warrant signature for the record whose WarrantID
    # equals the digest. It is not one now, and this vector is the proof.
    foreign_payload = b"a message signed under some other protocol\n"
    foreign_digest = hashlib.sha256(foreign_payload).hexdigest()
    reject.append({
        "why": ("CROSS-PROTOCOL REPLAY: a signature over the bare SHA-256 digest of "
                "unrelated content, offered as a Warrant signature for the record "
                "whose WarrantID equals that digest. A pre-0.6.0 verifier ACCEPTED "
                "this (DEC-001 §3); rejecting it is the whole point of §5's "
                "domain separator."),
        "warrant_id": foreign_digest,
        "key": DEMO_PUB,
        "sig": sk.sign(bytes.fromhex(foreign_digest)).hex(),
        "foreign_payload_utf8": foreign_payload.decode(),
    })

    return {
        "signature_vectors": TAG,
        "note": ("SPEC §8.5. `message`: an implementation MUST build exactly these "
                 "bytes for the given WarrantID. `accept`: verify_sig MUST return "
                 "true. `reject`: verify_sig MUST return false. The demo key and "
                 "seed are SPEC §8's, so every signature here is reproducible "
                 "from the spec alone."),
        "domain_separator_ascii": W.SIG_DOMAIN.decode(),
        "domain_separator_hex": W.SIG_DOMAIN.hex(),
        "construction": 'msg = "warrant-sig-v1:" || WarrantID_raw   (15 + 32 = 47 bytes)',
        "superseded_construction": "msg = WarrantID_raw   (32 bytes; pre-0.6.0, MUST NOT verify)",
        "message": messages,
        "accept": accept,
        "reject": reject,
    }


def main():
    doc = build()
    if "--emit" in sys.argv[1:]:
        OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")

    fails = []

    def chk(name, cond, detail=""):
        print(("OK   " if cond else "FAIL ") + name + ("" if cond else "  <<< " + detail))
        if not cond:
            fails.append(name)

    for m in doc["message"]:
        chk(f"[message] {m['why']}",
            W.sig_message(m["warrant_id"]).hex() == m["message_hex"])
        chk(f"[message] {m['why']}: 47 bytes, separator then digest",
            len(bytes.fromhex(m["message_hex"])) == 47
            and m["message_hex"].startswith(doc["domain_separator_hex"])
            and m["message_hex"].endswith(m["warrant_id"]))
    for a in doc["accept"]:
        chk(f"[accept] {a['why']}", W.verify_sig(a["warrant_id"], a))
    for r in doc["reject"]:
        chk(f"[reject] {r['why'][:70]}", not W.verify_sig(r["warrant_id"], r))

    # The migration claim, recomputed rather than asserted: re-signing rewrites
    # the envelope only, so the WarrantID — SHA-256 of the canonical body — is
    # unchanged. Everything that cites a record cites this number.
    for name, m in zip(VECTOR_FILES, doc["message"]):
        env = json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))
        chk(f"[identity] examples/{name}: re-signing did not move the WarrantID",
            hashlib.sha256(W.canon(env["body"])).hexdigest() == m["warrant_id"])

    if OUT.exists():
        chk("committed vectors reproduce byte-exactly",
            json.loads(OUT.read_text(encoding="utf-8")) == doc,
            "run --emit deliberately")
    else:
        chk("committed vectors exist", False, str(OUT))

    print()
    if fails:
        print(f"SIGNATURE-VECTORS: {len(fails)} FAIL(S): " + ", ".join(fails[:4]))
        return 1
    print(f"SIGNATURE-VECTORS: ALL PASS ({len(doc['message'])} messages, "
          f"{len(doc['accept'])} accept, {len(doc['reject'])} reject)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
