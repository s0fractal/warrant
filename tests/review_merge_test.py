#!/usr/bin/env python3
"""Merges of pull requests reviewed as records (tools/claimslib/reviews.py): a merge observation, its report
from history, and merges without reviewer acceptance (V13-V16); the merge's own tree is review_integration_test.

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
    filed = f.run("merged", "--pr", "1", "--merge", m1)[0]
    m = f.model()
    rep = m.reviews[1].merges[0][2] if m.reviews[1].merges else {}
    check("V13", filed == 0 and rep.get("tip") == tip1 and [x["commit"] for x in rep["accepted"]] == [h1] and rep["outside"] == []
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
          and RV.merge_state(rep3) == RV.TIP_CHANGED
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


def auto_cases():
    """`merged --due` files the merge observations Git's history shows; `head` refuses a head whose store lacks
    one (#181-#193 had none until #195 backfilled them by hand)."""
    f = Fixture()
    branch(f, "pr1")
    h1 = f.commit("change 1", {"calc.py": FIXED})
    f.ok("open", "--pr", "1", "--title", "One")
    f.ok("head", "--pr", "1", "--commit", h1)
    f.save()
    f.ok("accept", "--pr", "1", "--commit", h1, actor="codex")
    tip1 = f.save()
    # #2's branch takes #1's commits before #1 merges, under another number's subject: not #1's merge
    f.git("checkout", "-q", "-b", "pr2", "master")
    f.git("merge", "-q", "--no-ff", "-m", "Merge pull request #10 from s0fractal/pr1", tip1)
    h2 = f.commit("change 2", {"calc.py": FIXED + "# 2\n"})
    m1 = merge(f, tip1, "Merge pull request #1 from s0fractal/pr1")
    f.git("checkout", "-q", "-b", "elsewhere", f.start)    # #2's number on a merge that holds none of its heads
    stray = f.commit("unrelated", {"other.txt": "x\n"})
    merge(f, stray, "Merge pull request #2 from someone/elsewhere")
    f.git("checkout", "-q", "pr2")
    f.ok("open", "--pr", "2", "--title", "Two")
    head2 = f.run("head", "--pr", "2", "--commit", h2)[0]      # its history holds #1's commits, not #1's merge
    tip2 = f.save()
    m2 = merge(f, tip2, "Merge pull request #2 (accepted by codex)")
    branch(f, "pr3")
    h3 = f.commit("change 3", {"calc.py": FIXED + "# 3\n"})
    f.ok("open", "--pr", "3", "--title", "Three")
    f.save()
    refused = f.code("head", "--pr", "3", "--commit", h3)

    # V34: a head whose own commit's store lacks a merge observation of a pull request merged in its history
    check("V34", refused == ("REVIEW_MERGE_UNOBSERVED", True),
          "a head is not filed while its commit's store lacks the merge observation of a pull request merged "
          "into its history", refused)

    rc, out, err = f.run("merged", "--due")
    m = f.model()
    got = {n: rv.merges[0][2]["merge"] if rv.merges else None for n, rv in sorted(m.reviews.items())}
    by = {r["actor"] for n in (1, 2) for _, r, _ in m.reviews[n].merges}
    rc2, out2, _ = f.run("merged", "--due")
    uncommitted = f.code("head", "--pr", "3", "--commit", h3)     # observed, but not in h3's own store
    h3b = f.save()
    rc3, _, err3 = f.run("head", "--pr", "3", "--commit", h3b)
    # V35: the merge whose GitHub subject names exactly the pull request and that holds its latest head, each
    # observed once, by the writer; then a head whose own commit holds them is filed
    check("V35", (head2, rc, got, by, rc2, out2.strip(), uncommitted, rc3)
          == (0, 0, {1: m1, 2: m2, 3: None}, {"claude"}, 0, "", ("REVIEW_MERGE_UNOBSERVED", True), 0),
          "merged --due observes each pull request merged into HEAD's history, at its own merge commit, once",
          (head2, rc, err, got, by, rc2, out2, uncommitted, rc3, err3))
    f.close()

    # V36: two merges that both say they merged #1 and hold its head: nothing is guessed or filed
    f = Fixture()
    branch(f, "pr1")
    h1 = f.commit("change 1", {"calc.py": FIXED})
    f.ok("open", "--pr", "1", "--title", "One")
    f.ok("head", "--pr", "1", "--commit", h1)
    tip1 = f.save()
    f.git("checkout", "-q", "-b", "copy", "master")
    f.git("merge", "-q", "--no-ff", "-m", "Merge pull request #1 from s0fractal/copy", tip1)
    copy = f.git("rev-parse", "HEAD")
    m1 = merge(f, tip1, "Merge pull request #1 from s0fractal/pr1")
    f.git("merge", "-q", "--no-ff", "-m", "Merge branch 'copy'", copy)
    other = f.git("rev-parse", "HEAD")      # holds #1's head in what it merged, under no #1 subject
    twice = f.code("merged", "--due")
    # Codex finding on #197 head 3 (3789dbb): the explicit form accepted a merge outside the candidates
    outside = f.code("merged", "--pr", "1", "--merge", other)
    named = f.run("merged", "--pr", "1", "--merge", m1)[0]
    check("V36", (twice, outside, named) == (("REVIEW_MERGE_AMBIGUOUS", True), ("REVIEW_MERGE_NOT_THE_PR", True), 0),
          "an ambiguous merge is refused with nothing filed; the explicit merged --pr --merge observes one of its "
          "candidates, and no other merge", (twice, outside, named))
    f.close()


def binding_cases():
    """V37 (Codex findings on #197, observed at bb0fb07 and c21ff5f: `merged --pr 1 --merge` naming an unrelated
    merge, then another pull request's merge that had imported #1's head, was filed, and that observation let the
    next head pass while #1's own merge stayed unobserved; expected: refused)."""
    f = Fixture()
    branch(f, "unrelated")
    tip0 = f.commit("unrelated change", {"unrelated.txt": "x\n"})
    unrelated = merge(f, tip0, "Merge pull request #900 from fixture/unrelated")
    branch(f, "pr5")                    # merged under a subject Git's history does not name: only the operator does
    h5 = f.commit("change 5", {"five.txt": "5\n"})
    f.ok("open", "--pr", "5", "--title", "Five")
    f.ok("head", "--pr", "5", "--commit", h5)
    m5 = merge(f, f.save(), "Merge branch 'pr5'")
    branch(f, "pr1")
    h1 = f.commit("change 1", {"calc.py": FIXED})
    f.ok("open", "--pr", "1", "--title", "One")
    f.ok("head", "--pr", "1", "--commit", h1)
    tip1 = f.save()
    # #3's branch imports #1's reviewed head and merges first; #1 merges after it, with a later commit, so its
    # own merge holds that head in both parents (Codex's second finding on #197, at c21ff5f: an observation of
    # #3's merge stood for #1's)
    f.git("checkout", "-q", "-b", "pr3", "master")
    f.git("merge", "-q", "--no-ff", "-m", "Merge branch 'pr1' into pr3", tip1)
    m3 = merge(f, f.git("rev-parse", "pr3"), "Merge pull request #3 from fixture/pr3")
    f.git("checkout", "-q", "pr1")
    later = f.commit("after review", {"notes.txt": "n\n"})
    m1 = merge(f, later, "Merge pull request #1 from fixture/pr1")
    branch(f, "pr2")
    h2 = f.commit("change 2", {"other.txt": "y\n"})
    m2 = merge(f, h2, "Merge pull request #2 from fixture/pr2")      # holds #1's head through its first parent
    refused = [f.code("merged", "--pr", n, "--merge", x) for n, x in (("1", unrelated), ("1", m2), ("1", m3), ("5", unrelated))]
    named = f.run("merged", "--pr", "1", "--merge", m1)[0] + f.run("merged", "--pr", "5", "--merge", m5)[0]
    m = f.model()
    oid, r, rep = m.reviews[1].merges[0]
    probe = dict(m.snap.json_blob(r["body"]["probe"]), merge=unrelated)
    before = f.save()
    (f.dir / ".warrant" / "store" / "records" / f"{oid}.json").unlink()
    lie = dict(rep, merge=unrelated, tree=f.git("rev-parse", unrelated + "^{tree}"), base=f.git("rev-parse", unrelated + "^1"),
               tip=tip0, accepted=[], outside=None, integration=None)
    body = R.observation(RV.merge_target(m.cfg, 1), C.digest(C.canon(probe)), r["body"]["window"],
                         f"merged {unrelated} tip {tip0}", [C.digest(C.canon(lie))])
    f.put("claude", "observation", body, [probe, lie])
    f.ok("project")
    forged = f.model().reviews[1].merges[0][2]["merge"] == unrelated
    caught = f.problems(before)
    check("V37", (refused, named, forged, caught)
          == ([("REVIEW_MERGE_NOT_THE_PR", True)] * 4, 0, True, ["REVIEW_MERGE_REPORT"]),
          "a merge observation names the pull request's own merge: one of an unrelated merge, of a later one, or of "
          "another pull request's that imported its head is refused when filed and by check --base",
          (refused, named, forged, caught))
    f.close()


def main():
    for part in (merge_cases, auto_cases, binding_cases):
        try:
            part()
        except Exception as e:      # noqa: BLE001 -- a part that raises fails its cases, the others still run
            import traceback
            traceback.print_exc()
            check(f"RAISED-{part.__name__}", False, "ran to its end", f"{type(e).__name__}: {e}")
    return finish("REVIEW_MERGE_TEST")


if __name__ == "__main__":
    raise SystemExit(main())
