"""Merge eligibility and due-for-review of a pull request: one predicate, read from Git data only.

`assess` reads a pull request (its number, state, base branch, head commit and labels, as GitHub
reports them) against a base commit, in the Git repository at `root`, and returns an Assessment
holding two verdicts computed from the same facts:

  merge-eligible  every one of these holds (`reasons` is empty):
    - the owner's holds are off: no `hold` label on the pull request (merge.json `hold_label`),
      and the caller's global hold (the repository variable WARRANT_MERGE_GATE=hold) is off;
    - the pull request is open, not a draft, and into the base branch merge.json names;
    - the head's store is read from the head commit's tree as Git objects (no checkout, nothing of
      it run): every entry under .warrant/store is a regular file (100644) named by its content
      address, else STORE_ENTRY;
    - under the base's configuration (.warrant/reviews.json, .warrant/merge.json) and a trust made
      only of the keys the BASE's .warrant/roles.json pins (never the head's roles.json or
      trust.json, never a receiver's local trust), the head's store holds the pull request's review
      duty, its review records have no problem, and its heads do not fork;
    - the latest head's closure names a commit X that is canonical with the tree it names and an
      ancestor of the pull request's head;
    - the head's tree differs from X's only by added records and blobs of .warrant/store (regular
      files, named by content address) and by the bytes of the generated views (REVIEWS.md,
      ROADMAP.md, SPEC-CLAIMS.md, WITNESSES.md; added or changed), and every blob it adds is cited by a
      record it adds (a probe, evidence; else TAIL_BLOB_UNCITED). That those views are the
      byte-identical rendering of the head's records is checked by the required check `test` at the
      head, which runs the head's own `claims.py check`, `review.py check` and `roadmap.py check`: code
      byte-identical to X's, since the tail touches nothing else;
    - every record added after X is either a verdict record (authentic under the base's pins and signed
      by an actor of the base's accept_by), a review-loop record of this pull request's own duty (the
      duty, its head closures, findings against its heads, a merge observation) or an observation by a
      replayer of the base's reviews.json of any mechanical finding at one of its heads (the review
      waker files those on top of a head; the required check `test` re-executes each one new since the
      base, `review.py replay --verify`). Any other record (an unrelated transition, a grant, a record
      the base's pins do not authenticate) was never reviewed: TAIL_RECORD_UNREVIEWED;
    - an actor of the base's accept_by, other than the duty's author (the pull request's author
      actor) and the closure's filer, accepted exactly that closure, item 0 and its evidence, by a
      record signed with the key the base's roles.json pins for it (the trust above);
      or, for a pull request with no review duty of its own, it carries verdicts only: its whole change
      since its merge base with the base is a records-only tail (as above) whose added records are each
      an accept or a challenge by an actor of the base's accept_by (verdicts), each new (not in the base's
      store) and each of a closure item the BASE's tools/roadmap.py acceptance_due names for that actor;
      its head is a branch of this repository (not a fork) named under codex/verdicts/. The tail rule
      above admits such records after any reviewed head with no further review: a verdict is the
      reviewer's own act, and the reviewer cannot review itself. Codex's verdict on a roadmap
      obligation's closure filed on master travels this way (the review waker's acceptance wakes);
    - no finding (a challenge carrying a finding blob) stands against that head;
    - the pull request changes none of the base's merge.json `owner_paths` (what decides merging:
      the workflows, the role pins, the review and gate configuration, this predicate): those
      changes are reviewed as any other, and merged by the owner (AGENTS.md, rule 5: weakening
      protection needs a separate owner decision);
    - every required check merge.json names is green at the head commit: the latest GitHub Actions
      check run of that name whose workflow run is the named workflow file concluded success, and no
      check run of that name comes from another workflow.

  due-for-review  the pull request is open, not a draft, into the base branch; the base and the
    head's store read as above; the latest head's closure is at the head (X canonical, an ancestor,
    and the same records-only tail, its added records verdicts, this pull request's own or replay observations); every required check is green at the head; and there is no
    verdict at that head: no acceptance by a reviewer (the acceptance rule above) and no finding. A
    pull request of verdicts only is never due: it is the reviewer's own.

Both share every fact and every rule above; only the last clauses differ. Formats are functions of
an Assessment (summary_markdown, as_json, line). The GitHub calls are tools/claimslib/forge.py's;
the gate and the waker are `tools/review.py gate` and `tools/review.py due`.
"""
import json
import re
import subprocess

from warrant import jcs as C
from warrant import limits as L
from warrant import records as R
from warrant import shapes as S
from warrant.bindings import read_roles
from warrant.store import Snapshot, Trust

from . import reviews as RV
from .base import Refused

GATE = "warrant-review/gate@1"
GATE_FIELDS = ("gate", "base", "required", "hold_label", "owner_paths")
STORE = ".warrant/store/"
VIEWS = RV.LEDGER_FILES                # the generated views a records-only tail may change
REGULAR = "100644"
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")
WORKFLOW = re.compile(r"\.github/workflows/[A-Za-z0-9._-]+\.ya?ml\Z")
CHECK = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ()._/-]{0,99}\Z")
OWNER_PATH = re.compile(r"(?!.*\.\.)[A-Za-z0-9._-][A-Za-z0-9._/-]{0,199}\Z")
ACTIONS_APP = "github-actions"


# ---------------------------------------------------------------- Git data

def _git(root, *args, ids=(), paths=(), stdin=None):
    """Git at `root` (a checkout or a bare repository); ids are full object ids (reviews._git)."""
    if stdin is None:
        return RV._git(root, *args, ids=ids, paths=paths)
    if ids or paths:
        raise ValueError("stdin and ids are not combined")
    r = subprocess.run(["git", "-C", str(root), *args], input=stdin, capture_output=True, check=False)
    if r.returncode:
        raise subprocess.CalledProcessError(r.returncode, args, r.stdout, r.stderr)
    return r.stdout


def entries(root, commit, path):
    """[(mode, type, object id, size or None, path)] of the tree of `commit` under `path` (recursive)."""
    out = []
    for e in _git(root, "ls-tree", "-r", "-l", "-z", "--full-tree", ids=(commit,), paths=(path,)).decode().split("\0"):
        if e:
            meta, p = e.split("\t", 1)
            mode, typ, oid, size = meta.split()
            out.append((mode, typ, oid, int(size) if size.isdigit() else None, p))
    return out


def objects(root, oids):
    """{object id: bytes} read by one `git cat-file --batch` from standard input."""
    oids = list(dict.fromkeys(oids))
    if not oids:
        return {}
    data = _git(root, "cat-file", "--batch", stdin="".join(f"{o}\n" for o in oids).encode())
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
    """{path: bytes} of the regular files `paths` in the tree of `commit` (a path that is absent is left
    out). A symlink, a submodule or a tree there is refused: a base file is read as Git stores it."""
    rows = {}
    for e in _git(root, "ls-tree", "-z", "--full-tree", ids=(commit,), paths=paths).decode().split("\0"):
        if e:
            meta, path = e.split("\t", 1)
            rows[path] = meta.split()               # mode, type, object id
    for path, (mode, typ, _) in rows.items():
        if path in paths and (mode, typ) != (REGULAR, "blob"):
            raise Refused(f"{path} at {commit[:12]} is mode {mode}, not a regular file", "BASE_CONFIG")
    data = objects(root, [rows[p][2] for p in paths if p in rows])
    return {p: data[rows[p][2]] for p in paths if p in rows}


def store_at(root, commit, limits=None):
    """(Snapshot, problems) of .warrant/store in the tree of `commit`, from Git objects only: no
    checkout, no archive, nothing written. An entry that is not a regular file named by its content
    address (records/<hex64>.json, blobs/<hex64>) is a problem and left out."""
    lim = L.resolve(limits)
    rows, problems, want = entries(root, commit, STORE.rstrip("/")), [], []
    size = 0
    for mode, typ, oid, n, p in rows:
        kind, _, name = p[len(STORE):].partition("/")
        named = (kind == "records" and name.endswith(".json") and S.hex64(name[:-5])) or (kind == "blobs" and S.hex64(name))
        if (mode, typ) != (REGULAR, "blob") or not named:
            problems.append(("STORE_ENTRY", f"{p} is mode {mode} {typ}: the store holds regular files "
                             "records/<hex64>.json and blobs/<hex64> only"))
            continue
        size += n or 0
        want.append((kind, name, oid))
    L.admit(lim, "snapshot_records", sum(k == "records" for k, _, _ in want))
    L.admit(lim, "snapshot_blobs", sum(k == "blobs" for k, _, _ in want))
    L.admit(lim, "snapshot_bytes", size)
    data = objects(root, [o for _, _, o in want])
    recs, blobs = {}, {}
    for kind, name, oid in want:
        if kind == "records":
            recs[name[:-5]] = data[oid]
        elif C.digest(data[oid]) == name:
            blobs[name] = data[oid]
        else:
            problems.append(("STORE_ENTRY", f"{STORE}blobs/{name} is not named by its hash"))
    return Snapshot(recs, blobs), problems


def stored(path):
    """("records", id) or ("blobs", id) for a store entry named by its content address, else None."""
    kind, _, name = path[len(STORE):].partition("/") if path.startswith(STORE) else ("", "", "")
    if kind == "records" and name.endswith(".json") and S.hex64(name[:-5]):
        return kind, name[:-5]
    if kind == "blobs" and S.hex64(name):
        return kind, name
    return None


def tail(root, x, head, added=None, blobs=None):
    """[(path, why)] of the changes from commit `x` to commit `head` other than a records-only tail:
    an added regular file .warrant/store/records/<hex64>.json or .warrant/store/blobs/<hex64>, or an
    added or changed regular file among the generated views (VIEWS). Renames are read as delete and add.
    The ids of the records it adds are appended to `added` (tail_records reads what they are), those of
    the blobs to `blobs` (uncited)."""
    raw = _git(root, "diff-tree", "-r", "-z", "--no-renames", "--no-commit-id", ids=(x, head)).decode().split("\0")
    out, sinks = [], {"records": added, "blobs": blobs}
    for i in range(0, len(raw) - 1, 2):
        meta, path = raw[i], raw[i + 1]
        old_mode, new_mode, _, _, status = meta.lstrip(":").split()
        record = stored(path)
        if status == "A" and new_mode == REGULAR and record:
            if sinks[record[0]] is not None:
                sinks[record[0]].append(record[1])
            continue
        if status in ("A", "M") and new_mode == REGULAR and old_mode in (REGULAR, "000000") and path in VIEWS:
            continue
        out.append((path, f"{status} {old_mode}->{new_mode}"))
    return out


def tail_records(b, model, rv, added):
    """The records of `added` (ids added after the accepted commit) that are neither a verdict record (an
    authentic record, under the base's pins, by an actor of the base's accept_by), a review-loop record
    of this pull request's own duty (the duty, its head closures, findings against its heads, a merge
    observation) nor a replay observation the model admits (by a replayer of the base's reviews.json, of
    any pull request's mechanical finding at one of its heads; re-executed by the check `test`): records
    nobody reviewed."""
    mine = ({rv.did} | {h.tid for h in rv.heads} | {f.cid for f in rv.findings} | {o for o, _, _ in rv.merges}
            | {o for f in model.findings.values() for o, _ in f.observed.values()})
    return sorted(r for r in added if r not in mine
                  and (r not in model.recs or model.recs[r]["actor"] not in b.cfg["accept_by"]))


def uncited(model, added, blobs):
    """The blobs of `blobs` (added in a tail) that no record of `added` (added in the same tail) cites anywhere
    in its body (evidence, a probe, raw outputs): bytes nothing in the record graph refers to."""
    cited = set()

    def walk(v):
        if isinstance(v, str) and S.hex64(v):
            cited.add(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    for r in added:
        walk((model.recs.get(r) or {}).get("body"))
    return sorted(o for o in set(blobs) - cited if o in model.snap.blobs)      # a misnamed one is STORE_ENTRY's


def owner_paths(root, base, x, listed):
    """The paths the pull request changes (from the merge base of `base` and `x` to `x`) that `listed`
    names (an entry ending in / names a directory), or None when they have no merge base."""
    try:
        mb = _git(root, "merge-base", ids=(base, x)).decode().split()
    except subprocess.CalledProcessError:
        return None
    raw = _git(root, "diff-tree", "-r", "-z", "--no-renames", "--no-commit-id", "--name-only", ids=(mb[0], x)).decode()
    return sorted(p for p in raw.split("\0") if p and any(p == e or (e.endswith("/") and p.startswith(e)) for e in listed))


def is_ancestor(root, a, b):
    try:
        _git(root, "merge-base", "--is-ancestor", ids=(a, b))
        return True
    except subprocess.CalledProcessError:
        return False


# ---------------------------------------------------------------- the base's configuration

def gate_config(doc):
    """merge.json, checked: the base branch, the required checks (each bound to its workflow file) and
    the hold label."""
    req = doc.get("required") if isinstance(doc, dict) else None
    ok = (isinstance(doc, dict) and set(doc) == set(GATE_FIELDS) and doc["gate"] == GATE
          and isinstance(doc["base"], str) and BRANCH.match(doc["base"])
          and isinstance(req, list) and req
          and all(isinstance(c, dict) and set(c) == {"check", "workflow"} and isinstance(c["check"], str)
                  and CHECK.match(c["check"]) and isinstance(c["workflow"], str) and WORKFLOW.match(c["workflow"])
                  for c in req)
          and len({c["check"] for c in req}) == len(req)
          and isinstance(doc["hold_label"], str) and CHECK.match(doc["hold_label"])
          and isinstance(doc["owner_paths"], list) and all(isinstance(x, str) and OWNER_PATH.match(x) for x in doc["owner_paths"]))
    if not ok:
        raise Refused(f".warrant/merge.json members are {list(GATE_FIELDS)}, gate {GATE!r}, a branch name, a non-empty "
                      "list of distinct {check, workflow}, a label and a list of paths (a directory ends in /)", "BASE_CONFIG")
    return doc


class Base:
    """What the base commit says: the review configuration, the gate's, the role pins and the trust
    made of those pins only."""

    FILES = (".warrant/reviews.json", ".warrant/merge.json", ".warrant/roles.json")

    def __init__(self, root, commit):
        self.commit = commit
        files = files_at(root, commit, self.FILES)

        def doc(path):
            if files.get(path) is None:
                raise Refused(f"{path} does not exist at the base {commit[:12]}", "BASE_CONFIG")
            try:
                return json.loads(files[path])
            except ValueError as e:
                raise Refused(f"{path} at the base: {e}", "BASE_CONFIG") from e

        self.cfg = RV.check_config(doc(".warrant/reviews.json"))
        self.gate = gate_config(doc(".warrant/merge.json"))
        self.roles, problems = read_roles(doc(".warrant/roles.json"))
        if problems:
            raise Refused("; ".join(w for _, w in problems), "BASE_CONFIG")
        self.pins = {a: v for a, v in self.roles.items() if S.hex64(v)}
        try:
            self.trust = Trust(Trust.document(sorted(self.pins.items())))
        except R.Invalid as e:
            raise Refused(f".warrant/roles.json at the base: {e}", "BASE_CONFIG") from e


# ---------------------------------------------------------------- checks

def check_reasons(required, checks, head):
    """[(code, detail)] for each required check that is not green at `head`. `checks` is
    {"check_runs": [...], "workflow_runs": [...]} as the GitHub API returns them for that commit."""
    suites = {}
    for w in checks.get("workflow_runs", []):
        if isinstance(w, dict) and w.get("head_sha") == head:
            suites[w.get("check_suite_id")] = w.get("path")
    out = []
    for c in required:
        runs = [r for r in checks.get("check_runs", []) if isinstance(r, dict) and r.get("name") == c["check"]
                and r.get("head_sha") == head and (r.get("app") or {}).get("slug") == ACTIONS_APP]
        ours = [r for r in runs if suites.get((r.get("check_suite") or {}).get("id")) == c["workflow"]]
        other = [r for r in runs if r not in ours]
        if other:
            out.append(("CHECK_AMBIGUOUS", f"{c['check']}: {len(other)} check run(s) of that name at {head[:12]} come "
                        f"from a workflow other than {c['workflow']}"))
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
    """One pull request against one base: the facts, the merge refusals (`reasons`, empty when
    eligible) and whether it is due for review (`due`, with `not_due`, why not)."""

    def __init__(self, pr, base):
        self.pr, self.base = pr, base
        self.reasons, self.facts = [], {}
        self.shared = []               # refusals of both verdicts
        self.verdict = False           # a reviewer's acceptance or a finding stands at the head
        self.accept = None             # (actor, accept id, closure, commit) when a valid acceptance exists

    @property
    def eligible(self):
        return not self.reasons

    @property
    def due(self):
        return not self.shared and not self.verdict

    @property
    def not_due(self):
        return self.shared + ([("REVIEWED", "a reviewer's acceptance or finding stands at the head")] if self.verdict else [])

    def codes(self):
        return sorted({c for c, _ in self.reasons})


def valid_acceptors(base, model, h, author):
    """{actor: why not or None}: each actor with an authentic acceptance of exactly head `h`'s closure,
    item 0 and its evidence, and None when it counts: an actor of the base's accept_by, neither the
    author nor the closure's filer. Pinned by a key in the base's roles.json it is already: the model
    reads the head's store under a trust of those pins only, so nothing else is authentic."""
    out = {}
    for a in h.accepted_by:
        if a not in base.cfg["accept_by"]:
            out[a] = ("ACCEPT_NOT_ACCEPTOR", f"{a} accepted head {h.n}, and the base's accept_by is {base.cfg['accept_by']}")
        elif a in (author, h.rec["actor"]):
            out[a] = ("ACCEPT_BY_AUTHOR", f"{a} accepted head {h.n} and is the pull request's author or its filer")
        else:
            out[a] = None
    return out


def accept_id(model, h, actor):
    want = tuple(sorted(h.item["evidence"]))
    return next((aid for aid, r in sorted(model.recs.items()) if r["type"] == "accept" and r["actor"] == actor
                 and r["body"]["transition"] == h.tid and r["body"]["item"] == 0
                 and tuple(sorted(r["body"]["evidence"])) == want), None)


def assess(root, base, pr, checks, hold=False):
    """The Assessment of pull request `pr` ({number, state, draft, base, head, labels}) against the base
    commit `base` (a full id, or a Base already read) in the Git repository at `root`, with `checks`
    (check_reasons) and the global hold."""
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


HOLDS = ("GATE_HOLD", "PR_HOLD")          # refusals of a merge only; the rest of pr_reasons refuse both verdicts


def pr_reasons(b, pr, hold=False):
    """[(code, detail)] of the pull request's own state as GitHub reports it: the holds, open, not a draft,
    into the base branch. The gate applies it again to the pull request it reads just before merging."""
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


def _shared(a, root, b, pr, checks):
    """The facts and refusals both verdicts share, then the review's own (_review)."""
    sh = a.shared
    head = pr["head"]
    try:
        head, _ = RV.canonical(root, head)
    except Refused as e:
        sh.append(("HEAD_UNREADABLE", f"#{pr['number']}: {e}"))
        return
    sh += check_reasons(b.gate["required"], checks, head)
    try:
        snap, problems = store_at(root, head)
    except L.LimitExceeded as e:
        sh.append(("STORE_ENTRY", f"the head's store is beyond an admission limit: {e}"))
        return
    sh += problems
    model = RV.Model(snap, b.trust, b.cfg)
    if model.problems:
        sh.append(("REVIEW_RECORDS", f"{len(model.problems)} problem(s) in the head's review records: "
                   + "; ".join(f"{c} {d[:120]}" for c, d in model.problems[:3])))
    _review(a, root, b, pr, head, model)


def _review(a, root, b, pr, head, model):
    sh = a.shared
    rv = model.reviews.get(pr["number"])
    if rv is None:
        why = _verdicts_only(a, root, b, pr, head, model)
        if why is None:
            sh.append(("NO_REVIEW", f"the head's store holds no review duty of #{pr['number']} on the base's terms "
                       "and adds more than verdicts"))
        sh += why or []
        return
    if rv.fork:
        sh.append(("HEAD_FORK", f"#{pr['number']}'s heads fork"))
        return
    h = rv.latest()
    if h is None:
        sh.append(("NO_HEAD", f"#{pr['number']} has no head closure"))
        return
    a.facts.update(duty=rv.did, closure=h.tid, head_n=h.n, x=h.commit, author=rv.rec["actor"], verdict=h.verdict)
    try:
        x, tree = RV.canonical(root, h.commit)
    except Refused as e:
        sh.append(("HEAD_COMMIT", f"head {h.n}: {e}"))
        return
    if tree != h.tree:
        sh.append(("HEAD_COMMIT", f"head {h.n}: {x[:12]} has tree {tree[:12]}, the closure names {h.tree[:12]}"))
        return
    if not is_ancestor(root, x, head):
        sh.append(("HEAD_NOT_ANCESTOR", f"head {h.n}'s commit {x[:12]} is not an ancestor of #{pr['number']}'s head {head[:12]}"))
        return
    owned = owner_paths(root, b.commit, x, b.gate["owner_paths"])
    if owned is None or owned:
        a.reasons.append(("OWNER_PATHS", "the owner merges a change to what decides merging: " + (
            ", ".join(owned[:8]) if owned else f"{x[:12]} has no merge base with the base")))
    added, blobs = [], []
    extra = tail(root, x, head, added, blobs)
    if extra:
        sh.append(("TAIL_CHANGES", f"{len(extra)} change(s) after head {h.n} ({x[:12]}) beyond added records and "
                   "regenerated views: " + ", ".join(f"{p} ({w})" for p, w in extra[:8])))
    loose = uncited(model, added, blobs)
    if loose:
        sh.append(("TAIL_BLOB_UNCITED", f"{len(loose)} blob(s) added after head {h.n} ({x[:12]}) are cited by no record "
                   "added there: " + ", ".join(o[:12] for o in loose[:8])))
    stray = tail_records(b, model, rv, added)
    if stray:
        sh.append(("TAIL_RECORD_UNREVIEWED", f"{len(stray)} record(s) added after head {h.n} ({x[:12]}) are neither "
                   f"a verdict of {b.cfg['accept_by']} nor #{pr['number']}'s own review records: "
                   + ", ".join(r[:12] for r in stray[:8])))
    found = [f for f in rv.findings if f.head is h]
    accepts = valid_acceptors(b, model, h, rv.rec["actor"])
    good = sorted(x for x, why in accepts.items() if why is None)
    a.verdict = bool(good) or bool(found)
    if found:
        a.reasons.append(("OPEN_FINDING", f"{len(found)} finding(s) stand against head {h.n}: "
                          + ", ".join(f.cid[:12] for f in found)))
    a.reasons += [why for why in accepts.values() if why is not None]
    if not accepts:
        a.reasons.append(("NO_ACCEPT", f"no acceptance of head {h.n}'s closure {h.tid[:12]} by an actor of "
                          f"{b.cfg['accept_by']}"))
    if good:
        a.accept = (good[0], accept_id(model, h, good[0]), h.tid, x)


def _verdicts_only(a, root, b, pr, head, model):
    """None when the pull request does not carry verdicts only: from the merge base of the base and the head,
    a records-only tail whose added records are each an accept or a challenge, authentic under the base's
    pins, by an actor of the base's accept_by. Else [(code, detail)] of what refuses it (the module's rule:
    a fork, another branch, a verdict the base holds already or on a closure item the base's acceptance_due
    does not name for its actor, an uncited blob), and the pull request is eligible when that is empty and
    the rest holds, never due; a.accept names its first verdict, at the merge base."""
    try:
        mb = _git(root, "merge-base", ids=(b.commit, head)).decode().split()[0]
    except (subprocess.CalledProcessError, IndexError):
        return None
    added, blobs = [], []
    if tail(root, mb, head, added, blobs):
        return None
    verdicts = sorted(r for r in added if r in model.recs and model.recs[r]["type"] in ("accept", "challenge")
                      and model.recs[r]["actor"] in b.cfg["accept_by"])
    if not added or verdicts != sorted(added):
        return None
    out = []
    if pr.get("head_repo") != b.cfg["repository"]:
        out.append(("VERDICTS_FORK", f"#{pr['number']}'s head is a branch of {str(pr.get('head_repo'))[:60]!r}, not "
                    f"{b.cfg['repository']}: a pull request of verdicts only is the acceptor's own branch"))
    if not str(pr.get("branch") or "").startswith(VERDICT_BRANCH):
        out.append(("VERDICTS_BRANCH", f"#{pr['number']}'s branch {str(pr.get('branch'))[:60]!r} is not under "
                    f"{VERDICT_BRANCH}"))
    held = {e[4][len(STORE) + 8:-5] for e in entries(root, b.commit, STORE + "records")}
    old = [v for v in verdicts if v in held]
    if old:
        out.append(("VERDICT_NOT_NEW", f"{len(old)} verdict(s) the base holds already: " + ", ".join(v[:12] for v in old[:8])))
    due = _due(root, b)
    late = [v for v in verdicts if _closure_of(model.recs[v]) not in due.get(model.recs[v]["actor"], set())]
    if late:
        out.append(("VERDICT_NOT_DUE", f"{len(late)} verdict(s) on a closure item the base's acceptance_due does not "
                    "name for its actor: " + ", ".join(v[:12] for v in late[:8])))
    loose = uncited(model, added, blobs)
    if loose:
        out.append(("TAIL_BLOB_UNCITED", f"{len(loose)} blob(s) cited by no verdict: " + ", ".join(o[:12] for o in loose[:8])))
    first = model.recs[verdicts[0]]
    a.facts.update(verdicts=verdicts, x=mb)
    a.verdict = True
    a.accept = (first["actor"], verdicts[0], _closure_of(first)[0], mb)
    return out


VERDICT_BRANCH = "codex/verdicts/"


def _closure_of(rec):
    """(transition, item) an accept or a challenge concerns."""
    b = rec["body"]
    return b.get("transition", b.get("target")), b.get("item")


def _due(root, b):
    """{actor: {(closure, item)}} the base's tools/roadmap.py acceptance_due names for each actor of the base's
    accept_by, read from the base's store and .warrant/roadmap.json under the base's pins."""
    import roadmap as RM                      # tools/roadmap.py, beside claimslib (review.py puts tools/ first)
    snap, problems = store_at(root, b.commit)
    doc = files_at(root, b.commit, [".warrant/roadmap.json"]).get(".warrant/roadmap.json")
    if problems or doc is None:
        return {}
    try:
        m = RM.Model(snap, b.trust, RM.check_config(json.loads(doc)), b.roles)
    except (RM.Refused, ValueError):
        return {}
    return {actor: {(d["closure"], d["item"]) for d in RM.acceptance_due(m, actor)} for actor in b.cfg["accept_by"]}


# ---------------------------------------------------------------- formats

def line(a):
    n = a.pr["number"]
    if a.eligible and a.facts.get("verdicts"):
        return f"#{n} {a.pr['head'][:12]}: ELIGIBLE (verdicts only, by {a.accept[0]}, from {a.accept[3][:12]})"
    if a.eligible:
        return f"#{n} {a.pr['head'][:12]}: ELIGIBLE (accepted by {a.accept[0]} at {a.accept[3][:12]})"
    return f"#{n} {a.pr['head'][:12]}: " + ("DUE FOR REVIEW; " if a.due else "") + "refused " + ", ".join(a.codes())


def as_json(a):
    return {"pr": a.pr["number"], "head": a.pr["head"], "branch": a.pr.get("branch"), "title": a.pr.get("title"),
            "head_repo": a.pr.get("head_repo"),
            "base": a.base, "eligible": a.eligible, "due": a.due,
            "reasons": [list(r) for r in a.reasons], "not_due": [list(r) for r in a.not_due],
            "accept": list(a.accept) if a.accept else None, "facts": a.facts}


def summary_markdown(assessments, merged=None, base=None):
    out = ["## merge-on-acceptance", "", f"Base `{base or (assessments[0].base if assessments else '?')}`.", ""]
    if not assessments:
        out.append("No open pull request into the base branch.")
    for a in assessments:
        n = a.pr["number"]
        if a.eligible and a.facts.get("verdicts"):
            out.append(f"- **#{n}** head `{a.pr['head'][:12]}`: ELIGIBLE: verdicts only, {len(a.facts['verdicts'])} record(s) "
                       f"by {a.accept[0]} from `{a.accept[3][:12]}`: " + ", ".join(f"`{v[:12]}`" for v in a.facts["verdicts"]))
        elif a.eligible:
            actor, aid, tid, x = a.accept
            out.append(f"- **#{n}** head `{a.pr['head'][:12]}`: ELIGIBLE: accept `{(aid or '?')[:12]}` by {actor} of "
                       f"closure `{tid[:12]}` at `{x[:12]}`")
        else:
            out.append(f"- **#{n}** head `{a.pr['head'][:12]}`: refused")
            out += [f"  - `{c}` {d}" for c, d in a.reasons]
    if merged:
        out += ["", f"Merged: {merged}"]
    return "\n".join(out) + "\n"
