#!/usr/bin/env python3
"""impl/assessment.py (draft P3/P4 reference) against the redesign's matrix,
N38-N60. Every store is built with warrant's own Store and signer; every
verdict is the assessment's typed axis, checked by name.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import os  # noqa: E402
# ASSESSMENT_IMPL lets tests/assessment_mutants.py run this file against a mutated copy.
sys.path.insert(0, str(ROOT / "impl"))
if os.environ.get("ASSESSMENT_IMPL"):
    sys.path.insert(0, os.environ["ASSESSMENT_IMPL"])
import assessment as A   # noqa: E402
import warrant as W      # noqa: E402

results = {}
OBL = "refund_within_limit"
KEYS = {"a@x": "44", "i@x": "55", "m@x": "66"}


def case(nid, ok, what, detail=""):
    results[nid] = "PASS" if ok else "FAIL"
    print(("ok    " if ok else "FAIL  ") + f"{nid} {what}" + ("" if ok else f" | {detail}"))


def unrun(nid, why):
    results[nid] = "UNRUN"
    print(f"UNRUN {nid} {why}")


class Case:
    """One store, two honest actors (approver a@x, fact issuer i@x) and mallory."""

    def __init__(self, trusted=("a@x", "i@x")):
        self.tmp = Path(tempfile.mkdtemp(prefix="assess-"))
        self.S = W.Store(str(self.tmp / "s"))
        self.S.init()
        self.keys = {}
        for actor, b in KEYS.items():
            k = self.tmp / f"{actor}.key"
            k.write_text(b * 32 + "\n")
            self.keys[actor] = k
        self.trust = self.tmp / "trust.json"
        self.trust.write_text(json.dumps({"actors": {a: [W.pubkey_hex(W.load_key(str(self.keys[a])))]
                                                     for a in trusted}}))
        self.ts = 0

    def blob(self, doc):
        return self.S.put_blob(doc if isinstance(doc, bytes) else A._canon(doc))

    def record(self, decision, subject, under=(), because=(), actor="a@x", evidence=()):
        self.ts += 1
        body = {"warrant": "0.2", "decision": decision, "subject": {"hash": subject, "note": "case"},
                "under": list(under), "because": list(because), "evidence": list(evidence),
                "actor": {"id": actor}, "prior": [], "ts": self.ts}
        return self.S.put_record({"body": body, "sigs": [W.sign_envelope(body, actor, str(self.keys[actor]))]})

    def attest(self, name, value, issuer="i@x"):
        rules = self.blob(b"issuer attestation: we observed this value\n")
        return self.record("accept", self.blob(A.observation(OBL, name, value)), [rules], actor=issuer)

    def decision(self, decision, amount, *, rule="amount <= 50000", options=None, compiler=None,
                 reason="own", issuer="i@x", actor="a@x"):
        prog = A.program(OBL, {"amount": "int"}, rule)
        facts = A.fact_set(OBL, {"amount": A.observed(amount, self.attest("amount", amount, issuer))})
        pl = A.plan(prog, facts, options, put=self.S.put_blob, **({"compiler": compiler} if compiler else {}))
        under = [self.blob(prog), self.blob(facts), self.blob(pl)]
        check = pl["emitted"]["check"] if reason == "own" else reason
        because = [{"kind": "check", "check": check, "runtime": "ski@v1", "verdict": "pass"}] if check else []
        rec = self.record(decision, self.blob(b"refund request\n"), under, because, actor=actor)
        return rec, A.blob_id(prog)

    def profile(self, programs, **kw):
        return A.profile(programs, OBL, self.trust, ["i@x"], **kw)


def assess(c, rec, prof):
    return A.assess(c.S.root, rec, prof)


def ax(rep, name):
    return rep["axes"][name]


def main():
    # ------------------------------------------------------------ P3
    c = Case()
    rec, pid = c.decision("accept", 65088)
    r38 = assess(c, rec, c.profile([pid]))
    case("N38", ax(r38, "record_integrity") == "VERIFIED" and ax(r38, "policy_answer") == "FALSE"
         and ax(r38, "decision_compliance") == "CONTRADICTED_DECISION" and not r38["consumer_admits_action"],
         "signed accept, own compilation answering FALSE: record VERIFIED, decision CONTRADICTED", r38["axes"])

    c = Case()
    rec, pid = c.decision("accept", 12000)
    r39 = assess(c, rec, c.profile([pid]))
    case("N39", ax(r39, "decision_compliance") == "COMPLIANT" and r39["consumer_admits_action"],
         "TRUE, every requirement met: COMPLIANT, and the consumer admits the action", r39["axes"])

    c = Case()
    prose = c.blob(b"DENY_ALL: no change may be accepted under this policy.\n")
    rec = c.record("accept", c.blob(b"PR-1\n"), [prose], [])
    r40 = assess(c, rec, c.profile([]))
    r40w = assess(c, rec, c.profile([], required="witness"))
    case("N40", ax(r40, "record_integrity") == "VERIFIED" and ax(r40, "decision_compliance") == "NOT_ASSESSED"
         and not r40["consumer_admits_action"] and ax(r40w, "required_profile") == "SATISFIED"
         and not r40w["consumer_admits_action"],
         "prose policy: the witness is valid, compliance NOT_ASSESSED, nothing admitted", (r40["axes"], r40w["axes"]))

    c = Case()
    other_prog = A.program(OBL, {"amount": "int"}, "amount <= 99999999")
    other_facts = A.fact_set(OBL, {"amount": A.observed(65088, "x")})
    foreign = A.plan(other_prog, other_facts, put=c.S.put_blob)["emitted"]["check"]
    rec, pid = c.decision("accept", 65088, reason=foreign)
    r41 = assess(c, rec, c.profile([pid]))
    case("N41", ax(r41, "compilation_binding") == "COMPILATION_MISMATCH" and not r41["consumer_admits_action"],
         "WPL policy, reason runs another compiled term: COMPILATION_MISMATCH", r41["axes"])

    c = Case()
    rec_b, pid = c.decision("accept", 12000)
    rec_h, _ = c.decision("accept", 12000, options={"atp_headroom": 1000})
    rb, rh = assess(c, rec_b, c.profile([pid])), assess(c, rec_h, c.profile([pid]))
    case("N42", ax(rh, "compilation_binding") == "MATCHED_COMPILATION" and ax(rh, "policy_answer") == ax(rb, "policy_answer"),
         "more execution budget (headroom 1000): same binding, same answer", rh["axes"])
    rec_lie, _ = c.decision("accept", 12000, options={"atp_headroom": 1})
    pl_blob = json.loads((c.S.blobs / _under(c, rec_lie)[2]).read_bytes())
    pl_blob["options"] = {}                     # the plan now claims defaults for a headroom-1 check
    r43 = assess(c, _swap_under(c, rec_lie, 2, c.blob(pl_blob)), c.profile([pid]))
    rec_emit, _ = c.decision("accept", 12000)
    pl_emit = json.loads((c.S.blobs / _under(c, rec_emit)[2]).read_bytes())
    pl_emit["emitted"]["check"] = "00" * 32     # the plan misstates what it emitted; the reason is honest
    r43e = assess(c, _swap_under(c, rec_emit, 2, c.blob(pl_emit)), c.profile([pid]))
    case("N43", ax(rh, "compilation_binding") == "MATCHED_COMPILATION" and ax(r43, "compilation_binding") == "COMPILATION_MISMATCH"
         and ax(r43e, "compilation_binding") == "COMPILATION_MISMATCH",
         "declared options and emitted check are what is checked: honest MATCHED; misdeclared options "
         "or a misstated emitted check MISMATCH", (r43["axes"], r43e["axes"]))

    c = Case()
    rec, pid = c.decision("accept", 12000, compiler="producer-compiler@1/evil.sh")
    r44 = assess(c, rec, c.profile([pid]))
    case("N44", ax(r44, "compilation_binding") == "UNREGISTERED_COMPILER",
         "a compiler the plan names but this verifier does not have: refused, nothing executed", r44["axes"])

    c = Case()
    rec, loose_pid = c.decision("accept", 65088, rule="amount <= 99999999")
    strict_pid = A.blob_id(A.program(OBL, {"amount": "int"}, "amount <= 50000"))
    r45a = assess(c, rec, c.profile([strict_pid]))
    c2 = Case(trusted=("a@x", "i@x"))
    rec_m, pid_m = c2.decision("accept", 12000, actor="m@x")
    r45b = assess(c2, rec_m, c2.profile([pid_m]))
    case("N45", ax(r45a, "policy_authority") == "AUTHORITY_UNESTABLISHED" and not r45a["consumer_admits_action"]
         and ax(r45b, "record_integrity") == "INVALID" and not r45b["consumer_admits_action"],
         "producer picks a looser policy, or signs with a key the recipient does not trust: refused",
         (r45a["axes"], r45b["axes"]))

    c = Case()
    rec, pid = c.decision("accept", 12000)
    r46 = assess(c, rec, c.profile([pid]))
    c3 = Case(trusted=("a@x", "i@x", "m@x"))
    rec_u, pid_u = c3.decision("accept", 12000, issuer="m@x")
    r46u = assess(c3, rec_u, c3.profile([pid_u]))
    case("N46", ax(r46, "fact_provenance") == "ACCEPTED" and "TRUE" not in ax(r46, "fact_provenance")
         and ax(r46u, "fact_provenance") == "UNATTESTED",
         "observed fact from an admitted issuer: ACCEPTED (an attestation, not a truth); a bound but "
         "unadmitted issuer: UNATTESTED", (r46["axes"], r46u["axes"]))

    c = Case()
    src_rec, _ = c.decision("accept", 65088)            # its policy answers FALSE
    src_check = json.loads((c.S.blobs / _under(c, src_rec)[2]).read_bytes())["emitted"]["check"]
    prog = A.program(OBL, {"eligible": "bool"}, "eligible")
    facts = A.fact_set(OBL, {"eligible": A.derived(True, src_rec, src_check)})   # claims TRUE
    pl = A.plan(prog, facts, put=c.S.put_blob)
    rec = c.record("accept", c.blob(b"x\n"), [c.blob(prog), c.blob(facts), c.blob(pl)],
                   [{"kind": "check", "check": pl["emitted"]["check"], "runtime": "ski@v1", "verdict": "pass"}])
    r47 = assess(c, rec, c.profile([A.blob_id(prog)]))
    case("N47", ax(r47, "fact_provenance") == "DERIVATION_MISMATCH" and not r47["consumer_admits_action"],
         "derived fact claims TRUE, its cited check answers FALSE: DERIVATION_MISMATCH", r47["axes"])

    c = Case()
    rec, pid = c.decision("reject", 12000)
    strict = assess(c, rec, c.profile([pid], discretionary_reject=False))
    lenient = assess(c, rec, c.profile([pid], discretionary_reject=True))
    case("N48", ax(strict, "decision_compliance") == "CONTRADICTED_DECISION"
         and ax(lenient, "decision_compliance") == "COMPLIANT",
         "reject while the policy says TRUE: CONTRADICTED unless the recipient allows discretion",
         (strict["axes"], lenient["axes"]))

    case("N49", ax(r40, "required_profile") == "REQUIRED_PROFILE_NOT_SATISFIED",
         "recipient requires a policy decision, the record is only a witness: not satisfied")

    c = Case()
    paused = _low_budget_check(c)
    comp, answer = A.replay_answer(c.S, paused)
    case("N50", comp == "PAUSED" and answer == "NOT_ASSESSED" and A.decide("accept", answer, True) == "NOT_ASSESSED"
         and A.decide("reject", answer, False) == "NOT_ASSESSED",
         "a run that ran out of budget is PAUSED: not TRUE, not FALSE, and no decision is assessed", (comp, answer))

    # ------------------------------------------------------------ P4
    prof = c.profile([pid], evidence_slots=["amount"])
    settled = A.consequence(rb, prof)
    case("N51", A.novelty(settled, A.consequence(rh, prof), prof) == "NO_NEW_CONSEQUENCE",
         "another supported compilation of the same answer: NO_NEW_CONSEQUENCE")
    paused_report = {"axes": dict(rb["axes"], computation_verification="PAUSED", policy_answer="NOT_ASSESSED")}
    stale_answer = {"axes": dict(rb["axes"], computation_verification="PAUSED")}   # answer left over: TRUE
    case("N52", A.consequence(paused_report, prof) is None and A.consequence(stale_answer, prof) is None
         and A.novelty(settled, A.consequence(paused_report, prof), prof) == "NO_NEW_CONSEQUENCE",
         "less budget, PAUSED instead of the known answer: not a consequence, nothing reopened")
    c = Case()
    rec_claim, pidc = c.decision("accept", 12000)
    body_claims = _records(c)[rec_claim]["body"]
    body_claims["because"][0]["verdict"] = "fail"           # claimed expectation flipped
    rec_flip = c.record("accept", body_claims["subject"]["hash"], body_claims["under"], body_claims["because"])
    r53 = assess(c, rec_flip, c.profile([pidc]))
    case("N53", A.consequence(r53, prof) is None and A.novelty(settled, A.consequence(r53, prof), prof) == "NO_NEW_CONSEQUENCE",
         "a flipped claimed verdict is not a consequence (binding requires the replayed pass)", r53["axes"])
    case("N54", settled == (prof["semantics_class"], OBL, "TRUE"),
         "the consequence is (semantics class, obligation, answer) and nothing about how it was reached")
    case("N55", A.novelty(settled, None, prof, new_evidence=("compiler-log.txt", "i@x")) == "NO_NEW_CONSEQUENCE",
         "an arbitrary new blob is not an admitted evidence slot")
    case("N56", A.novelty(settled, None, prof, new_evidence=("amount", "i@x")) == "NEW_EVIDENCE"
         and A.novelty(settled, None, prof, new_evidence=("amount", "m@x")) == "NO_NEW_CONSEQUENCE",
         "a new value in a named slot from an admitted issuer may reopen; from anyone else, not")
    case("N57", A.novelty(settled, A.consequence(r38, prof), prof) == "NEW_CONSEQUENCE",
         "a genuinely different replayed answer in the same scope: NEW_CONSEQUENCE")
    case("N58", A.novelty(settled, (prof["semantics_class"], "made_up_obligation", "FALSE"), prof) == "SCOPE_MISMATCH"
         and A.novelty(settled, ("sigma-resume@v1/wpl@v1", OBL, "FALSE"), prof) == "MIGRATION_REQUIRED",
         "an invented obligation or another runtime class does not count as novelty")
    unrun("N59", "cycle consequences need a sigma-resume runtime; ski@v1 Boolean policies have none")
    c = Case()
    cmd = c.S.put_blob(b"#!/bin/sh\nexit 0\n")
    rec = c.record("accept", c.blob(b"x\n"), [c.blob(b"prose policy\n")],
                   [{"kind": "check", "check": cmd, "runtime": "cmd@v1", "verdict": "pass"}])
    r60 = assess(c, rec, c.profile([]))
    case("N60", A.consequence(r60, prof) is None and not r60["consumer_admits_action"],
         "a cmd@v1 'pass' is a claim: no replayed consequence, nothing admitted", r60["axes"])

    for rep in (r38, r39, r40, r41, r44, r45a, r46, r47, strict):
        assert set(rep["axes"]) == set(A.AXES) and all(v in A.AXES[k] for k, v in rep["axes"].items())
    print()
    counts = {k: sum(v == k for v in results.values()) for k in ("PASS", "FAIL", "UNRUN")}
    print(f"ASSESSMENT: {counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['UNRUN']} UNRUN"
          + ("" if counts["UNRUN"] == 0 else " (an UNRUN is not a pass)"))
    return 0 if counts["FAIL"] == 0 else 1


# ---------------------------------------------------------------- helpers

def _records(c):
    return {p.stem: json.loads(p.read_text()) for p in c.S.records.glob("*.json")}


def _under(c, rec):
    return _records(c)[rec]["body"]["under"]


def _swap_under(c, rec, i, new):
    """File a new signed record: the same body with one `under` entry replaced."""
    body = _records(c)[rec]["body"]
    body["under"][i] = new
    c.ts += 1
    body["ts"] = c.ts
    return c.S.put_record({"body": body, "sigs": [W.sign_envelope(body, "a@x", str(c.keys["a@x"]))]})


def _low_budget_check(c):
    prog = A.program(OBL, {"amount": "int"}, "amount <= 50000")
    facts = A.fact_set(OBL, {"amount": A.observed(12000, "x")})
    doc = json.loads((c.S.blobs / A.plan(prog, facts, put=c.S.put_blob)["emitted"]["check"]).read_bytes())
    doc["atp"] = 3
    return c.S.put_blob(A._canon(doc))


if __name__ == "__main__":
    sys.exit(main())
