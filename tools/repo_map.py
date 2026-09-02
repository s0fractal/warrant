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


def _sibling():
    """Where the other repository lives, without asking what this one is called.

    This used to be `ROOT.parent / ("sigma-glyph" if ROOT.name == "warrant"
    else "warrant")` — which resolved correctly only when the checkout
    directory was literally named `warrant`. Run from a worktree named
    anything else, `--regen` silently rewrote every sigma-glyph row to
    "resolves nowhere" and wrote a MAP.md that looked authoritative and was
    not. A check whose output depends on the name of the directory it runs in
    is a check that reports the filesystem, not the repository.

    Identity now comes from the git remote, with the old positional guess kept
    only as a last resort and never as the thing that decides.
    """
    import subprocess as _sp
    here = "warrant"
    try:
        url = _sp.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"],
                      capture_output=True, text=True, timeout=5).stdout.strip()
        if url:
            name = url.rstrip("/").rsplit("/", 1)[-1]
            here = name[:-4] if name.endswith(".git") else name
    except Exception:
        pass
    want = "sigma-glyph" if here == "warrant" else "warrant"
    # A worktree lives outside the checkout tree, so the sibling is not
    # necessarily beside it. Try the ordinary layout, then the real checkout
    # the worktree belongs to.
    for base in (ROOT.parent, Path.home() / "Projects"):
        cand = base / want
        if (cand / ".git").exists():
            return cand
    return ROOT.parent / want


SIBLING = _sibling()

# Identifiers this project cites as if the reader knows where they live.
ID_RE = re.compile(r"\b(ADR-\d{3}|WRT-\d{3}|GOV-\d{3}|Book\s+(?:I{1,3}))\b")

# Identifiers whose filename does not contain the citation string. "Book I" is
# cited nine times in this repository and lives in a file called
# book-1-truth.md, so a substring search finds nothing and would report the most
# heavily cited document in the project as resolving nowhere.
ALIASES = {"Book I": "book-1", "Book II": "book-2", "Book III": "book-3"}
SCAN = ("SPEC.md", "README.md", "ARCHITECT.md", "ROADMAP.md")
SCAN_DIRS = ("proposals", "briefs", "spec", "profiles", "needs")

# Canonical resolution for identifiers whose live location is NOT "the newest
# committed file whose path contains the string". A proposal number can outlive
# the pull request that closed it, and a number can collide with a workline
# filename (a workflow, a fixture). Left to the substring search, WRT-005 would
# resolve to `.github/workflows/wrt-005.yml` and WRT-003 to a stale copy on a
# feature branch.
#
# Every entry is fail-closed and pinned to a checkable object (Codex round 2 —
# the earlier form left closed-PR entries with no verifiable target, so swapping
# a PR number still passed `--check-map`):
#   commit set  -> the exact `commit:path` MUST resolve (`git cat-file -e`);
#   commit None -> the path MUST exist in the working tree.
# The MAP row's Path column carries that exact target, and `--check-map`
# verifies the whole row, not just that the token appears somewhere.
CANONICAL = {
    "WRT-003": {"lives_in": "closed PR #20 (verification receipts)",
                "commit": "25bd44c829cb015a836e08642022412c568de16a",
                "path": "proposals/WRT-003-verification-receipt.md"},
    "WRT-004": {"lives_in": "closed PR #21 (verify-report)",
                "commit": "7f40932060ded9a1fde7e6b74e91334e73b8080e",
                "path": "proposals/WRT-004-verify-report-v1.md"},
    "WRT-005": {"lives_in": "this repo, `proposals/wrt-005-outcome-fingerprint-purity`",
                "commit": None,
                "path": "proposals/WRT-005-outcome-fingerprint-purity.md"},
    "WRT-006": {"lives_in": "this repo, `proposals/wrt-006-ski-v1-equivalence-gate` (DRAFT)",
                "commit": None,
                "path": "proposals/WRT-006-ski-v1-implementation-substitution.md"},
}


def _canonical_target(entry):
    """The Path-column text for a canonical entry: `commit:path` for a pinned
    closed-PR entry, or `path` for a live working-tree entry."""
    if entry["commit"]:
        return f"`{entry['commit']}:{entry['path']}`"
    return f"`{entry['path']}`"


def _has_commit(commit):
    return subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True).returncode == 0


def _canonical_ok(entry):
    """Fail-closed check that a canonical entry points at something real: a
    pinned closed-PR `commit:path`, or an existing working-tree path.

    In a shallow CI checkout the pinned commit is not present; because these
    are full SHAs and the commits are reachable on origin, a targeted
    `git fetch` retrieves the one object needed, and the verification then runs
    for real. If the fetch cannot bring it in (no network), the check fails
    closed rather than silently passing."""
    if not entry["commit"]:
        return (ROOT / entry["path"]).exists()
    if not _has_commit(entry["commit"]):
        subprocess.run(["git", "-C", str(ROOT), "fetch", "--quiet", "--depth",
                        "1", "origin", entry["commit"]], capture_output=True)
    r = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e",
         f"{entry['commit']}:{entry['path']}"], capture_output=True)
    return r.returncode == 0


def _canonical_self_check():
    """Fail-closed: every CANONICAL entry must resolve to a real object — a
    pinned `commit:path` (closed PR) or an existing working-tree path (live).
    A dangling or wrong-commit entry would silently point MAP.md at nothing."""
    bad = [i for i, e in CANONICAL.items() if not _canonical_ok(e)]
    for ident in bad:
        e = CANONICAL[ident]
        tgt = f"{e['commit']}:{e['path']}" if e["commit"] else e["path"]
        print(f"CANONICAL: {ident} -> {tgt} does not resolve", file=sys.stderr)
    return not bad


def _citation_table(text):
    """Return every data row from MAP.md's citation table.

    Only the contiguous table beneath the exact four-column header counts.
    Tokens in prose or in another Markdown table are not mappings. Rows are
    returned even when malformed so `--check-map` can reject wrong cell counts
    rather than silently losing them during parsing.
    """
    lines = text.splitlines()
    header = "| Cited | Lives in | Path | First cited by |"
    try:
        start = lines.index(header)
    except ValueError:
        return None
    if start + 1 >= len(lines) or lines[start + 1].strip() != "|---|---|---|---|":
        return None
    rows = []
    for line in lines[start + 2:]:
        s = line.strip()
        if not s.startswith("|"):
            break
        rows.append([c.strip() for c in s.strip("|").split("|")])
    return rows


def _table_rows_for(ident, rows):
    """Rows whose first cell is exactly the cited identifier."""
    return [r for r in rows if r and r[0] == f"`{ident}`"]


def git(repo, *args, ok_fail=False):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    if r.returncode and not ok_fail:
        return ""
    return r.stdout


def refs_of(repo):
    """Local branches plus everything on origin, newest-looking first."""
    out = []
    # Filter on the FULL refname: the short form of refs/remotes/origin/HEAD is
    # bare "origin", which does not end in "/HEAD" and so slipped through as a
    # local branch. MAP.md then listed a branch named `origin` marked "on origin:
    # no" -- a ref that does not exist, in the generated file a reviewer reads to
    # find out which refs do.
    for line in git(repo, "for-each-ref", "--format=%(refname)\t%(refname:short)",
                    "refs/heads", "refs/remotes/origin").splitlines():
        full, _, short = line.partition("\t")
        if short and not full.endswith("/HEAD"):
            out.append(short)
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

    origin = git(ROOT, "remote", "get-url", "origin").strip()
    ids = cited(ROOT)

    if not _canonical_self_check():
        return 1

    rows, unresolved = [], []
    for ident in sorted(ids):
        if ident in CANONICAL:
            e = CANONICAL[ident]
            where = (e["lives_in"], _canonical_target(e))
        else:
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
        table = _citation_table(text)
        if table is None:
            print("MAP.md has no well-formed four-column citation table; "
                  "regenerate with tools/repo_map.py", file=sys.stderr)
            return 1
        by_ident = {i: _table_rows_for(i, table) for i in sorted(ids)}
        missing = [i for i, rws in by_ident.items() if not rws]
        for i in missing:
            print(f"UNMAPPED: {i} is cited but has no row in MAP.md -- "
                  f"regenerate with tools/repo_map.py", file=sys.stderr)
        malformed = [i for i, rws in by_ident.items()
                     if rws and (len(rws) != 1 or len(rws[0]) != 4)]
        for i in malformed:
            shapes = [len(r) for r in by_ident[i]]
            print(f"MALFORMED MAP ROW: {i} must have exactly one four-cell "
                  f"citation row; found {len(by_ident[i])} row(s) with cell "
                  f"counts {shapes}", file=sys.stderr)
        # Every cited identifier must be a real, unique, four-cell table row.
        # Canonical identifiers additionally carry exact pinned Lives-in and
        # Path cells plus the runtime-derived First-cited-by cell. This closes
        # both historical bypasses: hiding a token/prefix in prose, and keeping
        # the first three cells while corrupting or appending table cells.
        wrong = []
        for i in sorted(ids):
            if i not in CANONICAL or i in missing or i in malformed:
                continue
            e = CANONICAL[i]
            rws = by_ident[i]
            expected = [f"`{i}`", e["lives_in"], _canonical_target(e),
                        f"`{sorted(ids[i])[0]}`"]
            ok = rws[0] == expected
            if not ok:
                wrong.append(i)
                print(f"CANONICAL DRIFT: {i}'s row must be exactly {expected}; "
                      f"found {rws[0]}", file=sys.stderr)
        stale = [ln for ln in text.splitlines() if "resolves nowhere" in ln]
        for ln in stale:
            print(f"UNRESOLVED in MAP.md: {ln.strip()}", file=sys.stderr)
        print(f"REPO-MAP: {len(ids) - len(missing)}/{len(ids)} citations mapped, "
              f"{len(stale)} unresolved, {len(malformed)} malformed/duplicate, "
              f"{len(wrong)} canonical drift")
        return 1 if missing or stale or malformed or wrong else 0

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
        f"Repository `{origin}`. Regenerated by `tools/repo_map.py`; **not pinned",
        "to a commit** — a tracked file cannot honestly cite its own future SHA,",
        "so this map carries no `generated at <commit>` self-reference and no",
        "volatile branch-head inventory (both were wrong the moment a new commit",
        "landed). What it carries is stable: the identifier → location mapping,",
        "with closed proposals pinned to an immutable `commit:path`. To see live",
        "branch heads and their exact SHAs, ask git (`git branch -a -v`,",
        "`git ls-remote`) — that is git's job, not a checked-in file's.",
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
