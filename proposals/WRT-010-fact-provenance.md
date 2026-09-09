# WRT-010: Fact provenance — derived facts, and the chain of decisions

**Identifier resolution (operator-authorized editorial change, 2026-09-09).**
This proposal is **WRT-010**. **WRT-008** remains the *fact derivation profile*
in [PR #60](https://github.com/s0fractal/warrant/pull/60), whose document is
**CLOSED — DEFERRED**; the PR itself remains open. Its retained disposition is
pinned at `6360f83e3dce16b780a8c4ce9b713f15b8b6ffb3:proposals/WRT-008-fact-derivation-profile.md`.
**WRT-009** is already reserved for the deployment-predicate proposal in
`reviews/2026-09-chatgpt-web-cross-stack-response.md`; this change does not
allocate that number again.

**Relation: follows up WRT-008, without replacing its disposition.** This
workline was originally presented as a reactivation attempt under the same
number. It now has a distinct identifier because it has a different profile
(`warrant.fact-provenance@v0`), WPL authoring clause and implementation. The
old extractor model and measurement remain WRT-008's evidence. Fixing analogous
record-address defects here does not retroactively repair or adopt that model.

| Earlier WRT-008 residual | Corresponding protection in this implementation |
|---|---|
| Null/missing body received citation credit | `_record_at` refuses it; `check_record` reports INCOMPLETE |
| Filename was trusted as WarrantID | `_record_at` recomputes the body address before credit, including citation-walk intermediates |

The five technical review rounds keep their original labels and exact commits.
The bounded ACCEPT is for `848d103efda349bd46fa4273d7996c32ffdc1687`, documented
below; renumbering neither upgrades that scope nor constitutes adoption.
Historical WRT-008 labels in those reviews and frozen demo WPL comments denote
this workline at their pinned revisions, not a second current allocation.

**Governance note (owner decision, 2026-09-09).** WRT-007 §6's stopping rule
closes a proposal as deferred on a second AMEND on the same layer, and rounds 1
and 2 were both on the binding layer. The owner's call was to continue, on the
ground that two AMENDs is a low bar for a hard change and a rule applied by
count alone selects for cosmetic work. This revision takes that as a condition,
not a licence: the rule's *purpose* is to stop ad-hoc patching, so rev 4 answers
it by changing method rather than by patching again. `proposals/wrt-010-model/BINDING-EDGES.md`
enumerates every aboutness claim the profile relies on and what checks each. If
that enumeration itself returns AMEND, the proposal defers without argument.

**Status:** DRAFT rev 5 (editorially renumbered 2026-09-09) — **design plus a reference profile.** No
SPEC edit and no change to `ski@v1` is made or proposed by this document. It
adds an OPTIONAL verification profile (`warrant.fact-provenance@v0`) and an
additive, term-preserving WPL clause. Adoption of the profile requires an
adversarial gate; nothing here is adopted, and no existing record changes
meaning.

**Invariant this proposal is built around:** *provenance never changes the
term.* A WPL source with `from` clauses compiles to byte-identical `term`,
`expect`, `atp` and check blob as the same source without them. Every shipped
pack keeps its hashes; nothing is re-signed. This is enforced by a test, not
by intent (§6).

---

## 1. The problem

`docs/authoring-checks.md` §8 states the position honestly:

> **Nothing about the facts is proven.** `fact retroactive: bool = true` is an
> assertion by whoever compiled it. Its trustworthiness comes from the
> signature on the record and the evidence blobs cited beside it, not from the
> check.

That is correct and it is the right default. But it flattens two things that
are not alike, and the flattening has a cost the format has not paid attention
to.

Some facts are **observations**: someone looked at the world and wrote a
number. No cryptography makes an observation true. The strongest honest thing a
record can say is *who* asserted it and *when it entered the record*.

Other facts are **consequences of what is already in the store**. `files_changed`
is a consequence of a pinned diff. And — the case this proposal exists for —
*the answer of a previous decision* is a consequence of a term that is already
content-addressed, budget-bounded and re-runnable by anyone.

For the second class, **trust is the wrong instrument**. The value does not need
to be believed; it needs to be *re-derived*. Today WPL has no way to say so, so
an author who wants to build on a prior decision retypes its answer as a
literal, and a re-typed literal is indistinguishable from an invention.

**Consequence: decisions do not compose.** Each warrant is an island. A policy
cannot cite another policy's outcome mechanically, so the "chain of reasons"
the format is for stops at one link. This is the single blocker to the format
demonstrating what it is actually for.

## 2. Two fact kinds

| Kind | What it is | What binds it | What a verifier can say |
|---|---|---|---|
| **observed** | someone measured the world | a signature and an actor | *attested by X at t* — never "verified" |
| **derived** | a consequence of store contents | a re-runnable derivation | *derived*, *contradicted*, *underived*, or *stale* |

The design rule: **a policy cites an observed fact by its attestor, and a
derived fact by its derivation.** These MUST NOT be reported with the same
word. This is the same requirement SPEC §6(7) already imposes on reasons
("`Re-ran and matched` and `was not executed` MUST NOT be observationally
equivalent"), applied one level down, to the operands.

Observed facts remain exactly what they are today. This proposal adds nothing
to them and claims nothing about them. It gives the *other* kind a name and a
check.

## 3. The `from` clause (WPL, additive)

```
fact retroactive: bool = true                        # observed — unchanged
fact eligible:    bool = true from <WarrantID>       # derived
fact timely:      bool = true from <WarrantID> check <hex64>
```

Grammar: after a fact's literal, optionally the contextual word `from` followed
by ONE quoted reference — `"<WarrantID>"` or `"<WarrantID>/<check>"`. The
reference is a string literal because a 64-character hex id is not a WPL
number: WPL's lexer refuses a numeral followed by a letter, so a bare hex64
cannot be tokenized. Putting the optional selector inside the same string
rather than in a second `check` token also keeps the grammar free of a
two-token lookahead against the `check` keyword that opens the check
expression.

`from` is a **contextual word, not a reserved one**: it is recognized only in
this position, so a policy that already uses `from` as a fact name keeps
compiling.

**Which refusals happen when.** The compiler has no store, so it can only
refuse what is visible in the source: a non-bool fact, a malformed reference,
a reference that is not one or two hex64 segments. Whether the cited warrant
exists, and whether it carries exactly one `ski@v1` reason, is a **checking-time**
question, reported as `underived` (§5) — not a compile-time refusal. rev 1 of
this document described the ambiguity check as compile-time; that was wrong.

**Derived facts are `bool` only in v0.** A `ski@v1` check answers one Church
boolean (§3.1), so that is the only value shape a decision can hand to the next
policy. Deriving an `int` would require a check whose canonical outcome is a
numeral — a different outcome shape, and a different proposal. Predicate
chaining is what settlement needs, and predicate chaining is booleans.

**The clause does not enter the term.** Facts are still pinned as literals and
lowered exactly as before. `from` is provenance metadata, carried beside the
check, never inside it (§6).

## 4. The provenance document

One blob per check, JCS-canonical, cited in the filing warrant's `evidence`:

```json
{
  "provenance": "warrant.fact-provenance@v0",
  "check": "<hex64 — the ski@v1 check blob this describes>",
  "source": "<hex64 — the WPL source blob the check compiles from>",
  "facts": {
    "eligible":    {"kind": "derived",  "value": true,
                    "from": "<WarrantID>", "check": "<hex64>"},
    "retroactive": {"kind": "observed", "value": true}
  }
}
```

**Completeness (MUST).** The document MUST describe **every** fact of the check
it names, and a checker MUST refuse a document whose fact-name set differs from
the set recovered by recompiling `source`. Omission is the failure mode this
rule exists to stop: a provenance document that simply leaves a fact out would
otherwise turn a check off while the status stayed green. A missing entry is a
refusal, never a default to `observed`.

**The compiler stays untrusted.** The checker recompiles `source` and requires
it to yield `check`. Provenance is therefore auditable the same way the term
already is: by re-running the compiler and comparing, never by believing it.

## 5. What the profile checks

`warrant.fact-provenance@v0` is an OPTIONAL profile. A verifier asked for it
performs, for every derived fact:

1. Resolve the cited WarrantID among stored records.
2. Select its `ski@v1` reason (named by `check`, or the unique one).
3. Load the check blob; re-run `term` under its pinned `atp` (the same
   re-execution §6(7) already performs).
4. Require the result NodeHash to equal the reason's `expect`.
5. Map `expect` to a boolean by the canonical Church TRUE / Church FALSE node
   hashes. Any other normal form is **not a boolean outcome** and is a refusal,
   not a coerced value.
6. Compare that boolean to the fact's pinned literal.
7. Check whether the cited warrant has been superseded by a stored `supersede`.

Four terminal states per derived fact, which MUST be distinguishable in output:

| State | Meaning | Severity |
|---|---|---|
| `derived` | re-ran; the cited decision's answer equals the pinned value | — |
| `contradicted` | re-ran; the answer **differs** from the pinned value | ERR |
| `underived` | could not re-run: missing record or blob, over budget, ambiguous reason, non-boolean outcome | WARN, ERR under settlement grade |
| `stale` | derivation reproduces, but the cited warrant has been **superseded** | WARN, ERR under settlement grade |

Observed facts get one state, `attested`, carrying the `actor.id` of the record
that cites the provenance document. A checker MUST NOT print `verified` for an
observed fact. The actor is available only through `check_record`, which knows
the citing record; `check_doc` called on a bare document reports `attested` with
no actor, because at that entry point there is no record to attribute it to.

### 5.2. Record-level completeness

Per-fact states answer "does this derivation hold". They cannot answer "did I
see all of this record's provenance", and rev 1 conflated the two: a cited
provenance blob that had been deleted produced an empty result, so a removed
document and a record that never had one were the same answer. `check_record`
now returns one of three record-level statuses:

| Status | Meaning |
|---|---|
| `complete` | every cited evidence blob resolved and was address-intact; the findings below are all of it |
| `not-applicable` | everything resolved, and this record cites no provenance document — a legacy record, legitimately |
| `incomplete` | some cited evidence is missing or off-address, so the ABSENCE of a provenance document cannot be told from its LOSS |

`incomplete` is not a fact state and is never success.

### 5.4. A sidecar belongs to the reason it documents

A provenance document found in a record's `evidence` is credited only if its
`check` is one of **that record's own `ski@v1` reasons**. Recompiling its source
proves the document is internally consistent; it says nothing about whose reason
it describes, and without the binding a correct sidecar for an unrelated check
was accepted and the record reported `complete` — a result filed under one
WarrantID that was about a different question (review H1).

A profile document in `evidence` that names some other check is a **refusal**,
not an attachment to be ignored: it is presented as this record's provenance and
is not. If evidence ever needs to carry foreign sidecars as general
attachments, that needs its own explicit distinction; refusing is the
fail-closed choice and is the one that can be relaxed later.

Whether *every* `ski@v1` reason of a record must have a sidecar is a separate
question this revision does not decide (§9.6).

### 5.5. `derived` is not whole-chain validity

`stale` travels through a chain because supersession is a fact about a
**record**. A `contradicted` upstream derivation is a fact about a **value**,
and `derived` is defined in §3 against the *immediate* answer only. So:

```text
A answers false.  B pins true from A, and therefore computes true.
C pins true from B.
  ->  B.e = contradicted        C.f = derived
```

C is `derived` and that is the definition working, not failing: C's immediate
source really does answer what C pinned. But a consumer must not read `derived`
as validation of everything behind it. A whole-store report still surfaces the
contradiction at B, which is where it belongs, and
`test_derived_is_not_whole_chain_validity` pins this behaviour so it cannot
drift silently in either direction.

Whether the walk should also re-check upstream *values* — and if so, under
which state, since neither `stale` nor `underived` describes it — is §9.7.

### 5.3. Address integrity is a precondition, not an inference

Every byte this profile reads is read only after its address is checked:

* a **blob** (source or provenance) is read through `_intact_blob`, which
  requires `blob_intact` and not merely that a regular file sits at that name;
* a **record** is used only if its canonical body recomputes to the WarrantID it
  is stored under. `all_records` keys records by file name, and a body swapped
  under an existing name keeps that name while changing what it says.

Neither is a claim about authority. Address integrity, signature validity and
standing are three separate questions, and this profile answers only the first
of them, as a precondition for the rest of its work.

### 5.1. Why `stale` is the point

`stale` is the reason this proposal is worth more than tidiness.

When a leaf observation is later shown to be false, someone files a re-litigation
warrant under §7(b) and the affected decision is superseded. Every downstream
policy that derived a fact from it then reports `stale` — **mechanically,
offline, with no registry, no notification service and nobody remembering the
dependency existed.** Revocation propagates because the dependency is written
down in a form a machine re-walks, not because anyone maintained a list.

That is the honest version of the ambition: the format does not prevent a false
observation. It makes the discovery of one *propagate*.

**Propagation is transitive, and bounded.** Superseding the record a value came
from is only the shallow case. If that record itself derived a fact from
something since replaced, its answer rests on the same moved ground, so the
staleness travels: `_source_health` walks a cited record's own provenance
documents and reports `stale` through a named link. rev 1 claimed "every
downstream policy" while checking only the direct edge — a label wider than its
predicate, found at gate as F4.

The walk is bounded by depth (`MAX_DEPTH`), a global record budget
(`MAX_RECORDS_WALKED`) and a cycle guard. **Hitting any bound is reported as
`underived` with the reason**, never as success: an unwalked dependency is not
a walked one.

## 6. The term-preservation invariant

`from` clauses MUST NOT change `term`, `expect`, `atp`, the emitted node set, or
the check blob hash. The reference implementation enforces this by compiling
each fixture twice — once with every `from` clause stripped — and asserting
byte-equality of the emitted document.

This is what keeps the change additive: `ski@v1` is a registered, immutable
runtime tag (§13.1), the shipped `demos/air-canada` pack keeps its published
hashes, and a verifier that does not know about provenance verifies exactly what
it verified before.

## 7. What this does not claim

- **It does not make an observed fact true.** Nothing can. It only stops an
  observation from being typeset like a derivation.
- **It does not change §6, §7, or `ski@v1`.** It is a profile plus an authoring
  clause. A base-grade verification is unaffected, and a verifier that ignores
  the provenance blob is still conformant.
- **It does not establish that a cited decision was *authorized*.** Re-running a
  term proves what the term computes, not that its author had standing. Authority
  remains §5/§12's problem, and the trust root remains the verifier's
  configuration.
- **It bounds chain depth and cost, and the bounds are local policy.** A derived
  fact re-runs another check, which may itself carry derived facts. The
  reference checker bounds recursion depth and the number of records walked and
  reports either bound being hit as `underived` — never as success. Two
  verifiers configured differently may disagree about a very deep chain, which
  is the same deliberate local-policy divergence SPEC §3.1 already allows for
  the re-execution budget.
- **It does not claim the profile is adopted.** rev 2 has had ONE adversarial
  gate (Codex, 2026-09-09): AMEND, five findings, all reproduced against the
  code and all closed here with negative fixtures. One round by one reviewer on
  one host is not adoption, and the reactivation conditions in §0 are not
  thereby met.
- **It does not address cycles.** A store where W1's fact derives from W2 and
  W2's from W1 is possible to construct; §9(3) treats it as open.

## 8. Relation to the rest of the stack

- **Σ-GLYPH** owns the reduction; nothing here touches it. A derived fact is one
  more re-execution of an existing Book I term.
- **Aggregation (`all` / `any` / `count`) is downstream of this, not parallel to
  it.** Aggregation over a collection pinned into the term stays a closed ground
  check and costs only ATP. Aggregation over a collection that is *not* pinned
  requires knowing where the collection comes from — which is this proposal.
  Deciding quantifiers before binding is deciding the harder half first.
- **The manifesto's line about a network that remembers** gets a mechanism here:
  what the network remembers is not the value, it is the derivation.

## 9. Open questions (attack surface)

1. **Ambiguous reason selection.** v0 refuses a warrant with more than one
   `ski@v1` reason unless `check` names one. Is refusal right, or should the
   clause name a *reason index*? Index is fragile under re-filing; check-hash is
   stable but verbose.
2. **Non-boolean outcomes.** v0 refuses. A canonical DISSONANCE outcome is a
   real and meaningful answer ("this did not settle") that a downstream policy
   might legitimately want to branch on. Refusing it may be over-strict.
3. **Cycles and depth.** Closed in rev 2: a cycle is detected by a visiting set
   and reported `underived`, as is exceeding depth or the record budget. What
   remains open is whether the bounds are the right ones, and whether an
   `underived` caused by a bound should be distinguishable in the report from
   one caused by a missing blob.
4. **`stale` and re-filing.** A superseded warrant whose successor reaches the
   *same* answer arguably should not make downstream facts stale. Distinguishing
   "superseded and changed" from "superseded and unchanged" needs the successor's
   outcome fingerprint compared to the predecessor's — cheap, but unspecified in
   rev 1.
5. **Sidecar coverage.** §5.4 binds a sidecar to a reason of its record but does
   not require every `ski@v1` reason to have one. A record could document one
   reason and leave another undocumented, and report `complete`. Requiring full
   coverage is plausible; it would also make every existing record without
   provenance `incomplete` rather than `not-applicable`, so it is a scope
   decision, not a bug fix.
6. **Upstream value re-checking.** §5.5: the walk checks structure and
   supersession in ancestors, not whether each upstream derivation still holds.
   Adding it needs a state that means "rests on a contradicted foundation",
   which is neither `stale` (nothing was superseded) nor `underived` (the walk
   succeeded). Adding a fifth state mid-gate was judged worse than naming the
   boundary.
7. **Does `contradicted` belong at ERR?** It is a genuine defect of the citing
   record, but §6's convention is that a false claim is a dispute answered by a
   counter-warrant, not a corruption of the record. rev 1 chooses ERR because the
   citing author pinned a value their own cited source refutes, which is a
   different thing from disagreeing with someone else. This is the finding most
   likely to be reversed by review.

## 10. Reference artifacts in this branch

| Artifact | What it is |
|---|---|
| `impl/policy_lang.py` | `from` clause: parser, `Fact.source`, provenance emission. Term-preserving. |
| `impl/fact_provenance.py` | Profile checker: the four states, completeness rule, recompile-and-compare. |
| `tests/fact_provenance.py` | Including the term-preservation invariant and one negative fixture per state. |
| `demos/refund-chain/` | Three policies, chained; rhetoric refused; a new consequence of old evidence reopens settlement, and the downstream derived fact goes `stale` on its own. |
| `tools/pack_pdf.py` | The envelope: a pack as one file that is both a readable PDF and its own deterministic archive. It does not verify itself, on purpose. |
| `tests/pack_pdf.py` | Including the xref walk, hostile-archive refusals, and a property test on the *absence* of self-adjudication. |

---

## 11. Gate round 1 — disposition (Codex, 2026-09-09, AMEND)

All five findings reproduced against the code and closed in rev 2. Each has a
negative fixture that fails if the fix is reverted; three of them are the
review's own counterexamples, adopted verbatim as tests.

| Finding | What it showed | Closed by |
|---|---|---|
| **F1** P1 · entry not bound to `Fact.source` | relabelling a derived fact `observed` gave `attested`; retargeting `from` to another warrant gave `derived`, both with the source unchanged | `_require_complete` now compares kind, `from` and selector against the source's own clause; four vectors in `test_completeness_and_tampering` |
| **F2** P1 · addresses unchecked | a body swapped under an existing record name was credited; an edited source blob was compiled and used | `_intact_blob` + `_record_at`; `test_address_integrity`. These checks address the analogous residuals recorded for the earlier WRT-008 (§0); its own deferred model is unchanged |
| **F3** P2 · missing provenance silently skipped | deleting a cited provenance blob gave `findings=[], errors=[]` | record-level `complete` / `not-applicable` / `incomplete` (§5.2); `test_missing_provenance_is_incomplete` |
| **F4** P1 · `stale` did not travel | A→B→C, supersede A: `B.e = stale` but `C.f = derived` | `_source_health` walks the cited record's own provenance, bounded; `test_transitive_staleness` checks two- and four-link chains and that a bound is never reported as `derived` |
| **F5** P2 · refusal after a write | a hostile member after a valid one refused the traversal *and* left the earlier file replaced | full preflight in both `unpack_store` and the embedded runner; the fixture now carries a valid prefix, as the review asked |

Documentation findings are closed with them: §3 now describes the grammar the
parser actually accepts and says which refusals are compile-time and which are
checking-time; §5 scopes the `attested` actor to the entry point that has a
record; §0 records the relation to the earlier WRT-008 disposition rather than
silently reusing its number.

**Not closed, and deliberately so.** The reviewer's note that executing an
arbitrary PDF as Python is still executing its code stands. The envelope's
non-adjudication narrows what it *claims*, not what it *is*; a reader who
wants no execution at all should treat the artifact as data and extract it with
a trusted extractor, which is what the review's own probes did.

Counts after rev 2: `fact_provenance` 97/97, `pack_pdf` 42/42, `policy_lang`
147/147 (unchanged).

## 12. Gate round 2 — disposition (Codex, 2026-09-09, AMEND)

Round 1's F1–F5 confirmed closed by the reviewer, including the original F5
counterexample. Two new P2 findings, both reproduced and both closed here.

| Finding | What it showed | Closed by |
|---|---|---|
| **H1** P2 · sidecar not bound to the record's reason | a correct provenance document for an *unrelated* check, placed in a record's evidence, gave `status=complete`, `ok=True` and reported that other check's facts under this WarrantID | `_provenance_docs_of` now requires `doc.check` to be one of the record's own `ski@v1` reasons and refuses otherwise (§5.4); the same binding applies in the upstream walk, so an ancestor carrying a foreign sidecar is `underived` rather than credited |
| **H2** P2 · file/parent conflict caught after a write | an archive holding both `node` and `node/child` passed preflight and failed at `mkdir` — after `existing` had already been replaced | `_plan` now scans ancestor/descendant conflicts order-independently, and refuses a target whose parent exists as a file or which would replace a directory; the embedded runner carries the same scan |

**S1 is closed as a documented boundary, not a fix.** The reviewer's example
(A false, B pins true from A, C pins true from B → B contradicted, C derived) is
recorded in §5.5 and pinned by a test, and the open design question it raises is
§9.6/§9.7. `derived` means the immediate answer matched; it has never meant the
chain behind it was validated, and the profile now says so where a consumer
will read it.

One fixture defect of mine surfaced while writing the H1 regression and is worth
recording, because it is the same family: my first "unrelated check" was
`fact unrelated: bool = true / check unrelated`, which compiles to the **same
check blob** as `fact base: bool = true / check base`. WPL pins facts as
literals and fact names never enter the term, so a differently-named check is
not a different check. The test now asserts the two blobs differ before relying
on them differing.

Counts after rev 3: `fact_provenance` 109/109, `pack_pdf` 53/53, `policy_lang`
147/147 (unchanged).

## 13. Gate round 3 — disposition (Codex, 2026-09-09, AMEND)

H1 and the original H2 confirmed closed. Two new P2, both reproduced, both
closed with regressions.

| Finding | What it showed | Closed by |
|---|---|---|
| **J1** P2 · binding tested before shape | a document with `check: []` reached a set membership and raised `TypeError` out past `check_record`'s handler, losing the typed refusal **and** the report for every other record. Introduced by the H1 fix | `_validate_doc_shape` now runs before the binding test; a blob that claims to be ours and is malformed is a refusal, never an ignored attachment. Six malformed shapes plus a CLI control |
| **J2** P2 · path collisions compared as strings | on a case-insensitive filesystem `NODE` and `node` are one file; the second member silently overwrote the first, and the case variant of H2 lost `existing` before failing | `_fold` keys targets by case- and NFC-folded components, in the exact-collision check and the ancestor scan, in both extractors. `os.path.normcase` alone would have been a no-op here |

## 14. Rev 4 — the binding enumeration, and what it found

Rounds 1–3 produced F1, F2, H1 and J1: one defect wearing four faces, *something
claims to be about something else and nobody checked the claim*. Rev 4 answers
it by method rather than by another patch:
[`proposals/wrt-010-model/BINDING-EDGES.md`](wrt-010-model/BINDING-EDGES.md)
enumerates every such claim, what checks it, and the test.

It found two nobody had reported, and one more while fixing the first:

- **K1** — a derived fact was credited from a warrant outside the citing
  record's `prior` closure. SPEC §7 builds the settlement tunnel from `prior`,
  so such a dependency is invisible to re-litigation: superseding the source
  would never reach the record, and the propagation this whole profile exists
  for would silently not happen. Using a decision now requires citing it;
  transitively is enough.
- **K2** — `attested by <name>` implied an attestation. The name is
  `body.actor.id`, bound to the record's identity and to nothing else; this
  profile verifies no signature. The report now says so, and a test fails if the
  profile ever grows a signature API.
- Record status was derived from a subset of the refusal list, so a record could
  read `complete` while a document it cited had been refused. F3 one level up.

The enumeration cannot prove the list is complete. What it changes is the shape
of the next finding: a row that is wrong, or a row that is missing — an argument
about the model rather than another edge to patch.

Counts after rev 4: `fact_provenance` 136/136, `pack_pdf` 67/67, `policy_lang`
147/147 (unchanged).

## 15. Gate round 4 — disposition (Codex, 2026-09-09, AMEND)

J1, J2, H1, H2, F5 and the S1 boundary all confirmed closed. One new P1, in the
K1 code this proposal added one revision earlier.

| Finding | What it showed | Closed by |
|---|---|---|
| **L1** P1 · an unverified bridge proved citation coverage | the K1 walk delegated reachability to `warrant.tunnel`, which reads `body.prior` out of a dict keyed by FILE NAME. Swapping an intermediate record's body under its old name turned the K1 refusal into `complete, ok=True, derived`. Both endpoints were correctly addressed; the edge between them was a lie | `_citation_closure` is now our own bounded walk that applies E1 on **every hop** before reading a `prior`, does not traverse what it cannot verify, and names the record it stopped at. A missing or unparsable intermediate and a hit bound are each reported rather than swallowed by a broad `except` |

**What L1 taught the method, which matters more than the patch.** E1 was
listed in the enumeration, implemented, and tested — and the new walk still
read `prior` without it. *Listing an edge proves the check exists; it does not
prove the check runs at every site where that data is used as evidence.*
`BINDING-EDGES.md` now names **use sites** rather than checks, adds the
intermediate prior-path record `P` as an object in its own right, and states
the rule directly: a new path that consumes an existing object owes its own
row even when the check it needs is already written.

That is the enumeration doing what it was built for, one round later than
ideal: the reviewer could name the finding as a missing object in the model
rather than as another loose edge, which is exactly the change of argument
rev 4 was meant to buy.

Counts after rev 5: `fact_provenance` 145/145, `pack_pdf` 67/67, `policy_lang`
147/147 (unchanged).

## 16. Gate round 5 — disposition (Codex, 2026-09-09, ACCEPT in scope)

L1 confirmed closed by the reviewer's own probe re-run, with four new controls
on the honest transitive path: a deleted intermediate, an unparsable
intermediate, `MAX_CITATION_RECORDS=1`, and a record whose derivation is
directly cited while a *separate* prior branch is missing. The last is the one
worth naming: the fact stays `derived` while the record is `incomplete` and
`ok=False`. That is the local result and the completeness of the walk staying
apart, which is what §5.2 is for.

No finding returned. Every closed counterexample from rounds 1-4 was re-run and
none came back.

**What this ACCEPT is, stated narrowly so the label cannot widen later.** It is
a technical conclusion about these bytes. It is **not**:

- **adoption.** Nothing here is normative, no SPEC text changed, and the
  reactivation conditions in §0 still require a gate by someone who did not
  write the code. Four rounds by one reviewer on one host is not that.
- **merge.** No merge or push was performed by the reviewer or by this branch.
- **proof that the model is complete.** The reviewer is explicit that
  `BINDING-EDGES.md` remains *navigation for review*, not an automatic proof of
  coverage: this round established no formal or instrumented check that every
  use site in the repository is enumerated. §14's own limit stands unchanged.
- **a re-reading of the history.** Rounds 1-4 were AMEND and stay AMEND. This
  document records them as they happened, and the fact that a fifth round found
  nothing does not convert the earlier four into anything else.

**The deferral condition of §0 was not triggered.** It said: if the enumeration
itself returns AMEND *as a model*, the proposal defers without argument. This
round found no ground to call the approach unfit, so the condition does not
fire. It remains live for any future round.

**What the method is now judged to be worth.** The reviewer keeps the use-site
rule: a check must be shown to run at every place the data is used as evidence,
not merely to exist somewhere in the code. That rule is the durable output of
this whole sequence, and it generalizes past this profile.

Counts at rev 5: `fact_provenance` 145/145, `pack_pdf` 67/67, `policy_lang`
147/147 (unchanged throughout).

### Identifier disposition

WRT-010 is this live fact-provenance proposal. WRT-008 remains the deferred
fact-derivation proposal in PR #60. Its PR state and disposition are unchanged.
The two model directories have distinct namespaces (`wrt-010-model` here,
`wrt-008-model` there), so the worklines can coexist without a path collision.
The earlier review history is retained, not renumbered retroactively.
