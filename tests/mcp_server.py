#!/usr/bin/env python3
"""Tests for warrant-mcp-server (impl/warrant_mcp_server.py).

  A. protocol: initialize / tools/list over real stdio, unknown method -> -32601.
  B. filing: warrant_file_decision propose + accept-with-ski-check land in a
     temp store; warrant_show_reason returns the reasons and RE-EXECUTES the
     ski@v1 check (fresh verdict == filed verdict).
  C. verification: warrant_verify_store returns a clean verify-report@v0
     (ok:true, errors:0); a missing store fails closed (ok:false).
  D. tamper (negative control): one byte changed in a stored record makes the
     same call report ok:false with errors >= 1.

The server is exercised the way a host uses it — a subprocess speaking
newline-delimited JSON-RPC — never by importing server internals. The test's
only imports are warrant.Store/ski_policy, used to COMPILE a ski@v1 check blob
into the store (authoring tooling, not the surface under test).

WHY IT TAKES ARGUMENTS
----------------------
The default run tests this checkout. `--server-cmd` and `--impl` point the same
suite at an INSTALLED copy instead, so the console script a stranger gets from
`pip install warrant-verify` is exercised by the tests rather than assumed to
behave like the file in the tree. Testing only the checkout is how a package
ships a server nobody ever started from the package.

    python3 tests/mcp_server.py                    # this checkout
    python3 tests/mcp_server.py \
        --server-cmd /tmp/venv/bin/warrant-mcp-server \
        --impl /tmp/venv/lib/python3.13/site-packages   # the installed wheel

Nonzero exit on failure.
"""
import argparse
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "impl", "warrant_mcp_server.py")

ok = []


def chk(cond, label, detail=""):
    ok.append(cond)
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")


def _load(name, implroot):
    """Load an authoring module from the artifact under test, not from the tree.

    When `--impl` names a venv's site-packages this loads the INSTALLED
    warrant.py / ski_policy.py, so the ski@v1 blob the test compiles is compiled
    by the same code the installed server will re-execute it with. Loading the
    checkout's copy while testing an installed server would silently make the
    test about two different artifacts at once.
    """
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(implroot, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class Client:
    """Minimal MCP host: newline-delimited JSON-RPC 2.0 over the server's stdio."""

    def __init__(self, argv):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1)
        self.next_id = 1

    def request(self, method, params=None, timeout=60):
        mid = self.next_id
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"server closed stdout on {method}")
        resp = json.loads(line)
        assert resp.get("id") == mid, f"response id mismatch: {resp}"
        return resp

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def call_tool(self, name, arguments=None):
        resp = self.request("tools/call",
                            {"name": name, "arguments": arguments or {}})
        if "error" in resp:                   # protocol error (e.g. unknown tool)
            return None, resp["error"]["message"]
        result = resp["result"]
        payload = result["content"][0]["text"]
        if result.get("isError"):
            return None, payload
        return json.loads(payload), None

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


def main(argv=None):
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--server-cmd",
                    help="command that starts the server under test (e.g. an "
                         "installed `warrant-mcp-server`). Default: this "
                         "checkout's impl/warrant_mcp_server.py")
    ap.add_argument("--impl", default=os.path.join(ROOT, "impl"),
                    help="directory holding warrant.py and ski_policy.py for "
                         "the artifact under test (default: ./impl)")
    args = ap.parse_args(argv)
    server_argv = (shlex.split(args.server_cmd) if args.server_cmd
                   else [sys.executable, SERVER])
    print(f"server under test: {' '.join(server_argv)}")
    print(f"authoring modules: {args.impl}\n")

    d = tempfile.mkdtemp(prefix="warrant-mcp-server-test-")
    store = os.path.join(d, ".warrants")
    key = os.path.join(d, "agent.key")
    open(key, "w").write("c3" * 32 + "\n")
    policy = os.path.join(d, "policy.txt")
    open(policy, "w").write("clause 1: no retroactive application\n")

    c = Client(server_argv + ["--store", store, "--key", key,
                              "--actor", "agent@test"])

    try:
        # A. protocol
        r = c.request("initialize", {"protocolVersion": "2025-06-18",
                                     "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "0"}})
        chk(r["result"]["serverInfo"]["name"] == "warrant"
            and r["result"]["protocolVersion"] == "2025-06-18",
            "initialize returns serverInfo + echoed protocolVersion", str(r))
        c.notify("notifications/initialized")
        r = c.request("tools/list")
        names = sorted(t["name"] for t in r["result"]["tools"])
        chk(names == ["warrant_file_decision", "warrant_show_reason",
                      "warrant_verify_store"],
            "tools/list exposes exactly the three tools", str(names))
        chk(all("inputSchema" in t and t["description"]
                for t in r["result"]["tools"]),
            "every tool carries a description and an inputSchema")
        r = c.request("no/such/method")
        chk(r.get("error", {}).get("code") == -32601,
            "unknown method -> -32601", str(r))
        _, err = c.call_tool("no_such_tool")
        chk(err is not None, "unknown tool -> JSON-RPC error", str(err))

        # B. filing
        res, err = c.call_tool("warrant_file_decision", {
            "decision": "propose", "subject_text": "demo diff\n",
            "note": "PR-42", "policy": policy,
            "reasons": ["utility fns needed"]})
        chk(err is None and res and len(res["warrant_id"]) == 64,
            "propose files and returns a warrant id", str(err or res))
        wid1 = res["warrant_id"]

        # a reject missing its required reason must surface the CLI's refusal
        _, err = c.call_tool("warrant_file_decision", {
            "decision": "reject", "prior": wid1})
        chk(err is not None and "reason" in err,
            "reject without reasons -> honest CLI error", str(err))

        # compile a real ski@v1 predicate into the store (authoring tooling)
        W = _load("warrant", args.impl)
        sp = _load("ski_policy", args.impl)
        check = sp.compile_check(
            sp.And(sp.Fact("within_window", True),
                   sp.Not(sp.Fact("retroactive", False))),
            W.Store(store).put_blob)
        res, err = c.call_tool("warrant_file_decision", {
            "decision": "accept", "prior": wid1,
            "reasons": ["within window, not retroactive"],
            "check": check.blob, "runtime": "ski@v1", "verdict": "pass"})
        chk(err is None and res and len(res["warrant_id"]) == 64,
            "accept with a ski@v1 check files (verdict reproduced at filing)",
            str(err or res))
        wid2 = res["warrant_id"]

        res, err = c.call_tool("warrant_show_reason", {"warrant_id": wid2})
        chk(err is None and res["decision"] == "accept"
            and res["chain_verified"] is True
            and any(x.get("kind") == "prose" for x in res["reasons"]),
            "show_reason returns reasons + verified chain", str(err or res))
        rr = (res or {}).get("reruns") or []
        chk(len(rr) == 1 and rr[0]["runtime"] == "ski@v1"
            and rr[0]["reproduced"] is True and "atp_spent=" in rr[0]["rerun"],
            "ski@v1 reason RE-EXECUTES and reproduces the filed verdict",
            str(rr))
        _, err = c.call_tool("warrant_show_reason", {"warrant_id": "ab" * 32})
        chk(err is not None and "not in store" in err,
            "show_reason on an absent id -> honest error", str(err))

        # C. verification
        report, err = c.call_tool("warrant_verify_store", {})
        chk(err is None and report["report"] == "warrant.verify-report@v0"
            and report["ok"] is True and report["errors"] == 0
            and report["records"] == 2,
            "store verifies clean: verify-report@v0, ok:true, 2 records",
            str(err or report))
        report, err = c.call_tool("warrant_verify_store",
                                  {"store_path": os.path.join(d, "nowhere")})
        chk(err is None and report["ok"] is False and report["errors"] >= 1,
            "missing store fails closed (store-mode)", str(err or report))

        # D. tamper — the negative control: verification must now report errors
        rec = os.path.join(store, "records", wid1 + ".json")
        raw = open(rec).read()
        assert '"propose"' in raw
        open(rec, "w").write(raw.replace('"propose"', '"accept"', 1))
        report, err = c.call_tool("warrant_verify_store", {})
        chk(err is None and report["ok"] is False and report["errors"] >= 1,
            "tampered record -> ok:false, errors reported", str(err or report))
        chk(any(f["level"] == "ERR" for f in report.get("findings", [])),
            "tamper is an ERR finding, not a warning", str(report))
    finally:
        c.close()

    print("\n" + ("MCP-SERVER: ALL PASS" if all(ok)
                  else "MCP-SERVER: FAILURES PRESENT"))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
