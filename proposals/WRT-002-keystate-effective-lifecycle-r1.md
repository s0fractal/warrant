# WRT-002: Key-state, authorized effective-lifecycle, and the R1 checkpoint

**Status:** DRAFT **rev 5** (2026-07-27) — model design only. **No production
signatures, no adoption, no code, no runtime registration, and NO frozen wire bytes.**
Specifies the settlement substrate WRT-001's stored (R1) wave citation depends on —
Deferred items **1 (authorized effective-lifecycle)** and **2 (key-state → R1
checkpoint)**. Adoption requires the full Decision Process; none is performed here.

**rev history.** rev 1 (no immutable cut) → rev 2 (cut, self-exclusion, immutable
pre-state) → rev 3 (all signature predicates frozen, ACI provenance merge, policy-state,
causal frontier binding) → rev 4 (total manifest, target-role matrix, root-adoption in
the algebra, authorization ≠ effect). The rev-4 re-gate
(`reviews/2026-07-codex-wrt-002-rev4-design-regate.md`) confirmed **the cut, total
manifest, ACI carrier, auth/effect split, and resolver shapes all survive**, and asked
to close the remaining **authority algebra around lifecycle**. **rev 5 closes those and
still does not freeze bytes:** a supersede is a typed `lifecycle-supersede` carrying its
**authorization class** so it cannot be rolled back by a weaker authority through depth
(§4/§5); governance reversal uses the **current** effective policy-state, not a retired
historical quorum (§5); `active_roots` is the **least fixed point** from genesis so
untrusted roots cannot mutually bootstrap (§4); and emergency rotation's **filer-vs-
target** distinction is pinned so the bound-filing rule preserves it (§4).

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
checkpoint. rev 5 specifies: the cut (§2); a **total** frozen manifest (§3); a **total
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

**Event vocabulary (complete for `active_cut`).** A typed authorized event is one of:
`root-adoption`, `rotation`, `lifecycle-supersede`, `policy-succession`,
`key-conflict-resolution`, `policy-conflict-resolution`. A **`lifecycle-supersede`** is a
supersede of **any** record and **carries the authorization class it exercised** (SELF /
jurisdiction-policy / rotation-policy / adoption-authority / resolution-quorum); a
`revocation` of a rotation is the rotation-policy case. The class travels on the
lifecycle edge so superseding a supersede cannot downgrade authority (§5). Each event is
authorized by its manifest `threshold`/`incoming-pop`/`actor-filing` witnesses under its
§5 role rule, against the **derived-effective state** (below) of its own `preEvents`.

**Emergency rotation — filer vs target (P2).** A `rotation`'s enclosing `body.actor.id`
(the **filer**) MAY be an already-bound quorum actor **distinct from** the target actor
named in the incoming-key subject blob. The filer's `actor-filing` witness is
key-state-bound (satisfying the rotation record's own eligibility); the **target actor's
incoming key supplies the separate `incoming-pop`**, and the governing `threshold`
authorizes it. **No outgoing target-actor signature is required** — so the threshold
emergency-replacement path survives the bound-filing rule. A conforming verifier MUST
NOT require the rotated actor to file the record (which would make the incoming unbound
key fail `active_cut` and silently delete the emergency path).

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

- **`active_roots(J, E)`** — the **LEAST fixed point** seeded by exactly `J`'s
  trust-config-pinned genesis roots, then repeatedly adding the target root of every
  **effective, authorized `root-adoption` whose adopting record is ALREADY root-reachable
  to the current set**. An adoption points at the adopted root via `subject.hash`
  (**not** `prior` ancestry), so it is what joins a separately-rooted branch into `J`.
  Least-FP is **mandatory**: two non-pinned roots that mutually adopt each other activate
  **neither** — a greatest/self-supporting closure is forbidden (it would let untrusted
  roots bootstrap their own authority; ACI union alone does not choose between the two
  fixed points). **Stratification:** (1) `active_roots` least-FP from genesis; (2)
  `active_cut` (reachability + bound eligible filing); (3) the effectiveness recurrence.
  An event on a not-yet-active root never contributes, so it cannot bootstrap the root
  that would make it active. Adoption is reversible only through the §5 matrix.
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
| ordinary actor-owned record | **SELF** (a key authoritative for `X.actor.id`) **or** `J`'s **current** governing policy-state |
| `rotation` (incl. `revocation`) | the SPEC §5.1 **current-policy rule** governing that actor's key-state (threshold against pre-state keys, or the actor's bound key where no policy) |
| `lifecycle-supersede` | **authority no weaker than the class `X` itself exercised** (the class carried on `X`'s lifecycle edge, §4): a quorum-class supersede is reversible only by that quorum class, a SELF supersede by SELF — **no downgrade through depth** |
| `policy-succession` / `policy-conflict-resolution` | `J`'s **current** governing policy-state quorum (never a single SELF) |
| `root-adoption` | `J`'s **current** effective governing policy-state at `preEvents(S)` — **NOT** the historical policy that authorized the original adoption |
| `key-conflict-resolution` | `J`'s **current** governing policy-state — **NOT** the historical quorum that filed the resolution |
| `checkpoint` | **not** ordinary supersession — governed only by checkpoint succession/conflict (§6) |

**Current, not historical, governance (closes quorum resurrection).** Reversal of a
`root-adoption` or a governance resolution uses the **current effective jurisdiction
policy-state at `preEvents(S)`**, so a retired quorum (`P0={A,B}` after a valid
succession to `P1={C,D}`) can no longer roll back its historical acts; rotation
revocation continues under its SPEC current-policy rule (already current at pre-state).

**Authority provenance travels the lifecycle edge (closes laundering).** Because every
supersede is a `lifecycle-supersede` carrying its class (§4), superseding it needs
authority no weaker than that class: quorum `S1` → filer-only `S2` **fails**, and
`quorum S1 → quorum S2 → SELF S3` cannot launder authority down through depth.

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

**BYTES DEFERRED (explicit).** rev 5 does not freeze the `checkpoint@v1` / manifest /
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
  rotation's later supersede stays authorized); **mutual-untrusted-adoption** (two
  non-pinned roots adopt each other) → **neither** active (least-FP); one-pinned /
  one-adopted → adopted becomes active; **emergency rotation** (bound quorum filer, a
  *different* target actor in the key blob, no outgoing target signature, incoming-key
  PoP + quorum) → authorized and the new key binds.
- **role matrix (§5):** **one-filer rollback of every quorum-governed target**
  (policy-succession, threshold rotation, root-adoption, conflict-resolution, checkpoint)
  → rejected; **authority-laundering through depth** (quorum `S1` → filer-only `S2` →
  fails; quorum→quorum→SELF `S3` → fails) → rejected; SELF `S1` → same-actor `S2` may
  reinstate; **retired-quorum resurrection** (`P0` supersedes an adoption/resolution
  after succession to `P1`) → rejected (current policy-state governs); ordinary SELF
  supersede → effective; foreign non-self below quorum → ineffective; `X.under`-only →
  never authorizes; stale/unordered supersede → ineffective.
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
- **Ordering.** rev 5 is the model; a re-gate of §§2–6 precedes the byte-freeze
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
