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
        sign = ["--key", self.seeds[actor], "--actor", actor] if argv[0] not in ("path", "project", "check") else []
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


def requires_cases():
    r = Repo()
    r.ok("goal", "--id", "G1", "--text", "The ledger exists.")
    a = r.ok("oblige", "--text", "Counter blobs are accepted from any key.", "--answers", "G1")
    b = r.ok("oblige", "--text", "A witness ledger is derived from the records.", "--answers", "G1", "--requires", a[:10])
    tb = r.ok("done", "--duty", b, "--established", "the ledger is built", "--ref", "s0fractal/warrant#1")
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
          and [(f["state"], f["text"]) for f in p2["formulations"]] == [("REFORMULATED", "Unchanged goal."), ("CURRENT", "Unchanged goal.")]
          and p2["formulations"][1]["ref"].startswith(s + ":") and v != s and r.problems() == ["ROADMAP_MISSING"],
          "a goal is reformulated by a superseding transition: pending until accepted, then the old formulation is "
          "REFORMULATED, its obligations stay under the goal, the other goals are opened again unchanged", p)

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
          and len(served) == 2 and all(helper[:12] in ln and "G2" in ln for ln in served),
          "path prints the goal, its formulations, each obligation, under it its prerequisites, and the duties "
          "that serve a node with the goal they answer", lines)
    r.close()


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


GROUPS = ((goal_cases, ("P1", "P2")), (requires_cases, ("P3", "P4", "P5")), (supersede_cases, ("P6", "P7")),
          (projection_cases, ("P8",)), (forward_attack_cases, ("P9", "P11")), (spec_cases, ("P10",)),
          (check_cases, ("P12", "P13")))


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
