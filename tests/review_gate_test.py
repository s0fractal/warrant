#!/usr/bin/env python3
"""Merge eligibility and due-for-review (tools/claimslib/eligibility.py) and the gate's GitHub side
(tools/claimslib/gate.py), G1-G33. Each refusal case asserts the exact set of refusal codes, so a
mutant that removes one rule is seen by its code disappearing (a later rule catching the same case
does not hide it). Three fixture worlds are built once; each case works on its own branch from a
world's commit.

    python3 tests/review_gate_test.py
"""
import json
import os
import subprocess

from review_world import FIXED, Fixture, R
from world import check, finish

from claimslib import eligibility as EL      # noqa: E402  (review_world put tools/ on the path)
from claimslib import gate as GT             # noqa: E402

MERGE = {"gate": EL.GATE, "base": "master", "hold_label": "hold", "owner_paths": [".github/", ".warrant/roles.json"],
         "required": [{"check": "test", "workflow": ".github/workflows/ci.yml"},
                      {"check": "cross-repo", "workflow": ".github/workflows/x1-cross-repo.yml"}]}


def checks(head, test="success", status="completed", extra=()):
    """GitHub's check runs and workflow runs at `head`: both required checks, from their workflows."""
    runs = [{"id": 10, "name": "test", "head_sha": head, "status": status, "conclusion": test,
             "app": {"slug": "github-actions"}, "check_suite": {"id": 1}},
            {"id": 11, "name": "cross-repo", "head_sha": head, "status": "completed", "conclusion": "success",
             "app": {"slug": "github-actions"}, "check_suite": {"id": 2}}]
    wf = [{"id": 100, "check_suite_id": 1, "path": ".github/workflows/ci.yml", "head_sha": head},
          {"id": 101, "check_suite_id": 2, "path": ".github/workflows/x1-cross-repo.yml", "head_sha": head}]
    for r, w in extra:
        runs.append(dict(r, head_sha=head))
        wf.append(dict(w, head_sha=head))
    return {"check_runs": runs, "workflow_runs": wf}


def pr(head, labels=(), state="open", draft=False, base="master"):
    return {"number": 1, "state": state, "draft": draft, "base": base, "head": head, "labels": sorted(labels)}


def world(accept_by=("codex",)):
    """A base commit with .warrant/merge.json and a pull request #1 branched from it, whose head 1 (at
    f.x) is filed and committed (f.pre). The base also holds a duty by `stranger` (bound in trust.json,
    pinned by no role): a record the gate reads as not authentic, which G13 rewrites."""
    f = Fixture()
    f.config(accept_by=list(accept_by))
    f.stranger = f.put("stranger", "duty", R.duty("stranger", "a stranger's own line", ["s0fractal"], {"attest": {}},
                                                  accept_by=["s0fractal"]))
    (f.dir / ".warrant" / "merge.json").write_text(json.dumps(MERGE) + "\n")
    f.base_commit = f.commit("the gate's configuration")
    f.git("checkout", "-q", "-b", "pr1")
    f.x = f.commit("the change", {"calc.py": FIXED})
    f.ok("open", "--pr", "1", "--title", "Fix add")
    f.ok("head", "--pr", "1", "--commit", f.x)
    f.pre = f.save()
    return f


def at(f, commit, name):
    """Work on a new branch `name` from `commit` (the store in the working tree follows it)."""
    f.git("checkout", "-q", "-B", name, commit)
    return f


def codes(f, head, labels=(), hold=False, ch=None, base=None):
    a = EL.assess(f.dir, base or f.base_commit, pr(head, labels), ch if ch is not None else checks(head), hold=hold)
    return a, set(a.codes())


def closure(f):
    return f.model().reviews[1].latest()


def accept_by_hand(f, actor, key=None):
    h = closure(f)
    f.put(actor, "accept", R.accept(h.tid, 0, h.item["evidence"]), key=key)
    return f.save()


# ---------------------------------------------------------------- due, the positive control, acceptances

def pending_cases(f):
    head = f.pre
    a, got = codes(f, head)
    check("G1", got == {"NO_ACCEPT"} and a.due and a.not_due == [],
          "a head filed at X, CI green at the records commit, no verdict: due for review, not merge-eligible", (got, a.not_due))
    a2, pend = codes(f, head, ch=checks(head, status="in_progress", test=None))
    check("G2", pend == {"NO_ACCEPT", "CHECK_PENDING"} and not a2.due,
          "a required check still running: not due and not eligible", pend)

    at(f, f.pre, "g3").ok("accept", "--pr", "1", "--commit", f.x, actor="codex")
    tip = f.save()
    a, got = codes(f, tip)
    h = closure(f)
    check("G3", got == set() and a.eligible and not a.due and a.accept[0] == "codex" and a.accept[2] == h.tid
          and a.accept[3] == f.x and a.accept[1] in f.model().recs,
          "an acceptance by codex of the latest head's closure at X, records-only tail, CI green: eligible, no longer due",
          (got, a.accept))

    at(f, f.pre, "g7").ok("accept", "--pr", "1", "--commit", f.x, actor="codex")
    aid = next(i for i, r in f.model().recs.items() if r["type"] == "accept")
    p = f.dir / ".warrant" / "store" / "records" / f"{aid}.json"
    env = json.loads(p.read_text())
    sig = env["sig"]["ed25519"]
    env["sig"]["ed25519"] = ("0" if sig[0] != "0" else "1") + sig[1:]
    p.write_text(json.dumps(env, separators=(",", ":"), sort_keys=True))
    tip = f.save()
    _, got = codes(f, tip)
    check("G7", got == {"NO_ACCEPT", "TAIL_RECORD_UNREVIEWED"}, "a forged signature on codex's acceptance: no acceptance, and an "
          "unauthentic record in the tail", got)

    _, got = codes(f, accept_by_hand(at(f, f.pre, "g10"), "stranger"))
    check("G10", got == {"NO_ACCEPT", "TAIL_RECORD_UNREVIEWED"}, "an acceptance by an actor the base's roles.json does not pin is not "
          "authentic", got)
    _, got = codes(f, accept_by_hand(at(f, f.pre, "g25"), f.replayer))
    check("G25", got == {"ACCEPT_NOT_ACCEPTOR", "TAIL_RECORD_UNREVIEWED"}, "an acceptance by a pinned actor outside the base's accept_by",
          got)


def author_cases(f):
    _, got = codes(f, accept_by_hand(f, "claude"))
    check("G4", got == {"ACCEPT_BY_AUTHOR"}, "an acceptance by the pull request's author (in accept_by) does not count", got)


# ---------------------------------------------------------------- the accepted world

def accepted_cases(f):
    at(f, f.tip, "g5").ok("head", "--pr", "1", "--commit", f.commit("a second change", {"calc.py": FIXED + "# 2\n"}))
    _, got = codes(f, f.save())
    check("G5", got == {"NO_ACCEPT"}, "an acceptance of an older head does not carry to the latest head", got)

    roles = json.loads((f.dir / ".warrant" / "roles.json").read_text())
    roles["actors"]["codex"] = f.keys["stranger"].public
    at(f, f.tip, "g6").ok("head", "--pr", "1", "--commit", f.commit("re-pin codex", {".warrant/roles.json": json.dumps(roles)}))
    _, got = codes(f, accept_by_hand(f, "codex", key=f.keys["stranger"]))
    check("G6", got == {"NO_ACCEPT", "OWNER_PATHS", "TAIL_RECORD_UNREVIEWED"}, "pins taken from the pull request's head: an acceptance signed by "
          "the key the head pins for codex is not codex's under the base's pins (and re-pinning is the owner's to merge)", got)

    at(f, f.tip, "g8").ok("finding", "--pr", "1", "--commit", f.x, "--severity", "P2", "--what", "add is still wrong",
                          actor="codex")
    tip = f.save()
    a, got = codes(f, tip)
    check("G8", "OPEN_FINDING" in got, "a finding against the accepted head stands: not eligible", got)
    check("G9", got == {"OPEN_FINDING"} and not a.due, "the open finding is the one refusal, and a head with a verdict "
          "is not due", got)

    statement = at(f, f.tip, "g26").model().reviews[1].rec["body"]["statement"]
    f.put("claude", "duty", R.duty("claude", statement, ["s0fractal"], {"attest": {}}, accept_by=["codex"]))
    _, got = codes(f, f.save())
    check("G26", got == {"REVIEW_RECORDS", "TAIL_RECORD_UNREVIEWED"}, "a problem in the head's review records (a second review duty of #1)", got)

    gots = [EL.assess(f.dir, f.base_commit, pr(f.tip, **kw), checks(f.tip)).codes()
            for kw in ({"state": "closed"}, {"draft": True}, {"base": "release"})]
    check("G27", gots == [["PR_NOT_OPEN"], ["PR_DRAFT"], ["PR_BASE"]],
          "a closed pull request, a draft, and one into another branch", gots)

    for path in (".github/workflows/fake.yml", ".warrant/roles.json"):
        target = at(f, f.tip, f"g29-{len(path)}").dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((target.read_text() if target.is_file() else "") + "\n")
        f.ok("head", "--pr", "1", "--commit", f.commit("a change the owner merges"))
        _, got = codes(f, accept_by_hand(f, "codex"))
        check("G29" if path.startswith(".github") else "G30", got == {"OWNER_PATHS"},
              f"a pull request changing {path} (an owner path of the base's merge.json) is not merged by the gate", got)

    at(f, f.tip, "g31").put("claude", "duty", R.duty("claude", "an unrelated obligation, filed after review",
                                                     ["s0fractal"], {"attest": {}}, accept_by=["codex"]))
    _, got = codes(f, f.save())
    check("G31", got == {"TAIL_RECORD_UNREVIEWED"}, "a record by the author after the accepted head that is not this pull request's "
          "review record (an unrelated duty) was never reviewed", got)
    at(f, f.tip, "g32").put("stranger", "duty", R.duty("stranger", "a stranger's second line", ["s0fractal"],
                                                       {"attest": {}}, accept_by=["s0fractal"]))
    _, got = codes(f, f.save())
    check("G32", got == {"TAIL_RECORD_UNREVIEWED"}, "a record the base's pins do not authenticate, added after the accepted head", got)

    (at(f, f.tip, "g28").dir / ".warrant" / "store" / "blobs" / ("b" * 64)).write_text("{}")
    _, got = codes(f, f.commit("a blob not named by its hash"))
    check("G28", got == {"STORE_ENTRY"}, "a blob whose name is not its hash is refused, not read under that name", got)


def tail_cases(f):
    _, got = codes(f, at(f, f.tip, "g11").commit("after acceptance", {"calc.py": FIXED + "# unreviewed\n"}))
    check("G11", got == {"TAIL_CHANGES"}, "a code change after the accepted head", got)

    os.symlink("../../../calc.py", at(f, f.tip, "g12").dir / ".warrant" / "store" / "records" / ("a" * 64 + ".json"))
    _, got = codes(f, f.commit("a symlink in the store"))
    check("G12", got == {"TAIL_CHANGES", "STORE_ENTRY"}, "a symlink added under .warrant/store/records", got)

    rec = at(f, f.tip, "g13").dir / ".warrant" / "store" / "records" / f"{f.stranger}.json"
    rec.write_bytes(rec.read_bytes() + b"\n")
    _, got = codes(f, f.commit("a record rewritten"))
    check("G13", got == {"TAIL_CHANGES"}, "an existing record file changed after the accepted head", got)

    _, got = codes(f, at(f, f.tip, "g14").commit("not a view", {"README.md": "unreviewed\n"}))
    check("G14", got == {"TAIL_CHANGES"}, "a file that is not a generated view, added after the accepted head", got)

    view = at(f, f.tip, "g15").dir / "REVIEWS.md"
    view.write_text(view.read_text() + "\n")
    _, got = codes(f, f.commit("a view changed"))
    check("G15", got == set(), "a changed view passes the gate's path rule (its bytes are the required check's to refuse)", got)

    at(f, f.base_commit, "g16").git("checkout", "-q", f.tip, "--", ".warrant/store", "REVIEWS.md")
    _, got = codes(f, f.commit("the records without the reviewed commit"))
    check("G16", got == {"HEAD_NOT_ANCESTOR"}, "the head's history does not contain the accepted commit X", got)


def check_and_hold_cases(f):
    tip = f.tip
    _, got = codes(f, tip, ch=checks(tip, test="failure"))
    check("G17", got == {"CHECK_RED"}, "a red required check at the head", got)
    shadow = ({"id": 12, "name": "test", "status": "completed", "conclusion": "success",
               "app": {"slug": "github-actions"}, "check_suite": {"id": 3}},
              {"id": 102, "check_suite_id": 3, "path": ".github/workflows/fake.yml"})
    _, got = codes(f, tip, ch=checks(tip, test="failure", extra=[shadow]))
    check("G18", got == {"CHECK_RED", "CHECK_AMBIGUOUS"}, "a check of the required name from another workflow", got)
    ch = checks(tip)
    ch["check_runs"][0]["app"] = {"slug": "someone-elses-app"}
    _, got = codes(f, tip, ch=ch)
    check("G19", got == {"CHECK_MISSING"}, "a required check posted by another app is no check", got)
    _, got = codes(f, tip, labels=["hold"])
    check("G20", got == {"PR_HOLD"}, "the hold label", got)
    _, got = codes(f, tip, hold=True)
    check("G21", got == {"GATE_HOLD"}, "the global hold (WARRANT_MERGE_GATE=hold)", got)
    roles = at(f, f.base_commit, "g22").dir / ".warrant" / "roles.json"
    doc = json.loads(roles.read_text())
    doc["actors"]["codex"] = f.keys["stranger"].public
    _, got = codes(f, tip, base=f.commit("the base re-pins codex", {".warrant/roles.json": json.dumps(doc)}))
    check("G22", got == {"NO_ACCEPT", "TAIL_RECORD_UNREVIEWED"}, "the pins are the base's: re-pinned at the base, the same acceptance does not count", got)


# ---------------------------------------------------------------- the merge call

class FakeGh:
    """`gh api` for GitHub.run: records each call; the pull request's head is `head`, or another when `moved`."""

    def __init__(self, head, base, moved=False, now=None):
        self.calls, self.head, self.base, self.moved, self.now = [], head, base, moved, now or {}

    def __call__(self, cmd, input=None, capture_output=True, check=False):
        path = next(x for x in cmd if x.startswith("repos/"))
        method = cmd[cmd.index("--method") + 1]
        self.calls.append((method, path, json.loads(input) if input else None))
        if path.endswith("/pulls/1") and method == "GET":
            out = {"number": 1, "state": "open", "draft": False, "base": {"ref": "master"},
                   "head": {"sha": "f" * 40 if self.moved else self.head}, "labels": [], **self.now}
        elif "/branches/" in path:
            out = {"commit": {"sha": self.base}}
        elif path.endswith("/merge"):
            out = {"merged": True, "sha": "e" * 40}
        elif "/commits/" in path:
            out = {"parents": [{"sha": self.base}, {"sha": self.head}]}
        else:
            out = {}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out).encode(), b"")


def merge_cases(f):
    b = EL.Base(f.dir, f.base_commit)
    a = EL.assess(f.dir, b, pr(f.tip), checks(f.tip))
    fake = FakeGh(f.tip, f.base_commit)
    m = GT.merge_one(b, a, GT.GitHub("s0fractal/warrant", run=fake))
    put = [c for c in fake.calls if c[0] == "PUT"]
    check("G23", m["merged"] and m["as_assessed"] and len(put) == 1 and put[0][2].get("sha") == f.tip
          and put[0][2]["merge_method"] == "merge"
          and sorted(p for meth, p, _ in fake.calls if meth == "POST") == [
              "repos/s0fractal/warrant/actions/workflows/ci.yml/dispatches",
              "repos/s0fractal/warrant/actions/workflows/x1-cross-repo.yml/dispatches"],
          "the merge names the head assessed, as a merge commit, then dispatches the required workflows on master",
          fake.calls)
    moved = FakeGh(f.tip, f.base_commit, moved=True)
    m2 = GT.merge_one(b, a, GT.GitHub("s0fractal/warrant", run=moved))
    check("G24", not m2["merged"] and not [c for c in moved.calls if c[0] == "PUT"],
          "a head that moved since the assessment is not merged", (m2, moved.calls))
    late = {}
    for name, now in (("base", {"base": {"ref": "release"}}), ("hold", {"labels": [{"name": "hold"}]}),
                      ("draft", {"draft": True}), ("closed", {"state": "closed"})):
        fake = FakeGh(f.tip, f.base_commit, now=now)
        m3 = GT.merge_one(b, a, GT.GitHub("s0fractal/warrant", run=fake))
        late[name] = (m3["merged"], len([c for c in fake.calls if c[0] == "PUT"]))
    check("G33", late == {k: (False, 0) for k in ("base", "hold", "draft", "closed")},
          "a pull request retargeted, held, drafted or closed after the assessment, at the same head, is not merged "
          "(Codex finding 190c1c64418f on 17ea066)", late)


if __name__ == "__main__":
    w = world()
    pending_cases(w)
    w.close()
    w = world(accept_by=("claude", "codex"))
    author_cases(w)
    w.close()
    w = world()
    w.ok("accept", "--pr", "1", "--commit", w.x, actor="codex")
    w.tip = w.save()
    for cases in (accepted_cases, tail_cases, check_and_hold_cases, merge_cases):
        cases(w)
    w.close()
    raise SystemExit(finish("review_gate_test"))
