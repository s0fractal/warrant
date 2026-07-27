# WRT-002: Key-state, authorized effective-lifecycle, and the R1 checkpoint

**Status:** DRAFT / PROPOSED (2026-07-27) — design only. **No production signatures,
no adoption, no cross-implementation port.** This document specifies the settlement
substrate that WRT-001's stored (R1) wave citation depends on — WRT-001 §Deferred
items **1 (authorized effective-lifecycle)** and **2 (key-state → R1 checkpoint)**,
which that document declares **inseparable** ("the effective set is defined *by* key
state") and orders **before** the budget freeze (WRT-001 §8). Adoption requires the
Decision Process: ≥3 independent-family review with every P0/P1 closed, a reference
implementation gate, and a 2-of-3 governance threshold warrant — **none of which
this draft performs.**

**Why Warrant-level, not wave-level.** Key-state, authorized supersession, and a
point-in-time effective checkpoint are **general settlement primitives** — they
govern *any* stored settlement citation, not only `sigma-glyph.wave@v1`. WRT-001
consumes them; it does not own them. Kept separate so WRT-001 stays the runtime
contract and WRT-002 is the substrate it binds.

---

## 0. What this builds on in current Warrant (grounding)

The design is written against the EXACT shipped settlement semantics; it does not
reinvent them. Anchors (`impl/warrant.py`, `impl-go/main.go`, `SPEC.md`):

- **Supersede is a bare marker today — no authorization, no eviction.** SPEC §7
  (SPEC.md:125) requires only that `subject.hash` be the superseded WarrantID; there
  is **no** clause on *who* may supersede. The impl checks only subject presence
  (warrant.py:1136 / main.go:2235) and a valid self-signature by `body.actor.id`.
  Crucially, `active_records` (warrant.py:915-919 = `record_roots(wid) ∩ active_roots`,
  well-signed, valid-policy) **does not subtract supersede targets at all** — so
  today a superseded record **remains eligible**. Eligibility == effective. R1 must
  introduce BOTH the authorization gate AND the effective/eligible distinction.
- **Key-state is well-defined and implemented.** `keys_before(wid)`
  (warrant.py:867-876 / `keysBefore` main.go:1909): start from genesis-pinned
  `actor→keys`, walk ancestors in DAG order (`(depth, wid)`), and for each *authorized*
  rotation replace that actor's key set — **latest authorized rotation wins**, else
  the genesis key. `threshold_keys(wid) = keys_before(wid)` (warrant.py:878-883);
  a signature counts for an actor only if valid AND by a key bound at that DAG
  position (SPEC.md:113). Seeded by the trust config's `actors` (warrant.py:835).
- **Rotation** (SPEC.md:103; `rotation_authorized`, warrant.py:885-909 /
  main.go:1938-1985): an `accept` whose subject is a key blob `{actor,key}`, requiring
  proof-of-possession by the incoming key **plus** either the threshold satisfied
  against `prior_keys = keys_before(wid)`, or (no explicit policy) a valid signature
  by a key already bound to the actor. The incoming key's PoP does not count toward
  the threshold.
- **Conflict is detected but its RESOLUTION is dormant.** `conflict_actors`
  (warrant.py:945-953) flags an actor with >1 maximal (mutually DAG-unordered)
  authorized rotation; SPEC.md:105 says a conflicted key MUST NOT count toward a
  quorum "until a later warrant — authorized by the unconflicted remainder —
  resolves it; if the threshold would become unsatisfiable, it is reduced to exclude
  the conflicted actor strictly for conflict resolution." The reduction helper
  exists — `_threshold_satisfied(..., conflicted=frozenset())` (warrant.py:711-717) —
  **but every derivation caller passes an empty `conflicted` set**; `conflict_actors`
  is computed *after* the fixpoint and consumed only by the bound-report and a
  `WARN: key-state conflict` (warrant.py:1158). So the spec'd resolution path is
  present-but-unwired. (There is **no** `resolved_key_state` identifier in-tree; the
  liveness fix is the DAG-descendant non-conflict rule of SPEC.md:105, pinned by the
  stale-rotation-replay test tests/settlement.py:302-330, with the rejected
  "freeze-transitions" alternative recorded in GOV-001:195-205.)
- **Everything is live-head; no checkpoint exists.** `_settlement_context` reasons
  over ONE immutable observation of `all_records()` (warrant.py:786-792), but that is
  the *current* head, recomputed each verify. There is no `authorized_effective_active_for`,
  no effective set, and no committed point-in-time snapshot anywhere in either impl
  (those names appear only in proposals/reviews). `active_records`/key-state are
  mutually dependent and iterated to a fixpoint (warrant.py:911-937).
- **Trust config / genesis seed authority, fail-closed.** Closed schema
  `{genesis_roots, actors, genesis_json_sha256}` (warrant.py:592-619). `actors` →
  genesis keys; `genesis_roots` → initial `active_roots` (∩ well-signed); a root is
  settlement-active only if genesis-pinned or adopted by an active root's threshold
  (SPEC.md:178, warrant.py:923-935). `genesis.json` is **advisory** and used only if
  its hash matches the pinned `genesis_json_sha256` (single read, TOCTOU-safe,
  warrant.py:625-646); otherwise `WARN: genesis.json unverified` (SPEC.md:182).

The one load-bearing fact the design turns on: **Warrant settlement authenticates
only a self-signature for supersede, and does not evict on it.** That is the hole
items 1–2 close.

---

## 1. The problem (two coupled gaps)

### 1a. Naïve effective-lifecycle is a CENSORSHIP PRIMITIVE

Warrant's `active_records` is an **eligibility** set: a record an active `supersede`
has targeted is *still eligible* (SPEC §7). It is tempting to define the effective
set as `active_records` **minus every active-supersede target**. But because
eligibility checks only a self-signature, **any actor can file a `supersede` of any
other actor's WarrantID** and thereby evict it from the effective set — removing it
from a jurisdiction's index, its `select()` candidacy, and cardinality counts. That
is a griefing / eviction attack, not lifecycle. WRT-001 §6 therefore forbids the
naïve derivation and keeps **R0** ranking over **raw** eligibility (never
subtracting supersedes) — correct, but it means R0 cannot reflect *legitimate*
supersession at all. R0 is a raw query, not an effective view.

### 1b. A stored citation over live-head cannot converge

A settlement-active reason that ranks over the **current** effective set is **live**:
any later record that joins the set changes the ranking, so a filed precedent goes
`stale`, and `stale → unverified → ERR` then poisons every prior citation in an
append-only store. WRT-001 §6 makes R0 an **ephemeral, non-filing** query for this
reason. A **stored, replayable** citation needs a **committed, growth-immune**
effective set fixed at a point in time — a **checkpoint** — and that checkpoint must
itself be **authorized** (not self-filed), or the censorship/forgery problem simply
moves up one level.

**These are one problem.** The effective set is defined *by* key state (who was
authorized to act, and to supersede, as of a point in history); the checkpoint
commits *that* set. So key-state (§2), authorized supersession (§3), and the R1
checkpoint (§4) are specified together.

## 2. Key-state (the authority clock)

**Definition.** The **key-state at a history position `p`** is the map
`actor → { authorized public keys }` that a settlement verifier honours for
signatures evaluated as of `p`. It is derived from the settlement lineage — genesis
/ trust-config seed bindings, plus each authorized rotation — and is **monotone in
the committed history**, never in wall-clock.

**Requirements the design pins (mechanics grounded in §0):**

- **Seed.** The trust config / pinned `genesis.json` establishes the initial
  `actor → keys` bindings and the genesis roots that anchor each jurisdiction.
- **Rotation.** An actor rotates a key only via a record **authorized by the actor's
  current key-state** (a new key is bound only if the rotation is signed by a key
  already authoritative for that actor). A rotation is a state transition, not a
  free assertion.
- **Conflict.** When the lineage admits two maximal, DAG-unordered authorized
  rotations for one actor (`conflict_actors`, warrant.py:945), that actor's key is
  **not** honoured — fail-closed, never pick-one-arbitrarily (SPEC.md:105).
- **Liveness + resolution (a dormant path WRT-002 must ACTIVATE).** SPEC.md:105
  already fixes the deadlock: a conflicted key must not count toward a quorum until a
  later warrant *authorized by the unconflicted remainder* resolves it, reducing the
  threshold to exclude the conflicted actor strictly for that resolution (this is
  what stops a compromised key from vetoing its own resolution forever —
  GOV-001:195-205's "perpetual-veto self-destruct"). But today that path is
  **present-but-unwired**: the reduction helper `_threshold_satisfied(..., conflicted=)`
  (warrant.py:711) is never called with a non-empty `conflicted` set, so
  `conflict_actors` is report-only (§0). Because R1 makes the effective set and the
  checkpoint *depend* on key-state, WRT-002 requires the resolution to be wired into
  the derivation fixpoint — otherwise a conflict deadlocks the very key-state a
  checkpoint must commit. The stale-rotation-replay non-conflict (an ancestor replay
  is DAG-ordered → harmless, tests/settlement.py:302-330) is preserved.
- **As-of-checkpoint, not live-head.** For R1, the authoritative key-state is the one
  **committed by the checkpoint** (§4), so a key rotated *after* the checkpoint does
  not retroactively change what the checkpoint authorized.

## 3. Authorized effective-lifecycle

**The authorization rule (closes 1a).** A `supersede` of target `X` is **EFFECTIVE**
only if its filer is **authorized to supersede `X`** — i.e., the superseder's
signature is honoured by the key-state (§2) **and** the superseder satisfies the same
governing authority that admitted `X`:

- **self-authorized** — the supersede is signed by a currently-authorized key of the
  **same actor** named in `X`'s body (`X.actor.id`): an actor may retract or replace
  its own record; **or**
- **policy-authorized** — the supersede meets the **jurisdiction's threshold policy
  that governs `X`** (`X.under` / the root policy): the same authority that could have
  admitted `X` may retire it.

A `supersede` that is merely *eligible* (self-signed by a foreign actor, or by a key
not authoritative for its claimed actor, or failing the governing threshold) is
**not effective**: it stays in the store as a record but **does not evict its
target**. This is exactly what defeats the censorship primitive.

**Effective set.** `authorized_effective_active_for(J, checkpoint)` =
the records active for jurisdiction `J` as of `checkpoint`, **minus** every target of
an **authorized** supersede (per the rule above), evaluated under the key-state the
checkpoint commits. This — not raw eligibility, and not raw-minus-targets — is what a
checkpoint commits and a stored citation ranks over.

**Supersede-of-supersede (the fold).** Supersession is resolved as a fold over the
**authorized-supersede relation**, not a one-pass subtraction:

- if an authorized supersede `S₁` targets `X`, `X` is not effective;
- if `S₁` is itself targeted by an authorized supersede `S₂`, then `S₁` is not
  effective, so its eviction of `X` **no longer stands** — `X` reverts to effective
  **unless** another authorized supersede still targets it;
- the fold is computed to a fixed point over the committed lineage and MUST be
  deterministic and order-independent (a set relation, not a sequence).

**Competing authorized supersedes** of the same target do not "double-evict"; the
target is simply not effective. Competing supersedes that would *reinstate*
different states surface as a **settlement conflict** (like a Book III ConflictSet),
never a silent arithmetic merge.

## 4. The R1 authorized historical checkpoint

**Object.** An R1 checkpoint is a **settlement record** (candidate tag
`checkpoint@v1`) that commits, for a jurisdiction `J` at an epoch:

- `jurisdiction` (a genesis root WID);
- `epoch`;
- `effective_set_root` — a canonical set-commitment (a hash over the sorted effective
  WarrantIDs) of `authorized_effective_active_for(J, self)` — the output of §3's
  **authorized** derivation, not raw eligibility. (This is a Warrant-level primitive;
  the ADR-008 profile's `assertion_set_root` is one *consumer* of such a root, not a
  dependency of it — WRT-002 sits **below** ADR-008.)
- a **key-state pin** — the committed key-state (or its root) the derivation was
  authorized under (§2 "as-of-checkpoint");
- the **governing policy** reference that authorizes the checkpoint itself.

**Authorization (non-forgeable).** A checkpoint is valid **only if it is
threshold-authorized by `J`'s governing policy** — signed to the jurisdiction's
threshold, **not self-filed**. A self-signed "checkpoint" is rejected, so an attacker
cannot mint a checkpoint that commits a censorship-derived or fabricated set.

**Growth-immunity + replayability.** Because the checkpoint commits a **root** of the
effective set at an epoch under a **pinned** key-state, later store growth cannot
change the committed root. A verifier **replays** the checkpoint: it recomputes
`authorized_effective_active_for(J, checkpoint)` from the committed inputs and
**requires it to equal `effective_set_root`**; a mismatch is `unverified`. A stored
citation that binds a valid checkpoint is therefore replayable and immune to store
growth — the property R0 live-head cannot have.

**Binding from WRT-001.** WRT-001 §6 already requires that a **stored** (settlement-
active) `wave@v1` reason **explicitly carry the authorized checkpoint WarrantID**, and
that a verifier **reject a settlement-active wave reason that names no checkpoint**.
WRT-002 supplies what that WID must resolve to and how it is checked: resolve the
checkpoint, verify it is threshold-authorized and valid (§4), replay its
`effective_set_root`, and rank the citation over the checkpoint's authorized
effective set (minus the bound citation's own WID) — never over live-head. This is
what makes a stored precedent both censorship-resistant and convergent.

## 5. Countervectors (before adoption)

Every one must be a permanent differential vector (Python ↔ Go), fail-closed, and
bounded. Effective-lifecycle / key-state (extends WRT-001 item 1's list):

- **foreign supersede** — a supersede of `X` self-signed by an actor other than
  `X.actor.id` and failing `X`'s threshold → **not effective**, `X` stays in the set;
- **unbound-key supersede** — signed by a key not authoritative for its claimed actor
  under the key-state → not effective;
- **wrong-policy supersede** — meets *a* threshold but not the one governing `X` →
  not effective;
- **authorized self supersede** — signed by `X`'s own authorized key → `X` evicted;
- **authorized policy supersede** — meets `X`'s governing threshold → `X` evicted;
- **chained** `S₂`-supersedes-`S₁`-supersedes-`X` → `X` reinstated (fold fixed point);
- **competing** authorized supersedes → conflict surfaced, not silent merge;
- **unrelated** supersede (target not in `J`'s set) → no effect on the set;
- **rotation-then-supersede** — a key rotated after the checkpoint does not change
  the checkpoint's authorized set (as-of-checkpoint key-state).

Checkpoint (§4):

- **forged checkpoint** — self-filed, below threshold → rejected;
- **censorship-derived checkpoint** — commits a raw-minus-targets set (not the
  authorized derivation) → replay mismatch → `unverified`;
- **stale-under-growth** — new records join after the checkpoint; the committed root
  is unchanged and the bound citation still replays;
- **key-state-pin tamper** — a checkpoint whose committed key-state does not match its
  replayed derivation → `unverified`;
- **checkpoint-less stored citation** — a settlement-active wave reason naming no
  checkpoint → rejected (WRT-001 §6).

## 6. Non-goals, ordering, and the gate

- **Design only.** No signatures, no adoption, no registration of any runtime; no
  cross-impl port. The reference-prototype path in `sigma-glyph` continues to label
  its stored-reason demonstration as *anticipating* R1, not a permitted R0.
- **Ordering.** Items 1–2 are inseparable and precede the WRT-001 §8 budget **freeze**
  (the exact re-execution cost trace is frozen only once the effective-set scan is
  fixed here). §7 (novelty fingerprint / tunnel closure) and the governed profile
  anchor remain deferred; R1 does not depend on them.
- **Gate.** Adoption requires: ≥3 independent-family review with every P0/P1 closed;
  a reference-implementation gate with all §5 vectors ALL PASS **and** Python↔Go
  differential parity; a settlement/liveness re-check of the rotation + checkpoint
  transitions (the conflict-resolution / perpetual-veto self-destruct class,
  SPEC.md:105 + GOV-001:195-205); and a 2-of-3 governance threshold warrant. Until all of that lands, `wave@v1` stays structurally open for
  stored precedent, and only the ephemeral R0 query is available.
