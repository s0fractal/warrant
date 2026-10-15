# Warrant browser lab

A static explanation and a working local verifier. The website uses the Rust
core in `impl-rs/`; `impl-wasm/` only handles the browser transport. No backend,
account, external fonts, analytics, upload endpoint or browser persistence.

## Build and preview

Prerequisites: Rust, the `wasm32-unknown-unknown` target, Python 3.9+, Node 22+,
and the binding CLI matching the pinned Rust dependency:

```sh
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli --version 0.2.104 --locked
python3 web/build.py
cd web
npm test                         # Python reference needs cryptography
npm run preview                  # http://127.0.0.1:4173
```

`WASM_BINDGEN` can name an existing binding executable. `WARRANT_PYTHON` can
select the interpreter for the Python differential checks. Generated files stay
in ignored `web/dist/`. No JS dependencies or bundler are required.

## What the page does

- Loads the exact signed `examples/ski/accept-ski.warrant.json` specimen and its
  blobs. An optional button fetches those same bytes from the pinned public
  GitHub commit. Source links identify each record's provenance.
- Imports a `.warrants` folder, or a single envelope JSON. Folder imports preserve
  record filenames and every raw byte. A single file named by a WarrantID keeps
  that name; another name obtains a computed ID and still needs a valid signature.
- Uses the core's I-JSON parser, canonicalization, signatures, blob checks,
  settlement context and `ski@v1` evaluator. It returns the existing closed
  `warrant.verify-report@v0` report, without adding fields to it.
- Shows optional explanatory re-run results separately from that report. It
  never executes `cmd@v1` or treats prose as a computed result.
- Imports external trust JSON only on explicit selection; imported store files
  never become trusted configuration automatically. Clearing it restores base
  grade. An invalid selected config refuses settlement as in the CLI.
- Lets a reader edit a record while keeping its original filename, then observe
  the core's mismatch report.

The path-to-hex map used between JS and WASM is an adapter transport, **not a
new Warrant format**. It preserves raw input bytes and duplicate JSON keys in
record files. The thin `client.js` API and `client.d.ts` can be reused by another
frontend together with the generated `wasm/` files and worker. The package is
private until a separate package release is chosen; nothing has been published
to npm or JSR.

## Limits and meaning

The browser accepts up to 8 MiB and 2,048 store files, a 256 KiB trust config,
and a local ceiling of 1,000,000 ATP per check. It uses a 16 MiB WASM stack and
256 MiB maximum linear memory. Each operation has its own Web Worker, terminated
after completion or 12 seconds. A trap, timeout or admission refusal produces
an incomplete UI state, never a fabricated passing report. Large or deep stores
may require the CLI. ATP is not an RSS or wall-clock bound.

Native defaults and evaluator behavior remain unchanged. Browser and native
reports agree on the tested domain within these local limits; different limits
can produce different unverified/refused outcomes. Native core tests exercise
file-vs-memory reads, and Node tests instantiate the actual WASM and compare
reports with the Python reference, including malformed records, changed bytes,
duplicate fields, external trust and CAS identity controls.

`ok` means zero errors at the requested grade. Warnings remain visible. Neither
the page nor its sample grants key trust, factual truth, permission or governance
adoption. Settlement retains the current core's documented policy and key-state
limits. Consult the repository's current specification and threat model.

## Pages deployment

`.github/workflows/pages.yml` builds and tests on relevant pull requests without
deploying them. A successful `master` build can deploy the static artifact under
the existing `github-pages` environment. Before first deployment, the repository
owner must select **GitHub Actions** as the Pages build source; the repository
currently uses the legacy `master:/docs` source. The workflow does not change
that setting automatically. Existing `docs/conformance.html` is retained in the
built site. Merging and publishing still follow the repository's authorization
rules.

`build.json` records the source commit, working-tree state, WASM digest and local
limits. It is unsigned build metadata. The website does not claim to verify its
own delivery or turn its explanatory copy into signed protocol authority.
