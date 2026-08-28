# annaglova — WRT-003 rev 1 adversarial design gate

**Date:** 2026-08-27
**Reviewer label:** `annaglova` (GitHub identity; the operator notes the
review was produced with ChatGPT and posted under this account — so the
vendor is OpenAI and the label is a human account name, not a model family.
Recorded distinctly from `chatgpt-web` because the census counts labels and
these are different accounts; the manifest carries the vendor.)
**Target:** `proposals/WRT-003-outcome-fingerprint-purity.md` rev 1 (`c93716b`).
**Genre:** adversarial design gate — a typed review with a verdict, against a
DRAFT proposal. This is the acceptance-oracle role WRT-003 §5 asked for.
**Verdict as given:** AMEND.
**Posted at:** PR #30 review 5037405426.
**Response:** [`2026-08-annaglova-wrt-003-design-gate-response.md`](2026-08-annaglova-wrt-003-design-gate-response.md)

---

Verbatim (GitHub review body):

## WRT-003 adversarial design gate

**Verdict: AMEND**

The core direction is right: `expect` and claimed `verdict` do not belong in a
settlement novelty fingerprint, and excluding `cmd@v1` from §7(b) is the
cleanest resolution of SA-1. But rev 1 does not yet establish the stronger
property it claims. I found two independent re-opener families that survive the
repair, one of which the proposal currently blesses as its positive control.

### BLOCKER — ATP starvation is still a filer-controlled re-opener

§3.1 deliberately omits `atp` from the tuple but says a budget change that
changes the result should create a new fingerprint, and §5 explicitly proposes
the same term under an exhausting budget as the positive novelty case.

That preserves the same attack shape one field over:

1. Tunnel contains `T` evaluated with enough ATP, producing ordinary result `R`.
2. Re-litigant files the **same `T`**, same old evidence, but chooses an
   artificially low *still locally executable* `atp`.
3. The verifier really runs it and obtains canonical ATP-exhaustion DISSONANCE `D`.
4. Proposed fingerprint changes from `(ski@v1,T,R)` to `(ski@v1,T,D)` and §7(b)
   admits it.
5. Repeat at distinct operational boundaries / terms as needed. No new evidence
   and no new semantic consequence of the evidence was demonstrated; the filer
   only starved the computation.

This is distinct from open question 1. It is **not** the verifier refusing an
over-local-limit check. `run_ski_check` accepts every declared budget at or
below the local cap and passes that filer-chosen value directly to `eval_hash`;
the execution therefore succeeds as an execution and returns the
resource-exhaustion node.

The proposed purity theorem still passes, because the verifier genuinely
computed `D`. That shows the theorem is insufficient for the settlement
property: "verifier-computed" does not imply "not filer-steerable".

**Required gate counter-vector:** settle a term at sufficient budget; submit the
identical term with a deliberately insufficient but locally permitted budget.
Under the intended repair this should not acquire §7(b) novelty merely because
the execution was resource-starved.

Possible repair directions: make resource-exhaustion/refusal outcomes ineligible
for settlement fingerprints; have each runtime registration declare which result
classes are novelty-eligible; or define a settlement execution budget
independently of the filer's presentation. Whichever is chosen, the acceptance
property needs to cover `atp`, not only `expect`/claimed verdict/packaging.

### MAJOR — raw `term` identity makes semantic no-op wrappers endlessly novel

The new tuple uses the raw term hash as computation identity. Therefore a tunnel
containing `T -> R` does not block `I T -> R`, `I (I T) -> R`, etc. Each wrapper
has a fresh term hash, re-runs honestly, and produces the same substantive
consequence. Every one is fingerprint-distinct.

This is not well described as merely the existing "novelty vs relevance"
residual. These candidates are maximally relevant — they are the same
computation/result padded by a semantic identity — so a topical relevance policy
cannot distinguish the attack without itself inventing a semantic-equivalence
rule.

The proposal should either:

- define/derive a stronger computation identity than raw syntax, or
- explicitly scope the guarantee down: WRT-003 removes *unverified-field flips*,
  but does not prevent semantically equivalent fresh-term restatements from
  satisfying §7(b), and record that residual in the threat model.

At minimum, add this counter-vector to the gate so the choice is deliberate
rather than hidden by the phrase "fresh terms".

### MAJOR — strengthen the invariant and property test

The stated theorem only mutates `expect`, claimed `verdict`, and `because`
packaging. That proves the narrow defect is gone, but misses filer-controlled
execution parameters that can steer the verifier's own output. The property
suite should classify runtime inputs into at least: semantic computation inputs,
claim/presentation fields, resource/control fields. Then state what mutations in
each class are allowed to create settlement novelty. Otherwise "purity" can be
true while the reopening attack remains true as well.

### MINOR — §13.1 already requires a per-runtime fingerprint tuple

Open question 3 asks whether §13.1 should make the fingerprint tuple a required
per-runtime declaration. It already does: a runtime registration MUST supply
"the exact outcome-fingerprint tuple for §7 novelty". The new normative addition
is the purity / novelty-eligibility constraint on that declaration, not the
requirement to declare a tuple.

### MINOR — pin the `cmd@v1` behavior change with its own negative control

This proposal deliberately resolves SA-1 by making `cmd@v1` incapable of §7(b)
novelty, but the adoption gate only specifies the `ski@v1` expect-flip
reproduction. Add a regression where a tunnel and candidate have no new evidence
and the candidate changes `cmd@v1` verdict/transcript: it must remain
inadmissible; then add new evidence and prove §7(a) still admits it. That pins
the chosen SA-1 resolution independently of the ski repair.

### What I would keep unchanged

- Drop `expect` and re-run/claimed verdict from the ski fingerprint.
- No `cmd@v1` outcome fingerprint at settlement grade.
- Symmetric tunnel/candidate computation.
- Document-version bump + Python/Go lockstep implementation.
- Registry-level constraint for future runtimes.

The design is close, but the acceptance criterion currently tests the exact ATP
behavior I think must be rejected. Fix that first; then the remaining question is
whether semantic-equivalent term wrapping is accepted as an explicit residual or
solved at the format layer.
