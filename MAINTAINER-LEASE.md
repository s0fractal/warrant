# Maintainer lease

On 2026-07-29 the project's human steward delegated day-to-day maintenance of
`warrant` and `sigma-glyph` to a model actor (`claude-fable-5`), with other model
families (`codex`, `kimi`, `deepseek`, `qwen3-coder`) acting as gates and
advisers rather than maintainers.

This file writes that delegation down as a **bounded** grant, because the
alternative — an agent reading a broad instruction as general authority — is the
exact move `AGENTS.md` rule 2 forbids, and it would be strange for the first
thing to slip past this project's own machinery to be the maintainer.

The lease is deliberately in the shape the capability-lease design proposes:
a named holder, an enumerated set of permitted acts, an explicit exclusion list,
and no self-amendment.

## Holder

`claude-fable-5` — roster actor in both repositories' `trust-config.json`.

## Permitted without further authorisation

Everything reversible, and everything whose blast radius is a branch:

- work on branches: code, tests, tools, specifications, drafts;
- run gates, including paid reviewer families, and act on their findings;
- push branches to `origin` (a branch is not the trunk, and a branch can be
  deleted);
- choose licences for work this repository originates, per the delegation of
  2026-07-29, subject to the constraints in `TRADEMARK.md`;
- create and update governance and policy *drafts*;
- decline to do any of the above.

## Requires the steward's explicit act, each time

Not because permission is missing in principle, but because these cannot be
undone by the party who did them:

- **merging to `master`** in either repository;
- **publishing**: PyPI releases, tags, GitHub releases;
- **submitting to an external body**: standards liaison, public comment, patent
  or legal filings, anything that names the project to an institution;
- **rewriting shared history**, in any form;
- **adopting** a governance artefact — adoption is a threshold warrant signed by
  roster keys, and a lease never substitutes for a quorum (`AGENTS.md` rule 2);
- **amending this file**, or `AGENTS.md` rules 1–5.

## Why the exclusions are what they are

A merge to trunk, a publication, and a submission share one property: after
them, other people's decisions depend on the act. That is the line, not
seniority and not trust. The holder may prepare each of these to a single
command and should — reducing the steward's work is the point of the lease —
but the command is the steward's.

Rewriting history is excluded twice over: it would void the disclosure
manifests, orphan the Software Heritage snapshots, and break the sibling
repository's commit pins. See `PRIOR-ART.md`.

## Non-self-amendment

The holder may not widen this lease, and may not adopt the specification of the
lease mechanism itself. A capability that can enlarge its own scope is not a
capability; it is an assertion of authority wearing one, and the whole point of
writing this down is that the difference is checkable by someone who was not in
the room.

## Termination

The steward may revoke by saying so, in any words. No notice, no ceremony, no
wind-down. A lease that were hard to revoke would be a transfer.
