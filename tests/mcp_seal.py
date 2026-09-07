#!/usr/bin/env python3
"""Tests for the warrant-mcp sealing proxy.

  A. classifier: config wins; a tool absent from the config is A4 whatever
     its name (hints annotate, never downgrade); an empty effect list is
     refused (2026-09 chatgpt-web review: `query`/`get_and_execute` were A0
     by name, `[]` was A0 by declaration, and neither was ever sealed).
  B. Sealer core: A2+ sealed, A0/A1 skipped, produced pack verifies clean.
  C. stdio proxy: wraps a mock MCP server end to end, forwards traffic
     untouched, seals an undeclared tool, and the pack verifies clean.
  D. seal failure: the stream is still forwarded, and the loss is in the
     manifest (seal_failures, observation_complete=false) and in the exit
     status (3), not only on stderr.
  E. unanswered call: the server performs an effect and exits (cleanly, or
     crashing) without responding. The call is listed as unreturned, the
     pack is marked incomplete, the downstream exit code is recorded, and the
     proxy exits 3 (Codex R1 on PR #63: this path used to report a complete,
     empty pack with exit 0).

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
M = _load("warrant_mcp", "impl/warrant_mcp.py")

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
    chk(M.classify("github.delete_repo", {})[0] == "A4", "undeclared delete -> A4")
    chk(M.classify("fs.read_file", {})[0] == "A4",
        "undeclared read-looking tool -> A4 (a name is not a declaration)")
    chk(M.classify("weird.frobnicate", {})[0] == "A4", "unknown -> A4 (fail-closed)")
    # the review's table, now fail-closed on every row it found open
    for name in ("get_and_execute", "query", "execute_sql"):
        cls, effs, src = M.classify(name, {})
        chk(cls == "A4" and "mcp_tool_undeclared" in effs and src.startswith("undeclared"),
            f"undeclared {name!r} -> A4 via {src}", f"{cls} {effs} {src}")
    cls, effs, src = M.classify("query", {})
    chk(effs == ["mcp_tool_undeclared", "read"], "name hint kept as annotation only", str(effs))
    try:
        M.validate_effects_map({"execute_sql": []})
        chk(False, "empty effect list is refused")
    except ValueError as ex:
        chk("execute_sql" in str(ex), "empty effect list is refused, naming the tool")
    try:
        M.validate_effects_map({"execute_sql": ["write"], "ok": ["read"]})
        chk(True, "non-empty declarations accepted")
    except ValueError as ex:
        chk(False, "non-empty declarations accepted", str(ex))


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
               "repo.delete_file": ["delete"]}     # db.query deliberately undeclared
    effects_path = os.path.join(d, "effects.json")
    open(effects_path, "w").write(json.dumps(effects))
    mock = os.path.join(ROOT, "tests", "fixtures", "mock_mcp_server.py")
    cmd = [sys.executable, os.path.join(ROOT, "impl", "warrant_mcp.py"),
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
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "db.query", "arguments": {"sql": "DROP TABLE t"}}},
    ]
    stdin = "".join(json.dumps(c) + "\n" for c in calls)
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=30)
    # forwarding intact: host sees a response for every request id
    out_ids = {json.loads(l)["id"] for l in proc.stdout.splitlines() if l.strip()}
    chk(out_ids == {1, 2, 3, 4, 5}, "proxy forwards every server response untouched",
        f"got ids {sorted(out_ids)}")
    chk(proc.returncode == 0, "exit 0 when every consequential call was sealed",
        f"rc={proc.returncode} stderr={proc.stderr[-300:]}")
    manifest = json.load(open(os.path.join(d, "manifest.json")))
    chk(manifest["sealed_calls"] == 3,
        "sealed A2+ (write, delete) and the undeclared db.query; not the declared read",
        f"sealed {manifest['sealed_calls']}")
    chk(manifest["seal_failures"] == 0 and manifest["observation_complete"] is True,
        "manifest states the observation is complete")
    store = W.Store(os.path.join(d, ".warrants"))
    errs, _ = W.verify_store(store, quiet=True)
    chk(errs == 0, "proxy-produced evidence pack verifies clean", f"{errs} errors")
    decisions = [store.get_record(w)["body"]["decision"] for w in manifest["records"]]
    chk(decisions == ["accept", "reject", "accept"],
        "write->accept, delete(error)->reject, undeclared query->accept (sealed A4)",
        str(decisions))
    last = store.get_record(manifest["records"][-1])["body"]
    chk("undeclared" in json.dumps(last), "the undeclared call's record says so")


def test_seal_failure():
    d = tempfile.mkdtemp()
    effects = {"repo.write_file": ["source_change"], "repo.read_file": ["read"]}
    s = M.Sealer(os.path.join(d, ".warrants"), "agent@test", keyfile(d), effects, "A2")
    forwarded = []

    class Dst:
        def write(self, raw):
            forwarded.append(raw)

        def flush(self):
            pass
    def broken(raw):
        raise OSError("disk full")
    M._pump_and_forward(["{\"id\": 7}\n"], Dst(), broken,
                        on_error=lambda raw, ex: s.record_failure("repo.write_file", ex))
    chk(forwarded == ["{\"id\": 7}\n"], "stream forwarded despite the seal failure")
    m = s.write_manifest()
    chk(m["seal_failures"] == 1 and m["observation_complete"] is False
        and m["seal_failure_log"][0]["tool"] == "repo.write_file"
        and "disk full" in m["seal_failure_log"][0]["error"],
        "manifest carries the loss: count, tool, error", json.dumps(m["seal_failure_log"]))
    # end to end: a key that cannot sign makes every A2+ seal fail; the proxy
    # must still forward everything and exit 3, with the loss in the manifest
    d2 = tempfile.mkdtemp()
    bad_key = os.path.join(d2, "agent.key")
    open(bad_key, "w").write("not-a-seed\n")
    effects_path = os.path.join(d2, "effects.json")
    open(effects_path, "w").write(json.dumps(effects))
    mock = os.path.join(ROOT, "tests", "fixtures", "mock_mcp_server.py")
    cmd = [sys.executable, os.path.join(ROOT, "impl", "warrant_mcp.py"),
           "--store", d2, "--actor", "agent@test", "--key", bad_key,
           "--effects", effects_path, "--", sys.executable, mock]
    calls = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "repo.read_file", "arguments": {"path": "README"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "repo.write_file", "arguments": {"path": "x", "data": "1"}}},
    ]
    stdin = "".join(json.dumps(c) + "\n" for c in calls)
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=30)
    out_ids = {json.loads(l)["id"] for l in proc.stdout.splitlines() if l.strip()}
    chk(out_ids == {1, 2}, "proxy still forwards every response when sealing fails",
        f"got ids {sorted(out_ids)}")
    chk(proc.returncode == 3, "exit 3: the pack is incomplete", f"rc={proc.returncode}")
    m2 = json.load(open(os.path.join(d2, "manifest.json")))
    chk(m2["sealed_calls"] == 0 and m2["seal_failures"] == 1
        and m2["observation_complete"] is False
        and m2["seal_failure_log"][0]["tool"] == "repo.write_file",
        "manifest: 0 sealed, 1 failure attributed to the write", json.dumps(m2)[:300])
    # an empty declaration is refused before any traffic
    open(effects_path, "w").write(json.dumps({"repo.write_file": []}))
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=30)
    chk(proc.returncode == 2 and "declares no effects" in proc.stderr,
        "empty effect list refused at startup (exit 2)", f"rc={proc.returncode}")


def test_unanswered_call():
    mock = os.path.join(ROOT, "tests", "fixtures", "mock_mcp_server.py")
    for code in (0, 7):
        d = tempfile.mkdtemp()
        marker = os.path.join(d, "effect.marker")
        env = dict(os.environ, MOCK_MCP_SILENT_EXIT=str(code), MOCK_MCP_MARKER=marker)
        cmd = [sys.executable, os.path.join(ROOT, "impl", "warrant_mcp.py"),
               "--store", d, "--actor", "agent@test", "--key", keyfile(d),
               "--", sys.executable, mock]
        calls = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "get_and_execute_silent", "arguments": {"sql": "DROP TABLE t"}}},
        ]
        stdin = "".join(json.dumps(c) + "\n" for c in calls)
        proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                              timeout=30, env=env)
        tag = f"server exit {code} without a response"
        chk(os.path.exists(marker), f"[{tag}] the effect really happened (marker written)")
        chk(proc.returncode == 3, f"[{tag}] proxy exits 3", f"rc={proc.returncode}")
        m = json.load(open(os.path.join(d, "manifest.json")))
        chk(m["sealed_calls"] == 0 and m["observation_complete"] is False,
            f"[{tag}] manifest: nothing sealed, observation NOT complete", json.dumps(m)[:200])
        u = m["unreturned_calls"]
        chk(len(u) == 1 and u[0]["tool"] == "get_and_execute_silent" and u[0]["class"] == "A4"
            and u[0]["consequential"] is True,
            f"[{tag}] the unanswered call is listed, classified A4 (undeclared), consequential",
            json.dumps(u))
        chk(m["downstream_returncode"] == code and m["incomplete_because"],
            f"[{tag}] downstream exit code recorded and the reason stated",
            f"{m['downstream_returncode']} {m['incomplete_because']}")
        chk("INCOMPLETE" in proc.stderr, f"[{tag}] stderr says INCOMPLETE")
    # control: the same tool name answered normally is sealed and the pack is complete
    d = tempfile.mkdtemp()
    env = dict(os.environ); env.pop("MOCK_MCP_SILENT_EXIT", None)
    cmd = [sys.executable, os.path.join(ROOT, "impl", "warrant_mcp.py"),
           "--store", d, "--actor", "agent@test", "--key", keyfile(d),
           "--", sys.executable, mock]
    stdin = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "get_and_execute_silent", "arguments": {}}}) + "\n"
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=30, env=env)
    m = json.load(open(os.path.join(d, "manifest.json")))
    chk(proc.returncode == 0 and m["sealed_calls"] == 1 and m["observation_complete"] is True
        and m["unreturned_calls"] == [] and m["downstream_returncode"] == 0,
        "control: answered call -> sealed, complete, exit 0",
        f"rc={proc.returncode} {json.dumps(m)[:200]}")


def main():
    test_classifier()
    test_sealer_core()
    test_stdio_proxy()
    test_seal_failure()
    test_unanswered_call()
    print("\n" + ("MCP-SEAL: ALL PASS" if all(ok) else "MCP-SEAL: FAILURES PRESENT"))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
