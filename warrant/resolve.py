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
query), as `across` does. Each store's `identities` entry is the root of its one self-signed rules@1 lineage
(warrant.graph.identity), or None: a store's `repository` string is one it gives itself, and another can copy it.

    python -m warrant.resolve [ID ...] [--json]     # every cited id not PRESENT in its citing store, or these ids"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

from . import engine as E
from . import graph as G
from . import home as H
from . import jcs as C
from . import records as R
from . import shapes as S
from .pins import git
from .store import Store

FORMAT = "resolve/1"
STATES = ("PRESENT", "RESOLVED", "LOCATED", "MISSING")
GIT_PLACES = ("cas/cells", "cas/atoms")           # a minds chain's content-addressed objects, by the sha256 of their bytes
# Standard VARS-1 cell schema hashes (minds verify/minds_verify.py H_SCHEMA).
MINDS_SCHEMAS = {
    "aaf70509e078bf1f833492eb82a116e4122232d424cf1668c05a9dd25855dcda": "axiom",
    "391bbd2090d93f580fe033df9109cff948d46a07db24b9db05d55dc84e84277b": "contract",
    "1c97bc0b74ffc978ade540c55592b294b0d9f2502b94b969f89ef00d99dd10bb": "computation",
    "77655a8f5ca5b1c6347634e9a5848fdacee6efefd58569242d39f43410747639": "checkpoint",
    "065f1b5b54fa199d65fb7f3e185e6f024d7523e829af1ad98269de018a8fb548": "cycle_witness",
    "5a48e9c69afc5c3cebb3ca2980052151f2aaa539052702e0e23f7ba5504eb6fb": "decision",
    "1293a1513baa6e0e1edfdcf8c8f4b992efa1391ddbc0889efe9698d59c9b0cdf": "question",
    "c661936c020c0d817b8516b93454af5a30fe4282d854c1b0f628731c80f95d66": "acceptance",
    "9aab50548f8fc7c5e2090fa89a73440af7de5e92d800b928261f13f20a4bd2a9": "scope",
    "ad702699d5fc7b3d94138c38643c9889f1520a6e1c20760aa6b11a8e273dfdae": "verdict",
    "8029ae880cb62a8034f47ec44e8f5c5982ebc14a14be2c6893a3ab8f968aa818": "projection",
}


def minds_cell_schema(data):
    """Schema label (`minds:<name>`) of a VARS-1 cell's raw bytes, or None if not a known VARS-1 cell."""
    if len(data) < 296 or data[:7] != b"VAR1\x00\x00\x00":
        return None
    k = data[7]
    if k > 64 or len(data) != 296 + 32 * k:
        return None
    name = MINDS_SCHEMAS.get(data[8:40].hex())
    return f"minds:{name}" if name else None


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
        trust, profile, _ = H.receiver(self.path)
        try:
            self.identity = G.identity(E.View(self.snap, trust, profile).report(), self.snap)["identity"]
        except Exception:                # NOSONAR S112: a store its own rules cannot assess has no identity, and still resolves
            self.identity = None
        self.records = {i: envs[0]["record"] for i, envs in self.snap.lines.items()}
        try:
            rows = git(self.path, "for-each-ref", "--format=%(objectname) %(refname)", "refs/vars/heads").splitlines()
        except (subprocess.CalledProcessError, OSError):
            rows = []
        self.tips = dict(reversed(r.split(" ", 1)) for r in rows if " " in r)
        self.cell_schemas = {}

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
                where = f"git:{self.name}:{ref}:{path}"
                if place == "cas/cells":
                    label = minds_cell_schema(data)
                    if label is not None:
                        self.cell_schemas[where] = label
                return "RESOLVED", where
        return None


def places(doc):
    out, unavailable = [], []
    for name, r in sorted(doc["repositories"].items()):
        try:
            out.append(Place(name, r["path"], H.store_of(doc, name)))
        except (OSError, ValueError) as e:
            unavailable.append({"store": name, "why": f"{type(e).__name__}: {e}"[:200]})
    return out, unavailable


def stores(ps):
    """The places of each store (obligation ec6d1ebe; Codex on its closure): places of one identity are one store,
    keyed `rules@1:<identity>`, whose citations count once; a place with no identity is a store by its name."""
    out = {}
    for p in ps:
        out.setdefault(f"rules@1:{p.identity}" if p.identity else p.name, []).append(p)
    return out


def state(i, home, others):
    """(state, where) of `i` cited from store `home`, the places of one store (none for an id asked for)."""
    for p in home:
        if p.holds(i):
            return "PRESENT", f"store:{p.name}"
    for p in others:
        got = p.bytes_of(i)
        if got:
            return "RESOLVED", got[1]
    for p in [*home, *others]:
        got = p.in_git(i)
        if got:
            return got
    return "MISSING", None


def answer(doc, ids=None):
    """The resolve/1 answer over Home `doc`: for `ids`, each id's state; else each id a store cites that it does not
    hold, with the counts of every state over all cited ids."""
    ps, unavailable = places(doc)
    rows, counts = [], dict.fromkeys(STATES, 0)
    def _row(i, s, where, cited_by):
        row = {"id": i, "state": s, "where": where, "cited_by": cited_by}
        if s == "RESOLVED" and where:
            schema = next((p.cell_schemas[where] for p in ps if where in p.cell_schemas), None)
            if schema is not None:
                row["schema"] = schema
        return row

    if ids:
        for i in sorted(set(ids)):
            s, where = state(i, [], ps)
            rows.append(_row(i, s, where, sorted(p.name for p in ps if any(i in cited(r) for r in p.records.values()))))
            counts[s] += 1
    else:
        for _, home in sorted(stores(ps).items()):
            recs = [r for p in home for r in p.records.values()]
            for i in sorted(set().union(*(cited(r) for r in recs)) if recs else set()):
                s, where = state(i, home, [q for q in ps if q not in home])
                counts[s] += 1
                if s != "PRESENT":
                    rows.append(_row(i, s, where, [p.name for p in home]))
    root = C.doc_id({"stores": {p.name: p.snap.digest for p in ps}, "git": {p.name: p.tips for p in ps if p.tips},
                     "unavailable": unavailable})
    lens = C.doc_id({"code": E.code_identity(), "query": {"ids": sorted(set(ids or []))}})
    return {"warrant": FORMAT, "completeness": "UNATTESTED", "untrusted": True, "root": root, "lens": lens,
            "stores": [p.name for p in ps], "identities": {p.name: p.identity for p in ps}, "unavailable": unavailable,
            "counts": counts, "rows": rows}


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
        for name, ident in out["identities"].items():
            print(f"store {name}: " + (f"identity {ident[:12]}" if ident else "no identity (named by where it is read)"))
        print("cited ids: " + " · ".join(f"{s} {n}" for s, n in out["counts"].items()))
        for r in out["rows"]:
            extra = (f" · {r['schema']}" if r.get("schema") else "") + (f" · {r['where']}" if r["where"] else "")
            print(f"{r['state']:<9} {r['id'][:12]} cited by {', '.join(r['cited_by']) or '-'}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
