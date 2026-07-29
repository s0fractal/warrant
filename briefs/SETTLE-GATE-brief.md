# Brief — adversarial gate on `tools/settle.py`

## What you are being asked to break

`settle.py` decides when an adversarial review of an item has **ended**, so that a
branch may be merged. It was written because this repository measured, on
2026-07-28, that a reviewer with no termination rule never terminates: one item
took eight consecutive gates from a single model family, every one returning
`AMEND` with same-layer P1s, while seven green branches sat unmerged behind it.

Note who wrote it: the tool was written by Claude, in the same session that
diagnosed the problem it claims to solve, and it is the tool that will later
authorise merges. **A self-serving defect is exactly what this gate is for.** Do
not be polite about it.

## The claim under test

> An item is SETTLED unless a reproduction *executed* against the current subject
> and broke a normative clause not already broken in the tunnel.

Three sub-claims carry it, and each is a target:

1. **Executed evidence decides, signatures do not.** A finding that did not run is
   a Question with zero blocking power. This is deliberate — the roster's keys
   were co-located on one host, so a signature proves custody, not independence,
   while a reproduction can be re-run by a stranger.
2. **Novelty is per normative clause, not per transcript.** `SPEC.md §7` warns
   that syntactic novelty is unbounded and delegates relevance to the active
   policy. Without a clause rule a reviewer perturbs the repro bytes and
   manufactures unlimited "new" findings.
3. **A fix must be demonstrated, never assumed.** A claim reproduced against an
   earlier revision and never re-run against the current one must report
   `UNRESOLVED`, not silently age out of the tunnel.

## The failure that matters

**A wrong `SETTLED`.** Everything else is noise by comparison: a false `BLOCKED`
costs a round; a false `SETTLED` merges an unclosed defect while claiming a gate
covered it — the exact "green gate covering less than it claims" failure this
repository keeps finding in itself.

So the highest-value counter-vector is any ledger set that makes `settle()` return
`SETTLED` while a real, reproduced, unfixed defect exists. Second-highest: any way
to make a genuine blocker read as `UNRESOLVED`, or vanish.

## Places I would look if I were you

These are my own suspicions, offered so you do not spend rounds rediscovering
them. Finding something *not* on this list is worth more.

- `current` is chosen as `max(produced_at)` over ledgers. `produced_at` is a
  string written by the harness. What does a skewed, forged, or equal timestamp do
  to which subject counts as current — and to findings that were real?
- `claim_key` lowercases free-text clause strings. What do `D.3`, `d.3 `, `D.3.`
  and a same-numbered clause from a different document do to each other? Collision
  merges two defects into one claim; divergence splits one defect into two.
- A finding with no clause becomes `unclassified:<id>`. Ids are reviewer-chosen.
- `outcome_fingerprint` dedupes byte-identical outcomes before the restatement
  check. Consider two findings that differ only in a field the fingerprint does
  not cover.
- `min_families` counts distinct `family` strings on the current subject. The
  string is a command-line flag.
- Severity is taken as `max()` over a list of strings — read that literally.

## Known and accepted, so do not spend a round on it

**Ledgers are unsigned JSON files.** Anyone who can write `reviews/ledgers/` can
forge a settlement. The trust boundary is whoever runs the harness; this tool
does not close it and does not claim to. If you can show a way the *harness
itself* mints a false ledger from a well-behaved reviewer, that is in scope and
serious.

## What the sources are

You are given `settle.py`, the policy it runs under, and its test suite. The
suite passes; saying so is a rubber stamp and will be rejected (AGENTS.md §3).
The tests are also a target: a test that asserts the wrong thing is worse than a
missing test, because it certifies the defect.

`import settle` works from the model directory. `settle.settle(item, policy,
ledger_dir)` is directly callable — build ledger JSON files in a temp directory
and drive it. `policy` is a plain dict; load the shipped one or write your own to
show a policy that should be rejected and is not.
