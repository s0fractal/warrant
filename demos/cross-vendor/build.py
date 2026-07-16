#!/usr/bin/env python3
"""Build the cross-vendor witnessing demo pack — deterministically, via the real
library.

The seam no hosted platform can serve: two agents at DIFFERENT vendors, sharing
NO identity provider, jointly settle an outcome. Each vendor co-signs the same
decision. A third party (a dispute handler, an auditor) verifies that BOTH
consented — using its OWN keyring, trusting neither vendor's server.

  accept  "cross-vendor settlement of order ORD-7788"
    under  a 2-of-2 threshold policy {vendor-a, vendor-b}
    sigs   vendor-a AND vendor-b, over the same WarrantID

Microsoft won't verify a chain of Google's agents for free; a hosted log is one
party's word. A co-signed warrant is verifiable from bytes by anyone, because the
verifier supplies the keyring — as `trust.json` here does.
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPL = HERE.parent.parent / "impl"
sys.path.insert(0, str(IMPL))
import warrant as W  # noqa: E402

PACK = HERE / "pack"
STORE = PACK / ".warrants"

# Deterministic vendor identities (fixed Ed25519 seeds -> stable hashes).
VENDOR_A = ("agent@vendor-a", "1a" * 32)
VENDOR_B = ("auditor@vendor-b", "2b" * 32)
TS = 1708300800

SETTLEMENT = (
    '{"settles":"ORD-7788",'
    '"delegated_from":"agent@vendor-a",'
    '"performed_by":"auditor@vendor-b",'
    '"outcome":"delivery confirmed, $120 released",'
    '"both_parties_consent":true}'
)


def keyfile(seed, name):
    p = PACK / name
    p.write_text(seed + "\n")
    return str(p)


def main():
    if PACK.exists():
        shutil.rmtree(PACK)
    store = W.Store(str(STORE))
    store.init()

    a_key = keyfile(VENDOR_A[1], "_a.key")
    b_key = keyfile(VENDOR_B[1], "_b.key")
    a_pub = W.pubkey_hex(W.load_key(a_key))
    b_pub = W.pubkey_hex(W.load_key(b_key))

    subject = store.put_blob(SETTLEMENT.encode())

    # A 2-of-2 witness policy over the two vendors, pinned by hash.
    policy = store.put_blob(W.canon({
        "warrant_policy": "0.3",
        "threshold": {"min_sigs": 2, "actors": [VENDOR_A[0], VENDOR_B[0]]},
    }))

    # One decision, co-signed by BOTH vendors over the same WarrantID.
    body = {
        "warrant": "0.2",
        "decision": "accept",
        "subject": {"hash": subject, "note": "cross-vendor settlement ORD-7788"},
        "under": [policy],
        "because": [{"kind": "prose",
                     "text": "both vendors confirm delivery and release of funds"}],
        "evidence": [],
        "actor": {"id": VENDOR_A[0]},
        "prior": [],
        "ts": TS,
    }
    errs = W.validate_body(body)
    assert not errs, errs
    env = {"body": body, "sigs": [
        W.sign_envelope(body, VENDOR_A[0], a_key),
        W.sign_envelope(body, VENDOR_B[0], b_key),
    ]}
    wid = store.put_record(env)

    # trust.json — the VERIFIER's keyring. It names who each vendor is; the
    # record is the genesis (settlement) root. Neither vendor supplied this.
    (PACK / "trust.json").write_text(json.dumps({
        "genesis_roots": [wid],
        "actors": {VENDOR_A[0]: [a_pub], VENDOR_B[0]: [b_pub]},
    }, indent=2, sort_keys=True) + "\n")

    # Drop the private seeds; a verifier needs only the public keyring.
    (PACK / "_a.key").unlink()
    (PACK / "_b.key").unlink()

    (PACK / "manifest.json").write_text(json.dumps({
        "evidence_pack": "0",
        "title": "Cross-vendor settlement, 2-of-2 witnessed",
        "produced_by": "warrant demos/cross-vendor/build.py",
        "root": wid,
        "decision": wid,
        "records": [wid],
        "witnesses": [VENDOR_A[0], VENDOR_B[0]],
        "threshold": "2-of-2",
        "expected_verification": {"errors": 0},
        "how_to_verify":
            "warrant --store .warrants verify --settlement --trust-config trust.json",
    }, indent=2, sort_keys=True) + "\n")

    print("cross-vendor pack built")
    print("  settlement wid :", wid)
    print("  witnesses      :", VENDOR_A[0], "+", VENDOR_B[0], "(2-of-2)")


if __name__ == "__main__":
    main()
