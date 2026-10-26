#!/usr/bin/env python3
"""tools/graph.py, the record graph by query over this repository and over a fixture Git repository: path, why,
frontier, export and views (Z17, Z20-Z23), impact and delta over a range (Z18, Z19), root and lens (Z27, Z31),
and every byte a query reads in one of them (Z32, Z33). The engine and the agent operation are graph_test.py's.
Split from graph_test.py so the agent mutants, which target that file, do not run these cases (#209: a shard
of them outran its 20 minutes).

    python3 tests/graph_tools_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_world import ROOT, check, finish
from warrant_agent import graph as G

# tools/graph.py of the tree under test: a mutant of a tool runs from its copy in $WARRANT_IMPL/tools.
_impl = os.environ.get("WARRANT_IMPL")
TOOLS = Path(_impl) / "tools" if _impl and (Path(_impl) / "tools" / "graph.py").is_file() else ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import graph as GT                  # noqa: E402

REMOVED = "d085efe4f157d4e2a309298043b26737d3f40e1368e36bbc192f5d3c1c0f292e"
GIT = ["git", "-c", "user.name=graph-test", "-c", "user.email=graph@invalid", "-c", "commit.gpgsign=false",
       "-c", "gc.auto=0"]


def tool(*argv, root=ROOT):
    r = subprocess.run([sys.executable, str(TOOLS / "graph.py"), "--root", str(root), *argv], capture_output=True,
                       text=True, check=False, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return r.returncode, r.stdout, r.stderr


def repository_cases():
    rc, out, err = tool("path", "G9", "--json")
    p = json.loads(out) if rc == 0 else {}
    seen, ordered = set(), True
    for x in p.get("duties", []):
        ordered &= all(r in seen for r in x["requires"] if r in {y["duty"] for y in p["duties"]})
        seen.add(x["duty"])
    rc2, out2, _ = tool("path", "SPEC-3-22", "--json")
    p2 = json.loads(out2) if rc2 == 0 else {}
    import claims as CL
    duty = CL.Model(CL.Repo(ROOT).snapshot(), CL.Repo(ROOT).trust()).current["SPEC-3-22"].doc["duty"]
    check("Z17", p.get("kind") == "scope" and p.get("resolved") == "roadmap:G9" and p.get("target") == "G9" and p["questions"]
          and all(q["scope"] == "roadmap:G9" for q in p["questions"]) and ordered
          and p2.get("kind") == "duty" and [x["duty"] for x in p2["duties"] if x["root"]] == [duty],
          "graph.py path names a goal by its key (the scope roadmap:G<n>) and a SPEC claim by its id (its current "
          "duty), prerequisites first", (rc, err[-300:], p2.get("kind")))

    rc, out, err = tool("why", "warrant/engine.py:200", "--json")
    rcw = subprocess.run([sys.executable, str(TOOLS / "claims.py"), "--root", str(ROOT), "why", "warrant/engine.py:200",
                          "--json"], capture_output=True, text=True, check=False)
    gw = json.loads(out) if rc == 0 else {}
    ident = {k: gw.pop(k, None) for k in ("root", "lens")}
    check("Z21", rc == 0 and gw == json.loads(rcw.stdout) and gw["file"] == "warrant/engine.py",
          "graph.py why is tools/claims.py why", (rc, err[-300:]))
    check("Z31", isinstance(ident["lens"], str) and set(ident["root"] or {}) == {"worktree", "snapshot"},
          "graph.py why carries root and lens like every other query (Codex 26b46cfde7dd)", ident)

    rc, out, err = tool("frontier", "--actor", "codex", "--json")
    fr = json.loads(out)["frontier"] if rc == 0 else None
    rc2, dot, _ = tool("export", "--dot")
    rc3, js, _ = tool("export", "--json")
    g = json.loads(js) if rc3 == 0 else {}
    check("Z22", rc == 0 and isinstance(fr, list) and all("need" in x for x in fr) and rc2 == 0
          and dot.startswith("// root ") and dot.splitlines()[1] == "digraph warrant {"
          and dot.count("\n") == len(g.get("nodes", [])) + len(g.get("edges", [])) + 4 and g.get("lens") and g.get("root")
          and g.get("graph") == G.GRAPH,
          "graph.py frontier and export (json, dot) read this checkout's store", (rc, rc2, rc3, err[-300:]))

    vw = GT.render_views(ROOT)
    clean = GT.views_check(ROOT, vw)
    doctored = dict(vw, **{"ROADMAP.md": vw["ROADMAP.md"] + b"\n"})
    bad = GT.views_check(ROOT, doctored)
    check("Z20", clean == [] and [c for c, _ in bad] == ["VIEW_NONDETERMINISTIC"] * 3 and "ROADMAP.md" in bad[0][1]
          and sorted(vw) == sorted(GT.VIEWS),
          "views --check renders the four projections here again and in processes with two other hash seeds, and "
          "refuses a view any rendering differs from", bad)


def revision_cases():
    refused = []
    for rev in ("--output=x", "-p", "HEAD..master", "a b", ""):
        try:
            GT.commit(ROOT, rev)
            refused.append((rev, "resolved"))
        except GT.Refused as e:
            refused.append((rev, e.code))
    rc, _, err = tool("delta", "--", "--output=x..")
    # Two layers hold this refusal: the shape of a revision name, and --end-of-options before it reaches Git; a
    # mutant of either alone leaves the other refusing (unburned, by design).
    check("Z23", all(code == "GRAPH_REVISION" for _, code in refused) and rc == 2 and "GRAPH_REVISION" in err,
          "a revision that is an option, a range, or not a name is refused before Git reads it", refused)


def lens_cases(d):
    """`root` and `lens` (a teammate's request on #209): a lens changes with any deciding module, wherever it lives,
    and with the query; never with the store, which is the root's."""
    base = GT.tree_digest(d)
    moved = {}
    for rel in ("warrant/engine.py", "warrant_agent/graph.py", "tools/claimslib/why.py", "tests/mutants.py",
                ".warrant/roles.json"):
        f = d / rel
        keep = f.read_bytes()
        f.write_bytes(keep + b"\n")
        moved[rel] = GT.tree_digest(d) != base
        f.write_bytes(keep)
    rec = d / ".warrant" / "store" / "records" / ("e" * 64 + ".json")
    rec.write_text("{}")
    store_only = GT.tree_digest(d) == base
    rec.unlink()
    copy = Path(tempfile.mkdtemp(prefix="warrant-graph-plain-"))
    try:
        shutil.copytree(d / "tools", copy / "tools")
        plain = GT.tree_digest(copy)
        (copy / "tools" / "claimslib" / "why.py").write_text("# changed\n")
        plain_moved = GT.tree_digest(copy) != plain
    finally:
        shutil.rmtree(copy, ignore_errors=True)
    rc, out, _ = tool("path", "G9", "--json")
    rc2, out2, _ = tool("path", "G9", "--json")
    rc3, out3, _ = tool("path", "G10", "--json")
    one, two, other = (json.loads(x) if r == 0 else {} for r, x in ((rc, out), (rc2, out2), (rc3, out3)))
    check("Z27", all(moved.values()) and store_only and plain_moved and out == out2 and one.get("lens")
          and one["lens"] != other.get("lens") and one["root"] == other.get("root")
          and set(one["root"]) == {"worktree", "snapshot"},
          "a result's lens hashes the whole tree the tool runs from but the store (engine, agent, tools, mutant "
          "harness, pins: a change in any of them changes it, in a checkout or a plain copy) and its query; the store "
          "is the root's; the same lens over the same root gives the same bytes", (moved, store_only, plain_moved))


def provenance_cases(d, base, head):
    """Codex's findings on head 6 (872d780): 83ba61ff822d and 6ff8280a91ea. Every byte a query reads is in its root or
    its lens."""
    rc, out, _ = tool("impact", f"{base}..{head}", "--json", root=d)
    first = json.loads(out) if rc == 0 else {}
    left = sorted(p.name for p in (d / "build" / "graph").iterdir()) if (d / "build" / "graph").is_dir() else []
    planted = GT.head_tree(d, head)                    # an extraction a reader could edit, as a kept cache was
    eng = planted / "warrant" / "engine.py"
    eng.write_text(eng.read_text().replace('b["item"] == index and sorted(b["evidence"]) == want:',
                                           'b["item"] == index and sorted(list(b["evidence"])) == want:'))
    rc2, out2, _ = tool("impact", f"{base}..{head}", "--json", root=d)
    second = json.loads(out2) if rc2 == 0 else {}
    shutil.rmtree(planted, ignore_errors=True)
    check("Z32", rc == 0 and left == [] and second.get("statements") == first.get("statements") and first["statements"],
          "impact reads the named commit's tree from a fresh extraction it removes: none is kept, and an edited one "
          "changes nothing", (left, rc2))

    outside = Path(tempfile.mkdtemp(prefix="warrant-graph-referent-")) / "source.py"
    link = d / "tools" / "linked_source.py"
    try:
        outside.write_text("answer = 1\n")
        link.symlink_to(outside)
        rc, out, _ = tool("why", "tools/linked_source.py:1", "--json", root=d)
        one = json.loads(out) if rc == 0 else {}
        outside.write_text("answer = 2\n")
        rc2, out2, _ = tool("why", "tools/linked_source.py:1", "--json", root=d)
        two = json.loads(out2) if rc2 == 0 else {}
    finally:
        link.unlink(missing_ok=True)
        shutil.rmtree(outside.parent, ignore_errors=True)
    check("Z33", one.get("source") == "answer = 1" and two.get("source") == "answer = 2"
          and (one.get("root"), one.get("lens")) != (two.get("root"), two.get("lens")),
          "a source read through a symlink is bound by the bytes it leads to: another referent, another identity",
          (one.get("root"), two.get("root")))


def fixture_repo():
    """A Git repository holding this checkout's store, code, tools and tests at commit `base`; commit `head` changes
    one statement of warrant/engine.py that mutant M05 changes and deletes one record; the working tree still has
    that record."""
    d = Path(tempfile.mkdtemp(prefix="warrant-graph-"))
    for top in (".warrant", "warrant", "warrant_agent", "tools", "tests"):
        shutil.copytree(ROOT / top, d / top, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / ".gitignore", d / ".gitignore")

    def git(*a):
        return subprocess.run([*GIT, "-C", str(d), *a], capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    eng = d / "warrant" / "engine.py"
    old = 'b["item"] == index and sorted(b["evidence"]) == want:'
    src = eng.read_text()
    assert src.count(old) == 1, "M05's statement moved"
    eng.write_text(src.replace(old, old + "      # touched"))
    # The record removed at head is a roadmap obligation's duty (G11's query surface): Codex's challenge
    # ed4a4e636842 found impact dropping the goal such a duty answered.
    gone = d / ".warrant" / "store" / "records" / f"{REMOVED}.json"
    keep = gone.read_bytes()
    git("rm", "-q", str(gone.relative_to(d)))
    git("commit", "-q", "-am", "head")
    head = git("rev-parse", "HEAD")
    gone.write_bytes(keep)
    return d, base, head, gone.name[:-5]


def range_cases():
    d, base, head, rid = fixture_repo()
    try:
        lens_cases(d)
        provenance_cases(d, base, head)
        im = GT.impact(d, base, head)
        stm = [s for s in im["statements"] if "M05" in s["mutants"]]
        claims = {c["claim"] for s in stm for c in s["claims"]}
        got = {x["name"] for x in im["claims"] if "statement" in x["via"]}
        removed = [x for x in im["obligations"] if x["duty"] == rid]
        check("Z18", stm and stm[0]["file"] == "warrant/engine.py" and claims and claims <= got
              and im["records"]["removed"] == [rid] and im["head"] == head
              and removed and removed[0]["name"] == "G11" and "G11" in im["goals"],
              "graph.py impact BASE..HEAD: a changed statement names the claims BACKED by a mutant changing it "
              "(statement), then what names them and what they answer; a removed obligation's duty is still the "
              "obligation of its goal, and that goal is named", (stm[:1], sorted(got)[:5], im["records"], im["goals"]))
        rc, out, err = tool("delta", f"{base}..{head}", "--json", root=d)
        rc2, out2, _ = tool("delta", f"{base}..", "--json", root=d)
        # A record that another one names stays a node of the head's graph, as `missing`.
        def gone(doc):
            return [x["node"]["id"] for x in doc["nodes"] if x["change"] == "removed"
                    or (x["change"] == "changed" and x["node"]["kind"] == "missing")]
        removed = gone(json.loads(out)) if rc == 0 else None
        live = gone(json.loads(out2)) if rc2 == 0 else None
        check("Z19", removed is not None and rid in removed and live is not None and rid not in live,
              "graph.py delta reads a range's stores from the commits' Git objects (the record deleted at head is "
              "removed), and `BASE..` from the working tree (where it still is)", (rc, err[-300:], removed, live))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    repository_cases()
    revision_cases()
    range_cases()
    return finish("GRAPH-TOOLS")


if __name__ == "__main__":
    sys.exit(main())
