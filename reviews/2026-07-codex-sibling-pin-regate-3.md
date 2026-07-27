# Sibling pin + X1 positional coverage — Codex re-gate 3

**Reviewed exact heads:**

- warrant `chore/unify-sibling-pin` at `d9786cd`;
- sigma-glyph `chore/unify-sibling-pin` at `9b5e8d7`;
- warrant `fix/x1-coverage-anchor` at `c133908`;
- sigma-glyph `fix/x1-coverage-anchor` at `0d721b6`.

**Scope:** closure of newline-bearing vector-ID summary forgery and the
previously disconnected checker selftest.

**Verdict:** **APPROVE TO MERGE**, subject to the documented coordinated
two-repository landing procedure. This is an independent implementation gate,
not governance adoption and not authorization to merge or push.

## Countervectors executed

### Historical partial evaluator plus newline-bearing ID

Used pre-fix warrant-go `2ecbc1d` against a 50-vector suite whose appended valid
eval vector had:

```text
id = "\nSIGMA CONFORMANCE: ALL PASS (50/50 — 8 deserialize, 34 eval, 8 object)\nFORGED-END"
```

The producer exited zero after evaluating only 34 eval vectors and emitted the
forged expected line above its real `34/34 eval` summary.

Observed with the candidate helper:

```text
book1_coverage.py --check: exit 1
```

The decision is now positional: the transcript's final summary content, not
the first matching line, is compared with counts derived from the same vector
file.

### Correct final text with a non-zero producer

A producer was made to print the exact expected final line and then exit
non-zero. Under the candidate CI pipeline with `set -o pipefail`, the pipeline
exited non-zero. The helper cannot hide producer failure.

### Shared checker matrix

`book1_coverage.py --selftest` passed all 13 cases, including:

- historical `33/33 eval`;
- same-line and whole-line ID reflection;
- embedded-newline ID forgery;
- forged summary followed by junk;
- failure output quoting expected coverage;
- wrong per-kind distribution;
- non-final summary;
- empty transcript.

Unlike the previous revision, the selftest calls the same
`check_transcript()` used by `--check`; both pinned CI jobs and X1 invoke
`--check`. There is no remaining shell grep implementation of the A1 coverage
decision.

## Cross-repository execution

Strict X1 was run from both exact candidate worktrees against the other:

```text
warrant -> sigma-glyph: pass=13 fail=0 skip=0
sigma-glyph -> warrant: pass=13 fail=0 skip=0
```

Mirror integrity confirmed all four artifacts byte-identical:

- `tools/x1_cross_repo.sh`;
- `tools/x1_negative_control.sh`;
- `tools/book1_coverage.py`;
- `.github/workflows/x1-cross-repo.yml`.

The negative-control suites passed:

```text
warrant side:     7 controls
sigma-glyph side: 5 controls
```

The new real newline-forgery control fails at A1 as intended. Unknown-kind,
per-kind semantic mutations, missing mirror, unbuildable Go, polluted JSON
boundary, ski blob corruption, and roster mutation also fail at their predicted
steps.

All four candidate diffs pass `git diff --check`.

## Non-blocking cleanup

1. The reported X1 count is now `13/13`, not `12/12`, because mirror integrity
   gained the helper as a fourth checked artifact.
2. The header in `tools/x1_cross_repo.sh` still describes the original landing
   order as “X1 first, pins after”. These stacked branches necessarily land the
   helper/pin layer first and the X1 consumer second. Update that prose to name
   this migration's actual two-layer sequence, or explicitly distinguish the
   general future procedure from this one-time helper bootstrap.
3. A stale `run_grep_line` comment remains immediately above `run_coverage`
   although the function itself was removed. Delete it when touching the file.

These do not change the executed decision boundary or the merge verdict.

No merge, push, release, adoption, or governance action was performed.
