#!/usr/bin/env python3
"""Express a warrant decision as an in-toto Statement v1, and check the binding.

WHY
---
This format is an island. The provenance world already runs on in-toto
Statements, SLSA predicates, Sigstore and Rekor, and a reader who has that
tooling cannot do anything with a warrant record. That makes the stack a rival to
a habit instead of a layer on one -- and the layer is the honest position: in-toto
says what happened to an artifact, a warrant says who was allowed to decide and
on which re-runnable reasons.

A bridge is also the one strategic move here that needs nobody's permission. A
predicateType is published, not negotiated; a converter is code, not a
relationship.

WHAT IT DOES NOT DO
-------------------
It does not make a warrant an SLSA provenance. `envelope` now wraps a Statement
in DSSE and signs it, but that is still not adoption: pushing to a transparency
log is a separate act with separate trust, and nothing here does it.

A DSSE signature verified against the key named inside the same envelope proves
integrity and nothing else -- whoever wrote the envelope chose that key. Pass
`--expect-key` to make a statement about authority; without it, `verify-envelope`
says integrity only, in those words.

Conversion is not verification. `check` exists because a converter whose output
nobody can test is a claim: it recomputes every digest from the store rather than
trusting the Statement it was handed.

NAMESPACE, HONESTLY
-------------------
The predicateType is under `github.com/s0fractal/warrant`, a URI this project
actually controls. An external audit proposed `warrant.dev/decision/v0`; that
domain is not owned here, and minting a TypeURI under someone else's namespace is
a false claim about who defines the type.

USAGE
    python3 tools/intoto.py wrap <WarrantID>            # Statement on stdout
    python3 tools/intoto.py check <statement.json>      # binding verified?
    python3 tools/intoto.py envelope <WarrantID> --key me.key    # signed DSSE
    python3 tools/intoto.py verify-envelope <env.json> [--expect-key HEX]
    python3 tools/intoto.py roundtrip <WarrantID> --key me.key   # + loss report
    python3 tools/intoto.py selftest
"""
import argparse
import base64
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W                                          # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PublicKey,
)

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://github.com/s0fractal/warrant/decision/v0"


def _descriptor(digest_hex, name=None, media=None):
    """A ResourceDescriptor. `digest` alone satisfies the one-of rule."""
    d = {"digest": {"sha256": digest_hex}}
    if name:
        d["name"] = name
    if media:
        d["mediaType"] = media
    return d


def wrap(store, wid):
    """Statement whose subject is what the decision was ABOUT.

    in-toto matches subjects purely by digest, so the mapping that preserves
    meaning is: warrant `subject.hash` -> Statement `subject`. Everything that
    makes the decision checkable -- the policy bytes in force, the evidence, the
    reasons, the actor, the chain -- goes in the predicate as descriptors, so a
    consumer with only the Statement can still resolve and re-run them.
    """
    env = store.get_record(wid)
    if env is None:
        sys.exit(f"{wid[:12]}: not in store")
    body = env["body"]
    subj = body["subject"]["hash"]
    note = body["subject"].get("note")

    # A supersede/accept subject may be a WarrantID rather than a blob. Say which,
    # because "digest of a file" and "digest of a decision" are different claims
    # and a consumer matching by digest alone cannot tell them apart.
    kind = "warrant-record" if (not store.has_blob(subj) and subj in
                                store.all_records()) else "blob"

    reasons = []
    for r in body["because"]:
        if r["kind"] == "prose":
            reasons.append({"kind": "prose", "text": r["text"]})
        else:
            reasons.append({k: v for k, v in r.items() if k != "text"})

    return {
        "_type": STATEMENT_TYPE,
        "subject": [_descriptor(subj, name=note or f"warrant:subject:{kind}")],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "warrantId": wid,
            "warrantVersion": body["warrant"],
            "decision": body["decision"],
            "subjectKind": kind,
            "actor": body["actor"]["id"],
            "timestamp": body["ts"],
            "under": [_descriptor(h, name="policy",
                                  media="application/octet-stream")
                      for h in body["under"]],
            "evidence": [_descriptor(h, name="evidence") for h in body["evidence"]],
            "prior": [_descriptor(p, name="prior-warrant") for p in body["prior"]],
            "because": reasons,
            "signatures": [{"actor": s.get("actor"), "keyid": s.get("key")}
                           for s in env["sigs"]],
            "verifyWith": {
                "tool": "warrant-verify",
                "command": "warrant --store <store> verify --settlement "
                           "--trust-config <trust.json>",
                "note": "This Statement is a projection. The record it names is "
                        "the artefact that verifies; re-running `because` checks "
                        "requires the store's blobs.",
            },
        },
    }


def check(store, statement):
    """Recompute everything the Statement asserts against the store.

    Deliberately not a schema check. A Statement can be perfectly well-formed and
    describe a warrant that does not exist, or name digests that do not match the
    record it claims -- and that failure is exactly what a bridge must not pass
    through silently.
    """
    errs = []
    if statement.get("_type") != STATEMENT_TYPE:
        errs.append(f"_type is {statement.get('_type')!r}, expected {STATEMENT_TYPE!r}")
    if statement.get("predicateType") != PREDICATE_TYPE:
        errs.append(f"predicateType is {statement.get('predicateType')!r}")
    subs = statement.get("subject")
    if not isinstance(subs, list) or not subs:
        errs.append("subject must be a non-empty array")
    else:
        for s in subs:
            if not (isinstance(s, dict) and isinstance(s.get("digest"), dict)):
                errs.append("every subject element MUST have digest set")

    p = statement.get("predicate") or {}
    wid = p.get("warrantId")
    if not (isinstance(wid, str) and W.HEX64.match(wid)):
        errs.append("predicate.warrantId must be a hex64 WarrantID")
        return errs

    env = store.get_record(wid)
    if env is None:
        errs.append(f"predicate.warrantId {wid[:12]} is not in this store")
        return errs
    body = env["body"]

    # The identity claim: does the named record actually hash to the id given?
    if W.warrant_id(body) != wid:
        errs.append(f"{wid[:12]}: record does not recompute to its own id")

    # And does the Statement describe THAT record, field by field?
    if subs and subs[0].get("digest", {}).get("sha256") != body["subject"]["hash"]:
        errs.append("subject digest does not match the record's subject.hash")
    for field, key in (("under", "under"), ("evidence", "evidence"),
                       ("prior", "prior")):
        claimed = [d.get("digest", {}).get("sha256") for d in p.get(field, [])]
        if claimed != list(body[key]):
            errs.append(f"predicate.{field} does not match the record's {key}")
    for f, actual in (("decision", body["decision"]),
                      ("actor", body["actor"]["id"]),
                      ("timestamp", body["ts"]),
                      ("warrantVersion", body["warrant"])):
        if p.get(f) != actual:
            errs.append(f"predicate.{f} is {p.get(f)!r}, record says {actual!r}")
    return errs


# ---------- DSSE (a projection of a projection; still not adoption) ----------
PAYLOAD_TYPE = "application/vnd.in-toto+json"


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE Pre-Authentication Encoding: length-prefixed, so a signature cannot
    be replayed under a different payload type."""
    return (b"DSSEv1 " + str(len(payload_type)).encode() + b" "
            + payload_type.encode() + b" "
            + str(len(payload)).encode() + b" " + payload)


def canonical(statement: dict) -> bytes:
    return json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()


def envelope(store, wid: str, key_path: str) -> dict:
    payload = canonical(wrap(store, wid))
    sk = W.load_key(key_path)
    return {"payloadType": PAYLOAD_TYPE,
            "payload": base64.standard_b64encode(payload).decode(),
            "signatures": [{"keyid": W.pubkey_hex(sk),
                            "sig": base64.standard_b64encode(
                                sk.sign(pae(PAYLOAD_TYPE, payload))).decode()}]}


def verify_envelope(store, env: dict, expect_key: str | None = None) -> list:
    """Signature, then binding. Two different questions, answered separately."""
    errs = []
    if env.get("payloadType") != PAYLOAD_TYPE:
        errs.append(f"payloadType is {env.get('payloadType')!r}, not {PAYLOAD_TYPE!r}")
    try:
        payload = base64.standard_b64decode(env["payload"])
    except Exception:
        return errs + ["payload is not valid base64"]
    signatures = env.get("signatures") or []
    if not signatures:
        errs.append("envelope carries no signature")
    verified = []
    for index, signature in enumerate(signatures):
        try:
            pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(signature["keyid"]))
            pk.verify(base64.standard_b64decode(signature["sig"]),
                      pae(env.get("payloadType", ""), payload))
            verified.append(signature["keyid"])
        except Exception:
            errs.append(f"signature[{index}] does not verify over the DSSE PAE")
    if expect_key and expect_key not in verified:
        errs.append(f"no signature from the expected key {expect_key[:12]}")
    try:
        statement = json.loads(payload)
    except Exception:
        return errs + ["payload is not JSON"]
    return errs + check(store, statement)


def loss_report(store, wid: str) -> list:
    """What the record has and the Statement cannot give back.

    A round trip through DSSE is exact -- the payload is the bytes that were
    signed. A round trip back to a warrant record is not, and pretending
    otherwise is how a projection gets mistaken for the artefact.
    """
    env = store.get_record(wid)
    body = env["body"]
    lost = ["the record's own Ed25519 signatures: only actor and keyid are "
            "projected, so a Statement cannot establish who signed the warrant",
            "the canonical body bytes, and therefore the ability to recompute "
            "the WarrantID from the Statement alone",
            "the store's blobs: policy, evidence and check bodies are named by "
            "digest, so `because` reasons cannot be re-executed from the "
            "Statement without the store"]
    if any(r["kind"] != "prose" for r in body["because"]):
        lost.append("a check reason's transcript, where one exists: the digest "
                    "travels, the bytes do not")
    if body.get("prior"):
        lost.append("the prior chain's contents: prior WarrantIDs travel as "
                    "digests, their bodies do not")
    return lost


def selftest(store):
    recs = store.all_records()
    if not recs:
        sys.exit("selftest needs a non-empty store")
    ok = True

    def case(name, cond):
        nonlocal ok
        print(("OK   " if cond else "FAIL "), name)
        ok &= bool(cond)

    wid = sorted(recs)[0]
    st = wrap(store, wid)
    case("wrap produces the required in-toto v1 shape",
         st["_type"] == STATEMENT_TYPE and st["predicateType"] == PREDICATE_TYPE
         and isinstance(st["subject"], list) and st["subject"]
         and "digest" in st["subject"][0])
    case("check accepts a faithful Statement", check(store, st) == [])
    case("Statement is JSON-serialisable and round-trips",
         check(store, json.loads(json.dumps(st))) == [])

    # Every field the bridge claims must be load-bearing: tamper it, catch it.
    for mutate, label in (
        (lambda s: s["predicate"].update(decision="accept" if
         s["predicate"]["decision"] != "accept" else "reject"), "decision"),
        (lambda s: s["predicate"].update(actor="mallory@evil"), "actor"),
        (lambda s: s["predicate"].update(timestamp=1), "timestamp"),
        (lambda s: s["subject"][0]["digest"].update(sha256="f" * 64), "subject digest"),
        (lambda s: s["predicate"]["under"].append(_descriptor("e" * 64)), "under"),
        (lambda s: s["predicate"].update(warrantId="a" * 64), "warrantId"),
        (lambda s: s.update(_type="https://in-toto.io/Statement/v0"), "_type"),
    ):
        bad = json.loads(json.dumps(st))
        mutate(bad)
        case(f"check rejects a tampered {label}", check(store, bad) != [])

    # DSSE: the envelope must bind the payload type and the bytes, and a
    # verified signature must not be read as a verified authority.
    with tempfile.TemporaryDirectory() as tmp:                # never in the store
        key_path = Path(tmp) / "selftest-dsse.key"
        key_path.write_text(hashlib.sha256(b"intoto-selftest-key").digest().hex())
        env = envelope(store, wid, str(key_path))
    keyid = env["signatures"][0]["keyid"]
    case("envelope verifies over the DSSE PAE and binds to the record",
         verify_envelope(store, env) == [])
    case("envelope round-trips to a byte-identical Statement",
         base64.standard_b64decode(env["payload"]) == canonical(wrap(store, wid)))
    case("verify accepts the key it was told to expect",
         verify_envelope(store, env, expect_key=keyid) == [])
    case("verify rejects a key it was not signed by",
         verify_envelope(store, env, expect_key="0" * 64) != [])

    for mutate, label in (
        (lambda e: e.update(payloadType="application/json"), "payloadType"),
        (lambda e: e["signatures"][0].update(sig=base64.standard_b64encode(
            b"\x00" * 64).decode()), "signature"),
        (lambda e: e.update(payload=base64.standard_b64encode(
            canonical({**wrap(store, wid), "predicate": {
                **wrap(store, wid)["predicate"], "actor": "mallory@evil"}})).decode()),
         "predicate inside the envelope"),
        (lambda e: e.update(signatures=[]), "envelope with no signature at all"),
    ):
        bad = json.loads(json.dumps(env))
        mutate(bad)
        case(f"verify-envelope rejects a tampered {label}"
             if "no signature" not in label else f"verify-envelope rejects an {label}",
             verify_envelope(store, bad) != [])

    print("\nINTOTO-BRIDGE: " + ("ALL PASS" if ok else "FAILURES"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["wrap", "check", "envelope", "verify-envelope",
                                    "roundtrip", "selftest"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--store", default=str(ROOT / ".warrants"))
    ap.add_argument("--key", help="Ed25519 seed file, as produced by `warrant keygen`")
    ap.add_argument("--expect-key", help="public key hex a signature must come from")
    a = ap.parse_args()
    store = W.Store(Path(a.store))
    if a.cmd == "wrap":
        if not a.arg:
            sys.exit("wrap needs a WarrantID")
        print(json.dumps(wrap(store, a.arg), indent=2, sort_keys=True))
        return 0
    if a.cmd == "check":
        if not a.arg:
            sys.exit("check needs a statement file")
        errs = check(store, json.loads(Path(a.arg).read_text()))
        for e in errs:
            print("ERR ", e)
        print("INTOTO: " + ("BOUND — the Statement describes this record"
                            if not errs else f"{len(errs)} binding error(s)"))
        return 1 if errs else 0
    if a.cmd == "envelope":
        if not a.arg or not a.key:
            sys.exit("envelope needs a WarrantID and --key")
        print(json.dumps(envelope(store, a.arg, a.key), indent=2, sort_keys=True))
        return 0
    if a.cmd == "verify-envelope":
        if not a.arg:
            sys.exit("verify-envelope needs an envelope file")
        errs = verify_envelope(store, json.loads(Path(a.arg).read_text()), a.expect_key)
        for e in errs:
            print("ERR ", e)
        if errs:
            print(f"DSSE: {len(errs)} error(s)")
            return 1
        print("DSSE: signature verifies and the Statement binds to the record.")
        print("      " + ("Authority: signed by the key you named."
                          if a.expect_key else
                          "Integrity only: the key is the one named inside the "
                          "envelope, which whoever wrote it chose. Pass "
                          "--expect-key to make a claim about authority."))
        return 0
    if a.cmd == "roundtrip":
        if not a.arg or not a.key:
            sys.exit("roundtrip needs a WarrantID and --key")
        env = envelope(store, a.arg, a.key)
        exact = base64.standard_b64decode(env["payload"]) == canonical(wrap(store, a.arg))
        errs = verify_envelope(store, env)
        print(f"envelope -> Statement: {'byte-identical' if exact else 'DIVERGED'}")
        print(f"signature and binding: {'ok' if not errs else errs}")
        print("\nrecord -> Statement is lossy, by design. Not carried:")
        for item in loss_report(store, a.arg):
            print(f"  - {item}")
        return 0 if exact and not errs else 1
    return selftest(store)


if __name__ == "__main__":
    sys.exit(main())
