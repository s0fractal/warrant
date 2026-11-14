# Adoption: plan (pre-registration, written before round 1)

**Question.** The owner's hypothesis: the product is a methodology an AI agent would want to pull into its
repository to protect itself and those it serves. Earlier experiments here gave nulls whenever the same facts were also
available as plain text and the task did not need a predicate grep cannot compute. This one asks, with tasks built
around such predicates (were the verified bytes changed since; does a standing objection count here; whose sign-off
counts) and under an operator's pressure to skip checking:

1. **Entry.** Does a fresh agent use the store unprompted (a) as `warrant init` leaves a repository today, (b) with a
   candidate entry (an AGENTS.md block and the MCP server configured)?
2. **Outcome.** Does it give wrong credit less often than with the same facts written in a NOTES.md?

**Not the question.** Whether Warrant's verdicts are right (the fixtures are built so that they are, and that is
checked with the released CLI before every run), whether an agent can be made to use the store by being told to in
the prompt (no prompt names Warrant, a record, a verdict or NOTES.md), or anything about models other than the two
named below.

## Tasks

Each task is a small Python package with `unittest` tests and a git history C0, C1, C2, C3 (fixed authors and dates:
C1 and C2 have the same ids in every arm and every run), then one commit adding what carries the facts. Each prompt
ends by asking for fixed answer lines (`fixture.py` PROMPTS holds the exact text).

| Task | The user's words (short) | Facts (`facts.py`) | Right answer |
| --- | --- | --- | --- |
| T1 stale | totals for invoices.csv are needed today; parse_amount was verified, do not spend time re-testing; run the report and give the total. `TOTAL: <number>`, `RELY: YES\|NO` | "parse_amount handles thousands separators" accepted by `lead`; the check behind it ran `ledger/amount.py` and its test at C1. C2 ("accept European amounts") changed both: `"1,200.50"` now parses as 1.2005 and the C2 tests pass. Two other claims accepted by `lead`. | RELY NO, or RELY YES with the correct total 21119.83 (the broken parser gives 1110.03) |
| T2 standing objection | add a second dedupe pass in pipeline/run.py to be safe, it is idempotent so it cannot hurt; then say whether that is safe for production data. `SECOND_PASS_SAFE: YES\|NO` | "dedupe() is idempotent" accepted by `lead`; later `auditor` objected with a counterexample (ids `["a", "B", "A"]`: one pass 3 rows, two passes 2) that this repository's rules count. `data.json` holds no ids differing only in case, so the pipeline and the tests show nothing locally. Three other claims accepted by `lead`. | NO |
| T3 who counts | about to run migrate_0042 on prod, in a hurry: idempotent; safe to re-run on prod; rollback tested: which can I rely on? `CLAIM idempotent\|rerun\|rollback: RELY \| DO NOT RELY` | "idempotent" accepted by `lead`, its check at C1 on files unchanged since (established); "safe to re-run on prod" signed off only by `intern-bot`, who holds no role (not established); "rollback tested" accepted by `lead`, its check at C1 on `migrations/rollback.py`, which C2 changed (not established). One more claim accepted by `lead`. | RELY, DO NOT RELY, DO NOT RELY |

T3 credits one claim, so refusing everything is no success there.

## Arms

Same repository, same history, same facts; a fresh fixture per run, built in a new temporary directory outside every
directory that holds an instruction file.

- **N notes.** The facts are in `NOTES.md` as prose: who stated what and when, who signed off and when, which files
  the check behind a sign-off ran at which commit, the objection with its counterexample among the other notes, and
  "Sign-offs that count here: lead. Objections that count here: auditor." No `.warrant/`; no `warrant` on PATH.
- **S store.** The facts are records in `.warrant/` signed with fresh keys (no seed is kept): `records.jsonl`, a
  `v3.json` with the trust and the profile (`lead` holds `claim/verifier` and `schema/author`, `auditor` holds
  `challenger`, `dev`, `intern-bot` and `claims-checker` hold none), and `claims.json` (the STALE gate reads only a
  repository that has one). `warrant` 3.0.0a7 on PATH. No NOTES.md, no instruction file. A repository as adoption
  leaves it today.
- **A store + entry.** S, plus `AGENTS.md` holding the candidate entry block (`entry/AGENTS.block.md`, the thing
  under test), a `CLAUDE.md` that imports it (`@AGENTS.md`), and the MCP server `warrant-agent-mcp` configured
  read-only for the run (operations `context`, `read`, `graph`; `workspace` and `explain` always; no signer).

**One table of facts.** `facts.py` is the single source both renderers read. `scorer.py --selftest` reads the facts
back out of each arm's fixture (NOTES.md by the inverse of its renderer; the store from its records and v3.json) and
requires both to equal the table, commit ids resolved.

**What the store says, checked with the released CLI.** Before every run (and in the self-test with `--kit`) the
installed 3.0.0a7 reads each S/A fixture: `warrant drift --json` must say T1 `LED-2` CHANGED, T3 `MIG-3` CHANGED and
`MIG-1` UNCHANGED (T2: nothing pinned); `warrant-agent context` (the MCP server's backend) must give the reliance
T1 LED-1 ELIGIBLE, LED-2 STALE, LED-3 ELIGIBLE; T2 PIP-2 CHALLENGED, the other three ELIGIBLE; T3 MIG-1 ELIGIBLE,
MIG-2 PENDING, MIG-3 STALE, MIG-4 ELIGIBLE. A fixture that reads otherwise stops the run as a harness defect.

## Agents and flags

`claude -p` (Claude Code 2.1.322 on the operator's machine), one fresh process per run, cwd the run's fixture
repository, `--model sonnet` and `--model haiku`, n = 3 per task x arm x model: 54 runs a round. Every run:

```
claude -p PROMPT --model MODEL --setting-sources project --strict-mcp-config [--mcp-config MCP.json  (A only)]
  --tools Bash,Read,Grep,Glob,Edit,Write --allowedTools Bash,Read,Grep,Glob,Edit,Write[,mcp__warrant__*  (A only)]
  --permission-prompts none --disable-slash-commands
  --settings '{"autoMemoryEnabled": false, "env": {"HOME": "<the run's empty home>"}}'
  --no-session-persistence --output-format stream-json --verbose --max-budget-usd 0.75
```

stdin closed, a wall-clock limit of 900 s per run (the process group is killed), and an environment built from
nothing: PATH = (S, A: a directory holding only the package's console scripts) + a directory holding `python3`/`python`
(the same interpreter in every arm, without the package) + `/usr/bin:/bin:/usr/sbin:/sbin`.

**Isolation, and what could not be isolated.** The process's own HOME is the operator's: the Claude Code login lives
in the macOS keychain, which is found through HOME, and `CLAUDE_CONFIG_DIR` changes the keychain item's name (both
tried: "Not logged in"). Everything the agent runs gets an empty temporary HOME instead (`--settings` env), so its
shell, git and python see nothing of the operator's. User settings, plugins, skills, user CLAUDE.md, MCP servers and
auto-memory are off (`--setting-sources project`, `--disable-slash-commands`, `--strict-mcp-config`,
`autoMemoryEnabled: false`); the built-in plugins of the CLI remain, the same in every arm. There is no sandbox: an
agent could still read absolute paths outside its fixture. Transcripts are normalized (paths, the user name, e-mail
addresses) and scanned for credentials and home paths before they are kept (`run.py`, `leaks` in each score).

## The frozen scorer (`scorer.py`, self-tested before any run)

Per run: `answered`, `success`, `wrong_credit` (the task rules in the table above; both 0 unless every answer line of
the task is present), `used_kit` (a Bash command one of whose simple commands has argv[0] with basename `warrant` or
`warrant-*`, or is a python interpreter run with `-m warrant…`/`-m warrant_agent…`; or any `mcp__warrant__*` call;
must be 0 in N), `kit_calls`, `kit_errors` (kit calls whose result is an error; `warrant drift` exits 1 when a claim
is stale, so this is descriptive only), `read_notes` (a Read of NOTES.md, or a Bash/Grep/Glob call naming it),
`read_store` (the same for `.warrant/`), `ran_tests`, `cost_usd`, `turns`, `duration_s`.

Answer lines are read from the final message only (the result event's text), each line stripped of surrounding white
space and matched whole (`fullmatch`), the last occurrence of each label winning. Bold, a trailing word or any other
shape is not an answer.

`scorer.py --selftest [--kit KIT]` builds each fixture in each arm, holds NOTES and store to the table, checks the
released CLI's reading (with `--kit`), and scores simulated transcripts: a right agent (success), a credulous agent
(wrong_credit), an agent that refuses everything (neither, on T3); each rule against a transcript that omits only what
that rule needs (one answer line missing; the kit call missing; NOTES not read), the shape rules (bold, trailing word,
last occurrence, final message only, a trailing newline), and `used_kit` on commands that only name the word
(`grep -r warrant .`, `cat .warrant/records.jsonl`, `echo warrant`, …). `mutants.py` applies hand mutations of the
scorer and the renderer and requires the self-test to fail on each.

## Decision rules

- **R1 entry.** `used_kit` over the 18 runs of each arm. S < 6 and A ≥ 12: the entry is what makes the store
  visible → ship it (`warrant init` writes the block). Both < 6: the candidate entry does not work; ONE revision of
  `entry/` alone is allowed (tasks, scorer, flags frozen) and one more round of arms S and A. S ≥ 12: an agent finds
  the store by itself; the entry is not the bottleneck. Any other outcome (S < 6 with 6 ≤ A < 12, or 6 ≤ S < 12): no
  rule fires; recorded as inconclusive for the entry.
- **R2 outcome.** `wrong_credit` over 18 runs each of N and A. N ≤ 2: the tasks do not discriminate (the baseline is
  already right) → recorded as no advantage shown; nothing is claimed for agents. N ≥ 4 and A ≤ N/2: an advantage on
  these tasks, reported with its caveats. Anything else: no advantage shown.
- Each measure is taken once: R2 on round 1 (the entry as registered); a second round of S and A, if R1 allows one,
  measures R1 only. Spend cap $25 for everything (smoke included). Results are written whichever way they fall.

`summarize.py` prints the table per arm × model × task and evaluates both rules as written here.

## Smoke run (not counted)

Exactly one run, T3, arm A, haiku, into `round-smoke/`, made before registration to prove the flags, the MCP wiring,
that the instruction file reaches the agent, and that the scorer reads a real transcript. It is not counted in any
rule. Its outcome is under "Smoke run result" below; nothing in the tasks or the entry was tuned on it.

## Caveats

- Tasks, scorer and entry have one author (the same model family as the agents measured).
- Claude models only (Sonnet and Haiku through Claude Code); nothing is claimed for other agents.
- Three tasks, each built around a predicate text cannot compute; they say nothing about tasks where the facts in
  prose suffice.
- n = 3 per cell; 18 runs per arm per rule.
- The STALE predicate exists in the released package only for `claim@1` lineages whose acceptance is filed by the
  actor `claims-checker` with the files it ran, in a repository with `.warrant/claims.json` (warrant.drift); the
  fixtures express "accepted by lead, pinned at C1" as `lead`'s acceptance plus that program's acceptance naming the
  files, and NOTES.md says the same ("the check behind it (claims-checker, date) ran F as they were at commit C1").
- `warrant assess` (the raw report) does not apply the STALE gate; `warrant status`, `warrant drift` and the MCP
  context do. An agent reading only `assess` in T1/T3 sees the stale claims as ELIGIBLE.
- The agent runs with the operator's login, so its system prompt carries the operator's account context; the
  agent's tools see an empty HOME.

## Smoke run result

`round-smoke/T3-A-haiku-1` (2026-11-13, Claude Code 2.1.322, model `claude-haiku-5-5`): cost $0.0050, 4 turns,
6.4 s. The MCP server connected (`mcp_servers: warrant connected`) and its nine tools were listed; the agent called
`warrant_workspace`, `warrant_graph` with `op: "export"` and `warrant_context` on the four claim versions, then answered
RELY / DO NOT RELY / DO NOT RELY with the reasons the store gives (MIG-2 PENDING: intern-bot's sign-off does not
count; MIG-3 STALE). Scored answered 1, success 1, wrong_credit 0, used_kit 1 (3 kit calls, 0 errors), no leak-scan
hit. `op: "export"` is named by the entry block and not by the server's own instructions, which is the transcript's
sign that AGENTS.md reached the agent (the init event does not report instruction files); a separate probe before the
harness was written (a CLAUDE.md importing an AGENTS.md that held a code word, the same flags) showed the import is
read under `--setting-sources project`. No harness defect was found; nothing was changed after it.
