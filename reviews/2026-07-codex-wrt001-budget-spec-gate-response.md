# Adjudication — Codex gate on WRT-001 §8, the `wave@v1` re-execution budget

Raw review: [`2026-07-codex-wrt001-budget-spec-gate.md`](2026-07-codex-wrt001-budget-spec-gate.md)
(2026-07-27, against `wrt-001-budget-spec@10e5346`). Verdict **AMEND** — five P1,
one P2, and an explicit recommendation to keep §8 as a *draft cost framework*
rather than a specified one.

**Method and its limits.** The three §8 design findings were answered in the
proposal text on 2026-07-27 (`ad1b8d8`, `0d589a8`). The one implementation
finding was re-checked here against `master` by running both implementations,
with a control. The remaining two were closed on 2026-07-31 while preparing this
branch to land. **No second adversarial gate has run on any of it.** This
document is a disposition record, not a gate; §8 is still DRAFT and WRT-001 is
still PROPOSED.

## Dispositions

| # | Finding (Codex) | Verdict | Disposition |
|---|---|---|---|
| P1-1 | Committed ceiling unavailable when the first bounded read is required — `budget` lived in the check blob, but bounding the check-blob read needs the ceiling | **CONFIRMED — circular by inspection** | **Fixed** (`ad1b8d8`). `budget` moved to the **reason** (§1): the record body is parsed under its own I-JSON bounds before dispatch, so the ceiling is in hand with zero blob work. The check blob repeats it; `check.budget != reason.budget` is `unverified`. The reviewer's alternative (a pre-reason `WAVE_CHECK_MAX_BYTES`) is recorded in §8 as an equivalent design, not adopted, because it needs a second magic number. |
| P1-2 | Bounded-read arithmetic exceeds its own ceiling — spec read `R + 1` bytes | **CONFIRMED** | **Fixed, then over-corrected, then fixed properly.** `ad1b8d8` charged the resolution `+1` first and read `R − 1` bytes — one byte tighter than the reviewer asked for, and undecidable at the boundary: a full `R − 1`-byte read cannot distinguish an exactly-affordable blob from an oversize one. §8 now states the reviewer's own arithmetic verbatim in effect — read at most `R` bytes; fewer means affordable, exactly `R` is the sentinel proving unaffordable — which needs one read, no metadata, and never materializes past the ceiling. The over-correction is called out in §8 so it is not re-introduced. |
| P1-3 | The meter does not bound Book III selection work; `+1 per record` is not a size bound, and `select()` sorting is superlinear in comparisons | **CONFIRMED** (reviewer instrumented the selector: 1024 candidates → 9960 comparisons) | **Fixed in shape** (`ad1b8d8`). Each pairwise comparison charges `+(1 + m)` for the `actor.id` bytes compared, so superlinear comparison counts are charged rather than assumed away; the ADR-008 profile pins `WAVE_MAX_CANDIDATES` / `WAVE_MAX_ACTOR_ID_BYTES` as hard structural bounds, exceeding either being `unverified` rather than a silent truncation. **Partially open:** the reviewer's wider point — that the runtime also copies and inspects unbounded Warrant *body* arrays — is not fully closed. §8 now carries it as an explicit non-claim (peak memory is not bounded; the snapshot is charged per record, not per byte). |
| P1-4 | "Exact cost" is not yet a function of the specification — billable event trace undefined, and item 5 itself says the metered set stabilises only after items 1–2 | **CONFIRMED, and accepted rather than answered** | **Accepted as framing.** §8 is now explicitly a DRAFT *framework*: it fixes bootstrap and resource-completeness (the shape must be sound to exist at all) and deliberately does not freeze the scan set, caching, failed-load charging, traversal order, or error-vs-exhaustion precedence — those move with the effective-set computation, which is unstable until Deferred item 2. Exact `cost` integers and the byte-for-byte parity gate are normative only after item 2. This is the reviewer's own gate recommendation, adopted. |
| P1-5 | Item-0 I-JSON parity still excludes **escaped** lone surrogates: `"\uD800"` / `"\uD801"` keys split Python and Go on both a trust config and a hash-pinned `genesis.json` | **REPRODUCED AS FIXED on `master`** — the split no longer occurs | **Fixed on `master`, not by this branch.** Re-run here against `master` (`e79b26f`), Python and Go built from that tree: a trust config `{"actors":{"\uD800":[],"\uD801":[]}}` now yields `ERR settlement trust config unavailable`, `0 records, 1 errors, 0 warnings`, **identically in both**. Controls: ordinary keys → `0 errors` in both; a **valid surrogate pair** (`😀`) → `0 errors` in both, so the fix is not over-rejection — which is exactly the shape the reviewer asked for. `tests/settlement.py` carries the regression vectors (record body, trust actor key, policy blob) plus the valid-pair control, from the Kimi K3 line. **Not verified by me:** the `genesis.json` half. Both implementations agree (`0 errors, 0 warnings`) on a hash-pinned genesis carrying lone-surrogate keys, but an empty store surfaces no root-adoption difference, and the suite has no genesis-specific surrogate vector. No split is reproducible; whether the surrogate is *rejected* there, as opposed to accepted identically, is untested. |
| P2 | Local refusal policy mixed with deterministic semantics — `min(check.budget, local_cap)` and "reject if over cap" are different rules, and the text claimed exact agreement while making the cap environment-configurable | **CONFIRMED, and it survived `ad1b8d8`** | **Fixed 2026-07-31.** §8 now mirrors SPEC §3.1's existing `ski@v1` language, which already had this right: portable cost/boundary/verdict versus local *willingness*; a MAY-refuse that MUST report `unverified`; "a refusal is not a verdict"; differently-configured verifiers MAY disagree on whether a reason was re-executed, and that is local policy, not a schema split. The `min(...)` ceiling is **removed** — silently metering an over-cap reason down would make the exhaustion boundary depend on the environment. |

## Found while landing, not by the gate

Recorded separately so the gate is not credited with them.

- **The size-source fix inverted its own normative direction.** `0d589a8` closed a
  real seam — `stat()`-then-`read()` is a genuine compositional countervector —
  but named the **CAS-committed blob length** authoritative and the single-handle
  bounded read a "prototype approximation". That is backwards. Content addressing
  binds a digest to its authentic *content*; it says nothing about what a length
  index asserts about the bytes stored under that name. A length column is a claim
  by the store, and the attacker the rule exists for — one who can swap bytes under
  a hash — can generally also write the length describing the file it replaced, or
  leave a stale one. Trusting it relocates the seam from `(stat, read)` to
  `(index, read)`. The bounded read is the stronger primitive: race-free by
  construction and valid over a store the verifier does not trust. §8 now says so,
  with the index demoted to a MAY-consult fail-fast that MUST NOT authorize a
  longer read.
- **The budget is not a price.** §8 opens by contrasting itself with ATP, which
  bounds work *and* peak memory because Book I prices by term size. `wave@v1`'s
  meter is an enumerated tariff: it bounds charged work, bounds materialized CAS
  bytes, and does not bound peak memory or the pre-dispatch store load. §8 now
  carries these as non-claims, including the one that matters outside this
  repository: until item 2 freezes the trace, two conforming implementations may
  agree on the verdict and disagree on `cost`, so §8 supports a *bound* and not a
  *number*. Usage metering and billing need the number and cannot be claimed from
  this text.
- **A new cross-repository document ID breaks `tools/repo_map.py --check-map`.**
  The branch cited `ADR-001` once; `MAP.md` had no row for it and `check.py`
  went red. Regeneration was not a usable fix here: `repo_map.py` finds the
  sibling repository as `ROOT.parent / "sigma-glyph"` **only when the checkout
  directory is literally named `warrant`**, so regenerating from any worktree
  under another name silently rewrites all six sigma-glyph rows to "resolves
  nowhere" — a check whose output depends on the name of the directory it runs
  in. The citation was reworded to name Book I and ADR-001's actual title
  ("size-priced ATP"), which resolves through an existing row and loses nothing.

## Gate state

Gate 1 of ≥1 on §8: **AMEND**, and every finding is now disposed — four fixed,
one accepted as the framing the reviewer recommended, one confirmed fixed
elsewhere by reproduction. **That is not a pass.** The P2 and the size-source
inversion were closed *after* the gate and have been seen by no reviewer; the
sixth finding's `genesis.json` half is untested; and §8's whole remaining
substance is deferred behind item 2, which is not being worked. §8 stays DRAFT,
WRT-001 stays PROPOSED, `0.2+sigma-wave.1` stays unregistered, and adoption
remains a threshold warrant signed by roster keys.
