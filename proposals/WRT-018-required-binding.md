# WRT-018: Let the reader require that a record's actor signed with a bound key

**Status:** DECIDED: option A, 2026-10-16. The owner delegated the decision ("на твій розсуд"), and Claude chose A. Implemented in Python, Go and Rust (`verify --require-bound`). SPEC §5.1 carries the sentence, recorded in contract KEY-B1. Conformance pack 1.4.0 adds five vectors. The JS/WASM package gains `requireBound` in its next release.

## The finding (two consumers, measured)

At settlement grade with the reader's trust config, a record whose actor signed with
a key the config does not bind to that actor verifies `ok: true, errors: 0`. The only
signal is `WARN signature unbound: key … claims actor …`. This is specified behaviour.
SPEC §5.1 says "Bound/unbound is a report unless a v0.3 policy explicitly makes bound
signatures required for settlement-grade verification", and the only such policy
today is a threshold policy chosen by whoever files the record.

Two consumers have now each rebuilt the missing rule outside warrant:

- **`oaip`** (sibling ledger). Its source says "`warrant verify` CANNOT be configured
  to fail on an unbound signature". It enforces the rule over its own keyring and
  corroborates by parsing warrant's text output for `signature unbound` lines.
- **`warrant-pdf`** (two-party contract PDFs, 2026-10-16). With Bob's key in the
  reader's trust config, an accept for `bob@…` signed with Mallory's key verified
  `ok: true`. warrant-pdf therefore refuses on every finding except
  `unadopted root`. Measured consequence: an appended junk co-signature, even a
  cryptographically invalid one claiming an unrelated actor, refuses the whole
  contract. warrant's own envelope rule says that co-signature is "reported and
  excluded, never fatal" (§5).

So each consumer either parses message text or over-refuses. Both re-derive a binding
decision that the verifier has already made.

## Options

| | Rule | Who decides | Cost |
|---|---|---|---|
| A | A **verifier option** (`--require-bound`; JS `{ requireBound: true }`), valid only at settlement grade. A record is an ERR, `no bound signature by body.actor.id`, when no cryptographically valid signature by `body.actor.id` is bound at that record's position. Unbound or invalid co-signatures by other actors stay WARN-and-excluded. | the reader, like the re-execution budget (§3.1) | one option and one ERR message in Python, Go and Rust; JS passes it through; the conformance probe gains an input field; new settlement vectors |
| B | Report bound/unbound per record in a new report version (`warrant.verify-report@v1`, per-record `actor_bound`) | the consumer, from the report | a new closed schema in every implementation; every consumer still writes the rule itself |
| C | A v0.3 policy blob kind, `{"warrant_policy":"0.3","require_bound":true}`, cited in `under` | **the filer** | the document decides whether its own binding is checked. That is the wrong direction for the case above, where the forger chooses `under`. |
| D | Change the default: unbound by `body.actor.id` is always an ERR at settlement grade | the format | breaks every existing settlement-grade store where an actor's key is legitimately absent from one reader's config (partial keyrings are normal); not opt-in |

**Recommendation: A.** It is local verification policy, in the same category as
the re-execution budget and the resource fences: two readers with different settings
can disagree, and that is a stated local choice, not a schema split. It changes no
body, record, report schema or WarrantID. It is the exact predicate both consumers
need. It keeps §5's co-signature rule intact, which the over-refusing workaround
breaks. B leaves the rule to be re-implemented again. C lets the forger opt out. D
breaks partial keyrings.

## If A is chosen: what the change would be

- **SPEC §5.1**, after the bound/unbound sentence: a verifier MAY offer a
  *required-binding* option at settlement grade. With it, a record with no valid
  signature by `body.actor.id` that is bound at the record's DAG position MUST be
  reported `ERR: no bound signature by body.actor.id`. Other signatures keep their
  §5 treatment. The option MUST refuse to run without a trust configuration (base
  grade has no binding to require).
- **Implementations**: Python `impl/warrant.py` (the `signature unbound` branch at
  line 2052), Go `impl-go/main.go:3063`, Rust `impl-rs/src/verify.rs:264`. The ERR is
  derived from the same `bound` computation that already emits the WARN. Nothing new
  is computed.
- **Conformance**: `verify-store-settlement` vectors gain an optional
  `"require_bound": true` input. At least: (1) actor unbound → 1 ERR; (2) actor bound
  plus a junk co-signature → 0 ERR, 1 WARN; (3) actor bound → 0 ERR; (4) the option
  without a trust config → refused. A candidate that ignores the option fails (1).
- **JS**: `verifyStore(files, { trust, requireBound: true })` once the WASM core is
  rebuilt. This means a package release, which is the owner's action.
- **Contract**: one statement (say `KEY-B1`) with these four vectors as witnesses and
  mutants in each implementation (drop the option, make it apply to co-signatures).

## Also in this change (a correction, not a decision)

THREAT-MODEL A4 placed the "gates on `ok` alone" residual at base grade only. At
settlement grade with a trust configuration and no threshold policy, the same
residual holds: `ok: true` with one WARN. Measured by warrant-pdf (contract WPDF-T2).
The row is corrected in this PR.
