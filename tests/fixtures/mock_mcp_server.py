#!/usr/bin/env python3
"""Minimal mock MCP server for the warrant-mcp proxy test: newline-delimited
JSON-RPC on stdio. `tools/call` echoes an ok result, except a tool whose name
contains "delete", which returns an error result (isError), and -- when the
environment sets MOCK_MCP_SILENT_EXIT -- a tool whose name contains "silent",
for which the server performs an "effect" (writes the file named by
MOCK_MCP_MARKER) and exits with that code WITHOUT responding. That is the
2026-09 review probe: an effect ran, nobody answered."""
import json
import os
import sys


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        msg = json.loads(raw)
        mid = msg.get("id")
        if msg.get("method") == "tools/call":
            name = (msg.get("params") or {}).get("name", "")
            if "pingback" in name.lower():
                # MCP lets the server initiate requests; its id space is its own.
                # Reuse the host's id on purpose -- the collision is the probe.
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": "ping"}) + "\n")
                sys.stdout.flush()
            if "silent" in name.lower() and os.environ.get("MOCK_MCP_SILENT_EXIT"):
                marker = os.environ.get("MOCK_MCP_MARKER")
                if marker:
                    open(marker, "w").write(name + "\n")   # the effect happened
                sys.stdout.flush()
                sys.exit(int(os.environ["MOCK_MCP_SILENT_EXIT"]))
            if "delete" in name.lower():
                resp = {"jsonrpc": "2.0", "id": mid,
                        "result": {"isError": True,
                                   "content": [{"type": "text", "text": "refused: destructive"}]}}
            else:
                resp = {"jsonrpc": "2.0", "id": mid,
                        "result": {"content": [{"type": "text", "text": f"ok:{name}"}]}}
        else:
            resp = {"jsonrpc": "2.0", "id": mid, "result": {}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
