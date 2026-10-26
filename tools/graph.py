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
is JSON (sorted, one document) with --json, else a short text form. Every result carries `root`, what it
was computed from (full commit ids, or the working tree's digest, and each store's snapshot digest), and
`lens`, the content address of everything else that decides it (the whole tree this tool runs from but
the store, the packages, the pins, the trust, the profile and the query: `lens`): the same lens over the
same root gives the same bytes, so a result may be cached by (lens, root) and re-derived by anyone. The Markdown projections
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
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("WARRANT_IMPL") or str(ROOT))
sys.path.insert(1, str(Path(__file__).resolve().parent))

import claims as CL                          # noqa: E402
import roadmap as RM                         # noqa: E402
from claimslib import eligibility as EL      # noqa: E402
from claimslib import reviews as RV          # noqa: E402
from claimslib import why as WHY             # noqa: E402
from warrant import jcs as C                 # noqa: E402
from warrant.store import code_identity      # noqa: E402
from warrant_agent import adapter_id         # noqa: E402
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


# ---------------------------------------------------------------- identities: root and lens

UNHASHED = (".warrant/store/",)      # the root, named apart (root_of); every other file of the tree may decide


def _rels(top):
    """The relative paths of the files under `top`: git's tracked and untracked unignored files when `top` is the top
    level of a checkout, else every file under it but bytecode (a copy, as the mutant runner makes)."""
    r = subprocess.run(["git", "-C", str(top), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if r.returncode == 0 and Path(r.stdout.strip()).resolve() == top:
        listed = git(top, "ls-files", "-z", "--cached") + b"\0" + git(top, "ls-files", "-z", "--others", "--exclude-standard")
        return {x for x in listed.decode().split("\0") if x}
    return {p.relative_to(top).as_posix() for p in top.rglob("*")
            if (p.is_file() or p.is_symlink()) and "__pycache__" not in p.parts and ".git" not in p.parts}


def _referent(link):
    """The bytes a symlink makes a reader read: a file's digest, or every file's under a directory it names (its
    link text alone would leave them out: Codex 6ff8280a91ea on #209, why read a source through a link)."""
    target = link.resolve()
    if target.is_file():
        return hashlib.sha256(target.read_bytes()).digest()
    if target.is_dir():
        h = hashlib.sha256()
        for q in sorted(target.rglob("*")):
            if q.is_file() and "__pycache__" not in q.parts:
                h.update(q.relative_to(target).as_posix().encode() + b"\0" + hashlib.sha256(q.read_bytes()).digest())
        return h.digest()
    return b"absent"


def tree_digest(top):
    """The whole tree at `top` but the store, in the form of tests/mutants.py source_digest (the path, mode and bytes
    of every tracked and untracked unignored file as it is on disk): no list of folders, so no deciding module can be
    left out. A symlink counts with the bytes it leads to (_referent). The store is the root's, not the lens's."""
    top = Path(top).resolve()
    h = hashlib.sha256()
    for rel in sorted(_rels(top)):
        if any(rel.startswith(x) for x in UNHASHED):
            continue
        f = top / rel
        if f.is_symlink():
            mode, data = b"120000", os.readlink(f).encode() + b"\0" + _referent(f)
        elif f.is_file():
            mode, data = (b"100755" if os.access(f, os.X_OK) else b"100644"), f.read_bytes()
        else:
            continue
        h.update(rel.encode() + b"\0" + mode + b"\0" + hashlib.sha256(data).digest())
    return "files:" + h.hexdigest()


def lens(root, assessed, query):
    """The lens (warrant_agent/graph.py lens_id) of a result of this tool: its code is the whole tree this tool runs
    from (tree_digest: its code, tests and mutant harnesses, the .warrant/ pins and configuration), the packages
    imported (the engine's code identity with the signature library's version, the agent's adapter_id) and the
    queried repository's .warrant/ files; `assessed` the operands of every assessment it read (G.operands)."""
    pins = {p.name: C.digest(p.read_bytes()) for p in sorted((Path(root) / ".warrant").glob("*.json"))}
    code = {"tool": tree_digest(ROOT), "engine": code_identity(), "agent": adapter_id(), "pins": pins}
    return G.lens_id(code, assessed, query)


def root_of(root, rev, snapshot_digest):
    """What a result was computed from: the commit (its full id) or this checkout's working tree (its tree_digest),
    and the store's snapshot digest."""
    out = {"commit": rev} if rev is not WORKTREE else {"worktree": tree_digest(root)}
    return dict(out, snapshot=snapshot_digest)


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
    """A directory holding head's tree: this checkout for WORKTREE, else a new directory under build/graph/ that
    `git archive` of head fills for this call alone; the caller removes it. Never a cache: an extraction kept between
    calls is a mutable copy whose edits change the answer under the same root and lens (Codex 83ba61ff822d on #209)."""
    if head is WORKTREE:
        return Path(root)
    base = Path(root) / "build" / "graph"
    base.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="tree-", dir=base))
    data = git(root, "archive", "--format=tar", head)
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(out, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    return out


def _hunk(line):
    """The head lines one `@@` header of `git diff -U0` covers (a pure deletion: the head line it is at)."""
    m = HUNK.match(line)
    start, n = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
    return range(start, start + n) if n else [max(start, 1)]


def _hunks(diff):
    """{path: {head lines}} of a `git diff -U0`'s Python files."""
    out, path = {}, None
    for line in diff:
        if line.startswith("diff --git"):
            path = None
        elif line.startswith("+++ "):
            path = line[6:] if line.endswith(".py") and not line.startswith("+++ /dev/null") else None
        elif path is not None and line.startswith("@@"):
            out.setdefault(path, set()).update(_hunk(line))
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
    g0, r0 = graph_of(root, base, trust)
    g1, r1 = graph_of(root, head, trust)
    lines, gone = changed_lines(root, base, head)
    tree = head_tree(root, head)
    try:
        stmts = statements(WHY.Why(CL.Repo(tree)), lines)
    finally:
        if head is not WORKTREE:
            shutil.rmtree(tree, ignore_errors=True)
    also = {c["duty"]: "statement" for s in stmts for c in s["claims"]}
    d = G.impact(g0, g1, also)
    # A duty removed in the range is classed as the base held it: an obligation of its goal still.
    cls = {**classes(root, snapshot(root, base), trust), **classes(root, snapshot(root, head), trust)}
    for x in d["duties"]:
        x["class"], x["name"] = cls.get(x["duty"], ("duty", None))
    goals = sorted({q["scope"][len(RM.SCOPE):] for q in d["questions"] if (q["scope"] or "").startswith(RM.SCOPE)},
                   key=RM.key_n)
    return {"base": base, "head": head or "worktree", "root": {"base": root_of(root, base, g0["snapshot"]), "head": root_of(root, head, g1["snapshot"])},
            "assessed": [G.operands(r0), G.operands(r1)],
            "statements": stmts, "deleted_files": gone,
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
    """A result as JSON (its root and lens members included) or its text form, root and lens on the last line."""
    if as_json:
        print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False))
    else:
        print(text(doc) + f"root {json.dumps(doc['root'], sort_keys=True)} lens {doc['lens']}\n", end="")


# ---------------------------------------------------------------- command line

def cmd_views(root, a):
    """Write the four views to build/views/ with IDENTITY.json, their root and lens (with --check, after comparing
    their renderings); --digests prints the digests only (the child process of views_check)."""
    views = render_views(root)
    if a.digests:
        print(json.dumps(digests(views), sort_keys=True))
        return 0
    problems = views_check(root, views) if a.check else []
    out = root / VIEWS_DIR
    out.mkdir(parents=True, exist_ok=True)
    for name, data in views.items():
        (out / name).write_bytes(data)
    trust = CL.Repo(root).trust()
    ident = {"root": root_of(root, WORKTREE, CL.Repo(root).snapshot().digest),
             "lens": lens(root, [{"trust": trust.digest}], {"op": "views"}), "views": digests(views)}
    (out / "IDENTITY.json").write_text(json.dumps(ident, indent=1, sort_keys=True) + "\n")
    for code, detail in problems:
        print(f"REFUSED {code} {detail}")
    print(f"VIEWS: {', '.join(f'{k} {v[:12]}' for k, v in digests(views).items())} in {out}; lens {ident['lens'][:12]}"
          + ("; deterministic" if a.check and not problems else "") + (f"; {len(problems)} refused" if problems else ""))
    return 1 if problems else 0


def cmd_path(root, a, trust):
    g, rep = graph_of(root, WORKTREE, trust)
    d = G.path(g, resolve_target(root, a.target))
    emit(dict(d, target=a.target, resolved=d["target"], root=root_of(root, WORKTREE, g["snapshot"]),
              lens=lens(root, [G.operands(rep)], {"op": "path", "target": a.target})), a.json, text_path)


def cmd_frontier(root, a, trust):
    g, rep = graph_of(root, WORKTREE, trust)
    emit({"actor": a.actor, "frontier": G.frontier(rep, a.actor), "root": root_of(root, WORKTREE, g["snapshot"]),
          "lens": lens(root, [G.operands(rep)], {"op": "frontier", "actor": a.actor})}, a.json,
         lambda d: text_frontier(d["actor"], d["frontier"]))


def cmd_impact(root, a, trust):
    d = impact(root, *parse_range(root, a.range))
    emit(dict(d, lens=lens(root, d.pop("assessed"), {"op": "impact"})), a.json, text_impact)


def cmd_delta(root, a, trust):
    base, head = parse_range(root, a.range)
    (g0, r0), (g1, r1) = graph_of(root, base, trust), graph_of(root, head, trust)
    emit(dict(G.delta(g0, g1), root={"base": root_of(root, base, g0["snapshot"]), "head": root_of(root, head, g1["snapshot"])},
              lens=lens(root, [G.operands(r0), G.operands(r1)], {"op": "delta"})), a.json, text_delta)


def cmd_export(root, a, trust):
    rev = commit(root, a.at) if a.at else WORKTREE
    g, rep = graph_of(root, rev, trust)
    ident = {"root": root_of(root, rev, g["snapshot"]),
             "lens": lens(root, [G.operands(rep)], {"op": "export", "format": "json" if a.json else "dot"})}
    if a.json:
        print(json.dumps(dict(g, **ident), indent=1, sort_keys=True, ensure_ascii=False))
    else:
        print(f"// root {json.dumps(ident['root'], sort_keys=True)} lens {ident['lens']}\n" + G.dot(g), end="")


def cmd_why(root, a, trust):
    """tools/claims.py why FILE:LINE, with the root (this checkout's tree and store) and the lens it was read under:
    why reads no assessment, only the claims under `trust` (Codex 26b46cfde7dd on #209: it carried neither)."""
    repo = CL.Repo(root)
    m = WHY.WHY_LINE.match(a.target)
    if not m:
        raise CL.Refused(f"{a.target!r} is not FILE:LINE", "WHY_USAGE")
    d = WHY.Why(repo).at(WHY._why_path(repo, m.group(1)), int(m.group(2)))
    emit(dict(d, root=root_of(root, WORKTREE, repo.snapshot().digest),
              lens=lens(root, [{"trust": trust.digest}], {"op": "why", "target": a.target})), a.json, WHY.render_why)


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


COMMANDS = {"why": cmd_why, "path": cmd_path, "frontier": cmd_frontier, "impact": cmd_impact, "delta": cmd_delta, "export": cmd_export}


def main(argv=None):
    ap = parser()
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.cmd is None:
        ap.print_help()
        return 2
    try:
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
