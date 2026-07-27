# Sibling pin + X1 coverage anchoring — Codex re-gate 2

**Reviewed exact heads:**

- warrant `chore/unify-sibling-pin` at `d672fd7`;
- sigma-glyph `chore/unify-sibling-pin` at `d616856`;
- warrant `fix/x1-coverage-anchor` at `fe736b0`;
- sigma-glyph `fix/x1-coverage-anchor` at `fcc4d13`.

**Scope:** closure of the vector-ID substring injection, permanent coverage
controls, and consolidation of the X1 coverage algorithm.

**Verdict:** **AMEND**

The previous same-line vector-ID countervector is closed: both pinned workflows
and X1 now match the complete producer prefix and use `grep -qxF`. The helper is
byte-identical in both repositories, X1 consumes it rather than retaining inline
Python, and mirror integrity now covers the helper.

The remaining seam is that a free-form vector ID can contain a newline. The
producer prints IDs without escaping, so attacker-controlled data can still
materialize an exact physical line that satisfies `grep -x`.

## P1 — Newline-bearing vector ID forges the anchored summary line

The Go producer prints a successful vector with:

```go
fmt.Println("OK  ", id)
```

JSON strings may contain escaped newlines, and the vector schema does not
constrain IDs to a single-line token. After decoding, an ID can therefore emit
additional physical lines.

### Executed countervector

Starting from the pinned 49-vector suite:

1. duplicate one valid `eval` vector;
2. set its ID to:

   ```text
   \nSIGMA CONFORMANCE: ALL PASS (50/50 — 8 deserialize, 34 eval, 8 object)\nFORGED-END
   ```

3. run pre-fix warrant-go `2ecbc1d`, which evaluates only the 34 `eval`
   vectors and skips the 16 non-eval vectors;
4. apply the new `grep -qxF "$EXPECT"` assertion and run the new helper
   selftest.

Observed:

```text
expected=SIGMA CONFORMANCE: ALL PASS (50/50 — 8 deserialize, 34 eval, 8 object)
producer_rc=0
anchored_workflow_rc=0
helper_selftest_rc=0

OK
SIGMA CONFORMANCE: ALL PASS (50/50 — 8 deserialize, 34 eval, 8 object)
FORGED-END

SIGMA CONFORMANCE: ALL PASS (34/34 eval)
```

The old false-green producer is still accepted by all four candidate consumers.
Whole-line matching prevents same-line injection but not line creation by
unescaped producer data.

### Required closure

Do not accept the first matching line. Bind coverage to a structural output
position or a machine-readable result.

The smallest compatible closure is:

1. capture the complete producer stdout and exit status;
2. require exit status zero;
3. require the **final physical output line** to equal `EXPECT` exactly;
4. preferably also require exactly one line beginning
   `SIGMA CONFORMANCE:`.

The producer emits its summary after processing every vector, so an ID printed
inside the loop cannot forge the final line. A structured `--json` producer
mode would be a stronger future boundary, but is not required for this patch.

## P1 — The permanent selftest does not exercise the consumer it claims to pin

`book1_coverage.py --selftest` tests a local Python function:

```python
return any(l == want for l in transcript.split("\n"))
```

The workflows and X1 do not call that function. They independently implement
acceptance with shell `grep -qxF`. Therefore:

- changing the real caller back to `grep -qF` leaves the selftest green;
- the newline-ID countervector passes the real caller while all nine selftest
  cases remain green;
- adding a case that the Python model rejects does not prove that the shell
  consumer rejects it.

Put transcript checking in the shared helper, for example:

```sh
warrant-go sigma-conformance "$V" |
  tee /dev/stderr |
  python3 tools/book1_coverage.py --check "$V"
```

with `set -o pipefail`. Then make `--selftest` call the same `check_transcript`
function used by `--check`. Include the embedded-newline ID transcript as a
permanent negative case. This gives the controls teeth against both count
derivation and output-boundary regressions.

## What holds

- Same-line vector-ID injection is rejected.
- The current 49-vector suite produces and accepts the exact
  `49/49 — 8 deserialize, 33 eval, 8 object` line.
- The historical unchanged-suite `33/33 eval` output is rejected.
- The coverage helper is byte-identical and mirror-checked in both repositories.
- X1 no longer carries a third inline implementation of count derivation.
- Strict X1 passes in both directions with `13/13`, zero skips.
- Negative controls pass with `6` controls from warrant and `5` from
  sigma-glyph, including unknown-kind rejection and helper-mirror deletion.
- All four branch diffs pass `git diff --check`.

The compatible-baseline pin policy remains correctly closed.

No merge, push, release, adoption, or governance action was performed.
