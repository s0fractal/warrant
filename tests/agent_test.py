#!/usr/bin/env python3
"""warrant_agent (warrant-agent/3): each operation, its refusals, the Warrant 2 configuration it still
reads, `warrant-agent-mcp init` and its in-memory twin (--repo), and the stdio MCP server when the SDK is installed.

    python3 tests/agent_test.py
"""
import asyncio
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time

from world import KEYS, ROLES, Repo, check, finish

from warrant import across as A
from warrant import bootstrap as B
from warrant import cli as WCLI
from warrant import drift as D
from warrant import engine as E
from warrant import graph as G
from warrant import home as H
from warrant import records as R
from warrant import repo as RP
from warrant import roadmap as RM
from warrant.store import LIMITS
from warrant_agent import api
from warrant_agent import cli as CLI
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
    def v2_of(**over):
        return Config({"agent_api": "warrant-agent/1", "workspaces": {"w": {
            "store": str(repo.dot / "store"), "signer": {"actor": "bob", "key": str(repo.seed("bob"))}, **over}}})
    try:
        v2_of(limits={"context_bytes": 1})
        limited = None
    except ER.AgentError as e:
        limited = e.code
    check("A10b a Warrant 2 configuration that sets limits is refused, not read with Warrant 3's defaults (R-LEGACY-CUSTOM-CONFIG)",
          limited == "UNSUPPORTED_VERSION")
    narrow, reader = v2_of(operations=["context"]), v2_of(operations=["context", "read", "compute"])
    check("A10c a Warrant 2 configuration keeps its operations: graph only where read was granted, compute gone",
          narrow.workspaces["w"].operations == ("context",) and reader.workspaces["w"].operations == ("context", "read", "graph"))
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
    words = set(E.GUARDS) | set(E.RELIANCE) | {D.STALE} | set(E.BASES) | set(E.PROBLEMS) | set(E.REJECTIONS) | set(ER.CODES) | {"OK", "UNATTESTED"}
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


def with_home(path, f):
    env = os.environ.get("WARRANT_HOME")
    os.environ["WARRANT_HOME"] = str(path)
    try:
        return f()
    finally:
        if env is None:
            os.environ.pop("WARRANT_HOME", None)
        else:
            os.environ["WARRANT_HOME"] = env


def memory_cases():
    """--repo DIR --actor A: init's checks, its configuration held in memory, no file written (a review worktree)."""
    repo = Repo()
    I.ROOTS = (repo.home,)
    seed = repo.seed("bob")
    obl = repo.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    files = lambda: sorted(str(p) for p in repo.home.rglob("*") if ".warrant" not in p.parts)
    before = files()
    cfg = I.configuration(repo.root, "bob", seed)
    written = I.plan(repo.root, "bob", seed, repo.home / "cfg" / "same.json")[0]
    name = repo.root.name.lower()
    w = cfg.workspace(name) if name in cfg.workspaces else None
    p = ok(api.call(cfg, "prepare", {"workspace": name, "kind": "attest", "target": obl, "body": {"verdict": "seen"}}))
    filed = ok(api.call(cfg, "commit", {"workspace": name, "record": p.get("record")})).get("filed", {})
    check("I10 --repo holds in memory the configuration init would write for the checkout, signs as its signer, and "
          "writes no file", list(cfg.workspaces) == list(written["workspaces"]) == [name] and w is not None
          and (str(w.repo), w.signer, list(w.operations)) == (written["workspaces"][name]["repo"], ("bob", seed),
                                                            written["workspaces"][name]["operations"])
          and filed.get("actor") == "bob" and files() == before, (sorted(cfg.workspaces), written, filed))

    def refused(code, **kw):
        args = dict(repo=repo.root, actor="bob", seed=seed)
        args.update(kw)
        try:
            I.configuration(**args)
            return None
        except I.Refused as e:
            return e.code == code or e.code
    inside = repo.root / "k.seed"
    shutil.copy(seed, inside)
    got = {"key": refused("INIT_KEY_NOT_PINNED", seed=repo.seed("eve")), "inside": refused("INIT_INSIDE_REPOSITORY", seed=inside),
           "actor": refused("INIT_ACTOR_NOT_PINNED", actor="zed"), "repo": refused("INIT_NOT_A_REPOSITORY", repo=repo.home),
           "outside": refused("INIT_OUTSIDE_HOME", seed="/" + "k.seed")}
    inside.unlink()
    check("I11 --repo refuses what init refuses: a key the checkout does not bind to the actor, a seed inside the checkout, "
          "an actor it binds no key to, a directory that is no checkout, a seed outside the operator's home",
          set(got.values()) == {True}, got)
    os.chmod(seed, 0o600)
    home = H.add_identity(H.empty(), "bob", str(seed))
    H.save(home, repo.home / "conf" / "home.json")

    def by_home(actor):
        try:
            return I.configuration(repo.root, actor).workspace(name).signer
        except I.Refused as e:
            return e.code
    found = with_home(repo.home / "conf" / "home.json", lambda: (by_home("bob"), by_home("carol")))
    check("I12 with no --seed the signer's seed is the operator's Home identity's; an actor with no identity is refused",
          found == (("bob", seed), "INIT_NO_SEED"), found)

    def cli(*argv):
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = CLI.main(list(argv))
        except SystemExit as e:
            rc = e.code
        except Exception as e:                         # a mutant's escape is a result, not a crash of the suite
            rc = type(e).__name__
        try:
            return rc, json.loads(out.getvalue())
        except ValueError:
            return rc, None
    r = str(repo.root)
    runs = {"ok": cli("--repo", r, "--actor", "bob", "--seed", str(seed), "workspace", "{}"),
            "key": cli("--repo", r, "--actor", "bob", "--seed", str(repo.seed("eve")), "workspace", "{}"),
            "both": cli("--config", str(repo.home / "cfg" / "same.json"), "--repo", r, "--actor", "bob", "workspace", "{}"),
            "stray": with_home(repo.home / "conf" / "home.json", lambda: cli("--actor", "bob", "workspace", "{}")),
            "no-actor": cli("--repo", r, "workspace", "{}")}
    shape = {k: (rc, (out or {}).get("error") or [x["workspace"] for x in (out or {}).get("ok", {}).get("workspaces", [])])
             for k, (rc, out) in runs.items()}
    check("I13 warrant-agent --repo serves the checkout; a refused seed is the init refusal's code; --config with --repo, "
          "--actor without --repo, and --repo without --actor are usage errors, never another configuration",
          shape == {"ok": (0, [name]), "key": (2, "INIT_KEY_NOT_PINNED"), "both": (2, []), "stray": (2, []),
                    "no-actor": (2, [])}, shape)


def roadmap_parity_cases():
    """warrant's own repository through this interface: `init` for a pinned signer, then docs/AGENT.md's recipes for an
    obligation and its closure and an acceptance write the bytes warrant.roadmap and `warrant attest` write."""
    tools, agent = Repo(), Repo()
    goal = [r.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "goal"}) for r in (tools, agent)][0]
    I.ROOTS = (agent.home,)
    workspaces = {}
    for actor in ("carol", "bob"):
        out = agent.home / "cfg" / f"{actor}.json"
        name = I.init(agent.root, actor, agent.seed(actor), out)["workspace"]
        workspaces[actor] = (Config.load(out), name)

    def filed(actor, **req):
        cfg, name = workspaces[actor]
        made = ok(api.call(cfg, "prepare", dict(req, workspace=name)))
        return ok(api.call(cfg, "commit", {"workspace": name, "record": made.get("record")})).get("id")

    def roadmap(*argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = RP.main(RM.run, ["--root", str(tools.root), *argv])
        return json.loads(out.getvalue())["filed"][0] if code == 0 else code

    def attest(actor, target):
        old = os.getcwd()
        out = io.StringIO()
        try:
            os.chdir(tools.home)
            with contextlib.redirect_stdout(out):
                code = WCLI.main(["attest", "--store", "repo/.warrant", "--actor", actor, "--key", str(tools.seed(actor)), target])
        finally:
            os.chdir(old)
        return code

    done = {"established": ["what holds"], "residual": ["what does not"]}
    now, real = 1_900_000_000, time.time
    time.time = lambda: now
    try:
        o1 = roadmap("oblige", "--goal", "G1", "--statement", "owed", "--actor", "carol", "--key", str(tools.seed("carol")))
        c1 = roadmap("close", "--obligation", o1, "--ref", "s0fractal/warrant#1", "--established", done["established"][0],
                     "--residual", done["residual"][0], "--actor", "carol", "--key", str(tools.seed("carol")))
        accepted = attest("bob", c1)
        body = {"statement": "owed", "answers": goal, "serves": []}
        o2 = filed("carol", kind="entity", schema="obligation@1", body=dict(body, state="open"))
        c2 = filed("carol", kind="entity", schema="obligation@1", lineage=o2,
                   body=dict(body, state="done", evidence=[], refs=["s0fractal/warrant#1"], **done))
        filed("bob", kind="attest", target=c2, body={"verdict": "accept"})
    finally:
        time.time = real
    same = (o1, c1, accepted) == (o2, c2, 0) and agent.store.lines() == tools.store.lines()
    rep = RP.Repo(agent.root).report()
    check("R01 `init` for a pinned signer, then an obligation, its closure and its acceptance through the agent interface "
          "are the bytes warrant.roadmap and `warrant attest` file, and the roadmap reads the obligation done with no problem",
          same and rep["lineages"][o2]["state"] == "done" and RM.check(rep) == [], (o1, o2, c1, c2, accepted))


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
    check("M01 stdio MCP: nine tools; prepare and commit sign as the configured signer; a refusal is a tool error with its JSON",
          names == sorted(["warrant_" + n for n in ("workspace", "context", "read", "graph", "across", "handoff", "prepare", "commit", "explain")])
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
def _stores(*repos, **options):
    """A configuration of one workspace per (name, repo), read-only, with `options` for all of them."""
    return Config({"agent_api": "warrant-agent/3", "workspaces": {
        n: dict({"repo": str(r.root), "operations": ["context", "read", "graph"]}, **options) for n, r in repos}})


def _copy(frm, to, *ids):
    """The exact stored lines of `ids` in `frm`, added to `to`: one record, byte for byte, in two stores."""
    want = set(ids)
    to.store.add_lines([x for x in frm.store.lines() if json.loads(x)["record"] and R.rid(json.loads(x)["record"]) in want])


def _row(node, store):
    return next((v for v in (node or {}).get("in", []) if v["store"] == store), {})


def _ans(cfg, q):
    """The answer, or {} whatever the call raised: a case reads it with .get, so a mutant dies on the case's assertion."""
    try:
        return ok(api.call(cfg, "across", q))
    except Exception:           # noqa: BLE001
        return {}


def _by_id(out):
    return {n["id"]: n for n in out.get("nodes", [])}


def _all_pages(cfg, req):
    nodes, pages, offset = [], [], 0
    while offset is not None:
        out = _ans(cfg, dict(req, offset=offset))
        pages.append(out)
        nodes += out.get("nodes", [])
        offset = out.get("next")
    return nodes, pages


def across_cases():
    # X01-X03: one record in two stores, whose profiles differ: bob accepts in one, carol in the other.
    a, b = Repo(), Repo(roles=dict(ROLES, **{"roadmap/acceptor": ["carol"]}), name="s0fractal/other")
    root = a.entity("alice", "obligation@1", {"state": "open", "statement": "owed", "serves": []})
    done = a.entity("alice", "obligation@1", {"state": "done", "statement": "owed", "serves": []}, lineage=root)
    accept = a.attest("bob", done)
    _copy(a, b, root, done, accept)
    finding = a.put("bob", "challenge", {"target": done, "statement": "wrong"}, refs=[done])
    _copy(a, b, finding)
    cfg = _stores(("a", a), ("b", b))
    actor = {n["id"]: n for n in _all_pages(cfg, {"query": "actor", "actor": "alice"})[0]}
    d = actor.get(done)
    ra, rb = _row(d, "a"), _row(d, "b")
    check("X01 trust is not merged: one version reads MET and CHALLENGED under the store whose profile counts bob, PENDING "
          "under the store whose does not, each row from its own store's report alone",
          ra.get("guard") == "MET" and ra.get("reliance") == "CHALLENGED"
          and rb.get("guard") == "PENDING" and rb.get("reliance") == "ELIGIBLE", d)
    alone = {n: _ans(_stores((n, r)), {"query": "actor", "actor": "alice"}) for n, r in (("a", a), ("b", b))}
    single = {n: _by_id(alone[n]).get(done) for n in alone}
    check("X02 a store's row in the answer over both stores is the row it gives alone: no store's records change another's verdict",
          ra and rb and ra == _row(single["a"], "a") and rb == _row(single["b"], "b"), (d, single))
    ids = [n["id"] for n in actor.values()]
    schema_ids = sorted(a.schemas.values())
    _copy(a, b, *schema_ids)
    twice = _all_pages(cfg, {"query": "actor", "actor": "alice"})[0]
    seen = [n["id"] for n in twice]
    check("X03 a record in several stores appears once, with every store's verdict listed",
          len(seen) == len(set(seen)) and set(ids) <= set(seen) and [v["store"] for v in next((n for n in twice if n["id"] == done), {}).get("in", [])] == ["a", "b"],
          twice)

    # X04: the same actor's name under another key in another store is that store's own
    c = Repo(name="s0fractal/third")
    c.trust = dict(c.trust, keys=dict(c.trust["keys"], alice=[KEYS["eve"].public]))
    c.write_config("s0fractal/third")
    _copy(a, c, root)
    forged = R.record("entity", "alice", c.t + 1, {"state": "open", "statement": "forged", "serves": []}, "obligation@1")
    c.store.add_lines([R.line(forged, KEYS["bob"])[1]])
    out = _ans(_stores(("a", a), ("c", c)), {"query": "actor", "actor": "alice"})
    by = _by_id(out)
    keys = {s["store"]: s.get("keys") for s in out.get("stores", [])}
    counts = {s["store"]: s.get("counts") for s in out.get("stores", [])}
    check("X04 an actor is read under each store's own keys: a store that binds the name to another key rejects the record "
          "the other admits, its forged record is nobody's here, and each store's keys for the name are shown apart",
          "rejected" in _row(by.get(root), "c") and "basis" in _row(by.get(root), "a") and R.rid(forged) not in by
          and keys == {"a": [KEYS["alice"].public], "c": [KEYS["eve"].public]} and counts["c"] == {} and counts["a"]
          and next((s for s in out.get("stores", []) if s["store"] == "c"), {}).get("rejected", 0) >= 1, out.get("stores"))

    # X05-X06: stores that cannot be read
    broken = Repo(name="s0fractal/broken")
    (broken.dot / "v3.json").write_text("{")
    linked, other = Repo(), Repo()
    shutil.rmtree(linked.dot)
    linked.dot.symlink_to(other.dot, target_is_directory=True)
    file_link, big, badblob, blob_link = Repo(), Repo(), Repo(), Repo()
    shutil.rmtree(blob_link.dot / "blobs")
    (blob_link.dot / "blobs").symlink_to(other.dot / "blobs", target_is_directory=True)
    file_link.store.file.unlink()
    file_link.store.file.symlink_to(other.store.file)
    (badblob.dot / "blobs" / ("0" * 64)).write_bytes(b"not this")
    held = Repo(name="s0fractal/held")
    cite = held.entity("alice", "obligation@1", {"state": "open", "statement": "cites", "serves": []}, refs=["e" * 64])
    repos = (("broken", broken), ("linked", linked), ("link", file_link), ("big", big), ("badblob", badblob), ("bloblink", blob_link), ("held", held))
    cfg = Config({"agent_api": "warrant-agent/3", "workspaces": {n: {"repo": str(r.root), "operations": ["graph"],
                 "limits": dict(store_bytes=16 if n == "big" else 64 << 20, context_bytes=64 << 10, read_bytes=1 << 18)} for n, r in repos}})
    out = _ans(cfg, {"query": "open"})
    gone = {u["store"]: u["why"] for u in out.get("unavailable", [])}
    try:
        A.snapshot_of(big.store, 16)                   # Home's door, whose bound no workspace checks first
        over = None
    except A.Refusal as e:
        over = e.code
    check("X05 a store that fails to load is named with its reason, never dropped, and the others still answer: a bad v3.json, a "
          "`.warrant` link out, a records file or a blob directory linked out, a store beyond its bytes, a blob not named by its hash",
          over == "RESOURCE_LIMIT" and sorted(gone) == ["badblob", "big", "bloblink", "broken", "link", "linked"] and [s["store"] for s in out.get("stores", [])] == ["held"]
          and cite in _by_id(out) and all(gone.values()), gone)
    fifo = Repo()
    fifo.store.file.unlink()
    os.mkfifo(fifo.store.file)
    seen = []
    worker = threading.Thread(target=lambda: seen.append(_ans(_stores(("fifo", fifo)), {"query": "stores"})), daemon=True)
    worker.start()
    worker.join(10)
    check("X24 a records file that is not regular is named, and blocks no read", seen and "not a regular file" in str(seen[0].get("unavailable")), seen)
    out = _ans(cfg, {"query": "rests", "target": "e" * 64})
    check("X06 what no store read here holds reads UNAVAILABLE while the store that may hold it is named; the citing record is still found",
          out.get("target") == {"id": "e" * 64, "state": "UNAVAILABLE"} and sorted(u["store"] for u in out.get("unavailable", [])) == sorted(gone)
          and [n["id"] for n in out.get("nodes", [])] == ["e" * 64, cite], out.get("nodes"))

    # X07: nothing from a repository is executed
    planted = Repo(name="s0fractal/planted")
    mark = planted.home / "executed"
    code = f"open({str(mark)!r}, 'w').write('ran')\n"
    for rel in ("warrant/__init__.py", "warrant/across.py", "warrant_agent/__init__.py", "conftest.py", "setup.py", "tools/claims.py",
                ".warrant/__init__.py", ".warrant/hook.py", "json.py", "tests/mutants.py"):
        f = planted.root / rel
        f.parent.mkdir(exist_ok=True)
        f.write_text(code)
    (planted.dot / "claims.json").write_text(json.dumps({"warrant": "claims/1", "mutants": "tests/mutants.py", "witnesses": ["json.py"]}))
    home_doc = H.add_repository(H.empty(), str(planted.root), "planted", operations=["graph"])
    H.save(home_doc, planted.home / "conf" / "home.json")
    before = {str(p): p.read_bytes() for p in planted.root.rglob("*") if p.is_file()}
    env = dict(os.environ, WARRANT_HOME=str(planted.home / "conf" / "home.json"), PYTHONPATH=os.pathsep.join(sys.path))
    run = subprocess.run([sys.executable, "-c", "import sys; from warrant.cli import main; sys.exit(main(sys.argv[1:]))", "across", "open"],
                         capture_output=True, text=True, cwd=str(planted.home), env=env, check=False)
    in_process = _ans(Config.from_home(home_doc), {"query": "stores"})
    loaded = [m.__file__ for m in list(sys.modules.values()) if str(planted.root) in (getattr(m, "__file__", None) or "")]
    check("X07 nothing from any repository is executed or written: Python files planted where a package, a test harness or a claims "
          "file would name them stay unrun, no module loads from the repository, and every file holds the same bytes after the read",
          run.returncode == 0 and not mark.exists() and not loaded and in_process.get("stores")
          and before == {str(p): p.read_bytes() for p in planted.root.rglob("*") if p.is_file()}, (run.stderr[-300:], loaded))

    # X08-X10: open intents and standing challenges
    g1 = Repo(name="s0fractal/one")
    goal = g1.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "a question"})
    g2 = Repo(roles=dict(ROLES, **{"roadmap/acceptor": ["bob"]}), name="s0fractal/two")
    _copy(g1, g2, goal)
    met = g2.entity("alice", "goal@1", {"state": "met", "key": "G1", "text": "a question", "established": ["held"]}, lineage=goal)
    g2.attest("bob", met)
    pending = g1.entity("alice", "obligation@1", {"state": "open", "statement": "s" * 400, "serves": []})
    closure = g1.entity("alice", "obligation@1", {"state": "done", "statement": "s" * 400, "serves": []}, lineage=pending)
    closed = g1.entity("alice", "obligation@1", {"state": "open", "statement": "closed", "serves": []})
    closed_done = g1.entity("alice", "obligation@1", {"state": "done", "statement": "closed", "serves": []}, lineage=closed)
    g1.attest("bob", closed_done)
    none = Repo(roles=dict(ROLES, **{"schema/author": ["nobody"]}), name="s0fractal/none")
    cfg = _stores(("g1", g1), ("g2", g2), ("none", none))
    out = _ans(cfg, {"query": "open"})
    by = _by_id(out)
    rows = {s["store"]: s for s in out.get("stores", [])}
    check("X08 open intents: an intent one store reads as open and another as met is listed with each store's state; a closed "
          "one is not listed; its text and key are carried; a closure waiting shows its leaf and that guard's word",
          _row(by.get(goal), "g1").get("state") == "open" and _row(by.get(goal), "g2").get("state") == "met"
          and (by.get(goal) or {}).get("key") == "G1" and (by.get(goal) or {}).get("text") == "a question" and closed not in by and closed_done not in by
          and _row(by.get(pending), "g1").get("leaf") == closure and _row(by.get(pending), "g1").get("leaf_guard") == "PENDING"
          and 0 < len((by.get(pending) or {}).get("text", "")) < 400, by)
    check("X09 a store that counts neither schema says so; its silence never reads as no open intents",
          rows.get("none", {}).get("no_schema") == ["goal@1", "obligation@1"] and rows.get("none", {}).get("intents") == {}
          and "no_schema" not in rows.get("g1", {}) and rows.get("g1", {}).get("intents") == {"goal@1": 1, "obligation@1": 1}, rows)
    t1, t2 = Repo(name="s0fractal/one"), Repo(roles=dict(ROLES, **{"roadmap/acceptor": ["carol"]}), name="s0fractal/two")
    subject = t1.entity("alice", "obligation@1", {"state": "done", "statement": "s", "serves": []})
    stands = t1.put("bob", "challenge", {"target": subject, "statement": "counted in one"}, refs=[subject])
    thesis = t2.entity("alice", "obligation@1", {"state": "done", "statement": "t", "serves": []})
    only = t2.put("eve", "challenge", {"target": thesis, "statement": "a thesis"}, refs=[thesis])
    _copy(t1, t2, subject, stands)
    first_v = t1.entity("alice", "obligation@1", {"state": "open", "statement": "first", "serves": []})
    t1.entity("alice", "obligation@1", {"state": "open", "statement": "second", "serves": []}, lineage=first_v)
    past = t1.put("alice", "challenge", {"target": first_v, "statement": "of a version already replaced"}, refs=[first_v])
    out = _ans(_stores(("one", t1), ("two", t2)), {"query": "challenges"})
    by = _by_id(out)
    one, two = _row(by.get(stands), "one"), _row(by.get(stands), "two")
    check("X10 standing challenges: one that stands in one store and is a thesis in another is listed once with each store's "
          "reading; a thesis standing nowhere, and a counted challenge of a replaced version, are not listed",
          one.get("stands") is True and two.get("stands") is False and two.get("counted") is False and only not in by
          and past not in by and (by.get(stands) or {}).get("text") == "counted in one", by)

    # X11-X13: references between stores
    src, dst = Repo(name="s0fractal/src"), Repo(name="s0fractal/dst")
    report = src.entity("alice", "obligation@1", {"state": "open", "statement": "the report", "serves": []})
    dep = src.attest("bob", report)
    citing = dst.entity("alice", "obligation@1", {"state": "open", "statement": "rests on it", "serves": []}, refs=[report])
    next_ = dst.attest("bob", citing)
    dead = dst.entity("alice", "obligation@1", {"state": "open", "statement": "unrelated", "serves": []})
    cfg = _stores(("src", src), ("dst", dst))
    out = _ans(cfg, {"query": "rests", "target": report})
    by = _by_id(out)
    check("X11 what rests on a hash crosses stores: records of the store that holds it and of one that only cites it, each with "
          "its own store's rows, in order of distance, the foreign reference read ELSEWHERE with where it is held",
          set(by) == {report, dep, citing, next_} and by.get(report, {}).get("depth") == 0 and by.get(next_, {}).get("depth") == 2
          and out["nodes"][0]["id"] == report and out.get("complete") is True and dead not in by
          and by.get(citing, {}).get("foreign") == [{"id": report, "state": "ELSEWHERE", "held_in": ["src"]}]
          and [v["store"] for v in by.get(citing, {}).get("in", [])] == ["dst"] and out.get("target", {}).get("held_in") == ["src"], by)
    views = {x: _ans(cfg, {"query": "rests", "target": x}).get("query", {}).get("target")
             for x in (report[:12], f"s0fractal/src:{report}", f"nowhere:{report}")}
    refused = [err(api.call(cfg, "across", {"query": "rests", "target": t})) for t in
               ("0000000", "ffffffffffff", f"s0fractal/src:{report[:12]}", f"{report}\n", f"a:{report}\n", report.upper(), 7)]
    check("X12 a target is an id, a prefix of 8 or more, or a citation whose store part narrows nothing; a prefix naming nothing is "
          "NOT_FOUND; a malformed citation is BAD_REQUEST", set(views.values()) == {report}
          and refused == ["BAD_REQUEST", "NOT_FOUND", "BAD_REQUEST", "BAD_REQUEST", "BAD_REQUEST", "BAD_REQUEST", "BAD_REQUEST"], (views, refused))
    alone = _stores(("dst", dst))
    gone = _ans(alone, {"query": "rests", "target": report})
    text = json.dumps(gone).lower()
    cited = _by_id(gone).get(citing, {})
    check("X13 a reference nothing read here holds is UNAVAILABLE, in the answer and in a single store's graph, and no answer says it "
          "is absent or missing", cited.get("foreign") == [{"id": report, "state": "UNAVAILABLE"}] and gone.get("target", {}).get("state") == "UNAVAILABLE"
          and "absent" not in text and "missing" not in text and G.describe(dst.report(), {}, report)["kind"] == "unavailable", gone)

    # X14: the engine admits a foreign reference as it is, and no store's verdict meets another store's guard
    seed = dst.seed("bob")
    w = Config({"agent_api": "warrant-agent/3", "workspaces": {"w": {"repo": str(dst.root), "signer": {"actor": "bob", "key": str(seed)}}}})
    p = api.call(w, "prepare", {"workspace": "w", "kind": "entity", "schema": "obligation@1", "refs": [report], "body": {
        "state": "open", "statement": "cites by bare id", "serves": [], "refs": [f"s0fractal/src:{report}"]}})
    c = api.call(w, "commit", {"workspace": "w", "record": (p.get("ok") or {}).get("record")})
    rep = dst.report()
    closed_src = src.entity("alice", "obligation@1", {"state": "done", "statement": "closed there", "serves": []})
    src.attest("bob", closed_src)
    waits = dst.entity("alice", "obligation@1", {"state": "done", "statement": "needs it", "serves": []}, requires=[closed_src])
    dst.attest("bob", waits)
    row = _row(_by_id(_ans(cfg, {"query": "rests", "target": closed_src})).get(waits), "dst")
    check("X14 `refs` carries a foreign id unchanged and the engine admits it with no problem and no rejected line, with its citation "
          "in the body; a guard requiring a lineage closed only in another store stays PENDING: no store's verdict meets another's guard",
          "ok" in c and not rep["problems"] and not rep["rejected"] and report in [e[2] for e in rep["graph"]["edges"]]
          and row.get("guard") == "PENDING", (c, rep["problems"], row))

    # X15: the budget
    many = Repo(name="s0fractal/many")
    for i in range(40):
        many.entity("alice", "obligation@1", {"state": "open", "statement": f"n{i}", "serves": [], "refs": []}, refs=[f"{i:064x}"])
    wide = many.entity("alice", "obligation@1", {"state": "open", "statement": "wide", "serves": []}, refs=[f"{i:064x}" for i in range(100)])
    cfg = _stores(("many", many))
    nodes, pages = _all_pages(cfg, {"query": "open", "max_bytes": 8192})
    ids = [n["id"] for n in nodes]
    row = next((n for n in nodes if n["id"] == wide), {})
    check("X15 a result stays within its bytes: pages cover every row once, `total` says how many, `next` is null only at the end, and a "
          "record citing more than a row lists says how many it leaves out",
          len(pages) > 1 and all(len(json.dumps(x, sort_keys=True)) <= 8192 for x in pages) and len(ids) == len(set(ids)) == pages[0].get("total") == 41
          and pages[-1].get("next") is None and all(x.get("next") for x in pages[:-1]) and len(row.get("refs", [])) == A.REF_ROWS
          and row.get("refs_more") == 100 - A.REF_ROWS and row.get("foreign_more") == 100 - A.REF_ROWS, [len(x.get("nodes", [])) for x in pages])
    tiny, header = api.call(cfg, "across", {"query": "stores", "max_bytes": 64}), _ans(cfg, {"query": "open"})
    row_over = api.call(cfg, "across", {"query": "open", "max_bytes": len(json.dumps(dict(header, nodes=[]), sort_keys=True)) + 8})
    small = many.home / "small.json"
    small.write_text(json.dumps({"agent_api": "warrant-agent/3", "workspaces": {"many": {"repo": str(many.root), "limits": {
        "store_bytes": 64 << 20, "context_bytes": 8192, "read_bytes": 1 << 18}}}}))
    capped = _ans(Config.load(small), {"query": "open", "max_bytes": 1 << 20})
    check("X16 a page that cannot fit is refused (RESOURCE_LIMIT), never cut; a request asks for less than the operator's bound, never more",
          err(tiny) == "RESOURCE_LIMIT" and err(row_over) == "RESOURCE_LIMIT" and len(json.dumps(capped, sort_keys=True)) <= 8192
          and capped.get("next") is not None, (tiny, row_over, capped.get("next")))

    # X17: registration
    reg, private = Repo(name="s0fractal/reg"), Repo(name="s0fractal/private")
    secret = private.entity("alice", "obligation@1", {"state": "open", "statement": "a lens's own", "serves": []})
    doc = H.add_repository(H.empty(), str(reg.root), "reg")
    q = {"query": "actor", "actor": "alice"}
    one = _ans(Config.from_home(doc), q)
    two = ok(api.call(Config.from_home(H.add_repository(doc, str(private.root), "lens")), "across", q))
    held_back = ok(api.call(Config.from_home(H.add_repository(doc, str(private.root), "lens", operations=["context"])), "across", q))
    cli_back = A.answer(A.home_readings(H.add_repository(doc, str(private.root), "lens", operations=["context"])), q)
    check("X17 a private store appears only if the operator registers it, and one registered without `graph` is named as not read, "
          "through the agent and through Home alike", secret not in json.dumps(one) and secret in _by_id(two)
          and secret not in json.dumps(held_back) and [u["store"] for u in held_back.get("unavailable", [])] == ["lens"]
          and "NOT_PERMITTED" in str(held_back.get("unavailable")) and secret not in json.dumps(cli_back)
          and "NOT_PERMITTED" in str(cli_back.get("unavailable")), held_back.get("unavailable"))

    # X18: the commands proposed for the operator's Home are read-only for signing
    ro = Repo(name="s0fractal/ro")
    target = ro.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    doc = H.add_repository(H.empty(), str(ro.root), "ro", operations=["context", "read", "graph"])
    cfg = Config.from_home(doc)
    lines = ro.store.lines()
    calls = {"prepare": api.call(cfg, "prepare", {"workspace": "ro", "kind": "attest", "target": target, "body": {"verdict": "accept"}}),
             "commit": api.call(cfg, "commit", {"workspace": "ro", "record": {}}),
             "import": api.call(cfg, "handoff", {"workspace": "ro", "op": "import", "package": {}})}
    check("X18 a repository registered with no signer and the operations context, read and graph can sign nothing and write nothing: "
          "no identity is read, prepare, commit and import are refused, the store keeps its bytes",
          {k: err(v) for k, v in calls.items()} == {"prepare": "NOT_PERMITTED", "commit": "NOT_PERMITTED", "import": "NOT_PERMITTED"}
          and doc["identities"] == {} and cfg.workspace("ro").signer is None and ro.store.lines() == lines, calls)

    # X19-X21: the doors, the request, the identity of an answer
    cfg = _stores(("src", src), ("dst", dst))
    q = {"query": "open"}
    same = json.dumps(_ans(cfg, q), sort_keys=True) == json.dumps(_ans(cfg, q), sort_keys=True)
    first = _ans(cfg, q)
    other = Repo(roles=dict(ROLES, **{"roadmap/acceptor": ["carol"]}), name="s0fractal/src")
    shutil.rmtree(other.dot)
    shutil.copytree(src.dot, other.dot)
    other.profile = {"warrant": "profile/3", "roles": {r: sorted(a) for r, a in sorted(dict(ROLES, **{"roadmap/acceptor": ["carol"]}).items())}}
    other.write_config("s0fractal/src")
    moved = _ans(_stores(("src", other), ("dst", dst)), q)
    src.entity("alice", "obligation@1", {"state": "open", "statement": "one more", "serves": []})
    grown = _ans(cfg, q)
    check("X19 the same lens over the same root gives the same bytes; another store's profile changes the lens, a new record the root",
          same and first and moved.get("lens") != first.get("lens") and moved.get("root") == first.get("root")
          and grown.get("root") != first.get("root") and grown.get("lens") == first.get("lens"), (first.get("lens"), moved.get("lens")))
    path = dst.home / "conf2" / "home.json"
    doc = H.add_repository(H.add_repository(H.empty(), str(src.root), "src"), str(dst.root), "dst")
    H.save(doc, path)
    empty = dst.home / "conf3" / "home.json"
    H.save(H.empty(), empty)
    printed, code = [], []

    def warrant(*argv):
        buf, errs = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(errs):
            code.append(WCLI.main(["across", *argv]))
        printed.append(errs.getvalue())
        return buf.getvalue()
    by_cli = with_home(path, lambda: json.loads(warrant("actor", "alice", "--max-bytes", "9000") or "{}"))
    by_api = A.answer(A.home_readings(doc), {"query": "actor", "actor": "alice", "max_bytes": 9000})
    with_home(empty, lambda: warrant("open"))
    with_home(path, lambda: warrant("open", "stray"))
    check("X20 `warrant across` answers as the backend does; with no repository registered, or a stray argument, it refuses (exit 2)",
          by_cli == by_api and by_cli.get("nodes") and code[0] == 0 and code[1] == 2 and code[2] == 2 and "registers no repository" in printed[1], (code, printed))
    bad = {"workspace": {"query": "open", "workspace": "src"}, "query": {"query": "nope"}, "none": {}, "actor": {"query": "actor"},
           "stray": {"query": "open", "actor": "alice"}, "name": {"query": "actor", "actor": "a\n"}, "offset": {"query": "open", "offset": -1},
           "true": {"query": "open", "offset": True}, "bytes": {"query": "open", "max_bytes": 0}, "schema": {"query": "open", "schema": 5},
           "list": {"query": ["open"]}}
    codes = {}
    for k, v in bad.items():
        try:
            codes[k] = err(api.call(cfg, "across", v))
        except Exception as e:      # noqa: BLE001
            codes[k] = type(e).__name__
    check("X21 a request is read closed: a named workspace, an unknown query or member, a bad actor, offset, bound or schema is BAD_REQUEST",
          set(codes.values()) == {"BAD_REQUEST"}, codes)
    schemas = _ans(cfg, {"query": "actor", "actor": "alice", "schema": "goal@1"})
    listing = _ans(cfg, {"query": "stores"})
    (dst.home / "t.json").write_text(json.dumps(dst.trust))
    (dst.home / "p.json").write_text(json.dumps(dst.profile))
    named = _ans(Config({"agent_api": "warrant-agent/3", "workspaces": {"s": {"store": str(dst.dot), "trust": str(dst.home / "t.json"),
                                                                             "profile": str(dst.home / "p.json")}}}), {"query": "stores"})
    rows = {s["store"]: s for s in listing.get("stores", [])}
    check("X22 `schema` narrows the rows; `stores` gives each store's lineages by schema and state, and nothing merged; each store's "
          "row names the bytes read and the latest time a record there claims; a workspace named by store, trust and profile answers too",
          [s.get("store") for s in named.get("stores", [])] == ["s"] and "repository" not in named["stores"][0]
          and rows.get("src", {}).get("as_of") == src.t and rows.get("src", {}).get("root") == src.report()["snapshot"] and schemas.get("total") == 0 and {s["store"]: s.get("lineages", {}).get("obligation@1 open") for s in listing.get("stores", [])} == {"dst": 3, "src": 2}
          and listing.get("nodes") == [] and listing.get("completeness") == "UNATTESTED", listing.get("stores"))
    words = {w: GL.explain(w) for w in A.REFERENCE_STATES}
    check("X23 the words of a reference are in the glossary, and UNAVAILABLE says it does not establish that nothing exists",
          all(words.values()) and "not say" in words["UNAVAILABLE"]["does_not_establish"], words)


def bench_cases():
    """tests/assess_bound.py (R-AGENT-CLOCK) at a 1 MiB bound: Codex's challenge f97f77fa5fad, every store measured had
    crossed the bound and none went through the agent's admission."""
    import hashlib

    import assess_bound as AB
    bound = 1 << 20
    got = {name: AB.measure(make, bound) for name, make in AB.SHAPES}
    check("B01 the R-AGENT-CLOCK benchmark builds each shape at or below the bound, within one line of it, and the agent admits it",
          all("refused" not in g and bound - R.LINE_MAX < g["store_bytes"] <= bound and g["records"] > 0 for g in got.values()), got)

    def over(w):                     # a blob the size of the bound: records and blobs together exceed what the agent admits
        b = b"x" * bound
        w.r.store.blobs.mkdir(exist_ok=True)
        (w.r.store.blobs / hashlib.sha256(b).hexdigest()).write_bytes(b)
        AB.flat(w)
    refused = AB.measure(over, bound)
    check("B02 the benchmark reports a store the agent refuses as refused, with the agent's code, and times nothing",
          refused.get("refused") == "RESOURCE_LIMIT" and "assess_s" not in refused and refused["store_bytes"] > bound, refused)


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
    memory_cases()
    roadmap_parity_cases()
    mcp_cases()
    home_cases()
    across_cases()
    receiver_cases()
    bench_cases()
    sys.exit(finish())
