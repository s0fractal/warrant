# Autonomy envelope 0.1 — retirement record

**Status:** RETIRED  
**Mode:** CONTROLLED_FORGETTING  
**Last trunk revision containing the complete surface:** `4cb3c8f6e1f2bb66524f3ce7df707e725b296781`  
**Unmerged repair candidate:** `12bfe836fd71c5bfbf03b572e693ecfedee84666` ([PR #51](https://github.com/s0fractal/warrant/pull/51))

## What existed

The surface combined a signed standing policy, an advisory evidence collector,
a fail-closed eligibility evaluator and a GitHub write actor intended to merge a
narrow class of documentation-only pull requests.

## Why it left the active surface

No autonomous merge was completed by the actor. Every non-skipped production
run stopped before evaluation because the workflow token could not query the
full branch-protection endpoint. The repair candidate replaced that unreachable
input with the protection summary available from the branch endpoint, but the
larger result remained the same: Warrant carried a repository-operations
experiment of more than two thousand lines that was not part of its record,
signature, replay or settlement contract.

Removing it therefore retires an unrealised capability; it does not narrow any
admitted Warrant format, verifier command, conformance grade or settlement
invariant. Repository merges return to explicit maintainer acts.

## Preserved lessons

- A write-capable actor must bind the exact base, head, policy and required-check
  identities immediately before its write.
- Evidence unavailable to the actor must not be replaced by synthetic local
  fixtures or stronger prose.
- A signed standing authorization grants only the actions and paths its exact
  bytes name.
- `HOLD`, `DENY`, `ELIGIBLE` and an executed merge are different events.

## Removed active paths

- `.github/workflows/autonomy-advisory.yml`
- `.github/workflows/autonomy-merge.yml`
- `docs/agent-autonomy.md`
- `policies/agent-autonomy-v0.1.json`
- `trust/agent-autonomy-authorization.json`
- `trust/maintainer-autonomy-p256.pub`
- `tools/autonomy_{gate,advisory,merge}.py`
- `tools/autonomy_sign.swift`
- `tests/autonomy_{gate,advisory,merge}.py`

The exact bytes remain reachable in Git at the revision above. This record is
an index and loss declaration, not a replacement implementation and not a claim
that the repair candidate was adopted.

## Reactivation condition

Do not restore this surface because a merge bot sounds useful. A successor needs
a concrete repeated workload, an explicit owner for repository operations, and
one end-to-end write specimen before it becomes part of an active repository.
