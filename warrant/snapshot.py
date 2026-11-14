"""Witnessed snapshots of a store (docs/V3.md §16, stage 3): `snapshot@1`.

A witness is an actor that, before it signs, checks that the store it sees holds every record of the store it
witnessed last, and then files a version of its own `snapshot@1` lineage naming what it saw: the two Merkle roots of
the store (warrant.merkle: its record ids, its reverse index), how many leaves each has, each writer's head, the
commit it read and the store's digest. Its versions succeed one another (`lineage`: the version before), so two
versions of one witness after the same one are a FORK of that lineage: the engine's own verdict on a witness that
showed two histories, and the pair of records is the proof (`warrant verify` reads it offline).

What a witness says is no more than what it saw under that root: it is never a claim that nothing else exists
anywhere. A reader that holds a witness's root may ask whether an id is in it and what stands against an id in it
(warrant.merkle proofs); `completeness` stays UNATTESTED, and the answer is an `absence` that names its root and its
witness. While every witness writes to the same place the store does (one account), the floor says so.

The schema is filed by whoever wants witnessing (`python -m warrant.snapshot schema`), not by `warrant bootstrap`: a
store that has no witness is unchanged.

    python -m warrant.snapshot schema  --actor A --key K      # file snapshot@1 (an author of schemas)
    python -m warrant.snapshot witness --actor W --key K      # check the last witnessed store is held, file a version
    python -m warrant.snapshot show [--json]                  # the store's roots now, and each witness's leaf"""
import argparse
import json
import subprocess
import sys

from . import engine as E
from . import merkle as M
from . import records as R
from . import shapes as S
from .pins import git
from .repo import Failed, Repo, dump, env_root, load_key, main
from .store import Snapshot

SCHEMA = {"name": "snapshot@1",
          "fields": {"state": "str", "repository": "str", "commit": "str", "records": "str", "index": "str",
                     "size": "obj", "heads": "obj", "digest": "str", "format": "str"},
          "states": {"witnessed": None}, "closed": [], "successors": {}}
NAME = SCHEMA["name"]
RECORDS = ".warrant/records.jsonl"


def body(snap, trust, repository, commit):
    """What a witness says of `snap`: its roots, sizes, every trusted writer's head, the commit and the digest."""
    r = M.roots(snap)
    heads = {a: E.head(snap, trust, a)["id"] for a in sorted(trust.get("keys", {}))}
    return {"state": "witnessed", "repository": repository, "commit": commit, "format": r["format"],
            "records": r["records"], "index": r["index"], "size": r["size"],
            "heads": {a: h for a, h in heads.items() if h}, "digest": snap.digest}


def at_commit(root, commit):
    """The snapshot of the store's records at `commit` of the clone at `root` (no blobs: the roots name none). A
    commit read from a record reaches Git only as a full commit id."""
    if not S.hex_of(commit, 40):
        raise Failed("SNAPSHOT_COMMIT", f"{str(commit)[:50]!r} is not a full commit id")
    try:
        data = git(root, "show", f"{commit}:{RECORDS}", raw=True)
    except subprocess.CalledProcessError:
        raise Failed("SNAPSHOT_COMMIT", f"{RECORDS} cannot be read at {str(commit)[:12]}") from None
    return Snapshot([ln + b"\n" for ln in data.split(b"\n") if ln], {})


def leaves(rep, actor):
    """[version] of the leaf of each snapshot@1 lineage `actor` began; every version no other succeeds, when forked."""
    out = []
    for L, lin in rep["lineages"].items():
        if lin["schema"] != NAME or rep["_recs"][L]["actor"] != actor:
            continue
        parents = {rep["_recs"][v]["lineage"] for v in lin["versions"] if v != L}
        out += [lin["leaf"]] if lin["leaf"] else [v for v in lin["versions"] if v not in parents]
    return out


def holds(old, new):
    """[(code, detail)] of what keeps `new` from holding `old`: a record of `old` that `new` lacks."""
    gone = sorted(set(old.lines) - set(new.lines))
    return [("SNAPSHOT_SHRANK", f"{len(gone)} record(s) of the store witnessed last are not in this one: "
             + ", ".join(g[:12] for g in gone[:8]))] if gone else []


def witness(repo, actor, key, commit=None):
    """File the next version of `actor`'s snapshot lineage for the store at `commit` (HEAD by default), after checking
    that it holds the store its last version witnessed (read at that version's commit) and that its last version's
    roots are that store's. Returns the id filed."""
    trust, _, name = repo.config()
    commit = commit or git(repo.root, "rev-parse", "HEAD").strip()
    now = at_commit(repo.root, commit)
    rep = repo.report()
    last = leaves(rep, actor)
    if len(last) > 1:
        raise Failed("SNAPSHOT_FORKED", f"{actor}'s snapshot lineage is forked: a witness that showed two histories "
                     "files no more")
    prev = None
    if last:
        prev = last[0]
        b = rep["_recs"][prev]["body"]
        old = at_commit(repo.root, b["commit"])
        r = M.roots(old)
        if (r["records"], r["index"]) != (b["records"], b["index"]):
            raise Failed("SNAPSHOT_ROOTS", f"the store at {b['commit'][:12]} does not have the roots {prev[:12]} names")
        bad = holds(old, now)
        if bad:
            raise Failed(*bad[0])
    rec = R.record("entity", actor, 0, body(now, trust, name, commit), NAME, lineage=prev, refs=[])
    return repo.file(actor, key, [rec])[0]


def roots_now(repo):
    snap = repo.store.snapshot()
    return dict(M.roots(snap), digest=snap.digest)


def run(argv=None):
    root, argv = env_root(list(sys.argv[1:] if argv is None else argv))
    ap = argparse.ArgumentParser(prog="warrant snapshot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("schema", "witness"):
        p = sub.add_parser(n)
        p.add_argument("--actor", required=True)
        p.add_argument("--key", required=True)
    sub.choices["witness"].add_argument("--commit")
    sub.add_parser("show").add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    repo = Repo(root)
    if a.cmd == "schema":
        rec = R.record("schema", a.actor, 0, SCHEMA)
        dump({"schema": repo.file(a.actor, load_key(a.key, root), [rec])[0]})
        return 0
    if a.cmd == "witness":
        if a.commit is not None and not S.hex_of(a.commit, 40):
            raise Failed("BAD_REQUEST", "--commit is a full commit id")
        dump({"snapshot": witness(repo, a.actor, load_key(a.key, root), a.commit)})
        return 0
    rep = repo.report()
    out = {"roots": roots_now(repo), "witnesses": {}}
    for L, lin in rep["lineages"].items():
        if lin["schema"] == NAME:
            out["witnesses"][L] = {"actor": rep["_recs"][L]["actor"], "leaf": lin["leaf"], "forks": lin["forks"],
                                   "reliance": lin["reliance"]}
    if a.json:
        dump(out)
    else:
        r = out["roots"]
        print(f"roots       records {r['records'][:12]} ({r['size']['records']}) · index {r['index'][:12]} ({r['size']['index']})")
        for L, w in sorted(out["witnesses"].items()):
            print(f"witness     {w['actor']} {L[:12]}: " + (f"leaf {w['leaf'][:12]}" if w["leaf"] else
                                                          f"FORKED ({len(w['forks'])}): two histories shown"))
    return 0


if __name__ == "__main__":
    sys.exit(main(run))
