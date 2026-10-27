#!/usr/bin/env python3
"""Warrant 3 core (docs/V3.md): one case per rule, on snapshots built in memory.

    python3 tests/v3_core_test.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from warrant import jcs as C                # noqa: E402
from warrant import keys as K               # noqa: E402
from warrant import bootstrap as B          # noqa: E402
from warrant import engine as E             # noqa: E402
from warrant import records as R            # noqa: E402
from warrant.store import Snapshot, Store   # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        FAILS.append(name)


class World:
    """Actors with keys, a line list, a trust and a profile: records are appended in memory."""

    def __init__(self, roles=None):
        self.keys = {a: K.Key.from_seed_hex(f"{i + 1:02x}" * 32) for i, a in enumerate(("alice", "bob", "carol", "eve"))}
        self.lines, self.blobs, self.heads, self.t = [], {}, {}, 100
        self.trust = {"warrant": "trust/3", "keys": {a: [k.public] for a, k in self.keys.items()}}
        self.roles = roles or {"schema/author": ["alice"], "claim/verifier": ["bob"], "roadmap/acceptor": ["bob"],
                               "pr/acceptor": ["bob"], "replayer": ["carol"], "roadmap/owner": ["carol"]}
        for s in B.SCHEMAS:
            self.put("alice", "schema", s)

    def put(self, actor, kind, body, schema=None, lineage=None, refs=(), guard=None, signed=True, at=None):
        self.t += 1
        r = R.record(kind, actor, self.t if at is None else at, body, schema, lineage, refs, guard,
                     prev=self.heads.get(actor) if signed else None)
        i, line = R.line(r, self.keys[actor] if signed else None)
        if signed:
            self.heads[actor] = i
        self.lines.append(line)
        return i

    def attest(self, actor, target, **body):
        return self.put(actor, "attest", dict({"verdict": "accept"}, **body, target=target), refs=[target])

    def claim(self, actor="alice", state="backed", lineage=None, guard="default", text="x"):
        g = B.SCHEMAS[0]["states"][state] if guard == "default" else guard
        body = {"state": state, "id": "SPEC-1-1", "source": "SPEC.md", "section": "1", "text": text,
                "witnesses": ["a_test"], "mutants": ["M1"]}
        return self.put(actor, "entity", body, "claim@1", lineage, guard=g)

    def report(self, roles=None, as_of=None):
        prof = {"warrant": "profile/3", "roles": roles or self.roles}
        return E.assess(Snapshot(self.lines, self.blobs), self.trust, prof, as_of)


def lineage_cases():
    w = World()
    c1 = w.claim()
    rep = w.report()
    check("L1 a guarded version is PENDING until a role holder attests",
          rep["versions"][c1]["guard"] == "PENDING" and rep["lineages"][c1]["reliance"] == "PENDING")
    w.attest("alice", c1)
    self_verifier = dict(w.roles, **{"claim/verifier": ["alice", "bob"]})
    check("L2 the version's own actor never meets its guard, even holding the role",
          w.report(roles=self_verifier)["versions"][c1]["guard"] == "PENDING")
    w.attest("bob", c1, verdict="reject")
    check("L3 an attest whose body misses the match does not count", w.report()["versions"][c1]["guard"] == "PENDING")
    w.attest("bob", c1)
    rep = w.report()
    check("L4 an attest by a role holder with the match meets it",
          rep["versions"][c1]["guard"] == "MET" and rep["lineages"][c1]["state"] == "backed"
          and rep["lineages"][c1]["reliance"] == "ELIGIBLE", rep["versions"][c1])
    other = w.report(roles=dict(w.roles, **{"claim/verifier": ["carol"]}))
    check("L5 same bytes, another receiver's roles: another verdict", other["versions"][c1]["guard"] == "PENDING")
    c2 = w.claim(lineage=c1, text="y")
    rep = w.report()
    check("L6 a pending successor leaves the earlier version effective",
          rep["lineages"][c1]["leaf"] == c2 and rep["lineages"][c1]["effective"] == c1)
    c3 = w.claim(lineage=c1, text="z")
    rep = w.report()
    check("L7 two successors of one version are a FORK; nothing is excluded",
          rep["lineages"][c1]["verdict"] == "FORK" and rep["lineages"][c1]["leaf"] is None
          and {c2, c3} <= set(rep["lineages"][c1]["versions"]) and rep["lineages"][c1]["reliance"] == "FORK")
    w2 = World()
    a = w2.claim()
    e = w2.claim(actor="eve", lineage=a)
    rep = w2.report()
    check("L8 a successor by another actor without a successors role is excluded (LINEAGE_NOT_AUTHOR)",
          e not in rep["versions"] and ["LINEAGE_NOT_AUTHOR", e] in [p[:2] for p in rep["problems"]])
    weak = w2.claim(guard=None)
    rep = w2.report()
    check("L9 a guard weaker than the schema's for its state makes the record INVALID",
          weak in rep["rejected"] and weak not in rep["versions"])
    broken = w2.put("alice", "entity", {"state": "unbacked", "id": "S", "source": "s", "section": "1", "text": "t",
                                        "witnesses": [], "mutants": []}, "claim@1", lineage="ab" * 32)
    check("L10 a successor of a record not in the view is excluded (LINEAGE_BROKEN)",
          broken not in w2.report()["versions"])


def release_cases():
    w = World()
    o = w.put("alice", "entity", {"state": "open", "statement": "o", "serves": []}, "obligation@1")
    b = w.put("alice", "entity", {"state": "open", "statement": "b", "serves": []}, "obligation@1", guard=R.guard(requires=[o]))
    rel = w.put("carol", "entity", {"state": "released", "statement": "o", "serves": []}, "obligation@1", o)
    rep = w.report()
    check("L11 the owner alone releases an obligation it is owed (Codex #2)",
          rel in rep["versions"] and rep["lineages"][o]["state"] == "released", rep["problems"])
    bd = w.put("alice", "entity", {"state": "done", "statement": "b", "serves": []}, "obligation@1", b, guard=B.SCHEMAS[2]["states"]["done"])
    w.attest("bob", bd)
    check("L12 a release is not delivery: what requires it stays pending", w.report()["versions"][bd]["guard"] == "PENDING")
    w2 = World()
    o2 = w2.put("alice", "entity", {"state": "open", "statement": "o", "serves": []}, "obligation@1")
    self_rel = w2.put("alice", "entity", {"state": "released", "statement": "o", "serves": []}, "obligation@1", o2)
    rep = w2.report()
    check("L13 the holder cannot release its own obligation", self_rel not in rep["versions"] and rep["lineages"][o2]["state"] == "open")


def schema_cases():
    w = World()
    w.put("eve", "schema", dict(B.SCHEMAS[0], name="evil@1", states={"backed": None}))
    x = w.put("eve", "entity", {"state": "backed"}, "evil@1")
    check("S1 a schema by an actor without schema/author does not count; its records are INVALID",
          "evil@1" not in w.report()["schemas"] and x in w.report()["rejected"])
    w.put("alice", "schema", dict(B.SCHEMAS[1]))
    rep = w.report()
    check("S2 two schema lineages naming one name: SCHEMA_CONFLICT", "goal@1" not in rep["schemas"]
          and "SCHEMA_CONFLICT" in [p[0] for p in rep["problems"]])
    w = World()
    bad = w.put("alice", "entity", {"state": "unbacked", "id": "S", "text": "t"}, "claim@1")
    check("S3 a body missing schema members is INVALID", bad in w.report()["rejected"])
    bad = w.put("alice", "entity", {"state": "nope", "id": "S", "source": "s", "section": "1", "text": "t",
                                    "witnesses": [], "mutants": []}, "claim@1")
    check("S4 a state the schema does not list is INVALID", bad in w.report()["rejected"])
    w = World()
    two = dict(w.roles, **{"schema/author": ["alice", "bob"]})
    c = w.claim(state="unbacked", guard=None)
    rep = E.assess(Snapshot(w.lines, {}), w.trust, {"warrant": "profile/3", "roles": two, "quorum": {"schema/author": 2}})
    check("S5 with a schema quorum of 2, one author's schemas do not count; nothing of theirs is valid",
          not rep["schemas"] and c in rep["rejected"] and len(rep["schemas_pending"]) == len(B.SCHEMAS))
    for i in list(rep["schemas_pending"]):
        w.attest("eve", i)
    rep = E.assess(Snapshot(w.lines, {}), w.trust, {"warrant": "profile/3", "roles": two, "quorum": {"schema/author": 2}})
    check("S6 an attest by an actor outside schema/author does not make up the quorum", not rep["schemas"])
    for i in list(rep["schemas_pending"]):
        w.attest("bob", i)
    rep = E.assess(Snapshot(w.lines, {}), w.trust, {"warrant": "profile/3", "roles": two, "quorum": {"schema/author": 2}})
    check("S7 a second schema author's accept completes the quorum", len(rep["schemas"]) == len(B.SCHEMAS) and c in rep["versions"])


def guard_cases():
    w = World()
    o1 = w.put("alice", "entity", {"state": "open", "statement": "first", "serves": []}, "obligation@1")
    g = R.guard(1, ["roadmap/acceptor"], B.ACCEPT)
    o2 = w.put("alice", "entity", {"state": "open", "statement": "second", "serves": []}, "obligation@1", guard=R.guard(requires=[o1]))
    d2 = w.put("alice", "entity", {"state": "done", "statement": "second", "serves": []}, "obligation@1", o2,
               guard=R.guard(1, ["roadmap/acceptor"], B.ACCEPT))
    w.attest("bob", d2)
    rep = w.report()
    check("G1 requires are inherited down a lineage and hold a closing version",
          rep["versions"][d2]["guard"] == "PENDING" and any(o1 in x for x in rep["versions"][d2]["waiting"]), rep["versions"][d2])
    d1 = w.put("alice", "entity", {"state": "done", "statement": "first", "serves": []}, "obligation@1", o1, guard=g)
    w.attest("bob", d1)
    rep = w.report()
    check("G2 ... and admit it once the required lineage is closed",
          rep["versions"][d2]["guard"] == "MET" and rep["lineages"][o2]["state"] == "done", rep["versions"][d2])
    w = World()
    w.put("alice", "schema", {"name": "simple@1", "fields": {"state": "str"}, "states": {"open": None, "done": None},
                              "closed": ["done"], "successors": {}})
    a = w.put("alice", "entity", {"state": "open"}, "simple@1")
    b = w.put("alice", "entity", {"state": "open"}, "simple@1", guard=R.guard(requires=[a]))
    bd = w.put("alice", "entity", {"state": "done"}, "simple@1", b)
    rep = w.report()
    check("G3 requires hold a closing version that has no guard (Codex #3)",
          rep["versions"][bd]["guard"] == "PENDING" and rep["lineages"][b]["state"] == "open", rep["versions"][bd])


def challenge_cases():
    w = World()
    h = w.put("alice", "entity", {"state": "open", "pr": 1}, "pr-head@1")
    h1 = w.put("alice", "entity", {"state": "head", "commit": "c" * 40, "tree": "d" * 40}, "pr-head@1", h,
               guard=B.SCHEMAS[3]["states"]["head"])
    f = {"statement": "P2 x", "severity": "P2", "what": "x", "where": [], "commit": "c" * 40, "tree": "d" * 40, "target": h1}
    thesis = w.put("eve", "challenge", dict(f), "finding@1", refs=[h1])
    counted = w.put("bob", "challenge", dict(f, what="y", statement="P2 y"), "finding@1", refs=[h1])
    w.attest("carol", thesis, verdict="reproduces", on=h1)
    rep = w.report()
    check("C1 a stranger's challenge is a thesis until a replayer reproduces it at its target",
          rep["challenges"][thesis]["counted"] and rep["challenges"][thesis]["why"] == "reproduced by a replayer")
    check("C2 a challenge by a role of the target's guard counts", rep["challenges"][counted]["counted"])
    w.attest("bob", h1)
    rep = w.report()
    check("C3 a standing challenge makes reliance CHALLENGED, never the guard verdict",
          rep["versions"][h1]["guard"] == "MET" and rep["lineages"][h]["reliance"] == "CHALLENGED")
    h2 = w.put("alice", "entity", {"state": "head", "commit": "e" * 40, "tree": "f" * 40, "answers": [counted]},
               "pr-head@1", h1, refs=[counted], guard=B.SCHEMAS[3]["states"]["head"])
    w.attest("bob", h2)
    rep = w.report()
    check("C4 an effective successor answers the challenges against its predecessor",
          not rep["challenges"][counted]["stands"] and rep["lineages"][h]["reliance"] == "ELIGIBLE")


def store_cases():
    w = World()
    c = w.claim()
    base = w.report()
    shuffled = list(reversed(w.lines)) + [w.lines[0], w.lines[3]]
    rep = E.assess(Snapshot(shuffled, {}), w.trust, {"warrant": "profile/3", "roles": w.roles})
    check("T1 a union merge's order and duplicate lines change nothing but `canonical`",
          rep["lineages"] == base["lineages"] and rep["versions"] == base["versions"] and not rep["canonical"])
    canon = sorted(set(w.lines), key=lambda x: R.rid(C.loads(x.rstrip(b"\n"))["record"]))
    check("T2 distinct lines sorted by id are canonical", Snapshot(canon, {}).canonical)
    check("T3 the snapshot digest ignores line order and duplicates", Snapshot(canon, {}).digest == Snapshot(shuffled, {}).digest)
    import json
    env = json.loads(w.lines[-1])
    env["sig"] = {"key": w.keys["eve"].id, "ed25519": w.keys["eve"].sign(R.SIG_DOMAIN + bytes.fromhex(c))}
    rep = E.assess(Snapshot(w.lines + [C.canon(env) + b"\n"], {}), w.trust, {"warrant": "profile/3", "roles": w.roles})
    check("T4 two lines of one id: authentic if one verifies, listed as a duplicate",
          c in rep["versions"] and c in rep["duplicates"])
    rep = E.assess(Snapshot([b'{"record":1}\n', b"not json\n"] + w.lines, {}), w.trust, {"warrant": "profile/3", "roles": w.roles})
    check("T5 a malformed line is listed, never aborts the read", len(rep["rejected"]) == 2 and c in rep["versions"])
    forged = json.loads(w.lines[-1])
    forged["sig"]["ed25519"] = "00" * 64
    one = E.assess(Snapshot(w.lines[:-1] + [C.canon(forged) + b"\n"], {}), w.trust, {"warrant": "profile/3", "roles": w.roles})
    check("T6 a bad signature rejects the record", c in one["rejected"])
    deep = b'{"record":' + b"[" * 30000 + b"]" * 30000 + b',"sig":null}\n'
    try:
        snap = Snapshot([deep] + w.lines + [w.lines[0]], {})
        rep = E.assess(snap, w.trust, {"warrant": "profile/3", "roles": w.roles})
        ok = len(rep["rejected"]) == 1 and c in rep["versions"] and not rep["canonical"]
    except RecursionError:
        ok = False
    check("T9 a line nested too deep to parse is listed, never aborts the read (nor the canonical order check)", ok)
    check("T10 an identical duplicate line is counted once", rep["basis"]["SIGNED"] == base["basis"]["SIGNED"]
          and c not in rep["duplicates"], rep["basis"])
    chain, prev = World(), None
    for n in range(200):         # each obligation's `done` requires the previous one's lineage
        prev = chain.put("alice", "entity", {"state": "done", "statement": f"o{n}", "serves": []}, "obligation@1",
                         guard=R.guard(1, ["roadmap/acceptor"], {"verdict": "accept"}, [prev] if prev else []))
    try:
        chain.report()
        ok = False
    except R.Invalid as e:
        ok = "require lineages" in str(e)
    except RecursionError:
        ok = False
    check("T11 requires nested beyond the limit refuse the store, never exhaust the stack", ok)
    with tempfile.TemporaryDirectory() as d:
        st = Store(d).init()
        k = w.keys["alice"]
        a1 = st.append(R.record("schema", "alice", 5, B.SCHEMAS[0]), k, w.trust)
        a2 = st.append(R.record("schema", "alice", 6, B.SCHEMAS[1]), k, w.trust)
        recs = {R.rid(C.loads(x)["record"]): C.loads(x)["record"] for x in st.file.read_bytes().split(b"\n") if x}
        check("T7 append takes prev from the actor's head", recs[a2]["prev"] == a1 and recs[a1]["prev"] is None)
        try:
            st.append(R.record("schema", "alice", 7, B.SCHEMAS[2]), k, w.trust, expect_head=a1)
            ok = False
        except ValueError:
            ok = True
        check("T8 --expect-head is a compare-and-swap", ok)


def chain_cases():
    w = World()
    one = World()
    ids = [one.put("bob", "attest", {"target": f"{n:02x}" * 32, "verdict": "x"}, refs=[f"{n:02x}" * 32], at=500)
           for n in range(6)]
    check("K2 the head follows the chain through records filed in one second", E.head(Snapshot(one.lines, {}), one.trust, "bob")["id"] == ids[-1],
          E.head(Snapshot(one.lines, {}), one.trust, "bob"))
    w.put("bob", "attest", {"target": "ab" * 32, "verdict": "x"}, refs=["ab" * 32])
    w.heads["bob"] = None
    w.put("bob", "attest", {"target": "cd" * 32, "verdict": "y"}, refs=["cd" * 32])
    check("K1 two genesis records of one actor are a chain fork, listed", any(f[0] == "bob" for f in w.report()["chains"]["forks"]))


def migration_cases():
    w = World(roles=None)
    w.roles["migrator"] = ["carol"]
    body = {"state": "unbacked", "id": "SPEC-1-1", "source": "SPEC.md", "section": "1", "text": "x",
            "witnesses": ["a_test"], "mutants": ["M1"]}
    r = R.record("entity", "bob", 50, body, "claim@1")
    mid, line = R.line(r, None)
    w.lines.append(line)
    rep = w.report()
    check("M1 an unsigned record no migration vouches for is rejected", mid in rep["rejected"])
    blob = C.canon({"map": [[mid, ["11" * 32], []]]})
    h = __import__("hashlib").sha256(blob).hexdigest()
    w.blobs[h] = blob
    w.put("carol", "attest", {"target": h, "verdict": "migrated"}, R.MIGRATION, refs=[h])
    rep = w.report()
    check("M2 a migration by a migrator vouches for the records its map lists, basis MIGRATED",
          mid in rep["versions"] and rep["basis"]["MIGRATED"] == 1, rep["rejected"].get(mid))
    rep = w.report(roles={k: v for k, v in w.roles.items() if k != "migrator"})
    check("M3 ... only for a receiver whose profile accepts the migrator", mid in rep["rejected"])
    env = json.loads(line)
    env["sig"] = {"key": w.keys["eve"].id, "ed25519": w.keys["eve"].sign(R.SIG_DOMAIN + bytes.fromhex(mid))}
    for lines in (w.lines + [C.canon(env) + b"\n"], [C.canon(env) + b"\n"] + w.lines):
        rep = E.assess(Snapshot(lines, w.blobs), w.trust, {"warrant": "profile/3", "roles": w.roles})
        check("M4 a bad-signature variant of a vouched record never revokes its basis (Codex #1), in either order",
              mid in rep["versions"] and rep["basis"]["MIGRATED"] == 1, rep["rejected"].get(mid))
    rep = E.assess(Snapshot([C.canon(env) + b"\n"] + w.lines[:-2] + w.lines[-1:], w.blobs), w.trust, {"warrant": "profile/3", "roles": w.roles})
    check("M5 ... and a bad signature alone is still no basis", mid in rep["rejected"])


def main():
    lineage_cases()
    schema_cases()
    guard_cases()
    release_cases()
    challenge_cases()
    store_cases()
    chain_cases()
    migration_cases()
    print(f"{'FAILED ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
