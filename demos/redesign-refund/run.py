#!/usr/bin/env python3
"""The redesign's acceptance scenario (§25), end to end, offline.

    python3 demos/redesign-refund/run.py

One refund request against a rule limit:

 1. the recipient admits a policy program, one obligation and one fact issuer;
 2. the issuer attests the amount; the rule is compiled by a registered compiler;
 3. the policy's term runs on the sigma-resume kernel and is cut by an action
    limit: INCOMPLETE, with credit left unused, and the checkpoint goes to disk;
 4. a second producer, a separate process with only those files, verifies that
    checkpoint by replay (REPLAYED, PREFIX: reachable, not terminal) and finishes
    it with the credit it already carries;
 5. the computation reaches NORMAL_FORM: the policy answers FALSE, and warrant's
    own ski@v1 replay of the same check agrees;
 6. a signed accept is a well-formed record, and the assessment calls it
    CONTRADICTED_DECISION; the consumer does not act;
 7. a witness records the refusal: a reject, which is COMPLIANT;
 8. filing the same decision again (more progress, another checkpoint) is not a
    new consequence;
 9. a new admitted observation in the named slot is NEW_EVIDENCE (same answer,
    a new accepted value); another, under which the policy answers TRUE, is a
    NEW_CONSEQUENCE, and its accept is COMPLIANT;
10. everything above ran from this directory alone (tests/redesign_demo_offline.py
    runs it in a fresh one).

Draft: the kernel is vendored from a LOCAL, unpushed sigma-glyph branch
(vendor/sigma/PIN.json), and the assessment is the draft P3/P4 reference.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE / "vendor" / "sigma", HERE.parents[1] / "impl"):
    sys.path.insert(0, str(p))
import sigma_glyph as SG      # noqa: E402  (vendored kernel)
import sigma_resume as R      # noqa: E402
import assessment as A        # noqa: E402
import warrant as W           # noqa: E402

OBL = "refund_within_limit"
RULE = "amount <= 50000"
DESK, ISSUER, AUDITOR = "desk@shop", "issuer@bank", "auditor@shop"
S3, S45, S6, S7 = "3 producer A", "4-5 producer B", "6 accept", "7 witness reject"
S8, S9, S9R = "8 more ATP", "9 new observation", "9 reassessed"
WORK_ENV = "REDESIGN_DEMO_WORK"     # producer B learns the work dir here, never from argv


def kernel_env(store):
    """The frozen environment of the computation: every blob in the store."""
    hashes = [bytes.fromhex(p.name) for p in store.blobs.iterdir() if len(p.name) == 64]
    delivered = {h: (store.blobs / h.hex()).read_bytes() for h in hashes}
    return R.Environment(hashes, delivered)


def producer_b(work):
    """Step 4, a separate process: it has the files, not producer A's memory.
    The directory comes from the environment producer A set, not from argv."""
    store = W.Store(str(work / "store"))
    env = kernel_env(store)
    term = bytes.fromhex(json.loads((work / "task.json").read_text())["term"])
    expected_root = R.root(term, env)
    raw, state = (work / "checkpoint.json").read_bytes(), (work / "state.bin").read_bytes()
    basis, code, _ = R.verify(expected_root, env, raw, state)
    if basis != R.REPLAYED:
        print(json.dumps({"refused": code}))
        return 1
    doc, cid = R.parse_checkpoint(raw)
    done = R.advance(doc, cid, state, env, 0)          # the credit it carries is enough
    out = {"basis": basis, "verified_as": code, "outcome": done.outcome, "spent": done.checkpoint["spent_total"],
           "result_hash": SG.term_hash(done.term()).hex()}
    print(json.dumps(out))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--producer-b", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.producer_b:
        return producer_b(Path(os.environ[WORK_ENV]))
    work = Path(tempfile.mkdtemp(prefix="redesign-demo-"))   # always new: no path is taken from argv
    store = W.Store(str(work / "store"))
    store.init()
    keys = {}
    for actor, b in {DESK: "44", ISSUER: "55", AUDITOR: "77"}.items():
        keys[actor] = work / f"{actor}.key"
        keys[actor].write_text(b * 32 + "\n")
    trust = work / "trust.json"
    trust.write_text(json.dumps({"actors": {a: [W.pubkey_hex(W.load_key(str(k)))] for a, k in keys.items()}}))
    steps, ts = {}, [0]

    def record(decision, subject, under, actor, because=()):
        ts[0] += 1
        body = {"warrant": "0.2", "decision": decision, "subject": {"hash": subject, "note": "demo"},
                "under": under, "because": list(because), "evidence": [], "actor": {"id": actor},
                "prior": [], "ts": ts[0]}
        return store.put_record({"body": body, "sigs": [W.sign_envelope(body, actor, str(keys[actor]))]})

    def observe(amount):
        attest_rules = store.put_blob(b"issuer@bank attests observed amounts\n")
        return record("accept", store.put_blob(A._canon(A.observation(OBL, "amount", amount))),
                      [attest_rules], ISSUER)

    # 1-2. recipient profile; attested fact; compilation by a registered compiler
    prog = A.program(OBL, {"amount": "int"}, RULE)
    prof = A.profile([A.blob_id(prog)], OBL, trust, [ISSUER], True, evidence_slots=["amount"])
    facts = A.fact_set(OBL, {"amount": A.observed(65088, observe(65088))})
    pl = A.plan(prog, facts, put=store.put_blob)
    term = bytes.fromhex(json.loads((store.blobs / pl["emitted"]["check"]).read_bytes())["term"])
    (work / "task.json").write_text(json.dumps({"term": term.hex()}))

    # 3. producer A: an action limit cuts the run; the unused credit stays in the checkpoint
    env = kernel_env(store)
    rt = R.root(term, env)
    doc, cid, sb = R.start(rt[1], term)
    cut = R.advance(doc, cid, sb, env, 1000, max_actions=10)
    (work / "checkpoint.json").write_bytes(R._canon(cut.checkpoint))
    (work / "state.bin").write_bytes(cut.state_bytes)
    steps[S3] = {"outcome": cut.outcome, "credit": cut.checkpoint["credit_total"],
                 "spent": cut.checkpoint["spent_total"]}

    # 4-5. producer B in its own process; the answer, cross-checked with ski@v1
    b = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--producer-b"],
                       env=dict(os.environ, **{WORK_ENV: str(work)}), capture_output=True, text=True, check=False)
    pb = json.loads(b.stdout)
    false_h = SG.term_hash(("app", SG.KG, SG.IG)).hex()
    _, ski_answer = A.replay_answer(store, pl["emitted"]["check"])
    steps[S45] = dict(pb, answer="FALSE" if pb.get("result_hash") == false_h else "?",
                                   ski_v1_answer=ski_answer)

    # 6. the signed accept, assessed
    subject = store.put_blob(b"refund request #1: 650.88\n")
    acc = A.write_decision(store, "accept", subject, prog, facts, pl, DESK, keys[DESK], ts=100)
    r6 = A.assess(store.root, acc, prof)
    steps[S6] = {"record_integrity": r6["axes"]["record_integrity"],
                         "decision_compliance": r6["axes"]["decision_compliance"],
                         "consumer_admits_action": r6["consumer_admits_action"]}

    # 7. the witness keeps the refusal
    rej = A.write_decision(store, "reject", subject, prog, facts, pl, AUDITOR, keys[AUDITOR], ts=101)
    steps[S7] = A.assess(store.root, rej, prof)["axes"]["decision_compliance"]

    # 8. the same decision filed again: progress is not a new consequence
    again = A.write_decision(store, "accept", subject, prog, facts, pl, DESK, keys[DESK], ts=103)
    steps[S8] = {"novelty": A.novelty(r6, A.assess(store.root, again, prof), prof)}

    # 9. new admitted observations in the named slot
    facts_e = A.fact_set(OBL, {"amount": A.observed(70000, observe(70000))})      # still over the limit
    acc_e = A.write_decision(store, "accept", subject, prog, facts_e, A.plan(prog, facts_e, put=store.put_blob),
                             DESK, keys[DESK], ts=104)
    steps[S9] = {"novelty": A.novelty(r6, A.assess(store.root, acc_e, prof), prof)}
    facts2 = A.fact_set(OBL, {"amount": A.observed(12000, observe(12000))})
    pl2 = A.plan(prog, facts2, put=store.put_blob)
    acc2 = A.write_decision(store, "accept", subject, prog, facts2, pl2, DESK, keys[DESK], ts=102)
    r9 = A.assess(store.root, acc2, prof)
    steps[S9R] = {"decision_compliance": r9["axes"]["decision_compliance"],
                  "novelty": A.novelty(r6, r9, prof), "consumer_admits_action": r9["consumer_admits_action"]}

    expected = {
        S3: steps[S3]["outcome"] == "INCOMPLETE" and steps[S3]["credit"] > steps[S3]["spent"],
        S45: pb.get("basis") == "REPLAYED" and pb.get("verified_as") == "PREFIX" and pb.get("outcome") == "NORMAL_FORM"
        and steps[S45]["answer"] == "FALSE" and ski_answer == "FALSE",
        S6: r6["axes"]["record_integrity"] == "VERIFIED"
        and r6["axes"]["decision_compliance"] == "CONTRADICTED_DECISION" and not r6["consumer_admits_action"],
        S7: steps[S7] == "COMPLIANT",
        S8: steps[S8]["novelty"] == "NO_NEW_CONSEQUENCE",
        S9: steps[S9]["novelty"] == "NEW_EVIDENCE",
        S9R: r9["axes"]["decision_compliance"] == "COMPLIANT"
        and steps[S9R]["novelty"] == "NEW_CONSEQUENCE" and r9["consumer_admits_action"],
    }
    for k, v in steps.items():
        print(("ok    " if expected.get(k, True) else "FAIL  ") + f"{k}: {json.dumps(v)}")
    ok = all(expected.values())
    print("REDESIGN DEMO:", "SCENARIO HOLDS" if ok else "SCENARIO BROKEN", f"(work dir {work})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
