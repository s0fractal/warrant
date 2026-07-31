#!/usr/bin/env python3
"""Every count a document states about this repository must equal the thing it counts.

WHY THIS EXISTS
---------------
Two branches merged cleanly and both were wrong afterwards. `feat/domain-separation`
added two entries to `tools/check.py` and removed one; `feat/policy-frontend` added
one. Neither touched the sentence in `llms.txt` that says how many there are, so
each branch was off by one on its own and the merge was off by two -- while every
suite stayed green, because nothing compared the sentence to the list.

The same shape produced SA-11: `THREAT-MODEL.md` promises that a limit stated
anywhere else is also stated there, and `llms.txt` and `SECURITY.md` both quote a
count of scoped assumptions. A new assumption falsifies two sentences in files
nobody edited.

So this is not a style check. A document that says "all 30 checks" when 33 run is
the recurring defect of this repository in miniature: a claim about coverage,
maintained by hand, next to the thing that actually moved.

WHAT IT DOES NOT DO
-------------------
It compares numbers, and only the numbers written in the exact phrasings below.
It cannot tell whether a check is meaningful, whether an SA is accurate, or
whether a document that states no count is complete. A phrasing that disappears
is reported as a missing claim rather than passing silently -- a guard that goes
quiet when its subject is renamed is the failure mode it exists to prevent.

USAGE
    python3 tools/doc_counts.py
"""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_checks():
    spec = importlib.util.spec_from_file_location("_check", ROOT / "tools" / "check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return len(mod.CHECKS)


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def load_pack_counts():
    """How many conformance vectors there are, and how many are MUST-REJECT.

    Counted from the built pack, not from a constant: the pack is generated from
    `examples/`, so adding one negative vector upstream moves this number and
    every sentence quoting it. The negative count is the one that matters — it is
    the claim that the pack can tell a verifier apart from a program that returns
    true, and it is quoted in three documents.
    """
    import json
    vdir = ROOT / "conformance" / "vectors"
    index = json.loads((vdir / "index.json").read_text(encoding="utf-8"))
    negatives = 0
    for entry in index["files"]:
        doc = json.loads((vdir / entry["file"]).read_text(encoding="utf-8"))
        negatives += sum(1 for v in doc["vectors"] if v["polarity"] == "negative")
    return index["total_vectors"], negatives


# (file, human description, regex with ONE capturing group holding the number)
# Each pattern is anchored on wording specific enough that it cannot match a
# different sentence; if the wording changes, the claim is reported MISSING.
CLAIMS = [
    ("llms.txt", "count of tools/check.py checks",
     r"runs all (\d+) checks the repository's claims rest on", "checks"),
    ("SECURITY.md", "count of tools/check.py checks",
     r"python3 tools/check\.py\s+# (\d+) checks, one verdict", "checks"),
    ("llms.txt", "count of scoped assumptions",
     r"scoped assumptions \(`SA-1` … `SA-(\d+)`\)", "sa"),
    ("SECURITY.md", "count of scoped assumptions",
     r"assumptions \(`SA-1` … `SA-(\d+)`\)", "sa"),
    ("llms.txt", "count of explicit non-goals",
     r"non-goals\n\(`NG-1` … `NG-(\d+)`\)", "ng"),
    ("SECURITY.md", "count of explicit non-goals",
     r"non-goals \(`NG-1` … `NG-(\d+)`\)", "ng"),
    ("README.md", "count of conformance vectors",
     r'--candidate "\./your-verifier probe"\s+# (\d+) vectors', "vectors"),
    ("README.md", "count of MUST-REJECT conformance vectors",
     r"answer\. (\d+)\nof the \d+ vectors are MUST-REJECT", "negatives"),
    ("README.md", "conformance vector total beside the MUST-REJECT count",
     r"of the (\d+) vectors are MUST-REJECT", "vectors"),
    ("llms.txt", "count of conformance vectors",
     r"\n(\d+) vectors, \d+ of them MUST-REJECT", "vectors"),
    ("llms.txt", "count of MUST-REJECT conformance vectors",
     r"\n\d+ vectors, (\d+) of them MUST-REJECT", "negatives"),
    ("conformance/README.md", "count of MUST-REJECT conformance vectors",
     r"carry equal weight\.\*\* (\d+) of the \d+ vectors are MUST-REJECT",
     "negatives"),
    ("conformance/README.md", "conformance vector total",
     r"carry equal weight\.\*\* \d+ of the (\d+) vectors are MUST-REJECT",
     "vectors"),
]

# The same two counts are also written as English words beside the numerals.
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
         7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
         12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen"}

WORD_CLAIMS = [
    ("llms.txt", "worded count of scoped assumptions",
     r"\n(\w+) scoped assumptions \(`SA-1`", "sa"),
    ("SECURITY.md", "worded count of scoped assumptions",
     r"as (\w+) scoped\nassumptions \(`SA-1`", "sa"),
    ("llms.txt", "worded count of explicit non-goals",
     r"and (\w+) explicit non-goals", "ng"),
    ("SECURITY.md", "worded count of explicit non-goals",
     r"and (\w+) explicit non-goals", "ng"),
]


def main():
    tm = read("THREAT-MODEL.md")
    sa_headings = re.findall(r"^#### SA-(\d+)\.", tm, re.M)
    ng_headings = re.findall(r"^- \*\*NG-(\d+)\.", tm, re.M)

    pack_total, pack_negatives = load_pack_counts()
    truth = {
        "checks": load_checks(),
        "sa": len(sa_headings),
        "ng": len(ng_headings),
        "vectors": pack_total,
        "negatives": pack_negatives,
    }
    where = {
        "checks": "len(CHECKS) in tools/check.py",
        "sa": "`#### SA-n.` headings in THREAT-MODEL.md",
        "ng": "`- **NG-n.`` items in THREAT-MODEL.md",
        "vectors": "total_vectors in conformance/vectors/index.json",
        "negatives": "vectors with polarity=negative in conformance/vectors/",
    }

    failures = []

    # THREAT-MODEL's own numbering must be dense and start at 1, otherwise a
    # count is not the same fact as the highest label the documents cite.
    for label, found in (("SA", sa_headings), ("NG", ng_headings)):
        nums = [int(n) for n in found]
        if nums != list(range(1, len(nums) + 1)):
            failures.append(
                f"THREAT-MODEL.md: {label} numbering is {nums}, expected "
                f"1..{len(nums)} with no gaps or repeats")

    for fname, desc, pattern, key in CLAIMS:
        m = re.search(pattern, read(fname))
        if m is None:
            failures.append(
                f"{fname}: MISSING claim ({desc}) -- pattern no longer matches, "
                f"so nothing is checking it")
            continue
        stated = int(m.group(1))
        if stated != truth[key]:
            failures.append(
                f"{fname}: {desc} says {stated}, {where[key]} is {truth[key]}")

    for fname, desc, pattern, key in WORD_CLAIMS:
        m = re.search(pattern, read(fname))
        if m is None:
            failures.append(
                f"{fname}: MISSING claim ({desc}) -- pattern no longer matches, "
                f"so nothing is checking it")
            continue
        stated = m.group(1)
        expected = WORDS.get(truth[key])
        if expected is None:
            failures.append(
                f"{fname}: {desc} is {truth[key]}, which this check has no word for")
        elif stated != expected:
            failures.append(
                f"{fname}: {desc} says '{stated}', {where[key]} is "
                f"{truth[key]} ('{expected}')")

    n = len(CLAIMS) + len(WORD_CLAIMS) + 2
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        print(f"DOC-COUNTS: {len(failures)}/{n} FAILED")
        return 1
    print(f"DOC-COUNTS: ALL PASS ({n} claims; "
          f"checks={truth['checks']} SA={truth['sa']} NG={truth['ng']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
