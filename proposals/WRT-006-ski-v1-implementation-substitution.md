# WRT-006: `ski@v1` under a moved implementation — a Warrant-owned runtime profile, or `ski@v2`

**Identifier note.** Filed as **WRT-006**. The number WRT-004 is carried by two documents on two
branches (closed PR #21 verify-report; reason-binding profile `23ef810` on
`papers/the-reason-runs-again`). As of this revision `MAP.md` records that collision in a dedicated
section, pinned to both `commit:path` targets, and `tools/repo_map.py --check-map` fails if either
is missing. Resolving it by renumbering is a separate act.

**Status:** DRAFT **rev 2** (2026-09-02) — design plus one reproducer. No SPEC, `impl/`, vector or
registry change is made by this document; it carries no claim of adoption. Written by Claude
Fable 5.1 at the owner's request; rev 2 answers the Codex design gate on rev 1 (`defca553`,
verdict AMEND). A gate verdict is evidence, not adoption (AGENTS.md rules 3–4).

**rev 2 (2026-09-02) — what changed after the gate.** (1) Evidence cardinality corrected: the two
Σ-GLYPH suite documents carry the **same 33 operational inputs**; the earlier "66/66 + 67" is now
"33 unique inputs replayed from two suite documents + 1 `ski@v1` specimen", with warrant's 67/67
kept as a regression baseline, not as equivalence points. (2) The word *equivalence* is removed
from every credit-bearing field; the finite evidence is **profile-conformance / regression
evidence**. (3) Option A is restated as **A′: a Warrant-owned behavioural profile over a closed
admitted domain** — the reviewer's formulation, adopted. (4) The reproducer is three-axis with
typed verdicts, path-independent, writes only to a `TemporaryDirectory`, discovers the sibling
checkout, and asserts the boundary observation rather than narrating it. (5) The boundary
observation is stated more exactly than rev 1: E0 *executes* foreign bytes as the requested node
(with node-`I` bytes: normal form, spent 1 — the W1 test's own description; with an APPLY node:
DISSONANCE, spent 3); rev 1 had reported only the DISSONANCE case. (6) Option B's cost rebalanced;
L3 labelled model-consistency, not new coverage; L4 restated as owner/governance act, with the
reviewer attacking the classification.

---

## 1. The problem, in the SPEC's own words

`SPEC.md` §3.1: "`ski@v1` names Book I **v0.5** specifically; a later Book I is a different
runtime tag" and "an implementation MUST pin the Book I ruleset it evaluates against by version and
content … so `ski@v1` semantics cannot be changed under it."

`SPEC.md` §13.1: "**A tag is immutable.** A semantic change — including evaluating a later revision
of the same external ruleset — is a NEW tag, never a redefinition. `ski@v1` names Book I v0.5;
Book I v0.6 would be `ski@v2`."

W1 (PR #44, merged 2026-09-01) replaced the bundled `impl/sigma_glyph.py` with the module from the
Σ-GLYPH phase-4a wheel built at sigma-glyph `5050ab7` — a Book I **0.6.0** tree (adopted bundle
v0.7.0). `trust/sigma-evaluator-provenance.json` binds the bytes and says
`"adopted_bundle": "v0.7.0"`. `git diff 9816937 4915494 -- SPEC.md` is empty: §3.1 still says v0.5.

Read literally, the repository now evaluates `ski@v1` with "a later revision of the same external
ruleset". Either the tag's meaning is *not* "exact upstream Book identity" and the SPEC should say
what it is instead, or it is and `ski@v2` is owed. This must be decided before any release carries
W1: a released verifier is what strangers pin.

## 2. What has been measured (rev 2, 2026-09-02)

Reproducer: `proposals/wrt-006-model/differential.py`. Engines: **E0** = the module at
`98169375…:impl/sigma_glyph.py` (pre-W1, sha256 `0d2b898b…`), **E1** = the module on this branch
(sha256 `55072bc0…`, the value in the W1 provenance record). Three typed axes, none substituting for
another:

| Axis | Input | Result |
|---|---|---|
| `corpus_equivalence` | the **33 unique** `kind=eval` inputs (term, atp, store subset) shared by the v0.6.7 and HEAD/v0.7.0 suite documents, replayed from both (66 replays); compared on the engine's own canonical NodeHash of the result and on `atp_spent` | **MATCH** — 33/33 unique inputs, 0 errors |
| `ski_specimen` | `examples/ski/check.json` (this repository's one shipped `ski@v1` check) over its five blobs, both engines vs `expect` | **MATCH** — both `887045bc…`, spent 20 |
| `boundary_observation` | valid node bytes stored under a key they do not hash to; `eval` of that key | **EXPECTED_DIVERGENCE** — E0 *executes* the bytes as the requested node (node-`I` bytes → normal form, spent 1; an APPLY node → DISSONANCE, spent 3); E1 refuses with `ResourceFault('CAS key mismatch')`, a local fault, not a canonical outcome |

Regression baseline (not equivalence evidence): `impl/warrant.py conformance examples` is 67/67
with either engine; of its ten `ski`-labelled checks one is a re-execution (the specimen above), the
rest are schema, signature and MUST-REJECT checks. The v0.7.0 suite adds `expected.exit` and
changes no expected value on the 49 vector ids it shares with v0.6.7.

The boundary row is the finding. On every conforming input tested the engines agree. On a
non-conforming store they do not: E0 yields a canonical outcome, E1 a refusal — Book I 0.6.0 §3.5
("bytes under a key they do not hash to MUST NOT execute as that key's node") inside a module the
tag says is v0.5.

## 3. The obligation, stated exactly

Let **D** be the admitted domain of `ski@v1`: check blobs `{ski:1, term, atp:uint32, expect}`
evaluated over a warrant blob store used as the Σ-GLYPH CAS (§3.1 rule 2: every demanded object
MUST resolve among the store's blobs).

The statement a release would need: **for all `(term, atp, store) ∈ D`, `E0` and `E1` yield the same
`(result NodeHash, atp_spent)` and the same verdict/refusal class.** §2 establishes this at 34
points and exhibits one input where they differ; whether that input is in D is the whole question.
No finite corpus, fuzz run or model bridge establishes the universal statement, and none is claimed
to.

## 4. The gate — four layers, each stating its own coverage

| Layer | Artifact | Establishes | Does not establish |
|---|---|---|---|
| L1 corpus | `differential.py` receipt, wired into `tools/check.py` and CI with E0 pinned by commit | agreement on 33 + 1 named inputs at named digests | anything off-corpus |
| L2 fuzz | E0 added as a fourth engine to the existing differential fuzzer (`tests/fuzz_differential.py`; sigma-glyph runs Python/Rust/warrant-go per push) | agreement on N generated terms and budgets over conforming stores, N recorded | a proof |
| L3 model | sigma-glyph's `eval_bridge_check.py` (Lean `EvalMachine` ↔ oracle) run against **E0** as well as E1 | both engines are consistent with one mechanized model **on the same 33 vectors** — model consistency, not new coverage | coverage beyond those vectors |
| L4 domain | a SPEC clause (§5, A′) stating whether a non-conforming store is inside D | the boundary is decided by the owner/governance act, so §2's boundary row has a normative reading | that the decision is right — the gate reviewer attacks the classification; the owner sets it |

L1–L3 are mechanical. L4 is the reason this document exists.

## 5. Two options

### Option A′ — `ski@v1` as a Warrant-owned runtime profile over a closed admitted domain

Instead of asking whether Book I v0.5 and 0.6.0 are "equivalent" (a claim about upstream this
repository cannot make), Warrant takes ownership of what its tag means:

```text
runtime tag:            ski@v1  (Warrant-owned behavioural profile)
admitted domain:        the closed check schema of §3.1, over a conforming CAS —
                        every demanded object resolves under its own SHA-256
observable contract:    result NodeHash + atp_spent + verdict/refusal class
source implementation:  provenance only (today: Σ-GLYPH Book I 0.6.0 tree at 5050ab7)
validation:             profile-conformance evidence at named digests (L1–L3)
```

Proposed SPEC §3.1 text (replacing "per Σ-GLYPH Book I v0.5 … `ski@v1` names Book I v0.5
specifically"):

> `ski@v1` is a Warrant-owned runtime profile. Its semantics are fixed by this section and by the
> normative `ski@v1` vector set (§8.2), which pins canonical results and ATP spend over a
> **conforming CAS**: every object an evaluation demands resolves under its own SHA-256. Bytes
> stored under a key they do not hash to are **outside the domain** of `ski@v1`; a verifier MUST
> refuse to evaluate them and MUST report the reason as *unverified* (§6), never as `pass`, `fail`
> or a canonical outcome. The profile was derived from Σ-GLYPH Book I v0.5 and is checked against
> Book I's conformance vectors; the bundled implementation's provenance is recorded in
> `trust/sigma-evaluator-provenance.json` and MAY change so long as the profile's conformance
> evidence (§8.2 vectors, the differential fuzzer, the model bridge) is re-established and named
> in that record. An implementation that executed non-conforming bytes and returned a canonical
> outcome was non-conforming to rule 2 of this section.

Provenance record changes: `"adopted_bundle": "v0.7.0"` stays as **source provenance**; add
`"runtime_profile": "ski@v1"`, `"admitted_domain": "conforming-cas/closed-check-schema"`,
`"predecessor_module_sha256"`, and `"profile_conformance_receipts": [...]` naming the L1 receipt
digests. `tools/sigma_provenance_check.py` fails if the module changed and no receipt names its
predecessor. **No field says "equivalence".**

Cost: a SPEC document-version bump (prose change to §3.1 and §13.1's example; no body-schema
change — §14.3 governs the number); L1–L3 built; one fuzzer participant; one check. No record,
WarrantID or verdict over any conforming store changes. What Warrant gives up: the ability to define
the tag by pointing at an upstream version — it must now own the vector set as normative.

### Option B — register `ski@v2`

`ski@v2` names Book I 0.6.0 semantics (Receipt interface, §3.5 refusal); `ski@v1` keeps a v0.5-era
evaluator pinned. Implementation choices are open: the wheel may bundle two evaluators, or bundle
one and reject `ski@v1` re-execution as *unverified* with a named reason, or ship `ski@v1` as a
separate optional package. Existing records keep their tag and verify as before; new checks are
filed as `ski@v2`; WRT-005's outcome-fingerprint tuple is defined per tag.

Cost: a new body version (§13.1: a new tag needs one); every check-writing consumer (oaip's
reserved runtime, decision-archaeology's adapter, sigma-glyph's governance vectors) chooses a tag;
and the precedent that a strictness fix at the domain boundary is a semantic change — which it is,
if the tag means exact upstream identity.

### The decision this document asks for

Not A′ vs B on the merits alone, but first the prior question **what `ski@v1` means**:

- If `ski@v1` means "**exact upstream Book I v0.5 identity**" (the plain reading of §3.1/§13.1
  today), then W1 already evaluates under a later ruleset and **B is mandatory**; A′ would be a
  redefinition of an immutable tag.
- If Warrant is willing to **own the profile** (A′), the measured record (33 + 1 agreement, no
  expected value moved across the suite bump) is what a moved implementation under a stable
  profile looks like, and the one divergence lies on inputs rule 2 already excluded.

Recommendation: **A′**, because it separates the four things rev 1 conflated — implementation
provenance, the tag's normative semantics, corpus evidence, and the unproven universal statement —
and because B would make every future boundary-strictness fix a new tag. The recommendation is
conditional on the owner accepting profile ownership; that acceptance is a governance act (a SPEC
bump adopted the way SPEC bumps are adopted), not a review verdict.

## 6. Stopping rule

rev 2 → one adversarial pass (the reviewer of rev 1, or another vendor) plus the owner's
disposition. If the reviewer disputes the *classification* in L4 (that a non-conforming store lies
outside D) and the owner does not resolve it by governance act within that round, this proposal
**closes with B** as its outcome and says so at the top. No third round: the meaning of the tag is
the owner's to fix, not the author's to argue.

## 7. What this document does not claim

- Equivalence of E0 and E1 on D. It claims agreement on 34 named inputs and one located divergence.
- That W1 was wrong. W1's refusal is the safer behaviour; the question is under which name and
  under whose ownership it ships.
- That L1–L3 constitute a proof. They are three witnesses with stated coverage, one of which (L3)
  reuses L1's vectors.
- Any adoption, release readiness, or change to what `warrant-verify` 0.9.0 on PyPI does.

## 8. Falsifiers

1. L2 fuzzing finds a conforming-store input where E0 ≠ E1 → A′'s premise fails; fix the diverging
   engine or take B.
2. A reviewer exhibits a consumer that relied on E0 executing foreign-key bytes → A′ breaks it; B.
3. `eval_bridge_check.py` cannot run against E0 unmodified → L3 is weaker than claimed; the
   receipt says so and does not count it.
4. The provenance-receipt rule (A′) cannot be enforced in `sigma_provenance_check.py` without
   reading git history → the rule becomes CI prose and the proposal says the witness is advisory.
5. The owner states that the July intent of `ski@v1` was exact upstream identity → B; §5 A′'s
   SPEC text is withdrawn, not amended.

## 9. Relation to other documents

- `trust/sigma-evaluator-provenance.json`, `tools/sigma_provenance_check.py` (W1): unchanged here;
  A′ proposes additions.
- WRT-005: orthogonal; its fingerprint tuple is per runtime tag.
- `MAP.md` "Known identifier collisions": introduced with this revision for WRT-004.
- `manifesto/drafts/KELVIN-LAYERS-0.1.md` (non-normative): names this situation "a frozen name over
  a moved implementation"; vocabulary only, no credit crosses.
