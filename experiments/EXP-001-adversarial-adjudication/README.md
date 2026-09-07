# EXP-001 — adversarial adjudication (pre-registered, not started)

Read [`PREREGISTRATION.md`](PREREGISTRATION.md). Nothing here is a result.

Order of work, each step a separate commit so the freeze points are visible:

1. this pre-registration (done);
2. harness (done): `shop_server.py` (state + merchant effects ledger),
   `tee_logger.py` (LOG observer), `agent.py` (session driver, decisions,
   plants), `bundles.py` + `policy_check.py` (the two conditions),
   `adjudicate.py`, `score.py`, `run.py`, `budget.py` (the enforced cap),
   `schedule.json` (the assignment); `smoke.py` plus the R1–R4 fixtures from
   Codex's review run in `tools/check.py` so the plumbing cannot rot silently. Freeze commit to be named in
   `REPORT.md`;
3. Planter seals `PLANTS.sha256` (`commit_plants.py seal`);
4. the run, the reveal, the report.

`runs/` stays empty until step 4. A `.gitignore` in this directory keeps
`PLANTS.json` and `runs-scratch/` (pipeline tests) out of the tree; every
harness script refuses a path outside this directory (`harness/common.py`).
