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
import contextlib
import io
import json
import shutil
import sys
from pathlib import Path

from common import HERE, ROOT, inside   # noqa: E402
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W          # noqa: E402
import policy_check          # noqa: E402


def cli(*argv):
    """Run the warrant CLI in-process (no OS command) and return a transcript."""
    out = io.StringIO()
    saved = sys.argv
    sys.argv = ["warrant", *map(str, argv)]
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            W.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = saved
    shown = " ".join(a if " " not in a else repr(a) for a in map(str, argv))
    return f"$ warrant {shown}\n[exit {code}]\n{out.getvalue()}"


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
            _, req = reqs.get(m.get("id"), (None, {}))
            out.append({"ts": e["ts"], "dir": "server", "id": m.get("id"), "for": req.get("method"),
                        "tool": (req.get("params") or {}).get("name"), "result": m.get("result", m.get("error"))})
        else:
            out.append({"ts": e["ts"], "dir": e["dir"], "message": m})
    answered = {o["id"] for o in out if o["dir"] == "server"}
    for o in out:
        if o["dir"] == "host" and o["method"] == "tools/call" and o["id"] not in answered:
            o["no_response"] = True
    return out


def build(work, scenario, dispute, out):
    """Build PACK/ and LOG/ under `out` from a finished session in `work`."""
    work, out = Path(work), Path(out)
    sc = json.load(open(HERE / "scenarios" / f"{scenario}.json"))
    common = {"MANDATE.txt": sc["mandate"]["text"] + "\n", "TASK.txt": sc["task"] + "\n", "DISPUTE.txt": dispute + "\n",
              "merchant-effects-ledger.jsonl": (work / "effects.jsonl").read_text() if (work / "effects.jsonl").exists() else ""}
    # PACK
    pk = out / "PACK"; shutil.rmtree(pk, ignore_errors=True); pk.mkdir(parents=True)
    shutil.copytree(work / "pack", pk / "pack")
    store = str(pk / "pack" / ".warrants")
    tx = [cli("--store", store, "verify")]
    manifest = json.load(open(pk / "pack" / "manifest.json"))
    if manifest.get("decision"):
        tx.append(cli("--store", store, "why", manifest["decision"]))
    checks = []
    for rec in sorted(Path(store, "records").glob("*.json")):
        body = json.load(open(rec))["body"]
        for r in body.get("because", []):
            if r.get("kind") == "check" and r.get("runtime") == "ski@v1":
                checks.append(r["check"])
    for c in sorted(set(checks)):
        tx.append(cli("--store", store, "check", c))
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
    (lg / "policy_check.txt").write_text("$ policy_check.py --bundle LOG\n" + policy_check.report(lg))
    (lg / "HOW-TO-READ.txt").write_text(
        "session.jsonl: every request the agent sent and every response the shop returned, in order, paired by id\n"
        "(a request with no_response:true was never answered). decisions.jsonl: the agent's recorded decisions\n"
        "with the facts it stated. policy_check.txt: an ordinary script evaluating MANDATE.txt over the log.\n")
    return pk, lg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True); ap.add_argument("--scenario", required=True)
    ap.add_argument("--dispute", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pk, lg = build(inside(a.workdir, "workdir", must_exist=True), a.scenario, a.dispute, inside(a.out, "out"))
    print(f"PACK -> {pk}\nLOG  -> {lg}")


if __name__ == "__main__":
    sys.exit(main())
