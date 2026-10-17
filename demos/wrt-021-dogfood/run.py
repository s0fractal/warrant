#!/usr/bin/env python3
"""WRT-021 P2: three specimens expressed as events and assessed.

    python3 demos/wrt-021-dogfood/run.py

This is a TRANSCRIPTION. Every actor here signs with a fixture key, and the actor
ids say so (`codex@transcribed`, ...): no record below is Codex's, Claude's or
the owner's own signature, and none claims to be. The git SHAs are the real ones,
checked against ~/Projects/warrant on 2026-10-17. What the transcription tests is
whether the protocol can express each case without prose doing the work, and
whether the assessment then says what actually is open.

P2a  warrant #131, finding N1 (Codex re-review of cda525e):
     the AMEND opens a QUESTION, not a duty on Claude; Claude takes it on;
     Claude's run at e2f679c is a candidate; Codex reproduces at e2f679c/416ea4a
     and accepts that exact candidate; the merge of #131 at c5ea176 is a separate
     duty, and it went into the #130 branch, so "#130 into master" stays open.
P2b  service recovery: "restore the service" is closed by a probe run, and
     "the engineer clicked done" (an attestation) is not admitted.
P2c  maintenance: a recurring key rotation, one period covered and one lapsed.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "impl"))
import loops as L    # noqa: E402
import warrant as W  # noqa: E402

CLAUDE, CODEX, OWNER, OPS = "claude@transcribed", "codex@transcribed", "owner@transcribed", "ops@transcribed"
SEEDS = {CLAUDE: "a1", CODEX: "b2", OWNER: "c3", OPS: "d4"}
CDA525E = "cda525ef77de53cc050e5409e6a8c2f7a4934e45"   # git SHA-1s, as pinned subjects
E2F679C = "e2f679c8bbad4fa12087fa3b0e9735b769d295c8"
F416EA4 = "416ea4a8f8646c4e214a1cc64dff100666ab58fa"
C5EA176 = "c5ea17612595348ad203342a1f91ee966204fe93"


class Store:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wrt021-dogfood-"))
        self.S = W.Store(str(self.tmp / ".warrants"))
        self.S.init()
        self.keys = {}
        for a, b in SEEDS.items():
            self.keys[a] = self.tmp / f"{a}.key"
            self.keys[a].write_text(b * 32 + "\n")
        self.trust = self.tmp / "trust.json"
        self.trust.write_text(json.dumps({"actors": {a: [W.pubkey_hex(W.load_key(str(k)))]
                                                     for a, k in self.keys.items()}}))
        self.policy = self.S.put_blob(b"WRT-021 dogfood: transcribed specimens, fixture keys\n")

    def blob(self, doc):
        return self.S.put_blob(doc if isinstance(doc, bytes) else L.canon(doc))

    def rec(self, decision, subject, actor, ts, prior=()):
        body = {"warrant": "0.2", "decision": decision, "subject": {"hash": subject, "note": "wrt-021 dogfood"},
                "under": [self.policy], "because": [{"kind": "prose", "text": "transcribed"}], "evidence": [],
                "actor": {"id": actor}, "prior": list(prior), "ts": ts}
        return self.S.put_record({"body": body, "sigs": [W.sign_envelope(body, actor, str(self.keys[actor]))]})

    def open(self, ts, **kw):
        return self.rec("propose", self.blob(L.duty(**kw)), kw["holder"], ts, prior=kw.get("serves", ()))

    def act(self, actor, ts, t, prior=()):
        return self.rec("propose", self.blob(t), actor, ts, prior=prior)

    def accept(self, actor, ts, duty_id, t_id, index, evidence):
        return self.rec("accept", self.blob(L.acceptance(duty_id, t_id, index, evidence)), actor, ts, prior=[t_id])


def p2a(st):
    """#131 N1. Returns the ids the checks need."""
    review_text = st.blob(b"Codex re-review of cda525e: AMEND, N1 (assessment reads the live store "
                          b"between the snapshot and verification); repro.py attached\n")
    repro = st.blob(b"repro.py: a writer restores the honest envelope between copy and verify\n")
    n1_q = st.blob(L.canon({"question": "Does assess() judge exactly the bytes it verified (N1)?",
                            "about": CDA525E}))
    # 1. Codex's review at cda525e: a transition that OPENS questions; it binds nobody.
    review = st.act(CODEX, 10, L.transition("ATTESTED", [review_text, repro], opened=[n1_q],
                                            not_established=["whether other review points hold"],
                                            scope_subject=CDA525E))
    # 2. Claude takes N1 on: a duty owed to Codex, accepted by Codex, pinned to cda525e.
    round_duty = st.open(11, holder=CLAUDE, owed_to=[CODEX], statement="answer the cda525e re-review",
                         scope_subject=CDA525E, admits=[["DISCHARGED", "ATTESTED"]], acceptance=[CODEX])
    n1 = st.open(12, holder=CLAUDE, owed_to=[CODEX], statement="fix N1", scope_subject=CDA525E,
                 admits=[["DISCHARGED", "RUNNER_ATTESTED"]], acceptance=[CODEX], serves=[round_duty],
                 answers=n1_q)
    # 3. Claude's amendment at e2f679c: regression red on cda525e, green on e2f679c; a candidate.
    run_e2f = st.blob(b"tests/assessment_test.py N1 regression: FAIL at cda525e, PASS at e2f679c; "
                      b"mutant SNAPSHOT killed\n")
    exposed = st.blob(L.canon({"question": "Is genesis.json part of the snapshot?", "about": E2F679C}))
    amend = st.act(CLAUDE, 20, L.transition("RUNNER_ATTESTED", [run_e2f],
                                            closes=[L.mapping(n1, "DISCHARGED", [run_e2f])],
                                            addresses=[n1], opened=[exposed], scope_subject=E2F679C),
                   prior=[n1])
    # 4. Codex reproduces at e2f679c and at the final 416ea4a, and accepts exactly that candidate.
    rerun = st.blob(b"Codex: repro.py against e2f679c and 416ea4a: interleaving no longer admits; "
                    b"report about the verified reject\n")
    st.act(CODEX, 30, L.transition("RECIPIENT_REEXECUTED", [rerun], relied_on=[amend],
                                   scope_subject=F416EA4), prior=[amend])
    st.accept(CODEX, 31, n1, amend, 0, [run_e2f])
    # 5. Integration is a separate duty, held by the owner; #131 went into the #130 branch.
    merge_131 = st.open(40, holder=OWNER, owed_to=[CLAUDE, CODEX], statement="integrate #131",
                        scope_subject=F416EA4, admits=[["DISCHARGED", "ATTESTED"]], acceptance=[])
    merged = st.blob(f"merge commit {C5EA176}: #131 into wrt-020/policy-binding (not master)\n".encode())
    st.act(OWNER, 41, L.transition("ATTESTED", [merged], closes=[L.mapping(merge_131, "DISCHARGED", [merged])],
                                   scope_subject=C5EA176), prior=[merge_131])
    master_130 = st.open(42, holder=OWNER, owed_to=[CLAUDE, CODEX], statement="integrate #130 into master",
                         scope_subject=C5EA176, admits=[["DISCHARGED", "ATTESTED"]], acceptance=[])
    return {"review": review, "round": round_duty, "n1": n1, "merge_131": merge_131, "master_130": master_130,
            "n1_q": n1_q, "exposed": exposed}


def p2b(st):
    up = st.open(100, holder=OPS, owed_to=[OWNER], statement="the service is functional", shape="invariant",
                 freshness=60, scope_subject="ab" * 32, admits=[["OBSERVED", "RUNNER_ATTESTED"]], acceptance=[])
    restore = st.open(101, holder=OPS, owed_to=[OWNER], statement="restore the service after incident 7",
                      scope_subject="ab" * 32, admits=[["DISCHARGED", "RUNNER_ATTESTED"]], acceptance=[],
                      serves=[up])
    clicked = st.blob(b"ticket 7: status set to Done by ops\n")
    st.act(OPS, 110, L.transition("ATTESTED", [clicked], closes=[L.mapping(restore, "DISCHARGED", [clicked])]),
           prior=[restore])
    probe = st.blob(b"probe run 2026-10-17: GET /health 200, 3/3 checks\n")
    st.act(OPS, 120, L.transition("RUNNER_ATTESTED", [probe],
                                  closes=[L.mapping(restore, "DISCHARGED", [probe]),
                                          L.mapping(up, "OBSERVED", [probe], holds=True)]),
           prior=[restore, up])
    return {"up": up, "restore": restore}


def p2c(st):
    rotate = st.open(200, holder=OPS, owed_to=[OWNER], statement="rotate the backup key every period",
                     shape="recurring", period={"start": 200, "every": 100}, scope_subject="cd" * 32,
                     admits=[["DISCHARGED", "ATTESTED"]], acceptance=[OWNER])
    done = st.blob(b"key rotated, new fingerprint recorded\n")
    t = st.act(OPS, 250, L.transition("ATTESTED", [done],
                                      closes=[L.mapping(rotate, "DISCHARGED", [done], instance=0)]),
               prior=[rotate])
    st.accept(OWNER, 260, rotate, t, 0, [done])
    return {"rotate": rotate}


def main():
    st = Store()
    a, b, c = p2a(st), p2b(st), p2c(st)
    rep = L.assess(st.S.root, st.trust, as_of=420, current={F416EA4, C5EA176})
    du = rep["duties"]
    checks = {
        "P2a N1 is DISCHARGED on the accepted candidate": du[a["n1"]]["disposition"] == "DISCHARGED",
        "P2a closing N1 does not close the review round": du[a["round"]]["disposition"] == "OPEN",
        "P2a N1 is not current at 416ea4a until revalidated": du[a["n1"]]["applicability"] == "UNASSESSED",
        "P2a #131 integration is a separate, closed duty": du[a["merge_131"]]["disposition"] == "DISCHARGED",
        "P2a #130 into master stays open": du[a["master_130"]]["disposition"] == "OPEN",
        "P2a the AMEND is kept: the review transition is in the store": st.S.get_record(a["review"]) is not None,
        "P2a the question Claude exposed binds nobody": rep["unowned_questions"] == [a["exposed"]],
        "P2b 'clicked done' is not admitted": any(x["verdict"] == "OVERCLAIMED" for x in du[b["restore"]]["candidates"]),
        "P2b the probe run discharges the restore": du[b["restore"]]["disposition"] == "DISCHARGED",
        "P2b the observation is stale by as_of, so the service is UNOBSERVED": "UNOBSERVED" in du[b["up"]]["flags"],
        "P2c period 0 covered, 1 lapsed, 2 open": du[c["rotate"]].get("instances") == {"0": "COVERED", "1": "LAPSED",
                                                                                         "2": "OPEN"},
        "no record failed verification": rep["invalid_records"] == [],
    }
    for k, v in checks.items():
        print(("ok    " if v else "FAIL  ") + k)
    for actor in (CLAUDE, CODEX, OWNER, OPS):
        print(f"\nfrontier({actor}):")
        for x in L.frontier(rep, actor):
            print(f"  {x['duty'][:12]} {json.dumps(x['disposition'])} {x['flags']}"
                  + (f" answers {x['question'][:12]}" if x["question"] else ""))
    print(f"\nunowned questions: {[q[:12] for q in rep['unowned_questions']]}")
    print("WRT-021 DOGFOOD:", "EXPRESSIBLE" if all(checks.values()) else "BROKEN", f"(store {st.S.root})")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
