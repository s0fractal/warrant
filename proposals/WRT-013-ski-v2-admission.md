# WRT-013: Admitting `ski@v2` — Σ-GLYPH Book I 0.6.0 in body version `0.3`

**Status: DRAFT rev 1 (2026-09-17) — DESIGN ONLY.** No SPEC edit, no `impl/`
change, no vector change, no schema change is made by this document. It carries
no claim of adoption or implementation. Written by Claude Opus 5 at the owner's
request, under the plan in `~/Projects/CLAUDE-SIGMA-WARRANT-2026-09-17.md`
(stage 2). A gate verdict on it would be evidence, not adoption
(`AGENTS.md` rules 3–4).

**What it is for:** `ski@v2` is a reserved candidate (SPEC §3.2, §13.1) admitted
in no body version. SPEC §13.1 says a reserved row becomes a registration only
when **one** change supplies the tag's body versions, its re-execution
expectation and budget unit, its §7 outcome-fingerprint tuple, its ruleset
pinning rule and a normative negative vector set. This document is the design
for that one change, written before any of it is implemented, so the contract is
reviewed rather than inferred from a diff.

**Scope boundary.** Continuation / resumable reduction is **not** here. It is
stage 3 and needs its own pressure case; nothing below reserves a field, a tag
or a body version for it.

---

## 1. Why now

- **WRT-006** closed with disposition **B**: Book I 0.6.0 gets a new tag,
  `ski@v2`, because SPEC §3.1/§13.1 make `ski@v1` mean Book I v0.5 permanently.
  That settled the *name* and left the *admission* unwritten.
- **WRT-007** (per-tag evaluator selection) closed **deferred**; its retained
  design evidence — digest-before-import, one evaluator per tag, `active` vs
  inert `candidate` — is already implemented for `ski@v1` in `SKI_EVALUATORS`
  (`impl/warrant.py:438`) and `trust/ski-runtime-evaluators.json`.
- `history/SKI-V2-EXECUTABLE-CANDIDATE-RETIREMENT.md` withdrew the candidate
  evaluator bytes and states the condition this document meets: *"a future body
  0.3 must bring its evaluator, negative vectors, fingerprint tuple and
  admission rule in one explicit act."*
- **New since those documents:** Σ-GLYPH **0.7.0 is published** (PyPI, 2026-09-17,
  from tag `v0.7.0` / commit `9d10bbc`). The Book I 0.6.0 evaluator is now a
  released artifact with a read-back digest, not a tree state. That changes the
  *supply* story `ski@v1` had to settle for: `ski@v1`'s provenance note points at
  a wheel published after the fact, whereas `ski@v2` can pin bytes that were
  published, digest-compared against the building workflow's own artifact, and
  replayed from a clean install before the tag is registered.

## 2. What was measured (2026-09-17, this machine)

Two evaluators: `impl/sigma_glyph_v05.py` (`80299d68…`, the pinned `ski@v1`
engine) and the `sigma_glyph.py` inside PyPI `sigma-glyph==0.7.0`
(`f4d9990d…`), installed from the index into a clean venv.

| # | Measurement | Result |
|---|---|---|
| M1 | §8.2 specimen (`examples/ski/check.json`) on both engines | identical: `887045bc…` (H(S)), 20 ATP, verdict `pass`; v2 additionally reports `exit=normal_form` |
| M2 | same term at atp 0/1/5/19/20/21 | identical result hash and spend at every budget; v2 adds `exit` (`atp_exhausted` below 20, `normal_form` at/above) |
| M3 | the 33 `eval` vectors of the anchored Book I 0.6.0 suite (`vectors.json`, v0.7.0 bundle) | **33/33 agree** on `(result_hash, atp_spent)`; 0 divergences |
| M4 | bytes stored under a key they do not hash to | v0.5 engine **evaluates them** and returns a normal form (`8785b7dd…`, spent 1); Book I 0.6.0 engine **refuses**: `ResourceFault: CAS key mismatch` |
| M5 | one result hash, one spend, two exits | reproduced: `result 8bb0006f…`, `atp_spent 9` — §8.2 term at atp 9 (`atp_exhausted`) vs `APPLY(I,·)²` over the stored `DISSONANCE("ATP Exhausted")` node at atp 9 (`normal_form`) |
| M6 | Book I 0.6.0 admission limits | `DEFAULT_LIMITS.max_atp = None`; `VERIFIER_LIMITS.max_atp = 10_000_000`; over-limit raises `AdmissionRefused` **before execution** — while Warrant's own documented budget is `100_000_000` (`impl/warrant.py:37`) |

Reproduce: `proposals/wrt-013-model/engine_differential.py <sigma_glyph.py>`
(M1–M2) and `proposals/wrt-013-model/exit_collision.py <sigma_glyph.py>` (M5).
M3 replays the sibling's anchored suite; M4/M6 are four lines against each
module.

**What M3 and M5 together mean.** The two engines are not in dispute about any
value `ski@v1` can express — so `ski@v2` is not a bug fix, and no existing record
is wrong. What Book I 0.6.0 adds is an **observable that v0.5 does not have**:
the exit. M5 shows that observable is load-bearing rather than cosmetic: a
finished computation and an unfinished one can agree on the result hash *and* on
the spend. Every field of the §7 `ski@v1` fingerprint is identical across that
pair. Only `exit` separates them.

**What M4 means.** The refusal of foreign-keyed bytes moves from a Warrant-side
adapter guard (`run_ski_check`'s `BlobCAS`, added after the CAS-identity
finding) into the engine itself. Under `ski@v2` both boundaries hold; the design
keeps the adapter check anyway, because a defence that only one layer performs
is one edit from being performed by nobody.

## 3. The contract

### 3.1 Check blob (normative shape)

```json
{ "ski": 2, "term": "<hex64>", "atp": <uint32>, "expect": "<hex64>", "exit": "<canonical exit>" }
```

I-JSON, JCS-canonical, integers only, hashed like any blob — as `ski@v1`. The
member set is **exactly** these five; an unknown or missing member makes the
blob invalid (not a `fail`). `"ski"` MUST be `2`; a `"ski": 1` document is a
`ski@v1` blob and MUST NOT be executed under `ski@v2`, and the converse.
`exit` ∈ `{"normal_form", "atp_exhausted", "unresolved_reference"}` — the three
canonical exits of Book I 0.6.0 §3.4, and nothing else.

*Why `exit` is in the blob rather than derived.* M5: without it the reason's
claim is not a proposition about the computation, only about its last node. A
reason that cannot state "and it finished" cannot be checked for having
finished.

*Rejected alternative — a receipt digest* (`expect_receipt = SHA-256(JCS({exit,
result_hash, atp_spent}))`). It binds `atp_spent` into the claim, which makes
every check brittle against a budget change that does not change the outcome,
and it makes a failed check unreadable: a verifier could say only "the receipt
digest differs", not which field. Rejected for legibility, not for safety.

### 3.2 Evaluation

1. Evaluate `eval(term_hash, atp, content environment)` per **Σ-GLYPH Book I
   0.6.0** — the anchored `v0.7.0` bundle, adoption warrant `0e634c17…` —
   obtaining `Receipt = {exit, result_hash, atp_spent}`. As with `ski@v1`, the
   URL is not the trust anchor: the implementation pins the ruleset by the
   digest of the evaluator bytes it ships (§3.4 below).
2. The content environment IS the Warrant blob store, exactly as in §3.1 of the
   SPEC. Book I 0.6.0 §3.5 applies: bytes stored under a key they do not hash to
   are **refused, never evaluated** (M4). Warrant's adapter enforces the same
   rule independently; both normalise to `REASON_CAS_MISMATCH` ("content does
   not match its address").
3. Σ-GLYPH genesis axioms are intrinsic and need no blobs.

### 3.3 Verdict mapping

> `pass` **iff** `receipt.exit == blob.exit` **and** `receipt.result_hash == blob.expect`.
> Otherwise `fail`.

`atp_spent` is **not** part of the verdict. It is reported, never compared: a
claim about the budget actually consumed is a different proposition, and binding
it would make an honest check fail for a reason its author never asserted.

**Local outcomes are never verdicts.** Each of the following makes the reason
`ski@v2 unverified: <reason class>` — a WARN in base verification, an ERR under
settlement-grade verification when the reason participates in a settlement-active
record (SPEC §6(7), unchanged). None of them is `pass` or `fail`, and none is a
silent skip:

| Condition | Reason class |
|---|---|
| check blob absent from the store | `check blob missing` |
| check blob not at its content address | `content does not match its address` |
| not JSON / not JCS-canonical / wrong member set / `ski != 2` / bad `exit` | `invalid ski check blob: …` |
| `atp` above the verifier's re-execution budget | `atp exceeds re-execution budget` |
| engine raises `AdmissionRefused` | `admission refused` |
| engine raises `ResourceFault` (depth, materialization, store fetches) | `resource fault: …` |
| foreign-keyed bytes at any fetch (engine or adapter) | `content does not match its address` |
| no evaluator for the tag, or bundled bytes fail their digest | `runtime unavailable` |
| `$SIGMA_GLYPH` override byte-divergent from the pinned evaluator | `unpinned Σ-GLYPH evaluator (non-settlement-grade)` |

`AdmissionRefused` and `ResourceFault` are Book I's *local, non-canonical*
boundary (0.6.0 §3.6). Turning either into a canonical verdict would let a
verifier's own configuration decide a warrant's content — the failure §3.1
already forbids for the budget ceiling, generalised.

### 3.4 Evaluator binding (SPEC §3.1 "one evaluator per tag")

`SKI_EVALUATORS["ski@v2"] = ("sigma_glyph_v06.py", "f4d9990d40f07c8cfd3aa105…3feb4")`,
mirrored in `trust/ski-runtime-evaluators.json` with provenance:

| Field | Value |
|---|---|
| module bytes (sha256) | `f4d9990d40f07c8cfd3aa10512c2195a0a04e8dc78bc955c0f53dfe737d3feb4` |
| semantics | Σ-GLYPH Book I 0.6.0, anchored bundle `v0.7.0`, adoption warrant `0e634c17…` |
| source repository / tag / commit | `s0fractal/sigma-glyph`, `v0.7.0`, `9d10bbc2e92fdc394b488dc381e9b2a0942b7ea5` |
| published distribution | `sigma-glyph` 0.7.0; wheel `c9ee47687cfed43c7abb2764e4c8f4d885dd8be4975d0cc8b5e8dc8ee7d6276a`, sdist `5ad36077…bcf8` |
| relationship | the module inside that wheel, byte-identical to `impl/sigma_glyph.py` at the tag (read back from PyPI 2026-09-17) |

Rules, all already implemented for `ski@v1` and extended per-tag rather than
rewritten: digest checked **before** import; a moved module is never executed;
an unregistered tag returns no evaluator; **no fallback from one tag's evaluator
to another's**. Vendoring is deliberate (offline replay); the provenance record
is what makes the vendored copy identifiable, and it now names a *published*
artifact.

One defect this surfaces: the settlement preflight calls `load_sigma()` with the
default tag (`impl/warrant.py:1419`), so with two admitted tags it would pin the
wrong engine. It must become per-tag, and settlement must refuse if **any** tag
a settlement-active record uses is unpinned.

### 3.5 Budget

Warrant's `SKI_REEXEC_MAX_ATP` (default `100_000_000`, env-overridable) stays the
single admission gate, checked against `blob.atp` **before** the evaluator is
loaded, as today. The evaluator is additionally called with limits whose
`max_atp` equals that same budget, so the engine's admission and Warrant's agree
by construction. Book I's own `VERIFIER_LIMITS.max_atp` is `10_000_000` (M6):
passing it unchanged would silently give Warrant a tenth of the budget it
documents. Implementations MUST NOT inherit the sibling's default here.

### 3.6 Outcome fingerprint (SPEC §7, required by §13.1)

> `ski@v2` — `{runtime, term, expect, expect_exit, verdict, result_node_hash, exit}`
> where `verdict`, `result_node_hash` and `exit` are the **re-run's**, never the
> filer's claim.

Compared with `ski@v1`'s `{runtime, term, expect, verdict, result_node_hash}`,
two members are added: the claimed `expect_exit` (part of the claim's identity,
like `expect`) and the re-run's `exit`.

- **`atp_spent` is deliberately excluded.** Including it would make novelty
  reachable by editing one integer: file the same term with `atp` 5, then 6,
  then 7 — each exhausts at a different spend, each is a "new outcome", and
  settlement re-opens without limit. This is the §7 hazard WRT-005 exists
  around, and it must not be re-introduced through a new tag.
- **`exit` is included, and the novelty surface it adds is bounded.** For a
  fixed `(term, expect_exit, expect)` the exit takes at most three values, so
  the fingerprint set grows by a factor of at most 3 — and each of those three
  is a genuinely different fact about the computation (it finished / it ran out
  / it demanded an object that is not there). M5 is the case that forces it: two
  computations that a v1-shaped tuple cannot tell apart.
- The `ski@v1` tuple is **unchanged**, and a `ski@v1` reason's fingerprint under
  a store containing `ski@v2` records is bit-identical to what it is today.
  Fingerprints of different runtimes never compare equal — the tag is the first
  member.
- WRT-005 (fingerprint purity, DRAFT, not adopted) would, if adopted, restrict
  which *result normal forms* may bear a fingerprint at all. Its rule is stated
  per-tag; nothing here presumes its adoption, and nothing here blocks it.

## 4. Body version `0.3`

| Value | Admits | Rejects |
|---|---|---|
| `0.1` | `cmd@v1` | `ski@v1` (reserved), `ski@v2` (reserved) |
| `0.2` | `cmd@v1`, `ski@v1` | `ski@v2` (reserved) |
| **`0.3`** | `cmd@v1`, `ski@v1`, **`ski@v2`** | anything unregistered |

- A `0.3` body is otherwise the `0.2` body: **no field is added, removed or
  re-typed**, so every `0.1`/`0.2` record stays valid, keeps its WarrantID and
  its verification result (SPEC §13.2's non-invalidation rule).
- `ski@v1` remains admitted in `0.3`. A store may mix tags; a filer who does not
  need the exit keeps writing `ski@v1` reasons in `0.2` bodies, and nothing
  reinterprets them.
- **The version written into NEW records stays `0.2`** (`VERSION`,
  `impl/warrant.py:26`). A record is filed as `0.3` only when it actually
  carries a `ski@v2` reason (or when an author asks for it explicitly). Raising
  the default would make every new record unverifiable by conforming verifiers
  that have not yet implemented `0.3` — a cost with no benefit to a record that
  uses nothing from it.
- **Namespace warning for implementers.** `warrant_policy: "0.3"` already exists
  (threshold-policy blobs, `impl/warrant.py:1089`) and is unrelated. Two
  different `"0.3"`s will sit in the same tree; neither may be checked against
  the other's field.

## 5. Compatibility matrix

Support classes: **EXEC** = re-executes the tag and can reach `pass`/`fail`;
**REFUSE** = does not execute, and says so per reason in a way a consumer can
see (`<tag> unverified: runtime unavailable`); **INVALID** = the record is
schema-invalid here; **SILENT** = the defect class this design forbids: the
reason is neither executed nor reported.

| Body → | `0.1` | `0.2` | `0.3` (proposed) | |
|---|---|---|---|---|
| **Python** (`impl/warrant.py`) | cmd EXEC · ski@v1 INVALID · ski@v2 INVALID | cmd EXEC · ski@v1 EXEC · ski@v2 INVALID | cmd EXEC · ski@v1 EXEC · **ski@v2 EXEC** | settlement grade |
| **Go** (`impl-go`) | same | same | **ski@v2 EXEC required** — a second Book I rule set, or REFUSE declared | settlement grade today |
| **Rust** (`impl-rs`) | same | cmd EXEC · ski@v1 **REFUSE** | cmd EXEC · ski@v1 REFUSE · **ski@v2 REFUSE** | base grade by design |
| **Conformance pack** | `validate` vectors | `validate`, `ski-run` | new `validate` + `ski-run-v2` vectors, pack version bump | |

**Honest capability declaration is part of the admission, not a follow-up.** A
verifier that cannot execute `ski@v2` MUST still (a) treat a `0.3` body as
schema-valid if it claims to support `0.3`, and (b) report every `ski@v2` reason
as unverified. A verifier that does not support `0.3` at all rejects the body —
which is also conformant, and is what `impl-rs` may choose.

### 5.1 Where the current code would go SILENT (verified by reading it)

These are not hypotheses; each was read at the line given. Every one must be
fixed **in the admission change**, or `ski@v2` is worse than unimplemented — it
is invisible.

| Site | Today | Consequence for an admitted `ski@v2` |
|---|---|---|
| `impl-go/main.go:3006` | base verify filter `r["runtime"] != "ski@v1"` → `continue` | reason never re-executed, **no finding at all** |
| `impl-go/main.go:2728` | settlement verify filter, same shape | an unexecuted claim settles silently |
| `impl-go/main.go:1927` | `fingerprint`'s `switch runtime` `default: return "", false` | `ski@v2` contributes **no** §7 fingerprint → re-litigation is silently inadmissible |
| `impl-rs/src/main.rs:1060` | counts only `Some("ski@v1")` | `ski@v2` reasons produce no WARN — the exact "must not look like it ran" property the comment above it asserts |
| `impl-go/main.go:721-726` | admission is an inline boolean, no table; error text `runtime must be cmd@v1` is already stale for `0.2` | a third tag is unreadable here without restructuring |
| `impl/warrant.py:1419` | settlement pin uses `load_sigma()` (default tag) | pins the wrong engine once two tags exist |
| `impl/warrant.py:2355`, `impl/warrant_mcp_server.py:190` | `--runtime` / MCP enum `["cmd@v1","ski@v1"]` | a `ski@v2` reason cannot be filed by the reference tools |
| `impl-go/probe.go:30`, `impl-rs/src/probe.rs:19` | one `ski-run` class, no runtime selector; `version: "body-format/0.2"` | the conformance pack cannot ask "run this as v2" |

Python is the least exposed: `RUNTIMES` is a real table (`impl/warrant.py:40`)
and `load_sigma(tag)` is already per-tag. Its filters are still literal
`== "ski@v1"` (`:1657`, `:1967`, `:951`) and change with the same discipline.

## 6. Negative vector set (SPEC §13.1 requirement, §8.3 battery)

Every case below MUST be rejected or reported unverified — never `pass`, never
`fail`, never silence. This list is the design's answer to "a normative negative
vector set"; the vectors themselves are part of the implementing change.

*Schema / admission*
1. `ski@v2` reason in a `0.1` body → invalid (reserved).
2. `ski@v2` reason in a `0.2` body → invalid (reserved) — the case today's
   `reject-07-unknown-runtime` (`wasm@v1`) covers only by analogy.
3. `warrant: "0.3"` in an implementation that does not support it → invalid,
   with the version error. **There is no such vector today for any future
   version**; the gap is real and this change closes it.
4. `ski@v1` reason in a `0.3` body → **valid** (positive control against
   over-rejection).
5. Unknown runtime `ski@v3` in a `0.3` body → invalid.

*Check blob*
6. `{"ski":1,…}` blob referenced by a `ski@v2` reason → unverified (wrong blob
   version), and the mirror: a `ski@v2` blob under a `ski@v1` reason.
7. Missing `exit` member; unknown member; `exit: "dissonance"`; `exit: null`.
8. Non-JCS-canonical bytes; duplicate member; trailing content.
9. `atp` = `2**32`, `-1`, `1.0`, `true` → invalid blob.
10. Check blob stored under a foreign name → `content does not match its address`.

*Execution*
11. Term whose demanded object is absent → `exit=unresolved_reference`; a claim
    of `normal_form` with the same result hash → `fail`, not `pass`.
12. **M5's pair**: claim `{expect=8bb0006f…, exit=normal_form}` filed for the
    exhausting run → `fail` under `ski@v2`, while the same claim shaped as
    `ski@v1` is `pass`. This is the vector that proves the tag does something.
13. A term thunk stored under a foreign key → `content does not match its
    address`, from the engine and from the adapter independently.
14. `atp` above the local budget → `atp exceeds re-execution budget` (unverified),
    engine never loaded.
15. Evaluator bytes moved by one byte → refused before import; reason unverified.
16. `$SIGMA_GLYPH` pointing at a byte-divergent module → unverified; and
    settlement refuses globally.

*Settlement*
17. Re-litigation citing a `ski@v2` check whose re-run reproduces an existing
    tunnel fingerprint → `inadmissible: cites nothing new`.
18. Re-litigation differing only in `atp` (and therefore in `atp_spent`) with the
    same result and exit → **inadmissible** (the §3.6 exclusion, tested).
19. Re-litigation whose re-run differs only in `exit` → admissible (b), and the
    `ski@v1` twin of the same store remains inadmissible — the two tags'
    fingerprints must not collide.
20. A `ski@v1` record's fingerprint, computed in a store that also contains
    `ski@v2` records, is byte-identical to its value before this change.

*Replay of the old*
21. `examples/ski/` (the §8.2 specimen) re-runs to `pass`, `887045bc…`, exactly
    20 ATP, under the **unchanged** `ski@v1` evaluator, with `ski@v2` admitted.
22. `demos/air-canada/replay.json` — which freezes the `ski@v1` evaluator record
    and the exact unverified strings — replays unchanged.

## 7. What the admission act consists of

SPEC §13.1/§13.2 require these in **one** change; listing them is also the
answer to "how big is this":

1. **SPEC**: §3.2 rewritten from reservation to registration (blob shape,
   evaluation, verdict, local-fault rules); §7 gains the `ski@v2` fingerprint
   tuple; §13.1 row moves to *current* with its body versions; §13.2's `0.3` row
   is completed; §8 gains the `0.3`/`ski@v2` vectors. A document-version bump:
   this is a consensus-behaviour change (two verifiers at different revisions
   disagree about whether a `0.3` record is valid).
2. **Schemas**: `warrant-body.schema.json` version enum, runtime enum, and the
   per-version conditional; the ski **blob** has no schema today — the `ski@v2`
   blob SHOULD get one rather than living only in code.
3. **Python**: `RUNTIMES`, `_CORE_RUNTIMES`, `SKI_EVALUATORS` + vendored module,
   `validate_ski_blob` per version, `run_ski_check` on `eval_receipt`,
   `fingerprint`, both verify loops, settlement per-tag pin, CLI/MCP enums,
   filing-time re-run, `conformance()`.
4. **Go**: the admission table, a Book I 0.6.0 rule set (or a declared REFUSE),
   fingerprint arm, both filters, probe class/capability.
5. **Rust**: admission list, reserved rule, and the honest-reporting filter.
6. **Conformance pack**: new vectors, `ski-run` input gains a runtime selector,
   `PACK_VERSION` bump, `MANIFEST.sha256`, and the frozen copy under
   `needs/need-002-a3-base/operands/` left alone as the historical operand.
7. **Records**: `trust/ski-runtime-evaluators.json` row;
   `tests/ski_runtime_evaluators.py:56` currently asserts *"reserved `ski@v2`
   has no shipped evaluator"* — that assertion inverts, and its inversion is
   itself part of the act.

**Readiness is not admission.** Code and green CI do not register a tag; the
specification act does, and this document is not it.

## 8. Implementation staging (proposed, after design review)

Each stage is separately reviewable and separately revertable:

- **S1** — SPEC + schemas + vectors, no runtime code. The registration itself.
- **S2** — Python: evaluator binding, blob validation, execution, verdict.
- **S3** — Python: fingerprint, settlement per-tag pin, re-litigation vectors.
- **S4** — Python authoring: CLI/MCP, filing-time re-run, WPL/`ski_policy`
  decision (see open question Q3).
- **S5** — Go: table, engine or declared refusal, fingerprint, filters, probe.
- **S6** — Rust: admission + honest reporting.
- **S7** — conformance pack version bump and cross-implementation run.

S5 is the largest and the one that may return "REFUSE" rather than "EXEC"; that
choice is a reviewable outcome, not a failure, provided it is declared.

## 9. Open questions for the reviewer

- **Q1.** `exit` as a fifth blob member (§3.1) versus a receipt digest. I chose
  legibility; a reviewer who weighs "one comparison, one field" differently
  should say so now, because the blob shape is the one thing that cannot be
  changed after registration.
- **Q2.** Should `0.3` admit `ski@v1`? Admitting it keeps one body version able
  to carry both tags; refusing it would force a store to split by version. I
  chose admit.
- **Q3.** Should WPL / `ski_policy` (which compile Church-boolean predicates)
  emit `ski@v2` by default once admitted? Their terms evaluate identically on
  both engines (M3), so the only gain is the exit observable, and the cost is
  that every emitted check becomes unverifiable to a `0.2`-only verifier. My
  inclination: keep emitting `ski@v1` by default, add an opt-in flag, revisit
  when a second implementation executes `ski@v2`.
- **Q4.** Go: implement a second Book I rule set, or declare REFUSE for
  `ski@v2` and lose cross-implementation execution parity for the new tag? A
  declared refusal is honest but makes `ski@v2` a single-implementation runtime,
  which is precisely what the SPEC's "two independent implementations MUST
  agree" design rule exists to prevent.
- **Q5.** Is there a pressure case that needs `ski@v2` *records* now, or is the
  motivation the semantics (M5) plus the supply (published 0.7.0)? I did not
  find an application in `needs/` demanding it; the honest statement is that
  this is a protocol-completeness change with a demonstrated semantic gap, not a
  user-driven one. If the reviewer thinks that is insufficient grounds, the
  answer is to defer admission and keep the reservation — which costs nothing.

## 10. What this document does not do

It does not edit the SPEC, register a tag, define body `0.3` normatively, ship
or vendor an evaluator, change any implementation, add a vector, or claim a
review. It does not touch `ski@v1`'s bytes, semantics, fingerprint or records,
and it introduces no continuation, checkpoint or resume surface.
