#!/usr/bin/env python3
"""Two-host transport smoke, using installed Warrant 2 and Sigma 0.8.0.

Each agent operation starts a fresh CLI process. No private key is exported.
This is a control computation, not evidence of application usefulness, OS
isolation, source completeness, or independently attested remote execution.
"""
import argparse
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zlib

from warrant import compute as P, engine as E, jcs as C, records as R
from warrant.keys import Key
from warrant.store import Store, Trust

PROVIDER = "0caff793d00dd798fa0af89517674c2ca562e1d517e7c969cc40617778c776c5"
TARGET = "cross-host/compute"
USES = {"continue": {"delivery": ["MATCH_EXPECTED_SET", "LOCAL_CAPTURE"],
                     "reliance": ["ELIGIBLE"], "fresh": True},
        "import": {"delivery": ["MATCH_EXPECTED_SET"]}}


def need(cond, detail):
    if not cond:
        raise RuntimeError(str(detail))


def write(path, doc):
    path.write_bytes(C.canon(doc))


class Party:
    def __init__(self, root, name, peers):
        self.root, self.name = root.resolve(), name
        self.root.mkdir(parents=True, exist_ok=False)
        self.key = Key.generate()
        keypath = self.root / "private.key"
        fd = os.open(keypath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(self.key.seed_hex())
        self.store = Store(self.root / "store").init()
        self.profile = E.profile(uses={"continue": {"requires_triggers": False}},
                                 targets=[TARGET], providers=[PROVIDER])
        write(self.root / "profile.json", self.profile)
        write(self.root / "trust.json", Trust.document([(name, self.key.public), *peers]))
        self.doc = {"agent_api": "warrant-agent/1", "state": str(self.root / "state"),
                    "workspaces": {name: {"store": str(self.root / "store"),
                        "trust": str(self.root / "trust.json"), "profile": str(self.root / "profile.json"),
                        "signer": {"actor": name, "key": str(keypath)}, "source_name": name,
                        "uses": USES, "expectations": {}, "limits": {}}}}
        self.save()
        need(self.data("compute", op="provider")["provider"] == PROVIDER, "unexpected installed provider")

    def save(self):
        write(self.root / "config.json", self.doc)

    def call(self, operation, **req):
        p = subprocess.run([str(Path(sys.executable).parent / "warrant-agent"), "--config",
                            str(self.root / "config.json"), operation, "-"],
                           input=json.dumps(dict(req, workspace=self.name)), text=True,
                           capture_output=True, timeout=240, cwd=self.root)
        out = json.loads(p.stdout)
        need(p.returncode == (0 if "ok" in out else 2), (p.returncode, p.stderr, out))
        return out

    def ok(self, operation, **req):
        out = self.call(operation, **req)
        need("ok" in out, out)
        return out["ok"]

    def data(self, operation, **req):
        return self.ok(operation, **req)["data"]

    def file(self, kind, body):
        return self.store.put_record(R.record(kind, self.name, int(time.time()), body), self.key)

    def context(self, duty):
        return self.ok("context", actor=self.name, use="continue", targets=[{"kind": "duty", "id": duty}])

    def export(self, duty):
        view = self.context(duty)
        return self.data("handoff", op="export", view_token=view["view_token"],
                         roots=[{"kind": "duty", "id": duty}], request_id="export")["package"]

    def inspect(self, pkg, duty, source, public):
        self.doc["workspaces"][self.name]["expectations"]["operator-pin"] = {
            "manifest": C.doc_id(pkg["manifest"]), "source": source, "exporter": source}
        self.save()
        return self.ok("handoff", op="inspect", manifest=pkg["manifest"], payload=pkg["payload"],
                       declaration=pkg["declaration"], expectation="operator-pin", actor=self.name,
                       targets=[{"kind": "duty", "id": duty}])


def produce(a):
    p = Party(a.work, "producer", [])
    t = p.data("compute", op="term", expr="S K K (K I)")
    base = {"runtime": "book1", "input": t["input"], "environment": t["environment"]}
    s = p.data("compute", op="start", **base)
    r = p.data("compute", op="resume", **base, checkpoint=s["checkpoint"], state=s["state"], credit=2)
    seg = r["segment"]
    need(seg["outcome"] == "PAUSED", r)
    d = p.file("duty", R.duty("producer", "deliver a replayable PAUSED control computation",
                             ["receiver"], {"attest": {}}, accept_by=["receiver"]))
    ev = [seg["checkpoint"], seg["state"], t["environment"]]
    tr = p.file("transition", R.transition("ATTESTED", ev, closes=[R.item(d, "discharge", ev)],
        established=["the control computation paused after credit 2"],
        residual=["not a useful application workload", "the receiver must replay the checkpoint"]))
    packet = {"experiment": "warrant-cross-host-smoke/1", "producer_public": p.key.public,
              "provider": PROVIDER, "term": t, "paused": seg, "duty": d, "transition": tr,
              "package": p.export(d)}
    write(a.packet, packet)
    print(json.dumps({"packet_sha256": C.digest(a.packet.read_bytes()),
                      "manifest": C.doc_id(packet["package"]["manifest"]),
                      "producer_public": p.key.public, "outcome": seg["outcome"]}, indent=2))


def receive(a):
    raw = a.packet.read_bytes()
    need(C.digest(raw) == a.packet_sha256, "packet digest mismatch; nothing imported")
    packet = C.loads(raw)
    need(packet["experiment"] == "warrant-cross-host-smoke/1", "packet version")
    need(a.accept_provider == PROVIDER == packet["provider"], "operator provider choice")
    p = Party(a.work, "receiver", [("producer", packet["producer_public"])])
    pkg, d = packet["package"], packet["duty"]
    damaged = copy.deepcopy(pkg)
    damaged["payload"]["blobs"].pop()
    bad = p.inspect(damaged, d, "producer", packet["producer_public"])
    need(bad["delivery"]["relation"] == "MISSING_DECLARED_BYTES", bad)
    blocked = p.call("handoff", op="import", staged_id=bad["data"]["staged_id"], request_id="damaged")
    need(blocked.get("error") == "IMPORT_BLOCKED", blocked)
    seen = p.inspect(pkg, d, "producer", packet["producer_public"])
    need(seen["delivery"]["relation"] == "MATCH_EXPECTED_SET", seen)
    p.ok("handoff", op="import", staged_id=seen["data"]["staged_id"], request_id="import")
    t, seg = packet["term"], packet["paused"]
    base = {"runtime": "book1", "input": t["input"], "environment": t["environment"],
            "checkpoint": seg["checkpoint"], "state": seg["state"], "credit": 100}
    other = p.data("compute", op="term", expr="K")
    wrong = p.data("compute", op="resume", **dict(base, input=other["input"]))
    need(wrong["status"] == "REFUSED" and "segment" not in wrong, wrong)
    missing = p.call("compute", op="resume", **dict(base, checkpoint="ab" * 32))
    need(missing.get("error") == "NOT_FOUND", missing)
    invalid = p.data("compute", op="resume", **dict(base, state=t["environment"]))
    need(invalid["status"] == "REFUSED" and "segment" not in invalid, invalid)
    result = p.data("compute", op="resume", **base, target=TARGET)
    need(result["status"] == "ADVANCED" and result["base_verification"]["basis"] == "REPLAYED", result)
    need(result["segment"]["outcome"] == "NORMAL_FORM", result)
    expected = p.data("compute", op="term", expr="K I")["input"]
    need(result["segment"]["result"] == expected, result)
    bd = p.file("duty", R.duty("receiver", "the control term reduces to K I", ["producer"],
        {"compute": {"runtime": P.BOOK1, "input": t["input"], "environment": t["environment"], "expect": expected}}))
    closure = p.file("transition", R.transition("REPLAYED", [result["receipt"]],
        closes=[R.item(bd, "discharge", [result["receipt"]])],
        established=["replayed the foreign prefix and reached K I"],
        residual=["control term only; remote execution is reported, not attested"]))
    view = p.context(bd)
    need(view["data"]["capsules"][0]["disposition"] == "DISCHARGED", view)
    write(p.root / "profile.json", dict(p.profile, providers=[]))
    unaccepted = p.context(bd)
    need(unaccepted["data"]["capsules"][0]["disposition"] != "DISCHARGED", unaccepted)
    write(p.root / "profile.json", p.profile)
    acc = dict(based_on=view["view_token"], request_id="accept-handoff", type="accept",
               body={"transition": packet["transition"], "item": 0})
    draft = p.data("prepare", **acc)
    first = p.data("commit", draft_id=draft["draft_id"])
    before = len(p.store.snapshot().records)
    again = p.data("prepare", **acc)
    retry = p.data("commit", draft_id=again["draft_id"])
    need(first["record_id"] == retry["record_id"] and len(p.store.snapshot().records) == before, retry)
    need(p.context(d)["data"]["capsules"][0]["disposition"] == "DISCHARGED", "handoff not accepted")
    report = {"experiment": packet["experiment"], "packet_sha256": a.packet_sha256,
              "receiver_public": p.key.public, "provider": PROVIDER,
              "result": result, "result_duty": bd, "result_transition": closure,
              "acceptance": first["record_id"], "package": p.export(bd),
              "controls": {k: "PASS" for k in ["damaged_delivery", "wrong_root", "missing_checkpoint",
                  "wrong_state", "unaccepted_provider", "restart_retry"]},
              "remote_execution_basis": "receiver report; no machine attestation"}
    write(a.reply, report)
    compressed = base64.b64encode(zlib.compress(a.reply.read_bytes(), 9)).decode()
    print(json.dumps({"reply_sha256": C.digest(a.reply.read_bytes()), "receiver_public": p.key.public,
                      "result": result["segment"]["result"], "controls": report["controls"],
                      "reply_zlib_base64": compressed}, indent=2))


def verify(a):
    raw = a.reply.read_bytes()
    need(C.digest(raw) == a.reply_sha256, "reply digest mismatch")
    report, packet = C.loads(raw), C.loads(a.packet.read_bytes())
    need(report["packet_sha256"] == C.digest(a.packet.read_bytes()), "reply for a different packet")
    p = Party(a.work, "verifier", [("producer", packet["producer_public"]),
                                   ("receiver", report["receiver_public"])])
    seen = p.inspect(report["package"], report["result_duty"], "receiver", report["receiver_public"])
    need(seen["delivery"]["relation"] == "MATCH_EXPECTED_SET", seen)
    p.ok("handoff", op="import", staged_id=seen["data"]["staged_id"], request_id="return")
    snap = p.store.snapshot()
    good, bad = snap.authentic(Trust.load(p.root / "trust.json"))
    need(not bad and not snap.misfiled, (bad, snap.misfiled))
    expected = p.data("compute", op="term", expr="K I")["input"]
    condition = {"compute": {"runtime": P.BOOK1, "input": packet["term"]["input"],
                            "environment": packet["term"]["environment"], "expect": expected}}
    need(good[report["result_duty"]]["body"]["condition"] == condition, "reply names another task")
    result = report["result"]
    receipt = snap.json_blob(result["receipt"])
    need(receipt is not None and receipt["checkpoint"] == result["segment"]["checkpoint"]
         and receipt["state"] == result["segment"]["state"] and receipt["claimed"] == expected,
         "reply metadata does not name its receipt")
    checkpoint = snap.json_blob(receipt["checkpoint"])
    need(checkpoint is not None and checkpoint["parent_checkpoint_id"] == packet["paused"]["checkpoint"],
         "returned checkpoint does not extend the sent checkpoint")
    closure = good[report["result_transition"]]["body"]
    need(closure["basis"] == "REPLAYED" and R.item(report["result_duty"], "discharge", [result["receipt"]])
         in closure["closes"], "signed closure is not tied to the returned receipt")
    acceptance = good[report["acceptance"]]["body"]
    need(acceptance["transition"] == packet["transition"] and acceptance["item"] == 0,
         "acceptance is for another handoff")
    v = p.context(report["result_duty"])
    cap = v["data"]["capsules"][0]
    need(cap["disposition"] == "DISCHARGED" and any(x.startswith("REPLAYED:sigma-resume:") for x in cap["basis"]), cap)
    need(p.context(packet["duty"])["data"]["capsules"][0]["disposition"] == "DISCHARGED", "acceptance missing")
    print(json.dumps({"local_return_replay": "PASS", "delivery": seen["delivery"]["relation"],
                      "disposition": cap["disposition"], "basis": cap["basis"],
                      "residual": "remote execution and negative controls remain receiver-reported"}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["produce", "receive", "verify"])
    ap.add_argument("--work", type=Path, required=True, help="new private directory outside the checkout")
    ap.add_argument("--packet", type=Path, required=True)
    ap.add_argument("--packet-sha256")
    ap.add_argument("--accept-provider")
    ap.add_argument("--reply", type=Path)
    ap.add_argument("--reply-sha256")
    args = ap.parse_args()
    {"produce": produce, "receive": receive, "verify": verify}[args.mode](args)
