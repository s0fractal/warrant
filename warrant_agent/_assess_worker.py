"""Assess one frozen view directory; run by views._assess in its own process so
that a deadline can stop it. It reads only the view directory."""
import base64
import json
import sys
from pathlib import Path

from warrant import compute as P
from warrant import engine as E
from warrant import jcs as C
from warrant.store import Snapshot, Trust


def main(vdir):
    vdir = Path(vdir)
    meta = json.loads((vdir / "meta.json").read_bytes())
    trust = Trust(C.loads(base64.b64decode(meta["trust"])))
    provider = None
    if meta["provider"]:
        sources = {n: (vdir / "provider" / f"{n}.py").read_bytes() for n in P.MODULES}
        provider = P.Provider(sources, vdir / "provider")
    workspace = tuple(meta["repo"]) if meta["repo"] else None
    rep = E.assess(Snapshot.read(vdir), trust, meta["as_of"], meta["profile"], current=meta["current"],
                   workspace=workspace, provider=provider, replay_cache=meta.get("replay_cache"))
    tmp = vdir / "report.json.tmp"
    tmp.write_text(json.dumps(rep, sort_keys=True))
    tmp.replace(vdir / "report.json")


if __name__ == "__main__":
    main(sys.argv[1])
