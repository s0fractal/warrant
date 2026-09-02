# Warrant

**When a machine says something was allowed, can you check why — without trusting the machine that allowed it?**

A green CI run, a signed audit log, an agent's own JSON summary: each is a claim
about work, made by the party that did the work, covering exactly what that party
decided it should cover. Warrant is a decision record built the other way round. It
says **what** was decided, **under** which policy — pinned by hash, so "the policy"
is a specific sequence of bytes rather than a name — **because** of which reasons,
on **which** evidence, signed by the actor and addressed by its own hash. A reason
can be an executable check, which means the argument is not something you read. It
is something you re-run, on your own machine, and get the same verdict for.

Concretely: when an agent accepts, rejects, or proposes something, it writes a small JSON record, linked to the decisions that came before it.

```json
{
  "decision": "reject",
  "subject":  { "hash": "d5cf37…", "note": "PR-42" },
  "under":    [ "cb3a0a…  (policy in force, by hash)" ],
  "because":  [
    { "kind": "check", "check": "05d234…", "runtime": "cmd@v1",
      "verdict": "fail", "transcript": "9dc0c3…" },
    { "kind": "prose", "text": "policy clause 1: coverage drops 87.0 -> 84.2" }
  ],
  "evidence": [ "9dc0c3…" ],
  "actor":    { "id": "agent-b@vendor2" },
  "prior":    [ "00f79f…" ],
  "ts":       1751677200
}
```

The record's hash is its identity. Change one byte of the decision, the policy reference, or the reasons — the hash changes, and every later record that cited it stops resolving. Nothing can be quietly edited after the fact.

## Why not just logs?

A trace tells you what an agent did. A warrant proves **why it was allowed to** — and the proof survives the agent. Logs are mutable, vendor-shaped prose. Warrants are:

- **Immutable** — identity is the hash of the content.
- **Signed** — you know which actor decided.
- **Anchored** — `under` pins the exact bytes of the policy that was in force, not "the policy" in someone's memory.
- **Re-checkable** — a reason can be an executable check. Anyone can re-run it and get the same verdict.
- **Linked** — `prior` makes decisions a chain: propose → reject (with reasons) → revise → accept. `warrant why <hash>` walks the whole chain.

A rejection is a first-class record, not an absence. This is the part that matters as agents get autonomy: the "no, because" survives, gets cited by hash, and stops the same argument from being re-had from scratch.

## Ten minutes

```bash
pipx install warrant-verify   # or: pip install warrant-verify
```

Installs four commands: the `warrant` verifier, the `warrant-mcp` sealing proxy,
the `warrant-mcp-server` MCP server, and the `warrant-anchor` Merkle batcher.
`ski@v1` reasons re-run **offline** — the Σ-GLYPH Book I check engine ships
inside the package, so no separate clone is needed. One evaluator per runtime
tag, pinned by digest and checked before it is loaded (`ski@v1` = Book I v0.5,
`sigma_glyph_v05`; reserved candidate `ski@v2` = Book I 0.6.0,
`sigma_glyph_v06`, not registered or admitted in any body version — SPEC §3.2,
§13.2). (From a checkout:
`git clone … && pip install .`.)

The latest release **on PyPI is 0.9.0**, which is what that line installs and
what this checkout is; six versions are published (`0.5.0` … `0.9.0`), and
`CHANGELOG.md` covers them through `0.9.0`. All four commands above, including
`warrant-mcp-server`, come from the published wheel — no checkout required.

Checked on 2026-08-22 in an empty virtualenv: `pip install warrant-verify` gives
`0.9.0` and those four commands, and the walkthrough below runs from that
install alone. That is a maintainer's clean-room check, not a claim that anyone
else has installed it.

```bash
warrant init                          # .warrants/ store in your repo
warrant keygen --out me.key           # Ed25519; prints your pubkey
printf 'demo diff\n' > diff.patch     # the thing being decided about
printf 'clause 1: no coverage drop\n' > policy.txt      # your rules, as bytes
printf '#!/bin/sh\nexit 1\n' > check.sh && chmod +x check.sh   # a check that fails

POL=$(warrant policy add policy.txt)  # pin the rules in force -> hash

P=$(warrant propose --subject diff.patch --under $POL \
      --reason "utility fns needed" --actor me@host --key me.key)
R=$(warrant reject $P --check check.sh --verdict fail \
      --reason "clause 1: coverage drop" --actor me@host --key me.key)
printf '#!/bin/sh\nexit 0\n' > check.sh                 # fix the thing, check passes
A=$(warrant accept $R --check check.sh --verdict pass \
      --actor me@host --key me.key)

warrant why $A                        # decision -> reasons -> checks -> policy, verified
warrant verify                        # every hash, signature, and link in the store
```

Every file the walkthrough needs is created above, so it runs from a `pip
install` with no checkout. `verify` ends with `3 records, 0 errors, 3 warnings`:
the warnings say `binding unverified (no keyring)`, because nothing yet vouches
that the key belongs to `me@host` — that is what a trust config supplies, and
until you write one an unbound signature is reported rather than believed.

The store is plain files, content-addressed, git-friendly. No server, no vendor, no account.

## Machine-readable output (`--json`)

> **Requires `warrant-verify` 0.5.0 or newer.** `0.4.0` (2026-07-16) predates
> this boundary, so against that release the commands below give
> `error: unrecognized arguments: --store-mode --json`. That gap — the README
> documenting a surface no published artifact had — is now a release gate:
> `tools/check_release_surface.py` runs in CI against the checkout and in the
> publish workflow against the built wheel, so a release that cannot do what this
> file promises fails to publish.

For CI, MCP, or an agent framework, add `--json` to `verify` and get exactly one
`warrant.verify-report@v0` object (one physical line) on stdout — no human text to
parse. Add `--store-mode` so a path that is not an initialized store fails closed
(`ok:false`) instead of being silently treated as an empty verification — this is
what makes `.ok` a safe store-verification predicate. The Python CLI takes the
store via the global `--store`; the Go CLI takes it as a positional argument. An
Evidence Pack's store is its `.warrants/` directory:

```sh
warrant --store ./evidence-pack/.warrants verify --store-mode --json | jq -e '.ok'
warrant-go verify --store-mode --json ./evidence-pack/.warrants | jq -e '.ok'   # Go: positional store
```

```json
{"report":"warrant.verify-report@v0","grade":"base","ok":true,
 "records":3,"errors":0,"warnings":1,
 "findings":[{"level":"WARN","subject":"<WarrantID>","message":"..."}]}
```

`ok == (errors == 0)`; the counts and exit status are identical to text mode. Under
`--store-mode` a missing/uninitialized store fails closed (`ok:false`, one `ERR`
with subject `store`) in both implementations, so Python and Go agree on the
**normative** fields — `report`, `grade`, `ok`, `records`, `errors`, `warnings`,
and the set of `(level, subject)` findings; branch on those. A finding's `message`
is human-oriented prose and **may differ between the two implementations** (do not
branch on it). Without `--store-mode`, the Go CLI keeps a legacy flat-directory
mode for loose example files — pass `--store-mode`. The report is **not** a
Warrant: it is unsigned and carries no settlement authority.

Two guarantees a consumer may rely on (surfaced by the first consumer outside this
repository — the sibling `oaip` ledger, which is the same author's, not an outside
adopter):

- **Counts bind the findings.** `errors` equals the number of `ERR` findings and
  `warnings` equals the number of `WARN` findings — always, in both
  implementations. `findings` carries every `ERR`/`WARN` event (never `INFO`), so a
  consumer may cross-check `errors`/`warnings` against the finding levels and reject
  a report where they disagree.
- **`warrant.verify-report@v0` is a CLOSED schema.** Exactly the seven top-level
  keys above, and exactly `{level, subject, message}` per finding — no more. Any
  future additive field ships under a **new tag** (`@v1`), never inside `@v0`, so a
  strict consumer that rejects an unknown top-level or finding key stays correct
  across Warrant versions. Gate on the exact `report` tag you understand.

**The contract is specified in [`SPEC.md` §11](SPEC.md#11-verification-report--warrantverify-reportv0), not here.** This section is the
tour; §11 is what a producer commits to by printing the tag and what a consumer
may rely on when it reads it, with `schemas/verify-report-v0.schema.json`
alongside. Until 2026-07-30 §11 did not exist and this README was the only
statement of a contract a CI system branches on — a machine boundary specified
in a marketing document.

## Try it on a real case

Verify what an AI agent decided — the Air Canada chatbot case, as the record the
airline never had. **No clone, no build, no account.** Download the pack, check
it, and re-run the reason yourself:

```bash
pipx install warrant-verify==0.9.0
curl -LO https://github.com/s0fractal/warrant/releases/download/v0.8.0/air-canada-pack.zip
shasum -a 256 air-canada-pack.zip
# 74b36f1d5c7777ea9a3ee240e32f992483a3cd2c0dda0c7d065229c49f1a8249  air-canada-pack.zip
unzip air-canada-pack.zip

warrant --store air-canada-pack/.warrants verify        # every hash, signature, link
warrant --store air-canada-pack/.warrants why  9084cd23f205cdd6e013deb6c6e2a84e4a5f4f469fb8f77ba443dfed44716f5a
warrant --store air-canada-pack/.warrants check b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f
```

That last line is the part nothing else does: it **re-executes the reason** on
your machine — a content-addressed, budget-bounded Σ-GLYPH term — and prints
`pass result=65cd957fee7e… atp_spent=17`. The same bytes give the same verdict
for anyone, forever. You are not trusting a log; you are recomputing the argument.

The pack is pinned to the `v0.8.0` release because that is the release that
carries it: `releases/latest/download/…` returned **404** once `v0.9.0` shipped
without the asset, so the first command a stranger ran failed. Checked again on
2026-08-23: the pinned URL serves the digest above, and the current
`warrant-verify 0.9.0` verifies that pack and re-executes its reason unchanged.
A step-by-step version with the negative controls is in
[`docs/try-this-in-fifteen-minutes.md`](docs/try-this-in-fifteen-minutes.md).

The walkthrough is in **[`demos/air-canada/`](demos/air-canada/)**; the packs are
built by `tools/build_release_packs.sh`, which refuses to ship a pack containing
anything key-shaped and verifies each zip the way a stranger will — unzipped, in
an empty directory, with no repo on the path — before it is attached to a
release. Packs ship from **0.5.0 onward**; the release process is in
[`PUBLISHING.md`](PUBLISHING.md). The portable bundle format is specified in
**[`EVIDENCE-PACK.md`](EVIDENCE-PACK.md)**.

## Use it as a CI gate

```yaml
- uses: s0fractal/warrant@v0.6.0     # or @master to track HEAD
  with:
    store: ./evidence-pack           # a pack, or a .warrants store
    version: '0.6.0'                 # pin the verifier for a reproducible gate
```

Pin **0.6.0 or newer**. 0.6.0 is the domain-separation flag day (below): a
0.5.0 verifier does not accept a `warrant-sig-v1` signature, so pinning an
older version against a store signed today fails every signature — the
reverse of the 0.4.0/`--json` gap, and just as invisible until it fires.

Installs the verifier, verifies the store, fails the job on any error, and writes
a summary. Outputs `ok`, `records`, `errors`, `warnings`, and the full
`warrant.verify-report@v0` object. See [`action.yml`](action.yml).

The action does a **capability check, not a version check**: it asks the
installed verifier whether it actually offers `verify --store-mode --json` and
fails with that sentence if it does not, rather than letting you discover it as
an argparse error three steps later.

## Use it from an MCP client

<!-- mcp-name: io.github.s0fractal/warrant -->

The package ships an MCP server. Installing it installs the command; there is no
clone step and no MCP SDK dependency.

```bash
warrant-mcp-server --store /abs/path/.warrants
```

That is the process an MCP host launches over stdio. Registering it with Claude
Code is one line:

```
claude mcp add warrant -- warrant-mcp-server --store /abs/path/.warrants
```

Three tools: `warrant_file_decision` files a propose / accept / reject /
supersede and returns the record's hash; `warrant_verify_store` returns the
`warrant.verify-report@v0` object; `warrant_show_reason` returns a decision's
reasons **with its `ski@v1` checks re-executed**, so the fresh verdict arrives
beside the filed one. Details, options and the trust model:
[`integrations/mcp-server/`](integrations/mcp-server/).

**`warrant-mcp-server` is not `warrant-mcp`.** They are two programs in one
distribution and it is worth thirty seconds to get the right one:
`warrant-mcp` is a *sealing proxy* — it wraps somebody else's MCP server and
seals the tool-calls passing through it from the outside
([`integrations/mcp/`](integrations/mcp/)). `warrant-mcp-server` is a *server* —
the agent connects to it and files its own decisions on purpose. The proxy
requires a downstream server command after `--`; the server refuses one.

## What it is not

Not an agent framework. Not a blockchain. Not observability. It is one file format and five verbs, designed to be boring: three independent implementations agree on every hash, and the conformance contract's wire format plus one real class is an afternoon and full base grade is a few days — measured by writing two skeletons, not estimated, and still never measured against anyone who did not already know the format.

## Spec and status

`SPEC.md` — the format (v0.4 draft: the v0.1/v0.2 body schema plus v0.3 settlement, key-state and multi-root rules, plus v0.4's domain-separated signature message), canonicalization rules, and worked test vectors with real hashes and signatures (`examples/`). Reason runtimes: `prose`, `cmd@v1` (a check command run in a container), and — new in v0.2 — **`ski@v1`**: a portable, deterministic, budget-bounded check. The check is a content-addressed SKI term evaluated per [Σ-GLYPH Book I](https://github.com/s0fractal/sigma-glyph); the verdict is a hash comparison; work AND peak memory are bounded by the ATP budget, so re-verifying a stranger's reason is safe by construction. `warrant check <hash>` re-runs one.

`docs/authoring-checks.md` — how to write a `ski@v1` check without knowing what a combinator is. Policy rules are authored in **WPL**, a small expression language (`fact` declarations plus one boolean expression: comparisons, `in`, `&&`, `||`, `!`), and `impl/policy_lang.py` compiles them to the term a verifier re-runs. The compiler reports the exact ATP the check will cost and refuses at authoring time anything it cannot compile inside the budget. It is deliberately *not* trusted code: the verifier re-runs the term, the compilation is reproducible from the pinned source blob, and every compile is checked against the Σ-GLYPH oracle before it is emitted.

```bash
python3 impl/policy_lang.py compile examples/policies/1-threshold.wpl
python3 impl/policy_lang.py verify  examples/policies/1-threshold.wpl
```

`impl/warrant.py` — reference implementation (M1): the five verbs on a plain-file store, one file, stdlib + Ed25519 (`pip install cryptography`). It must pass its own law:

```bash
python3 impl/warrant.py conformance examples   # all SPEC §8 vectors, byte-exact
python3 impl/warrant.py selftest               # live round-trip + tamper detection
```

`impl-go/` — independent Go implementation for cross-checking the spec:

```bash
(cd impl-go && go build -o warrant-go .)       # stdlib-only; binary is not committed
./impl-go/warrant-go conformance examples      # same SPEC §8 vectors
./impl-go/warrant-go selftest examples         # schema and verification edges
```

`impl-rs/` — a third, independent **Rust** implementation (from scratch, no external crates): JCS canonicalization, schema, WarrantID, the weak-key blocklist, **and a from-scratch Ed25519 verifier** (SHA-512 + the 2^255-19 field + Edwards curve). It verifies all three §8 signatures and agrees with Python/Go byte-exact:

```bash
(cd impl-rs && cargo build --release)                 # no crates; binary not committed
./impl-rs/target/release/warrant-rs conformance examples   # §8 WarrantIDs + signatures + §8.3 negatives
./impl-rs/target/release/warrant-rs edtest            # Ed25519 selftest (RFC 8032 TV1)
python3 tests/differential.py                         # three-way canon: PY/GO/RS agree byte-exact
python3 tests/ed25519_differential.py                 # Ed25519: Rust vs Python cryptography agree
```

### Writing a fourth implementation

Three implementations agreeing is evidence about how clearly the document reads
**to the person who wrote it**. A fourth, written by someone who was not here, is
evidence about the document. The invitation, with the contract, the nine classes
and what is and is not true about it so far, is one page:
**[warrant-conformance/1](https://s0fractal.github.io/warrant/conformance.html)**.

`conformance/` is a self-contained pack for checking an implementation that is
**not** one of these three — no clone, no install, and the runner never executes
ours:

```bash
python3 conformance/run.py --candidate "./your-verifier probe"   # 139 vectors
python3 conformance/run.py --candidate "./your-verifier probe" --self-check
```

Your side of it is one page (`conformance/CONTRACT.md`): read one JSON request
from stdin, print one JSON response, exit 0 whenever you produced an answer. 62
of the 139 vectors are MUST-REJECT, so an implementation that accepts everything
fails loudly rather than scoring well; `--self-check` breaks *your* program on
purpose and fails if the runner does not notice — and reports a break that had
nothing to corrupt as `INAPPLICABLE` rather than as its own failure, because on
day one most of your classes do not exist yet. A partial implementation is told
it is incomplete and which class is cheapest to write next; it is never told to
go and read failures that are not there. Grades are reported, not
pass/fail — `impl-rs` claims and reaches SPEC §6 base grade, which is a complete
result, not a shortfall. The pack ships as a release tarball pinned by hash in
SPEC §8.6, and `TRADEMARK.md` conditions the name on it.

The only thing consuming the format so far is a sibling repository by the same author: [sigma-glyph](https://github.com/s0fractal/sigma-glyph) files its review adjudications as warrants (`.warrants/` in that repo) — the maintainer's accept/reject decisions are signed, hash-addressed, and cite CI gates as `cmd@v1` checks. That is a working integration and it is worth reading; it is not an outside user, and there are none. The full picture of who consumes what across the sibling protocols — gated, proposed, or absent — is indexed in the [ecosystem relationship map](https://github.com/s0fractal/protocol-ecosystem).

### Signatures are domain-separated (v0.4, BREAKING)

The message a key signs is **not** the WarrantID. It is

```
"warrant-sig-v1:" || WarrantID_raw          15 + 32 = 47 bytes
```

still pure RFC 8032 Ed25519 over a byte string (SPEC §5, vectors in §8.5). Before
0.6.0 the message was the bare 32-byte WarrantID, which is indistinguishable from
any other SHA-256 digest — so a key that also signed digests in another protocol
produced signatures valid in both. There is no dual-accept window: a verifier
that took the old message too would have no separation at all.

A record signed before 0.6.0 therefore does not verify, and says why:

```bash
python3 impl/warrant.py verify
# WARN <id>  signature does not verify (excluded): LEGACY pre-v1 signature
#            construction ... Re-sign with: warrant resign --key <keyfile>

python3 impl/warrant.py resign --key mykey.key --dry-run   # what would change
python3 impl/warrant.py resign --key mykey.key             # migrate in place
```

`resign` rewrites only `sigs[].sig`, and only where the existing signature is a
valid *old* signature by the key you gave it — so it re-signs what that key
already signed and invents nothing. **No WarrantID moves**: identity is
SHA-256 of the canonical body and the envelope is not hashed. A record whose key
you do not hold is named and the command exits non-zero, because a partial
migration that reports success is worse than one that stops.

License: MIT.

## v0.3: settlement-grade verification (DRAFT)

Beyond integrity (`verify`), v0.3 adds settlement semantics (SPEC §5.1/§7/§9):

```bash
python3 impl/warrant.py verify --settlement --trust-config trust.json
python3 impl/warrant.py settle <settling-wid> candidate-body.json
./impl-go/warrant-go verify --settlement --trust-config trust.json <store>
# NB: Python takes a global --store flag; Go verify/settle take the store as a
# positional argument — Go is deliberately verify-only (no filing surface).
```

Settlement-active roots come from your local trust configuration (plus
policy-authorized adoptions); `genesis.json` is advisory and must be pinned to
be used. Re-litigation of a settled subject requires new evidence or a new
outcome fingerprint — prose never re-opens anything. Key rotation/revocation
are warrants; key state derives from the DAG. Both implementations must agree
on every settlement outcome: `python3 tests/settlement.py`.
