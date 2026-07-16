#!/usr/bin/env python3
"""Tests for the warrant-mcp sealing proxy.

  A. classifier: config wins, name heuristics, unknown -> A4 (fail-closed).
  B. Sealer core: A2+ sealed, A0/A1 skipped, produced pack verifies clean.
  C. stdio proxy: wraps a mock MCP server end to end, forwards traffic
     untouched, and the produced evidence pack verifies clean.

Run: python3 tests/mcp_seal.py   (nonzero exit on any failure)
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("SIGMA_GLYPH", None)


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


W = _load("warrant_impl", "impl/warrant.py")
M = _load("warrant_mcp", "integrations/mcp/warrant_mcp.py")

ok = []


def chk(cond, label, detail=""):
    ok.append(cond)
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")


def keyfile(d):
    p = os.path.join(d, "agent.key")
    open(p, "w").write("c3" * 32 + "\n")
    return p


def test_classifier():
    effects = {"db.query": ["read"], "db.execute": ["source_change"],
               "bank.wire": ["transfer"]}
    chk(M.classify("db.query", effects)[0] == "A0", "config read -> A0")
    chk(M.classify("db.execute", effects)[0] == "A2", "config source_change -> A2")
    chk(M.classify("bank.wire", effects)[0] == "A4", "config transfer -> A4")
    chk(M.classify("github.delete_repo", {})[0] == "A4", "heuristic delete -> A4")
    chk(M.classify("fs.read_file", {})[0] == "A0", "heuristic read -> A0")
    chk(M.classify("weird.frobnicate", {})[0] == "A4", "unknown -> A4 (fail-closed)")


def test_sealer_core():
    d = tempfile.mkdtemp()
    effects = {"repo.read_file": ["read"], "repo.write_file": ["source_change"]}
    s = M.Sealer(os.path.join(d, ".warrants"), "agent@test", keyfile(d), effects, "A2")
    skipped = s.seal("repo.read_file", {"path": "a"}, {"content": "x"}, False, ts=1000)
    w1 = s.seal("repo.write_file", {"path": "a", "data": "y"}, {"ok": True}, False, ts=1001)
    w2 = s.seal("payments.charge", {"amount": 500}, {"isError": True}, True, ts=1002)
    chk(skipped is None, "A0 read is not sealed (below A2 ceiling)")
    chk(w1 and w2, "A2 write and A4 charge are sealed")
    chk(s.records == [w1, w2], "records in order")
    store = W.Store(os.path.join(d, ".warrants"))
    chk(store.get_record(w2)["body"]["prior"] == [w1],
        "second sealed action chains to the first via prior")
    chk(store.get_record(w2)["body"]["decision"] == "reject",
        "errored call sealed as reject")
    s.write_manifest()
    errs, _ = W.verify_store(W.Store(os.path.join(d, ".warrants")), quiet=True)
    chk(errs == 0, "sealer-produced pack verifies clean", f"{errs} errors")


def test_stdio_proxy():
    d = tempfile.mkdtemp()
    effects = {"repo.write_file": ["source_change"], "repo.read_file": ["read"],
               "repo.delete_file": ["delete"]}
    effects_path = os.path.join(d, "effects.json")
    open(effects_path, "w").write(json.dumps(effects))
    mock = os.path.join(ROOT, "tests", "fixtures", "mock_mcp_server.py")
    cmd = [sys.executable, os.path.join(ROOT, "integrations", "mcp", "warrant_mcp.py"),
           "--store", d, "--actor", "agent@test", "--key", keyfile(d),
           "--effects", effects_path, "--", sys.executable, mock]
    calls = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "repo.read_file", "arguments": {"path": "README"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "repo.write_file", "arguments": {"path": "x", "data": "1"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "repo.delete_file", "arguments": {"path": "x"}}},
    ]
    stdin = "".join(json.dumps(c) + "\n" for c in calls)
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=30)
    # forwarding intact: host sees a response for every request id
    out_ids = {json.loads(l)["id"] for l in proc.stdout.splitlines() if l.strip()}
    chk(out_ids == {1, 2, 3, 4}, "proxy forwards every server response untouched",
        f"got ids {sorted(out_ids)}")
    manifest = json.load(open(os.path.join(d, "manifest.json")))
    chk(manifest["sealed_calls"] == 2, "sealed only A2+ (write, delete), not the read",
        f"sealed {manifest['sealed_calls']}")
    store = W.Store(os.path.join(d, ".warrants"))
    errs, _ = W.verify_store(store, quiet=True)
    chk(errs == 0, "proxy-produced evidence pack verifies clean", f"{errs} errors")
    decisions = [store.get_record(w)["body"]["decision"] for w in manifest["records"]]
    chk(decisions == ["accept", "reject"], "write->accept, delete(error)->reject",
        str(decisions))


def main():
    test_classifier()
    test_sealer_core()
    test_stdio_proxy()
    print("\n" + ("MCP-SEAL: ALL PASS" if all(ok) else "MCP-SEAL: FAILURES PRESENT"))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
