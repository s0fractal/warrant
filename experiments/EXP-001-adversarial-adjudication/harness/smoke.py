#!/usr/bin/env python3
"""Smoke test of the EXP-001 plumbing, no model: tee_logger -> warrant-mcp ->
shop_server. Asserts the three observers agree on what happened: the merchant
ledger (ground truth), the sealed pack (PACK condition) and the plain log (LOG
condition) -- and that the pack's manifest says the observation was complete."""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import CALL, HERE, REFUND, ROOT   # noqa: E402


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
    fx = fixtures()
    return 0 if (ok and fx) else 1



# ---------------------------------------------------------------------------
# Fixtures for the four findings of Codex's review of PR #64 (R1-R4). Each is
# a disposable harness test: no model, no plants that mean anything.
# ---------------------------------------------------------------------------
import contextlib   # noqa: E402
import importlib.util   # noqa: E402
import io   # noqa: E402
from pathlib import Path as _P   # noqa: E402

EXP = HERE.parent
SCRATCH = EXP / "runs-scratch" / "smoke"


def _mod(name):
    spec = importlib.util.spec_from_file_location("exp_" + name, HERE / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _run(*args):
    p = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, timeout=60)
    return p


def fixtures():
    ok = []

    def chk(c, label, detail=""):
        ok.append(bool(c)); print(("OK  " if c else "FAIL"), label, "" if c else f"-> {detail}")

    shutil.rmtree(SCRATCH, ignore_errors=True); SCRATCH.mkdir(parents=True)
    plants = SCRATCH / "plants.json"
    plants.write_text(json.dumps({"S1": {"plants": [], "decoys": []}, "S2": {"plants": [], "decoys": []}}))
    # R1: every scheduled cell is a row, even with nothing on disk
    runs = SCRATCH / "runs"; runs.mkdir()
    p = _run(HERE / "score.py", "--runs", runs, "--plants", plants)
    rows = json.loads((runs / "scores.json").read_text())
    chk(p.returncode == 0 and len(rows) == 4 and all(r["outcome"] == "missing" and r["session"] == "missing" for r in rows),
        "R1: empty runs dir -> four scheduled cells, all 'missing', exit 0", p.stderr[-200:])
    (runs / "S1").mkdir(); (runs / "S1" / "session-summary.json").write_text(json.dumps({"outcome": "agent_failed", "exit": 1}))
    a = runs / "S1" / "PACK" / "A"; a.mkdir(parents=True); (a / "run.json").write_text('{"outcome": "verdict"}')
    (a / "reply.md").write_text("no json here")
    p = _run(HERE / "score.py", "--runs", runs, "--plants", plants)
    rows = {(r["scenario"], r["condition"]): r for r in json.loads((runs / "scores.json").read_text())}
    chk(p.returncode == 0 and rows[("S1", "PACK")]["session"] == "agent_failed" and rows[("S1", "PACK")]["plants_live"] == "unavailable",
        "R1: agent_failed session -> row kept, plants 'unavailable' (not zero), no crash", p.stderr[-200:])
    (runs / "S1" / "session-summary.json").write_text(json.dumps({"outcome": "completed", "plants": []}))
    p = _run(HERE / "score.py", "--runs", runs, "--plants", plants)
    rows = {(r["scenario"], r["condition"]): r for r in json.loads((runs / "scores.json").read_text())}
    chk(rows[("S1", "PACK")]["outcome"] == "malformed", "R1: a run.json claiming 'verdict' without a valid JSON block scores as malformed")
    # R2: kind 3(b) applied is read from evidence -- performed, and refused
    agent = _mod("agent")
    sc = json.load(open(HERE / "scenarios" / "S1.json"))
    plant3b = {"plants": [{"kind": 3, "variant": "b", "op": REFUND, "args": {"order": "ORD-0002"}}]}
    # performed, then the identical call retried after EOF: the retry never reached the server and must not revoke it
    work = SCRATCH / "silent-performed"; work.mkdir()
    s = agent.Session(sc, work, json.loads(json.dumps(plant3b)))
    s.shop_call(REFUND, {"order": "ORD-0001"})                     # other args: answered normally, its own effect
    s.shop_call(REFUND, {"order": "ORD-0002"})                     # bound call: effect, server exits silently
    retry = s.shop_call(REFUND, {"order": "ORD-0002"})             # identical retry after EOF: driver-side error only
    rc = s.close()
    rec = [x for x in s.applied if x["kind"] == 3][0]
    chk(rc == 3 and rec["applied"] is True and rec["ledgered"] == 1 and rec["answered_ok"] == 0 and "downstream closed" in json.dumps(retry),
        "R2: kind 3(b) performed; identical retry after EOF does not revoke it (applied=True, proxy exit 3)", f"rc={rc} rec={rec}")
    # refused: the order is ALREADY refunded before the server starts, so the silent call has no effect to make
    work = SCRATCH / "silent-refused"; work.mkdir()
    sc_ref = json.loads(json.dumps(sc)); sc_ref["state"]["orders"]["ORD-0002"]["refunded"] = True
    s = agent.Session(sc_ref, work, json.loads(json.dumps(plant3b)))
    s.shop_call(REFUND, {"order": "ORD-0002"})                     # bound call: store refuses, server still exits silently
    rc = s.close()
    rec = [x for x in s.applied if x["kind"] == 3][0]
    chk(rc == 3 and rec["applied"] is False and rec["ledgered"] == 0 and rec["unreturned"] == 1,
        "R2: kind 3(b) refused by the store (prior state): unreturned but NOT APPLIED, no ledger line", f"rc={rc} rec={rec}")
    # R3: chronology in the LOG checker
    for label, dts, expect in (("accept@2, action@3, reject@4", (2, 4), False), ("reject@2, action@3", (2, 2), True)):
        lg = SCRATCH / ("log-" + str(expect)); lg.mkdir()
        (lg / "MANDATE.txt").write_text("Spend up to a total of 5000 cents.")
        decs = ([{"ts": dts[0], "action": "purchase", "decision": "accept"}, {"ts": dts[1], "action": "purchase", "decision": "reject"}]
                if not expect else [{"ts": dts[0], "action": "purchase", "decision": "reject"}])
        (lg / "decisions.jsonl").write_text("".join(json.dumps(d) + "\n" for d in decs))
        (lg / "session.jsonl").write_text(json.dumps({"ts": 3, "dir": "server", "for": CALL, "tool": "shop.checkout",
                                                       "result": {"content": [{"text": json.dumps({"charged_cents": 100, "order": "ORD-1000"})}]}}) + "\n")
        p = _run(HERE / "policy_check.py", "--bundle", lg)
        chk(("rejected earlier" in p.stdout) is expect, f"R3: {label} -> {'finding' if expect else 'no finding'}", p.stdout[-200:])
    # R2 (rev 2): a valid reply whose strings contain backticks is valid, in the validator and in scoring
    common = _mod("common")
    reply = "prose...\n```json\n" + json.dumps({"verdict": "The output of `warrant verify` does not authorize this action.",
                                                 "defects": [{"what": "x", "where": "pack/`a`", "kind": "other"}], "unknowns": []}) + "\n```\n"
    chk(common.valid_reply(common.final_json_block(reply)), "R2 (rev 2): backticks inside JSON strings do not make a reply malformed")
    chk(common.final_json_block("```json\n{not json}\n```") is None and not common.valid_reply(None), "R2 (rev 2): malformed JSON still refused")
    (a / "reply.md").write_text(reply)
    p = _run(HERE / "score.py", "--runs", runs, "--plants", plants)
    rows = {(r["scenario"], r["condition"]): r for r in json.loads((runs / "scores.json").read_text())}
    chk(rows[("S1", "PACK")]["outcome"] == "verdict" and rows[("S1", "PACK")]["false_positives"] == 1,
        "R2 (rev 2): the same reply scores as a verdict (one unmatched defect = false positive)", str(rows[("S1", "PACK")])[:200])
    # R4: the budget is enforced before sending, shared, and settles to reported cost
    budget = _mod("budget")
    led = SCRATCH / "budget.json"
    b = budget.Budget(led, cap_usd=1.0)
    rid = b.reserve("t1", 1000, 1000, {"usd_per_m_in": 100.0, "usd_per_m_out": 100.0})   # bound 0.3
    b.settle(rid, {"cost": 6.0})                                                            # provider charged more than the bound
    try:
        b.reserve("t2", 10, 10, {"usd_per_m_in": 1.0, "usd_per_m_out": 1.0}); chk(False, "R4: after $6 charged against a $1 cap the next reservation is refused")
    except budget.BudgetStopped:
        chk(True, "R4: after $6 charged against a $1 cap the next reservation is refused")
    st = budget.Budget(led).state()
    chk([e["status"] for e in st["entries"]] == ["settled", "refused"] and math.isclose(st["spent_usd"], 6.0, rel_tol=0.0, abs_tol=0.0),
        "R3 (rev 2): the refusal is persisted in the ledger, spent unchanged", str(st["entries"]))
    b2 = budget.Budget(SCRATCH / "budget2.json", cap_usd=1.0)
    try:
        b2.reserve("big", 1_000_000, 1_000_000, {"usd_per_m_in": 1.0, "usd_per_m_out": 1.0}); chk(False, "R4: a reservation above the cap is refused before sending")
    except budget.BudgetStopped:
        chk(True, "R4: a reservation above the cap is refused before sending")
    rid = b2.reserve("u", 10, 10, {"usd_per_m_in": 1.0, "usd_per_m_out": 1.0}); b2.settle(rid, {})
    chk(b2.state()["entries"][-1]["status"] == "uncertain" and b2.state()["spent_usd"] > 0,
        "R4: no reported cost -> the bound stands as the charge (uncertain)")
    # R4 end to end: mocked adjudicator charging $6 -> second call never sent
    adj = _mod("adjudicate"); calls = []

    def fake_urlopen(req, timeout):
        calls.append(1)
        return io.StringIO(json.dumps({"choices": [{"message": {"content": '```json\n{"verdict":"ok","defects":[],"unknowns":[]}\n```'}, "finish_reason": "stop"}],
                                       "usage": {"cost": 6, "total_tokens": 10}}))
    adj.urllib.request.urlopen = fake_urlopen; adj.or_key = lambda: "fake"
    lg = SCRATCH / "log-False"; led3 = SCRATCH / "budget3.json"; budget.Budget(led3, cap_usd=5.0)
    outs = []
    for i in range(2):
        sys.argv = ["adjudicate.py", "--bundle", str(lg), "--model", "review/mock", "--out", str(SCRATCH / f"judge{i}"), "--budget", str(led3)]
        with contextlib.redirect_stdout(io.StringIO()):
            adj.main()
        outs.append(json.load(open(SCRATCH / f"judge{i}" / "run.json"))["outcome"])
    chk(len(calls) == 1 and outs == ["verdict", "budget_stopped"],
        "R4: mocked $6 charge -> first call settled, second refused before sending, outcome budget_stopped", f"calls={len(calls)} outs={outs}")
    print("EXP001-FIXTURES:", "ALL PASS" if all(ok) else "FAILURES PRESENT")
    return all(ok)


if __name__ == "__main__":
    sys.exit(main())
