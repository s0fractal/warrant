# GPT-5.6 Sol — WRT-003 rev 2 adversarial design gate

**Date:** 2026-08-27
**Reviewer label:** `gpt56sol` (self-identified "GPT-5.6 Sol via ChatGPT").
Vendor: OpenAI. **GitHub transport identity:** `s0fractal` — the operator's
own account; the review was authored by the model and posted through it, so
the account is transport, not authorship (recorded in the manifest).
**Target:** `proposals/WRT-003-outcome-fingerprint-purity.md` rev 2 (`a3f0214`).
**Genre:** adversarial design gate (typed, verdict).
**Verdict:** AMEND.
**Posted at:** PR #30 review 5037590934.
**Response:** [`2026-08-gpt56sol-wrt-003-rev2-design-gate-response.md`](2026-08-gpt56sol-wrt-003-rev2-design-gate-response.md)

**Diversity note (honest):** this is the OpenAI family reviewing its own
earlier gate — `annaglova` (rev 1 gate) and `gpt56sol` (rev 2 gate) are both
ChatGPT/OpenAI. So gate rounds 1→2 are *depth within one vendor*, not
diversity. It is recorded because the flagship paper's §7 downgraded a
"diversity beats depth" claim to a single observation; this is a *counter*
observation — depth within one family found the REF-padding hole in that same
family's previous fix — and both belong in the ledger, not just the flattering
one.

---

Verbatim (GitHub review body):

## WRT-003 rev 2 adversarial design gate

**Reviewer:** GPT-5.6 Sol via ChatGPT
**GitHub transport identity:** `s0fractal`
**Verdict: AMEND**

rev 2 fixes the ATP-starvation blocker in the right direction and correctly
refuses to bless raw-term identity after the `I T` counter-vector. I would
**not adopt recommended identity (B) yet**. It moves the no-op novelty surface
from term syntax into evaluator read-set/provenance, and §3.2 also needs one
semantic clarification before it is safe to make consensus-critical.

### BLOCKER — (B) has a REF/read-set padding re-opener

(B) proposes:

`(runtime, {evidence/REF blobs the reduction actually forced}, result_node_hash)`

But `ski@v1` does not execute against a capability consisting of
`body.evidence`; SPEC §3.1 says the **entire Warrant blob store is the Σ-GLYPH
CAS** and every demanded object may resolve from it. Therefore the operational
read-set contains blobs that need not be declared as evidence at all.

A minimal family follows directly from Book I's REF rule:

```
R1 = REF(S)
R2 = REF(R1)
R3 = REF(R2)
...

R1 -> S
R2 -> S
R3 -> S
```

All runs terminate normally with the same result NodeHash `S`. Yet an identity
based on the REF blobs actually forced changes at every level: `R1` forces one
REF layer, `R2` forces two, etc. The filer can add another content-addressed
REF alias to the CAS and obtain a fresh read-set without a new semantic
consequence.

Worse, those alias blobs do **not** have to appear in the candidate's
`evidence` array. So §7(a) can still see "no new evidence" while §7(b) sees a
fresh (B) fingerprint. That contradicts §7(b)'s own phrase "a new demonstrable
consequence **of evidence already present**" — the new identity component came
from an undeclared CAS path, not from a new consequence.

This is the same `I T` attack one layer down: syntactic path identity was
removed, then operational path identity was reintroduced as the consumed-set
member.

**Required gate vector:** settle a normal result through `REF(S)`, then
re-litigate through `REF(REF(S))` with the same declared evidence and the same
result. Under any accepted repair, that must not become novel merely because
the evaluator traversed another REF alias.

There are only three coherent ways out:

1. reject (B) and use semantic result identity;
2. define a normative **declared-evidence capability boundary** for `ski@v1`
   and reject/ignore reads outside it for settlement novelty; or
3. define a stronger semantic dependency relation than "was forced" (actual
   causal evidence, not operational traversal).

Simply intersecting the observed read-set with `body.evidence` is not enough
unless undeclared reads are forbidden: otherwise the computation still consumes
inputs that the fingerprint deliberately pretends it did not consume, which
weakens P1.

### MAJOR — (B)'s "actually forced" set is a new consensus observable

The current runtime consensus target is the deterministic evaluation result
(and ATP accounting). (B) makes an **execution trace property** part of
settlement consensus. "The evaluator can observe it" is not the same as "the
protocol defines it".

Before (B) can be normative, the runtime must define a **semantic demand/read
set**, independent of implementation details such as caching, prefetching,
memoization, internal representation, or equivalent evaluator optimizations.
Python and Go must be required to derive the same logical set, and that set
needs cross-implementation vectors just like result hashes do.

Otherwise two evaluators can agree on the Book I normal form and still disagree
on the Warrant outcome fingerprint — exactly the class of verifier split §13.1
is supposed to prevent.

If (B) survives, the registry requirement should therefore be stronger than
"instrument `eval_hash`": it must specify the read-set semantics and
conformance vectors for them.

### MAJOR — candidate (A) is not dominated by (B); §7's wording may actually require (A)

rev 2 says result-only over-forecloses because two independent derivations from
different evidence can reach the same normal form. I think this conflates **new
derivation** with **new consequence**.

§7 already separates the cases:

- §7(a): **new evidence**;
- §7(b): a **new demonstrable consequence** of evidence already present.

If the evidence is already in the tunnel and the normal-form result is the
same, then the consequence is not new; only the proof/path is new. That is
precisely why raw-term identity was wrong. Adding a consumed-read-set to the
tuple reintroduces derivation identity after rejecting term identity.

So `(runtime, result_node_hash)` deserves to be reopened as the default, not
treated as dominated. If a second derivation/proof is semantically important,
make that provenance/proof a **verified part of the result object** so its
NodeHash changes for a semantic reason. Do not make an evaluator's operational
trace itself the consequence.

This also gives a much cleaner invariant:

> same eligible semantic output => same §7(b) consequence, regardless of
> syntax, aliases, evaluation path, or already-present evidence subset.

### MAJOR — §3.2 must say whether eligibility is a property of the result node or of execution provenance

rev 2 says only a "normal-form" result is eligible and excludes
DISSONANCE/exhausted/unresolved/invalid outcomes. But in the vendored Book I
evaluator, a materialized `("dis", reason)` is itself a normal form (`step5`
returns `None` for `lit / dis`). In particular, a term can directly be the
canonical `DISSONANCE(ATP Exhausted)` node and finish normally with the **same
result hash** as a run that actually exhausted its ATP.

So there are two possible rules, and they are observably different:

- **node-class rule:** every final `DISSONANCE` opcode is ineligible,
  regardless of how it was reached; or
- **execution-origin rule:** only evaluator-generated exhaustion/unresolved/
  invalid events are ineligible, while a term that normally evaluates to that
  same node can be eligible.

The result hash alone cannot distinguish the second rule. If execution origin
matters, `eval_hash` needs a normative outcome-kind/provenance channel and both
implementations must agree on it. If all DISSONANCE nodes are categorically
ineligible, say that directly instead of "only normal form", because Book I
already treats stored DISSONANCE terms as normal forms.

**Required vector:** compare (1) a term that directly normalizes to the
canonical ATP-DISSONANCE node under ample ATP and (2) an unrelated term that
reaches the identical node because its budget actually exhausts. Pin whether
both are ineligible or only (2).

### What I would keep

- P1 purity: keep.
- P2 resource-neutrality: keep, after the eligibility semantics above are made
  exact.
- `expect` / claimed verdict stay out: keep.
- `cmd@v1` contributes no §7(b) fingerprint: keep.
- symmetric tunnel/candidate rule: keep.
- field taxonomy + T1/T2 + cmd negative control: keep.
- protocol/document-version bump and Python/Go lockstep: keep.

### Gate recommendation

For the next revision I would make **result-only (A) the baseline** and force
(B) to justify why "same result from different already-present evidence" is a
*new consequence* rather than merely a new derivation. If (B) is still desired,
it needs two additional pieces before adoption: a declared-evidence/read
capability rule and a normative cross-implementation semantic read-set.

rev 2 successfully closes the original expect-flip and ATP-starvation families.
The remaining problem is now sharper: **do not replace syntactic identity with
operational-trace identity unless that trace is itself protocol semantics and
cannot be padded.**
