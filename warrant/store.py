"""The store (docs/V3.md §8): `records.jsonl`, one canonical line per record, and `blobs/<sha256>`.
Read in any order with duplicates (union merge); written in canonical order (distinct lines by id)."""
import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path

from warrant import jcs as C
from warrant import shapes as S

from . import records as R

LIMITS = {"records": 200_000, "bytes": 256 << 20, "refs": 4096, "depth": 4096, "requires": 128}
# A line that cannot be read as a record is listed under `rejected` and never aborts the read (§8), whatever
# the reader raised on it (jcs refuses deep nesting itself; the tuple keeps a reader change from aborting).
UNREADABLE = (R.Invalid, ValueError, TypeError, KeyError, RecursionError)


class Refused(ValueError):
    pass


def confined(path, base):
    """The real path of `path`, refused unless it lies in `base` (by real path too): a path an
    operator or a caller names never reaches a file outside the tree it is meant for."""
    b, p = os.path.realpath(base), os.path.realpath(path)
    if p != b and not p.startswith(b + os.sep):
        raise Refused(f"{path}: outside {b}")
    return p


class Snapshot:
    """The bytes of one read: {id: [distinct lines]}, {hash: bytes}, and what was wrong."""

    def __init__(self, lines, blobs):
        self.blobs = dict(blobs)
        self.rejected, self.lines, seen = {}, {}, set()
        order = list(lines) == sorted(set(lines), key=_line_id)
        for raw in lines:
            if raw in seen:
                continue
            seen.add(raw)
            try:
                if len(raw) > R.LINE_MAX:
                    raise R.Invalid(f"line longer than {R.LINE_MAX} bytes")
                env = C.loads(raw.rstrip(b"\n"))
                R.need(isinstance(env, dict) and set(env) == {"record", "sig"}, "a line is {record, sig}")
                R.check(env["record"])
                sig = env["sig"]
                R.need(sig is None or (isinstance(sig, dict) and set(sig) == {"key", "ed25519"} and S.hex64(sig["key"])
                                       and S.hex128(sig["ed25519"])), "sig is null or {key, ed25519}")
            except UNREADABLE as e:
                self.rejected[hashlib.sha256(raw).hexdigest()] = f"line: {e}"
                continue
            self.lines.setdefault(R.rid(env["record"]), []).append(env)
        self.canonical = order and not self.rejected          # a rejected line is never canonical, wherever it sorts
        listing = sorted(seen) + [f"b {h} {C.digest(b)}".encode() for h, b in sorted(self.blobs.items())]
        self.digest = C.digest(b"\n".join(listing))
        if len(self.lines) > LIMITS["records"] or sum(map(len, seen)) + sum(map(len, self.blobs.values())) > LIMITS["bytes"]:
            raise Refused(f"store beyond limits {LIMITS}")

    def blob(self, h):
        return self.blobs.get(h)

    def json_blob(self, h):
        try:
            return C.loads(self.blobs[h]) if h in self.blobs else None
        except C.NotCanonical:
            return None


def _line_id(raw):
    """The sort key of a line: its record's id, or "" for a line that holds no record object (it is rejected)."""
    try:
        doc = json.loads(raw)
        rec = doc.get("record") if isinstance(doc, dict) else None
        return (R.rid(rec), raw) if isinstance(rec, dict) else ("", raw)
    except UNREADABLE:
        return "", raw


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.file, self.blobs = self.root / "records.jsonl", self.root / "blobs"

    def init(self):
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.file.touch()
        return self

    def put_blob(self, data):
        h = hashlib.sha256(data).hexdigest()
        p = confined(self.blobs / h, self.blobs)
        if not os.path.exists(p):
            fd, tmp = tempfile.mkstemp(prefix=".blob.", dir=self.blobs)     # named apart from the content
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        return h

    def snapshot(self):
        lines = self.lines()
        blobs = {p.name: p.read_bytes() for p in sorted(self.blobs.iterdir())} if self.blobs.is_dir() else {}
        bad = [h for h, b in blobs.items() if hashlib.sha256(b).hexdigest() != h]
        if bad:
            raise Refused(f"blobs not named by their hash: {bad[:3]}")
        return Snapshot(lines, blobs)

    @contextlib.contextmanager
    def locked(self):
        """The writers' exclusive lock: on the store directory, not on records.jsonl, whose file every write
        replaces (a lock on a replaced file would let a waiting writer append to an unlinked one)."""
        fd = os.open(self.root, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def lines(self):
        raw = self.file.read_bytes() if self.file.exists() else b""
        return [x + b"\n" for x in raw.split(b"\n") if x]

    def append(self, r, key, trust, expect_head=None):
        """File `r` signed by `key` as the next record of its actor's chain (§7): prev is the actor's
        head under the writers' lock; with expect_head, refused unless the head is that id ("": the actor
        has no signed record yet). The file is rewritten in canonical order."""
        return self.extend([r], key, trust, expect_head)[0]

    def extend(self, records, key, trust, expect_head=None):
        """append() for several records of one actor, chained in order, under one lock and one write."""
        from .engine import head
        out, data = [], []
        with self.locked():
            actor = records[0]["actor"]
            h = head(self.snapshot(), trust, actor)
            if expect_head is not None and (h["id"] or "") != expect_head:
                raise Refused(f"CHAIN_MOVED: the head of {actor} is {h['id']}")
            prev, at = h["id"], h["at"]
            for r in records:
                if r["actor"] != actor or (at is not None and r["at"] < at):
                    raise Refused(f"a record of {r['actor']} at {r['at']} does not extend {actor}'s chain at {at}")
                r = dict(r, prev=prev)
                R.check(r)
                prev, line = R.line(r, key)
                if len(line) > R.LINE_MAX:              # a writer never writes a line its reader rejects (§8)
                    raise Refused(f"the record's line is {len(line)} bytes, more than {R.LINE_MAX}")
                at = r["at"]
                out.append(prev)
                data.append(line)
            self.write_lines(self.lines() + data)
        return out

    def add_lines(self, lines):
        """Add lines as they are (an import, a union): under the writers' lock, in canonical order."""
        with self.locked():
            self.write_lines(self.lines() + list(lines))

    def write_lines(self, lines):
        """Replace the file with `lines` in canonical order (fmt, append, add_lines), durably."""
        out = b"".join(sorted(set(lines), key=_line_id))
        fd, tmp = tempfile.mkstemp(prefix=".records.", dir=self.root)
        with os.fdopen(fd, "wb") as f:
            f.write(out)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.file)
