#!/usr/bin/env python3
"""Tests for warrant_anchor — RFC 6962 Merkle batching.

  A. structure: n=1,2,3 roots match direct hand-computation via the primitives.
  B. domain separation: a leaf can't be forged into an interior node.
  C. round-trip: for many tree sizes, every leaf's inclusion proof verifies, and
     verification rejects a wrong leaf / tampered proof / wrong root.
  D. store integration: anchor a real warrant store; prove + verify a member;
     a non-member fails.

Run: python3 tests/anchor.py   (nonzero exit on any failure)
"""
import hashlib
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A = _load("warrant_anchor", "impl/warrant_anchor.py")
ok = []


def chk(cond, label, detail=""):
    ok.append(cond)
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")


def H(b):
    return hashlib.sha256(b).digest()


def test_structure():
    d = [bytes([i]) * 4 for i in range(3)]
    lh = [H(b"\x00" + x) for x in d]
    # n=1
    chk(A.merkle_root(d[:1]) == lh[0], "n=1 root = leaf hash")
    # n=2: node(leaf0, leaf1)
    exp2 = H(b"\x01" + lh[0] + lh[1])
    chk(A.merkle_root(d[:2]) == exp2, "n=2 root = node(leaf0,leaf1)")
    # n=3: split k=2 -> node( node(leaf0,leaf1), leaf2 )
    exp3 = H(b"\x01" + H(b"\x01" + lh[0] + lh[1]) + lh[2])
    chk(A.merkle_root(d[:3]) == exp3, "n=3 root = node(node(l0,l1),l2)")


def test_domain_separation():
    d0, d1 = b"left", b"right"
    root = A.merkle_root([d0, d1])
    # A forger who claims the two leaves are actually one interior node must NOT
    # be able to pass a leaf as a node: leaf and node hashes are prefix-separated.
    forged = H(A.leaf_hash(d0) + A.leaf_hash(d1))          # no 0x01 prefix
    chk(root.hex() != forged.hex(), "leaf/node domain separation (no 2nd-preimage)")
    chk(A.leaf_hash(d0) != A.node_hash(A.leaf_hash(d0), A.leaf_hash(d0)),
        "leaf hash != node hash")


def test_roundtrip():
    all_ok = True
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 16, 17, 33):
        leaves = [f"warrant-{i:03d}".encode() for i in range(n)]
        root = A.merkle_root(leaves).hex()
        for i in range(n):
            proof = A.inclusion_proof(leaves, i)
            if not A.verify_inclusion(leaves[i], proof, root):
                all_ok = False
                print(f"    n={n} idx={i} FAILED to verify")
            # wrong leaf must fail
            if A.verify_inclusion(b"not-a-member", proof, root):
                all_ok = False
                print(f"    n={n} idx={i} wrong leaf wrongly accepted")
    chk(all_ok, "all inclusion proofs verify; wrong leaves rejected (n up to 33)")

    # tamper: flip a proof sibling, and a wrong root -> reject
    leaves = [bytes([i]) for i in range(7)]
    root = A.merkle_root(leaves).hex()
    proof = A.inclusion_proof(leaves, 3)
    chk(A.verify_inclusion(leaves[3], proof, root), "baseline proof for n=7 idx=3")
    if proof:
        s, h = proof[0]
        bad = list(proof)
        bad[0] = (s, ("0" if h[0] != "0" else "1") + h[1:])
        chk(not A.verify_inclusion(leaves[3], bad, root), "tampered sibling rejected")
    chk(not A.verify_inclusion(leaves[3], proof, "00" * 32), "wrong root rejected")


def test_store_integration():
    pack = os.path.join(ROOT, "demos", "air-canada", "pack", ".warrants")
    if not os.path.isdir(pack):
        chk(True, "store integration SKIPPED (no air-canada pack)")
        return
    a = A.anchor_store(pack)
    chk(a["count"] >= 2 and len(a["root"]) == 64, "anchored air-canada store",
        f"count={a['count']}")
    wid = a["leaves"][0]
    pr = A.store_proof(pack, wid)
    chk(A.verify_inclusion(bytes.fromhex(wid), pr["proof"], pr["root"]),
        "a warrant proves inclusion against the batch root")
    chk(pr["root"] == a["root"], "proof root == batch root")
    # a warrant NOT in the batch cannot prove inclusion
    outsider = "ff" * 32
    chk(not A.verify_inclusion(bytes.fromhex(outsider), pr["proof"], pr["root"]),
        "non-member cannot prove inclusion")


def main():
    test_structure()
    test_domain_separation()
    test_roundtrip()
    test_store_integration()
    print("\n" + ("ANCHOR: ALL PASS" if all(ok) else "ANCHOR: FAILURES PRESENT"))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
