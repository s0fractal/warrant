#!/usr/bin/env python3
"""Rules of SPEC §4.1-§6 that had no witness case of their own before the
claim records (`.warrant/store`, `tools/claims.py`): each case is one sentence
of the SPEC, cited by its claim, with the mutant in tests/mutants.py that burns it.
R1-R13 are §4.1-§4.4 (pilot W); R14-R28 are §4.5-§6 (pilot W2); R29-R35 are §7-§9
(pilot W3; the §7 cases that need a provider run are C19-C28 of compute_test.py).

    python3 tests/assessment_test.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from world import CODEX, HOLDER, OWNER, SHA_NEW, SHA_OLD, STRANGER, E, P, R, W, World, check, finish, verdicts
from warrant import jcs as C
from warrant import limits as L
from warrant import triggers as TR
from warrant.store import MAX_FILE, Snapshot, Trust


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


def release(w, d, actor, at, label="release"):
    return w.close(d, actor=actor, act="release", evidence=[w.evidence(label)], at=at)


def grant_cases():
    # R14 (§4.5): a grant counts only from its own position on: a release filed before
    # the root grant that would authorize it is refused; one filed after it is admitted
    w = World()
    d = w.duty()
    root = w.file("grant", OWNER, R.grant(STRANGER, ["release"], [d]), at=300)
    early = release(w, d, STRANGER, 200, "early")
    late = release(w, d, STRANGER, 400, "late")
    rep = w.assess(prof=E.profile(grant_roots=[root]))
    got = (verdict_of(rep, d, early)["verdict"], "NOT_YET" in verdict_of(rep, d, early)["why"],
           verdict_of(rep, d, late)["verdict"], rep["duties"][d]["disposition"])
    check("R14", got == ("OVERCLAIMED", True, "ADMITTED", "RELEASED"),
          "a grant does not authorize an act filed before the grant itself", got)

    # R15 (§4.5): a grant has not expired at the act's position; `expires` is exclusive
    w = World()
    d1, d2 = w.duty(statement="one"), w.duty(statement="two")
    g = w.file("grant", OWNER, R.grant(STRANGER, ["release"], [d1, d2], expires=300), at=150)
    before = release(w, d1, STRANGER, 299)
    at_end = release(w, d2, STRANGER, 300)
    rep = w.assess(prof=E.profile(grant_roots=[g]))
    got = (verdict_of(rep, d1, before)["verdict"], verdict_of(rep, d2, at_end)["verdict"],
           "EXPIRED" in verdict_of(rep, d2, at_end)["why"], rep["grants"][g])
    check("R15", got == ("ADMITTED", "OVERCLAIMED", True, "EXPIRED"),
          "a grant authorizes before its expiry and not at it", got)

    # R16 (§4.5): a child grant needs its parent valid at the CHILD's own position: a child
    # filed before its parent, or naming a parent not in the view, is a broken chain even
    # once the parent exists; the same child filed after the parent authorizes
    w = World()
    d1, d2 = w.duty(statement="one"), w.duty(statement="two")
    parent = w.file("grant", OWNER, R.grant(STRANGER, ["release"], [d1, d2], delegable=["release"]), at=300)
    before = w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d1], parent=parent), at=200)
    orphan = w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d1], parent="ab" * 32), at=360)
    after = w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d2], parent=parent), at=350)
    r1, r2 = release(w, d1, CODEX, 400, "one"), release(w, d2, CODEX, 401, "two")
    rep = w.assess(prof=E.profile(grant_roots=[parent]))
    got = guarded(lambda: ({k: rep["grants"][g] for k, g in (("before", before), ("orphan", orphan), ("after", after))},
                           verdict_of(rep, d1, r1)["verdict"], verdict_of(rep, d2, r2)["verdict"]))
    check("R16", got == ({"before": "BROKEN_CHAIN", "orphan": "BROKEN_CHAIN", "after": "VALID"}, "OVERCLAIMED", "ADMITTED"),
          "a parent is judged at its child's position, and must be in the view", got)

    # R17 (§4.5): an attenuation is filed by the parent's grantee, names only the parent's
    # duties, and expires no later than the parent; the control child does all three
    w = World()
    d1, d2, d3 = w.duty(statement="one"), w.duty(statement="two"), w.duty(statement="three")
    p = w.file("grant", OWNER, R.grant(STRANGER, ["release"], [d1, d2], delegable=["release"], expires=5000))
    kids = {
        "control": w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d1], parent=p, expires=4000)),
        "grantor": w.file("grant", CODEX, R.grant(HOLDER, ["release"], [d1], parent=p, expires=4000)),
        "duties": w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d1, d3], parent=p, expires=4000)),
        "later": w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d2], parent=p, expires=6000)),
        "never": w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d2], parent=p)),
    }
    rep = w.assess(as_of=1000, prof=E.profile(grant_roots=[p]))
    got = {k: rep["grants"][g] for k, g in kids.items()}
    check("R17", got == {"control": "VALID", "grantor": "NOT_ATTENUATED", "duties": "NOT_ATTENUATED",
                         "later": "NOT_ATTENUATED", "never": "NOT_ATTENUATED"},
          "a child beyond its parent's grantee, duties or expiry is not an attenuation", got)

    # R49 (§4.5, G7): "within" and "no later" include equality: a child whose delegable is exactly
    # its parent's, and one that expires exactly when its parent does, are attenuations. Found by
    # the generated-mutant hunt: `<=` -> `<` on delegable and `>` -> `>=` on expires survived R17.
    w = World()
    d1 = w.duty(statement="one")
    p = w.file("grant", OWNER, R.grant(STRANGER, ["release"], [d1], delegable=["release"], expires=5000))
    kids = {
        "same delegable": w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d1], delegable=["release"], parent=p,
                                                            expires=4000)),
        "same expiry": w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d1], parent=p, expires=5000)),
        "one later": w.file("grant", STRANGER, R.grant(CODEX, ["release"], [d1], parent=p, expires=5001)),
    }
    rep = w.assess(as_of=1000, prof=E.profile(grant_roots=[p]))
    got = {k: rep["grants"][g] for k, g in kids.items()}
    check("R49", got == {"same delegable": "VALID", "same expiry": "VALID", "one later": "NOT_ATTENUATED"},
          "a child equal to its parent's delegable, or expiring with it, is an attenuation; one second later is not", got)

    # R18 (§4.5): a grant record signed by a key bound to another actor than its grantor
    # is invalid, even when the recipient lists its id as a root; the same grant signed
    # by its grantor authorizes
    w = World()
    d1, d2 = w.duty(statement="one"), w.duty(statement="two")
    forged = w.store.put_record(R.record("grant", OWNER, w.tick(), R.grant(STRANGER, ["release"], [d1])), w.keys[CODEX])
    real = w.file("grant", OWNER, R.grant(STRANGER, ["release"], [d2]))
    r1, r2 = release(w, d1, STRANGER, 400, "one"), release(w, d2, STRANGER, 401, "two")
    rep = w.assess(prof=E.profile(grant_roots=[forged, real]))
    got = (forged in rep["invalid_records"], forged in rep["grants"], verdict_of(rep, d1, r1)["verdict"],
           verdict_of(rep, d2, r2)["verdict"])
    check("R18", got == (True, False, "OVERCLAIMED", "ADMITTED"),
          "a grant not signed by its grantor is invalid; signed by it, it authorizes", got)


def profile_cases():
    # R19 (§4.6): the profile's accept_by.results names whose acceptance closes a
    # transition's results: a stranger's acceptance does not; the named acceptor's does;
    # a profile that names nobody leaves results unassessed
    w = World()
    t = w.act(HOLDER, [], established=["the API is v2"])
    w.accept(STRANGER, t, None)
    prof = E.profile(results_by=[OWNER])
    stranger_only = E.reliance(w.assess(prof=prof), t, "act")["state"]
    w.accept(OWNER, t, None)
    named = E.reliance(w.assess(prof=prof), t, "act")["state"]
    nobody = E.reliance(w.assess(), t, "act")["state"]
    got = (stranger_only, named, nobody)
    check("R19", got == ("NOT_CLOSED", "ELIGIBLE", "UNASSESSED"),
          "only an acceptor the profile names closes results", got)

    # R20 (§4.6): with no challengers listed, a challenge by the duty's owed_to actor counts,
    # and so does one by its accept_by actor (here two different actors); a stranger's does not
    def challenged_by(actor):
        w = World()
        d = w.duty(owed_to=(OWNER,), accept_by=(CODEX,))
        t = w.close(d)
        w.accept(CODEX, t)
        w.file("challenge", actor, R.challenge(t, f"{actor} disagrees", [w.evidence("repro")], 0))
        return E.reliance(w.assess(), d, "act")["state"]
    got = {a: challenged_by(a) for a in (OWNER, CODEX, STRANGER)}
    check("R20", got == {OWNER: "CHALLENGED", CODEX: "CHALLENGED", STRANGER: "ELIGIBLE"},
          "owed_to and accept_by of the duty always count as challengers; a stranger does not", got)


def supersession_cases():
    # R21 (§4.7): A <- B <- C, all accepted as results: A and B are superseded, C is current;
    # as of A's own time A was relied on; in a view where C is absent, B is current and A
    # stays superseded (A never returns without a record that says so)
    w = World()
    prof = E.profile(results_by=[OWNER])
    a = w.act(HOLDER, [], established=["the API is v1"], at=200)
    w.accept(OWNER, a, None, at=201)
    b = w.act(HOLDER, [], established=["the API is v2"], supersedes=[a], at=300)
    w.accept(OWNER, b, None, at=301)
    c = w.act(HOLDER, [], established=["the API is v3"], supersedes=[b], at=400)
    acc_c = w.accept(OWNER, c, None, at=401)

    def states(rep):
        return tuple(E.reliance(rep, x, "act")["state"] for x in (a, b, c))
    full = states(w.assess(prof=prof))
    then = E.reliance(w.assess(as_of=250, prof=prof), a, "act")["state"]
    part = w.dir / "without-c"
    shutil.copytree(w.store.root, part)
    for rid in (c, acc_c):
        (part / "records" / f"{rid}.json").unlink()
    without_c = states(E.assess(Snapshot.read(part), w.trust, 10_000, prof))
    got = (full, then, without_c)
    check("R21", got == (("SUPERSEDED", "SUPERSEDED", "ELIGIBLE"), "ELIGIBLE", ("SUPERSEDED", "ELIGIBLE", "MISSING")),
          "a superseded result was valid in its time; without C, B is current and A does not return", got)


# ---------------------------------------------------------------- triggers (SPEC §5)

GIT = ["git", "-c", "user.name=warrant-test", "-c", "user.email=test@invalid", "-c", "commit.gpgsign=false"]


def git(repo, *args):
    return subprocess.run([*GIT, "-C", str(repo), *args], capture_output=True, check=True, text=True).stdout.strip()


def commit(repo, files, symlinks=(), gitlinks=(), executable=(), remove=()):
    """Write `files` {path: text}, symlinks {path: target}, gitlinks {path: commit},
    mark `executable` and delete `remove`; commit everything; return the commit id."""
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    for path, target in dict(symlinks).items():
        os.symlink(target, repo / path)
    for path in executable:
        os.chmod(repo / path, 0o755)
    for path in remove:
        (repo / path).unlink()
    git(repo, "add", "-A")
    for path, oid in dict(gitlinks).items():
        git(repo, "update-index", "--add", "--cacheinfo", f"160000,{oid},{path}")
    git(repo, "commit", "-q", "--allow-empty", "-m", "fixture")
    return git(repo, "rev-parse", "HEAD")


def baseline(w, selector, entries):
    """A baseline manifest built by hand (never by the package under test):
    entries {path: (mode, bytes)}."""
    return w.blob({"selector": list(selector),
                   "entries": {p: {"mode": m, "sha256": hashlib.sha256(data).hexdigest()} for p, (m, data) in entries.items()}})


def changed(w, h):
    return [{"kind": "subject_changed", "baseline": h}]


def trigger_results(rep, ts):
    return {k: rep["results"][t]["triggers"][0]["result"] for k, t in ts.items()}


def trigger_cases():
    # R22 (§5): every trigger evaluates to one of FIRED, NOT_FIRED, UNEVALUABLE, all three
    # occurring here; a duty in a state the trigger does not name (CONTESTED) is
    # UNEVALUABLE, never its own state passed through (the engine refuses a result outside
    # the vocabulary, so a mutant that passes one through fails this case)
    def r22():
        w = World()
        open_d, done = w.duty(statement="open"), w.duty(statement="done")
        w.accept(OWNER, w.close(done))
        contested = w.duty(statement="contested")
        w.accept(OWNER, w.close(contested))
        w.close(contested, actor=OWNER, act="release")
        on = {"open": open_d, "done": done, "contested": contested, "absent": "cd" * 32}
        ts = {k: w.act(HOLDER, [], established=[k], triggers=[{"kind": "duty_not_discharged", "duty": x}])
              for k, x in on.items()}
        manifest = baseline(w, ["b.txt"], {"b.txt": ("100644", b"beta\n")})
        ts["no workspace"] = w.act(HOLDER, [], established=["subject"], triggers=changed(w, manifest))
        rep = w.assess()
        res = trigger_results(rep, ts)
        return res, set(res.values()) == set(TR.RESULTS)
    got = guarded(r22)
    check("R22", got == ({"open": "FIRED", "done": "NOT_FIRED", "contested": "UNEVALUABLE", "absent": "UNEVALUABLE",
                          "no workspace": "UNEVALUABLE"}, True),
          "each trigger evaluates to exactly one of FIRED, NOT_FIRED, UNEVALUABLE", got)

    repo = Path(tempfile.mkdtemp(prefix="warrant-trigger-"))
    git(repo, "init", "-q")
    first = commit(repo, {"a.txt": "alpha\n", "b.txt": "beta\n", "c.sh": "echo c\n", "d.txt": "delta\n",
                          "sub/inner.txt": "inner\n"}, symlinks={"link": "a.txt"})
    second = commit(repo, {"a.txt": "alpha, changed\n"}, executable=["c.sh"], remove=["d.txt"], gitlinks={"mod": first})
    plain = "100644"

    # R23 (§5): a baseline names explicit, sorted, repository-relative file paths: an unsorted
    # selector, a path out of the repository, a glob, a directory, a symlink and a submodule
    # are all UNEVALUABLE; the control (one plain file, unchanged) is NOT_FIRED
    def r23():
        w = World()
        b = (plain, b"beta\n")
        base = {
            "control": baseline(w, ["b.txt"], {"b.txt": b}),
            "unsorted": baseline(w, ["b.txt", "a.txt"], {"a.txt": (plain, b"alpha, changed\n"), "b.txt": b}),
            "outside": baseline(w, ["../b.txt"], {"../b.txt": b}),
            "glob": baseline(w, ["*.txt"], {"*.txt": b}),
            "directory": baseline(w, ["sub"], {"sub": (plain, b"inner\n")}),
            "symlink": baseline(w, ["link"], {"link": (plain, b"a.txt")}),
            "submodule": baseline(w, ["mod"], {"mod": (plain, first.encode())}),
        }
        ts = {k: w.act(HOLDER, [], established=[k], triggers=changed(w, h)) for k, h in base.items()}
        return trigger_results(w.assess(workspace=(repo, second)), ts)
    got = guarded(r23)
    want = dict({k: "UNEVALUABLE" for k in ("unsorted", "outside", "glob", "directory", "symlink", "submodule")},
                control="NOT_FIRED")
    check("R23", got == want, "only explicit, sorted, repository-relative file paths are evaluated", got)

    # R24 (§5): against the workspace commit, a changed file (content or mode) FIRES, an
    # unchanged one does not, and a deleted path, an absent or unreadable baseline, an
    # unreadable revision and a missing workspace are UNEVALUABLE. A FIRED trigger makes
    # its result STALE; a NOT_FIRED subject_changed gives a result established on an old
    # revision its revision basis.
    def r24():
        w = World()
        base = {
            "content": baseline(w, ["a.txt"], {"a.txt": (plain, b"alpha\n")}),
            "unchanged": baseline(w, ["b.txt"], {"b.txt": (plain, b"beta\n")}),
            "mode": baseline(w, ["c.sh"], {"c.sh": (plain, b"echo c\n")}),
            "deleted": baseline(w, ["d.txt"], {"d.txt": (plain, b"delta\n")}),
            "absent baseline": "ef" * 32,
            "not a manifest": w.blob({"selector": ["b.txt"]}),
        }
        prof = E.profile(results_by=[OWNER])
        ts = {}
        for k, h in base.items():
            ts[k] = w.act(HOLDER, [], established=[k], subject=SHA_OLD, triggers=changed(w, h))
            w.accept(OWNER, ts[k], None)
        rep = w.assess(prof=prof, workspace=(repo, second))
        res = trigger_results(rep, ts)
        rel = {k: E.reliance(rep, ts[k], "act")["state"] for k in ("content", "unchanged")}
        res["no workspace"] = trigger_results(w.assess(prof=prof), ts)["unchanged"]
        res["unknown revision"] = trigger_results(w.assess(prof=prof, workspace=(repo, "f" * 40)), ts)["unchanged"]
        return res, rel
    got = guarded(r24)
    want = ({"content": "FIRED", "unchanged": "NOT_FIRED", "mode": "FIRED", "deleted": "UNEVALUABLE",
             "absent baseline": "UNEVALUABLE", "not a manifest": "UNEVALUABLE", "no workspace": "UNEVALUABLE",
             "unknown revision": "UNEVALUABLE"}, {"content": "STALE", "unchanged": "ELIGIBLE"})
    check("R24", got == want, "subject_changed fires on a changed entry, and is UNEVALUABLE when anything cannot be read", got)
    shutil.rmtree(repo, ignore_errors=True)

    # R25 (§5): duty_not_discharged FIRES for an OPEN, RELEASED or IMPOSSIBLE duty, does not
    # for a DISCHARGED one, and is UNEVALUABLE otherwise: CONTESTED, SCHEDULED, absent
    def r25():
        w = World()
        on = {k: w.duty(statement=k) for k in ("OPEN", "RELEASED", "IMPOSSIBLE", "DISCHARGED", "CONTESTED")}
        on["SCHEDULED"] = w.duty(statement="scheduled", schedule={"start": 1000, "every": 1000})
        w.close(on["RELEASED"], actor=OWNER, act="release")
        w.accept(OWNER, w.close(on["IMPOSSIBLE"], act="impossible"))
        w.accept(OWNER, w.close(on["DISCHARGED"]))
        w.accept(OWNER, w.close(on["CONTESTED"]))
        w.close(on["CONTESTED"], actor=OWNER, act="release")
        on["absent"] = "cd" * 32
        ts = {k: w.act(HOLDER, [], established=[k], triggers=[{"kind": "duty_not_discharged", "duty": x}])
              for k, x in on.items()}
        rep = w.assess()
        disp = {k: rep["duties"][x]["disposition"] for k, x in on.items() if k != "absent"}
        return disp == {k: k for k in disp}, trigger_results(rep, ts)
    got = guarded(r25)
    want = (True, {"OPEN": "FIRED", "RELEASED": "FIRED", "IMPOSSIBLE": "FIRED", "DISCHARGED": "NOT_FIRED",
                   "CONTESTED": "UNEVALUABLE", "SCHEDULED": "UNEVALUABLE", "absent": "UNEVALUABLE"})
    check("R25", got == want, "duty_not_discharged: FIRED, NOT_FIRED or UNEVALUABLE by the duty's disposition", got)


def authority_cases():
    # R26 (§6): the duty says who may act: an actor in release_by (not owed_to) may release
    # it; a stranger may not
    w = World()
    d1 = w.duty(statement="one", release_by=(CODEX,))
    d2 = w.duty(statement="two", release_by=(CODEX,))
    by_named = release(w, d1, CODEX, 300)
    by_stranger = release(w, d2, STRANGER, 301)
    rep = w.assess()
    got = (verdict_of(rep, d1, by_named)["verdict"], rep["duties"][d1]["disposition"],
           verdict_of(rep, d2, by_stranger)["verdict"], rep["duties"][d2]["disposition"])
    check("R26", got == ("ADMITTED", "RELEASED", "OVERCLAIMED", "OPEN"), "release_by may release; a stranger may not", got)

    # R27 (§6): competence is not assessed: a holder whose closure of one duty stands
    # challenged, and whose filing on another was overclaimed, has its closure of a third
    # duty admitted and relied on like anyone's
    w = World()
    challenged = w.duty(statement="challenged", owed_to=(CODEX,), accept_by=(CODEX,))
    t = w.close(challenged)
    w.accept(CODEX, t)
    w.file("challenge", CODEX, R.challenge(t, "it fails on empty input", [w.evidence("repro")], 0))
    over = w.duty(statement="overclaimed")
    w.accept(OWNER, w.close(over, basis="OBSERVED"))
    fresh = w.duty(statement="unrelated")
    w.accept(OWNER, w.close(fresh, evidence=[w.evidence("fresh")]))
    rep = w.assess()
    got = guarded(lambda: (E.reliance(rep, challenged, "act")["state"], last(rep, over)["verdict"],
                           rep["duties"][fresh]["disposition"], E.reliance(rep, fresh, "act")["state"]))
    check("R27", got == ("CHALLENGED", "OVERCLAIMED", "DISCHARGED", "ELIGIBLE"),
          "a filer's record on other duties does not weigh on this one", got)

    # R28 (§6): delegation cannot widen what the holder could do: once the holder has passed
    # the duty on, its delegate's closure is refused like the holder's own
    w = World()
    d = w.duty()
    dl = w.close(d, act="delegate", to=CODEX, at=200)
    w.accept(CODEX, dl, at=201)
    sub = w.close(d, act="substitute", to=STRANGER, at=300)
    w.accept(STRANGER, sub, at=301)
    w.accept(OWNER, sub, at=302)
    c = w.close(d, actor=CODEX, at=400)
    w.accept(OWNER, c, at=401)
    rep = w.assess()
    got = (rep["duties"][d]["holder"], rep["duties"][d]["delegates"], verdict_of(rep, d, c)["verdict"],
           rep["duties"][d]["disposition"])
    check("R28", got == (STRANGER, [], "OVERCLAIMED", "OPEN"),
          "a delegate acts only while its delegator holds the duty", got)


def runtime_cases():
    # R29 (§7): Warrant's runtime ids are the kernel's own: the record shape admits
    # exactly the runtimes the installed sigma_resume defines, Book I and the draft
    # profile with Y, M, W (asked of sigma_resume in a separate interpreter, never
    # imported here)
    code = ("import json,sigma_resume as r;"
            "print(json.dumps([sorted(r.PROFILES), r.RUNTIME_SEMANTICS_ID, r.RICH_RUNTIME_ID]))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tempfile.gettempdir())
    theirs = json.loads(out.stdout) if out.returncode == 0 else out.stderr[-200:]
    mine = [sorted(R.RUNTIMES), P.BOOK1, P.RICH]
    check("R29", theirs == mine and list(R.RUNTIMES) == [P.BOOK1, P.RICH],
          "the runtime ids a condition may name are the kernel's own", (theirs, mine))


def capsule_cases():
    # R30 (§8): a capsule, for a duty and for a transition, carries the result, its
    # basis and acceptors, its limits, the current triggers with their results and the
    # challenges under which it must be revisited, and its evidence by id only
    w = World()
    other = w.duty(statement="other")
    d = w.duty()
    ev = w.evidence("the shipped bytes")
    trig = [{"kind": "duty_not_discharged", "duty": other}]
    t = w.act(HOLDER, [R.item(d, "discharge", [ev], triggers=trig)], established=["shipped"],
              residual=["not load-tested"], subject=SHA_NEW, triggers=trig)
    w.accept(OWNER, t)
    w.accept(OWNER, t, None)
    # One challenge of the closure (item 0), one of the results (item null): each capsule
    # names its own. Until the Gemini review (defect A) this case filed only the item-null
    # challenge and expected it in the duty's capsule too.
    ch = w.file("challenge", CODEX, R.challenge(t, "it fails on empty input", [w.evidence("repro")], 0))
    ch_results = w.file("challenge", CODEX, R.challenge(t, "it was not shipped", [w.evidence("repro")], None))
    rep = w.assess(prof=E.profile(challengers=[CODEX], results_by=[OWNER]))
    dc, tc = E.capsule(rep, d), E.capsule(rep, t)
    def fired(c):
        return [(x["kind"], x["duty"], x["result"]) for x in c["revalidate_when"]]
    got = guarded(lambda: {
        "duty": (dc["kind"], dc["disposition"], dc["basis"], dc["accept_by"], dc["limits"], fired(dc),
                 dc["challenges"], dc["evidence"], dc["completeness"]),
        "transition": (tc["kind"], tc["established"], tc["basis"], tc["accepted_by"], tc["limits"], tc["subject"],
                       fired(tc), tc["challenges"], tc["evidence"], tc["completeness"]),
        "bytes": "the shipped bytes" in json.dumps([dc, tc])})
    want = {"duty": ("duty", "DISCHARGED", [f"ATTESTED:{HOLDER}"], [OWNER], ["not load-tested"],
                     [("duty_not_discharged", other, "FIRED")], [ch], [ev], "UNATTESTED"),
            "transition": ("transition", ["shipped"], "ATTESTED", [OWNER], ["not load-tested"], SHA_NEW,
                           [("duty_not_discharged", other, "FIRED")], [ch_results], [ev], "UNATTESTED"),
            "bytes": False}
    check("R30", got == want, "a capsule names result, basis, limits, revisit conditions and evidence ids", got)


def frontier_cases():
    # R31 (§8): an actor's frontier lists the duties it holds or is delegated, periods
    # lapsed or open, results acceptances it owes under accept_by.results (marked
    # `under`), and challenges against its closures
    w = World()
    ds = w.duty(statement="weekly", schedule={"start": 1000, "every": 100}, at=1000)
    dd = w.duty(statement="delegated")
    w.accept(CODEX, w.close(dd, act="delegate", to=CODEX))
    dc = w.duty(statement="challenged")
    tc = w.close(dc)
    w.accept(OWNER, tc)
    w.file("challenge", CODEX, R.challenge(tc, "it fails on empty input", [w.evidence("repro")], 0))
    tr = w.act(HOLDER, [], established=["a result"])
    rep = w.assess(as_of=1250, prof=E.profile(results_by=[OWNER], challengers=[CODEX]))
    def needs(actor):
        return sorted((x.get("duty") or x.get("transition"), x["need"], x.get("under"))
                      for x in E.frontier(rep, actor))
    got = guarded(lambda: (needs(HOLDER), needs(CODEX), needs(OWNER)))
    want = (sorted([(dc, "revalidate (CHALLENGED for act)", None), (dd, "close", None),
                    (ds, "period 0 LAPSED", None), (ds, "period 1 LAPSED", None), (ds, "period 2 OPEN", None)]),
            [(dd, "close", None)], [(tr, "accept results", "profile accept_by.results")])
    check("R31", got == want, "the frontier lists held and delegated duties, periods, results owed and challenges", got)


def refusal_cases():
    # R32 (§9): what this version does not have is refused, never approximated: a
    # P-256 public key, a key binding with an expiry, a duty with a threshold, a
    # cmd@v1 or ski@v1 condition, a grant for an act other than release, a grant
    # with a revocation member. The controls (the same shapes without them) are valid.
    w = World()
    d = w.duty()
    duty = R.duty(HOLDER, "x", [OWNER], {"attest": {}}, accept_by=[OWNER])
    grant = R.grant(HOLDER, ["release"], [d])
    ed = W.Key.generate().public
    def ok(fn):
        try:
            fn()
            return "valid"
        except ValueError as e:
            return "refused" if isinstance(e, R.Invalid) else f"ValueError: {e}"
        except Exception as e:      # noqa: BLE001
            return f"raised {type(e).__name__}"
    shapes = {
        "P-256 key": lambda: Trust(Trust.document([("p", "02" + "ab" * 32)])),
        "key expiry": lambda: Trust({"warrant": "trust/2", "keys": [{"actor": "p", "public": ed, "until": 500}]}),
        "threshold": lambda: R.record("duty", HOLDER, 1, dict(duty, threshold=1)),
        "cmd@v1": lambda: R.record("duty", HOLDER, 1, dict(duty, condition={"cmd@v1": {}})),
        "ski@v1": lambda: R.record("duty", HOLDER, 1, dict(duty, condition={"ski@v1": {}})),
        "grant discharge": lambda: R.record("grant", OWNER, 1, R.grant(HOLDER, ["discharge"], [d])),
        "grant revoked": lambda: R.record("grant", OWNER, 1, dict(grant, revoked=True)),
    }
    controls = {"Ed25519 key": lambda: Trust(Trust.document([("p", ed)])),
                "duty": lambda: R.record("duty", HOLDER, 1, duty),
                "grant": lambda: R.record("grant", OWNER, 1, grant)}
    got = ({k: ok(f) for k, f in shapes.items()}, {k: ok(f) for k, f in controls.items()})
    check("R32", got == ({k: "refused" for k in shapes}, {k: "valid" for k in controls}),
          "P-256, key expiry, thresholds, cmd@v1/ski@v1, other grant acts and grant revocation are refused", got)


def _limits_view():
    w = World()
    ds = w.duty(statement="weekly", schedule={"start": 0, "every": 10}, at=0)
    w.accept(OWNER, w.close(ds, period=0, at=5, evidence=[w.evidence("period 0")]), at=6)
    child, child2 = w.duty(statement="child"), w.duty(statement="child 2")
    parent = w.duty(statement="parent", requires=sorted([child, child2]))
    w.accept(OWNER, w.close(child, evidence=[w.evidence("child")]))
    w.close(parent, evidence=[w.evidence("parent")])
    return w, w.store.snapshot()


def limit_cases():
    # R33 (§9): a view within every limit is assessed exactly as without limits: with
    # each limit set to the view's own count the report is the default one, byte for
    # byte, under the same identity; one below any of them is refused
    w, snap = _limits_view()
    size = sum(map(len, snap.records.values())) + sum(map(len, snap.blobs.values()))
    exact = {"snapshot_records": len(snap.records), "snapshot_blobs": len(snap.blobs), "snapshot_bytes": size,
             "requires_edges": 2, "duty_periods": 3, "report_periods": 3}
    def run():
        base = E.assess(snap, w.trust, 25, E.profile())
        tight = E.assess(snap, w.trust, 25, E.profile(), limits=exact)
        below = {}
        for k, v in exact.items():
            try:
                E.assess(snap, w.trust, 25, E.profile(), limits=dict(exact, **{k: v - 1}))
                below[k] = "assessed"
            except L.LimitExceeded as e:
                below[k] = e.limit
        return C.canon(base) == C.canon(tight), below
    got = guarded(run)
    check("R33", got == (True, {k: k for k in exact}), "at its own counts a view is assessed exactly as by default", got)

    # R34 (§9): the default of each admission limit is the table's
    check("R34", L.DEFAULTS == {"snapshot_records": 100_000, "snapshot_blobs": 100_000, "snapshot_bytes": 1 << 30,
                                "requires_edges": 1_000_000, "duty_periods": 10_000, "report_periods": 100_000},
          "the admission limits default to SPEC §9's table", L.DEFAULTS)

    # R35 (§9, §3): each file is bounded by 64 MiB: a blob file one byte over it, named
    # by its own hash, is kept out of the snapshot; that bound is not a bound on the
    # store: two 40 MiB blobs (80 MiB together) are read whole
    w = World()
    root = w.store.root
    over = b"\0" * (MAX_FILE + 1)
    h_over = C.digest(over)
    (root / "blobs" / h_over).write_bytes(over)
    del over
    snap = Snapshot.read(root)
    first = (h_over in snap.blobs, [m for m in snap.misfiled if m.startswith(f"blobs/{h_over}")])
    (root / "blobs" / h_over).unlink()
    hs = []
    for k in range(2):
        data = bytes([k + 1]) * (40 * 1024 * 1024)
        hs.append(w.store.put_blob(data))
    del data
    second = sorted(h for h in Snapshot.read(root).blobs if h in hs) == sorted(hs)
    shutil.rmtree(w.dir, ignore_errors=True)
    check("R35", first == (False, [f"blobs/{h_over}: larger than admitted"]) and second,
          "a file over 64 MiB is kept out; a store over 64 MiB is read", (first, second))


def _filed_id(w, rtype, actor, at, body):
    """The id a record would get, without filing it (an id is the digest of the record)."""
    return R.record_id(R.record(rtype, actor, at, body, prev=w.next_prev(actor)))


def _grant_ordered(w, actor, at, body_of, want):
    """File the first grant body_of(k) whose id satisfies `want`; ids are digests, so the
    order of two records at the same `at` is chosen by varying a field (here: expires)."""
    for k in range(1000):
        if want(_filed_id(w, "grant", actor, at, body_of(k))):
            return w.file("grant", actor, body_of(k), at=at)
    raise AssertionError("no grant id in the wanted order")


def gemini_review_cases():
    # R36 (§3.6, §4.4; Gemini deep review 2026-10-22, defect A): a challenge targets one
    # closure, the item it names. At b1a6d10 a challenge of item 0 made the duty closed by
    # item 1 CHALLENGED too, and a challenge with item null (the transition's results)
    # made every duty the transition closed CHALLENGED.
    w = World()
    d0, d1 = w.duty(statement="zero"), w.duty(statement="one")
    e0, e1 = w.evidence("e0"), w.evidence("e1")
    t = w.act(HOLDER, [R.item(d0, "discharge", [e0]), R.item(d1, "discharge", [e1])], established=["both done"])
    w.accept(OWNER, t, 0)
    w.accept(OWNER, t, 1)
    w.accept(OWNER, t, None)
    on_item = w.file("challenge", OWNER, R.challenge(t, "item 0 is wrong", [], 0))
    prof = E.profile(results_by=[OWNER])
    rep = w.assess(prof=prof)
    item_scoped = guarded(lambda: (E.reliance(rep, d0, "act")["state"], E.reliance(rep, d1, "act")["state"],
                                   E.capsule(rep, d0)["challenges"], E.capsule(rep, d1)["challenges"],
                                   E.reliance(rep, t, "act")["state"]))
    w2 = World()
    f0, f1 = w2.duty(statement="zero"), w2.duty(statement="one")
    g0, g1 = w2.evidence("e0"), w2.evidence("e1")
    t2 = w2.act(HOLDER, [R.item(f0, "discharge", [g0]), R.item(f1, "discharge", [g1])], established=["both done"])
    w2.accept(OWNER, t2, 0)
    w2.accept(OWNER, t2, 1)
    w2.accept(OWNER, t2, None)
    on_results = w2.file("challenge", OWNER, R.challenge(t2, "the established statement is wrong", [], None))
    rep2 = w2.assess(prof=prof)
    results_scoped = guarded(lambda: (E.reliance(rep2, f0, "act")["state"], E.reliance(rep2, f1, "act")["state"],
                                      E.capsule(rep2, f0)["challenges"], E.reliance(rep2, t2, "act")["state"],
                                      E.capsule(rep2, t2)["challenges"]))
    got = (item_scoped, results_scoped)
    check("R36", got == (("CHALLENGED", "ELIGIBLE", [on_item], [], "ELIGIBLE"),
                         ("ELIGIBLE", "ELIGIBLE", [], "CHALLENGED", [on_results])),
          "a challenge counts against the closure of the item it names; item null, against the results only", got)

    # R37 (§4.1, §8; defect B): a substitution waits for `to` AND for one of owed_to ∪
    # release_by. At b1a6d10 waiting_for named `to` only, its frontier item said
    # last_acceptance: true while the creditor's acceptance was still missing, and no
    # creditor saw the acceptance it could give.
    w = World()
    d = w.duty(owed_to=(OWNER,), release_by=(STRANGER,))
    s = w.close(d, act="substitute", to=CODEX)

    def accepts(rep, actor):
        return [(x["waiting_for"], x["last_acceptance"]) for x in E.frontier(rep, actor) if x.get("need") == "accept"]

    def state(rep):
        c = last(rep, d)
        return (c["verdict"], c.get("waiting_for"), c.get("awaiting"),
                {a: accepts(rep, a) for a in (CODEX, OWNER, STRANGER)}, E.capsule(rep, d)["waiting_for"])
    before = guarded(lambda: state(w.assess()))
    w.accept(CODEX, s)
    middle = guarded(lambda: state(w.assess()))
    w.accept(STRANGER, s)
    rep = w.assess()
    after = (last(rep, d)["verdict"], rep["duties"][d]["holder"], accepts(rep, OWNER))
    everyone = sorted([CODEX, OWNER, STRANGER])
    creditors = sorted([OWNER, STRANGER])
    got = (before, middle, after)
    want = (("PENDING", everyone, [[CODEX], creditors],
             {CODEX: [(everyone, False)], OWNER: [(everyone, False)], STRANGER: [(everyone, False)]}, everyone),
            ("PENDING", creditors, [creditors],
             {CODEX: [], OWNER: [(creditors, True)], STRANGER: [(creditors, True)]}, creditors),
            ("ADMITTED", CODEX, []))
    check("R37", got == want, "a substitution waits for `to` and for one creditor; each sees whether its accept is the last", got)

    # R38 (§3, §4.2, §8; defect B): whose acceptance is awaited is computed from the actor
    # sets, never parsed from text: an actor id may hold " (" (SPEC-3-21). And the twin of
    # the substitution: an attested `impossible` needs accept_by and ONE owed_to actor, so
    # an acceptor in both is the last one alone, and the other owed_to actor is not awaited
    # at all. At b1a6d10 "ci (nightly)" was awaited as "ci", and the impossible item waited
    # for every owed_to actor.
    paren = "ci (nightly)"
    w = World(actors=(HOLDER, OWNER, CODEX, STRANGER, paren))
    d = w.duty(owed_to=(OWNER,))
    w.close(d, act="substitute", to=paren)
    rep = w.assess()
    named = guarded(lambda: (last(rep, d).get("waiting_for"), accepts(rep, paren), accepts(rep, "ci")))
    w = World()
    d = w.duty(owed_to=(OWNER, CODEX), accept_by=(OWNER,))
    w.close(d, act="impossible")
    rep = w.assess()
    one_of = guarded(lambda: (last(rep, d).get("waiting_for"), last(rep, d).get("awaiting"),
                              accepts(rep, OWNER), accepts(rep, CODEX)))
    got = (named, one_of)
    check("R38", got == ((sorted([paren, OWNER]), [(sorted([paren, OWNER]), False)], []),
                         ([OWNER], [[OWNER]], [([OWNER], True)], [])),
          "awaited actors come from the actor sets: an id with ' (' and a one-of owed_to", got)

    # R39 (§4, §4.5; defect C): a grant is valid at a POSITION, (at, id): a grant filed at
    # the same `at` as a release, with a larger id, is after it and does not authorize it;
    # with a smaller id it does. A child grant at its parent's `at` with a smaller id is
    # before its parent. At b1a6d10 only `at` was compared: both releases were admitted.
    # Since F43 a record chained to a predecessor with the same `at` follows it (SPEC-4-7), so
    # each pair is filed in a world of its own: no actor files two records at that `at`.
    def tie(statement, want):
        w = World()
        d = w.duty(statement=statement)
        r = release(w, d, STRANGER, 300, statement)
        g = _grant_ordered(w, OWNER, 300, lambda k: R.grant(STRANGER, ["release"], [d], expires=20_000 + k),
                           lambda i: want(i, r))
        rep = w.assess(prof=E.profile(grant_roots=[g]))
        return verdict_of(rep, d, r)["verdict"], rep["duties"][d]["disposition"]

    def parent(statement, want):
        w = World()
        d = w.duty(statement=statement)
        root = w.file("grant", OWNER, R.grant(STRANGER, ["release"], [d], delegable=["release"]), at=400)
        child = _grant_ordered(w, STRANGER, 400, lambda k: R.grant(CODEX, ["release"], [d], expires=20_000 + k, parent=root),
                               lambda i: want(i, root))
        r = release(w, d, CODEX, 500, statement)
        rep = w.assess(prof=E.profile(grant_roots=[root]))
        return rep["grants"][child], verdict_of(rep, d, r)["verdict"]

    got = (tie("after", lambda i, r: i > r) + tie("before", lambda i, r: i < r),
           parent("child first", lambda i, root: i < root) + parent("parent first", lambda i, root: i > root))
    check("R39", got == (("OVERCLAIMED", "OPEN", "ADMITTED", "RELEASED"), ("BROKEN_CHAIN", "OVERCLAIMED", "VALID", "ADMITTED")),
          "a grant is valid from its position (at, id) on, not from its `at`", got)


def _verdict(rep, d, t):
    """The verdict of transition t on duty d, or ABSENT when t is not a candidate (a mutant may exclude it)."""
    return next((c["verdict"] for c in rep["duties"][d]["candidates"] if c["transition"] == t), "ABSENT")


def chain_cases():
    # R40 (§3, §4.1; F43, outside review "Monday", reproduced on 3f2be6a and d67bbf6): HOLDER
    # delegates at 100; CODEX discharges at 150 without having accepted (OVERCLAIMED), accepts at
    # 200, OWNER accepts the closure at 210. CODEX then files a second acceptance of the same
    # delegation dated 110. At d67bbf6 the earliest acceptance counted, the delegation took effect
    # at 110 and the duty was DISCHARGED: the delegate alone legalized its own earlier filing.
    w = World()
    d = w.duty(at=50)
    dl = w.close(d, act="delegate", to=CODEX, at=100)
    c = w.close(d, actor=CODEX, at=150)
    w.accept(CODEX, dl, at=200)
    w.accept(OWNER, c, at=210)
    before = w.assess()
    w.accept(CODEX, dl, at=110)
    after = w.assess()
    got = [(r["duties"][d]["disposition"], _verdict(r, d, c), _verdict(r, d, dl))
           for r in (before, after)]
    check("R40", got == [("OPEN", "OVERCLAIMED", "ADMITTED")] * 2,
          "a delegate's acceptance dated before its own earlier filing does not authorize that filing", got)

    # R41 (§4.1, F43 planned): CODEX discharges first and then files ONE acceptance dated 110,
    # between the delegation and its discharge. Whatever `prev` that acceptance names — CODEX's
    # head (the discharge: dated before it, unanchored), none (a second genesis: a fork) or no
    # prev at all (unchained) — the chain does not put it before the discharge, so it authorizes
    # nothing. CODEX's first record is an unrelated note, so its discharge is one record deeper in
    # its chain than a second genesis. Control: accepting first, then discharging, is admitted.
    def planned(prev):
        w = World()
        d = w.duty(at=50)
        dl = w.close(d, act="delegate", to=CODEX, at=100)
        w.act(CODEX, [], at=120, established=["a note"])
        c = w.close(d, actor=CODEX, at=150)
        w.accept(OWNER, c, at=210)
        w.accept(CODEX, dl, at=110, prev=prev)
        rep = w.assess()
        return rep["duties"][d]["disposition"], _verdict(rep, d, c), _verdict(rep, d, dl)

    w = World()
    d = w.duty(at=50)
    dl = w.close(d, act="delegate", to=CODEX, at=100)
    w.accept(CODEX, dl, at=120)
    c = w.close(d, actor=CODEX, at=150)
    w.accept(OWNER, c, at=210)
    rep = w.assess()
    control = rep["duties"][d]["disposition"], _verdict(rep, d, c)
    got = ([planned(p) for p in ("head", None, R.UNCHAINED)], control)
    check("R41", got == ([("OPEN", "OVERCLAIMED", "ADMITTED")] * 3, ("DISCHARGED", "ADMITTED")),
          "a delegate's acceptance authorizes its filing only from before it in the delegate's chain", got)

    # R42 (§4.1): a closure dated before the holder's own substitution. HOLDER substitutes to
    # OWNER at 300 (in effect at 301), then files a discharge dated 250: naming its head (the
    # substitution: dated before it, unanchored), naming the record before the substitution (a
    # fork) or no prev (unchained). The chain does not put it before the substitution, so the
    # substitution is in effect for it. Control: the discharge filed before the substitution in
    # HOLDER's chain is admitted.
    def backdated(prev):
        w = World()
        d = w.duty(at=50, accept_by=(CODEX,))
        s = w.close(d, act="substitute", to=OWNER, at=300)
        w.accept(OWNER, s, at=301)
        c = w.close(d, at=250, prev=d if prev == "fork" else prev)
        w.accept(CODEX, c, at=400)
        rep = w.assess()
        return rep["duties"][d]["disposition"], _verdict(rep, d, c), _verdict(rep, d, s)

    w = World()
    d = w.duty(at=50, accept_by=(CODEX,))
    c = w.close(d, at=250)
    s = w.close(d, act="substitute", to=OWNER, at=300)
    w.accept(OWNER, s, at=301)
    w.accept(CODEX, c, at=400)
    rep = w.assess()
    control = rep["duties"][d]["disposition"], _verdict(rep, d, c), rep["duties"][d]["holder"]
    got = ([backdated(p) for p in ("head", "fork", R.UNCHAINED)], control)
    check("R42", got == ([("OPEN", "OVERCLAIMED", "ADMITTED")] * 3, ("DISCHARGED", "ADMITTED", OWNER)),
          "a holder's filing the chain does not put before its own transfer is judged with the transfer in effect", got)

    # R43 (§3, §4): a fork is listed and excludes nothing. HOLDER substitutes to OWNER, OWNER
    # discharges and CODEX accepts; then HOLDER files a record naming the same prev as its
    # substitution. Excluding both branches would let HOLDER retract its own substitution and
    # turn OWNER's admitted discharge into OVERCLAIMED; here the substitution stands.
    w = World()
    d = w.duty(at=50, accept_by=(CODEX,))
    s = w.close(d, act="substitute", to=OWNER, at=300)
    w.accept(OWNER, s, at=301)
    c = w.close(d, actor=OWNER, at=350)
    w.accept(CODEX, c, at=360)
    x = w.act(HOLDER, [], at=400, prev=d, established=["I never handed it over"])
    rep = w.assess()
    got = (rep["chains"]["forks"], rep["duties"][d]["holder"], _verdict(rep, d, s),
           _verdict(rep, d, c), rep["duties"][d]["disposition"])
    check("R43", got == ([{"actor": HOLDER, "prev": d, "records": sorted([s, x])}], OWNER, "ADMITTED", "ADMITTED", "DISCHARGED"),
          "two records naming one prev are a listed fork; neither is excluded, so no transfer is retracted", got)

    # R44 (§4): an acceptance whose prev is not in the view is unanchored, listed, and its prev
    # is reported missing; it orders nothing, so the delegate's earlier discharge stays OVERCLAIMED.
    ghost = "e" * 64
    w = World()
    d = w.duty(at=50)
    dl = w.close(d, act="delegate", to=CODEX, at=100)
    c = w.close(d, actor=CODEX, at=150)
    w.accept(OWNER, c, at=210)
    a = w.accept(CODEX, dl, at=110, prev=ghost)
    rep = w.assess()
    got = (rep["chains"]["unanchored"].get(a), ghost in rep["missing"], _verdict(rep, d, c))
    check("R44", got == ("its prev is not in the view", True, "OVERCLAIMED"),
          "a record whose prev is not in the view is unanchored and its prev is missing", got)

    # R45 (§4): an acceptance naming another actor's record (the delegation itself, dated before
    # the discharge) as its prev is unanchored: a chain is one actor's.
    w = World()
    d = w.duty(at=50)
    dl = w.close(d, act="delegate", to=CODEX, at=100)
    c = w.close(d, actor=CODEX, at=150)
    w.accept(OWNER, c, at=210)
    a = w.accept(CODEX, dl, at=110, prev=dl)
    rep = w.assess()
    got = (rep["chains"]["unanchored"].get(a), _verdict(rep, d, c))
    check("R45", got == ("its prev was filed by another actor", "OVERCLAIMED"),
          "a record whose prev is another actor's is unanchored", got)

    # R46 (§4.1): replaying an old filing under a new prev. CODEX's discharge c was filed before it
    # accepted; it accepts late (220), then re-files c's body after that acceptance. Dated as c
    # (150) the copy is dated before its prev: unanchored, OVERCLAIMED. Dated now (230) it is a new
    # filing, authorized, and PENDING: OWNER accepted c, not the copy. c stays OVERCLAIMED.
    w = World()
    d = w.duty(at=50)
    dl = w.close(d, act="delegate", to=CODEX, at=100)
    ev = [w.evidence("work")]
    c = w.close(d, actor=CODEX, at=150, evidence=ev)
    w.accept(OWNER, c, at=210)
    a = w.accept(CODEX, dl, at=220)
    old = w.close(d, actor=CODEX, at=150, evidence=ev, prev=a)
    new = w.close(d, actor=CODEX, at=230, evidence=ev, prev=a)
    rep = w.assess()
    got = tuple(_verdict(rep, d, t) for t in (c, old, new)) + (rep["duties"][d]["disposition"],)
    check("R46", got == ("OVERCLAIMED", "OVERCLAIMED", "PENDING", "OPEN"),
          "an old filing replayed under a new prev is a new filing, from its own position, needing its own acceptance", got)

    # R48 (§4): records with the same `at` are ordered by id, except that a chained record follows
    # its predecessor. CODEX accepts the delegation and discharges in the same second, the discharge
    # with the smaller id. At d67bbf6 positions were (at, id): the discharge sorted before the
    # acceptance that put CODEX in effect, and was OVERCLAIMED.
    w = World()
    d = w.duty(at=50)
    dl = w.close(d, act="delegate", to=CODEX, at=100)
    a = w.accept(CODEX, dl, at=200)
    for k in range(1000):
        h = w.evidence(f"same second {k}")
        if _filed_id(w, "transition", CODEX, 200, R.transition("ATTESTED", [h], closes=[R.item(d, "discharge", [h])])) < a:
            break
    c = w.close(d, actor=CODEX, at=200, evidence=[h])
    w.accept(OWNER, c, at=210)
    rep = w.assess()
    got = (c < a, _verdict(rep, d, c), rep["duties"][d]["disposition"])
    check("R48", got == (True, "ADMITTED", "DISCHARGED"),
          "a chained record with the same `at` as its predecessor comes after it, whatever the ids", got)


def main():
    chain_cases()
    transfer_cases()
    admission_cases()
    disposition_cases()
    grant_cases()
    profile_cases()
    supersession_cases()
    trigger_cases()
    authority_cases()
    runtime_cases()
    capsule_cases()
    frontier_cases()
    refusal_cases()
    limit_cases()
    gemini_review_cases()
    return finish("ASSESSMENT")


if __name__ == "__main__":
    sys.exit(main())
