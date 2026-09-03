#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const sha256 = (value) => createHash("sha256").update(value).digest("hex");

function tree(rel) {
  const base = path.join(ROOT, rel);
  const files = [];
  function visit(dir, prefix) {
    for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const child = path.join(dir, entry.name);
      const childRel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) visit(child, childRel);
      else if (entry.isFile()) files.push(`${rel}/${childRel}`);
    }
  }
  visit(base, "");
  return files;
}

const files = [
  "README.md",
  "EXPERIMENT-REPORT.md",
  "PROVENANCE-AUDIT.md",
  "CONTRIBUTIONS.json",
  "audit-provenance.mjs",
  "freeze-evidence.mjs",
  ...tree("candidate"),
  "diagnostics/verify-sig-q1-node.json",
  "diagnostics/verify-sig-q2-node.json",
  "operands/SPEC.md",
  "operands/warrant-conformance-1.2.0.tar.gz",
  ...tree("operands/warrant-conformance-1.2.0"),
  "reports/q1-verify-store.json",
  "reports/q2-verify-sig.json",
  "reports/s2.json",
  "transcripts/verify-sig-q3-qwen3.8_27b-mlx.generation.json",
  "transcripts/verify-sig-q3-qwen3.8_27b-mlx.ollama.jsonl",
  "transcripts/verify-sig-q3-qwen3.8_27b-mlx.prompt.txt",
  "transcripts/verify-sig-q3-qwen3.8_27b-mlx.response.txt",
  "transcripts/verify-store-s2-gemma4_31b-mlx.generation.json",
  "transcripts/verify-store-s2-gemma4_31b-mlx.ollama.jsonl",
  "transcripts/verify-store-s2-gemma4_31b-mlx.prompt.txt",
  "transcripts/verify-store-s2-gemma4_31b-mlx.response.txt",
  ...tree("provenance"),
].sort();

const duplicate = files.find((rel, index) => files.indexOf(rel) !== index);
if (duplicate) throw new Error(`duplicate evidence path: ${duplicate}`);

const lines = files.map((rel) => `${sha256(readFileSync(path.join(ROOT, rel)))}  ${rel}`);
writeFileSync(path.join(ROOT, "EVIDENCE-MANIFEST.sha256"), `${lines.join("\n")}\n`, { encoding: "utf8", flag: "w" });
process.stdout.write(`wrote EVIDENCE-MANIFEST.sha256 (${files.length} operands)\n`);
