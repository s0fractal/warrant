#!/usr/bin/env python3
"""The review waker: start Codex once per pull request head that is due for review.

launchd runs it every five minutes (install.py). One run:

  1. fetches the base branch into a bare mirror (HOME/warrant.git);
  2. writes the base commit's tree once to HOME/code/<commit> (git archive) and runs THAT tree's
     `tools/review.py due` against the mirror: the due predicate (tools/claimslib/eligibility.py) is
     the base's, never a working tree's, and it reads each pull request's head as Git data only;
  3. for each pull request due, creates HOME/wakes/<n>-<head>.json exclusively (one wake per head;
     delete the memo to wake that head again) and runs `codex exec` with the warrant-review skill,
     logging to HOME/logs/<n>-<head>.log and keeping Codex's last message in HOME/results/; the memo
     records how it ended.

The waker signs nothing and reads no key: Codex, the agent, files its own records with its own seed.
HOME is ~/.warrant/codex-waker (--home). The file HOME/HOLD holds it: nothing is woken while it
exists. --dry-run does steps 1 and 2, prints what it would wake, writes no memo and starts nothing.

    python3 waker.py [--dry-run] [--home DIR] [--python VENV_PYTHON] [--codex PATH]
"""
import argparse
import datetime
import fcntl
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = "s0fractal/warrant"
BRANCH = "master"
HOME = Path.home() / ".warrant" / "codex-waker"
PLUGIN = Path(__file__).resolve().parents[1]
KEEP_TREES = 3


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def git(*args, **kw):
    return subprocess.run(["git", *args], capture_output=True, check=True, **kw).stdout


def mirror(home, repo):
    m = home / "warrant.git"
    if not (m / "HEAD").is_file():
        git("clone", "--bare", "--quiet", f"https://github.com/{repo}.git", str(m))
    git("-C", str(m), "fetch", "--quiet", "--no-tags", "origin", f"+refs/heads/{BRANCH}:refs/heads/{BRANCH}")
    return m, git("-C", str(m), "rev-parse", "--verify", f"refs/heads/{BRANCH}^{{commit}}").decode().strip()


def tree(home, m, base):
    """HOME/code/<base>: the base commit's tree, written once (to a fresh directory, then renamed)."""
    code = home / "code"
    out = code / base
    if not out.is_dir():
        code.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{base[:12]}-", dir=code))
        data = git("-C", str(m), "archive", "--format=tar", base)
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(tmp, filter="data")
        os.rename(tmp, out)
    for old in sorted((p for p in code.iterdir() if p.is_dir() and p != out and not p.name.startswith(".")),
                      key=lambda p: p.stat().st_mtime)[:-KEEP_TREES or None]:
        shutil.rmtree(old, ignore_errors=True)
    return out


def due(python, code, m, base):
    """The base tree's `review.py due --json`: {"due": [...], "not_due": [...]}, with "refused" when that run
    refused itself (exit 2: `REFUSED <CODE> ...`, e.g. the base has no .warrant/merge.json or moved meanwhile,
    or a usage error: a base older than the `due` command)."""
    env = dict(os.environ, PYTHONPATH=str(code), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([python, str(code / "tools" / "review.py"), "--root", str(m), "due", "--base", base, "--json"],
                       capture_output=True, env=env, check=False)
    err = r.stderr.decode(errors="replace").strip()
    if r.returncode == 2:
        lines = err.splitlines() or ["exit 2"]
        return {"due": [], "not_due": [], "refused": lines[0] if err.startswith("REFUSED ") else lines[-1]}
    if r.returncode:
        raise RuntimeError(f"review.py due exited {r.returncode}: {r.stderr.decode(errors='replace')[-800:]}")
    return json.loads(r.stdout)


def prompt(a, plugin):
    f = a["facts"]
    return (f"Use the warrant-review skill ($warrant-review). Pull request {REPO}#{a['pr']} is due "
            f"for review: branch {a.get('branch')}, head H {a['head']}; duty D {f.get('duty')}; head closure T "
            f"{f.get('closure')} (head {f.get('head_n')}) at commit X {f.get('x')}; base {BRANCH} M {a['base']}. "
            f"The plugin's stdio MCP client is {plugin / 'scripts' / 'warrant-mcp-call'}. These facts come from "
            "`tools/review.py due` at M, run by the review waker; check them yourself before you rely on them.")


def codex_command(codex, home, key, text):
    worktrees = Path.home() / "Projects" / ".worktrees"
    return [codex, "exec", "-C", str(Path.home() / "Projects" / "warrant"), "-s", "workspace-write",
            "-c", "sandbox_workspace_write.network_access=true", "-c", 'approval_policy="never"',
            "--add-dir", str(worktrees), "--add-dir", str(Path.home() / ".warrant"),
            "-o", str(home / "results" / f"{key}.md"), text]


def wake(a, home, codex, plugin, run=subprocess.run):
    """Wake Codex for Assessment JSON `a` unless its memo exists. (key, state)."""
    key = f"{a['pr']}-{a['head']}"
    memo = home / "wakes" / f"{key}.json"
    try:
        fd = os.open(memo, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return key, "already woken"
    doc = {"pr": a["pr"], "head": a["head"], "base": a["base"], "facts": a["facts"], "started": now(),
           "log": str(home / "logs" / f"{key}.log")}
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f, indent=1)
    with open(doc["log"], "ab") as log:
        r = run(codex_command(codex, home, key, prompt(a, plugin)), stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, check=False, timeout=4 * 3600)
    doc.update(finished=now(), exit=r.returncode)
    memo.write_text(json.dumps(doc, indent=1))
    return key, f"woken, codex exited {r.returncode}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--home", default=str(HOME))
    ap.add_argument("--python", default=str(HOME / "venv" / "bin" / "python"),
                    help="a Python with cryptography, to run the base's tools/review.py")
    ap.add_argument("--codex", default=shutil.which("codex") or "/opt/homebrew/bin/codex")
    ap.add_argument("--plugin", default=str(PLUGIN))
    a = ap.parse_args(argv)
    home = Path(a.home)
    for d in ("wakes", "logs", "results", "code"):
        (home / d).mkdir(parents=True, exist_ok=True)
    with open(home / "lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"{now()} another waker run holds {home / 'lock'}")
            return 0
        m, base = mirror(home, REPO)
        found = due(a.python, tree(home, m, base), m, base)
        print(f"{now()} base {BRANCH} {base[:12]}: {len(found['due'])} due, {len(found['not_due'])} not due"
              + (f"; nothing assessed: {found['refused']}" if found.get("refused") else ""))
        for x in found["not_due"]:
            print(f"  not due #{x['pr']} {x['head'][:12]}: {', '.join(c for c, _ in x['not_due'])}")
        held = (home / "HOLD").exists()
        for x in found["due"]:
            key = f"{x['pr']}-{x['head']}"
            if a.dry_run or held:
                seen = (home / "wakes" / f"{key}.json").exists()
                print(f"  DUE #{x['pr']} {x['head'][:12]}: " + ("already woken" if seen else
                      "held (HOME/HOLD)" if held else "would wake codex"))
                continue
            print(f"  DUE #{x['pr']} {x['head'][:12]}: " + wake(x, home, a.codex, Path(a.plugin))[1], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
