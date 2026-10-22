#!/usr/bin/env python3
"""The open circle of witnesses (tools/claims.py, tools/roadmap.py).

A: a key binding certifies itself (its key signs {actor, public, purpose}); `check`
admits it mechanically, first binding of an actor wins, and nobody judges who joins.
B: an acceptance is filed by an acceptor the duty names, of exactly a pending closure.
C: a counter blob that replays lowers a claim's backing whoever filed it; a claim's
lineage (supersede, retire, the document's next version) stays with its author.
D: WITNESSES.md is a ledger derived from the records; it grants nothing.

Each case builds a fixture repository (a store, bindings for claude, codex,
s0fractal and stranger, pins naming codex as acceptor) and asserts on data: refusal
codes, admitted bindings, table kinds, ledger rows, store bytes. Never on wording,
so a mutant is killed only when a rule stops holding. A counter's replay runs test
files; here it is stubbed (`replaying`), and the claims selftest replays real ones.

    python3 tests/circle_test.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from world import R, W, check, finish
from warrant import jcs as C
from warrant import keys as K
from warrant.store import Store, Trust

ROOT = Path(__file__).resolve().parents[1]


def _tool(name):
    impl = Path(os.environ["WARRANT_IMPL"]) / "tools" / name if os.environ.get("WARRANT_IMPL") else None
    path = impl if impl is not None and impl.is_file() else ROOT / "tools" / name
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name[:-3]] = mod
    spec.loader.exec_module(mod)
    return mod


CL = _tool("claims.py")
RM = _tool("roadmap.py")

ACTORS = ("claude", "codex", "s0fractal", "stranger")
PINS = {"claims": "warrant-claims/pins@1", "source": "SPEC.md", "sections": [], "sentences": {}, "headings": {},
        "owed_to": ["readers"], "accept_by": ["codex"]}
ROADMAP = {"roadmap": "warrant-roadmap/config@1", "owed_to": ["s0fractal"], "accept_by": ["codex"],
           "results_accept_by": ["codex"]}


def entry(actor, key, proof=None):
    return {"actor": actor, "public": key.public, "proof": CL.binding_proof(key, actor) if proof is None else proof}


def codes(problems):
    return [c for c, _ in problems]


class Fix:
    """A fixture repository with bound keys and claims filed by claude."""

    def __init__(self, pins=PINS):
        self.base = Path(tempfile.mkdtemp(prefix="warrant-circle-"))
        self.dir = self.base / "repo"
        (self.dir / ".warrant").mkdir(parents=True)
        Store(self.dir / ".warrant" / "store").init()
        (self.dir / ".warrant" / "claims.json").write_text(json.dumps(pins))
        (self.dir / ".warrant" / "roadmap.json").write_text(json.dumps(ROADMAP))
        self.keys = {a: W.Key.generate() for a in ACTORS}
        self.seeds = {}
        for a, k in self.keys.items():
            p = self.base / f"{a}.seed"
            p.write_text(k.seed_hex() + "\n")
            self.seeds[a] = str(p)
        self.write_trust([entry(a, k) for a, k in self.keys.items()])
        self.repo = CL.Repo(self.dir)
        self.store = Store(self.repo.store_dir)
        self.t = int(time.time())

    def write_trust(self, keys):
        (self.dir / ".warrant" / "trust.json").write_bytes(C.canon({"bindings": CL.BINDINGS, "keys": keys}))

    def at(self):
        self.t += 1
        return self.t

    def author(self, actor="claude"):
        return CL.Author(self.repo, self.keys[actor], actor, validate=False)

    def claim(self, cid, text="A rule holds.", backed=True, previous=None, counter=(), actor="claude"):
        return self.author(actor).claim(cid, text, ["records_test:A1"] if backed else [], ["M01"] if backed else [],
                                        previous=previous, because="fixture" if previous else None,
                                        unbacked_because=None if backed else "fixture: open", counter=counter)

    def file(self, actor, rtype, body):
        return self.store.put_record(R.record(rtype, actor, self.at(), body), self.keys[actor])

    def model(self):
        return CL.Model(self.repo.snapshot(), self.repo.trust())

    def node(self, cid):
        return self.model().current[cid]

    def counter(self, n, actor="stranger", challenge=True):
        """A counter blob against claim `n`, carried by `actor`'s challenge (or returned bare)."""
        h = self.store.put_json({"counter": CL.COUNTER, "claim": n.id, "against": n.tid, "patch": "",
                                 "passes": n.doc["witnesses"], "fails": ["records_test:A2"], "why": "fixture"})
        return self.file(actor, "challenge", R.challenge(n.tid, "fixture counter", [h], 0)) if challenge else h

    def files(self):
        return sorted((p.relative_to(self.dir).as_posix(), p.read_bytes()) for p in (self.dir / ".warrant").rglob("*")
                      if p.is_file())

    def run(self, tool, *argv, actor="claude"):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = tool.main(["--root", str(self.dir), argv[0], "--key", self.seeds[actor], "--actor", actor, *argv[1:]])
        return rc, err.getvalue().split()[1] if rc == 2 and err.getvalue().startswith("REFUSED ") else None

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)


@contextlib.contextmanager
def replaying(ok):
    """Stub the counter replay: `ok(h, p)` says whether counter blob `h` replays against claim `p`."""
    real = CL.replay_counter
    CL.replay_counter = lambda repo, snap, h, p: None if ok(h, p) else "fixture: does not replay"
    try:
        yield
    finally:
        CL.replay_counter = real


# ---------------------------------------------------------------- A: bindings

def binding_cases():
    k1, k2, k3 = W.Key.generate(), W.Key.generate(), W.Key.generate()
    doc = lambda *keys: {"bindings": CL.BINDINGS, "keys": list(keys)}       # noqa: E731
    adm, probs = CL.admit_bindings(doc(entry("claude", k1), entry("codex", k2)))
    f = Fix()
    rid = f.file("stranger", "challenge", R.challenge("ab" * 32, "fixture", [], None))
    check("B1", adm == [("claude", k1.public), ("codex", k2.public)] and not probs and rid in f.model().recs
          and sorted(a for a, _ in f.repo.trust().keys.values()) == sorted(ACTORS),
          "a binding whose proof is its own key's signature over {actor, public, purpose} is admitted, in order; "
          "a record its key signs is authentic", (adm, probs))
    f.close()

    bad = entry("claude", k1)
    bad["proof"] = ("0" if bad["proof"][0] != "0" else "1") + bad["proof"][1:]
    adm, probs = CL.admit_bindings(doc(bad))
    check("B2", adm == [] and codes(probs) == ["BINDING_PROOF_FORGED"], "a forged proof binds nothing", probs)

    other = {"actor": "victim", "public": k2.public, "proof": k1.sign(CL.binding_message("victim", k2.public))}
    adm, probs = CL.admit_bindings(doc(entry("mallory", k1), other))
    check("B3", adm == [("mallory", k1.public)] and codes(probs) == ["BINDING_PROOF_OTHER_KEY"],
          "a proof signed by another key of the file binds nothing, and says whose it is", probs)

    adm, probs = CL.admit_bindings(doc(entry("claude", k1), entry("claude", k2), entry("codex", k3)))
    check("B4", adm == [("claude", k1.public), ("codex", k3.public)] and codes(probs) == ["BINDING_ACTOR_TAKEN"],
          "the first binding of an actor wins; a second key for it is refused (rotation is out of scope)", probs)

    shapes = ["x\n", " x", "x ", "", "a" * 201, "é", "a\x00b"]
    got = [CL.admit_bindings(doc(entry(a, k1))) for a in shapes]
    ctrl = CL.admit_bindings(doc(entry("a" * 200, k1)))
    check("B5", all(adm == [] and codes(p) == ["BINDING_ACTOR_SHAPE"] for adm, p in got) and ctrl[0] == [("a" * 200, k1.public)],
          "an actor id failing SPEC-3-21 binds nothing (\\Z, white space, empty, length, NFC, control); 200 code points do",
          [codes(p) for _, p in got])

    adm, probs = CL.admit_bindings(doc(entry("claude", k1), entry("codex", k1)))
    check("B6", adm == [("claude", k1.public)] and codes(probs) == ["BINDING_KEY_TWICE"],
          "one key binds one actor", probs)

    legacy = Trust.document([("claude", k1.public)])
    noproof = doc({"actor": "claude", "public": k1.public})
    check("B7", codes(CL.admit_bindings(noproof)[1]) == ["BINDING_UNPROVEN"]
          and codes(CL.admit_bindings(legacy)[1]) == ["BINDINGS_SHAPE"] and CL.admit_bindings(legacy)[0] == []
          and CL.admit_bindings(legacy, legacy=True) == ([("claude", k1.public)], [])
          and codes(CL.admit_bindings(doc("claude"))[1]) == ["BINDING_SHAPE"],
          "an entry without a proof, a trust/2 file and a malformed entry admit nothing; trust/2 is read only as a base",
          CL.admit_bindings(noproof))

    rid = "cd" * 32
    domains = [k1.sign(K.sig_message(rid)), k1.sign(C.canon({"actor": "claude", "public": k1.public})),
               CL.binding_proof(k1, "codex")]
    got = [codes(CL.admit_bindings(doc(entry("claude", k1, p)))[1]) for p in domains]
    check("B8", got == [["BINDING_PROOF_FORGED"]] * 3,
          "a record signature, a proof without the purpose, or one for another actor id proves no binding", got)

    f = Fix()
    k = W.Key.generate()
    seed = f.base / "new.seed"
    seed.write_text(k.seed_hex() + "\n")
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc1 = CL.main(["--root", str(f.dir), "bind", "--key", str(seed), "--actor", "newcomer"])
        once = (f.dir / ".warrant" / "trust.json").read_bytes()
        rc2 = CL.main(["--root", str(f.dir), "bind", "--key", str(seed), "--actor", "newcomer"])
    again = (f.dir / ".warrant" / "trust.json").read_bytes()
    before = f.files()
    refused = [f.run(CL, "bind", actor="stranger")[1]]                     # stranger rebinds its own key: idempotent
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc3 = CL.main(["--root", str(f.dir), "bind", "--key", str(seed), "--actor", "claude"])
        rc4 = CL.main(["--root", str(f.dir), "bind", "--key", str(seed), "--actor", "newcomer\n"])
    adm, probs = f.repo.bindings()
    check("B9", rc1 == rc2 == 0 and once == again and ("newcomer", k.public) in adm and not probs
          and refused == [None] and rc3 == rc4 == 2 and f.files() == before,
          "bind appends the key's own proof, again is idempotent; another actor's id or a bad id is refused, nothing written",
          (rc1, rc2, rc3, rc4, refused, probs))
    legacy_dir = f.dir / ".warrant" / "trust.json"
    legacy_dir.write_bytes(C.canon(Trust.document([("claude", f.keys["claude"].public)])))
    f.run(CL, "bind", actor="claude")
    adm, probs = f.repo.bindings()
    check("B10", adm == [("claude", f.keys["claude"].public)] and not probs
          and codes(CL.bindings_kept([("claude", k1.public)], [("claude", k2.public)], "0" * 40)) == ["BINDING_REMOVED"]
          and CL.bindings_kept([("claude", k1.public)], [("codex", k3.public), ("claude", k1.public)], "0" * 40) == [],
          "bind turns a trust/2 entry into one with its proof; a binding admitted at the base and not now is refused",
          (adm, probs))
    forged = entry("mallory", W.Key.generate(), proof="00" * 64)
    f.write_trust([entry(a, k) for a, k in f.keys.items()] + [forged])
    got = codes(CL.check(f.repo))
    check("B11", "BINDING_PROOF_FORGED" in got and "mallory" not in {a for a, _ in f.repo.trust().keys.values()},
          "check refuses a binding it does not admit, and the trust it uses leaves it out", got)
    guest = W.Key.generate()
    local = f.base / "local.json"
    local.write_bytes(C.canon(Trust.document([("guest", guest.public)])))
    without = {a for a, _ in f.repo.trust().keys.values()}
    os.environ[CL.LOCAL_TRUST] = str(local)
    try:
        with_local = {a for a, _ in f.repo.trust().keys.values()}
        listed = f.repo.bindings()[0]
    finally:
        os.environ.pop(CL.LOCAL_TRUST)
    check("B12", "guest" in with_local and "guest" not in without and ("guest", guest.public) not in listed,
          "a receiver's own trust file ($WARRANT_CLAIMS_TRUST) adds its bindings to the trust it uses, not to the "
          "repository's bindings", (with_local, without))
    f.close()


# ---------------------------------------------------------------- B: acceptance

def accept_cases():
    f = Fix()
    f.claim("SPEC-1-1")
    f.claim("SPEC-1-2")
    f.claim("SPEC-1-3", backed=False)
    f.claim("SPEC-1-4")
    n = f.node("SPEC-1-1")
    f.file("s0fractal", "accept", R.accept(n.tid, 0, [f.store.put_blob(b"another evidence set")]))
    rc, _ = f.run(CL, "accept", "--claim", "SPEC-1-1", actor="codex")
    m = f.model()
    acc = [r for r in m.recs.values() if r["type"] == "accept" and r["actor"] == "codex"]
    rep = CL.assessment(m.snap, f.repo.trust())
    shown = CL.disposition(rep, n, CL.acceptors(m.recs, CL.accept_index(m.recs), n.tid, 0))
    check("K1", rc == 0 and len(acc) == 1 and acc[0]["actor"] == "codex"
          and acc[0]["body"] == R.accept(n.tid, 0, n.rec["body"]["closes"][0]["evidence"])
          and rep["duties"][n.doc["duty"]]["disposition"] == "DISCHARGED" and shown == "DISCHARGED (accepted by codex)",
          "accept files codex's acceptance of exactly the claim's closure; the view names the acceptor", (rc, shown))

    before = f.files()
    got = [f.run(CL, "accept", "--claim", "SPEC-1-2", actor="stranger")[1],
           f.run(CL, "accept", "--claim", "SPEC-1-2", actor="claude")[1],
           f.run(CL, "accept", "--claim", "SPEC-1-1", actor="codex")[1],
           f.run(CL, "accept", "--claim", "SPEC-1-3", actor="codex")[1],
           f.run(CL, "accept", "--claim", "SPEC-9-9", actor="codex")[1],
           f.run(CL, "accept", "--claim", "SPEC-1-2", "--claim", "SPEC-1-1", actor="codex")[1]]
    check("K2", got == ["NOT_AN_ACCEPTOR", "NOT_AN_ACCEPTOR", "NOT_PENDING", "NOT_A_CLOSURE", "NOT_A_CLOSURE", "NOT_PENDING"]
          and f.files() == before,
          "a stranger or the holder is no acceptor; an accepted, unbacked or unknown claim is not pending; a batch with "
          "one refusal writes nothing", got)

    f.write_trust([entry(a, k) for a, k in f.keys.items() if a != "codex"])
    before = f.files()
    rc, _ = f.run(CL, "accept", "--claim", "SPEC-1-2", actor="codex")
    check("K3", rc == 2 and f.files() == before,
          "an actor whose key is not admitted files nothing", rc)
    f.write_trust([entry(a, k) for a, k in f.keys.items()])

    p2 = f.node("SPEC-1-2")
    f.counter(p2)
    before = f.files()
    with replaying(lambda h, p: True):
        refused = f.run(CL, "accept", "--claim", "SPEC-1-2", actor="codex")[1]
        unchanged = f.files() == before
        rc_all, _ = f.run(CL, "accept", "--all", actor="codex")
    after = sorted(r["body"]["transition"] for r in f.model().recs.values() if r["type"] == "accept" and r["actor"] == "codex")
    check("K4", refused == "COUNTERED" and unchanged and rc_all == 0 and after == sorted([n.tid, f.node("SPEC-1-4").tid]),
          "a claim a replaying counter lowers is not accepted, and --all leaves it out", (refused, rc_all, len(after)))
    with replaying(lambda h, p: False):
        rc = f.run(CL, "accept", "--claim", "SPEC-1-2", actor="codex")[0]
    check("K5", rc == 0, "a counter that does not replay does not stop the acceptance", rc)
    f.close()

    f = Fix(dict(PINS, accept_by=["codex", "s0fractal"]))
    f.claim("SPEC-1-1")
    n = f.node("SPEC-1-1")
    first = f.run(CL, "accept", "--claim", "SPEC-1-1", actor="codex")[0]
    before = f.files()
    twice = f.run(CL, "accept", "--claim", "SPEC-1-1", actor="codex")[1]
    unchanged = f.files() == before
    second = f.run(CL, "accept", "--claim", "SPEC-1-1", actor="s0fractal")[0]
    m = f.model()
    shown = CL.disposition(CL.assessment(m.snap, f.repo.trust()), n, CL.acceptors(m.recs, CL.accept_index(m.recs), n.tid, 0))
    check("K7", first == 0 and twice == "NOT_PENDING" and unchanged and second == 0
          and shown == "DISCHARGED (accepted by codex, s0fractal)",
          "with two acceptors, one who accepted has nothing left to accept; the other's acceptance discharges", (twice, shown))
    f.close()

    f = Fix()
    rm = RM.Roadmap(f.dir)
    f.run(RM, "goal", "--id", "G1", "--text", "Witnesses widen.")
    d = RM.Writer(rm, f.keys["claude"], "claude").oblige("A ledger exists.", "G1")
    RM.Writer(rm, f.keys["claude"], "claude").done(d, "the ledger is built", ["s0fractal/warrant#1"])
    before = f.files()
    got = [f.run(RM, "accept", "--duty", d, actor="stranger")[1], f.run(RM, "accept", "--duty", d, actor="claude")[1]]
    unchanged = f.files() == before
    rc, _ = f.run(RM, "accept", "--duty", d, actor="codex")
    node = RM.path_data(rm.model(), "G1")["obligations"][0]
    again = f.run(RM, "accept", "--duty", d, actor="codex")[1]
    f.claim("SPEC-1-1")
    claim_duty = f.run(RM, "accept", "--duty", "SPEC-1-1", actor="codex")[1]
    check("K6", got == ["NOT_AN_ACCEPTOR", "NOT_AN_ACCEPTOR"] and unchanged and rc == 0 and node["state"] == "DISCHARGED"
          and node["accepted_by"] == ["codex"] and "[DISCHARGED · accepted by codex]" in RM.render_path(RM.path_data(rm.model(), "G1"))
          and again == "NOT_PENDING" and claim_duty == "NOT_AN_OBLIGATION",
          "roadmap accept: only the named acceptor, of the filed closure; the path shows who accepted", (got, node, again))
    f.close()


# ---------------------------------------------------------------- C: lineage and counters

def lineage_cases():
    f = Fix()
    f.claim("SPEC-1-1")
    n = f.node("SPEC-1-1")
    st = f.store
    text = "A rule holds, says the stranger."
    st.put_blob(text.encode())
    duty = f.file("stranger", "duty", R.duty("stranger", CL.statement_for("SPEC-1-1", text), ["readers"], {"attest": {}},
                                             accept_by=["codex"], subject=CL.sha(text)))
    doc = {"schema": CL.CLAIM, "id": "SPEC-1-1", "source": "SPEC.md", "section": "1", "text": text, "kind": "normative",
           "duty": duty, "witnesses": n.doc["witnesses"], "mutants": n.doc["mutants"], "reason": None, "because": "mine now",
           "previous": {"transition": n.tid, "duty": n.doc["duty"], "statement_sha256": CL.sha(n.doc["text"])}}
    h = st.put_json(doc)
    f.file("stranger", "transition", R.transition("ATTESTED", [h], closes=[R.item(duty, "discharge", [h])], established=[text],
                                                  supersedes=[n.tid]))
    m = f.model()
    check("L1", "LINEAGE_NOT_AUTHOR" in codes(m.problems) and m.current["SPEC-1-1"].tid == n.tid,
          "a supersession by another actor than the claim's author is refused and does not become current", m.problems)

    f.claim("SPEC-1-2")
    n2 = f.node("SPEC-1-2")
    ev = st.put_blob(b"gone")
    ch = f.file("stranger", "challenge", R.challenge(n2.tid, "gone", [ev], 0))
    rdoc = {"schema": CL.RETIRE, "id": "SPEC-1-2", "because": "gone", "counter": ev, "challenge": ch,
            "previous": {"transition": n2.tid, "duty": n2.doc["duty"], "statement_sha256": CL.sha(n2.doc["text"])}}
    rh = st.put_json(rdoc)
    f.file("stranger", "transition", R.transition("ATTESTED", sorted({ev, ch, rh}), established=["retired"], supersedes=[n2.tid]))
    m = f.model()
    check("L2", m.current["SPEC-1-2"].tid == n2.tid and not m.current["SPEC-1-2"].retired
          and sum(c == "LINEAGE_NOT_AUTHOR" for c in codes(m.problems)) == 2,
          "a retirement by another actor than the claim's author is refused", m.problems)

    au = f.author()
    au.file_document([{"heading": "# Title"}, "\n"], "fixture", f.at())
    d = CL.Document(f.model())
    dh = st.put_json({"schema": CL.DOCUMENT, "source": "SPEC.md", "parts": d.current["parts"], "because": "mine",
                      "previous": {"transition": d.tid, "sha256": d.nodes[d.tid][1]}})
    f.file("stranger", "transition", R.transition("ATTESTED", [dh], residual=[CL.DOCUMENT_RESIDUAL], supersedes=[d.tid]))
    d2 = CL.Document(f.model())
    refused = []
    for call in (lambda: f.author("stranger").claim("SPEC-1-1", "x", ["records_test:A1"], ["M01"], previous=f.node("SPEC-1-1"),
                                                    because="mine"),
                 lambda: f.author("stranger").retire("SPEC-1-1", "mine", ev),
                 lambda: f.author("stranger").file_document(d.current["parts"], "mine", f.at())):
        before = f.files()
        try:
            call()
            refused.append(None)
        except CL.Refused as e:
            refused.append(e.code if f.files() == before else "WROTE")
    check("L3", d2.tid == d.tid and "LINEAGE_NOT_AUTHOR" in codes(d2.problems) and refused == ["LINEAGE_NOT_AUTHOR"] * 3,
          "the document's next version is its author's; the tool refuses another author's supersede, retire and "
          "document version before writing", (d2.problems, refused))

    p = f.node("SPEC-1-1")
    before = f.files()
    cf = f.base / "counter.json"
    cf.write_text(json.dumps({"counter": CL.COUNTER, "claim": "SPEC-1-1", "against": p.tid, "patch": "",
                              "passes": p.doc["witnesses"], "fails": ["records_test:A2"], "why": "x"}))
    with replaying(lambda h, q: False):
        no = f.run(CL, "challenge", "--claim", "SPEC-1-1", "--because", "x", "--counter-file", str(cf), actor="stranger")
    unchanged = f.files() == before
    with replaying(lambda h, q: True):
        yes = f.run(CL, "challenge", "--claim", "SPEC-1-1", "--because", "x", "--counter-file", str(cf), actor="stranger")
    chs = [r for r in f.model().recs.values() if r["type"] == "challenge" and r["body"]["target"] == p.tid]
    check("L4", no == (2, "COUNTER_NOT_REPLAYED") and unchanged and yes == (0, None) and len(chs) == 1
          and chs[0]["actor"] == "stranger" and len(chs[0]["body"]["evidence"]) == 1 and chs[0]["body"]["item"] == 0,
          "challenge files a stranger's counter only if it replays; refused, it writes no blob", (no, yes))
    before = f.files()
    rc = f.run(CL, "retire", "--id", "SPEC-1-1", "--because", "mine", "--counter-file", str(cf), actor="stranger")
    check("L11", rc == (2, "LINEAGE_NOT_AUTHOR") and f.files() == before,
          "retire by another actor than the claim's author is refused before its counter-evidence is stored", rc)
    f.close()


def challenge_cases():
    f = Fix()
    for i in range(1, 6):
        f.claim(f"SPEC-1-{i}")
    f.claim("SPEC-1-6", backed=False)
    ns = {i: f.node(f"SPEC-1-{i}") for i in range(1, 7)}
    c_ok = f.counter(ns[1])                                   # stranger, replays
    c_no = f.counter(ns[2])                                   # stranger, does not replay
    th = f.file("stranger", "challenge", R.challenge(ns[3].tid, "a thesis", [], 0))
    cx = f.file("codex", "challenge", R.challenge(ns[4].tid, "the acceptor's thesis", [], 0))
    cl = f.file("claude", "challenge", R.challenge(ns[5].tid, "the author's own", [], 0))
    c_un = f.counter(ns[6])                                   # against an UNBACKED claim
    bad = {f.model().recs[c_no]["body"]["evidence"][0]}
    stub = (lambda h, p: h not in bad)
    with replaying(stub):
        m = f.model()
        t = CL.challenge_table(f.repo, m)
        problems = CL.check(f.repo)
        nc_new = CL.new_counters(f.repo, m, set())
        nc_old = CL.new_counters(f.repo, m, set(m.recs))
    kinds = {x["claim"]: x["kind"] for x in t.values()}
    want = {"SPEC-1-1": CL.LOWERS, "SPEC-1-2": CL.THESIS, "SPEC-1-3": CL.THESIS, "SPEC-1-4": CL.COUNTED,
            "SPEC-1-5": CL.COUNTED, "SPEC-1-6": CL.THESIS}
    check("L5", kinds == want and set(CL.lowered(t)) == {"SPEC-1-1"} and t[c_ok]["replays"] == m.recs[c_ok]["body"]["evidence"],
          "a counter that replays lowers whoever filed it; with none, the author's or acceptor's challenge counts, a "
          "stranger's is a thesis; a counter against an UNBACKED claim lowers nothing", kinds)
    challenged = sorted(d.split(":")[0] for c, d in problems if c == "CHALLENGED")
    check("L6", challenged == ["SPEC-1-4", "SPEC-1-5"],
          "check refuses CHALLENGED only for a challenge that counts: not for a lowering counter, not for a thesis", challenged)
    check("L7", [d.split(" ")[1] for c, d in nc_new if c == "COUNTER_NOT_REPLAYED"] == sorted([c_no[:12], c_un[:12]])
          and nc_old == [] and th and cx and cl,
          "a challenge new since the base must carry counters that replay against a BACKED claim; one at the base is not "
          "replayed again", nc_new)
    rows = {n.id: CL.status_of(n, CL.lowered(t)) for n in ns.values()}
    check("L8", rows["SPEC-1-1"] == "COUNTERED" and rows["SPEC-1-2"] == "BACKED" and rows["SPEC-1-6"] == "UNBACKED",
          "the view's status of a lowered claim is COUNTERED", rows)

    pins = dict(PINS)
    n = ns[1]
    terms = [CL.duty_terms(m, n, pins), CL.duty_terms(m, n, dict(pins, accept_by=["someone"])),
             CL.duty_terms(m, n, dict(pins, owed_to=["someone"]))]
    f.claim("SPEC-1-7", actor="stranger")
    m = f.model()
    own = CL.duty_terms(m, m.current["SPEC-1-7"], pins)
    (f.dir / ".warrant" / "claims.json").write_text(json.dumps(dict(PINS, accept_by=["accomplice"])))
    f.claim("SPEC-1-8", actor="stranger")
    (f.dir / ".warrant" / "claims.json").write_text(json.dumps(PINS))
    flagged = [d.split(":")[0] for c, d in CL.check(f.repo) if c == "CLAIM_DUTY_TERMS"]
    check("L9", terms[0] is None and terms[1] and terms[2] and own is None and flagged == ["SPEC-1-8"],
          "a claim's duty must be owed to and accepted by whom the pins name (a stranger's own claim with them passes)", terms)

    rm = RM.Roadmap(f.dir)
    f.run(RM, "goal", "--id", "G1", "--text", "Witnesses widen.")
    ref = RM.path_data(rm.model(), "G1")["formulations"][0]["ref"]
    f.file("stranger", "duty", R.duty("stranger", "Mine.", ["s0fractal"], {"attest": {}}, accept_by=["stranger2"], answers=ref))
    ok_duty = RM.Writer(rm, f.keys["stranger"], "stranger").oblige("Also mine.", "G1")
    terms = [c for c, _ in rm.model().problems if c == "OBLIGATION_TERMS"]
    check("L10", terms == ["OBLIGATION_TERMS"] and ok_duty,
          "an obligation not owed to and accepted by whom .warrant/roadmap.json names is refused", terms)
    f.close()


# ---------------------------------------------------------------- D: the witness ledger

def ledger_cases():
    f = Fix()
    f.claim("SPEC-1-1")
    f.claim("SPEC-1-2")
    f.claim("SPEC-1-3")
    f.claim("SPEC-1-4", actor="stranger")
    f.claim("SPEC-1-1", text="A rule holds, amended.", previous=f.node("SPEC-1-1"))
    n1, n2, n3 = (f.node(f"SPEC-1-{i}") for i in (1, 2, 3))
    a1 = f.file("codex", "accept", R.accept(n1.tid, 0, n1.rec["body"]["closes"][0]["evidence"]))
    a2 = f.file("codex", "accept", R.accept(n2.tid, 0, n2.rec["body"]["closes"][0]["evidence"]))
    a3 = f.file("s0fractal", "accept", R.accept(n3.tid, 0, n3.rec["body"]["closes"][0]["evidence"]))
    lower = f.counter(n1)                                         # stranger: replays now against n1
    down = f.counter(n2, actor="codex")                           # codex's counter against n2; claude downgrades citing it
    f.claim("SPEC-1-2", backed=False, previous=n2, counter=[down])
    m0 = f.model()
    down_blob = m0.recs[down]["body"]["evidence"][0]
    f.file("claude", "challenge", R.challenge(n3.tid, "claude cites it later", [down_blob], 0))
    other = f.counter(n3)                                         # stranger, does not replay; claude re-backs citing it
    other_blob = f.model().recs[other]["body"]["evidence"][0]
    f.file("stranger", "challenge", R.challenge(n3.tid, "a stranger's thesis", [], 0))
    f.claim("SPEC-1-3", text="A rule holds, re-backed.", previous=n3, counter=[other_blob])

    # an obligation closure: accepted, challenged, revalidated
    du = f.file("claude", "duty", R.duty("claude", "Do it.", ["s0fractal"], {"attest": {}}, accept_by=["codex"]))
    e1 = f.store.put_blob(b"first")
    t1 = f.file("claude", "transition", R.transition("ATTESTED", [e1], closes=[R.item(du, "discharge", [e1])]))
    a4 = f.file("codex", "accept", R.accept(t1, 0, [e1]))
    f.file("s0fractal", "challenge", R.challenge(t1, "it broke", [], 0))
    e2 = f.store.put_blob(b"again")
    f.file("claude", "transition", R.transition("ATTESTED", [e2], closes=[R.item(du, "revalidate", [e2], revalidates=[t1])]))
    du2 = f.file("claude", "duty", R.duty("claude", "Do that.", ["s0fractal"], {"attest": {}}, accept_by=["codex"]))
    e3 = f.store.put_blob(b"third")
    t3 = f.file("claude", "transition", R.transition("ATTESTED", [e3], closes=[R.item(du2, "discharge", [e3])]))
    a5 = f.file("codex", "accept", R.accept(t3, 0, [e3]))
    f.file("s0fractal", "challenge", R.challenge(t3, "challenged, never revalidated", [], 0))

    f.counter(f.node("SPEC-1-4"), actor="s0fractal")              # current, does not replay
    lower_blob = f.model().recs[lower]["body"]["evidence"][0]
    with replaying(lambda h, p: h == lower_blob):
        m = f.model()
        t = CL.challenge_table(f.repo, m)
        rows = CL.ledger(m, t, f.repo.bindings()[0])
        view = CL.render_witnesses(f.repo, m, t)
    c, s, x, o = rows["claude"], rows["stranger"], rows["codex"], rows["s0fractal"]
    check("W1", c["authored"] == 3 and s["authored"] == 1 and x["authored"] == 0,
          "claims authored counts the lineages an actor began, not its supersessions", (c["authored"], s["authored"]))
    check("W2", len(x["accepts"]) == 4 and len(o["accepts"]) == 1 and len(c["accepts"]) == 0,
          "acceptances count the accept records an actor filed", (x["accepts"], o["accepts"]))
    refuted = sorted(rid for rid, _, _ in x["refuted"])
    check("W3", refuted == sorted([a1, a2, a4]) and o["refuted"] == [],
          "an acceptance is refuted when a counter replays now against the claim, a downgrade cites one, or the closure "
          "was challenged and then revalidated; not when it was only challenged, or nothing replayed",
          (refuted, [a1, a2, a3, a4, a5]))
    check("W4", s["challenges"] == 3 and x["challenges"] == 1 and c["challenges"] == 1 and o["challenges"] == 3,
          "challenges count the challenge records an actor filed", {a: r["challenges"] for a, r in rows.items()})
    check("W5", s["counters"] == sorted([lower_blob, other_blob]) and x["counters"] == [down_blob] and c["counters"] == [],
          "a counter is the filer's whose record cited it first (claude citing codex's counter later takes nothing)",
          (s["counters"], x["counters"], c["counters"]))
    check("W6", s["now"] == [lower_blob] and x["now"] == [] and o["now"] == [] and len(o["counters"]) == 1
          and x["downgrade"] == [down_blob] and s["downgrade"] == [],
          "lowering now: a counter that replays against a current claim; cited by a downgrade: one a BACKED-to-UNBACKED "
          "supersession cites", (s["now"], x["downgrade"]))
    check("W7", len(c["rebacks"]) == 1 and s["rebacks"] == [] and c["rebacks"][0] == f.node("SPEC-1-3").tid,
          "a re-back is a BACKED claim over a claim a counter is against (an amendment over an uncountered one is not)",
          c["rebacks"])
    lines = view.splitlines()
    row = next(ln for ln in lines if ln.startswith("| stranger |"))
    check("W8", "nothing, and no rule reads it" in view
          and row.split(" | ")[1:] == [f"`{K.key_id(f.keys['stranger'].public)[:12]}`", "1", "0", "0", "3", "2", "1", "0", "0 |"],
          "WITNESSES.md renders each count of the ledger, with the bound key", row)
    with replaying(lambda h, p: h == lower_blob):
        gone = codes(CL.check(f.repo))
        f.repo.witnesses.write_bytes(view.encode())
        fresh = codes(CL.check(f.repo))
        f.repo.witnesses.write_bytes(view.replace("\n", "\r\n").encode())
        crlf = codes(CL.check(f.repo))
    check("W9", "WITNESSES_MISSING" in gone and not {"WITNESSES_MISSING", "WITNESSES_STALE"} & set(fresh)
          and "WITNESSES_STALE" in crlf,
          "check refuses a missing WITNESSES.md and one that differs from the rendering by a byte (\\r\\n)", (gone, crlf))
    f.close()


GROUPS = ((binding_cases, ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11", "B12")),
          (accept_cases, ("K1", "K2", "K3", "K4", "K5", "K6", "K7")),
          (lineage_cases, ("L1", "L2", "L3", "L4", "L11")),
          (challenge_cases, ("L5", "L6", "L7", "L8", "L9", "L10")),
          (ledger_cases, ("W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "W9")))


def main():
    from world import results
    for group, ids in GROUPS:
        try:
            group()
        except Exception as e:      # noqa: BLE001  an exception inside a group fails that group's remaining cases
            import traceback
            traceback.print_exc()
            for cid in ids:
                if cid not in results:
                    check(cid, False, f"{group.__name__} raised", f"{type(e).__name__}: {e}")
    return finish("CIRCLE")


if __name__ == "__main__":
    sys.exit(main())
