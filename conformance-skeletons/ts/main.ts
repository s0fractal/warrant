// A starting point for a Warrant verifier in TypeScript, wired to the
// conformance pack.
//
//	node conformance-skeletons/ts/main.ts       # Node >= 23.6 strips types natively
//	npx tsx conformance-skeletons/ts/main.ts    # any Node >= 18
//	python3 conformance/run.py --candidate "node <abs path>/main.ts" --claim base
//
// Node built-ins only, one file, no package.json, no tsconfig, no build step.
// It answers `capabilities`, implements `canon`, and declines every other class
// with `unsupported` — which is the honest state of a verifier that has not been
// written yet. Do not make it answer a class it cannot compute: an UNRUN vector
// costs you the grade, a wrong answer costs you the ability to trust the report.
//
// WHAT TO DO NEXT, IN THIS ORDER
//
//  1. `blob-hash` — SHA-256 over base64-decoded bytes, no framing. Ten minutes,
//     and it is the fixture the store classes are built on.
//  2. `sig-message` — the 47 bytes a key signs. Ten minutes, and getting it
//     wrong is invisible to every other class (that is why it has its own
//     battery). Reject a WarrantID that is not 64 lowercase hex characters.
//  3. `validate` — the schema. Largest of the base classes and the one with the
//     most MUST-REJECT vectors; write it against the negative vectors first,
//     because an implementation that returns true always passes every positive.
//  4. `parse` — I-JSON strictness over raw bytes. This is the class where
//     JSON.parse stops helping: it accepts duplicate member names last-wins,
//     accepts a leading BOM, and turns a lone surrogate escape into a lone
//     surrogate rather than an error. Expect to write a small scanner.
//  5. `verify-sig` — node:crypto `verify(null, msg, key, sig)` with an Ed25519
//     KeyObject built from the raw 32 bytes. The small-order and non-canonical
//     public keys must fail, and nothing here may throw.
//  6. `verify-store` — walk records/ and blobs/, recompute every address.
//     That completes base grade.
//
// Settlement grade (`ski-run`, `verify-store` with a trust config) comes after
// all of base is green. Claiming base and reaching base is a complete result.

import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const PROTOCOL = "1";

// The classes this build actually computes. Everything else is declined by
// name, so the report says which classes are missing rather than implying they
// passed. Add to this list only when the vectors for that class go green.
const IMPLEMENTED = ["canon"];

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

function main(): void {
  // Exit nonzero ONLY when no answer was produced. "The signature does not
  // verify" is an answer and exits 0; a thrown exception is not and exits 1.
  let req: { warrant_conformance?: string; id?: string; class?: string; input?: Json };
  try {
    req = JSON.parse(readFileSync(0, "utf8"));
  } catch (e) {
    process.stderr.write(`skeleton: request is not JSON: ${e}\n`);
    process.exit(1);
  }
  if (req.warrant_conformance !== PROTOCOL) {
    process.stderr.write(`skeleton: request protocol ${req.warrant_conformance}\n`);
    process.exit(1);
  }

  const resp: Record<string, unknown> = {
    warrant_conformance: PROTOCOL,
    id: req.id,
  };
  switch (req.class) {
    case "capabilities":
      resp.output = {
        name: "warrant-skeleton-ts",
        version: "0.1.0",
        grade: "base",
        classes: IMPLEMENTED,
      };
      break;
    case "canon":
      resp.output = doCanon((req.input as { body: Json }).body);
      break;
    default:
      resp.unsupported = `not implemented in this skeleton: ${req.class}`;
  }
  process.stdout.write(JSON.stringify(resp) + "\n");
}

// ---------------------------------------------------------------- canon

function doCanon(body: Json): Record<string, unknown> {
  let text: string;
  try {
    text = canon(body);
  } catch (e) {
    // A body that cannot be canonicalized is an answer, not a crash.
    return { error: String(e instanceof Error ? e.message : e) };
  }
  const bytes = Buffer.from(text, "utf8");
  return {
    canon_hex: bytes.toString("hex"),
    warrant_id: createHash("sha256").update(bytes).digest("hex"),
  };
}

// canon returns RFC 8785 (JCS) canonical text for the I-JSON subset the format
// admits. The three places a reimplementation splits, all of them vectored:
// escaping (below), key order, and numbers.
function canon(v: Json): string {
  if (v === null) return "null";
  switch (typeof v) {
    case "boolean":
      return v ? "true" : "false";
    case "number":
      // Bodies are integers only. Note what JSON.parse has ALREADY cost you:
      // it produced a Number, so `1.0` and `1e2` arrive indistinguishable from
      // `1` and `100` and are canonicalized instead of rejected. The pack does
      // not currently vector that, but a verifier that must reject a
      // non-integer as WRITTEN has to look at the raw bytes, not at this value.
      if (!Number.isInteger(v)) throw new Error(`non-integer number ${v}: bodies are I-JSON integers only`);
      if (!Number.isSafeInteger(v)) throw new Error(`integer ${v} is outside the exactly-representable range`);
      return String(v);
    case "string":
      return canonString(v);
    case "object":
      if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
      // Default Array.prototype.sort compares strings by UTF-16 code unit,
      // which is exactly what RFC 8785 asks for — one of the few places where
      // the JavaScript default is the correct one. Do not "fix" it with
      // localeCompare, which is locale-dependent and would sort differently on
      // a different machine.
      return (
        "{" +
        Object.keys(v)
          .sort()
          .map((k) => canonString(k) + ":" + canon((v as { [k: string]: Json })[k]))
          .join(",") +
        "}"
      );
  }
  throw new Error(`value of unexpected type ${typeof v}`);
}

const SHORT: Record<string, string> = {
  '"': '\\"',
  "\\": "\\\\",
  "\b": "\\b",
  "\t": "\\t",
  "\n": "\\n",
  "\f": "\\f",
  "\r": "\\r",
};

// canonString is the whole reason you cannot reach for JSON.stringify here.
// JSON.stringify happens to agree on this input today, but it is specified to
// escape lone surrogates as \udXXX and says nothing that stops an engine from
// widening the escape set — and the canonical bytes are what a signature
// commits to. Spell the rule out rather than inherit it.
function canonString(s: string): string {
  let out = '"';
  // for..of iterates by code point, so an astral character arrives whole and a
  // LONE surrogate arrives alone — which is how it gets caught rather than
  // silently turned into U+FFFD by Buffer.from() at the end.
  for (const ch of s) {
    const cp = ch.codePointAt(0)!;
    if (SHORT[ch] !== undefined) {
      out += SHORT[ch];
    } else if (cp < 0x20) {
      // Lowercase hex, long form, only for the C0 characters that have no short
      // escape. U+007F (DEL) and the C1 block are NOT escaped.
      out += "\\u" + cp.toString(16).padStart(4, "0");
    } else if (cp >= 0xd800 && cp <= 0xdfff) {
      throw new Error("string contains an unpaired surrogate (invalid I-JSON)");
    } else {
      // Raw for everything else: non-ASCII, and specifically `<` `>` `&` `/`
      // and U+2028/U+2029, all of which some serializers escape by habit.
      out += ch;
    }
  }
  return out + '"';
}

main();
