# X1 cross-repo gate — Codex re-gate

**Reviewed:** warrant `feat/x1-cross-repo` at `19f8b10` and sigma-glyph
`feat/x1-cross-repo` at `abcce40`
**Prior verdict:** AMEND at warrant `0402190` / sigma `c852f90`
**Verdict:** **AMEND (P2 only; all P1s closed)**

## Executed

I exported the exact two branch heads into clean temporary trees and ran:

- strict X1 from warrant against sigma: `11 pass / 0 fail / 0 skip`;
- strict X1 from sigma against warrant: `11 pass / 0 fail / 0 skip`;
- warrant-side negative controls: `5/5` at their predicted steps;
- sigma-side negative controls: `4/4` at their predicted steps.

The controls exercised `object`, `eval`, and `deserialize` independently, mirror
deletion, roster drift, ski-check corruption, and an unbuildable warrant Go
tree. The three mirrored X1 files were byte-identical.

## Prior findings

### P1 — Required crossings could SKIP into ALL PASS: CLOSED

Strict mode is now the default. A required crossing that cannot execute becomes
a failure, and the final pass requires both `fail == 0` and `skip == 0`.
Explicit degraded/bootstrap runs with a skip return non-zero and say
`INCOMPLETE`, never `ALL PASS`. CI pins strict/no-bootstrap mode explicitly.

### P1 — A1 did not bind its coverage claim: CLOSED

A1 derives the expected total and per-kind counts from the vector file and
requires the literal producer summary:

```text
ALL PASS (49/49 — 8 deserialize, 33 eval, 8 object)
```

Three distinct controls mutate one load-bearing expected field in each kind.
Each makes A1 fail at A1.

### P1 — Missing mirror was a permanent bypass: CLOSED

Mirror absence is fatal in normal mode. The deletion control removes a sibling
X1 file and makes Section E fail. Bootstrap is explicit, non-default, and cannot
produce `ALL PASS`.

### P2 — B1 discarded process behavior: PARTIALLY CLOSED

Exit status and stderr are now checked and bound to `ok`. One part of the
physical-line contract remains open.

## Remaining finding

### P2 — “One physical line” is checked after whitespace normalization

B1 currently does:

```python
p = subprocess.run(...)
out = p.stdout.strip()
assert out.count("\n") == 0
```

Calling `.strip()` first removes any number of leading and trailing blank
lines. All of these producer outputs pass the asserted one-line check:

```text
{"ok":true}


{"ok":true}



{"ok":true}
```

The JSON parser then sees the same normalized string. Thus the check does not
enforce the stated producer contract (“exactly one physical JSON line, with at
most one trailing newline”).

**Required closure:** inspect raw stdout bytes/text before normalization. Accept
exactly `JSON` or `JSON + "\n"`; reject leading whitespace lines, more than one
trailing newline, and any suffix. Parse only after this framing check.

**Required controls:**

- one JSON line, no newline → accepted;
- one JSON line plus one newline → accepted;
- leading blank line → rejected;
- two trailing newlines → rejected;
- whitespace-only suffix line → rejected.

## Landing choreography note

Strict mirror integrity creates an unavoidable non-atomic rollout seam: while
both master branches lack X1, the first PR clones a sibling master without the
mirror and correctly fails Section E. `X1_BOOTSTRAP=1` labels this
`INCOMPLETE` but deliberately still exits non-zero.

This is not a fail-open verifier defect, but the merge procedure must state the
exception honestly:

1. independently approve both exact branch heads;
2. human-authorize the first merge despite the expected mirror-absence result;
3. merge the second side immediately;
4. rerun X1 on both masters and require strict `0 skip`;
5. only then update pinned sibling commits.

Do not describe either pre-second-merge run as green or complete.

## Scope boundary

This verdict covers only X1 and the Go 49-vector dispatch. It does not review
release-surface, adoption/action packaging, EU profile, pin changes, WRT-002, or
any governance adoption.

No merge, push, release, pin update, or governance action was performed.
