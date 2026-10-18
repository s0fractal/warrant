# Rebuild state (working file; removed when the rebuild merges)

Goal: owner's GOAL-FOR-CLAUDE.md (2026-10-18), Warrant 2 rebuild.

- Base: master `8feb335` (merge #137), tag `history/warrant-0.x-2026-10-18`;
  `tools/check.py` there: 100 passed, 0 failed, 0 unrun.
- Branch: `rebuild/one-path`.

## Decisions on overlapping work

| work | decision |
| --- | --- |
| wrt-022/revalidation (9d7e354, RV-01/RV-02 fixed, unmerged) | 1: defect fixes carried into the new engine with their counterexamples (O1-O2, H1-H5) |
| wrt-022/s3-grants (d4d1ee6, unmerged) | 2: grants (roots, attenuation, release) are in the new contract (U4-U5) |
| wrt-023/effects-gates (b87ec4c, local draft) | 2/3: decision != attempt != effect becomes the `observation` record; frontier gates are not built; the draft is superseded |
| dogfood/wrt-022 store (old format) | 3: historical at the tag; open duties ee86a1c5 (revalidation) and e73729b1 (S3) were NOT discharged and are superseded by this rebuild, not closed |
| PR #60 WRT-008 fact derivation (open, deferred) | 3: superseded (fact provenance retired) |
| dependabot #111-#116 | 4: independent; obsolete for removed workflows |
| docs/sigma-warrant-decoupling (Codex, WRT-024) | 4/2: not touched (another session's worktree); its single-provider direction is applied here in Warrant only |
| sigma-glyph X1 mirror (HEAD vs HEAD) | owner action on sigma-glyph: its X1 job clones warrant master; see Blockers |

## Next slice

contract + engine + provider + CLI done locally; next: scenarios (examples/),
deletion of the superseded generation, CI, docs, mutants, review.

## Blockers

- sigma-glyph's required `cross-repo` check clones warrant master and checks byte-mirrored X1 files that the rebuild removes. A sigma-glyph PR that pins X1 to the historical tag needs the sigma owner's merge.
