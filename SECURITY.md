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
revocable delegation for day-to-day work (AGENTS.md). Accountability
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

The things Warrant 3 asks you to trust (docs/V3.md):

- **Authenticity being wrong.** A record counted without a signature that verifies under a key the
  reader's trust binds to its actor, or an unsigned record counted without a migration the reader's
  profile accepts; a bad line revoking another line's basis.
- **Lineage and guards being wrong.** A successor admitted from an actor the schema does not allow; a
  version effective without its guard met by distinct role holders other than its own actor, or with a
  required lineage open; a fork hidden; a challenge counted or ignored against §5.
- **Schemas.** A schema counted short of its quorum, or a body admitted that does not fit its schema.
- **Identity.** Two different snapshots with one digest, or one assessment with two ids; a checker's
  attest whose `code` does not name its whole import closure, or that CI accepts though `code` is not
  the checker's code at the commit it names.
- **The repository's gate** (warrant/gate.py, run through tools/gate.py): a pull request merged without the acceptance, tail,
  checks or owner-path rules of docs/V3.md §14.

## What is out of scope

- A local attacker who can write the installed package can change what runs; the
  assessment id then names different engine bytes.
- A view cannot prove its own completeness; reports say `UNATTESTED`.
- Competence of actors is not assessed: what an attestation is worth is the reader's profile.
- The retired Warrant 2 and 0.x generations (`docs/HISTORY.md`): report issues in the published
  `warrant-graph` 2.0.0a1 and
  published `warrant-verify` ≤ 0.12.0 here too, but fixes go to that line only if
  the owner decides to maintain it.
