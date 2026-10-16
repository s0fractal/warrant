#!/usr/bin/env python3
"""WRT-019: a record signed with a P-256 key verifies end to end, PY = GO = RS.

The key lives where a phone's secure element would keep it; here Python signs
(`keygen --alg p256`), and the three CLIs verify the store at settlement grade
with --require-bound against a trust config that binds the actor to the
compressed P-256 key.

WHAT IS ASSERTED, PYTHON = GO = RUST
  1. P-256 actor, key bound                      -> 0 ERR
  2. the same record with its signature high-S   -> 1 ERR (no valid actor signature)
  3. the entry's alg removed                     -> 1 ERR (a 33-byte key is not Ed25519)
  4. trust binds another P-256 key, --require-bound -> 1 ERR (not bound)
  5. a trust config holding an UNCOMPRESSED key  -> refused as a trust config (1 ERR, settlement)
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from three_clis import GO, PY, RS, Tally, W, unbuilt

T = Tally()
N = W._P256_N


def build():
    tmp = Path(tempfile.mkdtemp(prefix="wrt019-"))
    S = W.Store(tmp / "s")
    S.init()
    k = tmp / "phone.key"
    k.write_text(W.P256_KEYFILE_PREFIX + (12345678901234567890).to_bytes(32, "big").hex())
    other = tmp / "other.key"
    other.write_text(W.P256_KEYFILE_PREFIX + (98765).to_bytes(32, "big").hex())
    pol = S.put_blob(b"policy\n")
    body = {"warrant": "0.2", "decision": "propose", "subject": {"hash": S.put_blob(b"s")},
            "under": [pol], "because": [], "evidence": [], "actor": {"id": "phone@x"},
            "prior": [], "ts": 1}
    entry = W.sign_envelope(body, "phone@x", str(k))
    wid = S.put_record({"body": body, "sigs": [entry]})
    pub = {n: W.pubkey_hex(W.load_key(str(p))) for n, p in (("phone", k), ("other", other))}
    for name, keys in (("bound", [pub["phone"]]), ("other", [pub["other"]])):
        (tmp / f"{name}.json").write_text(json.dumps({"actors": {"phone@x": keys}}))
    sk = W.load_key(str(k))
    unc = sk.public_key().public_bytes(W.serialization.Encoding.X962,
                                       W.serialization.PublicFormat.UncompressedPoint).hex()
    (tmp / "uncompressed.json").write_text(json.dumps({"actors": {"phone@x": [unc]}}))
    return tmp, tmp / "s" / "records" / f"{wid}.json", entry


def run_all(st, args):
    cmds = {"py": PY + ["--store", str(st), "verify"] + args,
            "go": [str(GO), "verify"] + args + [str(st)],
            "rs": [str(RS), "--store", str(st), "verify"] + args}
    out = {}
    for k, c in cmds.items():
        p = subprocess.run(c, capture_output=True, text=True, check=False)
        m = re.search(r"verify: \d+ records, (\d+) errors", p.stdout)
        out[k] = int(m.group(1)) if m else None
    return out


def same(res, n):
    return set(res.values()) == {n}


def main():
    missing = unbuilt()
    if missing:
        print(f"UNRUN  {missing} not built")
        return 3
    tmp, rec, entry = build()
    st = tmp / "s"
    strict = lambda cfg: ["--settlement", "--trust-config", str(tmp / cfg), "--require-bound"]  # noqa: E731
    r = run_all(st, strict("bound.json"))
    T.check("1. P-256 actor, key bound: 0 ERR (PY = GO = RS)", same(r, 0), r)
    env = json.loads(rec.read_text())
    s = int(entry["sig"][64:], 16)
    env["sigs"][0]["sig"] = entry["sig"][:64] + (N - s).to_bytes(32, "big").hex()
    rec.write_text(json.dumps(env))
    r = run_all(st, strict("bound.json"))
    T.check("2. high-S signature: 1 ERR (PY = GO = RS)", same(r, 1), r)
    env["sigs"][0] = {k: v for k, v in entry.items() if k != "alg"}
    rec.write_text(json.dumps(env))
    r = run_all(st, strict("bound.json"))
    T.check("3. alg removed: 1 ERR (PY = GO = RS)", same(r, 1), r)
    env["sigs"][0] = entry
    rec.write_text(json.dumps(env))
    r = run_all(st, strict("other.json"))
    T.check("4. another P-256 key bound, --require-bound: 1 ERR (PY = GO = RS)", same(r, 1), r)
    r = run_all(st, strict("uncompressed.json"))
    T.check("5. uncompressed key in the trust config: refused, 1 ERR (PY = GO = RS)", same(r, 1), r)
    print(f"\nWRT-019-P256: {'ALL PASS' if T.ok else 'FAILURES PRESENT'}")
    return 0 if T.ok else 1


if __name__ == "__main__":
    sys.exit(main())
