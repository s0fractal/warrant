# A2→A3 provenance audit

This audit addresses a narrower question than conformance:

> Can the final semantic module bytes be traced to model responses whose
> request payloads were constructed from the frozen specification, frozen
> conformance material, prior model outputs, and machine observations — without
> Warrant implementation source as an input?

Run:

```sh
node audit-provenance.mjs
```

The verifier reconstructs all four inherited A2c prompts byte-for-byte from the
frozen `SPEC.md` and `CONTRACT.md`. It then reconstructs the two accepted A3
repair prompts from those same operands plus public vectors, prior model
modules, exact runner reports, and the two recorded Node diagnostics. It checks
prompt and response digests, model identities, extraction state, final module
bytes, contribution-ledger hashes, the final report, and the flat import
boundary.

The archived A2c prompt builder is included under `provenance/a2c/` and pinned by
digest. A2c's own closed-manifest verifier was also run before this subset was
copied; it reported its full evidence tree internally reproducible at commit
`aad8977e9284b0dc13ecdfc0d37502dabedfc39d`.

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
from all knowledge or lineage.
