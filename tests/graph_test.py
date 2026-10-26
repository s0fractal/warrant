#!/usr/bin/env python3
"""The record graph by query (G11): warrant_agent/graph.py, the agent operation `graph` and its MCP tool
`warrant_graph` (Z01-Z16), and tools/graph.py over this repository and a fixture Git repository (Z17-Z23).

    python3 tests/graph_test.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_world import ROOT, R, api, check, finish, views, world
from warrant import engine as E
from warrant.keys import Key
from warrant_agent import graph as G

# tools/graph.py of the tree under test: a mutant of a tool runs from its copy in $WARRANT_IMPL/tools.
_impl = os.environ.get("WARRANT_IMPL")
TOOLS = Path(_impl) / "tools" if _impl and (Path(_impl) / "tools" / "graph.py").is_file() else ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import graph as GT                  # noqa: E402

GIT = ["git", "-c", "user.name=graph-test", "-c", "user.email=graph@invalid", "-c", "commit.gpgsign=false",
       "-c", "gc.auto=0"]


def view_of(p):
    """(graph, report, view token) of a new frozen view of party `p`'s workspace."""
    token = views.capture(p.ws)["token"]
    _, report, view = views.load(p.ws, token)
    return G.build(view.snapshot(), report), report, token


def nodes(g):
    return {n["id"]: n for n in g["nodes"]}


# ---------------------------------------------------------------- a world with goals, obligations, verdicts

def goal_world():
    src, rcv = world()
    v1 = src.file("transition", "producer", 90, R.transition("ATTESTED", opened=[{"text": "A goal.", "scope": "roadmap:G1"}],
                                                              established=["vision"]))
    q1 = f"{v1}:0"
    ev = src.blob(b"candidate(-2) returns 2\n")
    d = src.file("duty", "producer", 100, R.duty("producer", 'abs(-2) == 2, say "hi"; } digraph x {', ["reviewer"],
                                                 {"attest": {}}, accept_by=["reviewer"]))
    t = src.file("transition", "producer", 110, R.transition("ATTESTED", [ev], closes=[R.item(d, "discharge", [ev])],
                                                             established=["abs is implemented"]))
    o1 = src.file("duty", "producer", 111, R.duty("producer", "First obligation.", ["reviewer"], {"attest": {}},
                                                  accept_by=["reviewer"], requires=[d], answers=q1))
    o2 = src.file("duty", "producer", 112, R.duty("producer", "Second obligation.", ["reviewer"], {"attest": {}},
                                                  accept_by=["reviewer"], requires=[o1], answers=q1))
    v2 = src.file("transition", "producer", 113, R.transition("ATTESTED", supersedes=[v1], established=["vision 2"],
                                                               opened=[{"text": "A goal, sharper.", "scope": "roadmap:G1"}]))
    q2 = f"{v2}:0"
    o3 = src.file("duty", "producer", 114, R.duty("producer", "Third obligation.", ["reviewer"], {"attest": {}},
                                                  accept_by=["reviewer"], answers=q2))
    o4 = src.file("duty", "producer", 115, R.duty("producer", "Serves a duty nobody filed.", ["reviewer"], {"attest": {}},
                                                  accept_by=["reviewer"], serves=["f" * 64]))
    o5 = src.file("duty", "producer", 116, R.duty("producer", "Serves the first duty.", ["reviewer"], {"attest": {}},
                                                  accept_by=["reviewer"], serves=[d]))
    # A record signed by a key the trust does not bind to its actor: the report lists it invalid.
    bad = src.store.put_record(R.record("duty", "producer", 117, R.duty("producer", "Forged.", ["reviewer"], {"attest": {}}, accept_by=["reviewer"])),
                               Key.generate())
    g0, rep0, tok0 = view_of(src)
    a = src.file("accept", "reviewer", 120, R.accept(t, 0, [ev]))
    g1, rep1, tok1 = view_of(src)
    return dict(src=src, rcv=rcv, q1=q1, q2=q2, d=d, t=t, ev=ev, o1=o1, o2=o2, o3=o3, o4=o4, o5=o5, bad=bad, a=a,
                g0=g0, rep0=rep0, tok0=tok0, g1=g1, rep1=rep1, tok1=tok1)


def engine_cases(w):
    g, rep = w["g1"], w["rep1"]
    ns = nodes(g)
    check("Z01", w["bad"] in rep["invalid_records"] and w["bad"] not in ns
          and all(e["from"] != w["bad"] and e["to"] != w["bad"] for e in g["edges"]),
          "a record the report lists invalid is no node of the graph, and no edge starts or ends at it", w["bad"] in ns)
    closes = [e for e in g["edges"] if e["from"] == w["t"] and e["rel"] == "closes"]
    cand = [c["verdict"] for c in rep["duties"][w["d"]]["candidates"] if c["transition"] == w["t"]]
    check("Z02", [e["verdict"] for e in closes] == cand == ["ADMITTED"]
          and ns[w["d"]]["state"] == rep["duties"][w["d"]]["disposition"] == "DISCHARGED",
          "a closes edge carries the report's verdict of that item and a duty node the report's disposition: shown, "
          "never recomputed", (closes, ns[w["d"]]))
    ends = {x for e in g["edges"] for x in (e["from"], e["to"])}
    check("Z03", ends <= set(ns) and ns.get("f" * 64, {}).get("kind") == "missing" and ns[w["ev"]]["kind"] == "blob"
          and ns[w["q1"]]["kind"] == "question" and ns[w["q1"]]["scope"] == "roadmap:G1",
          "every edge ends at a node: a cited blob is a blob node, an opened question a question node, an id the "
          "snapshot lacks a missing node", sorted(ends - set(ns))[:3])

    p = G.path(g, w["o2"])
    order = [x["duty"] for x in p["duties"]]
    check("Z04", order == [w["d"], w["o1"], w["o2"]] and [x["root"] for x in p["duties"]] == [False, False, True],
          "path to a duty lists every duty it requires, transitively, each once, a duty after its prerequisites", order)
    ps, pq = G.path(g, "roadmap:G1"), G.path(g, w["q1"])
    check("Z05", ps["kind"] == "scope" and [q["question"] for q in ps["questions"]] == sorted([w["q1"], w["q2"]])
          and {x["duty"] for x in ps["duties"] if x["root"]} == {w["o1"], w["o2"], w["o3"]}
          and pq["kind"] == "question" and {x["duty"] for x in pq["duties"] if x["root"]} == {w["o1"], w["o2"]},
          "path to a question scope reads every question of that scope (a reformulated goal's too) and the duties "
          "answering any of them; to a question reference, that question's only", (ps["questions"], ps["open"]))
    try:
        G.path(g, w["o2"][:7])
        short = "resolved"
    except G.Unknown as e:
        short = str(e)
    check("Z06", G.path(g, w["o2"][:8])["duties"][-1]["duty"] == w["o2"] and short != "resolved",
          "a duty is named by its id or a unique prefix of at least 8 hex digits; a shorter one names nothing", short)
    fr = op(w["src"], {"op": "frontier", "view_token": w["tok1"]}).get("ok", {}).get("data", {})
    other = op(w["src"], {"op": "frontier", "actor": "reviewer", "view_token": w["tok1"]}).get("ok", {}).get("data", {})
    want = E.frontier(rep, "producer")
    check("Z07", len(want) == 5 and [{k: v for k, v in x.items() if k != "section"} for x in fr.get("items", [])] == want
          and fr.get("summary") == {"actor": "producer", "open": 5} and G.frontier(rep, "producer") == want
          and other.get("summary") == {"actor": "reviewer", "open": len(E.frontier(rep, "reviewer"))},
          "frontier is the engine's frontier, for the configured signer's actor unless the request names another, "
          "as context's is", (fr.get("summary"), other.get("summary")))
    d = G.delta(w["g0"], g)
    added = [x["node"]["id"] for x in d["nodes"] if x["change"] == "added"]
    changed = {x["node"]["id"]: x["was"] for x in d["nodes"] if x["change"] == "changed"}
    vchg = [x for x in d["edges"] if x["change"] == "changed" and x["edge"]["from"] == w["t"]]
    check("Z08", added == [w["a"]] and changed.get(w["d"]) == {"state": "OPEN"} and len(vchg) == 1
          and vchg[0]["was"] == {"verdict": "PENDING"} and vchg[0]["edge"]["verdict"] == "ADMITTED",
          "delta from the view before an acceptance to the one after: the accept added, the duty changed from OPEN, "
          "the closes edge's verdict changed from PENDING", (added, changed, vchg))
    im = G.impact(w["g0"], g)
    via = {x["duty"]: x["via"] for x in im["duties"]}
    check("Z09", im["records"]["added"] == [w["a"]] and via.get(w["d"]) == ["record"] and via.get(w["o1"]) == ["requires"]
          and via.get(w["o2"]) == ["requires"] and w["o5"] not in via and w["o3"] not in via
          and [q["question"] for q in im["questions"]] == [w["q1"]],
          "impact of an added accept: the duty its transition closes (record), the duties requiring that one, "
          "transitively (requires), the question they answer; a duty that only serves it is not reached", via)
    im2 = G.impact(g, g, {w["d"]: "statement"})
    via2 = {x["duty"]: x["via"] for x in im2["duties"]}
    check("Z10", via2.get(w["d"]) == ["statement"] and via2.get(w["o5"]) == ["named"]
          and via2.get(w["o1"]) == ["named", "requires"] and im2["records"] == {"added": [], "removed": []},
          "impact of a named duty (a claim whose mutant changes a changed statement): the duties naming it "
          "(serves or requires, as claims.py why reads them), then their dependants", via2)
    text = G.dot(g)
    lines = text.splitlines()
    check("Z11", len(lines) == len(g["nodes"]) + len(g["edges"]) + 3 and 'say \\"hi\\"; } digraph x {' in text
          and lines[0] == "digraph warrant {" and lines[-1] == "}",
          "dot: one line per node and per edge, every string quoted and escaped, so a label cannot end its string "
          "or add a statement", [ln for ln in lines if "digraph x" in ln][:1])
    _, again, view = views.load(w["src"].ws, w["tok1"])
    check("Z12", json.dumps(G.build(view.snapshot(), again), sort_keys=True) == json.dumps(g, sort_keys=True)
          and [e["from"] for e in g["edges"]] == sorted(e["from"] for e in g["edges"])
          and [n["id"] for n in g["nodes"]] == sorted(n["id"] for n in g["nodes"]),
          "the graph of one view is the same document each time it is built, nodes by id, edges by origin")


# ---------------------------------------------------------------- the agent operation and its MCP tool

def op(p, req):
    return api.call(p.cfg, "graph", dict(req, workspace=p.name))


def agent_cases(w):
    src = w["src"]
    got = op(src, {"op": "path", "target": "roadmap:G1", "view_token": w["tok1"]})
    data = got.get("ok", {}).get("data", {})
    want = G.path(w["g1"], "roadmap:G1")
    src.doc["workspaces"][src.name]["operations"] = ["context"]
    src.reload()
    denied = op(src, {"op": "path", "target": "roadmap:G1", "view_token": w["tok1"]})
    del src.doc["workspaces"][src.name]["operations"]
    src.reload()
    check("Z13", [x["duty"] for x in data.get("items", []) if x["section"] == "duty"] == [x["duty"] for x in want["duties"]]
          and data.get("summary") == {"target": "roadmap:G1", "kind": "scope", "open": want["open"]}
          and data.get("untrusted_data") is True and got["ok"]["view_token"] == w["tok1"]
          and denied.get("error") == "NOT_PERMITTED",
          "the operation graph answers from the named view what graph.py answers, and is refused where read is "
          "not permitted", (got.get("error"), denied))

    pages, cur = [], None
    while True:
        r = op(src, dict({"op": "export", "view_token": w["tok1"], "max_bytes": 512}, **({"cursor": cur} if cur else {})))
        if "ok" not in r:
            pages.append(r)
            break
        pages.append(r["ok"])
        cur = r["ok"]["page"]["cursor"]
        if cur is None:
            break
    items = [x for p in pages if "data" in p for x in p["data"]["items"]]
    whole = [dict(n, section="node") for n in w["g1"]["nodes"]] + [dict(e, section="edge") for e in w["g1"]["edges"]]
    first = op(src, {"op": "path", "target": "roadmap:G1", "view_token": w["tok1"], "max_bytes": 256})
    other = op(src, {"op": "path", "target": w["q1"], "view_token": w["tok1"],
                     "cursor": first.get("ok", {}).get("page", {}).get("cursor")})
    check("Z14", len(pages) > 2 and items == whole and pages[0]["page"]["truncated"] is True
          and first.get("ok", {}).get("page", {}).get("cursor") and other.get("error") == "CURSOR_MISMATCH",
          "a graph result pages by bytes and the cursors give the whole of it once; a cursor of one request is "
          "refused for another (CURSOR_MISMATCH)", (len(pages), other))

    dl = op(src, {"op": "delta", "base_view_token": w["tok0"], "view_token": w["tok1"]})
    dd = G.delta(w["g0"], w["g1"])
    im = op(src, {"op": "impact", "base_view_token": w["tok0"], "view_token": w["tok1"]})
    check("Z15", dl.get("ok", {}).get("data", {}).get("summary", {}).get("added") == dd["counts"]["added"] == 1
          and [x["node"]["id"] for x in dl["ok"]["data"]["items"] if x["section"] == "node" and x["change"] == "added"] == [w["a"]]
          and im.get("ok", {}).get("data", {}).get("summary", {}).get("records_added") == 1,
          "delta and impact read their base from base_view_token and the head from view_token", (dl.get("error"), dd["counts"]))

    if importlib.util.find_spec("mcp") is None:
        check("Z16", False, "the MCP SDK is installed (pip install 'warrant-graph[mcp]')")
        return
    from agent_mcp_test import tool_calls, two_workspace_config
    cfg = two_workspace_config(src, w["rcv"])
    r = tool_calls(cfg, [("warrant_graph", {"op": "export", "workspace": "src", "format": "dot", "max_bytes": 1 << 20}),
                         ("warrant_graph", {"op": "path", "workspace": "src", "target": "roadmap:G1"})])
    dot = r[0].get("ok", {}).get("data", {})
    lines = [x.get("line") for x in dot.get("items", [])]      # .get: a JSON export instead fails the check, not the case
    path = r[1].get("ok", {}).get("data", {})
    check("Z16", lines == G.dot(w["g1"]).splitlines() and dot.get("summary", {}).get("format") == "dot"
          and path.get("summary", {}).get("kind") == "scope",
          "the MCP tool warrant_graph passes its arguments to the same backend: export as dot, path to a scope", r)


# ---------------------------------------------------------------- tools/graph.py

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
    check("Z21", rc == 0 and out == rcw.stdout and json.loads(out)["file"] == "warrant/engine.py",
          "graph.py why is tools/claims.py why", (rc, err[-300:]))

    rc, out, err = tool("frontier", "--actor", "codex", "--json")
    fr = json.loads(out)["frontier"] if rc == 0 else None
    rc2, dot, _ = tool("export", "--dot")
    rc3, js, _ = tool("export", "--json")
    g = json.loads(js) if rc3 == 0 else {}
    check("Z22", rc == 0 and isinstance(fr, list) and all("need" in x for x in fr) and rc2 == 0
          and dot.startswith("digraph warrant {") and dot.count("\n") == len(g.get("nodes", [])) + len(g.get("edges", [])) + 3
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
    gone = sorted((d / ".warrant" / "store" / "records").iterdir())[-1]
    keep = gone.read_bytes()
    git("rm", "-q", str(gone.relative_to(d)))
    git("commit", "-q", "-am", "head")
    head = git("rev-parse", "HEAD")
    gone.write_bytes(keep)
    return d, base, head, gone.name[:-5]


def range_cases():
    d, base, head, rid = fixture_repo()
    try:
        im = GT.impact(d, base, head)
        stm = [s for s in im["statements"] if "M05" in s["mutants"]]
        claims = {c["claim"] for s in stm for c in s["claims"]}
        got = {x["name"] for x in im["claims"] if "statement" in x["via"]}
        check("Z18", stm and stm[0]["file"] == "warrant/engine.py" and claims and claims <= got
              and im["records"]["removed"] == [rid] and im["head"] == head,
              "graph.py impact BASE..HEAD: a changed statement names the claims BACKED by a mutant changing it "
              "(statement), then what names them and what they answer; a removed record what it was about",
              (stm[:1], sorted(got)[:5], im["records"]))
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
    w = goal_world()
    engine_cases(w)
    agent_cases(w)
    repository_cases()
    revision_cases()
    range_cases()
    return finish("GRAPH")


if __name__ == "__main__":
    sys.exit(main())
