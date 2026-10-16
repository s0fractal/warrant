#!/usr/bin/env python3
"""What the witness recorded: refusals, asked-then-executed calls, open asks.

Reads the local store written by witness.py, and asks the warrant CLI to verify
it, so the listing never shows a record the verifier would not stand behind
without saying so.

USAGE
    python3 decisions.py [--hours N] [--json]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from witness import home  # noqa: E402


def cli():
    cand = os.environ.get("WARRANT_CLI")
    if cand:
        return [sys.executable, cand] if cand.endswith(".py") else [cand]
    found = shutil.which("warrant")
    return [found] if found else None


def load(store):
    recs = {}
    for p in (store / "records").glob("*.json"):
        try:
            recs[p.stem] = json.loads(p.read_text(encoding="utf-8"))["body"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return recs


def subject_doc(store, body):
    try:
        return json.loads((store / "blobs" / body["subject"]["hash"]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def verify(store, argv):
    if argv is None:
        return {"status": "UNRUN", "detail": "warrant CLI not found (pipx install warrant-verify)"}
    r = subprocess.run(argv + ["--store", str(store), "verify", "--store-mode", "--json"],
                       capture_output=True, text=True)
    try:
        rep = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"status": "UNRUN", "detail": (r.stderr or r.stdout).strip()[:200]}
    return {"status": "OK" if rep.get("errors") == 0 else "ERRORS",
            "records": rep.get("records"), "errors": rep.get("errors"),
            "warnings": rep.get("warnings")}


def report(hours):
    h = home()
    store = h / "store"
    since = time.time() - hours * 3600
    recs = load(store) if (store / "records").is_dir() else {}
    rows = []
    for wid, body in recs.items():
        if body.get("decision") not in ("accept", "reject") or body.get("ts", 0) < since:
            continue
        prior = recs.get((body.get("prior") or [None])[0], {})
        subj = subject_doc(store, prior) if prior else {}
        reasons = [b.get("text") for b in body.get("because", []) if b.get("kind") == "prose"]
        rows.append({"warrant_id": wid, "ts": body.get("ts"),
                     "outcome": "denied" if body["decision"] == "reject" else "asked, then executed",
                     "tool": subj.get("tool_name"), "tool_use_id": subj.get("tool_use_id"),
                     "input": json.dumps(subj.get("tool_input"), ensure_ascii=False)[:160],
                     "reason": reasons[0] if reasons else None})
    rows.sort(key=lambda r: r["ts"] or 0, reverse=True)
    open_asks = []
    for p in (h / "pending").glob("*.json"):
        try:
            n = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if n.get("asked_at", 0) >= since:
            open_asks.append({"asked_at": n.get("asked_at"), "tool": n.get("tool_name"),
                              "input": n.get("summary"),
                              "outcome": "asked, no execution observed (denied by hand, "
                                         "interrupted or still open)"})
    open_asks.sort(key=lambda r: r["asked_at"] or 0, reverse=True)
    return {"store": str(store), "hours": hours, "verify": verify(store, cli()),
            "decisions": rows, "open_asks": open_asks}


def fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "?"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = report(a.hours)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0
    v = rep["verify"]
    print(f"store: {rep['store']}")
    if v["status"] == "UNRUN":
        print(f"verify: NOT RUN -- {v['detail']}")
    else:
        print(f"verify: {v['records']} records, {v['errors']} errors, {v['warnings']} warnings")
    print(f"\nlast {a.hours:g} h: {len(rep['decisions'])} witnessed decisions, "
          f"{len(rep['open_asks'])} open asks")
    for r in rep["decisions"]:
        print(f"  {fmt_ts(r['ts'])}  {r['outcome']:<22} {r['tool']}  {r['input']}")
        print(f"      {r['reason']}")
        print(f"      warrant {r['warrant_id'][:16]}  tool_use_id {r['tool_use_id']}")
    for r in rep["open_asks"]:
        print(f"  {fmt_ts(r['asked_at'])}  {r['outcome']}")
        print(f"      {r['tool']}  {r['input']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
