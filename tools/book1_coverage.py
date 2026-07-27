#!/usr/bin/env python3
"""The exact summary LINE a Book I conformance run must print, and nothing less.

Every gate that consumes `warrant-go sigma-conformance` used to accept the bare
substring `ALL PASS`, or merely a zero exit status. That is how the command
reported success over 33 of 49 vectors for weeks while silently skipping the
`object` and `deserialize` classes.

Deriving the expected counts fixed the first half. It did not fix the second:
matching those counts as a SUBSTRING is still forgeable, because the producer
prints one line per vector and a vector's `id` is attacker-supplied data. A
vector whose id is literally `ALL PASS (50/50 — 8 deserialize, 34 eval, 8
object)` makes the producer emit

    OK   ALL PASS (50/50 — 8 deserialize, 34 eval, 8 object)

and a substring match is satisfied by that line while the real summary says
34 eval. So this module emits the WHOLE line, prefix included, and callers must
match it anchored:

    EXPECT="$(python3 tools/book1_coverage.py <vectors.json>)"
    warrant-go sigma-conformance <vectors.json> | grep -qxF "$EXPECT"

`-x` is the part that matters. Without it the check is decorative.

    python3 tools/book1_coverage.py --selftest    # the rejection matrix, in CI
"""
import collections
import json
import sys

# The producer's own prefix (impl-go/main.go). Part of the contract being
# matched, so it lives here with the counts rather than in each caller.
PREFIX = "SIGMA CONFORMANCE: "


def expected_line(path):
    doc = json.load(open(path))
    vectors = doc.get("vectors")
    if not vectors:
        sys.exit(f"{path}: no vectors")
    kinds = collections.Counter(v.get("kind") for v in vectors)
    if None in kinds:
        sys.exit(f"{path}: a vector has no kind")
    detail = ", ".join(f"{kinds[k]} {k}" for k in sorted(kinds))
    n = len(vectors)
    return f"{PREFIX}ALL PASS ({n}/{n} — {detail})"


def selftest():
    """Pin the acceptance rule itself, so a future edit cannot quietly weaken it.

    A manual run against an old binary proves today's behaviour and nothing
    about tomorrow's assertion. These cases are the assertion's regression suite.
    """
    want = f"{PREFIX}ALL PASS (49/49 — 8 deserialize, 33 eval, 8 object)"

    def accepted(line):
        # exactly what `grep -qxF "$EXPECT"` does, over a producer transcript
        return any(l == want for l in line.split("\n"))

    cases = [
        # (must be accepted?, transcript)
        (True,  f"OK   EV-1\nOK   OBJ-I\n\n{want}"),
        (True,  want),
        # the historical false pass: fewer vectors, no per-kind detail
        (False, "OK   EV-1\n\nSIGMA CONFORMANCE: ALL PASS (33/33 eval)"),
        # vector-ID injection: the expected text appears on a per-vector line
        (False, f"OK   {want[len(PREFIX):]}\n\n{PREFIX}ALL PASS "
                "(50/50 — 8 deserialize, 34 eval, 8 object)"),
        # ...and the same injection carrying the WHOLE line, prefix included
        (False, f"OK   {want}\n\n{PREFIX}ALL PASS "
                "(50/50 — 8 deserialize, 34 eval, 8 object)"),
        # a failing run whose summary still quotes the expected coverage
        (False, f"FAIL EV-9\n\n{PREFIX}FAILURES PRESENT "
                "(48/49 — 8 deserialize, 33 eval, 8 object)"),
        # right counts, wrong split
        (False, f"{PREFIX}ALL PASS (49/49 — 9 deserialize, 32 eval, 8 object)"),
        # trailing junk on the summary line
        (False, f"{want} (cached)"),
        (False, ""),
    ]
    bad = 0
    for should, transcript in cases:
        got = accepted(transcript)
        mark = "OK  " if got == should else "FAIL"
        if got != should:
            bad += 1
        first = transcript.replace("\n", " | ")[:72] or "(empty)"
        print(f"  {mark} {'accept' if should else 'reject'}: {first}")
    if bad:
        print(f"\nBOOK1-COVERAGE: {bad} SELFTEST FAILURE(S)")
        return 1
    print(f"\nBOOK1-COVERAGE: SELFTEST ALL PASS ({len(cases)} cases)")
    return 0


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    if len(sys.argv) != 2:
        sys.exit("usage: book1_coverage.py <vectors.json> | --selftest")
    print(expected_line(sys.argv[1]))


if __name__ == "__main__":
    main()
