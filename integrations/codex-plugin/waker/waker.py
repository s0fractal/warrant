#!/usr/bin/env python3
"""The review waker: replay the findings, then start Codex once per pull request head due for review and
once per obligation closure due for his verdict.

launchd runs it every five minutes (install.py). One run:

  1. fetches the base branch into a bare mirror (HOME/warrant.git);
  2. writes the base commit's tree once to HOME/code/<commit> (git archive) and runs THAT tree's
     `tools/review.py due` against the mirror: the due predicate (tools/claimslib/eligibility.py) is
     the base's, never a working tree's, and it reads each pull request's head as Git data only;
  3. for each pull request due, first the review replay checker (replay below); when that pushed
     observations, Codex is not woken in this run: the next run reads the new head once its checks
     are green, and the replay finds nothing left to do there;
  4. for each pull request due, keeps a memo HOME/wakes/<n>-<head>.json, gives the wake its own
     detached worktree of the mirror at that head (TREES/<n>-<head12>; never the operator's
     checkout), runs `codex exec` there with the warrant-review skill (log HOME/logs/<n>-<head>.log,
     Codex's last message HOME/results/<n>-<head>.md), records the attempt's exit status, and removes
     the worktree unless Codex left changes in it.

  5. then the obligation closures due for Codex's verdict: the base tree's `tools/roadmap.py due --actor
     codex` on the base's own records (acceptance_due there: a roadmap obligation's latest closure the
     engine holds PENDING for codex, every duty it requires DISCHARGED, neither accepted nor challenged by
     codex). At most one is woken per run, and none while an open pull request from a branch of this
     repository under VERDICT_BRANCH is open (Codex's previous verdict, not merged yet). Until G11 two such pull requests
     rendered the same generated views from different bases; they carry records only now, and the hold remains a
     limit of one verdict pull request at a time. Its memo is HOME/accepts/<closure>-<item>.json, its
     worktree TREES/accept-<closure12>-<item>-<base12>, detached at the base; Codex accepts the closure or challenges it
     through MCP and opens a pull request of those records only, which the merge gate admits as verdicts
     (eligibility.py). A closure that becomes acceptable later (its prerequisite was accepted meanwhile)
     is due in the run that reads that base.

One wake per head, and per closure: one whose attempt exited 0 is never woken again (delete its memo
to wake it again). An attempt that exited otherwise (or never finished) is retried after BACKOFF
seconds, doubled each time, at most MAX_TRIES attempts in all; then the memo says it gave up.

Replay. The review replay checker is an actor named by the hash of tools/claimslib/review_replay.py
(`checker sha256:<H>`); `tools/review.py replay` signs as it only from code with that hash. The waker
runs the BASE tree's `review.py replay --key -` (the base's reviews.json names the replayer; a pull
request whose head changes review_replay.py is not replayed) in a detached worktree of the head
(TREES/<n>-<head12>-replay), with the checker's seed REPLAYERS/<H>.seed (a regular file of this user,
mode 0600) on standard input only, inside sandbox-exec: no network, no write outside that worktree,
its git directory and a scratch directory HOME/replay-work/<n>-<head>, no read of REPLAYERS or of the
usual credential directories. It replays every mechanical finding of the head's store (any pull
request's, so a finding nobody replayed before is replayed now) at each of its heads no adopted
replayer has observed. The waker commits only the observation records the checker printed (by the
replayer, each with its probe blob), refuses anything else the run left (the generated views are build
artifacts, never committed: G11), and pushes that
commit on the pull request's branch only while the branch is still at the head (a fast-forward).
One replay per head: HOME/replays/<n>-<head>.json, with its runs. A run that failed (the checker exited
otherwise, its output was refused, or its observations did not reach the branch) is not a replay, nor
is one skipped at a head that changes the checker (Codex is woken there as before, and it covers nothing): it runs again after BACKOFF seconds, doubled each
time, at most MAX_TRIES runs, and Codex is not woken at that head meanwhile; once it gave up, Codex is
woken and told so in the prompt. The retry outlives the head being due: a pull request of this repository
not due (a verdict moved its tip) with an incomplete replay is replayed at its current head, and a replay
completed at a later head covers the earlier ones (Codex's challenge 6f72103999cd). No seed, no replay;
but a replay already incomplete at a head records the missing seed as a failed run, so its runs end.
`replay --verify` in CI re-executes every observation new since
the base, and merge eligibility admits these records after the reviewed head (eligibility.py).
Codex, the agent, files its own records with its own seed; no model is given the checker's seed.
HOME is $WARRANT_WAKER_HOME or ~/.warrant/codex-waker; TREES $WARRANT_WAKER_TREES or
~/Projects/.worktrees/codex-review; REPLAYERS $WARRANT_WAKER_REPLAYERS or ~/.warrant-review-replayer
(outside ~/.warrant, which Codex's sandbox may write); the Python that runs the base's tools is
$WARRANT_WAKER_PYTHON or HOME/venv/bin/python (it needs cryptography), the one that runs a replay
$WARRANT_WAKER_REPLAY_PYTHON or that one; Codex is $WARRANT_WAKER_CODEX or `codex` on PATH. The file HOME/HOLD holds it: nothing is woken while it exists. --dry-run does
steps 1 and 2 and prints each due head's and closure's state; it writes no memo, replays nothing and starts
nothing.

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
import stat
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
SANDBOX = "/usr/bin/sandbox-exec"
CHECKER_FILE = "tools/claimslib/review_replay.py"
CHECKER = re.compile(r"checker sha256:([0-9a-f]{64})\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
PROBE = "warrant-review/replay@1"
STORE = ".warrant/store/"
PR_BRANCH = re.compile(r"(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")
SECRETS = (".ssh", ".gnupg", ".config/gh", ".codex", ".claude", "Library/Keychains")
COMMITTER = ["-c", "user.name=warrant review waker", "-c", "user.email=review-waker@s0fractal.invalid",
             "-c", "commit.gpgsign=false"]
REPLAY_TIMEOUT = 3600
ACCEPTOR = "codex"                          # the actor the waker wakes: `codex exec`, signing with its own seed
VERDICT_BRANCH = "codex/verdicts/"          # where Codex pushes a verdict on an obligation closure


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


def record_id(v):
    """A record id (lowercase hex64), checked before it reaches a path."""
    if not (isinstance(v, str) and HEX.match(v)):
        raise ValueError(f"{str(v)[:70]!r} is not a record id")
    return v


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def profile(writable, unreadable):
    """The sandbox-exec profile of a replay: no network, no write outside `writable` (and /dev/null,
    /dev/tty, /dev/fd), no read under `unreadable`. Paths are resolved: the sandbox matches real paths."""
    def q(p):
        s = str(Path(p).resolve())
        if '"' in s or "\\" in s:
            raise ValueError(f"{s[:80]!r} cannot be named in a sandbox profile")
        return f'"{s}"'
    allow = " ".join(f"(subpath {q(p)})" for p in writable)
    return "\n".join(["(version 1)", "(allow default)", "(deny network*)", "(deny file-write*)",
                      f'(allow file-write* {allow} (literal "/dev/null") (literal "/dev/tty") (regex #"^/dev/fd/[0-9]+$"))',
                      *(f"(deny file-read* (subpath {q(p)}))" for p in unreadable), ""])


def sandboxed(cmd, prof, env, stdin=None):
    """Run `cmd` under sandbox-exec with the profile `prof` (macOS)."""
    return subprocess.run([SANDBOX, "-p", prof, *cmd], input=stdin, env=env, capture_output=True, check=False,
                          timeout=REPLAY_TIMEOUT)


def changes(wt, filed, actor):
    """The paths the replay changed in the worktree `wt`, to commit: the records `filed` (the ids the checker
    printed), each an observation by `actor`, and the new blobs among their probes. Anything else (another
    record or blob, a file outside the store, a generated view, a deletion, a link) is a RuntimeError."""
    raw = git("-C", str(wt), "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames").decode()
    entries = [(e[:2], e[3:]) for e in raw.split("\0") if e]
    want = {f"{STORE}records/{o}.json" for o in filed}
    probes, blobs, out = set(), [], []
    for xy, path in entries:
        p = wt / path
        if p.is_symlink() or not p.is_file():
            raise RuntimeError(f"the replay left {xy} {path[:80]}, not a regular file: nothing pushed")
        if xy == "??" and path in want:
            rec = json.loads(p.read_text()).get("record") or {}
            body = rec.get("body") if isinstance(rec.get("body"), dict) else {}
            if not (rec.get("type") == "observation" and rec.get("actor") == actor
                    and isinstance(body.get("probe"), str) and HEX.match(body["probe"])):
                raise RuntimeError(f"{path[:80]} is not an observation by {actor[:28]}: nothing pushed")
            probes.add(body["probe"])
        elif xy == "??" and path.startswith(STORE + "blobs/") and HEX.match(path[len(STORE) + 6:]):
            blobs.append(path)
        else:
            raise RuntimeError(f"the replay left {xy} {path[:80]}: nothing pushed")
        out.append(path)
    if want - set(out):
        raise RuntimeError(f"{len(want - set(out))} record(s) the checker printed are not in the store: nothing pushed")
    for path in blobs:
        name = path[len(STORE) + 6:]
        if name not in probes or (json.loads((wt / path).read_text()).get("probe") != PROBE):
            raise RuntimeError(f"{path[:80]} is not the probe of an observation filed: nothing pushed")
    return sorted(out)


class Skipped(Exception):
    """No replay can run at this head by design: it changes the checker, or its branch is not one to push to."""


class NotPushed(Exception):
    """The checker's run completed, and its observations did not reach the branch (it moved meanwhile)."""


def runs(doc):
    """A replay memo with its runs: one of an older waker (a single run, no `attempts`) reads as one run, failed
    when its line says the checker failed or its observations were not pushed (Codex finding on #204: that waker
    wrote "replay not pushed" after a lost branch race), skipped when it says so, else done."""
    if "attempts" not in doc:
        line = str(doc.get("line", "replayed"))
        failed = line.startswith(("replay failed", "replay not pushed"))
        skipped = line.startswith("replay skipped")
        doc["attempts"] = [{"finished": 0, "ok": not (failed or skipped), "line": line, **({"skipped": True} if skipped else {})}]
    return doc


class Waker:
    def __init__(self, home=None, trees=None, python=None, codex=None, plugin=PLUGIN,
                 run=subprocess.run, clock=time.time, replayers=None, replay_python=None, jail=sandboxed):
        env = os.environ.get
        self.home = Path(home or env("WARRANT_WAKER_HOME") or Path.home() / ".warrant" / "codex-waker")
        self.trees = Path(trees or env("WARRANT_WAKER_TREES") or Path.home() / "Projects" / ".worktrees" / "codex-review")
        self.python = str(python or env("WARRANT_WAKER_PYTHON") or self.home / "venv" / "bin" / "python")
        self.codex = str(codex or env("WARRANT_WAKER_CODEX") or shutil.which("codex") or "/opt/homebrew/bin/codex")
        self.replayers = Path(replayers or env("WARRANT_WAKER_REPLAYERS") or Path.home() / ".warrant-review-replayer")
        self.replay_python = str(replay_python or env("WARRANT_WAKER_REPLAY_PYTHON") or self.python)
        self.plugin, self.run, self.clock, self.jail = Path(plugin), run, clock, jail
        self.mirror = self.home / "warrant.git"
        for d in ("wakes", "accepts", "logs", "results", "code", "replays", "replay-work"):
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

    def acceptances(self, base):
        """The base tree's `roadmap.py due --actor codex --json` on that tree's own records: {"due": [...]}, the
        obligation closures due for Codex's verdict (tools/roadmap.py acceptance_due), with "refused" when that
        run refused itself (exit 2, e.g. a base older than the `due` command). The receiver-local trust and
        implementation variables are not passed on: the base's records under the base's trust, by its tools."""
        code = self.tree(base)
        env = {k: v for k, v in os.environ.items() if k not in ("WARRANT_IMPL", "WARRANT_CLAIMS_TRUST")}
        env.update(PYTHONPATH=str(code), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([self.python, str(code / "tools" / "roadmap.py"), "--root", str(code), "due", "--actor", ACCEPTOR,
                            "--json"], capture_output=True, env=env, check=False)
        err = r.stderr.decode(errors="replace").strip()
        if r.returncode == 2:
            return {"due": [], "refused": (err.splitlines() or ["exit 2"])[-1]}
        if r.returncode:
            raise RuntimeError(f"roadmap.py due exited {r.returncode}: {err[-800:]}")
        return json.loads(r.stdout)

    # -- the replay before a wake

    def seed(self, code):
        """(the base's current replayer, its seed) for the base tree `code`, or (why not, None)."""
        try:
            actor = json.loads((code / ".warrant" / "reviews.json").read_text())["replayers"][-1]
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return "replay skipped: the base's reviews.json names no replayer", None
        m = CHECKER.match(actor) if isinstance(actor, str) else None
        if m is None:
            return f"replay skipped: {str(actor)[:40]!r} is not a checker actor", None
        path = self.replayers / f"{m.group(1)}.seed"
        try:
            st = path.lstat()
        except OSError:
            return f"replay skipped: no seed {path}", None
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_uid != os.getuid():
            return f"replay skipped: {path} is not a regular file of this user with mode 0600", None
        text = path.read_text().strip()
        if not HEX.match(text):
            return f"replay skipped: {path} is not a seed", None
        return actor, (text + "\n").encode()

    def blob(self, rev, path):
        """The object id of `path` at commit `rev` in the mirror, or None."""
        r = subprocess.run(["git", "-C", str(self.mirror), "rev-parse", "--verify", "--quiet", f"{commit(rev)}:{path}"],
                           capture_output=True, check=False)
        return r.stdout.decode().strip() if r.returncode == 0 else None

    def env(self, work, code):
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "TMPDIR": str(work),
                "PYTHONPATH": str(code), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "en_US.UTF-8"}

    def replay(self, a, base):
        """The review replay checker for due head `a`, before Codex is woken (see the module's Replay).
        (pushed, line): when pushed, Codex is not woken in this run."""
        actor, seed = self.seed(self.tree(base))
        p, doc = self.replay_memo(a)
        if seed is None and doc is None:
            return False, actor             # no memo: a seed placed later serves this head
        state, why = self.replay_state(doc)
        if state != "retry":
            return False, why
        skipped = False
        try:
            if seed is None:                # a replay already incomplete here: the missing seed is a failed run,
                raise RuntimeError(actor)   # so the runs end and Codex is told the gap (Codex finding 77e675a71b60)
            (pushed, line), ok = self._replay(a, base, actor, seed), True
        except Skipped as e:            # no replay can run at this head: neither done nor failed (Codex, #204)
            pushed, line, ok, skipped = False, str(e), False, True
        except NotPushed as e:          # observations that did not reach the branch are no replay (Codex, #204)
            pushed, line, ok = False, str(e), False
        except (subprocess.SubprocessError, RuntimeError, ValueError, OSError) as e:
            pushed, line, ok = False, f"replay failed: {str(e)[:300]}", False
        t = self.clock()
        doc = doc or {"pr": a["pr"], "head": a["head"], "attempts": []}
        doc.update(base=base, replayer=actor, at=iso(t), pushed=pushed, line=line)
        doc["attempts"].append({"at": iso(t), "finished": t, "ok": ok, "line": line, **({"skipped": True} if skipped else {})})
        p.write_text(json.dumps(doc, indent=1))
        if ok:
            self.cover(a)
        return pushed, line

    def replay_memo(self, a):
        """(path, memo) of the replay at `a`'s head, or (path, None). A memo of an older waker (one run, no
        attempts) reads as one attempt, failed when its line says so."""
        p = self.home / "replays" / f"{self.key(a)}.json"
        return p, (runs(json.loads(p.read_text())) if p.is_file() else None)

    def replay_state(self, doc):
        """(what, detail) of a replay memo: done (a run completed, here or at a later head of the pull request,
        `covered_by`), skipped (no replay can run at this head: it changes the checker, or its branch is not one
        to push to; this covers nothing), gave up (MAX_TRIES runs failed), waiting (for its backoff) or retry. A
        failed run is not a replay (Codex's challenge 6f72103999cd: a transient exit 75 was kept as the head's
        replay)."""
        if doc is None:
            return "retry", "first replay"
        tries = doc["attempts"]
        last = tries[-1]
        if last.get("ok") or doc.get("covered_by"):
            return "done", (last.get("line") or "replayed") + (f" (covered by the replay at {doc['covered_by'][:12]})"
                                                               if doc.get("covered_by") and not last.get("ok") else "")
        if last.get("skipped"):
            return "skipped", last.get("line") or "replay skipped"
        if len(tries) >= MAX_TRIES:
            return "gave up", f"replay incomplete: {len(tries)} checker runs failed, the last: {last.get('line')}"
        due_at = last.get("finished", 0) + BACKOFF * 2 ** (len(tries) - 1)
        if self.clock() < due_at:
            return "waiting", f"replay incomplete: run {len(tries)} failed ({last.get('line')}); retry after {iso(due_at)}"
        return "retry", f"replay run {len(tries) + 1} of {MAX_TRIES}"

    def pending(self, n):
        """Whether a replay of pull request `n` is incomplete with runs left (waiting or retry), at any head."""
        return any(self.replay_state(runs(json.loads(p.read_text())))[0] in ("waiting", "retry")
                   for p in (self.home / "replays").glob(f"{number(n)}-*.json"))

    def cover(self, a):
        """A replay completed at `a`'s head replays every finding of its store at each of its heads: the
        incomplete replays of the same pull request at other heads are covered by it."""
        for p in (self.home / "replays").glob(f"{number(a['pr'])}-*.json"):
            doc = runs(json.loads(p.read_text()))
            last = doc["attempts"][-1]
            if doc.get("head") != a["head"] and not last.get("ok") and not last.get("skipped") and not doc.get("covered_by"):
                doc["covered_by"] = a["head"]
                p.write_text(json.dumps(doc, indent=1))

    def discard(self, wt, work):
        if wt.exists():
            subprocess.run(["git", "-C", str(self.mirror), "worktree", "remove", "--force", str(wt)], capture_output=True,
                           check=False)
            shutil.rmtree(wt, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)

    def _replay(self, a, base, actor, seed):
        n, head, branch = number(a["pr"]), commit(a["head"]), a.get("branch")
        if not (isinstance(branch, str) and PR_BRANCH.match(branch) and branch != BRANCH):
            raise Skipped(f"replay skipped: {str(branch)[:40]!r} is not a pull request branch to push to")
        if self.blob(base, CHECKER_FILE) != self.blob(head, CHECKER_FILE):
            raise Skipped(f"replay skipped: #{n} changes {CHECKER_FILE}; it replays once the checker is adopted")
        wt = self.trees / f"{n}-{head[:12]}-replay"
        work = self.home / "replay-work" / self.key(a)
        self.discard(wt, work)
        work.mkdir(parents=True)
        self.trees.mkdir(parents=True, exist_ok=True)
        git("-C", str(self.mirror), "worktree", "add", "--detach", "--quiet", str(wt), head)
        try:
            return self._file(a, base, actor, seed, wt, work, branch)
        finally:
            self.discard(wt, work)

    def _file(self, a, base, actor, seed, wt, work, branch):
        n, head, code = a["pr"], a["head"], self.tree(base)
        gitdir = Path(git("-C", str(wt), "rev-parse", "--absolute-git-dir").decode().strip())
        prof = profile([wt, work, gitdir], [self.replayers, *(Path.home() / s for s in SECRETS)])
        r = self.jail([self.replay_python, str(code / "tools" / "review.py"), "--root", str(wt), "replay", "--key", "-"],
                      prof, self.env(work, code), seed)
        if r.returncode:
            raise RuntimeError(f"the checker exited {r.returncode}: {r.stderr.decode(errors='replace').strip()[-300:]}")
        lines = [x for x in r.stdout.decode().splitlines() if x.split() and HEX.match(x.split()[0])]
        if not lines:
            return False, "replay: nothing to replay"
        paths = changes(wt, [x.split()[0] for x in lines], actor)
        git("-C", str(wt), "add", "--", *paths)
        msg = (f"Review replay of #{n} at {head[:12]}: {len(lines)} observation(s) by {actor[:27]}\n\n" + "\n".join(lines)
               + f"\n\nFiled by the review waker before waking the reviewer: the checker is the base {base[:12]}'s "
               f"{CHECKER_FILE}, run in a sandbox with its own seed; no person or model chose this run.\n")
        git("-C", str(wt), *COMMITTER, "commit", "--quiet", "--no-verify", "-m", msg)
        new = commit(git("-C", str(wt), "rev-parse", "HEAD").decode().strip())
        tip = git("-C", str(wt), "ls-remote", "origin", f"refs/heads/{branch}").decode().split()
        if tip[:1] != [head]:
            raise NotPushed(f"replay not pushed: {branch} is at {(tip or ['nothing'])[0][:12]}, not {head[:12]}")
        git("-C", str(wt), "push", "--quiet", "origin", f"{new}:refs/heads/{branch}")
        return True, f"replay: {len(lines)} observation(s) by {actor[:27]} pushed as {new[:12]} on {branch}"

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

    def command(self, a, path, incomplete=None):
        return self.codex_exec(path, self.key(a), prompt(a, self.plugin, path, incomplete))

    def codex_exec(self, path, key, text):
        if path.resolve() == OPERATOR_CHECKOUT.resolve():
            raise ValueError(f"{path} is the operator's checkout: a wake runs in its own worktree")
        return [self.codex, "exec", "-C", str(path), "-s", "workspace-write",
                "-c", "sandbox_workspace_write.network_access=true", "-c", 'approval_policy="never"',
                "--add-dir", str(Path.home() / ".warrant"),
                "-o", str(self.home / "results" / f"{key}.md"), text]

    def wake(self, a, incomplete=None):
        """Wake Codex for Assessment JSON `a` when its memo's state allows; `incomplete` says why the replay at
        its head gave up, for the prompt. (key, what happened)."""
        p, doc = self.memo(a)
        doc = doc or {"pr": a["pr"], "head": a["head"], "base": a["base"], "facts": a["facts"], "attempts": []}
        return self.key(a), self.attempt(p, doc, self.key(a), lambda: self.worktree(a),
                                         lambda path: self.command(a, path, incomplete))[1]

    def attempt(self, p, doc, key, worktree, command):
        """One attempt of the wake whose memo `p` holds `doc`, when its state allows: the memo is written before
        Codex runs (a crash counts as an attempt), `command(path)` runs in `worktree()`, which is removed after
        unless Codex left changes in it. (whether Codex was started, what happened)."""
        what, detail = self.state(doc)
        if what != "retry":
            return False, detail
        t = self.clock()
        attempt = {"started": t, "started_at": iso(t)}
        doc["attempts"].append(attempt)
        p.write_text(json.dumps(doc, indent=1))
        path = worktree()
        attempt["worktree"] = str(path)
        with open(self.home / "logs" / f"{key}.log", "ab") as log:
            r = self.run(command(path), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         check=False, timeout=4 * 3600)
        attempt.update(finished=self.clock(), exit=r.returncode)
        left = git("-C", str(path), "status", "--porcelain", "--untracked-files=all").decode().splitlines()
        if left:
            attempt["kept"] = left[:20]
        else:
            git("-C", str(self.mirror), "worktree", "remove", str(path))
        p.write_text(json.dumps(doc, indent=1))
        return True, f"woken, codex exited {r.returncode}" + (f"; worktree kept: {path}" if left else "")

    def report(self, a, held):
        """The line for a due head that is not woken now (a dry run, or HOME/HOLD)."""
        _, doc = self.memo(a)
        what = self.state(doc)[1] if doc else "not woken yet"
        return what + ("; held (HOME/HOLD)" if held else "; dry run")

    # -- one acceptance wake: an obligation closure due for Codex's verdict

    def accept_key(self, c):
        """<closure>-<item>: a transition that closes several obligations is one wake per item (Codex finding
        3acb42fc0511)."""
        if type(c["item"]) is not int or c["item"] < 0:
            raise ValueError(f"{c['item']!r} is not an item index")
        return f"{record_id(c['closure'])}-{c['item']}"

    def accept_memo(self, c):
        p = self.home / "accepts" / f"{self.accept_key(c)}.json"
        return p, (json.loads(p.read_text()) if p.is_file() else None)

    def accept_worktree(self, c, base):
        """A detached worktree of the mirror at the base, its own for this closure item and base."""
        self.accept_key(c)
        path = self.trees / f"accept-{c['closure'][:12]}-{c['item']}-{commit(base)[:12]}"
        if not path.exists():
            self.trees.mkdir(parents=True, exist_ok=True)
            git("-C", str(self.mirror), "worktree", "add", "--detach", "--quiet", str(path), base)
        return path

    def accept(self, c, base, why_not=None):
        """(woken, line) for obligation closure `c` (an entry of `roadmap.py due`) at the base: Codex is woken
        when its memo's state allows and nothing holds it (`why_not`: a dry run, HOME/HOLD, an open verdict
        pull request, a wake already started in this run); one memo per closure item, whatever the base."""
        p, doc = self.accept_memo(c)
        if why_not:
            what, detail = self.state(doc) if doc else ("retry", "not woken yet")
            return False, detail + (f"; {why_not}" if what == "retry" else "")
        key = f"accept-{self.accept_key(c)}"
        doc = doc or {"closure": c["closure"], "item": c["item"], "duty": c["duty"], "base": base, "attempts": []}
        return self.attempt(p, doc, key, lambda: self.accept_worktree(c, base),
                            lambda path: self.codex_exec(path, key, accept_prompt(c, base, self.plugin, path)))


def prompt(a, plugin, path, incomplete=None):
    f = a["facts"]
    gap = ("" if incomplete is None else
           f" The review replay checker did not complete at H ({incomplete}): no checker observation covers this "
           "head's mechanical findings. Run them yourself before you rely on them, and say in your verdict that the "
           "replay was incomplete.")
    return (f"Use the warrant-review skill ($warrant-review). Pull request {REPO}#{a['pr']} is due for review: "
            f"branch {a.get('branch')}, head H {a['head']}; duty D {f.get('duty')}; head closure T {f.get('closure')} "
            f"(head {f.get('head_n')}) at commit X {f.get('x')}; base {BRANCH} M {a['base']}. Your worktree is {path}, "
            f"detached at H (its remote origin is the repository). The plugin's stdio MCP client is "
            f"{plugin / 'scripts' / 'warrant-mcp-call'}. These facts come from `tools/review.py due` at M, run by the "
            "review waker; check them yourself before you rely on them." + gap)


def accept_prompt(c, base, plugin, path):
    """What Codex is told about closure `c`: what to look at and where (the duty's text, the closure's evidence
    ids, the references and subject that evidence names), never what the closure says it established."""
    def ids(xs):
        return "; ".join(str(x)[:200] for x in xs[:20]) or "none"
    return (f"Use the warrant-review skill ($warrant-review), section \"A verdict on an obligation closure\". On "
            f"{REPO} {BRANCH} M {base}, the closure T {c['closure']} (item {c['item']}) of the roadmap obligation D "
            f"{c['duty']} (goal {c.get('goal')}) awaits a verdict by {ACCEPTOR}. D owes: {json.dumps(c['statement'])}. "
            f"T's evidence: {ids(c['evidence'])}; the pull requests and commits that evidence names: {ids(c['refs'])}; "
            f"T's subject: {c.get('subject') or 'none'}; D requires: {ids(c['requires'])}. Your worktree is {path}, "
            f"detached at M (its remote origin is the repository). The plugin's stdio MCP client is "
            f"{plugin / 'scripts' / 'warrant-mcp-call'}. Judge whether what D owes is done; then accept T item "
            f"{c['item']}, or challenge T, through MCP. Commit only that record (and its blobs) on the branch "
            f"{VERDICT_BRANCH}{c['closure'][:12]}-{c['item']}, push it and open a pull request into {BRANCH}. These facts come from "
            f"`tools/roadmap.py due --actor {ACCEPTOR}` at M, run by the review waker; check them yourself before you "
            "rely on them.")


def tick(w, dry):
    """One run: the lines it prints."""
    base = w.fetch()
    found = w.due(base)
    out = [f"{iso(w.clock())} base {BRANCH} {base[:12]}: {len(found['due'])} due, {len(found['not_due'])} not due"
           + (f"; nothing assessed: {found['refused']}" if found.get("refused") else "")]
    out += [f"  not due #{x['pr']} {x['head'][:12]}: {', '.join(c for c, _ in x['not_due'])}" for x in found["not_due"]]
    held = (w.home / "HOLD").exists()
    for x in found["due"]:
        if dry or held:
            line = w.report(x, held)
        else:
            pushed, line = w.replay(x, base)
            if not pushed:
                line += "; " + wake_after_replay(w, x)
        out.append(f"  DUE #{x['pr']} {x['head'][:12]}: {line}")
    if not (dry or held):
        out += retry_lines(w, base, found)
    return out + acceptance_lines(w, base, found, dry, held)


def wake_after_replay(w, x):
    """What happens to due head `x` once its replay did not push: Codex is woken when the replay completed (or
    none could run: no seed, or the head changes the checker), not while it is incomplete with runs left, and, once it gave up, woken with that
    said in the prompt (a reviewer told of the gap can replay the findings itself; one never woken leaves the
    pull request unreviewed)."""
    _, doc = w.replay_memo(x)
    what, detail = w.replay_state(doc) if doc is not None else ("done", "")
    if what in ("waiting", "retry"):
        return "not woken: the replay is incomplete"
    return w.wake(x, detail if what == "gave up" else None)[1]


def retry_lines(w, base, found):
    """An incomplete replay outlives the head being due: a pull request of this repository that is not due (a
    verdict at its head moved it, its checks run) and has an incomplete replay with runs left is replayed again at
    its current head. Nobody is woken here."""
    out = []
    for x in found["not_due"]:
        if x.get("head_repo") == REPO and w.pending(x["pr"]):
            _, doc = w.replay_memo(x)
            if doc is None or w.replay_state(doc)[0] in ("waiting", "retry"):    # a head that skipped stays quiet
                out.append(f"  RETRY #{x['pr']} {x['head'][:12]}: {w.replay(x, base)[1]}")
    return out


def hold(found, dry, held):
    """Why no acceptance wake starts in this run, or None."""
    if dry:
        return "dry run"
    if held:
        return "held (HOME/HOLD)"
    if found.get("refused"):
        return "held: the open pull requests were not read"
    # this repository's branches only: a fork may name its branch anything (Codex finding 91ee68a60abe)
    verdicts = [x for x in found["due"] + found["not_due"] if x.get("head_repo") == REPO
                and str(x.get("branch") or "").startswith(VERDICT_BRANCH)]
    if verdicts:
        return f"held: verdict pull request #{verdicts[0]['pr']} is open"
    return None


def acceptance_lines(w, base, found, dry, held):
    """The obligation closures due for Codex's verdict at the base: at most one woken per run, none while a
    verdict pull request is open (or the open pull requests could not be read)."""
    got = w.acceptances(base)
    out = [f"  {len(got['due'])} obligation closure(s) due for {ACCEPTOR}'s verdict"
           + (f"; nothing assessed: {got['refused']}" if got.get("refused") else "")]
    why_not = hold(found, dry, held)
    for c in got["due"]:
        woken, line = w.accept(c, base, why_not)
        if woken:
            why_not = "next run: one verdict at a time"
        out.append(f"  ACCEPT {c['closure'][:12]} of {c.get('goal')} duty {c['duty'][:12]}: {line}")
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
