"""The pull request review loop as records (schemas pr-head@1 and finding@1).

A pull request is a pr-head@1 lineage: its root (state `open`: repository, pr, title, serves) and one `head`
version per commit the author asks to have reviewed (commit, tree; guard: an attest `accept` by a
pr/acceptor). The reviewer accepts a head version (an attest) or files findings against it (finding@1
challenges; a finding may carry a test: {file, case, patch}, a new file under tests/). The review replay
checker runs each finding's test at each later head and attests the result on the finding
({verdict: reproduces | does_not_reproduce | no_result | does_not_apply, on: head version, commit, tree}).
A merge is a Git act, observed by an attest {verdict: merged, merge, tip} on the head version merged.

    python3 -m warrant.review [--root DIR] due --base M [--json]           # the waker's: due for review
    python3 -m warrant.review [--root DIR] gate --base M [--merge] [--gate-var V] [--summary FILE] [--pr N ...]
    python3 -m warrant.review open --pr N --title T [--serves ID ...] --actor A --key SEED
    python3 -m warrant.review head --pr N [--commit SHA] [--answers ID ...] --actor A --key SEED
    python3 -m warrant.review merged --pr N --merge SHA --actor A --key SEED
    python3 -m warrant.review identity                                      # the replay checker's actor, code, env
    python3 -m warrant.review [--root DIR] replay --key -                   # the checker: run, attest, print ids
    python3 -m warrant.review verify --base M                               # CI: re-execute replays new since M
    python3 -m warrant.review view [--out FILE]

The commands run on the repository `--root` names, else the Git checkout around the current directory (warrant.repo):
its `.warrant/` (the name of the repository and its trust and profile are its `.warrant/v3.json`'s) and its Git data.

The checker is the actor `review-replayer`, one key bound once. Each replay names the code that ran (`code`, the
digest of the checker's whole import closure: this package's modules; a tools/ shim is outside it, so the checker
runs as `python3 -m warrant.review`)
and its environment (`env`). Whoever holds its seed can sign as it, so CI re-executes every replay new since the
base at the commit it names (`verify`), and refuses a different result or a `code` that is not that commit's."""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import gate as GT
from . import records as R
from . import shapes as S
from .repo import Failed, Repo, checker_problem, code_tree, dump, env_root, identity, inside, load_key, main

REPLAYER = "review-replayer"          # the replay checker's actor: one key, bound once; its code is in each attest
TEST_FILE = re.compile(r"[a-z0-9_]{1,80}_test\Z")
CASE = re.compile(r"[A-Za-z0-9_.-]{1,40}\Z")
RUN_SECONDS = 600
REPLAY_VERDICTS = ("reproduces", "does_not_reproduce", "no_result", "does_not_apply")


def lineage_of(rep, repository, n):
    found = [L for L, lin in rep["lineages"].items() if lin["schema"] == "pr-head@1"
             and rep["_recs"][L]["body"].get("pr") == n and rep["_recs"][L]["body"].get("repository") == repository]
    if len(found) != 1:
        raise Failed("REVIEW", f"{len(found)} pr-head@1 lineages of {repository}#{n} in the store")
    return found[0]


def git(root, *a):
    return GT.git(root, *a).decode().strip()


# ---------------------------------------------------------------- the replay checker

def finding_test(body):
    """(file, case, patch) of a finding's test, or None: a patch that adds one new file tests/<file>.py."""
    t = body.get("test")
    if not (isinstance(t, dict) and set(t) == {"file", "case", "patch"} and isinstance(t["file"], str)
            and TEST_FILE.match(t["file"]) and isinstance(t["case"], str) and CASE.match(t["case"]) and isinstance(t["patch"], str)):
        return None
    files = re.findall(r"^\+\+\+ (?:b/)?(\S+)", t["patch"], re.M)
    if files != [f"tests/{t['file']}.py"] or re.findall(r"^--- (?!/dev/null)", t["patch"], re.M):
        return None
    return t["file"], t["case"], t["patch"]


def run_test(root, file, case, patch):
    """The verdict of a finding's test in the checkout `root`: the patch applied, the file run once, removed."""
    try:                         # the patch on standard input: no file of it anywhere
        GT.git(root, "apply", "--check", "-", stdin=patch.encode())
    except subprocess.CalledProcessError:
        return "does_not_apply"
    GT.git(root, "apply", "-", stdin=patch.encode())
    try:
        r = subprocess.run([sys.executable, "-B", f"tests/{file}.py"], cwd=root, capture_output=True, text=True,
                           timeout=RUN_SECONDS, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        out = ""
    finally:
        (Path(root) / "tests" / f"{file}.py").unlink(missing_ok=True)
    lines = [x.split() for x in out.splitlines()]
    if any(x[:2] == ["FAIL", case] for x in lines):
        return "reproduces"
    if any(x[:2] == ["ok", case] for x in lines):
        return "does_not_reproduce"
    return "no_result"


def to_replay(rep, replayers):
    """[(finding, head version, (file, case, patch))]: each finding's test at each head version of its pull request
    from the one it targets on, that no replayer has observed yet."""
    recs = rep["_recs"]
    seen = {(recs[a]["body"]["target"], recs[a]["body"].get("on")) for a in recs
            if recs[a]["kind"] == "attest" and recs[a]["actor"] in replayers}
    return [x for x in replayable(rep) if x[:2] not in seen]


def replayable(rep):
    """[(finding, head version, (file, case, patch))]: each finding's test at each head version of its pull request
    from the one it targets on."""
    recs, out = rep["_recs"], []
    for c, r in sorted(recs.items()):
        if r["kind"] != "challenge" or r["schema"] != "finding@1" or finding_test(r["body"]) is None:
            continue
        t = r["body"]["target"]
        L = next((L for L, lin in rep["lineages"].items() if t in lin["path"]), None)
        if L is None:
            continue
        path = rep["lineages"][L]["path"]
        for h in path[path.index(t):]:
            if recs[h]["body"].get("state") == "head":
                out.append((c, h, finding_test(r["body"])))
    return out


def replay(repo, key):
    """Run every finding's test not yet replayed at the head version whose commit's code this checkout holds (its
    tree equals that commit's tree outside .warrant/), and attest each result as the checker, naming the code that
    ran (this tool's own, wherever --root points) and its environment."""
    me = identity(repo.root)
    trust, profile, _ = repo.config()
    if key.public not in trust["keys"].get(REPLAYER, []):
        raise Failed("SIGNER", f"the seed's key is not one .warrant/v3.json binds to {REPLAYER}")
    rep = repo.report()
    head = git(repo.root, "rev-parse", "HEAD")
    code = code_tree(repo.root, head)
    filed = []
    for c, h, (file, case, patch) in to_replay(rep, set(profile["roles"].get("replayer", [])) | {REPLAYER}):
        x = rep["_recs"][h]["body"].get("commit")
        try:
            if not S.hex_of(x, 40) or code_tree(repo.root, x) != code:
                continue                   # this checkout does not hold that head's code
        except subprocess.CalledProcessError:
            continue
        t0 = int(time.time())
        verdict = run_test(repo.root, file, case, patch)
        body = {"target": c, "verdict": verdict, "on": h, "commit": x, "tree": git(repo.root, "rev-parse", f"{x}^{{tree}}"),
                "test": f"{file}:{case}", "window": [t0, int(time.time())], **me}
        [i] = repo.file(REPLAYER, key, [R.record("attest", REPLAYER, 0, body, refs=[c, h])])
        filed.append(i)
        print(f"{i} {verdict} {c[:12]} on {h[:12]}", flush=True)
    return filed


def verify(repo, base):
    """Re-execute every signed replay attest that is new since commit `base`, at the commit it names, in a temporary
    worktree; refused (REPLAY_DIFFERS) when a result differs or its `code` is not the checker's code at that commit
    (CODE_DIFFERS), or when it is not one replay would run: its finding's test at a head version of the finding's pull
    request from the one it targets on, at that version's commit (REPLAY_NOT_DUE). A migrated replay rests on the
    migration and its replay (docs/V3.md §9), not on a re-execution here."""
    _, profile, _ = repo.config()
    replayers = set(profile["roles"].get("replayer", []))
    old, _ = GT.store_at(repo.root, base)
    rep = repo.report()
    recs, bad, n = rep["_recs"], [], 0
    due = {(c, h) for c, h, _ in replayable(rep)}
    for i, r in sorted(recs.items()):
        if r["kind"] != "attest" or r["actor"] not in replayers or i in old.lines or r["body"].get("verdict") not in REPLAY_VERDICTS \
                or rep["_basis"].get(i) != "SIGNED":
            continue
        f = recs.get(r["body"]["target"])
        test = finding_test(f["body"]) if f else None
        if test is None:
            bad.append(f"{i[:12]}: its finding has no test")
            continue
        n += 1
        wt = Path(repo.root) / "build" / f"verify-{os.getpid()}-{i[:12]}"      # the checkout's own scratch, ignored
        why = checker_problem(r["body"], repo.root)
        on = recs.get(r["body"].get("on")) or {"body": {}}
        if why is None and ((r["body"]["target"], r["body"].get("on")) not in due or r["body"].get("commit") != on["body"].get("commit")):
            why = f"REPLAY_NOT_DUE: no replay runs its finding at {str(r['body'].get('on'))[:12]} on {str(r['body'].get('commit'))[:12]}"
        if why:
            bad.append(f"{i[:12]}: {why}")
            continue
        git(repo.root, "worktree", "add", "--detach", "--quiet", str(wt), r["body"]["commit"])
        try:
            got = run_test(wt, *test)
        finally:
            git(repo.root, "worktree", "remove", "--force", str(wt))
        if got != r["body"]["verdict"]:
            bad.append(f"{i[:12]}: says {r['body']['verdict']}, re-executed {got}")
    if bad:
        raise Failed("REPLAY_DIFFERS", "; ".join(bad))
    return n



# ---------------------------------------------------------------- the view

def view(rep):
    recs = rep["_recs"]
    out = ["# Reviews", "", f"Generated from `.warrant/records.jsonl` (snapshot `{rep['snapshot'][:12]}`); a build artifact.", ""]
    for L, lin in sorted(((L, lin) for L, lin in rep["lineages"].items() if lin["schema"] == "pr-head@1"),
                         key=lambda x: -int(recs[x[0]]["body"].get("pr") or 0)):
        b = recs[L]["body"]
        out.append(f"## {b.get('repository')}#{b.get('pr')}: {b.get('title')}")
        out.append(f"State {lin['state']}, reliance {lin['reliance']}" + (", FORK" if lin["verdict"] == "FORK" else ""))
        for v in lin["versions"]:
            vb, g = recs[v]["body"], rep["versions"][v]
            if vb.get("state") != "head":
                continue
            out.append(f"- head `{v[:12]}` at `{str(vb.get('commit'))[:12]}`: {g['guard']}"
                       + (f", accepted by {', '.join(g['accepted_by'])}" if g["accepted_by"] else ""))
            for c, x in sorted(rep["challenges"].items()):
                if x["target"] == v:
                    fb = recs[c]["body"]
                    reps = "; ".join(f"{z[1]} on {str(z[0])[:12]}" for z in x["replays"])
                    out.append(f"  - finding `{c[:12]}` by {recs[c]['actor']} ({'counted' if x['counted'] else 'thesis'}"
                               f"{', stands' if x['stands'] else ''}): {str(fb.get('statement'))[:200]}" + (f" [{reps}]" if reps else ""))
            for a in sorted(recs):
                if recs[a]["kind"] == "attest" and recs[a]["body"].get("target") == v and recs[a]["body"].get("verdict") == "merged":
                    out.append(f"  - merged as `{str(recs[a]['body'].get('merge'))[:12]}` (observed by {recs[a]['actor']})")
        out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- commands

def run(argv=None):
    root, argv = env_root(list(sys.argv[1:] if argv is None else argv))
    ap = argparse.ArgumentParser(prog="warrant.review")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("due")
    g = sub.add_parser("gate")
    for p in (d, g):
        p.add_argument("--base", required=True)
        p.add_argument("--json", action="store_true")
        p.add_argument("--remote", default="origin")
    g.add_argument("--merge", action="store_true")
    g.add_argument("--gate-var", default="")
    g.add_argument("--summary")
    g.add_argument("--pr", type=int, action="append", default=[])
    o = sub.add_parser("open")
    o.add_argument("--title", required=True)
    o.add_argument("--serves", action="append", default=[])
    h = sub.add_parser("head")
    h.add_argument("--commit")
    h.add_argument("--answers", action="append", default=[])
    m = sub.add_parser("merged")
    m.add_argument("--merge", required=True)
    for p in (o, h, m):
        p.add_argument("--pr", type=int, required=True)
        p.add_argument("--actor", required=True)
        p.add_argument("--key", required=True)
    sub.add_parser("identity")
    r = sub.add_parser("replay")
    r.add_argument("--key", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--base", required=True)
    w = sub.add_parser("view")
    w.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "due":
        return GT.cmd_due(root, a.base, a.json, a.remote)
    if a.cmd == "gate":
        return GT.cmd_gate(root, a.base, a.merge, a.gate_var == "hold", a.summary, a.pr, a.remote, a.json)
    if a.cmd == "identity":
        dump({"actor": REPLAYER, **identity(root)})
        return 0
    repo = Repo(root)
    if a.cmd == "replay":
        replay(repo, load_key(a.key, root))
        return 0
    if a.cmd == "verify":
        print(f"replays new since {a.base[:12]}: {verify(repo, a.base)} re-executed, all equal")
        return 0
    rep = repo.report()
    if a.cmd == "view":
        text = view(rep)
        if a.out:
            out = inside(a.out, root)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)
        else:
            sys.stdout.write(text)
        return 0
    key = load_key(a.key, root)
    _, _, name = repo.config()
    if a.cmd == "open":
        rec = R.record("entity", a.actor, 0, {"state": "open", "repository": name, "pr": a.pr, "title": a.title,
                                              "serves": sorted(a.serves)}, "pr-head@1", refs=a.serves)
    else:
        L = lineage_of(rep, name, a.pr)
        leaf = rep["lineages"][L]["leaf"]
        if leaf is None:
            raise Failed("REVIEW", f"#{a.pr}'s heads fork")
        if a.cmd == "head":
            x = git(repo.root, "rev-parse", "--verify", f"{a.commit or 'HEAD'}^{{commit}}")
            body = {"state": "head", "commit": x, "tree": git(repo.root, "rev-parse", f"{x}^{{tree}}"), "answers": sorted(a.answers)}
            schema = rep["_recs"][rep["schemas"]["pr-head@1"]]["body"]
            rec = R.record("entity", a.actor, 0, body, "pr-head@1", lineage=leaf, refs=a.answers, guard=schema["states"]["head"])
        else:
            merge = git(repo.root, "rev-parse", "--verify", f"{a.merge}^{{commit}}")
            tip = git(repo.root, "rev-parse", f"{merge}^2")
            rec = R.record("attest", a.actor, 0, {"target": leaf, "verdict": "merged", "merge": merge, "tip": tip}, refs=[leaf])
    dump({"filed": repo.file(a.actor, key, [rec])})
    return 0


def entry():
    """The console script `warrant-review`."""
    return main(run)


if __name__ == "__main__":
    sys.exit(main(run))
