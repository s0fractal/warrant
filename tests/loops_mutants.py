#!/usr/bin/env python3
"""Each mutant of impl/loops.py undoes one rule of WRT-021 draft-2 and must make
ITS case of tests/loops_test.py fail. Breaking only some other case is
OFF_TARGET, a crash is CRASH, and neither counts as killed.

    python3 tests/loops_mutants.py

WL01/WL02 (Codex review of 0815959) and F2-F5 each have their own mutants
(L29-L36). Rules with no mutant, and why:
  L09  a failed attempt closes nothing: there is no code that could close it;
       the rule is an absence, and L09 checks it.
  L24  settlement compatibility is a property of the encoding (unique accept
       subjects), not of a guard in loops.py; L24 runs the real verifier.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mutant_runner import campaign  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {"loops.py": (ROOT / "impl" / "loops.py").read_text()}

MUTANTS = [
    ("L37", "loops.py", "JSON containers reach enum membership (WL03)",
     [('    return isinstance(value, str) and value in choices',
       '    return value in choices')]),
    ("L38", "loops.py", "a transition scope accepts an untyped subject (WL03)",
     [('    if "subject" in t["scope"] and not (isinstance(t["scope"]["subject"], str)',
       '    if False and not (isinstance(t["scope"]["subject"], str)')]),
    ("L01", "loops.py", "an unknown kind is accepted",
     [('    if not _enum(d["kind"], KINDS) or not _enum(d["shape"], SHAPES):', '    if False:')]),
    ("L02", "loops.py", "anyone may open a duty for a holder",
     [('            if why is None and body["actor"]["id"] != doc["holder"]:', '            if False:')]),
    ("L03", "loops.py", "no acceptance is required",
     [('    if missing:\n        return "PENDING"', '    if False:\n        return "PENDING"')]),
    ("L04", "loops.py", "any basis discharges",
     [('    if [disp, claimed] not in d["admits"]:', '    if False:')]),
    ("L05", "loops.py", "an acceptance is not bound to its transition",
     [('                if a["duty"] == duty_id and a["transition"] == t_id and a["mapping"] == index\n'
       '                and sorted',
       '                if a["duty"] == duty_id and a["mapping"] == index\n'
       '                and sorted')]),
    ("L06", "loops.py", "anyone's acceptance satisfies the duty",
     [('    missing = set(d["acceptance"]) - view.accepted_by(did, t_id, i, m["evidence"])',
       '    missing = set() if view.accepted_by(did, t_id, i, m["evidence"]) else set(d["acceptance"])')]),
    ("L07", "loops.py", "an acceptance is not bound to the evidence",
     [('                and sorted(a["evidence"]) == sorted(evidence)}', '                }')]),
    ("L08", "loops.py", "discharging every child discharges the parent",
     [('        _orphan_and_missing(view, report)',
       '        _orphan_and_missing(view, report)\n'
       '        for _p in report:\n'
       '            _kids = [k for k, dd in view.duties.items() if _p in dd["serves"]]\n'
       '            if _kids and all(report[k]["disposition"] == "DISCHARGED" for k in _kids):\n'
       '                report[_p]["disposition"] = "DISCHARGED"')]),
    ("L10", "loops.py", "anyone releases",
     [('        return ("ADMITTED", "") if actor in set(d["owed_to"]) | set(d["release_by"]) else \\',
       '        return ("ADMITTED", "") if True else \\')]),
    ("L11", "loops.py", "the holder abandons an obligation",
     [('        return "OVERCLAIMED", "an obligation cannot be abandoned by its holder"', '        return "ADMITTED", ""')]),
    ("L12", "loops.py", "anyone delegates",
     [('    if actor != state["holder"]:\n        return "OVERCLAIMED", "only the holder transfers or delegates"',
       '    if False:\n        return "OVERCLAIMED", "only the holder transfers or delegates"')]),
    ("L13", "loops.py", "holder and successor substitute without the creditor",
     [('    if m["disposition"] == "SUBSTITUTED" and not accepted & (set(d["owed_to"]) | set(d["release_by"])):',
       '    if False:')]),
    ("L13", "loops.py", "substitution keeps the old holder as a closer",
     [('        state["holder"], state["delegates"] = m["to"], set()',
       '        state["delegates"].add(m["to"])')]),
    ("L14", "loops.py", "incompatible closures are not contested",
     [('    if len(kinds) > 1:', '    if False:')]),
    ("L15", "loops.py", "a root duty is vacuously orphaned",
     [('        if not parents:\n            continue                    # a root duty is never orphaned (review R2)\n', '')]),
    ("L15", "loops.py", "a discharged parent orphans its children",
     [('ENDED = {"RELEASED", "ABANDONED", "DECLARED_IMPOSSIBLE"}',
       'ENDED = {"RELEASED", "ABANDONED", "DECLARED_IMPOSSIBLE", "DISCHARGED"}')]),
    ("L16", "loops.py", "an unknown reference is not reported",
     [('            r["flags"].append("MISSING")\n            continue', '            continue')]),
    ("L17", "loops.py", "a past instance without a closure is open, not lapsed",
     [('            report[str(n)] = "LAPSED" if end <= as_of else "OPEN"', '            report[str(n)] = "OPEN"')]),
    ("L17", "loops.py", "a recurring duty closes without an instance",
     [('    if d["shape"] == "recurring" and "instance" not in m:', '    if False:'),
      ('        acc["instances"].setdefault(m["instance"], t_id)',
       '        acc["instances"].setdefault(m.get("instance", 0), t_id)')]),
    ("L18", "loops.py", "no observation reads as holding",
     [('    if not fresh:\n        out["flags"].append("UNOBSERVED")', '    if not fresh:\n        pass')]),
    ("L18", "loops.py", "a stale observation counts as fresh",
     [('    fresh = [o for o in observations if as_of - o[0] <= d["freshness"]]', '    fresh = observations')]),
    ("L19", "loops.py", "records failing verification stay in the view",
     [('        valid = [w for w in ids if w not in bad] if store_ok else []', '        valid = ids')]),
    ("L21", "loops.py", "the view does not end at as_of",
     [('            if env["body"]["ts"] <= as_of:          # the view ends at as_of', '            if True:')]),
    ("L22", "loops.py", "a new revision is treated as current",
     [('    return "CURRENT" if any(s in current for s in scopes or []) else "UNASSESSED"', '    return "CURRENT"')]),
    ("L22", "loops.py", "applicability follows the defect's revision, not the closure's (F2)",
     [('    scopes = out.get("closure_scope") if out["closed_by"] else [out["scope"]]', '    scopes = [out["scope"]]')]),
    ("L23", "loops.py", "a taken question still counts as unowned",
     [('            if q not in taken:', '            if True:')]),
    ("L23", "loops.py", "every duty is in every actor's frontier",
     [('        if not involved:\n            continue\n', '')]),
    ("L25", "loops.py", "unimplemented kinds are assessed as obligations",
     [('    if d["kind"] not in IMPLEMENTED_KINDS:', '    if False:')]),
    ("L26", "loops.py", "a mapping may cite evidence the transition does not carry",
     [('        if not set(m["evidence"]) <= set(did["evidence"]):', '        if False:')]),
    ("L27", "loops.py", "misaddressed bytes are read",
     [('    if hashlib.sha256(raw).hexdigest() != h:\n        return None\n', '')]),
    ("L27", "loops.py", "non-canonical bytes are read",
     [('    return doc if isinstance(doc, dict) and canon(doc) == raw else None',
       '    return doc if isinstance(doc, dict) else None')]),
    ("L28", "loops.py", "a past overclaim keeps a closed duty in the frontier",
     [('        live = open_like or bool(set(r["flags"]) - {"OVERCLAIMED_CANDIDATE", "UNVERIFIED_CANDIDATE"})',
       '        live = open_like or bool(r["flags"])')]),
    ("L29", "loops.py", "a claimed basis is taken as validated (WL01)",
     [('    elif claimed not in VALIDATED_BASES:', '    elif False:')]),
    ("L30", "loops.py", "cited evidence need not be in the view (WL01)",
     [('    if not all(_resolves(view.store, h) for h in m["evidence"]):', '    if False:')]),
    ("L30", "loops.py", "evidence bytes need not match their address (WL01)",
     [('        return p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest() == h',
       '        return p.is_file()')]),
    ("L30", "loops.py", "an attestation need not name its evidence",
     [('    if not m["evidence"]:', '    if False:')]),
    ("L31", "loops.py", "a duty is assigned to someone who never accepted it (WL02)",
     [('    if m["to"] not in accepted:', '    if False:')]),
    ("L32", "loops.py", "a delegation counts before the delegate accepts it (WL02)",
     [('    if m["to"] not in accepted:', '    if m["to"] not in accepted and m["disposition"] == "SUBSTITUTED":')]),
    ("L33", "loops.py", "an acceptor's support need not resolve (F4)",
     [('            if why is None and not all(_resolves(self.store, h) for h in doc.get("support", [])):',
       '            if False:')]),
    ("L34", "loops.py", "any closure is reliable, whatever the revision (F2)",
     [('    if r["applicability"] != "CURRENT" and not scoped:', '    if False:')]),
    ("L35", "loops.py", "the question view ignores the scope (F3)",
     [('    return [q for q in rep["unowned_questions"] if scope is None or q["scope"] == scope]',
       '    return list(rep["unowned_questions"])')]),
    ("L36", "loops.py", "a parent closes without the children its condition names (F5)",
     [('    if disp == "DISCHARGED":\n        unmet = _unmet_children(d, done)',
       '    if False:\n        unmet = _unmet_children(d, done)')]),
]


def prepare(tmp, srcs):
    (tmp / "loops.py").write_text(srcs["loops.py"])
    return {"LOOPS_IMPL": str(tmp)}


if __name__ == "__main__":
    sys.exit(campaign("LOOPS MUTANTS", MUTANTS, SOURCES, prepare, ROOT / "tests" / "loops_test.py", "LOOPS_RESULTS"))
