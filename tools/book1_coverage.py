#!/usr/bin/env python3
"""Decide whether a Book I conformance transcript really claims full coverage.

THE THREE DEFECTS THIS EXISTS TO CLOSE, in the order they were found — each one
survived the fix for the previous, which is why the check ended up here instead
of in a `grep`:

1. `grep -q "ALL PASS"`. `warrant-go sigma-conformance` once printed
   "ALL PASS (33/33 eval)" and exited 0 while skipping sigma's `object` and
   `deserialize` classes entirely. A success word is not a coverage claim.

2. Derived counts, matched as a SUBSTRING. The producer prints one line per
   vector and a vector's `id` is free-form data, so a vector named after the
   expected summary satisfies the match while the real summary says something
   else. A count is not evidence if the attacker can echo it back.

3. Derived counts, matched with `grep -qxF` — anchored to a whole line, but not
   to a POSITION. An id may contain newlines, so

       id = "\\nSIGMA CONFORMANCE: ALL PASS (50/50 — …)\\nFORGED-END"

   makes the producer emit the expected text as its own physical line, and the
   real summary ("34/34 eval") follows harmlessly below.

So the rule is positional and lives in one place: the expected summary must be
the LAST line of the transcript. Injected content is printed while vectors are
being replayed, i.e. always before the summary, so it cannot occupy that
position without the producer being the thing that is broken.

    warrant-go sigma-conformance "$V" | python3 tools/book1_coverage.py --check "$V"

Use it in a `pipefail` pipeline so the producer's own exit status is bound too.

    python3 tools/book1_coverage.py <vectors.json>   # print the expected line
    python3 tools/book1_coverage.py --check <v.json> # verify a transcript on stdin
    python3 tools/book1_coverage.py --selftest       # the rejection matrix
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


def check_transcript(transcript, expected):
    """True iff the transcript's LAST line is exactly the expected summary.

    This is the single decision procedure. CI, X1 and the selftest all call it,
    so a caller cannot drift back to a weaker rule without the selftest going
    red with it — the previous arrangement tested a Python helper while CI ran a
    shell `grep`, and loosening the grep would have left the suite green.
    """
    if not transcript.strip():
        return False
    lines = transcript.rstrip("\n").split("\n")
    return lines[-1] == expected


def selftest():
    """Pin the decision procedure itself, so a future edit cannot weaken it."""
    want = f"{PREFIX}ALL PASS (49/49 — 8 deserialize, 33 eval, 8 object)"
    forged = f"{PREFIX}ALL PASS (50/50 — 8 deserialize, 34 eval, 8 object)"
    real34 = f"{PREFIX}ALL PASS (34/34 eval)"

    cases = [
        (True,  f"OK   EV-1\nOK   OBJ-I\n\n{want}",              "true summary, last"),
        (True,  want,                                            "summary alone"),
        (True,  f"OK   EV-1\n\n{want}\n",                        "trailing newline"),
        (False, f"OK   EV-1\n\n{PREFIX}ALL PASS (33/33 eval)",   "historical false pass"),
        (False, f"OK   {want[len(PREFIX):]}\n\n{forged}",        "id injection: counts only"),
        (False, f"OK   {want}\n\n{forged}",                      "id injection: whole line"),
        # the newline-in-id forgery: the expected text IS its own physical line,
        # but the producer's real summary is what ends the transcript
        (False, f"OK\n{want}\nFORGED-END\n\n{real34}",           "id injection: embedded newline"),
        # ...and the same forgery where nothing follows but blank lines
        (False, f"OK\n{want}\nFORGED-END\n",                     "forged line, junk after"),
        (False, f"FAIL EV-9\n\n{PREFIX}FAILURES PRESENT "
                "(48/49 — 8 deserialize, 33 eval, 8 object)",    "failing run quoting coverage"),
        (False, f"{PREFIX}ALL PASS (49/49 — 9 deserialize, 32 eval, 8 object)",
                                                                 "wrong per-kind split"),
        (False, f"{want} (cached)",                              "trailing junk on the summary"),
        (False, f"{want}\nsomething after",                      "summary not last"),
        (False, "",                                              "empty transcript"),
    ]
    bad = 0
    for should, transcript, name in cases:
        got = check_transcript(transcript, want)
        if got != should:
            bad += 1
        print(f"  {'OK  ' if got == should else 'FAIL'} "
              f"{'accept' if should else 'reject'}: {name}")
    if bad:
        print(f"\nBOOK1-COVERAGE: {bad} SELFTEST FAILURE(S)")
        return 1
    print(f"\nBOOK1-COVERAGE: SELFTEST ALL PASS ({len(cases)} cases)")
    return 0


def main():
    args = sys.argv[1:]
    if args == ["--selftest"]:
        sys.exit(selftest())
    if len(args) == 2 and args[0] == "--check":
        want = expected_line(args[1])
        transcript = sys.stdin.read()
        if check_transcript(transcript, want):
            print(f"BOOK1-COVERAGE: {want}")
            sys.exit(0)
        tail = transcript.rstrip("\n").split("\n")[-3:]
        print("BOOK1-COVERAGE: MISMATCH\n"
              f"  expected as the LAST line: {want}\n"
              "  transcript ended with:\n" +
              "\n".join(f"    | {t}" for t in tail), file=sys.stderr)
        sys.exit(1)
    if len(args) == 1 and not args[0].startswith("-"):
        print(expected_line(args[0]))
        return
    sys.exit("usage: book1_coverage.py <vectors.json> | --check <vectors.json> | --selftest")


if __name__ == "__main__":
    main()
