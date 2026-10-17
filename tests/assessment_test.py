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
        self.attested = {}

    def blob(self, doc):
        return self.S.put_blob(doc if isinstance(doc, bytes) else A._canon(doc))

    def record(self, decision, subject, under=(), because=(), actor="a@x", evidence=()):
        self.ts += 1
        body = {"warrant": "0.2", "decision": decision, "subject": {"hash": subject, "note": "case"},
                "under": list(under), "because": list(because), "evidence": list(evidence),
                "actor": {"id": actor}, "prior": [], "ts": self.ts}
        return self.S.put_record({"body": body, "sigs": [W.sign_envelope(body, actor, str(self.keys[actor]))]})

    def attest(self, name, value, issuer="i@x", obligation=OBL):
        """One attestation per (fact, value, issuer, obligation): asking twice
        returns the same record, as a real issuer's single observation would."""
        key = (name, value, issuer, obligation)
        if key not in self.attested:
            rules = self.blob(b"issuer attestation: we observed this value\n")
            self.attested[key] = self.record("accept", self.blob(A.observation(obligation, name, value)),
                                             [rules], actor=issuer)
        return self.attested[key]

    def decision(self, decision, amount, *, rule="amount <= 50000", options=None, compiler=None,
                 reason="own", issuer="i@x", actor="a@x", obligation=OBL, evidence=()):
        prog = A.program(obligation, {"amount": "int"}, rule)
        facts = A.fact_set(obligation, {"amount": A.observed(amount, self.attest("amount", amount, issuer,
                                                                                  obligation))})
        pl = A.plan(prog, facts, options, put=self.S.put_blob, **({"compiler": compiler} if compiler else {}))
        under = [self.blob(prog), self.blob(facts), self.blob(pl)]
        check = pl["emitted"]["check"] if reason == "own" else reason
        because = [{"kind": "check", "check": check, "runtime": "ski@v1", "verdict": "pass"}] if check else []
        rec = self.record(decision, self.blob(b"refund request\n"), under, because, actor=actor, evidence=evidence)
        return rec, A.blob_id(prog)

    def profile(self, programs, discretionary_reject=True, **kw):
        # The API has no default for discretion; this helper states one explicitly.
        return A.profile(programs, OBL, self.trust, ["i@x"], discretionary_reject, **kw)


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

    # ------------------------------------------------------------ P4 (one store, one profile)
    s = Case(trusted=("a@x", "i@x", "m@x"))       # m@x: a bound key, NOT an admitted fact issuer
    rec_base, pid4 = s.decision("accept", 12000)
    prof = s.profile([pid4], evidence_slots=["amount"])
    base = A.assess(s.S.root, rec_base, prof)
    settled = A.consequence(base, prof)
    rec_head, _ = s.decision("accept", 12000, options={"atp_headroom": 1000})
    head = A.assess(s.S.root, rec_head, prof)
    case("N51", A.novelty(base, head, prof) == "NO_NEW_CONSEQUENCE",
         "another supported compilation of the same answer, same facts: NO_NEW_CONSEQUENCE")
    paused_report = dict(base, axes=dict(base["axes"], computation_verification="PAUSED", policy_answer="NOT_ASSESSED"))
    stale_answer = dict(base, axes=dict(base["axes"], computation_verification="PAUSED"))   # answer left over: TRUE
    case("N52", A.consequence(paused_report, prof) is None and A.consequence(stale_answer, prof) is None
         and A.novelty(base, paused_report, prof) == "NO_NEW_CONSEQUENCE",
         "less budget, PAUSED instead of the known answer: not a consequence, nothing reopened")
    body_claims = _records(s)[rec_base]["body"]
    body_claims["because"][0]["verdict"] = "fail"           # claimed expectation flipped
    rec_flip = s.record("accept", body_claims["subject"]["hash"], body_claims["under"], body_claims["because"])
    r53 = A.assess(s.S.root, rec_flip, prof)
    case("N53", A.consequence(r53, prof) is None and A.novelty(base, r53, prof) == "NO_NEW_CONSEQUENCE",
         "a flipped claimed verdict is not a consequence (binding requires the replayed pass)", r53["axes"])
    case("N54", settled == (prof["semantics_class"], OBL, "TRUE"),
         "the consequence is (semantics class, obligation, answer) and nothing about how it was reached")
    rec_blob, _ = s.decision("accept", 12000, evidence=[s.blob(b"compiler-log.txt: nothing new\n")])
    case("N55", A.novelty(base, A.assess(s.S.root, rec_blob, prof), prof) == "NO_NEW_CONSEQUENCE",
         "an arbitrary new evidence blob, same named facts: NO_NEW_CONSEQUENCE")
    rec_new, _ = s.decision("accept", 13000)              # a new admitted observation, same answer
    rec_m, _ = s.decision("accept", 13000, issuer="m@x")  # the same value from a non-admitted issuer
    r_new, r_m = A.assess(s.S.root, rec_new, prof), A.assess(s.S.root, rec_m, prof)
    case("N56", A.novelty(base, r_new, prof) == "NEW_EVIDENCE" and A.novelty(base, r_m, prof) == "NO_NEW_CONSEQUENCE",
         "a new ACCEPTED value in the named slot reopens; the same value from an unadmitted issuer does not",
         (A.novelty(base, r_new, prof), A.novelty(base, r_m, prof)))
    rec_false, _ = s.decision("accept", 65088)
    r_false = A.assess(s.S.root, rec_false, prof)
    case("N57", A.novelty(base, r_false, prof) == "NEW_CONSEQUENCE",
         "a genuinely different replayed answer on accepted facts in the same scope: NEW_CONSEQUENCE")
    rec_scope, _ = s.decision("accept", 65088, obligation="made_up_obligation")
    r_scope = A.assess(s.S.root, rec_scope, prof)
    migrated = dict(r_false, scope=dict(r_false["scope"], semantics_class="sigma-resume@v1/wpl@v1"))
    case("N58", A.novelty(base, r_scope, prof) == "SCOPE_MISMATCH" and A.novelty(base, migrated, prof) == "MIGRATION_REQUIRED",
         "an invented obligation or another runtime class does not count as novelty")

    # ------------------------------------------------------------ independent review WA01-WA05
    wa = Case()
    src, _ = wa.decision("accept", 12000)                  # its policy answers TRUE
    src_check = json.loads((wa.S.blobs / _under(wa, src)[2]).read_bytes())["emitted"]["check"]
    prog = A.program(OBL, {"amount": "int"}, "amount <= 50000")
    facts = A.fact_set(OBL, {"amount": A.derived(40000, src, src_check)})   # an int "derived" from TRUE
    pl = A.plan(prog, facts, put=wa.S.put_blob)
    rec = wa.record("accept", wa.blob(b"x\n"), [wa.blob(prog), wa.blob(facts), wa.blob(pl)],
                    [{"kind": "check", "check": pl["emitted"]["check"], "runtime": "ski@v1", "verdict": "pass"}])
    r01 = assess(wa, rec, wa.profile([A.blob_id(prog)]))
    facts_b = A.fact_set(OBL, {"amount": A.observed(True, wa.attest("amount", True))})       # bool for int
    rec_b = wa.record("accept", wa.blob(b"y\n"), [wa.blob(prog), wa.blob(facts_b), wa.blob(A.plan(prog, A.fact_set(OBL, {"amount": A.observed(1, "x")}), put=wa.S.put_blob))], [])
    r01b = assess(wa, rec_b, wa.profile([A.blob_id(prog)]))
    src_f, _ = wa.decision("accept", 65088)                 # its policy answers FALSE
    chk_f = json.loads((wa.S.blobs / _under(wa, src_f)[2]).read_bytes())["emitted"]["check"]
    facts0 = A.fact_set(OBL, {"amount": A.derived(0, src_f, chk_f)})   # int 0 'derived' from FALSE: truthiness agrees
    pl0 = A.plan(prog, facts0, put=wa.S.put_blob)
    rec0 = wa.record("accept", wa.blob(b"z\n"), [wa.blob(prog), wa.blob(facts0), wa.blob(pl0)],
                     [{"kind": "check", "check": pl0["emitted"]["check"], "runtime": "ski@v1", "verdict": "pass"}])
    r01c = assess(wa, rec0, wa.profile([A.blob_id(prog)]))
    case("WA01", r01["axes"]["fact_provenance"] == "DERIVATION_MISMATCH" and not r01["consumer_admits_action"]
         and r01b["axes"]["fact_provenance"] == "TYPE_MISMATCH"
         and r01c["axes"]["fact_provenance"] == "DERIVATION_MISMATCH",
         "an int 'derived' from a Boolean answer is refused, and a bool is not an int", (r01["axes"], r01b["axes"]))
    case("WA02", A.consequence(r_m, prof) is None and A.novelty(base, r_m, prof) == "NO_NEW_CONSEQUENCE",
         "unattested facts produce no consequence and reopen nothing")
    case("WA03", A.novelty(base, r_scope, prof) == "SCOPE_MISMATCH" and A.novelty(base, base, prof) == "NO_NEW_CONSEQUENCE",
         "scope is checked first; novelty needs a new accepted value, not a named channel")
    w4 = Case()
    rec4, pid_4 = w4.decision("accept", 12000)
    prof4 = w4.profile([pid_4])
    r4a, r4b = assess(w4, rec4, prof4), assess(w4, rec4, prof4)
    w4.trust.write_text(json.dumps({"actors": {"a@x": ["00" * 32], "i@x": ["00" * 32]}}))
    r4c = assess(w4, rec4, prof4)
    case("WA04", r4a["context_id"] == r4b["context_id"] and r4c["axes"]["record_integrity"] == "INVALID"
         and r4c["context_id"] != r4a["context_id"],
         "the context names the trust bytes it used: same snapshot same id; changed trust, new id")
    w5 = Case()
    rec5, pid5 = w5.decision("accept", 12000)
    pl5 = json.loads((w5.S.blobs / _under(w5, rec5)[2]).read_bytes())
    pl5["runtime"] = "not-the-runtime"
    pl5["emitted"]["expect"] = "00" * 32
    pl5["emitted"]["atp"] = 0
    r05 = assess(w5, _swap_under(w5, rec5, 2, w5.blob(pl5)), w5.profile([pid5]))
    pl5r = json.loads((w5.S.blobs / _under(w5, rec5)[2]).read_bytes())
    pl5r["runtime"] = "not-the-runtime"                     # ONLY the runtime is false
    r05r = assess(w5, _swap_under(w5, rec5, 2, w5.blob(pl5r)), w5.profile([pid5]))
    case("WA05", r05["axes"]["compilation_binding"] == "COMPILATION_MISMATCH" and not r05["consumer_admits_action"]
         and r05r["axes"]["compilation_binding"] == "COMPILATION_MISMATCH",
         "a plan that misstates runtime, expect or atp, or only its runtime, is not MATCHED", (r05["axes"], r05r["axes"]))
    snapshot_case()
    try:
        A.profile([pid5], OBL, w5.trust, ["i@x"], None)
        explicit = False
    except (ValueError, TypeError):
        explicit = True
    case("WA-discretion", explicit, "the recipient must choose discretionary_reject explicitly: no default")
    unrun("N59", "cycle consequences need a sigma-resume runtime; ski@v1 Boolean policies have none")
    c = Case()
    cmd = c.S.put_blob(b"#!/bin/sh\nexit 0\n")
    rec = c.record("accept", c.blob(b"x\n"), [c.blob(b"prose policy\n")],
                   [{"kind": "check", "check": cmd, "runtime": "cmd@v1", "verdict": "pass"}])
    r60 = assess(c, rec, c.profile([]))
    case("N60", A.consequence(r60, prof) is None and not r60["consumer_admits_action"],
         "a cmd@v1 'pass' is a claim: no replayed consequence, nothing admitted", r60["axes"])

    for rep in (r38, r39, r40, r41, r44, r45a, r46, r47, strict):
        assert set(rep["axes"]) == set(A.AXES)
        assert all(v in A.AXES[k] for k, v in rep["axes"].items())
    print()
    counts = {k: sum(v == k for v in results.values()) for k in ("PASS", "FAIL", "UNRUN")}
    print(f"ASSESSMENT: {counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['UNRUN']} UNRUN"
          + ("" if counts["UNRUN"] == 0 else " (an UNRUN is not a pass)"))
    return 0 if counts["FAIL"] == 0 else 1


def snapshot_case():
    """Re-review of cda525e (Codex, N1): the CLI verified the LIVE store while the
    assessment judged its own earlier read. Deterministic interleaving, exactly as
    the review built it: a forged accept (decision flipped, reject's signature
    kept) is in place when assess starts; another writer atomically restores the
    signed reject before the real CLI verify runs. No verifier is faked."""
    c = Case()
    rid, pid = c.decision("reject", 12000)
    prof = c.profile([pid])
    path = c.S.records / f"{rid}.json"
    honest = path.read_bytes()
    forged = json.loads(honest)
    forged["body"]["decision"] = "accept"
    forged = A._canon(forged)

    def install(data):
        tmp = path.with_suffix(".replacement")
        tmp.write_bytes(data)
        tmp.replace(path)
    clean = A.assess(c.S.root, rid, prof)
    install(forged)
    static = A.assess(c.S.root, rid, prof)
    real = A._record_integrity

    def restore_then_verify(store, trust):
        install(honest)
        return real(store, trust)
    A._record_integrity = restore_then_verify
    try:
        mixed = A.assess(c.S.root, rid, prof)
    finally:
        A._record_integrity = real
        install(honest)
    ok = (clean["axes"]["record_integrity"] == "VERIFIED" and not clean["consumer_admits_action"]
          and static["axes"]["record_integrity"] == "INVALID" and not static["consumer_admits_action"]
          and not mixed["consumer_admits_action"] and mixed["axes"]["record_integrity"] == "INVALID")
    case("SNAPSHOT", ok, "a store changed between reads cannot pair a verified reject with an admitted accept: "
         "the assessment verifies and judges one snapshot (forged accept -> INVALID, nothing admitted)",
         (clean["axes"]["record_integrity"], static["axes"]["record_integrity"],
          mixed["axes"]["record_integrity"], mixed["consumer_admits_action"]))


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
