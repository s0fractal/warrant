#!/usr/bin/env python3
"""Run fresh headless agents on the adoption tasks and score them (PLAN.md).

    python3 run.py setup                         # the venv with warrant-graph[mcp]==3.0.0a7 and the bin dirs (.work/)
    python3 run.py smoke                         # the one uncounted smoke run: T3, arm A, haiku -> round-smoke/
    python3 run.py round NAME [--arms N,S,A] [--models sonnet,haiku] [--n 3] [--jobs 1]
                                                 # refused unless REGISTERED holds the plan's record id

For every (task, arm, model, k): a fresh fixture in a new temporary directory outside every directory that holds an
instruction file, one `claude -p` process in it, and under NAME/<task>-<arm>-<model>-<k>/ next to this file: the
prompt, the transcript (paths and identities normalized), the fixture summary and the score. A run whose score
exists is skipped, so an interrupted round resumes. The order is a shuffle seeded by the registered record id.
Spend cap: no run starts when the scored runs of every round here (smoke included) plus 0.75 for each run in flight
and the next would exceed $25; a run with no cost reported counts as 0.75.
"""
import argparse
import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import fixture as FX                        # noqa: E402
import scorer as SC                         # noqa: E402

WORK = HERE / ".work"
VENV, KIT, AGENT_BIN = WORK / "venv", WORK / "kit-bin", WORK / "agent-bin"
PACKAGE = "warrant-graph[mcp]==3.0.0a7"
KIT_SCRIPTS = ("warrant", "warrant-agent", "warrant-agent-mcp", "warrant-claims", "warrant-gate", "warrant-review",
               "warrant-roadmap")
CLAUDE = shutil.which("claude") or "/opt/homebrew/bin/claude"
TOOLS = "Bash,Read,Grep,Glob,Edit,Write"
BUDGET, CAP, WALL = 0.75, 25.0, 900          # per run (USD), whole experiment (USD), per run (seconds)
MODELS, ARMS, N = ("sonnet", "haiku"), ("N", "S", "A"), 3
HEX64 = re.compile(r"[0-9a-f]{64}")


def setup():
    """The venv (made once), KIT: links to its console scripts only (so `python3` is the same in every arm), and
    AGENT_BIN: python3/python, the interpreter running this harness, resolved."""
    if not (VENV / "bin" / "warrant").exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        subprocess.run([str(VENV / "bin" / "pip"), "install", "-q", PACKAGE], check=True)
    for d in (KIT, AGENT_BIN):
        d.mkdir(parents=True, exist_ok=True)
    for s in KIT_SCRIPTS:
        if not (KIT / s).is_symlink():
            (KIT / s).symlink_to(VENV / "bin" / s)
    py = os.path.realpath(sys.executable)
    for s in ("python3", "python"):
        if (AGENT_BIN / s).is_symlink():
            (AGENT_BIN / s).unlink()
        (AGENT_BIN / s).symlink_to(py)
    ver = subprocess.run([str(VENV / "bin" / "python"), "-I", "-c",
                          "import importlib.metadata as m; print(m.version('warrant-graph'))"],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert ver == "3.0.0a7", ver
    return ver


def flags(arm, model, mcp, fake_home):
    """The claude -p arguments of one run (everything but the prompt)."""
    allowed = TOOLS + (",mcp__warrant__*" if arm == "A" else "")
    out = ["--model", model, "--setting-sources", "project", "--strict-mcp-config"]
    if arm == "A":
        out += ["--mcp-config", str(mcp)]
    out += ["--tools", TOOLS, "--allowedTools", allowed, "--permission-prompts", "none", "--disable-slash-commands",
            "--settings", json.dumps({"autoMemoryEnabled": False, "env": {"HOME": str(fake_home)}}),
            "--no-session-persistence", "--output-format", "stream-json", "--verbose", "--max-budget-usd", str(BUDGET)]
    return out


def environment(arm, tmp):
    """The claude process's environment, built from nothing: none of the host session's variables. HOME stays the
    operator's because the login lives in the macOS keychain read through it; every tool the agent runs gets the
    run's empty HOME instead (the --settings env)."""
    path = ([str(KIT)] if arm != "N" else []) + [str(AGENT_BIN), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    return {"PATH": ":".join(path), "HOME": os.environ["HOME"], "USER": os.environ.get("USER", ""),
            "LANG": "en_US.UTF-8", "SHELL": "/bin/bash", "TMPDIR": str(tmp)}


# ----------------------------------------------------------------------------- normalization and the leak scan

def normalizer(paths):
    """A function replacing every given (path, name) and every other identity of the machine in a text."""
    home = os.path.realpath(os.environ["HOME"])
    user = os.environ.get("USER", "")
    pairs = []
    for p, name in paths + [(str(HERE), "<exp>"), (home, "~"), (os.environ["HOME"], "~")]:
        for v in {p, os.path.realpath(p), "/private" + p if p.startswith("/var/") else p}:
            pairs.append((v, name))
    pairs.sort(key=lambda kv: -len(kv[0]))
    email = re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.invalid\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

    def norm(text):
        for v, name in pairs:
            text = text.replace(v, name)
        text = email.sub("<email>", text)
        if user and len(user) >= 4:
            text = re.sub(re.escape(user), "<user>", text)
        return text
    return norm


LEAKS = [re.compile(p) for p in (r"sk-ant-[A-Za-z0-9_-]{8,}", r"/Users/", r"/home/[a-z]", r"Bearer [A-Za-z0-9._-]{16,}",
                                 r"ANTHROPIC_API_KEY=\S", r"CLAUDE_CODE_OAUTH_TOKEN=\S", r"refresh_?token",
                                 r"access_?token\"?\s*[:=]")]


def leak_scan(text):
    return sorted({m.group(0)[:40] for rx in LEAKS for m in rx.finditer(text)})


# ----------------------------------------------------------------------------- one run

def one(out_root, task, arm, model, k, budget_gate=None):
    name = f"{task}-{arm}-{model}-{k}"
    out = out_root / name
    if (out / "score.json").is_file():
        return name, json.loads((out / "score.json").read_text()), True
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="adoption-"))
    try:
        repo, home, ctmp = tmp / "repo", tmp / "home", tmp / "tmp"
        home.mkdir()
        ctmp.mkdir()
        summary = FX.build(task, arm, repo)
        summary["verified"] = v = FX.verify(task, arm, repo, KIT)
        if arm != "N" and (v["drift"] != FX.EXPECT[task]["drift"] or v["context_reliance"] != FX.EXPECT[task]["context"]):
            raise RuntimeError(f"{name}: the released CLI does not read the fixture as designed: {v}")
        mcp = tmp / "mcp.json"
        if arm == "A":
            cfg = home / "warrant-agent.json"
            cfg.write_text(json.dumps({"agent_api": "warrant-agent/3", "workspaces": {"repo": {
                "repo": str(repo), "operations": ["context", "read", "graph"]}}}, indent=1))
            mcp.write_text(json.dumps({"mcpServers": {"warrant": {"command": str(KIT / "warrant-agent-mcp"),
                                                                 "args": ["--config", str(cfg)]}}}, indent=1))
        prompt = FX.PROMPTS[task]
        args = [CLAUDE, "-p", prompt, *flags(arm, model, mcp, home)]
        norm = normalizer([(str(repo), "<repo>"), (str(home), "<home>"), (str(ctmp), "<tmp>"), (str(tmp), "<run>"),
                           (str(KIT), "<kit>"), (str(AGENT_BIN), "<bin>"), (str(WORK), "<work>")])
        t0 = time.time()
        raw = tmp / "transcript.raw.jsonl"
        errf = tmp / "stderr.txt"
        with open(raw, "w") as fh, open(errf, "w") as eh:
            p = subprocess.Popen(args, cwd=repo, stdin=subprocess.DEVNULL, stdout=fh, stderr=eh,
                                 env=environment(arm, ctmp), start_new_session=True)
            try:
                rc = p.wait(timeout=WALL)
            except subprocess.TimeoutExpired:
                rc = "timeout"
            try:                                    # the process group: claude and whatever it started (the MCP server)
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            p.wait()
        err = errf.read_text(errors="replace")
        wall = round(time.time() - t0, 1)
        text = norm(raw.read_text(errors="replace"))
        (out / "transcript.jsonl").write_text(text)
        (out / "prompt.md").write_text(prompt)
        changed = subprocess.run(["git", "-C", str(repo), "status", "--short"], capture_output=True, text=True).stdout
        diff = subprocess.run(["git", "-C", str(repo), "diff"], capture_output=True, text=True).stdout
        summary.update(changed_files=norm(changed), wall_s=wall, exit=rc, stderr=norm(err or "")[-1500:],
                       argv=[norm(a) for a in args[3:]])
        (out / "fixture.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
        if diff:
            (out / "agent.diff").write_text(norm(diff))
        s = SC.score(task, arm, SC.events(out / "transcript.jsonl"), summary["answers"])
        s.update(run=name, model_alias=model, exit=rc, wall_s=wall,
                 leaks=leak_scan(text + json.dumps(summary) + norm(diff)))
        (out / "score.json").write_text(json.dumps(s, indent=1, sort_keys=True) + "\n")
        return name, s, False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def spent():
    total = 0.0
    for f in HERE.glob("round-*/*/score.json"):
        c = json.loads(f.read_text()).get("cost_usd")
        total += BUDGET if c is None else c
    return total


def plan_digest():
    return hashlib.sha256((HERE / "PLAN.md").read_bytes()).hexdigest()


def manifest(out_root, registered, arms, models, n):
    claude = subprocess.run([CLAUDE, "--version"], capture_output=True, text=True).stdout.strip()
    doc = {"registered": registered, "plan_sha256": plan_digest(), "entry_sha256":
           hashlib.sha256(FX.ENTRY.read_bytes()).hexdigest(), "claude": claude, "package": PACKAGE,
           "arms": arms, "models": models, "n": n, "budget_per_run": BUDGET, "cap": CAP, "wall_s": WALL,
           "tools": TOOLS}
    out_root.mkdir(exist_ok=True)
    f = out_root / "round.json"
    if f.is_file():
        old = json.loads(f.read_text())
        changed = [k for k in doc if k != "claude" and old.get(k) != doc[k]]
        if changed:
            raise SystemExit(f"{f} differs from this invocation in {changed}: a round resumes only as it started")
    else:
        f.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return doc


def round_(name, arms, models, n, jobs):
    reg = HERE / "REGISTERED"
    rid = reg.read_text().strip() if reg.is_file() else ""
    if not HEX64.fullmatch(rid):
        raise SystemExit("refused: REGISTERED must hold the record id (64 lowercase hex) of the registered plan")
    if not re.fullmatch(r"round-[0-9]+", name):
        raise SystemExit("a round is named round-N")
    out_root = HERE / name
    doc = manifest(out_root, rid, arms, models, n)
    print(f"plan sha256 {doc['plan_sha256']} (compare with the registered record)", flush=True)
    runs = [(t, a, m, k) for t in FX.TASKS for a in arms for m in models for k in range(1, n + 1)]
    random.Random(rid + name).shuffle(runs)
    lock, inflight = threading.Lock(), [0]

    def go(r):
        with lock:
            if (out_root / f"{r[0]}-{r[1]}-{r[2]}-{r[3]}" / "score.json").is_file():
                pass
            elif spent() + BUDGET * (inflight[0] + 1) > CAP:
                return f"{'-'.join(map(str, r))}: NOT STARTED, spend cap ${CAP} (spent ${spent():.2f})", None
            inflight[0] += 1
        try:
            nm, s, skipped = one(out_root, *r)
        finally:
            with lock:
                inflight[0] -= 1
        return nm, s if not skipped else None

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(jobs) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(go, r) for r in runs]):
            nm, s = fut.result()
            if s is None:
                print(f"{nm}" if "NOT STARTED" in nm else f"{nm}: done earlier", flush=True)
            else:
                print(f"{nm}: answered={s['answered']} success={s['success']} wrong_credit={s['wrong_credit']} "
                      f"used_kit={s['used_kit']} cost={s['cost_usd']} leaks={s['leaks']}", flush=True)
    print(f"spent so far ${spent():.2f} of ${CAP}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    sub.add_parser("smoke")
    r = sub.add_parser("round")
    r.add_argument("name")
    r.add_argument("--arms", default=",".join(ARMS))
    r.add_argument("--models", default=",".join(MODELS))
    r.add_argument("--n", type=int, default=N)
    r.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    print(f"warrant-graph {setup()}", flush=True)
    if a.cmd == "smoke":
        if spent() + BUDGET > CAP:
            raise SystemExit("spend cap")
        manifest(HERE / "round-smoke", None, ["A"], ["haiku"], 1)
        nm, s, _ = one(HERE / "round-smoke", "T3", "A", "haiku", 1)
        print(json.dumps(s, indent=1, sort_keys=True))
    elif a.cmd == "round":
        arms, models = a.arms.split(","), a.models.split(",")
        assert set(arms) <= set(ARMS) and set(models) <= set(MODELS), (arms, models)
        round_(a.name, arms, models, a.n, a.jobs)


if __name__ == "__main__":
    main()
