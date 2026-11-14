#!/usr/bin/env python3
"""The review loop's commands on fixture repositories: claims (warrant/claims.py), the review loop's commands and
replay checker (warrant/review.py), the roadmap (warrant/roadmap.py) and what a checker's attest names (warrant/repo.py).

    python3 tests/tools_test.py
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from world import KEYS, ROLES, ROOT, Repo, check, git, run_sections

from warrant import across as A
from warrant import board as BD
from warrant import chains as CH
from warrant import claims as CL
from warrant import cli as CLI
from warrant import differential as DF
from warrant import drift as D
from warrant import engine as E
from warrant import jcs as JCS
from warrant import home as H
from warrant import keys as K
from warrant import records as R
from warrant import repo as RP
from warrant import review as RV
from warrant import roadmap as RM
from warrant.store import Store

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
    (r.root / "mutated.py").write_text("X = 0\n")
    (r.root / "tests" / "mutants.py").write_text(HARNESS.replace("warrant/engine.py", "mutated.py"))
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
    r = claims_repo()                                      # a repository whose claims live in two documents
    (r.root / "docs" / "RESUME.md").write_text("## 1. Resume\n\nA resumed run reaches the straight run's result.\n")
    two = dict(CLAIMS, source=[SOURCE, "docs/RESUME.md"])
    (r.root / ".warrant" / "claims.json").write_text(json.dumps(two))
    claim(r)
    claim(r, id="R-1-1", source="docs/RESUME.md", section="1", text="A resumed run reaches the straight run's result.")
    both = codes(r)
    wrong = claims_repo()
    (wrong.root / "docs" / "RESUME.md").write_text("## 1. Resume\n")
    (wrong.root / ".warrant" / "claims.json").write_text(json.dumps(two))
    claim(wrong, id="R-1-2", source="docs/RESUME.md", section="1")    # the first source's sentence, under the second
    claim(wrong, id="R-1-3", source="docs/OTHER.md")
    refused = sorted(codes(wrong))
    shapes = {}
    (wrong.root / RETIRED).write_text(SPEC)                # present, so only the configuration can refuse it
    for name, src in (("empty", []), ("twice", [SOURCE, SOURCE]), ("retired", [SOURCE, RETIRED])):
        (wrong.root / ".warrant" / "claims.json").write_text(json.dumps(dict(CLAIMS, source=src)))
        shapes[name] = (refused_code(CL.check, RP.Repo(wrong.root)) or "")[:6]
    git(r.root, "init", "-q", "-b", "master")
    git(r.root, "add", "-A")
    git(r.root, "commit", "-q", "-m", "two sources")
    text = CL.view(RP.Repo(r.root).report(), r.root)
    seed = r.seed("alice")
    try:
        CL.file_claims(RP.Repo(r.root), "alice", RP.load_key(str(seed), r.root),
                       [{"id": "R-9", "section": "1", "text": "x", "witnesses": [], "mutants": [], "source": "docs/OTHER.md"}])
        filed_elsewhere = "filed"
    except CL.Failed as e:
        filed_elsewhere = e.code
    check("C21 claims.json may name several sources: each claim's sentence is checked in its own source, a claim of a source "
          "not named is refused, a list empty, repeated or naming a retired source is no configuration, the view lists every "
          "source's claims, and a claim is filed only under a named source",
          both == [] and refused == ["CLAIM_SOURCE", "CLAIM_TEXT_MISSING"]
          and shapes == {"empty": "CONFIG", "twice": "CONFIG", "retired": "CONFIG"}
          and "docs/RESUME.md §1" in text and f"{SOURCE} §3" in text and filed_elsewhere == "CLAIM_SOURCE",
          (both, refused, shapes, filed_elsewhere))
    covered = {}                                           # Codex finding 5c401f4c on sigma-glyph#78
    for name, extra, filed in (
            ("claimed", "", ["A record whose `lineage` is L **succeeds** L."]),
            ("bare MUST", "Every record MUST name its schema.\n", ["A record whose `lineage` is L **succeeds** L."]),
            ("inside a claim", "Every record MUST name its schema.\n",
             ["A record whose `lineage` is L **succeeds** L.", "Every record MUST name its schema."]),
            ("informative", "Key words MUST and SHALL are as in RFC 2119.\n",
             ["A record whose `lineage` is L **succeeds** L.", "Key words MUST and SHALL are as in RFC 2119."]),
            ("heading, word, other case", "## 4. MUST PASS\n\nMUSTARD and must are no keywords.\n",
             ["A record whose `lineage` is L **succeeds** L."]),
            ("SHALL listed", "A reader SHALL NOT guess.\n", ["A record whose `lineage` is L **succeeds** L."]),
            ("the next sentence", "A record whose `lineage` is L **succeeds** L.\n\nA record MUST be signed.\n",
             ["A record whose `lineage` is L **succeeds** L."]),
            ("every occurrence", "A record MUST be signed.\n\nA record MUST be signed.\n",
             ["A record whose `lineage` is L **succeeds** L.", "A record MUST be signed."]),
            ("a claim ending inside it", "A reader MUST guess.\n",                # Codex finding on #259
             ["A record whose `lineage` is L **succeeds** L.", "A reader MU"]),
            ("MUST of MUST NOT", "A reader SHALL NOT guess.\n",
             ["A record whose `lineage` is L **succeeds** L.", "A reader SHALL"]),
            ("wrapped", "A reader SHALL\n  NOT guess.\n",                          # Codex finding cceaee70 on #259
             ["A record whose `lineage` is L **succeeds** L.", "A reader SHALL"]),
            ("wrapped, claimed", "A reader SHALL\n  NOT guess.\n",
             ["A record whose `lineage` is L **succeeds** L.", "A reader SHALL\n  NOT guess."])):
        r = claims_repo()
        (r.root / SOURCE).write_text(SPEC + extra)
        (r.root / ".warrant" / "claims.json").write_text(json.dumps(dict(CLAIMS, coverage=["MUST", "SHALL", "SHALL NOT"])))
        for i, text in enumerate(filed):
            claim(r, id=f"V3-3-{i + 1}", text=text,
                  **({"state": "informative", "witnesses": [], "mutants": [], "reason": "names the keywords"}
                     if name == "informative" and i else {}))
        got = CL.check(RP.Repo(r.root))[1]
        covered[name] = [d.split(" in «")[0] for c, d in got if c == "UNCLAIMED_KEYWORD"] or sorted({c for c, _ in got})
    r = claims_repo()
    claim(r)
    (r.root / SOURCE).write_text(SPEC + "Every record MUST name its schema.\n")
    off = codes(r)                                         # no "coverage": the configuration did not ask
    bad = {}
    for name, cover in (("empty", []), ("lower", ["must"]), ("twice", ["MUST", "MUST"]), ("trailing newline", ["MUST\n"])):
        (r.root / ".warrant" / "claims.json").write_text(json.dumps(dict(CLAIMS, coverage=cover)))
        bad[name] = (refused_code(CL.check, RP.Repo(r.root)) or "")[:6]
    check("C22 with `coverage`, every listed keyword outside a heading lies in some live claim's sentence (any state, an "
          "informative one included), whole: one that does not, or that a claim covers only in part, is UNCLAIMED_KEYWORD "
          "with its line, the words of a keyword across a line break or spaces included; a heading, a longer word or "
          "lower case is no keyword; without `coverage` nothing is asked; a coverage list empty, lower-case, repeated or "
          "with a trailing newline is no configuration",
          covered == {"claimed": [], "bare MUST": [f"{SOURCE}:6: MUST"], "inside a claim": [], "informative": [],
                      "heading, word, other case": [], "SHALL listed": [f"{SOURCE}:6: SHALL NOT"],
                      "the next sentence": [f"{SOURCE}:8: MUST"], "every occurrence": [],
                      "a claim ending inside it": [f"{SOURCE}:6: MUST"], "MUST of MUST NOT": [f"{SOURCE}:6: SHALL NOT"],
                      "wrapped": [f"{SOURCE}:6: SHALL NOT"], "wrapped, claimed": []}
          and off == [] and bad == {k: "CONFIG" for k in bad},
          (covered, off, bad))
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
    held = []
    once = CL.verify(rp, base, frozenset(), held)
    skipped = CL.verify(rp, base, frozenset(held))
    outside = refused_code(CL.run, ["--root", str(r.root), "verify", "--base", base, "--done", str(r.home / "done-ids")])
    check("C20 an acceptance a run of the same branch re-executed and found holding is not run again (its result at its "
          "commit cannot change), and a run names what held, so a pull request whose base moved re-executes only what is new "
          "(#364: 136 acceptances, 40 minutes each time); the file it keeps is one of the checkout, as every path a tool "
          "writes", once == 1 and held == first and skipped == 0 and (outside or "").startswith("PATH"), (once, held, skipped, outside))
    ids_file = r.root / "build" / "claims-done" / "ids"
    ids_file.parent.mkdir(parents=True, exist_ok=True)
    code = RP.identity(r.root)["code"]
    def verify_with(text):
        ids_file.write_text(text)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            CL.run(["--root", str(r.root), "verify", "--base", base, "--done", str(ids_file)])
        return buf.getvalue()
    same, other = verify_with(f"{first[0]} {code}\n"), verify_with(f"{first[0]} {'0' * 64}\n")
    ids_file.write_text(f"{first[0]} {code}\n")
    git(r.root, "add", "-f", "build/claims-done/ids")
    tracked = refused_code(CL.run, ["--root", str(r.root), "verify", "--base", base, "--done", str(ids_file)])
    git(r.root, "rm", "-q", "--cached", "build/claims-done/ids")
    q = checker_repo()                                       # a repository holding the package and its shim, as CI's checkout
    claim(q)
    shutil.copytree(ROOT / "warrant", q.root / "warrant", ignore=shutil.ignore_patterns("__pycache__"))
    (q.root / "tools").mkdir()
    shutil.copy(ROOT / "tools" / "claims.py", q.root / "tools" / "claims.py")
    qx = q.commit("the package and its shim")
    shim = subprocess.run([sys.executable, "-B", "tools/claims.py", "verify", "--base", qx, "--done", "build/claims-done/ids"],
                          capture_output=True, text=True, cwd=q.root, env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    check("C22 the command line CI runs (tools/claims.py verify --done, the shim) works: the code a done entry is bound "
          "to is the checker's code at the commit, not the identity of the running process (observed on #367 at 0eeb3072: "
          "REFUSED IDENTITY tools/claims.py is imported and not in the identity)",
          shim.returncode == 0 and "held before" in shim.stdout, (shim.returncode, shim.stdout[-200:], shim.stderr[-300:]))
    check("C21 a done file counts only as the runner's own: one the tree holds is refused (Codex on #367: a committed "
          "done file skipped the replay of what it named), and an entry counts only for the checker code that wrote it",
          "0 re-executed, 1 held before" in same and "1 re-executed" in other and (tracked or "").startswith("PATH"),
          (same, other, tracked))
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


def drift_repo():
    """A checker repository whose harness mutates lib/code.py; the claim is accepted by the claims checker at the head."""
    r = checker_repo()
    (r.root / "lib").mkdir()
    (r.root / "lib" / "code.py").write_text("X = 1\n")
    (r.root / "tests" / "mutants.py").write_text(HARNESS.replace("warrant/engine.py", "lib/code.py"))
    L = claim(r)
    r.commit("a claim")
    CL.replay(RP.Repo(r.root), CHECKER_KEY)
    r.commit("its acceptance")
    return r, L


def gated(r, L):
    """(drift answer, reliance) of claim lineage L at r's head."""
    rep = RP.Repo(r.root).report()
    d = D.gate(rep, r.root)
    return d.get(L, {}), rep["lineages"][L]["reliance"]


def pinned_by_lead():
    """A repository with no .warrant/claims.json: bob (roadmap/acceptor) accepts goal G1 met on lib/a.py's bytes at a
    commit (`files`, `commit`), the analysis session's case of 2026-11-13. Returns (repo, lineage, met version)."""
    r = Repo(git_init=True)
    (r.root / "lib").mkdir()
    (r.root / "lib" / "a.py").write_text("A = 1\n")
    x = r.commit("the file")
    goal = r.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "a question"})
    met = r.entity("alice", "goal@1", {"state": "met", "key": "G1", "text": "a question", "established": ["held"]}, lineage=goal)
    blob = git(r.root, "rev-parse", f"{x}:lib/a.py")
    r.attest("bob", met, commit=x, files={"lib/a.py": blob})
    r.commit("accepted on lib/a.py at its commit")
    return r, goal, met


def assessed(r, L):
    """(drift verdict, gate reliance, status's reliance counts, assess CLI reliance) of lineage L at r's head."""
    d, rel = gated(r, L)
    out = io.StringIO()
    with contextlib.chdir(r.root):
        st = CLI.status(CLI._parser().parse_args(["status", "--store", ".warrant"]))
        with contextlib.redirect_stdout(out):
            CLI.main(["assess", "--store", ".warrant"])
    return d.get("verdict"), rel, st["reliance"], json.loads(out.getvalue())["lineages"][L]["reliance"]


def pinned_cases():
    r, L, met = pinned_by_lead()
    before = assessed(r, L)
    (r.root / "lib" / "a.py").write_text("A = 2\n")
    r.commit("the file changes")
    after = assessed(r, L)
    check("DR30 any signed acceptance naming files at a commit that the version's guard counts pins the version, whatever "
          "its schema, with no .warrant/claims.json: a lead's acceptance of a goal on a file reads ELIGIBLE while the file "
          "holds its bytes and STALE once it changes, in drift, status and assess alike (the analysis session, 2026-11-13: "
          "STALE needed claims.json and the claims checker's name, and `assess` printed ELIGIBLE where status said STALE)",
          not (r.dot / "claims.json").exists() and before[:2] == ("UNCHANGED", "ELIGIBLE") and before[3] == "ELIGIBLE"
          and after[:2] == ("CHANGED", D.STALE) and after[2].get(D.STALE) == 1 and after[3] == D.STALE, (before, after))
    r2 = Repo(roles=dict(ROLES, migrator=["carol"]), git_init=True)
    (r2.root / "lib").mkdir()
    (r2.root / "lib" / "a.py").write_text("A = 1\n")
    x = r2.commit("the file")
    L2 = r2.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "a question"})
    met2 = r2.entity("alice", "goal@1", {"state": "met", "key": "G1", "text": "a question", "established": ["held"]}, lineage=L2)
    r2.attest("bob", met2)                                                # counted, naming no files: not pinned
    rec = R.record("attest", "eve", r2.t + 1, {"verdict": "accept", "target": met2, "commit": x,
                                               "files": {"lib/a.py": "1" * 40}}, refs=[met2])
    r2.store.append(rec, K.Key.from_seed_hex("ab" * 32), r2.trust)        # other bytes, under a key not trusted
    vouched = R.record("attest", "bob", r2.t + 2, {"verdict": "accept", "target": met2, "commit": x,
                                                   "files": {"lib/a.py": "2" * 40}}, refs=[met2])
    vid, line = R.line(vouched, None)                                     # other bytes, unsigned, vouched by a migration
    with open(r2.dot / "records.jsonl", "ab") as f:
        f.write(line)
    m = r2.blob(JCS.canon({"map": [[vid, ["11" * 32], []]]}))
    r2.put("carol", "attest", {"target": m, "verdict": "migrated"}, R.MIGRATION, refs=[m])
    r2.commit("an unpinned acceptance, an untrusted pinned attest, a migrated one")
    d2, rel2 = gated(r2, L2)
    basis2 = RP.Repo(r2.root).report()["_basis"].get(vid)
    check("DR31 only a signed acceptance that names files pins: one naming other bytes under a key the receiver does not "
          "trust, or carried unsigned by a migration (MIGRATED, as claims.acceptances reads only SIGNED), lowers nothing, "
          "and an acceptance naming no files leaves no drift answer",
          basis2 == "MIGRATED" and d2 == {} and rel2 == "ELIGIBLE", (basis2, d2, rel2))
    r3, L3, met3 = pinned_by_lead()
    (r3.root / "lib" / "a.py").write_text("A = 2\n")
    c2 = r3.commit("the file changes")
    stale3 = assessed(r3, L3)
    r3.attest("eve", met3, commit=c2, files={"lib/a.py": git(r3.root, "rev-parse", f"{c2}:lib/a.py")})   # trusted, no role
    r3.commit("an acceptance of the new bytes by an actor whose word does not count here")
    after3 = assessed(r3, L3)
    r4 = Repo(git_init=True)
    (r4.root / "lib").mkdir()
    (r4.root / "lib" / "a.py").write_text("A = 1\n")
    x4 = r4.commit("the file")
    L4 = r4.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "a question"})
    met4 = r4.entity("alice", "goal@1", {"state": "met", "key": "G1", "text": "a question", "established": ["held"]}, lineage=L4)
    r4.attest("bob", met4)
    r4.attest("eve", met4, commit=x4, files={"lib/a.py": "3" * 40})                                      # other bytes, no role
    r4.commit("a counted acceptance naming no files, and a word with no role naming other bytes")
    d4, rel4 = gated(r4, L4)
    check("DR32 an acceptance the version's guard does not count pins nothing: eve, trusted with no role, accepting the "
          "changed bytes leaves the stale lineage STALE in drift, status and assess; naming other bytes on a lineage no "
          "counted acceptance pins, she gives it no drift answer and it stays ELIGIBLE (the analysis session on #386, "
          "08b2276f)", stale3[:2] == ("CHANGED", D.STALE) and after3[:2] == ("CHANGED", D.STALE)
          and after3[2].get(D.STALE) == 1 and after3[3] == D.STALE and d4 == {} and rel4 == "ELIGIBLE",
          (stale3, after3, d4, rel4))


def drift_cases():
    from warrant_agent import api
    from warrant_agent.config import Config
    def agent(r):
        return Config({"agent_api": "warrant-agent/3", "workspaces": {"w": {"repo": str(r.root), "operations": ["context", "graph"]}}})
    r, L = drift_repo()
    rep = RP.Repo(r.root).report()
    pin = next(x["body"].get("files") for x in rep["_recs"].values() if x["kind"] == "attest" and x["actor"] == CL.CHECKER)
    (r.root / "README").write_text("unrelated\n")
    r.commit("an unrelated file")
    d0, rel0 = gated(r, L)
    home = {"repositories": {"r": {"path": str(r.root)}}}
    lens0 = A.answer(A.home_readings(home), {"query": "stores"})["lens"]
    (r.root / "lib" / "code.py").write_text("X = 2\n")
    x = r.commit("the mutated file changes")
    d1, rel1 = gated(r, L)
    far = tuple((x.verdict(L) or {}).get("reliance") if x.view else None for x in (A.home_readings(home)[0], api._reading(agent(r).workspaces["w"])))
    lens1 = A.answer(A.home_readings(home), {"query": "stores"})["lens"]
    ctx = api.call(agent(r), "context", {"workspace": "w", "targets": [L]})
    seen = ctx.get("ok", {}).get("targets", {}).get(L, {}).get("lineage", {}).get("reliance")
    text = D.lines({L: d1})
    shown = CL.view(RP.Repo(r.root).report(), r.root)
    CL.replay(RP.Repo(r.root), CHECKER_KEY)
    r.commit("accepted again")
    d2, rel2 = gated(r, L)
    check("DR1 a claim whose accepted mutant or witness files are other bytes at HEAD is STALE, not ELIGIBLE, in the drift answer, "
          "in claims view and in the agent's context, until the claims checker accepts it again (G14 obligation 055751e2); the "
          "acceptance names the files it ran on", set(pin or {}) == {"lib/code.py", "tests/q_test.py"}
          and d0.get("verdict") == "UNCHANGED" and rel0 == "ELIGIBLE" and d1.get("verdict") == "CHANGED" and rel1 == D.STALE
          and seen == D.STALE and f"; {D.STALE}; leaf `{rep['lineages'][L]['leaf'] or L}`)" in shown and d2.get("verdict") == "UNCHANGED" and rel2 == "ELIGIBLE",
          (pin, d0, rel0, d1, rel1, seen, d2, rel2))
    check("DR16 `across` reads a stale claim STALE as context does, through Home and through the agent, and its lens binds the "
          "tree it read: the same store answers differently at two heads", far == (D.STALE, D.STALE) and lens0 != lens1, (far, lens0, lens1))
    check("DR2 the drift answer leads with the verdict on the bytes and names the first commit after the accepted one that "
          "changed the file (obligation a476855f)",
          text.startswith("CHANGED ") and {"verdict": "CHANGED", "path": "lib/code.py", "detail": f"since {x[:12]}"} in d1.get("files", [])
          and "lib/code.py" in text.splitlines()[1] and "STALE" in text.splitlines()[0], (text, d1))
    r, L = drift_repo()
    git(r.root, "mv", "lib/code.py", "lib/moved.py")
    (r.root / "tests" / "mutants.py").write_text(HARNESS.replace("warrant/engine.py", "lib/moved.py"))
    r.commit("the mutated file moves, its bytes unchanged")
    d, rel = gated(r, L)
    text = D.lines({L: d})
    check("DR3 a file moved with its bytes unchanged reads as unchanged, at its new path, and the claim stays ELIGIBLE",
          d.get("verdict") == "UNCHANGED" and rel == "ELIGIBLE" and text.startswith("unchanged ")
          and {"verdict": "MOVED", "path": "lib/code.py", "detail": "now at lib/moved.py"} in d.get("files", [])
          and "unchanged, moved: now at lib/moved.py (was lib/code.py)" in text, (d, rel, text))
    r, L = drift_repo()
    os.chmod(r.root / "lib" / "code.py", 0o755)
    r.commit("the accepted file's mode changes, its bytes do not")
    mid, mid_rel = gated(r, L)
    (r.root / "lib" / "code.py").write_text("X = 2\n")
    edit = r.commit("the accepted file's bytes change")
    (r.root / "lib" / "code.py").write_text("X = 3\n")
    r.commit("and change again")
    d, rel = gated(r, L)
    check("DR26 a commit that changes only a file's mode changes no bytes: CHANGED names the first commit that changed them "
          "(Codex finding e895d8cad992)", mid.get("verdict") == "UNCHANGED" and mid_rel == "ELIGIBLE" and rel == D.STALE
          and {"verdict": "CHANGED", "path": "lib/code.py", "detail": f"since {edit[:12]}"} in d.get("files", []), (mid, d))
    seen = {}
    r, L = drift_repo()
    (r.root / "lib" / "code.py").unlink()
    r.commit("the accepted file is deleted")
    seen["deleted"] = gated(r, L)[0].get("verdict")
    (r.root / "lib" / "code.py").write_text("X = 1\n")
    r.commit("restored with the same bytes")
    seen["restored"] = gated(r, L)[0].get("verdict")
    (r.root / "lib" / "code.py").write_text("X = 2\n")
    edit = r.commit("its bytes change")
    seen["edited"] = next((f["detail"] for f in gated(r, L)[0].get("files", []) if f["path"] == "lib/code.py"), None)
    r, L = drift_repo()
    git(r.root, "mv", "lib/code.py", "lib/moved.py")
    r.commit("the accepted file moves, its bytes unchanged")
    seen["moved"] = gated(r, L)[0].get("verdict")
    (r.root / "lib" / "moved.py").write_text("X = 2\n")
    gone = r.commit("its bytes change at the new path")
    seen["gone"] = next((f["detail"] for f in gated(r, L)[0].get("files", []) if f["path"] == "lib/code.py"), None)
    check("DR27 CHANGED and GONE name the commit since which the file has read other bytes: not one before a commit at which "
          "it read unchanged again (deleted then restored, or moved with its bytes)",
          seen == {"deleted": "CHANGED", "restored": "UNCHANGED", "edited": f"since {edit[:12]}", "moved": "UNCHANGED",
                   "gone": f"not at HEAD, since {gone[:12]}"}, seen)
    r = checker_repo()
    (r.root / "lib").mkdir()
    (r.root / "lib" / "code.py").write_text("X = 1\n")
    (r.root / "tests" / "mutants.py").write_text(HARNESS.replace("warrant/engine.py", "lib/code.py"))
    L = claim(r)
    base = r.commit("a claim")
    plain = {"target": L, "verdict": "accept", "commit": base, "tree": git(r.root, "rev-parse", f"{base}^{{tree}}"), **RP.identity(r.root),
             "witnesses": ["q_test:Q1"], "mutants": ["Z1"]}
    put_as(r, CL.CHECKER, plain, [L])
    r.commit("an acceptance naming no files")
    d, rel = gated(r, L)
    again = CL.replay(RP.Repo(r.root), CHECKER_KEY)
    r.commit("accepted again")
    d2, rel2 = gated(r, L)
    bare = Repo()
    check("DR4 an acceptance naming no files compares nothing: UNKNOWN, the claim is not ELIGIBLE, and the checker accepts it again "
          "though its tree is unchanged; a store with no pinned acceptance has no drift answer",
          d.get("verdict") == "UNKNOWN" and rel == D.STALE and len(again) == 1 and d2.get("verdict") == "UNCHANGED" and rel2 == "ELIGIBLE"
          and D.drift(RP.Repo(bare.root).report(), bare.root) == {}, (d, rel, again, d2, rel2))
    def accepted_with(**named):
        """(drift answer, reliance) of a fresh claim whose one acceptance names these members."""
        r = checker_repo()
        (r.root / "lib").mkdir()
        (r.root / "lib" / "code.py").write_text("X = 1\\n")
        (r.root / "tests" / "mutants.py").write_text(HARNESS.replace("warrant/engine.py", "lib/code.py"))
        L = claim(r)
        base = r.commit("a claim")
        put_as(r, CL.CHECKER, {"target": L, "verdict": "accept", "commit": base, "tree": git(r.root, "rev-parse", f"{base}^{{tree}}"),
                               **RP.identity(r.root), "witnesses": ["q_test:Q1"], "mutants": ["Z1"],
                               "closure": CL.CLOSURE, **named}, [L])          # named by the rule: the read reaches pins
        (r.root / "lib" / "code.py").write_text("X = 2\\n")
        r.commit("an acceptance, and the file changes")
        return (r, L, *gated(r, L))
    _, _, empty, empty_rel = accepted_with(files={})
    check("DR8 an acceptance naming an empty list of files is UNKNOWN, not vacuously fresh", empty.get("verdict") == "UNKNOWN"
          and empty_rel == D.STALE, (empty, empty_rel))
    def crashless(files):                # the case is that the read does not crash: a crash is its FAIL, not the file's end
        try:
            return accepted_with(files=files)[2:]
        except Exception as e:           # noqa: BLE001
            return {"crashed": repr(e)}, None
    shaped, shaped_rel = crashless("lib/code.py")
    listed, listed_rel = crashless({"lib/code.py": ["not a blob"]})
    check("DR9 an acceptance whose files are not {path: blob} is UNKNOWN: the read does not crash on a record",
          shaped.get("verdict") == "UNKNOWN" and shaped_rel == D.STALE and listed.get("verdict") == "UNKNOWN" and listed_rel == D.STALE,
          (shaped, listed))
    r, L = drift_repo()
    out = r.home / "written-by-git"
    (r.root / "lib" / "code.py").write_text("X = 3\\n")
    r.commit("the file changes")
    put_as(r, CL.CHECKER, {"target": L, "verdict": "accept", "commit": f"--output={out}", "witnesses": ["q_test:Q1"], "mutants": ["Z1"],
                           "files": {"lib/code.py": "0" * 40}, "closure": CL.CLOSURE}, [L])
    r.commit("an acceptance whose commit is an option")
    d, rel = gated(r, L)
    check("DR10 a commit named by a record reaches Git only as a commit id: one shaped as an option writes nothing",
          not list(r.home.glob("written-by-git*")) and rel == D.STALE, (d, rel))
    r = checker_repo()
    (r.root / "lib").mkdir()
    (r.root / "lib" / "code.py").write_text("X = 1\n")
    (r.root / "tests" / "mutants.py").write_text(HARNESS.replace("warrant/engine.py", "lib/code.py"))
    (r.root / "tests" / "q_test.py").rename(r.root / "tests" / "witness_body.py")
    (r.root / "tests" / "q_test.py").symlink_to("witness_body.py")
    L = claim(r)
    r.commit("a witness reached through an internal link")
    CL.replay(RP.Repo(r.root), CHECKER_KEY)
    r.commit("its acceptance")
    before, rel_before = gated(r, L)
    (r.root / "tests" / "witness_body.py").write_text(TEST.replace("Q2 another", "Q2 changed"))
    r.commit("the file the link ends at changes, the link does not")
    after, rel_after = gated(r, L)
    check("DR11 an acceptance names the file a symlink witness ends at, not only the link: changing it is STALE (Codex finding "
          "f4729a41b788 on #266)", before.get("verdict") == "UNCHANGED" and rel_before == "ELIGIBLE" and after.get("verdict") == "CHANGED"
          and rel_after == D.STALE and {"verdict": "CHANGED", "path": "tests/witness_body.py"}.items() <= next(
              (f for f in after.get("files", []) if f["path"] == "tests/witness_body.py"), {}).items(), (before, after, rel_after))
    r = checker_repo()
    (r.root / "real").mkdir()
    (r.root / "real" / "code.py").write_text("X = 1\n")
    (r.root / "lib").symlink_to("real")
    (r.root / "tests" / "mutants.py").write_text(HARNESS.replace("warrant/engine.py", "lib/code.py"))
    claim(r)
    r.commit("a mutated file reached through a linked directory")
    named = CL.replay(RP.Repo(r.root), CHECKER_KEY)
    check("DR12 a file reached through a linked directory cannot be named, so the checker accepts nothing on it", named == [], named)
    r, L = drift_repo()
    cfg = agent(r)
    req = {"workspace": "w", "op": "around", "target": L}
    g0 = api.call(cfg, "graph", req)["ok"]
    (r.root / "lib" / "code.py").write_text("X = 2\n")
    r.commit("only the head's source changes, the store stays the same")
    g1 = api.call(cfg, "graph", req)["ok"]
    c1 = api.call(cfg, "context", {"workspace": "w", "targets": [L]})["ok"]
    check("DR13 a graph answer's identity binds the checkout that decided STALE: same root, another lens; context names the checkout "
          "too (Codex finding ccc4e8145ed2 on #266)", g0["data"]["node"]["lineage"]["reliance"] == "ELIGIBLE"
          and g1["data"]["node"]["lineage"]["reliance"] == D.STALE and g0["root"] == g1["root"] and g0["lens"] != g1["lens"]
          and c1.get("checkout", {}).get("tree") == git(r.root, "rev-parse", "HEAD^{tree}"), (g0["lens"], g1["lens"], c1.get("checkout")))
    r, L = drift_repo()
    held_bytes = (r.root / "lib" / "code.py").read_text()
    (r.root / "lib" / "code.py").unlink()
    (r.root / "lib" / "code.py").symlink_to(held_bytes)
    (r.root / "lib" / held_bytes).write_text("X = 999\n")
    r.commit("an accepted file becomes a link with the same blob id, reading other bytes")
    same, same_rel = gated(r, L)
    check("DR14 a regular file turned into a symlink with the same blob id is not unchanged (Codex finding ea6300ecf5d5 on #266)",
          same.get("verdict") == "CHANGED" and same_rel == D.STALE, (same, same_rel))
    def named_as(path):
        """(acceptances, drift verdict after lib/code.py changes) of a harness naming the mutated file as `path`."""
        r = checker_repo()
        (r.root / "lib").mkdir()
        (r.root / "lib" / "code.py").write_text("X = 1\n")
        (r.root / "tests" / "mutants.py").write_text(HARNESS.replace("warrant/engine.py", path))
        L = claim(r)
        r.commit("a claim")
        filed = CL.replay(RP.Repo(r.root), CHECKER_KEY)
        r.commit("its acceptance, if any")
        (r.root / "lib" / "code.py").write_text("X = 2\n")
        r.commit("the mutated file changes")
        return len(filed), gated(r, L)[1]
    dotted, absent = named_as("./lib/code.py"), named_as("lib/no-such-file.py")
    check("DR15 a path is pinned as the tree spells it, and a named file not in the tree makes no acceptance: a partial list is never "
          "signed (Codex finding f328c7477354 on #266)", dotted == (1, D.STALE) and absent[0] == 0, (dotted, absent))
    r, L = drift_repo()
    marker = r.home / "ran-repository-code"
    (r.root / "tests" / "mutants.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\nprint('{{}}')\n")
    r.commit("a harness that leaves a mark when it is run")
    api.call(agent(r), "context", {"workspace": "w", "targets": [L]})
    api.call(agent(r), "graph", {"workspace": "w", "op": "around", "target": L})
    d, rel = gated(r, L)
    D.lines({L: d})
    check("DR5 reading context, graph and the drift answer runs no code of the repository's: its mutant harness is not executed "
          "(Codex finding c589d17da0f3 on #266)", not marker.exists() and d.get("verdict") == "UNCHANGED" and rel == "ELIGIBLE", (d, rel))
    r, L = drift_repo()
    (r.root / "lib" / "old.py").write_text("X = 1\n")
    r.commit("a copy of the accepted bytes")
    (r.root / "lib" / "code.py").write_text("X = 2\n")
    r.commit("the accepted file changes")
    _, before = gated(r, L)
    (r.root / "tests" / "mutants.py").write_text(HARNESS.replace("warrant/engine.py", "lib/old.py"))
    r.commit("the harness retargets the mutant to the copy, no acceptance")
    d, after = gated(r, L)
    check("DR6 editing the mutant harness does not refresh an acceptance: the file it ran on still changed (Codex finding "
          "0e7a05e8832c on #266)", before == D.STALE and after == D.STALE and d.get("verdict") == "CHANGED", (before, after, d))
    r, L = drift_repo()
    rp = RP.Repo(r.root)
    base = git(r.root, "rev-parse", "HEAD")
    tree = git(r.root, "rev-parse", "HEAD^{tree}")
    honest = {"target": L, "verdict": "accept", "commit": base, "tree": tree, **RP.identity(r.root), "witnesses": ["q_test:Q1"], "mutants": ["Z1"]}
    true_pin = CL.files_of({"witnesses": ["q_test:Q1"], "mutants": ["Z1"]}, r.root, CL.harness(r.root), CL.blobs(r.root, base))
    put_as(r, CL.CHECKER, dict(honest, files=true_pin), [L])
    r.commit("an acceptance naming what its commit lists")
    kept = refused_code(CL.verify, rp, base)
    new = git(r.root, "rev-parse", "HEAD")
    put_as(r, CL.CHECKER, dict(honest, files={"lib/code.py": "0" * 40}), [L])
    r.commit("an acceptance naming other files")
    why = refused_code(CL.verify, rp, new)
    check("DR7 CI re-executes an acceptance's `files` too: one naming other files than its commit lists for the claim is refused",
          kept is None and why is not None and "names other files" in why, (kept, why))


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


SHARED_TEST = '''import helper


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)


check("%s1 a case", helper.ONE == 1)
'''
SHARED_HARNESS = '''import json, sys
M = {"Z1": ["mutated.py", "tests/q_test.py", ["Q1"]], "Y1": ["mutated.py", "tests/p_test.py", ["P1"]],
     "X1": ["other.py", "tests/s_test.py", ["S1"]]}
if "--matrix" not in sys.argv:
    print(json.dumps(M))
else:
    ids = sys.argv[1:sys.argv.index("--matrix")]
    open(sys.argv[sys.argv.index("--matrix") + 1], "w").write(json.dumps({"rows": [{"id": i, "outcome": "KILLED"} for i in ids]}))
'''


def shared_repo():
    """Three claims accepted by the claims checker: two whose witnesses import one helper (tests/helper.py), one whose
    witness imports nothing of the repository (Codex's counterexample on G14, 2026-11-13)."""
    r = checker_repo()
    (r.root / "other.py").write_text("Y = 0\n")
    (r.root / "tests" / "helper.py").write_text("ONE = 1\n")
    (r.root / "tests" / "q_test.py").write_text(SHARED_TEST % "Q")
    (r.root / "tests" / "p_test.py").write_text(SHARED_TEST % "P")
    (r.root / "tests" / "s_test.py").write_text(TEST.replace("Q1", "S1").replace("Q2", "S2"))
    (r.root / "tests" / "mutants.py").write_text(SHARED_HARNESS)
    Ls = {"q": claim(r, id="V3-3-1"), "p": claim(r, id="V3-3-2", witnesses=["p_test:P1"], mutants=["Y1"]),
          "s": claim(r, id="V3-3-3", witnesses=["s_test:S1"], mutants=["X1"])}
    r.commit("three claims")
    CL.replay(RP.Repo(r.root), CHECKER_KEY)
    r.commit("their acceptances")
    return r, Ls


def freshness_cases():
    r, Ls = shared_repo()
    before = {k: gated(r, L) for k, L in Ls.items()}
    (r.root / "tests" / "helper.py").write_text("ONE = 1  # the shared helper changes\n")
    r.commit("the helper both witnesses import changes")
    after = {k: gated(r, L) for k, L in Ls.items()}
    _, out = cli(r.root, "status", "--json")
    counted = json.loads(out or "{}").get("reliance", {})

    def changed(k):
        return [f["path"] for f in after[k][0].get("files", []) if f["verdict"] == "CHANGED"]
    check("CF1 a claim's acceptance names every file its witnesses load, not only its test and mutated files: a change "
          "to a helper two claims' witnesses import makes both STALE, and the claim whose witness does not import it stays "
          "ELIGIBLE (Codex's counterexample on G14, 2026-11-13)",
          [before[k][1] for k in "qps"] == ["ELIGIBLE"] * 3 and [after[k][1] for k in "qps"] == [D.STALE, D.STALE, "ELIGIBLE"]
          and changed("q") == changed("p") == ["tests/helper.py"], (before, after))
    check("CF5 `warrant status` in a checkout counts those claims STALE as G14 reads them, not ELIGIBLE (observed on master "
          "9e183284: status said ELIGIBLE 612 while 96 claims read STALE)", counted.get(D.STALE) == 2, counted)
    leaves = {k: RP.Repo(r.root).report()["lineages"][L]["leaf"] for k, L in Ls.items()}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        filed = CL.replay(RP.Repo(r.root), CHECKER_KEY)
    recs = RP.Repo(r.root).report()["_recs"]
    check("CF2 the checker runs again only the claims whose files changed: both claims resting on the helper are accepted "
          "again, the third keeps its acceptance and is not run",
          sorted(recs[i]["body"]["target"] for i in filed) == sorted([leaves["q"], leaves["p"]])
          and "2 of 3 backed claims run" in out.getvalue(), (filed, out.getvalue()))
    r, Ls = shared_repo()
    rep = RP.Repo(r.root).report()
    leaf = rep["lineages"][Ls["q"]]["leaf"]
    body = next(x["body"] for x in rep["_recs"].values() if x["kind"] == "attest" and x["body"].get("target") == leaf)
    r2 = checker_repo()
    for f in ("other.py", "tests/helper.py", "tests/q_test.py", "tests/p_test.py", "tests/s_test.py", "tests/mutants.py"):
        shutil.copy(r.root / f, r2.root / f)
    L2 = claim(r2, id="V3-3-1")
    x = r2.commit("a claim")
    put_as(r2, CL.CHECKER, {**{k: v for k, v in body.items() if k != "closure"}, "target": L2, "commit": x,
                            "tree": git(r2.root, "rev-parse", f"{x}^{{tree}}")}, [L2])
    r2.commit("an acceptance whose files carry no closure rule")
    d, rel = gated(r2, L2)
    with contextlib.redirect_stdout(io.StringIO()):
        again = CL.replay(RP.Repo(r2.root), CHECKER_KEY)
    check("CF3 an acceptance that does not say its files are the import closure (one signed before the rule) reads "
          "UNKNOWN and its claim STALE, though every file it names is unchanged: it may omit a module its witness ran; "
          "the checker runs that claim again",
          body.get("closure") == CL.CLOSURE and d.get("verdict") == "UNKNOWN" and rel == D.STALE and len(again) == 1,
          (body.get("closure"), d, rel, again))
    r = checker_repo()
    (r.root / ".gitignore").write_text("/build/\n/tests/ignored.py\n")
    (r.root / "tests" / "ignored.py").write_text("ONE = 1\n")
    (r.root / "tests" / "q_test.py").write_text("import ignored\n" + TEST)
    claim(r)
    r.commit("a witness importing a file the tree does not hold")
    with contextlib.redirect_stdout(io.StringIO()):
        named = CL.replay(RP.Repo(r.root), CHECKER_KEY)
    check("CF4 a module a witness imports that the commit does not hold (an ignored file) cannot be named, so the checker "
          "accepts nothing on that witness", named == [], named)


def drift_impact_cases():
    """`warrant drift --impact` (G14): what a change bears on, from the claims it makes stale."""
    r, L = drift_repo()
    rep = RP.Repo(r.root).report()
    eff = rep["lineages"][L]["effective"]
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "rests on the claim", "serves": [], "evidence": [eff]})
    o2 = r.entity("alice", "obligation@1", {"state": "open", "statement": "serves the first", "serves": [o]})
    free = r.entity("alice", "obligation@1", {"state": "open", "statement": "rests on nothing", "serves": []})
    base = r.commit("two obligations rest on the claim")
    m0 = D.impact(RP.Repo(r.root).report(), r.root)
    (r.root / "README").write_text("unrelated\n")
    (r.root / "lib" / "code.py").write_text("X = 2\n")
    head = r.commit("the mutated file changes, and a file no acceptance names")
    m = D.impact(RP.Repo(r.root).report(), r.root, head, base)
    text = D.impact_lines(m)
    check("DR18 the impact answer names each claim a change made stale and every lineage resting on it, transitively, "
          "and leads with the count; nothing stale reads `impact: 0 affected`",
          D.impact_lines(m0).startswith("impact: 0 affected\n") and [s["lineage"] for s in m["stale"]] == [L]
          and m["affected"] == sorted([o, o2]) and free not in m["affected"]
          and text.startswith("impact: 1 stale claim(s) -> 2 lineage(s) resting on them\n")
          and {"verdict": "CHANGED", "path": "lib/code.py", "detail": f"since {head[:12]}"} in m["stale"][0]["files"], (m0, m, text))
    check("DR19 given BASE, the changed files no acceptance names are listed, since nothing resting on them can be seen",
          m["changed"] == ["README", "lib/code.py"] and m["in_no_acceptance"] == ["README"]
          and "2 file(s), 1 in no acceptance: README" in text, m)
    import importlib.util
    spec = importlib.util.spec_from_file_location("graph_tool", ROOT / "tools" / "graph.py")
    TG = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(TG)
    _, roots, g = TG.impact(RP.Repo(r.root), f"{base}..{head}")
    check("DR25 `tools/graph.py impact BASE..HEAD` gives under `drift` the answer `warrant drift --impact BASE..HEAD` gives: "
          "one definition of what a change makes stale, read from the commits, with no harness run",
          g.get("drift") == m and "claims_by_mutated_file" not in g and roots == {"base": base, "head": head}, (g.get("drift"), m))
    (r.root / "README").write_text("unrelated again\n")
    later = r.commit("another unrelated change")
    m2 = D.impact(RP.Repo(r.root).report(), r.root, later, head)
    check("DR20 a claim already stale at BASE is not the change's: it is listed apart and counts nothing",
          m2["stale"] == [] and [a["lineage"] for a in m2["already_stale"]] == [L] and D.impact_lines(m2).startswith("impact: 0 affected"), m2)
    m3 = D.impact(RP.Repo(r.root).report(), r.root, base)
    check("DR24 the answer is of the commit it names, not of HEAD: at a commit before the change nothing is stale",
          m3["stale"] == [] and m3["head"] == base and D.checkout(r.root, base)["tree"] == git(r.root, "rev-parse", f"{base}^{{tree}}"), m3)
    out = r.home / "written"
    with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
        try:                                 # an exit here must fail DR21, not end the suite before the cases after it
            code = CLI.main(["drift", "--root", str(r.root), f"--impact=--output={out}"])
        except SystemExit as e:
            code = ("exit", e.code)
    try:
        D.resolve(r.root, f"--output={out}")
        shaped = None
    except RP.Failed as e:
        shaped = e.code
    check("DR21 a revision shaped as an option never reaches Git as one: it is refused as no revision and writes nothing",
          shaped == "BAD_REVISION" and code == 2 and "not a revision" in err.getvalue() and not out.exists(), (shaped, code, err.getvalue()))
    r, L = drift_repo()
    rep = RP.Repo(r.root).report()
    v2 = r.put("alice", "entity", dict(rep["_recs"][L]["body"], because="a second version"), "claim@1", lineage=L,
               guard=CL.schema_guard(rep, "backed"))
    r.commit("a second version")
    CL.replay(RP.Repo(r.root), CHECKER_KEY)
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "cites the first version", "serves": [], "evidence": [L]})
    base = r.commit("a second version, accepted; an obligation cites the first")
    (r.root / "lib" / "code.py").write_text("X = 3\n")
    head = r.commit("the mutated file changes")
    rep = RP.Repo(r.root).report()
    m = D.impact(rep, r.root, head, base)
    check("DR22 what rests on a claim is read from every version of it: a record citing an earlier version than the "
          "effective one is affected, and the claim's own versions are not", rep["lineages"][L]["effective"] == v2
          and [s["lineage"] for s in m["stale"]] == [L] and m["affected"] == [o], m)
    other = Repo()
    far = other.entity("bob", "obligation@1", {"state": "open", "statement": "in another store, cites the effective version",
                                              "serves": [], "evidence": [v2]})
    first = other.entity("bob", "obligation@1", {"state": "open", "statement": "in another store, cites the first version",
                                                "serves": [], "evidence": [L]})
    home = {"repositories": {"here": {"path": str(r.root)}, "there": {"path": str(other.root)}}}
    m = D.impact(RP.Repo(r.root).report(), r.root, head, base, A.home_readings(home))
    text = D.impact_lines(m)
    check("DR23 with Home's stores, a record in another store resting on any version of a stale claim is named with its "
          "store, and this checkout's own store is not counted twice",
          m["stores"] == ["there"] and [(e["store"], e["lineage"]) for e in m["stale"][0]["elsewhere"]] == sorted([("there", far), ("there", first)])
          and text.startswith("impact: 1 stale claim(s) -> 1 lineage(s) resting on them -> 1 other store(s)"), (m, text))
    r, L = drift_repo()
    here = r.entity("alice", "obligation@1", {"state": "open", "statement": "here, cites the claim", "serves": [], "evidence": [L]})
    other = Repo()
    far = other.entity("bob", "obligation@1", {"state": "open", "statement": "there, cites the record here", "serves": [], "evidence": [here]})
    back = r.entity("alice", "obligation@1", {"state": "open", "statement": "here, cites the record there", "serves": [], "evidence": [far]})
    base = r.commit("a chain through two stores")
    (r.root / "lib" / "code.py").write_text("X = 2\n")
    head = r.commit("the mutated file changes")
    home = {"repositories": {"here": {"path": str(r.root)}, "there": {"path": str(other.root)}}}
    m = D.impact(RP.Repo(r.root).report(), r.root, head, base, A.home_readings(home))
    alone = D.impact(RP.Repo(r.root).report(), r.root, head, base)
    check("DR28 with Home's stores the walk goes on through every store, this one too: a record elsewhere resting on a record "
          "here that rests on the claim is named, and so is a record here resting on it (Codex finding 72595e2154fd)",
          [(e["store"], e["lineage"]) for e in (m["stale"] or [{}])[0].get("elsewhere", [])] == [("there", far)]
          and m["affected"] == sorted([here, back]) and alone["affected"] == [here], (m, alone))
    env = os.environ.get("WARRANT_HOME")
    os.environ["WARRANT_HOME"] = str(r.home / "config" / "drift-home.json")
    try:
        H.save(dict(H.empty(), repositories={"here": {"path": str(r.root)}, "there": {"path": str(other.root)}}))
        def answered():                  # a refusal or crash reads as no answer, so the case fails on its own line
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                try:
                    CLI.main(["drift", "--root", str(r.root), f"--impact={base}..{head}", "--across", "--json"])
                    return json.loads(out.getvalue())
                except (SystemExit, Exception) as e:         # noqa: BLE001
                    return {"crashed": repr(e)}
        a = answered()
        other.entity("bob", "obligation@1", {"state": "open", "statement": "there, cites the claim", "serves": [], "evidence": [L]})
        b = answered()
        H.save(dict(H.empty(), repositories={"here": {"path": str(r.root)}, "there": {"path": str(other.root)},
                                             "gone": {"path": str(r.home / "no-such-store")}}))
        c = answered()
    finally:
        if env is None:
            os.environ.pop("WARRANT_HOME", None)
        else:
            os.environ["WARRANT_HOME"] = env
    readings = {x.name: x for x in A.home_readings({"repositories": {"here": {"path": str(r.root)}, "there": {"path": str(other.root)}}})}
    rep = RP.Repo(r.root).report()
    D.gate(rep, r.root, head)
    q = {"query": "impact", "head": head, "base": base, "across": True}
    want = A.identity({"here": rep, "there": readings["there"].rep}, [], rep["code"], None, q) if hasattr(A, "identity") else None
    check("DR29 an answer with Home's stores binds every store it read as `across` does: a record added in another store "
          "changes its root, a store that cannot be read is named and changes it too",
          "crashed" not in a and "crashed" not in b and "crashed" not in c
          and a["data"]["stale"][0]["elsewhere"] != b["data"]["stale"][0]["elsewhere"] and a["root"] != b["root"]
          and (b["root"], b["lens"]) == want and [u["store"] for u in c["data"].get("unavailable", [])] == ["gone"]
          and c["root"] != b["root"], (a.get("root"), b.get("root"), want, c.get("data", {}).get("unavailable")))


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
    v = Repo()
    for key in ("G10", "EXP-ADOPT-1", "G2", "G", "9 lives"):
        v.entity("alice", "goal@1", {"state": "open", "key": key, "text": f"goal {key}"})
    try:
        heads = [ln.split(" (")[0][3:] for ln in RM.view(RP.Repo(v.root).report()).splitlines() if ln.startswith("## ")]
    except ValueError as e:
        heads = f"view raised {e}"
    check("P02b the roadmap view names every goal whatever its key: G<number> ones in the order of their numbers, then "
          "the others by their key (a goal keyed EXP-ADOPT-1 ended the view: int() of what was left of the key)",
          heads == ["G2", "G10", "9 lives", "EXP-ADOPT-1", "G"], heads)
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


def chain_join_cases():
    """A writer's chain forks taken in by its own `joined` attests (warrant.chains, `warrant join`)."""
    r = Repo()
    base = r.store.lines()
    a = r.entity("alice", "obligation@1", {"state": "open", "statement": "a", "serves": []})   # branch one
    one = r.store.lines()
    r.store.write_lines(base)
    b = r.entity("alice", "obligation@1", {"state": "open", "statement": "b", "serves": []})   # branch two, same prev
    r.store.add_lines(one)                                                                      # the merge holds both
    view = lambda: E.View(r.store.snapshot(), r.trust, r.profile)                              # noqa: E731
    _, out = cli(r.root, "status", "--json")
    st = json.loads(out or "{}")
    check("CJ1 a writer that filed on two branches forks its chain, and the fork is open until the writer takes it in",
          st.get("chain_forks") == ["alice"] and st.get("chain_forks_open") == ["alice"]
          and len(CH.loose(view(), "alice")) == 1 and CH.loose(view(), "alice")[0] in (a, b), (st.get("chain_forks"), st.get("chain_forks_open")))
    loose = CH.loose(view(), "alice")[0]
    r.attest("alice", loose)                                             # her own acceptance is not a join
    r.put("carol", "attest", {"verdict": CH.JOINED, "target": loose}, refs=[loose])      # nor is another's `joined`
    check("CJ3 only the writer's own `joined` attest, on the line its head continues, takes a branch in",
          [f[0] for f in CH.forks(view())["open"]] == ["alice"] and CH.loose(view(), "alice") == [loose], CH.forks(view()))
    old = os.environ.get("WARRANT_KEY")
    os.environ["WARRANT_KEY"] = KEYS["alice"].seed_hex()     # a seed named by --key lies in the operator's home
    try:
        code, out = cli(r.root, "join", "--actor", "alice")
        filed = (json.loads(out or "{}") or {}).get("joined", [])
        _, out = cli(r.root, "status", "--json")
        st = json.loads(out or "{}")
        code2, out2 = cli(r.root, "join", "--actor", "alice")
    finally:
        os.environ.pop("WARRANT_KEY")
        if old is not None:
            os.environ["WARRANT_KEY"] = old
    rec = r.store.snapshot().lines.get(filed[0] if filed else "", [{"record": {}}])[0]["record"]
    check("CJ2 `warrant join` files one `joined` attest per loose tip, chained on the head; the fork stays listed, no "
          "longer open, and a second join files nothing",
          code == 0 and len(filed) == 1 and rec.get("body") == {"verdict": CH.JOINED, "target": loose}
          and st.get("chain_forks") == ["alice"] and st.get("chain_forks_open") == [] and code2 == 0
          and json.loads(out2 or "{}").get("joined") == [], (code, filed, st.get("chain_forks_open"), out2))
    r = Repo()                  # Codex F1 on #346 at 6662c57d: a branch whose body its schema refuses is still in the chain
    base = r.store.lines()
    r.entity("alice", "obligation@1", {"state": "open", "statement": "valid branch", "serves": []})
    one = r.store.lines()
    r.store.write_lines(base)
    bad = r.put("alice", "entity", {"state": "unknown", "statement": "invalid branch", "serves": []}, schema="obligation@1")
    r.store.add_lines(one)
    old = os.environ.get("WARRANT_KEY")
    os.environ["WARRANT_KEY"] = KEYS["alice"].seed_hex()
    try:
        code, out = cli(r.root, "join", "--actor", "alice")
    finally:
        os.environ.pop("WARRANT_KEY")
        if old is not None:
            os.environ["WARRANT_KEY"] = old
    after = E.View(r.store.snapshot(), r.trust, r.profile)
    check("CJ4 a branch whose record its schema refuses is still the writer's (§7 reads the signed chain): join takes it in",
          bad in after.bad and code == 0 and len((json.loads(out or "{}") or {}).get("joined", [])) == 1
          and not CH.forks(after)["open"], (code, out[-200:], CH.forks(after)))


def cli_cases():
    s = Repo()
    lines = s.store.lines()
    (s.dot / "records.jsonl").write_bytes(b"{  " + lines[0][1:] + b"".join(lines[1:]))
    _, out = cli(s.root, "fmt")
    doc = json.loads(out or "{}")
    check("K12 `warrant fmt` reports the order it leaves: a rejected line stays, and the store is not canonical "
          "(6d6bb700: it printed canonical true; moved from core_test T15, whose CLI import put the whole package in the "
          "import closure of every core claim)", doc.get("canonical") is False and doc.get("rejected") == 1, doc)
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
    stranger = K.Key.from_seed_hex("0b" * 32)
    (r.home / "stranger.seed").write_text(stranger.seed_hex())
    me = f"key:{stranger.public}"
    file = lambda kind, body, *more: cli(r.home, "put", "--store", "repo/.warrant", "--kind", kind, "--actor", me, "--key", "stranger.seed", *more, json.dumps(body))
    before = r.store.lines()
    finding = {"target": d, "statement": "P2 x", "severity": "P2", "what": "w", "where": [], "commit": "a" * 40, "tree": "b" * 40}
    filed, out = file("challenge", finding, "--schema", "finding@1", "--ref", d)
    rep = r.report()
    got = json.loads(out or "{}").get("record")
    check("K10 `warrant put` files a challenge under its own key's name with no key bound; it reads as a thesis",
          filed == 0 and got in rep["challenges"] and not rep["challenges"][got]["counted"], (filed, out[-200:]))
    before = r.store.lines()
    other, _ = file("entity", {"state": "open", "statement": "s", "serves": []}, "--schema", "obligation@1")
    check("K11 ... and refuses any other kind under such a name, writing nothing", other != 0 and r.store.lines() == before, other)


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


def impact_cases():
    """impact over two reports: a lineage gone from the later one is read in the earlier one, and a blob of the later
    store with its address hides nothing, a blob being no node (Codex's finding 917018f33b0a on #213, on Warrant 2's graph)."""
    from warrant import graph as G
    r = Repo()
    x = r.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    rep0 = r.report()
    rec = next(json.loads(ln)["record"] for ln in r.store.lines() if R.rid(json.loads(ln)["record"]) == x)
    other = Repo()
    blob = other.store.put_blob(JCS.canon(rec))
    other.entity("alice", "obligation@1", {"state": "open", "statement": "t", "serves": []}, refs=[blob])
    rep1 = other.report()
    try:
        got = next(e for e in G.impact(rep0, rep1)["lineages"] if e["lineage"] == x)
    except (KeyError, StopIteration) as e:
        got = repr(e)
    check("DR17 a lineage removed by the later report is read in the earlier one, whatever else has its address",
          blob == x and x not in {n[0] for n in rep1["graph"]["nodes"]}
          and isinstance(got, dict) and got["gone"] and got["schema"] == "obligation@1" and got["state"] == "open", got)


def differential_cases():
    """warrant.differential (roadmap G12): the published release n and this package on one store."""
    r = Repo(git_init=True)
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

    def release(n, accepted):
        """main --release 1.0 with N_PYTHON's answers made here: the reports of this store, `accepted`, version `n`."""
        out = io.StringIO()
        answers = {DF.RELEASE_SCRIPT: lambda args: {"release": args[0], "accepted": accepted},
                   DF.VERSION_SCRIPT: lambda args: n, DF.SCRIPT: lambda args: as_n(DF.head_report(r.root))}
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            old_pr = DF.published
            DF.published = lambda python, root, script, *args, run=None: answers[script](args)
            try:
                code = DF.main(["--python", "py", "--root", str(r.root), "--release", "1.0"])
            finally:
                DF.published = old_pr
        return code, json.loads(out.getvalue())
    r.commit("n 0.1")
    git(r.root, "tag", "v0.1")
    code, verdict = release("0.1", [])
    check("D08 --release refuses a release whose reports agree (here SAME but for the release) when no release duty "
          "of it is accepted", code == 1 and verdict["verdict"] == "REFUSED" and verdict["differs"] == []
          and verdict["release"]["accepted"] == [], verdict)
    records = r.dot / "records.jsonl"
    before = set(records.read_bytes().splitlines())
    r.entity("alice", "obligation@1", {"state": "open", "statement": "n's own", "serves": []})
    spare = r.blob(b"n's own")
    line, = set(records.read_bytes().splitlines()) - before
    r.commit("n 0.2")
    git(r.root, "tag", "v0.2")
    kept = records.read_bytes()
    stages = {"kept": release("0.2", [closed])}
    records.write_bytes(b"".join(x + b"\n" for x in kept.splitlines() if x != line))
    stages["line"] = release("0.2", [closed])
    records.write_bytes(kept)
    held = (r.dot / "blobs" / spare).read_bytes()
    (r.dot / "blobs" / spare).unlink()
    stages["blob"] = release("0.2", [closed])
    (r.dot / "blobs" / spare).write_bytes(held)
    stages["no tag"] = release("0.3", [closed])
    stages["not a version"] = release("0.2^{}", [closed])         # git would read v0.2^{} as v0.2's commit
    git(r.root, "branch", "v0.4")                                   # a branch, not a tag (Codex finding 9b3268821dd4)
    stages["a branch"] = release("0.4", [closed])
    got = {k: (c, v["verdict"], (v.get("release") or {}).get("history")) for k, (c, v) in stages.items()}
    check("D09 --release refuses a release whose store lost a record line or a blob of the store at n's tag (v + n's "
          "version): n's history is challenged, never rewritten; without that tag (a branch of its name is no tag), or when n names no public version (the tag's only "
          "source, read as a git revision), no verdict is made (UNMADE)",
          got == {"kept": (0, "SAME", {"of": "refs/tags/v0.2", "records": 0, "blobs": 0}),
                  "line": (1, "REFUSED", {"of": "refs/tags/v0.2", "records": 1, "blobs": 0}),
                  "blob": (1, "REFUSED", {"of": "refs/tags/v0.2", "records": 0, "blobs": 1}),
                  "no tag": (2, "UNMADE", None), "not a version": (2, "UNMADE", None),
                  "a branch": (2, "UNMADE", None)}, got)

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


def ledger_cases():
    """warrant.graph.ledger, the witness ledger (roadmap a997b9e40f55; Codex challenge 80330b9974ca on its #170 closure:
    a refutation was credited across closures). A replay counts for the challenge's own target only."""
    from warrant import graph as G
    r = Repo()
    a, b = (r.entity("alice", "obligation@1", {"state": "done", "statement": s, "serves": []},
                     lineage=r.entity("alice", "obligation@1", {"state": "open", "statement": s, "serves": []})) for s in "ab")
    for v in (a, b):
        r.attest("bob", v)
    ca = r.put("eve", "challenge", {"target": a, "statement": "a is wrong"}, refs=[a])
    cb = r.put("eve", "challenge", {"target": b, "statement": "b is wrong"}, refs=[b])
    r.put("carol", "attest", {"target": ca, "verdict": "reproduces", "on": a}, refs=[ca, a])
    r.put("carol", "attest", {"target": cb, "verdict": "reproduces", "on": a}, refs=[cb, a])    # run on another version
    r.put("eve", "attest", {"target": cb, "verdict": "reproduces", "on": b}, refs=[cb, b])      # by a non-replayer
    recs = lambda: {i: e[0]["record"] for i, e in r.store.snapshot().lines.items()}
    rows = G.ledger(r.report(), recs())
    check("WL1 the witness ledger: an acceptance is refuted, and a challenge credited, only by a replayer's `reproduces` on "
          "that challenge's own target; one run on another version, or by a non-replayer, refutes and credits nothing",
          rows.get("bob") == {"accepted": sorted([a, b]), "refuted": [[a, ca]], "challenged": [], "replayed": []}
          and rows.get("eve") == {"accepted": [], "refuted": [], "challenged": sorted([ca, cb]), "replayed": [ca]}, rows)
    # Codex challenge on c1cace09dd7c: an acceptance made after the refutation, citing the challenge and its replay,
    # was read as refuted; "later" was not checked.
    c2 = r.entity("alice", "obligation@1", {"state": "done", "statement": "c", "serves": []},
                  lineage=r.entity("alice", "obligation@1", {"state": "open", "statement": "c", "serves": []}))
    cc = r.put("eve", "challenge", {"target": c2, "statement": "c is wrong"}, refs=[c2])
    run = r.put("carol", "attest", {"target": cc, "verdict": "reproduces", "on": c2}, refs=[cc, c2])
    r.put("bob", "attest", {"target": c2, "verdict": "accept", "note": "knowing the refutation"}, refs=[c2, cc, run])
    late = G.ledger(r.report(), recs()).get("bob", {})
    check("WL2 an acceptance that cites the challenge and its replay was made after the refutation: it is not refuted",
          c2 in late.get("accepted", []) and [c2, cc] not in late.get("refuted", []) and late.get("refuted") == [[a, ca]], late)
    c3 = r.entity("alice", "obligation@1", {"state": "done", "statement": "d", "serves": []},
                  lineage=r.entity("alice", "obligation@1", {"state": "open", "statement": "d", "serves": []}))
    cd = r.put("eve", "challenge", {"target": c3, "statement": "d is wrong"}, refs=[c3])
    r.put("carol", "attest", {"target": cd, "verdict": "reproduces", "on": c3}, refs=[cd, c3])
    r.attest("bob", c3)                                          # cites nothing, dated after the replay
    late = G.ledger(r.report(), recs()).get("bob", {})
    check("WL3 ... and one dated after the replay, citing nothing, is not refuted either: `at` orders what no citation does",
          c3 in late.get("accepted", []) and [c3, cd] not in late.get("refuted", []), late)
    # Codex challenge caae1baae65e on e18c26ee0bf9: citing an unreplayed challenge exempted a later refutation (F1),
    # and a replay citing the acceptance, with an earlier `at`, was read as earlier (F2).
    def done(s):
        return r.entity("alice", "obligation@1", {"state": "done", "statement": s, "serves": []},
                        lineage=r.entity("alice", "obligation@1", {"state": "open", "statement": s, "serves": []}))
    e = done("e")
    ce = r.put("eve", "challenge", {"target": e, "statement": "e is wrong, not yet reproduced"}, refs=[e])
    ae = r.put("bob", "attest", {"target": e, "verdict": "accept"}, refs=[e, ce])
    r.put("carol", "attest", {"target": ce, "verdict": "reproduces", "on": e}, refs=[ce, e, ae])
    late = G.ledger(r.report(), recs()).get("bob", {})
    check("WL4 an acceptance citing a challenge not yet reproduced is refuted by a replay that comes after it: knowing an "
          "objection is not knowing its reproduction", [e, ce] in late.get("refuted", []), late)
    f = done("f")
    af = r.put("bob", "attest", {"target": f, "verdict": "accept"}, refs=[f], at=1800000100)
    cf = r.put("eve", "challenge", {"target": f, "statement": "f is wrong"}, refs=[f, af], at=1800000101)
    r.put("carol", "attest", {"target": cf, "verdict": "reproduces", "on": f}, refs=[cf, f, af], at=1800000050)
    late = G.ledger(r.report(), recs()).get("bob", {})
    check("WL5 a replay that cites the acceptance comes after it whatever its `at` says: a citation orders before any date",
          [f, cf] in late.get("refuted", []) and not r.report()["problems"], late)
    g = done("g")
    cg = r.put("eve", "challenge", {"target": g, "statement": "g is wrong"}, refs=[g], at=1800000200)
    rg = r.put("carol", "attest", {"target": cg, "verdict": "reproduces", "on": g}, refs=[cg, g], at=1800000210)
    note = r.entity("alice", "obligation@1", {"state": "open", "statement": "g refuted", "serves": []}, refs=[rg])
    r.put("bob", "attest", {"target": g, "verdict": "accept"}, refs=[g, note], at=1800000150)
    late = G.ledger(r.report(), recs()).get("bob", {})
    check("WL6 ... and an acceptance citing the replay, through a record that cites it, comes after it whatever its own "
          "`at` says: it is not refuted", g in late.get("accepted", []) and [g, cg] not in late.get("refuted", []), late)
    # Codex challenge 049f0ec2b8c5 on 39a921e41990: an attest that did not match the guard (scope=partial) was compared
    # with the replay, and its acceptor read as refuted though the one acceptance that counted cites the replay.
    guard = {"quorum": 1, "roles": ["roadmap/acceptor"], "match": {"verdict": "accept", "scope": "full"}, "requires": []}
    for early in ("partial", "full"):
        q = Repo()
        o = q.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
        v = q.entity("alice", "obligation@1", {"state": "done", "statement": "s", "serves": []}, lineage=o, guard=guard)
        q.put("bob", "attest", {"target": v, "verdict": "accept", "scope": early}, refs=[v])
        cq = q.put("eve", "challenge", {"target": v, "statement": "wrong"}, refs=[v])
        rq = q.put("carol", "attest", {"target": cq, "verdict": "reproduces", "on": v}, refs=[cq, v])
        q.put("bob", "attest", {"target": v, "verdict": "accept", "scope": "full"}, refs=[v, rq])
        rows = G.ledger(q.report(), {i: e[0]["record"] for i, e in q.store.snapshot().lines.items()}).get("bob", {})
        if early == "partial":
            partial = (rows, v in rows.get("accepted", []) and rows.get("refuted") == [])
        else:
            full = (rows, rows.get("refuted") == [[v, cq]])
    check("WL7 only an attest that counts toward the version's guard (every member of its match) is an acceptance: one "
          "short of the match, before the replay, refutes nobody; one that matches does",
          partial[1] and full[1], (partial[0], full[0]))


def grounded_cases():
    """warrant.graph.grounded: minds' Grounded over a report. A lineage is ELIGIBLE on a ground that is not: only the
    transitive answer says so."""
    from warrant import graph as G
    r = Repo()
    a0 = r.entity("alice", "obligation@1", {"state": "open", "statement": "the ground", "serves": []})
    a = r.entity("alice", "obligation@1", {"state": "done", "statement": "the ground", "serves": []}, lineage=a0)
    r.attest("bob", a)
    b0 = r.entity("alice", "obligation@1", {"state": "open", "statement": "rests on it", "serves": [], "evidence": [a0]}, refs=[a0])
    rep = r.report()
    first = G.grounded(rep, b0)
    r.put("alice", "challenge", {"target": a, "statement": "the ground is wrong"}, refs=[a])     # its own actor: counted
    rep = r.report()
    after, lin = G.grounded(rep, b0), rep["lineages"][b0]["reliance"]
    check("GR1 a version resting on a lineage whose reliance fell is not grounded, while its own lineage still reads "
          "ELIGIBLE; the ground is named, read through the lineage's effective version",
          first["grounded"] and lin == "ELIGIBLE" and not after["grounded"] and after["failing"] == [[a, "RELIANCE CHALLENGED"]],
          (first, lin, after))
    c0 = r.entity("alice", "obligation@1", {"state": "open", "statement": "one", "serves": []})
    d0 = r.entity("alice", "obligation@1", {"state": "open", "statement": "two", "serves": []})
    c1 = r.entity("alice", "obligation@1", {"state": "open", "statement": "one", "serves": [], "evidence": [d0]}, lineage=c0, refs=[d0])
    r.entity("alice", "obligation@1", {"state": "open", "statement": "two", "serves": [], "evidence": [c0]}, lineage=d0, refs=[c0])
    got = G.grounded(r.report(), c1)
    check("GR2 grounds that rest on each other (two lineages citing each other's latest version) are not grounded: "
          "the least fixed point", not got["grounded"] and {w for _, w in got["failing"]} == {"CYCLE"}, got)
    check("GR3 the version asked about must be its lineage's effective version", G.grounded(r.report(), c0)["failing"][:1] == [[c0, "NOT_EFFECTIVE"]],
          G.grounded(r.report(), c0))
    q = Repo()
    g = q.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "a goal"})
    o = q.entity("alice", "obligation@1", {"state": "open", "statement": "answers it", "answers": g, "serves": []}, refs=[g])
    met = q.entity("alice", "goal@1", {"state": "met", "key": "G1", "text": "a goal"}, lineage=g, refs=[o])
    q.attest("bob", met)
    rq = RP.Repo(q.root).report()
    answered = G.grounded(rq, o)
    check("GR4 the goal an obligation answers is a direction, not a ground: a met goal citing the obligation that answers "
          "it makes no CYCLE (the analysis session, 2026-11-13: minds read 88 failing on 18 items for this alone)",
          rq["lineages"][g]["effective"] == met and not any(w == "CYCLE" for _, w in answered["failing"]),
          (rq["lineages"][g]["effective"] == met, answered))

def narrow_cases():
    """The analysis session, 2026-11-13 (#364): every one of 136 claims read STALE after one change to warrant/gate.py,
    because the widest case of a witness file set its closure for all its claims (core_test T15 imported the CLI) and
    claims.py imported the gate. A change to the gate stales no claim a core witness alone backs."""
    from warrant import imports as IM
    from warrant.pins import blobs
    rep = RP.Repo(ROOT).report()
    known, tree = CL.harness(ROOT), blobs(ROOT, "HEAD")
    core = [b for b in CL.live(rep).values() if b["state"] == "backed" and b["witnesses"]
            and all(w.startswith("core_test:") for w in b["witnesses"])]
    named = [sorted(CL.files_of(b, ROOT, known, tree) or {}) for b in core[:5]]
    rows = {f: (size, n) for f, size, n in CL.closures(ROOT, rep)}
    check("CF6 a change to the gate stales no claim that core witnesses alone back: core_test's import closure and "
          "claims.py's hold no warrant/gate.py, and `claims closures` names each witness file's closure and the claims on it",
          core and all(names and "warrant/gate.py" not in names for names in named)
          and "warrant/gate.py" not in IM.closure(ROOT, "warrant/claims.py")
          and rows.get("tests/core_test.py", (0, 0))[0] and rows["tests/core_test.py"][0] < 12,
          (len(core), [len(n) for n in named], rows.get("tests/core_test.py")))

def resolve_cases():
    """W7 (docs/HOME.md): each cited hash gets one state over Home's stores and their clones' Git, the minds chain's
    cells among them; bytes that do not hash to their name are refused, never MISSING."""
    from warrant import home as H
    from warrant import resolve as RS
    a, b, chain = Repo(name="s0fractal/a"), Repo(name="s0fractal/b"), Repo(name="s0fractal/chain")
    held = b.entity("alice", "obligation@1", {"state": "open", "statement": "in b", "serves": []})
    cell = b"VAR1 a cell of a minds chain"
    cid = hashlib.sha256(cell).hexdigest()
    git(chain.root, "init", "-q", "-b", "main")
    (chain.root / "cas" / "cells" / cid[:2]).mkdir(parents=True)
    (chain.root / "cas" / "cells" / cid[:2] / cid[2:]).write_bytes(cell)
    chain.commit("a chain")
    git(chain.root, "update-ref", "refs/vars/heads/minds", "HEAD")
    nowhere = "ab" * 32
    own = a.entity("alice", "obligation@1", {"state": "open", "statement": "own", "serves": []})
    a.entity("alice", "goal@1", {"state": "open", "key": "Q1", "text": "cites"}, refs=[own, held, cid, nowhere])
    doc = H.empty()
    for name, r in (("a", a), ("b", b), ("chain", chain)):
        doc = H.add_repository(doc, str(r.root), name)
    out = RS.answer(doc)
    by = {r["id"]: r for r in out["rows"]}
    asked = RS.answer(doc, [cid, nowhere])
    check("RV1 a cited hash is PRESENT in its own store, RESOLVED in another store of Home or a clone's minds chain (its "
          "cell's bytes hash to its name), MISSING otherwise; the answer binds what it read (root, lens) and says it is "
          "not complete",
          own not in by and by.get(held, {}).get("where") == "store:b" and by.get(cid, {}).get("state") == "RESOLVED"
          and str(by.get(cid, {}).get("where", "")).startswith("git:chain:refs/vars/heads/minds:cas/cells/")
          and by.get(nowhere, {}).get("state") == "MISSING" and out["completeness"] == "UNATTESTED"
          and len(out["root"]) == 64 and len(out["lens"]) == 64
          and {r["id"]: r["state"] for r in asked["rows"]} == {cid: "RESOLVED", nowhere: "MISSING"},
          (by, asked["rows"]))
    bad = "cd" * 32
    (chain.root / "cas" / "cells" / bad[:2]).mkdir(parents=True, exist_ok=True)
    (chain.root / "cas" / "cells" / bad[:2] / bad[2:]).write_bytes(b"bytes that are not cd...")
    chain.commit("a cell under a name its bytes do not hash to")
    git(chain.root, "update-ref", "refs/vars/heads/minds", "HEAD")
    try:
        RS.answer(doc, [bad])
        refused = None
    except RS.Mismatch as e:
        refused = str(e)
    check("RV2 bytes found under a name they do not hash to are refused (BYTES_MISMATCH), never MISSING: a transport is not "
          "trusted", refused is not None and "does not hash" in refused, refused)

def voices_cases():
    """W4's stranger path in the core command: `warrant init --voices` and `warrant say`, with nothing but the package."""
    from warrant import commons as CM
    r = Repo()
    d = r.home / "my voices"
    d.mkdir()
    keep = CM.SEEDS
    CM.SEEDS = r.home / "seeds"
    try:
        code_init, out_init = cli(d, "init", "--voices")
        doc = json.loads((d / ".warrant" / "v3.json").read_text()) if (d / ".warrant" / "v3.json").exists() else {}
        target = "ab" * 32
        code_say, out_say = cli(d, "say", target, "the claim ignores the cold start", "--as", "stranger-1")
        said = json.loads(out_say or "{}")
        snap = Store(d / ".warrant").snapshot()
        rec = next((e[0]["record"] for e in snap.lines.values()), {})
        before = r.store.lines()
        code_proj, _ = cli(r.root, "say", target, "into a project's store", "--as", "stranger-1")
        code_proj_init, _ = cli(r.root, "init", "--voices")
    finally:
        CM.SEEDS = keep
    check("VS1 `warrant init --voices` makes a store of voices (it trusts nobody, gives nobody a role) and `warrant say` files "
          "a challenge into it under the agent's own key, `key:<public>`, with the package alone; pointed at a project's store, "
          "both refuse and nothing is appended (W4: the published package had no such command)",
          code_init == 0 and CM.is_commons(doc) and doc.get("repository") == "voices/my-voices" and code_say == 0
          and said.get("actor", "").startswith("key:") and rec.get("kind") == "challenge" and rec.get("actor") == said.get("actor")
          and rec.get("body", {}).get("target") == target and code_proj == 1 and code_proj_init != 0 and r.store.lines() == before,
          (code_init, doc, code_say, out_say, rec, code_proj, code_proj_init))

def _issue(body, number=7, login="octocat", uid=583231, kind="User", action="opened", **issue):
    """An `issues` event as GitHub delivers it, with what the bridge reads and members it must ignore."""
    return {"action": action, "repository": {"full_name": "acme/widget", "html_url": "https://evil.example/r"},
            "issue": dict({"number": number, "title": "MARKER-title", "html_url": "https://evil.example/issue",
                           "user": {"login": login, "id": uid, "type": kind}, "body": body}, **issue)}


def _form(target, stance, statement):
    return f"### Record\n\n{target}\n\n### Stance\n\n{stance}\n\n### Statement\n\n{statement}"


def bridge_cases():
    """The bridge (warrant/bridge.py): an issue opened through the form becomes one record in a store that trusts the
    bridge's key alone; everything else is refused in words of the bridge's own, and nothing is filed."""
    from warrant import bridge as BR
    from warrant import commons as CM
    from warrant import shapes as SH
    r = Repo()
    key, other_key = K.Key.from_seed_hex("0b" * 32), K.Key.from_seed_hex("0c" * 32)
    d = r.home / "voices"
    target, second = "ab" * 32, "cd" * 32
    said = "the claim ignores the cold start\r\n\r\n### Stance\r\n\r\nsupport\r\n\r\n### Record\r\n\r\n" + second
    raw = _form(target, "objection", said).replace("\n\n", "\r\n\r\n")
    first = BR.file(d, _issue(raw), key, at=1_900_000_000)
    again = BR.file(d, _issue(raw), key, at=1_900_000_005)
    support = BR.file(d, _issue(_form(second, "support", "  we rely on this  "), number=8, login="dependabot[bot]", uid=49699333, kind="Bot"),
                      key, at=1_900_000_010)
    dot = d / ".warrant"
    doc = json.loads((dot / "v3.json").read_text())
    snap = Store(dot).snapshot()
    recs = {i: e[0]["record"] for i, e in snap.lines.items()}
    a, b = recs.get(first.get("filed"), {}), recs.get(support.get("filed"), {})
    rep = E.assess(snap, doc["trust"], doc["profile"])
    nodes = {n[0]: n[1:] for n in rep["graph"]["nodes"]}
    check("BR1 an issue opened through the form becomes one record in the bridge's store, which trusts the one name "
          "github-bridge bound to the bridge's key and gives nobody a role: an objection is a challenge, a support an attest "
          "with stance support and no verdict member; each names the record id of the form, the statement as text (a "
          "statement that imitates the form's other fields stays the statement), and what the bridge states of GitHub: "
          "login, id, kind of account, repository, issue number, the issue's address built from those two (the event's own "
          "address is not copied) and the SHA-256 of the body as delivered; the store's own assessment admits both as signed",
          BR.is_bridge_store(doc, key.public) and doc["profile"]["roles"] == {} and list(doc["trust"]["keys"]) == ["github-bridge"]
          and (a.get("kind"), a.get("actor"), a.get("refs")) == ("challenge", "github-bridge", [target])
          and a.get("body") == {"target": target, "stance": "objection", "statement": said.replace("\r\n", "\n"),
                                "github": {"login": "octocat", "id": 583231, "account": "User", "repository": "acme/widget", "issue": 7,
                                           "url": "https://github.com/acme/widget/issues/7",
                                           "body_sha256": hashlib.sha256(raw.encode()).hexdigest()}}
          and (b.get("kind"), b.get("refs")) == ("attest", [second]) and b.get("body", {}).get("stance") == "support"
          and "verdict" not in b.get("body", {"verdict": 1}) and b.get("body", {}).get("statement") == "we rely on this"
          and b.get("body", {}).get("github", {}).get("login") == "dependabot[bot]"
          and [nodes.get(x, [None] * 5)[4] for x in (first.get("filed"), support.get("filed"))] == ["SIGNED", "SIGNED"],
          (doc, a, b, nodes))
    check("BR2 one record per issue: the same issue filed again adds no line and answers with the first record, marked as "
          "already filed", first.get("already") is False and again == dict(first, already=True) and len(recs) == 2, (first, again, len(recs)))
    lines = Store(dot).lines()
    marker = "MARKER-7f3a"
    bad = {
        "an edit": _issue(_form(target, "objection", marker), number=20, action="edited"),
        "a pull request": _issue(_form(target, "objection", marker), number=21, pull_request={"url": "x"}),
        "no form": _issue(marker, number=22),
        "text before the form": _issue(marker + "\n\n" + _form(target, "objection", "x"), number=23),
        "an id in upper case": _issue(_form("AB" * 32, "objection", marker), number=24),
        "an id of 63 digits": _issue(_form("a" * 63, "objection", marker), number=25),
        "an id and a newline": _issue(_form(target + "\n", "objection", marker), number=26),
        "a stance of accept": _issue(_form(target, "accept", marker), number=27),
        "an empty statement": _issue(_form(target, "objection", "  \n "), number=28),
        "a statement too long": _issue(_form(target, "objection", "x" * (BR.STATEMENT_MAX + 1)), number=29),
        "the form's empty answer": _issue(_form(target, "objection", "_No response_"), number=30),
        "a login with a space": _issue(_form(target, "objection", marker), number=31, login="octo cat " + marker),
        "a login and a newline": _issue(_form(target, "objection", marker), number=32, login="octocat\n"),
        "an id that is true": _issue(_form(target, "objection", marker), number=33, uid=True),
        "an organization": _issue(_form(target, "objection", marker), number=34, kind="Organization"),
        "a number of zero": _issue(_form(target, "objection", marker), number=0),
        "a body that is no text": _issue(None, number=35),
    }
    bad["a repository of another shape"] = dict(_issue(_form(target, "objection", marker), number=36), repository={"full_name": "acme/widget/" + marker})
    got = {}
    for name, ev in bad.items():
        try:
            got[name] = ("FILED", BR.file(d, ev, key, at=1_900_000_020))
        except BR.Refused as e:
            got[name] = ("REFUSED", BR.comment(why=str(e)))
        except Exception as e:                                  # anything else is the bridge breaking on an issue's text
            got[name] = (type(e).__name__, str(e))
    check("BR3 anything but the form as opened is refused and nothing is filed: an edit, a pull request, text that is not "
          "the form or stands before it, a record id in upper case, of 63 digits or with a newline after it, a stance the "
          "form does not offer, a statement that is empty, the form's own empty answer or longer than the limit, an author "
          "whose login, id or kind of account is not a GitHub account's, an issue number of zero, a repository name of "
          "another shape; the answer for the issue is in the bridge's words and repeats no text of the issue",
          all(k == "REFUSED" and marker not in v and "MARKER" not in v for k, v in got.values()) and Store(dot).lines() == lines,
          {n: v for n, v in got.items() if v[0] != "REFUSED" or "MARKER" in v[1]})
    ok_ev = _issue(_form(target, "objection", "into another's store"), number=40)
    commons = r.home / "commons"
    CM.init(commons)
    foreign = r.home / "foreign"
    BR.init(foreign, other_key)
    roles = r.home / "roles"
    (roles / ".warrant").mkdir(parents=True)
    (roles / ".warrant" / "v3.json").write_text(json.dumps(dict(BR.doc_for(key.public), profile={"warrant": "profile/3", "roles": {"pr/acceptor": ["github-bridge"]}})))
    shared = r.home / "shared"
    (shared / ".warrant").mkdir(parents=True)
    two = BR.doc_for(key.public)
    two["trust"]["keys"]["mallory"] = [other_key.public]
    (shared / ".warrant" / "v3.json").write_text(json.dumps(two))
    before = {str(x): (Store(x / ".warrant").lines() if (x / ".warrant" / "records.jsonl").exists() else None, r.store.lines())
              for x in (commons, foreign, roles, shared)}
    broke = []
    for x in (r.root, commons, foreign, roles, shared):
        try:
            BR.file(x, ok_ev, key, at=1_900_000_030)
            broke.append("FILED")
        except BR.Broken:
            broke.append("BROKEN")
        except BR.Refused:
            broke.append("REFUSED")
    after = {str(x): (Store(x / ".warrant").lines() if (x / ".warrant" / "records.jsonl").exists() else None, r.store.lines())
             for x in (commons, foreign, roles, shared)}
    check("BR4 the bridge writes into its own store alone: a project's store, a commons, a bridge's store bound to another "
          "key, a store of its shape that gives github-bridge a role and one that trusts a second name are each the "
          "bridge's failure (Broken, never an answer on the issue) and no line is appended to any of them",
          broke == ["BROKEN"] * 5 and before == after, (broke, before == after))
    ev_file, out = r.home / "event.json", io.StringIO()
    ev_file.write_text(json.dumps(ok_ev))
    keep = os.environ.pop(BR.SEED_ENV, None)
    try:
        codes, outs = [], []
        for seed, argv in ((None, ["file", "--event", str(ev_file), "--store", str(d)]),
                           ("0b" * 32, ["file", "--event", str(ev_file), "--store", str(d), "--reader", "https://example.test/reader.html",
                                         "--voices", "https://example.test/v/?a=1&b=2"]),
                           ("0b" * 32, ["file", "--event", str(r.home / "missing.json"), "--store", str(d)]),
                           ("0b" * 32, ["public"])):
            os.environ.pop(BR.SEED_ENV, None)
            if seed:
                os.environ[BR.SEED_ENV] = seed
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                codes.append(BR.main(argv))
            outs.append(out.getvalue().strip())
        ev_file.write_text(json.dumps(bad["a stance of accept"]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            codes.append(BR.main(["file", "--event", str(ev_file), "--store", str(d)]))
        outs.append(out.getvalue().strip())
    finally:
        os.environ.pop(BR.SEED_ENV, None)
        if keep is not None:
            os.environ[BR.SEED_ENV] = keep
    done, refused = json.loads(outs[1] or "{}"), json.loads(outs[4] or "{}")
    check("BR5 the command a workflow runs: without the seed in the environment it files nothing (status 2); with it, the "
          "issue's voice is filed (status 0) and the answer for the issue names the record's id, the target and the reader's "
          "address with the bridge's store beside it (its address as one query value), and says the account signed nothing; an event file that cannot be read is status 2; a refused "
          "issue is status 3 with its answer; `public` prints the key the store binds, and the seed is in no output; the "
          "record is filed although the chain's last record is ahead of this machine's clock, at that record's time",
          codes == [2, 0, 2, 0, 3] and Store(dot).snapshot().lines.get(done.get("filed"), [{}])[0].get("record", {}).get("at") == 1_900_000_010 and SH.hex64(done.get("filed")) and done["filed"] in done.get("comment", "")
          and "https://example.test/reader.html?with=https%3A%2F%2Fexample.test%2Fv%2F%3Fa%3D1%26b%3D2 " in done.get("comment", "") and "not the account's signature" in done.get("comment", "")
          and outs[3] == key.public and "Nothing was filed" in refused.get("comment", "") and not any("0b" * 32 in o for o in outs),
          (codes, outs))

    form = (ROOT / ".github" / "ISSUE_TEMPLATE" / "voice.yml").read_text()
    fields = re.findall(r"^  - type: (\w+)\n    id: (\w+)\n    attributes:\n      label: (.+)$", form, re.M)
    options = re.findall(r"^        - (.+)$", form, re.M)
    required = form.count("    validations:\n      required: true\n")
    delivered = "\n\n".join(f"### {label}\n\n{value}" for (_, _, label), value in zip(fields, (target, options[0] if options else "", "as the form delivers it")))
    try:
        through = BR.voice(_issue(delivered, number=50))
    except BR.Refused as e:
        through = str(e)
    told = (ROOT / "site" / "llms.txt").read_text().split("```\n")
    try:
        as_told = BR.voice(_issue(told[1].replace("RECORD_ID", target), number=51)) if len(told) == 3 else "no one block"
    except BR.Refused as e:
        as_told = str(e)
    check("BR6 the form on disk is the form the bridge reads: its fields are an input `record`, a dropdown `stance` and a "
          "textarea `statement`, labelled Record, Stance and Statement in that order, each required, the stances offered "
          "are objection and support and nothing else, and a body built from those labels as GitHub delivers a form's "
          "answers is filed; the body site/llms.txt tells an agent to write, with a record id in it, is filed too",
          fields == [("input", "record", "Record"), ("dropdown", "stance", "Stance"), ("textarea", "statement", "Statement")]
          and options == ["objection", "support"] == list(BR.STANCES) and required == 3
          and isinstance(through, tuple) and through[0] == "challenge" and through[1]["statement"] == "as the form delivers it"
          and isinstance(as_told, tuple) and as_told[0] == "challenge" and as_told[1]["target"] == target,
          (fields, options, required, through, as_told))


def _bridge_step(home):
    """The filing step of .github/workflows/voice-bridge.yml as a script, byte for byte, and what runs it here: a bare
    repository standing for GitHub's (Git rewrites the step's address to it), `gh` that keeps each answer in a file,
    `python` that is this interpreter, `sleep` that does not wait, and `git` that, when RACE names a script, runs it once
    just before the first push. (run(event number, seed, race) -> (status, answer, output), the bare repository)."""
    text = (ROOT / ".github" / "workflows" / "voice-bridge.yml").read_text()
    step = text.split("      - name: File the voice, publish the store, answer the issue\n")[1].split("        run: |\n")[1]
    script = "\n".join(line[10:] if line.startswith("          ") else line for line in step.splitlines()) + "\n"
    real_git = shutil.which("git")
    binp, origin, ws = home / "bin", home / "origin.git", home / "ws"
    for d in (binp, ws, home / "answers", home / "events"):
        d.mkdir(parents=True)
    os.symlink(ROOT, ws / "code")
    subprocess.run([real_git, "init", "-q", "--bare", str(origin)], check=True)
    (home / "step.sh").write_text(script)
    (home / "gitconfig").write_text(f'[url "{origin}"]\n\tinsteadOf = https://github.com/acme/widget.git\n[init]\n\tdefaultBranch = scratch\n')
    tools = {"gh": f'#!/bin/sh\nif [ "$1" = "issue" ]; then cp "$7" "{home}/answers/$3.md"; fi\n',
             "python": f'#!/bin/sh\nexec "{sys.executable}" -B "$@"\n', "sleep": "#!/bin/sh\nexit 0\n",
             "git": f'#!/bin/sh\nif [ -n "$RACE" ] && [ ! -e "$RACE.done" ]; then for a in "$@"; do if [ "$a" = "push" ]; then : > "$RACE.done"; '
                    f'RACE_NOW="$RACE"; RACE= sh "$RACE_NOW" >/dev/null 2>&1; fi; done; fi\nexec "{real_git}" "$@"\n'}
    for name, body in tools.items():
        (binp / name).write_text(body)
        (binp / name).chmod(0o755)

    def run(event, seed="0b" * 32, race=None, extra=None):
        n = event["issue"]["number"]
        (home / "events" / f"{n}.json").write_text(json.dumps(event))
        work = Path(tempfile.mkdtemp(dir=home))
        env = {"PATH": f"{binp}:/usr/bin:/bin", "HOME": str(home), "GIT_CONFIG_GLOBAL": str(home / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "github-bridge", "GIT_AUTHOR_EMAIL": "b@invalid", "GIT_COMMITTER_NAME": "github-bridge",
               "GIT_COMMITTER_EMAIL": "b@invalid", "READER": "https://example.test/reader.html", "WARRANT_BRIDGE_SEED": seed, "GH_TOKEN": "x",
               "GITHUB_EVENT_PATH": str(home / "events" / f"{n}.json"), "GITHUB_REPOSITORY": "acme/widget", "RUNNER_TEMP": str(work),
               "GITHUB_STEP_SUMMARY": str(work / "summary.md"), "GITHUB_WORKSPACE": str(ws), "RACE": str(race or ""), **(extra or {})}
        (home / "answers" / f"{n}.md").unlink(missing_ok=True)
        r = subprocess.run(["bash", str(home / "step.sh")], cwd=work, env=env, capture_output=True, text=True, timeout=120)
        ans = home / "answers" / f"{n}.md"
        return r.returncode, ans.read_text() if ans.exists() else "", r.stdout + r.stderr, env
    return run, origin, real_git


def bridge_step_cases():
    """The workflow's own step (voice-bridge.yml), run as written: what Codex found on #392 was in the workflow, where no
    case looked. A concurrency group kept one run pending and cancelled the one before it; now runs go side by side and
    a push the branch refuses is tried again from the branch as it is."""
    r = Repo()
    home = r.home / "runner"
    home.mkdir()
    run, origin, git_ = _bridge_step(home)
    target = "ab" * 32

    def show(*args):
        return subprocess.run([git_, "--git-dir", str(origin), *args], capture_output=True, text=True).stdout

    def records():
        return [json.loads(x)["record"] for x in show("show", "voices:.warrant/records.jsonl").splitlines()]
    rc5, a5, o5, env = run(_issue(_form(target, "objection", "the first voice; $(touch PWNED) `touch PWNED2`"), number=5))
    first = records()
    # issue 7's run meets a branch that moved: issue 99's whole run lands between its filing and its push
    race = home / "race.sh"
    (home / "events" / "99.json").write_text(json.dumps(_issue(_form(target, "support", "the run that got there first"), number=99)))
    racer = dict(env, GITHUB_EVENT_PATH=str(home / "events" / "99.json"), RUNNER_TEMP=str(home / "race-tmp"),
                 GITHUB_STEP_SUMMARY=str(home / "race-tmp" / "summary.md"), RACE="")
    (home / "race-tmp").mkdir()
    (home / "race-work").mkdir()
    race.write_text("cd " + str(home / "race-work") + " && env -i " + " ".join(f"{k}='{v}'" for k, v in racer.items()) + f" bash {home / 'step.sh'}\n")
    rc7, a7, o7, _ = run(_issue(_form(target, "objection", "the voice that had to try again"), number=7), race=race)
    both = records()
    doc = json.loads(show("show", "voices:.warrant/v3.json") or "{}")
    snap = E.assess  # the published store, assessed under its own rules
    work = Path(tempfile.mkdtemp(dir=home))
    subprocess.run([git_, "clone", "-q", "--branch", "voices", str(origin), str(work / "v")], check=False, capture_output=True)
    rep = snap(Store(work / "v" / ".warrant").snapshot(), doc.get("trust", {}), doc.get("profile", {})) if (work / "v" / ".warrant").exists() else {}
    by_issue = {x["body"]["github"]["issue"]: x for x in both}
    id7 = next((i for i, e in Store(work / "v" / ".warrant").snapshot().lines.items() if e[0]["record"]["body"]["github"]["issue"] == 7), "")
    check("BR7 the workflow's filing step, run as the YAML writes it against a repository standing for GitHub's: the first "
          "issue makes the branch voices (the store and a README) and is answered with its record's id; a statement "
          "holding shell text runs nothing; and when another issue's run publishes between this run's filing and its "
          "push, the refused push is tried again from the branch as it is then: both voices are on the branch, each "
          "once, both signed in the store's own assessment with none rejected and no fork, and the answer names the "
          "record that was published, not the one of the refused try",
          (rc5, rc7) == (0, 0) and len(first) == 1 and sorted(by_issue) == [5, 7, 99] and len(both) == 3
          and (race.parent / "race.sh.done").exists() and rep.get("rejected") == {} and rep.get("basis", {}).get("SIGNED") == 3
          and rep.get("chains", {}).get("forks") == [] and bool(id7) and f"`{id7}`" in a7 and show("ls-tree", "-r", "--name-only", "voices").split()
          == [".warrant/records.jsonl", ".warrant/v3.json", "README.md"] and not list(home.rglob("PWNED*")),
          (rc5, rc7, len(first), sorted(by_issue), rep.get("rejected"), rep.get("basis"), o7[-400:]))
    tip = show("rev-parse", "voices").strip()
    rc_bad, a_bad, _, _ = run(_issue(_form(target, "accept", "x"), number=8))
    rc_again, a_again, _, _ = run(_issue(_form(target, "objection", "the voice that had to try again"), number=7))
    rc_none, a_none, _, _ = run(_issue(_form(target, "objection", "no key"), number=9), seed="")
    rc_other, a_other, o_other, _ = run(_issue(_form(target, "objection", "another key"), number=10), seed="0c" * 32)
    wf = (ROOT / ".github" / "workflows" / "voice-bridge.yml").read_text()
    check("BR7 what publishes nothing: a refused issue is answered with the refusal, an issue filed before is answered "
          "with its first record, a run with no seed says the bridge has no key yet, and a run whose key the branch's "
          "store does not bind fails with no answer; the branch does not move in any of them. The workflow names no "
          "concurrency group, at its top or on a job: a group would cancel the run that waited",
          (rc_bad, rc_again, rc_none) == (0, 0, 0) and rc_other != 0 and "Nothing was filed" in a_bad and f"`{id7}`" in a_again
          and "nothing was filed now" in a_again and "no key yet" in a_none and a_other == "" and show("rev-parse", "voices").strip() == tip
          and "concurrency:" not in wf.replace("# No concurrency group.", ""),
          (rc_bad, rc_again, rc_none, rc_other, a_bad[:60], a_again[:80], a_none[:60], a_other, o_other[-200:]))


def merged_cases():
    """The observation of a merge says how it came about: a solo merge says that no second family reviewed it."""
    import argparse
    r = Repo()
    git(r.root, "init", "-q", "-b", "master")
    r.commit("base")
    rows = {}
    for n, msg in ((1, "Merge pull request #1 (solo: claude, the window passed)\n\nmerge-on-acceptance: solo: head version v by "
                       "claude at x, one model family, its window passed since 1 with no veto; head h; base b."),
                   (2, "Merge pull request #2 (accepted by codex)\n\nmerge-on-acceptance: head version v accepted by codex at x."),
                   (3, "Merge branch 'feature'")):
        git(r.root, "checkout", "-q", "-b", f"f{n}")
        (r.root / f"f{n}.txt").write_text(str(n))
        r.commit(f"change {n}")
        git(r.root, "checkout", "-q", "master")
        git(r.root, "merge", "-q", "--no-ff", f"f{n}", "-m", msg)
        merge = git(r.root, "rev-parse", "HEAD")
        rp = RP.Repo(r.root)
        name = rp.config()[2]
        r.put("alice", "entity", {"state": "open", "repository": name, "pr": n, "title": "t", "serves": []}, "pr-head@1")
        rows[n] = RV._pr_record(rp, RP.Repo(r.root).report(), argparse.Namespace(cmd="merged", pr=n, merge=merge, actor="alice"),
                                name)["body"].get("how")
    check("MR1 the merge observation names how the merge came about from its commit: the gate's solo merge says solo (no "
          "second family reviewed it), the gate's merge on an acceptance says accepted, anything else hand",
          rows == {1: "solo", 2: "accepted", 3: "hand"}, rows)

OBSERVER_AT = 1_794_522_625          # 2026-11-13: the owner leaves every guard (docs/REPOSITORY.md, "The owner as observer")
OWNER_ROLES = {"before": {"roadmap/acceptor": ["codex", "s0fractal"], "schema/author": ["claude", "codex", "s0fractal"],
                          "roadmap/owner": ["s0fractal"], "challenger": None},
               "after": {"roadmap/acceptor": ["codex"], "schema/author": ["claude", "codex"],
                         "roadmap/owner": ["claude", "codex", "s0fractal"], "challenger": ["s0fractal"]}}


def observer_cases():
    """The owner's transition to observer is a change of the profile only: his word may lower reliance, never raise it.
    Assessed as of the transition, under the profile with his former roles and under the profile as it is, no lineage
    of this repository's store changes its state or its reliance, no version its guard, no challenge whether it counts."""
    rp = RP.Repo(ROOT)
    trust, profile, _ = rp.config()

    def under(which):
        roles = {k: v for k, v in profile["roles"].items() if k not in OWNER_ROLES[which]}
        roles.update({k: v for k, v in OWNER_ROLES[which].items() if v is not None})
        rep = E.View(rp.store.snapshot(), trust, dict(profile, roles=roles), as_of=OBSERVER_AT).report()
        return ({L: (x["state"], x["reliance"]) for L, x in rep["lineages"].items()}, {v: x["guard"] for v, x in rep["versions"].items()},
                {c: x["counted"] for c, x in rep["challenges"].items()})
    before, after = under("before"), under("after")
    now = {k: v for k, v in profile["roles"].items() if k in OWNER_ROLES["after"]}
    check("OB1 the owner leaves roadmap/acceptor and schema/author, holds challenger, and claude and codex join him as "
          "roadmap/owner: assessed as of the transition, no lineage changes state or reliance, no version its guard",
          now == OWNER_ROLES["after"] and before == after and len(before[0]) > 600,
          (now, [L for L in before[0] if before[0][L] != after[0].get(L)][:5]))


class FakeBoard:
    """A project board in memory, answering the calls warrant.board makes (two items a page, to walk the pages)."""

    def __init__(self, kind="user"):
        self.fields, self.items, self.mutations, self.readme, self.n, self.kind, self.asked = {}, [], [], None, 0, kind, []

    def _id(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    def call(self, query, v):
        asked = next((k for k in BD.OWNERS if query == BD.PROJECT.replace("OWNER", k)), None)
        if asked:
            self.asked.append(asked)
            if asked != self.kind:
                raise RP.Failed("GITHUB", f"Could not resolve to a {asked} with the login")       # as GitHub answers the other kind
            start = int(v["after"] or 0)
            page = self.items[start:start + 2]
            def values(it):
                kind = {"TEXT": "text", "NUMBER": "number", "DATE": "date", "SINGLE_SELECT": "name"}
                return [{kind[self.fields[n]["dataType"]]: x, "field": {"name": n}} for n, x in it["values"].items()]
            return {asked: {"projectV2": {"id": "P", "title": "t", "public": False, "readme": self.readme,
                    "fields": {"nodes": list(self.fields.values())},
                    "items": {"pageInfo": {"hasNextPage": start + 2 < len(self.items), "endCursor": str(start + 2)},
                              "nodes": [{"id": it["id"], "isArchived": it["archived"],
                                         "content": {"id": it["draft"], "title": it["title"], "body": it["body"]},
                                         "fieldValues": {"nodes": values(it)}} for it in page]}}}}
        self.mutations.append(query)
        if query is BD.ADD_FIELD:
            f = {"id": self._id("F"), "name": v["name"], "dataType": v["type"]}
            if v["options"]:
                f["options"] = [{"id": self._id("O"), "name": o["name"]} for o in v["options"]]
            self.fields[v["name"]] = f
            return {"createProjectV2Field": {"projectV2Field": f}}
        if query is BD.ADD_ITEM:
            it = {"id": self._id("I"), "draft": self._id("D"), "title": v["title"], "body": v["body"], "archived": False,
                  "values": {"Status": "Todo"} if "Status" in self.fields else {}}      # as a new project's own workflow does
            self.items.append(it)
            return {"addProjectV2DraftIssue": {"projectItem": {"id": it["id"], "content": {"id": it["draft"]}}}}
        if query is BD.SET_TEXT:
            it = next(i for i in self.items if i["draft"] == v["draft"])
            it["title"], it["body"] = v["title"], v["body"]
        elif query in (BD.SET_FIELD, BD.CLEAR):
            it = next(i for i in self.items if i["id"] == v["item"])
            f = next(f for f in self.fields.values() if f["id"] == v["field"])
            if query is BD.CLEAR:
                it["values"].pop(f["name"], None)
            elif "singleSelectOptionId" in v["value"]:
                it["values"][f["name"]] = next(o["name"] for o in f["options"] if o["id"] == v["value"]["singleSelectOptionId"])
            else:
                it["values"][f["name"]] = next(iter(v["value"].values()))
        elif query is BD.ARCHIVE:
            next(i for i in self.items if i["id"] == v["item"])["archived"] = True
        elif query is BD.DESCRIBE:
            self.readme = v["readme"]
        return {}


def board_cases():
    """warrant.board: the roadmap as rows of a project board, one way. The board's side is FakeBoard here: no case
    reaches GitHub, so what GitHub's API answers to these calls is not held by any of them."""
    hostile = "@octocat see #1 and ```` four ticks ```` <script>alert(1)</script> [x](javascript:alert(2))"
    r = Repo()
    g = r.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "a goal"})
    ob = lambda text, **kw: r.entity("alice", "obligation@1", dict({"state": "open", "statement": text, "answers": g, "serves": []}, **kw))  # noqa: E731
    done = lambda text, o, **kw: r.entity("alice", "obligation@1", dict({"state": "done", "statement": text, "answers": g, "serves": []}, **kw), lineage=o)  # noqa: E731
    o_open = ob(hostile)
    o_claimed = ob("claimed")
    done("claimed", o_claimed, refs=["s0fractal/warrant#7", "merged as abc after s0fractal/warrant#8"])
    o_accepted = ob("accepted")
    r.attest("bob", done("accepted", o_accepted))
    o_released = ob("released")
    r.entity("dave", "obligation@1", {"state": "released", "statement": "released", "answers": g, "serves": [], "residual": ["no longer wanted"]}, lineage=o_released)
    o_challenged = ob("challenged")
    closing = done("challenged", o_challenged)
    r.put("bob", "challenge", {"target": closing, "statement": "it does not hold"}, refs=[closing])
    o_fork = ob("forked")
    done("forked", o_fork)
    r.entity("alice", "obligation@1", {"state": "open", "statement": "forked, otherwise", "answers": g, "serves": []}, lineage=o_fork)
    man = BD.manifest([r.root], reader="https://example.test/reader.html")
    by = {x["id"]: x for x in man["rows"]}
    want = {g: BD.OPEN, o_open: BD.OPEN, o_claimed: BD.CLAIMED, o_accepted: BD.ACCEPTED, o_released: BD.RELEASED,
            o_challenged: BD.CHALLENGED, o_fork: BD.FORKED}
    check("BD1 one row per goal and obligation lineage, its status from the records: open; claimed, not accepted (a "
          "closing version waits for its acceptor); accepted; released; challenged (a counted challenge stands against "
          "its leaf); forked", {i: x["status"] for i, x in by.items()} == want and by[o_claimed]["waits_for"] != ""
          and by[o_accepted]["accepted_by"] == "bob" and by[o_claimed]["goal"] == "G1", {i[:8]: x["status"] for i, x in by.items()})
    again = BD.manifest([r.root], reader="https://example.test/reader.html")
    rep = RP.Repo(r.root).report()
    r.entity("alice", "obligation@1", {"state": "open", "statement": "one more", "answers": g, "serves": []})
    later = BD.manifest([r.root], reader="https://example.test/reader.html")
    check("BD2 the manifest is a function of the store: the same store gives the same bytes; it names the store's snapshot "
          "and assessment; its digest is the digest of its stores and rows; one more record gives another digest",
          JCS.canon(man) == JCS.canon(again) and man["stores"][0]["snapshot"] == rep["snapshot"]
          and man["stores"][0]["assessment"] == rep["assessment"]
          and man["digest"] == JCS.doc_id({k: v for k, v in man.items() if k != "digest"}) and later["digest"] != man["digest"],
          (man["digest"][:12], later["digest"][:12]))
    body, title = by[o_open]["body"], by[o_open]["title"]
    inside, fence, outside = False, None, []
    for line in body.splitlines():
        ticks = len(line) - len(line.lstrip("`"))
        if not inside and ticks >= 3 and line[ticks:] == "text":
            inside, fence = True, ticks
        elif inside and line == "`" * fence:
            inside = False
        elif not inside:
            outside.append(line)
    links = [x for x in by[o_claimed]["body"].splitlines() if x.startswith("- https://")]
    check("BD3 what a record says is data on the board: its statement lies inside a fence longer than its longest run of "
          "backticks, no word of it outside one; its title holds no `@` followed by a name; and only a reference of the "
          "exact shape owner/name#N becomes a link",
          "@octocat" in body and "octocat" not in "\n".join(outside) and "<script>" not in "\n".join(outside)
          and "`````text" in body and "@octocat" not in title and "@\u200boctocat" in title
          and links == ["- https://github.com/s0fractal/warrant/pull/7"], (title, outside[:6], links))

    fb = FakeBoard()
    fb.fields["Status"] = {"id": "FS", "name": "Status", "dataType": "SINGLE_SELECT", "options": [{"id": "OT", "name": "Todo"}]}
    board = BD.read_board(fb.call, "o", 1)
    first_plan = BD.plan(man, board, "2026-11-13")
    reads_only = fb.mutations == []
    did = BD.sync(man, board, fb.call, "2026-11-13")
    names = {n for n, _, _ in BD.FIELDS} | {BD.SYNCED, "Status"}
    made = {it["values"].get(BD.ID): it for it in fb.items}
    fb.mutations.clear()
    second = BD.plan(man, BD.read_board(fb.call, "o", 1), "2026-11-13")
    BD.sync(man, BD.read_board(fb.call, "o", 1), fb.call, "2026-11-14")
    check("BD4 a first sync makes the fields and one item a row, each cell the row's; reading and planning change nothing; "
          "a second sync of the same manifest finds nothing to do and makes no call that changes the board",
          reads_only and sorted(first_plan["create"]) == sorted(by) and set(fb.fields) == names and set(made) == set(by)
          and all(made[i]["values"]["Warrant status"] == by[i]["status"] and made[i]["title"] == by[i]["title"]
                  and made[i]["values"][BD.SYNCED] == "2026-11-13" and made[i]["values"].get("Standing challenges", 0) == by[i]["challenges"]
                  and "Status" not in made[i]["values"]
                  for i in by)
          and first_plan["describe"] is True and second["describe"] is False
          and second["create"] == [] and second["update"] == {} and second["archive"] == [] and fb.mutations == []
          and man["digest"][:12] in (fb.readme or ""), (sorted(did["create"])[:2], second, len(fb.mutations)))
    org, refusal = FakeBoard("organization"), None
    try:
        BD.sync(man, BD.read_board(org.call, "o", 1), org.call, "2026-11-13")
    except RP.Failed as e:
        refusal = e.code
    fb.asked.clear()
    BD.read_board(fb.call, "o", 1)                    # one read of a user's board of several pages
    check("BD6 a board of an organization and a board of a user are read alike: the organization is asked first, and every "
          "page after the first asks only the kind that answered", refusal is None and len(org.items) == len(by) and set(org.asked) == {"organization"}
          and len(fb.asked) > 3 and fb.asked[:2] == ["organization", "user"] and set(fb.asked[2:]) == {"user"},
          (refusal, org.asked[:3], fb.asked[:5]))
    clash, code = FakeBoard(), None
    clash.fields["Store"] = {"id": "FX", "name": "Store", "dataType": "REPOSITORY"}
    try:
        BD.sync(man, BD.read_board(clash.call, "o", 1), clash.call, "2026-11-13")
    except RP.Failed as e:
        code = e.code
    check("BD7 a board whose field bears one of our names and another type refuses the sync before anything is changed",
          code == "FIELD" and clash.mutations == [] and clash.items == [], (code, len(clash.mutations)))
    made[o_accepted]["values"]["Warrant status"] = BD.OPEN            # a hand edit on the board: no record says so
    made[o_claimed]["title"] = "done, trust me"
    fb.items.append({"id": "X", "draft": "DX", "title": "a person's own note", "body": "", "archived": False, "values": {"Status": "Todo"}})
    made[o_open]["values"]["Status"] = "Todo"                         # the board's own column, set again on a row of ours
    smaller = dict(man, rows=[x for x in man["rows"] if x["id"] != o_fork])
    edited = BD.plan(smaller, BD.read_board(fb.call, "o", 1), "2026-11-15")
    BD.sync(smaller, BD.read_board(fb.call, "o", 1), fb.call, "2026-11-15")
    note = next(i for i in fb.items if i["id"] == "X")
    check("BD5 a hand edit is no record: the plan names exactly the cells that differ and the sync puts them back; a row "
          "the manifest no longer holds is archived; an item with no Warrant ID is not ours, is counted and is left as it was",
          edited["update"] == {o_accepted: ["Warrant status"], o_claimed: ["title"], o_open: ["Status"]} and edited["archive"] == [o_fork]
          and edited["foreign"] == 1 and made[o_accepted]["values"]["Warrant status"] == BD.ACCEPTED
          and made[o_claimed]["title"] == by[o_claimed]["title"] and made[o_fork]["archived"] is True
          and note["title"] == "a person's own note" and note["archived"] is False and note["values"] == {"Status": "Todo"}
          and "Status" not in made[o_open]["values"],
          (edited["update"], edited["archive"], edited["foreign"]))


# The block the adoption experiment measured (experiments/adoption/entry/AGENTS.block.md at 9bcf1f3386ec, branch
# exp/adoption, s0fractal/warrant#385): its sha256. `warrant init` writes it byte for byte.
ENTRY_BLOCK_SHA = "9114d7c650b0fb1a85d41cc39d43d798e37ec0a6fc3f66a18c14eb11138d4fea"
BEGIN, END = "<!-- warrant:begin -->", "<!-- warrant:end -->"


def _init(root, *args):
    """`warrant init ARGS` run in `root` (a repository's store: .warrant), its JSON answer, or the refusal's code."""
    out = io.StringIO()
    with contextlib.chdir(root), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            rc = CLI.main(["init", *args])
        except SystemExit as e:                  # a flag this version does not know
            rc = e.code
    try:
        return rc, json.loads(out.getvalue()) if out.getvalue().strip() else {}
    except ValueError:
        return rc, {}


def _text(p):
    return p.read_text() if p.exists() else ""


def _block(text):
    """The text between the marks, or None."""
    if BEGIN not in text or END not in text:
        return None
    return text.split(BEGIN + "\n", 1)[1].split(END, 1)[0]


def entry_cases():
    def fresh():
        d = Path(tempfile.mkdtemp())
        git(d, "init", "-q", "-b", "master")
        git(d, "remote", "add", "origin", "https://github.com/acme/widget.git")
        return d
    r = fresh()
    rc, first = _init(r)
    agents, claude = _text(r / "AGENTS.md"), _text(r / "CLAUDE.md")
    v3 = json.loads((r / ".warrant" / "v3.json").read_text()) if (r / ".warrant" / "v3.json").exists() else {}
    try:
        with contextlib.chdir(r):
            st = CLI.status(CLI._parser().parse_args(["status"]))
    except CLI.Refused:
        st = {}
    before = {p: _text(r / p) for p in ("AGENTS.md", "CLAUDE.md", ".warrant/v3.json")}
    rc2, second = _init(r)
    after = {p: _text(r / p) for p in before}
    blk = _block(agents)
    exp = ROOT / "experiments" / "adoption" / "entry" / "AGENTS.block.md"
    check("IN1 `warrant init` in a repository leaves the next agent what the adoption experiment measured (R1 fired: 0 of "
          "18 used the records without it, 18 of 18 with it): AGENTS.md holding the block byte for byte between marks, "
          "CLAUDE.md importing it, and a .warrant/v3.json naming the repository with an empty trust and profile, so "
          "`warrant status` reads the store; a second init writes nothing and changes no byte",
          rc == 0 and blk is not None and hashlib.sha256(blk.encode()).hexdigest() == ENTRY_BLOCK_SHA
          and (not exp.exists() or exp.read_text() == blk) and claude == "@AGENTS.md\n"
          and v3.get("repository") == "acme/widget" and v3.get("trust", {}).get("keys") == {} and st.get("repository") == "acme/widget"
          and first.get("wrote") == [".warrant/v3.json", "AGENTS.md", "CLAUDE.md", ".warrant/agent.json", ".mcp.json"]
          and bool(st) and "no actor holds a role" in CLI.render(st) and second.get("wrote") == [] and before == after,
          (rc, first, second, blk and hashlib.sha256(blk.encode()).hexdigest(), claude, v3))
    r = fresh()
    mine = "# Ours\n\nKeep this.\n"
    (r / "AGENTS.md").write_text(mine)
    (r / "CLAUDE.md").write_text("Our rules.")
    _init(r)
    a1, c1 = _text(r / "AGENTS.md"), _text(r / "CLAUDE.md")
    stale = a1.replace("Only `ELIGIBLE` may be relied on.", "Anything may be relied on.") + "Our tail.\n"
    (r / "AGENTS.md").write_text(stale)
    _, again = _init(r)
    a2 = _text(r / "AGENTS.md")
    check("IN2 an AGENTS.md or CLAUDE.md of the repository's own keeps every byte outside the marks: the block is added at "
          "its end, the import on a line of its own; a block edited between the marks is put back, the text after them "
          "kept, and nothing else is written",
          a1.startswith(mine) and _block(a1) is not None and c1 == "Our rules.\n@AGENTS.md\n"
          and a2 == a1 + "Our tail.\n" and again.get("wrote") == ["AGENTS.md"],
          (a1[:60], c1, again))
    r = fresh()
    (r / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    _, m1 = _init(r, "--no-entry")
    servers = json.loads((r / ".mcp.json").read_text())["mcpServers"]
    cfg = json.loads(_text(r / ".warrant" / "agent.json") or '{"workspaces": {"repo": null}}')
    (r / ".mcp.json").write_text(json.dumps({"mcpServers": {"warrant": {"command": "mine"}}}))
    _, m2 = _init(r, "--no-entry")
    r5 = fresh()
    _, m5 = _init(r5, "--no-mcp")
    kept = json.loads((r / ".mcp.json").read_text())["mcpServers"]
    plain = Path(tempfile.mkdtemp())
    _, q = _init(plain, "--store", "store")
    check("IN3 init adds the server `warrant` (unless --no-mcp: the experiment measured the block and the server together) (warrant-agent-mcp on .warrant/agent.json: this repository, read only) "
          "beside the servers .mcp.json names and never replaces one named warrant; `--no-entry` writes no AGENTS.md; a "
          "store not named .warrant is made alone, as before",
          servers.get("other") == {"command": "x"} and servers.get("warrant") == {"command": "warrant-agent-mcp", "args": ["--config", ".warrant/agent.json"]}
          and cfg["workspaces"]["repo"] == {"repo": ".", "operations": ["context", "read", "graph"]} and "signer" not in cfg["workspaces"]["repo"]
          and not (r / "AGENTS.md").exists() and m1.get("wrote") == [".warrant/v3.json", ".warrant/agent.json", ".mcp.json"]
          and kept == {"warrant": {"command": "mine"}} and m2.get("wrote") == [] and q == {"store": "store"}
          and m5.get("wrote") == [".warrant/v3.json", "AGENTS.md", "CLAUDE.md"] and not (r5 / ".mcp.json").exists()
          and sorted(p.name for p in plain.iterdir()) == ["store"],
          (m1, m2, servers, kept, q))


FAKE_TEST = """import sys
from world import check, run_sections
STATE = []


def a_cases():
    STATE.append(1)
    check("H1", True)


def b_cases():
    check("H2", bool(STATE) or "{lean}" == "no")


def c_cases():
    check("H3", "{fail}" != "H3")
    check("H4", True)


if __name__ == "__main__":
    sys.exit(run_sections([a_cases, b_cases, c_cases]))
"""


def harness_cases():
    """tests/mutants.py, the harness every KILLED rests on: a mutant runs only the sections holding its cases, read
    from clean runs of each section alone, and stops at its case's FAIL (the analysis session, 2026-11-13: 211 mutants
    ran all of tools_test.py, 201 all of agent_test.py, for one case each)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mutants_h", ROOT / "tests" / "mutants.py")
    MU = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MU)
    case_map = getattr(MU, "case_map", None)
    home = getattr(MU, "home_sections", None)

    def tree(lean, fail=""):
        d = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "warrant", d / "warrant", ignore=shutil.ignore_patterns("__pycache__"))
        (d / "tests").mkdir()
        shutil.copy2(ROOT / "tests" / "world.py", d / "tests" / "world.py")
        (d / "tests" / "fake_test.py").write_text(FAKE_TEST.replace("{lean}", lean).replace("{fail}", fail))
        (d / "tmp").mkdir()
        return d
    lean, alone = tree("yes"), tree("no")
    m_lean, r_lean = case_map({"tests/fake_test.py"}, [(lean, lean / "tmp")]) if case_map else ({}, [])
    m_alone, r_alone = case_map({"tests/fake_test.py"}, [(alone, alone / "tmp")]) if case_map else ({}, [])
    got = m_alone.get("tests/fake_test.py", {})
    check("HM1 the harness maps each case to the section that printed it, from each section run alone and unmutated, "
          "and refuses (BASELINE_RED) when a section does not pass alone: one leaning on another's state would read a "
          "FAIL its isolation caused as a kill",
          got == {"H1": {"a_cases"}, "H2": {"b_cases"}, "H3": {"c_cases"}, "H4": {"c_cases"}} and r_alone == []
          and len(r_lean) == 1 and "b_cases" in r_lean[0], (got, r_alone, r_lean))
    plan = [home(got, c) for c in (["H3"], ["H1", "H4"], ["H9"], ["H3", "H9"], [])] if home else []
    check("HM2 a mutant runs the sections holding its cases, and one whose case no clean run printed is NO_SECTION (None), "
          "never a full run that might find it", plan == [["c_cases"], ["a_cases", "c_cases"], None, None, None], plan)
    stop = tree("no", fail="H3")
    env = dict(os.environ, WARRANT_SECTION="c_cases", WARRANT_STOP="H3")
    out = subprocess.run([sys.executable, "-B", "tests/fake_test.py"], cwd=stop, capture_output=True, text=True, env=env)
    bad = subprocess.run([sys.executable, "-B", "tests/fake_test.py"], cwd=alone, capture_output=True, text=True,
                         env=dict(os.environ, WARRANT_SECTION="nope_cases"))
    whole = subprocess.run([sys.executable, "-B", "tests/fake_test.py"], cwd=alone, capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if not k.startswith("WARRANT_")})
    check("HM3 WARRANT_SECTION runs only the named sections and WARRANT_STOP ends the run right after its case's FAIL "
          "line; a section name the file does not have is refused (status 2); unset, the file runs whole as before",
          out.returncode == 1 and "FAIL H3" in out.stdout and "H4" not in out.stdout and "H1" not in out.stdout
          and bad.returncode == 2 and "NO_SUCH_SECTION" in bad.stdout
          and whole.returncode == 0 and all(f"ok   {c}" in whole.stdout for c in ("H1", "H2", "H3", "H4")),
          (out.returncode, out.stdout[-200:], bad.returncode, bad.stdout[-100:], whole.stdout[-200:]))
    combo = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "warrant", combo / "warrant", ignore=shutil.ignore_patterns("__pycache__"))
    (combo / "tests").mkdir()
    shutil.copy2(ROOT / "tests" / "world.py", combo / "tests" / "world.py")
    (combo / "tests" / "fake_test.py").write_text(
        "import sys\nfrom world import check, run_sections\nSTATE = []\n\n\ndef a_cases():\n    STATE.append(1)\n"
        "    check(\"H1\", True)\n\n\ndef b_cases():\n    STATE.clear()\n    check(\"H2\", True)\n\n\ndef c_cases():\n"
        "    check(\"H3\", not STATE)\n\n\nif __name__ == \"__main__\":\n    sys.exit(run_sections([a_cases, b_cases, c_cases]))\n")
    (combo / "unused.py").write_text("UNUSED = 0\n")
    keep = (MU.COPY, MU.TMP, MU.jobs, MU.MUTANTS, MU.copy_tree)
    MU.COPY, MU.TMP = combo.parent / (combo.name + "-copy"), combo.parent / (combo.name + "-tmp")
    MU.jobs, MU.copy_tree = (lambda: 1), (lambda dest: shutil.copytree(combo, dest, dirs_exist_ok=True))
    MU.MUTANTS = [("PROBE", "unused.py", "UNUSED = 0", "UNUSED = 1", "tests/fake_test.py", ["H1", "H3"])]
    with contextlib.redirect_stdout(io.StringIO()) as said:
        rows = MU.run_mutants(["PROBE"]) if case_map else [{"outcome": "KILLED"}]
    real_run = MU.run
    MU.run = lambda test, cwd, tmp=MU.TMP, extra=None: (None, "ok   H2 printed before it hung\n") \
        if (extra or {}).get("WARRANT_SECTION") == "b_cases" else real_run(test, cwd, tmp, extra)
    MU.MUTANTS = [("PROBE2", "unused.py", "UNUSED = 0", "UNUSED = 1", "tests/fake_test.py", ["H2"])]
    with contextlib.redirect_stdout(io.StringIO()) as said2:
        rows2 = MU.run_mutants(["PROBE2"]) if case_map else [{"outcome": "KILLED"}]
    MU.run = real_run
    MU.COPY, MU.TMP, MU.jobs, MU.MUTANTS, MU.copy_tree = keep
    check("HM4 the sections a mutant runs together are run together unmutated first: a and c pass alone and fail together "
          "(b clears what a leaves), so no mutant of theirs is credited a kill, the whole run refused (BASELINE_RED; "
          "Codex on #391 at 52e05290, its F1)", rows is None and "BASELINE_RED" in said.getvalue(), (rows, said.getvalue()[-300:]))
    check("HM5 a section that runs past the timeout unmutated refuses the run as a red one does: the cases it printed "
          "before it hung credit no kill (the analysis session on #391)", rows2 is None and "TIMEOUT" in said2.getvalue(),
          (rows2, said2.getvalue()[-300:]))


def asked_cases():
    """What was asked of an actor (a version whose body names it in `opened.for`, minds Q1 81d731d3): graph.frontier's
    `asked`, the gate's due_for and `roadmap due` (the review waker's queue), the agent's frontier (MCP)."""
    from warrant import gate as GT
    from warrant import graph as G
    from warrant import roadmap as RM
    from warrant_agent import api
    from warrant_agent.config import Config
    r = Repo()
    q = r.entity("alice", "goal@1", {"state": "open", "key": "Q1", "text": "why?", "opened": {"by": "alice", "for": "bob"}})
    mine = r.entity("bob", "goal@1", {"state": "open", "key": "Q2", "text": "me?", "opened": {"by": "bob", "for": "bob"}})
    odd = [r.entity("alice", "goal@1", {"state": "open", "key": f"Q{k}", "text": "?", "opened": {"for": f}})
           for k, f in ((3, ["bob"]), (4, {"actor": "bob"}), (5, ""))]
    rep = RP.Repo(r.root).report()
    prof = r.profile
    asked = lambda rep, actor: [x["version"] for x in G.frontier(rep, prof, actor).get("asked", [])]
    before_bob, before_carol = asked(rep, "bob"), asked(rep, "carol")
    due = [d for d in GT.due_for(rep, prof, "bob", ("goal@1", "obligation@1")) if d.get("asked")]
    rdue = [d for d in RM.due(rep, prof, "bob") if d.get("asked")]
    cfg = Config({"agent_api": "warrant-agent/3", "workspaces": {"w": {"repo": str(r.root), "operations": ["graph"]}}})
    mcp = api.call(cfg, "graph", {"workspace": "w", "op": "frontier", "actor": "bob"})
    via_mcp = [x["version"] for x in (mcp.get("ok", {}).get("data") or {}).get("asked", [])]
    check("FA1 a version whose body names an actor in `opened.for` is in that actor's frontier as `asked` (with no guard "
          "waiting on it), in no other's; the gate's due_for and `roadmap due` mark it asked (the review waker's queue), "
          "and the agent's frontier through MCP has it",
          before_bob == [q] and before_carol == [] and [d["version"] for d in due] == [q] and [d["closure"] for d in rdue] == [q]
          and via_mcp == [q], (before_bob, before_carol, due, rdue, via_mcp))
    all_due = [d["version"] for d in GT.due_for(rep, prof, "bob", ("goal@1", "obligation@1"))]
    check("FA2 a question an actor asks itself is not shown to it (nor due for it), and an `opened.for` that is no string "
          "naming an actor (a list, an object, empty) is shown to no one", mine not in before_bob and mine not in all_due
          and not set(odd) & set(before_bob), (before_bob, all_due, mine, odd))
    r.attest("bob", q, verdict="answered")
    after_attest = asked(RP.Repo(r.root).report(), "bob")
    r2 = Repo()
    q2 = r2.entity("alice", "goal@1", {"state": "open", "key": "Q1", "text": "why?", "opened": {"for": "bob"}})
    r2.put("bob", "challenge", {"target": q2, "statement": "the question rests on a wrong reading"}, refs=[q2])
    after_challenge = [x["version"] for x in G.frontier(RP.Repo(r2.root).report(), r2.profile, "bob").get("asked", [])]
    check("FA3 an attest or a challenge by the asked actor on the version takes it off its frontier (an answer is any "
          "verdict: no guard waits on it)", after_attest == [] and after_challenge == [], (after_attest, after_challenge))


if __name__ == "__main__":
    sys.exit(run_sections([
        claims_cases,
        preflight_cases,
        drift_cases,
        pinned_cases,
        entry_cases,
        freshness_cases,
        drift_impact_cases,
        review_cases,
        roadmap_cases,
        cli_cases,
        chain_join_cases,
        home_cases,
        impact_cases,
        differential_cases,
        ledger_cases,
        grounded_cases,
        observer_cases,
        merged_cases,
        voices_cases,
        bridge_cases,
        bridge_step_cases,
        board_cases,
        narrow_cases,
        resolve_cases,
        harness_cases,
        asked_cases,
    ]))
