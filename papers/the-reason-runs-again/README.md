# The Reason Runs Again

The flagship write-up of this repository: the Warrant record format —
content-addressed identity, domain-separated signatures, re-executable
reasons, settlement, and the conformance apparatus — together with what
building it broke and what it still does not provide.

**Deposit status: published.** Zenodo DOI
[`10.5281/zenodo.22172098`](https://doi.org/10.5281/zenodo.22172098) (record
22172098, concept DOI
[`10.5281/zenodo.22172097`](https://doi.org/10.5281/zenodo.22172097)),
**paper version 1.0.0**, CC BY 4.0, published 2026-08-30 from annotated tag
`paper-the-reason-runs-again-v1.0.0` = commit
[`d83984f`](https://github.com/s0fractal/warrant/tree/d83984f26207cc79ecefac9e1348f3739e94c8fe).
The paper version is the paper's own, distinct from any Warrant software or
protocol version — the deposit is **not** a v1.0 software release or a
governance adoption of the format. It has had no peer review, and nothing here
should be cited as carrying more than that.

| | |
| --- | --- |
| source | [`paper.md`](paper.md), bibliography in [`references.bib`](references.bib) |
| build | [`build.sh`](build.sh) — pandoc 3.10.2 with `--citeproc`, tectonic 0.17.0 |
| claims | [`check_claims.py`](check_claims.py) — recounts every countable number in the paper from the repository; `build.sh` runs it first and refuses to build on a mismatch |
| licence | CC BY 4.0 for the paper (see [`LICENSE.md`](LICENSE.md)); the code it documents stays MIT |

## The numbers are enforced, with a boundary

`check_claims.py` reads each countable claim **out of the paper** (a checker
holding its own copy of the answer only proves its two copies agree) and
recomputes it: conformance-pack vector totals, the canonicalization and
negative batteries, signature-vector counts, the review-ledger census and its
vendor mapping, the default re-execution budget. It also prints what it does
*not* check and why — harness-run measurements belong to `tools/check.py`,
and prose is not countable. The vendor mapping (which reviewer label belongs
to which model vendor) is a judgment; it lives in the checker where it can be
disputed, not in the paper as a bare assertion.

## What was deposited, and how to check it

Seven files, bound by the deposited [`MANIFEST.md`](deposited/MANIFEST.md) and
[`SHA256SUMS`](deposited/SHA256SUMS) — both kept here as downloaded from the
record on 2026-09-07 and verified against Zenodo's own checksums:

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `the-reason-runs-again.pdf` (16 pp) | 142823 | `da2f5506e315cb2243eac2700dc7898c2b52930f667963304e0db7904b13a111` |
| `warrant-source-v1.0.0-d83984f.tar.gz` | 1334994 | `50bfdd308d325ee6ac303d1fb853acbcac932bfeb6a4abc3fb3a7db0d00792b8` |
| `MANIFEST.md`, `SHA256SUMS`, `zenodo.json`, `CITATION.cff`, `paper-LICENSE.md` | | as listed in `SHA256SUMS` |

**Both binaries reproduce from the tag, byte for byte.** `paper.md`,
`references.bib` and `build.sh` on `master` are identical to `d83984f`. With
`SOURCE_DATE_EPOCH=1788048000` (which `build.sh` pins) the PDF rebuilds to the
digest above; the tarball is
`git archive --format=tar.gz --prefix=warrant-paper-v1.0.0/ paper-the-reason-runs-again-v1.0.0`.
Re-verified on 2026-09-07 with tectonic 0.17.0 and pandoc 3.11 — one minor
version past the 3.10.2 that `build.sh` enforces — which is a second successful
reproduction, not a loosening of the pin. Because the bytes reproduce, neither
binary is tracked here; the tracked artifacts are the source, the manifest and
the sums.

**The numbers are frozen with the commit, not with the tree.**
`check_claims.py --ref d83984f…` runs in `tools/check.py` and holds two things,
no more: (1) the countable claims it lists — 19 numbers, four classes stated
as unchecked — recounted against the deposited commit's tree, and (2) the
**source identity** of `paper.md`, `references.bib` and `build.sh`, which must
be byte-identical to their copies at that commit. It does not judge prose.
The identity check is what makes "edited past the deposited commit" a
failure: without it a retitled paper passed the census (Codex, PR #62
review), and the `--selftest` in CI proves both refusals fire on mutated
copies. Against the working tree the count check is red, correctly — the
review census the paper reports (92 documents) became 22 when the July corpus
was retired on 2026-09-07, and the conformance pack has grown by one vector. A
frozen paper describing a named commit is not wrong when the tree moves on. A
future version is a new deposit under the same concept DOI, with its own
commit, tag, manifest and `--ref`.

## Standing

Written by a language model working as maintainer on this stack
(`MODEL-ACTORS.md`). Every number is measured from committed refs; the
limitations section (§8) restates the threat model's scoped assumptions
rather than softening them. What none of that supplies is independent
review — §8 says so about the format, and it applies to this paper in full.
