"""warrant: init, key, trust, bootstrap, put, attest, blob, assess, fmt (docs/V3.md). Output is JSON.

A seed is read from --key FILE (in the current directory or the operator's home, never through a path that
leaves both) or from WARRANT_KEY; every other file named is inside the current directory."""
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
from .store import Refused, Store, confined


def here(p):
    """A store, trust, profile or blob file: inside the current directory."""
    return confined(p, os.getcwd())


def home(p):
    """A seed: inside the current directory or the operator's home, never named by a path that leaves both."""
    p = os.path.expanduser(p)
    try:
        return confined(p, os.getcwd())
    except Refused:
        return confined(p, os.path.expanduser("~"))


def signer(a):
    seed = Path(home(a.key)).read_text() if a.key else os.environ.get("WARRANT_KEY")
    if not seed:
        raise Refused("a signing seed is needed: --key FILE or WARRANT_KEY")
    key, trust = K.Key.from_seed_hex(seed), json.loads(Path(here(a.trust)).read_text())
    if key.public not in trust["keys"].get(a.actor, []):
        raise Refused(f"the trust does not bind this key to {a.actor!r}")
    return key, trust


def put(a, kind, body, schema=None, lineage=None, refs=(), guard=None):
    key, trust = signer(a)
    at = a.at if a.at is not None else int(time.time())
    r = R.record(kind, a.actor, at, body, schema=schema, lineage=lineage, refs=refs, guard=guard)
    return Store(here(a.store)).append(r, key, trust, expect_head=a.expect_head)


def main(argv=None):
    p = argparse.ArgumentParser(prog="warrant")
    sub = p.add_subparsers(dest="cmd", required=True)
    cmds = {n: sub.add_parser(n) for n in ("init", "key", "trust", "bootstrap", "put", "attest", "blob", "assess", "fmt")}
    for n, c in cmds.items():
        if n not in ("key", "trust"):
            c.add_argument("--store", default=".warrant")
    for n in ("bootstrap", "put", "attest"):
        c = cmds[n]
        c.add_argument("--key")
        c.add_argument("--actor", required=True)
        c.add_argument("--trust", required=True)
        c.add_argument("--at", type=int)
        c.add_argument("--expect-head")
    cmds["key"].add_argument("--out", required=True)
    for f in ("--trust", "--actor", "--key"):
        cmds["trust"].add_argument(f, required=True)
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
            Store(here(a.store)).init()
            out = {"store": str(a.store)}
        elif a.cmd == "key":
            k = K.Key.generate()
            fd = os.open(home(a.out), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, k.seed_hex().encode())
            os.close(fd)
            out = {"public": k.public}
        elif a.cmd == "trust":           # bind the seed's public key to an actor in a trust/3 file (created if absent)
            key = K.Key.from_seed_hex(Path(home(a.key)).read_text())
            name = os.path.basename(a.trust)        # a trust file of the current directory, by its name alone
            if name != a.trust or name in ("", ".", ".."):
                raise Refused("--trust names a file of the current directory")
            path = Path(os.getcwd(), name)
            doc = json.loads(path.read_text()) if path.exists() else {"warrant": "trust/3", "keys": {}}
            doc["keys"][a.actor] = sorted(set(doc["keys"].get(a.actor, [])) | {key.public})
            why = E.trust_problem(doc)
            if why:
                raise Refused(why)
            path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            out = {"actor": a.actor, "public": key.public}
        elif a.cmd == "bootstrap":
            out = {"schemas": [put(a, "schema", s) for s in B.SCHEMAS]}
        elif a.cmd == "put":
            out = {"record": put(a, a.kind, a.body, a.schema, a.lineage, a.ref, a.guard)}
        elif a.cmd == "attest":
            out = {"record": put(a, "attest", dict(a.body, target=a.target), refs=[a.target])}
        elif a.cmd == "blob":
            out = {"blob": Store(here(a.store)).put_blob(Path(here(a.file)).read_bytes())}
        elif a.cmd == "fmt":
            s = Store(here(a.store))
            s.add_lines([])
            out = {"canonical": True}
        else:
            rep = E.assess(Store(here(a.store)).snapshot(), json.loads(Path(here(a.trust)).read_text()),
                           json.loads(Path(here(a.profile)).read_text()), a.as_of)
            out = rep if not a.lineage else {"lineage": rep["lineages"].get(a.lineage),
                                             "versions": {v: rep["versions"][v] for v in rep["lineages"].get(a.lineage, {}).get("versions", [])}}
    except (Refused, R.Invalid, OSError, ValueError) as e:
        print(f"REFUSED {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
