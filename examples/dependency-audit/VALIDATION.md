# Local validation of the input stage

2026-10-20. These are local executions; the external application round has not run.

- Manifest pin: `7d722e2664dc57f1618b3bd7c47d3ffbb77d775f770315a8ebc1dcf0b6645653`.
- Candidate source: `698afa9c5e27f9f30ea065c3b8f86bc2b682912a`.
- Real candidate wheel SHA-256: `47c896fc1b2adb290c8b28791d585b3316ee49e6e872b26b7ffa659c7ab55e09`.
- Two local wheel builds with the recorded toolchain/SOURCE_DATE_EPOCH matched
  byte-for-byte. This is a bounded observation, not general reproducible-build
  or builder-authenticity proof.
- Selected frozen wheels total 4,270,404 bytes, including synthetic controls.
  Only the 61,373-byte candidate and two tiny synthetic metadata-only wheels
  are bundled; four public PyPI artifacts are fetched by exact URL/hash.
- Fresh native base installation: four distributions, no Sigma/MCP import;
  compute: five distributions, Sigma provider identity `0caff793…`, no MCP import.
  `fixture/observations.json` records the actual checks and package inventories.

| Case | Vertices | Edges | Host reference predicate |
|---|---:|---:|---|
| base | 6 | 3 | TRUE |
| compute | 6 | 4 | TRUE |
| transitive-prohibited (synthetic) | 4 | 2 | FALSE |

`selftest.py --wheelhouse <cache>`: **33 controls PASS**, including indirect
reachability, extras propagation, cycle termination, marker-environment changes,
version mismatches, duplicate keys/headers/edges, unknown members/extras, missing
dependencies and orphan inventory, forged graph with unchanged TRUE answer,
changed/missing wheel, rehashed same-version provider substitution, arbitrary URL,
source-package mismatch, bad operator pin and unchanged-answer/different-context
binding, plus replacing a manifest file after its pinned snapshot was read.
SonarCloud-triggered refactoring removes the manifest reread and binds the
collector to its own checkout. Artifact bytes and all three graph identities
remain unchanged. A discovered host-path portability defect (macOS `/var` cache aliases)
was corrected by canonicalizing the operator root while still rejecting symlinks
inside it; its regression is included.

The same 33 controls passed after copying the entire kit/cache outside the source
checkout into a fresh Python 3.12 venv containing only `packaging==26.3` (besides
pip), with socket connections disabled through that venv's `sitecustomize.py`.
No Warrant or Sigma import was available or required. A separate empty-cache
`audit.py fetch` acquired and verified the exact public artifact bytes.

Input evidence returns `INPUT_VERIFIED_ENCODING_PENDING`, not a discharged duty.
Sigma graph evaluation, term/environment binding, foreign resume of this workload,
Warrant application acceptance, external performance and remote execution remain
**NOT_RUN**. Native-source/install correspondence is a collector observation;
source/index completeness stays UNATTESTED.

## Application handoff stage (#151), local roles

2026-10-20, `handoff.py selftest`, Apple Silicon, Python 3.15, sigma-glyph 0.8.0
from PyPI, encoder `work/dependency-audit-sigma/reach.py` at `2348215116e8…`.
**12 controls PASS**: reviewed-encoder binding (other bytes refuse), deterministic
timing-free instance, producer pause of all three cases, wrong packet pin, packet
for another frozen instance, swapped instance blob caught at delivery, receiver
verdicts equal the frozen references, every binding control with its expected
code, producer-side readback with its own replay, and a receipt of another case
refused in readback. Per case the receiver also records `damaged_delivery`,
`wrong_root_resume = REFUSED`, `insufficient_budget = [PAUSED, no receipt]` and
`unaccepted_provider = OPEN`.

| Case | ATP (pause / total) | Rebuild + binding controls | Resume incl. replay | Verdict |
|---|---:|---:|---:|---|
| base | 2,688,425 / 5,376,851 | 18.3 s | 14.2 s | TRUE |
| compute | 2,610,112 / 5,220,225 | 17.7 s | 13.8 s | TRUE |
| transitive-prohibited | 370,460 / 740,920 | 3.9 s | 2.1 s | FALSE |

ATP is canonical; wall times are this host's and include the capped admission
run, ten binding refusals (two of them full kit re-verifications on a copied
cache), two refused/paused resumes and the provider's own replay. Both roles ran
on one host: this establishes the protocol and the refusals, not remote execution.
