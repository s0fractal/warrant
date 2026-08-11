#!/usr/bin/env python3
"""Run every mutant in `mutants.json` against `gate.py`. Exit status is the
verdict.

A gate nobody has seen fail is indistinguishable from a gate that cannot
fail. Round 1 asserted "9/9 mutations fail" in a README table with **no
runner in the repository** — a claim a reader could not check, and a reviewer
correctly refused to take.

Two rules make this an artifact rather than a gesture:

- **A missing anchor is a failure, not a skip.** When the code moves, a
  mutant that no longer applies must break loudly; silently skipping it is
  how a mutation suite decays into decoration.
- **The mutation must change the source.** An edit that leaves the file
  byte-identical proves nothing, which is exactly how one round-1 mutant
  "passed" while editing a docstring.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv):
    with open(os.path.join(HERE, "mutants.json")) as fh:
        doc = json.load(fh)
    cases = doc.get("cases") or []
    if not cases:
        print("FAIL  no mutants — a mutation run over zero cases is vacuous")
        return 1

    backup = tempfile.mkdtemp(prefix="wrt004-mut-")
    for name in ("input_manifest.py", "input_manifest.go"):
        shutil.copy(os.path.join(HERE, name), os.path.join(backup, name))

    # PRISTINE PREFLIGHT. Without it every mutant "dies" whenever the gate
    # is broken for an unrelated reason: with Go absent, each run fails, each
    # failure counts as a kill, and the suite reports 14/14 and exit 0 over a
    # baseline that never went green. A kill must be a transition from green
    # to red, not merely red.
    #
    # (Added while CLOSING this direction, not to advance it: leaving a tool
    # in the tree that reports success over a broken baseline would be
    # leaving a trap for whoever reads the retained artifact.)
    pre = subprocess.run([sys.executable, os.path.join(HERE, "gate.py")],
                         capture_output=True, text=True)
    if pre.returncode != 0:
        print("FAIL  the pristine baseline is not green — every mutant would "
              "'die' for a reason that has nothing to do with the mutation")
        print(pre.stdout[-400:])
        return 1
    print("pristine baseline: green\n")

    survived, applied = [], 0
    try:
        for case in cases:
            path = os.path.join(HERE, case["file"])
            with open(path) as fh:
                src = fh.read()
            if case["anchor"] not in src:
                print("FAIL  anchor missing (the code moved): %s" % case["name"])
                survived.append(case["name"])
                continue
            mutated = src.replace(case["anchor"], case["replacement"], 1)
            if mutated == src:
                print("FAIL  mutation changed nothing: %s" % case["name"])
                survived.append(case["name"])
                continue
            with open(path, "w") as fh:
                fh.write(mutated)
            applied += 1
            proc = subprocess.run([sys.executable, os.path.join(HERE, "gate.py")],
                                  capture_output=True, text=True)
            killed = proc.returncode != 0
            print("%s  %s" % ("kill" if killed else "SURVIVED", case["name"]))
            if not killed:
                survived.append(case["name"])
            shutil.copy(os.path.join(backup, case["file"]), path)
    finally:
        for name in ("input_manifest.py", "input_manifest.go"):
            shutil.copy(os.path.join(backup, name), os.path.join(HERE, name))
        shutil.rmtree(backup, ignore_errors=True)

    print("\n%d/%d mutants killed." % (applied - len(survived), len(cases)))
    if survived:
        print("SURVIVING: %s" % ", ".join(survived))
        print("A surviving mutant is a hole in the gate, not a quirk.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
