"""R-UNION-ON-FORGE (obligation c01ef100, docs/V3.md §12): how often GitHub's merge, which runs no union driver, would
have stopped on .warrant/records.jsonl.

    python3 experiments/union-on-forge/measure.py [--since 2026-10-16] [--until 2026-11-16] [--json]

A pull request merges on GitHub only when its head merges cleanly with the base there, union driver or not; a head
that would conflict is first brought up to date by merging the base into the branch, locally, where .gitattributes'
`merge=union` resolves records.jsonl. So the cost the driver hides is in those merges of the base into a branch. Each
one (a merge commit, not on master's first-parent line, whose second parent is a master commit) is merged again in a
temporary bare clone whose info/attributes sets `merge=text` for the three union paths: a conflict there in
.warrant/records.jsonl is one the forge would have refused. It reads Git objects only and runs nothing of the
repository's."""
import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

UNION = (".warrant/records.jsonl", "tests/mutants.py", "CHANGELOG.md")


def git(cwd, *a, ok=(0,)):
    p = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    if p.returncode not in ok:
        raise SystemExit(f"git {' '.join(a)}: {p.stderr.strip()}")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-16")
    ap.add_argument("--until", default="2026-11-16")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = Path(git(".", "rev-parse", "--show-toplevel").stdout.strip())
    master = git(root, "rev-parse", "origin/master").stdout.strip()
    on_master = set(git(root, "rev-list", master).stdout.split())
    first = set(git(root, "rev-list", "--first-parent", master).stdout.split())
    window = ["--since", a.since, "--until", a.until]
    pr_merges = git(root, "rev-list", "--first-parent", "--merges", *window, master).stdout.split()
    side = [c for c in git(root, "rev-list", "--merges", *window, master).stdout.split() if c not in first]
    rows = []
    with tempfile.TemporaryDirectory() as d:
        bare = Path(d) / "m.git"
        git(root, "clone", "--quiet", "--bare", "--no-local", str(root), str(bare))
        (bare / "info").mkdir(exist_ok=True)
        (bare / "info" / "attributes").write_text("".join(f"{p} merge=text\n" for p in UNION))
        for c in side:
            parents = git(bare, "rev-list", "--parents", "-n", "1", c).stdout.split()[1:]
            if len(parents) != 2 or parents[1] not in on_master:
                continue                        # not a merge of the base into a branch
            p = git(bare, "merge-tree", "--write-tree", "--name-only", parents[0], parents[1], ok=(0, 1))
            files = [] if p.returncode == 0 else [x for x in p.stdout.splitlines()[1:] if x and not x.startswith(("Auto-merging", "CONFLICT"))]
            rows.append({"commit": c, "conflicts": sorted(set(files))})
    by = Counter(f for r in rows for f in r["conflicts"])
    only_records = sum(1 for r in rows if r["conflicts"] == [".warrant/records.jsonl"])
    any_records = sum(1 for r in rows if ".warrant/records.jsonl" in r["conflicts"])
    out = {"window": [a.since, a.until], "pull_request_merges": len(pr_merges), "base_into_branch_merges": len(rows),
           "with_records_conflict": any_records, "records_conflict_only": only_records,
           "conflicts_by_path": dict(by.most_common()), "commits_with_records_conflict": [r["commit"] for r in rows if ".warrant/records.jsonl" in r["conflicts"]]}
    if a.json:
        json.dump(out, sys.stdout, indent=1)
        print()
    else:
        print(f"{out['pull_request_merges']} pull request merges, {out['base_into_branch_merges']} merges of the base into a branch, "
              f"{any_records} of them conflicting in .warrant/records.jsonl without the union driver ({only_records} in it alone)")
        for f, n in by.most_common():
            print(f"  {n:4} {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
