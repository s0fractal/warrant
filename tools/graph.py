#!/usr/bin/env python3
"""The record graph of this repository by query (warrant/graph.py over the engine's report), and the
Markdown views of the records as build artifacts.

    python3 tools/graph.py around ID | path ID | why ID     # a node; what it rests on; what rests on it
    python3 tools/graph.py grounded ID                       # whether a version and all it rests on stand (warrant.graph)
    python3 tools/graph.py frontier ACTOR                    # what waits for an actor
    python3 tools/graph.py impact BASE..HEAD                 # the lineages the records changed between two commits
                                                             # bear on, and under `drift` the claims the range makes
                                                             # stale with what rests on them (warrant drift --impact)
    python3 tools/graph.py delta BASE..HEAD                  # the records and lineages added, removed or changed
    python3 tools/graph.py export [--format json|dot]        # the whole record graph (dot: Graphviz text)
    python3 tools/graph.py views [--check]                   # build/views/{CLAIMS,ROADMAP,REVIEWS,WITNESSES}.md

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
from warrant import drift as DR            # noqa: E402
from warrant import review as RV           # noqa: E402
from warrant import roadmap as RM          # noqa: E402
from warrant import sources as SRC         # noqa: E402
from warrant.repo import Failed, Repo, dump, main  # noqa: E402
from warrant import graph as G             # noqa: E402

VIEWS = ("CLAIMS.md", "ROADMAP.md", "REVIEWS.md", "WITNESSES.md")


def code_id(root):
    """What decides a view besides the records, trust and profile: the working tree outside the store as one git tree id
    (a temporary index over every file Git would add, so two different uncommitted edits are two ids, not one `dirty`
    flag), the bytes of .warrant/claims.json (which shapes CLAIMS.md; the store's directory is not in that tree) and
    the bytes of the tools/graph.py that runs, which may come from another checkout (Codex 21eb439d on G11)."""
    import hashlib
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(d) / "index"))
        subprocess.run(["git", "-C", str(root), "add", "-A", "--", ".", ":!.warrant"], env=env, capture_output=True, check=True)
        tree = subprocess.run(["git", "-C", str(root), "write-tree"], env=env, capture_output=True, text=True,
                              check=True).stdout.strip()
    claims = Path(root) / ".warrant" / "claims.json"
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None  # noqa: E731
    return {"tree": tree, "claims": digest(claims), "tool": digest(Path(__file__).resolve())}


def render(repo):
    """The generated views, each under a line naming what decided it: `root` (the store's snapshot, full) and `lens`
    (warrant.graph.answer's content address of the code this tool runs from, the trust, the profile, the view's name
    and the checkout), as a query's result carries them (Codex b26d7983 on G11's closure); the checkout includes the
    code tree of each commit CLAIMS.md compares with HEAD, as this clone reads it, or that it cannot (Codex 7f4a36c5:
    a shallow clone rendered other bytes under the same lens)."""
    rep = repo.report()
    views = {"CLAIMS.md": CL.view(rep, repo.root), "ROADMAP.md": RM.view(rep), "REVIEWS.md": RV.view(rep),
             "WITNESSES.md": witnesses(rep)}
    code = json.dumps(dict(code_id(repo.root), trees=CL.trees_read(rep, repo.root)), sort_keys=True)
    out = {}
    for n, text in views.items():
        a = G.answer(rep, {"op": "view", "name": n}, None, code)
        head, _, rest = text.partition("\n")
        out[n] = f"{head}\n\nroot `{a['root']}` · lens `{a['lens']}`\n{rest}"
    return out


def witnesses(rep):
    """WITNESSES.md: the witness ledger (warrant.graph.ledger) as a view."""
    out = ["# Witness ledger", "", f"Generated from `.warrant/records.jsonl` (snapshot `{rep['snapshot'][:12]}`); a build artifact. "
           "It grants nothing, and no rule reads it.", "",
           "| actor | acceptances | refuted | challenges | replayed |", "|---|---|---|---|---|"]
    rows = G.ledger(rep)
    out += [f"| {a} | {len(x['accepted'])} | {len(x['refuted'])} | {len(x['challenged'])} | {len(x['replayed'])} |" for a, x in rows.items()]
    for a, x in rows.items():
        out += [f"- {a}: acceptance of `{v[:12]}` refuted by challenge `{c[:12]}`, reproduced" for v, c in x["refuted"]]
        out += [f"- {a}: challenge `{c[:12]}` reproduced on its target" for c in x["replayed"]]
    return "\n".join(out) + "\n"


def range_reports(repo, rng):
    base, head, s0, s1 = RV.range_snapshots(repo.root, rng)
    return base, head, [repo.report(s0), repo.report(s1)]


def impact(repo, rng):
    base, head, reps = range_reports(repo, rng)
    d = G.impact(*reps)
    d["drift"] = DR.impact(reps[1], repo.root, head, base)    # the code side: one definition, no harness run
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
    if cmd == "delta" and rest:
        base, head, reps = range_reports(repo, rest[0])
        return reps[1], {"base": base, "head": head}, {"op": "delta", "range": f"{base}..{head}"}, G.delta(*reps)
    if cmd == "export" and rest in ([], ["--format", "json"], ["--format", "dot"]):
        rep, fmt = repo.report(), rest[1] if rest else "json"
        return rep, None, {"op": "export", "format": fmt}, G.dot(rep["graph"]) if fmt == "dot" else rep["graph"]
    if cmd in ("around", "path", "why", "grounded") and rest:
        rep = repo.report()
        # the target is resolved in what the report read: the store with its declared sources beside it (Codex 12f81d92)
        snap, _ = SRC.with_sources(repo.root, repo.store.snapshot(), SRC.config_doc(repo.root))
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
