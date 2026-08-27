# WRT-003: Outcome-fingerprint purity — the expect-flip repair

**Status:** DRAFT rev 1 (2026-08-27) — **design only.** No SPEC edit, no code
change, no vector change is made by this document. Adoption requires an
adversarial gate and, on adoption, a SPEC document-version bump (this is a
consensus-behavior change: two verifiers at different revisions of §7 return
different admissibility verdicts over the same store).

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

> **An outcome fingerprint MUST be a function of the computation the
> verifier itself performed and the content-addressed inputs that
> computation consumed — and of nothing else.** No field a filer writes and
> the verifier does not recompute may enter the tuple.

Call this **fingerprint purity**. The current `ski@v1` tuple fails it in two
members (`expect`, and `verdict`, which is derived from `expect`); the
current `cmd@v1` tuple fails it in every member the verifier cannot check.

## 3. The repair

### 3.1 `ski@v1`

```
fingerprint = (runtime="ski@v1", term, result_node_hash)
```

- `term` is the content-addressed computation; `result_node_hash` is what the
  verifier's own re-execution produced. Both are outside the filer's reach.
- `expect` and `verdict` are dropped. `verdict` is `result == expect`, so
  keeping either keeps the flip.
- `atp` is deliberately absent as a *member* but present in effect: a budget
  change that changes the outcome changes `result_node_hash` (ATP-exhaustion
  outcomes are DISSONANCE nodes with fixed hashes, SPEC §3.1), and a budget
  change that does not change the outcome demonstrated nothing new.

**The predicate-novelty question, answered.** The reviewer asked where "a
genuinely new question about an old result" goes if `expect` leaves the
tuple. Answer: into the computation. A predicate that is real computation is
a new `term` (the predicate applied to its inputs), which re-runs to its own
`result_node_hash` and fingerprints as new — legitimately, because the
verifier ran it. A predicate expressed only as a different `expect` constant
is not computation, demonstrates nothing, and is exactly what purity
excludes. Novelty stays format; *which* new terms are relevant stays policy.
This draws the "novelty is format; relevance is policy" boundary one notch
more honestly than §7 currently does.

### 3.2 `cmd@v1`

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

### 3.3 Tunnel side, symmetrically

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
  inadmissible. Restatements under different `expect`/`atp`-with-same-result:
  already inadmissible, remain so, now for a reason the tuple states
  directly. `cmd@v1`-only re-litigations lacking new evidence: admissible
  today (write a different word) → inadmissible.
- **Consensus versioning.** Verifiers at old-§7 and new-§7 disagree on
  `settle` verdicts by design; per the §5-line design rule this ships as a
  SPEC document-version bump with both reference implementations moving in
  the same release, mirroring how v0.4 shipped the signature flag-day.
- **What purity does not buy:** relevance. A filer can still manufacture
  unbounded *genuinely new* computations (fresh terms) that are irrelevant
  to the settled subject. That bound stays where §7 already puts it — the
  active settlement policy — and this proposal does not touch it.

## 5. Acceptance criterion — the invariant, stated to be checked

**Theorem (fingerprint purity).** For a fixed store and a fixed check
computation, the outcome fingerprint is invariant under every change of
filer-chosen fields — `expect`, claimed `verdict`, and (for the tunnel side)
the `because` packaging around the check.

- Current §7: **fails** (the reproduction is the counterexample).
- §3.1 above: **holds by construction** — no filer-writable field appears in
  the tuple.

Adoption gate for this proposal MUST include, in order of strength:

1. **The reproduction as negative control.** The expect-flip script (three
   fresh-`expect` candidates against a settled ski question) flips from
   3/3 admitted to 0/3 admitted in *both* implementations; removing the fix
   restores 3/3. Wired into `tests/settlement.py` with the polarity of its
   "new fingerprint" case corrected and a *new* positive case added (a
   genuinely different term — e.g. the same term under a budget that
   exhausts, whose DISSONANCE result hash differs) so that admissibility is
   pinned from both sides and the rule cannot be "fixed" into rejecting
   everything.
2. **A property-based purity test now:** random `expect` mutations over
   random settled stores; assert fingerprint equality. Runs in
   `tools/check.py` like every other claim.
3. **Lean mechanization of the settlement calculus later** — tunnels,
   fingerprints, admissibility as functions; purity as a proved lemma —
   following the sigma-glyph layering discipline. That is tracked as its own
   work item; this proposal's adoption does not wait for it, and the
   mechanization must model the *adopted* rule, which is why this document
   comes first.

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

1. Should a `ski@v1` reason whose re-execution was *refused* (over-budget,
   §3.1) contribute a fingerprint? Draft answer: no — purity requires the
   verifier to have run it; an unverified reason demonstrates nothing, and
   §6(7) already escalates it at settlement grade. The gate should try to
   break this.
2. Does dropping tunnel-side `cmd@v1` fingerprints re-open any *presently
   settled* question in the wild? Draft answer: the only stores known to use
   settlement are this repository's and sigma-glyph's, and neither settles
   on `cmd@v1` reasons; a migration scan (grep stored reasons by runtime)
   is a one-liner the gate should demand be run and recorded.
3. Is `(runtime, term, result)` the right arity for future runtimes, or
   should §13.1's registration template make the fingerprint tuple a
   required, per-runtime declaration constrained by the purity rule? Draft
   answer: the latter — purity becomes a registry-level MUST, so `ski@v2`
   or a wasm runtime cannot re-introduce a filer field without failing
   registration.
