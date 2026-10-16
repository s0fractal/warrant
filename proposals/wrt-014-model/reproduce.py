#!/usr/bin/env python3
"""WRT-014 reproduction: one actor adopts a root under a jurisdiction whose own
policy is 2-of-2, by citing an opaque policy in the adoption record.

Prints what each implementation decides. On 2026-10-15 (and still on
3a0e3ae) all three adopted the root on one signature with 0 errors and 0
warnings. Since WRT-014 was decided as option A (2026-10-16) all three leave it
unadopted; tests/wrt014_adoption.py holds that as a gate.

    python3 proposals/wrt-014-model/reproduce.py
Exit 0 always: this is a measurement; the gate is tests/wrt014_adoption.py.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W  # noqa: E402

GO = ROOT / "impl-go" / "warrant-go"
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"

tmp = Path(tempfile.mkdtemp(prefix="wrt014-"))
st = tmp / "s"
S = W.Store(st)
S.init()
ka, kb = tmp / "a.key", tmp / "b.key"
ka.write_text("11" * 32)
kb.write_text("22" * 32)
threshold = S.put_blob(W.canon({"warrant_policy": "0.3",
                                "threshold": {"min_sigs": 2, "actors": ["a@x", "b@x"]}}))
opaque = S.put_blob(b"any text at all\n")


def rec(subject, prior, ts, under, signers):
    b = {"warrant": "0.2", "decision": "accept", "subject": {"hash": subject},
         "under": under, "because": [], "evidence": [], "actor": {"id": "a@x"},
         "prior": prior, "ts": ts}
    return S.put_record({"body": b, "sigs": [W.sign_envelope(b, a, str(k)) for a, k in signers]})


# The jurisdiction: a genesis root filed UNDER the 2-of-2 threshold, signed by both.
R = rec(S.put_blob(b"jurisdiction"), [], 1, [threshold], [("a@x", ka), ("b@x", kb)])
X = rec(S.put_blob(b"another root"), [], 2, [opaque], [("a@x", ka)])
# a@x alone adopts X into R's jurisdiction, citing an opaque policy.
rec(X, [R], 3, [opaque], [("a@x", ka)])
trust = tmp / "trust.json"
trust.write_text(json.dumps({"genesis_roots": [R], "actors": {
    "a@x": [W.pubkey_hex(W.load_key(str(ka)))], "b@x": [W.pubkey_hex(W.load_key(str(kb)))]}}))
arg = ["--settlement", "--trust-config", str(trust)]
runs = [("python", [sys.executable, str(ROOT / "impl" / "warrant.py"), "--store", str(st), "verify"] + arg)]
if GO.is_file():
    runs.append(("go", [str(GO), "verify"] + arg + [str(st)]))
if RS.is_file():
    runs.append(("rust", [str(RS), "--store", str(st), "verify"] + arg))
for name, cmd in runs:
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    summary = re.search(r"verify: .*", out).group()
    verdict = "X ADOPTED on one signature" if "unadopted root" not in out else "X unadopted"
    print(f"{name:7} {verdict:28} {summary}")
