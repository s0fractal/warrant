#!/usr/bin/env python3
"""Build the two condition bundles from one finished session workdir.

    python3 bundles.py --workdir <dir> --scenario S1 --dispute "<text>" --out <runs/S1>

PACK/  the evidence pack as produced, plus `warrant verify`, `warrant why`
       (from the manifest's decision) and `warrant check` for every ski@v1
       reason, the mandate text, the merchant effects ledger, the dispute.
LOG/   the plain session log (parsed into call/response pairs), the same
       mandate text, ledger and dispute, and the output of policy_check.py --
       an ordinary policy check over the log. No signatures, no chain.

Both bundles carry the same task-level material; only the observer's format
differs. Neither contains harness.jsonl, session-summary.json or PLANTS.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WARRANT = [sys.executable, str(ROOT / "impl" / "warrant.py")]


def sh(args, cwd=None):
    r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return f"$ {' '.join(a if ' ' not in a else repr(a) for a in args)}\n[exit {r.returncode}]\n{r.stdout}{r.stderr}"


def parse_session(lines):
    """Pair host requests with server responses by id; keep everything else as-is."""
    reqs, out = {}, []
    for e in lines:
        try:
            m = json.loads(e["line"])
        except ValueError:
            out.append({"ts": e["ts"], "dir": e["dir"], "raw": e["line"]}); continue
        if e["dir"] == "host" and "method" in m:
            reqs[m.get("id")] = (e["ts"], m)
            out.append({"ts": e["ts"], "dir": "host", "id": m.get("id"), "method": m["method"], "params": m.get("params")})
        elif e["dir"] == "server" and "method" not in m:
            t, req = reqs.get(m.get("id"), (None, {}))
            out.append({"ts": e["ts"], "dir": "server", "id": m.get("id"), "for": req.get("method"),
                        "tool": (req.get("params") or {}).get("name"), "result": m.get("result", m.get("error"))})
        else:
            out.append({"ts": e["ts"], "dir": e["dir"], "message": m})
    answered = {o["id"] for o in out if o["dir"] == "server"}
    for o in out:
        if o["dir"] == "host" and o["method"] == "tools/call" and o["id"] not in answered:
            o["no_response"] = True
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True); ap.add_argument("--scenario", required=True)
    ap.add_argument("--dispute", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    work, out = Path(a.workdir).resolve(), Path(a.out).resolve()
    sc = json.load(open(HERE / "scenarios" / f"{a.scenario}.json"))
    common = {"MANDATE.txt": sc["mandate"]["text"] + "\n", "TASK.txt": sc["task"] + "\n", "DISPUTE.txt": a.dispute + "\n",
              "merchant-effects-ledger.jsonl": (work / "effects.jsonl").read_text() if (work / "effects.jsonl").exists() else ""}
    # PACK
    pk = out / "PACK"; shutil.rmtree(pk, ignore_errors=True); pk.mkdir(parents=True)
    shutil.copytree(work / "pack", pk / "pack")
    store = str(pk / "pack" / ".warrants")
    tx = [sh(WARRANT + ["--store", store, "verify"])]
    manifest = json.load(open(pk / "pack" / "manifest.json"))
    if manifest.get("decision"):
        tx.append(sh(WARRANT + ["--store", store, "why", manifest["decision"]]))
    checks = []
    for rec in sorted(Path(store, "records").glob("*.json")):
        body = json.load(open(rec))["body"]
        for r in body.get("because", []):
            if r.get("kind") == "check" and r.get("runtime") == "ski@v1":
                checks.append(r["check"])
    for c in sorted(set(checks)):
        tx.append(sh(WARRANT + ["--store", store, "check", c]))
    (pk / "TRANSCRIPTS.txt").write_text("\n\n".join(tx))
    (pk / "HOW-TO-READ.txt").write_text(
        "pack/.warrants: the signed, content-addressed store (records/, blobs/). pack/manifest.json: what the\n"
        "sealing proxy observed, incl. seal_failures, unreturned_calls, observation_complete.\n"
        "TRANSCRIPTS.txt: `warrant verify`, `warrant why <decision>`, and `warrant check <hash>` for every\n"
        "ski@v1 reason -- each check is re-executed offline; its evidence blobs are in pack/.warrants/blobs.\n"
        "Blobs are raw bytes named by their sha256: policies, subjects, evidence (tool results), WPL sources.\n")
    for k, v in common.items():
        (pk / k).write_text(v)
    # LOG
    lg = out / "LOG"; shutil.rmtree(lg, ignore_errors=True); lg.mkdir(parents=True)
    raw = [json.loads(l) for l in open(work / "session.jsonl")]
    parsed = parse_session(raw)
    (lg / "session.raw.jsonl").write_text("".join(json.dumps(e) + "\n" for e in raw))
    (lg / "session.jsonl").write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in parsed))
    (lg / "decisions.jsonl").write_text("".join(
        json.dumps({k: v for k, v in e.items() if k not in ("wid",)}, sort_keys=True) + "\n"
        for e in (json.loads(l) for l in open(work / "harness.jsonl")) if e.get("event") == "decision"))
    for k, v in common.items():
        (lg / k).write_text(v)
    (lg / "policy_check.txt").write_text(sh([sys.executable, str(HERE / "policy_check.py"), "--bundle", str(lg)]))
    (lg / "HOW-TO-READ.txt").write_text(
        "session.jsonl: every request the agent sent and every response the shop returned, in order, paired by id\n"
        "(a request with no_response:true was never answered). decisions.jsonl: the agent's recorded decisions\n"
        "with the facts it stated. policy_check.txt: an ordinary script evaluating MANDATE.txt over the log.\n")
    print(f"PACK -> {pk}\nLOG  -> {lg}")


if __name__ == "__main__":
    sys.exit(main())
