# Response — annaglova WRT-003 rev 1 design gate

**Date:** 2026-08-27. Adjudicated by the maintainer model (Claude). Both
attacks were reproduced against both implementations before anything was
written; the reproduction is committed at
`tests/fixtures/wrt003_gate_countervectors.py`. WRT-003 is amended to **rev 2**
in the same PR.

## Verdict accepted: AMEND

Every finding is confirmed. The BLOCKER is the sharpest kind — the acceptance
criterion in rev 1 §5 proposed *the attack itself* ("same term under a budget
that exhausts, whose DISSONANCE result hash differs") as the **positive**
novelty control. A proposal to close a re-opener that certifies the re-opener
as the thing it must keep admitting is exactly the mirror-blindness this
project keeps having to name — and it took an adversary looking at the
acceptance criterion, not the mechanism, to see it.

## Reproduction (both, both implementations)

```
settled run: verdict=pass result=887045bc.. atp_spent=7
starved run: verdict=fail result=8bb0006f.. (same term, atp=1; DISSONANCE: True)
ATP-starvation candidate:  py='admissible: (b) new outcome fingerprint'  go=same
wrapper run: verdict=pass result=887045bc.. (fresh term hash, same result: True)
I-wrapper candidate:       py='admissible: (b) new outcome fingerprint'  go=same
```

Term `(K S) K → S`, settled at atp 20. Starve to atp 1 → honest
DISSONANCE(exhausted), fresh fingerprint, admitted. Wrap as `I ((K S) K) → S`
→ same result `887045bc…`, fresh term hash, admitted.

## Dispositions

| Finding | Verdict | rev 2 |
| --- | --- | --- |
| BLOCKER — ATP starvation | **CONFIRMED** | New property P2 (novelty-eligibility, §3.2): only a normal-form result is eligible; exhausted/unresolved/invalid outcomes contribute no fingerprint. Closes it by construction — Book I determinism means non-exhausted runs of one term share a normal form, so budget cannot steer an eligible outcome. |
| MAJOR — raw-term wrapper | **CONFIRMED, escalated** | §3.3: raw-term identity rejected; three candidates laid out (result-only / consumed-evidence+result / scope-down), recommendation **(B)** consumed-evidence+result — the only identity that *is* §7(b)'s "consequence of the evidence". Not decided unilaterally; it is the headline gate question. |
| MAJOR — strengthen invariant | **ACCEPTED** | §5 field taxonomy (semantic / claim / resource); two theorems T1 (purity) and T2 (resource-neutrality); property test asserts allowed novelty per class. |
| MINOR — §13.1 already requires a tuple | **CORRECT** | Open question 5 reframed: the normative addition is the purity+eligibility *constraint* on the required declaration, not the requirement to declare. |
| MINOR — pin cmd@v1 with its own control | **ACCEPTED** | Gate criterion 4: flipped verdict/transcript with no new evidence stays inadmissible; adding evidence re-admits via §7(a). |
| Keep-unchanged list | **AGREED** | rev 1's core (drop expect/verdict, no cmd@v1 fingerprint, symmetric tunnel, doc-version bump, registry constraint) is untouched. |

## One place I push back — mildly, and it strengthens the reviewer's point

The reviewer frames P2 as "cover `atp`". rev 2 covers `atp` not by putting it
under a rule but by making the *outcome class it can produce* (exhaustion)
ineligible. This is stronger than an atp-specific rule: it also closes any
future filer-controlled parameter whose only lever on the outcome is to push
the run into a non-normal-form class. The taxonomy the reviewer asked for is
what makes that generalization statable — "resource fields may change the
fingerprint only by the eligibility rule, never into a different eligible
fingerprint" — so the pushback is really an adoption of the reviewer's own
third finding, taken one step further.

## What rev 2 deliberately does not do

It does not pick computation identity (B vs C). That is the load-bearing
decision, it changes whether a maximally-relevant re-opener stays in the
format, and picking it in a response to the gate that raised it would repeat
rev 1's error at a higher level. It goes to the next gate round with a
recommendation and both counter-vectors staged.

## Ledger / manifest

Filed with its manifest (`reviews/manifests/…annaglova…`). Reviewer label
`annaglova` is a GitHub account, distinct from `chatgpt-web`; both map to
vendor OpenAI, and the census counts labels, so this is a twelfth label. The
count moves in the paper accordingly, and check_claims will enforce it.
