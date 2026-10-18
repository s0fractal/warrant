#!/usr/bin/env python3
"""Each mutant of impl/warrant.py's evaluator loader undoes one rule and must make
ITS case of tests/sigma_loader_read_once.py fail (OFF_TARGET and CRASH are not kills).

    python3 tests/sigma_loader_mutants.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "impl" / "warrant.py").read_text()

MUTANTS = [
    ("R1", "the module is built from a second read of the file, not the hashed bytes",
     [('    exec(compile(data, str(path), "exec"), mod.__dict__)  # noqa: S102  # NOSONAR',
       '    exec(compile(path.read_bytes(), str(path), "exec"), mod.__dict__)')]),
    ("R2", "the override's decision and its execution read the file separately",
     [('            mod = _import_sigma(op, unpinned=not same, data=data)',
       '            mod = _import_sigma(op, unpinned=not same)')]),
    ("R3", "a moved pinned module is executed",
     [('        if got != expected_sha:', '        if False:')]),
    ("R4", "'pinned' is decided against the bundled file, not the pinned digest",
     [('            same = hashlib.sha256(data).hexdigest() == ent[1]',
       '            same = data == bundled_sigma_path(tag).read_bytes()')]),
]


def run(target, pairs):
    src = SRC
    for old, new in pairs:
        if src.count(old) != 1:
            return "BAD_MUTANT", f"pattern occurs {src.count(old)} times: {old[:60]!r}"
        src = src.replace(old, new)
    with tempfile.TemporaryDirectory() as tmp:
        impl = Path(tmp) / "impl"
        shutil.copytree(ROOT / "impl", impl, ignore=shutil.ignore_patterns("__pycache__"))
        (impl / "warrant.py").write_text(src)
        res = Path(tmp) / "results.json"
        env = dict(os.environ, WARRANT_IMPL=str(impl), SIGMA_LOADER_RESULTS=str(res))
        env.pop("SIGMA_GLYPH", None)
        subprocess.run([sys.executable, str(ROOT / "tests" / "sigma_loader_read_once.py")], env=env,
                       capture_output=True, text=True, check=False)
        if not res.exists():
            return "CRASH", ""
        results = json.loads(res.read_text())
    failed = sorted(k for k, v in results.items() if v == "FAIL")
    if results.get(target) == "FAIL":
        return "KILLED", ",".join(failed)
    return ("OFF_TARGET" if failed else "SURVIVED"), ",".join(failed)


def main():
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        outcomes = list(pool.map(lambda mt: run(mt[0], mt[2]), MUTANTS))
    killed = 0
    for (target, what, _), (v, detail) in zip(MUTANTS, outcomes):
        killed += v == "KILLED"
        print(f"{v:10} {target} {what}" + (f"  [{detail}]" if detail else ""))
    print(f"SIGMA LOADER MUTANTS: {killed}/{len(MUTANTS)} killed on target")
    return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
