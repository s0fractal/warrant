#!/usr/bin/env python3
"""Second filing (after Codex RV-01): Claude files REVALIDATED mappings for the S1 and S2 closures, once, on 2026-10-18,
at the commit below. Both read STALE only because test harnesses moved to
tests/mutant_runner.py (and, for S1, because impl/loops.py grew S2 and revalidation).
Each revalidation names the closure it revalidates and declares subject_changed
over the CURRENT slice, which now includes tests/mutant_runner.py (Codex, handoff of
the #136/S2 acceptance). Codex's acceptance of each exact mapping is Codex's event.

    WRT022_KEY=<claude's key> python3 dogfood/wrt-022/record_claude_revalidate_s1_s2.py
"""
import json
import sys

import events as E

sys.path.insert(0, str(E.ROOT / "impl"))
import loops as L      # noqa: E402
import triggers as TR  # noqa: E402

AT = "568da2c428e35e7094b30bcf4440f77a84c03ea8"
COMMON = ["dogfood/wrt-022/POLICY.md", "dogfood/wrt-022/events.py", "dogfood/wrt-022/profile.json",
          "dogfood/wrt-022/trust.json", "impl/loops.py", "impl/triggers.py", "impl/warrant.py",
          "tests/loops_mutants.py", "tests/loops_test.py", "tests/mutant_runner.py",
          "tests/triggers_mutants.py", "tests/triggers_test.py"]
TARGETS = {
    "S1": {"duty": "8e52fa485bfb95b6165525ddb3dd783074a95bf02ba3391705815f97741b8dfa",
           "closure": "b952db61b0bb428c27a85043f97bfe267447b30ffef9b08cfb52ad53ca1a9bc1",
           "slice": COMMON},
    "S2": {"duty": "9fec95e34bd15c5078e183541db710db3e1b03728565b714b779080a53356b32",
           "closure": "08ae3651d3973de0d1d7c95109f09d3e3187e64e6d969fac269cd1a13ecb5efb",
           "slice": COMMON + ["impl/replay.py", "impl/replay_sigma_worker.py",
                              "impl/sigma_resume_c864d3e/PIN.json", "impl/sigma_resume_c864d3e/sigma_glyph.py",
                              "impl/sigma_resume_c864d3e/sigma_resume.py", "impl/sigma_glyph_v05.py",
                              "impl/assessment.py", "impl/policy_lang.py", "tests/replay_test.py",
                              "tests/replay_mutants.py", "tests/sigma_loader_read_once.py",
                              "tests/sigma_loader_mutants.py"]},
}
MEASURED = {"tools/check.py": "101 passed, 0 failed, 1 unrun (workflow lint) at 568da2c",
            "mutants": "loops 44/44, triggers 26/26, replay 21/21, loader 4/4, revalidation 8/8, on target",
            "tests": "loops 38, triggers 18, replay 22, loader 4, revalidation 12: all PASS"}


def main():
    s = E.store()
    out = {}
    for name, tg in TARGETS.items():
        att = {"claim": f"the WRT-022 {name} closure still holds at {AT}; its trigger fired only because test "
                        "harnesses moved to tests/mutant_runner.py" + (" and impl/loops.py grew S2 and revalidation"
                                                                       if name == "S1" else ""),
               "revalidates": tg["closure"], "at": AT, "measured": MEASURED}
        ev = s.put_blob(L.canon(att))
        base = s.put_blob(L.canon(TR.build(E.ROOT, AT, sorted(tg["slice"]))))
        m = L.mapping(tg["duty"], "REVALIDATED", [ev], triggers=[{"kind": "subject_changed", "baseline": base}],
                      revalidates=[tg["closure"]])
        t = L.transition("ATTESTED", [ev], closes=[m], addresses=[tg["duty"]], scope_subject=AT,
                         not_established=["an independent re-review of the revalidated implementation"])
        tid = E.file(s, "propose", s.put_blob(L.canon(t)), E.CLAUDE, prior=[tg["duty"], tg["closure"]],
                     note="revalidation")
        out[name] = {"transition": tid, "mapping": 0, "evidence": [ev]}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
