"""`warrant-agent` — the command-line front end of warrant-agent/1.

    warrant-agent --config CONFIG.json <operation> [REQUEST.json | - | '{...}']
    warrant-agent --config CONFIG.json gc [--workspace NAME] [--dry-run]

Operations: workspace, context, read, handoff, prepare, commit, compute, explain. The request is the
same JSON object the Python API and the MCP tools take; the output is the same
result object. Exit status 0 on a result, 2 on a typed refusal.

`gc` is the operator's command, not an operation of the interface: for each workspace (or the one
named) it removes the views that have expired and the objects no live view pins (views.collect),
waiting for every capture in flight; --dry-run reports what it would remove."""
import argparse
import json
import sys
from pathlib import Path

from . import api, views
from .config import Config
from .errors import AgentError


def _request(arg):
    if arg is None or arg == "-":
        return json.loads(sys.stdin.read() or "{}")
    if arg.lstrip().startswith("{"):
        return json.loads(arg)
    return json.loads(Path(arg).read_text())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="warrant-agent", description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="the operator's configuration (never chosen by a request)")
    ap.add_argument("operation", choices=sorted([*api.OPERATIONS, "gc"]))
    ap.add_argument("request", nargs="?")
    ap.add_argument("--workspace", help="gc: only this workspace")
    ap.add_argument("--dry-run", action="store_true", help="gc: report, remove nothing")
    a = ap.parse_args(argv)
    if a.operation != "gc" and (a.workspace or a.dry_run):
        ap.error("--workspace and --dry-run belong to gc")
    try:
        cfg = Config.load(a.config)
        if a.operation == "gc":
            names = [cfg.workspace(a.workspace).name] if a.workspace else sorted(cfg.workspaces)
            out = {"ok": {"gc": [views.collect(cfg.workspace(n), dry_run=a.dry_run) for n in names]}}
        else:
            out = api.call(cfg, a.operation, _request(a.request))
    except AgentError as e:
        out = e.to_json()
    except (OSError, ValueError) as e:
        out = {"error": "BAD_REQUEST", "message": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(out, sort_keys=True, indent=1, ensure_ascii=False) + "\n")
    return 0 if "ok" in out else 2


if __name__ == "__main__":
    sys.exit(main())
