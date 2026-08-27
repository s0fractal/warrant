/- WRT-003 rev 4 settlement fingerprint rule, mechanized (Lean 4 core).

   This turns WRT-003's acceptance invariants T1 (purity) and T2 (eligibility)
   from property tests (`tests/fixtures/wrt003_gate_countervectors.py`) into
   proved theorems about the RULE'S ALGEBRA — the layer that is independent of
   SHA-256 and of the Book I evaluator's internals.

   LAYERING, stated honestly (mirrors sigma-glyph's separation of a mechanized
   bound from an empirical bridge). This file proves what the fingerprint rule
   does GIVEN a result. It does NOT re-mechanize the Book I evaluator: that
   machine, its totality, and its determinism are mechanized in
   sigma-glyph/proofs/EvalMachine.lean (`eval` is a Lean function, so
   determinism is definitional; `eval_settles` is proved there). We model the
   evaluator abstractly as a function `Eval := Term → Nat → Term`, which is
   exactly the WRT-003 §3.6 precondition ("the runtime is a deterministic
   function"): any Lean function satisfies it. The result `Term` mirrors
   EvalMachine.Term with `thunk` dropped, because a RESULT is fully
   materialized (a thunk is an eval-internal state, never a returned result).

   What the theorems below establish, against the four+one re-opener families
   the three gates found:
     * expect-flip / claimed-verdict flip  -> `fp_ignores_claims`
     * `I·T` wrapper / REF-padding          -> `fp_factors_through_result`
     * ATP-starvation (-> DISSONANCE)       -> `dissonance_ineligible`, `atp_cannot_steer`
     * nested DISSONANCE (stuck app)        -> `nested_dissonance_ineligible`
   Together: the fingerprint is a function of the eligible, DISSONANCE-free
   result value and of nothing a filer writes. -/

namespace Warrant.Settlement

/-- Book I result terms (mirror of sigma-glyph `EvalMachine.Term`, minus the
    eval-internal `thunk`). `dis` is the error / bottom object. -/
inductive Term where
  | lit (atom : List UInt8)
  | ref (target : List UInt8)
  | dis (reason : List UInt8)
  | app (f a : Term)
deriving DecidableEq, Repr, Inhabited

/-- A result contributes a fingerprint iff it carries NO DISSONANCE node
    ANYWHERE (WRT-003 rev 4, §3.2 — "anywhere", not "root", after the nested
    counter-vector). Recursive, and a pure function of the result value. -/
def containsDis : Term → Bool
  | .dis _   => true
  | .app f a => containsDis f || containsDis a
  | _        => false

def eligible (r : Term) : Bool := ! containsDis r

/-- A ski@v1 check as the filer presents it. Only `term` and `atp` are eval
    inputs; `expect` and `verdict` are the filer's CLAIMS — the fields WRT-003
    proves the fingerprint must not read. -/
structure Check where
  term    : Term
  atp     : Nat
  expect  : Term
  verdict : Bool

/-- The evaluator, abstractly: a deterministic function term×budget → result.
    (Book I; §3.6 precondition. Determinism is definitional for a Lean fn.) -/
abbrev Eval := Term → Nat → Term

/-- The outcome fingerprint (WRT-003 rev 4, §3.1): the runtime tag and the
    result value, contributed ONLY when the result is eligible. `ski` is the
    single runtime here; the tuple carries the result and nothing else. -/
inductive FP where
  | ski (result : Term)
deriving DecidableEq, Repr

def fingerprint (ev : Eval) (c : Check) : Option FP :=
  let r := ev c.term c.atp
  if eligible r then some (.ski r) else none

/- ============================ T1 — Purity ============================ -/

/-- The fingerprint does not depend on `expect` or `verdict`: two checks with
    the same `term` and `atp` but any claims fingerprint identically. This is
    the expect-flip and claimed-verdict-flip immunity, by construction — the
    function cannot read a field it is not given. -/
theorem fp_ignores_claims (ev : Eval) (t : Term) (a : Nat)
    (e₁ e₂ : Term) (v₁ v₂ : Bool) :
    fingerprint ev ⟨t, a, e₁, v₁⟩ = fingerprint ev ⟨t, a, e₂, v₂⟩ := rfl

/-- The fingerprint factors through the evaluated result: any two checks whose
    evaluations agree have the same fingerprint, regardless of term syntax or
    evaluation path. This is the `I·T`-wrapper and REF-padding immunity — those
    attacks reach the SAME result under a different term, and equal results
    give equal fingerprints. -/
theorem fp_factors_through_result (ev : Eval) (c₁ c₂ : Check)
    (h : ev c₁.term c₁.atp = ev c₂.term c₂.atp) :
    fingerprint ev c₁ = fingerprint ev c₂ := by
  unfold fingerprint; rw [h]

/-- Purity, packaged: the fingerprint is a function of the result value alone.
    There EXISTS a function `g : Term → Option FP` such that every check's
    fingerprint is `g` of its evaluated result. -/
theorem fp_is_function_of_result (ev : Eval) :
    ∃ g : Term → Option FP, ∀ c : Check, fingerprint ev c = g (ev c.term c.atp) := by
  exact ⟨fun r => if eligible r then some (.ski r) else none, fun _ => rfl⟩

/- ========================= T2 — Eligibility ========================= -/

/-- Any DISSONANCE result is ineligible — from the result alone, no execution
    provenance. Covers ATP-Exhausted, Unresolved, and Invalid uniformly, and a
    directly-stored DISSONANCE the same as a genuine exhaustion (rev 3's point:
    they share a hash; here they share a constructor). -/
theorem dissonance_ineligible (r : List UInt8) : eligible (.dis r) = false := rfl

/-- A DISSONANCE result contributes no fingerprint. This is the ATP-starvation
    closure: a starved run returns `.dis rATP`, which lands here. -/
theorem fp_none_of_dissonance (ev : Eval) (c : Check) (r : List UInt8)
    (h : ev c.term c.atp = .dis r) : fingerprint ev c = none := by
  unfold fingerprint; rw [h]; rfl

/-- The nested case the third gate found: a stuck application whose ROOT is not
    DISSONANCE but which contains one is still ineligible under the "anywhere"
    rule. (A root-only rule would have called this eligible — the re-opener.) -/
theorem nested_dissonance_ineligible (f a : Term)
    (h : containsDis f = true ∨ containsDis a = true) :
    eligible (.app f a) = false := by
  simp only [eligible, containsDis]
  rcases h with h | h <;> simp [h]

/-- Contrapositive, as used at admission: an eligible result is DISSONANCE-free
    through and through. -/
theorem eligible_iff_no_dis (r : Term) : eligible r = true ↔ containsDis r = false := by
  simp [eligible]

/- ===================== Anti-steering (budget) ===================== -/

/-- ATP cannot steer an eligible fingerprint. This is the ONE statement that
    needs a Book I fact rather than pure algebra: that a non-exhausting run's
    result is budget-independent. We take that fact as the hypothesis `stable`
    (WRT-003 §3.6 — Book I determinism + the size ≤ atp+1 bound; mechanized in
    sigma-glyph as the eval machine, cited not re-derived), and conclude that
    no budget the filer picks changes an eligible fingerprint. Where the run
    is NOT eligible (it exhausted), the fingerprint is `none` by
    `fp_none_of_dissonance`, so there is nothing to steer either way. -/
theorem atp_cannot_steer (ev : Eval) (t : Term) (a₁ a₂ : Nat) (e : Term) (v : Bool)
    (stable : eligible (ev t a₁) = true → ev t a₂ = ev t a₁) :
    eligible (ev t a₁) = true →
      fingerprint ev ⟨t, a₂, e, v⟩ = fingerprint ev ⟨t, a₁, e, v⟩ := by
  intro helig
  unfold fingerprint
  simp only [stable helig]

/- ============ Concrete attack families (decidable checks) ============ -/

/-- A concrete toy evaluator: the settled question reduces to `S`; the starved
    and nested-dis terms reduce to DISSONANCE-bearing results; a genuinely new
    computation reduces to a different clean value `K`. The `example`s below are
    the Lean mirror of the Python fixture, checked by the kernel. -/
private def S : Term := .lit [0x53]
private def K : Term := .lit [0x4B]
private def D : Term := .dis (List.replicate 32 0xAB)

/-- expect-flip: same computation (result `S`), different `expect`/`verdict` in
    the check — identical fingerprint. -/
example (ev : Eval) (t : Term) (a : Nat) :
    fingerprint ev ⟨t, a, S, true⟩ = fingerprint ev ⟨t, a, D, false⟩ := rfl

/-- starvation: a result of `D` (DISSONANCE) contributes nothing. -/
example : fingerprint (fun _ _ => D) ⟨S, 1, S, true⟩ = none := rfl

/-- nested DISSONANCE: `(D · K)` is ineligible though its root is `app`. -/
example : eligible (.app D K) = false := rfl

/-- clean novelty survives: a different clean result `K` IS eligible and gives a
    fingerprint (the positive §7(b) control — the rule is not "reject all"). -/
example : fingerprint (fun _ _ => K) ⟨K, 5, K, true⟩ = some (.ski K) := rfl

/-- wrapper/REF immunity, concretely: two evaluators reaching the same result
    `S` on their respective terms give the same fingerprint. -/
example (t₁ t₂ : Term) (a₁ a₂ : Nat) :
    fingerprint (fun _ _ => S) ⟨t₁, a₁, S, true⟩
      = fingerprint (fun _ _ => S) ⟨t₂, a₂, D, false⟩ := rfl

/- ================= §7 admissibility (the money theorem) =================

   The fingerprint theorems above are about ONE reason. This layer is about the
   actual question a settled matter faces: can it be re-opened? SPEC §7 admits a
   re-litigation iff (a) it cites an evidence blob absent from the settling
   tunnel, or (b) it has a reason whose eligible fingerprint is absent from the
   tunnel. We model the tunnel's fingerprint set and blob set as INPUTS: computing
   them from the prior-DAG is a standard transitive closure, orthogonal to the
   admissibility rule and not modeled here. What is proved: no attack family
   re-opens a matter whose computation the tunnel already holds, and a genuinely
   new eligible result does. -/

abbrev Blob := List UInt8

/-- what a reason's result contributes to the §7(b) novelty set. -/
def contributes (r : Term) : Option FP :=
  if eligible r then some (.ski r) else none

/-- a re-litigation candidate, reduced to what §7 actually reads: the evidence
    hashes it cites, and the evaluated results of its ski reasons. -/
structure Candidate where
  evidence : List Blob
  results  : List Term

/-- §7 admissibility: (a) new evidence, OR (b) a new eligible fingerprint. -/
def admissible (tunFP : List FP) (tunBlobs : List Blob) (c : Candidate) : Bool :=
  c.evidence.any (fun b => ! tunBlobs.contains b)
  || c.results.any (fun r => match contributes r with
                              | some fp => ! tunFP.contains fp
                              | none    => false)

/-- **Restatement is inadmissible.** A candidate that cites no evidence outside
    the tunnel and whose every eligible result's fingerprint is already in the
    tunnel cannot re-open the matter. This is the one theorem the whole
    settlement layer exists to guarantee, and every attack family is an instance
    of it. -/
theorem restatement_inadmissible
    (tunFP : List FP) (tunBlobs : List Blob) (c : Candidate)
    (hev : ∀ b ∈ c.evidence, tunBlobs.contains b = true)
    (hfp : ∀ r ∈ c.results, ∀ fp, contributes r = some fp → tunFP.contains fp = true) :
    admissible tunFP tunBlobs c = false := by
  unfold admissible
  simp only [Bool.or_eq_false_iff, List.any_eq_false]
  refine ⟨?_, ?_⟩
  · intro b hb
    simp only [Bool.not_eq_true', Bool.not_eq_false]
    exact hev b hb
  · intro r hr
    cases hc : contributes r with
    | none => simp
    | some fp =>
        simp only [Bool.not_eq_true', Bool.not_eq_false]
        exact hfp r hr fp hc

/-- **A genuinely new eligible result IS admissible** — §7(b) is not a dead
    letter (the objection the third gate raised and this declines). -/
theorem novel_result_admissible
    (tunFP : List FP) (tunBlobs : List Blob) (c : Candidate) (r : Term)
    (hmem : r ∈ c.results) (helig : eligible r = true)
    (hnew : tunFP.contains (.ski r) = false) :
    admissible tunFP tunBlobs c = true := by
  unfold admissible
  simp only [Bool.or_eq_true, List.any_eq_true]
  right
  refine ⟨r, hmem, ?_⟩
  simp only [contributes, helig, if_true, hnew, Bool.not_false]

/-- **Any candidate whose reasons all reduce to DISSONANCE, citing no new
    evidence, is inadmissible.** This is ATP-starvation and nested-DISSONANCE at
    the admissibility level: a bottom result contributes no fingerprint, so §7(b)
    has nothing to offer and §7(a) is closed by the no-new-evidence hypothesis. -/
theorem dissonance_candidate_inadmissible
    (tunFP : List FP) (tunBlobs : List Blob) (c : Candidate)
    (hev : ∀ b ∈ c.evidence, tunBlobs.contains b = true)
    (hdis : ∀ r ∈ c.results, containsDis r = true) :
    admissible tunFP tunBlobs c = false := by
  apply restatement_inadmissible tunFP tunBlobs c hev
  intro r hr fp hc
  -- a DISSONANCE-bearing result is ineligible, so `contributes r = none`
  simp [contributes, eligible, hdis r hr] at hc

/-- Concrete: a matter settled by computing `S` (tunnel holds fingerprint
    `ski S`). The expect-flip / wrapper / REF-pad candidate re-reaches `S` with
    no new evidence — inadmissible. -/
example : admissible [FP.ski S] [] ⟨[], [S]⟩ = false := rfl

/-- Concrete: the ATP-starvation / nested-DISSONANCE candidate reduces to a
    bottom, no new evidence — inadmissible. -/
example : admissible [FP.ski S] [] ⟨[], [D]⟩ = false := rfl
example : admissible [FP.ski S] [] ⟨[], [.app D K]⟩ = false := rfl

/-- Concrete positive: a candidate reaching a NEW clean value `K` — admissible. -/
example : admissible [FP.ski S] [] ⟨[], [K]⟩ = true := rfl

end Warrant.Settlement
