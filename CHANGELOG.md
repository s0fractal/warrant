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

- **The shared primitives are held to [s0fractal/primitives](https://github.com/s0fractal/primitives).**
  That repository states the behaviour of SHA-256, RFC 8785, the signature
  message, Ed25519 and P-256 as vectors, not as shared code, so the three
  implementations stay independent. A copy pinned by commit and manifest
  digest lives in `third_party/primitives/`, and `tools/vendor_primitives.py
  --check` verifies it. `tests/primitives_pack.py` runs it against Python, Go
  and Rust. The probes gain one class, `p256-decode`, which asks the P-256 key
  decoder directly. Measured: with impl-rs's `x < p` or on-curve check
  removed, `verify-sig` still passed 50/50, while `p256-decode` reported the
  decoder accepting what it must refuse.
- **The policy-binding gap is now executable, and the README says so.** A
  record filed under a `DENY_ALL` policy blob, with a real `ski@v1` reason the
  verifier re-executes (it computes something unrelated to the policy) and an
  `accept` signed by a bound key, verifies with 0 errors in Python, Go and Rust
  at settlement grade with `--require-bound`. Every guarantee the construction
  offers holds; the claim that the decision was allowed by its policy is false.
  The countermodel and the three missing links (policy → computation, evidence
  → facts, result → decision) were named in a review conversation (manifesto
  `quotes/Monday/chat-0001`). THREAT-MODEL A6 said the same in prose.
  `tests/countermodel_policy_binding.py` pins it; it is meant to fail, and to
  become the witness of the binding rule, once one lands (WRT-010).

## 0.12.0 — keys that live in phone hardware can sign

Tooling version 0.12.0 (PyPI `warrant-verify`, npm/JSR `@s0fractal/warrant`, crate `warrant-verify`). SPEC document version unchanged. Conformance pack 1.5.0. The protocol-visible change is WRT-019 below (ECDSA P-256 signature entries, opt-in per entry; no body, report schema or WarrantID change). Also: `keygen` no longer overwrites a file or follows a symlink.

- **keygen never overwrites a key file (Python, Rust).** Sonar flagged the new
  key-file paths (S8707: CLI-supplied paths). Checking showed a real write
  primitive: `keygen --out` silently overwrote any existing file and followed a
  symlink, creating the file at its target. It also set 0600 only after
  writing. `keygen` now creates a new file, 0600 from the first byte, and
  never follows a symlink; an existing path is refused. `load_key` reads only
  a regular file of at most 4 KiB, so `/dev/zero` is refused instead of read
  forever. The Rust shadow harness gives Rust its own `--out` path in the same
  prior state. `tests/keygen_never_overwrites.py` checks Python and Rust.

- **[protocol] WRT-019 decided: ECDSA P-256 signatures, for keys held in phone
  hardware.** Phone secure elements (Secure Enclave, StrongBox) sign P-256
  only. A signature entry may now carry `alg: "ecdsa-p256-sha256"`; an absent
  `alg` still means Ed25519.
  - **One encoding per key and per signature.** The key is a compressed SEC1
    point on the curve with x < p. The signature is 64-byte `r ‖ s`, low-S.
    It covers the same 47-byte message.
  - **The algorithm is never inferred from a key's length**, and an unknown
    `alg` does not verify.
  - **Key slots:** the trust config `actors`, key-state blobs and `next`
    commitments accept compressed P-256 keys.
  - **Implementations:** Python (`cryptography`, which also signs: `keygen
    --alg p256`, RFC 6979, low-S normalized), Go (standard library) and Rust
    (written from scratch, verification only). All three agree on 280 random
    and mutated requests (`tests/p256_differential.py`) and end to end
    (`tests/wrt019_p256.py`).
  - **Conformance pack 1.4.0 → 1.5.0:** 17 `verify-sig` vectors with input
    `alg`; 166 vectors, 83 MUST-REJECT. Each negative is shown to be accepted
    by lenient ECDSA or to be malformed for a named reason
    (`tools/p256_vectors.py --selftest`).
  - **Found along the way:** the reject vectors could not catch a missing
    on-curve, x < p or prefix check in Rust's decoder, because they carry a
    real signature under another key. A direct decoding unit test now kills
    all three mutants. Contract SIG-P1.

## 0.11.0 — the reader can require the actor's own binding

Tooling version 0.11.0 (PyPI `warrant-verify`, npm/JSR `@s0fractal/warrant`, crate `warrant-verify`). SPEC document version unchanged; conformance pack 1.4.0. The protocol-visible change is WRT-018 below (an opt-in verifier option; no body, report schema or WarrantID change).

- **JS/WASM: `verifyStore(files, { trust, requireBound: true })`** exposes WRT-018. It throws without `trust`, as the CLI refuses `--require-bound` without `--settlement`. The core gains `verify_report_with_trust_opts`.

- **[protocol] WRT-018 decided (A): a reader may require the actor's own
  binding.** At settlement grade, bound/unbound is a report (§5.1). An actor
  signing with a key the reader's trust config does not bind therefore
  verified `ok: true` with one WARN. Two consumers rebuilt the rule outside
  warrant: oaip by parsing `signature unbound` lines, and warrant-pdf by
  refusing every finding. The latter refused a contract over an appended
  junk co-signature, which §5 says is excluded, never fatal. A new
  settlement-only option `verify --require-bound` (Python, Go, Rust)
  reports `ERR: no bound signature by body.actor.id` when a record's own
  actor has no bound signature. Co-signatures keep §5. The option without a
  trust config is exactly one `ERR` on `settlement`, and without
  `--settlement` the CLI refuses. No body, report schema or WarrantID changes.
  Conformance pack 1.3.0 → 1.4.0 adds five settlement vectors, with input
  `require_bound`. The two negative ones fail an implementation that ignores
  the option (measured on origin/master Python), and three mutants of the
  rule are each caught by their own vector. Contract KEY-B1;
  `tests/wrt018_required_binding.py` (PY = GO = RS). The JS/WASM package
  does not expose the option until its next release. THREAT-MODEL A4 now
  places the "gates on `ok` alone" residual at settlement grade too.

- **Paper "The Reason Runs Again" 1.1.0 published**: DOI
  10.5281/zenodo.23414323, tag `paper-the-reason-runs-again-v1.1.0` =
  `e494dbb`. The PDF was rebuilt byte-identically from two clean exports of
  the tag, and every published file was checked after publication against
  the manifest (`deposited/v1.1.0/`). `tools/check.py` now binds the tree's
  paper to that commit, as it did for 1.0.0.

- **Paper 1.1.0 candidate states the key-state decisions.** §5.3, §8 and §10
  now describe WRT-014, WRT-016 and WRT-017 as decided and implemented, with
  the "no quorum" gap found and closed along the way, rather than as open
  proposals. The triage of the second review records the decisions.

- **WRT-014 decided (A): an adoption satisfies the adopting jurisdiction's
  threshold.** SPEC §9 always asked for "the adopting root's current
  settlement policy, including any threshold rule". All three
  implementations checked only the policies the adoption cites, which its
  filer chooses. Under a 2-of-2 jurisdiction, one actor citing an opaque
  policy therefore adopted another root on one signature (recorded at
  3a0e3ae). An adoption must now also satisfy every threshold policy of each
  settlement-active root it descends from. Python, Go and Rust were changed
  together. `tests/wrt014_adoption.py` checks this with a positive control
  (both signers adopt), and mutating the rule out turns it red. Contract
  ADOPT-T1 records the decision and its counterexample. THREAT-MODEL SA-7
  is updated.

- **WRT-016 decided (C): a key-state conflict is scoped to the ancestry that
  contains it.** Before, a conflict anywhere unbound every signature of the
  actor across the whole store. Two retired keys could thereby deny an
  actor's entire history, the uncompromised current key included. Now an
  actor is conflicted at a record only when that record's ancestors hold two
  unordered authorized rotations for it, and every conflict is also reported
  once on the store (subject `store`). Implementing this found that SPEC's
  "a conflicted actor counts toward no quorum" had been enforced by none of
  the three implementations: a 2-of-2 adoption still succeeded with one
  signer conflicted. It is now enforced at the positions where the conflict
  is visible. Python, Go and Rust were changed together.
  `case_multihop_residual` was flipped to the new rule, and
  `case_conflict_counts_toward_no_quorum` was added; mutating either rule
  out turns them red. Contract KEY-C1 was amended with a new decision.

- **WRT-017 decided (A): there is no revocation operation.** SPEC §5.1 had
  specified revocation as a `supersede` of the introducing rotation, and no
  implementation ever derived key state from it. It is dropped rather than
  half-kept. A key leaves use only by rotation to its committed successor, a
  `supersede` of a rotation MUST NOT change key state, and an actor whose
  successor is lost is terminal unless a threshold policy rescues it. No
  implementation changes: the specification now says what all three do. New
  contract KEY-R1 records the decision and its counterexample.
  `case_no_revocation` (formerly `case_revocation_not_implemented`) now holds
  the rule instead of a known gap.

- **Paper "The Reason Runs Again" 1.1.0 candidate** (not deposited). It
  answers the 2026-10-16 DeepReview point by point (see the triage in
  `papers/the-reason-runs-again/reviews/`):
  - the full Ed25519 acceptance rule and the edge vectors;
  - pre-rotation and WRT-014;
  - resource fences, fingerprint tuples, DISSONANCE, and the zero-cost
    branch (a);
  - the report schema;
  - a per-class pack table bound by `check_claims.py`;
  - verified prior art: Cedar, Biscuit, OPA Wasm, KERI and ZIP-215;
  - every count restated at the current tree, with the archived review corpus
    explained;
  - a new §10 on what changed since 1.0.0.

  Rust is described at settlement parity, and the "20 mixed-torsion keys" claim
  is corrected. `check_claims.py --deposited d83984f` keeps 1.0.0 true at its
  own commit while the candidate is measured against the working tree.
- **Contracts for SPEC rules (method from sokol-core).** `contracts/<ID>.json`
  names one SPEC MUST sentence verbatim, the witnesses that hold it (test
  functions run by `tools/check.py`, or marked vectors), and the decisions
  behind it. Each decision has its `because`, and a decision made on a
  counterexample records the commit, the witness, what was observed and what
  was expected. The red is recorded as evidence; CI is not made to fail to
  show it (AGENTS.md rule 6). `tools/contract.py check` refuses:
  - a SPEC edit under a contract, or a statement change without a decision;
  - a rewritten or dropped decision against the base (CI fetches the base);
  - a witness that is gone or that no check runs;
  - a hand-edited `CONTRACTS.md`, which is generated.

  The first three contracts are SIG-E1 (§5 cofactorless equation), KEY-P1
  (§5.1 pre-rotation) and KEY-C1 (§5.1 conflict and its residual).
  `tests/contracts.py` gives each predicate a control: 11 broken copies, each
  refused, and two predicates mutated out turn their controls red. Not yet: an
  owner signature over contracts and witness bodies (sokol-core's
  witness-pin). Until then, append-only rests on git.

- **WRT-015 pre-rotation (SPEC §5.1, §12): a retired key can no longer rotate.**
  DeepReview R13, reproduced first: rotation authorization was judged at the
  record's DAG position while key-state conflict is store-wide. One leaked
  retired key could therefore sign an authorized rotation where it was still
  current, make the actor conflicted everywhere, and retroactively unbind
  every signature the actor ever made. Now every key state commits in advance
  to its successor's SHA-256: `next` in the key blob, and `next` in the trust
  config for genesis keys. A rotation must introduce exactly that key, and a
  key state without a commitment is terminal. This was implemented red-first:
  the countervector `tests/r13_retired_key_denial.py` (PY/GO/RS, report for
  report) landed failing and passes now. Residual: a key together with its
  committed successor can still fork, which is a conflict; ordering that
  duplicity needs WRT-012. `tests/settlement.py` and the `rs_parity` fuzz now
  build committed rotations, and the fuzz deliberately files duplicates so
  conflict handling stays covered. `trust add --next` is a follow-up. Also
  R14: SPEC §3.1 now treats resource fences as local policy, like the ATP
  budget, and a fence trip MUST report `unverified`.

- **Conformance pack 1.3.0: Ed25519 EDGE vectors; the cofactorless equation
  is now a MUST.** DeepReview (2026-10-16, R1/R2) observed that SPEC §5 only
  said "SHOULD prefer" a cofactorless verifier, and checking it showed the
  pack had no signature on which verifiers actually split. A cofactored
  verifier passed all 139 vectors. Five §8.5 vectors now pin the equation:
  `S + L`, a small-order `R` and its non-canonical alias, and a mixed-torsion
  key with one signature that MUST NOT verify (`[k]T8 ≠ O`) and one that MUST
  (`[k]T8 = O`). `tools/ed25519_edge.py` builds them and its selftest proves
  each one separates the two rules. Python, Go and Rust pass all of them
  unchanged (72/72 each). Pack: 144 vectors, 66 MUST-REJECT, new digest in
  SPEC §8.6. Also corrected: `tests/ed25519_differential.py`'s "mixed-torsion"
  loop signed for the *other* key, so it never reached the divergent case. Its
  comment now says so.

- **Plugin 0.2.0: auto mode is witnessed, and refusals are remembered.**
  Unprompted Bash calls that are checks (tests, builds, `gh pr checks`) or
  consequential (push, commit, merge, tag, publish, `rm -rf`) are filed as
  "executed, no prompt" with the permission mode, success or failure and a
  SHA-256 of the tool response. The output is not stored. A `SessionStart`
  hook gives the model up to five recent auto-mode denials, labelled as data,
  so a refused call is not retried blind. `/warrant:decisions` renders the
  report when the skill loads instead of through a prompted tool call. Tests
  cover a 20-case classifier table, the hash, that the output is absent from
  the store, and recall output both with and without denials. Four new
  mutations each turn them red.

- **Plugin 0.1.1: a fresh install no longer reads as a damaged store.** Before
  anything was witnessed, `/warrant:decisions` reported `1 errors` (the verifier
  on a store that does not exist yet). It now says "nothing to verify". A
  missing CLI is still reported first, and a store directory without `records/`
  still goes to the verifier. Found on the first live run.

- **Claude Code plugin: a decision witness** (`integrations/claude-code-plugin/`,
  marketplace `.claude-plugin/marketplace.json`). Hooks on `PermissionDenied`,
  `PermissionRequest` and `PostToolUse(Failure)` file a signed `reject` for each
  auto-mode denial (the harness's reason verbatim) and an `accept` for each call
  that was asked about and then ran. Manual dialog denials fire no hook, so
  they show as open asks rather than as a guess. The hook prints nothing and
  always exits 0. `/warrant:decisions` lists the records with the store's
  verification. `test_plugin.py` is wired into `tools/check.py`, and five
  mutations of the hook each turn it red. Prototype 0.1.0, not independently
  reviewed.

- **`@s0fractal/warrant` publishes from the release workflow.** `publish.yml`
  gains `js` (build once, test, gate on versions, clean tree and embedded WASM
  digest via `js/verify-build.mjs`) and `npm` / `jsr`, which publish those same
  bytes by OIDC — npm in environment `npm`, JSR from the linked repository, each
  behind a repository variable until its registry trusts the workflow. 0.10.0
  was published by hand from 0ec3b73.

- **WASM builds no longer carry the builder's paths.** `web/build.py` remaps the
  checkout and the cargo registry (`--remap-path-prefix` → `/warrant`, `/cargo`);
  the binary embedded 18 copies of the checkout path and the builder's home
  directory, and would have shipped them in `@s0fractal/warrant`. Also corrected:
  the WASM digest is **not** reproducible across build locations (the location
  reaches rustc's symbol metadata), which the previous entry's commit message
  implied it was; `js/README.md` and `web/README.md` now say so.

- **`@s0fractal/warrant` for npm and JSR: the Rust verifier as an offline,
  typed JavaScript package.** Built from the same Rust/WASM adapter as the
  browser lab (`impl-wasm`, `web/build.py`), with the WASM bytes embedded so
  an import never fetches anything and needs no CLI, checkout or install
  script. `verifyStore` returns the existing `warrant.verify-report@v0`;
  `runCheck` re-executes `ski@v1` (never `cmd@v1`); admission refusals and
  engine traps throw instead of becoming a report. It carries the WASM
  resource profile in every host — notably a **1,000,000 declared-ATP cap
  per check** against the native CLI's 100,000,000 — and the tests pin that
  divergence: at the boundary (inclusive cap, native passes above it while the
  package refuses), at depth (a 1,500-deep spine passes natively and either
  completes or traps in a disposable worker, never a fabricated result), and in
  the native `StoreCas`/`BlobCas` adapters (missing file, directory, symlink,
  dangling symlink, wrong bytes behave identically). `runCheck` — and the WASM
  `run_check` beneath it — no longer demands a `records/*.json` file: a check
  needs blobs only, as native `warrant check` always did (the browser lab keeps
  its own "select a record" guard). The deepest stored term the 2,048-file limit
  admits (2,046 nodes) completes in WASM as natively; the packed tarball is
  installed offline into an empty project by `js/test/installed.test.mjs`; CI
  also dry-runs the JSR publication. Self-tests and package QA, not an
  independent governance gate. No protocol surface moved.

- **Telemetry correlation: warrant beside OpenTelemetry, joined by
  `tool_use_id`.** `docs/telemetry-correlation.md` synthesises two external
  drafts that proposed putting WarrantIDs on spans, keeps their aim and replaces
  the mechanism the integration study had declined (an agent signing its own
  telemetry). The PreToolUse hook now binds `tool_use_id`, `session_id`, the
  tool input and any `TRACEPARENT` it is handed into the **signed subject**
  (`warrant.tool-call@v0`, built by `warrant_approval.tool_call_subject`) rather
  than a prose reason. `tools/otel_audit.py` (stdlib only) reads an OTLP/JSON
  export and a store and classifies each call: `store-invalid`, `misbound`,
  `contradiction`, `unwarranted` (exit 1), `telemetry-missing`, `corroborated`,
  `not-hook`, with a reason column (`reruns` for a re-executed `ski@v1` check).
  Its fixtures are synthesised from the documented Claude Code / Claude API event
  shapes, not captured; the selftest is wired into `tools/check.py`
  and was mutation-tested; `demos/otel-vs-warrant/` walks six scenes (edited export, API refusal with no span, dropped batch, relabelled pointer, edited evidence, a re-run reason) and asserts each (69 checks). No protocol surface moved; `warrant.otel-audit@v0` is
  a non-normative tool output. Self-tested only; no independent gate ran.

- **Browser lab and Rust-to-WASM adapter.** A static Pages frontend explains
  the format, opens a repository-pinned signed example or local record/store,
  returns the existing verify-report schema and re-executes `ski@v1` locally.
  The Rust core gains read-only in-memory store reads and explicitly supplied
  trust configuration; native defaults and protocol rules are unchanged. The
  browser uses a worker, smaller local ATP/input limits and an incomplete
  result for unfinished work. npm/JSR publication and signed website claims
  are not part of this increment. File/memory parity, actual WASM/reference
  comparisons and local browser interaction checks cover this implementation;
  these are tests, not an independent governance gate.

## 0.10.0 — one version, one behaviour, on both registries

`warrant-verify 0.9.0` shipped twice with different code: the PyPI wheel
(2026-08-01) and the crates.io crate (2026-10, carrying eleven reference fixes).
0.10.0 is cut from one tag for both, so the same version number again means the
same verdicts. Release contents, newest first:

- **Disclosed: a §9 threshold does not bind adoption in any implementation.**
  SPEC §9 admits an adopted root only if the adoption satisfies "the adopting
  root's current settlement policy, including any threshold rule"; Python, Go and
  Rust all evaluate instead the policies the adoption record itself cites, which
  its filer chooses — so a genesis root filed under a 2-of-2 threshold admits a
  root on one signature, 0 errors, 0 warnings
  (`proposals/wrt-014-model/reproduce.py`). THREAT-MODEL SA-7 now says so;
  [WRT-014](proposals/WRT-014-adoption-policy-binding.md) lays out the readings
  and options (fail-closed A/B, documentation-only C) and **decides none** — it is
  a settlement-semantics change for the owner. No behaviour changed.

- **Three Go consensus defects, found by comparing findings rather than counts.**
  (1) A threshold policy re-encoded as UTF-16, UTF-32 or with a UTF-8 BOM (also:
  with a `NaN` member) was "not JSON" to `encoding/json`, so `warrant-go` treated
  it as an opaque policy and **adopted a root on one signature where the policy
  asked for two**; Python and Rust read the declaration, found the bytes
  non-canonical and reported `ERR: invalid threshold policy`. Go now classifies a
  blob as a policy the way the reference does (`lenientJSONLoads`: encoding
  detection, NaN/Infinity, trailing content refused, the 4300-digit limit);
  canonicality is still judged on the raw bytes. (2) A `ski@v1` reason with no
  string `check` was skipped silently by Go — the silent skip SPEC §6(7)
  forbids — and is now reported `ski@v1 unverified`. (3) Go reported one finding
  per distinct referenced hash, the reference one per reference, so a hash cited
  twice gave different error counts. `tests/go_findings_parity.py` compares every
  finding's `(level, subject)` over fuzzed settlement stores at both grades and a
  policy in ten encodings; it is red on the previous Go (7/10 encodings split)
  and green now (240 reports). **[protocol-visible]** for `warrant-go` users at
  settlement grade.

- **The quickstart reaches a green settlement-grade report, with two new
  commands, and agents can read `why`.** `warrant trust add --actor ID
  --key FILE|--pubkey HEX` and `warrant trust root WARRANT_ID` create or extend a
  local trust config (SPEC §12) — the act that answers SA-2 had no tool, and the
  README stopped at "0 errors, 3 warnings". They write only what they are told:
  idempotent, weak keys and non-hex roots refused, an existing config that does
  not validate refused and left untouched. `warrant why ID --json` emits the walk
  `why` prints as one `warrant.why@v0` object (status per record, whole bodies,
  same exit status) — **non-normative**, no SPEC section. Both in Python and in
  `warrant-rs`, byte-identical (`tests/rs_parity.py` now compares them too).
  Following the README to settlement grade also showed its own accept was a
  re-litigation citing nothing new (no transcripts, so no new evidence and no
  new fingerprint — SA-1): the README now files transcripts that differ, and
  `tests/trust_and_why_json.py` runs the README's "Try it" blocks **verbatim**
  in both implementations and requires `0 errors, 0 warnings`. No protocol
  surface moved.

- **Orientation files made true and checked.** `llms.txt` named PyPI 0.6.0,
  "conformance 45/45" and DRAFT AGENTS rules that no longer exist, and did not
  mention the crate; THREAT-MODEL SA-6 and TRADEMARK still called `impl-rs`
  base-only. SA-6 now states what parity still assumes (one lineage, two ports).
  `tools/doc_counts.py` holds the conformance count to a real run, the crate
  version to pyproject, and llms.txt's published-packages paragraph to pointers
  rather than numbers.

- **The Rust implementation reaches the reference: the whole `warrant` CLI, held
  to its output byte for byte, and prepared for crates.io as `warrant-verify`.**
  `impl-rs` was a base-grade verifier (canon, schema, WarrantIDs, Ed25519
  verification, §6 store checks). It now implements every verb of the reference
  CLI — `init keygen blob policy propose accept reject supersede why check
  verify settle resign conformance selftest probe canon`, with the same flags —
  including settlement grade (§5.1 key state, §7 tunnels and fingerprints, §9
  roots and thresholds), `ski@v1` re-execution (a port of the pinned Book I v0.5
  evaluator, resource limits and their sampling cadence included), Ed25519
  signing, and the `warrant.verify-report@v0` report. Still no dependencies and
  no `unsafe`. On the conformance pack it reaches **settlement** grade, 139/139.
  `tests/rs_parity.py` compares its stdout, exit status and written bytes with
  the reference's over every reference-CLI call in the adversarial harnesses,
  fuzzed settlement stores (with a 29-branch coverage floor), the whole pack and
  fuzzed near-JSON; it has a negative control. CI gains a parallel `rust` job;
  `publish.yml` gains a `crate` job (package, test the package, dry-run upload)
  and a `crates-io` job gated off until the one-time setup in PUBLISHING.md is
  done. Nothing has been published. `tests/conformance_runner.py` and
  `tests/verify_three_way.py` now expect settlement grade from Rust and ask both
  grades; the runner's base-only path is kept under test by a proxy candidate
  (`tests/fixtures/base_only_candidate.py`). No protocol surface moved by the
  port itself.

- **Eleven reference defects found by the port, fixed in `impl/warrant.py`.**
  Each is a store anyone with write access can produce. Nine crashed the
  verifier outright (one record took the whole report down): a float in a ski
  check or threshold policy blob (`_canon_eq` caught only ValueError); a record
  nested ~500 deep (the canonicalizer recursed — it is iterative now); a trust
  config member that is `null`; a directory at a term child's address; a
  malformed record reached as an ancestor by settlement's tunnel walk; a valid
  signature whose `actor` is a list; a `ski@v1` reason without `check`; `why` on
  a record with no computable WarrantID; `under: [5]` at settlement grade. Two
  were **validity splits from Go**, the class this project ranks first: `HEX64`
  was `^…$`, and Python's `$` matches before a trailing newline, so
  `"<64 hex>\n"` was a valid hash in Python and not in Go (now `\A…\Z`); and
  `"ski": true` passed `ski != 1` (`True == 1`) and ran as a v1 check blob.
  **[protocol-visible]** in that the reference now refuses what SPEC and Go
  always refused. JSON nesting depth was the interpreter's stack (~990 to parse,
  ~500 to canonicalize, varying with the caller); it is now an explicit bound of
  **512**, checked before parsing, identical in Python, Go and Rust — documents
  deeper than that, which previously crashed or depended on the stack, are now
  uniformly "malformed JSON (nesting too deep)". `tests/reference_defects_2026_10.py`
  is red on the pre-fix reference for every case and green after, in all three
  implementations.

- **`warrant-mcp` no longer loses a call when the host reuses a request id.** Two
  `tools/call` with one id, both outstanding, used to leave one entry in `pending`: the
  first call vanished from the pack and the second was sealed with the first's result,
  while the manifest said complete and the proxy exited 0. `run_proxy` now decides each
  id's bookkeeping with the pinned table: a reused id is marked ambiguous, both calls
  are listed in `unreturned_calls` with `"ambiguous": true`, responses on that id are
  kept as blobs in the new manifest field `unpaired_responses` and never sealed, and
  the pack is incomplete (exit 3). The proxy refuses to start (exit 2) if the table does
  not load, and `run_proxy` loads it before spawning a server. A `tools/call` with no id
  (or id null), which the server may still execute and whose answer can never be paired,
  is listed unreturned with `"reason": "no request id"`, and a null-id response is kept in
  `unpaired_responses` (found in Codex's adversarial review of #81). No protocol surface
  moved.

- **`warrant_mcp.load_table()` authenticates and loads the certified table, unused.**
  The runtime's and the table's SHA-256 are pinned in `warrant_mcp.py`; a difference
  is refused before anything executes, and the runtime runs from the bytes that were
  hashed. `run_proxy` does not use it yet. No protocol surface moved.

- **`warrant_mcp_table` ships in the wheel, unused.** stargate's fixed table runtime
  (standard library only, lookup only), byte for byte; the first of three changes that
  put `warrant-mcp`'s per-id bookkeeping under a pinned, certified table. Nothing loads
  it yet. No protocol surface moved.

- **WRT-013 stage S1 — a DRAFT registration for `ski@v2`, in force nowhere.**
  SPEC §3.2 now carries the full contract a future admission change would
  register (check-blob shape with an explicit `exit`, verdict mapping, the
  local-outcomes-are-never-verdicts rule, the §7 fingerprint tuple that excludes
  `atp_spent`, and body version `0.3`), under a status block that says a
  conforming verifier MUST still reject the tag and the version. §7, §13.1 and
  §13.2 point at it and keep their "reserved, not registered" wording.
  `schemas/drafts/` gains the `0.3` body schema and the first schema the ski
  check blob has ever had; `examples/drafts/ski-v2-vectors.json` carries the
  23-case vector set, each case marked `executable_today` so a case nobody runs
  cannot be cited as evidence. **No protocol surface moved**: no implementation
  accepts `ski@v2` or `0.3`, no evaluator ships, no in-force schema, vector or
  conformance-pack entry changed, and `ski@v1` is byte-identical.
  `tests/ski_v2_draft_status.py` asserts exactly that by execution (Python, and
  Go over the probe `validate` class), pins the §8.2 specimen and each M5
  fingerprint as the COMPLETE historical tuple
  `('ski@v1', term, expect, 'pass', expect)` — a preservation contract that
  admitting `ski@v2` must leave untouched, since v2 changes nothing about what a
  `ski@v1` reason fingerprints to — and fails if any `executable_today` case is
  not actually executed. Demonstrated to fail twice: admitting the tag in
  `RUNTIMES`/`ACCEPTED` turns it red on six assertions, and appending a member
  to every fingerprint turns the preservation assertions red (the earlier
  equality-only form passed that mutation — found in review, not by me).
- **WRT-013 stage S2 — the `ski@v2` execution path, reachable by no record.**
  `impl/warrant.py` gains `validate_ski_v2_blob` (the closed five-member draft
  blob), `run_ski_v2_check` (Book I 0.6.0 `eval_receipt`, verdict = declared exit
  **and** result hash, `atp_spent` reported and never compared) and a SECOND
  evaluator table, `DRAFT_SKI_EVALUATORS`, kept apart from the in-force
  `SKI_EVALUATORS` because a reserved tag has no business in the table
  verification consults. `impl/sigma_glyph_v06.py` is vendored for the checkout
  and deliberately **not** added to `pyproject`'s `py-modules`: candidate bytes
  do not ship before a body version can invoke them
  (`history/SKI-V2-EXECUTABLE-CANDIDATE-RETIREMENT.md`), so an installed wheel
  has no `ski@v2` evaluator and reports `runtime unavailable`. **No protocol
  surface moved**: `RUNTIMES`, `ACCEPTED`, the schemas, the fingerprint and both
  verify loops are untouched, so `ski@v2` and body `0.3` are still rejected
  everywhere. `tests/ski_v2_execution.py` pins the four-cell verdict matrix over
  one term at two budgets, the refusal class of every local fault (admission,
  resource, foreign-keyed bytes, over-budget, drifted evaluator, missing or
  non-canonical blob), the wrong-version blob under either tag, and `ski@v1`
  still answering its §8.2 specimen in exactly 20 ATP. Demonstrated to fail:
  dropping the exit from the verdict reddens four assertions; turning an
  admission refusal into a `fail` reddens one.
- Docs, no protocol surface moved: the `ski@v1` safety claim is qualified
  everywhere it was still stated as "work and peak memory bounded by `atp`, safe
  by construction" — THREAT-MODEL A8, SPEC §3.1 and its security
  considerations, the `policy_lang` docstring, `docs/index.html`, the listing
  entry text. `atp` bounds priced work and materialized semantic state
  (`size − 1 ≤ spent`); it does not bound process peak memory, wall-clock or
  host admission/parsing work, so the re-execution budget and local resource
  fences remain the verifier's job and a breached local limit is reported
  `unverified`, never as a verdict. The paper and the 2026-08 review response
  (MC6, accepted) already said this; the normative text had not caught up.
- `experiments/EXP-001-adversarial-adjudication/`: pre-registration of the
  adjudication experiment the 2026-09 cross-stack review asked for (evidence
  pack versus plain log, four planted defect kinds placed by a second party
  under a hash commitment, two adjudicator families, falsifiers fixed before
  measuring). Registered as NEED-003. Not run; no result may be cited.
- `warrant-mcp`: a tool the effects config does not declare is sealed as
  undeclared (A4) whatever its name — name hints annotate the record and can
  no longer lower the class (`query`, `get_and_execute` were A0 by substring
  and never sealed under the default ceiling); an empty effect list in the
  config is refused at startup (exit 2); a failed seal is counted in the
  manifest (`seal_failures`, `seal_failure_log`, `observation_complete`) and
  in the exit status (3) instead of only on stderr; a call sent downstream
  and never answered before the server exited is listed as `unreturned_calls`
  with its class, the downstream exit code is recorded, and the pack is
  marked incomplete (exit 3) rather than reported complete and empty; a
  server-initiated request (`ping`) reusing the host's request id no longer
  resolves the pending call -- only a response does. Review:
  ChatGPT (web), 2026-09, `reviews/2026-09-chatgpt-web-cross-stack.md`; the
  unanswered-call path from Codex's review of PR #63. The compiler's
  no-arithmetic message and `docs/authoring-checks.md` now say what is true:
  arithmetic is not implemented and not admitted in WPL v1 (integers are
  fixed-width bit vectors of Church booleans, comparison only), and where the
  trust moved when a value is computed upstream and pinned as a fact.
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
  - Exact-head review (Codex, 29aecf8) found two false-green paths in the
    driver, both closed: every consumed `verify --json` report is now held to
    its own grade, `ok`, counts and exit status and to the exit the frozen
    vector implies (an installed CLI returning 1 with `ok:false` for the clean
    records is a `FAIL`, not a reproduced vector); and the control set is
    closed — a manifest naming an unknown control, or omitting a required one,
    is `REFUSED manifest`, and the closing count is of controls that executed.
    `tests/replay_driver.py` regresses both through the real `warrant`
    console script (venv assembled from `impl/`, no network) and is wired into
    `tools/check.py`.
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

[Unreleased]: https://github.com/s0fractal/warrant/compare/v0.12.0...HEAD
[0.12.0]: https://github.com/s0fractal/warrant/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/s0fractal/warrant/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/s0fractal/warrant/compare/v0.9.0...v0.10.0
[0.8.0]: https://github.com/s0fractal/warrant/compare/v0.7.1...v0.8.0
[0.6.0]: https://github.com/s0fractal/warrant/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/s0fractal/warrant/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/s0fractal/warrant/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/s0fractal/warrant/compare/v0.3...v0.3.0
[0.3]: https://github.com/s0fractal/warrant/compare/v0.2.0...v0.3
[0.2.0]: https://github.com/s0fractal/warrant/releases/tag/v0.2.0
