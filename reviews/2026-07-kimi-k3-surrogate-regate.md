# Kimi K3 — re-gate of the lone-surrogate parity fix (2026-07-27)

Reviewer: **Kimi K3** (local CLI, `kimi -m kimi-code/k3`), fresh-eyes adversarial
gate of branch `verifier-hardening-surrogates` — the fix that makes both
implementations reject unpaired UTF-16 surrogate escapes so they share one I-JSON
domain (RFC 7493). Task: build counter-vectors, run BOTH impls, hunt for a
parity break, a byte-scanner bypass, or a crash. READ-ONLY (K3 modified no repo
file; it built fixtures in a temp dir).

## What K3 completed

K3 read both `_reject_lone_surrogates` (Python) and `hasLoneSurrogateEscape` /
`hex4` (Go), reasoned through the byte-scanner's corner cases, then built a ~30
-vector differential harness and ran Python vs Go on each. **Every vector agreed**
(`(1,1,0)` / rc 1 both sides), covering:

- lone high / low, at D800/DBFF/DC00/DFFF boundaries, D7FF/E000 (valid) either side;
- valid surrogate PAIRS (min/max/emoji) accepted with the **same recomputed
  WarrantID** (`ed41398aeb1a` == `ed41398aeb1a`) — not over-rejected;
- byte-scanner bypass attempts: escaped backslash (`\\ud800` literal), triple/
  quadruple backslash, truncated escape at EOF and mid-buffer, mixed/upper/lower
  hex case, high-then-non-`\u`, high-then-bad-hex, split pairs across tokens/keys/
  values, NUL-escape-then-low, reversed low-high;
- surrogate in an actor key, a body key, an `under` array element, a subject hash,
  trust config, pinned `genesis.json`.

The cross-language byte-scanner held on all of them — no bypass, no over-rejection,
no crash on that surface.

## The finding that earned the gate (P1)

Before the harness even ran, K3's **reasoning** flagged a surface the fix did NOT
touch: the policy-blob / canonical-JSON-blob / ski-check-blob paths in Python use
**plain `json.loads`** (not `loads_ijson`) and then call `canon()` **outside** the
guarding `try`. `canon()` raises `UnicodeEncodeError` on a lone surrogate.

Verified directly (Claude, post-run): a record whose `under` references a policy
blob `{"threshold":{"actors":["\ud800evil"],...},"warrant_policy":"0.3"}`:

```
PY  rc 1  counts None   UnicodeEncodeError: 'utf-8' codec can't encode '\ud800'  (CRASH, no summary)
GO  rc 1  (1, 1, 1)     ERR "invalid threshold policy"                            (bounded)
```

A real **P1 parity break / crash** on already-merged code, in the same class as
the original item-0 P1-4 but on a path the escape-rejection fix missed (it lived
only in `loads_ijson`). K3's own differential harness was cut off by the CLI's
10-minute foreground timeout before it reached this vector empirically and before
it printed a final `SURROGATE-GATE:` token — but the reasoning was decisive and
the vector reproduces.

## Fix (Claude, 2026-07-27)

Added `_canon_eq(doc, raw)` — `canon(doc) == raw`, but an un-encodable doc (lone
surrogate) counts as **non-canonical rather than raising**. Applied at the three
plain-`json.loads` + `canon()` sites: `run_ski_check`, `_read_json_blob_if_canonical`,
`_parse_policy_blob`. This matches Go, whose decoder substitutes U+FFFD and then
fails the identical canon comparison — both reach a bounded "not canonical"
outcome. Result on the vector: **byte-identical** `(1,1,1)` rc 1, messages
`['invalid threshold policy', 'unadopted root']` on both sides. Regression vector
added to `case_verifier_hardening_k3`; full settlement + runtime-hook suites green.

## Honesty note

K3 did not print a final verdict token (foreground timeout at 10m, mid-harness).
Its completed work — the ~30-vector byte-scanner sweep (all parity) plus the
policy-blob P1 it reasoned out — is recorded above; raw session log in
`scratchpad/k3_surrogate_run.log`. The escape-rejection surface itself is
confirmed solid; the crash it surfaced was on an adjacent plain-`json.loads` path,
now fixed. A residual to consider for a future pass: whether the plain-`json.loads`
blob paths should route through `loads_ijson` for full domain unification (they now
agree with Go via `_canon_eq`, so this is consistency-hardening, not a live bug).
