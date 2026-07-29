# WRT-002 rev 7 — independent adversarial gate brief

**For a reviewer who is NOT Codex.** Every gate on WRT-002 rev 1→6 and on
ADR-008 rev 3→15 was Codex. That is a single-reviewer fixed point, not a gate:
each round converges on Codex's blind spot, and the project's own Decision
Process requires **≥3 independent model families**. This brief exists to be
handed to a different family (the two with a demonstrated record of finding what
Codex did not on this exact codebase are **Kimi K3** — 11 reproducible findings
the green suites missed — and **Gemini 3.1 Pro** — a P0 liveness self-destruct in
GOV promotion, and 2 P0s in the from-scratch Ed25519 that a 452-case
differential could not reach).

---

## Your job, stated precisely

**You are not asked to review prose, and you are not asked to run the suites.**

`proposals/wrt-002-model/vectors.py` prints `WRT-002-MODEL: ALL PASS` (29
checks). It did before you arrived. Reporting that it passes is a rubber stamp
and will be rejected (`AGENTS.md` §3).

You are asked to **produce a counter-vector**: a concrete, executable input to
the §D machine that makes it do something §D says it must not do. A finding is
real when it comes with code that runs against
`proposals/wrt-002-model/model.py` and demonstrates the violation. A finding
without a reproduction is a question, not a finding — file it as such.

Run this first:

```sh
cd proposals/wrt-002-model && python3 vectors.py     # -> WRT-002-MODEL: ALL PASS (29)
```

Then read `proposals/WRT-002-keystate-effective-lifecycle-r1.md` **§D only** —
it is the normative core, and where §§0–6 prose disagrees with §D, §D governs.
Do not spend your budget on §§0–6.

---

## What WRT-002 is trying to be

A settlement substrate that answers one question without a censorship primitive:

> Which records were *effectively* active, as of a fixed historical cut,
> authorized by evidence that cannot have changed since?

The naïve answer — `active − supersede-targets` — is a **censorship primitive**:
any self-signed actor can supersede anyone's WarrantID and vanish it. §D replaces
it with three ordered layers (`valid_cap` → `selected_lineage`/`admits` →
`effective`), a frozen total witness manifest, a capability algebra with a total
`may_reverse`, and a finite consumer-independent checkpoint `CID`.

---

## The attack surface, ranked (start at the top)

### 1. The three-layer split — is the negation cycle actually gone?

rev 6 was broken by a non-monotone fixed point; rev 7 claims the three ordered
layers remove the cycle by construction. Attack it:

- Construct a store where layer 2 (`admits`) depends on a fact that layer 3
  (`effective`) is what establishes — a cycle laundered through the manifest.
- The model carries a recursion guard that *raises* on non-well-foundedness. A
  guard that raises is a detector, not a proof. **Find an input where the guard
  does not fire but two valid evaluation orders give different `effective` sets.**
  Order-independence is claimed via ACI union over `preEvents`; try to break ACI
  with an event whose authorization basis differs by arrival order.

### 2. Total manifest — the negative claim

An `ineligible` entry is a **quorum-authorized negative historical claim**
(signature *absence* is unprovable from a mutable envelope, so the quorum
vouches). This is the softest joint in the design: it is a *social* fact wearing
a mechanical uniform.

- Show a store where a colluding quorum marks a validly-signed record
  `ineligible` and **no verifier can distinguish that from the mechanical case**.
  §D claims it stays *visible and attributable*. Is it? Produce the exact bytes a
  challenger would have to hold to prove the record was in fact eligible.
- Can an `ineligible` entry be made for a record whose eligibility *later*
  becomes provable (a signature appended after the checkpoint)? §3 freezes the
  seam — verify the freeze covers this, or break it.

### 3. `may_reverse` totality — the fail-closed default

Claimed total over the finite capability product with a fail-closed default.

- Enumerate the product yourself and diff against the model's table. A `False`
  default is safe for *authorization* but may be unsafe for *liveness*: find a
  legitimate governance action the fail-closed default makes permanently
  impossible. rev 6's predecessor died of exactly this class (a scoped key-state
  refusal that deadlocked on first rotation) — the class is not obviously extinct.

### 4. Checkpoint `CID` — finite and consumer-independent

`CID = hash(P, auth_root)`, each witness hashing its signature-over-`P` bytes, so
a late signature is a *different* witness and cannot flip a pinned `CID`.

- Two-stage proposal + separate authorization: can a filer produce two distinct
  authorization sets over the same `P` that both satisfy the policy, yielding two
  valid `CID`s for one frontier? Is that a fork, or a bug? §D should say; check
  that it does.
- **Frontier completeness is explicitly not mechanically proven** — it is a
  quorum claim. Construct the omission attack the governing quorum can perform
  and show what a downstream R1 consumer sees. Is it *visible*, as claimed?

### 5. Cross-actor emergency rotation

A bound quorum filer ≠ target, no outgoing key. This is the compromise-recovery
path, so it is the attacker's favourite.

- Show a compromised-key scenario where emergency rotation either (a) lets the
  attacker rotate a victim's key, or (b) is blocked when it must not be.
- The model found "RP satisfied by the slot actor's own bound key" as a real
  defect. Look for its siblings: any place a predicate is satisfiable by the
  entity it is meant to constrain.

### 6. The layer below — does WRT-002 hold up WRT-001/ADR-008?

WRT-002 exists to give ADR-008's R1 an authorized historical checkpoint. Check
the interface, not just the machine: does §D's checkpoint actually supply
`authorized_effective_active_for(J, checkpoint)` with the properties WRT-001 §6
assumes? A substrate that is internally sound and externally mismatched is still
a failed substrate.

---

## Ground rules

- **§D governs.** Prose elsewhere is context.
- **No wire bytes exist yet, on purpose.** Findings about serialization,
  canonicalization or crypto are out of scope — the model has no crypto by
  design (a signature is an `(actor, key)` pair). Do not spend budget there.
- **Severity:** P0 = the machine is unsound or a censorship/forgery path exists.
  P1 = a composition breaks, or a claimed property does not hold. P2 = a real but
  bounded defect. Anything you cannot reproduce is a **question**, filed as one.
- **Rebuttal is a valid outcome.** If you attack something and it holds, say so
  and show the walk — a refuted attack is worth as much as a finding here, and
  prior gates have recorded exactly that.
- **State what you did NOT examine.** Coverage honesty is part of the verdict.

## Verdict format

```
VERDICT: APPROVE | AMEND | REJECT
Examined: <what you actually read/ran>
NOT examined: <what you skipped, and why>
Findings: <P0/P1/P2, each with a runnable reproduction against model.py>
Refuted: <attacks you tried that held, with the walk>
```

File as `reviews/2026-07-<model>-wrt-002-rev7-adversarial-gate.md`.

---

*Prepared 2026-07-27 by an assisting agent (Claude, Cowork session) to break a
single-reviewer monoculture. This brief is not itself a gate, and its author is
not a reviewer of record.*
