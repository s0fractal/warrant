# WRT-006: `ski@v1` under a moved implementation — closed with disposition **B (`ski@v2`)**

**Status:** **CLOSED — governance disposition B** (rev 3, 2026-09-02). Design proposal plus one
reproducer; no SPEC, `impl/`, vector or registry change is made by this document, and closing it
adopts nothing. What it records: (a) the finding that W1 moved the evaluator under an immutable
tag; (b) the evidence, hardened after two gates; (c) the disposition that follows from the SPEC's
own text rather than from a preference. The dependency question it opens — *how* Warrant should
obtain an evaluator per tag without vendoring — is **WRT-007**.

**Identifier note.** WRT-004 is carried by two documents on two branches; `MAP.md` records the
collision in its "Known identifier collisions" section, pinned to both `commit:path`, and
`tools/repo_map.py --check-map` parses that section structurally. Renumbering is a separate act.

Written by Claude Fable 5.1 at the owner's request. rev 1 (`defca553`) and rev 2 (`19dda35`) were
gated by Codex (AMEND, AMEND-with-disposition-B). A gate verdict is evidence, not adoption
(AGENTS.md rules 3–4).

**rev 3 — what the second gate changed.**
1. **A′ withdrawn for `ski@v1`.** SPEC §3.1 ("`ski@v1` names Book I v0.5 specifically; a later
   Book I is a different runtime tag") and §13.1 ("a tag is immutable … `ski@v1` names Book I v0.5;
   Book I v0.6 would be `ski@v2`") already fix the tag's meaning. Re-describing `ski@v1` as a
   Warrant-owned profile would redefine an immutable tag; the authority is the published SPEC
   text, not anyone's memory of intent. A′ survives as the right *shape for a new tag*.
2. **Evidence axes made independent.** rev 2's `corpus_equivalence` measured only mutual agreement:
   two engines returning the same wrong hash on every vector stayed green (reproduced by the gate).
   rev 3 checks each engine against the suites' **normative expected values** separately, checks
   the two suite documents carry the **same closed input set** (identity includes object-content
   digests; duplicates refuse; missing lists printed; count pinned at 33), and keeps agreement as
   its own axis. Dropping one HEAD vector now yields `suite_shape: MISMATCH`, exit 1.
3. **Boundary fixtures pinned exactly** (node `I` and `APPLY(I,I)` under a foreign key): E0's exact
   result hash and spend, E1's exact exception type and message. rev 2's sentence about "an APPLY
   node → DISSONANCE, spent 3" came from an unpinned object and is superseded by the pinned fixture
   (result: thunk normal form, spent 4).
4. **Layer status column added**; nothing is described as built that is not.
5. **Receipt binds the reproducer** (`reproducer_sha256`, schema id) and `exit` is taken from
   `eval_receipt` where an engine has it, derived exactly as the normative runner does.
6. Collision section of `MAP.md` checked as exact bullets inside the section, not by substring.

---

## 1. The finding

W1 (PR #44, merged 2026-09-01) replaced the bundled `impl/sigma_glyph.py` with the module from the
Σ-GLYPH phase-4a wheel built at sigma-glyph `5050ab7` — a Book I **0.6.0** tree (adopted bundle
v0.7.0). `trust/sigma-evaluator-provenance.json` binds the bytes and says `"adopted_bundle":
"v0.7.0"`. `git diff 9816937 4915494 -- SPEC.md` is empty: §3.1 still binds `ski@v1` to v0.5.
Under §13.1 this is "evaluating a later revision of the same external ruleset" under an immutable
tag. W1 is unreleased, so the boundary can still be set before a stranger pins the contradiction.

## 2. Evidence (rev 3, reproducer `proposals/wrt-006-model/differential.py`)

E0 = `98169375…:impl/sigma_glyph.py` (pre-W1, sha256 `0d2b898b…`); E1 = the module on this branch
(sha256 `55072bc0…`, W1's provenance value). Suites: Σ-GLYPH `v0.6.7` and `HEAD` (v0.7.0)
`vectors.json`, digests in the receipt.

| Axis | Result | Meaning |
|---|---|---|
| `suite_shape` | MATCH — 33 unique inputs in each document, identical sets (object bytes included), no duplicates | the two documents test one closed input set |
| `E0_conformance` | PASS — `result_hash` 66/66, `atp_spent` 66/66, `outcome` 64/64 checkable; `exit` not checkable (two-value API); 2 `outcome` rows not checkable | E0 satisfies both suites' normative values on every observable it can report |
| `E1_conformance` | PASS — `result_hash` 66/66, `atp_spent` 66/66, `outcome` 66/66, `exit` 33/33 (HEAD suite; v0.6.7 carries no `exit`) | E1 satisfies both suites, including the v0.7.0 exit observable |
| `differential_agreement` | MATCH — 66 replays over 33 unique inputs, 0 disagreements | on conforming inputs the engines agree |
| `ski_specimen` | MATCH — `examples/ski/check.json` → `887045bc…`, spent 20, both engines = `expect` | the one shipped `ski@v1` check re-executes identically |
| `boundary_observation` | EXPECTED_DIVERGENCE — fixture `I`: E0 `2f33694d…`, spent 1; fixture `APPLY(I,I)`: E0 `2f33694d…`, spent 4; E1 raises `ResourceFault('CAS key mismatch')` on both | on a non-conforming store E0 executes foreign bytes as the requested node; E1 refuses with a local fault (Book I 0.6.0 §3.5) |

Regression baseline, not equivalence evidence: `impl/warrant.py conformance examples` is 67/67
with either engine (ten `ski`-labelled checks, one re-execution — the specimen above).

Negative controls run by the gate and reproduced in rev 3: two engines returning the same wrong
hash → `differential_agreement: MATCH` but `E0/E1_conformance: FAIL`, exit 1; one HEAD vector
removed → `suite_shape: MISMATCH`, exit 1; a collision bullet moved into prose → `--check-map`
exit 1.

## 3. What the evidence establishes, and does not

It establishes that E1 is a **conforming Book I 0.6.0 engine** that also satisfies every v0.6.7
observable, and that E0 and E1 agree on every conforming input tested and disagree on a
non-conforming store. It does **not** establish equivalence on the admitted domain of `ski@v1`
(infinite), and — decisively for the disposition — it cannot establish that E1 *is* Book I v0.5,
because it is not: its provenance record and its §3.5 behaviour say 0.6.0.

## 4. Layers, with status

| Layer | Artifact | Status | Establishes |
|---|---|---|---|
| L1 corpus | `differential.py` (six axes) | **PARTIAL** — standalone reproducer; **not** wired into `tools/check.py` or CI | named finite evidence at named digests |
| L2 fuzz | E0 as a fourth engine in `tests/fuzz_differential.py` | **PLANNED** | agreement on N generated inputs over conforming stores |
| L3 model | sigma-glyph `eval_bridge_check.py` against E0 | **PLANNED**; same 33 vectors — model consistency, not new coverage | both engines bridged to one mechanized model on one corpus |
| L4 domain | which store inputs are inside `ski@v1` | **GOVERNANCE-DECIDED: B** — the SPEC text already binds the tag; no clause is proposed for `ski@v1` | — |

## 5. Disposition

**B.** `ski@v1` remains Book I v0.5. Book I 0.6.0 (the W1 evaluator) is filed under a new tag,
**`ski@v2`**, which may be specified as a Warrant-owned behavioural profile over a closed admitted
domain (the A′ shape, applied where it belongs: a new tag with its own registration under §13.1,
its own body version, its own fingerprint tuple for WRT-005, and its own vector set). Existing
`ski@v1` reasons are re-executed by a v0.5 evaluator or, if none is shipped, reported as
*unverified* with a named reason — never silently by E1.

What B does not decide: **which artifact** supplies the v0.5 evaluator, and whether Warrant should
keep vendoring anything at all. Measured in passing (recorded here, argued in WRT-007): the
published PyPI `sigma-glyph==0.6.7` wheel's `sigma_glyph.py` (sha256 `80299d68…`, byte-identical
to the `v0.6.7` tag module) passes the v0.6.7 suite 49/49, passes warrant's 67/67, agrees with E0
on all 33 inputs and the specimen, and behaves like E0 on the boundary. It is, by the SPEC's own
definition, a `ski@v1` evaluator that Warrant did not write and does not need to vendor.

## 6. Falsifiers (of the disposition, now that the design question is closed)

1. A reading of §3.1/§13.1 under which "Book I v0.5" names a *behavioural profile* rather than an
   upstream edition — that reading would have to be shown in the SPEC text as published, not
   supplied later.
2. A conforming-store input on which E0 ≠ E1 (L2) — irrelevant to B, relevant to what `ski@v2`'s
   vector set must contain.
3. Evidence that an already-published consumer relies on E1 under the `ski@v1` name — none is
   possible, since W1 is unreleased.

## 7. Relation to other documents

- **WRT-007** (proposed alongside): Warrant obtains its per-tag evaluator as an installed,
  digest-pinned artifact; the vendored copy is retired; `ski@v1` ← published `sigma-glyph==0.6.7`.
- WRT-005: its fingerprint tuple is per runtime tag; `ski@v2` gets its own.
- `trust/sigma-evaluator-provenance.json` (W1): under B it describes the `ski@v2` candidate, not
  `ski@v1`; its `adopted_bundle: v0.7.0` line is then correct for the tag it will serve.
- `manifesto/drafts/KELVIN-LAYERS-0.1.md` (non-normative): "a frozen name over a moved
  implementation → a new name"; vocabulary only, no credit crosses.
