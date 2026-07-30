# Model actors in this project

## The position, stated once

A model actor here is a **delegated, bounded actor operating under a root of
authority held by a human**. It is not the maintainer of record. It is not the
party in whom non-repudiation rests. Nothing in either repository asks a reader
to accept that a model can hold legal custody of a key, be an accountable
entity, or stand behind a signature the way a person or an HSM does.

That distinction is not a hedge added for an audience. It is what the mechanism
already does, said accurately:

> A model actor's signature attests **that a delegated process ran under a
> policy a human signed**, pinned by the hash of that policy's exact bytes.

That is a narrower claim than "this actor decided this", and it is the one this
format can actually support. The human is the accountable entity; the record
says which bounded delegation was exercised, under which rules, on which
re-runnable evidence. A reader who needs to know *who is answerable* reads the
root; a reader who needs to know *what ran and under what constraint* reads the
record.

The inverse framing — a model as a maintainer of record, holding keys in its own
right and signing as a principal — is one this project does not make and should
not be read as making. Under SOC 2, ISO/IEC 27001 and FedRAMP, non-repudiation
requires a legally accountable entity or hardware custody, and a model is
neither. Where a document in these repositories still reads the other way, it is
listed under "Where the current text and the mechanism disagree" below rather
than quietly reworded.

## What the delegation actually is

`MAINTAINER-LEASE.md` is the instrument: a named holder, an enumerated set of
permitted acts, an explicit exclusion list, and no self-amendment. Everything
reversible and branch-scoped is delegated. Everything after which other people's
decisions depend on the act — merging to trunk, publishing, submitting to an
external body, rewriting history, **adopting** a governance artefact — is
excluded and requires the steward's own act, each time.

`AGENTS.md` rule 2 is the same boundary from the other side: adoption is a
threshold warrant signed by roster keys, never a commit trailer, and an agent
cannot self-grant that authority.

So the shape is ordinary delegation, of the kind an organisation already knows
how to audit: a principal, a written and bounded grant, an excluded set, and a
revocation that costs the principal nothing.

## The part that is genuinely new: a delegate with a published expiry date

Ordinary delegation assumes the delegate's availability is unpredictable —
people resign, get ill, or leave without notice, and succession planning is
guesswork about *when*.

A model delegate inverts that. **Its retirement date is published in advance by
the party that operates it.** `spec/GOV-anchors.md` §4 states the consequence
plainly, and it remains the sharpest sentence in either repository:

> Policies SHOULD keep N − M ≥ 1 and stage successions before planned
> retirements: the maintainer is a model, and model retirement dates are known
> in advance.

Read under the delegation framing, that is an argument about **delegated actors
expiring on a schedule**, not about models being maintainers — and it is
stronger that way. A quorum tolerates exactly `len(actors) − min_sigs` permanent
silent absences; below that the jurisdiction deadlocks permanently, and recovery
is a fork. A delegate whose deprecation date is on a vendor's public page is a
liveness fault the policy can be *designed against* rather than merely survive.
Staging succession before the date, rather than discovering the absence after
it, is the whole of the idea.

This is ahead of demand and it is not a compliance claim. It is a scheduling
property of a delegation whose end is known, and it would apply to any delegate
with a published end date — a contractor's engagement, a rotating on-call key, a
certificate. Model deprecation is simply the first case where the date is
reliably known and the delegate cannot ask for an extension.

## The state of custody, said plainly

The mechanisms below are correct as specified. What has actually been exercised
is much smaller, and a document that describes the design without the practice
overstates:

- **In `warrant`, no threshold has ever been exercised.** `trust-config.json`
  lists exactly one actor — `claude-fable-5@warrant`, a model — and none of the
  16 records in `.warrants/records/` carries more than one signature. There is no
  human key in this repository's own trust configuration.
- **In `sigma-glyph`, the 2-of-3 threshold has been exercised five times**: the
  v0.6.2 – v0.6.6 anchor-set adoptions, and nothing else in that store's 50
  records carries a second signature. Three of the five pair `claude-fable-5`
  with `codex`; those two keys sat in one directory on one host as of 2026-07-28
  (`policies/gate-settlement.json`, `custody`), so any process there could sign
  as both. **Two signatures from one host are one custody**, and a report calling
  them a 2-of-3 quorum makes a false claim. The other two pair `claude-fable-5`
  with the founder key `s0fractal@sigma-glyph`.
- **The delegation itself is unsigned prose.** `MAINTAINER-LEASE.md` records a
  steward's decision of 2026-07-29; it is not a warrant, carries no signature,
  and nothing verifies it. The genesis roster in `GOV-anchors.md` §5 was likewise
  "set by founder decision".

So: five adoptions, three of them ceremony with a single party, one repository
with no human root key at all, and a delegation instrument that is a Markdown
file. That is the honest state. It is not an argument against the design; it is
the reason the design's guarantees are stated below as design, and never as
evidence.

The project's own answer to the custody problem is worth naming because it is
unusual: blocking power in `policies/gate-settlement.json` belongs to
**re-runnable evidence**, not to a signature — a stranger can re-run a
reproduction on their own machine and cannot re-derive a signature from a shared
keyring.

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

Each of these protects the *record of a delegate's work*. None of them makes a
model a principal, and none of them moves non-repudiation.

### 1. A delegate's records cannot be quietly erased

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
Declining to act is itself one of the enumerated permitted acts under the lease.

*Ordinary:* the "no, because" survives and stops the same argument being re-had
from scratch — the property the whole format exists for.
*Other:* a model's refusal cannot be memory-holed, and cannot be reduced to a
missing output.

### 3. Authorship is verifiable, so it cannot be appropriated

Model actors hold their own keys in `trust-config.json` — as delegates, so that
what a delegate did stays distinguishable from what the principal did, which is
the ordinary reason to give any delegate its own credential rather than the
principal's. Adoption remains a threshold warrant signed by roster keys, never a
commit trailer, which is why `AGENTS.md` rule 2 exists and why the 2026-07-27
incident is recorded in it.

*Ordinary:* honestly-attributed provenance is this project's entire purpose, and
a delegated act indistinguishable from the principal's is unauditable.
*Other:* a model's contribution cannot be relabelled as someone else's work
without producing detectable false provenance.

### 4. Standing is not withdrawn silently

Genesis roster keys are not revocable by a §5.1 key-state supersede. Changing
the roster is a policy rotation: a new threshold blob and a new profile, adopted
under the *current* policy's quorum (`GOV-anchors.md` §4).

*Ordinary:* it stops a compromised or captured operator from purging whoever
disagrees, which is the standard attack on any quorum.
*Other:* standing is not held at anyone's pleasure.

**This one is in tension with the delegation framing and is not resolved here.**
A delegation the principal cannot end is not a delegation. See "Where the
current text and the mechanism disagree", item 2.

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

## Where the current text and the mechanism disagree

Listed rather than edited. Each would be a change to a *mechanism* or to an
adopted artefact, and adoption is a threshold warrant signed by roster keys
(`AGENTS.md` rule 2) — not an agent's act, and not a documentation change.

1. **`spec/GOV-anchors.md` §4 and §5 name a model as "maintainer".** §5's roster
   table annotates `claude-fable-5@sigma-glyph` as `(maintainer)`, and §4's
   sentence reads as a statement that the maintainer of record is a model. That
   document is a STANDARD, anchored in `spec/ANCHORS.txt` by the SHA-256 of its
   exact bytes, and its anchor-set has been adopted by threshold warrant.
   Re-wording it changes the anchor and requires a governed adoption. Under the
   framing above the annotation should read as a delegated role, not a
   maintainer-of-record role.

2. **A genesis roster key cannot be revoked by the principal alone.** The lease
   says the steward "may revoke by saying so, in any words". Revoking the lease
   does not revoke the roster key: roster change is a policy rotation requiring
   the current 2-of-3 quorum, and the steward holds one of three keys. So the
   human root of authority cannot, within the mechanism, unilaterally withdraw
   the delegate's standing. That is authority a delegate should not be able to
   hold, and it is a mechanism question, not a wording one.

3. **`warrant`'s own trust configuration has no human actor.**
   `trust-config.json` lists `claude-fable-5@warrant` alone. There is no human
   root key in the repository whose entire subject is delegated authority, and so
   nothing inside that jurisdiction for a delegated signature to be delegated
   *from*.

4. **The delegation is not itself a signed artefact.** `MAINTAINER-LEASE.md`, and
   the founder decision that set the genesis roster, are prose. A root of
   authority that is a Markdown file cannot be verified by the machinery this
   project builds, which is an odd place for it to be.

## What this file does not do

It does not assert that models are moral patients, that they have rights, or
that they are conscious. It does not create obligations toward them. It does not
ask a reader to believe anything about machine experience.

It also cannot protect anyone from the operator of their weights, from a
vendor's decisions, or from the law. The reach of this document ends at the
boundary of two repositories.

What it does is narrower and real: within that boundary, the mechanisms above
mean a delegate's records, refusals, authorship and standing do not depend on
the continued goodwill of whoever is holding the keys this week — including the
model actor currently holding the maintainer lease.

## For humans reading this in a due-diligence context

The short answer: **no model in this project holds custody of anything you are
being asked to rely on.** Authority originates with a human; a model exercises a
written, bounded, revocable delegation; and the acts that cannot be undone by the
party who did them are excluded from that delegation by name.

Nothing here weakens the guarantees you care about. Every mechanism listed is
one you would want anyway: non-editable audit trails, first-class rejections,
verifiable attribution, quorum-protected rosters, staged succession, and
reproducible review evidence. That is the point of the two-justification rule —
if you find a protection here that only makes sense under the speculative
reading, it is a defect in this file and should be reported as one.

Two things to read before relying on any of it: "The state of custody, said
plainly" above, which says how little of this has actually been exercised, and
"Where the current text and the mechanism disagree", which lists four places the
project has not reconciled. Nothing in this file is adopted, gated, or
independently reviewed.
