#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PACK = path.join(ROOT, "operands", "warrant-conformance-1.2.0");
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const bytes = (rel) => readFileSync(path.join(ROOT, rel));
const text = (rel) => bytes(rel).toString("utf8");
const json = (rel) => JSON.parse(text(rel));

let failures = 0;
function check(label, condition, detail = "") {
  process.stdout.write(`${condition ? "ok " : "BAD"}  ${label}${detail ? ` [${detail}]` : ""}\n`);
  if (!condition) failures++;
}

function extractOneModule(response) {
  const matches = [...response.matchAll(/```(?:(?:javascript|js)\s*)?\n([\s\S]*?)```/gi)];
  if (matches.length !== 1) return null;
  return matches[0][1].endsWith("\n") ? matches[0][1] : `${matches[0][1]}\n`;
}

function aggregateStream(rel) {
  const frames = text(rel).trim().split("\n").map((line) => JSON.parse(line));
  return {
    response: frames.map((frame) => frame.response || "").join(""),
    thinking: frames.map((frame) => frame.thinking || "").join(""),
    final: frames.at(-1),
  };
}

function specExcerpt(numbers) {
  const source = text("operands/SPEC.md");
  const matches = [...source.matchAll(/^## (\d+)\.[^\n]*$/gm)];
  return numbers.map((number) => {
    const at = matches.findIndex((match) => Number(match[1]) === number);
    if (at < 0) throw new Error(`SPEC section ${number} not found`);
    const start = matches[at].index;
    const end = at + 1 < matches.length ? matches[at + 1].index : source.length;
    return source.slice(start, end).trimEnd();
  }).join("\n\n");
}

function contractExcerpt(classes) {
  const source = readFileSync(path.join(PACK, "CONTRACT.md"), "utf8");
  const base = source.match(/^### Base-grade classes\n([\s\S]*?)(?=^#### )/m);
  if (!base) throw new Error("CONTRACT base-grade preface not found");
  const sections = [base[1].trim()];
  for (const cls of classes) {
    const marker = `#### \`${cls}\``;
    const start = source.indexOf(marker);
    if (start < 0) throw new Error(`CONTRACT class ${cls} not found`);
    const rest = source.slice(start + marker.length);
    const next = rest.search(/^#{3,4} /m);
    sections.push(source.slice(start, next < 0 ? source.length : start + marker.length + next).trimEnd());
  }
  return sections.join("\n\n");
}

const A2_STAGES = {
  canon: { file: "canon.mjs", classes: ["canon"], spec: [4] },
  parse: { file: "parse.mjs", classes: ["parse"], spec: [4] },
  validate: { file: "validate.mjs", classes: ["validate"], spec: [2, 3] },
  hashing: { file: "hashing.mjs", classes: ["blob-hash", "sig-message"], spec: [1, 5] },
};

function a2Prompt(stageName) {
  const stage = A2_STAGES[stageName];
  return [
    "You are the sole clean-room implementer in experiment NEED-002-A2c-QWEN38-JS.",
    `Implement only the Warrant conformance class module for: ${stage.classes.join(", ")}.`,
    "Use Node.js built-ins only. Do not use network access, child processes, external packages, repository source code, skeletons, or hidden guidance.",
    "No expected vector answers are supplied. Implement the rules in the frozen normative text.",
    "Your module must export handle(className, input), synchronously or asynchronously. It must return exactly {output: <class output>} when it answers, or {unsupported: <nonempty reason>} when it genuinely cannot answer. It must not read stdin or write stdout.",
    `Return exactly one fenced JavaScript block containing the complete ${stage.file} and no other fenced blocks.`,
    `\n===== VERBATIM FROZEN CONTRACT CLASS TEXT =====\n${contractExcerpt(stage.classes)}`,
    `\n===== VERBATIM FROZEN SPEC SECTIONS ${stage.spec.map((n) => `§${n}`).join(", ")} =====\n${specExcerpt(stage.spec)}`,
    `\nNow perform the task. Return the complete ${stage.file} in exactly one fenced JavaScript block.`,
  ].join("\n");
}

const A3_STAGES = {
  "verify-sig": { file: "verify-sig.mjs", classes: ["verify-sig"], spec: [5], dependencies: [] },
  "verify-store": {
    file: "verify-store.mjs",
    classes: ["verify-store"],
    spec: [2, 3, 4, 5, 6],
    dependencies: ["canon.mjs", "parse.mjs", "validate.mjs", "hashing.mjs", "verify-sig.mjs"],
  },
};

function a3FocusedPrompt(stageName, reportRel) {
  const stage = A3_STAGES[stageName];
  const parts = [
    "You are a contributor to iterative experiment NEED-002-A3-COLLAB-JS.",
    `Repair only candidate/${stage.file} until the collaborative JavaScript candidate conforms to the frozen Warrant contract.`,
    "This is construction, not a one-shot benchmark. Test feedback and prior model contributions are legitimate inputs.",
    "Use Node.js built-ins only. Do not use network access, child processes, external packages, or Warrant implementation source.",
    "The candidate namespace is FLAT. Your file is physically beside every dependency and candidate/main.mjs. Import a sibling only as ./<name>.mjs. Never use ../ and never guess another directory.",
    "Your module must export handle(className, input), synchronously or asynchronously. It must return exactly {output: <class output>} when it answers, or {unsupported: <nonempty reason>} when it genuinely cannot answer. It must not read stdin or write stdout.",
    `Return exactly one fenced JavaScript block containing the complete candidate/${stage.file}; no prose outside it and no other fenced blocks.`,
    `\n===== VERBATIM FROZEN CONTRACT =====\n${contractExcerpt(stage.classes)}`,
    `\n===== VERBATIM FROZEN SPEC ${stage.spec.map((n) => `§${n}`).join(", ")} =====\n${specExcerpt(stage.spec)}`,
    `\n===== REPLACEMENT MODE =====\nWrite a clean replacement from the contract and observations below. Do not copy or preserve the current module merely because it exists. The current module is deliberately omitted: an earlier model became trapped reproducing one of its long hexadecimal literals.`,
  ];
  for (const dependency of stage.dependencies) {
    parts.push(`\n===== CURRENT SIBLING candidate/${dependency} =====\n${text(`candidate/${dependency}`)}`);
  }
  parts.push(`\n===== EXACT MACHINE REPORT =====\n${text(reportRel)}`);
  for (const cls of stage.classes) {
    parts.push(`\n===== PUBLIC FROZEN VECTOR FILE ${cls}.json =====\n${text(`operands/warrant-conformance-1.2.0/vectors/${cls}.json`)}`);
  }
  if (stageName === "verify-sig") {
    for (const diagnostic of ["verify-sig-q1-node.json", "verify-sig-q2-node.json"]) {
      parts.push(`\n===== MACHINE-OBSERVED NODE DIAGNOSTIC ${diagnostic} =====\n${text(`diagnostics/${diagnostic}`)}`);
    }
  }
  parts.push(`\nNow repair candidate/${stage.file}. Preserve correct behavior as well as fixing failures.`);
  return parts.join("\n");
}

check("frozen SPEC", sha256(bytes("operands/SPEC.md")) === "3fc90963cb353d649bf5c7097a0c2e2b26a78bd86be2bc08abf7655d2f0c38ba");
check("frozen pack tarball", sha256(bytes("operands/warrant-conformance-1.2.0.tar.gz")) === "3226f8b4c9641247b1bf80cd781d11d082d0efef0428c71e129daef030251468");
check("A2 prompt builder source", sha256(bytes("provenance/a2c/orchestrate.mjs")) === "0dd88c037090a6b2dc191ccb50f833212d556cb6ff2f84a1ba37a0350515585c");

const inherited = {
  "canon-e": ["canon", "candidate/canon.mjs"],
  "parse-a": ["parse", "candidate/parse.mjs"],
  "validate-a": ["validate", "candidate/validate.mjs"],
  "hashing-a": ["hashing", "candidate/hashing.mjs"],
};
for (const [stem, [stage, candidate]] of Object.entries(inherited)) {
  const promptRel = `provenance/a2c/${stem}.prompt.txt`;
  const responseRel = `provenance/a2c/${stem}.response.txt`;
  const record = json(`provenance/a2c/${stem}.generation.json`);
  const stream = aggregateStream(`provenance/a2c/${stem}.ollama.jsonl`);
  const extracted = extractOneModule(text(responseRel));
  check(`${stem} prompt reconstructed from allowed inputs`, text(promptRel) === a2Prompt(stage));
  check(`${stem} prompt digest`, sha256(bytes(promptRel)) === record.prompt_sha256);
  check(`${stem} response digest`, sha256(bytes(responseRel)) === record.response_sha256);
  check(`${stem} raw stream aggregates to response`, stream.response === text(responseRel));
  check(`${stem} exact model`, record.model === "qwen3.8:27b-mlx" && stream.final.model === record.model);
  check(`${stem} terminal stream`, stream.final.done === true && stream.final.done_reason === "stop");
  check(`${stem} accepted complete output`, record.extraction === "ACCEPTED" && extracted !== null);
  check(`${stem} output is final ${candidate}`, extracted !== null && sha256(Buffer.from(extracted)) === record.output_sha256 && Buffer.from(extracted).equals(bytes(candidate)));
}

const repairs = [
  {
    stem: "verify-sig-q3-qwen3.8_27b-mlx",
    stage: "verify-sig",
    report: "reports/q2-verify-sig.json",
    candidate: "candidate/verify-sig.mjs",
    model: "qwen3.8:27b-mlx",
  },
  {
    stem: "verify-store-s2-gemma4_31b-mlx",
    stage: "verify-store",
    report: "reports/q1-verify-store.json",
    candidate: "candidate/verify-store.mjs",
    model: "gemma4:31b-mlx",
  },
];
for (const item of repairs) {
  const prefix = `transcripts/${item.stem}`;
  const record = json(`${prefix}.generation.json`);
  const stream = aggregateStream(`${prefix}.ollama.jsonl`);
  const extracted = extractOneModule(text(`${prefix}.response.txt`));
  check(`${item.stage} prompt reconstructed from allowed inputs`, text(`${prefix}.prompt.txt`) === a3FocusedPrompt(item.stage, item.report));
  check(`${item.stage} prompt digest`, sha256(bytes(`${prefix}.prompt.txt`)) === record.prompt_sha256);
  check(`${item.stage} response digest`, sha256(bytes(`${prefix}.response.txt`)) === record.response_sha256);
  check(`${item.stage} raw stream aggregates to response`, stream.response === text(`${prefix}.response.txt`));
  check(`${item.stage} exact model`, record.model === item.model && stream.final.model === record.model);
  check(`${item.stage} terminal stream`, stream.final.done === true && stream.final.done_reason === "stop");
  check(`${item.stage} generation completed`, record.done === true && record.done_reason === "stop" && record.extraction === "ACCEPTED");
  check(`${item.stage} output is final ${item.candidate}`, extracted !== null && sha256(Buffer.from(extracted)) === record.source_after_sha256 && Buffer.from(extracted).equals(bytes(item.candidate)));
}

const contributions = json("CONTRIBUTIONS.json");
check(
  `${contributions.transport.path} matches transport ledger`,
  contributions.transport.semantic_credit === false &&
    sha256(bytes(contributions.transport.path)) === contributions.transport.sha256,
);
for (const entry of contributions.final_semantic_modules) {
  check(`${entry.path} matches contribution ledger`, sha256(bytes(entry.path)) === entry.sha256);
}
const report = json("reports/s2.json");
check("final report pack digest", report.pack_digest === "5a7360ba655aae7652b47c4b5882beed7eb9ce17403aaf0b35da628c22c3bd58");
check("final report reaches base", report.grade_claimed === "base" && report.grade_achieved === "base");
check("final report exact vector", JSON.stringify(report.counts) === JSON.stringify({ PASS: 135, FAIL: 0, UNRUN: 0, ERROR: 0, "NOT-CLAIMED": 4 }));
check("all base negatives answered and rejected", report.negatives_run === 60 && report.negatives_answered === 60 && report.negatives_accepted === 0);

const boundarySource = [
  contributions.transport.path,
  ...contributions.final_semantic_modules.map((entry) => entry.path),
].map((rel) => text(rel)).join("\n");
check("flat candidate namespace", !/(?:from\s+|import\s*)["']\.\.\//.test(boundarySource));
check("no candidate network or child-process imports", !/(?:node:)?(?:https?|net|tls|child_process)["']/.test(boundarySource));

process.stdout.write(`\n${failures ? "FAIL" : "PASS"} — A2→A3 provenance and prompt-input closure ${failures ? "has inconsistencies" : "is internally reproducible"}.\n`);
process.exit(failures ? 1 : 0);
