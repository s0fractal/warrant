# WRT-023: Effects and frontier gates — from a decision to what happened, and from open loops to a merge

**Status:** DRAFT proposal, revision 1, 2026-10-18. Written by Claude at the owner's request. Nothing is implemented, and nothing in SPEC.md or `warrant verify` changes. It is agreed locally before any code, and goes to GitHub with its first implemented slice.

It is kept separate from WRT-022 so that the two surfaces do not mix:
- WRT-022 decides who may act and when a closure stops being reliable;
- WRT-023 binds closures to effects in the world, and binds a merge to the state of the frontier.

**It starts from:**
- warrant master `a2ac0ee`;
- WRT-022 S1 on `wrt-022/s1-triggers` at `4cf2c23`, PR #135, accepted by Codex and waiting on CI: tri-state triggers, `reliance_detail(rep, duty, use)`, and the real dogfood store.

## 1. Where this comes from

| Source | What is taken | What is not |
|---|---|---|
| **Gemini (Argon) review of warrant at `a2ac0ee`**, read against manifesto `ONTOLOGY-FORMALIZATION-0.1` (relayed by the owner, 2026-10-18). Gemini started from a partial export of manifesto, and its account mixes up which repository owns which obligation. | **I7**, result → effect: a `reject` record can coexist with an executed side effect, because nothing receipts the effect. **The closure rule for a session or pipeline**: it is not finished while open loops remain (VORTEX S1, read operationally). | Moving sigma-resume semantics into warrant's settlement code (§7). A "Cold Reconstruction Gap" score computed by a model judge (§7). Agent cross-model cosignatures as independence (§7). |
| **The meta-ontology**, manifesto `artifacts/ONTOLOGY-FORMALIZATION-0.1.md` at `dd0a74b` | §3.7: physical change ΔX is not informational change ΔC / ΔI; an effect is a ΔX across a boundary. §4.4 (0012): imagination keeps `candidate`, and hallucination casts it to `settled`. Read here as: an intended effect is not a performed one. §7.1.2: the present is local. | numeric confidence; VORTEX laws as metrics |
| **The live session** (2026-10-18) | PR #135 was not merged while the S1 duty was OPEN, by hand. §4 makes that rule checkable. | |
| **warrant itself** | `warrant-mcp` seals a tool call and its result: `accept` if the call succeeded, `reject` if it errored. `tools/gate.py` reads its rule from a base revision and treats the head as data. `demos/mcp-commerce`. | |

## 2. The gap, stated exactly

`warrant-mcp` writes `decision: reject` when a tool call returns an error. That record says the agent's side saw an error. It does **not** say the effect did not happen. A merchant that commits a charge and then times out produces exactly that record over an executed charge.

Conversely, `accept` on a successful call says the agent's side saw a success response. It says nothing about whether the counterparty would agree. Today both readings live in one field whose name, `decision`, suggests something else again.

**Three things are distinct:**

- **the decision:** to act, or not;
- **the attempt:** what the actor's side did and saw;
- **the effect:** what changed outside the actor's boundary, attested by whoever can attest it.

This is the ontology's ΔX-across-a-boundary, and it is the same discipline as WRT-022 §4.8, where a norm being in force is not the same as observed compliance: absence of evidence of an effect is not evidence of its absence.

## 3. Effects (part A)

### 3.1 The effect record

`warrant.effect@draft-1` is an addressed blob carried by a signed record. It has these fields:

- `intent`: the decision or duty it executes (a WarrantID);
- `effect_class`: the A0–A4 class, using the same table `warrant-mcp` pins in `under`;
- `idempotency_key`: unique per intended effect;
- `attempt`: the request bytes' hash, the response bytes' hash, and the attempt outcome (`RESPONDED_OK`, `RESPONDED_ERROR`, `NO_RESPONSE`);
- `executor`: the counterparty that performs the effect, named as an actor.

### 3.2 Effect state is an axis of its own

The effect state is computed per view. It is never read from `decision`.

| State | Established by |
|---|---|
| `INTENDED` | a decision or duty exists; no attempt is recorded |
| `ATTEMPTED` | an attempt record, by the actor's side (for example `warrant-mcp`): actor attestation of what was sent and seen |
| `CONFIRMED_EXECUTED` | a **receipt** from the executor (or a holder of a `receipt` grant, WRT-022 §4.1) that names the idempotency key |
| `CONFIRMED_NOT_EXECUTED` | a receipt from the executor stating non-execution for that key |
| `UNKNOWN` | an attempt with `RESPONDED_ERROR` or `NO_RESPONSE`, and no receipt. This is **never** read as not executed. |
| `CONTRADICTED` | two admitted receipts disagree |

**Four rules:**
1. **An attempt's outcome never sets the effect state** beyond `ATTEMPTED` or `UNKNOWN`. Only a receipt from the executor confirms.
2. **The idempotency key binds.** Two receipts for one key with different results give CONTRADICTED. A second attempt under the same key is the same intended effect.
3. **A compensation is a separate effect.** A refund for a charge, for example, is a new effect record whose `intent` is a repair transition (WRT-022 §4.4) citing the original. The original effect is never edited.
4. **The executor's identity is a trust question.** The recipient's trust snapshot decides whose receipts count. A receipt by the actor's own key is an actor attestation, not confirmation. Under one-operator custody the store says so.

### 3.3 Closure of an "execute" duty

A duty whose performance is an effect declares `effect_required: true`. Its DISCHARGED candidate is admitted only when its effect is `CONFIRMED_EXECUTED` in the view; otherwise the verdict is `UNMET_CONDITION`. This is WRT-021's named-child condition generalised to an effect: evaluated, never inferred.

A WRT-022 trigger `effect_state_changed(effect)` lets a closure become STALE if a later receipt contradicts it.

### 3.4 What `warrant-mcp` would change, and what it would not

- **Unchanged:** the proxy keeps sealing. Changing what its records mean would rewrite the meaning of existing stores.
- **New, optional:** the proxy also writes an effect record per sealed A2+ call, with `attempt` filled in and `effect_state` derivable as ATTEMPTED or UNKNOWN. Receipts come from executors or their adapters (the mock storefront in `demos/mcp-commerce` can sign one), never from the proxy.
- **The demo's honest outcome changes.** `shop.overspend_attempt` (refused by the store) can be `CONFIRMED_NOT_EXECUTED` only if the store signs that. Without such a receipt it is `UNKNOWN`, whatever `decision: reject` says.

## 4. Frontier gates (part B)

### 4.1 The rule we applied by hand

#135 waited for the S1 duty to be closed by a signed transition and a signed acceptance. Part B makes that a gate predicate:

> For a named use U (for example `merge` of a scope S), the gate admits only if
> (1) every duty the gate manifest *requires* is `ELIGIBLE(U)`, and
> (2) no duty the gate manifest *marks blocking* is open.

### 4.2 What blocks is declared, not inferred (the Codex rule)

Not every open loop blocks. A merge must not wait on every unowned question; questions bind nobody. Blocking is a typed act:

- **The gate manifest.** `warrant.gate-manifest@draft-1` names a use, a scope, the duties it requires, and how duties come to block: those opened in answer to findings filed against that scope by an actor holding a `review` grant for it.
- **The holder cannot unmark.** A finding's holder cannot unmark its duty as blocking. Only the finding's creditor, by release (WRT-021), or an adjudication (WRT-022 §4.4) can.
- **Unowned questions are reported, not blocking.** They appear in the gate report through `questions(scope)`.

### 4.3 The trust boundary is the gate's own

`tools/gate.py` already reads its rule from a revision the change cannot edit, because a change could otherwise rewrite its rule into a tautology (`tests/gate_isolation.py`). Part B extends this to every operand of reliance:

- **From the base revision:** `trust.json`, the recipient profile and the gate manifest. A PR that adds its own key to `trust.json` must not count its own acceptances.
- **From the head revision, as data:** the store (records and blobs). It is verified under the base revision's trust, and never executed.
- **The current workspace** for `subject_changed` triggers is the head revision (what would be merged), read through git, never checked out and run.

The gate report names the `assessment_id` (WRT-022 S1), so a reader can see exactly which bytes decided.

### 4.4 Outcomes

`ADMIT`, `REFUSE(causes)` and `UNASSESSED(causes)`. UNASSESSED covers an UNEVALUABLE trigger, a missing required duty, or a store that fails verification. As in `gate.py` today, whether a REFUSE blocks the merge is the installer's policy. The gate reports. It does not seize the merge button.

## 5. What this does not do

- It does not prove that an effect happened. It records who attests it, and whose attestations the recipient admits.
- It does not change `warrant-mcp`'s existing records or their meaning.
- It does not make the gate normative or install it in CI.
- It does not give independence: one operator's keys remain one custody.
- It covers neither path-class burden nor the "not established" section of the verify report (§7).

## 6. Plan

| Slice | Content | It fails if |
|---|---|---|
| E1 | effect records and the effect-state axis (§3.1–3.2) in a profile; vectors, including the timeout-after-commit case | an error response reads as `CONFIRMED_NOT_EXECUTED`, or a receipt by the actor's own key confirms |
| E2 | `effect_required` duties and the `effect_state_changed` trigger (§3.3) | an execute duty closes without a confirmed effect |
| E3 | `demos/mcp-commerce`: the storefront signs receipts; the proxy writes optional effect records | the overspend case reads as not executed without a store receipt |
| G1 | gate manifest plus the frontier predicate in `tools/gate.py`, with base-revision trust (§4) | a PR's own `trust.json` change counts its own acceptances, or an unowned question blocks |
| G2 | dogfood: the gate run over the real `dogfood/wrt-022` store for the next WRT-022 slice PR | the gate admits while a blocking duty is open |

## 7. Rejected or routed elsewhere, from the Gemini review

| Idea | Where it goes |
|---|---|
| Put sigma-resume's suspended computation into warrant's settlement code and conformance | **Not here.** That merges trajectories the ontology keeps apart. WRT-022 S2 (crossing with replay receipt) is the designed path: sigma owns the semantics, and warrant verifies a receipt. |
| Burden scaled by power depth, mapped to classes of repository paths (code, conformance vectors, contracts, gate/trust) | **WRT-022 S5** (per-act admission). The path class is one input to the recipient's tier map. `gate.wpl` already has `touches_ci` and `touches_deps`. |
| A "not established" section in the verify report (Gemini's LossReport) | **A separate, small proposal.** It extends the normative `verify-report` (SPEC §11) and needs its own version. |
| Cold Reconstruction Gap as a numeric bullshit score | **Deferred.** Without typed claims (WRT-022 §4.7) the subtraction is a model's opinion. Our packaging experiments are triply null (EXP-001, TRANSFER-1). Only with pre-registration, after claim axes exist. |
| Cross-model or human cosignature for epistemic and constitutional changes | **Narrowed.** Agent cosignatures under one operator are not independence. Where independence matters, the honest requirement is the owner's own signature. |
| Closing FLOW debts D16 and D17 through warrant's carriers | **manifesto's work.** Warrant can be cited as the substrate (carrier as content hash; endogenous kernel step versus exogenous attested input, as in WRT-022 §4.5). The debts belong to FLOW. |
| Gemini's reading of `contracts/KEY-*.json` as key-to-actor bindings | **A misreading.** Those are decision records for SPEC sentences. Key binding is the trust configuration plus key-state records (SPEC §5.1). |

## 8. Questions for review

1. Is `effect_state` best computed per view, as here, or should a confirmed receipt be a closure of its own (WRT-021) on an "execute" duty?
2. What should a receipt look like for executors that will never sign Warrant records? An adapter that signs on observation is again an attestation. Is a typed `adapter` grant enough honesty?
3. Is "blocking" correctly made a property of findings filed by a `review` grant holder? Or should the gate manifest name blocking duties explicitly, at the cost of a manifest update per finding?
4. The gate reads `trust.json` from the base revision. How then does a legitimate key enrolment ever take effect? Presumably in the PR after it merges. Is that delay acceptable, or does enrolment need its own gated path?
