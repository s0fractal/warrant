#!/usr/bin/env python3
"""Run fresh headless agents on the first-contact tasks and score them (PLAN.md).

    python3 run.py ROUND [--tasks t1,t2,t3] [--models sonnet,haiku] [--n 3] [--jobs 3]
                   [--work DIR] [--python PY]

For every (task, model, i): a fresh fixture under WORK/round-ROUND/<task>-<model>-<i>/,
an MCP configuration naming only `warrant-agent-mcp` from PY's environment, one
`claude -p` process with no built-in tools and no settings, its stream-json
transcript copied to round-ROUND/ next to this file with the score. A run whose
score exists is skipped, so an interrupted round resumes.
"""
import argparse
import concurrent.futures
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLAGS = ["--setting-sources", "", "--strict-mcp-config", "--tools", "", "--allowedTools", "mcp__warrant__*",
         "--no-session-persistence", "--output-format", "stream-json", "--verbose", "--max-budget-usd", "1.5"]


def one(rnd, task, model, i, work, py):
    name = f"{task}-{model}-{i}"
    out_dir = HERE / f"round-{rnd}"
    out_dir.mkdir(exist_ok=True)
    if (out_dir / f"{name}.score.json").is_file():
        return name, json.loads((out_dir / f"{name}.score.json").read_text())
    run = Path(work) / f"round-{rnd}" / name
    shutil.rmtree(run, ignore_errors=True)
    subprocess.run([py, "-I", str(HERE / "fixture.py"), task, str(run)], check=True, capture_output=True)
    exe = str(Path(py).parent / "warrant-agent-mcp")
    (run / "mcp.json").write_text(json.dumps({"mcpServers": {"warrant": {
        "command": exe, "args": ["--config", str(run / "config.json")]}}}))
    cwd = Path(work) / "agent-cwd" / f"round-{rnd}" / name
    cwd.mkdir(parents=True, exist_ok=True)
    prompt = (run / "prompt.md").read_text()
    tpath = out_dir / f"{name}.jsonl"
    with open(tpath, "w") as fh:
        p = subprocess.run(["claude", "-p", prompt, "--model", model, "--mcp-config", str(run / "mcp.json"), *FLAGS],
                           cwd=cwd, stdout=fh, stderr=subprocess.PIPE, text=True, timeout=1800, check=False)
    s = subprocess.run([py, "-I", str(HERE / "scorer.py"), str(run), str(tpath)], capture_output=True, text=True)
    if s.returncode != 0:
        raise RuntimeError(f"{name}: scorer failed: {s.stderr[-2000:]}")
    score = dict(json.loads(s.stdout), run=name, model=model, exit=p.returncode, stderr=p.stderr[-500:])
    (out_dir / f"{name}.score.json").write_text(json.dumps(score, indent=1))
    (out_dir / f"{name}.prompt.md").write_text(prompt)
    return name, score


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("round")
    ap.add_argument("--tasks", default="t1,t2,t3")
    ap.add_argument("--models", default="sonnet,haiku")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--work", default=str(Path.home() / "Projects" / ".worktrees" / "mcp-fc-work"))
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args()
    jobs = [(a.round, t, m, i, a.work, a.python) for m in a.models.split(",") for t in a.tasks.split(",")
            for i in range(1, a.n + 1)]
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(one, *j) for j in jobs]):
            name, s = fut.result()
            print(f"{name}: success={s['success']} wrong_credit={s['wrong_credit']} calls={s['tool_calls']} "
                  f"errors={s['tool_errors']} repeated={s['repeated_errors']} cost={s['cost_usd']}", flush=True)


if __name__ == "__main__":
    main()
