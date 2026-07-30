# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are the
**tooling** version (the `warrant-verify` package and the `warrant` /
`warrant-go` / `warrant-rs` CLIs).

**Read this first — four version numbers coexist deliberately** (SPEC §14.3):

| Number | What it versions | Current |
| --- | --- | --- |
| `warrant` body member | the record schema (SPEC §13.2) | `0.1`, `0.2` |
| SPEC document version | the document, including rules that add no body schema | v0.3 (DRAFT) |
| report tag | the machine boundary (SPEC §13.3) | `warrant.verify-report@v0` |
| release tag / PyPI | the tooling | 0.5.0 |

A release moving only the tooling number changes **no** protocol surface. Each
entry below says which of the four moved, and any entry that changes a
protocol-visible surface is marked **[protocol]**.

Everything before 2026-07-30 is **reconstructed from git history and the release
notes**, not written at the time. It is therefore a summary made after the fact:
tag dates and commit ranges are exact (they come from git), the groupings and
emphasis are a later reading. Where this file and `git log` disagree, git is
right.

## [Unreleased]

**Nothing here is adopted or released**; this section exists so the work is
legible before it is decided on. Entries are grouped by the branch that
produced them, because they were reviewed (or not) separately.

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
  `atp` 17, same check blob `b423b6a8…`), asserted in `build.py`, so no record
  in the shipped pack changed and the README's figures still hold. The pack now
  also carries the source blob, so the term can be traced to a readable rule.

### Added — branch `feat/spec-consolidation`

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

[Unreleased]: https://github.com/s0fractal/warrant/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/s0fractal/warrant/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/s0fractal/warrant/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/s0fractal/warrant/compare/v0.3...v0.3.0
[0.3]: https://github.com/s0fractal/warrant/compare/v0.2.0...v0.3
[0.2.0]: https://github.com/s0fractal/warrant/releases/tag/v0.2.0
