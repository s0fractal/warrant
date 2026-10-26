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
     repository under VERDICT_BRANCH is open (Codex's previous verdict, not merged yet: two such pull requests would render the
     same generated views from different bases). Its memo is HOME/accepts/<closure>-<item>.json, its
     worktree TREES/accept-<closure12>-<item>-<base12> (with -<n> from the second attempt on), detached at the
     base; Codex accepts the closure or challenges it through MCP into that worktree's store, and exits. The
     waker, not Codex, publishes it (Waker.publish; Codex's sandbox cannot write the worktree's Git metadata,
     and his GitHub tool needs an approval the `never` policy cannot give: the wake of 836e1789a97a, #210):
     what is new in the worktree's store, checked with the base's own package (verify_verdicts: only codex's
     accepts and challenges of that closure item, authentic under the key the base's roles.json pins, and the
     blobs they cite; anything else, and nothing is published), those bytes copied onto the base, the base's
     own projectors run, one commit by the waker pushed to VERDICT_BRANCH<closure12>-<item> and a pull request
     opened with `gh`, which the merge gate admits as verdicts (eligibility.py). The waker signs nothing. A
     closure that becomes acceptable later (its prerequisite was accepted meanwhile) is due in the run that
     reads that base.

One wake per head, and per closure: one whose attempt exited 0 is never woken again (delete its memo
to wake it again). An attempt that exited otherwise (or never finished) is retried after BACKOFF
seconds, doubled each time, at most MAX_TRIES attempts in all; then the memo says it gave up. An
acceptance wake is done only once its verdict reached GitHub: a pull request from its branch of this
repository exists, in any state, or the base holds codex's verdict on that item (never published twice).
An attempt that exited 0 and left nothing to publish is "unpublished", a failed attempt; a publication
that failed is retried after the same backoff, without waking Codex; the run's lines say which.

Replay. The review replay checker is an actor named by the hash of tools/claimslib/review_replay.py
(`checker sha256:<H>`); `tools/review.py replay` signs as it only from code with that hash. The waker
runs the BASE tree's `review.py replay --key -` (the base's reviews.json names the replayer; a pull
request whose head changes review_replay.py is not replayed) in a detached worktree of the head
(TREES/<n>-<head12>-replay), with the checker's seed REPLAYERS/<H>.seed (a regular file of this user,
mode 0600) on standard input only, inside sandbox-exec: no network, no write outside that worktree,
its git directory and a scratch directory HOME/replay-work/<n>-<head>, no read of REPLAYERS or of the
usual credential directories. It replays every mechanical finding of the head's store (any pull
request's, so a finding nobody replayed before is replayed now) at each of its heads no adopted
replayer has observed. The head's own `project` commands then regenerate the views (same sandbox, no
seed). The waker commits only the observation records the checker printed (by the replayer, each
with its probe blob) and the generated views, refuses anything else the run left, and pushes that
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
import base64
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
VIEWS = ("REVIEWS.md", "ROADMAP.md", "SPEC-CLAIMS.md", "WITNESSES.md")      # reviews.LEDGER_FILES
PROJECTORS = ("tools/review.py", "tools/claims.py", "tools/roadmap.py")
PR_BRANCH = re.compile(r"(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")
SECRETS = (".ssh", ".gnupg", ".config/gh", ".codex", ".claude", "Library/Keychains")
STATUS = ("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")    # every path, renames as two
COMMITTER = ["-c", "user.name=warrant review waker", "-c", "user.email=review-waker@s0fractal.invalid",
             "-c", "commit.gpgsign=false"]
REPLAY_TIMEOUT = 3600
ACCEPTOR = "codex"                          # the actor the waker wakes: `codex exec`, signing with its own seed
VERDICT_BRANCH = "codex/verdicts/"          # where the waker publishes Codex's verdict on an obligation closure
VERDICTS = ("accept", "challenge")          # the records an acceptance wake may publish
BASE_PROJECTORS = ("tools/claims.py", "tools/roadmap.py", "tools/review.py")      # the base's, run on a verdict's tree
MAX_PREPARED = 16 << 20                     # bytes of a prepared verdict's records and blobs, all told


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
    printed), each an observation by `actor`, the new blobs among their probes, and the generated views.
    Anything else (another record or blob, a file outside the store, a deletion, a link) is a RuntimeError."""
    raw = git("-C", str(wt), *STATUS).decode()
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
        elif not (xy == " M" and path in VIEWS):
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


class Unpublished(Exception):
    """Codex's worktree holds no verdict the waker may publish (none, or one it refuses): that wake prepared
    nothing, and Codex is woken again after the backoff."""


def closure_of(body):
    """(transition, item) an accept or a challenge concerns (eligibility._closure_of)."""
    return body.get("transition", body.get("target")), body.get("item")


def cites(v, out):
    """`out` with every hex64 string anywhere in `v`: what a record's body cites (eligibility.uncited)."""
    if isinstance(v, str) and HEX.match(v):
        out.add(v)
    elif isinstance(v, dict):
        for x in v.values():
            cites(x, out)
    elif isinstance(v, list):
        for x in v:
            cites(x, out)
    return out


def stored(path):
    """(kind, the name it claims) of a path under STORE: ("records", <id>) for records/<id>.json, ("blobs", <id>) for
    blobs/<id>, else (kind, "")."""
    kind, _, name = path[len(STORE):].partition("/")
    if kind == "records" and name.endswith(".json"):
        return kind, name[:-5]
    return kind, name if kind == "blobs" else ""


def blob_problem(digest, blobs, cited):
    """Why one of the prepared `blobs` may not be published (not named by its hash, or cited by no verdict), or None."""
    for b, data in sorted(blobs.items()):
        if digest(data) != b:
            return f"blob {b[:12]} is not named by its hash"
        if b not in cited:
            return f"blob {b[:12]} is cited by no verdict"
    return None


def verify_verdicts(req):
    """Why the prepared verdict `req` may not be published, or None. Run with the BASE tree's package first on
    PYTHONPATH (`waker.py --verify-verdicts`, the request on standard input), never in the waker's own process.
    Every record must be authentic under the one key the base's .warrant/roles.json pins for req["actor"] (so
    signed by that actor and named by its id), an accept or a challenge, of exactly the closure item woken; every
    blob named by its hash and cited by one of them; every evidence blob they name among them or in the base's
    store."""
    from warrant import jcs as C
    from warrant.bindings import read_roles
    from warrant.store import Snapshot, Trust
    code, actor, want = Path(req["code"]), req["actor"], (req["closure"], req["item"])
    roles, problems = read_roles(json.loads((code / ".warrant/roles.json").read_text()))
    pin = roles.get(actor)
    if problems or not (isinstance(pin, str) and HEX.match(pin)):
        return f"the base's roles.json pins no key for {actor}"
    recs = {r: base64.b64decode(d) for r, d in req["records"].items()}
    blobs = {b: base64.b64decode(d) for b, d in req["blobs"].items()}
    good, bad = Snapshot(recs, {}).authentic(Trust(Trust.document([(actor, pin)])))
    if bad:
        rid = min(bad)
        return f"record {rid[:12]} is not {actor}'s under the base's pin: {bad[rid]}"
    cited, evidence = set(), set()
    for rid, rec in sorted(good.items()):
        if rec["type"] not in VERDICTS:
            return f"record {rid[:12]} is a {rec['type']}, not a verdict"
        if closure_of(rec["body"]) != want:
            return f"record {rid[:12]} is not a verdict on closure {want[0][:12]} item {want[1]}"
        cites(rec["body"], cited)
        evidence.update(rec["body"]["evidence"])
    why = blob_problem(C.digest, blobs, cited)
    if why:
        return why
    missing = sorted(e for e in evidence if e not in blobs and not (code / STORE / "blobs" / e).is_file())
    if missing:
        return f"evidence {missing[0][:12]} is neither prepared nor in the base's store"
    return None


def held_verdict(code, c):
    """The id of a verdict by ACCEPTOR on closure item `c` that the base tree `code` holds already, or None."""
    for p in sorted((code / STORE / "records").glob("*.json")):
        try:
            rec = json.loads(p.read_bytes())["record"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if (isinstance(rec, dict) and rec.get("actor") == ACCEPTOR and rec.get("type") in VERDICTS
                and isinstance(rec.get("body"), dict) and closure_of(rec["body"]) == (c["closure"], c["item"])):
            return p.name[:-5]
    return None


class Forge:
    """GitHub through this user's `gh`: the pull requests from a branch of REPO, and a new one."""

    def __init__(self, run=subprocess.run, gh=None):
        self.run, self.gh = run, gh or shutil.which("gh") or "/opt/homebrew/bin/gh"

    def pulls(self, branch):
        """[(number, state)] of the pull requests, in any state, from the branch `branch` of REPO itself: a fork's
        branch of the same name is not where the waker publishes."""
        r = self.run([self.gh, "pr", "list", "--repo", REPO, "--head", branch, "--state", "all", "--json",
                      "number,state,headRefName,isCrossRepository"], capture_output=True, check=False, timeout=120)
        if r.returncode:
            raise RuntimeError(f"gh pr list exited {r.returncode}: {r.stderr.decode(errors='replace').strip()[-300:]}")
        return [(x["number"], x["state"]) for x in json.loads(r.stdout)
                if x.get("headRefName") == branch and x.get("isCrossRepository") is False]

    def open(self, branch, title, body):
        """The number of a new pull request from `branch` into BRANCH."""
        r = self.run([self.gh, "pr", "create", "--repo", REPO, "--base", BRANCH, "--head", branch, "--title", title,
                      "--body-file", "-"], input=body.encode(), capture_output=True, check=False, timeout=120)
        url = r.stdout.decode(errors="replace").strip().splitlines()[-1:] or [""]
        m = re.search(r"/pull/(\d+)\Z", url[0], re.ASCII)
        if r.returncode or m is None:
            raise RuntimeError(f"gh pr create exited {r.returncode}: {r.stderr.decode(errors='replace').strip()[-300:]}")
        return int(m.group(1))


class Waker:
    def __init__(self, home=None, trees=None, python=None, codex=None, plugin=PLUGIN,
                 run=subprocess.run, clock=time.time, replayers=None, replay_python=None, jail=sandboxed, forge=None):
        env = os.environ.get
        self.home = Path(home or env("WARRANT_WAKER_HOME") or Path.home() / ".warrant" / "codex-waker")
        self.trees = Path(trees or env("WARRANT_WAKER_TREES") or Path.home() / "Projects" / ".worktrees" / "codex-review")
        self.python = str(python or env("WARRANT_WAKER_PYTHON") or self.home / "venv" / "bin" / "python")
        self.codex = str(codex or env("WARRANT_WAKER_CODEX") or shutil.which("codex") or "/opt/homebrew/bin/codex")
        self.replayers = Path(replayers or env("WARRANT_WAKER_REPLAYERS") or Path.home() / ".warrant-review-replayer")
        self.replay_python = str(replay_python or env("WARRANT_WAKER_REPLAY_PYTHON") or self.python)
        self.plugin, self.run, self.clock, self.jail = Path(plugin), run, clock, jail
        self.forge = forge or Forge()
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
        for proj in PROJECTORS:
            if (wt / proj).is_file():
                v = self.jail([self.replay_python, str(wt / proj), "project"], prof, self.env(work, wt), None)
                if v.returncode:
                    raise RuntimeError(f"{proj} project exited {v.returncode}: "
                                       f"{v.stderr.decode(errors='replace').strip()[-300:]}")
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
        """(what, detail) of a memo: done, gave up, waiting (for its backoff) or retry. An attempt that exited 0 and
        left nothing to publish (`unpublished`: an acceptance wake) failed."""
        tries = doc.get("attempts", [])
        last = tries[-1] if tries else None
        if last is None:
            return "retry", "first attempt"
        if last.get("exit") == 0 and not last.get("unpublished"):
            return "done", f"done: woken {last.get('started_at')}, codex exited 0"
        how = f"exited 0, unpublished: {last['unpublished']}" if last.get("unpublished") else f"exited {last.get('exit')}"
        if len(tries) >= MAX_TRIES:
            return "gave up", f"gave up: {len(tries)} attempts failed (last {how}); delete the memo to retry"
        due_at = (last.get("finished") or last.get("started", 0)) + BACKOFF * 2 ** (len(tries) - 1)
        if self.clock() < due_at:
            return "waiting", f"waiting: attempt {len(tries)} {how}; retry after {iso(due_at)}"
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

    def attempt(self, p, doc, key, worktree, command, state=None):
        """One attempt of the wake whose memo `p` holds `doc`, when its state (`state`, else self.state) allows: the
        memo is written before Codex runs (a crash counts as an attempt), `command(path)` runs in `worktree()`, which
        is removed after unless Codex left changes in it. (whether Codex was started, what happened)."""
        what, detail = (state or self.state)(doc)
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

    def accept_worktree(self, c, base, n=1):
        """A detached worktree of the mirror at the base, its own for this closure item, base and attempt `n` (a
        retry starts clean; the earlier attempt's worktree keeps what that attempt left)."""
        self.accept_key(c)
        path = self.trees / (f"accept-{c['closure'][:12]}-{c['item']}-{commit(base)[:12]}" + (f"-{n}" if n > 1 else ""))
        if not path.exists():
            self.trees.mkdir(parents=True, exist_ok=True)
            git("-C", str(self.mirror), "worktree", "add", "--detach", "--quiet", str(path), base)
        return path

    def accept_state(self, doc):
        """(what, detail) of an acceptance memo. A wake is done only once its verdict reached GitHub (`published`).
        After a run of Codex that exited 0 (an older waker's memo of one included: it counted that as done) the
        verdict is to be published ("publish"), each failed publication retried after BACKOFF seconds, doubled each
        time, at most MAX_TRIES ("waiting", "gave up"). A run whose worktree held no verdict to publish is a failed
        attempt (`unpublished`), and Codex is woken again as after any failed attempt (state)."""
        if doc.get("published"):
            return "done", f"done: published, {doc['published'].get('line')}"
        tries = doc.get("attempts", [])
        last = tries[-1] if tries else {}
        if last.get("exit") != 0 or last.get("unpublished"):
            return self.state(doc)
        pubs = doc.get("publications", [])
        if len(pubs) >= MAX_TRIES:
            return "gave up", (f"unpublished: gave up after {len(pubs)} failed publications (the last: "
                               f"{pubs[-1].get('line')}); delete the memo to retry")
        due_at = pubs[-1].get("finished", 0) + BACKOFF * 2 ** (len(pubs) - 1) if pubs else 0
        if self.clock() < due_at:
            return "waiting", f"unpublished: publication {len(pubs)} failed ({pubs[-1].get('line')}); retry after {iso(due_at)}"
        return "publish", f"unpublished: publication {len(pubs) + 1} of {MAX_TRIES}"

    def accept(self, c, base, why_not=None):
        """(busy, line) for obligation closure `c` (an entry of `roadmap.py due`) at the base: Codex is woken, or
        the verdict his last run prepared is published, when the memo's state allows and nothing holds it
        (`why_not`: a dry run, HOME/HOLD, an open verdict pull request, a wake already started in this run); one
        memo per closure item, whatever the base. Busy: Codex was woken or a publication tried in this run."""
        p, doc = self.accept_memo(c)
        what, detail = self.accept_state(doc) if doc else ("retry", "not woken yet")
        if why_not:
            return False, detail + (f"; {why_not}" if what in ("retry", "publish") else "")
        if what == "publish":
            return True, self.publish(c, base, p, doc)
        key = f"accept-{self.accept_key(c)}"
        doc = doc or {"closure": c["closure"], "item": c["item"], "duty": c["duty"], "base": base, "attempts": []}
        started, line = self.attempt(p, doc, key, lambda: self.accept_worktree(c, base, len(doc["attempts"])),
                                     lambda path: self.codex_exec(path, key, accept_prompt(c, base, self.plugin, path)),
                                     self.accept_state)
        if started and doc["attempts"][-1].get("exit") == 0:
            line += "; " + self.publish(c, base, p, doc)
        return started, line

    # -- publication: the waker, not Codex, puts the verdict on GitHub

    def publish(self, c, base, p, doc):
        """Publish the verdict Codex's last run left in its worktree: unless it reached GitHub already (published),
        the records and blobs prepared() admits, copied onto the base by _publish. The line. A worktree with no
        verdict to publish marks the attempt `unpublished` (Codex is woken again); a publication that failed (Git,
        GitHub, the check's own run) is retried; one that succeeded makes the memo done and removes the worktree."""
        last, code, t = doc["attempts"][-1], self.tree(base), self.clock()
        branch = f"{VERDICT_BRANCH}{c['closure'][:12]}-{c['item']}"
        try:
            where = self.published(c, code, branch)
            if where is None:
                try:
                    records, blobs = self.prepared(Path(last.get("worktree") or self.trees / "-"), c, code)
                except Unpublished as e:
                    last["unpublished"] = str(e)[:300]
                    p.write_text(json.dumps(doc, indent=1))
                    return self.accept_state(doc)[1]
                where = self._publish(c, base, code, branch, records, blobs)
        except (subprocess.SubprocessError, RuntimeError, ValueError, OSError) as e:
            doc.setdefault("publications", []).append({"at": iso(t), "finished": self.clock(), "ok": False,
                                                       "line": f"publication failed: {str(e)[:300]}"})
            p.write_text(json.dumps(doc, indent=1))
            return self.accept_state(doc)[1]
        doc.setdefault("publications", []).append({"at": iso(t), "finished": self.clock(), "ok": True, "line": where["line"]})
        doc["published"] = where
        p.write_text(json.dumps(doc, indent=1))
        kept = Path(last.get("worktree") or self.trees / "-")
        if kept.parent == self.trees and kept.name.startswith("accept-"):
            self.discard(kept, kept)
        return f"published: {where['line']}"

    def published(self, c, code, branch):
        """Where the verdict on closure item `c` reached GitHub, or None: the base tree `code` holds a verdict of
        ACCEPTOR on it, or a pull request from `branch` of REPO exists, in any state (Codex published it himself, an
        earlier run did, or a courier: never a second one)."""
        held = held_verdict(code, c)
        if held:
            return {"line": f"the base holds {ACCEPTOR}'s verdict {held[:12]}", "record": held}
        pulls = self.forge.pulls(branch)
        if pulls:
            return {"line": f"pull request #{pulls[0][0]} ({str(pulls[0][1]).lower()}) from {branch}", "pr": pulls[0][0],
                    "branch": branch}
        return None

    def prepared(self, wt, c, code):
        """({record id: bytes}, {blob id: bytes}) of the verdict Codex left in his worktree `wt`: everything new in
        its store, read once. Unpublished unless it is only new regular files named by their content (no change to
        the base's store), at least one record, and verify() finds nothing wrong with them."""
        if not (wt.is_dir() and (wt / ".git").exists()):
            raise Unpublished(f"Codex left no worktree, so no verdict ({wt.name})")
        raw = git("-C", str(wt), *STATUS, "--", STORE).decode()
        records, blobs, size = {}, {}, 0
        for e in (x for x in raw.split("\0") if x):
            xy, path = e[:2], e[3:]
            kind, ident = stored(path)
            f = wt / path
            if xy != "??" or not HEX.match(ident) or f.is_symlink() or not f.is_file():
                raise Unpublished(f"the store holds {xy} {path[:80]}: only new records and blobs named by their content "
                                  "are published")
            size += f.stat().st_size
            if size > MAX_PREPARED:
                raise Unpublished(f"the prepared records and blobs exceed {MAX_PREPARED} bytes")
            (records if kind == "records" else blobs)[ident] = f.read_bytes()
        if not records:
            raise Unpublished("Codex left no verdict record in his worktree's store")
        why = self.verify(code, c, records, blobs)
        if why:
            raise Unpublished(why)
        return records, blobs

    def verify(self, code, c, records, blobs):
        """verify_verdicts on these bytes, in a process of its own with the base tree `code` first on PYTHONPATH:
        the base's package checks the signatures under the base's pins."""
        req = {"code": str(code), "actor": ACCEPTOR, "closure": c["closure"], "item": c["item"],
               "records": {k: base64.b64encode(v).decode() for k, v in records.items()},
               "blobs": {k: base64.b64encode(v).decode() for k, v in blobs.items()}}
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "PYTHONPATH": str(code),
               "PYTHONDONTWRITEBYTECODE": "1", "LANG": "en_US.UTF-8"}
        r = subprocess.run([self.python, str(Path(__file__).resolve()), "--verify-verdicts"], input=json.dumps(req).encode(),
                           env=env, capture_output=True, check=False, timeout=600)
        if r.returncode:
            raise RuntimeError(f"the verdict check exited {r.returncode}: {r.stderr.decode(errors='replace').strip()[-300:]}")
        return json.loads(r.stdout)["refused"]

    def _publish(self, c, base, code, branch, records, blobs):
        """The verdict's records and blobs, these bytes, in a new worktree of the base; the base's own projectors
        (BASE_PROJECTORS, those its tree has) regenerate whatever generated file the base tracks; one commit of the
        store entries and the tracked files they changed, by the waker; pushed to `branch` only while it does not
        exist (or exists already holding these records: an earlier run's push), and the pull request opened."""
        key = f"publish-{self.accept_key(c)}"
        wt, work = self.trees / f"publish-{c['closure'][:12]}-{c['item']}-{commit(base)[:12]}", self.home / "replay-work" / key
        self.discard(wt, work)
        work.mkdir(parents=True)
        self.trees.mkdir(parents=True, exist_ok=True)
        git("-C", str(self.mirror), "worktree", "add", "--detach", "--quiet", str(wt), base)
        try:
            ours = {f"{STORE}records/{r}.json": d for r, d in records.items()}
            ours.update((f"{STORE}blobs/{b}", d) for b, d in blobs.items())
            for path, data in ours.items():
                (wt / path).parent.mkdir(parents=True, exist_ok=True)
                (wt / path).write_bytes(data)
            for proj in BASE_PROJECTORS:
                if (code / proj).is_file():
                    r = subprocess.run([self.python, str(code / proj), "--root", str(wt), "project"], env=self.env(work, code),
                                       capture_output=True, check=False, timeout=REPLAY_TIMEOUT)
                    if r.returncode:
                        raise RuntimeError(f"the base's {proj} project exited {r.returncode}: "
                                           f"{r.stderr.decode(errors='replace').strip()[-300:]}")
            paths = projected(wt, ours)
            git("-C", str(wt), "add", "--", *paths)
            kinds = sorted({json.loads(d)["record"]["type"] for d in records.values()})
            title = f"Codex: {' and '.join(kinds)} of obligation closure {c['closure'][:12]}"
            git("-C", str(wt), *COMMITTER, "commit", "--quiet", "--no-verify", "-m",
                verdict_message(c, base, title, records, blobs))
            new = commit(git("-C", str(wt), "rev-parse", "HEAD").decode().strip())
            tip = git("-C", str(wt), "ls-remote", "origin", f"refs/heads/{branch}").decode().split()
            if tip:
                git("-C", str(wt), "fetch", "--quiet", "origin", f"refs/heads/{branch}")
                theirs = commit(git("-C", str(wt), "rev-parse", "FETCH_HEAD").decode().strip())
                if any(subprocess.run(["git", "-C", str(wt), "cat-file", "-e", f"{theirs}:{path}"], capture_output=True,
                                      check=False).returncode for path in ours):
                    raise RuntimeError(f"{branch} exists at {theirs[:12]} without this verdict: nothing pushed")
                new = theirs
            else:
                git("-C", str(wt), "push", "--quiet", f"--force-with-lease=refs/heads/{branch}:", "origin",
                    f"{new}:refs/heads/{branch}")
            body = verdict_body(c, base, branch, records, blobs, self.home / "results" / f"accept-{self.accept_key(c)}.md")
            n = self.forge.open(branch, title, body)
            return {"line": f"pull request #{n} from {branch} at {new[:12]}", "pr": n, "branch": branch, "commit": new,
                    "records": sorted(records), "blobs": sorted(blobs)}
        finally:
            self.discard(wt, work)

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
            f"{c['item']}, or challenge T, through MCP, into this worktree's store. Leave there only that record and "
            f"the blobs it cites; do not commit, push or open a pull request: after you exit, the waker checks them "
            f"under the base's pin for {ACCEPTOR} and publishes them itself on the branch "
            f"{VERDICT_BRANCH}{c['closure'][:12]}-{c['item']}, a pull request into {BRANCH} whose description is your "
            "final message. These facts come from "
            f"`tools/roadmap.py due --actor {ACCEPTOR}` at M, run by the review waker; check them yourself before you "
            "rely on them.")


def projected(wt, ours):
    """The paths to commit in the publication worktree `wt` after the base's projectors ran: the store entries
    `ours` (each new there) and the tracked files those projectors changed. A new file the base does not track
    stays out; anything else (a deletion, a store entry not ours) is a RuntimeError."""
    raw = git("-C", str(wt), *STATUS).decode()
    out = []
    for e in (x for x in raw.split("\0") if x):
        xy, path = e[:2], e[3:]
        if (xy == "??" and path in ours) or (xy == " M" and not path.startswith(STORE)):
            out.append(path)
        elif not (xy == "??" and not path.startswith(STORE)):
            raise RuntimeError(f"the publication left {xy} {path[:80]}: nothing pushed")
    if set(ours) - set(out):
        raise RuntimeError(f"{len(set(ours) - set(out))} prepared store entries are not new on the base: nothing pushed")
    return sorted(out)


def verdict_message(c, base, title, records, blobs):
    return (f"{title} (duty {c['duty'][:12]}), published by the review waker\n\n"
            + "".join(f"record {r}\n" for r in sorted(records)) + "".join(f"blob {b}\n" for b in sorted(blobs))
            + f"\nCodex filed these through MCP in his acceptance wake of closure {c['closure']} item {c['item']} at "
            f"base {base[:12]} and left them in his worktree. The review waker checked them under the base's pin for "
            f"{ACCEPTOR}, copied only these bytes onto the base, regenerated what the base generates with the base's "
            "own tools, and signed nothing.\n")


def verdict_body(c, base, branch, records, blobs, report):
    """The pull request's description: the facts the waker checked, then Codex's own report (his last message)."""
    try:
        text = report.read_text(errors="replace").strip()[:50000] if report.is_file() else ""
    except OSError:
        text = ""
    return (f"Codex's verdict on a roadmap obligation's closure. Codex prepared it in his acceptance wake and signed it "
            f"through MCP; the review waker published it on `{branch}` and signed nothing.\n\n"
            f"- Duty D: `{c['duty']}` (goal {c.get('goal')})\n- Closure T, item {c['item']}: `{c['closure']}`\n"
            f"- Base M: `{base}`\n"
            + "".join(f"- Record `{r}`: signed by {ACCEPTOR} with the key the base's roles.json pins\n" for r in sorted(records))
            + "".join(f"- Blob `{b}`: cited by the record\n" for b in sorted(blobs))
            + "\n## Codex's report (his last message in the wake, unedited)\n\n" + (text or "(none)") + "\n")


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
    ap.add_argument("--verify-verdicts", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.verify_verdicts:            # Waker.verify: the base's package on PYTHONPATH, the request on stdin
        print(json.dumps({"refused": verify_verdicts(json.load(sys.stdin))}))
        return 0
    dry = args.dry_run
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
