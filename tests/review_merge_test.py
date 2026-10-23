#!/usr/bin/env python3
"""Merges of pull requests reviewed as records (tools/claimslib/reviews.py): a merge observation, its report
from history, and merges without reviewer acceptance (V13-V16).

    python3 tests/review_merge_test.py
"""
from review_world import (BUGGY, C, FIXED, Fixture, R, RV, branch, merge)
from world import check, finish


# ---------------------------------------------------------------- merges

def merge_cases():
    f = Fixture()
    branch(f, "pr1")
    h1 = f.commit("change 1", {"calc.py": FIXED})
    f.ok("open", "--pr", "1", "--title", "Reviewed")
    f.ok("head", "--pr", "1", "--commit", h1)
    f.save()
    f.ok("accept", "--pr", "1", "--commit", h1, actor="codex")
    tip1 = f.save()
    m1 = merge(f, tip1)
    f.ok("merged", "--pr", "1", "--merge", m1)
    m = f.model()
    rep = m.reviews[1].merges[0][2]
    check("V13", rep["tip"] == tip1 and [x["commit"] for x in rep["accepted"]] == [h1] and rep["outside"] == []
          and not RV.merged_without_acceptance(rep) and m.rep["duties"][m.reviews[1].did]["disposition"] == "DISCHARGED",
          "a merge whose tip differs from the accepted head only in records and their views merged at that head", rep)
    after1 = f.save()

    branch(f, "pr2")
    h2 = f.commit("change 2", {"calc.py": FIXED + "# 2\n"})
    f.ok("open", "--pr", "2", "--title", "Unreviewed")
    f.ok("head", "--pr", "2", "--commit", h2)
    tip2 = f.save()
    m2 = merge(f, tip2)
    f.ok("accept", "--pr", "2", "--commit", h2, actor="codex")       # after the merge: not in the tip's store
    f.ok("merged", "--pr", "2", "--merge", m2)
    m = f.model()
    rep2 = m.reviews[2].merges[0][2]
    view = RV.render_view(m)
    section = view[view.index("## Merged without reviewer acceptance"):view.index("## s0fractal")]
    check("V14", rep2["accepted"] == [] and rep2["outside"] is None and RV.merged_without_acceptance(rep2)
          and "#2:" in section and "#1:" not in section and m.rep["duties"][m.reviews[2].did]["disposition"] == "DISCHARGED",
          "a pull request merged with no head accepted in the tip's store is shown as merged without reviewer "
          "acceptance, even once an acceptance is filed after the merge", section)
    f.save()

    branch(f, "pr3")
    h3 = f.commit("change 3", {"calc.py": FIXED + "# 3\n"})
    f.ok("open", "--pr", "3", "--title", "Changed after acceptance")
    f.ok("head", "--pr", "3", "--commit", h3)
    f.save()
    f.ok("accept", "--pr", "3", "--commit", h3, actor="codex")
    f.save()
    tip3 = f.commit("after acceptance", {"calc.py": BUGGY})
    m3 = merge(f, tip3)
    f.ok("merged", "--pr", "3", "--merge", m3)
    rep3 = f.model().reviews[3].merges[0][2]
    late = f.code("merged", "--pr", "3", "--merge", m3)
    no_merge = f.code("merged", "--pr", "1", "--merge", h1)
    check("V15", rep3["outside"] == ["calc.py"] and RV.merged_without_acceptance(rep3)
          and [x["commit"] for x in rep3["accepted"]] == [h3] and late == ("REVIEW_MERGE_TWICE", True)
          and no_merge[1] and no_merge[0] in ("REVIEW_MERGE_TWICE", "REVIEW_MERGE_SHAPE"),
          "a tip that changes code after the accepted head merged without reviewer acceptance; a merge is observed once",
          (rep3, late, no_merge))
    f.save()
    good = f.problems(after1)

    # The report is re-derived from history for observations new since the base.
    m = f.model()
    oid, r, rep = m.reviews[3].merges[0]
    probe = m.snap.json_blob(r["body"]["probe"])
    (f.dir / ".warrant" / "store" / "records" / f"{oid}.json").unlink()
    lie = dict(rep, outside=[])
    body = R.observation(RV.merge_target(m.cfg, 3), C.digest(C.canon(probe)), r["body"]["window"],
                         r["body"]["result"], [C.digest(C.canon(lie))])
    f.put("claude", "observation", body, [probe, lie])
    f.ok("project")
    bad = f.problems(after1)
    check("V16", good == [] and bad == ["REVIEW_MERGE_REPORT"],
          "check --base re-derives a new merge observation's report from history and refuses a report that hides "
          "the paths changed after acceptance", (good, bad))
    f.close()


def main():
    for part in (merge_cases,):
        try:
            part()
        except Exception as e:      # noqa: BLE001 -- a part that raises fails its cases, the others still run
            import traceback
            traceback.print_exc()
            check(f"RAISED-{part.__name__}", False, "ran to its end", f"{type(e).__name__}: {e}")
    return finish("REVIEW_MERGE_TEST")


if __name__ == "__main__":
    raise SystemExit(main())
