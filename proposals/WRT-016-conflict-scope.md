# WRT-016: Scope a key-state conflict to the fork, not the whole store

**Status:** DECIDED: option C, by the owner, 2026-10-16. Implemented in Python, Go and Rust. A conflict acts only on records whose ancestry contains both sides, and it is reported once per actor on the store. Implementing it also closed a related gap: SPEC said a conflicted actor counts toward no quorum, and no implementation enforced that. Recorded in contract KEY-C1.

## The finding (DeepReview of paper 1.1.0; reproduced)

After `a0 → a1 → a2` under pre-rotation (WRT-015), the holder of the two
**retired** keys `a0` and `a1` can introduce `a1` a second time at the root,
with a different onward commitment. The two rotations that introduce `a1` are
maximal and mutually unordered, so `a@x` is conflicted. SPEC §5.1 makes a
conflict store-wide, and the report then unbinds every `a@x` signature: the
genesis root, and the records signed by the uncompromised current key `a2`.
`tests/r13_retired_key_denial.py::case_multihop_residual` pins it, and Python,
Go and Rust agree.

Pre-rotation raised the bar from one retired key to two consecutive keys. It did
not stop the retroactive reach, because the conflict rule is not local.

## Options

| | Rule | Effect | Cost |
|---|---|---|---|
| A | Keep it store-wide (today) | any duplicity, however old, freezes the actor everywhere until resolved | the denial reaches back over all history |
| B | A conflict affects only records whose ancestry contains **both** conflicting rotations, or a descendant of the fork that the conflict leaves ambiguous; records that see only one side keep the key state their ancestry gives them | the legitimate branch and everything before the fork stay bound | the attacker's own branch is then *consistent at its positions*, i.e. a parallel history is representable, which is the existing "a formerly valid key can sign into an old DAG position" residual, now explicit |
| C | B, plus a verifier WARN on every store that contains a conflict, without unbinding | readers are told that two histories exist | a WARN is easy to ignore |

B and C turn a denial of the whole history into a fork that is visible.
Choosing which side is legitimate is outside the format either way: that needs
an external order (WRT-012).

## What a decision must come with

The rule in all three implementations; `case_multihop_residual` flipped from
"pinned current behaviour" to the chosen outcome; a vector; and the KEY-C1
contract amended with a new decision (its statement changes).
