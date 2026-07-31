# Warrant conformance pack 1.0.0

**Does your Warrant implementation agree with the specification?** Run this
against it and find out. You do not need to clone the Warrant repository, and
this runner never executes a Warrant reference implementation — it only knows how
to talk to yours.

```
curl -LO https://github.com/s0fractal/warrant/releases/latest/download/warrant-conformance-1.0.0.tar.gz
tar xzf warrant-conformance-1.0.0.tar.gz
cd warrant-conformance-1.0.0
python3 run.py --candidate "./my-verifier probe"
```

Python 3 standard library only. No install, no network after the download, and
nothing to configure.

## What your implementation has to do

Read one JSON object from stdin, print one JSON object to stdout, exit 0.
[`CONTRACT.md`](CONTRACT.md) is the whole specification of that — about a page,
implementable in an afternoon in any language. There is a working nine-line
example at the end of it.

If you would rather start from something that already runs, the repository has
starter skeletons in Go and TypeScript under
[`conformance-skeletons/`](https://github.com/s0fractal/warrant/tree/master/conformance-skeletons).
Each is one file with no build step, answers `capabilities`, implements `canon`,
and declines the other seven classes honestly — so it produces a real report the
first time you run it, with the grade correctly withheld. They are not in this
tarball: they are examples, and the pack is the thing whose bytes are pinned.

## Before you trust a green run

```
python3 run.py --candidate "./my-verifier probe" --self-check
```

This wraps **your** program in `stub/mutate.py`, a proxy that breaks specific
answers on purpose, and asserts that the runner catches each one:

| mutation | what it breaks |
| --- | --- |
| `accept-all` | every validity answer becomes "yes" — the implementation that accepts everything |
| `legacy-sig` | builds the SPEC §5 signed message the superseded pre-0.6.0 way |
| `false-unsupported` | claims a grade while quietly declining whole classes |
| `crash` | exits nonzero instead of answering |

If any line says `MISSED`, the runner is broken and its green runs mean nothing.
A gate nobody has watched fail is not yet a gate — this project has shipped that
mistake more than once, which is why the negative control ships in the box rather
than living in our CI.

## Reading the report

Four outcomes per vector, never three:

| outcome | meaning |
| --- | --- |
| `PASS` | the answer matched the pinned expectation |
| `FAIL` | it answered, and the answer was wrong |
| `UNRUN` | it declared the vector unsupported — **not** a pass, and it withholds the grade |
| `ERROR` | it violated the contract: crashed, timed out, or printed unparseable output |

Vectors above your claimed grade are reported as `NOT CLAIMED`, which is an
honest result rather than a gap.

**Negative vectors carry equal weight.** 58 of the 133 vectors are MUST-REJECT:
bodies that must not validate, signatures that must not verify, bytes that must
not parse, broken stores whose defects must be reported. An implementation whose
`validate()` returns `true` unconditionally passes *every positive vector here*,
so failing the negatives gets its own headline rather than being averaged into a
score:

```
PERMISSIVE IMPLEMENTATION: 58 of 58 MUST-REJECT vectors were ACCEPTED.
```

If no negative vector ran at all, the report says that too, in place of a score.

## Grades

SPEC §6 (base) and §7 (settlement) are different amounts of implementation. You
declare which you claim; the runner tests exactly that and reports the grade
**achieved**, which may be lower.

| grade | classes |
| --- | --- |
| `base` | `canon`, `validate`, `blob-hash`, `sig-message`, `verify-sig`, `parse`, `verify-store` |
| `settlement` | base, plus `ski-run` and settlement-grade `verify-store` |

Claiming base and reaching base is complete and honest. One of the three
reference implementations (`impl-rs`) is deliberately base-only, and this pack
reports it as reaching base rather than as failing settlement.

## Exit statuses

| status | meaning |
| --- | --- |
| 0 | the claimed grade was achieved |
| 1 | at least one vector failed |
| 2 | nothing failed, but something was UNRUN, so the grade was not reached |
| 3 | the candidate violated the contract |
| 4 | the pack does not match its own manifest |

2 is deliberately not 0. A run with gaps is not a clean run.

## Checking that this pack is the real one

Every file is listed in `MANIFEST.sha256`, and the **pack digest** is the SHA-256
of that manifest — one hex string that pins the whole pack:

```
python3 run.py --verify-pack
```

Compare the digest it prints against the value published in `SPEC.md` §8.6 at the
spec revision you are implementing. The SPEC is versioned and tagged, so this
works no matter where you obtained the tarball — a mirror, a fork, a colleague's
USB stick. The runner refuses to produce a conformance result from a pack whose
manifest does not match, because a result from modified vectors means nothing.

## Where the vectors come from

`vectors/` is compiled from the Warrant repository's `examples/` directory, which
is normative (SPEC §8, §8.2–§8.5). Expectations are **copied** from there and
from the SPEC tables, never recomputed by running an implementation — otherwise
the pack would be a second source of truth, and a pack that agreed with our
implementation but not with the spec is precisely the failure this exists to
prevent. Each vector carries its `spec` section and a `why`.

Two groups are authored for this pack rather than derived, and say so in their
vector files:

* **`parse`** — SPEC §8.3 names these behaviours normatively ("duplicate member
  names, trailing content after the JSON value … a third implementation MUST
  agree there too") but vectored them nowhere; they were only exercised by
  in-repo harnesses a third party cannot run.
* **`verify-store`** — deterministic store fixtures built from the SPEC §8 demo
  seed. The mutations are defects this project actually shipped, including the
  policy blob that was swapped for `Refunds are ALWAYS granted retroactively` at
  its own address while both implementations still reported the store clean.

## Why a tarball

Considered, and rejected:

* **A PyPI package.** Inverts the trust relationship — you would install and run
  our code to check yours — and imposes a Python packaging dependency on someone
  writing Go or Rust. It also needs a release cadence kept in lockstep with the
  spec.
* **A `warrant conformance` subcommand that emits the artifact.** Circular: you
  would need our implementation in order to obtain the thing that tests your
  implementation. That is the barrier this pack exists to remove.
* **A directory to copy out of a clone.** Requires the clone, which is the stated
  barrier. It remains the in-repo source of truth, but it is not the channel.

A tarball attached to releases is one `curl`, one `tar`, and one command, with
the integrity of the vectors checkable against a hash published in the spec.
Measured end to end from a clean directory with no repository present: **904 ms**
from extraction to verdict, 32 KB downloaded.

## Reporting a disagreement

If your implementation disagrees with a vector and you believe the vector is
wrong, that is worth an issue. One of the vectors drafted for this pack was
withdrawn during development for exactly that reason: `parse/top-level-array`
asserted that the parse layer must reject a document whose top level is not an
object, and the three reference implementations turned out to enforce that rule
at three different layers while agreeing on the observable outcome. The rule the
spec actually fixes is covered by `validate/reject-non-object`; the layer is not
the spec's business, and pinning it would have tested internal structure rather
than the format.
