# Warrant Go implementation

Second implementation for Warrant v0.1, using only the Go standard library.

```bash
./impl-go/warrant-go conformance examples
./impl-go/warrant-go selftest examples
./impl-go/warrant-go verify examples
```

Canonicalization note: `WarrantID = SHA-256(JCS(body))`. For v0.1 this
implementation writes the exact JCS subset required by the spec: UTF-8,
compact separators, object keys sorted bytewise, and integer-only numbers.
Bytewise key sorting is equivalent to JCS UTF-16 ordering here only because all
schema keys are fixed ASCII. Future versions with free-form object keys must
replace that shortcut.
