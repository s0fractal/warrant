#!/usr/bin/env python3
"""The merge commit's own tree (tools/claimslib/reviews.py, integration and merge_state; AMEND 1 of #181): code
a merge brings that neither the first parent nor the accepted head has is an unreviewed integration change;
an advanced base and a conflict resolved by one side are not (V30-V33).

    python3 tests/review_integration_test.py
"""
import subprocess

from review_world import BUGGY, FIXED, GIT, Fixture, RV, branch, merge
from world import check, finish


# ---------------------------------------------------------------- the merge's own tree (AMEND 1 of #181)

def reviewed(pr, files, base_files=None):
    """A fixture whose pull request #pr (branched from master) changes `files`, is accepted and pushed; master
    then gets `base_files` (an advanced base) and stays checked out. (fixture, accepted head, tip)."""
    f = Fixture()
    branch(f, f"pr{pr}")
    h = f.commit("the reviewed change", files)
    f.ok("open", "--pr", str(pr), "--title", "Reviewed")
    f.ok("head", "--pr", str(pr), "--commit", h)
    f.save()
    f.ok("accept", "--pr", str(pr), "--commit", h, actor="codex")
    tip = f.save()
    f.git("checkout", "-q", "master")
    if base_files:
        f.commit("the base moves on", base_files)
    return f, h, tip


def merging(f, tip):
    """`git merge --no-ff --no-commit tip` on master: conflicts leave the merge pending; True if any."""
    r = subprocess.run([*GIT, "-C", str(f.dir), "merge", "-q", "--no-ff", "--no-commit", tip], capture_output=True)
    return r.returncode != 0


def observed(f, pr, merge_commit):
    f.ok("merged", "--pr", str(pr), "--merge", merge_commit)
    f.ok("project")
    return f.model().reviews[pr].merges[0][2]


def integration_cases():
    # Codex's reproduction on c830c53: the accepted head fixed the bug, the merge resolution reinstates it.
    f, h, tip = reviewed(1, {"calc.py": FIXED})
    merging(f, tip)
    (f.dir / "calc.py").write_text(BUGGY)
    m = f.commit("merge resolution reinstates the bug")
    rep = observed(f, 1, m)
    view = (f.dir / "build" / "views" / "REVIEWS.md").read_text()
    unverified = dict(rep, integration=None)
    check("V30", rep["outside"] == [] and rep["integration"] == ["calc.py"]
          and RV.merge_state(rep) == RV.INTEGRATION_CHANGES and RV.merged_without_acceptance(rep)
          and (rep["merge"], rep["tree"], rep["base"]) == (m, f.git("rev-parse", f"{m}^{{tree}}"), f.git("rev-parse", f"{m}^1"))
          and "MERGED WITH UNREVIEWED INTEGRATION CHANGES" in view and f.problems(f.start) == []
          and RV.merge_state(unverified) == RV.INTEGRATION_UNVERIFIED and RV.merged_without_acceptance(unverified),
          "a merge whose own tree holds code that neither the first parent nor the accepted head has is merged with "
          "unreviewed integration changes, named by the merge's commit and tree; an integration Git cannot redo is "
          "unverified, never reviewed", rep)
    f.close()

    f, h, tip = reviewed(1, {"calc.py": FIXED})
    m0 = merge(f, tip)
    f.commit("amended merge", {"extra.py": "x = 1\n"})
    f.git("reset", "-q", "--soft", "HEAD~1")
    f.git("commit", "-q", "--amend", "--no-edit")
    m = f.git("rev-parse", "HEAD")
    rep = observed(f, 1, m)
    check("V31", m != m0 and rep["integration"] == ["extra.py"] and RV.merge_state(rep) == RV.INTEGRATION_CHANGES,
          "an amended merge commit that adds a file nobody reviewed is merged with unreviewed integration changes", rep)
    f.close()

    f, h, tip = reviewed(1, {"calc.py": FIXED}, base_files={"other.py": "y = 2\n"})
    m = merge(f, tip)
    rep = observed(f, 1, m)
    check("V32", rep["integration"] == [] and RV.merge_state(rep) == RV.REVIEWED and not RV.merged_without_acceptance(rep)
          and f.git("rev-parse", f"{m}^1") != f.start,
          "a normal merge onto a base that moved on with unrelated commits is merged at the accepted head", rep)
    f.close()

    states = []
    for keep in ("--theirs", "--ours", None):
        f, h, tip = reviewed(1, {"calc.py": FIXED}, base_files={"calc.py": "def add(a, b):\n    return b - a\n"})
        conflicted = merging(f, tip)
        if keep:
            f.git("checkout", keep, "--", "calc.py")
        else:
            (f.dir / "calc.py").write_text("def add(a, b):\n    return a * b\n")
        rep = observed(f, 1, f.commit("merge with a resolved conflict"))
        states.append((conflicted, rep["integration"], RV.merge_state(rep)))
        f.close()
    check("V33", states == [(True, [], RV.REVIEWED), (True, [], RV.REVIEWED),
                            (True, ["calc.py"], RV.INTEGRATION_CHANGES)],
          "a conflict resolved by keeping exactly one side (the accepted head's or the base's) adds nothing unreviewed; "
          "a resolution that is neither side is an integration change", states)


def main():
    for part in (integration_cases,):
        try:
            part()
        except Exception as e:      # noqa: BLE001 -- a part that raises fails its cases, the others still run
            import traceback
            traceback.print_exc()
            check(f"RAISED-{part.__name__}", False, "ran to its end", f"{type(e).__name__}: {e}")
    return finish("REVIEW_INTEGRATION_TEST")


if __name__ == "__main__":
    raise SystemExit(main())
