#!/usr/bin/env python3
"""A base-grade-only candidate, for the runner's grade-asymmetry controls.

    python3 tests/fixtures/base_only_candidate.py -- <real candidate argv>

Every implementation in this repository now reaches settlement grade, so the
runner's handling of a candidate that implements SPEC §6 and NOT §7 -- report
the settlement vectors NOT-CLAIMED, and when such a candidate is forced to claim
settlement, report the gap as UNRUN and withhold the grade -- would otherwise no
longer be exercised by anything. This proxy is that candidate: it forwards to a
real implementation, declares `grade: "base"`, and declines exactly the
settlement-grade questions, honestly, as `unsupported`.
"""
import json
import subprocess
import sys


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    raw = sys.stdin.buffer.read()
    req = json.loads(raw.decode("utf-8"))
    cls = req.get("class")
    inp = req.get("input") or {}
    settlement = cls == "ski-run" or (cls == "verify-store" and inp.get("grade") == "settlement")
    if settlement:
        print(json.dumps({"warrant_conformance": "1", "id": req.get("id"),
                          "unsupported": "base-grade control: SPEC §7 not implemented"}))
        return 0
    proc = subprocess.run(argv, input=raw, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.buffer.write(proc.stderr)
        return proc.returncode
    resp = json.loads(proc.stdout)
    if cls == "capabilities":
        out = resp["output"]
        out["name"] = "base-grade control (" + out.get("name", "?") + ")"
        out["grade"] = "base"
        out["classes"] = [c for c in out["classes"] if c != "ski-run"]
    print(json.dumps(resp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
