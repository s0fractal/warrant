# WRT-017: Revocation is specified and implemented nowhere

**Status:** DRAFT, for an owner decision. Not in force.

## The finding (DeepReview of paper 1.1.0; reproduced)

SPEC §5.1 specifies: "Revocation is a warrant: a `supersede` of the rotation
warrant that introduced the key, authorized under the same current-policy
rule." No implementation derives key state from it. Python, Go and Rust treat
such a `supersede` as an ordinary record, and the key it "revokes" stays bound.
`tests/r13_retired_key_denial.py::case_revocation_not_implemented` pins this.
The review also asked what authorizes a revocation, at which position, and what
key state follows it. The specification does not say.

## Options

| | Rule | Cost |
|---|---|---|
| A | Drop revocation from §5.1; retiring a key means rotating away from it (pre-rotation makes that the safe path) | an actor whose committed successor is lost cannot retire its current key without becoming terminal |
| B | Specify and implement revocation fully. It needs to say who authorizes it (under pre-rotation, plausibly the committed successor's holder), at which position it takes effect, what key state follows (none, so the actor becomes terminal, or the committed successor), and how it interacts with WRT-016 | a second key-state operation in three implementations, with its own attack surface |

Option A is honest about what exists today. Option B is what the text promised.
Either is better than a specified operation that silently does nothing.
