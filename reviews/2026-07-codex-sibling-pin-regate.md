# Unified sibling pins — Codex re-gate

**Reviewed exact heads:**

- warrant `chore/unify-sibling-pin` at `7199d4a`, pinning sigma-glyph
  `c5ab2ab218bbeaaf4d80d2e49be2cc7b48fb7f37`;
- sigma-glyph `chore/unify-sibling-pin` at `28938fc`, pinning warrant
  `3972427688730e114507dc6fa14808eff8458fb5`.

**Scope:** closure of the previous pin-gate P1/P2.
**Verdict:** **AMEND**

The compatible-baseline wording closes the previous process finding. The
coverage helper is byte-identical in both branches, derives the expected
`49/49 — 8/33/8` summary from the vector file, and rejects the historical
pre-fix warrant-go output `33/33 eval` on the current suite.

However, both workflows still use the derived text as an unanchored substring:

```sh
warrant-go sigma-conformance "$V" |
  grep -qF "$EXPECT"
```

That does not require the text to be the producer's summary line.

## P1 — A vector ID can satisfy the coverage assertion

`warrant-go sigma-conformance` prints successful vector IDs as:

```text
OK   <vector-id>
```

Vector IDs come from the same suite from which `book1_coverage.py` derives
`EXPECT`. Therefore a vector can carry the expected summary as its ID.

### Executed countervector

Starting from the pinned 49-vector suite:

1. duplicate one valid `eval` vector;
2. set its ID to:

   ```text
   ALL PASS (50/50 — 8 deserialize, 34 eval, 8 object)
   ```

3. run pre-fix warrant-go `2ecbc1d`, which evaluates only `eval` vectors and
   skips `object` and `deserialize`;
4. apply the exact workflow assertion from both candidate branches.

Observed:

```text
expected=ALL PASS (50/50 — 8 deserialize, 34 eval, 8 object)
producer_rc=0
current_workflow_rc=0
exact_summary_rc=1

OK   ALL PASS (50/50 — 8 deserialize, 34 eval, 8 object)
SIGMA CONFORMANCE: ALL PASS (34/34 eval)
```

The producer reproduced the original false-green behavior, but the new pinned
gate accepted it because `grep -qF` found `EXPECT` in an ordinary vector-result
line. This is reachable through valid JSON and a semantically valid vector; it
does not require malformed output or a malicious executable.

### Required closure

Bind the assertion to the complete summary line, including its fixed prefix:

```sh
grep -qxF "SIGMA CONFORMANCE: $EXPECT"
```

and retain `set -o pipefail` so a non-zero producer remains fatal.

Make the countervector permanent. At minimum, the checker test should prove
that all of these are rejected:

- successful `33/33 eval`;
- `OK   $EXPECT` followed by successful `34/34 eval`;
- `FAILURES PRESENT; ... $EXPECT`;

while the one exact full-coverage summary line is accepted.

The current commit messages call the manual old-binary experiment “teeth”, but
no negative control was checked in. A regression of the helper to
`print("ALL PASS")` would leave both workflows green against today's producer.

## P2 — The coverage rule is already three implementations with no parity gate

The same rule currently exists in:

1. warrant `tools/book1_coverage.py`;
2. sigma-glyph `tools/book1_coverage.py`;
3. inline Python in both mirrored copies of `tools/x1_cross_repo.sh`.

The two new files are byte-identical now, but X1's mirror check does not include
them, and the inline implementation already has a different failure domain
(for example, it does not reject an empty vector list or a missing kind the way
the helper does).

This is not a blocker independently of P1, but this coordinated two-repository
landing is the cheapest point to prevent drift:

- add `tools/book1_coverage.py` to X1's mirrored-artifact check;
- have X1 call the helper instead of retaining its third inline implementation.

That leaves two physical mirrored copies, one checked byte-contract, and one
coverage algorithm.

## What holds

- Both pins resolve to the intended post-X1 master commits.
- The old `33/33 eval` summary is rejected on the unchanged 49-vector suite.
- Both helpers derive the correct current `49/49 — 8/33/8` value and are
  byte-identical.
- The new compatible-baseline definition correctly makes ordinary HEAD drift
  non-actionable and eliminates the mutual pin ping-pong.
- Both branch diffs pass `git diff --check`.

No merge, push, release, adoption, or governance action was performed.
