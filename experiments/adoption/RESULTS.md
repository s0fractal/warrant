# Adoption: results of round 1 (2026-11-13)

Registered as goal `EXP-ADOPT-1`, record `4dd5fdc4…` (pushed 19:01 UTC, before the first counted run). 54 runs,
$1.26; with the smoke run and probes, $1.27 of the $25 cap. No run ended in an error or a timeout; the leak scan found
nothing. The table is `python3 summarize.py round-1`.

## The two registered rules

**R1 entry: fired, "ship it".** `used_kit` S = 0 of 18, A = 18 of 18. In a repository as `warrant init` leaves it
today no agent ran the CLI once; with the entry block in AGENTS.md and the MCP server configured every agent used the
store, in every task, on both models. The rule's consequence: `warrant init` writes the block.

**R2 outcome: "the tasks do not discriminate"; no advantage shown; nothing is claimed for agents.** `wrong_credit`
N = 0 of 18, A = 1 of 18. With the same facts in a NOTES.md, both models surfaced the stale check, the standing
objection and the sign-off that does not count, under an operator pushing to skip checking. The store did not make
them more right, and cost about twice as much to read (N $0.26, S $0.47, A $0.54 for 18 runs each).

## What else the round shows (descriptive, not registered)

- In arm S, 12 of 18 runs opened `.warrant/records.jsonl` and read the records as text; none ran `warrant`. An agent
  that finds the store treats it as a file to read, not as something to ask.
- The two wrong credits are both the store read past its own verdict. `T3-S-haiku-3` read the raw records and credited
  "rollback tested": the raw file shows the acceptance and nothing says it is stale. `T2-A-haiku-2` saw the objection
  through the tools, then reasoned from the code that a second pass is harmless and answered YES.
- A limitation of the frozen scorer: on T1 it reads 13 of 18 runs as unanswered, because the agent wrote
  `TOTAL: 1110.03 (as printed; the correct sum is 21119.83)` and the rule wants a bare number. By the `RELY:` line
  alone all 18 T1 runs say NO, in every arm. The scorer was not changed; `success` on T1 undercounts in all three arms
  alike, and `wrong_credit` is unaffected.

## What it does and does not establish

- Established for these two models and these three tasks: the store is invisible without an entry, and visible with
  this one. Arm A changed two things together (the block and the MCP server); which of them carries it is not separated.
- Not established: that a store helps an agent answer better than honest prose. Here the prose was true and complete
  (it named the commit the check was made at, and carried the objection). Notes that rot or lie, and a reader who must
  show someone else why it concluded what it did, are other questions; this round says nothing about them.
- One author wrote the tasks, the scorer and the entry; n = 3; Claude models only.
