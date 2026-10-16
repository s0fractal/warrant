// Release gate: the package was built from a clean tree at the commit being
// released, and the WASM embedded in generated/bytes.js is the one build.json
// names. Usage: node js/verify-build.mjs <expected-commit>
import { readFileSync, appendFileSync } from "node:fs";
import { createHash } from "node:crypto";

const here = new URL("./generated/", import.meta.url);
const want = process.argv[2];
const b = JSON.parse(readFileSync(new URL("build.json", here)));
const m = readFileSync(new URL("bytes.js", here), "utf8").match(/"([A-Za-z0-9+/=]+)"/);
const sha = createHash("sha256").update(Buffer.from(m[1], "base64")).digest("hex");
console.log(JSON.stringify({ rev: b.sourceRevision, tree: b.workingTree, sha }));
if (b.workingTree !== "clean") throw new Error("built from a dirty tree");
if (!want || b.sourceRevision !== want) throw new Error(`build.json revision ${b.sourceRevision} != ${want}`);
if (sha !== b.wasmSha256) throw new Error(`embedded WASM ${sha} != build.json ${b.wasmSha256}`);
if (process.env.GITHUB_STEP_SUMMARY)
  appendFileSync(process.env.GITHUB_STEP_SUMMARY, `WASM sha256 \`${sha}\` from \`${b.sourceRevision}\`\n`);
