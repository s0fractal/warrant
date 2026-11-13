"""Where the bytes a cited hash names are (docs/HOME.md): one state for each hex64 a record of a registered store cites.

    PRESENT   in the citing store itself (a record line, or a blob);
    RESOLVED  its bytes were found elsewhere and hash to the name: a record or blob of another store of Home, or an
              object of a registered clone's Git: a cell or atom of a minds chain (refs/vars/heads/*: cas/cells/xx/...,
              cas/atoms/xx/..., named by the sha256 of their bytes);
    LOCATED   a place is known to name it, but its bytes are not here (a tree lists the path, the object is absent);
    MISSING   none of the above.

Where the bytes are is not whether they changed: freshness is `drift`'s, and nothing here says anything about it.
Bytes that do not hash to their name are a refusal (BYTES_MISMATCH), never MISSING: a transport is not trusted. Nothing
of a repository is executed or written: the stores are read as data, a clone through `git cat-file`, `ls-tree` and
`for-each-ref`. The answer carries `root` (every store's snapshot and every Git tip read) and `lens` (the code and the
query), as `across` does. A store names itself by its `repository` string, which it gives itself: no identity (an
obligation of stage 2: a store named by its root record).

    python -m warrant.resolve [ID ...] [--json]     # every cited id not PRESENT in its citing store, or these ids"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

from . import engine as E
from . import home as H
from . import jcs as C
from . import records as R
from . import shapes as S
from .pins import git
from .store import Store

FORMAT = "resolve/1"
STATES = ("PRESENT", "RESOLVED", "LOCATED", "MISSING")
GIT_PLACES = ("cas/cells", "cas/atoms")           # a minds chain's content-addressed objects, by the sha256 of their bytes


class Mismatch(Exception):
    """Bytes found under a name they do not hash to."""


def cited(record):
    """The hex64 ids a record cites: its refs, target, lineage, prev and requires."""
    b = record.get("body") or {}
    out = [x for x in record.get("refs") or [] if isinstance(x, str)]
    out += [x for x in (b.get("target"), record.get("lineage"), record.get("prev")) if isinstance(x, str)]
    out += [x for x in record.get("requires") or [] if isinstance(x, str)]
    return {x for x in out if S.hex64(x)}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class Place:
    """One registered repository: its store's snapshot and, where its clone has them, its refs/vars heads."""

    def __init__(self, name, repo_path, store_path):
        self.name, self.path = name, os.path.expanduser(repo_path)
        self.snap = Store(store_path).snapshot()
        self.records = {i: envs[0]["record"] for i, envs in self.snap.lines.items()}
        try:
            rows = git(self.path, "for-each-ref", "--format=%(objectname) %(refname)", "refs/vars/heads").splitlines()
        except (subprocess.CalledProcessError, OSError):
            rows = []
        self.tips = dict(reversed(r.split(" ", 1)) for r in rows if " " in r)

    def holds(self, i):
        return i in self.snap.lines or i in self.snap.blobs

    def bytes_of(self, i):
        """(bytes, where) of `i` as a record or blob of this store, verified, or None."""
        if i in self.snap.lines:
            if R.rid(self.records[i]) != i:
                raise Mismatch(f"{self.name}: a record line keyed {i[:12]} has another id")
            return C.canon(self.records[i]), f"store:{self.name}"
        if i in self.snap.blobs:
            if _sha(self.snap.blobs[i]) != i:
                raise Mismatch(f"{self.name}: the blob {i[:12]} does not hash to its name")
            return self.snap.blobs[i], f"store:{self.name}"
        return None

    def in_git(self, i):
        """("RESOLVED" | "LOCATED", where) of `i` in a refs/vars head of this clone, or None."""
        for ref, tip in sorted(self.tips.items()):
            for place in GIT_PLACES:
                path = f"{place}/{i[:2]}/{i[2:]}"
                try:
                    row = git(self.path, "ls-tree", tip, "--", path)
                except subprocess.CalledProcessError:
                    continue
                if not row:
                    continue
                oid = row.split()[2]
                try:
                    data = git(self.path, "cat-file", "blob", oid, raw=True)
                except subprocess.CalledProcessError:
                    return "LOCATED", f"git:{self.name}:{ref}:{path}"
                if _sha(data) != i:
                    raise Mismatch(f"git:{self.name}:{ref}:{path} does not hash to its name")
                return "RESOLVED", f"git:{self.name}:{ref}:{path}"
        return None


def places(doc):
    out, unavailable = [], []
    for name, r in sorted(doc["repositories"].items()):
        try:
            out.append(Place(name, r["path"], H.store_of(doc, name)))
        except (OSError, ValueError) as e:
            unavailable.append({"store": name, "why": f"{type(e).__name__}: {e}"[:200]})
    return out, unavailable


def state(i, home, others):
    """(state, where) of `i` cited from store `home`."""
    if home is not None and home.holds(i):
        return "PRESENT", f"store:{home.name}"
    for p in others:
        got = p.bytes_of(i)
        if got:
            return "RESOLVED", got[1]
    for p in [home, *others] if home is not None else others:
        got = p.in_git(i)
        if got:
            return got
    return "MISSING", None


def answer(doc, ids=None):
    """The resolve/1 answer over Home `doc`: for `ids`, each id's state; else each id a store cites that it does not
    hold, with the counts of every state over all cited ids."""
    ps, unavailable = places(doc)
    rows, counts = [], dict.fromkeys(STATES, 0)
    if ids:
        for i in sorted(set(ids)):
            s, where = state(i, None, ps)
            rows.append({"id": i, "state": s, "where": where, "cited_by": sorted(p.name for p in ps
                                                                                  if any(i in cited(r) for r in p.records.values()))})
            counts[s] += 1
    else:
        for p in ps:
            for i in sorted(set().union(*(cited(r) for r in p.records.values())) if p.records else set()):
                s, where = state(i, p, [q for q in ps if q is not p])
                counts[s] += 1
                if s != "PRESENT":
                    rows.append({"id": i, "state": s, "where": where, "cited_by": [p.name]})
    root = C.doc_id({"stores": {p.name: p.snap.digest for p in ps}, "git": {p.name: p.tips for p in ps if p.tips},
                     "unavailable": unavailable})
    lens = C.doc_id({"code": E.code_identity(), "query": {"ids": sorted(set(ids or []))}})
    return {"warrant": FORMAT, "completeness": "UNATTESTED", "untrusted": True, "root": root, "lens": lens,
            "stores": [p.name for p in ps], "unavailable": unavailable, "counts": counts, "rows": rows}


def run(argv=None):
    ap = argparse.ArgumentParser(prog="warrant resolve", description=__doc__.split("\n\n")[0])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    bad = [i for i in a.ids if not S.hex64(i)]
    if bad:
        print(f"REFUSED not a record or blob id: {bad[0][:80]!r}", file=sys.stderr)
        return 2
    try:
        out = answer(H.load(), a.ids)
    except Mismatch as e:
        print(f"REFUSED BYTES_MISMATCH {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"REFUSED {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(out, indent=1, sort_keys=True))
    else:
        print("cited ids: " + " · ".join(f"{s} {n}" for s, n in out["counts"].items()))
        for r in out["rows"]:
            print(f"{r['state']:<9} {r['id'][:12]} cited by {', '.join(r['cited_by']) or '-'}" + (f" · {r['where']}" if r["where"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(run())
