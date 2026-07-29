#!/usr/bin/env python3
"""Emit a reproducible manifest of what a release publicly disclosed.

WHY THIS EXISTS
---------------
Prior art is not a timestamp. A timestamp proves a document existed; prior art
requires that the teaching was *publicly available* to a person skilled in the
art before someone else's priority date. Anchoring a private hash to a
blockchain proves possession, which is the wrong half.

The right half is: a public, dated, third-party-attested record of exactly which
bytes were available. This tool produces the "exactly which bytes" part, so the
attestation has something precise to point at.

Manifests are read from GIT OBJECTS, never the working tree. A manifest that
depended on an uncommitted checkout would describe a state no one else could
reach, which is the opposite of a disclosure record.

The single `manifest_sha256` at the end is the anchor point: timestamp that one
value and every listed file is covered, because changing any of them changes it.

WHAT THIS DOES NOT ESTABLISH
----------------------------
  * It does not create prior art. Publication did that; this records it.
  * It says nothing about a patent filed BEFORE the dates it lists. Against an
    earlier priority date, later disclosure is not prior art at all, and no
    amount of anchoring changes the order of events.
  * Git author/commit dates are self-asserted and trivially forgeable. They are
    listed as claims, not evidence. Only the third-party attestations recorded in
    PRIOR-ART.md carry independent weight.

USAGE
    python3 tools/disclosure_manifest.py v0.4.0
    python3 tools/disclosure_manifest.py v0.4.0 --json
    python3 tools/disclosure_manifest.py --all-tags
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# What counts as the disclosure: normative text, reference implementations,
# conformance vectors, and the profiles that apply them. Deliberately broad --
# an implementation teaches as much as a specification, and an examiner reading
# for enablement will want both.
INCLUDE_PREFIXES = ("spec/", "impl/", "impl-go/", "impl-rs/", "proofs/",
                    "tests/", "profiles/", "examples/", "docs/", "integrations/")
INCLUDE_FILES = ("SPEC.md", "README.md", "ARCHITECT.md", "EVIDENCE-PACK.md",
                 "QUICKSTART.md", "ROADMAP.md", "CHANGELOG.md")
SKIP_SUFFIXES = (".pyc", ".lock", ".png", ".jpg", ".zip", ".wasm")
# Build caches and dot-directories are not disclosure. v0.3.0 of this repository
# accidentally committed 789 files of `impl-go/.gocache/`, which would have
# padded a prior-art record with compiler droppings and invited the obvious
# question of what else was not being read before it was signed.
SKIP_DIR_PARTS = (".gocache", "__pycache__", "node_modules", ".pytest_cache",
                  "target", "dist", "build")


def git(*args, binary=False):
    r = subprocess.run(["git", "-C", str(ROOT), *args],
                       capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def included(path):
    if path.endswith(SKIP_SUFFIXES):
        return False
    parts = path.split("/")
    if any(p.startswith(".") or p in SKIP_DIR_PARTS for p in parts[:-1]):
        return False
    return path.startswith(INCLUDE_PREFIXES) or path in INCLUDE_FILES


def manifest(ref):
    """Every disclosed file at `ref`, with the SHA-256 of its exact bytes."""
    listing = git("ls-tree", "-r", "--name-only", ref).splitlines()
    entries = []
    for path in sorted(p for p in listing if included(p)):
        blob = git("show", f"{ref}:{path}", binary=True)
        entries.append({"path": path,
                        "sha256": hashlib.sha256(blob).hexdigest(),
                        "bytes": len(blob)})

    commit = git("rev-parse", f"{ref}^{{commit}}").strip()
    # Dates are recorded as CLAIMS. git lets an author write any date they like;
    # what makes a date credible is an independent party that saw it.
    authored = git("show", "-s", "--format=%aI", commit).strip()
    committed = git("show", "-s", "--format=%cI", commit).strip()

    body = "\n".join(f"{e['sha256']}  {e['path']}" for e in entries) + "\n"
    return {
        "manifest_version": "1",
        "repository": git("remote", "get-url", "origin").strip(),
        "ref": ref,
        "commit": commit,
        "git_authored_date_claimed": authored,
        "git_committed_date_claimed": committed,
        "file_count": len(entries),
        "files": entries,
        "manifest_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def render(m):
    lines = [
        f"# Disclosure manifest — {m['ref']}",
        f"# repository        {m['repository']}",
        f"# commit            {m['commit']}",
        f"# authored (claim)  {m['git_authored_date_claimed']}",
        f"# committed (claim) {m['git_committed_date_claimed']}",
        f"# files             {m['file_count']}",
        "#",
        "# Dates above are self-asserted by git and prove nothing on their own.",
        "# Independent attestations are recorded in PRIOR-ART.md.",
        "",
    ]
    lines += [f"{e['sha256']}  {e['path']}" for e in m["files"]]
    lines += ["", f"manifest_sha256  {m['manifest_sha256']}"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref", nargs="?", help="tag or commit; default HEAD")
    ap.add_argument("--all-tags", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    refs = ([t for t in git("tag").split()] if args.all_tags
            else [args.ref or "HEAD"])
    out = [manifest(r) for r in refs]

    if args.json:
        print(json.dumps(out if args.all_tags else out[0],
                         indent=2, sort_keys=True))
    else:
        print("\n".join(render(m) for m in out), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
