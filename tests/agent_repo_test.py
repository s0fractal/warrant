#!/usr/bin/env python3
"""A repository checkout through warrant-agent (I, T, B, Q): `warrant-agent-mcp init`, a workspace
whose trust is the repository's bindings under its roles, evidence blobs given with a prepare,
and the roadmap's operations through the interface.

Each case builds a fixture repository in the layout of tools/claims.py and tools/roadmap.py
(`.warrant/store`, `trust.json` bindings with proofs, `roles.json` pins, `roadmap.json`, one
goal filed by the tool). Refusals are asserted by their code and by what was (not) written,
states by the engine's data, never by wording.

    python3 tests/agent_repo_test.py        (Q02 needs the optional dependency `mcp`)
"""
import asyncio
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from agent_world import C, Config, Key, api, check, finish
from warrant import bindings as B
from warrant_agent import init as I

ROOT = Path(__file__).resolve().parents[1]
IMPL = os.environ.get("WARRANT_IMPL") or str(ROOT)
_tool = Path(IMPL) / "tools" / "roadmap.py"
_spec = importlib.util.spec_from_file_location("roadmap_for_agent", _tool if _tool.is_file() else ROOT / "tools" / "roadmap.py")
RM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RM)
ENV = dict(os.environ, PYTHONPATH=os.pathsep.join([IMPL] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])))

ACTORS = ("claude", "codex", "s0fractal", "stranger")
ROADMAP = {"roadmap": "warrant-roadmap/config@1", "owed_to": ["s0fractal"], "accept_by": ["codex"],
           "results_accept_by": ["codex"]}
GOAL = "An agent with no preparation can use Warrant correctly."


class Fixture:
    """A repository (base/repo), the operator's seeds (base/seeds) and configurations (base/op)."""

    def __init__(self, keys=None):
        self.base = Path(tempfile.mkdtemp(prefix="warrant-agent-repo-"))
        self.repo, self.seeds, self.op = self.base / "repo", self.base / "seeds", self.base / "op"
        for d in (self.repo / ".warrant" / "store" / "records", self.repo / ".warrant" / "store" / "blobs", self.seeds):
            d.mkdir(parents=True)
        self.keys = keys or {a: Key.generate() for a in ACTORS}
        for a, k in self.keys.items():
            (self.seeds / f"{a}.seed").write_text(k.seed_hex() + "\n")
        self.bindings([(a, k) for a, k in self.keys.items()])
        roles = {a: k.public for a, k in self.keys.items() if a != "stranger"}
        roles.update(s0fractal=None, readers=B.COLLECTIVE)
        self.roles(roles)
        (self.repo / ".warrant" / "roadmap.json").write_text(json.dumps(ROADMAP) + "\n")
        self.goal_ref = None

    def bindings(self, pairs, extra=()):
        doc = {"bindings": B.BINDINGS, "keys": [{"actor": a, "public": k.public, "proof": B.binding_proof(k, a)}
                                                for a, k in pairs] + list(extra)}
        (self.repo / ".warrant" / "trust.json").write_bytes(C.canon(doc))

    def roles(self, actors):
        (self.repo / ".warrant" / "roles.json").write_text(json.dumps({"roles": B.ROLES, "actors": actors}))

    def tool(self, *argv, actor="claude"):
        """(exit status, stdout) of one tools/roadmap.py command, signed by `actor`."""
        sign = ["--key", str(self.seeds / f"{actor}.seed"), "--actor", actor] if argv[0] not in ("project", "check", "path") else []
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = RM.main(["--root", str(self.repo), argv[0], *sign, *argv[1:]])
        assert rc == 0 or argv[0] == "check", f"roadmap.py {argv[0]} refused: {err.getvalue().strip()}"
        return rc, out.getvalue().strip()

    def with_goal(self):
        self.tool("goal", "--id", "G1", "--text", GOAL)
        self.goal_ref = RM.Roadmap(self.repo).model().current("G1").ref
        return self

    def init(self, actor="claude", name=None, **kw):
        cfg = self.op / f"{name or actor}.json"
        args = dict(repo=self.repo, actor=actor, seed=self.seeds / f"{actor}.seed", config=cfg,
                    workspace="repo", operations=("context", "read", "prepare", "commit"))
        args.update(kw)
        summary = I.init(**args)
        return Config.load(cfg), summary

    def refusal(self, **kw):
        """The code of init's refusal, or None; and whether anything was written outside the seeds."""
        before = self.listing()
        try:
            self.init(**kw)
            code = None
        except I.Refused as e:
            code = e.code
        return code, self.listing() != before

    def listing(self):
        return sorted(str(p.relative_to(self.base)) for p in self.base.rglob("*"))

    def store_files(self):
        root = self.repo / ".warrant" / "store"
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}

    def model(self):
        return RM.Roadmap(self.repo).model()

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)


def ok(res):
    assert "ok" in res, res
    return res["ok"]["data"]


def init_cases():
    f = Fixture().with_goal()
    cfg, summary = f.init()
    ws = cfg.workspace("repo")
    prof = ws.profile()
    view = ok(api.call(cfg, "workspace", {}))["workspaces"][0]
    seeds_after = sorted(p.name for p in f.seeds.iterdir())
    check("I01", ws.store == (f.repo / ".warrant" / "store").resolve() and ws.signer[0] == "claude"
          and summary["signer"]["key"] == f.keys["claude"].id and prof["accept_by"]["results"] == ROADMAP["results_accept_by"]
          and view["operations"] == ["context", "read", "prepare", "commit"] and view["store"]["invalid_records"] == 0
          and seeds_after == sorted(f"{a}.seed" for a in ACTORS)
          and not any(p.suffix in (".seed", ".key") for p in f.op.rglob("*")),
          "init writes a workspace on the repository's store, signer and roadmap profile, and creates no key",
          (summary, prof, view["operations"]))

    # I02: a seed whose key is not the one roles.json pins for the actor (another actor's) is refused
    got = f.refusal(actor="claude", name="x2", seed=f.seeds / "codex.seed")
    check("I02", got == ("INIT_KEY_NOT_PINNED", False), "a seed of another key than the pinned one is refused, nothing written", got)

    # I03: an actor with no pinned key (reserved, collective, no role) is refused before its key is compared
    got = [f.refusal(actor=a, name=f"x3{a}", seed=f.seeds / "stranger.seed") for a in ("s0fractal", "readers", "stranger")]
    check("I03", got == [("INIT_ACTOR_NOT_PINNED", False)] * 3, "reserved, collective and unpinned actors sign nothing", got)

    # I04: pinned, but its binding is not admitted (no binding; then a forged proof)
    g = Fixture(keys=f.keys)
    g.bindings([(a, k) for a, k in g.keys.items() if a != "codex"])
    no_binding = g.refusal(actor="codex")
    k = g.keys["codex"]
    g.bindings([(a, k2) for a, k2 in g.keys.items() if a != "codex"],
               extra=[{"actor": "codex", "public": k.public, "proof": g.keys["stranger"].sign(B.binding_message("codex", k.public))}])
    forged = g.refusal(actor="codex", name="x4")
    check("I04", (no_binding, forged) == (("INIT_NOT_ADMITTED", False),) * 2,
          "the pinned key's binding must be admitted by trust.json", (no_binding, forged))

    # I05: no seed at the path: refused, and no file appears there
    missing = f.seeds / "nobody.seed"
    got = f.refusal(seed=missing, name="x5")
    check("I05", got == ("INIT_NO_SEED", False) and not missing.exists(), "init never creates a seed", got)

    # I06: the configuration, the state or the seed inside the repository
    inside = f.repo / "seed-copy"
    inside.write_text(f.keys["claude"].seed_hex())
    got = [f.refusal(config=f.repo / "c.json"), f.refusal(name="x6", state=f.repo / "state"), f.refusal(name="x6b", seed=inside)]
    inside.unlink()
    check("I06", got == [("INIT_INSIDE_REPOSITORY", False)] * 3, "the operator's files stay outside the repository", got)

    # I07: operations are the operator's choice: an unknown one is refused; one not listed is NOT_PERMITTED
    bad = f.refusal(name="x7", operations=("context", "shell"))
    ro, _ = f.init(name="ro", operations=("context", "read"))
    denied = api.call(ro, "prepare", {"workspace": "repo", "type": "duty", "body": {}})
    check("I07", bad == ("INIT_OPERATIONS", False) and denied.get("error") == "NOT_PERMITTED",
          "init enables exactly the operations given", (bad, denied))

    # I08: an existing configuration is replaced only with force
    first = (f.op / "claude.json").read_bytes()
    again = f.refusal()
    _, _ = f.init(force=True, operations=("context",))
    check("I08", again == ("INIT_CONFIG_EXISTS", False) and (f.op / "claude.json").read_bytes() != first,
          "init replaces a configuration only with --force", again)

    # I09: the other refusals, each with its code and nothing written
    h = Fixture(keys=f.keys)
    (h.seeds / "bad.seed").write_text("not hex")
    shutil.rmtree(h.repo / ".warrant" / "store")
    no_repo = h.refusal()
    (h.repo / ".warrant" / "store").mkdir()
    got = [no_repo, h.refusal(actor="bad\n"), h.refusal(seed=h.seeds / "bad.seed"), h.refusal(workspace="Bad Name")]
    (h.repo / ".warrant" / "roadmap.json").write_text("{}")
    got.append(h.refusal())
    (h.repo / ".warrant" / "roles.json").write_text(json.dumps({"roles": B.ROLES, "actors": {"claude": "not-a-key"}}))
    got.append(h.refusal())
    want = ["INIT_NOT_A_REPOSITORY", "INIT_ACTOR_SHAPE", "INIT_SEED_SHAPE", "INIT_WORKSPACE_NAME", "INIT_ROADMAP_SHAPE",
            "INIT_TRUST_SHAPE"]
    check("I09", got == [(c, False) for c in want], "every other refusal has its code and writes nothing", got)

    # I10: the command line: exit 0 with the summary, exit 2 with REFUSED <CODE> on stderr
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc_ok = I.main(["--repo", str(f.repo), "--actor", "codex", "--seed", str(f.seeds / "codex.seed"),
                        "--config", str(f.op / "cli.json"), "--workspace", "repo"])
        rc_no = I.main(["--repo", str(f.repo), "--actor", "codex", "--seed", str(f.seeds / "claude.seed"),
                        "--config", str(f.op / "cli2.json")])
    check("I10", rc_ok == 0 and json.loads(out.getvalue())["signer"]["actor"] == "codex" and rc_no == 2
          and err.getvalue().startswith("REFUSED INIT_KEY_NOT_PINNED ") and not (f.op / "cli2.json").exists(),
          "init's command line", (rc_ok, rc_no, err.getvalue()))
    for x in (f, g, h):
        x.close()


def trust_cases():
    f = Fixture().with_goal()
    cfg, _ = f.init(name="t")
    ws = cfg.workspace("repo")
    first = api.call(cfg, "context", {"workspace": "repo"})["ok"]
    # T01: a binding admitted after init is in the next view's trust; the earlier view sees the change
    newcomer = Key.generate()
    roles = json.loads((f.repo / ".warrant" / "roles.json").read_text())["actors"]
    roles["newcomer"] = newcomer.public
    f.roles(roles)
    f.bindings([*f.keys.items(), ("newcomer", newcomer)])
    now = ws.trust()
    again = api.call(cfg, "read", {"workspace": "repo", "kind": "context", "view_token": first["view_token"]})["ok"]
    check("T01", newcomer.id in now.keys and now.keys[newcomer.id][0] == "newcomer"
          and again["observation"]["trust_current"] is False,
          "the trust is the repository's admitted bindings, read again for every view", again["observation"])

    # T02: a binding the roles refuse (the pinned name with another key) is not in the trust
    intruder = Key.generate()
    f.bindings([(a, k) for a, k in f.keys.items() if a != "codex"] + [("codex", intruder)])
    t = ws.trust()
    check("T02", intruder.id not in t.keys and f.keys["claude"].id in t.keys,
          "a binding .warrant/roles.json refuses is not admitted into the workspace's trust", sorted(a for a, _ in t.keys.values()))

    # T03: a roles file with any problem refuses every view: a dropped pin would make its name first-come
    roles["codex"] = "not-a-key"
    f.roles(roles)
    f.bindings([*f.keys.items()])
    refused = api.call(cfg, "context", {"workspace": "repo"})
    check("T03", refused.get("error") == "BAD_REQUEST" and "ROLES_SHAPE" in refused.get("details", {}).get("problems", []),
          "a malformed roles file is refused, not read as fewer pins", refused)
    f.close()


def blob_cases():
    f = Fixture().with_goal()
    cfg, _ = f.init(name="b")
    ev = {"schema": "warrant-roadmap/evidence@1", "duty": "0" * 64, "refs": ["#1"]}
    body = {"basis": "ATTESTED", "established": ["a fact"], "residual": ["open"], "evidence": ["blob:0"]}
    # B01: blob:<i> is the id of blobs[i]; commit stores its canonical bytes before the record
    d = ok(api.call(cfg, "prepare", {"workspace": "repo", "type": "transition", "body": body, "blobs": [ev]}))
    h = C.digest(C.canon(ev))
    blob = f.repo / ".warrant" / "store" / "blobs" / h
    before = blob.exists()
    c = ok(api.call(cfg, "commit", {"workspace": "repo", "draft_id": d["draft_id"]}))
    rec = C.loads((f.repo / ".warrant" / "store" / "records" / f"{c['record_id']}.json").read_bytes())["record"]
    check("B01", d["record"]["body"]["evidence"] == [h] and d["preview"]["blobs"] == [h] and not before
          and blob.is_file() and blob.read_bytes() == C.canon(ev) and rec["body"]["evidence"] == [h],
          "a prepare's blobs are stored at commit under the ids its record cites", d["preview"])

    # B02: a blob not cited, a blob:<i> naming no blob, a non-canonical document: BAD_REQUEST, nothing stored
    files = f.store_files()
    uncited = api.call(cfg, "prepare", {"workspace": "repo", "type": "transition", "body": dict(body, evidence=[]),
                                        "blobs": [ev, {"x": 1}]})
    beyond = api.call(cfg, "prepare", {"workspace": "repo", "type": "transition", "body": dict(body, evidence=["blob:1"]),
                                       "blobs": [{"x": 2}]})
    floaty = api.call(cfg, "prepare", {"workspace": "repo", "type": "transition", "body": body, "blobs": [{"x": 0.5}]})
    codes = [r.get("error") for r in (uncited, beyond, floaty)]
    check("B02", codes == ["BAD_REQUEST"] * 3 and f.store_files() == files,
          "every blob is cited, every blob:<i> names one, each is canonical JSON", codes)

    # B03: the same request id with other blobs is CONFLICT; the same blobs are the same draft
    req = {"workspace": "repo", "type": "transition", "request_id": "b3",
           "body": dict(body, established=["another fact"]), "blobs": [{"n": 1}]}
    a = ok(api.call(cfg, "prepare", req))
    same = ok(api.call(cfg, "prepare", req))
    other = api.call(cfg, "prepare", dict(req, blobs=[{"n": 2}]))
    auto1 = ok(api.call(cfg, "prepare", {k: v for k, v in req.items() if k != "request_id"}))
    auto2 = ok(api.call(cfg, "prepare", dict({k: v for k, v in req.items() if k != "request_id"}, blobs=[{"n": 3}])))
    check("B03", same["draft_id"] == a["draft_id"] and other.get("error") == "CONFLICT" and auto1["draft_id"] != auto2["draft_id"],
          "a draft's blobs are part of its inputs", other)

    # B04: a commit under another signer stores no blob
    nb = {"n": 4}
    d4 = ok(api.call(cfg, "prepare", {"workspace": "repo", "type": "transition", "body": dict(body, established=["b4"]),
                                      "blobs": [nb]}))
    cfg.workspace("repo").signer = ("codex", f.seeds / "codex.seed")
    changed = api.call(cfg, "commit", {"workspace": "repo", "draft_id": d4["draft_id"]})
    check("B04", changed.get("error") == "SIGNER_CHANGED"
          and not (f.repo / ".warrant" / "store" / "blobs" / C.digest(C.canon(nb))).exists(),
          "SIGNER_CHANGED files nothing, blobs included", changed)
    f.close()


# ---------------------------------------------------------------- the roadmap through the interface

def recipe():
    """The roadmap recipe of AGENT.md (the block after `<!-- roadmap-recipe -->`): {name: prepare arguments}."""
    text = (ROOT / "AGENT.md").read_text()
    block = text[text.index("<!-- roadmap-recipe -->"):]
    block = block[block.index("```json\n") + 8:]
    return json.loads(block[:block.index("```")])


def fill_in(doc, slots):
    """The recipe with its <slots> filled: a slot that is a whole string takes any JSON value."""
    if isinstance(doc, dict):
        return {k: fill_in(v, slots) for k, v in doc.items()}
    if isinstance(doc, list):
        return [fill_in(v, slots) for v in doc]
    if isinstance(doc, str) and re.fullmatch(r"<[^<>]+>", doc):
        return slots[doc]
    return doc


def prepare_commit(cfg, args):
    d = ok(api.call(cfg, "prepare", dict(args, workspace="repo")))
    return ok(api.call(cfg, "commit", {"workspace": "repo", "draft_id": d["draft_id"]}))["record_id"]


def equivalence_case():
    """Q01: each operation through the interface and through tools/roadmap.py files the same bytes."""
    a = Fixture().with_goal()
    b = Fixture(keys=a.keys)
    shutil.rmtree(b.repo / ".warrant" / "store")
    shutil.copytree(a.repo / ".warrant" / "store", b.repo / ".warrant" / "store")
    b.goal_ref = a.goal_ref                 # the same vision transition, copied
    claude, _ = b.init()
    codex, _ = b.init(actor="codex")
    steps = recipe()
    frozen = max(int(time.time()), max(r["at"] for r in a.model().recs.values())) + 60
    real, same = time.time, []
    time.time = lambda: frozen               # both writers date a record max(now, ...): one clock for both
    try:
        _, o1 = a.tool("oblige", "--text", "The first obligation.", "--answers", "G1")
        _, o2 = a.tool("oblige", "--text", "The second obligation.", "--answers", "G1", "--requires", o1, "--serves", o1)
        slots = {"<your actor>": "claude", "<goal ref>": b.goal_ref, "<owed_to of .warrant/roadmap.json>": ROADMAP["owed_to"],
                 "<accept_by of .warrant/roadmap.json>": ROADMAP["accept_by"]}
        m1 = prepare_commit(claude, fill_in(steps["oblige"], dict(slots, **{"<one line>": "The first obligation.",
                                                                           "<required duty ids>": [], "<served duty ids>": []})))
        m2 = prepare_commit(claude, fill_in(steps["oblige"], dict(slots, **{"<one line>": "The second obligation.",
                                                                           "<required duty ids>": [m1], "<served duty ids>": [m1]})))
        same.append(("oblige", (m1, m2) == (o1, o2) and a.store_files() == b.store_files()))
        refs, commit = ["#999", "0123456789abcdef0123456789abcdef01234567"], "0123456789abcdef0123456789abcdef01234567"
        _, t1 = a.tool("done", "--duty", o1, "--established", "It is done.", "--ref", refs[0], "--ref", refs[1], "--commit", commit)
        n1 = prepare_commit(claude, fill_in(steps["done"], {"<duty id>": m1, "<what is now true, one line>": "It is done.",
                                                            "<pull request>": refs[0], "<commit>": refs[1],
                                                            "<merge commit, hex40>": commit}))
        same.append(("done", n1 == t1 and a.store_files() == b.store_files()))
        _, acc = a.tool("accept", "--duty", o1, actor="codex")
        k1 = prepare_commit(codex, fill_in(steps["accept"], {"<closure transition id>": n1, "<item>": 0}))
        same.append(("accept", k1 == acc and a.store_files() == b.store_files()))
    finally:
        time.time = real
    for x in (a, b):
        x.tool("project")
    views = [(x.repo / "ROADMAP.md").read_bytes() for x in (a, b)]
    checks = [x.tool("check")[0] for x in (a, b)]
    state = next(n for n in RM.path_data(b.model(), "G1")["obligations"] if n["duty"] == m1)
    check("Q01", all(s for _, s in same) and views[0] == views[1] and checks == [0, 0]
          and (state["state"], state["accepted_by"]) == ("DISCHARGED", ["codex"]),
          "oblige, done and accept through the interface file the bytes tools/roadmap.py files; ROADMAP.md is identical",
          (same, checks, state["state"]))
    for x in (a, b):
        x.close()


def dogfood_case():
    """Q02: through the stdio MCP server: claude files an obligation and its closure, codex accepts it."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        check("Q02", False, "the MCP SDK is installed", "pip install 'warrant-graph[mcp]'")
        return
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    f = Fixture().with_goal()
    for actor in ("claude", "codex"):
        f.init(actor=actor)
    steps = recipe()

    async def session(actor, body):
        params = StdioServerParameters(command=os.sys.executable, env=ENV,
                                       args=["-m", "warrant_agent.mcp_server", "--config", str(f.op / f"{actor}.json")])
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await body(s)

    async def tool(s, name, **args):
        res = await s.call_tool(name, args)
        assert not res.is_error, res.content[0].text
        return res.structured_content["data"]

    async def claude(s):
        ctx = await tool(s, "warrant_context", workspace="repo")
        goal = next(q["question"] for q in ctx["questions"] if q["scope"] == "roadmap:G1")
        o = fill_in(steps["oblige"], {"<your actor>": "claude", "<goal ref>": goal, "<one line>": "Dogfood: an obligation filed through MCP.",
                                      "<owed_to of .warrant/roadmap.json>": ["s0fractal"],
                                      "<accept_by of .warrant/roadmap.json>": ["codex"],
                                      "<required duty ids>": [], "<served duty ids>": []})
        d = await tool(s, "warrant_prepare", workspace="repo", **o)
        duty = (await tool(s, "warrant_commit", workspace="repo", draft_id=d["draft_id"]))["record_id"]
        t = fill_in(steps["done"], {"<duty id>": duty, "<what is now true, one line>": "Filed and closed through MCP.",
                                    "<pull request>": "#0", "<commit>": "dogfood", "<merge commit, hex40>": None})
        d = await tool(s, "warrant_prepare", workspace="repo", **t)
        await tool(s, "warrant_commit", workspace="repo", draft_id=d["draft_id"])
        return duty

    async def codex(s, duty):
        ctx = await tool(s, "warrant_context", workspace="repo", targets=[duty])
        pending = [c for c in ctx["capsules"][0]["closures"] if c["verdict"] == "PENDING" and "codex" in c["waiting_for"]]
        ev = await tool(s, "warrant_read", workspace="repo", kind="blob",
                        target=C.loads((f.repo / ".warrant" / "store" / "records" / f"{pending[0]['transition']}.json")
                                       .read_bytes())["record"]["body"]["evidence"][0])
        a = fill_in(steps["accept"], {"<closure transition id>": pending[0]["transition"], "<item>": pending[0]["item"]})
        d = await tool(s, "warrant_prepare", workspace="repo", **a)
        await tool(s, "warrant_commit", workspace="repo", draft_id=d["draft_id"])
        after = await tool(s, "warrant_context", workspace="repo", targets=[duty])
        return json.loads(ev["content"]), after["capsules"][0]

    duty = asyncio.run(session("claude", claude))
    evidence, capsule = asyncio.run(session("codex", lambda s: codex(s, duty)))
    f.tool("project")
    rc, line = f.tool("check")
    node = RM.path_data(f.model(), "G1")["obligations"][0]
    check("Q02", rc == 0 and node["duty"] == duty and (node["state"], node["accepted_by"]) == ("DISCHARGED", ["codex"])
          and capsule["disposition"] == "DISCHARGED" and evidence["duty"] == duty
          and "[DISCHARGED · accepted by codex] Dogfood: an obligation filed through MCP." in (f.repo / "ROADMAP.md").read_text(),
          "an obligation filed, closed and accepted through the stdio MCP server reads DISCHARGED in ROADMAP.md",
          (line, node["state"]))
    f.close()


def main():
    for part in (init_cases, trust_cases, blob_cases, equivalence_case, dogfood_case):
        try:
            part()
        except Exception as e:      # noqa: BLE001 -- a part that raises fails its cases, the others still run
            check(f"RAISED-{part.__name__}", False, "ran to its end", f"{type(e).__name__}: {e}")
    return finish("AGENT-REPO")


if __name__ == "__main__":
    raise SystemExit(main())
