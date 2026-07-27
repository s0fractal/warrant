# X1 cross-repo gate — final Codex re-gate

**Reviewed exact heads:**

- warrant `feat/x1-cross-repo` at `c65beb5`;
- sigma-glyph `feat/x1-cross-repo` at `d3a3bda`.

**Scope:** X1, the warrant-go 49-vector dispatch, mirrored workflow/scripts,
negative controls, and closure of the prior Codex findings.
**Verdict:** **APPROVE TO MERGE — coordinated landing required**

This is an independent adversarial review of the scoped X1 change. It is not a
governance adoption, release approval, pin approval, or review of any sibling
feature branch.

## Executed against clean exact-head exports

### warrant → sigma-glyph

- strict X1: `11 pass / 0 fail / 0 skip`;
- negative controls: `5/5`, each red at its predicted step:
  - roster → D1;
  - object vector → A1;
  - eval vector → A1;
  - deserialize vector → A1;
  - mirror deletion → E.

### sigma-glyph → warrant

- strict X1: `11 pass / 0 fail / 0 skip`;
- negative controls: `5/5`, each red at its predicted step:
  - roster → D1;
  - ski blob → C1;
  - mirror deletion → E;
  - unbuildable warrant Go tree → A1;
  - polluted verifier stdout → B1.

The three mirrored files were byte-identical at the reviewed heads. Both
repository diffs passed `git diff --check`.

## Closure

### Required crossings cannot SKIP into green

Closed. Strict mode is the default and the workflow pins it explicitly. A
required crossing that cannot execute is a failure. Degraded/bootstrap skips
produce `INCOMPLETE`, exit 1, never `ALL PASS`.

### A1 binds its full coverage claim

Closed. Expected total/per-kind coverage is derived from the suite and matched
against:

```text
ALL PASS (49/49 — 8 deserialize, 33 eval, 8 object)
```

Every current vector kind has an independent negative control.

### Mirror removal cannot disable X1 silently

Closed. Missing mirrored files are fatal outside the explicit bootstrap
diagnostic, and deletion has a live Section-E control.

### B1 binds report, exit, stderr, and raw framing

Closed. Raw stdout is checked before parsing or normalization. It accepts only:

- one JSON line with no terminator; or
- one JSON line with exactly one terminal `\n`.

It rejects an empty stream, leading blank lines, multiple trailing newlines,
whitespace-only suffix lines, and stray surrounding spaces. The injected
leading-blank-line control makes B1 red.

## Landing condition

The code is ready for a **coordinated two-repository merge**, with the
non-atomic seam stated honestly:

1. the human explicitly authorizes the first master merge despite the expected
   temporary mirror-absence result;
2. merge the other repository immediately;
3. rerun strict X1 on both master heads and require `fail=0, skip=0`;
4. only then review and land the separate sibling-pin branches.

Until step 3, do not report X1 as live and green on both masters.

## Out of scope

Not reviewed here:

- `feat/release-surface-gate`;
- `feat/adoption-surface`;
- `docs/eu-ai-act-profile`;
- either `chore/unify-sibling-pin`;
- sigma `feat/readme-lede`;
- WRT-002 or its Kimi adjudication;
- any release, publication, or governance adoption.

No merge, push, release, pin update, or governance action was performed by this
review.
