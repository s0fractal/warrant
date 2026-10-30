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
import threading

from world import KEYS, ROLES, Repo, check, finish

from warrant import bootstrap as B
from warrant import engine as E
from warrant import home as H
from warrant import records as R
from warrant.store import LIMITS
from warrant_agent import api
from warrant_agent import errors as ER
from warrant_agent import glossary as GL
from warrant_agent import init as I
from warrant_agent.config import Config, repository_config


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


def refusal_cases():
    """What the engine would reject, list as a problem or refuse the store for is refused at prepare and at commit
    (§13), never filed; each refused record is also committed as built by hand, past prepare. The schemas are under
    a quorum of 2, so a proposal's own rules are seen apart from the engine's (a pending schema is no problem)."""
    repo = Repo(roles=dict(ROLES, **{"schema/author": ["alice", "bob"]}))
    repo.profile["quorum"] = {"schema/author": 2}
    repo.write_config()
    for i in repo.schemas.values():
        repo.attest("bob", i)
    goal2 = repo.put("alice", "schema", dict(next(x for x in B.SCHEMAS if x["name"] == "goal@1")), lineage=repo.schemas["goal@1"])
    repo.attest("bob", goal2)
    obl = repo.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})

    def both(req, repo=repo, actor="alice"):
        cfg = cfg_of(repo, actor)
        try:
            p = api.call(cfg, "prepare", dict(req, workspace="w"))
            r = R.record(req["kind"], actor, repo.t + 100, req["body"], schema=req.get("schema"), lineage=req.get("lineage"),
                         refs=req.get("refs", ()), prev=E.head(repo.store.snapshot(), repo.trust, actor)["id"])
            c = api.call(cfg, "commit", {"workspace": "w", "record": r})
            repo.report()
        except Exception as e:                  # noqa: BLE001 - a crash after a commit is the failure seen
            return "CRASH", type(e).__name__, str(e)
        return err(p), err(c), (p.get("message") or "") + " | " + (c.get("message") or "")
    note = {"name": "note@1", "fields": {"text": "str"}, "states": None, "closed": [], "successors": {}}
    goal = next(x for x in B.SCHEMAS if x["name"] == "goal@1")
    out = {
        "body": both({"kind": "schema", "body": {"name": "half@1"}}),
        "taken": both({"kind": "schema", "body": dict(note, name="goal@1")}),
        "rename": both({"kind": "schema", "lineage": goal2, "body": dict(goal, name="goal@2")}),
        "fork": both({"kind": "schema", "lineage": repo.schemas["goal@1"], "body": dict(goal, closed=[])}),
        "stranger": both({"kind": "schema", "body": note}, actor="eve"),
        "other author": both({"kind": "schema", "lineage": goal2, "body": dict(goal, closed=[])}, actor="bob"),
    }
    lines = len(repo.store.lines())
    check("A18 a schema the engine would not count once accepted is refused at prepare and commit: a malformed body, a "
          "name counted already, a successor renaming its schema or forking it, one by an actor without schema/author, "
          "a successor by another author (6d6bb700: all filed)",
          all(x[:2] == ("INVALID_RECORD", "INVALID_RECORD") for x in out.values())
          and "schema/author" in out["stranger"][2] and "LINEAGE_NOT_AUTHOR" in out["other author"][2]
          and "SCHEMA_CONFLICT" in out["taken"][2] and "SCHEMA_CONFLICT" in out["fork"][2] and "name" in out["rename"][2]
          and len(repo.store.lines()) == lines, out)
    mig = Repo()
    lines = len(mig.store.lines())
    m = both({"kind": "entity", "schema": R.MIGRATION, "body": {"state": "open"}}, mig)
    check("A19 a record of the reserved migration@1 is refused at prepare and commit (6d6bb700: an entity of it was filed "
          "and crashed every later assessment)", m[:2] == ("INVALID_RECORD", "INVALID_RECORD") and len(mig.store.lines()) == lines, m)
    p = api.call(cfg_of(repo, "alice"), "prepare", {"workspace": "w", "kind": "schema", "body": note})
    c = api.call(cfg_of(repo, "alice"), "commit", {"workspace": "w", "record": ok(p).get("record")})
    rep = repo.report()
    check("A22 a schema proposal: a valid schema short of its quorum is filed, pending, no problem",
          "ok" in c and ok(c).get("id") in rep["schemas_pending"] and not [x for x in rep["problems"] if x[1] == ok(c).get("id")], (p, c))
    cfg = cfg_of(repo, "alice")
    big = api.call(cfg, "prepare", {"workspace": "w", "kind": "attest", "target": obl, "body": {"verdict": "seen"},
                                    "refs": [f"{n:064x}" for n in range(1100)]})
    check("A20 a record whose signed line the store would reject as too long is refused at prepare (6d6bb700: filed, "
          "then rejected by its own store)", err(big) == "INVALID_RECORD" and "65536" in big.get("message", ""), big)
    late = repo.put("alice", "entity", {"state": "open", "statement": "future", "serves": []}, "obligation@1", at=repo.t + 10**6)
    cfg_d = cfg_of(repo, "dave")
    p = api.call(cfg_d, "prepare", {"workspace": "w", "kind": "entity", "schema": "obligation@1", "lineage": late,
                                    "body": {"state": "released", "statement": "future", "serves": []}})
    back = dict(ok(p).get("record") or {}, at=repo.t + 5)
    c = api.call(cfg_d, "commit", {"workspace": "w", "record": back})
    c2 = api.call(cfg_d, "commit", {"workspace": "w", "record": ok(p).get("record")})
    probs = [x for x in repo.report()["problems"] if x[0] == "LINEAGE_BACKDATED"]
    check("A21 a successor is never dated before what it succeeds: prepare dates it after, commit refuses a backdated one "
          "(LINEAGE_BACKDATED is a problem every gate refuses)",
          "ok" in p and err(c) == "INVALID_RECORD" and "LINEAGE_BACKDATED" in c.get("message", "") and "ok" in c2 and not probs,
          (p, c, c2, probs))
    deep = Repo()
    prev = None
    for n in range(LIMITS["requires"]):
        prev = deep.entity("alice", "obligation@1", {"state": "done", "statement": f"o{n}", "serves": []}, requires=[prev] if prev else [])
    g = dict(next(x for x in B.SCHEMAS if x["name"] == "obligation@1")["states"]["done"], requires=[prev])
    req = {"workspace": "w", "kind": "entity", "schema": "obligation@1", "guard": g, "body": {"state": "done", "statement": "one more", "serves": []}}
    p = api.call(cfg_of(deep, "alice"), "prepare", req)
    hand = R.record("entity", "alice", deep.t + 1, req["body"], "obligation@1", guard=g,
                    prev=E.head(deep.store.snapshot(), deep.trust, "alice")["id"])
    c = api.call(cfg_of(deep, "alice"), "commit", {"workspace": "w", "record": hand})
    after = api.call(cfg_of(deep, "alice"), "workspace", {})
    check("A23 a record after which the engine would refuse the store (requires nested beyond its limit) is refused at "
          "prepare and commit, and the workspace stays readable (6d6bb700: filed; every later operation RESOURCE_LIMIT)",
          err(p) == "INVALID_RECORD" and err(c) == "INVALID_RECORD" and "ok" in after, (p, c, after.get("error")))


def admission_cases():
    """Codex's findings on #221 (01cb8aa7c0de / 793c5d0077af, 4c58f74e7772 / cceccf9fb81c), his tests adapted."""
    repo = Repo()
    prev = None
    for n in range(LIMITS["requires"] - 1):
        prev = repo.put("alice", "entity", {"state": "open", "statement": str(n), "serves": []}, "obligation@1",
                        guard=R.guard(requires=[prev] if prev else []))
    alice, bob = cfg_of(repo, "alice"), cfg_of(repo, "bob")
    b = ok(api.call(bob, "prepare", {"workspace": "w", "kind": "entity", "schema": "obligation@1", "guard": R.guard(requires=[prev]),
                                     "body": {"state": "open", "statement": "last permitted dependency", "serves": []}})).get("record")
    a = ok(api.call(alice, "prepare", {"workspace": "w", "kind": "entity", "schema": "obligation@1", "guard": R.guard(requires=[R.rid(b)]),
                                       "body": {"state": "open", "statement": "concurrent dependent", "serves": []}})).get("record")
    # Each is admissible alone on this store: B takes it to depth 128, A requires B (not filed yet); both, 129.
    start, finished, results, original = threading.Event(), threading.Event(), {}, api._refusals

    def interleave(snap, view, trust, profile, record):
        why = original(snap, view, trust, profile, record)
        if record == a and not why and not start.is_set():
            start.set()
            finished.wait(2)            # if alice's admission holds the writers' lock, bob waits for it
        return why

    def other_writer():
        if start.wait(5):
            results["bob"] = api.call(bob, "commit", {"workspace": "w", "record": b})
        finished.set()
    api._refusals = interleave
    thread = threading.Thread(target=other_writer, daemon=True)
    thread.start()
    try:
        results["alice"] = api.call(alice, "commit", {"workspace": "w", "record": a})
    finally:
        api._refusals = original
    thread.join(5)
    after = api.call(alice, "workspace", {})
    lines = repo.store.snapshot().lines
    check("A24 commit admits a record on the store as it is under the writers' lock: another actor's append between "
          "prepare and commit cannot leave the store refused (Codex 01cb8aa7c0de on 94021033: both filed, every later "
          "operation RESOURCE_LIMIT)", "ok" in after and not thread.is_alive() and not (R.rid(a) in lines and R.rid(b) in lines),
          {"alice": err(results.get("alice", {})) or "ok", "bob": err(results.get("bob", {})) or "ok", "workspace": err(after) or "ok"})

    def exercise(rejected):
        repo = Repo()
        if rejected:
            repo.store.add_lines([b'{"junk":"' + b"x" * 1024 + b'"}\n'])
        cfg = cfg_of(repo, "bob")
        before = repo.store.file.read_bytes()
        target = repo.schemas["goal@1"]
        record = R.record("attest", "bob", repo.t + 1, {"target": target, "verdict": "seen"}, refs=[target],
                          prev=E.head(repo.store.snapshot(), repo.trust, "bob")["id"])
        bound = LIMITS["bytes"]
        try:
            LIMITS["bytes"] = len(before) + 64           # the engine's byte rule at a small bound, not 256 MiB
            p = api.call(cfg, "prepare", {"workspace": "w", "kind": "attest", "target": target, "body": {"verdict": "seen"}})
            c = api.call(cfg, "commit", {"workspace": "w", "record": record})
            w = api.call(cfg, "workspace", {})
            return {"prepare": err(p) or "ok", "commit": err(c) or "ok", "workspace": err(w) or "ok",
                    "unchanged": repo.store.file.read_bytes() == before}
        finally:
            LIMITS["bytes"] = bound
    want = {"prepare": "INVALID_RECORD", "commit": "INVALID_RECORD", "workspace": "ok", "unchanged": True}
    clean, junk = exercise(False), exercise(True)
    check("A25 the candidate is assessed over every raw line, rejected ones included, as the engine's byte bound counts "
          "them (Codex 4c58f74e7772 on 94021033: a rejected line let a write cross the bound)",
          clean == want and junk == want, {"clean": clean, "rejected_line": junk})


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


def home_cases():
    r, other = Repo(), Repo(name="s0fractal/other")
    seed = r.seed("bob")
    os.chmod(seed, 0o600)
    home = H.add_repository(H.add_repository(H.add_identity(H.empty(), "bob", str(seed)), str(r.root), "one", "bob"),
                            str(other.root), "two", operations=["context", "graph"])
    cfg = Config.from_home(home)
    one, two = cfg.workspace("one"), cfg.workspace("two")
    rows = {w["workspace"]: w for w in ok(api.call(cfg, "workspace", {}))["workspaces"]}
    check("A26 the operator's Home is a configuration: one workspace per registered repository, signing as its signer "
          "with that identity's seed, with its operations", sorted(cfg.workspaces) == ["one", "two"]
          and one.signer == ("bob", seed) and two.signer is None and two.operations == ("context", "graph")
          and rows["one"]["roles"] == ["pr/acceptor", "roadmap/acceptor"], rows)
    env = os.environ.get("WARRANT_HOME")
    os.environ["WARRANT_HOME"] = str(r.home / "home.json")
    try:
        H.save(home)
        try:
            loaded = sorted(Config.load(None).workspaces)
        except ER.AgentError as e:
            loaded = f"refused: {e}"
    finally:
        if env is None:
            os.environ.pop("WARRANT_HOME", None)
        else:
            os.environ["WARRANT_HOME"] = env
    check("A27 with no configuration named, the agent reads the operator's Home", loaded == ["one", "two"], loaded)
    cfg = Config.from_home(home)                       # Codex finding 1c3f12bcf1a9 on #238: `.warrant` swapped for a link out
    target = r.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    before = other.store.lines()
    shutil.rmtree(r.dot)
    r.dot.symlink_to(other.dot, target_is_directory=True)
    p = api.call(cfg, "prepare", {"workspace": "one", "kind": "attest", "target": target, "body": {"verdict": "accept"}})
    c = api.call(cfg, "commit", {"workspace": "one", "record": (p.get("ok") or {}).get("record")})
    sites = []                                          # each site on its own: the store a call opens, the receiver it reads
    for site in (cfg.workspace("one").open, lambda: repository_config(r.root)):
        try:
            site()
            sites.append(None)
        except ER.AgentError as e:
            sites.append(e.code)
    check("A29 a workspace's store is its repository's own: a `.warrant` link out of the repository is refused at prepare "
          "and at commit, by the store it opens and by the receiver it reads, and nothing reaches the other store",
          err(p) == "BAD_REQUEST" and err(c) is not None and sites == ["BAD_REQUEST", "BAD_REQUEST"]
          and other.store.lines() == before, (p, c, sites))
def receiver_cases():
    r = Repo()
    (r.dot / "v3.json").rename(r.home / "foreign-receiver.json")     # Codex finding d6127c0fd71d on #236
    (r.dot / "v3.json").symlink_to(r.home / "foreign-receiver.json")
    out = api.call(cfg_of(r), "workspace", {"workspace": "w"})
    check("A28 a workspace's v3.json is read from its repository's store only: a link out of it is refused",
          err(out) == "BAD_REQUEST" and "outside" in out["message"], out)


if __name__ == "__main__":
    operations()
    refusal_cases()
    admission_cases()
    init_cases()
    mcp_cases()
    home_cases()
    receiver_cases()
    sys.exit(finish())
