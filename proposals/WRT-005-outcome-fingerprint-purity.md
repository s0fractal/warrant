# WRT-005: Outcome-fingerprint purity — the expect-flip repair

**Identifier note.** This proposal is filed as **WRT-005**. **WRT-003 was this
design's earlier working name.** The number WRT-003 is not reused: it already
belongs to a closed, unrelated proposal (the verification-receipt work, PR
#20; WRT-004 is the closed verify-report work, PR #21). The live artifacts of
this design carry **only** WRT-005 — the proposal, the countervector
(`tests/fixtures/wrt005_gate_countervectors.py`), the Lean proof and its guard.
The name WRT-003 survives in exactly one place: the **preserved historical
reviews and their manifests**, left unrewritten because they are the record of
what was reviewed and when. Where those reviews say "WRT-003", they name this
same design under its old number.

**Status:** DRAFT rev 4 (2026-08-27) — **design only.** No SPEC edit, no code
change, no vector change is made by this document. Adoption requires an
adversarial gate and, on adoption, a SPEC document-version bump (this is a
consensus-behavior change: two verifiers at different revisions of §7 return
different admissibility verdicts over the same store). It carries **no claim of
adoption, implementation, or a proof of refinement** to the running verifier;
the Lean work below proves the rule's *algebra*, not that any implementation
computes it (§5).

**rev 4 (2026-08-27)** closes the third design gate — the first from a
different vendor (`reviews/2026-08-qwen-wrt-003-rev3-design-gate.md`, Qwen /
Alibaba, AMEND). Two of its eight findings were confirmed against the code;
one strong claim was declined with a reproduction; the rest are accepted as
honesty requirements the proposal was hiding. Changes:

- **Node-class eligibility was underspecified — root vs nested DISSONANCE
  (BLOCKER, confirmed).** A Book I normal form may be a *stuck application*
  whose root opcode is APPLY yet which contains a DISSONANCE subterm
  (reproduced: `(dis · K)` → root APPLY, and `(dis · K)` vs `(dis · I)` give
  distinct hashes — a fresh re-opener family under a root-only rule). rev 4
  fixes eligibility to **"the result normal form contains no DISSONANCE node
  anywhere"** (§3.2) — a recursive but still pure function of the result
  value, needing no execution provenance.
- **Identity (A) silently assumed evaluator determinism (MAJOR, accepted,
  reframed).** Result-only identity is sound only because ski@v1's evaluator
  is a *deterministic function* term→result (stronger than Church-Rosser
  confluence, and mechanized in Lean as `evalHash_settles`). Qwen framed it
  as an undocumented Church-Rosser dependency; the precise premise is
  determinism, which *is* proven for ski@v1 but is **not** guaranteed for a
  future runtime. rev 4 adds it as an explicit precondition and a registry
  gate (§3.6).
- **§7(b) is not empty, but its meaning under (A) must be stated (BLOCKER
  downgraded).** Qwen argued (A) makes §7(b) a dead letter for deterministic
  runtimes. Declined with a reproduction: a term reaching a *result-value
  absent from the tunnel* is admissible (settle `T→S`, file `T'→K` → admitted
  by both impls). What (A) forecloses is *restatement of a demonstrated
  value*; what it admits is *a newly demonstrated value*. §3.1 now states
  this and §5 pins it as the positive control.
- **SA-1 is closed by scope reduction, not repaired (MAJOR, accepted).**
  §3.4 and the paper now say so in those words.
- **Transition semantics were missing (MINOR, accepted).** New §8: the rule
  is retroactive by construction (fingerprints are computed, never stored)
  and strictly strengthens foreclosure, so it can only *keep more settled*,
  never mass-re-open.
- **The honest tradeoff (PROCESS, accepted).** New §9 states what (A) gave up:
  false-positive novelty is now impossible; false-negative novelty (two
  derivations of one value are indistinguishable) is guaranteed and
  deliberate.
- **check_claims overstated (MINOR, Qodo/Qwen, accepted)** — fixed in the
  paper's checker (reports verified AND unchecked, never "all verified").
- **Independence-class census (MAJOR meta, accepted)** — the paper now records
  that all gates are LLM-authored, cross-vendor but not cross-paradigm, with
  zero human-expert gates.

rev 3's core survives: identity is the result hash; `cmd@v1` contributes no
fingerprint; symmetric tunnel; doc-version bump; registry constraint.

**rev 3 (2026-08-27)** closes the second design gate
(`reviews/2026-08-gpt56sol-wrt-003-rev2-design-gate.md`, AMEND), which broke
rev 2's *recommended* identity (B) and out-argued its case against (A). Both
findings reproduced in `tests/fixtures/wrt005_gate_countervectors.py`:

- **(B) is paddable via REF aliases (BLOCKER, accepted).** `ski@v1` executes
  against the whole CAS, not `body.evidence`, so `REF(S)`, `REF(REF(S))`, …
  all reduce to the same result `S` while the "forced read-set" grows by one
  alias each level — an undeclared-CAS-path re-opener, the `I T` attack one
  layer down. Reproduced: same result `887045bc…`, spent 3 vs 6. (B) is
  **rejected**.
- **(A) is not dominated; §7(b) wording favors it (accepted).** rev 2 argued
  (A) over-forecloses "two derivations from different evidence reaching the
  same result". The gate showed this conflates *new derivation* with *new
  consequence*: if the evidence is already present and the result is the
  same, no new consequence was demonstrated — that is exactly why raw-term
  identity was wrong, and a consumed-read-set reintroduces derivation
  identity. rev 3 **adopts (A): `fingerprint = (runtime, result_node_hash)`**.
- **§3.2 eligibility disambiguated (accepted).** A materialized DISSONANCE
  node *is* a normal form in Book I, and a term that directly normalizes to
  `DISSONANCE(ATP Exhausted)` has the **same result hash** as a genuine
  exhaustion (reproduced: both `8bb0006f…`). "Only normal form" was
  ambiguous. rev 3 takes the **node-class rule** the gate preferred: a result
  whose node opcode is `DISSONANCE` (any reason) is ineligible **regardless
  of how it was reached** — a pure property of the result node, needing no
  execution-provenance channel and therefore no new consensus observable.

The result: identity and eligibility are now **both pure functions of the one
node the verifier already computes and hashes.** No read-set, no trace, no
new observable beyond the result hash. All four re-openers — expect-flip,
ATP-starvation, `I T` wrapper, REF-padding — collapse to one rule.

rev 2's other content (P1 purity, no `cmd@v1` fingerprint, symmetric tunnel,
field taxonomy, doc-version bump, registry constraint) survives; the gate
kept all of it.

**rev 2 (2026-08-27)** closes the first design gate
(`reviews/2026-08-annaglova-wrt-003-design-gate.md`, verdict AMEND), which
found two re-openers that survive rev 1 — both reproduced against both
implementations (`tests/fixtures/wrt005_gate_countervectors.py`):

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
  silently keep raw-term identity: §3.3 escalated the identity choice, and
  rev 3 (below) resolves it to result-only after the second gate.

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
yet carries only the filer's budget choice. P2 is what rules that out.

rev 3 collapses both properties into a single realization the second gate
forced: **the only thing that is neither filer-writable nor filer-steerable
is the result node the verifier itself computed and hashed.** Term syntax is
paddable (`I T`); the operational read-set is paddable (`REF(REF(S))`); the
budget is steerable (starvation). The result *value* is none of these — it is
a content-addressed fact. So identity is the result hash (§3.1) and
eligibility is a property of the result node (§3.2), and nothing else enters.
The current `ski@v1` tuple fails P1 in two members (`expect`, and the derived
`verdict`) and fails P2 (exhaustion outcomes are admitted); the current
`cmd@v1` tuple fails P1 in every member the verifier cannot check.

## 3. The repair

### 3.1 `ski@v1` — identity is the result (rev 3, adopts (A))

```
fingerprint = (runtime="ski@v1", result_node_hash)
    — contributed ONLY when result_node_hash is eligible (§3.2)
```

- `result_node_hash` is the sole computation-bearing member: what the
  verifier's own re-execution produced, a content-addressed value.
- **`term` is not a member.** The gate's `I T` (rev 2) and `REF(REF(S))`
  (rev 3) counter-vectors both reduce to the same result under a fresh
  term/read-set; putting any path identity — syntactic *or* operational — in
  the tuple lets a filer pad novelty without a new consequence. The result
  value is the consequence; the path is the filer's business.
- `expect` and `verdict` are dropped (`verdict = result == expect`, so either
  keeps the expect-flip).
- `atp` is absent and neutralized by §3.2: a budget change either leaves the
  result unchanged (non-exhausting runs of one computation share a result,
  Book I determinism, `size ≤ atp+1`) or produces a DISSONANCE, which is
  ineligible.

**Why not derivation identity.** §7 splits novelty into (a) new evidence and
(b) a new demonstrable *consequence* of evidence already present. A second
term reaching the *same* result over already-present evidence is a new
*derivation*, not a new consequence — and if it uses evidence *absent* from
the tunnel, §7(a) already admits it. So result-only identity is not a
convenience; it is what §7(b)'s own words denote. The clean invariant, from
the gate: **same eligible result ⇒ same §7(b) consequence, regardless of
syntax, aliases, evaluation path, or which already-present evidence subset
was used.** If "proven a different way" must itself count, the proof belongs
*inside* the result object so its NodeHash changes for a semantic reason —
never as the evaluator's operational trace.

**What §7(b) still admits (rev 4, against the "dead letter" objection).** The
third gate argued (A) empties §7(b) for a deterministic runtime. It does not.
§7(b) under (A) is precisely: *a check that reduces to an eligible
result-value not already demonstrated in the tunnel.* Settle a question with
`T → S`; a re-litigant files `T' → K` (a different computation over the same
present evidence, reaching a different value) — admissible, reproduced in
both implementations (`tests/fixtures/wrt005_gate_countervectors.py`, the
positive control). What is foreclosed is *restating a value already shown*;
what is admitted is *showing a value not yet shown*. §7(b) is not empty; it
is now exactly "a new demonstrated consequence" with the emphasis on
*demonstrated value*, not *derivation*. The honest corollary — that no
re-derivation of an already-shown value is novel — is §9.

### 3.2 Novelty-eligibility — DISSONANCE-free normal form (rev 4)

A result contributes a fingerprint **iff its result normal form contains no
`DISSONANCE` node anywhere** — not merely a non-DISSONANCE root. This is a
recursive but still pure function of the result value the verifier already
materialized; it needs no execution-provenance channel and adds no consensus
observable beyond the result bytes both implementations already hold.

**Why "anywhere", not "root" (rev 4, third gate).** rev 3 said "result node
opcode is not DISSONANCE", meaning the root. The third gate showed a Book I
normal form can be a *stuck application* — `(dis · K)` — whose root opcode is
APPLY while a DISSONANCE sits inside it. Reproduced: `(dis · K)` and
`(dis · I)` both normalize to root-APPLY terms with **distinct hashes**, so a
root-only rule would rule them eligible and hand a filer a fresh re-opener
family (REF-padding's shape, one structure deeper). The recursive rule closes
it. It is defensible on semantics, not only security: in Book I a DISSONANCE
node is exclusively the error/bottom object, so a normal form carrying one is
a *partial failure*, not a clean consequence of the evidence.

**Why not execution-origin.** rev 3 established, and rev 4 keeps, that a term
which directly normalizes to `DISSONANCE(ATP Exhausted)` has the same result
hash as a genuine exhaustion (reproduced: both `8bb0006f…`). Distinguishing
them would require `eval_hash` to emit a provenance channel both
implementations agree on byte-for-byte — a second observable, a second split
risk, exactly the operational-trace dependence this proposal rejects for
identity. Eligibility stays a pure function of the result value.

The DISSONANCE reasons all fail §7(b) for the same underlying cause — none is
a *consequence of the evidence*:

- **Exhausted** — a fact about the filer's budget, re-derivable for any
  terminating term by lowering `atp` (the ATP-starvation re-opener).
- **Unresolved Reference** — a fact about store completeness (NG-2).
- **Invalid** — a fact about a malformed blob.

A candidate whose every check re-runs to a DISSONANCE cites nothing new and is
inadmissible. **Predicate novelty** stays honest: a genuinely new question is
a computation reducing to a non-DISSONANCE result the verifier can hash; a
"question" that is only a different `expect`, a smaller budget, or a bottom
result demonstrates nothing. Novelty stays format; *which* eligible results
are relevant stays policy.

### 3.3 Computation identity — decided: result-only (rev 3)

This was rev 2's open question; two gate rounds have now closed it. The
candidates and their fates:

- **(A) result-only — ADOPTED.** `(runtime, result_node_hash)`. Matches
  §7(b)'s words (the consequence *is* the result), and closes every path
  attack because no path — syntactic or operational — is in the tuple. rev 2
  charged it with over-foreclosing independent derivations; the second gate
  answered that a new derivation over already-present evidence is not a new
  *consequence*, and a derivation over *absent* evidence is admitted by
  §7(a) — so the "over-foreclosure" is §7(b) doing its job.
- **(B) consumed-evidence + result — REJECTED.** rev 2 recommended it; the
  second gate broke it. `ski@v1` reads the whole CAS, not `body.evidence`, so
  `REF(S)` vs `REF(REF(S))` reach the same result with different forced
  read-sets, and the alias blobs need not be declared evidence — a fresh
  §7(b) fingerprint with no new consequence and no §7(a) trigger. It is the
  `I T` attack one layer down: path identity moved from syntax to operational
  trace. (B) also would have made an execution-trace property a consensus
  observable, needing its own cross-implementation semantic-read-set vectors
  — a split risk §13.1 exists to prevent.
- **(C) keep raw term, scope down — MOOT.** (A) closes the wrapper outright,
  so no residual needs documenting; (C) was only attractive as a fallback to
  (B)'s cost, and (A) has neither the cost nor the hole.

There is one honest consequence to name, not hide: (A) means a re-derivation
of an already-demonstrated result — however clever — is not settlement
novelty. That is intended. If a project wants "independently re-proven" to
carry weight, it makes the proof a **verified part of the result object** (so
the NodeHash differs for a semantic reason) or handles it in settlement
policy; the format layer measures consequences, and the same value is the
same consequence.

### 3.4 `cmd@v1` — SA-1 closed by scope reduction, not repaired

**`cmd@v1` reasons contribute no outcome fingerprint.** At settlement grade,
a `cmd@v1` reason can support §7(a) (new evidence) and nothing else; §7(b)
requires a runtime the verifier re-executes.

Stated honestly, at the third gate's insistence: **this closes SA-1 by
removing a surface, not by fixing it.** `cmd@v1` settlement novelty is now
evidence-gated only; computational-reconsequence novelty is unavailable for
opaque runtimes *by construction*. That is a narrowing of the protocol, and
`cmd@v1` is the reason kind most agent deployments actually use, so the honest
statement is "the most common reason class now has evidence-only settlement
novelty", not "SA-1 fixed". The alternative recorded in SA-1 — fingerprint
`= (runtime, sorted evidence, transcript)` — was considered and **rejected**:
a transcript blob is filer-fabricated at the cost of one write, so that tuple
is exactly as flippable as the current one, one level down. There is no pure
fingerprint for a computation the verifier cannot see; pretending otherwise is
how §7 got here. Of SA-1's two candidate repairs this proposal takes "novelty
requires re-execution", generalized to any future runtime via §5's registry
rule — and names the cost rather than burying it.

### 3.6 Precondition: the runtime is a deterministic function (rev 4)

Result-only identity is sound **only if the runtime's evaluation is a
deterministic function from term to result** — one term, one result value.
For `ski@v1` this holds and is not assumed: Book I's evaluator is
leftmost-outermost with a single result, mechanized in Lean as
`evalHash_settles` (a run ends on a configuration no further action fires).
This is stronger than Church-Rosser confluence (which the third gate named);
determinism gives uniqueness directly.

The precondition is **not** guaranteed for a future runtime. A non-confluent
or nondeterministic runtime would let semantically-equal results carry
different hashes (false novelty) or different semantics collide on one hash
(missed novelty). Therefore, as a registry rule (§5, §13.1): **a runtime
registration MUST certify that its evaluation is a deterministic function, or
it is ineligible for result-only fingerprints** and must declare a different,
purity-and-eligibility-respecting tuple. `ski@v1` carries this certificate in
the sibling repository's Lean mechanization; a runtime that cannot is refused.

### 3.5 Tunnel side, symmetrically

Tunnel fingerprints are computed by the same rule (they already are, in both
implementations — one function serves both sides). Consequences:

- A tunnel `ski@v1` reason blocks every later restatement reaching its
  result — regardless of the `expect` it was filed under, the term syntax, or
  the evaluation path — strictly *stronger* foreclosure than today, where an
  old reason's tuple collides only with a candidate matching its `expect` too.
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
- **Admissibility verdicts move.** All four re-opener families become
  inadmissible: the expect-flip (claim field, out of tuple), ATP-starvation
  (DISSONANCE result, ineligible §3.2), the `I T` wrapper and REF-padding
  (same result, same fingerprint), and `cmd@v1`-only re-litigations lacking
  new evidence (no fingerprint). A genuinely different result over the
  tunnel's evidence stays admissible — the rule forecloses restatement, not
  novelty.
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

**T1 (Purity).** For a fixed store, the fingerprint is invariant under every
mutation that does not change the result node — claim fields (`expect`,
verdict, transcript, packaging), term syntax (`I T`), operational path
(`REF(REF(S))`), and any non-exhausting budget. — Current §7: fails
(expect-flip). §3.1: holds by construction (only the result hash is in the
tuple).

**T2 (Eligibility).** A result contributes a fingerprint iff its normal form
contains no DISSONANCE node anywhere (§3.2, rev 4); a resource/unresolved/
invalid outcome, at the root or nested, never yields an eligible fingerprint.
— Current §7: fails (ATP starvation). §3.2: holds by construction.

**Precondition (rev 4).** T1's "does not change the result node ⇒ same
fingerprint" is sound only because the runtime is a deterministic function
(§3.6). For a non-deterministic runtime T1 is false; the registry gate refuses
result-only fingerprints for such a runtime.

Under (A) with §3.6, T1 and T2 give the one-line invariant: **the fingerprint
is a function of the eligible, DISSONANCE-free result value and nothing else.**

Adoption gate MUST include, in order of strength:

1. **All negative controls**, from
   `tests/fixtures/wrt005_gate_countervectors.py`, wired into
   `tests/settlement.py` — each flips admitted (current) → inadmissible
   (adopted), and restores when the fix is removed:
   - expect-flip (claim field);
   - ATP-starvation (DISSONANCE-bearing result);
   - `I T` wrapper (same result);
   - REF-padding `REF(S)` → `REF(REF(S))`, same evidence, same result;
   - direct-DISSONANCE-node vs genuine-exhaustion: **both** ineligible;
   - **nested DISSONANCE** `(dis · K)` vs `(dis · I)`: both ineligible under
     the "anywhere" rule (§3.2, rev 4) — pins root-vs-nested.
   The existing `case_relitigation` "new fingerprint" case has its polarity
   **corrected** — it is an expect-flip and today expects *admissible*.
2. **A genuinely-new positive** (reproduced, `positive.json` in the fixture):
   settle `T → S`, file `T' → K` — a **different clean result** over the
   tunnel's evidence — MUST stay admissible, so §7(b) is not emptied and the
   rule is not "reject everything". (Not rev 1's proposed positive, which was
   the ATP-starvation attack.)
3. **A property-based test:** random claim/term/path/non-exhausting-budget
   mutations over random settled stores assert T1; random
   different-result mutations assert eligible novelty is still reachable.
   Runs in `tools/check.py`.
4. **The `cmd@v1` control:** no-new-evidence + flipped verdict/transcript
   stays inadmissible; adding new evidence re-admits via §7(a).
5. **Lean mechanization — DONE for the fingerprint AND admissibility layers**
   (`proofs/Settlement.lean`, guarded by `proofs/check_settlement.py`). Eleven
   theorems, sound axiom cone (`{propext}` for the fingerprint algebra,
   `{propext, Quot.sound}` for admissibility; sorry / axiom / native_decide
   denylisted). T1 (purity) and T2 (eligibility) are proved:
   `fp_ignores_claims` (expect-flip), `fp_factors_through_result` (`I·T` /
   REF-padding), `dissonance_ineligible` + `fp_none_of_dissonance`
   (ATP-starvation), `nested_dissonance_ineligible` (nested-DISSONANCE),
   `atp_cannot_steer` (conditional on Book I budget-stability, cited not
   re-derived). And the **money theorems** at the §7 admissibility level:
   `restatement_inadmissible` — a candidate with no new evidence and no new
   eligible fingerprint cannot re-open a settled matter (every attack family is
   an instance); `dissonance_candidate_inadmissible`; and
   `novel_result_admissible` — a genuinely new eligible result *is* admissible,
   so §7(b) is not empty. What remains: the transitive-closure computation of
   the tunnel from the prior-DAG (a standard graph closure, orthogonal to the
   admissibility algebra and taken as input here), and a proof that the running
   Python/Go code implements this rule — the standing
   implementation-independence gap. The mechanization models the *rev-4* rule,
   so it tracks the proposal rather than pre-empting the gate.

## 6. Mirror check (SYMMETRY)

One rule, two implementations, one test harness: the change lands in
`impl/warrant.py::fingerprint` (line 747) and `impl-go/main.go::fingerprint`
(line 1835) in the same commit, or in neither; `tests/settlement.py` drives
both and its expectations move in that same commit. `impl-rs` is base-grade
and unaffected (SA-6). The conformance pack's settlement vectors
(`verify-store-settlement.json`) exercise trust fail-closed only and are
unaffected; if a re-litigation vector class is ever added to the pack, it
must be added under the adopted rule, not the current one.

## 7. Open questions for the next gate round

The identity question (rev 2's headline) is now closed to (A); what remains:

1. **Is result-only (A) ever too strong for a *future* runtime?** For a closed
   ski term the result is the whole consequence, so (A) is exact. A future
   runtime whose computation genuinely consumes `body.evidence` as a
   capability (unlike ski) might have a consequence that is "(inputs, output)"
   rather than "output". §5's registry rule already lets each runtime declare
   its own tuple under the purity+eligibility constraint — the open question
   is whether the *constraint* should forbid path/read-set members outright
   (rev 3's position, since they are paddable) or permit a **declared-input
   capability** member that is closed under content-addressing. The gate
   should pressure-test a runtime design, not just ski.
2. **Does the node-class rule (§3.2) mis-classify any legitimate consequence?**
   It rejects every DISSONANCE result. Try to exhibit a settlement whose
   honest consequence *is* a bottom — e.g. "this adversarial term does not
   normalize within the canonical budget". Draft answer: that is a statement
   about the budget, filer-steerable for any term, and belongs to policy; but
   the gate should try to break it.
3. Does dropping tunnel-side `cmd@v1` fingerprints re-open any *presently
   settled* question in the wild? The only stores known to use settlement are
   this repository's and sigma-glyph's, and neither settles on `cmd@v1`
   reasons; a migration scan (grep stored reasons by runtime) is a one-liner
   the gate should demand be run and recorded before adoption.
4. §13.1 already requires each runtime registration to declare its fingerprint
   tuple. The normative addition is the **purity + eligibility constraint** on
   that declaration: a registration MUST show its tuple contains no
   filer-writable and no operational-path member, and its eligibility
   predicate excludes resource/unresolved/invalid outcomes, or it is refused.

## 8. Transition — what happens to already-settled tunnels (rev 4)

The third gate observed, correctly, that a format whose pitch is *"the 'no,
because' survives so the same argument is not re-had"* must say what a change
to the novelty rule does to matters already settled. It does, and the answer
is benign by construction:

- **Fingerprints are computed at verification time, never stored** (§4). A
  verifier at the new SPEC version recomputes every tunnel and candidate
  fingerprint under the new rule; there is no stored fingerprint to migrate,
  and no WarrantID, signature, or blob changes.
- **The new rule strictly strengthens foreclosure.** Result-only identity
  collapses more candidates onto one fingerprint than the old
  `expect`-bearing tuple did, and DISSONANCE-free eligibility removes
  fingerprints the old rule admitted. So for any tunnel, the set of
  admissible re-litigations under the new rule is a **subset** of the set
  under the old rule.
- **Therefore the change can only keep more matters settled, never
  mass-re-open one.** A question foreclosed under the old rule stays
  foreclosed; some re-litigations that *were* admissible become inadmissible.
  A settlement format's safe direction is exactly this one.
- **The one thing to check before adoption** (already gate criterion, §7.3):
  a migration scan of existing stores confirming none relied on an
  old-rule-only admission to reach a *desired* settlement — i.e. that no
  legitimately-settled state depended on a re-litigation the new rule would
  now reject. For this repository and sigma-glyph the scan is a one-liner and
  the expected result is "none", because neither store settles on `cmd@v1`
  and neither has filed an expect-flip or starvation re-litigation.

The transition is a flag day at the SPEC-document-version boundary (as v0.4's
signature change was), not a dual-rule window: a verifier applies exactly one
§7 revision, and two verifiers at different revisions disagree by design.

## 9. The honest tradeoff — what (A) gives up (rev 4)

The third gate named a structural fact the earlier revisions had left
implicit, and it belongs in the open where the next reader meets it. Every
fingerprint defined *syntactically or operationally* loses a race against a
notion of novelty that is *semantic*: each round found a padding one layer
down (expect → atp → `I T` → REF → nested DISSONANCE). rev 3–4 stop the
regress by choosing the **coarsest defensible identity — the result value
itself** — and the honest theorem is not "we removed filer-writable fields"
but:

> We deliberately chose an identity coarser than semantic equivalence.
> **False-positive novelty is now impossible** — no filer-steerable field,
> path, or budget can manufacture a new fingerprint. **False-negative novelty
> is guaranteed and intended** — any two computations reaching the same
> eligible value are one consequence, so a genuinely independent
> re-derivation of an already-demonstrated result is not settlement novelty.

The second half is a real loss, not a rounding error: a system that wants
"independently re-proven" to carry weight cannot get it from §7(b) under this
rule. The escape hatch is deliberate and stated once more here: make the
proof a **verified part of the result object** (so its NodeHash differs for a
semantic reason), or handle re-proof significance in settlement policy, which
is where relevance already lives. The format layer measures *what was
concluded*, not *how many ways it was reached* — and now says so.

This is also why the next gate should not be another LLM. The regress is
closed against syntactic and operational padding; what remains is a question
about *semantics* (is result-value the right notion of consequence? does
DISSONANCE-free eligibility mis-classify any honest bottom?) and about
*proof* (are T1/T2 theorems or only property tests?). Those want a human
logician and a Lean mechanization of the settlement calculus, not a fourth
model round — see the response's recommendation.
