#!/usr/bin/env python3
"""A paused computation handed from A to B and continued by B (S3), with the
Warrant-side cases S08 and S10 and the negative cases of ACCEPTANCE.md.

    python3 tests/agent_compute_test.py      (needs the Sigma provider installed)
"""
import json
import sys

from agent_world import PROFILE, R, check, finish, world

TARGET = "rcv/compute"


def ok(res):
    assert "ok" in res, res
    return res["ok"]


def setup():
    src, rcv = world()
    prov = ok(rcv.call("compute", {"workspace": "rcv", "op": "provider"}))["data"]["provider"]
    # The receiver's own choice: it accepts this provider and this target.
    (rcv.base / "profile.json").write_text(json.dumps(dict(PROFILE, providers=[prov], targets=[TARGET])))
    rcv.reload()
    return src, rcv, prov


def handover(src, rcv):
    """A starts the computation, pauses it on a small budget, records the work and
    a duty B must accept; exports; B inspects against its own expectation and imports."""
    c = lambda req: ok(src.call("compute", dict(req, workspace="src")))["data"]      # noqa: E731
    t = c({"op": "term", "expr": "S K K (K I)"})
    s = c({"op": "start", "runtime": "book1", "input": t["input"], "environment": t["environment"]})
    p = c({"op": "resume", "runtime": "book1", "input": t["input"], "environment": t["environment"],
           "checkpoint": s["checkpoint"], "state": s["state"], "credit": 2})
    seg = p["segment"]
    d = src.file("duty", "producer", 100, R.duty("producer", "hand over a resumable computation of S K K (K I)",
                                                 ["receiver"], {"attest": {}}, accept_by=["receiver"]))
    ev = [seg["checkpoint"], seg["state"], t["environment"]]
    tr = src.file("transition", "producer", 110, R.transition(
        "ATTESTED", ev, closes=[R.item(d, "discharge", ev)],
        established=[f"S K K (K I) started under Book I; paused at checkpoint {seg['checkpoint'][:12]} "
                     f"(outcome {seg['outcome']})"],
        residual=["the result is not computed", "the checkpoint is the producer's; a receiver must replay it"]))
    ctx = ok(src.call("context", {"workspace": "src", "actor": "producer", "use": "continue",
                                  "targets": [{"kind": "duty", "id": d}]}))
    out = ok(src.call("handoff", {"op": "export", "workspace": "src", "view_token": ctx["view_token"],
                                  "roots": [{"kind": "duty", "id": d}], "request_id": "e1"}))
    rcv.expect("src-cut", out["data"]["manifest_digest"], source="src")
    pkg = out["data"]["package"]
    seen = ok(rcv.call("handoff", {"op": "inspect", "workspace": "rcv", "manifest": pkg["manifest"],
                                   "payload": pkg["payload"], "expectation": "src-cut", "actor": "receiver",
                                   "targets": [{"kind": "duty", "id": d}]}))
    ok(rcv.call("handoff", {"op": "import", "workspace": "rcv", "staged_id": seen["data"]["staged_id"],
                            "request_id": "i1"}))
    return {"term": t, "paused": seg, "duty": d, "transition": tr, "inspected": seen}


def main():
    src, rcv, prov = setup()
    h = handover(src, rcv)
    t, seg = h["term"], h["paused"]
    rc = lambda req: rcv.call("compute", dict(req, workspace="rcv"))                 # noqa: E731
    base = {"runtime": "book1", "input": t["input"], "environment": t["environment"]}
    # B's own duty: the computation's answer, closed only by B's replay of a receipt.
    kih = ok(rc({"op": "term", "expr": "K I"}))["data"]["input"]
    bd = rcv.file("duty", "receiver", 200, R.duty("receiver", "S K K (K I) reduces to K I", ["producer"],
                                                  {"compute": {"runtime": "sigma-book1-0.6.0/hash-thunk/leftmost-outermost",
                                                               "input": t["input"], "environment": t["environment"],
                                                               "expect": kih}}))

    # S01 end to end: B continues A's checkpoint through checked resume, files the
    # replayed closure, and its own assessment discharges the duty
    r = ok(rc(dict(base, op="resume", checkpoint=seg["checkpoint"], state=seg["state"], credit=100, target=TARGET)))["data"]
    view = ok(rcv.call("context", {"workspace": "rcv", "actor": "receiver", "use": "continue",
                                   "targets": [{"kind": "duty", "id": bd}]}))
    draft = ok(rcv.call("prepare", {"workspace": "rcv", "based_on": view["view_token"], "request_id": "close-bd",
                                    "type": "transition", "body": {
                                        "basis": "REPLAYED", "evidence": [r["receipt"]],
                                        "established": ["B replayed A's prefix and finished the computation"],
                                        "residual": [], "closes": [{"duty": bd, "act": "discharge",
                                                                    "evidence": [r["receipt"]]}]}}))
    ok(rcv.call("commit", {"workspace": "rcv", "draft_id": draft["data"]["draft_id"]}))
    after = ok(rcv.call("context", {"workspace": "rcv", "actor": "receiver", "use": "continue",
                                    "targets": [{"kind": "duty", "id": bd}]}))
    cap = after["data"]["capsules"][0]
    check("E2E", h["inspected"]["delivery"]["relation"] == "MATCH_EXPECTED_SET" and seg["outcome"] == "PAUSED"
          and r["status"] == "ADVANCED" and r["base_verification"]["basis"] == "REPLAYED"
          and r["segment"]["outcome"] == "NORMAL_FORM" and cap["disposition"] == "DISCHARGED"
          and cap["basis"][0].startswith("REPLAYED:sigma-resume:"),
          "A's paused computation is continued by B after replay and closes B's own condition", (r["status"], cap))

    # Exact acceptance of A's handoff closure by B, retried after a restart
    from agent_world import Config, api
    acc = {"workspace": "rcv", "based_on": after["view_token"], "request_id": "accept-handoff", "type": "accept",
           "body": {"transition": h["transition"], "item": 0}}
    a1 = ok(rcv.call("prepare", acc))
    c1 = ok(rcv.call("commit", {"workspace": "rcv", "draft_id": a1["data"]["draft_id"]}))
    restarted = Config.load(rcv.base / "config.json")
    a2 = ok(api.call(restarted, "prepare", acc))
    c2 = ok(api.call(restarted, "commit", {"workspace": "rcv", "draft_id": a2["data"]["draft_id"]}))
    hd = ok(rcv.call("context", {"workspace": "rcv", "actor": "receiver", "use": "continue",
                                 "targets": [{"kind": "duty", "id": h["duty"]}]}))
    check("ACCEPT", c1["data"]["record_id"] == c2["data"]["record_id"] and a1["data"]["at"] == a2["data"]["at"]
          and hd["data"]["capsules"][0]["disposition"] == "DISCHARGED",
          "B's exact acceptance survives a restart and retry as one record", (c1["data"], c2["data"]))

    # Negative cases: none of them closes anything
    other = ok(rc({"op": "term", "expr": "K"}))["data"]
    wrong_root = ok(rc(dict(base, op="resume", input=other["input"], checkpoint=seg["checkpoint"],
                            state=seg["state"], credit=100)))["data"]
    wrong_env = ok(rc(dict(base, op="resume", environment=other["environment"], checkpoint=seg["checkpoint"],
                           state=seg["state"], credit=100)))["data"]
    wrong_bytes = rc(dict(base, op="resume", checkpoint=seg["checkpoint"], state=t["environment"], credit=100))
    unknown = rc(dict(base, op="resume", checkpoint="ab" * 32, state=seg["state"], credit=100))
    check("S-NEG", wrong_root["status"] == "REFUSED" and "segment" not in wrong_root
          and wrong_env["status"] == "REFUSED"
          and wrong_bytes.get("ok", {}).get("data", {}).get("status") == "REFUSED"
          and "segment" not in wrong_bytes["ok"]["data"]
          and unknown.get("error") == "NOT_FOUND",
          "wrong root, wrong environment and wrong bytes continue nothing; absent bytes are not fetched",
          (wrong_root["status"], wrong_env["status"], wrong_bytes, unknown.get("error")))

    # S08: a provider the receiver did not accept gives no Warrant credit
    (rcv.base / "profile.json").write_text(json.dumps(dict(PROFILE, providers=[], targets=[TARGET])))
    rcv.reload()
    no_credit = ok(rcv.call("context", {"workspace": "rcv", "actor": "receiver", "use": "continue",
                                        "targets": [{"kind": "duty", "id": bd}]}))
    provider_view = ok(rc({"op": "provider"}))["data"]
    check("S08", no_credit["data"]["capsules"][0]["disposition"] == "OPEN"
          and provider_view["provider_accepted_by_profile"] is False and json.loads(
              (rcv.base / "profile.json").read_text())["providers"] == [],
          "computing is not accepting: the profile is untouched and REPLAYED is not credited",
          no_credit["data"]["capsules"][0]["disposition"])
    (rcv.base / "profile.json").write_text(json.dumps(dict(PROFILE, providers=[prov], targets=[TARGET])))
    rcv.reload()

    # S10: the bytes verified are the bytes advanced, even if the store changes
    # mid-request: compute reads the store once; a state replaced afterwards under
    # another name changes nothing already captured.
    from warrant_agent import computeops
    real_call = computeops._call

    def swap_then_call(ws, provider, op, args, blobs):
        (rcv.ws.store / "blobs" / seg["state"]).write_bytes(b"swapped after capture")
        return real_call(ws, provider, op, args, blobs)
    computeops._call = swap_then_call
    try:
        s10 = ok(rc(dict(base, op="resume", checkpoint=seg["checkpoint"], state=seg["state"], credit=100)))["data"]
    finally:
        computeops._call = real_call
        (rcv.ws.store / "blobs" / seg["state"]).write_bytes((src.ws.store / "blobs" / seg["state"]).read_bytes())
    check("S10", s10["status"] == "ADVANCED" and s10["segment"]["result"] == r["segment"]["result"],
          "the captured bytes are verified and advanced; a later swap on disk is not used", s10["status"])

    # S11: a claimed result whose receipt disagrees with the receiver's own replay is not credited, and the
    # capsules say so on the duty and on the transition (examples/mcp-first-contact, T1)
    from warrant import jcs as C
    sks = ok(rc({"op": "term", "expr": "S K S K"}))["data"]
    s_in = ok(rc({"op": "term", "expr": "S"}))["data"]["input"]
    b2 = dict(base, input=sks["input"], environment=sks["environment"])
    st = ok(rc(dict(b2, op="start")))["data"]
    fin = ok(rc(dict(b2, op="resume", checkpoint=st["checkpoint"], state=st["state"], credit=100, target=TARGET)))["data"]
    real = C.loads((rcv.ws.store / "blobs" / fin["receipt"]).read_bytes())
    lie = rcv.blob(C.canon(dict(real, claimed=s_in)))
    wd = rcv.file("duty", "producer", 300, R.duty("producer", "S K S K reduces to S", ["receiver"],
                                                  {"compute": {"runtime": "sigma-book1-0.6.0/hash-thunk/leftmost-outermost",
                                                               "input": sks["input"], "environment": sks["environment"],
                                                               "expect": s_in}}))
    wt = rcv.file("transition", "producer", 310, R.transition("REPLAYED", [lie], closes=[R.item(wd, "discharge", [lie])],
                                                              established=["S K S K reduces to S"], residual=[]))
    seen = ok(rcv.call("context", {"workspace": "rcv", "targets": [wd, wt]}))
    caps = {c["target"]: c for c in seen["data"]["capsules"]}
    dc, tc = caps[wd], caps[wt]
    check("S11", fin["segment"]["result"] != s_in and dc["disposition"] == "OPEN" and dc["reliance"] == "NOT_CLOSED"
          and [(c["verdict"], c.get("why")) for c in dc["closures"]] == [("UNVERIFIED", "the recipient's replay disagrees with the receipt")]
          and [(c["duty"], c["verdict"], c.get("why"), c["duty_disposition"]) for c in tc["closes"]]
          == [(wd, "UNVERIFIED", "the recipient's replay disagrees with the receipt", "OPEN")],
          "a receipt whose claim the receiver's replay contradicts closes nothing, and both capsules say why",
          (dc.get("closures"), tc.get("closes")))

    # S12: evaluate is the receiver's own run: it compares normal forms and files nothing
    n_records = len(list((rcv.ws.store / "records").iterdir()))
    good = ok(rc({"op": "evaluate", "expr": "S K K (K I)", "expect_expr": "K I"}))["data"]
    bad = ok(rc({"op": "evaluate", "expr": "S K S K", "expect_expr": "S"}))["data"]
    short = ok(rc({"op": "evaluate", "expr": "S K S K", "expect_expr": "K", "credit": 1}))["data"]
    check("S12", good["outcome"] == "NORMAL_FORM" and good["same_normal_form"] is True
          and bad["outcome"] == "NORMAL_FORM" and bad["same_normal_form"] is False and bad["result"] == fin["segment"]["result"]
          and short["outcome"] != "NORMAL_FORM" and short["same_normal_form"] is False
          and len(list((rcv.ws.store / "records").iterdir())) == n_records,
          "evaluate says whether the normal form is the expected term, never for an unfinished run, and files nothing",
          (good.get("same_normal_form"), bad.get("same_normal_form"), short.get("outcome")))

    # S07 (Warrant side): a provider stopped by the host deadline returns no state
    rcv.doc["workspaces"]["rcv"]["limits"] = {"provider_seconds": 0.01}
    rcv.reload()
    n_blobs = len(list((rcv.ws.store / "blobs").iterdir()))
    killed = rc(dict(base, op="resume", checkpoint=seg["checkpoint"], state=seg["state"], credit=100))
    stored_nothing = len(list((rcv.ws.store / "blobs").iterdir())) == n_blobs
    rcv.doc["workspaces"]["rcv"]["limits"] = {}
    rcv.reload()
    capped = ok(rc(dict(base, op="resume", checkpoint=seg["checkpoint"], state=seg["state"], credit=100,
                        max_actions=1)))["data"]
    check("S07", killed.get("error") == "PROVIDER" and stored_nothing
          and capped["segment"]["outcome"] == "INCOMPLETE",
          "a hard stop stores nothing; an action limit returns an atomic checkpoint", (killed, capped["segment"]))
    return finish("AGENT-COMPUTE")


if __name__ == "__main__":
    sys.exit(main())
