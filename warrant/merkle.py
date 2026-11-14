"""Merkle roots of a store, and proofs a reader checks against a root alone (docs/V3.md §16, stage 3).

A snapshot's `digest` hashes every line in one pass: it lets nobody prove anything about one record. Two trees
replace it for that purpose (the digest stays, as the snapshot's identity):

    records   the sorted record ids of the store's lines: a record's inclusion, or its absence;
    index     the reverse index, sorted by target: each id an `attest` or a `challenge` targets, with the sorted
              [kind, id] of every one targeting it. Its leaf for X says everything filed against X in this store;
              its absence says nothing is.

Hashing is RFC 9162's (§2.1): a leaf is SHA-256(0x00 || data), an inner node SHA-256(0x01 || left || right), the tree
over n leaves split at the largest power of two below n; the empty tree's root is SHA-256 of nothing. A records leaf's
data is the 32 bytes of the id; an index leaf's is the canonical JSON of [target, [[kind, id], ...]].

An inclusion proof is RFC 9162's audit path. An absence proof of key K is the inclusion of its neighbours: the leaf
before K and the leaf after it, at adjacent indices (or K below the first leaf, or above the last), so no leaf between
them can hold K. A proof says what is in, or not in, the tree under that root: never what is in no store anywhere
(`completeness` stays UNATTESTED; `absence` names the root, Codex on the plan, 2026-11-13).

Measured once (2026-11-13, the analysis session, live stores): a record's inclusion 384 B in warrant (3068 records); a
target's absence from the reverse index at most 704 B."""
import bisect
import hashlib

from . import jcs as C
from . import shapes as S

FORMAT = "merkle/1"
EMPTY = hashlib.sha256(b"").hexdigest()
SAID = ("attest", "challenge")


def _h(b):
    return hashlib.sha256(b).digest()


def leaf_hash(data):
    return _h(b"\x00" + data)


def _node(left, right):
    return _h(b"\x01" + left + right)


def _split(n):
    """The largest power of two strictly below n (n >= 2)."""
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def _root(hashes):
    if not hashes:
        return bytes.fromhex(EMPTY)
    if len(hashes) == 1:
        return hashes[0]
    k = _split(len(hashes))
    return _node(_root(hashes[:k]), _root(hashes[k:]))


def root(leaves):
    """The root (hex) of the tree over `leaves` (bytes each), in their order."""
    return _root([leaf_hash(d) for d in leaves]).hex()


def _path(hashes, i):
    if len(hashes) <= 1:
        return []
    k = _split(len(hashes))
    if i < k:
        return _path(hashes[:k], i) + [_root(hashes[k:])]
    return _path(hashes[k:], i - k) + [_root(hashes[:k])]


def path(leaves, i):
    """The audit path (hex, from the leaf up) of leaf `i` among `leaves`."""
    return [h.hex() for h in _path([leaf_hash(d) for d in leaves], i)]


def included(root_hex, size, i, data, audit):
    """Whether `data` is leaf `i` of a tree of `size` leaves with root `root_hex` (RFC 9162 §2.1.3.2)."""
    if not (isinstance(size, int) and isinstance(i, int) and 0 <= i < size and isinstance(audit, list)
            and all(S.hex64(x) for x in audit) and isinstance(data, bytes) and S.hex64(root_hex)):
        return False
    fn, sn, r = i, size - 1, leaf_hash(data)
    for p in audit:
        p = bytes.fromhex(p)
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = _node(p, r)
            if not fn & 1:
                while fn and not fn & 1:
                    fn, sn = fn >> 1, sn >> 1
        else:
            r = _node(r, p)
        fn, sn = fn >> 1, sn >> 1
    return sn == 0 and r.hex() == root_hex


# ---------------------------------------------------------------- the two trees of a store

def records_leaves(snap):
    """The sorted record ids of a snapshot's lines (as bytes, the leaves' data)."""
    return [bytes.fromhex(i) for i in sorted(snap.lines)]


def index_entries(snap):
    """[(target, [[kind, id], ...])] sorted by target: every attest and challenge of the snapshot by what it targets."""
    out = {}
    for i, envs in snap.lines.items():
        r = envs[0]["record"]
        t = (r.get("body") or {}).get("target") if isinstance(r.get("body"), dict) else None
        if r.get("kind") in SAID and S.hex64(t):
            out.setdefault(t, []).append([r["kind"], i])
    return [(t, sorted(v)) for t, v in sorted(out.items())]


def index_leaf(target, said):
    return C.canon([target, said])


def roots(snap):
    """{format, records, index, size: {records, index}} of a snapshot."""
    rec, idx = records_leaves(snap), [index_leaf(t, v) for t, v in index_entries(snap)]
    return {"format": FORMAT, "records": root(rec), "index": root(idx), "size": {"records": len(rec), "index": len(idx)}}


def _keyed(keys, leaves, key):
    """{root, size, key, in: {i, data, path} | None, before, after} over sorted `keys` with their `leaves`: the leaf of
    `key` when present, else its neighbours (absence)."""
    n, p = len(keys), bisect.bisect_left(keys, key)
    at = lambda j: {"i": j, "data": leaves[j].hex(), "path": path(leaves, j)}
    out = {"root": root(leaves), "size": n, "key": key, "in": None, "before": None, "after": None}
    if p < n and keys[p] == key:
        out["in"] = at(p)
    else:
        out["before"] = at(p - 1) if p > 0 else None
        out["after"] = at(p) if p < n else None
    return out


def prove_record(snap, rid):
    """The inclusion of record `rid` in the records tree, or its absence."""
    ids = sorted(snap.lines)
    return dict(_keyed(ids, [bytes.fromhex(i) for i in ids], rid), tree="records")


def prove_said(snap, target):
    """What the reverse index holds against `target`: its leaf (every attest and challenge targeting it), or that it
    holds none."""
    entries = index_entries(snap)
    return dict(_keyed([t for t, _ in entries], [index_leaf(t, v) for t, v in entries], target), tree="index")


def _key_of(tree, data):
    if tree == "records":
        return data.hex() if len(data) == 32 else None
    try:
        doc = C.loads(data)
    except (ValueError, RecursionError):
        return None
    return doc[0] if isinstance(doc, list) and len(doc) == 2 and S.hex64(doc[0]) else None


def check(proof, root_hex=None):
    """(holds, said) of a proof from prove_record / prove_said, against `root_hex` (its own `root` when None):
    `said` is the leaf's [[kind, id], ...] for an index leaf present, [] for a key absent from the index, True / False
    for a record in / not in the records tree. `holds` False: the proof does not show what it claims."""
    try:
        tree, key, n = proof["tree"], proof["key"], proof["size"]
        r = proof["root"] if root_hex is None else root_hex
        if tree not in ("records", "index") or not S.hex64(key) or r != proof["root"]:
            return False, None
        def leaf(x):
            data = bytes.fromhex(x["data"])
            return data, _key_of(tree, data), included(r, n, x["i"], data, x["path"])
        if proof["in"] is not None:
            data, k, ok = leaf(proof["in"])
            if not ok or k != key:
                return False, None
            if tree == "records":
                return True, True
            doc = C.loads(data)
            return True, doc[1]
        b, a = proof["before"], proof["after"]
        if n == 0:
            return (r == EMPTY and b is None and a is None), (False if tree == "records" else [])
        kb = ka = None
        if b is not None:
            _, kb, ok = leaf(b)
            if not ok or kb is None or not kb < key:
                return False, None
        if a is not None:
            _, ka, ok = leaf(a)
            if not ok or ka is None or not key < ka:
                return False, None
        adjacent = ((b is None and a is not None and a["i"] == 0) or (a is None and b is not None and b["i"] == n - 1)
                    or (b is not None and a is not None and a["i"] == b["i"] + 1))
        return adjacent, ((False if tree == "records" else []) if adjacent else None)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False, None
