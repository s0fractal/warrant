# WRT-004: Reason-binding profile — closing the justification-binding gap

**Status:** DRAFT rev 2 (2026-08-28) — **design only.** No SPEC edit, no body
schema change, no code change to `warrant verify` is made by this document.
The profile is an *additive blob* cited in `evidence`; base and settlement
verification are untouched until a future SPEC revision adopts a
profile-checking grade. Adoption requires an adversarial gate.

**Provenance.** The gap this closes — NG-7, the *justification-binding gap* —
was the central finding of the first whole-paper review
(`reviews/2026-08-monday.md`, 2026-08-28, Major Revision), which observed that
the format proves a `ski@v1` term re-executes to its declared result but never
that the term *is* the pinned policy over the cited evidence yielding a result
consistent with the decision. That review's Q4 asked for exactly this profile.

**Not prose-only.** Per this repository's discipline, the proposal ships with a
running demonstration rather than a promise:
`tools/reason_binding_check.py` implements the three checks below, and
`tests/fixtures/wrt004_reason_binding.py` shows the gap attack and each layer's
negative control turning red for its own layer (5/5).

## 1. The gap (reproduced)

A `ski@v1` reason names a check `{term, atp, expect}`. Base verification
re-runs `term` and compares the result hash to `expect`; a match is `pass`.
Nothing requires `term` to consume the policy in `under`, the `subject`, or the
`evidence`, nor to entail `body.decision`. The demonstration files the attack:
a term that **is** the expected result node — a constant — reproduces `expect`
trivially and verifies at base grade, while encoding nothing of any policy. A
verifier confirms every cryptographic and computational fact; no semantic
thread connects policy, evidence, and decision. Today the only thing narrowing
this is a WPL authoring *convention* (pin the source as evidence; recompile),
not a verifier-checkable invariant.

## 2. The profile

A blob, cited in the record's `evidence` like any other, addressed by
`SHA-256(bytes)`, JCS-canonical, integers-only:

```json
{ "profile": "warrant.reason-binding@v0",
  "check":         "<hex64 the ski@v1 check blob the reason cites>",
  "policy_source": "<hex64 the WPL source blob>",
  "fact_manifest": { "<fact name>": "<hex64 fact-evidence blob>", ... },
  "decision_map":  { "true": "<decision>", "false": "<decision>" } }
```

A profile-aware verifier, for a `ski@v1` reason whose `check` equals
`profile.check`, checks four layers and reports the reason **bound** or
**unbound** (a report, like §5.1 key binding — not a base-grade error unless a
future SPEC grade makes bound reasons required):

- **L0 — the profile is committed (rev 2, Codex round).** The profile blob
  MUST resolve, MUST be JCS-canonical, and its own hash MUST appear in the
  record's `evidence`. A profile a verifier is handed out of band, or one the
  record does not cite, binds nothing — it is post-hoc paper the base verifier
  never sees. rev 1 checked the profile's *contents* while trusting that the
  profile itself was part of the record; a reviewer's repro filed a perverse,
  uncommitted profile and got `BOUND`. L0 closes that: nothing is bound unless
  the binding is itself content-addressed into the record.
- **L1 — term ↔ policy.** Recompile the WPL `policy_source` deterministically;
  the compiled term and result must equal the check's `term` and `expect`. This
  is what proves *the term encodes this exact policy* (Monday Q1: yes, under
  this profile). Compilation is reproducible (SA-11), so this is a pure
  function of the source bytes.
- **L2 — facts ↔ evidence.** WPL bakes each `fact` into the term as a constant
  (SA-11). The manifest must name every fact of the source and no other; each
  named blob must contain exactly `{fact, type, value}` for that fact and must
  appear in the record's `evidence`; `policy_source` must appear in `evidence`
  too. This binds each baked-in constant to a *named, hash-pinned, independently
  citable evidence item* instead of a number the compiler invented (Monday Q2:
  partially — bound to an evidence item, see §4).
- **L3 — result ↔ decision.** The re-run result (Church TRUE/FALSE) maps under
  `decision_map` to a decision that must equal `body.decision`. This is the
  first normative relation between `body.decision` and a computation result
  (Monday Q3: yes, under this profile).

## 3. Why a blob, not a body field

The body schema is closed and versioned; adding a field is a breaking change
(SPEC §2). A profile blob in `evidence` is additive and non-breaking: a
v0.1/v0.2 verifier ignores it, a profile-aware verifier resolves and checks it,
and no WarrantID moves. This mirrors how every other machine-readable document
in this project (verify-report, canon-vectors, evidence-pack) is a tagged blob,
not a body field. A future SPEC revision may define a **profile grade** that
requires a resolvable, satisfied binding profile for reasons that claim to be
policy justifications — at which point an unbound reason claiming to justify a
decision becomes an error, not a report.

## 4. What this does NOT establish (the honest limits)

The whole point of NG-7 was that the paper let "reason" imply more than the
format proved; this profile must not repeat that at one remove. It closes the
*binding*, not the *truth*:

- **It does not prove a fact is true.** SA-11 stands unchanged: a fact-evidence
  blob is an assertion by whoever wrote it. L2 binds fact → evidence *item*,
  never fact → reality. What it removes is the *inline invented constant*: a
  disputant can now point at the exact evidence blob a fact rests on and file a
  counter-warrant against it. That is the format's dispute mechanism working as
  designed, not a truth oracle.
- **It does not prove the policy is a good policy.** NG-4 stands: Warrant pins
  which rules were in force and takes no view on whether they were right. A
  policy that says `check true` (permit everything) binds perfectly and
  authorizes everything; the profile proves the term is that policy, not that
  the policy is sound.
- **Subject binding is the weakest layer and is deliberately partial.** The
  profile can require `subject.hash ∈ evidence`, but "these facts *describe*
  this subject" is not mechanically provable — the facts are asserted
  properties. rev 1 does not claim subject-semantic binding; it is named here as
  the open edge, and a future revision may add a subject→fact derivation
  requirement if one can be made checkable without a filer-steerable trace (the
  hazard WRT-003 spent four revisions learning).
- **It is WPL-specific.** L1/L2 assume the reason is a WPL compilation. A
  hand-written ski term with no WPL source cannot be bound by this profile; it
  simply is not eligible for the profile grade, and a record may say so. A
  different reason language would need its own `@vN` binding profile under the
  §13.1 registry rule.

**Name the guarantee honestly (rev 2, Codex round): this is a
*declaration-coherence* profile, not a reason-binding *proof*.** With a
satisfied, committed `reason-binding@v0` profile, a verifier can confirm that a
reason's computation is the compilation of the pinned policy over facts
committed as cited evidence, and that its result is consistent with the
recorded decision under a committed map. It does *not* prove that the map is
the right map (a self-consistent but perverse map, `false → accept`, is
coherent under itself — the profile makes it committed and disputable, not
correct), that the facts are true (SA-11), or that the policy is sound (NG-4).
The philosophically correct next boundary — who may define decision semantics,
how facts relate to the subject and to reality, and what "this policy permits
this decision" means — is authorization, not coherence, and is exactly the
question WRT-004 leaves for a human logician (§6.1, §6.4).

## 5. Acceptance criteria (for the gate)

1. **The gap attack as a negative control** (already in the fixture): a
   constant-equivalent term that reproduces `expect` verifies at base grade and
   is reported **unbound** by L1; removing L1 makes it bind.
2. **One negative per layer** (already in the fixture), each turning red *for
   its own layer* — an L2 mutation must not fail at L1, etc.
3. **L0 negatives (rev 2):** a profile the record does not cite in `evidence`,
   and a profile whose bytes are not JCS-canonical, each report **unbound** —
   so a post-hoc or malformed profile binds nothing. Both are in the fixture.
4. **A positive** that binds fully, so the profile is not "reject everything".
4. **Determinism / cross-implementation:** L1 depends on the WPL compiler being
   a deterministic function of the source (as `ski@v1` identity depends on
   evaluator determinism, WRT-003 §3.6). Two implementations of the profile
   MUST agree on bound/unbound for every vector; the compiler's determinism is
   the precondition, and a second-implementation compiler is the real test —
   noted as the same unmet independence gap the rest of the project has.
5. **Registry:** `warrant.reason-binding@v0` registers under §13.3 as a
   closed-schema document tag; any additive change is a new tag.

## 6. Open questions for the gate

1. Should `decision_map` be fixed (`{true: accept, false: reject}`) rather than
   filer-declared? A filer-declared map is committed and checkable, but a
   perverse map (`{false: accept}`) binds a false policy result to an accept.
   Draft answer: allow the map but require it be *stated*, so the perversity is
   on the record and disputable; a profile grade MAY additionally pin the
   canonical map. The gate should decide.
2. Is L2's fact-evidence blob shape (`{fact, type, value}`) the right
   granularity, or should a fact reference a *sub-field of a larger evidence
   document* (e.g. one JSON evidence blob with many fields)? rev 1 takes the
   simplest shape; a document-plus-pointer form is a candidate rev-2 extension.
3. Does binding interact with settlement (WRT-003)? A bound reason is a stronger
   §7(b) consequence than an unbound one, but WRT-003's fingerprint is the
   result value alone and does not read the profile. Draft answer: keep them
   orthogonal — binding is about *what a reason means*, settlement about
   *whether a result is new* — but the gate should confirm no interaction was
   missed.
4. Subject binding (§4): can a checkable subject→fact derivation be defined at
   all, or is subject-description permanently a residual? This is the one place
   a human logician would help most.
