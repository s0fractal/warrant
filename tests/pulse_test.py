#!/usr/bin/env python3
"""Tests for `warrant.pulse` deterministic cross-repository organism pulse (`PL01..PL07`).

    python3 tests/pulse_test.py
"""
import sys

from world import Repo, check, run_sections

from warrant import engine as E
from warrant import jcs as C
from warrant import pact as P
from warrant import pulse as PL
from warrant import records as R
from warrant.store import Snapshot

def pulse_cases():
    # PL01: Per-repository pulse reports open obligations, pending done obligations, and verified actor counts
    r1 = Repo()
    r1.put("alice", "schema", P.SCHEMA)
    t = r1.t + 10
    o_open = r1.put("alice", "entity", {"state": "open", "statement": "open task", "serves": []}, schema="obligation@1", at=t)
    o_done_root = r1.put("alice", "entity", {"state": "open", "statement": "done task", "serves": []}, schema="obligation@1", at=t + 1)
    r1.put("alice", "entity", {"state": "done", "statement": "done task", "serves": []},
           schema="obligation@1", lineage=o_done_root,
           guard={"roles": ["roadmap/acceptor"], "quorum": 1, "match": {"verdict": "accept"}, "requires": []}, at=t + 2)
    rp1 = PL.pulse_repository("repo1", r1.store.snapshot(), r1.trust, r1.profile)
    check("PL01 pulse_repository separates open obligations from pending done obligations and counts verified actors",
          o_open in rp1["open_obligations"]
          and o_done_root in rp1["pending_done_obligations"]
          and o_done_root not in rp1["open_obligations"]
          and rp1["actors"]["alice"]["entity"] >= 3
          and rp1["rejected_count"] == 0,
          rp1)

    # PL02: as_of horizon strictly excludes future records without hiding malformed lines
    rp_early = PL.pulse_repository("repo1", r1.store.snapshot(), r1.trust, r1.profile, as_of=t)
    check("PL02 as_of horizon excludes records dated after as_of",
          o_open in rp_early["open_obligations"]
          and o_done_root not in rp_early["open_obligations"]
          and o_done_root not in rp_early["pending_done_obligations"],
          rp_early)

    # PL03: Unverified / forged signature lines are counted in rejected_count and never enter actor decision_profile
    bad_line = b'{"record":{"actor":"mallory","at":1,"body":{"x":1},"guard":null,"kind":"entity","lineage":null,"prev":null,"refs":[],"schema":null,"warrant":"3"},"sig":{"ed25519":"' + (b"0" * 128) + b'","key":"' + (b"0" * 64) + b'"}}\n'
    snap_bad = Snapshot(r1.store.snapshot().raw + [bad_line], {})
    rp_bad = PL.pulse_repository("repo1", snap_bad, r1.trust, r1.profile)
    check("PL03 forged signature line is counted in rejected_count and excluded from verified actors",
          rp_bad["rejected_count"] >= 1 and "mallory" not in rp_bad["actors"],
          rp_bad)

    # PL04: Ecosystem pulse aggregates across multiple repos with independent trust and order-independent digest
    r2 = Repo()
    r2.put("alice", "schema", P.SCHEMA)
    sa, sb = (r2.seed(a).read_text().strip() for a in ("alice", "bob"))
    t2 = r2.t + 10
    prop = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments={
        "alice": {"gives": ["a"]}, "bob": {"gives": ["b"]},
    }, expires_at=t2 + 100, purpose="pulse-pact", at=t2)
    pid = R.rid(prop["record"])
    r2.store.add_lines([C.canon(e) + b"\n" for e in [
        prop, P.make_accept("alice", sa, pid, at=t2 + 1), P.make_accept("bob", sb, pid, at=t2 + 2),
    ]])
    p_ab = PL.pulse_ecosystem({
        "repo1": (r1.store.snapshot(), r1.trust, r1.profile),
        "repo2": (r2.store.snapshot(), r2.trust, r2.profile),
    })
    p_ba = PL.pulse_ecosystem({
        "repo2": (r2.store.snapshot(), r2.trust, r2.profile),
        "repo1": (r1.store.snapshot(), r1.trust, r1.profile),
    })
    check("PL04 pulse_ecosystem aggregates multi-repo totals, active pacts, and order-independent SHA-256 digest",
          p_ab["digest"] == p_ba["digest"] and len(p_ab["digest"]) == 64
          and p_ab["pulse"]["totals"]["repositories"] == 2
          and p_ab["pulse"]["totals"]["active_pacts"] == 1
          and p_ab["pulse"]["decision_profile"]["alice"]["repositories"] == ["repo1", "repo2"],
          (p_ab["digest"], p_ab["pulse"]["totals"], p_ab["pulse"]["decision_profile"]))

    # PL05: Strict input validation refuses empty repo map, negative/bool as_of, and bad tuples
    errs = []
    for fn in (
        lambda: PL.pulse_ecosystem({}),
        lambda: PL.pulse_ecosystem({"r": (r1.store.snapshot(), r1.trust, r1.profile)}, as_of=True),
        lambda: PL._snapshot_at(r1.store.snapshot(), -1),
        lambda: PL.pulse_ecosystem({"r": ("not-a-tuple",)}),
    ):
        try:
            fn()
            errs.append(None)
        except ValueError as exc:
            errs.append(str(exc))
    check("PL05 empty repos, bool/negative as_of, and malformed repo tuples fail closed",
          all(e is not None for e in errs), errs)

    # PL06: Shape-valid forged signature (engine BAD_SIGNATURE) is counted in rejected_count and totals.rejected
    r3 = Repo()
    target = r3.schemas["obligation@1"]
    rid = r3.put("alice", "attest", {"target": target, "verdict": "accept"}, refs=[target])
    env = r3.store.snapshot().lines[rid][0]
    env["sig"]["ed25519"] = "0" * 128
    snap_sig = Snapshot([C.canon(env) + b"\n"], {}, sort=True)
    eng_rej = E.View(snap_sig, r3.trust, r3.profile).report()["rejected"]
    eco_sig = PL.pulse_ecosystem({"r": (snap_sig, r3.trust, r3.profile)})["pulse"]
    rp_sig = eco_sig["repositories"]["r"]
    check("PL06 shape-valid BAD_SIGNATURE is counted in rejected_count and totals.rejected",
          len(eng_rej) == 1 and rp_sig["rejected_count"] == 1
          and eco_sig["totals"]["rejected"] == 1 and "alice" not in rp_sig["actors"],
          {"engine": eng_rej, "pulse": rp_sig})

    # PL07: Malformed JSON lines without valid integer record.at are preserved under as_of
    malformed = [b"{}\n", b"[]\n", b'{"record":{}}\n', b'{"record":{"at":"bad"}}\n']
    observed = []
    for raw in malformed:
        msnap = Snapshot([raw], {})
        before = PL.pulse_repository("r", msnap, r3.trust, r3.profile)
        after = PL.pulse_repository("r", msnap, r3.trust, r3.profile, as_of=r3.t)
        observed.append((before["canonical"], before["rejected_count"],
                         after["canonical"], after["rejected_count"]))
    check("PL07 malformed JSON lines without valid integer timestamp stay rejected under as_of",
          observed == [(False, 1, False, 1)] * len(malformed), observed)


if __name__ == "__main__":
    sys.exit(run_sections([pulse_cases]))
