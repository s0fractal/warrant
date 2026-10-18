#!/usr/bin/env python3
"""Shared runner for this repository's targeted mutation campaigns.

A campaign is a list of (target case, file, description, [(old, new), ...]). Each
mutant is applied to a private copy of the sources, the campaign's test script runs
against that copy, and the mutant counts as KILLED only if ITS target case fails.
Breaking only another case is OFF_TARGET; a run that writes no results is CRASH;
a pattern that does not occur exactly once is BAD_MUTANT. None of those is a kill.
"""
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def run_one(target, pairs, sources, prepare, test, results_env, extra_env=None):
    """`sources` maps a file name to its text; `prepare(tmpdir, sources)` lays out a
    private copy and returns the environment the test needs to use it."""
    srcs = dict(sources)
    for fname, old, new in pairs:
        if srcs[fname].count(old) != 1:
            return "BAD_MUTANT", f"pattern occurs {srcs[fname].count(old)} times: {old[:60]!r}"
        srcs[fname] = srcs[fname].replace(old, new)
    with tempfile.TemporaryDirectory() as tmp:
        res = Path(tmp) / "results.json"
        env = dict(os.environ, **(extra_env or {}), **prepare(Path(tmp), srcs), **{results_env: str(res)})
        subprocess.run([sys.executable, str(test)], env=env, capture_output=True, text=True, check=False)
        if not res.exists():
            return "CRASH", ""
        results = json.loads(res.read_text())
    failed = sorted(k for k, v in results.items() if v == "FAIL")
    if results.get(target) == "FAIL":
        return "KILLED", ",".join(failed)
    return ("OFF_TARGET" if failed else "SURVIVED"), ",".join(failed)


def campaign(name, mutants, sources, prepare, test, results_env, extra_env=None):
    """Run every mutant in parallel and print one line each; exit status 0 iff all killed."""
    def one(m):
        target, fname, _, pairs = m
        return run_one(target, [(fname, o, n) for o, n in pairs], sources, prepare, test, results_env, extra_env)
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        outcomes = list(pool.map(one, mutants))
    killed = 0
    for (target, fname, what, _), (v, detail) in zip(mutants, outcomes):
        killed += v == "KILLED"
        print(f"{v:10} {target} {fname}: {what}" + (f"  [{detail}]" if detail else ""))
    print(f"{name}: {killed}/{len(mutants)} killed on target")
    return 0 if killed == len(mutants) else 1
