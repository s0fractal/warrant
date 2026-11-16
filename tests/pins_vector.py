"""The vector every reader of the records must pass (docs/V3.md §10): a store read with no checkout beside it shows a
lineage the freshness gate covers as PINS_NOT_CHECKED, never ELIGIBLE, and every other lineage with the engine's
reliance.

    python3 tests/pins_vector.py --write     # rebuilds tests/vectors/pins-not-checked.json

The store is tools_test's shared claims repository (claims accepted by the claims checker's replay, so pinned), with
one of its claims retired (its effective version still the accepted one: the gate does not cover a retired claim),
one obligation accepted with no files (not pinned: ELIGIBLE) and one waiting (PENDING). The vector holds the store's
lines and v3.json as they are, and `expect`, {lineage: reliance}: what Python reads (warrant.drift.not_checked over the
engine's report). tests/agent_test.py and tests/impl_js_test.py hold their readers to it."""
import contextlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
OUT = HERE / "vectors" / "pins-not-checked.json"


def build():
    import tools_test as TT
    from warrant import drift as D
    from warrant.repo import Repo as RealRepo
    with contextlib.redirect_stdout(io.StringIO()):
        r, _ = TT.shared_repo()
    from warrant import claims as CL
    pre = RealRepo(r.root).report()
    L0 = sorted(CL.live(pre))[0]                         # one pinned claim retired: its effective version stays the
    leaf = pre["lineages"][L0]["leaf"]                   # accepted one, but a retired claim is not the gate's
    body = dict(pre["_recs"][leaf]["body"], state="retired", reason="retired for the vector")
    r.put("alice", "entity", body, CL.CLAIM, lineage=leaf, guard=CL.schema_guard(pre, "backed"))   # waits: the effective version stays the pinned one
    o = r.entity("alice", "obligation@1", {"state": "done", "statement": "accepted, no files", "serves": []})
    r.attest("bob", o)
    r.entity("alice", "obligation@1", {"state": "done", "statement": "waiting", "serves": []})
    rep = RealRepo(r.root).report()           # carries the records drift reads (_recs)
    D.not_checked(rep)
    return {"warrant": "vector/pins-not-checked/1",
            "rule": "docs/V3.md §10: read with no checkout beside the store, a lineage the freshness gate covers is "
                    "PINS_NOT_CHECKED, never ELIGIBLE; every other lineage reads the engine's reliance",
            "v3": json.loads((r.dot / "v3.json").read_text()),
            "lines": (r.dot / "records.jsonl").read_text().splitlines(),
            "expect": {L: lin["reliance"] for L, lin in sorted(rep["lineages"].items())}}


if __name__ == "__main__":
    if "--write" not in sys.argv[1:]:
        sys.exit("usage: python3 tests/pins_vector.py --write")
    v = build()
    OUT.write_text(json.dumps(v, indent=1, sort_keys=True) + "\n")
    from collections import Counter
    print(OUT, dict(Counter(v["expect"].values())))
