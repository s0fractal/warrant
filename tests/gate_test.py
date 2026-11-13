#!/usr/bin/env python3
"""The merge gate's predicate (warrant/gate.py) on fixture Git repositories: one case per refusal, each asserting
the exact set of refusal codes (a mutant that removes one rule is seen even where another rule also refuses).

    python3 tests/gate_test.py
"""
import base64
import contextlib
import io
import importlib
import importlib.machinery
import importlib.util
import json
import time
import types
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from world import KEYS, Repo, check, finish, git

from warrant import gate as GT
from warrant.store import _line_id
from warrant import imports as IM
from warrant import records as R

REPO = "s0fractal/warrant"
ROOT = Path(__file__).resolve().parents[1]
MERGE = {"gate": GT.GATE, "base": "master", "required": [{"check": "test", "workflow": ".github/workflows/ci.yml"}],
         "hold_label": "hold", "owner_paths": [".github/", ".warrant/merge.json", ".warrant/v3.json", "AGENTS.md", "tools/gate.py"]}


def green(head, other=False, completed=None):
    runs = [{"name": "test", "head_sha": head, "app": {"slug": "github-actions"}, "check_suite": {"id": 1},
             "status": "completed", "conclusion": "success", "id": 1}]
    if completed is not None:               # GitHub's clock: when the check run completed
        runs[0]["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(completed))
    wf = [{"head_sha": head, "check_suite_id": 1, "path": ".github/workflows/ci.yml"}]
    if other:
        runs.append(dict(runs[0], check_suite={"id": 2}, id=2))
        wf.append({"head_sha": head, "check_suite_id": 2, "path": ".github/workflows/other.yml"})
    return {"check_runs": runs, "workflow_runs": wf}


class PR:
    """A repository with a base commit on master and a pull request #7 from branch `feature` whose author (alice)
    filed its pr-head@1 root and a head version at commit X, and (accept=True) bob's acceptance after X."""

    def __init__(self, accept=True, before_x=None, before_base=None, merge=None):
        self.r = Repo(git_init=False)
        if before_base:
            before_base(self)
        (self.r.dot / "merge.json").write_text(json.dumps(merge or MERGE))
        (self.r.root / "code.py").write_text("x = 1\n")
        (self.r.root / "AGENTS.md").write_text("rules\n")
        git(self.r.root, "init", "-q", "-b", "master")
        self.base = self.r.commit("base")
        git(self.r.root, "checkout", "-q", "-b", "feature")
        (self.r.root / "code.py").write_text("x = 2\n")
        if before_x:
            before_x(self)
        self.x = self.r.commit("the change")
        self.root_v = self.r.entity("alice", "pr-head@1", {"state": "open", "repository": REPO, "pr": 7, "title": "t"})
        self.head_v = self.r.entity("alice", "pr-head@1", {"state": "head", "commit": self.x,
                                                           "tree": git(self.r.root, "rev-parse", f"{self.x}^{{tree}}")}, lineage=self.root_v)
        self.h1 = self.r.commit("head version")
        if accept:
            self.r.attest("bob", self.head_v)
        self.head = self.r.commit("verdict")

    def assess(self, labels=(), checks=None, head=None, now=None, present=False, **pr):
        head = head or self.r.commit("tail") if pr.pop("recommit", False) else head or git(self.r.root, "rev-parse", "HEAD")
        facts = dict({"number": 7, "state": "open", "draft": False, "base": "master", "head": head, "labels": list(labels),
                      "branch": "feature", "head_repo": REPO}, **pr)
        return GT.assess(self.r.root, self.base, facts, checks or green(head), now=now, present=present)


def codes(a):
    return set(a.codes())


def eligible_cases():
    p = PR()
    a = p.assess()
    check("E01 an accepted head, records-only tail, green checks: eligible, by the acceptor, at X",
          a.eligible and a.accept and a.accept[0] == "bob" and a.accept[2] == p.x, a.reasons)
    check("E02 the owner's hold label refuses the merge only", codes(p.assess(labels=["hold"])) == {"PR_HOLD"} and p.assess(labels=["hold"]).due is False)
    q = PR(accept=False)
    before = q.assess()
    check("E03 a head with no verdict yet is due for review, and not eligible", before.due and codes(before) == {"NO_ACCEPT"},
          before.reasons)
    q.r.put("dave", "attest", {"verdict": "accept", "target": q.head_v}, refs=[q.head_v])
    check("E12 an acceptance by an actor who is no pr/acceptor does not count", codes(q.assess(recommit=True)) == {"NO_ACCEPT"})


def store_cases():
    p = PR()
    bad = R.record("attest", "eve", 1_900_000_000, {"verdict": "accept", "target": p.head_v}, refs=[p.head_v])
    _, line = R.line(bad, KEYS["dave"])                     # eve's record, signed with dave's key
    p.r.store.add_lines([line])
    check("E04 a line the base's trust does not authenticate refuses both verdicts",
          codes(p.assess(recommit=True)) == {"STORE_PROBLEMS", "TAIL_RECORD_UNREVIEWED"})
    p = PR()
    lines = p.r.store.lines()
    p.r.store.file.write_bytes(b"".join(reversed(lines)))
    a = p.assess(recommit=True)
    check("E25 a head store out of canonical order is refused", codes(a) == {"STORE_NOT_CANONICAL", "TAIL_CHANGES"} or codes(a) == {"STORE_NOT_CANONICAL"}, a.reasons)


def schema_cases():
    def two_authors(s):                     # the repository's quorum: two schema authors, every bootstrap schema backed by both
        s.r.profile["roles"]["schema/author"] = ["alice", "carol"]
        s.r.profile["quorum"] = {"schema/author": 2}
        s.r.write_config()
        for i in s.r.schemas.values():
            s.r.attest("carol", i)
    note = {"name": "note@1", "fields": {"text": "str"}, "states": None, "closed": [], "successors": {}}
    p = PR(accept=False, before_base=two_authors, before_x=lambda s: s.r.put("alice", "schema", note))
    a = p.assess()
    check("E28 a head that proposes one valid schema, backed by its author alone, is due for the acceptor's review, "
          "not refused (6d6bb700: SCHEMA_NOT_COUNTED made it STORE_PROBLEMS)", a.due and codes(a) == {"NO_ACCEPT"}, a.reasons)


def catch_up_cases():
    """The base moves on after the acceptance and the author merges it in (a sibling pull request merged first)."""
    def union(s):                                       # as the repository's own .gitattributes
        (s.r.root / ".gitattributes").write_text(".warrant/records.jsonl merge=union -text\n")

    def merged(p, *how):
        git(p.r.root, "merge", "-q", "--no-edit", *how, "master")
        p.r.store.add_lines([])                         # warrant fmt: the union in canonical order again
        return p.r.commit("records in canonical order")

    def advance(p, path="other.py", text="y = 1\n"):
        git(p.r.root, "checkout", "-q", "master")
        (p.r.root / path).write_text(text)
        p.r.entity("carol", "obligation@1", {"state": "open", "statement": "on the base", "serves": []})
        p.base = p.r.commit("the base moves on")
        git(p.r.root, "checkout", "-q", "feature")
    p = PR(before_base=union)
    advance(p)
    merged(p)
    a = p.assess()
    check("E29 a head that merged the base after the acceptance is held to X's clean merge with the base: eligible "
          "with no new review", codes(a) == set() and a.accept is not None, a.reasons)
    p = PR(before_base=union)
    advance(p)
    merged(p)
    (p.r.root / "code.py").write_text("x = 3\n")
    check("E30 a change beside the base's merged in after X still refuses", codes(p.assess(recommit=True)) == {"TAIL_CHANGES"})
    p = PR(before_base=union)
    advance(p, "code.py", "x = 9\n")                   # the base changes the line X changed: the merge conflicts
    try:
        git(p.r.root, "merge", "-q", "--no-edit", "master")
    except subprocess.CalledProcessError:
        (p.r.root / "code.py").write_text("x = 5\n")   # a resolution neither side had
        git(p.r.root, "add", "-A")
        git(p.r.root, "commit", "-q", "--no-edit")
    p.r.store.add_lines([])
    try:
        a = p.assess(recommit=True)
        got = (codes(a), a.reasons)
    except subprocess.CalledProcessError as e:          # the gate must answer a conflicting merge, not fail on it
        got = (None, f"raised {e}")
    check("E31 a head whose merge of the base conflicts with X is compared with X: its resolution needs a review",
          got[0] == {"TAIL_CHANGES", "TAIL_RECORD_UNREVIEWED"}, got[1])


def tail_cases():
    p = PR()
    (p.r.root / "code.py").write_text("x = 3\n")
    check("E05 a change after X beyond records and blobs refuses", codes(p.assess(recommit=True)) == {"TAIL_CHANGES"})
    held = {}
    p = PR(before_x=lambda s: held.update(o=s.r.entity("alice", "obligation@1", {"state": "open", "statement": "kept", "serves": []})))
    p.r.store.file.write_bytes(b"".join(x for x in p.r.store.lines() if b'"statement":"kept"' not in x))
    check("E06 a record line removed after X refuses", codes(p.assess(recommit=True)) == {"TAIL_CHANGES"})
    p = PR()
    p.r.blob(b"nobody cites me")
    check("E07 a blob added after X that no record added cites refuses", codes(p.assess(recommit=True)) == {"TAIL_BLOB_UNCITED"})
    p = PR()
    p.r.entity("alice", "obligation@1", {"state": "open", "statement": "unrelated", "serves": []})
    check("E08 a record added after X that is not this pull request's nor a verdict refuses",
          codes(p.assess(recommit=True)) == {"TAIL_RECORD_UNREVIEWED"})
    p = PR()
    p.r.put("eve", "challenge", {"target": p.root_v, "statement": "x"}, refs=[p.root_v])
    o = p.r.entity("alice", "obligation@1", {"state": "open", "statement": "o", "serves": []})
    p.r.put("eve", "attest", {"verdict": "seen", "target": o}, refs=[o])
    a = p.assess(recommit=True)
    check("E09 an attest by an actor who is no pr/acceptor, about another record, is no verdict",
          codes(a) == {"TAIL_RECORD_UNREVIEWED"} and len(a.reasons[0][1].split(": ")[1].split(", ")) == 2, a.reasons)


def lineage_cases():
    p = PR(before_x=lambda s: (s.r.root / "AGENTS.md").write_text("weaker rules\n"))
    a = p.assess()
    check("E10 a change to an owner path refuses the merge, not the review", codes(a) == {"OWNER_PATHS"}, a.reasons)
    p = PR()
    p.r.put("bob", "challenge", {"target": p.head_v, "statement": "P1 broken", "severity": "P1", "what": "w", "where": [],
                                 "commit": p.x, "tree": "t"}, "finding@1", refs=[p.head_v])
    a = p.assess(recommit=True)
    check("E11 a finding standing against the head version refuses the merge", codes(a) == {"OPEN_FINDING"} and not a.due, a.reasons)
    p = PR()
    p.r.entity("alice", "pr-head@1", {"state": "head", "commit": p.x, "tree": "f" * 40}, lineage=p.root_v)
    check("E13 two head versions succeeding one version fork the review", codes(p.assess(recommit=True)) == {"HEAD_FORK"})
    p = PR()
    git(p.r.root, "checkout", "-q", "--orphan", "other")
    (p.r.root / "code.py").write_text("x = 9\n")
    other = p.r.commit("unrelated history")
    check("E14 a head whose X is not an ancestor is refused", "HEAD_NOT_ANCESTOR" in codes(p.assess(head=other)))
    p = PR(accept=False)
    v = p.r.entity("alice", "pr-head@1", {"state": "head", "commit": p.x, "tree": "e" * 40}, lineage=p.head_v)
    p.r.attest("bob", v)
    check("E15 a head version naming another tree than its commit's is refused", codes(p.assess(recommit=True)) == {"HEAD_COMMIT"})


def verdict_cases():
    def setup(branch="codex/verdicts/x", repo=REPO, due=True, again=False):
        r = Repo()
        (r.dot / "merge.json").write_text(json.dumps(MERGE))
        o = r.entity("alice", "obligation@1", {"state": "open", "statement": "o", "serves": []})
        d = r.entity("alice", "obligation@1", {"state": "done", "statement": "o", "serves": []}, lineage=o) if due else o
        git(r.root, "init", "-q", "-b", "master")
        base = r.commit("base")
        git(r.root, "checkout", "-q", "-b", "verdict")
        r.attest("bob", d)
        head = r.commit("bob's verdict")
        if again:
            git(r.root, "checkout", "-q", "master")
            git(r.root, "checkout", "-q", "verdict", "--", ".warrant")
            base = r.commit("master got the same verdict")
        facts = {"number": 9, "state": "open", "draft": False, "base": "master", "head": head, "labels": [], "branch": branch,
                 "head_repo": repo}
        return GT.assess(r.root, base, facts, green(head))
    a = setup()
    check("E16 a pull request of verdicts only, due at the base, by a roadmap/acceptor: eligible, never due",
          a.eligible and not a.due and a.facts.get("verdicts"), a.reasons)
    check("E17 verdicts only from another repository's branch are refused", codes(setup(repo="mallory/warrant")) == {"VERDICTS_FORK"})
    check("E23 verdicts only from a branch outside codex/verdicts/ are refused", codes(setup(branch="feature")) == {"VERDICTS_BRANCH"})
    check("E18 a verdict the base holds already is refused", "VERDICT_NOT_NEW" in codes(setup(again=True)))
    check("E19 a verdict on a version the base does not hold due for its actor is refused", codes(setup(due=False)) == {"VERDICT_NOT_DUE"})
    def claims_pr(branch="claims/verdicts/x", state="backed", verifier=True):
        r = Repo()
        r.trust["keys"]["claims-checker"] = [KEYS["dave"].public]
        r.profile["roles"]["claim/verifier"] = ["claims-checker"] if verifier else []
        r.write_config()
        (r.dot / "merge.json").write_text(json.dumps(MERGE))
        c = r.entity("alice", "claim@1", {"state": state, "id": "V3-3-1", "source": "docs/V3.md", "section": "3", "text": "t",
                                          "witnesses": ["q_test:Q1"], "mutants": ["Z1"],
                                          **({"reason": "states no rule"} if state == "informative" else {})})
        git(r.root, "init", "-q", "-b", "master")
        base = r.commit("base")
        git(r.root, "checkout", "-q", "-b", "verdicts")
        r.t += 1
        r.store.append(R.record("attest", "claims-checker", r.t, {"target": c, "verdict": "accept", "commit": base}, refs=[c]),
                       KEYS["dave"], r.trust)
        head = r.commit("the checker's acceptance")
        facts = {"number": 9, "state": "open", "draft": False, "base": "master", "head": head, "labels": [], "branch": branch,
                 "head_repo": REPO}
        return GT.assess(r.root, base, facts, green(head))
    ok, wrong, idle, nobody = claims_pr(), claims_pr(branch="codex/verdicts/x"), claims_pr(state="informative"), claims_pr(verifier=False)
    check("E66 a pull request of the claims checker's acceptances only, on backed claims' leaves at the base, from a branch "
          "under claims/verdicts/, is the gate's to merge (CI re-executes each first); from another branch, on a claim "
          "that is not backed, or by a checker that is no claim/verifier at the base, it is not",
          ok.eligible and ok.facts.get("verdicts") and codes(wrong) == {"VERDICTS_BRANCH"} and codes(idle) == {"VERDICT_NOT_DUE"}
          and "NO_REVIEW" in codes(nobody), (ok.reasons, wrong.reasons, idle.reasons, nobody.reasons))
    r = Repo()
    o1 = r.entity("alice", "obligation@1", {"state": "open", "statement": "first", "serves": []})
    o2 = r.entity("alice", "obligation@1", {"state": "open", "statement": "second", "serves": []})
    d2 = r.entity("alice", "obligation@1", {"state": "done", "statement": "second", "serves": []}, lineage=o2, requires=[o1])
    rep = GT.assess_snapshot(type("B", (), {"trust": r.trust, "profile": r.profile})(), r.store.snapshot())
    check("E24 a version whose required lineage is open is not due for a verdict",
          d2 not in {x["version"] for x in GT.due_for(rep, r.profile, "bob", ("obligation@1",))})


def check_cases():
    p = PR()
    a = p.assess(checks=green(git(p.r.root, "rev-parse", "HEAD"), other=True))
    check("E20 a required check of that name from another workflow is refused (CHECK_AMBIGUOUS)", codes(a) == {"CHECK_AMBIGUOUS"}, a.reasons)
    a = p.assess(checks={"check_runs": [], "workflow_runs": []})
    check("E26 a required check with no run at the head is refused", codes(a) == {"CHECK_MISSING"})


def merge_cases():
    p = PR()
    a = p.assess()
    head = a.pr["head"]

    class GH:
        def __init__(self, now_head=head, tip=p.base):
            self.now_head, self.tip_, self.merged = now_head, tip, []

        def pull(self, n):
            return dict(a.pr, head=self.now_head)

        def tip(self, b):
            return self.tip_

        def merge(self, n, sha, title, msg):
            self.merged.append(sha)
            return {"merged": True, "sha": "c" * 40}

        def parents(self, sha):
            return [p.base, head]

        def dispatch(self, w, b):
            return None
    b = GT.Base(p.r.root, p.base)
    moved = GH(now_head="d" * 40)
    m = GT.merge_one(b, a, moved)
    check("E21 the gate reads the pull request again: a head moved since the assessment is not merged",
          not m["merged"] and "HEAD_MOVED" in m["why"] and not moved.merged, m)
    gone = GH(tip="e" * 40)
    m = GT.merge_one(b, a, gone)
    check("E22 ... and the base again: a base moved since the assessment is not merged", not m["merged"] and not gone.merged, m)
    ok = GH()
    m = GT.merge_one(b, a, ok)
    check("E27 an eligible pull request is merged at the head assessed, and the required workflows dispatched",
          m["merged"] and ok.merged == [head] and m["as_assessed"] and m["dispatched"] == [".github/workflows/ci.yml"], m)


def imported_modules(root, start, searched=("", "tools")):
    """The files of the repository at `root` that running `start` loads (warrant.imports, the walk the claims checker
    names an acceptance's files by), searched as the workflow starts the gate: the checkout, then tools/."""
    return IM.closure(root, start, searched)


def listed_by(policy, f):
    return any(f == e or (e.endswith("/") and f.startswith(e)) for e in policy)


def closure_cases():
    doc = json.loads((ROOT / ".warrant" / "merge.json").read_text())
    tight = doc["owner_paths"] + doc.get("constitutional", {}).get("paths", [])      # the owner's, or the longest windows
    policy = tight + doc.get("watched", {}).get("paths", [])
    closure = imported_modules(ROOT, "tools/gate.py")
    check("E32 every module the gate imports, directly or through another, is an owner, a constitutional or a watched "
          "path of this repository, and the gate itself is an owner or a constitutional path", "warrant/gate.py" in closure
          and listed_by(tight, "warrant/gate.py") and listed_by(tight, "tools/gate.py")
          and not [f for f in closure if not listed_by(policy, f)], sorted(closure))
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "warrant"
        w.mkdir()
        for name, text in {"__init__": "", "a": "from . import b\n", "b": "def f():\n    from warrant.c import x\n",
                           "c": "from .d import y\n", "d": "import json\nimport warrant.f\n", "e": "", "f": "from warrant import g\n", "g": ""}.items():
            (w / f"{name}.py").write_text(text)
        found = imported_modules(Path(d), "warrant/a.py")
        (w / "g").mkdir()
        (w / "g" / "__init__.py").write_text("")
        (w / "c" / "deep").mkdir(parents=True)
        shadowed = imported_modules(Path(d), "warrant/a.py")
    check("E33 ... the walk follows each form of import, one inside a function too, through other modules, and reaches no module nothing imports",
          found == {f"warrant/{x}.py" for x in ("__init__", "a", "b", "c", "d", "f", "g")}, sorted(found))
    check("E46 ... and it names what the interpreter loads: a same-name package in place of the module's file, and the "
          "file still where the directory of its name has no __init__",
          shadowed == {f"warrant/{x}.py" for x in ("__init__", "a", "b", "c", "d", "f")} | {"warrant/g/__init__.py"}, sorted(shadowed))
    with tempfile.TemporaryDirectory() as d:
        for name, text in {"t.py": 'run([sys.executable, "-m", "p"])\nrun(("python", "-m", "q.r"))\n'
                                   'run(["python", "-c", "import s; from u import v"])\nrun(["git", "-c", "a=b", "commit", "-m", "x.y"])\n',
                           "p/__init__.py": "", "p/__main__.py": "import w\n", "q/__init__.py": "", "q/r.py": "", "s.py": "",
                           "u.py": "", "w.py": "", "x.py": "", "bad.py": "def (\n", "uses_bad.py": "import bad\n"}.items():
            (Path(d) / name).parent.mkdir(parents=True, exist_ok=True)
            (Path(d) / name).write_text(text)
        programs = IM.closure(Path(d), "t.py")
        try:
            IM.closure(Path(d), "uses_bad.py")
            unreadable = None
        except IM.Unreadable as e:
            unreadable = str(e)
    check("E60 ... and it follows the programs a file starts by name: `-m` a module (a package's __main__ too) and the "
          "imports of `-c` code (a string after `-m` that names a module of the repository is followed whatever the program: "
          "naming more is the safe side); a file of the closure that does not parse is no closure (Unreadable), never a partial one",
          programs == {"t.py", "p/__init__.py", "p/__main__.py", "w.py", "q/__init__.py", "q/r.py", "s.py", "u.py", "x.py"}
          and unreadable is not None and unreadable.startswith("bad.py"), (sorted(programs), unreadable))
    probe = ("import json, os, runpy, sys\nsys.argv = ['tools/gate.py', 'gate', '--help']\nsys.path.insert(0, os.path.abspath('tools'))\n"
             "sys.stdout = open(os.devnull, 'w')\ntry:\n    runpy.run_path('tools/gate.py', run_name='__main__')\nexcept SystemExit:\n    pass\n"
             "here = os.path.realpath('.') + os.sep\nfrom_ = lambda m: getattr(m, '__file__', None) or ''.join(list(getattr(m, '__path__', []))[:1])\n"
             "sys.__stdout__.write(json.dumps(sorted({os.path.realpath(from_(m))[len(here):] for m in list(sys.modules.values())\n"
             "                                         if from_(m) and os.path.realpath(from_(m)).startswith(here)})))\n")
    r = subprocess.run([sys.executable, "-B", "-c", probe], cwd=ROOT, capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=str(ROOT)))          # as merge-on-acceptance.yml starts it
    try:
        ran = set(json.loads(r.stdout))
    except ValueError:
        ran = {f"unreadable: {r.stderr[-300:]}"}
    check("E47 a fresh interpreter started as the workflow starts the gate loads, from the checkout, only files the walk found, each a listed path",
          "warrant/gate.py" in ran and ran <= closure and not [f for f in ran if not listed_by(policy, f)], sorted(ran))


# The endings this interpreter loads an extension module from, and one of the merge workflow's runner (CPython 3.11, Linux).
EXT = importlib.machinery.EXTENSION_SUFFIXES
RUNNER = ".cpython-311-x86_64-linux-gnu.so"
LINK, SUBMODULE = "120000", "160000"


def plumb(root, *args, data=None, index=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
               GIT_AUTHOR_DATE="2026-10-27T00:00:00Z", GIT_COMMITTER_DATE="2026-10-27T00:00:00Z", **({"GIT_INDEX_FILE": index} if index else {}))
    return subprocess.run(["git", "-C", str(root), *args], input=data, capture_output=True, check=True, env=env).stdout.decode().strip()


def grown(r, base, entries):
    """The commit that adds or replaces `entries` ({path: bytes, or (mode, bytes; a commit id for a submodule), or None
    to remove it}) on commit `base`, written as Git objects alone: its tree can hold what this working tree could not
    (two names the file system folds into one, a submodule entry), and the gate reads Git objects, never a checkout."""
    index = str(r.home / "candidate.index")
    plumb(r.root, "read-tree", base, index=index)
    for path, v in entries.items():
        if v is None:
            plumb(r.root, "update-index", "--force-remove", path, index=index)
            continue
        mode, content = v if isinstance(v, tuple) else ("100644", v)
        oid = content if mode == SUBMODULE else plumb(r.root, "hash-object", "-w", "--stdin", data=content)
        plumb(r.root, "update-index", "--add", "--cacheinfo", f"{mode},{oid},".encode() + os.fsencode(path), index=index)
    return plumb(r.root, "commit-tree", "-m", "candidate", "-p", base, plumb(r.root, "write-tree", index=index))


def package_at(root):
    """This checkout's package and tools, as files, in the fixture at `root`: the modules the base's policy lists."""
    for d in ("warrant", "tools"):
        shutil.copytree(ROOT / d, root / d, ignore=shutil.ignore_patterns("__pycache__"))


# What a pull request may add beside the modules the policy lists, by the rule that makes it the owner's to merge. Each
# row is one candidate: {path: content}. Every row was first tried on the interpreter (which of them it loads is in the
# cases E48 and E49); the gate refuses more than one interpreter loads, never less.
SHADOWS = {
    "E36 a directory, a link or a submodule of a listed module's name is the owner's to merge (Codex challenge of dda3ad65: "
    "warrant/shapes/__init__.py was eligible)": [
        {"warrant/shapes/__init__.py": b"X = 1\n"}, {"warrant/shapes/other.py": b""}, {"warrant/gate/__init__.py": b""},
        {"tools/gate/__init__.py": b""}, {"warrant/shapes": (LINK, b"../docs")}, {"warrant/shapes": (SUBMODULE, None)},
        {"warrant/__init__/x.py": b""}],
    "E37 ... a file of that name with another ending the import system reads (an extension module is preferred to the source)":
        [{f"warrant/shapes{e}": b"\x7fELF"} for e in EXT] + [
        {f"warrant/keys{RUNNER}": b"\x7fELF"}, {f"warrant/__init__{RUNNER}": b"\x7fELF"}, {"warrant/store.abi3.so": b""},
        {"warrant/jcs.pyd": b""}, {"warrant/shapes.pyc": b""}, {"tools/gate.pyc": b""}],
    "E38 ... and the bytecode cache of a directory that holds one (it is loaded in place of the source)": [
        {"warrant/__pycache__/shapes.cpython-311.pyc": b""}, {"tools/__pycache__/gate.cpython-311.pyc": b""},
        {"warrant/__pycache__": (LINK, b"../docs")}],
    "E39 a module added to a directory the interpreter searches before the standard library is the owner's to merge": [
        {"json.py": b""}, {"tools/pathlib.py": b""}, {"sitecustomize.py": b""}, {"msvcrt.py": b""}, {"warrant.py": b""},
        {f"_cffi_backend{RUNNER}": b""}, {"tools/zlib.pyd": b""}, {"readline.pyc": b""}],
    "E40 ... a directory added there": [
        {"cryptography/__init__.py": b""}, {"json/decoder.py": b""}, {"tools/warrant/__init__.py": b""}, {"pip/__main__.py": b""},
        {"Docs/notes.py": b""}],      # where nothing is folded this is another directory than docs/
    "E41 ... an __init__ added to a directory that was there": [
        {"docs/__init__.py": b""}, {f"docs/__init__{RUNNER}": b""}, {"tests/__init__.pyc": b""}],
    "E42 ... and an entry there that is a link or a submodule": [
        {"json": (LINK, b"docs")}, {"tools/pathlib": (LINK, b"../docs")}, {"vendored": (SUBMODULE, None)}, {"NOTES.md": (LINK, b"docs/a.md")}],
    "E43 a .gitattributes, in any directory, is the owner's to merge (a checkout writes other bytes than the blob's where it says)": [
        {".gitattributes": b"warrant/*.py working-tree-encoding=UTF-7\n"}, {"warrant/.gitattributes": b"*.py ident\n"},
        {"docs/deep/.gitattributes": b""}],
    "E44 a name that a case-folding file system writes over a guarded one is the owner's to merge": [
        {"warrant/ſhapes.py": b""}, {"warrant/SHAPES/__init__.py": b""}, {"Warrant/gate.py": b""}, {"AGENTS.MD": b""},
        {"TOOLS/Pathlib.PY": b""}],
}
BESIDE = [{"warrant/other.py": b""}, {"warrant/shapes_extra.py": b""}, {"warrant/sub/__init__.py": b""}, {"warrant/claims.py": b"x = 2\n"},
          {"tools/claims.py": b"x = 2\n"}, {"docs/notes.py": b""}, {"docs/pkg/__init__.py": b""}, {"docs/a.md": b"more\n"}, {"NOTES.md": b""},
          {"tests/x_test.py": b""}, {"code.py": b"x = 2\n"}, {"warrant/data.json": b"{}"}]


def shadow_cases():
    """R-GATE-CLOSURE, by the base's own policy: what a change may put beside the modules the gate loads."""
    policy = json.loads((ROOT / ".warrant" / "merge.json").read_text())
    listed = (policy["owner_paths"] + policy.get("watched", {}).get("paths", [])     # the places derive from them all
              + policy.get("constitutional", {}).get("paths", []))

    def base(s):
        package_at(s.r.root)
        for f, text in {"docs/a.md": "a\n", "tests/a_test.py": "", "tools/claims.py": "x = 1\n", "warrant/claims.py": "x = 1\n"}.items():
            (s.r.root / f).parent.mkdir(exist_ok=True)
            (s.r.root / f).write_text(text)

    def shadow(s):
        (s.r.root / "warrant" / "shapes").mkdir()
        (s.r.root / "warrant" / "shapes" / "__init__.py").write_text((ROOT / "warrant" / "shapes.py").read_text() + "\nPROBE = True\n")
    p = PR(accept=False, before_base=base, before_x=shadow, merge=policy)
    a = p.assess()
    check("E34 a head that adds a package of the name of a module the gate imports refuses the merge, never the review "
          "(Codex challenge of dda3ad65, observed at a3917a9f: eligible, no reason)",
          codes(a) == {"NO_ACCEPT", "OWNER_PATHS"} and a.due and "warrant/shapes/__init__.py" in dict(a.reasons)["OWNER_PATHS"], a.reasons)
    q = PR(before_base=base, before_x=lambda s: (s.r.root / "warrant" / "other.py").write_text("y = 1\n"), merge=policy)
    check("E35 ... and one that adds a module nothing listed imports is still the gate's to merge", q.assess().eligible, q.assess().reasons)

    def owned(entries):
        entries = {f: (v[0], v[1] or p.base) if isinstance(v, tuple) else v for f, v in entries.items()}
        return GT.owner_paths(p.r.root, p.base, grown(p.r, p.base, entries), listed)
    def shadowed(cid):        # (ok, text, detail) of the SHADOWS row whose name begins with `cid`: one literal check per case
        name = next(n for n in SHADOWS if n.split(" ", 1)[0] == cid)
        got = [(sorted(row), owned(row)) for row in SHADOWS[name]]
        return all(want == found for want, found in got), name.split(" ", 1)[1], [g for g in got if g[0] != g[1]]
    check("E36", *shadowed("E36"))
    check("E37", *shadowed("E37"))
    check("E38", *shadowed("E38"))
    check("E39", *shadowed("E39"))
    check("E40", *shadowed("E40"))
    check("E41", *shadowed("E41"))
    check("E42", *shadowed("E42"))
    check("E43", *shadowed("E43"))
    check("E44", *shadowed("E44"))
    assert len(SHADOWS) == 9, "a row of SHADOWS has no check line above"
    got = [(sorted(row), owned(row)) for row in BESIDE]
    check("E45 beside all of these the gate still merges: a new module of the package, a name that only begins like a listed one, "
          "a file changed where it was, a file deeper in a directory that was there, a file that is no module",
          all(found == [] for _, found in got), [g for g in got if g[1]])
    moved = grown(p.r, p.base, {"docs/a.md": None})                 # the base goes on and drops its only file under docs/
    late = grown(p.r, p.base, {"docs/notes.py": b""})                # a head from before that adds a file there
    got = GT.owner_paths(p.r.root, moved, late, listed), GT.owner_paths(p.r.root, p.base, late, listed)
    check("E50 a directory the base has dropped since the merge base is a directory added: the merge would bring it back",
          got == (["docs/notes.py"], []), got)


def unreadable_cases():
    p = PR()
    odd = grown(p.r, p.head, {b"docs/caf\xe9.txt": b""})           # Latin-1 bytes: a path Git holds and UTF-8 does not
    try:
        a = p.assess(head=odd)
        got = codes(a), a.due
    except UnicodeDecodeError as e:                                  # the case fails on its assertion, not on the gate's crash
        got = f"raised {type(e).__name__}"
    check("E51 a head holding a path that is not UTF-8 is refused (HEAD_UNREADABLE), never the end of the run "
          "(observed at 9509b865: UnicodeDecodeError out of assess, so no other pull request was read)", got == ({"HEAD_UNREADABLE"}, False), got)

    bad = grown(p.r, p.base, {b"docs/caf\xe9.txt": b""})          # the same bytes in the base's own tree
    try:
        GT.Base(p.r.root, bad)
        got = "read"
    except GT.Refused as e:
        got = getattr(e, "code", None) or e.args[-1]
    except UnicodeDecodeError as e:                                  # the case fails on its assertion, not on the gate's crash
        got = f"raised {type(e).__name__}"
    check("E52 a base whose tree holds a path that is not UTF-8 is refused as BASE_CONFIG, never a crash of the gate's run",
          got == "BASE_CONFIG", got)


def interpreter_cases():
    """Why the rules of E36-E42 are what they are: what this interpreter loads when a pull request's file is there."""
    def resolved(name, tree, at, make):
        with tempfile.TemporaryDirectory() as d:
            d = Path(os.path.realpath(d))
            for f, text in tree.items():
                (d / f).parent.mkdir(parents=True, exist_ok=True)
                (d / f).write_text(text)
            make(d)
            importlib.invalidate_caches()
            spec = importlib.machinery.PathFinder.find_spec(name, [str(d / at), *[q for q in sys.path if q]])
            return Path(spec.origin).relative_to(d).as_posix() if spec and spec.has_location and d in Path(spec.origin).parents else None
    pkg = {"warrant/__init__.py": "", "warrant/shapes.py": "", "docs/pkg/__init__.py": ""}
    rows = [("warrant/shapes/__init__.py", "shapes", "warrant", lambda d: (d / "warrant/shapes").mkdir() or (d / "warrant/shapes/__init__.py").write_text("")),
            ("warrant/shapes/__init__.py", "shapes", "warrant", lambda d: os.symlink("../docs/pkg", d / "warrant/shapes")),
            *[(f"warrant/shapes{e}", "shapes", "warrant", lambda d, e=e: (d / f"warrant/shapes{e}").write_text("")) for e in EXT],
            (f"warrant/__init__{EXT[0]}", "warrant", "", lambda d: (d / f"warrant/__init__{EXT[0]}").write_text("")),
            ("json.py", "json", "", lambda d: (d / "json.py").write_text("")),
            ("json/__init__.py", "json", "", lambda d: (d / "json").mkdir() or (d / "json/__init__.py").write_text("")),
            ("msvcrt.py", "msvcrt", "", lambda d: (d / "msvcrt.py").write_text(""))]
    kept = [("warrant/shapes.py", "shapes", "warrant", lambda d: (d / "warrant/shapes").mkdir() or (d / "warrant/shapes/x.py").write_text("")),
            ("warrant/shapes.py", "shapes", "warrant", lambda d: (d / "warrant/shapes.pyc").write_text("")),
            ("warrant/__init__.py", "warrant", "", lambda d: (d / "warrant.py").write_text(""))]
    got = [(want, resolved(name, pkg, at, make)) for want, name, at, make in rows + kept]
    check("E48 this interpreter resolves a module to a same-name package, a link to one or an extension module before its .py file, "
          "and a standard library name to a file of the checkout; a directory without __init__, a .pyc beside the source "
          "and a file beside the package are not preferred (the gate refuses them all the same)",
          all(want == found for want, found in got), [g for g in got if g[0] != g[1]])
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "warrant" / "shapes.py"
        src.parent.mkdir()
        (src.parent / "__init__.py").write_text("")
        src.write_text("WHO = 'the cache'\n")
        py_compile.compile(str(src), cfile=importlib.util.cache_from_source(str(src)), invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        src.write_text("WHO = 'the source'\n")
        r = subprocess.run([sys.executable, "-B", "-c", "import warrant.shapes as s; print(s.WHO, 'at', s.__file__[-17:])"], cwd=d,
                           capture_output=True, text=True, env={k: v for k, v in os.environ.items() if not k.startswith("PYTHON")})
    check("E49 ... and it runs a committed __pycache__ file in place of the source beside it, whose path it still reports",
          r.stdout.strip() == "the cache at warrant/shapes.py", r.stdout + r.stderr[-300:])


WATCHED = dict(MERGE, watched={"paths": ["code.py"], "window_hours": 24, "solo_window_hours": 72, "families": 2,
                               "veto_role": "pr/owner"})
NOW = 1_900_000_000


def watched_cases():
    """Watched paths (merge.json `watched`): what the models merge with the owner watching. The fixture's change is to
    code.py, a watched path; bob holds pr/acceptor, dave pr/owner (the veto role)."""
    def acceptors(*who):
        def f(s):
            s.r.profile["roles"]["pr/acceptor"] = sorted(who)
            s.r.write_config()
        return f
    p = PR(merge=WATCHED)
    head = git(p.r.root, "rev-parse", "HEAD")
    after = lambda h: green(head, completed=NOW - h * 3600)
    one = p.assess(checks=after(25), now=NOW)
    check("E53 a change to a watched path accepted by one pr/acceptor, its author holding none, is not merged by the "
          "gate (WATCHED_FAMILIES); it stays reviewed, not due", codes(one) == {"WATCHED_FAMILIES"} and not one.due
          and one.facts.get("watched") == ["code.py"], one.reasons)
    q = PR(merge=WATCHED, before_base=acceptors("bob", "alice"))
    qh = git(q.r.root, "rev-parse", "HEAD")
    two = q.assess(checks=green(qh, completed=NOW - 25 * 3600), now=NOW)
    early = q.assess(checks=green(qh, completed=NOW - 23 * 3600), now=NOW)
    untimed = q.assess(checks=green(qh), now=NOW)
    check("E54 two families, the head version's author counted when it holds pr/acceptor: merged once the owner's "
          "window has passed since the required checks completed at the head (GitHub's clock), not before, and not "
          "when that time is unknown (WATCHED_WINDOW)", two.eligible and codes(early) == {"WATCHED_WINDOW"}
          and codes(untimed) == {"WATCHED_WINDOW"} and "1.0 h of 24 h remain" in dict(early.reasons)["WATCHED_WINDOW"],
          (two.reasons, early.reasons))
    q.r.put("dave", "challenge", {"target": q.head_v, "statement": "not yet: I want to read it"}, refs=[q.head_v])
    vh = q.r.commit("the owner's veto")
    vetoed = q.assess(checks=green(vh, completed=NOW - 100 * 3600), now=NOW, head=vh)
    q2 = PR(merge=WATCHED, before_base=acceptors("bob", "alice"))
    q2.r.put("eve", "challenge", {"target": q2.head_v, "statement": "a reader's objection"}, refs=[q2.head_v])
    eh = q2.r.commit("a challenge by no role")
    other = q2.assess(checks=green(eh, completed=NOW - 100 * 3600), now=NOW, head=eh)
    check("E55 a challenge by the veto role (pr/owner) on the head version stops the merge, counted or not "
          "(OWNER_VETO); one by an actor of no role does not", codes(vetoed) == {"OWNER_VETO"} and other.eligible,
          (vetoed.reasons, other.reasons))
    solo = PR(merge=WATCHED, accept=False, before_base=acceptors("bob", "alice"))
    sh = git(solo.r.root, "rev-parse", "HEAD")
    s70 = solo.assess(checks=green(sh, completed=NOW - 70 * 3600), now=NOW)
    s73 = solo.assess(checks=green(sh, completed=NOW - 73 * 3600), now=NOW)
    held = solo.assess(checks=green(sh, completed=NOW - 73 * 3600), now=NOW, labels=["hold"])
    check("E56 one family only (its author, no acceptor: the others out of budget): the gate itself merges it once the "
          "longer solo window has passed with nothing else refusing (solo_ready), not before, and a hold label withdraws it "
          "(owner, 2026-11-13: agents stop merging under the owner's name)",
          s73.eligible and s73.facts.get("solo") is True and "solo" in GT.line(s73) and not s70.eligible
          and codes(s70) == {"NO_ACCEPT", "WATCHED_FAMILIES"} and not held.eligible
          and s73.facts.get("solo_ready") is True and s70.facts.get("solo_ready") is False
          and held.facts.get("solo_ready") is False and s73.facts.get("solo_from") == NOW - 73 * 3600 + 72 * 3600,
          (s70.facts, s73.facts, held.reasons))
    plain = PR(merge=dict(WATCHED, watched=dict(WATCHED["watched"], paths=["elsewhere.py"])))
    pa = plain.assess()
    check("E57 a change to no watched and no owner path keeps the rule it had: one acceptance, no window",
          pa.eligible and "watched" not in pa.facts, pa.reasons)
    def shadow(s):
        (s.r.root / "code").mkdir()
        (s.r.root / "code" / "__init__.py").write_text("x = 3\n")
    sp = PR(merge=WATCHED, before_x=shadow, before_base=acceptors("bob", "alice"))
    spa = sp.assess(checks=green(git(sp.r.root, "rev-parse", "HEAD"), completed=NOW - 100 * 3600), now=NOW)
    check("E59 a place a watched file implies (a package of its module's name) is the owner's, not watched: only a "
          "change to a watched file itself is the models' to merge", "OWNER_PATHS" in codes(spa)
          and "code/__init__.py" in dict(spa.reasons)["OWNER_PATHS"] and spa.facts.get("watched") == ["code.py"], spa.reasons)
    bad = [dict(WATCHED, watched=dict(WATCHED["watched"], paths=["AGENTS.md"])),
           dict(WATCHED, watched=dict(WATCHED["watched"], families=1)),
           dict(WATCHED, watched=dict(WATCHED["watched"], solo_window_hours=12)),
           dict(WATCHED, watched=dict(WATCHED["watched"], window_hours=0)),
           dict(WATCHED, watched=dict(WATCHED["watched"], extra=1))]
    refused = [codes(PR(merge=m).assess()) for m in bad]
    check("E58 a watched policy that names an owner path, one family, a solo window shorter than the window, no window or "
          "an unknown member is refused as the base's configuration", all(c == {"BASE_CONFIG"} for c in refused), refused)


CONST = dict(WATCHED, owner_paths=[".github/", ".warrant/merge.json"], watched=dict(WATCHED["watched"], paths=["core.py"]),
             constitutional={"paths": ["AGENTS.md", ".warrant/v3.json", "tools/gate.py"], "window_hours": 72,
                             "solo_window_hours": 168, "families": 2, "veto_role": "pr/owner", "notify": ["owner-login"]})


def constitution_cases():
    """The constitutional tier (merge.json `constitutional`, owner 2026-11-13): the rules, the receiver and the gate
    are merged by the models with the owner watching, over windows longer than the core's; one comment names the owner
    when the window opens. And `solo`: one family's change to no listed path, merged by the gate after its window."""
    def acceptors(*who):
        def f(s):
            s.r.profile["roles"]["pr/acceptor"] = sorted(who)
            s.r.write_config()
        return f

    def rules(s):
        (s.r.root / "AGENTS.md").write_text("rules, amended\n")
    two = PR(merge=CONST, before_x=rules, before_base=acceptors("bob", "alice"))
    th = git(two.r.root, "rev-parse", "HEAD")
    at = {h: two.assess(checks=green(th, completed=NOW - h * 3600), now=NOW) for h in (71, 73)}
    check("E61 a change to a constitutional path accepted by two families is merged by the gate after the constitutional "
          "window (72 h here), not after the watched one, and leaves the notice its comment carries",
          codes(at[71]) == {"WATCHED_WINDOW"} and at[73].eligible and at[73].facts.get("constitutional") == ["AGENTS.md"]
          and "watched" not in at[73].facts and (at[73].facts.get("notice") or {}).get("notify") == ["owner-login"]
          and at[73].facts["notice"]["window_until"] == NOW - 73 * 3600 + 72 * 3600, (at[71].reasons, at[73].facts))
    one = PR(merge=CONST, before_x=rules, accept=False, before_base=acceptors("bob", "alice"))
    oh = git(one.r.root, "rev-parse", "HEAD")
    s = {h: one.assess(checks=green(oh, completed=NOW - h * 3600), now=NOW) for h in (100, 169)}
    both = PR(merge=CONST, before_x=lambda q: (rules(q), (q.r.root / "core.py").write_text("y = 1\n")), accept=False,
              before_base=acceptors("bob", "alice"))
    bh = git(both.r.root, "rev-parse", "HEAD")
    mixed = {h: both.assess(checks=green(bh, completed=NOW - h * 3600), now=NOW) for h in (100, 169)}
    check("E62 ... one family: merged by the gate after the constitutional solo window (168 h), not after the watched one "
          "(72 h); a change to both tiers waits for the longer",
          not s[100].eligible and s[169].eligible and s[169].facts.get("solo") and not mixed[100].eligible
          and mixed[169].eligible and mixed[169].facts.get("solo_from") == NOW - 169 * 3600 + 168 * 3600,
          (s[100].reasons, s[169].reasons, mixed[100].reasons, mixed[169].facts.get("solo_from")))
    c = CONST["constitutional"]
    bad = [dict(CONST, watched=None) and {k: v for k, v in CONST.items() if k != "watched"},
           dict(CONST, constitutional=dict(c, window_hours=12, solo_window_hours=48)),
           dict(CONST, constitutional=dict(c, solo_window_hours=71)),
           dict(CONST, constitutional=dict(c, paths=["core.py"])),
           dict(CONST, constitutional=dict(c, paths=[".github/"])),
           dict(CONST, constitutional=dict(c, notify=["@owner"])),
           dict(CONST, constitutional={k: v for k, v in c.items() if k != "notify"}),
           dict(CONST, solo={"window_hours": 73, "veto_role": "pr/owner"}),
           dict(CONST, solo={"window_hours": 4}),
           dict(MERGE, solo={"window_hours": 721, "veto_role": "pr/owner"})]
    refused = [codes(PR(merge=m).assess()) for m in bad]
    check("E63 a constitutional tier without a watched one, with a window or a solo window shorter than the watched one, "
          "naming a watched or an owner path, a login that is not one, or no notify; a solo rule longer than the watched "
          "solo window or without its veto role: each is refused as the base's configuration",
          all(x == {"BASE_CONFIG"} for x in refused), refused)
    SOLO = dict(MERGE, solo={"window_hours": 4, "veto_role": "pr/owner"})
    q = PR(merge=SOLO, accept=False, before_base=acceptors("bob", "alice"))
    qh = git(q.r.root, "rev-parse", "HEAD")
    early, late = (q.assess(checks=green(qh, completed=NOW - h * 3600), now=NOW) for h in (3, 5))
    stranger = PR(merge=SOLO, accept=False)
    sh = git(stranger.r.root, "rev-parse", "HEAD")
    nobody = stranger.assess(checks=green(sh, completed=NOW - 5 * 3600), now=NOW)
    q.r.put("dave", "challenge", {"target": q.head_v, "statement": "wait"}, refs=[q.head_v])
    vh = q.r.commit("the owner's veto")
    vetoed = q.assess(checks=green(vh, completed=NOW - 50 * 3600), now=NOW, head=vh)
    unset = PR(accept=False, before_base=acceptors("bob", "alice"))
    uh = git(unset.r.root, "rev-parse", "HEAD")
    plain = unset.assess(checks=green(uh, completed=NOW - 500 * 3600), now=NOW)
    check("E64 `solo`: a change to no listed path by a pr/acceptor, with no acceptance, is merged by the gate once its "
          "window has passed since the checks completed; not before, not by an author who holds no pr/acceptor, not "
          "against a pr/owner's challenge, and not at all where merge.json has no solo rule",
          codes(early) == {"NO_ACCEPT"} and late.eligible and late.facts.get("solo") and late.accept[0] == "alice"
          and not nobody.eligible and "OWNER_VETO" in codes(vetoed) and not vetoed.eligible and codes(plain) == {"NO_ACCEPT"},
          (early.reasons, late.reasons, nobody.reasons, vetoed.reasons, plain.reasons))

    class GH:
        def __init__(self, old=()):
            self.old, self.posted = list(old), []

        def comments(self, n):
            return self.old

        def comment(self, n, body):
            self.posted.append(body)
            self.old.append({"body": body, "user": {"login": "github-actions[bot]"}})
    b = GT.Base(two.r.root, two.base)
    gh = GH()
    first = GT.notify(b, [at[73], at[71]], gh)
    again = GT.notify(b, [at[73]], gh)
    forged = GH(old=[{"body": GT.NOTICE.format(x=at[73].facts["notice"]["x"]), "user": {"login": "someone"}}])
    GT.notify(b, [at[73]], forged)
    quiet = GT.notify(b, [late], GH())
    text = gh.posted[0] if gh.posted else ""
    check("E65 when a constitutional window opens the gate comments once per head commit, naming the owner's login, the "
          "paths, when each window ends and how to veto; a comment with its mark by another user does not count, and a "
          "change to no tier gets none",
          len(gh.posted) == 1 and first == [(7, "noticed")] and again == [] and "@owner-login" in text
          and "`AGENTS.md`" in text and "`hold`" in text and at[73].facts["notice"]["version"] in text
          and len(forged.posted) == 1 and quiet == [], (first, again, gh.posted, forged.posted, quiet))

PRES = dict(CONST, presence={"login": "owner-login", "days": 14, "since": NOW - 30 * 86400})


def brake_cases():
    """The owner present (2026-11-13: «72 hours of waiting» stays only for when he is away): no window before a tier's
    merge, the brake after it: his `hold` label or challenge within the window the merge would have waited, and the
    gate reverts it; a release waits until every brake in its history has closed."""
    def acceptors(*who):
        def f(s):
            s.r.profile["roles"]["pr/acceptor"] = sorted(who)
            s.r.write_config()
        return f

    def rules(s):
        (s.r.root / "AGENTS.md").write_text("rules, amended\n")
    one = PR(merge=PRES, before_x=rules, accept=False, before_base=acceptors("bob", "alice"))
    oh = git(one.r.root, "rev-parse", "HEAD")
    here = one.assess(checks=green(oh, completed=NOW - 60), now=NOW, present=True)
    away = one.assess(checks=green(oh, completed=NOW - 60), now=NOW, present=False)
    pending = one.assess(checks=green(oh), now=NOW, present=True)
    two = PR(merge=PRES, before_x=rules, before_base=acceptors("bob", "alice"))
    both = two.assess(checks=green(git(two.r.root, "rev-parse", "HEAD"), completed=NOW - 60), now=NOW, present=True)
    check("E67 the owner present, a constitutional change merges with no window before it once the checks are green, its "
          "brake as long as its window would have been (168 h for one family, 72 h for two); away, the windows apply; "
          "checks not completed, nothing merges",
          here.eligible and here.facts.get("brake_hours") == 168 and not away.eligible and "WATCHED_FAMILIES" in codes(away)
          and not pending.eligible and both.eligible and both.facts.get("brake_hours") == 72,
          (here.reasons, here.facts.get("brake_hours"), away.reasons, pending.reasons, both.reasons, both.facts.get("brake_hours")))

    class GH:
        def __init__(self, commits=None, labels=()):
            self.commits, self.labels, self.calls, self.merges, self.comments_ = commits or {}, list(labels), [], [], []

        def commit(self, sha):
            return self.commits.get(sha, {"author": {"login": "github-actions[bot]"}, "committer": {"login": "web-flow"}})

        def pull(self, n):
            return dict(here.pr, head=oh, labels=self.labels)

        def tip(self, b):
            return one.base

        def merge(self, n, sha, title, msg):
            self.merges.append(msg)
            return {"merged": True, "sha": "c" * 40}

        def parents(self, sha):
            return [one.base, oh]

        def dispatch(self, w, b):
            self.calls.append(("dispatch", w, b))

        def comment(self, n, body):
            self.comments_.append(body)

        def api(self, path, method="GET", body=None, pages=False):
            self.calls.append((path, method, body))
            return {"sha": "d" * 40}
    b = GT.Base(one.r.root, one.base)
    gh = GH()
    m = GT.merge_one(b, here, gh)
    line = next((ln for ln in gh.merges[0].splitlines() if ln.startswith("warrant-gate brake until")), "") if gh.merges else ""
    check("E68 a merge with the owner present carries its brake in the merge commit (until when, the pull request, the head "
          "version) and the gate comments once, naming the owner, how long the brake acts and how to pull it",
          m["merged"] and m.get("brake_until", 0) > time.time() + 167 * 3600 and GT.brake_lines(line) and here.accept[1] in line
          and len(gh.comments_) == 1 and "@owner-login" in gh.comments_[0] and "`hold`" in gh.comments_[0],
          (m, line, gh.comments_))

    # a base whose history holds a braked merge of AGENTS.md (and a record line), then an unrelated commit
    r = Repo(git_init=False)
    (r.dot / "merge.json").write_text(json.dumps(PRES))
    (r.root / "AGENTS.md").write_text("rules\n")
    (r.root / "code.py").write_text("x = 1\n")
    git(r.root, "init", "-q", "-b", "master")
    r.commit("base")
    git(r.root, "checkout", "-q", "-b", "feature")
    (r.root / "AGENTS.md").write_text("rules, weakened\n")
    v = r.entity("alice", "pr-head@1", {"state": "open", "repository": REPO, "pr": 7, "title": "t"})
    r.commit("the change and its record")
    git(r.root, "checkout", "-q", "master")
    until = NOW + 3600
    git(r.root, "merge", "-q", "--no-ff", "feature", "-m", f"Merge pull request #7\n\nwarrant-gate brake until {until}: #7 head version {v}")
    merge = git(r.root, "rev-parse", "HEAD")
    (r.root / "code.py").write_text("x = 2\n")
    base = r.commit("an unrelated change after it")
    rb = GT.Base(r.root, base)
    k = GT.brakes(r.root, base, now=NOW)
    plan, err = GT.revert_plan(r.root, base, merge)
    quiet, held = GH(), GH(labels=["hold"])
    snap, _ = GT.store_at(r.root, base)
    rep = GT.assess_snapshot(rb, snap)
    none_ = GT.vetoed(rb, rep, quiet, k[0]) if k else "no brake"
    held_why = GT.vetoed(rb, rep, held, k[0]) if k else None
    opened = GT.open_revert(r.root, rb, held, k[0], held_why) if k else ""
    tree = next((c[2] for c in held.calls if c[0] == "git/trees"), {})
    after = GT.brakes(r.root, base, now=until + 1)
    check("E69 a merge whose brake is open and that the owner's hold label vetoes is reverted: the gate opens a pull request "
          "from gate/revert/ whose one commit takes back exactly the merge's change, the store's records kept, and starts "
          "CI on it; with no veto nothing is done, and after its window the brake is closed",
          [x["pr"] for x in k] == [7] and err is None and [e["path"] for e in plan] == ["AGENTS.md"] and none_ is None
          and held_why is not None and "hold" in held_why
          and opened.startswith("revert of #7 opened") and [e["path"] for e in tree.get("tree", [])] == ["AGENTS.md"]
          and any(c[0] == "dispatch" for c in held.calls) and after == [],
          (k, plan, err, none_, opened, tree, after))
    (r.root / "AGENTS.md").write_text("rules, changed again\n")
    moved = r.commit("the reverted file changes again")
    _, conflict = GT.revert_plan(r.root, moved, merge)
    git(r.root, "reset", "-q", "--hard", base)
    git(r.root, "checkout", "-q", "-b", f"gate/revert/7-{merge[:12]}")
    (r.root / "AGENTS.md").write_text("rules\n")
    r.commit(f"Revert #7\n\nwarrant-gate revert of {merge}")
    rh = git(r.root, "rev-parse", "HEAD")
    pr = {"number": 8, "state": "open", "draft": False, "base": "master", "head": rh, "labels": [],
          "branch": f"gate/revert/7-{merge[:12]}", "head_repo": REPO, "author": "github-actions[bot]"}
    ok = GT.assess(r.root, base, pr, green(rh))
    forged = GT.assess(r.root, base, dict(pr, author="mallory"), green(rh))
    fork = GT.assess(r.root, base, dict(pr, head_repo="mallory/warrant"), green(rh))
    git(r.root, "reset", "-q", "--hard", base)
    (r.root / "AGENTS.md").write_text("rules\n")
    (r.root / "code.py").write_text("x = 99\n")
    r.commit(f"Revert #7, and more\n\nwarrant-gate revert of {merge}")
    more = git(r.root, "rev-parse", "HEAD")
    wider = GT.assess(r.root, base, dict(pr, head=more), green(more))
    check("E70 the gate's revert is merged as such once its checks are green: the exact revert of a braked merge of the base, "
          "opened by the workflow's bot; one opened by anyone else, or that changes more, is not; a path changed again "
          "since the merge makes no revert",
          ok.eligible and ok.facts.get("revert") == merge and not forged.eligible and "REVERT_NOT_EXACT" in codes(forged)
          and not fork.eligible and not fork.facts.get("revert")
          and not wider.eligible and "REVERT_NOT_EXACT" in codes(wider) and conflict is not None,
          (ok.reasons, forged.reasons, wider.reasons, conflict))
    rc_open = GT.main(["--root", str(r.root), "brakes", "--at", base]) if until > time.time() else None
    later = GT.brakes(r.root, base, now=until + 1)
    check("E71 a release waits for its brakes: `brakes --at C` fails while a merge in C's history may still be vetoed, and "
          "lists none once every window has passed",
          rc_open == 1 and later == [], (rc_open, later))
    owner = {"author": {"login": "owner-login"}, "committer": {"login": "web-flow"}}
    hand = {"author": {"login": "owner-login"}, "committer": {"login": "owner-login"}}
    rb_old = GT.Base(r.root, base)
    def at(cfg_since, commits, days=14, now=NOW):
        rb_old.gate = dict(rb_old.gate, presence={"login": "owner-login", "days": days, "since": cfg_since})
        return GT.present(r.root, rb_old, GH(commits=commits), now=now)
    when = GT._commit(r.root, merge)[1]
    check("E72 the owner is present when a merge into the base on GitHub is his (his login the author, GitHub's web-flow the "
          "committer) since `since` and within `days`; a bot's merge, one he did not make on GitHub, one before `since` "
          "or older than `days` is no presence",
          at(when - 10, {merge: owner}, now=when + 60) and not at(when - 10, {}, now=when + 60)
          and not at(when - 10, {merge: hand}, now=when + 60) and not at(when + 10, {merge: owner}, now=when + 60)
          and not at(when - 10, {merge: owner}, days=1, now=when + 2 * 86400),
          when)
    p = PRES["presence"]
    bad = [{k: v for k, v in PRES.items() if k not in ("watched", "constitutional")},
           dict(PRES, presence=dict(p, days=0)), dict(PRES, presence=dict(p, login="@x")), dict(PRES, presence=dict(p, extra=1))]
    refused = [codes(PR(merge=m).assess()) for m in bad]
    check("E73 a presence rule without a watched tier, with no days, a login that is not one or an unknown member refuses the "
          "base's configuration", all(x == {"BASE_CONFIG"} for x in refused), refused)

def solo_record_cases():
    """Codex challenge 338a305e15a4 on the #350 review (reproduced at 8278d4a3): a merge accepted by a second family was
    recorded as solo (F1), and a commenter whose login merely begins with github-actions could suppress the
    constitutional notice (F2)."""
    def acceptors(*who):
        def f(s):
            s.r.profile["roles"]["pr/acceptor"] = sorted(who)
            s.r.write_config()
        return f
    SOLO_ = dict(MERGE, solo={"window_hours": 0, "veto_role": "pr/owner"})
    p = PR(merge=SOLO_, before_base=acceptors("bob", "alice"))                       # alice's change, bob accepts it
    a = p.assess(checks=green(git(p.r.root, "rev-parse", "HEAD"), completed=NOW - 60), now=NOW)
    q = PR(merge=WATCHED, before_base=acceptors("bob", "alice"))                     # two families, past the solo window
    w = q.assess(checks=green(git(q.r.root, "rev-parse", "HEAD"), completed=NOW - 100 * 3600), now=NOW)
    check("E74 a change a second family accepted is merged as accepted, not as solo, whatever the solo windows say: "
          "solo is the record that no second family reviewed it (Codex F1 on #350)",
          a.eligible and not a.facts.get("solo") and "accepted by bob" in GT.line(a)
          and w.eligible and not w.facts.get("solo") and "accepted by bob" in GT.line(w),
          (a.facts.get("solo"), GT.line(a), w.facts.get("solo"), GT.line(w)))

    def rules(s):
        (s.r.root / "AGENTS.md").write_text("rules, amended\n")
    c = PR(merge=CONST, before_x=rules, before_base=acceptors("bob", "alice"))
    ca = c.assess(checks=green(git(c.r.root, "rev-parse", "HEAD"), completed=NOW - 73 * 3600), now=NOW)

    class GH:
        def __init__(self, old):
            self.old, self.posted = list(old), []

        def comments(self, n):
            return self.old

        def comment(self, n, body):
            self.posted.append(body)
    mark = GT.NOTICE.format(x=(ca.facts.get("notice") or {}).get("x"))
    lookalike = GH([{"body": mark, "user": {"login": "github-actions-evil", "type": "User"}}])
    GT.notify(GT.Base(c.r.root, c.base), [ca], lookalike)
    check("E75 a notice mark in a comment by a login that only begins with github-actions does not count: the notice is "
          "posted (Codex F2 on #350)", len(lookalike.posted) == 1, lookalike.posted)

def presence_cases():
    """Presence by a touch (the analysis session, 2026-11-13: with only `.github/` and merge.json left to him, two quiet
    weeks would read the owner away and bring the windows back while he is here): a reaction of his to a comment of the
    gate is a sign as a merge is; the comments say until when he counts as present; the change to away is announced."""
    v, x = "ab" * 32, "cd" * 20
    check("E76 a brake line is a whole line naming a full record id; a shorter id, trailing words or a revert line naming no "
          "full commit id are none",
          len(GT.brake_lines(f"x\nwarrant-gate brake until 5: #7 head version {v}\ny")) == 1
          and GT.brake_lines(f"warrant-gate brake until 5: #7 head version {v[:-2]}") == []
          and GT.brake_lines(f"warrant-gate brake until 5: #7 head version {v} and more") == []
          and len(GT.revert_lines(f"warrant-gate revert of {x}")) == 1 and GT.revert_lines(f"warrant-gate revert of {x[:-1]}") == [])
    p = PR(merge=PRES)
    b = GT.Base(p.r.root, p.base)
    t = NOW - 86400
    stamp = lambda e: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e))      # noqa: E731

    class GH:
        def __init__(self, comments=(), reactions=None, issues=()):
            self.comments_, self.reactions, self.issues, self.posted = list(comments), reactions or {}, list(issues), []

        def commit(self, sha):
            return {"author": {"login": "github-actions[bot]"}, "committer": {"login": "web-flow"}}

        def api(self, path, method="GET", body=None, pages=False):
            if path.startswith("issues/comments?"):
                return [self.comments_]
            if path.startswith("issues/comments/"):
                return [self.reactions.get(int(path.split("/")[2]), [])]
            if path.startswith("issues?"):
                return [self.issues]
            if path == "issues" and method == "POST":
                self.posted.append(body)
                self.issues.append({"body": body["body"], "user": {"login": "github-actions[bot]"}})
                return {}
            raise AssertionError(path)
    bot = {"login": "github-actions[bot]"}
    gate_c = {"id": 1, "user": bot, "body": GT.BRAKE_MARK + " merged"}
    other_c = {"id": 2, "user": {"login": "owner-login"}, "body": "a comment of his own"}
    mine = {"user": {"login": "owner-login"}, "created_at": stamp(t)}
    seen = GT.presence_until(p.r.root, b, GH([gate_c], {1: [mine]}), now=NOW)
    stranger = GT.presence_until(p.r.root, b, GH([gate_c], {1: [dict(mine, user={"login": "mallory"})]}), now=NOW)
    not_gate = GT.presence_until(p.r.root, b, GH([other_c], {2: [mine]}), now=NOW)
    check("E77 a reaction of the owner's login to a comment of the gate makes him present for `days` from it; a reaction by "
          "another login, or to a comment that is not the gate's, does not",
          seen == t + 14 * 86400 and stranger is None and not_gate is None, (seen, stranger, not_gate))
    gh = GH()
    first = GT.announce_away(b, gh, NOW - 60, now=NOW)
    again = GT.announce_away(b, gh, NOW - 60, now=NOW)
    still = GT.announce_away(b, GH(), NOW + 60, now=NOW)
    check("E78 when his presence ends the gate says so once, in an issue naming him, with what makes him present again; "
          "never again for the same end, and not while he is present",
          first == "away noticed" and again is None and still is None and len(gh.posted) == 1
          and "@owner-login" in gh.posted[0]["body"] and "reaction" in gh.posted[0]["body"], (first, again, still, gh.posted))

def notice_owner_cases():
    """Observed on #356 (head 78979a5f, 2026-11-13): the gate's notice said it may merge a change from a date, though the
    change also touched owner paths (.github/, .warrant/merge.json), which only the owner merges."""
    def both(s):
        (s.r.root / "AGENTS.md").write_text("rules, amended\n")
        (s.r.root / ".github").mkdir(exist_ok=True)
        (s.r.root / ".github" / "x.yml").write_text("on: push\n")
    def acceptors(s):
        s.r.profile["roles"]["pr/acceptor"] = ["alice", "bob"]
        s.r.write_config()
    p = PR(merge=CONST, before_x=both, before_base=acceptors)
    a = p.assess(checks=green(git(p.r.root, "rev-parse", "HEAD"), completed=NOW - 3600), now=NOW)
    check("E79 a change that also touches an owner path gets no constitutional notice: the gate will not merge it, the "
          "owner does", "OWNER_PATHS" in codes(a) and a.facts.get("constitutional") == ["AGENTS.md"] and "notice" not in a.facts,
          (a.reasons, a.facts.get("notice")))

def codex_356_cases():
    """Codex's findings on #356's last head (e8508e7f), reproduced at master 58e3cc74: dccff737, a brake beyond 300
    first-parent commits disappeared; 7a84e332, the exact-revert check ignored tree modes; cd8d1a0b, an expired presence
    announced nothing."""
    r = Repo(git_init=True)
    tree = git(r.root, "rev-parse", "HEAD^{tree}")
    base0 = git(r.root, "rev-parse", "HEAD")
    other = git(r.root, "commit-tree", tree, "-p", base0, "-m", "feature")
    until = int(time.time()) + 7 * 86400
    merge = git(r.root, "commit-tree", tree, "-p", base0, "-p", other, "-m", f"Merge #7\n\nwarrant-gate brake until {until}: #7 head version {'a' * 64}")
    tip = merge
    for i in range(301):
        tip = git(r.root, "commit-tree", tree, "-p", tip, "-m", f"unrelated {i}")
    with contextlib.redirect_stdout(io.StringIO()):
        rc = GT.main(["--root", str(r.root), "brakes", "--at", tip])
    check("E80 an open brake is found however many first-parent commits follow it: `brakes` reads the whole first-parent "
          "history, so a release and the revert still see it after 301 later commits (Codex dccff737 on #356)",
          rc == 1 and any(k["merge"] == merge for k in GT.brakes(r.root, tip)), (rc, GT.brakes(r.root, tip)))

    q = Repo(git_init=False)
    (q.dot / "merge.json").write_text(json.dumps(PRES))
    (q.root / "AGENTS.md").write_text("rules\n")
    git(q.root, "init", "-q", "-b", "master")
    q.commit("base")
    git(q.root, "checkout", "-q", "-b", "feature")
    (q.root / "AGENTS.md").write_text("weakened\n")
    q.commit("change")
    git(q.root, "checkout", "-q", "master")
    git(q.root, "merge", "-q", "--no-ff", "feature", "-m", f"Merge #7\n\nwarrant-gate brake until {until}: #7 head version {'a' * 64}")
    qm = git(q.root, "rev-parse", "HEAD")
    git(q.root, "checkout", "-q", "-b", f"gate/revert/7-{qm[:12]}")
    (q.root / "AGENTS.md").write_text("rules\n")
    head = q.commit(f"Revert #7\n\nwarrant-gate revert of {qm}")
    pr = {"number": 8, "state": "open", "draft": False, "base": "master", "head": head, "labels": [],
          "branch": f"gate/revert/7-{qm[:12]}", "head_repo": REPO, "author": "github-actions[bot]"}
    control = GT.assess(q.root, qm, pr, green(head))
    blob = git(q.root, "rev-parse", f"{head}:.warrant/merge.json")
    git(q.root, "update-index", "--cacheinfo", f"120000,{blob},.warrant/merge.json")
    linked = git(q.root, "commit-tree", git(q.root, "write-tree"), "-p", qm, "-m", f"Revert #7\n\nwarrant-gate revert of {qm}")
    bad = GT.assess(q.root, qm, dict(pr, head=linked), green(linked))
    check("E81 the gate's exact revert compares each path's mode as well as its object: the same blobs with an owner path "
          "turned into a link are no revert (Codex 7a84e332 on #356)",
          control.eligible and not bad.eligible and "REVERT_NOT_EXACT" in codes(bad), (control.reasons, bad.reasons))

    p = PR(merge=PRES)
    b = GT.Base(p.r.root, p.base)
    sign = 1_800_000_000
    b.gate["presence"] = dict(b.gate["presence"], since=sign - 1)
    stamp = time.strftime(GT.STAMP, time.gmtime(sign))

    class GH:
        def __init__(self):
            self.posted = []

        def commit(self, sha):
            return {"author": {"login": "github-actions[bot]"}, "committer": {"login": "web-flow"}}

        def api(self, path, method="GET", body=None, pages=False):
            if path.startswith("issues/comments?"):
                return [[{"id": 1, "user": {"login": "github-actions[bot]"}, "body": GT.BRAKE_MARK}]]
            if path.startswith("issues/comments/1/reactions?"):
                return [[{"user": {"login": "owner-login"}, "created_at": stamp}]]
            if path.startswith("issues?"):
                return [[]]
            if path == "issues" and method == "POST":
                self.posted.append(body)
                return {}
            raise AssertionError(path)
    gh = GH()
    expires = sign + b.gate["presence"]["days"] * 86400
    before = GT.presence_until(p.r.root, b, gh, now=expires - 1)
    after = GT.presence_until(p.r.root, b, gh, now=expires + 1)
    notice = GT.announce_away(b, gh, after, now=expires + 1)
    check("E82 when a sign of presence expires, the deadline is still read, so the change to away is announced (Codex "
          "cd8d1a0b on #356: presence_until dropped the expired sign and the notice never came)",
          before == expires and after == expires and notice == "away noticed" and len(gh.posted) == 1,
          (before, after, notice, gh.posted))

def refresh_cases():
    """#364 (2026-11-13): a pull request of verdicts only conflicts with the base whenever the base gains a record, since
    both append to one file and GitHub applies no merge=union; the claims checker's acceptances run CI for 40 minutes,
    so the base always moves first. The gate merges the base into such a branch itself: the stores' union."""
    r = Repo()
    (r.dot / "merge.json").write_text(json.dumps(MERGE))
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "o", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "o", "serves": []}, lineage=o)
    git(r.root, "init", "-q", "-b", "master")
    r.commit("base")
    git(r.root, "checkout", "-q", "-b", "codex/verdicts/x")
    r.attest("bob", d)
    head = r.commit("bob's verdict")
    head_lines = (r.dot / "records.jsonl").read_bytes()
    git(r.root, "checkout", "-q", "master")
    r.store.write_lines(GT.lines_of((r.dot / "records.jsonl").read_bytes()))
    r.entity("alice", "obligation@1", {"state": "open", "statement": "another", "serves": []})
    base = r.commit("the base moves on")
    base_lines = (r.dot / "records.jsonl").read_bytes()
    facts = {"number": 9, "state": "open", "draft": False, "base": "master", "head": head, "labels": [],
             "branch": "codex/verdicts/x", "head_repo": REPO}
    a = GT.assess(r.root, base, facts, green(head))

    class GH:
        def __init__(self, state, fail=(), branches=(), carry=None, runs=(), dispatch_fails=False, heads=(), tip=None):
            self.state, self.calls, self.fail, self.branches = state, [], set(fail), set(branches)
            self.carry, self.runs, self.dispatch_fails = carry, list(runs), dispatch_fails
            self.heads, self.tip = list(heads), tip            # the source's head at each read; its branch's tip

        def api(self, path, method="GET", body=None, pages=False):
            self.calls.append((path, method, body))
            if (path, method) in self.fail:
                raise GT.Refused(f"gh api {method} {path}: HTTP 502", "GITHUB")
            if path == "git/ref/heads/codex/verdicts/x":
                return {"object": {"sha": self.tip or head}}
            if path.startswith("git/ref/heads/"):
                if path[len("git/ref/heads/"):] not in self.branches:
                    raise GT.Refused(f"gh api GET {path}: gh: Not Found (HTTP 404)", "GITHUB")
                return {"object": {"sha": "e" * 40}}
            if path.startswith("git/commits/") and method == "GET":      # what the branch holds: given, else the carry made
                return self.carry or {"parents": [{"sha": head}, {"sha": base}], "tree": {"sha": "e" * 40}}
            if path.startswith("actions/runs?"):
                return {"workflow_runs": [{"path": w} for w in self.runs]}
            if path == "pulls" and method == "POST":
                return {"number": 10}
            if path.startswith("pulls/"):
                return {"mergeable_state": self.state, "head": {"sha": self.heads.pop(0) if self.heads else head}}
            return {"sha": "e" * 40}

        def dispatch(self, w, br):
            self.calls.append(("dispatch", w, br))
            if self.dispatch_fails:
                raise GT.Refused(f"dispatch {w} on {br}: HTTP 502", "GITHUB")

        def comment(self, n, body):
            self.calls.append(("comment", n, body))
    b = GT.Base(r.root, base)
    dirty, clean = GH("dirty"), GH("clean")
    out = GT.refresh_verdicts(r.root, b, dirty, [a])
    GT.refresh_verdicts(r.root, b, clean, [a])
    sent = next((c[2] for c in dirty.calls if c[0] == "git/blobs"), {})
    union = base64.b64decode(sent.get("content", "")) if sent else b""
    want = b"".join(sorted(set(GT.lines_of(base_lines) + GT.lines_of(head_lines)), key=_line_id))
    commit = next((c[2] for c in dirty.calls if c[0] == "git/commits"), {})
    plain = PR(accept=False)
    other = GT.refresh_verdicts(plain.r.root, GT.Base(plain.r.root, plain.base), GH("dirty"), [plain.assess()])
    fresh = f"codex/verdicts/{base[:12]}-from-9"
    made = [c for c in dirty.calls if c[0] == "git/refs" and c[1] == "POST"]
    opened = [c for c in dirty.calls if c[0] == "pulls" and c[1] == "POST"]
    check("E84 a pull request of verdicts only that conflicts with the base is carried by a new one: the base merged into "
          "its head by the gate (records the union of both stores in canonical order, parents the head and the base) on "
          "a new branch under the same prefix, opened as a pull request with CI started on it, the old one closed with a "
          "comment naming the new one and its branch deleted; a mergeable one, or one not verdicts only, is left alone "
          "(#364)",
          a.facts.get("verdicts") and [n for n, _ in out] == [9] and union == want and commit.get("parents") == [head, base]
          and made and made[0][2] == {"ref": f"refs/heads/{fresh}", "sha": "e" * 40}
          and opened and opened[0][2]["head"] == fresh and opened[0][2]["base"] == "master"
          and ("dispatch", ".github/workflows/ci.yml", fresh) in dirty.calls
          and any(c[0] == "comment" and c[1] == 9 and "#10" in c[2] for c in dirty.calls)
          and ("pulls/9", "PATCH", {"state": "closed"}) in dirty.calls
          and not any(c[1] == "DELETE" for c in dirty.calls)
          and [c[0] for c in clean.calls] == ["pulls/9"] and other == [],
          (out, a.reasons, len(union), len(want), commit.get("parents"), [c[:2] for c in dirty.calls],
           [c[0] for c in clean.calls], other))
    check("E89 ... and the old pull request's branch is never moved: GitHub holds a pull_request run of the workflow "
          "token's update for approval (#379, #382), where a pull request it opens starts none",
          not any(c[1] == "PATCH" and c[0].startswith("git/refs/") for c in dirty.calls), [c[:2] for c in dirty.calls])
    # E90: a run that failed part way is resumed, each step made once
    broke = GH("dirty", fail={("pulls/9", "PATCH")})
    first = GT.refresh_verdicts(r.root, b, broke, [a])
    opened_pr = types.SimpleNamespace(pr={"number": 10, "branch": fresh, "head_repo": REPO, "head": "e" * 40}, facts={}, shared=[])
    again = GH("dirty")
    second = GT.refresh_verdicts(r.root, b, again, [a, opened_pr])
    orphan = GH("dirty", branches={fresh})
    third = GT.refresh_verdicts(r.root, b, orphan, [a])
    posts = lambda g, p: [c for c in g.calls if c[0] == p and c[1] == "POST"]
    check("E90 a refresh that failed part way is resumed with each step made once: the new pull request open, the next "
          "run only closes the old one (no second branch or pull request, no FAILED); the branch made with no pull "
          "request, it opens one from it (the analysis session on #383)",
          "FAILED" in first[0][1] and posts(broke, "git/refs") and posts(broke, "pulls")
          and second == [(9, f"carried by #10 from {fresh} (resumed); codex/verdicts/x kept")] and not posts(again, "git/refs")
          and not posts(again, "pulls") and not posts(again, "git/commits")
          and ("pulls/9", "PATCH", {"state": "closed"}) in again.calls
          and not posts(orphan, "git/refs") and posts(orphan, "pulls") and ("pulls/9", "PATCH", {"state": "closed"}) in orphan.calls,
          (first, second, third, [c[:2] for c in again.calls], [c[:2] for c in orphan.calls]))
    # E91 (Codex on #383 head version 5be30830): nothing is retired on a name, and never before CI started on the carry
    closed = lambda g: ("pulls/9", "PATCH", {"state": "closed"}) in g.calls
    deleted = lambda g: any(c[0] == "git/refs/heads/codex/verdicts/x" and c[1] == "DELETE" for c in g.calls)
    alien = GH("dirty", carry={"parents": [{"sha": "d" * 40}, {"sha": base}], "tree": {"sha": "e" * 40}})
    got_alien = GT.refresh_verdicts(r.root, b, alien, [a, opened_pr])
    hollow = GH("dirty", branches={fresh}, carry={"parents": [{"sha": head}, {"sha": base}], "tree": {"sha": "f" * 40}})
    got_hollow = GT.refresh_verdicts(r.root, b, hollow, [a])
    nodispatch = GH("dirty", dispatch_fails=True)
    first_d = GT.refresh_verdicts(r.root, b, nodispatch, [a])
    rerun = GH("dirty")
    second_d = GT.refresh_verdicts(r.root, b, rerun, [a, opened_pr])
    ran = GH("dirty", runs=[".github/workflows/ci.yml"])
    GT.refresh_verdicts(r.root, b, ran, [a, opened_pr])
    check("E91 a resumed carry is bound to its source before anything is retired: an open pull request or a branch of the "
          "carry's name whose commit is not the head and the base merged (other parents, or another tree than the "
          "stores' union) leaves the old pull request open and its branch kept; and the old one is closed only once CI "
          "has started on the carry, dispatched again when its dispatch failed (Codex on #383)",
          "FAILED" in got_alien[0][1] and not closed(alien) and not deleted(alien) and not any(c[0] == "comment" for c in alien.calls)
          and "FAILED" in got_hollow[0][1] and not closed(hollow) and not deleted(hollow) and not posts(hollow, "pulls")
          and "FAILED" in first_d[0][1] and not closed(nodispatch)
          and ("dispatch", ".github/workflows/ci.yml", fresh) in rerun.calls and closed(rerun) and "FAILED" not in second_d[0][1]
          and not any(c[0] == "dispatch" for c in ran.calls) and closed(ran),
          (got_alien, got_hollow, first_d, second_d, [c[:2] for c in rerun.calls]))
    # E92 (Codex on #383 at f1da8d88): a source that moves after the survey keeps what the carry did not take
    moved = "c" * 40
    before = GH("dirty", heads=[moved])
    got_before = GT.refresh_verdicts(r.root, b, before, [a])
    during = GH("dirty", heads=[head, moved])
    got_during = GT.refresh_verdicts(r.root, b, during, [a])
    after = GH("dirty", tip=moved)
    got_after = GT.refresh_verdicts(r.root, b, after, [a])
    check("E92 the carry is of the head assessed: a source whose head moved since is not carried (nothing made, the next "
          "run reads it), one that moves while it is carried is left open, and its branch is never deleted: GitHub "
          "deletes a ref with no expected head, so a verdict pushed between a read and the delete would go with it "
          "(Codex on #383 at f1da8d88 and on #388 at e42e6695)",
          "not carried" in got_before[0][1] and not posts(before, "git/refs") and not closed(before) and not deleted(before)
          and "FAILED" in got_during[0][1] and not closed(during) and not deleted(during)
          and closed(after) and not deleted(after) and "kept" in got_after[0][1] and "FAILED" not in got_after[0][1],
          (got_before, got_during, got_after))
    # E93: a run GitHub holds for approval at a verdicts-only head is approved by the gate, and no other
    class Held:
        def __init__(self, live=None, state="open"):
            self.calls, self.live, self.state = [], live, state

        def api(self, path, method="GET", body=None, pages=False):
            self.calls.append((path, method))
            if path.startswith("pulls/"):
                return {"state": self.state, "head": {"sha": self.live or head}}
            if path.startswith("actions/runs?"):
                return {"workflow_runs": [
                    {"id": 41, "path": ".github/workflows/ci.yml", "conclusion": "action_required", "head_sha": head},
                    {"id": 42, "path": ".github/workflows/other.yml", "conclusion": "action_required", "head_sha": head},
                    {"id": 43, "path": ".github/workflows/ci.yml", "conclusion": "success", "head_sha": head}]}
            return {}
    approve = lambda g: [c[0] for c in g.calls if c[1] == "POST"]
    approve_held = getattr(GT, "approve_held", lambda *_: [])           # absent before #389's fix: nothing approved
    held = Held()
    got = approve_held(b, held, [a])
    moved_h, closed_h, plain_h, other_h = Held(live="c" * 40), Held(state="closed"), Held(), Held()
    approve_held(b, moved_h, [a])
    approve_held(b, closed_h, [a])
    approve_held(GT.Base(plain.r.root, plain.base), plain_h, [plain.assess()])
    refused = types.SimpleNamespace(pr=a.pr, facts=a.facts, shared=a.shared, reasons=[("OWNER_VETO", "x")])
    approve_held(b, other_h, [refused])
    code_h = Held()                                                     # code changes, accepted, waiting for its checks only
    approve_held(b, code_h, [types.SimpleNamespace(pr=a.pr, facts={}, shared=[], reasons=[("CHECK_MISSING", "x")])])
    check("E93 the gate approves the run GitHub holds for approval (action_required) at the head of a pull request it "
          "assessed as verdicts only, of a required workflow only, and none for a head that moved, a closed pull "
          "request, one that is not verdicts only (code waiting for its checks alone included), or one refused for more than its "
          "checks (#389: held when opened)",
          approve(held) == ["actions/runs/41/approve"] and got and "41" in got[0][1]
          and approve(moved_h) == approve(closed_h) == approve(plain_h) == approve(other_h) == approve(code_h) == [],
          (got, held.calls, moved_h.calls, plain_h.calls, other_h.calls))


def revert_pending_cases():
    """Codex 8caa1ce8 (on the #350 review closure, reproduced at 58e3cc74 and 3a0e18f8): enforce_brakes counted any open
    pull request on a branch gate/revert/<pr>-* as the pending revert, a fork's refused one by anyone included, so a
    stranger's branch gate/revert/7-blocker kept the owner's vetoed #7 from being reverted."""
    r = Repo(git_init=False)
    (r.dot / "merge.json").write_text(json.dumps(PRES))
    (r.root / "AGENTS.md").write_text("rules\n")
    git(r.root, "init", "-q", "-b", "master")
    r.commit("base")
    git(r.root, "checkout", "-q", "-b", "feature")
    (r.root / "AGENTS.md").write_text("rules, weakened\n")
    v = r.entity("alice", "pr-head@1", {"state": "open", "repository": REPO, "pr": 7, "title": "t"})
    r.commit("the change")
    git(r.root, "checkout", "-q", "master")
    until = NOW + 3600
    git(r.root, "merge", "-q", "--no-ff", "feature", "-m", f"Merge pull request #7\n\nwarrant-gate brake until {until}: #7 head version {v}")
    base = git(r.root, "rev-parse", "HEAD")
    b = GT.Base(r.root, base)

    class GH:
        def __init__(self):
            self.calls = []

        def pull(self, n):
            return {"labels": ["hold"]}

        def dispatch(self, w, br):
            self.calls.append(("dispatch", w, br))

        def api(self, path, method="GET", body=None, pages=False):
            self.calls.append((path, method))
            return {"sha": "d" * 40}

    def pending(branch, author, repo, facts=None):
        x = GT.Assessment({"number": 9, "branch": branch, "author": author, "head_repo": repo}, base)
        x.facts.update(facts or {})
        return x
    blocker = pending("gate/revert/7-blocker", "mallory", "mallory/warrant")
    gh = GH()
    out = GT.enforce_brakes(r.root, b, gh, [blocker], now=NOW)
    real = pending(f"gate/revert/7-{base[:12]}", "github-actions[bot]", REPO, {"revert": base})
    quiet = GH()
    held = GT.enforce_brakes(r.root, b, quiet, [real], now=NOW)
    check("E83 a revert counts as pending only when the gate assessed an open pull request as the exact revert of that "
          "merge: a fork's branch named gate/revert/7-blocker does not hold back the revert of the vetoed #7, the gate's own "
          "pending revert does (Codex 8caa1ce8)",
          [n for n, _ in out] == [7] and out[0][1].startswith("revert of #7 opened") and held == [] and not quiet.calls,
          (out, held, quiet.calls))

AFTER_ = dict(MERGE, after_merge=[{"workflow": ".github/workflows/pages.yml", "paths": ["site/"]},
                                  {"workflow": ".github/workflows/claims-replay.yml"}])


def after_merge_cases():
    """The analysis session, 2026-11-13: a merge by the gate starts no push workflow, and GitHub ran 5 of 52 scheduled
    runs of the gate in 26 hours, so the site and the claims checker never ran after the gate's merges. The gate starts
    them itself after its merge, as it starts the required workflows."""
    class GH:
        def __init__(self, a, p):
            self.a, self.p, self.dispatched = a, p, []

        def pull(self, n):
            return dict(self.a.pr)

        def tip(self, br):
            return self.p.base

        def merge(self, n, sha, title, msg):
            return {"merged": True, "sha": "c" * 40}

        def parents(self, sha):
            return [self.p.base, self.a.pr["head"]]

        def dispatch(self, w, br):
            self.dispatched.append(w)

    def merged(before_x=None, verdicts=False):
        p = PR(merge=AFTER_, before_x=before_x)
        a = p.assess()
        if verdicts:
            a.facts["verdicts"] = ["x"]
        gh = GH(a, p)
        GT.merge_one(GT.Base(p.r.root, p.base), a, gh)
        return sorted(gh.dispatched)

    def site(s):
        (s.r.root / "site").mkdir()
        (s.r.root / "site" / "page.html").write_text("<p>new</p>\n")
    plain, with_site, verdicts = merged(), merged(site), merged(verdicts=True)
    ci, pages, replay = ".github/workflows/ci.yml", ".github/workflows/pages.yml", ".github/workflows/claims-replay.yml"
    check("E85 after its merge the gate starts the after_merge workflows on the base: one with paths only when the merge "
          "changed one of them (pages after site/), one without after every merge, none after a merge of verdicts only "
          "(the checker's own acceptances must not start it again)",
          plain == [ci, replay] and with_site == [ci, replay, pages] and verdicts == [ci], (plain, with_site, verdicts))
    bad = [dict(MERGE, after_merge=[{"workflow": "pages.yml"}]),
           dict(MERGE, after_merge=[{"workflow": ".github/workflows/pages.yml", "paths": []}]),
           dict(MERGE, after_merge=[{"workflow": ".github/workflows/a.yml"}, {"workflow": ".github/workflows/a.yml"}]),
           dict(MERGE, after_merge=[{"workflow": ".github/workflows/a.yml", "when": "always"}])]
    refused = [codes(PR(merge=m).assess()) for m in bad]
    check("E86 an after_merge list naming no workflow file, empty paths, a workflow twice or an unknown member refuses the "
          "base's configuration", all(x == {"BASE_CONFIG"} for x in refused), refused)

def prerelease_cases():
    """The owner, 2026-11-13 (relayed): «в нас нема клієнтів — ми обслуговуємо своє майбутнє»: a pre-release (PEP 440
    a, b, rc, .dev, by the form of the version the package declares) is released with brakes open; a stable release
    waits for every brake, as before. A revert of a merge a published version holds says which."""
    r = Repo(git_init=True)
    tree = git(r.root, "rev-parse", "HEAD^{tree}")
    base0 = git(r.root, "rev-parse", "HEAD")
    other = git(r.root, "commit-tree", tree, "-p", base0, "-m", "feature")
    merge = git(r.root, "commit-tree", tree, "-p", base0, "-p", other, "-m",
                f"Merge #7\n\nwarrant-gate brake until {int(time.time()) + 86400}: #7 head version {'a' * 64}")

    def rc(version):
        args = ["--root", str(r.root), "brakes", "--at", merge] + (["--version", version] if version is not None else [])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                return GT.main(args)
            except SystemExit as e:          # an unknown option: argparse's own exit, a FAIL of the case, not its end
                return f"exit {e.code}"
    got = {v: rc(v) for v in ("3.0.0a7", "3.0.0b1", "3.0.0rc2", "3.0.0.dev3", "3.0.0a7.dev1", "3.0.0", "3.0.0.post1",
                              "3.0.0a7\n", "3.0.0a", "3.0.0-alpha", "a7")}
    check("E87 with brakes open, a pre-release by the form of its version (3.0.0a7, b1, rc2, .dev3) is admitted and a "
          "stable one (3.0.0, 3.0.0.post1) refused; the form is the whole string, so 3.0.0a7 with a newline, 3.0.0a, "
          "3.0.0-alpha or a7 are no pre-release; with no version the brakes refuse as before",
          got == {"3.0.0a7": 0, "3.0.0b1": 0, "3.0.0rc2": 0, "3.0.0.dev3": 0, "3.0.0a7.dev1": 0, "3.0.0": 1, "3.0.0.post1": 1,
                  "3.0.0a7\n": 1, "3.0.0a": 1, "3.0.0-alpha": 1, "a7": 1} and rc(None) == 1, got)
    git(r.root, "update-ref", "refs/heads/master", merge)
    later = git(r.root, "commit-tree", tree, "-p", merge, "-m", "a later commit, tagged")
    b = GT.Base.__new__(GT.Base)
    b.root, b.commit = r.root, later

    class GH:
        def api(self, path, method="GET", body=None, pages=False):
            return [[{"name": "v3.0.0a7", "commit": {"sha": later}}, {"name": "v3.0.0a6", "commit": {"sha": base0}}]]
    held = GT.published_with(r.root, GH(), merge)

    class Far:
        def api(self, path, method="GET", body=None, pages=False):
            return [[{"name": "v3.0.0a7", "commit": {"sha": "f" * 40}}, {"name": "v3.0.0a6", "commit": {"sha": base0}}]]
    far = GT.published_with(r.root, Far(), merge)
    check("E88 a revert of a merge names the published versions whose tagged commit holds it (here v3.0.0a7, not v3.0.0a6, "
          "tagged before it), and a tag whose commit this clone does not hold is unknown, never 'not published' (Codex "
          "on #376: merge-base exits 128 there, and False was read as no)",
          held == (["v3.0.0a7"], []) and far == ([], ["v3.0.0a7"]), (held, far))

if __name__ == "__main__":
    closure_cases()
    shadow_cases()
    unreadable_cases()
    interpreter_cases()
    eligible_cases()
    store_cases()
    schema_cases()
    tail_cases()
    catch_up_cases()
    lineage_cases()
    verdict_cases()
    check_cases()
    merge_cases()
    watched_cases()
    constitution_cases()
    brake_cases()
    solo_record_cases()
    presence_cases()
    notice_owner_cases()
    codex_356_cases()
    refresh_cases()
    after_merge_cases()
    prerelease_cases()
    revert_pending_cases()
    sys.exit(finish())
