#!/usr/bin/env python3
"""`tools/claims.py why`: from a source statement to its claims, obligations and goals.

Each case reads one fixture repository: a module warrant/fx.py, a mutant harness
whose mutants edit it, claims filed by claude citing those mutants (BACKED, UNBACKED,
superseded), and a roadmap whose obligations serve or require the claims' duties.
Counters are replayed by a stub (`replaying`: a fixed set of blobs replays); the claims
selftest replays a real one. `why` runs through its command line with --json; cases assert on the data (status,
statement indices, claim ids, obligation ids, goal keys, refusal codes), never on
wording, so a mutant is killed only when a rule of the mapping stops holding.

    python3 tests/why_test.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from world import R, W, check, finish
from warrant import jcs as C
from warrant.store import Store

ROOT = Path(__file__).resolve().parents[1]


def _tool(name):
    impl = Path(os.environ["WARRANT_IMPL"]) / "tools" / name if os.environ.get("WARRANT_IMPL") else None
    path = impl if impl is not None and impl.is_file() else ROOT / "tools" / name
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name[:-3]] = mod
    spec.loader.exec_module(mod)
    return mod


CL = _tool("claims.py")
RM = _tool("roadmap.py")

ACTORS = ("claude", "codex", "s0fractal", "stranger")
PINS = {"claims": "warrant-claims/pins@1", "source": "SPEC.md", "sections": [], "sentences": {}, "headings": {},
        "owed_to": ["readers"], "accept_by": ["codex"]}
ROADMAP = {"roadmap": "warrant-roadmap/config@1", "owed_to": ["s0fractal"], "accept_by": ["codex"],
           "results_accept_by": ["codex"]}

FX = '''"""Fixture module: its docstring is no statement."""
import os


def admit(x):
    # a comment is no statement
    if x > 0:
        return "ok"
    return "no"


def total(xs):
    out = 0
    for v in xs:
        out += v
    return out


def spread(a,
           b):
    return os.path.join(a,
                        b)


def tiny():
    return 1
'''

# The harness: (id, file, what, edits, test, targets), as tests/mutants.py.
HARNESS = [
    ("M01", "fx.py", "admits zero", [("    if x > 0:\n", "    if x >= 0:\n")], "fx_test", ["F1"]),
    ("M02", "fx.py", "refuses nothing", [('    return "no"\n', '    return "ok"\n')], "fx_test", ["F2"]),
    ("M03", "fx.py", "the sum starts at one", [("    out = 0\n", "    out = 1\n")], "fx_test", ["F3"]),
    ("M04", "fx.py", "the sum is negated (an insertion)", [("    return out\n", "    out = -out\n    return out\n")],
     "fx_test", ["F4"]),
    ("M05", "fx.py", "the sum subtracts", [("        out += v\n", "        out -= v\n")], "fx_test", ["F5"]),
    ("M06", "fx.py", "the second part is dropped", [("                        b)\n", "                        a)\n")],
     "fx_test", ["F6"]),
    ("M07", "fx.py", "tiny returns two", [("    return 1\n", "    return 2\n")], "fx_test", ["F7"]),
]


def line_of(text):
    """The number of the one line of FX that is `text` once stripped."""
    hits = [i + 1 for i, ln in enumerate(FX.splitlines()) if ln.strip() == text]
    assert len(hits) == 1, text
    return hits[0]


class Fix:
    """The fixture repository: module, harness, claims, roadmap."""

    def __init__(self, roadmap=True):
        self.base = Path(tempfile.mkdtemp(prefix="warrant-why-"))
        self.dir = self.base / "repo"
        for d in (".warrant", "warrant", "tests", "tools"):
            (self.dir / d).mkdir(parents=True)
        (self.dir / "warrant" / "fx.py").write_text(FX)
        (self.dir / "tools" / "broken.py").write_text("def broken(:\n")
        (self.base / "outside.py").write_text("x = 1\n")
        (self.dir / "tests" / "mutants.py").write_text(f"MUTANTS = {HARNESS!r}\n")
        (self.dir / "tests" / "fx_test.py").write_text("CASES = " + repr([f"F{i}" for i in range(1, 8)]) + "\n")
        Store(self.dir / ".warrant" / "store").init()
        (self.dir / ".warrant" / "claims.json").write_text(json.dumps(PINS))
        if roadmap:
            (self.dir / ".warrant" / "roadmap.json").write_text(json.dumps(ROADMAP))
        self.keys = {a: W.Key.generate() for a in ACTORS}
        self.seeds = {}
        for a, k in self.keys.items():
            p = self.base / f"{a}.seed"
            p.write_text(k.seed_hex() + "\n")
            self.seeds[a] = str(p)
        keys = [{"actor": a, "public": k.public, "proof": CL.binding_proof(k, a)} for a, k in self.keys.items()]
        (self.dir / ".warrant" / "trust.json").write_bytes(C.canon({"bindings": CL.BINDINGS, "keys": keys}))
        roles = {a: k.public for a, k in self.keys.items() if a != "stranger"}
        roles["readers"] = CL.COLLECTIVE
        (self.dir / ".warrant" / "roles.json").write_text(json.dumps({"roles": CL.ROLES, "actors": roles}))
        self.repo = CL.Repo(self.dir)
        au = CL.Author(self.repo, self.keys["claude"], "claude", validate=False)
        au.claim("SPEC-1-1", "Zero is refused.", ["fx_test:F1"], ["M01"])
        au.claim("SPEC-1-2", "Only a positive number is admitted.", ["fx_test:F1", "fx_test:F2"], ["M01", "M02"])
        au.claim("SPEC-1-3", "The sum starts at zero.", [], ["M03"], unbacked_because="fixture: no witness yet")
        au.claim("SPEC-1-4", "The sum keeps its sign.", ["fx_test:F4"], ["M04"])
        au.claim("SPEC-1-5", "The sum adds.", ["fx_test:F5"], ["M05"])
        old = CL.Model(self.repo.snapshot(), self.repo.trust()).current["SPEC-1-5"]
        au.claim("SPEC-1-5", "The sum adds.", ["fx_test:F2"], ["M02"], because="fixture: re-backed", previous=old)
        au.claim("SPEC-1-6", "Both parts are joined.", ["fx_test:F6"], ["M06"])
        au.claim("SPEC-1-7", "Tiny returns one.", ["fx_test:F7"], ["M07"])
        # A stranger's counter that replays lowers SPEC-1-7 (COUNTERED); one that does not is a thesis
        # against SPEC-1-1 and lowers nothing. Which blobs replay is the stub's set (`replaying`).
        cur = CL.Model(self.repo.snapshot(), self.repo.trust()).current
        self.counters = {cid: self.counter(cur[cid]) for cid in ("SPEC-1-7", "SPEC-1-1")}
        self.lowering = self.challenge(cur["SPEC-1-7"], self.counters["SPEC-1-7"])
        self.thesis = self.challenge(cur["SPEC-1-1"], self.counters["SPEC-1-1"])
        self.replays = {self.counters["SPEC-1-7"]}
        self.obligations = {}
        if roadmap:
            self.tool(RM, "goal", "--id", "G1", "--text", "Numbers are admitted by rule.",
                      "--id", "G2", "--text", "Paths keep their parts.")
            self.obligations["serves"] = self.tool(RM, "oblige", "--text", "The admission rule is witnessed.",
                                                   "--answers", "G1", "--serves", "SPEC-1-1")
            self.obligations["requires"] = self.tool(RM, "oblige", "--text", "Joining is witnessed.",
                                                     "--answers", "G2", "--requires", "SPEC-1-6")
            self.obligations["none"] = self.tool(RM, "oblige", "--text", "Something else.", "--answers", "G1")
            self.obligations["countered"] = self.tool(RM, "oblige", "--text", "Tiny is witnessed.", "--answers", "G2",
                                                      "--serves", "SPEC-1-7")

    def counter(self, n):
        return Store(self.repo.store_dir).put_json({"counter": CL.COUNTER, "claim": n.id, "against": n.tid, "patch": "",
                                                    "passes": n.doc["witnesses"], "fails": ["fx_test:F1"], "why": "fixture"})

    def challenge(self, n, h, actor="stranger"):
        at = max(r["at"] for r in CL.Model(self.repo.snapshot(), self.repo.trust()).recs.values()) + 1
        body = R.challenge(n.tid, "fixture counter", [h], 0)
        return Store(self.repo.store_dir).put_record(R.record("challenge", actor, at, body), self.keys[actor])

    def tool(self, mod, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = mod.main(["--root", str(self.dir), argv[0], "--key", self.seeds["claude"], "--actor", "claude", *argv[1:]])
        assert rc == 0, argv
        return out.getvalue().strip()

    def why(self, *argv, as_json=True):
        """(exit status, the --json answer or the text printed, the refusal code or None)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CL.main(["--root", str(self.dir), "why", *argv] + (["--json"] if as_json else []))
        code = err.getvalue().split()[1] if rc == 2 and err.getvalue().startswith("REFUSED ") else None
        return rc, json.loads(out.getvalue()) if rc == 0 and as_json else out.getvalue(), code

    def at(self, line):
        rc, d, _ = self.why(f"warrant/fx.py:{line}")
        assert rc == 0, line
        return d

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)


@contextlib.contextmanager
def replaying(blobs):
    """Stub the counter replay: a counter blob replays iff it is in `blobs`."""
    real = CL.counters.replay_counter
    CL.counters.replay_counter = lambda repo, snap, h, p: None if h in blobs else "fixture: does not replay"
    try:
        yield
    finally:
        CL.counters.replay_counter = real


def ids(d, key, field):
    return [x[field] for x in d[key]]


def main():
    fx = Fix()
    try:
        with replaying(fx.replays):
            cases(fx)
    finally:
        fx.close()
    bare = Fix(roadmap=False)
    try:
        with replaying(bare.replays):
            d = bare.at(line_of("if x > 0:"))
        check("Y11", d["status"] == "CLAIMED" and ids(d, "claims", "claim") == ["SPEC-1-1", "SPEC-1-2"]
              and d["obligations"] == [] and d["goals"] == [],
              "without a roadmap the claims are still answered, with no obligation", d)
    finally:
        bare.close()
    return finish("why_test")


def cases(fx):
    """Y1-Y10 and Y12-Y16, on the fixture with a roadmap, counters replaying by the stub."""
    units = CL.statement_lines(FX)
    own = {i: sorted(o) for i, (_, _, o) in enumerate(units)}
    index = {ln: i for i, o in own.items() for ln in o}

    d = fx.at(line_of("if x > 0:"))
    check("Y1", d["status"] == "CLAIMED" and ids(d, "statements", "index") == [index[line_of("if x > 0:")]]
          and ids(d, "claims", "claim") == ["SPEC-1-1", "SPEC-1-2"]
          and ids(d, "obligations", "obligation") == [fx.obligations["serves"]]
          and d["obligations"][0]["relation"] == "serves" and d["obligations"][0]["claims"] == ["SPEC-1-1"]
          and ids(d, "goals", "goal") == ["G1"],
          "a covered statement maps to the claims citing its mutant, their obligations and goals", d)

    d = fx.at(line_of('return "no"'))
    check("Y2", d["status"] == "CLAIMED" and ids(d, "claims", "claim") == ["SPEC-1-2", "SPEC-1-5"]
          and [c["via"] for c in d["claims"]] == [["M02"], ["M02"]] and d["obligations"] == [] and d["goals"] == [],
          "a statement two claims cite through one mutant maps to both, and to no obligation of another claim", d)

    d = fx.at(line_of("out = 0"))
    check("Y3", d["status"] == "NO_CLAIM" and d["claims"] == [] and d["statements"][0]["mutants"] == ["M03"]
          and d["statements"][0]["cited"] == [],
          "a statement only an UNBACKED claim's mutant changes has no claim", d)

    d = fx.at(line_of("return out"))
    check("Y4", d["status"] == "NO_CLAIM" and d["claims"] == [] and d["statements"][0]["mutants"] == []
          and d["statements"][0]["inserted_before"] == ["M04"],
          "a mutant inserting before a statement does not change it", d)

    d = fx.at(line_of("out += v"))
    check("Y5", d["status"] == "NO_CLAIM" and d["claims"] == [] and d["statements"][0]["mutants"] == ["M05"],
          "the mutant of a superseded claim covers nothing", d)

    quiet = [fx.at(line_of("# a comment is no statement")), fx.at(1), fx.at(line_of("def admit(x):") - 1)]
    check("Y6", [q["status"] for q in quiet] == ["NOT_A_STATEMENT"] * 3 and all(q["statements"] == [] for q in quiet),
          "a comment, a docstring or a blank line is not a statement", quiet)

    a, b = fx.at(line_of("return os.path.join(a,")), fx.at(line_of("b)"))
    check("Y7", a["status"] == b["status"] == "CLAIMED" and ids(a, "statements", "index") == ids(b, "statements", "index")
          and len(b["statements"]) == 1 and ids(b, "claims", "claim") == ["SPEC-1-6"]
          and ids(b, "obligations", "obligation") == [fx.obligations["requires"]]
          and b["obligations"][0]["relation"] == "requires" and ids(b, "goals", "goal") == ["G2"],
          "a statement's continuation line is that statement; an obligation that requires its claim is found", (a, b))

    rc, u, _ = fx.why("--uncovered")
    covered = {line_of(t) for t in ("if x > 0:", 'return "no"', "return os.path.join(a,")}
    listed = {s["line"] for s in u["uncovered"]} if rc == 0 else set()
    check("Y8", rc == 0 and u["files"] == ["warrant/fx.py"] and u["statements"] == len(units) == 14
          and u["covered"] == 3 and listed == {min(o) for o in own.values()} - covered
          and [(f["function"], f["statements"]) for f in u["functions"]] == [("total", 5), ("tiny", 2)],
          "--uncovered lists the statements no cited mutant changes, and the wholly uncovered functions largest first", u)

    refusals = [fx.why(t)[::2] for t in ("/etc/hosts:1", "../outside.py:1", "warrant/fx.py:999", "warrant/fx.py",
                                         "warrant/fx.py:7\n", "warrant/fx.py:0", "tools/broken.py:1")]
    refusals.append(fx.why("--uncovered", "../outside.py")[::2])
    refusals.append(fx.why()[::2])
    check("Y9", refusals == [(2, "WHY_FILE"), (2, "WHY_FILE"), (2, "WHY_LINE"), (2, "WHY_USAGE"), (2, "WHY_USAGE"),
                             (2, "WHY_USAGE"), (2, "WHY_FILE"), (2, "WHY_FILE"), (2, "WHY_USAGE")],
          "a file outside the source roots, a missing line or a malformed FILE:LINE is refused", refusals)

    # Y17: --uncovered DIR is the files of the source roots under that directory, nothing else; a prefix
    # that is not a directory, a directory outside the roots and one holding no such file are refused
    dirs = [fx.why("--uncovered", d) for d in ("warrant", "warrant/", str(fx.dir / "warrant"))]
    bad = [fx.why("--uncovered", d)[::2] for d in ("warr", "tests", "..", "tools")]
    check("Y17", all(r[0] == 0 and r[1]["files"] == ["warrant/fx.py"] and r[1]["statements"] == u["statements"]
                     and r[1]["covered"] == u["covered"] for r in dirs)
          and bad == [(2, "WHY_FILE")] * 4,
          "--uncovered DIR covers the files under that directory of the source roots; any other name is refused",
          ([r[:1] + (r[1].get("files") if isinstance(r[1], dict) else r[1],) for r in dirs], bad))

    rc, text, _ = fx.why(str(fx.dir / "warrant" / "fx.py") + f":{line_of('if x > 0:')}", as_json=False)
    check("Y10", rc == 0 and all(x in text for x in ("SPEC-1-1", "SPEC-1-2", fx.obligations["serves"][:12], "G1")),
          "an absolute path inside the repository is read; the text answer names the claims, obligation and goal", text)

    # AMEND 1: a claim a replaying counter lowered (COUNTERED, #170) is never backing.
    tiny = line_of("return 1")
    d = fx.at(tiny)
    low = d["countered"][0]["challenges"] if d["countered"] else []
    check("Y12", d["status"] == "NO_CLAIM" and d["claims"] == [] and ids(d, "countered", "claim") == ["SPEC-1-7"]
          and [(x["challenge"], x["counters"]) for x in low] == [(fx.lowering, [fx.counters["SPEC-1-7"]])]
          and d["obligations"] == [] and d["goals"] == [] and d["statements"][0]["cited"] == [],
          "a statement whose only claim is COUNTERED has no backing; the claim is named with its counter, "
          "and the obligation serving it is not reached", d)

    listed = {s["line"]: s["countered"] for s in u["uncovered"]} if rc == 0 else {}
    check("Y13", rc == 0 and listed.get(tiny) == ["SPEC-1-7"] and u["countered_only"] == 1 and u["covered"] == 3
          and all(v == [] for ln, v in listed.items() if ln != tiny),
          "--uncovered lists a statement covered only by a COUNTERED claim, names that claim, and counts it uncovered", u)

    model = CL.Model(fx.repo.snapshot(), fx.repo.trust())
    kinds = {ch: x["kind"] for ch, x in CL.challenge_table(fx.repo, model).items()}
    d = fx.at(line_of("if x > 0:"))
    check("Y14", kinds == {fx.lowering: "LOWERS", fx.thesis: "THESIS"} and "SPEC-1-1" in ids(d, "claims", "claim")
          and d["countered"] == [],
          "a stranger's challenge whose counter does not replay (a thesis) leaves the claim backing", (kinds, d))

    rows = {"M02": {"what": "x", "runs": {"fx_test": {"F1": "PASS", "F2": "FAIL"}}},
            "M07": {"what": "y", "runs": {"fx_test": {"F7": "PASS", "F1": "FAIL"}}}}
    blind, unknown = CL.audit(fx.repo, rows)
    pairs = sorted((b["claim"], b["mutant"]) for b in blind + unknown)
    check("Y15", ("SPEC-1-1", "M02") in pairs and not [p for p in pairs if p[0] == "SPEC-1-7"],
          "audit hunts blind witnesses of BACKED claims only: a COUNTERED claim is already shown blind", pairs)

    n7 = model.current["SPEC-1-7"]
    CL.Author(fx.repo, fx.keys["claude"], "claude", validate=False).claim(
        "SPEC-1-7", n7.doc["text"], ["fx_test:F1", "fx_test:F7"], ["M07"], because="fixture: re-backed", previous=n7)
    d = fx.at(tiny)
    check("Y16", d["status"] == "CLAIMED" and ids(d, "claims", "claim") == ["SPEC-1-7"] and d["countered"] == []
          and ids(d, "obligations", "obligation") == [fx.obligations["countered"]],
          "the author's re-backing makes the claim backing again, with its obligation", d)


if __name__ == "__main__":
    sys.exit(main())
