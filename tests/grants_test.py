#!/usr/bin/env python3
"""WRT-022 S3: minimal grants (impl/grants.py) and the release they authorize
(impl/loops.py).

    python3 tests/grants_test.py

Actors from loops_test: Claude holds a duty owed to Codex; the owner is a third
party bound in the trust snapshot; mallory is not. Every grant is a signed record.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "impl"))
# GRANTS_IMPL lets tests/grants_mutants.py run this file against mutated copies.
if os.environ.get("GRANTS_IMPL"):
    sys.path.insert(0, os.environ["GRANTS_IMPL"])
    os.environ["LOOPS_IMPL"] = os.environ["GRANTS_IMPL"]
import loops_test as LT   # noqa: E402
import loops as L         # noqa: E402
import grants as GR       # noqa: E402

CLAUDE, CODEX, OWNER = LT.CLAUDE, LT.CODEX, LT.OWNER
results = {}


def check(gid, ok, what, detail=""):
    results[gid] = "PASS" if ok else "FAIL"
    print(("ok    " if ok else "FAIL  ") + f"{gid} {what}" + ("" if ok else f" | {detail}"))


def grant(c, grantor, grantee, acts, delegable, duties, expires=None, parent=None, ts=None, signer=None):
    g = {"schema": GR.GRANT, "grantor": grantor, "grantee": grantee, "acts": sorted(acts),
         "delegable": sorted(delegable), "duties": sorted(duties), "expires": expires, "parent": parent}
    return c.record("propose", c.blob(g), signer or grantor, ts=ts)


def release(c, d, actor, ts=None):
    return c.record("propose", c.blob(L.transition("ATTESTED", [], closes=[L.mapping(d, "RELEASED")])), actor,
                    prior=[d], ts=ts)


def profile(roots):
    return {"schema": L.PROFILE, "uses": {"read": {"requires_declared_triggers": False}}, "grant_roots": list(roots)}


def assess(c, roots=(), with_profile=True):
    return L.assess(c.S.root, c.trust, LT.T_END, profile=profile(roots) if with_profile else None)


def last(rep, d):
    x = rep["duties"][d]["candidates"][-1]
    return rep["duties"][d]["disposition"], x["verdict"], x["why"]


def main():
    # G01 a grant from a root the recipient accepts lets a third party release
    c = LT.Case()
    d = c.open()
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [d])
    release(c, d, OWNER)
    disp, v, why = last(assess(c, [root]), d)
    check("G01", disp == "RELEASED" and v == "ADMITTED" and "by grant" in why, "an accepted root authorizes", why)

    # G02 the same grant, its root not accepted by the recipient: UNGROUNDED
    disp, v, why = last(assess(c, []), d)
    check("G02", disp == "OPEN" and v == "OVERCLAIMED" and "UNGROUNDED" in why,
          "a root the recipient did not accept authorizes nothing", why)

    # G03 no recipient profile, no roots
    disp, v, why = last(assess(c, with_profile=False), d)
    check("G03", disp == "OPEN" and v == "OVERCLAIMED", "no profile, no grant", why)

    # G04 an attenuating child grant authorizes its grantee
    c = LT.Case()
    d = c.open()
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [d])
    grant(c, OWNER, CLAUDE, ["release"], [], [d], parent=root)
    release(c, d, CLAUDE)
    disp, v, why = last(assess(c, [root]), d)
    check("G04", disp == "RELEASED" and "by grant" in why, "an attenuated chain authorizes", why)

    # G05 a child grants what its parent did not make delegable
    c = LT.Case()
    d = c.open()
    root = grant(c, CODEX, OWNER, ["release"], [], [d])
    grant(c, OWNER, CLAUDE, ["release"], [], [d], parent=root)
    release(c, d, CLAUDE)
    disp, v, why = last(assess(c, [root]), d)
    check("G05", disp == "OPEN" and "NOT_ATTENUATED" in why and "delegable" in why,
          "holding an act is not holding the right to grant it", why)

    # G06 a child whose grantor is not the parent's grantee
    c = LT.Case()
    d = c.open()
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [d])
    grant(c, CLAUDE, CLAUDE, ["release"], [], [d], parent=root)
    release(c, d, CLAUDE)
    disp, v, why = last(assess(c, [root]), d)
    check("G06", disp == "OPEN" and "not the parent's grantee" in why, "only the grantee delegates", why)

    # G07 a child that widens the scope to another duty
    c = LT.Case()
    d, other = c.open(), c.open(statement="other")
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [d])
    grant(c, OWNER, CLAUDE, ["release"], [], [d, other], parent=root)
    release(c, other, CLAUDE)
    disp, v, why = last(assess(c, [root]), other)
    check("G07", disp == "OPEN" and "duties beyond the parent's" in why, "scope never widens", why)

    # G08 expiry is evaluated at the act's position
    c = LT.Case()
    d1, d2 = c.open(), c.open(statement="second")
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [d1, d2], expires=50, ts=10)
    release(c, d1, OWNER, ts=40)
    release(c, d2, OWNER, ts=60)
    rep = assess(c, [root])
    check("G08", last(rep, d1)[0] == "RELEASED" and last(rep, d2)[0] == "OPEN" and "EXPIRED" in last(rep, d2)[2],
          "before expiry it authorizes, after it does not", (last(rep, d1), last(rep, d2)))

    # G09 a child that outlives its parent
    c = LT.Case()
    d = c.open()
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [d], expires=500, ts=10)
    grant(c, OWNER, CLAUDE, ["release"], [], [d], parent=root, ts=20)                 # no expiry: outlives it
    release(c, d, CLAUDE, ts=30)
    disp, v, why = last(assess(c, [root]), d)
    check("G09", disp == "OPEN" and "expires later than the parent" in why, "a child never outlives its parent", why)

    # G10 a grant issued after the act does not authorize it
    c = LT.Case()
    d = c.open()
    release(c, d, OWNER, ts=60)
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [d], ts=70)
    disp, v, why = last(assess(c, [root]), d)
    check("G10", disp == "OPEN" and "NOT_YET" in why, "authority is not retroactive", why)

    # G11 a grant record signed by someone other than its grantor is refused
    c = LT.Case()
    d = c.open()
    forged = grant(c, CODEX, OWNER, ["release"], ["release"], [d], signer=OWNER)
    release(c, d, OWNER)
    rep = assess(c, [forged])
    check("G11", forged in rep["refused_events"] and last(rep, d)[0] == "OPEN",
          "nobody grants in another's name", rep["refused_events"].get(forged))

    # G12 being bound in the trust snapshot authorizes nothing
    c = LT.Case()
    d = c.open()
    release(c, d, OWNER)
    disp, v, why = last(assess(c, []), d)
    check("G12", disp == "OPEN" and "no grant gives" in why, "a key binding is not a grant", why)

    # G13 a grant for another duty does not authorize this one
    c = LT.Case()
    d, other = c.open(), c.open(statement="other")
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [other])
    release(c, d, OWNER)
    disp, v, why = last(assess(c, [root]), d)
    check("G13", disp == "OPEN" and "no grant gives" in why, "a grant is scoped to its duties", why)

    # G14 malformed grants refuse their record; the view survives
    c = LT.Case()
    d = c.open()
    base = {"schema": GR.GRANT, "grantor": CODEX, "grantee": OWNER, "acts": ["release"], "delegable": [],
            "duties": [d], "expires": None, "parent": None}
    bads = [dict(base, acts=[]), dict(base, acts=["release", "release"]), dict(base, acts=[["release"]]),
            dict(base, delegable=["contest"]), dict(base, expires="soon"), dict(base, duties=["zz"]),
            dict(base, grantee={}), dict(base, extra=1)]
    ids = [c.record("propose", c.blob(b), CODEX) for b in bads]
    good = c.open(statement="unrelated")
    try:
        rep = assess(c, ids)
        ok14 = all(i in rep["refused_events"] for i in ids) and rep["duties"][good]["disposition"] == "OPEN"
        det14 = rep["refused_events"]
    except (TypeError, KeyError) as e:
        ok14, det14 = False, f"assessment aborted: {type(e).__name__}"
    check("G14", ok14, "malformed grants are refused per record", det14)

    # G15 the parent must be valid at the CHILD's position, not merely at the act's:
    # a child cannot attenuate a grant that did not exist yet when it was issued
    c = LT.Case()
    d = c.open()
    g_root = {"schema": GR.GRANT, "grantor": CODEX, "grantee": OWNER, "acts": ["release"],
              "delegable": ["release"], "duties": [d], "expires": None, "parent": None}
    root_id = L.W.warrant_id({"warrant": "0.2", "decision": "propose", "subject": {"hash": c.blob(g_root), "note": "loops"},
                              "under": [c.policy], "because": [{"kind": "prose", "text": "dogfood"}], "evidence": [],
                              "actor": {"id": CODEX}, "prior": [], "ts": 10})
    grant(c, OWNER, CLAUDE, ["release"], [], [d], parent=root_id, ts=5)                # issued before its parent
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [d], ts=10)
    release(c, d, CLAUDE, ts=20)
    disp, v, why = last(assess(c, [root]), d)
    check("G15", root == root_id and disp == "OPEN" and "BROKEN_CHAIN" in why and "granted after" in why,
          "a child issued before its parent existed is not valid", (why, root == root_id))

    # G16 the report states every grant at as_of
    c = LT.Case()
    d = c.open()
    root = grant(c, CODEX, OWNER, ["release"], ["release"], [d])
    loose = grant(c, CODEX, OWNER, ["release"], [], [d])
    rep = assess(c, [root])
    check("G16", rep["grants"] == {root: "VALID", loose: "UNGROUNDED"},
          "grants are reported with their state", rep["grants"])

    # G17 (GR-01): the grant evaluator decides admission, so it is in the assessment's
    # identity. Fresh interpreters over ONE signed store: the same grants.py gives the
    # same id; a grants.py that drops the delegable rule (and so RELEASES) gives another.
    import shutil
    import subprocess
    import tempfile
    c = LT.Case()
    d = c.open()
    root = grant(c, CODEX, OWNER, ["release"], [], [d])
    grant(c, OWNER, CLAUDE, ["release"], [], [d], parent=root)
    release(c, d, CLAUDE)
    here = Path(GR.__file__).parent
    copies = []
    for k, edit in enumerate((False, False, True)):
        tmp = Path(tempfile.mkdtemp(prefix=f"grant-eval-{k}-"))
        src = (here / "grants.py").read_text()
        if edit:
            src = src.replace('    if not set(g["acts"]) <= set(p["delegable"]):', '    if False:')
        (tmp / "grants.py").write_text(src)
        shutil.copy(Path(L.__file__), tmp / "loops.py")
        copies.append(tmp)
    probe = ("import json, sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(1, sys.argv[2]); import loops as L; "
             "r = L.assess(sys.argv[3], sys.argv[4], 10**6, profile=json.loads(sys.argv[5])); "
             "print(json.dumps([r['view']['assessment_id'], r['duties'][sys.argv[6]]['disposition']]))")
    runs = []
    for tmp in copies:
        p = subprocess.run([sys.executable, "-c", probe, str(tmp), str(ROOT / "impl"), str(c.S.root), str(c.trust),
                            json.dumps(profile([root])), d], capture_output=True, text=True, check=False)
        runs.append(json.loads(p.stdout) if p.returncode == 0 else ["crash", p.stderr[-200:]])
    check("G17", runs[0] == runs[1] and runs[0][1] == "OPEN" and runs[2][1] == "RELEASED" and runs[2][0] != runs[0][0],
          "a different grant evaluator is a different assessment", runs)

    failed = sorted(k for k, v in results.items() if v == "FAIL")
    print(f"GRANTS: {sum(v == 'PASS' for v in results.values())} PASS / {len(failed)} FAIL"
          + (f" ({', '.join(failed)})" if failed else ""))
    if os.environ.get("GRANTS_RESULTS"):
        Path(os.environ["GRANTS_RESULTS"]).write_text(json.dumps(results))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
