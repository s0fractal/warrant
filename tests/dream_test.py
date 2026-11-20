#!/usr/bin/env python3
"""Tests for `warrant.dream` deterministic lossless recipe synthesis & prescriptions (`DR01..DR10`).

    python3 tests/dream_test.py
"""
import sys

from world import Repo, check, run_sections

from warrant import dream as DR
from warrant import jcs as C
from warrant import pact as P
from warrant import records as R
from warrant_agent import api as agent_api
from warrant_agent.config import Config


def dream_cases():
    # DR01: Synthesizes multi-step lossless chain and automatically rejects lossy shortcut (silent drop)
    r_init = P.make_recipe("step_auth", requires=[], gives=["auth", "session"])
    r_lossy = P.make_recipe("step_lossy", requires=["auth"], gives=["deployed"])  # silently drops auth & session!
    r_safe = P.make_recipe("step_safe", requires=["auth"], gives=["deployed"], preserves=["auth", "session"])
    res = DR.dream_recipes([r_init, r_lossy, r_safe], goal_gives=["deployed", "auth"])
    check("DR01 dream_recipes finds lossless chain [step_auth, step_safe], rejects lossy shortcut, and emits prescription",
          res["solution_count"] == 1
          and res["solutions"][0]["steps"] == ["step_auth", "step_safe"]
          and res["solutions"][0]["composition"]["lossless"] is True
          and any(p["code"] == "SILENT_DROP_BLOCKED" and p["step"] == "step_lossy" for p in res["prescriptions"]),
          res)

    # DR02: Witness-typed goal filtering refuses ungrounded or mismatched verifier specs
    strict_w = {"verifier": "vars1-coalition-viability@1", "params": {"min_sovereign_bps": 10000}}
    weak_w = {"verifier": "sha256-blob@1", "params": {"min_bytes": 1}}
    r_weak = P.make_recipe("weak_verify", requires=[], gives=["viable"], witnesses={"viable": weak_w})
    r_strong = P.make_recipe("strong_verify", requires=[], gives=["viable"], witnesses={"viable": strict_w})
    r_dep = P.make_recipe("deploy", requires=["viable"], gives=["live"], preserves=["viable"],
                          required_witnesses={"viable": strict_w})
    res_w = DR.dream_recipes(
        [r_weak, r_strong, r_dep],
        goal_gives=["live", "viable"],
        required_witnesses={"viable": strict_w},
    )
    res_w1 = DR.dream_recipes(
        [r_weak, r_strong],
        goal_gives=["viable"],
        required_witnesses={"viable": strict_w},
        max_steps=1,
    )
    check("DR02 witness-typed synthesis picks strong_verify -> deploy and rejects weak_verify",
          res_w["solutions"][0]["steps"] == ["strong_verify", "deploy"]
          and all(s["steps"] != ["weak_verify", "deploy"] for s in res_w["solutions"])
          and res_w1["solution_count"] == 1 and res_w1["solutions"][0]["steps"] == ["strong_verify"]
          and any(p["code"] == "VERIFIER_SPEC_MISMATCH" for p in res_w["prescriptions"]),
          (res_w, res_w1))

    # DR03: Missing goal supplier & missing witness spec emit exact diagnostic prescriptions
    res_miss = DR.dream_recipes(
        [r_weak],
        goal_gives=["viable", "nonexistent"],
        required_witnesses={"viable": strict_w},
    )
    codes = {p["code"] for p in res_miss["prescriptions"]}
    check("DR03 missing goal supplier and missing witness spec produce MISSING_GOAL_SUPPLIER and MISSING_GOAL_WITNESS",
          res_miss["solution_count"] == 0
          and "MISSING_GOAL_SUPPLIER" in codes and "MISSING_GOAL_WITNESS" in codes,
          res_miss)

    # DR04: Boundary filtering rejects disjoint boundary recipes and admits intersecting boundary
    r_prod = P.make_recipe("prod_step", requires=[], gives=["ready"], boundary=["prod"])
    r_dev = P.make_recipe("dev_step", requires=[], gives=["ready"], boundary=["dev"])
    res_b = DR.dream_recipes([r_prod, r_dev], goal_gives=["ready"], boundary=["prod"])
    check("DR04 boundary filter admits only recipes intersecting requested boundary",
          res_b["solution_count"] == 1 and res_b["solutions"][0]["steps"] == ["prod_step"],
          res_b)

    # DR05: initial_gives enables 0-step trivial satisfaction or seeded continuation
    r_cont = P.make_recipe("build", requires=["seed"], gives=["artifact"], preserves=["seed"])
    res_0 = DR.dream_recipes([r_cont], goal_gives=["seed"], initial_gives=["seed"])
    res_1 = DR.dream_recipes([r_cont], goal_gives=["artifact"], initial_gives=["seed"])
    check("DR05 initial_gives supports 0-step satisfaction and seeded lossless continuation",
          res_0["solution_count"] >= 1 and res_0["solutions"][0]["steps"] == []
          and res_1["solution_count"] == 1 and res_1["solutions"][0]["steps"] == ["build"],
          (res_0, res_1))

    # DR06: Expansion budget exhaustion stops cleanly and reports BUDGET_EXHAUSTED (honest partiality)
    chain_recs = [
        P.make_recipe(f"r{i}", requires=[f"g{i - 1}"] if i > 0 else [], gives=[f"g{i}"],
                      preserves=[f"g{j}" for j in range(i)])
        for i in range(6)
    ]
    res_bud = DR.dream_recipes(chain_recs, goal_gives=["g5"], max_steps=6, max_expansions=3)
    check("DR06 hitting max_expansions halts cleanly with budget_exhausted=True and BUDGET_EXHAUSTED prescription",
          res_bud["budget_exhausted"] is True and res_bud["expansions"] == 3
          and any(p["code"] == "BUDGET_EXHAUSTED" for p in res_bud["prescriptions"]),
          res_bud)

    # DR07: Strict input validation refuses duplicate recipe ids, bool budgets, and bad witness keys
    errs = []
    for fn in (
        lambda: DR.dream_recipes([r_prod, r_prod], goal_gives=["ready"]),
        lambda: DR.dream_recipes([r_prod], goal_gives=["ready"], max_steps=True),
        lambda: DR.dream_recipes([r_prod], goal_gives=["ready"], max_expansions=0),
        lambda: DR.dream_recipes([r_prod], goal_gives=["ready"], required_witnesses={"other": weak_w}),
        lambda: DR.dream_recipes([r_prod], goal_gives=[]),
    ):
        try:
            fn()
            errs.append(None)
        except ValueError as exc:
            errs.append(str(exc))
    check("DR07 duplicate recipe ids, bool/zero budgets, empty goal, and mismatched witness keys fail closed",
          all(e is not None for e in errs) and "DUPLICATE_RECIPE_ID" in errs[0],
          errs)

    # DR08: dream_pacts + agent API `pact {op: dream}` synthesizes across live ACTIVE/SETTLED pacts & skips BREACHED
    repo = Repo()
    repo.put("alice", "schema", P.SCHEMA)
    t = repo.t + 10
    sa, sb = (repo.seed(a).read_text().strip() for a in ("alice", "bob"))
    p1 = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments={
        "alice": {"gives": ["auth"]}, "bob": {"requires": ["auth"], "gives": ["token"], "preserves": ["auth"]},
    }, expires_at=t + 100, purpose="p1", at=t)
    pid1 = R.rid(p1["record"])
    p2 = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments={
        "alice": {"requires": ["token"], "gives": ["deployed"], "preserves": ["auth", "token"]},
        "bob": {"gives": ["logged"]},
    }, expires_at=t + 100, purpose="p2", at=t)
    pid2 = R.rid(p2["record"])
    # Expired/unfulfilled pact that will be BREACHED at t+200 (or EXPIRED at t+10) -> skipped cleanly
    p_bad = P.make_proposal("alice", sa, parties=["alice", "bob"], commitments={
        "alice": {"gives": ["deployed"]}, "bob": {"gives": ["x"]},
    }, expires_at=t + 5, purpose="expired", at=t)
    pid_bad = R.rid(p_bad["record"])
    envs = [
        p1, P.make_accept("alice", sa, pid1, at=t + 1), P.make_accept("bob", sb, pid1, at=t + 2),
        p2, P.make_accept("alice", sa, pid2, at=t + 1), P.make_accept("bob", sb, pid2, at=t + 2),
        p_bad,
    ]
    repo.store.add_lines([C.canon(e) + b"\n" for e in envs])
    snap = repo.store.snapshot()
    dp = DR.dream_pacts(snap, repo.trust, t + 10, goal_gives=["deployed", "auth"])
    cfg = Config({"agent_api": "warrant-agent/3", "workspaces": {"w": {
        "repo": str(repo.root), "signer": {"actor": "bob", "key": str(repo.seed("bob"))},
    }}})
    api_res = agent_api.call(cfg, "pact", {
        "workspace": "w", "op": "dream", "as_of": t + 10, "goal_gives": ["deployed", "auth"],
    })
    check("DR08 dream_pacts and warrant_agent pact dream synthesize [pid1, pid2] and skip EXPIRED pact",
          dp["solution_count"] == 1 and dp["solutions"][0]["steps"] == [pid1, pid2]
          and dp["skipped_pacts"].get(pid_bad) == "STATUS_EXPIRED"
          and "ok" in api_res and api_res["ok"]["dream"]["solution_count"] == 1
          and api_res["ok"]["dream"]["solutions"][0]["steps"] == [pid1, pid2],
          (dp, api_res))


if __name__ == "__main__":
    sys.exit(run_sections([dream_cases]))
