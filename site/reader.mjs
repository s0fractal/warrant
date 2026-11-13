// The reader in a browser: a store fetched from any HTTP(S) root and assessed here, on the reader's device, by the
// second implementation (warrant.mjs, held byte for byte to the Python engine by tests/impl_js_test.py). No server of
// ours takes part: the page is static, the transport is not trusted (a blob that does not hash to its name refuses the
// read; an altered record line fails its signature and is rejected), and the verdicts are computed under the rules
// the reader names: the publisher's own `.warrant/v3.json`, or a trust and profile the reader pastes.
//
// This file has no DOM in it: it fetches, assesses and builds plain data (the view), so node can run the same
// functions the page runs (tests/impl_js_test.py J10). reader-page.mjs draws that data, as text only.
//
//   node site/reader.mjs --base URL [--full] [--pins] [--with URL]... [--config RULES.json] [--lineage ID]   # canonical JSON
//
// Two ways to read a store's blobs:
//   quick (the default)   only the blobs the assessment itself reads: the map of each migration (docs/V3.md §9).
//                         Every state and reliance is the full store's; the snapshot digest is NOT the store's root,
//                         because the root covers every blob, and the view says so (`root: null`).
//   full                  every blob a record names, each checked against its name: the digest is the store's root,
//                         the one `warrant status` prints for the same bytes.
//
// What a browser cannot say: whether an acceptance still names the bytes of a checkout (STALE, docs/V3.md §15) needs
// the repository's Git objects. So this reader never prints ELIGIBLE for a lineage whose acceptances name files or a
// commit: it prints PINS_NOT_CHECKED, the word `warrant verify` uses for a comparison that was not made. A note beside
// a green word is not enough: `warrant status` once said ELIGIBLE where the gate said STALE.
//
// Unless it is asked to compare (`--pins`, comparePins): the address of a repository's store is the root of a tree
// too, so each file a claims checker's acceptance names, {path: git blob}, can be fetched at that path and hashed as
// Git hashes a blob. The freshness gate's rule (warrant/drift.py drift, gate) then decides each claim it covers:
// ELIGIBLE when one acceptance's every file holds its bytes, STALE when none does, and PINS_NOT_CHECKED when a file
// that could decide it was not fetched. What the gate reads and HTTP does not, the reader does not guess: a file moved
// with its bytes (the gate lists the whole tree) and a symlink's entry read STALE here, where the gate says ELIGIBLE.
//
// Other stores (`--with URL`, readOthers): each assessed alone under its own rules; what they hold about this store's
// versions is shown as voices from outside, never counted here; with the reader's own rules, the overlay (overlay()).
import { assessPrepared, canon, canonStr, codeIdentity, hex64, loadsLenient, prepare, Refused, utf16 } from "./warrant.mjs";


export const MIGRATION = "migration@1";
export const TITLE_MEMBERS = ["statement", "title", "text", "name", "what"];   // the first a body has, as its one-line name

function split(raw) {
  const lines = [];
  let start = 0;
  for (let i = 0; i <= raw.length; i++) {
    if (i === raw.length || raw[i] === 0x0a) {
      if (i > start) { const l = new Uint8Array(i - start + 1); l.set(raw.subarray(start, i)); l[i - start] = 0x0a; lines.push(l); }
      start = i + 1;
    }
  }
  return lines;
}

// A missing file is an answer (null); anything else that is not the bytes is a refusal, never read as "missing":
// a transport that failed says nothing about what the store holds.
async function get(url, fetcher) {
  let r;
  try { r = await fetcher(url); } catch (e) { throw new Refused(`${url}: not fetched (${e?.message ?? e})`); }
  if (r.status === 404) return null;
  if (!r.ok) throw new Refused(`${url}: HTTP ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}

async function named(lines, backend) {
  // {every 64-hex value a record carries in its refs or body that is no record's id here, the targets of migration
  // attests}: a record's id names a record, never a blob, so it is not asked for (half of what a full read would fetch)
  const all = new Set(), maps = new Set(), records = [];
  const walk = (v) => {
    if (typeof v === "string") { if (hex64(v)) all.add(v); }
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") Object.values(v).forEach(walk);
  };
  const dec = new TextDecoder();
  for (const l of lines) {
    try {
      const r = JSON.parse(dec.decode(l)).record;
      records.push(r);
      walk(r.refs);
      walk(r.body);
      if (r.kind === "attest" && r.schema === MIGRATION && hex64(r.body.target)) maps.add(r.body.target);
    } catch { /* an unreadable line is the assessment's to reject */ }
  }
  const idOf = async (r) => { try { return await backend.sha256(canon(r)); } catch { return null; } };   // not canonical: the assessment rejects it
  for (const id of await Promise.all(records.map(idOf))) all.delete(id);
  return { all, maps };
}

// {lines, blobs, doc, missing, mode, asked}: the store at `base`, its blobs by `mode` ("quick" | "full").
export async function fetchStore(base, backend, { full = false, fetcher = globalThis.fetch } = {}) {
  const root = base.endsWith("/") ? base : base + "/";
  const config = await get(root + ".warrant/v3.json", fetcher);
  if (config === null) throw new Refused(`${root}: no .warrant/v3.json`);
  let doc;
  try { doc = loadsLenient(new TextDecoder().decode(config)); } catch { throw new Refused(`${root}.warrant/v3.json: not JSON`); }
  const lines = split((await get(root + ".warrant/records.jsonl", fetcher)) || new Uint8Array());
  const { all, maps } = await named(lines, backend);
  const wanted = [...(full ? all : maps)].sort(utf16), got = new Array(wanted.length);
  let next = 0;
  const worker = async () => {             // 16 requests at a time; the results are put back in order
    while (next < wanted.length) { const k = next++; got[k] = await get(root + ".warrant/blobs/" + wanted[k], fetcher); } // NOSONAR S9382: one request after another within a worker, 16 workers at once
  };
  await Promise.all(Array.from({ length: 16 }, worker));
  const hashes = await Promise.all(got.map((b) => (b === null ? null : backend.sha256(b))));
  const blobs = new Map(), missing = [];
  for (let k = 0; k < wanted.length; k++) {
    if (got[k] === null) { missing.push(wanted[k]); continue; }
    if (hashes[k] !== wanted[k]) throw new Refused(`the transport altered blob ${wanted[k]}: its bytes do not hash to its name`);
    blobs.set(wanted[k], got[k]);
  }
  return { lines, blobs, doc, missing, mode: full ? "full" : "quick", asked: wanted.length };
}

// The receiver's rules: the reader's own {trust, profile} when given, else the publisher's own (its v3.json).
export function receiver(doc, mine) {
  const of = (d) => (d && typeof d === "object" && d.trust && d.profile ? { trust: d.trust, profile: d.profile } : null);
  const own = of(mine);
  if (own) return { ...own, whose: "reader" };
  const pub = of(doc);
  if (!pub) throw new Refused("the store's .warrant/v3.json holds no {trust, profile}, and the reader gave none");
  return { ...pub, whose: "publisher" };
}

// {rep, recs, store, whose}: `store` as fetchStore gave it, assessed under `rules` (receiver()).
export async function read(store, rules, backend, source) {
  const code = await codeIdentity(source, backend);
  const prep = await prepare({ lines: store.lines, blobs: store.blobs, trust: rules.trust, profile: rules.profile, as_of: null, code }, backend);
  const rep = assessPrepared(prep);
  const recs = new Map();
  for (const [id, envs] of prep.snap.lines) recs.set(id, envs[0].record);
  return { rep, recs, store, whose: rules.whose, rules: { trust: rules.trust, profile: rules.profile } };
}

export const PINS_NOT_CHECKED = "PINS_NOT_CHECKED";

// Whether some attest on a lineage's effective version speaks of bytes at a commit (`files`, `commit`), whoever
// filed it and whether or not the guard counted it: the freshness gate (warrant.drift) reads every acceptance the
// claims checker signed on that version, so this must not read fewer.
const speaksOfBytes = (rec) => rec.kind === "attest" && ("files" in rec.body || "commit" in rec.body);

export function pinned(r, root) {
  const eff = r.rep.lineages[root].effective;
  if (!eff) return false;
  for (const rec of r.recs.values()) if (speaksOfBytes(rec) && rec.body.target === eff) return true;
  return false;
}

// The reliance this reader shows: the engine's, but never ELIGIBLE on pins it did not compare. A claim the
// comparison decided (comparePins) reads as the gate reads it, and the gate only ever lowers ELIGIBLE (drift.gate).
export function shown(r, root, pins) {
  const lin = r.rep.lineages[root];
  if (lin.reliance !== "ELIGIBLE") return lin.reliance;
  const c = r.compared?.lineages.get(root);
  if (c) return c.verdict === "UNCHANGED" ? "ELIGIBLE" : c.verdict === STALE ? STALE : PINS_NOT_CHECKED;
  return (pins ?? pinned(r, root)) ? PINS_NOT_CHECKED : lin.reliance;
}

// ---------------------------------------------------------------- pins: the gate's comparison over HTTP (opt-in)

export const STALE = "STALE";                             // warrant/drift.py STALE
export const CHECKER = "claims-checker";                  // warrant/claims.py CHECKER: the actor, a name in every store
export const CLOSURE = "imports/1";                       // warrant/claims.py CLOSURE: files named as the import closure
export const CLAIM = "claim@1";                           // warrant/claims.py CLAIM
const SHA1 = /^[0-9a-f]{40}$/;                            // a blob id of a SHA-1 repository, as `git ls-tree` spells it

// warrant/claims.py acceptances: [{id, commit, files, closure}] by version of the claims checker's SIGNED attests whose
// verdict is accept, in id order. The basis is the view's (graph nodes): a line whose signature fails is in `recs`
// (every line read) but not in the view.
function acceptances(r) {
  const basis = new Map(r.rep.graph.nodes.map((n) => [n[0], n[5]]));
  const out = new Map();
  for (const [id, rec] of [...r.recs].sort((a, b) => utf16(a[0], b[0]))) {
    if (rec.kind === "attest" && rec.actor === CHECKER && basis.get(id) === "SIGNED" && rec.body.verdict === "accept") {
      if (!out.has(rec.body.target)) out.set(rec.body.target, []);
      out.get(rec.body.target).push({ id, commit: rec.body.commit ?? null, files: rec.body.files, closure: rec.body.closure });
    }
  }
  return out;
}

// warrant/claims.py live and drift: {root: effective version} of each claim@1 lineage whose leaf is not retired (a fork,
// no leaf, is live) and whose effective version the claims checker accepted: the lineages the gate covers.
function covered(r, done) {
  const out = new Map();
  for (const [root, lin] of Object.entries(r.rep.lineages)) {
    if (lin.schema !== CLAIM || (lin.leaf ? r.recs.get(lin.leaf).body.state : null) === "retired") continue;
    if (lin.effective && done.get(lin.effective)?.length) out.set(root, lin.effective);
  }
  return out;
}

// warrant/pins.py unreadable: why `files` cannot be compared with any tree, or null (Python's `not files`: none, {}, …).
function unreadable(files) {
  const obj = files !== null && typeof files === "object" && !Array.isArray(files);
  if (!files || (obj && Object.keys(files).length === 0) || (Array.isArray(files) && files.length === 0)) return "the acceptance names no files";
  if (!(obj && Object.values(files).every((b) => typeof b === "string"))) return "the acceptance's files are not {path: blob}";
  return null;
}

// The URL of a tree path under `root`, or null for a string no Git tree holds as a path (empty, `.`, `..` or `.git`
// segments, NUL, a lone surrogate): such a path is never UNCHANGED in the gate, and it must not reach the server.
function treeUrl(root, path) {
  if (typeof path !== "string" || path.includes("\0")) return null;
  const segs = path.split("/");
  if (segs.some((s) => s === "" || s === "." || s === ".." || s.toLowerCase() === ".git")) return null;
  try { return root + segs.map(encodeURIComponent).join("/"); } catch { return null; }
}

// Git's blob id of `bytes`: SHA-1 of "blob <length>\0" and the bytes.
async function blobId(bytes, digest) {
  const head = new TextEncoder().encode(`blob ${bytes.length}\0`), all = new Uint8Array(head.length + bytes.length);
  all.set(head);
  all.set(bytes, head.length);
  return [...new Uint8Array(await digest(all))].map((x) => x.toString(16).padStart(2, "0")).join("");
}

// One file of an acceptance against what the address served at its path ({id} | {absent} | {refused}, or undefined
// when it was not asked for), in the words of warrant/pins.py where the reader can say them:
//   UNCHANGED     the bytes at the path hash to the blob;           CHANGED   other bytes at the path;
//   ABSENT        404 at the path: the gate's GONE, or its MOVED (fresh) when the bytes are at another path, which a
//                 reader that cannot list the tree does not see: not fresh here;
//   LINK          a symlink's entry (`link:<blob>`): over HTTP a link reads as its target's name or its target's bytes,
//                 never as a link: not fresh here, whatever the gate reads;
//   UNCOMPARABLE  a path no tree holds, or a blob that is no SHA-1 id: never UNCHANGED in the gate;
//   NOT_FETCHED   the transport failed: no answer, neither fresh nor stale.
function row(path, blob, got) {
  if (blob.startsWith("link:")) return [path, "LINK", "a symlink's entry: HTTP serves no link as a link"];
  if (!SHA1.test(blob) || got === undefined) return [path, "UNCOMPARABLE", "no tree holds this path, or the blob is no SHA-1 id"];
  if (got.refused) return [path, "NOT_FETCHED", got.refused];
  if (got.absent) return [path, "ABSENT", "not served at this path (moved or gone: the tree is not listed)"];
  return got.id === blob ? [path, "UNCHANGED", ""] : [path, "CHANGED", "other bytes at this path"];
}

// One acceptance's verdict from its rows (warrant/pins.py verdict): UNCHANGED when every file is, NOT_COMPARED when no
// file is known not to be and one was not fetched, else STALE.
function judged(rows) {
  if (rows.every((x) => x[1] === "UNCHANGED")) return "UNCHANGED";
  return rows.every((x) => x[1] === "UNCHANGED" || x[1] === "NOT_FETCHED") ? "NOT_COMPARED" : STALE;
}

// Compare the pins of every claim the gate covers with the tree at `base`, the store's own address: sets r.compared.
// Each distinct path is fetched once, 16 at a time. A transport that fails refuses no read here and answers nothing:
// the claims it could decide read PINS_NOT_CHECKED and the failure is named (summary().pins.refused). Without
// `.warrant/claims.json` at the address the gate has nothing to cover (drift: no drift answer); a failure to fetch it
// compares nothing.
export async function comparePins(r, base, { fetcher = globalThis.fetch, digest = (b) => globalThis.crypto.subtle.digest("SHA-1", b) } = {}) {
  const root = base.endsWith("/") ? base : base + "/";
  const out = { config: "present", lineages: new Map(), asked: 0, fetched: 0, absent: 0, compared: 0, refused: [] };
  r.compared = out;
  try { if ((await get(root + ".warrant/claims.json", fetcher)) === null) out.config = "absent"; }
  catch (e) { out.config = "refused"; out.refused.push(e.message); }
  if (out.config !== "present") return r;
  const done = acceptances(r), gate = covered(r, done), urls = new Map();
  for (const eff of gate.values()) {
    for (const a of done.get(eff)) {
      if (a.closure !== CLOSURE || unreadable(a.files)) continue;
      for (const [p, b] of Object.entries(a.files)) {
        const u = treeUrl(root, p);
        if (u !== null && SHA1.test(b)) urls.set(p, u);
      }
    }
  }
  const paths = [...urls.keys()].sort(utf16), got = new Map();
  let next = 0;
  const worker = async () => {             // 16 requests at a time, as fetchStore asks for blobs
    while (next < paths.length) { // NOSONAR S9382: one request after another within a worker, 16 workers at once
      const p = paths[next++];
      try {
        const bytes = await get(urls.get(p), fetcher);
        got.set(p, bytes === null ? { absent: true } : { id: await blobId(bytes, digest) });
      } catch (e) { got.set(p, { refused: e.message }); }
    }
  };
  await Promise.all(Array.from({ length: 16 }, worker));
  out.asked = paths.length;
  for (const g of got.values()) { if (g.id) out.fetched++; else if (g.absent) out.absent++; else out.refused.push(g.refused); }
  for (const [lroot, eff] of gate) {
    const seen = done.get(eff).map((a) => {
      const why = a.closure === CLOSURE ? unreadable(a.files)
        : "the acceptance names its test and mutated files, not the import closure they ran";
      const rows = why ? [["", "UNKNOWN", why]] : Object.keys(a.files).sort(utf16).map((p) => row(p, a.files[p], got.get(p)));
      out.compared += rows.filter((x) => x[1] === "UNCHANGED" || x[1] === "CHANGED").length;
      return { attest: a.id, commit: a.commit, verdict: judged(rows), files: rows.map(([path, verdict, detail]) => ({ path, verdict, detail })) };
    });
    // drift: fresh when ANY acceptance is; else not compared when one could still be; else stale
    const verdict = seen.some((s) => s.verdict === "UNCHANGED") ? "UNCHANGED" : seen.some((s) => s.verdict === "NOT_COMPARED") ? "NOT_COMPARED" : STALE;
    out.lineages.set(lroot, { verdict, acceptances: seen });
  }
  out.refused.sort(utf16);
  return r;
}

// ---------------------------------------------------------------- other stores: voices from outside, and "for me"
//
// The reader may name further stores. Each is read as the main one is (fetchStore, quick) and assessed ALONE under its
// own .warrant/v3.json: its verdicts are its own. A store that cannot be read is named with its reason; the others
// still answer (warrant.across). What they hold about the main store's lineages is shown as voices from outside, which
// the main store's rules do not count (warrant_agent/observe.py elsewhere). Only a reader who gave its own rules gets
// an overlay: the union of every store read, under the reader's rules (warrant_agent/overlay.py), beside each store's
// verdict, never in its place.

// [{address, name, r, why}] of the stores at `addresses`, each read and assessed under its own rules; `r` null and
// `why` the reason for one that could not be (a refusal, a v3.json with no rules, anything the engine throws on it).
export async function readOthers(addresses, backend, source, { fetcher = globalThis.fetch } = {}) {
  return Promise.all([...new Set(addresses)].map(async (address) => {
    try {
      const store = await fetchStore(address, backend, { fetcher });
      const r = await read(store, receiver(store.doc, null), backend, source);
      return { address, name: typeof store.doc.repository === "string" ? store.doc.repository : address, r, why: null };
    } catch (e) {
      return { address, name: address, r: null, why: String(e?.message ?? e) };
    }
  }));
}

// {version: [voice]} and {version: n left out} of what the other stores hold about versions of the main store: their
// attests and challenges whose body.target is such a version. A voice is a record its own store's assessment admits
// (in its view: its graph's nodes); a line that store rejects is no voice and is counted apart. A record the main store
// holds too is the main store's, not a voice. Built once per read.
function outside(r) {
  if (r._outside) return r._outside;
  const versions = new Set();
  for (const lin of Object.values(r.rep.lineages)) for (const v of lin.versions) versions.add(v);
  const voices = new Map(), left = new Map();
  for (const o of r.others ?? []) {
    if (!o.r) continue;
    const admitted = new Set(o.r.rep.graph.nodes.map((n) => n[0]));
    for (const [id, rec] of [...o.r.recs].sort((a, b) => utf16(a[0], b[0]))) {
      const t = rec.body?.target;
      if (!((rec.kind === "attest" || rec.kind === "challenge") && typeof t === "string" && versions.has(t)) || r.recs.has(id)) continue;
      if (!admitted.has(id)) { left.set(t, (left.get(t) || 0) + 1); continue; }
      if (!voices.has(t)) voices.set(t, []);
      voices.get(t).push({ id, store: o.name, address: o.address, kind: rec.kind, actor: rec.actor, at: rec.at, target: t,
                           verdict: typeof rec.body.verdict === "string" ? rec.body.verdict : null, statement: title(rec), counted: false });
    }
  }
  r._outside = { voices, left };
  return r._outside;
}

// {voices, stores, left_out} of a lineage: what other stores hold about its versions, none of it counted here.
function outsideOf(r, root) {
  const { voices, left } = outside(r), lin = r.rep.lineages[root];
  const vs = lin.versions.flatMap((v) => voices.get(v) || []).sort((a, b) => a.at - b.at || utf16(a.id, b.id));
  return { voices: vs, stores: new Set(vs.map((x) => x.address)).size, left_out: lin.versions.reduce((n, v) => n + (left.get(v) || 0), 0) };
}

// warrant_agent/overlay.py receiver: (trust, profile, held) of the reader composing `sources` ({store: trust}). The
// reader's own bindings; then each binding every source naming that actor agrees on, unless the reader's own profile
// gives that actor a role (Codex 2026-11-12, #348: a role holder's key comes from the reader's trust alone); held:
// [[actor, {store: keys}, "role" | "disagree"]] of the bindings not admitted.
export function overlayReceiver(readerTrust, readerProfile, sources) {
  const keys = new Map(Object.entries(readerTrust.keys).map(([a, k]) => [a, [...k].sort(utf16)]));
  const holders = new Set(Object.values(readerProfile.roles).flat());
  const named = new Map();
  for (const store of Object.keys(sources).sort(utf16)) {
    for (const [actor, k] of Object.entries(sources[store].keys)) {
      if (!named.has(actor)) named.set(actor, {});
      named.get(actor)[store] = [...k].sort(utf16);
    }
  }
  const held = [];
  for (const actor of [...named.keys()].sort(utf16)) {
    if (keys.has(actor)) continue;
    const by = named.get(actor), distinct = new Set(Object.values(by).map((k) => JSON.stringify(k)));
    if (holders.has(actor)) held.push([actor, by, "role"]);
    else if (distinct.size === 1) keys.set(actor, JSON.parse([...distinct][0]));
    else held.push([actor, by, "disagree"]);
  }
  const trust = { ...readerTrust, keys: Object.fromEntries([...keys].sort((a, b) => utf16(a[0], b[0]))) };
  return { trust, profile: readerProfile, held };
}

const bytesCmp = (a, b) => {
  for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] !== b[i]) return a[i] - b[i];
  return a.length - b.length;
};

// warrant_agent/overlay.py compose: every line of the stores once, in byte order, and all their blobs (each read
// checked its blobs against their names).
function compose(stores) {
  const seen = new Map(), key = new TextDecoder("latin1");       // windows-1252 decoding: one code point per byte, injective
  for (const s of stores) for (const l of s.lines) seen.set(key.decode(l), l);
  const blobs = new Map();
  for (const s of stores) for (const [h, b] of s.blobs) blobs.set(h, b);
  return { lines: [...seen.values()].sort(bytesCmp), blobs };
}

const docId = (v, backend) => backend.sha256(canon(v));

// The overlay (`r.overlay`): with the reader's own rules, the union of the main store (at `address`) and every other
// store read, assessed under the reader's rules, beside the main store's own verdict under its own rules. Each lineage
// of the main store whose state or reliance reads otherwise for the reader is a row: the store's (state, reliance) →
// the reader's, the challenges that stand for the reader and not in the store, and the actors who accept a version for
// the reader and not in the store. The reliance words are the engine's; `shown` applies this reader's rule to both
// sides: ELIGIBLE on pins nobody compared reads PINS_NOT_CHECKED (the overlay compares no pins).
export async function overlay(r, address, backend, source) {
  const done = (o) => { r.overlay = o; return r; };
  if (r.whose !== "reader") return done({ why: "no rules of the reader's own were given: there is nobody to read it for" });
  let own;
  try { own = await read(r.store, receiver(r.store.doc, null), backend, source); }
  catch (e) { return done({ why: `the store's own verdict cannot be read: ${e?.message ?? e}` }); }
  const readable = (r.others ?? []).filter((o) => o.r);
  const stores = [{ name: address, store: r.store, ids: [...r.recs.keys()] },
                  ...readable.map((o) => ({ name: o.address, store: o.r.store, ids: [...o.r.recs.keys()] }))];
  const sources = Object.fromEntries(stores.map((s) => [s.name, (s.name === address ? own : readable.find((o) => o.address === s.name).r).rules.trust]));
  const { trust, profile, held } = overlayReceiver(r.rules.trust, r.rules.profile, sources);
  const { lines, blobs } = compose(stores.map((s) => s.store));
  const over = await read({ lines, blobs, doc: r.store.doc }, { trust, profile, whose: "reader" }, backend, source);
  const ids = {};
  for (const s of [...stores].sort((a, b) => utf16(a.name, b.name))) ids[s.name] = await docId([...new Set(s.ids)].sort(utf16), backend);
  const identity = await docId({ stores: ids, trust: await docId(trust, backend), profile: await docId(profile, backend), code: over.rep.code }, backend);
  const out = [];
  for (const [L, a] of Object.entries(own.rep.lineages).sort((x, y) => utf16(x[0], y[0]))) {
    const b = over.rep.lineages[L];
    if (b && a.state === b.state && a.reliance === b.reliance) continue;
    const stands = (rep) => new Set(Object.entries(rep.challenges).filter(([, c]) => c.counted && c.stands && a.versions.includes(c.target)).map(([i]) => i));
    const before = stands(own.rep);
    const accepts = (rep, v) => new Set(rep.versions[v]?.accepted_by ?? []);
    out.push({ lineage: L, schema: a.schema,
               store: { state: a.state, reliance: a.reliance, shown: shown(own, L) },
               reader: b ? { state: b.state, reliance: b.reliance, shown: shown(over, L) } : null,
               challenges: [...stands(over.rep)].filter((i) => !before.has(i)).sort(utf16),
               accepted_by: b ? [...new Set(b.versions.flatMap((v) => [...accepts(over.rep, v)].filter((x) => !accepts(own.rep, v).has(x))))].sort(utf16) : [] });
  }
  return done({ why: null, identity, code: over.rep.code, stores: stores.map((s) => s.name), unread: (r.others ?? []).filter((o) => !o.r).map((o) => o.address),
                held, rows: out, rejected: Object.keys(over.rep.rejected).length });
}

function pinsIndex(r) {                                   // {root: true} of every pinned lineage, in one pass over the records
  const { rep, recs } = r;
  const eff = new Map();
  for (const [root, lin] of Object.entries(rep.lineages)) if (lin.effective) eff.set(lin.effective, root);
  const out = new Set();
  for (const rec of recs.values()) {
    const root = speaksOfBytes(rec) ? eff.get(rec.body.target) : undefined;
    if (root !== undefined) out.add(root);
  }
  return out;
}

const count = (into, key) => { into[key] = (into[key] || 0) + 1; };
const sorted = (o) => Object.fromEntries(Object.keys(o).sort(utf16).map((k) => [k, o[k]]));

// The facts `warrant status --json` gives for the same bytes and rules (warrant/cli.py status), and what this reader
// adds about itself: whose rules, which blobs it fetched, what it cannot see.
export function summary(r) {
  const { rep, store } = r;
  const lineages = {}, reliance = {}, pins = pinsIndex(r);
  for (const [root, lin] of Object.entries(rep.lineages)) {
    count(lineages[lin.schema] || (lineages[lin.schema] = {}), lin.state || "none");
    count(reliance, shown(r, root, pins.has(root)));
  }
  return {
    repository: typeof store.doc.repository === "string" ? store.doc.repository : null,
    root: store.mode === "full" ? rep.snapshot : null,          // the store's root only when every named blob was read
    assessment: rep.assessment, code: rep.code, as_of: rep.as_of, rules: r.whose,
    records: r.recs.size, signed: rep.basis.SIGNED, migrated: rep.basis.MIGRATED,
    rejected: Object.keys(rep.rejected).length, canonical: rep.canonical, completeness: rep.completeness,
    blobs: { mode: store.mode, asked: store.asked, read: store.blobs.size, missing: store.missing.length },
    chain_forks: [...new Set(rep.chains.forks.map((f) => f[0]))].sort(utf16),
    schemas: Object.keys(rep.schemas).sort(utf16), schemas_pending: Object.keys(rep.schemas_pending).sort(utf16),
    problems: rep.problems,
    lineages: sorted(Object.fromEntries(Object.entries(lineages).map(([k, v]) => [k, sorted(v)]))),
    reliance: sorted(reliance),
    not_checked: r.compared ? NOT_CHECKED_COMPARED : ["pins: whether an acceptance still names a checkout's bytes (STALE) needs Git objects; such a lineage reads PINS_NOT_CHECKED here, never ELIGIBLE"],
    ...(r.compared ? { pins: pinsSummary(r.compared) } : {}),       // only when asked: without it the summary is as it was
    ...(r.others ? { others: othersSummary(r) } : {}),
    ...(r.overlay ? { overlay: overlaySummary(r.overlay) } : {}),
  };
}

const NOT_CHECKED_COMPARED = [
  "pins: compared with the tree this address serves, not with a checkout's HEAD; PINS_NOT_CHECKED where a file was not fetched, or the lineage is no claim the freshness gate covers",
  "moved files and symlinks: a file moved with its bytes, or a symlink's entry, reads STALE here where the gate reads it fresh (HTTP lists no tree and serves no link as a link)",
];

// The other stores read: each named with its own reading or its reason, and the voices they hold about this store's
// lineages, none counted by this store's rules.
function othersSummary(r) {
  const { voices, left } = outside(r);
  const n = [...voices.values()].reduce((k, xs) => k + xs.length, 0);
  return { stores: r.others.map((o) => ({ address: o.address, name: o.name, read: o.r !== null, why: o.why,
                                           records: o.r ? o.r.recs.size : null, rules: o.r ? "its own" : null })),
           voices: n, counted: 0, left_out: [...left.values()].reduce((k, x) => k + x, 0),
           lineages: Object.keys(r.rep.lineages).filter((L) => outsideOf(r, L).voices.length).length };
}

function overlaySummary(o) {
  if (o.why) return { why: o.why };
  return { identity: o.identity, code: o.code, stores: o.stores, unread: o.unread, rejected: o.rejected, changed: o.rows.length, rows: o.rows,
           held: o.held.map(([actor, by, why]) => ({ actor, stores: Object.keys(by).sort(utf16), why })),
           pins: "the overlay compares no pins: ELIGIBLE on pins nobody compared reads PINS_NOT_CHECKED on both sides" };
}

function pinsSummary(c) {
  const by = {};
  for (const x of c.lineages.values()) count(by, x.verdict);
  return { config: c.config, claims: c.lineages.size, verdicts: sorted(by),
           files: { asked: c.asked, fetched: c.fetched, absent: c.absent, refused: c.asked - c.fetched - c.absent }, compared: c.compared,
           refused: c.refused };
}

// A record's one-line name: the first of TITLE_MEMBERS its body has as a string, as data (never markup).
export function title(record) {
  if (typeof record?.body !== "object" || record.body === null) return "";
  for (const k of TITLE_MEMBERS) if (typeof record.body[k] === "string" && record.body[k] !== "") return record.body[k];
  return "";
}

// One row per lineage, newest effective or leaf version first: what a list shows before a lineage is opened.
export function rows(r) {
  const { rep, recs } = r;
  const out = [], pins = pinsIndex(r);
  for (const [root, lin] of Object.entries(rep.lineages)) {
    const rec = recs.get(lin.effective || lin.leaf || root);
    const standing = lin.versions.reduce((n, v) => n + rep.versions[v].challenged_by.length, 0);
    out.push({ id: root, schema: lin.schema, state: lin.state, reliance: shown(r, root, pins.has(root)), actor: lin.actor,
               at: rec ? rec.at : null, versions: lin.versions.length, standing, title: title(rec) || title(recs.get(root)),
               ...(r.others ? { outside: outsideOf(r, root).voices.length } : {}) });
  }
  return out.sort((a, b) => (b.at ?? 0) - (a.at ?? 0) || utf16(a.id, b.id));
}

// One lineage, opened: the floor no lens decides (state, reliance, every counted challenge that stands, completeness),
// then its versions newest first with their guards, the attests on each and the challenges against each.
export function lineage(r, root) {
  const { rep, recs } = r;
  const lin = rep.lineages[root];
  if (!lin) return null;
  const on = new Map();                                   // version -> the attests and challenges that target it
  for (const [id, rec] of recs) {
    if ((rec.kind === "attest" || rec.kind === "challenge") && lin.versions.includes(rec.body.target)) {
      if (!on.has(rec.body.target)) on.set(rec.body.target, []);
      on.get(rec.body.target).push(id);
    }
  }
  const versions = [...lin.versions].reverse().map((v) => {
    const rec = recs.get(v), g = rep.versions[v];
    const said = (on.get(v) || []).sort((a, b) => recs.get(a).at - recs.get(b).at || utf16(a, b)).map((id) => {
      const x = recs.get(id), c = rep.challenges[id];
      return { id, kind: x.kind, actor: x.actor, at: x.at, verdict: typeof x.body.verdict === "string" ? x.body.verdict : null,
               statement: title(x), counted: c ? c.counted : null, stands: c ? c.stands : null, why: c ? c.why : null };
    });
    return { id: v, actor: rec.actor, at: rec.at, state: typeof rec.body.state === "string" ? rec.body.state : null,
             effective: lin.effective === v, leaf: lin.leaf === v, title: title(rec),
             guard: g.guard, waiting: g.waiting, accepted_by: g.accepted_by, said };
  });
  const standing = versions.flatMap((v) => v.said.filter((s) => s.kind === "challenge" && s.stands));
  return { floor: { id: root, schema: lin.schema, state: lin.state, reliance: shown(r, root), verdict: lin.verdict,
                    forks: lin.forks.length, standing, completeness: rep.completeness, rules: r.whose,
                    ...(r.compared ? { pins: r.compared.lineages.get(root) ?? null } : {}),     // each acceptance's comparison
                    ...(r.others ? { outside: outsideOf(r, root) } : {}),                       // never counted here
                    ...(r.overlay ? { overlay: r.overlay.why ? { why: r.overlay.why }
                      : (r.overlay.rows.find((x) => x.lineage === root) ?? { lineage: root, same: true }) } : {}) },
           versions };
}

async function main(argv) {
  const fs = await import("node:fs");
  const { nodeBackend } = await import("./warrant.mjs");
  const backend = await nodeBackend();
  const opt = (name) => { const k = argv.indexOf(name); return k >= 0 ? argv[k + 1] : undefined; };
  const base = opt("--base");
  if (!base) { process.stderr.write("usage: reader.mjs --base URL [--full] [--pins] [--with URL]... [--config RULES.json] [--lineage ID]\n"); return 2; }
  const others = argv.flatMap((a, k) => (a === "--with" && k + 1 < argv.length ? [argv[k + 1]] : []));
  try {
    const store = await fetchStore(base, backend, { full: argv.includes("--full") });
    const source = new Uint8Array(fs.readFileSync(new URL("./warrant.mjs", import.meta.url)));
    const mine = opt("--config") ? loadsLenient(fs.readFileSync(opt("--config"), "utf8")) : null;
    const r = await read(store, receiver(store.doc, mine), backend, source);
    if (argv.includes("--pins")) await comparePins(r, base);
    if (others.length) {
      r.others = await readOthers(others, backend, source);
      await overlay(r, base, backend, source);
    }
    const out = opt("--lineage") ? { lineage: lineage(r, opt("--lineage")) } : { summary: summary(r), rows: rows(r) };
    process.stdout.write(canonStr(out) + "\n");
  } catch (e) {
    if (e instanceof Refused) { process.stdout.write(canonStr({ refused: e.message }) + "\n"); return 2; }
    throw e;
  }
  return 0;
}

if (typeof process !== "undefined" && process.argv && import.meta.url === (await import("node:url")).pathToFileURL(process.argv[1] || "").href) {
  process.exitCode = await main(process.argv.slice(2));
}
