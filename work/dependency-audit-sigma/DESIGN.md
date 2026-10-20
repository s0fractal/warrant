# Dependency policy on Sigma-Glyph 0.8.0: amendment 1

Status: CANDIDATE for [sigma-glyph#68](https://github.com/s0fractal/sigma-glyph/issues/68),
answering the AMEND review of the draft `acd8307`, which was delivered as a signed
Warrant review handoff (warrant `18bbbc6`, `examples/review-handoff`). The input is
the frozen #150 kit (warrant `67e0031`, manifest
`7d722e2664dc57f1618b3bd7c47d3ffbb77d775f770315a8ebc1dcf0b6645653`).

This amendment proposes no change to the kernel, the SPEC or the provider, and no
merge, release or cross-host claim. Codex has not accepted it.

Files:
- `reach.py` holds the encoder, the input checks, admission, the reference
  traversal, the controls and the checked-resume driver.
- `amend-1/` holds the raw outputs of this host's runs.

## 1. Review findings and what changed

| Finding | Reproduced | Amendment |
| --- | --- | --- |
| 1. `n ≤ 7` does not bound the cost | Yes. All 8 rows of `capped-results.jsonl` were reproduced byte-for-byte except wall time (`amend-1/review-counterexamples-on-acd8307.jsonl`). | `n ≤ 7` is now only a cheap **structural** pre-check. A workload is **ADMITTED** only after a capped `VERIFIER_LIMITS` run ends in `normal_form` with a result of exactly `K` or `K I` and total ATP ≤ 10M. Otherwise it is **INCONCLUSIVE**: it gets no pause credit, and no verdict is derived from it. The pause credit is `floor(total/2)` of the *measured* total. Reverse-chain, edgeless and cyclic controls at n=7 are kept. |
| 2. Absent target names were dropped from the binding | Yes (`same_identities: true`). | There is no host-side target filtering any more. The input is the #150 per-install graph, in which an absent policy name is a virtual isolated vertex inside `evaluation`. Before anything is encoded, `evaluation_of()` recomputes `binding_id`, `graph_sha256` and `evaluation_sha256`, and checks the manifest pin, the input state and the provider. The workload document binds all of these together with the term identities. Regression: renaming the absent vertex `mcp` to `mcq` keeps the term and the answer identical, but the `graph_sha256` and the `workload_id` differ. |
| 3. EXISTS instead of the full policy | Yes: the two-required example returned TRUE. | Sigma now computes `NOT (some forbidden reachable) AND (every required reachable)`. P takes `C R F Q`. |

## 2. Encoding

```
input = P C R F Q
C = columns of the reflexive adjacency, DESCENDING j: C[j][i] = (i == j) or [i, j] in edges
R = root bit vector;  F = forbidden;  Q = required        (ascending index = #150 node order)
P C R F Q = iter C (policy F Q) (toScott R)
policy F Q r = (anyAnd F r) FALSE (allReq Q r)
```

- `iter` runs n−1 rounds of `r'[j] = anyAnd(C[j], r)`. `C` is reflexive, so the set
  is monotone, and a shortest path has at most n−1 edges.
- `allReq Q r` is `∀i. Q[i] → r[i]`.
- Results: `K` is TRUE and `K I` (`65cd957f…`, Book I `FALSE_H`) is FALSE. Any other
  normal form, and any `atp_exhausted` or resource fault, is not a verdict.
- Program hash: `4f8cd91909ecf4885cc58a6862afc7544822f14f4f091592a2cf4434f9ebcd7e`
  (C1 size 1847). It is the same for every graph.
- The encoding rules R1–R4 from the draft still apply. They are what keeps lazy C1
  code polynomial:
  - R1: lambda-lifted;
  - R2: the state vector is the last parameter and only ever the last argument;
  - R3: every bit is decided in head position before a continuation is chosen;
  - R4: the next state is accumulated forward.

## 3. Frozen workloads (this host, x86_64, Python 3.13.16, installed sigma-glyph 0.8.0)

| case | n/e | input | total ATP | verdict | workload_id |
| --- | --- | --- | ---: | --- | --- |
| base | 6/3 | `38bdaaee6a251998…` | 5,376,851 | TRUE | `2fc25e94b4672b70…` |
| compute | 6/4 | `e47d0552b9ae4a63…` | 5,220,225 | TRUE | `eff62e085092cac8…` |
| transitive-prohibited | 4/2 | `094ad18b6544a956…` | 740,920 | FALSE | `34f860effb238714…` |

The full identities are in `amend-1/workload-*.json`: encoder source, program,
C/R/F/Q, input, `environment_id`, `computation_id`, runtime and cost model, provider,
the #150 binding, admission, and pause credit.

Checked resume through `sigma_provider` (`amend-1/resume-*.json`): a PAUSED first
segment at the frozen credit, then `resume`. In all three cases the resume
verification basis is **REPLAYED**, the final outcome is **NORMAL_FORM**, the
result equals the admission's `expected_result`, and the spent equals the total.

| case | first segment | resume incl. replay | peak semantic size |
| --- | ---: | ---: | ---: |
| base | 18.5 s | 34.1 s | 67,891 |
| compute | 17.9 s | 34.0 s | 67,891 |
| transitive-prohibited | 2.8 s | 5.0 s | 25,931 |

ATP is canonical and deterministic. Wall times are host observations from this
single run.

## 4. Limit shapes (`amend-1/measure.jsonl`, all synthetic)

At n ≤ 6 every shape is ADMITTED, and its answer equals the reference. At n = 7:

| shape | state | ATP |
| --- | --- | ---: |
| chain-forward | ADMITTED (FALSE) | 8,957,933 |
| required-all-chain | ADMITTED (TRUE) | 9,737,423 |
| chain-reverse | INCONCLUSIVE (`atp_exhausted`) | 9,994,894 |
| edgeless | INCONCLUSIVE | 9,998,221 |
| cycle-reverse | INCONCLUSIVE | 9,994,941 |

Cost depends on the shape as well as on n. That is why admission is per instance.
No cap was raised, and no INCONCLUSIVE shape was given a verdict.

## 5. Controls (`reach.py selftest`, 34/34 on this host, `amend-1/selftest.out`)

- **Policy semantics (synthetic).**
  - All required, one of them missing → FALSE.
  - All required present → TRUE.
  - Indirect forbidden → FALSE.
  - Isolated forbidden vertex with the requirement met → TRUE.
  - Cycle → TRUE.
  - Root itself forbidden → FALSE.
  - Empty policy → TRUE.

  In every case Sigma equals the reference.
- **Real cases.** base, compute and transitive-prohibited are ADMITTED. Sigma
  equals the reference and the frozen `reference_only` predicate.
- **Admission at n = 7.** There are 5 shapes, and each is either ADMITTED with the
  right answer or INCONCLUSIVE with no verdict.
- **Binding.** These are refused before Sigma runs:
  - a forged evaluation (`GRAPH_DIGEST`);
  - a forged evaluation whose graph and binding were rehashed but whose
    evaluation digest is stale (`EVALUATION_DIGEST`);
  - a renamed absent vertex (`GRAPH_DIGEST`);
  - a changed binding field (`BINDING`);
  - a different manifest (`MANIFEST_PIN`);
  - metadata-only input (`INPUT_STATE`).

  A consistently rebound renamed policy name produces the same term and answer
  but a different `workload_id`.
- **Mutations.**
  - An added path to a forbidden vertex → FALSE.
  - A required vertex made unreachable → FALSE.
  - The constant-TRUE and constant-FALSE programs have identities other than P,
    and their answer does not change under the forbidden-path mutation.
- **Malformed input** is refused and never returns FALSE: unsorted, duplicate and
  out-of-range edges, an out-of-range root, unsorted policy lists, extra fields,
  and n above the structural limit.
- **Budget.** An insufficient budget produces `atp_exhausted`, with no verdict.

The #150 kit itself was checked on this host before adaptation:
- fetch and verify: `WHEEL_BYTES_VERIFIED` and `MATCHED_REVIEWED_BYTES`;
- `selftest.py`: 33/33 (`amend-1/kit-selftest.out`);
- `evidence.py` for all three cases;
- all 22 files in the kit are byte-identical to `examples/dependency-audit` at
  `67e0031`.

## 6. Residuals

- **Who checks what.**
  - Data-length invariants are enforced by the encoder and by the receiver
    rebuilding the input, not by Sigma.
  - The version requirement on Sigma 0.8.0 and the provider-file identity remain
    #150 and Warrant obligations.
  - A forger who rehashes every digest is caught only by comparing `binding_id`
    and `workload_id` with the values regenerated from the operator-pinned
    manifest, which is what this host did.
- **What this run shows and does not show.**
  - This host ran the producer and resume roles locally, so the run is not a
    cross-host computation.
  - Logs and signatures do not establish that the run was executed remotely.
  - No general correctness proof of the encoder exists, and it has had no
    independent re-review yet.
