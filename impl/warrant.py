#!/usr/bin/env python3
"""Warrant v0.3 — reference implementation (plain-file store, five filing verbs, conformance, settlement-grade verification and key state).

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
# SPEC §3.1: re-executing a stranger's ski@v1 reason is safe by construction
# (terminating, work+memory bounded by atp), but the atp ceiling is uint32
# (~4.3e9). A verifier re-running arbitrary strangers' checks caps the work it
# will spend so a pathological-but-legal atp cannot be a DoS. Over the cap, the
# reason is reported as *unverified* (a WARN, never a silent skip and never a
# verdict). Both implementations ship the SAME default so they agree by default;
# operators MAY raise it (SPEC §3.1) accepting the divergence that implies.
SKI_REEXEC_MAX_ATP = int(os.environ.get("WARRANT_SKI_MAX_ATP", 100_000_000))
BODY_FIELDS = {"warrant", "decision", "subject", "under", "because",
               "evidence", "actor", "prior", "ts"}
RUNTIMES = {"0.1": ("cmd@v1",),            # ski@v1 reserved in 0.1 bodies
            "0.2": ("cmd@v1", "ski@v1")}   # SPEC s3.1

# Runtime dispatch registry (generic plumbing, empty by default). Keyed by an
# EXACT (body_version, reason_runtime) so a handler runs ONLY for a shape-valid
# check reason whose body version authorizes that runtime — never for every store
# (Codex refactor gate: a global list could change a legacy 0.1/0.2 store's result
# merely by being installed). The handler receives the SINGLE settlement context,
# the SINGLE record snapshot, a verifier-owned `mode`, the reporter, and the
# reason-bearing record — but NOT the raw `settlement` inputs, so it cannot build
# a second authority. Empty here: no non-core runtime is registered.
_RUNTIME_HANDLERS = {}
# Core runtimes are executed by the base verifier and MUST NOT be overlaid by a
# registered handler (Codex refactor recheck): otherwise installing a handler for
# ("0.2","cmd@v1")/("0.2","ski@v1") would change a legacy store's report.
_CORE_RUNTIMES = frozenset({"cmd@v1", "ski@v1"})


def register_runtime(body_version, runtime, handler):
    """Register a handler for exactly (body_version, runtime). Refuses duplicates
    and refuses to overlay a core runtime. `runtime` MUST already be allowed by
    RUNTIMES[body_version] (a handler cannot smuggle in an unversioned runtime)."""
    if runtime in _CORE_RUNTIMES:
        raise ValueError(f"cannot overlay core runtime {runtime!r}")
    key = (body_version, runtime)
    if key in _RUNTIME_HANDLERS:
        raise ValueError(f"runtime handler already registered for {key}")
    if runtime not in RUNTIMES.get(body_version, ()):
        raise ValueError(f"runtime {runtime!r} not authorized by body version {body_version!r}")
    _RUNTIME_HANDLERS[key] = handler


class _RuntimeView:
    """Read-only execution context for a REGISTERED runtime handler.

    Trust model (stated, per Codex item-0 recheck): a registered handler is
    GOVERNED verifier-extension code — part of the TCB. In-process Python cannot
    be a security sandbox against malicious extension code. What this view DOES
    guarantee is that it retains **no reference to the verifier's live record map
    or raw store**, so accidental (or private-attribute) mutation by a handler
    cannot corrupt core verification or crash the record loop; and that blob bytes
    are reached only through a digest-authenticating resolver whose usage counter
    is **verifier-owned** (not an attribute on this object). All record access
    returns deep copies of a private snapshot taken before dispatch. An
    adversarial-plugin model would require a real process/WASM boundary (out of
    scope for item 0)."""
    __slots__ = ("_bodies", "_active", "_roots", "_blob")

    def __init__(self, bodies, active, roots, blob):
        self._bodies = bodies      # {wid: deep-copied body} — a PRIVATE snapshot
        self._active = active      # frozenset | None
        self._roots = roots        # {wid: frozenset} | None
        self._blob = blob          # bound resolver (verifier-owned counter closure)

    def blob(self, h):
        """Blob bytes iff they hash to `h`, else None — the only path to store
        bytes. Every attempted read (incl. wrong-digest) is counted by the
        verifier-owned meter."""
        return self._blob(h)

    def record_body(self, wid):
        """A deep COPY of a record body, or None. Mutating it cannot affect
        verification (and the underlying snapshot is not the verifier's live map)."""
        b = self._bodies.get(wid) if isinstance(wid, str) else None
        return json.loads(json.dumps(b)) if b is not None else None

    def warrant_ids(self):
        return frozenset(self._bodies)

    def active_records(self):
        return self._active                             # frozenset | None (base mode)

    def record_roots(self, wid):
        return self._roots.get(wid, frozenset()) if self._roots else frozenset()

WARN_RELITIGATION = "re-litigation cites nothing new"
WARN_UNADOPTED_ROOT = "unadopted root"
WARN_GENESIS_UNVERIFIED = "genesis.json unverified"
ERR_INVALID_THRESHOLD = "invalid threshold policy"
WARN_KEY_CONFLICT = "key-state conflict"
# One STABLE cross-language reason (Codex refactor gate): a REQUESTED settlement
# verification whose supplied trust config is missing/unreadable/malformed/schema-
# invalid is one global ERR with this exact string in BOTH Python and Go — never
# a silent fail-open (Go previously ignored the read error and returned 0 errors).
ERR_SETTLEMENT_TRUST = "settlement trust config unavailable"


# ---------- canonicalization & identity (SPEC §4) ----------
def canon(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _reject_dup_keys(pairs):
    """object_pairs_hook enforcing I-JSON (SPEC §4): duplicate member names are
    invalid. Stock parsers silently keep the last — a canonicalization attack
    surface and a split against any strict I-JSON reimplementation. Raise so
    ingestion treats a dup-key object as malformed, not last-wins."""
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"duplicate member name: {k}")
        d[k] = v
    return d


def _reject_constant(sym):
    # I-JSON / RFC 7493: NaN, Infinity, -Infinity are not valid JSON. Python's
    # stock json.loads accepts them by default (Go's decoder rejects them), so a
    # pinned genesis/trust value could activate a root in Python but not Go —
    # reject them so both share one actual I-JSON domain.
    raise ValueError(f"invalid I-JSON constant: {sym}")


def _reject_lone_surrogates(obj):
    """RFC 7493 I-JSON: every string is valid Unicode — no unpaired surrogates.
    Python's json keeps a lone-surrogate escape (``\\ud800``) as a surrogate
    code point in the resulting str; Go's decoder substitutes U+FFFD. Left
    unchecked the two implementations parse the SAME bytes into DIFFERENT string
    values, splitting the I-JSON domain (observably: a record/trust actor id with
    a lone surrogate is ``uncomputable`` in Python but a distinct recomputed id
    in Go). Reject in both so a lone surrogate is uniformly malformed. A valid
    surrogate PAIR (``\\ud800\\udc00``) is combined by json.loads into a single
    non-surrogate code point and is left untouched — only unpaired ones raise."""
    if isinstance(obj, str):
        if any(0xD800 <= ord(c) <= 0xDFFF for c in obj):
            raise ValueError("lone surrogate in string (invalid I-JSON)")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _reject_lone_surrogates(k)
            _reject_lone_surrogates(v)
    elif isinstance(obj, list):
        for v in obj:
            _reject_lone_surrogates(v)
    return obj


def loads_ijson(raw):
    """json.loads restricted to I-JSON: rejects duplicate member names, the
    non-JSON constants NaN/Infinity/-Infinity, AND unpaired surrogates in any
    string or member name (SPEC §4 / RFC 7493)."""
    return _reject_lone_surrogates(
        json.loads(raw, object_pairs_hook=_reject_dup_keys,
                   parse_constant=_reject_constant))


def _canon_eq(doc, raw):
    """``canon(doc) == raw``, but a doc carrying a lone surrogate (which canon
    cannot UTF-8 encode) counts as NON-canonical rather than raising. The CAS
    blob round-trip paths below (policy blob, canonical JSON blob, ski check
    blob) use PLAIN ``json.loads`` — which keeps lone surrogates, unlike
    ``loads_ijson`` which rejects them — so they must treat an un-encodable doc
    as simply not matching its raw bytes. This matches Go, whose decoder
    substitutes U+FFFD and then fails the identical canon comparison: both reach
    a bounded "not canonical" outcome instead of a Python-only crash."""
    try:
        return canon(doc) == raw
    except (UnicodeEncodeError, ValueError):
        return False


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
    if (not isinstance(b["ts"], int) or isinstance(b["ts"], bool)
            or not (0 <= b["ts"] <= 9223372036854775807)):
        e.append("ts must be an integer (unix seconds) in 0..2^63-1")
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
    """Protocol rule (SPEC §3): a reject whose every reason is prose.

    Shape-defensive: called from the verifier on possibly schema-invalid
    records, so a type-confused `because` (non-list, or non-dict entries)
    must yield False rather than raise (Kimi full-audit, 2026-07)."""
    because = body.get("because") if isinstance(body, dict) else None
    if not isinstance(because, list) or not because:
        return False
    return (body.get("decision") == "reject"
            and all(isinstance(r, dict) and r.get("kind") == "prose" for r in because))


# ---------- ski@v1 runtime (SPEC §3.1, v0.2) ----------
def load_sigma():
    """Load the Σ-GLYPH Book I oracle. Search order (first hit wins):
      1. $SIGMA_GLYPH/sigma_glyph.py   — explicit override (e.g. a dev checkout)
      2. sigma_glyph.py next to this file — the BUNDLED oracle, so an installed
         `warrant` re-runs ski@v1 reasons offline with no separate clone
      3. ~/sigma-glyph/impl/sigma_glyph.py — a conventional local checkout
    Returns the module or None (None -> ski@v1 reasons report as unverified)."""
    import importlib.util
    candidates = []
    if os.environ.get("SIGMA_GLYPH"):
        candidates.append(Path(os.environ["SIGMA_GLYPH"]) / "sigma_glyph.py")
    candidates.append(Path(__file__).resolve().parent / "sigma_glyph.py")
    candidates.append(Path.home() / "sigma-glyph/impl" / "sigma_glyph.py")
    for path in candidates:
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location("sigma_glyph", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return None


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
        raise RuntimeError("runtime unavailable")   # reason class; the CLI hint
    p = store.blobs / check_hex                       # is printed by cmd_check, not here
    if not (isinstance(check_hex, str) and HEX64.match(check_hex) and p.is_file()):
        raise RuntimeError("check blob missing")      # absent / dir / non-hex: bounded
    raw = p.read_bytes()
    try:
        doc = json.loads(raw)                # was leaking JSONDecodeError past the
    except ValueError:                       # caller's `except RuntimeError` (crash)
        raise RuntimeError("malformed check blob (not JSON)")
    if not _canon_eq(doc, raw):
        raise RuntimeError("malformed check blob (not JCS-canonical)")
    err = validate_ski_blob(doc)
    if err:
        raise RuntimeError(f"invalid ski check blob: {err}")
    if doc["atp"] > SKI_REEXEC_MAX_ATP:   # SPEC §3.1: local re-execution budget
        raise RuntimeError("atp exceeds re-execution budget")

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


# SPEC §5: small-order and non-canonical Ed25519 public keys are rejected.
# Such a key lets an ALL-ZERO signature verify for a large fraction of messages
# (small-order forgery), so an attacker mints a "valid signature" attributing a
# decision to any actor id without knowing a secret; and libraries disagree on
# which of these they accept (Python `cryptography` and Go `crypto/ed25519`
# already differ), so the SAME envelope can verify in one impl and not another —
# exactly the consensus split the design rule forbids. The two checks below are
# byte- and integer-only, so every implementation agrees by construction.
_ED25519_P = (1 << 255) - 19
_ED25519_SMALL_ORDER = {bytes.fromhex(h) for h in (
    "0100000000000000000000000000000000000000000000000000000000000000",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
    # non-canonical sign-bit variants of the x=0 torsion points (y=1, y=p-1):
    # current libs reject these at decode; blocklisted as defense-in-depth so a
    # lenient third implementation cannot accept them (Gemini 3.1 Pro audit).
    "0100000000000000000000000000000000000000000000000000000000000080",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
)}


def weak_ed25519_pubkey(raw):
    """True if `raw` (32 bytes) is a small-order or non-canonically-encoded
    Ed25519 public key that a conforming verifier MUST reject (SPEC §5)."""
    if len(raw) != 32 or raw in _ED25519_SMALL_ORDER:
        return True
    y = int.from_bytes(raw, "little") & ((1 << 255) - 1)   # drop the sign bit
    return y >= _ED25519_P                                  # non-canonical y


def verify_sig(wid, sig):
    try:
        key = bytes.fromhex(sig["key"])
        if weak_ed25519_pubkey(key):
            return False
        pk = Ed25519PublicKey.from_public_bytes(key)
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
        # A blob exists only if `h` is a hex64 name AND names a regular file —
        # matching Go (which admits only hex64-named regular files into its blob
        # map). A raw `.exists()` on an attacker-controlled string was a path
        # traversal / existence oracle (`../records`) and returned True for a
        # directory, splitting parity and crashing later reads (Kimi K3 gate).
        return HEX64.match(h) is not None and (self.blobs / h).is_file()

    def put_record(self, env):
        wid = warrant_id(env["body"])
        (self.records / f"{wid}.json").write_text(
            json.dumps(env, indent=2, sort_keys=True) + "\n")
        return wid

    def get_record(self, wid):
        p = self.records / f"{wid}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def all_records(self, load_errors=None):
        """Parse each record independently (Codex v0.3 hardening audit P2):
        a malformed record file MUST NOT abort the whole verifier. Unreadable /
        non-JSON / wrong-top-level-type records are collected in `load_errors`
        (a dict wid -> reason class) and skipped, so verification continues
        over the rest and reports a bounded error count."""
        out = {}
        for p in sorted(self.records.glob("*.json")):
            try:
                raw = p.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                if load_errors is not None:
                    load_errors[p.stem] = "unreadable or invalid UTF-8"
                continue
            try:
                env = loads_ijson(raw)          # SPEC §4: reject duplicate keys
            except ValueError:
                if load_errors is not None:
                    load_errors[p.stem] = "malformed JSON"
                continue
            except RecursionError:
                # Deeply-nested JSON overflows the parser's recursion. A verifier
                # MUST bound this to a report, not a crash (Gemini 3.1 Pro audit,
                # 2026-07: Python raised RecursionError where Go returned cleanly).
                if load_errors is not None:
                    load_errors[p.stem] = "malformed JSON (nesting too deep)"
                continue
            if not isinstance(env, dict) or not isinstance(env.get("body"), dict):
                if load_errors is not None:
                    load_errors[p.stem] = "wrong top-level shape (no body object)"
                continue
            out[p.stem] = env
        return out


# ---------- settlement (SPEC §7, §9, §5.1) ----------
def cited_blobs(body):
    refs = set(body["under"]) | set(body["evidence"]) | {body["subject"]["hash"]}
    for r in body["because"]:
        if r.get("kind") == "check":
            refs.add(r["check"])
            if "transcript" in r:
                refs.add(r["transcript"])
    return refs


def prior_closure(recs, wid):
    seen = set()
    stack = list(recs.get(wid, {}).get("body", {}).get("prior", []))
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in recs:
            continue
        seen.add(cur)
        stack.extend(recs[cur]["body"]["prior"])
    return seen


def tunnel(store, wid, recs=None):
    if recs is None:                    # single-snapshot: callers inside verify_store
        recs = store.all_records()      # MUST thread their loaded recs (no reload)
    records = prior_closure(recs, wid)
    blobs = set()
    for rwid in records:
        blobs.update(cited_blobs(recs[rwid]["body"]))
    return {"records": records, "blobs": blobs}


def _read_json_blob_if_canonical(store, h):
    p = store.blobs / h
    if not p.exists():
        return None
    try:
        raw = p.read_bytes()
        doc = json.loads(raw)
    except Exception:
        return None
    return doc if _canon_eq(doc, raw) else None


def fingerprint(reason, body, store):
    if reason.get("kind") != "check":
        return None
    runtime = reason.get("runtime")
    verdict = reason.get("verdict")
    if runtime == "cmd@v1":
        transcript = reason.get("transcript")
        if not transcript:
            return None
        needed = set(body.get("evidence", [])) | {reason.get("check"), transcript}
        if any(not h or not store.has_blob(h) for h in needed):
            return None
        return ("cmd@v1", tuple(sorted(body.get("evidence", []))), verdict, transcript)
    if runtime == "ski@v1":
        doc = _read_json_blob_if_canonical(store, reason.get("check"))
        if doc is None or validate_ski_blob(doc):
            return None
        try:
            _got, result_hash, _spent = run_ski_check(store, reason["check"])
        except RuntimeError:
            return None
        return ("ski@v1", doc["term"], doc["expect"], verdict, result_hash)
    return None


def tunnel_fingerprints(store, wid, recs=None):
    if recs is None:
        recs = store.all_records()
    fps = set()
    for rwid in tunnel(store, wid, recs)["records"]:
        body = recs[rwid]["body"]
        for r in body["because"]:
            fp = fingerprint(r, body, store)
            if fp is not None:
                fps.add(fp)
    return fps


def settlement_admissibility(store, settling_wid, candidate_body, recs=None):
    errs = validate_body(candidate_body)
    if errs:                       # a schema-invalid candidate is never admissible
        return f"invalid candidate: {errs[0]}"
    if recs is None:
        recs = store.all_records()
    tun = tunnel(store, settling_wid, recs)
    settling_body = recs.get(settling_wid, {}).get("body")
    known_blobs = set(tun["blobs"])
    if settling_body:
        known_blobs.update(cited_blobs(settling_body))
    for h in sorted(candidate_body.get("evidence", [])):
        if h not in known_blobs:
            return "admissible: (a) new evidence"
    old_fps = tunnel_fingerprints(store, settling_wid, recs)
    if settling_body:
        for r in settling_body["because"]:
            fp = fingerprint(r, settling_body, store)
            if fp is not None:
                old_fps.add(fp)
    for r in candidate_body.get("because", []):
        fp = fingerprint(r, candidate_body, store)
        if fp is not None and fp not in old_fps:
            return "admissible: (b) new outcome fingerprint"
    return "inadmissible: cites nothing new"


def _load_trust_config(path):
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


TRUST_FIELDS = {"genesis_roots", "actors", "genesis_json_sha256"}


def _validate_trust_config(doc):
    """Closed-schema validation of a trust config (Codex refactor recheck): the
    fail-closed guard must cover NESTED types, not just top-level JSON shape —
    `{"actors":[]}` or `{"actors":{"a":1}}` previously crashed settlement in
    Python while Go returned 0 errors. Returns None or a stable error string."""
    if not isinstance(doc, dict):
        return "trust config must be a JSON object"
    if set(doc) - TRUST_FIELDS:
        return "trust config has unknown fields"
    gr = doc.get("genesis_roots")
    if gr is not None and not (isinstance(gr, list) and all(_is_hex64(x) for x in gr)):
        return "genesis_roots must be a list of hex64"
    ac = doc.get("actors")
    if ac is not None:
        if not isinstance(ac, dict):
            return "actors must be an object"
        for a, keys in ac.items():
            if not (isinstance(a, str) and a):
                return "actors keys must be nonempty actor-id strings"
            if not (isinstance(keys, list) and all(_is_hex64(k) for k in keys)):
                return "each actor's keys must be a list of hex64"
    gh = doc.get("genesis_json_sha256")
    if gh is not None and not _is_hex64(gh):
        return "genesis_json_sha256 must be hex64"
    return None


def _trust_roots(store, trust, explicit_roots):
    roots = set(explicit_roots or []) | set(trust.get("genesis_roots", []))
    warnings = []
    g = store.root / "genesis.json"
    if g.exists():
        try:
            raw = g.read_bytes()                        # read ONCE
        except OSError:
            raw = None                                  # present but unreadable (e.g. a dir)
        if raw is not None and trust.get("genesis_json_sha256") == blob_hash(raw):
            # Parse the EXACT bytes whose digest was checked (no second read):
            # a hash-pinned input must not have a read_bytes/read_text TOCTOU that
            # lets a swapped value inject an attacker root (Codex item-0 recheck).
            try:
                doc = loads_ijson(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                doc = {}
            # Total genesis schema: `roots` may be absent, null, or a scalar in a
            # hostile pinned file — iterate ONLY a list (matching Go's
            # getStringArray, which yields nothing for a non-list), so an invalid
            # shape is a bounded no-op in both, never a Python traceback.
            if isinstance(doc, dict) and isinstance(doc.get("roots"), list):
                roots.update(r for r in doc["roots"] if _is_hex64(r))
        else:
            warnings.append(("store", WARN_GENESIS_UNVERIFIED))
    return roots, warnings


def _parse_policy_blob(store, h):
    p = store.blobs / h
    if not (isinstance(h, str) and HEX64.match(h) and p.is_file()):
        return None, False                          # absent / dir / non-hex: not a policy
    raw = p.read_bytes()
    try:
        doc = json.loads(raw)
    except Exception:
        return None, False
    if not isinstance(doc, dict) or doc.get("warrant_policy") != "0.3":
        return None, False
    if not _canon_eq(doc, raw):
        return None, True
    if set(doc) != {"warrant_policy", "threshold"}:
        return None, True
    th = doc.get("threshold")
    if not isinstance(th, dict) or set(th) != {"min_sigs", "actors"}:
        return None, True
    actors = th.get("actors")
    min_sigs = th.get("min_sigs")
    if (not isinstance(min_sigs, int) or isinstance(min_sigs, bool)
            or not isinstance(actors, list) or not actors
            or not all(isinstance(a, str) and a for a in actors)
            or len(set(actors)) != len(actors)
            or min_sigs < 1 or min_sigs > len(actors)):
        return None, True
    return {"min_sigs": min_sigs, "actors": actors}, False


def _record_policy(store, body):
    valid = []
    invalid = False
    for h in body.get("under", []):
        policy, bad = _parse_policy_blob(store, h)
        invalid = invalid or bad
        if policy:
            valid.append(policy)
    return valid, invalid


def _iter_sigs(env):
    """Yield only well-formed dict signature entries so callers can .get()
    safely (envelope sigs are attacker-shaped; a non-list or a non-dict entry
    must not crash settlement math). Gemini 3.1 Pro audit, 2026-07."""
    s = env.get("sigs")
    return [x for x in s if isinstance(x, dict)] if isinstance(s, list) else []


def _valid_sig_actors(wid, env, allowed_keys=None):
    actors = set()
    for s in _iter_sigs(env):
        if not verify_sig(wid, s):
            continue
        actor = s.get("actor")
        if allowed_keys is not None:
            if s.get("key") not in allowed_keys.get(actor, set()):
                continue
        actors.add(actor)
    return actors


def _threshold_satisfied(wid, env, policy, keys=None, conflicted=frozenset()):
    actors = [a for a in policy["actors"] if a not in conflicted]
    if not actors:
        return False
    min_sigs = min(policy["min_sigs"], len(actors))
    signers = _valid_sig_actors(wid, env, keys)
    return len(set(actors) & signers) >= min_sigs


def _policies_satisfied(store, wid, env, keys=None, conflicted=frozenset()):
    policies, invalid = _record_policy(store, env["body"])
    if invalid:
        return False
    if not policies:
        return any(verify_sig(wid, s) for s in _iter_sigs(env))
    return all(_threshold_satisfied(wid, env, p, keys, conflicted) for p in policies)


def _parse_key_blob(store, h):
    doc = _read_json_blob_if_canonical(store, h)
    if (isinstance(doc, dict) and set(doc) == {"actor", "key"}
            and isinstance(doc["actor"], str) and _is_hex64(doc["key"])):
        return doc["actor"], doc["key"]
    return None


def _well_signed(wid, env):
    """SPEC s9: schema-valid and carrying a valid signature by body.actor.id —
    the eligibility gate for settlement-active roots (and active records)."""
    if validate_body(env.get("body", {})):
        return False
    return any(verify_sig(wid, s) and s.get("actor") == env["body"]["actor"]["id"]
               for s in _iter_sigs(env))


def _settlement_context(store, trust_config=None, genesis_roots=None, recs=None, trust=None):
    # Single-snapshot rule (Codex refactor gate): callers that have already
    # loaded the records MUST pass them, so base verification, active-set
    # derivation, key state, and any runtime dispatcher all reason over ONE
    # immutable observation of the store (no TOCTOU between two all_records reads).
    if recs is None:
        recs = store.all_records()
    # Single trust-parse rule: verify_store parses AND validates the trust config
    # once and passes the validated VALUE, so the bytes that pass the fail-closed
    # guard are exactly the bytes that define authority (no trust TOCTOU / no
    # nested-invalid escape). Legacy callers that pass only a path still work.
    if trust is None:
        trust = _load_trust_config(trust_config)
    genesis, global_warnings = _trust_roots(store, trust, genesis_roots)
    roots = {wid for wid, env in recs.items() if not env["body"].get("prior")}
    well = {wid for wid, env in recs.items() if _well_signed(wid, env)}
    # SPEC s9: a root is eligible for settlement-active only if well-signed;
    # a trusted-but-broken root is reported under s6 and excluded here
    active_roots = set(genesis) & well

    invalid_policy = set()
    for wid, env in recs.items():
        _policies, bad = _record_policy(store, env["body"])
        if bad:
            invalid_policy.add(wid)

    def record_roots(wid):
        # iterative + cycle-safe + shape-defensive (Codex v0.3 hardening audit
        # P1): a `prior` cycle must never crash the verifier with unbounded
        # recursion, and a malformed body must not be dereferenced as valid.
        roots, seen, stack = set(), set(), [wid]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            env = recs.get(cur)
            body = env.get("body") if isinstance(env, dict) else None
            if not isinstance(body, dict):
                continue
            prior = body.get("prior")
            if not isinstance(prior, list):
                continue                          # malformed shape: not a root, no edges
            if not prior:
                roots.add(cur)
            else:
                stack.extend(p for p in prior if isinstance(p, str))
        return roots

    genesis_keys = {a: set(keys) for a, keys in trust.get("actors", {}).items()}
    ancestors_cache = {}

    def ancestors(wid):
        if wid not in ancestors_cache:
            ancestors_cache[wid] = prior_closure(recs, wid)
        return ancestors_cache[wid]

    def depth(wid):
        return len(ancestors(wid))

    rotation_cache = {}
    keys_cache = {}
    rotation_auth_cache = {}

    def rotation(wid):
        if wid not in rotation_cache:
            env = recs.get(wid)
            rotation_cache[wid] = None
            # Shape-defensive: rotation() is called for every ancestor in a
            # record's prior-closure, and an ancestor may be schema-invalid
            # (e.g. missing "decision"/"subject"). Dereferencing it as a valid
            # body crashed settlement with a KeyError when an ACTIVE record had
            # a malformed ancestor (Kimi full-audit, 2026-07). A malformed
            # ancestor simply carries no rotation.
            body = env.get("body") if isinstance(env, dict) else None
            if isinstance(body, dict) and body.get("decision") == "accept":
                subj = body.get("subject")
                if isinstance(subj, dict) and isinstance(subj.get("hash"), str):
                    rotation_cache[wid] = _parse_key_blob(store, subj["hash"])
        return rotation_cache[wid]

    def keys_before(wid):
        if wid in keys_cache:
            return {a: set(v) for a, v in keys_cache[wid].items()}
        keys = {a: set(v) for a, v in genesis_keys.items()}
        for awid in sorted(ancestors(wid), key=lambda x: (depth(x), x)):
            rot = rotation(awid)
            if rot and rotation_authorized(awid):
                keys[rot[0]] = {rot[1]}
        keys_cache[wid] = {a: set(v) for a, v in keys.items()}
        return keys

    def threshold_keys(wid):
        """SPEC s5.1/s9: for settlement-grade thresholds a signature counts
        for an actor only if made by a key currently bound to that actor at
        this warrant's DAG position; actors with NO configured key state
        contribute nothing (unbound claims MUST NOT satisfy a v0.3 threshold)."""
        return keys_before(wid)

    def rotation_authorized(wid):
        if wid in rotation_auth_cache:
            return rotation_auth_cache[wid]
        rotation_auth_cache[wid] = False
        env = recs[wid]
        rot = rotation(wid)
        if not rot or wid in invalid_policy or wid not in active_records:
            return False
        actor, incoming = rot
        proof = any(verify_sig(wid, s) and s.get("actor") == actor
                    and s.get("key") == incoming for s in _iter_sigs(env))
        if not proof:
            return False
        prior_keys = keys_before(wid)
        policies, bad = _record_policy(store, env["body"])
        if bad:
            return False
        if policies:
            ok = all(_threshold_satisfied(wid, env, p, prior_keys) for p in policies)
        else:
            ok = any(verify_sig(wid, s) and s.get("actor") == actor
                     and s.get("key") in prior_keys.get(actor, set())
                     for s in _iter_sigs(env))
        rotation_auth_cache[wid] = ok
        return ok

    # Fixpoint: adoption thresholds count only keys bound at the adopting
    # warrant's DAG position (SPEC s5.1/s9); key state depends on the active
    # set, so iterate to stability. Roots and adopting records must be
    # well-signed (s9).
    active_records = set()
    while True:
        active_records = {wid for wid in recs
                          if record_roots(wid) & active_roots
                          and wid not in invalid_policy and wid in well}
        keys_cache.clear()
        rotation_auth_cache.clear()
        grew = False
        for root in sorted(roots - active_roots):
            if root not in well:
                continue
            for wid, env in sorted(recs.items()):
                body = env["body"]
                if (wid in active_records
                        and body["decision"] == "accept"
                        and body["subject"]["hash"] == root
                        and _policies_satisfied(store, wid, env,
                                                keys=threshold_keys(wid))):
                    active_roots.add(root)
                    grew = True
                    break
        if not grew:
            break

    authorized_rotations = {}
    for wid in sorted(active_records, key=lambda x: (depth(x), x)):
        rot = rotation(wid)
        if rot and rotation_authorized(wid):
            authorized_rotations.setdefault(rot[0], set()).add(wid)

    conflict_actors = set()
    for actor, wids in authorized_rotations.items():
        maximal = set(wids)
        for a in wids:
            for b in wids:
                if a != b and a in ancestors(b):
                    maximal.discard(a)
        if len(maximal) > 1:
            conflict_actors.add(actor)

    return {
        "recs": recs,
        "roots": roots,
        "active_roots": active_roots,
        "active_records": active_records,
        "invalid_policy": invalid_policy,
        "global_warnings": global_warnings,
        "keys_before": keys_before,
        "conflict_actors": conflict_actors,
        "record_roots": record_roots,
    }


# ---------- verification (SPEC §6) ----------
def verify_store(store, quiet=False, settlement=None, report_out=None):
    """Return (n_errors, n_warnings). Prints a report unless quiet. If report_out
    (a dict) is given it is populated with the structured verify-report fields
    (records/errors/warnings/findings) that back the NON-NORMATIVE verify_report()
    integration API. The text output and exit code are byte-identical whether or
    not report_out is passed — findings are an additive side-channel, never a
    second derivation of the result."""
    errs = warns = 0
    findings = []

    def out(level, wid, msg):
        # TRUSTED internal reporter: core verification code only ever calls this
        # with exact-str ("ERR"/"WARN", a WarrantID/"settlement"/"store", an
        # f-string). The UNTRUSTED runtime-handler boundary does NOT get this
        # closure — it gets a validating, latching wrapper (see the dispatch loop),
        # so a hostile handler cannot poison counts/findings here.
        nonlocal errs, warns
        if level == "ERR":
            errs += 1
        elif level == "WARN":
            warns += 1
        if report_out is not None:
            # subject keeps the FULL WarrantID / "settlement" / "store"; only the
            # text rendering truncates to 12 chars. Emission order is deterministic
            # (records are iterated in sorted-WarrantID order), so findings are too.
            findings.append({"level": level, "subject": wid, "message": msg})
        if not quiet:
            print(f"{level:4} {wid[:12]}  {msg}")

    load_errors = {}
    recs = store.all_records(load_errors)

    def _finish():
        if report_out is not None:
            report_out["records"] = len(recs) + len(load_errors)
            report_out["errors"] = errs
            report_out["warnings"] = warns
            report_out["findings"] = findings
        return errs, warns
    ctx = None
    trust_doc = {}
    # Trust preflight runs BEFORE any per-record report so a fail-closed
    # short-circuit is EXACTLY one global ERR — a malformed record must not add an
    # error ahead of it (cross-impl parity: Go also emits nothing per-record on a
    # trust failure). Parse (I-JSON, dup-key/trailing-rejecting) AND closed-schema-
    # validate the trust config ONCE, then pass the value into context construction.
    if settlement is not None:
        trust_path = settlement.get("trust_config")
        trust_ok = True
        if trust_path:
            try:
                trust_doc = loads_ijson(Path(trust_path).read_text(encoding="utf-8"))
                err = _validate_trust_config(trust_doc)
                if err:
                    raise ValueError(err)
            except Exception:
                trust_ok = False
        if not trust_ok:
            out("ERR", "settlement", ERR_SETTLEMENT_TRUST)
            if not quiet:
                print(f"\nverify: {len(recs) + len(load_errors)} records, {errs} errors, {warns} warnings")
            return _finish()
    # Trust preflight passed (or base grade): now emit per-record load errors and
    # build the single settlement context over the SAME `recs` snapshot.
    for wid, reason in sorted(load_errors.items()):
        out("ERR", wid, f"unloadable record: {reason}")
    if settlement is not None:
        ctx = _settlement_context(store, genesis_roots=settlement.get("genesis_roots"),
                                  recs=recs, trust=trust_doc)
        for wid, msg in ctx["global_warnings"]:
            out("WARN", wid, msg)
        for root in sorted(ctx["roots"] - ctx["active_roots"]):
            out("WARN", root, WARN_UNADOPTED_ROOT)
    # Verifier-owned mode + a single read-only view passed to runtime handlers.
    # Built only when a handler is registered (deep copy has a cost); retains no
    # live recs/store and owns its own CAS meter (counts wrong-digest reads too).
    # On a trust-config failure verify_store has already returned; so when the
    # loop runs with settlement requested, ctx is always present. Mode is exactly
    # "base" or "settlement".
    _runtime_mode = "settlement" if ctx is not None else "base"
    _runtime_view = None
    if _RUNTIME_HANDLERS:
        _rt_reads = {"blobs": 0, "bytes": 0}

        def _rt_blob(h, _store=store, _reads=_rt_reads):
            if not (isinstance(h, str) and HEX64.match(h)):
                return None
            p = _store.blobs / h
            if not p.exists():
                return None
            raw = p.read_bytes()
            _reads["blobs"] += 1                        # count ATTEMPTED work,
            _reads["bytes"] += len(raw)                 # including wrong-digest reads
            return raw if blob_hash(raw) == h else None

        _rt_bodies = {w: json.loads(json.dumps(e["body"]))
                      for w, e in recs.items() if isinstance(e.get("body"), dict)}
        _rt_active = frozenset(ctx["active_records"]) if ctx is not None else None
        _rt_roots = ({w: frozenset(ctx["record_roots"](w)) for w in recs}
                     if ctx is not None else None)
        _runtime_view = _RuntimeView(_rt_bodies, _rt_active, _rt_roots, _rt_blob)
    for wid, env in recs.items():
        if set(env) != {"body", "sigs"}:
            out("ERR", wid, "envelope must be {body, sigs}")
            continue
        body = env["body"]
        if ctx is not None and wid in ctx["invalid_policy"]:
            out("ERR", wid, ERR_INVALID_THRESHOLD)
        schema_errs = validate_body(body)
        for m in schema_errs:
            out("ERR", wid, f"schema: {m}")
        try:
            got = warrant_id(body)
        except (UnicodeEncodeError, ValueError):
            # A body that cannot be canonicalized (e.g. a lone surrogate in a
            # string, which Python's json accepts but UTF-8 cannot encode) has no
            # computable WarrantID — a bounded ERR, never a traceback (Kimi K3 gate).
            out("ERR", wid, "WarrantID uncomputable (record contains invalid characters)")
            continue
        if got != wid:
            out("ERR", wid, f"WarrantID mismatch: recomputed {got[:12]}")
            continue
        sigs = env.get("sigs", [])
        if not isinstance(sigs, list):
            # A non-list `sigs` is a malformed envelope: one ERR, then SKIP the
            # record (like Go) — don't also emit "no signatures" nor process this
            # record's blob refs, which produced extra PY-only warnings (K3 gate).
            out("ERR", wid, "sigs must be a list")
            continue
        if not sigs:
            out("ERR", wid, "no signatures")
        actor_signed = False
        # body.actor may be type-confused in a schema-invalid record (already
        # ERR'd above); dereference it defensively so a string/scalar `actor`
        # cannot crash the signature loop with a valid co-signature attached
        # (Kimi full-audit, 2026-07: `actor:"x"` + valid sig → TypeError).
        _actor = body.get("actor") if isinstance(body, dict) else None
        body_actor_id = _actor.get("id") if isinstance(_actor, dict) else None
        for s in sigs:
            if not isinstance(s, dict):
                # A signature entry that is not an object is malformed. Report and
                # skip WITHOUT touching s.get(...) — a bare `s.get` crashed the
                # verifier on a string sig entry (Gemini 3.1 Pro audit, 2026-07).
                out("WARN", wid, "signature entry is not an object (excluded)")
                continue
            if not verify_sig(wid, s):
                # SPEC §5/§6: a co-signature that fails to verify is reported and
                # EXCLUDED, not fatal. The envelope is not hashed and co-sigs MAY
                # be appended by anyone with store write access, so a lone junk
                # co-sig MUST NOT be able to invalidate an otherwise-good record
                # (a griefing/availability vector). The record still ERRs below
                # if no *valid* signature by body.actor.id remains.
                out("WARN", wid, f"signature does not verify (excluded): "
                                 f"actor {s.get('actor')}")
                continue
            if ctx is None:
                # SPEC §5 MUST: with no keyring configured, the key↔actor binding is
                # unverified even though the signature is cryptographically valid —
                # the filer chose the key, so this actor claim is unproven.
                out("WARN", wid, f"binding unverified (no keyring): key "
                                 f"{str(s.get('key',''))[:12]} claims actor {s.get('actor')}")
            else:
                actor = s.get("actor")
                key = s.get("key")
                keys = ctx["keys_before"](wid)
                bound = (actor not in ctx["conflict_actors"]
                         and key in keys.get(actor, set()))
                if quiet:
                    pass
                elif bound:
                    print(f"INFO {wid[:12]}  signature bound: key "
                          f"{str(key)[:12]} claims actor {actor}")
                else:
                    out("WARN", wid, f"signature unbound: key "
                                     f"{str(key)[:12]} claims actor {actor}")
            if body_actor_id is not None and s.get("actor") == body_actor_id:
                actor_signed = True
        if sigs and not actor_signed:
            out("ERR", wid, "no valid signature by body.actor.id")
        # SPEC totality (Kimi full-audit, 2026-07): the semantic/DAG checks
        # below assume well-*typed* prior/under/evidence/because/subject. A
        # schema-invalid record may type-confuse them (e.g. prior:5, subject:"x")
        # and previously crashed the verifier with an uncaught TypeError/KeyError
        # — a store-wide AVAILABILITY vector, since one malformed record aborted
        # the whole run. The schema ERR is already reported above; here we simply
        # skip the parts of the semantic report that a wrong *type* makes
        # meaningless, WITHOUT suppressing the warnings a well-typed-but-invalid
        # record (e.g. a bad-*value* hash) still earns — matching the Go impl's
        # bounded report so PY/GO stay in lockstep (tests/fuzz_differential.py).
        for p in (body["prior"] if isinstance(body.get("prior"), list) else []):
            if not isinstance(p, str):
                continue
            prev = recs.get(p)
            if prev is None:
                out("ERR", wid, f"prior {p[:12]} not in store")
            # The ts-edge check must not crash on adversarial input: either body's
            # `ts` may be a non-integer in a schema-invalid record (already ERR'd
            # above). Compare only when both are real integers; otherwise the
            # schema error stands and the edge check is simply skipped. (Found by
            # tests/fuzz_differential.py — a string ts crashed the comparison.)
            elif (isinstance(prev["body"].get("ts"), int)
                  and not isinstance(prev["body"].get("ts"), bool)
                  and isinstance(body.get("ts"), int) and not isinstance(body.get("ts"), bool)
                  and prev["body"]["ts"] > body["ts"]):
                out("WARN", wid, f"ts decreases along prior edge {p[:12]}")
        # SPEC s6/s7: reference resolution is split by field kind. under,
        # evidence, check, transcript MUST resolve to BLOBS - a hash present
        # only as a stored record does not resolve them. subject.hash MAY
        # resolve to a WarrantID only where a rule explicitly names one
        # (supersede subjects; root-adoption/rotation accept subjects).
        # Type-guarded (see totality note above): well-typed inputs flow through
        # unchanged (transparent to the fuzzer); a type-confused field just
        # contributes no refs rather than raising.
        _under = body["under"] if isinstance(body.get("under"), list) else []
        _evidence = body["evidence"] if isinstance(body.get("evidence"), list) else []
        _because = body["because"] if isinstance(body.get("because"), list) else []
        _because = [r for r in _because if isinstance(r, dict)]
        blob_refs = [h for h in (list(_under) + list(_evidence)) if isinstance(h, str)]
        blob_refs += [r["check"] for r in _because
                      if r.get("kind") == "check" and isinstance(r.get("check"), str)]
        blob_refs += [r["transcript"] for r in _because
                      if r.get("kind") == "check" and isinstance(r.get("transcript"), str)]
        for h in blob_refs:
            if not store.has_blob(h):
                out("WARN", wid, f"unresolved blob {h[:12]}")
        _subject = body.get("subject") if isinstance(body, dict) else None
        subj = _subject.get("hash") if isinstance(_subject, dict) else None
        if isinstance(subj, str):
            subj_may_be_record = body.get("decision") in ("supersede", "accept")
            if not store.has_blob(subj) and not (subj_may_be_record and subj in recs):
                out("WARN", wid, f"unresolved blob {subj[:12]}")
            if body.get("decision") == "supersede" and subj not in recs:
                out("ERR", wid, "supersede subject MUST be the superseded WarrantID (SPEC s7)")
        if is_unverifiable(body):
            out("WARN", wid, "UNVERIFIABLE: reject with prose-only reasons")
        for r in _because:                          # re-run ski@v1 claims
            if r.get("kind") == "check" and r.get("runtime") == "ski@v1":
                try:
                    got, rh, _ = run_ski_check(store, r["check"])
                    if got != r["verdict"]:
                        out("WARN", wid, f"ski@v1 verdict mismatch: claimed "
                                         f"{r['verdict']}, re-run gives {got} ({rh[:12]})")
                except RuntimeError as ex:
                    # Codex v0.3 hardening audit P1: "reran and matched" and
                    # "not executed" MUST NOT be observationally equivalent.
                    # Base verification: a stable, path-free WARN. Settlement-
                    # grade: an ERR when the claim participates in an active
                    # record (an unexecuted claim can't be trusted to settle).
                    reason = str(ex)                # already a stable reason class
                    settle_active = ctx is not None and wid in ctx["active_records"]
                    lvl = "ERR" if (settlement is not None and settle_active) else "WARN"
                    out(lvl, wid, f"ski@v1 unverified: {reason}")
        if ctx is not None and wid in ctx["active_records"]:
            if body["actor"]["id"] in ctx["conflict_actors"]:
                out("WARN", wid, WARN_KEY_CONFLICT)
            if body["decision"] in ("accept", "reject"):
                for prior in sorted(prior_closure(recs, wid)):
                    prior_body = recs[prior]["body"]
                    if (prior in ctx["active_records"]
                            and prior_body["decision"] in ("accept", "reject")
                            and prior_body["subject"]["hash"] == body["subject"]["hash"]):
                        if settlement_admissibility(store, prior, body, recs).startswith("inadmissible"):
                            out("WARN", wid, WARN_RELITIGATION)
                        break
        # Version/reason-scoped runtime dispatch: only for a SCHEMA-VALID record
        # whose (body_version, runtime) has a registered handler. It receives the
        # single ctx/snapshot, the verifier mode, the reporter, and THIS reason —
        # not raw settlement. A handler exception is attributed to THIS record and
        # can never abort the core report. Empty registry => zero effect.
        if _RUNTIME_HANDLERS and not schema_errs:
            for r in _because:
                if r.get("kind") != "check":
                    continue
                handler = _RUNTIME_HANDLERS.get((body.get("warrant"), r.get("runtime")))
                if handler is None:
                    continue
                # The handler gets a VALIDATING, LATCHING reporter — never the raw
                # `out`. An invalid reporter call (level not exactly ERR/WARN, or a
                # subject/message that is not an EXACT built-in str — incl. a
                # hostile str subclass) is recorded in verifier-owned per-dispatch
                # state and NOT applied. The wrapper does NOT raise, so a handler
                # cannot suppress the consequence with a broad try/except (Codex
                # re-gate 2 P1). After the handler returns OR raises, exactly one
                # fail-closed ERR is folded if it crashed OR tripped the latch —
                # bounded and identical across quiet/loud/report renderers.
                fault = {"bad": False}

                def _reporter(level, w, msg, _fault=fault):
                    if (type(level) is not str or level not in ("ERR", "WARN")
                            or type(w) is not str or type(msg) is not str):
                        _fault["bad"] = True         # latch; do not apply, do not raise
                        return
                    out(level, w, msg)

                crashed = False
                try:
                    handler(_runtime_view, _runtime_mode, _reporter, wid, r)
                except Exception:
                    crashed = True
                if crashed or fault["bad"]:
                    out("ERR", wid, f"runtime {r.get('runtime')} fail-closed "
                                    f"(invalid reporter call or handler error)")
    if not quiet:
        print(f"\nverify: {len(recs) + len(load_errors)} records, {errs} errors, {warns} warnings")
    return _finish()


VERIFY_REPORT_VERSION = "warrant.verify-report@v0"


def verify_report(store, settlement=None):
    """NON-NORMATIVE machine-readable verification result for external agents
    (CI / MCP / LangGraph). This is NOT a Warrant: it is unsigned, carries no
    settlement semantics, and its shape (``warrant.verify-report@v0``) is an
    integration convenience, not part of SPEC — the normative result is still the
    error/warning counts and exit status. ``ok == (errors == 0)``; ``grade`` is
    ``settlement`` when a settlement context was requested, else ``base``; findings
    are in the verifier's deterministic emission order and always include warnings.
    Runs the SAME core as the text verifier (one derivation), so counts and exit
    status match ``verify`` exactly."""
    grade = "settlement" if settlement is not None else "base"
    # Fail-closed at the machine-consumption boundary (Codex countervector gate
    # P1-1): an uninitialized store (no records/ directory — a missing path, a
    # records/ that is a file, or blobs/ without records/) is NOT an empty
    # successful verification. Return one stable fail-closed report so an agent can
    # tell "verified empty initialized store" (ok:true, records:0) from "not a
    # store" (ok:false, one ERR whose subject is `store`). An initialized but empty
    # store still falls through to the normal ok:true path.
    if not store.records.is_dir():
        return {
            "report": VERIFY_REPORT_VERSION, "grade": grade, "ok": False,
            "records": 0, "errors": 1, "warnings": 0,
            "findings": [{"level": "ERR", "subject": "store",
                          "message": "no store (records/ is missing or not a directory)"}],
        }
    report_out = {}
    verify_store(store, quiet=True, settlement=settlement, report_out=report_out)
    return {
        "report": VERIFY_REPORT_VERSION,
        "grade": grade,
        "ok": report_out["errors"] == 0,
        "records": report_out["records"],
        "errors": report_out["errors"],
        "warnings": report_out["warnings"],
        "findings": report_out["findings"],
    }


WHY_MAX_DEPTH = 4096


def why(store, wid, depth=0, seen=None):
    # Iterative pre-order DAG walk. Was recursive: a deep *linear* prior-chain
    # (no cycle, so `seen` did not help) exhausted Python's call stack and
    # raised RecursionError — a `why` on hostile input crashed instead of
    # printing (Kimi full-audit, 2026-07). An explicit stack removes the call-
    # depth limit; `seen` still cuts cycles and depth is bounded defensively.
    seen = set()
    stack = [(wid, depth)]
    while stack:
        cur, d = stack.pop()
        env = store.get_record(cur)
        pad = "  " * d
        if env is None:
            print(f"{pad}?? {cur[:16]} (not in store)")
            continue
        body = env["body"]
        ok = warrant_id(body) == cur and all(verify_sig(cur, s) for s in env["sigs"])
        mark = "" if ok else "  [VERIFY FAILED]"
        unv = "  [unverifiable]" if is_unverifiable(body) else ""
        note = body["subject"].get("note", "")
        print(f"{pad}{body['decision'].upper()} {cur[:16]} by {body['actor']['id']}"
              f"  subject={body['subject']['hash'][:12]} {note}{mark}{unv}")
        for r in body["because"]:
            if r["kind"] == "prose":
                print(f"{pad}  - prose: {r['text']}")
            else:
                print(f"{pad}  - check {r['check'][:12]} [{r['runtime']}] -> {r['verdict']}")
        for h in body["under"]:
            print(f"{pad}  under policy {h[:12]}"
                  + ("" if store.has_blob(h) else " (unresolved)"))
        if cur in seen:
            print(f"{pad}  (cycle)")
            continue
        seen.add(cur)
        if d >= WHY_MAX_DEPTH:
            print(f"{pad}  (max depth {WHY_MAX_DEPTH} reached)")
            continue
        for p in reversed(body["prior"]):
            stack.append((p, d + 1))


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
    relitigates = getattr(args, "relitigates", None)
    if relitigates:
        verdict = settlement_admissibility(store, relitigates, body)
        if verdict.startswith("inadmissible"):
            sys.exit("refusing to file: cites nothing new")
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

    neg = d / "conformance-negatives.json"        # SPEC §8.3 (MUST reject each)
    if neg.exists():
        doc = json.loads(neg.read_text(encoding="utf-8"))
        for k in doc.get("weak_ed25519_pubkeys", []):
            sig = {"actor": "x", "key": k, "sig": "00" * 64}
            chk(f"neg: weak Ed25519 key {k[:12]} rejected",
                weak_ed25519_pubkey(bytes.fromhex(k)) and not verify_sig("00" * 64, sig))
        for case in doc.get("schema_invalid", []):
            chk(f"neg: schema-invalid ({case['why']})", bool(validate_body(case["body"])))

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
        p.add_argument("--relitigates")
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
    vf = sub.add_parser("verify")
    vf.add_argument("--settlement", action="store_true",
                    help="enable v0.3 settlement-grade checks (SPEC s5.1/s7/s9)")
    vf.add_argument("--genesis", action="append", default=[],
                    help="trusted genesis root WarrantID; repeatable")
    vf.add_argument("--trust-config",
                    help="local trust JSON: genesis_roots, genesis_json_sha256, actors")
    vf.add_argument("--json", action="store_true",
                    help="emit exactly one warrant.verify-report@v0 JSON object "
                         "(no human text); same counts and exit status as text mode")
    vf.add_argument("--store-mode", action="store_true",
                    help="require an initialized store (records/); fail closed on a "
                         "non-store. Python always verifies store-only, so this is a "
                         "no-op here — it exists for a portable store-strict command "
                         "line with the Go CLI (which also has a legacy flat mode)")
    stl = sub.add_parser("settle")
    stl.add_argument("settling_wid")
    stl.add_argument("candidate_body")
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
            hint = ("  (set SIGMA_GLYPH to the Σ-GLYPH impl directory)"
                    if str(ex) == "runtime unavailable" else "")
            sys.exit(f"ski@v1 unverified: {ex}{hint}")
        print(f"{verdict}  result={rh}  atp_spent={spent}")
        sys.exit(0 if verdict == "pass" else 1)
    elif args.cmd == "verify":
        settlement = None
        if args.settlement:
            settlement = {"genesis_roots": args.genesis,
                          "trust_config": args.trust_config}
        if args.json:
            # --json ALWAYS emits exactly one JSON object, even on a preflight
            # failure (verify_report is fail-closed on a missing store) — so the
            # machine contract holds without going through Store.require()'s exit.
            # ensure_ascii=True keeps it to one physical line (a U+2028/U+2029 in a
            # subject/message can't split the output for line-based consumers).
            report = verify_report(store, settlement=settlement)
            print(json.dumps(report, separators=(",", ":"), ensure_ascii=True))
            sys.exit(1 if report["errors"] else 0)
        store.require()
        errs, _ = verify_store(store, settlement=settlement)
        sys.exit(1 if errs else 0)
    elif args.cmd == "settle":
        store.require()
        body = loads_ijson(Path(args.candidate_body).read_text(encoding="utf-8"))
        verdict = settlement_admissibility(store, args.settling_wid, body)
        print(verdict)
        sys.exit(1 if verdict.startswith(("inadmissible", "invalid candidate")) else 0)
    elif args.cmd == "conformance":
        sys.exit(0 if conformance(args.examples) else 1)
    elif args.cmd == "selftest":
        sys.exit(0 if selftest() else 1)
    elif args.cmd == "canon":
        body = loads_ijson(Path(args.file).read_text(encoding="utf-8"))
        print(json.dumps({"warrant_id": warrant_id(body),
                          "canon_hex": canon(body).hex()}))


if __name__ == "__main__":
    main()
