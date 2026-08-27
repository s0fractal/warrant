# WRT-003: Outcome-fingerprint purity — the expect-flip repair

**Status:** DRAFT rev 2 (2026-08-27) — **design only.** No SPEC edit, no code
change, no vector change is made by this document. Adoption requires an
adversarial gate and, on adoption, a SPEC document-version bump (this is a
consensus-behavior change: two verifiers at different revisions of §7 return
different admissibility verdicts over the same store).

**rev 2 (2026-08-27)** closes the first design gate
(`reviews/2026-08-annaglova-wrt-003-design-gate.md`, verdict AMEND), which
found two re-openers that survive rev 1 — both reproduced against both
implementations (`tests/fixtures/wrt003_gate_countervectors.py`):

- **ATP starvation (BLOCKER, accepted).** rev 1 excluded `atp` from the tuple
  but let a resource-exhaustion outcome *be* a fingerprint — and §5 blessed
  "same term under an exhausting budget" as its **positive** novelty case,
  i.e. the acceptance criterion tested the attack. rev 2 adds a
  **novelty-eligibility** predicate: only a canonical **normal-form** result
  is novelty-eligible; every DISSONANCE / fault / unresolved outcome
  demonstrates a fact about the *budget or the store*, not a consequence of
  the evidence, and contributes no fingerprint (§3.2). Because Book I is
  deterministic, once a term is not starved its normal form is a function of
  the term alone, so no budget the filer picks steers an eligible outcome.
- **Semantic-no-op wrapper (MAJOR, escalated).** `I T` re-runs to the same
  result under a fresh term hash; raw-term identity admits it, and it is
  *maximally* relevant, so relevance policy cannot catch it. rev 2 does not
  silently keep raw-term identity: §3.3 lays out the identity choice as the
  proposal's headline open question with a recommendation, because picking
  computation identity unilaterally is exactly what the gate exists to
  prevent.

rev 1's core (drop `expect`/verdict; no `cmd@v1` fingerprint; symmetric
tunnel; doc-version bump; registry constraint) survives the gate unchanged —
the reviewer kept all of it.

**Provenance.** The defect was predicted from §7's fingerprint definition by
an external paper review
(`reviews/2026-08-chatgpt-web-paper-flagship-review.md`), reproduced against
both settlement-grade implementations the same day (3/3 fresh-`expect`
re-litigations of a settled question admitted; reproduction in the
[response](../reviews/2026-08-chatgpt-web-paper-flagship-review-response.md)),
and adjudicated as a **specification defect, not an implementation defect**:
`tests/settlement.py` `case_relitigation`'s "new fingerprint" case *is* an
expect-flip and pins it admissible, because that is what §7 says.

## 1. The defect

SPEC §7 defines outcome fingerprints:

```
ski@v1:  {runtime, term, expect, verdict(re-run), result_node_hash}
cmd@v1:  {runtime, sorted evidence hashes, verdict(claimed), transcript hash}
```

§7(b) admits a re-litigation whose check re-runs to a fingerprint absent from
the settling tunnel. The 0.5.0 repair made the `ski@v1` verdict the *re-run*
verdict, closing the lied-verdict flip. What it left: **`expect` is a
filer-chosen field inside a tuple that is supposed to measure what a
computation demonstrated.** File the same `term` with a fresh `expect`; the
re-run honestly returns `fail`; the tuple differs in `expect` (and the
verdict `expect` induces); admission answers "(b) new outcome fingerprint."
2^256 choices of `expect`, each a free re-opener, zero new computation, zero
new evidence. For `cmd@v1` it is worse and already recorded (SA-1): the
verdict itself is filer-written.

Both implementations agree perfectly — on the defect. Python
`impl/warrant.py:781`; Go `impl-go/main.go:1835`. That agreement is why this
is a WRT and not a bug fix: the specification is the thing that is wrong.

## 2. The principle

Two properties, not one — the gate showed that rev 1's single property was
insufficient:

> **P1 — Purity.** An outcome fingerprint MUST be a function of the
> computation the verifier itself performed and the content-addressed inputs
> that computation consumed — and of nothing else. No field a filer writes
> and the verifier does not recompute may enter the tuple.
>
> **P2 — Novelty-eligibility.** Only an outcome that demonstrates a
> *consequence of the evidence* may contribute a fingerprint. An outcome
> that is a fact about the filer's chosen **budget** (resource exhaustion),
> about a **missing blob** (unresolved reference), or about a **malformed
> object** (invalid) is not novelty-eligible and contributes no fingerprint.

Purity alone is not enough because "the verifier computed it" does not imply
"the filer did not steer it": the filer steers *which* computation runs and
*with what budget*, and a resource-exhaustion outcome is genuinely computed
yet carries only the filer's budget choice. P2 is what rules that out. The
current `ski@v1` tuple fails P1 in two members (`expect`, and the derived
`verdict`) and fails P2 (exhaustion outcomes are admitted); the current
`cmd@v1` tuple fails P1 in every member the verifier cannot check.

## 3. The repair

### 3.1 `ski@v1`

```
fingerprint = (runtime="ski@v1", <computation identity>, result_node_hash)
    — contributed ONLY when result_node_hash is a canonical normal form (§3.2)
```

- `result_node_hash` is what the verifier's own re-execution produced; the
  computation identity is discussed in §3.3 (rev 1 used the raw `term` hash;
  the gate showed that is too weak, and the choice is now open).
- `expect` and `verdict` are dropped. `verdict` is `result == expect`, so
  keeping either keeps the expect-flip (rev 1's finding, unchanged).
- `atp` is absent as a member **and** neutralized by §3.2: the only way a
  filer-chosen budget changes an eligible outcome is by exhausting the run,
  and an exhausted run is not eligible. Among non-exhausted runs of one term
  the normal form is invariant (Book I determinism, `size ≤ atp+1`), so no
  budget steers an eligible fingerprint.

### 3.2 Novelty-eligibility (rev 2; closes the ATP-starvation BLOCKER)

Book I's canonical outcomes are: **normal form**, **DISSONANCE(ATP
Exhausted)**, **DISSONANCE(Unresolved Reference)**, and the **INVALID**
object (SPEC §3.1; `impl/sigma_glyph.py`). Of these, **only a normal-form
result is novelty-eligible.** A non-normal-form outcome:

- **Exhausted** — states "budget `atp` was insufficient for `term`", a fact
  about the filer's budget choice, re-derivable for *any* terminating term by
  lowering `atp`. Admitting it is the ATP-starvation re-opener.
- **Unresolved** — states "a referenced blob is absent", a fact about store
  completeness (a non-goal, NG-2), not a consequence of present evidence.
- **Invalid** — states "an object is malformed", a fact about the blob, not
  about the evidence.

None of the three is a *demonstrable consequence of the evidence* in §7(b)'s
sense, so none contributes a fingerprint, on either the tunnel side or the
candidate side. A candidate whose every check re-runs to a non-eligible
outcome cites nothing new and is inadmissible.

**Predicate novelty, answered honestly.** A genuinely new question about the
evidence is real computation — a term that reduces to a normal form the
verifier can hash — and fingerprints as new because the verifier ran it. A
"question" expressed only as a different `expect` constant, or as a smaller
budget, is not computation and demonstrates nothing; P1 and P2 exclude them
respectively. Novelty stays format; *which* eligible terms are relevant stays
policy — the boundary §7 already names, now drawn where it belongs.

### 3.3 Computation identity — the headline open question (MAJOR, escalated)

rev 1's tuple used the raw `term` hash as computation identity. The gate's
`I T -> R` counter-vector defeats it: `I T`, `I (I T)`, … each have a fresh
term hash, re-run honestly to the same normal form `R`, and are all
fingerprint-distinct — and *maximally relevant*, so no relevance policy can
filter them without itself becoming a semantic-equivalence engine. Raw-term
identity is therefore rejected. Three candidates remain; the proposal does
**not** pick unilaterally, because computation identity is the load-bearing
design decision and the gate is where it should be chosen. My analysis and
recommendation:

- **(A) result-only:** `(runtime, result_node_hash)`. Simplest, and it
  directly matches §7(b)'s words — "a new demonstrable *consequence*" — since
  the consequence *is* the result. Kills the wrapper attack completely.
  **Cost:** over-foreclosure. Two genuinely independent derivations that
  reach the same normal form collide, so a second, honestly-new argument that
  happens to conclude the same value is blocked as "not new". For a closed
  tautology (`(K S)K -> S`, consuming no evidence) this is arguably correct
  — a math fact is not a consequence of *this question's* evidence at all —
  but for a term that consumes evidence it is too strong.
- **(B) consumed-evidence + result:** `(runtime, {evidence/REF blobs the
  reduction actually forced}, result_node_hash)`. This is the honest reading
  of "a new consequence *of the evidence*": identity is *what inputs produced
  what result*, and the term is the filer's path, which drops out. `I T` and
  `T` force the same evidence blobs and reach the same `R` → same identity →
  not new. Two derivations from *different* already-present evidence reaching
  the same result are correctly distinct. **Cost:** the evaluator must report
  the set of REF blobs it forced — an instrumentation change to `eval_hash`
  (it already resolves every REF through the CAS, so the set is observable;
  it is not currently returned). This is my **recommended** direction: it is
  the only candidate whose identity is *what §7(b) actually asks about*.
- **(C) keep raw term, scope the guarantee down:** WRT-003 removes
  unverified-field flips and budget starvation but explicitly does **not**
  prevent semantic-no-op restatements, recorded as a new THREAT-MODEL row.
  Honest and cheap; leaves a maximally-relevant re-opener in the format.
  Acceptable only if (B)'s instrumentation is judged too costly for this
  revision.

The gate should decide between (B) and (C) — (A) is dominated by (B). If (B),
the purity theorem's identity term is the consumed-evidence set and the
property test must include the wrapper counter-vector on the *rejecting*
side. If (C), the same counter-vector goes in on the *admissible* side with
the residual documented, so the scope-down is deliberate and visible.

### 3.4 `cmd@v1`

**`cmd@v1` reasons contribute no outcome fingerprint.** At settlement grade,
a `cmd@v1` reason can support §7(a) (new evidence) and nothing else; §7(b)
requires a runtime the verifier re-executes.

The alternative recorded in SA-1 — fingerprint `= (runtime, sorted evidence,
transcript)` — was considered and is **rejected**: a transcript blob is
filer-fabricated at the cost of one write, so that tuple is exactly as
flippable as the current one, one level down. There is no pure fingerprint
for a computation the verifier cannot see; pretending otherwise is how §7
got here. This subsumes SA-1's open choice: of its two candidate repairs,
this proposal takes "novelty requires re-execution", generalized to any
future runtime via §5's registry rule.

### 3.5 Tunnel side, symmetrically

Tunnel fingerprints are computed by the same rule (they already are, in both
implementations — one function serves both sides). Consequences:

- A tunnel `ski@v1` reason blocks every later restatement of the same
  computation regardless of the `expect` under which it was originally filed
  — strictly *stronger* foreclosure than today, where an old reason's tuple
  only collides with a candidate that matches its `expect` too.
- Old `cmd@v1` reasons stop contributing tunnel fingerprints. They never
  blocked anything a determined filer could not flip past, so no real
  foreclosure is lost; what is lost is the *appearance* of one.
- §7's "reason lacking a required field cannot block novelty" clause
  simplifies: the required fields for `ski@v1` become resolvable
  `check` + re-executable term; `transcript` exits the novelty rule
  entirely (it remains §3's inspectability convention).

## 4. What this changes, and what it cannot

- **No stored byte moves.** Fingerprints are computed at verification time
  and never stored. No WarrantID, signature, blob, or vector hash changes.
  Nothing is re-signed. §8's five hashes are untouched.
- **Admissibility verdicts move.** The expect-flip family: admissible →
  inadmissible. The ATP-starvation family (same term, starved budget →
  DISSONANCE): admissible today → inadmissible (§3.2). `cmd@v1`-only
  re-litigations lacking new evidence: admissible today (write a different
  word) → inadmissible. The semantic-no-op wrapper (`I T`): admissible today
  → inadmissible **iff** identity (B) is adopted; still admissible (as a
  documented residual) under (C) — the one verdict this proposal leaves to
  the gate.
- **Consensus versioning.** Verifiers at old-§7 and new-§7 disagree on
  `settle` verdicts by design; per the §5-line design rule this ships as a
  SPEC document-version bump with both reference implementations moving in
  the same release, mirroring how v0.4 shipped the signature flag-day.
- **What purity does not buy:** relevance. A filer can still manufacture
  unbounded *genuinely new* computations (fresh terms) that are irrelevant
  to the settled subject. That bound stays where §7 already puts it — the
  active settlement policy — and this proposal does not touch it.

## 5. Acceptance criteria — the invariants, stated to be checked

Two theorems now, matching the two properties of §2. The field taxonomy the
gate asked for (MAJOR-3) is: **semantic** = the term / the computation
identity of §3.3; **claim** = `expect`, claimed `verdict`, `transcript`,
`because` packaging; **resource** = `atp`.

**T1 (Purity).** For a fixed store and fixed semantic inputs, the fingerprint
is invariant under every mutation of a **claim** field. — Current §7: fails
(the expect-flip is the counterexample). §3: holds by construction (no claim
field is in the tuple).

**T2 (Resource-neutrality / eligibility).** For a fixed store and fixed
semantic inputs, mutating the **resource** field either leaves the fingerprint
unchanged (non-exhausted → same normal form) or removes it (exhausted → not
eligible); it never yields a *different* eligible fingerprint. — Current §7:
fails (ATP starvation is the counterexample). §3.2: holds by construction.

Adoption gate MUST include, in order of strength:

1. **Both reproductions as negative controls**, from
   `tests/fixtures/wrt003_gate_countervectors.py`, wired into
   `tests/settlement.py`:
   - expect-flip: 3/3 admitted (current) → 0/3 (adopted); removing the fix
     restores 3/3.
   - ATP-starvation: 1/1 admitted (current) → 0/1 (adopted).
   The existing `case_relitigation` "new fingerprint" case has its polarity
   **corrected** — it is an expect-flip and today expects *admissible*; under
   the adopted rule it MUST expect *inadmissible*.
2. **A genuinely-new positive case** — and it must be a real one, because rev
   1's proposed positive case *was the ATP-starvation attack* (a term under
   an exhausting budget). The correct positive: a **different term reaching a
   different normal form** over the tunnel's evidence — that MUST stay
   admissible, so the rule is not "reject everything". (If identity choice
   (B) is adopted, add a second positive: a different term reaching the same
   result from *different* consumed evidence — admissible; and the wrapper
   `I T` reaching the same result from the *same* evidence — inadmissible.)
3. **A property-based test** over the field taxonomy: random claim-field and
   resource-field mutations over random settled stores assert T1/T2; random
   semantic-field mutations assert that *eligible* novelty is still reachable.
   Runs in `tools/check.py`.
4. **The `cmd@v1` control (MINOR-2):** no-new-evidence + flipped
   verdict/transcript stays inadmissible; then add new evidence and confirm
   §7(a) still admits — pinning the SA-1 resolution independently of the ski
   repair.
5. **Lean mechanization of the settlement calculus later** — tunnels,
   fingerprints (with the §3.2 eligibility predicate and the §3.3 identity),
   admissibility as functions; T1 and T2 as proved lemmas — following the
   sigma-glyph layering discipline. Adoption does not wait for it, and it must
   model the *adopted* rule, which is why this document comes first.

## 6. Mirror check (SYMMETRY)

One rule, two implementations, one test harness: the change lands in
`impl/warrant.py::fingerprint` (line 747) and `impl-go/main.go::fingerprint`
(line 1835) in the same commit, or in neither; `tests/settlement.py` drives
both and its expectations move in that same commit. `impl-rs` is base-grade
and unaffected (SA-6). The conformance pack's settlement vectors
(`verify-store-settlement.json`) exercise trust fail-closed only and are
unaffected; if a re-litigation vector class is ever added to the pack, it
must be added under the adopted rule, not the current one.

## 7. Open questions for the gate

1. **Computation identity (B) vs (C)** — §3.3. The load-bearing decision.
   Recommendation: (B), consumed-evidence + result, accepting the `eval_hash`
   instrumentation cost, because it is the only identity that *is* what §7(b)
   asks about. Fallback: (C), scope down and add a THREAT-MODEL residual row.
   Second gate round should attack whichever is chosen.
2. Is normal-form-only eligibility (§3.2) too strong — is there a legitimate
   settlement whose *consequence* genuinely is a DISSONANCE? Draft answer:
   no — a resource/unresolved/invalid outcome is a fact about budget, store
   or blob, never about the evidence; a claim like "term T does not terminate
   within budget B" is filer-steerable for any T and belongs to policy, not
   format novelty. The gate should try to exhibit a counterexample.
3. A `ski@v1` reason whose re-execution was *refused* (over local budget,
   §3.1): no fingerprint (it is not even eligible under §3.2, and §6(7)
   already escalates it at settlement grade). Distinct from a run that
   executed and exhausted — that one *ran*, and is excluded by eligibility,
   not by refusal.
4. Does dropping tunnel-side `cmd@v1` fingerprints re-open any *presently
   settled* question in the wild? Draft answer: the only stores known to use
   settlement are this repository's and sigma-glyph's, and neither settles on
   `cmd@v1` reasons; a migration scan (grep stored reasons by runtime) is a
   one-liner the gate should demand be run and recorded.
5. §13.1 already requires each runtime registration to declare its
   fingerprint tuple (MINOR-1, correct). The normative addition is therefore
   the **purity + eligibility constraint** on that declaration, not the
   requirement to declare one: a registration MUST show its tuple contains no
   claim field and its eligibility predicate excludes resource/unresolved/
   invalid outcomes, or it is refused.
