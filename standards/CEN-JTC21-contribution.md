# Technical contribution — record-keeping for high-risk AI systems

**To:** CEN-CENELEC JTC 21, in relation to work on logging and record-keeping
for the AI Act (prEN 18229-1 and related items).
**From:** the `warrant` / `Σ-GLYPH` project (s0fractal).
**Date:** 2026-07-29. **Status:** DRAFT — not yet submitted.
**Terms:** royalty-free, no patents sought or held, see §5.

---

## 1. What is offered, and why it is being offered

An open record format for **agent decisions** — not a product, and not a
proposal to standardise this project's work as-is. What is offered is a worked
example, three interoperating implementations, and a conformance suite that a
committee or an implementer can run without contacting anyone.

The reason for contributing rather than selling: a logging standard determines
what evidence regulated deployers will be able to produce, for a decade. If the
format that emerges cannot be verified by a party that distrusts the vendor who
produced the log, then Article 12 records will be checkable only by the entity
with the most reason to be believed and the least reason to be checked. That
outcome is worth spending a week of committee time to avoid, whoever's format
prevails.

## 2. The specific gap

Article 12 requires automatic recording of events over a system's lifetime, and
Articles 19 and 26(6) require retention. Neither says what a record must let a
reader **do**.

For traditional systems the implicit answer is adequate: a log is read by a
person, and its authority comes from the organisation that kept it. For agentic
systems it is not, for one structural reason:

> An agent's log records what it did. A regulator, an insurer, a court, or an
> affected person needs to know **why it was permitted to** — and needs to
> establish that without trusting the operator's copy of its own policies.

Concretely, three properties that a record format can have and most do not:

1. **The governing rule is pinned by content, not by reference.** "Under policy
   v3" is not checkable a year later; the hash of the exact bytes that were in
   force is. In `Moffatt v. Air Canada` (2024 BCCRT 149) the operator's inability
   to establish what its own policy had been was the decisive failure.
2. **Reasons can be re-executed.** A reason that is prose can only be believed.
   A reason that is a deterministic, bounded computation can be re-run by the
   reader on their own machine, with a bit-identical outcome, without installing
   the vendor's runtime.
3. **A refusal is a record.** Most log formats represent "the agent declined"
   as the absence of an approval. For accountability the refusal and its reasons
   are frequently the material fact.

## 3. What exists, and how to check it without trusting us

Everything below is verifiable offline. No account, no key, no service.

```bash
pipx install warrant-verify
warrant verify --store-mode --json <pack>      # one machine-readable object
```

| Claim | How to check |
|---|---|
| Three independent implementations agree bit-exact | Python, Go and Rust replay one published vector set; the Rust one carries no third-party crates and its own SHA-256 |
| Reasons are re-executable and bounded | `ski@v1` checks are content-addressed terms; work *and* peak memory are priced by one budget, so re-running a stranger's reason is safe by construction |
| Determinism, totality and the memory bound are proved | Lean 4 mechanisation. Note the honest limit: part of the chain rests transitively on `native_decide`, which places the compiler in the trusted base |
| Records cannot be silently edited | Identity is the SHA-256 of the content; altering a record breaks every later reference to it |
| An Article 12 mapping exists | `profiles/eu-ai-act-article-12.md`, with its gaps stated in the same document |

The mapping profile is deliberately dated, and states which of the AI Act's
applicability dates are in force versus agreed-but-not-yet-signed. It is not a
compliance claim: no format makes a deployment compliant.

## 4. What this does **not** address

Stated plainly, because a contribution that claims to solve the whole clause is
not usable by a committee:

- **Not high-volume telemetry.** This records decisions — approve, reject,
  escalate, supersede — at human or agent decision rate. Inference-level tracing
  and system metrics are a different instrument and should stay one.
- **Not organisational duties.** Much of Article 12 and most of Article 26 is
  about what an operator must *do*. No serialisation format discharges that.
- **Not a retention or deletion system.** Append-only content-addressed storage
  is in tension with erasure duties; the profile handles this by keeping
  personal data out of records and referencing it by hash only, which is a
  discipline rather than a mechanism, and is documented as such.
- **Not truth.** A record proves an actor signed a decision with stated reasons
  under a pinned policy. Whether the decision was correct is outside it.

## 5. Intellectual property

- Implementations: MIT. Specification texts: CC-BY-4.0.
- **No patents are held, applied for, or sought** on any of it, and none will
  be. The format is published specifically so it cannot be enclosed.
- Prior art is recorded defensively and independently: the full history of both
  repositories is archived by Software Heritage under permanent identifiers, and
  per-release disclosure manifests are timestamped into a public blockchain.
  See `PRIOR-ART.md`. First public disclosure: 2026-07-05.
- The only reservation is on **names**: "Warrant" and "Σ-GLYPH" may be used for
  an implementation while it passes the published conformance vectors, so that a
  conformance claim keeps meaning something. Nobody grants this and nobody can
  withhold it — the check is public. Forking under a different name is
  unrestricted and expected. See `TRADEMARK.md`.

There is no commercial ask attached to this contribution and no membership being
sought by it.

## 6. What would be useful from the committee

In descending order of value to the work item, not to us:

1. **A conformance criterion for third-party verifiability** in the logging
   standard — that a record produced under it can be checked by a party who
   trusts neither the producer nor any service. Whether that is satisfied by
   this format or another is immaterial; that it is a criterion at all is what
   changes the outcome.
2. Review of the Article 12 mapping by people who read the clause professionally.
   The gaps section is the part most likely to be wrong.
3. An indication of whether a re-executable-reason mechanism is in scope for
   prEN 18229-1 or belongs in a separate item.

## 7. Sources

- `github.com/s0fractal/warrant` — format, verifier, Article 12 profile
- `github.com/s0fractal/sigma-glyph` — the deterministic check runtime
- Archived: Software Heritage, `swh:1:snp:c7ba55837844b5ed7259780c63e7b332cf6d1089`
  and `swh:1:snp:51b68178f8cef14fdf02bb98412a441c5fd536a8`

---

### Before sending — checklist for the steward

- [ ] Confirm the current stage of prEN 18229-1 and the correct submission route
      (public enquiry comment, national mirror committee, or liaison). This draft
      does not assume one; the route changes the format and the deadline.
- [ ] Decide whether to submit via a national standards body (the usual route for
      a non-member) or seek liaison status.
- [ ] Re-check every date in §3 and the profile against primary sources.
- [ ] Confirm the no-patent declaration is one you want to make permanently. It
      is deliberate and it is not reversible in practice.
- [ ] Hash and timestamp the final text before sending, so the submission is
      itself part of the prior-art record.
