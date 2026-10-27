#!/usr/bin/env python3
"""warrant_agent (warrant-agent/3): each operation, its refusals, the Warrant 2 configuration it still
reads, `warrant-agent-mcp init`, and the stdio MCP server when the SDK is installed.

    python3 tests/agent_test.py
"""
import asyncio
import json
import os
import shutil
import sys

from world import KEYS, Repo, check, finish

from warrant import engine as E
from warrant import records as R
from warrant.store import LIMITS
from warrant_agent import api
from warrant_agent import errors as ER
from warrant_agent import glossary as GL
from warrant_agent import init as I
from warrant_agent.config import Config


def cfg_of(repo, actor="bob", seed=None, **ws):
    seed = seed or repo.seed(actor)
    return Config({"agent_api": "warrant-agent/3",
                   "workspaces": {"w": dict({"repo": str(repo.root), "signer": {"actor": actor, "key": str(seed)}}, **ws)}})


def ok(out):
    return out.get("ok") or {}


def err(out):
    return out.get("error")


def operations():
    repo = Repo()
    obl = repo.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    done = repo.entity("alice", "obligation@1", {"state": "done", "statement": "s", "serves": []}, lineage=obl)
    cfg = cfg_of(repo)
    w = ok(api.call(cfg, "workspace", {}))["workspaces"][0]
    check("A01 workspace names the signer, its roles and the schemas this receiver counts",
          w["signer"] == "bob" and "roadmap/acceptor" in w["roles"] and "obligation@1" in w["schemas"], w)
    c = ok(api.call(cfg, "context", {"workspace": "w", "targets": [done[:10]]}))
    cap = c.get("targets", {}).get(done, {})
    check("A02 context: a pending closure, and the acceptor's frontier lists it",
          cap.get("guard", {}).get("guard") == "PENDING" and cap.get("lineage", {}).get("state") == "open"
          and [a["version"] for a in (c.get("frontier") or {}).get("attest", [])] == [done], c)
    p = ok(api.call(cfg, "prepare", {"workspace": "w", "kind": "attest", "target": done, "body": {"verdict": "accept"}}))
    out = api.call(cfg, "commit", {"workspace": "w", "record": p.get("record")})
    filed = ok(out).get("filed", {})
    rep = repo.report()
    check("A03 prepare and commit an acceptance: signed by the signer, the closure becomes effective",
          rep["lineages"][obl]["state"] == "done" and filed.get("actor") == "bob" and filed.get("basis") == "SIGNED", out)
    alien = R.record("attest", "eve", repo.t + 50, {"verdict": "accept", "target": done}, refs=[done])
    check("A04 commit refuses a record of another actor", err(api.call(cfg, "commit", {"workspace": "w", "record": alien})) == "NOT_PERMITTED")
    p1 = ok(api.call(cfg, "prepare", {"workspace": "w", "kind": "attest", "target": obl, "body": {"verdict": "seen"}}))
    p2 = ok(api.call(cfg, "prepare", {"workspace": "w", "kind": "attest", "target": obl, "body": {"verdict": "seen again"}}))
    first = api.call(cfg, "commit", {"workspace": "w", "record": p1.get("record")})
    second = api.call(cfg, "commit", {"workspace": "w", "record": p2.get("record")})
    check("A05 commit is a compare-and-swap on the signer's head: a stale prepare is CHAIN_MOVED",
          "ok" in first and err(second) == "CHAIN_MOVED", (first, second))
    bad = api.call(cfg, "prepare", {"workspace": "w", "kind": "entity", "schema": "obligation@1",
                                    "body": {"state": "open", "statement": 7, "serves": []}})
    check("A06 prepare refuses a body that does not fit its schema", err(bad) == "INVALID_RECORD", bad)
    succ = api.call(cfg, "prepare", {"workspace": "w", "kind": "entity", "schema": "obligation@1", "lineage": done,
                                     "body": {"state": "open", "statement": "taken over", "serves": []}})
    check("A07 prepare refuses a successor the lineage rule excludes (not the root's actor)",
          err(succ) == "INVALID_RECORD" and "LINEAGE_NOT_AUTHOR" in succ.get("message", ""), succ)
    wrong = repo.home / "keys" / "wrong.seed"
    wrong.write_text(KEYS["eve"].seed_hex())
    cfg_w = cfg_of(repo, seed=wrong)
    p = ok(api.call(cfg_w, "prepare", {"workspace": "w", "kind": "attest", "target": obl, "body": {"verdict": "x"}}))
    check("A08 commit refuses a seed whose key the trust does not bind to the signer",
          err(api.call(cfg_w, "commit", {"workspace": "w", "record": p.get("record")})) == "SIGNER_NOT_TRUSTED")
    small = cfg_of(repo, limits={"store_bytes": 100, "context_bytes": 65536, "read_bytes": 4096})
    check("A09 a store beyond the workspace's bound is refused before it is read",
          err(api.call(small, "context", {"workspace": "w"})) == "RESOURCE_LIMIT")
    v2 = Config({"agent_api": "warrant-agent/1", "state": str(repo.home / "state"), "workspaces": {"w": {
        "store": str(repo.dot / "store"), "trust": {"bindings": "x", "roles": "y"}, "profile": "p",
        "signer": {"actor": "bob", "key": str(repo.seed("bob"))}, "operations": ["context", "read", "prepare", "commit", "compute"]}}})
    p = ok(api.call(v2, "prepare", {"workspace": "w", "kind": "attest", "target": obl, "body": {"verdict": "v2 config"}}))
    check("A10 a configuration Warrant 2's init wrote is read as its repository, with its signer",
          v2.workspaces["w"].repo == repo.root and "ok" in api.call(v2, "commit", {"workspace": "w", "record": p.get("record")}))
    ro = cfg_of(repo, operations=["context"])
    check("A11 an operation the operator did not permit is refused",
          err(api.call(ro, "prepare", {"workspace": "w", "kind": "attest", "target": obl, "body": {}})) == "NOT_PERMITTED")
    check("A12 an unknown or ambiguous target is NOT_FOUND", err(api.call(cfg, "read", {"workspace": "w", "target": "0" * 12})) == "NOT_FOUND")
    exp = ok(api.call(cfg, "handoff", {"workspace": "w", "op": "export", "targets": [obl]}))
    other = Repo()
    cfg_o = cfg_of(other)
    ins = ok(api.call(cfg_o, "handoff", {"workspace": "w", "op": "inspect", "package": exp.get("package"), "alone": True}))
    imp = ok(api.call(cfg_o, "handoff", {"workspace": "w", "op": "import", "package": exp.get("package")}))
    again = ok(api.call(cfg_o, "handoff", {"workspace": "w", "op": "import", "package": exp.get("package")}))
    check("A13 handoff: a package carries a lineage and the verdicts on it; inspected alone it reads as at home; import is add-only",
          ins.get("roots", {}).get(obl, {}).get("lineage", {}).get("state") == "done" and imp.get("added", 0) > 0
          and again.get("added") == 0, (ins, imp, again))
    src = Repo()                  # Codex AMEND 1 on #220: a challenge counted by a replay travels with that replay
    o = src.entity("alice", "obligation@1", {"state": "open", "statement": "task", "serves": []})
    d = src.entity("alice", "obligation@1", {"state": "done", "statement": "task", "serves": []}, lineage=o)
    src.attest("bob", d)
    c = src.put("eve", "challenge", {"target": d, "statement": "reproduced counterexample"}, refs=[d])
    rp = src.put("carol", "attest", {"target": c, "verdict": "reproduces", "on": d}, refs=[c, d])
    pkg = ok(api.call(cfg_of(src), "handoff", {"workspace": "w", "op": "export", "targets": [o]})).get("package", {})
    insp = Repo()
    alone = ok(api.call(cfg_of(insp), "handoff", {"workspace": "w", "op": "inspect", "package": pkg, "alone": True}))
    dst = Repo()
    api.call(cfg_of(dst), "handoff", {"workspace": "w", "op": "import", "package": pkg})
    without = Repo()
    api.call(cfg_of(without), "handoff", {"workspace": "w", "op": "import", "package": dict(
        pkg, lines=[x for x in pkg.get("lines", []) if json.loads(x)["record"]["actor"] != "carol"])})
    check("A17 a package carries the verdicts on its verdicts: a challenge a replayer reproduced stays CHALLENGED inspected "
          "alone and imported; the package without that one replay reads ELIGIBLE",
          src.report()["lineages"][o]["reliance"] == "CHALLENGED"
          and alone.get("roots", {}).get(o, {}).get("lineage", {}).get("reliance") == "CHALLENGED"
          and dst.report()["lineages"][o]["reliance"] == "CHALLENGED" and rp in dst.store.snapshot().lines
          and without.report()["lineages"][o]["reliance"] == "ELIGIBLE",
          (alone.get("roots"), dst.report()["lineages"][o]["reliance"]))
    words = set(E.GUARDS) | set(E.RELIANCE) | set(E.BASES) | set(E.PROBLEMS) | set(E.REJECTIONS) | set(ER.CODES) | {"OK", "UNATTESTED"}
    check("A14 the glossary has an entry for every word the engine and the interface answer with", words <= set(GL.TERMS),
          sorted(words - set(GL.TERMS)))
    g1 = ok(api.call(cfg, "graph", {"workspace": "w", "op": "path", "target": done}))
    g2 = ok(api.call(cfg, "graph", {"workspace": "w", "op": "path", "target": done}))
    repo.profile["roles"]["claim/verifier"] = ["dave"]
    repo.write_config()
    g3 = ok(api.call(cfg, "graph", {"workspace": "w", "op": "path", "target": done}))
    check("A15 a graph result carries root and lens: the same query gives the same lens; another profile another",
          g1.get("lens") == g2.get("lens") and g1.get("lens") != g3.get("lens") and g1.get("root") == g3.get("root")
          and obl in [n["id"] for n in g1.get("data", {}).get("nodes", [])], (g1.get("lens"), g3.get("lens")))
    deep = Repo()
    prev = None
    for n in range(LIMITS["requires"] + 20):
        prev = deep.entity("alice", "obligation@1", {"state": "done", "statement": f"o{n}", "serves": []},
                           requires=[prev] if prev else [])
    check("A16 requires nested beyond the engine's limit: RESOURCE_LIMIT, never a crash",
          err(api.call(cfg_of(deep), "context", {"workspace": "w"})) == "RESOURCE_LIMIT")


def init_cases():
    repo = Repo()
    I.ROOTS = (repo.home,)
    seed = repo.seed("bob")
    out = repo.home / "cfg" / "bob.json"
    s = I.init(repo.root, "bob", seed, out)
    cfg = Config.load(out)
    check("I01 init writes a configuration that loads, with the existing seed as signer",
          cfg.workspaces[s["workspace"]].signer == ("bob", seed), s)

    def refused(code, **kw):
        args = dict(repo=repo.root, actor="bob", seed=seed, config=repo.home / "cfg" / "x.json")
        args.update(kw)
        try:
            I.init(**args)
            return False
        except I.Refused as e:
            return e.code == code
    check("I02 a seed whose key the repository does not bind to the actor is refused",
          refused("INIT_KEY_NOT_PINNED", seed=repo.seed("eve")))
    inside = repo.root / "k.seed"
    shutil.copy(seed, inside)
    check("I03 a seed inside the repository is refused", refused("INIT_INSIDE_REPOSITORY", seed=inside))
    check("I04 an existing configuration needs --force", refused("INIT_CONFIG_EXISTS", config=out))
    stranger = repo.home / "cfg" / "notes.json"
    stranger.write_text("{}")
    check("I05 --force replaces only a configuration init wrote", refused("INIT_NOT_INIT_OUTPUT", config=stranger, force=True))
    old = repo.home / "cfg" / "old.json"
    old.write_text(json.dumps({"agent_api": "warrant-agent/1", "state": "s", "workspaces": {"repo": {
        "store": str(repo.root / ".warrant" / "store"), "signer": {"actor": "bob", "key": str(seed)}}}}))
    try:
        I.init(repo.root, "bob", seed, old, force=True)
        replaced = json.loads(old.read_text())["agent_api"] == "warrant-agent/3"
    except I.Refused:
        replaced = False
    check("I06 --force replaces Warrant 2's init output for the same repository", replaced)
    (repo.home / "real").mkdir()
    os.symlink(repo.home / "real", repo.home / "link")
    check("I07 a symlink on the configuration's path is refused", refused("INIT_SYMLINK", config=repo.home / "link" / "c.json"))
    check("I08 a path outside the operator's home is refused", refused("INIT_OUTSIDE_HOME", config="/" + "c.json"))
    check("I09 an actor the repository binds no key to is refused", refused("INIT_ACTOR_NOT_PINNED", actor="zed"))


def mcp_cases():
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("skip M01 (the MCP SDK is not installed)")
        return
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    repo = Repo()
    obl = repo.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    path = repo.home / "cfg.json"
    path.write_text(json.dumps({"agent_api": "warrant-agent/3", "workspaces": {"w": {
        "repo": str(repo.root), "signer": {"actor": "bob", "key": str(repo.seed("bob"))}}}}))

    async def run():
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
        params = StdioServerParameters(command=sys.executable, args=["-m", "warrant_agent.mcp_server", "--config", str(path)], env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = sorted(t.name for t in (await s.list_tools()).tools)
                p = await s.call_tool("warrant_prepare", {"workspace": "w", "kind": "attest", "target": obl, "body": {"verdict": "seen"}})
                rec = (p.structured_content or {}).get("record")
                c = await s.call_tool("warrant_commit", {"workspace": "w", "record": rec})
                bad = await s.call_tool("warrant_read", {"workspace": "w", "target": "00000000"})
                return names, c, bad
    names, c, bad = asyncio.run(run())
    check("M01 stdio MCP: eight tools; prepare and commit sign as the configured signer; a refusal is a tool error with its JSON",
          names == sorted(["warrant_" + n for n in ("workspace", "context", "read", "graph", "handoff", "prepare", "commit", "explain")])
          and not c.is_error and (c.structured_content or {}).get("filed", {}).get("actor") == "bob"
          and bad.is_error and "NOT_FOUND" in bad.content[0].text, (names, c, bad))


if __name__ == "__main__":
    operations()
    init_cases()
    mcp_cases()
    sys.exit(finish())
