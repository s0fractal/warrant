"""A workspace's content-addressed objects: `<state>/<workspace>/objects/<2 hex>/<62 hex>`.

An object's name is the SHA-256 of its bytes, and nothing else is a name. Record envelopes, blobs,
provider modules and each view's tree, report body and manifest are objects (views.py). An object is
added, never changed: a new one is linked into place from a read-only temporary file, so a name is
never overwritten by a racing writer; bytes found under a name that do not hash to it are damage, and
the only replacement there is puts back the bytes that do. Every read hashes what it read and refuses
an absent object or bytes that are not the name's (Unreadable): nothing is read from elsewhere.

The lock (`objects/lock`) is held shared by a capture from its first write until its view is reachable,
and exclusively by a collection (views.collect): a collection never sees an object a capture is about
to pin as unreachable. The layout is git's loose objects and minds' cas/ (VARS-1 §3)."""
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import secrets
from pathlib import Path

from warrant import limits as L
from warrant import shapes as S
from warrant.store import Snapshot

LOCK, LAST = "lock", "gc.json"
TMP = ".tmp-"


class Unreadable(Exception):
    """An object a reader needs is absent, or its bytes do not hash to its name."""

    def __init__(self, name, why):
        super().__init__(f"object {str(name)[:16]} is {why}")
        self.name, self.why = name, why


def name_of(data):
    return hashlib.sha256(data).hexdigest()


def doc_bytes(doc):
    """The one encoding of a JSON object stored here (an operator's limits or profile may hold floats: not JCS)."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


class Objects:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, name):
        """The path of `name`: a full object name (shapes.hex64) whose real path is exactly
        <root>/<2 hex>/<62 hex>, inside the store's real root with no symlink below it."""
        if not S.hex64(name):
            raise Unreadable(name, "not an object name")
        base = os.path.realpath(self.root)
        want = os.path.join(base, name[:2], name[2:])
        real = os.path.realpath(want)
        if not (real.startswith(base + os.sep) and real == want):
            raise Unreadable(name, "not a plain file path under the object store")
        return Path(real)

    def _read(self, p, name):
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError as e:
            if e.errno == errno.ELOOP:
                raise Unreadable(name, "a symlink") from None
            raise
        with os.fdopen(fd, "rb") as f:
            return f.read()

    def put(self, data):
        """The name of `data`, stored once. Equal bytes already there: nothing is written."""
        data = bytes(data)
        name = name_of(data)
        p = self.path(name)
        d = p.parent
        d.mkdir(parents=True, exist_ok=True)
        for _ in range(3):
            existing = self._read(p, name)
            if existing == data:
                return name
            tmp = d / f"{TMP}{os.getpid()}-{secrets.token_hex(6)}"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            if existing is not None:
                # bytes under this name that do not hash to it: damage, replaced by the bytes that do
                os.replace(tmp, p)
                return name
            try:
                os.link(tmp, p)                 # fails if another writer linked the name first
                return name
            except FileExistsError:
                continue                        # its bytes are compared like any existing object's
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp)
        raise Unreadable(name, "not writable")

    def get(self, name):
        """The bytes of `name`, hashed on this read; Unreadable if absent or damaged."""
        p = self.path(name)
        data = self._read(p, name)
        if data is None:
            raise Unreadable(name, "absent")
        if name_of(data) != name:
            raise Unreadable(name, "damaged: its bytes do not hash to its name")
        return data

    def get_doc(self, name):
        try:
            doc = json.loads(self.get(name))
        except ValueError:
            raise Unreadable(name, "not a JSON document") from None
        if not isinstance(doc, dict):
            raise Unreadable(name, "not a JSON object")
        return doc

    def size(self, name):
        try:
            return os.lstat(self.path(name)).st_size
        except FileNotFoundError:
            raise Unreadable(name, "absent") from None

    def snapshot(self, tree, limits=None):
        """The Snapshot a tree names, under the admission limits a store read is under (Snapshot.read):
        counts first, then the bytes before and after each object is read."""
        lim = L.resolve(limits)
        recs, blobs = tree["records"], tree["blobs"]
        L.admit(lim, "snapshot_records", len(recs))
        L.admit(lim, "snapshot_blobs", len(blobs))
        out, size = {"records": {}, "blobs": {}}, 0
        for kind, pairs in (("records", sorted(recs.items())), ("blobs", [(h, h) for h in blobs])):
            for key, name in pairs:
                L.admit(lim, "snapshot_bytes", size + self.size(name))
                data = self.get(name)
                size += len(data)
                L.admit(lim, "snapshot_bytes", size)
                out[kind][key] = data
        return Snapshot(out["records"], out["blobs"], tree["misfiled"])

    @contextlib.contextmanager
    def lock(self, exclusive, wait=True):
        """Yields True with the lock held (shared or exclusive); False when wait=False and it is busy."""
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.root / LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            held = True
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                held = False
            yield held
        finally:
            os.close(fd)                        # closing the descriptor releases the lock

    def names(self):
        """(object name, path) of every file under a fan-out directory, temporaries included (name None)."""
        for d in sorted(self.root.iterdir()) if self.root.is_dir() else ():
            if not (S.hex_of(d.name, 2) and d.is_dir() and not d.is_symlink()):
                continue
            for f in sorted(d.iterdir()):
                full = d.name + f.name
                yield (full if S.hex64(full) else None), f
