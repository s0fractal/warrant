#!/usr/bin/env python3
"""Attenuating cryptographic capability delegation tests (`warrant.delegate`, docs/DELEGATION.md):
semilattice laws, chained monotonic attenuation, transitive ancestral revocation, forks, challenges,
time windows, scope enforcement, anti-laundering, No-Sybil-Inflation, cross-grant isolation and CLI."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from world import ROOT, check, finish
from warrant import delegate as D
from warrant import keys as K
from warrant import records as R
from warrant.store import Snapshot, Store


def _key():
    return K.Key.generate()


def _mk_trust(pairs):
    return {"warrant": "trust/3", "keys": {a: sorted(ks) for a, ks in pairs.items()}}


def _mk_profile(roles, quorum=None):
    p = {"warrant": "profile/3", "roles": {r: sorted(xs) for r, xs in roles.items()}}
    if quorum:
        p["quorum"] = dict(quorum)
    return p


def _schema_guarded(name, roles, quorum=1):
    return {
        "name": name,
        "fields": {"state": "str", "title": "str"},
        "states": {
            "open": None,
            "done": R.guard(quorum, sorted(roles), {"verdict": "accept"}),
        },
        "closed": ["done"],
        "successors": {},
    }


def _line(rec, key):
    return R.line(rec, key)[1]


def _setup_base(quorum=1, extra_roles=None):
    """Store with alice (author), bob (acceptor), carol (acceptor), dave (challenger), and task@1 schema."""
    ka, kb, kc, kd = _key(), _key(), _key(), _key()
    trust = _mk_trust({"alice": [ka.public], "bob": [kb.public], "carol": [kc.public], "dave": [kd.public]})
    roles = {
        "schema/author": ["alice", "bob"],
        "acceptor": ["bob", "carol"],
        "challenger": ["dave"],
        "r1": ["bob"],
        "r2": ["bob"],
    }
    if extra_roles:
        for r, xs in extra_roles.items():
            roles[r] = xs
    profile = _mk_profile(roles, {"schema/author": 2})

    s_task = R.record("schema", "alice", 10, _schema_guarded("task@1", ["acceptor"], quorum), None)
    s_task_id = R.rid(s_task)
    s_task_b = R.record("attest", "bob", 11, {"target": s_task_id, "verdict": "accept"}, refs=[s_task_id])

    s_grant = R.record("schema", "alice", 12, D.SCHEMA, None)
    s_grant_id = R.rid(s_grant)
    s_grant_b = R.record("attest", "bob", 13, {"target": s_grant_id, "verdict": "accept"}, refs=[s_grant_id])

    guard_done = {"roles": ["acceptor"], "quorum": quorum, "match": {"verdict": "accept"}, "requires": []}
    t_root = R.record("entity", "alice", 20, {"state": "open", "title": "ship"}, "task@1")
    t_root_id = R.rid(t_root)
    t_done = R.record("entity", "alice", 21, {"state": "done", "title": "ship"}, "task@1",
                      lineage=t_root_id, guard=guard_done)
    t_done_id = R.rid(t_done)

    lines = [
        _line(s_task, ka), _line(s_task_b, kb),
        _line(s_grant, ka), _line(s_grant_b, kb),
        _line(t_root, ka), _line(t_done, ka),
    ]
    return {
        "keys": {"alice": ka, "bob": kb, "carol": kc, "dave": kd},
        "trust": trust,
        "profile": profile,
        "lines": lines,
        "task_root": t_root_id,
        "task_done": t_done_id,
    }


def delegate_cases():
    # DG01: Meet-semilattice algebraic laws
    c1 = D.Cap(frozenset({"a", "b"}), frozenset({"attest", "entity"}), None, None, 10, 100, 3)
    c2 = D.Cap(frozenset({"b", "c"}), frozenset({"attest"}), frozenset({"task@1"}), None, 20, 80, 2)
    c3 = D.Cap(frozenset({"b"}), frozenset({"attest"}), frozenset({"task@1", "other@1"}), frozenset({"0" * 64}), 15, 90, 1)
    m12 = c1.meet(c2)
    check("DG01 Cap meet-semilattice: idempotence, commutativity, associativity, and order consistency (a <= b <=> meet(a,b)==a)",
          c1.meet(c1) == c1
          and c1.meet(c2) == c2.meet(c1)
          and c1.meet(c2).meet(c3) == c1.meet(c2.meet(c3))
          and m12.le(c1) and m12.le(c2) and not c1.le(c2)
          and (m12.meet(c1) == m12) and (c1.meet(m12) == m12),
          (m12, c1.meet(c2).meet(c3)))

    # DG02: Root grant lets ephemeral sub-agent accept a guarded version without editing static trust
    w = _setup_base()
    ksub = _key()
    g = D.grant_record("bob", "bob-sub", ksub.public, ["acceptor"], ["attest"], 100, 200, max_depth=0,
                       schemas=["task@1"], lineages=[w["task_root"]], at=100)
    gid = R.rid(g)
    att = R.record("attest", "bob-sub", 150, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
    att_id = R.rid(att)
    snap = Snapshot(w["lines"] + [_line(g, w["keys"]["bob"]), _line(att, ksub)], {})
    res = D.assess_delegated(snap, w["trust"], w["profile"], as_of=150)
    static_lin = res["static_report"]["lineages"].get(w["task_root"], {})
    del_lin = res["delegated_report"]["lineages"].get(w["task_root"], {})
    check("DG02 active root grant admits ephemeral delegate's attest: static stays open, delegated becomes done/ELIGIBLE with provenance",
          res["grants"].get(gid, {}).get("status") == "ACTIVE"
          and static_lin.get("state") == "open"
          and del_lin.get("state") == "done" and del_lin.get("reliance") == "ELIGIBLE"
          and res["provenance"].get(att_id, {}).get("root_issuer") == "bob"
          and res["provenance"].get(att_id, {}).get("chain") == [gid]
          and len(res["changes"]) == 1,
          (res["grants"].get(gid), static_lin, del_lin, res["provenance"]))

    # DG03: Multi-hop chained delegation (bob -> mid -> leaf) with strict monotonic attenuation
    w = _setup_base()
    kmid, kleaf = _key(), _key()
    g1 = D.grant_record("bob", "mid", kmid.public, ["acceptor", "r1"], ["attest", "challenge"], 100, 300, max_depth=2,
                        schemas=None, lineages=None, at=100)
    g1_id = R.rid(g1)
    g2 = D.grant_record("mid", "leaf", kleaf.public, ["acceptor"], ["attest"], 120, 250, max_depth=1,
                        schemas=["task@1"], lineages=[w["task_root"]], parent=g1_id, at=120)
    g2_id = R.rid(g2)
    att = R.record("attest", "leaf", 200, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
    snap = Snapshot(w["lines"] + [_line(g1, w["keys"]["bob"]), _line(g2, kmid), _line(att, kleaf)], {})
    res = D.assess_delegated(snap, w["trust"], w["profile"], as_of=200)
    g2_info = res["grants"].get(g2_id, {})
    check("DG03 chained delegation bob->mid->leaf attenuates scope across hops and carries full chain to root_issuer",
          g2_info.get("status") == "ACTIVE"
          and g2_info.get("root_issuer") == "bob"
          and g2_info.get("chain") == [g1_id, g2_id]
          and g2_info.get("depth") == 1
          and g2_info.get("effective", {}).get("roles") == ["acceptor"]
          and g2_info.get("effective", {}).get("schemas") == ["task@1"]
          and res["delegated_report"]["lineages"].get(w["task_root"], {}).get("state") == "done",
          g2_info)

    # DG04: Root issuer widening refused (alice does not hold `acceptor`)
    w = _setup_base()
    ksub = _key()
    g_bad = D.grant_record("alice", "alice-sub", ksub.public, ["acceptor"], ["attest"], 100, 200, at=100)
    g_bad_id = R.rid(g_bad)
    snap = Snapshot(w["lines"] + [_line(g_bad, w["keys"]["alice"])], {})
    gs = D.resolve_grants(snap, w["trust"], w["profile"], as_of=150)
    check("DG04 root issuer granting a role it does not hold in receiver profile fails closed with WIDENING",
          gs.get(g_bad_id, {}).get("status") == "WIDENING", gs.get(g_bad_id))

    # DG05: Child widening on every dimension fails closed (roles, kinds, schemas, lineages, window)
    w = _setup_base()
    kmid, k1, k2, k3, k4, k5 = _key(), _key(), _key(), _key(), _key(), _key()
    gp = D.grant_record("bob", "mid", kmid.public, ["acceptor"], ["attest"], 100, 200, max_depth=2,
                        schemas=["task@1"], lineages=[w["task_root"]], at=100)
    gp_id = R.rid(gp)
    wide_roles = D.grant_record("mid", "c1", k1.public, ["acceptor", "r1"], ["attest"], 110, 190, max_depth=1,
                                schemas=["task@1"], lineages=[w["task_root"]], parent=gp_id, at=110)
    wide_kinds = D.grant_record("mid", "c2", k2.public, ["acceptor"], ["attest", "challenge"], 110, 190, max_depth=1,
                                schemas=["task@1"], lineages=[w["task_root"]], parent=gp_id, at=110)
    wide_schemas = D.grant_record("mid", "c3", k3.public, ["acceptor"], ["attest"], 110, 190, max_depth=1,
                                  schemas=None, lineages=[w["task_root"]], parent=gp_id, at=110)
    wide_lin = D.grant_record("mid", "c4", k4.public, ["acceptor"], ["attest"], 110, 190, max_depth=1,
                              schemas=["task@1"], lineages=None, parent=gp_id, at=110)
    wide_win = D.grant_record("mid", "c5", k5.public, ["acceptor"], ["attest"], 99, 200, max_depth=1,
                              schemas=["task@1"], lineages=[w["task_root"]], parent=gp_id, at=110)
    snap = Snapshot(w["lines"] + [_line(gp, w["keys"]["bob"])] + [_line(x, kmid) for x in (wide_roles, wide_kinds, wide_schemas, wide_lin, wide_win)], {})
    gs = D.resolve_grants(snap, w["trust"], w["profile"], as_of=150)
    statuses = [gs.get(R.rid(x), {}).get("status") for x in (wide_roles, wide_kinds, wide_schemas, wide_lin, wide_win)]
    check("DG05 child widening on roles, kinds, schemas, lineages or time window fails closed with WIDENING",
          statuses == ["WIDENING"] * 5, statuses)

    # DG06: Depth exhaustion refused (parent depth 0 or child depth >= parent depth)
    w = _setup_base()
    km0, km1, kc0, kc1 = _key(), _key(), _key(), _key()
    g_d0 = D.grant_record("bob", "m0", km0.public, ["acceptor"], ["attest"], 100, 200, max_depth=0, at=100)
    g_d0_child = D.grant_record("m0", "c0", kc0.public, ["acceptor"], ["attest"], 100, 200, max_depth=0, parent=R.rid(g_d0), at=101)
    g_d1 = D.grant_record("bob", "m1", km1.public, ["acceptor"], ["attest"], 100, 200, max_depth=1, at=100)
    g_d1_same = D.grant_record("m1", "c1", kc1.public, ["acceptor"], ["attest"], 100, 200, max_depth=1, parent=R.rid(g_d1), at=101)
    snap = Snapshot(w["lines"] + [_line(g_d0, w["keys"]["bob"]), _line(g_d0_child, km0),
                                  _line(g_d1, w["keys"]["bob"]), _line(g_d1_same, km1)], {})
    gs = D.resolve_grants(snap, w["trust"], w["profile"], as_of=150)
    check("DG06 redelegation with max_depth == 0 or child max_depth >= parent max_depth refused as DEPTH_EXCEEDED",
          gs.get(R.rid(g_d0_child), {}).get("status") == "DEPTH_EXCEEDED"
          and gs.get(R.rid(g_d1_same), {}).get("status") == "DEPTH_EXCEEDED",
          (gs.get(R.rid(g_d0_child)), gs.get(R.rid(g_d1_same))))

    # DG07 & DG08: Direct revocation, transitive ancestral invalidation, and direct ancestral grandchild revocation
    w = _setup_base()
    kmid, kleaf = _key(), _key()
    g1 = D.grant_record("bob", "mid", kmid.public, ["acceptor"], ["attest"], 100, 300, max_depth=2, at=100)
    g1_id = R.rid(g1)
    g2 = D.grant_record("mid", "leaf", kleaf.public, ["acceptor"], ["attest"], 100, 300, max_depth=1, parent=g1_id, at=110)
    g2_id = R.rid(g2)
    att = R.record("attest", "leaf", 150, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
    att_id = R.rid(att)
    # (a) bob revokes g1 -> g1 REVOKED, g2 ANCESTOR_INVALID, att refused as DELEGATION_NOT_ACTIVE
    rev_g1 = D.revoke_from("bob", g1, g1_id, at=140, reason="compromised mid")
    snap_a = Snapshot(w["lines"] + [_line(g1, w["keys"]["bob"]), _line(g2, kmid), _line(rev_g1, w["keys"]["bob"]), _line(att, kleaf)], {})
    res_a = D.assess_delegated(snap_a, w["trust"], w["profile"], as_of=150)
    # (b) bob (root ancestor) directly revokes g2 while g1 stays ACTIVE!
    rev_g2_by_bob = D.revoke_from("bob", g2, g2_id, at=145, reason="root brake on grandchild")
    snap_b = Snapshot(w["lines"] + [_line(g1, w["keys"]["bob"]), _line(g2, kmid), _line(rev_g2_by_bob, w["keys"]["bob"]), _line(att, kleaf)], {})
    res_b = D.assess_delegated(snap_b, w["trust"], w["profile"], as_of=150)
    check("DG07 revoking parent grant invalidates parent (REVOKED), descendant (ANCESTOR_INVALID) and refuses descendant records",
          res_a["grants"].get(g1_id, {}).get("status") == "REVOKED"
          and res_a["grants"].get(g2_id, {}).get("status") == "ANCESTOR_INVALID"
          and any(x.get("id") == att_id and x.get("code") == "DELEGATION_NOT_ACTIVE" for x in res_a["refused"])
          and res_a["delegated_report"]["lineages"].get(w["task_root"], {}).get("state") == "open",
          (res_a["grants"], res_a["refused"]))
    check("DG08 transitive ancestral brake: root issuer can directly revoke a grandchild grant while parent remains ACTIVE",
          res_b["grants"].get(g1_id, {}).get("status") == "ACTIVE"
          and res_b["grants"].get(g2_id, {}).get("status") == "REVOKED"
          and res_b["delegated_report"]["lineages"].get(w["task_root"], {}).get("state") == "open",
          res_b["grants"])

    # DG09: Unauthorized third-party revocation is ignored
    w = _setup_base()
    ksub = _key()
    g1 = D.grant_record("bob", "bob-sub", ksub.public, ["acceptor"], ["attest"], 100, 300, at=100)
    g1_id = R.rid(g1)
    fake_rev = D.revoke_from("carol", g1, g1_id, at=120, reason="unauthorized")
    snap = Snapshot(w["lines"] + [_line(g1, w["keys"]["bob"]), _line(fake_rev, w["keys"]["carol"])], {})
    gs = D.resolve_grants(snap, w["trust"], w["profile"], as_of=150)
    check("DG09 unauthorized revocation by a non-ancestor actor is ignored and grant stays ACTIVE",
          gs.get(g1_id, {}).get("status") == "ACTIVE", gs.get(g1_id))

    # DG10: Forked grant lineage -> FORKED, descendant -> ANCESTOR_INVALID
    w = _setup_base()
    kmid, kleaf = _key(), _key()
    g1 = D.grant_record("bob", "mid", kmid.public, ["acceptor"], ["attest"], 100, 300, max_depth=2, at=100)
    g1_id = R.rid(g1)
    g2 = D.grant_record("mid", "leaf", kleaf.public, ["acceptor"], ["attest"], 100, 300, max_depth=1, parent=g1_id, at=110)
    g2_id = R.rid(g2)
    f1 = D.revoke_from("bob", g1, g1_id, at=120, reason="branch A")
    f2 = D.revoke_from("bob", g1, g1_id, at=121, reason="branch B")
    snap = Snapshot(w["lines"] + [_line(g1, w["keys"]["bob"]), _line(g2, kmid),
                                  _line(f1, w["keys"]["bob"]), _line(f2, w["keys"]["bob"])], {})
    gs = D.resolve_grants(snap, w["trust"], w["profile"], as_of=150)
    check("DG10 forked grant lineage yields FORKED with zero authority and ANCESTOR_INVALID for descendants",
          gs.get(g1_id, {}).get("status") == "FORKED"
          and gs.get(g2_id, {}).get("status") == "ANCESTOR_INVALID",
          gs)

    # DG11: Standing challenge by challenger invalidates grant and descendants
    w = _setup_base()
    kmid, kleaf = _key(), _key()
    g1 = D.grant_record("bob", "mid", kmid.public, ["acceptor"], ["attest"], 100, 300, max_depth=2, at=100)
    g1_id = R.rid(g1)
    g2 = D.grant_record("mid", "leaf", kleaf.public, ["acceptor"], ["attest"], 100, 300, max_depth=1, parent=g1_id, at=110)
    g2_id = R.rid(g2)
    ch = R.record("challenge", "dave", 130, {"target": g1_id, "claim": "leaked key"}, refs=[g1_id])
    snap = Snapshot(w["lines"] + [_line(g1, w["keys"]["bob"]), _line(g2, kmid), _line(ch, w["keys"]["dave"])], {})
    gs = D.resolve_grants(snap, w["trust"], w["profile"], as_of=150)
    check("DG11 standing challenge by challenger invalidates grant (CHALLENGED) and descendants (ANCESTOR_INVALID)",
          gs.get(g1_id, {}).get("status") == "CHALLENGED"
          and gs.get(g2_id, {}).get("status") == "ANCESTOR_INVALID",
          gs)

    # DG12: Time windows (NOT_YET_VALID, ACTIVE, EXPIRED, and record DELEGATION_OUTSIDE_WINDOW)
    w = _setup_base()
    ksub = _key()
    g = D.grant_record("bob", "bob-sub", ksub.public, ["acceptor"], ["attest"], 100, 200, at=50)
    gid = R.rid(g)
    att_early = R.record("attest", "bob-sub", 99, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
    snap = Snapshot(w["lines"] + [_line(g, w["keys"]["bob"]), _line(att_early, ksub)], {})
    gs_early = D.resolve_grants(snap, w["trust"], w["profile"], as_of=99)
    gs_late = D.resolve_grants(snap, w["trust"], w["profile"], as_of=201)
    res_mid = D.assess_delegated(snap, w["trust"], w["profile"], as_of=150)
    check("DG12 time window: NOT_YET_VALID before not_before, EXPIRED after not_after, record outside window refused",
          gs_early.get(gid, {}).get("status") == "NOT_YET_VALID"
          and gs_late.get(gid, {}).get("status") == "EXPIRED"
          and any(x.get("id") == R.rid(att_early) and x.get("code") == "DELEGATION_OUTSIDE_WINDOW" for x in res_mid["refused"]),
          (gs_early.get(gid), gs_late.get(gid), res_mid["refused"]))

    # DG13: Scope enforcement (disallowed kind, wrong lineage, unknown target)
    w = _setup_base()
    ksub = _key()
    other_root = R.record("entity", "alice", 22, {"state": "open", "title": "other"}, "task@1")
    other_done = R.record("entity", "alice", 23, {"state": "done", "title": "other"}, "task@1",
                          lineage=R.rid(other_root),
                          guard={"roles": ["acceptor"], "quorum": 1, "match": {"verdict": "accept"}, "requires": []})
    g = D.grant_record("bob", "bob-sub", ksub.public, ["acceptor"], ["attest"], 100, 200,
                       schemas=["task@1"], lineages=[w["task_root"]], at=100)
    att_other = R.record("attest", "bob-sub", 150, {"target": R.rid(other_done), "verdict": "accept"}, refs=[R.rid(other_done)])
    ch_disallowed = R.record("challenge", "bob-sub", 151, {"target": w["task_done"], "claim": "nope"}, refs=[w["task_done"]])
    att_missing = R.record("attest", "bob-sub", 152, {"target": "a" * 64, "verdict": "accept"}, refs=["a" * 64])
    snap = Snapshot(w["lines"] + [_line(other_root, w["keys"]["alice"]), _line(other_done, w["keys"]["alice"]),
                                  _line(g, w["keys"]["bob"]), _line(att_other, ksub),
                                  _line(ch_disallowed, ksub), _line(att_missing, ksub)], {})
    res = D.assess_delegated(snap, w["trust"], w["profile"], as_of=160)
    ref_map = {x["id"]: x["code"] for x in res["refused"]}
    check("DG13 scope enforcement refuses wrong lineage, disallowed kind, and unknown target",
          ref_map.get(R.rid(att_other)) == "DELEGATION_OUT_OF_SCOPE"
          and ref_map.get(R.rid(ch_disallowed)) == "DELEGATION_OUT_OF_SCOPE"
          and ref_map.get(R.rid(att_missing)) == "DELEGATION_UNKNOWN_TARGET",
          ref_map)

    # DG14: Anti-Laundering Theorem (DELEGATION_SELF_ACCEPT):
    # (a) alice -> alice-sub accepting alice's own version; (b) alice -> sub1 authoring, alice -> sub2 accepting
    w = _setup_base(extra_roles={"acceptor": ["alice", "bob", "carol"]})
    ks1, ks2 = _key(), _key()
    g_a1 = D.grant_record("alice", "a-sub-1", ks1.public, ["acceptor"], ["entity", "attest"], 100, 200, at=100)
    g_a2 = D.grant_record("alice", "a-sub-2", ks2.public, ["acceptor"], ["attest"], 100, 200, at=100)
    att_own = R.record("attest", "a-sub-1", 120, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
    sub_root = R.record("entity", "a-sub-1", 125, {"state": "done", "title": "sockpuppet"}, "task@1",
                        guard={"roles": ["acceptor"], "quorum": 1, "match": {"verdict": "accept"}, "requires": []})
    att_sock = R.record("attest", "a-sub-2", 130, {"target": R.rid(sub_root), "verdict": "accept"}, refs=[R.rid(sub_root)])
    snap = Snapshot(w["lines"] + [_line(g_a1, w["keys"]["alice"]), _line(g_a2, w["keys"]["alice"]),
                                  _line(att_own, ks1), _line(sub_root, ks1), _line(att_sock, ks2)], {})
    res = D.assess_delegated(snap, w["trust"], w["profile"], as_of=150)
    ref_map = {x["id"]: x["code"] for x in res["refused"]}
    check("DG14 anti-laundering: delegate cannot accept its root issuer's version OR another delegate of the same root",
          ref_map.get(R.rid(att_own)) == "DELEGATION_SELF_ACCEPT"
          and ref_map.get(R.rid(att_sock)) == "DELEGATION_SELF_ACCEPT"
          and res["delegated_report"]["lineages"].get(w["task_root"], {}).get("state") == "open"
          and res["delegated_report"]["lineages"].get(R.rid(sub_root), {}).get("reliance") == "PENDING",
          (ref_map, res["delegated_report"]["lineages"].get(w["task_root"])))

    # DG15: No-Sybil-Inflation Theorem (DELEGATION_QUORUM_INFLATION) on quorum=2
    w = _setup_base(quorum=2)
    kb1, kb2, kc1 = _key(), _key(), _key()
    gb1 = D.grant_record("bob", "bob-sub-1", kb1.public, ["acceptor"], ["attest"], 100, 200, at=100)
    gb2 = D.grant_record("bob", "bob-sub-2", kb2.public, ["acceptor"], ["attest"], 100, 200, at=100)
    gc1 = D.grant_record("carol", "carol-sub", kc1.public, ["acceptor"], ["attest"], 100, 200, at=100)
    a_b1 = R.record("attest", "bob-sub-1", 120, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
    a_b2 = R.record("attest", "bob-sub-2", 121, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
    a_c1 = R.record("attest", "carol-sub", 122, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
    # Two delegates of bob alone MUST NOT meet quorum=2!
    snap_sybil = Snapshot(w["lines"] + [_line(gb1, w["keys"]["bob"]), _line(gb2, w["keys"]["bob"]),
                                        _line(a_b1, kb1), _line(a_b2, kb2)], {})
    res_sybil = D.assess_delegated(snap_sybil, w["trust"], w["profile"], as_of=150)
    # Adding independent carol-sub meets quorum=2!
    snap_ok = Snapshot(snap_sybil.raw + [_line(gc1, w["keys"]["carol"]), _line(a_c1, kc1)], {})
    res_ok = D.assess_delegated(snap_ok, w["trust"], w["profile"], as_of=150)
    sybil_refs = {x["code"] for x in res_sybil["refused"]}
    check("DG15 No-Sybil-Inflation: two delegates of bob cannot meet quorum=2 (DELEGATION_QUORUM_INFLATION); independent carol-sub completes it",
          "DELEGATION_QUORUM_INFLATION" in sybil_refs
          and res_sybil["delegated_report"]["lineages"].get(w["task_root"], {}).get("state") == "open"
          and res_ok["delegated_report"]["lineages"].get(w["task_root"], {}).get("state") == "done"
          and res_ok["delegated_report"]["lineages"].get(w["task_root"], {}).get("reliance") == "ELIGIBLE",
          (sybil_refs, res_sybil["delegated_report"]["lineages"].get(w["task_root"]),
           res_ok["delegated_report"]["lineages"].get(w["task_root"])))

    # DG16: Cross-grant role isolation (delegate holds r1 on L1 and r2 on L2; L1 requires r2 -> MUST NOT bleed!)
    w = _setup_base()
    s_r2 = R.record("schema", "alice", 14, _schema_guarded("r2only@1", ["r2"], 1), None)
    s_r2_b = R.record("attest", "bob", 15, {"target": R.rid(s_r2), "verdict": "accept"}, refs=[R.rid(s_r2)])
    gd_r2 = {"roles": ["r2"], "quorum": 1, "match": {"verdict": "accept"}, "requires": []}
    l1 = R.record("entity", "alice", 25, {"state": "open", "title": "needs r2"}, "r2only@1")
    l1_done = R.record("entity", "alice", 26, {"state": "done", "title": "needs r2"}, "r2only@1",
                       lineage=R.rid(l1), guard=gd_r2)
    l2 = R.record("entity", "alice", 27, {"state": "open", "title": "other"}, "r2only@1")
    l2_done = R.record("entity", "alice", 28, {"state": "done", "title": "other"}, "r2only@1",
                       lineage=R.rid(l2), guard=gd_r2)
    kw = _key()
    g_r1_l1 = D.grant_record("bob", "worker", kw.public, ["r1"], ["attest"], 100, 200, lineages=[R.rid(l1)], at=100)
    g_r2_l2 = D.grant_record("bob", "worker", kw.public, ["r2"], ["attest"], 100, 200, lineages=[R.rid(l2)], at=101)
    att_l1 = R.record("attest", "worker", 150, {"target": R.rid(l1_done), "verdict": "accept"}, refs=[R.rid(l1_done)])
    att_l2 = R.record("attest", "worker", 151, {"target": R.rid(l2_done), "verdict": "accept"}, refs=[R.rid(l2_done)])
    snap = Snapshot(w["lines"] + [
        _line(s_r2, w["keys"]["alice"]), _line(s_r2_b, w["keys"]["bob"]),
        _line(l1, w["keys"]["alice"]), _line(l1_done, w["keys"]["alice"]),
        _line(l2, w["keys"]["alice"]), _line(l2_done, w["keys"]["alice"]),
        _line(g_r1_l1, w["keys"]["bob"]), _line(g_r2_l2, w["keys"]["bob"]),
        _line(att_l1, kw), _line(att_l2, kw),
    ], {})
    res = D.assess_delegated(snap, w["trust"], w["profile"], as_of=160)
    ref_map = {x["id"]: x["code"] for x in res["refused"]}
    check("DG16 cross-grant role isolation: worker's r2 on L2 never bleeds onto L1 where it only holds r1",
          ref_map.get(R.rid(att_l1)) == "DELEGATION_OUT_OF_SCOPE"
          and res["delegated_report"]["lineages"].get(R.rid(l1), {}).get("state") == "open"
          and res["delegated_report"]["lineages"].get(R.rid(l2), {}).get("state") == "done",
          (ref_map, res["delegated_report"]["lineages"].get(R.rid(l1)), res["delegated_report"]["lineages"].get(R.rid(l2))))

    # DG17: Unanchored signer & self-delegation cycle refused
    w = _setup_base()
    krogue, kself = _key(), w["keys"]["bob"]
    g_unanch = D.grant_record("rogue", "r-sub", _key().public, ["acceptor"], ["attest"], 100, 200, at=100)
    g_self = D.grant_record("bob", "bob", kself.public, ["acceptor"], ["attest"], 100, 200, at=100)
    snap = Snapshot(w["lines"] + [_line(g_unanch, krogue), _line(g_self, kself)], {})
    gs = D.resolve_grants(snap, w["trust"], w["profile"], as_of=150)
    check("DG17 unanchored issuer yields UNANCHORED and same-key self-delegation yields CYCLE",
          gs.get(R.rid(g_unanch), {}).get("status") == "UNANCHORED"
          and gs.get(R.rid(g_self), {}).get("status") == "CYCLE",
          gs)

    # DG18: Delegated challenge lowers reliance to CHALLENGED when holding challenger role
    w = _setup_base()
    ksub = _key()
    # Bob statically accepts task_done so static reliance is ELIGIBLE
    att_bob = R.record("attest", "bob", 30, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
    g_ch = D.grant_record("dave", "dave-bot", ksub.public, ["challenger"], ["challenge"], 100, 200, at=100)
    ch = R.record("challenge", "dave-bot", 150, {"target": w["task_done"], "claim": "counterexample"}, refs=[w["task_done"]])
    snap = Snapshot(w["lines"] + [_line(att_bob, w["keys"]["bob"]), _line(g_ch, w["keys"]["dave"]), _line(ch, ksub)], {})
    res = D.assess_delegated(snap, w["trust"], w["profile"], as_of=160)
    check("DG18 delegated challenge by challenger's sub-agent lowers reliance ELIGIBLE -> CHALLENGED",
          res["static_report"]["lineages"].get(w["task_root"], {}).get("reliance") == "ELIGIBLE"
          and res["delegated_report"]["lineages"].get(w["task_root"], {}).get("reliance") == "CHALLENGED",
          (res["static_report"]["lineages"].get(w["task_root"]), res["delegated_report"]["lineages"].get(w["task_root"])))

    # DG19: CLI `warrant delegate` end-to-end (schema, grant, grants, assess, revoke)
    with tempfile.TemporaryDirectory(prefix="warrant-delegate-cli-") as td, \
            tempfile.TemporaryDirectory(dir="/tmp", prefix="warrant-dg-keys-") as ktd:
        root = Path(td) / "repo"
        root.mkdir()
        st = Store(root / ".warrant")
        st.init()
        w = _setup_base()
        st.add_lines(w["lines"])
        (root / ".warrant" / "v3.json").write_text(json.dumps({
            "warrant": "repository/3", "repository": "test/delegate",
            "trust": w["trust"], "profile": w["profile"],
        }))
        bob_seed = Path(ktd) / "bob.seed"
        bob_seed.write_text(w["keys"]["bob"].seed_hex())
        bob_seed.chmod(0o600)
        ksub = _key()
        import time
        now = int(time.time())
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        def cli(*args):
            return subprocess.run([sys.executable, "-m", "warrant.delegate", *args],
                                  capture_output=True, text=True, env=env, check=False)
        p1 = cli("--root", str(root), "grant", "--actor", "bob", "--key", str(bob_seed),
                 "--to", "bob-cli", "--pub", ksub.public, "--role", "acceptor", "--kind", "attest",
                 "--not-before", str(now - 60), "--not-after", str(now + 600), "--at", str(now))
        gid = json.loads(p1.stdout).get("grant") if p1.returncode == 0 else None
        att = R.record("attest", "bob-cli", now + 10, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
        st.add_lines([_line(att, ksub)])
        p2 = cli("--root", str(root), "assess", "--as-of", str(now + 20), "--json")
        out_assess = json.loads(p2.stdout) if p2.returncode == 0 else {}
        p3 = cli("--root", str(root), "revoke", gid or ("0" * 64), "--actor", "bob", "--key", str(bob_seed),
                 "--at", str(now + 30), "--reason", "done")
        p4 = cli("--root", str(root), "grants", "--as-of", str(now + 40), "--json")
        out_grants = json.loads(p4.stdout) if p4.returncode == 0 else {}
        check("DG19 CLI `warrant delegate grant|assess|revoke|grants` works end-to-end on a repository store",
              (p1.returncode, p2.returncode, p3.returncode, p4.returncode) == (0, 0, 0, 0)
              and len(out_assess.get("changes", [])) == 1
              and out_grants.get(gid, {}).get("status") == "REVOKED",
              (p1.returncode, p2.returncode, p3.returncode, p4.returncode, p1.stderr, out_assess.get("changes"), out_grants.get(gid)))


def main():
    delegate_cases()
    return finish("delegate_test")


if __name__ == "__main__":
    sys.exit(main())
