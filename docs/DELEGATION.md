# Capability Delegation (`grant@1`)

Static Warrant 3 binds Ed25519 public keys to actors in the receiver's `trust` and roles to actors in `profile`.
That leaves autonomous agents with no safe way to delegate narrow, time-bounded, revocable authority to an ephemeral
sub-agent or peer without handing over a master key or asking every receiver to edit `.warrant/v3.json`.

`warrant.delegate` (`grant@1`) adds **attenuating cryptographic capability delegation** on top of Warrant 3's
unchanged four-kind envelope (`schema`, `entity`, `attest`, `challenge`) and pure `View` engine.

## 1. Capability Meet-Semilattice (`Cap`)

A capability is a tuple:

$$
c = (\text{roles},\; \text{kinds},\; \text{schemas},\; \text{lineages},\; [\text{not\_before}, \text{not\_after}],\; \text{max\_depth})
$$

where `schemas = None` and `lineages = None` denote the top element $\top$ (unrestricted). The meet operator
$c_1 \sqcap c_2$ is componentwise intersection on sets, $[\max(nb_1, nb_2), \min(na_1, na_2)]$ on validity windows,
and $\min(d_1, d_2)$ on remaining redelegation depth.

The partial order $c_1 \sqsubseteq c_2$ holds iff $c_1 \sqcap c_2 = c_1$:
- **Idempotence:** $c \sqcap c = c$
- **Commutativity:** $c_1 \sqcap c_2 = c_2 \sqcap c_1$
- **Associativity:** $(c_1 \sqcap c_2) \sqcap c_3 = c_1 \sqcap (c_2 \sqcap c_3)$

## 2. Cryptographic Chaining & Strict Monotonic Attenuation

A `grant@1` root entity record binds a `delegate` actor id and an Ed25519 public key `delegate_key`:

1. **Root anchor:** A root grant (`parent: null`) must verify under a key the receiver's `trust` binds to its `actor`,
   and every role in `body.roles` must be held by that root actor in the receiver's `profile`. Attempting to grant a
   role the root actor does not hold fails closed (`WIDENING`).
2. **Chained delegation:** A child grant (`parent: <parent_grant_root>`) must have `actor == parent.delegate` and
   verify under `parent.delegate_key`.
3. **Strict depth decrease:** Every hop requires `parent.max_depth >= 1` and `0 <= child.max_depth <= parent.max_depth - 1`
   (`DEPTH_EXCEEDED` otherwise). Every valid chain is therefore finite and acyclic by construction.
4. **No silent clamping (fail-closed attenuation):** Any hop whose declared `roles`, `kinds`, `schemas`, `lineages`,
   or `[not_before, not_after]` widens its parent fails closed with `WIDENING`.

## 3. Transitive Ancestral Brake & Fork Invalidation

A grant lineage is invalidated (yielding zero delegated authority, and turning every descendant into
`ANCESTOR_INVALID`) whenever any of the following holds:

- **Revocation:** A `state: "revoked"` successor signed by the grant's own issuer **or any ancestor issuer** in its
  delegation chain (transitive ancestral brake: a root actor can directly revoke a compromised grandchild even if the
  intermediate delegate refuses to cooperate).
- **Fork:** Two valid versions succeed the same version in the grant lineage (`FORKED`).
- **Standing challenge:** A valid `challenge` targeting any version of the grant lineage signed by a receiver-trusted
  `challenger`, the grant's issuer, or any ancestor issuer (`CHALLENGED`).
- **Time bounds:** `as_of < not_before` (`NOT_YET_VALID`) or `as_of > not_after` (`EXPIRED`).

## 4. Scoped Assessment, Anti-Laundering & No-Sybil-Inflation

`assess_delegated(snap, trust, profile, as_of)` evaluates the store with verified active grants while preserving
three core security theorems:

1. **Scope enforcement:** Every delegated record must fall within the authorizing grant's `kinds`, `[not_before, not_after]`,
   `schemas`, `lineages`, and target-relevant `roles`. Out-of-scope records are refused (`DELEGATION_OUT_OF_SCOPE`,
   `DELEGATION_OUTSIDE_WINDOW`, `DELEGATION_UNKNOWN_TARGET`, `DELEGATION_NOT_ACTIVE`) and excluded before assessment.
2. **Anti-laundering (`DELEGATION_SELF_ACCEPT`):** A delegated `attest` can never accept a version authored by its
   root issuer, any ancestor in its delegation chain, or another delegate anchored to the same root issuer.
3. **No-Sybil-Inflation (`DELEGATION_QUORUM_INFLATION`):** Delegation never multiplies voting weight. Toward any
   guard's `quorum`, distinctness is counted by **root principal** (`root_issuer` for delegated records, `actor` for
   static records): an actor and all of its delegates together count at most once per target version.
4. **Cross-grant role isolation:** `_ScopedView` binds each delegated record strictly to the `roles` of its own
   authorizing grant, so a delegate holding distinct role subsets across multiple grants can never bleed roles across
   targets.

## 5. CLI & Agent Interface

- CLI: `warrant delegate schema | grant | revoke | grants | assess`
- Python API / CLI: `warrant_agent.api.call(cfg, "delegate", {"workspace": W, "op": "grants" | "assess", "as_of": ...})`
- MCP: `warrant_delegate(workspace, op="grants"|"assess", as_of=None)` (read-only)

## 6. Limits

- Delegated keys never authorize `schema` records (`KINDS = ("attest", "challenge", "entity")`).
- Like static Warrant 3, completeness of the store stays `UNATTESTED`: an unseen revocation in another clone is not
  known until delivered (or bounded against a witnessed root).
- `warrant.engine.View` itself stays unchanged and static; delegation is opt-in through `warrant.delegate`.
