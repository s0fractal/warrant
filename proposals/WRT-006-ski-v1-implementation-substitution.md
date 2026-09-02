# WRT-006: `ski@v1` under a moved implementation — an equivalence gate, or `ski@v2`

**Identifier note.** Filed as **WRT-006**. WRT-005 is the last number on `master`. The number
WRT-004 is currently carried by **two different documents** on two branches — the closed
verify-report work (PR #21, `7f40932…:proposals/WRT-004-verify-report-v1.md`, which `MAP.md`
records) and a reason-binding profile (`23ef810`, 2026-08-28, on `papers/the-reason-runs-again`,
which `MAP.md` does not record). WRT-006 does not reuse either and asks that the collision be
resolved in `MAP.md` before another number is minted.

**Status:** DRAFT rev 1 (2026-09-02) — **design plus one reproducer.** No SPEC edit, no change to
`impl/`, no vector change, no registry change is made by this document. It carries no claim of
adoption. Written by Claude Fable 5.1 at the owner's request, from the finding raised by Codex in
review of the 2026-09 trajectory audit (`…/trajectory-audit-fable-5.1-2026-09/07-CORRECTIONS-CODEX-PASS.md`
§1.2). It is filed for an adversarial gate by the owner and Codex under `reviews/`; a gate verdict
is evidence, not adoption (AGENTS.md rule 3–4).

---

## 1. The problem, in the SPEC's own words

`SPEC.md` §3.1: "`ski@v1` names Book I **v0.5** specifically; a later Book I is a different
runtime tag." And: "an implementation MUST pin the Book I ruleset it evaluates against by version
and content … so `ski@v1` semantics cannot be changed under it."

`SPEC.md` §13.1: "**A tag is immutable.** A semantic change — including evaluating a later
revision of the same external ruleset — is a NEW tag, never a redefinition. `ski@v1` names Book I
v0.5; Book I v0.6 would be `ski@v2`."

W1 (PR #44, merged 2026-09-01) replaced the bundled `impl/sigma_glyph.py` with the module extracted
from the Σ-GLYPH phase-4a wheel built at sigma-glyph `5050ab7` — a tree whose Book I is **0.6.0**
(adopted bundle v0.7.0). `trust/sigma-evaluator-provenance.json` binds the bytes and says
`"adopted_bundle": "v0.7.0"`. `git diff 9816937 4915494 -- SPEC.md` is empty: §3.1 still says v0.5.

So, read literally, the repository now evaluates `ski@v1` with "a later revision of the same external
ruleset", which §13.1 says is a new tag. Either that reading is wrong because the *semantics* did
not move (only the implementation did), or it is right and `ski@v2` is owed. This proposal is the
procedure for deciding which, with evidence rather than by assertion — and it must be decided
**before** any release carries W1, because a released verifier is what strangers pin.

## 2. What has been measured (rev 1, 2026-09-02)

Reproducer: `proposals/wrt-006-model/differential.py` (writes nothing; prints one receipt; exits
non-zero on any disagreement or any vector an engine cannot run). Engines: **E0** = the module at
`98169375…:impl/sigma_glyph.py` (pre-W1, sha256 `0d2b898b…`), **E1** = the module on this branch
(sha256 `55072bc0…`, the W1 provenance value).

| Measurement | Result |
|---|---|
| `kind=eval` vectors of the Σ-GLYPH **v0.6.7** suite (33) and **HEAD/v0.7.0** suite (33), E0 vs E1 on `(result_hash, atp_spent)` | **66/66 agree**, 0 errors |
| Expected `result_hash / atp_spent / outcome` on the 49 vector ids common to v0.6.7 and v0.7.0 | identical (v0.7.0 adds `expected.exit`, changes no value) |
| `impl/warrant.py conformance examples` with the bundled engine, and with `SIGMA_GLYPH=` a Σ-GLYPH HEAD checkout | 67/67 both |
| **Domain-boundary control:** bytes stored under a key they do not hash to, evaluated at the module level | **E0 executes** them and returns a canonical `DISSONANCE` (spent 3); **E1 refuses** with `ResourceFault('CAS key mismatch')` — a local fault, not a canonical outcome |

The last row is the finding. On every conforming input tested the two engines are equal. On a
non-conforming store they are **not**: E0 yields a canonical result, E1 yields a refusal. That
difference is Book I 0.6.0 §3.5 ("Bytes under a key they do not hash to MUST NOT execute as that
key's node") living inside a module that `ski@v1` says is Book I v0.5.

## 3. The obligation, stated exactly

Let **D** be the admitted domain of `ski@v1`: check blobs `{ski:1, term, atp:uint32, expect}` evaluated
over a warrant blob store used as the Σ-GLYPH CAS (§3.1 rule 2: "every object the evaluation demands
MUST resolve among the store's blobs").

Claim to be established: **for all `(term, atp, store) ∈ D`, `E0(term, atp, store) = E1(term, atp,
store)`** as `(result_hash, atp_spent)`.

What §2 establishes: equality at 66 + 67 points; equality of the normative expectations across the
suite bump. What it does not: equality on D, which is infinite; and it exhibits one input where the
engines differ, whose membership in D is exactly the open question.

## 4. The gate — four layers, each stating its own coverage

| Layer | Artifact | Establishes | Does not establish |
|---|---|---|---|
| L1 corpus | `differential.py` receipt, wired into `tools/check.py` and CI with E0 pinned by commit | equality on the named corpora at named digests | anything off-corpus |
| L2 fuzz | add E0 as a fourth engine to the existing three-way differential fuzzer (`tests/fuzz_differential.py`; sigma-glyph runs Python/Rust/warrant-go on every push) | equality on N random terms/budgets over conforming stores, with N recorded | a proof |
| L3 model | run sigma-glyph's `eval_bridge_check.py` (Lean `EvalMachine` ↔ oracle, 33 vectors) against **E0** as well as E1 | both engines are bridged to one mechanized model on one corpus | bridge coverage beyond its vectors |
| L4 domain | a SPEC clause (§5, option A) that says whether a non-conforming store is in D | the boundary is *decided*, so the §2 control has a verdict | that the decision is wise — that is the gate reviewer's question |

L1–L3 are mechanical and can be built without a decision. L4 is a decision and is the whole reason
this document exists: without it, the §2 control is a disagreement inside `ski@v1`, and §13.1 applies.

## 5. Two options

### Option A — keep `ski@v1`; decide the boundary; pin by witness

1. **SPEC §3.1 clause (proposed text):** "The store a `ski@v1` evaluation runs over MUST be a
   conforming CAS: every object resolves under its own SHA-256. Bytes stored under a key they do
   not hash to are **outside the domain of `ski@v1`**; a verifier MUST refuse to evaluate them and
   MUST report the reason as *unverified* (§6), never as a canonical outcome. An evaluator that
   executed such bytes and returned a `DISSONANCE` was non-conforming to rule 2 of this section."
   Effect: E0's boundary behaviour is classified as a defect that E1 corrects; E1's refusal becomes
   enforcement of an existing MUST, not a semantic change; §13.1 is not triggered.
2. **Pinning rule amendment (§3.1):** pin the ruleset "by version and content" *and* by an
   **equivalence witness** — the L1 receipt naming the previous bundled engine — whenever the
   bundled module changes under an unchanged tag. `trust/sigma-evaluator-provenance.json` gains a
   `predecessor_module_sha256` and `equivalence_receipt_sha256`; `tools/sigma_provenance_check.py`
   fails if the module changed and no witness names its predecessor.
3. **Provenance record honesty:** `"adopted_bundle": "v0.7.0"` stays as *source provenance*; a new
   field `"ski_runtime_semantics": "Book I v0.5 (ski@v1); equivalence witnessed"` states what the tag
   promises, so the two versions stop reading as a contradiction.
4. L1–L3 built and green before release.

Cost: one SPEC document-version bump (prose clarification, no body-schema change; the §14.3 rule on
which number moves applies), one new check, one fuzzer participant. No record, WarrantID or
verdict on any conforming store changes.

### Option B — register `ski@v2`

`ski@v2` names Book I 0.6.0 (v0.7.0 bundle) with the Receipt interface and §3.5 refusal; `ski@v1`
keeps E0 pinned forever as its evaluator. New checks are filed as `ski@v2`; old records verify as
before.

Cost: two bundled evaluators in the wheel indefinitely; a body-version bump (§13.1: a new tag needs
a new body version); every consumer that writes checks (oaip's reserved runtime, decision-archaeology's
adapter, sigma-glyph's own governance vectors) chooses a tag; WRT-005's fingerprint tuple is defined
per tag. And the honest cost: it concedes that a bug-fix at the domain boundary is a semantic change,
which makes every future strictness fix a new tag.

### Recommendation

**A, conditionally.** The measured record (66/66, 67/67, expectations unchanged) is what "same
semantics, moved implementation" looks like; the one divergence is on inputs rule 2 already forbade.
Option A says so in the SPEC instead of leaving it to a provenance file. **The condition:** if the
gate reviewer disputes that non-conforming stores lie outside D — i.e. argues that `ski@v1` promised
a canonical outcome on *any* store — then A is a redefinition and **B is owed**. This is a question
about what §3.1 rule 2 meant in July, and it is the reviewer's to answer, not this author's.

## 6. Stopping rule

rev 1 → one adversarial design gate (Codex or another vendor) plus the owner's disposition. If the
gate returns AMEND on anything other than L4, amend and re-gate once. If it returns AMEND or REJECT
on L4 twice, this proposal **closes with option B** as its outcome and says so at the top, in the
manner of WRT-003/WRT-004. No third round on L4: the domain question is a decision, and a decision
that will not settle in two rounds should be made by the owner, not argued by the author.

## 7. What this document does not claim

- That E0 ≡ E1 on D. It claims equality on the named corpora and one located divergence.
- That W1 was wrong. W1's refusal is the *safer* behaviour; the question is under which name it ships.
- That L1–L3 constitute a refinement proof. They are three witnesses with stated coverage.
- Any adoption, any release readiness, any change to what `warrant-verify` 0.9.0 on PyPI does.

## 8. Falsifiers

1. L2 fuzzing finds a conforming-store input where E0 ≠ E1 → option A is false as stated; B is owed,
   or the divergence is a defect in one engine and is fixed *there* before any decision.
2. A reviewer exhibits a July-era consumer that relied on E0's canonical `DISSONANCE` for foreign bytes
   → A would break a consumer; B.
3. sigma-glyph's `eval_bridge_check.py` cannot be run against E0 without modification → L3 is
   weaker than claimed; say so in the receipt and do not count it.
4. The provenance-witness rule (A.2) turns out to be unenforceable in `sigma_provenance_check.py`
   without reading git history → the rule moves to CI prose, and the proposal says the witness is
   advisory.
5. The owner decides the June/July intent of rule 2 was "any bytes the store returns" → B, and this
   document's §5 A.1 text is withdrawn, not amended.

## 9. Relation to other documents

- `trust/sigma-evaluator-provenance.json` and `tools/sigma_provenance_check.py` (W1): unchanged by
  this draft; A.2–A.3 propose additions.
- WRT-005 (outcome-fingerprint purity): orthogonal; its fingerprint tuple is per runtime tag, so
  option B doubles it and option A leaves it alone.
- `manifesto/drafts/KELVIN-LAYERS-0.1.md` (non-normative draft): names this situation "a frozen name
  over a moved implementation" and asks for exactly an equivalence gate or a new name; cited for
  vocabulary only, no credit crosses.
