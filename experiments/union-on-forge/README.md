# R-UNION-ON-FORGE, measured (obligation c01ef100)

docs/V3.md §12 named the limit: GitHub's merge runs no union driver, so two pull requests adding neighbouring lines to
`.warrant/records.jsonl` conflict there, and the second must merge the base locally, where `.gitattributes`'
`merge=union` resolves it. The obligation is done when that is measured over a month of merges, or when the gate
rebases records-only conflicts itself.

`measure.py` reads the history pinned at a commit (`--at`) between two timestamps. It merges again every merge of
the base into a branch in the window (a merge whose second parent is on master's first-parent line), in a temporary
bare clone whose `info/attributes` sets `merge=text` for the three union paths (the forge) and again with
`merge=union` (a local merge). A conflict in the first in records.jsonl is one the forge would have refused. It reads
Git objects only.

## Result, 2026-10-16T00:00Z .. 2026-11-16T23:59Z at 8cc8b52b (`result-2026-10-16..2026-11-16.json`)

Corrected after Codex's challenge e65ebaba: the first count took every ancestor of master as "the base", so 17 merges
of one branch into another were read as base updates, and it attributed five conflicts to the gate where four are its.

- 314 pull request merges on master; 106 merges of the base into a branch (17 branch-into-branch merges counted apart).
- 14 of those 106 conflict in `.warrant/records.jsonl` without the union driver, 13 in it alone. They are 14 events
  in 12 distinct pull requests: about one pull request in 26 would have stopped on the forge for its records.
- 4 of the 14 were the gate's carries (`refresh_verdicts` in warrant/gate.py: github-actions[bot] as author, GitHub as
  committer, "records only (warrant-gate)"); 10 were local merges of the base. With the union driver, 13 of the 14
  merge cleanly; one (db53a851) still conflicts in five code and doc files, work no driver does.
- The union paths conflict more for other files: `CHANGELOG.md` 39 times, `tests/mutants.py` 25 (both `merge=union`),
  and files with no driver (`SPEC-CLAIMS.md` 13, `WITNESSES.md` 9, `REVIEWS.md` 5) needed hands.

## Decision

The records' conflicts on the forge are rare and cheap: the verdict pull requests, which conflict most because their
CI runs long, are carried by the gate, and every other one but one took a local merge the union driver resolves; the
one left needed hands for its code, which a gate rebase would not have spared. No general rebase by the gate: it would
be a constitutional change (warrant/gate.py) for about ten merges a month. What would cost more is named as the
residual: CHANGELOG.md and tests/mutants.py rely on the same driver thirty-nine and twenty-five times a month.

    python3 experiments/union-on-forge/measure.py --at 8cc8b52b43f42afc8d1c0f21b5a5f7c8f08740c3
