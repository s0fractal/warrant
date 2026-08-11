# WRT-003: `warrant.verification-receipt@v0` — a citable verification result

**Status:** DRAFT rev 1 (2026-08-11) — **NOT ADOPTED, NOT GATED BY THIS
PROJECT.** No threshold warrant, no roster signature, no code in `impl/`, no
wire bytes frozen *here*. This file asks one question and pins the artifact
the answer would be about; it does not merge a contract into Warrant.

**Origin, stated first because it changes how you should read this.** The
artifact was designed **outside** Warrant, in
[`s0fractal/sev`](https://github.com/s0fractal/sev), by an agent, to solve a
problem SEV had. It is a *candidate*, not a finding. SEV holds no authority
here and its review record is not Warrant's gate — see §6 for exactly what
was and was not validated.

---

## 0. The question

> Does Warrant want a **second** machine-readable artifact — a signed-nothing,
> snapshot-bound *receipt* — alongside `warrant.verify-report@v0`?

Everything below exists to make that question answerable. If the answer is
no, §5 records the alternative that would replace it, and that outcome is a
perfectly good result of filing this.

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

- **`core`** is byte-reproducible across implementations *relative to*
  (snapshot, trust config, grade, declared execution policy). Its digest is
  citable: two verifiers that agree produce identical bytes.
- **`producer`** is host-local (implementation name, artifact digest, local
  notes) and carries **no** cross-implementation agreement.

`core` carries, per source: logical path, entry digest, load state, claimed
vs computed WarrantID, per-signature `{valid, binding}`, per-reason outcome
as a closed sum type, and a structured issue list with locators. Plus
aggregate counts bound to that issue multiset, so a receipt cannot report
`ok` while its own sources say otherwise.

**It is not a Warrant.** Unsigned, no WarrantID, no settlement authority —
the same disclaimer the report already carries. It is a *statement by a
verifier about specific bytes*, which is precisely what a third party needs
in order to cite a verification **without re-running it**.

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

**3.2 It obliges a versioning discipline, immediately.** SEV tried to tighten
one rule (`binding` requires a trust basis) as an amendment to the frozen
`@v0`. The result was reproducible and ugly: **the same canonical bytes, the
same type tag, two different verdicts**, with nothing on the wire to tell an
implementation which contract judged them. A contract change that no byte
announces is not an amendment — it is a silent fork. The tightening now ships
as a separate tag, `@v1`, dispatched explicitly.

This lesson is Warrant's too, independently of this proposal:
`warrant.verify-report@v0` is normative for anything printing that tag, so
the same trap is open there today.

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

The alternative, stated so it can win: **grow `warrant.verify-report@v0`
instead.** Give findings a closed code registry alongside the prose message,
add per-record structure, and leave the byte-universe binding to whoever is
doing the bundling. That keeps one artifact, keeps Warrant self-contained,
and captures most of §1's gap. It would not give a *citable* result — the
report still would not say which bytes it ranged over — but Warrant may
reasonably decide that is not its job.

A third outcome: adopt nothing, and let SEV keep the receipt as a consumer-side
construction over Warrant's report, which is exactly what the live adapter
does today.

## 6. Provenance of the candidate — what was and was not validated

**Was:**

- An executable reference model with self-vectors, a language-neutral
  conformance corpus replayed through the implementation, and a live adapter
  that seals this repository's real `.warrants/` store and projects it.
- **26 adversarial review rounds** in the SEV repository (Codex, some Kimi),
  each against an exact SHA, each filed under `sev/reviews/` with a ledger.
  Findings included several defects in the *guards* rather than the product,
  and those are recorded as such. (Counts are as of the pinned SEV commit in
  §7; the ledger is the authority, not this sentence.)

**Was not:**

- **Not gated by Warrant.** No review by this project, no roster involvement,
  no threshold warrant. AGENTS.md rule 3 applies in full: green suites are
  not a gate, and the gating that happened was in another repository against
  another artifact's criteria.
- **Not adopted anywhere.** SEV's README states plainly that nothing there is
  a live contract and no protocol has accepted anything from it.
- **No Warrant code.** This proposal adds no implementation, registers no
  runtime, and changes no existing behaviour.

## 7. The pinned artifact

Bytes this proposal is about, at SEV `master` = `33a08a6`:

| Artifact | sha256 |
|---|---|
| `proposals/WARRANT-VERIFICATION-RECEIPT.md` | `1c0e0c1a59fc82c655a0589c100121c8755d28467dceb7af572d23a2d13838ed` |
| `model/snapshot_model.py` (executable model) | `ef1d9fef6689f7d4d8d23ef9bcbee76457cff1ba0fde99a0f271a62a8afb7548` |
| `conformance/signature-promotion.vectors.json` | `0dd38df8f17409c5599e9f4c20a4cce43df8a1b5fa87bb5245eae4d7765a18b9` |
| `conformance/judgement-identity.vectors.json` | `450809a762b5e7bef0cdf91404dc0a4b0db41dab8b056a04843af47e98a1bad7` |

The `@v0` core was frozen on the SEV side at its commit `1fb82d6` after a
clean exact-SHA round. `@v1` (the trust-basis tightening) is **proposed and
unratified** there, and this proposal does **not** ask Warrant to consider
it — it is named here only because §3.2 is the lesson that produced it.

## 8. What a decision looks like

Adoption is the project's own process: a threshold warrant signed by roster
keys, recorded in `.warrants/` (AGENTS.md rule 2). Nothing in this file, and
no commit or PR carrying it, constitutes or substitutes for that.

A rejection needs no ceremony — a maintainer saying "no, grow the report
instead" closes this, and §5 is already written to make that easy.
