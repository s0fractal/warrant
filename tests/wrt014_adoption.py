#!/usr/bin/env python3
"""WRT-014 option A: an adoption satisfies the ADOPTING jurisdiction's threshold.

SPEC §9 asked for "the adopting root's current settlement policy, including
any threshold rule". Every implementation checked only the policies the
adoption record itself cites, which its filer chooses. So under a 2-of-2
jurisdiction, one actor citing an opaque policy adopted another root on one
signature, with 0 errors and 0 warnings. That was recorded on 3a0e3ae with
proposals/wrt-014-model/reproduce.py.

WHAT IS ASSERTED, PYTHON = GO = RUST
  1. one signature, opaque policy cited  -> the root stays unadopted
  2. one signature, the threshold cited  -> unadopted
  3. both signatures, opaque policy cited -> adopted (the jurisdiction's rule
     is met, so the cited one need not repeat it)
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W  # noqa: E402

GO = ROOT / "impl-go" / "warrant-go"
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"
ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")


def scenario(cite_threshold, signers_b):
    tmp = Path(tempfile.mkdtemp(prefix="wrt014-"))
    S = W.Store(tmp / "s")
    S.init()
    ka, kb = tmp / "a.key", tmp / "b.key"
    ka.write_text("11" * 32)
    kb.write_text("22" * 32)
    thr = S.put_blob(W.canon({"warrant_policy": "0.3",
                              "threshold": {"min_sigs": 2, "actors": ["a@x", "b@x"]}}))
    opaque = S.put_blob(b"any text at all\n")

    def rec(subject, prior, ts, under, signers):
        b = {"warrant": "0.2", "decision": "accept", "subject": {"hash": subject},
             "under": under, "because": [], "evidence": [], "actor": {"id": "a@x"},
             "prior": prior, "ts": ts}
        return S.put_record({"body": b, "sigs": [W.sign_envelope(b, a, str(k)) for a, k in signers]})
    R = rec(S.put_blob(b"jurisdiction"), [], 1, [thr], [("a@x", ka), ("b@x", kb)])
    X = rec(S.put_blob(b"another root"), [], 2, [opaque], [("a@x", ka)])
    signers = [("a@x", ka)] + ([("b@x", kb)] if signers_b else [])
    rec(X, [R], 3, [thr if cite_threshold else opaque], signers)
    trust = tmp / "trust.json"
    trust.write_text(json.dumps({"genesis_roots": [R], "actors": {
        "a@x": [W.pubkey_hex(W.load_key(str(ka)))], "b@x": [W.pubkey_hex(W.load_key(str(kb)))]}}))
    arg = ["--settlement", "--trust-config", str(trust)]
    outs = {
        "py": subprocess.run([sys.executable, str(ROOT / "impl" / "warrant.py"), "--store",
                              str(tmp / "s"), "verify"] + arg, capture_output=True, text=True).stdout,
        "go": subprocess.run([str(GO), "verify"] + arg + [str(tmp / "s")],
                             capture_output=True, text=True).stdout,
        "rs": subprocess.run([str(RS), "--store", str(tmp / "s"), "verify"] + arg,
                             capture_output=True, text=True).stdout,
    }
    verdicts = {k: ("unadopted root" not in v, re.search(r"verify: .*", v).group()) for k, v in outs.items()}
    return verdicts


def main():
    for b in (GO, RS):
        if not b.is_file():
            print(f"UNRUN  {b} not built")
            return 3
    for label, cite, both, want in (
            ("1. one signature, opaque policy cited: unadopted", False, False, False),
            ("2. one signature, the threshold cited: unadopted", True, False, False),
            ("3. both signatures, opaque policy cited: adopted", False, True, True)):
        v = scenario(cite, both)
        check(label + " (PY = GO = RS)",
              len({x for x in v.values()}) == 1 and v["py"][0] is want, v)
    print(f"\nWRT-014-ADOPTION: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
