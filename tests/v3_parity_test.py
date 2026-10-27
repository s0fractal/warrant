#!/usr/bin/env python3
"""Differential parity of Warrant 3 against Warrant 2 on this repository's live store.

The v2 side is the existing tools (tools/claims.py's Model and challenge table, tools/roadmap.py,
tools/claimslib/reviews.py) over `.warrant/store`; the v3 side is warrant3's engine over the store
tools/migrate_v2_to_v3.py derives from it (in memory, with ephemeral keys: record ids do not depend
on keys). Each entity's v2 disposition is compared with its v3 verdict, read through the one
vocabulary map below. A difference passes only when it is named in DECLARED; anything else fails.

    python3 tests/v3_parity_test.py [--json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import claims as CL                          # noqa: E402
import migrate_v2_to_v3 as MG                # noqa: E402
import roadmap as RM                         # noqa: E402
from claimslib import reviews as RV          # noqa: E402
from warrant import engine as E2             # noqa: E402
from warrant import keys as K                # noqa: E402
from warrant3 import engine as E3            # noqa: E402
from warrant3.store import Snapshot          # noqa: E402

# The vocabulary map: a v3 verdict read as the v2 word for the same state.
CLAIM_STATUS = {"backed": "BACKED", "unbacked": "UNBACKED", "informative": "INFORMATIVE", "retired": "RETIRED"}
GOAL_STATE = {"open": "OPEN", "reformulated": "OPEN", "met": "MET", "withdrawn": "WITHDRAWN", None: "PROPOSED"}
GUARD = {"MET": "ADMITTED", "PENDING": "PENDING", "NONE": None}
FINDING = {"reproduces": "REPRODUCED", "does_not_reproduce": "NOT_REPRODUCED", None: "NOT_REPLAYED"}
REPLAY = {v: k for k, v in MG.REPLAY.items()}          # a v3 replay verdict read as the v2 observation result
# Differences that are not defects: (domain, v2 entity name) -> why. Empty: none is expected.
DECLARED = {}


BODY, BLOB, PROFILE = {}, {}, {}


def v3_side():
    """The v3 report of the migrated store, {v2 id: [v3 ids]} from the migration map, {version: lineage}."""
    # The repository's own profile: its schema quorum (.warrant/v3.json, claude and codex, 2 of 2) is met by the
    # bootstrap schemas claude files here and codex's acceptances committed in .warrant/v3/schema-accepts.jsonl.
    lines, blobs, trust, profile, summary = MG.migrate(ROOT, K.Key.generate(), K.Key.generate(), MG.accepts(ROOT))
    snap = Snapshot(lines, blobs)
    rep = E3.assess(snap, trust, profile)
    PROFILE.update(quorum=profile["quorum"], schemas=len(rep["schemas"]), pending=sorted(rep["schemas_pending"]),
                   accepted_by=sorted({a for i in summary["schemas"] for a in E3.View(snap, trust, profile).backers(i)}))
    assert PROFILE["schemas"] == len(summary["schemas"]) and not PROFILE["pending"], PROFILE
    BLOB.update(blobs)
    BODY.update({i: envs[0]["record"]["body"] for i, envs in snap.lines.items()})
    v2_to_v3 = {}
    for row in snap.json_blob(next(h for h in blobs if b'"warrant3/map@1"' in blobs[h]))["map"]:
        for x in row[1]:
            v2_to_v3.setdefault(x, []).append(row[0])
    root = {v: L for L, lin in rep["lineages"].items() for v in lin["versions"]}
    return rep, v2_to_v3, root, summary


def one(v2_to_v3, x):
    ids = v2_to_v3.get(x, [])
    assert len(ids) == 1, f"{x[:12]} maps to {len(ids)} v3 records"
    return ids[0]


def claims(rep, v2_to_v3, root):
    repo = CL.Repo(ROOT)
    m = CL.Model(repo.snapshot(), repo.trust())
    low = CL.lowered(CL.challenge_table(repo, m))
    d2 = E2.assess(m.snap, repo.trust(), max(r["at"] for r in m.recs.values()), E2.profile())["duties"]
    acc = CL.accept_index(m.recs)
    out = []
    for cid, n in sorted(m.current.items(), key=lambda kv: CL.id_key(kv[0])):
        duty = d2.get(n.doc["duty"]) if n.doc["duty"] else None
        v2 = {"status": CL.status_of(n, low), "duty": duty and duty["disposition"],
              "accepted_by": CL.acceptors(m.recs, acc, n.tid, 0) if n.rec["body"]["closes"] else [],
              "fork": any(c == "FORK" and cid in w for c, w in m.problems)}
        leaf_v = one(v2_to_v3, n.tid)
        lin = rep["lineages"][root[leaf_v]]
        ver = rep["versions"][leaf_v]
        state = BODY[leaf_v]["state"]
        countered = any(rep["challenges"][c]["why"] == "reproduced by a replayer" for c in ver["challenged_by"])
        v3 = {"status": "COUNTERED" if countered else CLAIM_STATUS[state],
              "duty": None if state == "informative" else "DISCHARGED" if ver["guard"] == "MET" and state == "backed" else "OPEN",
              "accepted_by": ver["accepted_by"], "fork": lin["verdict"] == "FORK" or lin["leaf"] != leaf_v}
        out.append(("claim", cid, v2, v3))
    return out


def roadmap(rep, v2_to_v3, root):
    m = RM.Roadmap(ROOT).model()
    out = []
    for key in sorted(m.goals, key=RM.key_n):
        lins = [lin for L, lin in rep["lineages"].items() if lin["schema"] == "goal@1" and BODY[L]["key"] == key]
        v3 = {"state": "FORK" if lins[0]["verdict"] == "FORK" else GOAL_STATE[lins[0]["state"]]} if len(lins) == 1 else \
            {"state": f"{len(lins)} lineages"}
        out.append(("goal", key, {"state": m.goal_state(key)}, v3))
    for did in sorted(m.obligations):
        L = one(v2_to_v3, did)
        lin = rep["lineages"][L]
        eff = lin["effective"]
        goal_root = BODY[L]["answers"]
        v2 = {"state": m.rep["duties"][did]["disposition"], "goal": m.goal_of(did), "accepted_by": m.accepted_by(did)}
        v3 = {"state": "FORK" if lin["verdict"] == "FORK" else "DISCHARGED" if lin["state"] == "done" else "OPEN",
              "goal": BODY[goal_root]["key"], "accepted_by": rep["versions"][eff]["accepted_by"] if lin["state"] == "done" else []}
        out.append(("obligation", did[:12], v2, v3))
    return out


def reviews(rep, v2_to_v3, root):
    m = RV.Reviews(ROOT).model()
    out = []
    for pr, rv in sorted(m.reviews.items()):
        L = one(v2_to_v3, rv.did)
        lin = rep["lineages"][L]
        heads = lin["path"][1:]
        img = {f.cid: one(v2_to_v3, f.cid) for f in rv.findings}
        v2 = {"state": m.rep["duties"][rv.did]["disposition"], "heads": [h.verdict for h in rv.heads],
              "accepted_by": [h.accepted_by for h in rv.heads],
              "findings": sorted((f.cid[:12], RV.finding_class(f), f.answered_by.n if f.answered_by else None,
                                  [f.at(h.commit) for h in rv.heads if h.n >= f.head.n]) for f in rv.findings),
              "merge": RV.merge_state(rv.merges[0][2]) if rv.merges else None}

        def cls(f):
            c = rep["challenges"][img[f.cid]]
            if BODY[img[f.cid]]["test"] is None:
                return "THESIS"
            at = [v for on, v, _ in c["replays"] if on == c["target"]]
            return FINDING.get(at[-1] if at else None, "UNEVALUABLE")

        def answered(f):
            n = [i + 1 for i, h in enumerate(heads) if img[f.cid] in (BODY[h].get("answers") or [])]
            return n[0] if n else None
        def series(f):
            c = rep["challenges"][img[f.cid]]
            start = heads.index(c["target"])
            return [next((REPLAY[v] for on, v, _ in c["replays"] if on == h), None) for h in heads[start:]]
        merges = [x for x in rep["graph"]["edges"] if x[1] == "attest" and x[2] == L and BODY[x[0]].get("verdict") == "merged"]
        v3 = {"state": "FORK" if lin["verdict"] == "FORK" else "DISCHARGED" if lin["state"] == "head" else "OPEN",
              "heads": [GUARD[rep["versions"][h]["guard"]] for h in heads],
              "accepted_by": [rep["versions"][h]["accepted_by"] for h in heads],
              "findings": sorted((f.cid[:12], cls(f), answered(f), series(f)) for f in rv.findings),
              "merge": RV.merge_state(json.loads(BLOB[BODY[merges[0][0]]["report"]])) if merges else None}
        out.append(("review", f"#{pr}", v2, v3))
    return out


def main():
    rep, v2_to_v3, root, summary = v3_side()
    rows = claims(rep, v2_to_v3, root) + roadmap(rep, v2_to_v3, root) + reviews(rep, v2_to_v3, root)
    table, bad = {}, []
    for dom, name, v2, v3 in rows:
        t = table.setdefault(dom, {"entities": 0, "equal": 0, "declared": 0, "undeclared": 0})
        t["entities"] += 1
        if v2 == v3:
            t["equal"] += 1
        elif (dom, name) in DECLARED:
            t["declared"] += 1
        else:
            t["undeclared"] += 1
            bad.append({"domain": dom, "entity": name, "v2": v2, "v3": v3})
    result = {"table": table, "undeclared": bad, "declared_migrations": summary["declared"],
              "v3": {"snapshot": rep["snapshot"], "rejected": len(rep["rejected"]), "problems": len(rep["problems"]),
                     "basis": rep["basis"]}, "v2_root": summary["v2"]["root"], "repository_profile": PROFILE}
    if "--json" in sys.argv:
        print(json.dumps(result, indent=1, sort_keys=True))
    else:
        print("domain       entities  equal  declared  undeclared")
        for dom, t in table.items():
            print(f"{dom:12} {t['entities']:8} {t['equal']:6} {t['declared']:9} {t['undeclared']:11}")
        for b in bad[:20]:
            print("DIFF", json.dumps(b, sort_keys=True)[:400])
        print("declared migrations applied:", len(summary["declared"]))
        print(f"repository profile (schema quorum {PROFILE['quorum']['schema/author']}): {PROFILE['schemas']} schemas "
              f"count, accepted by {', '.join(PROFILE['accepted_by'])}; {len(PROFILE['pending'])} pending")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
