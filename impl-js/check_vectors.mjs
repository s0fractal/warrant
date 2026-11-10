// Run impl-js/warrant.mjs against the vectors in impl-js/vectors (manifest.json says what they are and how an answer
// is compared), with no Python: one line per disagreement, then the counts. Exit 0 when every vector agrees.
//
//   node impl-js/check_vectors.mjs [DIR]
//
// Another implementation is held to the same vectors by the same rule: answer each case, drop the engine's identity
// (assessment, code, adapter), compare every other member as RFC 8785 bytes, and check that its own `assessment` is the
// digest of its own operands.
import * as W from "./warrant.mjs";
import { readFileSync } from "node:fs";
import { gunzipSync, constants } from "node:zlib";
import { createHash } from "node:crypto";
import { join } from "node:path";

const IDENTITY = new Set(["assessment", "code", "adapter"]);
const OPERANDS = ["snapshot", "trust", "profile", "as_of", "code"];
const dir = process.argv[2] || new URL("./vectors", import.meta.url).pathname;
const manifest = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));  // NOSONAR S8707: the operator's DIR argument (or the vectors beside this file), read as data
const gz = readFileSync(join(dir, manifest.cases));  // NOSONAR S8707: the cases file the operator's manifest names, read as data and checked against its SHA-256
const sha = createHash("sha256").update(gz).digest("hex");
if (sha !== manifest.sha256) { console.log("FAIL the cases' SHA-256 is not the one manifest.json names"); process.exit(1); }
const backend = await W.nodeBackend();
const code = await W.codeIdentity(new Uint8Array(readFileSync(new URL("./warrant.mjs", import.meta.url))), backend);
const counts = {};
let bad = 0;
for (const line of gunzipSync(gz, { finishFlush: constants.Z_SYNC_FLUSH }).toString("utf8").split("\n")) {
  if (!line) continue;
  const v = W.loadsLenient(line);
  const got = await W.runCase(v.case, backend, code);
  const why = [];
  if ("assessment" in got) {
    const ops = Object.create(null);
    for (const k of OPERANDS) ops[k] = got[k];
    if (got.assessment !== backend.sha256(W.canon(ops))) why.push("its assessment is not its operands' digest");
  }
  const members = new Set([...Object.keys(got), ...Object.keys(v.expect)].filter((k) => !IDENTITY.has(k)));
  for (const m of members) if (!(m in got) || !(m in v.expect) || W.canonStr(got[m]) !== W.canonStr(v.expect[m])) why.push(m);
  const c = (counts[v.class] ||= [0, 0]);
  c[0]++;
  if (why.length) { bad++; console.log(`FAIL ${v.class} ${v.name}: ${why.join(", ")}`); } else c[1]++;
}
console.log(Object.entries(counts).map(([k, [n, ok]]) => `${k}: ${ok} of ${n} agree`).join("; ") + (bad ? `; ${bad} disagree` : "; all agree"));
process.exit(bad ? 1 : 0);
