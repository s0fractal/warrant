# proofs/ — the settlement fingerprint rule, mechanized

One Lean 4 file, `Settlement.lean`, mechanizes the acceptance invariants of
`proposals/WRT-005-outcome-fingerprint-purity.md` (rev 4) — the settlement
outcome-fingerprint rule that four adversarial gate rounds drove to its
current shape. It turns the property tests in
`tests/fixtures/wrt005_gate_countervectors.py` (which show that the CURRENT
spec ADMITS all five attacks on concrete inputs, and that the proposed rev-4
arithmetic collapses them) into **theorems about the rule's algebra** (which
show the collapse holds *for all* inputs).

## What is proved, and what is cited

Stated plainly, because this repository's sibling paper is about apparatus that
claims more than it checks. This file proves the part that is pure algebra over
a result value; it does **not** re-mechanize the Book I evaluator.

**Proved here** (`Settlement.lean`; the guard `check_settlement.py` pins each
theorem's axiom cone and reports the union used):

*Fingerprint algebra — cone `{propext}`:*

| theorem | closes |
| --- | --- |
| `fp_ignores_claims` | the fingerprint cannot read `expect` or the claimed `verdict` — the **expect-flip** (gate round 1) |
| `fp_factors_through_result` | equal results give equal fingerprints, whatever the term or path — the **`I·T` wrapper** and **REF-padding** (gate round 2) |
| `fp_is_function_of_result` | the fingerprint is literally a function of the result value alone (purity, packaged) |
| `dissonance_ineligible`, `fp_none_of_dissonance` | a DISSONANCE result contributes nothing — the **ATP-starvation** run returns `.dis rATP` and lands here (gate round 1/2) |
| `nested_dissonance_ineligible` | a stuck application containing a DISSONANCE is ineligible under the "anywhere" rule — the **nested-DISSONANCE** re-opener a root-only rule missed (gate round 3, Qwen) |
| `eligible_iff_no_dis` | eligibility is exactly DISSONANCE-freedom |
| `atp_cannot_steer` | no budget the filer picks changes an eligible fingerprint — **conditional** on the Book I fact below |

*§7 admissibility — cone `{propext, Quot.sound}` (the money theorems: not "is
this fingerprint new" but "can this settled matter be re-opened"):*

| theorem | states |
| --- | --- |
| `restatement_inadmissible` | a candidate citing no evidence outside the tunnel and no eligible fingerprint outside it **cannot re-open the matter** — the single guarantee the whole settlement layer exists for; every attack family is an instance |
| `dissonance_candidate_inadmissible` | a candidate whose reasons all reduce to a bottom, with no new evidence, is inadmissible — ATP-starvation and nested-DISSONANCE at the admissibility level |
| `novel_result_admissible` | a candidate reaching a **new eligible result** IS admissible — §7(b) is not a dead letter (the objection gate round 3 raised, declined with a proof) |

The tunnel's fingerprint set and blob set are *inputs* to the admissibility
function: computing them from the prior-DAG is a standard transitive closure,
orthogonal to the admissibility rule, and not modeled here.

**Cited, not re-proved** — the Book I evaluator, its totality, and its
determinism live in `sigma-glyph/proofs/EvalMachine.lean` (`eval` is a Lean
function, so determinism is definitional; `eval_settles` is proved there). This
file models the evaluator abstractly as `Eval := Term → Nat → Term`, which is
exactly WRT-005 §3.6's precondition — *the runtime is a deterministic
function* — and any Lean function satisfies it. `atp_cannot_steer` takes the
one genuinely evaluator-level fact it needs (a non-exhausting run's result is
budget-independent) as an explicit hypothesis `stable` rather than smuggling it
in, because it belongs to Book I and not to the fingerprint algebra. The result
`Term` mirrors `EvalMachine.Term` with the eval-internal `thunk` dropped: a
returned result is fully materialized.

This is the same layering sigma-glyph uses (a mechanized bound plus an
empirical bridge to the running oracle). The bridge from *this* rule to the
running Python/Go settlement code is `tests/fixtures/wrt005_gate_countervectors.py`
and `tests/settlement.py`; the Lean file is the "for all inputs" companion to
their "on these inputs".

## Running it

```
lean proofs/Settlement.lean          # kernel-check the proofs (needs Lean 4, no mathlib)
python3 proofs/check_settlement.py    # the guard: compiles clean, holds every
                                      # theorem's axiom cone within the sound set
                                      # {propext, Quot.sound, Classical.choice}
                                      # (actual union used: {propext, Quot.sound}),
                                      # denylists sorry/axiom/native_decide, and
                                      # fails if a theorem is proved but not listed
```

`tools/check.py` runs the guard as one of its checks; it reports **UNRUN**
(never a failure, never a silent pass) on a machine with no Lean toolchain.

## What this does NOT claim

- It does not prove the Python/Go implementations match this rule — that is the
  fixtures' job, and the standing gap is a second implementation of the rule by
  someone who has not read this one.
- It does not adopt WRT-005. The proposal is design-only; mechanizing its
  *acceptance criteria* is evidence for the gate, not the gate's verdict.
- It does not settle the open semantic questions (is result-value the right
  notion of consequence?). Those are for the human-logician review both the
  WRT-005 (formerly WRT-003) gates and the Monday paper review named; a proof that the rule has
  the shape it claims is not a proof that the shape is the right one.
