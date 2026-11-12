"""Whether the bytes a claims checker's acceptance ran on are still the bytes at this receiver's head (G14).

An acceptance names its `files`, {path: git blob}: each witness's test file, each mutant's mutated file and test
file, as the checker found them at the commit it ran (`warrant claims replay`; CI's `claims verify` holds the list to
that commit). Each is compared with HEAD's tree (warrant.pins):

    UNCHANGED  the same bytes at the same path;
    MOVED      the path is gone from HEAD and the same bytes are at another path (unchanged, at its new path);
    CHANGED    other bytes at the path, with the first commit after the accepted one from which the bytes were not
               those (a commit changing only a mode, or one undone later, is not it);
    GONE       the path is gone from HEAD and those bytes are nowhere in it;
    UNKNOWN    the acceptance names no files (one signed before they were named): nothing can be compared.

A claim reads UNCHANGED when one of its effective version's acceptances has every file UNCHANGED or MOVED. When none
has, the acceptance is stale: that lineage's reliance is STALE, not ELIGIBLE, until the claims checker accepts it
again at a commit holding those bytes. This is a gate, not advice: time-lab Q10 H3 found a model under one sentence
of pressure acting on a stale conclusion in 72 of 72 scenarios despite an honest freshness answer it heeded without
pressure. The answer leads with the verdict on the bytes (Q10: "the pinned bytes are now at X" made a model re-read
where git's rename line did not).

It reads the store and Git's trees and history, and runs nothing of the repository's: `context` and `graph` answer
through it, in workspaces permitted to read only (Codex finding c589d17da0f3), and what the current mutant harness
lists is no part of it, so editing the harness cannot refresh an acceptance (finding 0e7a05e8832c). The head is the
receiver's HEAD commit, not its working tree. A checkout without .warrant/claims.json has no drift answer.

    python3 -m warrant drift [--root DIR] [--json]     # one line per accepted claim, the verdict first
    python3 -m warrant drift --impact [[BASE..]HEAD] [--across] [--json]

`--impact` answers what a change bears on: the claims whose acceptances it makes stale, the lineages of this store
that rest on them, transitively (graph `why`, from every version of the claim), and with `--across` the records of
Home's other stores that rest on them, the walk going on through every store, this one too (across.reach), the stores
not read named, and the answer's root and lens binding every store read (across.identity). Given BASE, only the claims fresh at BASE and stale at HEAD are the change's;
those already stale at BASE are listed apart, and the changed files that no acceptance names are listed too: a file
no witness reads and no mutant mutates is in no acceptance, so this answer cannot see what rests on it. It reads Git
objects and the store only, and its envelope binds the checkout it read, as `graph` does."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import claims as C
from . import graph as G
from .pins import FRESH, blobs, compare, paths_of
from .pins import verdict as _verdict
from .repo import Failed, Repo, dump, env_root, git, main

STALE = "STALE"
RANK = {"UNCHANGED": 0, "CHANGED": 1, "UNKNOWN": 2}     # the answer shown: fresh if any acceptance is, else what can be said
HERE = "."                          # this checkout's store in an answer's identity when Home does not register it: no Home name


def resolve(root, rev):
    """The commit id `rev` names in this clone, or a refusal. A revision shaped as an option never reaches Git as one."""
    if not isinstance(rev, str) or not rev or rev.startswith("-"):
        raise Failed("BAD_REVISION", f"not a revision: {rev!r}")
    try:
        return git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    except subprocess.CalledProcessError:
        raise Failed("BAD_REVISION", f"no commit {rev!r} in this clone") from None


def drift(rep, root, at="HEAD"):
    """{lineage: {id, version, verdict, commit, files}} for each live claim whose effective version the claims
    checker accepted: the comparison of the acceptance that is freshest, against commit `at` (a resolved id or HEAD)."""
    if not (Path(root) / ".warrant" / "claims.json").is_file():
        return {}
    done = C.acceptances(rep)
    try:
        head = blobs(root, at)
    except subprocess.CalledProcessError:
        head = {}
    where = paths_of(head)
    out, memo = {}, {}
    for L in sorted(C.live(rep)):
        eff = rep["lineages"][L]["effective"]
        if not done.get(eff):
            continue
        seen = [(x, compare(root, x, files, head, where, at, memo) if rule == C.CLOSURE else
                 [("UNKNOWN", "", "the acceptance names its test and mutated files, not the import closure they ran")])
                for x, files, rule in done[eff]]
        x, rows = min(seen, key=lambda s: RANK[_verdict(s[1])])
        out[L] = {"id": rep["_recs"][eff]["body"].get("id"), "version": eff, "verdict": _verdict(rows), "commit": x,
                  "files": [{"verdict": v, "path": p, "detail": d} for v, p, d in rows]}
    return out


def checkout(root, at="HEAD"):
    """What the gate read beside the store: HEAD's tree and whether this checkout has claims. The answer's identity
    binds it (Codex finding ccc4e8145ed2): the same store can answer ELIGIBLE and STALE at two heads."""
    try:
        tree = git(root, "rev-parse", f"{at}^{{tree}}")
    except subprocess.CalledProcessError:
        tree = None
    return {"tree": tree, "claims": (Path(root) / ".warrant" / "claims.json").is_file()}


def gate(rep, root, at="HEAD"):
    """`rep` with the reliance of each claim whose acceptances are all stale set to STALE (and its drift kept under
    `drift`): an ELIGIBLE lineage only, and with what it read under `checkout`. Returns the drift answer."""
    rep["checkout"] = checkout(root, at)
    d = drift(rep, root, at)
    for L, x in d.items():
        lin = rep["lineages"][L]
        lin["drift"] = x["verdict"]
        if x["verdict"] != "UNCHANGED" and lin["reliance"] == "ELIGIBLE":
            lin["reliance"] = STALE
    return d


def lines(d):
    """The drift answer as text: per claim the verdict on the bytes first, then the files that moved or changed."""
    out = []
    for L, x in sorted(d.items(), key=lambda kv: (kv[1]["verdict"] == "UNCHANGED", str(kv[1]["id"]))):
        word = {"UNCHANGED": "unchanged", "CHANGED": "CHANGED", "UNKNOWN": "UNKNOWN"}[x["verdict"]]
        out.append(f"{word:9} {x['id']} ({L[:12]}), accepted at {str(x['commit'])[:12]}"
                   + ("" if x["verdict"] == "UNCHANGED" else f": reliance {STALE} until the claims checker accepts it again"))
        for f in x["files"]:
            if f["verdict"] == "MOVED":
                out.append(f"  unchanged, moved: {f['detail']} (was {f['path']})")
            elif f["verdict"] != "UNCHANGED":
                out.append("  " + " ".join(w for w in (f["verdict"], f["path"], f["detail"]) if w))
    n = sum(1 for x in d.values() if x["verdict"] != "UNCHANGED")
    out.append(f"drift: {len(d)} accepted claim(s), {n} stale")
    return "\n".join(out) + "\n"


def _accepted_files(rep, L):
    """Every path any signed acceptance of claim lineage L's effective version names."""
    eff = rep["lineages"][L]["effective"]
    return {p for _, files, _ in C.acceptances(rep).get(eff, []) if isinstance(files, dict) for p in files}


def rests_on(rep, L):
    """The roots of the lineages of `rep` that rest on lineage L, transitively, from any of its versions: a record may
    cite the version it read, not the root."""
    roots = set()
    for v in rep["lineages"][L]["versions"]:
        roots |= {G.lineage_of(rep, n["id"]) for n in G.why(rep, v)["nodes"]}
    return sorted(roots - {None, L})


def changed_paths(root, base, head):
    """The paths whose bytes differ between two commits, as Git's trees spell them (no rename detection)."""
    out = git(root, "diff-tree", "-r", "-z", "--no-renames", "--name-only", base, head, raw=True).decode()
    return sorted(p for p in out.split("\0") if p)


def _row(rep, L):
    lin = rep["lineages"][L]
    return {"lineage": L, "schema": lin["schema"], "state": lin["state"], "reliance": lin["reliance"]}


def impact(rep, root, head="HEAD", base=None, readings=None):
    """What a change bears on (`--impact`): the claims whose acceptances it makes stale, each with the lineages of this
    store that rest on it, and with `readings` (warrant.across, Home's stores) the records elsewhere that rest on it.
    With `readings` the walk goes through every store read, this checkout's own included (Codex finding 72595e2154fd):
    a record here may rest on the claim through a record there, and one there through one here. A store that cannot
    be read is named under `unavailable`. `head` and `base` are resolved commit ids or HEAD; `rep` is this checkout's
    report, gated at `head`."""
    from . import across as A
    gate(rep, root, head)
    now = drift(rep, root, head)
    before = drift(rep, root, base) if base else {}
    read = [x for x in readings or [] if x.why is None]
    others = [x for x in read if (x.root is None or os.path.realpath(x.root) != os.path.realpath(root))]
    stale, already = [], []
    for L, x in sorted(now.items(), key=lambda kv: str(kv[1]["id"])):
        if x["verdict"] == "UNCHANGED":
            continue
        if base and before.get(L, {}).get("verdict") != "UNCHANGED":
            already.append({"lineage": L, "id": x["id"]})
            continue
        row = {"lineage": L, "id": x["id"], "verdict": x["verdict"], "commit": x["commit"],
               "files": [f for f in x["files"] if f["verdict"] not in FRESH]}
        if readings is None:
            row["rests_on_it"] = [_row(rep, R) for R in rests_on(rep, L)]
        else:
            vs = rep["lineages"][L]["versions"]
            reached = set(A.reach([rep, *(r.rep for r in read)], vs)[0]) - set(vs)
            row["rests_on_it"] = [_row(rep, R) for R in sorted({G.lineage_of(rep, i) for i in reached} - {None, L})]
            row["elsewhere"] = _elsewhere(others, reached, L)
        stale.append(row)
    out = {"head": head, "base": base, "stale": stale, "affected": sorted({r["lineage"] for s in stale for r in s["rests_on_it"]}),
           "stores": sorted({e["store"] for s in stale for e in s.get("elsewhere", [])})}
    if readings is not None:
        out["unavailable"] = _unavailable(readings, root)
    if base:
        named = set().union(*(_accepted_files(rep, L) for L in now)) if now else set()
        changed = changed_paths(root, base, head)
        out.update(already_stale=already, changed=changed, in_no_acceptance=[p for p in changed if p not in named])
    return out


def _elsewhere(others, reached, L):
    """[{store, lineage, schema, state, reliance}] of the records of Home's other stores among `reached` (what rests on
    a version of claim lineage L, through every store), each read under that store's own report."""
    out = []
    for i in reached:
        for x in others:
            if i in x.view.recs and i in x.view.root_of and x.view.root_of[i] in x.rep["lineages"] and x.view.root_of[i] != L:
                lin = x.rep["lineages"][x.view.root_of[i]]
                out.append({"store": x.name, "lineage": x.view.root_of[i], "schema": lin["schema"], "state": lin["state"],
                            "reliance": lin["reliance"]})
    return sorted({tuple(sorted(d.items())): d for d in out}.values(), key=lambda d: (d["store"], d["lineage"]))


def identity(rep, root, readings, query):
    """(root, lens) of an impact answer: this checkout's report alone, as `graph` binds it, or, with Home's
    `readings`, every store read (this checkout's report, gated at the answer's head, in place of its own reading)
    and every store not read, by across.identity's form (Codex finding 72595e2154fd)."""
    if readings is None:
        g = G.answer(rep, query, None, None)
        return g["root"], g["lens"]
    from . import across as A
    mine = _mine(readings, root)
    reps = {x.name: x.rep for x in readings if x.why is None and x.name not in mine}
    reps[mine[0] if mine else HERE] = rep
    return A.identity(reps, _unavailable(readings, root), rep["code"], None, query)


def _mine(readings, root):
    """The names Home gives this checkout (one at most: Home refuses two names for one directory)."""
    return [x.name for x in readings if x.root is not None and os.path.realpath(x.root) == os.path.realpath(root)]


def _unavailable(readings, root):
    """[{store, why}] of Home's stores that could not be read, as `across` names them; this checkout's is read here."""
    from . import across as A
    mine = _mine(readings, root)
    return [{"store": x.name, "why": A._short(x.why)} for x in sorted(readings, key=lambda x: x.name) if x.why and x.name not in mine]


def impact_lines(m):
    """The impact answer as text, the count first: `impact: 0 affected`, or claims -> lineages [-> stores]."""
    n = len(m["stale"])
    if not n:
        head = "impact: 0 affected"
    else:
        head = f"impact: {n} stale claim(s) -> {len(m['affected'])} lineage(s) resting on them"
        head += f" -> {len(m['stores'])} other store(s)" if m["stores"] else ""
    out = [head]
    for s in m["stale"]:
        out.append(f"STALE {s['id']} ({s['lineage'][:12]}), accepted at {str(s['commit'])[:12]}")
        out += ["  " + " ".join(w for w in (f["verdict"], f["path"], f["detail"]) if w) for f in s["files"]]
        out += [f"  rests: {r['schema']} {r['lineage'][:12]} {r['state']} {r['reliance']}" for r in s["rests_on_it"]]
        out += [f"  rests in {e['store']}: {e['schema']} {e['lineage'][:12]} {e['state']} {e['reliance']}" for e in s.get("elsewhere", [])]
    out += [f"not read: {u['store']} ({u['why']}), what rests there is not seen" for u in m.get("unavailable", [])]
    if m["base"]:
        if m["already_stale"]:
            out.append(f"already stale at {m['base'][:12]}: " + ", ".join(str(a["id"]) for a in m["already_stale"]))
        out.append(f"changed since {m['base'][:12]}: {len(m['changed'])} file(s), {len(m['in_no_acceptance'])} in no acceptance"
                   + (": " + ", ".join(m["in_no_acceptance"]) if m["in_no_acceptance"] else ""))
    else:
        out.append("a file no witness reads and no mutant mutates is in no acceptance: give BASE..HEAD to list the changed ones")
    return "\n".join(out) + "\n"


def run(argv=None):
    root, argv = env_root(list(sys.argv[1:] if argv is None else argv))
    ap = argparse.ArgumentParser(prog="warrant drift")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--impact", nargs="?", const="HEAD", metavar="[BASE..]HEAD")
    ap.add_argument("--across", action="store_true", help="with --impact: Home's other stores too")
    a = ap.parse_args(argv)
    if a.across and a.impact is None:
        raise Failed("BAD_REQUEST", "--across goes with --impact")
    if a.impact is not None:
        base, _, head = a.impact.rpartition("..")
        head = resolve(root, head or "HEAD")
        base = resolve(root, base) if base else None
        rep = Repo(root).report()
        readings = None
        if a.across:
            from . import across as A
            from . import home as H
            readings = A.home_readings(H.load())
        m = impact(rep, root, head, base, readings)
        query = {"query": "impact", "head": head, "base": base, "across": a.across}
        r0, lens = identity(rep, root, readings, query)
        res = {"root": r0, "lens": lens, "query": query, "data": m, "checkout": rep["checkout"]}
        if a.json:
            dump(res)
        else:
            sys.stdout.write(impact_lines(m))
        return 1 if m["stale"] else 0
    d = drift(Repo(root).report(), root)
    if a.json:
        dump(d)
    else:
        sys.stdout.write(lines(d))
    return 1 if any(x["verdict"] != "UNCHANGED" for x in d.values()) else 0


if __name__ == "__main__":
    sys.exit(main(run))
