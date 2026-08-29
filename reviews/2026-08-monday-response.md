# Response — Monday peer review of the flagship paper (PR #30)

**Date:** 2026-08-28. Adjudicated by the maintainer model (Claude). This is
the first review of the *whole paper* rather than the WRT-003 settlement
repair, and it is the most useful the paper has had: it found a conceptual
gap three settlement-focused gates never reached. Substantially accepted; the
paper revisions land in the same PR.

## Verdict accepted in spirit: Major Revision

The central finding is correct and I am not going to argue with it, because I
checked it against the format and it holds. A verified Warrant establishes
that a deterministic computation re-executes to a result over a
content-addressed store; it does **not** establish that the computation
interprets the pinned policy, that its facts derive from the cited evidence,
that it pertains to the subject, or that its result entails the decision. The
paper's §1 wording ("the stated reason really does evaluate to the stated
verdict") is defensible and the reviewer says so; the title and some framing
lean past it. The fix is conceptual, as the reviewer says: **state exactly
what proposition a verified Warrant proves, and make every layer obey it.**

## The proposition, stated once, now propagated

A verified Warrant record proves, and only proves:

- **Integrity** — these bytes hash to this identity; nothing pinned by hash
  (policy, subject, evidence, check) has changed relative to its identifier.
- **Authenticity** — this signature verifies under this key; at settlement
  grade with a trust configuration, this key is bound to this actor.
- **Replay** — for a `ski@v1` reason, this deterministic computation, over
  this store, re-executes to this result.

It does **not** prove: that the computation is an interpretation of the
policy; that its facts derive from the evidence; that it pertains to the
subject; that its result entails the decision; or that any of this existed at
a particular time. The first four are the **justification-binding gap** (new
non-goal NG-7); the last is **historical existence** (SA-12, now elevated to a
grade distinction).

## Dispositions

| # | Concern | Verdict | Action |
| --- | --- | --- | --- |
| MC1 | reason ≠ reason-*for-the-decision*; term not bound to policy/subject/evidence/decision | **ACCEPTED — the central fix** | Abstract + §1 state the proposition; a new §1.2 states the justification-binding gap; THREAT-MODEL gains **NG-7**; the conservative narrowing is adopted as the paper's claim; the reviewer's "ambitious option" (a normative reason-binding profile) is recorded as the recommended next normative step, not built here. |
| MC2 | related work incomplete (PCA, OPA, in-toto SVR, SCITT) | **ACCEPTED** | §2 adds Proof-Carrying Authentication (Appel & Felten, CCS 1999 — verified), OPA decision logs, the in-toto SVR predicate, and SCITT/RFC 9943 (verified: "An Architecture for Trustworthy and Transparent Digital Supply Chains", Standards Track, June 2026), reframed as composition, not distance. |
| MC3 | anchoring is part of the security argument | **ACCEPTED** | Two named grades: **self-contained integrity/replay** (a Warrant store) vs **historical existence/non-equivocation** (only with external receipts — SCITT, OTS, archive). The Air Canada framing is scoped to the first grade with the second named as what a court would additionally need. |
| MC4 | settlement is an experiment disguised as a feature | **ACCEPTED** | §5.2 reframed: settlement is presented as an experimental extension whose current honest result is *partly negative* — computable semantic novelty from filer-controlled syntax is hard, and WRT-003 (four unadopted revisions) is the evidence. Not "foreclosure you can compute" as a shipped contribution. |
| MC5 | key identity ≠ actor identity | **ACCEPTED** | Terminology pass: "key identity" and "actor identity" kept distinct; identity-flavoured claims scoped to the grade that supports them. |
| MC6 | "safe by construction in time and space" overstates | **ACCEPTED** | Qualified: Σ-GLYPH gives a *semantic* work bound and a bound on *peak materialized semantic state*; a concrete binary must separately enforce local resource fences (the Rust stack-overflow fence is the example). And evaluation is a function of `(term, atp, store)`, not `(term, atp)` — missing content yields a distinct unresolved result. |
| MC7 | evaluation is engineering history, not independent validation | **ACCEPTED (partial)** | The ledger discussion is trimmed; the methodological point (negative controls / UNRUN≠PASS as first-class evidence) is kept because the reviewer agrees it is worth preserving; forward-pointers added to the clean-room / interop / formal-property work that would be actual validation. |
| minors 1–6 | pass/fail vs true/false; immutable=content; policy-in-force; impl independence vs language diversity; Rust Ed25519 framing; receipts-not-reasoning | **ACCEPTED** | Folded into the relevant sections; "immutable" is qualified at first use (already done for the envelope; extended to the store/equivocation point). |

## Nothing declined — and why that is itself worth noting

Every prior gate this session had at least one finding I could push back on
with a reproduction. This one I could not, and the reason is structural: the
three WRT gates all attacked *settlement*, one field at a time, and got
steadily narrower; Monday attacked the *claim* and found the gap underneath
all of them. It is the first review aimed at the whole paper, and the first
from outside the settlement rabbit-hole. That a single whole-paper pass found
a larger issue than three deep settlement rounds is the clearest evidence yet
for the project's own thesis that **diversity of *target* matters more than
depth** — and it is recorded in the paper's §7, not just here.

## The one thing I did NOT do, on purpose

I did not build the reason-binding profile (Monday's ambitious option / Q4).
It is the right next normative step — a profile committing the policy-source
hash, a fact manifest, the evidence hashes, and a result→decision mapping into
the computation's own input, so a verifier can check that the term consumes
what the record claims it does. But it is a new normative surface deserving
its own proposal and its own gate, not a paragraph slipped into a review
response. It is recorded as a candidate (WRT-004-shaped) with Monday's Q1–Q4
as its acceptance questions, for the operator to greenlight.

## Answers to the reviewer's questions (brief)

1. No — a conforming verifier cannot currently determine that a `ski@v1` term
   encodes the policy in `under`. That is exactly why the paper now calls it a
   *replayable attached computation*, and reserves "policy justification" for
   the proposed binding profile.
2. No — not without the binding profile; today it is a WPL authoring
   convention (pin the source as evidence, recompile deterministically).
3. No normative relation between `body.decision` and the result node exists
   today. NG-7 says so; the profile would add one.
4. Yes — recorded as the WRT-004 candidate.
5. SCITT is now treated as exactly that natural transparency layer (§2, §5.4).
6. Without an external checkpoint, Warrant claims **integrity + replay**, not
   **historicity** — stated as the grade distinction (MC3).
7. Settlement is being moved out of the central contribution set (MC4);
   WRT-003 stays unadopted pending the human-logician + Lean round.
8. The falsifier is named in the paper: a clean-room implementation from the
   spec alone that *fails* to reproduce a conformance vector, or two
   independent implementations that disagree on one. Its absence is the
   standing gap.
