#!/usr/bin/env python3
"""The refusals of `tools/review.py check` (tools/claimslib/reviews.py) on review records filed by hand, as an
agent through MCP could: REVIEWS.md a build artifact, review duty terms and forks, head forks, unknown answers,
heads new since the base against history (V17-V19, V21-V23).

    python3 tests/review_check_test.py
"""
from review_world import C, FIXED, R, REPO, RV, head_of, started
from world import check, finish


# ---------------------------------------------------------------- refusals of check

def check_cases():
    f = started()
    clean = f.problems()
    f.ok("project")
    built = f.dir / "build" / "views" / "REVIEWS.md"
    view = built.read_bytes() if built.is_file() else None
    at_root = (f.dir / "REVIEWS.md").exists()
    built.parent.mkdir(parents=True, exist_ok=True)       # total: a mutant that writes elsewhere fails on the check
    built.write_bytes(b"edited by hand\r\n")
    edited = f.problems()
    built.unlink()
    missing = f.problems()
    check("V17", clean == [] and view == RV.render_view(f.model()).encode() and not at_root and edited == missing == [],
          "REVIEWS.md is a build artifact (G11): project writes build/views/REVIEWS.md and nothing at the root; check "
          "reads no view, so one edited or missing refuses nothing", (clean, at_root, edited, missing))

    f.put("stranger", "duty", R.duty("stranger", f"{REPO}#5 is fit to merge: Self-accepted", ["s0fractal"], {"attest": {}},
                                     accept_by=["codex", "stranger"]))
    f.put("claude", "duty", R.duty("claude", f"{REPO}#1 is fit to merge: Twice", ["s0fractal"], {"attest": {}},
                                   accept_by=["codex"]), at=f.at() + 1)       # later than the first: positions tie by id
    m = f.model()
    codes = [c for c, _ in m.problems]
    opened = f.code("open", "--pr", "1", "--title", "Again")
    check("V18", codes.count("REVIEW_TERMS") == 1 and codes.count("REVIEW_DUTY_FORK") == 1 and 5 not in m.reviews
          and m.reviews[1].did == f.duty and opened == ("REVIEW_DUTY_EXISTS", True),
          "a review duty has exactly the configured terms, and a pull request has one", codes)
    f.close()

    f = started()
    m = f.model()
    h = head_of(m, 1, 1)
    h2 = f.commit("more", {"calc.py": FIXED})
    tree2 = f.git("rev-parse", f"{h2}^{{tree}}")
    for i in range(2):
        doc = {"schema": RV.HEAD, "duty": f.duty, "pr": 1, "commit": h2, "tree": tree2, "previous": h.tid, "answers": []}
        hh = C.digest(C.canon(doc))
        f.put("claude", "transition", R.transition("ATTESTED", [hh], closes=[R.item(f.duty, "discharge", [hh])],
                                                   established=[f"fork {i}"], subject=h2), [doc])
    codes = [c for c, _ in f.model().problems]
    refused = f.code("head", "--pr", "1", "--commit", f.start)
    g = started()
    h = head_of(g.model(), 1, 1)
    h3 = g.commit("theirs", {"calc.py": FIXED})
    doc = {"schema": RV.HEAD, "duty": g.duty, "pr": 1, "commit": h3, "tree": g.git("rev-parse", f"{h3}^{{tree}}"),
           "previous": h.tid, "answers": []}
    hh = C.digest(C.canon(doc))
    g.put("codex", "transition", R.transition("ATTESTED", [hh], closes=[R.item(g.duty, "discharge", [hh])],
                                              established=["a reviewer's head"], subject=h3), [doc])
    m = g.model()
    filer = ([c for c, _ in m.problems], len(m.reviews[1].heads))
    g.close()
    check("V19", "REVIEW_HEAD_FORK" in codes and refused == ("REVIEW_HEAD_FORK", True)
          and filer == (["REVIEW_HEAD_FILER"], 1),
          "two heads naming the same previous are a fork: refused by check, and the tool files no next head; a "
          "closure by anyone but the author is no head", (codes, filer))
    f.close()

    f = started()
    m = f.model()
    h = head_of(m, 1, 1)
    h2 = f.commit("more", {"calc.py": FIXED})
    fake = "f" * 64
    tool = f.code("answer", "--pr", "1", "--commit", h2, "--finding", fake)
    tree2 = f.git("rev-parse", f"{h2}^{{tree}}")
    doc = {"schema": RV.HEAD, "duty": f.duty, "pr": 1, "commit": h2, "tree": tree2, "previous": h.tid, "answers": [fake]}
    hh = C.digest(C.canon(doc))
    f.put("claude", "transition", R.transition("ATTESTED", [hh], closes=[R.item(f.duty, "discharge", [hh])],
                                               established=["answers nothing"], subject=h2), [doc])
    codes = [c for c, _ in f.model().problems]
    check("V21", tool == ("REVIEW_ANSWER_UNKNOWN", True) and codes == ["REVIEW_ANSWER_UNKNOWN"],
          "a head answers only findings against earlier heads of its pull request", (tool, codes))
    f.close()


def commit_cases():
    f = started()
    f.git("checkout", "-q", "-b", "elsewhere", f.start)
    other = f.commit("elsewhere", {"calc.py": "# another line of history\n"})
    f.git("checkout", "-q", "master")
    tool = f.code("head", "--pr", "1", "--commit", other)
    m = f.model()
    h = head_of(m, 1, 1)
    tree = f.git("rev-parse", f"{other}^{{tree}}")

    def hand(commit, tree, what):
        doc = {"schema": RV.HEAD, "duty": f.duty, "pr": 1, "commit": commit, "tree": tree, "previous": h.tid, "answers": []}
        hh = C.digest(C.canon(doc))
        return f.put("claude", "transition", R.transition("ATTESTED", [hh], closes=[R.item(f.duty, "discharge", [hh])],
                                                          established=[what], subject=commit), [doc])
    base = f.save()
    hand(other, tree, "not an ancestor")
    f.ok("project")
    off = f.problems(base)
    lexical = f.problems()
    check("V22", tool == ("REVIEW_COMMIT_NOT_ANCESTOR", True) and off == ["REVIEW_COMMIT_NOT_ANCESTOR"] and lexical == [],
          "a head new since the base is an ancestor of HEAD: its closure is committed on top of it", (tool, off))
    f.close()

    f = started()
    m = f.model()
    h = head_of(m, 1, 1)
    base = f.save()
    h2 = f.commit("more", {"calc.py": FIXED})
    wrong = f.git("rev-parse", f"{f.start}^{{tree}}")
    doc = {"schema": RV.HEAD, "duty": f.duty, "pr": 1, "commit": h2, "tree": wrong, "previous": h.tid, "answers": []}
    hh = C.digest(C.canon(doc))
    f.put("claude", "transition", R.transition("ATTESTED", [hh], closes=[R.item(f.duty, "discharge", [hh])],
                                               established=["another tree"], subject=h2), [doc])
    f.ok("project")
    check("V23", f.problems(base) == ["REVIEW_COMMIT_NAME"] and f.problems() == [],
          "a head new since the base names its commit's own tree", f.problems(base))
    f.close()


def main():
    for part in (check_cases, commit_cases):
        try:
            part()
        except Exception as e:      # noqa: BLE001 -- a part that raises fails its cases, the others still run
            import traceback
            traceback.print_exc()
            check(f"RAISED-{part.__name__}", False, "ran to its end", f"{type(e).__name__}: {e}")
    return finish("REVIEW_CHECK_TEST")


if __name__ == "__main__":
    raise SystemExit(main())
