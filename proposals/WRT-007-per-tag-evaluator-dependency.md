# WRT-007: One published artifact per runtime tag — Warrant stops vendoring the Σ-GLYPH evaluator

**Status:** DRAFT rev 1 (2026-09-02) — design proposal plus one reproducer and one draft pin table.
No SPEC, `impl/`, `pyproject`, vector or registry change is made by this document; nothing is
adopted. Written by Claude Fable 5.1 at the owner's request ("prepare a counter-proposal about
warrant depending on sigma-glyph"), after WRT-006 closed with disposition B. A gate verdict is
evidence, not adoption (AGENTS.md rules 3–4).

**Thesis in one sentence:**

> A runtime tag is immutable (SPEC §13.1); therefore the evaluator that implements it should be an
> immutable, published, digest-pinned artifact that Warrant *depends on* — not a file Warrant
> copies and later replaces in place.

---

## 1. Why now

WRT-006 found that W1 replaced the bundled `impl/sigma_glyph.py` under the immutable `ski@v1` tag
and closed with B (`ski@v2` for Book I 0.6.0). That closes the *naming* question and leaves the
*supply* question open: today the tag's evaluator is whatever bytes sit in `impl/sigma_glyph.py`
at release time. Vendoring made the substitution possible and invisible. ADR-012's own success
metric #2 for the internal-substrate campaign is "neither consumer vendors or reimplements the
evaluator", and its kill criterion is "consumers still vendor evaluator logic or require a Sigma
checkout". manifesto met it (Phase 4A, PR #2). Warrant has not.

## 2. What was measured (2026-09-02)

The published PyPI artifact was downloaded (`pip download sigma-glyph==0.6.7 --no-deps`) and
opened in a scratch directory:

| Fact | Value |
|---|---|
| wheel | `sigma_glyph-0.6.7-py3-none-any.whl`, sha256 `c3b7bc32…` (full value in `wrt-007-model/runtime-pins.json`) |
| its `sigma_glyph.py` | sha256 `80299d68…` — **byte-identical to the `v0.6.7` git tag module**; docstring "oracle semantics v0.5.x" |
| vs Σ-GLYPH `v0.6.7` suite normative values | `ALL PASS (49/49)` |
| vs warrant `conformance examples` | `ALL PASS (67/67)` — under pre-W1 warrant (`9816937`, `SIGMA_GLYPH` override) and under W1 (`4915494`, `WARRANT_SIGMA_DIFFERENTIAL=1`) |
| WRT-006 differential, this module as E1 vs E0 (pre-W1 bundled) | `suite_shape MATCH`, `E1_conformance PASS`, `differential_agreement MATCH` (33/33), `ski_specimen MATCH`; boundary: executes foreign-key bytes exactly as E0 does |
| W1's module (`55072bc0…`) against the `ski@v1` pin | `NOT_THE_PINNED_EVALUATOR` (negative control of the pin check) |

Reproducers: `proposals/wrt-007-model/installed_engine_check.py` (pin + conformance),
`proposals/wrt-006-model/differential.py` (six axes). Draft pin table:
`proposals/wrt-007-model/runtime-pins.json`.

So an artifact already exists, published through sigma-glyph's own OIDC release path on
2026-07-31, that is a `ski@v1` evaluator by SPEC §3.1's definition, that Warrant did not write, and
that Warrant does not need to copy.

## 3. The proposal

### 3.1 Dependency, not copy

`pyproject.toml`: `dependencies = ["cryptography>=41", "sigma-glyph==0.6.7"]`; remove
`sigma_glyph` from `py-modules`; delete `impl/sigma_glyph.py`. `pip install warrant-verify` then
installs the evaluator as a dependency, so the README's offline promise ("`ski@v1` reasons re-run
offline … no separate clone") holds unchanged: offline *after install*, exactly as today.

### 3.2 Per-tag pin table, enforced at load

A tracked file (proposed home `trust/runtime-evaluator-pins.json`, shape in
`wrt-007-model/runtime-pins.json`) maps each registered runtime tag to **one** published artifact:
distribution, version, wheel sha256, module sha256, and the conformance evidence that qualified it.
`load_sigma()` resolves `sigma_glyph` from the installed environment, hashes the module file, and
compares it to the tag's pin. Mismatch → the module is **not** used and every reason under that tag
reports *unverified* with reason `evaluator-not-pinned` (§6 severity), never `pass`/`fail`. This
replaces W1's "is the override byte-identical to the bundled file" test with "is the installed
module the tag's pinned artifact" — the same fail-closed shape, with the copy removed.

### 3.3 `ski@v2` gets its own row, when registered

WRT-006's B: Book I 0.6.0 is `ski@v2`. Its row in the pin table points at a **future published**
sigma-glyph release whose module digest equals the registered pin; until such a release exists the
row carries `null` digests and `ski@v2` reasons are unverified by construction. The phase-4a
candidate wheel (`0.6.7+phase4a.5050ab7`) is deliberately unpublishable (PEP 440 local version,
rejected by PyPI) and therefore cannot be a pin target — which is the correct outcome: a tag pins a
published artifact or nothing.

### 3.4 Identity-by-Hash stays in Warrant

W1's fetch-layer refusal (`run_ski_check`, `tests/sigma_cas_identity.py`) is kept. A v0.5 evaluator
executes foreign-key bytes (measured); Warrant's store contract (§3.1 rule 2: the store IS the CAS)
is enforced *before* any bytes reach the evaluator. This is Warrant's rule about Warrant's store,
independent of which Book I edition the tag names — so WRT-006's boundary divergence never becomes
observable through Warrant under either tag.

### 3.5 The hard constraint, stated rather than hidden

Python installs **one** version of a distribution. Once `ski@v2` pins a `sigma-glyph` 0.7.x
release, one environment cannot hold both `sigma-glyph==0.6.7` (for `ski@v1`) and 0.7.x (for
`ski@v2`) under the same distribution name. Three ways out, in order of preference:

1. **A frozen distribution per frozen tag.** sigma-glyph publishes the v0.5-era Book I module
   under a distinct distribution name (e.g. `sigma-glyph-book1-v05`, importable as
   `sigma_glyph_v05`), byte-identical to the 0.6.7 module, and never releases it again. A frozen
   tag gets a frozen package. This is the cleanest expression of §13.1 and of Σ-GLYPH's own
   "hashes remain valid artifacts of their era". Cost: one publishing act by the sigma-glyph
   roster; a one-line import map in the pin table.
2. **One installed edition; the other tag reports unverified.** Warrant pins whichever edition
   the release targets; reasons under the other tag are reported *unverified* with a named reason.
   Honest, cheap, and it degrades old records' verifiability — B's own fallback.
3. **Extras.** `warrant-verify[ski-v1]` / `[ski-v2]` selecting the distribution. Only works if (1)
   exists; otherwise it is (2) with a nicer spelling.

The proposal recommends **(1)**, and until it exists, **(2)** with `ski@v1` installed — because
every existing record is `ski@v1`.

### 3.6 The knot, and what cutting it changes

Today the dependency picture is a copy in one direction and a CLI call in the other:

```text
warrant ──copies──▶ sigma-glyph impl/sigma_glyph.py       (runtime, hidden in a file)
sigma-glyph CI ──clones + runs──▶ warrant CLI              (governance tooling, WARRANT_PIN)
sigma-glyph Book III ──is a profile of──▶ Warrant v0.3     (normative text)
```

After WRT-007 the runtime edge is an explicit package dependency, digest-pinned, resolvable by
`pip` and auditable by `installed_engine_check.py`; the reverse edges are unchanged and named for
what they are — governance tooling and a normative profile relation — not runtime. At the
artifact level the graph is acyclic: `sigma-glyph` (the wheel) imports nothing from Warrant. The
bootstrap *practice* (each repo needs the other's tool to run its gates) remains, and remains
credit-free; what is removed is the one place where the cycle could silently change semantics.

## 4. What this proposal does not claim

- That `sigma-glyph==0.6.7` is *proven* equivalent to the pre-W1 bundled module on the admitted
  domain. It is measured equal on 33 + 1 inputs, both pass the normative suites, and both behave
  alike on the boundary. Equivalence on D is not claimed by WRT-006 and not by this.
- That a PyPI dependency is more available than a file. It is less: PyPI can be down, a version can
  be yanked. The pin table records the wheel digest so a mirrored or vendored *wheel* (not a loose
  file) can satisfy it; `--require-hashes` in CI is the enforcement.
- That sigma-glyph will publish anything. §3.5(1) is a request to its roster, not an assumption.
- Any change to what `warrant-verify` 0.9.0 does today.

## 5. Falsifiers

1. The published 0.6.7 module fails any warrant `ski@v1` vector or the specimen → the pin is wrong;
   the proposal is withdrawn until an artifact that passes exists.
2. `load_sigma()` cannot locate the installed module's file to hash it in some supported
   environment (zipimport, frozen apps) → the pin check needs a second witness (distribution
   `RECORD` hash) and the proposal says so.
3. The sigma-glyph roster declines §3.5(1) → the proposal falls back to §3.5(2) and says so at
   the top; it does not silently re-vendor.
4. A consumer exists that imports `warrant.sigma_glyph` by that path → migration note required.

## 6. Stopping rule

rev 1 → one adversarial gate plus the owner's disposition. Findings against §3.1–§3.4 are
amended once; a second AMEND on the same layer closes the proposal as *deferred* with the
measurements of §2 retained. §3.5 is a request to another repository's governance and is not
argued past the owner's answer.

## 7. Relation to other documents

- WRT-006 (closed, B): this proposal supplies the evaluator per tag that B presupposes.
- ADR-012 (sigma-glyph, DRAFT) and the internal-substrate brief: metric #2 and the vendoring kill
  criterion are what §3.1 meets for Warrant.
- W1 (`trust/sigma-evaluator-provenance.json`, `tools/sigma_provenance_check.py`): superseded in
  role by the pin table if adopted; kept as the provenance of the `ski@v2` candidate.
- `manifesto/drafts/KELVIN-LAYERS-0.1.md` (non-normative): "a frozen name gets a frozen package";
  vocabulary only.
