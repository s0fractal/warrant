"""Anchors: one store witnessed in another (docs/V3.md §16, cross-store witnessing): `anchor@1`.

A `snapshot@1` lies in the store it witnesses, so whoever rewrites that store's history rewrites its witness with it
(§16: "while a witness writes where the store does, its word is that account's"). An anchor lies in another store. A
witness that holds store B and reads store A files, in B, versions of an `anchor@1` lineage of its own for A: each names
A's identity (its `rules@1` genesis, warrant.graph.identity), the commit read, A's records root and size, A's digest,
and `added`, a blob of B holding the ids A gained since the version before, sorted, 32 bytes each. The lineage's blobs
together are every id A held at its leaf: B alone keeps what A was, and to rewrite A's history unseen one must rewrite
every store that anchors it too.

A store is a set of lines sorted by id, merged by union (§8), not a log: a new record lands anywhere in its records
tree, so no Merkle proof of the tree alone says that a later store holds an earlier one. The ids are the proof
instead, held where A cannot reach them. A witness checks two things before it signs: that its own blobs make the root
its leaf named (the anchors are honest), and that A now holds every id they name (`ANCHOR_REWRITTEN` names what is
gone). An id covers a record's content, not its signature: a line held with its signature spoiled still counts as held
here (`snapshot@1` compares lines).

What an anchor establishes: that A, read at that commit, held those records, by the witness's word, kept in B. Not
that A holds nothing else, nor that B was not rewritten as well: B's defence is its own anchors elsewhere. While the
witness and A's writers are one account, the anchor is that account's word, and says so in `check`.

    python -m warrant.anchor --root DIR init --actor W --key K --repository NAME   # a witness's store of its own
    python -m warrant.anchor schema  --actor W --key K                 # file anchor@1 in this store
    python -m warrant.anchor witness --of CLONE|ADDRESS [--commit C] --actor W --key K
    python -m warrant.anchor check   --of CLONE|ADDRESS [--commit C] [--json]  # exit 0 held, 1 rewritten or not anchored

ADDRESS is github.com/OWNER/NAME[/tree/BRANCH] (read at one commit) or an HTTPS root serving .warrant/: a witness need
not clone the store it anchors."""
import argparse
import json
import sys
from pathlib import Path

from . import engine as E
from . import graph as G
from . import merkle as M
from . import records as R
from . import shapes as S
from .pins import git
from .repo import Failed, Repo, dump, env_root, load_key, main
from .snapshot import at_commit
from .store import Snapshot, _line_id

SCHEMA = {"name": "anchor@1",
          "fields": {"state": "str", "store": "str", "repository": "str", "commit": "str", "records": "str",
                     "size": "int", "digest": "str", "added": "str", "format": "str"},
          "states": {"witnessed": None}, "closed": [], "successors": {}}
NAME = SCHEMA["name"]


ADDRESS = ("https://", "http://", "github.com/", "www.github.com/")


def is_address(of):
    """`of` names a store by its address (read over HTTPS, nothing cloned), not a clone on disk."""
    return isinstance(of, str) and of.startswith(ADDRESS)


def read(of, commit=None, allow=frozenset()):
    """(commit, snapshot, identity, repository, trust) of the store at `of`: a clone on disk, read at `commit` (HEAD by
    default), or an address. A GitHub address is read at one commit, `commit` or the one its branch names now (GitHub's
    commits API), so an anchor by address names the bytes an anchor by clone would; another HTTPS root has no commit
    (`""`) and takes none. Either is assessed under the receiver its own v3.json gives; only its own records.jsonl is
    anchored, never a source it declares."""
    if is_address(of):
        return _read_address(of, commit, allow)
    commit = commit or git(of, "rev-parse", "HEAD").strip()
    snap = at_commit(of, commit)
    try:
        doc = json.loads(git(of, "show", f"{commit}:.warrant/v3.json"))
    except Exception:
        raise Failed("ANCHOR_CONFIG", f".warrant/v3.json cannot be read at {commit[:12]}") from None
    return (commit, snap, *_identity(snap, doc), doc["trust"])


def _identity(snap, doc):
    ident = G.identity(E.View(snap, doc["trust"], doc["profile"]).report(), snap)
    if not ident["identity"]:
        raise Failed("ANCHOR_IDENTITY", f"the store names itself by nothing an anchor can keep: {ident['why']}")
    return ident["identity"], doc.get("repository", "")


def _read_address(of, commit, allow):
    from warrant_agent import remote as RM          # the HTTPS reader, its host rules and budget (docs/AGENT.md)
    from warrant_agent.config import DEFAULT_LIMITS
    from warrant_agent.errors import AgentError
    from warrant_agent.rely import address
    try:
        url = RM._checked(address(of), set(allow))
        if RM.RAW.match(url):
            ref = url[len(RM.RAW.match(url)[0]):].rstrip("/")
            commit = commit or RM.source_commit(url, ref)
            if not commit:
                raise Failed("ANCHOR_COMMIT", f"GitHub names no commit for {ref!r} of {url}")
            url = RM.source_base(url, commit)
        elif commit:
            raise Failed("BAD_REQUEST", "--commit names a commit of a GitHub address; this root serves no commits")
        ws = RM.Remote(url, dict(DEFAULT_LIMITS))
    except AgentError as e:
        raise Failed("ANCHOR_READ", f"{of}: {e.code}: {e}") from None
    snap = Snapshot([ln for ln in ws.snap.raw if _line_id(ln)[0] in ws.own], {})
    return (commit or "", snap, *_identity(snap, ws.doc), ws.doc["trust"])


def lineages(rep, store):
    """{root: [versions in lineage order]} of every anchor@1 lineage of `store` (an identity) in this report."""
    out = {}
    for L, lin in rep["lineages"].items():
        if lin["schema"] == NAME and rep["_recs"][L]["body"].get("store") == store:
            out[L] = lin
    return out


def ids_of(blob):
    """The sorted, distinct 32-byte ids of an `added` blob, or None when it is not one."""
    if blob is None or len(blob) % 32:
        return None
    ids = [blob[i:i + 32].hex() for i in range(0, len(blob), 32)]
    return ids if ids == sorted(set(ids)) else None


def held(blob, rep, lin):
    """(ids, problem) along one anchor lineage up to its leaf: the union of its versions' `added`, each version's root
    made again from the union so far (a witness whose blobs do not make the roots it signed is caught here). `blob`
    gives a blob's bytes by its id, or None: the anchoring store's, read from disk or over HTTPS."""
    if not lin["leaf"]:
        return None, f"FORKED ({len(lin['forks'])}): the witness showed two histories"
    chain, v = [], lin["leaf"]
    while v is not None:
        chain.append(v)
        v = rep["_recs"][v].get("lineage")
    have = set()
    for v in reversed(chain):
        b = rep["_recs"][v]["body"]
        got = ids_of(blob(b["added"]) if S.hex64(b.get("added")) else None)
        if got is None:
            return None, f"{v[:12]}: its `added` is no blob of sorted ids in this store"
        if have & set(got):
            return None, f"{v[:12]}: its `added` names ids an earlier version had"
        have |= set(got)
        if M.root([bytes.fromhex(i) for i in sorted(have)]) != b["records"] or len(have) != b["size"]:
            return None, f"{v[:12]}: its blobs do not make the records root it signed"
    return have, None


def init(root, actor, key, repository):
    """Make at `root` a witness's store of its own: a v3.json binding `actor` to `key` and naming it the one schema
    author, the rules@1 genesis (that v3.json, self-signed: the store's identity, §14) and anchor@1. A store that would
    otherwise anchor nothing (its rules counting no anchor@1, as a store whose schema quorum waits) gets one this way,
    under rules no other store's writers hold. [ids filed]; refused where a store is already."""
    from .gate import RULES, RULES_SCHEMA
    root = Path(root)
    if (root / ".warrant").exists() or (root / ".warrant").is_symlink():
        raise Failed("ANCHOR_INIT", f"{root} holds a store already")
    (root / ".warrant" / "blobs").mkdir(parents=True, exist_ok=True)
    doc = {"warrant": "repository/3", "repository": repository,
           "trust": {"warrant": "trust/3", "keys": {actor: [key.public]}},
           "profile": {"warrant": "profile/3", "quorum": {E.SCHEMA_AUTHOR: 1}, "roles": {E.SCHEMA_AUTHOR: [actor]}}}
    (root / ".warrant" / "v3.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    repo = Repo(root)
    ids = repo.file(actor, key, [R.record("schema", actor, 0, RULES_SCHEMA), R.record("schema", actor, 0, SCHEMA)])
    return ids + repo.file(actor, key, [R.record("entity", actor, 0, dict(doc, state="in force"), RULES, refs=[])])


def witness(repo, of, actor, key, commit=None, allow=frozenset()):
    """File the next version of `actor`'s anchor lineage for the store at `of` (a clone or an address); its id."""
    commit, snap, store, name, _ = read(of, commit, allow)
    rep = repo.report()
    own = G.identity(rep, repo.store.snapshot())["identity"]
    if own == store:
        raise Failed("ANCHOR_SELF", "an anchor lies in another store than the one it witnesses (that is snapshot@1)")
    mine = {L: lin for L, lin in lineages(rep, store).items() if rep["_recs"][L]["actor"] == actor}
    prev, have = None, set()
    if len(mine) > 1:
        raise Failed("ANCHOR_LINEAGES", f"{actor} keeps {len(mine)} anchor lineages of {store[:12]}")
    if mine:
        (L, lin), = mine.items()
        have, why = held(repo.store.snapshot().blob, rep, lin)
        if why:
            raise Failed("ANCHOR_BROKEN", why)
        prev = lin["leaf"]
    now = set(snap.lines)
    gone = sorted(have - now)
    if gone:
        raise Failed("ANCHOR_REWRITTEN", f"{len(gone)} record(s) the store held when anchored last are gone at "
                     f"{commit[:12]}: " + ", ".join(g[:12] for g in gone[:8]))
    added = repo.store.put_blob(b"".join(bytes.fromhex(i) for i in sorted(now - have)))
    r = M.roots(snap)
    body = {"state": "witnessed", "store": store, "repository": name, "commit": commit, "format": r["format"],
            "records": r["records"], "size": r["size"]["records"], "digest": snap.digest, "added": added}
    return repo.file(actor, key, [R.record("entity", actor, 0, body, NAME, lineage=prev, refs=[])])[0]


def check(repo, of, commit=None, allow=frozenset()):
    """Every anchor lineage this store keeps of the store at `of`, against that store at `commit`: {store, commit,
    holds, anchors: [{lineage, actor, leaf, at, held, missing, problem}], one_account}. `holds`: at least one anchor and
    none whose ids are gone or whose blobs are broken."""
    commit, snap, store, _, theirs = read(of, commit, allow)
    out = against(repo.report(), repo.store.snapshot().blob, repo.config()[0], store, set(snap.lines), theirs)
    return {"store": store, "commit": commit, **out}


def against(rep, blob, trust, store, now, theirs):
    """Every anchor lineage of `store` (an identity) in the anchoring store's report `rep`, against the ids the store
    holds `now`: {holds, anchors: [{lineage, actor, leaf, at, held, missing, problem}], one_account}. `blob` reads the
    anchoring store's blobs, `trust` is its trust, `theirs` the witnessed store's. `holds`: at least one anchor and none
    whose ids are gone or whose blobs are broken. One reader for a clone (check) and an address (warrant-agent rely)."""
    rows = []
    for L, lin in sorted(lineages(rep, store).items()):
        have, why = held(blob, rep, lin)
        leaf = lin["leaf"]
        rows.append({"lineage": L, "actor": rep["_recs"][L]["actor"], "leaf": leaf,
                     "at": rep["_recs"][leaf]["body"]["commit"] if leaf else None, "held": len(have or ()),
                     "missing": sorted((have or set()) - now), "problem": why})
    # the witness's keys among the witnessed store's own writers: then the anchor is one account's word
    keys = {k for ks in (theirs.get("keys") or {}).values() for k in ks}
    one = sorted({r["actor"] for r in rows if set(trust.get("keys", {}).get(r["actor"], [])) & keys})
    ok = bool(rows) and not any(r["missing"] or r["problem"] for r in rows)
    return {"holds": ok, "anchors": rows, "one_account": one}


def run(argv=None):
    root, argv = env_root(list(sys.argv[1:] if argv is None else argv))
    ap = argparse.ArgumentParser(prog="warrant anchor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("schema", "witness", "init"):
        p = sub.add_parser(n)
        p.add_argument("--actor", required=True)
        p.add_argument("--key", required=True)
    for n in ("witness", "check"):
        sub.choices[n].add_argument("--of", required=True, help="a clone on disk, or an address: github.com/OWNER/NAME"
                                    "[/tree/BRANCH] or an HTTPS root serving .warrant/")
        sub.choices[n].add_argument("--commit")
        sub.choices[n].add_argument("--allow-host", action="append", default=[], metavar="HOST",
                                    help="a host of your own network to read from (otherwise refused, as remote's are)")
    sub.choices["check"].add_argument("--json", action="store_true")
    sub.choices["init"].add_argument("--repository", required=True, help="the name the witness's store gives itself")
    a = ap.parse_args(argv)
    if a.cmd == "init":
        dump({"init": init(root, a.actor, load_key(a.key, root), a.repository)})
        return 0
    repo = Repo(root)
    if getattr(a, "commit", None) is not None and not S.hex_of(a.commit, 40):
        raise Failed("BAD_REQUEST", "--commit is a full commit id")
    if a.cmd == "schema":
        dump({"schema": repo.file(a.actor, load_key(a.key, root), [R.record("schema", a.actor, 0, SCHEMA)])[0]})
        return 0
    if a.cmd == "witness":
        dump({"anchor": witness(repo, a.of, a.actor, load_key(a.key, root), a.commit, a.allow_host)})
        return 0
    out = check(repo, a.of, a.commit, a.allow_host)
    if a.json:
        dump(out)
    else:
        print(f"store       {out['store'][:12]} at {out['commit'][:12] or a.of}: " + ("HELD" if out["holds"] else
              "NOT HELD" if out["anchors"] else "NOT ANCHORED here"))
        for r in out["anchors"]:
            state = r["problem"] or (f"{len(r['missing'])} record(s) gone: " + ", ".join(m[:12] for m in r["missing"][:8])
                                     if r["missing"] else f"all {r['held']} anchored records held")
            print(f"anchor      {r['actor']} {r['lineage'][:12]} (last at {(r['at'] or '?')[:12]}): {state}")
        if out["one_account"]:
            print(f"one account {', '.join(out['one_account'])}: a key of the witnessed store's own trust; their anchor is its word")
    return 0 if out["holds"] else 1


if __name__ == "__main__":
    sys.exit(main(run))
