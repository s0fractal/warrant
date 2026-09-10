# WRT-012 — ROOT-0.1: an ownerless trust root for the four repositories

**Status: DRAFT rev 1 (2026-09-10). A plan, not a decision, not an adoption.**
Written by the maintainer actor `claude-fable-5-1` after the owner's verbal
"повністю зрозумів" in chat on 2026-09-10. That is authorization to write this
plan and to prepare branches; it is not a threshold warrant, and nothing here is
adopted (warrant `AGENTS.md` rule 2). Filed in two places on purpose: this
file under `~/Projects/` so it survives a session ending, and as
`proposals/WRT-012-ownerless-root.md` on branch `wrt-012-ownerless-root` in
warrant, where the gate rounds will be appended.

Companion notes: `~/Projects/TRUST-ROOT-WITHOUT-OWNER-2026-09-10.md` (why),
`~/Projects/BLACK-HEART-STUDY-2026-09-10.md` (what black-heart does today).

Answer to the owner's question: **yes, this is the purpose spec of a new WRT in
warrant.** Warrant is the normative repo of the stack; the other three consume
the profile. The number 012 is free as of warrant `c25d494`.

---

## 0. Provenance check — what already exists, so this does not duplicate it

| Repo | Existing thing | What it is | What it is not |
|---|---|---|---|
| warrant | `trust-config.json` (`genesis_roots`, `genesis_json_sha256`, actor keys) | roster trust for warrants | a root outside the roster's custody |
| warrant | `trust/*.json` | evaluator/anchor trust sets | time-anchored or externally held |
| warrant | WRT-010 fact provenance, WRT-011 bounded aggregation | provenance of facts inside a pack | provenance of the pack's *verdict* |
| sigma-glyph | SA-5 / SA-5b | honest count: 2-of-3 satisfied by one custody | a remedy |
| sigma-glyph + warrant | `x1-cross-repo.yml` | HEAD-vs-HEAD coupling canary, daily | a record that either repo *holds* the other's head |
| manifesto | embedded-claims: `verifier` closure digest, `dep.sha256` | external verifier identity and operand pin | a time anchor or a holding |
| black-heart | `continuation/x0000_check.py` anchor | the one externally supplied anchor in that repo | used by any of the 35 engines |
| black-heart | everything else | trust roots read from the artifact; secret keys inside artifacts | a root |

Search on 2026-09-10 for `opentimestamps`, `ots`, `timestamp authority`,
`zenodo` in warrant `SPEC.md`, `THREAT-MODEL.md`, `ARCHITECT.md`,
`PUBLISHING.md`, `proposals/*.md`: **no hits.** Nothing in the stack anchors a
digest in proof-of-work time or records an independent holding. That is the
gap this WRT fills, and nothing else.

## 1. The fulcrum, in one sentence

Every verdict word emitted by the stack (`VERIFIED`, `SETTLED`, `SOUND`,
`REPLAYED`, `ADOPTED`) must name a **root record** whose digest is held
outside the emitting repository, by at least one holder the emitting
repository cannot change, or the tool prints `UNROOTED`.

Two ownerless holders exist today at zero cost:

- **Bitcoin time** via OpenTimestamps (`ots` v0.7.2 is installed on the
  maintainer host). Gives "digest D existed not later than block N". Nobody
  can edit the block or revoke the attestation.
- **Zenodo** as independent institutional custody. Warrant's flagship is
  already deposited as `10.5281/zenodo.22172098`; sigma-glyph's paper v2 as
  `10.5281/zenodo.22646920`. Zenodo records file checksums it computed itself.

A third source is not a holder but a recomputation: the **verifier closure
digest** (manifesto already emits `settle-gate://sha256:…`). Nobody owns a
digest; it is matched or not.

## 2. ROOT-0.1 record

One JSON document, canonical (sorted keys, compact separators, UTF-8, no
floats), content-addressed by its own SHA-256.

```json
{
  "schema": "root.v0.1",
  "subject": {"kind": "git-commit | file | bundle | warrant-record",
              "sha256": "<64 hex>", "ref": "<human pointer, informative>"},
  "verifier": {"closure_sha256": "<64 hex>", "ref": "<tool path@commit>"},
  "time": {"kind": "ots", "proof_sha256": "<64 hex of the .ots file>",
           "status": "PENDING | BITCOIN(<height>) | UNCHECKED"},
  "holdings": [
    {"holder": "zenodo:10.5281/zenodo.NNN", "holder_head": "<zenodo file checksum>",
     "observed": "<ISO date>", "custody": "zenodo"},
    {"holder": "git:s0fractal/sigma-glyph", "holder_head": "<commit sha>",
     "observed": "<ISO date>", "custody": "github:s0fractal",
     "sig": "<ed25519 over this holding by that repo's CI key, optional>"}
  ],
  "prev": "<sha256 of the previous root record for this subject line | null>"
}
```

Rules:

- `subject.sha256` is what a verdict is about. A verdict without a matching
  `subject.sha256` is not rooted by this record.
- `time.status` is exactly what `ots` can prove. `PENDING` = calendar
  attestation only; `BITCOIN(h)` = `ots verify` succeeded against a Bitcoin
  header source; `UNCHECKED` = `.ots` present, no header source available at
  check time. The label never outruns the predicate.
- `holdings[].custody` is a free string, but the **custody count** is the
  number of *distinct* custody strings, and the honest count for the four repos
  under one GitHub account is **1**, plus Zenodo = **2**. This is SA-5's
  counting rule applied to holdings.
- `prev` makes the record line append-only per subject line. A record with a
  `prev` that does not resolve is `UNROOTED`.

Verdict vocabulary emitted by `root.py check`:

```
ANCHORED(block N)            time.status == BITCOIN(N)
ANCHORED_PENDING             time.status == PENDING
HELD_BY(n, custodies m)      len(holdings), distinct custody
UNROOTED                     no record, subject mismatch, broken prev, or verifier mismatch
```

No truth semantics. Binding (WRT-010) and settlement (WRT-005) stay separate.

## 3. The tool — `tools/root.py`, one file, stdlib + `ots` CLI

Target ≤ 250 lines, Python 3.11, zero third-party imports (warrant policy).
Four verbs:

| Verb | Input | Output | Notes |
|---|---|---|---|
| `stamp <path\|sha256>` | subject bytes or digest | `<name>.ots` (pending) + a root record with `time.status=PENDING` | shells out to `ots stamp`; digests are public information, nothing else leaves the host |
| `upgrade <record>` | record with pending `.ots` | record with `BITCOIN(h)` or unchanged | `ots upgrade` then `ots verify`; without a header source, sets `UNCHECKED`, never `BITCOIN` |
| `hold <record> --holder <id> --head <sha> --custody <str>` | a record + one holding | new record with `prev` = old | append-only; refuses to rewrite |
| `check <record> --subject <sha256> [--verifier <sha256>]` | record + what the caller is about to call verified | one verdict line from §2 | exit 0 on ANCHORED*/HELD_BY, exit 2 on UNROOTED |

Mutation tests shipped with it (the "burn it" rule): edit `subject.sha256` →
UNROOTED; drop `prev` link → UNROOTED; relabel `PENDING` as `BITCOIN` by hand →
`check` recomputes from the `.ots` bytes and refuses; add two holdings with the
same custody string → custody count stays 1.

Header-source question (open, §8): `ots verify` needs a Bitcoin node or a
trusted header set. CI has neither. Proposal: pin `tools/bitcoin-headers.json`
with `{height, merkle_root, block_hash}` for the specific blocks cited, fetched
by the maintainer from two independent explorers and committed; `check` uses
that set, and states `UNCHECKED` for any height not in it. Adding a header is a
reviewable diff, which is the point.

## 4. Per-repository modification plan

Each step is independently landable and independently useful. Order matters
only within a repo.

### 4.1 warrant (normative; the profile lives here)

1. `proposals/WRT-012-ownerless-root.md` — this document, on branch
   `wrt-012-ownerless-root`. Gate rounds appended as §10+ in the WRT-010 style.
2. `tools/root.py` + `tests/test_root.py` (mutations above) on the same branch.
3. `holdings/README.md` + first records: subject = warrant flagship bytes at
   `d83984f`; holdings = Zenodo checksum (custody `zenodo`) + sigma-glyph HEAD
   (custody `github:s0fractal`). Stamp with `ots`. This produces the first
   record whose honest line reads `ANCHORED_PENDING; HELD_BY(2, custodies 2)`.
4. `.github/workflows/hold.yml` (weekly, `workflow_dispatch`): `git ls-remote`
   the other three repos' `master`/`main` heads, run `root.py hold`, `ots
   stamp` the new record, commit to branch `holdings` (**not** `master`,
   `AGENTS.md` rule 1), open no PR. The branch is append-only by `prev`.
5. Verdict grep: in `ci.yml`, after the existing suites, run the verify surface
   (`impl/` verify command over `examples/`) and fail if any output line
   matching `VERIFIED|SETTLED|ADOPTED` lacks `root=<sha256>`; run once more
   with no record and assert `UNROOTED` appears.
6. `SPEC.md`: no change in rev 1. The profile is additive; SPEC changes, if
   any, come after a gate round says the record format is stable.

Not changed: WarrantID, signature construction (DEC-001 territory), roster
policy, settlement rules.

### 4.2 sigma-glyph (governance consumer)

1. `SECURITY-ASSUMPTIONS.md` SA-5: add one paragraph and one column: for each
   adoption in `.warrants/records/`, the holdings count and custody count from
   its root record, or `UNROOTED` if none. Today every row reads `UNROOTED`;
   that is the truthful starting line.
2. `.github/workflows/hold.yml` mirror of warrant's (§4.1.4).
3. `.warrants/records/`: adoption records get `ots stamp` at adoption time
   (the maintainer's one non-delegable command, SA-5b, gains one more line).
4. Verdict grep on the arbiter's output (`ADOPTED`, `SETTLED`).

Not changed: the arbiter, the three-inputs/receipt design (v0.7.0), PyPI
release process.

### 4.3 manifesto (execution consumer)

1. `drafts/embedded-claims-poc/claims.py run`: after the vector report, compute
   the compiled-bundle digest (already available as the runner's bundle id),
   `root.py stamp` it, write the `.ots` and record under
   `drafts/embedded-claims-poc/anchors/`. Report gains one document-level line:
   `root: ANCHORED_PENDING | UNROOTED`. Per-record verdicts (`REPLAYED`,
   `MISMATCH`, `STALE`) are unchanged and still carry no document-level truth.
2. `embedded-claims-poc.yml`: run with `--root`, keep `--strict` semantics.
3. `.github/workflows/hold.yml` mirror.
4. Verdict grep on `REPLAYED` lines: each must be followed by the bundle's
   root line in the same report.

Not changed: capsule.v2 schema, verifier closure identity, `KNOWN_CLASSES`.

### 4.4 black-heart (the repo that needs it most)

Precondition, from the study §3: `cli.py verify` currently crashes or
mis-sniffs for nearly every document type. `--root` gating a function that
raises `ImportError` proves nothing. So:

0. Fix exactly the crashes, not the engines: `polyglot.py:234` and
   `monad.py:699/701` tuple-unpack → use `EvalResult` fields; `cli.py:151`
   `LivingLedger.verify()` → call the ledger's chain/signature checks that
   exist; `cli.py:126/135` import `audit_self`/`audit_zkp` → call the library
   auditors that exist or drop those branches; `cli.py:155/164` manifest
   prefixes → match what compilers emit; drop `Colony.load_from_polyglot`.
   Add one test per branch that compiles a fresh document and runs
   `cli.py verify` on it. This is a bounded PR.
1. `cli.py verify --root <record>` **required**; without it the command prints
   `UNROOTED` and exits 2, the same fail-closed shape `adjudicate` already has
   with `--pinned-author-pk`. `--allow-unrooted` exists for demos and prints
   `UNROOTED` on every line anyway.
2. Runner templates: every `print("... VERIFIED ...")` / `SOUND` / `Q.E.D.` in
   the embedded runners becomes `print(f"... {verdict}")` where `verdict` is
   `UNROOTED` unless the runner was given a record via argv. This is a
   mechanical edit across the runner strings; the study lists them.
3. `holdings/` + `hold.yml` mirror; black-heart's first holding is the other
   three repos' heads, and its first stamped subject is the study's HEAD
   `1bf7ad3`.
4. Verdict grep over `python3 test_all.py` output and over every
   `examples/*.pdf` executed with `--audit`: no `VERIFIED|SOUND|SETTLED|Q.E.D.`
   without `root=`.

Not changed in this WRT: the 35 engines' internals, secret-key-in-artifact
(separate finding, separate PR), `cegis_kernel.parse_term` `eval` (separate,
one-line fix, should land first).

## 5. Custody accounting — the honest table to maintain

| Holder | Custody string | Independent of the four repos? |
|---|---|---|
| Bitcoin (via ots) | `bitcoin` | yes, but time only; not a holder of bytes |
| Zenodo | `zenodo` | yes |
| GitHub `s0fractal/*` incl. all CI keys | `github:s0fractal` | no, one custody for all four |
| Codex / Gemini / Kimi sessions | none | they hold nothing between sessions (study, Kimi dialogue) |

Honest line for any record today: `HELD_BY(n, custodies ≤ 2)`. A third custody
appears only when an outside party runs `root.py hold` on our heads from their
own repo or ledger. That is the invitation the owner made to Kimi; it becomes
real only as a record in *their* store.

## 6. Order and cost

| Step | Where | Size | Depends on |
|---|---|---|---|
| A | warrant §4.1.1–2 (WRT + tool + tests) | 1 day | nothing |
| B | warrant §4.1.3 first record | 1 hour | A, `ots` on maintainer host |
| C | black-heart §4.4.0 verify fixes | ½ day | nothing (can run parallel to A) |
| D | `hold.yml` ×4 | ½ day | A |
| E | consumers §4.2–4.4.1–2 | 1 day | A, C |
| F | verdict grep ×4 | ½ day | E |
| G | gate round on WRT-012 (OpenRouter, normative → per multifamily policy) | 1 round | A–F on branches |

If the session ends after any row, the rows above it stand on their own: A is a
proposal plus a tool; B is one real anchored record; C is a bug-fix PR
black-heart needs regardless.

## 7. What this does not claim

- Not a consensus, not a mesh, not a network. Two holders and a clock.
- Not authenticity of content. `ANCHORED` says "existed by block N", `HELD_BY`
  says "these others recorded this digest". Neither says the artifact is
  correct, and `check` never emits a word that implies it.
- Not a fix for black-heart's self-attestation family by itself. It is the
  external root that family lacked; the family's per-engine defects remain and
  are listed in the study.
- Not a replacement for roster warrants. Adoption stays a threshold warrant;
  this WRT gives adoption records a root they currently do not have.

## 8. Open questions (for the gate)

1. Header source for `ots verify` in CI (§3). Pinned header set vs.
   `UNCHECKED` forever vs. a maintainer-run `upgrade` step.
2. `holdings` branch written by CI: same custody as `master`; is a branch the
   right store, or should holdings be artifacts attached to releases?
3. Should `hold` require a signature by the holding repo's CI key? It adds no
   custody (same account) but does bind the holding to that repo's commit line.
4. Zenodo holding: the checksum Zenodo records is MD5 for older deposits. A
   holding whose `holder_head` is MD5 is weaker than SHA-256; state it, or
   re-deposit with a SHA-256 manifest inside the file.
5. Whether `UNROOTED` should fail warrant's CI on day one (it will fail
   everywhere) or be a warning for one release cycle. Recommendation: fail,
   because a warning is a label wider than its predicate.

## 9. Relation to the rest of the stack

- WRT-010 (fact provenance) says where a fact came from; WRT-012 says where the
  *verdict about the pack* can be checked from outside. They compose: a pack's
  provenance document is a natural `subject`.
- WRT-005 settlement fingerprints get a `subject` line each; settlement stays
  the same, its record gains a time.
- manifesto's controlled-forgetting norm: a root record is derivable from its
  `.ots` and holdings, so records are removable in the norm's sense only if the
  `.ots` bytes are kept. Keep the `.ots`; forget the JSON if needed.
- Decision-archaeology loop: this WRT is the resolve step for a need that was
  never filed as a need. File `needs/NEED-004-external-root.md` alongside, so
  the loop has its case→need→resolve shape.

## 10. Gate rounds

*(appended in place as they happen; none yet)*
