#!/usr/bin/env python3
"""The merge gate's predicate (warrant/gate.py) on fixture Git repositories: one case per refusal, each asserting
the exact set of refusal codes (a mutant that removes one rule is seen even where another rule also refuses).

    python3 tests/gate_test.py
"""
import importlib
import importlib.machinery
import importlib.util
import json
import time
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from world import KEYS, Repo, check, finish, git

from warrant import gate as GT
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

    def assess(self, labels=(), checks=None, head=None, now=None, **pr):
        head = head or self.r.commit("tail") if pr.pop("recommit", False) else head or git(self.r.root, "rev-parse", "HEAD")
        facts = dict({"number": 7, "state": "open", "draft": False, "base": "master", "head": head, "labels": list(labels),
                      "branch": "feature", "head_repo": REPO}, **pr)
        return GT.assess(self.r.root, self.base, facts, checks or green(head), now=now)


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
    sys.exit(finish())
