# Dependency reachability on Sigma-Glyph 0.8.0: draft design

Status: DRAFT for [sigma-glyph#68](https://github.com/s0fractal/sigma-glyph/issues/68)
(pilot [warrant#149](https://github.com/s0fractal/warrant/issues/149)). **All vectors here
are SYNTHETIC.** The real graph contract and the wheel fixtures belong to
[warrant#150](https://github.com/s0fractal/warrant/issues/150). This draft names no
real wheel and claims nothing about one. It proposes no protocol, no kernel change
and no provider change.

Files: `reach.py` holds the encoder, the reference traversal and the controls.
`selftest.out`, `measure.jsonl` and `provider.jsonl` are the recorded runs.

## 1. Review of the existing surface

Everything below is from sigma-glyph `3890dae` (the release 0.8.0 merge). The
installed wheel's three provider files hash to the same bytes, so the provider
identity is `0caff793…c776c5`.

| Surface | What the workload relies on |
| --- | --- |
| `sigma_glyph.c1` (Book I §6) | A plain bracket abstraction: A-1 `I`, A-2 `K M`, A-3 `S`. It has no η and no B/C. Closed subterms stay closed subterms. |
| Node serialization and CAS | SigmaNodeV2 `[op, flags, 32-byte fields]`, with SHA-256 as the NodeHash. `force` checks the CAS relation and materializes **one** node per action; the children stay as thunks. |
| `step5` and the ATP model | Leftmost-outermost order. K and I cost 1, `S x y z` costs `1 + size(z)`, a force costs the size of the node it materializes. Sizes are counted as **trees**: there is no sharing in the accounting. |
| `VERIFIER_LIMITS` | `max_atp` 10,000,000 per call, 1M materialized nodes, depth 4096, 1M fetches. |
| `sigma_resume` | A root is `{runtime, cost model, input_term_hash, environment_id}`. A checkpoint is credit plus spent plus the state. `verify` replays **from the root up to `spent_total` in one `advance`**, so a checkpoint is only verifiable if `spent_total ≤ max_atp`. |
| `sigma_provider` | `term(expr)` parses only `S`, `K`, `I`, parentheses and `#hex`. It returns the input hash and every APPLY node, which form the environment. `resume` = verify the foreign checkpoint, then advance. |

Consequences for the design:

- Any lambda frontend is ours to write. The repository's routing for DA-SIGMA-0001 has
  already decided this: a non-C1 encoding has *application-adapter* status, so it is
  not a protocol question.
- The 10M per-call cap is the real ceiling for a computation that is meant to be
  replayed across hosts. A larger total cannot be re-verified from the root without
  a cached chain, so it is out of scope and not a parameter we can raise.

## 2. Encoding

```
input = P C R T     (P is fixed and identical for every graph; C, R, T are data)
```

**Data.** Nodes are sorted by normalized name. That order assigns the indices
`0..n-1`, so the data terms below depend only on the sorted node list.

- `C`: a Church list of the **columns** of the reflexive adjacency matrix, in
  **descending** column order. Column `j` is a Church list of bits over `i`, where
  `C[j][i] = TRUE` iff `i == j` or there is an edge `i → j`.
- `R`, `T`: Church lists of bits for the roots and the targets.
- Bits are `TRUE = K` and `FALSE = K I`. These are SKI constants that pass through
  C1 unchanged, and `K I` is Book I's own `FALSE_H` (`65cd957f…`).

**Program.** The source text is in `reach.py`. Every definition is closed, and the
whole program is compiled by `sigma_glyph.c1`.

```
anyAnd col r        = some i: col[i] AND r[i]       (col drives the fold, r is a Scott list)
round  C k r        = r'[j] = anyAnd(C[j], r) for all j, accumulated forward, then k r'
iter   C k0 r0      = n-1 rounds driven by C (its first element only sets a flag)
P      C R T        = iter C (anyAnd T) (toScott R)
```

**Result.** The result is the normal form `K` (TRUE) or `K I` (FALSE). Any other
normal form is not a verdict. `atp_exhausted` is an exit, not a verdict either.

**Correctness argument.** `C` is reflexive, so the reached set never shrinks. After
round `m` it equals the set of nodes reachable by a walk of at most `m` edges. A
shortest path has at most `n-1` edges, so `n-1` rounds reach the fixpoint whether or
not the graph has cycles. `reference()` is an independent depth-first traversal over
the same normalized graph.

**Identities.** For each instance the workload records `encoder`
(`warrant-dep-reach/draft-1`), `program`, `C`, `R`, `T`, `input` and
`graph_digest`. The current program hash is `74e3443f…720a95a`; its C1 size is 1507.
The receiver rebuilds the input from the frozen graph and must get the same
`input` before it runs a checked resume.

### 2.1 Encoding rules (each one fixes a measured blow-up)

The first straightforward encoding did not finish within 3M ATP on a **3-node**
graph. Under call-by-name with tree accounting there are two things that
explode:

1. **A copied computation.** `b X acc` with `acc` in both branches doubles the
   pending expression at every step, which gives 2^n in tree size.
2. **K-garbage in lazy C1 code.** For `[x](M N)` where `x` occurs in `M` but not in
   `N`, C1 builds `S [x]M (K N)`. At runtime the argument becomes `K N x`, a pending
   redex that carries a **copy of `x`**. It is reduced only when `N` reaches head
   position. Any continuation or list cell built inside a lambda whose parameter is
   the state therefore carries copies of the state. The next state inherits them and
   grows by about 13× per round (measured at n=2).

The rules:

- **R1** Lambda-lifted: no definition contains an inner lambda.
- **R2** The state vector is the *last* parameter and is only ever passed as the
  last argument, or consumed in head position.
- **R3** Every bit is decided in head position *before* a continuation is selected.
- **R4** The next state is accumulated forward, with columns in descending order, not
  through a continuation chain that captures cells.

Two further measured optimizations: the constant column bit selects a 3-parameter
helper (`AA_hit`/`AA_miss`, about −35 %), and the program runs `n-1` rounds instead
of `n`. The measurements show what is left: each state cell still carries O(1)
garbage (the fold tail `rest` and the round continuation `k`), and every S on the
state's path copies it. The cost is polynomial but steep, roughly `n^4.5` for
chains.

## 3. Measurements (synthetic, book1 oracle unless noted)

`measure.jsonl` records `eval_receipt` under `VERIFIER_LIMITS`. Rows for n=8 used
the uncapped oracle limits and are marked `admitted: false`. In every row
Sigma's verdict equals the reference.

| n | chain (TRUE) | chain-neg (FALSE) | dense DAG | env nodes |
| --- | ---: | ---: | ---: | ---: |
| 3 | 168,292 | 181,065 | 146,833 | 252 |
| 4 | 587,049 | 600,412 | 425,766 | 264 |
| 5 | 1,661,037 | 1,667,320 | 999,797 | 277 |
| 6 | 4,054,049 | 4,039,960 | 2,046,355 | 291 |
| 7 | 8,854,428 | 8,799,553 | 3,798,717 | 306 |
| 8 | 17,731,141 | 17,606,444 | 6,552,908 | 322 |

These are ATP figures, which are canonical and deterministic. Wall time in the bare
oracle is ≤ 1.3 s up to n=7. Through the provider (`provider.jsonl`: a PAUSED
segment at half the credit, then `resume`, which REPLAYs the prefix) the wall times
were:

| n | total ATP | first segment | resume incl. replay | peak semantic size | basis / outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| 3 | 168,292 | 0.5 s | 1.1 s | 13,389 | REPLAYED / NORMAL_FORM TRUE |
| 5 | 1,661,037 | 5.9 s | 11.9 s | 43,241 | REPLAYED / NORMAL_FORM TRUE |
| 6 | 4,054,049 | 15.6 s | 28.6 s | 67,329 | REPLAYED / NORMAL_FORM TRUE |
| 6 neg | 4,039,960 | 16.8 s | 30.4 s | 67,329 | REPLAYED / NORMAL_FORM FALSE |

The provider is about 10–25× slower than the oracle, because `_run` measures the
tree size after every action. ATP and wall time are separate metrics and stay
separate. The host was a single x86_64 container with Python 3.13.16.

## 4. Admission limits (proposed, to freeze with #150)

| Limit | Value | Why |
| --- | --- | --- |
| nodes `n` | 1 ≤ n ≤ **7** | The worst case measured (chain, n=7) is 8.85M, which is below the 10M per-call verifier cap. n=8 needs 17.7M and cannot be replayed from the root. |
| total ATP | the exact oracle figure for the frozen instance, ≤ 10,000,000 | It is deterministic, so it is recorded as the workload's `total_atp`. A run that spends any other amount is a mismatch, not noise. |
| first-host credit | `floor(total/2)` (frozen) | This gives a measurable PAUSED prefix. Its spent must equal the replayed spent. |
| peak semantic size | expected ≤ 120k at n=7 (67k measured at n=6) | Far below the 1M materialized-node limit. A `RESOURCE_FAULT` is a local outcome, never a verdict. |
| environment | ≤ 400 nodes (306 at n=7) | About 1.5k program nodes are shared; each added graph node adds about 15 environment nodes. |
| provider wall | `provider_seconds` 600 per call | n=6 needs 46 s in total. n=7 is estimated at about 100 s and **not yet measured** through the provider. |

If a real fixture exceeds `n = 7`, the report is **INCONCLUSIVE**, with the
measured node count and the oracle ATP, using the uncapped `DEFAULT_LIMITS` only to
measure. The graph is not simplified, the accounting is not changed and the cap is
not raised. Known real shape, from `pyproject.toml` at `698afa9` and the installed
METADATA, still to be frozen by #150: base is warrant-loops → cryptography → cffi →
pycparser, and `[compute]` adds sigma-glyph. With a separate extra node that is
about 6 nodes, which fits.

Predicates over **one union graph** (base and compute wheels plus extra nodes),
pending the #150 contract:

- Base separation: from root `warrant-loops`, target `{sigma-glyph, mcp}` must be
  **FALSE**. This is non-trivial because sigma-glyph is in the graph but reachable
  only through `warrant-loops[compute]`.
- Compute selection: from root `warrant-loops[compute]`, target
  `{sigma-glyph==0.8.0}` must be **TRUE**. Node identity is `name==version`, so a
  different selected version means a different node and a valid FALSE.
- The provider identity `0caff793…` is checked separately (Warrant). Graph
  reachability says nothing about bytes.
- `mcp` is outside the inventory while `[mcp]` is out of scope. An absent target
  contributes no bit, so the report must mark that part as "target absent from
  inventory", not as evidence.

## 5. Negative controls plan

Each control names the layer that must catch it and the observable that shows it.
"Refused" is never FALSE, and a FALSE is never a refusal. A ✓ means the control is
implemented in `reach.py selftest` (synthetic). ○ means it is planned for real
fixtures or integration.

| # | Control | Layer | Expected observable |
| --- | --- | --- | --- |
| C1 | transitive positive (path of length ≥ 2) | Sigma vs reference | `K`, equal to the reference ✓ |
| C2 | target present in the graph but not reachable from the root | Sigma vs reference | `K I`, equal to the reference ✓ (and real: base → sigma-glyph ○) |
| C3 | cycle, positive and negative | Sigma vs reference | answer equal to the reference, terminates within the frozen ATP ✓ |
| C4 | reordered nodes or edges, respelled names, duplicate edges | contract | identical `input` hash ✓ |
| C5 | one edge changed or removed | contract, then Sigma | new `C` and `input`; the answer follows the reference ✓ |
| C6 | changed input binding (root or target moved, data swapped) | contract | new `R`/`T`/`input`; the answer follows the reference ✓; the receiver's rebuilt `input` ≠ frozen → refused before resume ○ |
| C7 | constant-verdict encoder (`\C R T. TRUE` or `FALSE`) | identity, plus mutation | program hash ≠ frozen P, and its answer does not change under C5 ✓ |
| C8 | edge or root naming a missing node | contract | `REFUSED MISSING_NODE` ✓ |
| C9 | duplicate node after normalization, malformed fields, no root | contract | `REFUSED DUPLICATE_NODE / MALFORMED / NO_ROOT` ✓ |
| C10 | n > N_MAX | admission | `REFUSED LIMIT_NODES`; for a real fixture, INCONCLUSIVE with measurements ✓/○ |
| C11 | insufficient credit | kernel | `atp_exhausted` / PAUSED, no verdict ✓ |
| C12 | checkpoint under another root or input | provider resume | not REPLAYED; no credit (the existing provider self-test covers this) ○ |
| C13 | environment missing a node | provider | `EVIDENCE_UNAVAILABLE` (local) or `BLOCKED_REFERENCE`, never a verdict ○ |
| C14 | changed or omitted wheel, changed marker context, manifest/graph mismatch | Warrant #150 / #151 | detected before any Sigma evaluation is credited ○ |
| C15 | unaccepted provider identity | Warrant | the computation is not DISCHARGED (as in round 1) ○ |

Data-length invariants (rows, `R` and `T` all exactly `n`) are **not** checked by
Sigma. A short vector folds to FALSE. They are enforced by the encoder, and by the
receiver rebuilding the frozen `input`; C6 and C14 are the controls for this, and
the residual is recorded.

## 6. What was validated, and what was not

Validated, on synthetic vectors only and on this host:

- The `reach.py selftest` result is 18/18 (`selftest.out`).
- Sigma equals the reference on every measured instance (`measure.jsonl`, n = 2..8).
- PAUSED → REPLAYED → NORMAL_FORM through the installed provider for n = 3, 5 and 6,
  both positive and negative (`provider.jsonl`).
- The provider's `term()` reproduces the encoder's input hash.

Not validated:

- No real wheel or graph has been used, and the #150 contract has not been applied.
- No independent review of the encoding has been done.
- No cross-host run has been made.
- n=7 has not been run through the provider.
- Metadata-to-graph correctness is outside this file.
- The encoder's normalization (`canonical()`) is a placeholder that #150 replaces.

Open questions for #150:

- The exact name/version node key and how extras are represented.
- Whether the union graph or per-install graphs are the frozen instance.
- Which targets are in scope while `[mcp]` is excluded.
- Whether `n ≤ 7` holds for the frozen inventory.
