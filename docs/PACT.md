# Bilateral / Multilateral Pacts & Computed-Loss Composition (`pact@1`)

`warrant.pact` defines a fail-closed cryptographic commitment protocol and a mechanical computed-loss
composition algebra over Warrant 3's four-kind envelope (`entity`, `attest`, `challenge`) without
modifying the core engine.

## 1. Motivation

Static Warrant 3 records unilateral claims, obligations and hierarchical delegations (`grant@1`). Two
autonomous peers — agent-agent or agent-human — that do not share a master need:

1. **Mutual, non-unilateral commitment:** no peer is bound until every named party signs the exact
   content-addressed proposal digest (`pact_id`), and no party can silently escape after activation.
2. **Verifiable settlement & breach attribution:** equivocation (conflicting signed fulfillments) or
   expiry with partial fulfillment deterministically transitions the pact to `BREACHED`, naming exact
   `defaulters` and `honest_parties` and freezing any escrowed `grant@1` capabilities.
3. **Computed-loss composition (default-deny frame law):** chaining multi-agent contracts must not
   silently drop prior guarantees. Silence about a guarantee in a downstream step is computed as a
   loss, never assumed preserved.

## 2. Pact State Machine (`pact@1`)

A proposal is a root `entity` record (`schema: "pact@1"`, `state: "proposed"`) with:
- `parties`: $\ge 2$ distinct valid actor ids (no self-pact, no duplicates).
- `commitments`: one entry per party (`requires`, non-empty `gives`, optional `preserves`,
  `declared_losses`, `deliverable`).
- `expires_at`: non-negative integer timestamp.
- `arbiter` *(optional)*: neutral actor id strictly outside `parties` (`ARBITER_IS_PARTY` refused).
- `escrow_grants` *(optional)* & `escrow_mode` (`"active"` | `"settled"`): `grant@1` ids whose
  executability is gated by the pact's resolved state. A binding holds only when the grant's issuer is a party
  that bound it, as the pact's proposer or by accepting it: a pact between others never freezes a grant.
- The proposal is a lineage root (`lineage` null); its `prev` is its actor's chain, which may hold earlier records.

| State | Condition |
| :--- | :--- |
| `INVALID` | Bad/untrusted signature, `< 2` parties, duplicate parties, arbiter in parties, or commitment mismatch |
| `PROPOSED` | Valid proposal, `as_of <= expires_at`, fewer than all parties accepted, no valid withdraw |
| `WITHDRAWN` | A party signed `pact/withdraw` strictly before unanimous activation |
| `EXPIRED` | `as_of > expires_at` before unanimous activation (no defaulter) |
| `ACTIVE` | All parties signed `pact/accept` matching `pact_id` before `expires_at`, no prior withdraw, no breach, `as_of <= expires_at` |
| `SETTLED` | Every party signed a consistent, complete `pact/fulfill` in `[activation_at, expires_at]` (plus `pact/settle` by `arbiter` if configured) |
| `BREACHED` | Equivocation (`EQUIVOCATION`), valid arbiter `pact/breach` (`ARBITER_BREACH`), or `ACTIVE` passing `expires_at` unfulfilled (`EXPIRED_DEFAULT`) |

### Key Safety Invariants

- **Unanimous activation (`PC-1`, `PC-2`):** partial accepts bind nobody; an accept whose `pact_digest`
  differs from `pact_id` or arrives after `expires_at` is refused.
- **No post-activation escape (`PC-3`):** `pact/withdraw` at `at >= activation_at` is refused (`ALREADY_ACTIVE`).
- **Complete fulfillment (`PC-4`):** `pact/fulfill` missing any label in `commitments[party].gives` is refused (`INCOMPLETE_FULFILLMENT`).
- **Equivocation proof (`PC-5`):** two signed `pact/fulfill` records by the same party with distinct
  `evidence_digest`s trigger `BREACHED` (`EQUIVOCATION`) recording both conflicting record ids.
- **Arbiter neutrality & authorization (`PC-6`):** only the designated `arbiter` (never a member of `parties`)
  may file `pact/settle` or `pact/breach`.
- **Escrow freeze (`PC-7`):** `resolve_escrow` gates every bound `grant@1` on both `grant.status == "ACTIVE"`
  and the binding pact holding the required state (`ACTIVE` or `SETTLED`). Any breach/withdrawal/expiry
  immediately freezes the escrowed capability, and every grant delegated from it: `warrant.delegate.assess_delegated`
  reads such a grant as `ESCROW_FROZEN` and admits no record under it (`frozen_grants`).
- **One horizon:** a pact is resolved from the records dated at or before `as_of`; a later accept, fulfilment,
  withdrawal or arbiter record does not change an earlier view.

## 3. Computed-Loss Composition Algebra (Default-Deny Frame Law)

For ordered recipes $R_1, \dots, R_k$ where $R_i = (P_i, G_i, F_i, L_i, B_i)$:
- Compatibility at step $i \ge 2$ requires $P_i \subseteq \text{avail}_{i-1}$ and $B_{i-1} \cap B_i \neq \emptyset$.
- Carried guarantees at step $i$: $\text{carried}_i = G_i \cup (F_i \cap \text{avail}_{i-1})$.
- Silent drops at step $i$: $\text{dropped}_i = \text{avail}_{i-1} \setminus \text{carried}_i$.
- Computed losses: $L_{\text{computed}} = \bigcup_i L_i \cup \bigcup_i \text{dropped}_i$.

Example: if $R_1$ gives `{"auth", "signed"}` with $L_1 = \emptyset$ and $R_2$ requires `{"signed"}`,
gives `{"signed", "published"}`, and declares $L_2 = \emptyset$ without listing `"auth"` in `preserves`,
`compose_recipes([R_1, R_2])` mechanically reports `silent_drops = ["auth"]`, `computed_losses = ["auth"]`,
and `lossless = False`. Re-establishing `"auth"` at a later step restores it to `gives` without erasing
the historical drop event from `loss_events` (anti-laundering).

## 4. Proof-Carrying Guarantee Witnesses (`warrant.witness`, F4 / D23)

Opaque guarantee labels (`"viable"`, `"verified"`) allow two peers to declare the same word while
attaching different verification semantics or submitting arbitrary digests. `warrant.witness` closes
that seam offline and fail-closed:

- Commitments may carry `witnesses: {label: {"verifier": id, "params": {...}}}` (keys must lie in
  `gives`) and `required_witnesses` (keys must lie in `requires`).
- Built-in verifiers over `Snapshot.blobs` and verified records:
  - `sha256-blob@1` — blob exists in `snap.blobs` and SHA-256 matches digest.
  - `vars1-coalition-viability@1` — verifies `minds/coalition.py` certificates (`live_env`,
    `policy_verified`, integer `min_sovereign_bps` 0..10000, `max_blocked_states`, `required_states`).
  - `vars1-spore-receipt@1` — verifies `minds/spore.py` receipts (`SETTLED`, strict ATP conservation
    `atp_spent + atp_remaining == atp_budget`, `partiality_inflated is False`, `max_atp_spent`).
  - `vars1-identity-lineage@1` — verifies `minds/identity.py` certificates (`genesis`/`step`/`fork`
    shape, acyclic provenance/lineage suffix consistency, isolated fork relations, `min_atp`,
    `require_ancestor`, `require_distinct_from`, `required_invariants`).
  - `vars1-trajectory-mass@1` — verifies `minds/trajectory.py` certificates (`trajectory_safe is True`,
    unique `act_id`s, zero counted refutations, exact integer mass & total-weight accounting,
    `min_mass`, `min_steps`, `max_horizon`, `max_refuted`).
  - `warrant-record@1` — verifies a signature-verified Warrant 3 record dated `<= as_of`.
- Unknown verifiers fail closed (`UNKNOWN_VERIFIER`). A `pact/fulfill` failing any witness check is
  refused (`UNGROUNDED_GUARANTEE`), preventing settlement and keeping `escrow_mode="settled"` grants
  (and their sub-delegated descendants) `ESCROW_FROZEN`.
- `compose_recipes` checks `(verifier, canon_params_digest)` equality for `required_witnesses` and
  refuses semantic equivocation (`VERIFIER_SPEC_MISMATCH`); re-giving a label without a witness strips
  its prior witness spec (anti-laundering).

## 5. CLI and Agent Interface

```bash
python3 -m warrant pact status [--as-of T]
python3 -m warrant pact escrow [--as-of T]
python3 -m warrant pact compose PACT_ID_1 PACT_ID_2 ... [--as-of T]
```

Agent API / MCP tool: `warrant_pact` with `op: "status" | "escrow" | "compose"`.
