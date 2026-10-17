#!/usr/bin/env python3
"""Each mutant of impl/loops.py undoes one rule of WRT-021 draft-2 and must make
ITS case of tests/loops_test.py fail. Breaking only some other case is
OFF_TARGET, a crash is CRASH, and neither counts as killed.

    python3 tests/loops_mutants.py

Rules with no mutant, and why:
  L09  a failed attempt closes nothing: there is no code that could close it;
       the rule is an absence, and L09 checks it.
  L24  settlement compatibility is a property of the encoding (unique accept
       subjects), not of a guard in loops.py; L24 runs the real verifier.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "impl" / "loops.py").read_text()

MUTANTS = [
    ("L01", "an unknown kind is accepted",
     [('    if d["kind"] not in KINDS or d["shape"] not in SHAPES:', '    if False:')]),
    ("L02", "anyone may open a duty for a holder",
     [('                if why is None and body["actor"]["id"] != doc["holder"]:', '                if False:')]),
    ("L03", "no acceptance is required",
     [('    if missing:\n        return "PENDING"', '    if False:\n        return "PENDING"')]),
    ("L04", "any basis discharges",
     [('    if [disp, t["did"]["basis"]] not in d["admits"]:', '    if False:')]),
    ("L05", "an acceptance is not bound to its transition",
     [('                if a["duty"] == duty_id and a["transition"] == t_id and a["mapping"] == index',
       '                if a["duty"] == duty_id and a["mapping"] == index')]),
    ("L06", "anyone's acceptance satisfies the duty",
     [('    missing = set(d["acceptance"]) - view.accepted_by(did, t_id, i, m["evidence"])',
       '    missing = set() if view.accepted_by(did, t_id, i, m["evidence"]) else set(d["acceptance"])')]),
    ("L07", "an acceptance is not bound to the evidence",
     [('                and sorted(a["evidence"]) == sorted(evidence)}', '                }')]),
    ("L08", "discharging every child discharges the parent",
     [('        _orphan_and_missing(view, report)',
       '        _orphan_and_missing(view, report)\n'
       '        for _p in report:\n'
       '            _kids = [k for k, dd in view.duties.items() if _p in dd["serves"]]\n'
       '            if _kids and all(report[k]["disposition"] == "DISCHARGED" for k in _kids):\n'
       '                report[_p]["disposition"] = "DISCHARGED"')]),
    ("L10", "anyone releases",
     [('        return ("ADMITTED", "") if actor in set(d["owed_to"]) | set(d["release_by"]) else \\',
       '        return ("ADMITTED", "") if True else \\')]),
    ("L11", "the holder abandons an obligation",
     [('        return "OVERCLAIMED", "an obligation cannot be abandoned by its holder"', '        return "ADMITTED", ""'),
      ('CLOSING = {"DISCHARGED", "DECLARED_IMPOSSIBLE", "RELEASED"}',
       'CLOSING = {"DISCHARGED", "DECLARED_IMPOSSIBLE", "RELEASED", "ABANDONED"}')]),
    ("L12", "anyone delegates",
     [('        return ("ADMITTED", "") if actor == state["holder"] else ("OVERCLAIMED", "only the holder delegates")',
       '        return ("ADMITTED", "") if True else ("OVERCLAIMED", "only the holder delegates")')]),
    ("L13", "holder and successor substitute without the creditor",
     [('        if view.accepted_by(did, t_id, i, m["evidence"]) & authority:', '        if True:')]),
    ("L13", "substitution keeps the old holder as a closer",
     [('                state["holder"], state["delegates"] = m["to"], set()',
       '                state["delegates"].add(m["to"])')]),
    ("L14", "incompatible closures are not contested",
     [('    if len(kinds) > 1:', '    if False:')]),
    ("L15", "a root duty is vacuously orphaned",
     [('        if not parents:\n            continue                    # a root duty is never orphaned (review R2)\n', '')]),
    ("L15", "a discharged parent orphans its children",
     [('ENDED = {"RELEASED", "ABANDONED", "DECLARED_IMPOSSIBLE"}',
       'ENDED = {"RELEASED", "ABANDONED", "DECLARED_IMPOSSIBLE", "DISCHARGED"}')]),
    ("L16", "an unknown reference is not reported",
     [('            r["flags"].append("MISSING")\n            continue', '            continue')]),
    ("L17", "a past instance without a closure is open, not lapsed",
     [('                report[str(n)] = "LAPSED" if end <= as_of else "OPEN"', '                report[str(n)] = "OPEN"')]),
    ("L17", "a recurring duty closes without an instance",
     [('    if d["shape"] == "recurring" and "instance" not in m:', '    if False:'),
      ('                instances.setdefault(m["instance"], (t_id, t["did"]["basis"]))',
       '                instances.setdefault(m.get("instance", 0), (t_id, t["did"]["basis"]))')]),
    ("L18", "no observation reads as holding",
     [('        if not fresh:\n            out["flags"].append("UNOBSERVED")', '        if not fresh:\n            pass')]),
    ("L18", "a stale observation counts as fresh",
     [('        fresh = [o for o in observations if as_of - o[0] <= d["freshness"]]', '        fresh = observations')]),
    ("L19", "records failing verification stay in the view",
     [('        valid = [w for w in ids if w not in bad] if store_ok else []', '        valid = ids')]),
    ("L21", "the view does not end at as_of",
     [('            if env["body"]["ts"] <= as_of:          # the view ends at as_of', '            if True:')]),
    ("L22", "a new revision is treated as current",
     [('        out["applicability"] = "CURRENT" if d["scope"]["subject"] in current else "UNASSESSED"',
       '        out["applicability"] = "CURRENT"')]),
    ("L23", "a taken question still counts as unowned",
     [('        unowned = sorted({q for _, t in view.transitions.values() for q in t["opened"]}\n'
       '                         - {d["answers"] for d in view.duties.values() if "answers" in d})',
       '        unowned = sorted({q for _, t in view.transitions.values() for q in t["opened"]})')]),
    ("L23", "every duty is in every actor's frontier",
     [('        if not involved:\n            continue\n', '')]),
    ("L28", "a past overclaim keeps a closed duty in the frontier",
     [('        live = open_like or bool(set(r["flags"]) - {"OVERCLAIMED_CANDIDATE"})',
       '        live = open_like or bool(r["flags"])')]),
    ("L25", "unimplemented kinds are assessed as obligations",
     [('    if d["kind"] not in IMPLEMENTED_KINDS:', '    if False:')]),
    ("L26", "a mapping may cite evidence the transition does not carry",
     [('        if not set(m["evidence"]) <= set(did["evidence"]):', '        if False:')]),
    ("L27", "misaddressed bytes are read",
     [('    if hashlib.sha256(raw).hexdigest() != h:\n        return None\n', '')]),
    ("L27", "non-canonical bytes are read",
     [('    return doc if isinstance(doc, dict) and canon(doc) == raw else None',
       '    return doc if isinstance(doc, dict) else None')]),
]


def run(target, pairs):
    src = SRC
    for old, new in pairs:
        if src.count(old) != 1:
            return "BAD_MUTANT", f"pattern occurs {src.count(old)} times: {old[:60]!r}"
        src = src.replace(old, new)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "loops.py").write_text(src)
        res = Path(tmp) / "results.json"
        env = dict(os.environ, LOOPS_IMPL=tmp, LOOPS_RESULTS=str(res))
        subprocess.run([sys.executable, str(ROOT / "tests" / "loops_test.py")], env=env,
                       capture_output=True, text=True, check=False)
        if not res.exists():
            return "CRASH", ""
        results = json.loads(res.read_text())
    failed = sorted(k for k, v in results.items() if v == "FAIL")
    if results.get(target) == "FAIL":
        return "KILLED", ",".join(failed)
    return ("OFF_TARGET" if failed else "SURVIVED"), ",".join(failed)


def main():
    verdicts = []
    for target, what, pairs in MUTANTS:
        v, detail = run(target, pairs)
        verdicts.append(v)
        print(f"{v:10} {target} {what}" + (f"  [{detail}]" if detail else ""))
    killed = verdicts.count("KILLED")
    print(f"LOOPS MUTANTS: {killed}/{len(MUTANTS)} killed on target")
    return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
