#!/usr/bin/env python3
"""Each mutant of impl/warrant.py's evaluator loader undoes one rule and must make
ITS case of tests/sigma_loader_read_once.py fail (OFF_TARGET and CRASH are not kills).

    python3 tests/sigma_loader_mutants.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mutant_runner import campaign  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {"warrant.py": (ROOT / "impl" / "warrant.py").read_text()}

MUTANTS = [
    ("R1", "warrant.py", "the module is built from a second read of the file, not the hashed bytes",
     [('    exec(compile(data, str(path), "exec"), mod.__dict__)  # noqa: S102  # NOSONAR',
       '    exec(compile(path.read_bytes(), str(path), "exec"), mod.__dict__)')]),
    ("R2", "warrant.py", "the override's decision and its execution read the file separately",
     [('            mod = _import_sigma(op, unpinned=not same, data=data)',
       '            mod = _import_sigma(op, unpinned=not same)')]),
    ("R3", "warrant.py", "a moved pinned module is executed",
     [('        if got != expected_sha:', '        if False:')]),
    ("R4", "warrant.py", "'pinned' is decided against the bundled file, not the pinned digest",
     [('            same = hashlib.sha256(data).hexdigest() == ent[1]',
       '            same = data == bundled_sigma_path(tag).read_bytes()')]),
]


def prepare(tmp, srcs):
    impl = tmp / "impl"
    shutil.copytree(ROOT / "impl", impl, ignore=shutil.ignore_patterns("__pycache__"))
    (impl / "warrant.py").write_text(srcs["warrant.py"])
    return {"WARRANT_IMPL": str(impl)}


if __name__ == "__main__":
    sys.exit(campaign("SIGMA LOADER MUTANTS", MUTANTS, SOURCES, prepare,
                      ROOT / "tests" / "sigma_loader_read_once.py", "SIGMA_LOADER_RESULTS"))
