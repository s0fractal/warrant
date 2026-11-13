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
    led = ok(api.call(cfg_of(src), "graph", {"workspace": "w", "op": "ledger"}))
    gro = ok(api.call(cfg_of(src), "graph", {"workspace": "w", "op": "grounded", "target": d[:12]}))
    check("A30 graph op=ledger is the witness ledger of the workspace's store, op=grounded minds' Grounded of a target: a "
          "version a replayer reproduced a challenge on is refuted for its acceptor and not grounded, its lineage CHALLENGED",
          led.get("data", {}).get("bob", {}).get("refuted") == [[d, c]] and led.get("query") == {"op": "ledger"}
          and gro.get("data", {}).get("grounded") is False
          and [d, "RELIANCE CHALLENGED"] in gro.get("data", {}).get("failing", []), (led.get("data"), gro.get("data")))
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
          "reading; a voice no store counts (a thesis standing nowhere) is listed, marked uncounted (W4: a stranger's "
          "challenge was invisible here); a counted challenge of a replaced version is not listed",
          one.get("stands") is True and two.get("stands") is False and two.get("counted") is False
          and (by.get(only) or {}).get("uncounted") is True and not (by.get(stands) or {}).get("uncounted")
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


def serve_cases():
    """warrant serve (warrant_agent/serve.py): the records as pages a person reads, and a reaction he signs. Record
    text is data: it is escaped; a reaction credits nothing; a request from another host or a POST without the run's
    token is refused."""
    import http.client
    from http.server import ThreadingHTTPServer
    from warrant_agent import serve as SV
    r = Repo()
    evil = "<script>alert(1)</script> & \"quoted\""
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": evil, "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": evil, "serves": [],
                                           "established": ["it holds"], "residual": ["one gap"]}, lineage=o)
    c = r.put("eve", "challenge", {"target": d, "statement": "a counterexample <b>here</b>"}, refs=[d])
    r.attest("bob", d)
    space = SV.Space({"w": str(r.root)})
    app = SV.App(space, "bob", KEYS["bob"])
    rep = space.report("w")
    rows = SV.feed(rep)
    pages = [app.page_feed({}), app.page_lineage("w", d)[1], app.page_wait({"actor": "bob"}), app.page_stores()]
    check("SV1 the feed is one sentence per record, newest first: an obligation opened and closed, a challenge, an "
          "acceptance, each pointing at its lineage", [x["sentence"][1] for x in rows][:2] == ["прийняв", "заперечив"]
          and {x["sentence"][1] for x in rows} >= {"відкрив обов'язок", "закрив обов'язок"}
          and all(x["lineage"] == o for x in rows if x["kind"] != "schema")
          and {x["sentence"][1] for x in rows if x["kind"] == "schema"} == {"подав схему"}, [x["sentence"] for x in rows])
    check("SV2 record text is data on every page: escaped, never markup", all("<script>" not in h and "<b>here" not in h
          for h in pages) and "&lt;script&gt;" in pages[0] and "&lt;b&gt;here" in pages[1], [h[:0] for h in pages])
    by_attest = SV.lineage(rep, c)
    check("SV3 a lineage page: versions newest first with the attests and challenges on each, its state, reliance and "
          "groundedness; an attest or a challenge opens its target's lineage",
          by_attest and by_attest["lineage"] == o and [v["id"] for v in by_attest["versions"]] == [d, o]
          and {x["id"] for x in by_attest["versions"][0]["on"]} >= {c} and by_attest["grounded"] is not None
          and "it holds" in pages[1] and "one gap" in pages[1], by_attest and by_attest["state"])
    guard0 = dict(rep["versions"][d])
    form = {"token": app.token, "store": "w", "target": d, "agree": "-40", "importance": "90", "note": "not convinced"}
    refused = [app.react(dict(form, token="x"))[0], app.react(dict(form, agree="-101"))[0], app.react(dict(form, agree="1.5"))[0],
               app.react({k: v for k, v in form.items() if k in ("token", "store", "target")})[0],
               app.react(dict(form, target="0" * 64))[0], SV.App(space).react(form)[0]]
    code, where = app.react(form)
    rep2 = space.report("w")
    mine = [x for x in rep2["_recs"].values() if x["actor"] == "bob" and x["body"].get("verdict") == "react"]
    check("SV4 a reaction is the reader's attest {verdict: react} with integer dimensions in range and a note, filed "
          "only with this run's token and a signer; it credits nothing: the version's guard reads as before",
          refused == [403, 400, 400, 400, 400, 403] and code == 303 and where == f"/l/w/{d}" and len(mine) == 1
          and mine[0]["body"] == {"target": d, "verdict": "react", "agree": -40, "importance": 90, "note": "not convinced"}
          and {k: rep2["versions"][d][k] for k in ("guard", "accepted_by")} == {k: guard0[k] for k in ("guard", "accepted_by")}
          and "згода -40" in app.page_lineage("w", d)[1], (refused, code, mine))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = srv.server_address[1]
    srv.RequestHandlerClass = SV.handler(app, port)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        def ask(method, path, host, body=None):
            cx = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            cx.putrequest(method, path, skip_host=True)
            cx.putheader("Host", host)
            data = (body or "").encode()
            if method == "POST":
                cx.putheader("Content-Type", "application/x-www-form-urlencoded")
                cx.putheader("Content-Length", str(len(data)))
            cx.endheaders(data if method == "POST" else None)
            res = cx.getresponse()
            out = (res.status, res.getheader("Content-Security-Policy"), res.read().decode())
            cx.close()
            return out
        home = ask("GET", "/", f"127.0.0.1:{port}")
        other = ask("GET", "/", "attacker.example")
        rebound = ask("POST", "/react", f"evil.test:{port}", f"token={app.token}&store=w&target={d}&agree=10")
        no_token = ask("POST", "/react", f"localhost:{port}", f"store=w&target={d}&agree=10")
    finally:
        srv.shutdown()
        srv.server_close()
    check("SV5 the server answers only on its own host (a rebound name is refused, 421) and refuses a POST without the "
          "run's token (403); every page carries a content security policy",
          home[0] == 200 and "default-src 'none'" in (home[1] or "") and "script-src 'none'" in (home[1] or "") and other[0] == 421 and rebound[0] == 421
          and no_token[0] == 403 and "Не підписано" in no_token[2] and "token" in no_token[2],
          (home[0], other[0], rebound[0], no_token[0]))
    me = Repo()                                     # the reader's own store: the same keys, its own records
    both = SV.Space({"w": str(r.root), "me": str(me.root)})
    reader = SV.App(both, "bob", KEYS["bob"], mine="me")
    before_w = len(both.report("w")["_recs"])
    got = reader.react({"token": reader.token, "store": "w", "target": d, "agree": "55", "note": "from my own store"})
    in_me = [x for x in both.report("me")["_recs"].values() if x["body"].get("verdict") == "react"]
    shown = reader.page_lineage("w", d)[1]
    check("SV7 with a store of the reader's own (--mine), a reaction on a record of another store is filed there, "
          "leaving that store as it was, and the record's page shows it under its version, naming where it lives",
          got[0] == 303 and len(both.report("w")["_recs"]) == before_w and len(in_me) == 1
          and in_me[0]["body"]["target"] == d and "відреагував (у me)" in shown and "from my own store" in shown,
          (got, len(in_me)))
    w = SV.waiting(rep, "bob")
    check("SV6 what waits for an actor is the frontier under the store's own profile: bob, roadmap/acceptor, owes the "
          "closure his attest until he filed it", isinstance(w["roles"], list) and "roadmap/acceptor" in w["roles"], w)


def lens_cases():
    """Lenses (warrant_agent/lens.py): a lineage page's layout is a `lens@1` record, applied only when the reader
    adopted it; a card is data the interpreter knows or UNSUPPORTED; no lens decides the floor (state, reliance, every
    counted challenge that stands, UNATTESTED, which lens drew the page)."""
    from warrant_agent import lens as LZ
    from warrant_agent import serve as SV
    r = Repo()
    r.put("alice", "schema", LZ.SCHEMA)
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "the task", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "the task", "serves": [],
                                           "established": ["it holds"], "residual": ["one gap"]}, lineage=o)
    c = r.put("bob", "challenge", {"target": d, "statement": "a counted counterexample"}, refs=[d])
    def lens(name, card, actor="carol"):
        return r.put(actor, "entity", {"state": "active", "name": name, "applies": "obligation@1", "card": card}, "lens@1")
    fields = [{"path": "statement", "label": "", "as": "text"}, {"path": "established", "label": "Встановлено", "as": "list"}]
    nested = lens("nested card", {"layout": "nested", "fields": fields})
    flat = lens("flat stream", {"layout": "flat", "fields": fields[:1], "order": "oldest"})
    bare = lens("hides everything", {"layout": "nested", "fields": [], "activity": "hidden"})
    bad = lens("<i>bad</i> lens", {"layout": "nested", "fields": [], "script": "alert(1)"})
    shaped = r.put("eve", "attest", {"target": o, "verdict": "note", "state": "active", "name": "looks like a lens",
                                     "applies": "obligation@1", "card": {"layout": "nested", "fields": []}}, refs=[o])
    space = SV.Space({"w": str(r.root)})
    dave = SV.App(space, "dave", KEYS["dave"])
    look = SV.App(space, reader="dave")                      # dave reads; the app that signs for him draws forms too
    view = lambda app, q=None: app.page_lineage("w", o, q or {})[1]
    first = view(look)
    clock = RP.time                 # both adoptions in one second, always: the chain, not the clock, must order them
    RP.time = type("Clock", (), {"time": staticmethod(lambda: 1_700_000_000)})
    try:
        a1 = dave.adopt({"token": dave.token, "store": "w", "target": nested})
        with_nested = view(look)
        r.t += 10
        a2 = dave.adopt({"token": dave.token, "store": "w", "target": flat})
        with_flat = view(look)
    finally:
        RP.time = clock
    ats = {x["at"] for x in RP.Repo(r.root).report()["_recs"].values() if x["actor"] == "dave" and x["body"].get("verdict") == "adopt"}
    check("LN1 the reader's adopted lens draws the page, the latest adoption winning: built-in, then the nested card, "
          "then the flat stream, with no change of code; the two adoptions share one second, so the chain orders them",
          "лінза «вбудована»" in first and "лінза «nested card»" in with_nested and "лінза «flat stream»" in with_flat
          and with_nested.count('class="card"') == 2 and with_flat.count('class="card"') == 0 and a1[0] == a2[0] == 303
          and len(ats) == 1, (a1, a2, ats))
    eve = SV.App(space, "eve", KEYS["eve"])
    r.t += 10
    e1 = eve.adopt({"token": eve.token, "store": "w", "target": bare})
    lens("newer, adopted by nobody", {"layout": "nested", "fields": []})
    try:                                     # a crash here is this case's FAIL, never a missing line (a mutant survives that)
        mine, evs = view(look), view(SV.App(space, reader="eve"))
    except Exception as ex:
        mine, evs = f"crashed: {type(ex).__name__}: {ex}", ""
    check("LN2 a lens another reader adopted, or a newer one nobody adopted, is not applied: the page is the reader's",
          e1[0] == 303 and "лінза «flat stream»" in mine and "лінза «hides everything»" in evs
          and "лінза «newer, adopted by nobody»" not in mine and "лінза «hides everything»" not in mine, (e1, mine[:200]))
    unsupported = view(look, {"lens": bad})
    check("LN3 a card the interpreter does not know is UNSUPPORTED: the built-in draws the page and says why; the lens "
          "cannot be adopted; its text is data",
          "не підтримується" in unsupported and "лінза «вбудована»" in unsupported and "<i>bad" not in view(SV.App(space), {"lens": bad})
          and dave.adopt({"token": dave.token, "store": "w", "target": bad})[0] == 400
          and dave.adopt({"token": dave.token, "store": "w", "target": d})[0] == 400
          and dave.adopt({"token": dave.token, "store": "w", "target": shaped})[0] == 400, unsupported[:0])
    hidden = view(look, {"lens": bare})
    check("LN4 the floor: a lens that shows no member and hides the activity still shows the state, the reliance, the "
          "counted challenge that stands with its statement, UNATTESTED and its own name",
          "a counted counterexample" in hidden and "заперечень, що стоять: <b data-floor=\"standing\">1</b>" in hidden and "UNATTESTED" in hidden
          and "лінза «hides everything»" in hidden and "заперечив" not in hidden and "it holds" not in hidden
          and SV.standing(space.report("w"), SV.lineage(space.report("w"), o)) == [(c, d)], hidden[:0])
    reader = SV.App(space, reader="dave")
    by_portal, by_adoption = view(reader, {"lens": flat}), view(reader)
    other = view(reader, {"lens": nested})
    foot_of = lambda h: h[h.index("<footer>"):]
    check("LN5 a portal: a page naming its lens is byte-identical to the page the adoption of that lens draws, and "
          "its footer's lens differs from another lens's", by_portal == by_adoption and foot_of(other) != foot_of(by_portal)
          and f"?lens={flat}" in by_portal, foot_of(by_portal)[:120])
    # Lens objections, a lens for every schema, and the comparison of two lenses on one page
    r.t += 10
    obj = r.put("eve", "challenge", {"target": flat, "statement": "the flat stream hides which version an event was about"}, refs=[flat])
    drawn = view(look)
    check("LN7 a challenge against the lens that draws a page is shown on that page, counted or not (a lens has no guard)",
          "заперечень на цю лінзу: 1" in drawn and "the flat stream hides which version" in drawn
          and "заперечень на цю лінзу" not in view(look, {"lens": "builtin"}), obj)
    r.t += 10
    star = r.put("carol", "entity", {"state": "active", "name": "every schema", "applies": "*",
                                     "card": {"layout": "nested", "fields": fields}}, "lens@1")
    dave.adopt({"token": dave.token, "store": "w", "target": star})
    check("LN8 a lens that applies to `*` draws any schema once adopted", "лінза «every schema»" in view(look), star)
    cmp_ = view(look, {"lens": nested, "vs": bare})
    only_nested, only_bare = LZ.diff(SV.lineage(space.report("w"), o), LZ.lenses(space.report("w"))[nested],
                                     LZ.lenses(space.report("w"))[bare])
    check("LN9 the comparison of two lenses names what one shows of the page and the other does not: the nested card "
          "shows the statements, the established and the challenge that the bare lens hides; the bare shows nothing more",
          (d, "established") in only_nested and (c, "") in only_nested and only_bare == []
          and f"Показує лише «nested card»: {len(only_nested)}" in cmp_ and "Показує лише «hides everything»: 0" in cmp_
          and f"vs={bare}" in view(look, {"lens": nested}), (only_nested, only_bare))
    # Codex's observer pack OBS-P01: a reader adopts a lens of a store it cannot write to, in its own store.
    me = Repo()
    pub_bytes = r.store.file.read_bytes()
    two = SV.Space({"w": str(r.root), "me": str(me.root)})
    reader = SV.App(two, "bob", KEYS["bob"], mine="me")              # bob has adopted nothing anywhere
    got = reader.adopt({"token": reader.token, "store": "w", "target": nested})
    mine_adopts = [x for x in two.report("me")["_recs"].values() if x["body"].get("verdict") == "adopt"]
    check("LN10 a reader adopts a lens of another store in its own: the lens's store is unchanged, the adoption is the "
          "reader's record, and it draws the reader's pages", got[0] == 303 and r.store.file.read_bytes() == pub_bytes
          and [x["body"]["target"] for x in mine_adopts] == [nested]
          and "лінза «nested card»" in SV.App(two, reader="bob").page_lineage("w", o, {})[1], (got, len(mine_adopts)))
    adoptions = [x for x in space.report("w")["_recs"].values() if x["body"].get("verdict") == "adopt"]
    check("LN6 an adoption is the reader's attest {verdict: adopt} on a lens version, filed only with the run's token",
          sorted(x["actor"] for x in adoptions) == ["dave", "dave", "dave", "eve"]
          and dave.adopt({"token": "x", "store": "w", "target": nested})[0] == 403
          and all(set(x["body"]) == {"target", "verdict"} for x in adoptions), adoptions)


def voices_cases():
    """Who a voice is (warrant_agent/voices.py): the keys a store's trust binds to a name, not the name. Two names on
    one key are one source; one name on two keys (two stores) is two; a record admitted unsigned is no one's voice;
    the floor counts the voices independent of the author."""
    from warrant_agent import serve as SV
    from warrant_agent import voices as VC
    r = Repo()
    r.trust["keys"]["mallory"] = [KEYS["alice"].public]                  # alice's key under a second name
    r.write_config()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "the task", "serves": []})
    r.t += 1
    puppet = r.store.append(R.record("challenge", "mallory", r.t, {"target": o, "statement": "a puppet's objection"}, refs=[o]),
                            KEYS["alice"], r.trust)
    r.put("bob", "challenge", {"target": o, "statement": "bob objects"}, refs=[o])
    x = Repo()
    x.trust["keys"]["bob"] = [KEYS["carol"].public]                      # another store's bob is carol's key
    x.write_config()
    x.t = r.t + 1
    x.store.append(R.record("challenge", "bob", x.t, {"target": o, "statement": "the other bob"}, refs=[o]), KEYS["carol"], x.trust)
    space = SV.Space({"w": str(r.root), "x": str(x.root)})
    app = SV.App(space, reader="dave")
    try:                                      # a crash is this case's FAIL, never a missing line
        page_ = app.page_lineage("w", o, {})[1]
        rep = space.report("w")
        d = app.with_elsewhere("w", SV.lineage(rep, o))
        _, notes, independent = SV.voices(rep, "w", d, SV.sources(rep, "w", d)[1])
    except Exception as ex:
        page_, notes, independent = f"crashed: {type(ex).__name__}: {ex}", [], []
    check("VO1 two names on one key are one source: the author's key under another name is not an independent voice, "
          "and the page says so", "alice = mallory: один ключ" in notes and "mallory" not in independent
          and "alice = mallory: один ключ" in page_ and puppet in rep["_recs"], (notes, independent))
    check("VO2 one name on two keys in two stores is two sources, each independent of the author: the page names the split",
          any(n.startswith("bob: 2 різні джерела (w, x)") for n in notes) and independent == ["bob"]
          and "незалежних від автора: 1" in page_, (notes, independent))
    bob_id = next(i for i, y in rep["_recs"].items() if y["actor"] == "bob" and y["kind"] == "challenge")
    unsigned = dict(rep, _basis=dict(rep["_basis"], **{bob_id: "UNSIGNED"}))
    _, notes_u, ind_u = SV.voices(unsigned, "w", SV.lineage(unsigned, o), ["bob", "mallory"])
    check("VO3 a record its store admitted unsigned is no one's key: never an independent voice, and named as keyless",
          ind_u == [] and any(n.startswith("bob (у w): без ключа") for n in notes_u), (notes_u, ind_u))
    gs2 = VC.groups([("a", "s", {"k"}), ("b", "t", {"k", "m"}), ("c", "u", {"m"}), ("d", "s", set()), ("d", "s", set())])
    check("VO4 voices join through any shared key, transitively; keyless voices of one name in one store are one",
          [g["names"] for g in gs2] == [["a", "b", "c"], ["d"]] and gs2[0]["keys"] == ["k", "m"], gs2)


def contract_cases():
    """A lens's contract (warrant_agent/contract.py): what a card promises of a lineage page (each declared member
    that has a value, the activity it shows) and what the floor promises are read back from the marks of the page
    drawn; a broken promise is named on the page and by the command, which anyone with the same store replays."""
    from warrant_agent import contract as CT
    from warrant_agent import lens as LZ
    from warrant_agent import serve as SV
    r = Repo()
    r.put("alice", "schema", LZ.SCHEMA)
    long = "the task, said at length: " + "x" * 420
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": long, "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "the task", "serves": [],
                                           "established": ["it holds"], "residual": ["one gap"]}, lineage=o)
    c = r.put("bob", "challenge", {"target": d, "statement": "a counted counterexample"}, refs=[d])
    odd = [{"path": "statement", "label": "", "as": "list"}, {"path": "established", "label": "E", "as": "text"},
           {"path": "residual", "label": "R", "as": "list"}]
    nested = r.put("carol", "entity", {"state": "active", "name": "forms it guessed", "applies": "*",
                                       "card": {"layout": "nested", "fields": odd}}, "lens@1")
    flat = r.put("carol", "entity", {"state": "active", "name": "flat", "applies": "*",
                                     "card": {"layout": "flat", "fields": odd, "order": "oldest"}}, "lens@1")
    space = SV.Space({"w": str(r.root)})
    app = SV.App(space, reader="dave")
    rep = space.report("w")
    want = CT.promise(SV.lineage(rep, o), LZ.card_of(LZ.lenses(rep)[nested]), SV.standing(rep, SV.lineage(rep, o)))
    kept = {}
    for name, lid in (("builtin", "builtin"), ("nested", nested), ("flat", flat)):
        page = app.page_lineage("w", o, {"lens": lid})[1]
        kept[name] = (app.last_contract["broken"], "не тримає контракт" in page)
    check("KC1 the renderer keeps every lens's contract: a member drawn in a form other than the card's `as`, the "
          "root's statement cut in the heading (so drawn in its card), the activity and the floor, under the built-in, "
          "a nested and a flat lens", all(v == ([], False) for v in kept.values())
          and {(o, "statement"), (d, "statement"), (d, "established"), (d, "residual"), (c, "")} <= want[0]
          and want[1] == set(CT.FLOOR) and want[2] == {c}, kept)
    real = SV.on_html
    SV.on_html = lambda rep_, x: "" if x["id"] == c else real(rep_, x)      # a renderer that drops one challenge
    try:
        page = app.page_lineage("w", o, {"lens": nested})[1]
        broken = app.last_contract["broken"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = CT.main([r.root.name, o, "--lens", nested, "--root", str(r.root), "--reader", "dave"])
    except Exception as ex:                   # a crash is this case's FAIL, never a missing line
        page, broken, code, out = f"crashed: {type(ex).__name__}: {ex}", None, None, io.StringIO()
    finally:
        SV.on_html = real
    check("KC2 a renderer that drops a challenge the lens shows breaks the contract: the page names it and the command "
          "replays it (exit 1), while the floor still counts it", broken == [("visible", (c, ""))]
          and "сторінка не тримає контракт лінзи: 1" in page and code == 1 and '"kept": false' in out.getvalue()
          and "заперечень, що стоять: <b data-floor=\"standing\">1</b>" in page, (broken, code, page[:0]))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = CT.main([r.root.name, o, "--root", str(r.root)])
    err = io.StringIO()
    try:                                      # a crash is this case's FAIL, never a missing line
        with contextlib.redirect_stdout(err):
            missing = CT.main(["no-such-store", o, "--root", str(r.root)])
    except Exception as ex:
        missing = f"crashed: {type(ex).__name__}"
    check("KC3 the command on a page that keeps its contract: exit 0; on a store it does not read: exit 2, named",
          code == 0 and '"kept": true' in out.getvalue() and missing == 2 and "no-such-store" in err.getvalue(), out.getvalue()[:200])



def page_contract_cases():
    """The map's and the feed's contracts (warrant_agent/contract.py): the map draws every node of the lineage or
    names how many it folded; the feed draws the newest records of its scope and names, with how many, what it leaves
    out (automatic actors, migration records, past the limit) and every store it could not read. The promise is
    computed from the records, so a renderer that drops one is caught, on the page and by the command."""
    from warrant_agent import contract as CT
    from warrant_agent import scene as SC
    from warrant_agent import serve as SV
    r = Repo()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "the task", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "the task", "serves": []}, lineage=o)
    c = r.put("bob", "challenge", {"target": d, "statement": "a counterexample"}, refs=[d])
    a = r.attest("carol", d)
    gone = r.home / "not-a-store"
    gone.mkdir()
    space = SV.Space({"w": str(r.root), "gone": str(gone)})
    app = SV.App(space, reader="dave")
    keep, real, fsth, realn = (SV.MACHINES, SV.App.FEED_LIMIT), SV.item, SV.feed_scope_html, SC._node
    SV.MACHINES, SV.App.FEED_LIMIT = ("carol",), 3        # carol signs by program; the feed keeps three records
    try:
        h = app.page_feed({})
        kept = app.last_feed_contract
        want = CT.feed_promise(app.reports(), limit=3)
        total = len(space.report("w")["_recs"])
        SV.item = lambda store, x, show_store=True: "" if x["id"] == c else real(store, x, show_store)
        dropped = (app.page_feed({}), app.last_feed_contract)
        SV.item = real
        SV.feed_scope_html = lambda store, actor, omitted, unread: fsth(store, actor, {}, [])   # says nothing is left out
        app.page_feed({})
        SV.feed_scope_html = fsth
        broke_hidden = app.last_feed_contract
        mine = app.page_feed({"actor": "carol", "machines": "1"})
        kept_mine = app.last_feed_contract
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = CT.main(["--feed", "--root", str(r.root)])
    except Exception as ex:                   # a crash is this case's FAIL, never a missing line
        h = dropped = mine = f"crashed: {type(ex).__name__}: {ex}"
        kept = broke_hidden = kept_mine = want = code = None
        out = io.StringIO()
    finally:
        SV.item, SV.feed_scope_html = real, fsth
        SV.MACHINES, SV.App.FEED_LIMIT = keep
    check("FC1 the feed keeps its contract and names what it leaves out, with how many: the automatic actor's record, "
          "those past the limit, the store it could not read; one actor's feed names its scope",
          kept == [] and 'data-omit="machines 1"' in h and f'data-omit="limit {total - 1 - 3}"' in h
          and 'data-unread="gone"' in h and a not in h and len(want[0]) == 3 and want[2] == {"gone"}
          and kept_mine == [] and f'data-r="{a} w"' in mine and "лише <b>carol</b>" in mine
          and code == 0 and '"kept": true' in out.getvalue(), (kept, kept_mine, code))
    check("FC2 a feed that drops a record, or does not say what it left out and which store it could not read, breaks "
          "its contract: named on the page",
          isinstance(dropped, tuple) and dropped[1] == [("record", f"w {c}")]
          and "стрічка не тримає свій контракт: 1" in dropped[0]
          and broke_hidden == [("omit", f"limit {total - 1 - 3}"), ("omit", "machines 1"), ("unread", "gone")], (dropped[1:] if isinstance(dropped, tuple) else dropped, broke_hidden))
    small = Repo()                            # Codex finding F1 on #345: a count the page invents where none is left out
    small.entity("alice", "obligation@1", {"state": "open", "statement": "task", "serves": []})
    sapp = SV.App(SV.Space({"w": str(small.root)}))
    sapp.page_feed({"machines": "1"})
    control = sapp.last_feed_contract
    try:
        SV.feed_scope_html = lambda store, actor, omitted, unread: fsth(store, actor, dict(omitted, limit=999), unread)
        invented = sapp.page_feed({"machines": "1"})
        broke_invented = sapp.last_feed_contract
    except Exception as ex:
        invented, broke_invented = f"crashed: {type(ex).__name__}: {ex}", None
    finally:
        SV.feed_scope_html = fsth
    check("FC3 a feed that says it left records out where none were breaks its contract: the counts are compared both "
          "ways, a reason with nothing left out counting as zero (Codex finding F1 on #345)",
          control == [] and broke_invented == [("omit", "limit 0")] and "стрічка не тримає свій контракт" in invented,
          (control, broke_invented))
    rep = space.report("w")
    page_d = SV.lineage(rep, o)
    nodes = SC.nodes_of(rep, page_d)
    full = app.page_scene("w", o)[1]
    full_kept = app.last_contract["broken"]
    keep_n = SC.MAX_NODES
    SC.MAX_NODES = 2
    try:
        folded = app.page_scene("w", o)[1]
        folded_kept = app.last_contract["broken"]
        SC.MAX_NODES = keep_n
        SC._node = lambda n, pos, b, store, describe: "" if n["id"] == d else realn(n, pos, b, store, describe)
        lost = app.page_scene("w", o)[1]
        lost_broken = app.last_contract["broken"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mcode = CT.main([r.root.name, o, "--map", "--root", str(r.root)])
    except Exception as ex:
        folded = lost = f"crashed: {type(ex).__name__}: {ex}"
        folded_kept = lost_broken = mcode = None
    finally:
        SC.MAX_NODES = keep_n
        SC._node = realn
    from warrant_agent import lens as LZ
    r.put("alice", "schema", LZ.SCHEMA)
    flens = r.put("alice", "entity", {"state": "active", "name": "time map", "applies": "obligation@1",
                                      "card": {"layout": "nested", "fields": [], "scene": {"x": "time"}}}, "lens@1")
    app.page_scene("w", o, {"lens": "builtin", "vs": flens})
    pair_control = app.last_contract["broken"]
    realsvg, calls = SC.svg, []

    def drop_first(*args):                    # Codex finding F2 on #345: the first map loses a node, the second has it
        drawn_, legend_ = realsvg(*args)
        calls.append(1)
        return (drawn_.replace(f'data-n="{d}"', 'data-x=""') if len(calls) in (1, 5) else drawn_), legend_
    try:
        SC.svg = drop_first
        _, pair = app.page_scene("w", o, {"lens": "builtin", "vs": flens})
        pair_broken = app.last_contract["broken"]
        calls.append(1)                       # now the second map loses it
        app.page_scene("w", o, {"lens": "builtin", "vs": flens})
        second_broken = app.last_contract["broken"]
    except Exception as ex:
        pair, pair_broken, second_broken = f"crashed: {type(ex).__name__}: {ex}", None, None
    finally:
        SC.svg = realsvg
    check("MC3 beside a second map, a node missing from the first is still a breach: each map is read alone (Codex "
          "finding F2 on #345)", pair_control == [] and pair_broken == [("node", d)] and len(calls) == 5
          and "карта не тримає контракт: 1" in pair and pair.count('data-map=') == 2
          and second_broken == [("map2 node", d)], (pair_control, pair_broken, second_broken))
    check("MC1 the map keeps its contract: every node drawn, or the fold named with its count; the floor and the "
          "standing challenge above it", full_kept == [] and all(f'data-n="{n["id"]}"' in full for n in nodes)
          and folded_kept == [] and f'data-folded="{len(nodes) - 2}"' in folded and 'data-c="' + c + '"' in folded,
          (full_kept, folded_kept))
    check("MC2 a map that drops a node it neither draws nor folds breaks its contract: named on the page and by the "
          "command (exit 1)", lost_broken == [("node", d)] and "карта не тримає контракт: 1" in lost and mcode == 1,
          (lost_broken, mcode))

def changes_cases():
    """What changed for a reader (warrant_agent/changes.py): the past is the set of records the reader marked as
    seen, assessed by the same engine; a lineage is listed only when its floor or what the reader's lens draws of it
    differs, with the witness; new records that change nothing the reader sees are counted, not listed."""
    from warrant_agent import changes as CH
    from warrant_agent import lens as LZ
    from warrant_agent import serve as SV
    r = Repo()
    r.put("alice", "schema", LZ.SCHEMA)
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "the task", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "the task", "serves": []}, lineage=o)
    bare = r.put("carol", "entity", {"state": "active", "name": "hides activity", "applies": "*",
                                     "card": {"layout": "nested", "fields": [], "activity": "hidden"}}, "lens@1")
    marks = CH.Marks(r.home / "seen.json")
    space = SV.Space({"w": str(r.root)})
    app = SV.App(space, "dave", KEYS["dave"], marks=marks)
    at_mark = r.store.snapshot().digest
    refused = app.seen({"token": "x"})[0]
    code = app.seen({"token": app.token})[0]
    quiet = app.page_changes({})
    past, marked = app.past_report("w", r.store.snapshot())
    check("CH1 marking a look keeps the ids of every record each store holds; the past it reads back is that store "
          "exactly (its snapshot digest), and with nothing new the page says nothing changed",
          refused == 403 and code == 303 and marked and past["snapshot"] == at_mark and "Нічого не змінилось" in quiet,
          (refused, code, marked))
    r.t += 10
    note = r.put("eve", "attest", {"target": d, "verdict": "note"}, refs=[d])
    fresh = set(space.report("w")["_recs"]) - set(past["_recs"])
    rows, acc = CH.delta(SV, past, space.report("w"), lambda s: LZ.card_of(LZ.BUILTIN))
    rows_h, acc_h = CH.delta(SV, past, space.report("w"), lambda s: LZ.card_of(LZ.lenses(space.report("w"))[bare]))
    n, n_h = len(fresh - acc), len(fresh - acc_h)            # the new records that change nothing the reader sees
    check("CH2 a new attest that moves nothing in the floor is a change under the built-in lens (it draws the "
          "activity), with the attest as witness, and no change under a lens that hides the activity: counted, not listed",
          [x["lineage"] for x in rows] == [o] and (note, "") in rows[0]["appeared"] and n == 0
          and rows_h == [] and n_h == 1, (rows, n, rows_h, n_h))
    r.t += 10
    c = r.put("bob", "challenge", {"target": d, "statement": "counted, and it stands"}, refs=[d])
    rows_h, _ = CH.delta(SV, past, space.report("w"), lambda s: LZ.card_of(LZ.lenses(space.report("w"))[bare]))
    page_ = SV.App(space, reader="dave", marks=marks).page_changes({})      # a fresh run: the past is rebuilt from the mark
    check("CH3 a counted challenge that stands moves the floor, which no lens hides: the lineage is listed under the "
          "hiding lens too, and the page names the move", [x["lineage"] for x in rows_h] == [o]
          and rows_h[0]["floor_after"]["standing"] == [(c, d)] and "заперечень, що стоять: 0 → 1" in page_
          and "counted, and it stands" in page_, rows_h)


    # Codex review of #328 (2026-11-11): a page read other stores its footer did not name; /changes did not see a
    # reaction filed elsewhere; a lens diff saw presence only; an explicit --mine not read fell back silently.
    me = Repo()
    two = SV.Space({"w": str(r.root), "me": str(me.root)})
    bob = SV.App(two, "bob", KEYS["bob"], marks=CH.Marks(me.home / "seen.json"), mine="me")
    foot_of = lambda h: h[h.index("<footer>"):]
    p1 = foot_of(bob.page_lineage("w", o)[1])
    bob.seen({"token": bob.token})
    w_before = len(two.report("w")["_recs"])
    filed = bob.react({"token": bob.token, "store": "w", "target": d, "agree": "-30", "note": "seen from my own store"})
    p2 = foot_of(bob.page_lineage("w", o)[1])
    check("CH4 a page reads every store it draws from: a reaction filed in the reader's own store leaves the record's "
          "store as it was, yet the page's lens changes and its footer names the other stores read",
          filed[0] == 303 and len(two.report("w")["_recs"]) == w_before and p1 != p2 and "і ще 1 сховищ" in p2, (filed, p1, p2))
    seen_page = SV.App(two, reader="bob", marks=CH.Marks(me.home / "seen.json")).page_changes({})
    check("CH5 /changes sees a reaction filed in another store: the record's lineage is listed with that reaction as "
          "its witness, and the reaction is not counted among the records that changed nothing",
          "seen from my own store" in seen_page and "відреагував на (у me)" in seen_page
          and "не змінили нічого, що ти бачиш: 0" in seen_page, __import__("re").sub("<[^>]+>", " ", seen_page[seen_page.find("</form>"):])[:600])
    lone = r.entity("alice", "obligation@1", {"state": "open", "statement": "nobody else spoke", "serves": []})
    page_o, page_lone = bob.page_lineage("w", o)[1], bob.page_lineage("w", lone)[1]
    check("SV8 the floor names who stands behind a lineage: its authors, every other actor who filed on it here or in "
          "another store read, and how many stores; a lineage only its author spoke about says so, under any lens",
          "автор alice" in page_o and "висловились:" in page_o and "bob" in page_o.split("висловились:")[1][:80]
          and "сховищ: 2" in page_o and "лише автор" in page_lone and "сховищ: 1" in page_lone
          and "лише автор" in bob.page_lineage("w", lone, {"lens": "builtin"})[1], page_lone[:0])
    guard_d = {k: two.report("w")["versions"][d][k] for k in ("guard", "accepted_by")}
    read_d = bob.read({"token": bob.token, "store": "w", "target": d, "lens": "builtin"})
    read_lone = bob.read({"token": bob.token, "store": "w", "target": lone, "lens": "builtin"})
    bad_lens = bob.read({"token": bob.token, "store": "w", "target": lone, "lens": "<script>"})
    views = [x for x in two.report("me")["_recs"].values() if x["body"].get("verdict") == "seen"]
    after_read = bob.page_lineage("w", lone)[1]
    newer = r.entity("alice", "obligation@1", {"state": "open", "statement": "nobody else spoke, again", "serves": []}, lineage=lone)
    behind = bob.page_lineage("w", lone)[1]
    bob.read({"token": bob.token, "store": "w", "target": newer, "lens": "builtin"})
    caught_up = bob.page_lineage("w", lone)[1]
    check("SV9 a view is the reader's signed word that they saw a version, under which lens, at which root of its store: "
          "filed in the reader's own store, it credits nothing; the floor counts who saw apart from who spoke, so a "
          "silence after a view is not an empty one, and tells the reader which version they saw last",
          read_d[0] == read_lone[0] == 303 and bad_lens[0] == 400 and len(views) == 2
          and {x["body"]["target"] for x in views} == {d, lone}
          and all(x["body"]["lens"] == "builtin" and len(x["body"]["root"]) == 64 for x in views)
          and {k: two.report("w")["versions"][d][k] for k in ("guard", "accepted_by")} == guard_d
          and "бачили 1, і ніхто не прийняв і не заперечив" in after_read and "ти бачив останню версію" in after_read
          and "ти бачив версію 1 з 2" in behind and "ти бачив останню версію" in caught_up
          and newer in two.report("w")["_recs"], (read_d, read_lone, bad_lens, len(views)))
    lost = SV.App(two, "bob", KEYS["bob"], mine="nowhere")
    w_now, me_now = len(two.report("w")["_recs"]), len(two.report("me")["_recs"])
    try:                                   # a crash is this case's FAIL, never a missing line
        refused = lost.react({"token": lost.token, "store": "w", "target": d, "agree": "10"})
    except Exception as ex:
        refused = (500, f"crashed: {type(ex).__name__}")
    check("CH6 a reader's own store that is not read refuses the reaction and files nothing anywhere (fail closed)",
          refused[0] == 400 and "nothing is filed" in refused[1] and len(two.report("w")["_recs"]) == w_now
          and len(two.report("me")["_recs"]) == me_now, refused)
    a = {"state": "active", "name": "a", "applies": "*", "card": {"layout": "nested", "fields": [
        {"path": "statement", "label": "Що", "as": "text"}, {"path": "residual", "label": "Залишки", "as": "list"}]}}
    b = {"state": "active", "name": "b", "applies": "*", "card": {"layout": "flat", "order": "oldest", "fields": [
        {"path": "residual", "label": "", "as": "count"}, {"path": "statement", "label": "Що", "as": "text"}]}}
    moves = {w for w, _, _ in LZ.presentation(a, b)}
    check("CH7 two lenses that show the same members can still draw them differently: the comparison names the layout, "
          "the order of versions and of members, and each changed label and form",
          moves == {"layout", "order", "порядок полів", "residual.label", "residual.as"}
          and LZ.diff(SV.lineage(two.report("w"), o), a, b)[0] == [] and LZ.presentation(a, a) == [], sorted(moves))

def scene_cases():
    """Scenes (warrant_agent/scene.py): a lineage drawn as a map whose every channel is bound to a named field; the
    same page gives the same SVG; no scene hides a kind, shrinks a standing challenge, drops the legend or folds
    nodes away unnamed; record text is data."""
    from warrant_agent import lens as LZ
    from warrant_agent import scene as SC
    from warrant_agent import serve as SV
    r = Repo()
    r.put("alice", "schema", LZ.SCHEMA)
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "<script>alert(1)</script> map", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "<script>alert(1)</script> map", "serves": []}, lineage=o)
    for a in ("carol", "dave", "eve"):
        r.put(a, "attest", {"target": d, "verdict": "note"}, refs=[d])
    c = r.put("bob", "challenge", {"target": d, "statement": "counted, stands"}, refs=[d])
    late = r.put("eve", "attest", {"target": o, "verdict": "note"}, refs=[o])      # on the first version, filed last
    def lens(name, scene, fields=()):
        return r.put("carol", "entity", {"state": "active", "name": name, "applies": "*",
                                         "card": {"layout": "nested", "fields": list(fields), "scene": scene}}, "lens@1")
    by_time = lens("by time", {"x": "time", "y": "version", "size": "attests", "color": "actor", "shape": "none"})
    bad = lens("bad scene", {"x": "force-directed"})
    space = SV.Space({"w": str(r.root)})
    app = SV.App(space, reader="dave")
    one, two = app.page_scene("w", o)[1], app.page_scene("w", o)[1]
    page_d = SV.lineage(space.report("w"), o)
    nodes = SC.nodes_of(space.report("w"), page_d)
    check("SC1 the same page gives the same map, byte for byte; every node is a portal to its record's page; the map "
          "holds no script", one == two and "<script" not in one.lower() and len(nodes) == 7
          and all(f'href="/l/w/{n["id"]}"' in one for n in nodes), len(nodes))
    pos, _ = SC.layout(nodes, SC.bindings({"scene": {"size": "attests"}}))
    check("SC2 the floor: a counted challenge that stands is never drawn smaller than what it stands against, whatever "
          "the size channel says (attests makes the version large)", pos[c][2] >= pos[d][2] > SC.R, (pos[c], pos[d]))
    drawn, legend = SC.svg(space.report("w"), "w", page_d, LZ.card_of(LZ.lenses(space.report("w"))[by_time]), lambda x: x)
    check("SC3 the floor: under colour by actor and no shapes every node still carries its kind's glyph, and the legend "
          "names every binding", all(g in drawn for g in ("◆", "✓", "✗")) and "x = час (порядок за at)" in legend
          and "color = автор" in legend and "shape = однаково" in legend, legend)
    try:                                     # a crash is this case's FAIL, never a missing line
        unsupported = app.page_scene("w", o, {"lens": bad})[1]
    except Exception as ex:
        unsupported = f"crashed: {type(ex).__name__}"
    check("SC4 a scene binding no channel knows makes the lens UNSUPPORTED: the built-in draws the map and says why",
          "не підтримується" in unsupported and "scene: x is one of" in unsupported
          and LZ.problem(LZ.lenses(space.report("w"))[bad]) is not None, unsupported[:0])
    both = app.page_scene("w", o, {"lens": "builtin", "vs": by_time})[1]
    moves, binds = SC.moved(space.report("w"), page_d, LZ.card_of(LZ.BUILTIN), LZ.card_of(LZ.lenses(space.report("w"))[by_time]))
    check("SC5 two maps side by side: the page names how many nodes moved and which bindings differ; the lens "
          "comparison names the scene's bindings too", "Дві карти" in both and f"переміщено вузлів: {len(moves)}" in both
          and moves and ("x", "order", "time") in binds and "x: order → time" in both
          and SC.layout(nodes, SC.bindings({"scene": {"x": "time"}}))[0][late][0] > SC.layout(nodes, SC.bindings({"scene": {"x": "time"}}))[0][c][0]
          and SC.layout(nodes, SC.bindings({}))[0][late][0] < SC.layout(nodes, SC.bindings({}))[0][c][0]
          and ("scene.x", "order", "time") in LZ.presentation(LZ.BUILTIN, LZ.lenses(space.report("w"))[by_time]), binds)
    keep = SC.MAX_NODES
    SC.MAX_NODES = 3
    try:
        _, small = SC.svg(space.report("w"), "w", page_d, LZ.card_of(LZ.BUILTIN), lambda x: x)
    finally:
        SC.MAX_NODES = keep
    check("SC6 a map beyond its node budget names what it folded away, with the count", f"згорнуто {len(nodes) - 3} вузлів" in small, small)
    check("SC7 record text is data on the map: a node's title is escaped", "&lt;script&gt;" in one and "<script" not in one,
          one[:0])


def fragile_cases():
    """Fragile popularity (warrant_agent/fragile.py): attention beside the objections it met, never one score; whoever
    filed a reproduced or standing challenge is named, an unreproduced uncounted objection is shown, not credited."""
    from warrant_agent import fragile as FR
    from warrant_agent import serve as SV
    r = Repo()
    def done(s):
        return r.entity("alice", "obligation@1", {"state": "done", "statement": s, "serves": []},
                        lineage=r.entity("alice", "obligation@1", {"state": "open", "statement": s, "serves": []}))
    popular, quiet = done("popular"), done("quiet")
    for a in ("bob", "dave"):
        r.put(a, "attest", {"target": popular, "verdict": "seen", "lens": "builtin", "root": "0" * 64}, refs=[popular])
    r.attest("bob", popular)
    c = r.put("eve", "challenge", {"target": popular, "statement": "one counterexample"}, refs=[popular])
    r.put("carol", "attest", {"target": c, "verdict": "reproduces", "on": popular}, refs=[c, popular])
    q = r.put("eve", "challenge", {"target": quiet, "statement": "an objection nobody reproduced"}, refs=[quiet])
    r.put("carol", "attest", {"target": q, "verdict": "reproduces", "on": popular}, refs=[q, popular])   # on another version
    space = SV.Space({"w": str(r.root)})
    found = FR.rows(SV, {"w": space.report("w")})
    top = found[0] if found else {}
    check("FR1 lineages with an objection, the most attended first: attention is who saw, accepted or reacted, the "
          "authors aside, and a challenge is no attention", [x["title"] for x in found] == ["popular", "quiet"]
          and top["attention"]["saw"] == {"bob", "dave"} and top["attention"]["accepted"] == {"bob"}
          and len(top["attention"]["all"]) == 2 and "eve" not in top["attention"]["all"], found)
    who = FR.finders(found)
    check("FR2 the finders: a challenge reproduced on its own target is credited, with the attention of what it held "
          "against; an objection nobody reproduced and no role counts is shown, not credited",
          [a for a, _ in who] == ["eve"] and [(rr["title"], n) for rr, n in who[0][1]] == [("popular", 1)]
          and any(ch["id"] == q and not FR.credited(ch) for x in found for ch in x["challenges"]), who)
    page_ = SV.App(space).page_fragile()
    check("FR3 the page sets attention beside each objection and its fate, adds nothing up, and its record text is data",
          "увага: 2 (бачили 2, прийняли 1, відреагували 0)" in page_ and "відтворене" in page_ and "не зараховане" in page_
          and "Хто вказав" in page_ and "eve" in page_.split("Хто вказав")[1], page_[:0])


def whatif_cases():
    """What-if (warrant_agent/view.py, after minds' what_if): a store without some records, assessed by the same engine
    on a candidate; every lineage whose view changes is named with its witness; equal consequences, equal digest."""
    from warrant_agent import lens as LZ
    from warrant_agent import serve as SV
    from warrant_agent import view as VW
    r = Repo()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "the task", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "the task", "serves": []}, lineage=o)
    c = r.put("bob", "challenge", {"target": d, "statement": "counted, it stands"}, refs=[d])
    other = r.entity("carol", "obligation@1", {"state": "open", "statement": "untouched", "serves": []})
    space = SV.Space({"w": str(r.root)})
    app = SV.App(space)
    lines_before = len(r.store.lines())
    no_ch = app.hypothesis("w", "challenges")
    no_bob = app.hypothesis("w", "actor:bob")
    no_carol = app.hypothesis("w", "actor:carol")
    row = (no_ch or {"rows": [{}]})["rows"][0] if no_ch and no_ch["rows"] else {}
    check("WI1 a hypothesis is assessed on a candidate and files nothing: without its challenges the lineage it stood "
          "against is named, its floor before (none standing) and after (the challenge stands)",
          no_ch["dropped"] == 1 and [x["lineage"] for x in no_ch["rows"]] == [o] and row["floor_before"]["standing"] == []
          and row["floor_after"]["standing"] == [(c, d)] and len(r.store.lines()) == lines_before
          and other not in [x["lineage"] for x in no_ch["rows"]], no_ch)
    check("WI2 equal consequences give an equal digest whatever produced them (no challenge, or no record of the one who "
          "filed it), and other consequences another", no_ch["digest"] == no_bob["digest"] and no_carol["digest"] != no_ch["digest"]
          and VW.dropped(space.report("w"), "nothing") is None, (no_ch["digest"], no_bob["digest"], no_carol["digest"]))
    page_d = SV.lineage(space.report("w"), o)
    kept = VW.observe(SV, space.report("w"), page_d, LZ.card_of(LZ.BUILTIN), keep=lambda x: x["id"] != c)
    check("WI3 a view that keeps only some activity drops what it does not keep, a challenge that no longer stands included; "
          "the page says what follows and its direction", kept["floor"]["standing"] == [] and (c, "") not in kept["visible"]
          and "від гіпотези до того, як є" in app.page_whatif({"store": "w", "without": "challenges"})[1]
          and app.page_whatif({"store": "w", "without": "nothing"})[0] == 404, kept["floor"])


def audit_cases():
    """Codex's observer pack (2026-11-11), the gaps it found: OBS-P02 the interpreter's identity, OBS-P03 what a page
    cannot see, OBS-A07 a lens changed since the mark, OBS-P11 no script at all."""
    import re as _re
    from warrant_agent import changes as CH
    from warrant_agent import lens as LZ
    from warrant_agent import serve as SV
    r = Repo()
    r.put("alice", "schema", LZ.SCHEMA)
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "the task", "serves": []})
    r.put("bob", "attest", {"target": o, "verdict": "note"}, refs=[o])
    bare = r.put("carol", "entity", {"state": "active", "name": "bare", "applies": "*",
                                     "card": {"layout": "nested", "fields": [], "activity": "hidden"}}, "lens@1")
    me = Repo()
    missing = r.home / "not-a-store"
    space = SV.Space({"w": str(r.root), "me": str(me.root), "gone": str(missing)})
    dave = SV.App(space, "dave", KEYS["dave"], marks=CH.Marks(r.home / "seen.json"))
    loaded = {m.split(".")[1] for m in sys.modules if m.startswith("warrant_agent.")}
    names = {p.stem for p in SV.ADAPTER_FILES}
    page_ = dave.page_lineage("w", o)[1]
    check("AU1 a page's lens names the whole interpreter (every module of warrant_agent it runs, by bytes) and every "
          "other store it read with that store's trust and profile (OBS-P02)", loaded <= names and "lens" in names
          and space.report("me")["trust"] in page_ and space.report("me")["profile"] in page_, sorted(loaded - names))
    dave.seen({"token": dave.token})
    dave.adopt({"token": dave.token, "store": "w", "target": bare})
    hid = dave.page_lineage("w", o)[1]
    check("AU2 a page says what the reader's lens leaves out of it and which stores it could not read (OBS-P03)",
          "лінза не показує тут" not in page_ and "лінза не показує тут 2" in hid and "не прочитано сховищ: 1" in hid
          and "gone" in hid, hid[:0])
    changed = dave.page_changes({})
    check("AU3 /changes says when the reader's lens changed since the mark, and that both states are read under the "
          "lens of now (OBS-A07)", "твоя лінза змінилась відтоді" in changed and "«вбудована» → «bare»" in changed, changed[:0])
    pages = [page_, hid, changed, dave.page_feed({}), dave.page_fragile(), dave.page_scene("w", o)[1]]
    check("AU4 no page holds a script or an event handler, and the policy allows none (OBS-P11)",
          not any("<script" in h.lower() or _re.search(r"\son[a-z]+=", h) for h in pages), [h[:0] for h in pages])


def overlay_cases():
    """Overlay (warrant_agent/overlay.py, Codex 2026-11-11): three stores (a publisher's claim, a challenge it never
    took in, a replay that reproduces it), two readers with the same bytes and other rules. Each store's own verdict
    stands; each reader's is its own, named, with its own identity."""
    from warrant_agent import overlay as OV
    pub, crit, lab = Repo(), Repo(), Repo()
    o = pub.entity("alice", "obligation@1", {"state": "open", "statement": "the claim", "serves": []})
    d = pub.entity("alice", "obligation@1", {"state": "done", "statement": "the claim", "serves": []}, lineage=o)
    pub.attest("bob", d)
    c = crit.put("eve", "challenge", {"target": d, "statement": "a counterexample"}, refs=[d])
    lab.put("dave", "attest", {"target": c, "verdict": "reproduces", "on": d}, refs=[c, d])      # dave: no replayer of pub
    pub_bytes = pub.store.file.read_bytes()
    snaps = {"pub": pub.store.snapshot(), "crit": crit.store.snapshot(), "lab": lab.store.snapshot()}
    own = OV.assess({"pub": snaps["pub"]}, pub.trust, pub.profile)
    roles = lambda **extra: dict(pub.profile, roles=dict(pub.profile["roles"], **extra))
    p1 = roles(**{"roadmap/acceptor": ["bob", "eve"]})            # reader 1: eve's objection may count
    p2 = roles(replayer=[])                                        # reader 2: neither the challenger nor the replayer counts
    t1, _, _ = OV.receiver(pub.trust, p1, {n: pub.trust for n in snaps})
    r1, r2 = OV.assess(snaps, t1, p1), OV.assess(snaps, t1, p2)
    again = OV.assess(snaps, t1, p1)
    check("OV1 the publisher's store alone relies on its claim; a reader who composes the challenge's and the replay's "
          "stores under rules that count the challenger reads it CHALLENGED; the publisher's bytes are untouched",
          own["lineages"][o]["reliance"] == "ELIGIBLE" and r1["lineages"][o]["reliance"] == "CHALLENGED"
          and r1["challenges"][c]["counted"] and pub.store.file.read_bytes() == pub_bytes,
          (own["lineages"][o]["reliance"], r1["lineages"][o]["reliance"], r1["challenges"].get(c)))
    code = r1["code"]
    check("OV2 another reader with the same bytes and other rules (no role for the challenger, no trust in the replayer) "
          "reads it otherwise, and says why (the challenge is not counted); each result has its own identity, and the "
          "same inputs give the same one",
          r2["lineages"][o]["reliance"] == "ELIGIBLE" and not r2["challenges"][c]["counted"]
          and OV.identity(snaps, t1, p1, code) == OV.identity(snaps, t1, p1, again["code"])
          and OV.identity(snaps, t1, p1, code) != OV.identity(snaps, t1, p2, code)
          and OV.identity(snaps, t1, p1, code) != OV.identity({"pub": snaps["pub"]}, t1, p1, code), r2["challenges"].get(c))
    forged = dict(pub.trust, keys=dict(pub.trust["keys"], eve=[KEYS["dave"].public]))   # a store that calls dave's key eve
    reader_trust = dict(pub.trust, keys={a: k for a, k in pub.trust["keys"].items() if a != "eve"})
    t3, _, conflicts = OV.receiver(reader_trust, p2, {"pub": pub.trust, "forger": forged})     # eve holds no role in p2
    t4, _, none = OV.receiver(pub.trust, p2, {"pub": pub.trust, "forger": forged})
    check("OV3 a key binding is admitted only as the reader's own or as every source naming that actor agrees: a store "
          "that binds another key to an actor is named, and that actor is admitted from neither; the reader's own "
          "binding wins", "eve" not in t3["keys"] and [(a, w) for a, _, w in conflicts] == [("eve", "disagree")]
          and t4["keys"]["eve"] == pub.trust["keys"]["eve"] and none == [], conflicts)
    # Codex 2026-11-12 on overlay.receiver: one source "agreeing" with itself bound a role holder the reader never pinned
    pub6 = Repo()
    e = pub6.entity("alice", "obligation@1", {"state": "open", "statement": "another claim", "serves": []})
    e2 = pub6.entity("alice", "obligation@1", {"state": "done", "statement": "another claim", "serves": []}, lineage=e)
    unpinned = dict(pub.trust, keys={a: k for a, k in pub.trust["keys"].items() if a not in ("bob", "eve")})
    forger = Repo()
    forger.trust = dict(forger.trust, keys=dict(unpinned["keys"], bob=[KEYS["dave"].public], eve=[KEYS["eve"].public]))
    forger.write_config()
    forger.store.append(R.record("attest", "bob", forger.t + 1, {"target": e2, "verdict": "accept"}, refs=[e2]),
                        KEYS["dave"], forger.trust)                                   # dave's key, signing as bob
    fsnaps = {"pub": pub6.store.snapshot(), "forger": forger.store.snapshot()}
    t6, _, held = OV.receiver(unpinned, p2, {"pub": unpinned, "forger": forger.trust})
    r6 = OV.assess(fsnaps, t6, p2)
    check("OV6 a key binding for an actor the reader's own profile gives a role is admitted only from the reader's own "
          "trust: a single store binding bob (roadmap/acceptor) to another key is named, not admitted, and its forged "
          "acceptance does not settle the version; an actor with no role is still admitted when its sources agree",
          "bob" not in t6["keys"] and [(a, w) for a, _, w in held] == [("bob", "role")] and t6["keys"].get("eve") == [KEYS["eve"].public]
          and r6["lineages"][e]["state"] != "done", (held, r6["lineages"][e]["state"]))
    from warrant_agent import serve as SV
    me = Repo()
    me.profile["roles"] = dict(me.profile["roles"], replayer=["dave"])     # the reader trusts dave's replays; pub does not
    me.write_config()
    space = SV.Space({"pub": str(pub.root), "crit": str(crit.root), "lab": str(lab.root), "me": str(me.root)})
    mine_page = SV.App(space, reader="bob", mine="me").page_overlay({"store": "pub"})
    no_mine = SV.App(space, reader="bob").page_overlay({"store": "pub"})
    check("OV4 the page reads a store with the other stores under the reader's own rules (its own store's trust and "
          "roles): the lineage the publisher relies on reads CHALLENGED for this reader, with the challenge as witness "
          "and the store's verdict beside it; without a store of its own the reader is told why nothing is composed",
          mine_page[0] == 200 and "опора: ELIGIBLE → CHALLENGED" in mine_page[1] and "заперечив" in mine_page[1]
          and "у pub за його правилами → для тебе" in mine_page[1] and no_mine[0] == 400
          and pub.store.file.read_bytes() == pub_bytes, mine_page[1][:0])
    crit.entity("eve", "obligation@1", {"state": "open", "statement": "the critic own lineage", "serves": []})
    bare = Repo()
    bare.profile["roles"] = {k: v for k, v in bare.profile["roles"].items() if k != "roadmap/acceptor"}
    bare.write_config()
    space2 = SV.Space({"pub": str(pub.root), "crit": str(crit.root), "lab": str(lab.root), "bare": str(bare.root)})
    p5 = SV.App(space2, reader="bob", mine="bare").page_overlay({"store": "pub"})[1]
    check("OV5 the page lists only the store's own lineages (another store's own lineage is not news about this one), "
          "and names the roles the store's guards ask that the reader's rules give nobody",
          "the critic own lineage" not in p5 and "твої правила не називають, хто має ці ролі: roadmap/acceptor" in p5, p5[:0])


def commons_cases():
    """The commons (warrant_agent/commons.py): an agent with no key any store binds, no role and no part in a record
    says «фе» to it; every page shows the voice, no store's rules count it, a reader's rules may."""
    from warrant import commons as CM          # the core holds the commons (warrant say); warrant_agent.commons wraps it
    from warrant_agent import overlay as OV
    from warrant_agent import serve as SV
    r = Repo()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "the claim", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "the claim", "serves": []}, lineage=o)
    r.attest("bob", d)
    commons = r.home / "commons"
    w_bytes = r.store.file.read_bytes()
    stranger = CM.seed(r.home / "stranger.seed")
    filed = CM.say(commons, d, "фе: the claim ignores the cold start", stranger, at=1_900_000_000)
    from warrant.repo import Repo as RR
    rep_c = RR(str(commons)).report()
    check("CM1 an agent bound by no trust and holding no role files a challenge against a record of another store, in "
          "the commons, under its own key's name; the commons admits it and the store objected to is untouched",
          filed in rep_c["_recs"] and rep_c["_recs"][filed]["actor"] == "key:" + stranger.public
          and not rep_c["rejected"] and not rep_c["problems"] and r.store.file.read_bytes() == w_bytes
          and (r.home / "stranger.seed").stat().st_mode & 0o777 == 0o600, rep_c["rejected"])
    space = SV.Space({"w": str(r.root), "commons": str(commons)})
    page_ = SV.App(space, reader="dave").page_lineage("w", o)[1]
    fragile = SV.App(space).page_fragile()
    check("CM2 every page shows the voice from outside, and no store's rules count it: the lineage's reliance stays the "
          "store's, the floor counts the voice among those who spoke, /fragile lists it uncounted",
          "заперечив (у commons)" in page_ and "голос ззовні" in page_ and "ignores the cold start" in page_
          and "опора <span data-floor=\"reliance\"><span class=\"tag ELIGIBLE\"" in page_ and "висловились:" in page_ and "key:" in page_
          and "ignores the cold start" in fragile and space.report("w")["lineages"][o]["reliance"] == "ELIGIBLE", page_[:0])
    impostor = R.record("challenge", "claude", 1_900_000_001, {"target": d, "statement": "I am claude"}, refs=[d])
    from warrant.store import Store as ST
    ST(commons / ".warrant").extend([impostor], stranger, CM.DOC["trust"])
    loud = R.record("attest", "key:" + stranger.public, 1_900_000_002, {"target": d, "verdict": "accept"}, refs=[d])
    ST(commons / ".warrant").extend([loud], stranger, CM.DOC["trust"])
    rep_c2 = RR(str(commons)).report()
    check("CM3 nobody speaks in another's name and a stranger's key speaks only to object: a challenge signed as "
          "'claude' with another key, and an acceptance under a key's own name, are rejected", len(rep_c2["rejected"]) == 2
          and filed in rep_c2["_recs"], rep_c2["rejected"])
    lab = Repo()
    lab.put("carol", "attest", {"target": filed, "verdict": "reproduces", "on": d}, refs=[filed, d])
    snaps = {"w": r.store.snapshot(), "commons": ST(commons / ".warrant").snapshot(), "lab": lab.store.snapshot()}
    t, _, _ = OV.receiver(r.trust, r.profile, {"w": r.trust, "lab": lab.trust})
    counted = OV.assess(snaps, t, r.profile)
    check("CM4 a reader whose rules trust a replayer that reproduces the voice counts it: the claim the store relies on "
          "reads CHALLENGED for that reader, and still ELIGIBLE in its store", counted["lineages"][o]["reliance"] == "CHALLENGED"
          and space.report("w")["lineages"][o]["reliance"] == "ELIGIBLE", counted["challenges"].get(filed))
    refused = []
    for target, text in (("nope", "x"), (d, ""), (d, "x" * (CM.STATEMENT_MAX + 1))):
        try:                                 # a crash is this case's FAIL; only the commons' own refusal counts
            CM.say(commons, target, text, stranger, at=1_900_000_010)
            refused.append(False)
        except Exception as e:
            refused.append(isinstance(e, CM.Refused))
    check("CM5 the commons refuses what is no voice: a target that is no record id, an empty statement, one beyond "
          f"{CM.STATEMENT_MAX} characters", refused == [True, True, True], refused)
    outcomes = []
    for attempt in (lambda: CM.say(r.root, d, "фе into a store that trusts", stranger, at=1_900_000_020),
                    lambda: CM.seed(commons / "inside.seed", commons)):
        try:                                 # a crash is this case's FAIL; only the commons' own refusal counts
            attempt()
            outcomes.append(False)
        except Exception as e:
            outcomes.append(isinstance(e, CM.Refused))
    keep_seeds = CM.SEEDS
    CM.SEEDS = r.home / "seeds"
    try:
        named = CM.seed_named("agent-1")
        try:
            CM.seed_named("../escape")
            escaped = True
        except CM.Refused:
            escaped = False
    finally:
        CM.SEEDS = keep_seeds
    outcomes.append(not escaped and (r.home / "seeds" / "agent-1.seed").exists() and named.public)
    check("CM6 a voice is written only into a commons (a store that trusts nobody and gives nobody a role): pointed at "
          "a project's store it is refused, nothing appended; a seed inside the store it writes to is refused; the "
          "command line names a key, never a path (a name that would leave the seeds' directory is refused)",
          outcomes[:2] == [True, True] and bool(outcomes[2]) and r.store.file.read_bytes() == w_bytes, outcomes)


def tails_cases():
    """Small tails of Codex's observer pack: P09 references held elsewhere are named; R06 the page as the reader saw
    it then, rebuilt from the dates and checked against the root the view recorded; P10 a warm cache changes nothing."""
    from warrant_agent import serve as SV
    other = Repo()
    far = other.entity("carol", "obligation@1", {"state": "open", "statement": "held elsewhere", "serves": []})
    r = Repo()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "the claim", "serves": []}, refs=[far])
    me = Repo()
    space = SV.Space({"w": str(r.root), "me": str(me.root)})
    page_ = SV.App(space, reader="bob").page_lineage("w", o)[1]
    check("TL1 a page names the records its lineage rests on that this store does not hold, unchecked (P09)",
          "тримається й на 1 записах поза цим сховищем" in page_ and far[:12] in page_, page_[:0])
    root_then = r.store.snapshot().digest
    seen = me.put("bob", "attest", {"target": o, "verdict": "seen", "lens": "builtin", "root": root_then}, refs=[o], at=r.t + 1)
    wrong = me.put("bob", "attest", {"target": o, "verdict": "seen", "lens": "builtin", "root": "0" * 64}, refs=[o], at=r.t + 2)
    from warrant_agent import lens as LZ
    me.put("alice", "schema", LZ.SCHEMA)
    flat = me.put("carol", "entity", {"state": "active", "name": "flat then", "applies": "*",
                                      "card": {"layout": "flat", "fields": []}}, "lens@1")
    under = me.put("bob", "attest", {"target": o, "verdict": "seen", "lens": flat, "root": root_then}, refs=[o], at=r.t + 3)
    r.t += 10
    later = r.entity("alice", "obligation@1", {"state": "open", "statement": "the claim, later", "serves": []}, lineage=o)
    app = SV.App(space, reader="bob")
    then = app.page_lineage("w", o, {"asof": seen})[1]
    approx = app.page_lineage("w", o, {"asof": wrong})[1]
    now = app.page_lineage("w", o)[1]
    check("TL2 «як бачив тоді»: the store rebuilt from the records dated no later than the reader's view, under the lens "
          "it names; the same root reads «відтворено точно», another «наближено»; the floor links the reader's last view (R06)",
          "відтворено точно" in then and later[:12] not in then and later[:12] in now and "наближено" in approx
          and "лінза «flat then»" in app.page_lineage("w", o, {"asof": under})[1] and "лінза «flat then»" not in now
          and f"asof={under}" in now, then[:0])
    cold = SV.App(SV.Space({"w": str(r.root), "me": str(me.root)}), reader="bob")
    warm = SV.App(space, reader="bob")
    pages = lambda a: [a.page_lineage("w", o)[1], a.page_scene("w", o)[1], a.page_fragile(), a.page_feed({}),
                       a.page_whatif({"store": "w", "without": "challenges"})[1]]
    first, again = pages(warm), pages(warm)
    check("TL3 a warm cache is an optimisation, never another page: a fresh space and a warmed one render every page "
          "byte for byte the same (P10)", pages(cold) == first == again, [len(x) for x in first])


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
    serve_cases()
    lens_cases()
    changes_cases()
    scene_cases()
    fragile_cases()
    whatif_cases()
    audit_cases()
    overlay_cases()
    commons_cases()
    tails_cases()
    contract_cases()
    page_contract_cases()
    voices_cases()
    sys.exit(finish())
