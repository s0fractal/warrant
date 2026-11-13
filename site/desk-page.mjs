// The page of the desk: it draws what desk.mjs computed, one block a store, as text only (page.mjs el(): no markup is
// ever built from a string), and the page's policy allows no script but this origin's (desk.html). Every element it
// draws into is found or made here (page.mjs section): a cached desk.html of another release must not break it.
import { webBackend } from "./warrant.mjs";
import * as desk from "./desk.mjs";
import { makeMark } from "./reader.mjs";
import { $, counts, el, fill, keepActor, keptActor, loadMark, loadText, markKey, saveMark, saveText, section, short } from "./page.mjs";

const STORES = "warrant-desk-stores/1";                   // the list the reader edited here, as stores.json holds one
const SHOWN = 12;                                         // changed lineages named in a block; the rest is the reader's
const ctx = { plan: null, got: [], backend: null, source: null, actor: "", run: 0 };   // run: the latest start(); an earlier one draws nothing more

function params() {
  const p = new URLSearchParams(location.search);
  return { stores: p.getAll("store").filter(Boolean), actor: (p.get("actor") || "").trim() };
}

function say(text, bad) {
  const s = $("status") ?? section("status");
  s.hidden = false;
  s.textContent = text;
  s.className = "status" + (bad ? " bad" : "");
}

// A link into the reader for one store (and a lineage, an actor, only what changed).
function readerHref(base, extra) {
  const q = new URLSearchParams({ base });
  for (const [k, v] of Object.entries(extra ?? {})) if (v) q.set(k, v);
  return "reader.html?" + q.toString();
}

function storeBlock(entry, k) {
  const b = entry.block;
  const head = el("h2", {}, el("a", { href: readerHref(b.base), text: b.name }));
  if (!b.read) {
    return el("article", { class: "desk-store", id: `store-${k}` }, head,
      el("p", {}, el("strong", { text: `not read: ${b.why}` })), el("p", { class: "small", text: b.base }));
  }
  const c = b.changes, more = c.listed.length - SHOWN;
  const mark = el("button", { type: "button", text: "Mark as seen" });
  mark.addEventListener("click", () => {
    mark.disabled = true;
    markOne(k).catch((e) => say(`Failed: ${e?.message ?? e}`, true)).finally(() => { mark.disabled = false; });
  });
  return el("article", { class: "desk-store", id: `store-${k}` }, head,
    el("p", { class: "row-meta", text: `${b.repository ?? "no name"} · the publisher's rules · ${b.records} records · rejected ${b.rejected} · ${b.lineages} lineages` }),
    el("p", { class: "small", text: `reliance: ${counts(b.reliance)}` }),
    el("p", { class: "small", text: `standing counted challenges: on ${b.challenged} lineage(s)` }),
    el("p", {}, c.listed.length ? el("strong", { text: c.line }) : c.line),
    c.listed.length ? el("ul", { class: "rows" }, c.listed.slice(0, SHOWN).map((x) => el("li", {},
      el("a", { class: "row-title", href: readerHref(b.base, { l: x.lineage }), text: x.title || "(no statement)" }),
      el("div", { class: "row-meta", text: `${x.schema}${x.new ? " · new lineage" : ""}` })))) : null,
    more > 0 ? el("p", { class: "small" }, el("a", { href: readerHref(b.base, { changes: "1" }), text: `and ${more} more: what changed, in the reader` })) : null,
    b.waits ? el("p", {}, el("a", { href: readerHref(b.base, { actor: b.waits.actor }), text: `waits for ${b.waits.actor}: ${b.waits.count}` }),
      el("span", { class: "small", text: ` (may attest ${b.waits.attest} · own pending ${b.waits.pending} · own challenged ${b.waits.challenged})` })) : null,
    mark);
}

function drawStore(k) {
  const box = section("stores"), have = $(`store-${k}`), now = storeBlock(ctx.got[k], k);
  if (have) have.replaceWith(now); else box.append(now);
}

const marksOf = (base, rules) => loadMark(markKey(base, rules));

// A published release (desk.mjs readReleases): what its index says, as published, and the page that verifies it. The
// desk verifies nothing of it, so it draws no pill and no word of a verdict; one that cannot be read is named.
const whom = (xs) => xs.map((x) => x.name ?? `a key the roster does not name (${x.key.slice(0, 12)})`).join(", ") || "none";
function releaseArticle(b) {
  if (!b.read) {
    return el("article", { class: "desk-store" }, el("h2", { text: b.name }),
      el("p", {}, el("strong", { text: `not read: ${b.why}` })), el("p", { class: "small", text: b.index ?? b.base ?? "" }));
  }
  return el("article", { class: "desk-store" }, el("h2", { text: b.name }),
    el("p", { class: "row-meta", text: `${b.note} · ${b.format}` }),
    el("div", { class: "statement", text: b.statement }),
    el("p", { class: "small" }, `chain ${b.chain} at `, short(b.chain_tip), ` · published ${b.published}`),
    el("p", { class: "small", text: `endorsers: ${whom(b.endorsers)}` }),
    el("p", { class: "small", text: `witnesses: ${whom(b.witnesses)}` }),
    el("p", {}, el("a", { href: b.verify, text: "Check it on the minds page" }), el("span", { class: "small", text: " (it runs the published verifier in your browser)" })));
}

// The releases of the list, each drawn as it answers; nothing when desk.mjs is of an earlier release (cached apart).
async function drawReleases(plan, list, id) {
  const box = section("desk-releases");
  const entries = typeof desk.releasesOf === "function" ? desk.releasesOf(plan, list) : [];
  if (!entries.length) { fill(box); box.hidden = true; return; }
  const head = [el("h2", { text: "Published releases" }), el("p", { class: "small", text: "Read from where they are published; not verified here." })];
  fill(box, head, entries.map((e) => el("article", { class: "desk-store" }, el("h2", { text: e.name }), el("p", { class: "small", text: "reading …" }))));
  box.hidden = false;
  const fetcher = (u) => fetch(u, { cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" });
  const got = await desk.readReleases(entries, { fetcher });
  if (id !== ctx.run) return;
  fill(box, head, got.map(releaseArticle));
}

async function remark(k) {                                 // the mark of now, kept; the block drawn again against it
  const g = ctx.got[k], mark = await makeMark(g.r, g.block.base, ctx.backend);
  const why = saveMark(markKey(g.block.base, g.rules), mark);
  if (why) return why;
  const s = { name: g.block.name, base: g.block.base };
  g.block = await desk.block(s, g.r, mark, { backend: ctx.backend, source: ctx.source, actor: ctx.actor });
  drawStore(k);
  return null;
}

async function markOne(k) {
  const why = await remark(k);
  say(why ?? `Marked ${ctx.got[k].block.name}: what it holds now is what you have seen.`, Boolean(why));
}

async function markAll() {
  const read = ctx.got.map((g, k) => (g?.r ? k : -1)).filter((k) => k >= 0);
  for (const k of read) {
    const why = await remark(k);                          // NOSONAR S9382: one store's mark after another, each kept before the next
    if (why) { say(why, true); return; }
  }
  const unread = ctx.got.filter((g) => g && !g.r).length;
  say(`Marked ${read.length} store(s) as seen` + (unread ? ` · ${unread} not read, so not marked` : "") + ".");
}

// The tools above the blocks: who the frontier is for, and one mark for every store.
function drawTools() {
  const box = section("desk-tools");
  const input = el("input", { id: "actor", type: "text", value: ctx.actor, autocomplete: "off", spellcheck: "false", placeholder: "an actor, e.g. codex", "aria-label": "actor" });
  const who = el("form", { class: "who" }, el("label", { for: "actor", text: "What waits for" }), input, el("button", { type: "submit", text: "Show" }));
  who.addEventListener("submit", (e) => {
    e.preventDefault();
    const why = keepActor(input.value);
    if (why) say(`The name is not remembered: ${why}`, true);
    const q = new URLSearchParams(location.search);
    if (input.value.trim()) q.set("actor", input.value.trim()); else q.delete("actor");
    history.pushState(null, "", "?" + q.toString());
    start();
  });
  const all = el("button", { type: "button", text: "Mark all as seen" });
  all.addEventListener("click", () => {
    all.disabled = true;
    markAll().catch((e) => say(`Failed: ${e?.message ?? e}`, true)).finally(() => { all.disabled = false; });
  });
  fill(box, who, all);
  box.hidden = false;
}

// The list of stores, editable: one a line, the address and then its name; kept in this browser when it keeps storage,
// else carried by the address (store=, which names no name).
function drawEditor() {
  const box = section("desk-edit"), plan = ctx.plan;
  const area = el("textarea", { id: "stores-text", rows: 4, spellcheck: "false", "aria-label": "stores, one a line" });
  area.value = desk.linesOf(plan.stores);
  const keep = el("button", { type: "button", text: "Keep this list" }), reset = el("button", { type: "button", text: "Back to the default list" });
  keep.addEventListener("click", () => {
    let list;
    try { list = desk.storesFromLines(area.value); } catch (e) { say(`The list is not kept: ${e.message}`, true); return; }
    const why = saveText(STORES, JSON.stringify(list), "the list");
    const q = new URLSearchParams(location.search);
    q.delete("store");
    if (why) for (const s of list) q.append("store", s.base);           // no storage: the address carries the list
    history.pushState(null, "", "?" + q.toString());
    if (why) say(`${why}: the addresses are in this page's address instead (their names are not kept)`, true);
    start();
  });
  reset.addEventListener("click", () => {
    const why = saveText(STORES, null, "the list");
    if (why) { say(why, true); return; }
    const q = new URLSearchParams(location.search);
    q.delete("store");
    history.pushState(null, "", "?" + q.toString());
    start();
  });
  const from = { address: "the addresses in this page's address", kept: "the list kept in this browser", list: "the default list (stores.json)", none: "no list" }[plan.from];
  fill(box, el("details", {}, el("summary", { text: `The stores on this desk: ${plan.stores.length}, from ${from}` }),
    el("label", { for: "stores-text", text: "One store a line: its address (a repository served over HTTP), then, after a space, a name." }),
    area, el("div", { class: "desk-buttons" }, keep, reset)));
  box.hidden = false;
}

// The text of stores.json beside this page, or null and why.
async function defaultList() {
  try {
    const r = await fetch(new URL("./" + desk.LIST, import.meta.url), { cache: "no-store", credentials: "omit" });
    return r.ok ? { text: await r.text(), why: null } : { text: null, why: `${desk.LIST}: HTTP ${r.status}` };
  } catch (e) { return { text: null, why: `${desk.LIST}: not fetched (${e?.message ?? e})` }; }
}

async function run() {
  const p = params(), id = ++ctx.run;
  say("Reading the list of stores …");
  for (const name of ["desk-tools", "stores", "desk-releases", "desk-edit"]) section(name);   // in this order on a page that has none of them
  ctx.actor = p.actor || keptActor();
  const kept = loadText(STORES), list = await defaultList();
  ctx.plan = desk.selectStores({ addresses: p.stores, kept: kept.value, list: list.text });
  const why = [...ctx.plan.why, ...(list.why ? [list.why] : [])];
  drawTools();
  drawEditor();
  drawReleases(ctx.plan, list.text, id).catch((e) => say(`Failed: ${e?.message ?? e}`, true));   // beside the stores, not after them
  ctx.got = new Array(ctx.plan.stores.length);
  fill(section("stores"));
  section("stores").hidden = false;
  if (!ctx.plan.stores.length) { say(`No store to read: ${why.join("; ") || "the list is empty"}.`, true); return; }
  say(`Reading ${ctx.plan.stores.length} store(s) …` + (why.length ? ` (${why.join("; ")})` : ""));
  ctx.backend = webBackend();
  ctx.source = new Uint8Array(await (await fetch(new URL("./warrant.mjs", import.meta.url))).arrayBuffer());
  const fetcher = (u) => fetch(u, { cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" });
  const started = performance.now();
  // each block is drawn as its store answers, in the list's order: a placeholder holds the place of the others
  ctx.plan.stores.forEach((s, k) => section("stores").append(el("article", { class: "desk-store", id: `store-${k}` }, el("h2", { text: s.name }), el("p", { class: "small", text: "reading …" }))));
  await desk.readDesk(ctx.plan.stores, { backend: ctx.backend, source: ctx.source, fetcher, marks: marksOf, actor: ctx.actor,
                                          done: (k, entry) => { if (id === ctx.run) { ctx.got[k] = entry; drawStore(k); } } });
  if (id !== ctx.run) return;
  const unread = ctx.got.filter((g) => !g.r).length;
  say(`Read and assessed ${ctx.got.length - unread} of ${ctx.got.length} store(s) in ${((performance.now() - started) / 1000).toFixed(1)} s.`
      + (why.length ? ` ${why.join("; ")}.` : ""), unread > 0);
}

function start() {
  run().catch((e) => say(`Failed: ${e?.message ?? e}`, true));    // anything run() did not foresee is shown, never dropped
}

addEventListener("popstate", start);
start();
