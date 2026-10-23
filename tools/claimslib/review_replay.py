"""The review replay checker: does a finding's test case fail at a commit?

The checker is an actor whose id names the bytes of this file: `checker sha256:<H>`, where H is
SHA-256 over canon({"checker": "warrant-review/replay@1", "files": {"tools/claimslib/review_replay.py":
sha256(bytes)}}), the form of the replay checker of claims (replay.py) and of the Sigma provider
identity (SPEC §7). A change of one byte here is another actor, with another key to pin. It imports
nothing of the claims tool: what it runs is given to `run` whole.

A finding (warrant-review/finding@1, tools/claimslib/reviews.py) may carry a test: a test file of
tests/, a case id and a unified diff confined to tests/ (patch_problem). `run` extracts the exact tree
of one commit (`git archive`, a canonical id: the caller resolves it first), applies the diff there,
runs that one test file against that tree (WARRANT_IMPL) and reads the case's outcome from its
results file (WARRANT_RESULTS, tests/world.py). The answer is one of RESULTS:

  FAIL            the case ran and failed: the finding reproduces at that commit;
  PASS            the case ran and passed: it does not;
  NO_RESULT       the file wrote no results or not this case (it crashed, or the case does not exist):
                  an ImportError is no reproduction (a red must fail on its assertion);
  DOES_NOT_APPLY  the diff does not apply to that tree.

The diff is code from the finding's author. It runs only where the PR's own tests run (CI, or a
sandbox of whoever holds this checker's seed), never inside an assessment or a `check`: a finding's
test entered the repository through the pull request's branch, as every test of the pull request
did, and is run with the same trust as they are.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from warrant import jcs as C

CHECKER = "warrant-review/replay@1"
PROBE = "warrant-review/replay@1"            # the schema of an observation's probe blob
PROBE_FIELDS = ("probe", "finding", "commit", "tree", "test")
SELF = "tools/claimslib/review_replay.py"    # the path the identity names
PREFIX = "checker sha256:"
RESULTS = ("FAIL", "PASS", "NO_RESULT", "DOES_NOT_APPLY")
TEST = re.compile(r"[a-z][a-z0-9_]*_test\Z")                   # \Z: `$` admits a trailing newline
CASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
PATCH_PATH = re.compile(r"[ab]/tests/\w[\w./-]*\Z", re.ASCII)            # ASCII: \w is [A-Za-z0-9_]
RENAME = ("rename from ", "rename to ", "copy from ", "copy to ")           # their path has no a/ or b/
# A symlink (120000) or submodule (160000) mode on a file mode line or an index line.
LINK_MODE = re.compile(r"(?:(?:new |deleted )?(?:file )?|old )mode 1[26]0000\b|(?:index \S+ 1[26]0000\Z)")
TIMEOUT = 900


def identity(data):
    """H for the bytes `data` of this file."""
    files = {SELF: hashlib.sha256(data).hexdigest()}
    return hashlib.sha256(C.canon({"checker": CHECKER, "files": files})).hexdigest()


def actor(data=None):
    """The actor id of these bytes (this file's own when none are given)."""
    return PREFIX + identity(Path(__file__).read_bytes() if data is None else data)


def _paths(line):
    """The paths a header line of a diff names (`a/…`, `b/…` or /dev/null), [] for any other line."""
    if line.startswith("diff --git "):
        return line[len("diff --git "):].split(" ")
    if line.startswith(RENAME):
        return ["a/" + line.split(" ", 2)[-1]]
    if line.startswith(("--- ", "+++ ")):
        return [line[4:].split("\t")[0].strip()]
    return []


def _line_problem(line):
    if line.startswith(("GIT binary patch", "Binary files ")):
        return "the patch is binary"
    if LINK_MODE.match(line):
        return "the patch makes a symlink or a submodule"
    for p in _paths(line):
        if p != "/dev/null" and (not PATCH_PATH.match(p) or ".." in p.split("/")):
            return f"the patch touches {p[:80]!r}, outside tests/"
    return None


def patch_problem(patch):
    """Why a finding's diff is not a text diff of files under tests/, or None. A path outside tests/,
    a `..`, a symlink or submodule mode and a binary hunk are each refused: the diff adds or changes
    test code, and nothing else."""
    if not isinstance(patch, str):
        return "the patch is not a string"
    return next((why for why in map(_line_problem, patch.splitlines()) if why), None)


def test_problem(test):
    """Why a finding's test member is not {file, case, patch}, or None."""
    if not (isinstance(test, dict) and set(test) == {"file", "case", "patch"}):
        return "test is null or {file, case, patch}"
    if not (isinstance(test["file"], str) and TEST.match(test["file"])):
        return "test.file is the name of a test file of tests/ without .py, ending in _test"
    if not (isinstance(test["case"], str) and CASE.match(test["case"])):
        return "test.case is a case id: letters, digits, `_.-`, at most 64"
    return patch_problem(test["patch"])


def extract(root, commit, into):
    """The tree of `commit` (a canonical id) of the repository at `root`, into the empty `into`."""
    data = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", commit], capture_output=True,
                          check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(into, filter="data")


def run(root, commit, test, timeout=TIMEOUT):
    """The outcome (one of RESULTS) of the finding test `test` at `commit` of the repository at
    `root`. `commit` must already be a canonical commit id: this function never resolves a name."""
    why = test_problem(test)
    if why:
        raise ValueError(why)
    work = Path(tempfile.mkdtemp(prefix="review-replay-"))
    try:
        tree = work / "tree"
        tree.mkdir()
        extract(root, commit, tree)
        if test["patch"].strip():
            # GIT_CEILING_DIRECTORIES: `git apply` patches this directory, never a repository around it.
            env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(work))
            r = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=tree, input=test["patch"].encode(),
                               capture_output=True, env=env, check=False)
            if r.returncode:
                return "DOES_NOT_APPLY"
        script = tree / "tests" / f"{test['file']}.py"
        if not script.is_file() or script.is_symlink():
            return "NO_RESULT"
        res = work / "results.json"
        env = dict(os.environ, WARRANT_IMPL=str(tree), WARRANT_RESULTS=str(res), PYTHONDONTWRITEBYTECODE="1")
        try:
            subprocess.run([sys.executable, str(script)], cwd=tree / "tests", env=env, capture_output=True,
                           timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return "NO_RESULT"
        try:
            got = json.loads(res.read_text())
        except (OSError, ValueError):
            return "NO_RESULT"
        v = got.get(test["case"]) if isinstance(got, dict) else None
        return v if v in ("FAIL", "PASS") else "NO_RESULT"
    finally:
        shutil.rmtree(work, ignore_errors=True)
