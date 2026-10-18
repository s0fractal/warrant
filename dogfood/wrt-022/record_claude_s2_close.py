#!/usr/bin/env python3
"""Claude's closing transition for the S2 duty, filed once, on 2026-10-18, after
Codex's ACCEPT of S2 at 73f90e1 and of the loader fix at 150bd94, both integrated
at the commit below. Kept for audit: running it again files a NEW record. Codex's
acceptance of this exact mapping is Codex's event.

    WRT022_KEY=<claude's key> python3 dogfood/wrt-022/record_claude_s2_close.py
"""
import json
import sys

import events as E

sys.path.insert(0, str(E.ROOT / "impl"))
import loops as L      # noqa: E402
import triggers as TR  # noqa: E402

S2_DUTY = "9fec95e34bd15c5078e183541db710db3e1b03728565b714b779080a53356b32"
INTEGRATED = "faf52e0fbd4c79844fc6013971bc45c7bf2a8d68"
CODEX_REVIEW = "8e7af40c4270b01b80f4344e058c2aff02f83c3a2fdcadb391985243c6fa6125"
SLICE = sorted([
    "impl/replay.py", "impl/replay_sigma_worker.py",
    "impl/sigma_resume_c864d3e/sigma_resume.py", "impl/sigma_resume_c864d3e/sigma_glyph.py",
    "impl/sigma_resume_c864d3e/PIN.json", "impl/loops.py", "impl/triggers.py", "impl/warrant.py",
    "impl/sigma_glyph_v05.py", "impl/assessment.py", "impl/policy_lang.py",
    "tests/replay_test.py", "tests/replay_mutants.py", "tests/sigma_loader_read_once.py",
    "tests/sigma_loader_mutants.py", "tests/loops_test.py", "tests/loops_mutants.py",
    "tests/triggers_test.py", "tests/triggers_mutants.py",
    "dogfood/wrt-022/POLICY.md", "dogfood/wrt-022/events.py", "dogfood/wrt-022/profile.json",
    "dogfood/wrt-022/trust.json",
])


def main():
    s = E.store()
    attestation = {
        "claim": "WRT-022 S2 (crossings, replay receipts the recipient re-verifies) is implemented, with the "
                 "evaluator-loader fix integrated",
        "implementation": INTEGRATED,
        "reviewed": {"S2": "73f90e1ece815ec8932a50d517d89634dd16df32",
                     "loader": "150bd9400831645a02964a0ed0ff97d91ae17cfc"},
        "measured_at_implementation": {
            "tests/replay_test.py": "22 PASS / 0 FAIL", "tests/replay_mutants.py": "21/21 killed on target",
            "tests/sigma_loader_read_once.py": "4 PASS / 0 FAIL", "tests/sigma_loader_mutants.py": "4/4",
            "tools/check.py": "99 passed, 0 failed, 1 unrun (workflow lint: actionlint absent)"},
        "independent_review": {"record": CODEX_REVIEW, "verdict": "ACCEPT", "actor": E.CODEX},
        "not_established": ["S3-S8 of WRT-022", "independent key custody: both keys are one operator's",
                            "S1's closure revalidation (its trigger fired on impl/loops.py; not needed here)"],
    }
    ev = s.put_blob(L.canon(attestation))
    baseline = s.put_blob(L.canon(TR.build(E.ROOT, INTEGRATED, SLICE)))
    trig = [{"kind": "subject_changed", "baseline": baseline}]
    t = L.transition("ATTESTED", [ev], closes=[L.mapping(S2_DUTY, "DISCHARGED", [ev], triggers=trig)],
                     relied_on=[CODEX_REVIEW], addresses=[S2_DUTY],
                     not_established=attestation["not_established"], scope_subject=INTEGRATED)
    tid = E.file(s, "propose", s.put_blob(L.canon(t)), E.CLAUDE, prior=[S2_DUTY, CODEX_REVIEW], note="transition")
    print(json.dumps({"transition": tid, "mapping": 0, "evidence": [ev], "baseline": baseline}, indent=2))


if __name__ == "__main__":
    main()
