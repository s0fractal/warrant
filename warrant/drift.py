"""Whether the bytes a claims checker's acceptance ran on are still the bytes at this receiver's head (G14).

An acceptance names its `files`, {path: git blob}: each witness's test file, each mutant's mutated file and test
file, as the checker found them at the commit it ran (`warrant claims replay`; CI's `claims verify` holds the list to
that commit). Each is compared with HEAD's tree:

    UNCHANGED  the same bytes at the same path;
    MOVED      the path is gone from HEAD and the same bytes are at another path (unchanged, at its new path);
    CHANGED    other bytes at the path, with the first commit after the accepted one that changed it;
    GONE       the path is gone from HEAD and those bytes are nowhere in it;
    UNKNOWN    the acceptance names no files (one signed before they were named): nothing can be compared.

A claim reads UNCHANGED when one of its effective version's acceptances has every file UNCHANGED or MOVED. When none
has, the acceptance is stale: that lineage's reliance is STALE, not ELIGIBLE, until the claims checker accepts it
again at a commit holding those bytes. This is a gate, not advice: time-lab Q10 H3 found a model under one sentence
of pressure acting on a stale conclusion in 72 of 72 scenarios despite an honest freshness answer it heeded without
pressure. The answer leads with the verdict on the bytes (Q10: "the pinned bytes are now at X" made a model re-read
where git's rename line did not).

It reads the store and Git's trees and history, and runs nothing of the repository's: `context` and `graph` answer
through it, in workspaces permitted to read only (Codex finding c589d17da0f3), and what the current mutant harness
lists is no part of it, so editing the harness cannot refresh an acceptance (finding 0e7a05e8832c). The head is the
receiver's HEAD commit, not its working tree. A checkout without .warrant/claims.json has no drift answer.

    python3 -m warrant drift [--root DIR] [--json]     # one line per accepted claim, the verdict first"""
import argparse
import subprocess
import sys
from pathlib import Path

from . import claims as C
from . import shapes as S
from .repo import Repo, dump, env_root, git, main

STALE = "STALE"
FRESH = ("UNCHANGED", "MOVED")
RANK = {"UNCHANGED": 0, "CHANGED": 1, "UNKNOWN": 2}     # the answer shown: fresh if any acceptance is, else what can be said


def first_change(root, commit, path):
    """The first commit after `commit`, on the way to HEAD, that changed `path` (None when none is found: the commit
    is not in this clone, or a merge brought the bytes). `commit` and `path` come from a record: only a commit id
    reaches Git, and the path is literal."""
    if not S.hex_of(commit, 40):
        return None
    try:
        out = git(root, "--literal-pathspecs", "log", "--reverse", "--format=%H", f"{commit}..HEAD", "--", path).splitlines()
    except subprocess.CalledProcessError:
        return None
    return out[0] if out else None


def compare(root, commit, files, head, where):
    """[(verdict, path, detail)] of an acceptance's `files` against HEAD (`head`, {path: blob}; `where`, {blob: path})."""
    if not files:
        return [("UNKNOWN", "", "the acceptance names no files")]
    if not (isinstance(files, dict) and all(isinstance(b, str) for b in files.values())):
        return [("UNKNOWN", "", "the acceptance's files are not {path: blob}")]
    out = []
    for p, blob in sorted(files.items()):
        now = head.get(p)
        if now == blob:
            out.append(("UNCHANGED", p, ""))
        elif now is None and blob in where:
            out.append(("MOVED", p, f"now at {where[blob]}"))
        else:
            x = first_change(root, commit, p)
            since = f"since {x[:12]}" if x else f"since {str(commit)[:12]}"
            out.append(("CHANGED", p, since) if now else ("GONE", p, f"not at HEAD, {since}"))
    return out


def _verdict(rows):
    words = {v for v, _, _ in rows}
    if words <= set(FRESH):
        return "UNCHANGED"
    return "UNKNOWN" if words == {"UNKNOWN"} else "CHANGED"


def drift(rep, root):
    """{lineage: {id, version, verdict, commit, files}} for each live claim whose effective version the claims
    checker accepted: the comparison of the acceptance that is freshest."""
    if not (Path(root) / ".warrant" / "claims.json").is_file():
        return {}
    done = C.acceptances(rep)
    try:
        head = C.blobs(root, "HEAD")
    except subprocess.CalledProcessError:
        head = {}
    where = {b: p for p, b in sorted(head.items(), reverse=True)}
    out = {}
    for L in sorted(C.live(rep)):
        eff = rep["lineages"][L]["effective"]
        if not done.get(eff):
            continue
        seen = [(x, compare(root, x, files, head, where)) for x, files in done[eff]]
        x, rows = min(seen, key=lambda s: RANK[_verdict(s[1])])
        out[L] = {"id": rep["_recs"][eff]["body"].get("id"), "version": eff, "verdict": _verdict(rows), "commit": x,
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
                out.append(f"  unchanged, moved: {f['detail']} (was {f['path']})")
            elif f["verdict"] != "UNCHANGED":
                out.append("  " + " ".join(w for w in (f["verdict"], f["path"], f["detail"]) if w))
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
