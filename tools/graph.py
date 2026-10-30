#!/usr/bin/env python3
"""The record graph of this repository by query (warrant/graph.py over the engine's report), and the
Markdown views of the records as build artifacts.

    python3 tools/graph.py around ID | path ID | why ID     # a node; what it rests on; what rests on it
    python3 tools/graph.py frontier ACTOR                    # what waits for an actor
    python3 tools/graph.py impact BASE..HEAD                 # the lineages the records changed between two commits
                                                             # bear on, and the claims whose mutants change a file
                                                             # the range touches
    python3 tools/graph.py views [--check]                   # build/views/{CLAIMS,ROADMAP,REVIEWS}.md

A query's result is JSON: {root, lens, query, data}. `root` names the store read (its snapshot digest; with
impact the two commits too); `lens` is the content address of everything else that decides the result (the
engine's code, this tree outside the store as its git tree id, the trust, the profile and the query). The
same lens over the same root gives the same bytes. views --check renders twice more, in processes with other
hash seeds, and refuses a difference (VIEW_NONDETERMINISTIC)."""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from warrant import claims as CL           # noqa: E402
from warrant import gate as GT             # noqa: E402
from warrant import review as RV           # noqa: E402
from warrant import roadmap as RM          # noqa: E402
from warrant.repo import Failed, Repo, dump, main  # noqa: E402
from warrant import graph as G             # noqa: E402

VIEWS = ("CLAIMS.md", "ROADMAP.md", "REVIEWS.md")


def code_id(root):
    """The tree this tool runs from, outside the store: the git tree ids of every top-level entry but .warrant/."""
    rows = subprocess.run(["git", "-C", str(root), "ls-tree", "HEAD"], capture_output=True, text=True, check=True).stdout
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", ":!.warrant"], capture_output=True,
                           text=True, check=True).stdout
    return {"tree": "\n".join(r for r in rows.splitlines() if r.split("\t")[1] != ".warrant"), "dirty": bool(dirty)}


def render(repo):
    rep = repo.report()
    return {"CLAIMS.md": CL.view(rep, repo.root), "ROADMAP.md": RM.view(rep), "REVIEWS.md": RV.view(rep)}


def impact(repo, rng):
    base, _, head = rng.partition("..")
    git = lambda *a: subprocess.run(["git", "-C", str(repo.root), *a], capture_output=True, text=True, check=True).stdout.strip()
    base, head = git("rev-parse", "--verify", f"{base}^{{commit}}"), git("rev-parse", "--verify", f"{head or 'HEAD'}^{{commit}}")
    reps = []
    for c in (base, head):
        snap, problems = GT.store_at(repo.root, c)
        if problems:
            raise Failed("STORE", f"{c[:12]}: {problems[:2]}")
        reps.append(repo.report(snap))
    d = G.impact(*reps)
    changed = set(git("diff", "--name-only", base, head).splitlines())
    known = CL.harness(repo.root)
    by_file = {m for m, (f, _, _) in known.items() if f in changed}
    claims = sorted(b["id"] for b in CL.live(reps[1]).values() if set(b["mutants"]) & by_file)
    d.update(files=sorted(changed), claims_by_mutated_file=claims)
    return reps[1], {"base": base, "head": head}, d


def write_views(repo, check):
    """Write build/views/; with `check`, render twice more under other hash seeds and refuse a difference."""
    out = repo.root / "build" / "views"
    views = render(repo)
    out.mkdir(parents=True, exist_ok=True)
    for n, text in views.items():
        (out / n).write_text(text)
    if check:
        for seed in ("1", "2"):
            r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "views-json"], capture_output=True, text=True,
                               env=dict(os.environ, PYTHONHASHSEED=seed), check=True)
            if json.loads(r.stdout) != views:
                raise Failed("VIEW_NONDETERMINISTIC", f"the views differ under PYTHONHASHSEED={seed}")
    print(f"views: {', '.join(VIEWS)} in {out}")


def ask(repo, cmd, rest):
    """(report, roots or None, query, data) of a query command."""
    _, profile, _ = repo.config()
    if cmd == "impact" and rest:
        rep, roots, data = impact(repo, rest[0])
        return rep, roots, {"op": "impact", "range": rest[0]}, data
    if cmd in ("around", "path", "why") and rest:
        rep = repo.report()
        snap = repo.store.snapshot()
        ids = [i for i in list(snap.lines) + list(snap.blobs) if i.startswith(rest[0])]
        if len(set(ids)) != 1:
            raise Failed("TARGET", f"{rest[0]} names {len(set(ids))} records or blobs")
        return rep, None, {"op": cmd, "target": ids[0]}, getattr(G, cmd)(rep, ids[0])
    if cmd == "frontier" and rest:
        rep = repo.report()
        return rep, None, {"op": cmd, "actor": rest[0]}, G.frontier(rep, profile, rest[0])
    raise Failed("USAGE", __doc__.split("\n\n")[1])


def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        raise Failed("USAGE", __doc__.split("\n\n")[1])
    repo = Repo()
    cmd, rest = argv[0], argv[1:]
    if cmd == "views":
        write_views(repo, "--check" in rest)
        return 0
    if cmd == "views-json":
        print(json.dumps(render(repo)))
        return 0
    rep, roots, query, data = ask(repo, cmd, rest)
    out = G.answer(rep, query, data, json.dumps(code_id(repo.root), sort_keys=True))
    if roots:
        out["root"] = {"snapshot": out["root"], **roots}
    dump(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(run))
