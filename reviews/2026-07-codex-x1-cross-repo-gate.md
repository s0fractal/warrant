# X1 cross-repo gate — independent adversarial review

**Reviewed:** warrant `feat/x1-cross-repo` at `0402190` (including Go fix
`65067a6`) and sigma-glyph `feat/x1-cross-repo` at `c852f90`
**Scope:** X1 workflow, mirrored shell gate, negative controls, and the claimed
49-vector Go conformance coverage; no release/adoption/WRT-002 review
**Verdict:** **AMEND**

X1 is the correct next production primitive: pinned reproducibility and live
HEAD-to-HEAD compatibility are different questions, and both are needed. The Go
change also closes a real shipped coverage defect. The current gate can still
report `ALL PASS` while omitting the very surfaces it claims to guard.

## Findings

### P1 — Required Go crossings can silently SKIP and the job still passes

`tools/x1_cross_repo.sh` deliberately aggregates failures, but a failed Go build
does not become a failure:

```bash
if (cd "$WARRANT/impl-go" && go build ...); then
  WGO=...
fi
```

When the build fails, A1, A2, and C2 call `c_skip`. The final verdict depends
only on `FAIL == 0`, so it prints:

```text
X1-CROSS-REPO: ALL PASS
```

with no Go implementation tested.

The negative controls do not close this in both directions. When X1 runs from
sigma-glyph with warrant as the sibling, the applicable controls are D1 and C1;
neither requires A1/A2/C2. A broken sibling Go build can therefore yield green
X1 and green controls from that side.

**Required fix:** CI must run a strict/full mode in which missing toolchains,
failed builds, and skipped required A–D crossings are failures. Keep optional
SKIP behavior only for an explicitly selected local/degraded mode. The workflow
must set strict mode.

**Countervectors:**

- introduce a Go compile error in the sibling and require each repository's X1
  workflow to fail at the Go build/A1 boundary;
- hide `go` from PATH under strict mode and require failure;
- prove that zero required A–D steps can be skipped in CI.

### P1 — X1 does not bind `ALL PASS` to 49 vectors or to all three kinds

A1 checks only that successful output contains the substring `ALL PASS`.
It does not assert `49/49` or the per-kind coverage
`8 deserialize, 33 eval, 8 object`.

The negative control described as an “expected result-hash” control mutates the
first 64-hex expected value. In the current vector ordering that is:

```text
vector 0: OBJ-I, kind=object, expected.hash
```

Thus it proves only that one `object` vector is read. No control exercises an
`eval` expected result, and none flips a `deserialize.expected.valid` value.
A future regression that silently skips all eight deserialize vectors while
still printing `ALL PASS` would leave X1 and its controls green — the exact
defect class this change is meant to retire.

**Required fix:** derive the expected kind counts from the vector file and
require the producer summary to match them exactly. Add three named A1 controls:

- change an `object.expected.hash`;
- change an `eval.expected.result_hash`;
- invert a `deserialize.expected.valid`.

Each must turn A1 red for the intended reason.

### P1 — Permanent “mirror absent = SKIP” makes gate deletion fail open

Section E treats a missing sibling X1 file as SKIP to permit initial staggered
landing. That bootstrap exception remains permanent.

After both sides are deployed, deleting X1 from one repository creates a stable
bypass:

1. the deleted workflow no longer runs in that repository;
2. the surviving repository sees the sibling file absent;
3. Section E emits SKIP;
4. `FAIL` remains zero and X1 reports `ALL PASS`.

The mirror-integrity mechanism therefore detects divergence but not removal.

**Required fix:** make bootstrap state explicit and temporary. For example,
land a version/required marker in both repositories, after which any missing
mirror file is fatal. The final production commits must not retain the
absence-as-SKIP rule.

**Countervector:** delete each of the three mirrored files from either sibling,
one at a time, and require the surviving side to fail Section E.

### P2 — B1 does not bind the JSON report to process behavior

B1 discards the verifier's return code and stderr:

```python
out = subprocess.run(..., capture_output=True, text=True).stdout.strip()
```

A verifier regression that emits `ok:true` JSON but exits non-zero is accepted.
Non-empty stderr is also ignored, despite the machine-boundary contract's
single-clean-JSON posture.

**Required fix:** assert exact return-code semantics (`0` iff `ok`, otherwise
the documented failure code) and exact empty stderr before accepting the
report.

## What holds

- The Go implementation now dispatches all currently known vector kinds and
  rejects unknown kinds.
- Current Book I vectors agree 49/49; the discovered defect was hidden coverage,
  not a known semantic divergence.
- Pin drift is correctly informational rather than silently changing the
  reproducible pin.
- X1 is honestly labelled a regression gate, not an independent adversarial
  review.
- Controls require the predicted step to fail, rather than accepting any
  non-zero result.
- The two repository copies are byte-identical at the reviewed heads.

## Landing gate

After the three P1s are closed:

1. re-run the negative controls from both repository directions;
2. verify exact zero-SKIP strict CI and exact per-kind coverage;
3. merge the warrant X1/Go fix and sigma X1 mirror as one coordinated landing;
4. only then update reproducible sibling pins in a separate commit.

Release-surface, adoption/action packaging, and WRT-002 should remain separate
review tracks.

No merge, push, release, pin update, adoption, or governance action was
performed by this review.
