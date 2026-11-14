# Adoption experiment: how to rerun

PLAN.md is the pre-registration (question, tasks, arms, flags, scorer, decision rules). This page is the procedure.

| file | what it is |
| --- | --- |
| `facts.py` | the one table of facts per task; both renderers read it |
| `fixture.py` | builds one run's repository for (task, arm); `verify` reads a store with the installed CLI |
| `entry/AGENTS.block.md` | the candidate entry block (arm A's AGENTS.md): the thing under test |
| `scorer.py` | the frozen scorer, `--selftest [--kit DIR]` |
| `mutants.py` | hand mutations of the scorer and the renderer; each must fail the self-test |
| `run.py` | `setup`, `smoke`, `round NAME` |
| `summarize.py` | the table per arm × model × task and the decision rules |
| `round-smoke/` | the one uncounted smoke run |

## Before a round

```sh
cd experiments/adoption
python3 run.py setup                                   # .work/venv with warrant-graph[mcp]==3.0.0a7, .work/kit-bin, .work/agent-bin
python3 scorer.py --selftest --kit .work/kit-bin       # every fixture in every arm, read by the released CLI: "all passed"
python3 mutants.py                                     # every mutant KILLED
shasum -a 256 PLAN.md                                  # the digest the registered record names
```

Register the plan as a signed record, then write its record id (64 lowercase hex, one line) to `REGISTERED`.
`run.py round` refuses to start without it, and writes `round-N/round.json` (the record id, PLAN.md's and the entry's
digests, the claude version, the flags); a round resumes only with the same settings.

## A round

```sh
python3 run.py round round-1 --jobs 3                  # 3 tasks × 3 arms × 2 models × 3 = 54 runs
python3 summarize.py round-1
```

A run whose `score.json` exists is skipped, so an interrupted round is resumed by the same command. A run is
`round-1/<task>-<arm>-<model>-<k>/`: `prompt.md`, `transcript.jsonl` (normalized), `fixture.json` (commits, the
released CLI's reading of the store, the answers, the exact argv, exit status), `agent.diff` (what the agent changed,
if anything) and `score.json` (with `leaks`: what the credential/home-path scan found after normalization).

Before committing a round: `summarize.py` names every run with a leak-scan hit; read those transcripts and do not
commit one that holds anything of the operator's. If R1 says "Both < 6", revise `entry/` alone and run
`python3 run.py round round-2 --arms S,A --jobs 3`; then `python3 summarize.py round-1 --entry-round round-2`.

Spend: `run.py` stops starting runs when the scored runs of every round (smoke included) plus 0.75 per run in flight
would exceed $25.

## Isolation, briefly

Each run gets a fresh temporary directory (fixture repository, an empty HOME for the agent's tools, the MCP
configuration), deleted afterwards. The claude process runs with an environment built from nothing and the operator's
HOME only because its login is in the macOS keychain; PLAN.md says what that does and does not isolate.

CI does not run the self-test. A case in `tests/tools_test.py` did for one push (AD1): it added eight seconds to a
suite the mutant runner repeats for every tools mutant, and one mutant shard ran past its 30 minutes. The harness is
frozen evidence of round 1; rerun `python3 scorer.py --selftest --kit .work/kit-bin` and `python3 mutants.py` by hand
before reusing it.