#!/usr/bin/env python3
"""Do Python and Go report the same findings — not just the same counts?

WHY
---
`tests/verify_three_way.py` compares (records, errors, warnings) on nine
hand-broken stores. A finer comparison over the fuzzed settlement stores that
`tests/rs_parity.py` builds found two Go defects the counts had never met:

  * A threshold policy re-encoded as UTF-16, UTF-32 or with a UTF-8 BOM was
    "not JSON" to encoding/json, so Go treated it as an opaque policy and
    adopted a root on ONE signature where the policy asked for two; Python and
    Rust read the declaration, found the bytes non-canonical and reported
    `ERR: invalid threshold policy`. Same store, different settlement verdict.
  * A ski@v1 reason with no string `check` was skipped silently by Go and
    reported `ski@v1 unverified` by Python — the silent skip SPEC §6(7) forbids.

WHAT IS ASSERTED
  1. Over fuzzed stores, at base and settlement grade, the multiset of
     (level, subject) pairs in `verify --json` is identical for Python and Go.
     `message` is not compared: it is human prose and may differ (README,
     "Machine boundary") — which is itself why agents need stable codes.
  2. A 2-of-2 threshold policy in ten encodings — canonical, UTF-16 LE/BE,
     UTF-32, UTF-8 BOM, pretty-printed, duplicate member, NaN, trailing bytes,
     invalid UTF-8 — gets the same report and the same adoption outcome from
     Python and Go.

`WARRANT_GO` selects the Go binary (red-first: point it at a pre-fix build).
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import rs_parity as R          # noqa: E402  (the fuzzed settlement-store builder)

GO = Path(os.environ.get("WARRANT_GO", ROOT / "impl-go" / "warrant-go"))
W = R.W
ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")


def pairs(cmd):
    out = subprocess.run(cmd, capture_output=True, text=True, env=R.ENV).stdout
    rep = json.loads(out)
    return Counter((f["level"], f["subject"]) for f in rep["findings"]), rep


def fuzzed(n, seed):
    rng = random.Random(seed)
    diverged = []
    for i in range(n):
        tmp = tempfile.mkdtemp(prefix="goparity-")
        s, trust = R.build(Path(tmp, "s"), rng)
        for extra in ([], ["--settlement", "--trust-config", trust]):
            py, prep = pairs(R.PY + ["--store", str(s.root), "verify", "--json"] + extra)
            go, grep_ = pairs([str(GO), "verify", "--json", "--store-mode"] + extra + [str(s.root)])
            if py != go or (prep["errors"], prep["warnings"]) != (grep_["errors"], grep_["warnings"]):
                diverged.append((i, extra and "settlement" or "base", dict(py - go), dict(go - py)))
    return diverged


def policy_encodings():
    doc = {"warrant_policy": "0.3", "threshold": {"min_sigs": 2, "actors": ["a@x", "b@x"]}}
    canon = W.canon(doc)
    variants = {
        "canonical": canon,
        "utf-16le+BOM": b"\xff\xfe" + canon.decode().encode("utf-16-le"),
        "utf-16be": canon.decode().encode("utf-16-be"),
        "utf-32le": canon.decode().encode("utf-32-le"),
        "utf-8 BOM": b"\xef\xbb\xbf" + canon,
        "pretty": json.dumps(doc, indent=1).encode(),
        "dup member": canon.replace(b'"min_sigs":2', b'"min_sigs":1,"min_sigs":2'),
        "NaN member": canon[:-1] + b',"x":NaN}',
        "trailing bytes": canon + b" x",
        "invalid utf-8": canon.replace(b'"a@x"', b'"a\xff@x"'),
    }
    split = []
    for name, blob in variants.items():
        tmp = Path(tempfile.mkdtemp(prefix="gopolicy-"))
        st = tmp / "s"
        S = W.Store(st)
        S.init()
        ka, kb = tmp / "a.key", tmp / "b.key"
        ka.write_text("11" * 32)
        kb.write_text("22" * 32)
        pol = S.put_blob(blob)

        def rec(subj, prior, ts, under):
            b = {"warrant": "0.2", "decision": "accept", "subject": {"hash": subj}, "under": under,
                 "because": [], "evidence": [], "actor": {"id": "a@x"}, "prior": prior, "ts": ts}
            return S.put_record({"body": b, "sigs": [W.sign_envelope(b, "a@x", str(ka))]})
        p0 = S.put_blob(b"p")
        r1 = rec(S.put_blob(b"root one"), [], 1, [p0])
        r2 = rec(S.put_blob(b"root two"), [], 2, [p0])
        rec(r2, [r1], 3, [pol])          # adopt root two, ONE signature, under the policy
        trust = tmp / "t.json"
        trust.write_text(json.dumps({"genesis_roots": [r1], "actors": {
            "a@x": [W.pubkey_hex(W.load_key(str(ka)))], "b@x": [W.pubkey_hex(W.load_key(str(kb)))]}}))
        arg = ["--settlement", "--trust-config", str(trust)]
        py, prep = pairs(R.PY + ["--store", str(st), "verify", "--json"] + arg)
        go, grep_ = pairs([str(GO), "verify", "--json", "--store-mode"] + arg + [str(st)])
        if py != go:
            split.append(name)
    return split


def main():
    if not GO.is_file():
        print(f"SKIP  go findings parity: warrant-go not built ({GO})")
        return 0
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    d = fuzzed(n, 20261015)
    check(f"fuzzed stores: same (level, subject) findings at both grades ({2 * n} reports)",
          not d, d[:3])
    s = policy_encodings()
    check("threshold policy in ten encodings: same report and adoption outcome", not s, s)
    print(f"\nGO-FINDINGS-PARITY: {'ALL AGREE' if ok else 'DIVERGENCE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
