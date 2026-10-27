"""The proof-space pilot's test fixture (tests/pilot_test.py): a directory with a blob store A (blobs/<hex64>,
the layout warrant_pilot's BlobDir reads) and a fanout object store B (<2 hex>/<62 hex>), and the check list.
The pilot reads objects, never records: `duty()` gives one canonical record envelope's id and bytes, so a case
can show that a record named by its id is no object."""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from warrant import jcs as C               # noqa: E402
from warrant_pilot import compute as P     # noqa: E402,F401  (re-exported: tests/pilot_test.py imports P from here)

results = {}


class Snap:
    def __init__(self, blobs, records):
        self.blobs, self.records = blobs, records


class Store:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)
        self.records = {}

    def put_blob(self, data):
        h = hashlib.sha256(data).hexdigest()
        (self.root / "blobs" / h).write_bytes(data)
        return h

    def snapshot(self):
        return Snap({p.name: p.read_bytes() for p in (self.root / "blobs").iterdir()}, dict(self.records))


class World:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="warrant-pilot-"))
        self.store = Store(self.dir / "store")

    def blob(self, doc):
        return self.store.put_blob(C.canon(doc))

    def duty(self):
        rec = {"warrant": "3", "kind": "entity", "statement": "a record, not an object"}
        rid = C.doc_id(rec)                      # a record's id is its own digest, never its stored line's
        self.store.records[rid] = C.canon({"record": rec, "sig": None})
        return rid


class Objects:
    """A fanout object store: put(bytes) writes <dir>/<2 hex>/<62 hex> and returns the name."""

    def __init__(self, root):
        self.root = Path(root)

    def put(self, data):
        h = hashlib.sha256(data).hexdigest()
        (self.root / h[:2]).mkdir(parents=True, exist_ok=True)
        (self.root / h[:2] / h[2:]).write_bytes(data)
        return h


def check(cid, ok, what, detail=""):
    results[cid] = "PASS" if ok else "FAIL"
    print(("ok   " if ok else "FAIL ") + f"{cid} {what}" + ("" if ok else f" | {str(detail)[:300]}"), flush=True)


def finish(name):
    failed = sorted(k for k, v in results.items() if v == "FAIL")
    print(f"{name}: {sum(v == 'PASS' for v in results.values())} PASS / {len(failed)} FAIL" + (f" ({', '.join(failed)})" if failed else ""))
    if os.environ.get("WARRANT_RESULTS"):
        Path(os.environ["WARRANT_RESULTS"]).write_text(json.dumps(results))
    return 1 if failed else 0
