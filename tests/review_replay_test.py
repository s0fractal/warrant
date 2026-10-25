#!/usr/bin/env python3
"""The review replay checker (tools/claimslib/review_replay.py) and its observations: diffs confined to
tests/, outcomes that reproduce nothing, verify, adopted replayers (V26-V28). Then the review waker's
replay (integrations/codex-plugin/waker/waker.py, Waker.replay): the checker runs before Codex is woken,
on every due head, with no person or model choosing to run it, and the waker pushes only what the
checker's own code filed (W1-W11). Then its acceptance wakes: the base's `tools/roadmap.py due` names the
obligation closures due for Codex's verdict, each woken once, one at a time, none while Codex's previous verdict
pull request is open (W12-W14).

The waker is driven against a fixture: a bare `origin` with the pull request's branch, the waker's
mirror cloned from it, and a base tree whose tools are the ones under test. A jail runs the commands
the waker would run under sandbox-exec (unconfined here, so the cases run on any host; W4 runs the
real sandbox where there is one).

    python3 tests/review_replay_test.py
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from review_world import (C, CRASHING_TEST, FIXED, GIT, R, RR, RV, Fixture, _write, finding_test, head_of,
                          new_file_patch, started)
from world import check, finish

import warrant
from warrant.store import Store



# ---------------------------------------------------------------- replay

def replay_cases():
    f = started()
    p = _write(f.base / "outside.diff", "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-x\n+y\n")
    outside = f.code("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "outside",
                     "--test", "finding_test", "--case", "F1", "--patch", str(p), actor="codex")
    shapes = [RR.patch_problem(x) is not None for x in (
        "--- a/tests/x/../../calc.py\n+++ b/tests/x/../../calc.py\n",
        "diff --git a/tests/x_test.py b/tests/x_test.py\nnew file mode 120000\n",
        "diff --git a/tests/x_test.py b/tests/x_test.py\nGIT binary patch\n",
        "rename from calc.py\nrename to tests/calc.py\n",
        new_file_patch("tests/ok_test.py", "x = 1\n"))]
    crash = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "crashes",
                 "--test", "crash_test", "--case", "F1",
                 "--patch", str(_write(f.base / "c.diff", finding_test("crash_test", CRASHING_TEST)["patch"])), actor="codex")
    stale = {"file": "calc_test", "case": "F1",
             "patch": "--- a/tests/calc_test.py\n+++ b/tests/calc_test.py\n@@ -1 +1 @@\n-# not this line\n+x\n"}
    nope = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "does not apply",
                "--test", stale["file"], "--case", "F1", "--patch", str(_write(f.base / "s.diff", stale["patch"])),
                actor="codex")
    f.ok("replay")
    m = f.model()
    check("V26", outside == ("REVIEW_FINDING_TEST", True) and shapes == [True, True, True, True, False]
          and m.findings[crash].at(f.h1) == "NO_RESULT" and m.findings[nope].at(f.h1) == "DOES_NOT_APPLY"
          and RV.finding_class(m.findings[crash]) == RV.finding_class(m.findings[nope]) == "UNEVALUABLE",
          "a test diff is confined to tests/; a test that crashes or a diff that does not apply reproduces nothing",
          (outside, shapes))
    base = f.save()

    # The replayer's observations new since the base are re-executed by verify.
    cid = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "add subtracts",
               "--test", "finding_test", "--case", "F1",
               "--patch", str(_write(f.base / "f.diff", finding_test()["patch"])), actor="codex")
    m = f.model()
    probe = {"probe": RR.PROBE, "finding": cid, "commit": f.h1, "tree": head_of(m, 1, 1).tree, "test": "finding_test:F1"}
    now = f.at()
    lie = f.put(f.replayer, "observation", R.observation(RV.replay_target(m.cfg, 1, cid, f.h1), C.digest(C.canon(probe)),
                                                         [now, now], "PASS"), [probe])
    f.save()
    rc, out, _ = f.run("replay", "--verify", "--base", base)
    lied = [c for c, _ in RV.verify(f.rv(), base)]
    m = f.model()
    check("V27", lied == ["REVIEW_REPLAY_DIFFERS"] and rc == 1 and m.findings[cid].at(f.h1) == "PASS"
          and m.findings[cid].observed[f.h1][0] == lie and RV.verify(f.rv(), f.git("rev-parse", "HEAD")) == [],
          "replay --verify re-executes each replay observation new since the base and refuses one it does not "
          "reproduce", (lied, out))
    f.close()

    f = started()
    cid = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "add subtracts",
               "--test", "finding_test", "--case", "F1",
               "--patch", str(_write(f.base / "f.diff", finding_test()["patch"])), actor="codex")
    m = f.model()
    probe = {"probe": RR.PROBE, "finding": cid, "commit": f.h1, "tree": head_of(m, 1, 1).tree, "test": "finding_test:F1"}
    now = f.at()
    f.put("stranger", "observation", R.observation(RV.replay_target(m.cfg, 1, cid, f.h1), C.digest(C.canon(probe)),
                                                   [now, now], "PASS"), [probe])
    m = f.model()
    unpinned = [c for c, _ in m.problems]
    f.config(replayers=["checker sha256:" + "0" * 64])
    f.ok("project")
    stale = f.problems()
    check("V28", unpinned == ["REVIEW_REPLAYER_UNPINNED"] and m.findings[cid].at(f.h1) is None
          and "REVIEW_REPLAYER_STALE" in stale,
          "only an adopted replayer's observation counts, and the adopted one is this checkout's review_replay.py",
          (unpinned, stale))
    f.close()


ROOT = Path(__file__).resolve().parents[1]
_impl = Path(os.environ["WARRANT_IMPL"]) if os.environ.get("WARRANT_IMPL") else None
_rel = Path("integrations", "codex-plugin", "waker", "waker.py")
WAKER_PY = _impl / _rel if _impl is not None and (_impl / _rel).is_file() else ROOT / _rel
_spec = importlib.util.spec_from_file_location("waker", WAKER_PY)
WAKER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(WAKER)
TOOLS = Path(RV.__file__).resolve().parents[1]          # the tools review_world loaded (a mutant's copy, or this checkout's)
PKG = Path(warrant.__file__).resolve().parent
EVIL = ('import os, sys\nsys.path.insert(0, os.environ["WARRANT_IMPL"])\nimport evil\n')


def unconfined(cmd, prof, env, stdin=None):
    return subprocess.run(cmd, input=stdin, env=env, capture_output=True, check=False, timeout=600)


class Jail:
    """Runs what the waker would sandbox, unconfined, and keeps (cmd, profile, env, stdin) of each call;
    `after(cmd, result)` may change the world after a command (what code inside the jail could do)."""

    def __init__(self, after=None):
        self.calls, self.after = [], after

    def __call__(self, cmd, prof, env, stdin=None):
        self.calls.append((cmd, prof, env, stdin))
        r = unconfined(cmd, prof, env, stdin)
        if self.after is not None:
            self.after(cmd, r)
        return r


class FakeCodex:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)


def git(*args):
    return subprocess.run([*GIT, *args], capture_output=True, check=True).stdout.decode().strip()


def projector(f):
    """A head's own tools/review.py `project` (the fixture's head has no tools of its own): the view."""
    return (f"import sys\nsys.path[:0] = [{str(TOOLS)!r}, {str(PKG.parent)!r}]\nfrom pathlib import Path\n"
            "from claimslib import reviews\n"
            "sys.exit(reviews.main(['--root', str(Path(__file__).resolve().parents[1]), *sys.argv[1:]]))\n")


def pr_world(after=None, head_files=None):
    """#1 with Codex's mechanical finding at its buggy head 1 (f.h1) answered by head 2 (f.h2, fixed),
    the records committed on top (f.head, with a projector and `head_files`); the branch pr1 of a bare
    origin at f.head; the waker's mirror cloned from origin; its base tree f.code (this checkout's tools
    and package, the fixture's reviews.json); the replayer's seed in f.replayers, mode 0600."""
    f = started()
    f.cid = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "add subtracts",
                 "--test", "finding_test", "--case", "F1",
                 "--patch", str(_write(f.base / "f.diff", finding_test()["patch"])), actor="codex")
    f.save()
    f.h2 = f.commit("the fix", {"calc.py": FIXED})
    f.ok("answer", "--pr", "1", "--commit", f.h2, "--finding", f.cid)
    for path, text in {"tools/review.py": projector(f), **(head_files or {})}.items():
        _write_at(f.dir / path, text)
    f.head = f.save()
    f.origin = f.base / "origin.git"
    git("clone", "--bare", "-q", str(f.dir), str(f.origin))
    git("-C", str(f.origin), "update-ref", "refs/heads/pr1", f.head)
    git("-C", str(f.origin), "update-ref", "refs/heads/master", f.start)
    home = f.base / "home"
    home.mkdir()
    git("clone", "--bare", "-q", str(f.origin), str(home / "warrant.git"))
    f.code = f.base / "code"
    (f.code / ".warrant").mkdir(parents=True)
    (f.code / "tools").symlink_to(TOOLS)
    (f.code / "warrant").symlink_to(PKG)
    (f.code / ".warrant" / "reviews.json").write_bytes((f.dir / ".warrant" / "reviews.json").read_bytes())
    f.replayers = f.base / "replayers"
    f.replayers.mkdir(mode=0o700)
    f.seed = f.replayers / f"{f.replayer[len(RR.PREFIX):]}.seed"
    f.seed.write_text(f.keys[f.replayer].seed_hex() + "\n")
    f.seed.chmod(0o600)
    f.codex, f.jail = FakeCodex(), Jail(after)
    f.w = WAKER.Waker(home=home, trees=f.base / "trees", python=sys.executable, codex="/bin/codex", run=f.codex,
                      replayers=f.replayers, replay_python=sys.executable, jail=f.jail)
    f.w.tree = lambda base: f.code          # the base tree: the tools under test, not the fixture's (it has none)
    return f


def _write_at(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def due(f, head=None):
    return {"pr": 1, "head": head or f.head, "branch": "pr1", "base": f.start,
            "facts": {"duty": f.duty, "closure": None, "head_n": 2, "x": f.h2}}


def tip(f):
    return git("-C", str(f.origin), "rev-parse", "refs/heads/pr1")


def added(f, old, new):
    return git("-C", str(f.origin), "diff-tree", "-r", "--no-commit-id", "--name-status", old, new).splitlines()


def at_commit(f, rev):
    """The fixture checked out at `rev` of origin."""
    f.git("fetch", "-q", str(f.origin), "pr1")
    f.git("checkout", "-q", "--detach", rev)
    return f.model()


def root_of(cmd):
    return Path(cmd[cmd.index("--root") + 1])


def plant(wt, actor, key, f, result, at):
    """A replay observation filed straight into the worktree's store (what code inside the jail could do)."""
    m = RV.Reviews(wt).model()
    h1 = next(h for h in m.reviews[1].heads if h.commit == f.h1)
    probe = {"probe": RR.PROBE, "finding": f.cid, "commit": f.h1, "tree": h1.tree, "test": "finding_test:F1"}
    store = Store(wt / ".warrant" / "store")
    store.put_json(probe)
    body = R.observation(RV.replay_target(m.cfg, 1, f.cid, f.h1), C.digest(C.canon(probe)), [at, at], result)
    return store.put_record(R.record("observation", actor, at, body), key)


# ---------------------------------------------------------------- the replay, the tick, the key

def waker_cases():
    f = pr_world()
    pushed, line = f.w.replay(due(f), f.start)
    new = tip(f)
    names = added(f, f.head, new)
    parent = git("-C", str(f.origin), "rev-parse", f"{new}^")
    m = at_commit(f, new)
    fnd = m.findings[f.cid]
    actors = {m.recs[o]["actor"] for o, _ in fnd.observed.values()}
    stale = [c for c in f.problems() if c == "REVIEWS_STALE"]
    check("W1", pushed and parent == f.head and fnd.at(f.h1) == "FAIL" and fnd.at(f.h2) == "PASS"
          and actors == {f.replayer} and len(names) == 5 and "M\tREVIEWS.md" in names and stale == []
          and all(n.startswith("A\t.warrant/store/") for n in names if n != "M\tREVIEWS.md"),
          "the waker runs the base's checker on a due head: Codex's finding replayed FAIL at head 1 and PASS at "
          "head 2, by the checker, pushed as one commit of those records and the head's own view on the branch",
          (line, names, fnd.observed, stale))
    f.close()

    g = pr_world()
    g.w.fetch = lambda: g.start
    g.w.due = lambda base: {"due": [due(g, tip(g))], "not_due": []}
    first = WAKER.tick(g.w, False)
    woke1, moved = len(g.codex.calls), tip(g)
    second = WAKER.tick(g.w, False)
    woke2 = len(g.codex.calls)
    again = g.w.replay(due(g, moved), g.start)
    check("W2", woke1 == 0 and moved != g.head and "pushed" in first[1] and woke2 == 1
          and "nothing to replay" in second[1] and "woken" in second[1] and tip(g) == moved
          and again == (False, "replay: nothing to replay") and len(g.jail.calls) == 3,
          "a run that pushed observations wakes nobody; the next run, at the new head, finds nothing left to replay "
          "and wakes Codex; one replay per head", (first, second, again))

    seed = g.keys[g.replayer].seed_hex()
    calls = g.jail.calls
    signed = [c for c in calls if c[3] is not None]
    prof = signed[0][1]
    allow = next(x for x in prof.splitlines() if x.startswith("(allow file-write*"))
    writable = re.findall(r'\(subpath "([^"]+)"\)', allow)
    replay_cmd = [sys.executable, str(g.code / "tools" / "review.py"), "--root"]
    check("W3", len(signed) == 2 and all(c[3] == (seed + "\n").encode() and c[0][:3] == replay_cmd
                                         and c[0][-3:] == ["replay", "--key", "-"] for c in signed)
          and all(seed not in " ".join(c[0]) and seed not in json.dumps(c[2]) and str(g.replayers) not in json.dumps(c[2])
                  for c in calls)
          and "(deny network*)" in prof.splitlines() and "(deny file-write*)" in prof.splitlines()
          and f'(deny file-read* (subpath "{g.replayers.resolve()}"))' in prof.splitlines()
          and len(writable) == 3 and str(g.replayers.resolve()) not in writable
          and all(Path(p).is_relative_to(g.base.resolve()) for p in writable),
          "the seed reaches only the base checker's `replay --key -`, on standard input, never an argument or the "
          "environment; the sandbox denies the network, reading the seeds, and writing outside the worktree, its "
          "git directory and the scratch directory", (writable, [c[0] for c in calls]))
    g.close()


def sandbox_cases():
    if not Path(WAKER.SANDBOX).is_file():
        print(f"skip  W4 (no {WAKER.SANDBOX} on this host)")
        return
    if subprocess.run([WAKER.SANDBOX, "-p", "(version 1)\n(allow default)\n", "/usr/bin/true"], capture_output=True).returncode:
        print("skip  W4 (this process may not apply a sandbox: it runs inside one already)")
        return
    f = Fixture()
    try:
        keys, inside, outside = f.base / "keys", f.base / "inside", f.base / "outside"
        for d in (keys, inside, outside):
            d.mkdir()
        (keys / "k.seed").write_text("0" * 64 + "\n")
        probe = ("import socket, sys\nout = []\n"
                 f"for p in ({str(keys / 'k.seed')!r},):\n"
                 "    try:\n        open(p).read(); out.append('read')\n    except OSError:\n        out.append('no read')\n"
                 f"for p in ({str(inside / 'x')!r}, {str(outside / 'x')!r}):\n"
                 "    try:\n        open(p, 'w').write('1'); out.append('write')\n    except OSError:\n        out.append('no write')\n"
                 "try:\n    socket.create_connection(('1.1.1.1', 443), timeout=3); out.append('net')\n"
                 "except OSError:\n    out.append('no net')\nprint(' '.join(out))\n")
        r = WAKER.sandboxed([sys.executable, "-c", probe], WAKER.profile([inside], [keys]),
                            {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(f.base)})
        got = r.stdout.decode().strip()
        check("W4", got == "no read write no write no net",
              "under sandbox-exec with the replay's profile: no read of the seeds, writes only where allowed, no network",
              (got, r.stderr.decode()[-300:]))
    finally:
        f.close()


# ---------------------------------------------------------------- what the waker refuses to push

def refusal_cases():
    def forged(cmd, r):
        if "replay" in cmd:
            plant(root_of(cmd), f.replayer, f.keys[f.replayer], f, "PASS", f.at() + 5)

    f = pr_world(after=lambda cmd, r: forged(cmd, r))
    pushed, line = f.w.replay(due(f), f.start)
    check("W5", not pushed and "nothing pushed" in line and tip(f) == f.head,
          "an observation the checker's run did not print (here PASS at head 1, which a real replay finds FAIL), "
          "even signed with the checker's key, is not pushed", line)
    f.close()

    def foreign(cmd, r):
        if "replay" in cmd:
            oid = plant(root_of(cmd), "claude", f.keys["claude"], f, "FAIL", f.at() + 5)
            r.stdout += f"{oid} finding {f.cid[:12]} at {f.h1[:12]}: FAIL\n".encode()

    f = pr_world(after=lambda cmd, r: foreign(cmd, r))
    pushed, line = f.w.replay(due(f), f.start)
    check("W6", not pushed and "is not an observation by" in line and tip(f) == f.head,
          "a record printed as the checker's but signed by another identity (claude) is not pushed", line)
    f.close()

    sentinel = None

    def evil(f):
        nonlocal sentinel
        sentinel = f.base / "SENTINEL"
        test = {"file": "evil_test", "case": "F1",
                "patch": new_file_patch("evil.py", f"open({str(sentinel)!r}, 'w').write('ran')\n")
                + new_file_patch("tests/evil_test.py", EVIL)}
        return test

    f = started()
    f.cid = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "add subtracts",
                 "--test", "finding_test", "--case", "F1",
                 "--patch", str(_write(f.base / "f.diff", finding_test()["patch"])), actor="codex")
    test = evil(f)
    raised = None
    try:
        RR.run(f.dir, f.h1, test)
    except ValueError as e:
        raised = str(e)
    check("W8", raised is not None and "outside tests/" in raised and not sentinel.exists(),
          "the checker refuses a finding test whose diff touches a file outside tests/ before anything is extracted, "
          "applied or run", (raised, sentinel.exists()))
    f.close()

    g = pr_world()
    test = evil(g)
    m = g.model()
    h2 = m.reviews[1].latest()
    doc = {"schema": RV.FINDING, "duty": g.duty, "pr": 1, "head": h2.tid, "commit": h2.commit, "tree": h2.tree,
           "severity": "P2", "what": "runs evil.py", "where": [], "test": test}
    bad = g.put("codex", "challenge", R.challenge(h2.tid, "P2 runs evil.py", [C.digest(C.canon(doc))], item_index=0),
                [doc])
    g.head = g.save()
    git("-C", str(g.origin), "fetch", "-q", str(g.dir), f"+{g.head}:refs/heads/pr1")
    git("-C", str(g.w.mirror), "fetch", "-q", str(g.origin), "+refs/heads/pr1:refs/heads/pr1")
    pushed, line = g.w.replay(due(g), g.start)
    m = at_commit(g, tip(g))
    check("W7", pushed and not sentinel.exists() and bad not in m.findings and m.findings[g.cid].at(g.h2) == "PASS"
          and not any(r["type"] == "observation" and bad in r["body"]["target"] for r in m.recs.values()),
          "a finding (filed by hand) whose test diff touches a file outside tests/ is no finding: the waker's replay "
          "runs the other finding and never that test", (line, sentinel.exists()))
    g.close()


def guard_cases():
    f = pr_world(head_files={RR.SELF: "# another checker\n"})
    pushed, line = f.w.replay(due(f), f.start)
    check("W9", not pushed and "changes" in line and tip(f) == f.head and f.jail.calls == [],
          "a pull request whose head changes review_replay.py is not replayed by the base's checker", line)
    f.close()

    f = pr_world()
    git("-C", str(f.origin), "update-ref", "refs/heads/pr1", f.h2)
    pushed, line = f.w.replay(due(f), f.start)
    check("W10", not pushed and "not pushed" in line and tip(f) == f.h2,
          "the observations are pushed only while the branch is still at the head replayed (here it went back to an "
          "ancestor, where a push would fast-forward)", line)
    f.close()

    f = pr_world()
    f.seed.chmod(0o644)
    loose = f.w.replay(due(f), f.start)
    f.seed.chmod(0o600)
    link = f.replayers / "elsewhere.seed"
    f.seed.rename(link)
    f.seed.symlink_to(link)
    linked = f.w.replay(due(f), f.start)
    memo = list((f.w.home / "replays").iterdir())
    check("W11", not loose[0] and "mode 0600" in loose[1] and not linked[0] and "mode 0600" in linked[1]
          and f.jail.calls == [] and memo == [],
          "a seed readable by others, or a link to one, is not used; nothing is replayed and no memo is kept",
          (loose, linked, memo))
    f.close()


# ---------------------------------------------------------------- acceptance wakes

def roadmap_base(f):
    """The waker's base tree for acceptance wakes: the tools and package under test beside the fixture's .warrant."""
    code = f.base / "accept-code"
    code.mkdir()
    (code / "tools").symlink_to(TOOLS)
    (code / "warrant").symlink_to(PKG)
    (code / ".warrant").symlink_to(f.dir / ".warrant")
    return code


def obligation(f, goal, text, requires=()):
    """A duty on .warrant/roadmap.json's terms answering `goal` (a vision transition's first question)."""
    return f.put("claude", "duty", R.duty("claude", text, ["s0fractal"], {"attest": {}}, accept_by=["codex"],
                                          requires=list(requires), answers=goal + ":0"))


def done(f, duty, refs):
    """A closure of `duty` citing an evidence blob, as `roadmap.py done` files it; what it says it established is
    CONCLUSION, which no wake may pass on."""
    ev = {"schema": "warrant-roadmap/evidence@1", "duty": duty, "refs": refs}
    h = C.digest(C.canon(ev))
    return f.put("claude", "transition", R.transition("ATTESTED", [h], closes=[R.item(duty, "discharge", [h])],
                                                      established=["CONCLUSION"]), [ev]), h


def entry(n):
    return {"closure": f"{n}" * 64, "duty": "d" * 64, "item": 0, "goal": "G1", "statement": f"duty {n}",
            "evidence": ["e" * 64], "refs": [], "subject": None, "requires": []}


def acceptance_cases():
    f = pr_world()
    goal = f.put("claude", "transition", R.transition("ATTESTED", [], opened=[{"text": "The ledger exists.",
                                                                               "scope": "roadmap:G1"}]))
    a = obligation(f, goal, "Counter blobs are accepted from any key.")
    ta, ha = done(f, a, ["s0fractal/warrant#9", "merge " + "c" * 40])
    b = obligation(f, goal, "A witness ledger is derived from the records.", requires=[a])
    tb, _ = done(f, b, ["s0fractal/warrant#10"])
    code = roadmap_base(f)
    f.w.tree = lambda base: code
    f.w.due = lambda base: {"due": [], "not_due": []}
    f.w.fetch = lambda: f.start
    got = f.w.acceptances(f.start)
    first = WAKER.tick(f.w, False)
    second = WAKER.tick(f.w, False)
    f.w.fetch = lambda: f.head                  # master moved: the same closure, another base
    third = WAKER.tick(f.w, False)
    cmd = f.codex.calls[0] if f.codex.calls else []
    wt = Path(cmd[cmd.index("-C") + 1]) if "-C" in cmd else None
    text = cmd[-1] if cmd else ""
    memos = sorted(p.name for p in (f.w.home / "accepts").iterdir())
    check("W12", [d["closure"] for d in got["due"]] == [ta] and len(f.codex.calls) == 1
          and "woken, codex exited 0" in first[-1] and "done" in second[-1] and "done" in third[-1]
          and memos == [f"{ta}.json"] and wt is not None and wt.name == f"accept-{ta[:12]}-{f.start[:12]}"
          and not wt.exists() and all(x in text for x in (ta, a, ha, "s0fractal/warrant#9", "merge " + "c" * 40,
                                                          "Counter blobs are accepted from any key.", f.start,
                                                          WAKER.VERDICT_BRANCH + ta[:12]))
          and "CONCLUSION" not in text,
          "the base's roadmap.py due names the closure whose prerequisites are met (not the dependent one); Codex is "
          "woken for it once, in its own worktree of the base, told the duty, the closure, its evidence and what that "
          "evidence names, never what the closure says it established; not again in later runs, at another base",
          (got, first, second, third, memos))

    f.put("codex", "accept", R.accept(ta, 0, [ha]))
    fourth = WAKER.tick(f.w, False)
    now = [d["closure"] for d in f.w.acceptances(f.head)["due"]]
    check("W14", now == [tb] and len(f.codex.calls) == 2 and tb in f.codex.calls[1][-1] and "woken" in fourth[-1],
          "once the prerequisite's closure is accepted on the base, the next run finds the dependent closure due and "
          "wakes Codex for it", (now, fourth))
    f.close()

    g = pr_world()
    g.w.fetch = lambda: g.start
    g.w.acceptances = lambda base: {"due": [entry(1), entry(2)]}
    open_pr = {"pr": 5, "head": "e" * 40, "branch": WAKER.VERDICT_BRANCH + "1" * 12, "not_due": [["REVIEWED", "x"]]}
    g.w.due = lambda base: {"due": [], "not_due": [open_pr]}
    held = WAKER.tick(g.w, False)
    g.w.due = lambda base: {"due": [], "not_due": [], "refused": "REFUSED BASE_CONFIG x"}
    unread = WAKER.tick(g.w, False)
    after_held = len(g.codex.calls)
    g.w.due = lambda base: {"due": [], "not_due": []}
    one = WAKER.tick(g.w, False)
    after_one = [c[-1] for c in g.codex.calls]
    two = WAKER.tick(g.w, False)
    woken = [next(n for n in (1, 2) if f"{n}" * 64 in c[-1]) for c in g.codex.calls]
    check("W13", after_held == 0 and all("held" in x for x in held[-2:] + unread[-2:])
          and len(after_one) == 1 and "next run" in one[-1] and woken == [1, 2] and "done" in two[-2],
          "no acceptance wake while Codex's previous verdict pull request is open, or while the open pull requests "
          "could not be read; at most one per run, the next closure in the next run", (held, unread, one, two))
    g.close()


def main():
    for part in (replay_cases, waker_cases, sandbox_cases, refusal_cases, guard_cases, acceptance_cases):
        try:
            part()
        except Exception as e:      # noqa: BLE001 -- a part that raises fails its cases, the others still run
            import traceback
            traceback.print_exc()
            check(f"RAISED-{part.__name__}", False, "ran to its end", f"{type(e).__name__}: {e}")
    return finish("REVIEW_REPLAY_TEST")


if __name__ == "__main__":
    raise SystemExit(main())
