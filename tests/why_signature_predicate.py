#!/usr/bin/env python3
"""`why` and `verify` must agree about what "signed" means (SPEC §5, §6).

    python3 tests/why_signature_predicate.py

SPEC §5: "A co-signature that fails to verify is reported and EXCLUDED, not fatal
(MUST): because anyone with store write access can append envelope signatures, a
single junk co-signature MUST NOT be able to invalidate a record that still
carries a valid signature by body.actor.id."

`why` required EVERY signature to verify, so appending one junk signature -- an
operation available to anyone who can write a file in the store -- made `why`
report VERIFY FAILED and exit 1 on a record `verify --json` returned ok:true for.
Two verdicts about one store, from one binary.

Requested by an external review after the fix, on the grounds that the fix itself
had no test: the predicate had been changed to `_well_signed`, and nothing in the
suite would have noticed it changing back.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W  # noqa: E402

WARRANT = [sys.executable, str(ROOT / "impl" / "warrant.py")]
checks, fails = [], []


def chk(name, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'}  {name:<52} got={got} want={want}")
    (checks if ok else fails).append(name)


def run(store, *args):
    p = subprocess.run(WARRANT + ["--store", store, *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout


with tempfile.TemporaryDirectory() as tmp:
    store = os.path.join(tmp, ".warrants")
    st = W.Store(store)
    st.init() if hasattr(st, "init") else None

    # sign_envelope takes a key PATH, not raw bytes.
    import secrets
    key = os.path.join(tmp, "a.key")
    with open(key, "w") as fh:
        fh.write(secrets.token_bytes(32).hex())

    policy = json.dumps({"policy": "none"}, separators=(",", ":")).encode()
    ph = st.put_blob(policy)
    body = {"warrant": "0.1", "decision": "propose",
            "subject": {"hash": ph}, "under": [ph], "because": [],
            "evidence": [], "actor": {"id": "a@x"}, "prior": [],
            "ts": 1751673600}
    env = {"body": body, "sigs": [W.sign_envelope(body, "a@x", key)]}
    wid = st.put_record(env)

    code, _ = run(store, "verify")
    chk("baseline: verify accepts the record", code, 0)
    code, _ = run(store, "why", wid)
    chk("baseline: why accepts the record", code, 0)

    # Anyone with store write access appends a junk co-signature.
    env2 = st.get_record(wid)
    env2["sigs"].append({"actor": "intruder@x", "pub": "00" * 32, "sig": "11" * 64})
    st.put_record(env2)

    code, out = run(store, "verify", "--json")
    verify_ok = code == 0
    chk("junk co-signature: verify still accepts (§5 MUST)", verify_ok, True)
    code, _ = run(store, "why", wid)
    chk("junk co-signature: why still accepts (§5 MUST)", code, 0)

    # Now remove the actor's own signature: no valid signature by body.actor.id.
    env3 = st.get_record(wid)
    env3["sigs"] = [s for s in env3["sigs"] if s["actor"] != "a@x"]
    st.put_record(env3)

    code, _ = run(store, "verify")
    chk("no actor signature: verify rejects (§6 ERR)", code != 0, True)
    code, _ = run(store, "why", wid)
    chk("no actor signature: why rejects", code != 0, True)

    # And an envelope with no signatures at all must not read as verified:
    # all() over an empty list is True, which is how this once passed.
    env4 = st.get_record(wid)
    env4["sigs"] = []
    st.put_record(env4)
    code, _ = run(store, "why", wid)
    chk("no signatures at all: why rejects", code != 0, True)

print()
if fails:
    print(f"WHY-SIGNATURE-PREDICATE: FAILURES ({len(fails)}): {', '.join(fails)}")
    raise SystemExit(1)
print(f"WHY-SIGNATURE-PREDICATE: ALL PASS ({len(checks)}/{len(checks)})")
