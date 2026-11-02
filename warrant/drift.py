"""Whether the bytes a claims checker's acceptance named are still the bytes at this receiver's head (G14).

An acceptance names one commit. The claim it accepts names its witness cases (in test files) and its mutants (each
mutating one file, killed by one test file). Those files, as the receiver's head lists them, are what the acceptance
spoke of; each is compared with the same path at the accepted commit:

    UNCHANGED  the same bytes at the same path;
    MOVED      the path is new since that commit, and the same bytes were at another path there (unchanged, moved);
    CHANGED    other bytes, or a path that is new with no such bytes there; with the first commit after the accepted
               one that changed it;
    GONE       the head no longer has a file the claim names (the claims check refuses it as well);
    UNKNOWN    the accepted commit is not in this clone: nothing can be compared.

A claim reads UNCHANGED when one of its effective version's acceptances has every file UNCHANGED or MOVED. When none
has, the acceptance is stale: that lineage's reliance is STALE, not ELIGIBLE, until the claims checker accepts it
again at a commit holding those bytes (`warrant claims replay`). This is a gate, not advice: time-lab Q10 H3 found a
model under one sentence of pressure acting on a stale conclusion in 72 of 72 scenarios despite an honest freshness
answer it heeded without pressure. The answer leads with the verdict on the bytes (Q10: "the pinned bytes are now at
X" made a model re-read where git's rename line did not).

The head is the receiver's HEAD commit, not its working tree. A checkout without .warrant/claims.json has no claims
and nothing changes.

    python3 -m warrant drift [--root DIR] [--json]     # one line per accepted claim, the verdict first"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import claims as C
from .repo import Repo, dump, env_root, git, main

STALE = "STALE"
FRESH = ("UNCHANGED", "MOVED")


def _blobs(root, commit):
    """{path: blob id} of `commit`'s whole tree, or None when the commit is not in this clone."""
    try:
        rows = git(root, "ls-tree", "-r", "--full-tree", commit).splitlines()
    except subprocess.CalledProcessError:
        return None
    return {r.split("\t", 1)[1]: r.split()[2] for r in rows}


def files_of(body, root, known):
    """The repository paths a claim body's witnesses and mutants name, as this checkout lists them: each witness's
    test file, each mutant's mutated file and its test file. A name this checkout cannot place is kept as `?name`."""
    out = set()
    tests = C.witness_files(root)
    for w in body.get("witnesses") or []:
        name = w.split(":")[0]
        out.add(tests[name].relative_to(root).as_posix() if name in tests else f"?{name}")
    for m in body.get("mutants") or []:
        out.update(known[m][:2] if m in known else [f"?{m}"])
    return sorted(out)


def first_change(root, commit, path):
    """The first commit after `commit`, on the way to HEAD, that changed `path` (None when none did: a merge's
    history can bring bytes without one)."""
    try:
        out = git(root, "log", "--reverse", "--format=%H", f"{commit}..HEAD", "--", path).splitlines()
    except subprocess.CalledProcessError:
        return None
    return out[0] if out else None


def compare(root, commit, paths, head, trees):
    """[(verdict, path, detail)] of `paths` at HEAD (`head`, {path: blob}) against `commit`."""
    if commit not in trees:
        trees[commit] = _blobs(root, commit)
    then = trees[commit]
    if then is None:
        return [("UNKNOWN", p, f"{str(commit)[:12]} is not in this clone") for p in paths]
    out = []
    for p in paths:
        now = head.get(p)
        if now is None:
            out.append(("GONE", p, "not at HEAD"))
        elif then.get(p) == now:
            out.append(("UNCHANGED", p, ""))
        elif p not in then and now in then.values():
            out.append(("MOVED", p, "was " + min(q for q, b in then.items() if b == now)))
        else:
            x = first_change(root, commit, p)
            out.append(("CHANGED", p, f"since {x[:12]}" if x else f"since {commit[:12]}"))
    return out


def _verdict(rows):
    words = {v for v, _, _ in rows}
    if words <= set(FRESH):
        return "UNCHANGED"
    return "UNKNOWN" if words == {"UNKNOWN"} else "CHANGED"


def drift(rep, root):
    """{lineage: {id, version, verdict, commit, files}} for each live claim whose effective version the claims
    checker accepted: the acceptance whose files are all unchanged if one is, else the latest one's comparison."""
    if not (Path(root) / ".warrant" / "claims.json").is_file():
        return {}
    try:
        known = C.harness(root)
    except (OSError, ValueError, subprocess.CalledProcessError):
        known = {}               # no listing: every mutant is unplaced, and the claims citing one are not fresh
    done = C.checked(rep)
    head, trees, out = _blobs(root, "HEAD") or {}, {}, {}
    for L, b in sorted(C.live(rep).items()):
        lin = rep["lineages"][L]
        eff = lin["effective"]
        commits = done.get(eff) if eff else None
        if not commits:
            continue
        body = rep["_recs"][eff]["body"]
        paths = files_of(body, root, known)
        seen = []
        for x in commits:
            rows = compare(root, x, paths, head, trees)
            seen.append((x, rows))
            if _verdict(rows) == "UNCHANGED":
                break
        x, rows = seen[-1]
        out[L] = {"id": body.get("id"), "version": eff, "verdict": _verdict(rows), "commit": x,
                  "files": [{"verdict": v, "path": p, "detail": d} for v, p, d in rows]}
    return out


def gate(rep, root):
    """`rep` with the reliance of each claim whose acceptances are all stale set to STALE (and its drift kept under
    `drift`): an ELIGIBLE lineage only. Returns the drift answer."""
    d = drift(rep, root)
    for L, x in d.items():
        lin = rep["lineages"][L]
        lin["drift"] = x["verdict"]
        if x["verdict"] != "UNCHANGED" and lin["reliance"] == "ELIGIBLE":
            lin["reliance"] = STALE
    return d


def lines(d):
    """The drift answer as text: per claim the verdict on the bytes first, then the files that moved or changed."""
    out = []
    for L, x in sorted(d.items(), key=lambda kv: (kv[1]["verdict"] == "UNCHANGED", str(kv[1]["id"]))):
        word = {"UNCHANGED": "unchanged", "CHANGED": "CHANGED", "UNKNOWN": "UNKNOWN"}[x["verdict"]]
        out.append(f"{word:9} {x['id']} ({L[:12]}), accepted at {str(x['commit'])[:12]}"
                   + ("" if x["verdict"] == "UNCHANGED" else f": reliance {STALE} until the claims checker accepts it again"))
        for f in x["files"]:
            if f["verdict"] == "MOVED":
                out.append(f"  unchanged, moved: now at {f['path']} ({f['detail']})")
            elif f["verdict"] != "UNCHANGED":
                out.append(f"  {f['verdict']} {f['path']} {f['detail']}")
    n = sum(1 for x in d.values() if x["verdict"] != "UNCHANGED")
    out.append(f"drift: {len(d)} accepted claim(s), {n} stale")
    return "\n".join(out) + "\n"


def run(argv=None):
    root, argv = env_root(list(sys.argv[1:] if argv is None else argv))
    ap = argparse.ArgumentParser(prog="warrant drift")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    d = drift(Repo(root).report(), root)
    if a.json:
        dump(d)
    else:
        sys.stdout.write(lines(d))
    return 1 if any(x["verdict"] != "UNCHANGED" for x in d.values()) else 0


if __name__ == "__main__":
    sys.exit(main(run))
