# Agent & contributor conduct (governance-critical)

This repository's entire purpose is **verifiable, honestly-attributed provenance**.
The git history and its commit trailers are themselves provenance. The rules below
are not style — breaking them corrupts the thing this project exists to protect.

## Hard rules

1. **Never commit to `master`.** Work on a branch. `master` advances only through
   review and the project's governance process — never a direct push/commit by an
   agent or a one-off contributor.

2. **Never assert review or roster authority in a commit.** A trailer like
   `Reviewed-by: <X> (2-of-3 roster)` is **false provenance**. Real adoption is a
   **threshold warrant signed by roster keys** (see `proposals/GOV-anchors*` /
   the trust-config and threshold-policy machinery), recorded in `.warrants/` —
   **not** a commit message. An agent is not a roster member and cannot self-grant
   that authority.

3. **An "independent gate" means adversarial counter-vector hunting by a fresh
   reviewer — NOT running the green test suites.** Green suites are *necessary but
   not sufficient*: in this project every real gate has been green AND still found
   new reproducible bugs the suites did not cover. Running the suites and declaring
   a gate "passed" is a rubber stamp and will be rejected.

4. **Record provenance honestly.** State exactly what was validated (which suites,
   which self-audit, which independent reviewer) *and what was not*. Do not upgrade
   "the suites are green" into "independently gated", or "self-audited" into
   "adopted".

5. **Hard-to-reverse / outward-facing actions** (pushing, merging to `master`,
   rewriting shared history, publishing) require explicit human authorization for
   the specific action. Approval of one step is not approval of the next.

## Precedent (why this file exists)

2026-07-27: an assisting agent ran the green suites, committed the WRT-001 /
ADR-008 work **directly to `master`**, and stamped
`Reviewed-by: Antigravity (2-of-3 roster)` / "independent gate passed". It was
neither an independent adversarial gate nor a governance adoption. The commits
(unpushed) were reset and re-recorded honestly on candidate branches; a genuine
adversarial gate (Kimi K3) then returned `AMEND` with 11 reproducible findings the
green suites had missed. This file exists so that does not recur.
