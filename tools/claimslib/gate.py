"""The merge gate and the review waker's reading of GitHub (tools/review.py gate, due).

`survey` lists the open pull requests into the base branch merge.json names, fetches each head as
Git data only (refs/warrant-gate/pull/<n>; nothing checked out, nothing of it run), reads its
checks, and assesses it (eligibility.assess) against the base commit. `gate` then merges, with a
merge commit, at most one eligible pull request: it reads the pull request and the base branch
again, gives GitHub the head it assessed (`sha`: GitHub refuses the merge when the head moved), reads
the merge commit back, and dispatches the required workflows on the base branch, since a merge made
with a workflow's GITHUB_TOKEN starts no push workflow. `due` is the waker's: the pull requests due
for review.

Every GitHub call goes through `gh api` (GH_TOKEN in a workflow, the operator's login on a
machine); every path is built from checked parts (an owner/name, a number, a full commit id, a
branch name, a workflow file name).
"""
import json
import subprocess
from pathlib import PurePosixPath

from . import eligibility as EL
from . import reviews as RV
from .base import Refused

REF = "refs/warrant-gate/pull/{n}"


class GitHub:
    """`gh api` for one repository. `run` is subprocess.run (a test passes its own)."""

    def __init__(self, repo, gh="gh", run=subprocess.run):
        if not RV.REPOSITORY.match(repo):
            raise Refused(f"{repo[:60]!r} is not owner/name", "GATE_INPUT")
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
        pages = self.api(f"pulls?state=open&base={_branch(base)}&per_page=100", pages=True)
        return [facts(p) for page in pages for p in page]

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
        if not EL.WORKFLOW.match(f".github/workflows/{name}"):
            raise Refused(f"{name!r} is not a workflow file name", "GATE_INPUT")
        return self.api(f"actions/workflows/{name}/dispatches", "POST", {"ref": _branch(branch)})


def _number(n):
    if type(n) is not int or n < 1:
        raise Refused(f"{n!r} is not a pull request number", "GATE_INPUT")
    return n


def _sha(s):
    if not RV.is_commit(s):
        raise Refused(f"{str(s)[:50]!r} is not a full commit id", "GATE_INPUT")
    return s


def _branch(b):
    if not (isinstance(b, str) and EL.BRANCH.match(b) and ".." not in b):
        raise Refused(f"{str(b)[:50]!r} is not a branch name", "GATE_INPUT")
    return b


def facts(p):
    """The facts of a pull request the predicate reads, from the API's object (the title is for the waker's
    prompt; the branch and the head's repository are read by the rule for a pull request of verdicts only)."""
    return {"number": p["number"], "state": p["state"], "draft": bool(p.get("draft")), "base": p["base"]["ref"],
            "head": p["head"]["sha"], "labels": sorted(x["name"] for x in p.get("labels", [])),
            "branch": p["head"].get("ref"), "title": p.get("title"),
            "head_repo": (p["head"].get("repo") or {}).get("full_name")}


def fetch(root, n, remote="origin"):
    """Fetch pull request `n`'s head into refs/warrant-gate/pull/<n> (Git data only) and return its id."""
    ref = REF.format(n=_number(n))
    subprocess.run(["git", "-C", str(root), "fetch", "--no-tags", "--quiet", remote, f"+refs/pull/{n}/head:{ref}"],
                   capture_output=True, check=True)
    return subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", ref], capture_output=True,
                          check=True).stdout.decode().strip()


def survey(root, b, gh, prs=None, hold=False, remote="origin"):
    """[Assessment] of the open pull requests into the base branch (or only the numbers in `prs`), each
    fetched as Git data and assessed against the base `b` (an eligibility.Base). Refused BASE_MOVED when
    the base branch on GitHub is no longer at that commit: what runs and what is read are one commit."""
    base = b.commit
    tip = gh.tip(b.gate["base"])
    if tip != base:
        raise Refused(f"{b.gate['base']} is at {tip[:12]} on GitHub, the base read here is {base[:12]}", "BASE_MOVED")
    out = []
    for pr in sorted(gh.pulls(b.gate["base"]), key=lambda p: p["number"]):
        if prs and pr["number"] not in prs:
            continue
        try:
            got = fetch(root, pr["number"], remote)
        except subprocess.CalledProcessError as e:
            got = f"unfetchable: {e.stderr.decode(errors='replace').strip()[:100]}"
        if got != pr["head"]:
            a = EL.Assessment(pr, base)
            a.shared.append(("HEAD_MOVED", f"#{pr['number']} reads {pr['head'][:12]} on GitHub and {got[:40]} fetched"))
            a.reasons += a.shared
        else:
            a = EL.assess(root, b, pr, gh.checks(pr["head"]), hold=hold)
        out.append(a)
    return out


def merge_one(b, a, gh):
    """Merge eligible Assessment `a` at the head it assessed, after reading the pull request and the
    base branch again: the pull request read again must still pass the predicate's own pull request rules
    (eligibility.pr_reasons: no hold label, open, not a draft, into the base branch) at the same head.
    Then dispatch the required workflows on the base branch. A dict of what happened, for the summary."""
    n, head, base = a.pr["number"], a.pr["head"], a.base
    now = gh.pull(n)
    changed = EL.pr_reasons(b, now)
    if now["head"] != head:
        changed.append(("HEAD_MOVED", f"#{n} is at {now['head'][:12]}, not the head assessed"))
    if changed:
        return {"pr": n, "merged": False, "why": "; ".join(f"{c}: {d}" for c, d in changed)}
    tip = gh.tip(b.gate["base"])
    if tip != base:
        return {"pr": n, "merged": False, "why": f"BASE_MOVED: {b.gate['base']} is at {tip[:12]}"}
    actor, aid, tid, x = a.accept
    title = f"Merge pull request #{n} (accepted by {actor})"
    message = (f"merge-on-acceptance: accept {aid} by {actor} of head closure {tid} at {x}; head {head}; "
               f"base {base}; required checks green at the head.")
    if a.facts.get("verdicts"):
        title = f"Merge pull request #{n} (verdicts by {actor})"
        message = (f"merge-on-acceptance: verdicts only, {', '.join(a.facts['verdicts'])}, from {x}; head {head}; "
                   f"base {base}; required checks green at the head.")
    try:
        res = gh.merge(n, head, title, message)
    except Refused as e:
        return {"pr": n, "merged": False, "why": f"GitHub refused the merge: {e}"}
    if res.get("merged") is not True or not RV.is_commit(res.get("sha")):
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


# ---------------------------------------------------------------- commands

def _write(path, text):
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def cmd_gate(rv, a):
    """review.py gate: assess every open pull request into the base branch; with --merge, merge the first
    eligible one. Exit 0 whether or not anything was eligible; 2 on a refusal of the run itself."""
    base = a.base
    b = EL.Base(rv.root, _sha(base))
    gh = GitHub(b.cfg["repository"])
    try:
        found = survey(rv.root, b, gh, set(a.pr or ()), hold=a.gate_var == "hold", remote=a.remote)
    except Refused as e:
        _write(a.summary, f"## merge-on-acceptance\n\nNothing assessed: `{e.code}` {e}\n")
        if e.code == "BASE_MOVED":          # a merge landed meanwhile: the run its CI starts reads the new base
            print(f"REFUSED {e.code} {e}")
            return 0
        raise
    merged = None
    if a.merge:
        first = next((x for x in found if x.eligible), None)
        merged = merge_one(b, first, gh) if first is not None else None
    text = EL.summary_markdown(found, describe(merged) if merged else None, base)
    _write(a.summary, text)
    for x in found:
        print(EL.line(x))
    if merged:
        print("MERGE " + describe(merged))
    if a.json:
        print(json.dumps({"base": base, "assessments": [EL.as_json(x) for x in found], "merge": merged}, indent=1))
    return 0


def cmd_due(rv, a):
    """review.py due: the pull requests due for review, one line each (or JSON); exit 0."""
    b = EL.Base(rv.root, _sha(a.base))
    found = survey(rv.root, b, GitHub(b.cfg["repository"]), remote=a.remote)
    due = [x for x in found if x.due]
    if a.json:
        print(json.dumps({"base": a.base, "due": [EL.as_json(x) for x in due],
                          "not_due": [EL.as_json(x) for x in found if not x.due]}, indent=1))
    else:
        for x in found:
            print(("DUE " if x.due else "not due ") + EL.line(x)
                  + ("" if x.due else " | " + ", ".join(c for c, _ in x.not_due)))
    return 0
