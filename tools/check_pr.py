#!/usr/bin/env python3
"""Local pre-flight check for pull requests (external contributors and agents).

    python3 tools/check_pr.py [--base master] [--files FILE ...] [--run-tests] [--run-mutants] [--json]

Catches the three CI surprises external contributors hit most often before pushing:
  1. `warrant_verify.py` drift after editing any module reachable from `warrant/verify.py` (`tools/build_verify.py`).
  2. Stale or ambiguous mutants in `tests/mutants.py` whose `find` snippet no longer matches uniquely in a modified file.
  3. Core boundary violations (`tests/boundary_test.py`: `warrant/` must not import `warrant_agent/`).

Exits 0 when every check passes, 1 when any check fails (with exact commands to fix), 2 on usage/git errors.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import build_verify as BV  # noqa: E402


def _git_lines(root: Path, *args: str) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def changed_files(root: Path, base: str = "master") -> list[str]:
    """Sorted unique repo-relative paths changed vs `base`, including staged and unstaged edits."""
    found = set()
    found.update(_git_lines(root, "diff", "--name-only", f"{base}...HEAD"))
    found.update(_git_lines(root, "diff", "--name-only"))
    found.update(_git_lines(root, "diff", "--cached", "--name-only"))
    return sorted(found)


def check_verify_fresh(root: Path) -> dict:
    """Verify `warrant_verify.py` matches what `tools/build_verify.py` builds from `warrant/`."""
    out = root / BV.OUT
    expected = BV.build(root)
    same = out.is_file() and out.read_text(encoding="utf-8") == expected
    return {"ok": same, "stale": not same, "fix": "python3 tools/build_verify.py"}


def _load_mutants(root: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("_warrant_mutants", root / "tests" / "mutants.py")
    if spec is None or spec.loader is None:
        raise ValueError("cannot load tests/mutants.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MUTANTS


def check_mutants_fresh(root: Path, files: list[str], mutants=None) -> dict:
    """Check that every mutant in `tests/mutants.py` targeting a modified file matches its `find` string exactly once."""
    rows = _load_mutants(root) if mutants is None else mutants
    touched = set(files)
    affected_mutants = []
    affected_tests = set()
    stale = []
    ambiguous = []
    cache: dict[str, str | None] = {}

    for row in rows:
        mid, rel_path, find, _replace, test_file, _cases = row
        if rel_path not in touched:
            continue
        affected_mutants.append(mid)
        affected_tests.add(test_file)
        if rel_path not in cache:
            p = root / rel_path
            cache[rel_path] = p.read_text(encoding="utf-8") if p.is_file() else None
        text = cache[rel_path]
        if text is None:
            stale.append({"id": mid, "file": rel_path, "reason": "FILE_MISSING"})
            continue
        count = text.count(find)
        if count == 0:
            stale.append({"id": mid, "file": rel_path, "reason": "FIND_NOT_FOUND"})
        elif count > 1:
            ambiguous.append({"id": mid, "file": rel_path, "reason": f"MATCHES_{count}_TIMES"})

    ok = not stale and not ambiguous
    return {
        "ok": ok,
        "affected_mutants": sorted(affected_mutants),
        "affected_tests": sorted(affected_tests),
        "stale": stale,
        "ambiguous": ambiguous,
    }


def check_boundary(root: Path, files: list[str]) -> dict:
    """Run B1 (`tests/boundary_test.py` `boundary_problems`) on any modified `warrant/*.py` module (stdlib only)."""
    core_files = [f for f in files if f.startswith("warrant/") and f.endswith(".py") and (root / f).is_file()]
    if not core_files:
        return {"ran": False, "ok": True, "problems": []}
    import importlib.util
    if str(root / "tests") not in sys.path:
        sys.path.insert(0, str(root / "tests"))
    spec = importlib.util.spec_from_file_location("_warrant_boundary", root / "tests" / "boundary_test.py")
    if spec is None or spec.loader is None:
        raise ValueError("cannot load tests/boundary_test.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    modules = {f[len("warrant/"):]: (root / f).read_text(encoding="utf-8") for f in core_files}
    probs = mod.boundary_problems(modules)
    return {
        "ran": True,
        "ok": not probs,
        "problems": [{"file": f"warrant/{rel}", "line": line, "reason": why} for rel, line, why in probs],
    }


def run_check(root: Path = ROOT, *, base: str = "master", files: list[str] | None = None,
              run_tests: bool = False, run_mutants: bool = False, mutants=None) -> dict:
    """Run all pre-flight checks and return a deterministic JSON-serializable report."""
    target_files = sorted(set(files)) if files is not None else changed_files(root, base)
    verify = check_verify_fresh(root)
    mut = check_mutants_fresh(root, target_files, mutants=mutants)
    boundary = check_boundary(root, target_files)

    hints = []
    if not verify["ok"]:
        hints.append("python3 tools/build_verify.py")
    if mut["stale"] or mut["ambiguous"]:
        bad_ids = [x["id"] for x in mut["stale"] + mut["ambiguous"]]
        hints.append(f"retarget stale/ambiguous mutants in tests/mutants.py: {', '.join(bad_ids)}")
    if not boundary["ok"]:
        hints.append("fix core boundary violation reported by tests/boundary_test.py (warrant/ must not import warrant_agent/)")

    test_runs = []
    if run_tests and mut["affected_tests"]:
        for tf in mut["affected_tests"]:
            r = subprocess.run([sys.executable, "-B", tf], cwd=root, capture_output=True, text=True)
            test_runs.append({"test": tf, "ok": r.returncode == 0})
    mutant_run = None
    if run_mutants and mut["affected_mutants"] and mut["ok"]:
        r = subprocess.run([sys.executable, "-B", "tests/mutants.py", *mut["affected_mutants"]],
                           cwd=root, capture_output=True, text=True)
        mutant_run = {"ok": r.returncode == 0, "output": (r.stdout + r.stderr).strip()}

    overall = (
        verify["ok"]
        and mut["ok"]
        and boundary["ok"]
        and all(t["ok"] for t in test_runs)
        and (mutant_run is None or mutant_run["ok"])
    )
    out = {
        "ok": overall,
        "files": target_files,
        "verify": verify,
        "mutants": mut,
        "boundary": boundary,
        "hints": hints,
    }
    if run_tests:
        out["test_runs"] = test_runs
    if run_mutants:
        out["mutant_run"] = mutant_run
    return out


def format_text(rep: dict) -> str:
    lines = [
        f"PR PRE-FLIGHT: {'PASS' if rep['ok'] else 'FAIL'} ({len(rep['files'])} changed file(s))",
        f"  warrant_verify.py : {'ok' if rep['verify']['ok'] else 'STALE -> ' + rep['verify']['fix']}",
        f"  mutants targeting : {len(rep['mutants']['affected_mutants'])} affected, "
        f"{len(rep['mutants']['stale'])} stale, {len(rep['mutants']['ambiguous'])} ambiguous",
        f"  core boundary B1  : {'ok' if rep['boundary']['ok'] else 'FAIL'}"
        + ("" if rep["boundary"]["ran"] else " (skipped: no warrant/*.py changed)"),
    ]
    for item in rep["mutants"]["stale"] + rep["mutants"]["ambiguous"]:
        lines.append(f"    ! {item['id']} ({item['file']}): {item['reason']}")
    if rep["mutants"]["affected_tests"]:
        lines.append("  suggested tests   : " + ", ".join(rep["mutants"]["affected_tests"]))
    if rep["mutants"]["affected_mutants"]:
        lines.append("  suggested mutants : python3 tests/mutants.py " + " ".join(rep["mutants"]["affected_mutants"]))
    for h in rep["hints"]:
        lines.append(f"  ACTION: {h}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tools/check_pr.py", description="Local pre-flight check for Warrant PRs.")
    ap.add_argument("--base", default="master", help="Git base ref to diff against (default: master)")
    ap.add_argument("--files", nargs="*", default=None, help="Explicit repo-relative files instead of git diff")
    ap.add_argument("--run-tests", action="store_true", help="Also run affected test files")
    ap.add_argument("--run-mutants", action="store_true", help="Also run affected mutants")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    a = ap.parse_args(argv)
    try:
        rep = run_check(ROOT, base=a.base, files=a.files, run_tests=a.run_tests, run_mutants=a.run_mutants)
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=2, sort_keys=True) if a.json else format_text(rep))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
