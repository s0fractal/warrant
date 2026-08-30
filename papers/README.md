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
| [`the-reason-runs-again/`](the-reason-runs-again/) | 9 659 | the format: content-addressed decision records, domain-separated signatures, re-executable reasons, settlement — and the measured record of what the conformance apparatus caught |

None is deposited yet. A DOI, when one exists, buys a permanent address and a
frozen artifact — no venue, no peer review, no endorsement — and each
paper's README will say which commit it froze.

Candidate companions, mined from material already in this repository (each
listed here so the flagship paper does not silently absorb their scope):

- **the audit experience report** — the full review ledger (92 documents at
  this writing — 70 inbound and 22 responses, of which one inbound review is
  unattributed and carries no vendor label — and growing), the taxonomy of what
  six vendors' models found and missed, negative-control calibration; companion
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
