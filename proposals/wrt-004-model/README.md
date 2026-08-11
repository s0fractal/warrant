# WRT-004 model — retained after the direction was **closed**

**`warrant.verify-report@v1` was killed as a contract by its own stopping
rule.** See `proposals/WRT-004-verify-report-v1.md`. This directory is kept
for the record of *how* it failed, not as a candidate.

**Do not read the code below as a specification.** It is wrong in ways the
closure documents: `seal()` discards the bytes it hashes, so a judgement
could not have been derived from it without re-reading the filesystem; an
`unreadable` entry carries no digest, so changing that file's contents does
not move `input_root`; and symlinked store roots and trust configs are
handled inconsistently between the two implementations.

The gate and the mutation runner still run, and `mutate.py` gained a
**pristine preflight** during the closure — without it, a broken baseline
made every mutant "die" and the suite reported 14/14 with exit 0 over a run
that was never green. That fix is hygiene on a retained artifact, not an
attempt to continue the direction: leaving a tool that reports success over
a broken baseline would be leaving a trap.

They are **not in CI**, deliberately. A green check for a closed direction
implies life it does not have.

---

## What it covers, and what it does not

**Covers:** `input_manifest` and `input_root` — the part of the design whose
central claim is decidable today, that two independent implementations agree
on **bytes**.

**Does not cover:** the judgement half of `@v1`. That needs the closed
issue-code registry WRT-004 §7 leaves open, and shipping it with an
"extension point" there is precisely what sank WRT-003 — two valid reports
over identical inputs hashing differently. The gate says so in its own output
rather than letting a green line imply more than it checked.

## Why the Go is not a translation

`input_manifest.go` was written from the proposal text, not ported from
`input_manifest.py`. A port proves the porter agreed with themselves. Two
implementations from one specification is the only arrangement in which
disagreement is evidence about the *specification*.

It found one immediately: Go's `encoding/json` escapes `<`, `>` and `&`
unless told not to, so a store containing `blobs/a<b>c&d` produces different
manifest bytes in the two languages for the same files. That is in the corpus
because a corpus of well-behaved ASCII stores would have passed on day one
and proved nothing.

## Round 1 was refuted; this is round 2

The exact-SHA re-gate refuted round 1 on three counts, all mine:

1. **The manifest did not commit the bytes the judgement used.** A live
   verifier follows a symlinked record; round 1's walk skipped symlinks
   silently, so `input_root` was `[]` over a store whose report judged one
   record. The manifest and the judgement were two separate producers, and
   they diverged on the first adversarial input. `seal()` is now one
   observation both derive from.
2. **"Attempted but unreadable" was unrepresentable** — `sha256` was
   mandatory and there are no bytes after a failed read. The Python did not
   merely mis-model it; it crashed with a traceback. `state` is a sum type
   now.
3. **Go escaped U+2028**, which SPEC §4 forbids outright, and this repository
   already ships 47 machine-readable escaping vectors (§8.4) that decide it.
   I argued about escaping in prose while the normative battery sat unrun.
   Both encoders are written out now, and the battery runs in the gate.

## Result

The gate passes, and `mutate.py` kills **14/14** mutants — including one for
each of the three refutations above, so a regression to round 1's behaviour
fails loudly.

`mutate.py` exists because round 1 asserted "9/9 mutations fail" in a table
**with no runner in the repository**. That is a claim a reader cannot check,
and the reviewer was right to refuse it. Two rules make it an artifact: a
**missing anchor is a failure, not a skip**, so the suite cannot rot as the
code moves; and a mutation that leaves the file byte-identical fails too,
because one round-1 mutant "passed" while editing a docstring.

Both the gate and the mutants run in CI. Round 1's ran nowhere, so a green
`conformance` said nothing about WRT-004 at all.

One mutant survived the first executable run — *"Go uses uppercase hex"* —
because the corpus used U+0001, whose escape `\u0001` has no hex letter and
renders identically in either case. The corpus now uses U+001F. The mutation
runner found a hole in the corpus on its first outing, which is the argument
for having one.


The mutant list is `mutants.json` and the count comes from the runner, not
from this file. A table of mutations in prose is the same rot as any other
prose copy — and the previous revision of this README carried exactly that,
still claiming 9/9 four paragraphs below its own account of why the claim was
refused.

**Three findings in round 1 were in the gate rather than the
implementations**, and are kept here because a harness wrong in the *safe*
direction is the failure mode this repository keeps meeting: a root check
comparing `bytes` to a hexdigest `str` (vacuously false against correct
code); a mutation sequence comparing each root against every previously seen
one while the sequence ends by undoing its own addition; and a mutant that
edited a docstring rather than the code path.

## Not covered by the corpus, stated rather than assumed

Symlinks and unreadable files cannot live in a JSON fixture — they are
filesystem states. They are materialized directly by the gate instead, which
is how they became permanent vectors rather than a note.
