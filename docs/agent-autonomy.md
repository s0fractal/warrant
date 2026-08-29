# Agent autonomy: a capability envelope, not a blank cheque

**Status: HASH-ACTIVATED ENVELOPE.** This mechanism grants standing authority
only on a protected `master` revision that contains all four of: an active
policy, the public key named by that exact policy, a valid detached signature
over the exact policy bytes, and the base-owned merge actor. Removing or
invalidating any one makes the decision `HOLD`; this prose does not authorize
anything by itself.

The maintainer's intended direction is AI-reviewed, progressively autonomous
operation. The engineering consequence is not “trust the model more.” It is to
make the model's available actions smaller, explicit, observable, and difficult
to enlarge from inside the action being judged.

## The boundary

For a pull request from base commit `B` to candidate commit `H`:

1. The advisory job checks out only the **default branch** — the same trusted
   source `workflow_run` loads the workflow itself from — and runs the evaluator
   and its trust-binding pre-processor from there. It never checks out a
   PR-chosen ref. The policy and trust roots are then read from `B` by that
   evaluator, and `B` is accepted only after it is proven to be on the default
   branch (its base ref is the API's default branch, and it is a git ancestor of
   the checked-out default tip). A same-repo *feature* branch used as a base is
   refused before any of its bytes are read.
2. `H` is the immutable `workflow_run.head_sha` — the exact commit the required
   checks ran on. It is fetched and inspected as Git data; no executable from
   `H` runs in the authorization job. If the live pull request has since drifted
   (a force-push, or the base advancing), the check evidence is withheld and the
   decision is `HOLD`, so a green packet can never describe a different revision
   pair than the one the checks observed.
3. Required-check evidence is bound to trusted workflow identity — the
   default-branch workflow file, the github-actions app, this head, this pull
   request, a `pull_request` event — never to a bare check-run name another app
   or a candidate workflow could mint.
4. A protected-path hit is a denial, not a request for the model to explain why
   its own exception is safe.
5. Missing or failing checks, a stale head binding, malformed policy, unsupported
   file mode, or absent authorization cannot be interpreted as permission.
6. The decision packet binds the base SHA, head SHA, exact policy hash, measured
   diff, check evidence, reasons, and decision. Each required check is credited
   only from a workflow run whose own snapshot observed that exact base and head
   — checks that passed against an older base are never stitched onto a newer one.

### The packet proves a pair; the actor closes the merge boundary

The advisory packet is evidence about **one exact `(base, head)` pair** the
required checks were observed against. It does not perform a merge and it cannot
speak for the state of the repository at some later instant. Between the packet
and any merge, the base branch can advance and the head can be force-pushed.

So the packet is necessary, not sufficient. The write-capable
`autonomy-merge` actor independently re-reads the live PR, default-branch tip,
mergeability, and branch-protection response. It requires the same exact
`(base, head)` pair and the exact two required check/app identities, then runs
the signed policy gate from `base` again. Immediately before mutation it reads
the live state a second time and calls GitHub's protected merge endpoint with
the expected head SHA. GitHub atomically refuses a changed head; strict required
checks on a protection rule enforced for administrators refuse a candidate
whose base is no longer current.

The actor token has `contents:write` and `pull-requests:write`, but no repository
administration permission. It therefore cannot weaken the protection response
that its own preflight requires. Candidate bytes are never checked out or
executed by either autonomy workflow.

This creates three distinct outcomes:

- `ELIGIBLE`: the requested action is inside a ratified envelope and every
  required fact is present.
- `HOLD`: the change may be sound, but standing authority or required evidence
  is absent. Silence lands here.
- `DENY`: the requested action is outside the envelope or violates a hard bound.

`ELIGIBLE` means only that a repository action is authorized by this envelope.
It does not mean governance adoption, independent custody, correctness,
scientific validity, or normative authority.

## Active capability

The v0.1 policy grants agents the reversible working actions needed to make
progress and permits unattended merge only inside `briefs/`, `demos/`, `docs/`,
`examples/`, and `prior-art/`, within the numeric and file-shape ceilings in the
signed policy. It explicitly withholds release, branch-admin, history-rewrite,
and governance-adoption authority.

An unattended merge can occur only while all of the following remain true:

1. branch protection on `master` requires a PR, is strict and enforced for
   administrators, forbids force-push/deletion, and names only `test` and
   `cross-repo` from GitHub Actions app id `15368`;
2. a maintainer public key is pinned on `master`;
3. a detached maintainer signature authorizes the exact SHA-256 of a policy,
   repository, branch, validity window, and permitted action set;
4. the policy's `merge` capability is explicitly true;
5. the authorization workflow still comes from the protected base revision.

The maintainer key uses P-256 in this Mac's Secure Enclave. The repository's
signer stores only an opaque, device-bound handle under the maintainer's
`Library/Application Support/Warrant` directory and requires user presence
(Touch ID or device password) for the signing operation. The repository receives
only the X9.63 public key and detached ECDSA signature. No raw private scalar is
exported to a file or supplied to an agent.

This is a user-presence boundary, not an independent human review and not a
second machine. A malicious process on the same host may request a signature or
misdescribe what the prompt means; the maintainer must still inspect the policy
digest printed by the signer before authenticating. A GitHub login, PR comment,
model statement, co-located roster key, or green suite is never upgraded into
that signature.

From the repository root, the maintainer creates or reuses the Secure Enclave
key and signs the current exact policy with one command:

```sh
swift tools/autonomy_sign.swift authorize --days 365
```

The command prints the policy digest, action set, and validity window before the
macOS authentication prompt. It refuses to fall back to a software key when the
Secure Enclave is unavailable.

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

## Operational stop and recovery

The fastest stop is disabling `.github/workflows/autonomy-merge.yml` in GitHub
Actions. The durable stop is a protected PR that sets the policy to `revoked` or
removes the authorization. The actor cannot merge either its own expansion or
its own repair because `.github/`, `policies/`, `trust/`, `tools/`, and `tests/`
are protected paths. Those changes remain explicit maintainer merges.

If the Mac or Secure Enclave handle is lost, existing authorization remains
verifiable but no new authorization can be issued with that key. Recovery is a
protected, explicit key-rotation PR; there is no agent-side recovery secret.
