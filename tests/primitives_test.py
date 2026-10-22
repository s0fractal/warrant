#!/usr/bin/env python3
"""The encoding and signature core against the vendored s0fractal/primitives pack
(blob-hash, canon, sig-message, verify-sig) and the cofactorless Ed25519 edge
vectors. P-256/P-384 vectors are outside Warrant 2 (SPEC §9) and are counted as
excluded by name, never as passed.

    python3 tests/primitives_test.py
"""
import base64
import hashlib
import json
import sys
from pathlib import Path

from world import ROOT, check, finish
from warrant import jcs, keys

PACK = ROOT / "third_party" / "primitives"


def manifest_ok():
    for line in (PACK / "MANIFEST.sha256").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if hashlib.sha256((PACK / name).read_bytes()).hexdigest() != digest:
            return False
    return True


def answer(cls, inp):
    if cls == "blob-hash":
        return {"hash": jcs.digest(base64.b64decode(inp["bytes_base64"]))}
    if cls == "canon":
        b = jcs.canon(inp["body"])
        return {"canon_hex": b.hex(), "warrant_id": jcs.digest(b)}
    if cls == "sig-message":
        return {"message_hex": keys.sig_message(inp["warrant_id"]).hex()}
    if inp.get("alg", "ed25519") != "ed25519":
        return None
    return {"valid": keys.verify(inp["key"], inp["sig"], keys.sig_message(inp["warrant_id"]))}


def main():
    check("P0", manifest_ok(), "the vendored pack matches its MANIFEST")
    # The case ids are spelled out so a claim can cite them (tools/claims.py finds a case by its literal id).
    for cls, cid in (("blob-hash", "P-blob-hash"), ("canon", "P-canon"), ("sig-message", "P-sig-message"),
                     ("verify-sig", "P-verify-sig")):
        vs = json.loads((PACK / "vectors" / f"{cls}.json").read_text())["vectors"]
        bad, excluded = [], []
        for v in vs:
            got = answer(cls, v["input"])
            if got is None:
                excluded.append(v["id"])
            elif any(got.get(k) != want for k, want in v["expect"].items()):
                bad.append(v["id"])
        check(cid, not bad, f"{cls}: {len(vs) - len(excluded)} vectors pass"
              + (f", {len(excluded)} excluded (not Ed25519)" if excluded else ""), bad)
    edge = json.loads((ROOT / "tests" / "vectors" / "ed25519-edge.json").read_text())["vectors"]
    wrong = [v["why"] for v in edge if keys.verify(v["key"], v["sig"], keys.sig_message(v["warrant_id"])) != v["valid"]]
    check("P-edge", len(edge) == 5 and not wrong, "cofactorless Ed25519 on the five edge signatures", wrong)
    return finish("PRIMITIVES")


if __name__ == "__main__":
    sys.exit(main())
