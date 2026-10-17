#!/usr/bin/env python3
"""impl/loops.py (WRT-021 draft-2, obligation slice) against proposal §5-§8.
Every store is built with warrant's own Store and signer, and every verdict is
read from the assessment by name.

    python3 tests/loops_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
# LOOPS_IMPL lets tests/loops_mutants.py run this file against a mutated copy.
if os.environ.get("LOOPS_IMPL"):
    sys.path.insert(0, os.environ["LOOPS_IMPL"])
import loops as L    # noqa: E402
import warrant as W  # noqa: E402

results = {}
CLAUDE, CODEX, OWNER, MALLORY = "claude@local", "codex@local", "owner@local", "mallory@x"
KEYS = {CLAUDE: "11", CODEX: "22", OWNER: "33", MALLORY: "66"}
SHA_OLD, SHA_NEW = "cda525ef" + "0" * 32, "e2f679c8" + "0" * 32
T_END = 1000


def case(lid, ok, what, detail=""):
    results[lid] = "PASS" if ok else "FAIL"
    print(("ok    " if ok else "FAIL  ") + f"{lid} {what}" + ("" if ok else f" | {detail}"))


class Case:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="loops-"))
        self.S = W.Store(str(self.tmp / "s"))
        self.S.init()
        self.keys = {}
        for actor, b in KEYS.items():
            k = self.tmp / f"{actor}.key"
            k.write_text(b * 32 + "\n")
            self.keys[actor] = k
        self.trust = self.tmp / "trust.json"
        self.trust.write_text(json.dumps({"actors": {a: [W.pubkey_hex(W.load_key(str(self.keys[a])))]
                                                     for a in (CLAUDE, CODEX, OWNER)}}))
        self.policy = self.S.put_blob(b"WRT-021 draft-2 dogfood policy\n")
        self.ts = 0
        self.evidence = self.S.put_blob(b"repro.py output: red on old head, green on new\n")

    def blob(self, doc):
        return self.S.put_blob(L.canon(doc))

    def record(self, decision, subject, actor, prior=(), ts=None):
        self.ts = ts if ts is not None else self.ts + 1
        body = {"warrant": "0.2", "decision": decision, "subject": {"hash": subject, "note": "loops"},
                "under": [self.policy], "because": [{"kind": "prose", "text": "dogfood"}],
                "evidence": [], "actor": {"id": actor}, "prior": list(prior), "ts": self.ts}
        return self.S.put_record({"body": body, "sigs": [W.sign_envelope(body, actor, str(self.keys[actor]))]})

    def open(self, actor=CLAUDE, prior=None, **kw):
        kw.setdefault("holder", CLAUDE)
        kw.setdefault("owed_to", [CODEX])
        kw.setdefault("statement", "fix finding N1")
        kw.setdefault("scope_subject", SHA_OLD)
        kw.setdefault("admits", [["DISCHARGED", "RUNNER_ATTESTED"]])
        kw.setdefault("acceptance", [CODEX])
        return self.record("propose", self.blob(L.duty(**kw)), actor,
                           prior=kw.get("serves", ()) if prior is None else prior)

    def act(self, actor, closes, basis="RUNNER_ATTESTED", ts=None, opened=(), addresses=(), prior=None):
        t = L.transition(basis, [self.evidence], closes=closes, opened=opened, addresses=addresses,
                         scope_subject=SHA_NEW)
        if prior is None:
            prior = sorted({m["duty"] for m in closes} | set(addresses))
        return self.record("propose", self.blob(t), actor, prior=prior, ts=ts)

    def accept(self, actor, duty_id, t_id, index=0, evidence=None):
        a = L.acceptance(duty_id, t_id, index, [self.evidence] if evidence is None else evidence)
        return self.record("accept", self.blob(a), actor, prior=[t_id])

    def discharge(self, duty_id, actor=CLAUDE, basis="RUNNER_ATTESTED"):
        return self.act(actor, [L.mapping(duty_id, "DISCHARGED", [self.evidence])], basis)

    def assess(self, as_of=T_END, current=None):
        return L.assess(self.S.root, self.trust, as_of, current)


def d(rep, wid):
    return rep["duties"][wid]


def main():
    # L01: a well-formed duty opens; a malformed one is refused, not opened
    c = Case()
    good = c.open()
    wish = L.duty(CLAUDE, [CODEX], "a wish", SHA_OLD, [["DISCHARGED", "ATTESTED"]])
    wish["kind"] = "wish"
    bad = c.record("propose", c.blob(wish), CLAUDE)
    rep = c.assess()
    case("L01", d(rep, good)["disposition"] == "OPEN" and bad in rep["refused_events"]
         and bad not in rep["duties"], "a malformed duty is refused, a well-formed one is OPEN", rep["refused_events"])

    # L02: nobody opens an obligation for someone else (§6.3)
    c = Case()
    forced = c.open(actor=CODEX)          # Codex opens a duty whose holder is Claude
    rep = c.assess()
    case("L02", forced not in rep["duties"] and "holder" in rep["refused_events"].get(forced, ""),
         "a duty opened by someone other than its holder is refused", rep["refused_events"])

    # L03: discharge on an admitted basis, with the creditor's acceptance bound to it
    c = Case()
    n1 = c.open()
    t = c.discharge(n1)
    rep_pending = c.assess()
    c.accept(CODEX, n1, t)
    rep = c.assess()
    case("L03", d(rep_pending, n1)["disposition"] == "OPEN"
         and "PENDING_ACCEPTANCE" in d(rep_pending, n1)["flags"]
         and d(rep, n1)["disposition"] == "DISCHARGED" and d(rep, n1)["basis"] == ["RUNNER_ATTESTED"],
         "DISCHARGED needs the admitted basis and the named acceptance", (d(rep_pending, n1), d(rep, n1)))

    # L04: a basis the duty does not admit is OVERCLAIMED and closes nothing (review R1)
    c = Case()
    n1 = c.open()
    t = c.discharge(n1, basis="ATTESTED")
    c.accept(CODEX, n1, t)
    r = d(c.assess(), n1)
    case("L04", r["disposition"] == "OPEN" and "OVERCLAIMED_CANDIDATE" in r["flags"]
         and r["candidates"][0]["verdict"] == "OVERCLAIMED",
         "a non-admitted basis is OVERCLAIMED, never reinterpreted", r)

    # L05: an acceptance of transition T1 does not admit T2 (review R3)
    c2 = Case()
    n1b = c2.open()
    t1b = c2.discharge(n1b)
    t2b = c2.act(CLAUDE, [L.mapping(n1b, "DISCHARGED", [c2.evidence])], ts=50)
    c2.accept(CODEX, n1b, t1b)
    rb = d(c2.assess(), n1b)
    verdicts = {x["transition"]: x["verdict"] for x in rb["candidates"]}
    case("L05", verdicts.get(t1b) == "ADMITTED" and verdicts.get(t2b) == "PENDING",
         "an acceptance binds one transition id", verdicts)

    # L06: an acceptance by someone not named in the duty's acceptance does not count
    c = Case()
    n1 = c.open()
    t = c.discharge(n1)
    c.accept(OWNER, n1, t)
    r = d(c.assess(), n1)
    case("L06", r["disposition"] == "OPEN" and "PENDING_ACCEPTANCE" in r["flags"],
         "only the named acceptor's acceptance counts", r)

    # L07: an acceptance naming other evidence does not bind
    c = Case()
    n1 = c.open()
    t = c.discharge(n1)
    other = c.S.put_blob(b"different evidence\n")
    c.accept(CODEX, n1, t, evidence=[other])
    r = d(c.assess(), n1)
    case("L07", r["disposition"] == "OPEN", "an acceptance binds the evidence ids", r)

    # L08: closing a child never closes the parent it serves (§6.1)
    c = Case()
    review = c.open(statement="the #131 review round", admits=[["DISCHARGED", "ATTESTED"]])
    n1 = c.open(serves=[review])
    t = c.discharge(n1)
    c.accept(CODEX, n1, t)
    rep = c.assess()
    case("L08", d(rep, n1)["disposition"] == "DISCHARGED" and d(rep, review)["disposition"] == "OPEN",
         "a discharged only child leaves its parent OPEN", (d(rep, n1)["disposition"], d(rep, review)))

    # L09: a failed attempt closes nothing
    c = Case()
    n1 = c.open()
    c.act(CLAUDE, [], addresses=[n1])
    r = d(c.assess(), n1)
    case("L09", r["disposition"] == "OPEN" and not r["candidates"], "a failed attempt leaves the duty OPEN", r)

    # L10: release by the creditor closes; release by the holder is OVERCLAIMED
    c = Case()
    n1 = c.open()
    c.act(CLAUDE, [L.mapping(n1, "RELEASED")])
    r_self = d(c.assess(), n1)
    c.act(CODEX, [L.mapping(n1, "RELEASED")])
    r = d(c.assess(), n1)
    case("L10", r_self["disposition"] == "OPEN" and r["disposition"] == "RELEASED",
         "only the creditor or release_by releases", (r_self["disposition"], r["disposition"]))

    # L11: an obligation cannot be abandoned by its holder
    c = Case()
    n1 = c.open()
    c.act(CLAUDE, [L.mapping(n1, "ABANDONED")])
    r = d(c.assess(), n1)
    case("L11", r["disposition"] == "OPEN" and "OVERCLAIMED_CANDIDATE" in r["flags"],
         "ABANDONED is not a closure of an obligation", r)

    # L12: delegation keeps the holder; the delegate may discharge; only the holder delegates
    c = Case()
    n1 = c.open()
    c.act(OWNER, [L.mapping(n1, "DELEGATED", to=OWNER)])
    r_bad = d(c.assess(), n1)
    c.act(CLAUDE, [L.mapping(n1, "DELEGATED", to=OWNER)])
    t = c.discharge(n1, actor=OWNER)
    c.accept(CODEX, n1, t)
    r = d(c.assess(), n1)
    case("L12", r_bad["delegates"] == [] and r["holder"] == CLAUDE and r["delegates"] == [OWNER]
         and r["disposition"] == "DISCHARGED", "delegation keeps the holder; the delegate may close", (r_bad, r))

    # L13: substitution needs the creditor; afterwards the old holder no longer closes (review R3)
    c = Case()
    n1 = c.open()
    s = c.act(CLAUDE, [L.mapping(n1, "SUBSTITUTED", to=OWNER)])
    r_pending = d(c.assess(), n1)
    c.accept(CODEX, n1, s, evidence=[])
    t_old = c.discharge(n1)
    c.accept(CODEX, n1, t_old)
    r = d(c.assess(), n1)
    case("L13", r_pending["holder"] == CLAUDE and "PENDING_ACCEPTANCE" in r_pending["flags"]
         and r["holder"] == OWNER and r["disposition"] == "OPEN",
         "holder and successor alone cannot substitute; after it the old holder cannot close",
         (r_pending["holder"], r["holder"], r["disposition"]))

    # L14: two admitted, incompatible closures are CONTESTED, not silently ordered
    c = Case()
    n1 = c.open(admits=[["DISCHARGED", "RUNNER_ATTESTED"], ["DECLARED_IMPOSSIBLE", "ATTESTED"]])
    t1 = c.discharge(n1)
    c.accept(CODEX, n1, t1)
    t2 = c.act(CLAUDE, [L.mapping(n1, "DECLARED_IMPOSSIBLE", [c.evidence])], basis="ATTESTED")
    c.accept(CODEX, n1, t2)
    r = d(c.assess(), n1)
    case("L14", "CONTESTED" in r["flags"] and r["disposition"] is None
         and r["dispositions"] == ["DECLARED_IMPOSSIBLE", "DISCHARGED"], "incompatible closures are CONTESTED", r)

    # L15: orphaned only when every parent ended; a root is never orphaned; DISCHARGED orphans nobody
    c = Case()
    root = c.open(statement="root, serves nothing")
    parent = c.open(statement="parent")
    child = c.open(serves=[parent])
    c.act(CODEX, [L.mapping(parent, "RELEASED")])
    rep = c.assess()
    c2 = Case()
    p2 = c2.open(statement="parent")
    ch2 = c2.open(serves=[p2])
    t = c2.discharge(p2)
    c2.accept(CODEX, p2, t)
    rep2 = c2.assess()
    case("L15", "ORPHANED" in d(rep, child)["flags"] and "ORPHANED" not in d(rep, root)["flags"]
         and "ORPHANED" not in d(rep2, ch2)["flags"],
         "orphaned iff every parent ended; never vacuously", (d(rep, child)["flags"], d(rep2, ch2)["flags"]))

    # L16: an unknown typed reference is MISSING, never OPEN or ORPHANED. (A dangling
    # `prior` is already an integrity error of SPEC §6, so the typed relation is the case.)
    c = Case()
    ghost = "ab" * 32
    child = c.open(serves=[ghost], prior=[])
    c.act(CLAUDE, [L.mapping(ghost, "DISCHARGED", [c.evidence])], prior=[])
    rep = c.assess()
    case("L16", "MISSING" in d(rep, child)["flags"] and "ORPHANED" not in d(rep, child)["flags"]
         and rep["missing_duties"] == [ghost], "unknown references are MISSING", rep)

    # L17: recurring duties have instances: covered, lapsed, open; no instance, no closure
    c = Case()
    maint = c.open(statement="rotate the backup key", shape="recurring", period={"start": 100, "every": 100},
                   admits=[["DISCHARGED", "ATTESTED"]], acceptance=[])
    c.act(CLAUDE, [L.mapping(maint, "DISCHARGED", [c.evidence], instance=0)], basis="ATTESTED", ts=150)
    c.act(CLAUDE, [L.mapping(maint, "DISCHARGED", [c.evidence])], basis="ATTESTED", ts=160)
    r = d(c.assess(as_of=350), maint)
    case("L17", r["disposition"] == "RECURRING" and r["instances"] == {"0": "COVERED", "1": "LAPSED", "2": "OPEN"}
         and "LAPSED" in r["flags"] and r["candidates"][1]["verdict"] == "OVERCLAIMED",
         "instance 0 covered, 1 lapsed, 2 open; a mapping without an instance closes nothing", r)

    # L18: an invariant is observed at a time; no fresh observation is not "holds" (review R4)
    c = Case()
    inv = c.open(statement="service functional", shape="invariant", freshness=50,
                 admits=[["OBSERVED", "RUNNER_ATTESTED"]], acceptance=[])
    r0 = d(c.assess(as_of=100), inv)
    c.act(CLAUDE, [L.mapping(inv, "OBSERVED", [c.evidence], holds=True)], ts=200)
    r1 = d(c.assess(as_of=220), inv)
    r2 = d(c.assess(as_of=400), inv)
    c.act(CLAUDE, [L.mapping(inv, "OBSERVED", [c.evidence], holds=False)], ts=410)
    r3 = d(c.assess(as_of=420), inv)
    case("L18", "UNOBSERVED" in r0["flags"] and not r1["flags"] and "UNOBSERVED" in r2["flags"]
         and "BREACHED" in r3["flags"], "fresh hold: no flag; stale or none: UNOBSERVED; fresh false: BREACHED",
         (r0["flags"], r1["flags"], r2["flags"], r3["flags"]))

    # L19: a record that fails settlement-grade verification is not in the view
    c = Case()
    n1 = c.open()
    t = c.discharge(n1)
    c.accept(MALLORY, n1, t)                   # mallory is not in the recipient's trust
    rep = c.assess()
    c2 = Case()
    n1b = c2.open()
    c2.act(MALLORY, [L.mapping(n1b, "RELEASED")])   # an untrusted "release"
    rep2 = c2.assess()
    case("L19", len(rep["invalid_records"]) == 1 and d(rep, n1)["disposition"] == "OPEN"
         and d(rep2, n1b)["disposition"] == "OPEN",
         "unbound signatures are excluded from the view", (rep["invalid_records"], d(rep2, n1b)))

    # L20: a duty blob whose bytes were replaced is not read
    c = Case()
    n1 = c.open()
    body = c.S.get_record(n1)["body"]
    p = c.S.blobs / body["subject"]["hash"]
    doc = json.loads(p.read_bytes())
    doc["owed_to"] = [OWNER]
    p.write_bytes(L.canon(doc))
    rep = c.assess()
    case("L20", n1 not in rep["duties"], "a replaced duty blob is not admitted", rep["duties"].keys())

    # L21: the view ends at as_of
    c = Case()
    n1 = c.open()
    t = c.discharge(n1)
    c.accept(CODEX, n1, t)
    early = d(c.assess(as_of=2), n1)
    case("L21", early["disposition"] == "OPEN" and d(c.assess(), n1)["disposition"] == "DISCHARGED",
         "events after as_of are outside the view", early)

    # L22: a new revision makes applicability UNASSESSED and leaves the disposition as it was (review R5)
    c = Case()
    n1 = c.open()
    t = c.discharge(n1)
    c.accept(CODEX, n1, t)
    r_old = d(c.assess(current={SHA_OLD}), n1)
    r_new = d(c.assess(current={"416ea4a8" + "0" * 32}), n1)
    case("L22", r_old["applicability"] == "CURRENT" and r_new["applicability"] == "UNASSESSED"
         and r_new["disposition"] == "DISCHARGED", "replacement is not invalidation", (r_old, r_new))

    # L23: the frontier: unowned questions bind nobody; a taken question appears with its duty
    c = Case()
    q_unowned = c.S.put_blob(L.canon({"question": "does the snapshot cover genesis.json?"}))
    q_taken = c.S.put_blob(L.canon({"question": "is the trust file read once?"}))
    n1 = c.open(answers=q_taken)
    c.act(CODEX, [], opened=[q_unowned, q_taken], addresses=[n1])
    rep = c.assess()
    fc, fx, fo = L.frontier(rep, CLAUDE), L.frontier(rep, CODEX), L.frontier(rep, OWNER)
    case("L23", rep["unowned_questions"] == [q_unowned] and [x["question"] for x in fc] == [q_taken]
         and len(fx) == 1 and fo == [],
         "unowned questions are in nobody's frontier", (rep["unowned_questions"], fc, fx, fo))

    # L24: SPEC §7 -- a dogfood store verifies at settlement grade with no re-litigation warning
    c = Case()
    n1 = c.open()
    t = c.discharge(n1)
    c.accept(CODEX, n1, t)
    c.act(CODEX, [L.mapping(n1, "RELEASED")])
    out = subprocess.run([sys.executable, str(ROOT / "impl" / "warrant.py"), "--store", str(c.S.root), "verify",
                          "--settlement", "--require-bound", "--trust-config", str(c.trust), "--json"],
                         capture_output=True, text=True, check=False)
    vrep = json.loads(out.stdout)
    case("L24", vrep["errors"] == 0 and not any("re-litigation" in f["message"] for f in vrep["findings"]),
         "loop events are settlement-compatible", vrep["findings"])

    # L25: kinds other than obligation are recognized and not implemented
    c = Case()
    g = c.open(kind="goal", owed_to=[], statement="a portable review loop")
    r = d(c.assess(), g)
    case("L25", r["disposition"] == "NOT_IMPLEMENTED", "goal is NOT_IMPLEMENTED in the obligation slice", r)

    # L26: a mapping cannot cite evidence the transition does not carry
    c = Case()
    n1 = c.open()
    stray = c.S.put_blob(b"not carried\n")
    t = L.transition("RUNNER_ATTESTED", [c.evidence], closes=[L.mapping(n1, "DISCHARGED", [stray])])
    wid = c.record("propose", c.blob(t), CLAUDE, prior=[n1])
    rep = c.assess()
    case("L26", wid in rep["refused_events"], "mapping evidence must be the transition's own", rep["refused_events"])

    # L27: _blob reads only canonical bytes at their own address (a second guard
    # behind verify's subject check, so it is tested directly)
    c = Case()
    doc = {"schema": L.DUTY, "x": 1}
    h = c.S.put_blob(L.canon(doc))
    loose = c.S.put_blob(json.dumps(doc, indent=1).encode())
    (c.S.blobs / ("cd" * 32)).write_bytes(L.canon(doc))
    case("L27", L._blob(c.S, h) == doc and L._blob(c.S, loose) is None and L._blob(c.S, "cd" * 32) is None,
         "non-canonical or misaddressed bytes are not read")

    # L28: an overclaim on a duty that was then properly closed leaves the frontier
    c = Case()
    n1 = c.open()
    c.discharge(n1, basis="ATTESTED")                  # overclaimed
    t = c.discharge(n1)
    c.accept(CODEX, n1, t)
    rep = c.assess()
    case("L28", d(rep, n1)["disposition"] == "DISCHARGED" and "OVERCLAIMED_CANDIDATE" in d(rep, n1)["flags"]
         and L.frontier(rep, CLAUDE) == [], "a closed duty's past overclaim stays in the report, not the frontier",
         L.frontier(rep, CLAUDE))

    failed = sorted(k for k, v in results.items() if v == "FAIL")
    print(f"LOOPS: {sum(v == 'PASS' for v in results.values())} PASS / {len(failed)} FAIL"
          + (f" ({', '.join(failed)})" if failed else ""))
    if os.environ.get("LOOPS_RESULTS"):
        Path(os.environ["LOOPS_RESULTS"]).write_text(json.dumps(results))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
