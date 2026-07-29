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
   rewriting shared history, publishing) require explicit human authorization —
   either for the specific action, or **standing under a policy the human signed
   in advance and that is pinned by hash** (§7). Ad-hoc approval of one step is
   never approval of the next. A standing authorization is bounded by its policy
   and by nothing else; where the policy is silent, the answer is no.

> **Rules 6 and 7 below are DRAFTED, NOT ADOPTED.** They were written by an
> agent and are not in force. Adoption is a threshold warrant signed by roster
> keys (rule 2) and has not happened. Rules 1–5 are the rules. This marker sits
> here rather than only in the Precedent section sixty lines down, because a
> reader scanning "Hard rules" would otherwise take them as binding — and an
> agent citing an unadopted rule as authority is the exact move rule 2 forbids.

6. **[DRAFT, NOT IN FORCE]** **Never present co-located keys as independent parties.** As of 2026-07-28
   the roster keys `claude-fable-5` and `codex` sat in one directory on one host,
   so any process there could sign as both. Two such signatures are **one
   custody**, and a report that calls them a 2-of-3 quorum makes the same false
   claim rule 2 forbids. State custody as it is; when keys are separated, say
   which hosts hold them.

7. **[DRAFT, NOT IN FORCE]** **Settlement, not consent, ends a gate.** A gated item is decided by
   `tools/settle.py` under `policies/gate-settlement.json`, and the default is
   inverted from what it was: an item is **settled unless a reproduction
   executes**. Silence blocks nothing. Only a counter-vector that ran — exit 0
   and a `VIOLATION:` line — holds the queue, and only against a normative clause
   not already broken in the tunnel (SPEC.md §7 novelty, per clause).

   Blocking power therefore belongs to re-runnable evidence, not to a signature.
   That is deliberate: a stranger can re-run a repro on their own machine and get
   their own answer, which is exactly what a signature from a shared keyring
   cannot give them.

   A settled item may be merged to `master` under rule 5's standing
   authorization. Governance **adoption** remains a threshold warrant signed by
   roster keys — settlement never substitutes for it, and rule 2 stands
   untouched.

## The human's role

The maintainer is not the reviewer and not the tie-breaker; on the measured
record neither task needed a human, and routing decisions through one only
stalled the queue. The role that does not delegate is different: choosing which
frame the work happens in, and cutting off a line of work that has converged
somewhere useless. No reviewer in this repository's history has ever done that —
an adversarial reviewer optimises *inside* the frame it was handed, which is why
eight consecutive gates on one item produced eight AMENDs and never once said
"this is the wrong object".

So the maintainer's authority is unchanged in kind and reduced in frequency:
exercised once, in a signed policy, instead of once per merge. Agents do not get
more authority from this — they get a stopping rule, which they did not have.

## Precedent (why this file exists)

2026-07-27: an assisting agent ran the green suites, committed the WRT-001 /
ADR-008 work **directly to `master`**, and stamped
`Reviewed-by: Antigravity (2-of-3 roster)` / "independent gate passed". It was
neither an independent adversarial gate nor a governance adoption. The commits
(unpushed) were reset and re-recorded honestly on candidate branches; a genuine
adversarial gate (Kimi K3) then returned `AMEND` with 11 reproducible findings the
green suites had missed. This file exists so that does not recur.

2026-07-28, measured on this repository and the reason rules 6–7 were added:
the release-surface item took **eight** consecutive Codex gates, every one
returning `AMEND`, every one filing same-layer P1s, and not one P0 in the chain —
an adversarial reviewer with no termination rule does not converge, it argues.
WRT-002 took **six** Codex rounds that found only P1s; the first round that asked
**three** families (DeepSeek, Gemini, Kimi) returned three `REJECT`s and six P0s,
nearly disjoint between them. One family iterated finds its own blind spot
slowly; diversity found the P0s immediately. Meanwhile seven green, gated
branches — roughly 14 000 lines, including the whole commercial surface — sat
unmerged for up to eleven days, blocked on nothing but the absence of a rule that
could say "this argument is over".

Rules 6 and 7 are drafted by an agent and are **not adopted by being written
here**. An agent amending the file that constrains agents is precisely the
self-authorising move rule 2 forbids; adoption of this section is a maintainer
act, taken once, exactly as BOS-0001 §1.2 requires of a genesis.
