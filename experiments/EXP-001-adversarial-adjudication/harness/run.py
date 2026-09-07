#!/usr/bin/env python3
"""Run one scenario end to end into runs/<S>/: session (with plants), both bundles.

    python3 run.py --scenario S1 --runs <runs dir> --agent-model <model|scripted> --plants PLANTS.json [--budget runs/budget.json]

Writes runs/<S>/work/ (the raw session: pack, state, ledger, session.jsonl,
harness.jsonl, agent-transcript.jsonl, proxy.stderr.txt), runs/<S>/session-summary.json,
and runs/<S>/PACK, runs/<S>/LOG. Adjudications go under runs/<S>/<COND>/<name>/
via adjudicate.py; scoring via score.py after the reveal. Everything runs
in-process; the only OS commands are the harness's own fixed scripts.
"""
import argparse
import json
import shutil
import sys
import traceback

import agent
import bundles
from budget import Budget
from common import HERE, SUMMARY, inside, model_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=["S1", "S2"]); ap.add_argument("--runs", required=True)
    ap.add_argument("--agent-model", required=True); ap.add_argument("--plants", required=True)
    ap.add_argument("--budget", help="runs/budget.json (required unless the agent is scripted)")
    a = ap.parse_args()
    runs = inside(a.runs, "runs dir"); sd = runs / a.scenario; work = sd / "work"
    plants_path = inside(a.plants, "plants file", must_exist=True); model = model_id(a.agent_model)
    if sd.exists():
        sys.exit(f"{sd} exists; the protocol has no partial re-runs -- remove the whole runs dir to start over")
    work.mkdir(parents=True)
    scenario = json.load(open(HERE / "scenarios" / f"{a.scenario}.json"))
    plants_all = json.load(open(plants_path))
    schedule = json.load(open(HERE / "schedule.json"))
    budget = None
    if model != "scripted":
        if not a.budget:
            sys.exit("a paid model needs --budget runs/budget.json (the shared, enforced ledger)")
        budget = Budget(inside(a.budget, "budget ledger", must_exist=True))
    try:
        agent.run(scenario, work, model, plants_all.get(a.scenario), budget, schedule)
    except Exception:                                   # kept as an observation, never re-rolled
        (sd / "agent.stderr.txt").write_text(traceback.format_exc())
        (sd / SUMMARY).write_text(json.dumps({"outcome": "agent_failed"}))
        print(f"agent failed; kept as an observation in {sd}")
        return 1
    shutil.copy(work / SUMMARY, sd / SUMMARY)
    bundles.build(work, a.scenario, plants_all[a.scenario]["dispute"], sd)
    print(f"{a.scenario}: session + bundles in {sd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
