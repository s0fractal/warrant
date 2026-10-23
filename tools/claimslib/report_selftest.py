"""`audit` and `why` burned on clones of the selftest fixture (this repository's code, mutants,
claims and roadmap): planted matrices, a real matrix of two mutants, and a counter that
replays for real."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from warrant import records as R
from warrant.store import Store

from .base import AUTHOR, COUNTER, GIT_NO_GC, id_key, Refused
from .repo import Repo
from .model import Model
from .counters import _replay_counter, STATEMENT_REFUSAL
from .author import Author
from .audit import _harness, _mutant_patch, audit, audit_doc, confined, load_matrices, MATRIX
from .why import _mid_key, CLAIMED, NO_CLAIM, NOT_A_STATEMENT, UNCOVERED_ROOTS, Why


def _found(blind, cid, mid):
    return [b for b in blind if b["claim"] == cid and b["mutant"] == mid]


def _clone(fix, d):
    subprocess.run(["git", *GIT_NO_GC, "clone", "-q", "--no-local", str(fix), str(d)], capture_output=True, check=True)
    return Repo(d)


def _audit_pick(r, defs):
    """(claim c, mutant x overlapping c's scopes, mutant y disjoint from them) of the fixture, or None."""
    model = Model(r.snapshot(), r.trust())
    for n in sorted((n for n in model.current.values() if n.backed and not n.retired), key=lambda n: id_key(n.id)):
        mine = {sc for mid in n.doc["mutants"] for sc in r.mutant_scopes(mid)}
        xs = [mid for mid in sorted(defs) if mid not in n.doc["mutants"] and r.mutant_scopes(mid) & mine]
        ys = [mid for mid in sorted(defs) if r.mutant_scopes(mid) and not r.mutant_scopes(mid) & mine]
        if mine and xs and ys:
            return n, xs[0], ys[0]
    return None


def _audit_synthetic(fix, work):
    """(1) Matrices built here over the fixture's own mutants: a planted blind claim and each guard."""
    r = _clone(fix, work / "audit-synthetic")
    r.mutants()
    core = _harness(r, "mutants.py")
    # The core harness's mutants only: the planted matrix is one of tests/mutants.py, and a matrix
    # holds only its own harness's ids (check_matrices: MATRIX_UNKNOWN_ID, AMEND 1 of #178).
    defs = {m[0]: m for m in core.MUTANTS}
    pick = _audit_pick(r, defs)
    if pick is None:
        return [("audit: the fixture has a claim with an overlapping and a disjoint mutant", False, "none found")]
    c, x, y = pick
    src = core.source_digest(r.root)
    first = c.doc["witnesses"][0]

    def matrix(result=lambda w: "PASS", drop=(), source=src, definition=None, killer=True, lie=False):
        runs = {}
        for w in c.doc["witnesses"]:
            test, _, case = w.partition(":")
            if test not in drop:
                runs.setdefault(test, {})[case] = result(w)
        rows = {}
        for mid in (x, y):
            row_runs = json.loads(json.dumps(runs))
            row_runs.setdefault("zz_test", {})["ZZ_KILLER"] = "FAIL" if killer else "PASS"
            rows[mid] = {"definition": definition or core.mutant_digest(defs[mid]), "file": defs[mid][1], "what": defs[mid][2],
                         "test": defs[mid][4], "targets": list(defs[mid][5]), "runs": row_runs,
                         # the outcome the row's own runs give, as run_all writes it (check_matrices recomputes it)
                         "outcome": core.verdict(row_runs, defs[mid][4], defs[mid][5])[0]}
            if lie:
                rows[mid]["outcome"] = "SURVIVED" if rows[mid]["outcome"] == "KILLED" else "KILLED"
        p = work / f"matrix-{len(list(work.glob('matrix-*.json')))}.json"
        p.write_text(json.dumps({"matrix": MATRIX, "harness": "mutants", "tests": "selftest", "source": source, "mutants": rows}))
        return [str(p)]

    def run(**kv):
        rows, probs = load_matrices(r, matrix(**kv))
        return (*audit(r, rows), rows, probs)

    return _synthetic_found(c, x, y, run) + _synthetic_guards(r, c, x, first, run, matrix)


def _synthetic_found(c, x, y, run):
    """A planted blind claim is reported with its counter; a disjoint mutant is not."""
    out = []
    blind, _, _, probs = run()
    hit = _found(blind, c.id, x)
    out.append(("audit: a claim whose witnesses all pass under an overlapping mutant some case kills is reported",
                bool(hit) and not probs and hit[0]["counter"]["passes"] == sorted(c.doc["witnesses"])
                and hit[0]["counter"]["claim"] == c.id and hit[0]["counter"]["against"] == c.tid
                and hit[0]["counter"]["fails"] == ["zz_test:ZZ_KILLER"], (c.id, x, probs, blind[:2])))
    out.append(("audit: a mutant whose scopes are disjoint from the claim's mutants' is not reported against it",
                not _found(blind, c.id, y), _found(blind, c.id, y)))
    return out


def _synthetic_guards(r, c, x, first, run, matrix):
    """Each guard of audit and load_matrices, one planted matrix at a time."""
    def unknown_only(blind, unknown):
        return not _found(blind, c.id, x) and any(u["claim"] == c.id and u["mutant"] == x for u in unknown)

    out = []
    blind, unknown, _, _ = run(result=lambda w: "FAIL" if w == first else "PASS")
    out.append(("audit: a claim one of whose witnesses fails under the mutant is not reported",
                not _found(blind, c.id, x) and not [u for u in unknown if u["claim"] == c.id and u["mutant"] == x],
                _found(blind, c.id, x)))
    blind, unknown, _, _ = run(drop={first.partition(":")[0]})
    out.append(("audit: a witness whose test file did not run under the mutant is unknown, not blind",
                unknown_only(blind, unknown), (_found(blind, c.id, x), unknown[:1])))
    rows, _ = load_matrices(r, matrix())
    for row in rows.values():
        row["runs"][first.partition(":")[0]].pop(first.partition(":")[2])
    blind, unknown = audit(r, rows)
    out.append(("audit: a witness case absent from its file's results under the mutant is unknown, not blind",
                unknown_only(blind, unknown), (_found(blind, c.id, x), unknown[:1])))
    blind, unknown, _, _ = run(killer=False)
    out.append(("audit: a mutant under which no case fails is not reported (its counter would fail nothing)",
                not _found(blind, c.id, x) and not unknown, (_found(blind, c.id, x), unknown[:1])))
    _, _, _, probs = run(source="0" * 64)
    out.append(("audit: a matrix of another source is refused MATRIX_STALE", [p[0] for p in probs] == ["MATRIX_STALE"], probs))
    _, _, rows, probs = run(definition="0" * 64)
    out.append(("audit: a row of a mutant defined otherwise now is refused MATRIX_STALE",
                not rows and {p[0] for p in probs} == {"MATRIX_STALE"}, probs))
    _, _, rows, probs = run(lie=True)
    out.append(("audit: a row labelled with an outcome its own runs do not give is refused MATRIX_OUTCOME "
                "(the validation --merge uses, AMEND 1 of #178)", not rows and {p[0] for p in probs} == {"MATRIX_OUTCOME"}, probs))
    escaped = []
    for arg in ("/etc/hosts", "../hosts", "sub/../../hosts", ".."):
        try:
            escaped.append((arg, str(confined(arg))))
        except Refused:
            pass
    inside = confined(os.path.join(tempfile.gettempdir(), "m.json"))
    out.append(("audit: a --matrix or --counters path outside the temporary directory is refused; one in it is kept",
                not escaped and inside == Path(os.path.realpath(tempfile.gettempdir())) / "m.json", (escaped, inside)))
    return out


def _audit_e2e(fix, work, key):
    """(2) End to end, a real matrix of M278 and M116: the pre-review SPEC-3.3-8 (X1 A6; M05 M06
    M241) is blind to M278, Gemini's counter, which changes the statement M05 changes: reported,
    and its would-be counter replays; citing A7 clears it. The pre-review SPEC-4.1-5 (U1 U4 U5; M09
    M10 M11) is blind to M116 too, but M116 changes another statement than any of its mutants:
    reported, and not confined."""
    s338, s415 = "SPEC-3.3-8", "SPEC-4.1-5"
    r = _clone(fix, work / "audit-e2e")
    m = Model(r.snapshot(), r.trust())
    n, n5 = m.current.get(s338), m.current.get(s415)
    if n is None or n5 is None or not {"M278", "M116"} <= set(r.mutants()):
        return [("audit e2e: SPEC-3.3-8, SPEC-4.1-5, M278 and M116 exist in the fixture", False, "missing")]
    au = Author(r, key, AUTHOR, validate=False)
    au.claim(n.id, n.doc["text"], ["contract_test:X1", "records_test:A6"], ["M05", "M06", "M241"],
             because="selftest: the claim as it stood before the Gemini review", previous=n)
    au.claim(n5.id, n5.doc["text"], ["contract_test:U1", "contract_test:U4", "contract_test:U5"], ["M09", "M10", "M11"],
             because="selftest: the claim as it stood before the Gemini review", previous=n5)
    mx = work / "matrix-e2e.json"
    run = subprocess.run([sys.executable, str(r.tests / "mutants.py"), "--jobs", "2", "--matrix", str(mx),
                          "--matrix-tests", "assessment_test,contract_test,records_test", "M116", "M278"], cwd=r.root,
                         env=dict(os.environ, WARRANT_IMPL=""), capture_output=True, text=True, timeout=900)
    rows, probs = load_matrices(r, [str(mx)])
    blind, _ = audit(r, rows)
    hit, hit5 = _found(blind, s338, "M278"), _found(blind, s415, "M116")
    now = Model(r.snapshot(), r.trust()).current
    why = _replay_counter(r, hit[0]["counter"], now[s338]) if hit else "not reported"
    why5 = _replay_counter(r, hit5[0]["counter"], now[s415]) if hit5 else None
    out = [("audit e2e: the pre-review SPEC-3.3-8 is reported blind to M278, and its would-be counter replays",
            run.returncode == 0 and not probs and bool(hit) and hit[0]["confined"] and why is None
            and "records_test:A7" in hit[0]["fails"], (run.stdout[-300:], probs, why)),
           ("audit e2e: the pre-review SPEC-4.1-5 is blind to M116, not confined, and its counter is refused per statement",
            bool(hit5) and not hit5[0]["confined"] and bool(why5) and STATEMENT_REFUSAL in why5, (hit5[:1], why5))]
    pairs = [(x["claim"], x["mutant"], x["confined"]) for x in audit_doc("tree:x", blind, [], {})["blind"]]
    out.append(("audit e2e: --json names each candidate as a (claim, mutant) pair with its confinement",
                (s338, "M278", True) in pairs and (s415, "M116", False) in pairs, pairs[:4]))
    au.claim(n.id, n.doc["text"], ["contract_test:X1", "records_test:A6", "records_test:A7"], ["M05", "M06", "M241"],
             because="selftest: A7 cited, M278 still not", previous=now[s338])
    blind, _ = audit(r, rows)
    out.append(("audit e2e: cited with A7, which M278 fails, SPEC-3.3-8 is not reported", not _found(blind, s338, "M278"),
                _found(blind, s338, "M278")))
    return out


def why_selftest(fix, work, key):
    """[(name, ok, detail)]: `why` burned on a clone of the selftest fixture `fix` (this
    repository's code, mutants, claims and roadmap), then with a real counter (M234's patch,
    replayed) lowering SPEC-3.2-20 to COUNTERED (AMEND 1 of #171)."""
    r = _clone(fix, work / "why")
    w = Why(r)
    paths = [p for p in w.files if p.split("/")[0] in UNCOVERED_ROOTS]
    out = []
    pick = next(((n, mid, path, i, ln) for mid, ns in sorted(w.cited.items(), key=lambda kv: _mid_key(kv[0]))
                 for n in ns for d in sorted(w.lineage.get(n.id, ())) if d in w.links
                 for (path, i) in sorted(k for k, ms in w.changes.items() if mid in ms)
                 for ln in w.links[d] if ln["goal"]), None)
    if pick is None:
        return [("why: the fixture has a claim a duty of whose lineage an obligation names, and whose mutant changes a statement",
                 False, "none found")]
    n, mid, path, i, ln = pick
    d = w.at(path, min(w.units(path)[i][2]))
    out.append(("why: a statement a cited mutant changes maps to its claim, the obligation naming the claim's duty, "
                "and that obligation's goal",
                d["status"] == CLAIMED and i in [s["index"] for s in d["statements"]]
                and n.id in [c["claim"] for c in d["claims"]] and ln["obligation"] in [o["obligation"] for o in d["obligations"]]
                and ln["goal"] in [g["goal"] for g in d["goals"]], (n.id, mid, path, i, d["status"], d["claims"][:2])))
    lost = [(p, i) for p in paths for i, (_, _, own) in enumerate(w.units(p))
            if i not in [s["index"] for s in w.at(p, min(own))["statements"]]]
    out.append(("why: every statement of warrant/ and warrant_agent/ is found again from its first line", not lost, lost[:3]))
    u = w.uncovered(paths)
    listed = {(s["file"], s["index"]) for s in u["uncovered"]}
    wrong = [s for s in u["uncovered"][:200] if w.at(s["file"], s["line"])["status"] != NO_CLAIM]
    out.append(("why: --uncovered lists exactly the statements no cited mutant changes, each answered NO_CLAIM",
                u["statements"] - u["covered"] == len(listed) and (path, i) not in listed and not wrong and u["covered"] > 0,
                (u["statements"], u["covered"], len(listed), wrong[:2])))
    src = w.files["warrant/engine.py"].read_text().splitlines()
    comment = next(k + 1 for k, t in enumerate(src) if t.strip().startswith("#"))
    out.append(("why: a comment line of warrant/engine.py is not a statement",
                w.at("warrant/engine.py", comment)["status"] == NOT_A_STATEMENT, comment))
    codes = []
    for arg in ("SPEC.md", "../warrant/engine.py", "tests/mutants.py"):
        try:
            w.at(arg, 1)
            codes.append(None)
        except Refused as e:
            codes.append(e.code)
    out.append(("why: a file outside warrant/, warrant_agent/ and tools/ is refused WHY_FILE", codes == ["WHY_FILE"] * 3, codes))
    return out + _why_countered(fix, work, key, w, u, paths)


def _why_countered(fix, work, key, w, u, paths):
    """SPEC-3.2-20 lowered by a counter that replays for real: not backing anywhere `why` looks."""
    r = _clone(fix, work / "why-countered")
    r.mutants()
    p = Model(r.snapshot(), r.trust()).current.get("SPEC-3.2-20")
    if p is None or "M234" not in r.mutant_edits:
        return [("why countered: SPEC-3.2-20 and M234 exist in the fixture", False, "missing")]
    store = Store(r.store_dir)
    h = store.put_json({"counter": COUNTER, "claim": p.id, "against": p.tid, "patch": _mutant_patch(r, "M234"),
                        "passes": sorted(p.doc["witnesses"]), "fails": ["records_test:I5"],
                        "why": "selftest: M234 changes the statement M232 changes; the witnesses pass"})
    at = max(x["at"] for x in Model(r.snapshot(), r.trust()).recs.values()) + 1
    ch = store.put_record(R.record("challenge", AUTHOR, at, R.challenge(p.tid, "selftest: replaying counter", [h], 0)), key)
    w2 = Why(r)
    mine = sorted({(path, i) for mid in p.doc["mutants"] for (path, i), ms in w2.changes.items() if mid in ms})
    answers = {k: w2.at(k[0], min(w2.units(k[0])[k[1]][2])) for k in mine}
    named = all(p.id not in [c["claim"] for c in d["claims"]]
                and [(x["challenge"], x["counters"]) for c in d["countered"] if c["claim"] == p.id for x in c["challenges"]]
                == [(ch, [h])] for d in answers.values())
    only = [k for k in mine if {n.id for mid in w.changes.get(k, ()) for n in w.cited.get(mid, [])} == {p.id}]
    u2 = w2.uncovered(paths)
    listed = {(s["file"], s["index"]): s["countered"] for s in u2["uncovered"]}
    return [("why countered: SPEC-3.2-20 lowered by a replaying counter is named with that counter at each of its "
             "statements and is backing at none", bool(mine) and named and p.id in w2.low, (mine, ch[:12])),
            ("why countered: a statement SPEC-3.2-20 alone covered is uncovered now, listed with the COUNTERED claim",
             bool(only) and u2["covered"] == u["covered"] - len(only)
             and all(p.id in listed.get(k, []) for k in only), (only, u["covered"], u2["covered"]))]


def audit_selftest(fix, work, key):
    """[(name, ok, detail)]: `audit` burned on clones of the selftest fixture `fix`."""
    return _audit_synthetic(fix, work) + _audit_e2e(fix, work, key)
