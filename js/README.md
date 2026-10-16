# @s0fractal/warrant

The Warrant Rust verifier compiled to WebAssembly, with a thin typed JavaScript
API. The same package name and version are published to npm and JSR. It includes
the WASM bytes: no local checkout, CLI, runtime download or native install step.

```sh
npm install @s0fractal/warrant@0.10.0
# or
deno add jsr:@s0fractal/warrant@0.10.0
```

```ts
import { verifyStore, runCheck, recordId } from "@s0fractal/warrant";
// Deno can also import from "jsr:@s0fractal/warrant@0.10.0".

const files = {
  // Preserve the record's original filename and every original byte.
  "records/<WarrantID>.json": recordBytes, // Uint8Array
  "blobs/<SHA256>": blobBytes,
};
const report = verifyStore(files);
console.log(report.ok, report.errors, report.warnings, report.findings);
// Explicit trust config JSON selects settlement grade:
const settlement = verifyStore(files, { trust: trustConfigText });
// Optional separate re-execution (blobs alone suffice) and identity calculation:
const result = runCheck(files, checkHash);
const id = recordId(recordBytes);
```

Inputs are relative store paths mapped to `Uint8Array` or hexadecimal byte
strings. Raw record bytes are never parsed and reserialized by the wrapper.
External trust is never inferred from imported files. `verifyStore` returns the
existing closed `warrant.verify-report@v0` report. Inspect warnings even when
`ok` is true; neither a signature nor a report establishes factual truth or
permission. `recordId` alone verifies neither identity binding nor a signature.

## Runtime and resource boundaries

ESM only, with no runtime dependencies. CI runs the test suite on Node and
dry-runs the JSR publication; for 0.10.0 the suite also passed on Node 22.23 and
24.18, and the API was exercised on Deno 2.9.2 and in a Chromium browser
(`js/test/browser-smoke.html`), by hand.
All calls are **synchronous**, including WASM initialization. In a UI or when
reading untrusted stores, run the package in a disposable Web Worker / Node
worker thread and enforce your own elapsed-time limit. A worker example is in
`js/test/deep-worker.mjs` in the source repository. The browser lab uses a
separate worker with cancellation and a 12-second timeout; this low-level API
does **not** add a worker or a timeout for callers.

This package uses the browser WASM resource profile in every host:

- 8 MiB raw store input, 2,048 files, 256 KiB external trust config.
- **1,000,000 declared ATP per check**, inclusive. Native CLI defaults to
  100,000,000. A descriptor declaring 1,000,001 ATP refuses here even if the
  actual computation would spend only 20 ATP. This is a local admission limit,
  not a different protocol rule. Native and WASM outcomes can differ at this
  boundary; the boundary has an executable differential test.
- 16 MiB linear stack and 256 MiB maximum WASM linear memory. Measured: the
  deepest term a store can hand this package — a 2,046-node spine, the most the
  2,048-file limit admits — completes here as it does natively. Both run the
  same evaluator with the same 4,096-node depth fault for terms that deepen
  while they run; whether a host's stack gives out before that fault is NOT
  measured. A trap throws, and the instance must then be discarded.

Admission refusals, engine traps and unfinished work throw; they are never
converted into a passing report. Dispose of a failed worker. A successfully
completed report can still contain errors, warnings or unverified reasons.
`ski@v1` is re-executed; `cmd@v1` is never executed by this package. ATP is not
an elapsed-time or total-process-memory bound. Current core settlement limits
remain applicable; see the repository specification and threat model.

## Source and builds

MIT. Source: <https://github.com/s0fractal/warrant/tree/master/js>.
The shipped `generated/build.json` (JSR) or `dist/generated/build.json` (npm)
records the source commit, package/core versions, working-tree state and the
SHA-256 of the decoded WASM. This is unsigned build metadata. The digest
identifies the shipped bytes; it is **not** a reproducible-build claim:
rebuilding the same commit in another directory or on another machine gives
different bytes (rustc hashes the build location into symbol metadata). Local
source paths are remapped out of the binary (`/warrant`, `/cargo`). The binary is
embedded as base64 to make offline imports portable across hosts and bundlers.

From a checkout with Rust, Python, Node, the wasm32 target and wasm-bindgen CLI
0.2.104: `python3 js/build.py`, then `npm --prefix js test`. TypeScript 5.9.3 is
used only to build the npm ESM/types output. JSR publishes the typed source and
the same generated binding and WASM bytes. Tests compare native/WASM budget
boundaries and depth, check that `LIMITS` and the embedded bytes match
`build.json`, and install the packed tarball offline into an empty project
(`test/installed.test.mjs`); the native CAS edge cases (directory, symlink,
dangling symlink, wrong bytes) are Rust tests in `impl-rs/src/ski.rs`.
These are self-tests, not an independent governance gate.
