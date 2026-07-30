# Security

## Reporting a vulnerability

Use GitHub's private reporting: **Security → Report a vulnerability** on
<https://github.com/s0fractal/warrant>. That opens a channel visible only to the
maintainers, which is the right place for anything you would not want in a public
issue.

If that is unavailable to you, open a public issue saying only that you have a
security report and asking for a channel. Do not put the details in it.

## What you can expect, honestly

This project is maintained by one person and one model actor. There is no
security team, no on-call rotation, and no paid triage.

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

The things this project asks you to trust:

- **The verifier being wrong.** A store that should fail verification and does
  not; two implementations disagreeing on a verification outcome or a WarrantID.
  This is the highest-value class here — see the severity ladder below.
- **Forging provenance.** Any way to make a record, a policy, an evidence blob or
  a chain read as verified when it is not: swapped bytes at a content address,
  a signature that counts when it should not, an unbound key satisfying a
  threshold, a re-litigation admitted without new evidence.
- **The settlement algebra** (SPEC §7) and **key state** (§5.1): unbounded
  re-opening, censorship of a legitimate record, a subject locked out of
  resolving its own state.
- **`ski@v1` re-execution**: a check that reports pass without running, or whose
  re-run disagrees with what the verifier records.
- **Supply chain of the published package**: anything about the PyPI artefact
  that a reader of `PUBLISHING.md` would not expect.

## What is out of scope

Not because it does not matter, but because it is documented as a limit rather
than a defect:

- **`cmd@v1` verdicts are trusted by specification.** SPEC §7 states the verifier
  does not re-execute them; their trust model is the container. A forged `cmd@v1`
  verdict is a known property of the format, listed in `llms.txt`. A report
  showing it is *worse than documented* is in scope; one restating it is not.
- **`genesis.json` is advisory** (§9) and mutable by anyone with store write
  access. Tampering it produces `WARN: genesis.json unverified` and its contents
  are not used. That is the specified behaviour.
- **`native_decide` is in the Lean trusted base** for part of the proof chain,
  which puts the compiler there too. Stated in `llms.txt`.
- Denial of service through resource exhaustion on a store you already control.
- Findings that require write access to a store to then claim that store is
  untrustworthy, unless the point is that a *reader* cannot tell.

## The consolidated threat model

`THREAT-MODEL.md` (DRAFT, 2026-07-30) is the single attacker-capability matrix:
given an attacker who can write to the store, control the blob transport,
co-sign, hold an unbound key, or author the policy — what still holds, and what
they get. It also states the known structural weaknesses in one place rather
than across four files. The in/out-of-scope lists below remain the process; that
document is the model they rest on.

## Severity, as this project ranks it

The ladder used in `reviews/` and in the gate policy:

- **P0** — two conforming verifiers can disagree on a WarrantID or a verification
  outcome; or something forged reads as verified.
- **P1** — the specification is silent where an implementer must guess.
- **P2** — clarity, structure, misleading output.
- **P3** — roadmap.

## A finding is a reproduction

Not a rule for you, an offer: a report that runs is acted on immediately, and a
report that does not has to be re-derived before anything can happen. If you can
send a script that exits non-zero on the defect and zero once it is fixed, it
becomes a permanent regression test with your name on it.

Every fix in this repository's history carries a negative control — the fix is
removed and the attack is shown to come back — so a reproduction is what the
process is built to consume.

## Verify anything first

```bash
python3 tools/check.py     # 29 checks, one verdict; UNRUN is not a pass
```

If a document and a command disagree, the command is right. Several reports
against this project have been artefacts of reading a feature branch, an archived
evidence blob, or truncated output rather than the thing itself; `MAP.md` says
which ref holds what, and `llms.txt` lists the known gaps so you do not spend a
pass rediscovering them.
