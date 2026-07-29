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
It does not make a warrant an SLSA provenance, and it does not claim the
attestation is signed -- wrapping in DSSE and pushing to Rekor is a separate step
with separate trust. This produces the Statement; signing it is the caller's
business and is deliberately not hidden inside a converter.

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
    python3 tools/intoto.py selftest
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W                                          # noqa: E402

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

    print("\nINTOTO-BRIDGE: " + ("ALL PASS" if ok else "FAILURES"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["wrap", "check", "selftest"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--store", default=str(ROOT / ".warrants"))
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
    return selftest(store)


if __name__ == "__main__":
    sys.exit(main())
