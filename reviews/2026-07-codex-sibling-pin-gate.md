# Unified sibling pins — independent Codex gate

**Reviewed exact heads:**

- warrant `chore/unify-sibling-pin` at `4d486a3`, pinning sigma-glyph
  `c5ab2ab218bbeaaf4d80d2e49be2cc7b48fb7f37`;
- sigma-glyph `chore/unify-sibling-pin` at `3c7cad5`, pinning warrant
  `3972427688730e114507dc6fa14808eff8458fb5`.

**Scope:** pin unification and the CI consumers of those pins only.
**Verdict:** **AMEND**

Both branches are correctly based on the post-X1 master heads and each changes
only `.github/workflows/ci.yml`. The old fractured three-pin state is gone:
warrant has exactly one `SIGMA_PIN`, sigma-glyph exactly one `WARRANT_PIN`.
Every pinned artifact resolved and the targeted conformance paths passed.

One coverage seam remains in both workflows.

## Executed from clean exact-head exports

### warrant candidate → pinned sigma-glyph

- Python conformance: `45/45`;
- warrant-go sigma conformance:
  `49/49 — 8 deserialize, 33 eval, 8 object`;
- full `agree_check.sh`:
  - differential `45/45`;
  - settlement all agree;
  - runtime hook all pass;
  - pedantic edges `15/15`.

### sigma-glyph candidate → pinned warrant

- warrant-go sigma conformance:
  `49/49 — 8 deserialize, 33 eval, 8 object`;
- Book I fuzz with warrant-go: all agree;
- settlement machine boundary: `50 records, 0 warnings`;
- connector hostile/contract vectors: all pass;
- governed anchors through the pinned trust artifact: authorized.

Both branch diffs pass `git diff --check`.

## Finding

### P1 — The pinned CI gates still do not bind `ALL PASS` to full vector coverage

The X1 gate now derives and asserts the exact suite coverage. The reproducible
pinned jobs do not:

- warrant runs:

  ```yaml
  ./impl-go/warrant-go sigma-conformance .../vectors.json
  ```

  and trusts exit 0;

- sigma-glyph runs:

  ```yaml
  ... sigma-conformance vectors.json |
    grep -q "SIGMA CONFORMANCE: ALL PASS"
  ```

  and trusts the bare substring.

Both commands would accept the historical false-green producer:

```text
SIGMA CONFORMANCE: ALL PASS (33/33 eval)
```

The pin branches are meant to make the cross-implementation claim reproducible.
Reproducibly running a producer is insufficient if the consumer does not bind
the producer's declared scope to the pinned suite. X1 would likely catch a live
regression later, but that does not make the pinned gate's own claim true.

**Required closure in both workflows:**

1. derive total and per-kind counts from the pinned
   `tests/spec_conformance/vectors.json`;
2. capture warrant-go output and exit status;
3. require the exact derived summary, currently:

   ```text
   ALL PASS (49/49 — 8 deserialize, 33 eval, 8 object)
   ```

4. fail if any suite kind disappears unexpectedly or a new kind is unsupported.

Prefer one checked-in helper used by X1 and both pinned workflows, rather than
three copies of the coverage calculation.

**Required countervector:** substitute a successful producer that reports
`ALL PASS (33/33 eval)` and require both pinned jobs to fail at the
sigma-conformance coverage boundary.

## Process clarification

### P2 — “Refresh whenever behind HEAD” creates an impossible mutual-pin chase

The selected SHAs are correct reviewed semantic baselines: they are the two X1
landing commits. After these pin branches merge, both master hashes necessarily
change. Each pin will then be one metadata commit behind its sibling.

It is impossible for two content-addressed commits to contain each other's final
hashes: updating warrant's pin changes warrant's hash, which makes sigma's pin
old; updating sigma then changes sigma's hash, which makes warrant's pin old,
and so on.

Therefore the workflow comments must not instruct maintainers to refresh merely
because X1 reports that the pin is behind HEAD. Define the pin as a **reviewed
compatible semantic baseline** and refresh when relevant sibling surfaces
change—not for pin-only, documentation-only, or other explicitly irrelevant
commits.

The older warrant comment saying “refresh ONLY when Book I vectors change” is
also too narrow: this very refresh is needed because warrant-go coverage and
machine-boundary behavior changed without a Book I vector change.

Suggested trigger: refresh when a reviewed commit changes a consumed artifact
or its semantics:

- Book I vectors/oracle;
- warrant-go sigma evaluator;
- structured verifier/connector contract;
- out-of-band anchor trust.

Record old/new SHAs and the affected conformance outputs, as these commits
already do.

## What holds

- Each workflow has one visible sibling pin.
- Every consumer in sigma-glyph uses the same warrant SHA.
- The pinned commits exist on origin and contain the expected post-X1 surfaces.
- The pin-only diffs are isolated from release, adoption, README, EU profile,
  and WRT-002.
- HEAD-to-HEAD X1 and reproducible pinned testing remain correctly distinct.

No merge, push, release, adoption, or governance action was performed.
