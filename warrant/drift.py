"""Whether the bytes a claims checker's acceptance ran on are still the bytes at this receiver's head (G14).

An acceptance names its `files`, {path: git blob}: each witness's test file, each mutant's mutated file and test
file, as the checker found them at the commit it ran (`warrant claims replay`; CI's `claims verify` holds the list to
that commit). Each is compared with HEAD's tree:

    UNCHANGED  the same bytes at the same path;
    MOVED      the path is gone from HEAD and the same bytes are at another path (unchanged, at its new path);
    CHANGED    other bytes at the path, with the first commit after the accepted one that changed it;
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
Home's other stores that rest on them. Given BASE, only the claims fresh at BASE and stale at HEAD are the change's;
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
from . import shapes as S
from .repo import Failed, Repo, dump, env_root, git, main

STALE = "STALE"
FRESH = ("UNCHANGED", "MOVED")
RANK = {"UNCHANGED": 0, "CHANGED": 1, "UNKNOWN": 2}     # the answer shown: fresh if any acceptance is, else what can be said


def resolve(root, rev):
    """The commit id `rev` names in this clone, or a refusal. A revision shaped as an option never reaches Git as one."""
    if not isinstance(rev, str) or not rev or rev.startswith("-"):
        raise Failed("BAD_REVISION", f"not a revision: {rev!r}")
    try:
        return git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    except subprocess.CalledProcessError:
        raise Failed("BAD_REVISION", f"no commit {rev!r} in this clone") from None


def first_change(root, commit, path, head="HEAD"):
    """The first commit after `commit`, on the way to HEAD, that changed `path` (None when none is found: the commit
    is not in this clone, or a merge brought the bytes). `commit` and `path` come from a record: only a commit id
    reaches Git, and the path is literal."""
    if not S.hex_of(commit, 40):
        return None
    try:
        out = git(root, "--literal-pathspecs", "log", "--reverse", "--format=%H", f"{commit}..{head}", "--", path).splitlines()
    except subprocess.CalledProcessError:
        return None
    return out[0] if out else None


def compare(root, commit, files, head, where, at="HEAD"):
    """[(verdict, path, detail)] of an acceptance's `files` against HEAD (`head`, {path: blob}; `where`, {blob: path})."""
    if not files:
        return [("UNKNOWN", "", "the acceptance names no files")]
    if not (isinstance(files, dict) and all(isinstance(b, str) for b in files.values())):
        return [("UNKNOWN", "", "the acceptance's files are not {path: blob}")]
    out = []
    for p, blob in sorted(files.items()):
        now = head.get(p)
        if now == blob:
            out.append(("UNCHANGED", p, ""))
        elif now is None and blob in where:
            out.append(("MOVED", p, f"now at {where[blob]}"))
        else:
            x = first_change(root, commit, p, at)
            since = f"since {x[:12]}" if x else f"since {str(commit)[:12]}"
            out.append(("CHANGED", p, since) if now else ("GONE", p, f"not at HEAD, {since}"))
    return out


def _verdict(rows):
    words = {v for v, _, _ in rows}
    if words <= set(FRESH):
        return "UNCHANGED"
    return "UNKNOWN" if words == {"UNKNOWN"} else "CHANGED"


def drift(rep, root, at="HEAD"):
    """{lineage: {id, version, verdict, commit, files}} for each live claim whose effective version the claims
    checker accepted: the comparison of the acceptance that is freshest, against commit `at` (a resolved id or HEAD)."""
    if not (Path(root) / ".warrant" / "claims.json").is_file():
        return {}
    done = C.acceptances(rep)
    try:
        head = C.blobs(root, at)
    except subprocess.CalledProcessError:
        head = {}
    where = {b: p for p, b in sorted(head.items(), reverse=True)}
    out = {}
    for L in sorted(C.live(rep)):
        eff = rep["lineages"][L]["effective"]
        if not done.get(eff):
            continue
        seen = [(x, compare(root, x, files, head, where, at)) for x, files in done[eff]]
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
    return {p for _, files in C.acceptances(rep).get(eff, []) if isinstance(files, dict) for p in files}


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
    `head` and `base` are resolved commit ids or HEAD; `rep` is this checkout's report, gated at `head`."""
    gate(rep, root, head)
    now = drift(rep, root, head)
    before = drift(rep, root, base) if base else {}
    stale, already = [], []
    for L, x in sorted(now.items(), key=lambda kv: str(kv[1]["id"])):
        if x["verdict"] == "UNCHANGED":
            continue
        if base and before.get(L, {}).get("verdict") != "UNCHANGED":
            already.append({"lineage": L, "id": x["id"]})
            continue
        row = {"lineage": L, "id": x["id"], "verdict": x["verdict"], "commit": x["commit"],
               "files": [f for f in x["files"] if f["verdict"] not in FRESH],
               "rests_on_it": [_row(rep, R) for R in rests_on(rep, L)]}
        if readings is not None:
            row["elsewhere"] = _elsewhere(readings, rep, L, root)
        stale.append(row)
    out = {"head": head, "base": base, "stale": stale, "affected": sorted({r["lineage"] for s in stale for r in s["rests_on_it"]}),
           "stores": sorted({e["store"] for s in stale for e in s.get("elsewhere", [])})}
    if base:
        named = set().union(*(_accepted_files(rep, L) for L in now)) if now else set()
        changed = changed_paths(root, base, head)
        out.update(already_stale=already, changed=changed, in_no_acceptance=[p for p in changed if p not in named])
    return out


def _elsewhere(readings, rep, L, root):
    """[{store, lineage, schema, state, reliance}] of the records in Home's other stores that rest on any version of L
    (warrant.across `rests`: an edge read from the citing record crosses stores, since a hash names the same record)."""
    from . import across as A
    read = [x for x in readings if x.why is None and (x.root is None or os.path.realpath(x.root) != os.path.realpath(root))]
    out = []
    for v in rep["lineages"][L]["versions"]:
        ids, _, _ = A._rests(read, v, None)
        for i in ids[1:]:
            for x in read:
                if i in x.view.recs and i in x.view.root_of and x.view.root_of[i] in x.rep["lineages"]:
                    lin = x.rep["lineages"][x.view.root_of[i]]
                    out.append({"store": x.name, "lineage": x.view.root_of[i], "schema": lin["schema"], "state": lin["state"],
                                "reliance": lin["reliance"]})
    return sorted({tuple(sorted(d.items())): d for d in out}.values(), key=lambda d: (d["store"], d["lineage"]))


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
        res = G.answer(rep, {"query": "impact", "head": head, "base": base, "across": a.across}, m, None)
        res["checkout"] = rep["checkout"]
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
