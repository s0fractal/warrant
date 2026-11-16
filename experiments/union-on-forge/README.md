# R-UNION-ON-FORGE, measured (obligation c01ef100)

docs/V3.md §12 named the limit: GitHub's merge runs no union driver, so two pull requests adding neighbouring lines to
`.warrant/records.jsonl` conflict there, and the second must merge the base locally, where `.gitattributes`'
`merge=union` resolves it. The obligation is done when that is measured over a month of merges, or when the gate
rebases records-only conflicts itself.

`measure.py` merges again, in a temporary bare clone whose `info/attributes` sets `merge=text` for the three union
paths, every merge of the base into a branch in the window. A conflict there in records.jsonl is one the forge would
have refused. It reads Git objects only.

## Result, 2026-10-16 .. 2026-11-16 (`result-2026-10-16..2026-11-16.json`)

- 312 pull request merges on master; 123 merges of the base into a branch.
- 14 of those 123 conflict in `.warrant/records.jsonl` without the union driver, 13 in it alone: about one pull
  request in 22 would have stopped on the forge for its records.
- 5 of the 14 were made by the gate itself (`refresh_verdicts` in warrant/gate.py: a verdicts-only pull request
  GitHub cannot merge is carried by a new one with the base merged in, records only, "records only (warrant-gate)").
  The other 9 were agents' local `git merge` of the base, one command each.
- The union paths conflict more for other files: `CHANGELOG.md` 40 times, `tests/mutants.py` 27 (both `merge=union`),
  and files with no driver (`SPEC-CLAIMS.md` 15, `WITNESSES.md` 10, `REVIEWS.md` 7) needed hands.

## Decision

The records' conflicts on the forge are rare and already cheap: the verdict pull requests, which conflict most because
their CI runs long, are carried by the gate, and every other one took one local merge. No general rebase by the gate:
it would be a constitutional change (warrant/gate.py) for about nine merges a month. What would cost more is named as
the residual: CHANGELOG.md and tests/mutants.py rely on the same driver forty and twenty-seven times a month.

    python3 experiments/union-on-forge/measure.py --since 2026-10-16 --until 2026-11-16
