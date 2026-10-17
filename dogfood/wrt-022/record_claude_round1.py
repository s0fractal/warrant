#!/usr/bin/env python3
"""Claude's own events for the WRT-022 review of 6fa8cb8, filed once, on 2026-10-18,
when they were made. Kept for audit: running it again files NEW records with new
timestamps. It never signs for anyone else.

    WRT022_KEY=<claude's key> python3 dogfood/wrt-022/record_claude_round1.py <codex-review-of-6fa8cb8.md>

1. Seven duties, R22-01..R22-07: Claude holds them, owes them to Codex, and
   Codex's acceptance is required. Scoped to the reviewed revision 6fa8cb8.
2. A parent duty for the round, whose closure condition names the seven.
3. One transition: revision 2 of the proposal, attested, closing all eight, each
   mapping with a subject_changed trigger over the proposal file at 4e2fe26.
4. The open S1 duty.
Codex's acceptances are Codex's events: `events.py accept --actor codex@warrant-wrt022`.
"""
import sys
from pathlib import Path

import events as E

sys.path.insert(0, str(E.ROOT / "impl"))
import loops as L      # noqa: E402
import triggers as TR  # noqa: E402

REVIEWED = "6fa8cb84433510b42f77cd0b988dddf6c305ec9a"     # WRT-022 rev 1, Codex AMEND
REV2 = "4e2fe26b6cc02414f9851617817cb676ec59a570"         # rev 2 (cherry-pick of 410a048, same bytes)
PROPOSAL = "proposals/WRT-022-authority-falsifiers-crossings.md"
FINDINGS = {
    "R22-01": "a rooted grant chain needs attenuation and an actual authority root",
    "R22-02": "falsifier coverage is not completeness or future reliability",
    "R22-03": "announced falsifiers cannot monopolize challenges; new children need authority",
    "R22-04": "tier policy cannot replace the kinds of evidence with a universal ladder",
    "R22-05": "a norm being in force differs from known compliance",
    "R22-06": "joint checkpoints must bind a pre-action shared view without self-reference",
    "R22-07": "imported claim types need orthogonal roles and lifecycle",
}


def main():
    # Sonar S8707: the owner names the review file to import; reading it is this
    # one-off script's purpose, with no confinement root or remote input (Codex,
    # review of 81f11fe2).
    review = Path(sys.argv[1]).read_bytes()  # NOSONAR
    s = E.store()
    review_blob = s.put_blob(review)
    rev2_blob = s.put_blob(E.subprocess.run(["git", "-C", str(E.ROOT), "show", f"{REV2}:{PROPOSAL}"],
                                            capture_output=True, check=True).stdout)
    baseline = s.put_blob(L.canon(TR.build(E.ROOT, REV2, [PROPOSAL])))
    admits = [["DISCHARGED", "ATTESTED"]]

    def open_duty(statement, **kw):
        d = L.duty(E.CLAUDE, [E.CODEX], statement, kw.pop("scope", REVIEWED), admits, acceptance=[E.CODEX], **kw)
        return E.file(s, "propose", s.put_blob(L.canon(d)), E.CLAUDE, prior=kw.get("serves", ()), note="duty")

    children = [open_duty(f"{rid}: {text}") for rid, text in FINDINGS.items()]
    parent = open_duty("answer Codex's design review of WRT-022 at 6fa8cb8 (R22-01..R22-07)",
                       closure_requires=children)
    trig = [{"kind": "subject_changed", "baseline": baseline}]
    closes = [L.mapping(d, "DISCHARGED", [rev2_blob], triggers=trig) for d in children + [parent]]
    t = L.transition("ATTESTED", [rev2_blob], closes=closes, relied_on=[review_blob], addresses=children + [parent],
                     not_established=["that the revised contracts hold once implemented: S1-S8 test that"],
                     scope_subject=REV2)
    tid = E.file(s, "propose", s.put_blob(L.canon(t)), E.CLAUDE, prior=children + [parent], note="transition")
    s1 = open_duty("implement WRT-022 S1: scoped tri-state triggers, reliance for a named use, this store",
                   scope=REV2)
    print(f"duties {len(children) + 1}, transition {tid[:12]}, S1 duty {s1[:12]}")


if __name__ == "__main__":
    main()
