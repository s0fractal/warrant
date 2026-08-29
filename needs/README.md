# Needs — useful validation this repository does not yet have

A **need** records validation that would materially improve the project but is
**not yet available**. Recording it is the opposite of pretending it is met.
It does not become a release, merge, adoption, or status gate merely by being
listed here; only a separately adopted policy can give it that force.

**Status of this surface (2026-08-29): maintainer-accepted, non-normative
planning.** It was initially added by an agent outside the enumerated scope of
a correction pass and was therefore not accepted by that commit alone. The
maintainer has since explicitly accepted the AI-reviewed / human-authorized
operating model reflected here. That acceptance does not manufacture evidence:
the human review and clean-room implementation below still have not happened.

A need is not a defect and is not a blocker unless an adopted policy says so.
Its absence limits only the claims that depend on it. In particular, these
needs do not block review or merge of an honestly-labelled design draft, and
NEED-001 is not required for WRT-005 adoption under the maintainer's chosen
AI-review trust boundary.

## Standing needs

### NEED-001 — optional external human logic / governance review

The settlement outcome-fingerprint design
(`proposals/WRT-005-outcome-fingerprint-purity.md`) survived four adversarial
model-gate rounds and has its rule-algebra and §7 admissibility mechanized in
Lean (`proofs/`). What it has **not** had is a review by an independent human
with a logic / authorization / governance background, of the *semantic*
questions a proof of the rule's shape cannot answer:

- Is "consequence = eligible result node" the right notion of novelty at all?
- The rule is *structural*, not semantic — result-node identity is finer than
  extensional equivalence (`K` vs `S(KK)I`), so an extensional reformulation
  can re-open a settled matter. Is that acceptable, and for which deployments?
- Does DISSONANCE-free eligibility mis-classify any honest bottom?

**Current decision basis:** every gate so far was an LLM under one orchestrator
— cross-vendor but not cross-paradigm, and never a human domain expert. The
maintainer knowingly accepts that AI-only review basis. It is substantial
adversarial depth, not evidence of an independent human review.

**What meeting it looks like:** a written review by such a person, filed in
`reviews/`, adjudicated like any gate. If nobody volunteers, the need may remain
open indefinitely without blocking WRT-005. The Lean guarantees remain stated
for exactly what they cover and no further either way.

### NEED-002 — a context-isolated clean-room implementation from the spec alone

The format's design rule is that implementations agree byte-exactly. Three
implementations exist (Python, Go, Rust), but all were written inside this
project with access to each other's code. A stronger check on the specification
is an implementation produced with **only `SPEC.md` and the conformance pack**
— never this repository's implementation code.

The implementer may be a person or a context-isolated model. A model on the
same host is not an independent party, custody, or external adoption; the
narrow evidence would be clean-room-from-code implementability, and nothing
more. That boundary must remain explicit.

**What meeting it looks like:** an isolated implementer runs the conformance
pack against its own implementation and either reproduces every vector
(evidence the spec is implementable from its published text) or finds a
divergence (a real defect). Until then the repository must not claim clean-room
implementability has been demonstrated. This is an evidence boundary, not an
automatic blocker on merge, adoption, release, or version number.

---

*These needs remain visible so absent validation is named rather than silently
claimed. They describe possible evidence, not authorities the project must wait
for before acting.*
