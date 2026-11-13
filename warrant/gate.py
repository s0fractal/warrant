"""Merge eligibility and due-for-review of a pull request (one predicate, read from Git data only), and the
GitHub side of the merge gate. An owner path (.warrant/merge.json): what decides merging.

`assess` reads a pull request ({number, state, draft, base, head, labels, branch, head_repo}, as GitHub
reports it) against a base commit, in the Git repository at `root`, and returns an Assessment holding two
verdicts computed from the same facts:

  merge-eligible  every one of these holds (`reasons` is empty):
    - the owner's holds are off: no `hold` label (merge.json hold_label) and no global hold (the repository
      variable WARRANT_MERGE_GATE=hold);
    - the pull request is open, not a draft, and into the base branch merge.json names;
    - the head's store is read from the head commit's tree as Git objects (nothing checked out, nothing of it
      run): .warrant/records.jsonl and .warrant/blobs/<hex64>, each a regular file, every blob named by its
      hash (STORE_ENTRY); assessed under the BASE's .warrant/v3.json trust and profile (never the head's), it
      has no rejected line and no problem (STORE_PROBLEMS), in canonical order (STORE_NOT_CANONICAL);
    - the head's store holds one pr-head@1 lineage of this pull request (root body {repository: the base's
      repository, pr: N}); it does not fork (HEAD_FORK); its leaf is a `head` version naming a commit X,
      canonical, with the tree it names (HEAD_COMMIT), an ancestor of the pull request's head
      (HEAD_NOT_ANCESTOR);
    - the head's tree differs from X's only by lines added to .warrant/records.jsonl (none removed) and
      blobs added under .warrant/blobs/ (TAIL_CHANGES); when the head merged base commits after X, it is compared
      with X's clean merge with the newest base commit it holds instead (caught_up: what the base brings is the
      base's, merged already; a merge that conflicts is compared with X, so its resolution needs a review); every blob added is cited by a record added
      (TAIL_BLOB_UNCITED); every record added is a verdict (an attest or a challenge by a pr/acceptor of the
      base's profile), a version of this pull request's lineage or a record about one of its versions (a
      finding, a merge observation), or a replay result (an attest by a replayer of the base's profile on a
      finding@1 challenge): else TAIL_RECORD_UNREVIEWED. The required check `test` runs the head's own
      checks, code byte-identical to X's since the tail touches nothing else;
    - the leaf's guard is MET by a pr/acceptor of the base's profile (never the version's own actor: the
      engine's rule) (NO_ACCEPT), and no counted challenge stands against it (OPEN_FINDING);
    - or, for a pull request with no lineage of its own, it carries verdicts only: from its merge base with
      the base, a tail as above whose records are each an attest or a challenge by a roadmap/acceptor of the
      base's profile, each new (VERDICT_NOT_NEW), each on a version the base's roadmap names as due for that
      actor (VERDICT_NOT_DUE), its head a branch of this repository (VERDICTS_FORK) under codex/verdicts/
      (VERDICTS_BRANCH), and every blob it adds cited (TAIL_BLOB_UNCITED);
    - it changes none of the base's merge.json owner_paths (OWNER_PATHS: the owner merges those), nor a path the
      interpreter could load one of the listed Python files' modules from instead, nor adds a module, a package, a
      link or a directory to a directory the interpreter searches for them, nor changes a .gitattributes (owner_paths);
    - every required check merge.json names is green at the head: the latest GitHub Actions check run of that
      name whose workflow run is the named workflow file concluded success, and none of that name comes from
      another workflow (CHECK_MISSING, CHECK_PENDING, CHECK_RED, CHECK_AMBIGUOUS).

  due-for-review  the same facts and shared refusals, and no verdict at the head yet: no acceptance and no
    counted challenge of the leaf. A pull request of verdicts only is never due.

The gate (`gate`) merges at most one eligible pull request per run, reading the pull request and the base
branch again just before (TOCTOU), giving GitHub the assessed head (it refuses the merge when the head
moved), and then dispatches the required workflows on the base branch (a GITHUB_TOKEN merge starts none)."""
import base64
import calendar
import importlib.machinery
import json
import os
import re
import subprocess
import time
import unicodedata
from pathlib import PurePosixPath

from . import engine as E
from . import jcs as C
from . import shapes as S
from .store import Snapshot, _line_id

GATE = "warrant-review/gate@1"
GATE_FIELDS = ("gate", "base", "required", "hold_label", "owner_paths")
WATCHED = "watched"     # optional: {paths, window_hours, solo_window_hours, families, veto_role}: what models merge, the owner watching
WATCHED_FIELDS = {"paths", "window_hours", "solo_window_hours", "families", "veto_role"}
# optional, beside `watched`: the same policy, plus `notify` (GitHub logins), for what decides merging and trust (the
# rules, the receiver, the gate itself), with windows no shorter than watched's; the gate comments once when one opens
CONSTITUTIONAL = "constitutional"
TIERS = (WATCHED, CONSTITUTIONAL)
SOLO = "solo"           # optional: {window_hours, veto_role}: one family merges a change to no listed path after the window
SOLO_FIELDS = {"window_hours", "veto_role"}
# optional: [{workflow, paths?}]: what the gate starts on the base after its own merge, as it starts the required
# workflows (a merge with GITHUB_TOKEN starts no push workflow, and GitHub drops most scheduled runs): each workflow
# when the merge changed a path under one of `paths` (every merge without them), never after a merge of verdicts only
AFTER = "after_merge"
ACCEPTOR = "pr/acceptor"   # the role whose verdicts the gate counts
# optional: {login, days, since}: the owner is present when a merge into the base on GitHub is his (author login, the
# committer GitHub's web-flow) since `since` and within `days`; agents never merge under his login (AGENTS.md rule 1).
# Present, a tier's change merges with no window before it, and the brake acts after it (brakes, open_revert).
PRESENCE = "presence"
PRESENCE_FIELDS = {"login", "days", "since"}
BRAKE = re.compile(r"warrant-gate brake until (\d{1,12}): #(\d{1,9}) head version (\w+)")       # a whole line (fullmatch)
REVERT = re.compile(r"warrant-gate revert of (\w+)")
REVERT_BRANCH = "gate/revert/"
# PEP 440's pre-releases (aN, bN, rcN, optionally .devN; or .devN alone), by the whole string: released with brakes
# open (owner, 2026-11-13: «в нас нема клієнтів — ми обслуговуємо своє майбутнє»); a stable release waits for them
_N = r"(?:0|[1-9][0-9]*)"
PRERELEASE = re.compile(rf"{_N}(?:\.{_N})*(?:(?:a|b|rc){_N}(?:\.post{_N})?(?:\.dev{_N})?|\.dev{_N})")
BRAKE_MARK = "<!-- warrant-gate brake -->"
AWAY = "<!-- warrant-gate presence ended {until} -->"
WEB_FLOW = "web-flow"                       # GitHub's committer of a merge made on GitHub
STAMP = "%Y-%m-%dT%H:%M:%SZ"                # GitHub's UTC time stamps
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
NOTICE = "<!-- warrant-gate constitutional window {x} -->"
MARKS = ("<!-- warrant-gate constitutional window ", "<!-- warrant-gate brake -->")    # the gate's own comments
ROLE = re.compile(r"[a-z][a-z0-9-]{0,39}/[a-z][a-z0-9-]{0,39}\Z")
REPOSITORY_DOC = "repository/3"
RECORDS, BLOBS = ".warrant/records.jsonl", ".warrant/blobs/"
REGULAR = "100644"
FILE_MODES = (REGULAR, "100755", "000000")      # a regular file, an executable one, none (deleted): never a link or a submodule
# Every ending a module's file can have: this interpreter's own list (FileFinder tries extension modules first, then
# source, then bytecode), with the endings other builds use, so that the answer does not move with the runner.
MODULE_SUFFIXES = tuple(sorted({*importlib.machinery.all_suffixes(), ".py", ".pyc", ".pyw", ".pyd", ".so"}))
ATTRIBUTES = ".gitattributes"                   # it decides the bytes a checkout writes for a path (encoding, eol, ident, filters)
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")
WORKFLOW = re.compile(r"\.github/workflows/[A-Za-z0-9._-]+\.ya?ml\Z")
CHECK = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ()._/-]{0,99}\Z")
OWNER_PATH = re.compile(r"(?!.*\.\.)[A-Za-z0-9._-][A-Za-z0-9._/-]{0,199}\Z")
REPO_NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
ACTIONS_APP = "github-actions"
VERDICT_BRANCH = "codex/verdicts/"
# the claims checker's acceptances, made on a runner after a merge (.github/workflows/claims-replay.yml): CI re-executes
# each at the commit it names (claims verify) before the gate merges them
CLAIMS_CHECKER, CLAIMS_BRANCH = "claims-checker", "claims/verdicts/"
HOLDS = ("GATE_HOLD", "PR_HOLD")          # refusals of a merge only; the rest of pr_reasons refuse both verdicts
REF = "refs/warrant-gate/pull/{n}"


class Refused(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- Git data

# The only options any caller passes; every other argument is an operand and may not look like an option.
GIT_OPTIONS = {"-r", "-z", "-l", "-q", "-C", "-n", "--quiet", "--verify", "--end-of-options", "--full-tree", "--no-renames",
               "--no-commit-id", "--name-only", "--is-ancestor", "--batch", "--no-tags", "--detach", "--force", "--check",
               "--parents", "--write-tree", "--no-messages", "--first-parent", "-", "--"}


def git(root, *args, stdin=None):
    """Git at `root`, refused when an argument that is no known option starts with "-" (a ref, a path or a remote
    named by a caller must never be read as an option)."""
    bad = [a for a in args if str(a).startswith("-") and a not in GIT_OPTIONS]
    if bad:
        raise Refused(f"git arguments that look like options: {bad[:3]}", "GATE_INPUT")
    r = subprocess.run(["git", *map(str, args)], cwd=os.path.realpath(root), input=stdin, capture_output=True, check=False)
    if r.returncode:
        raise subprocess.CalledProcessError(r.returncode, args, r.stdout, r.stderr)
    return r.stdout


def canonical(root, rev):
    """(commit id, tree id) of `rev`, refused unless it is the full lowercase id of a commit resolving to itself."""
    if not S.hex_of(rev, 40):
        raise Refused(f"{str(rev)[:50]!r} is not a full commit id", "HEAD_COMMIT")
    try:
        got = git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}").decode().strip()
        tree = git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{tree}}").decode().strip()
    except subprocess.CalledProcessError:
        raise Refused(f"{rev[:12]} is not a commit here", "HEAD_COMMIT") from None
    if got != rev:
        raise Refused(f"{rev[:12]} resolves to {got[:12]}", "HEAD_COMMIT")
    return got, tree


def entries(root, commit, path):
    """[(mode, type, object id, path)] of the tree of `commit` under `path` (recursive)."""
    out = []
    for e in git(root, "ls-tree", "-r", "-z", "--full-tree", commit, "--", path).decode().split("\0"):
        if e:
            meta, p = e.split("\t", 1)
            mode, typ, oid = meta.split()
            out.append((mode, typ, oid, p))
    return out


def objects(root, oids):
    """{object id: bytes} read by one `git cat-file --batch`."""
    oids = list(dict.fromkeys(oids))
    if not oids:
        return {}
    data = git(root, "cat-file", "--batch", stdin="".join(f"{o}\n" for o in oids).encode())
    out, i = {}, 0
    for o in oids:
        nl = data.index(b"\n", i)
        head = data[i:nl].decode().split()
        if len(head) != 3 or head[0] != o:
            raise Refused(f"{o[:12]} is not a readable object", "GIT_OBJECT")
        n = int(head[2])
        out[o] = data[nl + 1:nl + 1 + n]
        i = nl + 1 + n + 1
    return out


def files_at(root, commit, paths):
    """{path: bytes} of the regular files `paths` at `commit` (an absent one left out; any other mode refused)."""
    rows = {p: (m, t, o) for m, t, o, p in entries(root, commit, ".") if p in paths}
    for p, (m, t, _) in rows.items():
        if (m, t) != (REGULAR, "blob"):
            raise Refused(f"{p} at {commit[:12]} is mode {m}, not a regular file", "BASE_CONFIG")
    data = objects(root, [o for _, _, o in rows.values()])
    return {p: data[o] for p, (_, _, o) in rows.items()}


def lines_of(data):
    return [x + b"\n" for x in data.split(b"\n") if x]


def store_at(root, commit):
    """(Snapshot, problems) of .warrant/records.jsonl and .warrant/blobs/ in the tree of `commit`, from Git objects
    only. An entry that is not a regular file, or a blob not named by its hash, is a problem and left out."""
    problems, want = [], []
    for mode, typ, oid, p in entries(root, commit, ".warrant"):
        if p == RECORDS or (p.startswith(BLOBS) and S.hex64(p[len(BLOBS):])):
            if (mode, typ) != (REGULAR, "blob"):
                problems.append(("STORE_ENTRY", f"{p} is mode {mode} {typ}, not a regular file"))
            else:
                want.append((p, oid))
        elif p.startswith(BLOBS):
            problems.append(("STORE_ENTRY", f"{p} is not named by a hash"))
    data = objects(root, [o for _, o in want])
    lines, blobs = [], {}
    for p, oid in want:
        if p == RECORDS:
            lines = lines_of(data[oid])
        elif C.digest(data[oid]) == p[len(BLOBS):]:
            blobs[p[len(BLOBS):]] = data[oid]
        else:
            problems.append(("STORE_ENTRY", f"{p} is not named by its hash"))
    return Snapshot(lines, blobs), problems


def tail(root, x, head):
    """(changes beyond the records-only tail, record lines added, blob names added) from commit `x` to `head`:
    the tail is lines added to .warrant/records.jsonl (none removed; order free) and blobs added under
    .warrant/blobs/, each a regular file. Renames read as delete and add."""
    raw = git(root, "diff-tree", "-r", "-z", "--no-renames", "--no-commit-id", x, head).decode().split("\0")
    extra, blobs, lines_changed = [], [], False
    for meta, path in zip(raw[0::2], raw[1::2]):
        old_mode, new_mode, _, _, status = meta.lstrip(":").split()
        if path == RECORDS and status == "M" and old_mode == new_mode == REGULAR:
            lines_changed = True
        elif path.startswith(BLOBS) and S.hex64(path[len(BLOBS):]) and status == "A" and new_mode == REGULAR:
            blobs.append(path[len(BLOBS):])
        else:
            extra.append((path, f"{status} {old_mode}->{new_mode}"))
    added = []
    if lines_changed:
        f = files_at(root, x, [RECORDS])
        g = files_at(root, head, [RECORDS])
        before, after = set(lines_of(f.get(RECORDS, b""))), set(lines_of(g.get(RECORDS, b"")))
        if before - after:
            extra.append((RECORDS, f"{len(before - after)} line(s) removed"))
        added = sorted(after - before)
    return extra, added, sorted(blobs)


def caught_up(root, x, head, base):
    """What the head is held to after the reviewed commit `x`: the tree of x's clean three-way merge with B, the
    newest commit of `base` that `head` holds (git merge-tree, with the repository's merge attributes, as a local
    `git merge` of the base applies them): x's own tree when the head merged no base commit after x (B is then an
    ancestor of x); `x` when that merge conflicts (a resolution is new content: a review must see it)."""
    try:
        b = git(root, "merge-base", head, base).decode().split()[0]
        return git(root, "merge-tree", "--write-tree", "--no-messages", x, b).decode().split()[0]
    except (subprocess.CalledProcessError, IndexError):
        return x


def owner_paths(root, base, x, listed):
    """The paths changed from the merge base of `base` and `x` to `x` that are the owner's to merge: those `listed`
    names (an entry ending in / names a directory) and those the interpreter could load a listed Python file's module
    from in its place (loadable), names compared folded; or None when they have no merge base. Read from the diff of
    two trees: nothing of `x` is checked out, imported or run."""
    try:
        mb = git(root, "merge-base", base, x).decode().split()[0]
    except (subprocess.CalledProcessError, IndexError):
        return None
    modules, searched = import_roots(listed)
    # A directory was there only when the merge base and the base both hold it: one the base has dropped since is added again.
    held = {folded(d): subdirectories(root, mb, d) & subdirectories(root, base, d) for d in searched}
    modules = {folded(d): {folded(n) for n in names} for d, names in modules.items()}
    listed = [folded(e) for e in listed]
    raw = git(root, "diff-tree", "-r", "-z", "--no-renames", "--no-commit-id", mb, x).decode().split("\0")
    out = []
    for meta, path in zip(raw[0::2], raw[1::2]):
        _, mode, _, _, status = meta.lstrip(":").split()
        p = folded(path)
        if any(p == e or (e.endswith("/") and p.startswith(e)) for e in listed) or loadable(p, path, status, mode, modules, held):
            out.append(path)
    return sorted(out)


def folded(path):
    """`path` as a file system that folds case and normalizes names compares it (APFS, NTFS; Unicode's canonical
    caseless match): a checkout there writes two paths of one folded name to one file, so the bytes at a listed path
    can be another path's."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", path).casefold())


def import_roots(listed):
    """({directory: module names}, [searched directories]) that the listed Python files tell of: `D/N.py` is module N
    of directory D, and the directory the interpreter searches to reach it is D, or the one above D while D is a listed
    package (`D/__init__.py`). In this repository `warrant/` is reached through the root ("") and `tools/gate.py`, a
    script, puts `tools` on the path: whatever module either holds comes before the standard library's."""
    modules = {}
    for e in listed:
        if e.endswith(".py"):
            d, _, f = e.rpartition("/")
            modules.setdefault(d, set()).add(f[:-len(".py")])
    searched = set()
    for d in modules:
        while d and "__init__" in modules.get(d, ()):
            d = d.rpartition("/")[0]
        searched.add(d)
    return modules, sorted(searched)


def subdirectories(root, commit, d):
    """The names of the directories directly in directory `d` ("": the root) of `commit`; none when it has no such
    directory."""
    try:
        rows = git(root, "ls-tree", "-z", f"{commit}:{d}").decode().split("\0")
    except subprocess.CalledProcessError:
        return set()
    return {r.split("\t", 1)[1] for r in rows if r and r.split()[1] == "tree"}


def _in(path, d):
    """`path` relative to directory `d`, or None when it is not in it."""
    return path if not d else path[len(d) + 1:] if path.startswith(d + "/") else None


def _module_file(name, module):
    """Whether the file name `name` is one the interpreter could load `module` from: the module's name and an ending
    of the import system, or any ending that starts with a dot (every build's do, but a Windows debug build's)."""
    rest = name[len(module):]
    return name.startswith(module) and (rest.startswith(".") or rest in MODULE_SUFFIXES)


def loadable(path, written, status, mode, modules, held):
    """Whether a change to `path` (folded; `written` as the tree spells it; its status and new mode in the diff) can
    change the bytes the interpreter loads when the gate runs, though no listed path names it; `modules` is {directory:
    listed module names} and `held` {searched directory: the directories that were in it}. Three rules, each wider
    than what one interpreter does:

    1. beside a listed module `D/N.py`: `D/N` itself and everything in it (a package of that name is preferred to the
       file, and a link or a submodule there is whatever it leads to), a file `D/N` with another ending (an extension
       module is preferred to the source), and `D/__pycache__` (bytecode there is loaded in place of the source);
    2. in a searched directory, where any module shadows the standard library's and the installed ones (a name the
       library only tries, as `msvcrt`, too): a module file added, an `__init__` added to a directory, a directory
       added, and an entry that is a link or a submodule. A file changed there was there, under the name it has;
    3. `.gitattributes`, in any directory: the checkout writes other bytes than the blob's where it says so."""
    if path.rpartition("/")[2] == ATTRIBUTES:
        return True
    for d, names in modules.items():
        first, _, deeper = (_in(path, d) or "").partition("/")
        if first == "__pycache__" or first in names or (not deeper and any(_module_file(first, n) for n in names)):
            return True
    for d, were in held.items():
        first, _, deeper = (_in(path, d) or "").partition("/")
        if not first:
            continue
        if not deeper and (mode not in FILE_MODES or (status == "A" and first.endswith(MODULE_SUFFIXES))):
            return True
        # Whether the directory was there is asked of its name as written: where nothing is folded, another case of it is
        # another directory. Every other comparison here is of folded names, and so refuses more.
        if deeper and (written.split("/")[d.count("/") + 1 if d else 0] not in were
                       or (status == "A" and "/" not in deeper and _module_file(deeper, "__init__"))):
            return True
    return False


def is_ancestor(root, a, b):
    """Whether `a` is an ancestor of `b`; False also when Git cannot say (an object missing here): every caller that
    reads False as a refusal is on the safe side. One that would read it as "it does not hold" uses ancestry()."""
    return ancestry(root, a, b) is True


def ancestry(root, a, b):
    """True or False when Git establishes whether `a` is an ancestor of `b`; None when it cannot (an object not in
    this clone: merge-base exits 128, not 1) (Codex on #376: a tag's commit not fetched read as "not published")."""
    try:
        git(root, "merge-base", "--is-ancestor", a, b)
        return True
    except subprocess.CalledProcessError as e:
        return False if e.returncode == 1 else None


# ---------------------------------------------------------------- the base

def gate_config(doc):
    ok = _gate_shape(doc)
    why = policy_problem(doc) if ok else None
    if not ok or why:
        raise Refused(f".warrant/merge.json members are {list(GATE_FIELDS)} and optionally {[*TIERS, SOLO]}: gate {GATE!r}, a "
                      "branch name, a non-empty list of distinct {check, workflow}, a label and a list of paths"
                      + (f"; {why}" if why else ""), "BASE_CONFIG")
    return doc


def _gate_shape(doc):
    req = doc.get("required") if isinstance(doc, dict) else None
    return bool(isinstance(doc, dict) and set(GATE_FIELDS) <= set(doc) <= set(GATE_FIELDS) | {*TIERS, SOLO, PRESENCE, AFTER} and doc["gate"] == GATE
                and isinstance(doc["base"], str) and BRANCH.match(doc["base"]) and isinstance(req, list) and req
                and all(isinstance(c, dict) and set(c) == {"check", "workflow"} and isinstance(c["check"], str)
                        and CHECK.match(c["check"]) and isinstance(c["workflow"], str) and WORKFLOW.match(c["workflow"]) for c in req)
                and len({c["check"] for c in req}) == len(req)
                and isinstance(doc["hold_label"], str) and CHECK.match(doc["hold_label"])
                and isinstance(doc["owner_paths"], list) and all(isinstance(x, str) and OWNER_PATH.match(x) for x in doc["owner_paths"]))


def policy_problem(doc):
    """None when the optional tiers and the solo rule are a policy: `watched` (watched_problem); `constitutional`
    (constitutional_problem); `solo` (solo_problem). Else why not."""
    w = doc.get(WATCHED)
    why = watched_problem(w, doc["owner_paths"]) if WATCHED in doc else None
    if why is None and CONSTITUTIONAL in doc:
        why = constitutional_problem(doc[CONSTITUTIONAL], w, doc["owner_paths"])
    if why is None and SOLO in doc:
        why = solo_problem(doc[SOLO], w)
    if why is None and PRESENCE in doc:
        why = presence_problem(doc[PRESENCE], w)
    if why is None and AFTER in doc:
        why = after_problem(doc[AFTER])
    return why


def after_problem(after):
    """`after_merge` is a list of distinct {workflow: a workflow file, paths?: a non-empty list of paths}."""
    ok = (isinstance(after, list) and all(
        isinstance(x, dict) and set(x) in ({"workflow"}, {"workflow", "paths"}) and isinstance(x["workflow"], str)
        and WORKFLOW.match(x["workflow"]) and (isinstance(x.get("paths", ["x"]), list) and x.get("paths", ["x"])
                                               and all(isinstance(p, str) and OWNER_PATH.match(p) for p in x.get("paths", ["x"])))
        for x in after) and len({x["workflow"] for x in after}) == len(after))
    return None if ok else "after_merge is a list of distinct {workflow, paths?}"


def presence_problem(p, w):
    """`presence` only beside `watched`: {login: a GitHub login, days: 1..90, since: seconds since the epoch}."""
    if w is None:
        return "presence is read beside watched"
    ok = (isinstance(p, dict) and set(p) == PRESENCE_FIELDS and isinstance(p["login"], str) and LOGIN.match(p["login"])
          and type(p["days"]) is int and 1 <= p["days"] <= 90 and type(p["since"]) is int and p["since"] >= 0)
    return None if ok else "presence is {login: a GitHub login, days: 1..90, since: seconds since the epoch}"


def constitutional_problem(c, w, owner):
    """`constitutional` only beside `watched`: a watched policy with `notify` whose paths are neither owner nor watched
    paths and whose windows are no shorter than watched's (a rule that let the constitution change faster than the
    core would invert the tiers)."""
    if w is None:
        return "constitutional is a tier beside watched"
    if not (isinstance(c, dict) and isinstance(c.get("notify"), list)
            and all(isinstance(x, str) and LOGIN.match(x) for x in c["notify"])):
        return "constitutional.notify is a list of GitHub logins"
    why = watched_problem({k: v for k, v in c.items() if k != "notify"}, owner + w["paths"], CONSTITUTIONAL)
    if why is None and (c["window_hours"] < w["window_hours"] or c["solo_window_hours"] < w["solo_window_hours"]):
        why = "a constitutional window is no shorter than the watched one"
    return why


def solo_problem(solo, w):
    """`solo` is {window_hours: 0..watched's solo window (720 without one), veto_role: a role}."""
    top = w["solo_window_hours"] if w else 720
    ok = (isinstance(solo, dict) and set(solo) == SOLO_FIELDS and type(solo["window_hours"]) is int
          and 0 <= solo["window_hours"] <= top and isinstance(solo["veto_role"], str) and ROLE.match(solo["veto_role"]))
    return None if ok else f"solo is {{window_hours: 0..{top}, veto_role}}"


def watched_problem(w, owner, name=WATCHED):
    """None when `w` is a watched policy: {paths: a non-empty list of paths none of which is an owner path,
    window_hours: 1..720, solo_window_hours: window_hours..720, families: 2..5, veto_role: a role}; else why not."""
    if not (isinstance(w, dict) and set(w) == WATCHED_FIELDS):
        return f"{name} is {{{', '.join(sorted(WATCHED_FIELDS | ({'notify'} if name == CONSTITUTIONAL else set())))}}}"
    if not (isinstance(w["paths"], list) and w["paths"] and all(isinstance(x, str) and OWNER_PATH.match(x) for x in w["paths"])):
        return f"{name}.paths is a non-empty list of paths"
    if set(w["paths"]) & set(owner):
        return f"a {name} path is not an owner path" + (" or a watched path" if name == CONSTITUTIONAL else "")
    if not (type(w["window_hours"]) is int and 1 <= w["window_hours"] <= 720):
        return f"{name}.window_hours is an integer of 1..720"
    if not (type(w["solo_window_hours"]) is int and w["window_hours"] <= w["solo_window_hours"] <= 720):
        return f"{name}.solo_window_hours is an integer of window_hours..720"
    if not (type(w["families"]) is int and 2 <= w["families"] <= 5):
        return f"{name}.families is an integer of 2..5"
    if not (isinstance(w["veto_role"], str) and ROLE.match(w["veto_role"])):
        return f"{name}.veto_role is a role"
    return None


class Base:
    """What the base commit says: the gate's configuration (.warrant/merge.json) and the receiver's
    (.warrant/v3.json: the repository, the trust and the profile every head is assessed under)."""

    FILES = (".warrant/merge.json", ".warrant/v3.json")

    def __init__(self, root, commit):
        self.root, self.commit = root, commit
        try:
            files = files_at(root, commit, self.FILES)
        except UnicodeDecodeError:          # Git holds paths as bytes: a base tree with one that is no UTF-8 is refused, not a crash
            raise Refused(f"a path of the base {commit[:12]}'s tree is not UTF-8", "BASE_CONFIG") from None
        docs = {}
        for p in self.FILES:
            try:
                docs[p] = json.loads(files[p])
            except (KeyError, ValueError) as e:
                raise Refused(f"{p} at the base {commit[:12]}: {type(e).__name__} {e}", "BASE_CONFIG") from None
        self.gate = gate_config(docs[".warrant/merge.json"])
        v3 = docs[".warrant/v3.json"]
        if not (isinstance(v3, dict) and set(v3) == {"warrant", "repository", "trust", "profile"} and v3["warrant"] == REPOSITORY_DOC
                and isinstance(v3["repository"], str) and REPO_NAME.match(v3["repository"])
                and E.trust_problem(v3["trust"]) is None and E.profile_problem(v3["profile"]) is None):
            raise Refused(f".warrant/v3.json at the base is not a {REPOSITORY_DOC} document", "BASE_CONFIG")
        self.repository, self.trust, self.profile = v3["repository"], v3["trust"], v3["profile"]

    def holders(self, role):
        return set(self.profile["roles"].get(role, []))

    def claims_due(self, snap):
        """{version ids} the claims checker may accept: the leaf of each claim@1 lineage at the base whose leaf is
        `backed`. Whether it holds is CI's re-execution (claims verify), a required check of the pull request."""
        rep = assess_snapshot(self, snap)
        return {lin["leaf"] for lin in rep["lineages"].values() if lin["schema"] == "claim@1" and lin["leaf"]
                and rep["_recs"][lin["leaf"]]["body"].get("state") == "backed"}

    def roadmap_due(self, actor):
        """{version ids} the base's own records hold due for `actor`'s verdict: the leaf of a goal@1 or obligation@1
        lineage whose guard waits only for attests by a role the actor holds (no open requirement), not its own,
        neither attested nor challenged by it (the waker's `roadmap.py due`)."""
        snap, problems = store_at(self.root, self.commit)
        if problems:
            return set()
        return {x["version"] for x in due_for(assess_snapshot(self, snap), self.profile, actor, ("goal@1", "obligation@1"))}


def due_for(rep, profile, actor, schemas):
    """The versions of `schemas` waiting for `actor`'s verdict in report `rep` (warrant.graph.frontier's
    rule, stated here again so that the gate's decision rests on no file outside the owner paths)."""
    roles = {r for r, a in profile["roles"].items() if actor in a}
    acted = {r["body"]["target"] for r in _recs(rep).values() if r["kind"] in ("attest", "challenge") and r["actor"] == actor}
    out = []
    for root, lin in sorted(rep["lineages"].items()):
        if lin["schema"] not in schemas or lin["verdict"] != "OK":
            continue
        v = lin["leaf"]                 # only the latest version: an earlier pending one was replaced by it
        g = rep["versions"][v]
        if g["guard"] == "PENDING" and g["short"] and not g["open"] and roles & set(g["roles"]) \
                and v not in acted and _recs(rep)[v]["actor"] != actor:
            out.append({"version": v, "lineage": root, "schema": lin["schema"]})
    return out


def _recs(rep):
    return rep["_recs"]


def assess_snapshot(base, snap):
    """The base's report of a snapshot, with its admitted records attached (for the predicate only)."""
    view = E.View(snap, base.trust, base.profile)
    rep = view.report()
    rep["_recs"] = view.recs
    return rep


# ---------------------------------------------------------------- checks

def check_reasons(required, checks, head):
    """[(code, detail)] for each required check that is not green at `head`. `checks` is {"check_runs": [...],
    "workflow_runs": [...]} as the GitHub API returns them for that commit."""
    suites = {w.get("check_suite_id"): w.get("path") for w in checks.get("workflow_runs", [])
              if isinstance(w, dict) and w.get("head_sha") == head}
    out = []
    for c in required:
        runs = [r for r in checks.get("check_runs", []) if isinstance(r, dict) and r.get("name") == c["check"]
                and r.get("head_sha") == head and (r.get("app") or {}).get("slug") == ACTIONS_APP]
        ours = [r for r in runs if suites.get((r.get("check_suite") or {}).get("id")) == c["workflow"]]
        if len(ours) != len(runs):
            out.append(("CHECK_AMBIGUOUS", f"{c['check']}: {len(runs) - len(ours)} check run(s) of that name at {head[:12]} "
                        f"come from a workflow other than {c['workflow']}"))
        if not ours:
            out.append(("CHECK_MISSING", f"{c['check']} ({c['workflow']}) has no check run at {head[:12]}"))
            continue
        last = max(ours, key=lambda r: r.get("id", 0))
        if last.get("status") != "completed":
            out.append(("CHECK_PENDING", f"{c['check']} is {last.get('status')} at {head[:12]}"))
        elif last.get("conclusion") != "success":
            out.append(("CHECK_RED", f"{c['check']} concluded {last.get('conclusion')} at {head[:12]}"))
    return out


def checks_completed(required, checks, head):
    """The time (seconds since the epoch, GitHub's clock) the last of the required checks completed at `head`: of each
    check, its latest run there from its own workflow; None when one has not completed or its time cannot be read."""
    suites = {w.get("check_suite_id"): w.get("path") for w in checks.get("workflow_runs", [])
              if isinstance(w, dict) and w.get("head_sha") == head}
    out = 0
    for c in required:
        ours = [r for r in checks.get("check_runs", []) if isinstance(r, dict) and r.get("name") == c["check"]
                and r.get("head_sha") == head and (r.get("app") or {}).get("slug") == ACTIONS_APP
                and suites.get((r.get("check_suite") or {}).get("id")) == c["workflow"]]
        if not ours:
            return None
        last = max(ours, key=lambda r: r.get("id", 0))
        try:
            out = max(out, calendar.timegm(time.strptime(last.get("completed_at") or "", STAMP)))
        except ValueError:
            return None
    return out


# ---------------------------------------------------------------- the predicate

class Assessment:
    def __init__(self, pr, base):
        self.pr, self.base = pr, base
        self.reasons, self.shared, self.facts = [], [], {}
        self.verdict = False           # an acceptance or a counted challenge stands at the head
        self.accept = None             # (actor, version, commit X) when the head is accepted

    @property
    def eligible(self):
        return not self.reasons

    @property
    def due(self):
        return not self.shared and not self.verdict

    @property
    def not_due(self):
        return self.shared + ([("REVIEWED", "an acceptance or a finding stands at the head")] if self.verdict else [])

    def codes(self):
        return sorted({c for c, _ in self.reasons})


def pr_reasons(b, pr, hold=False):
    """[(code, detail)] of the pull request's own state: the holds, open, not a draft, into the base branch. The gate
    applies it again to the pull request it reads just before merging."""
    out = []
    if hold:
        out.append(("GATE_HOLD", "the repository variable WARRANT_MERGE_GATE is hold"))
    if b.gate["hold_label"] in pr["labels"]:
        out.append(("PR_HOLD", f"#{pr['number']} carries the label {b.gate['hold_label']!r}"))
    if pr["state"] != "open":
        out.append(("PR_NOT_OPEN", f"#{pr['number']} is {pr['state']}"))
    if pr["draft"]:
        out.append(("PR_DRAFT", f"#{pr['number']} is a draft"))
    if pr["base"] != b.gate["base"]:
        out.append(("PR_BASE", f"#{pr['number']} is into {pr['base']}, not {b.gate['base']}"))
    return out


def assess(root, base, pr, checks, hold=False, now=None, present=False):
    """The Assessment of pull request `pr` against the base commit `base` (a full id, or a Base already read); `now`
    (seconds since the epoch, default the clock) is when a watched change's window is read; `present`, whether the
    owner is (present: no window before a tier's merge, the brake after it)."""
    a = Assessment(pr, base if isinstance(base, str) else base.commit)
    a.facts["present"] = bool(present)
    try:
        b = base if isinstance(base, Base) else Base(root, base)
    except (Refused, subprocess.CalledProcessError) as e:
        a.shared.append(("BASE_CONFIG", str(e)))
        a.reasons += a.shared
        return a
    reasons = pr_reasons(b, pr, hold)
    a.reasons += [r for r in reasons if r[0] in HOLDS]
    a.shared += [r for r in reasons if r[0] not in HOLDS]
    try:
        _shared(a, root, b, pr, checks, now)
    except UnicodeDecodeError:              # Git holds paths as bytes: one that is no UTF-8 refuses its pull request, not the run
        a.shared.append(("HEAD_UNREADABLE", f"#{pr['number']}: a path of the head's trees is not UTF-8"))
    a.reasons += a.shared
    return a


def _shared(a, root, b, pr, checks, now=None):
    sh = a.shared
    try:
        head, _ = canonical(root, pr["head"])
    except Refused as e:
        sh.append(("HEAD_UNREADABLE", f"#{pr['number']}: {e}"))
        return
    sh += check_reasons(b.gate["required"], checks, head)
    snap, problems = store_at(root, head)
    sh += problems
    try:
        rep = assess_snapshot(b, snap)
    except Exception as e:                     # a store beyond limits, a malformed one: refused, never a crash
        sh.append(("STORE_PROBLEMS", f"the head's store cannot be assessed under the base's terms: {e}"))
        return
    if rep["rejected"] or rep["problems"]:
        sh.append(("STORE_PROBLEMS", f"under the base's trust and profile the head's store rejects {len(rep['rejected'])} "
                   f"line(s) and has {len(rep['problems'])} problem(s): "
                   + "; ".join([f"{i[:12]} {w[:80]}" for i, w in list(rep["rejected"].items())[:2]]
                               + [f"{c} {str(i)[:12]}" for c, i, _ in rep["problems"][:2]])))
    if not rep["canonical"]:
        sh.append(("STORE_NOT_CANONICAL", "the head's records.jsonl is not in canonical order (`warrant fmt`)"))
    _review(a, root, b, pr, head, rep, checks, now)


def _lineage(b, rep, n):
    return sorted(L for L, lin in rep["lineages"].items() if lin["schema"] == "pr-head@1"
                  and rep["_recs"][L]["body"].get("pr") == n and rep["_recs"][L]["body"].get("repository") == b.repository)


def _ids(lines):
    out = []
    for raw in lines:
        try:
            out.append(C.doc_id(C.loads(raw.rstrip(b"\n"))["record"]))
        except (ValueError, KeyError, TypeError):
            out.append(None)
    return out


def _uncited(rep, added, blobs):
    cited = set()
    for r in added:
        cited |= set((rep["_recs"].get(r) or {}).get("refs", []))
    return sorted(set(blobs) - cited)


def _review(a, root, b, pr, head, rep, checks=None, now=None):
    sh, n = a.shared, pr["number"]
    if str(pr.get("branch") or "").startswith(REVERT_BRANCH):
        why = _revert_only(a, root, b, pr, head)
        if why:
            sh.append(("REVERT_NOT_EXACT", why))
        return
    found = _lineage(b, rep, n)
    if not found:
        why = _verdicts_only(a, root, b, pr, head, rep)
        if why is None:
            sh.append(("NO_REVIEW", f"the head's store holds no pr-head@1 lineage of {b.repository}#{n} and adds more than verdicts"))
        sh += why or []
        return
    if len(found) > 1:
        sh.append(("HEAD_FORK", f"{len(found)} pr-head@1 lineages name {b.repository}#{n}"))
        return
    L = found[0]
    lin = rep["lineages"][L]
    if lin["verdict"] == "FORK":
        sh.append(("HEAD_FORK", f"#{n}'s heads fork"))
        return
    leaf = rep["_recs"].get(lin["leaf"]) or {"body": {}}        # total: a fork has no leaf
    if leaf["body"].get("state") != "head":
        sh.append(("NO_HEAD", f"#{n} has no head version"))
        return
    a.facts.update(duty=L, closure=lin["leaf"], head_n=len(lin["path"]) - 1, x=leaf["body"].get("commit"),
                   author=rep["_recs"][L]["actor"], changed=changed_paths(root, b.commit, head))
    x = _reviewed(sh, root, leaf, head, n)
    if x is None:
        return
    tiers = [(t, b.gate[t]) for t in TIERS if t in b.gate]
    # Every place the listed files imply (a shadowing package, a module added where the interpreter searches, ...)
    # is derived from owner and tier paths together, and stays the owner's; only a change to a file a tier lists
    # itself is the models' to merge, the owner watching.
    every = owner_paths(root, b.commit, x, b.gate["owner_paths"] + [p for _, w in tiers for p in w["paths"]])
    touched = {t: [p for p in every or [] if _listed(w["paths"], p)] for t, w in tiers}
    owned = None if every is None else [p for p in every if not any(p in ps for ps in touched.values())]
    if owned is None or owned:
        a.reasons.append(("OWNER_PATHS", "the owner merges a change to what decides merging: "
                          + (", ".join(owned[:8]) if owned else f"{x[:12]} has no merge base with the base")))
    _tail(sh, root, b, rep, lin, x, head, n)
    _verdict(a, b, rep, lin, x)
    ready = [_watched(a, b, rep, lin, w, touched[t], checks or {}, head, now, t) for t, w in tiers if touched[t]]
    if ready:
        a.facts["solo_ready"] = all(r for r, _ in ready)
        a.facts["solo_from"] = None if any(f is None for _, f in ready) else max(f for _, f in ready)
    elif owned == [] and SOLO in b.gate:
        a.facts["solo_ready"], a.facts["solo_from"] = _solo_window(a, b, rep, lin, b.gate[SOLO], checks or {}, head, now)
    # solo only when something a second family would give is missing: an accepted change is merged as accepted
    # (Codex F1 on #350: a merge accepted by codex was recorded as solo)
    if a.facts.get("solo_ready") and any(c in ("NO_ACCEPT", "WATCHED_FAMILIES") for c, _ in a.reasons):
        _solo(a, rep, lin, x)


def _solo(a, rep, lin, x):
    """The gate merges a change one model family stands behind once its solo window has passed with nothing else
    refusing (no veto, no hold, no finding, the checks green): the waiting for an acceptance or a second family ends."""
    a.reasons = [r for r in a.reasons if r[0] not in ("NO_ACCEPT", "WATCHED_FAMILIES", "WATCHED_WINDOW")]
    a.facts["solo"] = True
    if a.accept is None:
        a.accept = (rep["_recs"][lin["leaf"]]["actor"], lin["leaf"], x)


def _solo_window(a, b, rep, lin, solo, checks, head, now):
    """(solo_ready, solo_from) of a change to no listed path: its author holds pr/acceptor, no challenge by a holder of
    the veto role stands against the head version, nothing but the missing acceptance refuses it, and `window_hours`
    have passed since the required checks completed at the head."""
    author = rep["_recs"][lin["leaf"]]["actor"]
    vetoers = b.holders(solo["veto_role"])
    veto = [c for c, x in rep["challenges"].items() if x["target"] == lin["leaf"] and rep["_recs"].get(c, {}).get("actor") in vetoers]
    if veto:
        a.reasons.append(("OWNER_VETO", f"a {solo['veto_role']} challenged the head version: " + ", ".join(c[:12] for c in sorted(veto))))
    done = checks_completed(b.gate["required"], checks, head)
    now = time.time() if now is None else now
    others = [c for c, _ in a.reasons + a.shared if c != "NO_ACCEPT"]
    ready = bool(author in b.holders(ACCEPTOR) and not others and done is not None
                 and now - done >= solo["window_hours"] * 3600)
    return ready, None if done is None else int(done + solo["window_hours"] * 3600)


def changed_paths(root, base, head):
    """The paths the pull request changes against its merge base with the base, or None when Git cannot say."""
    try:
        mb = git(root, "merge-base", base, head).decode().split()[0]
        return sorted(p for p in git(root, "diff-tree", "-r", "-z", "--name-only", "--no-commit-id", mb, head).decode().split("\0") if p)
    except (subprocess.CalledProcessError, IndexError, UnicodeDecodeError):
        return None


def _listed(paths, p):
    return any(p == e or (e.endswith("/") and p.startswith(e)) for e in paths)


def _watched(a, b, rep, lin, w, touched, checks, head, now, tier=WATCHED):
    """A change to a path of a tier (`watched`, `constitutional`) is merged by the gate, the owner watching, only when
    the head version is accepted by `families` distinct pr/acceptors, its own actor counted when it holds pr/acceptor
    (WATCHED_FAMILIES); no challenge by a holder of `veto_role` is filed against it, counted or not (OWNER_VETO); and
    `window_hours` have passed since the required checks completed at the head, by GitHub's clock (WATCHED_WINDOW).
    With fewer families (one model family, the others out of budget) the gate merges it once the longer
    `solo_window_hours` has passed with one pr/acceptor family, no veto, no hold and nothing else refusing
    (`solo_ready`, then `_solo`). Returns (solo_ready, solo_from) of this tier; a constitutional change also leaves
    `notice`, what the gate's one comment says when its window opens."""
    a.facts[tier] = touched
    v = rep["versions"][lin["leaf"]]
    acceptors = b.holders(ACCEPTOR)
    families = (set(v["accepted_by"]) & acceptors) | ({rep["_recs"][lin["leaf"]]["actor"]} & acceptors)
    if len(families) < w["families"]:
        a.reasons.append(("WATCHED_FAMILIES", f"a change to {tier} paths ({', '.join(touched[:4])}) needs {w['families']} "
                          f"distinct pr/acceptors, its author counted: {', '.join(sorted(families)) or 'none'}"))
    vetoers = b.holders(w["veto_role"])
    veto = sorted(c for c, x in rep["challenges"].items()
                  if x["target"] == lin["leaf"] and rep["_recs"].get(c, {}).get("actor") in vetoers)
    if veto and not any(r[0] == "OWNER_VETO" for r in a.reasons):
        a.reasons.append(("OWNER_VETO", f"a {w['veto_role']} challenged the head version: " + ", ".join(c[:12] for c in veto)))
    done = checks_completed(b.gate["required"], checks, head)
    now = time.time() if now is None else now
    if a.facts.get("present"):
        # the owner present: no window before the merge; the brake holds after it for as long as the window would have
        blocking = [c for c, _ in a.reasons + a.shared if c not in ("NO_ACCEPT", "WATCHED_FAMILIES")]
        hours = w["window_hours"] if len(families) >= w["families"] else w["solo_window_hours"]
        a.facts["brake_hours"] = max(a.facts.get("brake_hours", 0), hours)
        return bool(families and not blocking and done is not None), None if done is None else int(done)
    if done is None or now - done < w["window_hours"] * 3600:
        left = "the required checks have not completed" if done is None else \
            f"{(w['window_hours'] * 3600 - (now - done)) / 3600:.1f} h of {w['window_hours']} h remain"
        a.reasons.append(("WATCHED_WINDOW", f"the owner's window on {tier} paths ({', '.join(touched[:4])}): {left}"))
    solo_left = None if done is None else w["solo_window_hours"] * 3600 - (now - done)
    blocking = [c for c, _ in a.reasons + a.shared if c not in ("NO_ACCEPT", "WATCHED_FAMILIES", "WATCHED_WINDOW")]
    solo_from = None if done is None else int(done + w["solo_window_hours"] * 3600)
    if tier == CONSTITUTIONAL and done is not None and not any(r[0] == "OWNER_PATHS" for r in a.reasons):
        a.facts["notice"] = {"x": lin_commit(rep, lin), "version": lin["leaf"], "paths": touched, "notify": w.get("notify", []),
                             "window_until": int(done + w["window_hours"] * 3600), "solo_until": solo_from, "families": w["families"]}
    return bool(families and not blocking and solo_left is not None and solo_left <= 0), solo_from


def lin_commit(rep, lin):
    return rep["_recs"][lin["leaf"]]["body"].get("commit")


def _reviewed(sh, root, leaf, head, n):
    """The head version's commit: canonical, with the tree the version names, an ancestor of the pull request's
    head; None after the reason it is not."""
    try:
        x, tree = canonical(root, leaf["body"].get("commit"))
    except Refused as e:
        sh.append(("HEAD_COMMIT", f"the head version: {e}"))
        return None
    if tree != leaf["body"].get("tree"):
        sh.append(("HEAD_COMMIT", f"{x[:12]} has tree {tree[:12]}; the head version names {str(leaf['body'].get('tree'))[:12]}"))
        return None
    if not is_ancestor(root, x, head):
        sh.append(("HEAD_NOT_ANCESTOR", f"{x[:12]} is not an ancestor of #{n}'s head {head[:12]}"))
        return None
    return x


def _tail(sh, root, b, rep, lin, x, head, n):
    """Refuse (in `sh`) what the pull request adds after the reviewed commit x beyond record lines and the blobs
    they cite, and a record that is neither a pr/acceptor's verdict, a version of its own lineage or about one,
    nor a replay result."""
    extra, lines, blobs = tail(root, caught_up(root, x, head, b.commit), head)
    if extra:
        sh.append(("TAIL_CHANGES", f"{len(extra)} change(s) after {x[:12]} beyond added record lines and blobs: "
                   + ", ".join(f"{p} ({w})" for p, w in extra[:8])))
    added = _ids(lines)
    loose = _uncited(rep, added, blobs)
    if loose:
        sh.append(("TAIL_BLOB_UNCITED", f"{len(loose)} blob(s) added after {x[:12]} are cited by no record added there: "
                   + ", ".join(o[:12] for o in loose[:8])))
    stray = _stray(b, rep, added, set(lin["versions"]))
    if stray:
        sh.append(("TAIL_RECORD_UNREVIEWED", f"{len(stray)} record(s) added after {x[:12]} are neither a verdict of a "
                   f"pr/acceptor, #{n}'s own, nor a replay result: " + ", ".join(s[:12] for s in stray[:8])))


def _stray(b, rep, added, versions):
    stray = []
    for r in added:
        rec = rep["_recs"].get(r)
        about = rec["body"].get("target") if rec and rec["kind"] in ("attest", "challenge") else None
        ok = rec is not None and (
            (rec["kind"] in ("attest", "challenge") and rec["actor"] in b.holders(ACCEPTOR))
            or r in versions or about in versions
            or (rec["kind"] == "attest" and rec["actor"] in b.holders("replayer")
                and (rep["_recs"].get(about) or {}).get("schema") == "finding@1"))
        if not ok:
            stray.append(r or "unreadable")
    return stray


def _verdict(a, b, rep, lin, x):
    """The verdict on the head version, whose commit is x: accepted by a pr/acceptor with its guard met, or findings
    stand against it."""
    v = rep["versions"][lin["leaf"]]
    by = sorted(set(v["accepted_by"]) & b.holders(ACCEPTOR))
    findings = v["challenged_by"]
    a.verdict = bool(by and v["guard"] == "MET") or bool(findings)
    if findings:
        a.reasons.append(("OPEN_FINDING", f"{len(findings)} finding(s) stand against the head version: "
                          + ", ".join(f[:12] for f in findings)))
    if v["guard"] != "MET" or not by:
        a.reasons.append(("NO_ACCEPT", f"the head version {lin['leaf'][:12]} is {v['guard']}: " + "; ".join(v["waiting"])[:200]))
    a.accept = (by[0], lin["leaf"], x) if by else None


def _verdicts_only(a, root, b, pr, head, rep):
    """None when the pull request does not carry verdicts only; else [(code, detail)] of what refuses it."""
    try:
        mb = git(root, "merge-base", b.commit, head).decode().split()[0]
    except (subprocess.CalledProcessError, IndexError):
        return None
    extra, lines, blobs = tail(root, mb, head)
    if extra or not lines:
        return None
    added = _ids(lines)
    acceptors = b.holders("roadmap/acceptor")
    recs = [rep["_recs"].get(r) for r in added]
    roadmap = all(x is not None and x["kind"] in ("attest", "challenge") and x["actor"] in acceptors for x in recs)
    claims = all(x is not None and x["kind"] == "attest" and x["actor"] == CLAIMS_CHECKER
                 and CLAIMS_CHECKER in b.holders("claim/verifier") and x["body"].get("verdict") == "accept" for x in recs)
    if not (roadmap or claims):
        return None
    branch = VERDICT_BRANCH if roadmap else CLAIMS_BRANCH
    out = []
    if pr.get("head_repo") != b.repository:
        out.append(("VERDICTS_FORK", f"#{pr['number']}'s head is a branch of {str(pr.get('head_repo'))[:60]!r}, not {b.repository}"))
    if not str(pr.get("branch") or "").startswith(branch):
        out.append(("VERDICTS_BRANCH", f"#{pr['number']}'s branch {str(pr.get('branch'))[:60]!r} is not under {branch}"))
    base_snap, _ = store_at(root, b.commit)
    old = [r for r in added if r in base_snap.lines]
    if old:
        out.append(("VERDICT_NOT_NEW", f"{len(old)} verdict(s) the base holds already: " + ", ".join(r[:12] for r in old[:8])))
    due = {actor: b.roadmap_due(actor) for actor in {x["actor"] for x in recs}} if roadmap else \
        {CLAIMS_CHECKER: b.claims_due(base_snap)}
    late = [r for r, x in zip(added, recs) if x["body"]["target"] not in due[x["actor"]]]
    if late:
        out.append(("VERDICT_NOT_DUE", f"{len(late)} verdict(s) on a version the base's roadmap does not hold due for its "
                    "actor: " + ", ".join(r[:12] for r in late[:8])))
    loose = _uncited(rep, added, blobs)
    if loose:
        out.append(("TAIL_BLOB_UNCITED", f"{len(loose)} blob(s) cited by no verdict: " + ", ".join(o[:12] for o in loose[:8])))
    a.facts.update(verdicts=sorted(added), x=mb)
    a.verdict = True
    a.accept = (recs[0]["actor"], min(added), mb)
    return out


# ---------------------------------------------------------------- the brake after a merge

def _commit(root, sha):
    """(parents, committer time, message) of commit `sha`, read from its object."""
    return _parse_commit(git(root, "cat-file", "commit", sha))


def _parse_commit(raw):
    head, _, msg = raw.decode(errors="replace").partition("\n\n")
    lines = head.splitlines()
    parents = [ln.split()[1] for ln in lines if ln.startswith("parent ")]
    when = next(int(ln.split()[-2]) for ln in lines if ln.startswith("committer "))
    return parents, when, msg


def first_parent(root, commit, n=None):
    """[(commit, parents, committer time, message)] along the first parents of `commit`, newest first: all of them
    (`n` None), read in one batch. A brake is found however many commits follow it (Codex dccff737 on #356: a scan
    bounded at 300 called a brake closed that was open)."""
    ids = git(root, "rev-list", "--first-parent", commit).decode().split()
    ids = ids if n is None else ids[:n]
    data = objects(root, ids)
    return [(x, *_parse_commit(data[x])) for x in ids]


def _epoch(stamp):
    """Seconds since the epoch of GitHub's UTC time stamp, None when it is not one."""
    try:
        return calendar.timegm(time.strptime(str(stamp), STAMP))
    except ValueError:
        return None


def _reacted(b, gh, since):
    """The newest time the `presence` login reacted to a comment of the gate's own (its notice or its brake), at or
    after `since`: one touch, from a phone, says «seen». Agents never react under that login (AGENTS.md rule 1)."""
    login, newest = b.gate[PRESENCE]["login"], None
    stamp = time.strftime(STAMP, time.gmtime(since))
    mine = [c for page in gh.api(f"issues/comments?since={stamp}&per_page=100", pages=True) for c in page
            if (c.get("user") or {}).get("login") == f"{ACTIONS_APP}[bot]" and any(m in (c.get("body") or "") for m in MARKS)]
    for c in mine[-20:]:
        for page in gh.api(f"issues/comments/{int(c['id'])}/reactions?per_page=100", pages=True):
            for r in page:
                t = _epoch(r.get("created_at"))
                if (r.get("user") or {}).get("login") == login and t is not None and t >= since:
                    newest = t if newest is None else max(newest, t)
    return newest


def presence_until(root, b, gh, now=None):
    """Until when the owner counts as present (seconds since the epoch), or None: `days` after his newest sign at or
    after `since` and within `days`: a merge into the base made on GitHub under the `presence` login (its author, with
    GitHub's web-flow as committer), or a reaction of his to a comment of the gate. Agents never merge or react under
    that login (AGENTS.md rule 1), so his own acts are the signal; nothing else he does is needed. A failure to read
    either is no sign: the windows before a merge apply."""
    p = b.gate.get(PRESENCE)
    if not p:
        return None
    now = time.time() if now is None else now
    # signs older than `days` are read too (to twice that), so an expired deadline is still known and its end announced
    # (Codex cd8d1a0b on #356: the expired sign was dropped and announce_away never ran)
    since, asked, signs = max(p["since"], now - 2 * p["days"] * 86400), 0, []
    for x, parents, when, _ in first_parent(root, b.commit):
        if when < since or asked >= 30:
            break
        if len(parents) != 2:
            continue
        asked += 1
        try:
            c = gh.commit(x)
        except Refused:
            break
        if (c.get("author") or {}).get("login") == p["login"] and (c.get("committer") or {}).get("login") == WEB_FLOW:
            signs.append(when)
            break
    try:
        t = _reacted(b, gh, since)
    except (Refused, AttributeError, KeyError, TypeError, ValueError):
        t = None
    signs += [t] if t is not None else []
    return int(max(signs) + p["days"] * 86400) if signs else None


def present(root, b, gh, now=None):
    """Whether the owner is present at `now` (presence_until)."""
    now = time.time() if now is None else now
    until = presence_until(root, b, gh, now)
    return until is not None and until > now


def announce_away(b, gh, until, now=None):
    """Once, when the owner's presence has ended, an issue naming him: the windows come before a merge again, and what
    makes him present. The mode never changes silently. The outcome as text, or None."""
    now = time.time() if now is None else now
    if PRESENCE not in b.gate or until is None or until > now:
        return None
    mark = AWAY.format(until=until)
    try:
        if any(mark in (i.get("body") or "") for page in gh.api("issues?state=all&per_page=100", pages=True) for i in page
               if (i.get("user") or {}).get("login") == f"{ACTIONS_APP}[bot]"):
            return None
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(until))
        login = b.gate[PRESENCE]["login"]
        gh.api("issues", "POST", {"title": f"warrant-gate: {login} counts as away since {when}",
                                  "body": f"{mark}\n@{login} no merge of yours on GitHub and no reaction of yours to a "
                                          f"comment of the gate for {b.gate[PRESENCE]['days']} days: since {when} the "
                                          "windows come before a merge again (watched 24/72 h, constitutional 72/168 h). "
                                          "A merge of yours, or a reaction of yours to any comment of the gate, makes "
                                          f"you present again for {b.gate[PRESENCE]['days']} days.\n"})
    except Refused as e:
        return f"away notice FAILED: {e}"
    return "away noticed"


def brake_lines(msg):
    """The brake lines of a commit message: whole lines, the version a full record id (shapes)."""
    return [m for ln in msg.splitlines() if (m := BRAKE.fullmatch(ln)) and S.hex64(m[3])]


def revert_lines(msg):
    """The revert lines of a commit message: whole lines naming a full commit id."""
    return [m for ln in msg.splitlines() if (m := REVERT.fullmatch(ln)) and S.hex_of(m[1], 40)]


def brakes(root, commit, now=None, open_only=True):
    """[{merge, until, pr, version}] of the merges along the first parents of `commit` whose message carries the gate's
    brake line; with `open_only`, those whose brake has not ended at `now`."""
    now = time.time() if now is None else now
    return [{"merge": x, "until": int(m[1]), "pr": int(m[2]), "version": m[3]}
            for x, _, _, msg in first_parent(root, commit) for m in brake_lines(msg) if not open_only or int(m[1]) > now]


def reverted(root, commit, merge):
    return any(m[1] == merge for _, _, _, msg in first_parent(root, commit) for m in revert_lines(msg))


def vetoed(b, rep, gh, k):
    """Why the merge of brake `k` is vetoed, or None: the hold label on its pull request, or a challenge on its head
    version by a holder of a veto role (counted or not)."""
    if b.gate["hold_label"] in gh.pull(k["pr"])["labels"]:
        return f"the label {b.gate['hold_label']!r} on #{k['pr']}"
    roles = {w["veto_role"] for t, w in b.gate.items() if t in (*TIERS, SOLO)}
    vetoers = set().union(*(b.holders(r) for r in roles)) if roles else set()
    veto = sorted(c for c, x in rep["challenges"].items() if x["target"] == k["version"] and rep["_recs"].get(c, {}).get("actor") in vetoers)
    return f"a challenge by {rep['_recs'][veto[0]]['actor']} on #{k['pr']}'s head version: {veto[0][:12]}" if veto else None


def _kept(path):
    """A revert never takes records back: the store is append-only, and its history stays whole."""
    return path == RECORDS or path.startswith(BLOBS)


def revert_plan(root, base, merge):
    """([tree entry], None) that revert `merge` (its change against its first parent) on top of `base`, the store's
    records kept; (None, why) when it is no merge or a path it changed has changed again since (no exact revert)."""
    parents, _, _ = _commit(root, merge)
    if len(parents) != 2:
        return None, f"{merge[:12]} is not a merge"
    rows = {c: {p: (m, t, o) for m, t, o, p in entries(root, c, ".")} for c in (parents[0], merge, base)}
    before, after, now = rows[parents[0]], rows[merge], rows[base]
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p) and not _kept(p))
    bad = [p for p in changed if now.get(p) != after.get(p) or any(r.get(p, ("", "blob"))[1] != "blob" for r in (before, after))]
    if bad:
        return None, f"changed again since, or not a file: {', '.join(bad[:4])}"
    return [{"path": p, "mode": before[p][0], "type": "blob", "sha": before[p][2]} if p in before
            else {"path": p, "mode": after[p][0], "type": "blob", "sha": None} for p in changed], None


def published_with(root, gh, merge):
    """(held, unknown): the tags of this repository (v...) whose commit holds `merge` (the published versions a revert
    of it does not reach), and those whose relation to it this clone cannot establish (their commit is not here). An
    agent records an obligation for each held one; a yank is the owner's act, if he wants one."""
    held, unknown = [], []
    for page in gh.api("tags?per_page=100", pages=True):
        for t in page:
            sha = (t.get("commit") or {}).get("sha")
            if not str(t.get("name", "")).startswith("v"):
                continue
            rel = ancestry(root, merge, sha) if S.hex_of(sha, 40) else None
            if rel is True:
                held.append(t["name"])
            elif rel is None:
                unknown.append(t["name"])
    return sorted(held), sorted(unknown)


def open_revert(root, b, gh, k, why):
    """Open the gate's revert of the merge of brake `k` as a pull request from gate/revert/<pr>-<merge>, made through
    GitHub's API with the workflow's token, and start the required workflows on it; the outcome as text."""
    plan, err = revert_plan(root, b.commit, k["merge"])
    if err:
        return f"revert of #{k['pr']} NOT made: {err}"
    try:
        tree = gh.api("git/trees", "POST", {"base_tree": git(root, "rev-parse", f"{b.commit}^{{tree}}").decode().strip(), "tree": plan})["sha"]
        msg = f"Revert #{k['pr']} (vetoed in its brake window)\n\nwarrant-gate revert of {k['merge']}\nvetoed: {why}\n"
        commit = gh.api("git/commits", "POST", {"message": msg, "tree": tree, "parents": [b.commit]})["sha"]
        branch = f"{REVERT_BRANCH}{k['pr']}-{k['merge'][:12]}"
        gh.api("git/refs", "POST", {"ref": f"refs/heads/{branch}", "sha": commit})
        try:
            held, unknown = published_with(root, gh, k["merge"])
        except (Refused, AttributeError, TypeError, KeyError, ValueError):     # an answer that is no list of tags: not read
            held, unknown = None, None
        reached = ""
        if held:
            reached += ("Published versions hold the reverted change: " + ", ".join(held) + ". An agent records an "
                        "obligation for each (the next pre-release closes it); a yank is the owner's act, if he wants one. ")
        if unknown:
            reached += "Whether these published versions hold it could not be established here: " + ", ".join(unknown) + ". "
        if held is None:
            reached = "Whether a published version holds it could not be read."
        elif not held and not unknown:
            reached = "No published version holds it (every tag was checked)."
        gh.api("pulls", "POST", {"title": f"Revert #{k['pr']} (vetoed in its brake window)", "head": branch, "base": b.gate["base"],
                                 "body": f"The gate reverts {k['merge']}: {why}. The store's records are kept. {reached}"})
        for w in sorted({c["workflow"] for c in b.gate["required"]}):
            gh.dispatch(w, branch)
    except Refused as e:
        return f"revert of #{k['pr']} FAILED: {e}"
    return f"revert of #{k['pr']} opened from {branch}"


def union_plan(root, base, head):
    """(records bytes, [tree entry]) that merge the base's store into a head that adds only records and blobs: the
    union of both records.jsonl files in the store's canonical order (`warrant fmt`), and the head's blobs the base
    does not hold. Git's merge=union does this locally; GitHub does not apply it (R-UNION-ON-FORGE)."""
    files = {c: files_at(root, c, [RECORDS]).get(RECORDS, b"") for c in (base, head)}
    union = b"".join(sorted(set(lines_of(files[base]) + lines_of(files[head])), key=_line_id))
    have = {p for _, _, _, p in entries(root, base, BLOBS.rstrip("/"))}
    return union, [{"path": p, "mode": m, "type": "blob", "sha": o} for m, t, o, p in entries(root, head, BLOBS.rstrip("/"))
                   if p not in have and t == "blob"]


def refresh_verdicts(root, b, gh, found):
    """[(pr, outcome)]: each open pull request of verdicts only, from a branch of this repository under its prefix,
    that GitHub cannot merge (its records conflict with the base's: two branches append to one file) gets the base
    merged into its branch through GitHub's API, the stores' union as its records, and CI started on it. A pull request
    of the claims checker's acceptances runs CI for long enough that the base moves on meanwhile; without this it
    would conflict again and never merge (#364, 2026-11-13)."""
    out = []
    for a in found:
        if not a.facts.get("verdicts") or {c for c, _ in a.shared} & {"VERDICTS_FORK", "VERDICTS_BRANCH", "HEAD_MOVED"}:
            continue
        n, head, branch = a.pr["number"], a.pr["head"], a.pr.get("branch")
        try:
            if gh.api(f"pulls/{_number(n)}").get("mergeable_state") != "dirty":
                continue
            records, blobs = union_plan(root, b.commit, head)
            blob = gh.api("git/blobs", "POST", {"content": base64.b64encode(records).decode(), "encoding": "base64"})["sha"]
            base_tree = git(root, "rev-parse", f"{b.commit}^{{tree}}").decode().strip()
            tree = gh.api("git/trees", "POST", {"base_tree": base_tree, "tree": [
                {"path": RECORDS, "mode": REGULAR, "type": "blob", "sha": blob}, *blobs]})["sha"]
            commit = gh.api("git/commits", "POST", {"message": f"Merge {b.gate['base']} into {branch}: records only (warrant-gate)\n\n"
                                                    f"The union of the stores, in canonical order; base {b.commit}.\n",
                                                    "tree": tree, "parents": [head, b.commit]})["sha"]
            gh.api(f"git/refs/heads/{_branch(branch)}", "PATCH", {"sha": commit, "force": False})
            for w in sorted({c["workflow"] for c in b.gate["required"]}):
                gh.dispatch(w, branch)
            out.append((n, f"base merged into {branch} as {commit[:12]}"))
        except Refused as e:
            out.append((n, f"refresh FAILED: {e}"))
    return out


def enforce_brakes(root, b, gh, found, now=None):
    """[(pr, outcome)] of each merge whose brake is open, vetoed, not reverted and with no revert pending: an open pull
    request the gate assessed as the exact revert of that merge (_revert_only). A branch's name alone is no revert
    (Codex 8caa1ce8: a fork's pull request on gate/revert/7-blocker held back the revert of a vetoed #7)."""
    snap, _ = store_at(root, b.commit)
    rep = assess_snapshot(b, snap)
    pending = {a.facts.get("revert") for a in found if a.facts.get("revert")}
    out = []
    for k in brakes(root, b.commit, now):
        if reverted(root, b.commit, k["merge"]) or k["merge"] in pending:
            continue
        why = vetoed(b, rep, gh, k)
        if why:
            out.append((k["pr"], open_revert(root, b, gh, k, why)))
    return out


def _revert_only(a, root, b, pr, head):
    """None when the pull request is the gate's exact revert of a braked merge of the base (opened by the workflow's
    bot, one commit naming the merge, its parent on the base, changing exactly what the merge changed back to what it
    was, records kept, nothing changed there since); else why not."""
    if pr.get("author") != f"{ACTIONS_APP}[bot]" or pr.get("head_repo") != b.repository:
        return f"#{pr['number']} under {REVERT_BRANCH} was not opened by the gate from this repository"
    parents, _, msg = _commit(root, head)
    m = next(iter(revert_lines(msg)), None)
    if len(parents) != 1 or not m:
        return "the head is not one commit naming the merge it reverts"
    merge, parent = m[1], parents[0]
    if not any(k["merge"] == merge for k in brakes(root, b.commit, open_only=False)) or not is_ancestor(root, parent, b.commit):
        return f"{merge[:12]} is no braked merge of the base, or the revert's parent is not on the base"
    plan, err = revert_plan(root, b.commit, merge)
    if err:
        return err
    # each path's mode and type as well as its object (Codex 7a84e332 on #356: the same blobs with an owner path made
    # a link passed as the exact revert)
    want = {e["path"]: (e["mode"], e["type"], e["sha"]) if e["sha"] else None for e in plan}
    got = {p: (m, t, o) for m, t, o, p in entries(root, head, ".")}
    was = {p: (m, t, o) for m, t, o, p in entries(root, parent, ".")}
    moved = {p for p in set(got) | set(was) if got.get(p) != was.get(p)}
    if any(got.get(p) != o for p, o in want.items()) or not moved <= set(want):
        return "the head is not the exact revert of the merge it names"
    a.facts["revert"], a.verdict, a.accept = merge, True, (f"{ACTIONS_APP}[bot]", merge, parent)
    return None


# ---------------------------------------------------------------- formats

def line(a):
    n = a.pr["number"]
    if a.eligible and a.facts.get("verdicts"):
        return f"#{n} {a.pr['head'][:12]}: ELIGIBLE (verdicts only, by {a.accept[0]}, from {a.accept[2][:12]})"
    if a.eligible and a.facts.get("solo"):
        return f"#{n} {a.pr['head'][:12]}: ELIGIBLE (solo: {a.accept[0]}'s head at {a.accept[2][:12]}, its window passed)"
    if a.eligible:
        return f"#{n} {a.pr['head'][:12]}: ELIGIBLE (accepted by {a.accept[0]} at {a.accept[2][:12]})"
    return f"#{n} {a.pr['head'][:12]}: " + ("DUE FOR REVIEW; " if a.due else "") + "refused " + ", ".join(a.codes())


def as_json(a):
    return {"pr": a.pr["number"], "head": a.pr["head"], "branch": a.pr.get("branch"), "title": a.pr.get("title"),
            "head_repo": a.pr.get("head_repo"), "base": a.base, "eligible": a.eligible, "due": a.due,
            "reasons": [list(r) for r in a.reasons], "not_due": [list(r) for r in a.not_due],
            "accept": list(a.accept) if a.accept else None, "facts": a.facts}


def summary_markdown(found, merged=None, base=None):
    out = ["## merge-on-acceptance", "", f"Base `{base or (found[0].base if found else '?')}`.", ""]
    if not found:
        out.append("No open pull request into the base branch.")
    for a in found:
        n = a.pr["number"]
        if a.eligible:
            out.append(f"- **#{n}** head `{a.pr['head'][:12]}`: {line(a).split(': ', 1)[1]}")
        else:
            out.append(f"- **#{n}** head `{a.pr['head'][:12]}`: refused")
            out += [f"  - `{c}` {d}" for c, d in a.reasons]
    if merged:
        out += ["", f"Merged: {merged}"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- GitHub

class GitHub:
    """`gh api` for one repository; `run` is subprocess.run (a test passes its own)."""

    def __init__(self, repo, gh="gh", run=subprocess.run):
        if not (isinstance(repo, str) and REPO_NAME.match(repo)):
            raise Refused(f"{str(repo)[:60]!r} is not owner/name", "GATE_INPUT")
        self.repo, self.gh, self._run = repo, gh, run

    def api(self, path, method="GET", body=None, pages=False):
        cmd = [self.gh, "api", "--method", method, f"repos/{self.repo}/{path}"]
        if pages:
            cmd[2:2] = ["--paginate", "--slurp"]
        if body is not None:
            cmd += ["--input", "-"]
        r = self._run(cmd, input=json.dumps(body).encode() if body is not None else None, capture_output=True, check=False)
        if r.returncode:
            raise Refused(f"gh api {method} {path}: {(r.stderr or b'').decode(errors='replace').strip()[:300]}", "GITHUB")
        return json.loads(r.stdout or b"null")

    def pulls(self, base):
        return [facts(p) for page in self.api(f"pulls?state=open&base={_branch(base)}&per_page=100", pages=True) for p in page]

    def pull(self, n):
        return facts(self.api(f"pulls/{_number(n)}"))

    def checks(self, sha):
        sha = _sha(sha)
        runs = self.api(f"commits/{sha}/check-runs?per_page=100", pages=True)
        wf = self.api(f"actions/runs?head_sha={sha}&per_page=100", pages=True)
        return {"check_runs": [r for page in runs for r in page.get("check_runs", [])],
                "workflow_runs": [w for page in wf for w in page.get("workflow_runs", [])]}

    def tip(self, branch):
        return self.api(f"branches/{_branch(branch)}")["commit"]["sha"]

    def merge(self, n, sha, title, message):
        return self.api(f"pulls/{_number(n)}/merge", "PUT", {"sha": _sha(sha), "merge_method": "merge",
                                                              "commit_title": title, "commit_message": message})

    def commit(self, sha):
        return self.api(f"commits/{_sha(sha)}")

    def comments(self, n):
        return [c for page in self.api(f"issues/{_number(n)}/comments?per_page=100", pages=True) for c in page]

    def comment(self, n, body):
        return self.api(f"issues/{_number(n)}/comments", "POST", {"body": body})

    def parents(self, sha):
        return [p["sha"] for p in self.api(f"commits/{_sha(sha)}")["parents"]]

    def dispatch(self, workflow, branch):
        name = PurePosixPath(workflow).name
        if not WORKFLOW.match(f".github/workflows/{name}"):
            raise Refused(f"{name!r} is not a workflow file name", "GATE_INPUT")
        return self.api(f"actions/workflows/{name}/dispatches", "POST", {"ref": _branch(branch)})


def _number(n):
    if type(n) is not int or n < 1:
        raise Refused(f"{n!r} is not a pull request number", "GATE_INPUT")
    return n


def _sha(s):
    if not S.hex_of(s, 40):
        raise Refused(f"{str(s)[:50]!r} is not a full commit id", "GATE_INPUT")
    return s


def _branch(b):
    if not (isinstance(b, str) and BRANCH.match(b) and ".." not in b):
        raise Refused(f"{str(b)[:50]!r} is not a branch name", "GATE_INPUT")
    return b


def facts(p):
    return {"number": p["number"], "state": p["state"], "draft": bool(p.get("draft")), "base": p["base"]["ref"],
            "head": p["head"]["sha"], "labels": sorted(x["name"] for x in p.get("labels", [])),
            "branch": p["head"].get("ref"), "title": p.get("title"), "head_repo": (p["head"].get("repo") or {}).get("full_name"),
            "author": (p.get("user") or {}).get("login")}


def fetch(root, n, remote="origin"):
    """Fetch pull request `n`'s head into refs/warrant-gate/pull/<n> (Git data only) and return its id."""
    ref = REF.format(n=_number(n))
    git(root, "fetch", "--no-tags", "--quiet", remote, f"+refs/pull/{n}/head:{ref}")
    return git(root, "rev-parse", "--verify", ref).decode().strip()


def survey(root, b, gh, prs=None, hold=False, remote="origin", present_=False):
    """[Assessment] of the open pull requests into the base branch, each fetched as Git data and assessed against
    the base `b`. Refused BASE_MOVED when the base branch on GitHub is no longer at that commit."""
    tip = gh.tip(b.gate["base"])
    if tip != b.commit:
        raise Refused(f"{b.gate['base']} is at {tip[:12]} on GitHub, the base read here is {b.commit[:12]}", "BASE_MOVED")
    out = []
    for pr in sorted(gh.pulls(b.gate["base"]), key=lambda p: p["number"]):
        if prs and pr["number"] not in prs:
            continue
        try:
            got = fetch(root, pr["number"], remote)
        except subprocess.CalledProcessError as e:
            got = f"unfetchable: {e.stderr.decode(errors='replace').strip()[:100]}"
        if got != pr["head"]:
            a = Assessment(pr, b.commit)
            a.shared.append(("HEAD_MOVED", f"#{pr['number']} reads {pr['head'][:12]} on GitHub and {got[:40]} fetched"))
            a.reasons += a.shared
        else:
            a = assess(root, b, pr, gh.checks(pr["head"]), hold=hold, present=present_)
        out.append(a)
    return out


def merge_one(b, a, gh):
    """Merge eligible Assessment `a` at the head it assessed, after reading the pull request and the base branch
    again (the pull request rules at the same head, the base at the same commit); then dispatch the required
    workflows on the base branch."""
    n, head, base = a.pr["number"], a.pr["head"], a.base
    now = gh.pull(n)
    changed = pr_reasons(b, now)
    if now["head"] != head:
        changed.append(("HEAD_MOVED", f"#{n} is at {now['head'][:12]}, not the head assessed"))
    if changed:
        return {"pr": n, "merged": False, "why": "; ".join(f"{c}: {d}" for c, d in changed)}
    tip = gh.tip(b.gate["base"])
    if tip != base:
        return {"pr": n, "merged": False, "why": f"BASE_MOVED: {b.gate['base']} is at {tip[:12]}"}
    actor, rid, x = a.accept
    hours = a.facts.get("brake_hours")
    until = int(time.time() + hours * 3600) if hours and not a.facts.get("revert") else None
    if a.facts.get("revert"):
        title = f"Merge pull request #{n} (the gate's revert of {rid[:12]}, vetoed in its brake window)"
        message = f"merge-on-acceptance: revert of {rid}: the change it reverts was vetoed in its brake window; head {head}; base {base}."
    elif a.facts.get("solo") and a.facts.get("present") and hours:
        title = f"Merge pull request #{n} (solo: {actor}, the owner present: the brake after the merge)"
        message = (f"merge-on-acceptance: solo: head version {rid} by {actor} at {x}, one model family, merged with the owner "
                   f"present and no window before it; head {head}; base {base}.")
    elif a.facts.get("solo"):
        title = f"Merge pull request #{n} (solo: {actor}, the window passed)"
        message = (f"merge-on-acceptance: solo: head version {rid} by {actor} at {x}, one model family, its window passed "
                   f"since {a.facts.get('solo_from')} with no veto; head {head}; base {base}.")
    elif a.facts.get("verdicts"):
        title = f"Merge pull request #{n} (verdicts by {actor})"
        message = f"merge-on-acceptance: verdicts only, {', '.join(a.facts['verdicts'])}, from {x}; head {head}; base {base}."
    else:
        title = f"Merge pull request #{n} (accepted by {actor})"
        message = f"merge-on-acceptance: head version {rid} accepted by {actor} at {x}; head {head}; base {base}."
    message += " Required checks green at the head."
    if until:
        message += f"\n\nwarrant-gate brake until {until}: #{n} head version {rid}"
    try:
        res = gh.merge(n, head, title, message)
    except Refused as e:
        return {"pr": n, "merged": False, "why": f"GitHub refused the merge: {e}"}
    if res.get("merged") is not True or not S.hex_of(res.get("sha"), 40):
        return {"pr": n, "merged": False, "why": f"GitHub answered {json.dumps(res)[:200]}"}
    parents = gh.parents(res["sha"])
    out = {"pr": n, "merged": True, "merge": res["sha"], "parents": parents, "head": head, "base": base,
           "as_assessed": parents == [base, head], "dispatched": [], "dispatch_failed": []}
    for w in sorted({c["workflow"] for c in b.gate["required"]}) + after_merge(b, a):
        try:
            gh.dispatch(w, b.gate["base"])
            out["dispatched"].append(w)
        except Refused as e:
            out["dispatch_failed"].append(f"{w}: {e}")
    if until:
        out["brake_until"] = until
        try:
            gh.comment(n, brake_text(b, a, until))
        except Refused as e:
            out["dispatch_failed"].append(f"brake comment: {e}")
    return out


def after_merge(b, a):
    """The `after_merge` workflows a merge of `a` starts: none after verdicts only (a merge of the claims checker's
    acceptances must not start the checker again); one with `paths` when the change touched one of them."""
    if a.facts.get("verdicts"):
        return []
    changed = a.facts.get("changed")
    return [x["workflow"] for x in b.gate.get(AFTER, [])
            if "paths" not in x or changed is None or any(_listed(x["paths"], p) for p in changed)]


def brake_text(b, a, until):
    """The gate's comment on a change merged while the owner is present: merged, and how long the brake acts."""
    who = " ".join(f"@{x}" for x in [b.gate[PRESENCE]["login"]] if PRESENCE in b.gate)
    tiers = ", ".join(t for t in TIERS if a.facts.get(t))
    upto = a.facts.get("present_until")
    seen = (f" You count as present until {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(upto))}; a reaction of yours to "
            "this comment, or a merge of yours, extends it." if upto else "")
    return (f"{BRAKE_MARK}\n{who} merged with no window before it (you are present).{seen} The brake holds until "
            f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(until))}: the label `{b.gate['hold_label']}` on this pull "
            f"request, or a challenge by `pr/owner` on the head version `{a.accept[1]}`, and the gate reverts this merge "
            f"({tiers} paths: {', '.join(f'`{p}`' for t in TIERS for p in (a.facts.get(t) or [])[:8])}).\n")


def notice_text(a, base):
    """The gate's one comment on a pull request whose constitutional window has opened: what changes, until when a
    veto stops it, how to file one. It names the logins `notify` lists: the one notification the owner receives."""
    k = a.facts["notice"]
    when = lambda t: time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t)) if t is not None else "unknown"
    who = " ".join(f"@{x}" for x in k["notify"])
    return "\n".join([NOTICE.format(x=k["x"]), f"{who} a constitutional window opened on #{a.pr['number']} (head version "
                      f"`{k['version'][:12]}` at `{str(k['x'])[:12]}`).", "",
                      f"It changes: {', '.join(f'`{p}`' for p in k['paths'][:12])}.",
                      f"With {k['families']} model families accepting, the gate may merge it from {when(k['window_until'])}; "
                      f"with one family, from {when(k['solo_until'])}.",
                      f"To stop it: the label `{base.gate['hold_label']}` on this pull request, or a challenge on the head "
                      f"version `{k['version']}` by a holder of `pr/owner` (`warrant challenge`). Either stops the merge "
                      "until it is removed or answered.", "",
                      (f"A reaction of yours to this comment makes you present for {base.gate[PRESENCE]['days']} days: then "
                       "the gate merges such a change once its checks are green and the brake acts after the merge."
                       if PRESENCE in base.gate else "")]) + "\n"


def notify(b, found, gh):
    """Post the notice of each assessment whose constitutional window opened and whose head commit has none yet;
    [(pr, outcome)]. A failure is reported, never the end of the run."""
    out = []
    for a in found:
        k = a.facts.get("notice")
        if not k:
            continue
        mark = NOTICE.format(x=k["x"])
        try:
            if any(mark in (c.get("body") or "") and (c.get("user") or {}).get("login") == f"{ACTIONS_APP}[bot]"
                   for c in gh.comments(a.pr["number"])):
                continue
            gh.comment(a.pr["number"], notice_text(a, b))
            out.append((a.pr["number"], "noticed"))
        except Refused as e:
            out.append((a.pr["number"], f"notice FAILED: {e}"))
    return out


def describe(m):
    if not m["merged"]:
        return f"#{m['pr']} not merged: {m['why']}"
    s = (f"#{m['pr']} as `{m['merge'][:12]}` (parents {', '.join(p[:12] for p in m['parents'])}"
         f"{'' if m['as_assessed'] else ': NOT the base and head assessed'}); dispatched on the base: "
         f"{', '.join(m['dispatched']) or 'nothing'}")
    return s + (f"; dispatch FAILED: {'; '.join(m['dispatch_failed'])}" if m["dispatch_failed"] else "")


def cmd_gate(root, base, merge=False, hold=False, summary=None, prs=(), remote="origin", as_json_=False, gh=None):
    """Assess every open pull request into the base branch; with merge, merge the first eligible one."""
    b = Base(root, _sha(base))
    gh = gh or GitHub(b.repository)
    try:
        until = presence_until(root, b, gh)
        here = until is not None and until > time.time()
        found = survey(root, b, gh, set(prs), hold=hold, remote=remote, present_=here)
        for x in found:
            x.facts["present_until"] = until
    except Refused as e:
        _append(summary, f"## merge-on-acceptance\n\nNothing assessed: `{e.code}` {e}\n")
        if e.code == "BASE_MOVED":          # a merge landed meanwhile: the run its CI starts reads the new base
            print(f"REFUSED {e.code} {e}")
            return 0
        raise
    merged, noticed = None, []
    if merge:
        away = announce_away(b, gh, until)
        noticed = (notify(b, found, gh) + enforce_brakes(root, b, gh, found) + refresh_verdicts(root, b, gh, found)
                   + ([(0, away)] if away else []))
        first = next((x for x in found if x.eligible and x.facts.get("revert")), None) or next((x for x in found if x.eligible), None)
        merged = merge_one(b, first, gh) if first is not None else None
    _append(summary, summary_markdown(found, describe(merged) if merged else None, base)
            + "".join(f"- notice #{n}: {o}\n" for n, o in noticed))
    for x in found:
        print(line(x))
    if merged:
        print("MERGE " + describe(merged))
    if as_json_:
        print(json.dumps({"base": base, "assessments": [as_json(x) for x in found], "merge": merged}, indent=1))
    return 0


def cmd_due(root, base, as_json_=False, remote="origin", gh=None):
    """The pull requests due for review (the waker's), one line each or JSON."""
    b = Base(root, _sha(base))
    found = survey(root, b, gh or GitHub(b.repository), remote=remote)
    if as_json_:
        print(json.dumps({"base": base, "due": [as_json(x) for x in found if x.due],
                          "not_due": [as_json(x) for x in found if not x.due]}, indent=1))
    else:
        for x in found:
            print(("DUE " if x.due else "not due ") + line(x) + ("" if x.due else " | " + ", ".join(c for c, _ in x.not_due)))
    return 0


def _append(path, text):
    """Append to the job summary: a file of the runner's own (RUNNER_TEMP) or of the current directory."""
    if path:
        real = os.path.realpath(path)
        if not any(real.startswith(os.path.realpath(b) + os.sep) for b in filter(None, (os.environ.get("RUNNER_TEMP"), os.getcwd()))):
            raise Refused(f"{path}: the summary is a file of the runner's temporary directory or of the current one", "GATE_INPUT")
        with open(real, "a", encoding="utf-8") as f:
            f.write(text)


def main(argv=None):
    """python3 -m warrant.gate [--root DIR] gate --base M [--merge] [--gate-var V] [--summary FILE] [--pr N ...] [--json]
       python3 -m warrant.gate [--root DIR] due --base M [--json]
       python3 -m warrant.gate [--root DIR] brakes --at C       # exit 1 while a merge in C's history may still be vetoed
    The workflow runs this module from the base commit's checkout (`tools/gate.py`, a shim of it, in this package's
    own repository), so that what merges is decided by this file and the core alone."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="warrant.gate")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("gate", "due"):
        c = sub.add_parser(name)
        c.add_argument("--base", required=True)
        c.add_argument("--json", action="store_true")
        c.add_argument("--remote", default="origin")
    g = sub.choices["gate"]
    g.add_argument("--merge", action="store_true")
    g.add_argument("--gate-var", default="")
    g.add_argument("--summary")
    g.add_argument("--pr", type=int, action="append", default=[])
    k = sub.add_parser("brakes")
    k.add_argument("--at", required=True)
    k.add_argument("--version", help="the version the release declares: a PEP 440 pre-release is released with brakes open")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "brakes":
            open_ = brakes(a.root, _sha(a.at))
            for x in open_:
                print(f"OPEN #{x['pr']} merged as {x['merge'][:12]}: its brake holds until "
                      f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(x['until']))}")
            print(f"{len(open_)} merge(s) at {a.at[:12]} whose brake is still open")
            pre = a.version is not None and bool(PRERELEASE.fullmatch(a.version))
            if open_ and pre:
                print(f"{a.version} is a pre-release: released with brakes open; a revert names it")
            return 1 if open_ and not pre else 0
        if a.cmd == "due":
            return cmd_due(a.root, a.base, a.json, a.remote)
        return cmd_gate(a.root, a.base, a.merge, a.gate_var == "hold", a.summary, a.pr, a.remote, a.json)
    except Refused as e:
        print(f"REFUSED {e.code} {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
