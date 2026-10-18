# Security

## Reporting a vulnerability

Use GitHub's private reporting: **Security → Report a vulnerability** on
<https://github.com/s0fractal/warrant>. That opens a channel visible only to the
maintainers, which is the right place for anything you would not want in a public
issue.

If that is unavailable to you, open a public issue saying only that you have a
security report and asking for a channel. Do not put the details in it.

## What you can expect, honestly

This project is maintained by one person, with a model actor holding a bounded,
revocable delegation for day-to-day work (`MAINTAINER-LEASE.md`). Accountability
sits with the person; the model is a delegate, not a maintainer of record. There
is no security team, no on-call rotation, and no paid triage.

- **Acknowledgement:** best effort, usually within a few days. If a week passes
  with no reply, assume the message was missed and say so publicly without
  details — that is not a breach of coordination, it is the only remedy you have.
- **Fix timeline:** none is promised, because none could be kept. What is
  promised is that a confirmed report gets a reproduction, a regression test, and
  a commit that says plainly what was wrong.
- **Credit:** named in the fixing commit unless you ask otherwise.
- **Embargo:** as long as you need to coordinate, and no longer. If a fix ships
  before you are ready, the commit will say the reporter asked for a delay.

No bounty. No CVE-issuing authority here; if a report warrants a CVE, request one
through GitHub's advisory flow, which this repository supports.

## What is in scope

The things Warrant 2 asks you to trust (SPEC.md):

- **Admission being wrong.** A closure admitted without its required acceptance,
  by someone who did not hold the duty at that position, on a basis its
  condition does not admit, or out of admission order; an acceptance of another
  item or evidence set counting.
- **Reliance being wrong.** ELIGIBLE where a trigger fired or was unevaluable,
  where a counting challenge stands, where an observation is stale, or without a
  revision basis.
- **Authority.** A key binding, `serves`, or a delegation authorizing more than
  SPEC §4.1/§4.5 allow; a grant beyond its parent.
- **Computation.** A replay credited for another task, another answer or a target
  the recipient did not accept; bytes executed that are not the pinned ones.
- **Identity.** Two different views with one assessment id, or one view with two.

## What is out of scope

- The process boundary around the Sigma kernel isolates module names; it is not
  an OS sandbox. A local attacker who can write the installed package can change
  what runs; the assessment id then names different engine bytes.
- A view cannot prove its own completeness; reports say `UNATTESTED`.
- Competence of actors is not assessed (SPEC §6).
- The retired Warrant 0.x generation (`HISTORY.md`): report issues in the
  published `warrant-verify` ≤ 0.12.0 here too, but fixes go to that line only if
  the owner decides to maintain it.
