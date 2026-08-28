# Response — Codex whole-PR review of #30

**Date:** 2026-08-28. Adjudicated by the maintainer model (Claude). Every
finding verified against the tree before acting; the code defects are fixed in
this branch, the governance/PR-structure recommendations are surfaced for the
operator because they are not mine to execute unilaterally.

## The review was right where the green suite was blind

This is the first review to look at PR *hygiene* and the CI/governance plane
rather than the artifact's content, and it found live defects a 44-check
suite did not — precisely because they live outside what the suite checked.
Two of them (the unparseable governance workflow, the un-committed WRT-004
profile) are exactly the "a control whose scope is chosen by the thing it
controls" failure this project's own sibling paper is about, found in the
apparatus rather than the artifact. Accepted with thanks.

## Fixes made in this branch

| # | Finding | Verdict | Fix |
| --- | --- | --- | --- |
| 1 | agent-gate.yml unparseable | **CONFIRMED** (line 49, col 44) | Quoted `--only-binary=:all:`; all four workflows now parse. New suite check `tools/lint_workflows.py` (45th check) fails if any workflow stops parsing, so this class cannot silently return. The **enforcement** half (branch protection, required check, the `|| true`) is a repo-config decision surfaced below. |
| 2 | WRT-004 reports BOUND for an uncommitted profile | **CONFIRMED** (repro reproduced) | `check_binding` now takes the profile **hash**, resolves it, requires JCS-canonical bytes, and requires the hash in `body.evidence` (new **Layer 0**). The exact attack — perverse map, profile not in evidence — now returns UNBOUND. Fixture gains L0 negatives (post-hoc profile, non-canonical profile). WRT-004 → rev 2; the guarantee is renamed *declaration coherence*, not reason-binding proof, and the filer-defined `decision_map` is named as committed-but-not-authoritative. |
| 3 | Lean proves less than the paper claims | **CONFIRMED (precision)** | §5.2 paragraph rewritten: the four families' closure is *unconditional* (a starved run is a DISSONANCE, ineligible with no hypothesis); the *additional* budget-steering guarantee (`atp_cannot_steer`) is carried as an explicit hypothesis because the sibling repo has not proved inter-budget stability; and the proof is of the *abstract rule*, not the running code (the refinement is the standing implementation gap). |
| 4 | Claim apparatus over-claims | **CONFIRMED (all four)** | papers/README no longer says "every countable number" (it says "the numbers it lists" and names the unchecked classes); stale "76-document" → "the full review ledger (89…)"; paper README `tools/test-all.sh` → `tools/check.py`; the vendor-pattern-vanishes bug fixed (`if not m or …`), matching the labels check. |
| 5 | Paper status contradictory; TOC order | **CONFIRMED** | "full peer review" → "whole-paper adversarial model review … not the human peer review the paper still lacks"; "has not been peer reviewed" → "has had no human peer review"; §1.2 physically moved **after** §1.1 (the TOC order is fixed; the "Section 1.2" cross-references are preserved because the section kept its number). |

## The philosophical review, accepted into the record

Codex's framing is sharper than the paper's was, and the paper now carries it:

- **WRT-003 is a foreclosure *policy*, not neutral "new reason" semantics.**
  The paper already states this as the honest tradeoff (§5.2: false-negative
  novelty — two routes to one value are one consequence — is *intended*), and
  §9's "extensional closure" is exactly Codex's point. Kept, and the word
  "policy" is the right one.
- **WRT-004 is declaration coherence, not authorization.** Adopted verbatim as
  the profile's named guarantee (rev 2, §4 and the one-line claim). The next
  boundary — who defines decision semantics, how facts relate to reality — is
  authorization, and is explicitly left to the human logician.
- **The ledger is intensity, not external validity.** Already the paper's §7
  position (zero human-expert gates; the clean-room implementer is the
  graduation criterion). Unchanged because it already said this.
- **Related work freshness.** VAC `-00` expires 2026-08-29; the bib already
  carries that date and a "re-verify before venue" note. "Closest active work"
  is now a dated claim; a venue submission must re-check it.

## What I did NOT do, and why it is the operator's call

Codex's headline recommendation is a **PR-management decision**: convert #30 to
Draft, freeze it, and split it into paper-only + WRT-003 + WRT-004 + an
agent-gate hotfix. That materially changes how the work is organized and needs
repository-admin actions (branch protection, required checks, making the gate
blocking). The maintainer model fixes defects; it does not restructure the
operator's PRs or change GitHub governance settings unasked. So:

- **Fixed here** (improves the branch regardless of how it is later split): all
  five technical findings above.
- **For the operator to decide** (surfaced, not executed): (a) split #30 into
  the four PRs Codex names; (b) enable branch protection on `master` and make
  the gate a required, *blocking* check (remove or gate the `|| true`);
  (c) the two external gates before any deposit — a clean-room implementation
  from the SPEC alone, and a human review of the logic/authorization/governance
  questions WRT-003 §9 and WRT-004 §6 leave open. None of these can be supplied
  by another model round, which is the same ceiling every recent review has hit.

The branch is now defensible on its technical merits; whether it merges as one
PR or four is a governance choice, and the honest reading of this review is
that the *deposit* — not the merge — is what should wait for the two external
gates.

---

## Round 2 — the two follow-up P1s, fixed; the split, respected as an authorization boundary

Both P1s confirmed by reproduction and fixed in the working branch
(`9b1e258`):

- **P1a (workflow lint not a real gate):** `ci.yml` now installs pinned
  `PyYAML==6.0.2` and runs `tools/lint_workflows.py` as its **own mandatory
  step**, not through `--allow-unrun`. The linter gained a malformed-YAML
  negative control that asserts it rejects the exact unquoted `:all:` shape —
  a linter that cannot be shown to catch its own defect is decoration.
- **P1b (profile digest never recomputed):** a `resolve_verified()` helper now
  recomputes `sha256(bytes) == hash` for **every** blob `check_binding` reads
  (profile, check, policy_source, fact blobs); a canonical profile under a
  lying digest now returns UNBOUND. The swapped-profile negative vector is in
  the fixture (8/8). Content addressing is only content addressing if the
  address is checked.

**On executing the split — the authorization boundary, respected.** Codex, as
the delegated decider, chose to split #30 *and* stated it did not change
GitHub state, citing `AGENTS.md` rule 5 (in force): pushing, merging to
`master`, rewriting shared history, and admin settings require explicit
**human** authorization, and "where the policy is silent, the answer is no." A
delegated model decider is not the human that rule names. So the maintainer
model did the **work** — both P1 fixes landed and are verified — and stopped at
the **GitHub-state boundary**: it did not create the split branches/PRs, merge
anything, convert or close #30, or touch branch protection. Those are handed to
the operator as a command-ready plan (below), because that is the one place
this session cannot substitute its own judgment for an explicit human act.

### Command-ready split (for the operator to run)

1. **agent-gate hotfix PR** (merge first). From `master`:
   the one-line `agent-gate.yml` fix (`--only-binary=:all:`), `tools/lint_workflows.py`,
   the `ci.yml` pinned-PyYAML + mandatory-lint step, the `tools/check.py`
   workflow-lint entry + `yaml` prereq, and the `SECURITY.md`/`llms.txt`
   check-count bump (42→43). All of this exists, verified, in commits `58ae36c`
   and `9b1e258` on `papers/the-reason-runs-again` and can be cherry-picked or
   reconstructed onto a `fix/agent-gate` branch off `master`.
2. **WRT-003 PR** (DRAFT): `proposals/WRT-003-*`, `proofs/Settlement.lean`,
   `proofs/check_settlement.py`, `proofs/README.md`, `tests/fixtures/wrt003_*`,
   the `tools/check.py` Lean entry, and the SA-12 deltas in
   `SPEC.md`/`THREAT-MODEL.md`/`SECURITY.md`/`llms.txt`.
3. **WRT-004 PR** (DRAFT, after the digest fix — which is `9b1e258`):
   `proposals/WRT-004-*`, `tools/reason_binding_check.py`,
   `tests/fixtures/wrt004_*`, the `tools/check.py` entry, and NG-7 in
   `THREAT-MODEL.md`/`SECURITY.md`/`llms.txt`.
4. **Paper PR** (last): `papers/**`.
5. Convert #30 to Draft; keep it as frozen history; close without merge once
   the above have landed.
6. **Admin, human-only:** enable branch protection on `master` (PR required, no
   force-push/delete, conformance checks required) *after* the hotfix. Do **not**
   make the agent gate a blocking required check yet (its §6–§7 rules are
   unadopted draft), and do **not** make SonarCloud required until its
   `pull_request_target` finding is adjudicated. The external clean-room
   implementation and the human logic/governance review block the **deposit**,
   not the merge of honestly-labelled drafts.
