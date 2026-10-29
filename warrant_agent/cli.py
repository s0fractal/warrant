"""`warrant-agent` — the command-line front end of warrant-agent/3.

    warrant-agent --config CONFIG.json <operation> [REQUEST.json | - | '{...}']

Operations: workspace, context, read, graph, handoff, prepare, commit, explain. The request is the same
JSON object the Python API and the MCP tools take; the output is the same result object. Exit status 0
on a result, 2 on a typed refusal."""
import argparse
import json
import sys
from pathlib import Path

from . import api
from .config import Config
from .errors import AgentError


def _request(arg):
    if arg is None or arg == "-":
        return json.loads(sys.stdin.read() or "{}")
    if arg.lstrip().startswith("{"):
        return json.loads(arg)
    return json.loads(Path(arg).read_text())  # NOSONAR S8707: the operator's argument; MCP requests never come here


def main(argv=None):
    ap = argparse.ArgumentParser(prog="warrant-agent", description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="the operator's configuration (never chosen by a request)")
    ap.add_argument("operation", choices=sorted(api.OPERATIONS_))
    ap.add_argument("request", nargs="?")
    a = ap.parse_args(argv)
    try:
        out = api.call(Config.load(a.config), a.operation, _request(a.request))
    except AgentError as e:
        out = e.to_json()
    except (OSError, ValueError) as e:
        out = {"error": "BAD_REQUEST", "message": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(out, sort_keys=True, indent=1, ensure_ascii=False) + "\n")
    return 0 if "ok" in out else 2


if __name__ == "__main__":
    sys.exit(main())
