<!-- produced via tools/or_review.py | model: deepseek/deepseek-v4-pro | two-pass blind protocol | gates run by maintainer | pass-1 (blind) preserved at reviews/2026-07-deepseek-gov001-gate.md.pass1 -->

# Review: Gate Review 3 — GOV-001 rev 3 (candidate SPEC v0.3)

**Reviewer:** second pass (same adversarial model family)   
**Scope:** `proposals/GOV-001-settlement-at-scale.md` REV 3 (candidate SPEC v0.3 text)  
**Focus items:** assigned gate asks (1) conflicted-key exclusion, (2) `genesis.json` trust, (3) strawman re‑litigation flooding, (4) implementability audit of outcome fingerprints and compatibility rules.  
**Prior reviews considered:** Codex (gate 1), Gemini (gate 2), and maintainer responses.

## Verdict

**Provisional acceptance — one P1 mandated before adoption.**  
The core machinery (outcome fingerprints, threshold‑policy activation, conflicted‑key exclusion) is sound. Rev 3 survives the attack on stale‑rotation conflict (ask 1), and the format‑layer unboundedness for re‑litigation is an acceptable separation of concerns (ask 3). However, **the `genesis.json` trust rule (ask 2) is a P1 security hazard** because the spec currently commands verifiers to blindly trust a mutable file that lacks cryptographic authenticity. This must be tightened before SPEC v0.3 lands. All remaining issues are P2 clarity / implementability improvements that can be addressed concurrently but do not block adoption.

---

## 1. Conflicted‑Key Exclusion Attack (Ask 1)

**Attack scenario:** 2‑of‑3 actors (A honest, B compromised, C honest). The attacker wants to exclude A’s key and reduce the threshold in their favour by engineering an **authorized** fork conflict against A. The proposed vector is replaying a stale, once‑authorized rotation warrant (e.g., an old rotation that moved A’s key from `A1` to `A2`) and making it appear as an unordered‑key‑state warrant.

**State‑machine walk:**

The honest store DAG contains:

… → `RotOld` (A1→A2, signed by A & B, authorized at that time) → … → `RotNew` (A2→A3, signed by A & C, authorized under current 2‑of‑3 policy).  
`RotNew` lists the prior chain that includes `RotOld`, so in the global DAG there is a directed path `RotOld → … → RotNew` (ancestor/descendant relation).

The attacker, controlling only B, cannot mint a new rotation for A because A’s signature is missing. Their only hope is to **re‑play the existing `RotOld` record into a fork** that omits `RotNew`. They create a branch that diverges before `RotNew`, takes `RotOld` as its latest key‑state record for A, and adds other records on that branch.

Now, does a **key‑state conflict** arise? Rev 3 §5 says:

> “When two authorized key‑state warrants are unordered by the DAG (fork‑and‑merge), verifiers MUST report `WARN: key‑state conflict` …”

The two relevant warrants for A are `RotOld` and `RotNew`. In the global DAG, `RotNew` is reachable from `RotOld` via the honest chain; therefore they **are ordered** (ancestor/descendant). They are not “unordered by the DAG”. Consequently **no conflict is triggered**, A’s key is not excluded, and the threshold remains unchanged. The attack fails.

**Confirmation through arithmetic:** The conflict test is purely graph‑theoretic. Given the honest branch’s continuity, the stale rotation is always an ancestor of the current one. The attacker would need to create an **incomparable** rotation for A (e.g., a truly parallel branch with a new rotation warrant that diverges from a common ancestor *before* the old rotation), but to be authorized that warrant would require signatures from A and at least one other actor — they have neither. Thus the attacker cannot engineer an authorized fork conflict.

**Risk of ambiguity:** The spec does not explicitly state that conflict resolution applies only to **maximal** key‑state warrants (i.e., those without a descendant superseding them). Without this, an implementation could mistakenly treat any two rotation warrants as unordered if they sit on separate branches, even when one branch is a continuation of the other. That would be a spec‑silent area. I recommend a P2 clarification.

**Proposed amendment (P2):**

In §5, after the conflict rule, insert:

> “A key‑state warrant is only considered conflicting if there is no later authorized warrant for the same actor that is a descendant of it in the DAG. Two warrants that are ordered by the DAG (one reachable from the other) are not a conflict, even if they appear in separate branches; only indecomposable unordered warrants trigger this rule.”

---

## 2. `genesis.json` Trust (Ask 2)

Rev 3 includes (from Gemini’s suggestion) a `genesis.json` manifest:

> “Stores SHOULD contain a `genesis.json` in the store root: a map `{"roots": ["<WarrantID>"]}`. If present, verifiers MUST use these as the default genesis roots for settlement unless explicitly overridden by the verifier's local trust configuration.”

The problem: `genesis.json` is an ordinary file, not a warrant, not signed, and not content‑addressed. An attacker with **write access to the store’s filesystem** can edit it, substituting their own roots. A naive verifier that follows the `MUST use as default` directive would blindly trust the tampered file and accept the attacker’s roots as settlement‑active, potentially compromising the entire jurisdiction.

**Local‑override alone is not tamper‑evidence.** If the verifier’s local trust configuration is empty or “accept defaults,” the tampering succeeds silently. Even a warning after the fact is too late — the verifier has already incorporated the poisoned roots into its settlement calculus.

**Minimal binding rule:** The spec must **deny automatic trust** to `genesis.json`. It should be treated as an advisory hint, and a verifier may only rely on it after verifying its integrity out‑of‑band (e.g., the verifier’s local config pins the expected hash of the file, or the user explicitly confirms its content). This preserves the file’s intended purpose (portable default) without creating a trust anchor from a mutable artifact.

**Severity: P1** — if implemented verbatim, two independent verifiers could end up with different settlement‑active root sets based solely on who last edited the file, and no cryptographic evidence would detect the divergence until damage is done.

**Concrete amendment (P1):**

Replace the `genesis.json` paragraph in §9 with:

> “Stores SHOULD contain a `genesis.json` in the store root: a map `{"roots": ["<WarrantID>"]}`. This file is **advisory**; verifiers MUST NOT treat it as a trust anchor. Before using its listed roots as settlement‑active, a verifier MUST independently verify the file’s authenticity — typically by pinning its expected hash in the verifier’s local trust configuration or by requiring explicit user acceptance. If `genesis.json` is present but not yet verified, the verifier MUST report `WARN: genesis.json unverified` and MUST NOT use its contents for settlement.”

---

## 3. Strawman Flooding (Ask 3)

Rev 3’s §7(b) defines novelty strictly by outcome fingerprint; relevance is pushed to the policy layer. A permissive‑policy store can indeed be flooded with “fingerprint‑novel” re‑litigations:

- An attacker crafts a check that differs only in a throw‑away evidence blob, producing a new transcript hash and thus a new outcome fingerprint.
- Since the format layer only checks fingerprint absence, the warrant is admitted; the verifier must index it and potentially re‑run it.

**Is this acceptable without a format‑layer bound?** Yes. The format layer correctly captures the mechanically decidable part — whether the outcome has been seen before. Deciding if a novel outcome is actually **relevant** to the settled claim requires semantic reasoning, which belongs at the policy layer (or tool level). Attempting to encode anti‑flooding heuristics in the core protocol (e.g., limiting fingerprints per tunnel) would risk false positives and stymie legitimate post‑facto discovery. Unbounded‑but‑explicit is the right separation.

However, the spec should acknowledge the DoS surface and direct implementers to provide configurable limits. This is a P2 operational note.

**Proposed addition (P2):**

At the end of §7, append:

> “NOTE: Because novelty is purely syntactic, a store with a permissive settlement policy may accumulate an unbounded number of fingerprint‑distinct but substantively irrelevant re‑litigations. Implementations SHOULD provide configurable limits (e.g., maximum re‑litigations per tunnel, warning thresholds) to prevent resource exhaustion. Such limits are policy choices, not format requirements.”

---

## 4. Implementability Audit (Ask 4)

### 4.1 Outcome‑fingerprint definitions versus v0.2 records

- **`ski@v1` fingerprint:** `{runtime, term, expect, verdict, result_node_hash}`.  
  The `term` and `expect` are extracted from the `check` blob’s JCS‑canonical content; `result_node_hash` is computed by re‑evaluating the sigma‑glyph term. All fields are derivable without schema change. Re‑evaluation requires a sigma‑glyph interpreter, which is mandated by v0.2 spec, so no new capability is needed.

- **`cmd@v1` fingerprint:** `{runtime, sorted evidence hashes, verdict, transcript hash}`.  
  The warrant body’s `evidence` array is present. The sorting step is deterministic (lexicographic on hex hashes) and does not require schema changes. The **transcript** field is optional in v0.2. Rev 3 requires `transcript` for §7(b) use (novel consequence). That is enforceable: a re‑litigation warrant under (b) can simply be rejected if its check reason lacks `transcript`. No schema change needed — it’s a semantic requirement.

  **Ambiguity:** The tunnel’s outcome fingerprint set. Existing v0.2 check reasons may lack `transcript`, making their complete fingerprint unavailable. The spec must define how they are treated for novelty blocking. The safest rule: a check reason missing a required transcript is excluded from the tunnel’s fingerprint set, so it cannot block a later attempt under (b). This prevents divergence where one verifier treats a missing transcript as `null` and another ignores it entirely.

**P2 amendment (clarification):**

In §7, after the outcome fingerprint definition, add:

> “For the purpose of determining whether an outcome fingerprint appears in the tunnel, only check reasons that supply all required fields (including `transcript` for `cmd@v1`) are considered. If a runtime’s fingerprint definition mandates a field that a particular reason in the tunnel lacks, that reason is not part of the tunnel’s outcome fingerprint set and cannot block novelty under (b).”

### 4.2 `evidence` array fingerprint clarity

The proposal says “sorted evidence hashes”. It should explicitly note that “sorted” refers to the lexicographical ordering of the hex strings **after** extracting them from the `evidence` array (which may be in arbitrary order because JCS does not sort arrays). This is a minor but important implementability note.

**P2 clarification:**

After the fingerprint definition for `cmd@v1`, add:

> “(The `evidence` array in the warrant body is not ordered by JCS; the fingerprint is computed by sorting the hex‑string hashes in ascending lexicographic order.)”

### 4.3 Compatibility activation rules

Rev 3’s compatibility section states:

- Every v0.1/v0.2 body schema‑valid remains schema‑valid.
- v0.3 settlement rules MUST NOT turn a v0.1/v0.2 record into a schema error.
- Threshold checks activate only for blobs that declare `"warrant_policy": "0.3"`.
- Bound/unbound is a report unless a v0.3 policy says otherwise.

A v0.2 store upgraded in place will work: old records stay valid, their guarantees are unchanged, and new v0.3 features only engage when new‑format policy blobs or explicit adoption warrants are added. No incompatibility found. The fingerprint mechanism (even for old tunnels) is a verification‑layer computation, not a schema change. The missing‑transcript rule (above) ensures that old checks don’t suddenly cause false novelty blockages. The activation gates are explicit and safe.

**Verdict:** Implementable and backward‑compatible. No amendments needed beyond the P2 clarifications already noted.

---

## 5. Additional P2 Issues

### 5.1 Keyring derivation detail

Rev 3 mentions `keyring.json` as a cache derived mechanically from key‑state warrants but does not define the derivation algorithm (ordering, conflict handling, `since`/`until` computation). This could lead to differing key‑ring caches across implementations, causing inconsistent bound/unbound reports. I recommend (as Codex did) either fully specifying the derivation or removing the `keyring.json` file specification, leaving caching to implementations.

**P2:** Defer the keyring cache specification. The norm may simply state: “Implementations MAY derive a key‑state cache internally; any such cache MUST be purely deterministic from the DAG of key‑state warrants. No inter‑changeable `keyring.json` format is mandated by this spec.”

### 5.2 Adoption warrant subject clarification

Rev 3 says an adoption warrant is an `accept` whose subject is the new root’s first `WarrantID`. While `subject.hash` can hold a WarrantID, the phrasing “new root’s first WarrantID” is slightly misleading because a root *is* a warrant; its WarrantID is its own hash. Clarifying that the adoptor files an `accept` with `subject.hash` equal to the root’s WarrantID will help implementers.

**P2:** tweak §9 to say “… an `accept` warrant whose `subject.hash` is the WarrantID of the root to be adopted.”

---

## Relation to Prior Reviews

**Agree with Codex (gate 1):**

- **Novelty by outcome fingerprint:** Codex’s core insight — that byte‑new checks do not equal claim novelty — was correct. Rev 3 fully adopts this via outcome fingerprints, aligning with the original recommendation.
- **Multi‑root adoption and threshold:** Codex’s warnings about unadopted roots and spam roots were properly addressed in rev 2/3 with the settlement‑active / well‑signed distinction and policy‑scoped adoption. I consider those threats resolved.
- **Both‑keys rotation:** Codex’s analysis of the outgoing‑key compromise was accurate. Rev 3’s rotation rule now mandates current‑policy quorum (inc. threshold) and treats the incoming signature as proof‑of‑possession only, which is safe.

**Agree with Gemini (gate 2):**

- **“Names the settled claim” is unimplementable:** Gemini’s executable probe proved that the v0.2 check‑reason schema cannot carry a claim target. Rev 3 correctly removed that attempt and separated novelty (format) from relevance (policy). This is the right decoupling.
- **`genesis.json` as an in‑band default:** Gemini’s addition is valuable for portability, but rev 3’s trust rule is too trusting. My P1 amendment fixes the security gap without removing the feature.
- **Conflicted‑key exclusion:** Gemini identified the DoS veto in rev 2’s transition‑freeze. Rev 3 adopted the conflicted‑key exclusion, which is sound. I have independently verified that the stale‑rotation replay attack does not work under rev 3 because of DAG ordering; the exclusion rule is not exploitable by an attacker with a single compromised key.

**New findings not in prior reviews:**

- The stale‑rotation replay attack (ask 1) was not analysed in prior reviews; I show it is harmless under the current DAG‑ordering rule with a minor clarification.
- The `genesis.json` trust problem (ask 2) was not fully examined before; my P1 amendment is essential.
- The implementability audit (ask 4) uncovered several P2 gaps (transcript in tunnel fingerprints, evidence sorting, keyring spec) that need tightening.

---

## Final Recommendation

**Amend GOV‑001 rev 3 as follows, then adopt as SPEC v0.3:**

1. **P1 (mandatory):** Replace the `genesis.json` trust rule with the advisory‑only, verification‑required text proposed in §2 above.
2. **P2 (highly recommended):**
   - Clarify key‑state conflict ordering (maximal warrants) — §5.
   - Define tunnel outcome fingerprint handling for missing transcripts — §7.
   - Explicitly state evidence‑hash sorting for `cmd@v1` fingerprint — §7.
   - Add operational note on re‑litigation flooding — §7.
   - Defer or fully specify `keyring.json` derivation — §5.
   - Sharpen adoption warrant subject wording — §9.

With these changes, rev 3 is ready to graduate to SPEC v0.3.﻿The core security properties (conflict resolution, key binding, compatibility) hold under the amended rules.
