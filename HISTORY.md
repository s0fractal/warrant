# History

## Warrant 2, retired 2026-10-27 by the switch to Warrant 3

Warrant 2 is preserved at the git tag **`history/warrant-2-2026-10-27`**, created by the owner at
commit `b37328b2` (merge of #219), the last master commit on which Warrant 2 was the current
format. Its package stays published as it was: `warrant-graph` 2.0.0a1 on PyPI. The next release
is Warrant 3 (roadmap G12); nothing of Warrant 3 is published by the switch.

What Warrant 2 was: six signed record types (duty, transition, accept, challenge, observation,
grant) in one file per record under `.warrant/store/`, assessed by `warrant/engine.py` under the
receiver's trust and profile (SPEC.md, 2.0.0a1), with `attest`, `observe` and `compute` conditions,
Sigma replay of computations, grants, triggers and schedules; an agent interface
(`warrant_agent`, MCP) over frozen views in an object store; and about 9.7k lines of repository
tools that re-implemented lineage, forks and acceptance per domain: SPEC claims backed by a replay
checker (`tools/claims.py`), the roadmap (`tools/roadmap.py`), the pull request review loop and its
merge gate (`tools/review.py`, `tools/claimslib/eligibility.py`), and the record graph
(`tools/graph.py`).

Its records were migrated, not re-signed: `.warrant/records.jsonl` holds every Warrant 2 record
of `b37328b2` as Warrant 3 records with `sig: null`, vouched for by one `migration@1` attest of the
migrator checker (docs/V3.md §9). The migrator, `tools/migrate_v2_to_v3.py`, depends on the
Warrant 2 package and lives at the tag; its replay is run there. Run on `b37328b2` with Python 3.15
and cryptography 50.0.2, it gave the migrator checker `checker sha256:dd56e635…8826f` (the digest of
its whole import closure, the interpreter and the signature library: another interpreter gives
another actor), genesis `49ad1e41cc56…`, 1 446 migrated records and 1 459 lines with the six
bootstrap schemas and Codex's six schema acceptances, and 473 blobs. Its replay, from a checkout of
the tag with the same interpreter:

```sh
git worktree add ../warrant-2 history/warrant-2-2026-10-27 && cd ../warrant-2
mkdir -p build/v3 && cp -R <switched checkout>/.warrant/records.jsonl <switched checkout>/.warrant/blobs build/v3/
python3 tools/migrate_v2_to_v3.py verify       # IDENTICAL: 1446 replayed, v2 root 649172b24ab6…
```

`IDENTICAL` means only that the re-derived migrated ids equal the store's unsigned ids (docs/V3.md
§9). The differential parity of the migrated store against the Warrant 2 tools, at the tag
(`python3 tests/v3_parity_test.py`): claims 362/362, goals 12/12, obligations 49/49, reviews 19/19
equal, none declared, none undeclared; two declared migration rules applied ("parallel closures").

## Warrant 0.x, retired 2026-10-18 by the Warrant 2 rebuild

The previous generation, Warrant 0.x, is preserved at the git tag
**`history/warrant-0.x-2026-10-18`** (commit `8feb335`, merge of #137). On that
tree `tools/check.py` gave 100 passed, 0 failed, 0 unrun on 2026-10-18. Its
packages stay published as they were: `warrant-verify` ≤ 0.12.0 on PyPI, npm,
JSR and crates.io. Its records, papers and conformance packs verify against that
tag. They are not evidence about Warrant 2, and Warrant 2 does not read them.

The rebuild was mandated by the owner on 2026-10-18: an incompatible rebuild,
one current path, and deletion of the superseded implementations.

### Retired, and what replaced it

| 0.x | Status | Replaced by |
| --- | --- | --- |
| SPEC v0.4: propose/accept/reject/supersede bodies, `prior` DAG, `under`/`because` | retired | SPEC.md: six typed records, no `prior` |
| `cmd@v1`, `ski@v1` reasons; bundled Book I v0.5 evaluator (`sigma_glyph_v05`) | retired | `compute` conditions replayed by the recipient (SPEC §7) |
| `ski@v2` execution path, `sigma_glyph_v06` (unreachable by any record) | retired | — |
| Settlement §7 (tunnels, outcome fingerprints), `tools/settle.py`, gate settlement | retired | admission and disposition (SPEC §4.2–4.3) |
| WRT-010 `fact_provenance`, WRT-020 `policy_binding`, REDESIGN-1 `assessment` (three linkers of policy, facts and decision) | retired | one mechanism: a duty's condition (attest / observe / compute) judged in one view |
| WPL (`policy_lang`), `ski_policy` | retired | a `compute` condition names its term, environment and answer |
| WRT-021/022 drafts (`loops`, `triggers`, `replay`, `grants`) | folded in | `warrant/engine.py`, `warrant/triggers.py`, `warrant/compute.py`; RV-01, RV-02, S2-01..04, GR-01 counterexamples carried as tests |
| Four copies of Σ-GLYPH code (v05, v06, `sigma_resume_c864d3e`, the demo vendor copy) | retired | the installed `sigma-glyph` wheel's `sigma_provider`, accepted by identity in the recipient profile. Warrant 2.0.0.dev0 briefly bundled one copy in `warrant/provider/` (c864d3e); that copy is retired too |
| Subprocess `warrant verify` over a temporary copy of the store | retired | `Snapshot`: bytes read once, assessed in memory |
| Threshold (k-of-n) adoption, key state, pre-rotation, revocation (WRT-014/015/017), P-256 (WRT-019) | retired | not in Warrant 2 (SPEC §9) |
| Go, Rust (`warrant-verify` crate), WASM, JS, web verifier | retired, published versions stay | Python reference only |
| Conformance pack, skeletons, schemas, Lean/Creusot proofs of the 0.x encoders | retired | `tests/primitives_test.py` (vendored primitives pack) |
| MCP sealing proxy (`warrant-mcp`), MCP decision server, `warrant-anchor`, approval bridge, in-toto/OTel/PDF tools | retired | — (a front end over the new CLI is future work) |
| `tools/check.py`, `doc_counts.py`, `contract.py`, X1 mirror scripts, agent gate, 25 other tools | retired | `tests/` and five scenarios in `examples/` |
| `contracts/*.json` (rule 6) | closed with SPEC v0.4 | SIG-E1 (cofactorless Ed25519) is kept: `tests/vectors/ed25519-edge.json`. SIG-P1, KEY-B1/C1/P1/R1 and ADOPT-T1 bound rules that no longer exist |
| Experiments, demos, needs, dogfood stores | historical | — |
| Papers, proposals (WRT-001..022, REDESIGN-1, GOV-001), reviews, prior-art, standards notes, docs, 0.x root documents (ARCHITECT, THREAT-MODEL, EVIDENCE-PACK, PUBLISHING, LISTINGS, MAP, CONTRACTS, PRIOR-ART), `llms.txt`, `action.yml` | historical, at the tag | SPEC.md, README.md, HISTORY.md, SECURITY.md. Deposited papers keep their DOIs |
| Workflows `wrt-005`, `pages`, `publish`, `agent-gate` | retired | `ci.yml` (`test`) and `x1-cross-repo.yml` (`cross-repo`) |

### Work open at the rebuild

| Work | Decision |
| --- | --- |
| `wrt-022/revalidation` (9d7e354), RV-01/RV-02 fixed but not merged | defect fixes carried over with their counterexamples (`tests/contract_test.py` O1–O2, H1–H5) |
| `wrt-022/s3-grants` (d4d1ee6), not merged | grants are in SPEC §4.5 (U4–U5) |
| `wrt-023/effects-gates` (b87ec4c), local draft | the effect/attempt distinction became the `observation` record. Frontier gates were not built. The draft is superseded |
| Dogfood duties `ee86a1c5` (revalidation) and `e73729b1` (S3) in `dogfood/wrt-022` | still OPEN in that store. They were not discharged; the rebuild supersedes them |
| PR #60 (WRT-008 fact derivation, deferred) | superseded |
| Claude Code plugin (`integrations/claude-code-plugin`) | kept as a bridge for the owner's installed plugin. It records and verifies in the 0.x format through `warrant-verify` 0.12.0 |
| Governance records `.warrants/`, `trust-config.json`, `trust/` | kept as historical data. They verify with `warrant-verify` 0.12.0 |
