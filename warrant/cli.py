"""warrant: one command. The core's verbs init, key, trust, bootstrap, put, attest, blob, assess and fmt
(docs/V3.md; output is JSON); status, a reader's summary of a store; and the review loop's commands review,
gate, claims and roadmap (`warrant review ...` is `python -m warrant.review ...`; docs/REPOSITORY.md).

The store is --store, else the nearest `.warrant/` from the current directory upward (WARRANT_REPO_ROOT's when
it is set; `init` creates it in the current directory). The trust and the profile are --trust and --profile,
else that store's `v3.json` (docs/REPOSITORY.md): a repository is assessed under its own receiver configuration
with no flag. A seed is read from --key FILE (in the current directory or the operator's home, never through a
path that leaves both) or from WARRANT_KEY; every other file named is inside the current directory."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from warrant import keys as K

from . import bootstrap as B
from . import engine as E
from . import graph as G
from . import records as R
from .store import Refused, Store, confined

LOOP = ("review", "gate", "claims", "roadmap")       # the review loop's commands, each its own module's parser
RECEIVER = "v3.json"                                 # a repository's trust and profile, in its store directory


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


def store_dir(a):
    """--store inside the current directory; else WARRANT_REPO_ROOT's `.warrant`; else the nearest `.warrant/`
    directory from the current one upward; else (and for `init`) the current directory's."""
    if a.store is not None:
        return here(a.store)
    if os.environ.get("WARRANT_REPO_ROOT"):
        return str(Path(os.environ["WARRANT_REPO_ROOT"]) / ".warrant")
    cwd = Path(os.getcwd())
    if a.cmd != "init":
        for d in (cwd, *cwd.parents):
            if (d / ".warrant").is_dir():
                return str(d / ".warrant")
    return str(cwd / ".warrant")


def receiver(a, store):
    """(trust, profile, repository name or None): each of --trust and --profile when given, else the store's
    v3.json; refused when neither names it."""
    doc = None
    if not (getattr(a, "trust", None) and getattr(a, "profile", None)):
        f = Path(store) / RECEIVER
        if not f.is_file():
            raise Refused(f"no --trust/--profile and no {RECEIVER} in the store {store}")
        doc = json.loads(f.read_text())
        if not (isinstance(doc, dict) and isinstance(doc.get("trust"), dict) and isinstance(doc.get("profile"), dict)):
            raise Refused(f"{f} is not a receiver configuration {{repository, trust, profile}}")
    trust = json.loads(Path(here(a.trust)).read_text()) if getattr(a, "trust", None) else doc["trust"]
    profile = json.loads(Path(here(a.profile)).read_text()) if getattr(a, "profile", None) else doc["profile"]
    for why in (E.trust_problem(trust), E.profile_problem(profile)):
        if why:
            raise Refused(why)
    return trust, profile, (doc or {}).get("repository")


def signer(a):
    seed = Path(home(a.key)).read_text() if a.key else os.environ.get("WARRANT_KEY")
    if not seed:
        raise Refused("a signing seed is needed: --key FILE or WARRANT_KEY")
    key = K.Key.from_seed_hex(seed)
    trust = json.loads(Path(here(a.trust)).read_text()) if a.trust else receiver(a, store_dir(a))[0]
    if key.public not in trust["keys"].get(a.actor, []):
        raise Refused(f"the trust does not bind this key to {a.actor!r}")
    return key, trust


def put(a, kind, body, schema=None, lineage=None, refs=(), guard=None):
    key, trust = signer(a)
    at = a.at if a.at is not None else int(time.time())
    r = R.record(kind, a.actor, at, body, schema=schema, lineage=lineage, refs=refs, guard=guard)
    return Store(store_dir(a)).append(r, key, trust, expect_head=a.expect_head)


def _parser():
    p = argparse.ArgumentParser(prog="warrant")
    sub = p.add_subparsers(dest="cmd", required=True)
    cmds = {n: sub.add_parser(n) for n in ("init", "key", "trust", "bootstrap", "put", "attest", "blob", "assess", "fmt",
                                           "status")}
    for n in LOOP:
        sub.add_parser(n, help=f"python -m warrant.{n} (its own arguments)", add_help=False)
    for n, c in cmds.items():
        if n not in ("key", "trust"):
            c.add_argument("--store")
    for n in ("bootstrap", "put", "attest"):
        c = cmds[n]
        c.add_argument("--key")
        c.add_argument("--actor", required=True)
        c.add_argument("--trust")
        c.add_argument("--at", type=int)
        c.add_argument("--expect-head")
    cmds["key"].add_argument("--out", required=True)
    cmds["trust"].add_argument("--trust", required=True)
    cmds["trust"].add_argument("--bind", action="append", required=True, metavar="ACTOR=SEED")
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
    for n in ("assess", "status"):
        c = cmds[n]
        c.add_argument("--trust")
        c.add_argument("--profile")
        c.add_argument("--as-of", type=int)
    cmds["assess"].add_argument("--lineage")
    cmds["status"].add_argument("--actor", help="also what waits for this actor")
    cmds["status"].add_argument("--json", action="store_true")
    return p


def _trust(a):
    """A trust/3 file binding each seed's public key to its actor, written whole in the current directory."""
    keys = {}
    for b in a.bind:
        actor, _, seed = b.partition("=")
        keys.setdefault(actor, set()).add(K.Key.from_seed_hex(Path(home(seed)).read_text()).public)
    doc = {"warrant": "trust/3", "keys": {x: sorted(v) for x, v in sorted(keys.items())}}
    why = E.trust_problem(doc)
    if why:
        raise Refused(why)
    name = os.path.basename(a.trust)        # a trust file of the current directory, by its name alone
    if name != a.trust or name in ("", ".", ".."):
        raise Refused("--trust names a file of the current directory")
    Path(os.getcwd(), name).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return doc


def _assess(a):
    store = store_dir(a)
    trust, profile, _ = receiver(a, store)
    rep = E.assess(Store(store).snapshot(), trust, profile, a.as_of)
    if not a.lineage:
        return rep
    return {"lineage": rep["lineages"].get(a.lineage),
            "versions": {v: rep["versions"][v] for v in rep["lineages"].get(a.lineage, {}).get("versions", [])}}


def status(a):
    """A reader's summary of one store under its receiver: the snapshot, the schemas, lineages by schema and
    state, reliance, what is wrong, and (with --actor) what waits for that actor (warrant.graph.frontier)."""
    store = store_dir(a)
    trust, profile, name = receiver(a, store)
    snap = Store(store).snapshot()
    rep = E.assess(snap, trust, profile, a.as_of)
    lineages, reliance = {}, {}
    for lin in rep["lineages"].values():
        by, state = lineages.setdefault(lin["schema"], {}), lin["state"] or "none"     # none: no effective version yet
        by[state] = by.get(state, 0) + 1
        reliance[lin["reliance"]] = reliance.get(lin["reliance"], 0) + 1
    return {"repository": name, "store": store, "snapshot": rep["snapshot"], "assessment": rep["assessment"],
            "records": len(snap.lines), "blobs": len(snap.blobs), "canonical": rep["canonical"],
            "completeness": rep["completeness"], "rejected": len(rep["rejected"]),
            "chain_forks": sorted({f[0] for f in rep["chains"]["forks"]}), "schemas": sorted(rep["schemas"]),
            "schemas_pending": sorted(rep["schemas_pending"]), "problems": rep["problems"],
            "lineages": {k: dict(sorted(v.items())) for k, v in sorted(lineages.items())},
            "reliance": dict(sorted(reliance.items())),
            "frontier": G.frontier(rep, profile, a.actor) if a.actor else None}


def _counts(d):
    return " · ".join(f"{k} {n}" for k, n in d.items()) or "none"


def render(st):
    """`status` for a person: one line per fact, the same facts as its --json."""
    rows = [("repository", st["repository"] or "(no repository named)"),
            ("store", f"{st['store']} · snapshot {st['snapshot'][:12]}"),
            ("records", f"{st['records']} · blobs {st['blobs']} · {'canonical' if st['canonical'] else 'NOT canonical'}"
                        f" · rejected {st['rejected']} · completeness {st['completeness']}"),
            ("schemas", ", ".join(st["schemas"]) + (f" (pending: {', '.join(st['schemas_pending'])})" if st["schemas_pending"] else ""))]
    w = max([len(k) for k in st["lineages"]] or [0])
    rows += [("lineages" if i == 0 else "", f"{k.ljust(w)}  {_counts(v)}") for i, (k, v) in enumerate(st["lineages"].items())]
    rows += [("reliance", _counts(st["reliance"])),
             ("chain forks", ", ".join(st["chain_forks"]) or "none"),
             ("problems", f"{len(st['problems'])}" if st["problems"] else "none")]
    f = st["frontier"]
    if f:
        rows.append((f["actor"], f"may attest {len(f['attest'])} · own pending {len(f['pending'])} · challenged {len(f['challenged'])}"
                                 f" · roles {', '.join(f['roles']) or 'none'}"))
        rows += [("", f"{x['version'][:12]}  {x['schema']}  {'; '.join(x['waiting'])}") for x in f["attest"]]
    return "".join(f"{k.ljust(12)}{v}\n" for k, v in rows)


def loop(argv):
    """`warrant review|gate|claims|roadmap ARGS`: that module's own command, unchanged."""
    from . import claims, gate, review, roadmap
    from .repo import main as run_tool
    mod = {"review": review, "gate": gate, "claims": claims, "roadmap": roadmap}[argv[0]]
    return mod.main(argv[1:]) if mod is gate else run_tool(mod.run, argv[1:])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] and argv[0] in LOOP:
        return loop(argv)
    a = _parser().parse_args(argv)
    if a.cmd == "status":
        try:
            st = status(a)
        except (OSError, ValueError) as e:
            print(f"REFUSED {e}", file=sys.stderr)
            return 2
        sys.stdout.write(json.dumps(st, indent=1, sort_keys=True) + "\n" if a.json else render(st))
        return 0
    try:
        if a.cmd == "init":
            store = store_dir(a)
            Store(store).init()
            out = {"store": a.store if a.store is not None else store}     # as named, else where it went
        elif a.cmd == "key":
            k = K.Key.generate()
            fd = os.open(home(a.out), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, k.seed_hex().encode())
            os.close(fd)
            out = {"public": k.public}
        elif a.cmd == "trust":
            out = _trust(a)
        elif a.cmd == "bootstrap":
            out = {"schemas": [put(a, "schema", s) for s in B.SCHEMAS]}
        elif a.cmd == "put":
            out = {"record": put(a, a.kind, a.body, a.schema, a.lineage, a.ref, a.guard)}
        elif a.cmd == "attest":
            out = {"record": put(a, "attest", dict(a.body, target=a.target), refs=[a.target])}
        elif a.cmd == "blob":
            out = {"blob": Store(store_dir(a)).put_blob(Path(here(a.file)).read_bytes())}
        elif a.cmd == "fmt":
            s = Store(store_dir(a))
            s.add_lines([])
            snap = s.snapshot()
            out = {"canonical": snap.canonical, "rejected": len(snap.rejected)}     # sorted is not canonical with a rejected line
        else:
            out = _assess(a)
    except (OSError, ValueError) as e:      # a store's refusal and an invalid record are ValueErrors

        print(f"REFUSED {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
