#!/usr/bin/env python3
"""Claude's closing transition for the S1 duty, filed once, on 2026-10-18, after
Codex's ACCEPT of the implementation at c8c59e7. Kept for audit: running it again
files a NEW record. It never signs for anyone else.

    WRT022_KEY=<claude's key> python3 dogfood/wrt-022/record_claude_s1_close.py

The closure is attested by the holder. It relies on Codex's signed review event,
and declares a subject_changed trigger over the implementation's dependency slice
at the reviewed commit: the trigger and loop sources, the verifier they call, the
tests and mutation harnesses, and the store's profile, trust and policy. The store
itself is not in the slice, so appending events does not make the closure stale.
Codex's acceptance of this exact mapping is Codex's event.
"""
import json
import sys

import events as E

sys.path.insert(0, str(E.ROOT / "impl"))
import loops as L      # noqa: E402
import triggers as TR  # noqa: E402

S1_DUTY = "8e52fa485bfb95b6165525ddb3dd783074a95bf02ba3391705815f97741b8dfa"
REVIEWED = "c8c59e758ef68ff6656c5ebabcd3e6f09ea6ab4a"
CODEX_REVIEW = "fc52a2c69e308c4f40407a2e95be15c7f12e459af5ec7d288334a5ddc8e7a211"
SLICE = sorted([
    "impl/loops.py", "impl/triggers.py", "impl/warrant.py",
    "tests/loops_test.py", "tests/loops_mutants.py", "tests/triggers_test.py", "tests/triggers_mutants.py",
    "dogfood/wrt-022/POLICY.md", "dogfood/wrt-022/events.py", "dogfood/wrt-022/profile.json",
    "dogfood/wrt-022/trust.json",
])


def main():
    s = E.store()
    attestation = {
        "claim": "WRT-022 S1 is implemented as specified by the 410a048 re-review's S1 contract",
        "implementation": REVIEWED,
        "measured_at_implementation": {
            "tests/triggers_test.py": "18 PASS / 0 FAIL", "tests/triggers_mutants.py": "26/26 killed on target",
            "tests/loops_test.py": "38 PASS / 0 FAIL", "tests/loops_mutants.py": "44/44 killed on target",
            "tools/check.py": "95 passed, 0 failed, 1 unrun (workflow lint: actionlint absent)"},
        "independent_review": {"record": CODEX_REVIEW, "verdict": "ACCEPT", "actor": E.CODEX},
        "not_established": ["S2-S8 of WRT-022", "independent key custody: both keys are one operator's"],
    }
    ev = s.put_blob(L.canon(attestation))
    baseline = s.put_blob(L.canon(TR.build(E.ROOT, REVIEWED, SLICE)))
    trig = [{"kind": "subject_changed", "baseline": baseline}]
    t = L.transition("ATTESTED", [ev], closes=[L.mapping(S1_DUTY, "DISCHARGED", [ev], triggers=trig)],
                     relied_on=[CODEX_REVIEW], addresses=[S1_DUTY],
                     not_established=attestation["not_established"], scope_subject=REVIEWED)
    tid = E.file(s, "propose", s.put_blob(L.canon(t)), E.CLAUDE, prior=[S1_DUTY, CODEX_REVIEW], note="transition")
    print(json.dumps({"transition": tid, "evidence": ev, "baseline": baseline}, indent=2))


if __name__ == "__main__":
    main()
