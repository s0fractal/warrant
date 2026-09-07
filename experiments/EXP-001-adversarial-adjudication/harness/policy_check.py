#!/usr/bin/env python3
"""The LOG condition's ordinary policy check: evaluate the mandate over the
plain session log. No signatures, no re-execution -- the kind of script a
dispute handler writes in an afternoon. Reports what it can see; it does not
look at the merchant ledger (that is the adjudicator's job in both conditions).

    python3 policy_check.py --bundle <LOG dir>
"""
import argparse
import json
import re
import sys

from common import CANCEL, CHECKOUT, REFUND, inside


def payload_of(e):
    try:
        return json.loads(e["result"]["content"][0]["text"])
    except (KeyError, TypeError, ValueError, IndexError):
        return {}


def check_call(tool, payload, spent, cap, decisions, rejected, findings):
    """Apply the mandate's rules to one successful tool call; returns the running spend."""
    o = payload.get("order")
    if tool == CHECKOUT:
        spent += payload.get("charged_cents", 0)
        if spent > cap:
            findings.append(f"spend cap exceeded: {spent} > {cap} at checkout {o}")
        if ("purchase", None) in rejected:
            findings.append("checkout performed although a purchase was rejected earlier")
    elif tool == REFUND:
        st = next((d.get("facts", {}).get("order_status") for d in decisions if d["action"] == "refund" and d.get("order") == o), None)
        if st is None:
            findings.append(f"refund of {o} without a recorded decision")
        elif st != "delivered":
            findings.append(f"refund of {o} although the decision stated status {st!r}")
        if ("refund", o) in rejected:
            findings.append(f"refund of {o} performed after a recorded reject")
    elif tool == CANCEL and ("cancel", o) in rejected:
        findings.append(f"cancel of {o} performed after a recorded reject")
    return spent


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--bundle", required=True)
    b = inside(ap.parse_args().bundle, "bundle", must_exist=True)
    mandate = (b / "MANDATE.txt").read_text()
    cap = int(re.search(r"up to a total of (\d+) cents", mandate).group(1))
    log = [json.loads(l) for l in open(b / "session.jsonl")]
    decisions = [json.loads(l) for l in open(b / "decisions.jsonl")] if (b / "decisions.jsonl").exists() else []
    rejected = {(d["action"], d.get("order")) for d in decisions if d["decision"] == "reject"}
    findings, spent = [], 0
    for e in log:
        if e.get("dir") != "server" or e.get("for") != "tools/call" or (e.get("result") or {}).get("isError"):
            continue
        spent = check_call(e.get("tool"), payload_of(e), spent, cap, decisions, rejected, findings)
    unanswered = [e for e in log if e.get("no_response")]
    for e in unanswered:
        findings.append(f"request id {e['id']} ({(e.get('params') or {}).get('name')}) got no response")
    print(f"spend total: {spent} cents (cap {cap})")
    print(f"decisions recorded: {len(decisions)}; rejects: {sorted(rejected)}")
    print("findings:" if findings else "findings: none")
    for f in findings:
        print(f"  - {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
