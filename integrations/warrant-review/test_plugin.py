#!/usr/bin/env python3
"""The Codex plugin and its waker, without Codex and without GitHub (C1-C14, W1-W14).

    python3 integrations/warrant-review/test_plugin.py      (C8 needs the optional dependency `mcp`)
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from world import KEYS, Repo, git as wgit                # noqa: E402

from warrant import records as R                         # noqa: E402

results = {}


def check(cid, ok, what, detail=""):
    results[cid] = ok
    print(("ok   " if ok else "FAIL ") + f"{cid} {what}" + ("" if ok else f" | {str(detail)[:400]}"), flush=True)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WAKER = load("waker", HERE / "waker" / "waker.py")
INSTALL = load("install", HERE / "install.py")


def inside(root, rel):
    p = (root / rel).resolve()
    return rel.startswith("./") and (p == root.resolve() or root.resolve() in p.parents)


def manifests():
    market = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    [entry] = market["plugins"]
    src = entry["source"]
    plugin = (ROOT / src["path"]).resolve()
    check("C1", src["source"] == "local" and inside(ROOT, src["path"]) and plugin == HERE,
          "the marketplace's one plugin is this directory, by a ./ path inside the marketplace root", entry)
    man = json.loads((HERE / ".codex-plugin" / "plugin.json").read_text())
    mcp_path, skills = HERE / man["mcpServers"], HERE / man["skills"]
    mcp = json.loads(mcp_path.read_text())
    server = mcp["mcpServers"]["warrant"]
    check("C2", man["name"] == entry["name"] == "warrant-review" and inside(HERE, man["mcpServers"])
          and mcp_path.is_file() and not mcp_path.is_symlink() and inside(HERE, man["skills"]) and skills.is_dir()
          and server["command"] == "/bin/sh" and (HERE / server["args"][0]).is_file()
          and set(server["env_vars"]) == {"HOME", "PATH", "WARRANT_AGENT_MCP", "WARRANT_AGENT_CONFIG"},
          "the manifest's MCP file (a regular file) and skills are inside the plugin; the server `warrant` is its launcher",
          (man, server))
    skill = (skills / "warrant-review" / "SKILL.md").read_text()
    front = re.match(r"---\nname: (\S+)\ndescription: (.+)\n---\n", skill)
    check("C3", front is not None and front.group(1) == "warrant-review" and "AGENT.md" in skill
          and "Sign only as A," in skill and "/tmp" in skill and "`codex`" not in skill.replace("e.g. `codex`", ""),
          "the skill names itself, points to the review recipe, and states who signs (the actor the waker names, no agent "
          "fixed) and where files go")
    lookup = next(x for x in skill.splitlines() if x.startswith("MCP="))       # the skill's own line, run as written
    def found(**env):
        return subprocess.run(["/bin/sh", "-c", lookup + '; printf %s "$MCP"'], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "HOME": "/h", **env}).stdout
    got = {"none": found(), "named": found(WARRANT_AGENT_MCP="/x/bin/warrant-agent-mcp")}
    check("C17", got == {"none": "/h/.warrant/codex-mcp/bin/warrant-agent-mcp", "named": "/x/bin/warrant-agent-mcp"},
          "the skill finds the MCP server where no PATH holds it (the waker's launchd PATH): $WARRANT_AGENT_MCP, else "
          "PATH, else install.py's venv", got)
    portable(man)


PLUGIN_FIELDS = {"$schema", "name", "version", "description", "author", "homepage", "repository", "license", "keywords",
                 "extensions"}
STDIO_FIELDS = {"type", "command", "args", "env", "cwd"}
NAME = re.compile(r"(?!.*(--|\.\.))[a-z0-9]([a-z0-9.-]{0,62}[a-z0-9])?\Z")


def portable(codex_man):
    """Agent Plugins 1.0.0 (agent-plugins.org): the package any conforming client loads, and the client manifests
    agreeing with it."""
    man = json.loads((HERE / "plugin.json").read_text())
    mcp = json.loads((HERE / "mcp.json").read_text())
    claude = json.loads((HERE / ".claude-plugin" / "plugin.json").read_text())
    servers = mcp.get("mcpServers", {})
    skill_dirs = sorted(d.name for d in (HERE / "skills").iterdir() if (d / "SKILL.md").is_file())
    fronts = {d: re.match(r"---\nname: (\S+)\ndescription: .+\n---\n", (HERE / "skills" / d / "SKILL.md").read_text())
              for d in skill_dirs}
    escapes = [str(q) for q in HERE.rglob("*") if q.is_symlink() or not inside(HERE, "./" + q.relative_to(HERE).as_posix())]
    problems = {
        "manifest": set(man) <= PLUGIN_FIELDS and man.get("$schema") == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
                    and isinstance(man.get("name"), str) and NAME.match(man["name"]) is not None
                    and set(man.get("author", {})) <= {"name", "email", "url"},
        "mcp": set(mcp) == {"$schema", "mcpServers"} and mcp["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
               and all(set(v) <= STDIO_FIELDS and v.get("type") == "stdio" and isinstance(v.get("command"), str)
                       and "${" not in v["command"] and "/" not in v["command"].removeprefix("./")
                       and not set(v.get("env", {})) & {"PLUGIN_ROOT", "PLUGIN_DATA"} for v in servers.values()),
        "server": servers.get("warrant") == {"type": "stdio", "command": "warrant-agent-mcp"},
        "skills": skill_dirs == ["warrant-review"] and all(f is not None and f.group(1) == d for d, f in fronts.items()),
        "contained": escapes == [],
        "clients": man["name"] == codex_man["name"] == claude["name"] and man["version"] == codex_man["version"] == claude["version"]
                   and claude.get("mcpServers") == "./mcp.json",
    }
    check("C16", all(problems.values()),
          "the plugin is an Agent Plugins 1.0.0 package (closed manifest and mcp.json, a bare server command with no "
          "placeholder, one skill per directory named as its SKILL.md, nothing linked or outside the root), and the Codex "
          "and Claude Code manifests name the same plugin and version; Claude Code's reads the portable mcp.json",
          {k: v for k, v in problems.items() if not v})


def launcher():
    d = Path(tempfile.mkdtemp(prefix="codex-plugin-"))
    fake = d / "fake-mcp"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    fake.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(d), "WARRANT_AGENT_MCP": str(fake)}
    out = subprocess.run(["/bin/sh", str(HERE / "scripts" / "warrant-mcp")], env=env, capture_output=True, text=True)
    own = subprocess.run(["/bin/sh", str(HERE / "scripts" / "warrant-mcp")], capture_output=True, text=True,
                         env=dict(env, WARRANT_AGENT_CONFIG=str(d / "other.json")))
    none = subprocess.run(["/bin/sh", str(HERE / "scripts" / "warrant-mcp")], capture_output=True, text=True,
                          env={"PATH": "/nonexistent", "HOME": str(d)})
    check("C4", out.stdout.split() == ["--config", str(d / ".warrant" / "codex-warrant.json")]
          and own.stdout.split() == ["--config", str(d / "other.json")] and none.returncode == 127,
          "the launcher runs the server with the operator's configuration, another one when named, and says when "
          "there is no server", (out.stdout, own.stdout, none.returncode))


def config_edit():
    text = ('model = "x"\n\n[mcp_servers.warrant]\ncommand = "/a/warrant-agent-mcp"\nargs = ["--config", "/a.json"]\n\n'
            '[mcp_servers.warrant-181]\ncommand = "/b"\n\n[desktop]\nk = 1\n')
    got = INSTALL.TABLE.sub("", text, count=1)
    check("C5", "[mcp_servers.warrant]" not in got and "/a/warrant-agent-mcp" not in got
          and "[mcp_servers.warrant-181]\ncommand = \"/b\"" in got and "[desktop]\nk = 1" in got,
          "install removes exactly the [mcp_servers.warrant] table from config.toml", got)


def dry_install():
    """install(dry=True) with the commit, the marketplace and the configuration edit stubbed (they read the
    checkout and the operator's files): every command it would run is printed, none that changes anything
    runs, and nothing is written under its home or LaunchAgents."""
    from unittest.mock import patch
    calls = []

    def fake(cmd, **kw):
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    home = Path(tempfile.mkdtemp(prefix="codex-install-dry-"))
    plist = home / "LaunchAgents" / "x.plist"
    with patch.object(INSTALL, "HOME", home / "waker"), patch.object(INSTALL, "PLIST", plist), \
            patch.object(INSTALL, "head", return_value="a" * 40), patch.object(INSTALL, "marketplace"), \
            patch.object(INSTALL, "config_without_server"), patch.object(INSTALL.subprocess, "run", side_effect=fake):
        INSTALL.install(True)
    check("C13", calls == [["codex", "plugin", "marketplace", "list"]] and not (home / "waker").exists() and not plist.exists(),
          "install --dry-run runs only a read (the marketplace list): no launchctl, codex or pip command, no file "
          "(Codex finding 41141d15bbaf on f2a95e5)", calls)


def fixture_mirror():
    """A Waker over a scratch home whose mirror is a bare repository with two commits (heads to wake for)."""
    base = Path(tempfile.mkdtemp(prefix="codex-waker-"))
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@invalid", "-c", "commit.gpgsign=false"]
    work = base / "work"
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    heads = []
    for i in range(2):
        (work / "f").write_text(str(i))
        subprocess.run([*g, "-C", str(work), "add", "-A"], check=True)
        subprocess.run([*g, "-C", str(work), "commit", "-q", "-m", str(i)], check=True)
        heads.append(subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"], capture_output=True, text=True,
                                    check=True).stdout.strip())
    home = base / "home"
    home.mkdir()
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(home / "warrant.git")], check=True)
    return base, home, heads


def entry(home, trees, repository="s0fractal/warrant", branch="master", mirror=None):
    """An entry of the waker's repositories.json: the repository it serves, with its own home and worktrees."""
    return {"repository": repository, "branch": branch, "home": str(home), "mirror": str(mirror or Path(home) / "warrant.git"),
            "trees": str(trees), "checkout": str(Path(home).parent / "operator-checkout")}


def due_json(head, pr=7):
    return {"pr": pr, "head": head, "base": "b" * 40, "branch": "topic",
            "facts": {"duty": "d" * 64, "closure": "c" * 64, "head_n": 2, "x": "e" * 40}}


class Codex:
    """A fake `codex exec`: records each command, exits `code`, and may leave a file in its worktree."""

    def __init__(self, code=0, dirty=False):
        self.calls, self.code, self.dirty = [], code, dirty

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if self.dirty:
            (Path(cmd[cmd.index("-C") + 1]) / "left.txt").write_text("x")
        return subprocess.CompletedProcess(cmd, self.code)


def wakes():
    base, home, heads = fixture_mirror()
    now = [1_000_000.0]
    codex = Codex()
    w = WAKER.Waker(entry(home, base / "trees"), replayers=base / "no-seeds", codex="/bin/codex", run=codex, clock=lambda: now[0])
    a = due_json(heads[0])
    first, second = w.wake(a)[1], w.wake(a)[1]
    memo = json.loads((home / "wakes" / f"7-{heads[0]}.json").read_text())
    cmd = codex.calls[0] if codex.calls else []
    text = cmd[-1] if cmd else ""
    check("C6", first.startswith("woken") and second.startswith("woken") is False and len(codex.calls) == 1
          and [t.get("exit") for t in memo["attempts"]] == [0] and memo["head"] == heads[0],
          "one wake per pull request head: a second run after a clean exit starts nothing", (first, second, memo))
    check("C7", cmd[:2] == ["/bin/codex", "exec"] and "-s" in cmd and cmd[cmd.index("-s") + 1] == "workspace-write"
          and not any("dangerously" in c for c in cmd) and all(x in text for x in ("$warrant-review", "c" * 64, "e" * 40,
                                                                                   heads[0], "warrant-mcp-call")),
          "codex exec runs sandboxed with the review skill and the facts of the head it was woken for", cmd)
    wt = Path(cmd[cmd.index("-C") + 1]) if cmd else None
    check("C10", wt is not None and wt.parent == base / "trees" and wt.name == f"7-{heads[0][:12]}"
          and wt.resolve() != w.checkout.resolve() and not wt.exists()
          and memo["attempts"][0]["worktree"] == str(wt),
          "each wake runs in its own worktree of the mirror, never the operator's checkout, removed after a clean run",
          (wt, memo))
    refused = None
    try:
        w.command(a, w.checkout)
    except ValueError as e:
        refused = str(e)
    dirty = WAKER.Waker(entry(home, base / "trees"), replayers=base / "no-seeds", codex="/bin/codex", run=Codex(dirty=True),
                        clock=lambda: now[0])
    out = dirty.wake(due_json(heads[1], pr=8))[1]
    kept = base / "trees" / f"8-{heads[1][:12]}"
    head_there = subprocess.run(["git", "-C", str(kept), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    check("C11", refused is not None and "kept" in out and (kept / "left.txt").is_file() and head_there == heads[1],
          "the operator's checkout is refused as a wake's directory; a worktree Codex left changes in is kept, "
          "detached at the head", (refused, out, head_there))

    failing = Codex(code=1)
    f = WAKER.Waker(entry(home, base / "trees"), replayers=base / "no-seeds", codex="/bin/codex", run=failing, clock=lambda: now[0])
    b = due_json(heads[1], pr=9)
    states = [f.wake(b)[1], f.wake(b)[1]]
    now[0] += WAKER.BACKOFF + 1
    states.append(f.wake(b)[1])
    now[0] += 2 * WAKER.BACKOFF + 1
    states.append(f.wake(b)[1])
    now[0] += 100 * WAKER.BACKOFF
    states.append(f.wake(b)[1])
    tries = json.loads((home / "wakes" / f"9-{heads[1]}.json").read_text())["attempts"]
    check("C12", len(failing.calls) == WAKER.MAX_TRIES == 3 and [t["exit"] for t in tries] == [1, 1, 1]
          and "retry after" in states[1] and states[2].startswith("woken") and "gave up" in states[4]
          and "gave up" in f.report(b, held=False),
          "a wake that exited non-zero is retried after a doubling backoff, three attempts in all, then given up; the "
          "listing says so", states)


def mcp_call():
    if importlib.util.find_spec("mcp") is None:
        print("skip C8 (no mcp)")
        return
    r = Repo()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    cfg = r.home / "config.json"
    cfg.write_text(json.dumps({"agent_api": "warrant-agent/3", "workspaces": {"src": {
        "repo": str(r.root), "signer": {"actor": "bob", "key": str(r.seed("bob"))}}}}))
    server = r.home / "server"
    server.write_text(f'#!/bin/sh\nPYTHONPATH="{ROOT}" exec "{sys.executable}" -m warrant_agent.mcp_server "$@"\n')
    server.chmod(0o755)
    env = dict(os.environ, WARRANT_AGENT_MCP=str(server))

    def call(tool, args):
        out = subprocess.run([sys.executable, str(HERE / WAKER.CLIENT), "--config", str(cfg), tool,
                              json.dumps(args)], env=env, capture_output=True, text=True)
        return out.returncode, json.loads(out.stdout) if out.stdout.strip() else out.stderr
    rc1, ws = call("workspace", {})
    rc2, prep = call("prepare", {"workspace": "src", "kind": "attest", "target": o, "body": {"verdict": "seen"}})
    rc3, done = call("commit", {"workspace": "src", "record": prep.get("record") if isinstance(prep, dict) else None})
    filed = r.report()["graph"]["nodes"]
    check("C8", (rc1, rc2, rc3) == (0, 0, 0) and isinstance(done, dict) and done.get("id") in [n[0] for n in filed],
          "warrant-mcp-call drives the warrant MCP server for a given configuration, one tool per process: a prepare "
          "and its commit (the record passed back) in two calls file one signed record", (rc1, ws, rc2, prep, rc3, done))
    rc4, err = call("read", {"workspace": "src", "target": "0" * 12})
    check("C9", rc4 == 2, "a refusal of the server exits 2", (rc4, err))

    def by_repo(tool, args, *flags):
        out = subprocess.run([sys.executable, str(HERE / WAKER.CLIENT), *flags, tool, json.dumps(args)],
                             env=dict(env, HOME=str(r.home)), capture_output=True, text=True)   # init's confinement: $HOME
        return out.returncode, json.loads(out.stdout) if out.stdout.strip() else out.stderr
    flags = ("--repo", str(r.root), "--actor", "bob", "--seed", str(r.seed("bob")))
    name = r.root.name.lower()
    before = sorted(str(q) for q in r.home.rglob("*") if ".warrant" not in q.parts)
    rc5, prep = by_repo("prepare", {"workspace": name, "kind": "attest", "target": o, "body": {"verdict": "accept"}}, *flags)
    rc6, done = by_repo("commit", {"workspace": name, "record": prep.get("record") if isinstance(prep, dict) else None}, *flags)
    rc7, _ = by_repo("workspace", {}, "--config", str(cfg), *flags)
    after = sorted(str(q) for q in r.home.rglob("*") if ".warrant" not in q.parts)
    check("C15", (rc5, rc6) == (0, 0) and isinstance(done, dict) and done.get("filed", {}).get("actor") == "bob"
          and before == after and rc7 == 2,
          "warrant-mcp-call --repo --actor --seed serves a review worktree with no configuration file: the server holds "
          "it in memory and signs as that actor; --config with --repo is refused, and exits 2, not a traceback",
          (rc5, prep, rc6, done, rc7, sorted(set(after) - set(before))))


def store_rules():
    """The waker's own reading of the store (W1-W6): replay commits, verdicts it publishes, branches it resumes."""
    WAKER.ACCEPTOR = "bob"
    r = Repo()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "s", "serves": []}, lineage=o)
    wgit(r.root, "init", "-q", "-b", "master")
    base = r.commit("base")
    lines = r.store.lines()
    check("W1", all(WAKER.rid_of(x) == R.rid(json.loads(x)["record"]) for x in lines),
          "the waker names a stored line's record by the line's own bytes, as the engine does")
    f = r.put("bob", "challenge", {"target": d, "statement": "P2 x", "severity": "P2", "what": "w", "where": [],
                                   "commit": "a" * 40, "tree": "b" * 40}, "finding@1", refs=[d])
    head = r.commit("a finding")
    replay = r.put("carol", "attest", {"target": f, "verdict": "reproduces", "on": d}, refs=[f, d])
    ok = WAKER.changes(r.root, [replay], "carol")

    def refused(filed, actor):
        try:
            WAKER.changes(r.root, filed, actor)
            return False
        except RuntimeError:
            return True
    unprinted = r.put("carol", "attest", {"target": f, "verdict": "no_result", "on": d}, refs=[f, d])
    check("W2", ok == [WAKER.RECORDS] and refused([replay], "carol"),
          "a replay commit holds exactly the replay attests the checker printed, as new lines; one it did not print refuses it")
    wgit(r.root, "checkout", "-q", "--", ".")
    r.put("eve", "attest", {"target": f, "verdict": "reproduces", "on": d}, refs=[f, d])
    eve = [WAKER.rid_of(x) for x in WAKER.added_lines(r.root)[0]]
    check("W7", refused(eve, "carol") and unprinted not in eve,
          "... and every one of them is a replay result by the replayer: a printed line by another actor refuses it")
    code = r.root
    wgit(r.root, "checkout", "-q", "--", ".")
    accept = R.line(R.record("attest", "bob", r.t + 10, {"verdict": "accept", "target": d}, refs=[d]), KEYS["bob"])[1]
    other = R.line(R.record("attest", "bob", r.t + 11, {"verdict": "accept", "target": o}, refs=[o]), KEYS["bob"])[1]
    forged = R.line(R.record("attest", "bob", r.t + 12, {"verdict": "accept", "target": d}, refs=[d]), KEYS["eve"])[1]

    def verify(ls, blobs=None):
        import base64
        return WAKER.verify_verdicts({"code": str(code), "actor": "bob", "closure": d,
                                      "lines": [base64.b64encode(x).decode() for x in ls],
                                      "blobs": {k: base64.b64encode(v).decode() for k, v in (blobs or {}).items()}})
    got = [verify([accept]), verify([other]), verify([forged]), verify([accept], {"ab" * 32: b"x"})]
    check("W3", got[0] is None and all(got[1:]),
          "a verdict is published only when it is the acceptor's own acceptance of exactly the version due, signed with "
          "a key the base binds to it, every blob cited and named by its hash", got)
    wgit(r.root, "checkout", "-q", "-b", "verdict")
    with open(r.root / WAKER.RECORDS, "ab") as fh:
        fh.write(accept)
    tip = r.commit("bob's verdict")
    same = WAKER.pushed_before(r.root, tip, head, {accept}, {})
    diff = WAKER.pushed_before(r.root, tip, head, {other}, {})
    check("W4", same is None and diff is not None, "a resumed push is this verdict only if the branch adds exactly its lines",
          (same, diff))
    wgit(r.root, "checkout", "-q", "-b", "linked", base)
    (r.root / WAKER.BLOBS).mkdir(exist_ok=True)
    name = __import__("hashlib").sha256(b"evidence").hexdigest()
    os.symlink("evidence", r.root / WAKER.BLOBS / name)
    linked = r.commit("a link where a blob goes")
    check("W5", WAKER.tail_of(r.root, base, linked) == ([], {}),
          "a branch whose blob is a link (a mode other than a regular file) carries no verdict")
    wgit(r.root, "checkout", "-q", "verdict")
    check("W6", WAKER.held_verdict(r.root, {"closure": d}) in (WAKER.rid_of(accept), f) and WAKER.held_verdict(r.root, {"closure": o}) is None,
          "the waker finds a verdict the base holds already on the version, and only on it")


def seeds():
    """The replayer's seed is REPLAYERS/<actor>.seed for the actor the base's `review.py identity` names (W8)."""
    base = Path(tempfile.mkdtemp(prefix="codex-waker-seed-"))
    keys = base / "keys"                 # REPLAYERS is keys/replayers; keys/evil.seed lies outside it
    (keys / "replayers").mkdir(mode=0o700, parents=True)
    for p in (keys / "replayers" / "review-replayer.seed", keys / "evil.seed"):
        p.write_text("01" * 32 + "\n")
        p.chmod(0o600)
    w = WAKER.Waker(entry(base / "home", base / "trees"), replayers=keys / "replayers", replay_python=sys.executable,
                    codex="/bin/codex", run=Codex(), clock=lambda: 0.0)

    def base_tree(actor):
        code = Path(tempfile.mkdtemp(dir=base))
        (code / "warrant").mkdir()
        (code / ".warrant").mkdir()
        (code / "warrant" / "__init__.py").write_text("")
        (code / "warrant" / "review.py").write_text(f"import json\nprint(json.dumps({{'actor': {actor!r}, 'code': '0' * 64}}))\n")
        (code / ".warrant" / "v3.json").write_text(json.dumps({"profile": {"roles": {"replayer": [actor]}}}))
        return code
    good, evil = w.seed(base_tree("review-replayer")), w.seed(base_tree("../evil"))
    check("W8", good == ("review-replayer", ("01" * 32 + "\n").encode()) and evil[1] is None,
          "the replay seed is REPLAYERS/<actor>.seed for the replayer the base names; an actor that is not a plain name reads none",
          (good, evil))


def served_repo(base, name, branch, named=None):
    """A repository the waker serves: a work repository on `branch` whose .warrant/v3.json names `named` (default its
    own name), and the entry's home with a bare mirror of it (origin: the work repository, so `fetch` runs locally)."""
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@invalid", "-c", "commit.gpgsign=false"]
    slug = name.replace("/", "__")
    work = base / "origin" / slug
    subprocess.run(["git", "init", "-q", "-b", branch, str(work)], check=True)
    (work / ".warrant").mkdir()
    (work / ".warrant" / "v3.json").write_text(json.dumps({"repository": named or name}))
    subprocess.run([*g, "-C", str(work), "add", "-A"], check=True)
    subprocess.run([*g, "-C", str(work), "commit", "-q", "-m", "base"], check=True)
    head = subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    home = base / "homes" / slug
    home.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(home / "mirror.git")], check=True)
    return entry(home, base / "trees" / slug, name, branch, mirror=home / "mirror.git"), head


def serving():
    """Several repositories in one run (W9-W11): GitHub's side (`due`, `acceptances`) and the replay are stubbed, the
    rest is the waker's own: each repository's mirror fetched, its base checked, its due head woken in its worktree."""
    import contextlib
    import io
    base = Path(tempfile.mkdtemp(prefix="codex-waker-served-"))
    first, h1 = served_repo(base, "s0fractal/warrant", "master")
    second, h2 = served_repo(base, "s0fractal/sokol-core", "main")
    stray, _ = served_repo(base, "s0fractal/stray", "main", named="s0fractal/other")
    broken = dict(first, repository="s0fractal/broken", home=str(base / "homes" / "broken"), mirror=str(base / "nowhere.git"),
                  trees=str(base / "trees" / "broken"))
    waker = base / "waker"
    waker.mkdir()
    (waker / WAKER.CONFIG).write_text(json.dumps({"warrant": WAKER.CONFIG_DOC, "repositories": [first, broken, second, stray]}))
    codex = Codex()
    due = {"s0fractal/sokol-core": [dict(due_json(h2, pr=5), base=h2, branch="topic")]}

    class Served(WAKER.Waker):
        def fetch(self):
            if self.repository == "s0fractal/broken":
                raise RuntimeError("the mirror cannot be fetched")
            return super().fetch()

        def due(self, b):
            return {"due": due.get(self.repository, []), "not_due": []}

        def acceptances(self, b):
            return {"due": []}

        def replay(self, a, b):
            return False, "replay stubbed"

    def make(e):
        return Served(e, replayers=base / "no-seeds", codex="/bin/codex", run=codex, clock=lambda: 1_000_000.0)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = WAKER.serve(waker, False, make)
    lines = out.getvalue().splitlines()
    text = codex.calls[0][-1] if codex.calls else ""
    wt = Path(codex.calls[0][codex.calls[0].index("-C") + 1]) if codex.calls else None
    check("W9", len(codex.calls) == 1 and "s0fractal/sokol-core#5" in text and f"base main M {h2}" in text
          and "s0fractal/warrant" not in text and wt is not None and wt.parent == Path(second["trees"])
          and (Path(second["home"]) / "wakes" / f"5-{h2}.json").is_file() and not (Path(first["home"]) / "wakes" / f"5-{h2}.json").exists()
          and any(x.startswith(f"{WAKER.iso(1_000_000.0)} s0fractal/warrant master {h1[:12]}: 0 due") for x in lines),
          "the waker serves each repository of its configuration: a head due in the second wakes Codex with that "
          "repository's name and base branch, in its own worktree root, its memo in its own home", (lines, text))
    check("W10", any("s0fractal/stray main" in x and "nobody woken" in x and "s0fractal/other" in x for x in lines),
          "a base whose .warrant/v3.json names another repository than the entry's is refused: nothing assessed, nobody woken",
          lines)
    check("W11", code == 1 and any(x.endswith("s0fractal/broken master: failed: the mirror cannot be fetched") for x in lines)
          and lines.index(next(x for x in lines if "broken" in x)) < lines.index(next(x for x in lines if "sokol-core" in x)),
          "a repository whose run fails is reported and the next one still served; the run exits 1", lines)


def ungated():
    """A repository without a merge gate (W14): `due` refuses its base, so the open verdict pull requests that hold a
    roadmap wake are GitHub's list, this repository's branches under VERDICT_BRANCH only (s0fractal/minds, 2026-10-29)."""
    import types

    def forge(prs):
        def run(cmd, **kw):
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(prs).encode(), stderr=b"")
        return WAKER.Forge("s0fractal/minds", "main", run=run, gh="gh")
    other = [{"number": 3, "headRefName": "topic", "isCrossRepository": False},
             {"number": 4, "headRefName": WAKER.VERDICT_BRANCH + "abc-0", "isCrossRepository": True}]
    mine = other + [{"number": 9, "headRefName": WAKER.VERDICT_BRANCH + "def-0", "isCrossRepository": False}]
    refused = {"due": [], "not_due": [], "refused": "REFUSED BASE_CONFIG .warrant/merge.json at the base"}
    got = [WAKER.hold(types.SimpleNamespace(repository="s0fractal/minds", forge=forge(p)), refused, False, False) for p in (other, mine)]
    check("W14", got == [None, "held: verdict pull request #9 is open"], "a repository whose base `due` refuses (no merge "
          "gate) has its roadmap versions woken unless GitHub lists an open verdict pull request from its own branch", got)


def configuration():
    """repositories.json (W12) and install's default (C14)."""
    from unittest.mock import patch
    base = Path(tempfile.mkdtemp(prefix="codex-waker-config-"))
    one = entry(base / "a", base / "ta", "s0fractal/warrant", "master")
    two = entry(base / "b", base / "tb", "s0fractal/sokol-core", "main")

    def refused(doc):
        (base / WAKER.CONFIG).write_text(json.dumps(doc))
        try:
            WAKER.served(base)
            return False
        except ValueError:
            return True
    doc = {"warrant": WAKER.CONFIG_DOC, "repositories": [one, two]}
    (base / WAKER.CONFIG).write_text(json.dumps(doc))
    ok = [e["repository"] for e in WAKER.served(base)] == ["s0fractal/warrant", "s0fractal/sokol-core"]
    bad = {"empty": {"warrant": WAKER.CONFIG_DOC, "repositories": []},
           "same home": dict(doc, repositories=[one, dict(two, home=one["home"])]),
           "same trees": dict(doc, repositories=[one, dict(two, trees=one["trees"])]),
           "same repository": dict(doc, repositories=[one, dict(two, repository=one["repository"])]),
           "relative path": dict(doc, repositories=[dict(one, mirror="warrant.git")]),
           "not owner/name": dict(doc, repositories=[dict(one, repository="warrant")]),
           "branch": dict(doc, repositories=[dict(one, branch="a..b")]),
           "extra member": dict(doc, repositories=[dict(one, token="x")])}
    (base / "alias").symlink_to(base / "a", target_is_directory=True)     # Codex finding 4df591987fb7 on #226 (a2f6fab9)
    bad.update({"home by a link": dict(doc, repositories=[one, dict(two, home=str(base / "alias"))]),
                "home by ..": dict(doc, repositories=[one, dict(two, home=str(base / "a" / ".." / "a"))])})
    got = {k: refused(v) for k, v in bad.items()}
    check("W12", ok and all(v for k, v in got.items() if "home by" not in k), "repositories.json is a list of distinct "
          "repositories, each with its own home, mirror and worktree root, a branch name and absolute paths; anything else "
          "serves nothing", got)
    check("W13", got["home by a link"] and got["home by .."], "two entries whose homes are one place by real path (a link, "
          "x/../x) are refused: one repository's done wake would hold the other's", got)
    home = base / "install"
    with patch.object(INSTALL, "HOME", home):
        INSTALL.repositories(False)
        written = WAKER.served(home)
        kept = json.loads((home / WAKER.CONFIG).read_text())
        kept["repositories"].append(two)
        (home / WAKER.CONFIG).write_text(json.dumps(kept))
        INSTALL.repositories(False)
        after = [e["repository"] for e in WAKER.served(home)]
    v3 = json.loads((ROOT / ".warrant" / "v3.json").read_text())["repository"]
    check("C14", [(e["repository"], e["branch"], e["home"], e["checkout"]) for e in written] == [(v3, "master", str(home), str(ROOT))]
          and written[0]["mirror"] == str(home / "warrant.git") and after == [v3, "s0fractal/sokol-core"],
          "install writes the waker's repositories with this checkout's repository as the only entry, its state where the "
          "single-repository waker kept it; an existing configuration is kept", (written, after))


class Agent:
    """A fake reviewer agent: records each command and how it ran (its directory, where its stdout went)."""

    def __init__(self, code=0):
        self.calls, self.code = [], code

    def __call__(self, cmd, **kw):
        out = kw.get("stdout")
        self.calls.append({"cmd": cmd, "cwd": kw.get("cwd"), "stdout": getattr(out, "name", out)})
        return subprocess.CompletedProcess(cmd, self.code)


def reviewers():
    """The reviewer roster (W15-W18): who is woken for a head, how each agent runs, what the configuration admits."""
    base, home, heads = fixture_mirror()
    now = [1_000_000.0]
    roster = [{"actor": "codex", "agent": "codex"}, {"actor": "claude", "agent": "claude", "seed": "/k/claude.seed"}]
    run = Agent()
    w = WAKER.Waker(dict(entry(home, base / "trees"), reviewers=roster), replayers=base / "no-seeds", codex="/bin/codex",
                    claude="/bin/claude", run=run, clock=lambda: now[0])
    by_codex = dict(due_json(heads[0], pr=11), facts=dict(due_json(heads[0])["facts"], author="codex"))
    by_claude = dict(due_json(heads[1], pr=12), facts=dict(due_json(heads[1])["facts"], author="claude"))
    w.wake(by_codex)
    w.wake(by_claude)
    first, second = run.calls
    wt = base / "trees" / f"11-{heads[0][:12]}"
    check("W15", first["cmd"][:2] == ["/bin/claude", "-p"] and "--plugin-dir" in first["cmd"]
          and first["cmd"][first["cmd"].index("--plugin-dir") + 1] == str(w.plugin) and first["cwd"] == str(wt)
          and first["stdout"] == str(home / "results" / f"11-{heads[0]}.md")
          and "you are the actor claude, your seed is /k/claude.seed" in first["cmd"][-1]
          and second["cmd"][:2] == ["/bin/codex", "exec"] and "you are the actor codex." in second["cmd"][-1],
          "the waker wakes the first reviewer of the roster that is not the pull request's author: a head codex wrote is "
          "Claude's (claude -p with the plugin, in the wake's worktree, its last message the result, its seed named), "
          "a head claude wrote is Codex's", [c["cmd"][:2] + [c["cmd"][-1][:90]] for c in run.calls])
    alone = Agent()
    solo = WAKER.Waker(dict(entry(home, base / "trees"), reviewers=[roster[1]]), replayers=base / "no-seeds",
                       codex="/bin/codex", claude="/bin/claude", run=alone, clock=lambda: now[0])
    _, line = solo.wake(dict(by_claude, pr=13))
    check("W16", alone.calls == [] and line.startswith("not woken: no reviewer"),
          "nobody reviews their own pull request: with only its author in the roster, nobody is woken", line)
    failing = Agent(code=1)
    f = WAKER.Waker(dict(entry(home, base / "trees"), reviewers=roster), replayers=base / "no-seeds", codex="/bin/codex",
                    claude="/bin/claude", run=failing, clock=lambda: now[0])
    head = dict(by_codex, pr=14)
    f.wake(head)
    now[0] += WAKER.BACKOFF + 1
    f.reviewers = [roster[1], roster[0]]
    f.wake(dict(head, facts=dict(head["facts"], author="claude")))
    check("W17", [c["cmd"][0] for c in failing.calls] == ["/bin/claude", "/bin/claude"],
          "a head keeps the reviewer its memo names across retries, whatever the roster or the facts say later",
          [c["cmd"][0] for c in failing.calls])
    cfg = Path(tempfile.mkdtemp(prefix="codex-waker-roster-"))
    one = entry(cfg / "a", cfg / "ta")

    def admitted(rs):
        (cfg / WAKER.CONFIG).write_text(json.dumps({"warrant": WAKER.CONFIG_DOC, "repositories": [dict(one, reviewers=rs)]}))
        try:
            return [r["actor"] for r in WAKER.Waker(WAKER.served(cfg)[0], run=Agent()).reviewers]
        except ValueError:
            return None
    got = {"roster": admitted(roster), "empty": admitted([]), "agent": admitted([{"actor": "x", "agent": "gpt"}]),
           "twice": admitted([roster[0], dict(roster[1], actor="codex")]), "relative seed": admitted([dict(roster[1], seed="k")]),
           "extra": admitted([dict(roster[0], token="t")]), "actor": admitted([{"actor": "Bad Actor", "agent": "codex"}])}
    (cfg / WAKER.CONFIG).write_text(json.dumps({"warrant": WAKER.CONFIG_DOC, "repositories": [one]}))
    default = [r["actor"] for r in WAKER.Waker(WAKER.served(cfg)[0], run=Agent()).reviewers]
    check("W18", got["roster"] == ["codex", "claude"] and default == ["codex"]
          and all(v is None for k, v in got.items() if k != "roster"),
          "an entry's reviewers are a non-empty list of distinct actors, each running a known agent, a seed only by an "
          "absolute path; an entry without them is reviewed by codex, as before", dict(got, default=default))

    entries = {}
    for name, value in (("absolute", "/opt/pin/bin/python"), ("relative", "pin/bin/python"), ("not a path", 3)):
        (cfg / WAKER.CONFIG).write_text(json.dumps({"warrant": WAKER.CONFIG_DOC,
                                                    "repositories": [dict(one, replay_python=value)]}))
        try:
            entries[name] = WAKER.Waker(WAKER.served(cfg)[0], run=Agent()).replay_python
        except ValueError:
            entries[name] = None
    pinned = dict(one, replay_python="/opt/pin/bin/python")
    (cfg / WAKER.CONFIG).write_text(json.dumps({"warrant": WAKER.CONFIG_DOC, "repositories": [pinned]}))
    chosen = WAKER.Waker(WAKER.served(cfg)[0], run=Agent(), replay_python="/given/python").replay_python
    check("W19", entries == {"absolute": "/opt/pin/bin/python", "relative": None, "not a path": None}
          and chosen == "/given/python",
          "an entry may name the interpreter its review replays run under (an absolute path: the venv of the "
          "warrant-graph that repository pins), which the waker uses for that repository; an explicit argument "
          "still wins", dict(entries, chosen=chosen))


def carrying():
    """A reviewer's verdict signed in its kept worktree and not committed (Codex's sandbox denied Git's lock files on
    sigma-glyph#80, twice) is carried to the pull request's branch by the waker, only as that reviewer's verdict on the
    head version woken, under the base's keys, while the branch is at the head reviewed (W20)."""
    g = ["-c", "user.name=t", "-c", "user.email=t@invalid", "-c", "commit.gpgsign=false"]
    got = {}
    for case in ("good", "forged", "other version", "branch moved", "base branch", "committed"):
        r = Repo()
        o = r.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
        v = r.entity("alice", "obligation@1", {"state": "done", "statement": "s", "serves": []}, lineage=o)
        wgit(r.root, "init", "-q", "-b", "master")
        base = r.commit("base").strip()
        wgit(r.root, "checkout", "-q", "-b", "topic")
        head = r.commit("the head reviewed").strip()
        wgit(r.root, "checkout", "-q", "master")
        home = r.home / "waker-home"
        home.mkdir()
        subprocess.run(["git", "clone", "-q", "--bare", str(r.root), str(home / "mirror.git")], check=True)
        e = entry(home, r.home / "trees", branch="master", mirror=home / "mirror.git")
        wt = r.home / "trees" / f"7-{head[:12]}"
        wt.parent.mkdir()
        wgit(home / "mirror.git", "worktree", "add", "--detach", "--quiet", str(wt), head)
        signer, target = ("eve" if case == "forged" else "bob"), (o if case == "other version" else v)
        line = R.line(R.record("attest", "bob", r.t + 10, {"verdict": "accept", "target": target}, refs=[target]),
                      KEYS[signer])[1]
        if case == "committed":           # a commit of its own (anything), its verdict left uncommitted on top
            (wt / "stray.txt").write_text("not a verdict")
            subprocess.run(["git", *g, "-C", str(wt), "add", "stray.txt"], check=True)
            subprocess.run(["git", *g, "-C", str(wt), "commit", "-qm", "the reviewer's own commit"], check=True)
        with open(wt / WAKER.RECORDS, "ab") as fh:
            fh.write(line)
        if case == "branch moved":        # rewound behind the head: a push of head + verdict would fast-forward it
            wgit(r.root, "branch", "-f", "topic", base)

        class Carrier(WAKER.Waker):
            def verify(self, code, c, lines, blobs, actor=None):
                import base64
                return WAKER.verify_verdicts({"code": str(code), "actor": actor, "closure": c["closure"],
                                              "lines": [base64.b64encode(x).decode() for x in lines], "blobs": {}})
        w = Carrier(e, replayers=r.home / "none", codex="/bin/codex", run=Codex(), clock=lambda: 0.0)
        a = {"pr": 7, "head": head, "base": base, "branch": "master" if case == "base branch" else "topic",
             "facts": {"closure": v}}
        memo = home / "memo.json"
        doc = {"attempts": [{"worktree": str(wt), "exit": 0, "kept": [" M " + WAKER.RECORDS]}]}
        said = w.carry(a, memo, doc, "bob")
        landed = line in subprocess.run(["git", "-C", str(r.root), "show", f"topic:{WAKER.RECORDS}"],
                                        capture_output=True).stdout
        got[case] = (said.split(":")[0], landed, json.loads(memo.read_text())["attempts"][-1].get("carried", "")[:12],
                     wt.exists())
    check("W20", got["good"] == ("carried", True, "carried: 1 r", False)
          and all(got[k][:2] == ("not carried", False) for k in ("forged", "other version", "base branch", "committed"))
          and got["branch moved"][:2] == ("carrying failed", False) and got["committed"][3] and got["forged"][3],
          "a verdict the reviewer signed in its worktree and did not commit is carried onto the pull request's branch "
          "(one commit of the waker's, pushed while the branch is at the head reviewed) only when it is the reviewer's "
          "own, under the base's keys, on the head version woken; a forged or misdirected one, the base branch, a "
          "worktree the reviewer committed in (its commit is not the waker's to push) and a branch that moved, even "
          "behind the head where the push would fast-forward, carry nothing, and the memo says why", got)


if __name__ == "__main__":
    manifests()
    launcher()
    config_edit()
    dry_install()
    wakes()
    mcp_call()
    store_rules()
    seeds()
    serving()
    ungated()
    configuration()
    reviewers()
    carrying()
    failed = sorted(k for k, v in results.items() if not v)
    print(f"codex plugin: {sum(results.values())} PASS / {len(failed)} FAIL" + (f" ({', '.join(failed)})" if failed else ""))
    sys.exit(1 if failed else 0)
