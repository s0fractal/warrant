# Warrant

**A decision record for AI agents. Signed, hash-addressed, with reasons you can re-run.**

When an agent accepts, rejects, or proposes something, it writes a warrant: a small JSON record that says **what** was decided, **under** which policy, **because** of which reasons, based on **which** evidence — signed by the actor, addressed by its own hash, linked to the decisions that came before it.

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

Installs the `warrant` verifier and the `warrant-mcp` sealer. `ski@v1` reasons
re-run **offline** — the Σ-GLYPH Book I check engine ships inside the package, so
no separate clone is needed. (From a checkout: `git clone … && pip install .`.)

```bash
warrant init                          # .warrants/ store in your repo
warrant keygen --out me.key           # Ed25519; prints your pubkey
printf 'demo diff\n' > diff.patch     # the thing being decided about
POL=$(warrant policy add examples/policy.txt)   # pin the rules in force -> hash

P=$(warrant propose --subject diff.patch --under $POL \
      --reason "utility fns needed" --actor me@host --key me.key)
R=$(warrant reject $P --check examples/check.sh --verdict fail \
      --reason "clause 1: coverage drop" --actor me@host --key me.key)
A=$(warrant accept $R --check examples/check.sh --verdict pass \
      --actor me@host --key me.key)

warrant why $A                        # decision -> reasons -> checks -> policy, verified
warrant verify                        # every hash, signature, and link in the store
```

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

Two guarantees a consumer may rely on (surfaced by the first external consumer):

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
pipx install warrant-verify
curl -LO https://github.com/s0fractal/warrant/releases/latest/download/air-canada-pack.zip
unzip air-canada-pack.zip

warrant --store air-canada-pack/.warrants verify        # every hash, signature, link
warrant --store air-canada-pack/.warrants why  9084cd23f205cdd6e013deb6c6e2a84e4a5f4f469fb8f77ba443dfed44716f5a
warrant --store air-canada-pack/.warrants check b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f
```

That last line is the part nothing else does: it **re-executes the reason** on
your machine — a content-addressed, budget-bounded Σ-GLYPH term — and prints
`pass result=65cd957fee7e… atp_spent=17`. The same bytes give the same verdict
for anyone, forever. You are not trusting a log; you are recomputing the argument.

The walkthrough is in **[`demos/air-canada/`](demos/air-canada/)**; the packs are
built by `tools/build_release_packs.sh`, which refuses to ship a pack containing
anything key-shaped and verifies each zip the way a stranger will — unzipped, in
an empty directory, with no repo on the path — before it is attached to a
release. Packs ship from **0.5.0 onward**; the release process is in
[`PUBLISHING.md`](PUBLISHING.md). The portable bundle format is specified in
**[`EVIDENCE-PACK.md`](EVIDENCE-PACK.md)**.

## Use it as a CI gate

```yaml
- uses: s0fractal/warrant@master     # or pin a release tag once one is cut
  with:
    store: ./evidence-pack           # a pack, or a .warrants store
    version: '0.5.0'                 # pin the verifier for a reproducible gate
```

Installs the verifier, verifies the store, fails the job on any error, and writes
a summary. Outputs `ok`, `records`, `errors`, `warnings`, and the full
`warrant.verify-report@v0` object. See [`action.yml`](action.yml).

The action does a **capability check, not a version check**: it asks the
installed verifier whether it actually offers `verify --store-mode --json` and
fails with that sentence if it does not, rather than letting you discover it as
an argparse error three steps later.

## What it is not

Not an agent framework. Not a blockchain. Not observability. It is one file format and five verbs, designed to be boring: any language can implement it from the spec in an afternoon, and two implementations agree on every hash.

## Spec and status

`SPEC.md` — the format (v0.3 draft: the v0.1/v0.2 body schema plus v0.3 settlement, key-state and multi-root rules), canonicalization rules, and worked test vectors with real hashes and signatures (`examples/`). Reason runtimes: `prose`, `cmd@v1` (a check command run in a container), and — new in v0.2 — **`ski@v1`**: a portable, deterministic, budget-bounded check. The check is a content-addressed SKI term evaluated per [Σ-GLYPH Book I](https://github.com/s0fractal/sigma-glyph); the verdict is a hash comparison; work AND peak memory are bounded by the ATP budget, so re-verifying a stranger's reason is safe by construction. `warrant check <hash>` re-runs one.

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

First real user: [sigma-glyph](https://github.com/s0fractal/sigma-glyph) files its review adjudications as warrants (`.warrants/` in that repo) — the maintainer's accept/reject decisions are signed, hash-addressed, and cite CI gates as `cmd@v1` checks.

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
