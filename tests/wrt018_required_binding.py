#!/usr/bin/env python3
"""WRT-018 option A: the reader may require the actor's own binding.

Without the option, a record whose actor signed with a key the trust config does
not bind to that actor verifies ok:true with one WARN (SPEC §5.1: bound/unbound is
a report). Two consumers rebuilt the missing rule outside warrant (oaip,
warrant-pdf); warrant-pdf's version refused a record over an appended junk
co-signature, which §5 says is excluded, never fatal.

WHAT IS ASSERTED, PYTHON = GO = RUST, THROUGH EACH CLI
  1. actor's key unbound, no option          -> 0 ERR (the report stays a report)
  2. actor's key unbound, --require-bound    -> 1 ERR per record, "no bound signature by body.actor.id"
  3. actor bound + a valid co-signature by an unbound key for another actor,
     --require-bound                         -> 0 ERR (co-signatures keep §5)
  4. --require-bound with no trust config    -> exactly 1 ERR, subject settlement
  5. --require-bound without --settlement    -> the CLI refuses (nonzero exit, no verdict)
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


def store(cosign_other=False):
    """Two records by a@x signed with key A; optionally a co-signature by key M for m@x."""
    tmp = Path(tempfile.mkdtemp(prefix="wrt018-"))
    S = W.Store(tmp / "s")
    S.init()
    ka, km = tmp / "a.key", tmp / "m.key"
    ka.write_text("11" * 32)
    km.write_text("33" * 32)
    pol = S.put_blob(b"policy\n")

    def rec(subject, prior, ts):
        b = {"warrant": "0.2", "decision": "accept", "subject": {"hash": subject},
             "under": [pol], "because": [], "evidence": [], "actor": {"id": "a@x"},
             "prior": prior, "ts": ts}
        sigs = [W.sign_envelope(b, "a@x", str(ka))]
        if cosign_other:
            sigs.append(W.sign_envelope(b, "m@x", str(km)))
        return S.put_record({"body": b, "sigs": sigs})
    r1 = rec(S.put_blob(b"one"), [], 1)
    rec(S.put_blob(b"two"), [r1], 2)
    pub = {k: W.pubkey_hex(W.load_key(str(p))) for k, p in (("a", ka), ("m", km))}
    bound = tmp / "bound.json"
    bound.write_text(json.dumps({"actors": {"a@x": [pub["a"]]}}))
    unbound = tmp / "unbound.json"          # a@x is bound to M's key, not A's
    unbound.write_text(json.dumps({"actors": {"a@x": [pub["m"]]}}))
    return tmp / "s", bound, unbound


def run_all(st, args):
    """{impl: (exit code, error count or None, full output)} for the same request."""
    cmds = {
        "py": [sys.executable, str(ROOT / "impl" / "warrant.py"), "--store", str(st), "verify"] + args,
        "go": [str(GO), "verify"] + args + [str(st)],
        "rs": [str(RS), "--store", str(st), "verify"] + args,
    }
    res = {}
    for k, c in cmds.items():
        p = subprocess.run(c, capture_output=True, text=True)
        m = re.search(r"verify: \d+ records, (\d+) errors", p.stdout)
        res[k] = (p.returncode, int(m.group(1)) if m else None, p.stdout + p.stderr)
    return res


def agree(res):
    return len({(c != 0, e) for c, e, _ in res.values()}) == 1


def main():
    for b in (GO, RS):
        if not b.is_file():
            print(f"UNRUN  {b} not built")
            return 3
    st, bound, unbound = store()
    r = run_all(st, ["--settlement", "--trust-config", str(unbound)])
    check("1. unbound actor, no option: 0 ERR (PY = GO = RS)",
          agree(r) and r["py"][1] == 0 and "signature unbound" in r["py"][2], r)
    r = run_all(st, ["--settlement", "--trust-config", str(unbound), "--require-bound"])
    check("2. unbound actor, --require-bound: 1 ERR per record (PY = GO = RS)",
          agree(r) and r["py"][1] == 2 and all(
              o.count("no bound signature by body.actor.id") == 2 for _, _, o in r.values()), r)
    st2, bound2, _ = store(cosign_other=True)
    r = run_all(st2, ["--settlement", "--trust-config", str(bound2), "--require-bound"])
    check("3. bound actor + unbound co-signature, --require-bound: 0 ERR (PY = GO = RS)",
          agree(r) and r["py"][1] == 0 and all(
              "signature unbound" in o for _, _, o in r.values()), r)
    r = run_all(st, ["--settlement", "--require-bound"])
    check("4. --require-bound without a trust config: exactly 1 ERR (PY = GO = RS)",
          agree(r) and r["py"][1] == 1 and all(
              "required binding needs a trust config" in o for _, _, o in r.values()), r)
    r = run_all(st, ["--require-bound"])
    check("5. --require-bound without --settlement: refused, no verdict (PY = GO = RS)",
          all(c != 0 and e is None for c, e, _ in r.values()), r)
    print(f"\nWRT-018-REQUIRED-BINDING: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
