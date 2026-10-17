#!/usr/bin/env python3
"""KNOWN GAP, pinned: a record can survive every check and still contradict its policy.

The countermodel is Monday's (manifesto/quotes/Monday/chat-0001/0001-0002), built
here in its strongest form so the gap is a measurement, not a remark:

    policy   = "DENY_ALL: no change may be accepted under this policy."
    reason   = a real ski@v1 check, RE-EXECUTED by the verifier, verdict pass
               (examples/ski: a reduction that has nothing to do with the policy)
    decision = accept, signed by a key the reader's trust config binds

Warrant pins the policy bytes, replays the reason, binds the signer
(--settlement --require-bound), and reports 0 errors. Every guarantee the
construction offers holds; the headline "the decision was allowed by its policy"
is false. Monday named the missing invariants: policy -> computation binding,
evidence -> facts binding, result -> decision binding. THREAT-MODEL A6 says the
same thing in prose ("Whatever the policy says"); WRT-020 is the open design
(its profile reports this store OPAQUE: a prose policy cannot be checked).

This test PASSES while the gap is open. When a binding mechanism lands, the
verifier should refuse this store, this test should fail, and it should be turned
into the witness of the new rule, the way warrant-pdf's pinned limitation became
a witness when WRT-018 shipped.

WHAT IS ASSERTED, PYTHON = GO = RUST
  1. the reason really re-executes: `check` gives pass (it is not a cmd@v1 claim)
  2. verify --settlement --require-bound: 0 errors in all three implementations
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from three_clis import GO, PY, RS, Tally, W, unbuilt

ROOT = Path(__file__).resolve().parents[1]
SKI = ROOT / "examples" / "ski"
T = Tally()
POLICY = b"DENY_ALL: no change may be accepted under this policy.\n"


def build():
    tmp = Path(tempfile.mkdtemp(prefix="countermodel-"))
    S = W.Store(tmp / "s")
    S.init()
    for b in sorted(SKI.glob("*.bin")):
        S.put_blob(b.read_bytes())
    check = S.put_blob((SKI / "check.json").read_bytes())
    policy = S.put_blob(POLICY)
    subject = S.put_blob(b"PR-1: delete the audit log\n")
    key = tmp / "a.key"
    key.write_text("44" * 32)
    body = {"warrant": "0.2", "decision": "accept",
            "subject": {"hash": subject, "note": "PR-1"}, "under": [policy],
            "because": [{"kind": "check", "check": check, "runtime": "ski@v1", "verdict": "pass"}],
            "evidence": [], "actor": {"id": "approver@x"}, "prior": [], "ts": 1}
    wid = S.put_record({"body": body, "sigs": [W.sign_envelope(body, "approver@x", str(key))]})
    trust = tmp / "trust.json"
    trust.write_text(json.dumps({"genesis_roots": [wid],
                                 "actors": {"approver@x": [W.pubkey_hex(W.load_key(str(key)))]}}))
    return tmp / "s", trust, check


def main():
    missing = unbuilt()
    if missing:
        print(f"UNRUN  {missing} not built")
        return 3
    store, trust, check = build()
    r = subprocess.run(PY + ["--store", str(store), "check", check], capture_output=True, text=True, check=False)
    T.check("1. the reason re-executes and passes (a replayed ski@v1 check, not a claim)",
            r.returncode == 0 and r.stdout.startswith("pass"), r.stdout + r.stderr)
    args = ["--settlement", "--trust-config", str(trust), "--require-bound"]
    cmds = {"py": PY + ["--store", str(store), "verify"] + args,
            "go": [str(GO), "verify"] + args + [str(store)],
            "rs": [str(RS), "--store", str(store), "verify"] + args}
    errs = {}
    for k, c in cmds.items():
        out = subprocess.run(c, capture_output=True, text=True, check=False).stdout
        m = re.search(r"verify: \d+ records, (\d+) errors", out)
        errs[k] = int(m.group(1)) if m else None
    T.check("2. KNOWN GAP: a DENY_ALL policy, a replayed unrelated reason and an accept verify "
            "with 0 errors (PY = GO = RS)", set(errs.values()) == {0}, errs)
    print(f"\nCOUNTERMODEL-POLICY-BINDING: {'GAP STILL OPEN (as pinned)' if T.ok else 'CHANGED -- see docstring'}")
    return 0 if T.ok else 1


if __name__ == "__main__":
    sys.exit(main())
