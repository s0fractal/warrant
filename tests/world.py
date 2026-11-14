"""Shared fixtures of the test files: deterministic keys, a check list that a mutant run reads, and a
repository directory with a Warrant 3 store (.warrant/records.jsonl, blobs/, v3.json) built through the
package's own Store, so every record is a real signed line."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from warrant import bootstrap as B          # noqa: E402
from warrant import engine as E             # noqa: E402
from warrant import keys as K               # noqa: E402
from warrant import records as R            # noqa: E402
from warrant.store import Store             # noqa: E402

FAILS = []
ACTORS = ("alice", "bob", "carol", "eve", "dave")
KEYS = {a: K.Key.from_seed_hex(f"{i + 1:02x}" * 32) for i, a in enumerate(ACTORS)}
ROLES = {"schema/author": ["alice"], "claim/verifier": ["carol"], "roadmap/acceptor": ["bob"], "roadmap/owner": ["dave"],
         "pr/acceptor": ["bob"], "pr/owner": ["dave"], "replayer": ["carol"]}


# The mutant harness (tests/mutants.py) runs one section of a test file, not all of it, and stops at its case's FAIL:
#   WARRANT_SECTION=a,b   run_sections runs only the sections (functions) of these names;
#   WARRANT_CASE_MAP=FILE  each check appends "<case id>\t<section>\n" to FILE: the map a clean run builds;
#   WARRANT_STOP=X,Y      the process ends (status 1) right after printing `FAIL X` or `FAIL Y`.
# Unset, a test file runs whole and nothing changes. The verdict is the printed `FAIL <case>` line either way.
SECTION = "main"


def check(name, ok, detail="", extra=None):
    """One case's verdict: `ok   ID ...` or `FAIL ID ...`; a mutant is killed only by a FAIL line of its case.
    check(ID, ok, what, detail) is the form with the id and its text apart."""
    if extra is not None:
        name, detail = f"{name} {detail}", extra
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {str(detail)[:300]}"), flush=True)
    case = str(name).split()[0] if str(name).split() else ""
    if os.environ.get("WARRANT_CASE_MAP"):
        with open(os.environ["WARRANT_CASE_MAP"], "a", encoding="utf-8") as f:
            f.write(f"{case}\t{SECTION}\n")
    if not ok:
        FAILS.append(name)
        if case in os.environ.get("WARRANT_STOP", "").split(","):
            sys.stdout.flush()
            os._exit(1)


def run_sections(sections):
    """Run a test file's sections (its *_cases functions) in order, or only those WARRANT_SECTION names; then
    finish(). A name that is no section of this file is refused (status 2), never a silent full run."""
    global SECTION
    if os.environ.get("WARRANT_LIST_SECTIONS"):
        print("SECTIONS " + " ".join(f.__name__ for f in sections), flush=True)
        return 0
    only = [x for x in os.environ.get("WARRANT_SECTION", "").split(",") if x]
    names = {f.__name__ for f in sections}
    unknown = [x for x in only if x not in names]
    if unknown:
        print(f"NO_SUCH_SECTION {unknown}", flush=True)
        return 2
    for f in sections:
        if only and f.__name__ not in only:
            continue
        SECTION = f.__name__
        f()
    SECTION = "main"
    return finish()


def finish(_name=None):
    print("all passed" if not FAILS else f"FAILED {len(FAILS)}: {' '.join(f.split()[0] for f in FAILS)}")
    return 1 if FAILS else 0


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
                          env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                                   GIT_COMMITTER_EMAIL="t@t", GIT_AUTHOR_DATE="2026-10-27T00:00:00Z",
                                   GIT_COMMITTER_DATE="2026-10-27T00:00:00Z")).stdout.strip()


class Repo:
    """A repository directory: `.warrant/v3.json` (trust of ACTORS' keys, profile `roles`), the bootstrap
    schemas filed by alice (schema/author, quorum 1), and records appended through Store.append."""

    def __init__(self, roles=None, base=None, git_init=False, name="s0fractal/warrant"):
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.home = Path(os.path.realpath(self.tmp.name))
        self.root = self.home / "repo"
        self.dot = self.root / ".warrant"
        self.dot.mkdir(parents=True)
        self.store = Store(self.dot).init()
        self.roles = roles or ROLES
        self.trust = {"warrant": "trust/3", "keys": {a: [k.public] for a, k in sorted(KEYS.items())}}
        self.profile = {"warrant": "profile/3", "roles": {r: sorted(a) for r, a in sorted(self.roles.items())}}
        self.write_config(name)
        self.t = 1_800_000_000
        self.schemas = {s["name"]: self.put("alice", "schema", s) for s in B.SCHEMAS}
        if git_init:
            git(self.root, "init", "-q", "-b", "master")
            self.commit("base")

    def write_config(self, name="s0fractal/warrant"):
        doc = {"warrant": "repository/3", "repository": name, "trust": self.trust, "profile": self.profile}
        (self.dot / "v3.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")

    def seed(self, actor):
        p = self.home / "keys" / f"{actor}.seed"
        p.parent.mkdir(exist_ok=True)
        p.write_text(KEYS[actor].seed_hex())
        return p

    def put(self, actor, kind, body, schema=None, lineage=None, refs=(), guard=None, at=None):
        self.t += 1
        r = R.record(kind, actor, self.t if at is None else at, body, schema, lineage, refs, guard)
        return self.store.append(r, KEYS[actor], self.trust)

    def attest(self, actor, target, **body):
        return self.put(actor, "attest", dict({"verdict": "accept"}, **body, target=target), refs=[target])

    def entity(self, actor, schema, body, lineage=None, refs=(), guard="default", requires=()):
        s = next(x for x in B.SCHEMAS if x["name"] == schema)
        g = (s["states"] or {}).get(body.get("state")) if guard == "default" else guard
        if g is not None and requires:
            g = dict(g, requires=sorted(set(g["requires"]) | set(requires)))
        refs = sorted(set(refs) | R.body_refs(s["fields"], body))
        return self.put(actor, "entity", body, schema, lineage, refs, g)

    def blob(self, data):
        return self.store.put_blob(data if isinstance(data, bytes) else json.dumps(data, sort_keys=True).encode())

    def report(self):
        return E.assess(self.store.snapshot(), self.trust, self.profile)

    def commit(self, msg):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "--allow-empty", "-m", msg)
        return git(self.root, "rev-parse", "HEAD")
