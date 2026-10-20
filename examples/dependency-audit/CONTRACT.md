# Application dependency graph input, version 1

Owner: the Warrant application pilot (#149/#150), not Sigma core or Warrant SPEC.
This contract uses existing package metadata and produces the numeric input for
Sigma issue s0fractal/sigma-glyph#68. No kernel/profile adoption is proposed.

## Instance and trust boundary

The operator pins the SHA-256 of the entire canonical `manifest.json` outside the
package. It binds the source revision, acquisition observation, complete declared
target-marker map, compatible wheel tags, exact selected wheel inventories,
artifact hashes, application contract and collector/verifier source hashes.
Selected inventory completeness is checked for that declared resolution only;
global index/source completeness remains UNATTESTED.

Acquisition used actual fresh native CPython 3.12.13/macOS arm64 installations,
explicit `https://pypi.org/simple`, binary wheels only and pip installation
reports. Exact PyPI version JSON file entries were compared to pip URLs/hashes,
and exact downloaded bytes were checked. Candidate package files were compared
with Git blobs at the pinned Warrant revision. This is a recorded local source
correspondence observation, not a signed build attestation or reproducible-build
claim. The candidate wheel is bundled as a test artifact, not published.

A receiver may inspect these macOS wheel ZIPs on Linux: it evaluates the declared
target marker environment and frozen tags, never silently substitutes its host.
It does not install those platform wheels. A Linux installation is another
instance, with another marker context, artifacts and manifest pin.

## Admission and reconstruction

`packaging==26.3` is the parsing/evaluation dependency. All eleven marker variables
must be present explicitly; `extra` is set only from the activated extra context.
Missing/malformed/ambiguous input is REFUSED, never a predicate result. JSON uses
ASCII escaping, sorted keys and compact separators; no floats, non-finite values
or duplicate object keys. This is an application byte encoding, not a replacement
for Warrant/Sigma canonicalization.

For every selected wheel, verify size/SHA-256, unique bounded ZIP members,
filename/METADATA distribution identity, WHEEL/filename tags and intersection with
the declared target's tag set, and exact METADATA digest/bytes. Require one Name,
one Version and at most one Requires-Python; normalize names with PEP 503 and
versions with PEP 440. Reject invalid Requires-Dist and direct URLs (even in an
inactive extra) under this deliberately bounded profile. Requires-Python must
admit the target full Python version. Case selection has exactly one version per
normalized name, a present root and no unreachable inventory members.

Start with the root and requested extras. For each reached distribution, evaluate
each requirement with `extra=""` OR each active extra, always against the complete
declared marker context. Enabled requirements must resolve to a selected wheel
with a version satisfying the specifier (`prereleases=True` for membership in the
already selected resolution). Activate the dependency's requested extras and
revisit it when that set grows. Unknown extras/missing dependencies refuse. Iterate
to a fixed point, allowing cycles and deduplicating edges. This verifies a chosen
resolution; it does not implement or prove the resolver's selection algorithm.

Limits: 16 selected/graph vertices, 64 directed edges, 4 extras per distribution,
32 requirements per METADATA, 128 KiB METADATA, 16 MiB per wheel, 64 MiB total,
32 artifacts and 8 cases per manifest, 2048 target tags. No artifact code runs.

## Graph for the encoder

`graph.schema = warrant-dependency-graph/1`. `nodes` is sorted by normalized
distribution name and contains selected distributions plus all required/forbidden
policy names. Policy names absent from inventory are explicit virtual isolated
vertices: `selected=false`, `version=null`, `extras=[]`. All other nodes carry
their selected version and sorted activated extras.

`graph.evaluation` is the sole numeric computation input:

```json
{"n":6,"edges":[[0,1]],"root":5,"forbidden":[2,4],"required":[]}
```

Here the numbers only illustrate the shape. Vertex indices are zero-based offsets
in `nodes`. Edges are sorted unique pairs, forbidden/required are sorted unique
indices. The root is reachable from itself; all other reachability follows the
directed edges. Compute reachability to a fixed point (at most n rounds).
The predicate is TRUE iff no forbidden vertex is reachable AND every required
vertex is reachable. Cycles terminate under this finite bound.

Base policy forbids `mcp` and `sigma-glyph`; compute policy requires reachable
`sigma-glyph` and forbids `mcp`. Sigma 0.8.0's version requirement is independently
validated from enabled root METADATA and the selected version before this graph
predicate; provider-file identity is a separate application binding obligation.
The numeric input includes isolated forbidden vertices, so absence is explicit
data rather than permission to replace graph evaluation with a constant answer.

`graph_sha256` hashes the entire graph including labels/versions. The evaluation
digest hashes only the numeric object. They are not interchangeable: the same
computation can occur over differently bound artifacts or marker environments.
`reference` is a host-side graph traversal and witness paths. It is test evidence,
not the term to execute: the Sigma encoder must implement the fixed predicate
over graph data, not encode the reference Boolean as a constant normal form.

## Cases, states and non-claims

`base` and `compute` come from real installations. `transitive-prohibited` is a
labeled synthetic metadata-only wheel control with path
`warrant-loops -> audit-bridge -> sigma-glyph`; never install its synthetic wheels.
It is a valid graph whose predicate is FALSE, not a malformed-input refusal.

Full artifact verification produces `WHEEL_BYTES_VERIFIED`. The explicit
metadata-only diagnostic produces `METADATA_ONLY_UNVERIFIED` and grants no wheel
binding credit. Missing/changed wheels, wrong context pin, invalid metadata or
graph mismatch REFUSE. Acquisition/index access happens only in explicit `fetch`
or collector mode. Verification itself uses local bytes and never resolves again.
Sigma execution, checked resume and Warrant application acceptance are NOT_RUN in
this input-fixture stage; matching graph reconstruction is not their completion.

This proves neither all possible installations, package safety, runtime import
behavior, metadata truth, global completeness, general encoder correctness,
release authorization nor remote execution. Native installation observations,
artifact/source bindings, Sigma computation and recipient acceptance stay distinct.
