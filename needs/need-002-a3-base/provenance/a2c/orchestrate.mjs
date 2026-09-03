#!/usr/bin/env node

import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

const ROOT = path.dirname(new URL(import.meta.url).pathname);
const PACK = path.join(ROOT, "operands", "warrant-conformance-1.2.0");
const MODEL = "qwen3.8:27b-mlx";

const STAGES = {
  canon: { file: "canon.mjs", classes: ["canon"], spec: [4] },
  parse: { file: "parse.mjs", classes: ["parse"], spec: [4] },
  validate: { file: "validate.mjs", classes: ["validate"], spec: [2, 3] },
  hashing: { file: "hashing.mjs", classes: ["blob-hash", "sig-message"], spec: [1, 5] },
  "verify-sig": { file: "verify-sig.mjs", classes: ["verify-sig"], spec: [5] },
  "verify-store": {
    file: "verify-store.mjs",
    classes: ["verify-store"],
    spec: [2, 3, 4, 5, 6],
    dependencies: ["canon.mjs", "parse.mjs", "validate.mjs", "hashing.mjs", "verify-sig.mjs"]
  }
};

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const text = (file) => readFile(file, "utf8");

function extractOneModule(response) {
  const matches = [...response.matchAll(/```(?:(?:javascript|js)\s*)?\n([\s\S]*?)```/gi)];
  if (matches.length !== 1) throw new Error(`expected exactly one JavaScript code fence, got ${matches.length}`);
  return matches[0][1].endsWith("\n") ? matches[0][1] : `${matches[0][1]}\n`;
}

async function specExcerpt(numbers) {
  const source = await text(path.join(ROOT, "operands", "SPEC.md"));
  const matches = [...source.matchAll(/^## (\d+)\.[^\n]*$/gm)];
  const sections = [];
  for (const number of numbers) {
    const at = matches.findIndex((match) => Number(match[1]) === number);
    if (at < 0) throw new Error(`SPEC section ${number} not found`);
    const start = matches[at].index;
    const end = at + 1 < matches.length ? matches[at + 1].index : source.length;
    sections.push(source.slice(start, end).trimEnd());
  }
  return sections.join("\n\n");
}

async function contractExcerpt(classes) {
  const source = await text(path.join(PACK, "CONTRACT.md"));
  const base = source.match(/^### Base-grade classes\n([\s\S]*?)(?=^#### )/m);
  if (!base) throw new Error("CONTRACT base-grade encoding preface not found");
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

async function modulePrompt(stageName, repairReport) {
  const stage = STAGES[stageName];
  const sections = [
    `You are the sole clean-room implementer in experiment NEED-002-A2c-QWEN38-JS.`,
    `Implement only the Warrant conformance class module for: ${stage.classes.join(", ")}.`,
    `Use Node.js built-ins only. Do not use network access, child processes, external packages, repository source code, skeletons, or hidden guidance.`,
    `No expected vector answers are supplied. Implement the rules in the frozen normative text.`,
    `Your module must export handle(className, input), synchronously or asynchronously. It must return exactly {output: <class output>} when it answers, or {unsupported: <nonempty reason>} when it genuinely cannot answer. It must not read stdin or write stdout.`,
    `Return exactly one fenced JavaScript block containing the complete ${stage.file} and no other fenced blocks.`,
    `\n===== VERBATIM FROZEN CONTRACT CLASS TEXT =====\n${await contractExcerpt(stage.classes)}`,
    `\n===== VERBATIM FROZEN SPEC SECTIONS ${stage.spec.map((n) => `§${n}`).join(", ")} =====\n${await specExcerpt(stage.spec)}`
  ];
  if (stage.dependencies) {
    sections.push(`\nThe following modules are your earlier outputs and expose the same handle(className, input) result contract: ${stage.dependencies.join(", ")}. You may import them by relative path. Their source is deliberately not duplicated into this prompt.`);
  }
  if (repairReport) {
    sections.push(`\n===== YOUR CURRENT ${stage.file} =====\n${await text(path.join(ROOT, "modules", stage.file))}`);
    sections.push(`\n===== RAW CLASS-SCOPED MACHINE REPORT =====\n${await text(path.join(ROOT, "reports", repairReport))}`);
    sections.push(`\nThis is one repair pass on your own module. Treat the report as observations only; no diagnosis or suggested algorithm is supplied.`);
  }
  sections.push(`\nNow perform the task. Return the complete ${stage.file} in exactly one fenced JavaScript block.`);
  return sections.join("\n");
}

async function integrationPrompt(repairReport) {
  const sections = [
    `You are the sole clean-room implementer in experiment NEED-002-A2c-QWEN38-JS.`,
    `Integrate your previously authored modules into one stateless Node.js warrant-conformance/1 candidate.`,
    `Write only candidate/main.mjs. Import and dispatch to the modules; do not copy or reimplement their class algorithms in main.mjs.`,
    `Target base grade only and decline settlement/ski-run. Use only Node.js built-ins.`,
    `The process must read exactly one JSON request from stdin, write exactly one JSON response to stdout, echo the opaque id, and follow the frozen contract.`,
    `Return exactly one fenced JavaScript block containing complete candidate/main.mjs and no other fenced blocks.`,
    `\n===== FROZEN CONTRACT.md =====\n${await text(path.join(PACK, "CONTRACT.md"))}`
  ];
  for (const stage of Object.values(STAGES)) {
    try {
      sections.push(`\n===== YOUR AVAILABLE ${stage.file} =====\n${await text(path.join(ROOT, "modules", stage.file))}`);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      sections.push(`\n===== UNAVAILABLE ${stage.file} =====\nNo complete model output was produced for this module. Do not claim or implement its classes in main.mjs; return unsupported for them.`);
    }
  }
  if (repairReport) {
    sections.push(`\n===== YOUR CURRENT candidate/main.mjs =====\n${await text(path.join(ROOT, "candidate", "main.mjs"))}`);
    sections.push(`\n===== RAW MACHINE REPORT =====\n${await text(path.join(ROOT, "reports", repairReport))}`);
    sections.push(`\nThis is one integration repair pass. Treat the report as observations only; no diagnosis or suggested algorithm is supplied.`);
  }
  sections.push(`\nNow integrate the supplied modules. Return complete candidate/main.mjs in exactly one fenced JavaScript block.`);
  return sections.join("\n");
}

async function main() {
  const stageName = process.argv[2];
  const attempt = process.argv[3] || "a";
  const repairReport = process.argv[4] || null;
  if (!(stageName === "integration" || STAGES[stageName])) {
    throw new Error(`usage: node orchestrate.mjs ${[...Object.keys(STAGES), "integration"].join("|")} <attempt> [report-file]`);
  }
  if (!/^[a-z][a-z0-9-]*$/.test(attempt)) throw new Error("invalid attempt label");
  if (repairReport && !/^[a-zA-Z0-9._-]+$/.test(repairReport)) throw new Error("invalid report filename");

  await mkdir(path.join(ROOT, "transcripts"), { recursive: true });
  const prompt = stageName === "integration"
    ? await integrationPrompt(repairReport)
    : await modulePrompt(stageName, repairReport);
  const stem = `${stageName}-${attempt}`;
  await writeFile(path.join(ROOT, "transcripts", `${stem}.prompt.txt`), prompt, { flag: "wx" });

  const response = await fetch("http://127.0.0.1:11434/api/generate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      model: MODEL,
      prompt,
      stream: true,
      think: false,
      options: { temperature: 0.2, seed: 20260903, num_ctx: 32768, num_predict: 8192 }
    })
  });
  if (!response.ok) throw new Error(`ollama HTTP ${response.status}: ${await response.text()}`);
  const streamBytes = Buffer.from(await response.arrayBuffer());
  await writeFile(path.join(ROOT, "transcripts", `${stem}.ollama.jsonl`), streamBytes, { flag: "wx" });
  const frames = streamBytes.toString("utf8").trim().split("\n").map((line) => JSON.parse(line));
  if (frames.length === 0) throw new Error("ollama returned an empty stream");
  const finalFrame = frames.at(-1);
  const envelope = {
    ...finalFrame,
    response: frames.map((frame) => frame.response || "").join(""),
    thinking: frames.map((frame) => frame.thinking || "").join("")
  };
  if (typeof envelope.thinking === "string" && envelope.thinking.length > 0) {
    await writeFile(path.join(ROOT, "transcripts", `${stem}.thinking.txt`), envelope.thinking, { flag: "wx" });
  }
  await writeFile(path.join(ROOT, "transcripts", `${stem}.response.txt`), envelope.response, { flag: "wx" });
  const record = {
    stage: stageName,
    attempt,
    repair_report: repairReport,
    prompt_sha256: sha256(Buffer.from(prompt)),
    response_sha256: sha256(Buffer.from(envelope.response)),
    thinking_sha256: typeof envelope.thinking === "string" && envelope.thinking.length > 0
      ? sha256(Buffer.from(envelope.thinking))
      : null,
    model: envelope.model,
    thinking_mode: "disabled",
    done: envelope.done,
    done_reason: envelope.done_reason,
    total_duration_ns: envelope.total_duration,
    prompt_eval_count: envelope.prompt_eval_count,
    eval_count: envelope.eval_count
  };
  let source;
  try {
    source = extractOneModule(envelope.response);
    record.output_sha256 = sha256(Buffer.from(source));
    record.extraction = "ACCEPTED";
  } catch (error) {
    record.output_sha256 = null;
    record.extraction = "REFUSED";
    record.extraction_error = String(error.message || error);
    await writeFile(path.join(ROOT, "transcripts", `${stem}.generation.json`), `${JSON.stringify(record, null, 2)}\n`, { flag: "wx" });
    throw error;
  }

  const destination = stageName === "integration"
    ? path.join(ROOT, "candidate", "main.mjs")
    : path.join(ROOT, "modules", STAGES[stageName].file);
  const temporary = `${destination}.${process.pid}.tmp`;
  await writeFile(temporary, source, { flag: "wx", mode: 0o755 });
  await rename(temporary, destination);

  await writeFile(path.join(ROOT, "transcripts", `${stem}.generation.json`), `${JSON.stringify(record, null, 2)}\n`, { flag: "wx" });
  process.stdout.write(`${JSON.stringify(record, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exit(1);
});
