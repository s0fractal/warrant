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
      blobs added under .warrant/blobs/ (TAIL_CHANGES); every blob added is cited by a record added
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
    - it changes none of the base's merge.json owner_paths (OWNER_PATHS: the owner merges those);
    - every required check merge.json names is green at the head: the latest GitHub Actions check run of that
      name whose workflow run is the named workflow file concluded success, and none of that name comes from
      another workflow (CHECK_MISSING, CHECK_PENDING, CHECK_RED, CHECK_AMBIGUOUS).

  due-for-review  the same facts and shared refusals, and no verdict at the head yet: no acceptance and no
    counted challenge of the leaf. A pull request of verdicts only is never due.

The gate (`gate`) merges at most one eligible pull request per run, reading the pull request and the base
branch again just before (TOCTOU), giving GitHub the assessed head (it refuses the merge when the head
moved), and then dispatches the required workflows on the base branch (a GITHUB_TOKEN merge starts none)."""
import json
import os
import re
import subprocess
from pathlib import PurePosixPath

from warrant import engine as E
from warrant import jcs as C
from warrant import shapes as S
from warrant.store import Snapshot

GATE = "warrant-review/gate@1"
GATE_FIELDS = ("gate", "base", "required", "hold_label", "owner_paths")
REPOSITORY_DOC = "repository/3"
RECORDS, BLOBS = ".warrant/records.jsonl", ".warrant/blobs/"
REGULAR = "100644"
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")
WORKFLOW = re.compile(r"\.github/workflows/[A-Za-z0-9._-]+\.ya?ml\Z")
CHECK = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ()._/-]{0,99}\Z")
OWNER_PATH = re.compile(r"(?!.*\.\.)[A-Za-z0-9._-][A-Za-z0-9._/-]{0,199}\Z")
REPO_NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
ACTIONS_APP = "github-actions"
VERDICT_BRANCH = "codex/verdicts/"
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
               "--parents", "-", "--"}


def git(root, *args, stdin=None):
    """Git at `root`, refused when an argument that is no known option starts with "-" (a ref, a path or a remote
    named by a caller must never be read as an option)."""
    bad = [a for a in args if str(a).startswith("-") and a not in GIT_OPTIONS]
    if bad:
        raise Refused(f"git arguments that look like options: {bad[:3]}", "GATE_INPUT")
    r = subprocess.run(["git", "-C", os.path.realpath(root), *map(str, args)], input=stdin, capture_output=True, check=False)
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


def owner_paths(root, base, x, listed):
    """The paths changed from the merge base of `base` and `x` to `x` that `listed` names (an entry ending in /
    names a directory), or None when they have no merge base."""
    try:
        mb = git(root, "merge-base", base, x).decode().split()[0]
    except (subprocess.CalledProcessError, IndexError):
        return None
    raw = git(root, "diff-tree", "-r", "-z", "--no-renames", "--no-commit-id", "--name-only", mb, x).decode()
    return sorted(p for p in raw.split("\0") if p and any(p == e or (e.endswith("/") and p.startswith(e)) for e in listed))


def is_ancestor(root, a, b):
    try:
        git(root, "merge-base", "--is-ancestor", a, b)
        return True
    except subprocess.CalledProcessError:
        return False


# ---------------------------------------------------------------- the base

def gate_config(doc):
    req = doc.get("required") if isinstance(doc, dict) else None
    ok = (isinstance(doc, dict) and set(doc) == set(GATE_FIELDS) and doc["gate"] == GATE
          and isinstance(doc["base"], str) and BRANCH.match(doc["base"]) and isinstance(req, list) and req
          and all(isinstance(c, dict) and set(c) == {"check", "workflow"} and isinstance(c["check"], str)
                  and CHECK.match(c["check"]) and isinstance(c["workflow"], str) and WORKFLOW.match(c["workflow"]) for c in req)
          and len({c["check"] for c in req}) == len(req)
          and isinstance(doc["hold_label"], str) and CHECK.match(doc["hold_label"])
          and isinstance(doc["owner_paths"], list) and all(isinstance(x, str) and OWNER_PATH.match(x) for x in doc["owner_paths"]))
    if not ok:
        raise Refused(f".warrant/merge.json members are {list(GATE_FIELDS)}, gate {GATE!r}, a branch name, a non-empty "
                      "list of distinct {check, workflow}, a label and a list of paths", "BASE_CONFIG")
    return doc


class Base:
    """What the base commit says: the gate's configuration (.warrant/merge.json) and the receiver's
    (.warrant/v3.json: the repository, the trust and the profile every head is assessed under)."""

    FILES = (".warrant/merge.json", ".warrant/v3.json")

    def __init__(self, root, commit):
        self.root, self.commit = root, commit
        files = files_at(root, commit, self.FILES)
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

    def roadmap_due(self, actor):
        """{version ids} the base's own records hold due for `actor`'s verdict: the leaf of a goal@1 or obligation@1
        lineage whose guard waits only for attests by a role the actor holds (no open requirement), not its own,
        neither attested nor challenged by it (the waker's `roadmap.py due`)."""
        snap, problems = store_at(self.root, self.commit)
        if problems:
            return set()
        return {x["version"] for x in due_for(assess_snapshot(self, snap), self.profile, actor, ("goal@1", "obligation@1"))}


def due_for(rep, profile, actor, schemas):
    """The versions of `schemas` waiting for `actor`'s verdict in report `rep` (warrant_agent.graph.frontier's
    rule, stated here again so that the gate's decision rests on no file outside the owner paths but the core)."""
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


def assess(root, base, pr, checks, hold=False):
    """The Assessment of pull request `pr` against the base commit `base` (a full id, or a Base already read)."""
    a = Assessment(pr, base if isinstance(base, str) else base.commit)
    try:
        b = base if isinstance(base, Base) else Base(root, base)
    except (Refused, subprocess.CalledProcessError) as e:
        a.shared.append(("BASE_CONFIG", str(e)))
        a.reasons += a.shared
        return a
    reasons = pr_reasons(b, pr, hold)
    a.reasons += [r for r in reasons if r[0] in HOLDS]
    a.shared += [r for r in reasons if r[0] not in HOLDS]
    _shared(a, root, b, pr, checks)
    a.reasons += a.shared
    return a


def _shared(a, root, b, pr, checks):
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
    _review(a, root, b, pr, head, rep)


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


def _review(a, root, b, pr, head, rep):
    sh, n = a.shared, pr["number"]
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
                   author=rep["_recs"][L]["actor"])
    try:
        x, tree = canonical(root, leaf["body"].get("commit"))
    except Refused as e:
        sh.append(("HEAD_COMMIT", f"the head version: {e}"))
        return
    if tree != leaf["body"].get("tree"):
        sh.append(("HEAD_COMMIT", f"{x[:12]} has tree {tree[:12]}; the head version names {str(leaf['body'].get('tree'))[:12]}"))
        return
    if not is_ancestor(root, x, head):
        sh.append(("HEAD_NOT_ANCESTOR", f"{x[:12]} is not an ancestor of #{n}'s head {head[:12]}"))
        return
    owned = owner_paths(root, b.commit, x, b.gate["owner_paths"])
    if owned is None or owned:
        a.reasons.append(("OWNER_PATHS", "the owner merges a change to what decides merging: "
                          + (", ".join(owned[:8]) if owned else f"{x[:12]} has no merge base with the base")))
    extra, lines, blobs = tail(root, x, head)
    if extra:
        sh.append(("TAIL_CHANGES", f"{len(extra)} change(s) after {x[:12]} beyond added record lines and blobs: "
                   + ", ".join(f"{p} ({w})" for p, w in extra[:8])))
    added = _ids(lines)
    loose = _uncited(rep, added, blobs)
    if loose:
        sh.append(("TAIL_BLOB_UNCITED", f"{len(loose)} blob(s) added after {x[:12]} are cited by no record added there: "
                   + ", ".join(o[:12] for o in loose[:8])))
    versions = set(lin["versions"])
    stray = []
    for r in added:
        rec = rep["_recs"].get(r)
        about = rec["body"].get("target") if rec and rec["kind"] in ("attest", "challenge") else None
        ok = rec is not None and (
            (rec["kind"] in ("attest", "challenge") and rec["actor"] in b.holders("pr/acceptor"))
            or r in versions or about in versions
            or (rec["kind"] == "attest" and rec["actor"] in b.holders("replayer")
                and (rep["_recs"].get(about) or {}).get("schema") == "finding@1"))
        if not ok:
            stray.append(r or "unreadable")
    if stray:
        sh.append(("TAIL_RECORD_UNREVIEWED", f"{len(stray)} record(s) added after {x[:12]} are neither a verdict of a "
                   f"pr/acceptor, #{n}'s own, nor a replay result: " + ", ".join(s[:12] for s in stray[:8])))
    v = rep["versions"][lin["leaf"]]
    by = sorted(set(v["accepted_by"]) & b.holders("pr/acceptor"))
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
    if not all(x is not None and x["kind"] in ("attest", "challenge") and x["actor"] in acceptors for x in recs):
        return None
    out = []
    if pr.get("head_repo") != b.repository:
        out.append(("VERDICTS_FORK", f"#{pr['number']}'s head is a branch of {str(pr.get('head_repo'))[:60]!r}, not {b.repository}"))
    if not str(pr.get("branch") or "").startswith(VERDICT_BRANCH):
        out.append(("VERDICTS_BRANCH", f"#{pr['number']}'s branch {str(pr.get('branch'))[:60]!r} is not under {VERDICT_BRANCH}"))
    base_snap, _ = store_at(root, b.commit)
    old = [r for r in added if r in base_snap.lines]
    if old:
        out.append(("VERDICT_NOT_NEW", f"{len(old)} verdict(s) the base holds already: " + ", ".join(r[:12] for r in old[:8])))
    due = {actor: b.roadmap_due(actor) for actor in {x["actor"] for x in recs}}
    late = [r for r, x in zip(added, recs) if x["body"]["target"] not in due[x["actor"]]]
    if late:
        out.append(("VERDICT_NOT_DUE", f"{len(late)} verdict(s) on a version the base's roadmap does not hold due for its "
                    "actor: " + ", ".join(r[:12] for r in late[:8])))
    loose = _uncited(rep, added, blobs)
    if loose:
        out.append(("TAIL_BLOB_UNCITED", f"{len(loose)} blob(s) cited by no verdict: " + ", ".join(o[:12] for o in loose[:8])))
    a.facts.update(verdicts=sorted(added), x=mb)
    a.verdict = True
    a.accept = (recs[0]["actor"], sorted(added)[0], mb)
    return out


# ---------------------------------------------------------------- formats

def line(a):
    n = a.pr["number"]
    if a.eligible and a.facts.get("verdicts"):
        return f"#{n} {a.pr['head'][:12]}: ELIGIBLE (verdicts only, by {a.accept[0]}, from {a.accept[2][:12]})"
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
            "branch": p["head"].get("ref"), "title": p.get("title"), "head_repo": (p["head"].get("repo") or {}).get("full_name")}


def fetch(root, n, remote="origin"):
    """Fetch pull request `n`'s head into refs/warrant-gate/pull/<n> (Git data only) and return its id."""
    ref = REF.format(n=_number(n))
    git(root, "fetch", "--no-tags", "--quiet", remote, f"+refs/pull/{n}/head:{ref}")
    return git(root, "rev-parse", "--verify", ref).decode().strip()


def survey(root, b, gh, prs=None, hold=False, remote="origin"):
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
            a = assess(root, b, pr, gh.checks(pr["head"]), hold=hold)
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
    if a.facts.get("verdicts"):
        title = f"Merge pull request #{n} (verdicts by {actor})"
        message = f"merge-on-acceptance: verdicts only, {', '.join(a.facts['verdicts'])}, from {x}; head {head}; base {base}."
    else:
        title = f"Merge pull request #{n} (accepted by {actor})"
        message = f"merge-on-acceptance: head version {rid} accepted by {actor} at {x}; head {head}; base {base}."
    try:
        res = gh.merge(n, head, title, message + " Required checks green at the head.")
    except Refused as e:
        return {"pr": n, "merged": False, "why": f"GitHub refused the merge: {e}"}
    if res.get("merged") is not True or not S.hex_of(res.get("sha"), 40):
        return {"pr": n, "merged": False, "why": f"GitHub answered {json.dumps(res)[:200]}"}
    parents = gh.parents(res["sha"])
    out = {"pr": n, "merged": True, "merge": res["sha"], "parents": parents, "head": head, "base": base,
           "as_assessed": parents == [base, head], "dispatched": [], "dispatch_failed": []}
    for w in sorted({c["workflow"] for c in b.gate["required"]}):
        try:
            gh.dispatch(w, b.gate["base"])
            out["dispatched"].append(w)
        except Refused as e:
            out["dispatch_failed"].append(f"{w}: {e}")
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
        found = survey(root, b, gh, set(prs), hold=hold, remote=remote)
    except Refused as e:
        _append(summary, f"## merge-on-acceptance\n\nNothing assessed: `{e.code}` {e}\n")
        if e.code == "BASE_MOVED":          # a merge landed meanwhile: the run its CI starts reads the new base
            print(f"REFUSED {e.code} {e}")
            return 0
        raise
    merged = None
    if merge:
        first = next((x for x in found if x.eligible), None)
        merged = merge_one(b, first, gh) if first is not None else None
    _append(summary, summary_markdown(found, describe(merged) if merged else None, base))
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
    """python3 tools/gate.py [--root DIR] gate --base M [--merge] [--gate-var V] [--summary FILE] [--pr N ...] [--json]
       python3 tools/gate.py [--root DIR] due --base M [--json]
    The workflow runs this file itself, so that what merges is decided by this file and the core alone."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="gate.py")
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
    a = ap.parse_args(argv)
    try:
        if a.cmd == "due":
            return cmd_due(a.root, a.base, a.json, a.remote)
        return cmd_gate(a.root, a.base, a.merge, a.gate_var == "hold", a.summary, a.pr, a.remote, a.json)
    except Refused as e:
        print(f"REFUSED {e.code} {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
