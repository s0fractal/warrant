"""What binds a generated view (ROADMAP.md, CLAIMS.md, REVIEWS.md, WITNESSES.md) to what decided it: one line under its
title naming `root`, the store's full snapshot, and `lens`, warrant.graph.answer's content address of the code, the
trust, the profile, the view's name and the checkout read (the working tree outside the store, .warrant/claims.json,
the tool that rendered it when it is not the package, and the code tree of each commit CLAIMS.md compares with HEAD).

One definition for `tools/graph.py render` and the public `warrant roadmap view`, `warrant claims view` and `warrant
review view`, which once printed only a 12-character snapshot prefix and no lens (Codex e283140f on G11)."""
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from . import graph as G


def code_id(root, tool=None):
    """What decides a view besides the records, trust and profile: the working tree outside the store as one git tree id
    (a temporary index over every file Git would add, so two different uncommitted edits are two ids, not one `dirty`
    flag; None for a store with no checkout), the bytes of .warrant/claims.json (which shapes CLAIMS.md; the store's directory is not in that tree) and
    the bytes of `tool`, the file that rendered it when it is not this package (whose digest the report's `code`
    names), which may come from another checkout (Codex 21eb439d on G11)."""
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(d) / "index"))
        try:
            subprocess.run(["git", "--no-replace-objects", "-C", str(root), "add", "-A", "--", ".", ":!.warrant"], env=env,
                           capture_output=True, check=True)
            tree = subprocess.run(["git", "--no-replace-objects", "-C", str(root), "write-tree"], env=env,
                                  capture_output=True, text=True, check=True).stdout.strip()
        except subprocess.CalledProcessError:
            tree = None               # a store with no checkout of its own: no working tree decides the view
    claims = Path(root) / ".warrant" / "claims.json"
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest() if p is not None and Path(p).is_file() else None  # noqa: E731
    return {"tree": tree, "claims": digest(claims), "tool": digest(tool)}


def bound(rep, root, views, tool=None):
    """{name: text} with each view's root and lens under its title; `rep` the report the views were rendered from."""
    from . import claims as CL
    code = json.dumps(dict(code_id(root, tool), trees=CL.trees_read(rep, root)), sort_keys=True)
    out = {}
    for n, text in views.items():
        a = G.answer(rep, {"op": "view", "name": n}, None, code)
        head, _, rest = text.partition("\n")
        out[n] = f"{head}\n\nroot `{a['root']}` · lens `{a['lens']}`\n{rest}"
    return out
