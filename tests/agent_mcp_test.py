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

from agent_world import Config, R, api, check, finish, reviewed_work, views, world

# The modules of the tree under test (WARRANT_IMPL for mutants), run as the console scripts run them.
IMPL = os.environ.get("WARRANT_IMPL") or str(Path(__file__).resolve().parents[1])
# IMPL first; a PYTHONPATH the run already has stays after it (the line tracer of
# tests/generated_mutants.py coverage reaches the server through it).
ENV = dict(os.environ, PYTHONPATH=os.pathsep.join([IMPL] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])))
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
        try:                       # communicate() closes stdin itself (EOF ends the server)
            out, err = self.p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
            out, err = self.p.communicate()
        self.lines += out.splitlines(keepends=True)
        return err


def tool_calls(cfg_path, calls):
    """[(tool, arguments)] through one SDK session; each result as tool_json gives it (an exception becomes
    {"exception": ...}, so a case reports FAIL instead of ending the suite)."""
    async def body(s):
        out = []
        for name, args in calls:
            try:
                out.append(tool_json(await s.call_tool(name, args)))
            except Exception as e:          # noqa: BLE001 - recorded as the case's failure
                out.append({"exception": repr(e)})
        return out
    return asyncio.run(sdk_session(cfg_path, "modern", body))[1]


def guarded(fn):
    """Run one case's body; an exception is that case's failure, not the suite's."""
    try:
        return fn()
    except Exception as e:                  # noqa: BLE001
        return {"exception": repr(e)}


def first_contact_cases(src, rcv, ids, cfg_path, cfg):
    """M06-M14: what a fresh agent needs from the first call (examples/mcp-first-contact, round 1)."""
    from warrant_agent import handoff
    from warrant_agent.errors import AgentError
    doc = json.loads(cfg_path.read_text())
    # a closure waiting for an acceptance, and an acceptance that names `reviewer` but is signed by `producer`
    ev = src.blob(b"ran it once\n")
    pd = src.file("duty", "producer", 150, R.duty("producer", "the cache is warm", ["reviewer"], {"attest": {}},
                                                  accept_by=["reviewer"]))
    pt = src.file("transition", "producer", 160, R.transition("ATTESTED", [ev], closes=[R.item(pd, "discharge", [ev])],
                                                              established=["the cache is warm"], residual=[]))
    forged = src.store.put_record(R.record("accept", "reviewer", 170, R.accept(pt, 0, [ev])), src.keys["producer"])

    # M06: the overview names the operator's handles and nothing that selects a file or a key
    r = tool_calls(cfg_path, [("warrant_workspace", {})])[0]
    ws = {w["name"]: w for w in r.get("ok", {}).get("data", {}).get("workspaces", [])}
    text = json.dumps(r)
    secrets_ = [doc["state"], src.doc["workspaces"]["src"]["signer"]["key"], src.keys["producer"].seed_hex()] + \
        [w[k] for w in doc["workspaces"].values() for k in ("store", "trust", "profile")]
    check("M06", set(ws) == {"src", "rcv"} and ws["src"]["signer"] == "producer"
          and ws["src"]["default_use"] == next(iter(doc["workspaces"]["src"]["uses"]))
          and set(ws["src"]["uses"]) == set(doc["workspaces"]["src"]["uses"])
          and {x["id"] for x in ws["src"]["index"]["rows"]} >= {ids["duty"], ids["transition"], pd, pt}
          and not any(x in text for x in secrets_),
          "the overview names workspaces, signer actor, uses, expectations and records; no path or key",
          {k: (v["signer"], v["default_use"]) for k, v in ws.items()})

    # M07: a bare id is a duty or transition of THIS view; any other id is refused by what it is
    r = tool_calls(cfg_path, [("warrant_context", {"workspace": "src", "targets": [ids["duty"], {"id": ids["transition"]}]}),
                              ("warrant_context", {"workspace": "src", "targets": [ids["accept"]]}),
                              ("warrant_context", {"workspace": "src", "targets": ["ab" * 32]}),
                              ("warrant_context", {"workspace": "src", "targets": [{"record": ids["duty"]}]})])
    kinds = [c["kind"] for c in r[0].get("ok", {}).get("data", {}).get("capsules", [])]
    check("M07", kinds == ["duty", "transition"]
          and r[1].get("error") == "BAD_REQUEST" and r[1].get("details", {}).get("type") == "accept"
          and r[2].get("error") == "NOT_FOUND" and r[3].get("error") == "BAD_REQUEST",
          "targets by bare id resolve to duty/transition; an accept id and an unknown id are refused",
          (kinds, r[1].get("error"), r[1].get("details"), r[2].get("error")))

    # M08: a capsule shows every closure attempt with the engine's own verdict and why
    r = tool_calls(cfg_path, [("warrant_context", {"workspace": "src", "targets": [pd, pt]})])[0]
    caps = {c["target"]: c for c in r.get("ok", {}).get("data", {}).get("capsules", [])}
    rep = views.load(Config(doc).workspace("src"), r["ok"]["view_token"])[1] \
        if "ok" in r else {"duties": {pd: {"candidates": []}}}
    cand = rep["duties"][pd]["candidates"]
    dcl, tcl = caps.get(pd, {}).get("closures", []), caps.get(pt, {}).get("closes", [])
    check("M08", len(cand) == 1 and cand[0]["verdict"] == "PENDING"
          and dcl == [{k: cand[0][k] for k in ("transition", "item", "act", "filer", "basis", "verdict", "why",
                                                "waiting_for", "awaiting") if k in cand[0]}]
          and len(tcl) == 1 and tcl[0]["duty"] == pd and tcl[0]["verdict"] == "PENDING" and tcl[0]["why"] == cand[0]["why"]
          and tcl[0]["waiting_for"] == ["reviewer"] and tcl[0]["awaiting"] == [["reviewer"]]
          and tcl[0]["duty_disposition"] == "OPEN",
          "a pending closure is visible on the duty and on the transition with the engine's verdict and why",
          (dcl, tcl))

    # M09: without use or actor the operator's first configured use and the signer's actor apply
    doc2 = json.loads(json.dumps(doc))
    doc2["workspaces"]["src"]["uses"] = dict(reversed(list(doc2["workspaces"]["src"]["uses"].items())))
    cfg2 = cfg_path.with_name("mcp-config-m09.json")
    cfg2.write_text(json.dumps(doc2))
    first = next(iter(doc2["workspaces"]["src"]["uses"]))
    r = tool_calls(cfg2, [("warrant_context", {"workspace": "src"}),
                          ("warrant_context", {"workspace": "src", "use": "no-such-use"})])
    ok = r[0].get("ok", {})
    check("M09", first != "continue" and ok.get("use", {}).get("name") == first
          and r[1].get("error") == "BAD_REQUEST" and r[1].get("details", {}).get("configured") == list(doc2["workspaces"]["src"]["uses"]),
          "the default use is the operator's first configured one; an unknown use lists the configured ones",
          (ok.get("use", {}).get("name"), r[1]))

    # M10: an export root of another kind is a typed refusal, through the MCP door and in handoff.export itself
    r = tool_calls(cfg_path, [("warrant_handoff", {"op": "export", "workspace": "src",
                                                   "roots": [{"kind": "record", "id": ids["duty"]}]})])[0]
    token = api.call(cfg, "context", {"workspace": "src", "targets": [ids["duty"]]})["ok"]["view_token"]

    def direct():
        try:
            handoff.export(cfg.workspace("src"), token, [{"kind": "record", "id": ids["duty"]}], "m10")
        except AgentError as e:
            return e.code
        return "exported"
    d = guarded(direct)
    check("M10", r.get("error") == "BAD_REQUEST" and d == "BAD_REQUEST",
          "an export root that is not a duty or transition is refused as BAD_REQUEST, never an untyped crash", (r, d))

    # M11: a received package in one piece is the same inspection as its parts; capsules default to its roots;
    # an invalid record is named with what it claims to be
    pkg = api.call(cfg, "handoff", {"op": "export", "workspace": "src", "view_token": token,
                                    "roots": [{"kind": "duty", "id": pd}, {"kind": "duty", "id": ids["duty"]}],
                                    "request_id": "m11"})["ok"]["data"]
    doc3 = json.loads(json.dumps(doc))
    doc3["state"] = str(Path(doc["state"]).with_name("mcp-state-m11"))
    doc3["workspaces"]["rcv"]["expectations"] = {"from-src": {"manifest": pkg["manifest_digest"], "source": "src",
                                                                  "exporter": "producer"}}
    cfg3 = cfg_path.with_name("mcp-config-m11.json")
    cfg3.write_text(json.dumps(doc3))
    p = pkg["package"]
    r = tool_calls(cfg3, [("warrant_handoff", {"op": "inspect", "workspace": "rcv", "package": p, "expectation": "from-src"})])
    parts = api.call(Config.load(cfg3), "handoff", {"op": "inspect", "workspace": "rcv", "manifest": p["manifest"],
                                                    "payload": p["payload"], "declaration": p["declaration"],
                                                    "expectation": "from-src"}).get("ok", {})
    one = r[0].get("ok", {})

    def verdicts(res):               # the assessment id carries the moment of assessment; the verdicts do not
        return [(c["target"], c["reliance"], c["disposition"]) for c in res.get("data", {}).get("capsules", [])]
    inv = one.get("data", {}).get("boundary", {}).get("invalid", [])
    check("M11", one and one["data"]["staged_id"] == parts.get("data", {}).get("staged_id")
          and verdicts(one) == verdicts(parts) and one["delivery"] == parts.get("delivery")
          and one["delivery"]["relation"] == "MATCH_EXPECTED_SET"
          and [c["target"] for c in one["data"]["capsules"]] == [r_["id"] for r_ in p["manifest"]["roots"]]
          and [(i["id"], i.get("claims_to_be", {}).get("actor"), i.get("claims_to_be", {}).get("transition"))
               for i in inv] == [(forged, "reviewer", pt)],
          "package in one piece = its parts; capsules default to the package's roots; the forged accept is named",
          (one.get("delivery", {}).get("relation"), inv, verdicts(one), verdicts(parts)))

    # M12: a record is read without a view token from a new view; a context page needs its own view
    r = tool_calls(cfg_path, [("warrant_read", {"workspace": "src", "target": ids["transition"]}),
                              ("warrant_read", {"workspace": "src", "kind": "context"})])
    got = r[0].get("ok", {})
    stored = (src.ws.store / "records" / f"{ids['transition']}.json").read_bytes()
    check("M12", got.get("data", {}).get("content", "").encode() == stored and got.get("view_token") != token
          and len(got.get("view_token", "")) == 32 and r[1].get("error") == "BAD_REQUEST",
          "a record read without a view token comes from a new frozen view; a context page is refused without one",
          (got.get("view_token"), r[1]))

    # M13: without a request id the same body is the same draft; an invalid body shows its type's template
    body = {"basis": "ATTESTED", "established": ["m13 ran"], "residual": ["nothing else was checked"]}
    r = tool_calls(cfg_path, [("warrant_prepare", {"workspace": "src", "type": "transition", "body": body}),
                              ("warrant_prepare", {"workspace": "src", "type": "transition", "body": body}),
                              ("warrant_prepare", {"workspace": "src", "type": "transition",
                                                   "body": dict(body, established=["m13 ran twice"])}),
                              ("warrant_prepare", {"workspace": "src", "type": "transition", "body": {"established": ["x"]}})])
    ids3 = [x.get("ok", {}).get("data", {}).get("draft_id") for x in r[:3]]
    tpl = r[3].get("details", {}).get("template", {})
    check("M13", ids3[0] and ids3[0] == ids3[1] and ids3[2] and ids3[2] != ids3[0]
          and r[0]["ok"]["data"]["record"]["body"]["closes"] == [] and r[3].get("error") == "BAD_REQUEST"
          and {"basis", "established", "residual"} <= set(tpl),
          "the same body without a request id is the same draft; an invalid body is refused with a template",
          (ids3, r[3]))

    # M15: stored bytes that are not a record's shape (Codex P2 on 7a56a56) are listed as invalid, never read
    # as records: context, workspace and read stay ordinary results, with master's invalid count
    import hashlib
    import shutil
    vec = [b'{"record":[]}', b'[]', b'"x"', b'{"record":{"type":5}}', b'{"record":{"type":"duty"', b'\xff\xfe\x00',
           b'{"record":null}', b'{"record":{"body":{},"type":[]}}', b'{"record":{"body":null,"type":"duty"}}']
    doc5 = json.loads(json.dumps(doc))
    store5 = Path(doc["state"]).with_name("store-m15")
    shutil.copytree(src.ws.store, store5)
    doc5["state"] = str(Path(doc["state"]).with_name("mcp-state-m15"))
    doc5["workspaces"]["src"]["store"] = str(store5)
    cfg5 = cfg_path.with_name("mcp-config-m15.json")
    cfg5.write_text(json.dumps(doc5))
    before = api.call(Config.load(cfg5), "context", {"workspace": "src"})["ok"]["data"]["boundary"]["invalid_records"]
    bad = []
    for v in vec:
        h = hashlib.sha256(v).hexdigest()
        bad.append(h)
        (store5 / "records" / f"{h}.json").write_bytes(v)
    r = tool_calls(cfg5, [("warrant_context", {"workspace": "src", "targets": [ids["duty"]]}),
                          ("warrant_workspace", {"workspace": "src"}),
                          ("warrant_read", {"workspace": "src", "target": bad[0]}),
                          ("warrant_context", {"workspace": "src", "targets": [bad[0]]})])
    b5 = r[0].get("ok", {}).get("data", {}).get("boundary", {})
    w5 = (r[1].get("ok", {}).get("data", {}).get("workspaces") or [{}])[0]
    listed = {i["id"] for i in b5.get("invalid", [])}
    check("M15", b5.get("invalid_records") == before + len(vec) and listed >= set(bad)
          and all("claims_to_be" not in i for i in b5.get("invalid", []) if i["id"] in bad)
          and [c["target"] for c in r[0].get("ok", {}).get("data", {}).get("capsules", [])] == [ids["duty"]]
          and w5.get("store", {}).get("invalid_records") == before + len(vec)
          and not {x["id"] for x in w5.get("index", {}).get("rows", [])} & set(bad)
          and r[2].get("ok", {}).get("data", {}).get("content") == vec[0].decode()
          and r[3].get("error") == "BAD_REQUEST" and r[3].get("details", {}).get("type") == "unreadable",
          "malformed stored bytes are listed as invalid by context and counted by workspace; nothing crashes",
          (b5.get("invalid_records"), before, w5.get("store"), r[2].get("error"), r[3].get("error"), r[3].get("details")))

    # M14: explain is static: a known word has its meaning and what it does not establish
    r = tool_calls(cfg_path, [("warrant_explain", {"term": "UNVERIFIED"}), ("warrant_explain", {"term": "nonsense"})])
    k, u = r[0].get("ok", {}).get("data", {}), r[1].get("ok", {}).get("data", {})
    check("M14", k.get("means") and k.get("does_not_establish") and u.get("unknown") is True and "UNVERIFIED" in u.get("terms", []),
          "explain gives a meaning and its limit for a known word, the known words for an unknown one", (k, u))

    # M16: every word a result can answer with is one explain knows: each refusal code, each delivery
    # relation, each reliance state and each use state (at c4e6c94 four refusal codes had none)
    from warrant import engine as E
    from warrant_agent import config as CF, errors
    words = list(errors.CODES) + list(CF.RELATIONS) + list(E.RELIANCE) + ["WITHIN_POLICY", "HOLD", "UNATTESTED"]
    unknown = [t for t in words if api.call(cfg, "explain", {"term": t}).get("ok", {}).get("data", {}).get("unknown")]
    via_mcp = tool_calls(cfg_path, [("warrant_explain", {"term": "CURSOR_MISMATCH"})])[0].get("ok", {}).get("data", {})
    check("M16", unknown == [] and via_mcp.get("means"),
          "every refusal code, delivery relation, reliance state and use state has a meaning in explain", unknown)


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
        r = tool_json(await s.call_tool("warrant_read", {"workspace": "src", "view_token": token,
                                                         "kind": "record", "target": ids["transition"]}))
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
        b = tool_json(await s.call_tool("warrant_handoff", {"op": "inspect", "workspace": "src",
                                                            "manifest": {}, "payload": {"blobs": "x"}}))
        c = tool_json(await s.call_tool("warrant_read", {"workspace": "src", "kind": "draft", "target": "x"}))
        d = await s.call_tool("no_such_tool", {})
        e = tool_json(await s.call_tool("warrant_read", {"workspace": "src", "view_token": token,
                                                         "kind": "record", "target": ids["transition"]}))
        return a, b, c, d, e
    _, (a, b, c, d, e) = asyncio.run(sdk_session(cfg_path, "modern", bad))
    # the interface version is checked by the backend every front end shares (the MCP tools carry none)
    v = api.call(cfg, "read", {"workspace": "src", "kind": "draft", "target": "x", "agent_api": "warrant-agent/9"})
    check("M02", a.get("error") == "BAD_REQUEST" and b.get("error") == "BAD_REQUEST"
          and c.get("error") == "BAD_REQUEST" and v.get("error") == "UNSUPPORTED_VERSION" and d.is_error and "ok" in e,
          "typed refusals, an unknown tool is an error, and the control still answers",
          (a.get("error"), b.get("error"), c.get("error"), v.get("error"), d.is_error))

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
              "params": {"name": "warrant_read", "arguments": {"workspace": "src", "kind": "draft",
                                                               "target": p2["draft_id"]}}})
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
    first_contact_cases(src, rcv, ids, cfg_path, cfg)
    out_dir = os.environ.get("WARRANT_MCP_MATRIX")
    if out_dir:
        Path(out_dir).write_text(json.dumps({"sdk": "mcp==2.3.0", "handshake": matrix, "modern_discover": v2,
                                             "stderr_tail": stderr[-400:]}, indent=1))
    return finish("AGENT-MCP")


if __name__ == "__main__":
    sys.exit(main())
