# EXP-001 — adversarial adjudication (pre-registered, not started)

Read [`PREREGISTRATION.md`](PREREGISTRATION.md). Nothing here is a result.

Order of work, each step a separate commit so the freeze points are visible:

1. this pre-registration (done);
2. harness: shop server with an effects ledger, tee logger, plant application
   from `PLANTS.json`, condition bundles, adjudicator prompt, scoring script —
   then a freeze commit named in `REPORT.md`;
3. Planter seals `PLANTS.sha256` (`commit_plants.py seal`);
4. the run, the reveal, the report.

`runs/` stays empty until step 4. A `.gitignore` in this directory keeps
`PLANTS.json` out of the tree until the reveal.
