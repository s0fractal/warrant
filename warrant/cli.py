"""warrant: one command. The core's verbs init, key, trust, bootstrap, put, attest, blob, assess and fmt
(docs/V3.md; output is JSON); status, a reader's summary of a store; join, a writer taking its own chain forks in
(warrant.chains); home, the operator's registry of
repositories (docs/HOME.md); across, one read over every repository registered there; the review loop's commands review, gate, claims and roadmap (`warrant review ...`
is `python -m warrant.review ...`; docs/REPOSITORY.md); drift, whether the bytes the claims checker accepted are
still the bytes at HEAD (warrant.drift); and verify, whether this receiver may rely on a package it was handed, with no
store at all (warrant.verify, docs/VERIFY.md: its exit status is the answer, and the files it names lie anywhere).

The store is --store, else --repo NAME's (a repository registered in Home), else the nearest `.warrant/` from the current directory upward (WARRANT_REPO_ROOT's when
it is set; `init` creates it in the current directory). The trust and the profile are --trust and --profile,
else that store's `v3.json` (docs/REPOSITORY.md): a repository is assessed under its own receiver configuration
with no flag. A seed is read from --key FILE (in the current directory or the operator's home, never through a
path that leaves both) or from WARRANT_KEY; every other file named is inside the current directory."""
import argparse
import json
import os
import re
import sys
import subprocess
import time
from pathlib import Path

from warrant import keys as K

from . import across as A
from . import bootstrap as B
from . import chains as CH
from . import engine as E
from . import sources as SRC
from . import graph as G
from . import home as H
from . import records as R
from .store import Refused, Store, confined, read_inside

LOOP = ("review", "gate", "claims", "roadmap", "drift", "snapshot", "anchor", "delegate")       # the review loop's commands, each its own module's parser
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
    """--store inside the current directory; else WARRANT_REPO_ROOT's `.warrant`; else the nearest `.warrant`
    from the current directory upward; else (and for `init`) the current directory's. A store found by default is
    confined, by real path, to the directory it is found in, as --store is to the current one: a `.warrant` link
    leading out of its repository is refused, never followed into another store (Codex finding 24b91d75f065)."""
    if a.store is not None:
        return here(a.store)
    if getattr(a, "repo", None):
        return H.store_of(H.load(), a.repo)
    if os.environ.get("WARRANT_REPO_ROOT"):
        root = Path(os.environ["WARRANT_REPO_ROOT"])
        return confined(root / ".warrant", root)
    cwd = Path(os.getcwd())
    if a.cmd != "init":
        for d in (cwd, *cwd.parents):
            if (d / ".warrant").is_dir() or (d / ".warrant").is_symlink():     # a link is found, then refused
                return confined(d / ".warrant", d)
    return confined(cwd / ".warrant", cwd)


def receiver(a, store):
    """(trust, profile, repository name or None): each of --trust and --profile when given, else the store's
    v3.json; refused when neither names it."""
    doc = None
    if not (getattr(a, "trust", None) and getattr(a, "profile", None)):
        f = Path(store) / RECEIVER
        if not os.path.lexists(f):
            raise Refused(f"no --trust/--profile and no {RECEIVER} in the store {store}")
        doc = json.loads(read_inside(f, store))
        if not (isinstance(doc, dict) and isinstance(doc.get("trust"), dict) and isinstance(doc.get("profile"), dict)):
            raise Refused(f"{f} is not a receiver configuration {{repository, trust, profile}}")
    trust = json.loads(Path(here(a.trust)).read_text()) if getattr(a, "trust", None) else doc["trust"]
    profile = json.loads(Path(here(a.profile)).read_text()) if getattr(a, "profile", None) else doc["profile"]
    for why in (E.trust_problem(trust), E.profile_problem(profile)):
        if why:
            raise Refused(why)
    return trust, profile, (doc or {}).get("repository")


def signer(a, kind=None):
    seed = Path(home(a.key)).read_text() if a.key else os.environ.get("WARRANT_KEY")
    if not seed:
        raise Refused("a signing seed is needed: --key FILE or WARRANT_KEY")
    key = K.Key.from_seed_hex(seed)
    trust = json.loads(Path(here(a.trust)).read_text()) if a.trust else receiver(a, store_dir(a))[0]
    if key.public not in trust["keys"].get(a.actor, []) and not (kind == "challenge" and a.actor == f"key:{key.public}"):
        raise Refused(f"the trust does not bind this key to {a.actor!r}")
    return key, trust


def join(a):
    """`join`: one `joined` attest by the actor on each of its chain tips its head does not take in (warrant.chains),
    chained on that head, compare-and-swap on it; the ids filed (none when nothing is loose)."""
    store = store_dir(a)
    key, trust = signer(a, "attest")
    s = Store(store)
    view = E.View(s.snapshot(), trust, receiver(a, store)[1])
    recs = CH.join_records(view, a.actor)
    if not recs:
        return []
    at, h = CH.tips(view, a.actor)[-1]
    at = a.at if a.at is not None else max(int(time.time()), at)
    return s.extend([dict(r, at=at) for r in recs], key, trust, expect_head=h)


def seen_body(a, body):
    """An acceptance with what its signer's view held of the target (warrant.graph.seen_of), as the agent interface's
    prepare gives it (warrant.graph.with_seen); any other verdict, or a store with no rules to read it by (--trust
    without --profile, and no v3.json), as given."""
    if body.get("verdict") != "accept":
        return body
    store = store_dir(a)
    try:
        trust, profile = receiver(a, store)[:2]
    except Refused:                  # no rules to read the store by (--trust alone): it names no horizon
        return body
    return G.with_seen(E.View(Store(store).snapshot(), trust, profile).report(), body)


def schema_of(a, name):
    """The body of schema `name` as this store reads it: the counted one under its receiver, else (no rules to read it
    by, --trust alone) the newest schema record of that name in the store; None when there is none."""
    store = store_dir(a)
    snap = Store(store).snapshot()
    try:
        trust, profile = receiver(a, store)[:2]
        return E.View(snap, trust, profile).schemas.get(name)
    except Refused:
        rows = [e[0]["record"] for e in snap.lines.values()]
        named = sorted((r["at"], r["body"]) for r in rows if r.get("kind") == "schema" and (r.get("body") or {}).get("name") == name)
        return named[-1][1] if named else None


def put(a, kind, body, schema=None, lineage=None, refs=(), guard=None):
    if kind == "schema" and E._schema_problem(body):     # it would lie in the store for good and never count
        raise Refused(f"SCHEMA_NOT_COUNTED: {E._schema_problem(body)}")
    if kind == "entity" and schema and isinstance(body, dict):
        # as the agent's prepare does: the schema's minimal guard for the state when none is named (a closing version
        # with no guard is never effective and waits for nobody), and the references its typed fields name
        s = schema_of(a, schema)
        if s is not None:
            if guard is None and isinstance(s.get("states"), dict):
                guard = s["states"].get(body.get("state"))
            refs = sorted(set(refs) | R.body_refs(s.get("fields") or {}, body))
    key, trust = signer(a, kind)
    at = a.at if a.at is not None else int(time.time())
    r = R.record(kind, a.actor, at, body, schema=schema, lineage=lineage, refs=refs, guard=guard)
    return Store(store_dir(a)).append(r, key, trust, expect_head=a.expect_head)


LOOP_HELP = {
    "review": "the pull request review loop as records: open, head, a finding's replay",
    "gate": "the merge gate: which pull requests a recorded acceptance makes mergeable",
    "claims": "a specification's sentences as claims, their tests and mutants, and the checker that accepts them",
    "roadmap": "goals and obligations: what is open, what is due for whom, close and release",
    "drift": "which accepted claims name bytes the checkout no longer holds",
    "snapshot": "Merkle roots of the store and witnesses over them",
    "anchor": "this store witnessing another: what it held, kept here, and whether it still holds it",
}
HELP = {
    "init": "make a store here (.warrant/, with AGENTS.md and the MCP server for agents), or --store DIR",
    "key": "make a signing key (an Ed25519 seed) at --out",
    "trust": "write a trust file binding each key to its actor (--bind ACTOR=SEED)",
    "bootstrap": "file the five schemas (claim, goal, obligation, pull request head, finding) as --actor",
    "put": "file one record (--kind entity|schema|attest|challenge); the schema's guard for its state by default",
    "attest": "file an attest on a record, an acceptance by default (--body '{\"verdict\": ...}')",
    "blob": "store a file's bytes by their hash, for records to cite",
    "assess": "the whole report as JSON: every lineage, version, guard and challenge under this receiver",
    "fmt": "sort the store's records into canonical order",
    "status": "where the store stands, in a few lines (--actor A: what waits for A)",
    "join": "take the actor's forked chain in (one `joined` attest per loose tip)",
    "show": "one record in plain words: its lineage, state, what its guard waits for, who accepted, who objected",
}


def show(a):
    """`show ID`: one record as this receiver reads it, in plain words (--json: the same as data)."""
    store = store_dir(a)
    trust, profile = receiver(a, store)[:2]
    snap = Store(store).snapshot()
    view = E.View(snap, trust, profile)
    rep = view.report()
    # reliance as `assess` and `status` read it (G14, docs/V3.md §10): a repository's store beside its checkout through
    # the freshness gate, a store alone with a pinned lineage PINS_NOT_CHECKED, never ELIGIBLE (Codex 3a57ee31)
    from . import drift as D
    rep["_recs"], rep["_basis"] = view.recs, view.basis
    D.reading(rep, Path(store).resolve().parent if Path(store).name == ".warrant" else None)
    ids = [i for i in list(snap.lines) + list(snap.blobs) if i.startswith(a.id)]
    if len(set(ids)) != 1:
        raise Refused(f"{a.id[:64]!r} names {len(set(ids))} records or blobs in this store")
    i = ids[0]
    r = view.recs.get(i)
    out = {"id": i, "kind": r["kind"] if r else "blob", "schema": r.get("schema") if r else None,
           "actor": r.get("actor") if r else None, "body": r.get("body") if r else None}
    if i in rep["versions"]:
        root = G.lineage_of(rep, i)
        lin, v = rep["lineages"][root], rep["versions"][i]
        out["lineage"] = {"root": root, "state": lin["state"], "reliance": lin["reliance"], "leaf": lin["leaf"],
                          "effective": lin["effective"]}
        out["guard"] = {"guard": v["guard"], "waiting": v["waiting"], "accepted_by": v["accepted_by"]}
        g = G.grounded(rep, i, view.recs)
        out["grounded"] = g["grounded"]
    out["challenges"] = [{"id": c, "actor": view.recs[c]["actor"], "counted": x["counted"],
                          "statement": str((view.recs[c].get("body") or {}).get("statement", ""))[:200]}
                         for c, x in sorted(rep["challenges"].items()) if x["target"] == i and c in view.recs]
    return out


def show_text(x):
    """`show` for a person."""
    who = f" by {x['actor']}" if x["actor"] else ""
    rows = [f"{x['id'][:12]}  {x['kind']}{' ' + x['schema'] if x['schema'] else ''}{who}"]
    b = x["body"] or {}
    for k in ("statement", "text", "title", "verdict", "reason"):
        if isinstance(b.get(k), str):
            rows.append(f"  {k}: {b[k][:300]}")
    if "lineage" in x:
        lin, g = x["lineage"], x["guard"]
        here = "this version" if lin["leaf"] == x["id"] else f"leaf {str(lin['leaf'])[:12]}"
        rows.append(f"  lineage {lin['root'][:12]}: {lin['state'] or 'no effective version yet'}, {lin['reliance']} ({here})")
        rows.append(f"  guard: {g['guard']}" + (f", waits for {'; '.join(g['waiting'])}" if g["waiting"] else "")
                    + (f"; accepted by {', '.join(g['accepted_by'])}" if g["accepted_by"] else ""))
        rows.append(f"  grounded: {'yes' if x['grounded'] else 'no: it, or something it rests on, is not yet effective and ELIGIBLE'}")
    for c in x["challenges"]:
        rows.append(f"  challenged by {c['actor']} ({'counted' if c['counted'] else 'not counted here'}): {c['statement']}")
    return "\n".join(rows) + "\n"


def _parser():
    p = argparse.ArgumentParser(prog="warrant", description=(
        "Warrant keeps work as signed records: what a thing is, who accepted it, who objected. Each reader judges "
        "the same bytes under its own trust and profile and gets one answer: what may be relied on now, and what "
        "still waits, for whom. Start: `warrant init`, then QUICKSTART.md."))
    sub = p.add_subparsers(dest="cmd", required=True)
    cmds = {n: sub.add_parser(n, help=h) for n, h in HELP.items()}
    for n in LOOP:
        sub.add_parser(n, help=LOOP_HELP.get(n, f"python -m warrant.{n}") + " (its own arguments)", add_help=False)
    sub.add_parser("verify", help="may this receiver rely on a package it was handed? (python -m warrant.verify, its own arguments)",
                   add_help=False)
    sub.add_parser("resolve", help="where the bytes each cited hash names are, over Home (python -m warrant.resolve)",
                   add_help=False)
    sub.add_parser("say", help="a voice on a record, under one's own key, with no rights against it (warrant init --voices)",
                   add_help=False)
    for n, c in cmds.items():
        if n not in ("key", "trust", "init"):     # show among them: it reads a store
            g = c.add_mutually_exclusive_group()
            g.add_argument("--store")
            g.add_argument("--repo", help="a repository registered in Home (warrant home)")
    cmds["init"].add_argument("--store")
    cmds["init"].add_argument("--no-entry", action="store_true",
                              help="a repository's store without the AGENTS.md block and CLAUDE.md import (warrant.entry)")
    cmds["init"].add_argument("--no-mcp", action="store_true",
                              help="a repository's store without .warrant/agent.json and the MCP server `warrant` in .mcp.json")
    cmds["init"].add_argument("--voices", action="store_true",
                              help="a store of voices: it trusts nobody and gives nobody a role (warrant say files into it)")
    x = sub.add_parser("across", help="one read over every repository registered in Home (docs/HOME.md); output is JSON")
    x.add_argument("query", nargs="?", default="stores", choices=A.QUERIES)
    x.add_argument("subject", nargs="?", help="actor: whose records; rests: a record or blob id, a prefix, or <store>:<id>")
    x.add_argument("--schema")
    x.add_argument("--offset", type=int)
    x.add_argument("--max-bytes", type=int)
    h = sub.add_parser("home", help="the operator's registry of repositories and identities (docs/HOME.md)")
    h.add_argument("action", nargs="?", default="list", choices=("list", "add", "identity", "remove"))
    h.add_argument("target", nargs="?", help="add: a repository directory; identity: an actor; remove: a name")
    h.add_argument("--name")
    h.add_argument("--signer")
    h.add_argument("--seed")
    h.add_argument("--operation", action="append", dest="operations")
    h.add_argument("--json", action="store_true")
    for n in ("bootstrap", "put", "attest", "join"):
        c = cmds[n]
        c.add_argument("--key")
        c.add_argument("--actor", required=True)
        c.add_argument("--trust")
        c.add_argument("--at", type=int)
        if n != "join":                 # join swaps on the head it read the tips under
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
    for n in ("put", "attest"):
        cmds[n].add_argument("--id", action="store_true", help="print the new record's id alone")
    c = cmds["show"]
    c.add_argument("id", help="a record or blob id, or 8 or more of its first hex digits")
    c.add_argument("--trust")
    c.add_argument("--profile")
    c.add_argument("--json", action="store_true")
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
    """The engine's report; for a repository's store read now, with the freshness gate applied as `status`, `drift`
    and the agent's `context` apply it (G14): `assess` alone once printed ELIGIBLE for a lineage they read STALE (the
    analysis session, 2026-11-13). What the gate read is under `checkout`, and `assessment` stays the engine's."""
    store = store_dir(a)
    trust, profile, _ = receiver(a, store)
    if a.as_of is None and Path(store).name == ".warrant":
        from . import drift as D
        view = E.View(Store(store).snapshot(), trust, profile, None)
        rep = view.report()
        rep["_recs"], rep["_basis"] = view.recs, view.basis
        D.reading(rep, Path(store).resolve().parent)   # the gate when that folder is a checkout's top, else not_checked
        del rep["_recs"], rep["_basis"]
    else:                         # no checkout read beside it: a pinned lineage reads PINS_NOT_CHECKED (§10)
        from . import drift as D
        view = E.View(Store(store).snapshot(), trust, profile, a.as_of)
        rep = view.report()
        rep["_recs"], rep["_basis"] = view.recs, view.basis
        D.not_checked(rep)
        del rep["_recs"], rep["_basis"]
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
    root = Path(store).resolve().parent
    srcs = []
    if Path(store).name == ".warrant":            # a repository's store: the sources its v3.json names, read beside it
        snap, srcs = SRC.with_sources(root, snap, SRC.config_doc(root))
    view = E.View(snap, trust, profile, a.as_of)
    rep, forks = view.report(), CH.forks(view)
    if a.as_of is None and Path(store).name == ".warrant":
        from . import drift as D
        rep["_recs"], rep["_basis"] = view.recs, view.basis
        D.reading(rep, root)         # G14 (the gate when root is a checkout's top, else not_checked): a lineage whose acceptances name other bytes than HEAD's counts STALE here too
    else:                            # no checkout compared: a pinned lineage reads PINS_NOT_CHECKED, never ELIGIBLE (§10)
        from . import drift as D
        rep["_recs"], rep["_basis"] = view.recs, view.basis
        D.not_checked(rep)
    brakes = open_brakes(root) if a.as_of is None and Path(store).name == ".warrant" else None
    lineages, reliance = {}, {}
    for lin in rep["lineages"].values():
        by, state = lineages.setdefault(lin["schema"], {}), lin["state"] or "none"     # none: no effective version yet
        by[state] = by.get(state, 0) + 1
        reliance[lin["reliance"]] = reliance.get(lin["reliance"], 0) + 1
    return {"repository": name, "identity": G.identity(rep, snap), "store": store, "snapshot": rep["snapshot"], "assessment": rep["assessment"],
            "trusted": sorted(trust.get("keys", {})), "roles": {r: sorted(a) for r, a in sorted(profile.get("roles", {}).items())},
            "records": len(snap.lines), "blobs": len(snap.blobs), "canonical": rep["canonical"],
            "completeness": rep["completeness"], "rejected": len(rep["rejected"]),
            "chain_forks": sorted({f[0] for f in rep["chains"]["forks"]}),
            "chain_forks_open": sorted({f[0] for f in forks["open"]}), "schemas": sorted(rep["schemas"]),
            "schemas_pending": sorted(rep["schemas_pending"]), "problems": rep["problems"],
            "lineages": {k: dict(sorted(v.items())) for k, v in sorted(lineages.items())},
            "reliance": dict(sorted(reliance.items())),
            "frontier": G.frontier(rep, profile, a.actor, view.recs) if a.actor else None, "brakes": brakes,
            "sources": srcs}


def open_brakes(root):
    """The gate's brakes still open at this checkout's HEAD (warrant.gate.brakes: merges the owner may still veto, read
    from the merge messages, no network), each with whether the gate's exact revert of it is still possible
    (revert_plan: `revertable`, or why not); None outside a git checkout."""
    from . import gate as GT
    try:
        head = subprocess.run(["git", "--no-replace-objects", "-C", str(root), "rev-parse", "HEAD^{commit}"], capture_output=True, text=True,
                              check=True).stdout.strip()
        out = []
        for b in GT.brakes(root, head):
            _, why = GT.revert_plan(root, head, b["merge"])
            out.append(dict(b, revertable=why is None, **({"why": why} if why else {})))
        return out
    except (subprocess.CalledProcessError, OSError, GT.Refused):
        return None


def _counts(d):
    return " · ".join(f"{k} {n}" for k, n in d.items()) or "none"


def render(st):
    """`status` for a person: one line per fact, the same facts as its --json."""
    ident = st["identity"]
    rows = [("repository", st["repository"] or "(no repository named)"),
            ("identity", f"{ident['identity'][:12]} (the genesis of its rules@1)" if ident["identity"] else ident["why"]),
            ("store", f"{st['store']} · snapshot {st['snapshot'][:12]}"),
            ("records", f"{st['records']} · blobs {st['blobs']} · {'canonical' if st['canonical'] else 'NOT canonical'}"
                        f" · rejected {st['rejected']} · completeness {st['completeness']}"),
            ("receiver", (f"{len(st['trusted'])} trusted actor(s) · roles: " + "; ".join(f"{r} {', '.join(a)}" for r, a in st["roles"].items()))
                         if any(st["roles"].values()) else
                         f"{len(st['trusted'])} trusted actor(s) · no actor holds a role: no acceptance counts here yet "
                         "(.warrant/v3.json: trust binds keys, the profile gives roles)"),
            ("schemas", (", ".join(st["schemas"]) or "none: `warrant bootstrap` files them")
                        + (f" (pending: {', '.join(st['schemas_pending'])})" if st["schemas_pending"] else ""))]
    w = max([len(k) for k in st["lineages"]] or [0])
    rows += [("lineages" if i == 0 else "", f"{k.ljust(w)}  {_counts(v)}") for i, (k, v) in enumerate(st["lineages"].items())]
    rows += [("reliance", _counts(st["reliance"])),
             ("chain forks", (", ".join(st["chain_forks"]) + f" · open: {', '.join(st['chain_forks_open']) or 'none'}")
                             if st["chain_forks"] else "none"),
             ("problems", f"{len(st['problems'])}" if st["problems"] else "none")]
    for x in st.get("sources") or []:
        if not x["commit"]:
            what = "not in this clone (fetch the ref)"
        else:
            what = f"{x['records']} record(s) by its actors at {x['commit'][:12]}"
            what += f", {x['left_out']} by others left out" if x["left_out"] else ""
        rows.append(("source", f"{x['name']} at {x['ref']}: {what}"))
    if st.get("brakes") is not None:
        rows.append(("brakes", f"{len(st['brakes'])} open (the owner may veto; the gate reverts a vetoed merge)" if st["brakes"] else "none open"))
        rows += [("", f"#{b['pr']} merged as {b['merge'][:12]}, until {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(b['until']))}"
                      f" · {'revertable' if b['revertable'] else 'no exact revert: ' + b['why']}") for b in st["brakes"]]
    f = st["frontier"]
    if f:
        rows.append((f["actor"], f"may attest {len(f['attest'])} · own pending {len(f['pending'])} · challenged {len(f['challenged'])}"
                                 f" · roles {', '.join(f['roles']) or 'none'}"))
        rows += [("", f"{x['version'][:12]}  {x['schema']}  {'; '.join(x['waiting'])}") for x in f["attest"]]
    return "".join(f"{k.ljust(12)}{v}\n" for k, v in rows)


def home_cmd(a):
    """`warrant home [list|add DIR|identity ACTOR --seed FILE|remove NAME]`: the operator's registry (warrant.home)."""
    if a.action == "list":
        doc = H.load()
        return {"home": str(H.path()), "identities": sorted(doc["identities"]), "repositories": H.listing(doc)}
    if not a.target:
        raise Refused(f"warrant home {a.action} needs its target")
    if a.action == "identity" and not a.seed:
        raise Refused("warrant home identity ACTOR --seed FILE")
    change = {"add": lambda d: H.add_repository(d, a.target, a.name, a.signer, a.operations),
              "identity": lambda d: H.add_identity(d, a.target, a.seed),
              "remove": lambda d: H.remove(d, a.target)}[a.action]
    doc = H.update(change)                              # read, change and write under Home's lock
    return {"home": str(H.path()), "identities": sorted(doc["identities"]), "repositories": sorted(doc["repositories"])}


def across_cmd(a):
    """`warrant across [stores|actor A|open|challenges|rests HASH]`: one read over Home's repositories (warrant.across)."""
    doc = H.load()
    if not doc["repositories"]:
        raise Refused("Home registers no repository (warrant home add DIR)")
    q = {"query": a.query, **{k: v for k, v in (("schema", a.schema), ("offset", a.offset), ("max_bytes", a.max_bytes))
                              if v is not None}}
    if a.subject is not None:
        q[{"actor": "actor", "rests": "target"}.get(a.query, "subject")] = a.subject
    return A.answer(A.home_readings(doc), q)


def render_home(out):
    rows = [f"home        {out['home']}", f"identities  {', '.join(out['identities']) or 'none'}"]
    for r in out["repositories"]:
        if not isinstance(r, dict):
            rows.append(f"            {r}")
            continue
        signer = "read only" if not r["signer"] else f"signs as {r['signer']}" + ("" if r.get("bound") else " (key NOT bound there)")
        ident = f"identity {r['identity'][:12]}" if r.get("identity") else "no identity"
        same = f" (same store as {', '.join(r['same'])})" if r.get("same") else ""
        rows.append(f"{r['name']:<12}{r.get('repository') or r.get('problem')} · {ident}{same} · {r.get('records', '?')} records"
                    f" · {signer} · {r['path']}")
    return "\n".join(rows) + "\n"


VOICE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")


def voices_name(root):
    """The repository name a store of voices gives itself: voices/<its directory's name>, as Git names allow. A name
    it gives itself, not an identity (an obligation of stage 2: a store named by its root record)."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", Path(root).name)[:100].strip(".-") or "local"
    return f"voices/{name if VOICE_NAME.match(name) else 'local'}"


def say(argv):
    """`warrant say TARGET "TEXT" [--as NAME] [--store DIR]`: a voice with no rights against any record (the commons,
    warrant/commons.py), filed under the agent's own key `key:<public>` in the store of voices around the current
    directory (or DIR), made with `warrant init --voices` or on first use. A store that trusts anyone is refused."""
    from . import commons as CM
    ap = argparse.ArgumentParser(prog="warrant say")
    ap.add_argument("target")
    ap.add_argument("statement")
    ap.add_argument("--as", dest="name", default="commons")
    ap.add_argument("--store", help="the directory holding the store of voices (.warrant/); default the current one")
    a = ap.parse_args(argv)
    root = Path(a.store) if a.store else Path.cwd()
    try:
        key = CM.seed_named(a.name, root)
        if not (root / ".warrant" / CM.V3).exists():
            CM.init(root, voices_name(root))
        filed = CM.say(root, a.target, a.statement, key)
    except CM.Refused as e:
        print(f"REFUSED {e}", file=sys.stderr)
        return 1
    print(json.dumps({"filed": filed, "actor": "key:" + key.public, "store": str(root / ".warrant")}, sort_keys=True))
    return 0


def loop(argv):
    """`warrant review|gate|claims|roadmap|drift|snapshot|anchor|delegate ARGS`: that module's own command, unchanged."""
    from . import anchor, claims, delegate, drift, gate, review, roadmap, snapshot
    from .repo import main as run_tool
    mod = {"review": review, "gate": gate, "claims": claims, "roadmap": roadmap, "drift": drift,
           "snapshot": snapshot, "anchor": anchor, "delegate": delegate}[argv[0]]
    return mod.main(argv[1:]) if mod is gate else run_tool(mod.run, argv[1:])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] and argv[0] in LOOP:
        return loop(argv)
    if argv[:1] == ["verify"]:
        from . import verify
        return verify.main(argv[1:])
    if argv[:1] == ["pact"]:
        from . import pact
        return pact.main(argv[1:])
    if argv[:1] == ["pulse"]:
        from . import pulse
        return pulse.main(argv[1:])
    if argv[:1] == ["resolve"]:
        from . import resolve
        return resolve.run(argv[1:])
    if argv[:1] == ["say"]:
        return say(argv[1:])
    a = _parser().parse_args(argv)
    if a.cmd == "across":
        try:
            sys.stdout.write(json.dumps(across_cmd(a), sort_keys=True) + "\n")
        except (OSError, ValueError) as e:
            print(f"REFUSED {e}", file=sys.stderr)
            return 2
        return 0
    if a.cmd in ("status", "home"):
        try:
            st = status(a) if a.cmd == "status" else home_cmd(a)
        except (OSError, ValueError) as e:
            print(f"REFUSED {e}", file=sys.stderr)
            return 2
        human = render(st) if a.cmd == "status" else render_home(st)
        sys.stdout.write(json.dumps(st, indent=1, sort_keys=True) + "\n" if a.json else human)
        return 0
    try:
        if a.cmd == "init" and a.voices:
            from . import commons as CM
            store = store_dir(a)
            if Path(store).name != ".warrant":
                raise Refused(f"{store}: a store of voices is a .warrant directory")
            try:
                CM.init(Path(store).parent, voices_name(Path(store).parent))
            except CM.Refused as e:
                raise Refused(str(e)) from None
            out = {"store": a.store if a.store is not None else store, "voices": True}
        elif a.cmd == "init":
            store = store_dir(a)
            Store(store).init()
            out = {"store": a.store if a.store is not None else store}     # as named, else where it went
            if Path(store).name == ".warrant":                             # a repository's store: what the next agent reads
                from . import entry as EN
                root = Path(store).parent
                wrote = EN.receiver(root) + ([] if a.no_entry else EN.agents(root)) + ([] if a.no_mcp else EN.mcp(root))
                out["wrote"] = wrote
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
        elif a.cmd == "join":
            out = {"joined": join(a)}
        elif a.cmd == "attest":
            out = {"record": put(a, "attest", seen_body(a, dict(a.body, target=a.target)), refs=[a.target])}
        elif a.cmd == "blob":
            out = {"blob": Store(store_dir(a)).put_blob(Path(here(a.file)).read_bytes())}
        elif a.cmd == "show":
            x = show(a)
            sys.stdout.write(json.dumps(x, indent=1, sort_keys=True) + "\n" if a.json else show_text(x))
            return 0
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
    if getattr(a, "id", False) is True and isinstance(out.get("record"), str):
        print(out["record"])                # --id: the new record's id alone, for a shell to keep
        return 0
    print(json.dumps(out, indent=1, sort_keys=True))
    if a.cmd == "init" and not a.voices and sys.stderr.isatty():
        print("next: `warrant key --out me.key`, bind it in .warrant/v3.json (`warrant trust`), `warrant bootstrap`, "
              "then `warrant put` and `warrant show ID`; the 15-minute walk: QUICKSTART.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
