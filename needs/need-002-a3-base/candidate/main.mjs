#!/usr/bin/env node

// Experiment-owned transport only. Semantic class implementations live in the
// flat candidate namespace beside this file and retain per-file provenance.
import { handle as canon } from "./canon.mjs";
import { handle as parse } from "./parse.mjs";
import { handle as validate } from "./validate.mjs";
import { handle as hashing } from "./hashing.mjs";
import { handle as verifySig } from "./verify-sig.mjs";
import { handle as verifyStore } from "./verify-store.mjs";

const handlers = new Map([
  ["canon", canon],
  ["parse", parse],
  ["validate", validate],
  ["blob-hash", hashing],
  ["sig-message", hashing],
  ["verify-sig", verifySig],
  ["verify-store", verifyStore],
]);

let raw = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) raw += chunk;

try {
  const request = JSON.parse(raw);
  if (
    request?.warrant_conformance !== "1" ||
    typeof request.id !== "string" ||
    typeof request.class !== "string"
  ) throw new Error("malformed warrant-conformance/1 request");

  let result;
  if (request.class === "capabilities") {
    result = {
      output: {
        name: "NEED-002-A3-COLLAB-JS",
        version: "candidate",
        grade: "base",
        classes: [...handlers.keys()],
      },
    };
  } else {
    const handler = handlers.get(request.class);
    result = handler
      ? await handler(request.class, request.input)
      : { unsupported: `class ${request.class} is not implemented` };
  }

  if (
    !result ||
    typeof result !== "object" ||
    Number(Object.hasOwn(result, "output")) + Number(Object.hasOwn(result, "unsupported")) !== 1
  ) throw new Error("class module violated the result contract");

  process.stdout.write(`${JSON.stringify({ warrant_conformance: "1", id: request.id, ...result })}\n`);
} catch (error) {
  process.stderr.write(`${error?.stack || error}\n`);
  process.exitCode = 1;
}
