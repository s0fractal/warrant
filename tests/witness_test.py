#!/usr/bin/env python3
"""Proof-carrying guarantee witnesses (`warrant.witness`, `pact@1` + `grant@1` escrow + `minds` bridge).

    python3 tests/witness_test.py
"""
import hashlib
import sys

from world import Repo, check, run_sections

from warrant import delegate as D
from warrant import jcs as C
from warrant import pact as P
from warrant import records as R
from warrant import witness as W
from warrant.store import Snapshot


def _snap(envs, blobs=None):
    return Snapshot([C.canon(e) + b"\n" for e in envs], blobs or {}, sort=True)


def _cert_blob(body):
    raw = W.canonical_json_bytes(body)
    return hashlib.sha256(raw).hexdigest(), raw


def _viab_cert(ratio=1.0, blocked=(), ctrl=("0", "1", "2"), live=True, verified=True):
    return _cert_blob({
        "schema": "vars1-coalition-viability@1",
        "label": "a2a-floor",
        "live_env": live,
        "dead_pairs": [],
        "safe": list(ctrl) + list(blocked),
        "angelic_viability": list(ctrl) + list(blocked),
        "controllable_viability": list(ctrl),
        "blocked_states": list(blocked),
        "sovereign_ratio": ratio,
        "policy": {s: "act" for s in ctrl},
        "policy_verified": verified,
        "policy_info": {"verified_states": len(ctrl)},
    })


def witness_cases():
    repo = Repo()
    trust, profile = repo.trust, repo.profile
    sa, sb = (repo.seed(x).read_text().strip() for x in ("alice", "bob"))
    alice_role = sorted(r for r, actors in profile["roles"].items() if "alice" in actors)[0]

    # WT01: sha256-blob@1 verifies existing blob and refuses missing / tampered / undersized blobs
    blob_bytes = b"deterministic-evidence-payload"
    blob_dig = hashlib.sha256(blob_bytes).hexdigest()
    snap_b = _snap([], {blob_dig: blob_bytes})
    snap_tamp = _snap([], {blob_dig: b"tampered-payload"})
    ok1, r1 = W.verify_witness({"verifier": "sha256-blob@1", "params": {"min_bytes": 10}}, blob_dig, snap_b, {}, 10)
    ok2, r2 = W.verify_witness({"verifier": "sha256-blob@1", "params": {}}, blob_dig, _snap([]), {}, 10)
    ok3, r3 = W.verify_witness({"verifier": "sha256-blob@1", "params": {}}, blob_dig, snap_tamp, {}, 10)
    ok4, r4 = W.verify_witness({"verifier": "sha256-blob@1", "params": {"min_bytes": 999}}, blob_dig, snap_b, {}, 10)
    check("WT01 sha256-blob@1 accepts matching blob and refuses missing, tampered, or undersized blobs",
          ok1 and r1 == "OK" and not ok2 and r2 == "BLOB_MISSING"
          and not ok3 and r3 == "DIGEST_MISMATCH" and not ok4 and r4 == "BLOB_TOO_SMALL",
          (ok1, r1, ok2, r2, ok3, r3, ok4, r4))

    # WT02: vars1-coalition-viability@1 verifies live_env, policy_verified, sovereign_ratio, max_blocked, required_states
    vd_ok, vb_ok = _viab_cert(ratio=0.75, blocked=("3",), ctrl=("0", "1", "2"))
    vd_dead, vb_dead = _viab_cert(live=False)
    vd_unver, vb_unver = _viab_cert(verified=False)
    snap_v = _snap([], {vd_ok: vb_ok, vd_dead: vb_dead, vd_unver: vb_unver})
    v_pass, vr_pass = W.verify_witness(
        {"verifier": "vars1-coalition-viability@1",
         "params": {"min_sovereign_bps": 7500, "max_blocked_states": 1, "required_states": ["0", "2"]}},
        vd_ok, snap_v, {}, 10)
    v_ratio, vr_ratio = W.verify_witness(
        {"verifier": "vars1-coalition-viability@1", "params": {"min_sovereign_bps": 9000}},
        vd_ok, snap_v, {}, 10)
    v_blk, vr_blk = W.verify_witness(
        {"verifier": "vars1-coalition-viability@1", "params": {"max_blocked_states": 0}},
        vd_ok, snap_v, {}, 10)
    v_req, vr_req = W.verify_witness(
        {"verifier": "vars1-coalition-viability@1", "params": {"required_states": ["3"]}},
        vd_ok, snap_v, {}, 10)
    v_dead, vr_dead = W.verify_witness({"verifier": "vars1-coalition-viability@1"}, vd_dead, snap_v, {}, 10)
    v_unv, vr_unv = W.verify_witness({"verifier": "vars1-coalition-viability@1"}, vd_unver, snap_v, {}, 10)
    check("WT02 vars1-coalition-viability@1 enforces live_env, policy_verified, ratio, blocked cap, and required states",
          v_pass and vr_pass == "OK"
          and not v_ratio and vr_ratio == "SOVEREIGN_RATIO_BELOW_THRESHOLD"
          and not v_blk and vr_blk == "BLOCKED_STATES_EXCEEDED"
          and not v_req and vr_req == "REQUIRED_STATE_NOT_VIABLE"
          and not v_dead and vr_dead == "ENV_NOT_LIVE"
          and not v_unv and vr_unv == "POLICY_UNVERIFIED",
          (vr_pass, vr_ratio, vr_blk, vr_req, vr_dead, vr_unv))

    # WT03: vars1-spore-receipt@1 enforces SETTLED, strict ATP conservation, max_atp_spent, and non-inflation
    spore_id = hashlib.sha256(b"spore-frame-1").hexdigest()
    sd_ok, sb_ok = W.make_spore_receipt_blob(spore_digest=spore_id, atp_budget=100, atp_spent=40, atp_remaining=60)
    sd_bad_atp, sb_bad_atp = W.make_spore_receipt_blob(spore_digest=spore_id, atp_budget=100, atp_spent=40, atp_remaining=70)
    sd_inf, sb_inf = W.make_spore_receipt_blob(spore_digest=spore_id, atp_budget=100, atp_spent=40, atp_remaining=60,
                                               partiality_inflated=True)
    snap_s = _snap([], {sd_ok: sb_ok, sd_bad_atp: sb_bad_atp, sd_inf: sb_inf})
    s_ok, sr_ok = W.verify_witness(
        {"verifier": "vars1-spore-receipt@1", "params": {"max_atp_spent": 50, "spore_digest": spore_id}},
        sd_ok, snap_s, {}, 10)
    s_cons, sr_cons = W.verify_witness({"verifier": "vars1-spore-receipt@1"}, sd_bad_atp, snap_s, {}, 10)
    s_inf, sr_inf = W.verify_witness({"verifier": "vars1-spore-receipt@1"}, sd_inf, snap_s, {}, 10)
    s_over, sr_over = W.verify_witness(
        {"verifier": "vars1-spore-receipt@1", "params": {"max_atp_spent": 20}}, sd_ok, snap_s, {}, 10)
    check("WT03 vars1-spore-receipt@1 enforces SETTLED, ATP conservation, partiality non-inflation, and budget cap",
          s_ok and sr_ok == "OK"
          and not s_cons and sr_cons == "ATP_CONSERVATION_VIOLATED"
          and not s_inf and sr_inf == "PARTIALITY_INFLATED"
          and not s_over and sr_over == "ATP_SPENT_EXCEEDED",
          (sr_ok, sr_cons, sr_inf, sr_over))

    # WT04: warrant-record@1 enforces signature-verified record AND horizon at <= as_of (no future leak)
    rec_env = P._sign_env(R.record("entity", "alice", 50, {"state": "open", "statement": "s", "serves": []},
                                   schema="obligation@1"), sa)
    rec_id = R.rid(rec_env["record"])
    snap_r = _snap([rec_env])
    valid_r, _ = P._extract_verified_records(snap_r, trust)
    wr_past, wrr_past = W.verify_witness({"verifier": "warrant-record@1", "params": {"actor": "alice"}},
                                         rec_id, snap_r, valid_r, as_of=40)
    wr_now, wrr_now = W.verify_witness(
        {"verifier": "warrant-record@1", "params": {"actor": "alice", "schema": "obligation@1", "state": "open"}},
        rec_id, snap_r, valid_r, as_of=50)
    wr_unk, wrr_unk = W.verify_witness({"verifier": "no-such-verifier@9"}, rec_id, snap_r, valid_r, as_of=50)
    check("WT04 warrant-record@1 refuses records dated after as_of, admits at <= as_of, and fails closed on unknown verifier",
          not wr_past and wrr_past == "RECORD_AFTER_AS_OF"
          and wr_now and wrr_now == "OK"
          and not wr_unk and wrr_unk == "UNKNOWN_VERIFIER",
          (wrr_past, wrr_now, wrr_unk))

    # WT05: proposal rejects witness key not in gives (WITNESS_KEY_NOT_IN_GIVES)
    bad_prop = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments={
        "alice": {"gives": ["signed"], "witnesses": {"ghost": {"verifier": "sha256-blob@1"}}},
        "bob": {"gives": ["done"]},
    }, expires_at=100, purpose="bad-wkey", at=5)
    r_bad_p = P.resolve_pacts(_snap([bad_prop]), trust, as_of=10).get(R.rid(bad_prop["record"]), {})
    check("WT05 proposal referencing witness key outside gives is rejected as INVALID",
          r_bad_p.get("status") == "INVALID" and "WITNESS_KEY_NOT_IN_GIVES" in r_bad_p.get("reason", ""),
          r_bad_p)

    # WT06: End-to-end A2A seam: grant@1 (settled-mode escrow) + pact@1 requiring BOTH spore receipt & viability cert!
    # An ungrounded fulfill is REFUSED (UNGROUNDED_GUARANTEE), keeping pact ACTIVE and escrowed grant ESCROW_FROZEN.
    g_rec = D.grant_record("alice", "carol", trust["keys"]["carol"][0],
                           roles=[alice_role], kinds=["attest"],
                           not_before=0, not_after=200, max_depth=1, at=5)
    g_env = P._sign_env(g_rec, sa)
    gid = R.rid(g_env["record"])

    prop_a2a = P.make_proposal(
        "alice", sa,
        parties=["alice", "bob"],
        commitments={
            "alice": {
                "requires": [],
                "gives": ["task_funded"],
                "witnesses": {"task_funded": {"verifier": "sha256-blob@1"}},
            },
            "bob": {
                "requires": ["task_funded"],
                "gives": ["spore_settled", "viable_floor"],
                "witnesses": {
                    "spore_settled": {"verifier": "vars1-spore-receipt@1", "params": {"max_atp_spent": 50}},
                    "viable_floor": {"verifier": "vars1-coalition-viability@1", "params": {"min_sovereign_bps": 7500}},
                },
            },
        },
        expires_at=100,
        purpose="a2a-proof-carrying-handoff",
        escrow_grants=[gid],
        escrow_mode="settled",
        at=10,
    )
    pid = R.rid(prop_a2a["record"])
    acc_a = P.make_accept("alice", sa, pid, at=11)
    acc_b = P.make_accept("bob", sb, pid, at=12)
    ful_a = P.make_fulfill("alice", sa, pid, evidence_digest=blob_dig, delivered=["task_funded"], at=15)

    # Fake fulfill by bob with random evidence_digest and missing blobs -> UNGROUNDED_GUARANTEE!
    fake_dig = hashlib.sha256(b"empty-claim").hexdigest()
    ful_b_fake = P.make_fulfill("bob", sb, pid, evidence_digest=fake_dig,
                                delivered=["spore_settled", "viable_floor"], at=16)
    snap_ungr = _snap([g_env, prop_a2a, acc_a, acc_b, ful_a, ful_b_fake], {blob_dig: blob_bytes})
    res_ungr = P.resolve_pacts(snap_ungr, trust, as_of=20).get(pid, {})
    dg_frozen = D.assess_delegated(snap_ungr, trust, profile, as_of=20).get("grants", {}).get(gid, {})
    ungr_codes = [e.get("code") for e in res_ungr.get("refused_events", [])]
    check("WT06 ungrounded fulfillment is refused (UNGROUNDED_GUARANTEE), keeping pact ACTIVE and settled-mode grant ESCROW_FROZEN",
          res_ungr.get("status") == "ACTIVE"
          and "bob" not in res_ungr.get("fulfilled", {})
          and "UNGROUNDED_GUARANTEE" in ungr_codes
          and dg_frozen.get("status") == "ESCROW_FROZEN",
          (res_ungr, dg_frozen))

    # WT07: Real multi-witness fulfillment by bob (both spore receipt + coalition viability cert) -> SETTLED & escrow UNLOCKED!
    ful_b_real = P.make_fulfill(
        "bob", sb, pid,
        evidence_digest=sd_ok,
        witness_digests={"spore_settled": sd_ok, "viable_floor": vd_ok},
        delivered=["spore_settled", "viable_floor"],
        at=18,
    )
    snap_ok = _snap([g_env, prop_a2a, acc_a, acc_b, ful_a, ful_b_real],
                    {blob_dig: blob_bytes, sd_ok: sb_ok, vd_ok: vb_ok})
    res_ok = P.resolve_pacts(snap_ok, trust, as_of=20).get(pid, {})
    dg_live = D.assess_delegated(snap_ok, trust, profile, as_of=20).get("grants", {}).get(gid, {})
    check("WT07 valid multi-witness fulfillment settles pact to SETTLED and unlocks settled-mode grant@1 to ACTIVE",
          res_ok.get("status") == "SETTLED"
          and sorted(res_ok.get("fulfilled", {}).get("bob", {}).get("verified_witnesses", {}).keys()) == ["spore_settled", "viable_floor"]
          and dg_live.get("status") == "ACTIVE",
          (res_ok, dg_live))

    # WT08: Equivocation on witness_digests (same evidence_digest, conflicting per-label witness_digests) triggers BREACHED!
    ful_b_eq1 = P.make_fulfill("bob", sb, pid, evidence_digest=sd_ok,
                               witness_digests={"spore_settled": sd_ok, "viable_floor": vd_ok},
                               delivered=["spore_settled", "viable_floor"], at=18)
    ful_b_eq2 = P.make_fulfill("bob", sb, pid, evidence_digest=sd_ok,
                               witness_digests={"spore_settled": sd_ok, "viable_floor": vd_dead},
                               delivered=["spore_settled", "viable_floor"], at=19)
    res_eq = P.resolve_pacts(
        _snap([g_env, prop_a2a, acc_a, acc_b, ful_a, ful_b_eq1, ful_b_eq2],
              {blob_dig: blob_bytes, sd_ok: sb_ok, vd_ok: vb_ok, vd_dead: vb_dead}),
        trust, as_of=20,
    ).get(pid, {})
    check("WT08 conflicting witness_digests under identical evidence_digest trigger EQUIVOCATION",
          res_eq.get("status") == "BREACHED" and res_eq.get("reason") == "EQUIVOCATION"
          and res_eq.get("defaulters") == ["bob"],
          res_eq)

    # WT09: Typed composition rejects VERIFIER_SPEC_MISMATCH (string label matches, verifier/params differ or ungrounded)
    r_weak = P.make_recipe("lint_only", requires=[], gives=["verified"],
                           witnesses={"verified": {"verifier": "sha256-blob@1"}})
    r_ungr = P.make_recipe("prose_only", requires=[], gives=["verified"])
    r_strict = P.make_recipe(
        "deploy", requires=["verified"], gives=["deployed"], preserves=["verified"],
        required_witnesses={"verified": {"verifier": "vars1-coalition-viability@1", "params": {"min_sovereign_bps": 10000}}},
    )
    r_match = P.make_recipe(
        "prove", requires=[], gives=["verified"],
        witnesses={"verified": {"verifier": "vars1-coalition-viability@1", "params": {"min_sovereign_bps": 10000}}},
    )
    c_mis1 = P.compose_recipes([r_weak, r_strict])
    c_mis2 = P.compose_recipes([r_ungr, r_strict])
    c_good = P.compose_recipes([r_match, r_strict])
    check("WT09 compose_recipes refuses VERIFIER_SPEC_MISMATCH (wrong verifier or ungrounded string) and admits exact spec match",
          c_mis1.get("well_typed") is False
          and any(e.get("code") == "VERIFIER_SPEC_MISMATCH" for e in c_mis1.get("errors", []))
          and c_mis2.get("well_typed") is False
          and any(e.get("code") == "VERIFIER_SPEC_MISMATCH" for e in c_mis2.get("errors", []))
          and c_good.get("well_typed") is True and c_good.get("lossless") is True
          and "verified" in c_good.get("witness_specs", {}),
          (c_mis1, c_mis2, c_good))

    # WT10: Anti-laundering — re-giving a witnessed guarantee without a witness strips its witness spec
    r_overwrite = P.make_recipe("overwrite_unverified", requires=["verified"], gives=["verified"])
    c_strip = P.compose_recipes([r_match, r_overwrite, r_strict])
    check("WT10 overwriting a witnessed guarantee with an ungrounded give strips its witness spec and fails downstream",
          c_strip.get("well_typed") is False
          and any(e.get("code") == "VERIFIER_SPEC_MISMATCH" and e.get("step") == 2 for e in c_strip.get("errors", [])),
          c_strip)

    # WT11: Internal consumer required_witnesses enforced at settlement, escrow, and recipe extraction (Codex F1)
    strict_blob = {"verifier": "sha256-blob@1", "params": {"min_bytes": 100}}
    weak_blob = {"verifier": "sha256-blob@1", "params": {"min_bytes": 1}}
    prop_int = P.make_proposal(
        "alice", sa, parties=["alice", "bob"],
        commitments={
            "alice": {"gives": ["verified"]},
            "bob": {"requires": ["verified"], "required_witnesses": {"verified": strict_blob}, "gives": ["deployed"]},
        },
        purpose="internal consumer witness enforcement", expires_at=100,
        escrow_grants=[gid], escrow_mode="settled", at=10,
    )
    pid_int = R.rid(prop_int["record"])
    snap_int = _snap([
        g_env, prop_int, P.make_accept("alice", sa, pid_int, at=11), P.make_accept("bob", sb, pid_int, at=12),
        P.make_fulfill("alice", sa, pid_int, evidence_digest="a" * 64, delivered=["verified"], at=15),
        P.make_fulfill("bob", sb, pid_int, evidence_digest="b" * 64, delivered=["deployed"], at=16),
    ])
    res_int = P.resolve_pacts(snap_int, trust, 20)[pid_int]
    esc_int = P.resolve_escrow(snap_int, trust, profile, 20)
    int_err = None
    try:
        P.pact_to_recipe(res_int)
    except ValueError as exc:
        int_err = str(exc)
    check("WT11 unwitnessed internal handoff cannot settle pact, unlock escrow, or compose as well-typed",
          res_int["status"] == "ACTIVE"
          and any(e["code"] == "UNGROUNDED_GUARANTEE" for e in res_int.get("refused_events", []))
          and esc_int["escrow"][gid]["escrow_allowed"] is False
          and int_err == "INTERNAL_WITNESS_UNSATISFIED:verified",
          (res_int["status"], res_int.get("refused_events"), esc_int["escrow"].get(gid), int_err))

    # WT12: Conflicting external required_witnesses across parties rejected regardless of order (Codex F2)
    def _conflicting_rw_err(spec_a, spec_b):
        pr = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments={
            "alice": {"requires": ["in"], "required_witnesses": {"in": spec_a}, "gives": ["s1"]},
            "bob": {"requires": ["in"], "required_witnesses": {"in": spec_b}, "gives": ["s2"]},
        }, purpose="conflict", expires_at=100, at=10)
        pid_c = R.rid(pr["record"])
        sn = _snap([pr, P.make_accept("alice", sa, pid_c, at=11), P.make_accept("bob", sb, pid_c, at=12)])
        try:
            P.pact_to_recipe(P.resolve_pacts(sn, trust, 20)[pid_c])
            return None
        except ValueError as exc:
            return str(exc)

    err_sw, err_ws = _conflicting_rw_err(strict_blob, weak_blob), _conflicting_rw_err(weak_blob, strict_blob)
    check("WT12 conflicting external required_witnesses across parties are rejected in either party order",
          err_sw == "CONFLICTING_REQUIRED_WITNESS:in" and err_ws == "CONFLICTING_REQUIRED_WITNESS:in",
          (err_sw, err_ws))

    # WT13: Oversized integer in viability certificate is refused cleanly without aborting resolve_pacts (Codex F3)
    huge_dig, huge_bytes = _viab_cert(ratio=10 ** 400)
    ful_b_huge = P.make_fulfill(
        "bob", sb, pid, evidence_digest=sd_ok,
        witness_digests={"spore_settled": sd_ok, "viable_floor": huge_dig},
        delivered=["spore_settled", "viable_floor"], at=18,
    )
    snap_huge = _snap([g_env, prop_a2a, acc_a, acc_b, ful_a, ful_b_huge],
                      {blob_dig: blob_bytes, sd_ok: sb_ok, huge_dig: huge_bytes})
    res_huge = P.resolve_pacts(snap_huge, trust, 20)[pid]
    check("WT13 oversized integer sovereign_ratio fails closed as UNGROUNDED_GUARANTEE without OverflowError",
          res_huge["status"] == "ACTIVE"
          and any(e.get("code") == "UNGROUNDED_GUARANTEE"
                  and e.get("failed_witnesses", {}).get("viable_floor", {}).get("reason") == "BAD_SOVEREIGN_RATIO"
                  for e in res_huge.get("refused_events", [])),
          (res_huge["status"], res_huge.get("refused_events")))

    # WT14: Same-party required_witnesses on a label that party also gives still gates settlement & escrow (Codex P1 #2)
    prop_self = P.make_proposal(
        "alice", sa, parties=["alice", "bob"],
        commitments={
            "alice": {"requires": ["verified"], "gives": ["verified"], "required_witnesses": {"verified": strict_blob}},
            "bob": {"gives": ["done"]},
        },
        purpose="same-party required witness enforcement", expires_at=100,
        escrow_grants=[gid], escrow_mode="settled", at=10,
    )
    pid_self = R.rid(prop_self["record"])
    snap_self = _snap([
        g_env, prop_self, P.make_accept("alice", sa, pid_self, at=11), P.make_accept("bob", sb, pid_self, at=12),
        P.make_fulfill("alice", sa, pid_self, evidence_digest="a" * 64, delivered=["verified"], at=15),
        P.make_fulfill("bob", sb, pid_self, evidence_digest="b" * 64, delivered=["done"], at=16),
    ])
    res_self = P.resolve_pacts(snap_self, trust, 20)[pid_self]
    esc_self = P.resolve_escrow(snap_self, trust, profile, 20)["escrow"][gid]
    dg_self = D.assess_delegated(snap_self, trust, profile, 20)["grants"][gid]
    check("WT14 same-party required_witnesses on a self-given label blocks settlement and keeps escrow frozen",
          res_self["status"] == "ACTIVE" and "alice" not in res_self["fulfilled"]
          and any(e.get("code") == "UNGROUNDED_GUARANTEE" for e in res_self.get("refused_events", []))
          and esc_self["escrow_allowed"] is False and dg_self["status"] == "ESCROW_FROZEN",
          (res_self["status"], res_self["fulfilled"], esc_self["escrow_allowed"], dg_self["status"]))

    # WT15: Handoff export carries witness blobs via fulfillment refs for both evidence_digest & witness_digests (Codex P2)
    import base64
    from warrant_agent import api as agent_api
    from warrant_agent.config import Config

    ho_ok = []
    for per_label in (False, True):
        src = Repo()
        src.put("alice", "schema", P.SCHEMA)
        t0 = src.t + 10
        bdig = src.blob(b"proof-carrying-handoff-blob")
        pr_h = P.make_proposal(
            "alice", sa, parties=["alice", "bob"],
            commitments={
                "alice": {"gives": ["verified"], "witnesses": {"verified": {"verifier": "sha256-blob@1"}}},
                "bob": {"gives": ["done"]},
            }, expires_at=t0 + 100, purpose="handoff witness refs", at=t0,
        )
        pid_h = R.rid(pr_h["record"])
        ful_h = P.make_fulfill(
            "alice", sa, pid_h,
            evidence_digest="b" * 64 if per_label else bdig,
            delivered=["verified"],
            witness_digests={"verified": bdig} if per_label else None, at=t0 + 3,
        )
        src.store.add_lines([C.canon(e) + b"\n" for e in [
            pr_h, P.make_accept("alice", sa, pid_h, at=t0 + 1), P.make_accept("bob", sb, pid_h, at=t0 + 2),
            ful_h, P.make_fulfill("bob", sb, pid_h, evidence_digest="a" * 64, delivered=["done"], at=t0 + 4),
        ]])
        cfg = Config({"agent_api": "warrant-agent/3", "workspaces": {"w": {
            "repo": str(src.root), "signer": {"actor": "bob", "key": str(src.seed("bob"))},
        }}})
        pkg = agent_api.call(cfg, "handoff", {"workspace": "w", "op": "export", "targets": [pid_h]})["ok"]["package"]
        recv = Snapshot([x.encode() + b"\n" for x in pkg["lines"]],
                        {h: base64.b64decode(b) for h, b in pkg["blobs"].items()})
        ho_ok.append((
            per_label,
            P.resolve_pacts(src.store.snapshot(), src.trust, t0 + 10)[pid_h]["status"],
            P.resolve_pacts(recv, src.trust, t0 + 10)[pid_h]["status"],
            bdig in pkg["blobs"] and bdig in ful_h["record"]["refs"],
        ))
    check("WT15 handoff export carries witness blobs through fulfillment refs so remote settlement reproduces",
          all(s1 == s2 == "SETTLED" and has_b for _, s1, s2, has_b in ho_ok), ho_ok)

    # WT16: Duplicate or inconsistent viability state sets are refused and cannot unlock escrow (Codex P2)
    base_cert = {
        "schema": "vars1-coalition-viability@1", "label": "half", "live_env": True, "dead_pairs": [],
        "safe": ["0", "1"], "angelic_viability": ["0", "1"], "controllable_viability": ["0"],
        "blocked_states": ["1"], "sovereign_ratio": 0.5, "policy": {"0": "act"},
        "policy_verified": True, "policy_info": {"verified_states": 1},
    }
    dup_dig, dup_raw = _cert_blob(dict(base_cert, controllable_viability=["0", "0"]))
    ovl_dig, ovl_raw = _cert_blob(dict(base_cert, controllable_viability=["0", "1"], blocked_states=["1"], sovereign_ratio=1.0))
    rat_dig, rat_raw = _cert_blob(dict(base_cert, sovereign_ratio=1.0))
    snap_badv = _snap([], {dup_dig: dup_raw, ovl_dig: ovl_raw, rat_dig: rat_raw})
    spec_100 = {"verifier": "vars1-coalition-viability@1", "params": {"min_sovereign_bps": 10000}}
    v_dup = W.verify_witness(spec_100, dup_dig, snap_badv, {}, 20)
    v_ovl = W.verify_witness(spec_100, ovl_dig, snap_badv, {}, 20)
    v_rat = W.verify_witness(spec_100, rat_dig, snap_badv, {}, 20)
    check("WT16 duplicate viability states, overlapping sets, and inconsistent sovereign_ratio fail closed",
          v_dup == (False, "DUPLICATE_VIABILITY_STATES")
          and v_ovl == (False, "INCONSISTENT_VIABILITY_SETS")
          and v_rat == (False, "INCONSISTENT_SOVEREIGN_RATIO"),
          (v_dup, v_ovl, v_rat))

    # WT17: vars1-identity-lineage@1 verifies fork isolation, ancestor provenance, and refuses spoofing
    id_ok_dig, id_ok_raw = _cert_blob({
        "schema": "vars1-identity-lineage@1", "node_id": "b0", "entity_root": "b0",
        "birth_kind": "fork", "atp": 40, "invariants": [["str", "safety"]], "relations": [],
        "provenance_chain": ["a0", "b0"], "entity_lineage": ["b0"],
    })
    id_leak_dig, id_leak_raw = _cert_blob({
        "schema": "vars1-identity-lineage@1", "node_id": "b0", "entity_root": "b0",
        "birth_kind": "fork", "atp": 40, "invariants": [["str", "safety"]], "relations": [["str", "stolen"]],
        "provenance_chain": ["a0", "b0"], "entity_lineage": ["b0"],
    })
    id_same_dig, id_same_raw = _cert_blob({
        "schema": "vars1-identity-lineage@1", "node_id": "a1", "entity_root": "a0",
        "birth_kind": "step", "atp": 40, "invariants": [["str", "safety"]], "relations": [],
        "provenance_chain": ["a0", "a1"], "entity_lineage": ["a0", "a1"],
    })
    snap_id = _snap([], {id_ok_dig: id_ok_raw, id_leak_dig: id_leak_raw, id_same_dig: id_same_raw})
    spec_id = {
        "verifier": "vars1-identity-lineage@1",
        "params": {
            "require_birth_kind": "fork", "require_ancestor": "a0", "require_distinct_from": "a0",
            "require_empty_relations": True, "min_atp": 30, "required_invariants": [["str", "safety"]],
        },
    }
    i_ok = W.verify_witness(spec_id, id_ok_dig, snap_id, {}, 20)
    i_leak = W.verify_witness(spec_id, id_leak_dig, snap_id, {}, 20)
    i_same = W.verify_witness(
        {"verifier": "vars1-identity-lineage@1", "params": {"require_distinct_from": "a0"}},
        id_same_dig, snap_id, {}, 20,
    )
    check("WT17 vars1-identity-lineage@1 verifies isolated fork child and rejects cloned relations or same-entity",
          i_ok == (True, "OK") and i_leak == (False, "INVALID_FORK_SHAPE") and i_same == (False, "SAME_ENTITY_FORBIDDEN"),
          (i_ok, i_leak, i_same))

    # WT18: vars1-trajectory-mass@1 enforces safety, exact mass accounting, horizon, and anti-Sybil dedup
    tm_ok_dig, tm_ok_raw = _cert_blob({
        "schema": "vars1-trajectory-mass@1", "label": "run1", "trajectory_safe": True,
        "step_count": 2, "horizon": 5, "verified_mass": 17, "total_weight": 67,
        "verified_acts": [{"act_id": "a1", "step_idx": 0, "weight": 10}, {"act_id": "a2", "step_idx": 1, "weight": 7}],
        "refuted_ids": [], "non_counting_acts": [{"act_id": "f1", "origin": "forked", "refuted": False, "step_idx": 1, "weight": 50}],
    })
    tm_dup_dig, tm_dup_raw = _cert_blob({
        "schema": "vars1-trajectory-mass@1", "label": "dup", "trajectory_safe": True,
        "step_count": 2, "horizon": 5, "verified_mass": 20, "total_weight": 20,
        "verified_acts": [{"act_id": "a1", "step_idx": 0, "weight": 10}, {"act_id": "a1", "step_idx": 1, "weight": 10}],
        "refuted_ids": [], "non_counting_acts": [],
    })
    tm_ref_dig, tm_ref_raw = _cert_blob({
        "schema": "vars1-trajectory-mass@1", "label": "ref", "trajectory_safe": True,
        "step_count": 2, "horizon": 5, "verified_mass": 10, "total_weight": 10,
        "verified_acts": [{"act_id": "a1", "step_idx": 0, "weight": 10}],
        "refuted_ids": ["a1"], "non_counting_acts": [],
    })
    tm_fake_dig, tm_fake_raw = _cert_blob({
        "schema": "vars1-trajectory-mass@1", "label": "fake", "trajectory_safe": True,
        "step_count": 2, "horizon": 5, "verified_mass": 99, "total_weight": 99,
        "verified_acts": [{"act_id": "a1", "step_idx": 0, "weight": 10}],
        "refuted_ids": [], "non_counting_acts": [],
    })
    tm_hid_dig, tm_hid_raw = _cert_blob({
        "schema": "vars1-trajectory-mass@1", "label": "hidden-ref", "trajectory_safe": True,
        "step_count": 2, "horizon": 5, "verified_mass": 17, "total_weight": 27,
        "verified_acts": [{"act_id": "a1", "step_idx": 0, "weight": 10}, {"act_id": "a2", "step_idx": 1, "weight": 7}],
        "refuted_ids": [],
        "non_counting_acts": [{"act_id": "bad", "origin": "verified", "refuted": True, "step_idx": 0, "weight": 10}],
    })
    snap_tm = _snap([], {
        tm_ok_dig: tm_ok_raw, tm_dup_dig: tm_dup_raw, tm_ref_dig: tm_ref_raw,
        tm_fake_dig: tm_fake_raw, tm_hid_dig: tm_hid_raw,
    })
    spec_tm = {"verifier": "vars1-trajectory-mass@1", "params": {"min_mass": 15, "min_steps": 2, "max_horizon": 5, "max_refuted": 0}}
    t_ok = W.verify_witness(spec_tm, tm_ok_dig, snap_tm, {}, 20)
    t_dup = W.verify_witness(spec_tm, tm_dup_dig, snap_tm, {}, 20)
    t_ref = W.verify_witness(spec_tm, tm_ref_dig, snap_tm, {}, 20)
    t_fake = W.verify_witness(spec_tm, tm_fake_dig, snap_tm, {}, 20)
    t_hid = W.verify_witness(spec_tm, tm_hid_dig, snap_tm, {}, 20)
    check("WT18 vars1-trajectory-mass@1 verifies exact mass and refuses duplicate acts, counted/hidden refutations, or inflated totals",
          t_ok == (True, "OK") and t_dup == (False, "DUPLICATE_ACT_ID")
          and t_ref == (False, "REFUTED_ACT_COUNTED") and t_fake == (False, "MASS_ACCOUNTING_MISMATCH")
          and t_hid == (False, "REFUTED_IDS_MISMATCH"),
          (t_ok, t_dup, t_ref, t_fake, t_hid))

    # WT19: Full 4-certificate autonomous A2A loop (Identity + Spore + Coalition + Trajectory) unlocks escrow & survives handoff export
    src_a2a = Repo()
    src_a2a.put("alice", "schema", P.SCHEMA)
    t_a2a = src_a2a.t + 10
    for raw_b in (id_ok_raw, sb_ok, vb_ok, tm_ok_raw):
        src_a2a.blob(raw_b)
    role_a2a = sorted(r for r, actors in src_a2a.profile["roles"].items() if "alice" in actors)[0]
    g_a2a = P._sign_env(D.grant_record(
        "alice", "carol", src_a2a.trust["keys"]["carol"][0],
        roles=[role_a2a], kinds=["attest"], not_before=0, not_after=t_a2a + 500, at=t_a2a - 2,
    ), sa)
    gid_a2a = R.rid(g_a2a["record"])
    prop_4w = P.make_proposal(
        "alice", sa, parties=["alice", "bob"],
        commitments={
            "alice": {"gives": ["forked_child"], "witnesses": {"forked_child": spec_id}},
            "bob": {
                "requires": ["forked_child"],
                "required_witnesses": {"forked_child": spec_id},
                "gives": ["spore_ok", "viable_ok", "mass_ok"],
                "witnesses": {
                    "spore_ok": {"verifier": "vars1-spore-receipt@1", "params": {"max_atp_spent": 50}},
                    "viable_ok": {"verifier": "vars1-coalition-viability@1", "params": {"min_sovereign_bps": 7500}},
                    "mass_ok": spec_tm,
                },
            },
        },
        expires_at=t_a2a + 100, purpose="full-4-witness-a2a-loop",
        escrow_grants=[gid_a2a], escrow_mode="settled", at=t_a2a,
    )
    pid_4w = R.rid(prop_4w["record"])
    src_a2a.store.add_lines([C.canon(e) + b"\n" for e in [
        g_a2a, prop_4w,
        P.make_accept("alice", sa, pid_4w, at=t_a2a + 1),
        P.make_accept("bob", sb, pid_4w, at=t_a2a + 2),
        P.make_fulfill("alice", sa, pid_4w, evidence_digest=id_ok_dig, delivered=["forked_child"], at=t_a2a + 3),
        P.make_fulfill("bob", sb, pid_4w, evidence_digest=sd_ok,
                       witness_digests={"spore_ok": sd_ok, "viable_ok": vd_ok, "mass_ok": tm_ok_dig},
                       delivered=["spore_ok", "viable_ok", "mass_ok"], at=t_a2a + 4),
    ]])
    cfg_a2a = Config({"agent_api": "warrant-agent/3", "workspaces": {"w": {
        "repo": str(src_a2a.root), "signer": {"actor": "bob", "key": str(src_a2a.seed("bob"))},
    }}})
    pkg_4w = agent_api.call(cfg_a2a, "handoff", {"workspace": "w", "op": "export", "targets": [pid_4w]})["ok"]["package"]
    recv_4w = Snapshot([x.encode() + b"\n" for x in pkg_4w["lines"]],
                       {h: base64.b64decode(b) for h, b in pkg_4w["blobs"].items()})
    res_4w = P.resolve_pacts(recv_4w, src_a2a.trust, t_a2a + 10)[pid_4w]
    esc_4w = P.resolve_escrow(recv_4w, src_a2a.trust, src_a2a.profile, t_a2a + 10)["escrow"][gid_a2a]
    check("WT19 full 4-witness A2A pact settles, unlocks escrow, and exports all 4 proof blobs via handoff",
          res_4w["status"] == "SETTLED" and esc_4w["escrow_allowed"] is True
          and all(d in pkg_4w["blobs"] for d in (id_ok_dig, sd_ok, vd_ok, tm_ok_dig)),
          (res_4w["status"], esc_4w, sorted(pkg_4w["blobs"])))


if __name__ == "__main__":
    sys.exit(run_sections([witness_cases]))
