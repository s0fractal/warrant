#!/usr/bin/env python3
"""Fail-closed harness for tools/fact_derivation_check.py (WRT-008).

  A. the tool's own selftest passes (22 controls);
  B. three mutants of the TOOL must make that selftest fail -- a harness that
     cannot go red is the defect one level up;
  C. end to end on a real .warrants layout: a WPL policy compiled with
     --store, evidence and profile blobs put beside it, the CLI reporting per
     fact, exit 0 on a clean profile and 1 once the evidence contradicts the
     term; a blob wearing the wrong name is UNRESOLVED, not read.
Every relation is asserted; any deviation exits 1.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "fact_derivation_check.py"
PY = sys.executable
ok = []


def chk(cond, what, detail=""):
    ok.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + what + (f"  [{detail}]" if detail and not cond else ""))


def run(args, cwd=ROOT):
    return subprocess.run([PY, *args], cwd=cwd, capture_output=True, text=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def section_a():
    r = run([str(TOOL), "--selftest"])
    chk(r.returncode == 0 and "FACT-DERIVATION-SELFTEST: ALL PASS" in r.stdout, "A. tool selftest passes", r.stdout[-200:] + r.stderr[-200:])


def section_b():
    src = TOOL.read_text()
    mutants = {
        "diverged never reported": ('results.append((name, "DIVERGED",', 'results.append((name, "DERIVED",'),
        "cmd executed by default": ("if not execute:\n            return \"UNRUN\"", "if False:\n            return \"UNRUN\""),
        "profile value unchecked": ('raise Refusal(f"PROFILE_VALUE_NOT_IN_TERM:{name}")', "pass"),
    }
    for name, (old, new) in mutants.items():
        assert src.count(old) == 1, (name, src.count(old))
        with tempfile.TemporaryDirectory() as td:
            tools = Path(td) / "tools"; tools.mkdir()
            (tools / "fact_derivation_check.py").write_text(src.replace(old, new))
            os.symlink(ROOT / "impl", Path(td) / "impl")
            r = run([str(tools / "fact_derivation_check.py"), "--selftest"], cwd=td)
            chk(r.returncode != 0, f"B. mutant '{name}' is caught by the selftest", r.stdout[-200:])


def section_c():
    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / ".warrants"; (store / "blobs").mkdir(parents=True)

        def put(b):
            h = sha(b); (store / "blobs" / h).write_bytes(b); return h
        policy = Path(td) / "gate.wpl"
        policy.write_text("fact files_changed: int = 2\nfact lines_added: int = 267\n"
                          "fact label: string = \"docs\"\n"
                          "check files_changed <= 30 && lines_added <= 600 && label == \"docs\"\n")
        r = run([str(ROOT / "impl" / "policy_lang.py"), "compile", str(policy), "--store", str(store), "--json"])
        chk(r.returncode == 0, "C. policy compiles into the store", r.stderr[-200:])
        compiled = json.loads(r.stdout)
        chk(compiled["result"] is True and compiled["check"], "C. compiled check is stored and true")
        src_hex = put(policy.read_bytes())
        evidence = put(b'{"lines_added": 267, "paths": ["a.md", "b.md"], "label": "docs"}')
        profile = {"profile": "warrant.fact-derivation@v0", "policy_source": src_hex, "facts": {
            "files_changed": {"from": evidence, "via": {"kind": "json-len", "pointer": "/paths"}, "value": 2},
            "lines_added": {"from": evidence, "via": {"kind": "json", "pointer": "/lines_added"}, "value": 267},
            "label": {"from": evidence, "via": {"kind": "json", "pointer": "/label"}, "value": "docs"}}}
        canon = lambda d: json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
        prof_hex = put(canon(profile))
        r = run([str(TOOL), "--store", str(store), "--profile", prof_hex])
        lines = r.stdout.splitlines()
        chk(r.returncode == 0, "C. clean profile exits 0", r.stdout)
        chk(sum(1 for l in lines if l.startswith("DERIVED")) == 3, "C. three facts DERIVED", r.stdout)
        chk(re.search(r"FACT-DERIVATION [0-9a-f]{12}: facts=3 derived=3 diverged=0 .* semantic-credit=none", r.stdout) is not None,
            "C. summary line counts facts and disclaims credit", r.stdout)
        # Evidence that contradicts the term -> DIVERGED, exit 1.
        tampered = put(b'{"lines_added": 601, "paths": ["a.md", "b.md"], "label": "docs"}')
        bad = json.loads(json.dumps(profile)); bad["facts"]["lines_added"]["from"] = tampered
        bad_hex = put(canon(bad))
        r = run([str(TOOL), "--store", str(store), "--profile", bad_hex])
        chk(r.returncode == 1 and "DIVERGED   lines_added" in r.stdout, "C. contradicting evidence -> DIVERGED, exit 1", r.stdout)
        # Bytes wearing the evidence blob's name are not that blob.
        (store / "blobs" / evidence).write_bytes(b'{"lines_added": 267, "paths": ["a.md", "b.md"], "label": "docs", "x": 1}')
        r = run([str(TOOL), "--store", str(store), "--profile", prof_hex])
        chk(r.returncode == 0 and r.stdout.count("UNRESOLVED") == 3, "C. blob not hashing to its address is UNRESOLVED, never read", r.stdout)
        # A profile that is not there.
        r = run([str(TOOL), "--store", str(store), "--profile", "f" * 64])
        chk(r.returncode == 1 and "REFUSED  PROFILE_UNRESOLVED" in r.stdout, "C. missing profile is a typed refusal", r.stdout)


def main():
    section_a(); section_b(); section_c()
    print(f"\n{sum(ok)}/{len(ok)} checks")
    print("FACT-DERIVATION: ALL PASS" if all(ok) else "FACT-DERIVATION: FAILURES PRESENT")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
