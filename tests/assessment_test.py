#!/usr/bin/env python3
"""Rules of SPEC §4.1-§4.4 that had no witness case of their own before the
claim records (`.warrant/store`, `tools/claims.py`): each case is one sentence
of the SPEC, cited by its claim, with the mutant in tests/mutants.py that burns it.

    python3 tests/assessment_test.py
"""
import hashlib
import sys

from world import CODEX, HOLDER, OWNER, E, R, World, check, finish, verdicts


def last(rep, d):
    return rep["duties"][d]["candidates"][-1]


def verdict_of(rep, d, t):
    return next(c for c in rep["duties"][d]["candidates"] if c["transition"] == t)


def guarded(fn):
    """A mutant may make the engine raise; that is a failure of the case, not a crash of the file."""
    try:
        return fn()
    except Exception as e:      # noqa: BLE001
        return f"raised {type(e).__name__}: {e}"


def transfer_cases():
    # R1 (§4.1): transfers are applied in order of effect position, and the filer must
    # still hold the duty when its transfer takes effect. t1 is filed first but takes
    # effect last; by then t2 has already passed the duty to CODEX.
    w = World()
    d = w.duty()
    t1 = w.close(d, act="substitute", to=OWNER, at=200)
    t2 = w.close(d, act="substitute", to=CODEX, at=300)
    w.accept(CODEX, t2, at=301)
    w.accept(OWNER, t2, at=302)
    w.accept(OWNER, t1, at=600)         # OWNER is both the incoming holder and the creditor
    rep = w.assess()
    got = (rep["duties"][d]["holder"], verdict_of(rep, d, t2)["verdict"], verdict_of(rep, d, t1)["verdict"])
    check("R1", got == (CODEX, "ADMITTED", "OVERCLAIMED") and "no longer held" in verdict_of(rep, d, t1)["why"],
          "a transfer filed earlier but taking effect later is judged after the one that took effect first", got)

    # R2 (§4.1): a delegation needs the acceptance of `to`; a substitution also needs one
    # of owed_to or release_by. Without them nothing moves.
    w = World()
    d = w.duty()
    w.close(d, act="delegate", to=CODEX)               # CODEX never accepts
    c = w.close(d, actor=CODEX)
    w.accept(OWNER, c)
    d2 = w.duty(statement="substituted")
    s = w.close(d2, act="substitute", to=CODEX)
    w.accept(CODEX, s)                                 # the incoming holder accepts, no creditor does
    rep = w.assess()
    got = (rep["duties"][d]["delegates"], verdict_of(rep, d, c)["verdict"], rep["duties"][d]["disposition"],
           rep["duties"][d2]["holder"], verdict_of(rep, d2, s)["verdict"])
    check("R2", got == ([], "OVERCLAIMED", "OPEN", HOLDER, "PENDING"),
          "an unaccepted delegation delegates nothing; a substitution without a creditor's consent moves nothing", got)

    # R3 (§4.1, §4.2 1): being named in a duty is no authority: its creditor and acceptor
    # cannot discharge it, even accepting its own filing
    w = World()
    d = w.duty()
    t = w.close(d, actor=OWNER)
    w.accept(OWNER, t)
    rep = w.assess()
    check("R3", last(rep, d)["verdict"] == "OVERCLAIMED" and rep["duties"][d]["disposition"] == "OPEN",
          "an actor named in owed_to and accept_by does not hold the duty", verdicts(rep, d))


def admission_cases():
    # R4 (§4.2 2): evidence must resolve in the view to bytes with that hash: a hash with no
    # bytes, and a blob file named by a hash its bytes do not have, are both missing evidence
    w = World()
    d = w.duty()
    t = w.close(d, evidence=["ab" * 32])
    w.accept(OWNER, t)
    d2 = w.duty(statement="misfiled evidence")
    fake = hashlib.sha256(b"the bytes the name promises").hexdigest()
    (w.store.root / "blobs" / fake).write_bytes(b"other bytes")
    t2 = w.close(d2, evidence=[fake])
    w.accept(OWNER, t2)
    rep = w.assess()
    got = (last(rep, d)["verdict"], last(rep, d2)["verdict"], rep["duties"][d]["disposition"], rep["duties"][d2]["disposition"])
    check("R4", got == ("MISSING_EVIDENCE", "MISSING_EVIDENCE", "OPEN", "OPEN") and any(fake in m for m in rep["misfiled"]),
          "absent bytes and bytes under another hash's name are missing evidence", (got, rep["misfiled"]))

    # R5 (§4.2 3): an attest condition is met by an ATTESTED basis only
    w = World()
    d = w.duty()
    w.accept(OWNER, w.close(d, basis="OBSERVED"))
    d2 = w.duty(statement="replayed")
    w.accept(OWNER, w.close(d2, basis="REPLAYED"))
    rep = w.assess()
    got = (last(rep, d)["verdict"], last(rep, d2)["verdict"], rep["duties"][d]["disposition"], rep["duties"][d2]["disposition"])
    check("R5", got == ("OVERCLAIMED", "OVERCLAIMED", "OPEN", "OPEN"),
          "an accepted OBSERVED or REPLAYED transition does not meet an attest condition", got)

    # R6 (§4.2 6): a revalidation names admitted closures of the same duty; a closure of
    # another duty is not one
    def r6():
        w = World()
        d = w.duty()
        other = w.duty(statement="other")
        o = w.close(other)
        w.accept(OWNER, o)
        w.accept(OWNER, w.close(d))
        rv = w.close(d, act="revalidate", revalidates=[o])
        w.accept(OWNER, rv)
        c = verdict_of(w.assess(), d, rv)
        return c["verdict"], "not an admitted closure of this duty" in c["why"]
    got = guarded(r6)
    check("R6", got == ("OVERCLAIMED", True), "a revalidation of another duty's closure is refused", got)

    # R7 (§4.2): an attested impossibility also needs one owed_to actor's acceptance, and
    # it is attested: any other basis is overclaimed
    w = World()
    d = w.duty(owed_to=(OWNER,), accept_by=(CODEX,))
    t = w.close(d, act="impossible")
    w.accept(CODEX, t)
    before = (w.assess()["duties"][d]["disposition"], last(w.assess(), d)["verdict"], last(w.assess(), d).get("waiting_for"))
    w.accept(OWNER, t)
    after = w.assess()["duties"][d]["disposition"]
    d2 = w.duty(owed_to=(OWNER,), accept_by=(CODEX,), statement="observed impossibility")
    t2 = w.close(d2, act="impossible", basis="OBSERVED")
    w.accept(CODEX, t2)
    w.accept(OWNER, t2)
    rep = w.assess()
    got = (before, after, last(rep, d2)["verdict"], rep["duties"][d2]["disposition"])
    check("R7", got == (("OPEN", "PENDING", [OWNER]), "IMPOSSIBLE", "OVERCLAIMED", "OPEN"),
          "an attested impossibility waits for a creditor; an observed one is overclaimed", got)

    # R8 (§4.2, §4.3): impossible and revalidate are not defined for a scheduled duty;
    # a scheduled duty is SCHEDULED until it is released, then RELEASED
    w = World()
    d = w.duty(schedule={"start": 1000, "every": 100})
    t0 = w.close(d, period=0, at=1050)
    w.accept(OWNER, t0, at=1051)
    imp = w.close(d, act="impossible", at=1060)
    w.accept(OWNER, imp, at=1061)
    rv = w.close(d, act="revalidate", revalidates=[t0], at=1070)
    w.accept(OWNER, rv, at=1071)
    rep = w.assess(as_of=1150)
    shapes = [(verdict_of(rep, d, x)["verdict"], "not defined for a scheduled duty" in verdict_of(rep, d, x)["why"]) for x in (imp, rv)]
    scheduled = rep["duties"][d]["disposition"]
    w.close(d, actor=OWNER, act="release", at=1080)
    released = w.assess(as_of=1150)["duties"][d]["disposition"]
    got = (shapes, scheduled, released)
    check("R8", got == ([("OVERCLAIMED", True)] * 2, "SCHEDULED", "RELEASED"),
          "a scheduled duty refuses impossible and revalidate, and is RELEASED once released", got)


def disposition_cases():
    # R13 (§4.2): a candidate that is not admitted closes nothing, whatever its verdict
    w = World()
    pending = w.duty(statement="pending")
    w.close(pending)
    over = w.duty(statement="overclaimed")
    w.accept(OWNER, w.close(over, actor=CODEX))
    missing = w.duty(statement="missing evidence")
    w.accept(OWNER, w.close(missing, evidence=["ef" * 32]))
    child = w.duty(statement="open child")
    unmet = w.duty(statement="unmet", requires=[child])
    w.accept(OWNER, w.close(unmet))
    rep = w.assess()
    got = {rep["duties"][x]["candidates"][-1]["verdict"]: rep["duties"][x]["disposition"] for x in (pending, over, missing, unmet)}
    check("R13", got == {"PENDING": "OPEN", "OVERCLAIMED": "OPEN", "MISSING_EVIDENCE": "OPEN", "UNMET_CONDITION": "OPEN"},
          "PENDING, OVERCLAIMED, MISSING_EVIDENCE and UNMET_CONDITION leave the duty OPEN", got)

    # R9 (§4.3, §4.4): admitted closures that disagree make the duty CONTESTED, and
    # reliance says so; an open duty is NOT_CLOSED; an unknown target is MISSING
    w = World()
    d = w.duty()
    w.accept(OWNER, w.close(d))
    w.close(d, actor=OWNER, act="release")
    open_d = w.duty(statement="open")
    rep = w.assess()
    got = guarded(lambda: (rep["duties"][d]["disposition"], rep["duties"][d].get("dispositions"),
                           E.reliance(rep, d, "act")["state"], E.reliance(rep, open_d, "act")["state"],
                           E.reliance(rep, "cd" * 32, "act")["state"]))
    check("R9", got == ("CONTESTED", ["DISCHARGED", "RELEASED"], "CONTESTED", "NOT_CLOSED", "MISSING"),
          "a discharged and released duty is CONTESTED; an open one NOT_CLOSED; an absent one MISSING", got)

    # R10 (§4.4): a use the recipient's profile does not name is UNASSESSED, not ELIGIBLE
    w = World()
    d = w.duty()
    w.accept(OWNER, w.close(d))
    rep = w.assess()
    got = guarded(lambda: (E.reliance(rep, d, "act")["state"], E.reliance(rep, d, "ship")["state"],
                           any("not in the recipient profile" in c for c in E.reliance(rep, d, "ship")["causes"])))
    check("R10", got == ("ELIGIBLE", "UNASSESSED", True), "an unnamed use is not assessed", got)

    # R11 (§4.3): nothing later rewrites a disposition or erases a closure: a counting
    # challenge, a fired trigger, a revalidation and a results supersession leave the
    # original closure admitted and named in closed_by
    w = World()
    od = w.duty(statement="open dependency")
    d = w.duty(owed_to=(CODEX,), accept_by=(CODEX,))
    t = w.close(d, at=200, triggers=[{"kind": "duty_not_discharged", "duty": od}])
    w.accept(CODEX, t, at=201)
    ch = w.file("challenge", CODEX, R.challenge(t, "it fails on empty input", [w.evidence("repro")], 0), at=300)
    mid = w.assess()
    rv = w.close(d, act="revalidate", revalidates=[t], at=400)
    w.accept(CODEX, rv, at=401)
    new = w.act(HOLDER, [], established=["the replacement result"], supersedes=[t], at=500)
    w.accept(CODEX, new, None, at=501)
    rep = w.assess(prof=E.profile(results_by=[CODEX]))
    got = (mid["duties"][d]["disposition"], mid["duties"][d]["closed_by"] == [t], rep["duties"][d]["disposition"],
           t in rep["duties"][d]["closed_by"], verdict_of(rep, d, t)["verdict"], ch in rep["challenges"],
           E.reliance(rep, t, "act")["state"])
    check("R11", got == ("DISCHARGED", True, "DISCHARGED", True, "ADMITTED", True, "SUPERSEDED"),
          "a challenge, a fired trigger, a revalidation and a supersession are added; the closure stays", got)

    # R12 (§4.4): a revalidation supersedes the closures it names for present reliance
    # only: their triggers stay in the report with current: false
    trig = [x for x in rep["duties"][d]["triggers"] if x["closure"] == t]
    got = ([(x["kind"], x["result"], x["current"]) for x in trig], E.reliance(rep, d, "act")["state"])
    check("R12", got == ([("duty_not_discharged", "FIRED", False)], "ELIGIBLE"),
          "the revalidated closure's fired trigger stays as history and no longer decides reliance", got)


def main():
    transfer_cases()
    admission_cases()
    disposition_cases()
    return finish("ASSESSMENT")


if __name__ == "__main__":
    sys.exit(main())
