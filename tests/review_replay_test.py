#!/usr/bin/env python3
"""The review replay checker (tools/claimslib/review_replay.py) and its observations: diffs confined to
tests/, outcomes that reproduce nothing, verify, adopted replayers (V26-V28).

    python3 tests/review_replay_test.py
"""
from review_world import (C, CRASHING_TEST, R, RR, RV, _write, finding_test, head_of, new_file_patch, started)
from world import check, finish


# ---------------------------------------------------------------- replay

def replay_cases():
    f = started()
    p = _write(f.base / "outside.diff", "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-x\n+y\n")
    outside = f.code("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "outside",
                     "--test", "finding_test", "--case", "F1", "--patch", str(p), actor="codex")
    shapes = [RR.patch_problem(x) is not None for x in (
        "--- a/tests/x/../../calc.py\n+++ b/tests/x/../../calc.py\n",
        "diff --git a/tests/x_test.py b/tests/x_test.py\nnew file mode 120000\n",
        "diff --git a/tests/x_test.py b/tests/x_test.py\nGIT binary patch\n",
        "rename from calc.py\nrename to tests/calc.py\n",
        new_file_patch("tests/ok_test.py", "x = 1\n"))]
    crash = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "crashes",
                 "--test", "crash_test", "--case", "F1",
                 "--patch", str(_write(f.base / "c.diff", finding_test("crash_test", CRASHING_TEST)["patch"])), actor="codex")
    stale = {"file": "calc_test", "case": "F1",
             "patch": "--- a/tests/calc_test.py\n+++ b/tests/calc_test.py\n@@ -1 +1 @@\n-# not this line\n+x\n"}
    nope = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "does not apply",
                "--test", stale["file"], "--case", "F1", "--patch", str(_write(f.base / "s.diff", stale["patch"])),
                actor="codex")
    f.ok("replay")
    m = f.model()
    check("V26", outside == ("REVIEW_FINDING_TEST", True) and shapes == [True, True, True, True, False]
          and m.findings[crash].at(f.h1) == "NO_RESULT" and m.findings[nope].at(f.h1) == "DOES_NOT_APPLY"
          and RV.finding_class(m.findings[crash]) == RV.finding_class(m.findings[nope]) == "UNEVALUABLE",
          "a test diff is confined to tests/; a test that crashes or a diff that does not apply reproduces nothing",
          (outside, shapes))
    base = f.save()

    # The replayer's observations new since the base are re-executed by verify.
    cid = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "add subtracts",
               "--test", "finding_test", "--case", "F1",
               "--patch", str(_write(f.base / "f.diff", finding_test()["patch"])), actor="codex")
    m = f.model()
    probe = {"probe": RR.PROBE, "finding": cid, "commit": f.h1, "tree": head_of(m, 1, 1).tree, "test": "finding_test:F1"}
    now = f.at()
    lie = f.put(f.replayer, "observation", R.observation(RV.replay_target(m.cfg, 1, cid, f.h1), C.digest(C.canon(probe)),
                                                         [now, now], "PASS"), [probe])
    f.save()
    rc, out, _ = f.run("replay", "--verify", "--base", base)
    lied = [c for c, _ in RV.verify(f.rv(), base)]
    m = f.model()
    check("V27", lied == ["REVIEW_REPLAY_DIFFERS"] and rc == 1 and m.findings[cid].at(f.h1) == "PASS"
          and m.findings[cid].observed[f.h1][0] == lie and RV.verify(f.rv(), f.git("rev-parse", "HEAD")) == [],
          "replay --verify re-executes each replay observation new since the base and refuses one it does not "
          "reproduce", (lied, out))
    f.close()

    f = started()
    cid = f.ok("finding", "--pr", "1", "--commit", f.h1, "--severity", "P2", "--what", "add subtracts",
               "--test", "finding_test", "--case", "F1",
               "--patch", str(_write(f.base / "f.diff", finding_test()["patch"])), actor="codex")
    m = f.model()
    probe = {"probe": RR.PROBE, "finding": cid, "commit": f.h1, "tree": head_of(m, 1, 1).tree, "test": "finding_test:F1"}
    now = f.at()
    f.put("stranger", "observation", R.observation(RV.replay_target(m.cfg, 1, cid, f.h1), C.digest(C.canon(probe)),
                                                   [now, now], "PASS"), [probe])
    m = f.model()
    unpinned = [c for c, _ in m.problems]
    f.config(replayers=["checker sha256:" + "0" * 64])
    f.ok("project")
    stale = f.problems()
    check("V28", unpinned == ["REVIEW_REPLAYER_UNPINNED"] and m.findings[cid].at(f.h1) is None
          and "REVIEW_REPLAYER_STALE" in stale,
          "only an adopted replayer's observation counts, and the adopted one is this checkout's review_replay.py",
          (unpinned, stale))
    f.close()


def main():
    for part in (replay_cases,):
        try:
            part()
        except Exception as e:      # noqa: BLE001 -- a part that raises fails its cases, the others still run
            import traceback
            traceback.print_exc()
            check(f"RAISED-{part.__name__}", False, "ran to its end", f"{type(e).__name__}: {e}")
    return finish("REVIEW_REPLAY_TEST")


if __name__ == "__main__":
    raise SystemExit(main())
