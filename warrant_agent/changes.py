"""What changed for a reader: the difference between two states of a store as the reader sees them.

The past state is a set of records the reader had seen (a mark: their ids, kept per reader and store), assessed by
the same engine as the present: records are never removed, so it is reproduced exactly. Two states are the same for
the reader on a lineage when its page under the reader's lens shows the same: the floor (state, reliance, the
counted challenges that stand, whether it is grounded) and what the lens draws (`lens.visible`: each body member of
each version, each attest and challenge). Records are content-addressed, so a shown member cannot change without a
new id. A lineage that differs is listed with its witness: what appeared, what vanished, what in the floor moved.
New records that change nothing the reader sees are counted, never listed one by one.

This is observational equivalence relative to the reader: under another lens the same two states may differ, or
not. It sees only the records of each store; a store's completeness stays UNATTESTED."""
import json
import os
import time
from pathlib import Path

from warrant import home as H
from warrant import repo as RP
from warrant import records as R
from warrant import engine as EN
from warrant.store import Snapshot

DAY = 86400


def subset(snap, keep):
    """The snapshot of the records of `snap` whose ids are in `keep`, with all its blobs."""
    lines = [raw for raw in snap.raw if _rid(raw) in keep]
    return Snapshot(lines, snap.blobs)


def _rid(raw):
    try:
        return R.rid(json.loads(raw)["record"])
    except (ValueError, KeyError, TypeError):
        return None


def before(snap, cutoff):
    """The ids of the records filed (by their own `at`) before `cutoff`: the default past when no mark exists."""
    return {i for i, envs in snap.lines.items() if envs[0]["record"]["at"] < cutoff}


def report_of(root, snap):
    trust, profile, _ = RP.Repo(root).config()
    v = EN.View(snap, trust, profile)
    rep = v.report()
    rep["_recs"], rep["_basis"] = v.recs, v.basis
    return rep


# What changed is the general comparison of two views (view.py) with time varied: the marked past, and now.
from warrant_agent.view import candidates, delta  # noqa: E402,F401  (changes.delta stays this module's name)


class Marks:
    """Where a reader's last look lives: {reader: {store: [record id]}} in a private file beside Home."""

    def __init__(self, path=None):
        self.path = Path(path) if path else H.path().parent / "serve-seen.json"

    def load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def get(self, reader, store):
        got = self.load().get(reader or "", {}).get(store)
        return set(got) if isinstance(got, list) else None

    def set(self, reader, marks):
        doc = self.load()
        doc[reader or ""] = {s: sorted(ids) for s, ids in marks.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(doc))
        os.replace(tmp, self.path)


def since_text(mark_at):
    return "останньої позначки" if mark_at else f"останньої доби (за датами записів, до {time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() - DAY))})"
