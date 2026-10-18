#!/usr/bin/env python3
"""Observation, schedule and challenge conditions (SPEC §3.4, §4.2-§4.4).

    python3 tests/conditions_test.py
"""
import sys

from world import CODEX, HOLDER, OBSERVER, OWNER, STRANGER, E, R, World, check, finish, verdicts


def observe_duty(w, fresh_for=None, schedule=None, accept_by=()):
    probe = w.blob({"argv": ["curl", "-s", "http://service/health"]})
    cond = {"observe": {"observers": [OBSERVER], "probe": probe, "expect": "ok", "fresh_for": fresh_for}}
    return w.duty(cond, accept_by=accept_by, schedule=schedule), probe


def observe(w, probe, result="ok", actor=OBSERVER, window=None, at=None):
    at = w.tick(at)
    return w.file("observation", actor, R.observation("http://service/health", probe, window or [at - 1, at], result), at)


def last(rep, d):
    return rep["duties"][d]["candidates"][-1]


def observation_cases():
    # B1: the executor's "done" is not an observation
    w = World()
    d, probe = observe_duty(w)
    w.close(d)
    rep = w.assess()
    check("B1", last(rep, d)["verdict"] == "OVERCLAIMED", "an observed condition is not met by the filer's word", verdicts(rep, d))
    # B2: observed by someone not named, with another probe, or another result: not met
    for actor, pr, result, label in ((STRANGER, probe, "ok", "B2a"), (OBSERVER, w.blob({"argv": ["true"]}), "ok", "B2b"),
                                     (OBSERVER, probe, "503", "B2c")):
        o = observe(w, pr, result=result, actor=actor)
        w.close(d, basis="OBSERVED", evidence=[o])
        rep = w.assess()
        check(label, last(rep, d)["verdict"] == "UNMET_CONDITION", f"an observation that does not meet the condition ({label})",
              last(rep, d))
    # B3: the filer cannot be its own observer
    w = World()
    probe = w.blob({"argv": ["curl", "-s", "http://service/health"]})
    d = w.duty({"observe": {"observers": [HOLDER, OBSERVER], "probe": probe, "expect": "ok", "fresh_for": None}}, accept_by=())
    o = observe(w, probe, actor=HOLDER)
    w.close(d, basis="OBSERVED", evidence=[o])
    rep = w.assess()
    check("B3", last(rep, d)["verdict"] == "UNMET_CONDITION" and "own closure" in last(rep, d)["why"],
          "the filer's own observation does not close its duty", last(rep, d))
    # B4: a named observer's matching observation closes it; it goes stale after fresh_for
    w = World()
    d, probe = observe_duty(w, fresh_for=100)
    o = observe(w, probe, at=500)
    w.close(d, basis="OBSERVED", evidence=[o], at=510)
    fresh, stale = w.assess(as_of=550), w.assess(as_of=700)
    check("B4", E.reliance(fresh, d, "act")["state"] == "ELIGIBLE" and E.reliance(stale, d, "act")["state"] == "STALE"
          and fresh["duties"][d]["disposition"] == stale["duties"][d]["disposition"] == "DISCHARGED",
          "fresh within fresh_for, stale after it; the closure itself stays", (E.reliance(fresh, d, "act"), E.reliance(stale, d, "act")))

    # B5 (R138-01, Codex review of 1235d1e): only an observation that met the
    # condition refreshes a closure. A fresh record cited alongside a stale good one
    # -- by a stranger, by the filer itself, with another probe, or with another
    # result -- leaves it STALE; a fresh matching observation refreshes it, and it
    # goes stale again after fresh_for.
    w = World()
    d, probe = observe_duty(w, fresh_for=100)
    good = observe(w, probe, at=500)
    w.close(d, basis="OBSERVED", evidence=[good], at=510)
    other = w.blob({"argv": ["false"]})
    stale = []
    for k, (actor, pr, result) in enumerate(((STRANGER, probe, "ok"), (HOLDER, probe, "ok"),
                                             (OBSERVER, other, "ok"), (OBSERVER, probe, "503"))):
        o = observe(w, pr, result=result, actor=actor, at=940 + k)
        w.close(d, basis="OBSERVED", evidence=[good, o], at=950 + k)
        stale.append(E.reliance(w.assess(as_of=1000), d, "act")["state"])
    fresh = observe(w, probe, at=980)
    w.close(d, basis="OBSERVED", evidence=[fresh], at=990)
    now, later = E.reliance(w.assess(as_of=1000), d, "act")["state"], E.reliance(w.assess(as_of=1200), d, "act")["state"]
    check("B5", stale == ["STALE"] * 4 and (now, later) == ("ELIGIBLE", "STALE"),
          "only observations that met the condition count for freshness", (stale, now, later))


def schedule_cases():
    # Q1: one period covered, one lapsed, one open; nothing covers another period
    w = World()
    d = w.duty(schedule={"start": 1000, "every": 100})
    t0 = w.close(d, period=0, at=1050)
    w.accept(OWNER, t0, at=1051)
    rep = w.assess(as_of=1250)
    p = rep["duties"][d]["periods"]
    check("Q1", (p["0"]["state"], p["1"]["state"], p["2"]["state"]) == ("COVERED", "LAPSED", "OPEN")
          and "LAPSED" in rep["duties"][d]["flags"], "a past discharge does not cover a later period", p)
    # Q2: a period cannot be discharged before it starts
    t2 = w.close(d, period=2, at=1100)
    w.accept(OWNER, t2, at=1101)
    rep = w.assess(as_of=1250)
    check("Q2", rep["duties"][d]["periods"]["2"]["state"] == "OPEN" and last(rep, d)["verdict"] == "OVERCLAIMED",
          "an early discharge of a future period is refused", last(rep, d))
    # Q3: a scheduled observation must fall inside the period it covers
    w = World()
    d, probe = observe_duty(w, schedule={"start": 1000, "every": 100})
    o = observe(w, probe, window=[1010, 1020], at=1020)
    w.close(d, basis="OBSERVED", evidence=[o], period=1, at=1150)
    rep = w.assess(as_of=1199)
    check("Q3", rep["duties"][d]["periods"]["1"]["state"] == "OPEN" and "outside the period" in last(rep, d)["why"],
          "an observation from period 0 does not cover period 1", last(rep, d))


def challenge_cases():
    # K1: a counterexample by the creditor makes reliance CHALLENGED; history stays DISCHARGED
    w = World()
    d = w.duty(owed_to=(CODEX,), accept_by=(CODEX,))
    t = w.close(d)
    w.accept(CODEX, t)
    ch = w.file("challenge", CODEX, R.challenge(t, "it fails on empty input", [w.evidence("repro")], 0))
    rep = w.assess()
    check("K1", E.reliance(rep, d, "act")["state"] == "CHALLENGED" and rep["duties"][d]["disposition"] == "DISCHARGED",
          "a counting challenge blocks present reliance and rewrites nothing", E.reliance(rep, d, "act"))
    # K2: a stranger's challenge does not count unless the recipient listens to it
    w2 = World()
    d2 = w2.duty(owed_to=(CODEX,), accept_by=(CODEX,))
    t2 = w2.close(d2)
    w2.accept(CODEX, t2)
    w2.file("challenge", STRANGER, R.challenge(t2, "noise", [], 0))
    a = E.reliance(w2.assess(), d2, "act")["state"]
    b = E.reliance(w2.assess(prof=E.profile(challengers=[STRANGER])), d2, "act")["state"]
    check("K2", (a, b) == ("ELIGIBLE", "CHALLENGED"), "who may block reliance is the recipient's choice", (a, b))
    # K3: an accepted revalidation that resolves the challenge restores eligibility
    rv = w.close(d, act="revalidate", revalidates=[t])
    w.accept(CODEX, rv)
    rep = w.assess()
    check("K3", E.reliance(rep, d, "act")["state"] == "ELIGIBLE" and ch in rep["challenges"],
          "an accepted revalidation of the challenged closure restores reliance; the challenge stays in the record", E.reliance(rep, d, "act"))


def main():
    observation_cases()
    schedule_cases()
    challenge_cases()
    return finish("CONDITIONS")


if __name__ == "__main__":
    sys.exit(main())
