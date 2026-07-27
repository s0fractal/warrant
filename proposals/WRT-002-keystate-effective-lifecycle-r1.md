# WRT-002: Key-state, authorized effective-lifecycle, and the R1 checkpoint

**Status:** DRAFT **rev 3** (2026-07-27) — model design only. **No production
signatures, no adoption, no code, no runtime registration, and NO frozen wire
bytes.** Specifies the settlement substrate WRT-001's stored (R1) wave citation
depends on — Deferred items **1 (authorized effective-lifecycle)** and **2 (key-state
→ R1 checkpoint)**, inseparable and ordered before the §8 budget freeze. Adoption
requires the full Decision Process; none is performed here.

**rev history.** rev 1 → AMEND (no immutable cut; envelope signatures outside the
WarrantID break growth-immunity). rev 2 closed the cut, self-exclusion, causal
supersede, immutable-pre-state authorization, emergency rotation, and the `X.under`
rejection, but the re-gate (`reviews/2026-07-codex-wrt-002-rev2-design-regate.md`)
found four more model seams. **rev 3 answers them and still does not freeze bytes**:
the model is frozen first, re-gated, and only then are `checkpoint@v1` bytes chosen.

**Warrant-level, not wave-level.** Key-state, authorized supersession, an immutable
historical cut, a jurisdiction policy-state, and a checkpoint are **general settlement
primitives**. WRT-001 and ADR-008 consume them; WRT-002 sits **below** both.

---

## 0. What this builds on in current Warrant (grounding)

Anchored to shipped semantics (`impl/warrant.py`, `impl-go/main.go`, `SPEC.md`):

- **Supersede today is a bare marker: no authorization, no eviction** (SPEC.md:125;
  warrant.py:1136 / main.go:2235). `active_records` (warrant.py:915-919) never
  subtracts supersede targets — today eligibility == effective. R1 introduces both
  the distinction and the authorization gate.
- **Key-state is implemented.** `keys_before(wid)` (warrant.py:867-876): genesis-pinned
  `actor→keys` from the trust config's `actors` map, walk ancestors in DAG order, each
  *authorized* rotation **replaces** that actor's key set (latest-authorized-wins).
  The map is **not monotone** (rotation replaces); only a fixed cut yields a fixed
  state. Threshold counts a signature only if valid AND by a key bound at that DAG
  position (SPEC.md:113).
- **Rotation** (SPEC.md:103; `rotation_authorized`, warrant.py:885-909): an `accept`
  whose subject is a key blob, requiring incoming proof-of-possession **plus** either
  the governing threshold against `keys_before`, **or** a valid signature by a key
  already bound. Threshold-authorized **emergency replacement without the outgoing
  key** is deliberately allowed.
- **Conflict is detected; RESOLUTION is dormant.** `conflict_actors` (warrant.py:945)
  flags an actor with >1 maximal DAG-unordered authorized rotation; it is **live/global
  after the active-set fixpoint — not an as-of-cut function**. The threshold-reduction
  helper `_threshold_satisfied(..., conflicted=)` (warrant.py:711) is never called with
  a non-empty set (SPEC.md:105 rule is unwired). No `resolved_key_state` exists in-tree.
- **Everything is live-head; no checkpoint, no effective set** anywhere.
- **Trust config / genesis, fail-closed** (warrant.py:592-647): `actors` → key seeds;
  **`genesis.json` establishes ROOTS only** (advisory, hash-pinned; SPEC.md:182).
- **A WarrantID hashes only the body.** SPEC §5 permits appending envelope signatures
  (filing and co-signatures) **without changing any WarrantID** — the seam every
  signature-dependent predicate must be frozen against (§3).
- **Ordinary records are NOT threshold-admitted** — `active_records` needs only
  root-reachability, well-signedness, and a valid policy shape; `_policies_satisfied`
  gates root-adoption and rotations, not every `X`. So there is no shipped "policy that
  admitted `X`", and a **genesis-pinned root has no governing threshold policy at
  all** (§5.5).

## 1. The problem (one coupled problem)

**1a.** Naïve `active − supersede-targets` is a **censorship primitive** (any
self-signature evicts any WID). **1b.** A live-head stored citation cannot converge in
an append-only store (`stale → unverified → ERR` poisons prior citations,
WRT-001:133-141). The effective set is defined *by* key-state over a *fixed historical
cut*, authorized by *frozen evidence*, under a jurisdiction *policy-state*, committed
by a *causally-anchored* checkpoint. rev 3 specifies, in the re-gate's order:

1. an **immutable input cut** (§2);
2. a **complete, resolvable, frozen witness manifest** over **every** signature-
   dependent replay input (§3);
3. a **total ACI-provenance transition algorithm** with a concrete resolver (§4);
4. **lifecycle-policy** + a **jurisdiction policy-state** primitive (§5, §5.5);
5. the **R1 checkpoint** causally bound to its frontier, with a succession chain —
   **bytes still deferred** (§6).

## 2. The immutable input cut

A checkpoint commits a **frontier `F`**: a JCS-canonical sorted, deduplicated set of
WarrantIDs. The **cut is the inclusive causal closure of the frontier**:

```
cut(F) = ⋃_{w ∈ F} closure(w)      # closure(w) = w together with all records reachable via prior edges
```

`cut(F)` is downward-closed and is a pure function of `F` + content-addressed bodies —
no store head, no `ts`, no global epoch (Warrant has none). It is "strict" only
relative to the *later* checkpoint record, which is filed after `F` and is therefore
**never in its own cut** (kills the rev-1 identity cycle). Post-cut growth is invisible
→ growth-immunity.

**Completeness is a quorum-authorized claim, not a mechanical proof.** `F` must be an
**antichain** of `cut(F)` (no member is a prior of another); this plus the effective
set being *derived* over `cut(F)` (§4) stops a rival **inside** `cut(F)` from being
dropped. It does **not** by itself prove global completeness: a rival that is
concurrent and **outside** `cut(F)` is a different history line. Requiring the
checkpoint to be **threshold-authorized by `J`'s governing policy** (§5.5/§6) makes "F
is the frontier" a **quorum-authorized claim** — it prevents unilateral *filer*
omission, not omission by the governing quorum (which is accountable and visible).

## 3. Complete, resolvable, frozen witness manifest

**The seam (broadened).** A WarrantID hashes only the body; SPEC §5 lets any
signature — a **filing** actor signature *or* a threshold co-signature — be appended
later without changing a WID. **Every** signature-dependent replay predicate is
therefore mutable under ordinary growth: not only transition thresholds (adoption,
rotation, supersede) but the **well-signedness of every ordinary record** that
`active_cut(X)` consults. Freezing only transitions (rev 2) left ordinary eligibility
mutable — appending a valid filing signature to a previously-unsigned `X` inside the
cut would change `effective_set_root` with no WID/frontier/root change.

**Fix — freeze every signature-dependent predicate, and replay never reads a live
envelope for a cut record.** The checkpoint commits a **witness manifest**: for each
record in `cut(F)` whose eligibility or authorization the derivation uses, one entry
with **typed witness roles**:

- `actor-filing` — the `body.actor.id` signature that makes an ordinary record (or a
  root) well-signed;
- `incoming-pop` — a rotation's incoming-key proof-of-possession;
- `threshold` — the exact multiset of signatures counted for a quorum (root-adoption,
  rotation, supersede, policy-succession, conflict-resolution).

Each entry is `{ warrant_id, role, witnesses: [ {actor, key, sig}, … ] }`, sorted
canonically. Replay authorizes and eligibility-checks **only** from the manifest; it
MUST NOT consult a record's live envelope for anything inside `cut(F)`. A witness that
no longer verifies (key/body mismatch) → `unverified`.

**Completeness is authorized.** An **omitted** already-valid filing witness would let a
checkpoint censor an eligible record. So the manifest MUST be complete for the cut —
every cut record whose eligibility the derivation reads has an `actor-filing` entry —
and **completeness is part of the quorum-authorized claim** (§2): the governing
threshold vouches that the manifest covers the cut. Replay treats a cut record with no
manifest witness as **not eligible**, and an over-broad manifest (a witness for a
record not in `cut(F)`) as `unverified`.

**Resolvable.** A bare `witness_root` has no preimage. The canonical manifest MUST be a
**content-addressed blob** referenced by the checkpoint (resolvable by replay); the
`witness_root` is its digest. (Byte layout deferred, §6.)

**Vectors:** ordinary / root filing signature appended after checkpoint → replay
unchanged; a previously-unsigned cut record admitted by a live signature → NOT admitted
(manifest authoritative); an omitted already-valid filing witness → that record is not
eligible **and** the omission is attributable to the authorizing quorum.

## 4. Total ACI-provenance transition algorithm

Authorization has **negative edges** (a rotation enables a key; a key-signed supersede
can revoke that rotation), so a collapsed-state fixpoint is non-monotone and can
oscillate, and an unspecified `merge` lets Python and Go diverge. rev 3 makes state
**provenance**, merge an **ACI union**, and derivation a **single specified function**.

**Authority state = a set of authorized events + their causal relation.** `Events` is
the set of already-authorized transition events (`rotation`, `revocation`,
`policy-succession`, `conflict-resolution`) drawn from `cut(F)`, each carrying its
record WID and DAG position. State is **never** a collapsed key-map; it is this event
set, from which every marker is *derived*.

**Merge is ACI union.** `preEvents(w) = ⋃_{p ∈ w.prior} Events(p)` (empty union = the
genesis seed). Set union is **associative, commutative, idempotent** → `preEvents(w)`
is a pure function of `w`'s causal past, independent of parent order, list order, or
iteration order. This is the load-bearing law rev 2 left unnamed.

**One derivation from an event set.** Given any event set `E`, a *single* function
derives:
- **maximal rotations** per actor = the causally-maximal authorized rotation(s) in `E`;
  if exactly one, it is the actor's key; if ≥2 maximal and DAG-unordered, the actor is
  **conflicted** (marker in the derived state, key unusable — fail-closed);
- **policy-state** per jurisdiction, by the same maximal-succession rule over
  `policy-succession` events (§5.5);
- **effective status** of records (§5's reverse pass).

**Two ordered passes (direction stated).** (a) **Forward authorization**, in causal
order: a transition `w` becomes an event of `Events(w)` iff its committed witnesses
(§3) satisfy its rule against the *derived state of* `preEvents(w)` — its immutable
pre-state — and, once authorized, it is never retroactively withdrawn (so `R:K0→K1`
then `K1`-signed `S` superseding `R` is authorized, because `K1 ∈ derived(preEvents(S))`;
`S` revokes `R` only forward). (b) **Reverse effectiveness**, from causally-later
superseders back toward targets: `effective(X) ⇔ active_cut(X) ∧ ¬∃ S :
authorizedSupersede(S,X) ∧ effective(S)` (§5), well-founded because supersedes
strictly increase causal depth.

**Conflict resolution is a concrete transition.** The resolver `Q` is a **rotation
`accept`** for the conflicted actor that: resolves it to one named incoming key
(carrying `incoming-pop`); **DAG-descends every maximal conflicting rotation** (so `Q`
is a strict causal successor of the whole conflict); and is `threshold`-authorized by
the **unconflicted remainder** of the governing quorum evaluated at `preEvents(Q)`, with
the threshold **reduced** to exclude the conflicted actor strictly for `Q`
(SPEC.md:105). Its state effect: `Q` is a new authorized rotation that dominates the
conflicting maxima, so the derived "maximal rotation" is again unique and the marker
clears. If no unconflicted remainder satisfies even the reduced threshold, the actor is
**terminally conflicted** (fail-closed; the derivation never guesses). Multiple
simultaneously-conflicted policy actors reduce independently and deterministically.

**Determinism gate.** For a fixed `cut(F)` + manifest, the derived state MUST be
**byte-identical under every parent/list/iteration permutation** — a required
differential vector, not merely equal error counts.

## 5. Lifecycle-policy resolution

A supersede `S` of `X` is **authorizedSupersede(S, X)** for jurisdiction `J`, evaluated
against `derived(preEvents(S))` with committed witnesses, iff **both**:

- **Causal position (required).** `X ∈ closure(S) \ {S}`. A supersede must causally
  descend its target; an old-branch or concurrent `S` is **ineffective**.
- **One authorization path:**
  - **SELF** — a signature by a key authoritative for `X.actor.id` at `preEvents(S)`.
    Sufficient alone; does not additionally require lifecycle policy.
  - **JURISDICTION POLICY** — the `threshold` witnesses satisfy **`J`'s governing
    policy-state** (§5.5) at `preEvents(S)`. **Never `X.under`** (a check/evidence
    policy, zero/one/many, not a lifecycle authority — explicitly forbidden).

Everything is **per-jurisdiction**: a record reachable from two adopted roots may be
effective in `J₁` and superseded in `J₂` independently; a checkpoint is for one `J`.

## 5.5. Jurisdiction policy-state (new primitive)

Shipped settlement has **no** persistent singular policy per jurisdiction, and a
**genesis-pinned root has no threshold policy at all** — so §5's "jurisdiction policy"
and §6's "threshold-authorized checkpoint" have nothing to resolve to. rev 3 introduces
a **jurisdiction policy-state**, tracked exactly like key-state (§4 provenance):

- **Anchor.** The trust config pins, per genesis root, a **governing policy** (a
  `min_sigs`/`actors` threshold blob), alongside the existing `actors`→keys pin. A
  genesis root with **no** pinned governing policy is **not checkpoint-capable**: only
  SELF supersession is available in it and **no R1 checkpoint can be authorized there**
  (fail-closed, stated plainly — this is a deliberate narrowing, not an oversight).
- **Succession.** The governing policy changes only via a **`policy-succession`
  event**: a threshold `accept` whose subject is a new governing-policy blob,
  authorized by the *current* governing policy at its pre-state — the exact analogue of
  key rotation, with the same maximal-succession + conflict rules (§4). Policy conflict
  (≥2 maximal unordered successions) is fail-closed and resolvable by the §4 resolver
  shape.
- **In the cut/witness model.** Policy-state is derived over `cut(F)` from
  `policy-succession` events and committed by the checkpoint as `policy_state_root`
  (§6); its authorizing signatures are `threshold` witnesses in the manifest. So the
  policy that authorizes a checkpoint is itself replayable and frozen — no live
  policy is consulted.
- **Multiply-adopted roots.** "The governing policy for `J`" is resolved **for the
  jurisdiction root the checkpoint names**, from that root's pinned anchor and its
  succession chain — not from arbitrary adoption `under` policies. A record reachable
  via two roots is evaluated under each named jurisdiction's own policy-state.

**Vectors:** pinned-genesis-without-policy → no checkpoint possible (fail-closed);
two adoption paths with different `under` policies → neither is the lifecycle authority;
policy succession authorized by the prior policy; policy fork → conflict + resolver.

## 6. The R1 checkpoint — causally bound, with succession; BYTES DEFERRED

**Vehicle.** A checkpoint is **an `accept` Warrant whose subject is a canonical
`checkpoint@v1` blob** (same shape as a rotation) — **no new body version**. Its
**threshold authorization is the enclosing `accept`'s signatures satisfying `J`'s
governing policy-state** (§5.5), never self-filed.

**Causal binding (closes the two-position seam).** The checkpoint `accept`'s
**`body.prior` MUST equal the committed `frontier`** (after the same canonical
sort/dedup). Then the checkpoint's own authorizing signatures — evaluated at
`keys_before/derived(preEvents(checkpoint))` — and the replayed cut are the **one and
the same** `cut(F)`. A checkpoint cannot advertise cut `F₁` while being authorized
against unrelated pre-state `F₂`.

**Committed (subject blob), for `(J, sequence)`:** `jurisdiction` (the root WID whose
pinned policy-state governs); `sequence` (per-`J` counter); `frontier` (= `body.prior`);
`effective_set_root`; `key_state_root`; `policy_state_root`; `witness_root` (resolvable
manifest, §3).

**Succession chain (closes rollback).** A checkpoint at `sequence n+1` MUST **causally
descend the previous accepted checkpoint** (that checkpoint ∈ `closure(frontier)`) and
its cut MUST **extend** the previous cut (`cut(Fₙ) ⊆ cut(Fₙ₊₁)`). Sequence starts at a
defined genesis value; a gap or a non-extending higher sequence is `unverified`;
competing accepted checkpoints at one `(J, sequence)` are a settlement **conflict**
(ConflictSet), never a silent pick.

**Replay contract.** Resolve the `accept`; check its signatures satisfy the derived
governing policy-state at the frontier; verify `body.prior == frontier` and the
succession chain; rebuild `cut(frontier)`; re-run §4/§5 using **only** the resolvable
manifest; require the recomputed `effective_set_root` / `key_state_root` /
`policy_state_root` to **equal** the committed values. Any mismatch, unverifiable or
missing/over-broad witness, non-antichain frontier, `prior≠frontier`, or broken
succession → `unverified` (ERR for a settlement-active citation, WRT-001 §5).

**Binding from WRT-001.** WRT-001 §6's stored `wave@v1` reason names an authorized
checkpoint WID; WRT-002 supplies what it resolves to and how it replays. The citation
then ranks over the checkpoint's authorized effective set (minus its own WID), never
live-head.

**BYTES DEFERRED (explicit).** rev 3 does **not** freeze the `checkpoint@v1` blob
schema / canonical layout; the **domain-separated** hashing inputs for
`effective_set_root` / `key_state_root` / `policy_state_root` / `witness_root`; the
canonical encoding of key-state and policy-state **including conflict markers**; the
manifest byte layout; `sequence` genesis/gap encoding; or exact validation severities.
Per the gate, bytes are frozen only **after** this model (§§2–5.5) survives another
design re-gate — then attacked independently before Python/Go work.

## 7. Countervectors before the next design gate

All become permanent Python↔Go differential vectors, fail-closed and bounded:

- **cut/growth:** omitted rival inside `cut(F)` → still derived; old-`ts` record
  appended after cut → invisible; checkpoint self-inclusion → impossible.
- **witnesses (§3):** ordinary / root `actor-filing` signature appended after
  checkpoint → replay unchanged; a previously-unsigned cut record → not admitted by a
  live signature; omitted already-valid filing witness → not eligible + attributable
  to the quorum; over-broad manifest → `unverified`; threshold co-signature appended
  → replay unchanged.
- **transitions (§4):** rotation-enables-its-own-revocation → deterministic, no
  oscillation; **merge-permutation → byte-identical state** (every parent/list/order);
  resolver descends only one of two maxima → invalid; two policy actors simultaneously
  conflicted → deterministic reduction or terminal; chained supersede-of-supersede →
  reinstatement.
- **lifecycle/policy (§5, §5.5):** foreign non-self supersede below `J`'s quorum →
  ineffective; same meeting the quorum → effective; self-supersede → effective;
  `X.under`-only → never authorizes; stale/unordered supersede → ineffective;
  pinned-genesis-without-policy → no checkpoint; two adoption policies → neither is
  authority; policy succession + policy fork.
- **checkpoint (§6):** `body.prior ≠ frontier` → `unverified`; higher-sequence
  rollback to a non-extending frontier → `unverified`; competing checkpoints at one
  `(J, sequence)` → conflict; sequence gap → `unverified`.

## 8. Non-goals, ordering, and the gate

- **Design only.** No signatures, adoption, registration, code, or frozen bytes. The
  sigma reference path keeps labelling its stored-reason demo as *anticipating* R1.
- **Ordering.** rev 3 is the model; a re-gate of §§2–5.5 precedes the rev-4 byte
  freeze, which precedes implementation. Items 1–2 precede the WRT-001 §8 budget
  freeze. §7-novelty/tunnel and the governed profile anchor remain independently
  deferred.
- **Gate.** Adoption requires ≥3 independent-family review with every P0/P1 closed; a
  reference-implementation gate with all §7 vectors ALL PASS **and** Python↔Go
  differential parity (incl. byte-identical merge-permutation state) over frozen
  `checkpoint@v1` bytes; a settlement/liveness re-check of rotation + policy-succession
  + conflict-resolution + checkpoint-succession transitions (the perpetual-veto
  self-destruct class, SPEC.md:105 + GOV-001:195-205); and a 2-of-3 governance
  threshold warrant. Until all of that lands, `wave@v1` stays structurally open for
  stored precedent; only the ephemeral R0 query is available.
