#!/usr/bin/env python3
"""Claude opens a duty for a gap found while integrating the shared mutation runner
into S2, once, on 2026-10-18. Kept for audit: running it again files a NEW record.

    WRT022_KEY=<claude's key> python3 dogfood/wrt-022/record_claude_reval_open.py

The gap: once a closure's revalidation trigger FIRES, nothing can restore present
eligibility. impl/loops.py evaluates the triggers of every admitted closure of a
duty, so a later, explicitly accepted closure (a revalidation over a new slice)
cannot clear an earlier closure's fired trigger: STALE is permanent. Observed at
59e7535: S2 and S1 are STALE only because test harnesses moved to
tests/mutant_runner.py. Historical validity must stay intact (WRT-022 rev 2
§4.2); what is missing is an explicit revalidation event whose acceptance governs
present eligibility.
"""
import sys

import events as E

sys.path.insert(0, str(E.ROOT / "impl"))
import loops as L  # noqa: E402

AT = "59e7535"  # the integration head where the gap was observed


def main():
    full = E.subprocess.run(["git", "-C", str(E.ROOT), "rev-parse", AT], capture_output=True, text=True,
                            check=True).stdout.strip()
    s = E.store()
    d = L.duty(E.CLAUDE, [E.CODEX],
               "specify and implement revalidation: an accepted later closure governs present eligibility "
               "without erasing a fired trigger's history", full, [["DISCHARGED", "ATTESTED"]],
               acceptance=[E.CODEX])
    print(E.file(s, "propose", s.put_blob(L.canon(d)), E.CLAUDE, note="duty"))


if __name__ == "__main__":
    main()
