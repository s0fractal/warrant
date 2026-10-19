#!/usr/bin/env python3
"""Counterexamples as requirements: each case is one class of defect the contract
(SPEC.md) must refuse, with a positive control where the refusal could be vacuous.

    python3 tests/contract_test.py
"""
import sys

from world import (CODEX, HOLDER, OBSERVER, OWNER, SHA_NEW, SHA_OLD, STRANGER, E, R, World, check, finish,
                   verdicts)


def last(rep, did):
    return rep["duties"][did]["candidates"][-1]


def attest_cases():
    # A1: a closure the holder files is not closed by the holder's word alone
    w = World()
    d = w.duty()
    t = w.close(d)
    rep = w.assess()
    check("A1", rep["duties"][d]["disposition"] == "OPEN" and last(rep, d)["verdict"] == "PENDING",
          "an attested closure waits for the required acceptor", verdicts(rep, d))
    # A2: the holder accepting its own item, or a stranger accepting it, is not the required acceptance
    w.accept(HOLDER, t)
    w.accept(STRANGER, t)
    rep = w.assess()
    pending = rep["duties"][d]["disposition"] == "OPEN"
    w.accept(OWNER, t)
    rep2 = w.assess()
    check("A2", pending and rep2["duties"][d]["disposition"] == "DISCHARGED",
          "only the named acceptor's acceptance closes; theirs does", (pending, verdicts(rep2, d)))
    # A3: a duty that nobody but its holder must accept cannot be filed as attested
    try:
        R.record("duty", HOLDER, 1, R.duty(HOLDER, "x", [OWNER], {"attest": {}}, accept_by=[HOLDER]))
        refused = False
    except R.Invalid:
        refused = True
    check("A3", refused, "a self-accepted attestation is not a record shape")


def exact_acceptance_cases():
    # X1-X3: acceptance of another transition, item, or evidence set does not count
    w = World()
    d = w.duty()
    other = w.duty(statement="other")
    t = w.act(HOLDER, [R.item(other, "discharge", [w.evidence("a")]), R.item(d, "discharge", [w.evidence("b")])])
    t2 = w.close(d, evidence=[w.evidence("c")])
    w.accept(OWNER, t, 0)                                    # the other item of t
    w.accept(OWNER, t2, 0, evidence=[w.evidence("b")])       # another evidence set for t2
    w.file("accept", OWNER, R.accept(t2, 1, [w.evidence("c")]))  # an item index that does not exist
    rep = w.assess()
    check("X1", rep["duties"][d]["disposition"] == "OPEN" and rep["duties"][other]["disposition"] == "DISCHARGED",
          "an acceptance binds exactly one transition, item and evidence set", verdicts(rep, d))
    w.accept(OWNER, t, 1)
    rep = w.assess()
    check("X2", rep["duties"][d]["closed_by"] == [t], "the exact acceptance closes the exact item", verdicts(rep, d))


def goal_cases():
    # G1: a parent that requires two named children is not closed by one of them
    w = World()
    c1, c2 = w.duty(statement="child 1"), w.duty(statement="child 2")
    parent = w.duty(statement="parent", requires=[c1, c2])
    w.accept(OWNER, w.close(c1))
    w.accept(OWNER, w.close(parent))
    rep = w.assess()
    check("G1", rep["duties"][parent]["disposition"] == "OPEN" and last(rep, parent)["verdict"] == "UNMET_CONDITION",
          "one discharged child does not discharge the goal", verdicts(rep, parent))
    w.accept(OWNER, w.close(c2))
    w.accept(OWNER, w.close(parent))
    rep = w.assess()
    check("G2", rep["duties"][parent]["disposition"] == "DISCHARGED", "with every named child discharged, it closes",
          verdicts(rep, parent))
    # G3: `serves` grants nothing: the holder of a serving duty cannot close the served one
    w = World()
    top = w.duty(holder=OWNER, owed_to=(CODEX,), accept_by=(CODEX,), statement="purpose")
    w.duty(serves=[top], statement="means")
    t = w.close(top, actor=HOLDER)
    w.accept(CODEX, t)
    rep = w.assess()
    check("G3", last(rep, top)["verdict"] == "OVERCLAIMED", "serving a duty is no authority over it", verdicts(rep, top))


def authority_cases():
    # U1: a trusted key is authentication only: a stranger cannot release
    w = World()
    d = w.duty()
    w.close(d, actor=STRANGER, act="release")
    rep = w.assess()
    check("U1", last(rep, d)["verdict"] == "OVERCLAIMED" and rep["duties"][d]["disposition"] == "OPEN",
          "a key binding authorizes nothing", verdicts(rep, d))
    # U2: a delegate may close but not transfer or release: delegation does not widen rights
    w = World()
    d = w.duty()
    t = w.close(d, act="delegate", to=CODEX)
    w.accept(CODEX, t)
    w.close(d, actor=CODEX, act="substitute", to=STRANGER)
    w.close(d, actor=CODEX, act="release")
    rep = w.assess()
    v = verdicts(rep, d)
    check("U2", v[1:] == [("substitute", "OVERCLAIMED"), ("release", "OVERCLAIMED")] and rep["duties"][d]["holder"] == HOLDER,
          "a delegate cannot pass the duty on or release it", v)
    t3 = w.close(d, actor=CODEX)
    w.accept(OWNER, t3)
    rep = w.assess()
    check("U3", rep["duties"][d]["disposition"] == "DISCHARGED", "a delegate's own closure is admitted", verdicts(rep, d))
    # U4: grants: an accepted root lets its grantee release; an unaccepted root does not;
    #     an attenuation beyond the parent's delegable is refused
    w = World()
    d = w.duty()
    root = w.file("grant", OWNER, R.grant(STRANGER, ["release"], [d], delegable=[]))
    child = w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d], parent=root))
    w.close(d, actor=CODEX, act="release")
    prof = E.profile(grant_roots=[root])
    rep = w.assess(prof=prof)
    check("U4", rep["grants"][child] == "NOT_ATTENUATED" and last(rep, d)["verdict"] == "OVERCLAIMED",
          "a grant beyond its parent's delegable acts is refused", (rep["grants"], verdicts(rep, d)))
    w.close(d, actor=STRANGER, act="release")
    rep, no_root = w.assess(prof=prof), w.assess()
    check("U5", rep["duties"][d]["disposition"] == "RELEASED" and last(no_root, d)["verdict"] == "OVERCLAIMED",
          "a root the recipient accepted authorizes; the same root unaccepted does not",
          (verdicts(rep, d), rep["grants"]))


def order_cases():
    # O1: filed early, accepted late, is admitted late (RV-01)
    w = World()
    od, dd = w.duty(statement="open dep"), w.duty(statement="done dep")
    w.accept(OWNER, w.close(dd))
    d = w.duty()
    trig = lambda x: [{"kind": "duty_not_discharged", "duty": x}]      # noqa: E731
    orig = w.close(d, at=200, triggers=trig(od))
    rv = w.close(d, act="revalidate", at=300, revalidates=[orig], triggers=trig(dd))
    w.accept(OWNER, rv, at=301)
    w.accept(OWNER, orig, at=600)
    rep = w.assess()
    check("O1", rep["duties"][d]["disposition"] == "DISCHARGED" and last(rep, d)["verdict"] == "OVERCLAIMED"
          and "admission order" in last(rep, d)["why"] and E.reliance(rep, d, "act")["state"] == "STALE",
          "a revalidation accepted before its predecessor was accepted does not supersede it", verdicts(rep, d))
    rv2 = w.close(d, act="revalidate", at=700, revalidates=[orig], triggers=trig(dd))
    w.accept(OWNER, rv2, at=701)
    rep = w.assess()
    check("O2", E.reliance(rep, d, "act")["state"] == "ELIGIBLE" and
          [c["verdict"] for c in rep["duties"][d]["candidates"] if c["act"] == "revalidate"] == ["OVERCLAIMED", "ADMITTED"],
          "a revalidation admitted after its predecessor supersedes it; the fired trigger stays as history",
          verdicts(rep, d))


def holder_case(actor, at, act="substitute"):
    """Claude substitutes (or delegates) the duty to OWNER, filed at 500, consented by
    OWNER at 501 and, for a substitution, by the creditor CODEX at 502."""
    w = World()
    od, dd = w.duty(statement="open dep"), w.duty(statement="done dep")
    w.accept(OWNER, w.close(dd))
    d = w.duty(owed_to=(CODEX,), accept_by=(CODEX,))
    trig = lambda x: [{"kind": "duty_not_discharged", "duty": x}]      # noqa: E731
    orig = w.close(d, at=200, triggers=trig(od))
    w.accept(CODEX, orig, at=201)
    rv = None
    if at < 500:
        rv = w.close(d, actor=actor, act="revalidate", at=at, revalidates=[orig], triggers=trig(dd))
        w.accept(CODEX, rv, at=at + 1)
    tr = w.close(d, act=act, to=OWNER, at=500)
    w.accept(OWNER, tr, at=501)
    if act == "substitute":
        w.accept(CODEX, tr, at=502)
    if at >= 500:
        rv = w.close(d, actor=actor, act="revalidate", at=at, revalidates=[orig], triggers=trig(dd))
        w.accept(CODEX, rv, at=at + 5)
    rep = w.assess()
    c = next(c for c in rep["duties"][d]["candidates"] if c["transition"] == rv)
    return rep["duties"][d]["holder"], c["verdict"], E.reliance(rep, d, "act")["state"]


def transfer_cases():
    got = holder_case(OWNER, 300)
    check("H1", got == (OWNER, "OVERCLAIMED", "STALE"), "a later substitution does not authorize an earlier non-holder", got)
    got = holder_case(HOLDER, 300)
    check("H2", got == (OWNER, "ADMITTED", "ELIGIBLE"), "a later substitution does not un-admit the then-holder", got)
    got = holder_case(OWNER, 600)
    check("H3", got == (OWNER, "ADMITTED", "ELIGIBLE"), "the incoming holder, after the transfer took effect, is admitted", got)
    got = holder_case(OWNER, 501)
    check("H4", got == (OWNER, "OVERCLAIMED", "STALE"), "a transfer takes effect at its last required consent", got)
    early, late = holder_case(OWNER, 300, "delegate")[1:], holder_case(OWNER, 600, "delegate")[1:]
    check("H5", early == ("OVERCLAIMED", "STALE") and late == ("ADMITTED", "ELIGIBLE"),
          "the same holds for a delegation, in both directions", (early, late))
    # H6: a transfer the incoming actor never accepted moves nothing
    w = World()
    d = w.duty()
    w.close(d, act="substitute", to=CODEX)
    rep = w.assess()
    check("H6", rep["duties"][d]["holder"] == HOLDER and last(rep, d)["verdict"] == "PENDING",
          "nobody acquires a duty they did not accept", verdicts(rep, d))


def identity_cases():
    import shutil
    w = World()
    d = w.duty()
    w.accept(OWNER, w.close(d))
    a = w.assess()
    moved = w.dir / "elsewhere"
    shutil.copytree(w.store.root, moved)
    from warrant.store import Snapshot
    b = E.assess(Snapshot.read(moved), w.trust, 10_000, E.profile(), current=(SHA_NEW,))
    c = w.assess(prof=E.profile(uses={"other": {"requires_triggers": False}}))
    dd = w.assess(as_of=10_001)
    e = w.assess(current=(SHA_OLD,))
    ids = {x["assessment_id"] for x in (a, c, dd, e)}
    check("I1", a["assessment_id"] == b["assessment_id"] and len(ids) == 4,
          "same bytes elsewhere: same identity; another profile, time or current set: another identity",
          (a["assessment_id"][:12], b["assessment_id"][:12], len(ids)))


def unknown_cases():
    # N1: an UNEVALUABLE trigger is not NOT_FIRED
    w = World()
    d = w.duty()
    t = w.close(d, triggers=[{"kind": "duty_not_discharged", "duty": "ab" * 32}])
    w.accept(OWNER, t)
    rep = w.assess()
    check("N1", E.reliance(rep, d, "act")["state"] == "UNASSESSED", "an unknown trigger result never reads as success",
          E.reliance(rep, d, "act"))
    # N2: no declared triggers is neutral, never "cannot be falsified"
    w = World()
    d = w.duty()
    w.accept(OWNER, w.close(d, tkw={"subject": SHA_NEW}))
    prof = E.profile(uses={"act": {"requires_triggers": False}, "ship": {"requires_triggers": True}})
    rep = w.assess(prof=prof)
    check("N2", rep["duties"][d]["trigger_coverage"] == "NONE_DECLARED" and E.reliance(rep, d, "act")["state"] == "ELIGIBLE"
          and E.reliance(rep, d, "ship")["state"] == "UNASSESSED",
          "an empty trigger list is reported as such; a use that needs triggers is not served by it",
          (rep["duties"][d].get("trigger_coverage"), E.reliance(rep, d, "ship")))
    # N3: a closure established on a revision that is not current has no revision basis
    rep = w.assess(prof=prof, current=(SHA_OLD,))
    check("N3", E.reliance(rep, d, "act")["state"] == "UNASSESSED", "no revision basis is UNASSESSED, not ELIGIBLE",
          E.reliance(rep, d, "act"))
    # N4: an unknown trigger kind is not a record
    try:
        R.record("transition", HOLDER, 1, R.transition("ATTESTED", triggers=[{"kind": "always_fine", "duty": "ab" * 32}]))
        refused = False
    except R.Invalid:
        refused = True
    check("N4", refused, "an unknown trigger kind is refused, not ignored")
    # N5: unauthentic records never count and never abort the view
    w = World()
    d = w.duty()
    t = w.close(d)
    w.store.put_record(R.record("accept", OWNER, 900, R.accept(t, 0, W_ev(w, t))), w.keys[STRANGER])
    rep = w.assess()
    check("N5", rep["duties"][d]["disposition"] == "OPEN" and len(rep["invalid_records"]) == 1,
          "an acceptance signed with another actor's key is invalid and counts for nothing", rep["invalid_records"])

    # N6 (R138-02, Codex review of 1235d1e): a malformed signature member is an
    # invalid record; it never aborts the assessment of the rest of the store.
    from warrant import canon, loads
    w = World()
    control = w.act(HOLDER, [], established=["a valid record"])
    bad = {}
    for k, (field, value) in enumerate((("key", []), ("key", {}), ("key", None), ("key", "zz"),
                                        ("ed25519", 7), ("ed25519", "00"))):
        rid = w.act(HOLDER, [], established=[f"to be broken {k}"])
        p = w.store.root / "records" / f"{rid}.json"
        env = loads(p.read_bytes())
        env["sig"][field] = value
        p.write_bytes(canon(env))
        bad[rid] = field
    try:
        rep = w.assess()
        ok6 = set(bad) <= set(rep["invalid_records"]) and control in rep["results"] and not set(bad) & set(rep["results"])
        det6 = rep["invalid_records"]
    except (TypeError, ValueError, AttributeError) as e:
        ok6, det6 = False, f"assessment aborted: {type(e).__name__}: {e}"
    check("N6", ok6, "malformed signature members are invalid records; the rest is assessed", det6)


def W_ev(w, t):
    from warrant import loads
    return loads(w.store.snapshot().records[t])["record"]["body"]["closes"][0]["evidence"]


def supersession_cases():
    w = World()
    prof = E.profile(results_by=[OWNER])
    a = w.act(HOLDER, [], established=["the API is v1"])
    w.accept(OWNER, a, None)
    b = w.act(HOLDER, [], established=["the API is v2"], supersedes=[a])
    w.accept(OWNER, b, None)
    rep = w.assess(prof=prof)
    check("S1", E.reliance(rep, a, "act")["state"] == "SUPERSEDED" and E.reliance(rep, b, "act")["state"] == "ELIGIBLE"
          and rep["results"][a]["accepted"], "a superseded result stays accepted history and is not relied on now",
          (E.reliance(rep, a, "act"), E.reliance(rep, b, "act")))
    c = w.act(HOLDER, [], established=["the API is v3"], supersedes=[b])
    rep = w.assess(prof=prof)
    check("S2", E.reliance(rep, b, "act")["state"] == "ELIGIBLE" and E.reliance(rep, a, "act")["state"] == "SUPERSEDED",
          "an unaccepted C does not supersede B, and A never returns", (E.reliance(rep, a, "act"), E.reliance(rep, b, "act")))
    w.accept(OWNER, c, None)
    import shutil
    from warrant.store import Snapshot
    part = w.dir / "partial"
    shutil.copytree(w.store.root, part)
    (part / "records" / f"{b}.json").unlink()
    rep = E.assess(Snapshot.read(part), w.trust, 10_000, prof, current=(SHA_NEW,))
    check("S3", b in rep["missing"] and rep["view"]["completeness"] == "UNATTESTED",
          "a slice without B names B as missing; it never reports that nothing happened", rep["missing"])


def question_cases():
    w = World()
    d = w.duty()
    t = w.act(HOLDER, [R.item(d, "discharge", [w.evidence()])], established=["shipped"],
              opened=[{"text": "should v2 keep the old field?", "scope": None}])
    w.accept(OWNER, t)
    rep = w.assess()
    q = E.questions(rep)
    check("Q1", rep["duties"][d]["disposition"] == "DISCHARGED" and len(q) == 1
          and all(x.get("need") != "close" for x in E.frontier(rep, HOLDER))
          and not any("question" in str(x) for x in E.frontier(rep, OWNER)),
          "an opened question leaves the result standing and is in nobody's frontier", (q, E.frontier(rep, HOLDER)))


def handoff_cases():
    # F1-F2: what a new session needs from the report (2026-10-18 handoff experiment):
    # the holder's frontier names whom a filed closure waits for; the report names
    # the duty's requires, and the actors who cannot sign in this view.
    w = World()
    child = w.duty(statement="child")
    parent = w.duty(statement="parent", requires=[child], accept_by=("nobody-bound",))
    w.close(child)
    rep = w.assess()
    needs = {x["duty"]: x["need"] for x in E.frontier(rep, HOLDER)}
    check("F1", needs[child] == f"awaiting acceptance by {OWNER}" and needs[parent] == "close",
          "a filed closure waiting for acceptance is not shown as work to do", needs)
    check("F2", rep["duties"][parent]["requires"] == [child] and rep["unbound_actors"] == ["nobody-bound"],
          "the report shows requires, and an acceptor without a key", (rep["duties"][parent]["requires"], rep["unbound_actors"]))

    # F3: after a replacement closure and its results are accepted, the superseded
    # closure is no longer offered for acceptance (it stays in the report)
    w = World()
    d = w.duty()
    old = w.close(d)
    new = w.act(HOLDER, [R.item(d, "discharge", [w.evidence("v2")])], supersedes=[old])
    w.accept(OWNER, new, 0)
    w.accept(OWNER, new, None)
    rep = w.assess(prof=E.profile(results_by=[OWNER]))
    offered = [x for x in E.frontier(rep, OWNER) if x.get("need") == "accept"]
    check("F3", rep["duties"][d]["disposition"] == "DISCHARGED" and not offered
          and any(c["transition"] == old for c in rep["duties"][d]["candidates"]),
          "a superseded closure is history, not acceptance work", offered)

    # F4 (W141-01, Codex review of 0c3b034): replacing a transition's RESULTS does
    # not make its pending closure obsolete. A replacement that closes nothing, one
    # that closes another duty, and one whose results are accepted but whose own
    # item is not: in each, the old item is still the owner's acceptance work.
    def still_offered(variant):
        w = World()
        d = w.duty()
        other = w.duty(statement="other")
        old = w.close(d)
        if variant == "results-only":
            new = w.act(HOLDER, [], established=["v2"], supersedes=[old])
        elif variant == "other-duty":
            new = w.act(HOLDER, [R.item(other, "discharge", [w.evidence("o")])], supersedes=[old])
            w.accept(OWNER, new, 0)
        else:
            new = w.act(HOLDER, [R.item(d, "discharge", [w.evidence("v2")])], supersedes=[old])
        w.accept(CODEX, new, None)
        rep = w.assess(prof=E.profile(results_by=[CODEX]))
        return rep["duties"][d]["disposition"] == "OPEN" and any(
            x.get("need") == "accept" and x.get("transition") == old for x in E.frontier(rep, OWNER))
    got = {v: still_offered(v) for v in ("results-only", "other-duty", "item-unaccepted")}
    check("F4", all(got.values()), "results supersession alone never hides a pending closure from its acceptor", got)

    # F5: who closes a duty is in its capsule, and an acceptor's frontier item says
    # whose acceptance it still waits for and whether this one is the last (the
    # 2026-10-19 fresh-context run guessed that its own accept "may not close" it)
    w = World()
    d = w.duty(owed_to=(OWNER,), accept_by=(OWNER, CODEX))
    t = w.close(d)
    rep = w.assess()
    first = [x for x in E.frontier(rep, OWNER) if x.get("need") == "accept"]
    cap = E.capsule(rep, d)
    w.accept(CODEX, t, 0)
    rep2 = w.assess()
    last = [x for x in E.frontier(rep2, OWNER) if x.get("need") == "accept"]
    cap2 = E.capsule(rep2, d)
    w.accept(OWNER, t, 0)
    rep3 = w.assess()
    check("F5", cap["accept_by"] == [OWNER, CODEX] and cap["owed_to"] == [OWNER]
          and cap["waiting_for"] == sorted([OWNER, CODEX])
          and first and first[0]["waiting_for"] == sorted([OWNER, CODEX]) and first[0]["last_acceptance"] is False
          and last and last[0]["waiting_for"] == [OWNER] and last[0]["last_acceptance"] is True
          and cap2["waiting_for"] == [OWNER] and rep3["duties"][d]["disposition"] == "DISCHARGED"
          and E.capsule(rep3, d)["waiting_for"] == [],
          "a capsule names who closes the duty; an acceptor knows whether its accept is the last one",
          (cap.get("waiting_for"), first, last))


def main():
    attest_cases()
    exact_acceptance_cases()
    goal_cases()
    authority_cases()
    order_cases()
    transfer_cases()
    identity_cases()
    unknown_cases()
    supersession_cases()
    question_cases()
    handoff_cases()
    return finish("CONTRACT")


if __name__ == "__main__":
    sys.exit(main())
