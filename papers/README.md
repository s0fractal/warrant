# Papers

Write-ups about this repository, following the discipline of
`sigma-glyph/papers/`: source in `paper.md`, bibliography in
`references.bib`, a recorded `build.sh`, and a claims checker that recounts
the countable numbers it lists from the repository itself — run before every
build, red on any drift, and printing the claim classes it does *not* check
(harness-run measurements, external citation status) rather than implying it
covers everything.

| | words | subject |
|---|---|---|
| [`the-reason-runs-again/`](the-reason-runs-again/) | 14 645 | the format: content-addressed decision records, domain-separated signatures, re-executable reasons, settlement — and the measured record of what the conformance apparatus caught |
| [`what-remains-open/`](what-remains-open/) | 8 100 | **working draft 0.3, not deposited**: the follow-on work on the three links the flagship leaves open (policy binding, typed assessment, resumable computation), evidence bases, and the WRT-021 open-loop draft; written for review of the vision, with every claim labelled IMPLEMENTED / DRAFT / VISION |

The flagship paper is **deposited**: Zenodo DOI
[`10.5281/zenodo.22172098`](https://doi.org/10.5281/zenodo.22172098)
(**paper version 1.0.0**, published 2026-08-30 from commit `d83984f`; concept
DOI `10.5281/zenodo.22172097`). The paper version is the paper's own, distinct
from any Warrant software or protocol version; the deposit is not a v1.0
software release or a governance adoption of the format. A DOI buys a permanent
address and a frozen artifact — no venue, no peer review, no endorsement. The
deposited `MANIFEST.md` binds DOI, version, tag, commit and file hashes, and is
kept under `the-reason-runs-again/deposited/`; `check_claims.py --deposited
d83984f` holds that version's own text to the commit it names.

**Version 1.1.0 is published** (2026-10-16): DOI
[`10.5281/zenodo.23414323`](https://doi.org/10.5281/zenodo.23414323), tag
`paper-the-reason-runs-again-v1.1.0` = `e494dbb`. It follows two automated
reviews and one model review of the drafts, kept verbatim with triage in
`the-reason-runs-again/reviews/`. `check_claims.py --ref e494dbb` holds the
text in the tree to that commit; the word count above is 1.1.0's.

Candidate companions, mined from material already in this repository (each
listed here so the flagship paper does not silently absorb their scope):

- **the audit experience report** — the full review ledger (92 documents at
  version 1.0.0 of the flagship; 24 in the current tree after the July corpus
  was archived, with every byte kept in git history), the taxonomy of what the
  vendors' models found and missed, negative-control calibration; companion
  to sigma-glyph's *Twenty-One Ways Past a Proof Guard*.
- **settlement semantics** — tunnels, foreclosure, novelty fingerprints,
  multi-root adoption (`SPEC.md` §7/§9, `proposals/GOV-001`).
- **the expiring delegate** — key state, thresholds, and model actors with
  vendor-scheduled end-of-life (`MODEL-ACTORS.md`, WRT-002).
- **EU AI Act Article 12 engineering** — `profiles/eu-ai-act-article-12.md`,
  the CEN/CENELEC JTC 21 contribution, the Air Canada demo.

## Not anchored

Papers are not normative. Editing one is an ordinary commit, not a release
act; the claims checker is what keeps an ordinary commit honest.
