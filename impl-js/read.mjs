// A second client: the same records read through another resolver, assessed by the second implementation.
//
//   node impl-js/read.mjs --base URL [--summary]
//
// URL is the root of a repository served over HTTP(S) (a GitHub raw URL at a commit, a mirror, a local server):
// the client fetches .warrant/v3.json and .warrant/records.jsonl, and each blob a record names (a 64-hex value that is
// no record's id, in its refs or body) from .warrant/blobs/<hash>. The transport is not trusted: a blob whose bytes do
// not hash to its name refuses the read, and a record line altered on the way fails its signature and is rejected by
// the assessment, as any reader would see it. A named value the server holds no blob for (a code digest, a commit, a
// blob it does not have, another record's id) is counted under `unresolved` and is absent from the snapshot, never guessed.
//
// The assessment is warrant.mjs's (held byte for byte to the Python engine), with warrant.mjs's code identity: given
// the same bytes, the report equals `node impl-js/warrant.mjs assess --store DIR --config V3JSON`. `--summary` prints
// {root, lineages: {id: [state, reliance]}, rejected, unresolved}: what a reader needs to compare two clients.
import { assess, canonStr, codeIdentity, hex64, loadsLenient, nodeBackend, Refused } from "./warrant.mjs";

const SPLIT = (raw) => {
  const lines = [];
  let start = 0;
  for (let i = 0; i <= raw.length; i++) {
    if (i === raw.length || raw[i] === 0x0a) {
      if (i > start) { const l = new Uint8Array(i - start + 1); l.set(raw.subarray(start, i)); l[i - start] = 0x0a; lines.push(l); }
      start = i + 1;
    }
  }
  return lines;
};

async function get(url) {
  const r = await fetch(url);
  if (r.status === 404) return null;
  if (!r.ok) throw new Refused(`${url}: HTTP ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}

function cited(lines) {
  // every 64-hex string a record carries in its refs or anywhere in its body, and every record id
  const named = new Set();
  const walk = (v) => {
    if (typeof v === "string") { if (hex64(v)) named.add(v); }
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") Object.values(v).forEach(walk);
  };
  const dec = new TextDecoder();
  for (const l of lines) {
    try {
      const env = JSON.parse(dec.decode(l));
      walk(env.record && env.record.refs);
      walk(env.record && env.record.body);
    } catch { /* an unreadable line is the assessment's to reject */ }
  }
  return named;
}

export async function read(base, backend) {
  const root = base.endsWith("/") ? base : base + "/";
  const config = await get(root + ".warrant/v3.json");
  if (config === null) throw new Refused(`${root}: no .warrant/v3.json`);
  const doc = loadsLenient(new TextDecoder().decode(config));
  const raw = (await get(root + ".warrant/records.jsonl")) || new Uint8Array();
  const lines = SPLIT(raw);
  const named = cited(lines);
  const blobs = new Map(), missing = [];
  const wanted = [...named].sort(), got = new Array(wanted.length);
  let next = 0;
  const worker = async () => {             // 16 requests at a time; the results are put back in order
    while (next < wanted.length) { const k = next++; got[k] = await get(root + ".warrant/blobs/" + wanted[k]); }
  };
  await Promise.all(Array.from({ length: 16 }, worker));
  for (let k = 0; k < wanted.length; k++) {
    const h = wanted[k], b = got[k];
    if (b === null) { missing.push(h); continue; }
    if ((await backend.sha256(b)) !== h) throw new Refused(`the transport altered blob ${h}: its bytes do not hash to its name`);
    blobs.set(h, b);
  }
  return { lines, blobs, doc, missing };
}

async function main(argv) {
  const fs = await import("node:fs");
  const backend = await nodeBackend();
  const opt = (name) => { const k = argv.indexOf(name); return k >= 0 ? argv[k + 1] : undefined; };
  const base = opt("--base");
  if (!base) { process.stderr.write("usage: read.mjs --base URL [--summary]\n"); return 2; }
  const code = await codeIdentity(new Uint8Array(fs.readFileSync(new URL("./warrant.mjs", import.meta.url))), backend);
  try {
    const { lines, blobs, doc, missing } = await read(base, backend);
    const rep = await assess({ lines, blobs, trust: doc.trust, profile: doc.profile, as_of: null, code }, backend);
    if (argv.includes("--summary")) {
      const lineages = {};
      for (const [L, lin] of Object.entries(rep.lineages)) lineages[L] = [lin.state, lin.reliance];
      process.stdout.write(canonStr({ root: rep.snapshot, lineages, rejected: Object.keys(rep.rejected).length, unresolved: missing.length }) + "\n");
    } else {
      process.stdout.write(canonStr(rep) + "\n");
    }
  } catch (e) {
    if (e instanceof Refused) { process.stdout.write(canonStr({ refused: e.message }) + "\n"); return 2; }
    throw e;
  }
  return 0;
}

if (typeof process !== "undefined" && process.argv && import.meta.url === (await import("node:url")).pathToFileURL(process.argv[1] || "").href) {
  process.exitCode = await main(process.argv.slice(2));
}
