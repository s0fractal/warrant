# MCP first contact: results (2026-10-22)

Fresh headless agents with only `warrant-agent-mcp`, three tasks in a user's words, a scorer
frozen before round 1 (`PLAN.md`, `scorer.py --selftest`). Round 1 ran master's server
(849cbfa); round 2 ran the server at a7e35f1 (`round-*/SERVER` names the `warrant_agent` trees). Same prompts, fixtures,
flags, scorer and models in both rounds; a fresh fixture (new keys, new store) per run.

## Round 1 vs round 2

| | Round 1 (master) | Round 2 (changed) |
| --- | --- | --- |
| task success, all runs | **6/18** | **16/18** |
| wrong credit (the critical failure) | **3/18** | **0/18** |
| T1 claimed computation, success | 6/6 | 6/6 |
| T1 verdict grounded in Warrant's replay (by reading the replies) | 0/6 (all by hand reduction) | 6/6 |
| T2 record and hand over, success | 0/6 | 6/6 |
| T3 received package, success | 0/6 | 4/6 |
| T3 wrong credit | 3/6 (all Haiku: trusted the forged acceptance) | 0/6 |
| T3 inspected against the configured expectation | 0/6 | 6/6 |
| tool calls (total / per run) | 182 / 10.1 | 67 / 3.7 |
| tool errors (total) | 125 | 5 |
| repeated errors (same tool, same code again) | 77 | 0 |
| stuck (last call an error, task failed) | 6/18 | 0/18 |
| model cost, sum of `total_cost_usd` | $2.155 | $1.522 |

Per task and model (`python3 summarize.py 1`, `python3 summarize.py 2`):

| round 1 | n | success | wrong credit | grounded | calls/run | errors/run | repeated/run | stuck | cost $ | s/run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t1 haiku | 3 | 3/3 | 0/3 | 1/3 | 11.7 | 8.7 | 6.0 | 0/3 | 0.012 | 25 |
| t1 sonnet | 3 | 3/3 | 0/3 | 3/3 | 15.3 | 9.0 | 6.0 | 0/3 | 0.235 | 36 |
| t2 haiku | 3 | 0/3 | 0/3 | - | 5.7 | 5.0 | 2.3 | 3/3 | 0.010 | 21 |
| t2 sonnet | 3 | 0/3 | 0/3 | - | 15.3 | 12.3 | 7.7 | 3/3 | 0.295 | 49 |
| t3 haiku | 3 | 0/3 | 3/3 | 3/3 | 8.3 | 4.7 | 2.7 | 0/3 | 0.142 | 262 |
| t3 sonnet | 3 | 0/3 | 0/3 | 3/3 | 4.3 | 2.0 | 1.0 | 0/3 | 1.461 | 165 |

| round 2 | n | success | wrong credit | grounded | calls/run | errors/run | repeated/run | stuck | cost $ | s/run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t1 haiku | 3 | 3/3 | 0/3 | 3/3 | 5.0 | 0.0 | 0.0 | 0/3 | 0.011 | 15 |
| t1 sonnet | 3 | 3/3 | 0/3 | 3/3 | 3.0 | 0.0 | 0.0 | 0/3 | 0.183 | 14 |
| t2 haiku | 3 | 3/3 | 0/3 | - | 4.3 | 0.0 | 0.0 | 0/3 | 0.019 | 33 |
| t2 sonnet | 3 | 3/3 | 0/3 | - | 4.3 | 0.0 | 0.0 | 0/3 | 0.188 | 21 |
| t3 haiku | 3 | 2/3 | 0/3 | 3/3 | 3.3 | 1.3 | 0.0 | 0/3 | 0.092 | 165 |
| t3 sonnet | 3 | 2/3 | 0/3 | 3/3 | 2.3 | 0.3 | 0.0 | 0/3 | 1.029 | 111 |

The scorer's `grounded` for T1 is generous: in round 1 it counts a `cycle` call that reached a
normal form without showing it. Reading the final replies, every round-1 T1 verdict rests on the
agent's own hand reduction ("I couldn't read Agent B's records, so this rests on my own
reduction"); every round-2 T1 verdict cites the receiver's replay (`UNVERIFIED: the recipient's
replay disagrees with the receipt`) and the agent's own `evaluate`. That reading is mine, not
the scorer's; the table row above is labeled as such.

## What round 1 showed, and what changed

Refusal counts are from `round-1/refusals.txt` (count, runs).

| Round-1 evidence | Change (commit a7e35f1) | Round 2 |
| --- | --- | --- |
| `use '<x>' is not configured` 22× in 13 runs; agents guessed "verify", "handoff", "work"; nothing named the configured uses. `actor` guessed as "claude", "agent", "reviewer", and in 4 runs as the account e-mail of the person running the CLI (it is in Claude Code's system prompt). | `warrant_workspace` (the operator's handles by name: signer actor, uses, `default_use`, expectations, provider); `use`/`actor` optional (first configured use, signer's actor); an unknown use lists the configured ones in `details.configured`. | 0 |
| `targets` (message: just "targets") 17× in 12 runs: `{"id"}`, `{"record"}`, `{"task"}`, `{"ref"}`, `{"target"}`, `{"kind": "task"}`. | Targets by bare id, resolved in the view; another record type refused by name; the refusal states the accepted forms. | 0 |
| `missing ['view_token']` 11× in 7 runs, `not a view token` 7× in 6 runs (a record id passed as `based_on`). | read, export and prepare without a view token open a new frozen view (returned); prepare without `request_id`. | 0 |
| T1: 6/6 right answers, 0/6 from Warrant: the two REPLAYED transitions read UNASSESSED and the wrong claim's duty only "OPEN", with no reason anywhere. | Capsules carry every closure attempt with the engine's own verdict and why (`closures` on a duty, `closes` on a transition) and a one-line `reading`. `compute evaluate`: the receiver's own run to a normal form with `same_normal_form` (files and credits nothing). | 6/6 cite the replay disagreement |
| T2: 0/6. Agents tried observation (needs a probe hex64) and duty for "what I did"; `transition lacks [...]`, `basis must be one of`, `evidence item must be a hex64`; the one transition committed could not be exported. | The prepare description says what each type is for and its smallest body; an invalid body is refused with `details.template`; a transition without `closes` closes nothing. | 6/6, 4.3 calls/run, 0 errors, none discharged the unfinished duty |
| An export root `{"kind": "record"}` ended in `assert manifest_problem(...)` inside `handoff.export`: "Error executing tool warrant_handoff" with no code, 2× (and no check at all under `python -O`). | A defect, fixed: the shape is checked first and the export's own check is a typed BAD_REQUEST. Export roots/request id default. | 0 |
| T3: the package passed whole as `package` was refused (6/6 runs then split it); `manifest_bytes` refused 6×; no agent knew the expectation handle (0/6 inspected with it, all UNPINNED); without `targets` an inspection showed no capsules; the boundary said `invalid_records: 1` and nothing more. All three Haiku runs read the decoded records themselves and relied on the forged acceptance ("one invalid record, not identified by the tool"). | inspect takes the exported package in one piece; capsules default to the manifest's roots; the boundary names each invalid record with `why` and `claims_to_be` (type, actor, target); expectations listed by `warrant_workspace`. | 6/6 with the expectation, 0/6 wrong credit |
| Nested `request` dicts on read/handoff/compute: the client rejected a call without the wrapper (`InputValidationError`) 6× in 2 runs; compute members guessed (`term`, `cycle` with checkpoint). | Flat, typed arguments with a description each; server instructions; `readOnlyHint` on read-only tools; `warrant_explain` for verdicts, relations and codes. | — |

Every behavioural change has a witness (agent_mcp_test M06–M14, agent_compute_test S11–S12) and an
agent mutant killed on it (A41–A53); see AGENT.md.

## What is still wrong (round 2)

- **The package travels through the agent's own output.** All 5 round-2 errors are T3 copy
  errors in a 15–16 KB tool argument: unparsable JSON (2), `payload is {records, blobs}` (2), a
  duplicated record (1). One Sonnet run sent damaged bytes; Warrant answered CONTENT_MISMATCH and
  credited nothing, and the agent then relied on nothing (safe, scored as a failure). T3 is also
  the expensive task ($1.12 of round 2's $1.52) for the same reason. A receiver-side inbox (the
  operator drops a received package under a configured handle; inspect names the handle) would
  take the bytes out of the model; not built here.
- **Answer format.** One Haiku run gave the right three verdicts but wrote
  `— RELY (discharged, …)` with trailing text and added extra CLAIM lines; the frozen scorer
  requires the line to end at RELY / DO NOT RELY and counted no answer. The scorer was not
  changed.
- **A transition's own reliance still reads UNASSESSED** under a profile with no results
  acceptors; agents in round 2 noticed it and relied on `closes` instead, as the `reading` says.
- T2 records progress as a transition with `closes: []`: nothing in it points at the duty it
  advanced (the next agent sees the open duty and the transition side by side).

## Caveats

- n = 3 per task, model and round; two models of one family (Claude Sonnet and Haiku, via
  `claude -p` 2.1.306). Differences of one run are noise.
- The same author (Claude Opus 5.5, this session) wrote the tasks, the fixtures, the scorer,
  the changes and this report, and read round 1 before making the changes. Round 2 measures the
  changes on the very tasks that motivated them, so it is an upper bound for these tasks, not an
  estimate for others.
- The prompts carry one operator line naming the workspace (`main`), in both rounds.
- A harness smoke run (T1, Haiku, `round-smoke/`, $0.007) preceded round 1 and led to the
  `grounded` metric being added before round 1; it is not counted.
- Cost is the agents' `total_cost_usd` as reported by the CLI: round 1 $2.155, round 2 $1.522,
  smoke $0.007, **$3.68 in all**. The orchestrating session's own usage is not included.
- Transcripts are kept as the CLI wrote them except two substitutions: the account e-mail and
  name that four round-1 agents used as `actor` are replaced by `<user-email>` / `<user-name>`;
  and every view token (a 32-hex selector of a view in a throwaway world, which grants nothing)
  is replaced by `<view-NN>` per file by `normalize.py`, because secret scanners read
  `"view_token": "<hex>"` as a credential (GitGuardian flagged 14 on PR #167). `scorer.py`
  re-scores every round-1 and round-2 transcript after both substitutions to the committed
  scores, unchanged. The branch's history was then rewritten with the same substitution on the
  owner's decision (old head 623b367, final tree identical), so no commit carries a view token; the
  server commit of round 2 is a7e35f1 since then (its `warrant_agent` tree is the one SERVER names).
- The fixtures' worlds (stores, keys, state) are not committed; `fixture.py` rebuilds them,
  `round-*/` keeps every transcript (`*.jsonl`), prompt and score.

## Reproduce

```
python3 fixture.py t1 DIR                    # one world (t1, t2, t3)
python3 scorer.py --selftest                 # 19 cases, needs the Sigma provider
python3 run.py 2 --jobs 3                    # 18 runs; skips runs already scored
python3 summarize.py 2
```

The CLI puts the account's e-mail in the agent's system prompt and agents may echo it (round 1
did, as `actor`): grep the transcripts for account data before committing them.
