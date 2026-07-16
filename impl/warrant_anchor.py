#!/usr/bin/env python3
"""warrant-anchor — batch many warrants under one Merkle root, with per-warrant
inclusion proofs.

Anchoring every warrant individually to a public log or timestamp is absurd at
scale. Instead, take the WarrantIDs of a batch, build one Merkle tree, and anchor
only the ROOT (one OpenTimestamps stamp, one transparency-log entry, one on-chain
commitment). Anyone can later prove a single warrant was in that batch with a
short inclusion proof — without holding the batch.

The tree is RFC 6962 (Certificate Transparency / Sigstore): domain-separated leaf
and node hashes (`0x00` / `0x01` prefixes) over SHA-256, so a leaf can never be
forged into an interior node. This is the same primitive Sigstore's transparency
log uses — here it proves *action* provenance instead of artifact provenance.

    warrant-anchor root   <store>            -> the batch Merkle root (hex)
    warrant-anchor prove  <store> <wid>      -> inclusion proof (JSON) for one warrant
    warrant-anchor verify <wid> <proof.json> <root>   -> 0 if the warrant is in the batch

MIT. Pure standard library.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def _h(b):
    return hashlib.sha256(b).digest()


def leaf_hash(data):
    """RFC 6962 leaf hash: SHA-256(0x00 || data). `data` is the raw leaf bytes."""
    return _h(b"\x00" + data)


def node_hash(left, right):
    """RFC 6962 interior hash: SHA-256(0x01 || left || right)."""
    return _h(b"\x01" + left + right)


def _split(n):
    """Largest power of two strictly less than n (RFC 6962 k)."""
    k = 1
    while k << 1 < n:
        k <<= 1
    return k


def _root_of(hashes):
    """Merkle root of a list of already-computed leaf hashes (RFC 6962 split)."""
    n = len(hashes)
    if n == 1:
        return hashes[0]
    k = _split(n)
    return node_hash(_root_of(hashes[:k]), _root_of(hashes[k:]))


def merkle_root(leaves):
    """RFC 6962 Merkle Tree Hash over an ordered list of leaf-byte-strings.
    Returns 32 raw bytes. Empty list -> SHA-256 of the empty string (RFC 6962)."""
    if not leaves:
        return _h(b"")
    return _root_of([leaf_hash(d) for d in leaves])


def inclusion_proof(leaves, index):
    """RFC 6962 audit path for leaf `index`: a list of sibling hashes (hex),
    bottom-up, each tagged with the side it sits on ('L' or 'R' relative to the
    running hash). Verifiable with `verify_inclusion`."""
    if not (0 <= index < len(leaves)):
        raise IndexError("leaf index out of range")
    hashes = [leaf_hash(d) for d in leaves]
    path = []

    def build(hs, idx):
        n = len(hs)
        if n == 1:
            return
        k = _split(n)
        if idx < k:
            path.append(("R", _root_of(hs[k:]).hex()))   # sibling on the right
            build(hs[:k], idx)
        else:
            path.append(("L", _root_of(hs[:k]).hex()))    # sibling on the left
            build(hs[k:], idx - k)

    build(hashes, index)
    path.reverse()                       # bottom-up
    return path


def verify_inclusion(leaf_data, proof, root_hex):
    """Recompute the root from a leaf and its audit path; return True iff it
    equals `root_hex`. `proof` is the list from `inclusion_proof`."""
    cur = leaf_hash(leaf_data)
    for side, sib_hex in proof:
        sib = bytes.fromhex(sib_hex)
        if side == "R":
            cur = node_hash(cur, sib)
        elif side == "L":
            cur = node_hash(sib, cur)
        else:
            return False
    return cur.hex() == root_hex


# ---------- warrant-store integration ----------
def _record_ids(store_dir):
    """Sorted WarrantIDs (the record filenames) of a .warrants store."""
    recs = Path(store_dir) / "records"
    return sorted(p.stem for p in recs.glob("*.json"))


def anchor_store(store_dir):
    """Build the batch: a Merkle tree whose leaves are the store's WarrantIDs
    (raw 32-byte hashes). Returns {root, count, leaves}."""
    wids = _record_ids(store_dir)
    leaves = [bytes.fromhex(w) for w in wids]
    return {"root": merkle_root(leaves).hex(), "count": len(wids), "leaves": wids}


def store_proof(store_dir, wid):
    wids = _record_ids(store_dir)
    if wid not in wids:
        raise KeyError(f"{wid} not in store")
    leaves = [bytes.fromhex(w) for w in wids]
    idx = wids.index(wid)
    return {"wid": wid, "root": merkle_root(leaves).hex(),
            "proof": inclusion_proof(leaves, idx)}


# ---------- CLI ----------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="warrant-anchor",
                                 description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("root", help="print the batch Merkle root")
    r.add_argument("store")
    p = sub.add_parser("prove", help="inclusion proof (JSON) for one warrant")
    p.add_argument("store")
    p.add_argument("wid")
    v = sub.add_parser("verify", help="verify a warrant is in an anchored batch")
    v.add_argument("wid")
    v.add_argument("proof")
    v.add_argument("root")
    args = ap.parse_args(argv)

    def sdir(s):
        d = Path(s)
        return d if (d / "records").is_dir() else d / ".warrants"

    if args.cmd == "root":
        a = anchor_store(sdir(args.store))
        print(json.dumps(a))
    elif args.cmd == "prove":
        print(json.dumps(store_proof(sdir(args.store), args.wid)))
    elif args.cmd == "verify":
        proof_doc = json.loads(Path(args.proof).read_text())
        proof = proof_doc["proof"] if isinstance(proof_doc, dict) else proof_doc
        ok = verify_inclusion(bytes.fromhex(args.wid), proof, args.root)
        print("in-batch" if ok else "NOT in batch")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
