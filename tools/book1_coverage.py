#!/usr/bin/env python3
"""Print the exact conformance summary a Book I vector file must produce.

Every gate that consumes `warrant-go sigma-conformance` used to accept the bare
substring `ALL PASS`, or merely a zero exit status. That is how the command
reported success over 33 of 49 vectors for weeks while silently skipping the
`object` and `deserialize` classes: a summary line is evidence only if the number
in it is checked against the suite it claims to cover.

So the expected line is DERIVED from the vector file the job actually pins, and
the job requires a literal match:

    EXPECT="$(python3 tools/book1_coverage.py <vectors.json>)"
    warrant-go sigma-conformance <vectors.json> | grep -qF "$EXPECT"

Adding a vector, or a whole new kind, tightens the assertion automatically
instead of loosening it -- which is the property that was missing.
"""
import collections
import json
import sys


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: book1_coverage.py <vectors.json>")
    doc = json.load(open(sys.argv[1]))
    vectors = doc.get("vectors")
    if not vectors:
        sys.exit(f"{sys.argv[1]}: no vectors")
    kinds = collections.Counter(v.get("kind") for v in vectors)
    if None in kinds:
        sys.exit(f"{sys.argv[1]}: a vector has no kind")
    detail = ", ".join(f"{kinds[k]} {k}" for k in sorted(kinds))
    print(f"ALL PASS ({len(vectors)}/{len(vectors)} — {detail})")


if __name__ == "__main__":
    main()
