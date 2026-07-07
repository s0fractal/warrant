# Warrant Go implementation

Second implementation for Warrant v0.2, using only the Go standard library.

**Scope (deliberate):** verify-only. This implementation exists to hold the
SPEC's differential bar — "two independent implementations MUST agree on every
WarrantID and every verification outcome" — so it implements canonicalization,
WarrantID, store verification, ski@v1 re-runs and the conformance suites, but
no filing/signing path and no `why`. Author records with the Python reference;
verify them with either. (Opus 4.8 review F7, 2026-07.)

```bash
./impl-go/warrant-go conformance examples
./impl-go/warrant-go sigma-conformance ../sigma-glyph/tests/spec_conformance/vectors.json
./impl-go/warrant-go selftest examples
./impl-go/warrant-go verify examples
```

Canonicalization note: `WarrantID = SHA-256(JCS(body))`. For v0.1/v0.2 this
implementation writes the exact JCS subset required by the spec: UTF-8,
compact separators, object keys sorted bytewise, and integer-only numbers.
Bytewise key sorting is equivalent to JCS UTF-16 ordering here only because
schema keys and ski@v1 check keys are fixed ASCII. Future versions with
free-form object keys must replace that shortcut.
