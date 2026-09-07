# Deposit manifest — "The Reason Runs Again" (paper v1.0.0)

**Source of record: the annotated git tag below.** This manifest binds the
Zenodo DOI, the paper version, the git tag, the exact commit, and the file
hashes. The PDF was rebuilt from a fresh detached checkout of the tag and its
SHA-256 matched the recorded value byte-for-byte.

The DOI `10.5281/zenodo.22172098` was **reserved before the final build**, so it
appears inside the deposited artifact itself. The current publication state of
this record is determined by the Zenodo record itself (deposition 22172098), not
by this file.

## Binding

| field | value |
|---|---|
| Paper version | **1.0.0** (the paper's own version — NOT a Warrant software or protocol release, NOT a v1.0 adoption of the format) |
| Zenodo DOI | **10.5281/zenodo.22172098** |
| Zenodo deposition | 22172098 — https://zenodo.org/deposit/22172098 |
| Git tag (annotated) | `paper-the-reason-runs-again-v1.0.0` |
| Tag object | `220097de5b4e766ca040038614a91ffb734f28e4` |
| Exact commit (tag `^{}`) | `d83984f26207cc79ecefac9e1348f3739e94c8fe` (merge of PR #41) |
| Merge parents | `8c46de91aacd77171c65f22a7999629518b90021` + `fe9c38d8522d136de52806e30e85d45ad9ccf90e` |
| Repository | https://github.com/s0fractal/warrant |
| Sibling dependency | `sigma-glyph@a447a67bd428c085979ce735c1c92a33540c7076` |
| Paper licence | CC BY 4.0 (code/repository are MIT) |
| Creator | Serhii Glova — ORCID 0009-0001-8010-420X |

## Reproducible build

- Toolchain (enforced by `build.sh`): pandoc 3.10.2, tectonic 0.17.0 (python 3.14.7 for the claims checker).
- `SOURCE_DATE_EPOCH=1788048000` pinned → byte-reproducible.
- Verification: a fresh `git worktree` detached at the tag → `sh build.sh` → the PDF SHA-256 equalled the recorded `da2f5506…` exactly.

## Artifacts and hashes (SHA-256)

| file | sha256 |
|---|---|
| `the-reason-runs-again.pdf` (16 pp, real DOI) | `da2f5506e315cb2243eac2700dc7898c2b52930f667963304e0db7904b13a111` |
| `warrant-source-v1.0.0-d83984f.tar.gz` (git archive of the tag) | `50bfdd308d325ee6ac303d1fb853acbcac932bfeb6a4abc3fb3a7db0d00792b8` |
| `zenodo.json` | `a907ad1b73f4302a39a966dd313e93a45abcedd867d5fb8ce3b107b12910ecfb` |
| `CITATION.cff` | `110bcd8ee4484bc41c9e506757bd9846dbfccda85fbf9e8fbd2b83eab850097a` |
| `paper-LICENSE.md` | `ac6f23855e57639ce9944222c06db63ac814655e1c0b92b89736071b89418cae` |

`SHA256SUMS` in this bundle repeats these (and this file's own hash) for machine checking.
