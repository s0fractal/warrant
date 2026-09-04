# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are the
**tooling** version (the `warrant-verify` package and the `warrant` /
`warrant-go` / `warrant-rs` CLIs).

**Read this first — four version numbers coexist deliberately** (SPEC §14.3):

| Number | What it versions | Current |
| --- | --- | --- |
| `warrant` body member | the record schema (SPEC §13.2) | `0.1`, `0.2` |
| SPEC document version | the document, including rules that add no body schema | v0.4 (DRAFT) |
| report tag | the machine boundary (SPEC §13.3) | `warrant.verify-report@v0` |
| release tag / PyPI | the tooling | declared by `version` in `pyproject.toml`; what actually shipped is the latest tag `v<version>` on GitHub Releases and the latest release on PyPI (`publish.yml` refuses a tag that disagrees) |

A release moving only the tooling number changes **no** protocol surface. Each
entry below says which of the four moved, and any entry that changes a
protocol-visible surface is marked **[protocol]**.

Everything before 2026-07-30 is **reconstructed from git history and the release
notes**, not written at the time. It is therefore a summary made after the fact:
tag dates and commit ranges are exact (they come from git), the groupings and
emphasis are a later reading. Where this file and `git log` disagree, git is
right.

## Unreleased

- The air-canada evidence pack is now a frozen, replayable specimen:
  `demos/air-canada/replay.json` pins the exact input bytes, the `ski@v1`
  evaluator digest, the run profile and the per-record `verify --json` /
  `check` vector; `replay-clean.sh` replays it through the public CLI installed
  from a wheel built at the same commit, in a fresh venv, from outside the
  checkout, with fail-closed controls (verdict `fail`, configured evaluator
  failure with no fallback, root and nested CAS identity). Base-grade WARN on
  an unexecutable reason is frozen as a named limitation, not changed.
  `tests/evidence_pack.py` holds the freeze to the tree offline. No protocol
  surface moved.
- Reduced the active surface without changing admitted protocol behavior:
  retired the never-completed autonomy actor, stopped shipping executable bytes
  for the unadmitted `ski@v2` candidate, and kept both histories as explicit
  controlled-forgetting records.
- `tools/check.py` no longer guesses a sibling checkout from its directory name
  or lets an ambient `SIGMA_GLYPH` turn production settlement into a differential.
  `SIBLING` is explicit for local X1; X1 otherwise performs its documented fresh
  clone and scopes its own non-crediting HEAD override.

- Removed the executable `ski@v2` candidate and its candidate-wheel provenance
  machinery from the shipped distribution. No admitted body version can name
  `ski@v2`; its tag remains reserved in SPEC §3.2/§13, while executable bytes
  return only with a future registration, vectors and body-version admission.
  `ski@v1` bytes, pin, offline replay and every current WarrantID are unchanged.

**NEED-002 base evidence — clean-room-from-code implementability demonstrated for one frozen corpus; settlement remains open.**

- An iterative local multi-model process produced a JavaScript candidate from
  the frozen public SPEC, conformance material, prior model outputs, runner
  output, and orchestrator-authored runtime probes without receiving Warrant
  implementation source.
  It reaches conformance pack 1.2.0's complete base grade: 135 PASS, 0 FAIL,
  0 UNRUN, 0 ERROR; all 60 base-grade negative vectors are answered and none
  accepted. The runner detects all four deliberate mutations.
- `needs/need-002-a3-base/` is a 97-operand closed evidence bundle containing
  the candidate, frozen operands, accepted generation streams, prompt-input
  provenance, and replay report. `needs/NEED-002-A3-BASE.json` pins the bundle,
  transport module, exact claim and exclusions, and its self-certified
  adjudication; `tools/verify_need002_a3.py` replays it, while mutation controls
  prove missing, extra, changed, locally rehashed, or semantically widened
  operands fail closed.
- The status is split rather than amplified: `NEED-002-BASE` is met at this
  operand; `NEED-002-SETTLEMENT` remains open because the four settlement-grade
  vectors are explicitly `NOT-CLAIMED`. This is not independent custody,
  external adoption, proof outside the corpus, a release, or governance
  adoption. Aggregate check count 52 → 54.

**Conformance pack 1.2.0 candidate — UTF-16 member ordering is now exercised, not only stated.**

- Added one schema-invalid-but-canonical §8.4 vector whose keys sort differently
  under locale collation, Unicode scalar-value order, and RFC 8785 UTF-16
  code-unit order. This exposed the same latent ASCII-key shortcut in the
  Python, Go and Rust reference canonicalizers; all three now implement UTF-16
  ordering over the full canonicalization-class input domain.
- The vector corpus grows from 138 to 139 (base 134 to 135); the 62
  MUST-REJECT vectors are unchanged. Published pack 1.1.0 remains immutable;
  the new corpus is versioned 1.2.0 and is not a release merely because these
  source bytes exist.
- The stricter Python renderer initially let a schema-invalid float escape as
  an unbounded `TypeError` during store verification. The existing three-seed
  Python/Go differential fuzzer caught it in CI; uncomputable IDs from either
  invalid characters or non-integer values now become the same bounded record
  error rather than a traceback.

**SPEC document change, no body-schema change: `ski@v2` reserved as a candidate, registered/admitted nowhere; one bundled evaluator per runtime tag.**

- SPEC §3.2 reserves candidate **`ski@v2`** = Σ-GLYPH Book I 0.6.0 (adopted bundle v0.7.0); §13.1 gains
  its row; §13.2 reserves body version `0.3` for it and leaves `0.3` unspecified, so every
  implementation (Python, Go, Rust) still rejects `ski@v2` as an unregistered runtime and no
  record, WarrantID or verdict changes. `ski@v1` remains Book I v0.5 (WRT-006, disposition B).
- The bundled evaluator is now **one module per tag**, pinned by digest and hashed *before*
  import (SPEC §3.1 "One evaluator per tag"): `impl/sigma_glyph_v05.py` (sha `80299d68…`, the
  `v0.6.7` tag module, byte-identical to the published PyPI `sigma-glyph==0.6.7`) serves
  `ski@v1`; `impl/sigma_glyph_v06.py` (sha `55072bc0…`, the W1 module) is the `ski@v2`
  evaluator, loadable by internal tooling but unreachable by any admitted record. `impl/sigma_glyph.py` is gone.
  Record: `trust/ski-runtime-evaluators.json`; enforcement: `SKI_EVALUATORS` in
  `impl/warrant.py`; a moved module is refused without executing a line of it
  (`tests/ski_runtime_evaluators.py`). **This closes the compatibility debt W1 exposed**: the
  v0.6.0 evaluator no longer runs under the immutable `ski@v1` name.
- `ski_policy` / `policy_lang` compile against the `ski@v1` engine by path and no longer
  `import sigma_glyph` from whatever is installed. `tools/sigma_provenance_check.py` reads the
  vendored path from the manifest and additionally binds the per-tag record to the code
  constant and to the `v0.6.7` source module. The `tests/sigma_cas_identity.py` in-module
  guard controls target the Book I 0.6.0 module; the adapter (`BlobCAS`) remains the guard for
  `ski@v1`, and the test now shows the v0.5 module alone would execute foreign bytes.

**Also unreleased — design-only research artifact (WRT-005):**

- `proposals/WRT-005-outcome-fingerprint-purity.md` — DRAFT, design only. The
  outcome-fingerprint rule for settlement §7 (identity = the eligible result
  value; a result is eligible iff it carries no DISSONANCE node anywhere), with
  its full adversarial history: an initial paper review that predicted the
  expect-flip, three design-gate rounds (annaglova, gpt56sol, Qwen) with
  responses and manifests, a fail-closed Python countervector proving the five
  re-opener families on the current spec and their collapse under the rule, and
  a Lean 4 mechanization of the rule's algebra and §7 admissibility (sound
  axiom cone; `sorry`/`axiom`/`native_decide` denylisted). **Carries no claim
  of adoption, implementation, or a refinement proof** — the Lean work proves
  the rule's algebra, not that any verifier computes it. Filed as WRT-005
  because WRT-003 (the number its historical artifacts still use) already
  belongs to a closed, unrelated proposal; see the proposal's identifier note.
  Two new checks in `tools/check.py` (the fail-closed countervector; the Lean
  guard) and a dedicated mandatory CI (`.github/workflows/wrt-005.yml`, pinned
  Σ-GLYPH + built Go + pinned Lean, no `--allow-unrun`); stated check count
  43 → 45.

## 0.9.0 — the published package disagreed with the published pack

**BREAKING for records with implausible timestamps; no real record is affected.**

SPEC §2's integer domain is now ±(2^53−1) rather than int64, in all three
implementations, the JSON schema and the specification. Identity is SHA-256 over
RFC 8785 bytes and RFC 8785 §3.2.2.3 serializes numbers through an IEEE-754
double, so above 2^53−1 the canonical bytes stop being a function of the value:
`ts = 9223372036854775807` canonicalizes to `9223372036854776000` in any
conforming JCS, and one logical record acquires two WarrantIDs. Reported by an
external Codex review. Wrapping was rejected — it maps two values onto one
WarrantID in a format whose identity *is* that hash, and breaks §6's
non-decreasing `ts` rule along `prior` edges.

Every JSON in this repository and its two siblings was scanned: no record, blob,
vector or fixture carried an integer outside the new range, so nothing migrates
and no WarrantID moves. The change was possible only while the user count is
zero.

**Why this release exists at all, rather than waiting.** Conformance pack 1.1.0
tests the new bound. `warrant-verify` 0.8.0 implements the old one. Measured
against the published wheel:

```
PERMISSIVE IMPLEMENTATION: 2 of 62 MUST-REJECT vectors were ACCEPTED.
  accepted: validate/reject-11-ts-=-2^53
  accepted: validate/reject-12-ts-=-int64-max
```

A stranger running `pip install warrant-verify` against the current pack would
have been told the reference implementation is permissive. The pack and the
package have to agree, and the package is the one that was behind.

Also in this release:

- `why` no longer rejects records `verify` accepts. SPEC §5 says a junk
  co-signature MUST NOT invalidate a record that still carries a valid signature
  by `body.actor.id`; `why` required every signature to verify, handing that
  power to anyone who could write a file in the store. Both now use
  `_well_signed`, so there is one definition of "signed" rather than two.
- §2's integer rule is enforced by an explicit walk over every integer rather
  than by `min_sigs > len(actors)` rejecting the same values coincidentally.
- Conformance pack **1.1.0**: 138 vectors, 62 MUST-REJECT, digest
  `ddd825a8…`. The corpus changed, so the version changed — 1.0.0 stays
  published unaltered, because two people holding one filename must not have
  two different files.

## [0.8.0] — 2026-07-31

> Recorded here as unreleased while it was; it was published to PyPI on 2026-07-31 and
> superseded by 0.9.0 on 2026-08-01. The section below is the text written before that,
> corrected only in this heading — a changelog that keeps saying "not published" about a
> published version is the same defect the release-surface gate exists to catch.

Tooling number only; **no protocol surface moves**. 0.7.0 and 0.7.1 are on PyPI
and are not written up below — this file is still narrated through 0.6.0, and
saying so is more useful than a reconstruction nobody checked.

### Added — branch `feat/ship-mcp-server`

- **`warrant-mcp-server`: the MCP server now ships in the wheel.** Until 0.7.1
  the server was `integrations/mcp-server/server.py`, which `pyproject.toml`
  could not ship — `package-dir = {"" = "impl"}` gives the flat namespace one
  root — so the only install path was a clone. The module is now
  `impl/warrant_mcp_server.py`, listed in `py-modules`, exposed as the console
  script `warrant-mcp-server`. `pip install warrant-verify` gives a working MCP
  server; `claude mcp add warrant -- warrant-mcp-server --store <abs>` registers
  it.
- **`README.md` carries `<!-- mcp-name: io.github.s0fractal/warrant -->`.** The
  MCP Registry proves PyPI ownership by finding that token in the README of the
  published release (`internal/validators/registries/pypi.go`), so it has to be
  in the artifact before a manifest naming the package can be published.
- `tools/doc_counts.py` now checks the distribution version against
  `impl/warrant_mcp_server.py`'s `__version__` and both version fields of
  `integrations/mcp-server/server.json`. A manifest whose version lags the
  release points the registry at a different artifact, or at a 404.

### Changed

- `integrations/mcp-server/server.json` gains a `packages` block naming
  `warrant-verify` 0.8.0, and bumps to `0.8.0`. It **cannot be published until
  0.8.0 is on PyPI**; the registry fetches the version-specific metadata URL and
  a 404 there is a hard failure. `runtimeHint: "uvx"` is deliberately absent:
  a client composes `uvx … <identifier>`, the identifier is the distribution
  name, and `uvx --from warrant-verify warrant-verify` is not a command that
  exists — measured against the built wheel, not assumed.
- `integrations/mcp-server/test_server.py` → `tests/mcp_server.py`, beside the
  other suites, and it takes `--server-cmd` / `--impl` so the same tests can be
  run against an **installed** copy rather than only the checkout.
- `LISTINGS.md` corrected. It said "nothing here has been submitted. This
  project is listed nowhere" after `io.github.s0fractal/warrant` had already
  been published to the official MCP Registry.

**Not gated.** No independent adversarial review ran on this branch; the suites
are green, which is necessary and not sufficient (AGENTS.md §3). Nothing here is
adopted, and nothing here is published.

## [0.6.0] — 2026-07-31

24 commits since 0.5.0. Tag `v0.6.0` (`0d147aa`), published the same day to
PyPI as `warrant-verify` 0.6.0 through the Trusted Publishing (OIDC) path in
`.github/workflows/publish.yml`.

**Released is not adopted.** Entries are grouped by the branch that produced
them, because they were reviewed (or not) separately, and nothing here has
passed an independent gate. `proposals/DEC-001-domain-separation.md` is still
marked OPEN: cutting a release ships the mechanism, it does not record the
threshold warrant that adoption requires.

### Changed — BREAKING, branch `feat/domain-separation`

- **[protocol] SPEC §5: the signed message is now domain-separated.**
  `msg = "warrant-sig-v1:" || WarrantID_raw` (47 bytes), still pure RFC 8032
  Ed25519 over a byte string — not Ed25519ctx, which is the orthodox answer and
  is not uniformly reachable from Python's `cryptography`, Go's `crypto/ed25519`
  or a from-scratch verifier, so it is the choice more likely to split
  implementations. The pre-0.6.0 bare-WarrantID message **MUST NOT verify**, and
  no verifier accepts both at any time under any flag: accepting the old one is
  the same as having no separation. This implements option A of
  `proposals/DEC-001-domain-separation.md`. **Adoption of DEC-001 is a maintainer
  act; shipping it in 0.6.0 is a release, not an adoption, and no threshold
  warrant records one.**

  Which of the four numbers moved: **SPEC document version v0.3 → v0.4**;
  **release tag 0.5.0 → 0.6.0**. Body versions `0.1`/`0.2` are unchanged and no
  WarrantID moves — a migrated record has the same identity it had before,
  because the WarrantID is SHA-256 of the canonical body and the envelope is not
  hashed. The report tag stays `warrant.verify-report@v0`: the report's shape did
  not change, only a finding's text.

  There is no version field that tells the two apart. The discriminator is the
  signature: exactly one of the two messages verifies, never both. So a verifier
  that meets an old record reports §5's exact diagnosis — naming the
  construction and the repair — instead of the bare "signature does not verify"
  that a flipped byte also produces.

- **[protocol] SPEC §8.5 + `examples/signature-vectors.json`:** a new MUST-PASS
  battery pinning the 47 signed bytes, four signatures that MUST verify and ten
  that MUST NOT — including the pre-v1 construction, the two concatenation
  mistakes, a missing colon, and a signature over the bare SHA-256 digest of
  unrelated content, which a pre-0.6.0 verifier accepted as a Warrant signature.
  All three implementations read it from `conformance`.

- `warrant resign --key <keyfile>` migrates a store in place. It rewrites only
  `sigs[].sig`, and only for an entry whose `key` is the supplied key's public
  key AND whose existing signature verifies over the bare WarrantID — proof the
  holder of that key really signed that WarrantID, so no attribution is created.
  Anything it cannot re-sign is named and the command exits non-zero.

- `tools/domain_separation_prototype.py` and `examples/draft/` are replaced by
  `tools/signature_vectors.py` and `examples/signature-vectors.json`: the
  prototype cross-verified two candidate rules because neither was in force.

### Added — branch `feat/policy-frontend` (tooling and docs only; no protocol surface)

- **WPL v1 and `impl/policy_lang.py`** — a policy source language that compiles
  to `ski@v1` terms, so authoring a re-runnable reason no longer means
  hand-building combinator terms. `fact` declarations plus one boolean
  expression over `==` `!=` `<` `<=` `>` `>=` `in` `&&` `||` `!`, on `bool`,
  `int` and `string`; comparisons lower to bit-vector folds at the minimum width
  that separates the operands. Every compile reports the exact ATP a verifier
  will spend and the blobs it adds, and REFUSES at authoring time anything over
  the budget rather than emitting a check that exhausts ATP in someone else's
  verifier. `docs/policy-language-choice.md` records why this and not a CEL
  subset; `docs/authoring-checks.md` is the tutorial.
- **`tests/policy_lang.py`**, wired into `tools/check.py`: 120 checks, including
  a differential over generated programs whose expected answer comes from
  Python's own operators (never from the compiler) and whose actual answer is
  read out of a real re-execution through `warrant.run_ski_check`; mutation
  controls that fail if an injected mis-compilation survives; and a gate that
  executes every command in the tutorial and compares its printed output.
- **`demos/air-canada/policy.wpl`** — the demo's check, rewritten in WPL. It
  compiles to a byte-identical `ski@v1` doc (same term, same `expect`, same
  `atp` 17, same check blob `b423b6a8…`), asserted in `build.py`, so this branch
  changed no record in the shipped pack and the README's figures still hold. The
  pack now also carries the source blob, so the term can be traced to a readable
  rule. (The two pack records did change on `master` afterwards, under the
  domain-separation entry above: `sigs[].sig` was rewritten, nothing else. Both
  WarrantIDs, both bodies, the manifest's `records`/`root`/`ski_checks` and every
  figure in `demos/air-canada/README.md` are unchanged.)

### Fixed — branch `fix/wpl-headroom-validation` (tooling only; no protocol surface)

- **The WPL compiler emitted `ski@v1` checks its own verifier rejects.**
  `--headroom` took any integer and the compiler wrote `atp + headroom`
  unvalidated, while `warrant.validate_ski_blob` requires `0 <= atp < 2**32`.
  Reported by Codex (external cross-family audit, 2026-07-31) with two
  reproductions, both re-run here before the fix: `--headroom=-1` pinned
  `atp=494` against a 495 ATP spend and the verifier answered **`fail`** — a
  wrong verdict from a correct term, not an error — and
  `--headroom=5000000000` pinned `atp=5000000495`, which the verifier rejected
  as not a uint32.

  Negative and non-integer headroom are now refused by name. The substantive
  change is that `compile_source` serializes the check document, decodes it
  back, puts it through `warrant.validate_ski_blob` (the verifier's own
  predicate, imported rather than restated) and **re-executes `term` under the
  pinned `atp`**, comparing against `expect` — then stores exactly those bytes.
  The compiler's three existing guarantees all concerned the term; the blob's
  own `atp` field was covered by none of them. `impl/ski_policy.py` had the
  identical `atp + headroom` line and now shares the gate.

  Section L of `tests/policy_lang.py` covers this: the two reproductions, both
  ceilings at their exact boundary, a compiler-vs-verifier agreement check that
  runs both rather than restating either, and three mutants that corrupt the
  document at the moment of serialization — which only a gate reading the
  serialized bytes can catch. 12 of its 17 assertions fail against the
  pre-fix compiler.

  Not fixed here, and not defects: `--max-atp` is a compile-time ceiling that
  reaches no artifact, and `warrant file --ts` was already validated against
  the verifier's own `validate_body` before writing — which is the pattern this
  fix brings to the compiler.

### Added — at the merge of `feat/policy-frontend` into `master`

- **THREAT-MODEL.md `SA-11`** — the WPL front end narrows, but does not close,
  the gap between a policy source and the term a verifier re-runs: the compiler
  and its reference interpreter share a parser, so a shared misreading agrees
  with itself and the differential stays green. The mitigation is the `formula`
  line the compiler prints, read by a human. The branch stated this limit in
  `llms.txt`'s residual list; `master` had meanwhile moved that list into
  `THREAT-MODEL.md`, which promises that a limit stated anywhere else is stated
  there too. Keeping both truths meant moving the item rather than duplicating
  it. `SA-11` is the branch's own wording, not a new or softened claim.
- **`tools/doc_counts.py`**, wired into `tools/check.py`: every count a document
  states about this repository must equal the thing it counts — the number of
  entries in `CHECKS`, the number of `SA-n` headings, the number of `NG-n`
  items — and a claim whose wording stops matching is reported MISSING rather
  than passing silently. It exists because both merged branches were already
  wrong: each moved `CHECKS` without moving the sentence in `llms.txt` and
  `SECURITY.md` that counts it, so each was off by one alone and the merge was
  off by two, under green suites. Corrected to 33.
- `tools/check.py`: 33 checks (was 31 on `master`, 31 on the branch, both
  stating 30).

- **[protocol]** SPEC §11: `warrant.verify-report@v0` specified in the spec.
  The contract a CI system branches on previously existed only in `README.md`
  and in two implementations' source comments, both of which called it
  "non-normative". Closed schema, counts binding findings, `ok == (errors == 0)`,
  the reserved `store` / `settlement` subjects, one physical line, exit-status
  parity, and the extension rule (a new field means a new tag, never a field
  inside `@v0`).
- **[protocol]** SPEC §12: the `trust-config.json` format, which §5.1 declined to
  mandate while both reference implementations read the identical shape. Closed
  member set, I-JSON parsing, and the fail-closed rule for a requested
  settlement verification whose trust cannot be constructed.
- **[protocol]** SPEC §13: registries for reason-runtime tags, body format
  versions, report tags and reserved report subjects — with the honest note that
  **there is no registry operator**, so a registration is a pull request against
  this repository. `x-` is reserved for experimental/private tags.
- **[protocol]** SPEC §14.1: an `application/warrant+json` IANA registration
  template, **drafted and NOT filed**. No expert review has been requested; the
  media type is unregistered and must be treated as such.
- SPEC §14.2 and `schemas/`: published JSON Schema (draft 2020-12) for the body,
  the envelope, the verify report, the trust config and the evidence-pack
  manifest, plus `tools/schema_check.py`, which checks them against the corpus in
  both directions (every positive artifact validates, every §8.3 negative body is
  rejected) and prints the rejection classes no schema can express.
- `THREAT-MODEL.md`: one attacker-capability matrix (14 rows), consolidating what
  was scattered across `SECURITY.md`, `llms.txt`, SPEC rationale and
  `policies/gate-settlement.json`, with the disclosed structural weaknesses stated
  in full: `cmd@v1` novelty satisfiable "by writing a different word", key↔actor
  binding as a flat local keyring with unbound as WARN, co-located roster keys,
  a non-independent reviewer quorum, hand-rolled crypto in a trust path, and
  settlement's one-and-a-half implementations.
- `proposals/DEC-001-domain-separation.md`: the signature-domain-separation
  decision — both options fully worked out, with a DRAFT prototype
  (`tools/domain_separation_prototype.py`) and side-by-side old/new signature
  vectors under `examples/draft/`. **A recommendation, not a decision**; SPEC §5
  is unchanged and no shipped code path was touched. Recommends adopting a
  separator now, because the cost is at its global minimum while the user base is
  zero and rises monotonically after.
- SPEC §14.3: how to cite a version of this document — by commit SHA or by the
  SHA-256 of the exact bytes, never by branch.
- **[protocol]** SPEC §8.4 and `examples/canon-vectors.json`: the JCS escaping
  battery as machine-readable vectors (47 cases, each pinning input body,
  canonical bytes and WarrantID). SPEC §4 previously made `tests/differential.py`
  normative by reference, which required a third-party implementer to read
  Python. Two cases are new: `<` `>` `&` raw emission and U+2028/U+2029 raw
  emission — both named normatively in §4 and exercised by no vector until now.
  All three implementations already agreed on both.

### Changed

- **[protocol]** SPEC §2: `actor.id` is stated to be a **nonempty** string. The
  table said `<string>`; all three implementations already rejected `""`. A spec
  gap, recorded as one.
- `tools/check.py`: 29 checks (was 27).

### Fixed

- **[protocol]** `verify --settlement --trust-config` reported `1 warnings` in
  text mode and `"warnings":0, "findings":[]` in `--json` for the same store when
  a signature was **unbound** — a key claiming an actor the operator's own
  keyring does not vouch for. Python's `quiet` branch, meant to suppress the
  `INFO signature bound` line, swallowed the `WARN signature unbound` with it, so
  the finding an integrator most needs was invisible to exactly the consumer told
  to consume the JSON. Go emitted it in both renderers, so Python and Go
  disagreed on a verification outcome — P0 by `SECURITY.md`'s ladder. Found by
  the first external consumer (the sibling `oaip` ledger documented the behaviour
  and built its own enforcement around it). Regression vector added with the
  negative control run.

### Known defects recorded, not fixed

- SPEC §11.3: without `--store-mode`, the Go CLI's legacy flat-directory mode
  emits `ok:true` on an uninitialized directory where Python emits the
  fail-closed `ok:false` — the same report tag carrying opposite verdicts about
  the same path in two conformant implementations. Disclosed in `README.md`
  before this branch; now named as a defect against the §5 design rule instead of
  as a mode. Repairing it changes a released surface, so it is recorded.

## [0.5.0] — 2026-07-30

133 commits since 0.4.0. Body schema unchanged (`0.1`/`0.2`); SPEC document
still v0.3 DRAFT; report tag `@v0` introduced.

### Added

- **[protocol]** `warrant.verify-report@v0` — `verify --store-mode --json` emits
  exactly one closed-schema report object. The machine boundary the GitHub Action
  consumes.
- `--store-mode`: a path that is not an initialized store fails closed instead of
  being read as an empty successful verification.
- GitHub Action (`action.yml`): installs the verifier, verifies a store or pack,
  fails the job on any error, exposes `ok` / `records` / `errors` / `warnings` /
  the full report. Does a **capability** check, not a version check.
- Release evidence packs (`air-canada-pack.zip`, `cross-vendor-pack.zip`,
  `SHA256SUMS`) built by `tools/build_release_packs.sh`, which refuses to ship
  anything key-shaped and verifies each zip the way a stranger will. Releases
  v0.2.0–v0.4.0 carried **zero** assets, so the README's `curl` line 404'd.
- `impl-rs` verifies stores (SPEC §6 **base grade only**: no settlement, no key
  state, no `ski@v1` oracle), so three implementations agree on what verifies and
  on what does not — checked against nine deliberately broken stores.
- in-toto Statement v1 bridge (`tools/intoto.py`) with a ten-case tamper matrix.
  The Statement is **not** signed here; DSSE and Rekor are separate steps.
- `tools/settle.py` + `policies/gate-settlement.json`: a gated item is settled
  unless a reproduction executes.
- `tools/check.py`: one command running every claim, reporting UNRUN separately
  from pass.
- `tools/check_release_surface.py`: extracts documented CLI invocations and
  validates them against the built wheel; the publish workflow fails if the
  artifact cannot do what the docs promise.
- `SECURITY.md`, `CITATION.cff`, `AGENTS.md`, `MAINTAINER-LEASE.md`,
  `MODEL-ACTORS.md`, `llms.txt`, `MAP.md`, EU AI Act Article 12 profile (DRAFT).

### Fixed

- **[protocol]** A blob could be swapped at its own content address and both
  verifiers reported ok; the fix covers all five content kinds.
- **[protocol]** Lone surrogates are rejected in both implementations — one
  I-JSON domain, so the same bytes cannot parse to different strings.
- **[protocol]** A losing quorum could adopt a root (WRT-002 finding), closed with
  the negative control run.
- **[protocol]** The settlement outcome fingerprint used the claimed verdict
  rather than the re-run one for `ski@v1`.
- **[protocol]** BOM rejection named in the canonicalization rules rather than
  left incidental.
- `why` printed honest output and exited 0 regardless; the exit status now
  matches what it printed.
- Policy / `ski` / JSON-blob paths no longer crash on hostile input (verifier
  totality, from an external audit).
- A supplied keyring was reported as absent.
- `action.yml`: the `version` input was spliced into a shell command; injection
  closed.

### Known at release

PyPI served 0.4.0 while the README documented 0.5.0-only flags — the gap that
made `check_release_surface.py` a gate rather than a note.

## [0.4.0] — 2026-07-17

Four commits after 0.3.0. No protocol change.

- `warrant-anchor`: RFC 6962 Merkle batching, so a batch of WarrantIDs is
  anchored by one root with short inclusion proofs.
- `impl/ski_policy.py`: re-executable boolean policy predicates, addressing the
  "nobody can author a `ski@v1` check" gap (it remains a gap: SKI combinators are
  not an authoring surface a normal engineer will use).
- Dropped a committed Go build cache.

## [0.3.0] — 2026-07-17

Packaging release. Body schema unchanged.

- `warrant-verify` on PyPI: an installable offline verifier, with the Σ-GLYPH
  Book I check engine bundled so `ski@v1` re-runs without a second clone.
- Evidence Pack format v0 (`EVIDENCE-PACK.md`) and the Air Canada demo pack.
- `warrant-mcp` sealing proxy: an MCP stdio session sealed into a verifiable pack.
- Verifier hardening from two external audits (a P0 `ts` clamp/narrowing split
  between Python and Go, plus P1s in both implementations).

## [0.3] — 2026-07-07 (spec)

**[protocol]** SPEC v0.3 DRAFT — the document-level release, adopted from GOV-001
rev 4 after a three-family adversarial gate (Codex, Gemini 3.1 Pro, DeepSeek v4
Pro). **Adds no body schema**: every `0.1`/`0.2` record stays valid.

- §7 settlement: tunnels, foreclosure, the re-litigation novelty test, outcome
  fingerprints.
- §9 multi-root stores: root eligibility, scoped adoption, advisory `genesis.json`.
- §5.1 key state: binding, rotation and revocation as warrants, threshold policy
  grammar.
- Settlement-grade verification in both Python and Go; `tests/negative.py`
  negative-path differential harness.
- Canonicalization divergences between Python and Go closed (F1–F4 from an
  external v0.2 review).

## [0.2.0] — 2026-07-05

**[protocol]** Body version `0.2`: the `ski@v1` reason runtime — a portable,
deterministic, budget-bounded check evaluated per Σ-GLYPH Book I v0.5, where the
verdict is a hash comparison and work *and* peak memory are bounded by the ATP
budget. Reasons a stranger can re-run without trusting the filer.

- Independent Go implementation (`impl-go/`), verifier-only, byte-exact with
  Python on every vector.
- `ski@v1` is reserved and MUST be rejected in `0.1` bodies.

## [0.1] — 2026-07-05

**[protocol]** Initial format: signed, content-addressed decision records; the
body schema (§2), reasons (§3), JCS canonicalization and WarrantID (§4), the
envelope and Ed25519 signatures (§5), verification (§6). Python reference
implementation, five verbs, plain-file store, conformance vectors.

[Unreleased]: https://github.com/s0fractal/warrant/compare/v0.9.0...HEAD
[0.8.0]: https://github.com/s0fractal/warrant/compare/v0.7.1...v0.8.0
[0.6.0]: https://github.com/s0fractal/warrant/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/s0fractal/warrant/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/s0fractal/warrant/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/s0fractal/warrant/compare/v0.3...v0.3.0
[0.3]: https://github.com/s0fractal/warrant/compare/v0.2.0...v0.3
[0.2.0]: https://github.com/s0fractal/warrant/releases/tag/v0.2.0
