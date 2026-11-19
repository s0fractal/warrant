#!/usr/bin/env python3
"""Bilateral/multilateral cryptographic pacts and computed-loss composition (`pact@1`, docs/PACT.md).

    python3 tests/pact_test.py
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from world import Repo, check, run_sections

from warrant import delegate as D
from warrant import jcs as C
from warrant import pact as P
from warrant import records as R
from warrant.store import Snapshot
from warrant_agent import api
from warrant_agent.config import Config


def _h(label):
    return hashlib.sha256(label.encode()).hexdigest()


def _snap_from_envs(envs):
    lines = [C.canon(e) + b"\n" for e in envs]
    return Snapshot(lines, {}, sort=True)


def _mk_world():
    """Create a fresh Repo with alice, bob, carol, dave, eve keys."""
    repo = Repo()
    return repo, repo.trust, repo.profile


def _two_party_comms():
    return {
        "alice": {"requires": ["auth"], "gives": ["signed", "auth"], "preserves": [], "declared_losses": []},
        "bob": {"requires": ["signed"], "gives": ["published", "signed"], "preserves": [], "declared_losses": []},
    }


def _seed(repo, actor):
    return repo.seed(actor).read_text().strip()


def _rid(env):
    return R.rid(env["record"])


def pact_cases():
    repo, trust, profile = _mk_world()
    sa, sb, sc, sd = (_seed(repo, x) for x in ("alice", "bob", "carol", "dave"))

    # PC01: proposal validation guards (<2 parties, duplicate, arbiter in parties, commitment mismatch)
    bad_one = P.make_proposal("alice", sa, parties=["alice"], commitments={"alice": {"gives": ["x"]}},
                              expires_at=100, purpose="solo")
    bad_arb = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments=_two_party_comms(),
                              expires_at=100, purpose="biased", arbiter="alice")
    bad_mis = P.make_proposal("alice", sa, parties=["alice", "bob"],
                              commitments={"alice": {"gives": ["x"]}}, expires_at=100, purpose="mismatch")
    snap_bad = _snap_from_envs([bad_one, bad_arb, bad_mis])
    res_bad = P.resolve_pacts(snap_bad, trust, as_of=10)
    check("PC01 proposal validation refuses <2 parties, party-as-arbiter, and commitment/party mismatch",
          res_bad.get(_rid(bad_one), {}).get("status") == "INVALID"
          and res_bad.get(_rid(bad_one), {}).get("reason") == "BAD_PARTIES_COUNT"
          and res_bad.get(_rid(bad_arb), {}).get("status") == "INVALID"
          and res_bad.get(_rid(bad_arb), {}).get("reason") == "ARBITER_IS_PARTY"
          and res_bad.get(_rid(bad_mis), {}).get("status") == "INVALID"
          and res_bad.get(_rid(bad_mis), {}).get("reason") == "COMMITMENTS_PARTY_MISMATCH",
          res_bad)

    # PC02: unanimous activation (no unilateral binding; digest mismatch & non-party accept refused)
    prop = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments=_two_party_comms(),
                           expires_at=100, purpose="exchange", at=10)
    pid = _rid(prop)
    acc_a = P.make_accept("alice", sa, pid, at=12)
    acc_eve = P.make_accept("carol", sc, pid, at=13)
    acc_bad_dig = P.make_accept("bob", sb, pid, at=14, pact_digest=_h("wrong-terms"))
    snap_part = _snap_from_envs([prop, acc_a, acc_eve, acc_bad_dig])
    r_part = P.resolve_pacts(snap_part, trust, as_of=20).get(pid, {})
    refused_codes = {e.get("code") for e in r_part.get("refused_events", [])}
    check("PC02 partial acceptance stays PROPOSED; non-party accept and digest mismatch are refused",
          r_part.get("status") == "PROPOSED"
          and sorted(r_part.get("accepted", {}).keys()) == ["alice"]
          and "NOT_A_PARTY" in refused_codes
          and "DIGEST_MISMATCH" in refused_codes,
          r_part)

    # PC03: unanimous activation -> ACTIVE; expiry while PROPOSED -> EXPIRED (no defaulter)
    r_exp_prop = P.resolve_pacts(snap_part, trust, as_of=101).get(pid, {})
    acc_b = P.make_accept("bob", sb, pid, at=15)
    snap_act = _snap_from_envs([prop, acc_a, acc_b])
    r_act = P.resolve_pacts(snap_act, trust, as_of=20).get(pid, {})
    check("PC03 unaccepted proposal expires cleanly as EXPIRED with no defaulters; all parties accepting enters ACTIVE",
          r_exp_prop.get("status") == "EXPIRED" and r_exp_prop.get("defaulters") == []
          and r_act.get("status") == "ACTIVE" and r_act.get("activation_at") == 15,
          (r_exp_prop, r_act))

    # PC04: pre-activation withdrawal succeeds (WITHDRAWN), post-activation withdrawal is refused (ALREADY_ACTIVE)
    wd_early = P.make_withdraw("bob", sb, pid, at=14, reason="changed mind")
    r_wd_early = P.resolve_pacts(_snap_from_envs([prop, acc_a, wd_early, acc_b]), trust, as_of=20).get(pid, {})
    wd_late = P.make_withdraw("bob", sb, pid, at=16, reason="escape attempt")
    r_wd_late = P.resolve_pacts(_snap_from_envs([prop, acc_a, acc_b, wd_late]), trust, as_of=20).get(pid, {})
    late_codes = {e.get("code") for e in r_wd_late.get("refused_events", [])}
    check("PC04 withdrawal before activation yields WITHDRAWN; withdrawal at/after activation is refused as ALREADY_ACTIVE",
          r_wd_early.get("status") == "WITHDRAWN"
          and r_wd_late.get("status") == "ACTIVE"
          and "ALREADY_ACTIVE" in late_codes,
          (r_wd_early, r_wd_late))

    # PC05: incomplete fulfillment is refused; complete fulfillments by all parties settle cleanly -> SETTLED
    ful_a_inc = P.make_fulfill("alice", sa, pid, evidence_digest=_h("ev-a"), delivered=["signed"], at=20)
    r_inc = P.resolve_pacts(_snap_from_envs([prop, acc_a, acc_b, ful_a_inc]), trust, as_of=25).get(pid, {})
    inc_codes = {e.get("code") for e in r_inc.get("refused_events", [])}
    ful_a = P.make_fulfill("alice", sa, pid, evidence_digest=_h("ev-a"), delivered=["signed", "auth"], at=22)
    ful_b = P.make_fulfill("bob", sb, pid, evidence_digest=_h("ev-b"), delivered=["published", "signed"], at=25)
    r_set = P.resolve_pacts(_snap_from_envs([prop, acc_a, acc_b, ful_a, ful_b]), trust, as_of=30).get(pid, {})
    check("PC05 incomplete fulfillment is refused (INCOMPLETE_FULFILLMENT); complete fulfillments settle to SETTLED",
          r_inc.get("status") == "ACTIVE" and "alice" not in r_inc.get("fulfilled", {})
          and "INCOMPLETE_FULFILLMENT" in inc_codes
          and r_set.get("status") == "SETTLED"
          and r_set.get("honest_parties") == ["alice", "bob"]
          and r_set.get("defaulters") == [],
          (r_inc, r_set))

    # PC06: fulfillment before activation or after expiry is refused
    ful_pre = P.make_fulfill("alice", sa, pid, evidence_digest=_h("ev-pre"), delivered=["signed", "auth"], at=14)
    ful_post = P.make_fulfill("bob", sb, pid, evidence_digest=_h("ev-post"), delivered=["published", "signed"], at=105)
    r_time = P.resolve_pacts(_snap_from_envs([prop, acc_a, acc_b, ful_pre, ful_post]), trust, as_of=30).get(pid, {})
    time_codes = {e.get("code") for e in r_time.get("refused_events", [])}
    r_late = P.resolve_pacts(_snap_from_envs([prop, acc_a, acc_b, ful_pre, ful_post]), trust, as_of=110).get(pid, {})
    late_codes = {e.get("code") for e in r_late.get("refused_events", [])}
    check("PC06 fulfillment before activation or after expires_at is refused, each read when it is there: at 30 the "
          "fulfilment dated 105 does not exist yet; at 110 it is refused as after expiry (Codex F1)",
          r_time.get("status") == "ACTIVE" and r_time.get("fulfilled") == {}
          and "FULFILL_BEFORE_ACTIVATION" in time_codes and "FULFILL_AFTER_EXPIRY" not in time_codes
          and "FULFILL_AFTER_EXPIRY" in late_codes,
          (r_time, r_late))

    # PC07: equivocation detection — conflicting signed fulfill digests trigger BREACHED + dual-record proof
    ful_a_1 = P.make_fulfill("alice", sa, pid, evidence_digest=_h("ev-a-v1"), delivered=["signed", "auth"], at=20)
    ful_a_2 = P.make_fulfill("alice", sa, pid, evidence_digest=_h("ev-a-v2"), delivered=["signed", "auth"], at=21)
    r_eq = P.resolve_pacts(_snap_from_envs([prop, acc_a, acc_b, ful_a_1, ful_a_2, ful_b]), trust, as_of=30).get(pid, {})
    eq_proof = r_eq.get("equivocations", {}).get("alice", [])
    check("PC07 equivocation (two distinct evidence_digests by same party) breaches pact with dual-record proof",
          r_eq.get("status") == "BREACHED" and r_eq.get("reason") == "EQUIVOCATION"
          and r_eq.get("defaulters") == ["alice"]
          and r_eq.get("honest_parties") == ["bob"]
          and sorted(eq_proof) == sorted([_rid(ful_a_1), _rid(ful_a_2)]),
          r_eq)

    # PC08: expiry of ACTIVE pact with asymmetric fulfillment attributes exact defaulter and honest party
    r_def = P.resolve_pacts(_snap_from_envs([prop, acc_a, acc_b, ful_a]), trust, as_of=101).get(pid, {})
    check("PC08 ACTIVE pact passing expires_at with only alice fulfilled yields BREACHED(defaulters=[bob], honest=[alice])",
          r_def.get("status") == "BREACHED" and r_def.get("reason") == "EXPIRED_DEFAULT"
          and r_def.get("defaulters") == ["bob"]
          and r_def.get("honest_parties") == ["alice"],
          r_def)

    # PC09: neutral arbiter settlement & breach, refusing non-arbiter settle/breach attempts
    prop_arb = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments=_two_party_comms(),
                               expires_at=100, purpose="arbitrated", arbiter="carol", at=10)
    pid_a = _rid(prop_arb)
    aa1 = P.make_accept("alice", sa, pid_a, at=11)
    aa2 = P.make_accept("bob", sb, pid_a, at=12)
    fa1 = P.make_fulfill("alice", sa, pid_a, evidence_digest=_h("a1"), delivered=["signed", "auth"], at=20)
    fb1 = P.make_fulfill("bob", sb, pid_a, evidence_digest=_h("b1"), delivered=["published", "signed"], at=21)
    fake_settle = P.make_settle("dave", sd, pid_a, at=22)
    fake_breach = P.make_breach("bob", sb, pid_a, defaulter="alice", evidence_digest=_h("fake"), reason="slander", at=22)
    r_wait = P.resolve_pacts(_snap_from_envs([prop_arb, aa1, aa2, fa1, fb1, fake_settle, fake_breach]),
                             trust, as_of=25).get(pid_a, {})
    real_settle = P.make_settle("carol", sc, pid_a, at=23)
    r_arb_ok = P.resolve_pacts(_snap_from_envs([prop_arb, aa1, aa2, fa1, fb1, real_settle]),
                               trust, as_of=25).get(pid_a, {})
    real_breach = P.make_breach("carol", sc, pid_a, defaulter="bob", evidence_digest=_h("proof-b"), reason="forged", at=23)
    r_arb_br = P.resolve_pacts(_snap_from_envs([prop_arb, aa1, aa2, fa1, real_breach]),
                               trust, as_of=25).get(pid_a, {})
    wait_codes = [e.get("code") for e in r_wait.get("refused_events", [])]
    check("PC09 arbitrated pact waits for neutral arbiter; non-arbiter settle/breach refused; arbiter settles or breaches",
          r_wait.get("status") == "ACTIVE" and wait_codes.count("NOT_ARBITER") == 2
          and r_arb_ok.get("status") == "SETTLED"
          and r_arb_br.get("status") == "BREACHED" and r_arb_br.get("reason") == "ARBITER_BREACH"
          and r_arb_br.get("defaulters") == ["bob"],
          (r_wait, r_arb_ok, r_arb_br))

    # PC10: escrow bridge with grant@1 (active mode & settled mode; breach freezes escrowed grant immediately)
    # Pick a role alice actually holds in Repo's profile so the root grant@1 is ACTIVE
    alice_roles = sorted(r for r, actors in profile.get("roles", {}).items() if "alice" in actors)
    g_rec = D.grant_record(
        "alice", "carol", trust["keys"]["carol"][0],
        roles=[alice_roles[0]], kinds=["attest"],
        not_before=0, not_after=200, max_depth=1, at=5,
    )
    g_env = P._sign_env(g_rec, sa)
    gid = _rid(g_env)

    prop_esc = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments=_two_party_comms(),
                               expires_at=100, purpose="escrow-active",
                               escrow_grants=[gid], escrow_mode="active", at=10)
    pe_id = _rid(prop_esc)
    ae1 = P.make_accept("alice", sa, pe_id, at=11)
    ae2 = P.make_accept("bob", sb, pe_id, at=12)

    es_prop = P.resolve_escrow(_snap_from_envs([g_env, prop_esc, ae1]), trust, profile, as_of=20)["escrow"].get(gid, {})
    es_act = P.resolve_escrow(_snap_from_envs([g_env, prop_esc, ae1, ae2]), trust, profile, as_of=20)["escrow"].get(gid, {})
    es_br = P.resolve_escrow(_snap_from_envs([g_env, prop_esc, ae1, ae2]), trust, profile, as_of=105)["escrow"].get(gid, {})

    prop_set_esc = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments=_two_party_comms(),
                                   expires_at=100, purpose="escrow-settled",
                                   escrow_grants=[gid], escrow_mode="settled", at=10)
    ps_id = _rid(prop_set_esc)
    as1 = P.make_accept("alice", sa, ps_id, at=11)
    as2 = P.make_accept("bob", sb, ps_id, at=12)
    fs1 = P.make_fulfill("alice", sa, ps_id, evidence_digest=_h("s-a"), delivered=["signed", "auth"], at=15)
    fs2 = P.make_fulfill("bob", sb, ps_id, evidence_digest=_h("s-b"), delivered=["published", "signed"], at=16)
    es_wait_set = P.resolve_escrow(_snap_from_envs([g_env, prop_set_esc, as1, as2]), trust, profile, as_of=20)["escrow"].get(gid, {})
    es_done_set = P.resolve_escrow(_snap_from_envs([g_env, prop_set_esc, as1, as2, fs1, fs2]), trust, profile, as_of=20)["escrow"].get(gid, {})

    check("PC10 escrow gates grant@1 on pact state: active-mode allows only when ACTIVE (freezes on PROPOSED/BREACHED); "
          "settled-mode releases only when SETTLED",
          es_prop.get("escrow_allowed") is False
          and es_act.get("escrow_allowed") is True
          and es_br.get("escrow_allowed") is False
          and es_wait_set.get("escrow_allowed") is False
          and es_done_set.get("escrow_allowed") is True,
          (es_prop, es_act, es_br, es_wait_set, es_done_set))

    # PC11: Computed-loss composition — exact F1 countermodel caught mechanically!
    r1 = P.make_recipe("sign", requires=["auth"], gives=["auth", "signed"], declared_losses=[])
    r2 = P.make_recipe("publish", requires=["signed"], gives=["signed", "published"], declared_losses=[])
    c_f1 = P.compose_recipes([r1, r2])
    check("PC11 F1 countermodel: silent drop of `auth` by R2 is mechanically caught in silent_drops & computed_losses",
          c_f1.get("well_typed") is True
          and c_f1.get("lossless") is False
          and c_f1.get("declared_losses") == []
          and c_f1.get("silent_drops") == ["auth"]
          and c_f1.get("computed_losses") == ["auth"]
          and c_f1.get("gives") == ["published", "signed"]
          and any(ev.get("guarantee") == "auth" and ev.get("recipe_id") == "publish" and ev.get("kind") == "silent_drop"
                  for ev in c_f1.get("loss_events", [])),
          c_f1)

    # PC12: Explicit frame preservation (`preserves`) keeps guarantee and certifies lossless composition
    r2_frame = P.make_recipe("publish_preserving", requires=["signed"], gives=["signed", "published"],
                             preserves=["auth"], declared_losses=[])
    c_ok = P.compose_recipes([r1, r2_frame])
    check("PC12 explicit `preserves=['auth']` carries guarantee across R2 and certifies lossless=True",
          c_ok.get("well_typed") is True
          and c_ok.get("lossless") is True
          and c_ok.get("computed_losses") == []
          and c_ok.get("gives") == ["auth", "published", "signed"],
          c_ok)

    # PC13: Anti-laundering — re-establishing a silently dropped guarantee later does NOT erase historical drop event
    r3_reauth = P.make_recipe("reauth", requires=["published"], gives=["auth", "published", "signed"])
    c_launder = P.compose_recipes([r1, r2, r3_reauth])
    check("PC13 anti-laundering: re-establishing `auth` at step 2 restores it to gives, yet lossless stays False and drop event persists",
          c_launder.get("well_typed") is True
          and c_launder.get("lossless") is False
          and "auth" in c_launder.get("gives", [])
          and "auth" in c_launder.get("silent_drops", [])
          and "auth" in c_launder.get("re_established", [])
          and len(c_launder.get("loss_events", [])) >= 2,
          c_launder)

    # PC14: Unmet prerequisite and incompatible boundary fail well-typedness
    r_bad_pre = P.make_recipe("needs_audit", requires=["audited"], gives=["done"])
    r_bad_bnd = P.make_recipe("wrong_scope", requires=["signed"], gives=["signed"], boundary=["prod_only"])
    r_dev = P.make_recipe("dev_step", requires=[], gives=["signed"], boundary=["dev_only"])
    c_pre = P.compose_recipes([r1, r_bad_pre])
    c_bnd = P.compose_recipes([r_dev, r_bad_bnd])
    check("PC14 unmet prerequisite (PREREQ_UNMET) and disjoint boundary (BOUNDARY_INCOMPATIBLE) fail well_typed",
          c_pre.get("well_typed") is False
          and any(e.get("code") == "PREREQ_UNMET" and "audited" in e.get("missing", []) for e in c_pre.get("errors", []))
          and c_bnd.get("well_typed") is False
          and any(e.get("code") == "BOUNDARY_INCOMPATIBLE" for e in c_bnd.get("errors", [])),
          (c_pre, c_bnd))

    # PC15: Step 0 dropping its own prerequisite without preserving or giving it is caught
    r0_drop = P.make_recipe("consume_only", requires=["secret_token"], gives=["receipt"])
    c_drop0 = P.compose_recipes([r0_drop])
    check("PC15 step 0 dropping its own prerequisite is caught in silent_drops & computed_losses",
          c_drop0.get("well_typed") is True
          and c_drop0.get("lossless") is False
          and c_drop0.get("silent_drops") == ["secret_token"],
          c_drop0)

    # PC16: End-to-end compose_pacts over live SETTLED pacts + refusal on BREACHED pact
    p1 = P.make_proposal("alice", sa, parties=["alice", "bob"],
                         commitments={
                             "alice": {"requires": ["auth"], "gives": ["auth", "signed"]},
                             "bob": {"requires": ["signed"], "gives": ["signed", "packaged"]},
                         }, expires_at=100, purpose="stage1", boundary=["net-a", "net-b"], at=10)
    p2 = P.make_proposal("bob", sb, parties=["bob", "carol"],
                         commitments={
                             "bob": {"requires": ["packaged"], "gives": ["packaged", "shipped"]},
                             "carol": {"requires": ["shipped"], "gives": ["shipped", "verified"]},
                         }, expires_at=100, purpose="stage2", boundary=["net-b"], at=10)
    p1_id, p2_id = _rid(p1), _rid(p2)
    envs_chain = [
        p1, P.make_accept("alice", sa, p1_id, at=11), P.make_accept("bob", sb, p1_id, at=12),
        p2, P.make_accept("bob", sb, p2_id, at=11), P.make_accept("carol", sc, p2_id, at=12),
    ]
    snap_chain = _snap_from_envs(envs_chain)
    c_live = P.compose_pacts(snap_chain, trust, [p1_id, p2_id], as_of=20)
    # At as_of=105 both pacts are BREACHED -> compose_pacts must refuse
    refused_breached = False
    try:
        P.compose_pacts(snap_chain, trust, [p1_id, p2_id], as_of=105)
    except ValueError:
        refused_breached = True
    check("PC16 compose_pacts composes ACTIVE/SETTLED pacts, detects silent drops across pacts, and refuses BREACHED pacts",
          c_live.get("well_typed") is True
          and c_live.get("boundary") == ["net-b"]
          and "auth" in c_live.get("silent_drops", [])
          and "signed" in c_live.get("silent_drops", [])
          and refused_breached is True,
          (c_live, refused_breached))

    # PC17: Agent API (`pact` op=status/escrow/compose) & CLI (`warrant pact status`)
    # Append p1, p2 and accepts into repo's store
    store_path = repo.root / ".warrant" / "records.jsonl"
    with store_path.open("ab") as fh:
        for env in envs_chain:
            fh.write(C.canon(env) + b"\n")
    cfg = Config({"agent_api": "warrant-agent/3",
                  "workspaces": {"w": {"repo": str(repo.root), "signer": {"actor": "bob", "key": str(repo.seed("bob"))}}}})
    st_res = api.call(cfg, "pact", {"workspace": "w", "op": "status", "as_of": 20}).get("ok", {})
    es_res = api.call(cfg, "pact", {"workspace": "w", "op": "escrow", "as_of": 20}).get("ok", {})
    co_res = api.call(cfg, "pact", {"workspace": "w", "op": "compose", "as_of": 20, "pact_ids": [p1_id, p2_id]}).get("ok", {})
    bad_op = api.call(cfg, "pact", {"workspace": "w", "op": "bogus"})
    cli_run = subprocess.run([sys.executable, "-m", "warrant", "pact", "--root", str(repo.root), "status", "--as-of", "20"],
                             capture_output=True, text=True, check=False)
    cli_json = json.loads(cli_run.stdout) if cli_run.returncode == 0 else {}
    check("PC17 agent API (status/escrow/compose/refusal) and CLI (`warrant pact status`) return deterministic pact views",
          st_res.get("warrant") == "pact/1" and st_res.get("count") == 2
          and es_res.get("warrant") == "pact/1" and es_res.get("op") == "escrow"
          and co_res.get("composition", {}).get("well_typed") is True
          and "auth" in co_res.get("composition", {}).get("silent_drops", [])
          and bad_op.get("error") == "BAD_REQUEST"
          and cli_run.returncode == 0 and len(cli_json.get("pacts", {})) == 2,
          (st_res, es_res, co_res, bad_op, cli_run.returncode))


def review_cases():
    """Codex's five reproducers on #577, each its own file under tests/, run as they were written: a pact reads only
    records dated by its horizon (F1), escrow freezes delegated admission (F2), only an issuer binds its grant (F3),
    the schema is one the engine admits (F4), and a proposal may follow its actor's earlier records (F5)."""
    import subprocess
    here = Path(__file__).resolve().parent
    for case, name, what in (("PR1", "time", "a pact reads no record dated after its horizon"),
                             ("PR2", "escrow", "a breached escrow refuses the delegated record"),
                             ("PR3", "binding", "an unrelated pact cannot freeze another issuer's grant"),
                             ("PR4", "schema", "the pact@1 schema is admitted by the V3 engine"),
                             ("PR5", "chain", "a proposal may follow an earlier record of its actor"),
                             ("PR6", "descendant", "a breached escrow freezes the grants delegated from it too")):
        out = subprocess.run([sys.executable, str(here / f"pact_review_{name}_test.py")], capture_output=True,
                             text=True, cwd=here.parent, timeout=600)
        check(f"{case} {what} (Codex's reproducer, tests/pact_review_{name}_test.py)",
              out.returncode == 0 and "\nok   " in "\n" + out.stdout and "FAIL" not in out.stdout,
              (out.stdout + out.stderr)[-400:])


if __name__ == "__main__":
    sys.exit(run_sections([pact_cases, review_cases]))
