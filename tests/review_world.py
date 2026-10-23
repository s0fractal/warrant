"""Fixtures of the review loop tests (reviews_test, review_merge_test, review_replay_test): a Git
repository whose store only the review loop uses, its seeds beside it, and the tool driven through
its command line in process (tools/review.py, tools/claimslib/reviews.py)."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from world import R, W
from warrant import bindings as B
from warrant import engine as E
from warrant import jcs as C
from warrant.store import Store

ROOT = Path(__file__).resolve().parents[1]
_tools = Path(os.environ["WARRANT_IMPL"]) / "tools" if os.environ.get("WARRANT_IMPL") else None
sys.path.insert(0, str(_tools if _tools is not None and (_tools / "claimslib").is_dir() else ROOT / "tools"))

from claimslib import review_replay as RR         # noqa: E402
from claimslib import reviews as RV               # noqa: E402

ACTORS = ("claude", "codex", "stranger")
REPO = "s0fractal/warrant"
GIT = ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@invalid", "-c", "commit.gpgsign=false",
       "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-c", "init.defaultBranch=master"]
BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
FINDING_TEST = ('import json, os, sys\nsys.path.insert(0, os.environ["WARRANT_IMPL"])\nimport calc\n'
                'json.dump({"F1": "PASS" if calc.add(2, 2) == 4 else "FAIL"}, open(os.environ["WARRANT_RESULTS"], "w"))\n')
CRASHING_TEST = 'import no_such_module_here\n'


def new_file_patch(path, text):
    lines = text.splitlines()
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{x}\n" for x in lines))


def finding_test(name="finding_test", text=FINDING_TEST, case="F1"):
    return {"file": name, "case": case, "patch": new_file_patch(f"tests/{name}.py", text)}


class Fixture:
    """A Git repository whose store only the review loop uses, its seeds beside it."""

    def __init__(self):
        self.base = Path(tempfile.mkdtemp(prefix="warrant-reviews-"))
        self.dir = self.base / "repo"
        (self.dir / ".warrant").mkdir(parents=True)
        self.keys = {a: W.Key.generate() for a in ACTORS}
        self.replayer = RR.actor()
        self.keys[self.replayer] = W.Key.generate()
        self.seeds = {}
        for i, (a, k) in enumerate(self.keys.items()):
            p = self.base / f"seed-{i}"
            p.write_text(k.seed_hex() + "\n")
            self.seeds[a] = str(p)
        self.bind(list(self.keys.items()))
        roles = {"claude": self.keys["claude"].public, "codex": self.keys["codex"].public, "s0fractal": None,
                 "readers": B.COLLECTIVE, self.replayer: self.keys[self.replayer].public}
        (self.dir / ".warrant" / "roles.json").write_text(json.dumps({"roles": B.ROLES, "actors": roles}))
        self.config()
        (self.dir / ".warrant" / "roadmap.json").write_text(json.dumps(
            {"roadmap": "warrant-roadmap/config@1", "owed_to": ["s0fractal"], "accept_by": ["codex"],
             "results_accept_by": ["codex"]}) + "\n")
        Store(self.dir / ".warrant" / "store").init()
        (self.dir / "tests").mkdir()
        (self.dir / "calc.py").write_text(BUGGY)
        (self.dir / "tests" / "calc_test.py").write_text("# the fixture's own suite\n")
        self.git("init", "-q")
        self.start = self.commit("base")
        self.clock = None

    def config(self, **kw):
        cfg = {"reviews": RV.CONFIG, "repository": REPO, "owed_to": ["s0fractal"], "accept_by": ["codex"],
               "replayers": [self.replayer]}
        cfg.update(kw)
        (self.dir / ".warrant" / "reviews.json").write_text(json.dumps(cfg) + "\n")

    def bind(self, pairs):
        doc = {"bindings": B.BINDINGS, "keys": [{"actor": a, "public": k.public, "proof": B.binding_proof(k, a)}
                                                for a, k in pairs]}
        (self.dir / ".warrant" / "trust.json").write_bytes(C.canon(doc))

    def git(self, *args):
        return subprocess.run([*GIT, "-C", str(self.dir), *args], capture_output=True, check=True).stdout.decode().strip()

    def commit(self, msg, files=None):
        for path, text in (files or {}).items():
            (self.dir / path).parent.mkdir(parents=True, exist_ok=True)
            (self.dir / path).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def run(self, *argv, actor="claude"):
        """(exit status, stdout, stderr) of one tool command, signed by `actor`."""
        sign = []
        if argv[0] == "replay" and "--verify" not in argv:
            sign = ["--key", self.seeds[self.replayer]]
        elif argv[0] not in ("project", "check", "replay"):
            sign = ["--key", self.seeds[actor], "--actor", actor]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = RV.main(["--root", str(self.dir), argv[0], *sign, *argv[1:]])
        return rc, out.getvalue().strip(), err.getvalue()

    def ok(self, *argv, actor="claude"):
        rc, out, err = self.run(*argv, actor=actor)
        if rc != 0:
            raise AssertionError(f"{argv[0]} refused: {err.strip()}")
        return out

    def code(self, *argv, actor="claude"):
        """The refusal code of a command, and whether the store stayed as it was."""
        before = self.files()
        rc, _, err = self.run(*argv, actor=actor)
        code = err.split()[1] if rc == 2 and err.startswith("REFUSED ") else None
        return code, self.files() == before

    def rv(self):
        return RV.Reviews(self.dir)

    def model(self):
        return self.rv().model()

    def problems(self, base=None):
        return [c for c, _ in RV.check(self.rv(), base)]

    def files(self):
        root = self.dir / ".warrant" / "store"
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}

    def at(self):
        return max([int(time.time())] + [r["at"] for r in self.model().recs.values()])

    def put(self, actor, rtype, body, blobs=(), key=None, at=None):
        """A record filed by hand (as an agent through MCP could), chained on `actor`'s head."""
        store = Store(self.dir / ".warrant" / "store")
        for doc in blobs:
            store.put_json(doc)
        k = key or self.keys[actor]
        trust = self.rv().repo.trust() if key is None else None
        if trust is None:
            return store.put_record(R.record(rtype, actor, at or self.at(), body), k)
        return store.append(rtype, actor, at or self.at(), body, k, trust)

    def save(self):
        """Commit the records and their views on top of HEAD: what the author pushes."""
        self.ok("project")
        return self.commit("records")

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)


def started(pr=1):
    """A fixture with #pr opened and its buggy head H1 filed."""
    f = Fixture()
    f.h1 = f.commit("the change", {"calc.py": BUGGY + "\n# a change\n"})
    f.duty = f.ok("open", "--pr", str(pr), "--title", "Add numbers")
    f.t1 = f.ok("head", "--pr", str(pr), "--commit", f.h1)
    f.save()
    return f


def head_of(m, pr, n):
    return m.reviews[pr].heads[n - 1]


def reliance(f, duty, commit):
    """The engine's reliance on the duty for a receiver whose current revision is `commit`."""
    m = f.model()
    as_of = max(r["at"] for r in m.recs.values())
    return E.reliance(E.assess(m.snap, f.rv().repo.trust(), as_of, E.profile(), current=[commit]), duty, "act")["state"]


def _write(path, text):
    path.write_text(text)
    return path


def merge(f, branch_tip, msg="Merge pull request"):
    """Merge `branch_tip` into master with a merge commit (what GitHub does), master checked out after."""
    f.git("checkout", "-q", "master")
    f.git("merge", "-q", "--no-ff", "-m", msg, branch_tip)
    return f.git("rev-parse", "HEAD")


def branch(f, name):
    f.git("checkout", "-q", "-b", name)
