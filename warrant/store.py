"""Stores, immutable snapshots and trust (SPEC §3, §4).

A store is a directory with `records/<id>.json` and `blobs/<sha256>`. A Snapshot
reads every file exactly once into memory; everything an assessment decides is
decided from those bytes, never from the directory again."""
import os
from pathlib import Path

from . import jcs as C
from . import keys as K
from . import limits as L
from . import records as R

MAX_FILE = 64 * 1024 * 1024


class Store:
    """A writable store directory. Writing is content-addressed and idempotent."""

    def __init__(self, root):
        self.root = Path(root)

    def init(self):
        (self.root / "records").mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)
        return self

    def put_blob(self, data):
        h = C.digest(data)
        p = self.root / "blobs" / h
        if not p.exists():
            _write(p, data)
        return h

    def put_json(self, doc):
        return self.put_blob(C.canon(doc))

    def put_record(self, r, key):
        rid, data = R.sign(r, key)
        p = self.root / "records" / f"{rid}.json"
        if not p.exists():
            _write(p, data)
        return rid

    def snapshot(self, limits=None):
        return Snapshot.read(self.root, limits=limits)


def _write(path, data):
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Trust:
    """The recipient's key bindings: key id -> (actor, public key). Authentication only."""

    def __init__(self, doc):
        R._fields(doc, ("warrant", "keys"), what="trust")
        R._need(doc["warrant"] == "trust/2", "trust version must be \"trust/2\"")
        R._need(isinstance(doc["keys"], list), "trust keys must be a list")
        self.keys = {}
        for k in doc["keys"]:
            R._fields(k, ("actor", "public"), what="trust key")
            R._actor(k["actor"], "trust actor")
            R._hex(k["public"], "trust public key")
            kid = K.key_id(k["public"])
            R._need(kid not in self.keys, "a key is bound twice")
            self.keys[kid] = (k["actor"], k["public"])
        self.digest = C.doc_id(doc)

    @classmethod
    def load(cls, path):
        return cls(C.loads(Path(path).read_bytes()))

    @staticmethod
    def document(bindings):
        """A trust document from [(actor, public hex)]."""
        return {"warrant": "trust/2", "keys": [{"actor": a, "public": p} for a, p in bindings]}


class Snapshot:
    """An immutable view of a store's bytes: {record id: bytes}, {blob hash: bytes}.
    Files whose name is not their content address are kept out and listed."""

    def __init__(self, records, blobs, misfiled=()):
        self.records = dict(records)
        self.blobs = dict(blobs)
        self.misfiled = sorted(misfiled)
        listing = sorted([f"r {k} {C.digest(v)}" for k, v in self.records.items()]
                         + [f"b {k}" for k in self.blobs] + [f"x {m}" for m in self.misfiled])
        # Content, not location: the same bytes in another directory give the same digest.
        self.digest = C.digest("\n".join(listing).encode())

    def admit(self, limits):
        """Refuse a snapshot beyond the admission limits (limits.LimitExceeded)."""
        L.admit(limits, "snapshot_records", len(self.records))
        L.admit(limits, "snapshot_blobs", len(self.blobs))
        L.admit(limits, "snapshot_bytes", sum(map(len, self.records.values())) + sum(map(len, self.blobs.values())))

    @classmethod
    def read(cls, root, limits=None):
        """Read a store once. Beyond an admission limit (`limits` overrides
        limits.DEFAULTS) it raises limits.LimitExceeded before reading further:
        64 MiB per file is no bound on the whole (Codex F2)."""
        lim = L.resolve(limits)
        root = Path(root)
        found = {"records": {}, "blobs": {}}
        misfiled = []
        size = 0
        for kind in ("records", "blobs"):
            folder = root / kind
            entries = []
            for p in folder.iterdir() if folder.is_dir() else ():
                entries.append(p)
                L.admit(lim, f"snapshot_{kind}", len(entries))
            for p in sorted(entries):
                why = _file_problem(kind, p)
                if why:
                    misfiled.append(f"{kind}/{p.name}: {why}")
                else:
                    L.admit(lim, "snapshot_bytes", size + p.stat().st_size)
                    data = p.read_bytes()
                    size += len(data)
                    L.admit(lim, "snapshot_bytes", size)
                    key = p.name if kind == "blobs" else p.name[:-5]
                    if kind == "blobs" and key != C.digest(data):
                        misfiled.append(f"blobs/{p.name}: name is not its hash")
                    else:
                        found[kind][key] = data
        return cls(found["records"], found["blobs"], misfiled)

    def blob(self, h):
        return self.blobs.get(h) if isinstance(h, str) else None

    def json_blob(self, h):
        """A canonical JSON blob, or None."""
        data = self.blob(h)
        if data is None:
            return None
        try:
            return C.loads(data)
        except C.NotCanonical:
            return None

    def authentic(self, trust):
        """({id: record}, {id: reason}) — records that are canonical, carry their
        own id, and are signed by a key the trust binds to their actor."""
        good, bad = {}, {}
        for rid, data in sorted(self.records.items()):
            why, rec = _authenticate(rid, data, trust)
            if why:
                bad[rid] = why
            else:
                good[rid] = rec
        return good, bad


def _file_problem(kind, p):
    if p.is_symlink() or not p.is_file():
        return "not a regular file"
    if p.stat().st_size > MAX_FILE:
        return "larger than admitted"
    if kind == "records" and not (p.name.endswith(".json") and R.HEX64.match(p.name[:-5])):
        return "not a record file name"
    return None


def _authenticate(rid, data, trust):
    try:
        env = C.loads(data)
    except C.NotCanonical as e:
        return f"not canonical: {e}", None
    try:
        R._fields(env, ("record", "sig"), what="stored record")
        R._fields(env["sig"], ("key", "ed25519"), what="sig")
        R._hex(env["sig"]["key"], "sig key")            # types before lookup (R138-02)
        R._need(isinstance(env["sig"]["ed25519"], str) and K.HEX128.match(env["sig"]["ed25519"]) is not None,
                "sig ed25519 must be 128 hex characters")
        R.check(env["record"])
    except R.Invalid as e:
        return f"invalid: {e}", None
    rec = env["record"]
    if R.record_id(rec) != rid:
        return "id does not match the record", None
    bound = trust.keys.get(env["sig"]["key"])
    if bound is None:
        return "signed by a key the trust does not bind", None
    if bound[0] != rec["actor"]:
        return "signed by a key bound to another actor", None
    if not K.verify(bound[1], env["sig"]["ed25519"], K.sig_message(rid)):
        return "signature does not verify", None
    return None, rec
