"""Two separate parties for warrant-agent tests: a source and a receiver, each with
its own store, trust, profile, signer and operator configuration."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("WARRANT_IMPL") or str(ROOT))

from warrant import jcs as C                      # noqa: E402
from warrant import records as R                  # noqa: E402
from warrant.keys import Key                      # noqa: E402
from warrant.store import Store, Trust            # noqa: E402
from warrant_agent import api, handoff, views     # noqa: E402,F401
from warrant_agent.config import Config           # noqa: E402

ACTORS = ("producer", "reviewer", "auditor", "receiver")


class Party:
    def __init__(self, base, name, signer, keys, profile, uses, expectations=None, limits=None):
        self.base, self.name, self.keys = base / name, name, keys
        self.base.mkdir(parents=True)
        self.store = Store(self.base / "store").init()
        (self.base / "trust.json").write_bytes(C.canon(Trust.document([(a, k.public) for a, k in keys.items()])))
        (self.base / "profile.json").write_text(json.dumps(profile))
        (self.base / f"{signer}.key").write_text(keys[signer].seed_hex())
        self.signer = signer
        self.doc = {"agent_api": "warrant-agent/1", "state": str(self.base / "state"),
                    "workspaces": {name: {"store": str(self.base / "store"), "trust": str(self.base / "trust.json"),
                                          "profile": str(self.base / "profile.json"),
                                          "signer": {"actor": signer, "key": str(self.base / f"{signer}.key")},
                                          "source_name": name, "uses": uses,
                                          "expectations": expectations or {}, "limits": limits or {}}}}
        self.reload()

    def reload(self):
        (self.base / "config.json").write_text(json.dumps(self.doc))
        self.cfg = Config.load(self.base / "config.json")
        self.ws = self.cfg.workspace(self.name)

    def expect(self, handle, manifest, **extra):
        """The controller's act: a receiver-side expectation, outside any package."""
        self.doc["workspaces"][self.name]["expectations"][handle] = dict(manifest=manifest, **extra)
        self.reload()

    def file(self, rtype, actor, at, body):
        return self.store.put_record(R.record(rtype, actor, at, body), self.keys[actor])

    def blob(self, data):
        return self.store.put_blob(data)

    def call(self, op, req):
        return api.call(self.cfg, op, req)


PROFILE = {"uses": {"continue": {"requires_triggers": False}}, "accept_by": {"results": []}, "targets": [],
           "grant_roots": [], "challengers": ["auditor"], "providers": []}
USES = {"continue": {"delivery": ["MATCH_EXPECTED_SET", "LOCAL_CAPTURE"], "reliance": ["ELIGIBLE"], "fresh": True},
        "import": {"delivery": ["MATCH_EXPECTED_SET"]}}


def world():
    base = Path(tempfile.mkdtemp(prefix="warrant-agent-"))
    keys = {a: Key.generate() for a in ACTORS}
    src = Party(base, "src", "producer", keys, PROFILE, USES)
    rcv = Party(base, "rcv", "receiver", keys, PROFILE, USES)
    return src, rcv


def reviewed_work(src, challenge=True):
    """A duty, its closure, the reviewer's exact acceptance and (optionally) the
    auditor's counting challenge. Returns ids."""
    ev = src.blob(b"candidate(-2) returns 4\n")
    d = src.file("duty", "producer", 100, R.duty("producer", "abs(-2) == 2 is implemented", ["reviewer"],
                                                 {"attest": {}}, accept_by=["reviewer"]))
    t = src.file("transition", "producer", 110, R.transition("ATTESTED", [ev], closes=[R.item(d, "discharge", [ev])],
                                                             established=["abs is implemented"],
                                                             residual=["only -2 was tried"]))
    a = src.file("accept", "reviewer", 120, R.accept(t, 0, [ev]))
    out = {"duty": d, "transition": t, "accept": a, "evidence": ev}
    if challenge:
        cx = src.blob(b"candidate(-2) returns -4\n")
        out["challenge"] = src.file("challenge", "auditor", 140, R.challenge(t, "abs(-2) returns -4", [cx], 0))
        out["counterexample"] = cx
    return out


results = {}


def check(cid, ok, what, detail=""):
    results[cid] = "PASS" if ok else "FAIL"
    print(("ok    " if ok else "FAIL  ") + f"{cid} {what}" + ("" if ok else f" | {detail}"), flush=True)


def finish(name):
    failed = sorted(k for k, v in results.items() if v == "FAIL")
    print(f"{name}: {sum(v == 'PASS' for v in results.values())} PASS / {len(failed)} FAIL"
          + (f" ({', '.join(failed)})" if failed else ""))
    if os.environ.get("WARRANT_RESULTS"):
        Path(os.environ["WARRANT_RESULTS"]).write_text(json.dumps(results))
    return 1 if failed else 0
