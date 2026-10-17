#!/usr/bin/env python3
"""Each mutant of impl/assessment.py must make ITS case of tests/assessment_test.py
fail; breaking only some other case is OFF_TARGET, not killed.

    python3 tests/assessment_mutants.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "impl" / "assessment.py").read_text()

MUTANTS = [
    ("SNAPSHOT", "the assessment reads the live store instead of one snapshot",
     '        store, store_sha = _snapshot_store(store_root, Path(tmp) / "store")',
     '        store, store_sha = W.Store(str(store_root)), "live"'),
    # Independent review (Codex, 2026-10-17): each fix has a mutant that undoes it.
    ("WA01", "a derived int is accepted from a Boolean answer",
     '    if typ != "bool" or type(f.get("value")) is not bool:',
     '    if False:'),
    ("WA02", "unattested facts still yield a consequence",
     '                and a["fact_provenance"] == "ACCEPTED" and a["required_profile"] == "SATISFIED"',
     '                and a["required_profile"] == "SATISFIED"'),
    ("WA04", "the context ignores the trust snapshot",
     '    return blob_id({"verifier_build": build, "profile_id": blob_id(prof), "trust_sha256": trust_sha,',
     '    return blob_id({"verifier_build": build, "profile_id": blob_id(prof),'),
    ("WA05", "the plan's runtime is not checked",
     '    if pl.get("runtime") != RUNTIME:',
     '    if False:'),
    ("N38", "accept is compliant whatever the answer",
     '        return "COMPLIANT" if answer == "TRUE" else "CONTRADICTED_DECISION"',
     '        return "COMPLIANT"'),
    ("N48", "discretionary reject always allowed",
     '        return "COMPLIANT" if answer == "FALSE" or discretionary_reject else "CONTRADICTED_DECISION"',
     '        return "COMPLIANT"'),
    ("N41", "any ski@v1 pass reason counts as the plan's check",
     '    if not any(r.get("runtime") == RUNTIME and r.get("check") == check and r.get("verdict") == "pass"',
     '    if not any(r.get("runtime") == RUNTIME and r.get("verdict") == "pass"'),
    ("N43", "the plan's declared options and emitted values are not compared",
     '    if (emitted["check"], emitted["term"], emitted["expect"], emitted["atp"]) != (check, doc["term"], doc["expect"], doc["atp"]):',
     '    if emitted["term"] != doc["term"]:'),
    ("N44", "an unregistered compiler is accepted",
     '    if pl.get("compiler_id") not in COMPILERS:',
     '    if False:'),
    ("N45", "the recipient's admitted programs are not consulted",
     '    admitted = (p_id in prof["admitted_programs"] and prog.get("obligation") == prof["obligation"]',
     '    admitted = (True and prog.get("obligation") == prof["obligation"]'),
    ("N46", "any bound actor counts as an admitted issuer",
     '    return bool(rec and rec.get("actor", {}).get("id") in prof["fact_issuers"]',
     '    return bool(rec'),
    ("N47", "a derived value is not compared with its source's answer",
     '    if comp != "REPLAYED_NORMAL_FORM" or ans != ("TRUE" if f["value"] is True else "FALSE"):',
     '    if comp != "REPLAYED_NORMAL_FORM":'),
    ("N49", "the required profile is ignored",
     '    axes["required_profile"] = "SATISFIED" if (has_all or prof["required"] == "witness") else \\',
     '    axes["required_profile"] = "SATISFIED" if True else \\'),
    ("N52", "an unfinished run still yields a consequence",
     '                and a["computation_verification"] == "REPLAYED_NORMAL_FORM"\n',
     '\n'),
    ("N55", "any change of report counts as new evidence, named slot or not",
     '    if candidate_report.get("slots") != settled_report.get("slots"):',
     '    if candidate_report.get("record") != settled_report.get("record"):'),
    ("N58", "an invented obligation counts as a new consequence",
     '    if scope.get("obligation") != prof["obligation"]:\n        return "SCOPE_MISMATCH"\n',
     ''),
]


def run(text):
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "assessment.py").write_text(text.replace(
            'HERE = Path(__file__).resolve().parent', f'HERE = Path({str(ROOT / "impl")!r})'))
        r = subprocess.run([sys.executable, str(ROOT / "tests" / "assessment_test.py")],
                           env=dict(os.environ, ASSESSMENT_IMPL=tmp), capture_output=True, text=True, timeout=900)
    return r.stdout + r.stderr


def main():
    base = run(SRC)
    clean = "0 FAIL" in base
    print(("ok  " if clean else "FAIL"), "unmutated module: no FAIL")
    if not clean:
        print(base[-1500:])
        return 1
    ok = True
    for nid, what, old, new in MUTANTS:
        if SRC.count(old) != 1:
            print(f"FAIL  {nid}: mutant site missing or not unique ({what})")
            ok = False
            continue
        out = run(SRC.replace(old, new))
        hit = re.search(rf"^FAIL  {nid}\b", out, re.M) is not None
        verdict = "KILLED" if hit else ("CRASHED" if "Traceback" in out else "OFF_TARGET" if "FAIL" in out else "SURVIVED")
        ok &= hit
        print(f"{verdict:10} {nid} {what}")
    print("ASSESSMENT MUTANTS:", "ALL KILLED ON TARGET" if ok else "NOT ALL KILLED ON TARGET")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
