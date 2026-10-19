#!/usr/bin/env python3
"""Write and retry cases of ACCEPTANCE.md (W) through warrant_agent's API.

    python3 tests/agent_write_test.py
"""
import sys

from agent_world import Config, R, check, finish, reviewed_work, world


def ok(res):
    assert "ok" in res, res
    return res["ok"]


def context(p, targets=()):
    return ok(p.call("context", {"workspace": p.name, "actor": p.signer, "use": "continue", "targets": list(targets)}))


def main():
    src, rcv = world()
    ids = reviewed_work(src)
    # The reviewer is the signer of a third party that accepts work.
    rev = src
    rev.doc["workspaces"]["src"]["signer"] = {"actor": "reviewer", "key": str(src.base / "reviewer.key")}
    (src.base / "reviewer.key").write_text(src.keys["reviewer"].seed_hex())
    rev.reload()
    view = context(rev, [{"kind": "duty", "id": ids["duty"]}])

    # W01: an acceptance of another item or another evidence set credits nothing
    wrong_item = rev.call("prepare", {"workspace": "src", "based_on": view["view_token"], "request_id": "w1a",
                                      "type": "accept", "body": {"transition": ids["transition"], "item": 3}})
    other_ev = ok(rev.call("prepare", {"workspace": "src", "based_on": view["view_token"], "request_id": "w1b",
                                       "type": "accept", "body": {"transition": ids["transition"], "item": 0,
                                                                  "evidence": [ids["counterexample"]]}}))
    ok(rev.call("commit", {"workspace": "src", "draft_id": other_ev["data"]["draft_id"]}))
    d2 = rev.file("duty", "producer", 400, R.duty("producer", "second", ["reviewer"], {"attest": {}}, accept_by=["reviewer"]))
    ev2 = rev.blob(b"second evidence")
    t2 = rev.file("transition", "producer", 410, R.transition("ATTESTED", [ev2], closes=[R.item(d2, "discharge", [ev2])]))
    later = context(rev, [{"kind": "duty", "id": d2}])
    acc_other = ok(rev.call("prepare", {"workspace": "src", "based_on": later["view_token"], "request_id": "w1c",
                                        "type": "accept", "body": {"transition": t2, "item": 0, "evidence": [ids["evidence"]]}}))
    ok(rev.call("commit", {"workspace": "src", "draft_id": acc_other["data"]["draft_id"]}))
    after = context(rev, [{"kind": "duty", "id": d2}])
    check("W01", wrong_item.get("error") == "BAD_REQUEST" and after["data"]["capsules"][0]["disposition"] == "OPEN",
          "an accept of another item or evidence set is filed but credits nothing", after["data"]["capsules"][0])

    # W02: prepare again after a restart: the same draft, actor, at and record id
    req = {"workspace": "src", "based_on": after["view_token"], "request_id": "w2", "type": "accept",
           "body": {"transition": t2, "item": 0}}
    first = ok(rev.call("prepare", req))
    restarted = Config.load(rev.base / "config.json")
    from warrant_agent import api
    second = ok(api.call(restarted, "prepare", req))
    check("W02", first["data"] == second["data"] and first["data"]["actor"] == "reviewer",
          "a repeated prepare returns the same frozen draft", (first["data"]["record_id"], second["data"]["record_id"]))

    # W03: another body under the same request id is a CONFLICT
    clash = rev.call("prepare", dict(req, body={"transition": t2, "item": None}))
    check("W03", clash.get("error") == "CONFLICT", "a request id names one draft", clash)

    # W04: committed, the answer lost, retried after other events: the same record
    c1 = ok(rev.call("commit", {"workspace": "src", "draft_id": first["data"]["draft_id"]}))
    rev.file("transition", "producer", 500, R.transition("ATTESTED", established=["something else happened"]))
    n_before = len(list((rev.ws.store / "records").iterdir()))
    c2 = ok(api.call(Config.load(rev.base / "config.json"), "commit", {"workspace": "src",
                                                                      "draft_id": first["data"]["draft_id"]}))
    check("W04", c1["data"]["record_id"] == c2["data"]["record_id"] == first["data"]["record_id"]
          and len(list((rev.ws.store / "records").iterdir())) == n_before,
          "a retried commit returns the committed record and files nothing new", (c1["data"], c2["data"]))

    # W05: cancelled before commit stays PREPARED; after commit it is COMMITTED
    p5 = ok(rev.call("prepare", {"workspace": "src", "based_on": after["view_token"], "request_id": "w5",
                                 "type": "challenge", "body": {"target": t2, "item": 0, "statement": "doubt",
                                                               "evidence": []}}))
    s_before = ok(rev.call("read", {"workspace": "src", "kind": "draft", "target": p5["data"]["draft_id"]}))
    ok(rev.call("commit", {"workspace": "src", "draft_id": p5["data"]["draft_id"]}))
    s_after = ok(rev.call("read", {"workspace": "src", "kind": "draft", "target": p5["data"]["draft_id"]}))
    check("W05", s_before["data"]["status"] == "PREPARED" and s_after["data"]["status"] == "COMMITTED",
          "status says what happened; nothing is rolled back", (s_before["data"]["status"], s_after["data"]["status"]))

    # W06: an actor or key path in the request does not choose the signer
    in_args = rev.call("prepare", dict(req, request_id="w6a", actor="producer"))
    in_body = rev.call("prepare", {"workspace": "src", "based_on": after["view_token"], "request_id": "w6b",
                                   "type": "challenge", "body": {"target": t2, "item": 0, "statement": "x",
                                                                 "evidence": [], "key": "/tmp/k"}})
    in_commit = rev.call("commit", {"workspace": "src", "draft_id": p5["data"]["draft_id"], "signer": "producer"})
    check("W06", in_args.get("error") == in_body.get("error") == in_commit.get("error") == "BAD_REQUEST",
          "no request member selects a signer or a key", (in_args, in_body, in_commit))

    # W07: a challenge can be filed against a closure that is not ELIGIBLE
    v7 = context(rev, [{"kind": "duty", "id": ids["duty"]}])
    p7 = ok(rev.call("prepare", {"workspace": "src", "based_on": v7["view_token"], "request_id": "w7",
                                 "type": "challenge", "body": {"target": ids["transition"], "item": 0,
                                                               "statement": "still wrong", "evidence": []}}))
    c7 = rev.call("commit", {"workspace": "src", "draft_id": p7["data"]["draft_id"]})
    check("W07", v7["data"]["capsules"][0]["reliance"] == "CHALLENGED" and "ok" in c7,
          "recording a challenge is not gated by the use policy", c7)

    # W08: the configured signer changed after prepare: the old draft is not signed by the new one
    p8 = ok(rev.call("prepare", {"workspace": "src", "based_on": v7["view_token"], "request_id": "w8",
                                 "type": "challenge", "body": {"target": ids["transition"], "item": 0,
                                                               "statement": "late", "evidence": []}}))
    rev.doc["workspaces"]["src"]["signer"] = {"actor": "auditor", "key": str(src.base / "auditor.key")}
    (src.base / "auditor.key").write_text(src.keys["auditor"].seed_hex())
    rev.reload()
    c8 = rev.call("commit", {"workspace": "src", "draft_id": p8["data"]["draft_id"]})
    check("W08", c8.get("error") == "SIGNER_CHANGED"
          and not (rev.ws.store / "records" / f"{p8['data']['record_id']}.json").exists(),
          "a draft is signed only by the principal it was prepared for", c8)
    return finish("AGENT-WRITE")


if __name__ == "__main__":
    sys.exit(main())
