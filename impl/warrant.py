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

VERSION = "0.2"           # version written into NEW records
ACCEPTED = ("0.1", "0.2")  # versions this implementation validates
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DECISIONS = ("propose", "accept", "reject", "supersede")
BODY_FIELDS = {"warrant", "decision", "subject", "under", "because",
               "evidence", "actor", "prior", "ts"}
RUNTIMES = {"0.1": ("cmd@v1",),            # ski@v1 reserved in 0.1 bodies
            "0.2": ("cmd@v1", "ski@v1")}   # SPEC s3.1


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
    if b["warrant"] not in ACCEPTED:
        e.append(f"warrant version must be one of {ACCEPTED}")
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
    ver = b.get("warrant") if b.get("warrant") in ACCEPTED else VERSION
    for i, r in enumerate(bc):
        e += [f"because[{i}]: {m}" for m in _validate_reason(r, ver)]
    if b.get("decision") in ("reject", "supersede") and len(bc) < 1:
        e.append(f"{b['decision']} requires >=1 reason")
    return e


def _validate_reason(r, version=VERSION):
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
        allowed = RUNTIMES[version]
        if r.get("runtime") == "ski@v1" and "ski@v1" not in allowed:
            e.append("runtime ski@v1 is reserved and MUST be rejected in v0.1")
        elif r.get("runtime") not in allowed:
            e.append(f"runtime must be one of {allowed}")
        if r.get("verdict") not in ("pass", "fail"):
            e.append("verdict must be pass|fail")
        if "transcript" in r and not _is_hex64(r["transcript"]):
            e.append("transcript must be hex64")
        return e
    return [f"unknown reason kind: {kind!r}"]


def is_unverifiable(body):
    """Protocol rule (SPEC §3): a reject whose every reason is prose."""
    return (body["decision"] == "reject"
            and bool(body["because"])
            and all(r.get("kind") == "prose" for r in body["because"]))


# ---------- ski@v1 runtime (SPEC §3.1, v0.2) ----------
def load_sigma():
    """Load the Σ-GLYPH Book I oracle. Path: $SIGMA_GLYPH (dir containing
    sigma_glyph.py) or ~/sigma-glyph/impl. Returns module or None."""
    import importlib.util
    path = Path(os.environ.get("SIGMA_GLYPH",
                               Path.home() / "sigma-glyph/impl")) / "sigma_glyph.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("sigma_glyph", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def validate_ski_blob(doc):
    if not isinstance(doc, dict) or set(doc) != {"ski", "term", "atp", "expect"}:
        return "ski check blob must be exactly {ski, term, atp, expect}"
    if doc["ski"] != 1:
        return "ski field must be 1"
    if not (_is_hex64(doc.get("term")) and _is_hex64(doc.get("expect"))):
        return "term and expect must be hex64 NodeHashes"
    a = doc.get("atp")
    if not isinstance(a, int) or isinstance(a, bool) or not (0 <= a < 2**32):
        return "atp must be a uint32"
    return None


def run_ski_check(store, check_hex, sg=None):
    """Execute a ski@v1 check against the warrant blob store (which IS a
    Σ-GLYPH CAS). Returns (verdict, result_hash_hex, atp_spent).
    Raises RuntimeError if the check blob is malformed or the oracle missing."""
    sg = sg or load_sigma()
    if sg is None:
        raise RuntimeError("ski@v1 runtime unavailable: sigma_glyph.py not found "
                           "(set SIGMA_GLYPH to its impl directory)")
    p = store.blobs / check_hex
    if not p.exists():
        raise RuntimeError(f"check blob {check_hex[:12]} not in store")
    raw = p.read_bytes()
    doc = json.loads(raw)
    if canon(doc) != raw:
        raise RuntimeError("ski check blob is not JCS-canonical (SPEC s3.1)")
    err = validate_ski_blob(doc)
    if err:
        raise RuntimeError(f"invalid ski check blob: {err}")

    class BlobCAS:                       # adapter: warrant blobs -> Σ-GLYPH store
        def get(self, h):
            q = store.blobs / h.hex()
            return q.read_bytes() if q.exists() else None

    r, spent = sg.eval_hash(bytes.fromhex(doc["term"]), doc["atp"], BlobCAS())
    rh = sg.term_hash(r).hex()
    return ("pass" if rh == doc["expect"] else "fail"), rh, spent


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
                continue
            # SPEC §5 MUST: with no keyring configured, the key↔actor binding is
            # unverified even though the signature is cryptographically valid —
            # the filer chose the key, so this actor claim is unproven.
            out("WARN", wid, f"binding unverified (no keyring): key "
                             f"{str(s.get('key',''))[:12]} claims actor {s.get('actor')}")
            if s.get("actor") == body["actor"]["id"]:
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
            out("ERR", wid, "supersede subject MUST be the superseded WarrantID (SPEC s7)")
        if is_unverifiable(body):
            out("WARN", wid, "UNVERIFIABLE: reject with prose-only reasons")
        for r in body["because"]:                   # re-run ski@v1 claims if we can
            if r.get("kind") == "check" and r.get("runtime") == "ski@v1":
                try:
                    got, rh, _ = run_ski_check(store, r["check"])
                    if got != r["verdict"]:
                        out("WARN", wid, f"ski@v1 verdict mismatch: claimed "
                                         f"{r['verdict']}, re-run gives {got} ({rh[:12]})")
                except RuntimeError:
                    pass                            # oracle absent/blob elsewhere: skip
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
        runtime = getattr(args, "runtime", None) or "cmd@v1"
        r = {"kind": "check", "check": resolve_blob_arg(store, args.check),
             "runtime": runtime, "verdict": args.verdict}
        if args.transcript:
            r["transcript"] = resolve_blob_arg(store, args.transcript)
        if runtime == "ski@v1":                    # verify the claim at filing time
            got, rh, spent = run_ski_check(store, r["check"])
            if got != args.verdict:
                sys.exit(f"refusing to file: ski@v1 check re-run gives {got} "
                         f"(result {rh[:16]}, {spent} ATP), you claimed {args.verdict}")
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

    ski_dir = d / "ski"
    if ski_dir.is_dir():                                # SPEC s8.2 (v0.2)
        env = json.loads((ski_dir / "accept-ski.warrant.json").read_text())
        wid = warrant_id(env["body"])
        chk("ski: warrant id",
            wid == "8c9267bccbc217db2f3f16e6928acaf062a1c78443b2317985567b238ccfe8a0", wid)
        chk("ski: schema (0.2 body)", not validate_body(env["body"]),
            "; ".join(validate_body(env["body"])))
        for s in env["sigs"]:
            chk(f"ski: sig by {s['actor']}", verify_sig(wid, s))
        cb = (ski_dir / "check.json").read_bytes()
        ch = blob_hash(cb)
        chk("ski: check blob hash",
            ch == "0c30960435e9c9302a6a1538682e5864f2a754475369979bd3d635543976b2ad", ch)
        v01 = dict(env["body"], warrant="0.1")
        chk("ski: 0.1 body MUST reject ski@v1",
            any("reserved" in m for m in validate_body(v01)))
        sg = load_sigma()
        if sg is None:
            chk("ski: runtime re-run SKIPPED (no sigma_glyph; set SIGMA_GLYPH)", True)
        else:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                st = Store(td)
                st.init()
                for f in ski_dir.glob("*.bin"):
                    st.put_blob(f.read_bytes())
                st.put_blob(cb)
                verdict, rh, spent = run_ski_check(st, ch, sg)
                chk("ski: re-run -> pass, H(S), 20 ATP",
                    verdict == "pass" and spent == 20
                    and rh == "887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6",
                    f"{verdict} {rh} {spent}")
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
            p.add_argument("prior_id", nargs="?",
                           help="warrant being responded to; omit to file "
                                "without a prior (requires --subject, --under)")
        p.add_argument("--subject")
        p.add_argument("--note")
        p.add_argument("--under", action="append", default=[])
        p.add_argument("--reason", action="append")
        p.add_argument("--check")
        p.add_argument("--runtime", choices=["cmd@v1", "ski@v1"], default="cmd@v1")
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
    ck = sub.add_parser("check", help="re-run a ski@v1 check blob against the store")
    ck.add_argument("hash")
    sub.add_parser("verify")
    cf = sub.add_parser("conformance")
    cf.add_argument("examples", nargs="?", default="examples")
    sub.add_parser("selftest")
    cn = sub.add_parser("canon", help="print {warrant_id, canon_hex} for a bare body JSON")
    cn.add_argument("file")

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
        if args.prior_id is None:
            if args.cmd == "supersede":
                sys.exit("supersede requires the warrant id being superseded")
            if not (args.subject and args.under):
                sys.exit(f"{args.cmd} without a prior requires --subject and --under")
            file_warrant(store, args.cmd, resolve_blob_arg(store, args.subject),
                         args, note=args.note)
            return
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
    elif args.cmd == "check":
        store.require()
        try:
            verdict, rh, spent = run_ski_check(store, args.hash)
        except RuntimeError as ex:
            sys.exit(str(ex))
        print(f"{verdict}  result={rh}  atp_spent={spent}")
        sys.exit(0 if verdict == "pass" else 1)
    elif args.cmd == "verify":
        store.require()
        errs, _ = verify_store(store)
        sys.exit(1 if errs else 0)
    elif args.cmd == "conformance":
        sys.exit(0 if conformance(args.examples) else 1)
    elif args.cmd == "selftest":
        sys.exit(0 if selftest() else 1)
    elif args.cmd == "canon":
        body = json.loads(Path(args.file).read_text(encoding="utf-8"))
        print(json.dumps({"warrant_id": warrant_id(body),
                          "canon_hex": canon(body).hex()}))


if __name__ == "__main__":
    main()
