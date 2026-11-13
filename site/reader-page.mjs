// The page of the browser reader: it draws what reader.mjs computed. Everything a record says reaches the document
// through textContent (the `text` of el() below) or an attribute set by name: no markup is ever built from a string,
// and the page's policy allows no script but this origin's (reader.html).
import { utf16, webBackend } from "./warrant.mjs";
import { comparePins, fetchStore, lineage, overlay, PINS_NOT_CHECKED, read, readOthers, receiver, rows, STALE, summary } from "./reader.mjs";

const DEFAULT_BASE = "https://raw.githubusercontent.com/s0fractal/warrant/master/";
const PAGE = 150;                                         // rows drawn at once; the rest is named and asked for
const $ = (id) => document.getElementById(id);

function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") n.textContent = String(v);
    else if (k === "class") n.className = v;
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) n.append(k);
  return n;
}

// Put `kids` (nodes, strings, arrays of them; nothing for null or false) in place of what `box` held.
function fill(box, ...kids) {
  box.replaceChildren(...kids.flat(3).filter((k) => k !== null && k !== undefined && k !== false));
}

const short = (id) => el("code", { text: String(id).slice(0, 12), title: id });
const when = (at) => (Number.isInteger(at) ? new Date(at * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC" : "");
const pill = (word) => el("span", { class: "pill pill-" + String(word || "none").toLowerCase().replace(/[^a-z]/g, "-"), text: word || "none" });
const counts = (o) => Object.entries(o).map(([k, n]) => `${k} ${n}`).join(" · ") || "none";

let current = null;                                       // {r, base, full, pins, with}: the store read last
let shownRows = PAGE;

function params() {
  const p = new URLSearchParams(location.search);
  return { base: p.get("base"), full: p.get("full") === "1", pins: p.get("pins") === "1", with: p.getAll("with").filter(Boolean), l: p.get("l"), schema: p.get("schema") || "", reliance: p.get("reliance") || "" };
}

function href(over) {
  const now = params(), q = new URLSearchParams();
  const v = { ...now, ...over };
  if (v.base) q.set("base", v.base);
  if (v.full) q.set("full", "1");
  if (v.pins) q.set("pins", "1");
  for (const w of v.with ?? []) q.append("with", w);
  if (v.l) q.set("l", v.l);
  if (v.schema) q.set("schema", v.schema);
  if (v.reliance) q.set("reliance", v.reliance);
  return "?" + q.toString();
}

const same = (p) => current?.base === (p.base || DEFAULT_BASE) && current.full === p.full && current.pins === p.pins
  && current.with.join("\n") === p.with.join("\n");

function go(over) {                                       // the same page at another address, with no second read
  history.pushState(null, "", href(over));
  const p = params();
  if (same(p)) draw(); else start();
}

function link(text, over, attrs) {
  const a = el("a", { href: href(over), text, ...attrs });
  a.addEventListener("click", (e) => { if (!e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); go(over); } });
  return a;
}

function fact(name, ...value) {
  return [el("dt", { text: name }), el("dd", {}, ...value)];
}

function pinsLine(p) {
  if (p.config !== "present") return p.config === "absent" ? "compared nothing: this address serves no .warrant/claims.json, so no claim is gated"
    : `compared nothing: .warrant/claims.json was not fetched (${p.refused.join("; ")})`;
  return `${p.claims} gated claim(s): ${counts(p.verdicts)} · files: ${p.files.fetched} fetched of ${p.files.asked} asked for, `
    + `${p.files.absent} not at their path, ${p.files.refused} not fetched · ${p.compared} comparison(s)`
    + (p.refused.length ? ` · not fetched: ${p.refused.join("; ")}` : "");
}

const pinsWhy = {
  [PINS_NOT_CHECKED]: " accepted on files at a commit; this reader compared no tree for it, so it does not say ELIGIBLE",
  [STALE]: " no acceptance of the claims checker names the bytes this address serves (or a file it names moved, or is a symlink: see below)",
};

function drawPins(c) {
  if (!c) return null;
  return [el("h3", { text: `Pins: ${c.verdict}, compared with the tree at this address` }),
    el("ul", { class: "said" }, c.acceptances.map((a) => el("li", {},
      `acceptance `, short(a.attest), a.commit ? [" at ", short(a.commit)] : null, ` · ${a.verdict}`,
      el("ul", {}, a.files.map((f) => el("li", { class: "small", text: [f.verdict, f.path, f.detail].filter(Boolean).join(" ") })))))),
  ];
}

function drawOthers(s) {
  if (!s.others) return [];
  const o = s.others;
  return [
    fact("other stores", el("ul", {}, o.stores.map((x) => el("li", {}, `${x.name} · ${x.address} · `,
      x.read ? `read, ${x.records} records, under its own rules` : el("strong", { text: `not read: ${x.why}` }))))),
    fact("voices from outside", `${o.voices} on ${o.lineages} lineage(s), counted by this store's rules: none`
      + (o.left_out ? ` · ${o.left_out} left out (their own store rejects them)` : "")),
    fact("for me", overlayLine(s.overlay)),
  ];
}

function overlayLine(v) {
  if (!v) return "no overlay";
  if (v.why) return `no overlay: ${v.why} (paste a trust and a profile under "Judge it under my own rules")`;
  return [`the union of ${v.stores.length} store(s) under your rules: ${v.changed} lineage(s) read otherwise for you · identity `, short(v.identity),
    v.unread.length ? ` · not read: ${v.unread.join(", ")}` : null,
    v.held.length ? ` · key bindings not admitted: ${v.held.map((h) => `${h.actor} (${h.why === "role" ? "your rules give it a role: bind its key yourself" : "the stores disagree"})`).join("; ")}` : null,
    ` · ${v.pins}`,
    el("ul", {}, v.rows.map((x) => el("li", {}, link(x.lineage.slice(0, 12), { l: x.lineage }),
      ` ${x.schema}: in the store ${x.store.state || "none"} ${x.store.shown} → for you ${x.reader ? `${x.reader.state || "none"} ${x.reader.shown}` : "not in the union under your rules"}`)))];
}

function drawOutside(out, ov) {
  if (!out) return null;
  return [el("h3", { text: `Voices from outside (${out.voices.length}, in ${out.stores} store(s)): not counted by this store's rules` }),
    out.left_out ? el("p", { class: "small", text: `${out.left_out} record(s) left out: their own store rejects them` }) : null,
    out.voices.length ? el("ul", { class: "said" }, out.voices.map((v) => el("li", {},
      `${v.store} · ${v.actor} · ${v.kind === "challenge" ? "challenge" : v.verdict || "attest"} · ${when(v.at)} · on `, short(v.target),
      v.statement ? el("div", { class: "statement", text: v.statement }) : null))) : null,
    ov ? el("p", { class: "small" }, ...[ov.why ? `For me: no overlay: ${ov.why}` : ov.same ? "For me: it reads the same under your rules."
      : [`For me: in the store ${ov.store.state || "none"} ${ov.store.shown} → for you ${ov.reader ? `${ov.reader.state || "none"} ${ov.reader.shown}` : "absent"}`,
         ov.challenges.length ? [" · challenges that stand for you: ", ...ov.challenges.flatMap((c) => [short(c), " "])] : null,
         ov.accepted_by.length ? ` · accepted for you by: ${ov.accepted_by.join(", ")}` : null]].flat(2)) : null];
}

function drawFloor() {
  const s = summary(current.r), box = $("floor");
  fill(box,
    el("h2", { text: s.repository || "A store with no name" }),
    el("dl", { class: "facts" },
      fact("rules", s.rules === "reader" ? "yours (the trust and profile you gave)" : "the publisher's own (.warrant/v3.json): under other rules the same bytes give other answers"),
      fact("records", `${s.records} · signed ${s.signed} · vouched for by a migration ${s.migrated} · rejected ${s.rejected}`),
      fact("root", s.root ? short(s.root) : "not computed: the root covers every blob, and only the migration maps were fetched",
           s.root ? null : " ", s.root ? null : link("fetch every blob", { full: true })),
      fact("blobs", `${s.blobs.read} read of ${s.blobs.asked} asked for` + (s.blobs.missing ? ` · ${s.blobs.missing} named and not served` : "")),
      fact("completeness", `${s.completeness}: no store can show that it holds everything said about its records`),
      fact("reliance", counts(s.reliance)),
      s.pins ? fact("pins", pinsLine(s.pins)) : [],
      s.reliance[PINS_NOT_CHECKED] || s.pins ? fact("not checked", s.not_checked.join(" · ")) : [],
      ...drawOthers(s),
      fact("schemas", s.schemas.join(", ") || "none", s.schemas_pending.length ? ` (pending: ${s.schemas_pending.length})` : null),
      fact("writers' forks", s.chain_forks.join(", ") || "none"),
      fact("problems", s.problems.length ? s.problems.map((p) => p[0]).join(", ") : "none"),
      fact("assessed", "in this browser, by warrant.mjs ", short(s.code), ` · assessment `, short(s.assessment)),
    ),
    el("table", {}, el("thead", {}, el("tr", {}, el("th", { text: "Schema" }), el("th", { text: "Lineages by state" }))),
      el("tbody", {}, Object.entries(s.lineages).map(([k, v]) =>
        el("tr", {}, el("td", {}, link(k, { schema: k, l: null })), el("td", { text: counts(v) }))))),
  );
  box.hidden = false;
}

function drawList() {
  const p = params(), all = rows(current.r), box = $("list");
  const schemas = [...new Set(all.map((x) => x.schema))].sort(utf16), words = [...new Set(all.map((x) => x.reliance))].sort(utf16);
  const kept = all.filter((x) => (!p.schema || x.schema === p.schema) && (!p.reliance || x.reliance === p.reliance));
  const select = (id, label, values, now) => {
    const sel = el("select", { id, "aria-label": label }, el("option", { value: "", text: `${label}: all` }),
                   values.map((v) => el("option", { value: v, text: v, selected: v === now })));
    sel.addEventListener("change", () => { shownRows = PAGE; go({ [id]: sel.value, l: null }); });
    return sel;
  };
  const more = kept.length > shownRows ? el("button", { type: "button", text: `Show ${Math.min(PAGE, kept.length - shownRows)} more of ${kept.length - shownRows}` }) : null;
  if (more) more.addEventListener("click", () => { shownRows += PAGE; drawList(); });
  fill(box,
    el("h2", { text: `Lineages (${kept.length}${kept.length === all.length ? "" : " of " + all.length})` }),
    el("div", { class: "filters" }, select("schema", "schema", schemas, p.schema), select("reliance", "reliance", words, p.reliance)),
    el("ul", { class: "rows" }, kept.slice(0, shownRows).map((x) =>
      el("li", {},
        link(x.title || "(no statement)", { l: x.id }, { class: "row-title" }),
        el("div", { class: "row-meta" }, pill(x.reliance), ` ${x.schema} · ${x.state || "no effective version"} · ${x.actor} · ${when(x.at)}`,
           x.standing ? el("strong", { text: ` · ${x.standing} standing challenge${x.standing === 1 ? "" : "s"}` }) : null,
           x.outside ? ` · ${x.outside} voice${x.outside === 1 ? "" : "s"} from outside, not counted` : null)))),
    more,
  );
  box.hidden = false;
}

const word = (s) => (s.kind === "challenge" ? "challenge" : s.verdict || "attest");
const fate = (s) => ` · ${s.counted ? "counted" : "not counted"}${s.stands ? ", stands" : ""}`;

function drawLineage() {
  const p = params(), box = $("lineage");
  if (!p.l) { box.hidden = true; box.replaceChildren(); return; }
  const d = lineage(current.r, p.l);
  if (!d) {
    fill(box, el("h2", { text: "No such lineage here" }), el("p", {}, short(p.l), " is not the root of a lineage of this store. ", link("Back to the list", { l: null })));
    box.hidden = false;
    return;
  }
  const f = d.floor;
  fill(box,
    el("p", { class: "small" }, link("← all lineages", { l: null })),
    el("h2", { class: "statement-title", text: d.versions.at(-1).title || d.versions[0].title || "(no statement)" }),
    el("dl", { class: "facts floor" },
      fact("state", f.state || "none: no version is effective yet"),
      fact("reliance", pill(f.reliance), Object.hasOwn(pinsWhy, f.reliance) ? pinsWhy[f.reliance] : null),
      fact("standing challenges", f.standing.length ? el("ul", {}, f.standing.map((c) => el("li", {}, `${c.actor}: `, el("span", { text: c.statement || "(no statement)" })))) : "none in this store"),
      f.forks ? fact("fork", `${f.forks}: two versions succeed one; the lineage has no leaf`) : [],
      fact("completeness", `${f.completeness}: an objection held elsewhere is not seen here`),
      fact("rules", f.rules === "reader" ? "yours" : "the publisher's own"),
      fact("lineage", short(f.id), ` · ${f.schema}`),
    ),
    drawPins(f.pins),
    drawOutside(f.outside, f.overlay),
    el("h3", { text: `Versions, newest first (${d.versions.length})` }),
    d.versions.map((v) => el("article", { class: "version" + (v.effective ? " effective" : "") },
      el("p", { class: "row-meta" }, short(v.id), ` · ${v.actor} · ${when(v.at)} · state ${v.state || "none"}`,
         v.effective ? el("strong", { text: " · effective" }) : null, v.leaf && !v.effective ? " · leaf, not effective" : null),
      v.title ? el("p", { class: "statement", text: v.title }) : null,
      el("p", { class: "small" }, `guard ${v.guard}`, v.accepted_by.length ? ` · accepted by ${v.accepted_by.join(", ")}` : null,
         v.waiting.length ? ` · waits for: ${v.waiting.join("; ")}` : null),
      v.said.length ? el("ul", { class: "said" }, v.said.map((s) => el("li", {},
        el("span", { class: "glyph", text: s.kind === "challenge" ? "✗ " : "✓ " }),
        `${s.actor} · ${word(s)} · ${when(s.at)}`,
        s.kind === "challenge" ? fate(s) : null,
        s.statement ? el("div", { class: "statement", text: s.statement }) : null,
        s.kind === "challenge" && s.why ? el("div", { class: "small", text: s.why }) : null))) : null)),
  );
  box.hidden = false;
  box.scrollIntoView({ block: "start" });
}

function draw() {
  if (!current) return;
  drawFloor();
  drawLineage();
  drawList();
}

function say(text, bad) {
  const s = $("status");
  s.textContent = text;
  s.className = "status" + (bad ? " bad" : "");
}

async function run() {
  const p = params();
  const base = p.base || DEFAULT_BASE;
  let mine = null;
  const pasted = $("mine").value.trim();
  if (pasted) {
    try { mine = JSON.parse(pasted); } catch { say("Your rules are not JSON; nothing was read.", true); return; }
    if (!mine || typeof mine !== "object" || !mine.trust || !mine.profile) { say("Your rules need both a trust and a profile; nothing was read.", true); return; }
  }
  $("go").disabled = true;
  say(`Reading ${base} …`);
  try {
    const backend = webBackend();
    const started = performance.now();
    const fetcher = (u) => fetch(u, { cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" });
    const store = await fetchStore(base, backend, { full: p.full, fetcher });
    say(`Assessing ${store.lines.length} lines …`);
    const source = new Uint8Array(await (await fetch(new URL("./warrant.mjs", import.meta.url))).arrayBuffer());
    const r = await read(store, receiver(store.doc, mine), backend, source);
    if (p.pins) {
      say(`Comparing pins with the tree at ${base} …`);
      await comparePins(r, base, { fetcher });
    }
    if (p.with.length) {
      say(`Reading ${p.with.length} other store(s) …`);
      r.others = await readOthers(p.with, backend, source, { fetcher });
      await overlay(r, base, backend, source);
    }
    current = { r, base, full: p.full, pins: p.pins, with: p.with };
    shownRows = PAGE;
    say(`Read and assessed in ${((performance.now() - started) / 1000).toFixed(1)} s.`);
    draw();
  } catch (e) {
    current = null;
    for (const id of ["floor", "lineage", "list"]) $(id).hidden = true;
    say(`Refused: ${e?.message ?? e}`, true);                    // a refusal is shown whole; nothing partial is drawn
  } finally {
    $("go").disabled = false;
  }
}

// run() reports its own refusals; anything it did not foresee is shown too, never dropped.
function start() {
  run().catch((e) => say(`Failed: ${e?.message ?? e}`, true));
}

$("ask").addEventListener("submit", (e) => {
  e.preventDefault();
  history.pushState(null, "", href({ base: $("base").value.trim(), full: $("full").checked, pins: $("pins").checked, with: $("with").value.split("\n").map((x) => x.trim()).filter(Boolean), l: null, schema: "", reliance: "" }));
  start();
});
addEventListener("popstate", () => {
  const p = params();
  if (same(p)) draw(); else if (p.base) start();
});

const first = params();
$("base").value = first.base || DEFAULT_BASE;
$("full").checked = first.full;
$("pins").checked = first.pins;
$("with").value = first.with.join("\n");
if (first.base) start();
