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

5. **Act under the owner's standing delegation; close the applicable obligations.**
   Owner instruction, 2026-10-17: routine pushes, merges and releases do not
   require a fresh human confirmation. Properly discharged obligations are the
   basis for proceeding. This rule grants workflow authority to agents working
   within the owner's project scope; a closure record supplies evidence that
   its prerequisites were met, not new authority of its own.

   - **Local work and CI:** make routine design decisions, implement, test,
     commit on branches, push ordinary branch updates and open/update PRs
     autonomously. A push to obtain CI is not a release or governance adoption.
   - **Merge:** proceed through a PR when the exact candidate has satisfied the
     applicable review, counterexample/regression and required CI obligations,
     and no unresolved blocking finding remains in that scope. Identify the
     evidence and the policy that accepts each closure. Recheck the remote head
     and merge normally; never bypass protection or push directly to `master`.
   - **Release:** proceed when the release's applicable obligations are closed:
     reviewed canonical source, required checks, intended version and artifact
     identities, and the publishing identity/provenance required by the target.
     Prepare and check the artifacts, publish once, then read back the public
     version and digests. A failed or missing readback is incomplete publication,
     not a successful closure and not permission to publish duplicates blindly.
   - **Evidence:** signatures, accepted runner attestations, fresh executions
     and deterministic replays are distinct bases. Use the basis admitted by
     the applicable policy; never upgrade one into another. Existing PRs,
     reproducible artifacts and reports may carry this evidence. WRT-021 is a
     draft: do not pretend its checker exists or make an unimplemented format
     a prerequisite for ordinary work.
   - **Scope and stopping:** distinguish findings that block this action from
     unassigned questions and future research. Record residuals. Do not restart
     a settled review without a relevant new reason; after a candidate changes,
     revalidate affected obligations. Do not invent extra gates or ask for
     ceremonial approval once the applicable obligations are satisfied.
   - **Limits:** a generated claim, green CI, a self-declared closure or access
     to a key cannot enlarge this delegation. Governance adoption still needs
     the actual authority/signatures in rule 2. Rewriting shared history,
     weakening protection, or changing the owner's mandate needs a separate
     owner decision. Ask only for a concrete missing decision, authority or
     credential; first finish everything that does not depend on it. Report
     precisely what remains open rather than requesting a blanket permission.

6. **A counterexample is recorded, not staged as red CI.** When a test shows a
   rule broken, the test and the fix land in the same change, and CI stays
   green. The red goes into the record instead: in the rule's contract
   (`contracts/<ID>.json`, a `decisions[]` entry whose `counterexample` names
   the commit it was observed on, the witness, what was observed and what was
   expected), and in the commit message. Show that a new check can fail by
   mutating what it guards and watching it go red. Changing a contracted SPEC
   sentence requires a new decision in its contract; accepted decisions are
   never rewritten (`tools/contract.py`, `CONTRACTS.md`). Method taken from
   sokol-core (ADR-0023/0024).

The retired autonomy-envelope experiment and the lessons preserved from it are
indexed in `history/AUTONOMY-ENVELOPE-0.1-RETIREMENT.md`. Its policy is not an
active source of authority.

## Precedent (why this file exists)

2026-07-27: an assisting agent ran the green suites, committed the WRT-001 /
ADR-008 work **directly to `master`**, and stamped
`Reviewed-by: Antigravity (2-of-3 roster)` / "independent gate passed". It was
neither an independent adversarial gate nor a governance adoption. The commits
(unpushed) were reset and re-recorded honestly on candidate branches; a genuine
adversarial gate (Kimi K3) then returned `AMEND` with 11 reproducible findings the
green suites had missed. This file exists so that does not recur.
