#!/usr/bin/env python3
"""The record graph by query: the repository's `.warrant/store` read as one graph of duties,
transitions, verdicts, questions and blobs, with Warrant's own assessment attached.

The graph is warrant_agent/graph.py's (the agent operation `graph` and its MCP tool `warrant_graph`
answer from the same functions over a frozen view); this command reads it from this checkout's store
or from the store of a Git commit (as Git objects, nothing checked out), and adds what only the
repository knows: SPEC claim ids and roadmap goal keys as targets, and which claims the mutants of a
changed source statement back (tools/claims.py why). Every store is judged under this checkout's
trust (`.warrant/trust.json` under `.warrant/roles.json`), the default profile, as of its latest
record: one receiver reading both sides of a range.

    python3 tools/graph.py path G11 | SPEC-3-22 | DUTY [--json]   # a goal, a claim or a duty, prerequisites first
    python3 tools/graph.py why warrant/engine.py:729 [--json]    # tools/claims.py why
    python3 tools/graph.py frontier --actor codex [--json]       # what is open for an actor
    python3 tools/graph.py impact BASE..HEAD [--json]            # claims, obligations and goals a change bears on
    python3 tools/graph.py delta BASE..HEAD [--json]             # nodes and edges added, changed, removed
    python3 tools/graph.py export [--at REV] (--json | --dot)    # the whole graph
    python3 tools/graph.py views [--check]                       # the Markdown projections, a build artifact

A range is two revisions; `BASE..` (no head) reads the head from this checkout's working tree. Output
is JSON (sorted, one document) with --json, else a short text form. The Markdown projections
(SPEC-CLAIMS.md, WITNESSES.md, ROADMAP.md, REVIEWS.md) are never committed: `views` writes them to
build/views/ (ignored), and `views --check` renders them here and in two more processes with other
hash seeds and refuses any difference (VIEW_NONDETERMINISTIC). Refusals print as `REFUSED <CODE> <detail>`.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("WARRANT_IMPL") or str(ROOT))
sys.path.insert(1, str(Path(__file__).resolve().parent))

import claims as CL                          # noqa: E402
import roadmap as RM                         # noqa: E402
from claimslib import eligibility as EL      # noqa: E402
from claimslib import reviews as RV          # noqa: E402
from claimslib import why as WHY             # noqa: E402
from warrant_agent import graph as G         # noqa: E402

VIEWS_DIR = Path("build") / "views"
VIEWS = ("SPEC-CLAIMS.md", "WITNESSES.md", "ROADMAP.md", "REVIEWS.md")
SEEDS = ("0", "1")                     # the hash seeds of the two other processes `views --check` renders in
REV = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/~^-]{0,199}\Z")   # a revision name: never an option, never a range
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
WORKTREE = None                        # a range's head read from this checkout's files


class Refused(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- stores and graphs

def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if r.returncode:
        raise Refused(f"git {args[0]}: {r.stderr.decode(errors='replace').strip()[:200]}", "GRAPH_REVISION")
    return r.stdout


def commit(root, rev):
    """The full id of the commit `rev` names (a branch, a tag, an abbreviation: resolved once, here). A name that is
    not a revision name (an option, a range, a path) is refused before Git sees it."""
    if not (isinstance(rev, str) and REV.match(rev) and ".." not in rev):
        raise Refused(f"{str(rev)[:60]!r} is not a revision name", "GRAPH_REVISION")
    return git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}").decode().strip()


def snapshot(root, rev):
    """The store at commit `rev` read as Git objects, or this checkout's store when `rev` is WORKTREE."""
    if rev is WORKTREE:
        return CL.Repo(root).snapshot()
    snap, problems = EL.store_at(root, rev)
    if problems:
        raise Refused(f"the store at {rev[:12]}: " + "; ".join(f"{c} {d}" for c, d in problems[:3]), "GRAPH_STORE")
    return snap


def graph_of(root, rev, trust):
    snap = snapshot(root, rev)
    report = CL.assessment(snap, trust)
    return G.build(snap, report), report


def parse_range(root, text):
    base, sep, head = (text or "").partition("..")
    if not (sep and base):
        raise Refused(f"{text!r} is not BASE..HEAD (or BASE.. for this checkout)", "GRAPH_USAGE")
    return commit(root, base), (commit(root, head) if head else WORKTREE)


# ---------------------------------------------------------------- repository names

def resolve_target(root, target):
    """A goal key (G<n>) as its question scope, a SPEC claim id as its current duty; anything else as given."""
    if RM.KEY_RE.match(target or ""):
        return RM.SCOPE + target
    if CL.ID_RE.match(target or ""):
        m = CL.Model(CL.Repo(root).snapshot(), CL.Repo(root).trust())
        n = m.current.get(target)
        if n is None or n.retired or not n.doc["duty"]:
            raise Refused(f"{target} is not a current claim with a duty", "GRAPH_TARGET")
        return n.doc["duty"]
    return target


def classes(root, snap, trust):
    """{duty id: (class, name)}: a SPEC claim (any duty of its lineage), a roadmap obligation (with its goal) or a
    pull request's review duty; other duties are left out."""
    out = {}
    cm = CL.Model(snap, trust)
    for n in cm.nodes.values():
        if not n.retired and n.doc["duty"]:
            out[n.doc["duty"]] = ("claim", n.id)
    try:
        cfg = RM.Roadmap(root).config()
        m = RM.Model(snap, trust, cfg)
        for did in m.obligations:
            out[did] = ("obligation", m.goal_of(did))
    except RM.Refused:
        pass
    recs, _ = CL.authentic(snap, trust)
    for did, r in recs.items():
        if r["type"] == "duty" and did not in out:
            s = RV.STATEMENT.match(r["body"]["statement"])
            if s:
                out[did] = ("review", f"#{s.group('pr')}")
    return out


# ---------------------------------------------------------------- impact

def head_tree(root, head):
    """A directory holding head's tree: this checkout for WORKTREE, else build/graph/trees/<tree id> written once
    from `git archive` (statements are read from the files of the head, never from the working tree)."""
    if head is WORKTREE:
        return Path(root)
    tree = git(root, "rev-parse", f"{head}^{{tree}}").decode().strip()
    out = Path(root) / "build" / "graph" / "trees" / tree
    if not (out / ".complete").is_file():
        data = git(root, "archive", "--format=tar", head)
        out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(out, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        (out / ".complete").write_text(tree + "\n")
    return out


def _hunks(diff):
    """{path: {head lines}} of a `git diff -U0`'s Python files (a pure deletion counts the head line it is at)."""
    out, path = {}, None
    for line in diff:
        if line.startswith("diff --git"):
            path = None
        elif line.startswith("+++ "):
            path = line[6:] if line.endswith(".py") and not line.startswith("+++ /dev/null") else None
        elif path is not None and line.startswith("@@"):
            m = HUNK.match(line)
            start, n = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            out.setdefault(path, set()).update(range(start, start + n) if n else [max(start, 1)])
    return out


def changed_lines(root, base, head):
    """{path: sorted lines of head} of the Python files under why's roots that differ from base (a deletion counts
    the head line it is at); and the paths of those deleted in head."""
    rng = ["--no-renames", "--no-color", base] + ([] if head is WORKTREE else [head])
    raw = git(root, "diff", "-U0", *rng, "--", *WHY.WHY_ROOTS).decode(errors="replace").splitlines()
    out = _hunks(raw)
    gone = git(root, "diff", "--name-only", "--diff-filter=D", *rng, "--", *WHY.WHY_ROOTS).decode().splitlines()
    return {p: sorted(v) for p, v in sorted(out.items())}, sorted(p for p in gone if p.endswith(".py"))


def statements(w, lines):
    """[{file, function, lines, mutants, claims}] of the statements of head the changed lines are in, with the
    claims BACKED there citing a mutant that changes them (why's own index)."""
    out = []
    for path, ls in lines.items():
        if path not in w.files:
            continue
        want = set(ls)
        for i, (_, fn, own) in enumerate(w.units(path)):
            if not want & set(own):
                continue
            mids = sorted(w.changes.get((path, i), ()), key=WHY._mid_key)
            claims = sorted({n.id: n.doc["duty"] for mid in mids for n in w.cited.get(mid, [])}.items(),
                            key=lambda kv: CL.id_key(kv[0]))
            out.append({"file": path, "function": fn, "lines": [min(own), max(own)], "mutants": mids,
                        "claims": [{"claim": c, "duty": d} for c, d in claims]})
    return out


def impact(root, base, head):
    repo = CL.Repo(root)
    trust = repo.trust()
    g0, _ = graph_of(root, base, trust)
    g1, _ = graph_of(root, head, trust)
    lines, gone = changed_lines(root, base, head)
    w = WHY.Why(CL.Repo(head_tree(root, head)))
    stmts = statements(w, lines)
    also = {c["duty"]: "statement" for s in stmts for c in s["claims"]}
    d = G.impact(g0, g1, also)
    cls = classes(root, snapshot(root, head), trust)
    for x in d["duties"]:
        x["class"], x["name"] = cls.get(x["duty"], ("duty", None))
    goals = sorted({q["scope"][len(RM.SCOPE):] for q in d["questions"] if (q["scope"] or "").startswith(RM.SCOPE)},
                   key=RM.key_n)
    return {"base": base, "head": head or "worktree", "statements": stmts, "deleted_files": gone,
            "records": d["records"],
            "claims": [x for x in d["duties"] if x["class"] == "claim"],
            "obligations": [x for x in d["duties"] if x["class"] == "obligation"],
            "reviews": [x for x in d["duties"] if x["class"] == "review"],
            "other_duties": [x for x in d["duties"] if x["class"] == "duty"],
            "questions": d["questions"], "goals": goals}


# ---------------------------------------------------------------- views

def render_views(root):
    """{name: bytes} of the four Markdown projections of this checkout's records."""
    repo = CL.Repo(root)
    model = CL.Model(repo.snapshot(), repo.trust())
    table = CL.challenge_table(repo, model)
    return {"SPEC-CLAIMS.md": CL.render(repo, model, table).encode(),
            "WITNESSES.md": CL.render_witnesses(repo, model, table).encode(),
            "ROADMAP.md": RM.render_view(RM.Roadmap(root).model()).encode(),
            "REVIEWS.md": RV.render_view(RV.Reviews(root).model()).encode()}


def digests(views):
    return {k: hashlib.sha256(v).hexdigest() for k, v in sorted(views.items())}


def other_process(root, seed):
    """The digests of the views as a child process with PYTHONHASHSEED=`seed` renders them."""
    env = dict(os.environ, PYTHONHASHSEED=seed)
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), f"--root={Path(root).resolve()}", "views", "--digests"],
                       capture_output=True, env=env, check=False)
    if r.returncode:
        raise Refused(f"the views did not render under PYTHONHASHSEED={seed}: "
                      f"{r.stderr.decode(errors='replace').strip()[-300:]}", "VIEW_NONDETERMINISTIC")
    return json.loads(r.stdout)


def views_check(root, views):
    """[(code, detail)]: each view rendered twice here and once per seed of SEEDS in another process, compared as
    bytes (digests); empty iff every rendering agrees."""
    out, here = [], digests(views)
    again = digests(render_views(root))
    runs = [("a second rendering in this process", again)] + [(f"a process with PYTHONHASHSEED={s}", other_process(root, s))
                                                               for s in SEEDS]
    for name in VIEWS:
        for what, got in runs:
            if got.get(name) != here[name]:
                out.append(("VIEW_NONDETERMINISTIC", f"{name}: {what} renders {str(got.get(name))[:12]}, this one {here[name][:12]}"))
    return out


# ---------------------------------------------------------------- text forms

def text_path(d):
    out = [f"{d['target']} ({d['kind']}): {len(d['duties'])} duties, {len(d['open'])} not DISCHARGED"]
    out += [f"  question {q['question'][:12]}…:{q['question'].split(':')[1]} [{q['state']}] {q['text']}" for q in d["questions"]]
    for x in d["duties"]:
        req = f" requires {', '.join(r[:12] for r in x['requires'])}" if x["requires"] else ""
        cl = "; ".join(f"{c['transition'][:12]}:{c['item']} {c['verdict']}" for c in x["closures"])
        out.append(f"  {'*' if x['root'] else ' '} [{x['state']}] {x['duty'][:12]} {x['statement']}{req}"
                   + (f" (closures: {cl})" if cl else "") + (" (cycle)" if x["cycle"] else ""))
    return "\n".join(out) + "\n"


def text_frontier(actor, items):
    out = [f"{actor}: {len(items)} open"]
    out += [f"  {x['need']}: {(x.get('duty') or x.get('transition') or '')[:12]} {x.get('statement') or ''}".rstrip()
            for x in items]
    return "\n".join(out) + "\n"


def text_impact(d):
    out = [f"{d['base'][:12]}..{d['head'][:12]}: {len(d['statements'])} statements, "
           f"{len(d['records']['added'])} records added, {len(d['records']['removed'])} removed"]
    for k in ("claims", "obligations", "reviews", "other_duties"):
        for x in d[k]:
            out.append(f"  {k[:-1].replace('_', ' ')} {x['name'] or x['duty'][:12]} [{x['state']}] via {', '.join(x['via'])}: "
                       f"{x['statement']}")
    out += [f"  goal {g}" for g in d["goals"]]
    return "\n".join(out) + "\n"


def text_delta(d):
    c = d["counts"]
    out = [f"nodes +{c['added']} -{c['removed']} ~{c['changed']}; edges +{c['edges_added']} -{c['edges_removed']} "
           f"~{c['edges_changed']}"]
    sign = {"added": "+", "removed": "-", "changed": "~"}
    out += [f"  {sign[x['change']]} {x['node']['kind']} {x['node']['id'][:12]} [{x['node']['state']}] {x['node']['label'] or ''}".rstrip()
            for x in d["nodes"] if x["node"]["kind"] not in ("blob",)]
    return "\n".join(out) + "\n"


def emit(doc, as_json, text):
    if as_json:
        print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False))
    else:
        print(text(doc), end="")


# ---------------------------------------------------------------- command line

def cmd_views(root, a):
    """Write the four views to build/views/ (with --check, after comparing their renderings); --digests prints the
    digests only (the child process of views_check)."""
    views = render_views(root)
    if a.digests:
        print(json.dumps(digests(views), sort_keys=True))
        return 0
    problems = views_check(root, views) if a.check else []
    out = root / VIEWS_DIR
    out.mkdir(parents=True, exist_ok=True)
    for name, data in views.items():
        (out / name).write_bytes(data)
    for code, detail in problems:
        print(f"REFUSED {code} {detail}")
    print(f"VIEWS: {', '.join(f'{k} {v[:12]}' for k, v in digests(views).items())} in {out}"
          + ("; deterministic" if a.check and not problems else "") + (f"; {len(problems)} refused" if problems else ""))
    return 1 if problems else 0


def cmd_path(root, a, trust):
    g, _ = graph_of(root, WORKTREE, trust)
    d = G.path(g, resolve_target(root, a.target))
    emit(dict(d, target=a.target, resolved=d["target"]), a.json, text_path)


def cmd_frontier(root, a, trust):
    _, rep = graph_of(root, WORKTREE, trust)
    emit({"actor": a.actor, "frontier": G.frontier(rep, a.actor)}, a.json, lambda d: text_frontier(d["actor"], d["frontier"]))


def cmd_impact(root, a, trust):
    emit(impact(root, *parse_range(root, a.range)), a.json, text_impact)


def cmd_delta(root, a, trust):
    base, head = parse_range(root, a.range)
    emit(G.delta(graph_of(root, base, trust)[0], graph_of(root, head, trust)[0]), a.json, text_delta)


def cmd_export(root, a, trust):
    g, _ = graph_of(root, commit(root, a.at) if a.at else WORKTREE, trust)
    print(json.dumps(g, indent=1, sort_keys=True, ensure_ascii=False) if a.json else G.dot(g), end="\n" if a.json else "")


def parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(ROOT), help="the repository (default: this checkout)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("path", help="what a goal, a claim or a duty leads to, prerequisites first")
    p.add_argument("target", metavar="G<n>|SPEC-…|DUTY|QUESTION|SCOPE")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("why", help="the claims, obligations and goals a source statement serves (tools/claims.py why)")
    p.add_argument("target", metavar="FILE:LINE")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("frontier", help="what is open for an actor (the engine's frontier)")
    p.add_argument("--actor", required=True)
    p.add_argument("--json", action="store_true")
    for name, what in (("impact", "the claims, obligations and goals the changed statements and records bear on"),
                       ("delta", "nodes and edges added, changed or removed between two stores")):
        p = sub.add_parser(name, help=what)
        p.add_argument("range", metavar="BASE..HEAD")
        p.add_argument("--json", action="store_true")
    p = sub.add_parser("export", help="the whole graph")
    p.add_argument("--at", help="a revision whose store to read (default: this checkout's)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--json", action="store_true")
    g.add_argument("--dot", action="store_true")
    p = sub.add_parser("views", help="write the Markdown projections to build/views/ (never committed)")
    p.add_argument("--check", action="store_true", help="also render them in two more processes and compare")
    p.add_argument("--digests", action="store_true", help=argparse.SUPPRESS)
    return ap


COMMANDS = {"path": cmd_path, "frontier": cmd_frontier, "impact": cmd_impact, "delta": cmd_delta, "export": cmd_export}


def main(argv=None):
    ap = parser()
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.cmd is None:
        ap.print_help()
        return 2
    try:
        if a.cmd == "why":
            return WHY.cmd_why(CL.Repo(root), argparse.Namespace(target=a.target, uncovered=None, json=a.json))
        if a.cmd == "views":
            return cmd_views(root, a)
        COMMANDS[a.cmd](root, a, CL.Repo(root).trust())
        return 0
    except G.Unknown as e:
        print(f"REFUSED GRAPH_TARGET {e}", file=sys.stderr)
        return 2
    except (Refused, CL.Refused) as e:
        print(f"REFUSED {e.code or 'GRAPH'} {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
