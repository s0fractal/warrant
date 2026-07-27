# WRT-002: Key-state, authorized effective-lifecycle, and the R1 checkpoint

**Status:** DRAFT **rev 4** (2026-07-27) — model design only. **No production
signatures, no adoption, no code, no runtime registration, and NO frozen wire bytes.**
Specifies the settlement substrate WRT-001's stored (R1) wave citation depends on —
Deferred items **1 (authorized effective-lifecycle)** and **2 (key-state → R1
checkpoint)**. Adoption requires the full Decision Process; none is performed here.

**rev history.** rev 1 (no immutable cut) → rev 2 (cut, self-exclusion, causal
supersede, immutable pre-state) → rev 3 (all signature predicates frozen, ACI
provenance merge, jurisdiction policy-state, causal frontier binding). The rev-3
re-gate (`reviews/2026-07-codex-wrt-002-rev3-design-regate.md`) confirmed **the ACI
provenance carrier is sound** and asked to close the **event vocabulary and role
semantics** riding on it: total manifest, target-role authorization matrix,
root-adoption in the algebra, and distinct conflict resolvers. **rev 4 closes those
and still does not freeze bytes.** The conceptual key rev 4 adds: **event
*authorization* is permanent; event *effect* is lifecycle-gated** — two separate
functions (P2), which is what lets "never retroactively withdrawn" and "revocation is
a supersede" coexist without oscillation.

**Warrant-level, not wave-level.** These are general settlement primitives; WRT-001
and ADR-008 consume them; WRT-002 sits below both.

---

## 0. What this builds on in current Warrant (grounding)

(`impl/warrant.py`, `impl-go/main.go`, `SPEC.md`.) Supersede today is a bare marker —
no authorization, no eviction (SPEC.md:125; warrant.py:1136); `active_records`
(warrant.py:915-919) never subtracts supersede targets, so today eligibility ==
effective. Key-state is implemented (`keys_before`, warrant.py:867-876; genesis-pinned
`actors` from the trust config, DAG-ordered authorized rotations, latest-wins, **not
monotone**). Rotation (SPEC.md:103; `rotation_authorized`, warrant.py:885) allows
threshold **emergency replacement without the outgoing key**. Conflict is detected
(`conflict_actors`, warrant.py:945) but its **resolution is dormant** (the reduction
helper warrant.py:711 is never called with a non-empty `conflicted`; SPEC.md:105 rule
unwired; `conflict_actors` is live/global, not as-of-cut). No checkpoint / effective
set anywhere. Trust config: `actors`→keys; **`genesis.json` = ROOTS only**, advisory,
hash-pinned (SPEC.md:182). **A WarrantID hashes only the body**; SPEC §5 lets any
filing or co-signature be appended later without changing a WID (the seam §3 freezes).
**Ordinary records are NOT threshold-admitted**; a **genesis-pinned root has no
governing threshold policy** (§5.5). SPEC §9 calls a root well-signed only when its
filing signature is valid **and bound** where key-state is configured, while shipped
`_well_signed` (warrant.py:737) checks only the actor signature, not binding — a
choice rev 4 resolves (§4).

## 1. The problem (one coupled problem)

Naïve `active − supersede-targets` is a **censorship primitive**; a live-head stored
citation cannot converge in an append-only store (WRT-001:133-141). The effective set
is defined *by* key-state and policy-state over a *fixed historical cut*, authorized by
*frozen evidence* under a *role-appropriate* rule, committed by a *causally-anchored*
checkpoint. rev 4 specifies: the cut (§2); a **total** frozen manifest (§3); a **total
ACI-provenance algebra** with authorization ≠ effect, root-adoption, and filing-key
boundness (§4); a **target-role authorization matrix** (§5) over a **jurisdiction
policy-state** (§5.5); the checkpoint with distinct resolvers and succession (§6).

## 2. The immutable input cut

A checkpoint commits a **frontier `F`** (JCS-canonical sorted, deduplicated WIDs). The
cut is the **inclusive causal closure** `cut(F) = ⋃_{w∈F} closure(w)` — downward-closed,
a pure function of `F` + content-addressed bodies, no store head / `ts` / epoch. The
checkpoint record is filed after `F`, so it is **never in its own cut** (no identity
cycle). Post-cut growth is invisible → growth-immunity. `F` MUST be an **antichain** of
`cut(F)`. Frontier **completeness is a quorum-authorized claim, not a mechanical
proof**: requiring the checkpoint to be threshold-authorized by `J`'s governing
policy-state (§5.5) prevents unilateral *filer* omission; omission by the accountable
governing quorum is visible, not prevented mechanically.

## 3. Total, resolvable, frozen witness manifest

**Seam.** Every signature-dependent replay predicate is mutable under ordinary growth
(a WarrantID hashes only the body; filing signatures and co-signatures may be appended
later). Replay MUST NOT read a live envelope for anything inside `cut(F)`.

**Total manifest (one entry per cut record — no absence semantics).** The checkpoint
commits a **manifest that is total over `cut(F)`**: exactly one entry per record in the
cut, each an **explicit eligibility claim**:

- `eligible` + the exact typed witnesses it relied on:
  - `actor-filing` — the `body.actor.id` signature making the record well-signed
    (**required to be key-state-bound**, §4);
  - `incoming-pop` — a rotation's incoming-key proof-of-possession;
  - `threshold` — the exact multiset of signatures counted for a quorum event
    (root-adoption, rotation, supersede, policy-succession, conflict-resolution,
    checkpoint);
- `ineligible` + a **closed reason class** (`schema-invalid`, `no-valid-filing`,
  `unbound-filing-key`, `invalid-policy-shape`, …).

Replay uses **only** the manifest. A `missing`, `duplicate`, or **out-of-cut** record
entry, or a witness that no longer verifies, **invalidates the whole checkpoint**
(`unverified`) — this is the *mechanical completeness* rule. An `ineligible` entry is a
**quorum-authorized negative historical claim** (signature *absence* cannot be proved
from a mutable envelope, so the governing quorum vouches it) — an accountable,
*visible* decision, distinct from a mechanical failure. The manifest is a **resolvable
content-addressed blob**; `witness_root` is its digest (bytes deferred, §6).

**Three non-collapsing outcomes** (required vectors): (a) a genuinely-unsigned cut
record → `ineligible/no-valid-filing`, replay agrees; (b) a cut record with **no
manifest entry** → checkpoint `unverified` (incomplete); (c) a validly-signed cut
record the quorum marks `ineligible` → the effective set excludes it, but the act is a
*visible quorum decision*, not a mechanical error — attributable, not silent.

## 4. Total ACI-provenance algebra (authorization ≠ effect)

**Carrier (sound per the re-gate).** Authority state is a **set of authorized events**
+ their causal relation; `preEvents(w) = ⋃_{p∈w.prior} Events(p)` is an **ACI union**
(associative/commutative/idempotent) → a pure, order-independent function of the causal
past.

**Event vocabulary (now complete for `active_cut`).** A typed authorized event is one
of: `root-adoption`, `rotation`, `revocation` (a supersede of a rotation),
`policy-succession`, `key-conflict-resolution`, `policy-conflict-resolution`. Each is
authorized by its **manifest `threshold`/`incoming-pop` witnesses** under its role rule
(§5), against the **derived-effective state** (below) of its own `preEvents`.

**Authorization is PERMANENT; effect is LIFECYCLE-GATED (the P2 split).** Two separate
functions over an event set `E`:

1. **`authorized(e)`** — computed forward in causal order; once true it is **never
   withdrawn** (so `R:K0→K1` then a `K1`-signed matrix-authorized revocation `S` of `R`
   is authorized, because `K1` is in the derived state of `preEvents(S)`; no
   oscillation). Authorization is monotone and terminating.
2. **`effective(record)`** — computed by the reverse recurrence: an authorized event's
   **record** is effective iff `active_cut(record)` holds **and** no
   **matrix-authorized, effective** supersede targets it (§5). An event contributes to
   derived state **only while its record is effective** — so `S` revokes `R`'s *effect*
   forward without un-authorizing `S`.

**One derivation from the EFFECTIVE authorized events** (`derived(E)`):

- **`active_roots(J, E)`** — the genesis-pinned roots for `J`, plus every root reached
  by an **effective** `root-adoption` event whose adopting record is itself active for
  `J`. A `root-adoption` points at the adopted root via `subject.hash` (**not** via
  `prior` ancestry), so when the cut joins the adopting branch and the separately-rooted
  adopted branch, the adoption event is what activates the second branch for `J`.
  Adoption is reversible only through the §5 target-role matrix.
- **`active_cut(X, J, E)`** — `X` is root-reachable to `active_roots(J,E)`, has an
  `eligible` manifest entry, and its `actor-filing` witness is **key-state-bound in
  `derived(preEvents(X))`** (rev 4's explicit choice: an R1 filing witness MUST be by a
  key authoritative for the actor at the record's pre-state; an unbound/rotated-away key
  does not make a record effective — resolving the SPEC §9 vs shipped-`_well_signed`
  divergence in favour of binding).
- **key-state** — per actor, the causally-maximal effective authorized rotation; ≥2
  maximal DAG-unordered → **key-conflict marker** (key unusable, fail-closed).
- **policy-state** — per jurisdiction, the causally-maximal effective authorized
  policy-succession from the pinned anchor; ≥2 maximal → **policy-conflict marker**
  (§5.5).
- **effective set** — `{ X : active_cut(X,J,E) ∧ effective(X) }`.

**Determinism gate.** For a fixed `cut(F)` + manifest, `derived` MUST be **byte-identical
under every parent/list/iteration permutation** — a required differential vector.

## 5. Target-role authorization matrix

A generic SELF rule is unsafe: it lets one filer roll back a **quorum-governed** event
(A files a 2-of-3 `policy-succession`, then A alone supersedes their own succession
record — role confusion). Authorization to **supersede X** is keyed by **X's role**,
evaluated against `derived(preEvents(S))` with committed witnesses, and always requires
the causal rule `X ∈ closure(S)\{S}`:

| Target `X`'s role | Authorization to supersede `X` |
|---|---|
| ordinary actor-owned record | **SELF** (a key authoritative for `X.actor.id`) **or** `J`'s governing policy-state |
| `rotation` / `revocation` | the SPEC §5.1 **current-policy rule** governing that actor's key-state (threshold against pre-state keys, or the same actor's bound key where no policy) |
| `policy-succession` / `policy-conflict-resolution` | the **governing policy-state quorum** (never a single SELF) |
| `root-adoption` | the **adopting-jurisdiction authority** (the policy under which the adoption was authorized) |
| `key-conflict-resolution` | the same quorum that authorized the resolution |
| `checkpoint` | **not** ordinary supersession — governed only by checkpoint succession/conflict (§6) |

`X.under` is **never** a lifecycle authority (a check/evidence policy). Everything is
per-jurisdiction. This matrix is what §4's `effective(record)` consults when deciding
whether a supersede is matrix-authorized.

## 5.5. Jurisdiction policy-state

Shipped settlement has no persistent per-jurisdiction policy, and a genesis-pinned root
has none — so §5's "governing policy" needs an explicit primitive.

- **Anchor.** The trust config pins, per genesis root, a **governing policy**
  (`min_sigs`/`actors`), alongside `actors`→keys. A root with **no** pinned policy is
  **not checkpoint-capable**: only SELF supersession of ordinary records is available,
  and **no R1 checkpoint can be authorized there** (fail-closed, deliberate).
- **Succession.** Changed only by a **`policy-succession` event** (a threshold `accept`
  whose subject is a new governing-policy blob), authorized by the **current** governing
  policy-state at its pre-state (matrix row above). Tracked in `derived` exactly like
  key-state.
- **Policy conflict + its own resolver.** ≥2 maximal unordered effective
  policy-successions → policy-conflict marker (fail-closed). Resolved by a
  **`policy-conflict-resolution`** event: a threshold `accept` whose subject is a single
  chosen governing-policy blob, which **DAG-descends every maximal conflicting
  policy-succession** and is authorized by the **greatest common causal-predecessor
  policy-state** those forks share (the last non-conflicted policy all descend from). If
  the competitors share **no** single authorized common-predecessor policy inside the
  cut, the jurisdiction's policy-state is **terminally conflicted** (fail-closed; no
  checkpoint authorizable). Its witnesses + a cleared marker enter provenance.

## 6. The R1 checkpoint — resolvers, succession, multi-root scope; BYTES DEFERRED

**Vehicle.** An `accept` Warrant whose subject is a canonical `checkpoint@v1` blob
(rotation-shaped) — **no new body version**. Its authorization is the enclosing
`accept`'s signatures satisfying `J`'s **governing policy-state** (§5.5), never
self-filed.

**Causal binding.** `checkpoint.body.prior` MUST equal the committed `frontier` (same
sort/dedup) — one `cut(F)` for both authorization and replay. **Multi-root scope
(P2):** a multi-root frontier makes the checkpoint reachable from several roots under
shipped `record_roots`, but all checkpoint semantics are scoped **only to the
`jurisdiction` named in its subject** — the checkpoint is not itself an adoption or a
member of any other jurisdiction's effective set.

**Committed subject blob, for `(J, sequence)`:** `jurisdiction`; `sequence`;
`frontier` (= `body.prior`); `effective_set_root`; `key_state_root`;
`policy_state_root`; `witness_root` (resolvable total manifest).

**Succession + checkpoint conflict resolver.** A checkpoint at `sequence n+1` MUST
causally descend the accepted checkpoint(s) at `n` and extend their cut. Two competing
accepted checkpoints `Cₙᴬ`, `Cₙᴮ` at one `(J,n)` are a settlement conflict; the chain
is resolved only by a **resolver checkpoint `Cₙ₊₁`** that **descends every maximal
competitor** and whose frontier's cut **extends the union** of the competitors' cuts,
authorized by a **non-conflicted policy-state** (if policy-state is itself conflicted,
no checkpoint is authorizable until §5.5 resolves it — simultaneous policy+checkpoint
conflict is fail-closed). If no `Cₙ₊₁` can descend all maximal competitors, the chain
is **terminal**. A gap, a non-extending higher sequence, or a resolver that misses a
competitor is `unverified`.

**Replay.** Resolve the `accept`; verify its signatures satisfy the derived governing
policy-state at the frontier; verify `body.prior == frontier`, the antichain, and the
succession/resolver rules; rebuild `cut(frontier)`; run §3/§4/§5 using **only** the
resolvable manifest; require recomputed `effective_set_root` / `key_state_root` /
`policy_state_root` to **equal** the committed values. Any mismatch, non-total or
over-broad manifest, unbound/failing witness, `prior≠frontier`, broken succession, or
active conflict marker where a singular result is required → `unverified` (ERR for a
settlement-active citation, WRT-001 §5).

**Binding from WRT-001.** WRT-001 §6's stored `wave@v1` reason names an authorized
checkpoint WID; the citation ranks over that checkpoint's effective set (minus its own
WID), never live-head.

**BYTES DEFERRED (explicit).** rev 4 does not freeze the `checkpoint@v1` / manifest /
policy-blob schemas and canonical layouts; the domain-separated hashing inputs for the
four roots; the canonical encoding of key-state and policy-state **including conflict
markers**; `sequence` genesis/gap encoding; or validation severities. Per the gate,
bytes are frozen only **after** this model (§§2–6) survives another re-gate.

## 7. Countervectors before the next design gate

Permanent Python↔Go differential vectors, fail-closed and bounded:

- **manifest (§3):** genuinely-unsigned record → `ineligible`; **omitted entry →
  unverified**; validly-signed record marked `ineligible` → excluded but attributable;
  duplicate / out-of-cut entry → `unverified`; filing / co-signature appended after
  checkpoint → replay unchanged.
- **algebra (§4):** merge-permutation → **byte-identical `derived`**; rotation enables
  its own revocation → deterministic; adopted-root cross-branch merge → second branch
  activated only via the `root-adoption` event; **bound-vs-unbound filing** → unbound
  filing key ⇒ not effective; authorization-permanent-vs-effect-gated (a revoked
  rotation's later supersede stays authorized).
- **role matrix (§5):** **one-filer rollback of every quorum-governed target**
  (policy-succession, threshold rotation/revocation, root-adoption,
  conflict-resolution, checkpoint) → rejected; ordinary SELF supersede → effective;
  foreign non-self below quorum → ineffective; `X.under`-only → never authorizes;
  stale/unordered supersede → ineffective.
- **policy-state (§5.5):** pinned-genesis-without-policy → no checkpoint; two adoption
  `under` policies → neither is authority; policy succession by the prior policy; policy
  fork → `policy-conflict-resolution` by the common predecessor; no common predecessor →
  terminal.
- **checkpoint (§6):** `body.prior ≠ frontier` → `unverified`; higher-sequence rollback
  → `unverified`; `Cₙᴬ/Cₙᴮ → Cₙ₊₁` resolver descends both / misses one; simultaneous
  policy+checkpoint conflict → fail-closed; multi-root frontier scoping.

## 8. Non-goals, ordering, and the gate

- **Design only.** No signatures, adoption, registration, code, or frozen bytes. The
  sigma reference path keeps labelling its stored-reason demo as *anticipating* R1.
- **Ordering.** rev 4 is the model; a re-gate of §§2–6 precedes the byte-freeze
  revision, which precedes implementation. Items 1–2 precede the WRT-001 §8 budget
  freeze. §7-novelty/tunnel and the governed profile anchor remain deferred.
- **Gate.** Adoption requires ≥3 independent-family review, all P0/P1 closed; a
  reference-implementation gate with all §7 vectors ALL PASS **and** Python↔Go
  differential parity (incl. byte-identical merge-permutation `derived`) over frozen
  bytes; a settlement/liveness re-check of rotation + policy-succession + both conflict
  resolvers + checkpoint succession (the perpetual-veto self-destruct class,
  SPEC.md:105 + GOV-001:195-205); and a 2-of-3 governance threshold warrant. Until then
  `wave@v1` stays structurally open for stored precedent; only the ephemeral R0 query
  is available.
