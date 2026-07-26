# WRT-001: `sigma-glyph.wave@v1` — a settlement-integrated check runtime

**Status:** PROPOSED (2026-07-26) — Warrant-side companion to **sigma-glyph ADR-008 (Resonant Precedent)**, which consumes this runtime. Not adopted; no production signatures; no cross-implementation port yet. This document is the normative home of the runtime per ADR-008's cross-project split: *C1 (the runtime) belongs to Warrant; Book II owns the coherence math; Book III owns effective-wave selection; the ADR-008 profile owns the view/entry/result schemas.*

**Origin:** ADR-008 needs to cite a prior decision as *precedent* with a machine-checkable claim "decision X's projected wave coheres with query Q, under jurisdiction J's effective wave." `ski@v1` cannot express this: it evaluates a Book I SigmaNode graph and cannot parse a Book III JCS assertion, call Book II `wave()`/`LUT_COS`, or bind body-level evidence to a fact inside the term. So ADR-008 requires a **new Warrant check runtime**. The rev-1..7 gate history (in `sigma-glyph/reviews/`) established that this is a Warrant-level contract — not a string added to `RUNTIMES` — because it changes validation, severity, tunnel expansion, novelty fingerprinting, and future budget.

**Reference prototype:** `sigma-glyph/examples/resonant_precedent_join_probe.py` — a hermetic fixture (real signed lineage, synthetic trust config, settlement-derived context) demonstrating the runtime rules against this repository's `_settlement_context`, `verify_store`, and `select`. It is a **wrapper prototype**: it does not implement the real single-context/one-reporter path (§3), R1, §7, or a governed profile anchor, and R0 is live-head (not the R1 checkpoint). Adopt after ≥3-family review and a real implementation gate, per the Decision Process.

---

## Why a new body version (not a `RUNTIMES["0.2"]` extension)

Appending `sigma-glyph.wave@v1` to `RUNTIMES["0.2"]` at runtime **retroactively
changes the validity of already-versioned bytes**: the same body is invalid to a
clean 0.2 verifier and valid to a patched one, with an unchanged WarrantID — two
honest 0.2 implementations disagree on whether the record exists in the valid
domain. This violates Warrant's version rule ("unknown versions make the record
invalid") and destroys cross-implementation agreement before the runtime even
runs.

**Decision:** `wave@v1` is permitted **only under a new body version tag**
(prototype: `0.2+sigma-wave.1`). A clean 0.2 verifier then *rejects* a wave
record as an unknown version — a correct, deterministic outcome — rather than
re-interpreting 0.2 bytes. The new version is warranted because the runtime
changes more than an allowed string: severity (`unverified`→ERR escalation),
tunnel expansion, the §7 novelty fingerprint, and a future re-execution budget.

## The runtime contract (normative)

### 1. Reason and check schema

A `wave@v1` reason is `{kind: "check", check: <hex64>, runtime:
"sigma-glyph.wave@v1", verdict: "pass"|"fail"}`. The check blob is closed:

```json
{ "check": "sigma-glyph.wave@v1", "entry": "<hex64 precedent-entry@v1>",
  "query_assertion": "<hex64 wave-assertion>", "threshold": <int16>,
  "ruleset": "<hex64 governed Σ anchor-set>" }
```

### 2. Ruleset binds the executed semantics

The runtime implements **exactly one governed anchor-set hash**. `check.ruleset`
MUST equal it or the reason is `unverified`. The anchor-set commits the **real**
governed Specification Anchors it executes — from `sigma-glyph/spec/ANCHORS.txt`:
Book II (`spec/book-2-navigation.md`, coherence/`LUT_COS`) and Book III
(`spec/book-3-federation.md`, assertion schema + `select`). **Book I is
unreachable**; the only narrow Book I dependency is NodeHash identity. **The
profile member is NOT yet governed:** ADR-008 is not in `spec/ANCHORS.txt`, so
pinning a raw document digest of it is self-referential and goes stale as prose
changes. Before adoption, the profile (C0/C2/C3 schemas + join algorithm) MUST be
factored into an externally anchored artifact and its governed anchor pinned
here. Until then the ruleset is *exact* (a different hash is `unverified`) but not
*wholly governed*.

### 3. Fail-closed, single settlement context, dispatched by `verify_store`

The runtime MUST be invoked **by `verify_store` itself** (as `ski@v1` is), so the
public verifier's error count includes wave outcomes — a caller trusting a
zero-error result must never miss a wave failure. The **real Warrant plumbing for
this has now landed** (§Deferred item 0): one record snapshot shared by base
checks, settlement context, and dispatch; fail-closed context construction as a
GLOBAL ERR with a stable Python↔Go reason; and a `(body_version, runtime)`-scoped
dispatch registry that hands a handler the single ctx/snapshot + mode + reporter
and **no raw authority**. What remains before wave activation is the runtime
semantics itself (§6/§7), not the plumbing. (The Sigma reference is still a
*wrapper prototype* over `verify_store`; it does not register through the new
registry.)

### 4. Totality

The dispatcher executes reasons only from shape-validated records, stays
defensive over inactive malformed records (`because: ["not-an-object"]` must not
raise), and converts every runtime exception to `unverified`. No input in the
byte domain may raise; `verify_store` stays bounded.

### 5. Severity

`pass`/`fail` are the check verdicts (compared to the claimed `verdict`; a
mismatch is a failure). A structurally unexecutable citation is `unverified`,
which is **ERR for a settlement-active record** and WARN otherwise — identical to
the `ski@v1` unverified rule.

### 6. Citation role binding + the temporal contract (LIVE-HEAD at R0)

**Role binding (MUST).** The reason-bearing citation Warrant is bound to its
entry: `citation.body.subject.hash == check.entry`. The candidate universe
excludes **only the current citation's own WarrantID** — never "any record
carrying a wave reason". Excluding by reason *presence* is a bypass: a rival
assertion that borrows a valid check reason would silently vanish from Book III
`select()` even though, if included, it would win. With the binding, a borrowed
reason on a non-citation record fails (its subject is not the entry) and the
rival remains a selection candidate.

**Effective vs eligible — AUTHORIZATION REQUIRED (R1-only, NOT normative here).**
Warrant's `active_records` is a settlement/root **eligibility** set: it still
contains a record an active `supersede` has replaced (SPEC §7). It is tempting to
define the effective set as `active_records` minus every active-`supersede`
target — but that is a **CENSORSHIP PRIMITIVE**: Warrant eligibility checks only a
self-signature, so **any actor can supersede another actor's WarrantID** and evict
it. The runtime therefore **MUST NOT** use that naïve derivation. The authorized
effective set, `authorized_effective_active_for(J, checkpoint)` — where a
supersede is honoured only if authorized by the target's policy / key state — is
**deferred to R1** (§Deferred items 1–2). Until then:
- **R0 queries rank over RAW eligibility** (`active_records`), so an unauthorized
  supersede cannot change a query result (probe: an R0 query is unchanged under a
  foreign supersede of the cited assertion);
- the naïve effective derivation survives **only** as an explicitly-failing
  research vector in the R1-anticipating prototype path, never as the profile
  algorithm.

**Temporal contract — R0 LIVE-HEAD is EPHEMERAL (research query only).** The
candidate universe is `raw active_records for(J)` (R0) — the current citation is
subtracted only in the R1 stored path; the
C2 view commits `assertion_set_root` of it and the runtime recomputes it. This is
complete (no rival can be omitted) but **live**: any growth of the effective set
changes the commitment. Because a `stale` mismatch is returned `unverified` →
ERR (§5) and Warrant's active set is **append-only** (a new citation does not
deactivate an older one), a settlement-*carried* live-head citation would poison
every prior citation on any store growth — the re-cite workflow cannot converge.

**Decision: R0 is a DIRECT ephemeral query API that creates no Warrant reason.**
The closed check/view schema has no `mode` or checkpoint field, so "a wave reason
MUST NOT be filed settlement-active" is only *enforceable* by keeping R0 a
non-filing call (`verify_citation(...)` directly), not by inferring the mode from
host configuration. A **STORED** citation is exclusively an R1 record whose check
schema **explicitly carries the authorized checkpoint WarrantID** (below); a
verifier MUST reject a settlement-active wave reason that names no checkpoint.
(The Sigma probe's `verify_store` demonstration files such a reason only to
exercise the plumbing and is labelled as anticipating R1, not a permitted R0.)

**R1 — historical authorized checkpoint (REQUIRED for any STORED citation, not a
later tightening).** A stored, replayable, non-manipulable citation needs a
**threshold-authorized checkpoint object**: a settlement record committing the
**effective** set at an epoch, authorized by the jurisdiction's policy (not
self-filed), whose membership is replayable and growth-immune. This depends on
**key-state / threshold policy** — so key-state + effective-lifecycle are ordered
**before** budget (§Deferred). Until R1, the runtime is NOT structurally closed
for a stored precedent; only the ephemeral R0 query is available.

### 7. §7 novelty fingerprint and tunnel closure — PROPOSED AND DEFERRED

This is **not yet integrated**: the real `fingerprint(reason, body, store)`
returns `None` for a `wave@v1` reason and `tunnel_fingerprints()` is empty. Two
things MUST be specified and implemented before any settlement-novelty claim:

- **An executable *outcome* fingerprint** — it MUST carry the *recomputed*
  verdict (and the coherence / selected-assertion result), not the *claimed*
  verdict, so a false claim cannot mint novelty. The tuple sketch
  `("sigma-glyph.wave@v1", entry, query_assertion, threshold, ruleset, …)` is a
  starting point, not a closure rule; the executable form must recompute from all
  nested blobs and settlement state.
- **The exact recursive tunnel closure** — which members enter the tunnel (check,
  entry, query, view; projection, cited assertion, projection/selection policy,
  vocabulary, ruleset; the decision/projection/assertion/checkpoint records; every
  candidate examined by `select()` and its subject blob), and how unresolved and
  budget-exhausted members behave.

Until both exist with vectors, a wave citation is **not** settlement-novelty-
integrated and MUST NOT close or re-open any settlement it touches. Consuming
documents MUST NOT claim §7 registration/closure is specified.

## Deferred (named, not faked) — REORDERED after the rev-8 gate

The rev-8/rev-9 gates showed the budget cannot come next: it would meter an
unstable computation (R0 is live-head, effective-lifecycle and §7 are unfinished).
Ordered close-out before adoption:

0. **Generic Warrant verifier refactor — regression-free per an independent gate,
   with a corrected (narrowed) scope (working tree; branch, not master).**

   **SCOPE (what item 0 delivers and claims parity for):** (a) one record
   snapshot threaded through settlement/re-litigation; (b) the **trust-config and
   hash-pinned `genesis.json` *config* inputs** parsed once under one strict
   I-JSON domain (invalid-UTF-8 / NaN-Infinity / dup-key / trailing / non-object
   rejected; genesis a bounded no-op incl. present-but-unreadable → WARN, never a
   traceback), with **Python↔Go parity at the public `verify` report level for
   those config inputs**; (c) fail-closed trust short-circuit; (d) the read-only,
   version/reason-scoped runtime dispatch (Python).

   **NON-CLAIMS (explicitly out of scope):** item 0 does **not** claim
   verifier-wide Python↔Go parity or crash-freedom on adversarial **record /
   blob / policy / canonicalization** inputs. Those belong to the ongoing
   verifier-hardening track (the Kimi full-audit line).

   **Independent gate:** Kimi K3 ran an adversarial gate
   (`reviews/2026-07-kimi-k3-item0-adversarial-gate.md`), forbidden from
   rubber-stamping. Verdict `AMEND` — 11 P1 counter-vectors. Triage: **all 11 are
   in verifier code byte-identical to `origin/master` (pre-existing latent bugs,
   NOT item-0 regressions)**; the gate refuted an over-broad contract claim (now
   narrowed above) and surfaced one in-scope item (`genesis.json`-as-directory
   traceback), **fixed** (Python guard + Go parity WARN). item-0's own changes are
   regression-free.

   **Verifier-hardening prerequisite — DONE.** The severe *pre-existing* findings
   (Go stack-overflow on a prior-cycle+rotation store; Python tracebacks on
   dir-as-blob / dir-as-genesis / lone-surrogate record; the `-0`
   canonicalization/WarrantID **consensus split**) plus the count-parity gaps were
   fixed and independently re-gated by Kimi K3 (all 11 confirmed FIXED, no new P1;
   `reviews/2026-07-kimi-k3-item0-regate.md`). This generic verifier refactor +
   hardening is landed on `master`. **`wave@v1` itself is NOT adopted here:**
   `0.2+sigma-wave.1` is **not registered** in `ACCEPTED`/`RUNTIMES` and this doc
   is PROPOSED, not adopted. Adoption still requires the deferred items below
   (budget, key-state → R1) and a **2-of-3 governance threshold warrant** signed by
   roster keys — a git merge of the refactor is not that adoption.
   - **One record snapshot, threaded everywhere:** `verify_store` loads records
     once and threads that snapshot through the settlement context, the runtime
     handlers, **and the re-litigation path** (`settlement_admissibility`/`tunnel`/
     `tunnel_fingerprints` no longer reload) — a two-record re-litigation lineage
     now reads the store exactly once (was 5).
   - **One strict I-JSON domain for every trust/pinned input:** trust config and
     `genesis.json` are decoded by the SAME strict parser in Python and Go —
     rejecting **invalid UTF-8** (Go's `encoding/json` substituted U+FFFD), **NaN /
     Infinity / -Infinity** (Python's stock `json.loads` accepted them), duplicate
     keys, and trailing content; `genesis.json` is hashed and parsed as the SAME
     bytes under a **total schema** (`roots` may be absent/null/scalar → bounded
     no-op, never a Python traceback; roots must be hex64). Identical digest-pinned
     bytes therefore authorize identical roots (a duplicate `roots` key no longer
     adopts an attacker root in Go). Differential vectors assert **all three**
     summary fields `(records, errors, warnings)` — the record count is no longer
     dropped, and the genesis vector asserts the attacker root is *not adopted*
     (unadopted-root warning), against a clean-genesis baseline that *is* adopted.
   - **One trust parse, fail-closed over the SEMANTIC domain:** the trust config is
     parsed once (I-JSON) and **closed-schema-validated including nested types**
     (`genesis_roots`, `actors`, `genesis_json_sha256`, unknown fields), then passed
     **by value** into context construction — no second read, no nested-invalid
     escape. A missing / malformed / non-object / trailing / dup-key / nested-invalid
     trust config is one global ERR `settlement trust config unavailable`.
   - **Fail-closed continuation is short-circuit, PRECEDING any per-record report,
     identical Python↔Go at the public `verify` report level:** a requested
     settlement verification whose trust config is unusable reports the one global
     ERR and **stops before emitting any per-record error** — so a malformed record
     plus broken trust is still exactly `(1, 0)` in both (Python previously emitted
     the record load-error first, giving `(2, 0)`/`0 records` vs Go `(1, ?)`). Both
     return `(1, 0)` exit 1 on empty and non-empty stores, with vectors in
     `tests/settlement.py`. A trust failure runs no runtime handler.
   - **Read-only runtime execution context (TCB model, stated):** a registered
     handler is governed verifier-extension code (in-process Python is not a
     security sandbox); the view **retains no reference to the live record map or
     raw store** (it holds a deep-copied private snapshot + frozensets), so a
     handler cannot crash the record loop (`dict changed size`) or corrupt core
     verification by mutation. Blob bytes come only through a digest-authenticating
     resolver whose usage counter is **verifier-owned** and counts attempted work
     **including wrong-digest reads** (an adversarial-plugin model would need a real
     process/WASM boundary — out of scope).
   - **Version/reason-scoped registry** keyed by `(body_version, runtime)`; a handler
     runs only for a shape-valid matching reason; **core runtimes cannot be overlaid**;
     duplicate/unauthorized registration refused. Tests: `tests/runtime_hook.py`
     (base / settlement modes, single-snapshot, CAS good hash / present-wrong-digest,
     mutation isolation, trust-failure short-circuits with no handler run).
   - `0.1/0.2/cmd@v1/ski@v1` preserved byte-for-byte (`agree_check` green).
   - **Parity scope (explicit):** the **trust construction AND its fail-closed
     continuation** are **Python↔Go** at the public `verify` report level (empty +
     non-empty vectors); the registry/handler/CAS layer is **Python-only** (Go/Rust
     runtime parity is deferred item 7). Rust has no settlement path.
   - **`0.2+sigma-wave.1` is NOT registered.** Awaiting commit via the Warrant gate.
1. **AUTHORIZED effective-lifecycle derivation** (§6) — the naïve "active minus
   supersede targets" set is a **censorship primitive**: Warrant eligibility only
   checks a self-signature, so any actor can supersede another's WarrantID and
   remove it from C2 / cardinality / `select()` (shown in the probe as a
   known-open gap). Effective supersession therefore needs **target-policy /
   key-state authorization** — so items 1 and 2 are **not separable**; the
   effective set is defined *by* key state. Also define supersede-of-supersede.
   Vectors: unbound/foreign, wrong-policy, authorized same-policy, chained,
   competing, unrelated supersede.
2. **Key-state binding → the R1 authorized historical checkpoint** (§6), which
   commits the output of the item-1 *authorized* derivation (not raw eligibility).
   Required for any STORED citation — a live-head reason cannot converge in an
   append-only store.
3. **Exact §7 fingerprint (recomputed, not claimed) + recursive tunnel closure**
   (§7), with novelty and foreclosure vectors.
4. **Externally governed profile anchor** (§2) pinned in the ruleset.
5. **Deterministic re-execution budget** — a simple cost model, **not** ATP
   verbatim; natural units: **canonical bytes read, WarrantIDs examined
   (checkpoint/cardinality), assertion candidates passed to `select`, a fixed cost
   per schema/digest check** — with `unverified` on exhaustion and exact-limit /
   one-over-limit vectors. Meaningful only once 1–2 fix which computation is metered.
6. **Direct-R0 abstention vectors** (pin-only / structurally-derived terms).
7. **Cross-implementation parity** (Go/Rust) over frozen fixture bytes — the final
   structural gate.
8. **Adoption via the Warrant governance gate** (2-of-3 roster) with real signing
   keys — only after 1–7.

## Relationship to `ski@v1`

`wave@v1` reuses `ski@v1`'s trust posture (re-runnable by anyone with the blobs,
`unverified`→ERR severity, verify-time re-execution) but not its executor: it runs
a pinned Book II/III integer algorithm over JCS assertions, not a Book I graph.
Where `ski@v1` bounds work by ATP, `wave@v1` will bound work by the §Deferred
item-5 cost model. The two are siblings in the runtime registry under distinct body versions.

---

**Adoption checklist (Decision Process):** ≥3 independent model families; a
reference implementation that makes `verify_store` dispatch this runtime with the
rules above; the deferred items 1–7 closed with vectors; then the governance gate.
