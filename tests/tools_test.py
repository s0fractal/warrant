#!/usr/bin/env python3
"""The repository's tools on fixture repositories: claims (tools/claims.py), the review loop's commands and
replay checker (tools/review.py), the roadmap (tools/roadmap.py) and the checker identity (tools/repo.py).

    python3 tests/tools_test.py
"""
import subprocess
import sys

from world import KEYS, ROOT, Repo, check, finish, git

import claims as CL
import repo as RP
import review as RV
import roadmap as RM
from warrant import records as R

SPEC = "## 3. Lineage\n\nA record whose `lineage` is L **succeeds** L.\n\nFORK is a core verdict.\n"
TEST = '''from world import check, finish
check("Q1 a case", True)
check("Q2 another", True)
finish()
'''
HARNESS = '''import json, sys
print(json.dumps({"Z1": ["warrant/engine.py", "tests/q_test.py", ["Q1"]], "Z2": ["warrant/engine.py", "tests/q_test.py", ["Q2"]]}))
'''


def claims_repo():
    r = Repo()
    (r.root / "docs").mkdir()
    (r.root / "docs" / "V3.md").write_text(SPEC)
    (r.root / "tests").mkdir()
    (r.root / "tests" / "q_test.py").write_text(TEST)
    (r.root / "tests" / "mutants.py").write_text(HARNESS)
    return r


def claim(r, actor="alice", **kw):
    body = dict({"state": "backed", "id": "V3-3-1", "source": CL.SOURCE, "section": "3",
                 "text": "A record whose `lineage` is L **succeeds** L.", "witnesses": ["q_test:Q1"], "mutants": ["Z1"]}, **kw)
    return r.put(actor, "entity", body, "claim@1", guard=CL.schema_guard(RP.Repo(r.root).report(), body["state"]))


def codes(r):
    return sorted({c for c, _ in CL.check(RP.Repo(r.root))[1]})


def claims_cases():
    r = claims_repo()
    claim(r)
    check("C01 a claim quoting the spec, witnessed by a printed case and a mutant on it: no problem", codes(r) == [], codes(r))
    r = claims_repo()
    claim(r, text="A sentence the spec does not hold.")
    check("C02 a live claim whose sentence is not in the spec is refused", codes(r) == ["CLAIM_TEXT_MISSING"], codes(r))
    r = claims_repo()
    claim(r, witnesses=["q_test:Q9"], mutants=[])
    check("C03 a witness no test prints is refused", "WITNESS_MISSING" in codes(r), codes(r))
    r = claims_repo()
    claim(r, mutants=["Z1", "Z9"])
    check("C04 a mutant not in the harness is refused", codes(r) == ["UNKNOWN_MUTANT"], codes(r))
    r = claims_repo()
    v2 = claim(r, source=CL.V2_SOURCE, id="SPEC-1-1")
    before = codes(r)
    seed = r.seed("alice")
    CL.retire_v2(RP.Repo(r.root), "alice", RP.load_key(str(seed)))
    rep = RP.Repo(r.root).report()
    check("C05 a live Warrant 2 claim is refused until retired; retired, it stays in the store as history",
          before == ["V2_CLAIM_LIVE"] and codes(r) == [] and rep["lineages"][v2]["state"] == "retired"
          and len(rep["lineages"][v2]["versions"]) == 2, (before, codes(r)))
    r = claims_repo()
    claim(r, mutants=["Z2"])
    check("C06 a mutant whose cases are not among the claim's witnesses is refused", codes(r) == ["MUTANT_OFF_CLAIM"], codes(r))
    r = claims_repo()
    claim(r, mutants=[])
    check("C07 a backed claim with no mutant is unburned", codes(r) == ["UNBURNED"], codes(r))
    try:                         # a checker that does not refuse goes on to run every witness: a hang is a failure here
        out = subprocess.run([sys.executable, "-B", str(ROOT / "tools" / "claims.py"), "replay", "--key", "-"],
                             input=KEYS["eve"].seed_hex() + "\n", capture_output=True, text=True, cwd=ROOT, timeout=60)
        refused, why = out.returncode == 2 and out.stderr.startswith("REFUSED SIGNER"), out.stderr[-300:]
    except subprocess.TimeoutExpired:
        refused, why = False, "it ran on for a minute instead of refusing"
    check("C08 the claims checker signs only with a key the trust binds to its own identity", refused, why)
    r = claims_repo()
    doc = [{"id": "V3-3-1", "section": "3", "text": "A record whose `lineage` is L **succeeds** L.", "witnesses": ["q_test:Q1"],
            "mutants": ["Z1"]}]
    k = RP.load_key(str(r.seed("alice")))
    first = CL.file_claims(RP.Repo(r.root), "alice", k, doc)
    again = CL.file_claims(RP.Repo(r.root), "alice", k, doc)
    doc[0]["text"] = "FORK is a core verdict."
    third = CL.file_claims(RP.Repo(r.root), "alice", k, doc)
    rep = RP.Repo(r.root).report()
    check("C09 filing claims is idempotent; a changed sentence is a new version of the same lineage",
          len(first) == 1 and again == [] and len(third) == 1 and len(rep["lineages"][first[0]]["versions"]) == 2)


def review_repo():
    r = Repo()
    (r.root / "tests").mkdir()
    (r.root / "tests" / "world.py").write_text((ROOT / "tests" / "world.py").read_text())
    (r.root / "code.py").write_text("X = 1\n")
    git(r.root, "init", "-q", "-b", "master")
    r.commit("base")
    return r


PATCH = '''diff --git a/tests/bug_test.py b/tests/bug_test.py
new file mode 100644
--- /dev/null
+++ b/tests/bug_test.py
@@ -0,0 +1,6 @@
+import sys
+sys.path.insert(0, ".")
+import code
+print(("ok   " if code.X == 1 else "FAIL ") + "F1 X is one")
+print("FAIL F2 always")
+print("ok   F3 always")
'''


def review_cases():
    r = review_repo()
    rp = RP.Repo(r.root)
    k = RP.load_key(str(r.seed("alice")))
    [root] = rp.file("alice", k, [R.record("entity", "alice", 0, {"state": "open", "repository": "s0fractal/warrant", "pr": 3,
                                                                    "title": "t", "serves": []}, "pr-head@1")])
    x1 = git(r.root, "rev-parse", "HEAD")
    sys.argv = ["review.py"]
    RV.run(["--root", str(r.root), "head", "--pr", "3", "--actor", "alice", "--key", str(r.seed("alice"))])
    rep = rp.report()
    h1 = rep["lineages"][root]["leaf"]
    hb = rep["_recs"][h1]["body"]
    check("R01 `head` files a head version naming the commit, its tree and the schema's guard",
          hb["state"] == "head" and hb["commit"] == x1 and hb["tree"] == git(r.root, "rev-parse", f"{x1}^{{tree}}")
          and rep["_recs"][h1]["guard"]["roles"] == ["pr/acceptor"])
    test = {"file": "bug_test", "case": "F1", "patch": PATCH}
    f = r.put("bob", "challenge", {"target": h1, "statement": "P1 x", "severity": "P1", "what": "w", "where": [],
                                   "commit": x1, "tree": hb["tree"], "test": test}, "finding@1", refs=[h1])
    r.commit("finding")
    (r.root / "code.py").write_text("X = 2\n")
    x2 = r.commit("break it")
    v2 = r.entity("alice", "pr-head@1", {"state": "head", "commit": x2, "tree": git(r.root, "rev-parse", f"{x2}^{{tree}}")}, lineage=h1)
    rep = rp.report()
    todo = [(c, h) for c, h, _ in RV.to_replay(rep, {"carol"})]
    check("R02 a finding's test is due for replay at each head version from its target on", todo == [(f, h1), (f, v2)], todo)
    verdicts = (RV.run_test(r.root, "bug_test", "F1", PATCH), RV.run_test(r.root, "bug_test", "F3", PATCH),
                RV.run_test(r.root, "bug_test", "F9", PATCH))
    check("R03 a test's verdict is its own case's line: FAIL reproduces, ok does not, absent is no result (another case's FAIL is not)",
          verdicts == ("reproduces", "does_not_reproduce", "no_result") and not (r.root / "tests" / "bug_test.py").exists(), verdicts)
    wide = PATCH.replace("+++ b/tests/bug_test.py", "+++ b/code.py")
    check("R04 a finding's test may add one new file under tests/, nothing else",
          RV.finding_test({"test": test}) and RV.finding_test({"test": dict(test, patch=wide)}) is None
          and RV.finding_test({"test": dict(test, patch=PATCH + PATCH.replace("bug_test", "two_test"))}) is None)
    base = r.commit("before the replays")
    r.put("carol", "attest", {"target": f, "verdict": "does_not_reproduce", "on": v2, "commit": x2, "tree": hb["tree"],
                              "test": "bug_test:F1", "window": [1, 2]}, refs=[f, v2])
    r.commit("a false replay")
    try:
        RV.verify(rp, base)
        caught = False
    except RP.Failed as e:
        caught = e.code == "REPLAY_DIFFERS"
    check("R05 CI re-executes every replay new since the base at its commit and refuses a different result", caught)
    try:
        RP.identity(["warrant"])
        refused = False
    except RP.Failed as e:
        refused = e.code == "IDENTITY"
    check("R06 a checker identity is refused when a module loaded from the repository is not hashed", refused)


def roadmap_cases():
    r = Repo()
    g = r.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "goal"})
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "owed", "answers": g, "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "owed", "answers": g, "serves": [], "evidence": []}, lineage=o)
    rp = RP.Repo(r.root)
    due = RM.due(rp.report(), r.profile, "bob")
    r.attest("bob", d)
    after = RM.due(rp.report(), r.profile, "bob")
    check("P01 a closure waiting for the acceptor is due for it, with its goal; once accepted, no longer",
          [(x["closure"], x["duty"], x["goal"]) for x in due] == [(d, o, "G1")] and after == [], due)
    r.entity("alice", "obligation@1", {"state": "open", "statement": "stray", "answers": o, "serves": []})
    check("P02 an obligation answering no goal is a roadmap problem", len(RM.check(rp.report())) == 1)


if __name__ == "__main__":
    claims_cases()
    review_cases()
    roadmap_cases()
    sys.exit(finish())
