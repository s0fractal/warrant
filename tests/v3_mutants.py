#!/usr/bin/env python3
"""Mutants of the Warrant 3 core and migration: each is one exact find/replace in one file, and the
named test must fail on its own assertion (a FAIL line or an undeclared parity difference), never by
a crash. The run happens in a copy under build/v3-mutants/; the unmutated copy must pass first.

    python3 tests/v3_mutants.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / "build" / "v3-mutants"
CORE, PARITY = "tests/v3_core_test.py", "tests/v3_parity_test.py"
MUTANTS = [
    ("V1", "warrant3/engine.py", 'self._effective[L] = next((v for v in reversed(path) if self.guard(v)["guard"] in (NONE, MET)), None)',
     "self._effective[L] = path[-1] if path else None", PARITY),
    ("V2", "tools/migrate_v2_to_v3.py", "            if before:\n", "            if False:\n", PARITY),
    ("V3", "warrant3/engine.py", 'return any(actor in self.profile["roles"].get(x, []) for x in roles)', "return True", CORE),
    ("V4", "warrant3/engine.py", 'out.update((self.recs[cur]["guard"] or {}).get("requires", []))', "pass", CORE),
    ("V5", "warrant3/engine.py", 'if self.recs[a]["actor"] != r["actor"] and self.holds', "if self.holds", CORE),
    ("V6", "tools/migrate_v2_to_v3.py", '"PASS": "does_not_reproduce"', '"PASS": "reproduces"', PARITY),
    ("V7", "warrant3/engine.py", 'forks = {p: c for p, c in lin["succ"].items() if len(c) > 1}', "forks = {}", CORE),
    ("V8", "warrant3/engine.py", "elif not may_succeed(r, self.recs[rt]):", "elif False:", CORE),
    ("V9", "warrant3/engine.py", 'if need is not None and _weaker(r["guard"], need):', "if False:", CORE),
    ("V10", "warrant3/engine.py", "if by is not None:", "if True:", CORE),
    ("V12", "warrant3/engine.py", 'elif any(e["sig"] is None for e in envs):', "elif not sigs:", CORE),
    ("V13", "warrant3/engine.py", 'return r["actor"] == root["actor"] if roles is None else self.holds(r["actor"], *roles)',
     'return r["actor"] == root["actor"]', CORE),
    ("V14", "warrant3/engine.py", 'return r["actor"] == root["actor"] if roles is None else self.holds(r["actor"], *roles)',
     'return r["actor"] == root["actor"] or (roles is not None and self.holds(r["actor"], *roles))', CORE),
    ("V15", "warrant3/engine.py", 'if r["body"].get("state") in self.schema_of(v).get("closed", []):       # with',
     'if g is not None and r["body"].get("state") in self.schema_of(v).get("closed", []):       # with', CORE),
    ("V16", "warrant3/engine.py", 'if why or len(backers) < self.quorum("schema/author"):', "if why or not backers:", CORE),
    ("V11", "warrant3/engine.py", 'elif any(on == x and v == "reproduces" for on, v, _ in replays):', "elif False:", CORE),
]


def run(test):
    r = subprocess.run([sys.executable, "-B", test], cwd=COPY, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
    out = r.stdout + r.stderr
    asserted = "\nFAIL " in "\n" + out or any(l.split()[-1] != "0" for l in out.splitlines()
                                             if l.split()[:1] in (["claim"], ["goal"], ["obligation"], ["review"]))
    return r.returncode, asserted and "Traceback" not in out


def main():
    if COPY.exists():
        shutil.rmtree(COPY)
    for d in ("warrant", "warrant3", "tools", "tests", ".warrant"):
        shutil.copytree(ROOT / d, COPY / d, ignore=shutil.ignore_patterns("__pycache__"))
    for test in (CORE, PARITY):
        rc, _ = run(test)
        if rc:
            print(f"BASELINE_RED {test}")
            return 2
    survived = 0
    for mid, path, old, new, test in MUTANTS:
        f = COPY / path
        src = f.read_text()
        if src.count(old) != 1:
            print(f"{mid} STALE: the find text occurs {src.count(old)} times in {path}")
            survived += 1
            continue
        f.write_text(src.replace(old, new))
        rc, asserted = run(test)
        f.write_text(src)
        killed = rc != 0 and asserted
        survived += not killed
        print(f"{mid} {'KILLED' if killed else 'SURVIVED'} {path} by {test}")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
