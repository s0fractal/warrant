#!/usr/bin/env python3
"""The MCP front end against the same backend (M01-M05), through real stdio
clients: the official SDK client (handshake 2025-11-25 and discover 2026-07-28)
and a raw JSON-RPC client for wire discipline, version matrix and cancellation.

    python3 tests/agent_mcp_test.py        (needs the optional dependency `mcp`)
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from agent_world import api, check, finish, reviewed_work, world

# The modules of the tree under test (WARRANT_IMPL for mutants), run as the console scripts run them.
IMPL = os.environ.get("WARRANT_IMPL") or str(Path(__file__).resolve().parents[1])
ENV = dict(os.environ, PYTHONPATH=IMPL)
SERVER, SERVER_ARGS = sys.executable, ["-m", "warrant_agent.mcp_server"]
CLI = [sys.executable, "-m", "warrant_agent.cli"]


def two_workspace_config(src, rcv):
    doc = {"agent_api": "warrant-agent/1", "state": str(src.base.parent / "mcp-state"),
           "workspaces": {"src": src.doc["workspaces"]["src"], "rcv": rcv.doc["workspaces"]["rcv"]}}
    p = src.base.parent / "mcp-config.json"
    p.write_text(json.dumps(doc))
    return p


async def sdk_session(cfg_path, mode, body):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    params = StdioServerParameters(command=SERVER, args=[*SERVER_ARGS, "--config", str(cfg_path)], env=ENV)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            if mode == "handshake":
                await s.initialize()
            else:
                await s.discover()
            return s.protocol_version, await body(s)


def tool_json(res):
    if res.is_error:                 # the SDK prefixes the refusal's JSON with its own text
        text = res.content[0].text
        return json.loads(text[text.index("{"):])
    text = json.loads(res.content[0].text)
    assert text == res.structured_content, "structured content and its text differ"
    return {"ok": res.structured_content}


def _json(line):
    try:
        msg = json.loads(line)
    except ValueError:
        return {}
    return msg if isinstance(msg, dict) else {}


class Raw:
    """A raw newline-delimited JSON-RPC client over the server's stdio."""

    def __init__(self, cfg_path):
        self.p = subprocess.Popen([SERVER, *SERVER_ARGS, "--config", str(cfg_path)], env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1)
        self.lines = []

    def send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def read_until(self, rid, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            line = self.p.stdout.readline()
            if not line:
                break
            self.lines.append(line)
            msg = _json(line)
            if msg.get("id") == rid:
                return msg
        return None

    def close(self):
        self.p.stdin.close()
        try:
            out, err = self.p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
            out, err = self.p.communicate()
        self.lines += out.splitlines(keepends=True)
        return err


def main():
    src, rcv = world()
    ids = reviewed_work(src)
    cfg_path = two_workspace_config(src, rcv)
    from warrant_agent.config import Config
    cfg = Config.load(cfg_path)
    ctx = api.call(cfg, "context", {"workspace": "src", "actor": "producer", "use": "continue",
                                    "targets": [{"kind": "duty", "id": ids["duty"]}]})["ok"]
    token = ctx["view_token"]
    prep = {"workspace": "src", "based_on": token, "request_id": "m01", "type": "challenge",
            "body": {"target": ids["transition"], "item": 0, "statement": "same through three doors", "evidence": []}}

    # M01: Python, CLI and MCP (both protocol paths) give the same results
    py_prep = api.call(cfg, "prepare", prep)["ok"]["data"]
    cli = json.loads(subprocess.run([*CLI, "--config", str(cfg_path), "prepare", json.dumps(prep)],
                                    capture_output=True, text=True, env=ENV).stdout)["ok"]["data"]
    py_read = api.call(cfg, "read", {"workspace": "src", "view_token": token, "kind": "record",
                                     "target": ids["transition"]})["ok"]["data"]

    async def body(s):
        p = tool_json(await s.call_tool("warrant_prepare", prep))
        c = tool_json(await s.call_tool("warrant_commit", {"workspace": "src", "draft_id": p["ok"]["data"]["draft_id"]}))
        r = tool_json(await s.call_tool("warrant_read", {"request": {"workspace": "src", "view_token": token,
                                                                     "kind": "record", "target": ids["transition"]}}))
        return p, c, r
    v1, (h_prep, h_commit, h_read) = asyncio.run(sdk_session(cfg_path, "handshake", body))
    v2, (m_prep, m_commit, m_read) = asyncio.run(sdk_session(cfg_path, "modern", body))
    stored = (src.ws.store / "records" / f"{py_prep['record_id']}.json").read_bytes()
    same = lambda d: {k: v for k, v in d.items() if k != "status"}                  # noqa: E731
    check("M01", py_prep == cli == h_prep["ok"]["data"] and same(h_prep["ok"]["data"]) == same(m_prep["ok"]["data"])
          and m_prep["ok"]["data"]["status"] == "COMMITTED"
          and h_commit["ok"]["data"]["record_id"] == m_commit["ok"]["data"]["record_id"] == py_prep["record_id"]
          and py_read == h_read["ok"]["data"] == m_read["ok"]["data"] and len(stored) > 0
          and (v1, v2) == ("2025-11-25", "2026-07-28"),
          "Python, CLI and MCP (2025-11-25 and 2026-07-28) give the same draft, record and bytes", (v1, v2))

    # M02: malformed arguments and versions are typed refusals; a control still works
    async def bad(s):
        a = tool_json(await s.call_tool("warrant_commit", {"workspace": "src", "draft_id": "zz"}))
        b = tool_json(await s.call_tool("warrant_handoff", {"request": {"op": "inspect", "workspace": "src",
                                                                        "manifest": {}, "payload": {"blobs": "x"}}}))
        c = tool_json(await s.call_tool("warrant_read", {"request": {"workspace": "src", "kind": "draft",
                                                                     "target": "x", "agent_api": "warrant-agent/9"}}))
        d = await s.call_tool("no_such_tool", {})
        e = tool_json(await s.call_tool("warrant_read", {"request": {"workspace": "src", "view_token": token,
                                                                     "kind": "record", "target": ids["transition"]}}))
        return a, b, c, d, e
    _, (a, b, c, d, e) = asyncio.run(sdk_session(cfg_path, "modern", bad))
    check("M02", a.get("error") == "BAD_REQUEST" and b.get("error") == "BAD_REQUEST"
          and c.get("error") == "UNSUPPORTED_VERSION" and d.is_error and "ok" in e,
          "typed refusals, an unknown tool is an error, and the control still answers",
          (a.get("error"), b.get("error"), c.get("error"), d.is_error))

    # M03 + M04 + cancellation: raw wire, stdout discipline, version matrix
    raw = Raw(cfg_path)
    matrix = {}
    for n, ver in enumerate(("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "1999-01-01")):
        if n:
            raw.close()
            raw = Raw(cfg_path)
        raw.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": ver, "capabilities": {}, "clientInfo": {"name": "raw", "version": "0"}}})
        resp = raw.read_until(1)
        matrix[ver] = (resp or {}).get("result", {}).get("protocolVersion") or (resp or {}).get("error", {}).get("message")
    raw.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    # cancellation: a commit request immediately cancelled; then a new request reads the status
    p2 = api.call(cfg, "prepare", dict(prep, request_id="m-cancel"))["ok"]["data"]
    raw.send({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
              "params": {"name": "warrant_commit", "arguments": {"workspace": "src", "draft_id": p2["draft_id"]}}})
    raw.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 7, "reason": "test"}})
    stderr = raw.close()
    lines = list(raw.lines)
    raw = Raw(cfg_path)               # a new server, a new request: the status comes from the durable draft
    raw.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "raw", "version": "0"}}})
    raw.read_until(1)
    raw.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    raw.send({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
              "params": {"name": "warrant_read", "arguments": {"request": {"workspace": "src", "kind": "draft",
                                                                           "target": p2["draft_id"]}}}})
    st = raw.read_until(8)
    stderr += raw.close()
    raw.lines = lines + raw.lines
    wire_ok = all(_json(line).get("jsonrpc") == "2.0" for line in raw.lines if line.strip())
    status = json.loads(st["result"]["content"][0]["text"])["data"]["status"] if st else None
    on_disk = (src.ws.store / "records" / f"{p2['record_id']}.json").exists()
    answered_7 = any(_json(line).get("id") == 7 for line in raw.lines if line.strip())
    check("M03", wire_ok and len(raw.lines) > 0, "stdout carries only JSON-RPC messages; diagnostics go to stderr",
          [line[:80] for line in raw.lines if not line.startswith("{")][:3])
    check("M04", matrix["2025-11-25"] == "2025-11-25" and matrix["2024-11-05"] == "2024-11-05"
          and matrix["1999-01-01"] in ("2025-11-25",) and v2 == "2026-07-28",
          "measured version matrix: handshake revisions answered as negotiated, an unknown one is countered, "
          "2026-07-28 by discover", matrix)
    check("CANCEL", status == ("COMMITTED" if on_disk else "PREPARED"),
          "after a cancelled commit the status read by a new request matches the store; nothing is rolled back",
          {"status": status, "on_disk": on_disk, "answered_cancelled_request": answered_7})

    # M05: a handle from another workspace grants nothing there
    other_view = api.call(cfg, "read", {"workspace": "rcv", "view_token": token, "kind": "record",
                                        "target": ids["transition"]})
    other_draft = api.call(cfg, "commit", {"workspace": "rcv", "draft_id": py_prep["draft_id"]})
    other_cursor = api.call(cfg, "read", {"workspace": "src", "view_token": token, "kind": "context",
                                          "cursor": "0" * 32 + ":context:producer:1"})
    check("M05", other_view.get("error") == "VIEW_UNKNOWN" and other_draft.get("error") == "NOT_FOUND"
          and other_cursor.get("error") == "CURSOR_MISMATCH",
          "views, drafts and cursors are local selectors, not authority",
          (other_view.get("error"), other_draft.get("error"), other_cursor.get("error")))
    out_dir = os.environ.get("WARRANT_MCP_MATRIX")
    if out_dir:
        Path(out_dir).write_text(json.dumps({"sdk": "mcp==2.3.0", "handshake": matrix, "modern_discover": v2,
                                             "stderr_tail": stderr[-400:]}, indent=1))
    return finish("AGENT-MCP")


if __name__ == "__main__":
    sys.exit(main())
