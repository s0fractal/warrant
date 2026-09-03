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
the optional human review below has not happened. The clean-room need has since
split: its base-grade half is met by a bounded model-generated implementation;
its settlement-grade half remains open.

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

### NEED-002 — clean-room-from-code implementation from the public surface

The format's design rule is that implementations agree byte-exactly. Three
implementations exist (Python, Go, Rust), but all were written inside this
project with access to each other's code. A stronger check on the specification
is an implementation produced without this repository's implementation code.
The allowed construction inputs are explicit: the frozen `SPEC.md`, frozen
conformance contract and public vectors, prior model-emitted candidate modules,
runner output, and orchestrator-authored public-runtime probes. The last class
may contain a proposed API call or other repair hypothesis; it is not neutral
machine authorship and must be named as such.

The implementer may be a person or a context-isolated model. A model on the
same host is not an independent party, custody, or external adoption; the
narrow evidence would be clean-room-from-code implementability, and nothing
more. That boundary must remain explicit.

The need is now split by the grades the conformance contract already separates.
An implementation can honestly complete the base format without implementing
the settlement runtime.

#### NEED-002-BASE — MET at one frozen operand

Experiment `NEED-002-A3-COLLAB-JS` used an iterative local multi-model process:
Qwen3.8 and Gemma4 authored semantic JavaScript modules; the orchestrator
provided the frozen SPEC, conformance material, prior model outputs, runner
output, and two orchestrator-authored runtime probes, but no Warrant
implementation source. One retained store handoff is a curated result extract,
not canonical runner output, and the diagnostic-generator bytes were not
preserved. The resulting candidate achieved the complete **base** grade of the
candidate conformance pack 1.2.0: 135 PASS, 0 FAIL, 0 UNRUN, 0 ERROR, with all
60 base-grade negative vectors answered and none accepted. The runner detected
all four deliberate mutations.

The compact evidence bundle, prompt-input provenance audit, candidate, frozen
operands, accepted generation streams, and replay command live in
[`need-002-a3-base/`](need-002-a3-base/). The claim and exact commitments are in
[`NEED-002-A3-BASE.json`](NEED-002-A3-BASE.json); `tools/verify_need002_a3.py`
checks the closed bundle and replays it.

`MET_BASE_ONLY` is **self-certified by this repository's maintainer**. The
record says so in a closed `adjudication` object; the verifier enforces that it
cannot be relabelled independent. Adversarial review of the mechanism narrows
the claim but does not turn the experiment into independent custody or external
validation.

`MET` is deliberately narrow: implementability from the public base surface was
demonstrated for one frozen corpus. It is not one-shot or single-model
reproduction, proof outside the vectors, independent custody, human review,
external adoption, a release, or governance adoption.

#### NEED-002-SETTLEMENT — OPEN

The A3 candidate claims base grade. Two positive and two negative settlement
vectors are `NOT-CLAIMED`; it implements neither `ski-run` nor settlement-grade
store verification. Meeting this half requires a separately bounded clean-room
implementation to replay the settlement corpus. Base evidence cannot be
composed into settlement credit.

This remains an evidence boundary, not an automatic blocker on merge, adoption,
release, or version number.

---

*These needs remain visible so absent validation is named rather than silently
claimed. They describe possible evidence, not authorities the project must wait
for before acting.*
