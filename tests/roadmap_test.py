#!/usr/bin/env python3
"""The roadmap as records (tools/roadmap.py): goals, obligations, path search.

Each case builds a fixture repository (a store, bindings with proofs for claude,
codex, s0fractal and stranger, .warrant/roadmap.json) and drives the tool through its
command line in process. States are asserted on the data `path` reads from the
engine's report, refusals by their code or by the store staying unchanged, never
by wording, so a mutant is killed only when a rule stops holding.

    python3 tests/roadmap_test.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from world import R, W, check, finish
from warrant import jcs as C
from warrant.store import Snapshot, Store, Trust

ROOT = Path(__file__).resolve().parents[1]
_impl = Path(os.environ["WARRANT_IMPL"]) / "tools" / "roadmap.py" if os.environ.get("WARRANT_IMPL") else None
TOOL = _impl if _impl is not None and _impl.is_file() else ROOT / "tools" / "roadmap.py"
_spec = importlib.util.spec_from_file_location("roadmap", TOOL)
RM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RM)
CL = RM.CL

ACTORS = ("claude", "codex", "s0fractal", "stranger")
CONFIG = ('{"roadmap": "warrant-roadmap/config@1", "owed_to": ["s0fractal"], "accept_by": ["codex"], '
          '"results_accept_by": ["codex"]}\n')


class Repo:
    """A fixture repository whose store only the roadmap uses (or a copy of this one's, `spec=True`)."""

    def __init__(self, spec=False):
        self.base = Path(tempfile.mkdtemp(prefix="warrant-roadmap-"))
        self.dir = self.base / "repo"
        (self.dir / ".warrant").mkdir(parents=True)
        self.keys = {a: W.Key.generate() for a in ACTORS}
        if spec:
            shutil.copytree(ROOT / ".warrant" / "store", self.dir / ".warrant" / "store")
            shutil.copy(ROOT / ".warrant" / "claims.json", self.dir / ".warrant" / "claims.json")
            for f in ("SPEC.md", "SPEC-CLAIMS.md", "WITNESSES.md"):
                shutil.copy(ROOT / f, self.dir / f)
            bound = list(C.loads((ROOT / ".warrant" / "trust.json").read_bytes())["keys"])
            # This store's claude is bound already (the first binding of an actor wins): the test's
            # claude key is the receiver's own binding (WARRANT_CLAIMS_TRUST), as in the claims selftest.
            local = self.base / "local-trust.json"
            local.write_bytes(C.canon(Trust.document([("claude", self.keys["claude"].public)])))
            os.environ[CL.LOCAL_TRUST] = str(local)
        else:
            Store(self.dir / ".warrant" / "store").init()
            bound = []
        self.seeds = {}
        for a, k in self.keys.items():
            p = self.base / f"{a}.seed"
            p.write_text(k.seed_hex() + "\n")
            self.seeds[a] = str(p)
        mine = [{"actor": a, "public": k.public, "proof": CL.binding_proof(k, a)} for a, k in self.keys.items()
                if not (spec and a == "claude")]
        doc = {"bindings": CL.BINDINGS, "keys": bound + mine}
        (self.dir / ".warrant" / "trust.json").write_bytes(C.canon(doc))
        # The roles the configuration names are pinned (AMEND 1 of #170): to the test keys, and in
        # spec mode claude to the key this store's records are signed with (its own binding).
        roles = {a: k.public for a, k in self.keys.items() if a != "stranger"}
        if spec:
            roles["claude"] = next(e["public"] for e in bound if e["actor"] == "claude")
        roles["readers"] = CL.COLLECTIVE
        (self.dir / ".warrant" / "roles.json").write_text(json.dumps({"roles": CL.ROLES, "actors": roles}))
        (self.dir / ".warrant" / "roadmap.json").write_text(CONFIG)
        self.rm = RM.Roadmap(self.dir)
        self.store = Store(self.dir / ".warrant" / "store")

    def run(self, *argv, actor="claude"):
        """(exit status, stdout stripped, stderr) of one tool command, signed by `actor`."""
        sign = ["--key", self.seeds[actor], "--actor", actor] if argv[0] not in ("path", "project", "check", "due") else []
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = RM.main(["--root", str(self.dir), argv[0], *sign, *argv[1:]])
        return rc, out.getvalue().strip(), err.getvalue()

    def ok(self, *argv, actor="claude"):
        rc, out, err = self.run(*argv, actor=actor)
        if rc != 0:
            raise AssertionError(f"{argv[0]} refused: {err.strip()}")
        return out

    def model(self):
        return self.rm.model()

    def files(self):
        return sorted(p.name for p in (self.dir / ".warrant" / "store").rglob("*") if p.is_file())

    def at(self):
        return max([int(time.time())] + [r["at"] for r in self.model().recs.values()])

    def file(self, actor, rtype, body, blobs=()):
        for doc in blobs:
            self.store.put_json(doc)
        return self.store.put_record(R.record(rtype, actor, self.at(), body), self.keys[actor])

    def accept(self, tid, item=0, actor="codex"):
        body = self.model().recs[tid]["body"]
        ev = body["evidence"] if item is None else body["closes"][item]["evidence"]
        return self.file(actor, "accept", R.accept(tid, item, ev))

    def path(self, key):
        return RM.path_data(self.model(), key)

    def problems(self):
        return [c for c, _ in RM.check(self.rm)]

    def close(self):
        os.environ.pop(CL.LOCAL_TRUST, None)
        shutil.rmtree(self.base, ignore_errors=True)


def state_of(tree, did):
    """The state and need of duty `did` wherever it appears in a path tree."""
    for n in tree:
        if n["duty"] == did:
            return n["state"], n.get("need")
        found = state_of(n["children"], did)
        if found:
            return found
    return None


def goal_cases():
    r = Repo()
    v = r.ok("goal", "--id", "G1", "--text", "A counterexample changes the repository.",
             "--id", "G2", "--text", "An agent with no preparation can use it.")
    m = r.model()
    qs = [q for q in m.rep["questions"] if q["scope"] in ("roadmap:G1", "roadmap:G2")]
    check("P1", len(qs) == 2 and all(q["question"].startswith(v + ":") and not q["owned"] for q in qs)
          and r.path("G1")["state"] == "OPEN" and r.path("G1")["formulations"][0]["taken_by"] == []
          and "unowned" in RM.render_path(r.path("G1")),
          "a goal is a question a vision transition opens, scoped roadmap:<key>; it is unowned and OPEN", qs)

    d = r.ok("oblige", "--text", "Counter blobs are accepted from any key.", "--answers", "G1")
    m = r.model()
    q = next(q for q in m.rep["questions"] if q["scope"] == "roadmap:G1")
    p = r.path("G1")
    check("P2", m.recs[d]["body"]["answers"] == q["question"] and q["owned"] and q["taken_by"] == [d]
          and [n["duty"] for n in p["obligations"]] == [d] and m.recs[d]["body"]["holder"] == "claude"
          and m.recs[d]["body"]["accept_by"] == ["codex"] and "unowned" not in RM.render_path(p),
          "an obligation is a duty held by its filer whose answers names the goal; the goal is then owned", p)
    r.close()


def source_cases():
    r = Repo()
    proposal = b'{"goal": "proposed by codex"}\n'           # raw, not canonical JSON: cited as it is
    tmp, was = r.base / "tmp", tempfile.tempdir
    tmp.mkdir()
    tempfile.tempdir = os.path.realpath(tmp)               # --source is a file name in $TMPDIR (CL.confined)
    (tmp / "claims.json").write_bytes(proposal)
    (r.base / "outside.json").write_bytes(proposal)
    v = r.ok("goal", "--id", "G1", "--text", "Proposed.", "--source", str(tmp / "claims.json"), "--source-by", "codex")
    m = r.model()
    raw = C.digest(proposal)
    src = {"schema": RM.SOURCE, "by": "codex", "blob": raw}
    f = r.path("G1")["formulations"][0]
    good = (m.recs[v]["body"]["evidence"] == [C.digest(C.canon(src)), raw] and m.snap.blob(raw) == proposal
            and f["sources"] == [{"by": "codex", "blob": raw}] and f"from codex's source blob {raw[:12]}" in RM.render_path(r.path("G1")))
    r.ok("project")
    control = r.problems()
    before = r.files()
    rcs = [r.run("goal", "--id", "G2", "--text", "x", *extra)[0] for extra in
           (("--source", str(tmp / "claims.json")), ("--source-by", "codex"),
            ("--source", str(tmp / "claims.json"), "--source-by", "codex\n"),
            ("--source", str(tmp / "absent"), "--source-by", "codex"),
            ("--source", str(r.base / "outside.json"), "--source-by", "codex"),
            ("--source", str(tmp / ".." / "outside.json"), "--source-by", "codex"))]
    unchanged = r.files() == before
    tempfile.tempdir = was
    r.close()
    r = Repo()
    # names bytes the store holds and the transition does not cite
    ghost = {"schema": RM.SOURCE, "by": "codex", "blob": r.store.put_blob(proposal)}
    r.file("claude", "transition", R.transition("ATTESTED", [C.digest(C.canon(ghost))],
                                                opened=[{"text": "Ghost.", "scope": "roadmap:G1"}]), [ghost])
    r.ok("project")
    ghosted = r.problems()
    r.close()
    check("P16", good and control == [] and rcs == [2] * 6 and unchanged and ghosted == ["SOURCE_SHAPE"],
          "goal --source cites the proposal's raw bytes and a source blob naming its author; path shows it; check "
          "refuses a source blob naming bytes the transition does not cite; a half or bad --source, or one not named in $TMPDIR, writes nothing",
          (good, control, rcs, unchanged, ghosted))


def requires_cases():
    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "The ledger exists.")
    a = r.ok("oblige", "--text", "Counter blobs are accepted from any key.", "--answers", "G1")
    b = r.ok("oblige", "--text", "A witness ledger is derived from the records.", "--answers", "G1", "--requires", a[:10])
    tb = r.ok("done", "--duty", b, "--established", "the ledger is built", "--ref", "s0fractal/warrant#1")
    filed = state_of(r.path("G1")["obligations"], b)
    r.accept(tb)
    blocked = state_of(r.path("G1")["obligations"], b)
    ta = r.ok("done", "--duty", a, "--established", "counter@1 from any key", "--ref", "s0fractal/warrant#2")
    pending = state_of(r.path("G1")["obligations"], a)
    r.accept(ta)
    p = r.path("G1")
    nb = next(n for n in p["obligations"] if n["duty"] == b)
    check("P3", blocked[0] == "OPEN" and state_of(p["obligations"], b)[0] == "DISCHARGED"
          and [c["duty"] for c in nb["children"]] == [a] and nb["children"][0]["edge"] == "requires",
          "requires blocks: an accepted discharge stays OPEN until the prerequisite is DISCHARGED; the tree shows it",
          (blocked, p))
    cand = r.model().rep["duties"][b]["candidates"]
    check("P14", filed[0] == blocked[0] == "OPEN" and filed[1] == blocked[1] != "no closure filed"
          and a[:12] in filed[1] and [c["verdict"] for c in cand] == ["ADMITTED"],
          "a discharge filed before its prerequisite is DISCHARGED reads as filed and unmet, naming the prerequisite, "
          "not as no closure filed; it is admitted once the prerequisite is", (filed, blocked, cand))
    ev = r.model().recs[ta]["body"]["evidence"]
    check("P4", pending == ("OPEN", "awaiting acceptance by codex") and state_of(p["obligations"], a) == ("DISCHARGED", None)
          and r.model().snap.json_blob(ev[0])["refs"] == ["s0fractal/warrant#2"],
          "done files a discharge citing an evidence blob; it is OPEN awaiting the acceptor, then DISCHARGED", pending)

    rc, _, _ = r.run("done", "--duty", a, "--established", "again", "--ref", "x")
    c = r.ok("oblige", "--text", "A third thing.", "--answers", "G1")
    before = r.files()
    refused = [r.run("release", "--duty", c, "--because", "not needed")[0],                       # claude is not owed it
               r.run("done", "--duty", c, "--established", "done", "--ref", "x", actor="codex")[0],  # codex does not hold it
               r.run("done", "--duty", c, "--established", "done")[0]]                           # no evidence named
    unchanged = r.files() == before
    r.ok("release", "--duty", c, "--because", "the owner forgives it", actor="s0fractal")
    check("P5", rc == 2 and refused == [2, 2, 2] and unchanged and state_of(r.path("G1")["obligations"], c)[0] == "RELEASED",
          "release is forgiveness by whom the duty is owed to; the holder cannot release or re-close, a stranger cannot "
          "discharge, a discharge names evidence", (rc, refused, unchanged))

    # A declined closure is replaced only by naming it (#182: evidence without the merge commit).
    d = r.ok("oblige", "--text", "A fourth thing.", "--answers", "G1")
    t1 = r.ok("done", "--duty", d, "--established", "done", "--ref", "s0fractal/warrant#3")
    before = r.files()
    blind = r.run("done", "--duty", d, "--established", "done", "--ref", "s0fractal/warrant#3", "--ref", "a" * 40)[0]
    wrong = r.run("done", "--duty", d, "--established", "done", "--ref", "x", "--replaces", "b" * 64)[0]
    e = r.ok("oblige", "--text", "A fifth thing.", "--answers", "G1")
    before = r.files()
    nothing = r.run("done", "--duty", e, "--established", "done", "--ref", "x", "--replaces", t1)[0]
    unchanged = r.files() == before
    t2 = r.ok("done", "--duty", d, "--established", "done", "--ref", "s0fractal/warrant#3", "--ref", "a" * 40,
              "--replaces", t1)
    body = r.model().recs[t2]["body"]
    cands = [(c["transition"], c["verdict"]) for c in r.model().rep["duties"][d]["candidates"]]
    r.accept(t2)
    check("P15", blind == wrong == nothing == 2 and unchanged and any(t1 in x for x in body["residual"])
          and sorted(cands) == sorted([(t1, "PENDING"), (t2, "PENDING")])
          and state_of(r.path("G1")["obligations"], d)[0] == "DISCHARGED",
          "a second closure of a duty with one waiting is filed only with --replaces naming that one (and --replaces "
          "names a waiting closure of that duty); its residual "
          "names it, both stay in the record, and accepting the new one discharges the duty", (blind, wrong, cands))
    # P26 (Gemini review of 1a660a6): the replacement names the declined closure in `supersedes`,
    # so once it is admitted the acceptor is not asked for the declined one (on master duties
    # 2e4b8aea0bc9 and 879b8bd5219b were DISCHARGED and their declined closures still asked codex).
    asked = [x for x in RM.E.frontier(r.model().rep, "codex") if x.get("need") == "accept" and x["transition"] == t1]
    check("P26", body["supersedes"] == [t1] and not asked,
          "a closure filed with --replaces supersedes the declined one, which then is not acceptance work",
          (body["supersedes"], asked))

    # P32 (#204, observed at b64b732): a closure filed instead of another is refiled once more (its code moved on)
    # with --replaces naming it; `done` refused, counting the first one, which it already supersedes, as waiting.
    g = r.ok("oblige", "--text", "A sixth thing.", "--answers", "G1")
    u1 = r.ok("done", "--duty", g, "--established", "done", "--ref", "s0fractal/warrant#6")
    u2 = r.ok("done", "--duty", g, "--established", "done", "--ref", "s0fractal/warrant#6", "--replaces", u1)
    before = r.files()
    stale = r.run("done", "--duty", g, "--established", "done", "--ref", "x", "--replaces", u1)[0]
    unchanged = r.files() == before
    rc, out, _ = r.run("done", "--duty", g, "--established", "done again", "--ref", "s0fractal/warrant#6", "--replaces", u2)
    u3 = out.strip()
    m = r.model()
    check("P32", (stale, unchanged, rc) == (2, True, 0) and m.recs[u3]["body"]["supersedes"] == [u2]
          and [c for c in due(r) if c in (u1, u2, u3)] == [u3]
          and not any("declined" in x for x in m.recs[u3]["body"]["residual"]),
          "a closure filed instead of another can itself be filed over, naming it; the one it superseded is not "
          "waiting any more, and the residual says only what it was filed instead of", (stale, rc, out))
    r.close()


def supersede_cases():
    r = Repo()
    v = r.ok("goal", "--id", "G1", "--text", "Old wording.", "--id", "G2", "--text", "Unchanged goal.")
    d = r.ok("oblige", "--text", "Something for the old wording.", "--answers", "G1")
    s = r.ok("reformulate", "--goal", "G1", "--text", "New wording.", "--because", "sharper")
    p = r.path("G1")
    proposed = ([f["state"] for f in p["formulations"]] == ["CURRENT", "PROPOSED"] and p["pending"][0]["act"] == "reformulate"
                and p["pending"][0]["waiting_for"] == ["codex"] and r.problems() == ["ROADMAP_MISSING"])
    r.accept(s, item=None)
    p, p2 = r.path("G1"), r.path("G2")
    fs = p["formulations"]
    check("P6", proposed and [f["state"] for f in fs] == ["REFORMULATED", "CURRENT"] and fs[0]["by"] == fs[1]["ref"]
          and fs[1]["ref"].startswith(s + ":") and fs[1]["text"] == "New wording." and p["state"] == "OPEN"
          and [n["duty"] for n in p["obligations"]] == [d]
          and [(f["state"], f["text"]) for f in p2["formulations"]] == [("REOPENED", "Unchanged goal."), ("CURRENT", "Unchanged goal.")]
          and p2["formulations"][1]["ref"].startswith(s + ":") and v != s and r.problems() == ["ROADMAP_MISSING"],
          "a goal is reformulated by a superseding transition: pending until accepted, then the old formulation is "
          "REFORMULATED, its obligations stay under the goal, the other goals are opened again unchanged (REOPENED)", p)

    b = r.ok("oblige", "--text", "A prerequisite.", "--answers", "G1")
    r.ok("oblige", "--text", "Built on it.", "--answers", "G1", "--requires", b)
    helper = r.ok("oblige", "--text", "Helps the prerequisite.", "--answers", "G2", "--serves", b)
    lines = RM.render_path(r.path("G1")).splitlines()
    served = [ln for ln in lines if ln.lstrip().startswith("served by ")]
    tops = [ln for ln in lines if ln.startswith("  answered by ")]
    deep = [ln for ln in lines if ln.startswith("    requires ")]
    parent = lines[lines.index(deep[0]) - 1] if deep else ""
    check("P7", lines[0].startswith("G1 [OPEN] New wording.") and len(tops) == 3 and len(deep) == 1 and b[:12] in deep[0]
          and parent.startswith("  answered by ") and "Built on it." in parent and "reformulated as" in lines[1]
          and len(served) == 1 and all(helper[:12] in ln and "G2" in ln for ln in served),
          "path prints the goal, its formulations, each obligation, under it its prerequisites, and the duties "
          "that serve a node with the goal they answer (once, where the node is printed in full)", lines)
    r.close()


def shared_cases():
    """A duty many obligations require is printed in full once per goal; a goal opened again unchanged
    is not called reformulated, nor unowned while obligations answer its text."""
    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "Shared prerequisites.", "--id", "G2", "--text", "Carried unchanged.")
    a = r.ok("oblige", "--text", "The common base.", "--answers", "G1")
    b = r.ok("oblige", "--text", "Left, on the base.", "--answers", "G1", "--requires", a)
    c = r.ok("oblige", "--text", "Right, on the base.", "--answers", "G1", "--requires", a)
    d = r.ok("oblige", "--text", "Top, on both.", "--answers", "G1", "--requires", b, "--requires", c)
    p = r.path("G1")
    lines = RM.render_path(p).splitlines()
    full = [ln for ln in lines if "The common base." in ln]
    back = [ln for ln in lines if a[:12] in ln and "shown above" in ln]
    nd = next(n for n in p["obligations"] if n["duty"] == d)
    again = RM.render_path(r.path("G1"))
    tops = [n["duty"] for n in p["obligations"]]
    check("P17", len(full) == 1 and full[0].startswith("  answered by ") and len(back) == 2
          and tops.index(a) < min(tops.index(b), tops.index(c)) and tops.index(d) == 3
          and [x.get("shown") for x in nd["children"]] == [True, True] and nd["children"][0]["state"] == "OPEN"
          and len([ln for ln in lines if "Left, on the base." in ln]) == 1 and again == "\n".join(lines) + "\n",
          "within a goal a duty is printed in full once; every later occurrence is one line naming it, shown above "
          "(the base three obligations require reads once, not five times); an obligation comes after those it "
          "requires; the view is the same twice", lines)

    e = r.ok("oblige", "--text", "Answers the carried goal.", "--answers", "G2")
    r.accept(r.ok("reformulate", "--goal", "G1", "--text", "Shared prerequisites, sharper.", "--because", "sharper"), item=None)
    q = r.path("G2")
    fs = q["formulations"]
    head = RM.render_path(q).splitlines()[1:3]
    check("P18", [f["state"] for f in fs] == ["REOPENED", "CURRENT"] and fs[1].get("answered_as") == [fs[0]["ref"]]
          and fs[1]["taken_by"] == [] and fs[0]["taken_by"] == [e] and "reformulated" not in head[0]
          and "unowned" not in head[1] and fs[0]["ref"][:12] in head[1]
          and [f["state"] for f in r.path("G1")["formulations"]] == ["REFORMULATED", "CURRENT"],
          "a goal another goal's revision opens again unchanged is REOPENED, not REFORMULATED; its current form "
          "names the formulation its obligations answer instead of reading unowned", (fs, head))
    r.close()


class _Cyclic:
    """A stand-in model whose two duties require each other (no signed records can: an id is a hash)."""

    def __init__(self, x, y):
        duty = {"disposition": "OPEN", "serves": []}
        self.rep = {"duties": {x: dict(duty, statement="X.", requires=[y]), y: dict(duty, statement="Y.", requires=[x])}}
        self.claim_of = {}

    @classmethod
    def chain(cls, ids, requires):
        """A stand-in whose duties `ids` require `requires[id]`."""
        m = cls("x" * 64, "y" * 64)
        m.rep["duties"] = {i: {"requires": requires.get(i, [])} for i in ids}
        return m

    def need(self, did):
        return None

    def accepted_by(self, did):
        return []

    def served_by(self, did):
        return []

    def goal_of(self, did):
        return None


def cycle_cases():
    x, y = "a" * 64, "b" * 64
    n = RM.node(_Cyclic(x, y), x, "answered by", frozenset(), set())
    inner = n["children"][0]["children"][0]
    out = []
    RM.render_node(n, 1, out)
    check("P19", inner["duty"] == x and inner.get("shown") and inner.get("cycle") and inner["children"] == []
          and len(out) == 3 and "cycle:" in out[2] and sum("X." in ln for ln in out) == 1,
          "a duty that requires itself through others ends the walk at the repeat, marked as a cycle", out)
    ids = ["d", "b", "a", "c"]
    order = RM.prerequisites_first(_Cyclic.chain(ids, {"d": ["b"], "b": ["a"]}), ids)
    loop = RM.prerequisites_first(_Cyclic.chain(ids, {"d": ["b"], "b": ["d"]}), ids)
    check("P20", order == ["a", "b", "d", "c"] and loop == ["a", "c", "d", "b"],
          "a goal's obligations are ordered so each comes after those of them it requires, else in filing order "
          "(same-second records tie on `at`); a cycle takes the first of the rest", (order, loop))


def projection_cases():
    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "A goal.")
    r.ok("project")
    fresh = r.problems()
    view = r.rm.view.read_bytes()
    r.rm.view.write_bytes(view.replace(b"\n", b"\r\n"))
    crlf = r.problems()
    r.rm.view.unlink()
    gone = r.problems()
    r.ok("project")
    r.ok("oblige", "--text", "A new obligation.", "--answers", "G1")
    later = r.problems()
    check("P8", fresh == [] and crlf == ["ROADMAP_STALE"] and gone == ["ROADMAP_MISSING"] and later == ["ROADMAP_STALE"],
          "ROADMAP.md is the view of the records: check refuses it edited (CRLF too), missing, or behind a new record",
          (fresh, crlf, gone, later))
    r.close()


def forward_attack_cases():
    r = Repo()
    r.ok("goal", "--id", "G3", "--text", "Witnesses widen without an admin.", "--id", "G4", "--text", "A rule can act.")
    a = r.ok("oblige", "--text", "First.", "--answers", "G3")
    b = r.ok("oblige", "--text", "Second.", "--answers", "G3")
    r.accept(r.ok("done", "--duty", a, "--established", "first", "--ref", "pr#1"))
    one = r.path("G3")["marks"]
    r.accept(r.ok("done", "--duty", b, "--established", "second", "--ref", "pr#2"))
    both = r.path("G3")
    c = r.ok("oblige", "--text", "Third, discharged.", "--answers", "G4")
    e = r.ok("oblige", "--text", "Fourth, forgiven.", "--answers", "G4")
    r.accept(r.ok("done", "--duty", c, "--established", "third", "--ref", "pr#3"))
    r.ok("release", "--duty", e, "--because", "dropped", actor="s0fractal")
    released = r.path("G4")["marks"]
    t = r.ok("met", "--goal", "G3", "--because", "shown by a run", "--ref", "pr#9")
    claimed = r.path("G3")
    r.accept(t, item=None)
    met = r.path("G3")
    check("P9", one == [] and both["marks"] == ["FORWARD_ATTACK"] and "mark:" in RM.render_path(both)
          and released == [] and claimed["marks"] == ["FORWARD_ATTACK"] and claimed["pending"][0]["act"] == "met"
          and met["state"] == "MET" and met["marks"] == [] and r.path("G4")["state"] == "OPEN",
          "a goal still open whose obligations are all DISCHARGED is marked (Forward Attack); one open, one released "
          "or the goal shown met (accepted) is not", (one, both["marks"], released, met))

    rec = r.model().recs[t]["body"]
    check("P11", rec["established"] == ["Witnesses widen without an admin."] and rec["opened"] == [
        {"text": "A rule can act.", "scope": "roadmap:G4"}] and r.problems() == ["ROADMAP_MISSING"],
        "met supersedes the vision transition, establishes the goal's text and opens the other goals again", rec)
    r.close()


def spec_cases():
    r = Repo(spec=True)          # this repository's own store: G9999 is a key it does not use
    spec, claims_view = (r.dir / "SPEC.md").read_bytes(), (r.dir / "SPEC-CLAIMS.md").read_bytes()
    r.ok("goal", "--id", "G9999", "--text", "A rule can act.")
    d = r.ok("oblige", "--text", "A checker accepts by replay.", "--answers", "G9999", "--serves", "SPEC-3-22")
    r.ok("project")
    snap, trust = Snapshot.read(r.dir / ".warrant" / "store"), r.rm.claims.trust()
    cm = CL.Model(snap, trust)
    doc = CL.Document(cm)
    node = r.path("G9999")["obligations"][0]
    check("P10", (r.dir / "SPEC.md").read_bytes() == spec and CL.render_spec(cm, doc.current).encode() == spec
          and (r.dir / "SPEC-CLAIMS.md").read_bytes() == claims_view and (r.dir / "ROADMAP.md").is_file()
          and b"A rule can act." not in spec and node["duty"] == d
          and node["serves"] == [{"duty": cm.current["SPEC-3-22"].doc["duty"], "claim": "SPEC-3-22", "goal": None}],
          "nothing of the roadmap renders into SPEC.md; a SPEC claim is named by its claim id and linked by its duty", node)
    r.close()


def check_cases():
    rows = []
    r = Repo()
    v = r.ok("goal", "--id", "G1", "--text", "One.", "--id", "G2", "--text", "Two.")
    r.ok("project")
    rows.append(("control", r.problems(), []))
    r.file("claude", "transition", R.transition("ATTESTED", opened=[{"text": "One again.", "scope": "roadmap:G1"}]))
    r.ok("project")
    rows.append(("fork", r.problems(), ["GOAL_FORK"]))
    r.close()

    r = Repo()
    v = r.ok("goal", "--id", "G1", "--text", "One.", "--id", "G2", "--text", "Two.")
    t = r.file("claude", "transition", R.transition("ATTESTED", established=["G1 reformulated: x"], supersedes=[v],
                                                    opened=[{"text": "One, better.", "scope": "roadmap:G1"}]))
    r.ok("project")
    rows.append(("dropped", r.problems(), ["GOAL_DROPPED"]))
    r.close()

    r = Repo()
    v = r.ok("goal", "--id", "G1", "--text", "One.")
    rev = {"schema": RM.REVISION, "goal": "G1", "act": "met", "because": "x", "refs": []}
    r.file("claude", "transition", R.transition("ATTESTED", [C.digest(C.canon(rev))], established=["something else"],
                                                supersedes=[v]), [rev])
    r.ok("project")
    rows.append(("met without its text", r.problems(), ["REVISION_SHAPE"]))
    r.close()

    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "One.")
    ref = r.path("G1")["formulations"][0]["ref"]
    r.file("claude", "duty", R.duty("claude", "Needs a ghost.", ["s0fractal"], {"attest": {}}, accept_by=["codex"],
                                    requires=["ab" * 32], answers=ref))
    r.ok("project")
    rows.append(("requires a duty not in the view", r.problems(), ["MISSING_LINK"]))
    r.close()

    r = Repo()
    r.file("claude", "transition", R.transition("ATTESTED", opened=[{"text": "Bad key.", "scope": "roadmap:G1\n"}]))
    r.ok("project")
    rows.append(("scope roadmap:G1\\n", r.problems(), ["GOAL_KEY"]))
    r.close()
    bad = [(label, got) for label, got, want in rows if got != want]
    check("P12", not bad, "check refuses a fork, a dropped goal, met without its text, a dangling link and a bad key", bad)

    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "One.")
    before = r.files()
    rcs = [r.run("goal", "--id", k, "--text", t)[0] for k, t in
           (("G0", "x"), ("G1\n", "x"), ("g2", "x"), ("G2", "two\nlines"), ("G2", " padded"), ("G1", "again"))]
    rcs += [r.run("oblige", "--text", "x", "--answers", g)[0] for g in ("G9", "G1\n", "1234")]
    rcs += [r.run("oblige", "--text", "x", "--answers", "G1", "--requires", "SPEC-1-1")[0]]
    check("P13", rcs == [2] * len(rcs) and r.files() == before,
          "commands refuse a bad key (\\Z, not $), a multi-line text, a reopened goal, an unknown goal or duty; "
          "nothing is written", rcs)
    r.close()


def due(r, actor="codex"):
    """The closures `roadmap.py due` names for `actor`."""
    return [d["closure"] for d in RM.acceptance_due(r.model(), actor)]


def due_cases():
    # P21: a closure whose prerequisite is not DISCHARGED is not due; once it is, the next reading names it.
    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "The ledger exists.")
    a = r.ok("oblige", "--text", "Counter blobs are accepted from any key.", "--answers", "G1")
    b = r.ok("oblige", "--text", "A witness ledger is derived from the records.", "--answers", "G1", "--requires", a)
    tb = r.ok("done", "--duty", b, "--established", "the ledger is built", "--ref", "s0fractal/warrant#1")
    alone = due(r)
    ta = r.ok("done", "--duty", a, "--established", "counter@1 from any key", "--ref", "s0fractal/warrant#2",
              "--commit", "c" * 40)
    both = due(r)
    r.accept(ta)
    after = due(r)
    r.accept(tb)
    check("P21", alone == [] and both == [ta] and after == [tb] and due(r) == [],
          "a closure whose required duty is not DISCHARGED is not due for the acceptor's verdict; once the prerequisite's "
          "closure is accepted, the dependent closure is due, and an accepted one is not", (alone, both, after))
    rc, out, _ = r.run("due", "--actor", "codex", "--json")
    r.close()

    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "The ledger exists.")
    d = r.ok("oblige", "--text", "One thing.", "--answers", "G1")
    t = r.ok("done", "--duty", d, "--established", "done", "--ref", "s0fractal/warrant#3", "--commit", "d" * 40)
    got = r.run("due", "--actor", "codex", "--json")
    bad = r.run("due", "--actor", "codex\n")[0]
    doc = json.loads(got[1])
    one = doc["due"][0] if len(doc["due"]) == 1 else {}
    ev = r.model().recs[t]["body"]["closes"][0]["evidence"]
    check("P31", rc == 0 and json.loads(out)["due"] == [] and got[0] == 0 and doc["actor"] == "codex" and bad == 2
          and (one.get("duty"), one.get("closure"), one.get("item"), one.get("goal"), one.get("evidence"), one.get("refs"),
               one.get("subject"), one.get("requires")) == (d, t, 0, "G1", ev, ["s0fractal/warrant#3"], "d" * 40, [])
          and "established" not in one,
          "`due --actor A --json` names each due closure with its duty, goal, evidence ids, the references its evidence "
          "blob names and its subject, never what it says it established; a bad actor id is refused", (out, got, bad))
    r.close()

    # P22: a closure the acceptor accepted is not due: with one acceptor it is admitted; with two, it waits for the
    # other, who is due and the first is not.
    r = Repo()
    q = r.ok("goal", "--id", "G1", "--text", "The ledger exists.")
    d = r.ok("oblige", "--text", "One thing.", "--answers", "G1")
    t = r.ok("done", "--duty", d, "--established", "done", "--ref", "s0fractal/warrant#3")
    r.accept(t)
    single = due(r)
    two = r.file("claude", "duty", R.duty("claude", "Two acceptors.", ["s0fractal"], {"attest": {}},
                                          accept_by=["codex", "s0fractal"], answers=q + ":0"))
    t2 = r.ok("done", "--duty", two, "--established", "done", "--ref", "s0fractal/warrant#4")
    before = due(r)
    r.accept(t2)
    check("P22", single == [] and before == [t2] and due(r) == [] and due(r, "s0fractal") == [t2],
          "a closure the acceptor accepted is not due for it: admitted, or waiting only for the other acceptor",
          (single, before, due(r), due(r, "s0fractal")))

    # P23: a closure whose duty does not name the acceptor in accept_by is not due for it.
    other = r.file("claude", "duty", R.duty("claude", "The owner accepts this.", ["s0fractal"], {"attest": {}},
                                            accept_by=["s0fractal"], answers=q + ":0"))
    t3 = r.ok("done", "--duty", other, "--established", "done", "--ref", "s0fractal/warrant#5")
    check("P23", t3 not in due(r) and sorted(due(r, "s0fractal")) == sorted([t2, t3]),
          "a closure whose duty's accept_by does not name codex is not due for codex (it is for its own acceptor)",
          (due(r), due(r, "s0fractal")))
    r.close()

    # P24: a closure the acceptor challenged is not due for it; another actor's challenge changes nothing.
    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "The ledger exists.")
    d = r.ok("oblige", "--text", "One thing.", "--answers", "G1")
    e = r.ok("oblige", "--text", "Another thing.", "--answers", "G1")
    t = r.ok("done", "--duty", d, "--established", "done", "--ref", "s0fractal/warrant#3")
    u = r.ok("done", "--duty", e, "--established", "done", "--ref", "s0fractal/warrant#4")
    ev = r.model().recs[t]["body"]["evidence"]
    r.file("codex", "challenge", R.challenge(t, "the evidence names no commit", ev, 0))
    r.file("stranger", "challenge", R.challenge(u, "I disagree", ev, 0))
    check("P24", due(r) == [u], "a closure codex challenged is not due for codex's verdict; a stranger's challenge hides "
          "nothing", due(r))

    # P25: a closure filed over (done --replaces) is not due; the one filed instead is.
    t2 = r.ok("done", "--duty", d, "--established", "done", "--ref", "s0fractal/warrant#3", "--ref", "a" * 40,
              "--replaces", t)
    f = r.ok("oblige", "--text", "A third thing.", "--answers", "G1")
    s1 = r.ok("done", "--duty", f, "--established", "done", "--ref", "s0fractal/warrant#6")
    s2 = r.ok("done", "--duty", f, "--established", "done", "--ref", "s0fractal/warrant#6", "--ref", "b" * 40,
              "--replaces", s1)
    check("P25", sorted(due(r)) == sorted([u, t2, s2]),
          "of a duty's closures waiting for acceptance only the latest is due: an earlier one was filed over (records "
          "filed in one second are named in id order)", due(r))

    # P27: once the closure filed in its place is accepted, the filed-over one stays not due (Codex finding
    # aeacfd5c933e on 41a1073: it was the duty's only PENDING closure left, and read as due).
    r.accept(s2)                # s1, filed over by s2, was never challenged
    check("P27", r.model().rep["duties"][f]["disposition"] == "DISCHARGED" and sorted(due(r)) == sorted([u, t2])
          and s1 not in due(r),
          "accepting a replacement leaves neither it nor the closure it was filed over due", due(r))

    # P30: a filed-over closure is not due while the one filed in its place is refused (here OBSERVED where the duty
    # admits an attestation: OVERCLAIMED); the duty stays OPEN and waits for its holder.
    k = r.ok("oblige", "--text", "A fifth thing.", "--answers", "G1")
    k1 = r.ok("done", "--duty", k, "--established", "done", "--ref", "s0fractal/warrant#12")
    ev = {"schema": RM.EVIDENCE, "duty": k, "refs": ["s0fractal/warrant#12", "a" * 40]}
    r.store.put_json(ev)
    h = C.digest(C.canon(ev))
    k2 = r.store.put_record(R.record("transition", "claude", r.at() + 1, R.transition(
        "OBSERVED", [h], closes=[R.item(k, "discharge", [h])], established=["again"])), r.keys["claude"])
    ks = [(c["transition"], c["verdict"]) for c in r.model().rep["duties"][k]["candidates"]]
    check("P30", ks == [(k1, "PENDING"), (k2, "OVERCLAIMED")] and k1 not in due(r) and k2 not in due(r),
          "a closure filed over stays not due while the closure filed in its place is refused", (ks, due(r)))
    r.close()

    # P28: a challenge of item k hides closure k only; one of item null concerns the transition's results (SPEC §3.6).
    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "The ledger exists.")
    d, e, g = (r.ok("oblige", "--text", x, "--answers", "G1") for x in ("One thing.", "Another thing.", "A third thing."))
    ev = {"schema": RM.EVIDENCE, "duty": d, "refs": ["s0fractal/warrant#7"]}
    h = C.digest(C.canon(ev))
    two = r.file("claude", "transition", R.transition("ATTESTED", [h], closes=[R.item(d, "discharge", [h]),
                                                                           R.item(e, "discharge", [h])],
                                                      established=["both"]), [ev])
    tg = r.ok("done", "--duty", g, "--established", "done", "--ref", "s0fractal/warrant#8")
    r.file("codex", "challenge", R.challenge(two, "item 1 is not done", [h], 1))
    r.file("codex", "challenge", R.challenge(tg, "about the results", r.model().recs[tg]["body"]["evidence"], None))
    items = sorted((x["closure"], x["item"]) for x in RM.acceptance_due(r.model(), "codex"))
    check("P28", items == sorted([(two, 0), (tg, 0)]),
          "codex's challenge of item 1 of a transition hides that item only, and a challenge of a transition's results "
          "(item null) hides none of its closures", items)

    # P29: a closure of a duty already DISCHARGED is not due, even when it is the duty's latest.
    hd = r.ok("oblige", "--text", "A fourth thing.", "--answers", "G1")
    th1 = r.ok("done", "--duty", hd, "--established", "done", "--ref", "s0fractal/warrant#10")
    r.accept(th1)
    ev2 = {"schema": RM.EVIDENCE, "duty": hd, "refs": ["s0fractal/warrant#11"]}
    h2 = C.digest(C.canon(ev2))
    r.store.put_json(ev2)            # one second later: same-second records are ordered by id
    th2 = r.store.put_record(R.record("transition", "claude", r.at() + 1, R.transition(
        "ATTESTED", [h2], closes=[R.item(hd, "discharge", [h2])], established=["again"])), r.keys["claude"])
    m = r.model()
    last = [c for c in m.rep["duties"][hd]["candidates"]][-1]
    check("P29", m.rep["duties"][hd]["disposition"] == "DISCHARGED" and last["transition"] == th2
          and last["verdict"] == "PENDING" and th2 not in due(r) and th1 not in due(r),
          "a closure filed on a duty that is already DISCHARGED is not due, though it is the duty's latest and PENDING",
          (last, due(r)))
    r.close()


GROUPS = ((goal_cases, ("P1", "P2")), (source_cases, ("P16",)), (requires_cases, ("P3", "P14", "P4", "P5", "P15")), (supersede_cases, ("P6", "P7")),
          (shared_cases, ("P17", "P18")), (cycle_cases, ("P19", "P20")), (projection_cases, ("P8",)), (forward_attack_cases, ("P9", "P11")), (spec_cases, ("P10",)),
          (check_cases, ("P12", "P13")), (due_cases, ("P21", "P31", "P22", "P23", "P24", "P25", "P27", "P30", "P28", "P29")))


def main():
    from world import results
    for group, ids in GROUPS:
        try:
            group()
        except Exception as e:      # noqa: BLE001  a refused command inside a case fails that group's cases
            for cid in ids:
                if cid not in results:
                    check(cid, False, f"{group.__name__} raised", f"{type(e).__name__}: {e}")
    return finish("ROADMAP")


if __name__ == "__main__":
    sys.exit(main())
