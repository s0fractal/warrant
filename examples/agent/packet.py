#!/usr/bin/env python3
"""Build the fresh-context handoff fixture (ACCEPTANCE.md step 6, S5).

    python3 packet.py --out DIR

Runs the producer's side of the acceptance run through the Python door, then
stops where the receiver takes over: the full cut is inspected against the
receiver's expectation and imported, and nothing has been filed by the receiver.
Writes, in DIR:

  rcv/config.json      the receiver's operator configuration (for warrant-agent-mcp)
  packet.json          the compact starting packet: the receiver's own context
                       (capsules, frontier, questions, boundary, delivery, use),
                       the configured handles and the evidence addresses
  log/signed-log.json  the contrast: the same facts as a plain signed JSON log
                       (every signed envelope in time order, the blobs, the trust file)
  truth.json           what a correct reading must say, for scoring; not shown to a model
"""
import argparse
import base64
import json
import sys
from pathlib import Path

from acceptance import PROFILE, Party, PythonDoor, R  # noqa: F401 - same world as the acceptance run
from acceptance import ACTORS, Key
from warrant import jcs as C


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    base = Path(ap.parse_args().out)
    base.mkdir(parents=True)
    keys = {a: Key.generate() for a in ACTORS}
    src = Party(base, "src", "producer", keys, PythonDoor)
    rcv = Party(base, "rcv", "receiver", keys, PythonDoor)

    ev_blob = src.store.put_blob(b"candidate(-2) returns 2\n")
    d1 = src.file("d1", "duty", {"holder": "producer", "statement": "abs(-2) == 2 is implemented",
                                 "owed_to": ["reviewer"], "condition": {"attest": {}}, "accept_by": ["reviewer"]})
    t1 = src.file("t1", "transition", {"basis": "ATTESTED", "evidence": [ev_blob],
                                       "closes": [{"duty": d1, "act": "discharge", "evidence": [ev_blob]}],
                                       "established": ["abs is implemented"], "residual": ["only -2 was tried"]})
    a1 = src.other_actor("reviewer", "accept", R.accept(t1, 0, [ev_blob]))
    t = src.ok("compute", {"op": "term", "expr": "S K K (K I)"})["data"]
    s = src.ok("compute", {"op": "start", "runtime": "book1", "input": t["input"], "environment": t["environment"]})["data"]
    seg = src.ok("compute", {"op": "resume", "runtime": "book1", "input": t["input"], "environment": t["environment"],
                             "checkpoint": s["checkpoint"], "state": s["state"], "credit": 2})["data"]["segment"]
    d2 = src.file("d2", "duty", {"holder": "producer", "statement": "hand over a resumable computation of S K K (K I)",
                                 "owed_to": ["receiver"], "condition": {"attest": {}}, "accept_by": ["receiver"]})
    cev = [seg["checkpoint"], seg["state"], t["environment"]]
    t2 = src.file("t2", "transition", {
        "basis": "ATTESTED", "evidence": cev, "closes": [{"duty": d2, "act": "discharge", "evidence": cev}],
        "established": [f"S K K (K I) started under Book I; paused at {seg['checkpoint'][:12]} ({seg['outcome']})"],
        "residual": ["the result is not computed", "the checkpoint is the producer's; a receiver must replay it"]})
    cx = src.store.put_blob(b"candidate(-2) returns -4 on the 32-bit path\n")
    ch = src.other_actor("auditor", "challenge", R.challenge(t1, "abs(-2) returns -4 on the 32-bit path", [cx], 0))
    roots = [{"kind": "duty", "id": d1}, {"kind": "duty", "id": d2}]
    full = src.ok("handoff", {"op": "export", "view_token": src.context("producer", roots)["view_token"],
                              "roots": roots, "request_id": "full-cut"})["data"]
    rcv.doc["workspaces"]["rcv"]["expectations"] = {"src-full": {"manifest": full["manifest_digest"], "source": "src"}}
    prov = rcv.ok("compute", {"op": "provider"})["data"]["provider"]
    # the receiver operator accepts this provider for its computation target, before the agent starts
    (rcv.base / "profile.json").write_text(json.dumps(dict(PROFILE, providers=[prov], targets=["rcv/compute"])))
    rcv.restart()
    seen = rcv.ok("handoff", {"op": "inspect", "manifest": full["package"]["manifest"],
                              "payload": full["package"]["payload"], "declaration": full["package"]["declaration"],
                              "expectation": "src-full", "use": "continue", "actor": "receiver", "targets": roots})
    rcv.ok("handoff", {"op": "import", "staged_id": seen["data"]["staged_id"], "request_id": "import-full"})
    ctx = rcv.context("receiver", roots)
    ctx["data"].pop("staged_id", None)
    packet = {
        "you_are": "receiver",
        "workspace": "rcv",
        "use": "continue",
        "context": {k: ctx[k] for k in ("view_token", "assessment_id", "delivery", "use", "observation", "page")},
        "capsules": ctx["data"]["capsules"], "frontier": ctx["data"]["frontier"],
        "questions": ctx["data"]["questions"], "boundary": ctx["data"]["boundary"],
        "delivered": {"expectation": "src-full", "relation": seen["delivery"]["relation"], "manifest": full["manifest_digest"]},
        "computation": {"runtime": "book1", "input": t["input"], "environment": t["environment"],
                        "paused_checkpoint": seg["checkpoint"], "paused_state": seg["state"], "target": "rcv/compute"},
    }
    (base / "packet.json").write_text(json.dumps(packet, indent=1))
    # the contrast: the same facts as a plain signed log
    store = rcv.base / "store"
    envs = [C.loads(p.read_bytes()) for p in (store / "records").iterdir()]
    envs.sort(key=lambda e: (e["record"]["at"], e["record"]["type"]))
    log = {"log": "plain signed JSON log", "trust": C.loads((rcv.base / "trust.json").read_bytes()),
           "entries": [dict(e, id=R.record_id(e["record"])) for e in envs],
           "blobs": {p.name: base64.b64encode(p.read_bytes()).decode() for p in sorted((store / "blobs").iterdir())}}
    (base / "log").mkdir()
    (base / "log" / "signed-log.json").write_text(json.dumps(log, indent=1))
    truth = {"d1": d1, "t1": t1, "accept_t1": a1, "challenge": ch, "d2": d2, "t2": t2,
             "t2_item0_evidence": sorted(cev), "computation": packet["computation"],
             "rely": {d1: "hold", d2: "open"}, "residual_t2": ["the result is not computed"]}
    (base / "truth.json").write_text(json.dumps(truth, indent=1))
    for p in (src, rcv):
        p.door.close()
    print(json.dumps({"out": str(base), "packet_bytes": (base / "packet.json").stat().st_size,
                      "log_bytes": (base / "log" / "signed-log.json").stat().st_size}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
