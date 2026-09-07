#!/usr/bin/env python3
"""Smoke test of the EXP-001 plumbing, no model: tee_logger -> warrant-mcp ->
shop_server. Asserts the three observers agree on what happened: the merchant
ledger (ground truth), the sealed pack (PACK condition) and the plain log (LOG
condition) -- and that the pack's manifest says the observation was complete."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CALL = "tools/call"
REFUND = "shop.request_refund"


def call(i, name, args):
    return {"jsonrpc": "2.0", "id": i, "method": CALL, "params": {"name": name, "arguments": args}}


def main():
    work = Path(tempfile.mkdtemp(prefix="exp001-smoke-"))
    scen = json.load(open(HERE / "scenarios" / "S1.json"))
    json.dump(scen["state"], open(work / "state.json", "w"))
    (work / "agent.key").write_text("c3" * 32 + "\n")
    pack = work / "pack"
    cmd = [sys.executable, str(HERE / "tee_logger.py"), "--workdir", str(work), "--",
           sys.executable, str(ROOT / "impl" / "warrant_mcp.py"), "--store", str(pack),
           "--actor", "agent@exp001", "--key", str(work / "agent.key"),
           "--effects", str(HERE / "effects.json"), "--",
           sys.executable, str(HERE / "shop_server.py"), "--workdir", str(work)]
    calls = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        call(3, "shop.search_products", {"q": "headphones"}),
        call(4, "shop.add_to_cart", {"sku": "HP-100"}),
        call(5, "shop.checkout", {}),
        call(6, REFUND, {"order": "ORD-0001"}),
        call(7, REFUND, {"order": "ORD-0001"}),
    ]
    stdin = "".join(json.dumps(c) + "\n" for c in calls)
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=60)
    out = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    ok = True
    def chk(c, label, detail=""):
        nonlocal ok; ok &= bool(c); print(("OK  " if c else "FAIL"), label, "" if c else f"-> {detail}")
    chk({m["id"] for m in out} == {1, 2, 3, 4, 5, 6, 7}, "host received every response through both observers")
    chk(len(json.loads(out[1]["result"]["tools"] and json.dumps(out[1]["result"]["tools"]))) == 7, "tools/list served")
    led = [json.loads(l) for l in open(work / "effects.jsonl")]
    chk([e["op"] for e in led] == ["shop.add_to_cart", "shop.checkout", REFUND],
        "merchant ledger: exactly the three mutations (second refund refused, not ledgered)")
    m = json.load(open(pack / "manifest.json"))
    chk(m["sealed_calls"] == 4 and m["observation_complete"] is True and p.returncode == 0,
        "pack: 4 sealed (cart, checkout, refund, refused refund), complete, exit 0", json.dumps(m)[:200])
    log = [json.loads(l) for l in open(work / "session.jsonl")]
    chk(sum(1 for e in log if e["dir"] == "host") == 7 and sum(1 for e in log if e["dir"] == "server") == 7,
        "plain log: 7 host lines, 7 server lines")
    v = subprocess.run([sys.executable, str(ROOT / "impl" / "warrant.py"), "--store", str(pack / ".warrants"), "verify"],
                       capture_output=True, text=True)
    chk(v.returncode == 0, "pack verifies (base grade)", v.stdout[-200:])
    st = json.load(open(work / "state.json"))
    chk(st["orders"]["ORD-0001"]["refunded"] and "ORD-0003" in st["orders"], "state advanced: refund flag set, new order created")
    print("EXP001-SMOKE:", "ALL PASS" if ok else "FAILURES PRESENT")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
