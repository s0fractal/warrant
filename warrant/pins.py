"""Pins: the bytes an acceptance names, compared with a Git tree of the receiver's (G14).

An acceptance names its `files`, {path: git blob} (a symlink's as `link:<blob>`). Each is compared with one commit's
tree:

    UNCHANGED  the same bytes at the same path;
    MOVED      the path is gone from the tree and the same bytes are at another path;
    CHANGED    other bytes at the path, with the first commit after the accepted one that changed it;
    GONE       the path is gone from the tree and those bytes are nowhere in it;
    UNKNOWN    the acceptance names no files, or not as {path: blob}: nothing can be compared.

`warrant drift` (warrant.drift) reads a repository's claims through this, and `warrant verify` (warrant.verify) the
acceptances behind a package's roots. It reads Git's trees and history and runs nothing of the repository's; the
paths and commits come from records, so only a full commit id reaches Git and a path is literal."""
import subprocess

from . import shapes as S

FRESH = ("UNCHANGED", "MOVED")


def git(root, *a, raw=False):
    out = subprocess.run(["git", "-C", str(root), *a], capture_output=True, check=True).stdout
    return out if raw else out.decode().strip()


def blobs(root, commit):
    """{path: git blob} of `commit`'s whole tree, a symlink's as `link:<blob>`: its blob is its target's name, and the
    same id as a regular file holding that name would read other bytes (Codex finding ea6300ecf5d5)."""
    rows = git(root, "ls-tree", "-r", "-z", "--full-tree", commit, raw=True).decode().split("\0")
    return {r.split("\t", 1)[1]: ("link:" if r.startswith("120000 ") else "") + r.split()[2] for r in rows if r}


def paths_of(head):
    """{blob: path} of a tree's {path: blob}: where a blob is now, the first of its paths in order."""
    return {b: p for p, b in sorted(head.items(), reverse=True)}


def first_change(root, commit, path, head="HEAD"):
    """The first commit after `commit`, on the way to HEAD, that changed `path` (None when none is found: the commit
    is not in this clone, or a merge brought the bytes). `commit` and `path` come from a record: only a commit id
    reaches Git, and the path is literal."""
    if not S.hex_of(commit, 40):
        return None
    try:
        out = git(root, "--literal-pathspecs", "log", "--reverse", "--format=%H", f"{commit}..{head}", "--", path).splitlines()
    except subprocess.CalledProcessError:
        return None
    return out[0] if out else None


def unreadable(files):
    """Why an acceptance's `files` cannot be compared with any tree, or None."""
    if not files:
        return "the acceptance names no files"
    if not (isinstance(files, dict) and all(isinstance(b, str) for b in files.values())):
        return "the acceptance's files are not {path: blob}"
    return None


def compare(root, commit, files, head, where, at="HEAD"):
    """[(verdict, path, detail)] of an acceptance's `files` against HEAD (`head`, {path: blob}; `where`, {blob: path})."""
    why = unreadable(files)
    if why:
        return [("UNKNOWN", "", why)]
    out = []
    for p, blob in sorted(files.items()):
        now = head.get(p)
        if now == blob:
            out.append(("UNCHANGED", p, ""))
        elif now is None and blob in where:
            out.append(("MOVED", p, f"now at {where[blob]}"))
        else:
            x = first_change(root, commit, p, at)
            since = f"since {x[:12]}" if x else f"since {str(commit)[:12]}"
            out.append(("CHANGED", p, since) if now else ("GONE", p, f"not at HEAD, {since}"))
    return out


def verdict(rows):
    """One acceptance's verdict from its rows: UNCHANGED when every file is fresh, UNKNOWN when nothing could be
    compared, else CHANGED."""
    words = {v for v, _, _ in rows}
    if words <= set(FRESH):
        return "UNCHANGED"
    return "UNKNOWN" if words == {"UNKNOWN"} else "CHANGED"
