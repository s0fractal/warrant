# WRT-007: A Warrant release addressably selects one evaluator per immutable runtime tag

**Status: CLOSED — DEFERRED by its own stopping rule (§6), 2026-09-02.** Three gates (rev 1
`677632e`, rev 2 `342f57e`, rev 3 `a2b3976`), each AMEND on the positive-credit boundary. §6 says a
second AMEND on the same layer closes the proposal as *deferred* with §2's measurements retained,
and it does. **Retained as design evidence:** per-tag module digest checked **before import**;
the separation of runtime semantics (registry, bound to SPEC bytes) from release selection
(manifest, bound to registry/record/receipt commitments); `active` vs inert `candidate`; the
measured fact that the published `sigma-glyph==0.6.7` module is a `ski@v1` evaluator by SPEC §3.1.
**Not retained:** any path to `credit_bearing: true` — the reproducer is now unconditionally
non-crediting (§8). Activation and release-binding are a separate, smaller act (§8).

Written by Claude Fable 5.1 at the owner's request. A gate verdict is evidence, not adoption
(AGENTS.md rules 3–4).

**rev 3 — what the second gate changed.** (1) **The registry binds bytes, not prose.** Each registered
tag carries `semantics.spec_commit` + `spec_sha256` (exact `SPEC.md` bytes), a
`vector_manifest_commitment`, and a structured `store_contract` (rule, SPEC digest, enforcing code
path, test path + digest); the checker re-derives the SPEC digest from git at run time. (2) **The
manifest binds the registry**: `registry_sha256` and, per selection, `selected_runtime_record_commitment`
and `conformance_receipt_sha256` (the WRT-006 receipt's host-independent `core_sha256`), plus the
exact `warrant_release.commit`. A one-sided edit of SPEC, registry, specimen files or the manifest
now fails a named binding before anything runs. (3) **`active` vs `candidate`**: `ski@v2` moved to
`candidates`, inert, never loadable; `credit_bearing` is **false** until `activation.status` is
`active` with a named act — the repository-default path is a mechanism result, not adoption.
(4) The `examples/ski/*` closed filename→digest map is verified before any run. (5) Closed schemas are
recursive and typed (enums, hex64-or-null, ints); nested extra fields refuse.

**Thesis in one sentence:**

> A runtime tag names an immutable semantics and a vector manifest (SPEC §13.1); a Warrant release
> names, by digest, the one evaluator it ships for that tag; the two must never be the same record,
> and a mismatch between what a release ships and what it declares must refuse before any byte runs.

---

## 1. Why now

WRT-006 found that W1 replaced the bundled evaluator under the immutable `ski@v1` tag and closed
with disposition B (`ski@v2` for Book I 0.6.0). That settles the *name*. It leaves the *supply*
question: today the tag's evaluator is whatever bytes sit in `impl/sigma_glyph.py` at release time,
bound by a provenance record that names the bytes but not the tag. Vendoring is not the defect —
the missing per-tag selection record is. ADR-012 (sigma-glyph) measures its campaign by "no consumer
vendors or reimplements the evaluator"; this proposal meets the *intent* of that metric (no hidden
copy whose identity is unrecorded) without adopting a delivery channel.

## 2. What was measured (2026-09-02)

| Fact | Value |
|---|---|
| PyPI `sigma-glyph==0.6.7` wheel (downloaded, not installed) | sha256 `c3b7bc32…`; its `sigma_glyph.py` sha256 `80299d68…`, **byte-identical to the `v0.6.7` git tag module**; docstring "oracle semantics v0.5.x" |
| that module vs Σ-GLYPH `v0.6.7` suite (format 2: `result_hash`, `atp_spent`, `outcome`) | `PASS` 33/33/33 |
| that module vs Σ-GLYPH HEAD suite (format 3, adds `exit`) | `PARTIAL_UNREPORTABLE:exit` — 33/33/33 on the three fields; `exit` has no observable in a two-value engine |
| that module vs warrant `conformance examples` | 67/67 (pre-W1 override; W1 differential mode) |
| WRT-006 differential, that module as E1 vs E0 (pre-W1 bundled) | `suite_shape MATCH`, agreement 33/33, specimen MATCH; boundary: executes foreign-key bytes exactly as E0 |
| `installed_engine_check.py` on that module + wheel, repository-default records, `activation: draft` | `ARTIFACT_AND_MODULE_PINNED_AND_CONFORMING`; all five bindings BOUND (registry sha, runtime-record commitment, SPEC bytes at `spec_commit`, specimen map, conformance receipt); **`credit_bearing: false`** (no activation act) |
| W1's module (`55072bc0…`) vs the `ski@v1` selection | `NOT_THE_PINNED_EVALUATOR`; differential **not run**, module **not imported** |
| a module with an import side effect, wrong sha | refused before import; side-effect marker absent |
| caller-supplied manifest naming W1's module as `ski@v1` | `TEST_PROFILE_RESULT`, `authority: caller-supplied`, `credit_bearing: false` |
| manifest with an extra field (`equivalence: witnessed`) | `REGISTRY_OR_MANIFEST_INVALID` (closed schema) |
| registry with an altered specimen digest, manifest untouched | `BINDING_FAILURE` on `manifest_registry_sha256`, `selected_runtime_record`, `ski_specimen_map` |
| nested extra field (`vector_manifest.sigma_book1_suite.equivalence`, `artifact.equivalence`) | `REGISTRY_OR_MANIFEST_INVALID` (recursive closed schema) |
| `--tag ski@v2` (candidate) | `TAG_NOT_REGISTERED`; a candidate is never loaded |
| manifest `conformance_receipt_sha256` altered | `conformance_receipt: MISMATCH`, credit false |

Reproducers: `proposals/wrt-007-model/installed_engine_check.py`; `proposals/wrt-006-model/differential.py`.
Draft records: `proposals/wrt-007-model/runtime-registry.json`, `…/release-evaluator-manifest.json`.

## 3. The proposal

### 3.1 Runtime registry — normative, per tag, owned by SPEC §13.1

```text
ski@v1 → semantics: Book I v0.5 (SPEC §3.1)
         body versions: 0.2
         vector manifest: sigma-glyph v0.6.7 vectors.json (format 2) sha256 322fd290…, required
                          {result_hash, atp_spent, outcome}; warrant examples/ski/* by sha256
         store contract: §3.1 rule 2, enforced by Warrant's fetch layer
ski@v2 → NOT REGISTERED (placeholder from WRT-006 B): Book I 0.6.0; format-3 manifest; new body version
```

The registry says what a tag *means* — bound to exact `SPEC.md` bytes at a named commit, a vector manifest
commitment, and a structured store contract — and what any evaluator (this repository's, a stranger's, a Go
or Rust one) must satisfy. It names no implementation. It is the §13.1 registration table made
machine-readable; a new tag is a new row, never an edit.

### 3.2 Release evaluator manifest — operational, per (release, tag), owned by the release

```text
(warrant-verify <release>, ski@v1) → form: vendored-file | distribution
                                     module sha256 80299d68…
                                     artifact provenance (distribution, version, wheel sha256)
                                     conformance receipt sha256 (WRT-006 receipt at that module)
(warrant-verify <release>, ski@v2) → null until ski@v2 is registered and a conforming module exists
```

Exactly one **active** evaluator per (release, tag); `candidates` are inert. The manifest pins the registry
(`registry_sha256`), the selected runtime record (commitment), the conformance receipt (`core_sha256`) and the
release commit. `load_sigma(tag)` locates the module file, hashes it **before import**, and compares it to the
active selection; mismatch → the module is not imported and every
reason under that tag reports *unverified* with reason `evaluator-not-pinned`. This replaces W1's
"is the override byte-identical to the bundled file" with "is the file the release declared for this
tag" — the same fail-closed shape, now addressable per tag and per release.

### 3.3 Operational form — delivery-agnostic

The manifest's `form` may be:

- **vendored files, one per tag** — `impl/sigma_glyph_v05.py` (sha `80299d68…`, the v0.6.7 module)
  for `ski@v1`; `impl/sigma_glyph_v06.py` (sha `55072bc0…`, W1's module) for `ski@v2` once
  registered. No packaging change, no PyPI dependency, no one-version-per-environment problem, and
  the README's offline promise holds trivially. **Recommended now**: the owner's "simplify without
  losing integrity" is exactly this — integrity is the digest in the manifest, not the channel.
- **a published distribution** — `sigma-glyph==0.6.7` by wheel digest, or a future frozen
  distribution per frozen tag (`sigma-glyph-book1-v05`). Same manifest, different `form`. This is
  what an IPFS/torrent/registry delivery layer would later fill in; the manifest does not change.

Whichever form, `installed_engine_check.py` verifies the module against the manifest and the tag
against the registry; `artifact_identity` is `VERIFIED` only when a wheel is presented and both the
wheel digest and the module inside it match.

### 3.4 Identity-by-Hash stays in Warrant

W1's fetch-layer refusal (`run_ski_check`, `tests/sigma_cas_identity.py`) is kept and is now the
registry's `store_contract`. A v0.5 evaluator executes foreign-key bytes (measured); Warrant's store
contract refuses them *before* any evaluator sees them, under either tag.

### 3.5 What this changes in the dependency graph

The runtime edge warrant → Σ-GLYPH Book I becomes a per-tag, per-release, digest-addressed
selection record instead of an anonymous file. The reverse edges (sigma-glyph CI running the
warrant CLI for governance; Book III as a Warrant v0.3 profile) are unchanged and remain what they
are — tooling and a normative profile relation. The bootstrap practice stays and stays credit-free;
what is removed is the one place where the cycle could silently change semantics under a frozen name.

## 4. What this proposal does not claim

- Equivalence of the v0.6.7 module and the pre-W1 bundled module on the admitted domain — measured
  equal on 33 + 1 inputs and both conforming to the tag's manifest; not proven equal.
- That a vendored file is "published" — `artifact_identity` is `NOT_VERIFIED` for a loose file, and
  the manifest records artifact provenance as provenance, not as a runtime dependency.
- That the registry is adopted: it is a draft machine form of §13.1's table; adopting it is a SPEC
  document-version bump.
- Any change to what `warrant-verify` 0.9.0 does today.

## 5. Falsifiers

1. The v0.6.7 module fails any vector of the `ski@v1` registry manifest or the specimen → the
   selection is wrong; withdraw until a conforming module exists.
2. A supported environment in which the module file cannot be located and hashed before import
   (zipimport, frozen apps) → `load_sigma` needs a second witness (distribution `RECORD`) and the
   proposal says so.
3. A consumer imports `warrant.sigma_glyph` by path → migration note required.
4. The owner declines per-tag selection as over-engineering for a repository with no external
   consumers → the minimum that survives is one line: the module sha per tag in the provenance
   record, checked before import. Everything else in this document is optional above that line.

## 6. Stopping rule

rev 2 → one adversarial gate plus the owner's disposition. Findings against §3.1–§3.4 amended
once; a second AMEND on the same layer closes the proposal as *deferred* with §2 retained. **Applied
2026-09-02 after the rev 3 gate — see §8.**

## 7. Relation to other documents

- WRT-006 (closed, B): this supplies the per-tag evaluator that B presupposes.
- W1 (`trust/sigma-evaluator-provenance.json`, `tools/sigma_provenance_check.py`): its record
  becomes the `ski@v2` row's artifact provenance; its pin check becomes `load_sigma(tag)`.
- ADR-012 / internal-substrate brief (sigma-glyph): metric #2's intent met without a channel choice.
- `manifesto/drafts/KELVIN-LAYERS-0.1.md` (non-normative): frozen name, frozen bytes, moved
  implementation → new name; vocabulary only.

## 8. Closure record — the third gate's findings, left open

Recorded as received (Codex, 2026-09-02); none is repaired here, because repairing them is the
successor act, not another revision of this design.

| # | Finding | Why it is real | What the successor act must do |
|---|---|---|---|
| P0 | **Self-issued activation minted credit.** `activation.act` was checked only as a non-empty string and `warrant_release.commit` as any string; `act="self-issued:anything"`, `commit="not-a-git-commit"` gave all bindings BOUND and `credit_bearing: true`. | The one boundary this proposal claimed to close — "credit only on activation" — was a string test. | Activation is a **separate governance record** that externally binds manifest sha256, registry sha256, an exact release commit/ref (verified with `git cat-file`), and the signing authority; the checker only *reads* it. |
| P0 | **"The release ships this evaluator" was never checked.** `form: vendored-file`, `impl/sigma_glyph_v05.py` — no such file exists on the branch; an external `site-packages/sigma_glyph.py` with matching bytes passed. | Byte identity was proven; presence of those bytes in the named release tree was not. | For `vendored-file`: `git show <release_commit>:<module_path>` must equal the pin; for `distribution`: the wheel digest, separately. |
| P1 | **The release receipt depended on a moving Σ-GLYPH HEAD.** The WRT-006 differential loaded the HEAD suite by default; one added newline in a HEAD vector (same JSON) kept the semantic verdict PASS but changed `core_sha256`, so `receipt_bound: false`. | An immutable `ski@v1` release must not depend on a sibling's future surface. | Compute the release receipt only over the **registry's** suite revisions; keep HEAD as a non-crediting canary. |
| P1 | **`store_contract` was described, not executed.** `test_sha256` / `enforced_by` were schema-validated only; mutating `tests/sigma_cas_identity.py` changed nothing in the verdict. | The fetch-layer refusal is what compensates for a v0.5 evaluator executing foreign bytes; its closure must be part of the release binding. | Verify the enforcing code path and its test exist in the release tree at the pinned digests, and run the test. |
| P1 | **JSON was not strict.** `json.load` accepted duplicate keys last-value-wins, invisible to the closed schema. | The same bytes could have two protocol readings. | Reject duplicate keys (`object_pairs_hook`) and require canonical bytes for both records. |

What this closure changes in the artifact: `installed_engine_check.py` sets `credit_bearing: false`
unconditionally and says why in its receipt; the manifest's `activation` block is marked
`never-activatable-in-this-form`. Everything else stays as the record of what was measured.

Minimum successor act (not this document): one activation record type; `git show`-based presence
check per `form`; registry-suite-only receipt; store-contract closure executed; strict JSON. It is
smaller than this proposal and should be filed as its own WRT with its own gate.
