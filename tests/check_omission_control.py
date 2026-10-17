#!/usr/bin/env python3
"""N70: removing a required check from the harness turns it red, by name.

A copy of tools/check.py with one required entry deleted from CHECKS is run
with --required-only; it must exit 1 and name the dropped script. The real
harness must exit 0. A control that stays green when the check did not run at
all would be the failure this exists to catch.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "tools" / "check.py").read_text()
DROP = "tests/assessment_test.py"


def run(text):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "tools").mkdir()
        (Path(tmp) / "tools" / "check.py").write_text(text)
        return subprocess.run([sys.executable, str(Path(tmp) / "tools" / "check.py"), "--required-only"],
                              capture_output=True, text=True, check=False)


def main():
    entry = re.search(r'    \("[^"\n]*",\n     \["python3", "' + re.escape(DROP) + r'"\], None\),\n', SRC)
    assert entry, "the required entry to drop was not found"
    real = run(SRC)
    dropped = run(SRC.replace(entry.group(0), ""))
    ok_real = real.returncode == 0 and "FAIL" not in real.stdout
    ok_drop = dropped.returncode == 1 and f"omits a required check: {DROP}" in dropped.stdout
    print(("ok  " if ok_real else "FAIL"), "the real harness lists every required check")
    print(("ok  " if ok_drop else "FAIL"), f"dropping {DROP} from CHECKS is red and named", "" if ok_drop else dropped.stdout)
    print("CHECK OMISSION CONTROL:", "ALL PASS" if ok_real and ok_drop else "FAILURES")
    return 0 if ok_real and ok_drop else 1


if __name__ == "__main__":
    sys.exit(main())
