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
//        [--mark FILE] [--write-mark FILE]     what changed since the mark in FILE; write the mark of now to FILE
//        [--actor NAME]                        what waits for NAME (frontier(): warrant.graph.frontier)
//        [--watch ID[,ID…]]...                 the answer for the lineages watched (watched()): exit 0 silent, 3 touched,
//                                              4 not established; with --write-mark, the mark records their floors
//        [--frame ID[,ID…]]                    the frame of those lineages (frame())
//        [--toward-exit]                       with --watch: exit 5 when silent with a lineage toward what is watched
//        [--resolve ID[,ID…]]...               where the bytes of each id are (resolved()): PRESENT, RESOLVED, MISSING,
//                                              NOT_FETCHED; completeness UNATTESTED
//
// Two ways to read a store's blobs:
//   quick (the default)   only the blobs the assessment itself reads: the map of each migration (docs/V3.md §9).
//                         Every state and reliance is the full store's; the snapshot digest is NOT the store's root,
//                         because the root covers every blob, and the view says so (`root: null`).
//   full                  every blob a record names, each checked against its name: the digest is the store's root,
//                         the one `warrant status` prints for the same bytes.
//
// What a browser cannot say: whether an acceptance still names the bytes of a checkout (STALE, docs/V3.md §15) needs
// the repository's Git objects. So this reader never prints ELIGIBLE for a lineage the freshness gate covers (a pinned
// acceptance on its effective version, warrant/drift.py pinned: a signed accept naming `files`, whoever signed it, or
// the claims checker's): it prints PINS_NOT_CHECKED, the word `warrant verify` uses for a comparison that was not made.
// A note beside a green word is not enough: `warrant status` once said ELIGIBLE where the gate said STALE.
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
//
// What changed for me (`--mark FILE`, changes()): the lineages whose view differs since the reader marked the store as
// seen (makeMark: the page keeps the mark in localStorage, the CLI in a file), the rest of the new records counted.
// With a watch list (`--watch`, watched()), the same is said of the watched lineages alone: touched with its witness,
// silent with its numbers, or not established with its reasons; and, beside that answer, the lineages that reach the
// watched ones and moved (toward: the cone, for attention, never for the outcome).
//
// Where the bytes of a cited id are (resolved(), `--resolve`): here, in a store read beside, missing, or not fetched.
import { assessPrepared, canon, canonStr, cmp, codeIdentity, hex64, loadsLenient, prepare, Refused, utf16 } from "./warrant.mjs";


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
  return { lines, blobs, doc, missing, mode: full ? "full" : "quick", asked: wanted.length, base: root };
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

// Whether the freshness gate covers a lineage: one predicate with warrant/drift.py (pinned, drift), held by
// impl_js_test J11 against it. Until 3.0.0a7 this read any attest naming `files` or a `commit`, while the gate read the
// claims checker's alone and only beside .warrant/claims.json (the analysis session, 2026-11-13).
export function pinned(r, root) {
  return gated(r).has(root);
}

function gated(r) {                                       // covered(), once per read: the lineages the gate covers
  if (!r._gated) r._gated = covered(r, acceptances(r));
  return r._gated;
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

// warrant/drift.py pinned: [{id, commit, files, closure}] by version of the pinned acceptances, in id order: each
// SIGNED attest whose verdict is accept and that names `files` as a map, whoever signed it (closure CLOSURE: its files
// are what it says it rests on), and the claims checker's even naming none (its own `closure`). The basis is the
// view's (graph nodes): a line whose signature fails is in `recs` (every line read) but not in the view, and a MIGRATED
// one is not SIGNED.
const isMap = (x) => x !== null && typeof x === "object" && !Array.isArray(x);

function acceptances(r) {
  const basis = new Map(r.rep.graph.nodes.map((n) => [n[0], n[5]]));
  const out = new Map();
  for (const [id, rec] of [...r.recs].sort((a, b) => utf16(a[0], b[0]))) {
    if (rec.kind !== "attest" || basis.get(id) !== "SIGNED" || !isMap(rec.body) || rec.body.verdict !== "accept") continue;
    const own = rec.actor === CHECKER;
    if (!own && !isMap(rec.body.files)) continue;
    if (!out.has(rec.body.target)) out.set(rec.body.target, []);
    out.get(rec.body.target).push({ id, commit: rec.body.commit ?? null, files: rec.body.files, closure: own ? rec.body.closure : CLOSURE });
  }
  return out;
}

// warrant/drift.py drift: {root: effective version} of each lineage whose effective version has a pinned acceptance,
// a claim@1 one only when its leaf is not retired (a fork, no leaf, is live): the lineages the gate covers.
function covered(r, done) {
  const out = new Map();
  for (const [root, lin] of Object.entries(r.rep.lineages)) {
    if (lin.schema === CLAIM && (lin.leaf ? r.recs.get(lin.leaf).body.state : null) === "retired") continue;
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
// the claims it could decide read PINS_NOT_CHECKED and the failure is named (summary().pins.refused). No
// configuration is read: the gate covers what the pinned acceptances name, with or without .warrant/claims.json.
export async function comparePins(r, base, { fetcher = globalThis.fetch, digest = (b) => globalThis.crypto.subtle.digest("SHA-1", b) } = {}) {
  const root = base.endsWith("/") ? base : base + "/";
  const out = { lineages: new Map(), asked: 0, fetched: 0, absent: 0, compared: 0, refused: [] };
  r.compared = out;
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

function pinsIndex(r) {                                   // the roots of every lineage the gate covers
  return new Set(gated(r).keys());
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
    cited: citedCounts(r),                                        // resolved(): where the bytes of every cited id are
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
  return { claims: c.lineages.size, verdicts: sorted(by),
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

// {version: [the ids of the attests and challenges whose body.target it is]}, in record order; of `only` versions alone
// when given (one lineage opened), else of every target (every lineage opened at once).
function onIndex(r, only) {
  const keep = only ? new Set(only) : null, on = new Map();
  for (const [id, rec] of r.recs) {
    const t = rec.body?.target;
    if ((rec.kind === "attest" || rec.kind === "challenge") && (keep ? keep.has(t) : typeof t === "string")) {
      if (!on.has(t)) on.set(t, []);
      on.get(t).push(id);
    }
  }
  return on;
}

// One lineage, opened: the floor no lens decides (state, reliance, every counted challenge that stands, completeness),
// then its versions newest first with their guards, the attests on each and the challenges against each.
// `idx` ({on, pins}, viewsOf): the indexes of one pass over the records, for opening every lineage of a store at once.
export function lineage(r, root, idx) {
  const { rep, recs } = r;
  const lin = rep.lineages[root];
  if (!lin) return null;
  const on = idx ? idx.on : onIndex(r, lin.versions);     // version -> the attests and challenges that target it
  const versions = [...lin.versions].reverse().map((v) => {
    const rec = recs.get(v), g = rep.versions[v];
    const said = [...(on.get(v) || [])].sort((a, b) => recs.get(a).at - recs.get(b).at || utf16(a, b)).map((id) => {
      const x = recs.get(id), c = rep.challenges[id];
      return { id, kind: x.kind, actor: x.actor, at: x.at, verdict: typeof x.body.verdict === "string" ? x.body.verdict : null,
               statement: title(x), counted: c ? c.counted : null, stands: c ? c.stands : null, why: c ? c.why : null };
    });
    return { id: v, actor: rec.actor, at: rec.at, state: typeof rec.body.state === "string" ? rec.body.state : null,
             effective: lin.effective === v, leaf: lin.leaf === v, title: title(rec),
             guard: g.guard, waiting: g.waiting, accepted_by: g.accepted_by, said };
  });
  const standing = versions.flatMap((v) => v.said.filter((s) => s.kind === "challenge" && s.stands));
  return { floor: { id: root, schema: lin.schema, state: lin.state, reliance: shown(r, root, idx ? idx.pins.has(root) : undefined), verdict: lin.verdict,
                    forks: lin.forks.length, standing, completeness: rep.completeness, rules: r.whose,
                    ...(r.compared ? { pins: r.compared.lineages.get(root) ?? null } : {}),     // each acceptance's comparison
                    ...(r.others ? { outside: outsideOf(r, root) } : {}),                       // never counted here
                    ...(r.overlay ? { overlay: r.overlay.why ? { why: r.overlay.why }
                      : (r.overlay.rows.find((x) => x.lineage === root) ?? { lineage: root, same: true }) } : {}) },
           versions };
}

// ---------------------------------------------------------------- what changed for me: a mark, and the difference
//
// warrant_agent/changes.py and view.py, for this reader. The past is the set of records the reader had marked as seen,
// assessed again by the same engine under the same rules: records are never removed, so it is reproduced exactly. A
// lineage is listed when its view differs between the past and now (viewOf below: what this reader's lineage view
// shows; this reader has no lenses); new records that change no lineage's view are counted, never listed. Two states
// are the same for the reader exactly when no lineage's view differs (observational equivalence, relative to this
// reader and its rules: under other rules the same records may differ, so a mark belongs to the rules it was read
// under and is not used under others).

export const MARK = "reader-mark/1";
const PREFIX = 8;          // bytes of each marked id kept: which present record a marked one may be
const GROUP = 16;          // marked ids per group digest: what makes "it was marked" exact

// The mark of one store: {n, prefix, group, ids, groups}. A store's ids are 64-hex (32 bytes): kept whole, 100 000 of
// them are 6.4 M characters as hex and 4.3 M as base64, near or past what a browser keeps for one origin (about 5 M
// UTF-16 units). Kept here: the sorted ids' first PREFIX bytes (`ids`, base64), and for each run of GROUP of them in
// that order the SHA-256 of their full 32-byte ids (`groups`, base64): 10 bytes an id, 1.33 M characters for 100 000.
// A present record is SEEN only when its prefix is a marked one AND its whole group is found and hashes to the group's
// digest (unmark): so no new record is ever called seen unless SHA-256 collides, the assumption every record id rests
// on. A group that does not verify (a marked record no longer served, or a new record sharing an 8-byte prefix) is
// not trusted: its present records count as new, more is listed and nothing is hidden (`unverified`, named).
async function markOf(ids, backend) {
  const all = [...new Set(ids)].sort(utf16), pre = new Uint8Array(all.length * PREFIX);
  const dig = new Uint8Array(Math.ceil(all.length / GROUP) * 32);
  for (let k = 0; k < all.length; k++) pre.set(hexBytes(all[k]).subarray(0, PREFIX), k * PREFIX);
  for (let g = 0; g * GROUP < all.length; g++) dig.set(hexBytes(await groupDigest(all.slice(g * GROUP, (g + 1) * GROUP), backend)), g * 32);
  return { n: all.length, prefix: PREFIX, group: GROUP, ids: b64(pre), groups: b64(dig) };
}

const hexBytes = (h) => Uint8Array.from({ length: h.length / 2 }, (_, i) => parseInt(h.slice(2 * i, 2 * i + 2), 16));
const bytesHex = (b) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
function groupDigest(ids, backend) {                     // SHA-256 of the sorted full ids, 32 bytes each, concatenated
  const all = new Uint8Array(ids.length * 32);
  ids.forEach((id, k) => all.set(hexBytes(id), k * 32));
  return backend.sha256(all);
}
function b64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
function unb64(s) {                                       // only the one form b64 writes: atob also takes others
  const t = atob(s), out = Uint8Array.from(t, (c) => c.charCodeAt(0));
  if (b64(out) !== s) throw new Error("not the canonical base64");
  return out;
}

// {seen: the present ids shown to be marked, marked, gone: marked ids no present record has the prefix of (a gone
// record's bytes are not held, so the past never has it: it is counted, its lineage not reproduced),
// unverified: present records whose group did not verify (counted as new)}: `entry` against the `present` ids.
async function unmark(entry, present, backend) {
  const { where, prefixes } = markIndex(entry, unb64(entry.ids));
  const { cand, hit } = candidates(where, present);
  const { seen, doubt } = await verified(cand, entry, unb64(entry.groups), backend);
  return { seen, marked: entry.n, gone: prefixes.filter((p) => !hit.has(p)).length, unverified: [...doubt].filter((i) => !seen.has(i)).length };
}

// {where: {marked prefix: [the groups holding it]}, prefixes: every marked prefix, in the mark's order} of `entry`,
// whose prefixes are `pre` (its decoded `ids`).
function markIndex(entry, pre) {
  const where = new Map(), prefixes = [];
  for (let k = 0; k < entry.n; k++) {
    const p = bytesHex(pre.subarray(k * PREFIX, (k + 1) * PREFIX)), g = Math.floor(k / GROUP);
    prefixes.push(p);
    if (!where.has(p)) where.set(p, []);
    if (!where.get(p).includes(g)) where.get(p).push(g);
  }
  return { where, prefixes };
}

// {cand: {group: the present ids whose prefix it holds}, hit: the marked prefixes a present id has}: which present
// record each group may be, before any digest says it is.
function candidates(where, present) {
  const cand = new Map(), hit = new Set();
  for (const id of present) {
    const gs = where.get(id.slice(0, 2 * PREFIX));
    if (!gs) continue;
    hit.add(id.slice(0, 2 * PREFIX));
    for (const g of gs) { if (!cand.has(g)) cand.set(g, []); cand.get(g).push(id); }
  }
  return { cand, hit };
}

// {seen, doubt}: the candidates of each group found whole and hashing to its digest (`dig`, the decoded `groups`),
// and those of every other group: a group that does not verify calls none of its records seen.
async function verified(cand, entry, dig, backend) {
  const seen = new Set(), doubt = new Set();
  for (const [g, ids] of cand) {
    ids.sort(utf16);
    const size = Math.min(GROUP, entry.n - g * GROUP);
    const ok = ids.length === size && (await groupDigest(ids, backend)) === bytesHex(dig.subarray(g * 32, (g + 1) * 32));
    for (const id of ids) (ok ? seen : doubt).add(id);
  }
  return { seen, doubt };
}

// Why `m` is no mark this reader can read, or null.
function markProblem(m) {
  if (!m || typeof m !== "object" || Array.isArray(m) || m.warrant !== MARK) return `it is no reader mark (${MARK})`;
  if (typeof m.base !== "string" || !hex64(m.rules) || !Number.isInteger(m.at) || !m.stores || typeof m.stores !== "object"
      || Array.isArray(m.stores)) return "it lacks its store, its rules, its time or its stores";
  for (const [address, e] of Object.entries(m.stores)) {
    const bad = `its entry for ${address} is malformed`;
    if (!e || typeof e !== "object" || !Number.isInteger(e.n) || e.n < 0 || e.prefix !== PREFIX || e.group !== GROUP
        || typeof e.ids !== "string" || typeof e.groups !== "string") return bad;
    let a, b;
    try { a = unb64(e.ids); b = unb64(e.groups); } catch { return bad; }
    if (a.length !== e.n * PREFIX || b.length !== Math.ceil(e.n / GROUP) * 32) return bad;
  }
  return null;
}

const norm = (address) => (address.endsWith("/") ? address : address + "/");

// The identity of the rules a read was assessed under: the digest of {trust, profile}, whoever gave them.
export function rulesId(r, backend) { return docId({ trust: r.rules.trust, profile: r.rules.profile }, backend); }

// The mark of `r` now (read from `base`): the ids of every record of the main store and of each other store read,
// under the identity of the rules of the main store's read. The page keeps this JSON; `--write-mark` writes it.
// With a watch list (`watch`, as parseWatch takes it), the mark also records the floor this reader sees now of each
// watched lineage (`floors`, floorOf): what the records alone cannot reproduce (a pinned file compared with the tree
// served now) is then compared with what was seen. Without one the mark is as it was.
export async function makeMark(r, base, backend, at = Math.floor(Date.now() / 1000), { watch } = {}) {
  const stores = { [norm(base)]: await markOf(r.recs.keys(), backend) };
  for (const o of r.others ?? []) if (o.r && !(norm(o.address) in stores)) stores[norm(o.address)] = await markOf(o.r.recs.keys(), backend);
  const floors = {};
  for (const L of parseWatch(watch ?? []).ids) if (r.rep.lineages[L]) floors[L] = floorOf(r, L);
  return { warrant: MARK, base: norm(base), rules: await rulesId(r, backend), at, stores, ...(Object.keys(floors).length ? { floors } : {}) };
}

// warrant_agent/changes.py subset: `store` with only the lines whose record id is in `keep` (all its blobs kept).
async function subsetOf(store, keep, backend) {
  const dec = new TextDecoder();
  const ids = await Promise.all(store.lines.map(async (l) => {
    try { return await backend.sha256(canon(JSON.parse(dec.decode(l)).record)); } catch { return null; }
  }));
  return { ...store, lines: store.lines.filter((_, k) => ids[k] !== null && keep.has(ids[k])) };
}

// A fetcher that asks each URL once and answers again with the same bytes: the pins of the past and of now are
// compared with one tree, the one the address serves now (there is no other), each file fetched once.
export function memoFetch(fetcher) {
  const got = new Map();
  return (url) => {
    if (!got.has(url)) {
      got.set(url, (async () => {
        const r = await fetcher(url);
        return { status: r.status, ok: r.ok, bytes: r.ok ? new Uint8Array(await r.arrayBuffer()) : null };
      })());
    }
    return got.get(url).then((x) => ({ status: x.status, ok: x.ok, arrayBuffer: async () => x.bytes.slice().buffer }));
  };
}

// A lineage's VIEW, the definition this reader compares (warrant_agent/view.py observe, with lineage() in the place of
// the lens): what lineage() shows of it, in two parts.
//   floor  compared member by member, each one that differs named as moved [before, after]:
//          state; reliance as shown (shown(): never ELIGIBLE on pins not compared; with pins compared, the gate's
//          word); standing (the sorted ids of the counted challenges that stand against a version); forks (how many
//          versions fork); effective (the effective version's id, or null); versions (how many).
//   seen   a set of [record id, member], each one that differs named as appeared or vanished:
//          [v, "version"] for each version; [v, "guard G"], [v, "accepted by A"], [v, "waits for W"] of its guard;
//          [x, "attest" | "challenge"] for each attest or challenge on a version, and [x, "counted"], [x, "stands"]
//          for a challenge that is; with other stores read, [x, "voice from ADDRESS"] for each voice from outside.
// Not in it: what is the same for every lineage of a read (completeness, whose rules: a mark is per rules), and what a
// record id fixes (a version's or an attest's actor, time, verdict and text: content-addressed, so a new text is a new
// id). Also not in it, so a change there lists nothing: the overlay ("for me" under the reader's rules) and each
// acceptance's pin rows (their verdict is in the reliance).
function viewOf(d) {
  const f = d.floor, seen = new Map();
  const put = (id, member) => seen.set(canonStr([id, member]), [id, member]);
  for (const v of d.versions) {
    put(v.id, "version");
    put(v.id, `guard ${v.guard}`);
    for (const a of v.accepted_by) put(v.id, `accepted by ${a}`);
    for (const w of v.waiting) put(v.id, `waits for ${w}`);
    for (const s of v.said) {
      put(s.id, s.kind);
      if (s.counted) put(s.id, "counted");
      if (s.stands) put(s.id, "stands");
    }
  }
  for (const x of f.outside?.voices ?? []) put(x.id, `voice from ${x.address}`);
  return { floor: { state: f.state, reliance: f.reliance, standing: f.standing.map((s) => s.id).sort(utf16), forks: f.forks,
                    effective: d.versions.find((v) => v.effective)?.id ?? null, versions: d.versions.length },
           seen };
}

function viewsOf(r) {                                     // {root: view} of every lineage, from one pass over the records
  const idx = { on: onIndex(r), pins: pinsIndex(r) }, out = new Map();
  for (const root of Object.keys(r.rep.lineages)) out.set(root, viewOf(lineage(r, root, idx)));
  return out;
}

const pairCmp = (a, b) => utf16(a[0], b[0]) || utf16(a[1], b[1]);

// warrant_agent/view.py difference: {appeared, vanished, moved} from view `a` to view `b`; `a` null: the lineage is new
// in `b`. (`b` is never null: the past is a subset of the lines served now, so each lineage it has, now has.)
export function difference(a, b) {
  const sa = a ? a.seen : new Map(), sb = b.seen;
  const appeared = [...sb].filter(([k]) => !sa.has(k)).map(([, p]) => p).sort(pairCmp);
  const vanished = [...sa].filter(([k]) => !sb.has(k)).map(([, p]) => p).sort(pairCmp);
  const moved = !a ? { new: [null, true] }
    : Object.fromEntries(Object.keys(b.floor).filter((k) => canonStr(a.floor[k]) !== canonStr(b.floor[k])).map((k) => [k, [a.floor[k], b.floor[k]]]));
  return { appeared, vanished, moved };
}

// What changed for the reader since `mark` (makeMark's JSON, or null): {mark: null, why} when there is no mark this
// read can use, else {mark: {at, base, rules, stores: [{address, marked, gone, unverified, new}]}, new, listed, quiet}:
// `listed` the lineages whose view differs, each with what appeared, vanished and moved, its floor before and after;
// `quiet` how many of the `new` records (here and in the other stores read) change no lineage's view.
// The past is the marked subset of each store read, assessed as now (the main store under `r`'s rules, each other
// store under its own); with pins compared now (r.compared), the past's are compared with the same tree (`fetcher`:
// memoFetch, to fetch nothing twice). An other store the mark does not hold is read as empty then: all of it is new.
export async function changes(r, mark, backend, source, opts = {}) {
  return changesOf(r, await since(r, mark, backend, source, opts));
}

// The comparison changes() and watched() share, made once: {why} when there is no mark this read can use, else {why:
// null, mark, root, past, stores, before, after} (the past read, each store's count, every lineage's view then and now).
export async function since(r, mark, backend, source, { base, fetcher = globalThis.fetch } = {}) {
  const root = norm(base);
  const why = await markRefusal(r, mark, root, backend);
  if (why) return { why, root, mark: null };
  const { past, stores } = await pastOf(r, mark, root, backend, source);
  if (r.compared) await comparePins(past, root, { fetcher });
  return { why: null, root, mark, past, stores, before: viewsOf(past), after: viewsOf(r) };
}

// changes() of a comparison since() made.
export function changesOf(r, s) {
  if (s.why) return { mark: null, why: s.why };
  const { fresh, touched } = newRecords(r, s.past);
  const { listed, accounted } = changedLineages(r, s.before, s.after, fresh, touched);
  return { mark: { at: s.mark.at, base: s.root, rules: s.mark.rules, stores: s.stores }, new: fresh.size, listed,
           quiet: [...fresh].filter((i) => !accounted.has(i)).length };
}

// Why `mark` cannot be compared with `r` (read from `root`), or null: none yet, unreadable, of another store, of other
// rules, or holding nothing of this store.
async function markRefusal(r, mark, root, backend) {
  if (mark === null || mark === undefined) return "no mark yet: nothing is compared until you mark this store as seen";
  const bad = markProblem(mark);
  if (bad) return `the mark cannot be read: ${bad}`;
  if (mark.base !== root) return `the mark is of another store (${mark.base})`;
  if (mark.rules !== (await rulesId(r, backend))) return "the mark was set under other rules: a mark belongs to the rules it was read under, and is not used under these";
  if (!mark.stores[root]) return "the mark holds nothing of this store";
  return null;
}

// {past, stores}: the marked subset of the main store assessed under `r`'s rules, with (when `r` read others) the
// marked subset of each other store under its own; `stores` the count of each against its mark entry.
async function pastOf(r, mark, root, backend, source) {
  const m = await unmark(mark.stores[root], r.recs.keys(), backend);
  const past = await read(await subsetOf(r.store, m.seen, backend), { ...r.rules, whose: r.whose }, backend, source);
  const stores = [{ address: root, marked: m.marked, gone: m.gone, unverified: m.unverified, new: r.recs.size - past.recs.size }];
  if (r.others) {
    past.others = [];
    for (const o of r.others) {
      const then = await otherPast(o, mark, backend, source);
      past.others.push(then.other);
      if (then.store) stores.push(then.store);
    }
  }
  return { past, stores };
}

// {other, store} of one other store: the marked subset of it, read under its own rules (empty when the mark does not
// hold it: all of it is new), and its count; a store that could not be read now stays as it is, uncounted.
async function otherPast(o, mark, backend, source) {
  if (!o.r) return { other: o, store: null };
  const e = mark.stores[norm(o.address)];
  const mo = e ? await unmark(e, o.r.recs.keys(), backend) : { seen: new Set(), marked: null, gone: 0, unverified: 0 };
  const pr = await read(await subsetOf(o.r.store, mo.seen, backend), receiver(o.r.store.doc, null), backend, source);
  return { other: { ...o, r: pr },
           store: { address: norm(o.address), marked: mo.marked, gone: mo.gone, unverified: mo.unverified, new: o.r.recs.size - pr.recs.size } };
}

// {fresh, touched}: the new records (here and in the other stores read) and, by lineage, those each touches (an
// entity of it, an attest or a challenge on one of its versions) with the latest time among them: view.py candidates,
// for the count of those that change nothing.
function newRecords(r, past) {
  const rootOf = new Map();
  for (const [L, lin] of Object.entries(r.rep.lineages)) for (const v of lin.versions) rootOf.set(v, L);
  const fresh = new Set(), touched = new Map();
  const touch = (id, rec) => {
    fresh.add(id);
    const L = rootOf.get(rec.kind === "attest" || rec.kind === "challenge" ? rec.body?.target : id);
    if (L === undefined) return;
    if (!touched.has(L)) touched.set(L, { ids: new Set(), at: null });
    const t = touched.get(L);
    t.ids.add(id);
    if (Number.isInteger(rec.at) && (t.at === null || rec.at > t.at)) t.at = rec.at;
  };
  const added = (now, then) => { for (const [id, rec] of now.recs) if (!then.recs.has(id)) touch(id, rec); };
  added(r, past);
  (r.others ?? []).forEach((o, k) => { if (o.r) added(o.r, past.others[k].r); });
  return { fresh, touched };
}

// {listed, accounted}: each lineage whose view differs from `before` to `after`, newest first, and the new records
// those listings account for (the ones touching a listed lineage, and the new ones named as what appeared).
function changedLineages(r, before, after, fresh, touched) {
  const listed = [], accounted = new Set();
  for (const L of [...after.keys()].sort(utf16)) {
    const a = before.get(L) ?? null, b = after.get(L), diff = difference(a, b);
    if (!diff.appeared.length && !diff.vanished.length && !Object.keys(diff.moved).length) continue;
    for (const i of touched.get(L)?.ids ?? []) accounted.add(i);
    for (const [i] of diff.appeared) if (fresh.has(i)) accounted.add(i);
    const lin = r.rep.lineages[L], rec = r.recs.get(lin.effective || lin.leaf || L);
    listed.push({ lineage: L, schema: lin.schema, title: title(rec) || title(r.recs.get(L)), new: a === null,
                  at: touched.get(L)?.at ?? null, ...diff, before: a ? a.floor : null, after: b.floor });
  }
  listed.sort((x, y) => (y.at ?? 0) - (x.at ?? 0) || utf16(x.lineage, y.lineage));
  return { listed, accounted };
}

// The one sentence a page says of `c` (changes()): silence said plainly, never everything presented as changed.
export function changesLine(c) {
  if (!c.mark) return c.why;
  const gone = c.mark.stores.reduce((n, s) => n + s.gone, 0), doubt = c.mark.stores.reduce((n, s) => n + s.unverified, 0);
  const tail = (gone ? ` · ${gone} marked record(s) no longer served` : "")
    + (doubt ? ` · ${doubt} record(s) whose mark could not be verified, counted as new` : "");
  if (!c.listed.length) return (c.new ? `${c.new} new record(s) changed nothing you see` : "no new records since the mark") + tail;
  return `${c.listed.length} lineage(s) changed for you · ${c.quiet} other new record(s) changed nothing you see` + tail;
}

// ---------------------------------------------------------------- a watch list: frames, and silence with its evidence
//
// The reader names the lineages it relies on (a watch list: their roots). What changed is then said of them alone, in
// one of three outcomes, never more than the records these addresses serve now establish:
//   touched          a watched lineage has a new record in its frame (the witness: each such record, its store, and a
//                    shortest chain of relations from it to the lineage), or its own floor moved (state, reliance as
//                    shown, standing challenges, leaf), or its view differs: with no new record in its frame that is
//                    said as "moved with no new record";
//   silent           none is touched: how many records are new, that none of them is in a watched frame, the frames'
//                    size and the stores' size, at the addresses read (completeness stays UNATTESTED);
//   not established  silence could not be said, and why: no mark this read can use, a watched value that is no lineage
//                    root here, a store beside this one not read now, a marked record no longer served, a mark entry
//                    that could not be verified, pins compared with no floor of a watched lineage recorded in the mark.
//
// THE FRAME of the lineages `roots` (frame()): the set of record ids a reader's reliance on them can be moved through.
// The closure, starting from every version of each root lineage, under
//   (a) the out-edges of the report's graph whose relation is in warrant/graph.py WALK (lineage, requires, ref, attest,
//       challenge): what a member rests on;
//   (b) the in-edges of relation attest or challenge: what was said on a member;
//   (c) every version of the lineage of any member;
// the frame is the ids of that closure that are records of the view (the graph's nodes); an id the closure reaches that
// is no record here (a blob, a record not served) is in the closure, not in the frame.
//   (d) when other stores were read (r.others): a record of another store that is an attest or a challenge whose target
//       is in the closure (an edge of that store's own graph: a record its own assessment admits), unless the main
//       store holds it too, is in the frame, named with its store's address; the closure does not go on from it.
// Every sentence watchLine() says of a frame says no more than this.

export const WALK = ["lineage", "requires", "ref", "attest", "challenge"];     // warrant/graph.py WALK
export const SAME = "same lineage";                     // the step of (c) in a chain: two versions of one lineage
export const WATCH_EXIT = { silent: 0, touched: 3, "not established": 4 };      // the CLI's exit status with --watch
const SAID = new Set(["attest", "challenge"]);

// {out: {id: [[rel, to]]} of the WALK relations, into: {id: [[rel, from]]} of attest and challenge, rootOf: {version:
// root}, nodes: the view's record ids} of `r`'s graph, built once per read.
function graphIndex(r) {
  if (r._graph) return r._graph;
  const out = new Map(), into = new Map(), rootOf = new Map();
  const push = (m, k, v) => { if (!m.has(k)) m.set(k, []); m.get(k).push(v); };
  for (const [a, rel, b] of r.rep.graph.edges) {
    if (!WALK.includes(rel)) continue;
    push(out, a, [rel, b]);
    if (SAID.has(rel)) push(into, b, [rel, a]);
  }
  for (const [L, lin] of Object.entries(r.rep.lineages)) for (const v of lin.versions) rootOf.set(v, L);
  r._graph = { out, into, rootOf, nodes: new Set(r.rep.graph.nodes.map((n) => n[0])) };
  return r._graph;
}

// The closure of (a)-(c) from the versions of `roots`, breadth first: {id: the step it was reached by, [from, rel, to]
// as the graph's edge reads (SAME for (c)), or null for a version of a root}. Following the steps back from an id gives
// a shortest chain from it to a version of a root.
function closure(r, roots) {
  const { out, into, rootOf } = graphIndex(r), via = new Map(), todo = [];
  const reach = (id, step) => { if (!via.has(id)) { via.set(id, step); todo.push(id); } };
  for (const L of roots) for (const v of r.rep.lineages[L]?.versions ?? []) reach(v, null);
  for (let k = 0; k < todo.length; k++) {
    const cur = todo[k];
    for (const [rel, b] of out.get(cur) ?? []) reach(b, [cur, rel, b]);
    for (const [rel, a] of into.get(cur) ?? []) reach(a, [a, rel, cur]);
    const L = rootOf.get(cur);
    if (L !== undefined) for (const v of r.rep.lineages[L].versions) reach(v, [v, SAME, cur]);
  }
  return via;
}

// The steps from `id` back to a version of a root: [[from, rel, to]], the first touching `id`.
function chainOf(via, id) {
  const steps = [];
  let x = id;
  while (via.get(x)) {
    const s = via.get(x);
    steps.push(s);
    x = s[0] === x ? s[2] : s[0];
  }
  return steps;
}

// (d): [{address, id, rel, target}] of the other stores' attests and challenges on an id of the closure `via`.
function outsideFrame(r, via) {
  const out = [], seen = new Set();
  for (const o of r.others ?? []) {
    if (!o.r) continue;
    for (const [x, rel, t] of o.r.rep.graph.edges) {
      const key = `${o.address} ${x}`;
      if (!SAID.has(rel) || !via.has(t) || r.recs.has(x) || seen.has(key)) continue;
      seen.add(key);
      out.push({ address: o.address, id: x, rel, target: t });
    }
  }
  return out.sort((a, b) => utf16(a.address, b.address) || utf16(a.id, b.id));
}

// The frame of `roots` (lineage roots of `r`): {roots, ids: the records of this store in it, sorted; outside: (d)}.
export function frame(r, roots) {
  const via = closure(r, roots), { nodes } = graphIndex(r);
  return { roots: [...roots], ids: [...via.keys()].filter((i) => nodes.has(i)).sort(utf16), outside: outsideFrame(r, via) };
}

// {ids, refused: [{value, why}]} of watch values (each "ID" or "ID,ID,…"): an id is 64 lowercase hexadecimal
// characters and nothing else; every other piece is refused by name, never dropped.
export function parseWatch(values) {
  const ids = new Set(), refused = [];
  for (const v of values ?? []) {
    for (const piece of String(v).split(",")) {
      if (piece.length === 64 && /^[0-9a-f]{64}$/.test(piece)) ids.add(piece);
      else refused.push({ value: piece, why: `${JSON.stringify(piece)} is no record id (64 lowercase hexadecimal characters, nothing else)` });
    }
  }
  return { ids: [...ids].sort(utf16), refused };
}

// The floor of lineage `L` as this reader shows it, or null when `r` has no such lineage: state, reliance (shown()),
// the sorted counted challenges that stand against a version, leaf.
export function floorOf(r, L) {
  const lin = r.rep.lineages[L];
  if (!lin) return null;
  const standing = Object.entries(r.rep.challenges).filter(([, c]) => c.counted && c.stands && lin.versions.includes(c.target)).map(([i]) => i);
  return { state: lin.state, reliance: shown(r, L), standing: standing.sort(utf16), leaf: lin.leaf };
}

const isFloor = (f) => Boolean(f) && typeof f === "object" && !Array.isArray(f) && (f.state === null || typeof f.state === "string")
  && typeof f.reliance === "string" && Array.isArray(f.standing) && f.standing.every((x) => hex64(x)) && (f.leaf === null || hex64(f.leaf));

// Why the watched values cannot all be read as lineage roots of `r`, one reason each (none for a root).
function rootReasons(r, ids, refused) {
  const { rootOf } = graphIndex(r);
  const out = refused.map((x) => `the watched value ${x.why}`);
  for (const id of ids) {
    if (r.rep.lineages[id]) continue;
    const L = rootOf.get(id);
    out.push(L ? `${id} is a version of lineage ${L}, not its root: watch ${L}` : `${id} is not the root of a lineage at this address`);
  }
  if (!ids.length && !refused.length) out.push("no lineage is watched");
  return out;
}

// Why the comparison `s` cannot establish silence about `roots`, one reason each.
function comparisonReasons(r, s, roots) {
  if (s.why) return [`no comparison with a mark: ${s.why}`];
  const out = (r.others ?? []).filter((o) => !o.r).map((o) => `the store at ${o.address} could not be read now (${o.why})`);
  for (const x of s.stores) {
    if (x.gone) out.push(`${x.gone} marked record(s) at ${x.address} are no longer served`);
    if (x.unverified) out.push(`${x.unverified} record(s) at ${x.address} whose mark could not be verified`);
  }
  const floors = s.mark.floors;
  if (floors !== undefined && (!floors || typeof floors !== "object" || Array.isArray(floors) || !Object.values(floors).every(isFloor))) {
    out.push("the floors the mark recorded cannot be read");
  } else if (r.compared) {
    for (const L of roots) if (!floors?.[L]) out.push(`pins are compared and the mark recorded no floor of ${L}: a file changed since then would not be seen (mark again while watching it)`);
  }
  return out;
}

// [{store, id, rec}] of the records new since the mark: this store's, then each other store read.
function newSince(r, s) {
  const out = [];
  for (const [id, rec] of r.recs) if (!s.past.recs.has(id)) out.push({ store: s.root, id, rec });
  (r.others ?? []).forEach((o, k) => {
    if (!o.r) return;
    const then = s.past.others?.[k]?.r;
    for (const [id, rec] of o.r.recs) if (!then?.recs.has(id)) out.push({ store: o.address, id, rec });
  });
  return out;
}

// The chain from a new record to a version of the watched lineage, or null when the record is not in its frame: one of
// this store's records of the closure `via`; or another store's record of (d) (`far`), its own edge first.
function witnessChain(here, id, via, nodes, far) {
  if (here) return nodes.has(id) && via.has(id) ? chainOf(via, id) : null;
  return far ? [[far.id, far.rel, far.target], ...chainOf(via, far.target)] : null;
}

// One watched lineage: {lineage, schema, title, witness, floor, moved, view, said}, or null when nothing touched it.
function touchedOne(r, s, L, fresh) {
  const via = closure(r, [L]), { nodes } = graphIndex(r);
  const outside = new Map(outsideFrame(r, via).map((x) => [`${x.address} ${x.id}`, x]));
  const witness = [];
  for (const { store, id, rec } of fresh) {
    const chain = witnessChain(store === s.root, id, via, nodes, outside.get(`${store} ${id}`));
    if (chain === null) continue;
    witness.push({ id, store, kind: rec.kind, actor: rec.actor, at: rec.at, distance: chain.length, chain });
  }
  witness.sort((a, b) => a.distance - b.distance || utf16(a.store, b.store) || utf16(a.id, b.id));
  const kept = s.mark.floors?.[L], before = isFloor(kept) ? kept : floorOf(s.past, L), after = floorOf(r, L);
  const moved = before ? Object.fromEntries(["state", "reliance", "standing", "leaf"].filter((k) => canonStr(before[k]) !== canonStr(after[k])).map((k) => [k, [before[k], after[k]]]))
    : { new: [null, true] };
  const d = difference(s.before.get(L) ?? null, s.after.get(L));
  const view = d.appeared.length + d.vanished.length + Object.keys(d.moved).length > 0;
  if (!witness.length && !Object.keys(moved).length && !view) return null;
  const lin = r.rep.lineages[L];
  return { lineage: L, schema: lin.schema, title: title(r.recs.get(lin.effective || lin.leaf || L)) || title(r.recs.get(L)),
           witness, floor: { before, after }, moved, view,
           said: witness.length ? `${witness.length} new record(s) in its frame` : "moved with no new record" };
}

// The answer for the watch list `values` (parseWatch) from the comparison `s` (since()): {outcome, watch, refused,
// reasons, addresses, new, in_frames, outside, frame, records, touched, quiet, line}. The counts are null when there
// is no comparison. Silence is said only when no reason stands; with one, the outcome is "not established".
export function watched(r, s, values) {
  const { ids, refused } = parseWatch(values);
  const roots = ids.filter((id) => r.rep.lineages[id]);
  const reasons = [...rootReasons(r, ids, refused), ...comparisonReasons(r, s, roots)];
  const addresses = [s.root, ...(r.others ?? []).filter((o) => o.r).map((o) => o.address)];
  const out = { watch: ids, refused, reasons, addresses, new: null, in_frames: null, outside: null, frame: null, records: null, touched: [], quiet: [] };
  if (!s.why) {
    const fresh = newSince(r, s), all = frame(r, roots);
    out.touched = roots.map((L) => touchedOne(r, s, L, fresh)).filter(Boolean);
    const hit = new Set(out.touched.flatMap((t) => t.witness.map((w) => `${w.store} ${w.id}`)));
    out.quiet = roots.filter((L) => !out.touched.some((t) => t.lineage === L));
    Object.assign(out, { new: fresh.length, in_frames: hit.size, outside: fresh.length - hit.size, frame: all.ids.length + all.outside.length,
                         records: r.recs.size + (r.others ?? []).reduce((n, o) => n + (o.r ? o.r.recs.size : 0), 0) });
  }
  out.outcome = reasons.length ? "not established" : out.touched.length ? "touched" : "silent";
  out.line = watchLine(out);
  if (out.outcome !== "not established") out.toward = toward(r, s, roots);     // after the outcome: it never decides it
  return out;
}

const whereRead = (xs) => (xs.length === 1 ? `this address (${xs[0]})` : `these addresses (${xs.join(", ")})`);

// The one sentence a page says of `w` (watched()): silence only when it was established, never everything presented
// as quiet; a reason, when one stands, in place of either.
export function watchLine(w) {
  const k = w.watch.length;
  if (w.outcome === "not established") return `whether what you watch changed is not established: ${w.reasons.join("; ")}`;
  if (w.outcome === "touched") {
    const bare = w.touched.filter((t) => !t.witness.length).length;
    return `${w.touched.length} of the ${k} lineage(s) you watch touched at ${whereRead(w.addresses)}: ${w.in_frames} new record(s) in their frames`
      + (bare ? ` · ${bare} moved with no new record` : "") + ` · ${w.outside} other new record(s) outside them`;
  }
  return `${w.new} new record(s) at ${whereRead(w.addresses)}; none is in the frame of the ${k} lineage(s) you watch (${w.frame} of ${w.records} records)`
    + " · completeness UNATTESTED: only the records served there now are read";
}

// ---------------------------------------------------------------- toward what you watch: the cone, and the work in it
//
// The frame says whether a reader's RELIANCE on a lineage was touched: what it rests on, and what was said on that.
// A goal's frame is a few records, so a reader who watches goals hears silence while the obligations and pull-request
// heads that cite them open, close and are accepted. That silence is true; toward says the rest, for attention: it
// never changes the outcome (touched, silent, not established), and it is said only when the comparison was made.
//
// THE CONE of the lineages `roots` (cone()): the record ids from which a watched lineage is reachable. The closure,
// starting from every version of each root lineage, under
//   (a) the in-edges of the report's graph whose relation is in WALK (lineage, requires, ref, attest, challenge);
//   (b) every version of the lineage of any member;
// its members are graph nodes only. With other stores read (r.others): a record of another store with an out-edge of
// that store's own graph (any WALK relation) to a member, unless the main store holds it too, is in the cone, named
// with its store's address; the closure does not go on from it.
//
// TOWARD (watched().toward): for each watched lineage, the lineages of this store with a version in its cone, except
// the watched lineages and every lineage with a version in a watched frame (reported once, as the frame's: never a
// witness twice), that are new since the mark or whose floor moved (floorOf: state, reliance as shown, standing
// challenges, leaf); each with its distance and a shortest chain from its nearest version (as a witness's chain), its
// (state, reliance) before and after, and the new records of this store touching it (a version of it, an attest or a
// challenge on one). The other stores' records of the cone are not listed there: their lineages are not this store's.

export const TOWARD_EXIT = 5;               // the CLI's exit status with --toward-exit for "silent, something toward"

// {id: [[rel, from]]} of the WALK relations, by the record they point to: the in-edges (a), built once per read.
function intoIndex(r) {
  if (r._into) return r._into;
  const into = new Map();
  for (const [a, rel, b] of r.rep.graph.edges) {
    if (!WALK.includes(rel)) continue;
    if (!into.has(b)) into.set(b, []);
    into.get(b).push([rel, a]);
  }
  r._into = into;
  return into;
}

// The closure of (a)-(b) from the versions of `roots`, breadth first: {id: the step it was reached by, [from, rel, to]
// as the graph's edge reads (SAME for (b)), or null for a version of a root}; chainOf() gives a shortest chain back.
function coneClosure(r, roots) {
  const up = intoIndex(r), { rootOf, nodes } = graphIndex(r), via = new Map(), todo = [];
  const reach = (id, step) => { if (nodes.has(id) && !via.has(id)) { via.set(id, step); todo.push(id); } };
  for (const L of roots) for (const v of r.rep.lineages[L]?.versions ?? []) reach(v, null);
  for (let k = 0; k < todo.length; k++) {
    const cur = todo[k];
    for (const [rel, a] of up.get(cur) ?? []) reach(a, [a, rel, cur]);                       // (a)
    const M = rootOf.get(cur);
    if (M !== undefined) for (const v of r.rep.lineages[M].versions) reach(v, [v, SAME, cur]);  // (b)
  }
  return via;
}

// [{address, id, rel, target}] of the other stores' records with an edge (WALK) to a member of `via`, the main store
// holding none of them; one entry a record (its first such edge in its graph's order).
function outsideCone(r, via) {
  const out = [], seen = new Set(), read = (r.others ?? []).filter((o) => o.r);
  for (const o of read) {
    for (const [x, rel, t] of o.r.rep.graph.edges) {
      const key = `${o.address} ${x}`;
      if (!WALK.includes(rel) || !via.has(t) || r.recs.has(x) || seen.has(key)) continue;
      seen.add(key);
      out.push({ address: o.address, id: x, rel, target: t });
    }
  }
  return out.sort((a, b) => utf16(a.address, b.address) || utf16(a.id, b.id));
}

// The cone of `roots` (lineage roots of `r`): {roots, ids: the records of this store in it, sorted; outside}.
export function cone(r, roots) {
  const via = coneClosure(r, roots);
  return { roots: [...roots], ids: [...via.keys()].sort(utf16), outside: outsideCone(r, via) };
}

// {lineage: {ids, at}}: the records of this store new since the comparison `s`, by the lineage each touches (a version
// of it, or an attest or a challenge on one), with the latest time among them.
function freshByLineage(r, s) {
  const { rootOf } = graphIndex(r), out = new Map();
  for (const [id, rec] of r.recs) {
    if (s.past.recs.has(id)) continue;
    const L = rootOf.get(rec.kind === "attest" || rec.kind === "challenge" ? rec.body?.target : id);
    if (L === undefined) continue;
    if (!out.has(L)) out.set(L, { ids: [], at: null });
    const t = out.get(L);
    t.ids.push(id);
    if (Number.isInteger(rec.at) && (t.at === null || rec.at > t.at)) t.at = rec.at;
  }
  return out;
}

// The lineages with a version in the frame of any of `roots`, and `roots` themselves: what toward never lists.
function framed(r, roots) {
  const { rootOf } = graphIndex(r), out = new Set(roots);
  for (const L of roots) for (const id of closure(r, [L]).keys()) if (rootOf.has(id)) out.add(rootOf.get(id));
  return out;
}

// {lineage: its nearest version} of the lineages of the cone `via` not in `skip`: the first version the breadth-first
// closure reached (its chain is a shortest one).
function nearestVersions(r, via, skip) {
  const { rootOf } = graphIndex(r), out = new Map();
  for (const id of via.keys()) {
    const M = rootOf.get(id);
    if (M !== undefined && !skip.has(M) && !out.has(M)) out.set(M, id);
  }
  return out;
}

const relied = (f) => (f ? { state: f.state, reliance: f.reliance } : null);
const FLOOR_KEYS = ["state", "reliance", "standing", "leaf"];

// One lineage `M` of the cone of watched `L`, reached first at version `v`: its toward item, or null when it is not new
// and its floor did not move.
function towardItem(r, s, L, M, v, via, fresh) {
  const before = floorOf(s.past, M), after = floorOf(r, M);
  if (before && FLOOR_KEYS.every((k) => canonStr(before[k]) === canonStr(after[k]))) return null;
  const lin = r.rep.lineages[M], chain = chainOf(via, v), mine = fresh.get(M);
  return { watched: L, lineage: M, schema: lin.schema, title: title(r.recs.get(lin.effective || lin.leaf || M)) || title(r.recs.get(M)),
           distance: chain.length, chain, new: !before, before: relied(before), after: relied(after),
           records: mine ? [...mine.ids].sort(utf16) : [], at: mine ? mine.at : null };
}

// watched().toward of the comparison `s` for the watched `roots`: {lineages: newest first, counts: {lineages,
// records} (each lineage and record once, however many watched cones hold it), line}.
function toward(r, s, roots) {
  const skip = framed(r, roots), fresh = freshByLineage(r, s), items = [];
  for (const L of roots) {
    const via = coneClosure(r, [L]);
    for (const [M, v] of nearestVersions(r, via, skip)) {
      const item = towardItem(r, s, L, M, v, via, fresh);
      if (item) items.push(item);
    }
  }
  items.sort((a, b) => (b.at ?? 0) - (a.at ?? 0) || utf16(a.watched, b.watched) || utf16(a.lineage, b.lineage));
  const by = new Map(items.map((x) => [x.lineage, x.schema]));
  const counts = { lineages: by.size, records: new Set(items.flatMap((x) => x.records)).size };
  return { lineages: items, counts, line: towardLine(counts, by, s.root) };
}

// Toward's one sentence: a second sentence beside the watched one, about attention; it says nothing of reliance.
function towardLine(counts, by, root) {
  if (!counts.lineages) return `toward what you watch: no lineage that reaches it moved at ${whereRead([root])}`;
  const schemas = {};
  for (const schema of by.values()) count(schemas, schema);
  const named = Object.entries(sorted(schemas)).map(([k, n]) => `${n} ${k}`).join(", ");
  return `toward what you watch: ${counts.lineages} lineage(s) that reach it moved at ${whereRead([root])} (${named}) through ${counts.records} new record(s)`;
}

// The CLI's exit status for a watched answer `w`: WATCH_EXIT, and with `towardExit` TOWARD_EXIT for silence with a
// lineage toward it (an agent that wants to be woken by work, not only by risk).
export function watchExit(w, towardExit) {
  return towardExit && w.outcome === "silent" && w.toward?.counts.lineages ? TOWARD_EXIT : WATCH_EXIT[w.outcome];
}

// ---------------------------------------------------------------- where the bytes of a cited id are
//
// The resolver's states (warrant/resolve.py), as far as this reader can say them over what it read:
//   PRESENT      a record of this store, or a blob of it fetched and hashed to its name;
//   RESOLVED     not here, but a record of a store read beside this one (`with=`; each line's id is recomputed from its
//                bytes when it is read) or a blob that store fetched and hashed to its name: `where` names that address;
//   MISSING      neither, on a full read (every blob a record names was asked for);
//   NOT_FETCHED  the reader's own word: neither, on a quick read, where no blob of this store was asked for, so it may
//                be one: never PRESENT on bytes not hashed, never MISSING on a question not asked.
// There is no LOCATED here: the reader fetches whole stores, and has no place that names an id without holding it.
// A store beside this one that could not be read is named (`unread`) on an answer that did not find the bytes.

export const NOT_FETCHED = "NOT_FETCHED";

function resolveIndex(r) {
  if (r._resolve) return r._resolve;
  const others = (r.others ?? []).filter((o) => o.r).map((o) => ({ address: o.address, r: o.r }));
  r._resolve = { others, unread: (r.others ?? []).filter((o) => !o.r).map((o) => o.address) };
  return r._resolve;
}

// {id, state, where, lineage[, unread]} of the id `id`: where its bytes are among the stores read.
export function resolved(r, id) {
  const here = r.store.base ?? null;
  if (r.recs.has(id)) return { id, state: "PRESENT", where: here, lineage: graphIndex(r).rootOf.get(id) ?? null };
  if (r.store.blobs.has(id)) return { id, state: "PRESENT", where: here, lineage: null };
  const { others, unread } = resolveIndex(r);
  for (const o of others) {
    if (o.r.recs.has(id)) return { id, state: "RESOLVED", where: o.address, lineage: graphIndex(o.r).rootOf.get(id) ?? null };
    if (o.r.store.blobs.has(id)) return { id, state: "RESOLVED", where: o.address, lineage: null };
  }
  const asked = r.store.mode === "full" || r.store.missing.includes(id);
  return asked ? { id, state: "MISSING", where: null, lineage: null, unread } : { id, state: NOT_FETCHED, where: here, lineage: null, unread };
}

// {from: [[rel, to]]} of every edge of the report's graph (prev too: a version cites what it says it follows).
function citesIndex(r) {
  if (r._cites) return r._cites;
  const out = new Map();
  for (const [a, rel, b] of r.rep.graph.edges) {
    if (!out.has(a)) out.set(a, []);
    out.get(a).push([rel, b]);
  }
  r._cites = out;
  return out;
}

// What each version of lineage `root` cites, newest version first: [{version, cites: [{rel, ...resolved()}]}].
export function citations(r, root) {
  const lin = r.rep.lineages[root];
  if (!lin) return null;
  const idx = citesIndex(r);
  return [...lin.versions].reverse().map((v) => ({ version: v, cites: (idx.get(v) ?? []).map(([rel, b]) => ({ rel, ...resolved(r, b) })) }));
}

// {MISSING, NOT_FETCHED, PRESENT, RESOLVED}: how many distinct ids the graph's edges point to, by resolved()'s word.
function citedCounts(r) {
  const out = { MISSING: 0, NOT_FETCHED: 0, PRESENT: 0, RESOLVED: 0 };
  for (const b of new Set(r.rep.graph.edges.map((e) => e[2]))) out[resolved(r, b).state]++;
  return out;
}

// ---------------------------------------------------------------- what waits for whom: the frontier of an actor
//
// warrant/graph.py frontier, for an actor the reader names (the observer mostly asks it of the agents: "what waits
// for codex"), under the rules the store was read with (r.rules.profile). Python's rule, as it reads:
//   roles       the roles the profile gives the actor;
//   acted       every record an attest or a challenge BY the actor targets: the graph's `attest` and `challenge`
//               edges (the view: a line whose signature fails is no node, so it is no act of the actor's);
//   for each lineage, by root in Python's order, its LEAF only (an earlier pending version was replaced by it; a
//   fork has no leaf and waits for nobody here), when its guard is PENDING:
//     pending   the leaf is the actor's own version;
//     attest    else, when the actor has not acted on it, the guard is still short of attests (`short`), requires
//               no lineage still open (`open` empty), and one of its roles is the actor's: {version, lineage, schema,
//               waiting};
//   challenged  the roots of the lineages the actor wrote whose engine reliance is CHALLENGED.
// No word here is the reader's own (shown(), pins): the frontier is the engine's report, as Python reads it.
export function frontier(r, actor) {
  const { rep } = r;
  const roles = new Set(Object.entries(r.rules.profile.roles).filter(([, actors]) => actors.includes(actor)).map(([role]) => role));
  const author = new Map(rep.graph.nodes.map((n) => [n[0], n[3]]));
  const acted = new Set(rep.graph.edges.filter(([a, rel]) => (rel === "attest" || rel === "challenge") && author.get(a) === actor).map((e) => e[2]));
  const attest = [], pending = [], byRoot = Object.entries(rep.lineages).sort((x, y) => cmp(x[0], y[0]));
  for (const [root, lin] of byRoot) {
    const v = lin.leaf, g = v === null ? null : rep.versions[v];
    if (g?.guard !== "PENDING") continue;
    if (author.get(v) === actor) pending.push(v);
    else if (!acted.has(v) && g.short && !g.open.length && g.roles.some((x) => roles.has(x))) {
      attest.push({ version: v, lineage: root, schema: lin.schema, waiting: g.waiting });
    }
  }
  const challenged = byRoot.filter(([, lin]) => lin.reliance === "CHALLENGED" && lin.actor === actor).map(([root]) => root);
  return { actor, roles: [...roles].sort(cmp), attest, pending, challenged };
}

// What a page draws of frontier(): each item with its lineage (a pending version's too) and its one-line name, and
// how many wait in all.
export function waitsFor(r, actor) {
  const f = frontier(r, actor), rootOf = new Map();
  for (const [L, lin] of Object.entries(r.rep.lineages)) for (const v of lin.versions) rootOf.set(v, L);
  const named = (lineage, version) => ({ lineage, version, schema: r.rep.lineages[lineage].schema,
                                         title: title(r.recs.get(version ?? r.rep.lineages[lineage].leaf ?? lineage)) || title(r.recs.get(lineage)) });
  return { actor, roles: f.roles,
           attest: f.attest.map((x) => ({ ...named(x.lineage, x.version), waiting: x.waiting })),
           pending: f.pending.map((v) => named(rootOf.get(v), v)),
           challenged: f.challenged.map((L) => named(L, null)),
           count: f.attest.length + f.pending.length + f.challenged.length };
}

// The key a page keeps a store's mark under in localStorage: one per store address and rules identity (rulesId),
// shared by the reader and the desk, so that a store marked on one is marked on the other.
export const markKey = (base, rules) => `warrant-${MARK} ${norm(base)} ${rules}`;

const USAGE = "usage: reader.mjs --base URL [--full] [--pins] [--with URL]... [--config RULES.json] [--lineage ID] [--mark FILE] [--write-mark FILE] [--actor NAME]\n"
  + "                  [--watch ID[,ID...]]... [--frame ID[,ID...]] [--toward-exit] [--resolve ID[,ID...]]...\n"
  + "  --watch: the answer for the lineages watched (`watch`); with it the exit status is a gate: 0 silent (established),\n"
  + "  3 touched, 4 not established (2: a refused read or no --base). --write-mark with --watch records their floors.\n"
  + "  --toward-exit: with --watch, 5 for silent with a lineage toward what is watched (watch.toward); the others as above.\n"
  + "  --resolve: where the bytes of each id are (`resolve`); a value that is no record id is refused by name.\n";

// The CLI's options: the value after `name`, every value after a repeated `name`, whether a flag is given.
function options(argv) {
  const opt = (name) => { const k = argv.indexOf(name); return k >= 0 ? argv[k + 1] : undefined; };
  const all = (name) => argv.flatMap((a, k) => (a === name && k + 1 < argv.length ? [argv[k + 1]] : []));
  return { opt, all, has: (name) => argv.includes(name) };
}

// The CLI's `resolve`: {ids: resolved() of each id asked, refused: [{value, why}] (parseWatch's rule), completeness}.
function resolveAll(r, values) {
  const { ids, refused } = parseWatch(values);
  return { ids: ids.map((id) => resolved(r, id)), refused, completeness: "UNATTESTED" };
}

// A mark file as the CLI reads it: a missing file is no mark yet; one that is not JSON, no mark (changes() says so).
export function markFile(fs, path) {
  try { return JSON.parse(fs.readFileSync(path, "utf8")); } catch (e) { return e?.code === "ENOENT" ? null : {}; }
}

// The reading the CLI answers from: the store at `base` under the rules asked for, its pins and its other stores.
async function cliRead(o, base, backend, fs) {
  const store = await fetchStore(base, backend, { full: o.has("--full") });
  const source = new Uint8Array(fs.readFileSync(new URL("./warrant.mjs", import.meta.url)));
  const mine = o.opt("--config") ? loadsLenient(fs.readFileSync(o.opt("--config"), "utf8")) : null;
  const r = await read(store, receiver(store.doc, mine), backend, source);
  const tree = memoFetch(globalThis.fetch);              // the pins of now and of the past, from one fetch each
  if (o.has("--pins")) await comparePins(r, base, { fetcher: tree });
  const others = o.all("--with");
  if (others.length) {
    r.others = await readOthers(others, backend, source);
    await overlay(r, base, backend, source);
  }
  return { r, source, tree };
}

async function main(argv) {
  const fs = await import("node:fs");
  const { nodeBackend } = await import("./warrant.mjs");
  const backend = await nodeBackend();
  const o = options(argv), base = o.opt("--base");
  if (!base) { process.stderr.write(USAGE); return 2; }
  try {
    const { r, source, tree } = await cliRead(o, base, backend, fs);
    const watch = o.has("--watch") ? o.all("--watch") : null, marked = o.opt("--mark") !== undefined;
    const s = marked || watch ? await since(r, marked ? markFile(fs, o.opt("--mark")) : null, backend, source, { base, fetcher: tree }) : null;
    const changed = marked ? changesOf(r, s) : null;
    if (o.opt("--write-mark") !== undefined) fs.writeFileSync(o.opt("--write-mark"), JSON.stringify(await makeMark(r, base, backend, undefined, { watch: watch ?? [] })) + "\n");
    const out = o.opt("--lineage") ? { lineage: lineage(r, o.opt("--lineage")) }
      : { summary: summary(r), rows: rows(r), ...(changed ? { changes: { ...changed, line: changesLine(changed) } } : {}) };
    if (o.opt("--actor") !== undefined) out.frontier = frontier(r, o.opt("--actor"));     // only when asked: else as it was
    if (o.has("--frame")) { const f = parseWatch(o.all("--frame")); out.frame = { ...frame(r, f.ids.filter((L) => r.rep.lineages[L])), refused: f.refused }; }
    if (o.has("--resolve")) out.resolve = resolveAll(r, o.all("--resolve"));
    const w = watch ? watched(r, s, watch) : null;
    if (w) out.watch = w;
    process.stdout.write(canonStr(out) + "\n");
    return w ? watchExit(w, o.has("--toward-exit")) : 0;
  } catch (e) {
    if (e instanceof Refused) { process.stdout.write(canonStr({ refused: e.message }) + "\n"); return 2; }
    throw e;
  }
}

if (typeof process !== "undefined" && process.argv && import.meta.url === (await import("node:url")).pathToFileURL(process.argv[1] || "").href) {
  process.exitCode = await main(process.argv.slice(2));
}
