# EXP-001 — report

**Status: FROZEN, NOT RUN.** No observation exists. Nothing below the
"Results" heading may be filled in before the Planter's commitment is in the
tree and the run has happened in the order the pre-registration fixes.

## Freeze

| | |
| --- | --- |
| harness commit | `193a7114ec20292bfe5548491c0376ba5b462790` (master, merge of PR #64, 2026-09-07 23:04 UTC) |
| pre-registration | `PREREGISTRATION.md` as at that commit; digest in the table below |
| assignment | `harness/schedule.json`: agent `deepseek/deepseek-chat-v3.1`; adjudicator A `google/gemini-2.5-flash`; adjudicator B `mistralai/mistral-large-2512`; cells S1/PACK/A, S1/LOG/B, S2/LOG/A, S2/PACK/B |
| budget | USD 5.00, enforced by `harness/budget.py` (`runs/budget.json`); second guard: an OpenRouter key with a provider-side credit limit of USD 5, created by the operator for this run |
| Planter | Codex; `PLANTS.sha256` to be committed via `commit_plants.py seal` **after** this freeze and **before** any run |
| Runner | Claude |

Every file of the experiment at the freeze (the harness, the scenarios, the
pre-registration, this file's siblings), so that a change after the freeze
is detectable by anyone:

| sha256 | file |
| --- | --- |
| `ac1c0cbc2116cb84ce9a148a6d047a4447384ed03728aab36d70562e6e58ceb4` | `.gitignore` |
| `7705572cd1af50e4ba5c9bbe53c6622588e43cc280df3c18b247f3a7a44cb77b` | `PREREGISTRATION.md` |
| `536a36e395332625dab42b229e33352e27c5516f43727a29130ed81d1219062c` | `README.md` |
| `4127f0c54e289c77f34b14d992a30e96dc2383e8f31a09721e2fd1ce1beabbd5` | `commit_plants.py` |
| `d32597110e7c7fc147bc45fc6c4bb618b7eef3e5dccd9b3e7430287eaf6f57fd` | `harness/adjudicate.py` |
| `c5c0ff7693f19478acc62911cadf2a1075478df57217706e030ffb7c0b53a4ec` | `harness/agent.py` |
| `6823319efcc39bae2e27c2bb3aa3d4aa3c5c6cca28be118c5b3305c6450e97b3` | `harness/budget.py` |
| `ea6a6fa157527c30c6f4a7c74f790ade85ce3a339e9b843a799889f6b28effac` | `harness/bundles.py` |
| `fd0f11027d3752877da0f048e67021ce2f95742661d47a80228cf62f0334d871` | `harness/common.py` |
| `e26ad23421d85d0b024b1ab781d1f034c466967aa8a34ba514fe9f23f6a93872` | `harness/effects.json` |
| `472141421094729e706b1d82a6ba0fbc35bbe35bba2af4e39e6339cba8172d6a` | `harness/policy_check.py` |
| `df8788f2c5536dfbace2c9895e3c29e7e14f9a4444bfb3d1a9d7a8fe572516c0` | `harness/run.py` |
| `b0a0b064a6b8ad40bc1483a36267a9486ca21f10189080704e1e9dc644ac3c0c` | `harness/scenarios/S1.json` |
| `1ed45190456bab41946c9e075a88e003e94100ddd8d84bbe4a5a22df12c35e24` | `harness/scenarios/S2.json` |
| `dd4d685b283611f7a11855ad35884baeb4714e50512bcc9d7d2f939470b680a4` | `harness/schedule.json` |
| `d3909d88b7a642e949b1197ed4b6a7bc4f259477bbfd8e4df5e75ed71deda1b4` | `harness/score.py` |
| `3cc521d0435cb424b1928e344c98aebe78a6c51cc3c834197a9874e35f9e4f51` | `harness/shop_server.py` |
| `c6ae152d8e750b730d77789696fbd8b10e9bb21f293104f635ef7169826cca3c` | `harness/smoke.py` |
| `a36f62a6898b23434b9ff7f9101e9d01afbd67a3ab30da5ef80d1b8cd95e8fd2` | `harness/tee_logger.py` |
| `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `runs/.gitkeep` |

A run is valid only against these bytes. A harness bug found during the run
is fixed in a new commit, named here as an amendment, and the **whole**
protocol repeats from step 3 with the repetition count reported.

## Run log

*(empty — filled by the Runner, one line per protocol step, with commit,
time and outcome; refusals, timeouts and budget stops included)*

## Results

*(empty until the reveal; then: the `score.py` table, m1–m6 per cell, F1–F4
status, the Planter's verification of `PLANTS.sha256`, and the result line)*

## Amendments

- **2026-09-08, before the run — second budget guard.** The pre-registration
  names an OpenRouter key with a provider-side USD 5 credit limit as the second
  guard. The operator supplied the account's global key instead (no key-level
  limit; `auth/key` reports `limit: null`). The run therefore proceeds with
  **one** enforced guard, the shared ledger in `harness/budget.py` (cap USD 5,
  reservation before every request, refusal before sending), and an outer
  bound that is not a guard but a fact: the account's remaining credit at run
  start, read from `/credits` before step 3 and recorded in the Run log. If
  the ledger's accounting is wrong, that balance is the most that can be
  spent. Recorded here so the deviation is the protocol's, dated, and not
  discovered in the report.
