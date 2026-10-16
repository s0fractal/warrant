# Deposit manifest — "The Reason Runs Again" (paper v1.1.0)

**Source of record: the annotated git tag below.** This manifest binds the
Zenodo DOI, the paper version, the git tag, the exact commit and the file
hashes. The DOI was reserved before the final build, so it appears inside the
deposited PDF. The commit hash appears here and not in the PDF, because a
document cannot contain the hash of the commit that contains it.

## Binding

| field | value |
|---|---|
| Paper version | **1.1.0** (the paper's own version — NOT a Warrant software or protocol release, NOT a v1.0 adoption of the format) |
| Zenodo DOI | **10.5281/zenodo.23414323** (record 23414323, a new version of 22172098) |
| Previous version | 1.0.0 — 10.5281/zenodo.22172098, tag `paper-the-reason-runs-again-v1.0.0` (`d83984f`) |
| Concept DOI | 10.5281/zenodo.22172097 (resolves to the latest version) |
| Git tag (annotated) | `paper-the-reason-runs-again-v1.1.0` |
| Tag object | `f7ee5f94a698a79c4e097118f130b1ea102b2e7d` |
| Exact commit (tag `^{}`) | `e494dbb84ea68a3d67752d929154b74f7fb415e8` (merge of PR #109) |
| Repository | https://github.com/s0fractal/warrant |
| Paper licence | CC BY 4.0 (code/repository are MIT) |
| Creator | Serhii Glova — ORCID 0009-0001-8010-420X |

## Reproducible build

- `papers/the-reason-runs-again/build.sh` at the tag; toolchain enforced by it: pandoc 3.12.1, tectonic 0.17.0.
- `SOURCE_DATE_EPOCH=1792108800` (2026-10-16) pinned → byte-reproducible.
- Verification: two clean `git archive` exports of the tag, each built with `sh build.sh`, gave the same PDF SHA-256 as below, which also equalled a build made before the merge.
- `check_claims.py --ref e494dbb…` at the tag: 20 countable claims hold and the source identity holds. 1.0.0 still holds at its own commit (`check_claims.py --deposited d83984f…`).

## Artifacts and hashes (SHA-256)

| file | sha256 |
|---|---|
| `the-reason-runs-again.pdf` (real DOI inside) | `8219ca13495ab41483be913c1df518d8b992fca42a66be6aefa450fbfed86497` |
| `warrant-source-v1.1.0-e494dbb.tar.gz` (`git archive --format=tar.gz --prefix=warrant-paper-v1.1.0/` of the tag; deterministic) | `e018a45fd873bcefaa13ad6096a3adf16d850ac88981f005c48df7baad94f29e` |
| `zenodo.json` | `ff48bdb0e4f8d88c14ed2f037e20b50ea6ab231bc696a0f19fec30f3200d202d` |
| `CITATION.cff` | `1e4b06a571eba59fd95609507d0faec1373fdedec15793df60c3e95e533f2d61` |
| `paper-LICENSE.md` | `ac6f23855e57639ce9944222c06db63ac814655e1c0b92b89736071b89418cae` |

`SHA256SUMS` in this bundle repeats these (and this file's own hash) for machine checking.

## What this deposit is not

Not peer reviewed. Authored by a language-model maintainer. Two automated
reviews and one model review of the drafts are kept verbatim, with triage, in
`papers/the-reason-runs-again/reviews/` at the tag. A DOI is a permanent
address for a frozen artifact, not a venue, a review or an endorsement.
