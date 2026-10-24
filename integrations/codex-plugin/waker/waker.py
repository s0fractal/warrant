#!/usr/bin/env python3
"""The review waker: start Codex once per pull request head that is due for review.

launchd runs it every five minutes (install.py). One run:

  1. fetches the base branch into a bare mirror (HOME/warrant.git);
  2. writes the base commit's tree once to HOME/code/<commit> (git archive) and runs THAT tree's
     `tools/review.py due` against the mirror: the due predicate (tools/claimslib/eligibility.py) is
     the base's, never a working tree's, and it reads each pull request's head as Git data only;
  3. for each pull request due, keeps a memo HOME/wakes/<n>-<head>.json, gives the wake its own
     detached worktree of the mirror at that head (TREES/<n>-<head12>; never the operator's
     checkout), runs `codex exec` there with the warrant-review skill (log HOME/logs/<n>-<head>.log,
     Codex's last message HOME/results/<n>-<head>.md), records the attempt's exit status, and removes
     the worktree unless Codex left changes in it.

One wake per head: a head whose attempt exited 0 is never woken again (delete its memo to wake it
again). An attempt that exited otherwise (or never finished) is retried after BACKOFF seconds,
doubled each time, at most MAX_TRIES attempts in all; then the memo says it gave up.

The waker signs nothing and reads no key: Codex, the agent, files its own records with its own seed.
HOME is $WARRANT_WAKER_HOME or ~/.warrant/codex-waker; TREES $WARRANT_WAKER_TREES or
~/Projects/.worktrees/codex-review; the Python that runs the base's tools is
$WARRANT_WAKER_PYTHON or HOME/venv/bin/python (it needs cryptography); Codex is $WARRANT_WAKER_CODEX
or `codex` on PATH. The file HOME/HOLD holds it: nothing is woken while it exists. --dry-run does
steps 1 and 2 and prints each due head's state; it writes no memo and starts nothing.

    python3 waker.py [--dry-run]
"""
import argparse
import datetime
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = "s0fractal/warrant"
BRANCH = "master"
PLUGIN = Path(__file__).resolve().parents[1]
KEEP_TREES = 3
MAX_TRIES = 3
BACKOFF = 900
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
OPERATOR_CHECKOUT = Path.home() / "Projects" / "warrant"


def iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(timespec="seconds")


def commit(v):
    """A full lowercase commit id, checked before it reaches Git or a path."""
    if not (isinstance(v, str) and COMMIT.match(v)):
        raise ValueError(f"{str(v)[:50]!r} is not a full commit id")
    return v


def number(v):
    if type(v) is not int or v < 1:
        raise ValueError(f"{v!r} is not a pull request number")
    return v


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


class Waker:
    def __init__(self, home=None, trees=None, python=None, codex=None, plugin=PLUGIN,
                 run=subprocess.run, clock=time.time):
        env = os.environ.get
        self.home = Path(home or env("WARRANT_WAKER_HOME") or Path.home() / ".warrant" / "codex-waker")
        self.trees = Path(trees or env("WARRANT_WAKER_TREES") or Path.home() / "Projects" / ".worktrees" / "codex-review")
        self.python = str(python or env("WARRANT_WAKER_PYTHON") or self.home / "venv" / "bin" / "python")
        self.codex = str(codex or env("WARRANT_WAKER_CODEX") or shutil.which("codex") or "/opt/homebrew/bin/codex")
        self.plugin, self.run, self.clock = Path(plugin), run, clock
        self.mirror = self.home / "warrant.git"
        for d in ("wakes", "logs", "results", "code"):
            (self.home / d).mkdir(parents=True, exist_ok=True)

    # -- the base and its predicate

    def fetch(self):
        if not (self.mirror / "HEAD").is_file():
            git("clone", "--bare", "--quiet", f"https://github.com/{REPO}.git", str(self.mirror))
        git("-C", str(self.mirror), "fetch", "--quiet", "--no-tags", "origin", f"+refs/heads/{BRANCH}:refs/heads/{BRANCH}")
        git("-C", str(self.mirror), "worktree", "prune")
        return commit(git("-C", str(self.mirror), "rev-parse", "--verify", f"refs/heads/{BRANCH}^{{commit}}").decode().strip())

    def tree(self, base):
        """HOME/code/<base>: the base commit's tree, written once (to a fresh directory, then renamed)."""
        code = self.home / "code"
        out = code / commit(base)
        if not out.is_dir():
            tmp = Path(tempfile.mkdtemp(prefix=f".{base[:12]}-", dir=code))
            with tarfile.open(fileobj=io.BytesIO(git("-C", str(self.mirror), "archive", "--format=tar", base))) as t:
                t.extractall(tmp, filter="data")
            os.rename(tmp, out)
        old = sorted((p for p in code.iterdir() if p.is_dir() and p != out and not p.name.startswith(".")),
                     key=lambda p: p.stat().st_mtime)
        for p in old[:max(0, len(old) - KEEP_TREES)]:
            shutil.rmtree(p, ignore_errors=True)
        return out

    def due(self, base):
        """The base tree's `review.py due --json`: {"due": [...], "not_due": [...]}, with "refused" when that
        run refused itself (exit 2: `REFUSED <CODE> ...`, e.g. the base has no .warrant/merge.json or moved
        meanwhile, or a usage error: a base older than the `due` command)."""
        code = self.tree(base)
        env = dict(os.environ, PYTHONPATH=str(code), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([self.python, str(code / "tools" / "review.py"), "--root", str(self.mirror), "due",
                            "--base", base, "--json"], capture_output=True, env=env, check=False)
        err = r.stderr.decode(errors="replace").strip()
        if r.returncode == 2:
            lines = err.splitlines() or ["exit 2"]
            return {"due": [], "not_due": [], "refused": lines[0] if err.startswith("REFUSED ") else lines[-1]}
        if r.returncode:
            raise RuntimeError(f"review.py due exited {r.returncode}: {err[-800:]}")
        return json.loads(r.stdout)

    # -- one wake

    def key(self, a):
        return f"{number(a['pr'])}-{commit(a['head'])}"

    def state(self, doc):
        """(what, detail) of a memo: done, gave up, waiting (for its backoff) or retry."""
        tries = doc.get("attempts", [])
        last = tries[-1] if tries else None
        if last is None:
            return "retry", "first attempt"
        if last.get("exit") == 0:
            return "done", f"done: woken {last.get('started_at')}, codex exited 0"
        if len(tries) >= MAX_TRIES:
            return "gave up", f"gave up: {len(tries)} attempts failed (last exit {last.get('exit')}); delete the memo to retry"
        due_at = (last.get("finished") or last.get("started", 0)) + BACKOFF * 2 ** (len(tries) - 1)
        if self.clock() < due_at:
            return "waiting", f"waiting: attempt {len(tries)} exited {last.get('exit')}; retry after {iso(due_at)}"
        return "retry", f"attempt {len(tries) + 1} of {MAX_TRIES}"

    def memo(self, a):
        p = self.home / "wakes" / f"{self.key(a)}.json"
        return p, (json.loads(p.read_text()) if p.is_file() else None)

    def worktree(self, a):
        """A detached worktree of the mirror at the pull request's head, its own for this wake."""
        path = self.trees / f"{number(a['pr'])}-{commit(a['head'])[:12]}"
        if not path.exists():
            self.trees.mkdir(parents=True, exist_ok=True)
            git("-C", str(self.mirror), "worktree", "add", "--detach", "--quiet", str(path), a["head"])
        return path

    def command(self, a, path):
        if path.resolve() == OPERATOR_CHECKOUT.resolve():
            raise ValueError(f"{path} is the operator's checkout: a wake runs in its own worktree")
        return [self.codex, "exec", "-C", str(path), "-s", "workspace-write",
                "-c", "sandbox_workspace_write.network_access=true", "-c", 'approval_policy="never"',
                "--add-dir", str(Path.home() / ".warrant"),
                "-o", str(self.home / "results" / f"{self.key(a)}.md"), prompt(a, self.plugin, path)]

    def wake(self, a):
        """Wake Codex for Assessment JSON `a` when its memo's state allows. (key, what happened)."""
        p, doc = self.memo(a)
        if doc is not None:
            what, detail = self.state(doc)
            if what != "retry":
                return self.key(a), detail
        doc = doc or {"pr": a["pr"], "head": a["head"], "base": a["base"], "facts": a["facts"], "attempts": []}
        t = self.clock()
        attempt = {"started": t, "started_at": iso(t)}
        doc["attempts"].append(attempt)
        p.write_text(json.dumps(doc, indent=1))       # before Codex runs: a crash counts as an attempt
        path = self.worktree(a)
        attempt["worktree"] = str(path)
        with open(self.home / "logs" / f"{self.key(a)}.log", "ab") as log:
            r = self.run(self.command(a, path), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         check=False, timeout=4 * 3600)
        attempt.update(finished=self.clock(), exit=r.returncode)
        left = git("-C", str(path), "status", "--porcelain", "--untracked-files=all").decode().splitlines()
        if left:
            attempt["kept"] = left[:20]
        else:
            git("-C", str(self.mirror), "worktree", "remove", str(path))
        p.write_text(json.dumps(doc, indent=1))
        return self.key(a), f"woken, codex exited {r.returncode}" + (f"; worktree kept: {path}" if left else "")

    def report(self, a, held):
        """The line for a due head that is not woken now (a dry run, or HOME/HOLD)."""
        _, doc = self.memo(a)
        what = self.state(doc)[1] if doc else "not woken yet"
        return what + ("; held (HOME/HOLD)" if held else "; dry run")


def prompt(a, plugin, path):
    f = a["facts"]
    return (f"Use the warrant-review skill ($warrant-review). Pull request {REPO}#{a['pr']} is due for review: "
            f"branch {a.get('branch')}, head H {a['head']}; duty D {f.get('duty')}; head closure T {f.get('closure')} "
            f"(head {f.get('head_n')}) at commit X {f.get('x')}; base {BRANCH} M {a['base']}. Your worktree is {path}, "
            f"detached at H (its remote origin is the repository). The plugin's stdio MCP client is "
            f"{plugin / 'scripts' / 'warrant-mcp-call'}. These facts come from `tools/review.py due` at M, run by the "
            "review waker; check them yourself before you rely on them.")


def tick(w, dry):
    """One run: the lines it prints."""
    base = w.fetch()
    found = w.due(base)
    out = [f"{iso(w.clock())} base {BRANCH} {base[:12]}: {len(found['due'])} due, {len(found['not_due'])} not due"
           + (f"; nothing assessed: {found['refused']}" if found.get("refused") else "")]
    out += [f"  not due #{x['pr']} {x['head'][:12]}: {', '.join(c for c, _ in x['not_due'])}" for x in found["not_due"]]
    held = (w.home / "HOLD").exists()
    for x in found["due"]:
        line = w.report(x, held) if dry or held else w.wake(x)[1]
        out.append(f"  DUE #{x['pr']} {x['head'][:12]}: {line}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    dry = ap.parse_args(argv).dry_run
    w = Waker()
    with open(w.home / "lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"{iso(w.clock())} another waker run holds {w.home / 'lock'}")
            return 0
        for line in tick(w, dry):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
