"""warrant3: init, key, bootstrap, put, attest, blob, assess, fmt (docs/V3.md). Output is JSON."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from warrant import keys as K

from . import bootstrap as B
from . import engine as E
from . import records as R
from .store import Refused, Store


def signer(a):
    seed = Path(a.key).read_text() if a.key else os.environ.get("WARRANT_KEY")
    if not seed:
        raise Refused("a signing seed is needed: --key FILE or WARRANT_KEY")
    key, trust = K.Key.from_seed_hex(seed), json.loads(Path(a.trust).read_text())
    if key.public not in trust["keys"].get(a.actor, []):
        raise Refused(f"the trust does not bind this key to {a.actor!r}")
    return key, trust


def put(a, kind, body, schema=None, lineage=None, refs=(), guard=None):
    key, trust = signer(a)
    at = a.at if a.at is not None else int(time.time())
    r = R.record(kind, a.actor, at, body, schema=schema, lineage=lineage, refs=refs, guard=guard)
    return Store(a.store).append(r, key, trust, expect_head=a.expect_head)


def main(argv=None):
    p = argparse.ArgumentParser(prog="warrant3")
    sub = p.add_subparsers(dest="cmd", required=True)
    cmds = {n: sub.add_parser(n) for n in ("init", "key", "bootstrap", "put", "attest", "blob", "assess", "fmt")}
    for n, c in cmds.items():
        if n != "key":
            c.add_argument("--store", default=".warrant")
    for n in ("bootstrap", "put", "attest"):
        c = cmds[n]
        c.add_argument("--key")
        c.add_argument("--actor", required=True)
        c.add_argument("--trust", required=True)
        c.add_argument("--at", type=int)
        c.add_argument("--expect-head")
    cmds["key"].add_argument("--out", required=True)
    c = cmds["put"]
    c.add_argument("--kind", required=True, choices=R.KINDS)
    c.add_argument("--schema")
    c.add_argument("--lineage")
    c.add_argument("--ref", action="append", default=[])
    c.add_argument("--guard", type=json.loads)
    c.add_argument("body", type=json.loads)
    c = cmds["attest"]
    c.add_argument("target")
    c.add_argument("--body", type=json.loads, default={"verdict": "accept"})
    cmds["blob"].add_argument("file")
    c = cmds["assess"]
    c.add_argument("--trust", required=True)
    c.add_argument("--profile", required=True)
    c.add_argument("--as-of", type=int)
    c.add_argument("--lineage")
    a = p.parse_args(argv)
    try:
        if a.cmd == "init":
            Store(a.store).init()
            out = {"store": str(a.store)}
        elif a.cmd == "key":
            k = K.Key.generate()
            fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, k.seed_hex().encode())
            os.close(fd)
            out = {"public": k.public}
        elif a.cmd == "bootstrap":
            out = {"schemas": [put(a, "schema", s) for s in B.SCHEMAS]}
        elif a.cmd == "put":
            out = {"record": put(a, a.kind, a.body, a.schema, a.lineage, a.ref, a.guard)}
        elif a.cmd == "attest":
            out = {"record": put(a, "attest", dict(a.body, target=a.target), refs=[a.target])}
        elif a.cmd == "blob":
            out = {"blob": Store(a.store).put_blob(Path(a.file).read_bytes())}
        elif a.cmd == "fmt":
            s = Store(a.store)
            s.write_lines([x + b"\n" for x in s.file.read_bytes().split(b"\n") if x])
            out = {"canonical": True}
        else:
            rep = E.assess(Store(a.store).snapshot(), json.loads(Path(a.trust).read_text()),
                           json.loads(Path(a.profile).read_text()), a.as_of)
            out = rep if not a.lineage else {"lineage": rep["lineages"].get(a.lineage),
                                             "versions": {v: rep["versions"][v] for v in rep["lineages"].get(a.lineage, {}).get("versions", [])}}
    except (Refused, R.Invalid, OSError, ValueError) as e:
        print(f"REFUSED {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
