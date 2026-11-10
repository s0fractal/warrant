#!/usr/bin/env python3
"""Warrant 3 package verifier: one file, the standard library only (docs/VERIFY.md).

You were handed a `package/3` file: the records a result rests on and the verdicts on them. Copy this file anywhere
and ask whether you may rely on it, under your own trust (which keys are whose) and profile (who holds which role):

    python3 -I warrant_verify.py PACKAGE --trust TRUST.json --profile PROFILE.json [--require ROOT ...]
                                 [--checkout DIR] [--as-of N] [--max-bytes N]
    python3 -I warrant_verify.py PACKAGE --config V3.json          # a file holding both: {trust, profile}

The exit status is the answer: 0 only when every root asked for is one you may rely on now; 1 when one is not, or
the package was refused; 2 for a command line or a file of your own that cannot be read; 3 for an error of this file
itself, never the code of a refusal. Standard output is one line of canonical JSON: per root its lineage, its guard,
who accepted it under which of your roles, the challenges, and the files its acceptances name; and two lists in
sentences, `established` and `not_established`. No package can show what its sender left out, and that is always in
the second list.

It needs no installation, no store, no network and no Git, and writes nothing. `--checkout DIR` asks Git for the
tree of DIR's HEAD, to compare the files an acceptance names with it; without Git they read NOT_CHECKED, never fresh.
`-I` keeps Python from importing a file that happens to lie beside this one.

This file is built, not written: `python3 tools/build_verify.py` puts the modules of the `warrant` package that
`warrant verify` runs (SOURCES below, each byte for byte, its SHA-256 in DIGESTS) after the few functions here: an
Ed25519 verification for an interpreter without the `cryptography` library, and the loader. `warrant verify` of the
installed package gives the same bytes on the same input; tests/verify_test.py holds both to that, and this file to
its build."""
import hashlib
import sys
import types

# Built by tools/build_verify.py from the files below, each byte for byte; edit those and build again.
DIGESTS = {
    "warrant/jcs.py": "edf1c844a8471a79b4ef96a7d28735d0a348c0cf972da4ea0ce701c88610b250",
    "warrant/graph.py": "308221cf07c1873feb1ae937312035a3fe590f880b9201fbdeb9c3387219daee",
    "warrant/shapes.py": "f03275222b2b4a3c3265eaa53ab6454ca47ef91189bd521d888d677773ff388d",
    "warrant/keys.py": "1a1dcb743779d2f3488df87e7ddef9328312b6e5f9549ad639f2c28c8347ee3a",
    "warrant/pins.py": "b5b355e1f51b0cb4379c190674561fcff4fe5c70d0eda034dce93e1fd671a254",
    "warrant/records.py": "411937f2642656a77ece5dc77e7b1b407fa55a9e823a883870ea9e3ceb45a0c3",
    "warrant/store.py": "81a733eeca5e452f21213478c093c426df82a5560fbe0d877d0223b23e720137",
    "warrant/engine.py": "228fcb2f9264c34f3880c1a80fca2c138b9bcd59ecace848b0f3cd6f599e2e50",
    "warrant/verify.py": "bd91ee2f73f930fe98d9f4ac58143d45235eaa78fc5b6b7f13a7fba3dad77f5a",
}
ORDER = ('jcs', 'graph', 'shapes', 'keys', 'pins', 'records', 'store', 'engine', 'verify')
SOURCES = {}

SOURCES["jcs"] = r'''"""Canonical JSON (SPEC §2): RFC 8785 over integers, strings, booleans, null,
arrays and objects, plus a strict reader for the same domain."""
import hashlib
import json

MAX_INT = 2**53 - 1
MAX_DEPTH = 256


class NotCanonical(ValueError):
    """Bytes or values outside the encoding of SPEC §2."""


def _scalar(v):
    """The JCS text of a scalar, or None if `v` is not one."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        if not -MAX_INT <= v <= MAX_INT:
            raise NotCanonical("integer outside ±(2^53-1)")
        return str(v)
    if isinstance(v, str):
        _check_text(v)
        return json.dumps(v, ensure_ascii=False)
    return None


def _push_container(stack, v, depth):
    """Push the tokens of a list or object, last first."""
    if isinstance(v, list):
        stack.append(("s", "]", 0))
        for i in range(len(v) - 1, -1, -1):
            stack.append(("v", v[i], depth + 1))
            if i:
                stack.append(("s", ",", 0))
        stack.append(("s", "[", 0))
        return
    if not (isinstance(v, dict) and all(isinstance(k, str) for k in v)):
        raise NotCanonical(f"not a JSON value of this domain: {type(v).__name__}")
    keys = sorted(v, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
    stack.append(("s", "}", 0))
    for i in range(len(keys) - 1, -1, -1):
        _check_text(keys[i])
        stack.extend((("v", v[keys[i]], depth + 1), ("s", ":", 0), ("s", json.dumps(keys[i], ensure_ascii=False), 0)))
        if i:
            stack.append(("s", ",", 0))
    stack.append(("s", "{", 0))


def canon(value):
    """RFC 8785 bytes. Object members are ordered by UTF-16 code units; integers
    outside ±(2^53-1), floats and lone surrogates are refused. Iterative, so
    nesting depth is bounded by MAX_DEPTH, not by the interpreter's stack."""
    out = []
    stack = [("v", value, 0)]
    while stack:
        tag, v, depth = stack.pop()
        if tag == "s":
            out.append(v)
            continue
        if depth > MAX_DEPTH:
            raise NotCanonical("nested too deep")
        text = _scalar(v)
        if text is not None:
            out.append(text)
        else:
            _push_container(stack, v, depth)
    return "".join(out).encode("utf-8")


def _check_text(s):
    if any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        raise NotCanonical("lone surrogate")


def _pairs(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise NotCanonical(f"duplicate member {k!r}")
        d[k] = v
    return d


def _constant(name):
    raise NotCanonical(f"not JSON: {name}")


def _float(text):
    raise NotCanonical("floats are not admitted")


def loads(raw):
    """Parse bytes that MUST be the canonical encoding of what they parse to."""
    if not isinstance(raw, (bytes, bytearray)):
        raise NotCanonical("bytes expected")
    raw = bytes(raw)
    if raw.count(b"[") + raw.count(b"{") > MAX_DEPTH * 4 and _depth(raw) > MAX_DEPTH:
        raise NotCanonical("nested too deep")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as e:
        raise NotCanonical(f"not JSON: {type(e).__name__}") from None
    if canon(value) != raw:
        raise NotCanonical("bytes are not canonical")
    return value


def _depth(raw):
    depth = best = 0
    in_str = esc = False
    for b in raw:
        if in_str:
            if esc:
                esc = False
            elif b == 0x5C:
                esc = True
            elif b == 0x22:
                in_str = False
        elif b == 0x22:
            in_str = True
        elif b in (0x5B, 0x7B):
            depth += 1
            best = max(best, depth)
        elif b in (0x5D, 0x7D):
            depth -= 1
    return best


def digest(data):
    return hashlib.sha256(data).hexdigest()


def doc_id(value):
    return digest(canon(value))
'''

SOURCES["graph"] = r'''"""Queries over the record graph of one assessment report (docs/V3.md §10: nodes and typed edges read
from `refs`, `lineage`, `guard.requires`, `prev` and an attest's or challenge's target, never from text).
Pure functions of reports: the agent operation `graph`, `warrant status` and the repository's tools/graph.py
call the same ones. Every state shown is the report's, never recomputed.

  around(rep, id)          a node, its lineage and its edges in and out
  path(rep, id)            what a record rests on (edges out, transitively; `prev` left out)
  why(rep, id)             what rests on a record (edges in, transitively)
  frontier(rep, profile, actor)   what waits for the actor: versions it may attest, its own pending
                           versions and its challenged lineages
  delta(rep0, rep1)        nodes added and removed, lineages whose state or reliance changed
  impact(rep0, rep1)       the lineages the changed records bear on, and what rests on those
  ledger(rep, recs)        the witness ledger: per actor, acceptances later refuted, challenges that replayed
  answer(rep, query, data, adapter)   {root, lens, query, data}: the same lens over the same root gives
                           the same bytes, so a result may be cached by (lens, root) and re-derived

`root` is the snapshot digest; `lens` the content address of everything else that decides a result:
the engine's code, the adapter's, the trust, the profile and the query."""
from . import jcs as C

WALK = ("lineage", "requires", "ref", "attest", "challenge")       # `prev` orders a writer's chain; it is no dependency
MAX_NODES = 2000


def index(rep):
    """({id: node}, {id: [(rel, to)]}, {id: [(rel, from)]}) of a report's graph."""
    nodes = {n[0]: {"id": n[0], "kind": n[1], "schema": n[2], "actor": n[3], "at": n[4], "basis": n[5]}
             for n in rep["graph"]["nodes"]}
    out, into = {}, {}
    for a, rel, b in rep["graph"]["edges"]:
        out.setdefault(a, []).append((rel, b))
        into.setdefault(b, []).append((rel, a))
    return nodes, out, into


def lineage_of(rep, i):
    """The root of the lineage version `i` is in, or None."""
    for root, lin in rep["lineages"].items():
        if i in lin["versions"]:
            return root
    return None


def describe(rep, nodes, i):
    n = dict(nodes.get(i) or {"id": i, "kind": "unavailable"})       # no record of it in this report: never "does not exist"
    if i in rep["versions"]:
        n["guard"] = rep["versions"][i]
        root = lineage_of(rep, i)
        lin = rep["lineages"][root]
        n["lineage"] = {"root": root, "state": lin["state"], "reliance": lin["reliance"], "leaf": lin["leaf"],
                        "effective": lin["effective"], "verdict": lin["verdict"]}
    if i in rep["challenges"]:
        n["challenge"] = rep["challenges"][i]
    return n


def around(rep, i):
    nodes, out, into = index(rep)
    return {"node": describe(rep, nodes, i), "out": sorted([r, b] for r, b in out.get(i, [])),
            "in": sorted([r, a] for r, a in into.get(i, []))}


def _walk(rep, i, edges):
    nodes, out, into = index(rep)
    adj = out if edges == "out" else into
    seen, order, todo = {i}, [], [i]
    while todo and len(order) < MAX_NODES:
        cur = todo.pop(0)
        for rel, nxt in sorted(adj.get(cur, [])):
            if rel in WALK and nxt not in seen:
                seen.add(nxt)
                order.append(nxt)
                todo.append(nxt)
    return {"from": i, "nodes": [describe(rep, nodes, x) for x in order], "complete": not todo}


def path(rep, i):
    return _walk(rep, i, "out")


def why(rep, i):
    return _walk(rep, i, "in")


def frontier(rep, profile, actor):
    """What waits for `actor` in this report: `attest` the lineage leaves whose guard waits only for attests by roles
    the actor holds (no open requirement, not its own, not yet attested or challenged by it); `pending` its own
    leaves whose guard waits; `challenged` its lineages a counted challenge holds."""
    roles = {r for r, actors in profile["roles"].items() if actor in actors}
    nodes, _, into = index(rep)
    acted = {b for b, ins in into.items() for rel, a in ins if rel in ("attest", "challenge") and nodes[a]["actor"] == actor}
    attest, pending = [], []
    for root, lin in sorted(rep["lineages"].items()):
        v = lin["leaf"]           # the latest version: an earlier pending one was replaced by it
        g = rep["versions"].get(v) or {"guard": None}
        if g["guard"] != "PENDING":
            continue
        if nodes[v]["actor"] == actor:
            pending.append(v)
        elif v not in acted and g["short"] and not g["open"] and roles & set(g["roles"]):
            attest.append({"version": v, "lineage": root, "schema": lin["schema"], "waiting": g["waiting"]})
    challenged = [root for root, lin in sorted(rep["lineages"].items())
                  if lin["reliance"] == "CHALLENGED" and lin["actor"] == actor]
    return {"actor": actor, "roles": sorted(roles), "attest": attest, "pending": pending, "challenged": challenged}


def delta(rep0, rep1):
    n0, n1 = {n[0] for n in rep0["graph"]["nodes"]}, {n[0] for n in rep1["graph"]["nodes"]}
    changed = sorted(L for L, lin in rep1["lineages"].items() if L in rep0["lineages"]
                     and (rep0["lineages"][L]["state"], rep0["lineages"][L]["reliance"], rep0["lineages"][L]["leaf"])
                     != (lin["state"], lin["reliance"], lin["leaf"]))
    return {"added": sorted(n1 - n0), "removed": sorted(n0 - n1), "changed": changed,
            "lineages_added": sorted(set(rep1["lineages"]) - set(rep0["lineages"])),
            "lineages_removed": sorted(set(rep0["lineages"]) - set(rep1["lineages"]))}


def impact(rep0, rep1):
    """The lineages the records added or removed between two reports bear on (a version's own, an attest's or a
    challenge's target's), each with what rests on it in the later report (why), roots of other lineages only."""
    d = delta(rep0, rep1)
    touched = set(d["changed"]) | set(d["lineages_added"]) | set(d["lineages_removed"])
    for rep, ids in ((rep1, d["added"]), (rep0, d["removed"])):
        _, out, _ = index(rep)
        for i in ids:
            for x in [i] + [b for rel, b in out.get(i, []) if rel in ("attest", "challenge")]:
                root = lineage_of(rep, x)
                if root:
                    touched.add(root)
    out = []
    for L in sorted(touched):
        rep = rep1 if L in rep1["lineages"] else rep0
        lin = rep["lineages"][L]
        rests = sorted({lineage_of(rep, n["id"]) for n in why(rep, L)["nodes"]} - {None, L})
        out.append({"lineage": L, "schema": lin["schema"], "state": lin["state"], "reliance": lin["reliance"],
                    "gone": L not in rep1["lineages"], "rests_on_it": rests})
    return {"delta": d, "lineages": out}


def ledger(rep, recs=None):
    """The witness ledger, per actor: `accepted`, the versions whose guard the actor's acceptance counts toward;
    `refuted`, of those, [version, challenge] where a replayer attested `reproduces` on that challenge with `on` that
    version *later* than one of the actor's acceptances of it: the acceptance cites neither the challenge nor that
    replay, and is dated no later than the replay (Codex challenge on c1cace09dd7c: an acceptance made after the
    refutation, citing it, was read as refuted); `challenged`, the challenges the actor filed; `replayed`, of those, the
    ones a replayer reproduced on their own target. Read from the report (versions' accepted_by, challenges' replays,
    the graph, the records' refs and dates): it grants nothing, and no rule reads it. `at` is each filer's own word, so
    "later" is read from it where no citation fixes the order. A challenge answered without a replay (a successor
    accepted) credits nobody here."""
    recs = rep.get("_recs", {}) if recs is None else recs     # {id: record}: a repository's report carries it
    _, _, into = index(rep)
    actor = {n[0]: n[3] for n in rep["graph"]["nodes"]}
    rows, reproduced = {}, {}
    row = lambda a: rows.setdefault(a, {"accepted": [], "refuted": [], "challenged": [], "replayed": []})
    for c, x in sorted(rep["challenges"].items()):
        row(actor[c])["challenged"].append(c)
        if any(on == x["target"] and v == "reproduces" for on, v, _ in x["replays"]):
            row(actor[c])["replayed"].append(c)
            replayers = {a for on, v, a in x["replays"] if on == x["target"] and v == "reproduces"}
            runs = [i for rel, i in into.get(c, []) if rel == "attest" and i in recs and recs[i]["actor"] in replayers
                    and recs[i]["body"].get("verdict") == "reproduces" and recs[i]["body"].get("on") == x["target"]]
            reproduced.setdefault(x["target"], []).append((c, runs))
    for v, g in sorted(rep["versions"].items()):
        for a in g["accepted_by"]:
            row(a)["accepted"].append(v)
            mine = [recs[i] for rel, i in into.get(v, []) if rel == "attest" and i in recs and recs[i]["actor"] == a
                    and recs[i]["body"].get("verdict") == "accept"]
            row(a)["refuted"] += [[v, c] for c, runs in reproduced.get(v, [])
                                  if any(c not in m["refs"] and r not in m["refs"] and m["at"] <= recs[r]["at"]
                                         for m in mine for r in runs)]
    return dict(sorted(rows.items()))

def answer(rep, query, data, adapter):
    lens = C.doc_id({"code": rep["code"], "adapter": adapter, "trust": rep["trust"], "profile": rep["profile"],
                     "query": query, **({"checkout": rep["checkout"]} if "checkout" in rep else {})})
    return {"root": rep["snapshot"], "lens": lens, "query": query, "data": data}
'''

SOURCES["shapes"] = r'''"""The lexical shapes of SPEC §2-§3, each defined once.

A value is checked against its shape before anything reads it. Every module that checks one
of these shapes imports it from here: warrant, warrant_agent and the tools. Before this module
existed, fourteen definitions of these four shapes (hex64, hex128, a 32-digit token, a question
reference) and of the actor-id predicate lived in eleven modules, and one defect of the family,
`$` used where `\\Z` was meant, had to be fixed at fourteen sites (AMEND 2 of #164). Each pattern is
anchored with `\\Z`. With `.match`, `$` also matches before a final newline, so a 64-character
id followed by "\\n" passed. Digits are written [0-9], never \\d, because \\d matches any
Unicode digit. Hex is lowercase."""
import re
import unicodedata

HEX = re.compile(r"^[0-9a-f]*\Z")              # lowercase hex of any length (hex_of gives it one)
HEX32 = re.compile(r"^[0-9a-f]{32}\Z")        # a view token (warrant_agent.views)
HEX64 = re.compile(r"^[0-9a-f]{64}\Z")        # a record id, a blob address, an Ed25519 public key
HEX128 = re.compile(r"^[0-9a-f]{128}\Z")      # an Ed25519 signature
# A question reference: "<transition id>:<index of its opened question>", the index without leading zeros.
QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})\Z")  # NOSONAR S6353: \d would admit any Unicode digit
# A citation of a record in another store: "<store>:<record id>"; the store is a name a repository or a Home gives it.
CITATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,127}:[0-9a-f]{64}\Z")
MAX_ACTOR = 200
# Unicode White_Space outside Cc (Cc is refused anywhere in an actor id): Zs, Zl, Zp.
EDGE_SPACE = ("Zs", "Zl", "Zp")


def hex64(v):
    """True iff `v` is a string of exactly 64 lowercase hex digits."""
    return isinstance(v, str) and HEX64.match(v) is not None


def hex128(v):
    """True iff `v` is a string of exactly 128 lowercase hex digits."""
    return isinstance(v, str) and HEX128.match(v) is not None


def hex_of(v, n):
    """True iff `v` is a string of exactly `n` lowercase hex digits (a git object id: n = 40 or 64)."""
    return isinstance(v, str) and len(v) == n and HEX.match(v) is not None


def qref(v):
    """True iff `v` is a question reference (QREF)."""
    return isinstance(v, str) and QREF.match(v) is not None


def citation(v):
    """True iff `v` is a citation (CITATION): the id names the record, the store part says where the citer saw it."""
    return isinstance(v, str) and CITATION.match(v) is not None


def actor_problem(v):
    """None if `v` is an actor id (SPEC §3), else the reason it is not, phrased to follow the
    member's name. An actor id is a non-empty string of at most 200 code points, in NFC, with
    no control character (Cc) and no white space at either end. Nothing here asks what the
    actor is: a person, a model, a program and a rule have ids of the same shape."""
    if not (isinstance(v, str) and v and len(v) <= MAX_ACTOR):
        return f"must be a string ≤ {MAX_ACTOR}"
    if not unicodedata.is_normalized("NFC", v):
        return "must be in Unicode NFC"
    if any(unicodedata.category(c) == "Cc" for c in v):
        return "must not contain a control character"
    if unicodedata.category(v[0]) in EDGE_SPACE or unicodedata.category(v[-1]) in EDGE_SPACE:
        return "must not begin or end with white space"
    return None


def is_actor(v):
    """True iff `v` is an actor id (actor_problem)."""
    return actor_problem(v) is None
'''

SOURCES["keys"] = r'''"""Ed25519 keys and the record signature (SPEC §3).

A key binding authenticates an actor's records. It authorizes nothing (SPEC §6)."""
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import shapes as S

SIG_DOMAIN = b"warrant-sig-v1:"

_P = (1 << 255) - 19
# Small-order points and the non-canonical encodings of the x=0 torsion points:
# a key from this set lets a forged signature verify for many messages.
_WEAK = {bytes.fromhex(h) for h in (
    "0100000000000000000000000000000000000000000000000000000000000000",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
    "0100000000000000000000000000000000000000000000000000000000000080",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
)}


def weak_public_key(raw):
    if len(raw) != 32 or raw in _WEAK:
        return True
    return (int.from_bytes(raw, "little") & ((1 << 255) - 1)) >= _P


def sig_message(record_id):
    return SIG_DOMAIN + bytes.fromhex(record_id)


def key_id(public_hex):
    return hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()


def verify(public_hex, sig_hex, message):
    """True iff `sig_hex` is a valid Ed25519 signature of `message` by a strong key."""
    if not (S.hex64(public_hex) and S.hex128(sig_hex)):
        return False
    raw = bytes.fromhex(public_hex)
    if weak_public_key(raw):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(raw).verify(bytes.fromhex(sig_hex), message)
        return True
    except (InvalidSignature, ValueError):
        return False


class Key:
    """A private signing key held by its owner. Never written into a store."""

    def __init__(self, sk):
        self._sk = sk
        self.public = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        self.id = key_id(self.public)

    @classmethod
    def generate(cls):
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_seed_hex(cls, seed_hex):
        return cls(Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex.strip())))

    def seed_hex(self):
        return self._sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                      serialization.NoEncryption()).hex()

    def sign(self, message):
        return self._sk.sign(message).hex()
'''

SOURCES["pins"] = r'''"""Pins: the bytes an acceptance names, compared with a Git tree of the receiver's (G14).

An acceptance names its `files`, {path: git blob} (a symlink's as `link:<blob>`). Each is compared with one commit's
tree:

    UNCHANGED  the same bytes at the same path;
    MOVED      the path is gone from the tree and the same bytes are at another path;
    CHANGED    other bytes at the path, with the first commit after the accepted one from which the bytes were not
               those (a commit changing only a mode, or one undone later, is not it);
    GONE       the path is gone from the tree and those bytes are nowhere in it;
    UNKNOWN    the acceptance names no files, or not as {path: blob}: nothing can be compared.

`warrant drift` (warrant.drift) reads a repository's claims through this, and `warrant verify` (warrant.verify) the
acceptances behind a package's roots. It reads Git's trees and history and runs nothing of the repository's; the
paths and commits come from records, so only a full commit id reaches Git and a path is literal."""
import subprocess

from . import shapes as S

FRESH = ("UNCHANGED", "MOVED")


def git(root, *a, raw=False):
    # NOSONAR S8705: every option is a caller's literal; a commit or object id read from a record is checked as a full
    # hex id before it reaches Git (shapes.hex_of), and a path read from one follows "--" under --literal-pathspecs
    out = subprocess.run(["git", "-C", str(root), *a], capture_output=True, check=True).stdout  # NOSONAR S8705
    return out if raw else out.decode().strip()


def blobs(root, commit):
    """{path: git blob} of `commit`'s whole tree, a symlink's as `link:<blob>`: its blob is its target's name, and the
    same id as a regular file holding that name would read other bytes (Codex finding ea6300ecf5d5)."""
    rows = git(root, "ls-tree", "-r", "-z", "--full-tree", commit, raw=True).decode().split("\0")
    return {r.split("\t", 1)[1]: ("link:" if r.startswith("120000 ") else "") + r.split()[2] for r in rows if r}


def paths_of(head):
    """{blob: path} of a tree's {path: blob}: where a blob is now, the first of its paths in order."""
    return {b: p for p, b in sorted(head.items(), reverse=True)}


def unreadable(files):
    """Why an acceptance's `files` cannot be compared with any tree, or None."""
    if not files:
        return "the acceptance names no files"
    if not (isinstance(files, dict) and all(isinstance(b, str) for b in files.values())):
        return "the acceptance's files are not {path: blob}"
    return None


def fresh(tree, path, blob):
    """Whether a tree ({path: blob}, as blobs spells it) holds an accepted file's bytes: at its path, or, the path
    gone, at another (moved). Only the bytes count: a commit changing a file's mode alone changes nothing here."""
    now = tree.get(path)
    return now == blob or (now is None and blob in tree.values())


def first_change(root, commit, path, blob, head="HEAD"):
    """The commit since which `path` has not held `blob` (`fresh`), on the way from `commit` to `head`: of the commits
    that changed the path or the number of copies of those bytes in the tree, the first after the last one at which the
    file read fresh again (deleted then restored, moved with its bytes), and never one that changed only its mode
    (Codex finding e895d8cad992). None when none is found: the commit is not in this clone, or a merge brought the
    bytes. `commit`, `path` and `blob` come from a record: only a commit id and an object id reach Git, and the path
    is literal."""
    if not S.hex_of(commit, 40):
        return None
    oid = blob[len("link:"):] if blob.startswith("link:") else blob
    try:
        order = git(root, "rev-list", "--reverse", "--topo-order", f"{commit}..{head}").splitlines()
        touched = set(git(root, "--literal-pathspecs", "log", "--format=%H", f"{commit}..{head}", "--", path).splitlines())
        if S.hex_of(oid, 40):
            touched |= set(git(root, "log", "--format=%H", f"--find-object={oid}", f"{commit}..{head}").splitlines())
        since = None
        for c in reversed([c for c in order if c in touched]):
            if fresh(blobs(root, c), path, blob):
                break
            since = c
    except subprocess.CalledProcessError:
        return None
    return since


def compare(root, commit, files, head, where, at="HEAD", memo=None):
    """[(verdict, path, detail)] of an acceptance's `files` against HEAD (`head`, {path: blob}; `where`, {blob: path}).
    `memo`, one answer's: first_change once per (commit, path, blob), however many claims name them."""
    memo = {} if memo is None else memo
    why = unreadable(files)
    if why:
        return [("UNKNOWN", "", why)]
    out = []
    for p, blob in sorted(files.items()):
        now = head.get(p)
        if now == blob:
            out.append(("UNCHANGED", p, ""))
        elif now is None and blob in where:
            out.append(("MOVED", p, f"now at {where[blob]}"))
        else:
            if (commit, p, blob) not in memo:
                memo[commit, p, blob] = first_change(root, commit, p, blob, at)
            x = memo[commit, p, blob]
            since = f"since {x[:12]}" if x else f"since {str(commit)[:12]}"
            out.append(("CHANGED", p, since) if now else ("GONE", p, f"not at HEAD, {since}"))
    return out


def verdict(rows):
    """One acceptance's verdict from its rows: UNCHANGED when every file is fresh, UNKNOWN when nothing could be
    compared, else CHANGED."""
    words = {v for v, _, _ in rows}
    if words <= set(FRESH):
        return "UNCHANGED"
    return "UNKNOWN" if words == {"UNKNOWN"} else "CHANGED"
'''

SOURCES["records"] = r'''"""The Warrant 3 record (docs/V3.md §2): one envelope, four kinds, the guard's shape and the
schema field types. Canonical bytes and Ed25519 are Warrant 2's jcs.py and keys.py, unchanged."""
from warrant import jcs as C
from warrant import keys as K
from warrant import shapes as S

VERSION = "3"
KINDS = ("schema", "entity", "attest", "challenge")
MEMBERS = ("warrant", "kind", "actor", "at", "prev", "schema", "lineage", "refs", "guard", "body")
GUARD = ("quorum", "roles", "match", "requires")
SIG_DOMAIN = b"warrant-sig-v3:"
BODY_MAX = 16384
LINE_MAX = 65536
TYPES = ("str", "int", "bool", "strs", "ref", "refs", "obj")
MIGRATION = "migration@1"       # the one schema name the core reserves (§9)


class Invalid(ValueError):
    pass


def need(ok, why):
    if not ok:
        raise Invalid(why)


def is_list(v, item, sorted_=False):
    return isinstance(v, list) and all(item(x) for x in v) and (not sorted_ or v == sorted(set(v)))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def guard_problem(g):
    """Why `g` is not a guard, or None."""
    if not (isinstance(g, dict) and set(g) == set(GUARD)):
        return f"a guard has exactly {list(GUARD)}"
    if not (is_int(g["quorum"]) and g["quorum"] >= 0 and is_list(g["roles"], S.is_actor, True)
            and isinstance(g["match"], dict) and is_list(g["requires"], S.hex64, True)):
        return "guard: quorum >= 0, roles a sorted list of names, match an object, requires sorted ids"
    return None


def check(r):
    """Raise Invalid unless `r` is a well-formed v3 record (its body is checked against its schema
    by the engine, which alone knows the schemas the receiver counts)."""
    need(isinstance(r, dict) and set(r) == set(MEMBERS), f"a record has exactly {list(MEMBERS)}")
    need(r["warrant"] == VERSION and r["kind"] in KINDS, "warrant must be \"3\" and kind one of " + "/".join(KINDS))
    need(S.is_actor(r["actor"]), "actor is not an actor id")
    need(is_int(r["at"]) and r["at"] >= 0, "at is a non-negative integer")
    need(r["prev"] is None or S.hex64(r["prev"]), "prev is null or a record id")
    need(r["lineage"] is None or S.hex64(r["lineage"]), "lineage is null or a record id")
    need(is_list(r["refs"], S.hex64, True), "refs is a sorted list of distinct hex64")
    need(isinstance(r["body"], dict) and len(C.canon(r["body"])) <= BODY_MAX, f"body is an object of at most {BODY_MAX} bytes")
    need(r["guard"] is None or guard_problem(r["guard"]) is None, str(guard_problem(r["guard"])))
    if r["kind"] == "schema":
        need(r["schema"] is None, "a schema record has no schema")
    else:
        need(r["schema"] is None or (isinstance(r["schema"], str) and 0 < len(r["schema"]) <= 100), "schema is a name")
    if r["kind"] == "entity":
        need(r["schema"] is not None, "an entity names its schema")
    if r["kind"] in ("attest", "challenge"):
        need(S.hex64(r["body"].get("target")) and r["body"]["target"] in r["refs"] and r["lineage"] is None
             and r["guard"] is None, "an attest or challenge names body.target, in refs, and has no lineage or guard")


def record(kind, actor, at, body, schema=None, lineage=None, refs=(), guard=None, prev=None):
    r = {"warrant": VERSION, "kind": kind, "actor": actor, "at": at, "prev": prev, "schema": schema,
         "lineage": lineage, "refs": sorted(set(refs)), "guard": guard, "body": body}
    check(r)
    return r


def guard(quorum=0, roles=(), match=None, requires=()):
    return {"quorum": quorum, "roles": sorted(set(roles)), "match": dict(match or {}), "requires": sorted(set(requires))}


def named_key(r):
    """The key a challenge's actor names itself by (`key:<public key>`, §5), or None: any other record's actor is
    a name a trust binds."""
    a = r["actor"]
    return a[4:] if r["kind"] == "challenge" and a.startswith("key:") else None


def rid(r):
    return C.doc_id(r)


def line(r, key=None):
    """The stored line of `r`, signed by `key` (None: a migrated record, sig null)."""
    i = rid(r)
    sig = None if key is None else {"key": key.id, "ed25519": key.sign(SIG_DOMAIN + bytes.fromhex(i))}
    return i, C.canon({"record": r, "sig": sig}) + b"\n"


def verifies(r_id, sig, public):
    return K.verify(public, sig["ed25519"], SIG_DOMAIN + bytes.fromhex(r_id)) and sig["key"] == K.key_id(public)


def type_ok(t, v):
    """A body value against a schema field type (§4); `?` admits null."""
    if t.endswith("?"):
        if v is None:
            return True
        t = t[:-1]
    return {"str": lambda: isinstance(v, str), "int": lambda: is_int(v), "bool": lambda: isinstance(v, bool),
            "strs": lambda: is_list(v, lambda x: isinstance(x, str)), "ref": lambda: S.hex64(v),
            "refs": lambda: is_list(v, S.hex64), "obj": lambda: True}.get(t, lambda: False)()


def body_refs(fields, body):
    """The ids a body names through reference-typed fields."""
    out = set()
    for k, t in fields.items():
        v = body.get(k)
        if t.rstrip("?") == "ref" and v is not None:
            out.add(v)
        elif t.rstrip("?") == "refs" and v is not None:
            out.update(v)
    return out
'''

SOURCES["store"] = r'''"""The store (docs/V3.md §8): `records.jsonl`, one canonical line per record, and `blobs/<sha256>`.
Read in any order with duplicates (union merge); written in canonical order (distinct lines by id)."""
import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path

from warrant import jcs as C
from warrant import shapes as S

from . import records as R

LIMITS = {"records": 200_000, "bytes": 256 << 20, "refs": 4096, "depth": 4096, "requires": 128}
# A line that cannot be read as a record is listed under `rejected` and never aborts the read (§8), whatever
# the reader raised on it (jcs refuses deep nesting itself; the tuple keeps a reader change from aborting).
UNREADABLE = (R.Invalid, ValueError, TypeError, KeyError, RecursionError)


class Refused(ValueError):
    pass


class Inadmissible(Refused):
    """An append the caller's admission refused, on the store as it is under the writers' lock."""

    def __init__(self, why):
        super().__init__("; ".join(why))
        self.why = why


def confined(path, base):
    """The real path of `path`, refused unless it lies in `base` (by real path too): a path an
    operator or a caller names never reaches a file outside the tree it is meant for."""
    b, p = os.path.realpath(base), os.path.realpath(path)
    if p != b and not p.startswith(b + os.sep):
        raise Refused(f"{path}: outside {b}")
    return p


def dot_of(root):
    """A repository's store directory, `<root>/.warrant`, refused unless its real path lies in `root`: a `.warrant`
    link out of the repository never leads a reader or a writer into another store (Codex findings 24b91d75f065,
    1c3f12bcf1a9)."""
    return Path(confined(Path(root) / ".warrant", root))


def read_inside(path, base):
    """The bytes of `path`, refused unless its real path lies in `base`: a configuration a repository holds (its
    `.warrant/v3.json`) is read from that repository only, never through a link to a file outside it (Codex finding
    d6127c0fd71d)."""
    return Path(confined(path, base)).read_bytes()


class Snapshot:
    """The bytes of one read: {id: [distinct lines]}, {hash: bytes}, and what was wrong."""

    def __init__(self, lines, blobs):
        self.blobs = dict(blobs)
        self.rejected, self.lines, seen = {}, {}, set()
        self.raw = list(dict.fromkeys(lines))       # every distinct line as read, rejected ones too (the limits count them)
        order = list(lines) == sorted(set(lines), key=_line_id)
        for raw in lines:
            if raw in seen:
                continue
            seen.add(raw)
            try:
                if len(raw) > R.LINE_MAX:
                    raise R.Invalid(f"line longer than {R.LINE_MAX} bytes")
                env = C.loads(raw.rstrip(b"\n"))
                R.need(isinstance(env, dict) and set(env) == {"record", "sig"}, "a line is {record, sig}")
                R.check(env["record"])
                sig = env["sig"]
                R.need(sig is None or (isinstance(sig, dict) and set(sig) == {"key", "ed25519"} and S.hex64(sig["key"])
                                       and S.hex128(sig["ed25519"])), "sig is null or {key, ed25519}")
            except UNREADABLE as e:
                self.rejected[hashlib.sha256(raw).hexdigest()] = f"line: {e}"
                continue
            self.lines.setdefault(R.rid(env["record"]), []).append(env)
        self.canonical = order and not self.rejected          # a rejected line is never canonical, wherever it sorts
        listing = sorted(seen) + [f"b {h} {C.digest(b)}".encode() for h, b in sorted(self.blobs.items())]
        self.digest = C.digest(b"\n".join(listing))
        if len(self.lines) > LIMITS["records"] or sum(map(len, seen)) + sum(map(len, self.blobs.values())) > LIMITS["bytes"]:
            raise Refused(f"store beyond limits {LIMITS}")

    def blob(self, h):
        return self.blobs.get(h)

    def json_blob(self, h):
        try:
            return C.loads(self.blobs[h]) if h in self.blobs else None
        except C.NotCanonical:
            return None


def _line_id(raw):
    """The sort key of a line: its record's id, or "" for a line that holds no record object (it is rejected)."""
    try:
        doc = json.loads(raw)
        rec = doc.get("record") if isinstance(doc, dict) else None
        return (R.rid(rec), raw) if isinstance(rec, dict) else ("", raw)
    except UNREADABLE:
        return "", raw


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.file, self.blobs = self.root / "records.jsonl", self.root / "blobs"

    def init(self):
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.file.touch()
        return self

    def put_blob(self, data):
        h = hashlib.sha256(data).hexdigest()
        p = confined(self.blobs / h, self.blobs)
        if not os.path.exists(p):
            fd, tmp = tempfile.mkstemp(prefix=".blob.", dir=self.blobs)     # named apart from the content
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        return h

    def snapshot(self):
        lines = self.lines()
        blobs = {p.name: p.read_bytes() for p in sorted(self.blobs.iterdir())} if self.blobs.is_dir() else {}
        bad = [h for h, b in blobs.items() if hashlib.sha256(b).hexdigest() != h]
        if bad:
            raise Refused(f"blobs not named by their hash: {bad[:3]}")
        return Snapshot(lines, blobs)

    @contextlib.contextmanager
    def locked(self):
        """The writers' exclusive lock: on the store directory, not on records.jsonl, whose file every write
        replaces (a lock on a replaced file would let a waiting writer append to an unlinked one)."""
        fd = os.open(self.root, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def lines(self):
        raw = self.file.read_bytes() if self.file.exists() else b""
        return [x + b"\n" for x in raw.split(b"\n") if x]

    def append(self, r, key, trust, expect_head=None, admit=None):
        """File `r` signed by `key` as the next record of its actor's chain (§7): prev is the actor's
        head under the writers' lock; with expect_head, refused unless the head is that id ("": the actor
        has no signed record yet). The file is rewritten in canonical order."""
        return self.extend([r], key, trust, expect_head, admit)[0]

    def extend(self, records, key, trust, expect_head=None, admit=None):
        """append() for several records of one actor, chained in order, under one lock and one write. `admit(snapshot,
        records)`, called under the lock on the store as it is then, returns why the records may not be filed
        (Inadmissible), so no other writer changes the store between that decision and the write."""
        from .engine import head
        out, data, chained = [], [], []
        with self.locked():
            snap = self.snapshot()
            actor = records[0]["actor"]
            h = head(snap, trust, actor)
            if expect_head is not None and (h["id"] or "") != expect_head:
                raise Refused(f"CHAIN_MOVED: the head of {actor} is {h['id']}")
            prev, at = h["id"], h["at"]
            for r in records:
                if r["actor"] != actor or (at is not None and r["at"] < at):
                    raise Refused(f"a record of {r['actor']} at {r['at']} does not extend {actor}'s chain at {at}")
                r = dict(r, prev=prev)
                R.check(r)
                chained.append(r)
                prev, line = R.line(r, key)
                if len(line) > R.LINE_MAX:              # a writer never writes a line its reader rejects (§8)
                    raise Refused(f"the record's line is {len(line)} bytes, more than {R.LINE_MAX}")
                at = r["at"]
                out.append(prev)
                data.append(line)
            why = admit(snap, chained) if admit else []
            if why:
                raise Inadmissible(why)
            self.write_lines(self.lines() + data)
        return out

    def add_lines(self, lines):
        """Add lines as they are (an import, a union): under the writers' lock, in canonical order."""
        with self.locked():
            self.write_lines(self.lines() + list(lines))

    def write_lines(self, lines):
        """Replace the file with `lines` in canonical order (fmt, append, add_lines), durably."""
        out = b"".join(sorted(set(lines), key=_line_id))
        fd, tmp = tempfile.mkstemp(prefix=".records.", dir=self.root)
        with os.fdopen(fd, "wb") as f:
            f.write(out)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.file)
'''

SOURCES["engine"] = r'''"""Assessment (docs/V3.md §§3-7, 10): one pure pass over a snapshot under the receiver's trust and
profile. Authentication, actor chains, schemas, lineages with FORK, guards, challenges, reliance
and the graph come out of the same View."""
import hashlib
from pathlib import Path

from warrant import jcs as C
from warrant import shapes as S

from . import records as R
from .store import LIMITS

NONE, MET, PENDING = "NONE", "MET", "PENDING"
# Every word a report answers with, for the agent's glossary (warrant_agent/glossary.py is held to these).
GUARDS = (NONE, MET, PENDING)
RELIANCE = ("ELIGIBLE", "PENDING", "CHALLENGED", "FORK")
BASES = ("SIGNED", "MIGRATED")
PROBLEMS = ("INVALID", "LINEAGE_BACKDATED", "LINEAGE_BROKEN", "LINEAGE_NOT_AUTHOR", "MIGRATION_MAP", "SCHEMA_CONFLICT",
            "SCHEMA_NOT_COUNTED")
REJECTIONS = ("line", "BAD_SIGNATURE", "UNSIGNED", "INVALID")
REPLAY = ("reproduces", "does_not_reproduce", "no_result", "does_not_apply")
SCHEMA_AUTHOR = "schema/author"
_CODE = []


def code_identity():
    """The digest of every file that decides a verdict: this package, whole (the core imports nothing
    outside it but the standard library and the signature library), with that library's version."""
    if not _CODE:
        import cryptography
        files = sorted(Path(__file__).resolve().parent.glob("*.py"))
        h = {f"warrant/{p.name}": hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        _CODE.append(C.doc_id({"files": h, "cryptography": cryptography.__version__}))
    return _CODE[0]


def trust_problem(t):
    ok = isinstance(t, dict) and set(t) == {"warrant", "keys"} and t["warrant"] == "trust/3" and isinstance(t["keys"], dict) \
        and all(S.is_actor(a) and R.is_list(ks, S.hex64, True) for a, ks in t["keys"].items())
    return None if ok else "trust is {warrant: trust/3, keys: {actor: [sorted public hex]}}"


def profile_problem(p):
    ok = isinstance(p, dict) and {"warrant", "roles"} <= set(p) <= {"warrant", "roles", "quorum"} and p["warrant"] == "profile/3" \
        and isinstance(p["roles"], dict) and all(isinstance(k, str) and R.is_list(v, S.is_actor, True) for k, v in p["roles"].items()) \
        and isinstance(p.get("quorum", {}), dict) and all(R.is_int(k) and k >= 1 for k in p.get("quorum", {}).values())
    return None if ok else "profile is {warrant: profile/3, roles: {role: [sorted actors]}, quorum?: {role: k >= 1}}"


def _authentic(snap, trust, as_of, only=None):
    """({id: record}, {id: basis}, {id: why}, later): SIGNED by a trusted key of the actor, or
    UNSIGNED pending a migration voucher; records after as_of are left out (counted). `only`: read
    one actor's records alone (a writer's head verifies no other signature)."""
    recs, basis, bad, later = {}, {}, {}, 0
    for i, envs in snap.lines.items():
        r = envs[0]["record"]
        if only is not None and r["actor"] != only:
            continue
        if as_of is not None and r["at"] > as_of:
            later += 1
            continue
        sigs = [e["sig"] for e in envs if e["sig"] is not None]
        keys = trust["keys"].get(r["actor"], []) + ([R.named_key(r)] if R.named_key(r) else [])
        if any(R.verifies(i, s, k) for s in sigs for k in keys):
            recs[i], basis[i] = r, "SIGNED"
        elif any(e["sig"] is None for e in envs):          # a bad signature beside it never revokes the unsigned line's basis
            recs[i], basis[i] = r, "UNSIGNED"
        else:
            bad[i] = "BAD_SIGNATURE: no signature verifies under a key the trust binds to the actor, or a challenge's own"
    return recs, basis, bad, later


def head(snap, trust, actor):
    """The writer's head (§7): the latest of the actor's chained signed records no other names."""
    recs, basis, _, _ = _authentic(snap, trust, None, only=actor)
    mine = {i: r for i, r in recs.items() if basis[i] == "SIGNED"}
    named = {r["prev"] for r in mine.values()}
    # Chained as §7 says, by the links themselves: records of one second follow their chain, never their time.
    chained = {i for i, r in mine.items() if r["prev"] is None or (r["prev"] in mine and mine[r["prev"]]["at"] <= r["at"])}
    tips = sorted((mine[i]["at"], i) for i in chained if i not in named)
    return {"id": tips[-1][1], "at": tips[-1][0]} if tips else {"id": None, "at": None}


class View:
    def __init__(self, snap, trust, profile, as_of=None):
        for why in (trust_problem(trust), profile_problem(profile)):
            if why:
                raise R.Invalid(why)
        self.snap, self.trust, self.profile = snap, trust, profile
        self.as_of = as_of if as_of is not None else max((e[0]["record"]["at"] for e in snap.lines.values()), default=0)
        self.recs, self.basis, self.bad, self.later = _authentic(snap, trust, self.as_of)
        self.problems = []
        self._vouch()
        self._chains()
        self._index_attests()
        self._schemas()
        self._bodies()
        self._pins()
        self._index_attests()
        ents = {i for i, r in self.recs.items() if r["kind"] == "entity"}
        self.root_of, self.lineages = self._lineages(ents, self._may_succeed)
        self._requires_depth()
        self._guards, self._effective = self._resolve()

    def _index_attests(self):
        self.attests = {}
        for i, r in sorted(self.recs.items(), key=lambda kv: (kv[1]["at"], kv[0])):
            if r["kind"] == "attest":
                self.attests.setdefault(r["body"]["target"], []).append(i)

    def holds(self, actor, *roles):
        return any(actor in self.profile["roles"].get(x, []) for x in roles)

    def problem(self, code, rid, detail=""):
        self.problems.append([code, rid, detail])

    def drop(self, i, why):
        self.bad[i] = why
        self.recs.pop(i, None)
        self.basis.pop(i, None)

    # -- authentication of migrated records (§9)

    def _vouch(self):
        vouched = {}
        for i, r in sorted(self.recs.items()):
            if not (r["kind"] == "attest" and r["schema"] == R.MIGRATION and self.basis[i] == "SIGNED"
                    and self.holds(r["actor"], "migrator")):
                continue
            rows = _map_rows(self.snap.json_blob(r["body"]["target"]))
            if rows is None:
                self.problem("MIGRATION_MAP", i, "its target is not a map blob in the view")
                continue
            for row in rows:
                vouched.setdefault(row[0], i)
        self.vouched_by = {}
        for i in [i for i, b in self.basis.items() if b == "UNSIGNED"]:
            by = vouched.get(i)
            if by is not None:
                self.basis[i], self.vouched_by[i] = "MIGRATED", by
            else:
                self.drop(i, "UNSIGNED: no signature, and no migration the profile accepts lists it")

    # -- actor chains (§7)

    def _chains(self):
        signed = {i: r for i, r in self.recs.items() if self.basis[i] == "SIGNED"}
        self.chain_forks, by_prev, self.unanchored = [], {}, []
        for i, r in sorted(signed.items()):
            by_prev.setdefault((r["actor"], r["prev"]), []).append(i)
            p = signed.get(r["prev"]) if r["prev"] else None
            if r["prev"] is not None and not (p and p["actor"] == r["actor"] and p["at"] <= r["at"]):
                self.unanchored.append(i)
        self.chain_forks = [[a, p, ids] for (a, p), ids in sorted(by_prev.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
                            if len(ids) > 1]

    # -- schemas (§4)

    def _schemas(self):
        self.schemas, self.pending, cand = {}, [], {}
        for i, r in sorted(self.recs.items()):
            if r["kind"] == "schema":
                why = _schema_problem(r["body"])
                if why:
                    self.problem("SCHEMA_NOT_COUNTED", i, why)
                elif len(self.backers(i)) < self.quorum(SCHEMA_AUTHOR):
                    self.pending.append(i)          # waits for backers (schemas_pending): not a problem of the store
                else:
                    cand[i] = r
        self.schema_root, lins = self._lineages(set(cand), lambda r, root: r["actor"] == root["actor"])
        by_name = {}
        for root, lin in lins.items():
            if lin["leaf"] is None:
                self.problem("SCHEMA_CONFLICT", root, "its lineage forks")
                continue
            by_name.setdefault(self.recs[lin["leaf"]]["body"]["name"], []).append(lin["leaf"])
        for name, leaves in sorted(by_name.items()):
            if len(leaves) > 1:
                self.problem("SCHEMA_CONFLICT", name, f"{len(leaves)} schema lineages name it")
            else:
                self.schemas[name] = {"id": leaves[0], **self.recs[leaves[0]]["body"]}

    def quorum(self, role):
        return self.profile.get("quorum", {}).get(role, 1)

    def backers(self, i):
        """The schema/author actors behind schema record i: its filer and each that attests it with accept. Only an
        attest without a schema counts: it is admitted whatever the schemas are, so none that the body check
        drops later (INVALID) stands behind a schema, and no schema rests on a record read under a schema."""
        out = {self.recs[a]["actor"] for a in self.attests.get(i, [])
               if self.recs[a]["schema"] is None and self.recs[a]["body"].get("verdict") == "accept"}
        out.add(self.recs[i]["actor"])
        return sorted(a for a in out if self.holds(a, SCHEMA_AUTHOR))

    def _pins(self):
        """§4: a schema's `pinned` member of a lineage's root is an object, and each closing version's guard matches at
        least that. Decided over the bodies that passed and before any is dropped, so record ids decide nothing."""
        bad = {}
        for i, r in sorted(self.recs.items()):
            s = self.schemas.get(r["schema"]) if r["kind"] == "entity" else None
            if not (s and s.get("pinned")):
                continue
            root, seen = r, {i}
            while root["lineage"] in self.recs and root["lineage"] not in seen:
                seen.add(root["lineage"])
                root = self.recs[root["lineage"]]
            pin = root["body"].get(s["pinned"])
            if pin is not None and not isinstance(pin, dict):
                bad[i] = f"the root's {s['pinned']} is not an object"
            elif pin and r["body"].get("state") in s["closed"] \
                    and any((r["guard"] or {"match": {}})["match"].get(k, object()) != v for k, v in pin.items()):
                bad[i] = f"its guard matches less than its root's {s['pinned']}"
        for i, why in bad.items():
            self.problem("INVALID", i, why)
            self.drop(i, f"INVALID: {why}")

    def _bodies(self):
        for i, r in sorted(self.recs.items()):
            # migration@1 is the migration's attest alone (§9); no counted schema bears the name, so any other record of it is INVALID
            if r["kind"] == "schema" or (r["schema"] is None and r["kind"] != "entity") or (r["schema"] == R.MIGRATION and r["kind"] == "attest"):
                continue
            s = self.schemas.get(r["schema"])
            why = f"schema {r['schema']!r} is not one this receiver counts" if s is None else _body_problem(r, s)
            if why:
                self.problem("INVALID", i, why)
                self.drop(i, f"INVALID: {why}")

    # -- lineages (§3)

    def _may_succeed(self, r, root):
        """A state the schema's successors name is entered only by those roles; any other by the root's actor."""
        roles = self.schemas[r["schema"]]["successors"].get(r["body"].get("state"))
        return r["actor"] == root["actor"] if roles is None else self.holds(r["actor"], *roles)

    def _lineages(self, ids, may_succeed):
        """({id: root}, {root: lineage}) over `ids`; successors that break the rules are excluded."""
        root_of = {}
        for i in sorted(ids):
            for x in reversed(self._climb(i, ids, root_of)):
                self._succeed(x, root_of, may_succeed)
        lins = {}
        for i in sorted(ids, key=lambda i: (self.recs[i]["at"], i)):
            rt = root_of.get(i)
            if rt is None:
                continue
            lin = lins.setdefault(rt, {"versions": [], "succ": {}})
            lin["versions"].append(i)
            if i != rt:
                lin["succ"].setdefault(self.recs[i]["lineage"], []).append(i)
        for rt, lin in lins.items():
            _settle(rt, lin)
        return {i: rt for i, rt in root_of.items() if rt is not None and i in ids}, lins

    def _climb(self, i, ids, root_of):
        """The versions from i up its lineage links to the first one rooted already or outside `ids` (rooted here:
        itself when it is a root in `ids`, else none), nearest first."""
        path, cur = [], i
        while cur not in root_of and cur in ids and self.recs[cur]["lineage"] is not None and len(path) < 4096:
            path.append(cur)
            cur = self.recs[cur]["lineage"]
        if cur not in root_of:
            root_of[cur] = cur if cur in ids and self.recs[cur]["lineage"] is None else None
        return path

    def _succeed(self, x, root_of, may_succeed):
        """Put version x in its predecessor's lineage (root_of[x] its root), or in none when it breaks the rules."""
        p, r, rt = self.recs[x]["lineage"], self.recs[x], root_of[self.recs[x]["lineage"]]
        if rt is None or self.recs[p]["kind"] != r["kind"] or self.recs[p]["schema"] != r["schema"]:
            root_of[x] = None
            self.problem("LINEAGE_BROKEN", x, f"it succeeds {p[:12]}, which is no admitted version of its kind and schema")
        elif not may_succeed(r, self.recs[rt]):
            root_of[x] = None
            self.problem("LINEAGE_NOT_AUTHOR", x, f"filed by {r['actor']!r}; the lineage is {self.recs[rt]['actor']!r}'s")
        else:
            root_of[x] = rt
            if r["at"] < self.recs[p]["at"]:
                self.problem("LINEAGE_BACKDATED", x, "dated before the version it succeeds")

    # -- guards (§6)

    def _requires_depth(self):
        """Refuse the store (§8) when a chain of lineages requiring lineages is longer than LIMITS["requires"]: a
        bound on the input, as the other limits are (guards are resolved without recursion, _resolve). The depth is
        the structure's (every version's requires, cycles cut), so it does not depend on the order in which
        versions are evaluated. Computed without recursion."""
        deps = {L: sorted({x for v in lin["versions"] for x in (self.recs[v]["guard"] or {}).get("requires", [])
                           if x in self.lineages}) for L, lin in self.lineages.items()}
        depth = {}
        for start in sorted(deps):
            if start in depth:
                continue
            stack, on = [(start, iter(deps[start]))], {start}
            while stack:
                node, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    stack.pop()
                    on.discard(node)
                    depth[node] = 1 + max((depth[c] for c in deps[node] if c in depth), default=0)
                elif nxt not in depth and nxt not in on:
                    on.add(nxt)
                    stack.append((nxt, iter(deps[nxt])))
        if max(depth.values(), default=0) > LIMITS["requires"]:
            raise R.Invalid(f"store beyond limits: lineages require lineages {max(depth.values())} deep, "
                            f"more than {LIMITS['requires']}")

    def schema_of(self, i):
        return self.schemas[self.recs[i]["schema"]]

    def _resolve(self):
        """Every version's guard (§6) and every lineage's effective version (§3), at once and without recursion.
        Rule 2 is a least fixpoint: a version closing with requires starts unmet, and is met only once each lineage
        it requires has a closing effective version met before it; the met set only grows, until nothing changes.
        Nothing depends on the order of record ids, and a cycle of requires that nothing outside it closes stays
        PENDING (a version never satisfies what requires it through itself)."""
        part, closing = self._attested()
        users, short = {}, {}
        for v, ls in closing.items():
            short[v] = len(ls)
            for L in ls:
                users.setdefault(L, []).append(v)
        met = {v for v, (_, waiting) in part.items() if not waiting and not short.get(v)}
        at = {v: n for lin in self.lineages.values() for n, v in enumerate(lin["path"])}
        eff = {L: next((v for v in reversed(lin["path"]) if v in met), None) for L, lin in self.lineages.items()}
        # Only closing versions join `met` from here on, so a lineage once closed stays closed: each closes once.
        shut, todo = set(), sorted(eff)
        while todo:
            L = todo.pop()
            if L in shut or eff[L] is None or self.recs[eff[L]]["body"].get("state") not in self.schema_of(L).get("closed", []):
                continue
            shut.add(L)
            todo += self._release(users.get(L, []), short, part, met, eff, at)
        guards = {v: self._guard_of(v, acc, waiting, closing.get(v, []), shut) for v, (acc, waiting) in part.items()}
        return guards, eff

    def _attested(self):
        """({version: (accepted by, waiting)}, {closing version: lineages it requires}): each version's guard by its
        attests alone, and the versions whose state closes."""
        part, closing = {}, {}
        for v in sorted(self.root_of):
            r, g = self.recs[v], self.recs[v]["guard"]
            acc, waiting = [], []
            if g is not None:
                acc = sorted({self.recs[a]["actor"] for a in self.attests.get(v, [])
                              if self.recs[a]["actor"] != r["actor"] and self.holds(self.recs[a]["actor"], *g["roles"])
                              and all(self.recs[a]["body"].get(k) == x for k, x in g["match"].items())})
                if len(acc) < g["quorum"]:
                    waiting.append(f"{g['quorum'] - len(acc)} attest(s) by {', '.join(g['roles'])} matching {C.canon(g['match']).decode()}")
            part[v] = (acc, waiting)
            if r["body"].get("state") in self.schema_of(v).get("closed", []):       # with or without a guard (Codex #3)
                closing[v] = self.requires(v)
        return part, closing

    def _release(self, users, short, part, met, eff, at):
        """A lineage closed: each of its `users` (the versions requiring it) is short one less; a user short of
        nothing whose attests are in is met, and its lineage's effective version when later on that lineage's path.
        The lineages whose effective version moved, to be looked at again."""
        moved = []
        for u in users:
            short[u] -= 1
            if short[u] == 0 and not part[u][1]:
                met.add(u)
                U = self.root_of[u]
                if u in at and (eff[U] is None or at[u] > at[eff[U]]):
                    eff[U] = u
                    moved.append(U)
        return moved

    def _guard_of(self, v, acc, waiting, requires, shut):
        g = self.recs[v]["guard"]
        still_open = [L for L in requires if L not in shut]
        waiting = waiting + [f"requires {L} closed" for L in still_open]
        return {"guard": _guard_word(waiting, g), "waiting": waiting, "accepted_by": acc,
                "roles": g["roles"] if g else [], "short": max(0, g["quorum"] - len(acc)) if g else 0, "open": still_open}

    def guard(self, v):
        return self._guards[v]

    def requires(self, v):
        out, cur = set(), v
        while cur is not None:
            out.update((self.recs[cur]["guard"] or {}).get("requires", []))
            cur = self.recs[cur]["lineage"]
        return sorted(out)

    def effective(self, lineage):
        return self._effective[lineage]

    # -- challenges (§5)

    def challenge(self, c):
        r = self.recs[c]
        x = r["body"]["target"]
        t = self.recs.get(x)
        replays = [[self.recs[a]["body"].get("on"), self.recs[a]["body"].get("verdict"), self.recs[a]["actor"]]
                   for a in self.attests.get(c, []) if self.holds(self.recs[a]["actor"], "replayer")
                   and self.recs[a]["body"].get("verdict") in REPLAY]
        why = None
        if t is not None and r["actor"] == t["actor"]:
            why = "its target's actor"
        elif t is not None and t["guard"] and self.holds(r["actor"], *t["guard"]["roles"]):
            why = "holds a role of its target's guard"
        elif self.holds(r["actor"], "challenger"):
            why = "holds the challenger role"
        elif any(on == x and v == "reproduces" for on, v, _ in replays):
            why = "reproduced by a replayer"
        stands = why is not None and t is not None
        if stands and x in self.root_of:
            lin = self.lineages[self.root_of[x]]
            eff = self.effective(self.root_of[x])
            stands = x in lin["path"] and (eff is None or lin["path"].index(eff) <= lin["path"].index(x))
        return {"target": x, "counted": why is not None, "why": why or "thesis: its actor's challenge does not count here",
                "replays": sorted(replays, key=lambda z: (str(z[0]), str(z[1]), z[2])), "stands": stands}

    # -- the report (§10)

    def report(self):
        challenges = {c: self.challenge(c) for c, r in sorted(self.recs.items()) if r["kind"] == "challenge"}
        standing = {}
        for c, x in challenges.items():
            if x["stands"]:
                standing.setdefault(x["target"], []).append(c)
        versions = {v: dict(self.guard(v), challenged_by=standing.get(v, [])) for v in sorted(self.root_of)}
        lineages = {}
        for L, lin in sorted(self.lineages.items()):
            eff = self.effective(L)
            reliance = _reliance(lin, eff, standing)
            lineages[L] = {"schema": self.recs[L]["schema"], "actor": self.recs[L]["actor"], "versions": lin["versions"],
                           "path": lin["path"], "leaf": lin["leaf"], "effective": eff,
                           "state": self.recs[eff]["body"].get("state") if eff else None,
                           "verdict": "FORK" if lin["forks"] else "OK", "forks": lin["forks"], "reliance": reliance}
        operands = {"snapshot": self.snap.digest, "trust": C.doc_id(self.trust), "profile": C.doc_id(self.profile),
                    "as_of": self.as_of, "code": code_identity()}
        return {"warrant": "3", "assessment": C.doc_id(operands), **operands, "completeness": "UNATTESTED",
                "canonical": self.snap.canonical, "later": self.later,
                "basis": {b: sum(1 for x in self.basis.values() if x == b) for b in ("SIGNED", "MIGRATED")},
                "rejected": dict(sorted({**self.snap.rejected, **self.bad}.items())),
                "duplicates": sorted(i for i, e in self.snap.lines.items() if len(e) > 1 and i in self.recs),
                "chains": {"forks": self.chain_forks, "unanchored": self.unanchored},
                "schemas": {n: s["id"] for n, s in sorted(self.schemas.items())},
                "schemas_pending": {i: {"name": self.recs[i]["body"]["name"], "backed_by": self.backers(i),
                                        "need": self.quorum(SCHEMA_AUTHOR)} for i in self.pending},
                "lineages": lineages, "versions": versions, "challenges": challenges,
                "problems": sorted(self.problems), "graph": self.graph()}

    def graph(self):
        nodes, edges = [], []
        for i, r in sorted(self.recs.items()):
            nodes.append([i, r["kind"], r["schema"], r["actor"], r["at"], self.basis[i]])
            t = r["body"].get("target") if r["kind"] in ("attest", "challenge") else None
            edges += [[i, "lineage", r["lineage"]]] if r["lineage"] else []
            edges += [[i, "prev", r["prev"]]] if r["prev"] else []
            edges += [[i, r["kind"], t]] if t else []
            edges += [[i, "requires", x] for x in (r["guard"] or {}).get("requires", [])]
            edges += [[i, "ref", x] for x in r["refs"] if x != t]
        return {"nodes": nodes, "edges": sorted(edges)}


def _map_rows(doc):
    """The rows of a migration's map blob ([[id, ...], ...], three members each), or None when `doc` is not one."""
    rows = doc.get("map") if isinstance(doc, dict) else None
    return rows if isinstance(rows, list) and all(isinstance(x, list) and len(x) == 3 and S.hex64(x[0]) for x in rows) else None


def _settle(rt, lin):
    """A lineage's forks, and its path from the root `rt` and its leaf when it has none."""
    forks = {p: c for p, c in lin["succ"].items() if len(c) > 1}
    lin["forks"] = [[p, c] for p, c in sorted(forks.items())]
    if forks:
        lin["path"], lin["leaf"] = [], None
        return
    path = [rt]
    while path[-1] in lin["succ"]:
        path.append(lin["succ"][path[-1]][0])
    lin["path"], lin["leaf"] = path, path[-1]


def _guard_word(waiting, g):
    if waiting:
        return PENDING
    return NONE if g is None else MET


def _reliance(lin, eff, standing):
    if lin["leaf"] is None:
        return "FORK"
    if eff is None:
        return "PENDING"
    return "CHALLENGED" if standing.get(eff) else "ELIGIBLE"


SCHEMA_MEMBERS = {"name", "fields", "states", "closed", "successors"}


def _schema_problem(b):
    ok = isinstance(b, dict) and SCHEMA_MEMBERS <= set(b) <= SCHEMA_MEMBERS | {"pinned"} \
        and isinstance(b["name"], str) and 0 < len(b["name"]) <= 100 and b["name"] != R.MIGRATION \
        and isinstance(b["fields"], dict) and all(isinstance(t, str) and t.rstrip("?") in R.TYPES for t in b["fields"].values()) \
        and (b["states"] is None or (isinstance(b["states"], dict) and b["fields"].get("state") == "str"
                                     and all(g is None or R.guard_problem(g) is None for g in b["states"].values()))) \
        and R.is_list(b["closed"], lambda s: isinstance(b["states"], dict) and s in b["states"], True) \
        and isinstance(b["successors"], dict) and all(isinstance(b["states"], dict) and st in b["states"]
                                                      and R.is_list(rs, S.is_actor, True) for st, rs in b["successors"].items()) \
        and ("pinned" not in b or (isinstance(b["pinned"], str) and b["fields"].get(b["pinned"]) in ("obj", "obj?")))
    return None if ok else ("a schema body is {name, fields: {member: type}, states: {state: guard|null}|null, closed, "
                            "successors: {state: [roles]}, pinned?: a member of type obj}")


def _body_problem(r, s):
    b, f = r["body"], s["fields"]
    if r["kind"] in ("attest", "challenge") and "target" not in f:
        f = dict(f, target="ref")
    extra, missing = set(b) - set(f), {k for k, t in f.items() if not t.endswith("?")} - set(b)
    if extra or missing:
        return f"members {sorted(extra)} are not in {s['name']}, or {sorted(missing)} are missing"
    bad = [k for k, v in b.items() if not R.type_ok(f[k], v)]
    if bad:
        return f"members {bad} do not have their types in {s['name']}"
    if not R.body_refs(f, b) <= set(r["refs"]):
        return "a reference in the body is not in refs"
    if r["kind"] != "entity":
        return None
    if not isinstance(s["states"], dict) or b.get("state") not in s["states"]:
        return f"state {b.get('state')!r} is not a state of {s['name']}"
    need = s["states"][b["state"]]
    if need is not None and _weaker(r["guard"], need):
        return f"its guard is weaker than {s['name']}'s for state {b['state']!r}"
    return None


def _weaker(g, need):
    if g is None:
        return True
    return (g["quorum"] < need["quorum"] or (need["quorum"] > 0 and not set(g["roles"]) <= set(need["roles"]))
            or any(g["match"].get(k, object()) != v for k, v in need["match"].items())
            or not set(need["requires"]) <= set(g["requires"]))


def assess(snap, trust, profile, as_of=None):
    return View(snap, trust, profile, as_of).report()
'''

SOURCES["verify"] = r'''"""`warrant verify PACKAGE`: may this receiver rely on what it was handed? (docs/VERIFY.md)

One party hands another a `package/3` (the agent interface's `handoff export`, docs/V3.md §13): the records a result
rests on and the verdicts on them. This assesses the package alone, under the receiver's own trust and profile, with
no store, no workspace and no agent configuration, and writes nothing.

    warrant verify PACKAGE (--trust T --profile P | --config V3JSON) [--as-of N] [--checkout DIR]
                           [--require ROOT ...] [--max-bytes N]

The answer is one line of canonical JSON on standard output, and the exit status is the gate:

    0   every root asked for is one this receiver may rely on now;
    1   otherwise: a root is not relied on, or the package was refused (the answer says which);
    2   the command line, or a file of the receiver's own that it names, cannot be read;
    3   an error of this verifier itself, never the code of a refusal.

A root is a record id. It is relied on when it is the effective version of its lineage (docs/V3.md §3: a lineage
that forks has none, and a version whose guard waits is not it), no counted challenge in the package stands against
it, and, with --checkout, the files its acceptances name are still those bytes in that checkout's HEAD (warrant.pins;
without a checkout they are listed, not checked). The roots are --require's, else the ones the package names.

The answer keeps five things apart and never folds them into one word: `integrity` (the bytes are the bytes their
names hash), `authenticity` (whose signatures verify under the receiver's trust), `completeness` (what the slice
does not hold: always something, since its sender chose it), `execution` (the schemas and rules as this receiver
counts them) and, per root, the right to rely. `established` and `not_established` say the same in sentences,
built from what this run found.

The agent interface's `handoff` reads a package through `unpack`, `snapshot` and `describe` here, so there is one
reader of the format. warrant_verify.py at the repository's root is this module and the ones it imports as one
standard-library file (tools/build_verify.py)."""
import argparse
import base64
import hashlib
import json
import subprocess
import sys

from . import engine as E
from . import graph as G
from . import jcs as C
from . import pins as P
from . import records as R
from . import shapes as S
from .store import Refused, Snapshot

PACKAGE = "package/3"
ANSWER = "verify/3"
MAX_BYTES = 64 << 20
MEMBERS = {"warrant", "roots", "lines", "blobs"}
# Why a root is not relied on: it is relied on only when none holds. A reliance the engine gives an effective version
# other than ELIGIBLE is passed on under the engine's own word (today CHALLENGED), so a new one fails the gate too.
WHY_NOT = ("UNAVAILABLE", "NOT_A_VERSION", "NOT_EFFECTIVE", "CHALLENGED", "STALE", "PINS_NOT_CHECKED")
# Why a package is refused before anything is assessed, each with its one sentence (no reader's own wording: another
# implementation gives the same bytes).
REFUSALS = {
    "TOO_LARGE": "the package is larger than {limit} bytes",
    "NOT_JSON": "the package is not UTF-8 JSON, or an object in it names a member twice",
    "NOT_A_PACKAGE": "a package is {{warrant: " + PACKAGE + ", roots, lines, blobs}}",
    "BAD_BASE64": "a blob is not base64",
    "BAD_BLOB": "a blob is not named by its hash",
    "BAD_LINE": "{n} line(s) of the package are not records",
    "LIMITS": "the package is beyond the engine's limits",
}


class Refusal(ValueError):
    """A package that is not read: `code` (REFUSALS), its sentence, and `detail`, a reader's own words for a caller
    that wants them (never in an answer)."""

    def __init__(self, code, detail="", **words):
        super().__init__(REFUSALS[code].format(**words))
        self.code, self.detail = code, detail


class Usage(Exception):
    """The command line, or a file of the receiver's own, cannot be read: exit 2."""


# ---------------------------------------------------------------- the format

def read_json(raw):
    """The JSON value in `raw`, read one way or refused: an object naming a member twice has two readings (Python
    keeps the last value, other readers the first). A float, NaN or Infinity is read and then fits no shape a
    package, a trust or a profile has; a record's line is read by the canonical reader (warrant.jcs), which takes
    neither."""
    def one(pairs):
        d = dict(pairs)
        if len(d) != len(pairs):
            raise ValueError("a member is named twice")
        return d
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=one)
    except (ValueError, RecursionError) as e:
        raise Refusal("NOT_JSON", f"{type(e).__name__}: {e}") from None


def unpack(pkg, limit=None):
    """(lines, blobs) of a package object: each line's bytes with its newline, {hash: bytes}. Refused: another shape,
    a blob that is not base64 or not named by its hash, more than `limit` bytes of lines and blobs (None: the caller
    bounded the package's own bytes already)."""
    if not (isinstance(pkg, dict) and pkg.get("warrant") == PACKAGE and set(pkg) == MEMBERS
            and isinstance(pkg["lines"], list) and all(isinstance(x, str) for x in pkg["lines"])
            and isinstance(pkg["blobs"], dict) and isinstance(pkg["roots"], list) and all(S.hex64(r) for r in pkg["roots"])):
        raise Refusal("NOT_A_PACKAGE")
    try:
        blobs = {h: base64.b64decode(b, validate=True) for h, b in pkg["blobs"].items()}
    except (ValueError, TypeError) as e:
        raise Refusal("BAD_BASE64", str(e)) from None
    # A lone surrogate is not UTF-8: its bytes stay what no reader takes for a record (snapshot counts the line).
    lines = [x.encode("utf-8", "surrogatepass") + b"\n" for x in pkg["lines"]]
    if limit is not None and sum(map(len, lines)) + sum(map(len, blobs.values())) > limit:
        raise Refusal("TOO_LARGE", limit=limit)
    if not all(S.hex64(h) and C.digest(b) == h for h, b in blobs.items()):
        raise Refusal("BAD_BLOB")
    return lines, blobs


def snapshot(lines, blobs):
    """The package as one read (store.Snapshot), refused when a line is not a record. A line holds one newline, its
    last byte: a second one would be the same record under another digest."""
    snap = Snapshot(lines, blobs)
    extra = [x for x in snap.raw if x.count(b"\n") != 1 and hashlib.sha256(x).hexdigest() not in snap.rejected]
    if snap.rejected or extra:
        raise Refusal("BAD_LINE", n=len(snap.rejected) + len(extra))
    return snap


def describe(rep, ids):
    """{id: its node, lineage, guard and challenge in report `rep`} (graph.describe); an id the report has no record
    of reads `unavailable`, never as absent from the world."""
    nodes, _, _ = G.index(rep)
    return {i: G.describe(rep, nodes, i) for i in ids}


# ---------------------------------------------------------------- the answer

def verify(raw, trust, profile, as_of=None, require=(), checkout=None, limit=MAX_BYTES):
    """The answer (a JSON object, module docstring) for the bytes of a package file. `require`: the roots the receiver
    asks about (none: the package's own); `checkout`: what read_checkout gave, or None."""
    for why in (E.trust_problem(trust), E.profile_problem(profile)):
        if why:
            raise Usage(why)
    receiver = {"trust": C.doc_id(trust), "profile": C.doc_id(profile), "as_of": as_of}
    asked = {"by": "receiver" if require else "package", "roots": sorted(set(require))}
    try:
        if len(raw) > limit:
            raise Refusal("TOO_LARGE", limit=limit)
        pkg = read_json(raw)
        lines, blobs = unpack(pkg)                       # what a package holds is smaller than its file
        snap = snapshot(lines, blobs)
        try:
            view = E.View(snap, trust, profile, as_of)
        except (Refused, R.Invalid) as e:
            raise Refusal("LIMITS", str(e)) from None
    except Refusal as e:
        return _refused(e, receiver, asked)
    except Refused as e:                                 # the snapshot beyond the engine's limits
        return _refused(Refusal("LIMITS", str(e)), receiver, asked)
    if not require:
        asked["roots"] = sorted(set(pkg["roots"]))
    return _answer(snap, view, view.report(), dict(receiver, as_of=view.as_of), asked, checkout)


def _refused(e, receiver, asked):
    return {"warrant": ANSWER, "rely": False, "refused": {"code": e.code, "why": str(e)}, "package": None,
            "receiver": receiver, "asked": asked, "checkout": None, "integrity": None, "authenticity": None,
            "completeness": None, "execution": None, "roots": {}, "established": [],
            "not_established": [f"integrity: the package was refused and nothing in it was assessed: {e}"]}


def _answer(snap, view, rep, receiver, asked, checkout):
    nodes, out, _ = G.index(rep)
    roots = {i: _root(snap, view, rep, nodes, out, i, checkout) for i in asked["roots"]}
    code = {i: w.split(":")[0] for i, w in rep["rejected"].items()}
    by = {}
    for i, a in sorted(view.vouched_by.items()):
        by[a] = by.get(a, 0) + 1
    named = sum(1 for i, r in view.recs.items() if view.basis[i] == "SIGNED" and R.named_key(r))
    q = view.quorum(E.SCHEMA_AUTHOR)
    problems = sorted({(p[0], p[1]) for p in rep["problems"]})
    ans = {
        "warrant": ANSWER, "rely": bool(roots) and all(r["rely"] for r in roots.values()), "refused": None,
        "package": snap.digest, "receiver": receiver, "asked": asked,
        "checkout": None if checkout is None else {"tree": checkout["tree"]},
        "integrity": {"records": len(snap.lines), "blobs": len(snap.blobs),
                      "bytes": sum(map(len, snap.raw)) + sum(map(len, snap.blobs.values()))},
        "authenticity": {"signed": rep["basis"]["SIGNED"], "migrated": rep["basis"]["MIGRATED"], "named_keys": named,
                         "migrations": [{"attest": a, "actor": view.recs[a]["actor"], "records": n} for a, n in sorted(by.items())],
                         "rejected": {i: c for i, c in sorted(code.items()) if c != "INVALID"},
                         "duplicates": rep["duplicates"]},
        "completeness": {"attested": rep["completeness"], "later": rep["later"],
                         "unavailable": sorted({x for r in roots.values() for x in r["unavailable"]}),
                         "unanchored": len(rep["chains"]["unanchored"]), "chain_forks": len(rep["chains"]["forks"])},
        "execution": {"schemas": rep["schemas"], "quorum": q,
                      "schemas_pending": {i: p["name"] for i, p in sorted(rep["schemas_pending"].items())},
                      "invalid": sorted(i for i, c in code.items() if c == "INVALID"),
                      "problems": [list(p) for p in problems]},
        "roots": roots}
    ans["established"], ans["not_established"] = _sentences(ans)
    return ans


def _accepted(view, v, by):
    """The attests behind version v's met or waiting guard: those of the actors the engine counted (`by`, its
    accepted_by: docs/V3.md §6, rule 1) whose body has every member the guard matches, each with the roles of the
    guard its actor holds under the receiver's profile."""
    g = view.recs[v]["guard"]
    rows = []
    for a in view.attests.get(v, []) if g is not None else []:
        x = view.recs[a]
        if x["actor"] in by and all(x["body"].get(k) == w for k, w in g["match"].items()):
            rows.append({"attest": a, "actor": x["actor"], "roles": [role for role in g["roles"] if view.holds(x["actor"], role)]})
    return sorted(rows, key=lambda d: (d["actor"], d["attest"]))


def _rests(out, starts):
    """Every id reached from `starts` along the graph's dependency edges (graph.WALK), the starts left out."""
    seen, todo = set(starts), sorted(starts)
    while todo:
        for rel, nxt in out.get(todo.pop(), []):
            if rel in G.WALK and nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen - set(starts)


def _pins(view, v, accepted, checkout):
    """The files the acceptances behind version v name, each compared with the checkout's tree (warrant.pins):
    {verdict, acceptances}. NONE: no acceptance names files. NOT_CHECKED: some do and no tree was read. Else FRESH when
    the guard's quorum is still met by the actors that name no files or have an acceptance whose every file is those
    bytes (unchanged or moved), and STALE when it is not."""
    rows, fresh, pinning = [], set(), set()
    read = checkout is not None and checkout["tree"] is not None
    for a in accepted:
        b = view.recs[a["attest"]]["body"]
        files = b.get("files")
        if files is None:
            continue
        pinning.add(a["actor"])
        commit = b.get("commit") if S.hex_of(b.get("commit"), 40) or S.hex_of(b.get("commit"), 64) else None
        if P.unreadable(files):
            word, listed = "UNKNOWN", []
        elif not read:
            word, listed = "NOT_CHECKED", [{"path": p, "blob": x, "verdict": "NOT_CHECKED", "detail": ""} for p, x in sorted(files.items())]
        else:
            got = P.compare(checkout["root"], commit or "unknown", files, checkout["head"], checkout["where"], checkout["commit"])
            word, listed = P.verdict(got), [{"path": p, "blob": files[p], "verdict": w, "detail": d} for w, p, d in got]
        if word == "UNCHANGED":
            fresh.add(a["actor"])
        rows.append({"attest": a["attest"], "actor": a["actor"], "commit": commit, "verdict": word, "files": listed})
    if not rows:
        return {"verdict": "NONE", "acceptances": []}
    if not read:
        return {"verdict": "NOT_CHECKED", "acceptances": rows}
    still = fresh | ({a["actor"] for a in accepted} - pinning)
    return {"verdict": "FRESH" if len(still) >= view.recs[v]["guard"]["quorum"] else "STALE", "acceptances": rows}


def _root(snap, view, rep, nodes, out, i, checkout):
    n = G.describe(rep, nodes, i)
    kind = "blob" if n["kind"] == "unavailable" and i in snap.blobs else n["kind"]
    rejected = rep["rejected"].get(i)
    root = {"kind": kind, "schema": n.get("schema"), "actor": n.get("actor"), "at": n.get("at"), "basis": n.get("basis"),
            "rejected": rejected.split(":")[0] if rejected else None, "lineage": None, "guard": None, "accepted": [],
            "challenges": {}, "pins": {"verdict": "NONE", "acceptances": []}, "unavailable": []}
    why = []
    if kind == "unavailable":
        why.append("UNAVAILABLE")
    elif "lineage" not in n:
        why.append("NOT_A_VERSION")
        root["challenges"] = _challenges(view, rep, {i})
        root["unavailable"] = _missing(snap, view, out, {i})
    else:
        L = n["lineage"]["root"]
        lin, g = rep["lineages"][L], n["guard"]
        acc = _accepted(view, i, g["accepted_by"])
        pins = _pins(view, i, acc, checkout)
        root.update(guard=g, accepted=acc, pins=pins, challenges=_challenges(view, rep, set(lin["versions"])),
                    unavailable=_missing(snap, view, out, {i} | {a["attest"] for a in acc}),
                    lineage={"root": L, "state": lin["state"], "reliance": lin["reliance"], "verdict": lin["verdict"],
                             "leaf": lin["leaf"], "effective": lin["effective"], "forks": lin["forks"]})
        if lin["effective"] != i:
            why.append("NOT_EFFECTIVE")
        elif lin["reliance"] != "ELIGIBLE":
            why.append(lin["reliance"])
        if pins["verdict"] == "STALE":
            why.append("STALE")
            if not why[:-1]:
                root["lineage"]["reliance"] = "STALE"          # the receiver's tree read beside the package (docs/V3.md §15)
        if pins["verdict"] == "NOT_CHECKED" and checkout is not None:
            why.append("PINS_NOT_CHECKED")
    root["why_not"] = why
    root["rely"] = not why
    return root


def _challenges(view, rep, targets):
    return {c: dict(x, actor=view.recs[c]["actor"]) for c, x in sorted(rep["challenges"].items()) if x["target"] in targets}


def _missing(snap, view, out, starts):
    return sorted(x for x in _rests(out, starts) if x not in view.recs and x not in snap.blobs)


# ---------------------------------------------------------------- in sentences

def _n(n, one, many=None):
    return f"{n} {one if n == 1 else many or one + 's'}"


def _sentences(ans):
    """(established, not_established): each sentence names its dimension first and is built from what this run found.
    One sentence is always there: no package can show what its sender left out."""
    yes, no = [], []
    it, au, co, ex = ans["integrity"], ans["authenticity"], ans["completeness"], ans["execution"]
    tree = (ans["checkout"] or {}).get("tree")
    yes.append(f"integrity: {_n(it['records'], 'record')} and {_n(it['blobs'], 'blob')}, each named by the hash of its "
               f"bytes, checked here; together they are package {ans['package']}")
    bound = au["signed"] - au["named_keys"]
    if bound:
        yes.append(f"authenticity: {_n(bound, 'record')} signed with a key your trust binds to the record's actor; "
                   "each signature verified here")
    if au["named_keys"]:
        yes.append(f"authenticity: {_n(au['named_keys'], 'challenge')} signed with the key its actor names itself by; "
                   "the signature verified here, and no trust says whose key it is")
    for m in au["migrations"]:
        no.append(f"authenticity: {_n(m['records'], 'record')} unsigned, vouched for by migration {m['attest'][:12]} of "
                  f"{m['actor']}, a migrator in your profile: that actor's word, not the writers' signatures")
    if au["rejected"]:
        no.append(f"authenticity: {_n(len(au['rejected']), 'record')} with no signature that verifies under your trust "
                  "and no migration you accept: left out, counted for nothing")
    if ex["schemas"]:
        yes.append(f"execution: {_n(len(ex['schemas']), 'schema')} counted at your quorum of {ex['quorum']} "
                   f"schema/author: {', '.join(sorted(ex['schemas']))}")
    if ex["schemas_pending"]:
        no.append(f"execution: {_n(len(ex['schemas_pending']), 'schema')} short of your quorum of {ex['quorum']} "
                  f"schema/author, counted for nothing: {', '.join(sorted(ex['schemas_pending'].values()))}")
    if ex["invalid"]:
        no.append(f"execution: {_n(len(ex['invalid']), 'record')} that fit no schema you count: left out")
    if ex["problems"]:
        codes = sorted({p[0] for p in ex["problems"]})
        no.append(f"execution: the engine lists {_n(len(ex['problems']), 'problem')}: "
                  + ", ".join(f"{c} {sum(1 for p in ex['problems'] if p[0] == c)}" for c in codes))
    no.append("completeness: the package holds what its sender chose to include: a challenge or a later version it "
              "left out cannot be seen here")
    if co["unavailable"]:
        no.append(f"completeness: {_n(len(co['unavailable']), 'record or blob', 'records or blobs')} that the roots rest "
                  "on, named and not in the package: " + ", ".join(x[:12] for x in co["unavailable"]))
    if co["unanchored"]:
        no.append(f"completeness: {_n(co['unanchored'], 'signed record')} naming an earlier record of its writer that "
                  "the package does not hold: the writers' own order is not witnessed here")
    if co["chain_forks"]:
        no.append(f"completeness: {_n(co['chain_forks'], 'writer')} with two records naming the same earlier one: that "
                  "writer's order forks")
    if co["later"]:
        no.append(f"completeness: {_n(co['later'], 'record')} dated after {ans['receiver']['as_of']}, left out of this view")
    if ans["asked"]["by"] == "package":
        no.append("reliance: the roots answered are the ones the package names; --require names the ones you ask about")
    if not ans["roots"]:
        no.append("reliance: no root is named, by --require or by the package: nothing was asked, nothing is relied on")
    for i, r in ans["roots"].items():
        _root_sentences(i, r, tree, ans["checkout"] is not None, yes, no)
    return yes, no


def _root_sentences(i, r, tree, asked_tree, yes, no):
    s, lin, pins = i[:12], r["lineage"], r["pins"]
    if lin and lin["effective"] == i:
        head = f"reliance: {s} ({r['schema']}, state {lin['state']}) is the effective version of its lineage"
        if r["guard"]["guard"] == E.MET:
            by = ", ".join(sorted({f"{a['actor']} ({', '.join(a['roles'])})" for a in r["accepted"]}))
            yes.append(f"{head}; its guard is met by {by}" if by else f"{head}; its guard asks for no attest")
        else:
            yes.append(f"{head}; it carries no guard and stands as filed by {r['actor']}"
                       + (", unsigned, on a migration's word" if r["basis"] == "MIGRATED" else ""))
        if not r["guard"]["challenged_by"]:
            yes.append(f"reliance: no challenge in the package stands against {s}")
    for a in pins["acceptances"]:
        files, who = _n(len(a["files"]), "file"), f"{a['attest'][:12]} by {a['actor']}"
        if a["verdict"] == "UNCHANGED":
            moved = sum(1 for f in a["files"] if f["verdict"] == "MOVED")
            yes.append(f"pins: {s}: the acceptance {who} names {files}, the same bytes in your tree {tree[:12]}"
                       + (f", {moved} at another path" if moved else ""))
        elif a["verdict"] == "CHANGED":
            other = _n(sum(1 for f in a["files"] if f["verdict"] not in P.FRESH), "file")
            no.append(f"pins: {s}: the acceptance {who} names {files}; {other} of them are other bytes in your tree {tree[:12]}")
        elif a["verdict"] == "UNKNOWN":
            no.append(f"pins: {s}: the acceptance {who} names its files in no form that can be compared")
        else:
            no.append(f"pins: {s}: the acceptance {who} names {files}; "
                      + ("git is not available here" if asked_tree else "no checkout was given")
                      + ", so whether they are still those bytes is not checked")
    if asked_tree and lin and pins["verdict"] == "NONE":
        no.append(f"pins: {s}: no acceptance behind it names files: nothing ties it to your tree")
    if r["rely"]:
        return
    cause = []
    if "NOT_EFFECTIVE" in r["why_not"]:
        if lin["verdict"] == "FORK":
            cause.append("its lineage forks and has no effective version")
        if r["guard"]["guard"] == E.PENDING:
            cause.append("its guard waits for " + " and ".join(r["guard"]["waiting"]))
        if lin["effective"]:
            cause.append(f"{lin['effective'][:12]} is the effective version of its lineage")
    words = {
        "UNAVAILABLE": "the package holds no admitted record of that id" + (f" (its line is {r['rejected']})" if r["rejected"] else ""),
        "NOT_A_VERSION": f"it is a record of kind {r['kind']} in no lineage",
        "NOT_EFFECTIVE": "; ".join(cause) or "its lineage has no effective version",
        "CHALLENGED": "a counted challenge stands against it: " + ", ".join(c[:12] for c in (r["guard"] or {}).get("challenged_by", [])),
        "STALE": "the files its acceptances name are no longer those bytes in your tree",
        "PINS_NOT_CHECKED": "the files its acceptances name were to be compared with your tree and could not be",
    }
    no.append(f"reliance: {s} is not relied on: " + "; ".join(words.get(w, f"its lineage reads {w}") for w in r["why_not"]))


# ---------------------------------------------------------------- the command

def read_checkout(d):
    """What the pins are compared with: HEAD's commit and tree in the Git checkout `d`, and {path: blob} of it; with no
    git to ask, a tree of None (the pins then read NOT_CHECKED, never fresh). A directory that is no checkout with a
    commit is the receiver's own mistake."""
    try:
        commit = P.git(d, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        head = P.blobs(d, commit)
        return {"root": d, "commit": commit, "tree": P.git(d, "rev-parse", f"{commit}^{{tree}}"), "head": head,
                "where": P.paths_of(head)}
    except subprocess.CalledProcessError:
        raise Usage(f"--checkout {d}: not a Git checkout with a commit") from None
    except OSError:
        return {"root": d, "commit": None, "tree": None, "head": None, "where": None}


def _own(path, flag):
    """A JSON file of the receiver's own."""
    try:
        with open(path, "rb") as f:  # NOSONAR S8707: a file of the receiver's own that its command line names, read as data
            return read_json(f.read())
    except OSError as e:
        raise Usage(f"{flag} {path}: {type(e).__name__}") from None
    except Refusal:
        raise Usage(f"{flag} {path}: not JSON that reads one way") from None


def _receiver(a):
    if a.config and not (a.trust or a.profile):
        doc = _own(a.config, "--config")
        if not (isinstance(doc, dict) and "trust" in doc and "profile" in doc):
            raise Usage(f"--config {a.config}: not a receiver configuration {{trust, profile}}")
        trust, profile = doc["trust"], doc["profile"]
    elif a.trust and a.profile and not a.config:
        trust, profile = _own(a.trust, "--trust"), _own(a.profile, "--profile")
    else:
        raise Usage("name the receiver: --trust T and --profile P, or --config V3JSON")
    return trust, profile                                # verify() holds them to their shapes


def _run(argv, prog):
    ap = argparse.ArgumentParser(prog=prog, allow_abbrev=False, description="May this receiver rely on what it was "
                                 "handed? Exit 0: yes, every root asked for. 1: no. 2: a wrong command line. 3: an "
                                 "error of the verifier.")
    ap.add_argument("package", help="a package/3 file (handoff export)")
    ap.add_argument("--trust", help="your trust/3 file: which keys are whose")
    ap.add_argument("--profile", help="your profile/3 file: who holds which role")
    ap.add_argument("--config", help="a file holding both, {trust, profile} (a repository's .warrant/v3.json)")
    ap.add_argument("--as-of", type=int, help="leave out records dated after this Unix time")
    ap.add_argument("--checkout", help="a Git checkout: compare the files the acceptances name with its HEAD")
    ap.add_argument("--require", nargs="+", action="extend", default=[], metavar="ROOT",
                    help="the record ids you ask about (default: the ones the package names)")
    ap.add_argument("--max-bytes", type=int, default=MAX_BYTES, help=f"refuse a larger package (default {MAX_BYTES})")
    a = ap.parse_args(argv)
    if a.max_bytes < 1 or (a.as_of is not None and a.as_of < 0):
        raise Usage("--max-bytes is at least 1 and --as-of is not negative")
    if not all(S.hex64(r) for r in a.require):
        raise Usage("--require names record ids: 64 lowercase hex digits each")
    trust, profile = _receiver(a)
    try:
        with open(a.package, "rb") as f:  # NOSONAR S8707: the package its command line names, read as data within --max-bytes
            raw = f.read(a.max_bytes + 1)
    except OSError as e:
        raise Usage(f"the package {a.package}: {type(e).__name__}") from None
    ans = verify(raw, trust, profile, a.as_of, a.require, None if a.checkout is None else read_checkout(a.checkout), a.max_bytes)
    line = C.canon(ans) + b"\n"
    out = getattr(sys.stdout, "buffer", None)            # the bytes, whatever encoding the terminal has
    if out is None:
        sys.stdout.write(line.decode("utf-8"))
    else:
        out.write(line)
        out.flush()
    return 0 if ans["rely"] else 1


def main(argv=None, prog="warrant verify"):
    """The command: the exit status is the gate (module docstring). An error of this file exits 3: an uncaught Python
    error would exit 1, the code of a negative answer."""
    try:
        return _run(sys.argv[1:] if argv is None else list(argv), prog)
    except Usage as e:
        print(f"{prog}: {e}", file=sys.stderr)
        return 2
    except Exception as e:                       # NOSONAR: every error of the verifier itself is exit 3
        print(f"{prog}: error of the verifier: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
'''

# ---------------------------------------------------------------- Ed25519, verification only (RFC 8032 §5.1.7)
#
# The check OpenSSL makes, which the `cryptography` library calls: S below the group order, the public key a point
# of the curve, and the bytes of [S]B - [h]A equal to the signature's first half. No cofactor is multiplied in, and
# R is never decoded: another encoding of the same point, or a point off by a small-order one, is another signature.
# warrant/keys.py refuses the small-order and non-canonical public keys before either implementation sees one.

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _x_of(y, sign):
    """The x of the curve's point with this y and this sign of x, or None when there is none."""
    if y >= _P:
        return None
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if xx == 0:
        return None if sign else 0
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P:
        x = x * _I % _P
    if (x * x - xx) % _P:
        return None
    return _P - x if x & 1 != sign else x


def _add(p, q):
    """The sum of two points in extended coordinates (the unified, complete addition of RFC 8032 §5.1.4)."""
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a, b = (y1 - x1) * (y2 - x2) % _P, (y1 + x1) * (y2 + x2) % _P
    c, d = 2 * t1 * t2 * _D % _P, 2 * z1 * z2 % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _encode(p):
    x, y, z, _ = p
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return (y | (x & 1) << 255).to_bytes(32, "little")


_BY = 4 * pow(5, _P - 2, _P) % _P
_BX = _x_of(_BY, 0)
_B = (_BX, _BY, 1, _BX * _BY % _P)


def ed25519_verify(public, signature, message):
    """True iff `signature` (64 bytes) is the Ed25519 signature of `message` under `public` (32 bytes)."""
    if len(public) != 32 or len(signature) != 64:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    y = int.from_bytes(public, "little")
    x = _x_of(y & ((1 << 255) - 1), y >> 255)
    if x is None:
        return False
    y &= (1 << 255) - 1
    minus_a = ((_P - x) % _P, y, 1, (_P - x) * y % _P)
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _L
    both, acc = _add(_B, minus_a), (0, 1, 1, 0)
    for i in range(max(s.bit_length(), h.bit_length()) - 1, -1, -1):        # [s]B + [h](-A), one pass over the bits
        acc = _add(acc, acc)
        bs, bh = s >> i & 1, h >> i & 1
        if bs or bh:
            acc = _add(acc, both if bs and bh else _B if bs else minus_a)
    return _encode(acc) == signature[:32]


# ---------------------------------------------------------------- the loader

def _stand_in():
    """The names warrant/keys.py imports from `cryptography`, over the verification above: for an interpreter that
    has no such library. Verification only: this file signs nothing and creates no key."""
    class InvalidSignature(Exception):
        pass

    class Ed25519PublicKey:
        def __init__(self, raw):
            self._raw = raw

        @classmethod
        def from_public_bytes(cls, raw):
            return cls(bytes(raw))

        def verify(self, signature, data):
            if not ed25519_verify(self._raw, bytes(signature), bytes(data)):
                raise InvalidSignature()

    class Ed25519PrivateKey:
        """Named by warrant/keys.py's import; never made here."""

    ed = "cryptography.hazmat.primitives.asymmetric.ed25519"
    members = {"cryptography": {"__version__": "none: the standard library"},
               "cryptography.exceptions": {"InvalidSignature": InvalidSignature},
               "cryptography.hazmat": {}, "cryptography.hazmat.primitives": {},
               "cryptography.hazmat.primitives.serialization": {}, "cryptography.hazmat.primitives.asymmetric": {},
               ed: {"Ed25519PublicKey": Ed25519PublicKey, "Ed25519PrivateKey": Ed25519PrivateKey}}
    for name, inside in members.items():
        m = types.ModuleType(name)
        m.__dict__.update(inside, __path__=[])
        sys.modules[name] = m
        if "." in name:
            setattr(sys.modules[name.rpartition(".")[0]], name.rpartition(".")[2], m)


def _signatures():
    """Use `cryptography` when this interpreter has it, as the package does; else the stand-in. Both give the same
    answer on every input (tests/verify_test.py holds them to each other and to the Ed25519 vectors)."""
    try:
        from cryptography.exceptions import InvalidSignature  # noqa: F401
        from cryptography.hazmat.primitives import serialization  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey  # noqa: F401
    except Exception:                    # absent, or present and unusable: neither is a reason to verify nothing
        for name in [n for n in sys.modules if n == "cryptography" or n.startswith("cryptography.")]:
            del sys.modules[name]
        _stand_in()


def _load():
    """The modules of SOURCES as the package `warrant`, in this process only: each compiled from its text above, in
    ORDER (a module after the ones it imports). No file is read, and an installed `warrant` is never imported."""
    pkg = types.ModuleType("warrant")
    pkg.__path__, pkg.__package__ = [], "warrant"
    sys.modules["warrant"] = pkg
    for name in ORDER:
        m = types.ModuleType(f"warrant.{name}")
        m.__package__, m.__file__ = "warrant", f"<warrant/{name}.py in warrant_verify.py>"
        sys.modules[m.__name__] = m
        exec(compile(SOURCES[name], f"warrant/{name}.py", "exec"), m.__dict__)
        setattr(pkg, name, m)
    # The engine names its code by the files of an installed package; here the code is this file's SOURCES. No answer
    # of `verify` carries that name: it differs between this file and the package, and their answers do not.
    sys.modules["warrant.engine"]._CODE[:] = [hashlib.sha256(repr(sorted(DIGESTS.items())).encode()).hexdigest()]
    return sys.modules["warrant.verify"]


def main(argv):
    _signatures()
    return _load().main(argv, prog="warrant_verify.py")


if __name__ == "__main__":
    try:
        status = main(sys.argv[1:])
    except Exception as e:               # an error of this file is exit 3, never the 1 of an uncaught Python error
        print(f"warrant_verify.py: error of the verifier: {type(e).__name__}: {e}", file=sys.stderr)
        status = 3
    sys.exit(status)
