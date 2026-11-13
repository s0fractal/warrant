#!/usr/bin/env python3
"""The second implementation, impl-js/warrant.mjs (Node, no dependencies), against this package's engine.

Both engines assess the same (lines, blobs, trust, profile, as_of). Their reports must be the same canonical bytes
but for the engine's identity (`code`, `assessment`), as warrant/differential.py compares two releases: compare()
also checks that each report's `assessment` is the digest of its own operands. A refusal must be the same refusal,
word for word; a crash of either engine is a disagreement. The classes:

  J1  the repository's own store under .warrant/v3.json, through both commands (`warrant assess`, `warrant.mjs assess`),
      and a store whose blob is not named by its hash
  J2  every World tests/core_test.py assesses, captured as its cases run (its own lines are silenced): the rejected
      lines, duplicates, forged signatures, the limits and every rule's negative case
  J3  the store QUICKSTART.md builds, after each of its command blocks
  J4  mutations of the J1-J3 stores: lines dropped, duplicated, reordered; one byte flipped; a signature cut, zeroed or
      removed; one byte of a body changed; a record changed and signed again with the test keys; the receiver's
      roles, quorum and as_of changed. Seeded, so a run is reproducible (--seed).
  J5  handoff inspect alone: `warrant.mjs verify` (here its batch form) against warrant_agent's handoff, on packages
      of the J2 worlds and their mutations
  J6  the encoding: the vendored primitives vectors (canon, blob-hash, sig-message, verify-sig), the Ed25519 edge
      vectors, the WebCrypto backend on a world, and repr/actor-id shapes of every code point (Python's Unicode
      tables against the platform's)

One ok/FAIL line per case (J4: per mutated source, with its count). Skips when `node` is not on PATH.

    python3 tests/impl_js_test.py [--seed N] [--mutations N] [--vectors DIR] [--quick]

--vectors DIR also writes the J2-J5 cases with Python's answers (impl-js/vectors/, read by impl-js/check_vectors.mjs);
--quick leaves out J1's mutations of the repository's store (the slow part).
"""
import argparse
import base64
import contextlib
import copy
import gzip
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

from world import ROOT, Repo, check, finish

from warrant import bootstrap as B          # noqa: E402
from warrant import differential as DF      # noqa: E402
from warrant import engine as E             # noqa: E402
from warrant import jcs as C                # noqa: E402
from warrant import keys as K               # noqa: E402
from warrant import records as R            # noqa: E402
from warrant import shapes as SH            # noqa: E402
from warrant import store as ST             # noqa: E402

NODE = shutil.which("node")
JS = ROOT / "impl-js" / "warrant.mjs"
IDENTITY = set(DF.IDENTITY) | {"adapter"}      # what names an engine (and, for handoff, its adapter), not what it found
TEST_SEEDS = [f"{i:02x}" * 32 for i in range(1, 6)] + ["0a" * 32]     # tests/core_test.py, tests/world.py, KN1's outsider
TEST_KEYS = {k.public: k for k in (K.Key.from_seed_hex(s) for s in TEST_SEEDS)}
MAX_FAIL_LINES = 40


# ---------------------------------------------------------------- the two engines

def py_report(case):
    try:
        return E.assess(ST.Snapshot(case["lines"], case["blobs"]), case["trust"], case["profile"], case.get("as_of"))
    except (ST.Refused, R.Invalid, C.NotCanonical) as e:
        return {"refused": str(e)}
    except Exception as e:          # noqa: BLE001 - a crash of the reference is a finding, not an abort
        return {"crash": f"Python {type(e).__name__}: {e}"}


def wire(case):
    """A case as the JS batch (and the vectors) read it: lines and blobs in base64, the receiver as JSON."""
    if "package" in case:
        return {"package": case["package"], "trust": case["trust"], "profile": case["profile"]}
    return {"lines": [base64.b64encode(x).decode() for x in case["lines"]],
            "blobs": {h: base64.b64encode(b).decode() for h, b in sorted(case["blobs"].items())},
            "trust": case["trust"], "profile": case["profile"], "as_of": case.get("as_of")}


def js_batch(cases, extra=()):
    """warrant.mjs's answer to each case, in order (one node process for all of them)."""
    if not cases:
        return []
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "cases.jsonl"
        with f.open("w") as out:
            for c in cases:
                out.write(json.dumps(wire(c)) + "\n")
        p = subprocess.run([NODE, str(JS), "batch", str(f), *extra], capture_output=True, check=False, timeout=3600)
    if p.returncode:
        raise RuntimeError(f"node exited {p.returncode}: {p.stderr.decode(errors='replace')[-800:]}")
    got = [json.loads(x) for x in p.stdout.decode().splitlines()]
    if len(got) != len(cases):
        raise RuntimeError(f"node answered {len(got)} of {len(cases)} cases")
    return got


def agree(py, js, operands=DF.OPERANDS):
    """None when the two answers agree, else what differs."""
    if not isinstance(py, dict) or not isinstance(js, dict):
        return "an answer is not an object"
    if {"refused", "crash", "error"} & (set(py) | set(js)):
        return None if C.canon(py) == C.canon(js) else f"python {str(py)[:300]} | js {str(js)[:300]}"
    for name, rep in (("python", py), ("js", js)):
        if rep.get("assessment") != C.doc_id({k: rep.get(k) for k in operands}):
            return f"the {name} report's assessment is not its operands' digest"
    differs = [m for m in sorted((set(py) | set(js)) - IDENTITY) if m not in py or m not in js or C.canon(py[m]) != C.canon(js[m])]
    return None if not differs else f"members differ: {differs}: " + "; ".join(
        f"{m}: python {str(py.get(m))[:200]} | js {str(js.get(m))[:200]}" for m in differs[:3])


def features(py):
    """What an answer exercises: problem codes, rejection reasons, refusals, guard words, reliance, the rest."""
    if "refused" in py:
        return {"refused: " + py["refused"].split(":")[0][:40]}
    if "error" in py:
        return {"error: " + py["error"]}
    if "crash" in py:
        return {"crash"}
    rep = py if "lineages" in py else None
    out = set()
    if rep is None:
        return {"inspect"}
    out |= {"problem " + p[0] for p in rep["problems"]}
    out |= {"rejected " + w.split(":")[0] + (": " + w.split(":")[1].strip()[:28] if w.startswith("line") else "") for w in rep["rejected"].values()}
    out |= {"guard " + v["guard"] for v in rep["versions"].values()} | {"reliance " + x["reliance"] for x in rep["lineages"].values()}
    out |= {"challenge " + c["why"][:30] + (" standing" if c["stands"] else "") for c in rep["challenges"].values()}
    out |= {k for k, on in (("chain fork", rep["chains"]["forks"]), ("unanchored", rep["chains"]["unanchored"]),
                            ("duplicates", rep["duplicates"]), ("later", rep["later"]), ("not canonical", not rep["canonical"]),
                            ("schemas pending", rep["schemas_pending"]), ("MIGRATED", rep["basis"]["MIGRATED"])) if on}
    return out


class Tally:
    def __init__(self):
        self.classes, self.disagreements, self.vectors, self.seen = {}, [], [], {}

    def add(self, cls, name, case, py, js):
        for f in features(py):
            self.seen[f] = self.seen.get(f, 0) + 1
        why = agree(py, js)
        if why and declared(py, js):
            self.departed = getattr(self, "departed", []) + [(cls, name, declared(py, js))]
            why = None
        n = self.classes.setdefault(cls, [0, 0])
        n[0] += 1
        n[1] += why is None
        if why:
            self.disagreements.append((cls, name, why))
        if cls in VECTOR_CLASSES and " / " not in name and not name.startswith("deep:"):             # the worlds, crafted cases, quickstart, packages; no mutation
            self.vectors.append({"class": cls, "name": name, "case": wire(case), "expect": {k: v for k, v in py.items() if k not in IDENTITY}})
        return why


def run_cases(tally, cls, named, quiet=False, label=None):
    """Assess each (name, case) with both engines; one line per case unless quiet. The disagreements' reasons."""
    pys = [py_answer(c) for _, c in named]
    jss = js_batch([c for _, c in named])
    out = []
    for (name, case), py, js in zip(named, pys, jss):
        why = tally.add(cls, name, case, py, js)
        out.append(why)
        if not quiet:
            check(f"{cls} {name}", why is None, why)
    if quiet and named:
        bad = [w for w in out if w]
        check(f"{cls} {label}", not bad, f"{len(named)} cases, {len(named) - len(bad)} agree", bad[:1])
    return out


def canon_short(v):
    keep = {k: v[k] for k in ("error", "message", "problems", "rejected", "schemas") if k in v} if isinstance(v, dict) else v
    return C.canon(keep).decode()[:300]


def py_answer(case):
    return py_inspect(case) if "package" in case else py_report(case)


# ---------------------------------------------------------------- J2: the worlds tests/core_test.py builds

def capture_core_worlds():
    """[(name, case)] of every assessment tests/core_test.py makes, in order, by patching engine.assess and
    store.Snapshot to remember their inputs (core_test's own lines are silenced; its verdicts are its own)."""
    import core_test as CT
    cases, label = [], ["?"]
    orig_assess, orig_init = E.assess, ST.Snapshot.__init__

    def init(self, lines, blobs):
        self._src = (list(lines), dict(blobs))
        orig_init(self, lines, blobs)

    def assess(snap, trust, profile, as_of=None):
        lines, blobs = snap._src
        cases.append((f"{label[0]}#{sum(1 for n, _ in cases if n.startswith(label[0] + '#')) + 1}",
                      {"lines": lines, "blobs": blobs, "trust": json.loads(json.dumps(trust)),
                       "profile": json.loads(json.dumps(profile)), "as_of": as_of}))
        return orig_assess(snap, trust, profile, as_of)

    E.assess, ST.Snapshot.__init__ = assess, init
    try:
        for fn in (CT.lineage_cases, CT.schema_cases, CT.pin_cases, CT.guard_cases, CT.release_cases, CT.challenge_cases,
                   CT.store_cases, CT.chain_cases, CT.migration_cases):
            label[0] = fn.__name__
            with contextlib.redirect_stdout(io.StringIO()):
                fn()
    finally:
        E.assess, ST.Snapshot.__init__ = orig_assess, orig_init
    return cases


# ---------------------------------------------------------------- J2: lines and records made to be refused

def _world():
    import core_test as CT
    return CT.World()


def _receiver(w):
    return {"trust": json.loads(json.dumps(w.trust)), "profile": {"warrant": "profile/3", "roles": json.loads(json.dumps(w.roles))}}


def line_cases():
    """[(name, case)]: one world (its schemas, a claim, its acceptance) plus one line made to meet one reader rule of
    store.py, jcs.py and records.check: every refusal the line reader can give, and lines it must read."""
    w = _world()
    c = w.claim()
    w.attest("bob", c)
    base, rc = list(w.lines), _receiver(w)
    bob = w.keys["bob"]

    def rec(**over):
        r = R.record("attest", "bob", 500, {"target": c, "verdict": "accept"}, refs=[c])
        r.update(over)
        return r

    def signed(r):
        return C.canon({"record": r, "sig": {"key": bob.id, "ed25519": bob.sign(R.SIG_DOMAIN + bytes.fromhex(C.doc_id(r)))}}) + b"\n"

    good = signed(rec())
    text = good.decode()
    sub = lambda a, b: text.replace(a, b, 1).encode()                      # noqa: E731 - a byte-level edit of the good line
    lines = {
        "a line longer than 65536 bytes": signed(rec(body={"target": c, "verdict": "x" * 70000})),
        "a body over 16384 bytes": signed(rec(body={"target": c, "verdict": "x" * 20000})),
        "a float": sub('"at":500', '"at":500.0'), "an exponent": sub('"at":500', '"at":5e2'), "NaN": sub('"at":500', '"at":NaN'),
        "Infinity": sub('"at":500', '"at":Infinity'), "-Infinity": sub('"at":500', '"at":-Infinity'),
        "a repeated member": sub('"verdict":"accept"', '"verdict":"accept","verdict":"accept"'),
        "a repeated member, then a float": sub('"verdict":"accept"', '"verdict":"a","verdict":"b","x":1.5'),
        "a repeated non-ASCII member": sub('"verdict":"accept"', '"é\\u0000­\U0001F600\'":1,"é\\u0000­\U0001F600\'":2'),
        "a lone high surrogate": sub('"accept"', '"\\ud800"'), "a lone low surrogate in a key": sub('"verdict":', '"\\udc00x":'),
        "an escaped pair in capitals": sub('"accept"', '"\\uD83D\\uDE00"'), "an escaped pair": sub('"accept"', '"\\ud83d\\ude00"'),
        "a pair after a lone high surrogate": sub('"accept"', '"\\ud83d\\ud83d\\ude00"'), "a bad \\u escape": sub('"accept"', '"\\u12g4"'),
        "an escaped solidus": sub('"accept"', '"a\\/b"'), "a raw control character": sub('"accept"', '"a\tb"'),
        "2^53": sub('"at":500', '"at":9007199254740992'), "-2^53 in a body": sub('"accept"', '-9007199254740992'),
        "2^53-1": sub('"at":500', '"at":9007199254740991'), "-0": sub('"at":500', '"at":-0'), "a leading zero": sub('"at":500', '"at":0500'),
        "an integer of 5000 digits": sub('"accept"', "1" * 5000), "an integer of 4300 digits": sub('"accept"', "1" * 4300),
        "a negative integer of 4301 digits": sub('"accept"', "-" + "1" * 4301),
        "an invalid UTF-8 byte": good.replace(b'"accept"', b'"acc\xffpt"'), "an encoded surrogate": good.replace(b'"accept"', b'"\xed\xa0\x80"'),
        "an overlong encoding": good.replace(b'"accept"', b'"\xc0\xaf"'), "a BOM": b"\xef\xbb\xbf" + good,
        "a leading space": b" " + good, "a trailing space": good[:-1] + b" \n", "a carriage return": good[:-1] + b"\r\n",
        "two newlines": good + b"\n", "no newline": good[:-1], "a tab": good[:-1] + b"\t\n",
        "nested 300 deep": sub('"accept"', "[" * 300 + "]" * 300), "nested 1100 deep": sub('"accept"', "[" * 1100 + "]" * 1100),
        "nested 257 deep, empty": sub('"accept"', "[" * 254 + "]" * 254),
        "1100 brackets 3 deep": sub('"accept"', "[" + ",".join(["[[]]"] * 370) + "]"),
        "brackets inside a string": sub('"accept"', '"' + "[" * 1100 + '"'),
        "not JSON": b"not json\n", "an array": b"[]\n", "an object": b"{}\n", "a record that is a number": b'{"record":1,"sig":null}\n',
        "no sig member": sub(',"sig":{', ',"sog":{'), "a third member": sub('{"record":', '{"a":1,"record":'),
        "UTF-16 key order": sub('"verdict":"accept"', '"verdict":"accept","\U0001F600":1,"￿":2'),
        "code point key order (not canonical)": sub('"verdict":"accept"', '"verdict":"accept","￿":2,"\U0001F600":1'),
        "U+2028 and U+007F in a string": sub('"accept"', '" \u007f"'),
    }
    for name, r in {
        "an extra record member": rec(x=1), "warrant 2": rec(warrant="2"), "warrant 3 as a number": rec(warrant=3),
        "an unknown kind": rec(kind="note"), "a kind in a list": rec(kind=["attest"]), "an empty actor": rec(actor=""),
        "an actor with a space first": rec(actor=" bob"), "an actor with a no-break space last": rec(actor="bob "),
        "an actor with a control character": rec(actor="b\u0000b"), "an actor with U+0085": rec(actor="b\u0085b"),
        "an actor not in NFC": rec(actor="é"), "an actor of 201 code points": rec(actor="a" * 201),
        "an actor of 200 astral code points": rec(actor="\U0001F600" * 200), "an actor of 201 astral code points": rec(actor="\U0001F600" * 201),
        "an actor ending in U+2029": rec(actor="bob "), "an actor ending in U+3000": rec(actor="bob　"),
        "at -1": rec(at=-1), "at true": rec(at=True), "at a string": rec(at="5"),
        "prev in capitals": rec(prev="AB" * 32), "prev too short": rec(prev="ab" * 31), "prev with a newline": rec(prev="ab" * 31 + "a\n"),
        "lineage a number": rec(lineage=5), "refs unsorted": rec(refs=sorted([c, "ff" * 32], reverse=True)),
        "refs repeated": rec(refs=[c, c]), "refs in capitals": rec(refs=[c.upper()]), "a body that is a list": rec(body=[c]),
        "an attest with a guard": rec(guard=R.guard()), "a guard missing a member": rec(kind="entity", schema="claim@1", guard={"quorum": 0}),
        "a guard of quorum -1": rec(kind="entity", schema="claim@1", guard=dict(R.guard(), quorum=-1)),
        "a guard of quorum true": rec(kind="entity", schema="claim@1", guard=dict(R.guard(), quorum=True)),
        "guard roles unsorted": rec(kind="entity", schema="claim@1", guard=dict(R.guard(), roles=["b", "a"])),
        "guard match a list": rec(kind="entity", schema="claim@1", guard=dict(R.guard(), match=[])),
        "guard requires unsorted": rec(kind="entity", schema="claim@1", guard=dict(R.guard(), requires=["ff" * 32, "00" * 32])),
        "a schema record naming a schema": rec(kind="schema", schema="x"), "an empty schema name": rec(schema=""),
        "a schema name of 101 characters": rec(schema="s" * 101), "a schema name of 100 astral characters": rec(schema="\U0001F600" * 100),
        "a schema name that is a number": rec(schema=5), "an entity without a schema": rec(kind="entity"),
        "an attest without a target": rec(body={"verdict": "accept"}), "a target not in refs": rec(refs=[]),
        "an attest with a lineage": rec(lineage=c), "a target that is not an id": rec(body={"target": "x", "verdict": "accept"}),
        "a __proto__ member": rec(body={"target": c, "verdict": "accept", "__proto__": {"a": 1}, "constructor": 1}),
    }.items():
        try:
            lines[name] = signed(r)
        except Exception:               # noqa: BLE001 - the encoding refuses it: the line is written by hand
            lines[name] = C.canon({"record": r, "sig": None}) + b"\n"
    for name, sig in {"a sig without its signature": {"key": bob.id}, "a short signature": {"key": bob.id, "ed25519": "ab"},
                      "a sig with a third member": {"key": bob.id, "ed25519": "00" * 64, "x": 1}, "a sig that is a list": [],
                      "a sig that is a string": "x", "a key id in capitals": {"key": bob.id.upper(), "ed25519": "00" * 64},
                      "another key's id": {"key": w.keys["alice"].id, "ed25519": json.loads(good)["sig"]["ed25519"]}}.items():
        lines[name] = C.canon({"record": rec(), "sig": sig}) + b"\n"
    out = [(f"line: {name}", dict(rc, lines=base + [raw], blobs={}, as_of=None)) for name, raw in lines.items()]
    out.append(("line: the good line, alone", dict(rc, lines=base + [good], blobs={}, as_of=None)))
    return out


def receiver_cases():
    """[(name, case)]: receivers the engine refuses or reads, over one world."""
    w = _world()
    w.attest("bob", w.claim())
    rc = _receiver(w)
    t, p = rc["trust"], rc["profile"]
    cases = {
        "trust with a third member": (dict(t, x=1), p), "trust/2": (dict(t, warrant="trust/2"), p),
        "trust keys unsorted": (dict(t, keys=dict(t["keys"], alice=sorted(t["keys"]["alice"] + ["ff" * 32], reverse=True))), p),
        "trust naming a bad actor": (dict(t, keys={" x": []}), p), "profile without roles": (t, {"warrant": "profile/3"}),
        "profile roles unsorted": (t, dict(p, roles={"schema/author": ["bob", "alice"]})),
        "profile quorum 0": (t, dict(p, quorum={"schema/author": 0})), "profile quorum true": (t, dict(p, quorum={"x": True})),
        "profile quorum 2^60": (t, dict(p, quorum={"schema/author": 2 ** 60})), "profile with a fourth member": (t, dict(p, x=1)),
        "a role named __proto__": (t, dict(p, roles=dict(p["roles"], __proto__=["bob"], constructor=["carol"]))),
        "an empty profile's roles": (t, dict(p, roles={})), "no keys at all": (dict(t, keys={}), p),
    }
    out = [(f"receiver: {n}", dict(lines=list(w.lines), blobs={}, trust=tt, profile=pp, as_of=None)) for n, (tt, pp) in cases.items()]
    out += [(f"receiver: as_of {a}", dict(rc, lines=list(w.lines), blobs={}, as_of=a)) for a in (0, 105, 108, 10 ** 12)]
    return out


def boundary_cases():
    """[(name, case)]: Python's == over JSON values (True == 1, a missing member == null) where a guard or a pin matches,
    and requires nested exactly at LIMITS["requires"] and one beyond."""
    out = []
    w = _world()
    done = B.SCHEMAS[2]["states"]["done"]
    for n, (want, got) in enumerate([(1, True), (0, False), (True, 1), (None, "absent"), (1, 1.0 if False else "1"), ({"a": 1}, {"a": True})]):
        o = w.put("alice", "entity", {"state": "done", "statement": f"eq {n}", "serves": []}, "obligation@1",
                  guard=dict(done, match=dict(done["match"], n=want)))
        w.attest("bob", o, **({} if got == "absent" else {"n": got}))
    sch = {"name": "pin@1", "fields": {"state": "str", "by": "obj?"}, "states": {"open": None, "shut": None}, "closed": ["shut"],
           "successors": {}, "pinned": "by"}
    w.put("alice", "schema", sch)
    root = w.put("alice", "entity", {"state": "open", "by": {"k": True}}, "pin@1")
    w.put("alice", "entity", {"state": "shut"}, "pin@1", root, guard=R.guard(0, [], {"k": 1}))
    out.append(("Python's == in guard and pin matches", dict(_receiver(w), lines=list(w.lines), blobs={}, as_of=None)))
    # Member order in reasons: the members of the wrong type in the body's own (UTF-16, canonical) order, U+1F600 before
    # U+FFFF; the members a schema lacks in Python's sorted() (code point) order, U+FFFF before U+1F600.
    w = _world()
    w.put("alice", "schema", {"name": "order@1", "fields": {"￿": "int", "\U0001F600": "int", "Ａ": "int"}, "states": None,
                              "closed": [], "successors": {}})
    target = w.claim()
    w.put("bob", "attest", {"target": target, "￿": "x", "\U0001F600": "y", "Ａ": "z"}, "order@1", refs=[target])
    w.put("bob", "attest", {"target": target, "￿": 1, "\U0001F600": 1, "Ａ": 1, "\U0001F601": 1, "￾": 1}, "order@1", refs=[target])
    w.put("bob", "attest", {"target": target}, "order@1", refs=[target])
    out.append(("member order in reasons, above U+FFFF", dict(_receiver(w), lines=list(w.lines), blobs={}, as_of=None)))
    for depth in (ST.LIMITS["requires"], ST.LIMITS["requires"] + 1):
        chain, prev = _world(), None
        for n in range(depth):
            prev = chain.put("alice", "entity", {"state": "done", "statement": f"o{n}", "serves": []}, "obligation@1",
                             guard=R.guard(1, ["roadmap/acceptor"], {"verdict": "accept"}, [prev] if prev else []))
        out.append((f"requires nested {depth} deep", dict(_receiver(chain), lines=list(chain.lines), blobs={}, as_of=None)))
    return out


def spec_gap_cases():
    """[(name, case)]: where the reference departs from docs/V3.md and the port follows the reference (both must agree):
    a counted challenge against a version of a forked lineage, which §5 says stands (no later version is effective)
    and the reference does not stand; and a lineage deeper than the 4096 that _climb follows, whose deepest version
    sorts first by id, which §8 says refuses the store and the reference assesses, breaking 4096 versions."""
    w = _world()
    a = w.put("alice", "entity", {"state": "open", "statement": "a", "serves": []}, "obligation@1")
    for x in ("b", "c"):
        w.put("alice", "entity", {"state": "open", "statement": x, "serves": []}, "obligation@1", a)
    w.put("alice", "challenge", {"target": a, "statement": "x"}, refs=[a])
    out = [("spec gap: a counted challenge against a forked lineage's version", dict(_receiver(w), lines=list(w.lines), blobs={}, as_of=None))]
    w = _world()
    prev = w.put("alice", "entity", {"state": "open", "statement": "v0", "serves": []}, "obligation@1")
    for n in range(1, 4098):
        prev = w.put("alice", "entity", {"state": "open", "statement": f"v{n}", "serves": []}, "obligation@1", prev)
    low = min(R.rid(C.loads(x.rstrip(b"\n"))["record"]) for x in w.lines)
    for k in range(100000):          # a leaf whose id sorts before every other: _climb starts from it
        r = R.record("entity", "alice", w.t + 1, {"state": "open", "statement": f"leaf {k}", "serves": []}, "obligation@1", prev,
                     prev=w.heads["alice"])
        if R.rid(r) < low:
            break
    out.append(("deep: a lineage 4099 versions deep whose leaf sorts first", dict(_receiver(w), lines=list(w.lines) + [R.line(r, w.keys["alice"])[1]],
                                                                                 blobs={}, as_of=None)))
    return out


def exotic_actor_cases():
    """[(name, case)]: actors whose code point order is not their UTF-16 order (above U+D7FF), or that are names an
    object's prototype has, in every place the report sorts or keys by actor."""
    w = _world()
    names = ["\U0001F600a", "Ａb", "__proto__", "constructor"]
    for k, a in enumerate(names):
        w.keys[a] = K.Key.from_seed_hex(f"{0x20 + k:02x}" * 32)
        w.trust["keys"][a] = [w.keys[a].public]
    w.roles = dict(w.roles, **{"pr/acceptor": sorted(names[:3]), "challenger": ["constructor"], "roadmap/owner": sorted(["carol", "\U0001F600a"])})
    h = w.put("alice", "entity", {"state": "open", "pr": 1}, "pr-head@1")
    h1 = w.put("alice", "entity", {"state": "head", "commit": "c" * 40, "tree": "d" * 40}, "pr-head@1", h,
               guard=R.guard(3, ["pr/acceptor"], B.ACCEPT))
    for a in names[:3]:
        w.attest(a, h1)
    w.put("constructor", "challenge", {"target": h1, "statement": "P2", "severity": "P2", "what": "x", "where": [],
                                       "commit": "c" * 40, "tree": "d" * 40}, "finding@1", refs=[h1])
    for a in ("Ａb", "\U0001F600a"):            # two genesis records each: chain forks sorted by actor
        w.heads[a] = None
        w.attest(a, h, verdict="note")
    o = w.put("\U0001F600a", "entity", {"state": "open", "statement": "o", "serves": []}, "obligation@1")
    w.put("Ａb", "entity", {"state": "open", "statement": "o2", "serves": []}, "obligation@1", o)       # LINEAGE_NOT_AUTHOR
    return [("exotic actors", dict(_receiver(w), lines=list(w.lines), blobs={}, as_of=None)),
            ("exotic actors, reversed lines", dict(_receiver(w), lines=list(reversed(w.lines)), blobs={}, as_of=None))]


# Where the reference crashes and the specification gives an answer, the port answers it (docs/V3.md) and the
# departure is declared here: the case, the reference's crash and why. A declared departure that no longer occurs
# fails, so the list follows the reference.
def departure_cases():
    out = []
    w = _world()
    w.put("alice", "schema", {"name": "x@1", "fields": {"state": "str"}, "states": {"open": None}, "closed": [["open"]], "successors": {}})
    out.append(("a schema whose closed list holds a list", dict(_receiver(w), lines=list(w.lines), blobs={}, as_of=None),
                "Python TypeError", "§4: `closed` lists states; a body that is not a schema body is SCHEMA_NOT_COUNTED. "
                "engine._schema_problem tests `s in b['states']` with an unhashable item: any trusted signer's schema record "
                "makes every receiver's assess raise TypeError"))
    w = _world()
    rc = _receiver(w)
    rc["profile"]["roles"]["migrator"] = ["carol"]
    blob = b'{"map":[' + b"1" * 5000 + b"]}"
    h = hashlib.sha256(blob).hexdigest()
    w.put("carol", "attest", {"target": h, "verdict": "migrated"}, R.MIGRATION, refs=[h])
    out.append(("a migration map blob holding an integer of 5000 digits", dict(rc, lines=list(w.lines), blobs={h: blob}, as_of=None),
                "Python ValueError", "§9/§10: a target that is not a map is MIGRATION_MAP. Snapshot.json_blob catches NotCanonical "
                "only, and jcs.loads lets CPython's int digit limit escape as ValueError"))
    pkg = {"warrant": "package/3", "roots": ["00" * 32], "lines": ['{"record":"\ud800","sig":null}'], "blobs": {}}
    out.append(("a package line holding a lone surrogate", dict(rc, package=pkg), "Python UnicodeEncodeError",
                "§13 handoff: a package whose line is not text is a bad request. api._unpack encodes each line with str.encode, "
                "which raises out of api.call"))
    return out


def declared(py, js):
    """The declared departure this disagreement is (its name), or None."""
    crash = py.get("crash", "") if isinstance(py, dict) else ""
    for name, _, prefix, _ in DEPARTURES:
        if crash.startswith(prefix + ":") and "crash" not in js:
            return name
    return None


DEPARTURES = []


# ---------------------------------------------------------------- J1: the repository's store, both commands

def store_case(dot, receiver):
    st = ST.Store(dot)
    return {"lines": st.lines(), "blobs": {p.name: p.read_bytes() for p in sorted(st.blobs.iterdir())} if st.blobs.is_dir() else {},
            "trust": receiver["trust"], "profile": receiver["profile"], "as_of": None}


def cli_pair(dot, config, as_of=None):
    """(python's report, js's report, seconds each) of one store directory through each engine's command."""
    t = time.perf_counter()
    doc = json.loads(Path(config).read_text())
    try:
        py = E.assess(ST.Store(dot).snapshot(), doc["trust"], doc["profile"], as_of)
    except (ST.Refused, R.Invalid, C.NotCanonical) as e:
        py = {"refused": str(e)}
    tp = time.perf_counter() - t
    t = time.perf_counter()
    cmd = [NODE, str(JS), "assess", "--store", str(dot), "--config", str(config)] + (["--as-of", str(as_of)] if as_of is not None else [])
    p = subprocess.run(cmd, capture_output=True, check=False, timeout=600)
    tj = time.perf_counter() - t
    js = json.loads(p.stdout) if p.stdout.strip() else {"crash": p.stderr.decode(errors="replace")[-400:]}
    return py, js, tp, tj


def repo_cases(tally, args):
    dot, config = ROOT / ".warrant", ROOT / ".warrant" / "v3.json"
    py, js, tp, tj = cli_pair(dot, config)
    why = tally.add("J1", "repository store, CLI", None, py, js)
    n = len(ST.Store(dot).lines())
    check("J1 the repository's store under .warrant/v3.json: both commands' reports agree", why is None,
          f"{n} lines, python {tp:.2f} s, node {tj:.2f} s (each command, in process for python)", why)
    TIMINGS.append(("repository store, one assessment", tp, tj))
    with tempfile.TemporaryDirectory() as d:
        st = ST.Store(Path(d)).init()
        st.write_lines(ST.Store(dot).lines()[:40])
        (st.blobs / ("ab" * 32)).write_bytes(b"not these bytes")
        py, js, _, _ = cli_pair(Path(d), config)
        why = tally.add("J1", "blob not named by its hash", None, py, js)
        check("J1 a blob whose bytes do not hash to its name refuses the read in both, with the same words",
              why is None and "refused" in py, why or py)
    return store_case(dot, json.loads(config.read_text()))


def limit_cases(tally):
    """--limits (heavy, not by default): a store of LIMITS["records"] + 1 records and one of LIMITS["bytes"] + 1 bytes, through
    both commands: each refused before it is assessed, in the same words."""
    config = ROOT / ".warrant" / "v3.json"
    with tempfile.TemporaryDirectory(dir=ROOT.parent) as d:
        st = ST.Store(Path(d)).init()
        n = ST.LIMITS["records"] + 1
        with open(st.file, "wb") as f:
            for k in range(n):
                f.write(C.canon({"record": R.record("attest", "x", k, {"target": "00" * 32, "verdict": "x"}, refs=["00" * 32]), "sig": None}) + b"\n")
        py, js, tp, tj = cli_pair(Path(d), config)
        why = tally.add("J1", "records beyond the limit", None, py, js)
        check(f"J1 a store of {n} records is refused by both, in the same words", why is None and "refused" in py,
              f"python {tp:.1f} s, node {tj:.1f} s", why or py)
    with tempfile.TemporaryDirectory(dir=ROOT.parent) as d:
        st = ST.Store(Path(d)).init()
        big = b"\0" * (ST.LIMITS["bytes"] + 1)
        st.put_blob(big)
        del big
        py, js, tp, tj = cli_pair(Path(d), config)
        why = tally.add("J1", "bytes beyond the limit", None, py, js)
        check(f"J1 a store of {ST.LIMITS['bytes'] + 1} bytes is refused by both, in the same words", why is None and "refused" in py,
              f"python {tp:.1f} s, node {tj:.1f} s", why or py)


# ---------------------------------------------------------------- J3: QUICKSTART.md

def quickstart_cases():
    """[(name, case)]: the quickstart's store after each command block, run as quickstart_test.py runs it but with
    `warrant` this checkout's package."""
    import quickstart_test as QT
    steps = QT.parse((ROOT / "QUICKSTART.md").read_text())
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        work, snaps, bindir = tmp / "work", tmp / "snaps", tmp / "bin"
        for x in (work, snaps, bindir):
            x.mkdir()
        shim = bindir / "warrant"
        shim.write_text(f"#!/bin/sh\nPYTHONPATH={ROOT} exec {sys.executable} -m warrant \"$@\"\n")
        shim.chmod(0o755)
        script = "".join(f"{s['code']}\nmkdir -p {snaps}/{n} && cp -R store trust.json profile.json {snaps}/{n}/ 2>/dev/null || true\n"
                         for n, s in enumerate(steps))
        env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}")
        p = subprocess.run(["bash", "--noprofile", "--norc", "-eu", "-o", "pipefail", "-c", script], cwd=work, env=env,
                           capture_output=True, timeout=300, check=False)
        if p.returncode:
            raise RuntimeError(f"QUICKSTART.md did not run: {p.stderr.decode(errors='replace')[-500:]}")
        for n, s in enumerate(steps):
            d = snaps / str(n)
            if not (d / "trust.json").exists() or not (d / "profile.json").exists():
                continue
            rc = {"trust": json.loads((d / "trust.json").read_text()), "profile": json.loads((d / "profile.json").read_text())}
            out.append((f"after `{s['name']}`", store_case(d / "store", rc)))
    return out


# ---------------------------------------------------------------- J4: mutations

def records_of(case):
    out = []
    for raw in case["lines"]:
        try:
            env = C.loads(raw.rstrip(b"\n"))
            if not (isinstance(env, dict) and isinstance(env.get("record"), dict) and isinstance(env["record"].get("body"), dict)):
                continue
            out.append((R.rid(env["record"]), env, raw))
        except Exception:           # noqa: BLE001 - a line that is not a record has no id to mutate around
            continue
    return out


def signed_line(r, trust):
    """The canonical line of `r`, signed by a test key the trust binds to its actor (or its own key:<hex>), else null."""
    pubs = list(trust.get("keys", {}).get(r.get("actor"), [])) if isinstance(r.get("actor"), str) else []
    if r.get("kind") == "challenge" and isinstance(r.get("actor"), str) and r["actor"].startswith("key:"):
        pubs.append(r["actor"][4:])
    key = next((TEST_KEYS[p] for p in pubs if p in TEST_KEYS), None)
    try:
        return R.line(r, key)[1]
    except Exception:               # noqa: BLE001 - a mutated record the encoding refuses: write it unsigned by hand
        return C.canon({"record": r, "sig": None}) + b"\n"


STATES = ["open", "done", "released", "backed", "unbacked", "head", "met", "withdrawn", "reformulated", "retired", "decided", "nope"]
VERDICTS = ["accept", "reject", "reproduces", "does_not_reproduce", True, 1, None]


def mutate_record(r, ids, actors, rng):
    """One semantic change to a record (a copy), as a writer could sign it."""
    r = copy.deepcopy(r)
    body = r["body"]
    pick = rng.randrange(14)
    if pick == 0 and r["kind"] == "entity":
        body["state"] = rng.choice(STATES)
    elif pick == 1:
        g = r["guard"] or R.guard()
        g = dict(g, quorum=max(0, g["quorum"] + rng.choice([-1, 1, 2])))
        r["guard"] = None if r["kind"] in ("attest", "challenge") else g
    elif pick == 2 and r["kind"] == "entity":
        r["guard"] = rng.choice([None, R.guard(1, [rng.choice(["roadmap/acceptor", "claim/verifier", "pr/acceptor", "nobody"])],
                                               rng.choice([{"verdict": "accept"}, {}, {"verdict": None}]),
                                               rng.sample(ids, min(len(ids), rng.randrange(3))))])
    elif pick == 3:
        r["actor"] = rng.choice(actors)
    elif pick == 4:
        r["at"] = max(0, r["at"] + rng.choice([-1000, -1, 1, 1000]))
    elif pick == 5 and r["kind"] in ("entity", "schema"):
        r["lineage"] = rng.choice([None] + ids)
    elif pick == 6 and r["kind"] in ("attest", "challenge"):
        old, new = body["target"], rng.choice(ids)
        body["target"] = new
        r["refs"] = sorted((set(r["refs"]) - {old}) | {new})
    elif pick == 7 and r["kind"] == "attest":
        body["verdict"] = rng.choice(VERDICTS)
        if rng.random() < 0.5:
            body["on"] = rng.choice(ids)
            r["refs"] = sorted(set(r["refs"]) | {body["on"]})
    elif pick == 8:
        r["prev"] = rng.choice([None] + ids)
    elif pick == 9 and r["kind"] != "schema":
        r["schema"] = rng.choice([None, "claim@1", "goal@1", "obligation@1", "pr-head@1", "finding@1", "migration@1", "nope@1"])
        if r["kind"] == "entity" and r["schema"] is None:
            r["schema"] = "nope@1"
    elif pick == 10:
        if rng.random() < 0.5 or not r["refs"]:
            r["refs"] = sorted(set(r["refs"]) | {rng.choice(ids)})
        else:
            r["refs"] = sorted(set(r["refs"]) - {rng.choice(r["refs"])} | ({body["target"]} if "target" in body else set()))
    elif pick == 11:
        if body and rng.random() < 0.5:
            body.pop(rng.choice(sorted(body)))
        else:
            body[rng.choice(["zz", "reason", "answers", "pinned", "test"])] = rng.choice([1, "x", None, [], {"a": 1}])
    elif pick == 12 and r["kind"] == "schema":
        k = rng.choice(["closed", "successors", "states", "fields", "name", "pinned"])
        body[k] = rng.choice([[], {}, None, ["done"], {"done": ["roadmap/owner"]}, "x", [["done"]], {"state": "str"}])
    else:
        r["kind"] = rng.choice(["schema", "entity", "attest", "challenge"])
    return r


def mutations(case, rng, n):
    """[(what, case)]: n mutations of one case, each one change (sometimes two)."""
    recs = records_of(case)
    ids = [i for i, _, _ in recs] or ["00" * 32]
    actors = sorted(set(case["trust"].get("keys", {})) | {"eve", "zed", f"key:{K.Key.from_seed_hex('0a' * 32).public}"})
    out = []
    for _ in range(n):
        c = dict(case, lines=list(case["lines"]), blobs=dict(case["blobs"]), profile=copy.deepcopy(case["profile"]))
        what = []
        for _ in range(1 + (rng.random() < 0.25)):
            L = c["lines"]
            op = rng.choice(["drop", "dup", "shuffle", "flip", "cutsig", "zerosig", "nullsig", "bodybyte", "resign", "resign",
                             "resign", "add", "receiver", "as_of", "blob", "newline"])
            k = rng.randrange(len(L)) if L else None
            if op == "drop" and L:
                L.pop(k)
            elif op == "dup" and L:
                L.insert(rng.randrange(len(L) + 1), L[k])
            elif op == "shuffle":
                rng.shuffle(L)
            elif op == "flip" and L:
                b = bytearray(L[k])
                j = rng.randrange(len(b))
                b[j] = b[j] ^ (1 << rng.randrange(8))
                L[k] = bytes(b)
            elif op in ("cutsig", "zerosig", "nullsig", "bodybyte", "resign", "add") and recs:
                i, env, raw = rng.choice(recs)
                env = copy.deepcopy(env)
                pos = L.index(raw) if raw in L else None
                if op == "cutsig" and env["sig"]:
                    env["sig"]["ed25519"] = env["sig"]["ed25519"][:rng.choice([0, 64, 126])]
                    new = C.canon(env) + b"\n"
                elif op == "zerosig" and env["sig"]:
                    env["sig"]["ed25519"] = "00" * 64
                    new = C.canon(env) + b"\n"
                elif op == "nullsig":
                    env["sig"] = None
                    new = C.canon(env) + b"\n"
                elif op == "bodybyte":
                    strs = [k2 for k2, v in sorted(env["record"]["body"].items()) if isinstance(v, str) and v]
                    if strs:
                        k2 = rng.choice(strs)
                        v = env["record"]["body"][k2]
                        j = rng.randrange(len(v))
                        env["record"]["body"][k2] = v[:j] + ("x" if v[j] != "x" else "y") + v[j + 1:]
                    new = C.canon(env) + b"\n"
                else:
                    new = signed_line(mutate_record(env["record"], ids, actors, rng), c["trust"])
                if op != "add" and pos is not None and rng.random() < 0.8:
                    L[pos] = new
                else:
                    L.insert(rng.randrange(len(L) + 1), new)
            elif op == "receiver":
                roles = c["profile"].setdefault("roles", {})
                sub = rng.randrange(4)
                if sub == 0 and roles:
                    roles.pop(rng.choice(sorted(roles)))
                elif sub == 1:
                    role = rng.choice(sorted(roles) + ["challenger", "replayer", "migrator", "schema/author"])
                    roles[role] = sorted(set(roles.get(role, [])) | {rng.choice(actors)})
                elif sub == 2:
                    c["profile"]["quorum"] = {"schema/author": rng.choice([1, 2])}
                else:
                    c["profile"].pop("quorum", None)
            elif op == "as_of" and recs:
                c["as_of"] = rng.choice(recs)[1]["record"]["at"] + rng.choice([-1, 0])
            elif op == "blob" and c["blobs"]:
                h = rng.choice(sorted(c["blobs"]))
                if rng.random() < 0.5:
                    c["blobs"].pop(h)
                else:
                    c["blobs"][h] = c["blobs"][h][:-1] + b"]"
            elif op == "newline" and L:
                L[k] = L[k].rstrip(b"\n") + rng.choice([b"\r\n", b" \n", b"\n\n", b""])
            what.append(op)
        out.append(("+".join(what), c))
    return out


def mutation_cases(tally, sources, rng, n):
    for name, case in sources:
        named = [(f"{name} / {w} #{k}", c) for k, (w, c) in enumerate(mutations(case, rng, n))]
        run_cases(tally, "J4", named, quiet=True, label=f"{name}: mutations")


# ---------------------------------------------------------------- J5: handoff inspect alone

INSPECTOR = []
B64_PROBES = ["abc", "a!==", "====", "YQ==YQ==", "\u00e9", 1, None, [1], {}, True, "Y===", "YR==", " YQ==", "YQ==\n", "YQ=a", "Y=QQ",
              "YWJj=", "YWJjYQ===", "YWJjY", "=YQ", "YQ=", "YWE==", "YWE=a", "", "YQ==a!", "YQ==!a", "YQ===a", "Y=!Q", "YQ=!", "YQ=\n="]


def py_inspect(case):
    """warrant_agent's handoff {op: inspect, alone: true} under the case's receiver: a repository workspace whose
    .warrant/v3.json holds it."""
    from warrant_agent import api
    from warrant_agent.config import Config
    if not INSPECTOR:
        repo = Repo()
        INSPECTOR.append((repo, Config({"agent_api": "warrant-agent/3", "workspaces": {"w": {
            "repo": str(repo.root), "signer": {"actor": "bob", "key": str(repo.seed("bob"))}}}})))
    repo, cfg = INSPECTOR[0]
    repo.trust, repo.profile = case["trust"], case["profile"]
    repo.write_config()
    try:
        out = api.call(cfg, "handoff", {"workspace": "w", "op": "inspect", "package": case["package"], "alone": True})
    except Exception as e:          # noqa: BLE001
        return {"crash": f"Python {type(e).__name__}: {e}"}
    return out["ok"] if "ok" in out else {"error": out["error"], "message": out["message"]}


def package_of(case, rng):
    recs = records_of(case)
    rep = py_report(case)
    roots = sorted(rep.get("lineages", {}))[:2] + sorted(rep.get("challenges", {}))[:1] + [recs[len(recs) // 2][0] if recs else "00" * 32, "00" * 32]
    lines = []
    for raw in case["lines"]:
        try:
            lines.append(raw.rstrip(b"\n").decode())
        except UnicodeDecodeError:
            continue
    return {"package": {"warrant": "package/3", "roots": roots, "lines": lines,
                        "blobs": {h: base64.b64encode(b).decode() for h, b in sorted(case["blobs"].items())}},
            "trust": case["trust"], "profile": case["profile"]}


def package_cases(tally, worlds, rng):
    named = []
    for name, case in worlds:
        named.append((f"package of {name}", package_of(case, rng)))
        for w, m in mutations(case, rng, 2):
            named.append((f"package of {name} / {w}", package_of(m, rng)))
    # Blobs read by the package's own base64 rule (warrant/verify.py _BASE64), not binascii's: one answer on every interpreter.
    for b in B64_PROBES:
        named.append((f"a package blob {b!r}", dict(named[0][1], package={"warrant": "package/3", "roots": [], "lines": [], "blobs": {"ab" * 32: b}})))
    big = bytes(9 << 20)            # Codex F1 on #342 at 3efb118a: a valid 12-MiB base64 blob overflowed V8's regexp stack
    named.append(("a package blob of 9 MiB", dict(named[0][1], package={"warrant": "package/3", "roots": [], "lines": [],
                                                                    "blobs": {hashlib.sha256(big).hexdigest(): base64.b64encode(big).decode()}})))
    named.append(("blobs refused in the order read", dict(named[0][1], package={"warrant": "package/3", "roots": [], "lines": [],
                                                                               "blobs": {"9": "YQ=", "10": "=", "a": 1}})))
    bad = {"warrant": "package/3", "roots": ["00" * 32], "lines": [], "blobs": {"ab" * 32: "bm90IHRoZXNl"}}
    named.append(("a package whose blob is not named by its hash", dict(named[0][1], package=bad)))
    named.append(("a package that is not a package", dict(named[0][1], package={"warrant": "package/2"})))
    run_cases(tally, "J5", named, quiet=True, label="handoff inspect alone, packages of the J2 worlds and their mutations")
    # the command itself, once
    case = named[0][1]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "pkg.json").write_text(json.dumps(case["package"]))
        (Path(d) / "v3.json").write_text(json.dumps({"warrant": "repository/3", "repository": "x", "trust": case["trust"], "profile": case["profile"]}))
        p = subprocess.run([NODE, str(JS), "verify", str(Path(d) / "pkg.json"), "--config", str(Path(d) / "v3.json")],
                           capture_output=True, check=False, timeout=120)
    js = json.loads(p.stdout) if p.stdout.strip() else {"crash": p.stderr.decode(errors="replace")[-300:]}
    why = tally.add("J5", "verify command", case, py_inspect(case), js)
    check("J5 `warrant.mjs verify PACKAGE --config V3JSON` prints what handoff inspect alone answers", why is None, why)


# ---------------------------------------------------------------- J6: the encoding

J6_SCRIPT = r"""
import * as W from %s;
const fs = await import("node:fs");
const backend = await W.nodeBackend();
const inp = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const out = {canon: [], blob: [], sig: [], verify: [], edge: [], unicode: null};
const hex = (b) => Buffer.from(b).toString("hex");
for (const v of inp.canon) { const b = W.canon(W.loadsLenient(JSON.stringify(v))); out.canon.push([hex(b), backend.sha256(b)]); }
for (const v of inp.blob) out.blob.push(backend.sha256(Buffer.from(v, "base64")));
for (const v of inp.sig) out.sig.push(hex(Buffer.concat([Buffer.from("warrant-sig-v1:"), Buffer.from(v, "hex")])));
for (const [key, sig, id] of inp.verify) out.verify.push(await W.verifySig(backend, key, sig, Buffer.concat([Buffer.from("warrant-sig-v1:"), Buffer.from(id, "hex")])));
const h = (await import("node:crypto")).createHash("sha256");
const blocks = [];
for (let b = 0; b < 0x110000; b += 0x1000) {
  const parts = [];
  for (let c = b; c < b + 0x1000; c++) { const ch = String.fromCodePoint(c); parts.push(W.pyReprStr(ch) + (W.isActor(ch) ? "1" : "0") + (W.isActor("a" + ch + "a") ? "1" : "0") + (/^\p{Cn}$/u.test(ch) ? "n" : "")); }
  blocks.push(parts);
}
out.unicode = blocks;
out.unicode_version = process.versions.unicode;
process.stdout.write(JSON.stringify(out));
"""


def py_unicode_blocks():
    out = []
    for b in range(0, 0x110000, 0x1000):
        out.append([repr(chr(c)) + ("1" if SH.is_actor(chr(c)) else "0") + ("1" if SH.is_actor("a" + chr(c) + "a") else "0")
                    for c in range(b, b + 0x1000)])
    return out


def encoding_cases(tally, worlds):
    pack = ROOT / "third_party" / "primitives" / "vectors"
    canon = json.loads((pack / "canon.json").read_text())["vectors"]
    blob = json.loads((pack / "blob-hash.json").read_text())["vectors"]
    sig = json.loads((pack / "sig-message.json").read_text())["vectors"]
    ver = [v for v in json.loads((pack / "verify-sig.json").read_text())["vectors"] if v["input"].get("alg", "ed25519") == "ed25519"]
    edge = json.loads((ROOT / "tests" / "vectors" / "ed25519-edge.json").read_text())["vectors"]
    inp = {"canon": [v["input"]["body"] for v in canon], "blob": [v["input"]["bytes_base64"] for v in blob],
           "sig": [v["input"]["warrant_id"] for v in sig],
           "verify": [[v["input"]["key"], v["input"]["sig"], v["input"]["warrant_id"]] for v in ver] + [[v["key"], v["sig"], v["warrant_id"]] for v in edge]}
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "in.json"
        f.write_text(json.dumps(inp))
        p = subprocess.run([NODE, "--input-type=module", "-e", J6_SCRIPT % json.dumps(JS.as_uri()), str(f)], capture_output=True,
                           check=False, timeout=600)
    if p.returncode:
        check("J6 the encoding probe runs", False, p.stderr.decode(errors="replace")[-500:])
        return
    got = json.loads(p.stdout)
    bad = [v["id"] for v, g in zip(canon, got["canon"]) if any({"canon_hex": g[0], "warrant_id": g[1]}.get(k) != w for k, w in v["expect"].items())]
    check("J6 canon: the primitives pack's canonical bytes and ids", not bad, f"{len(canon)} vectors", bad)
    bad = [v["id"] for v, g in zip(blob, got["blob"]) if g != v["expect"]["hash"]]
    check("J6 blob-hash: the primitives pack's SHA-256", not bad, f"{len(blob)} vectors", bad)
    bad = [v["id"] for v, g in zip(sig, got["sig"]) if g != v["expect"]["message_hex"]]
    check("J6 sig-message: the bytes a key signs", not bad, f"{len(sig)} vectors", bad)
    want = [v["expect"]["valid"] for v in ver] + [v["valid"] for v in edge]
    bad = [n for n, (g, w) in enumerate(zip(got["verify"], want)) if g != w]
    check("J6 verify-sig and the five Ed25519 edge signatures (cofactorless, S < L, weak keys refused)", not bad,
          f"{len(ver)} + {len(edge)} vectors", bad)
    py = py_unicode_blocks()
    diff = [(b * 0x1000 + k, x, y) for b, (pb, jb) in enumerate(zip(py, got["unicode"])) for k, (x, y) in enumerate(zip(pb, jb))
            if x != y.rstrip("n")]
    same = tuple(map(int, unicodedata.unidata_version.split("."))) == tuple(map(int, (got["unicode_version"] + ".0.0").split(".")[:3]))
    # With one Unicode version both sides must agree everywhere; across versions, only where a code point is assigned
    # in one table and not the other (a new character's repr): the rest of the shapes still agree.
    unexplained = [d for d in diff if same or (unicodedata.category(chr(d[0])) == "Cn") == d[2].endswith("n")]
    check(f"J6 every code point: Python's repr, is_actor(c) and is_actor('a'+c+'a') against the platform's Unicode tables "
          f"(Python {unicodedata.unidata_version}, node {got['unicode_version']})", not unexplained,
          f"0x110000 code points, {len(diff)} differ only by a character one table has not assigned",
          [f"U+{c:04X} python {x} js {y}" for c, x, y in unexplained[:8]] + [f"{len(unexplained)} in all"])
    # the WebCrypto backend answers as node:crypto does, on the worlds with signatures that verify and do not
    sample = [c for _, c in worlds][:30]
    a, b = js_batch(sample), js_batch(sample, ["--webcrypto"])
    bad = [n for n, (x, y) in enumerate(zip(a, b)) if C.canon({k: v for k, v in x.items() if k not in IDENTITY})
           != C.canon({k: v for k, v in y.items() if k not in IDENTITY})]
    check("J6 the WebCrypto backend gives the reports node:crypto gives", not bad, f"{len(sample)} worlds", bad)


# ---------------------------------------------------------------- main

TIMINGS = []


VECTOR_CLASSES = ("J2", "J3", "J5")
VECTORS = ROOT / "impl-js" / "vectors"
VECTOR_FORMAT = "warrant-assess-vectors/1"


VECTOR_MAX = 1 << 20      # bytes of one vector case's JSON


def vector_bytes(tally):
    """(cases.jsonl.gz, manifest.json): the J2, J3 and J5 cases (no mutation) with this engine's answers. Deterministic: the
    test keys, the times and the order of the cases are fixed, and gzip carries no time."""
    small = [v for v in tally.vectors if len(json.dumps(v)) <= VECTOR_MAX]     # a case of thousands of records (T16) stays a live case
    data = "".join(json.dumps(v, separators=(",", ":")) + "\n" for v in small).encode()     # dict order kept: a package's blobs are read in it
    gz = gzip.compress(data, compresslevel=9, mtime=0)
    counts = {}
    for v in small:
        counts[v["class"]] = counts.get(v["class"], 0) + 1
    manifest = {"format": VECTOR_FORMAT, "cases": "cases.jsonl.gz", "sha256": hashlib.sha256(gz).hexdigest(), "bytes": len(data),
                "counts": counts, "reference": "warrant/ (this commit's engine)",
                "generator": "python3 tests/impl_js_test.py --vectors impl-js/vectors",
                "reader": "node impl-js/check_vectors.mjs [impl-js/vectors]",
                "rule": ("Each gzipped line is {class, name, case, expect}. A case {lines: [base64 line bytes, newline included], "
                         "blobs: {name: base64}, trust, profile, as_of} is assess(snapshot of the lines and blobs, trust, profile, "
                         "as_of) (docs/V3.md §10); a case {package, trust, profile} is handoff inspect alone (§13). expect is the "
                         "answer of the Python reference: a report, {refused: why}, a handoff result or {error, message}, with the "
                         "engine's identity left out (assessment, code; adapter). An implementation agrees when every member of "
                         "its answer but those is canonically equal to expect's (RFC 8785, docs/V3.md §1) and its own assessment "
                         "is the SHA-256 of canon({snapshot, trust, profile, as_of, code}) with its own code."),
                "excluded": ("J1 (the repository's store: run the test), J4 (seeded mutations: generated by the test, --seed), "
                             "J6 (third_party/primitives and tests/vectors already carry them), J7 (the reference crashes there)")}
    return gz, (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()


def write_vectors(tally, out):
    gz, manifest = vector_bytes(tally)
    out.mkdir(parents=True, exist_ok=True)
    (out / "cases.jsonl.gz").write_bytes(gz)
    (out / "manifest.json").write_bytes(manifest)
    return len(gz)


def vectors_current(tally):
    """J8: the committed vectors are what this engine answers now, case for case, and the reader in impl-js reads them.
    The cases are compared unzipped: gzip's bytes are zlib's, which differ between builds of one Python (3.11 on CI,
    3.15 here gave one content and two archives); the committed manifest must name the committed archive's SHA-256."""
    gz, manifest = vector_bytes(tally)
    have = (VECTORS / "cases.jsonl.gz").read_bytes() if (VECTORS / "cases.jsonl.gz").exists() else b""
    m_have = json.loads((VECTORS / "manifest.json").read_text()) if (VECTORS / "manifest.json").exists() else {}
    m_want = json.loads(manifest)
    try:
        same = gzip.decompress(have) == gzip.decompress(gz)
    except (OSError, EOFError):
        same = False
    check("J8 impl-js/vectors is what the reference answers now (regenerate: --vectors impl-js/vectors)",
          same and m_have.get("sha256") == hashlib.sha256(have).hexdigest()
          and {k: v for k, v in m_have.items() if k != "sha256"} == {k: v for k, v in m_want.items() if k != "sha256"},
          f"{len(tally.vectors)} cases, {len(gz)} bytes gzipped", "impl-js/vectors differs from the cases this run made")
    p = subprocess.run([NODE, str(ROOT / "impl-js" / "check_vectors.mjs"), str(VECTORS)], capture_output=True, text=True, check=False, timeout=600)
    check("J8 node impl-js/check_vectors.mjs agrees with every vector, with no Python", p.returncode == 0,
          p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "", p.stdout[-600:] + p.stderr[-600:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--mutations", type=int, default=8, help="mutations per source case")
    ap.add_argument("--vectors", help="also write the cases and Python's answers here")
    ap.add_argument("--quick", action="store_true", help="leave out the mutations of the repository's store")
    ap.add_argument("--limits", action="store_true", help="also the stores at LIMITS records + 1 and bytes + 1 (heavy)")
    a = ap.parse_args()
    if NODE is None:
        print("SKIP impl_js_test: no `node` on PATH; the JavaScript implementation is not checked")
        return 0
    rng = random.Random(a.seed)
    tally = Tally()
    repo = repo_cases(tally, a)
    second_client_cases()
    browser_reader_cases()
    browser_pins_cases()
    browser_others_cases()
    if a.limits:
        limit_cases(tally)
    worlds = capture_core_worlds()
    check("J2 tests/core_test.py's worlds were captured", len(worlds) > 50, f"{len(worlds)} assessments")
    t = time.perf_counter()
    run_cases(tally, "J2", worlds)
    TIMINGS.append((f"{len(worlds)} core worlds, both engines", time.perf_counter() - t, None))
    run_cases(tally, "J2", line_cases() + receiver_cases() + boundary_cases() + exotic_actor_cases() + spec_gap_cases())
    found = departure_cases()
    # Two crashes of the reference the port found are fixed in the engine (S12, M6): both engines now agree there.
    # The three crashes of the reference the port found are fixed (S12 and M6 in the engine, the lone surrogate in
    # warrant/verify.py's package reader): both engines agree there now, and no departure is declared.
    run_cases(tally, "J2", [(f"formerly a departure: {n}", c) for n, c, p, _ in found if p != "Python UnicodeEncodeError"])
    run_cases(tally, "J5", [(f"formerly a departure: {n}", c) for n, c, p, _ in found if p == "Python UnicodeEncodeError"])
    DEPARTURES[:] = []
    for name, case, prefix, because in DEPARTURES:
        py, js = py_answer(case), js_batch([case])[0]
        ok = "crash" in py and py["crash"].startswith(prefix + ":") and "crash" not in js
        check(f"J7 declared departure: {name}", ok, f"python {str(py)[:200]} | js {str(js)[:200]}")
        print(f"     the reference: {py.get('crash', '')[:160]}\n     the port: {canon_short(js)}\n     because {because}")
    quick = quickstart_cases()
    run_cases(tally, "J3", quick)
    mutation_cases(tally, worlds + quick, rng, a.mutations)
    if not a.quick:
        run_cases(tally, "J4", [(f"repository store / {w} #{k}", c) for k, (w, c) in enumerate(mutations(repo, rng, 24))],
                  quiet=True, label="repository store: 24 mutations")
    package_cases(tally, worlds, rng)
    encoding_cases(tally, worlds)
    for cls, (n, ok) in sorted(tally.classes.items()):
        print(f"     {cls}: {n} cases, {ok} agree")
    print("     exercised (answers of the reference, all classes): " + "; ".join(f"{k} {n}" for k, n in sorted(tally.seen.items())))
    for cls, name, dep in getattr(tally, "departed", []):
        print(f"     {cls} {name}: the declared departure {dep!r}")
    for cls, name, why in tally.disagreements[:MAX_FAIL_LINES]:
        print(f"     DISAGREE {cls} {name}: {why[:400]}")
    for what, tp, tj in TIMINGS:
        print(f"     time {what}: python {tp:.2f} s" + (f", node {tj:.2f} s" if tj is not None else ""))
    if a.vectors:
        size = write_vectors(tally, Path(a.vectors))
        print(f"     vectors: {len(tally.vectors)} cases, {size} bytes gzipped, written to {a.vectors}")
    vectors_current(tally)
    return finish("impl_js_test")


READ = ROOT / "impl-js" / "read.mjs"


def _serve(directory):
    """A local HTTP server for `directory` (the second client's resolver); (server, base URL)."""
    import functools
    import http.server
    import threading
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def second_client_cases():
    """The second client (impl-js/read.mjs): the repository's records fetched through another resolver (HTTP) and
    assessed by the second implementation give the same report, byte for byte, as the store read from disk; a transport
    that alters a blob is refused, one that alters a record line has it rejected (Codex's second client, OBS-P12)."""
    srv, base = _serve(ROOT)
    try:
        p = subprocess.run([NODE, str(READ), "--base", base], capture_output=True, check=False, timeout=600)
        q = subprocess.run([NODE, str(JS), "assess", "--store", str(ROOT / ".warrant"), "--config", str(ROOT / ".warrant" / "v3.json")],
                           capture_output=True, check=False, timeout=600)
        s = subprocess.run([NODE, str(READ), "--base", base, "--summary"], capture_output=True, check=False, timeout=600)
    finally:
        srv.shutdown()
    doc = json.loads((ROOT / ".warrant" / "v3.json").read_text())
    py = E.assess(ST.Store(ROOT / ".warrant").snapshot(), doc["trust"], doc["profile"], None)
    summary = json.loads(s.stdout) if s.stdout.strip() else {}
    check("J9 the repository read over HTTP by the second client: its report is byte-identical to the store read from "
          "disk, and its root and every lineage's state and reliance are the Python engine's",
          p.returncode == 0 and p.stdout == q.stdout and summary.get("root") == py["snapshot"]
          and summary.get("lineages") == {L: [x["state"], x["reliance"]] for L, x in py["lineages"].items()},
          (p.returncode, p.stderr[-300:], len(p.stdout), len(q.stdout)))
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        (repo / ".warrant").mkdir(parents=True)
        shutil.copy(ROOT / ".warrant" / "v3.json", repo / ".warrant" / "v3.json")
        lines = ST.Store(ROOT / ".warrant").lines()
        blob_dir = ROOT / ".warrant" / "blobs"
        cited = next((b.name for b in sorted(blob_dir.iterdir()) if any(b.name.encode() in l for l in lines)), None) if blob_dir.is_dir() else None
        (repo / ".warrant" / "blobs").mkdir()
        if cited:
            (repo / ".warrant" / "blobs" / cited).write_bytes(b"altered on the way")
        (repo / ".warrant" / "records.jsonl").write_bytes(b"".join(lines))
        srv, base2 = _serve(repo)
        try:
            altered_blob = subprocess.run([NODE, str(READ), "--base", base2, "--summary"], capture_output=True, check=False, timeout=600)
            if cited:
                (repo / ".warrant" / "blobs" / cited).unlink()
            tampered = list(lines)
            tampered[0] = tampered[0].replace(b'"at":', b'"at":1', 1) if b'"at":' in tampered[0] else tampered[0]
            (repo / ".warrant" / "records.jsonl").write_bytes(b"".join(tampered))
            altered_line = subprocess.run([NODE, str(READ), "--base", base2, "--summary"], capture_output=True, check=False, timeout=600)
        finally:
            srv.shutdown()
    refused = json.loads(altered_blob.stdout or b"{}")
    rejected = json.loads(altered_line.stdout or b"{}")
    check("J9 a transport that alters a blob is refused (its bytes do not hash to its name); one that alters a record line "
          "has that line rejected by its signature", cited is not None and "transport altered blob" in refused.get("refused", "")
          and rejected.get("rejected", 0) >= 1, (cited, refused, rejected.get("rejected")))


READER = ROOT / "site" / "reader.mjs"
PAGE_FILES = [ROOT / "site" / "reader.html", ROOT / "site" / "reader-page.mjs", ROOT / "site" / "reader.mjs"]
MARKUP_FROM_TEXT = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "DOMParser", "srcdoc", "eval(",
                    "new Function", "setAttribute(\"on", "javascript:")


def _reader(base, *args):
    """(exit status, the reader's JSON answer) of `node site/reader.mjs --base BASE ...`."""
    p = subprocess.run([NODE, str(READER), "--base", base, *args], capture_output=True, check=False, timeout=600)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, {"crash": p.stderr.decode(errors="replace")[-300:]}


def _serve_failing(directory, failing):
    """As _serve, but a path ending in `failing` answers 500: a transport that failed, not a file that is absent."""
    import functools
    import http.server
    import threading
    class Failing(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            if self.path.endswith(failing):
                self.send_error(500)
            else:
                super().do_GET()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Failing, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def browser_reader_cases():
    """The reader in a browser (site/reader.mjs, drawn by site/reader-page.mjs): what the page shows of a store is held
    to the Python engine here, through node, by the functions the page runs. J10 is about the data the page draws and
    about its source text; no case here drives a browser."""
    import re
    from warrant import claims as CL
    link = ROOT / "site" / "warrant.mjs"
    check("J10 the page runs the engine the vectors hold: site/warrant.mjs is a link to impl-js/warrant.mjs, not a copy",
          link.is_symlink() and os.readlink(link) == "../impl-js/warrant.mjs", link)

    doc = json.loads((ROOT / ".warrant" / "v3.json").read_text())
    view = E.View(ST.Store(ROOT / ".warrant").snapshot(), doc["trust"], doc["profile"], None)
    py = view.report()
    speaks = {r["body"]["target"] for r in view.recs.values() if r["kind"] == "attest" and ("files" in r["body"] or "commit" in r["body"])}
    want = {L: ("PINS_NOT_CHECKED" if x["reliance"] == "ELIGIBLE" and x["effective"] in speaks else x["reliance"])
            for L, x in py["lineages"].items()}
    by_state = {}
    for x in py["lineages"].values():
        by_state.setdefault(x["schema"], {}).setdefault(x["state"] or "none", 0)
        by_state[x["schema"]][x["state"] or "none"] += 1
    srv, base = _serve(ROOT)
    try:
        rc, quick = _reader(base)
        rc_full, full = _reader(base, "--full")
    finally:
        srv.shutdown()
    rows = {x["id"]: x for x in quick.get("rows", [])}
    summ = quick.get("summary", {})
    check("J10 the repository read by the browser's reader: every lineage's state is the Python engine's, its reliance the "
          "engine's except PINS_NOT_CHECKED where an attest on its effective version names files or a commit, and the "
          "counts by schema and state are the engine's",
          rc == 0 and {L: x["state"] for L, x in rows.items()} == {L: x["state"] for L, x in py["lineages"].items()}
          and {L: x["reliance"] for L, x in rows.items()} == want and summ.get("lineages") == by_state
          and summ.get("records") == len(view.snap.lines) and summ.get("rejected") == len(py["rejected"]),
          (rc, quick.get("refused") or quick.get("crash"), len(rows), len(py["lineages"])))
    py["_recs"], py["_basis"] = view.recs, view.basis
    gated = {L for L in CL.live(py) if CL.acceptances(py).get(py["lineages"][L]["effective"])}
    check("J10 no lineage the freshness gate can read STALE (a live claim whose effective version the claims checker "
          "accepted, warrant.drift) reads ELIGIBLE in the browser's reader, which compares no checkout",
          rc == 0 and len(gated) > 0 and all(rows.get(L, {}).get("reliance") != "ELIGIBLE" for L in gated),
          (len(gated), sorted(L[:12] for L in gated if rows.get(L, {}).get("reliance") == "ELIGIBLE")[:5]))
    check("J10 a quick read (the migration maps alone) names no root; a full read (every blob a record names that is no "
          "record's id, each checked against its name) gives the store's root, the Python snapshot digest",
          summ.get("root") is None and summ.get("blobs", {}).get("mode") == "quick"
          and rc_full == 0 and full.get("summary", {}).get("root") == py["snapshot"],
          (summ.get("root"), full.get("summary", {}).get("root"), full.get("refused")))

    hostile = "<img src=x onerror=alert(1)><script>alert(2)</script> \u202e&amp;"
    r = Repo()
    goal = r.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "a goal"})
    plain = r.entity("alice", "obligation@1", {"state": "open", "statement": hostile, "serves": [goal]})
    done = r.entity("alice", "obligation@1", {"state": "done", "statement": hostile, "serves": [goal]}, lineage=plain)
    r.attest("bob", done)
    pinned = r.entity("alice", "obligation@1", {"state": "open", "statement": "accepted on files", "serves": [goal]})
    pinned_done = r.entity("alice", "obligation@1", {"state": "done", "statement": "accepted on files", "serves": [goal]}, lineage=pinned)
    r.attest("bob", pinned_done, commit="c" * 40, files={"a.py": "0" * 40})
    at_commit = r.entity("alice", "obligation@1", {"state": "open", "statement": "accepted at a commit", "serves": [goal]})
    at_commit_done = r.entity("alice", "obligation@1", {"state": "done", "statement": "accepted at a commit", "serves": [goal]}, lineage=at_commit)
    r.attest("bob", at_commit_done, commit="c" * 40)
    stranger = dict(json.loads((r.dot / "v3.json").read_text()))
    stranger["profile"] = dict(stranger["profile"], roles=dict(stranger["profile"]["roles"], **{"roadmap/acceptor": ["carol"]}))
    mine = r.home / "mine.json"
    mine.write_text(json.dumps(stranger))
    srv, base = _serve(r.root)
    try:
        _, theirs = _reader(base)
        _, opened = _reader(base, "--lineage", plain)
        _, own = _reader(base, "--config", str(mine))
    finally:
        srv.shutdown()
    t = {x["id"]: x for x in theirs.get("rows", [])}
    o = {x["id"]: x for x in own.get("rows", [])}
    lin = opened.get("lineage") or {}
    check("J10 what a record says reaches the page's data unchanged, as text: a statement holding markup, a script and a "
          "direction override is the same string in the list and in the opened lineage",
          t.get(plain, {}).get("title") == hostile and [v.get("title") for v in lin.get("versions", [])] == [hostile, hostile],
          (t.get(plain), lin.get("versions")))
    check("J10 an acceptance that names files, or a commit alone: the lineage reads PINS_NOT_CHECKED, never ELIGIBLE; one "
          "that names neither reads ELIGIBLE",
          t.get(pinned, {}).get("reliance") == "PINS_NOT_CHECKED" and t.get(at_commit, {}).get("reliance") == "PINS_NOT_CHECKED"
          and t.get(plain, {}).get("reliance") == "ELIGIBLE"
          and theirs.get("summary", {}).get("reliance") == {"ELIGIBLE": 2, "PINS_NOT_CHECKED": 2}, theirs.get("summary", {}).get("reliance"))
    check("J10 the reader's own rules decide: under the publisher's profile the closure is accepted (state done, rules "
          "publisher); under a profile where its acceptor holds no role the same bytes read state open (rules reader)",
          t.get(plain, {}).get("state") == "done" and theirs.get("summary", {}).get("rules") == "publisher"
          and o.get(plain, {}).get("state") == "open" and own.get("summary", {}).get("rules") == "reader",
          (t.get(plain, {}).get("state"), o.get(plain, {}).get("state"), own.get("summary", {}).get("rules"), own.get("refused")))

    srv, base = _serve_failing(r.root, "records.jsonl")
    try:
        rc_500, failed = _reader(base)
    finally:
        srv.shutdown()
    (r.dot / "v3.json").unlink()
    srv, base = _serve(r.root)
    try:
        rc_none, absent = _reader(base)
    finally:
        srv.shutdown()
    check("J10 a transport that fails is a refusal, never an empty store: records answered with HTTP 500 refuse the read, "
          "and so does a root with no .warrant/v3.json",
          rc_500 == 2 and "HTTP 500" in failed.get("refused", "") and rc_none == 2 and "no .warrant/v3.json" in absent.get("refused", ""),
          (rc_500, failed, rc_none, absent))

    maps = sorted({x["body"]["target"] for x in view.recs.values() if x["kind"] == "attest" and x["schema"] == R.MIGRATION})
    with tempfile.TemporaryDirectory() as d:
        copy_root = Path(d) / "repo"
        (copy_root / ".warrant" / "blobs").mkdir(parents=True)
        shutil.copy(ROOT / ".warrant" / "v3.json", copy_root / ".warrant" / "v3.json")
        shutil.copy(ROOT / ".warrant" / "records.jsonl", copy_root / ".warrant" / "records.jsonl")
        for m in maps:
            (copy_root / ".warrant" / "blobs" / m).write_bytes(b"altered on the way")
        srv, base = _serve(copy_root)
        try:
            rc_blob, altered = _reader(base)
        finally:
            srv.shutdown()
    check("J10 a transport that alters a blob the quick read asks for (a migration's map) refuses the read: its bytes do "
          "not hash to its name", len(maps) > 0 and rc_blob == 2 and "transport altered blob" in altered.get("refused", ""),
          (maps, rc_blob, altered))

    texts = {p.name: p.read_text() for p in PAGE_FILES}
    html = texts["reader.html"]
    found = sorted((name, word) for name, text in texts.items() for word in MARKUP_FROM_TEXT if word in text)
    check("J10 the page's source: no call that builds markup from a string in its three files, one script element and "
          "that one external, no inline handler, and a policy allowing scripts of its own origin only",
          not found and html.count("<script") == 1 and '<script type="module" src="reader-page.mjs"></script>' in html
          and re.search(r"<[^>]*\son[a-z]+\s*=", html, re.I) is None
          and "script-src 'self'" in html and "default-src 'none'" in html and "'unsafe-inline'" not in html
          and "'unsafe-eval'" not in html, found)


def _serve_counting(directory, failing=None):
    """As _serve_failing (`failing`: a path ending answering 500, or None), and {request path: times asked}."""
    import collections
    import functools
    import http.server
    import threading
    asked = collections.Counter()
    class Counting(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            asked[self.path] += 1
            if failing and self.path.endswith(failing):
                self.send_error(500)
            else:
                super().do_GET()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Counting, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/", asked


def _read_served(root, *args, failing=None):
    """(the reader's rows {lineage: reliance}, its summary, {path: times asked}) of `root` served over HTTP."""
    srv, base, asked = _serve_counting(root, failing)
    try:
        _, out = _reader(base, *args)
    finally:
        srv.shutdown()
    return {x["id"]: x["reliance"] for x in out.get("rows", [])}, out.get("summary", out), asked


def _lineage_served(root, L, *args):
    srv, base, _ = _serve_counting(root)
    try:
        _, out = _reader(base, "--lineage", L, *args)
    finally:
        srv.shutdown()
    return (out.get("lineage") or {}).get("floor", {})


def _gate(root):
    """({lineage: reliance} after the Python freshness gate at HEAD, {lineage: drift verdict}) of a checkout."""
    from warrant import drift as D
    from warrant import repo as RP
    rep = RP.Repo(root).report()
    d = D.gate(rep, root)
    return {L: x["reliance"] for L, x in rep["lineages"].items()}, {L: x["verdict"] for L, x in d.items()}


def browser_pins_cases():
    """The reader's opt-in comparison of pins with the tree at its address (site/reader.mjs comparePins), held to the
    Python freshness gate (warrant.drift.gate) on real claims repositories, built as tools_test builds them (claims
    accepted by the claims checker's replay), served over HTTP from a clean checkout at HEAD."""
    import contextlib
    import io
    import tools_test as TT
    from warrant import claims as CL
    from warrant import records as RR
    from world import KEYS
    from world import git as wgit
    quiet = contextlib.redirect_stdout(io.StringIO())

    # (a) differential, and (f) the option off: two claims stale after a helper both witnesses import changed, one fresh
    with quiet:
        r, Ls = TT.shared_repo()
    (r.root / "tests" / "helper.py").write_text("ONE = 1  # the shared helper changes\n")
    r.commit("the helper both witnesses import changes")
    py, drift = _gate(r.root)
    js, summ, asked = _read_served(r.root, "--pins")
    paths = {p for x in _acceptance_files(r.root) for p in x}
    tree_asked = {p: n for p, n in asked.items() if not p.startswith("/.warrant/")}
    check("J11 the reader with --pins gives every lineage the freshness gate covers exactly the gate's reliance at HEAD, "
          "where some claims read STALE (a file they ran changed) and one ELIGIBLE, and every other lineage the engine's",
          drift and js == py and {py[L] for L in drift} == {"STALE", "ELIGIBLE"} and [py[Ls[k]] for k in "qps"] == ["STALE", "STALE", "ELIGIBLE"],
          ({L[:12]: (py.get(L), js.get(L)) for L in drift}, summ.get("refused") or summ.get("crash")))
    check("J11 each file an acceptance names is fetched once, however many acceptances name it, and the summary counts what "
          "was fetched and compared",
          tree_asked == {"/" + p: 1 for p in paths} and summ.get("pins", {}).get("files") == {"asked": len(paths), "fetched": len(paths), "absent": 0, "refused": 0}
          and summ.get("pins", {}).get("compared", 0) >= len(paths) and summ.get("pins", {}).get("claims") == len(drift),
          (tree_asked, sorted(paths), summ.get("pins")))
    off, summ_off, asked_off = _read_served(r.root)
    check("J11 without --pins nothing is compared: each gated claim reads PINS_NOT_CHECKED as before, no file of the tree "
          "is fetched and the summary has no pins member",
          all(off.get(L) == "PINS_NOT_CHECKED" for L in drift) and "pins" not in summ_off
          and not [p for p in asked_off if not p.startswith("/.warrant/")], (off, sorted(asked_off)))

    # (e) a transport that fails answers nothing: neither fresh nor stale, unless another file already decides
    with quiet:
        r, Ls = TT.shared_repo()
    py, _ = _gate(r.root)
    js, summ, _ = _read_served(r.root, "--pins", failing="helper.py")
    check("J11 a file answered with HTTP 500 is not fetched, not absent: the claims that name it read PINS_NOT_CHECKED, "
          "neither ELIGIBLE nor STALE, the gate's ELIGIBLE for the claim that does not name it, and the failure is named",
          [py[Ls[k]] for k in "qps"] == ["ELIGIBLE"] * 3 and [js.get(Ls[k]) for k in "qps"] == ["PINS_NOT_CHECKED", "PINS_NOT_CHECKED", "ELIGIBLE"]
          and summ.get("pins", {}).get("files", {}).get("refused") == 1 and any("HTTP 500" in x for x in summ.get("pins", {}).get("refused", [])),
          ([js.get(Ls[k]) for k in "qps"], summ.get("pins")))
    (r.root / "mutated.py").write_text("X = 9\n")
    r.commit("the file both mutants mutate changes")
    py, _ = _gate(r.root)
    js, _, _ = _read_served(r.root, "--pins", failing="helper.py")
    check("J11 a file another acceptance names changed decides it though one of its files was not fetched: STALE, as the gate",
          [py[Ls[k]] for k in "qp"] == ["STALE"] * 2 and [js.get(Ls[k]) for k in "qp"] == ["STALE"] * 2, ([py[Ls[k]] for k in "qp"], [js.get(Ls[k]) for k in "qp"]))
    js_cfg, summ_cfg, _ = _read_served(r.root, "--pins", failing="claims.json")
    (r.root / ".warrant" / "claims.json").unlink()
    py_none, drift_none = _gate(r.root)
    js_none, summ_none, _ = _read_served(r.root, "--pins")
    check("J11 .warrant/claims.json answered with HTTP 500 compares nothing (the claims read PINS_NOT_CHECKED, the failure "
          "named); absent, the gate covers nothing (ELIGIBLE there) and the reader, which cannot tell what else compares "
          "pins, keeps PINS_NOT_CHECKED",
          all(js_cfg.get(Ls[k]) == "PINS_NOT_CHECKED" for k in "qps") and summ_cfg.get("pins", {}).get("config") == "refused"
          and drift_none == {} and all(py_none[Ls[k]] == "ELIGIBLE" for k in "qps")
          and all(js_none.get(Ls[k]) == "PINS_NOT_CHECKED" for k in "qps") and summ_none.get("pins", {}).get("config") == "absent",
          (js_cfg, summ_cfg.get("pins"), drift_none, js_none, summ_none.get("pins")))

    # (b) a file changed after acceptance
    with quiet:
        r, L = TT.drift_repo()
    (r.root / "lib" / "code.py").write_text("X = 2\n")
    r.commit("the mutated file changes")
    py, drift = _gate(r.root)
    js, _, _ = _read_served(r.root, "--pins")
    floor = _lineage_served(r.root, L, "--pins")
    rows = [f for a in (floor.get("pins") or {}).get("acceptances", []) for f in a["files"]]
    check("J11 a file changed after the acceptance: STALE in the reader as in the gate, and the opened lineage names the "
          "file CHANGED", drift.get(L) == "CHANGED" and py[L] == "STALE" and js.get(L) == "STALE" and floor.get("reliance") == "STALE"
          and {"path": "lib/code.py", "verdict": "CHANGED", "detail": "other bytes at this path"} in rows, (py.get(L), js.get(L), rows))

    # (d) a file moved with its bytes: the documented difference, STALE here where the gate says ELIGIBLE
    with quiet:
        r, L = TT.drift_repo()
    wgit(r.root, "mv", "lib/code.py", "lib/moved.py")
    (r.root / "tests" / "mutants.py").write_text(TT.HARNESS.replace("warrant/engine.py", "lib/moved.py"))
    r.commit("the mutated file moves, its bytes unchanged")
    py, drift = _gate(r.root)
    js, _, _ = _read_served(r.root, "--pins")
    floor = _lineage_served(r.root, L, "--pins")
    rows = [f for a in (floor.get("pins") or {}).get("acceptances", []) for f in a["files"]]
    check("J11 a file moved with its bytes unchanged: the gate reads it fresh (it lists the tree) and says ELIGIBLE; the "
          "reader, which cannot list a tree over HTTP, finds nothing at the path and says STALE (the documented difference, "
          "in this direction only)", drift.get(L) == "UNCHANGED" and py[L] == "ELIGIBLE" and js.get(L) == "STALE"
          and any(f["path"] == "lib/code.py" and f["verdict"] == "ABSENT" for f in rows), (py.get(L), js.get(L), rows))

    # (c) which acceptances count: the closure rule, any of them, readable files, the checker's signed accept only;
    # and a symlink's entry
    with quiet:
        r, L = TT.drift_repo()
    rep = _report(r.root)
    eff = rep["lineages"][L]["effective"]
    body = next(x["body"] for x in rep["_recs"].values() if x["kind"] == "attest" and x["actor"] == CL.CHECKER and x["body"]["target"] == eff)
    bare = {k: v for k, v in body.items() if k != "closure"}
    TT.put_as(r, CL.CHECKER, {**bare, "target": eff}, [eff])               # a second acceptance of L, with no closure rule
    L2 = TT.claim(r, id="V3-3-2")
    TT.put_as(r, CL.CHECKER, {**bare, "target": L2}, [L2])
    L3 = TT.claim(r, id="V3-3-3")
    TT.put_as(r, CL.CHECKER, {**body, "target": L3, "files": {}}, [L3])
    L5 = TT.claim(r, id="V3-3-5")
    TT.put_as(r, CL.CHECKER, {**body, "target": L5, "files": {p: "0" * 40 for p in body["files"]}}, [L5])
    r.t += 1                                                               # the checker's name, another's key: rejected
    r.store.append(RR.record("attest", CL.CHECKER, r.t, {**body, "target": L5}, refs=[L5]), KEYS["alice"], r.trust)
    r.attest("carol", L5, **{k: v for k, v in body.items() if k not in ("verdict", "target")})   # a verifier, not the checker
    TT.put_as(r, CL.CHECKER, {**body, "target": L5, "verdict": "reject"}, [L5])                  # the checker, not accepting
    os.symlink("code.py", r.root / "lib" / "alias.py")
    r.commit("a symlink")
    link = wgit(r.root, "rev-parse", "HEAD:lib/alias.py")
    L4 = TT.claim(r, id="V3-3-4")
    TT.put_as(r, CL.CHECKER, {**body, "target": L4, "files": {"lib/alias.py": "link:" + link}}, [L4])
    L6 = TT.claim(r, id="V3-3-6")
    TT.put_as(r, CL.CHECKER, {**body, "target": L6}, [L6])
    r.put("carol", "challenge", {"target": L6, "statement": "a counterexample"}, refs=[L6])   # a verifier: counted
    r.commit("acceptances of every shape")
    py, drift = _gate(r.root)
    js, _, _ = _read_served(r.root, "--pins")
    want = {L: "ELIGIBLE", L2: "STALE", L3: "STALE", L4: "ELIGIBLE", L5: "STALE"}
    check("J11 an acceptance without the import-closure rule is not fresh, whatever its files: its claim reads STALE in "
          "the reader as in the gate; a claim with one such acceptance and one fresh is ELIGIBLE (any acceptance decides)",
          {x: py.get(x) for x in want} == want and js.get(L2) == "STALE" and js.get(L) == "ELIGIBLE" and drift.get(L2) == "UNKNOWN",
          ({x[:12]: (py.get(x), js.get(x)) for x in want}, drift))
    check("J11 an acceptance naming no files compares nothing: STALE in the reader as in the gate", js.get(L3) == "STALE" == py.get(L3), (py.get(L3), js.get(L3)))
    check("J11 only the claims checker's signed acceptances count: a stale claim stays STALE beside fresh files named by a "
          "line under the checker's name that fails its signature, by a verifier who is not the checker, and by the "
          "checker's attest that does not accept", js.get(L5) == "STALE" == py.get(L5) and drift.get(L5) == "CHANGED", (py.get(L5), js.get(L5)))
    check("J11 a symlink's entry (link:<blob>): the gate reads the tree's link and says ELIGIBLE; HTTP serves no link as a "
          "link, so the reader says STALE (the documented difference, in this direction only)",
          py.get(L4) == "ELIGIBLE" and drift.get(L4) == "UNCHANGED" and js.get(L4) == "STALE", (py.get(L4), js.get(L4)))
    check("J11 the comparison only ever lowers ELIGIBLE, as the gate does: a fresh claim the engine does not read ELIGIBLE "
          "(a challenge stands against it) keeps the engine's reliance", drift.get(L6) == "UNCHANGED"
          and py.get(L6) not in ("ELIGIBLE", "STALE") and js.get(L6) == py.get(L6), (py.get(L6), js.get(L6)))


def _serve_many(*roots):
    """Each root served by its own local HTTP server: ([servers], [base URLs])."""
    pairs = [_serve(x) for x in roots]
    return [a for a, _ in pairs], [b for _, b in pairs]


def _overlay_py(roots, names, reader_trust, reader_profile):
    """warrant_agent.overlay on the same stores (`roots`, named `names`, the first the main one): ({lineage: [(state,
    reliance) in the main store under its own rules, under the reader's over the union]} of the lineages that differ,
    the receiver's held bindings as [(actor, why)], (snaps, trust, profile) for the identity)."""
    from warrant_agent import overlay as OV
    snaps = {n: ST.Store(Path(x) / ".warrant").snapshot() for n, x in zip(names, roots)}
    docs = {n: json.loads((Path(x) / ".warrant" / "v3.json").read_text()) for n, x in zip(names, roots)}
    t, p, held = OV.receiver(reader_trust, reader_profile, {n: d["trust"] for n, d in docs.items()})
    over = OV.assess(snaps, t, p)
    own = OV.assess({names[0]: snaps[names[0]]}, docs[names[0]]["trust"], docs[names[0]]["profile"])
    rows = {}
    for L, a in own["lineages"].items():
        b = over["lineages"].get(L)
        if b is None or (a["state"], a["reliance"]) != (b["state"], b["reliance"]):
            rows[L] = [[a["state"], a["reliance"]], [b["state"], b["reliance"]] if b else None]
    return rows, [(a, w) for a, _, w in held], (snaps, t, p)


def _overlay_js(out):
    o = out.get("summary", {}).get("overlay") or {}
    return ({x["lineage"]: [[x["store"]["state"], x["store"]["reliance"]], [x["reader"]["state"], x["reader"]["reliance"]] if x["reader"] else None]
             for x in o.get("rows", [])}, [(h["actor"], h["why"]) for h in o.get("held", [])], o)


def browser_others_cases():
    """The reader's other stores (site/reader.mjs readOthers, outside, overlay): a publisher's store, a commons holding a
    stranger's challenge under its key's own name, and a lab holding a replayer's `reproduces` on it. Voices from outside
    are shown, never counted by the store read; with the reader's own rules the union is assessed under them, held to
    warrant_agent.overlay through node."""
    from warrant import commons as CM
    from warrant_agent import overlay as OV
    from world import KEYS
    pub = Repo()
    o = pub.entity("alice", "obligation@1", {"state": "open", "statement": "the claim", "serves": []})
    d = pub.entity("alice", "obligation@1", {"state": "done", "statement": "the claim", "serves": []}, lineage=o)
    pub.attest("bob", d)
    other = pub.entity("alice", "obligation@1", {"state": "open", "statement": "nobody spoke of this", "serves": []})
    hostile = "<img src=x onerror=alert(1)> \u202e&amp; the claim ignores the cold start"
    commons = pub.home / "commons"
    stranger = CM.seed(pub.home / "stranger.seed")
    voice = CM.say(commons, d, hostile, stranger, at=1_900_000_000)
    forged = R.record("challenge", "claude", 1_900_000_001, {"target": d, "statement": "I am claude"}, refs=[d])
    ST.Store(commons / ".warrant").extend([forged], stranger, CM.DOC["trust"])            # claude's name, a stranger's key
    q = pub.entity("alice", "obligation@1", {"state": "open", "statement": "accepted at a commit", "serves": []})
    q2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "accepted at a commit", "serves": []}, lineage=q)
    pub.attest("bob", q2, commit="c" * 40)
    voice_q = CM.say(commons, q2, "the commit does not hold it", stranger, at=1_900_000_002)
    lab = Repo()
    lab.put("carol", "attest", {"target": voice, "verdict": "reproduces", "on": d}, refs=[voice, d])   # carol: replayer
    lab.put("carol", "attest", {"target": voice_q, "verdict": "reproduces", "on": q2}, refs=[voice_q, q2])
    trusting = pub.home / "trusting.json"                       # the publisher's own rules, pasted: carol's replays count
    trusting.write_text(json.dumps({"trust": pub.trust, "profile": pub.profile}))
    doubting_profile = dict(pub.profile, roles=dict(pub.profile["roles"], replayer=[]))
    doubting = pub.home / "doubting.json"
    doubting.write_text(json.dumps({"trust": pub.trust, "profile": doubting_profile}))
    srvs, (b_pub, b_com, b_lab) = _serve_many(pub.root, commons, lab.root)
    gone = "http://127.0.0.1:9/"                                 # the discard port: nothing answers
    try:
        _, plain = _reader(b_pub)
        _, alone = _reader(b_pub, "--with", b_com, "--with", b_lab, "--with", gone)
        _, opened = _reader(b_pub, "--with", b_com, "--with", b_lab, "--lineage", o)
        _, mine = _reader(b_pub, "--with", b_com, "--with", b_lab, "--config", str(trusting))
        _, opened_mine = _reader(b_pub, "--with", b_com, "--with", b_lab, "--config", str(trusting), "--lineage", o)
        _, theirs = _reader(b_pub, "--with", b_com, "--with", b_lab, "--config", str(doubting))
    finally:
        for x in srvs:
            x.shutdown()
    rows = {x["id"]: x for x in alone.get("rows", [])}
    floor = (opened.get("lineage") or {}).get("floor", {})
    out = floor.get("outside") or {}
    vs = out.get("voices", [])
    summ = alone.get("summary", {})
    check("J12 a challenge another store holds against a version of a lineage is shown on that lineage as a voice from "
          "outside, with its store (its repository name) and its actor as that store names it, uncounted: the store's "
          "reliance is unchanged and the list marks the lineage",
          [(v["id"], v["kind"], v["actor"], v["store"], v["address"], v["counted"]) for v in vs]
          == [(voice, "challenge", "key:" + stranger.public, CM.DOC["repository"], b_com, False)] and floor.get("reliance") == "ELIGIBLE"
          and rows.get(o, {}).get("reliance") == "ELIGIBLE" and rows.get(o, {}).get("outside") == 1 and rows.get(other, {}).get("outside") == 0
          and out.get("stores") == 1 and summ.get("others", {}).get("counted") == 0, (vs, floor.get("reliance"), rows.get(o)))
    check("J12 what a voice says reaches the data unchanged, as text", [v["statement"] for v in vs] == [hostile], vs)
    check("J12 a line the other store rejects (a challenge under claude's name, signed with a stranger's key) is no voice: "
          "it is not shown and is counted as left out", voice in [v["id"] for v in vs] and len(vs) == 1 and out.get("left_out") == 1
          and summ.get("others", {}).get("left_out") == 1, out)
    names = {x["address"]: x for x in summ.get("others", {}).get("stores", [])}
    check("J12 a store that cannot be read is named with its reason, and the others still answer",
          names.get(gone, {}).get("read") is False and names.get(gone, {}).get("why") and names.get(b_com, {}).get("read") is True
          and names.get(b_lab, {}).get("read") is True and len(vs) == 1, names)
    check("J12 with no rules of the reader's own there is no overlay, and the answer says why",
          "no rules of the reader's own" in (summ.get("overlay") or {}).get("why", ""), summ.get("overlay"))
    check("J12 without other stores nothing changes: no others or overlay member, no outside count in the list",
          "others" not in plain.get("summary", {}) and "overlay" not in plain.get("summary", {})
          and all("outside" not in x for x in plain.get("rows", [])), plain.get("summary", {}).get("others"))

    roots, addrs = [pub.root, commons, lab.root], [b_pub, b_com, b_lab]
    py1, held1, (snaps, t1, p1) = _overlay_py(roots, addrs, pub.trust, pub.profile)
    js1, jheld1, o1 = _overlay_js(mine)
    lin_mine = ((opened_mine.get("lineage") or {}).get("floor") or {}).get("overlay") or {}
    check("J12 overlay, a reader who trusts the replayer: the union under the reader's rules gives exactly the changed "
          "lineages and verdicts warrant_agent.overlay gives: the claim reads CHALLENGED for the reader, ELIGIBLE in its "
          "store, with the challenge that makes the difference", py1 == js1 and py1.get(o) == [["done", "ELIGIBLE"], ["done", "CHALLENGED"]]
          and lin_mine.get("challenges") == [voice] and jheld1 == held1, (py1, js1, lin_mine))
    shown_q = next((x for x in o1.get("rows", []) if x["lineage"] == q), {})
    check("J12 the overlay compares no pins: on both sides ELIGIBLE on an acceptance at a commit reads PINS_NOT_CHECKED "
          "(the store's side here), and the summary says so", py1.get(q) == [["done", "ELIGIBLE"], ["done", "CHALLENGED"]]
          and shown_q.get("store", {}).get("shown") == "PINS_NOT_CHECKED" and shown_q.get("reader", {}).get("shown") == "CHALLENGED"
          and "compares no pins" in o1.get("pins", ""), shown_q)
    check("J12 the overlay's identity is warrant_agent.overlay's for the same stores, receiver and engine",
          o1.get("identity") == OV.identity(snaps, t1, p1, o1.get("code")), (o1.get("identity"), o1.get("code")))
    py2, _, _ = _overlay_py(roots, addrs, pub.trust, doubting_profile)
    js2, _, _ = _overlay_js(theirs)
    check("J12 overlay, a reader who does not trust the replayer: nothing reads otherwise, as warrant_agent.overlay says",
          py2 == js2 == {} and "rows" in (theirs.get("summary", {}).get("overlay") or {}), (py2, js2))

    # #348: a source store binds a role holder's name to its own key and signs that holder's acceptance
    pub6 = Repo()
    e = pub6.entity("alice", "obligation@1", {"state": "open", "statement": "another claim", "serves": []})
    e2 = pub6.entity("alice", "obligation@1", {"state": "done", "statement": "another claim", "serves": []}, lineage=e)
    unpinned = dict(pub6.trust, keys={a: k for a, k in pub6.trust["keys"].items() if a != "bob"})
    pub6.trust = unpinned
    pub6.write_config()
    forger = Repo()
    forger.trust = dict(forger.trust, keys=dict(unpinned["keys"], bob=[KEYS["dave"].public], eve=[KEYS["dave"].public]))
    forger.write_config()
    forger.store.append(R.record("attest", "bob", forger.t + 1, {"target": e2, "verdict": "accept"}, refs=[e2]), KEYS["dave"], forger.trust)
    reader = pub.home / "unpinned.json"
    own_trust = dict(unpinned, keys={a: k for a, k in unpinned["keys"].items() if a != "eve"})     # the reader binds no eve
    reader.write_text(json.dumps({"trust": own_trust, "profile": pub6.profile}))
    srvs, (b6, bf) = _serve_many(pub6.root, forger.root)
    try:
        _, impost = _reader(b6, "--with", bf, "--config", str(reader))
    finally:
        for x in srvs:
            x.shutdown()
    py6, held6, _ = _overlay_py([pub6.root, forger.root], [b6, bf], own_trust, pub6.profile)
    js6, jheld6, _ = _overlay_js(impost)
    check("J12 overlay, #348: a source whose trust binds a role holder (bob, roadmap/acceptor) to another key does not give "
          "that key the role: the binding is held, named, and its forged acceptance settles nothing, as "
          "warrant_agent.overlay says; a binding the sources disagree on (eve) is held too",
          ("bob", "role") in held6 and ("eve", "disagree") in held6 and jheld6 == held6 and js6 == py6 and e not in js6
          and "rows" in (impost.get("summary", {}).get("overlay") or {}), (held6, jheld6, py6, js6, impost.get("summary", {}).get("overlay")))


def _report(root):
    from warrant import repo as RP
    return RP.Repo(root).report()


def _acceptance_files(root):
    """The {path: blob} of every signed acceptance by the claims checker in the checkout's store."""
    from warrant import claims as CL
    return [f for xs in CL.acceptances(_report(root)).values() for _, f, _ in xs if isinstance(f, dict)]


if __name__ == "__main__":
    sys.exit(main())
