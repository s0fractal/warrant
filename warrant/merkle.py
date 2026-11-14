"""Merkle roots of a store, and proofs a reader checks against a root alone (docs/V3.md §16, stage 3).

A snapshot's `digest` hashes every line in one pass: it lets nobody prove anything about one record. Two trees
replace it for that purpose (the digest stays, as the snapshot's identity):

    records   the sorted record ids of the store's lines: a record's inclusion, or its absence;
    index     the reverse index, sorted by target: each id an `attest` or a `challenge` targets, with the sorted
              [kind, id] of every one targeting it. Its leaf for X says everything filed against X in this store;
              its absence says nothing is.

Hashing is RFC 9162's (§2.1): a leaf is SHA-256(0x00 || data), an inner node SHA-256(0x01 || left || right), the tree
over n leaves split at the largest power of two below n; the empty tree's root is SHA-256 of nothing. A records leaf's
data is the 32 bytes of the id; an index leaf's is the 32 bytes of the target and the SHA-256 of the canonical JSON of
its [[kind, id], ...]: a neighbour in an absence proof costs its 64 bytes, and only the leaf asked about carries its
list (2026-11-14: with the whole list in every leaf, the proof of a frame was larger than the frame in 33 of 99
lineages of warrant's store, an absence there being two neighbours for three ids in four).

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
    return bytes.fromhex(target) + hashlib.sha256(C.canon(said)).digest()


def roots(snap):
    """{format, records, index, size: {records, index}} of a snapshot."""
    rec, idx = records_leaves(snap), [index_leaf(t, v) for t, v in index_entries(snap)]
    return {"format": FORMAT, "records": root(rec), "index": root(idx), "size": {"records": len(rec), "index": len(idx)}}


def _keyed(keys, leaves, key, lists=None):
    """{root, size, key, in: {i, data, path} | None, before, after} over sorted `keys` with their `leaves`: the leaf of
    `key` when present, else its neighbours (absence)."""
    n, p = len(keys), bisect.bisect_left(keys, key)
    at = lambda j: {"i": j, "data": leaves[j].hex(), "path": path(leaves, j)}
    out = {"root": root(leaves), "size": n, "key": key, "in": None, "before": None, "after": None}
    if p < n and keys[p] == key:
        out["in"] = dict(at(p), **({"said": lists[p]} if lists is not None else {}))
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
    return dict(_keyed([t for t, _ in entries], [index_leaf(t, v) for t, v in entries], target, [v for _, v in entries]),
                tree="index")


def _key_of(tree, data):
    if tree == "records":
        return data.hex() if len(data) == 32 else None
    return data[:32].hex() if len(data) == 64 else None


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
            said = proof["in"].get("said")
            if not (isinstance(said, list) and hashlib.sha256(C.canon(said)).digest() == data[32:]
                    and all(isinstance(x, list) and len(x) == 2 and x[0] in SAID and S.hex64(x[1]) for x in said)):
                return False, None
            return True, said
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


# ---------------------------------------------------------------- a set of index proofs, compact (witness/1 `said`)

def pack(proofs):
    """{hashes, proofs} of index proofs from prove_said, one per key, for a witness/1: every hash of every path once,
    in a table, and each path as the table's indices; each leaf as its [target, said] value, not as hex. The root, the
    size and the tree are the witness's (its snapshot names them), so they are not repeated. Measured on warrant's
    store (2026-11-14): the proof of a lineage's frame went from 2.4 times the frame's bytes (each proof whole, hex) to
    the figures docs/V3.md §16 gives."""
    table, out = {}, {}
    def ref(h):
        return table.setdefault(h, len(table))
    for key, p in sorted(proofs.items()):
        def leaf(x, said=False):
            if x is None:
                return None
            d = bytes.fromhex(x["data"])
            got = {"i": x["i"], "path": [ref(h) for h in x["path"]]}
            return dict(got, said=x["said"]) if said else dict(got, key=d[:32].hex(), digest=d[32:].hex())
        out[key] = {"in": leaf(p["in"], True), "before": leaf(p["before"]), "after": leaf(p["after"])}
    return {"hashes": [h for h, _ in sorted(table.items(), key=lambda kv: kv[1])], "proofs": out}


def unpack(packed, key, root_hex, size):
    """The prove_said form of `key`'s proof in a pack, at the witness's root and size; None when it has none or is
    malformed (then check() is never asked)."""
    try:
        hs, p = packed["hashes"], packed["proofs"][key]
        if not (isinstance(hs, list) and all(S.hex64(h) for h in hs) and isinstance(p, dict)
                and set(p) == {"in", "before", "after"}):
            return None
        def leaf(x, said=False):
            if x is None:
                return None
            want = {"i", "said", "path"} if said else {"i", "key", "digest", "path"}
            if not (isinstance(x, dict) and set(x) == want and isinstance(x["path"], list)
                    and all(type(j) is int and 0 <= j < len(hs) for j in x["path"])):
                raise ValueError("a leaf of a pack")
            path_ = [hs[j] for j in x["path"]]
            if said:
                return {"i": x["i"], "data": index_leaf(key, x["said"]).hex(), "said": x["said"], "path": path_}
            if not (S.hex64(x["key"]) and S.hex64(x["digest"])):
                raise ValueError("a neighbour of a pack")
            return {"i": x["i"], "data": x["key"] + x["digest"], "path": path_}
        return {"tree": "index", "root": root_hex, "size": size, "key": key,
                "in": leaf(p["in"], True), "before": leaf(p["before"]), "after": leaf(p["after"])}
    except (KeyError, TypeError, ValueError):
        return None

