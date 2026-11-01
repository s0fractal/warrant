# Agents and contributors

This repository keeps work as signed records; its git history and commit trailers are provenance
too. The rules below protect that provenance.

Read first: [docs/AGENT.md](docs/AGENT.md) (the agent interface and its configuration),
[docs/V3.md](docs/V3.md) (the specification) and [docs/REPOSITORY.md](docs/REPOSITORY.md) (this
repository's records, tools, review loop and merge gate).

## Hard rules

1. **Never commit to `master`.** Work on a branch and open a pull request. `master` advances only
   by a merge: the owner's, or the merge gate's (`tools/gate.py`) when the review loop accepted the
   pull request (docs/V3.md §14). A pull request that changes an owner path is merged by the owner.

2. **Never claim review authority you do not hold.** A trailer such as `Reviewed-by: X` or a
   sentence saying "independently reviewed" is false provenance unless X filed that review. A review
   is a record signed by its reviewer: an `attest` or a `finding@1` challenge by a `pr/acceptor` on
   the head version. Sign only as your own actor, with your own key; never as another actor or as a
   checker (`claims-checker`, `review-replayer`), whose seeds only the owner and the waker hold.

3. **An independent review hunts for counterexamples.** Green suites are necessary, not sufficient:
   every real review of this project found defects the suites did not cover. Running the suites is
   not a review.

4. **Record provenance honestly.** Say exactly what was checked (which suites, which mutants, which
   reviewer) and what was not. Do not upgrade "the suites are green" into "reviewed", or "filed" into
   "accepted".

5. **A counterexample is recorded, not staged as red CI.** The test and the fix land in the same
   change, and CI stays green. The regression case names the defect it catches; the commit message
   names the commit it was observed on, what was observed and what was expected. Show that a new
   check can fail by a mutant in `tests/mutants.py` that fails its own case. A change to a rule of
   docs/V3.md files the claim's new version (docs/REPOSITORY.md); earlier records are never
   rewritten.

6. **Act within the owner's delegation; stop at what is missing.** Branch pushes, pull requests and
   records under your own actor need no fresh confirmation (owner, 2026-10-17); seeds and owner-path
   merges are the owner's. Release tags and package publication are delegated (owner, 2026-11-01: decide by
   the mathematics and the mission, not by asking): push `vX` when G12 holds for X — the release duty is
   accepted, the published release admits X (`python -m warrant.differential --release X`) and master CI is
   green on the commit — and let `release.yml` publish; one tag per decision, its evidence in the report.
   Finish everything that does not depend on a missing decision, key
   or credential, then ask for exactly that. Record what remains open as an obligation or a named
   residual rather than asking for blanket permission.

Earlier generations of these rules, and the incident that started them, are at the tags
`history/warrant-2-2026-10-27` and `history/warrant-0.x-2026-10-18` (docs/HISTORY.md).
