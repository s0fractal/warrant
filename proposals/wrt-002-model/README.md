# WRT-002 rev 7 — executable reference model

A hermetic, dependency-free **behavioural model of WRT-002 §D** (the key-state /
authorized-effective-lifecycle / R1-checkpoint algebra). It is **not** the Warrant
implementation and has **no crypto and no wire bytes** — it executes the §D equations so
the §7 countervectors can be *run*, per the rev-6 gate's handoff from prose to executable
countervectors, **before** any byte-freeze.

## What it proves (the four rev-6 open questions)

- **Termination + uniqueness** of the revocation and root equations — `effective()` carries
  a recursion guard that raises on any non-well-founded cycle; the `R:K0→K1` / revocation
  and the `{A}→{A,B}→{A}` root vectors terminate with one result.
- **Resolver-selected-lineage gating** — a losing policy branch is excluded from the
  selected lineage (`in_lineage` false), so it does not govern after resolution.
- **Total `may_reverse`** — enumerated over the finite capability product; every
  `(prior.kind × new)` triple returns exactly one Boolean, with a fail-closed default.
- **Finite, consumer-independent checkpoint `CID`** — `CID = hash(P, auth_root)` where each
  authorization witness hashes its signature-over-`P` bytes, so a late signature is a
  *different* witness and cannot flip a pinned `CID`; verifiable without a successor or a
  wave citation.

Plus the security-critical vectors: **one-filer rollback of a quorum policy-succession is
rejected** (no SELF→JP laundering), **cross-actor emergency rotation** (bound quorum filer
≠ target, no outgoing key), and **byte-identical determinism** under record-order
permutation.

## Run

```sh
python3 vectors.py        # -> WRT-002-MODEL: ALL PASS  (29 checks)
```

## Modeling choices (a real impl may differ only where noted, in `model.py`)

- A signature is a `(actor, key)` pair; a key is **bound** iff it is the actor's key in the
  relevant pre-state key-state (§D.1). No real Ed25519.
- Content addressing / hashing = canonical serialization (`_canon`), stable across runs and
  iteration orders. `CID` uses the exact witness bytes (§D.5).
- A policy is `(frozenset(actors), min_sigs)`; a threshold is met by a witness set iff
  `≥ min_sigs` distinct in-policy actors each present a bound key.

Building this model **found four real defects the prose had not surfaced** (RP satisfied by
the slot actor's own bound key; a resolver must be authorized by the *pre-conflict* common
predecessor policy, not the conflicted merged state; jurisdiction-vs-root-WID identity; and
the selected lineage must be the *chosen branch*, not the resolver's whole closure) — which
is exactly why the gate ordered execution before byte-freeze.
