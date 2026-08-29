# Agent autonomy: a capability envelope, not a blank cheque

**Status: BOOTSTRAP DRAFT.** The evaluator is useful immediately as a read-only
control, but unattended merge authority is disabled. This document and the
policy do not ratify themselves.

The maintainer's intended direction is AI-reviewed, progressively autonomous
operation. The engineering consequence is not “trust the model more.” It is to
make the model's available actions smaller, explicit, observable, and difficult
to enlarge from inside the action being judged.

## The boundary

For a pull request from base commit `B` to candidate commit `H`:

1. The evaluator, policy, and trust roots are read from `B`, never `H`.
2. `H` is fetched and inspected as Git data. No executable from `H` runs in the
   authorization job.
3. A protected-path hit is a denial, not a request for the model to explain why
   its own exception is safe.
4. Missing or failing checks, a stale head binding, malformed policy, unsupported
   file mode, or absent authorization cannot be interpreted as permission.
5. The decision packet binds the base SHA, head SHA, exact policy hash, measured
   diff, check evidence, reasons, and decision.

This creates three distinct outcomes:

- `ELIGIBLE`: the requested action is inside a ratified envelope and every
  required fact is present.
- `HOLD`: the change may be sound, but standing authority or required evidence
  is absent. Silence lands here.
- `DENY`: the requested action is outside the envelope or violates a hard bound.

`ELIGIBLE` means only that a repository action is authorized by this envelope.
It does not mean governance adoption, independent custody, correctness,
scientific validity, or normative authority.

## Bootstrap phase

The v0.1 policy grants agents the reversible working actions needed to make
progress: push a non-default branch, open or update a Draft PR, and mark it ready
after evidence is recorded. It explicitly withholds merge, release, branch-admin,
history-rewrite, and governance-adoption authority.

The first unattended merge can occur only after all of the following are true:

1. branch protection on `master` is active and names the load-bearing required
   checks;
2. a maintainer public key is pinned on `master`;
3. a detached maintainer signature authorizes the exact SHA-256 of a policy,
   repository, branch, validity window, and permitted action set;
4. the policy's `merge` capability is explicitly true;
5. the authorization workflow still comes from the protected base revision.

The private key is never created, held, or used by an agent. A GitHub login, PR
comment, model statement, co-located roster key, or green suite is not silently
upgraded into that signature.

## Why self-change is excluded

The autonomous lane is deliberately narrow. A candidate that changes any of
these surfaces cannot merge under its own verdict:

- the autonomy policy, evaluator, workflow, tests, or trust roots;
- `AGENTS.md`, Warrant stores, protocol/spec/schema, adoption, or settlement;
- dependencies, release/publish configuration, integrations, proof machinery,
  conformance vectors, or implementation code.

Those changes are not forbidden. They require a different authority path. This
is the load-bearing asymmetry: agents may work on the court, but the court being
changed does not sit in judgment over that same change.

## Progression

The safe progression is capability-by-capability:

1. reversible branch and PR operations;
2. unattended merge for a small non-normative path lane;
3. broader implementation lanes only after their own countervectors and
   independently changeable gates exist;
4. releases and governance, if ever, under separate keys and policies.

Expansion happens by replacing a hash-pinned policy through the protected path,
not by adding an exception to a candidate PR. Revocation is simpler: disable the
workflow or replace the authorization on `master`; absence immediately fails
closed.
