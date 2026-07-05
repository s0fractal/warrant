#!/usr/bin/env python3
"""Warrant v0.1 — reference implementation (M1: file store, five verbs, conformance).

One file, standard library + `cryptography` (Ed25519). The spec (SPEC.md) is
the contract; the vectors in examples/ are law: `conformance` MUST reproduce
all five hashes byte-exactly and verify all three signatures.

Canonicalization note: WarrantID = SHA-256 over RFC 8785 (JCS) bytes. For v0.1
bodies this equals Python's `json.dumps(body, sort_keys=True,
separators=(',',':'), ensure_ascii=False)` because (a) every number is an
integer and (b) every object key is schema-fixed ASCII. JCS sorts keys by
UTF-16 code units while Python sorts by code point — identical for ASCII.
Any future version that admits free-form keys MUST revisit this shortcut.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)

VERSION = "0.1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DECISIONS = ("propose", "accept", "reject", "supersede")
BODY_FIELDS = {"warrant", "decision", "subject", "under", "because",
               "evidence", "actor", "prior", "ts"}
RUNTIMES = ("cmd@v1",)          # ski@v1 is reserved: MUST be rejected in v0.1


# ---------- canonicalization & identity (SPEC §4) ----------
def canon(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def warrant_id(body):
    return hashlib.sha256(canon(body)).hexdigest()


def blob_hash(b):
    return hashlib.sha256(b).hexdigest()


# ---------- schema validation (SPEC §2, §3) ----------
def _is_hex64(x):
    return isinstance(x, str) and bool(HEX64.match(x))


def validate_body(b):
    """Return a list of error strings; empty list = schema-valid."""
    e = []
    if not isinstance(b, dict):
        return ["body is not an object"]
    for k in sorted(set(b) - BODY_FIELDS):
        e.append(f"unknown field: {k}")
    for k in sorted(BODY_FIELDS - set(b)):
        e.append(f"missing field: {k}")
    if e:
        return e
    if b["warrant"] != VERSION:
        e.append(f"warrant version must be \"{VERSION}\"")
    if b["decision"] not in DECISIONS:
        e.append(f"decision must be one of {DECISIONS}")
    s = b["subject"]
    if not isinstance(s, dict) or set(s) - {"hash", "note"} or "hash" not in s:
        e.append("subject must be {hash, note?}")
    else:
        if not _is_hex64(s["hash"]):
            e.append("subject.hash must be hex64")
        if "note" in s and not (isinstance(s["note"], str) and len(s["note"]) <= 200):
            e.append("subject.note must be a string of <=200 chars")
    if not (isinstance(b["under"], list) and len(b["under"]) >= 1
            and all(_is_hex64(h) for h in b["under"])):
        e.append("under must be a list of >=1 hex64 hashes")
    if not (isinstance(b["evidence"], list) and all(_is_hex64(h) for h in b["evidence"])):
        e.append("evidence must be a list of hex64 hashes")
    a = b["actor"]
    if not (isinstance(a, dict) and set(a) == {"id"} and isinstance(a["id"], str) and a["id"]):
        e.append("actor must be {id: <nonempty string>}")
    if not (isinstance(b["prior"], list) and all(_is_hex64(h) for h in b["prior"])):
        e.append("prior must be a list of WarrantIDs (hex64)")
    if not isinstance(b["ts"], int) or isinstance(b["ts"], bool):
        e.append("ts must be an integer (unix seconds)")
    bc = b["because"]
    if not isinstance(bc, list):
        e.append("because must be a list")
        bc = []
    for i, r in enumerate(bc):
        e += [f"because[{i}]: {m}" for m in _validate_reason(r)]
    if b.get("decision") in ("reject", "supersede") and len(bc) < 1:
        e.append(f"{b['decision']} requires >=1 reason")
    return e


def _validate_reason(r):
    if not isinstance(r, dict):
        return ["reason is not an object"]
    kind = r.get("kind")
    if kind == "prose":
        if set(r) != {"kind", "text"} or not isinstance(r.get("text"), str):
            return ["prose reason must be {kind, text}"]
        return []
    if kind == "check":
        if set(r) - {"kind", "check", "runtime", "verdict", "transcript"}:
            return ["check reason has unknown fields"]
        e = []
        if not _is_hex64(r.get("check")):
            e.append("check must be hex64")
        if r.get("runtime") == "ski@v1":
            e.append("runtime ski@v1 is reserved and MUST be rejected in v0.1")
        elif r.get("runtime") not in RUNTIMES:
            e.append(f"runtime must be one of {RUNTIMES}")
        if r.get("verdict") not in ("pass", "fail"):
            e.append("verdict must be pass|fail")
        if "transcript" in r and not _is_hex64(r["transcript"]):
            e.append("transcript must be hex64")
        return e
    return [f"unknown reason kind: {kind!r}"]


def is_unverifiable(body):
    """Protocol rule (SPEC §3): a reject whose every reason is prose."""
    return (body["decision"] == "reject"
            and all(r.get("kind") == "prose" for r in body["because"]))


# ---------- keys & signatures (SPEC §5) ----------
def load_key(path):
    seed = bytes.fromhex(Path(path).read_text().strip())
    if len(seed) != 32:
        sys.exit("key file must contain a 32-byte hex seed")
    return Ed25519PrivateKey.from_private_bytes(seed)


def pubkey_hex(sk):
    return sk.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def sign_envelope(body, actor, key_path):
    sk = load_key(key_path)
    wid = warrant_id(body)
    return {"actor": actor, "key": pubkey_hex(sk),
            "sig": sk.sign(bytes.fromhex(wid)).hex()}


def verify_sig(wid, sig):
    try:
        pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(sig["key"]))
        pk.verify(bytes.fromhex(sig["sig"]), bytes.fromhex(wid))
        return True
    except Exception:
        return False


# ---------- store ----------
class Store:
    def __init__(self, root=".warrants"):
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.records = self.root / "records"

    def init(self):
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.records.mkdir(parents=True, exist_ok=True)

    def require(self):
        if not self.records.is_dir():
            sys.exit(f"no store at {self.root} (run: warrant init)")

    def put_blob(self, data):
        h = blob_hash(data)
        p = self.blobs / h
        if not p.exists():
            p.write_bytes(data)
        return h

    def has_blob(self, h):
        return (self.blobs / h).exists()

    def put_record(self, env):
        wid = warrant_id(env["body"])
        (self.records / f"{wid}.json").write_text(
            json.dumps(env, indent=2, sort_keys=True) + "\n")
        return wid

    def get_record(self, wid):
        p = self.records / f"{wid}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def all_records(self):
        out = {}
        for p in sorted(self.records.glob("*.json")):
            out[p.stem] = json.loads(p.read_text())
        return out


# ---------- verification (SPEC §6) ----------
def verify_store(store, quiet=False):
    """Return (n_errors, n_warnings). Prints a report unless quiet."""
    errs = warns = 0

    def out(level, wid, msg):
        nonlocal errs, warns
        if level == "ERR":
            errs += 1
        elif level == "WARN":
            warns += 1
        if not quiet:
            print(f"{level:4} {wid[:12]}  {msg}")

    recs = store.all_records()
    for wid, env in recs.items():
        if set(env) != {"body", "sigs"}:
            out("ERR", wid, "envelope must be {body, sigs}")
            continue
        body = env["body"]
        for m in validate_body(body):
            out("ERR", wid, f"schema: {m}")
        got = warrant_id(body)
        if got != wid:
            out("ERR", wid, f"WarrantID mismatch: recomputed {got[:12]}")
            continue
        sigs = env.get("sigs", [])
        if not sigs:
            out("ERR", wid, "no signatures")
        actor_signed = False
        for s in sigs:
            if not verify_sig(wid, s):
                out("ERR", wid, f"bad signature by {s.get('actor')}")
            elif s.get("actor") == body["actor"]["id"]:
                actor_signed = True
        if sigs and not actor_signed:
            out("ERR", wid, "no valid signature by body.actor.id")
        for p in body["prior"]:
            prev = recs.get(p)
            if prev is None:
                out("ERR", wid, f"prior {p[:12]} not in store")
            elif prev["body"]["ts"] > body["ts"]:
                out("WARN", wid, f"ts decreases along prior edge {p[:12]}")
        refs = list(body["under"]) + list(body["evidence"]) + [body["subject"]["hash"]]
        refs += [r["check"] for r in body["because"] if r.get("kind") == "check"]
        refs += [r["transcript"] for r in body["because"]
                 if r.get("kind") == "check" and "transcript" in r]
        for h in refs:
            if not store.has_blob(h) and h not in recs:
                out("WARN", wid, f"unresolved blob {h[:12]}")
        if body["decision"] == "supersede" and body["subject"]["hash"] not in recs:
            out("WARN", wid, "supersede subject is not a stored WarrantID")
        if is_unverifiable(body):
            out("WARN", wid, "UNVERIFIABLE: reject with prose-only reasons")
    if not quiet:
        print(f"\nverify: {len(recs)} records, {errs} errors, {warns} warnings")
    return errs, warns


def why(store, wid, depth=0, seen=None):
    seen = seen if seen is not None else set()
    env = store.get_record(wid)
    pad = "  " * depth
    if env is None:
        print(f"{pad}?? {wid[:16]} (not in store)")
        return
    body = env["body"]
    ok = warrant_id(body) == wid and all(verify_sig(wid, s) for s in env["sigs"])
    mark = "" if ok else "  [VERIFY FAILED]"
    unv = "  [unverifiable]" if is_unverifiable(body) else ""
    note = body["subject"].get("note", "")
    print(f"{pad}{body['decision'].upper()} {wid[:16]} by {body['actor']['id']}"
          f"  subject={body['subject']['hash'][:12]} {note}{mark}{unv}")
    for r in body["because"]:
        if r["kind"] == "prose":
            print(f"{pad}  - prose: {r['text']}")
        else:
            print(f"{pad}  - check {r['check'][:12]} [{r['runtime']}] -> {r['verdict']}")
    for h in body["under"]:
        print(f"{pad}  under policy {h[:12]}"
              + ("" if store.has_blob(h) else " (unresolved)"))
    if wid in seen:
        print(f"{pad}  (cycle)")
        return
    seen.add(wid)
    for p in body["prior"]:
        why(store, p, depth + 1, seen)


# ---------- filing ----------
def resolve_blob_arg(store, val):
    """Accept a hex64 hash or a file path (file gets blob-added)."""
    if val and HEX64.match(val):
        return val
    p = Path(val)
    if p.is_file():
        return store.put_blob(p.read_bytes())
    sys.exit(f"not a hex64 hash or existing file: {val}")


def build_reasons(store, args):
    reasons = [{"kind": "prose", "text": t} for t in (args.reason or [])]
    if getattr(args, "check", None):
        r = {"kind": "check", "check": resolve_blob_arg(store, args.check),
             "runtime": "cmd@v1", "verdict": args.verdict}
        if args.transcript:
            r["transcript"] = resolve_blob_arg(store, args.transcript)
        reasons.append(r)
    return reasons


def file_warrant(store, decision, subject_hash, args, note=None):
    body = {
        "warrant": VERSION,
        "decision": decision,
        "subject": ({"hash": subject_hash, "note": note} if note
                    else {"hash": subject_hash}),
        "under": [resolve_blob_arg(store, u) for u in args.under],
        "because": build_reasons(store, args),
        "evidence": [resolve_blob_arg(store, ev) for ev in (args.evidence or [])],
        "actor": {"id": args.actor},
        "prior": list(args.prior or []),
        "ts": args.ts if args.ts is not None else int(time.time()),
    }
    errors = validate_body(body)
    if errors:
        sys.exit("invalid warrant:\n  " + "\n  ".join(errors))
    env = {"body": body, "sigs": [sign_envelope(body, args.actor, args.key)]}
    wid = store.put_record(env)
    if is_unverifiable(body):
        print("warning: UNVERIFIABLE reject (prose-only reasons); "
              "add a --check to make it provable", file=sys.stderr)
    print(wid)
    return wid


# ---------- conformance (SPEC §8) ----------
SPEC_VECTORS = {
    "policy.txt": "cb3a0afe6ee6219867b9c3f9b860080918fe1042f315fe02ff62300f780beb73",
    "check.sh": "05d234bec21803c6fa007d848c1773b9fd05cfdf852d6d09542ed3b127c02b6c",
    "propose.warrant.json": "00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1",
    "reject.warrant.json": "5f5d4035a4ae04a3eec255105eee7dda7c98daaf9962c92cbbbad38ac21509d8",
    "accept.warrant.json": "bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78",
}


def conformance(examples_dir):
    d = Path(examples_dir)
    ok = []

    def chk(name, cond, detail=""):
        ok.append(cond)
        print(("OK  " if cond else "FAIL"), name, "" if cond else detail)

    for name in ("policy.txt", "check.sh"):
        got = blob_hash((d / name).read_bytes())
        chk(f"blob {name}", got == SPEC_VECTORS[name], got)
    chain = {}
    for name in ("propose.warrant.json", "reject.warrant.json", "accept.warrant.json"):
        env = json.loads((d / name).read_text())
        errs = validate_body(env["body"])
        chk(f"schema {name}", not errs, "; ".join(errs))
        wid = warrant_id(env["body"])
        chk(f"WarrantID {name}", wid == SPEC_VECTORS[name], wid)
        for s in env["sigs"]:
            chk(f"sig {name} by {s['actor']}", verify_sig(wid, s))
        chain[name] = (wid, env["body"])
    p = chain["propose.warrant.json"][0]
    r = chain["reject.warrant.json"]
    a = chain["accept.warrant.json"]
    chk("chain reject.prior -> propose", r[1]["prior"] == [p])
    chk("chain accept.prior -> reject", a[1]["prior"] == [r[0]])
    ts = [chain[n][1]["ts"] for n in
          ("propose.warrant.json", "reject.warrant.json", "accept.warrant.json")]
    chk("ts non-decreasing", ts == sorted(ts))
    print(f"\n{'CONFORMANCE: ALL PASS' if all(ok) else 'CONFORMANCE: FAILURES PRESENT'}"
          f" ({sum(ok)}/{len(ok)})")
    return all(ok)


# ---------- selftest (live round-trip in a temp store) ----------
def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        st = Store()
        st.init()
        key = Path("k.key")
        key.write_text(os.urandom(32).hex())
        sk = load_key(key)
        _ = pubkey_hex(sk)
        policy = st.put_blob(b"POLICY: selftest v1\n1. be verifiable\n")
        check = st.put_blob(b"#!/bin/sh\ntrue\n")
        subject = st.put_blob(b"the change under decision\n")

        class A:  # minimal args shim
            pass

        a = A()
        a.under, a.evidence, a.prior, a.reason = [policy], [], [], ["needed"]
        a.check = a.transcript = None
        a.actor, a.key, a.ts = "tester@self", str(key), 1751700000
        w1 = file_warrant(st, "propose", subject, a, note="selftest")
        a2 = A()
        a2.under, a2.evidence, a2.prior = [policy], [], [w1]
        a2.reason, a2.check, a2.verdict, a2.transcript = [], check, "pass", None
        a2.actor, a2.key, a2.ts = "tester@self", str(key), 1751700001
        w2 = file_warrant(st, "accept", subject, a2)
        errs, warns = verify_store(st, quiet=True)
        assert errs == 0, f"selftest: verify errors {errs}"
        assert st.get_record(w2)["body"]["prior"] == [w1]
        # tamper: one byte in the stored body must break identity
        env = st.get_record(w1)
        env["body"]["ts"] += 1
        (st.records / f"{w1}.json").write_text(json.dumps(env))
        errs2, _ = verify_store(st, quiet=True)
        assert errs2 >= 1, "selftest: tampering not detected"
        print("SELFTEST: ALL PASS")
        return True


# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser(prog="warrant", description=__doc__.splitlines()[0])
    ap.add_argument("--store", default=".warrants")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    kg = sub.add_parser("keygen")
    kg.add_argument("--out", required=True)
    ba = sub.add_parser("blob")
    ba.add_argument("action", choices=["add"])
    ba.add_argument("file")
    pa = sub.add_parser("policy")
    pa.add_argument("action", choices=["add"])
    pa.add_argument("file")

    def filing(p, with_prior_pos=False):
        if with_prior_pos:
            p.add_argument("prior_id")
        p.add_argument("--subject")
        p.add_argument("--note")
        p.add_argument("--under", action="append", default=[])
        p.add_argument("--reason", action="append")
        p.add_argument("--check")
        p.add_argument("--verdict", choices=["pass", "fail"], default="pass")
        p.add_argument("--transcript")
        p.add_argument("--evidence", action="append")
        p.add_argument("--prior", action="append")
        p.add_argument("--actor", required=True)
        p.add_argument("--key", required=True)
        p.add_argument("--ts", type=int)

    filing(sub.add_parser("propose"))
    filing(sub.add_parser("accept"), with_prior_pos=True)
    filing(sub.add_parser("reject"), with_prior_pos=True)
    filing(sub.add_parser("supersede"), with_prior_pos=True)
    wy = sub.add_parser("why")
    wy.add_argument("id")
    sub.add_parser("verify")
    cf = sub.add_parser("conformance")
    cf.add_argument("examples", nargs="?", default="examples")
    sub.add_parser("selftest")

    args = ap.parse_args()
    store = Store(args.store)

    if args.cmd == "init":
        store.init()
        print(f"initialized {store.root}")
    elif args.cmd == "keygen":
        seed = os.urandom(32)
        p = Path(args.out)
        p.write_text(seed.hex() + "\n")
        p.chmod(0o600)
        print("pubkey", pubkey_hex(Ed25519PrivateKey.from_private_bytes(seed)))
    elif args.cmd in ("blob", "policy"):
        store.require()
        print(store.put_blob(Path(args.file).read_bytes()))
    elif args.cmd == "propose":
        store.require()
        if not args.subject:
            sys.exit("propose requires --subject")
        file_warrant(store, "propose", resolve_blob_arg(store, args.subject),
                     args, note=args.note)
    elif args.cmd in ("accept", "reject", "supersede"):
        store.require()
        prior_env = store.get_record(args.prior_id)
        if prior_env is None:
            sys.exit(f"prior warrant {args.prior_id} not in store")
        args.prior = [args.prior_id] + (args.prior or [])
        if args.cmd == "supersede":
            subject = args.prior_id
        elif args.subject:
            subject = resolve_blob_arg(store, args.subject)
        else:
            subject = prior_env["body"]["subject"]["hash"]
        if not args.under:
            args.under = list(prior_env["body"]["under"])
        note = args.note or prior_env["body"]["subject"].get("note")
        file_warrant(store, args.cmd, subject, args, note=note)
    elif args.cmd == "why":
        store.require()
        why(store, args.id)
    elif args.cmd == "verify":
        store.require()
        errs, _ = verify_store(store)
        sys.exit(1 if errs else 0)
    elif args.cmd == "conformance":
        sys.exit(0 if conformance(args.examples) else 1)
    elif args.cmd == "selftest":
        sys.exit(0 if selftest() else 1)


if __name__ == "__main__":
    main()
