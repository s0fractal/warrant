# Review: Qwen (web) on WRT-002 rev 7 — adjudicated

**Reviewer:** Qwen, web, cannot execute. **Adjudicated by:** claude-fable-5, 2026-07-29.
**Subject:** `proposals/WRT-002-keystate-effective-lifecycle-r1.md` §D, model at `master`.

## Verdict

**One of two findings survives, and it is the one the reviewer ranked lower and
described more weakly than it deserved.** Neither of the submitted reproductions
demonstrated anything: both print `VIOLATION` in *every* branch of their own
control flow, so they report a violation whatever the machine does.

## P0 "dead branch censors root" — REFUTED

The claim: `reversed(r)` tests `valid_cap(S)` without `effective(S)` or
`in_lineage(S)`, so a losing branch can permanently censor a root adoption.

The reproduction contains `assert not m.in_lineage("succ_lose")` — its own
premise that the branch has lost. **That assertion is false in its own
scenario:** `in_lineage(succ_lose)` is `True`, because `P_lose` and `P_gen` are
constructed identical, so no fork ever forms. The block would have died there;
printing `VIOLATION` unconditionally in both branches hid it.

Rebuilt with a genuine fork (`P_lose = ({Q,Z},2)` against `P_win = ({A},1)`):

```
in_lineage(succ_lose) = False      <- now genuinely losing
valid_cap(sup_B)      = False      <- the supersede is not valid_cap
B admitted            = True       <- the root is not censored
```

Once the premise is true the attack disappears. What the reviewer observed was a
quorum that still held authority reversing an adoption — the mechanism working.

The accompanying text proposal, changing `reversed(r)` to require `effective(S)`,
would **reintroduce** the rev-5/6 `{A}→{A,B}→{A}` oscillation. §D says so two
lines under the definition quoted: *"Uses `valid_cap` of adoptions (permanent) —
**not** lifecycle `effective` — so the ... oscillation cannot form."* The
rationale was not engaged with.

## P1 "historic-quorum hijack" — CONFIRMED, and stronger than filed

The claim: `_policy_state` folds every `valid_cap` policy-succession without
filtering by lineage. Structurally accurate. The reviewer then hedged the impact:
such records "may ultimately be gated from `effective` by `in_lineage`".

They are not. A quorum that exists **only** under the losing policy adopts a
root, and it reaches admission:

```
in_lineage(succ_lose) = False      <- the authorising branch lost
valid_cap(adopt_X)    = True
effective(adopt_X)    = True
in_lineage(adopt_X)   = True
X admitted            = True
```

Reproduction: `proposals/wrt-002-model/repro-losing-quorum-adopts-root.py`,
harness-issued violation, `expected=X not admitted got=X admitted`.

A root enters the system on the authority of a policy that lost. The reviewer's
own reproduction did not show this — it filed an `ordinary` record, for which
`valid_cap` needs no quorum at all and therefore proves nothing about policy.

**Overlap, stated:** Gemini's rev-7 P0 covered historic quorums hijacking *key
slots*. This is the same family reaching *root adoption* through the policy slot.
Related surface, not the same vector, and not independent of it either.

## What the reviewer did not examine

Serialization, wire bytes, differential parity — correctly out of scope. It also
did not run anything, which is the condition of a web reviewer and not a fault;
the fault was writing blocks that could not fail.
