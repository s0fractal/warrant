# WRT-013 amendment 1: one current path, and what it refuses

**Status: DRAFT rev 1 (2026-09-18) — DESIGN ONLY.** No SPEC edit, no `impl/`
change, no schema, no vector, no adoption is made by this document. It amends
the accepted design `WRT-013-ski-v2-admission.md` (rev 3, ACCEPT at
`4c5606a`); everything that document says and this one does not change stays in
force. Written by Claude Opus 5 at the owner's direction in
`~/Projects/CLAUDE-POST-S2-SIMPLIFICATION-2026-09-18.md`, which replaces the
future work in the 2026-09-17 plan after S2. **That direction is a change of
priorities, not an adoption act, and neither is this document.**

## 0. What this amendment changes in WRT-013

| WRT-013 said | Amended to |
|---|---|
| §4: body `0.3`, admitting `cmd@v1`, `ski@v1`, `ski@v2` | body **`1.0`**, admitting `cmd@v1` and `ski@v2`. `0.3` is retired unused (§1) |
| §5.2: Python **and** Go execution agreement is a precondition of admission | Python alone is the current path. Go and Rust stay at `0.1`/`0.2` as **historical verifiers** and are not ported (§3) |
| §8: seven stages S3–S7, then a separate admission act | S3–S7 are withdrawn. One reviewed integration change (§6) |
| §9 Q3: WPL keeps emitting `ski@v1`, v2 by opt-in | One current writer: WPL and the other authoring paths move together (§2) |
| §6 vector 19/19a and the negative set | Unchanged in content; they move to the `1.0`/`ski@v2` path |
| "`ski@v1` bytes, verdicts, fingerprints and replays are untouched" | **Still true, and now carried by the frozen release**, not by the current implementation (§1.3) |

S1 (merged, `2412db7`) and S2 (open, `5469256`) stand as reviewed; this
amendment is what comes after S2, not a change to it.

## 1. The single supported combination

### 1.1 What it is

> **body `1.0` × runtime `ski@v2` (and `cmd@v1`) × the Σ-GLYPH Book I 0.6.0
> evaluator, digest `f4d9990d…3feb4` — the module published as `sigma-glyph`
> 0.7.0.**

One body version, one ski evaluator, one writer. `cmd@v1` is **kept**, not
removed: it is a separate runtime, not an old edition of this one, and the
dependency check below finds it in live use (all 16 check reasons in this
repository's own governance store are `cmd@v1`, and `oaip` writes it).

### 1.2 Why `1.0` and not `0.3`

`0.3` is not free to reuse. SPEC §13.2 reserves it for the **additive** step —
"`ski@v2` runtime … until then `ski@v2` is reserved-and-rejected" — and S1's
draft text in §3.2 states that `0.3` admits `cmd@v1`, `ski@v1` and `ski@v2`.
The path described here admits a **different, smaller** set. Publishing that
under the reserved number would be reusing a published identifier for changed
semantics, which is the one thing the owner's direction rules out. So:

- **`0.3` is retired, unused.** No record has ever carried it and no
  implementation has ever accepted it, so retiring it invalidates nothing.
- **`1.0` is the new edition**, and its major number says what it is: the first
  body version that is not a superset of its predecessor.

### 1.3 What happens to `0.1`, `0.2` and `ski@v1`

They are **not invalidated, not re-interpreted and not re-signed.** SPEC §13.2's
non-invalidation rule constrains what a new body version does to records, and
`1.0` does nothing to them: a `0.2` record stays exactly as valid under `0.2` as
it is today, with the same WarrantID and the same verification outcome.

What changes is **who verifies them**: the frozen release, not the current path.

- `warrant-verify==0.9.0` is published and installable, and it verifies every
  record that exists today, `ski@v1` evaluator included.
- `impl-go` and `impl-rs`, unchanged, are `body-format/0.2` verifiers. Not
  porting them is what leaves two independent historical verifiers standing.
- The current Python path will **refuse** a `0.1`/`0.2` record with a distinct,
  stable message naming that release. Not a silent skip, not a
  re-interpretation, not a `fail` verdict.

That refusal is the contract change this amendment actually needs, and §5 writes
it out.

## 2. Dependency check: who reads or writes the old path today

Narrow and current, per the direction: authoring/WPL, settlement,
governance/trust bootstrapping, Sigma-Glyph. Counts are read from the JSON, not
estimated. Archived projects were not opened.

| Consumer | What it is today | Decision |
|---|---|---|
| **This repository's governance store** `.warrants/` | 16 records: 14 × body `0.2`, 2 × `0.1`; 16 prose + **16 `cmd@v1`** check reasons; **zero `ski@v1`** | **Frozen verifier.** CI verifies it with `warrant-verify==0.9.0` (and with the unchanged Go binary). No migration, no re-signing. It never needed a Σ-GLYPH evaluator at all |
| **`examples/ski/`** (SPEC §8.2 vector) | 1 record, body `0.2`, one `ski@v1` reason | **Historical.** Stays as the `0.2`-era vector under the frozen release; the current path gets its own `1.0`/`ski@v2` vectors |
| **`demos/air-canada/`** | 2 records, body `0.2`, `ski@v1`; `replay.py` freezes exact `ski@v1 unverified: …` strings; CI already runs its replay against a **pinned wheel** | **Migrate** — it becomes the end-to-end scenario of §3. The frozen replay stays reproducible on 0.9.0 as the historical pack |
| **`demos/refund-chain/`** | 5 records, body `0.2`, `ski@v1` (`SKI = "ski@v1"`, `build.py:59`) | **Migrate** with the compiler change, or drop to a historical pack. Recommend migrate: it is one constant and one rebuild |
| **WPL / `ski_policy`** (`impl/policy_lang.py`, `impl/ski_policy.py`, `tools/gate.py`) | compile predicates to `{"ski":1,…}` and emit `runtime: "ski@v1"` in `0.2` bodies | **Migrate together.** One current writer; no opt-in flag, no dual emission |
| **MCP server, `integrations/approval`** | `runtime` enums `["cmd@v1","ski@v1"]` | **Migrate** the enums to `["cmd@v1","ski@v2"]` |
| **WRT-010 fact-provenance profile** (`impl/fact_provenance.py`) | binds sidecars to `ski@v1` reasons | **Migrate** to the current tag |
| **Settlement** (`fingerprint`, tunnel, `settle`) | `ski@v1` arm produces the 5-tuple | **Migrate**: the `ski@v2` tuple of WRT-013 §3.6 replaces it on the current path. The `ski@v1` arm goes with the v1 evaluator |
| **`oaip`** (live, external) | files real signed records through this repository's CLI/checkout; writes **`cmd@v1`**, treats `ski@v1` as reserved and never writes it (`impl/oaip.py:1312-1313`) | **Named dependency.** `cmd@v1` stays admitted in `1.0`, so oaip's *runtime* is unaffected; its *body version* moves when it adopts, and until then it pins `0.9.0`. Coordinate; do not break silently |
| **`manifesto`** (live, external) | already installs **`warrant-verify==0.9.0`** in CI and re-executes one stored `ski@v1` check there (`papers-deposit-check.yml:53-58`) | **No action.** It is already on the frozen-release model, and is the evidence that the model works |
| **Sigma-Glyph** | 53 records: 45 × `0.2`, 8 × `0.1`; 42 `cmd@v1` checks, 10 prose-only — and **exactly one `ski@v1` check**, whose WarrantID `14d413f2…a841ef` is a **genesis root** in both `.warrants/genesis.json` and `trust-config.json` | **Frozen verifier, permanently** (§2.1). Its everyday gates already pin Warrant by commit; what has to move is the one unpinned step |

### 2.1 Sigma-Glyph: the one record that settles this

Counted from its store, not assumed (and re-counted by me after the inventory
said so): of 53 records, **one** carries a `ski@v1` check —
`14d413f2952b5d5b7840a467b3154f12f2882dd939dfbe99fdf69524b4a841ef`, "Executable
law: TV-10 as a `ski@v1` reason". Its check blob is a real `{ski, term, atp,
expect}` triple, so it is re-executed rather than trusted.

That WarrantID is one of the three **genesis roots**, in `.warrants/genesis.json`
and in `trust-config.json` alike. A genesis root is inside the settlement closure
of every verification of that store, so it cannot be scoped out: **settlement
over Sigma-Glyph's store requires a `ski@v1`-capable verifier, for as long as
that store exists.** Re-filing the same claim under `ski@v2` would not help —
the old root stays in the closure — and re-signing history is forbidden.

This is not a blocker, because Sigma-Glyph is already on the frozen model
everywhere except one step:

- `ci.yml` pins `WARRANT_PIN: 0d147aa1…` and runs its settlement gate against
  that exact commit; `tools/test-all.sh` reads the same pin. Both keep working
  unchanged after the current path moves on.
- `impl-go` and `impl-rs` at `body-format/0.2` verify that store too.
- **`x1-cross-repo` is the exception.** Its B2 step runs Sigma-Glyph's store
  through **Warrant HEAD, deliberately unpinned** — that is the whole point of
  the canary. Once HEAD stops supporting `0.2`/`ski@v1`, B2 goes red, and it
  will be red for a reason that is not drift: the seam did not move, the
  supported set did.

So X1 needs a decision, and it is the only cross-repo change this amendment
forces:

1. **B2 verifies the historical store with the historical verifier** (the pin,
   or `warrant-verify==0.9.0`), and X1 keeps a HEAD-vs-HEAD step by giving it a
   **new subject**: a small `1.0`/`ski@v2` store built inside the gate. This
   keeps both properties — the old store stays verified, and HEAD is still
   crossed against HEAD.
2. Or B2 is retired and X1 covers only the current path, which drops the
   coupling check on the store that actually exists today.

I recommend (1), and it requires a coordinated change in `sigma-glyph` as well
as here — named, bounded, and not a return to a general compatibility matrix.

## 3. The one end-to-end scenario

A single scripted path, with no `ski@v1` evaluator loaded anywhere in it —
asserted by the absence of `sigma_glyph_v05` from `sys.modules`, not by reading
the code:

1. **Author.** A WPL source compiles to a `{"ski":2,…}` check blob against the
   0.6.0 evaluator, with its declared `exit`.
2. **File.** `warrant accept --runtime ski@v2 …` writes a body `1.0` record; the
   claim is re-executed at filing time and the filing is refused if it does not
   reproduce.
3. **Verify.** `verify` re-executes the reason, compares **exit and result**,
   and reports a mismatch as a WARN and an unexecuted claim as
   `ski@v2 unverified: <class>`.
4. **Fingerprint.** The §7 tuple of WRT-013 §3.6, with the re-run's `exit` and
   without `atp_spent`.
5. **Settle.** A second record citing a check whose re-run differs only in the
   exit is **admissible (b)**; one that reproduces an existing outcome is
   `inadmissible: cites nothing new`.
6. **Replay.** The record verifies from a clean install of the current wheel,
   offline, with the pinned evaluator inside it.

Step 6 is where `impl/sigma_glyph_v06.py` **joins `py-modules`**: under S2 it
was deliberately kept out of the wheel because no body version could invoke it
(`history/SKI-V2-EXECUTABLE-CANDIDATE-RETIREMENT.md`). `1.0` is that body
version, so the reason for keeping it out expires with this change — and the
same record removes `sigma_glyph_v05` from the wheel, so the shipped artifact
carries **one** evaluator, not two.

## 4. What actually disappears

Reduction measured in the executable system, not in section counts. Line counts
are of today's files.

| Removed from the current path | Size |
|---|---|
| `impl/sigma_glyph_v05.py` (ships only in ≤0.9.0 from then on) | 465 lines |
| `run_ski_check` v1 path + `validate_ski_blob` | ~66 lines |
| The two-table evaluator machinery (`SKI_EVALUATORS` + `DRAFT_SKI_EVALUATORS`, `load_sigma`/`load_draft_sigma`/`bundled_sigma_path`/`draft_sigma_path`) collapses to one table and one loader | ~105 lines → ~45 |
| `RUNTIMES`'s per-version tag table and the `0.1`-reserved special case | ~10 lines |
| `tests/ski_v2_draft_status.py` — the whole point of it was that the tag was inert | 230 lines |
| `ski@v1` expectations in `tests/ski_policy.py`, `tests/policy_lang.py`, `tests/sigma_cas_identity.py`, `tests/ski_runtime_evaluators.py`, `tests/fact_provenance.py` | rewritten to the one current tag, not duplicated per tag |
| `examples/ski/` §8.2 fixtures and the conformance pack's `ski-run` v1 vectors | move to the historical pack |
| The Go port that WRT-013 §5.2 required, and the Rust update of §8 S6 | never written |

Net: one evaluator in the wheel instead of two, one check-blob shape in the
validator instead of two, one runtime dispatch instead of a per-version table,
and one suite instead of the inertness/execution pair.

**Kept deliberately:** `cmd@v1` and every test of it; the digest-before-import
rule; the refusal classes; the fingerprint purity rules; `tests/negative.py`,
`tests/hostile.py`, `tests/settlement.py` retargeted rather than dropped.

## 5. The contract change, stated

Three edits to SPEC, in one change, with a document-version bump (this changes
verification outcomes between releases, so it is not a docs-only edit):

1. **§13.2 — a body version MAY admit a subset.** Today's policy reads as if
   each version adds to the last. State plainly: a new body version MAY admit
   fewer runtimes than its predecessor; the non-invalidation rule protects
   records *under their declared version*, and nothing more. Retire the `0.3`
   row as unused; add `1.0`.
2. **§6/§11 — supported-version declarations, and a distinct refusal.** A
   verifier MUST declare which body versions it supports. For a record whose
   declared version it does not support it MUST report a **stable, distinct**
   refusal that names a release which does verify it, MUST NOT validate it under
   another version's rules, and MUST NOT skip it silently. The capability string
   (`body-format/…`, §11, and the conformance probe) is where the declaration
   lives.
3. **§3.1/§3.2/§7/§13.1 — the tag tables.** `ski@v1` becomes *historical*: valid
   in `0.2`, admitted in no later version, with its evaluator named in the
   frozen release. `ski@v2` is registered in `1.0` with the blob shape, verdict,
   refusal classes and fingerprint tuple already drafted in §3.2, and §8 gains
   the `1.0` vectors.

**Adoption.** This is a specification change under the repository's normal
process: review, `CHANGELOG.md` record, and the §8 vectors in the same change.
It is not a threshold act, this document does not claim one, and the owner's
direction note is not one either. Where the amendment contradicts the accepted
WRT-013 text, the contradiction is resolved **here, before** any behaviour is
activated — which is why this document exists rather than a commit that quietly
changes direction.

## 6. What happens after this is reviewed

**One integration change**, in logical commits, not a new stage ladder:

- SPEC + schemas + `1.0` vectors;
- `RUNTIMES`/`ACCEPTED`/loader/validator/execution collapsed to the current path;
- fingerprint + settlement on `ski@v2`;
- authoring (WPL, `ski_policy`, MCP, approval, `gate.py`) moved together;
- demos rebuilt; historical packs pinned to `0.9.0`;
- the unsupported-version refusal, with its own tests;
- deletions from §4.

Re-review is for a substantive contract change or a found defect, not for each
internal function. Nothing is deleted from the working tree before this
amendment is reviewed.

## 7. Risks I am carrying deliberately

- **R1 — one implementation.** The current path will have no independent second
  implementation, so SPEC's "two implementations MUST agree" rule no longer
  covers it. The honest capability statement is: *Python 1.0 is the only
  verifier of the current path; Go and Rust verify `0.1`/`0.2`.* No cross-language
  agreement may be claimed for `ski@v2`, and none will be.
- **R2 — `oaip` writes through this CLI.** Its runtime (`cmd@v1`) survives, but
  its body version moves. If it is not coordinated, it either keeps filing
  `0.2` against a pinned `0.9.0` or breaks. Naming it here is the point.
- **R3 — the frozen release must stay installable.** The model rests on
  `warrant-verify==0.9.0` remaining on PyPI and runnable. That is a stated
  environment, not a lifetime guarantee, and the amendment says so rather than
  implying support.
- **R4 — `1.0` is a claim.** A major number invites "stable"; this one means
  "not a superset". §13.2's text has to say that, or the number will be read as
  a maturity promise nobody made.
- **R5 — X1 changes meaning.** Whichever option §2.1 takes, the canary no
  longer crosses HEAD against HEAD over the store that holds the project's own
  governance history. Option 1 restores the property with a synthetic subject,
  which is weaker evidence than the real store and should be described as such.
- **R6 — the §8.2 specimen is normative in the current SPEC.** Moving it to the
  historical pack means the current SPEC's §8 must carry `1.0` vectors of equal
  strength, or the new path ships with weaker pinned evidence than the old one.
