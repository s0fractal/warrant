# Warrant

**When a machine says something was allowed, can you check why — without
trusting the machine that allowed it?**

Warrant is a small, signed, content-addressed decision record. It names what was
decided, the exact policy bytes in force, the reasons and evidence, the actor,
and the decisions that came before it. An executable reason can be re-run by the
reader instead of trusted as a log entry.

```json
{
  "decision": "reject",
  "subject": {"hash": "d5cf37…", "note": "PR-42"},
  "under": ["cb3a0a…"],
  "because": [
    {"kind": "check", "check": "05d234…", "runtime": "cmd@v1",
     "verdict": "fail", "transcript": "9dc0c3…"},
    {"kind": "prose", "text": "policy clause 1: coverage drops"}
  ],
  "evidence": ["9dc0c3…"],
  "actor": {"id": "agent-b@vendor2"},
  "prior": ["00f79f…"],
  "ts": 1751677200
}
```

The canonical body hash is the record's identity. Changing the decision,
policy reference, reason, evidence or prior edge changes that identity. The
signature says which key signed the body; whether that key belongs to the named
actor is a separate trust-configuration question. A rejection is a durable
record, not an absence.

Warrant is not an agent framework, blockchain or observability system. It is one
file format and five filing verbs, designed to be boring.

## Try it

```bash
pipx install warrant-verify   # or: pip install warrant-verify

warrant init
warrant keygen --out me.key
printf 'demo diff\n' > diff.patch
printf 'clause 1: no coverage drop\n' > policy.txt
printf '#!/bin/sh\nexit 1\n' > check.sh && chmod +x check.sh

POL=$(warrant policy add policy.txt)
P=$(warrant propose --subject diff.patch --under "$POL" \
      --reason "utility functions needed" --actor me@host --key me.key)
R=$(warrant reject "$P" --check check.sh --verdict fail \
      --reason "clause 1: coverage drop" --actor me@host --key me.key)
printf '#!/bin/sh\nexit 0\n' > check.sh
A=$(warrant accept "$R" --check check.sh --verdict pass \
      --actor me@host --key me.key)

warrant why "$A"
warrant verify
```

Every file used above is created above. The final warnings say that the key-to-
actor binding is unverified until a trust configuration supplies that authority;
a valid signature is not silently promoted into a valid identity claim.

The `warrant-verify` distribution installs four commands:

- `warrant` — file, inspect and verify decisions;
- `warrant-mcp-server` — let an MCP client file its own decisions;
- `warrant-mcp` — seal calls passing through another MCP server;
- `warrant-anchor` — batch WarrantIDs into a Merkle anchor.

`ski@v1` reasons replay offline through one bundled Σ-GLYPH Book I v0.5
evaluator, pinned by digest and checked before import. Reserved `ski@v2` is not
admitted by any body version and ships no executable candidate bytes.

The longer walkthrough, including negative controls, is
[`docs/try-this-in-fifteen-minutes.md`](docs/try-this-in-fifteen-minutes.md).

## Machine boundary

For CI, MCP or an agent framework, verify an initialized store with
`--store-mode --json`:

```sh
warrant --store ./evidence-pack/.warrants verify --store-mode --json | jq -e '.ok'
warrant-go verify --store-mode --json ./evidence-pack/.warrants | jq -e '.ok'
```

```json
{"report":"warrant.verify-report@v0","grade":"base","ok":true,
 "records":3,"errors":0,"warnings":1,
 "findings":[{"level":"WARN","subject":"<WarrantID>","message":"..."}]}
```

`--store-mode` is part of the safe predicate: a missing or uninitialized store
fails closed instead of looking like an empty successful verification. Python
takes the store through the global `--store`; Go takes it positionally.

Consumers may rely on these boundaries:

- `ok == (errors == 0)`, and the error/warning counts equal the corresponding
  findings;
- `warrant.verify-report@v0` is closed: seven top-level fields and
  `{level, subject, message}` findings;
- Python and Go agree on normative fields and `(level, subject)` pairs; `message`
  is human prose and may differ;
- `grade` distinguishes `base` from `settlement`;
- the report is unsigned and carries **no Warrant authority**.

The normative contract is [`SPEC.md` §11](SPEC.md#11-verification-report--warrantverify-reportv0),
with [`schemas/verify-report-v0.schema.json`](schemas/verify-report-v0.schema.json)
alongside. `tools/check_release_surface.py` fails CI and publishing when the
documented CLI surface is absent from the checkout or built wheel.

## Re-execute a real specimen

The Air Canada specimen is an authored reconstruction of the decision record
the airline did not have; it is not evidence produced by Air Canada.

```bash
pipx install warrant-verify==0.9.0
curl -LO https://github.com/s0fractal/warrant/releases/download/v0.8.0/air-canada-pack.zip
echo '74b36f1d5c7777ea9a3ee240e32f992483a3cd2c0dda0c7d065229c49f1a8249  air-canada-pack.zip' | shasum -a 256 -c
unzip air-canada-pack.zip
warrant --store air-canada-pack/.warrants verify
warrant --store air-canada-pack/.warrants check b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f
```

The last command re-executes the content-addressed, ATP-bounded reason locally;
it does not merely read the filed verdict. The pinned asset, source specimen and
portable layout are documented in [`demos/air-canada/`](demos/air-canada/),
[`EVIDENCE-PACK.md`](EVIDENCE-PACK.md) and [`PUBLISHING.md`](PUBLISHING.md).

## Integrate it

As a GitHub Actions gate:

```yaml
- uses: s0fractal/warrant@v0.6.0
  with:
    store: ./evidence-pack
    version: '0.6.0'
```

Pin `0.6.0` or newer for domain-separated signatures. The action checks the
required capability, emits the machine report and fails on verification errors;
see [`action.yml`](action.yml).

From an MCP client:

<!-- mcp-name: io.github.s0fractal/warrant -->

```bash
warrant-mcp-server --store /abs/path/.warrants
claude mcp add warrant -- warrant-mcp-server --store /abs/path/.warrants
```

The server exposes filing, store verification and reason inspection with fresh
`ski@v1` replay. It is deliberately distinct from `warrant-mcp`, the sealing
proxy for somebody else's downstream MCP server. See
[`integrations/mcp-server/`](integrations/mcp-server/) and
[`integrations/mcp/`](integrations/mcp/).

## Contract map

| Surface | Authority |
|---|---|
| Record format, canonicalization, signatures, replay, settlement and trust config | [`SPEC.md`](SPEC.md) |
| JSON schemas | [`schemas/`](schemas/) — derivative; SPEC remains normative |
| Portable `.warrants/` bundle | [`EVIDENCE-PACK.md`](EVIDENCE-PACK.md) |
| Writing WPL checks | [`docs/authoring-checks.md`](docs/authoring-checks.md) |
| WPL design boundary | [`docs/policy-language-choice.md`](docs/policy-language-choice.md) |
| Threat model | [`THREAT-MODEL.md`](THREAT-MODEL.md) |
| External implementation contract | [`conformance/`](conformance/) |
| Releases and artifacts | [`PUBLISHING.md`](PUBLISHING.md) and [`CHANGELOG.md`](CHANGELOG.md) |

The Python reference implements the five filing verbs and settlement. Go is an
independent verify/settle implementation. Rust is a from-scratch base-grade
implementation including Ed25519 verification. All three were produced within
one author/model lineage: agreement is conformance evidence, not independent
custody or adoption.

```bash
python3 impl/warrant.py conformance examples
python3 impl/warrant.py selftest
(cd impl-go && go build -o warrant-go .)
./impl-go/warrant-go conformance examples
(cd impl-rs && cargo build --release)
./impl-rs/target/release/warrant-rs conformance examples
python3 tests/differential.py
```

A fourth JavaScript candidate was created without Warrant implementation source
and reached the complete base grade under a self-certified iterative local-model
experiment. Its settlement grade is unimplemented. This establishes bounded
implementability against that frozen corpus, not external custody, adoption or
correctness beyond it; see [`needs/README.md`](needs/README.md).

To test another implementation without executing ours:

```bash
python3 conformance/run.py --candidate "./your-verifier probe"   # 139 vectors
python3 conformance/run.py --candidate "./your-verifier probe" --self-check
```

The runner checks the candidate's typed answer. 62
of the 139 vectors are MUST-REJECT, and the pack reports `base` and `settlement`
separately. Details and digest verification are in
[`conformance/README.md`](conformance/README.md).

## Breaking signature boundary

Since release `0.6.0`, signatures cover the domain-separated message

```text
"warrant-sig-v1:" || WarrantID_raw
```

rather than the bare WarrantID. There is no dual-accept window. Pre-0.6.0
signatures therefore do not verify under the current protocol. Where the old
signing key is available, migrate only signatures — WarrantIDs and body links do
not change:

```bash
warrant resign --key mykey.key --dry-run
warrant resign --key mykey.key
```

## Settlement

Settlement is a separate verification grade defined by SPEC §5.1, §7, §9 and
§12. It derives key state and active roots from explicit trust configuration,
replays settlement-active reasons, and requires new evidence or a new outcome
fingerprint to reopen a subject. Prose alone never reopens settlement.

```bash
python3 impl/warrant.py verify --settlement --trust-config trust.json
python3 impl/warrant.py settle <settling-wid> candidate-body.json
./impl-go/warrant-go verify --settlement --trust-config trust.json <store>
python3 tests/settlement.py
```

An unusable requested trust configuration fails closed; it does not fall back to
a clean base-grade report. `genesis.json` is advisory unless explicitly pinned
by the verifier.

The only known format consumer is the sibling `sigma-glyph` repository. It is a
working same-author integration, not outside adoption. Published software,
protocol adoption, green CI, self-review and independent validation remain
different claims.

License: MIT.
