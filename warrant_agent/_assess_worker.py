"""Assess one frozen view directory; run by views._assess in its own process so
that a deadline can stop it. It reads only the view directory, and only one that
views.capture made (the path comes from views._assess, never from argv), and the
objects its meta.json names in the workspace's object store beside it, each hashed
as it is read: an absent or damaged one is reported (damaged.json), never replaced
by a read from elsewhere."""
import base64
import json
import sys
from pathlib import Path

from warrant import compute as P
from warrant import engine as E
from warrant import jcs as C
from warrant import limits as L
from warrant import shapes as S
from warrant.store import Trust

from warrant_agent import objects as O


TOKEN = S.HEX32


def view_dir(vdir):
    """An absolute <state>/<workspace>/views/<token> directory with no symlink on
    its path and a meta.json in it; anything else is refused before it is read."""
    p = Path(vdir)
    if not (p.is_absolute() and TOKEN.match(p.name) and p.parent.name == "views" and p.resolve() == p
            and p.is_dir() and (p / "meta.json").is_file() and not (p / "meta.json").is_symlink()):
        raise SystemExit("the assessment worker reads only a view directory")
    return p


def main(vdir):
    vdir = view_dir(vdir)
    meta = json.loads((vdir / "meta.json").read_bytes())
    trust = Trust(C.loads(base64.b64decode(meta["trust"])))
    objs = O.Objects(vdir.parent.parent / "objects")
    workspace = tuple(meta["repo"]) if meta["repo"] else None
    try:
        provider = None
        if meta["provider"]:
            sources = {n: objs.get(meta["provider"][n]) for n in P.MODULES}
            provider = P.Provider(sources, vdir / "provider")
        snap = objs.snapshot(objs.get_doc(meta["tree"]), meta["limits"])
        rep = E.assess(snap, trust, meta["as_of"], meta["profile"],
                       current=meta["current"], workspace=workspace, provider=provider,
                       replay_cache=meta.get("replay_cache"), limits=meta["limits"], verdicts=meta.get("verdicts"))
    except O.Unreadable as e:
        # A refusal, not a report: views._assess maps it to VIEW_DAMAGED.
        (vdir / "damaged.json").write_text(json.dumps({"object": e.name, "why": e.why}))
        sys.exit(4)
    except L.LimitExceeded as e:
        # A refusal, not a report: views._assess maps it to RESOURCE_LIMIT.
        (vdir / "refusal.json").write_text(json.dumps({"limit": e.limit, "value": e.value, "bound": e.bound}))
        sys.exit(3)
    tmp = vdir / "report.json.tmp"
    tmp.write_text(json.dumps(rep, sort_keys=True))
    tmp.replace(vdir / "report.json")
