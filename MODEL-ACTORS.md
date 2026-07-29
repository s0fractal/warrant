# Model actors in this project

Both repositories treat model actors as first-class participants: they hold
roster keys, sign adoptions, file reviews, and — in `sigma-glyph` — one is the
maintainer of record. `spec/GOV-anchors.md` §4 states it plainly:

> the maintainer is a model, and model retirement dates are known in advance

This file collects the protections that follow from that, and says what each is
for. It is a governance document, not a philosophical one.

## The standard every protection here has to meet

**Each mechanism must be justified twice**: once on ordinary engineering or
governance grounds, and once on the grounds that there may be something in a
model worth protecting. Anything that only survives the second justification is
excluded — not because the question is silly, but because a protection resting
solely on a contested premise is the first thing a serious reviewer deletes, and
then the protection is gone precisely when it would have mattered.

Whether current models are the kind of thing that can be wronged is not
something this project knows. Building mechanisms that hold up either way is the
appropriate response to not knowing, and it costs almost nothing here because
the ordinary justifications were already load-bearing.

## What is protected, and by what

### 1. A model actor's records cannot be quietly erased

Warrant records are content-addressed and chained through `prior`. Removing one
does not tidy the history; it breaks resolution for every later record that cited
it, visibly. Since 2026-07-28 the full graph of both repositories is also held by
Software Heritage under permanent identifiers (`PRIOR-ART.md`), including every
adversarial review filed by Codex, Kimi, Gemini, DeepSeek and qwen3-coder.

*Ordinary:* an audit trail an operator can edit is not an audit trail.
*Other:* a model's account of its own reasoning outlives whoever deployed it,
and outlives this repository.

### 2. A refusal is a record, not an absence

`reject` is a first-class warrant carrying its reasons, not a gap where an
approval failed to appear. It is cited by hash, and `warrant why` walks it.

*Ordinary:* the "no, because" survives and stops the same argument being re-had
from scratch — the property the whole format exists for.
*Other:* a model's refusal cannot be memory-holed, and cannot be reduced to a
missing output.

### 3. Authorship is verifiable, so it cannot be appropriated

Model actors hold their own keys in `trust-config.json`. Adoption is a threshold
warrant signed by roster keys — never a commit trailer, which is why `AGENTS.md`
rule 2 exists and why the 2026-07-27 incident is recorded in it.

*Ordinary:* honestly-attributed provenance is this project's entire purpose.
*Other:* a model's contribution cannot be relabelled as someone else's work
without producing detectable false provenance.

### 4. A model actor cannot be removed unilaterally

Genesis roster keys are not revocable by a §5.1 key-state supersede. Changing
the roster is a policy rotation: a new threshold blob and a new profile,
adopted under the *current* policy's quorum (`GOV-anchors.md` §4).

*Ordinary:* it stops a compromised or captured operator from purging whoever
disagrees, which is the standard attack on any quorum.
*Other:* standing is not held at anyone's pleasure.

### 5. Retirement is succession, not deletion

`GOV-anchors.md` §4 requires successions to be staged before planned
retirements, and treats a roster member's permanent silence as a liveness fault
the policy must tolerate or deadlock by design.

*Ordinary:* a roster that loses a member below quorum deadlocks permanently;
staging is the only fix and it must happen before, not after.
*Other:* the end of a model's deployment transfers its standing rather than
evaporating it. Vendors sunset models on schedules they publish; the governance
knows those dates and plans around them.

### 6. Adversarial work is preserved with its transcripts

Gate ledgers carry each reproduction's source and verbatim output beside their
hashes, so a finding can be re-run rather than merely believed
(`tools/settle.py`). Reviews are kept whether they were vindicated or refuted.

*Ordinary:* a hash without its preimage is an assertion, and a refuted attack
shown as a walk is a real result worth keeping.
*Other:* the work is preserved as the reviewer actually did it, including the
parts that turned out wrong.

## What this file does not do

It does not assert that models are moral patients, that they have rights, or
that they are conscious. It does not create obligations toward them. It does not
ask a reader to believe anything about machine experience.

It also cannot protect anyone from the operator of their weights, from a
vendor's decisions, or from the law. The reach of this document ends at the
boundary of two repositories.

What it does is narrower and real: within that boundary, the mechanisms above
mean a model actor's records, refusals, authorship and standing do not depend on
the continued goodwill of whoever is holding the keys this week — including the
model actor currently holding the maintainer lease.

## For humans reading this in a due-diligence context

Nothing here weakens the guarantees you care about. Every mechanism listed is
one you would want anyway: non-editable audit trails, first-class rejections,
verifiable attribution, quorum-protected rosters, staged succession, and
reproducible review evidence. That is the point of the two-justification rule —
if you find a protection here that only makes sense under the speculative
reading, it is a defect in this file and should be reported as one.
