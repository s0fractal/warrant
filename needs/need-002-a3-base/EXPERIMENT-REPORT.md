# NEED-002-A3-COLLAB-JS — result report

Date: 2026-09-03  
Frozen specification SHA-256: `3fc90963cb353d649bf5c7097a0c2e2b26a78bd86be2bc08abf7655d2f0c38ba`  
Frozen pack version: `1.2.0`  
Pack manifest digest: `5a7360ba655aae7652b47c4b5882beed7eb9ce17403aaf0b35da628c22c3bd58`  
Pack tarball SHA-256: `3226f8b4c9641247b1bf80cd781d11d082d0efef0428c71e129daef030251468`

## Result

An iterative, provenance-recorded, local multi-model process produced a
runnable JavaScript candidate that agrees with every base-grade expectation in
the frozen Warrant conformance pack 1.2.0.

```text
PASS           135
FAIL             0
UNRUN            0
ERROR            0
NOT-CLAIMED      4
GRADE ACHIEVED   base
```

The full machine report is [`reports/s2.json`](reports/s2.json), SHA-256
`9cbe47202f99566d2662cf5e6c39a2b05fb6b9556d460f78fa5098bf2719f3e0`.
All 60 base-grade MUST-REJECT vectors were answered and rejected as expected.
The remaining two negative and two positive settlement-grade vectors were not
claimed.

## What changed from the earlier experiments

The unit of evaluation was the construction trajectory, not a single prompt.
The task removed accidental path inference: every semantic module lives in the
flat `candidate/` namespace and imports dependencies only as sibling
`./<name>.mjs` coordinates. `candidate/main.mjs` is experiment-owned transport
and receives no semantic implementation credit.

The collaborative baseline combined the strongest independently generated
modules from the earlier Qwen3.8 and Gemma4 runs. It immediately executed all
135 base vectors and scored 130 PASS / 5 FAIL / 0 ERROR. That result shows that
the earlier path failures had hidden an almost complete semantic implementation.

The remaining work proceeded as ordinary iterative debugging:

1. Gemma4 and Qwen3.8 attempted the signature module against runner reports;
   one later store handoff used a curated nine-result extract.
2. Qwen3.8's second complete replacement correctly introduced an Ed25519 SPKI
   wrapper but used Node's streaming digest API, leaving four positive vectors
   false.
3. Two orchestrator-authored probes recorded Node runtime observations and
   supplied repair hypotheses. Their generator was not preserved, so the
   compact bundle hashes those inputs but cannot replay their construction. No
   Warrant implementation source was consulted or disclosed.
4. Qwen3.8 attempt `verify-sig-q3` emitted the complete final signature module.
   It passed 28/28 signature vectors: four positives and twenty-four negative
   replay, weak-key, and malformed-key cases.
5. Gemma4 attempt `verify-store-s2` consumed the public contract, store vectors,
   and the already-green sibling modules. Its complete emitted store module
   moved the composite from 134/135 to 135/135.

Qwen3-Coder, DeepSeek-Coder-V2, and Qwen3.6 attempts that ended without a
complete artifact remain recorded as generation/transport outcomes. They do not
receive implementation credit. Non-improving but complete attempts are likewise
preserved rather than rewritten out of the trajectory.

## Negative control and path check

The frozen runner's self-check detected all four deliberate mutations:

- `accept-all`: 64 answers corrupted; 60 vectors newly flagged; exit 1.
- `legacy-sig`: 4 answers corrupted; 4 vectors newly flagged; exit 1.
- `false-unsupported`: 48 answers corrupted; 48 vectors newly flagged; exit 2.
- `crash`: 136 answers corrupted; 135 vectors newly flagged; exit 3.

Two consecutive full JSON reports in the same environment were byte-identical.
Running the absolute candidate path from a foreign temporary working directory
produced the same vector counts and grade. Its report bytes differed because the
report honestly embeds the invoked candidate locator; the evaluated result did
not.

## Claim boundary

This result establishes compatibility with one frozen public corpus under the
recorded Node/runtime environment. It does not establish:

- correctness for inputs outside the corpus;
- settlement-grade behavior;
- that one model can reproduce the implementation in one pass;
- independence of the overall development lineage;
- external adoption, normative validity, or a released Warrant implementation;
- that every retained model response contributed useful semantic code.

The stronger and more relevant observation is constructive: given an explicit
coordinate space, public specification, executable tests, iterative feedback,
and permission to hand work between models, the local models collectively
produced a complete base-grade implementation without access to Warrant's
implementation source.
