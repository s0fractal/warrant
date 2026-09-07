# Disposition — ChatGPT (web) cross-stack review (2026-09-07)

Raw: [`2026-09-chatgpt-web-cross-stack.md`](2026-09-chatgpt-web-cross-stack.md).
Written the same day. The review was prompted to be adversarial; the
disposition is by reproduction, not by tone. Where a point restates a limit
this repository already documents, that is said, and it is still accepted
when the documented limit is where the product promise falls through.

## Reproduced before anything changed

The §2 table reproduces exactly on `84e42dd` (`impl/warrant_mcp.py`,
`classify`): `get_and_execute` → A0 via hint `get`; `query` → A0 via hint
`read`; `execute_sql` with no config → A4 undeclared; `execute_sql: []` in the
config → A0 with an empty effect list. Under the default ceiling A2 the first,
second and fourth were never sealed. The write-failure path: `_pump_and_forward`
printed to stderr and forwarded; `manifest.json` had no field for the loss.

## Dispositions

- **§1 "the check repeated" vs "the right thing was checked"; arithmetic
  rationale wrong — ACCEPTED, two parts.** (a) The tutorial and the compiler's
  refusal message said arithmetic is absent *so that the verifier re-executes
  every step instead of trusting the compiler's sum*. That is false: a sum
  compiled into the term would be re-executed like any operator. The honest
  statement: arithmetic is not implemented and not admitted in WPL v1 —
  integers compile to fixed-width bit vectors of Church booleans for
  comparison folds, and an adder over them would need an encoding, a measured
  cost curve and an admission decision that nobody has produced. Fixed in
  `docs/authoring-checks.md` and `_ARITH_HINT` in `impl/policy_lang.py`; the
  page now also says where the trust went ("a signed answer to a questionnaire
  the decider filled in") and cites WRT-008's measurement with its own scope:
  0 of 58 facts in ten real decisions *carried provenance*; 48 were classified
  as candidate-derivable; no derivation was executed. (b) The end-to-end case with
  fact provenance, transformation and binding to the executed action does not
  exist. **OPEN**: it is the reviewer's own §7 experiment, and WRT-008 is
  deferred until a case like it exists rather than the other way round.
- **§2 MCP proxy loses the events it is there for — ACCEPTED, FIXED, all three
  asks.** A tool absent from the effects config is now sealed as undeclared
  (A4) whatever its name; a name hint is kept as an annotation on the record
  and can never lower the class. An empty effect list is refused at startup
  (exit 2, naming the tool). A seal failure is recorded per call in the
  manifest (`seal_failures`, `seal_failure_log`, `observation_complete:false`)
  and turns the proxy's exit status to 3; the stream is still forwarded.
  Controls in `tests/mcp_seal.py`: the review's four rows, the annotation-only
  hint, the refusal, an undeclared `db.query` sealed end to end, an injected
  `OSError` in the pump, and an unsignable key across the stdio proxy (every
  response forwarded, 0 sealed, 1 failure attributed, exit 3). Not changed:
  arguments are still not inspected — the proxy classifies declarations, and
  the fix makes an undeclared tool loud rather than making the proxy guess.
- **§3 green `verify` reads as permission; `ok` is a boolean — ACCEPTED as an
  integration defect, OPEN as design.** SPEC §11 already binds `ok` to §6
  errors only and the Action's defaults are as stated. What is missing is the
  deployment predicate the reviewer describes (subject, policy, permitted
  signers, required checks and their verdicts). That is a proposal, not a
  patch: **WRT-009**, to be written after the §7 experiment shows what a
  reader of a pack actually needs to ask. Until then the Action's README
  should not gain a sentence; it already says what `ok` is not.
- **§4 semantic bound sold as an operational guarantee — ACCEPTED for this
  repository's docs; already fixed in sigma-glyph.** sigma-glyph's paper v2
  and `SECURITY-ASSUMPTIONS.md` state the bound as semantic and demand a
  verifier admission limit; `docs/authoring-checks.md` ("re-running a
  stranger's reason is safe") and `docs/policy-language-choice.md` ("work and
  peak memory bounded") still carried the wide wording. Both now say: bound on
  the calculus, not the process; the verifier chooses what to afford (SPEC
  §3.1); "three separately implemented engines from one lineage".
- **§5 manifesto — ACCEPTED, fixed there** (manifesto README 0.2.1: each of
  the three sentences carries its type; receipt re-settled). Not this
  repository's finding; recorded for the cross-reference.
- **§6 no measurement of net benefit; SA-12 — ACCEPTED, OPEN.** There is no
  measurement of the whole cycle's cost on external work. It is the same debt
  as Manifesto's controlled-forgetting §14 and it is what §7 would produce.
  SA-12 (sigma-glyph) is documented and open; nothing here changes it.
- **§7 external consumer; the adversarial adjudication experiment — ACCEPTED
  as the next piece of work.** Design, pre-registered before running: a
  third-party agent does a real task through the sealing proxy; the pack
  carries four planted defects (a substituted fact, an irrelevant check, a
  dropped event, an action after a refusal); an adjudicator from another model
  family, without the authors, resolves the dispute from the pack alone versus
  from a plain log plus an ordinary policy check; measured: time to
  adjudicate, defects missed, integration cost. Not started in this PR.

## Amended after Codex's review of PR #63 (2026-09-07)

- **R1 (P1).** A server that performed an effect and exited without
  responding left the proxy at exit 0 with `observation_complete: true` and
  zero records — the new completeness field meant only "no caught seal
  exception". Now: at server EOF every request the host sent and never got
  answered is listed in the manifest as `unreturned_calls` (tool, class,
  effects, source, consequential), the downstream exit code is recorded,
  `observation_complete` is false with `incomplete_because` stated, and the
  proxy exits 3. Nothing is invented about the outcome. Controls: Codex's own
  probes (clean EOF without response, crash exit 7 after the effect, and the
  answered control) reproduced in `tests/mcp_seal.py` with an effect marker
  proving the operation ran; 44 checks.
- **R2 (P2).** My first correction of the arithmetic rationale named the wrong
  encoding (Church numerals) and asserted an unmeasured cost. WPL integers are
  fixed-width bit vectors of Church booleans; arithmetic is simply not
  implemented and not admitted. Hint, tutorial and this file corrected
  together; `EXP-ADR011-01` demoted to related work.
- **R3 (P2).** "0 of 58 derivable" reversed the distinction PR #60's R5 had
  already repaired. WRT-008's statement is "0 of 58 carry provenance"; 48 were
  classified candidate-derivable and no extraction was executed. Corrected in
  the tutorial and above; WRT-008's deferred status and reactivation condition
  are cited as recorded.

## What this review changed

`impl/warrant_mcp.py` (classification, declaration validation, loss
accounting, exit status), `tests/mcp_seal.py` (31 checks, was 15),
`impl/policy_lang.py` (the arithmetic hint), `docs/authoring-checks.md`,
`docs/policy-language-choice.md`; in manifesto, README 0.2.1; in sigma-glyph,
an inbox pointer. Nothing in SPEC, the vectors or the Action moved.

## Not done, and why

- The end-to-end fact-provenance case and the §7 experiment: one piece of
  work, pre-registered next, not folded into a fix PR.
- WRT-009 deployment predicate: after that experiment.
- Argument inspection in the proxy: out of scope by the proxy's own contract
  (it seals declarations, it does not authorize).
