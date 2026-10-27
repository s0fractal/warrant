#!/usr/bin/env python3
"""The merge gate's predicate (tools/gate.py) on fixture Git repositories: one case per refusal, each asserting
the exact set of refusal codes (a mutant that removes one rule is seen even where another rule also refuses).

    python3 tests/gate_test.py
"""
import json
import sys

from world import KEYS, Repo, check, finish, git

import gate as GT
from warrant import records as R

REPO = "s0fractal/warrant"
MERGE = {"gate": GT.GATE, "base": "master", "required": [{"check": "test", "workflow": ".github/workflows/ci.yml"}],
         "hold_label": "hold", "owner_paths": [".github/", ".warrant/merge.json", ".warrant/v3.json", "AGENTS.md", "tools/gate.py"]}


def green(head, other=False):
    runs = [{"name": "test", "head_sha": head, "app": {"slug": "github-actions"}, "check_suite": {"id": 1},
             "status": "completed", "conclusion": "success", "id": 1}]
    wf = [{"head_sha": head, "check_suite_id": 1, "path": ".github/workflows/ci.yml"}]
    if other:
        runs.append(dict(runs[0], check_suite={"id": 2}, id=2))
        wf.append({"head_sha": head, "check_suite_id": 2, "path": ".github/workflows/other.yml"})
    return {"check_runs": runs, "workflow_runs": wf}


class PR:
    """A repository with a base commit on master and a pull request #7 from branch `feature` whose author (alice)
    filed its pr-head@1 root and a head version at commit X, and (accept=True) bob's acceptance after X."""

    def __init__(self, accept=True, before_x=None):
        self.r = Repo(git_init=False)
        (self.r.dot / "merge.json").write_text(json.dumps(MERGE))
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

    def assess(self, labels=(), checks=None, head=None, **pr):
        head = head or self.r.commit("tail") if pr.pop("recommit", False) else head or git(self.r.root, "rev-parse", "HEAD")
        facts = dict({"number": 7, "state": "open", "draft": False, "base": "master", "head": head, "labels": list(labels),
                      "branch": "feature", "head_repo": REPO}, **pr)
        return GT.assess(self.r.root, self.base, facts, checks or green(head))


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


if __name__ == "__main__":
    eligible_cases()
    store_cases()
    tail_cases()
    lineage_cases()
    verdict_cases()
    check_cases()
    merge_cases()
    sys.exit(finish())
