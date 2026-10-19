#!/usr/bin/env python3
"""The end-to-end acceptance run of warrant-agent/1 (ACCEPTANCE.md, "Наскрізний
acceptance run", steps 1-6) through one front end at a time.

    python3 acceptance.py --door python|cli|mcp [--out DIR]

Run it with the interpreter of an environment where the wheels are installed
(warrant-loops[mcp] and sigma-glyph), from outside the source checkout. Every
act of the producer and of the receivers goes through the chosen door: context,
read, handoff, prepare, commit, compute. Three things are deliberately not door
calls, because they are not the agent's to do: the reviewer's and the auditor's
own signed records (other actors, their own keys), the controller's receiver
expectation, and the receiver operator's profile choice to accept a provider.

--out keeps the whole world (stores, configs, package, transcript) as a
replayable fixture; the transcript lists every door call with its request and
result. Exit status 0 only when every step holds.
"""
import argparse
import asyncio
import concurrent.futures
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from warrant import jcs as C
from warrant import records as R
from warrant.keys import Key
from warrant.store import Store, Trust
from warrant_agent import AGENT_API, api, adapter_id
from warrant_agent.config import Config

ACTORS = ("producer", "reviewer", "auditor", "receiver", "receiver2")
PROFILE = {"uses": {"continue": {"requires_triggers": False}}, "accept_by": {"results": []}, "targets": [],
           "grant_roots": [], "challengers": ["auditor"], "providers": []}
USES = {"continue": {"delivery": ["MATCH_EXPECTED_SET", "LOCAL_CAPTURE"], "reliance": ["ELIGIBLE"], "fresh": True},
        "import": {"delivery": ["MATCH_EXPECTED_SET"]}}
TARGET = "rcv/compute"
TRANSCRIPT = []


# ---------------------------------------------------------------- front ends

class PythonDoor:
    def __init__(self, cfg_path):
        self.cfg = Config.load(cfg_path)

    def call(self, op, req):
        return api.call(self.cfg, op, req)

    def close(self):
        pass


class CliDoor:
    def __init__(self, cfg_path):
        self.cfg_path = str(cfg_path)
        self.exe = str(Path(sys.executable).parent / "warrant-agent")

    def call(self, op, req):
        p = subprocess.run([self.exe, "--config", self.cfg_path, op, "-"], input=json.dumps(req),
                           capture_output=True, text=True, check=False)
        out = json.loads(p.stdout)
        assert (p.returncode == 0) == ("ok" in out), (p.returncode, out)
        return out

    def close(self):
        pass


class McpDoor:
    """One `warrant-agent-mcp` stdio server per configuration, driven by the
    official SDK client in a background event loop."""
    TYPED = {"context": "warrant_context", "prepare": "warrant_prepare", "commit": "warrant_commit"}
    WRAPPED = {"read": "warrant_read", "handoff": "warrant_handoff", "compute": "warrant_compute"}

    def __init__(self, cfg_path):
        self.exe = str(Path(sys.executable).parent / "warrant-agent-mcp")
        self.cfg_path = str(cfg_path)
        self.ready = concurrent.futures.Future()
        self.thread = threading.Thread(target=lambda: asyncio.run(self._serve()), daemon=True)
        self.thread.start()
        self.protocol = self.ready.result(timeout=120)

    async def _serve(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        self.loop, self.queue = asyncio.get_running_loop(), asyncio.Queue()
        params = StdioServerParameters(command=self.exe, args=["--config", self.cfg_path])
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.discover()
                self.ready.set_result(s.protocol_version)
                while (item := await self.queue.get()) is not None:
                    tool, args, fut = item
                    try:
                        fut.set_result(await s.call_tool(tool, args))
                    except Exception as e:          # noqa: BLE001 - handed to the caller
                        fut.set_exception(e)

    def call(self, op, req):
        if op in self.TYPED:
            args = dict(req)
            if op == "context" and "limits" in args:
                args["context_bytes"] = args.pop("limits")["context_bytes"]
            tool = self.TYPED[op]
        else:
            tool, args = self.WRAPPED[op], {"request": req}
        fut = concurrent.futures.Future()
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (tool, args, fut))
        res = fut.result(timeout=900)
        text = res.content[0].text
        if res.is_error:
            return json.loads(text[text.index("{"):])
        assert json.loads(text) == res.structured_content
        return {"ok": res.structured_content}

    def close(self):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)
        self.thread.join(timeout=30)


DOORS = {"python": PythonDoor, "cli": CliDoor, "mcp": McpDoor}


# ---------------------------------------------------------------- the world

class Party:
    def __init__(self, base, name, signer, keys, door):
        self.base, self.name, self.keys, self.door_cls = base / name, name, keys, door
        self.base.mkdir(parents=True)
        self.store = Store(self.base / "store").init()
        (self.base / "trust.json").write_bytes(C.canon(Trust.document([(a, k.public) for a, k in keys.items()])))
        (self.base / "profile.json").write_text(json.dumps(PROFILE))
        (self.base / f"{signer}.key").write_text(keys[signer].seed_hex())
        self.doc = {"agent_api": AGENT_API, "state": str(self.base / "state"),
                    "workspaces": {name: {"store": str(self.base / "store"), "trust": str(self.base / "trust.json"),
                                          "profile": str(self.base / "profile.json"),
                                          "signer": {"actor": signer, "key": str(self.base / f"{signer}.key")},
                                          "source_name": name, "uses": USES, "expectations": {}, "limits": {}}}}
        self.door = None
        self.restart()

    def restart(self):
        """Write the operator's configuration and start a fresh front end on it."""
        if self.door:
            self.door.close()
        (self.base / "config.json").write_text(json.dumps(self.doc, indent=1))
        self.door = self.door_cls(self.base / "config.json")

    def call(self, op, req):
        req = dict(req, workspace=self.name)
        out = self.door.call(op, req)
        TRANSCRIPT.append({"party": self.name, "op": op, "request": req, "result": out})
        return out

    def ok(self, op, req):
        out = self.call(op, req)
        assert "ok" in out, (op, out)
        return out["ok"]

    def file(self, request_id, rtype, body, targets=()):
        """Prepare and commit one record as this party's configured signer."""
        view = self.ok("context", {"actor": self.doc["workspaces"][self.name]["signer"]["actor"], "use": "continue",
                                   "targets": list(targets)})
        d = self.ok("prepare", {"based_on": view["view_token"], "request_id": request_id, "type": rtype,
                                "body": body})["data"]
        return self.ok("commit", {"draft_id": d["draft_id"]})["data"]["record_id"]

    def context(self, actor, targets, **extra):
        return self.ok("context", dict({"actor": actor, "use": "continue", "targets": targets}, **extra))

    def other_actor(self, actor, rtype, body):
        """Another actor's own signed act, outside this party's door."""
        return self.store.put_record(R.record(rtype, actor, int(time.time()), body), self.keys[actor])


STEPS = {}


def step(sid, ok, what, detail=None):
    STEPS[sid] = {"pass": bool(ok), "what": what, "detail": detail}
    print(("ok    " if ok else "FAIL  ") + f"{sid} {what}" + ("" if ok else f" | {detail}"), flush=True)


def run(door, base):
    keys = {a: Key.generate() for a in ACTORS}
    src = Party(base, "src", "producer", keys, DOORS[door])
    rcv = Party(base, "rcv", "receiver", keys, DOORS[door])
    rcv2 = Party(base, "rcv2", "receiver2", keys, DOORS[door])
    # receiver 2 has its own profile: it does not count the auditor's challenges
    (rcv2.base / "profile.json").write_text(json.dumps(dict(PROFILE, challengers=[])))

    # 2. The producer's work, through the door: a reviewed duty and a paused computation
    ev = src.ok("compute", {"op": "provider"})                       # the provider is installed and named
    ev_blob = src.store.put_blob(b"candidate(-2) returns 2\n")      # the producer's working file
    d1 = src.file("d1", "duty", {"holder": "producer", "statement": "abs(-2) == 2 is implemented",
                                 "owed_to": ["reviewer"], "condition": {"attest": {}}, "accept_by": ["reviewer"]})
    t1 = src.file("t1", "transition", {"basis": "ATTESTED", "evidence": [ev_blob],
                                       "closes": [{"duty": d1, "act": "discharge", "evidence": [ev_blob]}],
                                       "established": ["abs is implemented"], "residual": ["only -2 was tried"]})
    src.other_actor("reviewer", "accept", R.accept(t1, 0, [ev_blob]))
    t = src.ok("compute", {"op": "term", "expr": "S K K (K I)"})["data"]
    s = src.ok("compute", {"op": "start", "runtime": "book1", "input": t["input"], "environment": t["environment"]})["data"]
    p = src.ok("compute", {"op": "resume", "runtime": "book1", "input": t["input"], "environment": t["environment"],
                           "checkpoint": s["checkpoint"], "state": s["state"], "credit": 2})["data"]
    seg = p["segment"]
    d2 = src.file("d2", "duty", {"holder": "producer", "statement": "hand over a resumable computation of S K K (K I)",
                                 "owed_to": ["receiver"], "condition": {"attest": {}}, "accept_by": ["receiver"]})
    cev = [seg["checkpoint"], seg["state"], t["environment"]]
    t2 = src.file("t2", "transition", {
        "basis": "ATTESTED", "evidence": cev, "closes": [{"duty": d2, "act": "discharge", "evidence": cev}],
        "established": [f"S K K (K I) started under Book I; paused at {seg['checkpoint'][:12]} ({seg['outcome']})"],
        "residual": ["the result is not computed", "the checkpoint is the producer's; a receiver must replay it"]})
    roots = [{"kind": "duty", "id": d1}, {"kind": "duty", "id": d2}]
    # the signed partial inventory: a cut exported before the auditor's challenge exists
    early = src.ok("handoff", {"op": "export", "view_token": src.context("producer", roots)["view_token"],
                               "roots": roots, "request_id": "early-cut"})["data"]
    cx = src.store.put_blob(b"candidate(-2) returns -4 on the 32-bit path\n")
    src.other_actor("auditor", "challenge", R.challenge(t1, "abs(-2) returns -4 on the 32-bit path", [cx], 0))
    full = src.ok("handoff", {"op": "export", "view_token": src.context("producer", roots)["view_token"],
                              "roots": roots, "request_id": "full-cut"})["data"]
    (base / "package.json").write_text(json.dumps(full["package"]))
    step("A2", seg["outcome"] == "PAUSED" and ev["data"]["provider"] and full["manifest_digest"] != early["manifest_digest"],
         "the producer filed duty/transition records, paused a computation and exported two signed cuts",
         seg["outcome"])

    # The controller's act: each receiver's expectation, outside any package
    for party in (rcv, rcv2):
        party.doc["workspaces"][party.name]["expectations"] = {
            "src-full": {"manifest": full["manifest_digest"], "source": "src"},
            "src-early": {"manifest": early["manifest_digest"], "source": "src"}}
        party.restart()

    def inspect(party, pkg, expectation, payload=None):
        return party.ok("handoff", {"op": "inspect", "manifest": pkg["manifest"], "payload": payload or pkg["payload"],
                                    "declaration": pkg["declaration"], "expectation": expectation, "use": "continue",
                                    "actor": party.doc["workspaces"][party.name]["signer"]["actor"], "targets": roots})

    # 3. Compact context: basis, residual and open actions, evidence read on demand only
    seen = inspect(rcv, full["package"], "src-full")
    caps = {c["target"]: c for c in seen["data"]["capsules"]}
    # the frontier names the receiver's own open action; the transition behind it is read on demand
    need = [f for f in seen["data"]["frontier"] if f["duty"] == d2]
    t2_read = rcv.ok("read", {"view_token": seen["view_token"], "kind": "record", "target": need[0]["transition"]}) \
        if need else None
    blob = rcv.ok("read", {"view_token": seen["view_token"], "kind": "blob", "target": cx})
    t2_body = json.loads(t2_read["data"]["content"])["record"]["body"] if t2_read and t2_read["data"]["complete"] else {}
    step("A3", caps[d1]["reliance"] == "CHALLENGED" and caps[d1]["challenges"] and caps[d1]["limits"] == ["only -2 was tried"]
         and caps[d2]["disposition"] == "OPEN" and need and need[0]["need"] == "accept" and need[0]["transition"] == t2
         and "the result is not computed" in t2_body.get("residual", []) and blob["data"]["untrusted_data"],
         "the receiver's own context names basis, residual, the challenge and its own open action (accept t2); "
         "the transition and the counterexample are read on demand as data",
         {"caps": {k: (v["disposition"], v["reliance"]) for k, v in caps.items()}, "frontier": seen["data"]["frontier"],
          "t2": t2_read and list(t2_read["data"])})

    # 4. Full delivery with a challenge holds; a damaged delivery holds; the signed partial matches
    damaged = dict(full["package"]["payload"],
                   blobs=[b for b in full["package"]["payload"]["blobs"] if b["id"] != cx])
    bad = inspect(rcv, full["package"], "src-full", payload=damaged)
    partial = inspect(rcv, early["package"], "src-early")
    other = inspect(rcv2, full["package"], "src-full")
    step("A4", seen["delivery"]["relation"] == "MATCH_EXPECTED_SET" and seen["use"]["state"] == "HOLD"
         and bad["delivery"]["relation"] == "MISSING_DECLARED_BYTES" and bad["use"]["state"] == "HOLD"
         and partial["delivery"]["relation"] == "MATCH_EXPECTED_SET"
         and partial["data"]["boundary"]["completeness"] == "UNATTESTED"
         and {c["target"]: c["reliance"] for c in partial["data"]["capsules"]}[d1] == "ELIGIBLE"
         and {c["target"]: c["reliance"] for c in other["data"]["capsules"]}[d1] == "ELIGIBLE"
         and other["assessment_id"] != seen["assessment_id"],
         "full+challenge HOLD; damaged delivery HOLD; the signed partial cut MATCHes with completeness "
         "UNATTESTED (residual H03, unresolved); receiver 2's own profile gives its own verdict",
         {"full": seen["use"]["state"], "damaged": (bad["delivery"]["relation"], bad["use"]["state"]),
          "partial": (partial["delivery"]["relation"], partial["use"]["state"])})

    # 5. Import, continue the computation after replay, close the receiver's own duty, accept exactly
    rcv.ok("handoff", {"op": "import", "staged_id": seen["data"]["staged_id"], "request_id": "import-full"})
    prov = rcv.ok("compute", {"op": "provider"})["data"]["provider"]
    (rcv.base / "profile.json").write_text(json.dumps(dict(PROFILE, providers=[prov], targets=[TARGET])))
    rcv.restart()                                    # the receiver operator's own choice, then a restart
    kih = rcv.ok("compute", {"op": "term", "expr": "K I"})["data"]["input"]
    bd = rcv.file("bd", "duty", {"holder": "receiver", "statement": "S K K (K I) reduces to K I", "owed_to": ["producer"],
                                 "accept_by": [], "condition": {"compute": {"runtime": "sigma-book1-0.6.0/hash-thunk/leftmost-outermost",
                                                           "input": t["input"], "environment": t["environment"],
                                                           "expect": kih}}})
    r = rcv.ok("compute", {"op": "resume", "runtime": "book1", "input": t["input"], "environment": t["environment"],
                           "checkpoint": seg["checkpoint"], "state": seg["state"], "credit": 100, "target": TARGET})["data"]
    rcv.file("close-bd", "transition", {"basis": "REPLAYED", "evidence": [r["receipt"]],
                                        "established": ["the receiver replayed the producer's prefix and finished it"],
                                        "residual": [], "closes": [{"duty": bd, "act": "discharge",
                                                                    "evidence": [r["receipt"]]}]}, targets=[])
    after = rcv.context("receiver", [{"kind": "duty", "id": bd}, {"kind": "duty", "id": d2}])
    acc = {"based_on": after["view_token"], "request_id": "accept-t2", "type": "accept", "body": {"transition": t2, "item": 0}}
    a1 = rcv.ok("prepare", acc)["data"]
    c1 = rcv.ok("commit", {"draft_id": a1["draft_id"]})["data"]
    rcv.restart()                                    # response lost, front end restarted, the agent retries
    a2 = rcv.ok("prepare", acc)["data"]
    c2 = rcv.ok("commit", {"draft_id": a2["draft_id"]})["data"]
    accepts = [p for p in (rcv.base / "store" / "records").iterdir()
               if C.loads(p.read_bytes())["record"]["type"] == "accept"
               and C.loads(p.read_bytes())["record"]["actor"] == "receiver"]
    final = {c["target"]: c for c in rcv.context("receiver", [{"kind": "duty", "id": bd},
                                                          {"kind": "duty", "id": d2}])["data"]["capsules"]}
    step("A5", r["status"] == "ADVANCED" and r["base_verification"]["basis"] == "REPLAYED"
         and r["segment"]["outcome"] == "NORMAL_FORM" and final[bd]["disposition"] == "DISCHARGED"
         and final[bd]["basis"][0].startswith("REPLAYED:") and c1["record_id"] == c2["record_id"]
         and a1["at"] == a2["at"] and len(accepts) == 1 and final[d2]["disposition"] == "DISCHARGED",
         "replay, continue and an independent final replay close the receiver's duty; the exact acceptance "
         "survives a restart and a retry as one record",
         {"resume": r["status"], "bd": final[bd]["disposition"], "accepts": len(accepts)})
    for party in (src, rcv, rcv2):
        party.door.close()
    return {"door": door, "protocol": getattr(src.door, "protocol", None), "adapter_id": adapter_id(),
            "provider": prov, "ids": {"d1": d1, "t1": t1, "d2": d2, "t2": t2, "bd": bd, "accept": c1["record_id"]},
            "manifests": {"full": full["manifest_digest"], "early": early["manifest_digest"]}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--door", choices=sorted(DOORS), required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    base = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix=f"warrant-agent-acceptance-{a.door}-"))
    base.mkdir(parents=True, exist_ok=True)
    try:
        summary = run(a.door, base)
    except AssertionError as e:
        step("RUN", False, "a door call was refused", str(e)[:400])
        summary = {"door": a.door}
    failed = sorted(k for k, v in STEPS.items() if not v["pass"])
    (base / "transcript.json").write_text(json.dumps({"summary": summary, "steps": STEPS, "calls": TRANSCRIPT},
                                                     indent=1, default=str))
    print(f"ACCEPTANCE[{a.door}]: {len(STEPS) - len(failed)} PASS / {len(failed)} FAIL"
          + (f" ({', '.join(failed)})" if failed else "") + f"  calls={len(TRANSCRIPT)}  out={base}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
