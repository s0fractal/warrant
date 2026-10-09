# warrant-verify (Rust)

An independent, dependency-free Rust implementation of
[Warrant](https://github.com/s0fractal/warrant): signed, hash-addressed decision
records whose reasons anyone can re-run.

A Warrant record is a small JSON body — the decision, the policy it was made
under, its reasons and evidence, its actor and the decisions it answers. Its
identity (the *WarrantID*) is the SHA-256 of the body's RFC 8785 canonical bytes;
it is signed with Ed25519 over a domain-separated message; and a `ski@v1` reason
is a check any verifier re-executes, bit for bit, instead of trusting the
verdict written next to it.

This crate is the third implementation of the format, beside the Python
reference (`warrant-verify` on PyPI) and Go. It ships:

* a **library** (`warrant_verify`): canonicalization, schema validation,
  WarrantIDs, Ed25519 signing and verification, the `ski@v1` evaluator
  (Σ-GLYPH Book I v0.5), store verification at base and settlement grade, the
  `warrant.verify-report@v0` machine report, and settlement admissibility;
* a **CLI** (`warrant-rs`) with the reference CLI's verbs and flags:
  `init keygen blob policy propose accept reject supersede why check verify
  settle resign conformance selftest probe canon`.

## Held to the reference, byte for byte

"Agrees with the reference" is a strong word here, and it is measured rather
than claimed. The repository's `tests/rs_parity.py` compares this
implementation's **output** — every report line, every exit status, every byte
written into a store — with the Python reference's, over:

* every reference-CLI call made by the project's adversarial test harnesses
  (replayed against a copy of the store they act on);
* randomized settlement-grade stores: genesis roots, threshold policies valid
  and invalid, authorized, forged and conflicting key rotations, re-litigations
  citing `cmd@v1` and `ski@v1` checks, legacy and junk signatures, and hostile
  JSON (floats, duplicate names, deep nesting, byte order marks, UTF-16 blobs,
  lone surrogates) — with a coverage floor of 29 report branches the stores must
  reach for a run to count;
* all 139 vectors of the conformance pack, and fuzzed near-JSON through the
  parser (error messages included).

The comparison has a negative control: before it runs, it is pointed at a
binary that differs by one output byte and must report it.

It reaches **settlement grade** on the conformance pack (139/139, nothing
UNRUN):

```bash
python3 conformance/run.py --candidate "warrant-rs probe" --claim settlement
```

Porting the reference closely enough to match it also found eleven defects in
the reference itself — hostile stores that crashed its verifier, and two
validity verdicts that split from Go's. They are fixed there, and
`tests/reference_defects_2026_10.py` keeps them fixed in all three
implementations.

## No dependencies

SHA-256, SHA-512, Ed25519, the I-JSON parser and RFC 8785 canonicalization are
written in this crate, and `unsafe` is forbidden. Agreement with the reference
is then evidence about the *specification* — not about a cryptography or JSON
library two implementations happen to share.

## Install

```bash
cargo install warrant-verify        # installs the `warrant-rs` binary
```

## Use

```bash
warrant-rs init
warrant-rs keygen --out me.key
warrant-rs propose --subject change.diff --under policy.txt \
    --reason "needed by three modules" --actor me@example --key me.key
warrant-rs verify                                    # SPEC §6, base grade
warrant-rs verify --settlement --trust-config trust.json --json
warrant-rs why <warrant-id>
```

```rust
use warrant_verify::{json, schema, store, verify};

let body = json::parse_ijson(br#"{"warrant":"0.2","decision":"propose",
  "subject":{"hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  "under":["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
  "because":[],"evidence":[],"actor":{"id":"a@example"},"prior":[],"ts":1}"#).unwrap();
assert!(schema::validate_body(&body).is_empty());
println!("{}", store::warrant_id(&body).unwrap());

let report = verify::verify_store(&store::Store::new(".warrants"), true, None);
println!("{} errors, {} warnings", report.errors, report.warnings);
```

## Scope and limits, stated

* **The `warrant` CLI, not the whole Python package.** The PyPI package also
  ships `warrant-mcp` (an MCP sealing proxy), `warrant-mcp-server`,
  `warrant-anchor` (RFC 6962 anchoring) and the WPL policy compiler. Those are
  integrations around the format and are not part of this crate.
* **Signing is not constant-time.** It exists so this implementation can file
  and re-sign records on the machine that holds the key, as the reference CLI
  does. Do not expose it as a signing oracle to anyone who can time it.
  Verification handles only public data.
* **Randomness** (`keygen`, scratch directories) comes from `/dev/urandom`, so
  those two operations are Unix-only.
* **The `ski@v1` evaluator is compiled in.** The reference's `$SIGMA_GLYPH`
  development override (an unpinned evaluator, refused at settlement grade
  anyway) has no equivalent here. `ski@v2` is reserved by the specification and
  admitted in no body version; it is not implemented.
* **Diagnostic wording follows CPython ≥ 3.13.** Where the reference's report
  quotes a JSON or UTF-8 error (`resign`'s "unreadable envelope", the probe's
  parse errors), the text is its interpreter's, and 3.13 changed some of it.
* The record format and its rules are defined by
  [SPEC.md](https://github.com/s0fractal/warrant/blob/master/SPEC.md), not by any
  implementation, this one included.

## License

MIT. See [LICENSE](LICENSE).
