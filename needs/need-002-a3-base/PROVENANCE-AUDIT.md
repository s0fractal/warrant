# A2→A3 provenance audit

This audit addresses a narrower question than conformance:

> Can the final semantic module bytes be traced to model responses whose
> request payloads were constructed from the frozen specification, frozen
> conformance material, prior model outputs, runner output, and
> orchestrator-authored runtime probes — without Warrant implementation source
> as an input?

Run:

```sh
node audit-provenance.mjs
```

The verifier reconstructs all four inherited A2c prompts byte-for-byte from the
frozen `SPEC.md` and `CONTRACT.md`. It then reconstructs the two accepted A3
repair prompts from those same operands plus public vectors, prior model
modules, runner output, and the two recorded Node diagnostics. It checks
prompt and response digests, model identities, extraction state, final module
bytes, contribution-ledger hashes, the final report, and the flat import
boundary. The boundary scan includes experiment-owned `candidate/main.mjs`,
whose bytes are pinned separately from the semantic modules and receive no
implementation credit.

The historical prompt headings overstate two inputs and are retained only
because changing them would falsify the recorded prompt bytes:

- `reports/q1-verify-store.json` is a **curated nine-result extract**, not an
  exact report emitted by conformance runner 1.2.0. It omits the runner's
  counts, tag, and negative-vector summary, and retains the orchestrator's
  absolute candidate locator.
- `diagnostics/verify-sig-q1-node.json` and
  `diagnostics/verify-sig-q2-node.json` contain machine observations selected
  and assembled by the orchestrator. In particular, choosing the
  `verify(null, message, key, signature)` call in q2 is part of the proposed
  repair hypothesis, not a conclusion produced by a neutral diagnostic engine.

No byte-preserved diagnostic generator was retained, and the two historical
candidate states named by `candidate_source_sha256` are not operands in this
compact bundle. The observations therefore cannot be regenerated from the
bundle alone. They remain hash-closed prompt inputs, not independently
replayable machine reports. They execute and disclose no Warrant implementation
source.

The archived A2c prompt builder is included under `provenance/a2c/` and pinned by
digest as historical provenance. This audit does not execute it: it independently
reimplements the frozen prompt construction and compares the resulting bytes.
A2c's own closed-manifest verifier was reported green before this subset was
copied at commit `aad8977e9284b0dc13ecdfc0d37502dabedfc39d`, but that source
commit is only a locator and is not reachable or revalidated from this bundle.

`EVIDENCE-MANIFEST.sha256` closes the compact transferable evidence subset. It
contains the accepted construction chain and all operands needed to rerun the
base-grade result; incomplete and non-improving attempts remain in the full A3
repository but are not silently presented as contributors to this bundle.

## Boundary

This is request-payload provenance, not proof of model weights, runtime
isolation, absence of pretraining knowledge, independent custody, or external
authorship. The frozen normative SPEC itself contains prose references to the
project's reference implementations; it does not include their source bytes.
The claim is therefore **clean-room from implementation code**, not clean-room
from all knowledge or lineage. The final `MET_BASE_ONLY` classification is
self-certified by the experiment owner; this provenance audit is a mechanism
check, not independent adjudication.
