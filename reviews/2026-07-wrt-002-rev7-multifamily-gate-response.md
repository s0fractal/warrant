# Adjudication: WRT-002 rev 7 — three-family adversarial gate

**Status: analysis by an assisting agent (Claude), not a governance adoption.**
Under `AGENTS.md` §2 an agent cannot grant review or roster authority, and under
§4 the provenance has to say exactly what was and was not established. This
document records what three non-Codex reviewers produced, which of their claims
survived execution, which survived *scrutiny* — a different and stricter thing —
and what changed in the design as a result. The maintainer's acceptance is a
separate act that has not happened.

## Why this gate exists

Every gate on WRT-002 rev 1→6, and on ADR-008 rev 3→15, was Codex. One family,
iterated, converges on that family's blind spot; the project's own Decision
Process asks for ≥3 independent families. The reviewers here are
`moonshotai/kimi-k3`, `google/gemini-3.1-pro-preview` and `deepseek/deepseek-v4-pro`,
driven by `tools/adversarial_gate.py`: each emits counter-vectors as executable
Python, the harness runs them against a throwaway copy of
`proposals/wrt-002-model/`, and feeds back the verbatim transcript before asking
for a revision. A reviewer's confidence decides nothing; execution does. (One
caveat about *which* copy Kimi's blocks met is stated in full below, rather than
in a footnote — it is the kind of thing a gate must not let itself hide.)

## Outcome in one line

**Nine reproduced defects. Six closed here; four left open on purpose, including
one that defeats the design's headline property.** rev 7 passed 29 green checks
and six Codex gates while every one of these was reachable.

| id | source | severity | status |
|---|---|---|---|
| resolver-scope escalation | Gemini F1 | **P0** | **fixed** (§D.2b, `[resolver-scope]`) |
| policy abdication `(∅,0)` | mine, from Kimi's scrap | **P0** | **fixed** (§5.5, `[policy-wf]`) |
| policy bricking `min_sigs>\|actors\|` | same | **P0** | **fixed** (same) |
| CONFLICT marker binds as a key | Kimi F1 | **P0** | **fixed** (`[binding]`) |
| absent key binds (`None == None`) | Kimi F2 | **P0** | **fixed** (`[binding]`) |
| checkpoint verdict flips retroactively | Kimi F6 | P1 | **fixed** (`[checkpoint-scope]`) |
| witnesses bound to no state | Kimi F8 | P2 | **fixed** (same) |
| actor and filing witness detached | Kimi F9 | P2 | **fixed** (`[binding]`) |
| duplicate `(J,sequence)` CIDs | Kimi F10 | P2 | no longer reproduces after the above |
| **dead branch censors a root permanently** | **Kimi F3** | **P0** | **OPEN** |
| dead branch admits an unauthorized root | Kimi F4 | P1 | **OPEN** |
| `selected_lineage` non-monotone in the cut | Kimi F5 | P1 | **OPEN** |
| competing resolvers brick the jurisdiction | Kimi F7 | P1 | **OPEN** |
| "cut omission is censorship" | DeepSeek F1 | P0 claimed | **rejected** — compares two different cuts |
| "conflict is a permanent deadlock" | DeepSeek F2 | P0 claimed | **refuted by execution** |
| self-resolution deadlock | Gemini F2 | P1 claimed | **refuted as designed** |
| SELF cannot reverse RP | Gemini F3 | P1 claimed | **refuted as designed** |

Three reviewers, three **REJECT** verdicts. Two of them were not supported by
their own evidence. The third — Kimi's — is, and it is the one that matters.

### Two things about this gate that must not be smoothed over

**1. Kimi's reproductions executed against a model I had already modified.** Its
run was still in round 1 when I landed the rev-8 resolver-scope and
well-formedness fixes in the working tree; the harness copies the model at
*execution* time, so its round-2 blocks ran against rev 8 while its prompt held
rev 7. The review's own words — "against a pristine `model.py`" — are therefore
wrong, and that is a defect in how I sequenced the work, not in the review.

I did not leave it as a caveat. I re-ran all ten blocks against both revisions,
in isolation: **nine reproduce identically on rev 7 and rev 8.** Only F7 differs,
and only in one assertion — rev 7 accepted a resolver-of-resolvers as `valid_cap`
where rev 8 refuses it. So I extracted F7's *substance* and ran it separately on
both: two competing resolvers brick the jurisdiction in rev 7 exactly as in
rev 8, and the rev-7 resolver-of-resolvers was `valid_cap` yet equally impotent.
**My fix did not cause the deadlock; it removed a record that was valid and
useless.** The confound changes nothing about the findings, but nobody should
have to take that on trust — the check is three commands and it is written down
here because it would have been easy to omit.

**2. The best reviewer of the three did not follow the protocol on its first
run**, hit the token ceiling, and produced 94 KB of raw reasoning with no review.
Had I accepted "0 reproductions" as its answer, the P0 that binds a conflicted
key slot open would still be in the design. The harness had two defects that
caused this (metadata inside the block instead of on the fence line; an empty
round becoming the review body) — both are fixed, and both are worth remembering
as *gate* failures rather than reviewer failures.

---

## F1 (Gemini) — resolver-scope escalation. CONFIRMED, P0.

**The claim.** A resolver only has to satisfy `maxima ⊆ resolves`, and the
"greatest common causal-predecessor" authorizing it is folded over `resolves`.
So a filer can pad `resolves` with an unrelated record anchored near genesis,
dragging the fold back to a policy-state under which it still held authority.

**Reproduced, then re-run by hand.** In the transcript an actor `Q`, *already
removed from the governing policy by a valid succession*, padded `resolves` with
one ordinary record of its own and thereby seized the resolution of `User`'s key
conflict, setting `User`'s key to a value `Q` chose. I re-ran the block outside
the harness against an untouched copy: same result, exit 0. The assertions are
the right ones — the repro checks that the removing succession is itself valid
and that `Q` is genuinely out of the current policy before showing the seizure.
This is not an artifact of a contrived world; it is the algebra.

**Why it is P0.** It is a capability-escalation path from *revoked* to *governing*
that needs no key compromise, no quorum collusion, and no race. The victim is a
third party. §5.5's own words say the resolver is authorized by the policy "those
forks share" — so the model was not even implementing the spec's intent; the
spec's `⊆` merely failed to forbid the deviation.

**Fix (rev 8).** `resolves` must equal the maxima at the resolver's own
pre-state, every member must be a transition of the same slot (same target actor
for a key slot) in the same jurisdiction, and the pre-conflict fold runs over the
maxima rather than over `resolves`. Fail closed on every mismatch. §D.2b and §5.5
updated. Vectors `[resolver-scope]` pin: the ordinary-record padding fails; a
subtler padding with a *real* rotation from another actor's slot also fails; and
the honest resolver still resolves, because a fix that only deadlocks is not a
fix.

## Policy well-formedness — CONFIRMED, P0. Not from a reviewer's finding.

Kimi's run hit the token ceiling and produced no final review, but its discarded
reasoning contained the line *"new_policy = (frozenset(), 0) → then an adoption
with EMPTY threshold is valid"*. It never built the vector. I did, and it holds:

* **Abdication.** One valid `policy-succession` to `(∅, 0)` makes every threshold
  check pass vacuously. A stranger with **no witnesses at all** then adopts their
  own root into the jurisdiction. Verified: `valid_cap(D) = True`,
  `admits = {B, g}`.
* **Bricking.** One valid succession to `min_sigs > |actors|` makes the
  jurisdiction unable to authorize anything again — *including the succession
  that would undo it*. Verified: the recovery succession is `valid_cap = False`.
  This is precisely the liveness self-destruct class the brief warned had killed
  a predecessor of rev 6, and it was still reachable.

**Fix (rev 8).** A governing policy is usable iff `actors ≠ ∅ ∧ 1 ≤ min_sigs ≤
|actors|`; an ill-formed policy authorizes nothing, and a succession or
resolution *into* one is refused at filing time rather than discovered later as a
jurisdiction that has gone quiet. Vectors `[policy-wf]` pin both attacks, the
stranger's root staying unadmitted, and — the check that matters most — that a
well-formed succession still works and the jurisdiction can still legislate
afterwards.

I am flagging the provenance explicitly: this one is not a reviewer's finding.
It came from a reviewer's *scrap*, and the reviewer neither claimed it nor
demonstrated it. Recording it as Kimi's finding would be exactly the kind of
inflation `AGENTS.md` §4 exists to prevent.

---

## What did not survive

**DeepSeek F1 — "cut omission is a censorship primitive." Rejected.** The
reproduction builds one world, evaluates it under the full cut and again under a
cut that omits the supersede, and observes different answers. That is what a cut
*is*: §D defines effectiveness as of a fixed historical cut, and evaluating a
different cut asks a different question. The brief asked something narrower and
harder — whether an omission by the governing quorum stays *visible and
attributable*, frontier completeness being an acknowledged quorum claim rather
than a mechanical property. The reproduction does not test visibility at all; it
asserts "no verifier can distinguish" in a comment and prints `VIOLATION`. The
harness ran it, which is exactly why the gap between what ran and what was
claimed is legible. Filed as a **question**, unchanged from where the brief left
it.

**DeepSeek F2 — "policy conflict permanently blocks emergency rotation."
Refuted by execution.** The transcript shows a rotation refused while the policy
is conflicted, which is the intended fail-closed behaviour. The claim attached to
it — that this "cannot be unwound without a previously appointed resolver" — is
false, and §5.5 already says so. I built the missing step: a `policy-resolution`
naming both forks, authorized by the greatest common predecessor policy (here the
pinned anchor, which necessarily exists), and re-ran it:

```
conflicted, no resolver          : valid_cap(rot) = False
after policy-conflict-resolution : valid_cap(res) = True   effective(res) = True
                                   valid_cap(rot) = True   effective(rot) = True
```

The recovery path exists and works. No resolver need be appointed in advance.

**Gemini F2 — "a user's key fork is a permanent lockout requiring quorum
rescue." Refuted as designed, with a reason worth writing down.** It is true that
`key-resolution` is authorized by jurisdiction policy and not by the affected
actor, and the §D.4 matrix says so deliberately. But the stronger point is that
self-resolution is not merely disallowed, it is *structurally impossible and must
be*: during a key conflict the slot holds `CONFLICT`, so no key is bound to that
actor, so there is no "self" left to authorize with. And that is the safe
behaviour — a key fork is indistinguishable from a compromise in which an
attacker rotated a stolen key, so permitting the holder of either fork to settle
it would hand the account to whoever raced faster. The fail-closed default is
load-bearing here rather than incidental. Gemini's own Questions section asked
whether this was intentional; the answer is yes, and §D should state the reason
rather than leaving it to be re-derived by every reviewer.

**Gemini F3 — "SELF cannot reverse RP breaks self-rollback." Refuted as
designed**, same class: the §D.4 matrix pins it, and permitting it would let an
actor undo a governance-authorized action on their own key slot.

## Refuted attacks worth recording

Both reviewers attacked the rev-6 defect directly and both failed, independently:
Gemini tried to rebuild the `{A} → {A,B} → {A}` non-monotone loop through nested
root adoptions crossed with revocation chains, and reports that Layer 2a's
reliance on `valid_cap` distances shields `admits` from lifecycle volatility.
DeepSeek reports the same for the revocation vector, root-oscillation
termination, checkpoint CID determinism, and the quorum-rollback rejection. Two
families, no access to each other's work, both unable to reopen the cycle. That
is worth more than either REJECT verdict.

## The four that stay open, and why they are not patched

Kimi's F3, F4, F5 and F7 share one root: **Layer 2a consumes Layer 1's
permanence without Layer 2b's gate.** `_compute_admits` and `dist()` read
`valid_cap` only — which is precisely the property that bought rev 7 its
freedom from the rev-6 `effective ↔ effective` cycle. The consequence is that a
policy branch a resolver *rejected* still carries authority into root admission:

* **F3 (P0)** a supersede authorized solely under the dead branch — one that
  never even descends its target — reverses an adoption, and revoking the
  censor plus re-adopting cannot restore it. A dead branch **permanently
  censors a root and every record on it.** WRT-002 exists to remove exactly
  this primitive; here it is, laundered through rejected governance.
* **F4 (P1)** the dual: the dead branch admits a root the selected governance
  never adopted.
* **F5 (P1)** gating is non-monotone in the cut — once a later succession
  descends the resolver, both forks re-enter the lineage.
* **F7 (P1)** two honest quorums resolving one fork differently brick the slot
  forever; a later unanimous re-resolution is `valid_cap` yet impotent.

Each has an obvious-looking local patch, and each local patch reaches straight
back into the layering that keeps the machine well-founded. Fixing them one at a
time tonight is how rev 6 was born. They are the rev-9 agenda, and **until F3 is
closed the design does not deliver its own headline property** — which is the
honest reason not to advance this proposal.

## Coverage — what nobody examined

No reviewer attacked the **total manifest's `ineligible` entries** — the
quorum-authorized negative historical claim that the brief calls the softest
joint in the design. DeepSeek said so explicitly and filed it as out of scope
because the model has no `ineligible` mechanism to attack. That is a real hole in
this gate: the softest joint is untested because the executable model does not
implement it. Nor did anyone test the **WRT-001/ADR-008 interface** (does §D's
checkpoint actually supply what WRT-001 §6 assumes), or checkpoint `CID`
collisions under signature permutation. Those are the assignments for the next
round, and they should go to a family that has not seen this one.

## State after this gate

`vectors.py` is **53 checks, ALL PASS, up from 29**. Every addition is an attack
that worked against rev 7, not a restatement of the design.

This gate is **necessary and not sufficient**, and its result is mostly evidence
about the *process*: nine reproduced defects — five of them P0 — in an algebra
six consecutive gates had signed off on. Single-family review had been
converging, not verifying.

**Recommendation: do not adopt.** Not because the fixes are unsound, but because
F3 is open and F3 is the property the proposal exists to provide. rev 9 should
take the Layer-2a/2b composition as one problem, and the manifest joint below
should go to a fourth family that has not seen this round.

---

*Reviews: `2026-07-gemini31pro-wrt-002-rev7-adversarial-gate.md`,
`2026-07-deepseek-v4-wrt-002-rev7-adversarial-gate.md`,
`2026-07-kimi-k3-wrt-002-rev7-adversarial-gate.md`. Each carries its machine-run
transcripts as an appendix; every claim above can be re-run from them.*
