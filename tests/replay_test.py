#!/usr/bin/env python3
"""G4: the replay checker (tools/claimslib/replay.py) and acceptances by replay as `check`
reads them (tools/claimslib/by_replay.py).

Each case builds a small git repository with a copy of the packages under test, a toy module
(warrant/toy.py), its test file (tests/toy_test.py: T1 double, T2 negate, T3 a case one fixture
fails) and a mutant harness of three mutants: M1 breaks double (T1 fails), M2 breaks negate (only
T2 fails), M3 makes the module unimportable. Claims are filed by claude under pins that adopt
the checker, so their duties name it. Cases assert on data: refusal codes, records filed, the
engine's disposition, the view's words.

  R0  a claim whose witnesses pass and whose mutants its cited cases kill is accepted; DISCHARGED
  R1  a cited witness fails: refused, nothing filed
  R2  the mutant fails only a case the claim does not cite, or crashes the test file (no results,
      as an import error proves nothing): refused, nothing filed
  R3  the working tree is not HEAD's: refused, nothing filed
  R4  a challenge targets the claim: refused, nothing filed
  R5  run with a key not bound to the checker's id: refused, nothing filed
  R6  the pins adopt a checker roles.json does not pin: ROLE_UNPINNED; pinned, a squatter's binding
      is refused and its forged acceptance is not authentic, the duty stays OPEN
  R7  an acceptance signed by the checker's key whose report shows a failure: CHECKER_REPORT_FAILS
  R8  a report naming another tree, or a commit without the claim: CHECKER_OTHER_TREE
  R9  checker code changed and the same actor id reused: CHECKER_CODE_MISMATCH; pins naming a
      checker this checkout's code is not: CHECKER_PIN_STALE
  R10 an acceptance of a claim challenged in the replayed store: CHECKER_ACCEPTED_CHALLENGED
  R11 a report the signer did not replay (a surviving mutant shown KILLED): `replay --verify`
      re-executes the commit's replay.py and refuses CHECKER_REPLAY_DIFFERS
  R12 a duty naming the checker for an UNBACKED claim: CLAIM_DUTY_TERMS (a replay accepts no thesis)
  R13 rehome: a claim filed before the checker moves to a new duty that names it; the old duty
      stays OPEN in the store, and the roadmap and `why` follow the lineage to the claim
  R14 the view names an acceptance by replay for what it checked, never as a review
  R15 a claim's superseded transition is not replayed: only its current one
  AMEND 1 of #176 (Codex: a report naming its commit by a tag that later moved made `replay
  --verify` run another tree and say OK). A commit is named by its canonical id, the full
  lowercase hex id that Git resolves to itself as a commit, never by a ref (minds VARS-1 §3):
  R16 Codex's reproduction: a report naming a tag is refused by every check, and `--verify`
      refuses it before running anything, before and after the tag moves; an honest report's
      canonical id still verifies after a tag at it is moved and deleted
  R17 a short id          R18 HEAD, HEAD~1, a 40-character tag name
  R19 an annotated tag's own object id (full lowercase hex, not a commit's id)
  R20 uppercase hex       R21 a trailing newline at the valid length (39 digits + "\n")
  R22 a commit whose tree is not the report's tree: `--verify` refuses it before running anything

    python3 tests/replay_test.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from world import R, W, check, finish
from warrant import jcs as C
from warrant.store import Store, Trust

ROOT = Path(__file__).resolve().parents[1]
IMPL = Path(os.environ["WARRANT_IMPL"]) if os.environ.get("WARRANT_IMPL") else ROOT


def _tool(name):
    path = IMPL / "tools" / name if (IMPL / "tools" / name).is_file() else ROOT / "tools" / name
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name[:-3]] = mod
    spec.loader.exec_module(mod)
    return mod


CL = _tool("claims.py")
RP, BR = CL.replay, CL.by_replay
TOOLS = Path(CL.__file__).resolve().parent         # the tools/ the claims tool under test came from
CHECKER = RP.actor()

TOY = "def double(x):\n    return x * 2\n\n\ndef negate(x):\n    return -x\n"
TOY_TEST = '''import sys
from world import check, finish
from warrant import toy


def main():
    check("T1", toy.double(3) == 6, "double")
    check("T2", toy.negate(1) == -1, "negate")
    check("T3", T3, "a case a fixture may make fail")
    return finish("TOY")


T3 = True
if __name__ == "__main__":
    sys.exit(main())
'''
HARNESS = '''MUTANTS = [
    ("M1", "toy.py", "double adds", [("    return x * 2\\n", "    return x + 2\\n")], "toy_test", ["T1"]),
    ("M2", "toy.py", "negate is the identity", [("    return -x\\n", "    return x\\n")], "toy_test", ["T2"]),
    ("M3", "toy.py", "toy does not import", [("def negate(x):\\n", "def negate(x:\\n")], "toy_test", ["T1"]),
]
'''
PINS = {"claims": "warrant-claims/pins@1", "source": "SPEC.md", "sections": [], "sentences": {}, "headings": {},
        "owed_to": ["readers"], "accept_by": ["codex"]}
GIT = ["-c", "user.name=replay-test", "-c", "user.email=replay@invalid", "-c", "commit.gpgsign=false",
       "-c", "gc.auto=0", "-c", "maintenance.auto=false"]
BASE = Path(tempfile.mkdtemp(prefix="replay-test-"))
KEYS = {a: W.Key.generate() for a in ("claude", "codex", "checker", "squatter")}


def git(d, *args):
    return subprocess.run(["git", "-C", str(d), *GIT, *args], capture_output=True, check=True).stdout.decode().strip()


class Fix:
    """One fixture repository: `claims` {id: (witnesses, mutants)} filed by claude, committed."""

    def __init__(self, name, claims, checkers=(CHECKER,), pin_checker=True, t3=True, before=None):
        d = self.dir = BASE / name
        shutil.copytree(IMPL / "warrant", d / "warrant", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(TOOLS, d / "tools", ignore=shutil.ignore_patterns("__pycache__"))
        (d / "warrant" / "toy.py").write_text(TOY)
        (d / "tests").mkdir()
        shutil.copy2(ROOT / "tests" / "world.py", d / "tests" / "world.py")
        (d / "tests" / "toy_test.py").write_text(TOY_TEST.replace("T3 = True", f"T3 = {t3}"))
        (d / "tests" / "mutants.py").write_text(HARNESS)
        (d / ".warrant").mkdir()
        roles = {"claude": KEYS["claude"].public, "codex": KEYS["codex"].public, "readers": "collective"}
        if pin_checker:
            roles[CHECKER] = KEYS["checker"].public
        (d / ".warrant" / "roles.json").write_text(json.dumps({"roles": CL.ROLES, "actors": roles}))
        self.bind([("claude", "claude"), ("codex", "codex"), (CHECKER, "checker")])
        (d / ".warrant" / "claims.json").write_text(json.dumps(dict(PINS, checkers=list(checkers))))
        self.repo = CL.Repo(d)
        Store(self.repo.store_dir).init()
        if before:
            before(self)
        au = CL.Author(self.repo, KEYS["claude"], "claude", validate=False)
        self.tid = {cid: au.claim(cid, f"sentence {cid}", w, m) for cid, (w, m) in claims.items()}
        git(d, "init", "-q")
        self.commit()

    def bind(self, pairs):
        keys = [{"actor": a, "public": KEYS[k].public, "proof": CL.binding_proof(KEYS[k], a)} for a, k in pairs]
        (self.dir / ".warrant" / "trust.json").write_bytes(C.canon({"bindings": CL.BINDINGS, "keys": keys}))

    def commit(self, msg="state"):
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "--allow-empty", "-m", msg)
        return git(self.dir, "rev-parse", "HEAD")

    def model(self):
        return CL.Model(self.repo.snapshot(), self.repo.trust())

    def replay(self, cid, key="checker"):
        """(accepted transitions, refusal codes) of the checker run on claim `cid`, or the code it raised."""
        try:
            filed, refused = RP.run(self.dir, Store(self.repo.store_dir), self.repo.trust(), KEYS[key],
                                    [self.model().current[cid].tid], jobs=2)
        except RP.Refusal as e:
            return [], [e.code]
        return [t for t, _ in filed], [e.code for _, e in refused]

    def challenge(self, cid):
        at = max(r["at"] for r in self.model().recs.values()) + 1
        return Store(self.repo.store_dir).append("challenge", "claude", at, R.challenge(self.tid[cid], "disputed", [], 0),
                                                 KEYS["claude"], self.repo.trust())

    def accepts(self):
        return [r for r in self.model().recs.values() if r["type"] == "accept"]

    def disposition(self, cid):
        m = self.model()
        rep = CL.assessment(m.snap, self.repo.trust())
        return rep["duties"][m.current[cid].doc["duty"]]["disposition"]

    def forge(self, cid, key, actor, **report):
        """File an acceptance as `actor` signed by `key`, with a report blob: the honest one of
        R0's shape, its members overridden by `report`."""
        m = self.model()
        n = m.current[cid]
        rep = {"replay": RP.REPORT, "checker": CHECKER[len(RP.PREFIX):], "commit": git(self.dir, "rev-parse", "HEAD"),
               "tree": git(self.dir, "rev-parse", "HEAD^{tree}"), "claim": cid, "transition": n.tid,
               "duty": n.doc["duty"], "witnesses": {w: "PASS" for w in n.doc["witnesses"]},
               "mutants": {x: {"outcome": "KILLED", "fails": list(n.doc["witnesses"][:1])} for x in n.doc["mutants"]}}
        rep.update(report)
        store = Store(self.repo.store_dir)
        h = store.put_json(rep)
        at = max(r["at"] for r in m.recs.values()) + 1
        ev = n.rec["body"]["closes"][0]["evidence"]
        return store.append("accept", actor, at, R.accept(n.tid, 0, ev, [h]), KEYS[key], self.repo.trust())

    def codes(self, base=None):
        """The checker codes `check` reports: by_replay over every acceptance, and, against the
        commit `base`, over the acceptances new since it."""
        m = self.model()
        out = BR.problems(self.repo, m, self.repo.pins())
        if base is not None:
            before = {Path(p).name[:-5] for p in git(self.dir, "ls-tree", "-r", "--name-only", base, "--",
                                                     ".warrant/store/records").split()}
            out += BR.new_problems(self.repo, m, before)
        return sorted({c for c, _ in out})


GOOD = {"SPEC-1-1": (["toy_test:T1"], ["M1"])}


def checker_cases():
    """R0-R5: what the checker files, and what it refuses to file."""
    f = Fix("good", GOOD)
    base = git(f.dir, "rev-parse", "HEAD")
    acc, ref = f.replay("SPEC-1-1")
    f.commit("accepted")
    ok = acc == [f.tid["SPEC-1-1"]] and not ref and len(f.accepts()) == 1 and f.disposition("SPEC-1-1") == "DISCHARGED"
    check("R0", ok and f.codes(base) == [] and BR.verify(f.repo, f.model(), base, jobs=2) == [],
          "a claim whose witness passes and whose mutant its cited case kills is accepted by replay; DISCHARGED; "
          "check and the re-execution agree", (acc, ref, f.disposition("SPEC-1-1"), f.codes(base)))
    g = Fix("witness-fails", {"SPEC-1-3": (["toy_test:T3"], ["M1"])}, t3=False)
    acc, ref = g.replay("SPEC-1-3")
    check("R1", acc == [] and ref == ["REPLAY_WITNESS_FAILS"] and not g.accepts(),
          "a cited witness fails: refused, nothing filed", (acc, ref))
    g = Fix("mutant-survives", {"SPEC-1-2": (["toy_test:T1"], ["M2"])})
    acc, ref = g.replay("SPEC-1-2")
    g2 = Fix("mutant-crashes", {"SPEC-1-4": (["toy_test:T1"], ["M3"])})
    acc2, ref2 = g2.replay("SPEC-1-4")
    check("R2", acc == [] and ref == ["REPLAY_MUTANT_SURVIVES"] and not g.accepts() and acc2 == []
          and ref2 == ["REPLAY_MUTANT_SURVIVES"] and not g2.accepts(),
          "a mutant that fails only a case the claim does not cite, or crashes the test file, is no kill: refused",
          (acc, ref, acc2, ref2))
    g = Fix("dirty", GOOD)
    (g.dir / "tests" / "toy_test.py").write_text((g.dir / "tests" / "toy_test.py").read_text() + "\n# local edit\n")
    acc, ref = g.replay("SPEC-1-1")
    check("R3", acc == [] and ref == ["REPLAY_DIRTY"] and not g.accepts(),
          "a working tree that is not HEAD's is refused: a replay is of a commit's exact tree", (acc, ref))
    g = Fix("challenged", GOOD)
    g.challenge("SPEC-1-1")
    g.commit("challenged")
    acc, ref = g.replay("SPEC-1-1")
    check("R4", acc == [] and ref == ["REPLAY_CHALLENGED"] and not g.accepts(),
          "a challenged claim is refused: it is left to its author and acceptors", (acc, ref))
    g = Fix("wrong-key", GOOD)
    acc, ref = g.replay("SPEC-1-1", key="claude")
    check("R5", acc == [] and ref == ["REPLAY_KEY"] and not [r for r in (g.repo.store_dir / "records").glob("*")
                                                                 if b'"accept"' in r.read_bytes()],
          "run with a key not bound to the checker's own id: refused, nothing filed", (acc, ref))


def check_side_cases():
    """R6-R11: acceptances filed around the checker, as `check` and the re-execution read them."""
    g = Fix("unpinned", GOOD, pin_checker=False)
    unpinned = [c for c, w in CL.check(g.repo) if c == "ROLE_UNPINNED" and CHECKER in w]
    g2 = Fix("squat", GOOD)
    g2.bind([("claude", "claude"), ("codex", "codex"), (CHECKER, "squatter")])
    refused = [c for c, _ in g2.repo.bindings()[1]]
    rid = g2.forge("SPEC-1-1", "squatter", CHECKER)
    check("R6", bool(unpinned) and "BINDING_ROLE_KEY" in refused and rid not in g2.model().recs
          and g2.disposition("SPEC-1-1") == "OPEN",
          "a checker the pins adopt must be pinned in roles.json; a squatter's key for its name is refused, and an "
          "acceptance it signs is not authentic: the duty stays OPEN", (unpinned, refused))
    g = Fix("lies", GOOD)
    base = git(g.dir, "rev-parse", "HEAD")
    g.forge("SPEC-1-1", "checker", CHECKER, witnesses={"toy_test:T1": "FAIL"})
    g3 = Fix("lies-mutant", GOOD)
    g3.forge("SPEC-1-1", "checker", CHECKER, mutants={"M1": {"outcome": "SURVIVED", "fails": []}})
    check("R7", g.codes(base) == ["CHECKER_REPORT_FAILS"] and g3.codes() == ["CHECKER_REPORT_FAILS"],
          "an acceptance whose report shows a failing witness or a surviving mutant is refused, whoever signed it",
          (g.codes(base), g3.codes()))
    g = Fix("other-tree", GOOD)
    base = git(g.dir, "rev-parse", "HEAD")
    g.forge("SPEC-1-1", "checker", CHECKER, tree="ab" * 20)
    h = Fix("other-commit", GOOD)
    git(h.dir, "rm", "-q", "-r", "--cached", ".warrant/store")
    git(h.dir, "commit", "-q", "-m", "a commit without the store")
    early = git(h.dir, "rev-parse", "HEAD")
    h.commit("the store again")
    h_base = git(h.dir, "rev-parse", "HEAD")
    h.forge("SPEC-1-1", "checker", CHECKER, commit=early, tree=git(h.dir, "rev-parse", f"{early}^{{tree}}"))
    check("R8", g.codes(base) == ["CHECKER_OTHER_TREE"] and h.codes(h_base) == ["CHECKER_OTHER_TREE"],
          "a report naming another tree than its commit's, or a commit whose store lacks the claim, is refused",
          (g.codes(base), h.codes(h_base)))
    g = Fix("code-changed", GOOD)
    base = git(g.dir, "rev-parse", "HEAD")
    p = g.dir / RP.SELF
    p.write_text(p.read_text() + "\n# one more byte is another checker\n")
    g.commit("checker code changed")
    g.forge("SPEC-1-1", "checker", CHECKER)
    check("R9", g.codes(base) == ["CHECKER_CODE_MISMATCH", "CHECKER_PIN_STALE"],
          "the same checker id with other code is refused, and pins naming a checker the code is not are stale",
          g.codes(base))
    g = Fix("accepted-challenged", GOOD)
    g.challenge("SPEC-1-1")
    base = g.commit("challenged")
    g.forge("SPEC-1-1", "checker", CHECKER)
    check("R10", g.codes(git(g.dir, "rev-parse", "HEAD~1")) == ["CHECKER_ACCEPTED_CHALLENGED"],
          "an acceptance of a claim a challenge targeted in the replayed store is refused", g.codes(base))
    g = Fix("unreplayed", {"SPEC-1-2": (["toy_test:T1"], ["M2"])})
    base = git(g.dir, "rev-parse", "HEAD")
    g.forge("SPEC-1-2", "checker", CHECKER)
    g.commit("an acceptance nobody replayed")
    got = [c for c, _ in BR.verify(g.repo, g.model(), base, jobs=2)]
    check("R11", g.codes(base) == [] and got == ["CHECKER_REPLAY_DIFFERS"],
          "a report its signer did not replay passes every structural check, and the re-execution of the "
          "commit's own checker refuses it", (g.codes(base), got))


def migration_cases():
    """R12-R14: which duties a checker may be named in, the migration, and the view."""
    def unbacked(fx):
        au = CL.Author(fx.repo, KEYS["claude"], "claude", validate=False)
        au.pins["accept_by"] = [CHECKER]          # a thesis filed under the checker: what the pins refuse
        fx.thesis = au.claim("SPEC-2-1", "an open question", [], [], unbacked_because="no witness yet")
    g = Fix("thesis", {}, before=unbacked)
    terms = [c for c, w in CL.check(g.repo) if c == "CLAIM_DUTY_TERMS" and "SPEC-2-1" in w]
    check("R12", bool(terms), "a duty naming the checker for an UNBACKED claim is refused: a replay accepts no thesis",
          terms)
    g = Fix("rehome", GOOD, checkers=())
    old = g.model().current["SPEC-1-1"]
    old_duty = old.doc["duty"]
    pins = g.repo.pins()
    g.repo.write_pins(dict(pins, checkers=[CHECKER]))
    seed = BASE / "claude.seed"
    seed.write_text(KEYS["claude"].seed_hex() + "\n")
    with contextlib.redirect_stdout(io.StringIO()):
        rc = CL.main(["--root", str(g.dir), "rehome", "--key", str(seed), "--because", "G4"])
    m = g.model()
    new = m.current["SPEC-1-1"]
    rep = CL.assessment(m.snap, g.repo.trust())
    (g.dir / ".warrant" / "roadmap.json").write_text(json.dumps({"roadmap": "warrant-roadmap/config@1", "owed_to": ["codex"],
                                                                "accept_by": ["codex"], "results_accept_by": ["codex"]}))
    mapped = _tool("roadmap.py").Roadmap(g.dir).model().claim_of.get(old_duty) == "SPEC-1-1"
    w = CL.Why(g.repo)
    check("R13", rc == 0 and new.tid != old.tid and new.doc["duty"] != old_duty
          and m.recs[new.doc["duty"]]["body"]["accept_by"] == [CHECKER] and rep["duties"][old_duty]["disposition"] == "OPEN"
          and mapped and w.lineage.get("SPEC-1-1") == {old_duty, new.doc["duty"]},
          "rehome moves a BACKED claim to a new duty the checker accepts; the old duty stays OPEN; the roadmap and "
          "why map both duties to the claim", (rc, new.doc["duty"][:12], old_duty[:12], mapped))
    g.commit("rehomed")
    acc, ref = g.replay("SPEC-1-1")
    view = CL.render(g.repo)
    row = next((ln for ln in view.splitlines() if ln.startswith("| SPEC-1-1 ")), "")
    check("R14", acc == [g.model().current["SPEC-1-1"].tid] and "DISCHARGED (accepted by replay of its witnesses and "
          "mutants at tree" in row and "review" not in row.lower() and CHECKER not in row,
          "the view names an acceptance by replay for what it checked: witnesses and mutants at a tree, by "
          "checker <hash>, never a review", (acc, ref, row))
    g = Fix("superseded", GOOD)
    au = CL.Author(g.repo, KEYS["claude"], "claude", validate=False)
    old = g.model().current["SPEC-1-1"]
    au.claim("SPEC-1-1", old.doc["text"], ["toy_test:T1", "toy_test:T2"], ["M1"], because="a second witness",
             previous=old)
    g.commit("re-backed")
    try:
        filed, refused = RP.run(g.dir, Store(g.repo.store_dir), g.repo.trust(), KEYS["checker"], [old.tid], jobs=2)
        got = ([t for t, _ in filed], [e.code for _, e in refused])
    except RP.Refusal as e:
        got = ([], [e.code])
    check("R15", got == ([], ["REPLAY_SUPERSEDED"]) and not g.accepts(),
          "a claim's superseded transition is not replayed, though its duty is the same: only the current one", got)


def naming_cases():
    """R16-R22: the reported commit is named by its canonical id, or nothing reads it."""
    f = Fix("tag", GOOD)
    base = git(f.dir, "rev-parse", "HEAD")
    tag = "refs/tags/replay-source"
    git(f.dir, "update-ref", tag, base)
    f.forge("SPEC-1-1", "checker", CHECKER, commit=tag)
    f.commit("a report naming a tag")
    before = (f.codes(), [c for c, _ in BR.verify(f.repo, f.model(), base, jobs=1)])
    (f.dir / "README.md").write_text("another source tree\n")
    git(f.dir, "update-ref", tag, f.commit("another tree"))
    moved = [c for c, _ in BR.verify(f.repo, f.model(), base, jobs=1)]
    with contextlib.redirect_stdout(io.StringIO()):
        rc = CL.main(["--root", str(f.dir), "replay", "--verify", "--base", base, "--jobs", "1"])
    h = Fix("tag-honest", GOOD)
    h_base = git(h.dir, "rev-parse", "HEAD")
    h.replay("SPEC-1-1")
    git(h.dir, "update-ref", "refs/tags/at-source", h.commit("accepted"))
    (h.dir / "README.md").write_text("moved on\n")
    git(h.dir, "update-ref", "refs/tags/at-source", h.commit("another tree"))
    after_move = BR.verify(h.repo, h.model(), h_base, jobs=1)
    git(h.dir, "update-ref", "-d", "refs/tags/at-source")
    after_delete = BR.verify(h.repo, h.model(), h_base, jobs=1)
    check("R16", before == (["CHECKER_COMMIT_NAME"], ["CHECKER_COMMIT_NAME"]) and moved == ["CHECKER_COMMIT_NAME"]
          and rc == 1 and after_move == [] and after_delete == [] and len(h.accepts()) == 1,
          "a report naming its commit by a tag is refused by every check and never replayed, before or after the "
          "tag moves; a canonical id verifies whatever happens to tags", (before, moved, rc, after_move, after_delete))

    def named(name, commit=None, tree=None, verify=False, new=False):
        """The checker codes of a forged report whose commit (or tree) is `commit(g)` (`tree(g)`):
        the checks of every acceptance (no git: the shape of the ids), with `new` also those of an
        acceptance new since the base (the ids resolved), or with `verify` the re-execution."""
        g = Fix(name, GOOD)
        b = git(g.dir, "rev-parse", "HEAD")
        kv = {k: v for k, v in (("commit", commit(g) if commit else None), ("tree", tree(g) if tree else None)) if v}
        g.forge("SPEC-1-1", "checker", CHECKER, **kv)
        g.commit("forged")
        return ([c for c, _ in BR.verify(g.repo, g.model(), b, jobs=1)] if verify else g.codes(b if new else None)), kv

    def full(g):
        return git(g.dir, "rev-parse", "HEAD")

    got, kv = named("short", commit=lambda g: full(g)[:12])
    check("R17", got == ["CHECKER_COMMIT_NAME"], "a short commit id is refused: an abbreviation names what it "
          "resolves to today", (got, kv))

    def long_tag(g):
        git(g.dir, "tag", "r" * 40, "HEAD")
        return "r" * 40
    rows = {label: named(f"expr-{k}", commit=make)[0] for k, (label, make) in enumerate(
        (("HEAD", lambda g: "HEAD"), ("HEAD~1", lambda g: "HEAD~1"), ("40-character tag", long_tag)))}
    check("R18", all(v == ["CHECKER_COMMIT_NAME"] for v in rows.values()),
          "HEAD, HEAD~1 and a tag as long as an id are refused: a revision expression or a ref is no commit id", rows)

    def annotated(g):
        git(g.dir, "tag", "-a", "-m", "annotated", "annotated-source", "HEAD")
        return git(g.dir, "rev-parse", "refs/tags/annotated-source")
    got, kv = named("annotated", commit=annotated, new=True)
    got_v, kv_v = named("annotated-v", commit=annotated, verify=True)
    check("R19", got == ["CHECKER_COMMIT_NAME"] and got_v == ["CHECKER_COMMIT_NAME"] and len(kv["commit"]) == 40,
          "an annotated tag's own object id (full lowercase hex) is refused: Git resolves it to another id", (got, got_v))
    got, kv = named("upper", commit=lambda g: full(g).upper())
    check("R20", got == ["CHECKER_COMMIT_NAME"], "an uppercase commit id is refused", (got, kv))
    got, kv = named("newline", commit=lambda g: full(g)[:39] + "\n")
    check("R21", got == ["CHECKER_COMMIT_NAME"] and len(kv["commit"]) == 40,
          "a 39-digit id with a trailing newline, at the valid length, is refused (\\Z, not $)", (got, kv))
    got, kv = named("tree", tree=lambda g: git(g.dir, "rev-parse", "HEAD^{tree}")[::-1], verify=True)
    check("R22", got == ["CHECKER_OTHER_TREE"], "a commit whose tree is not the report's tree is refused by --verify "
          "before anything runs", (got, kv))


def main():
    try:
        checker_cases()
        check_side_cases()
        migration_cases()
        naming_cases()
    finally:
        shutil.rmtree(BASE, ignore_errors=True)
    return finish("REPLAY")


if __name__ == "__main__":
    sys.exit(main())
