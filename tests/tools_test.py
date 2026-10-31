#!/usr/bin/env python3
"""The review loop's commands on fixture repositories: claims (warrant/claims.py), the review loop's commands and
replay checker (warrant/review.py), the roadmap (warrant/roadmap.py) and what a checker's attest names (warrant/repo.py).

    python3 tests/tools_test.py
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from world import KEYS, ROOT, Repo, check, finish, git

from warrant import claims as CL
from warrant import cli as CLI
from warrant import differential as DF
from warrant import engine as E
from warrant import jcs as JCS
from warrant import home as H
from warrant import keys as K
from warrant import records as R
from warrant import repo as RP
from warrant import review as RV
from warrant import roadmap as RM

SPEC = "## 3. Lineage\n\nA record whose `lineage` is L **succeeds** L.\n\nFORK is a core verdict.\n"
TEST = '''def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)


check("Q1 a case", True)
check("Q2 another", True)
'''
# The fixture's harness: Z1 is killed, Z2 survives.
HARNESS = '''import json, sys
M = {"Z1": ["warrant/engine.py", "tests/q_test.py", ["Q1"]], "Z2": ["warrant/engine.py", "tests/q_test.py", ["Q2"]]}
if "--matrix" not in sys.argv:
    print(json.dumps(M))
else:
    ids = sys.argv[1:sys.argv.index("--matrix")]
    rows = [{"id": i, "outcome": "KILLED" if i == "Z1" else "SURVIVED"} for i in ids]
    open(sys.argv[sys.argv.index("--matrix") + 1], "w").write(json.dumps({"rows": rows}))
'''
CHECKER_KEY = KEYS["dave"]               # the fixture's key bound to the claims checker and the replayer
SOURCE, RETIRED = "docs/V3.md", "SPEC.md"
CLAIMS = {"warrant": "claims/1", "source": SOURCE, "retired": [RETIRED], "witnesses": ["tests/*_test.py"],
          "mutants": "tests/mutants.py"}


def claims_config(r):
    (r.root / ".warrant" / "claims.json").write_text(json.dumps(CLAIMS))


def claims_repo():
    r = Repo()
    (r.root / "docs").mkdir()
    (r.root / "docs" / "V3.md").write_text(SPEC)
    (r.root / "tests").mkdir()
    (r.root / "tests" / "q_test.py").write_text(TEST)
    (r.root / "tests" / "mutants.py").write_text(HARNESS)
    claims_config(r)
    return r


def claim(r, actor="alice", **kw):
    body = dict({"state": "backed", "id": "V3-3-1", "source": SOURCE, "section": "3",
                 "text": "A record whose `lineage` is L **succeeds** L.", "witnesses": ["q_test:Q1"], "mutants": ["Z1"]}, **kw)
    return r.put(actor, "entity", body, "claim@1", guard=CL.schema_guard(RP.Repo(r.root).report(), body["state"]))


def checker_repo():
    """A committed claims repository whose `.warrant/v3.json` binds a key to the claims checker, a claim/verifier."""
    r = claims_repo()
    (r.root / ".gitignore").write_text("/build/\n")
    r.trust["keys"][CL.CHECKER] = [CHECKER_KEY.public]
    r.profile["roles"]["claim/verifier"] = sorted(["carol", CL.CHECKER])
    r.write_config()
    git(r.root, "init", "-q", "-b", "master")
    return r


def put_as(r, actor, body, refs):
    """An attest by `actor` signed with CHECKER_KEY (the fixture's KEYS name people only)."""
    r.t += 1
    return r.store.append(R.record("attest", actor, r.t, body, refs=refs), CHECKER_KEY, r.trust)


def refused_code(fn, *a):
    try:
        fn(*a)
        return None
    except RP.Failed as e:
        return f"{e.code} {e}"


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
    v2 = claim(r, source=RETIRED, id="SPEC-1-1")
    before = codes(r)
    seed = r.seed("alice")
    CL.retire_v2(RP.Repo(r.root), "alice", RP.load_key(str(seed), r.root))
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
    r = claims_repo()
    claim(r)
    r.profile["roles"]["schema/author"] = ["alice", "bob"]
    r.profile["quorum"] = {"schema/author": 2}
    for i in r.schemas.values():
        r.attest("bob", i)
    r.write_config()
    r.put("alice", "schema", {"name": "note@1", "fields": {"text": "str"}, "states": None, "closed": [], "successors": {}})
    check("C10 a schema awaiting its second author is a proposal the claims check does not refuse", codes(r) == [], codes(r))
    r = checker_repo()           # a claim that waits: a checker that does not refuse first goes on to run its witnesses
    claim(r)
    r.commit("a claim waiting for the checker")
    ran = []
    real, CL.run_checks = CL.run_checks, lambda *a: ran.append(a) or real(*a)
    try:
        why = refused_code(CL.replay, RP.Repo(r.root), KEYS["eve"])
    finally:
        CL.run_checks = real
    check("C08 the claims checker signs only with a key the trust binds to its own identity, refused before it runs "
          "anything", why is not None and why.startswith("SIGNER the seed's key") and ran == [], (why, len(ran)))
    r = checker_repo()
    (r.root / RP.NAME).mkdir()                     # the tree carries a package source, so its code is read from Git
    (r.root / RP.NAME / "__init__.py").write_text("x = 1\n")
    x = r.commit("a committed tree")
    sub = r.root / "docs"                          # a directory inside the checkout, as the mutant harness's copy under build/
    check("C20 the code a checker's result is checked against is the commit's whole tree, also from a directory inside "
          "the checkout", RP.code_tree(sub, x) == RP.code_tree(r.root, x) != ""
          and RP.checker_code(x, sub) == RP.checker_code(x, r.root), (RP.code_tree(sub, x)[:200],))
    r = claims_repo()
    doc = [{"id": "V3-3-1", "section": "3", "text": "A record whose `lineage` is L **succeeds** L.", "witnesses": ["q_test:Q1"],
            "mutants": ["Z1"]}]
    k = RP.load_key(str(r.seed("alice")), r.root)
    first = CL.file_claims(RP.Repo(r.root), "alice", k, doc)
    again = CL.file_claims(RP.Repo(r.root), "alice", k, doc)
    doc[0]["text"] = "FORK is a core verdict."
    third = CL.file_claims(RP.Repo(r.root), "alice", k, doc)
    rep = RP.Repo(r.root).report()
    check("C09 filing claims is idempotent; a changed sentence is a new version of the same lineage",
          len(first) == 1 and again == [] and len(third) == 1 and len(rep["lineages"][first[0]]["versions"]) == 2)
    config_cases()
    checker_cases()


def config_cases():
    r = claims_repo()
    claim(r)
    (r.root / ".warrant" / "claims.json").write_text(json.dumps(dict(CLAIMS, source="/etc/hosts")))
    why = refused_code(CL.check, RP.Repo(r.root))
    (r.root / ".warrant" / "claims.json").write_text(json.dumps(dict(CLAIMS, witnesses=[])))
    shape = refused_code(CL.check, RP.Repo(r.root))
    (r.root / ".warrant" / "claims.json").unlink()
    gone = refused_code(CL.check, RP.Repo(r.root))
    check("C16 the claims check refuses a repository whose .warrant/claims.json is absent, not a claims/1 document or names a "
          "path outside it", all(x is not None and x.startswith("CONFIG") for x in (why, shape, gone)), (why, shape, gone))
    r = Repo()
    (r.root / "spec").mkdir()
    (r.root / "spec" / "S.md").write_text(SPEC)
    (r.root / "checks").mkdir()
    (r.root / "checks" / "q_test.py").write_text(TEST)
    (r.root / "checks" / "harness.py").write_text(HARNESS.replace("tests/q_test.py", "checks/q_test.py"))
    (r.root / ".warrant" / "claims.json").write_text(json.dumps(dict(CLAIMS, source="spec/S.md", witnesses=["checks/*_test.py"],
                                                                    mutants="checks/harness.py")))
    claim(r, source="spec/S.md", witnesses=["checks/q_test:Q1"])
    here = codes(r)
    claim(r, source=SOURCE, id="V3-3-2")
    there = codes(r)
    check("C17 the specification, the witness files and the mutant harness are the ones the repository's claims.json names",
          here == [] and there == ["CLAIM_SOURCE"], (here, there))
    escapes = {}
    for which in ("source", "mutants", "witnesses"):       # Codex finding 583d6f508840 on #226 (a2f6fab9)
        r = claims_repo()
        claim(r)
        target = {"source": r.root / SOURCE, "mutants": r.root / "tests" / "mutants.py", "witnesses": r.root / "tests" / "q_test.py"}[which]
        outside = r.home / target.name
        target.rename(outside)
        target.symlink_to(outside)
        marker = r.home / "ran"
        with outside.open("a") as f:
            f.write(f"\nopen({str(marker)!r}, 'w').write('x')\n" if which != "source" else "")
        escapes[which] = (refused_code(CL.check, RP.Repo(r.root)) or "")[:6], marker.exists()
    check("C18 a claim's specification, witness file or mutant harness that is a link leading outside the repository is refused "
          "(CONFIG) before it is read or run", all(v == ("CONFIG", False) for v in escapes.values()), escapes)
    r = claims_repo()
    git(r.root, "init", "-q", "-b", "master")
    rel = Path(os.path.relpath(r.root))
    got = CL.run_checks(RP.Repo(rel).root, ["q_test:Q1"], ["Z1"])
    check("C19 a relative --root is the repository it names: its witnesses run and its mutants are counted (Codex finding "
          "89aaf813e35e on #226)", "Q1" in got[0].get("q_test", set()) and got[1].get("Z1", {}).get("outcome") == "KILLED", got)


def checker_cases():
    r = checker_repo()
    rp = RP.Repo(r.root)
    L = claim(r)
    base = r.commit("a claim")
    first = CL.replay(rp, CHECKER_KEY)
    x1 = r.commit("its acceptance")
    rep = rp.report()
    a = rep["_recs"][first[0]]["body"] if first else {}
    again = CL.replay(rp, CHECKER_KEY)
    check("C11 the claims checker's acceptance names the commit, its tree, the checker's code there and its environment",
          len(first) == 1 and rep["versions"][L]["guard"] == "MET" and a["commit"] == base
          and a["tree"] == git(r.root, "rev-parse", f"{base}^{{tree}}") and a.get("code") == RP.checker_code(base, r.root)
          and set(a.get("env", {})) == {"python", "cryptography"} and again == [], (first, a, again))
    ok = CL.verify(rp, base)
    put_as(r, CL.CHECKER, dict(a, code="0" * 64), [L])
    r.commit("an acceptance naming other code")
    why = refused_code(CL.verify, rp, x1)
    check("C12 CI re-executes the checker's acceptances new since the base and refuses one whose code is not the checker's "
          "at its commit", ok == 1 and why is not None and "CODE_DIFFERS" in why, (ok, why))
    view = CL.view(rp.report(), r.root)
    (r.root / "tests" / "q_test.py").write_text(TEST + "# changed\n")
    r.commit("the code changes")
    stale = CL.view(rp.report(), r.root)
    third = CL.replay(rp, CHECKER_KEY)
    check("C13 an acceptance holds for its commit: the view says whether it is at this tree, and the checker accepts again "
          "at a tree none of its acceptances is at", "checked at this tree" in view and "not this tree" in stale and len(third) == 1,
          (view[-300:], stale[-300:], third))
    r = checker_repo()
    rp = RP.Repo(r.root)
    L = claim(r, witnesses=["q_test:Q1", "q_test:Q2"], mutants=["Z1", "Z2"])
    base = r.commit("a claim whose mutant survives")
    held = CL.replay(rp, CHECKER_KEY)
    put_as(r, CL.CHECKER, {"target": L, "verdict": "accept", "commit": base, "tree": git(r.root, "rev-parse", f"{base}^{{tree}}"),
                           **RP.identity(r.root), "witnesses": ["q_test:Q1", "q_test:Q2"], "mutants": ["Z1", "Z2"]}, [L])
    r.commit("a forged acceptance")
    why = refused_code(CL.verify, rp, base)
    check("C14 the checker accepts no claim whose mutant survives, and CI refuses an acceptance that does not hold again at its commit",
          held == [] and why is not None and why.startswith("CLAIM_REPLAY_DIFFERS") and "does not hold" in why, (held, why))


def preflight_fixture(sentence_present):
    """Codex's case (finding e6bbc0409ecf on #224): a checker acceptance whose commit fails the claims check there
    (its sentence is missing at that commit, present at the head). The fixture hashes the real checker files."""
    sentence = "A record whose lineage is L succeeds L."
    r = Repo()
    r.trust["keys"][CL.CHECKER] = [CHECKER_KEY.public]
    r.profile["roles"]["claim/verifier"] = sorted(["carol", CL.CHECKER])
    r.write_config()
    (r.root / ".gitignore").write_text("/build/\n")
    (r.root / "docs").mkdir()
    (r.root / "docs" / "V3.md").write_text("## 3. Lineage\n" + (sentence if sentence_present else "An unrelated sentence.") + "\n")
    (r.root / "tests").mkdir()
    (r.root / "tests" / "q_test.py").write_text(TEST)
    (r.root / "tests" / "mutants.py").write_text(HARNESS)
    claims_config(r)
    shutil.copytree(ROOT / "warrant", r.root / "warrant", ignore=shutil.ignore_patterns("__pycache__"))
    body = {"state": "backed", "id": "V3-3-1", "source": SOURCE, "section": "3", "text": sentence,
            "witnesses": ["q_test:Q1"], "mutants": ["Z1"]}
    target = r.entity("alice", "claim@1", body)
    git(r.root, "init", "-q", "-b", "master")
    x = r.commit("the checker's input")
    rp = RP.Repo(r.root)
    before = [c for c, _ in CL.check(rp)[1]]
    put_as(r, CL.CHECKER, {"target": target, "verdict": "accept", "commit": x, "tree": git(r.root, "rev-parse", f"{x}^{{tree}}"),
                           **RP.identity(r.root), "witnesses": body["witnesses"], "mutants": body["mutants"]}, [target])
    (r.root / "docs" / "V3.md").write_text("## 3. Lineage\n" + sentence + "\n")
    r.commit("the acceptance, and the sentence present at the head")
    return before, refused_code(CL.verify, rp, x), [c for c, _ in CL.check(rp)[1]]


def preflight_cases():
    good = preflight_fixture(True)
    bad = preflight_fixture(False)
    check("C15 CI refuses a checker acceptance whose commit fails the claims check there, though the head passes it",
          good == ([], None, []) and bad[0] == ["CLAIM_TEXT_MISSING"] and bad[2] == [] and bad[1] is not None
          and "CLAIM_PREFLIGHT" in bad[1], (good, bad))


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
    k = RP.load_key(str(r.seed("alice")), r.root)
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
    ran = {"commit": x2, "tree": git(r.root, "rev-parse", f"{x2}^{{tree}}"), "code": RP.checker_code(x2, r.root),
           "env": {"python": "3.11.9", "cryptography": "46.0.0"}, "test": "bug_test:F1", "window": [1, 2]}
    r.put("carol", "attest", {"target": f, "verdict": "reproduces", "on": v2, **ran}, refs=[f, v2])
    true = r.commit("a true replay")
    ok = refused_code(RV.verify, rp, base)
    r.put("carol", "attest", {"target": f, "verdict": "does_not_reproduce", "on": v2, **ran}, refs=[f, v2])
    r.commit("a false replay")
    why = refused_code(RV.verify, rp, true)
    check("R05 CI re-executes every replay new since the base at its commit and refuses a different result",
          ok is None and why is not None and why.startswith("REPLAY_DIFFERS") and "re-executed reproduces" in why, (ok, why))
    r.put("carol", "attest", {"target": f, "verdict": "reproduces", "on": v2, **dict(ran, code="0" * 64)}, refs=[f, v2])
    late = r.commit("a replay naming other code")
    why = refused_code(RV.verify, rp, late + "^")
    check("R07 CI refuses a replay whose code is not the replayer's code at the commit it names", why is not None and "CODE_DIFFERS" in why, why)
    r.put("carol", "attest", {"target": f, "verdict": "does_not_reproduce", "on": v2,
                              **dict(ran, commit=x1, tree=hb["tree"], code=RP.checker_code(x1, r.root))}, refs=[f, v2])
    off = r.commit("a replay of the second head run at the first head's commit")
    why = refused_code(RV.verify, rp, off + "^")
    check("R09 CI refuses a replay that names a commit other than its head version's", why is not None and "REPLAY_NOT_DUE" in why, why)
    r.trust["keys"][RV.REPLAYER] = [CHECKER_KEY.public]
    r.profile["roles"]["replayer"] = sorted(["carol", RV.REPLAYER])
    r.write_config()
    f2 = r.put("bob", "challenge", {"target": v2, "statement": "P1 y", "severity": "P1", "what": "w", "where": [],
                                    "commit": x2, "tree": ran["tree"], "test": test}, "finding@1", refs=[v2])
    r.commit("a second finding")
    out = subprocess.run([sys.executable, "-B", "-m", "warrant.review", "--root", str(r.root), "replay", "--key", "-"],
                         input=CHECKER_KEY.seed_hex() + "\n", capture_output=True, text=True, cwd=ROOT, timeout=120)
    got = [x for x in rp.report()["_recs"].values() if x["actor"] == RV.REPLAYER]
    me = json.loads(subprocess.run([sys.executable, "-B", "-m", "warrant.review", "--root", str(ROOT), "identity"], capture_output=True,
                                   text=True, check=True, cwd=ROOT).stdout)
    check("R08 the replayer signs each replay as `review-replayer`, naming the code that ran (its own tool's) and its environment",
          out.returncode == 0 and len(got) == 1 and got[0]["body"]["target"] == f2 and got[0]["body"]["on"] == v2
          and got[0]["body"].get("code") == me["code"] and got[0]["body"].get("env") == me["env"], (out.stderr[-300:], got))
    carrier_cases(r)
    try:
        RP.identity(ROOT)
        refused = False
    except RP.Failed as e:
        refused = e.code == "IDENTITY"
    check("R06 a checker identity is refused when a module loaded from the repository is not hashed", refused)


def carrier_cases(r):
    """In a repository that carries the package's source, a checker's code is the package at the commit it names, not
    the one running; the commands run on the checkout they are started in (the package from elsewhere: PYTHONPATH)."""
    out = subprocess.run([sys.executable, "-B", "-m", "warrant.review", "head", "--pr", "3", "--actor", "alice", "--key",
                          str(r.seed("alice"))], cwd=r.root, capture_output=True, text=True,
                         env={**{k: v for k, v in os.environ.items() if k != "WARRANT_REPO_ROOT"}, "PYTHONPATH": str(ROOT)})
    rep = RP.Repo(r.root).report()
    here = git(r.root, "rev-parse", "HEAD")
    heads = [v for v in rep["_recs"].values() if v["schema"] == "pr-head@1" and v["body"].get("commit") == here]
    check("R11 the review commands run on the checkout around the current directory: its store, its repository's name "
          "and its HEAD", out.returncode == 0 and len(heads) == 1, (out.stdout[-200:], out.stderr[-300:]))
    out = subprocess.run([sys.executable, "-B", "-m", "warrant.review", "--root", str(r.root), "due", "--base", here, "--json"],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    check("R12 `due` at a base with no .warrant/merge.json is refused, exit 2 (the waker goes on to the roadmap's closures)",
          out.returncode == 2 and out.stderr.startswith("REFUSED BASE_CONFIG .warrant/merge.json"), (out.returncode, out.stderr[-300:]))
    shutil.copytree(ROOT / "warrant", r.root / "warrant", ignore=shutil.ignore_patterns("__pycache__"))
    with open(r.root / "warrant" / "repo.py", "a") as f:
        f.write("# another package\n")
    x = r.commit("a package that differs from the running one")
    body = {"commit": x, "tree": git(r.root, "rev-parse", f"{x}^{{tree}}"), "env": {"python": "3.11.9", "cryptography": "46.0.0"}}
    running = RP.checker_problem(dict(body, code=RP.package_code()), r.root)
    carried = RP.checker_problem(dict(body, code=RP.code_at(x, r.root)), r.root)
    check("R10 in a repository that carries the package, a checker's code must be the package at the commit it names, "
          "not the package that runs", running is not None and "CODE_DIFFERS" in running and carried is None, (running, carried))


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
    r = Repo()
    rp = RP.Repo(r.root)
    g = r.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "goal"})
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "old words", "answers": g, "serves": []})
    tool = lambda *argv: RP.main(RM.run, ["--root", str(r.root), *argv])           # noqa: E731
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        by_other = tool("revise", "--obligation", o, "--statement", "x", "--actor", "bob", "--key", str(r.seed("bob")))
        by_root = tool("revise", "--obligation", o, "--statement", "new words", "--actor", "alice", "--key", str(r.seed("alice")))
    rep = rp.report()
    lin = rep["lineages"][o]
    check("P03 `revise` files an open version with the new statement by the lineage's root actor, and refuses anyone else",
          by_other == 2 and by_root == 0 and lin["state"] == "open" and len(lin["versions"]) == 2
          and rep["_recs"][lin["effective"]]["body"]["statement"] == "new words", (by_other, by_root, lin))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        by_holder = tool("release", "--obligation", o, "--reason", "r", "--actor", "alice", "--key", str(r.seed("alice")))
        by_owner = tool("release", "--obligation", o, "--reason", "no longer wanted", "--actor", "dave", "--key", str(r.seed("dave")))
    rep = rp.report()
    lin = rep["lineages"][o]
    check("P04 `release` files the released version by a roadmap/owner, its reason as the residual, and refuses the holder",
          by_holder == 2 and by_owner == 0 and lin["state"] == "released"
          and rep["_recs"][lin["effective"]]["body"].get("residual") == ["no longer wanted"], (by_holder, by_owner, lin))


def cli(cwd, *argv):
    """`warrant ARGV` in process from the directory `cwd`, WARRANT_REPO_ROOT unset: (exit code, standard output)."""
    out, old, env = io.StringIO(), os.getcwd(), os.environ.pop("WARRANT_REPO_ROOT", None)
    try:
        os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = CLI.main(list(argv))
            except SystemExit as e:          # argparse refusing the arguments
                code = e.code
    finally:
        os.chdir(old)
        if env is not None:
            os.environ["WARRANT_REPO_ROOT"] = env
    return code, out.getvalue()


def cli_cases():
    r = Repo()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "s", "serves": []}, lineage=o)
    sub = r.root / "docs" / "deep"
    sub.mkdir(parents=True)
    code, out = cli(sub, "assess")
    rep = json.loads(out or "{}")
    check("K01 `warrant assess` with no flag, below the repository, assesses the nearest store under its own v3.json",
          code == 0 and rep.get("assessment") == r.report()["assessment"], (code, out[-200:]))
    other = {"warrant": "trust/3", "keys": {a: v for a, v in r.trust["keys"].items() if a != "bob"}}
    (sub / "t.json").write_text(json.dumps(other))
    code, out = cli(sub, "assess", "--trust", "t.json")
    want = E.assess(r.store.snapshot(), other, r.profile)["assessment"]
    check("K02 --trust names the trust and the store's v3.json gives the rest",
          code == 0 and json.loads(out or "{}").get("assessment") == want != r.report()["assessment"], (code, out[-200:]))
    code, out = cli(sub, "status", "--json", "--actor", "bob")
    st = json.loads(out or "{}")
    check("K03 `warrant status` counts the store's records and lineages by schema and state, and what waits for an actor",
          code == 0 and st.get("records") == len(r.store.snapshot().lines) and st.get("lineages") == {"obligation@1": {"open": 1}}
          and st.get("reliance") == {"ELIGIBLE": 1} and [x["version"] for x in (st.get("frontier") or {}).get("attest", [])] == [d],
          st)
    code, out = cli(sub, "status")
    check("K04 `warrant status` without --json says the same facts in lines",
          code == 0 and "obligation@1  open 1" in out and "reliance    ELIGIBLE 1" in out, out)
    code, out = cli(r.root, "roadmap", "--root", str(r.root), "check")
    check("K05 `warrant roadmap ARGS` is `python -m warrant.roadmap ARGS`", code == 0 and out.startswith("roadmap: 1 lineages"),
          (code, out[-200:]))
    cli(sub, "init")
    check("K06 `warrant init` creates the store in the current directory, also inside a repository",
          (sub / ".warrant" / "records.jsonl").is_file(), sorted(p.name for p in sub.iterdir()))
    other = Repo(name="s0fractal/other")              # Codex finding 24b91d75f065 on #236: a `.warrant` link out of its repository
    linked = r.home / "linked"
    linked.mkdir()
    (linked / ".warrant").symlink_to(other.dot, target_is_directory=True)
    (linked / "payload").write_bytes(b"a payload")
    before = sorted(p.name for p in other.store.blobs.iterdir())
    found, _ = cli(linked, "blob", "payload")
    made, _ = cli(linked, "init")
    check("K07 a store found by default is confined to the directory it is found in: a `.warrant` link out of it is refused, "
          "by discovery and by init", found == 2 and made == 2 and sorted(p.name for p in other.store.blobs.iterdir()) == before,
          (found, made))
    outside = Repo(name="s0fractal/outside")         # Codex finding d6127c0fd71d on #236: v3.json a link out of its store
    (outside.dot / "v3.json").rename(outside.home / "foreign-receiver.json")
    (outside.dot / "v3.json").symlink_to(outside.home / "foreign-receiver.json")
    code_a, _ = cli(outside.root, "assess")
    code_r, _ = cli(outside.root, "roadmap", "--root", str(outside.root), "check")
    check("K08 a repository's v3.json is read from its store only: a link to a file outside it is refused, by the core's "
          "commands and by the review loop's", code_a == 2 and code_r == 2, (code_a, code_r))
    bob = str(r.seed("bob"))                         # time-lab N6: an unsorted `closed` was filed and never counted
    before = r.store.lines()
    body = {"name": "probe@1", "fields": {"state": "str"}, "states": {"a": None, "b": None}, "successors": {}}
    at = ("put", "--store", "repo/.warrant", "--kind", "schema", "--actor", "bob", "--key", bob)   # the seed: inside the cwd
    bad, _ = cli(r.home, *at, json.dumps(dict(body, closed=["b", "a"])))
    kept = r.store.lines() == before
    good, _ = cli(r.home, *at, json.dumps(dict(body, closed=["a", "b"])))
    check("K09 `warrant put --kind schema` refuses a body the engine would never count (here an unsorted `closed`) and "
          "writes nothing, as the agent's prepare does; a schema body is filed", bad == 2 and kept and good == 0
          and len(r.store.lines()) == len(before) + 1, (bad, kept, good))


def home_cases():
    r, other = Repo(), Repo(name="s0fractal/other")
    env = os.environ.get("WARRANT_HOME")
    os.environ["WARRANT_HOME"] = str(r.home / "config" / "home.json")
    try:
        seed = r.seed("alice")
        os.chmod(seed, 0o600)
        stray = r.home / "keys" / "stray.seed"                # a key no repository's trust binds
        stray.write_text(K.Key.generate().seed_hex())
        os.chmod(stray, 0o600)
        tree = sorted((str(q), q.read_bytes()) for q in r.root.rglob("*") if q.is_file())
        doc = H.add_identity(H.add_identity(H.empty(), "alice", str(seed)), "zed", str(stray))
        doc = H.add_repository(H.add_repository(doc, str(r.root), "one", "alice"), str(other.root), "two", "zed")
        H.save(doc)
        rows = {x["name"]: x for x in H.listing(H.load())}
        check("H01 Home lists each repository with the repository its v3.json names, its record lines, and whether its "
              "trust binds the signer's key", rows["one"].get("repository") == "s0fractal/warrant" and rows["one"].get("bound") is True
              and rows["one"].get("records") == len(r.store.lines()) and rows["two"].get("bound") is False, rows)
        inside = r.root / "in.seed"
        inside.write_text(K.Key.generate().seed_hex())
        os.chmod(inside, 0o600)
        why_seed = refused_home(H.add_identity, doc, "carol", str(inside))
        loose = other.root / "x.seed"                       # registered first, then its repository
        loose.write_text(K.Key.generate().seed_hex())
        os.chmod(loose, 0o600)
        why_repo = refused_home(H.add_repository, H.add_identity(H.empty(), "carol", str(loose)), str(other.root), "two")
        inside.unlink()
        loose.unlink()
        check("H02 a seed never lies inside a registered repository, whichever is registered first",
              "inside the registered repository" in why_seed and "inside the registered repository" in why_repo, (why_seed, why_repo))
        hp = H.path()
        os.chmod(hp, 0o620)
        writable = refused_home(H.load)
        os.chmod(hp, 0o600)
        link = r.home / "config" / "link.json"
        link.symlink_to(hp)
        linked = refused_home(H.load, link)
        check("H03 a Home other users may write, or a link to one, is refused", "other users may write" in writable
              and "not a link" in linked, (writable, linked))
        os.chmod(stray, 0o644)
        readable = refused_home(H.add_identity, H.empty(), "zed", str(stray))
        os.chmod(stray, 0o600)
        check("H04 a seed others may read is refused at registration", "others may read" in readable, readable)
        code, out = cli(r.home, "status", "--repo", "two", "--json")
        check("H05 `warrant status --repo NAME` reads that registered repository's store, from any directory",
              code == 0 and json.loads(out or "{}").get("repository") == "s0fractal/other", (code, out[-200:]))
        third = r.home / "third"                             # a registered repository whose .warrant leads out of it
        third.mkdir()
        (third / ".warrant").symlink_to(other.dot, target_is_directory=True)
        H.save(dict(doc, repositories=dict(doc["repositories"], three={"path": str(third)})))
        code3, _ = cli(r.home, "status", "--repo", "three")
        check("H07 a registered repository's store is confined to it: a `.warrant` link out of it is refused", code3 == 2, code3)
        H.save(doc)
        (other.dot / "v3.json").rename(other.home / "foreign-receiver.json")
        (other.dot / "v3.json").symlink_to(other.home / "foreign-receiver.json")
        rows = {x["name"]: x for x in H.listing(doc)}
        added = refused_home(H.add_repository, H.empty(), str(other.root), "again")
        check("H08 Home reads a repository's v3.json from its store only: a link out of it is refused, when it is listed "
              "and when it is registered", "outside" in rows["two"].get("problem", "") and "outside" in added, (rows["two"], added))
        (other.dot / "v3.json").unlink()
        (other.home / "foreign-receiver.json").rename(other.dot / "v3.json")
        escaping = r.home / "escaping"
        escaping.mkdir()
        (escaping / ".warrant").symlink_to(other.dot, target_is_directory=True)
        why_link = refused_home(H.add_repository, H.empty(), str(escaping), "escaping")      # other's v3.json is its own again
        code_loop, _ = cli(escaping, "roadmap", "--root", str(escaping), "check")
        check("H09 a repository whose `.warrant` links out of it is refused at registration and by the review loop's "
              "commands", "outside" in why_link and code_loop == 2, (why_link, code_loop))
        race = r.home / "config" / "race.json"          # Codex finding 773e7e02f857 on #238: two changes at once
        H.save(H.empty(), race)

        def slow(d):
            time.sleep(0.4)                              # inside the first change, after its read
            return H.add_repository(d, str(r.root), "first")
        first = threading.Thread(target=H.update, args=(slow, race))
        first.start()
        time.sleep(0.1)
        os.environ["WARRANT_HOME"] = str(race)
        code_second, _ = cli(r.home, "home", "add", str(other.root), "--name", "second")
        os.environ["WARRANT_HOME"] = str(r.home / "config" / "home.json")
        first.join()
        names = sorted(H.load(race)["repositories"])
        check("H10 two changes of Home made at once both take effect: the second waits for the first's write",
              code_second == 0 and names == ["first", "second"], (code_second, names))
        shared = r.home / "shared"                      # Codex finding 3f75f9921074 on #238: a Home in a directory others may write
        shared.mkdir()
        H.save(doc, shared / "home.json")
        os.chmod(shared, 0o777)
        refusals = [refused_home(H.load, shared / "home.json"), refused_home(H.save, doc, shared / "home.json"),
                    refused_home(H.update, lambda d: d, shared / "home.json")]
        os.chmod(shared, 0o700)
        check("H11 a Home whose directory other users may write is refused when it is read, saved or changed",
              all("other users may write the Home's directory" in w for w in refusals), refusals)
        cli(r.home, "home")
        check("H06 Home writes nothing into a repository", sorted((str(q), q.read_bytes()) for q in r.root.rglob("*") if q.is_file())
              == tree)
    finally:
        if env is None:
            os.environ.pop("WARRANT_HOME", None)
        else:
            os.environ["WARRANT_HOME"] = env


def refused_home(fn, *a):
    try:
        fn(*a)
        return ""
    except (OSError, ValueError) as e:
        return str(e)


def differential_cases():
    """warrant.differential (roadmap G12): the published release n and this package on one store."""
    r = Repo()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    r.entity("alice", "obligation@1", {"state": "done", "statement": "s", "serves": []}, lineage=o)
    head = DF.head_report(r.root)

    def as_n(rep, **change):
        """`rep` as another engine made it: its code (and so its assessment) another, `change` applied."""
        n = json.loads(json.dumps(dict(rep, code="0" * 64, **change)))
        n["assessment"] = JCS.doc_id({k: n.get(k) for k in DF.OPERANDS})
        return n
    moved = json.loads(json.dumps(head["lineages"]))
    moved[o]["state"] = "released"                       # what another engine might have found
    decl = {"warrant": DF.FORMAT, "differs": ["lineages"], "because": "a migration"}
    got = {"same": DF.compare(as_n(head), head)["verdict"],
           "moved": DF.compare(as_n(head, lineages=moved), head),
           "declared": DF.compare(as_n(head, lineages=moved), head, decl)["verdict"],
           "stale": DF.compare(as_n(head), head, decl)["verdict"],
           "wider": DF.compare(as_n(head, lineages=moved), head, dict(decl, differs=["lineages", "versions"]))["verdict"]}
    check("D01 the published release and the head agree when their reports differ only in the engine's identity (code, "
          "and the assessment digest that includes it)", got["same"] == "SAME", got)
    check("D02 any other difference is refused unless declared, and a declaration names exactly the members that differ: "
          "one that did not occur, or one more than occurred, is refused", got["moved"]["verdict"] == "REFUSED"
          and got["moved"]["differs"] == ["lineages"] and got["declared"] == "DECLARED" and got["stale"] == "REFUSED"
          and got["wider"] == "REFUSED", got)
    forged = dict(as_n(head), code="1" * 64)          # its assessment no longer its operands': no excluded member hides a change
    check("D03 a report whose assessment is not the digest of its own operands (snapshot, trust, profile, as_of, code) is "
          "refused, before anything is compared",
          DF.compare(forged, head)["verdict"] == "REFUSED", DF.compare(forged, head))
    calls = []

    def fake(cmd, **kw):
        calls.append((cmd, kw.get("cwd")))
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(as_n(head)).encode(), stderr=b"")

    def failing(cmd, **kw):                            # a report on stdout, but the run failed: no report
        return subprocess.CompletedProcess(cmd, 1, stdout=json.dumps(as_n(head)).encode(), stderr=b"interrupted")
    n = DF.published_report("/n/python", r.root, run=fake)
    (cmd, cwd), = calls
    try:
        DF.published_report("/n/python", r.root, run=failing)
        unmade = False
    except DF.Unmade:
        unmade = True
    check("D04 the published release runs isolated (-I) from a directory outside the checkout, on this store and its "
          "v3.json receiver, and a run that fails makes no report", cmd[:3] == ["/n/python", "-I", "-c"]
          and cmd[4] == str(r.dot) and json.loads(cmd[5]) == {"trust": r.trust, "profile": r.profile}
          and cwd is not None and not Path(cwd).resolve().is_relative_to(r.root.resolve()) and n["code"] == "0" * 64 and unmade,
          (cmd[:2], cmd[4:], cwd, unmade))
    seen = []

    def where(cmd, **kw):
        seen.append(cmd[0])
        return fake(cmd, **kw)
    old = os.getcwd()
    try:
        os.chdir(r.home)                              # Codex finding 30154b8b64e1 on #246: a path from here, run from elsewhere
        DF.published_report("runner/python", r.root, run=where)
        DF.published_report("python3", r.root, run=where)
    finally:
        os.chdir(old)
    check("D06 an interpreter named by a path is the one that path names from the caller's directory, though it runs "
          "from another; a bare name stays a name for PATH", seen == [str(r.home / "runner" / "python"), "python3"], seen)

    def here(cmd, **kw):                              # the release script, run by this checkout's engine (not -I)
        return subprocess.run([sys.executable, *cmd[2:]], capture_output=True, cwd=kw.get("cwd"), check=False,
                              env=dict(os.environ, PYTHONPATH=str(ROOT)))
    rel = r.entity("alice", "obligation@1", {"state": "open", "statement": "release 9.9", "serves": []})
    stages = {"open": DF.release_duties("py", r.root, "9.9", run=here)}
    closed = r.entity("alice", "obligation@1", {"state": "done", "statement": "release 9.9", "serves": [],
                                                 "refs": ["warrant-graph==9.9"]}, lineage=rel)
    stages["closed"] = DF.release_duties("py", r.root, "9.9", run=here)
    r.attest("bob", closed, verdict="accept")
    stages["accepted"] = DF.release_duties("py", r.root, "9.9", run=here)
    stages["other version"] = DF.release_duties("py", r.root, "9.10", run=here)
    forgiven = r.entity("alice", "obligation@1", {"state": "open", "statement": "release 9.11", "serves": []})
    r.entity("dave", "obligation@1", {"state": "released", "statement": "release 9.11", "serves": [],
                                       "refs": ["warrant-graph==9.11"]}, lineage=forgiven)
    stages["released"] = DF.release_duties("py", r.root, "9.11", run=here)
    check("D07 release n admits n+1 only through a release duty n's own engine finds closed and accepted with the "
          "version's ref: none while open, none while its closure waits for the acceptor, none for another version, "
          "none forgiven (released) by the owner", stages == {"open": [], "closed": [], "accepted": [closed],
                                                               "other version": [], "released": []}, stages)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        old_pr = DF.published
        DF.published = lambda python, root, script, *args, run=None: \
            (as_n(DF.head_report(r.root)) if script == DF.SCRIPT else {"release": args[0], "accepted": []})
        try:
            code = DF.main(["--python", "py", "--root", str(r.root), "--release", "1.0"])
        finally:
            DF.published = old_pr
    verdict = json.loads(out.getvalue())
    check("D08 --release refuses a release whose reports agree (here SAME but for the release) when no release duty "
          "of it is accepted", code == 1 and verdict["verdict"] == "REFUSED" and verdict["differs"] == []
          and verdict["release"]["accepted"] == [], verdict)

    def admitted(doc):
        f = r.home / "decl.json"
        f.write_text(json.dumps(doc))
        try:
            return DF.declaration(f)["differs"]
        except DF.Unmade:
            return None
    got = {"good": admitted(decl), "empty": admitted(dict(decl, differs=[])), "no reason": admitted(dict(decl, because=" ")),
           "not names": admitted(dict(decl, differs=[1])), "extra": admitted(dict(decl, by="x"))}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = DF.main(["--python", "/nonexistent/python", "--root", str(r.root)])
    check("D05 a declaration names one member or more and says why; anything else is no declaration, and a release that "
          "cannot be run makes no verdict (UNMADE, exit 2)", got["good"] == ["lineages"]
          and all(v is None for k, v in got.items() if k != "good") and code == 2
          and json.loads(out.getvalue())["verdict"] == "UNMADE", (got, code))


if __name__ == "__main__":
    claims_cases()
    preflight_cases()
    review_cases()
    roadmap_cases()
    cli_cases()
    home_cases()
    differential_cases()
    sys.exit(finish())
