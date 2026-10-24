#!/usr/bin/env python3
"""The Codex plugin and its waker, without Codex and without GitHub (C1-C13).

    python3 integrations/codex-plugin/test_plugin.py      (C8 needs the optional dependency `mcp`)
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

from agent_world import PROFILE, USES, Key, Party       # noqa: E402

results = {}


def check(cid, ok, what, detail=""):
    results[cid] = ok
    print(("ok    " if ok else "FAIL  ") + f"{cid} {what}" + ("" if ok else f" | {detail}"), flush=True)


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
          and "Sign only as `codex`" in skill and "/tmp" in skill,
          "the skill names itself, points to the review recipe, and states who signs and where files go")


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
    w = WAKER.Waker(home=home, trees=base / "trees", codex="/bin/codex", run=codex, clock=lambda: now[0])
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
          and wt.resolve() != WAKER.OPERATOR_CHECKOUT.resolve() and not wt.exists()
          and memo["attempts"][0]["worktree"] == str(wt),
          "each wake runs in its own worktree of the mirror, never the operator's checkout, removed after a clean run",
          (wt, memo))
    refused = None
    try:
        w.command(a, WAKER.OPERATOR_CHECKOUT)
    except ValueError as e:
        refused = str(e)
    dirty = WAKER.Waker(home=home, trees=base / "trees", codex="/bin/codex", run=Codex(dirty=True), clock=lambda: now[0])
    out = dirty.wake(due_json(heads[1], pr=8))[1]
    kept = base / "trees" / f"8-{heads[1][:12]}"
    head_there = subprocess.run(["git", "-C", str(kept), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    check("C11", refused is not None and "kept" in out and (kept / "left.txt").is_file() and head_there == heads[1],
          "the operator's checkout is refused as a wake's directory; a worktree Codex left changes in is kept, "
          "detached at the head", (refused, out, head_there))

    failing = Codex(code=1)
    f = WAKER.Waker(home=home, trees=base / "trees", codex="/bin/codex", run=failing, clock=lambda: now[0])
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
        print("skip  C8 (no mcp)")
        return
    d = Path(tempfile.mkdtemp(prefix="codex-plugin-mcp-"))
    keys = {a: Key.generate() for a in ("producer", "reviewer", "auditor", "receiver")}
    Party(d, "src", "producer", keys, PROFILE, USES)
    server = d / "server"
    impl = os.environ.get("WARRANT_IMPL") or str(ROOT)
    server.write_text(f'#!/bin/sh\nPYTHONPATH="{impl}" exec "{sys.executable}" -m warrant_agent.mcp_server "$@"\n')
    server.chmod(0o755)
    env = dict(os.environ, WARRANT_AGENT_MCP=str(server))

    def call(tool, args):
        r = subprocess.run([sys.executable, str(HERE / "scripts" / "warrant-mcp-call"), "--config", str(d / "src" / "config.json"),
                            tool, json.dumps(args)], env=env, capture_output=True, text=True)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip() else r.stderr
    rc1, ws = call("workspace", {})
    body = {"holder": "producer", "statement": "the plugin's stdio client files a duty", "owed_to": ["reviewer"],
            "accept_by": ["reviewer"], "condition": {"attest": {}}}
    rc2, prep = call("prepare", {"workspace": "src", "type": "duty", "body": body})
    rc3, done = call("commit", {"workspace": "src", "draft_id": prep.get("draft_id") if isinstance(prep, dict) else None})
    rid = done.get("record_id") or done.get("id") if isinstance(done, dict) else None
    stored = [f.stem for f in (d / "src" / "store" / "records").iterdir()]
    check("C8", (rc1, rc2, rc3) == (0, 0, 0) and isinstance(ws, dict) and len(stored) == 1 and (rid is None or rid in stored),
          "warrant-mcp-call drives the warrant MCP server for a given configuration, one tool per process: a prepare "
          "and its commit in two calls file one record", (rc1, ws, rc2, prep, rc3, done, stored))
    rc4, err = call("commit", {"workspace": "src", "draft_id": "0" * 32})
    check("C9", rc4 == 2, "a refusal of the server exits 2", (rc4, err))


if __name__ == "__main__":
    manifests()
    launcher()
    config_edit()
    dry_install()
    wakes()
    mcp_call()
    failed = sorted(k for k, v in results.items() if not v)
    print(f"codex plugin: {sum(results.values())} PASS / {len(failed)} FAIL" + (f" ({', '.join(failed)})" if failed else ""))
    sys.exit(1 if failed else 0)
