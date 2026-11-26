"""`warrant-agent` — the command-line front end of warrant-agent/3.

    warrant-agent [--config CONFIG.json | --repo DIR --actor A [--seed SEED]] <operation> [REQUEST.json | - | '{...}']
    warrant-agent rely ADDRESS WHAT [--json]       # may I rely on WHAT in the store at ADDRESS? (no workspace needed)
    warrant-agent anchor witness|check --of ADDRESS  # anchor a store read by its address in this one (warrant_agent/anchor.py)

Operations: workspace, context, read, graph, across, handoff, prepare, commit, explain. The request is the same
JSON object the Python API and the MCP tools take; the output is the same result object. Exit status 0
on a result, 2 on a typed refusal."""
import argparse
import json
import sys
from pathlib import Path

from . import api, init
from .errors import AgentError


def _request(arg):
    if arg is None or arg == "-":
        return json.loads(sys.stdin.read() or "{}")
    if arg.lstrip().startswith("{"):
        return json.loads(arg)
    return json.loads(Path(arg).read_text())  # NOSONAR S8707: the operator's argument; MCP requests never come here


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    if args[:1] == ["anchor"]:                # a store by its address, anchored in the checkout's own (warrant.anchor)
        from . import anchor
        from warrant.repo import main as run_main
        return run_main(anchor.run, args[1:])
    if args[:1] == ["rely"]:                  # needs no workspace: an address and a question (warrant_agent/rely.py)
        from . import rely
        return rely.main(args[1:])
    ap = argparse.ArgumentParser(prog="warrant-agent", description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    init.add_arguments(ap)
    ap.add_argument("operation", choices=sorted(api.OPERATIONS_))
    ap.add_argument("request", nargs="?")
    a = ap.parse_args(args)
    try:
        out = api.call(init.load(ap, a), a.operation, _request(a.request))
    except AgentError as e:
        out = e.to_json()
    except init.Refused as e:
        out = {"error": e.code, "message": e.message}
    except (OSError, ValueError) as e:
        out = {"error": "BAD_REQUEST", "message": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(out, sort_keys=True, indent=1, ensure_ascii=False) + "\n")
    return 0 if "ok" in out else 2


if __name__ == "__main__":
    sys.exit(main())
