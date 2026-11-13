// The desk: several stores on one screen, one block each, for a reader who opens one page in the morning. Each store is
// read as the reader reads it (reader.mjs fetchStore, quick; assessed in the page under the publisher's own rules) and
// summed up: its counts, what changed for the reader since that store's mark (the reader's own mark: the same key in
// localStorage, the same representation, the same changes()), and, for an actor the reader names, how much waits for
// it (reader.mjs frontier). A store that cannot be read is named with its reason and the others still answer; a block
// is whole or it is a refusal, never partial.
//
// This file has no DOM in it, so node runs the functions the page runs (tests/impl_js_test.py J14, J15):
//
//   node site/desk.mjs [--store URL]... [--list FILE] [--kept FILE] [--marks DIR] [--actor NAME]   # canonical JSON
//        [--write-mark URL]... [--write-marks]    after answering, write the mark of now for that store (for every one)
//        [--plan]                                 only which stores would be read, and from where
//        [--watches FILE]                         the lineages watched per store, {address: [root id]} as the page keeps
//                                                 them (page.mjs, reader-watch/1): each such store's block says `watch`
//   The releases of the list (parseReleases; none when --store names the stores) are read too: `releases`.
//
// Which stores (selectStores): the addresses in the page's address (`store=URL`, repeatable; `--store`), else the list
// the reader edited on the page (localStorage; `--kept FILE`), else site/stores.json (`--list FILE`). A mark file per
// store lies in DIR, named by the SHA-256 of the store's address: the page keeps the same JSON under page.mjs markKey.
import { canonStr, Refused } from "./warrant.mjs";
import * as reader from "./reader.mjs";

export const BOUND = 3;                // stores read at once: each read asks for up to 16 blobs at a time itself
export const LIST = "stores.json";     // the default list, beside this file

// A store's address as a list may give it, or why it is none: http(s) only (a link built from it is followed), with
// no credentials in it (the address is shown and kept), normalised to end in "/" as every mark names it.
export function address(text) {
  if (typeof text !== "string" || text.trim() === "") return { why: "no address" };
  let u;
  try { u = new URL(text.trim()); } catch { return { why: `${JSON.stringify(text)} is no URL` }; }
  if (u.protocol !== "https:" && u.protocol !== "http:") return { why: `${JSON.stringify(text)} is not http(s)` };
  if (u.username || u.password) return { why: `${JSON.stringify(text)} carries credentials` };
  const base = u.href.endsWith("/") ? u.href : u.href + "/";
  return { base };
}

// [{name, base}] of a list as stores.json holds it (a JSON list of {name, base}, both strings), or a Refused naming
// what is wrong: a list is taken whole or not at all. An address listed twice is read once, under its first name.
export function parseStores(text) {
  let doc;
  try { doc = JSON.parse(text); } catch { throw new Refused("the list of stores is not JSON"); }
  if (!Array.isArray(doc)) throw new Refused("the list of stores is not a list");
  const out = [], seen = new Set();
  doc.forEach((x, k) => {
    if (isRelease(x)) return;                              // a published release (parseReleases), not a store
    if (!x || typeof x !== "object" || Array.isArray(x) || typeof x.name !== "string" || x.name.trim() === "") {
      throw new Refused(`entry ${k} of the list of stores is no {name, base}`);
    }
    const a = address(x.base);
    if (a.why) throw new Refused(`entry ${k} of the list of stores: ${a.why}`);
    if (!seen.has(a.base)) { seen.add(a.base); out.push({ name: x.name, base: a.base }); }
  });
  return out;
}

// ---------------------------------------------------------------- a published release, as data
//
// The second kind of entry of a list: {name, base, release}, where `release` names the format of what is published at
// `base` and `base + "index.json"` is its index. One kind is known, minds.published-bundles@1 (the minds repository's
// latest release as static files). The desk does NOT verify a release: it shows what the index says (the statement,
// the chain tip, when published, the endorsers and witnesses by the roster's names), says it is as published and not
// verified here, and links to the page that verifies it. No word of a verdict is the desk's own. The entry keeps a
// `base` so that a desk.mjs of an earlier release, cached apart from stores.json, reads it as a store it cannot read
// and names it, instead of refusing the whole list.

export const RELEASE = "minds.published-bundles@1";
export const RELEASE_INDEX = "index.json";
export const RELEASE_VERIFY = "https://s0fractal.github.io/minds/";
export const RELEASE_NOTE = "as published; not verified here";

const isRelease = (x) => Boolean(x) && typeof x === "object" && !Array.isArray(x) && Object.hasOwn(x, "release");

// [{name, base, format, index}] of the release entries of a list as stores.json holds it, each with `why` instead
// when it cannot be read (a name, an http(s) base, a format this desk knows); [] for a list that is not one (its
// stores are what parseStores refuses or takes).
export function parseReleases(text) {
  let doc;
  try { doc = JSON.parse(text); } catch { return []; }
  if (!Array.isArray(doc)) return [];
  return doc.filter(isRelease).map((x, k) => {
    const name = typeof x.name === "string" && x.name.trim() !== "" ? x.name : `release ${k}`;
    const a = address(x.base);
    if (a.why) return { name, base: null, format: null, index: null, why: a.why };
    if (x.release !== RELEASE) return { name, base: a.base, format: null, index: null, why: `the format ${JSON.stringify(x.release)} is not one this desk reads (it reads ${RELEASE})` };
    return { name, base: a.base, format: RELEASE, index: a.base + RELEASE_INDEX, why: null };
  });
}

const str = (v) => typeof v === "string" && v !== "";
const strs = (v) => Array.isArray(v) && v.every(str);
const obj = (v) => Boolean(v) && typeof v === "object" && !Array.isArray(v);

// The members a minds.published-bundles@1 index must have, each with its test; the first that fails is named.
const MEMBERS = [
  ["about", str], ["chain", str], ["chain_tip", str], ["published", str],
  ["projection", obj], ["projection.id", str], ["projection.tip", str], ["projection.witnesses", strs], ["projection.file", str], ["projection.sha256", str],
  ["attestation", obj], ["attestation.decision", str], ["attestation.statement", str], ["attestation.endorsers", strs],
  ["attestation.file", str], ["attestation.sha256", str],
  ["roster", (v) => Array.isArray(v) && v.every((x) => obj(x) && str(x.name) && str(x.key))],
  ["rules", (v) => Array.isArray(v) && v.every((x) => obj(x) && str(x.id) && str(x.file) && str(x.sha256))],
  ["verifier", obj], ["verifier.main", str], ["verifier.file", str], ["verifier.sha256", str],
];
const member = (doc, path) => path.split(".").reduce((v, k) => (obj(v) && Object.hasOwn(v, k) ? v[k] : undefined), doc);

// The block of one release from its index's text: {read: true, ...what it says} or {read: false, why}, never a part.
// Keys are named by the roster (the publisher's word: name null for a key it does not name).
export function releaseBlock(entry, text) {
  const head = { name: entry.name, base: entry.base, index: entry.index };
  let doc;
  try { doc = JSON.parse(text); } catch { return { ...head, read: false, why: "the index is not JSON" }; }
  if (!obj(doc)) return { ...head, read: false, why: "the index is not a JSON object" };
  if (doc.format !== RELEASE) return { ...head, read: false, why: `the index's format is ${JSON.stringify(doc.format ?? null)}, not ${RELEASE}` };
  const bad = MEMBERS.find(([path, ok]) => !ok(member(doc, path)));
  if (bad) return { ...head, read: false, why: `the index's member ${bad[0]} is missing or not of its form` };
  const names = new Map(doc.roster.map((x) => [x.key, x.name]));
  const named = (keys) => keys.map((key) => ({ key, name: names.get(key) ?? null }));
  return { ...head, read: true, why: null, note: RELEASE_NOTE, verify: RELEASE_VERIFY + "?index=" + encodeURIComponent(entry.index),
           format: doc.format, chain: doc.chain, chain_tip: doc.chain_tip, published: doc.published,
           statement: doc.attestation.statement, endorsers: named(doc.attestation.endorsers), witnesses: named(doc.projection.witnesses) };
}

// The blocks of `entries` (parseReleases), fetched BOUND at a time: an entry that cannot be used, an index that is not
// fetched or answers other than 200, each named with its reason; the others still answer.
export async function readReleases(entries, { fetcher = globalThis.fetch } = {}) {
  return bounded(entries, BOUND, async (e) => {
    const head = { name: e.name, base: e.base, index: e.index };
    if (e.why) return { ...head, read: false, why: e.why };
    let r;
    try { r = await fetcher(e.index); } catch (x) { return { ...head, read: false, why: `not fetched (${x?.message ?? x})` }; }
    if (!r.ok) return { ...head, read: false, why: `HTTP ${r.status}` };
    let text;
    try { text = await r.text(); } catch (x) { return { ...head, read: false, why: `not fetched (${x?.message ?? x})` }; }
    return releaseBlock(e, text);
  });
}

// Which releases the desk shows: those of the list, unless the address names its stores (a link names what it shows).
export const releasesOf = (plan, list) => (plan.from === "address" || list === null ? [] : parseReleases(list));

// The page's editor: one store a line, its address first and then, after a space, its name (the address when none);
// blank lines are skipped. A Refused names the first line that is no address.
export function storesFromLines(text) {
  const out = [];
  String(text).split("\n").forEach((line, k) => {
    const t = line.trim();
    if (!t) return;
    const cut = t.search(/\s/), url = cut < 0 ? t : t.slice(0, cut), name = cut < 0 ? "" : t.slice(cut).trim();
    const a = address(url);
    if (a.why) throw new Refused(`line ${k + 1}: ${a.why}`);
    out.push({ name: name || a.base, base: a.base });
  });
  return parseStores(JSON.stringify(out));                 // the one validation, and one read per address
}

export const linesOf = (stores) => stores.map((s) => (s.name === s.base ? s.base : `${s.base} ${s.name}`)).join("\n");

// {stores, from, why}: which stores the desk reads. `addresses` (the address's `store=`) first: a link names its
// stores; then `kept` (the text the page keeps, or null), when it is a list parseStores takes and not empty; then
// `list` (the text of stores.json). `why` names a kept list or an address that could not be used; it is never silent.
export function selectStores({ addresses = [], kept = null, list = null } = {}) {
  const why = [];
  if (addresses.length) {
    const stores = [];
    for (const x of addresses) {
      const a = address(x);
      if (a.why) why.push(`store=${a.why}`);
      else if (!stores.some((s) => s.base === a.base)) stores.push({ name: a.base, base: a.base });
    }
    if (stores.length) return { stores, from: "address", why };
  }
  if (kept !== null) {
    try {
      const stores = parseStores(kept);
      if (stores.length) return { stores, from: "kept", why };
      why.push("the list kept in this browser is empty");
    } catch (e) { why.push(`the list kept in this browser is not used: ${e.message}`); }
  }
  if (list === null) return { stores: [], from: "none", why: [...why, "no list of stores was read"] };
  try { return { stores: parseStores(list), from: "list", why }; }
  catch (e) { return { stores: [], from: "none", why: [...why, `${LIST}: ${e.message}`] }; }
}

// `items` through `fn`, at most `n` at once; the results in the order of `items`.
async function bounded(items, n, fn) {
  const out = new Array(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) { const k = next++; out[k] = await fn(items[k], k); }  // NOSONAR S9382: one store after another within a worker, n workers at once
  };
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, worker));
  return out;
}

// The reader.mjs this file needs, or a Refused: a page may hold a reader.mjs of an earlier release, cached apart.
function readerOk() {
  for (const f of ["fetchStore", "read", "receiver", "summary", "rows", "changes", "changesLine", "makeMark", "rulesId", "frontier", "waitsFor"]) {
    if (typeof reader[f] !== "function") throw new Refused(`reader.mjs is of an earlier release (it has no ${f}): reload the page`);
  }
}

// One store's block, from its read `r`, its mark (or null), the actor named ("" for none) and the lineages watched in
// it (`watch`, a list as reader.mjs parseWatch takes it, or null): whole, or it throws. A block with no watch list is
// as it was; with one, `watch` says the watched answer (reader.mjs watched(), the reader's own function).
export async function block(s, r, mark, { backend, source, actor, watch = null }) {
  const sum = reader.summary(r), all = reader.rows(r);
  const watching = watch?.length && typeof reader.since === "function" && typeof reader.watched === "function";
  const since = watching ? await reader.since(r, mark, backend, source, { base: s.base }) : null;
  const c = since ? reader.changesOf(r, since) : await reader.changes(r, mark, backend, source, { base: s.base });
  return {
    name: s.name, base: s.base, read: true, why: null,
    repository: sum.repository, rules: sum.rules, records: sum.records, rejected: sum.rejected, lineages: all.length,
    reliance: sum.reliance,                                // reader.mjs shown(): never ELIGIBLE on pins not compared
    challenged: all.filter((x) => x.standing > 0).length,  // lineages with a counted challenge that stands
    changes: { mark: c.mark !== null, at: c.mark?.at ?? null, line: reader.changesLine(c), new: c.mark ? c.new : null, quiet: c.mark ? c.quiet : null,
               listed: c.mark ? c.listed.map((x) => ({ lineage: x.lineage, schema: x.schema, title: x.title, new: x.new })) : [] },
    ...(actor ? { waits: waitsCount(reader.waitsFor(r, actor)) } : {}),          // nothing computed without an actor
    ...(since ? { watch: watchOf(reader.watched(r, since, watch)) } : {}),      // nothing computed without a watch list
  };
}

const watchOf = (w) => ({ outcome: w.outcome, line: w.line, watch: w.watch, refused: w.refused.map((x) => x.value), reasons: w.reasons,
                          touched: w.touched.map((t) => ({ lineage: t.lineage, schema: t.schema, title: t.title, said: t.said, witness: t.witness.length })) });

const waitsCount = (w) => ({ actor: w.actor, roles: w.roles, count: w.count, attest: w.attest.length, pending: w.pending.length, challenged: w.challenged.length });

// [{block, r, rules}] of `stores`, read BOUND at a time: `marks(base, rulesId)` gives a store's mark ({mark, why}),
// as the page keeps it or the CLI's file holds it; `done(k, entry)`, when given, hears of each store as it is read (a
// page draws it at once). A store that cannot be read (a refusal, anything the engine throws on it) is {name, base,
// read: false, why}; the others still answer.
export async function readDesk(stores, { backend, source, fetcher = globalThis.fetch, marks, actor = "", done = null, watches = null }) {
  readerOk();
  return bounded(stores, BOUND, async (s, k) => {
    const entry = await readOne(s, { backend, source, fetcher, marks, actor, watches });
    done?.(k, entry);
    return entry;
  });
}

// One store's entry: its block whole, or its refusal; a `done` that throws is the page's, not the store's.
async function readOne(s, { backend, source, fetcher, marks, actor, watches }) {
  try {
    const store = await reader.fetchStore(s.base, backend, { fetcher });
    const r = await reader.read(store, reader.receiver(store.doc, null), backend, source);
    const rules = await reader.rulesId(r, backend), kept = await marks(s.base, rules);
    const b = await block(s, r, kept.mark, { backend, source, actor, watch: watches ? watches(s.base) : null });
    if (kept.why) b.changes.line = kept.why;              // storage that cannot be read: said, nothing presented as changed
    return { block: b, r, rules };
  } catch (e) {
    return { block: { name: s.name, base: s.base, read: false, why: String(e?.message ?? e) }, r: null, rules: null };
  }
}

// (address) => its watch list or null, of the text of a watches file ({address: [id]}, the page's reader-watch/1); a
// file that is not that is refused whole.
export function watchesFile(text) {
  let doc;
  try { doc = JSON.parse(text); } catch { throw new Refused("the watches file is not JSON"); }
  if (!doc || typeof doc !== "object" || Array.isArray(doc) || !Object.values(doc).every((v) => Array.isArray(v))) throw new Refused("the watches file is no {address: [id]}");
  const by = new Map(Object.entries(doc).map(([a, v]) => [address(a).base ?? a, v]));
  return (base) => (by.has(base) && by.get(base).length ? by.get(base).map(String) : null);
}

// The mark file of a store in DIR: the SHA-256 of its address (UTF-8), as hex, and ".json".
export async function markName(base, backend) {
  return (await backend.sha256(new TextEncoder().encode(base))) + ".json";
}

async function main(argv) {
  const fs = await import("node:fs"), path = await import("node:path");
  const { nodeBackend } = await import("./warrant.mjs");
  const backend = await nodeBackend();
  const opt = (name) => { const k = argv.indexOf(name); return k >= 0 ? argv[k + 1] : undefined; };
  const all = (name) => argv.flatMap((a, k) => (a === name && k + 1 < argv.length ? [argv[k + 1]] : []));
  const text = (file) => (file === undefined ? null : fs.readFileSync(file, "utf8"));
  const listFile = opt("--list") ?? new URL("./" + LIST, import.meta.url);
  const plan = selectStores({ addresses: all("--store"), kept: text(opt("--kept")), list: fs.readFileSync(listFile, "utf8") });
  if (argv.includes("--plan")) { process.stdout.write(canonStr(plan) + "\n"); return 0; }
  const dir = opt("--marks"), actor = (opt("--actor") ?? "").trim();
  const marks = async (base) => (dir === undefined ? { mark: null, why: null }
    : { mark: reader.markFile(fs, path.join(dir, await markName(base, backend))), why: null });
  const source = new Uint8Array(fs.readFileSync(new URL("./warrant.mjs", import.meta.url)));
  let watched = null;
  try { if (opt("--watches") !== undefined) watched = watchesFile(fs.readFileSync(opt("--watches"), "utf8")); }
  catch (e) { process.stdout.write(canonStr({ refused: String(e?.message ?? e) }) + "\n"); return 2; }
  const got = await readDesk(plan.stores, { backend, source, marks, actor, watches: watched });
  const releases = await readReleases(releasesOf(plan, fs.readFileSync(listFile, "utf8")));
  process.stdout.write(canonStr({ desk: { from: plan.from, why: plan.why, actor: actor || null, stores: got.map((g) => g.block),
                                          ...(releases.length ? { releases } : {}) } }) + "\n");    // a list with none: as before
  const write = new Set(argv.includes("--write-marks") ? got.map((g) => g.block.base) : all("--write-mark").map((x) => address(x).base));
  if (write.size && dir === undefined) { process.stderr.write("--write-mark needs --marks DIR\n"); return 2; }
  for (const g of got) {
    const watch = watched ? watched(g.block.base) : null;
    if (g.r && write.has(g.block.base)) fs.writeFileSync(path.join(dir, await markName(g.block.base, backend)), JSON.stringify(await reader.makeMark(g.r, g.block.base, backend, undefined, { watch: watch ?? [] })) + "\n");
  }
  return 0;
}

if (typeof process !== "undefined" && process.argv && import.meta.url === (await import("node:url")).pathToFileURL(process.argv[1] || "").href) {
  process.exitCode = await main(process.argv.slice(2));
}

