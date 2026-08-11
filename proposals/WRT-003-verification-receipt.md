# WRT-003: `warrant.verification-receipt@v0` — a citable verifier claim

**Status:** DRAFT **rev 3** (2026-08-11) — **NOT ADOPTED, NOT ADOPTABLE, NOT
GATED BY THIS PROJECT.** Two exact-SHA reviews have run against it; §9 is the
revision history and §0 says what changed most: **this file can no longer be
adopted into force**, because the candidate it pins is not a complete wire
contract. It asks whether the direction is worth specifying.

No threshold warrant, no roster signature, no code in `impl/`, no wire
bytes frozen *here*. This file asks one question and pins the artifact
the answer would be about; it does not merge a contract into Warrant.

**Origin, stated first because it changes how you should read this.** The
artifact was designed **outside** Warrant, in
[`s0fractal/sev`](https://github.com/s0fractal/sev), by an agent, to solve a
problem SEV had. It is a *candidate*, not a finding. SEV holds no authority
here and its review record is not Warrant's gate — see §6 for exactly what
was and was not validated.

---

## 0. The question

> Should Warrant **begin specifying** a second machine-readable artifact — a
> signed-nothing, snapshot-bound *receipt* — alongside
> `warrant.verify-report@v0`?

**rev 3 narrows this from "should Warrant adopt this contract".** It cannot
be that question, because the pinned candidate is not a complete wire
contract. Reproduced on the pinned model at SEV `1fb82d6`: two canonical
receipts over the *same* snapshot, trust config, grade and execution policy,
differing only in one arbitrary `WARN` issue code, **both validate with no
findings and produce different `core` digests**. The issue-code registry is
an explicit extension point in the frozen text, so "byte-reproducible core
across implementations" — §2's central promise — is not something the pinned
bytes deliver. Two honest implementations can disagree on the digest of the
same judgement.

That is not a defect to be patched in this file. It means the wire contract
is unfinished, and a decision to adopt it would be adopting a hole. So the
decision on offer is the smaller and more honest one: **is this direction
worth specifying at all?** If yes, the missing semantics — issue-code
registry, locator grammar, runtime and settlement internals — get completed
*first*, under a new manifest, and adoption is a later question.

If the answer is no, §5 records the alternative that would replace it, and
that outcome is a perfectly good result of filing this.

## 1. What already exists, and what it does not do

`warrant.verify-report@v0` (SPEC §11, `impl/warrant.py:verify_report`) is
normative for anything printing that tag: `ok == (errors == 0)`, `grade`,
deterministic finding order, same core as the text verifier. It is unsigned,
carries no WarrantID and no settlement authority — deliberately.

It answers **"did this store verify, for me, just now?"** Three things it
does not do, none of which are defects in it:

1. **It is not bound to a byte universe.** Findings name records by
   WarrantID and `records` gives a count, but nothing pins *which files were
   read*. Two reports over two entirely different stores with the same counts
   and the same finding shapes are indistinguishable documents. A third party
   holding one cannot tell what it ranged over.
2. **Findings carry prose.** `{"level", "subject", "message"}`, where
   `message` is human text — correctly non-normative, and therefore not
   joinable. A consumer that must act on *which* problem occurred has to
   parse English.
3. **There is no per-source structure.** No path, no entry digest, no
   per-signature validity/binding, no per-reason outcome. The report is an
   aggregate plus a finding list.

**This is empirical, not theoretical.** A live adapter in SEV consumes this
repository's real `.warrants/` store through this repository's own verifier.
To carry the report's findings into a structured artifact without inventing
judgements, it had to enumerate **every message prefix** the reference
implementation can emit, swept from the `out(level, wid, msg)` call sites,
and **fail closed** on anything unrecognised. The sweep still missed one —
`ski@v1 unverified`, emitted from the runtime-handler boundary rather than
the core reporter — and the fail-closed path caught it on a real store.
That is the boundary being real, measured rather than argued.

## 2. What the receipt is

One object per (sealed snapshot subroot, verification), split `core` /
`producer`:

- **`core`** *aims to be* byte-reproducible across implementations relative
  to (snapshot, trust config, grade, declared execution policy).

  **It does not achieve that yet, and §0 exists because of it.** The frozen
  text leaves the issue-code registry an extension point, so two receipts
  over identical inputs differing only in an arbitrary `WARN` code both
  validate and hash differently. The aim is the reason to specify; it is not
  a property the candidate has.
- **`producer`** is host-local (implementation name, artifact digest, local
  notes) and carries **no** cross-implementation agreement.

`core` carries, per source: logical path, entry digest, load state, claimed
vs computed WarrantID, per-signature `{valid, binding}`, per-reason outcome
as a closed sum type, and a structured issue list with locators. Plus
aggregate counts bound to that issue multiset, so a receipt cannot report
`ok` while its own sources say otherwise.

**It is not a Warrant, and it is not an attestation.** Unsigned, no
WarrantID, no settlement authority — the same disclaimer the report already
carries. `producer.impl` is a free string and `producer.artifact_digest` may
be `null`, so **nothing in a receipt proves that the named verifier existed,
ran, or produced it.**

*(rev 2 — the earlier text said a receipt is "precisely what a third party
needs in order to cite a verification **without re-running it**". That was
an overclaim, and the distinction it blurred is the one this whole document
is supposed to be careful about. A digest makes the document
**content-addressable**; it says nothing about **provenance** or **truth**.
Anyone can write a receipt claiming anything.)*

The honest promise is narrower: a receipt is a **citable verifier claim about
specific bytes** — a claim whose subject cannot drift, whose contents cannot
be silently edited, and which two verifiers that agree will produce
identically. Its authority comes from **independent re-derivability**, which
means *re-running*, not from the document. **Reliance requires either a
re-run or an external signed attestation binding the receipt to a producer.**
That is strictly less than the report offers today in one respect — the
report at least comes from the process you invoked — and strictly more in
another: it names the bytes it judged.

The normative text is pinned in §7, deliberately **not copied here** — see
§4.

## 3. The honest cost of adopting it

**3.1 It takes a dependency Warrant does not own.** `core` is keyed by
`subroot_descriptor_digest`, an identity defined by `ecosystem.snapshot@v0`
in the SEV repository. Adopting the receipt as written means Warrant's
machine-readable surface depends on a neutral bundling format specified
elsewhere. **This is the strongest argument against adoption** and it is not
mine to wave away: Warrant has kept its verification surface
self-contained, and this breaks that. A Warrant-owned variant keyed by
something Warrant defines is a legitimate counter-proposal, and the receipt's
shape survives that change — only the binding does.

**3.2 It inherits a versioning discipline Warrant already has.** *(rev 2 —
this section previously claimed the receipt would* oblige *one, and offered
the point as a lesson. That was wrong in both directions and the correction
is worth keeping visible.)*

SEV tried to tighten one rule (`binding` requires a trust basis) as an
amendment to the frozen `@v0`, and got the same canonical bytes under the
same tag with two different verdicts. The tightening now ships as a separate
tag, dispatched explicitly.

**Warrant had already legislated this, and more precisely.** SPEC §11.4 makes
`@v0` a closed schema, forbids adding any field "including an obviously
harmless one", requires any change of meaning to ship under a new tag,
requires consumers to gate on the exact tag and not a prefix, and forbids
substituting a tag the consumer did not ask for. SEV rediscovered by
stepping on it a rule this project had already written down.

And the open same-tag divergence here is **not** hypothetical, which is what
the earlier revision implied: SPEC §11.3 discloses it concretely — without
`--store-mode`, the Go CLI's legacy flat mode emits `ok:true, records:0`
where Python emits the fail-closed `ok:false`, *"the same tag carrying
opposite verdicts about the same path in two conformant implementations"*,
recorded there as an open defect rather than legislated away. That is a
sharper instance than anything this proposal contributes.

So the cost is real but narrower than stated: a second artifact means a
second tag registry to keep honest under §13.3, not a new discipline.

**3.3 A second artifact is a second thing to keep true.** Two machine-readable
outputs that can disagree is a worse failure than one that says less.

## 4. Why this file pins instead of copying

Across four consecutive review rounds in SEV, the same defect recurred: a
rule was fixed in code and left standing in the prose that specified it — run
identity, the promotion rule, a manifest schema, a loss-code wording. Each
time the document was what a second implementation would read, and each time
it was wrong.

So this proposal does not restate the contract. It **pins the exact bytes**
(§7) and asks a question about them. If Warrant adopts, the normative text
**moves into this repository** and SEV stops maintaining a normative copy,
pinning Warrant's artifact instead — that boundary is already written down on
the SEV side and is not something Warrant has to negotiate.

## 5. If the answer is no

The alternative, stated so it can win: **specify
`warrant.verify-report@v1`.** Give findings a closed code registry alongside
the prose message, add per-record structure, and leave the byte-universe
binding to whoever is doing the bundling. One artifact family, Warrant stays
self-contained, and most of §1's gap closes.

*(rev 2: this section previously said "grow `@v0`". That is **forbidden** by
SPEC §11.4 — `@v0` is a closed schema and a producer MUST NOT add a field to
it, ever. A proposal that offered an alternative violating the host
project's own normative text was not offering a real alternative. The
substance is unchanged; the tag is.)*

It would not give a result that names its own inputs — a `@v1` report still
would not say which bytes it ranged over — but Warrant may reasonably decide
that is not its job.

A third outcome: adopt nothing, and let SEV keep the receipt as a consumer-side
construction over Warrant's report, which is exactly what the live adapter
does today.

## 6. Provenance of the candidate — what was and was not validated

**Was:**

- An executable reference model with self-vectors **at the pinned freeze**
  (§7). Note the asymmetry honestly: the language-neutral conformance corpus
  that replays through the implementation, and the live adapter that seals
  this repository's real `.warrants/` store, were **built later** — they
  exercise SEV's current tree, not the pinned `@v0` bytes. They are evidence
  that the shape survives contact with real data; they are not evidence
  about the exact candidate.
- **26 adversarial review rounds** in the SEV repository (Codex, some Kimi),
  each against an exact SHA, each filed under `sev/reviews/` with a ledger.
  Findings included several defects in the *guards* rather than the product,
  and those are recorded as such. (Counts are as of the pinned SEV commit in
  §7; the ledger is the authority, not this sentence.) **Most of those
  rounds gated the work that came AFTER the freeze** — the `@v1` split,
  the projector, the corpus. The candidate itself was gated through the
  round that froze it, and no further.

**Was not:**

- **Not gated by Warrant.** No review by this project, no roster involvement,
  no threshold warrant. AGENTS.md rule 3 applies in full: green suites are
  not a gate, and the gating that happened was in another repository against
  another artifact's criteria.
- **Not adopted anywhere.** SEV's README states plainly that nothing there is
  a live contract and no protocol has accepted anything from it.
- **No Warrant code.** This proposal adds no implementation, registers no
  runtime, and changes no existing behaviour.

## 7. The candidate, pinned unambiguously

*(rev 2 — the earlier table was self-contradicting and the correction is the
substance of this revision. It pinned SEV's **current** bytes while the text
said Warrant is asked about the **frozen `@v0`** and that `@v1` is out of
scope. The current bytes contain `@v1`. It also pinned two conformance files
that did not exist at the freeze, and it did **not** pin
`ecosystem.snapshot@v0` at all — the very dependency §3.1 calls the strongest
argument against adoption. "Pins the exact bytes" and "`@v1` is not on the
table" could not both be true of that table.)*

**The candidate is exactly this, and nothing else:**

| Role | Ref | sha256 |
|---|---|---|
| Receipt contract, `warrant.verification-receipt@v0` | SEV `1fb82d6` · `proposals/WARRANT-VERIFICATION-RECEIPT.md` | `d49c4ee5cf437877e11e376d5f0c9f99bcf739fb27cfcb184d3b3c438e59c453` |
| Executable model at the freeze | SEV `1fb82d6` · `model/snapshot_model.py` | `ed89c8cfc19ca0266ccb5dceded505924921d7c2061e4871bcf219adca54f58a` |
| **Dependency** — `ecosystem.snapshot@v0`, prose | SEV `7935400` · `spec/ECOSYSTEM-SNAPSHOT.md` | `814d8ac69c18274a1d93e12539c9002068ebfac877419d98603e7a2f78443422` |
| **Dependency** — the parser boundary, executable | SEV `7935400` · `conformance/parse-strict.vectors.json` | `dde19ca66aed52c772803cd7f5ef50653f8a2038974319c3d55794eed5bbe0d6` |

*(rev 3 adds the fourth row. The frozen snapshot surface includes
`parse_strict`'s **complete refusal set**, and the prose spec alone does not
carry it — the refusal set is pinned by the language-neutral corpus. A
manifest that named only the prose would have pinned the description and not
the boundary.)*

**Normative precedence at the parser boundary**, stated because two artifacts
now describe one thing: where the prose and the vectors disagree, **the
vectors govern** — they are bytes, replayable by an implementation that
reads no prose at all, and the disagreement itself would be a defect to
report rather than interpret.

**Freeze provenance** (non-normative, and deliberately separate from the
candidate bytes above): both pinned documents describe *themselves* as
`SKETCH` / design candidate at those commits — the `FROZEN` declarations are
in SEV's `README.md` freeze table and were written later. That is ordinary
freeze mechanics, not a contradiction, but the act and the subject are
different things and this file pins only the subject. A reviewer wanting the
act should read SEV's freeze table and `reviews/` ledger at `master`, which
move; they are not pinned here precisely because they are not part of the
candidate.

**Explicitly NOT part of the candidate**, listed because they exist and could
otherwise be mistaken for it:

- `warrant.verification-receipt@v1` — the trust-basis tightening. Proposed
  and unratified in SEV, named in §3.2 only as the story that produced the
  versioning point, and **not before Warrant** in any form.
- Everything in SEV `master` after those commits: the `@v1` dispatch, the
  §4.1 PROV mapping, the projector, the conformance matrices built for
  `@v1`. Newer, better tested, and **not the thing being asked about**.

If Warrant ever wants the later work, that is a different proposal with a
different manifest.

## 8. What a decision looks like

**This file cannot be adopted into force, and rev 3 says so rather than
leaving it implied.** §0 explains why: the pinned candidate leaves wire
semantics unspecified, and a threshold warrant over an incomplete contract
would freeze a hole. Even a maintainer inclined to say yes should not adopt
*this*.

The three outcomes available:

1. **"Worth specifying."** The missing semantics — issue-code registry,
   locator grammar, runtime and settlement internals — are completed first,
   under a new manifest and a new proposal. Adoption is a question for that
   proposal, not this one.
2. **"Not worth it — specify `warrant.verify-report@v1` instead."** §5. This
   closes WRT-003 cleanly and needs no ceremony.
3. **"Neither."** SEV keeps the receipt as a consumer-side construction over
   Warrant's report, which is what the live adapter does today. Also a clean
   close.

Adoption of anything, whenever it comes, is this project's own process: a
threshold warrant signed by roster keys, recorded in `.warrants/` (AGENTS.md
rule 2). Nothing in this file, and no commit or PR carrying it, constitutes
or substitutes for that.

## 9. Revision history

- **rev 1** — filed. Three P1s at exact-SHA review: the §5 alternative
  violated SPEC §11.4; the §7 pins did not identify a unique candidate
  (current bytes containing `@v1`, no snapshot dependency); §2 overclaimed
  citability for an unsigned document.
- **rev 2** — those three corrected in place, with the errors left visible.
  Two further P1s: the GitHub PR title and body still carried rev 1's claims,
  and the pinned `@v0` is not a complete wire contract — reproduced as two
  valid receipts over identical inputs with different `core` digests.
- **rev 3** — the question narrowed from *"adopt this"* to *"is this worth
  specifying"*, §2's reproducibility claim demoted from a property to an
  aim, the manifest completed with the parser boundary, freeze provenance
  separated from candidate bytes, and this history added so the file's own
  drift is legible without reading git.
