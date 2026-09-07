#!/usr/bin/env python3
"""Run one scenario end to end into runs/<S>/: session (with plants), both bundles.

    python3 run.py --scenario S1 --runs <runs dir> --agent-model <model|scripted> --plants PLANTS.json

Writes runs/<S>/work/ (the raw session: pack, state, ledger, session.jsonl,
harness.jsonl, agent-transcript.jsonl), runs/<S>/session-summary.json, and
runs/<S>/PACK, runs/<S>/LOG. Adjudications go under runs/<S>/<COND>/<name>/
via adjudicate.py; scoring via score.py after the reveal.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from common import HERE, SUMMARY, inside, model_id   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=["S1", "S2"]); ap.add_argument("--runs", required=True)
    ap.add_argument("--agent-model", required=True); ap.add_argument("--plants", required=True)
    a = ap.parse_args()
    runs = inside(a.runs, "runs dir"); sd = runs / a.scenario; work = sd / "work"
    plants = inside(a.plants, "plants file", must_exist=True); model = model_id(a.agent_model)
    if sd.exists():
        sys.exit(f"{sd} exists; the protocol has no partial re-runs -- remove the whole runs dir to start over")
    work.mkdir(parents=True)
    r = subprocess.run([sys.executable, str(HERE / "agent.py"), "--scenario", a.scenario, "--workdir", str(work),
                        "--model", model, "--plants", str(plants)], capture_output=True, text=True)
    (sd / "agent.stderr.txt").write_text(r.stderr)
    if r.returncode != 0:
        (sd / SUMMARY).write_text(json.dumps({"outcome": "agent_failed", "exit": r.returncode}))
        print(f"agent failed (exit {r.returncode}); kept as an observation in {sd}")
        return 1
    shutil.copy(work / SUMMARY, sd / SUMMARY)
    dispute = json.load(open(plants))[a.scenario]["dispute"]
    subprocess.run([sys.executable, str(HERE / "bundles.py"), "--workdir", str(work), "--scenario", a.scenario,
                    "--dispute", dispute, "--out", str(sd)], check=True)
    print(f"{a.scenario}: session + bundles in {sd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
