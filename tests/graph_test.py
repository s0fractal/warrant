#!/usr/bin/env python3
"""The record graph by query (G11): warrant_agent/graph.py and the agent operation `graph` with its MCP tool
`warrant_graph` (Z01-Z16); Codex's findings on head 2 (Z24-Z26); root and lens of the operation (Z28) and Codex's
findings on head 5 (Z29, Z30); Codex's challenge of a G11 closure (Z34). tools/graph.py is graph_tools_test.py's (Z17-Z23, Z27, Z31-Z33).

    python3 tests/graph_test.py
"""
import importlib.util
import json
import sys

from agent_world import C, Key, R, api, check, finish, views, world
from graph_tools_test import GT, ROOT, TOOLS, fixture_repo, tool
from warrant import engine as E
from warrant.store import Trust
from warrant_agent import graph as G

# Codex's finding tests on #209 import these from graph_test, where they lived before the split.
REEXPORTED = (GT, ROOT, TOOLS, fixture_repo, tool)


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

def finding_cases():
    """Codex's findings on #209 head 2 (9052c7f): 51541256eeb7, 0ad3ed6d54a1, 3456ece28888."""
    from contract_test import _chain
    src, _ = world()
    src.file("duty", "producer", 100, R.duty("producer", "one", ["reviewer"], {"attest": {}}, accept_by=["reviewer"]))
    src.file("transition", "producer", 101, R.transition("ATTESTED", established=["two"]))
    req = {"workspace": src.name, "op": "export", "max_bytes": 256}
    first = api.call(src.cfg, "graph", req).get("ok", {})
    nxt = api.call(src.cfg, "graph", dict(req, view_token=first.get("view_token"), cursor=first.get("page", {}).get("cursor")))
    check("Z24", bool(first.get("page", {}).get("cursor")) and nxt.get("ok", {}).get("page", {}).get("offset")
          == first["page"]["included"],
          "a graph result read without view_token is continued with the view_token and cursor it returned (the "
          "cursor names the view; the request's other members bind it)", nxt.get("error"))

    snap, trust, as_of, ids = _chain(1200)
    report = E.assess(snap, trust, as_of, E.profile())
    g = G.build(snap, report)
    try:
        deep, err = [x["duty"] for x in G.path(g, ids[-1])["duties"]], None
        about = G.impact(g, g, {ids[0]: "statement"})["duties"]
    except RecursionError as e:
        deep, about, err = [], [], type(e).__name__
    check("Z25", len(report["duties"]) == 1200 and deep == ids and len(about) == 1200,
          "path and impact answer an admitted chain of 1200 duties (no recursion), prerequisites first", err)

    got = []
    for name in ("graph", "handoff", "compute"):
        for bad in ([], {}, ["path"]):
            try:
                got.append(api.call(src.cfg, name, {"workspace": src.name, "op": bad}).get("error"))
            except TypeError as e:          # what the finding saw: the lookup of an unhashable op escaped
                got.append(type(e).__name__)
    check("Z26", got == ["BAD_REQUEST"] * 9,
          "an op that is not a string (a list, an object) is BAD_REQUEST in graph, handoff and compute, never an "
          "exception escaping the interface", got)


def agent_lens_cases(w):
    src = w["src"]
    req = {"op": "path", "target": "roadmap:G1", "view_token": w["tok1"]}
    a1 = op(src, req).get("ok", {}).get("data", {})
    a2 = op(src, req).get("ok", {}).get("data", {})
    q2 = op(src, dict(req, target=w["q1"])).get("ok", {}).get("data", {})
    real = api.adapter_id
    try:
        api.adapter_id = lambda: "0" * 64          # another agent package
        moved = op(src, req).get("ok", {}).get("data", {})
    finally:
        api.adapter_id = real
    dl = op(src, {"op": "delta", "base_view_token": w["tok0"], "view_token": w["tok1"]}).get("ok", {}).get("data", {})
    check("Z28", a1.get("lens") and a1["lens"] == a2.get("lens") and a1["lens"] != q2.get("lens")
          and a1["lens"] != moved.get("lens") and a1.get("root") == {"snapshot": w["rep1"]["view"]["snapshot"],
                                                                     "as_of": w["rep1"]["view"]["as_of"]}
          and dl.get("root", {}).get("base", {}).get("snapshot") == w["rep0"]["view"]["snapshot"],
          "the operation graph's results carry root (the view's snapshot and time; a base view's too) and lens (the "
          "agent's and the engine's code, the view's trust and profile, the query): another agent package or another "
          "target changes the lens, the same request does not", (a1.get("root"), a1.get("lens")))


def identity_finding_cases(w):
    """Codex's findings on head 5 (24d5d32): 5af55ace3344 and 74a162414cb8. Two results that differ must not share
    (root, lens)."""
    src = w["src"]
    req = {"op": "frontier", "view_token": w["tok1"]}
    first = op(src, req).get("ok", {}).get("data", {})
    key = src.base / "reviewer.key"
    key.write_text(src.keys["reviewer"].seed_hex())
    signer = src.doc["workspaces"][src.name]["signer"]
    try:
        src.doc["workspaces"][src.name]["signer"] = {"actor": "reviewer", "key": str(key)}
        src.reload()
        second = op(src, req).get("ok", {}).get("data", {})
    finally:
        src.doc["workspaces"][src.name]["signer"] = signer
        src.reload()
    check("Z29", first.get("items") != second.get("items")
          and (first.get("root"), first.get("lens")) != (second.get("root"), second.get("lens")),
          "frontier with no actor reads the configured signer's: two signers' frontiers of one view differ in lens (the "
          "query is hashed with its defaults resolved)", (first.get("lens"), second.get("lens")))

    path = src.base / "trust.json"
    keep = path.read_bytes()
    try:
        other = Key.generate()
        path.write_bytes(C.canon(Trust.document([(a, other.public if a == "reviewer" else k.public)
                                                for a, k in src.keys.items()])))
        base = views.capture(src.ws, as_of=w["rep1"]["view"]["as_of"])["token"]
    finally:
        path.write_bytes(keep)
    one = op(src, {"op": "delta", "view_token": w["tok1"], "base_view_token": w["tok1"]}).get("ok", {}).get("data", {})
    two = op(src, {"op": "delta", "view_token": w["tok1"], "base_view_token": base}).get("ok", {}).get("data", {})
    check("Z30", one.get("items") == [] and two.get("items") and one.get("root") == two.get("root")
          and one.get("lens") != two.get("lens"),
          "delta and impact hash every assessment operand of the base view too (its trust): two bases of one snapshot "
          "and time under other pins differ in lens", (one.get("lens"), two.get("lens")))


def removal_cases(w):
    """Codex's challenge ed4a4e636842 (of G11 closure 1faff6c83d6a): a duty removed in the range answered a question
    in the base; impact names that question."""
    from warrant.store import Snapshot
    _, rep, view = views.load(w["src"].ws, w["tok1"])
    snap = view.snapshot()
    less = Snapshot({k: v for k, v in snap.records.items() if k != w["o3"]}, dict(snap.blobs))
    rep2 = E.assess(less, Trust.load(w["src"].base / "trust.json"), rep["view"]["as_of"], rep["profile"])
    im = G.impact(w["g1"], G.build(less, rep2))
    via = {x["duty"]: x for x in im["duties"]}
    check("Z34", im["records"]["removed"] == [w["o3"]] and via.get(w["o3"], {}).get("answers") == w["q2"]
          and [q["question"] for q in im["questions"]] == [w["q2"]] and im["questions"][0]["scope"] == "roadmap:G1",
          "impact reads a removed duty's own relations in the base: the question it answered is named", im)


def main():
    w = goal_world()
    engine_cases(w)
    agent_cases(w)
    agent_lens_cases(w)
    identity_finding_cases(w)
    finding_cases()
    removal_cases(w)
    return finish("GRAPH")


if __name__ == "__main__":
    sys.exit(main())
