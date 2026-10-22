"""Where the first-contact tools may read and write: this directory (transcripts, scores) and
~/Projects/.worktrees (fixture worlds). Every path a command line names is resolved and refused
outside these roots before it is opened."""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path.home() / "Projects" / ".worktrees"
ROOTS = (HERE, WORK)


def confined(arg, roots=ROOTS):
    """The resolved path of `arg` if it lies under one of `roots`; SystemExit otherwise."""
    real = os.path.realpath(arg)
    for root in roots:
        base = os.path.realpath(root)
        if os.path.commonpath([real, base]) == base:
            return Path(real)
    raise SystemExit(f"{arg}: outside {', '.join(str(r) for r in roots)}")
