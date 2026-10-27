"""The store (docs/V3.md §8): `records.jsonl`, one canonical line per record, and `blobs/<sha256>`.
Read in any order with duplicates (union merge); written in canonical order (distinct lines by id)."""
import fcntl
import hashlib
import json
import os
from pathlib import Path

from warrant import jcs as C
from warrant import shapes as S

from . import records as R

LIMITS = {"records": 200_000, "bytes": 256 << 20, "refs": 4096, "depth": 4096}


class Refused(ValueError):
    pass


class Snapshot:
    """The bytes of one read: {id: [distinct lines]}, {hash: bytes}, and what was wrong."""

    def __init__(self, lines, blobs):
        self.blobs = dict(blobs)
        self.rejected, self.lines, seen = {}, {}, set()
        self.canonical = list(lines) == sorted(set(lines), key=_line_id)
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
            except (R.Invalid, C.NotCanonical, ValueError) as e:
                self.rejected[hashlib.sha256(raw).hexdigest()] = f"line: {e}"
                continue
            self.lines.setdefault(R.rid(env["record"]), []).append(env)
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
    try:
        return R.rid(json.loads(raw)["record"]), raw
    except (ValueError, KeyError, TypeError):
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
        p = self.blobs / h
        if not p.exists():
            tmp = p.with_name(f".{h}.{os.getpid()}")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        return h

    def snapshot(self):
        raw = self.file.read_bytes() if self.file.exists() else b""
        lines = [x + b"\n" for x in raw.split(b"\n") if x]
        blobs = {p.name: p.read_bytes() for p in sorted(self.blobs.iterdir())} if self.blobs.is_dir() else {}
        bad = [h for h, b in blobs.items() if hashlib.sha256(b).hexdigest() != h]
        if bad:
            raise Refused(f"blobs not named by their hash: {bad[:3]}")
        return Snapshot(lines, blobs)

    def append(self, r, key, trust, expect_head=None):
        """File `r` signed by `key` as the next record of its actor's chain (§7): prev is the actor's
        head under an exclusive lock; with expect_head, refused unless the head is that id."""
        from .engine import head
        with open(self.file, "ab") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            h = head(self.snapshot(), trust, r["actor"])
            if expect_head is not None and h["id"] != expect_head:
                raise Refused(f"CHAIN_MOVED: the head of {r['actor']} is {h['id']}")
            if h["at"] is not None and r["at"] < h["at"]:
                raise Refused(f"at {r['at']} is before the actor's head ({h['at']})")
            r = dict(r, prev=h["id"])
            R.check(r)
            i, data = R.line(r, key)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        return i

    def write_lines(self, lines):
        """Replace the file with `lines` in canonical order (fmt, migration)."""
        out = b"".join(sorted(set(lines), key=_line_id))
        tmp = self.file.with_name(f".records.{os.getpid()}")
        tmp.write_bytes(out)
        os.replace(tmp, self.file)
