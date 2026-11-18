"""R-UNION-ON-FORGE (obligation c01ef100, docs/V3.md §12): how often GitHub's merge, which runs no union driver, would
have stopped on .warrant/records.jsonl.

    python3 experiments/union-on-forge/measure.py --at COMMIT [--since 2026-10-16T00:00:00Z] [--until 2026-11-16T23:59:59Z] [--json]

A pull request merges on GitHub only when its head merges cleanly with the base there, union driver or not; a head
that would conflict is first brought up to date by merging the base into the branch, locally, where .gitattributes'
`merge=union` resolves records.jsonl. So the cost the driver hides is in those merges of the base into a branch.

The population (Codex e65ebaba): a two-parent commit in the window, reachable from COMMIT, not on its first-parent
line, whose second parent IS on that first-parent line: the base, as it was, merged into a branch. A merge of one
branch into another (its second parent off the first-parent line) is counted apart, never as a base update. Each update
is merged again in a temporary bare clone whose info/attributes sets `merge=text` for the three union paths (the forge),
and again with `merge=union` (a local merge): a conflict in the first in .warrant/records.jsonl is one the forge would
have refused; a path still conflicting in the second needed hands whatever the driver. Each conflict is attributed by
its commit: the gate's carry (github-actions[bot] as author, GitHub as committer, the message `records only
(warrant-gate)`) or a local merge; and to the pull request whose merge on the first-parent line first holds it, so
events and distinct pull requests are told apart. History is pinned (--at) and the bounds are timestamps, so a rerun
reads the same commits. It reads Git objects only and runs nothing of the repository's."""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

UNION = (".warrant/records.jsonl", "tests/mutants.py", "CHANGELOG.md")
RECORDS = ".warrant/records.jsonl"
CARRY = "records only (warrant-gate)"
PR = re.compile(r"Merge pull request #(\d+)")


def git(cwd, *a, ok=(0,)):
    p = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    if p.returncode not in ok:
        raise SystemExit(f"git {' '.join(a)}: {p.stderr.strip()}")
    return p


def conflicts(bare, ours, theirs):
    p = git(bare, "merge-tree", "--write-tree", "--name-only", ours, theirs, ok=(0, 1))
    return [] if p.returncode == 0 else sorted({x for x in p.stdout.splitlines()[1:] if x and not x.startswith(("Auto-merging", "CONFLICT"))})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", required=True, help="the commit of master the history is read from (pinned)")
    ap.add_argument("--since", default="2026-10-16T00:00:00Z")
    ap.add_argument("--until", default="2026-11-16T23:59:59Z")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = Path(git(".", "rev-parse", "--show-toplevel").stdout.strip())
    at = git(root, "rev-parse", "--verify", "--end-of-options", f"{a.at}^{{commit}}").stdout.strip()
    first = git(root, "rev-list", "--first-parent", at).stdout.split()
    on_first = set(first)
    window = ["--since", a.since, "--until", a.until]
    pr_merges = git(root, "rev-list", "--first-parent", "--merges", *window, at).stdout.split()
    side = [c for c in git(root, "rev-list", "--merges", *window, at).stdout.split() if c not in on_first]
    # each commit off the first-parent line, to the first master merge that brought it in (its pull request)
    brought = {}
    for m in reversed([c for c in first if len(git(root, "rev-list", "--parents", "-n", "1", c).stdout.split()) == 3]):
        p1, p2 = git(root, "rev-list", "--parents", "-n", "1", m).stdout.split()[1:]
        n = PR.search(git(root, "log", "-1", "--format=%s", m).stdout)
        for c in git(root, "rev-list", f"{p1}..{p2}").stdout.split():
            brought.setdefault(c, f"#{n.group(1)}" if n else m[:12])
    rows, branch_into_branch = [], 0
    with tempfile.TemporaryDirectory() as d:
        bare = {}
        for mode in ("text", "union"):
            b = Path(d) / f"{mode}.git"
            git(root, "clone", "--quiet", "--bare", "--no-local", str(root), str(b))
            (b / "info").mkdir(exist_ok=True)
            (b / "info" / "attributes").write_text("".join(f"{p} merge={mode}\n" for p in UNION))
            bare[mode] = b
        for c in side:
            parents = git(root, "rev-list", "--parents", "-n", "1", c).stdout.split()[1:]
            if len(parents) != 2:
                continue
            if parents[1] not in on_first:
                branch_into_branch += 1             # a branch merged into a branch: not an update from the base
                continue
            forge = conflicts(bare["text"], *parents)
            if not forge:
                rows.append({"commit": c, "conflicts": []})
                continue
            who = git(root, "log", "-1", "--format=%an%x00%cn%x00%s", c).stdout.strip().split("\0")
            gate = who[0] == "github-actions[bot]" and who[1] == "GitHub" and CARRY in who[2]
            rows.append({"commit": c, "conflicts": forge, "by": "gate" if gate else "local",
                         "with_union": conflicts(bare["union"], *parents), "pull_request": brought.get(c)})
    rec = [r for r in rows if RECORDS in r["conflicts"]]
    out = {"at": at, "window": [a.since, a.until], "pull_request_merges": len(pr_merges),
           "side_merges": len(side), "branch_into_branch_merges": branch_into_branch,
           "base_into_branch_merges": len(rows),
           "with_records_conflict": len(rec), "records_conflict_only": sum(1 for r in rec if r["conflicts"] == [RECORDS]),
           "records_conflicts_by": dict(Counter(r["by"] for r in rec)),
           "records_conflicts_distinct_pull_requests": len({r["pull_request"] for r in rec}),
           "records_conflicts_needing_hands_with_union": [r["commit"] for r in rec if r["with_union"]],
           "conflicts_by_path": dict(Counter(f for r in rows for f in r["conflicts"]).most_common()),
           "records_conflicts": [{k: r[k] for k in ("commit", "by", "pull_request", "conflicts", "with_union")} for r in rec]}
    if a.json:
        json.dump(out, sys.stdout, indent=1)
        print()
    else:
        print(f"at {at[:12]}, {a.since}..{a.until}: {out['pull_request_merges']} pull request merges; "
              f"{out['base_into_branch_merges']} merges of the base into a branch ({branch_into_branch} branch-into-branch "
              f"merges apart); {len(rec)} conflicting in {RECORDS} without the union driver "
              f"({out['records_conflict_only']} in it alone), {out['records_conflicts_by']}, "
              f"{out['records_conflicts_distinct_pull_requests']} distinct pull requests, "
              f"{len(out['records_conflicts_needing_hands_with_union'])} still conflicting elsewhere with union")
        for f, n in out["conflicts_by_path"].items():
            print(f"  {n:4} {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
