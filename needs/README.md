# Needs — what this repository requires but does not yet have

A **need** is something the project has honestly concluded it requires for a
particular status (adoption of a proposal, deposit of a paper, a 1.0), which is
**not yet available** — and which no amount of the work already here can
substitute for. Recording a need here is the opposite of pretending it is met:
it keeps the requirement visible and keeps honestly-labelled *drafts* moving
without either blocking on the need indefinitely or quietly claiming it away.

A need is not a defect and not a blocker on draft work. It is a boundary on
*status*: a draft with an open need stays a draft, and says why.

## Standing needs

### NEED-001 — independent, human logic / governance review of settlement semantics

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

**Why it cannot be met from inside:** every gate so far was an LLM under one
orchestrator — cross-vendor but not cross-paradigm, and never a human domain
expert. A model reviewing its own family's output is depth, not independence.

**What meeting it looks like:** a written review by such a person, filed in
`reviews/`, adjudicated like any gate. Until then WRT-005 stays DRAFT; the
Lean guarantees are stated for exactly what they cover and no further.

### NEED-002 — an independent clean-room implementation from the spec alone

The format's whole design rule is that two independent implementations agree
byte-exactly. Three implementations exist (Python, Go, Rust), but all were
written inside this project by parties who read each other's code. The
standing graduation criterion for any 1.0, and the strongest possible check on
the specification, is an implementation written by someone who has **only the
`SPEC.md` text and the conformance pack** — never this repository's code.

**Why it cannot be met from inside:** independence is the property being
tested; a fourth implementation by the same authors does not supply it.

**What meeting it looks like:** a stranger runs the conformance pack against
their own implementation and either reproduces every vector (evidence the spec
is implementable from its text) or finds a divergence (a real defect). Either
outcome is worth more than another internal pass. The conformance pack
(`conformance/`) is the standing invitation.

---

*These are the two needs the project keeps naming across its documents; they
live here so the naming is in one place and a draft's dependence on them is a
recorded fact rather than an implied promise.*
