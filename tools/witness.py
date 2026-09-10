#!/usr/bin/env python3
"""witness.py — WRT-012 prototype: commitment / proofs / report, kept apart.

Three objects, never folded (proposals/WRT-012-ownerless-root.md §2):

  commitment  canonical JSON naming a subject digest, a verifier closure digest,
              a stream, a sequence and `prev`. Its SHA-256 is `C`. Nothing about
              proofs lives inside it.
  proofs      `C.ots` (time, produced by `ots stamp`) and holder receipts
              (written by the HOLDER in the HOLDER's own store, signed with the
              holder's key). Each proof is about `C`, none is inside `C`.
  report      derived, offline, recomputed every time from commitment + proofs
              + the verifier's OWN trusted holder configuration. Never an input.

Axes of the report (§2.3), each independent:

  verification  method / result / scope   — byte-profile results are replayed;
                                            legacy run claims remain NOT_RUN
  time          NONE | FILE_BOUND_PENDING | BLOCK_ATTESTATION_PRESENT_UNVERIFIED
                | UNCLASSIFIED             — this tool never emits BITCOIN_VERIFIED:
                                            it has no chain-header source
  holding       per configured holder: EXTERNALLY_OBSERVED | NONE
  freshness     UNKNOWN | LATER_STATE_WITNESSED(holder, path)
                — one direction only: local C_i, holder receipt for C_j, and a
                  link-by-link verified `prev` path C_i -> C_j. Anything else is
                  UNKNOWN with a typed note: PATH_INCOMPLETE (a link's bytes are
                  missing), DISCONNECTED (proven not the same chain),
                  LINK_TAMPERED (bytes at an address do not hash to it),
                  PATH_BOUND_EXCEEDED. None of the four grants later state.
  adoption      NOT_EVALUATED             — always, here

What this does NOT do: talk to the network in `report` (holder stores are
local paths in this prototype), verify a Bitcoin block, discover the latest
head, or decide anything. `authority: none` is printed on every report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
MAX_PATH_STEPS = 10_000
COMMIT_TYPE = "warrant.commitment@wrt012-dev"
RECEIPT_TYPE = "warrant.holder-receipt@wrt012-dev"
RUN_TYPE = "warrant.verifier-run@wrt012-dev"
REPORT_TYPE = "warrant.witness-report@wrt012-dev"
RECEIPT_DOMAIN = b"wrt012-receipt-v0:"


class Refused(ValueError):
    pass


def need(ok, why):
    if not ok:
        raise Refused(why)


# ----------------------------------------------------------------- bytes ---

def hex64(s):
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read(path) -> bytes:
    p = Path(path)
    fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        need(stat.S_ISREG(os.fstat(f.fileno()).st_mode), f"NOT_REGULAR_FILE:{p.name}")
        b = f.read(MAX_BYTES + 1)
        need(len(b) <= MAX_BYTES, f"SIZE_LIMIT:{p.name}")
        return b


def _no_floats(o):
    if isinstance(o, float):
        raise Refused("FLOAT_REFUSED")
    if isinstance(o, dict):
        for k, v in o.items():
            need(isinstance(k, str), "NON_STRING_KEY")
            _no_floats(v)
    elif isinstance(o, list):
        for v in o:
            _no_floats(v)


def canonical(obj) -> bytes:
    _no_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _pairs_hook(pairs):
    d = {}
    for k, v in pairs:
        need(k not in d, f"DUPLICATE_KEY:{k}")
        d[k] = v
    return d


def parse(b: bytes):
    try:
        return json.loads(b.decode("utf-8"), object_pairs_hook=_pairs_hook,
                          parse_float=lambda s: (_ for _ in ()).throw(Refused("FLOAT_REFUSED")),
                          parse_constant=lambda s: (_ for _ in ()).throw(Refused("CONSTANT_REFUSED")))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise Refused(f"JSON:{type(e).__name__}") from e


def write_new(path, b: bytes):
    """Create-only, never overwrite. The initial receipt rule from .triad."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(b)
        f.flush()
        os.fsync(f.fileno())


# ------------------------------------------------------------ commitment ---

def validate_commitment(obj) -> dict:
    need(isinstance(obj, dict) and set(obj) == {"type", "subject", "verifier", "stream", "sequence", "prev"},
         "COMMITMENT_SHAPE")
    need(obj["type"] == COMMIT_TYPE, "COMMITMENT_TYPE")
    s = obj["subject"]
    need(isinstance(s, dict) and set(s) == {"kind", "sha256"} and hex64(s["sha256"])
         and s["kind"] in ("git-commit", "file", "bundle", "warrant-record"), "SUBJECT")
    v = obj["verifier"]
    need(isinstance(v, dict) and set(v) == {"closure_sha256"} and hex64(v["closure_sha256"]), "VERIFIER")
    need(hex64(obj["stream"]), "STREAM")
    need(isinstance(obj["sequence"], int) and not isinstance(obj["sequence"], bool)
         and 0 <= obj["sequence"] < 2**53, "SEQUENCE")
    need(obj["prev"] is None or hex64(obj["prev"]), "PREV")
    need((obj["sequence"] == 0) == (obj["prev"] is None), "GENESIS_SHAPE")
    return obj


def load_commitment(path, expected: str | None = None):
    """Bytes -> (digest, obj). Refuses if bytes do not hash to `expected`."""
    b = read(path)
    d = sha(b)
    if expected is not None:
        need(d == expected, f"COMMITMENT_PIN:{expected[:12]}")
    obj = validate_commitment(parse(b))
    need(canonical(obj) == b, "NOT_CANONICAL")
    return d, obj


class Store:
    """Local stream store: commitments/<C>.json, proofs/<C>.ots, runs/<C>.json, tip."""

    def __init__(self, root):
        self.root = Path(root)

    def path(self, kind, c, ext="json"):
        return self.root / kind / f"{c}.{ext}"

    def tip(self):
        p = self.root / "tip"
        if not p.exists():
            return None
        t = read(p).decode("ascii").strip()
        need(hex64(t), "TIP_MALFORMED")
        return t

    def set_tip(self, c):
        p = self.root / "tip"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(c + "\n")
        os.replace(tmp, p)


def cmd_commit(a):
    st = Store(a.store)
    tip = st.tip()
    if tip is None:
        need(a.stream is not None, "NEW_STREAM_NEEDS_--stream")
        need(a.prev is None, "GENESIS_HAS_NO_PREV")
        stream, seq, prev = a.stream, 0, None
    else:
        _, tobj = load_commitment(st.path("commitments", tip), tip)
        need(a.prev is None or a.prev == tip, f"PREV_NOT_TIP:{tip[:12]}")
        need(a.stream is None or a.stream == tobj["stream"], "STREAM_MISMATCH")
        stream, seq, prev = tobj["stream"], tobj["sequence"] + 1, tip
    obj = validate_commitment({
        "type": COMMIT_TYPE,
        "subject": {"kind": a.subject_kind, "sha256": a.subject_sha256},
        "verifier": {"closure_sha256": a.verifier_closure_sha256},
        "stream": stream, "sequence": seq, "prev": prev})
    b = canonical(obj)
    c = sha(b)
    write_new(st.path("commitments", c), b)
    st.set_tip(c)
    print(json.dumps({"commitment": c, "sequence": seq, "prev": prev, "stream": stream}))
    return 0


# ------------------------------------------------------------------ time ---

def cmd_stamp(a):
    st = Store(a.store)
    src = st.path("commitments", a.commitment)
    load_commitment(src, a.commitment)
    dst = st.path("proofs", a.commitment, "ots")
    need(not dst.exists(), "OTS_EXISTS_NEVER_OVERWRITE")
    dst.parent.mkdir(parents=True, exist_ok=True)
    # `ots stamp` writes <src>.ots beside the source; move it, never re-stamp.
    r = subprocess.run([a.ots, "stamp", str(src)], capture_output=True, text=True)
    side = src.with_name(src.name + ".ots")
    out = {"exit": r.returncode, "stdout": r.stdout[-2000:], "stderr": r.stderr[-2000:]}
    if r.returncode == 0 and side.exists():
        shutil.move(str(side), str(dst))
        out["proof_sha256"] = sha(read(dst))
        out["note"] = "calendar submission of one digest; exit 0 is not time verification"
    print(json.dumps(out))
    return 0 if r.returncode == 0 else 1


def cmd_upgrade(a):
    """Upgrade a COPY. The initial receipt is never touched."""
    st = Store(a.store)
    src = st.path("proofs", a.commitment, "ots")
    need(src.exists(), "NO_INITIAL_OTS")
    dst = st.path("proofs", a.commitment, "upgraded.ots")
    need(not dst.exists(), "UPGRADED_EXISTS_NEVER_OVERWRITE")
    with tempfile.TemporaryDirectory() as td:
        cp = Path(td) / "copy.ots"
        shutil.copyfile(src, cp)
        r = subprocess.run([a.ots, "upgrade", str(cp)], capture_output=True, text=True)
        out = {"exit": r.returncode, "stdout": r.stdout[-2000:], "stderr": r.stderr[-2000:]}
        if r.returncode == 0:
            shutil.copyfile(cp, dst)
            out["upgraded_sha256"] = sha(read(dst))
    print(json.dumps(out))
    return 0 if r.returncode == 0 else 1


def classify_ots(commitment_bytes: bytes, proof_bytes: bytes) -> dict:
    """Offline. Same predicates as .triad/continuity/ots_receipt_status.py."""
    try:
        from opentimestamps.core.timestamp import DetachedTimestampFile
        from opentimestamps.core.serialize import BytesDeserializationContext
        from opentimestamps.core.op import OpSHA256
        from opentimestamps.core.notary import PendingAttestation, BitcoinBlockHeaderAttestation
    except ImportError:
        return {"status": "UNCLASSIFIED", "note": "opentimestamps library unavailable",
                "file_binding_verified": False, "time_verified": False}
    try:
        det = DetachedTimestampFile.deserialize(BytesDeserializationContext(proof_bytes))
    except Exception as e:  # library raises many types; all mean "not a receipt"
        raise Refused(f"OTS_PARSE:{type(e).__name__}") from e
    need(type(det.file_hash_op) is OpSHA256, "OTS_HASH_PROFILE")
    need(det.file_digest == hashlib.sha256(commitment_bytes).digest(), "OTS_FILE_DIGEST")
    pending, blocks, unknown = set(), [], []
    for msg, att in det.timestamp.all_attestations():
        if isinstance(att, PendingAttestation):
            pending.add(att.uri)
        elif isinstance(att, BitcoinBlockHeaderAttestation):
            blocks.append({"height": att.height, "attested_merkle_root_internal_hex": msg.hex()})
        else:
            unknown.append(type(att).__name__)
    status = ("BLOCK_ATTESTATION_PRESENT_UNVERIFIED" if blocks
              else "FILE_BOUND_PENDING" if pending else "FILE_BOUND_UNSUPPORTED_ATTESTATION")
    return {"status": status, "pending_calendars": sorted(pending), "bitcoin_attestations": blocks,
            "unsupported_attestations": sorted(unknown), "file_binding_verified": True,
            "time_verified": False, "calendar_authenticity_verified": False,
            "note": "no chain-header source; chain time is never claimed by this tool"}


def cmd_classify(a):
    st = Store(a.store)
    cb = read(st.path("commitments", a.commitment))
    need(sha(cb) == a.commitment, "COMMITMENT_PIN")
    pb = read(st.path("proofs", a.commitment, a.ext))
    print(json.dumps(classify_ots(cb, pb), sort_keys=True))
    return 0


# ---------------------------------------------------------- verification ---

BYTE_PROFILE = "warrant.byte-equality@v1"


def checker_sha256():
    return sha(read(__file__))


def byte_check(policy_bytes, subject_bytes, obj):
    """Trusted built-in predicate. No artifact-supplied code is executed."""
    need(sha(policy_bytes) == obj["verifier"]["closure_sha256"], "POLICY_PIN")
    policy = parse(policy_bytes)
    need(isinstance(policy, dict) and set(policy) == {"type", "checker_sha256", "expected_sha256"}, "POLICY_SHAPE")
    need(canonical(policy) == policy_bytes and policy["type"] == BYTE_PROFILE, "POLICY_PROFILE")
    need(policy["checker_sha256"] == checker_sha256(), "CHECKER_CHANGED")
    need(hex64(policy["expected_sha256"]), "EXPECTED_DIGEST")
    need(obj["subject"]["kind"] == "file", "SUBJECT_KIND")
    need(sha(subject_bytes) == obj["subject"]["sha256"], "SUBJECT_PIN")
    return {"method": "EXTERNAL_CLOSURE", "result": "PASS" if sha(subject_bytes) == policy["expected_sha256"] else "FAIL",
            "scope": "subject bytes SHA-256 equals policy.expected_sha256", "profile": BYTE_PROFILE}


def put_operand(st, data):
    path = st.path("operands", sha(data), "bin")
    try:
        write_new(path, data)
    except FileExistsError:
        need(read(path) == data, "OPERAND_COLLISION")


def cmd_run_verifier(a):
    # Refuse legacy execution BEFORE launching anything, including on retries.
    need(a.script is None and not a.args and a.cwd is None and a.scope is None
         and a.method == "EXTERNAL_CLOSURE", "UNBOUND_EXECUTION_UNSUPPORTED")
    need(a.policy is not None and a.subject is not None, "POLICY_AND_SUBJECT_REQUIRED")
    st = Store(a.store)
    c, obj = load_commitment(st.path("commitments", a.commitment), a.commitment)
    policy_bytes, subject_bytes = read(a.policy), read(a.subject)
    # Validate all operands before any write. Computation has no external effects.
    ver = byte_check(policy_bytes, subject_bytes, obj)
    dst = st.path("runs", c)
    try:
        write_new(dst, canonical({"type": RUN_TYPE, "commitment": c, "state": "RESERVED"}))
    except FileExistsError:
        raise Refused("RUN_EXISTS_NEVER_OVERWRITE")
    # A crash leaves RESERVED; report never turns it into completed work.
    put_operand(st, policy_bytes)
    put_operand(st, subject_bytes)
    rec = {"type": RUN_TYPE, "commitment": c, "state": "COMPLETE", "profile": BYTE_PROFILE,
           "closure_sha256": sha(policy_bytes), "subject_sha256": sha(subject_bytes), "verification": ver}
    # Only the exclusive reservation owner reaches this publication step.
    fd, name = tempfile.mkstemp(prefix=".run-", dir=dst.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical(rec)); f.flush(); os.fsync(f.fileno())
        os.replace(name, dst)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print(json.dumps({"commitment": c, **ver}))
    return 0


# ---------------------------------------------------------------- holder ---

def _ed25519():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
    return Ed25519PrivateKey, Ed25519PublicKey, serialization, InvalidSignature


def cmd_keygen(a):
    Priv, _, ser, _ = _ed25519()
    k = Priv.generate()
    raw = k.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())
    pub = k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
    p = Path(a.out)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw.hex() + "\n")
    print(json.dumps({"pubkey_hex": pub.hex(), "secret_file": str(p)}))
    return 0


def receipt_body(holder, c, holder_head, observed):
    return {"type": RECEIPT_TYPE, "holder": holder, "commitment": c,
            "holder_head": holder_head, "observed": observed}


def receipt_message(body) -> bytes:
    return RECEIPT_DOMAIN + hashlib.sha256(canonical(body)).digest()


def cmd_receive(a):
    """HOLDER side. Re-hash the received bytes, keep them, write a signed
    receipt into the holder's own store. holder_head chains the holder's
    receipts so a holder's store is itself an append-only line."""
    Priv, _, _, _ = _ed25519()
    b = read(a.commitment_file)
    c = sha(b)
    validate_commitment(parse(b))
    H = Path(a.holder_store)
    write_new(H / "commitments" / f"{c}.json", b)
    heads = sorted((H / "receipts").glob("*.json")) if (H / "receipts").exists() else []
    head = read(H / "head").decode().strip() if (H / "head").exists() else None
    need(head is None or hex64(head), "HOLDER_HEAD")
    body = receipt_body(a.holder_id, c, head, a.observed)
    sk = Priv.from_private_bytes(bytes.fromhex(read(a.key).decode().strip()))
    sig = sk.sign(receipt_message(body)).hex()
    rec = dict(body, sig_hex=sig)
    rb = canonical(rec)
    write_new(H / "receipts" / f"{c}.json", rb)
    (H / "head").write_text(sha(rb) + "\n")
    print(json.dumps({"holder": a.holder_id, "commitment": c, "receipt_sha256": sha(rb),
                      "prior_receipts": len(heads)}))
    return 0


def verify_receipt(rec_bytes: bytes, pubkey_hex: str) -> dict:
    _, Pub, _, InvalidSignature = _ed25519()
    rec = parse(rec_bytes)
    need(isinstance(rec, dict) and set(rec) == {"type", "holder", "commitment", "holder_head", "observed", "sig_hex"},
         "RECEIPT_SHAPE")
    need(rec["type"] == RECEIPT_TYPE and hex64(rec["commitment"]), "RECEIPT_TYPE")
    need(rec["holder_head"] is None or hex64(rec["holder_head"]), "RECEIPT_HEAD")
    body = {k: rec[k] for k in ("type", "holder", "commitment", "holder_head", "observed")}
    try:
        Pub.from_public_bytes(bytes.fromhex(pubkey_hex)).verify(bytes.fromhex(rec["sig_hex"]), receipt_message(body))
    except (InvalidSignature, ValueError) as e:
        raise Refused("RECEIPT_SIG") from e
    return rec


# ---------------------------------------------------------------- report ---

def parse_holders(data) -> list:
    cfg = parse(data)
    need(isinstance(cfg, dict) and set(cfg) == {"holders"} and isinstance(cfg["holders"], list), "HOLDERS_SHAPE")
    out = []
    for h in cfg["holders"]:
        need(isinstance(h, dict) and set(h) == {"id", "pubkey_hex", "store", "custody"}, "HOLDER_SHAPE")
        need(hex64(h["pubkey_hex"]), "HOLDER_PUBKEY")
        need(isinstance(h["store"], str) and Path(h["store"]).is_absolute(), "HOLDER_STORE_ABSOLUTE")
        out.append(h)
    return out



def load_holders(path) -> list:
    return parse_holders(read(path))


def walk_path(local_c: str, local_obj: dict, cj: str, sources: list, inputs: dict, max_steps: int) -> dict:
    """Verify prev-links from C_j back to local C_i, one link at a time.
    Every link: bytes hash to their address, stream equal, sequence == child-1.
    Returns {"outcome": ..., "steps": n, "path": [...]}."""
    def fetch(c):
        for base in sources:
            p = Path(base) / "commitments" / f"{c}.json"
            if p.exists():
                b = read(p)
                inputs[str(p)] = sha(b)
                need(sha(b) == c, f"LINK_TAMPERED:{c[:12]}")
                return validate_commitment(parse(b))
        return None
    cur_c, path = cj, [cj]
    cur = fetch(cur_c)
    if cur is None:
        return {"outcome": "PATH_INCOMPLETE", "steps": 0, "path": path, "missing": cur_c}
    if cur["stream"] != local_obj["stream"]:
        return {"outcome": "DISCONNECTED", "steps": 0, "path": path, "why": "stream"}
    steps = 0
    while True:
        if steps >= max_steps:
            return {"outcome": "PATH_BOUND_EXCEEDED", "steps": steps, "path": path}
        if cur["sequence"] <= local_obj["sequence"]:
            return {"outcome": "DISCONNECTED", "steps": steps, "path": path, "why": "sequence_reached_without_meeting_local"}
        if cur["prev"] is None:
            return {"outcome": "DISCONNECTED", "steps": steps, "path": path, "why": "genesis_reached"}
        if cur["prev"] == local_c:
            if cur["sequence"] != local_obj["sequence"] + 1:
                return {"outcome": "DISCONNECTED", "steps": steps, "path": path, "why": "sequence_gap_at_local"}
            path.append(local_c)
            return {"outcome": "COMPLETE", "steps": steps + 1, "path": path}
        try:
            prev = fetch(cur["prev"])
        except Refused as e:
            return {"outcome": "LINK_TAMPERED", "steps": steps, "path": path, "why": str(e)}
        if prev is None:
            return {"outcome": "PATH_INCOMPLETE", "steps": steps, "path": path, "missing": cur["prev"]}
        if prev["stream"] != local_obj["stream"] or prev["sequence"] != cur["sequence"] - 1:
            return {"outcome": "DISCONNECTED", "steps": steps, "path": path, "why": "link_inconsistent"}
        path.append(cur["prev"])
        cur_c, cur = cur["prev"], prev
        steps += 1


def build_report(store, c: str, holders_cfg, max_steps=MAX_PATH_STEPS) -> dict:
    need(type(max_steps) is int and 1 <= max_steps <= MAX_PATH_STEPS, "PATH_LIMIT")
    st = Store(store)
    inputs = {}
    cpath = st.path("commitments", c)
    cb = read(cpath)
    inputs[str(cpath)] = sha(cb)
    need(sha(cb) == c, "COMMITMENT_PIN")
    obj = validate_commitment(parse(cb))
    need(canonical(obj) == cb, "NOT_CANONICAL")

    # Old run records are untrusted claims. The bounded profile is replayed
    # from pinned operands; no result string or claimed historical execution is trusted.
    ver = {"method": "EXTERNAL_CLOSURE", "result": "NOT_RUN", "scope": None}
    rp = st.path("runs", c)
    if rp.exists():
        rb = read(rp)
        inputs[str(rp)] = sha(rb)
        run = parse(rb)
        need(isinstance(run, dict) and run.get("type") == RUN_TYPE and run.get("commitment") == c, "RUN_RECORD")
        if run.get("state") == "RESERVED":
            ver["note"] = "RUN_INCOMPLETE"
        elif run.get("profile") != BYTE_PROFILE:
            ver["note"] = "UNVERIFIED_LEGACY_RUN_CLAIM"
        else:
            need(set(run) == {"type", "commitment", "state", "profile", "closure_sha256", "subject_sha256", "verification"}
                 and run["state"] == "COMPLETE"
                 and run["closure_sha256"] == obj["verifier"]["closure_sha256"]
                 and run["subject_sha256"] == obj["subject"]["sha256"], "RUN_BINDING")
            operands = []
            for digest in [run["closure_sha256"], run["subject_sha256"]]:
                op = st.path("operands", digest, "bin")
                data = read(op); inputs[str(op)] = sha(data)
                need(sha(data) == digest, "OPERAND_PIN")
                operands.append(data)
            ver = byte_check(*operands, obj)
            need(canonical(ver) == canonical(run["verification"]), "RUN_RESULT_DIVERGED")
            ver = {**ver, "basis": "REPLAYED_NOW_NOT_HISTORICAL_ATTESTATION"}

    # time: from the initial receipt (and the upgraded copy if present)
    time_axis = {"status": "NONE"}
    for ext in ("upgraded.ots", "ots"):
        pp = st.path("proofs", c, ext)
        if pp.exists():
            pb = read(pp)
            inputs[str(pp)] = sha(pb)
            time_axis = classify_ots(cb, pb)
            time_axis["proof"] = ext
            break

    # holding + freshness, per configured holder; nothing else is consulted
    holdings, fresh = [], {"status": "UNKNOWN", "notes": []}
    for h in holders_cfg:
        H = Path(h["store"])
        entry = {"holder": h["id"], "custody": h["custody"], "status": "NONE"}
        rdir = H / "receipts"
        if not rdir.is_dir():
            entry["note"] = "STORE_UNAVAILABLE"
            holdings.append(entry)
            fresh["notes"].append({"holder": h["id"], "outcome": "STORE_UNAVAILABLE"})
            continue
        verified = {}
        for rp_ in sorted(rdir.glob("*.json")):
            rb_ = read(rp_)
            inputs[str(rp_)] = sha(rb_)
            try:
                rec = verify_receipt(rb_, h["pubkey_hex"])
                need(rec["holder"] == h["id"], "RECEIPT_HOLDER")
            except Refused as e:
                fresh["notes"].append({"holder": h["id"], "receipt": rp_.name, "outcome": "RECEIPT_REFUSED", "why": str(e)})
                continue
            need(rp_.name == rec["commitment"] + ".json", "RECEIPT_FILENAME")
            verified[rec["commitment"]] = rec
        if c in verified:
            entry["status"] = "EXTERNALLY_OBSERVED"
            entry["receipt_sha256"] = inputs[str(rdir / f"{c}.json")]
        holdings.append(entry)
        # freshness: candidates are receipts for commitments on the same stream with a larger sequence
        cands = []
        for cj in verified:
            if cj == c:
                continue
            p = H / "commitments" / f"{cj}.json"
            if not p.exists():
                fresh["notes"].append({"holder": h["id"], "candidate": cj, "outcome": "PATH_INCOMPLETE", "missing": cj})
                continue
            b = read(p)
            inputs[str(p)] = sha(b)
            if sha(b) != cj:
                fresh["notes"].append({"holder": h["id"], "candidate": cj, "outcome": "LINK_TAMPERED"})
                continue
            try:
                o = validate_commitment(parse(b))
            except Refused as e:
                fresh["notes"].append({"holder": h["id"], "candidate": cj, "outcome": "RECEIPT_REFUSED", "why": str(e)})
                continue
            if o["stream"] == obj["stream"] and o["sequence"] > obj["sequence"]:
                cands.append((o["sequence"], cj))
        for _, cj in sorted(cands, reverse=True):
            try:
                w = walk_path(c, obj, cj, [H, st.root], inputs, max_steps)
            except Refused as e:
                w = {"outcome": "LINK_TAMPERED", "why": str(e), "path": [cj], "steps": 0}
            fresh["notes"].append({"holder": h["id"], "candidate": cj, **w})
            if w["outcome"] == "COMPLETE" and fresh["status"] == "UNKNOWN":
                fresh = {"status": "LATER_STATE_WITNESSED", "holder": h["id"],
                         "path": f"{c[:12]}->{cj[:12]}", "steps": w["steps"], "notes": fresh["notes"]}
    return {"type": REPORT_TYPE, "commitment": c, "stream": obj["stream"], "sequence": obj["sequence"],
            "verification": ver, "time": time_axis, "holding": holdings, "freshness": fresh,
            "adoption": "NOT_EVALUATED", "authority": "none", "network_calls": 0,
            "inputs_sha256": dict(sorted(inputs.items())),
            "evaluation": {"tool_sha256": checker_sha256(), "max_path_steps": max_steps,
                           "holders_value_sha256": sha(canonical(holders_cfg))}}


def cmd_report(a):
    config_bytes = read(a.holders)
    holders = parse_holders(config_bytes)
    rep = build_report(a.store, a.commitment, holders, a.max_path)
    rep["inputs_sha256"][str(Path(a.holders))] = sha(config_bytes)
    rep["holder_config_sha256"] = sha(config_bytes)
    print(json.dumps(rep, sort_keys=True, indent=None if a.compact else 1))
    return 0


# ------------------------------------------------------------------- cli ---

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("commit"); p.set_defaults(fn=cmd_commit)
    p.add_argument("--store", required=True); p.add_argument("--subject-kind", required=True)
    p.add_argument("--subject-sha256", required=True); p.add_argument("--verifier-closure-sha256", required=True)
    p.add_argument("--stream"); p.add_argument("--prev")

    for name, fn in (("stamp", cmd_stamp), ("upgrade", cmd_upgrade)):
        p = sp.add_parser(name); p.set_defaults(fn=fn)
        p.add_argument("--store", required=True); p.add_argument("--commitment", required=True)
        p.add_argument("--ots", default="ots")

    p = sp.add_parser("classify"); p.set_defaults(fn=cmd_classify)
    p.add_argument("--store", required=True); p.add_argument("--commitment", required=True)
    p.add_argument("--ext", default="ots")

    p = sp.add_parser("run-verifier"); p.set_defaults(fn=cmd_run_verifier)
    p.add_argument("--store", required=True); p.add_argument("--commitment", required=True)
    p.add_argument("--script"); p.add_argument("--cwd")
    p.add_argument("--policy"); p.add_argument("--subject")
    p.add_argument("--method", choices=("EXTERNAL_CLOSURE", "SELF_REFERENTIAL"), default="EXTERNAL_CLOSURE")
    p.add_argument("--scope"); p.add_argument("args", nargs="*")

    p = sp.add_parser("keygen"); p.set_defaults(fn=cmd_keygen); p.add_argument("--out", required=True)

    p = sp.add_parser("receive"); p.set_defaults(fn=cmd_receive)
    p.add_argument("--holder-store", required=True); p.add_argument("--holder-id", required=True)
    p.add_argument("--key", required=True); p.add_argument("--commitment-file", required=True)
    p.add_argument("--observed", required=True)

    p = sp.add_parser("report"); p.set_defaults(fn=cmd_report)
    p.add_argument("--store", required=True); p.add_argument("--commitment", required=True)
    p.add_argument("--holders", required=True); p.add_argument("--max-path", type=int, default=MAX_PATH_STEPS)
    p.add_argument("--compact", action="store_true")

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except Refused as e:
        print(json.dumps({"status": "REFUSED", "reason": str(e), "authority": "none"}))
        return 2
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as e:
        print(json.dumps({"status": "REFUSED", "reason": type(e).__name__, "authority": "none"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
