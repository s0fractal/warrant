# ChatGPT (web) — review of PR #30, the flagship paper draft

**Date:** 2026-08-27
**Reviewer:** ChatGPT (web interface; the operator notes it should not be
labelled "Codex" — that name is reserved for the CLI agent surface, so this
file introduces the reviewer label `chatgpt-web`). Vendor: OpenAI.
**Target:** PR #30 (`papers/the-reason-runs-again`), paper draft at b098d0c.
**Provenance:** relayed verbatim by the operator from a web session. The
prompt was informal ("побудь суворим критиком і рецензентом…" plus the PR
summary), not a frozen review packet; the reviewer had web access and used it
(datatracker, EUR-Lex, DSSE/TUF/Git docs). Per `THREAT-MODEL.md` SA-4 this is
defect-hunting, not an independent gate.
**Verdict as given:** REQUEST_CHANGES.
**Response:** [`2026-08-chatgpt-web-paper-flagship-review-response.md`](2026-08-chatgpt-web-paper-flagship-review-response.md)

---

The review as received (translated/paraphrased headings preserved; content
verbatim where it matters):

## Findings table (reviewer's own severities)

| Severity | Finding |
| --- | --- |
| P0/P1 boundary | `ski@v1` has a cheap novelty bypass via `expect` — the "expect-flip": same term, same evidence, same actual reduction result; a fresh `expect` yields a new outcome fingerprint and "(b)" admissibility. SA-1 covers `cmd@v1`; the analogous structure survives in the "strong" runtime. |
| BLOCKER | Abstract reads as if all 3 implementations pass all 138 vectors; `impl-rs` is base-only and the pack has settlement-specific vectors. |
| BLOCKER | DSSE / CT / TUF / Git are cited as bare-digest signing domains; at least DSSE (PAE) and CT (signed struct per RFC 6962) do not sign a bare 32-byte digest. The domain-separation decision is right; the prior-art argument for it is partly wrong. |
| P1 | "diversity finds what depth does not" is a causal claim from one observed episode with uncontrolled confounders (artifact drift between rounds, prompt differences, history visibility, orchestrator-chosen stopping point). |
| P1 | No threat-model row for post-compromise retroactive signing: DAG order is not signature-creation time; a later-compromised, historically-valid key can sign "into" an old DAG position today. Checkpointing (OTS/SWH) is the mitigation and belongs in the security story, not just the archive tooling. |
| P1 | "10 reviewer identities / 6 vendors" is a classification of filename labels under the repository's own naming convention; the checker verifies its own ontology, not reviewer independence. Suggest per-review manifests (vendor, model, session, prompt hash, context hash, blindness, stopping criterion). Better metrics: defect classes, cross-family rediscovery rate, finding overlap, post-adjudication false-positive rate. |
| P2 | "immutable record" overstates: immutable body, mutable (appendable) envelope. |
| P2 | EU AI Act Art. 12 is paraphrased stronger than the law: it requires automatic recording of events for traceability, not "records sufficient to reconstruct decisions". |
| P2 | `vac2026` bib entry: actual title is "Verifiable Agent Conversation Records"; individual -00 draft, expires 2026-08-29 — two days after this review. Citation-expiry should be a machine gate, not a comment. |
| P2 | `check_claims.py` is a good anti-drift tripwire presented almost as an epistemic verifier; it does not check the harness-run numbers or external citations. Suggest three tiers (counts / measurements / sources) and negative controls for the paper build itself; build.sh does not even enforce the pandoc/tectonic versions its comment names. |

## Points the reviewer explicitly passed

- §3.1 integer-domain history: attacked and not broken; PASS, minus some
  dramatization.
- `check_claims.py`'s core discipline (answers read out of the paper, not
  duplicated in the checker): keep and multiply.

## The systemic critique (recorded in full because it is the sharpest)

Vendor diversity is not epistemic independence. One orchestration layer
controls context → task framing → model order → what each saw → when review
stops → what enters the ledger → adjudication → next model. Different
vendors' failure modes all pass through one causal funnel. "Six vendors ≠ six
epistemic custodians" — the same distinction Warrant itself draws between
different signatures and different custody (SA-3). Proposed: make
orchestration itself an audited object (frozen commit, frozen review packet,
prompt hashes, blind reviewers, pre-registered stopping criterion, separate
adjudication round); and promote "a stranger implements a verifier from SPEC
+ conformance contract alone, never having seen the source" from future work
to a 1.0 graduation criterion.

## MODEL-ACTORS.md drift

`MODEL-ACTORS.md` §1 "A delegate's records cannot be quietly erased" and §3
"Authorship is verifiable" are both stronger than `THREAT-MODEL.md` (A1:
deletion/censorship possible, an uncited leaf record disappears without a
dangling edge; SA-2: base-grade authorship is a claim, not a verified fact).
The philosophy document is looser than the threat model — mirror blindness
in prose.

## Overall

"Система цікавіша за paper." Leave the scars in; remove vanity counts;
weaken causal claims; formalize reviewer independence; move orchestration
into the threat boundary; and test the `ski expect-flip` against the real
settlement implementation — if it goes through, PR #30 did its job before
merge.
