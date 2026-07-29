#!/usr/bin/env python3
"""Resolve every document this repository names, and say where it actually is.

WHY THIS EXISTS
---------------
Four separate reviews in three days produced findings that were artefacts of not
knowing what was being looked at:

  * "the X1 files are missing from warrant" -- they were on master; the reviewer
    was reading a working tree parked on a feature branch;
  * "warrant-go prints 33/33" -- it prints 49/49; the reviewer read an archived
    evidence blob from an old run;
  * "the sibling pin is three weeks stale" -- it was same-day;
  * "ADR-008 lives only on unpushed branches, so this is a dangling reference" --
    it is on a pushed branch, publicly readable, just not on master.

The last one is the honest core of the class: `master` names ADR-008 six times,
ADR-004 twice and WRT-002 once, and none of them resolve here. A reader is left
to guess whether the document is missing, renamed, secret, or somewhere else --
and every reviewer guessed differently.

None of those were careless reviewers. They were reviewers without a map.

This generates the map from git, so it cannot drift the way a hand-written
inventory does -- two hand-written counts in this repository were wrong by 25
conformance vectors and one whole PyPI release until 2026-07-29.

WHAT IT DOES NOT DO
-------------------
It reports *where a document is*, never whether it is adopted, correct, or in
force. Location is a fact about git; status is a fact about governance, and
conflating the two is how "present on a branch" becomes "in effect".

USAGE
    python3 tools/repo_map.py            # write MAP.md
    python3 tools/repo_map.py --check    # non-zero if any reference resolves nowhere
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIBLING = ROOT.parent / ("sigma-glyph" if ROOT.name == "warrant" else "warrant")

# Identifiers this project cites as if the reader knows where they live.
ID_RE = re.compile(r"\b(ADR-\d{3}|WRT-\d{3}|GOV-\d{3}|Book\s+(?:I{1,3}))\b")

# Identifiers whose filename does not contain the citation string. "Book I" is
# cited nine times in this repository and lives in a file called
# book-1-truth.md, so a substring search finds nothing and would report the most
# heavily cited document in the project as resolving nowhere.
ALIASES = {"Book I": "book-1", "Book II": "book-2", "Book III": "book-3"}
SCAN = ("SPEC.md", "README.md", "ARCHITECT.md", "ROADMAP.md")
SCAN_DIRS = ("proposals", "briefs", "spec", "profiles")


def git(repo, *args, ok_fail=False):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    if r.returncode and not ok_fail:
        return ""
    return r.stdout


def refs_of(repo):
    """Local branches plus everything on origin, newest-looking first."""
    out = []
    for line in git(repo, "for-each-ref", "--format=%(refname:short)",
                    "refs/heads", "refs/remotes/origin").splitlines():
        if line and not line.endswith("/HEAD"):
            out.append(line)
    # master first: if a document is on the trunk that is the answer worth giving
    out.sort(key=lambda r: (r.split("/")[-1] != "master", r))
    return out


def find(repo, ident):
    """Every (ref, path) where a document with this identifier exists."""
    ident = ALIASES.get(" ".join(ident.split()), ident)
    hits = []
    seen_paths = set()
    for ref in refs_of(repo):
        matches = [p for p in git(repo, "ls-tree", "-r", "--name-only", ref).splitlines()
                   if ident.lower() in p.lower()]
        # Prefer the normative text over a translation of it. `Book I` matched
        # book-1-truth.en.md, the informative English rendering, and pointing a
        # reviewer at a translation while calling it the citation target is the
        # same ambiguity this file exists to remove.
        matches.sort(key=lambda p: (".en." in p, "/archive/" in p, len(p)))
        for path in matches:
            if path not in seen_paths:
                hits.append((ref, path))
                seen_paths.add(path)
    return hits


def cited(repo):
    """Identifiers named by this repository's own normative and proposal text."""
    ids = {}
    files = [f for f in SCAN if (repo / f).exists()]
    for d in SCAN_DIRS:
        if (repo / d).is_dir():
            files += [str(p.relative_to(repo)) for p in (repo / d).rglob("*.md")]
    for f in files:
        try:
            text = (repo / f).read_text(errors="replace")
        except OSError:
            continue
        for m in ID_RE.findall(text):
            ids.setdefault(" ".join(m.split()), set()).add(f)
    return ids


def resolve(ident):
    here = find(ROOT, ident)
    there = find(SIBLING, ident) if SIBLING.exists() else []
    return here, there


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="non-zero if a citation resolves on no known ref; "
                         "needs the sibling repository checked out")
    ap.add_argument("--check-map", action="store_true",
                    help="non-zero if a citation is absent from the committed "
                         "MAP.md; works without the sibling, so CI can run it")
    args = ap.parse_args()

    head = git(ROOT, "rev-parse", "HEAD").strip()
    origin = git(ROOT, "remote", "get-url", "origin").strip()
    ids = cited(ROOT)

    rows, unresolved = [], []
    for ident in sorted(ids):
        here, there = resolve(ident)
        if here:
            ref, path = here[0]
            where = f"this repo, `{ref}`", f"`{path}`"
        elif there:
            ref, path = there[0]
            where = f"**{SIBLING.name}**, `{ref}`", f"`{path}`"
        else:
            where = ("**resolves nowhere**", "—")
            unresolved.append(ident)
        rows.append((ident, where[0], where[1], sorted(ids[ident])[0]))

    if args.check_map:
        # CI has no sibling checkout, so it cannot re-resolve cross-repo
        # citations. It can still demand that every citation be ACCOUNTED FOR in
        # the committed map: a new reference to a document nobody has located is
        # exactly the defect, and it shows up as an entry missing from MAP.md.
        #
        # Written this way because the first attempt wired `--check || true` into
        # the workflow, which is a step that cannot fail -- the same
        # covering-less-than-it-claims shape this repository has spent three days
        # removing, nearly added to CI by the person removing it.
        mp = ROOT / "MAP.md"
        if not mp.exists():
            print("MAP.md is missing; run tools/repo_map.py", file=sys.stderr)
            return 1
        text = mp.read_text()
        missing = [i for i in sorted(ids) if f"`{i}`" not in text]
        for i in missing:
            print(f"UNMAPPED: {i} is cited but has no row in MAP.md -- "
                  f"regenerate with tools/repo_map.py", file=sys.stderr)
        stale = [ln for ln in text.splitlines() if "resolves nowhere" in ln]
        for ln in stale:
            print(f"UNRESOLVED in MAP.md: {ln.strip()}", file=sys.stderr)
        print(f"REPO-MAP: {len(ids) - len(missing)}/{len(ids)} citations mapped, "
              f"{len(stale)} unresolved")
        return 1 if missing or stale else 0

    if args.check:
        for ident in unresolved:
            print(f"UNRESOLVED: {ident} is cited but exists in neither repository "
                  f"on any local or origin ref", file=sys.stderr)
        print(f"REPO-MAP: {len(rows) - len(unresolved)}/{len(rows)} references resolve")
        return 1 if unresolved else 0

    out = [
        "# Map — where the documents this repository names actually live",
        "",
        "<!-- GENERATED by tools/repo_map.py. Do not edit; regenerate. -->",
        "",
        f"Repository `{origin}`, generated at commit `{head[:12]}`.",
        "",
        "This answers one question and only one: **given a document identifier",
        "cited somewhere in this repository, which ref holds it.** It says nothing",
        "about whether that document is adopted, correct, or in force — location is",
        "a fact about git, status is a fact about governance, and treating the",
        "first as the second is how \"present on a branch\" turns into \"in effect\".",
        "",
        "If you are reviewing this project: check the ref before reporting anything",
        "absent. Four reviews in three days reported things missing that were",
        "present on a ref the reviewer was not looking at.",
        "",
        "| Cited | Lives in | Path | First cited by |",
        "|---|---|---|---|",
    ]
    for ident, where, path, by in rows:
        out.append(f"| `{ident}` | {where} | {path} | `{by}` |")

    out += [
        "",
        "## Refs that exist",
        "",
        "A branch is not the trunk. Anything below that is not `master` is a",
        "candidate: readable, citable, and **not in force**.",
        "",
        "| Ref | Head | On origin |",
        "|---|---|---|",
    ]
    remote = {r.split("/", 1)[1] for r in refs_of(ROOT) if r.startswith("origin/")}
    for ref in refs_of(ROOT):
        if ref.startswith("origin/"):
            continue
        sha = git(ROOT, "rev-parse", "--short", ref).strip()
        out.append(f"| `{ref}` | `{sha}` | {'yes' if ref in remote else '**no**'} |")

    if unresolved:
        out += ["", "## Cited and resolving nowhere", "",
                "These are named by this repository and exist in neither repository",
                "on any ref known here. Either the document is unpublished, or the",
                "citation is wrong; both are defects and neither is the reader's to",
                "guess about.", ""]
        out += [f"- `{i}`" for i in unresolved]

    (ROOT / "MAP.md").write_text("\n".join(out) + "\n")
    print(f"MAP.md written: {len(rows)} references, {len(unresolved)} unresolved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
