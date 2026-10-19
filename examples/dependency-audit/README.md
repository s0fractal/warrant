# Real wheel dependency audit: input stage

Pilot: #149. Input task: #150. Application acceptance: #151.
Sigma encoder: <https://github.com/s0fractal/sigma-glyph/issues/68>.

This freezes real Warrant base/compute installation inputs and makes their
metadata-to-graph mapping executable. It is the next step after the control-term
handoff in `examples/cross-host/`. Sigma evaluation, graph-to-term binding,
checked foreign resume of this application and application acceptance are still
**NOT_RUN**. `evidence.py` deliberately returns `INPUT_VERIFIED_ENCODING_PENDING`.

Read [CONTRACT.md](CONTRACT.md) before implementing the encoder. It defines the
numeric adjacency/roots/forbidden/required input, labels and metadata binding,
target markers, activated extras, cycles, limits and refusal semantics. Frozen
graphs and reference answers are in `fixture/manifest.json`; reference Booleans
are diagnostics, not the computation to encode as constant terms.

## Actual selected packages

| Case | Selected dependency closure | Reference predicate |
|---|---|---|
| base | warrant-loops 2.0.0.dev0, cryptography 50.0.2, cffi 2.1.1, pycparser 3.11 | TRUE: no Sigma/MCP |
| compute | same, plus sigma-glyph 0.8.0 | TRUE: Sigma reachable, no MCP |
| transitive-prohibited | synthetic Warrant -> audit-bridge -> real Sigma wheel | FALSE: prohibited transitive path |

The selected real installations ran in fresh native CPython 3.12.13/macOS arm64
venvs. The complete marker environment and compatible tag set are frozen; Linux
can verify the ZIP metadata for this declared target without installing macOS
wheels. Do not substitute Linux/native marker values. Synthetic metadata-only
control wheels must never be installed.

The candidate wheel and two small synthetic wheels are bundled. Third-party
wheels are acquired by immutable recorded URL/size/SHA-256 into a cache. Raw
METADATA is also frozen, but metadata-only diagnosis grants no wheel-byte credit.
The public candidate is a test fixture built from `698afa9…`; it is not a PyPI
release. Native-install observations and source checks are recorded in
`fixture/observations.json`; they remain collector observations, not build or
machine attestations. The cryptographic commitments prove byte identity, not
package safety or runtime-import behavior.

## Fresh, portable verification

```sh
python3 -m venv /tmp/dependency-audit-tools
/tmp/dependency-audit-tools/bin/pip install 'packaging==26.3'
KIT=/absolute/path/to/examples/dependency-audit
CACHE=/absolute/path/to/a-wheel-cache
PIN=$(cat "$KIT/fixture/manifest.sha256")

# First acquisition only: exact pinned files, no dependency resolution.
/tmp/dependency-audit-tools/bin/python "$KIT/audit.py" fetch \
  --manifest "$KIT/fixture/manifest.json" --manifest-sha256 "$PIN" --wheelhouse "$CACHE"

# With that cache this and all controls run offline, outside a checkout.
/tmp/dependency-audit-tools/bin/python "$KIT/audit.py" verify \
  --manifest "$KIT/fixture/manifest.json" --manifest-sha256 "$PIN" --wheelhouse "$CACHE"
/tmp/dependency-audit-tools/bin/python "$KIT/selftest.py" --wheelhouse "$CACHE"
/tmp/dependency-audit-tools/bin/python "$KIT/evidence.py" \
  --manifest "$KIT/fixture/manifest.json" --manifest-sha256 "$PIN" \
  --case base --wheelhouse "$CACHE"
```

For a real receiver round, obtain PIN independently from the operator's message
and compare it to these files. Reading a pin from the same directory is a local
fixture-integrity convenience, not an independent trust anchor.

## Freeze provenance / reproduction

Original source SHA: `698afa9c5e27f9f30ea065c3b8f86bc2b682912a`.
Builder: Python 3.12.13, build 1.5.0, setuptools 84.0.0, wheel 0.48.0, pip 25.0.1.
Build used `SOURCE_DATE_EPOCH=1792428332 python -m build --wheel --no-isolation`.
The native base and compute venvs each ran pip install with `--only-binary=:all:`,
`--index-url https://pypi.org/simple` and `--report`, against this exact wheel
(with `[compute]` for the second case). The collector compared report URLs and
hashes to PyPI version JSON entries, then checked downloaded bytes. It also
compared every bundled candidate package file against Git blobs at the source SHA.

`collect.py` accepts those two original reports, source repository and candidate
wheel, writes a **new** fixture directory and refuses to overwrite one. Repeating
today's pip resolution is a new experiment, not reproduction of the frozen one.
Raw acquisition reports remain host-local because they include local file URLs;
the normalized selected sets, origin links and exact bytes needed for verification
are frozen here. No token or private key is included.

## States and outstanding work

`WHEEL_BYTES_VERIFIED` and `MATCHED_REVIEWED_BYTES` mean the exact wheel artifacts
and Sigma provider source hashes matched. They do not mean Sigma evaluated a
graph or Warrant accepted an audit. `METADATA_ONLY_UNVERIFIED` is diagnostic only.
Malformed/incomplete/changed input refuses with exit 2; a valid negative graph
returns a false reference predicate without being a malformed input.

The graph encoder must perform reachability in Sigma, rebuild identities on the
receiver and preserve the separate whole-instance binding. The Warrant wrapper
must still bind the encoder, actual term/environment/expected normal form and
target, record observations and independent acceptance, and verify the returned
artifact. No existing trust/profile/release settings are changed by this kit.
