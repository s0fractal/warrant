"""Stores, immutable snapshots and trust (SPEC §3, §4).

A store is a directory with `records/<id>.json` and `blobs/<sha256>`. A Snapshot
reads every file exactly once into memory; everything an assessment decides is
decided from those bytes, never from the directory again."""
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path

from . import jcs as C
from . import keys as K
from . import limits as L
from . import records as R

MAX_FILE = 64 * 1024 * 1024


class ChainMoved(ValueError):
    """A record's `prev` is no longer its actor's head in this store (SPEC §3)."""


class Store:
    """A writable store directory. Writing is content-addressed and idempotent. `verdicts`
    names a directory of the writer's own (Verdicts.at) where a head read remembers its
    authentication verdicts across processes: cost only (F44)."""

    def __init__(self, root, verdicts=None):
        self.root = Path(root)
        self.verdicts = verdicts

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

    def head(self, actor, trust):
        """(id, at) of `actor`'s chain head in this store, or None before its first chained
        record. Only records the reader itself admits count (AMEND 1 of #174): authentic
        under `trust` by the reader's own path (Snapshot.authentic: canonical, named by its
        id, well-formed, signed by a key bound to `actor`), carrying `prev`, and chained
        back to a genesis (each link to the actor's own authentic record, not dated after
        it). An unanchored record is no head: a record extending it would have no ancestors
        before it, so the actor's own chain authority would stop there. Of those records,
        the ones no other names as its `prev`, the latest by (at, id). A rejected or
        unanchored file is never a predecessor; the reader still reports it.

        Every record file is read on every call; the verdicts of files whose bytes were
        authenticated before under this trust come from this process's memory or the
        writer's own `verdicts` directory (F44): cost, never which records count."""
        snap = Snapshot.read(self.root, kinds=("records",))
        index = Verdicts.at(self.verdicts) if self.verdicts is not None else None
        good, _ = snap.authentic(trust, index)
        if index is not None:
            index.flush(snap)
        mine = {rid: r for rid, r in good.items() if r["actor"] == actor and "prev" in r}
        anchored = {}
        for start in sorted(mine):
            path, x = [], start
            while x not in anchored:
                r = mine.get(x)
                if r is None:                   # not the actor's own authentic record
                    anchored[x] = False
                    break
                path.append(x)
                p = r["prev"]
                if p is None:
                    anchored[x] = True
                    break
                if p in mine and mine[p]["at"] > r["at"]:
                    anchored[x] = False
                    break
                x = p
            ok = anchored[x]
            for y in path:
                anchored.setdefault(y, ok)
        chain = {rid: r for rid, r in mine.items() if anchored.get(rid)}
        named = {r["prev"] for r in chain.values()}
        tips = [(r["at"], rid) for rid, r in chain.items() if rid not in named]
        return (max(tips)[1], max(tips)[0]) if tips else None

    def append(self, rtype, actor, at, body, key, trust=None):
        """File a record that extends `actor`'s chain in this store: `prev` is the head under
        `trust` (default: a trust binding only the signing key to `actor`), read and extended
        under one lock (see extend). A record dated before its predecessor is refused, not
        filed unanchored. The head is read once: under the lock no writer of this store
        files, so a second read before filing would find the same head (F44)."""
        trust = trust or _own(actor, key)

        def file():
            head = self.head(actor, trust)
            return self._extend(R.record(rtype, actor, at, body, prev=head[0] if head else None), key, head)
        return self._locked(file)

    def extend(self, r, key, trust=None):
        """File record `r`, already built, iff its `prev` is still `r`'s actor's head here
        under `trust` (default: the signing key's own): a compare-and-swap (minds VARS-1 §3:
        `git update-ref <ref> T_new T_old`), under an exclusive lock on records/, so two
        writers of one store never name the same head. Raises ChainMoved otherwise; nothing
        is written."""
        R.check(r)
        trust = trust or _own(r["actor"], key)
        return self._locked(lambda: self._extend(r, key, self.head(r["actor"], trust)))

    def _extend(self, r, key, head):
        """File `r` iff its prev is `head`, the head read under the lock this call holds."""
        if "prev" not in r or r["prev"] != (head[0] if head else None):
            raise ChainMoved(f"{r['actor']}'s chain head here is {head[0][:12] if head else 'none'}, "
                             f"not the record's prev {str(r.get('prev'))[:12]}")
        if head is not None and r["at"] < head[1]:
            raise ValueError(f"{r['actor']}'s chain head {head[0][:12]} is at {head[1]}; a record at {r['at']} would precede it")
        return self.put_record(r, key)

    def _locked(self, fn):
        self.init()
        fd = os.open(self.root / "records", os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            return fn()
        finally:
            os.close(fd)

    def snapshot(self, limits=None):
        return Snapshot.read(self.root, limits=limits)


def _own(actor, key):
    """The trust of a writer that knows only its own key: that key bound to `actor`."""
    return Trust(Trust.document([(actor, key.public)]))


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
    def read(cls, root, limits=None, kinds=("records", "blobs")):
        """Read a store once. Beyond an admission limit (`limits` overrides
        limits.DEFAULTS) it raises limits.LimitExceeded before reading further:
        64 MiB per file is no bound on the whole (Codex F2). kinds=("records",)
        leaves the blobs unread: a writer's head is decided by records alone."""
        lim = L.resolve(limits)
        root = Path(root)
        found = {"records": {}, "blobs": {}}
        misfiled = []
        size = 0
        for kind in kinds:
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

    def authentic(self, trust, index=None):
        """({id: record}, {id: reason}) — records that are canonical, carry their
        own id, and are signed by a key the trust binds to their actor. Each verdict
        is _authenticate's on these bytes under this trust, remembered by this process
        and, with an `index` (Verdicts), by its owner (see _verdict)."""
        good, bad = {}, {}
        for rid, data in sorted(self.records.items()):
            why, rec = _verdict(rid, data, trust, index)
            if why:
                bad[rid] = why
            else:
                good[rid] = rec
        return good, bad


# ---------------------------------------------------------------- remembered verdicts (F44)
#
# A record file's verdict is a function of its name, its bytes, the trust it is read under
# and the code that reads it: _authenticate reads nothing else. So a verdict computed once
# can stand in for computing it again, exactly when all four are the same. Like the
# ReplayCache (SPEC §7) it changes cost, never the answer: every file is still read and its
# bytes hashed on every read, so a new, changed or removed file is seen as such, and a
# record a remembered verdict admits is parsed from those same bytes.

MISS = object()
_MEMO = {}              # (trust digest, record id, sha256 of the bytes) -> reason or None
_MEMO_MAX = 1 << 17     # entries (some 40 MB); this process's own memory, emptied when full


def _verdict(rid, data, trust, index=None):
    """_authenticate(rid, data, trust), from this process's memory or `index` when either
    holds the verdict for these exact bytes under this exact trust."""
    k = (trust.digest, rid, hashlib.sha256(data).hexdigest())
    why = _MEMO.get(k, MISS)
    if why is MISS and index is not None:
        why = index.get(k)
    if why is MISS:
        why, rec = _authenticate(rid, data, trust)
    else:
        # Bytes _authenticate admitted are canonical (SPEC §2), and json reads canonical
        # bytes as the strict reader does: the same record from the same bytes.
        rec = None if why else json.loads(data)["record"]
    if len(_MEMO) >= _MEMO_MAX:
        _MEMO.clear()
    _MEMO[k] = why
    if index is not None:
        index.add(k, why)
    return why, rec


_CODE = []


def code_identity():
    """The code a verdict was computed by: every file of the package (engine_identity) and
    the version of the library that verifies signatures."""
    if not _CODE:
        import cryptography

        from .engine import engine_identity
        _CODE.append(C.doc_id({"package": engine_identity(), "cryptography": cryptography.__version__}))
    return _CODE[0]


class Verdicts:
    """An index of the verdicts its owner has computed (F44): one line per (trust digest,
    record id, sha256 of the file's bytes, verdict), each MACed, with the package's code
    identity, under the owner's secret: 32 random bytes in the same directory, made on first
    use and readable by the owner only. One file per trust digest, read only when a verdict
    under that trust is looked up. The directory is the owner's, like its keys and its
    ReplayCache (SPEC §7), outside every store: Snapshot.read does not read it and a handoff
    does not carry it, and it is never another party's to trust. A line whose MAC or shape is
    wrong is skipped, so a tampered, forged, stale or truncated index costs a fresh
    authentication, never a verdict its owner did not compute (a party who can read the
    secret can forge, as it could write a ReplayCache entry)."""
    SCHEMA = "warrant-verdicts/1"

    def __init__(self, folder, secret, code):
        self.folder, self._secret, self.code = folder and Path(folder), secret, code
        self.parts = {}         # trust digest -> {"entries": {key: verdict}, "lines": n, "new": [key]}

    def path(self, trust_digest):
        return self.folder / f"{trust_digest}.jsonl" if self.folder else None

    def _part(self, t):
        part = self.parts.get(t)
        if part is not None:
            return part
        part = self.parts[t] = {"entries": {}, "lines": 0, "new": []}
        try:
            data = self.path(t).read_bytes() if self.folder and R.HEX64.match(t) else b""
        except OSError:
            data = b""
        for line in data.split(b"\n"):
            if not line:
                continue
            part["lines"] += 1
            try:
                x = json.loads(line)
            except ValueError:
                continue
            # The MAC covers the code identity too: a line another version of the package wrote
            # (or another owner's secret) does not verify.
            if not (isinstance(x, list) and len(x) == 7 and x[0] == self.SCHEMA
                    and all(isinstance(v, str) for v in x[2:5]) and (x[5] is None or isinstance(x[5], str))
                    and isinstance(x[6], str) and hmac.compare_digest(x[6], self._mac(x[2:6]))):
                continue
            part["entries"][tuple(x[2:5])] = x[5]
        return part

    @classmethod
    def at(cls, folder):
        """The index in `folder`, its secret `folder/secret`. A secret of another size is not
        used, and nothing is read or written: the index then costs nothing and saves nothing."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / "secret"
        if not p.exists():
            tmp = folder / f"secret.tmp{os.getpid()}"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, os.urandom(32))
            finally:
                os.close(fd)
            try:
                os.link(tmp, p)                 # the first writer's secret wins
            except FileExistsError:
                pass
            finally:
                os.remove(tmp)
        secret = p.read_bytes()
        return cls(folder if len(secret) == 32 else None, secret, code_identity())

    def _mac(self, fields):
        msg = json.dumps([self.SCHEMA, self.code, *fields], ensure_ascii=True, separators=(",", ":"))
        return hmac.new(self._secret, msg.encode(), hashlib.sha256).hexdigest()

    def _line(self, k, why):
        fields = [*k, why]
        return json.dumps([self.SCHEMA, self.code, *fields, self._mac(fields)], ensure_ascii=True,
                          separators=(",", ":")) + "\n"

    def get(self, k):
        return self._part(k[0])["entries"].get(k, MISS)

    def add(self, k, why):
        part = self._part(k[0])
        if k not in part["entries"]:
            part["entries"][k] = why
            part["new"].append(k)

    def flush(self, snap):
        """Write what this read added. When most lines of a file name files no longer in `snap`,
        or were skipped, it is rewritten with the entries for files `snap` holds."""
        if self.folder is None:
            return
        present = {(rid, hashlib.sha256(b).hexdigest()) for rid, b in snap.records.items()}
        for t, part in self.parts.items():
            entries, new = part["entries"], part["new"]
            live = [k for k in entries if k[1:] in present]
            if not new and part["lines"] <= 2 * len(live) + 64:
                continue
            if part["lines"] + len(new) > 2 * len(live) + 64:
                _write(self.path(t), "".join(self._line(k, entries[k]) for k in live).encode())
                part["lines"] = len(live)
            else:
                fd = os.open(self.path(t), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
                try:
                    os.write(fd, "".join(self._line(k, entries[k]) for k in new).encode())
                finally:
                    os.close(fd)
                part["lines"] += len(new)
            part["new"] = []


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
