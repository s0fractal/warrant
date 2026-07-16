#!/usr/bin/env python3
"""Minimal mock MCP server for the warrant-mcp proxy test: newline-delimited
JSON-RPC on stdio. `tools/call` echoes an ok result, except a tool whose name
contains "delete", which returns an error result (isError)."""
import json
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
