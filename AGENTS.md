# Agents and contributors

This repository keeps work as signed records; its git history and commit trailers are provenance
too. The rules below protect that provenance.

Read first: [docs/AGENT.md](docs/AGENT.md) (the agent interface and its configuration),
[docs/V3.md](docs/V3.md) (the specification) and [docs/REPOSITORY.md](docs/REPOSITORY.md) (this
repository's records, tools, review loop and merge gate).

## Hard rules

1. **Never commit to `master`, and never merge under another's name.** Work on a branch and open a pull request.
   `master` advances only by a merge of the merge gate (`tools/gate.py`, the workflow's bot), or by the owner's own
   merge of a change to an owner path (`.github/`, `.warrant/merge.json`: the brake itself). Agents do not run
   `gh pr merge`: under this machine's GitHub login that merge is recorded as the owner's act. They file the review
   lineage and the gate merges (docs/V3.md §14, `.warrant/merge.json`):
   - an accepted change to no listed path: at once;
   - an unaccepted one whose author holds `pr/acceptor` (`solo`): once its window (4 h) has passed since the checks
     completed, with no finding and no veto;
   - a change to a watched path (the core modules): two families after 24 h, or one family after 72 h (`solo_ready`);
   - a change to a constitutional path (these rules, `.warrant/v3.json`, `.warrant/v3/`, the gate): two families after
     72 h, or one family after 7 days; when such a window opens the gate comments once, naming the owner.
   The owner vetoes with the `hold` label or a challenge on the head version (`pr/owner`, `challenger`). His word
   can lower reliance, never raise it: he holds no role that accepts. A merge the gate cannot make (its own defect) is
   an open point to report, not a reason to merge by hand.

2. **Never claim review authority you do not hold.** A trailer such as `Reviewed-by: X` or a
   sentence saying "independently reviewed" is false provenance unless X filed that review. A review
   is a record signed by its reviewer: an `attest` or a `finding@1` challenge by a `pr/acceptor` on
   the head version. Sign only as your own actor, with your own key; never as another actor or as a
   checker (`claims-checker`, `review-replayer`): the claims checker's seed lives on a GitHub runner (the
   environment `claims`, deployable from `master` alone; `.github/workflows/claims-key.yml`), the replayer's with the
   waker. A key the owner held stays bound beside it, so that earlier acceptances keep their authenticity.

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

## What stays the owner's

The owner is an observer with a brake (2026-11-13): nothing waits for his signature, and he can stop anything.
These acts remain his and no agent performs or prepares them as his: the license and the CLA; DOI deposits;
letters, applications and messages in his name; spending money; GitHub security settings, branch protection,
environments and secrets; the owner paths (`.github/`, `.warrant/merge.json`). An agent that needs one records it as
an open point addressed to him, with the exact command, and blocks nothing else on it.

Earlier generations of these rules, and the incident that started them, are at the tags
`history/warrant-2-2026-10-27` and `history/warrant-0.x-2026-10-18` (docs/HISTORY.md).
