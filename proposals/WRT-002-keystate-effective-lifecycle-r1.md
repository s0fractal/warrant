# WRT-002: Key-state, authorized effective-lifecycle, and the R1 checkpoint

**Status:** DRAFT **rev 2** (2026-07-27) — design only. **No production signatures,
no adoption, no code, no runtime registration, and no frozen wire bytes.** This
document specifies the settlement substrate WRT-001's stored (R1) wave citation
depends on — its Deferred items **1 (authorized effective-lifecycle)** and **2
(key-state → R1 checkpoint)**, declared inseparable and ordered before the §8 budget
freeze. Adoption requires the Decision Process (≥3 independent-family review, all
P0/P1 closed; a reference-implementation gate with Python↔Go parity; a 2-of-3
governance threshold warrant) — none performed here.

**rev 2** answers the Codex design gate (`reviews/2026-07-codex-wrt-002-design-gate.md`),
which correctly found rev 1 was not a closed replay machine: it committed an output
root but no immutable input cut, ignored that envelope signatures are outside the
WarrantID (so growth immunity was false), left "the policy that admitted X"
undefined, and gave no total causal transition algorithm. rev 2 fixes these in the
order the gate prescribed and **explicitly defers the wire-byte freeze** to a later
revision, after this model is itself attacked.

**Why Warrant-level, not wave-level.** Key-state, authorized supersession, an
immutable historical cut, and a checkpoint are **general settlement primitives** —
they govern *any* stored settlement citation. WRT-001 and ADR-008 consume them;
WRT-002 sits **below** both.

---

## 0. What this builds on in current Warrant (grounding)

Anchored to shipped semantics (`impl/warrant.py`, `impl-go/main.go`, `SPEC.md`):

- **Supersede today is a bare marker: no authorization, no eviction.** SPEC §7
  (SPEC.md:125) requires only `subject.hash == superseded WarrantID`; the impl checks
  only subject presence (warrant.py:1136 / main.go:2235) plus a valid self-signature.
  `active_records` (warrant.py:915-919) **never subtracts supersede targets** — a
  superseded record stays eligible. Today **eligibility == effective**; R1 introduces
  the distinction *and* the authorization gate.
- **Key-state is implemented.** `keys_before(wid)` (warrant.py:867-876): genesis-pinned
  `actor→keys`, walk ancestors in DAG order, each *authorized* rotation **replaces**
  that actor's key set (latest-authorized-wins). `threshold_keys = keys_before`;
  a signature counts only if valid AND by a key bound at that DAG position
  (SPEC.md:113).
- **Rotation** (SPEC.md:103; `rotation_authorized`, warrant.py:885-909): an `accept`
  whose subject is a key blob `{actor,key}`, requiring incoming proof-of-possession
  **plus** either the governing threshold satisfied against `keys_before`, **or**
  (no explicit policy) a valid signature by a key already bound to the actor.
  Threshold-authorized **emergency replacement without the outgoing key** is
  deliberately allowed (incoming PoP + governing quorum) — WRT-002 preserves this.
- **Conflict is detected; its RESOLUTION is dormant.** `conflict_actors`
  (warrant.py:945-953) flags an actor with >1 maximal DAG-unordered authorized
  rotation. SPEC.md:105 says a conflicted key must not count until a later warrant
  *authorized by the unconflicted remainder* resolves it (threshold reduced if
  needed). The reduction helper `_threshold_satisfied(..., conflicted=)`
  (warrant.py:711) exists but is **never called with a non-empty `conflicted`**;
  `conflict_actors` is report-only, computed live/global *after* the active-set
  fixpoint — it does **not** provide as-of-cut semantics. (No `resolved_key_state`
  identifier exists in-tree; the liveness fix is the DAG-descendant non-conflict rule,
  pinned by tests/settlement.py:302-330, rationale in GOV-001:195-205.)
- **Everything is live-head; no checkpoint, no effective set.** `_settlement_context`
  reasons over one immutable observation of `all_records()` (warrant.py:786-792) — but
  that observation is the *current* head, recomputed each verify. No
  `authorized_effective_active_for`, no committed cut anywhere.
- **Trust config / genesis seed authority, fail-closed** (warrant.py:592-647).
  The **actor→key seeds come from the validated trust config's `actors` map**; the
  **pinned `genesis.json` establishes ROOTS only** (advisory, used only if its hash
  matches `genesis_json_sha256`; else `WARN: genesis.json unverified`, SPEC.md:182).
- **The key map is NOT monotone.** History grows monotonically, but a rotation
  *replaces* an actor's key set, so the derived key-state changes; only a fixed cut
  yields a fixed state.

The load-bearing fact: **Warrant authenticates only a self-signature for supersede,
does not evict on it, and its WarrantID excludes the envelope signatures that carry
authorization.** WRT-002 closes exactly that.

## 1. The problem (one coupled problem)

**1a. Naïve effective-lifecycle is a CENSORSHIP PRIMITIVE.** Defining the effective set
as `active_records` minus every supersede target lets any actor evict any WarrantID
on a bare self-signature (§0). WRT-001 §6 forbids it and keeps R0 over *raw*
eligibility — correct, but R0 then cannot reflect *legitimate* supersession at all.

**1b. A stored citation over live-head cannot converge.** A settlement-active reason
ranked over the current effective set is *live*: store growth restages it, so a
filed precedent goes `stale → unverified → ERR` and poisons prior citations
(WRT-001:133-141). A stored citation needs a **committed, growth-immune** effective
set — a **checkpoint** — that is itself **authorized** and **replayable from
committed inputs**, not from the current store.

These are one problem: the effective set is defined *by* key-state over a *fixed
historical cut*; the checkpoint commits that cut, that state, and the *evidence* that
authorized it. rev 2 specifies the five pieces the Codex gate ordered:

1. an **immutable input cut** (§2),
2. committed **authorization witnesses** (§3),
3. a **causal, stratified transition algorithm** (§4),
4. **lifecycle-policy resolution** (§5),
5. the **R1 checkpoint object** — vehicle chosen, **bytes deferred** (§6).

## 2. The immutable input cut (Codex step 1)

**Frontier.** A checkpoint commits a **frontier `F`**: a JCS-canonical **sorted set of
WarrantIDs**. The **cut** is the strict prior-closure of the frontier:

```
cut(F) = ⋃_{w ∈ F} priorClosure(w)      # priorClosure(w) = w and all records reachable via prior edges
```

`cut(F)` is downward-closed by construction (every record's priors are in it) and is
a pure function of the frontier plus content-addressed record bodies — no store head,
no `ts`, no global epoch (Warrant has none; SPEC.md:105). Post-frontier growth is
**invisible** to `cut(F)`: this is where growth-immunity comes from.

**Self-exclusion by construction.** The checkpoint record is filed *after* `F` (it
cites `F`), so it is not in any `priorClosure(w ∈ F)` and is **never a member of its
own cut**. The rev-1 identity cycle (a root committed inside the body that includes
the committing WID) cannot arise: the effective set is derived over `cut(F)`, which
excludes the checkpoint.

**No filer omission of a rival inside the cut.** The effective set is *derived* over
`cut(F)` (§4/§5), never filer-listed — so a rival that is in `cut(F)` cannot be
dropped; it is included or superseded by the deterministic derivation. A rival that
is **concurrent and outside** `cut(F)` is a genuinely different history line that this
checkpoint does not attest to; merging it is a *later* checkpoint over a larger
frontier. To stop frontier-gerrymandering, **`F` must be an antichain of `cut(F)`**
(no member of `F` is a prior of another) and the checkpoint's completeness is an
**authorized** claim (§6): only `J`'s threshold may assert "`F` is the frontier",
so a single filer cannot unilaterally choose a cut that omits a rival.

**Vectors:** omitted-already-present rival (in `cut(F)` → still derived); post-cut
growth (invisible → replay unchanged); untrusted `ts`/epoch backfill (ignored — cut
is causal, not temporal); checkpoint self-inclusion (impossible by construction).

## 3. Committed authorization witnesses (Codex step 2)

**The seam.** A WarrantID hashes only the **body**; SPEC §5 permits appending
envelope co-signatures without changing any WID. Threshold satisfaction (adoption,
rotation, supersede authorization) is evaluated from those *mutable* signatures. So a
checkpoint that commits only WIDs/roots is not growth-immune: appending a co-signature
to a supersede `S` after the checkpoint can make `S` authorized and evict a target —
with no WID, policy, or committed-root change (Codex countervector).

**Fix — the checkpoint commits the evidence, and replay uses only it.** For every
**authorized state transition** in `cut(F)` that the derivation relies on — each
root-adoption, rotation, and *effective* supersede — the checkpoint commits a
**witness manifest**: a JCS-canonical, sorted list of

```
{ warrant_id, sig_witnesses: [ {actor, key, sig}, … ] }
```

where `sig_witnesses` is the **exact multiset of signatures the derivation counted**
for that transition. The checkpoint commits a **`witness_root`** (a set-commitment
over the manifest). **Replay authorizes each transition using ONLY the committed
witnesses**, never the live envelope — a signature appended after the checkpoint is
not in the manifest, so it cannot change the replay. Conversely, a witness in the
manifest that no longer verifies (key/body mismatch) fails the checkpoint
(`unverified`). This freezes rotation authorization (hence the key-state pin) and
supersede authorization against ordinary later growth.

(Equivalent alternative, noted not chosen: represent every authorization as its own
content-addressed record so nothing lives in a mutable envelope. That is a larger
Warrant change; the witness manifest is the minimal fix and is what rev 2 specs.)

**Vectors:** exact-before (one sig, `S` unauthorized, `X` kept) and exact-after (a
co-signature appended — replay unchanged because the manifest is authoritative);
witness that stops verifying → `unverified`.

## 4. Causal, stratified transition algorithm (Codex step 3)

The dependency graph has **negative edges** (a rotation enables a key; a key-signed
supersede can revoke that rotation), so a "current-state, re-evaluate-after-effects"
fixpoint is non-monotone and can oscillate (rev-1's flaw). rev 2 uses a **causal,
DAG-positioned** derivation with an **immutable pre-state rule**.

**Authority-state as a function of the causal past.** For each record `w ∈ cut(F)`
define `AS(w)` = the authority state (key-state + conflict markers + effective
markers) obtained by folding the transitions along `priorClosure(w)`, where **each
transition is authorized against its own strict-causal pre-state**
`preAS(w) = merge(AS(p) for p in w.prior)` (the empty merge = the genesis seed). `AS`
is well-founded on the acyclic causal order and is a **pure function of `cut(F)` +
the committed witnesses** — deterministic and order-independent (a linear extension is
used only for iteration; a record never reads a concurrent branch's effect, only a
`merge` at its own `prior` join).

**Monotone authorization (breaks the cycle).** A transition `w` is authorized iff its
committed witnesses satisfy the rule against `preAS(w)`. **Once authorized, that
authorization is never retroactively withdrawn.** For `R: K0→K1` then a same-actor
supersede `S` of `R` signed by `K1`: `K1 ∈ preAS(S)` because `R` is in `S`'s causal
past and was authorized in an earlier stratum, so **`S` is authorized**; `S`'s
revocation of `R` applies only in states that have `S` in *their* past — it does not
un-authorize `S` itself. No oscillation; a single deterministic outcome.

**Conflict state (carried, not post-hoc).** `AS(w)` carries a per-actor conflict
marker: an actor is conflicted at `w` iff two authorized rotations for it are maximal
and DAG-unordered within `priorClosure(w)`. A conflicted actor's key **does not count**
toward any quorum evaluated at or after `w` (fail-closed). **Resolution** is an
authorized record `Q` that (a) **descends from every maximal conflicting rotation**
(so it is causally after the whole conflict), and (b) is authorized against `preAS(Q)`
by the **unconflicted remainder** of the governing quorum, with the threshold reduced
to exclude the conflicted actor strictly for `Q` (SPEC.md:105). If no unconflicted
remainder can satisfy even the reduced threshold, the actor **stays conflicted
(terminal, fail-closed)** — the jurisdiction cannot use that actor until a wider
quorum acts; the derivation never guesses.

**Supersede-of-supersede (formal recurrence, acyclic by causality).** A supersede `S`
of `X` requires `X ∈ priorClosure(S) \ {S}` (§5 causal rule), so supersede chains
strictly increase in causal depth and are acyclic. Over `cut(F)`:

```
effective(X) ⇔ active_cut(X)  ∧  ¬∃ S : authorizedSupersede(S, X) ∧ effective(S)
```

where `active_cut(X)` is root-reachability + well-signedness + valid-policy computed
over `cut(F)` (the existing `active_records` predicate, but scoped to the cut, not
live-head), and `authorizedSupersede(S,X)` is §5. The recurrence terminates
(well-founded on causal depth) and is deterministic. Competing authorized supersedes
of one `X` do not double-evict — `X` is simply not effective; competing transitions
that would reinstate *different* states surface as a settlement **conflict**, never a
silent merge.

**Vectors:** rotation-enables-its-own-revocation (no oscillation, `S` authorized,
`R` revoked forward); resolver descends only one of two maxima → not a valid resolver;
two policy actors simultaneously conflicted → threshold reduced deterministically or
terminal-conflict; chained `S₂`-supersedes-`S₁`-supersedes-`X` → `X` reinstated.

## 5. Lifecycle-policy resolution (Codex step 4)

Ordinary records are **not threshold-admitted** (only root-adoption and rotations are),
so "the policy that admitted `X`" does not exist. rev 2 defines the lifecycle authority
explicitly. A supersede `S` of `X` is **authorizedSupersede(S, X)** for jurisdiction
`J`, evaluated against `preAS(S)` with the committed witnesses (§3), iff **both** the
causal rule and one authorization path hold:

- **Causal position (required).** `X ∈ priorClosure(S) \ {S}`. A supersede must
  causally descend its target; an old-branch or concurrent `S` is **ineffective**
  (defeats "stale key on a fork revokes a later record").
- **Authorization path (one of):**
  - **SELF** — `S` carries a signature by a key authoritative for `X.actor.id` in
    `preAS(S)`. An actor may retire its own record; **self-authorization is
    sufficient alone** and does not additionally require lifecycle policy.
  - **JURISDICTION POLICY** — for a non-self supersede, `S`'s committed witnesses
    satisfy **`J`'s governing settlement policy** (the same threshold that governs
    root-adoption / makes `J` settlement-active), evaluated at `preAS(S)`. This is
    **not** `X.under`: `X.under` is a check/evidence policy, may be zero/one/several,
    and is not a lifecycle authority — rev 2 explicitly forbids using it to authorize
    supersession.

**Jurisdiction-relativity.** A record reachable from two adopted roots may be effective
in `J₁` and superseded in `J₂` independently; a checkpoint is for **one `J`**, and all
of §4/§5 is evaluated within that `J`. `J`'s governing settlement policy is the policy
under which `J`'s genesis/adopted root is settlement-active (SPEC.md:178), resolved to
a single policy per jurisdiction; if a jurisdiction's root admits no single governing
threshold policy, only SELF supersession is available there (fail-closed, never a
guess among candidates).

**Vectors:** foreign non-self supersede below `J`'s quorum → ineffective; the same
meeting `J`'s quorum → effective; self-supersede by the actor's authorized key →
effective; target with zero/multiple `X.under` policies → `X.under` never authorizes;
target shared by two jurisdictions → per-`J` outcome; unordered/stale-key supersede →
ineffective (causal rule).

## 6. The R1 checkpoint object — vehicle chosen, bytes DEFERRED (Codex step 5)

**Versioning vehicle (chosen).** A checkpoint is **an `accept` Warrant whose subject
is a canonical `checkpoint@v1` blob** — the same shape as a rotation (an `accept`
whose subject is a key blob), so **no new body version is required** and the existing
closed 0.1/0.2 body schema is unchanged (SPEC v0.3 adds no body schema). The
checkpoint's **threshold authorization is the `accept`'s own signatures satisfying
`J`'s governing settlement policy** — a checkpoint is valid only if threshold-signed
by `J`, never self-filed. The `checkpoint@v1` subject blob commits, for `(J, sequence)`:

- `jurisdiction` (a genesis/adopted root WID for `J`);
- `sequence` (a per-`J` monotone counter; **not** a wall-clock epoch — Warrant has no
  global time);
- `frontier` (§2, the sorted WID set whose strict prior-closure is the cut);
- `effective_set_root` (§4/§5 output over the cut, self-excluded);
- `key_state_root` (the canonical committed key-state **including conflict markers**);
- `witness_root` (§3);
- `governing_policy` (the resolved single lifecycle/adoption policy for `J`).

**Replay contract.** A verifier resolves the checkpoint `accept`, checks its
signatures satisfy `J`'s governing policy, rebuilds `cut(frontier)` from
content-addressed bodies, re-runs §4/§5 **using only the committed witnesses**, and
requires the recomputed `effective_set_root` / `key_state_root` to **equal** the
committed values; any mismatch, any unverifiable witness, or a non-antichain frontier
is `unverified` (ERR for a settlement-active citation, per WRT-001 §5). Competing
checkpoints at one `(J, sequence)` are a settlement **conflict** (like a Book III
ConflictSet), never a silent pick.

**Binding from WRT-001.** WRT-001 §6 already requires a stored `wave@v1` reason to
name an authorized checkpoint WID and rejects one that names none. WRT-002 supplies
what that WID resolves to (a threshold-authorized `checkpoint@v1` accept) and how it
is replayed; the citation then ranks over the checkpoint's authorized effective set
(minus the citation's own WID), never over live-head.

**BYTES DEFERRED (explicit).** rev 2 does **not** freeze: the closed `checkpoint@v1`
blob schema and canonical byte layout; the **domain-separated** hashing inputs for
`effective_set_root` / `key_state_root` / `witness_root`; the canonical encoding of
key-state-with-conflicts; the `governing_policy` resolution bytes; or the exact
validation severities. Per the gate, these are frozen **only after** §§2–5 are
themselves attacked in review, so Python and Go can then be built to one contract.
Until then no implementation should start.

## 7. Countervectors before the next design gate

All must become permanent Python↔Go differential vectors, fail-closed and bounded.
The Codex gate's ten, plus §§2–5:

1. checkpoint omits a rival already inside `cut(F)` → still derived (not omittable);
2. record with old `ts` appended after the checkpoint → invisible (causal cut);
3. checkpoint self-inclusion → impossible by construction;
4. threshold co-signature appended after the checkpoint → replay unchanged (witness
   manifest authoritative);
5. unordered / stale-key supersede of a later or concurrent target → ineffective;
6. target with zero/multiple `X.under` policies; target shared by two jurisdictions;
7. rotation enables its own revocation → deterministic, no oscillation;
8. resolver descends from only one of two conflicting maxima → not a valid resolver;
9. two policy actors simultaneously conflicted → deterministic reduction or terminal;
10. competing checkpoints at one `(J, sequence)` → conflict, not silent pick;
plus: foreign vs jurisdiction-quorum supersede; self-supersede; chained
supersede-of-supersede reinstatement; a witness that stops verifying.

## 8. Non-goals, ordering, and the gate

- **Design only.** No signatures, adoption, runtime registration, code, or frozen
  bytes. The sigma reference path keeps labelling its stored-reason demo as
  *anticipating* R1, not a permitted R0.
- **Ordering.** §§2–5 are the substrate; the §6 byte freeze is next (rev 3), then
  implementation. Items 1–2 precede the WRT-001 §8 budget **freeze** (the exact
  re-execution scan set is fixed only once §4/§5 are). §7 novelty/tunnel and the
  governed profile anchor remain independently deferred.
- **Gate.** Adoption requires ≥3 independent-family review with every P0/P1 closed; a
  reference-implementation gate with all §7 vectors ALL PASS **and** Python↔Go
  differential parity over the frozen `checkpoint@v1` bytes; a settlement/liveness
  re-check of the rotation + resolution + checkpoint transitions (the conflict-
  resolution / perpetual-veto self-destruct class, SPEC.md:105 + GOV-001:195-205);
  and a 2-of-3 governance threshold warrant. Until all of that lands, `wave@v1` stays
  structurally open for stored precedent; only the ephemeral R0 query is available.
