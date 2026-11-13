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
from shlex import quote as shlex_quote
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
    browser_changes_cases()
    browser_desk_cases()
    browser_frontier_cases()
    browser_door_cases()
    browser_watch_cases()
    browser_toward_cases()
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
DESK_FILES = [ROOT / "site" / "desk.html", ROOT / "site" / "desk-page.mjs", ROOT / "site" / "desk.mjs", ROOT / "site" / "page.mjs"]
DESK = ROOT / "site" / "desk.mjs"
DOOR_FILES = [ROOT / "site" / "object.html", ROOT / "site" / "voice.mjs"]   # J16: the door (object.html runs no script)
# bidirectional controls and zero-width characters: none may stand literally in a page's source (written as escapes)
INVISIBLE = {chr(c) for c in [*range(0x202a, 0x202f), *range(0x2066, 0x206a), 0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x2060, 0xfeff, 0x061c]}
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

    texts = {p.name: p.read_text() for p in PAGE_FILES + DESK_FILES + DOOR_FILES}
    html, desk_html, door_html = texts["reader.html"], texts["desk.html"], texts["object.html"]
    csp = lambda h: re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', h)
    found = sorted((name, word) for name, text in texts.items() for word in MARKUP_FROM_TEXT if word in text)
    hidden = sorted((name, f"U+{ord(ch):04X}") for name, text in texts.items() for ch in INVISIBLE if ch in text)
    door_csp = csp(door_html)
    check("J10 the page's source: no call that builds markup from a string in the reader's three files, the desk's "
          "four (desk.html, desk-page.mjs, desk.mjs, page.mjs) and the door's two (object.html, voice.mjs), no literal "
          "bidirectional or zero-width character in any of them; the reader and the desk one script element each and "
          "that one external, object.html none and a policy allowing none (default-src 'none', no script-src), no "
          "inline handler, and a policy allowing scripts of its own origin only; the desk's policy is the reader's, word "
          "for word",
          not found and not hidden and html.count("<script") == 1 and '<script type="module" src="reader-page.mjs"></script>' in html
          and desk_html.count("<script") == 1 and '<script type="module" src="desk-page.mjs"></script>' in desk_html
          and "<script" not in door_html and len(door_csp) == 1 and "default-src 'none'" in door_csp[0] and "script-src" not in door_csp[0]
          and all(re.search(r"<[^>]*\son[a-z]+\s*=", h, re.I) is None for h in (html, desk_html, door_html))
          and "script-src 'self'" in html and "default-src 'none'" in html and "'unsafe-inline'" not in html
          and "'unsafe-eval'" not in html and len(csp(html)) == 1 and csp(desk_html) == csp(html)
          and "connect-src 'self' https:" in csp(html)[0], (found, hidden, csp(html), csp(desk_html), door_csp))


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


def _floor_py(rep):
    """{lineage: (state, reliance, the sorted counted challenges that stand against a version)} of a Python report."""
    return {L: (x["state"], x["reliance"], sorted(c for c, y in rep["challenges"].items()
                                                  if y["target"] in x["versions"] and y.get("counted") and y.get("stands")))
            for L, x in rep["lineages"].items()}


def browser_changes_cases():
    """What changed for me in the browser reader (site/reader.mjs makeMark, changes): the reader marks a store as seen
    (`--write-mark FILE`, the JSON the page keeps in localStorage), records are added, and the reader compares
    (`--mark FILE`). The past is the marked subset assessed again by the same engine; a lineage is listed when its view
    (viewOf) differs, with what appeared, vanished and moved; new records that change no view are counted. Each step
    marks afresh, so each case sees one step's records. One server per store for the whole run: a mark names its
    store's address."""
    import base64 as B64
    from warrant_agent import changes as CH
    pub, other = Repo(), Repo()
    a1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "the closure", "serves": []})
    a2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "the closure", "serves": []}, lineage=a1)
    b1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "the accepted one", "serves": []})
    b2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "the accepted one", "serves": []}, lineage=b1)
    acc_b = pub.attest("bob", b2)
    stranger = dict(json.loads((pub.dot / "v3.json").read_text()))
    stranger["profile"] = dict(stranger["profile"], roles=dict(stranger["profile"]["roles"], **{"roadmap/acceptor": ["carol"]}))
    (pub.home / "other-rules.json").write_text(json.dumps(stranger))
    (pub.home / "same-rules.json").write_text(json.dumps({"trust": pub.trust, "profile": pub.profile}))
    srvs, (b_pub, b_oth) = _serve_many(pub.root, other.root)
    n = iter(range(100))
    def mark(*args):
        path = pub.home / f"mark-{next(n)}.json"
        rc, out = _reader(b_pub, "--write-mark", str(path), *args)
        return path if rc == 0 and path.exists() else out
    def changed(path, *args):
        rc, out = _reader(b_pub, "--mark", str(path), *args)
        return out.get("changes") or {"rc": rc, "out": out}
    listed = lambda c: [x["lineage"] for x in c.get("listed", [])]
    try:
        m0, m0w = mark(), mark("--with", b_oth)
        keep0 = set(pub.store.snapshot().lines)
        c0, c0w = changed(m0), changed(m0w, "--with", b_oth)
        doc = json.loads(m0.read_text())
        e = doc["stores"].get(b_pub, {})
        text = m0.read_text()
        check("J13 (a) nothing added since the mark: nothing listed, no new record, and the reader says so; with other "
              "stores read the mark holds each of them, and still nothing is listed",
              listed(c0) == [] and c0.get("new") == 0 and c0.get("quiet") == 0 and c0.get("line") == "no new records since the mark"
              and listed(c0w) == [] and c0w.get("new") == 0 and sorted(json.loads(m0w.read_text())["stores"]) == sorted([b_pub, b_oth]), (c0, c0w))
        check("J13 the mark is compact and names no whole id: 8 bytes of each record id and one 32-byte digest per 16 ids, "
              "as canonical base64, under the store's address and the rules' identity",
              e.get("n") == len(keep0) and len(B64.b64decode(e.get("ids", ""))) == 8 * len(keep0)
              and len(B64.b64decode(e.get("groups", ""))) == 32 * -(-len(keep0) // 16) and not any(i in text for i in keep0)
              and doc.get("base") == b_pub and doc.get("rules") == C.doc_id({"trust": pub.trust, "profile": pub.profile}), (doc, len(keep0)))

        sid = pub.schemas["obligation@1"]
        pub.put("eve", "attest", {"target": sid, "verdict": "seen"}, refs=[sid])                 # on a schema: no lineage
        pub.put("dave", "attest", {"target": acc_b, "verdict": "react", "agree": 30}, refs=[acc_b])   # on an attest
        c1 = changed(m0)
        check("J13 (b) records that change no lineage's view (a `seen` on a schema record, a `react` on an attest: neither "
              "targets a version) are counted as new, not listed, and the reader says they changed nothing you see",
              listed(c1) == [] and c1.get("new") == 2 and c1.get("quiet") == 2 and c1.get("line") == "2 new record(s) changed nothing you see", c1)

        m2 = mark()
        by_eve = pub.attest("eve", b2)
        c2 = changed(m2)
        x = (c2.get("listed") or [{}])[0]
        check("J13 (b') an attest by an actor with no role on a version moves no floor but is drawn among the version's "
              "attests: listed with that attest as what appeared and nothing moved (agent_test CH2 under the built-in lens)",
              listed(c2) == [b1] and x.get("appeared") == [[by_eve, "attest"]] and x.get("moved") == {} and x.get("vanished") == []
              and c2.get("quiet") == 0, c2)

        m3 = mark()
        acc_a = pub.attest("bob", a2, commit="c" * 40)
        c3 = changed(m3)
        x = (c3.get("listed") or [{}])[0]
        check("J13 (c) a closure accepted (at a commit): its lineage is listed with its state and reliance then and now, "
              "the reliance as shown (PINS_NOT_CHECKED, never ELIGIBLE on pins not compared), the acceptance appeared",
              listed(c3) == [a1] and x.get("moved", {}).get("state") == ["open", "done"]
              and x.get("moved", {}).get("reliance") == ["ELIGIBLE", "PINS_NOT_CHECKED"] and x.get("moved", {}).get("effective") == [a1, a2]
              and [acc_a, "attest"] in x.get("appeared", []) and [a2, "accepted by bob"] in x.get("appeared", [])
              and [a2, "guard MET"] in x.get("appeared", []) and [a2, "guard PENDING"] in x.get("vanished", []) and x.get("new") is False, c3)

        m4 = mark()
        ch_b = pub.put("bob", "challenge", {"target": b2, "statement": "counted, and it stands"}, refs=[b2])
        c4 = changed(m4)
        x = (c4.get("listed") or [{}])[0]
        check("J13 (d) a counted challenge filed: the lineage is listed, the challenge named as what appeared (counted, "
              "standing) and the standing challenges and reliance moved",
              listed(c4) == [b1] and x.get("moved", {}).get("standing") == [[], [ch_b]]
              and x.get("moved", {}).get("reliance", [None])[0] == "ELIGIBLE" and x.get("moved", {}).get("reliance", [None, None])[1] != "ELIGIBLE"
              and all([ch_b, m] in x.get("appeared", []) for m in ("challenge", "counted", "stands")), c4)

        m5 = mark()
        c_new = pub.entity("alice", "obligation@1", {"state": "open", "statement": "a new task", "serves": []})
        c5 = changed(m5)
        x = (c5.get("listed") or [{}])[0]
        check("J13 (e) a new lineage is listed as new: no view before, moved names it new",
              listed(c5) == [c_new] and x.get("new") is True and x.get("before") is None and x.get("moved") == {"new": [None, True]}
              and x.get("title") == "a new task", c5)

        m6, m6w = mark(), mark("--with", b_oth)
        voice = other.put("carol", "challenge", {"target": a2, "statement": "from elsewhere"}, refs=[a2])
        c6w, c6 = changed(m6w, "--with", b_oth), changed(m6)
        x = (c6w.get("listed") or [{}])[0]
        check("J13 (f) a voice from outside appearing in another store: listed when that store is read (`--with`), the "
              "voice as what appeared and nothing moved (it is not counted here); without `--with` nothing is listed and "
              "nothing is new in the store read",
              listed(c6w) == [a1] and x.get("appeared") == [[voice, f"voice from {b_oth}"]] and x.get("moved") == {}
              and c6w.get("new") == 1 and c6w.get("quiet") == 0 and listed(c6) == [] and c6.get("new") == 0, (c6w, c6))

        c7, c7s = changed(m6, "--config", str(pub.home / "other-rules.json")), changed(m6, "--config", str(pub.home / "same-rules.json"))
        check("J13 (g) a mark belongs to its rules' identity: under other rules it is not used (no listing, and the "
              "reason); under the same trust and profile pasted by the reader it is",
              c7.get("mark") is None and "other rules" in (c7.get("why") or "") and "listed" not in c7
              and c7s.get("mark") is not None and listed(c7s) == [], (c7, c7s))

        rest = changed(m0)
        past, now = CH.report_of(pub.root, CH.subset(pub.store.snapshot(), keep0)), CH.report_of(pub.root, pub.store.snapshot())
        fp, fn = _floor_py(past), _floor_py(now)
        py = {L for L in fn if L not in fp or fp[L] != fn[L]}
        js = {x["lineage"] for x in rest.get("listed", []) if x["new"] or {"state", "reliance", "standing"} & set(x["moved"])}
        check("J13 (i) differential: from the first mark, the lineages whose (state, reliance, standing challenges) the "
              "reader lists as moved, or as new, are exactly those whose Python assessments of the marked subset "
              "(warrant_agent.changes.subset) and of the whole store differ",
              js == py == {a1, b1, c_new}, (sorted(js), sorted(py)))

        for k in range(40):                                  # enough records for groups of 16 to split
            pub.put("eve", "attest", {"target": sid, "verdict": "seen", "n": k}, refs=[sid])
        mh = mark()
        marked = sorted(set(pub.store.snapshot().lines))
        lines_path = pub.dot / "records.jsonl"
        whole = lines_path.read_bytes()
        try:
            lines_path.write_bytes(b"".join(l for l in whole.splitlines(keepends=True) if b"a new task" not in l))     # the only line of that lineage
            ch_h = changed(mh)
        finally:
            lines_path.write_bytes(whole)
        k = marked.index(c_new) // 16
        doubt = len(marked[16 * k:16 * k + 16]) - 1
        st = ((ch_h.get("mark") or {}).get("stores") or [{}])[0]
        check("J13 (h) a mark naming a record the store no longer serves: no crash, one counted gone and said so, its "
              "lineage not listed (its bytes are not held, so neither state has it), and the rest of its group of 16 "
              "counted as new (unverified, said), never as seen",
              st.get("gone") == 1 and st.get("unverified") == doubt == st.get("new") and 0 < doubt < len(marked) - 1
              and c_new not in listed(ch_h) and "1 marked record(s) no longer served" in ch_h.get("line", "")
              and f"{doubt} record(s) whose mark could not be verified" in ch_h.get("line", ""), (ch_h, doubt))

        bad = json.loads(mh.read_text())
        g = bytearray(B64.b64decode(bad["stores"][b_pub]["groups"]))
        g[0] ^= 1
        bad["stores"][b_pub]["groups"] = B64.b64encode(bytes(g)).decode()
        mj = pub.home / "mark-tampered.json"
        mj.write_text(json.dumps(bad))
        ch_j = changed(mj)
        st = ((ch_j.get("mark") or {}).get("stores") or [{}])[0]
        check("J13 (j) a group whose digest does not verify is not trusted: its 16 records are counted as new "
              "(unverified), none of them is called seen; the other groups are",
              st.get("unverified") == 16 and st.get("new") == 16 and ch_j.get("new") == 16 and st.get("gone") == 0
              and len(marked) > 32, ch_j)
        good = json.loads(mh.read_text())["stores"][b_pub]
        spaced = json.loads(mh.read_text())
        spaced["stores"][b_pub]["ids"] = good["ids"][:4] + " " + good["ids"][4:]            # atob would skip the space
        miscount = json.loads(mh.read_text())
        miscount["stores"][b_pub]["n"] = good["n"] + 1                                      # a count its bytes do not hold
        ch_k = []
        for k, m in enumerate((spaced, miscount)):
            (pub.home / f"mark-malformed-{k}.json").write_text(json.dumps(m))
            ch_k.append(changed(pub.home / f"mark-malformed-{k}.json"))
        (pub.home / "mark-text.json").write_text("not json")
        ch_t = changed(pub.home / "mark-text.json")
        ch_n = changed(pub.home / "no-such-mark.json")
        check("J13 (k) a mark that is not the one form makeMark writes (base64 with a space that atob skips, a count its "
              "bytes do not hold), or not JSON, cannot be read and is said so; a missing file is no mark yet; none of "
              "them presents anything as changed",
              all(c.get("mark") is None and "cannot be read" in c.get("why", "") for c in ch_k + [ch_t])
              and ch_n.get("mark") is None and ch_n.get("why", "").startswith("no mark yet")
              and not any("listed" in c for c in ch_k + [ch_t, ch_n]), (ch_k, ch_t, ch_n))
    finally:
        for srv in srvs:
            srv.shutdown()


def _desk(*args):
    """(exit status, the desk's JSON answer) of `node site/desk.mjs ...`."""
    p = subprocess.run([NODE, str(DESK), *args], capture_output=True, check=False, timeout=600)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, {"crash": p.stderr.decode(errors="replace")[-300:]}


def _desk_expected(root):
    """What a desk block must say of the store at `root`, from the Python engine under the store's own rules: records,
    rejected, lineages, reliance counts (ELIGIBLE on an effective version an attest names files or a commit of reads
    PINS_NOT_CHECKED, as J10) and the lineages with a counted challenge that stands."""
    doc = json.loads((Path(root) / ".warrant" / "v3.json").read_text())
    view = E.View(ST.Store(Path(root) / ".warrant").snapshot(), doc["trust"], doc["profile"], None)
    rep = view.report()
    speaks = {r["body"]["target"] for r in view.recs.values() if r["kind"] == "attest" and ("files" in r["body"] or "commit" in r["body"])}
    reliance = {}
    for x in rep["lineages"].values():
        w = "PINS_NOT_CHECKED" if x["reliance"] == "ELIGIBLE" and x["effective"] in speaks else x["reliance"]
        reliance[w] = reliance.get(w, 0) + 1
    standing = {L for L, x in rep["lineages"].items() if any(rep["versions"][v]["challenged_by"] for v in x["versions"])}
    return {"records": len(view.snap.lines), "rejected": len(rep["rejected"]), "lineages": len(rep["lineages"]),
            "reliance": dict(sorted(reliance.items())), "challenged": len(standing)}


def browser_desk_cases():
    """The desk (site/desk.mjs, drawn by site/desk-page.mjs): several stores read at once, one block each, with what
    changed for the reader since each store's own mark (the reader's mark: reader.mjs makeMark and changes(); the CLI
    keeps one file per store, named by the SHA-256 of its address, where the page keeps localStorage under one key per
    address and rules). Held through node to the Python engine and to the reader's own CLI; no case drives a browser."""
    from world import KEYS
    hostile = "<img src=x onerror=alert(1)><script>alert(2)</script> \u202e&amp; \u200b"
    one, two, three = Repo(name="one/store"), Repo(name="two/store"), Repo(name="three/store")
    o1 = one.entity("alice", "obligation@1", {"state": "open", "statement": "accepted", "serves": []})
    one.attest("bob", one.entity("alice", "obligation@1", {"state": "done", "statement": "accepted", "serves": []}, lineage=o1))
    p1 = one.entity("alice", "obligation@1", {"state": "open", "statement": "accepted at a commit", "serves": []})
    one.attest("bob", one.entity("alice", "obligation@1", {"state": "done", "statement": "accepted at a commit", "serves": []}, lineage=p1), commit="c" * 40)
    c1 = one.entity("alice", "obligation@1", {"state": "open", "statement": "challenged", "serves": []})
    c2 = one.entity("alice", "obligation@1", {"state": "done", "statement": "challenged", "serves": []}, lineage=c1)
    one.attest("bob", c2)
    one.put("bob", "challenge", {"target": c2, "statement": "counted, and it stands"}, refs=[c2])
    one.store.append(R.record("challenge", "bob", one.t + 1, {"target": c2, "statement": "not bob's key"}, refs=[c2]), KEYS["dave"], one.trust)
    two.entity("alice", "obligation@1", {"state": "open", "statement": "the other store's task", "serves": []})
    three.entity("alice", "obligation@1", {"state": "open", "statement": "never read whole", "serves": []})
    srvs, (b1, b2) = _serve_many(one.root, two.root)
    fsrv, b3 = _serve_failing(three.root, "records.jsonl")
    srvs.append(fsrv)
    gone = "http://127.0.0.1:9/"                                 # the discard port: nothing answers
    marks = one.home / "desk-marks"
    marks.mkdir()
    blocks = lambda out: {x["base"]: x for x in (out.get("desk") or {}).get("stores", [])}
    lines = lambda out: {b: x.get("changes", {}).get("line") for b, x in blocks(out).items()}
    listed = lambda out, b: [x["lineage"] for x in blocks(out).get(b, {}).get("changes", {}).get("listed", [])]
    stores = ("--store", b1, "--store", b2, "--store", gone, "--store", b3, "--marks", str(marks))
    no_mark = "no mark yet: nothing is compared until you mark this store as seen"
    try:
        rc0, d0 = _desk(*stores)
        x0 = blocks(d0)
        e1, e2 = _desk_expected(one.root), _desk_expected(two.root)
        got = lambda b: {k: x0.get(b, {}).get(k) for k in e1}
        check("J14 several stores read at once: each read store's block gives the Python engine's records, rejected (a "
              "line under bob's name with another's key), lineages, reliance (never ELIGIBLE on pins not compared) and "
              "lineages with a standing counted challenge, under the "
              "publisher's rules, in the order given; with no mark yet each says so and lists nothing",
              rc0 == 0 and [x["base"] for x in d0.get("desk", {}).get("stores", [])] == [b1, b2, gone, b3]
              and got(b1) == e1 and got(b2) == e2 and e1["challenged"] == 1 and e1["reliance"].get("PINS_NOT_CHECKED") == 1 and e1["rejected"] == 1
              and x0.get(b1, {}).get("rules") == "publisher" and x0.get(b1, {}).get("repository") == "one/store"
              and lines(d0).get(b1) == lines(d0).get(b2) == no_mark and not listed(d0, b1) and not listed(d0, b2),
              (rc0, d0.get("crash"), got(b1), e1, got(b2), e2))
        check("J14 a store that cannot be read is named with its reason and the others still answer: nothing answers at "
              "one address (not fetched), another answers its records with HTTP 500; each block is the refusal alone, "
              "nothing partial (no count, no change, no wait in it)",
              x0.get(gone, {}).get("read") is False and "not fetched" in x0.get(gone, {}).get("why", "")
              and x0.get(b3, {}).get("read") is False and "HTTP 500" in x0.get(b3, {}).get("why", "")
              and all(set(x0.get(b, {})) == {"name", "base", "read", "why"} for b in (gone, b3))
              and x0.get(b1, {}).get("read") is True and x0.get(b2, {}).get("read") is True, (x0.get(gone), x0.get(b3)))

        rc1, d1 = _desk(*stores, "--write-mark", b1)
        rc1b, d1b = _desk(*stores)
        name1 = hashlib.sha256(b1.encode()).hexdigest() + ".json"
        files = sorted(x.name for x in marks.iterdir())
        rm = one.home / "reader-mark.json"
        _reader(b1, "--write-mark", str(rm))
        dm, rmj = json.loads((marks / name1).read_text()) if (marks / name1).exists() else {}, json.loads(rm.read_text())
        check("J14 marks are per store: marking one writes one file, named by the SHA-256 of its address; then that "
              "store has nothing new since its mark and the other still has no mark; the file is the reader's own mark "
              "(the same JSON reader.mjs --write-mark writes for that store, but for its time)",
              rc1 == rc1b == 0 and files == [name1] and lines(d1b).get(b1) == "no new records since the mark"
              and lines(d1b).get(b2) == no_mark and {k: v for k, v in dm.items() if k != "at"} == {k: v for k, v in rmj.items() if k != "at"},
              (files, lines(d1b), sorted(dm), sorted(rmj)))

        _desk(*stores, "--write-mark", b2)
        L = two.entity("alice", "obligation@1", {"state": "open", "statement": hostile, "serves": []})
        rc2, d2 = _desk(*stores)
        x2 = blocks(d2).get(b2, {}).get("changes", {})
        _, via_reader = _reader(b2, "--mark", str(marks / (hashlib.sha256(b2.encode()).hexdigest() + ".json")))
        check("J14 a change in one store is listed in its block only: a new lineage in the second store is listed there "
              "(as new, its statement unchanged as data) and the first store's block says nothing new; the reader's own "
              "CLI, given the desk's mark file, lists the same lineages with the same sentence",
              rc2 == 0 and listed(d2, b2) == [L] and x2.get("listed", [{}])[0].get("new") is True
              and x2.get("listed", [{}])[0].get("title") == hostile
              and x2.get("line") == "1 lineage(s) changed for you · 0 other new record(s) changed nothing you see"
              and lines(d2).get(b1) == "no new records since the mark" and listed(d2, b1) == []
              and [x["lineage"] for x in (via_reader.get("changes") or {}).get("listed", [])] == [L]
              and (via_reader.get("changes") or {}).get("line") == x2.get("line"), (x2, lines(d2), via_reader.get("changes")))

        one.entity("alice", "obligation@1", {"state": "open", "statement": "a new one in the first store", "serves": []})
        rc3, d3 = _desk(*stores)
        rc4, _ = _desk(*stores, "--write-marks")
        rc5, d5 = _desk(*stores)
        check("J14 mark all: before it each store lists its own change; after it nothing changed anywhere, every read "
              "store says so, and a store that cannot be read is still named, not marked",
              rc3 == rc4 == rc5 == 0 and len(listed(d3, b1)) == 1 and listed(d3, b2) == [L]
              and lines(d5).get(b1) == lines(d5).get(b2) == "no new records since the mark"
              and not listed(d5, b1) and not listed(d5, b2) and blocks(d5).get(gone, {}).get("read") is False
              and len(list(marks.iterdir())) == 2, (lines(d3), lines(d5), sorted(x.name for x in marks.iterdir())))

        hostile_list = one.home / "hostile-list.json"
        hostile_list.write_text(json.dumps([{"name": hostile, "base": b1}]))
        _, dh = _desk("--list", str(hostile_list))
        check("J14 what a list or a record says reaches the desk's data unchanged, as text: a store named with markup, a "
              "direction override and a zero-width space keeps that name, a statement holding them keeps its text",
              [x.get("name") for x in (dh.get("desk") or {}).get("stores", [])] == [hostile] and x2.get("listed", [{}])[0].get("title") == hostile, dh)
    finally:
        for x in srvs:
            x.shutdown()

    default = json.loads((ROOT / "site" / "stores.json").read_text())
    _, plan0 = _desk("--plan")
    _, plan_a = _desk("--plan", "--store", "https://example.org/a", "--store", "https://example.org/a/", "--store", "ftp://example.org/b")
    _, plan_bad = _desk("--plan", "--store", "javascript:alert(1)")
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "kept.json").write_text(json.dumps([{"name": "mine", "base": "https://example.org/mine"}, {"name": "again", "base": "https://example.org/mine/"}]))
        (tmp / "kept-bad.json").write_text(json.dumps([{"name": "mine", "base": "file:///etc/"}]))
        (tmp / "kept-empty.json").write_text("[]")
        (tmp / "list-bad.json").write_text(json.dumps({"name": "not a list"}))
        _, plan_k = _desk("--plan", "--kept", str(tmp / "kept.json"))
        _, plan_kb = _desk("--plan", "--kept", str(tmp / "kept-bad.json"))
        _, plan_ke = _desk("--plan", "--kept", str(tmp / "kept-empty.json"))
        _, plan_ka = _desk("--plan", "--kept", str(tmp / "kept.json"), "--store", "https://example.org/a")
        _, plan_lb = _desk("--plan", "--list", str(tmp / "list-bad.json"))
    finally:
        shutil.rmtree(tmp)
    want = [{"base": "https://raw.githubusercontent.com/s0fractal/warrant/master/", "name": "s0fractal/warrant"},
            {"base": "https://raw.githubusercontent.com/s0fractal/minds/main/", "name": "s0fractal/minds"}]
    check("J14 the default list: site/stores.json is a plain list of {name, base} holding this repository's store and "
          "minds' (beside its release entries, J16), and it is what the desk reads when no store= is given and none is "
          "kept (no network: the selection alone)",
          [dict(sorted(x.items())) for x in default if "release" not in x] == want and plan0 == {"from": "list", "stores": want, "why": []}, (default, plan0))
    check("J14 the selection rule: store= addresses first (each read once, named by its address; one that is not "
          "http(s) is named and skipped), then the list kept in the browser (an address listed twice is read once, under "
          "its first name), then stores.json; a kept list that is "
          "empty or names a non-http(s) address is not used and the desk says why; a stores.json that is no list "
          "reads nothing and says why; an address that is no http(s) reads nothing it names",
          plan_a.get("from") == "address" and plan_a.get("stores") == [{"base": "https://example.org/a/", "name": "https://example.org/a/"}]
          and len(plan_a.get("why", [])) == 1 and "not http(s)" in plan_a["why"][0]
          and plan_k == {"from": "kept", "stores": [{"base": "https://example.org/mine/", "name": "mine"}], "why": []}
          and plan_ka.get("from") == "address"
          and plan_kb.get("from") == "list" and plan_kb.get("stores") == want and "not used" in " ".join(plan_kb.get("why", []))
          and plan_ke.get("from") == "list" and "empty" in " ".join(plan_ke.get("why", []))
          and plan_lb.get("from") == "none" and plan_lb.get("stores") == [] and "not a list" in " ".join(plan_lb.get("why", []))
          and plan_bad.get("from") == "list" and "not http(s)" in " ".join(plan_bad.get("why", [])),
          (plan_a, plan_k, plan_kb, plan_ke, plan_ka, plan_lb, plan_bad))


def _frontier_py(root, actor):
    """warrant.graph.frontier of the store at `root` under its own rules, for `actor`."""
    from warrant import graph as G
    doc = json.loads((Path(root) / ".warrant" / "v3.json").read_text())
    rep = E.View(ST.Store(Path(root) / ".warrant").snapshot(), doc["trust"], doc["profile"], None).report()
    return G.frontier(rep, doc["profile"], actor)


def browser_frontier_cases():
    """What waits for whom (site/reader.mjs frontier, drawn by the reader and counted by the desk): differential against
    warrant.graph.frontier, on a fixture that reaches each branch of its rule and on this repository's own store."""
    from world import KEYS
    f = Repo()
    def closure(actor, statement, **kw):
        o = f.entity(actor, "obligation@1", {"state": "open", "statement": statement, "serves": []})
        return o, f.entity(actor, "obligation@1", {"state": "done", "statement": statement, "serves": []}, lineage=o, **kw)
    w_root, waits = closure("alice", "waits for an acceptor")
    s_root, seen = closure("alice", "attested by bob, short of the match")
    f.attest("bob", seen, verdict="seen")
    c_root, chal = closure("alice", "challenged by bob")
    f.put("bob", "challenge", {"target": chal, "statement": "a counterexample"}, refs=[chal])
    goal = f.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "still open"})
    r_root, needs = closure("alice", "requires an open lineage", requires=[goal])
    b_root, bobs = closure("bob", "bob's own closure")
    claim = {"id": "C1", "source": "docs/V3.md", "section": "1", "text": "a claim", "witnesses": [], "mutants": []}
    cl = f.entity("bob", "claim@1", dict(claim, state="unbacked"))
    backed = f.entity("bob", "claim@1", dict(claim, state="backed"), lineage=cl)
    pr = f.entity("dave", "pr-head@1", {"state": "open", "title": "a head"})
    head = f.entity("dave", "pr-head@1", {"state": "head", "title": "a head"}, lineage=pr)
    a_root, accepted = closure("alice", "accepted, then challenged by its acceptor")
    f.attest("bob", accepted)
    f.put("bob", "challenge", {"target": accepted, "statement": "it does not hold"}, refs=[accepted])
    e_root, eves = closure("eve", "eve holds no role")
    x_root, replaced = closure("alice", "replaced while pending")
    newer = f.entity("alice", "obligation@1", {"state": "open", "statement": "reopened", "serves": []}, lineage=replaced)
    k_root = f.entity("alice", "obligation@1", {"state": "open", "statement": "forked", "serves": []})
    f.entity("alice", "obligation@1", {"state": "done", "statement": "forked one way", "serves": []}, lineage=k_root)
    f.entity("alice", "obligation@1", {"state": "done", "statement": "forked another", "serves": []}, lineage=k_root)
    forged = f.store.append(R.record("challenge", "bob", f.t + 1, {"target": waits, "statement": "not bob's key"}, refs=[waits]), KEYS["dave"], f.trust)
    actors = ["alice", "bob", "carol", "dave", "eve", "nobody", "bo"]       # "bo": a prefix of a role holder, no holder
    srvs, (bf,) = _serve_many(f.root)
    try:
        js = {a: _reader(bf, "--actor", a)[1].get("frontier") for a in actors}
        _, plain = _reader(bf)
        _, d_bob = _desk("--store", bf, "--actor", "bob")
        _, d_none = _desk("--store", bf)
    finally:
        for x in srvs:
            x.shutdown()
    py = {a: _frontier_py(f.root, a) for a in actors}
    bob = py["bob"]
    may = [x["version"] for x in bob["attest"]]
    check("J15 the fixture reaches each branch of warrant.graph.frontier: bob may attest the closure that waits and the "
          "pull request head and eve's closure (roles he holds), not one he attested short of the match, not one he "
          "challenged while it waits, not one that requires an open lineage, not his own (pending instead), not a "
          "version replaced while pending, not a fork; a line under his name with another's key is no act of his; "
          "carol may attest bob's claim; alice's lineage whose acceptor challenged it is listed as challenged; eve "
          "holds no role and has her own pending closure",
          sorted(may) == sorted([waits, head, eves]) and sorted(bob["pending"]) == sorted([bobs, backed]) and bob["challenged"] == []
          and [x["version"] for x in py["carol"]["attest"]] == [backed] and py["alice"]["challenged"] == [a_root]
          and chal in py["alice"]["pending"] and needs in py["alice"]["pending"] and seen in py["alice"]["pending"]
          and py["dave"]["pending"] == [head] and forged in f.report()["rejected"]
          and py["eve"]["roles"] == [] and py["eve"]["pending"] == [eves] and py["eve"]["attest"] == []
          and replaced not in may and newer not in py["alice"]["pending"] and py["nobody"]["roles"] == []
          and forged not in json.dumps(bob), py)
    check("J15 differential: the reader's frontier (reader.mjs --actor) equals warrant.graph.frontier for every actor of "
          "the fixture, an actor with no role, a name no profile holds and a prefix of a role holder's name included, "
          "member for member",
          all(js[a] == py[a] for a in actors), {a: (js[a], py[a]) for a in actors if js[a] != py[a]})
    w = ((d_bob.get("desk") or {}).get("stores") or [{}])[0].get("waits") or {}
    check("J15 the desk counts what waits for the actor named, per store, as the frontier has it (may attest, own "
          "pending, own challenged, and their sum); with no actor named neither the desk nor the reader shows any",
          w == {"actor": "bob", "roles": bob["roles"], "count": len(bob["attest"]) + len(bob["pending"]) + len(bob["challenged"]),
                "attest": len(bob["attest"]), "pending": len(bob["pending"]), "challenged": len(bob["challenged"])}
          and "waits" not in (((d_none.get("desk") or {}).get("stores") or [{}])[0]) and "frontier" not in plain, (w, d_none))

    srv, base = _serve(ROOT)
    try:
        own = {a: _reader(base, "--actor", a)[1].get("frontier") for a in ("codex", "claude")}
    finally:
        srv.shutdown()
    py_own = {a: _frontier_py(ROOT, a) for a in own}
    check("J15 differential on this repository's own store, served over HTTP: the reader's frontier for codex and for "
          "claude equals warrant.graph.frontier under the store's own rules",
          all(own[a] == py_own[a] and own[a] is not None for a in own),
          {a: (len((own[a] or {}).get("attest", [])), len(py_own[a]["attest"]), len((own[a] or {}).get("pending", [])), len(py_own[a]["pending"])) for a in own})


def _report(root):
    from warrant import repo as RP
    return RP.Repo(root).report()


def _acceptance_files(root):
    """The {path: blob} of every signed acceptance by the claims checker in the checkout's store."""
    from warrant import claims as CL
    return [f for xs in CL.acceptances(_report(root)).values() for _, f, _ in xs if isinstance(f, dict)]


VOICE = ROOT / "site" / "voice.mjs"
# words that read as a verdict: none may stand in a release block the desk draws, which verifies nothing (its one
# sentence «as published; not verified here», the member `note`, is the exception the case names)
VERDICT_WORDS = ("accept", "accepted", "settled", "verified", "valid", "eligible", "passed", "endorsed", "ok")


def _node_json(script, *args):
    """(exit status, JSON answer) of `node SCRIPT ARGS`."""
    p = subprocess.run([NODE, str(script), *args], capture_output=True, check=False, timeout=600)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, {"crash": p.stderr.decode(errors="replace")[-300:]}


def _shown_steps(html):
    """{step: [lines]} of object.html: each `<pre class="command" data-step="NAME"><code>...</code></pre>`, unescaped."""
    import html as H
    import re
    return {m.group(1): H.unescape(m.group(2)).split("\n")
            for m in re.finditer(r'<pre class="command" data-step="([a-z-]+)"><code>(.*?)</code></pre>', html, re.S)}


def _run_steps(steps, cwd, env, marker="@@STEP "):
    """Run `steps` [(name, [lines])] in ONE shell from `cwd`, as a reader runs them in order (each `cd` carries to the
    next line); {name: stdout of that step}, the exit status, stderr."""
    script = "set -e\n" + "".join(f"echo '{marker}{name}'\n" + "\n".join(lines) + "\n" for name, lines in steps)
    p = subprocess.run(["/bin/sh", "-c", script], cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=600)
    out, name = {}, None
    for line in p.stdout.splitlines(keepends=True):
        if line.startswith(marker):
            name = line[len(marker):].strip()
            out[name] = ""
        elif name is not None:
            out[name] += line
    return out, p.returncode, p.stderr


def browser_door_cases():
    """The door (site/voice.mjs; drawn by site/reader-page.mjs beside a lineage's effective version and leaf, and shown
    by site/object.html) and the desk's published releases (site/desk.mjs readReleases). The commands the pages show are
    run here, as shown, against this checkout's package: a voice said, published as a git repository, served, and read
    beside a publisher's store by the reader's CLI. No case drives a browser."""
    import re
    import urllib.parse
    pub = Repo()
    o = pub.entity("alice", "obligation@1", {"state": "open", "statement": "the claim", "serves": []})
    d = pub.entity("alice", "obligation@1", {"state": "done", "statement": "the claim", "serves": []}, lineage=o)
    pub.attest("bob", d)
    hostile = "<img src=x onerror=alert(1)> \u202e\u200b \"; touch pwned; $(touch pwned2) `touch pwned3` ' VERSION_ID"
    leaf = pub.entity("alice", "obligation@1", {"state": "done", "statement": hostile, "serves": []}, lineage=d)
    other = pub.entity("alice", "obligation@1", {"state": "open", "statement": "nobody spoke of this", "serves": []})

    rc, st = _node_json(VOICE, "--steps")
    steps = {x["step"]: x["lines"] for x in st.get("steps", [])}
    door = (ROOT / "site" / "object.html").read_text()
    shown = _shown_steps(door)
    check("J16 object.html shows the steps voice.mjs holds, word for word and in their order, each in a "
          "<pre class=\"command\" data-step>: install, say, publish, read",
          rc == 0 and list(shown) == list(steps) == ["install", "say", "publish", "read"] and shown == steps, (shown, steps))
    navs = {n: (ROOT / "site" / n).read_text() for n in ("reader.html", "desk.html", "index.html")}
    check("J16 object.html is linked from the reader's nav, the desk's and index.html's",
          all('<a href="object.html">Object</a>' in t.split("</nav>")[0] for t in navs.values()), [n for n, t in navs.items() if "object.html" not in t])
    lines = [l for ls in shown.values() for l in ls]
    check("J16 the voice is said with the released package, installed into an environment of the objector's own: a venv "
          "in the empty directory and the package by a specifier that admits 3.0.0a7 (the first with `warrant say`) and "
          "later, never the system's interpreter (PEP 668 refuses it), no `sudo`, no `--break-system-packages`, nothing "
          "piped into a shell; `warrant say` is the venv's, and no clone is needed before the read step",
          shown.get("install") == ["python3 -m venv .venv", '.venv/bin/pip install "warrant-graph>=3.0.0a7"']
          and shown.get("say") == ['.venv/bin/warrant say --store voices VERSION_ID "why this version is wrong"']
          and not any("sudo" in l or "--break-system-packages" in l or "|" in l for l in lines)
          and not any("git clone" in l for n in ("install", "say", "publish") for l in shown.get(n, []))
          and "3.0.0a6" not in door and "next release" not in door, shown)

    srv_pub, b_pub = _serve(pub.root)
    try:
        rc_t, tg = _node_json(VOICE, "--base", b_pub, "--lineage", o)
        _, tg_one = _node_json(VOICE, "--base", b_pub, "--lineage", other)
    finally:
        srv_pub.shutdown()
    blocks = tg.get("targets", [])
    fill = lambda v: [l.replace("VERSION_ID", v) for n in ("install", "say", "publish") for l in steps.get(n, [])]
    check("J16 the reader's block names the full id of its version: one for the effective version and one for the leaf "
          "when they differ, each command the step's with that id filled in; one block, effective and leaf, when they are "
          "one version",
          rc_t == 0 and [(b["version"], b["effective"], b["leaf"]) for b in blocks] == [(leaf, False, True), (d, True, False)]
          and all(b["commands"] == fill(b["version"]) for b in blocks)
          and [(b["version"], b["effective"], b["leaf"]) for b in tg_one.get("targets", [])] == [(other, True, True)], (blocks, tg_one))
    pieces = ["<img", "onerror", "\u202e", "\u200b", "touch pwned", "$(", "`"]
    dumped = json.dumps(blocks, ensure_ascii=False)
    bad_ids = ['x"; touch pwned', leaf.upper(), leaf[:63], leaf + "\n", leaf + " ", "$(touch pwned)" + leaf[14:]]
    refused = [_node_json(VOICE, "--version", x)[1].get("commands", "absent") for x in bad_ids]
    check("J16 hostile text in a lineage (markup, a direction override, a zero-width space, shell metacharacters, the "
          "placeholder's own name) reaches no command: the block is built from the version id alone, and an id that is "
          "not 64 lowercase hex (quoted, upper case, short, with a newline or a space after it) gives no command at all",
          not any(x in dumped for x in pieces) and "VERSION_ID" not in dumped and refused == [None] * len(bad_ids), (dumped[:400], refused))
    _, add1 = _node_json(VOICE, "--with", "https://a.example/s", "--add", " https://b.example/v ")
    _, add2 = _node_json(VOICE, "--with", "https://a.example/s", "--add", "https://a.example/s/")
    _, add3 = _node_json(VOICE, "--add", "javascript:alert(1)")
    _, add4 = _node_json(VOICE, "--add", "https://u:p@b.example/")
    check("J16 the block's field adds an address to the page's with= list: an http(s) address with no credentials, ending "
          "in /, once; anything else is named and not added",
          add1 == {"with": ["https://a.example/s", "https://b.example/v/"]} and add2 == {"with": ["https://a.example/s"]}
          and "not http(s)" in add3.get("why", "") and "with" not in add3 and "credentials" in add4.get("why", "") and "with" not in add4,
          (add1, add2, add3, add4))

    # the commands run: the block's (install, say, publish, for the effective version) and object.html's read step
    work = pub.home / "stranger"
    (work / "bin").mkdir(parents=True)
    (work / "home").mkdir()
    (work / "bin" / "python3").write_text(f"#!/bin/sh\nexec {shlex_quote(sys.executable)} \"$@\"\n")
    (work / "bin" / "python3").chmod(0o755)
    env = {"PATH": f"{work / 'bin'}:{os.environ.get('PATH', '')}", "HOME": str(work / "home"), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "a stranger", "GIT_AUTHOR_EMAIL": "stranger@example.org",
           "GIT_COMMITTER_NAME": "a stranger", "GIT_COMMITTER_EMAIL": "stranger@example.org", "LANG": "C.UTF-8"}
    eff = next((b for b in blocks if b["effective"]), {"commands": []})["commands"]
    # two substitutions, both this checkout for where a stranger gets the code: for PyPI, the venv's `warrant` is made
    # to run this checkout's package (no network, and the venv has no cryptography of its own); for GitHub, a clone of it
    clone = "git clone https://github.com/s0fractal/warrant.git"
    pip = '.venv/bin/pip install "warrant-graph>=3.0.0a7"'
    shim = (f"printf '#!/bin/sh\\nPYTHONPATH=%s exec %s -m warrant \"$@\"\\n' {shlex_quote(str(ROOT))} {shlex_quote(sys.executable)} "
            "> .venv/bin/warrant && chmod +x .venv/bin/warrant")
    swap = {clone: f"git clone -q {shlex_quote(str(ROOT))} warrant", pip: shim}
    ran = [swap.get(l, l) for l in eff]
    srvs, (b_pub2, b_voices) = _serve_many(pub.root, work / "voices")
    safe = re.compile(r"[A-Za-z0-9:/._-]+")
    try:
        assert all(safe.fullmatch(x) for x in (b_pub2, b_voices, o)), (b_pub2, b_voices)
        read = [swap.get(l, l).replace("STORE_URL", b_pub2).replace("VOICES_URL", b_voices).replace("LINEAGE_ID", o) for l in shown.get("read", [])]
        out, rc_run, err = _run_steps([("block", ran), ("read", read)], work, env)
        _, plain = _reader(b_pub2, "--lineage", o)
        _, listed = _reader(b_pub2, "--with", b_voices)
    finally:
        for x in srvs:
            x.shutdown()
    said = {}
    with contextlib.suppress(ValueError, IndexError):
        said = json.loads([l for l in out.get("block", "").splitlines() if l.startswith("{")][-1])
    seen = {}
    with contextlib.suppress(ValueError):
        seen = json.loads(out.get("read", ""))
    floor = (seen.get("lineage") or {}).get("floor", {})
    vs = (floor.get("outside") or {}).get("voices", [])
    rows = {x["id"]: x for x in listed.get("rows", [])}
    seed = work / "home" / ".config" / "warrant" / "commons" / "commons.seed"
    check("J16 the commands run as shown: in an empty directory the block's commands (a venv made, this checkout's "
          "package in place of PyPI's, the venv's `warrant say` against the effective version into ./voices, that "
          "directory committed as a git repository) and object.html's read step (a clone of this checkout in place of "
          "GitHub, the publisher served, the voices served beside it) exit 0; the voice is filed under key:<hex> with "
          "its seed in the objector's own home, and both substituted lines were among the commands",
          rc_run == 0 and said.get("actor", "").startswith("key:") and len(said.get("actor", "")) == 68 and seed.is_file()
          and (work / "voices" / ".git").is_dir() and (work / ".venv" / "bin" / "warrant").is_file()
          and pip in eff and clone in shown.get("read", []), (rc_run, err[-600:], said, sorted(out)))
    check("J16 the voice appears on the right lineage, uncounted, under its key: actor: the reader with --with the "
          "voices store lists it on that lineage's effective version, the store's state and reliance unchanged, no "
          "voice on another lineage",
          [(v["id"], v["actor"], v["kind"], v["target"], v["counted"], v["statement"]) for v in vs]
          == [(said.get("filed"), said.get("actor"), "challenge", d, False, "why this version is wrong")]
          and (floor.get("state"), floor.get("reliance")) == ((plain.get("lineage") or {}).get("floor", {}).get("state"), (plain.get("lineage") or {}).get("floor", {}).get("reliance"))
          and floor.get("reliance") == "ELIGIBLE" and rows.get(o, {}).get("outside") == 1 and rows.get(other, {}).get("outside") == 0,
          (vs, floor.get("reliance"), rows.get(o), rows.get(other)))

    # the desk's published releases: a served fixture, never the network
    tmp = Path(tempfile.mkdtemp())
    try:
        site = tmp / "site"
        roster = [{"name": "github-actions", "key": "1" * 64}, {"name": "<b>maintainer</b> \u202e", "key": "2" * 64}]
        good = {"format": "minds.published-bundles@1", "about": "the publisher's word", "chain": "refs/vars/heads/minds",
                "chain_tip": "f" * 40, "published": "2026-11-13T06:48:59Z",
                "projection": {"id": "c" * 64, "tip": "3" * 40, "witnesses": ["1" * 64, "9" * 64], "file": "bundles/p.json", "sha256": "a" * 64},
                "attestation": {"decision": "4" * 64, "statement": "minds release main@cec236 rules@1ca798; checks: lake build", "endorsers": ["1" * 64, "2" * 64],
                                "file": "bundles/a.json", "sha256": "7" * 64},
                "roster": roster, "rules": [{"id": "8" * 64, "file": "rules/8.wasm", "sha256": "8" * 64}],
                "verifier": {"main": "4" * 40, "file": "minds_verify.mjs", "sha256": "e" * 64}}
        missing = copy.deepcopy(good)
        del missing["attestation"]["endorsers"]
        files = {"good": json.dumps(good), "other": json.dumps(dict(good, format="minds.published-bundles@2")),
                 "notjson": "<html>not json</html>", "missing": json.dumps(missing), "fail": json.dumps(good)}
        for k, text in files.items():
            (site / k).mkdir(parents=True)
            (site / k / "index.json").write_text(text)
        srv, b = _serve_failing(site, "fail/index.json")
        lst = tmp / "list.json"
        lst.write_text(json.dumps([{"name": k, "base": b + k + "/", "release": "minds.published-bundles@1"} for k in files]
                                  + [{"name": "unknown kind", "base": b + "good/", "release": "something@1"}]))
        try:
            rc_d, dk = _node_json(DESK, "--list", str(lst))
            _, dk_addr = _node_json(DESK, "--list", str(lst), "--store", b + "good/")
            _, plan = _node_json(DESK, "--plan", "--list", str(lst))
            (tmp / "plain.json").write_text(json.dumps([{"name": "plain", "base": b + "good/"}]))
            _, dk_none = _node_json(DESK, "--list", str(tmp / "plain.json"))
        finally:
            srv.shutdown()
    finally:
        shutil.rmtree(tmp)
    rel = {x["name"]: x for x in (dk.get("desk") or {}).get("releases", [])}
    g = rel.get("good", {})
    index = b + "good/index.json"
    check("J16 a well-formed release index gives the statement, the chain and its tip, when published, the endorsers and "
          "the witnesses with the roster's names (null for a key it does not name; a name holding markup kept as text), "
          "the sentence «as published; not verified here» and the minds page's link with ?index=<the index address>",
          rc_d == 0 and g.get("read") is True and g.get("statement") == good["attestation"]["statement"] and g.get("chain_tip") == "f" * 40
          and g.get("chain") == good["chain"] and g.get("published") == good["published"] and g.get("index") == index
          and g.get("endorsers") == [{"key": "1" * 64, "name": "github-actions"}, {"key": "2" * 64, "name": roster[1]["name"]}]
          and g.get("witnesses") == [{"key": "1" * 64, "name": "github-actions"}, {"key": "9" * 64, "name": None}]
          and g.get("note") == "as published; not verified here"
          and g.get("verify") == "https://s0fractal.github.io/minds/?index=" + urllib.parse.quote(index, safe="-_.!~*'()"), g)
    whys = {k: rel.get(k, {}).get("why") or "" for k in ("other", "notjson", "missing", "fail", "unknown kind")}
    printed = ("statement", "chain_tip", "endorsers", "witnesses", "published", "verify", "note")
    check("J16 an index of another format, one that is not JSON, one with a member missing, HTTP 500 and an entry of a "
          "kind the desk does not read are each named with their reason and print no release; the others still answer",
          all(rel.get(k, {}).get("read") is False and not any(m in rel.get(k, {}) for m in printed) for k in whys)
          and "minds.published-bundles@2" in whys["other"] and "not JSON" in whys["notjson"]
          and "attestation.endorsers" in whys["missing"] and "HTTP 500" in whys["fail"] and "something@1" in whys["unknown kind"]
          and g.get("read") is True, whys)
    words = lambda x: {w for w in VERDICT_WORDS if re.search(rf"\b{w}\b", json.dumps({k: v for k, v in x.items() if k != "note"}).lower())}
    check("J16 no word of a verdict (" + ", ".join(VERDICT_WORDS) + ") in any release block's data, read or not, but the "
          "one sentence that says it is not verified here",
          len(rel) == 6 and not any(words(x) for x in rel.values()), {k: words(x) for k, x in rel.items()})
    js = ("import * as d from %s; import fs from 'node:fs'; const t = fs.readFileSync(%s, 'utf8');"
          " console.log(JSON.stringify({releases: d.parseReleases(t), stores: d.parseStores(t)}))") % (json.dumps(DESK.as_uri()), json.dumps(str(ROOT / "site" / "stores.json")))
    p = subprocess.run([NODE, "--input-type=module", "-e", js], capture_output=True, text=True, check=False, timeout=60)
    dflt = json.loads(p.stdout) if p.returncode == 0 else {}
    check("J16 the default list (site/stores.json) holds minds' latest release as a second kind of entry, {name, base, "
          "release}: its index is <base>index.json on minds' site branch, its format minds.published-bundles@1, and it "
          "keeps a base (a desk.mjs of an earlier release reads it as a store it cannot read, not as a broken list); "
          "parseStores leaves it out",
          [(x["index"], x["format"], x["why"]) for x in dflt.get("releases", [])]
          == [("https://raw.githubusercontent.com/s0fractal/minds/site/index.json", "minds.published-bundles@1", None)]
          and len(dflt.get("stores", [])) == 2, (p.stderr[-300:], dflt))
    check("J16 without release entries nothing changes: a list's stores are read as before (the plan names no release), "
          "a desk whose stores the address names shows no release, and the CLI answers no releases member for a list with none",
          plan == {"from": "list", "stores": [], "why": []} and "releases" not in (dk_addr.get("desk") or {})
          and len((dk_addr.get("desk") or {}).get("stores", [])) == 1
          and sorted(dk_none.get("desk") or {}) == ["actor", "from", "stores", "why"] and len(dk_none["desk"]["stores"]) == 1,
          (plan, dk_addr, dk_none))


# ---------------------------------------------------------------- J17: a watch list, frames, silence with its evidence

WATCH_EXIT = {"silent": 0, "touched": 3, "not established": 4}
SILENCE = "none is in the frame"
# what --mark answers without --watch (the `changes` member) over _changes_golden's fixture, before the watch list
# existed (site/reader.mjs at f02c7e7a): the sha256 of its canonical text with addresses and mark times made constant
CHANGES_GOLDEN = "7228e0c021d8318e04c4b997760232a18951a8f3a066794d1519f05d4b59ed8a"


def _watch_run(base, *args, reader=None):
    """(exit status, JSON answer, stdout as text) of `node site/reader.mjs --base BASE ...`."""
    p = subprocess.run([NODE, str(reader or READER), "--base", base, *args], capture_output=True, check=False, timeout=600)
    text = p.stdout.decode("utf-8", errors="replace")
    try:
        return p.returncode, json.loads(text), text
    except ValueError:
        return p.returncode, {"crash": p.stderr.decode(errors="replace")[-300:]}, text


def _machine(repo, lineages, per, tag):
    """`lineages` new obligation lineages by eve and `per` attests by dave on each: records nothing watched here rests
    on and that rest on nothing watched (filed in two writes: Repo.put rewrites the store each time)."""
    from world import KEYS
    es = []
    for k in range(lineages):
        repo.t += 1
        es.append(R.record("entity", "eve", repo.t, {"state": "open", "statement": f"machine {tag} {k}", "serves": []}, "obligation@1", None, [], None))
    ids = repo.store.extend(es, KEYS["eve"], repo.trust)
    ats = []
    for e in ids:
        for j in range(per):
            repo.t += 1
            ats.append(R.record("attest", "dave", repo.t, {"target": e, "verdict": "seen", "n": j}, None, None, [e], None))
    repo.store.extend(ats, KEYS["dave"], repo.trust)


def _closure_py(rep, roots):
    """{id: steps from the nearest version of a root} of the closure a frame is (site/reader.mjs frame (a)-(c)), breadth
    first, computed here from a Python report alone: out-edges whose relation is in warrant.graph.WALK, in-edges of
    relation attest or challenge, and every version of the lineage of any member."""
    import collections
    from warrant import graph as G
    out, into = {}, {}
    for a, rel, b in rep["graph"]["edges"]:
        if rel in G.WALK:
            out.setdefault(a, []).append(b)
        if rel in ("attest", "challenge"):
            into.setdefault(b, []).append(a)
    root_of = {v: L for L, x in rep["lineages"].items() for v in x["versions"]}
    dist, todo = {}, collections.deque()
    for L in roots:
        for v in rep["lineages"][L]["versions"]:
            if v not in dist:
                dist[v] = 0
                todo.append(v)
    while todo:
        cur = todo.popleft()
        near = out.get(cur, []) + into.get(cur, []) + (rep["lineages"][root_of[cur]]["versions"] if cur in root_of else [])
        for x in near:
            if x not in dist:
                dist[x] = dist[cur] + 1
                todo.append(x)
    return dist


def _frame_py(rep, roots, held, others=()):
    """(the frame's record ids, sorted; [(address, id)] of (d), sorted) of `roots`: the closure's ids that are records of
    the view, and each other store's attest or challenge (an edge of its own report's graph) on an id of the closure
    that the main store (`held`: the ids of its lines) does not hold. `others`: [(address, report)]."""
    dist = _closure_py(rep, roots)
    nodes = {n[0] for n in rep["graph"]["nodes"]}
    outside = sorted({(addr, a) for addr, orep in others for a, rel, t in orep["graph"]["edges"]
                      if rel in ("attest", "challenge") and t in dist and a not in held})
    return sorted(i for i in dist if i in nodes), outside


def _report_of(root):
    doc = json.loads((Path(root) / ".warrant" / "v3.json").read_text())
    return E.assess(ST.Store(Path(root) / ".warrant").snapshot(), doc["trust"], doc["profile"], None)


def _chain_ok(rep, chain, start, L, first=None):
    """Whether `chain` ([[from, rel, to]]) leads from `start` to a version of lineage L, each step an edge of the report's
    graph in WALK or two versions of one lineage ("same lineage"); `first`, when given, the set of edges the first step
    must be one of (another store's graph)."""
    from warrant import graph as G
    edges = {tuple(e) for e in rep["graph"]["edges"]}
    root_of = {v: x for x, lin in rep["lineages"].items() for v in lin["versions"]}
    node = start
    for k, (a, rel, b) in enumerate(chain):
        if node not in (a, b):
            return False
        if k == 0 and first is not None:
            ok = (a, rel, b) in first
        elif rel == "same lineage":
            ok = a in root_of and root_of[a] == root_of.get(b)
        else:
            ok = rel in G.WALK and (a, rel, b) in edges
        if not ok:
            return False
        node = b if node == a else a
    return node in rep["lineages"][L]["versions"]


def _frames_js(base, others=()):
    """{lineage: frame} of every lineage of the store at `base` (site/reader.mjs frame), the stores `others` read beside."""
    wm = ROOT / "site" / "warrant.mjs"
    js = ("import * as R from %s; import { nodeBackend } from %s; import fs from 'node:fs';"
          " const b = await nodeBackend(); const src = new Uint8Array(fs.readFileSync(%s));"
          " const store = await R.fetchStore(%s, b); const r = await R.read(store, R.receiver(store.doc, null), b, src);"
          " const others = %s; if (others.length) r.others = await R.readOthers(others, b, src);"
          " const out = {}; for (const L of Object.keys(r.rep.lineages)) out[L] = R.frame(r, [L]);"
          " process.stdout.write(JSON.stringify(out));") % (json.dumps(READER.as_uri()), json.dumps(wm.as_uri()), json.dumps(str(wm)),
                                                            json.dumps(base), json.dumps(list(others)))
    p = subprocess.run([NODE, "--input-type=module", "-e", js], capture_output=True, text=True, check=False, timeout=600)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout else {"crash": p.stderr[-300:]}


def _changes_golden(reader):
    """The sha256 of what `--mark` answers without `--watch` (the CLI's `changes` member) over J13's kinds of change,
    one mark each (an attest by no role, an acceptance at a commit, a counted challenge, a new lineage, a voice in another
    store read beside), with the addresses and the mark times made constant. Deterministic: the test keys and times."""
    pub, other = Repo(), Repo()
    a1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "the closure", "serves": []})
    a2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "the closure", "serves": []}, lineage=a1)
    b1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "the accepted one", "serves": []})
    b2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "the accepted one", "serves": []}, lineage=b1)
    pub.attest("bob", b2)
    srvs, (bp, bo) = _serve_many(pub.root, other.root)
    outs = []
    def step(change, *args):
        path = pub.home / f"golden-{len(outs)}.json"
        subprocess.run([NODE, str(reader), "--base", bp, "--write-mark", str(path), *args], capture_output=True, check=False, timeout=600)
        doc = json.loads(path.read_text())
        doc["at"] = 1
        path.write_text(json.dumps(doc))
        change()
        p = subprocess.run([NODE, str(reader), "--base", bp, "--mark", str(path), *args], capture_output=True, check=False, timeout=600)
        outs.append(json.loads(p.stdout).get("changes"))
    try:
        step(lambda: pub.attest("eve", b2))
        step(lambda: pub.attest("bob", a2, commit="c" * 40))
        step(lambda: pub.put("bob", "challenge", {"target": b2, "statement": "counted, and it stands"}, refs=[b2]))
        step(lambda: pub.entity("alice", "obligation@1", {"state": "open", "statement": "a new task", "serves": []}))
        step(lambda: other.put("carol", "challenge", {"target": a2, "statement": "from elsewhere"}, refs=[a2]), "--with", bo)
    finally:
        for s in srvs:
            s.shutdown()
    text = json.dumps(outs, sort_keys=True, ensure_ascii=False).replace(bp, "PUB/").replace(bo, "OTHER/")
    return hashlib.sha256(text.encode()).hexdigest(), outs


def _not_established(rc, out, text, reason):
    """Whether an answer is "not established" with a reason holding `reason`, exit 4, and no silence said anywhere."""
    w = out.get("watch") or {}
    return (rc == WATCH_EXIT["not established"] and w.get("outcome") == "not established" and any(reason in x for x in w.get("reasons", []))
            and "silent" not in text and SILENCE not in text)


def browser_watch_cases():
    """A watch list in the browser reader (site/reader.mjs frame, since, watched): what changed is said of the lineages
    the reader relies on, by their frames, as touched (with the witness: the new record, its store and a shortest chain
    of relations to the lineage), silent (with its numbers) or not established (with its reasons). The frame is held to
    a closure computed here from the Python report; the CLI's exit status is the gate (0 silent, 3 touched, 4 not
    established). No case drives a browser."""
    import re
    import contextlib as CTX
    import tools_test as TT
    hostile = "<img src=x onerror=alert(1)> \u202e\u200b \"; touch pwned; $(touch pwned2) `x`"
    pub, other = Repo(), Repo()
    goal = pub.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "a goal"})
    m1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "the dependency", "serves": []})
    m2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "the dependency", "serves": []}, lineage=m1)
    acc_m2 = pub.attest("bob", m2)
    ev = pub.blob(b"evidence held as a blob: an id the closure reaches that is no record")
    w1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": hostile, "serves": [goal], "evidence": [ev]})
    w2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": hostile, "serves": [goal]}, lineage=w1, requires=[m1])
    pub.attest("bob", w2)
    x1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "watched, never touched", "serves": []})
    y1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "not watched", "serves": []})
    both = f"{w1},{x1}"
    # a record both stores hold (bob's acceptance of m2, the same line): the main store's, never (d)
    shared = next(l for l in pub.store.lines() if ST._line_id(l)[0] == acc_m2)
    olines = other.dot / "records.jsonl"
    olines.write_bytes(b"".join(sorted(set(olines.read_bytes().splitlines(keepends=True)) | {shared}, key=ST._line_id)))
    (pub.home / "other-rules.json").write_text(json.dumps(dict(json.loads((pub.dot / "v3.json").read_text()),
                                                               profile=dict(pub.profile, roles=dict(pub.profile["roles"], **{"roadmap/acceptor": ["carol"]})))))
    srvs, (b_pub, b_oth, b_twin) = _serve_many(pub.root, other.root, pub.root)
    n = iter(range(100))
    def mark(*args):
        path = pub.home / f"watch-mark-{next(n)}.json"
        rc, out, _ = _watch_run(b_pub, "--write-mark", str(path), *args)
        assert path.exists(), (rc, out)
        return str(path)
    try:
        m_a = mark("--with", b_oth, "--watch", both)
        _machine(pub, 250, 3, "a")
        rc, out, text = _watch_run(b_pub, "--with", b_oth, "--mark", m_a, "--watch", both)
        w = out.get("watch") or {}
        rep = _report_of(pub.root)
        held = set(pub.store.snapshot().lines)
        size = len(_frame_py(rep, [w1, x1], held, [(b_oth, _report_of(other.root))])[0]) + len(_frame_py(rep, [w1, x1], held, [(b_oth, _report_of(other.root))])[1])
        total = len(held) + len(other.store.snapshot().lines)
        check("J17 the plan's check, silence: 1000 machine records filed outside the watched frames (250 new lineages, 750 "
              "attests on them) leave the watch list silent, exit 0, nothing touched, and the one sentence carries the "
              "numbers (1000 new, none in the frame, the frames' size and the stores') and the addresses read",
              rc == 0 and w.get("outcome") == "silent" and w.get("touched") == [] and w.get("new") == 1000 and w.get("in_frames") == 0
              and w.get("outside") == 1000 and w.get("frame") == size and w.get("records") == total and 0 < size < 40
              and w.get("line", "").startswith(f"1000 new record(s) at these addresses ({b_pub}, {b_oth}); {SILENCE} of the 2 lineage(s) you watch ({size} of {total} records)")
              and "completeness UNATTESTED" in w.get("line", ""), (rc, w, size, total))
        check("J17 unwatched change: the same 250 new lineages are listed store-wide (changes) while the watch list is silent",
              len((out.get("changes") or {}).get("listed", [])) == 250 and w.get("outcome") == "silent", (out.get("changes") or {}).get("line"))

        m_b = mark("--with", b_oth, "--watch", both)
        ch = pub.put("carol", "challenge", {"target": m2, "statement": "a counterexample"}, refs=[m2])
        rc, out, text = _watch_run(b_pub, "--with", b_oth, "--mark", m_b, "--watch", both)
        _, plain_out, _ = _watch_run(b_pub, "--with", b_oth, "--mark", m_b)
        w = out.get("watch") or {}
        rep = _report_of(pub.root)
        dist = _closure_py(rep, [w1])
        t = (w.get("touched") or [{}])[0]
        wit = t.get("witness") or [{}]
        check("J17 the plan's check, one record inside: a challenge on a version of a lineage a watched version requires "
              "(three steps away) touches exactly that watched lineage, exit 3; the witness names exactly that record, "
              "this store, and a shortest chain of the graph's relations from it to the watched lineage",
              rc == WATCH_EXIT["touched"] and w.get("outcome") == "touched" and [x.get("lineage") for x in w.get("touched", [])] == [w1]
              and w.get("quiet") == [x1] and [(x.get("id"), x.get("store"), x.get("kind")) for x in wit] == [(ch, b_pub, "challenge")]
              and wit[0].get("distance") == dist.get(ch) == len(wit[0].get("chain", [])) and dist.get(ch, 0) >= 2
              and _chain_ok(rep, wit[0].get("chain", []), ch, w1) and w.get("new") == 1 and w.get("in_frames") == 1 and w.get("outside") == 0
              and t.get("said") == "1 new record(s) in its frame", (rc, w.get("outcome"), t, dist.get(ch)))
        check("J17 the watch list changes nothing else: the `changes` member with --watch is the one without it",
              out.get("changes") == plain_out.get("changes") and "watch" not in plain_out and out.get("summary") == plain_out.get("summary"),
              (out.get("changes"), plain_out.get("changes")))
        bad = ["<img", "onerror", "\u202e", "\u200b", "touch pwned", "$("]
        check("J17 hostile text in a record's statement (markup, U+202E, U+200B, shell metacharacters) reaches the answer only "
              "as data: the touched lineage's title is the statement unchanged, and no sentence holds any of it",
              t.get("title") == hostile and not any(x in w.get("line", "") for x in bad)
              and not any(x in r for r in w.get("reasons", []) for x in bad), (t.get("title"), w.get("line")))

        m_c = mark("--with", b_oth, "--watch", both)
        voice = other.put("carol", "challenge", {"target": m2, "statement": "from elsewhere"}, refs=[m2])
        rc, out, _ = _watch_run(b_pub, "--with", b_oth, "--mark", m_c, "--watch", both)
        rc_alone, alone, _ = _watch_run(b_pub, "--mark", m_c, "--watch", both)
        w, wa = out.get("watch") or {}, alone.get("watch") or {}
        wit = ((w.get("touched") or [{}])[0].get("witness") or [{}])
        orep = _report_of(other.root)
        check("J17 a voice appearing in another store on a member of a frame touches the watched lineage, naming that store's "
              "address; its chain begins with the other store's own edge and is shortest",
              rc == WATCH_EXIT["touched"] and [x.get("lineage") for x in w.get("touched", [])] == [w1]
              and [(x.get("id"), x.get("store")) for x in wit] == [(voice, b_oth)] and wit[0].get("distance") == 1 + dist.get(m2, -9)
              and _chain_ok(rep, wit[0].get("chain", []), voice, w1, first={tuple(e) for e in orep["graph"]["edges"]}), (rc, w))
        check("J17 the same voice with that store not read: silent, exit 0, and the sentence names the one address read "
              "(this address), not the store that holds the voice",
              rc_alone == 0 and wa.get("outcome") == "silent" and wa.get("addresses") == [b_pub]
              and f"at this address ({b_pub})" in wa.get("line", "") and b_oth not in wa.get("line", ""), (rc_alone, wa))

        m_d = mark("--with", b_oth, "--watch", both)
        y2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "not watched", "serves": []}, lineage=y1)
        pub.attest("bob", y2)
        rc, out, _ = _watch_run(b_pub, "--with", b_oth, "--mark", m_d, "--watch", both)
        w = out.get("watch") or {}
        check("J17 unwatched change: a lineage outside the watch list moves (accepted done): silent for the watch list, exit 0, "
              "while the store-wide listing lists it",
              rc == 0 and w.get("outcome") == "silent" and w.get("new") == 2
              and [x.get("lineage") for x in (out.get("changes") or {}).get("listed", [])] == [y1], (rc, w, out.get("changes")))

        rep, orep = _report_of(pub.root), _report_of(other.root)
        held = set(pub.store.snapshot().lines)
        js = _frames_js(b_pub, [b_oth])
        py = {L: _frame_py(rep, [L], held, [(b_oth, orep)]) for L in rep["lineages"]}
        got = {L: (f.get("ids"), sorted((x["address"], x["id"]) for x in f.get("outside", []))) for L, f in js.items() if isinstance(f, dict)}
        check("J17 the frame of every lineage of the store (" + str(len(py)) + " of them) is the closure computed here from "
              "the Python report: (a) out-edges in warrant.graph.WALK, (b) in-edges attest and challenge, (c) every version "
              "of a member's lineage, the closure's records; and (d) the other store's attests and challenges on it",
              got == {L: (a, b) for L, (a, b) in py.items()} and len(py) > 250 and py[w1][1] == [(b_oth, voice)]
              and ch in py[w1][0] and goal in py[w1][0] and y1 not in py[w1][0] and py[y1][1] == []
              and ev in _closure_py(rep, [w1]) and ev not in py[w1][0] and acc_m2 in py[w1][0]
              and acc_m2 in {a for a, rel, _ in orep["graph"]["edges"] if rel == "attest"},
              (len(got), len(py), [L[:12] for L in py if got.get(L) != py[L]][:5]))

        # not established: each reason alone gives it, exit 4, and no silence is said anywhere in the output
        m_e = mark("--with", b_oth)
        cases = {
            "no mark": (_watch_run(b_pub, "--watch", w1), "no mark yet"),
            "other rules": (_watch_run(b_pub, "--mark", m_e, "--config", str(pub.home / "other-rules.json"), "--watch", w1), "other rules"),
            "another store": (_watch_run(b_twin, "--mark", m_e, "--watch", w1), "another store"),
            "a version, not a root": (_watch_run(b_pub, "--mark", m_e, "--watch", w2), f"{w2} is a version of lineage {w1}, not its root"),
            "no lineage here": (_watch_run(b_pub, "--mark", m_e, "--watch", "e" * 64), f"{'e' * 64} is not the root of a lineage"),
            "a store beside not read": (_watch_run(b_pub, "--mark", m_e, "--with", "http://127.0.0.1:9/", "--watch", w1), "could not be read now"),
            "an empty watch list": (_watch_run(b_pub, "--mark", m_e, "--watch"), "no lineage is watched"),
        }
        lines_path = pub.dot / "records.jsonl"
        whole = lines_path.read_bytes()
        try:
            lines_path.write_bytes(b"".join(l for l in whole.splitlines(keepends=True) if b"machine a 7\"" not in l))
            cases["a marked record gone"] = (_watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch", w1), "no longer served")
        finally:
            lines_path.write_bytes(whole)
        tampered = json.loads(Path(m_e).read_text())
        g = bytearray(base64.b64decode(tampered["stores"][b_pub]["groups"]))
        g[0] ^= 1
        tampered["stores"][b_pub]["groups"] = base64.b64encode(bytes(g)).decode()
        (pub.home / "watch-tampered.json").write_text(json.dumps(tampered))
        cases["a mark entry unverified"] = (_watch_run(b_pub, "--mark", str(pub.home / "watch-tampered.json"), "--with", b_oth, "--watch", w1), "could not be verified")
        rc_ok, ok_out, _ = _watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch", w1)
        check("J17 not established: no mark, a mark of other rules, a mark of another store, a watched version that is no "
              "root, an id that is no lineage here, a store beside this one not read now, an empty watch list, a marked "
              "record no longer served, a mark entry that does not verify: each gives \"not established\" with its reason, "
              "exit 4 (not touched's 3, not silence's 0), and neither the word silent nor the silence sentence anywhere "
              "in the output; the same mark and watch list with nothing wrong is silent",
              all(_not_established(*v, why) for v, why in cases.values()) and rc_ok == 0 and (ok_out.get("watch") or {}).get("outcome") == "silent",
              {k: (v[0], (v[1].get("watch") or {}).get("outcome"), (v[1].get("watch") or {}).get("reasons")) for k, (v, why) in cases.items() if not _not_established(*v, why)})

        malformed = [w1.upper(), w1[:63], w1 + "\n", w1 + " ", "", "$(touch pwned)" + w1[14:]]
        refused = [_watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch", x) for x in malformed]
        mixed = _watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch", f"{w1},{w1.upper()}")
        hexid = re.compile(r"[0-9a-f]{64}")
        check("J17 a malformed watch value (upper case hex, 63 characters, a trailing newline or space, empty, shell text) is "
              "refused by name, never dropped: not established, exit 4, the value itself in `refused` and its reason; beside "
              "a valid id the valid one is still watched, and every id watched is 64 lowercase hex",
              all(_not_established(*x, "the watched value") and [y["value"] for y in x[1]["watch"]["refused"]] == [v] and x[1]["watch"]["watch"] == []
                  for x, v in zip(refused, malformed))
              and _not_established(*mixed, "the watched value") and mixed[1]["watch"]["watch"] == [w1]
              and [y["value"] for y in mixed[1]["watch"]["refused"]] == [w1.upper()]
              and all(hexid.fullmatch(i) for i in mixed[1]["watch"]["watch"]),
              [(x[0], (x[1].get("watch") or {}).get("refused")) for x in refused])

        # the desk: per store, the same function, from the same kind of watch list the page keeps
        dk_dir = pub.home / "desk-marks"
        dk_dir.mkdir()
        watches = pub.home / "watches.json"
        watches.write_text(json.dumps({b_pub: [w1]}))
        _desk("--store", b_pub, "--marks", str(dk_dir), "--watches", str(watches), "--write-mark", b_pub)
        ch2 = pub.put("carol", "challenge", {"target": m1, "statement": "another counterexample"}, refs=[m1])
        rc_d, dk = _desk("--store", b_pub, "--marks", str(dk_dir), "--watches", str(watches))
        _, dk_plain = _desk("--store", b_pub, "--marks", str(dk_dir))
        blk = ((dk.get("desk") or {}).get("stores") or [{}])[0]
        check("J17 the desk says each store's watched answer with the reader's function: touched, the lineage named, from a "
              "watches file as the page keeps them ({address: [id]}); a desk with no watch list has no watch member",
              rc_d == 0 and (blk.get("watch") or {}).get("outcome") == "touched" and [x["lineage"] for x in blk["watch"]["touched"]] == [w1]
              and "watch" not in ((dk_plain.get("desk") or {}).get("stores") or [{}])[0] and ch2, (rc_d, blk.get("watch")))
    finally:
        for s in srvs:
            s.shutdown()

    # moved with no new record: a pinned file changed, compared with the floor the mark recorded
    with CTX.redirect_stdout(io.StringIO()):
        r, L = TT.drift_repo()
    srv, base, _ = _serve_counting(r.root)
    try:
        floors, bare = str(r.home / "pins-mark.json"), str(r.home / "pins-bare.json")
        _watch_run(base, "--pins", "--watch", L, "--write-mark", floors)
        _watch_run(base, "--pins", "--write-mark", bare)
        (r.root / "lib" / "code.py").write_text("X = 2\n")
        r.commit("the mutated file changes")
        rc, out, _ = _watch_run(base, "--pins", "--mark", floors, "--watch", L)
        nf = _watch_run(base, "--pins", "--mark", bare, "--watch", L)
    finally:
        srv.shutdown()
    w = out.get("watch") or {}
    t = (w.get("touched") or [{}])[0]
    check("J17 moved with no new record: pins compared, a pinned file changed since the mark: the watched claim is touched, "
          "exit 3, said as \"moved with no new record\", no witness, its reliance ELIGIBLE (the floor the mark recorded) "
          "then STALE now; with a mark that recorded no floor of it, not established, and why",
          rc == WATCH_EXIT["touched"] and t.get("lineage") == L and t.get("said") == "moved with no new record" and t.get("witness") == []
          and t.get("moved", {}).get("reliance") == ["ELIGIBLE", "STALE"] and w.get("new") == 0
          and "1 moved with no new record" in w.get("line", "") and _not_established(*nf, "recorded no floor"), (rc, w, nf[1].get("watch")))

    digest, outs = _changes_golden(READER)
    check("J17 without a watch list nothing changes: --mark answers the `changes` member byte for byte as before the watch "
          "list existed (the digest of J13's kinds of change, taken from site/reader.mjs at f02c7e7a)",
          digest == CHANGES_GOLDEN and len(outs) == 5 and all(o and o.get("listed") for o in outs), (digest, [o and o.get("line") for o in outs]))


# ---------------------------------------------------------------- J18: toward what you watch (the cone), and resolve

TOWARD_EXIT = 5
TOWARD_LINE = "toward what you watch"
# what --watch answers (the `watch` member without `toward`) and `summary` (without `cited`) over _watch_golden's
# fixture, taken from site/reader.mjs at f7e3637b (master before the cone): the sha256 of their canonical text with
# the addresses made constant
WATCH_GOLDEN = "60d95f1ae5fffa29d492f3dc75d89c23104dd4b0904cdd785db421b1b5b563c2"
SUMMARY_GOLDEN = "60896816c792cb5062918eed076db9ddef858edb64bab986f21dcb380af29281"       # without code and assessment: they name the runtime
RESOLVE_WORDS = {"PRESENT", "RESOLVED", "MISSING", "NOT_FETCHED"}


def _watch_golden(reader):
    """(sha256 of the `watch` members, sha256 of the `summary` members, the answers) of `reader` over J17's kinds of
    answer: silent with records outside the frame (quick and full), touched by a record three steps inside, touched by
    a voice in another store read beside and silent with that store not read, and three reasons for not established
    (no mark, a version watched, an empty list). `toward` and `cited` are left out: they are what J18 adds.
    Deterministic: the test keys and times, the addresses made constant."""
    pub, other = Repo(), Repo()
    goal = pub.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": "a goal"})
    m1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "the dependency", "serves": []})
    m2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "the dependency", "serves": []}, lineage=m1)
    pub.attest("bob", m2)
    ev = pub.blob(b"evidence held as a blob")
    w1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "watched", "serves": [goal], "evidence": [ev]})
    w2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "watched", "serves": [goal]}, lineage=w1, requires=[m1])
    pub.attest("bob", w2)
    o1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "rests on the watched one", "serves": [w1]})
    y1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "not watched", "serves": []})
    srvs, (bp, bo) = _serve_many(pub.root, other.root)
    n = iter(range(100))
    outs = []
    def mark(*args):
        path = pub.home / f"golden-watch-{next(n)}.json"
        _watch_run(bp, "--write-mark", str(path), *args, reader=reader)
        doc = json.loads(path.read_text())
        doc["at"] = 1
        path.write_text(json.dumps(doc))
        return str(path)
    def ask(*args):
        rc, out, _ = _watch_run(bp, *args, reader=reader)
        w = {k: v for k, v in (out.get("watch") or {}).items() if k != "toward"}
        # `code` and `assessment` name the runtime (impl-js codeIdentity: the node and OpenSSL versions), not what was
        # read: a digest over them holds on one machine only (CI's node is not a developer's)
        s = {k: v for k, v in (out.get("summary") or {}).items() if k not in ("cited", "code", "assessment")}
        outs.append([rc, w, s])
    try:
        m_a = mark("--with", bo, "--watch", w1)
        o2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "rests on the watched one", "serves": [w1]}, lineage=o1)
        pub.attest("bob", o2)
        pub.entity("alice", "obligation@1", {"state": "done", "statement": "not watched", "serves": []}, lineage=y1)
        ask("--with", bo, "--mark", m_a, "--watch", w1)
        ask("--full", "--with", bo, "--mark", m_a, "--watch", w1)
        m_b = mark("--with", bo, "--watch", w1)
        pub.put("carol", "challenge", {"target": m2, "statement": "a counterexample"}, refs=[m2])
        ask("--with", bo, "--mark", m_b, "--watch", w1)
        m_c = mark("--with", bo, "--watch", w1)
        other.put("carol", "challenge", {"target": m2, "statement": "from elsewhere"}, refs=[m2])
        ask("--with", bo, "--mark", m_c, "--watch", w1)
        ask("--mark", m_c, "--watch", w1)
        ask("--watch", w1)
        ask("--mark", m_c, "--watch", w2)
        ask("--mark", m_c, "--watch")
    finally:
        for s in srvs:
            s.shutdown()
    text = lambda k: json.dumps([[o[0], o[k]] for o in outs], sort_keys=True, ensure_ascii=False).replace(bp, "PUB/").replace(bo, "OTHER/")
    return hashlib.sha256(text(1).encode()).hexdigest(), hashlib.sha256(text(2).encode()).hexdigest(), outs


def _cone_py(rep, roots, held, others=()):
    """({id: steps from the nearest version of a root}, the cone's record ids sorted, [(address, id)] of the other
    stores' clause sorted) of `roots`, computed here from Python reports alone (site/reader.mjs cone): from every version
    of each root, the in-edges whose relation is in warrant.graph.WALK and every version of the lineage of any member,
    breadth first, graph nodes only; and each other store's record with an edge of its own graph (any WALK relation) to
    a member, unless the main store (`held`: the ids of its lines) holds it. Not warrant.graph.why: that walks in-edges
    alone, without the other versions of a member's lineage."""
    import collections
    from warrant import graph as G
    into = {}
    for a, rel, b in rep["graph"]["edges"]:
        if rel in G.WALK:
            into.setdefault(b, []).append(a)
    nodes = {n[0] for n in rep["graph"]["nodes"]}
    root_of = {v: L for L, x in rep["lineages"].items() for v in x["versions"]}
    dist, todo = {}, collections.deque()
    for L in roots:
        for v in rep["lineages"][L]["versions"]:
            if v not in dist and v in nodes:
                dist[v] = 0
                todo.append(v)
    while todo:
        cur = todo.popleft()
        near = into.get(cur, []) + (rep["lineages"][root_of[cur]]["versions"] if cur in root_of else [])
        for x in near:
            if x not in dist and x in nodes:
                dist[x] = dist[cur] + 1
                todo.append(x)
    outside = sorted({(addr, a) for addr, orep in others for a, rel, t in orep["graph"]["edges"]
                      if rel in G.WALK and t in dist and a not in held})
    return dist, sorted(dist), outside


def _js_eval(base, body, others=(), full=False):
    """The JSON `body` (JavaScript over `R`, the reader module, and `r`, the read of the store at `base` with `others`
    read beside) writes, or {"crash": ...}. A function the reader lacks is a value the case compares, not a crash."""
    wm = ROOT / "site" / "warrant.mjs"
    js = ("import * as R from %s; import { nodeBackend } from %s; import fs from 'node:fs';"
          " const b = await nodeBackend(); const src = new Uint8Array(fs.readFileSync(%s));"
          " const store = await R.fetchStore(%s, b, { full: %s }); const r = await R.read(store, R.receiver(store.doc, null), b, src);"
          " const others = %s; if (others.length) r.others = await R.readOthers(others, b, src);"
          " process.stdout.write(JSON.stringify(await (async () => { %s })()));") % (
        json.dumps(READER.as_uri()), json.dumps(wm.as_uri()), json.dumps(str(wm)), json.dumps(base), "true" if full else "false",
        json.dumps(list(others)), body)
    p = subprocess.run([NODE, "--input-type=module", "-e", js], capture_output=True, text=True, check=False, timeout=600)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout else {"crash": p.stderr[-300:]}


def _toward_of(out):
    """{lineage: item} of the `toward` member of a --watch answer ({} when there is none)."""
    t = (out.get("watch") or {}).get("toward") or {}
    return {x.get("lineage"): x for x in t.get("lineages", []) if isinstance(x, dict)}


def _resolve_py(rep, ids, held, blobs, others, mode):
    """{id: (state, where)} of `ids` as site/reader.mjs resolved() must say, computed here: PRESENT a line of this store
    (`held`) or a blob it fetched and hashed (`blobs`); else RESOLVED at the first other store read whose lines hold it
    (`others`: [(address, held ids)]); else NOT_FETCHED on a quick read (no blob of this store was asked for) and
    MISSING on a full one."""
    out = {}
    for i in ids:
        if i in held or i in blobs:
            out[i] = ("PRESENT", "here")
        elif any(i in h for _, h in others):
            out[i] = ("RESOLVED", next(a for a, h in others if i in h))
        else:
            out[i] = ("NOT_FETCHED", "here") if mode == "quick" else ("MISSING", None)
    return out


def browser_toward_cases():
    """Toward what you watch (site/reader.mjs cone, watched().toward) and where the bytes of a cited id are (resolved).
    The cone of a lineage is held to a closure computed here from the Python reports; toward lists the lineages of the
    cone, outside every watched frame, that are new or whose floor moved since the mark, and never changes the outcome
    (silence is about reliance, toward about attention); --toward-exit makes "silent with something toward" exit 5. The
    existing members of `watch` and of `summary` are held to digests taken from master. No case drives a browser."""
    import re
    import contextlib as CTX
    import tools_test as TT
    hostile = "<img src=x onerror=alert(1)> \u202e\u200b \"; touch pwned; $(touch pwned2) `x`"
    bad = ["<img", "onerror", "\u202e", "\u200b", "touch pwned", "$("]

    w_digest, s_digest, _ = _watch_golden(READER)
    check("J18 the cone changes nothing that was: what --watch answered (outcome, line, witnesses, counts, reasons) and "
          "the summary, over J17's kinds of answer (silent quick and full, touched inside, a voice read and not read, not "
          "established), are byte for byte master's (digests taken from site/reader.mjs at f7e3637b), `toward` and "
          "`cited` apart, and the summary's `code` and `assessment`, which name the runtime (the node version) and so "
          "hold on one machine only", (w_digest, s_digest) == (WATCH_GOLDEN, SUMMARY_GOLDEN), (w_digest, s_digest))

    pub, other = Repo(), Repo()
    goal = pub.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": hostile})
    o1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "serves the goal", "serves": [goal]})
    o3a = pub.entity("alice", "obligation@1", {"state": "open", "statement": "two steps away", "serves": [o1]})
    o3b = pub.entity("alice", "obligation@1", {"state": "done", "statement": "two steps away", "serves": [o1]}, lineage=o3a)
    p1 = pub.entity("alice", "pr-head@1", {"state": "open", "title": hostile, "serves": [o1]})
    # a lineage both in the goal's frame (the goal's second version refs m1a) and in its cone (m1b serves the goal)
    m1a = pub.entity("alice", "obligation@1", {"state": "open", "statement": "both rested on and resting", "serves": []})
    g2 = pub.entity("alice", "goal@1", {"state": "open", "key": "G1", "text": hostile}, lineage=goal, refs=[m1a])
    m1b = pub.entity("alice", "obligation@1", {"state": "done", "statement": "both rested on and resting", "serves": [goal]}, lineage=m1a)
    y1 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "unrelated", "serves": []})
    acc_o1 = pub.attest("dave", o1)
    # the other store: a record both stores hold (dave's attest on o1, the same line), a challenge on o1 of its own,
    # and an entity of its own citing the goal
    shared = next(l for l in pub.store.lines() if ST._line_id(l)[0] == acc_o1)
    olines = other.dot / "records.jsonl"
    olines.write_bytes(b"".join(sorted(set(olines.read_bytes().splitlines(keepends=True)) | {shared}, key=ST._line_id)))
    voice = other.put("carol", "challenge", {"target": o1, "statement": "from elsewhere"}, refs=[o1])
    far = other.entity("alice", "obligation@1", {"state": "open", "statement": "cites the goal from elsewhere", "serves": [goal]})
    (pub.home / "other-rules.json").write_text(json.dumps(dict(json.loads((pub.dot / "v3.json").read_text()),
                                                               profile=dict(pub.profile, roles=dict(pub.profile["roles"], **{"roadmap/acceptor": ["carol"]})))))
    srvs, (b_pub, b_oth, b_twin) = _serve_many(pub.root, other.root, pub.root)
    n = iter(range(100))
    def mark(*args):
        path = pub.home / f"toward-mark-{next(n)}.json"
        _watch_run(b_pub, "--write-mark", str(path), *args)
        return str(path)
    try:
        rep, orep = _report_of(pub.root), _report_of(other.root)
        held = set(pub.store.snapshot().lines)
        cones = _js_eval(b_pub, "const out = {}; for (const L of Object.keys(r.rep.lineages)) out[L] = typeof R.cone === 'function' ? R.cone(r, [L]) : null; return out;", [b_oth])
        py = {L: _cone_py(rep, [L], held, [(b_oth, orep)]) for L in rep["lineages"]}
        got = {L: (c.get("ids"), sorted((x.get("address"), x.get("id")) for x in c.get("outside", []))) if isinstance(c, dict) else c
               for L, c in cones.items()}
        check("J18 the cone of every lineage of the fixture (" + str(len(py)) + " of them) is the closure computed here from "
              "the Python reports: from every version, (a) in-edges in warrant.graph.WALK, (b) every version of a member's "
              "lineage, graph nodes only; and the other store's records with an edge to a member, named with its address, "
              "a record both stores hold being this store's alone",
              got == {L: (ids, out) for L, (_, ids, out) in py.items()} and len(py) == 6
              and o3a in py[goal][1] and o3b in py[goal][1] and p1 in py[goal][1] and m1b in py[goal][1] and y1 not in py[goal][1]
              and acc_o1 in py[goal][1] and (b_oth, acc_o1) not in py[goal][2]
              and (b_oth, voice) in py[goal][2] and (b_oth, far) in py[goal][2] and py[y1][2] == []
              and acc_o1 in {a for a, rel, _ in orep["graph"]["edges"]},
              (sorted(cones)[:3] if "crash" in cones else [(L[:12], got.get(L), py[L][1:]) for L in py if got.get(L) != py[L][1:]][:3]))

        # silent with something toward: an obligation two steps away accepted, a new one citing the goal, and an
        # unrelated lineage moving
        m_a = mark("--with", b_oth, "--watch", goal)
        dk_dir, watches = pub.home / "toward-desk-marks", pub.home / "toward-watches.json"
        dk_dir.mkdir()
        watches.write_text(json.dumps({b_pub: [goal]}))
        _desk("--store", b_pub, "--marks", str(dk_dir), "--watches", str(watches), "--write-mark", b_pub)
        acc_o3 = pub.attest("bob", o3b)
        o4 = pub.entity("alice", "obligation@1", {"state": "open", "statement": hostile, "serves": [g2]})   # the goal's second version: one step
        seen_o4 = pub.attest("dave", o4, verdict="seen")       # a record touching o4 that moves no floor
        y2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": "unrelated", "serves": []}, lineage=y1)
        pub.attest("bob", y2)
        rc, out, text = _watch_run(b_pub, "--with", b_oth, "--mark", m_a, "--watch", goal)
        rc5, out5, _ = _watch_run(b_pub, "--with", b_oth, "--mark", m_a, "--watch", goal, "--toward-exit")
        rep = _report_of(pub.root)
        dist = _cone_py(rep, [goal], set(pub.store.snapshot().lines))[0]
        w, tw = out.get("watch") or {}, _toward_of(out)
        near = lambda L: min(dist[v] for v in rep["lineages"][L]["versions"])
        chains = {L: any(_chain_ok(rep, x.get("chain", []), v, goal) for v in rep["lineages"][L]["versions"]) for L, x in tw.items()}
        floor = lambda L: {"state": rep["lineages"][L]["state"], "reliance": rep["lineages"][L]["reliance"]}
        t = w.get("toward") or {}
        check("J18 silent with work toward it: after the mark an obligation two steps from the watched goal is accepted, a "
              "new obligation citing the goal is filed and an unrelated lineage moves: the outcome stays silent, exit 0 "
              "(5 with --toward-exit), and toward lists exactly the two, each with its distance and a shortest chain of "
              "the graph's relations to the goal (a Python breadth-first search), new or not, its floor before and after "
              "and the new records touching it, newest first, the counts each lineage and record once; the unrelated "
              "one and the unchanged ones are absent",
              rc == 0 and rc5 == TOWARD_EXIT and w.get("outcome") == "silent" and sorted(tw) == sorted([o3a, o4])
              and tw[o3a].get("distance") == near(o3a) == 2 and tw[o4].get("distance") == near(o4) == 1
              and all(chains.values()) and all(len(x.get("chain", [])) == x.get("distance") for x in tw.values())
              and tw[o3a].get("new") is False and tw[o4].get("new") is True and tw[o4].get("before") is None
              and tw[o3a].get("before") == {"state": "open", "reliance": "ELIGIBLE"} and tw[o3a].get("after") == floor(o3a) == {"state": "done", "reliance": "ELIGIBLE"}
              and tw[o4].get("after") == floor(o4) and tw[o3a].get("records") == [acc_o3] and tw[o4].get("records") == sorted([o4, seen_o4])
              and all(x.get("watched") == goal for x in tw.values()) and tw[o3a].get("schema") == "obligation@1"
              and [x.get("lineage") for x in t.get("lineages", [])] == [o4, o3a] and t.get("counts") == {"lineages": 2, "records": 3},
              (rc, rc5, w.get("outcome"), {k[:8]: (x.get("distance"), x.get("records"), x.get("before"), x.get("after")) for k, x in tw.items()}, t.get("counts")))
        check("J18 toward is a second sentence: the silence sentence is said as before, and toward's own line names the "
              "lineages moved, their schemas, the new records and the address, and never the word silent",
              SILENCE in w.get("line", "") and t.get("line") == f"{TOWARD_LINE}: 2 lineage(s) that reach it moved at this address ({b_pub}) "
              "(2 obligation@1) through 3 new record(s)" and "silent" not in t.get("line", "silent"), (w.get("line"), t.get("line")))
        check("J18 hostile text in a title (markup, U+202E, U+200B, shell metacharacters) reaches toward only as data: the "
              "new obligation's title is its statement unchanged, and no sentence holds any of it",
              tw.get(o4, {}).get("title") == hostile and not any(x in t.get("line", "") + w.get("line", "") for x in bad), tw.get(o4, {}).get("title"))
        rc_d, dk = _desk("--store", b_pub, "--marks", str(dk_dir), "--watches", str(watches))
        _, dk_plain = _desk("--store", b_pub, "--marks", str(dk_dir))
        blk = ((dk.get("desk") or {}).get("stores") or [{}])[0].get("watch") or {}
        check("J18 the desk's watched line gains toward's count and sentence, the reader's own (the same function over the "
              "same store); a desk with no watch list has no watch member",
              rc_d == 0 and blk.get("outcome") == "silent" and blk.get("toward") == {"lineages": 2, "records": 3, "line": t.get("line")}
              and "watch" not in ((dk_plain.get("desk") or {}).get("stores") or [{}])[0], (rc_d, blk))
        rc_u, out_u, _ = _watch_run(b_pub, "--with", b_oth, "--mark", mark("--with", b_oth, "--watch", goal), "--watch", goal, "--toward-exit")
        check("J18 silent with nothing toward: exit 0 even with --toward-exit, an empty list, and toward's line says nothing moved",
              rc_u == 0 and (out_u.get("watch") or {}).get("outcome") == "silent" and ((out_u.get("watch") or {}).get("toward") or {}).get("lineages") == []
              and ((out_u.get("watch") or {}).get("toward") or {}).get("counts") == {"lineages": 0, "records": 0}
              and ((out_u.get("watch") or {}).get("toward") or {}).get("line") == f"{TOWARD_LINE}: no lineage that reaches it moved at this address ({b_pub})",
              (rc_u, (out_u.get("watch") or {}).get("toward")))

        # touched: an acceptance of the lineage that is in both the frame and the cone; a new lineage in the cone alone
        m_b = mark("--with", b_oth, "--watch", goal)
        acc_m = pub.attest("bob", m1b)
        o5 = pub.entity("alice", "obligation@1", {"state": "open", "statement": "another citing the goal", "serves": [goal]})
        rc, out, _ = _watch_run(b_pub, "--with", b_oth, "--mark", m_b, "--watch", goal)
        rc_t, _, _ = _watch_run(b_pub, "--with", b_oth, "--mark", m_b, "--watch", goal, "--toward-exit")
        w, tw = out.get("watch") or {}, _toward_of(out)
        wit = {x.get("id") for t in w.get("touched", []) for x in t.get("witness", [])}
        check("J18 a frame witness is not repeated under toward: the acceptance of a lineage both in the goal's frame and in "
              "its cone touches the goal (exit 3, with --toward-exit too) and that lineage is reported once, as the frame's; "
              "toward lists the new lineage of the cone alone, and no witness among its records",
              rc == rc_t == WATCH_EXIT["touched"] and w.get("outcome") == "touched" and wit == {acc_m} and sorted(tw) == [o5]
              and m1a not in tw and not any(i in wit for x in tw.values() for i in x.get("records", [])), (rc, rc_t, w.get("outcome"), wit, sorted(tw)))

        # not established: no toward member and no toward sentence, whatever the reason
        m_e = mark("--with", b_oth)
        cases = {
            "no mark": (_watch_run(b_pub, "--watch", goal), "no mark yet"),
            "other rules": (_watch_run(b_pub, "--mark", m_e, "--config", str(pub.home / "other-rules.json"), "--watch", goal), "other rules"),
            "another store": (_watch_run(b_twin, "--mark", m_e, "--watch", goal), "another store"),
            "a version, not a root": (_watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch", g2), "not its root"),
            "no lineage here": (_watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch", "e" * 64), "is not the root of a lineage"),
            "a store beside not read": (_watch_run(b_pub, "--mark", m_e, "--with", "http://127.0.0.1:9/", "--watch", goal), "could not be read now"),
            "an empty watch list": (_watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch"), "no lineage is watched"),
            "a malformed value": (_watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch", goal.upper()), "the watched value"),
        }
        pub.entity("alice", "obligation@1", {"state": "open", "statement": "new since the last mark", "serves": [goal]})
        lines_path = pub.dot / "records.jsonl"
        whole = lines_path.read_bytes()
        try:
            lines_path.write_bytes(b"".join(l for l in whole.splitlines(keepends=True) if b"another citing the goal" not in l))
            cases["a marked record gone"] = (_watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch", goal), "no longer served")
        finally:
            lines_path.write_bytes(whole)
        tampered = json.loads(Path(m_e).read_text())
        gd = bytearray(base64.b64decode(tampered["stores"][b_pub]["groups"]))
        gd[0] ^= 1
        tampered["stores"][b_pub]["groups"] = base64.b64encode(bytes(gd)).decode()
        (pub.home / "toward-tampered.json").write_text(json.dumps(tampered))
        cases["a mark entry unverified"] = (_watch_run(b_pub, "--mark", str(pub.home / "toward-tampered.json"), "--with", b_oth, "--watch", goal), "could not be verified")
        rc_ok, ok_out, _ = _watch_run(b_pub, "--mark", m_e, "--with", b_oth, "--watch", goal, "--toward-exit")
    finally:
        for s in srvs:
            s.shutdown()
    with CTX.redirect_stdout(io.StringIO()):
        r, L = TT.drift_repo()
    srv, base, _ = _serve_counting(r.root)
    try:
        bare = str(r.home / "toward-bare.json")
        _watch_run(base, "--pins", "--write-mark", bare)
        cases["pins with no floor"] = (_watch_run(base, "--pins", "--mark", bare, "--watch", L, "--toward-exit"), "recorded no floor")
    finally:
        srv.shutdown()
    quiet = lambda v: _not_established(*v[0], v[1]) and "toward" not in (v[0][1].get("watch") or {}) and TOWARD_LINE not in v[0][2]
    check("J18 not established, for every reason (no mark, other rules, another store, a version, no lineage here, a store "
          "beside not read, an empty list, a malformed value, a marked record gone, a mark entry unverified, pins with no "
          "floor recorded): exit 4, no toward member and no toward sentence anywhere (no partial news when the comparison "
          "could not be made); with nothing wrong the same mark gives toward, the new lineage in it, exit 5 with --toward-exit",
          all(quiet(v) for v in cases.values()) and rc_ok == TOWARD_EXIT and (ok_out.get("watch") or {}).get("outcome") == "silent"
          and len(_toward_of(ok_out)) == 1,
          {k: (v[0][0], (v[0][1].get("watch") or {}).get("outcome"), "toward" in (v[0][1].get("watch") or {})) for k, v in cases.items() if not quiet(v)})

    # resolve: where the bytes of a cited id are
    pub, other = Repo(), Repo()
    ev = pub.blob(b"evidence held as a blob of this store")
    elsewhere = other.entity("alice", "obligation@1", {"state": "open", "statement": "held elsewhere", "serves": []})
    nowhere = "ab" * 32
    cit = pub.entity("alice", "obligation@1", {"state": "open", "statement": hostile, "serves": [], "evidence": [ev]}, refs=[elsewhere, nowhere])
    cit2 = pub.entity("alice", "obligation@1", {"state": "done", "statement": hostile, "serves": []}, lineage=cit)
    srvs, (b_pub, b_oth) = _serve_many(pub.root, other.root)
    asked = f"{cit},{cit2},{ev},{elsewhere},{nowhere}"
    try:
        runs = {
            "quick": _watch_run(b_pub, "--resolve", asked),
            "full": _watch_run(b_pub, "--full", "--resolve", asked),
            "quick with": _watch_run(b_pub, "--with", b_oth, "--resolve", asked),
            "full with": _watch_run(b_pub, "--full", "--with", b_oth, "--resolve", asked),
            "full unread": _watch_run(b_pub, "--full", "--with", "http://127.0.0.1:9/", "--resolve", asked),
        }
        malformed = [cit.upper(), cit[:63], cit + "\n"]
        refused = [_watch_run(b_pub, "--resolve", x) for x in malformed]
        cites = _js_eval(b_pub, "return typeof R.citations === 'function' ? R.citations(r, %s) : null;" % json.dumps(cit), [b_oth], full=True)
    finally:
        for s in srvs:
            s.shutdown()
    held, oheld = set(pub.store.snapshot().lines), set(other.store.snapshot().lines)
    blobs = {p.name for p in (pub.dot / "blobs").iterdir()}
    def answers(k):
        res = (runs[k][1].get("resolve") or {})
        return {x.get("id"): (x.get("state"), x.get("where"), x.get("lineage")) for x in res.get("ids", []) if isinstance(x, dict)}
    def want(k):
        mode = "full" if k.startswith("full") else "quick"
        others = [(b_oth, oheld)] if k.endswith(" with") else []
        exp = _resolve_py(None, asked.split(","), held, blobs if mode == "full" else set(), others, mode)
        root = {cit: cit, cit2: cit, elsewhere: elsewhere}
        return {i: (s, b_pub if wh == "here" else wh, root.get(i) if s in ("PRESENT", "RESOLVED") else None) for i, (s, wh) in exp.items()}
    got = {k: answers(k) for k in runs}
    unread = (runs["full unread"][1].get("resolve") or {}).get("ids", [])
    check("J18 resolve: a record of this store is PRESENT (here, with its lineage); a record only in a store read beside "
          "(with=) is RESOLVED at that address with its lineage there; neither is MISSING on a full read; a blob of this "
          "store is NOT_FETCHED on a quick read (its bytes were not hashed) and PRESENT on a full one; without the other "
          "store the record held there is not found (NOT_FETCHED quick, MISSING full); completeness UNATTESTED",
          all(got[k] == want(k) for k in ["quick", "full", "quick with", "full with"])
          and got["quick"][ev][0] == "NOT_FETCHED" and got["full"][ev][0] == "PRESENT" and got["full with"][elsewhere] == ("RESOLVED", b_oth, elsewhere)
          and got["full with"][nowhere][0] == "MISSING" and got["full"][elsewhere][0] == "MISSING"
          and all((runs[k][1].get("resolve") or {}).get("completeness") == "UNATTESTED" for k in runs) and runs["quick"][0] == 0,
          {k: [(i[:8], got[k].get(i), want(k)[i]) for i in want(k) if got[k].get(i) != want(k)[i]] for k in ["quick", "full", "quick with", "full with"]})
    check("J18 resolve with a store beside that could not be read: the id held there is MISSING, never RESOLVED on a "
          "guess, and the answer names the unread address",
          [(x.get("state"), x.get("unread")) for x in unread if x.get("id") == elsewhere] == [("MISSING", ["http://127.0.0.1:9/"])]
          and all(x.get("state") != "RESOLVED" for x in unread), unread)
    hexid = re.compile(r"[0-9a-f]{64}\Z")
    check("J18 a malformed --resolve value (upper case hex, 63 characters, a trailing newline) is refused by name, never "
          "resolved or dropped: the value itself in `refused` with its reason, no id answered",
          all([y.get("value") for y in (x[1].get("resolve") or {}).get("refused", [])] == [v] and (x[1].get("resolve") or {}).get("ids") == []
              for x, v in zip(refused, malformed))
          and all(hexid.fullmatch(x.get("id", "")) for k in runs for x in (runs[k][1].get("resolve") or {}).get("ids", [])),
          [(x[1].get("resolve") or {}).get("refused") for x in refused])
    edges = [(rel, b) for a, rel, b in _report_of(pub.root)["graph"]["edges"] if a == cit]
    cited_py = lambda k: {w: sum(1 for b in {b for _, _, b in _report_of(pub.root)["graph"]["edges"]} if _resolve_py(None, [b], held, blobs if k.startswith("full") else set(), [(b_oth, oheld)] if k.endswith(" with") else [], "full" if k.startswith("full") else "quick")[b][0] == w)
                          for w in sorted(RESOLVE_WORDS)}
    check("J18 the floor summary counts every cited id (each target of the graph's edges) by its word, as computed here; "
          "the lineage page's citations of a version are its edges, each with its word",
          all((runs[k][1].get("summary") or {}).get("cited") == cited_py(k) for k in runs if k != "full unread")
          and isinstance(cites, list) and len(cites) == 2
          and sorted((x.get("rel"), x.get("id"), x.get("state")) for x in (next((v for v in cites if isinstance(v, dict) and v.get("version") == cit), {}).get("cites") or []))
          == sorted((rel, b, "PRESENT" if b in held or b in blobs else "RESOLVED" if b in oheld else "MISSING") for rel, b in edges),
          ({k: (runs[k][1].get("summary") or {}).get("cited") for k in runs}, {k: cited_py(k) for k in runs if k != "full unread"}, cites))
    check("J18 hostile text in a cited version's statement reaches no resolve answer: ids, words and addresses only",
          len((runs["full with"][1].get("resolve") or {}).get("ids", [])) == 5
          and not any(x in json.dumps(runs["full with"][1].get("resolve"), ensure_ascii=False) for x in bad), runs["full with"][1].get("resolve"))
    # What the page draws of a record: its invisible direction and width controls shown, not obeyed. Driven through
    # page.mjs's own el() over a document that only records what it is given (no browser).
    js = ("globalThis.document = {createElement: () => ({kids: [], set textContent(v) { this.t = v; }, append(k) { this.kids.push(k); },"
          " setAttribute(k, v) { (this.a ??= {})[k] = v; }})};"
          " const p = await import(%s); const h = process.argv[1];"
          " const n = p.el('p', {text: h, title: h}, h, ' tail');"
          " console.log(JSON.stringify({t: n.t, kids: n.kids, title: n.a.title, plain: typeof p.plain === 'function' ? p.plain('ok \\u2067x') : null}))"
          ) % json.dumps((ROOT / "site" / "page.mjs").as_uri())
    p = subprocess.run([NODE, "--input-type=module", "-e", js, hostile], capture_output=True, text=True, check=False, timeout=60)
    drawn = json.loads(p.stdout) if p.returncode == 0 else {"error": p.stderr[-300:]}
    controls = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
    check("J18 the page shows a record's direction and width controls instead of obeying them: text and string children "
          "drawn through el() carry \u27e8U+202E\u27e9 and \u27e8U+200B\u27e9 for the characters (a right-to-left override would "
          "redraw the rest of a statement backwards), every other character as it was; an attribute keeps the bytes",
          "error" not in drawn and not controls.search(drawn["t"]) and not controls.search("".join(drawn["kids"]))
          and "\u27e8U+202E\u27e9\u27e8U+200B\u27e9" in drawn["t"] and drawn["kids"][0] == drawn["t"] and drawn["kids"][1] == " tail"
          and drawn["t"].replace("\u27e8U+202E\u27e9", "\u202e").replace("\u27e8U+200B\u27e9", "\u200b") == hostile
          and drawn["title"] == hostile and drawn["plain"] == "ok \u27e8U+2067\u27e9x", drawn)


if __name__ == "__main__":
    sys.exit(main())
