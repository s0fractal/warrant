#!/usr/bin/env python3
"""WRT-022 S1: revalidation triggers (impl/triggers.py) and reliance for a named
use (impl/loops.py), against the engineering contract of the 410a048 re-review.

    python3 tests/triggers_test.py

Every case builds a real git repository and a real signed store; every verdict
is read by name from the assessment.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "impl"))
# TRIGGERS_IMPL lets tests/triggers_mutants.py run this file against mutated copies
# of impl/loops.py and impl/triggers.py; loops_test honours it as LOOPS_IMPL.
if os.environ.get("TRIGGERS_IMPL"):
    sys.path.insert(0, os.environ["TRIGGERS_IMPL"])
    os.environ["LOOPS_IMPL"] = os.environ["TRIGGERS_IMPL"]
import loops_test as LT   # noqa: E402  (its Case: a signed store with three actors)
import loops as L         # noqa: E402
import triggers as TR     # noqa: E402

results = {}
case = None
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
PROFILE = {"schema": L.PROFILE, "uses": {"merge": {"requires_declared_triggers": True},
                                         "read": {"requires_declared_triggers": False}}}


def check(tid, ok, what, detail=""):
    results[tid] = "PASS" if ok else "FAIL"
    print(("ok    " if ok else "FAIL  ") + f"{tid} {what}" + ("" if ok else f" | {detail}"))


class Repo:
    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="trig-repo-"))
        self.git("init", "-q")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.path), *args], env=GIT_ENV, capture_output=True,
                              text=True, check=True).stdout.strip()

    def write(self, rel, text, mode=None):
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if mode:
            os.chmod(p, mode)

    def commit(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")


def setup():
    """A repo with a reviewed file, a toolchain file and an unrelated file; a duty,
    closed by an attested transition that declares a subject_changed trigger over
    the reviewed file and the toolchain file (the dependency slice)."""
    repo = Repo()
    repo.write("src/rule.py", "LIMIT = 50000\n")
    repo.write("rust-toolchain.toml", "[toolchain]\nchannel = '1.90'\n")
    repo.write("docs/notes.md", "notes\n")
    base = repo.commit("base")
    c = LT.Case()
    selector = ["rust-toolchain.toml", "src/rule.py"]
    manifest = TR.build(repo.path, base, selector)
    mh = c.blob(manifest)
    return repo, base, c, mh


def close(c, triggers, scope=None):
    n1 = c.open()
    t = L.transition("ATTESTED", [c.evidence], closes=[L.mapping(n1, "DISCHARGED", [c.evidence], triggers=triggers)],
                     scope_subject=scope)
    tid = c.record("propose", c.blob(t), LT.CLAUDE, prior=[n1])
    c.accept(LT.CODEX, n1, tid)
    return n1


def results_of(rep, did):
    return [t["result"] for t in rep["duties"][did]["triggers"]]


def main():
    # T01 unchanged: NOT_FIRED, and the scoped trigger is a revision basis
    repo, base, c, mh = setup()
    n1 = close(c, [{"kind": "subject_changed", "baseline": mh}])
    rep = L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, base))
    check("T01", results_of(rep, n1) == ["NOT_FIRED"] and L.reliance(rep, n1) == "ELIGIBLE",
          "an unchanged dependency slice: NOT_FIRED, ELIGIBLE", rep["duties"][n1]["triggers"])

    # T02 an unrelated change outside the slice: still NOT_FIRED, still ELIGIBLE
    repo.write("docs/notes.md", "other notes\n")
    later = repo.commit("unrelated")
    rep = L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, later))
    check("T02", results_of(rep, n1) == ["NOT_FIRED"] and L.reliance(rep, n1) == "ELIGIBLE",
          "a change outside the declared slice does not fire", rep["duties"][n1]["triggers"])

    # T03 a relevant change: FIRED, STALE naming the path; the closure itself is untouched
    repo.write("src/rule.py", "LIMIT = 60000\n")
    rel = repo.commit("relevant")
    rep = L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, rel))
    det = L.reliance_detail(rep, n1)
    check("T03", results_of(rep, n1) == ["FIRED"] and det["state"] == "STALE"
          and "src/rule.py" in det["causes"][0] and rep["duties"][n1]["disposition"] == "DISCHARGED",
          "a changed relevant operand fires; historical validity stays", det)

    # T04 a toolchain operand is part of the slice: changing it fires too
    repo2, base2, c2, mh2 = setup()
    n2 = close(c2, [{"kind": "subject_changed", "baseline": mh2}])
    repo2.write("rust-toolchain.toml", "[toolchain]\nchannel = '1.91'\n")
    tc = repo2.commit("toolchain")
    rep = L.assess(c2.S.root, c2.trust, LT.T_END, workspace=(repo2.path, tc))
    check("T04", results_of(rep, n2) == ["FIRED"], "a toolchain operand change fires",
          rep["duties"][n2]["triggers"])

    # T05 a file-mode change fires (the mode is part of the entry)
    repo2.write("src/rule.py", "LIMIT = 50000\n", mode=0o755)
    md = repo2.commit("mode")
    m_now = TR.build(repo2.path, md, ["src/rule.py"])["entries"]["src/rule.py"]["mode"]
    rep = L.assess(c2.S.root, c2.trust, LT.T_END, workspace=(repo2.path, md))
    check("T05", m_now == "100755" and results_of(rep, n2) == ["FIRED"], "a mode change fires", m_now)

    # T06 the current revision cannot be read: UNEVALUABLE, never NOT_FIRED
    rep = L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, "ab" * 20))
    det = L.reliance_detail(rep, n1)
    check("T06", results_of(rep, n1) == ["UNEVALUABLE"] and det["state"] == "UNASSESSED"
          and "revision unavailable" in det["causes"][0], "an unavailable current revision is UNEVALUABLE", det)

    # T07 a required dependency is missing at the current revision: UNEVALUABLE
    repo3, base3, c3, mh3 = setup()
    n3 = close(c3, [{"kind": "subject_changed", "baseline": mh3}])
    repo3.git("rm", "-q", "rust-toolchain.toml")
    gone = repo3.commit("rm")
    rep = L.assess(c3.S.root, c3.trust, LT.T_END, workspace=(repo3.path, gone))
    det = L.reliance_detail(rep, n3)
    check("T07", results_of(rep, n3) == ["UNEVALUABLE"] and "missing dependency: rust-toolchain.toml" in det["causes"][0],
          "a missing required dependency is UNEVALUABLE, not unchanged", det)

    # T08 no workspace in the view, or a baseline that is not in the store: UNEVALUABLE
    rep = L.assess(c3.S.root, c3.trust, LT.T_END)
    c4 = LT.Case()
    n4 = close(c4, [{"kind": "subject_changed", "baseline": "cd" * 32}])
    rep4 = L.assess(c4.S.root, c4.trust, LT.T_END, workspace=(repo3.path, base3))
    check("T08", results_of(rep, n3) == ["UNEVALUABLE"] and results_of(rep4, n4) == ["UNEVALUABLE"]
          and "baseline manifest not in view" in rep4["duties"][n4]["triggers"][0]["detail"],
          "no workspace, or no baseline, is UNEVALUABLE", (rep["duties"][n3]["triggers"], rep4["duties"][n4]["triggers"]))

    # T09 duty_not_discharged: known DISCHARGED / known open / missing
    c5 = LT.Case()
    dep_open = c5.open(statement="still open")
    dep_done = c5.open(statement="done")
    td = c5.discharge(dep_done)
    c5.accept(LT.CODEX, dep_done, td)
    ghost = "ef" * 32
    a = close(c5, [{"kind": "duty_not_discharged", "duty": dep_done}], scope=LT.SHA_NEW)
    b = close(c5, [{"kind": "duty_not_discharged", "duty": dep_open}], scope=LT.SHA_NEW)
    g = close(c5, [{"kind": "duty_not_discharged", "duty": ghost}], scope=LT.SHA_NEW)
    rep = L.assess(c5.S.root, c5.trust, LT.T_END, current={LT.SHA_NEW})
    check("T09", (results_of(rep, a), results_of(rep, b), results_of(rep, g)) == (["NOT_FIRED"], ["FIRED"], ["UNEVALUABLE"])
          and [L.reliance(rep, x) for x in (a, b, g)] == ["ELIGIBLE", "STALE", "UNASSESSED"],
          "known discharged / known open / missing duty are three different results",
          [rep["duties"][x]["triggers"] for x in (a, b, g)])

    # T10 several causes stay separate
    repo6, base6, c6, mh6 = setup()
    open6 = c6.open(statement="open dependency")
    n6 = close(c6, [{"kind": "subject_changed", "baseline": mh6}, {"kind": "duty_not_discharged", "duty": open6},
                    {"kind": "duty_not_discharged", "duty": "ab" * 32}])
    repo6.write("src/rule.py", "LIMIT = 1\n")
    ch6 = repo6.commit("relevant")
    rep = L.assess(c6.S.root, c6.trust, LT.T_END, workspace=(repo6.path, ch6))
    det = L.reliance_detail(rep, n6)
    check("T10", results_of(rep, n6) == ["FIRED", "FIRED", "UNEVALUABLE"] and det["state"] == "STALE"
          and len(det["causes"]) == 2 and rep["duties"][n6]["trigger_coverage"] == {"FIRED": 2, "NOT_FIRED": 0,
                                                                                    "UNEVALUABLE": 1},
          "every trigger result and every cause is kept", det)

    # T11 no declared triggers is neutral: it neither satisfies nor skips the revision basis
    c7 = LT.Case()
    n7 = close(c7, [], scope=LT.SHA_NEW)
    with_basis = L.assess(c7.S.root, c7.trust, LT.T_END, current={LT.SHA_NEW})
    without = L.assess(c7.S.root, c7.trust, LT.T_END)
    check("T11", with_basis["duties"][n7]["trigger_coverage"] == "NO_DECLARED_TRIGGERS"
          and L.reliance(with_basis, n7) == "ELIGIBLE" and L.reliance(without, n7) == "UNASSESSED",
          "NO_DECLARED_TRIGGERS is neutral coverage", L.reliance_detail(without, n7))

    # T12 a named use: unknown use, and a use that requires declared triggers
    rep = L.assess(c7.S.root, c7.trust, LT.T_END, current={LT.SHA_NEW}, profile=PROFILE)
    rep1 = L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, later), profile=PROFILE)
    check("T12", L.reliance(rep, n7, "read") == "ELIGIBLE" and L.reliance(rep, n7, "merge") == "UNASSESSED"
          and L.reliance(rep, n7, "deploy") == "UNASSESSED" and L.reliance(rep1, n1, "merge") == "ELIGIBLE",
          "eligibility is for a named use in the recipient's profile", L.reliance_detail(rep, n7, "merge"))

    # T13 the assessment identity binds every operand that can change a result
    ids = {
        "base": L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, base), profile=PROFILE),
        "again": L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, base), profile=PROFILE),
        "commit": L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, rel), profile=PROFILE),
        "profile": L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, base)),
        "current": L.assess(c.S.root, c.trust, LT.T_END, workspace=(repo.path, base), profile=PROFILE,
                            current={LT.SHA_NEW}),
        "as_of": L.assess(c.S.root, c.trust, LT.T_END - 1, workspace=(repo.path, base), profile=PROFILE),
    }
    aid = {k: v["view"]["assessment_id"] for k, v in ids.items()}
    manifests_differ = ((ids["base"]["view"]["workspace"] or {}).get("manifests")
                        != (ids["commit"]["view"]["workspace"] or {}).get("manifests"))
    check("T13", aid["base"] == aid["again"] and len({aid[k] for k in aid if k != "again"}) == 5 and manifests_differ
          and L.reliance_detail(ids["base"], n1, "merge")["assessment_id"] == aid["base"],
          "same operands, same id; any changed operand, a different id", aid)

    # T14 unsupported inputs are refused, never hashed as if covered
    repo8 = Repo()
    repo8.write("real.txt", "x\n")
    os.symlink("real.txt", repo8.path / "link.txt")
    (repo8.path / "dir").mkdir()
    repo8.write("dir/a.txt", "a\n")
    r8 = repo8.commit("inputs")
    refused = []
    for sel in (["link.txt"], ["dir"], ["nope.txt"], ["/etc/passwd"], ["a/../b"], ["b", "a"]):
        try:
            TR.build(repo8.path, r8, sel)
            refused.append(None)
        except TR.Refusal as e:
            refused.append(str(e))
    # Unsafe paths must be refused by the selector rule itself, before git is asked:
    # git would also fail on some of them, which is not this guard.
    unsafe = [TR.selector_problem([p]) for p in ("/etc/passwd", "a/../b", "a\\b", "./a", "a//b")]
    check("T14", all(refused) and "mode 120000" in refused[0] and "directory" in refused[1]
          and "missing dependency" in refused[2] and "not a plain" in refused[3] and "not a plain" in refused[4]
          and "sorted" in refused[5] and all(u and "not a plain" in u for u in unsafe),
          "symlink, directory, missing, unsafe or unsorted selectors refuse", (refused, unsafe))

    # T15 malformed trigger declarations: the transition is refused, the rest of the view survives
    c9 = LT.Case()
    other = c9.open(statement="unrelated duty")
    bads = [{"kind": "nope", "duty": "ab" * 32}, {"kind": "duty_not_discharged", "duty": "ab" * 32, "x": 1},
            {"kind": "subject_changed", "baseline": "XYZ"}, {"kind": ["subject_changed"], "baseline": "ab" * 32}]
    refused_ids = []
    for bad in bads:
        n9 = c9.open()
        t = L.transition("ATTESTED", [c9.evidence], closes=[L.mapping(n9, "DISCHARGED", [c9.evidence], triggers=[bad])])
        refused_ids.append(c9.record("propose", c9.blob(t), LT.CLAUDE, prior=[n9]))
    n_dup = c9.open()
    dup = [{"kind": "duty_not_discharged", "duty": "ab" * 32}] * 2
    t = L.transition("ATTESTED", [c9.evidence], closes=[L.mapping(n_dup, "DISCHARGED", [c9.evidence], triggers=dup)])
    refused_ids.append(c9.record("propose", c9.blob(t), LT.CLAUDE, prior=[n_dup]))
    rep = L.assess(c9.S.root, c9.trust, LT.T_END)
    check("T15", all(r in rep["refused_events"] for r in refused_ids) and rep["duties"][other]["disposition"] == "OPEN",
          "malformed triggers refuse their transition only", rep["refused_events"])

    failed = sorted(k for k, v in results.items() if v == "FAIL")
    print(f"TRIGGERS: {sum(v == 'PASS' for v in results.values())} PASS / {len(failed)} FAIL"
          + (f" ({', '.join(failed)})" if failed else ""))
    if os.environ.get("TRIGGERS_RESULTS"):
        Path(os.environ["TRIGGERS_RESULTS"]).write_text(json.dumps(results))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
