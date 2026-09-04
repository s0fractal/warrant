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


def load_pack_shape():
    """Per-(class, grade) vector and MUST-REJECT counts, plus the derived totals.

    `docs/conformance.html` is the page a stranger reads INSTEAD of this
    repository, and it restates the whole pack as a table. A table is nine
    hand-copied numbers next to a thing that moves whenever a vector is added,
    which is this repository's most-repeated defect with more places to occur.
    So the page is compared to the pack row by row, not just on its totals: a
    row that goes stale, and a row that disappears entirely, are both findings.

    `capabilities` carries no vectors — it is the mandatory declaration class —
    so the class NAMES are counted from the grade lists plus that one, while the
    rows are counted from the vector files.
    """
    import json
    vdir = ROOT / "conformance" / "vectors"
    index = json.loads((vdir / "index.json").read_text(encoding="utf-8"))
    rows, base_total = {}, 0
    for entry in index["files"]:
        doc = json.loads((vdir / entry["file"]).read_text(encoding="utf-8"))
        neg = sum(1 for v in doc["vectors"] if v["polarity"] == "negative")
        rows[(entry["class"], entry["grade"])] = (entry["vectors"], neg)
        if entry["grade"] == "base":
            base_total += entry["vectors"]
    classes = set(index["grades"]["base"]) | set(index["grades"]["settlement"])
    return rows, base_total, len(classes) + 1        # + the mandatory declaration


CONTRACT_PAGE = "docs/conformance.html"

# One row of the class table on the contract page. The prose cell is not read.
PAGE_ROW = re.compile(
    r'<tr><td><code>([a-z-]+)</code></td><td>([a-z]+)</td>'
    r'<td class="n">(\d+)</td><td class="n">(\d+)</td>')


def check_contract_page(rows):
    """The published class table must equal the pack it describes."""
    failures = []
    text = read(CONTRACT_PAGE)
    found = {(c, g): (int(v), int(n)) for c, g, v, n in PAGE_ROW.findall(text)}

    if "<code>capabilities</code>" not in text:
        failures.append(
            f"{CONTRACT_PAGE}: the mandatory `capabilities` class has no row; "
            f"a candidate that never declares its grade cannot be tested at one")

    for key in sorted(rows):
        cls, grade = key
        if key not in found:
            failures.append(
                f"{CONTRACT_PAGE}: no row for `{cls}` at {grade} grade, which the "
                f"pack has ({rows[key][0]} vectors) -- the page under-reports the "
                f"work by a whole class")
        elif found[key] != rows[key]:
            failures.append(
                f"{CONTRACT_PAGE}: `{cls}` ({grade}) is written as "
                f"{found[key][0]} vectors / {found[key][1]} MUST-REJECT, the pack "
                f"has {rows[key][0]} / {rows[key][1]}")
    for key in sorted(found):
        if key not in rows:
            failures.append(
                f"{CONTRACT_PAGE}: has a row for `{key[0]}` at {key[1]} grade, "
                f"which is not a class in conformance/vectors/index.json")
    return failures


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
    # docs/conformance.html is served on GitHub Pages and is written to be read
    # INSTEAD of the repository, so its numbers are the ones a stranger acts on
    # and the ones nothing was counting until they were listed here.
    (CONTRACT_PAGE, "conformance vector total",
     r"The other \w+ carry\s+the (\d+) vectors", "vectors"),
    (CONTRACT_PAGE, "count of MUST-REJECT vectors",
     r"<strong>(\d+) of the \d+ vectors are MUST-REJECT", "negatives"),
    (CONTRACT_PAGE, "vector total beside the MUST-REJECT count",
     r"<strong>\d+ of the (\d+) vectors are MUST-REJECT", "vectors"),
    (CONTRACT_PAGE, "MUST-REJECT count in the permissive-implementation banner",
     r"PERMISSIVE IMPLEMENTATION: (\d+) of \d+ MUST-REJECT", "negatives"),
    (CONTRACT_PAGE, "MUST-REJECT total in the permissive-implementation banner",
     r"PERMISSIVE IMPLEMENTATION: \d+ of (\d+) MUST-REJECT", "negatives"),
    (CONTRACT_PAGE, "count of refused inputs in what-you-get",
     r"on the (\d+) inputs that must be refused", "negatives"),
    (CONTRACT_PAGE, "vector total in the honest-state note",
     r"each pass all (\d+) vectors at settlement grade", "vectors"),
    (CONTRACT_PAGE, "base-grade vector total",
     r"passes the (\d+) base vectors", "base_vectors"),
    (CONTRACT_PAGE, "vector total in the per-vector spawn cost",
     r"spawns your candidate (\d+) times", "vectors"),
    # The landing page carries the same two numbers in its pitch to an
    # implementer. Same page, same rot, same gate.
    ("docs/index.html", "conformance vector total",
     r"(\d+) vectors, \d+ of them MUST-REJECT", "vectors"),
    ("docs/index.html", "count of MUST-REJECT vectors",
     r"\d+ vectors, (\d+) of them MUST-REJECT", "negatives"),
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
    (CONTRACT_PAGE, "worded count of contract classes",
     r"<h2>The (\w+) classes</h2>", "classes"),
    (CONTRACT_PAGE, "worded count of vector-carrying classes",
     r"The other (\w+) carry", "vector_classes"),
]


def check_mcp_ownership_marker(server_name):
    """README.md must carry the marker the MCP Registry checks PyPI ownership with.

    Ported from the registry's own source rather than from its prose
    (`internal/validators/registries/mcpname.go` on `main`): the token is the
    literal `mcp-name: <server-name>` with EXACTLY one space after the colon,
    and what follows it must be a boundary — end of content, any character
    outside `[A-Za-z0-9._/-]`, or the start of `-->` / `--!>`. A trailing period
    glued to the name is therefore not a match, which is the documented way to
    get this wrong.

    The registry reads the README **as published to PyPI** (`info.description`
    of the version-specific metadata), so a marker deleted here does not fail
    the publish to PyPI — it fails the registry publish afterwards, for a
    release that has already shipped. Checking the source file is the last point
    at which that is cheap. Nothing here touches the network.
    """
    if not server_name:
        return ["integrations/mcp-server/server.json: no `name` — nothing to "
                "match an ownership marker against"]

    def is_name_char(c):
        return c.isascii() and (c.isalnum() or c in "._-/")

    def is_boundary(rest):
        if not rest or not is_name_char(rest[0]):
            return True
        return rest.startswith("-->") or rest.startswith("--!>")

    content, token, i = read("README.md"), f"mcp-name: {server_name}", 0
    while True:
        j = content.find(token, i)
        if j < 0:
            return [f"README.md: no `{token}` token followed by a boundary. The "
                    f"MCP Registry reads this file as the PyPI package "
                    f"description and refuses the packages block without it — "
                    f"put it on its own line, or inside `<!-- … -->`, and do not "
                    f"glue a period to the name"]
        if is_boundary(content[j + len(token):]):
            return []
        i = j + 1


def check_release_versions():
    """The distribution version, written in four places, must be one number.

    The two documents that say which release is current are held to it too
    (`check_current_release_prose`).

    Shipping the MCP server created three new copies of it: the module's
    `__version__` (which the server reports to its host as `serverInfo`), and
    both version fields of the registry manifest — the server version and the
    PyPI version inside `packages`. The registry fetches
    `pypi.org/pypi/warrant-verify/<that version>/json`, so a manifest whose
    number lags the release does not merely read wrong: it points the whole
    listing at a different artifact, or at a 404.

    This is defect class 8 with an audience outside the repository, which is why
    it is counted here rather than trusted.
    """
    import json

    failures = []
    pyproject = read("pyproject.toml")
    m = re.search(r'(?m)^version = "([^"]+)"', pyproject)
    if m is None:
        return ["pyproject.toml: no `version = \"…\"` line found"]
    dist = m.group(1)

    mod = read("impl/warrant_mcp_server.py")
    m = re.search(r'(?m)^__version__ = "([^"]+)"', mod)
    if m is None:
        failures.append("impl/warrant_mcp_server.py: no `__version__` line — the "
                        "server would report an unknown version to its host")
    elif m.group(1) != dist:
        failures.append(f"impl/warrant_mcp_server.py: __version__ is "
                        f"{m.group(1)}, pyproject.toml version is {dist}")

    manifest_path = ROOT / "integrations" / "mcp-server" / "server.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        return failures + [f"integrations/mcp-server/server.json: unreadable ({ex})"]

    if manifest.get("version") != dist:
        failures.append(f"integrations/mcp-server/server.json: version is "
                        f"{manifest.get('version')!r}, pyproject.toml version "
                        f"is {dist}")
    failures += check_mcp_ownership_marker(manifest.get("name"))

    pkgs = [p for p in manifest.get("packages") or []
            if p.get("registryType") == "pypi"]
    if not pkgs:
        failures.append("integrations/mcp-server/server.json: no pypi `packages` "
                        "entry — the listing offers no install path but a clone")
    for p in pkgs:
        if p.get("identifier") != "warrant-verify":
            failures.append(f"integrations/mcp-server/server.json: pypi identifier "
                            f"is {p.get('identifier')!r}, not `warrant-verify`")
        if p.get("version") != dist:
            failures.append(f"integrations/mcp-server/server.json: pypi package "
                            f"version is {p.get('version')!r}, pyproject.toml "
                            f"version is {dist} — the registry would resolve a "
                            f"different release, or none")
    failures += check_current_release_prose(dist)
    return failures


# Where the documents say which release is current. Each is a prose twin of
# `pyproject.toml`: CHANGELOG.md's version table row for the tooling number, and
# PUBLISHING.md's "current release(d) version" sentence. Both still said 0.6.0
# after 0.9.0 had shipped, because nothing compared them to anything.
CURRENT_RELEASE_PROSE = (
    ("CHANGELOG.md", "release tag / PyPI table row",
     r"(?m)^\| release tag / PyPI \|.*$"),
    ("PUBLISHING.md", "current release sentence",
     r"(?im)^.*\bcurrent releas.*$"),
)


def check_current_release_prose(dist):
    """A document that names the current release must name pyproject's number.

    The sentence is allowed to point at `pyproject.toml` / PyPI instead of
    quoting a number (that is the preferred form: nothing to go stale). What it
    must not do is quote a different number, and it must still exist -- a
    phrasing that disappears is reported, not passed.
    """
    failures = []
    for fname, desc, pattern in CURRENT_RELEASE_PROSE:
        lines = re.findall(pattern, read(fname))
        if not lines:
            failures.append(f"{fname}: MISSING claim ({desc}) -- pattern no "
                            f"longer matches, so nothing is checking it")
            continue
        for line in lines:
            for num in re.findall(r"\b\d+\.\d+\.\d+\b", line):
                if num != dist:
                    failures.append(f"{fname}: {desc} names {num}, pyproject.toml "
                                    f"version is {dist}")
    return failures


def main():
    tm = read("THREAT-MODEL.md")
    sa_headings = re.findall(r"^#### SA-(\d+)\.", tm, re.M)
    ng_headings = re.findall(r"^- \*\*NG-(\d+)\.", tm, re.M)

    pack_total, pack_negatives = load_pack_counts()
    pack_rows, base_total, class_count = load_pack_shape()
    truth = {
        "checks": load_checks(),
        "sa": len(sa_headings),
        "ng": len(ng_headings),
        "vectors": pack_total,
        "negatives": pack_negatives,
        "base_vectors": base_total,
        "classes": class_count,
        # every class except the mandatory `capabilities` declaration
        "vector_classes": class_count - 1,
    }
    where = {
        "checks": "len(CHECKS) in tools/check.py",
        "sa": "`#### SA-n.` headings in THREAT-MODEL.md",
        "ng": "`- **NG-n.`` items in THREAT-MODEL.md",
        "vectors": "total_vectors in conformance/vectors/index.json",
        "negatives": "vectors with polarity=negative in conformance/vectors/",
        "base_vectors": "base-grade vectors in conformance/vectors/index.json",
        "classes": "grades.* in conformance/vectors/index.json, plus capabilities",
        "vector_classes": "the same, minus capabilities",
    }

    failures = check_contract_page(pack_rows)
    version_failures = check_release_versions()
    failures += version_failures

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

    # +5 for the listing identities: the release-version identities (module
    # __version__, manifest version, manifest pypi identifier, manifest pypi
    # version) against pyproject.toml, plus README.md's MCP ownership marker;
    # then one per document whose current-release prose is held to pyproject.
    n = (len(CLAIMS) + len(WORD_CLAIMS) + len(pack_rows) + 3 + 5
         + len(CURRENT_RELEASE_PROSE))
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
