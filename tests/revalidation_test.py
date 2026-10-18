#!/usr/bin/env python3
"""Revalidation (WRT-022, duty ee86a1c5 of the dogfood store): an accepted, later
REVALIDATED mapping restores present eligibility after a revalidation trigger fired,
without erasing the fired trigger's history.

    python3 tests/revalidation_test.py

Triggers here are duty_not_discharged over dependency duties, so FIRED / NOT_FIRED
is set by signed events alone; the subject_changed path is the same code.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "impl"))
# REVAL_IMPL lets tests/revalidation_mutants.py run this file against a mutated copy.
if os.environ.get("REVAL_IMPL"):
    sys.path.insert(0, os.environ["REVAL_IMPL"])
    os.environ["LOOPS_IMPL"] = os.environ["REVAL_IMPL"]
import loops_test as LT   # noqa: E402
import loops as L         # noqa: E402

results = {}


def check(vid, ok, what, detail=""):
    results[vid] = "PASS" if ok else "FAIL"
    print(("ok    " if ok else "FAIL  ") + f"{vid} {what}" + ("" if ok else f" | {detail}"))


def dep(c, done):
    """A dependency duty, DISCHARGED or left OPEN."""
    x = c.open(statement="dependency")
    if done:
        t = c.discharge(x)
        c.accept(LT.CODEX, x, t)
    return x


def trig(x):
    return [{"kind": "duty_not_discharged", "duty": x}]


def close(c, d, triggers, ts=None):
    t = L.transition("ATTESTED", [c.evidence], closes=[L.mapping(d, "DISCHARGED", [c.evidence], triggers=triggers)],
                     scope_subject=LT.SHA_NEW)
    tid = c.record("propose", c.blob(t), LT.CLAUDE, prior=[d], ts=ts)
    c.accept(LT.CODEX, d, tid)
    return tid


def revalidate(c, d, cites, triggers, actor=LT.CLAUDE, basis="ATTESTED", accept=True, ts=None):
    t = L.transition(basis, [c.evidence],
                     closes=[L.mapping(d, "REVALIDATED", [c.evidence], triggers=triggers, revalidates=list(cites))],
                     scope_subject=LT.SHA_NEW)
    tid = c.record("propose", c.blob(t), actor, prior=[d], ts=ts)
    if accept:
        c.accept(LT.CODEX, d, tid)
    return tid


def assess(c):
    return L.assess(c.S.root, c.trust, LT.T_END, current={LT.SHA_NEW})


def cand(rep, d):
    return [(x["disposition"], x["verdict"], x["why"]) for x in rep["duties"][d]["candidates"]]


def main():
    # V01: fired -> STALE; an accepted revalidation over a new slice -> ELIGIBLE; history kept
    c = LT.Case()
    open_dep, done_dep = dep(c, False), dep(c, True)
    d = c.open()
    t1 = close(c, d, trig(open_dep))
    before = L.reliance(assess(c), d)
    rv = revalidate(c, d, [t1], trig(done_dep))
    rep = assess(c)
    trs = rep["duties"][d]["triggers"]
    check("V01", before == "STALE" and L.reliance(rep, d) == "ELIGIBLE" and rep["duties"][d]["disposition"] == "DISCHARGED"
          and rep["duties"][d]["closed_by"] == [t1]
          and [(t["closure"], t["result"], t["current"]) for t in trs] == [(t1, "FIRED", False), (rv, "NOT_FIRED", True)],
          "a revalidation restores eligibility; the fired trigger stays as history", (before, trs))

    # V02: without the creditor's acceptance the revalidation is pending and nothing changes
    c = LT.Case()
    open_dep, done_dep = dep(c, False), dep(c, True)
    d = c.open()
    t1 = close(c, d, trig(open_dep))
    revalidate(c, d, [t1], trig(done_dep), accept=False)
    rep = assess(c)
    check("V02", L.reliance(rep, d) == "STALE" and cand(rep, d)[-1][1] == "PENDING",
          "an unaccepted revalidation changes nothing", cand(rep, d))

    # V03: it can only revalidate admitted closures of THIS duty
    c = LT.Case()
    open_dep, done_dep = dep(c, False), dep(c, True)
    other = c.open(statement="other")
    t_other = close(c, other, [])
    d = c.open()
    close(c, d, trig(open_dep))
    revalidate(c, d, [t_other], trig(done_dep))
    rep = assess(c)
    check("V03", L.reliance(rep, d) == "STALE" and cand(rep, d)[-1][1] == "OVERCLAIMED"
          and "not an admitted closure of this duty" in cand(rep, d)[-1][2],
          "another duty's closure cannot be revalidated here", cand(rep, d))

    # V04: an OPEN duty has nothing to revalidate
    c = LT.Case()
    done_dep = dep(c, True)
    d = c.open()
    revalidate(c, d, ["ab" * 32], trig(done_dep))
    rep = assess(c)
    check("V04", rep["duties"][d]["disposition"] == "OPEN" and "nothing admitted" in cand(rep, d)[-1][2],
          "a revalidation never closes a duty", cand(rep, d))

    # V05: only the holder (or a delegate) revalidates
    c = LT.Case()
    open_dep, done_dep = dep(c, False), dep(c, True)
    d = c.open()
    t1 = close(c, d, trig(open_dep))
    revalidate(c, d, [t1], trig(done_dep), actor=LT.OWNER)
    rep = assess(c)
    check("V05", L.reliance(rep, d) == "STALE" and cand(rep, d)[-1][1] == "OVERCLAIMED",
          "a non-holder's revalidation is overclaimed", cand(rep, d))

    # V06: a revalidation whose own trigger fires is STALE again; a second one restores it
    c = LT.Case()
    open_dep, done_dep = dep(c, False), dep(c, True)
    d = c.open()
    t1 = close(c, d, trig(open_dep))
    rv1 = revalidate(c, d, [t1], trig(open_dep))
    mid = L.reliance(assess(c), d)
    revalidate(c, d, [rv1], trig(done_dep))
    check("V06", mid == "STALE" and L.reliance(assess(c), d) == "ELIGIBLE",
          "revalidations chain; each supersedes only what it names", mid)

    # V07: superseding is per named closure; an unnamed fired closure still counts
    c = LT.Case()
    open_dep, done_dep = dep(c, False), dep(c, True)
    d = c.open()
    t1 = close(c, d, trig(open_dep))
    t2 = close(c, d, trig(done_dep))
    revalidate(c, d, [t2], trig(done_dep))
    rep = assess(c)
    check("V07", L.reliance(rep, d) == "STALE" and any(t["closure"] == t1 and t["current"] for t in rep["duties"][d]["triggers"]),
          "a closure the revalidation does not name stays current", rep["duties"][d]["triggers"])

    # V08: malformed revalidation mappings refuse their transition
    c = LT.Case()
    d = c.open()
    t1 = close(c, d, [])
    bad = [L.mapping(d, "REVALIDATED", [c.evidence]),                                  # names nothing
           L.mapping(d, "DISCHARGED", [c.evidence], revalidates=[t1]),                 # not a revalidation
           L.mapping(d, "REVALIDATED", [c.evidence], revalidates=[]),                  # empty
           L.mapping(d, "REVALIDATED", [c.evidence], revalidates=[t1, t1]),            # duplicate
           L.mapping(d, "REVALIDATED", [c.evidence], revalidates=[t1], instance=0)]    # recurring instance
    ids = [c.record("propose", c.blob(L.transition("ATTESTED", [c.evidence], closes=[m])), LT.CLAUDE, prior=[d])
           for m in bad]
    try:     # without the schema rule the assessment would abort: record that as this case failing
        rep = assess(c)
        ok8 = all(i in rep["refused_events"] for i in ids) and rep["duties"][d]["disposition"] == "DISCHARGED"
        det8 = rep["refused_events"]
    except (KeyError, TypeError) as e:
        ok8, det8 = False, f"assessment aborted: {type(e).__name__}"
    check("V08", ok8, "malformed revalidations are refused, the view survives", det8)

    # V09: the basis must be one the duty admits for a discharge
    c = LT.Case()
    open_dep, done_dep = dep(c, False), dep(c, True)
    d = c.open()
    t1 = close(c, d, trig(open_dep))
    revalidate(c, d, [t1], trig(done_dep), basis="RUNNER_ATTESTED")
    rep = assess(c)
    check("V09", L.reliance(rep, d) == "STALE" and "is not admitted by this duty" in cand(rep, d)[-1][2],
          "a revalidation is admitted only on a basis the duty admits", cand(rep, d))

    # V10: it can only name closures admitted earlier in admission order. An earlier
    # closure exists, so the refusal is about order, not "nothing admitted".
    c = LT.Case()
    open_dep, done_dep = dep(c, False), dep(c, True)
    d = c.open()
    close(c, d, trig(open_dep), ts=30)
    t_late = L.transition("ATTESTED", [c.evidence], scope_subject=LT.SHA_NEW,
                          closes=[L.mapping(d, "DISCHARGED", [c.evidence], triggers=trig(done_dep))])
    # the revalidation is earlier in admission order (ts 45) than the closure it names (ts 50)
    late = c.record("propose", c.blob(t_late), LT.CLAUDE, prior=[d], ts=50)
    c.accept(LT.CODEX, d, late)
    revalidate(c, d, [late], trig(done_dep), ts=45)
    rep = assess(c)
    rv = [x for x in cand(rep, d) if x[0] == "REVALIDATED"]
    check("V10", L.reliance(rep, d) == "STALE" and len(rv) == 1 and rv[0][1] == "OVERCLAIMED"
          and "not an admitted closure" in rv[0][2],
          "a revalidation cannot name a closure admitted after it", cand(rep, d))

    failed = sorted(k for k, v in results.items() if v == "FAIL")
    print(f"REVALIDATION: {sum(v == 'PASS' for v in results.values())} PASS / {len(failed)} FAIL"
          + (f" ({', '.join(failed)})" if failed else ""))
    if os.environ.get("REVAL_RESULTS"):
        Path(os.environ["REVAL_RESULTS"]).write_text(json.dumps(results))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
