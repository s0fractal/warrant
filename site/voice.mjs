// The door: how a reader who disagrees with one version of a lineage says so, and how that voice reaches a reader of
// the store it objects to. A voice is a challenge filed under the objector's own key's name (`key:<hex>`, docs/V3.md
// §5) in a store of voices of its own (`warrant say`, warrant/commons.py): nobody admits it and nobody can remove it,
// the publisher's rules do not count it, and it reaches a reader only when that reader reads the store of voices
// beside the publisher's (the reader's `with=`, reader.mjs readOthers).
//
// This file has no DOM in it, so node runs what the pages show (tests/impl_js_test.py J16): the steps below are the
// one source of the commands. reader-page.mjs fills them with one version's id; site/object.html shows them with their
// placeholders in `<pre class="command" data-step="NAME">` (J16 holds the two equal, and runs them).
//
//   node site/voice.mjs --steps                      the steps, with their placeholders     # canonical JSON
//   node site/voice.mjs --version ID                 the commands for one version
//   node site/voice.mjs --bridge ID                  the second door: the issue form's address for one version, per stance
//   node site/voice.mjs --base URL --lineage ID      the blocks of that lineage's effective version and leaf
//   node site/voice.mjs --with URL... --add TEXT     the `with=` list after the page's field adds TEXT
import { canonStr } from "./warrant.mjs";

export const CLONE = "https://github.com/s0fractal/warrant.git";
export const PACKAGE = "warrant-graph>=3.0.0a7";   // the first release with `warrant say`; the specifier names a pre-release, so pip admits one
export const VERSION = "VERSION_ID";      // the placeholders object.html shows; the reader fills VERSION_ID alone
export const STORE = "STORE_URL";
export const VOICES = "VOICES_URL";
export const LINEAGE = "LINEAGE_ID";

// The commands, step by step, from an empty directory: the released package installed into a venv of the objector's
// own (never the system's interpreter, which PEP 668 refuses), the voice said into ./voices (made on first use: it
// trusts nobody and gives nobody a role), that directory made a git repository to publish, and, for a reader at a
// terminal, the publisher's store read with the voices beside it (the reader's CLI is in the repository, not in the
// package: the page reads the same from an address). Each line is one command a shell runs as written; `cd` lines carry
// the directory to the next.
export const STEPS = [
  { step: "install", lines: ["python3 -m venv .venv", `.venv/bin/pip install "${PACKAGE}"`] },
  { step: "say", lines: [`.venv/bin/warrant say --store voices ${VERSION} "why this version is wrong"`] },
  { step: "publish", lines: ["cd voices", "git init", "git add .warrant", "git commit -m \"a voice\""] },
  { step: "read", lines: ["cd ..", `git clone ${CLONE}`, `node warrant/site/reader.mjs --base ${STORE} --with ${VOICES} --lineage ${LINEAGE}`] },
];

// What the reader's block says beside the commands: what an objection is and is not.
export const MEANING = [
  "The objection is a challenge under your own key's name, key:<hex>: the key is made on first use and its seed kept at ~/.config/warrant/commons/commons.seed (--as NAME keeps another). Nobody admits it and nobody can remove it.",
  "The publisher's rules do not count it: the lineage's state and reliance in the publisher's store do not move. It counts for a reader only when a replayer that reader trusts reproduces it.",
  "To make it visible, publish the directory voices at any HTTP(S) address (a public git repository's raw address is one, such as https://raw.githubusercontent.com/OWNER/REPOSITORY/BRANCH/) and add that address under \"Other stores beside this one\": a reader who reads it sees your voice on this lineage, uncounted. A store nobody reads is seen by nobody.",
];

const ID = /^[0-9a-f]{64}$/;                 // a record id: lowercase hex, 64 characters, nothing else (JS `$`: the end)

// The command lines for one version (the steps that file and publish it: install, say, publish), or null when
// `version` is no record id: nothing but a 64-hex id is ever put into a command.
export function voiceCommands(version) {
  if (typeof version !== "string" || !ID.test(version)) return null;
  return STEPS.filter((s) => s.step !== "read").flatMap((s) => s.lines.map((l) => l.replaceAll(VERSION, version)));
}

// The second door, for a reader with a GitHub account and nothing else: an issue through this repository's form
// (.github/ISSUE_TEMPLATE/voice.yml), which the bridge files as one record in its own store of voices (warrant/bridge.py,
// .github/workflows/voice-bridge.yml). That record says that GitHub delivered the issue, opened by that account: the
// bridge's statement, not the account's signature. `form` is the form's address, `store` where the bridge's store is
// published (the branch `voices`).
export const BRIDGE = { form: "https://github.com/s0fractal/warrant/issues/new?template=voice.yml",
                        store: "https://raw.githubusercontent.com/s0fractal/warrant/voices/" };
export const STANCES = ["objection", "support"];

// The form's address with one version's id and a stance filled in (GitHub fills a form's fields from the query, by
// their ids), or null: nothing but a 64-hex id and one of the two stances is ever put into it.
export function bridgeLink(version, stance) {
  if (typeof version !== "string" || !ID.test(version) || !STANCES.includes(stance)) return null;
  return `${BRIDGE.form}&record=${version}&stance=${stance}`;
}

// The blocks of one opened lineage (reader.mjs lineage(): its versions, newest first): the effective version's and
// the leaf's, one block when they are one version. Built from each version's id and its two flags alone, so nothing a
// record says can reach a command.
export function targets(view) {
  const out = [];
  for (const v of view?.versions ?? []) {
    if (!v.effective && !v.leaf) continue;
    const commands = voiceCommands(v.id);
    if (commands) out.push({ version: v.id, effective: Boolean(v.effective), leaf: Boolean(v.leaf), commands });
  }
  return out;
}

// {with} the `with=` list after adding `text`, or {why} it was not added: an http(s) address with no credentials in
// it (it is fetched, shown and kept in the page's address), normalised to end in "/"; one listed already is not added
// twice.
export function withAdded(list, text) {
  const t = typeof text === "string" ? text.trim() : "";
  if (!t) return { why: "no address was given" };
  let u;
  try { u = new URL(t); } catch { return { why: `${JSON.stringify(t)} is no URL` }; }
  if (u.protocol !== "https:" && u.protocol !== "http:") return { why: `${JSON.stringify(t)} is not http(s)` };
  if (u.username || u.password) return { why: `${JSON.stringify(t)} carries credentials` };
  const base = u.href.endsWith("/") ? u.href : u.href + "/";
  const norm = (x) => (x.endsWith("/") ? x : x + "/");
  return { with: (list ?? []).some((x) => norm(x) === base) ? [...list] : [...(list ?? []), base] };
}

async function main(argv) {
  const opt = (name) => { const k = argv.indexOf(name); return k >= 0 ? argv[k + 1] : undefined; };
  const all = (name) => argv.flatMap((a, k) => (a === name && k + 1 < argv.length ? [argv[k + 1]] : []));
  let out;
  if (argv.includes("--steps")) out = { steps: STEPS, clone: CLONE, package: PACKAGE, meaning: MEANING };
  else if (opt("--bridge") !== undefined) out = { bridge: BRIDGE, links: STANCES.map((x) => bridgeLink(opt("--bridge"), x)), bad: bridgeLink(opt("--bridge"), "accept") };
  else if (opt("--version") !== undefined) out = { commands: voiceCommands(opt("--version")) };
  else if (opt("--add") !== undefined) out = withAdded(all("--with"), opt("--add"));
  else if (opt("--base") !== undefined && opt("--lineage") !== undefined) {
    const fs = await import("node:fs");
    const { nodeBackend } = await import("./warrant.mjs");
    const reader = await import("./reader.mjs");
    const backend = await nodeBackend();
    const store = await reader.fetchStore(opt("--base"), backend);
    const source = new Uint8Array(fs.readFileSync(new URL("./warrant.mjs", import.meta.url)));
    const r = await reader.read(store, reader.receiver(store.doc, null), backend, source);
    out = { targets: targets(reader.lineage(r, opt("--lineage"))) };
  } else {
    process.stderr.write("usage: voice.mjs --steps | --version ID | --bridge ID | --base URL --lineage ID | [--with URL]... --add TEXT\n");
    return 2;
  }
  process.stdout.write(canonStr(out) + "\n");
  return 0;
}

if (typeof process !== "undefined" && process.argv && import.meta.url === (await import("node:url")).pathToFileURL(process.argv[1] || "").href) {
  process.exitCode = await main(process.argv.slice(2));
}
