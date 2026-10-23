#!/usr/bin/env python3
"""The pull request review loop as records (tools/review.py, tools/claimslib/reviews.py): the loop open ->
head -> finding (reproduces) -> answer -> no longer reproduces -> accept, theses, forgeries, names,
superseded heads, acceptances, the interface (V01-V12, V20, V24, V25, V29).

Each case builds a fixture Git repository (tests/review_world.py) and drives the tool through its
command line in process. States are asserted on the model's data and the engine's report, refusals by
their code and by the store staying unchanged, never by wording, so a mutant is killed only when a rule
stops holding.

    python3 tests/reviews_test.py
"""
import json
import re
import shutil
import tempfile
import time
from pathlib import Path

from review_world import (BUGGY, C, FIXED, Fixture, R, REPO, ROOT, RR, RV, W, _write,
                          finding_test, head_of, reliance, started)
import claimslib                                  # noqa: E402  (tools/ is on the path: review_world)
from world import check, finish


# ---------------------------------------------------------------- the loop

def loop_cases():
    f = Fixture()
    h1 = f.commit("the change", {"calc.py": BUGGY + "\n# a change\n"})
    duty = f.ok("open", "--pr", "7", "--title", "Add numbers")
    m = f.model()
    d = m.recs[duty]["body"]
    check("V01", m.reviews[7].did == duty and d["holder"] == "claude" and d["owed_to"] == ["s0fractal"]
          and d["accept_by"] == ["codex"] and d["condition"] == {"attest": {}} and d["release_by"] == []
          and d["statement"] == f"{REPO}#7 is fit to merge: Add numbers" and m.rep["duties"][duty]["disposition"] == "OPEN",
          "open files the pull request's duty: held by its author, owed to and accepted by whom reviews.json names", d)

    t1 = f.ok("head", "--pr", "7", "--commit", h1)
    m = f.model()
    h = head_of(m, 7, 1)
    tree = f.git("rev-parse", f"{h1}^{{tree}}")
    check("V02", h.tid == t1 and (h.commit, h.tree, h.previous, h.answers) == (h1, tree, None, [])
          and m.recs[t1]["body"]["subject"] == h1 and h.item["act"] == "discharge" and h.verdict == "PENDING"
          and h.waiting == ["codex"] and m.recs[t1]["actor"] == "claude",
          "head files a closure of the duty naming the head's full commit and tree ids, awaiting the acceptor",
          (h.commit, h.verdict, h.waiting))
    f.save()

    cid = f.ok("finding", "--pr", "7", "--commit", h1, "--severity", "P2", "--what", "add subtracts",
               "--where", "calc.py:2", "--test", "finding_test", "--case", "F1",
               "--patch", str(_write(f.base / "f.diff", finding_test()["patch"])), actor="codex")
    m = f.model()
    fd = m.findings.get(cid)
    ch = m.rep["challenges"].get(cid, {})
    check("V03", fd is not None and fd.head.tid == t1 and ch.get("target") == t1 and ch.get("item") == 0
          and fd.blob["commit"] == h1 and fd.blob["severity"] == "P2" and fd.test["file"] == "finding_test"
          and RV.finding_class(fd) == "NOT_REPLAYED" and m.recs[cid]["actor"] == "codex",
          "finding files the reviewer's challenge of the current head's closure with a finding blob naming that head",
          fd and fd.blob)
    f.save()

    out = f.ok("replay")
    m = f.model()
    fd = m.findings[cid]
    oid = fd.observed.get(h1, (None,))[0]
    check("V04", fd.at(h1) == "FAIL" and RV.finding_class(fd) == "REPRODUCED" and oid is not None
          and m.recs[oid]["actor"] == RR.actor() and m.recs[oid]["type"] == "observation" and len(out.splitlines()) == 1,
          "the review replay checker observes the finding's case failing at its head: it reproduces", out)
    f.save()

    h2 = f.commit("fix", {"calc.py": FIXED + "\n# a change\n"})
    t2 = f.ok("answer", "--pr", "7", "--commit", h2, "--finding", cid)
    m = f.model()
    hh = head_of(m, 7, 2)
    check("V05", hh.tid == t2 and hh.previous == t1 and hh.answers == [cid] and m.findings[cid].answered_by is hh
          and hh.item["act"] == "discharge" and head_of(m, 7, 1).successor is hh,
          "answer files the next head's closure naming the previous head and the findings it answers", hh.blob)
    f.save()

    f.ok("replay")
    m = f.model()
    fd = m.findings[cid]
    view = RV.render_view(m)
    check("V06", fd.at(h1) == "FAIL" and fd.at(h2) == "PASS" and RV.finding_class(fd) == "REPRODUCED"
          and f"head 2 `{h2[:12]}`: DOES NOT REPRODUCE" in view and f"head 1 `{h1[:12]}`: REPRODUCES" in view,
          "replayed at the answering head, the finding no longer reproduces; the view shows both", fd.observed)
    f.save()

    f.ok("accept", "--pr", "7", "--commit", h2, actor="codex")
    m = f.model()
    counts = RV.ledger_counts(m)
    check("V07", m.rep["duties"][duty]["disposition"] == "DISCHARGED" and head_of(m, 7, 2).verdict == "ADMITTED"
          and head_of(m, 7, 2).accepted_by == ["codex"] and head_of(m, 7, 1).verdict == "PENDING"
          and counts.get("codex") == {"findings": 1, "reproduced": 1, "answered": 1, "misses": 0}
          and reliance(f, duty, h2) == "ELIGIBLE",
          "the acceptor accepts the answering head: the duty is DISCHARGED; the ledger counts the finding",
          (m.rep["duties"][duty]["disposition"], counts))
    f.save()
    check("V08", f.problems(f.start) == [] and f.ok("check", "--base", f.start).endswith("; OK"),
          "the loop's records and REVIEWS.md pass check against the base", f.problems(f.start))
    return f


def thesis_and_forgery_cases():
    f = started()
    t = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P3", "--what", "the name says nothing",
             actor="codex")
    out = f.ok("replay")
    m = f.model()
    fd = m.findings[t]
    check("V09", fd.test is None and RV.finding_class(fd) == "THESIS" and out == "" and fd.observed == {}
          and "thesis: THESIS — the name says nothing" in RV.render_view(m),
          "a finding without a test is a thesis, labelled so, and nothing replays it", out)
    f.save()

    before = RV.render_view(f.model())
    counts = RV.ledger_counts(f.model())
    m = f.model()
    h = head_of(m, 1, 1)
    doc = {"schema": RV.FINDING, "duty": f.duty, "pr": 1, "head": h.tid, "commit": h.commit, "tree": h.tree,
           "severity": "P0", "what": "forged", "where": [], "test": None}
    forged = f.put("codex", "challenge", R.challenge(h.tid, "P0 forged", [C.digest(C.canon(doc))], item_index=0), [doc],
                   key=W.Key.generate())
    m = f.model()
    check("V10", forged not in m.recs and forged not in m.findings and RV.render_view(m) == before
          and RV.ledger_counts(m) == counts and (f.dir / ".warrant" / "store" / "records" / f"{forged}.json").is_file(),
          "a finding signed by a key bound to nobody is not authentic: it is no finding, not shown, not counted", forged)
    f.close()


def name_cases():
    f = started()
    short = f.h1[:12]
    tool = [f.code("finding", "--pr", "1", "--commit", c, "--severity", "P2", "--what", "x", actor="codex")
            for c in ("HEAD", short, f.h1.upper(), f.h1 + "\n")]
    heads = [f.code("head", "--pr", "1", "--commit", c) for c in ("HEAD", "master", short)]
    m = f.model()
    h = head_of(m, 1, 1)
    for i, name in enumerate(("master", short)):
        doc = {"schema": RV.FINDING, "duty": f.duty, "pr": 1, "head": h.tid, "commit": name, "tree": h.tree,
               "severity": "P2", "what": f"by ref {i}", "where": [], "test": None}
        f.put("codex", "challenge", R.challenge(h.tid, f"P2 by ref {i}", [C.digest(C.canon(doc))], item_index=0), [doc])
    tree = f.git("rev-parse", "HEAD^{tree}")
    doc = {"schema": RV.HEAD, "duty": f.duty, "pr": 1, "commit": "master", "tree": tree, "previous": h.tid, "answers": []}
    hh = C.digest(C.canon(doc))
    f.put("claude", "transition", R.transition("ATTESTED", [hh], closes=[R.item(f.duty, "discharge", [hh])],
                                               established=["by ref"]), [doc])
    m = f.model()
    check("V11", tool == [("REVIEW_COMMIT_NAME", True)] * 4 and heads == [("REVIEW_COMMIT_NAME", True)] * 3
          and [c for c, _ in m.problems].count("REVIEW_FINDING_COMMIT_NAME") == 2 and not m.findings
          and [c for c, _ in m.problems].count("REVIEW_COMMIT_NAME") == 1 and len(m.reviews[1].heads) == 1,
          "a head or a finding names a commit by its full lowercase id: a ref, a short id, uppercase or a trailing "
          "newline is refused by the tool and, in a record filed by hand, by check", (tool, heads, m.problems))
    f.close()


def superseded_cases():
    f = started()
    h2 = f.commit("more", {"calc.py": FIXED})
    t2 = f.ok("head", "--pr", "1", "--commit", h2)
    tool = f.code("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "late", actor="codex")
    late_accept = f.code("accept", "--pr", "1", "--commit", f.h1, actor="codex")
    m = f.model()
    h = head_of(m, 1, 1)
    doc = {"schema": RV.FINDING, "duty": f.duty, "pr": 1, "head": h.tid, "commit": h.commit, "tree": h.tree,
           "severity": "P2", "what": "against head 1", "where": [], "test": None}
    late = f.put("codex", "challenge", R.challenge(h.tid, "P2 against head 1", [C.digest(C.canon(doc))], item_index=0),
                 [doc], at=m.recs[t2]["at"] + 1)
    t1 = m.recs[h.tid]["body"]
    f.put("codex", "accept", R.accept(h.tid, 0, t1["closes"][0]["evidence"]), at=m.recs[t2]["at"] + 1)
    m = f.model()
    codes = [c for c, _ in m.problems]
    check("V12", tool == ("REVIEW_HEAD_SUPERSEDED", True) and late_accept == ("REVIEW_HEAD_SUPERSEDED", True)
          and "REVIEW_FINDING_SUPERSEDED" in codes and late not in m.findings and "REVIEW_ACCEPT_SUPERSEDED" in codes,
          "a finding or an acceptance names the current head: one against a superseded head is refused by the tool "
          "and, filed by hand after the next head, by check", (tool, late_accept, m.problems))
    f.close()


def accept_cases():
    f = started()
    claude = f.code("accept", "--pr", "1", "--commit", f.h1)
    stranger = f.code("accept", "--pr", "1", "--commit", f.h1, actor="stranger")
    f.ok("accept", "--pr", "1", "--commit", f.h1, actor="codex")
    twice = f.code("accept", "--pr", "1", "--commit", f.h1, actor="codex")
    check("V24", claude == ("NOT_AN_ACCEPTOR", True) and stranger == ("NOT_AN_ACCEPTOR", True)
          and twice == ("NOT_PENDING", True) and head_of(f.model(), 1, 1).accepted_by == ["codex"],
          "only an acceptor the duty names accepts, once, the current head", (claude, stranger, twice))
    f.save()

    # A finding after acceptance: the closure is challenged, the next head revalidates it.
    cid = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P1", "--what", "add subtracts",
               "--test", "finding_test", "--case", "F1",
               "--patch", str(_write(f.base / "f.diff", finding_test()["patch"])), actor="codex")
    f.ok("replay")
    m = f.model()
    challenged = reliance(f, f.duty, f.h1)
    miss = RV.ledger_counts(m)["codex"]["misses"]
    h2 = f.commit("fix", {"calc.py": FIXED})
    t2 = f.ok("answer", "--pr", "1", "--commit", h2, "--finding", cid)
    f.ok("accept", "--pr", "1", "--commit", h2, actor="codex")
    m = f.model()
    item = m.recs[t2]["body"]["closes"][0]
    check("V25", challenged == "CHALLENGED" and miss == 1 and item["act"] == "revalidate" and item["revalidates"] == [f.t1]
          and reliance(f, f.duty, h2) == "ELIGIBLE" and RV.ledger_counts(m)["codex"]["misses"] == 1,
          "a finding reproduced at an accepted head challenges the closure and counts as the acceptor's miss; the "
          "answering head revalidates it and, accepted, is relied on again", (challenged, item))
    f.close()


# ---------------------------------------------------------------- the interface

def recipe():
    """The review recipe of AGENT.md (the block after `<!-- review-recipe -->`): {name: prepare arguments}."""
    text = (ROOT / "AGENT.md").read_text()
    block = text[text.index("<!-- review-recipe -->"):]
    block = block[block.index("```json\n") + 8:]
    return json.loads(block[:block.index("```")])


def fill_in(doc, slots):
    if isinstance(doc, dict):
        return {k: fill_in(v, slots) for k, v in doc.items()}
    if isinstance(doc, list):
        return [fill_in(v, slots) for v in doc]
    if isinstance(doc, str) and re.fullmatch(r"<[^<>]+>", doc):
        return slots[doc]
    return doc


def equivalence_case():
    """V20: each step through warrant-agent prepare/commit files the bytes tools/review.py files."""
    try:
        from warrant_agent import api
        from warrant_agent import init as I
        from warrant_agent.config import Config
    except ImportError as e:
        check("V20", False, "warrant_agent is importable", str(e))
        return
    a = Fixture()
    h1 = a.commit("change", {"calc.py": BUGGY + "#\n"})
    h2 = a.commit("fix", {"calc.py": FIXED + "#\n"})
    b = Fixture.__new__(Fixture)
    b.__dict__.update(a.__dict__)
    b.base = Path(tempfile.mkdtemp(prefix="warrant-reviews-b-"))
    shutil.rmtree(b.base)
    shutil.copytree(a.base, b.base, symlinks=True)
    b.dir = b.base / "repo"
    b.seeds = {k: str(b.base / Path(v).name) for k, v in a.seeds.items()}

    def init(actor):
        cfg = b.base / "op" / f"{actor}.json"
        real = I.ROOTS
        I.ROOTS = (b.base,)
        try:
            I.init(repo=b.dir, actor=actor, seed=Path(b.seeds[actor]), config=cfg, workspace="repo",
                   operations=("context", "read", "prepare", "commit"))
        finally:
            I.ROOTS = real
        return Config.load(cfg)

    def pc(cfg, args):
        d = api.call(cfg, "prepare", dict(args, workspace="repo"))
        assert "ok" in d, d
        c = api.call(cfg, "commit", {"workspace": "repo", "draft_id": d["ok"]["data"]["draft_id"]})
        assert "ok" in c, c
        return c["ok"]["data"]["record_id"]

    claude, codex = init("claude"), init("codex")
    steps = recipe()
    tree = {c: a.git("rev-parse", f"{c}^{{tree}}") for c in (h1, h2)}
    frozen = int(time.time()) + 120
    real, same = time.time, []
    time.time = lambda: frozen
    try:
        d1 = a.ok("open", "--pr", "9", "--title", "Through MCP")
        d2 = pc(claude, fill_in(steps["open"], {"<your actor>": "claude", "<REPO#N is fit to merge: TITLE>":
                                                f"{REPO}#9 is fit to merge: Through MCP", "<owed_to of .warrant/reviews.json>":
                                                ["s0fractal"], "<accept_by of .warrant/reviews.json>": ["codex"],
                                                "<served duty ids>": []}))
        same.append(("open", d1 == d2 and a.files() == b.files()))

        def head_slots(commit, previous, answers):
            return {"<duty id>": d1, "<number>": 9, "<commit>": commit, "<tree>": tree[commit],
                    "<REPO#N head COMMIT tree TREE>": f"{REPO}#9 head {commit} tree {tree[commit]}",
                    "<previous head closure or null>": previous, "<sorted finding ids>": answers}
        t1 = a.ok("head", "--pr", "9", "--commit", h1)
        u1 = pc(claude, fill_in(steps["head"], head_slots(h1, None, [])))
        same.append(("head", t1 == u1 and a.files() == b.files()))
        test = finding_test()
        c1 = a.ok("finding", "--pr", "9", "--commit", h1, "--severity", "P2", "--what", "add subtracts",
                  "--where", "calc.py:2", "--test", test["file"], "--case", test["case"],
                  "--patch", str(_write(a.base / "f.diff", test["patch"])), actor="codex")
        k1 = pc(codex, fill_in(steps["finding"], {"<current head closure>": u1, "<SEVERITY WHAT>": "P2 add subtracts",
                                                  "<duty id>": d1, "<number>": 9, "<commit>": h1, "<tree>": tree[h1],
                                                  "<P0, P1, P2 or P3>": "P2", "<one line>": "add subtracts",
                                                  "<paths or path:line>": ["calc.py:2"], "<null or file, case, patch>": test}))
        same.append(("finding", c1 == k1 and a.files() == b.files()))
        t2 = a.ok("answer", "--pr", "9", "--commit", h2, "--finding", c1)
        u2 = pc(claude, fill_in(steps["head"], head_slots(h2, u1, [k1])))
        same.append(("answer", t2 == u2 and a.files() == b.files()))
        x1 = a.ok("accept", "--pr", "9", "--commit", h2, actor="codex")
        y1 = pc(codex, fill_in(steps["accept"], {"<current head closure>": u2}))
        same.append(("accept", x1 == y1 and a.files() == b.files()))
    finally:
        time.time = real
    for x in (a, b):
        x.ok("project")
    views = [(x.dir / "REVIEWS.md").read_bytes() for x in (a, b)]
    m = b.model()
    check("V20", all(s for _, s in same) and views[0] == views[1] and a.problems() == b.problems() == []
          and m.rep["duties"][d1]["disposition"] == "DISCHARGED" and m.findings[k1].answered_by.tid == u2
          and "revalidate" in steps and steps["revalidate"]["body"]["closes"][0]["act"] == "revalidate",
          "open, head, finding, answer and accept through prepare/commit file the bytes tools/review.py files; "
          "REVIEWS.md is identical", same)
    shutil.rmtree(b.base, ignore_errors=True)
    a.close()


def witnesses_case():
    """V29: WITNESSES.md carries the review columns of the repository's records (claims views)."""
    f = loop_cases()
    repo = claimslib.Repo(f.dir)
    model = claimslib.Model(repo.snapshot(), repo.trust())
    text = claimslib.render_witnesses(repo, model, {})
    row = next(line for line in text.splitlines() if line.startswith("| codex |"))
    row_c = next(line for line in text.splitlines() if line.startswith("| claude |"))
    check("V29", row.endswith("| 1 | 1 | 1 | 0 |") and row_c.endswith("| 0 | 0 | 0 | 0 |")
          and RV.repo_ledger(f.dir, model) == RV.ledger_counts(f.model())
          and "Accepted heads a finding reproduces at" in text,
          "the witness ledger counts each actor's findings, reproduced, answered, and accepted heads a finding "
          "reproduces at", (row, row_c))
    f.close()


def main():
    for part in (witnesses_case, thesis_and_forgery_cases, name_cases, superseded_cases, accept_cases, equivalence_case):
        try:
            part()
        except Exception as e:      # noqa: BLE001 -- a part that raises fails its cases, the others still run
            import traceback
            traceback.print_exc()
            check(f"RAISED-{part.__name__}", False, "ran to its end", f"{type(e).__name__}: {e}")
    return finish("REVIEWS_TEST")


if __name__ == "__main__":
    raise SystemExit(main())
