// The page of the browser reader: it draws what reader.mjs computed, as text only (page.mjs el(): no markup is ever
// built from a string), and the page's policy allows no script but this origin's (reader.html).
import { utf16, webBackend } from "./warrant.mjs";
import * as reader from "./reader.mjs";
import { changes, changesLine, comparePins, fetchStore, lineage, makeMark, memoFetch, overlay, PINS_NOT_CHECKED, read, readOthers,
         receiver, rows, rulesId, STALE, summary } from "./reader.mjs";
import { $, counts, el, fill, keepActor, keptActor, loadMark, markKey, pill, saveMark, section, short, when } from "./page.mjs";
import * as page from "./page.mjs";
import * as voice from "./voice.mjs";

const DEFAULT_BASE = "https://raw.githubusercontent.com/s0fractal/warrant/master/";
const PAGE = 150;                                         // rows drawn at once; the rest is named and asked for

let current = null;                                       // {r, base, full, pins, with, changes, ...}: the store read last
let shownRows = PAGE;

function params() {
  const p = new URLSearchParams(location.search);
  return { base: p.get("base"), full: p.get("full") === "1", pins: p.get("pins") === "1", with: p.getAll("with").filter(Boolean), l: p.get("l"), changes: p.get("changes") === "1", watch: p.has("watch") ? p.getAll("watch") : null, schema: p.get("schema") || "", reliance: p.get("reliance") || "", actor: (p.get("actor") || "").trim() };
}

function href(over) {
  const now = params(), q = new URLSearchParams();
  const v = { ...now, ...over };
  if (v.base) q.set("base", v.base);
  if (v.full) q.set("full", "1");
  if (v.pins) q.set("pins", "1");
  for (const w of v.with ?? []) q.append("with", w);
  if (v.l) q.set("l", v.l);
  if (v.changes) q.set("changes", "1");
  if (v.watch) q.set("watch", v.watch.join(","));
  if (v.schema) q.set("schema", v.schema);
  if (v.reliance) q.set("reliance", v.reliance);
  if (v.actor) q.set("actor", v.actor);
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
  const only = p.changes && current.changes?.mark ? new Set(current.changes.listed.map((x) => x.lineage)) : null;   // changes=1
  const kept = all.filter((x) => (!p.schema || x.schema === p.schema) && (!p.reliance || x.reliance === p.reliance) && (!only || only.has(x.id)));
  const select = (id, label, values, now) => {
    const sel = el("select", { id, "aria-label": label }, el("option", { value: "", text: `${label}: all` }),
                   values.map((v) => el("option", { value: v, text: v, selected: v === now })));
    sel.addEventListener("change", () => { shownRows = PAGE; go({ [id]: sel.value, l: null }); });
    return sel;
  };
  const more = kept.length > shownRows ? el("button", { type: "button", text: `Show ${Math.min(PAGE, kept.length - shownRows)} more of ${kept.length - shownRows}` }) : null;
  if (more) more.addEventListener("click", () => { shownRows += PAGE; drawList(); });
  fill(box,
    el("h2", { text: `${only ? "Changed lineages" : "Lineages"} (${kept.length}${kept.length === all.length ? "" : " of " + all.length})` }),
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
  // the door beside the effective version and the leaf (voice.mjs targets: built from their ids alone); none when
  // voice.mjs is of an earlier release, cached apart from this script
  const doors = new Map((typeof voice.targets === "function" ? voice.targets(d) : []).map((t) => [t.version, t]));
  fill(box,
    el("p", { class: "small" }, link("← all lineages", { l: null })),
    el("h2", { class: "statement-title", text: d.versions.at(-1).title || d.versions[0].title || "(no statement)" }),
    watchControl(f.id),
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
        s.kind === "challenge" && s.why ? el("div", { class: "small", text: s.why }) : null))) : null,
      objectBlock(doors.get(v.id)))),
  );
  box.hidden = false;
  box.scrollIntoView({ block: "start" });
}

// ---------------------------------------------------------------- the door: object to this version
//
// A collapsed block beside the effective version and the leaf: the commands that file a voice against exactly that
// version (voice.mjs voiceCommands: its full id, nothing a record says), what such a voice is and is not, and a field
// that adds the address of a store of voices to this page's `with=` list. The commands are text to copy; the page runs
// nothing. The copy button exists only where the browser offers the Clipboard API (a user gesture, no permission
// asked of the page's policy); elsewhere the text is selected by hand.

function copyButton(text) {
  const clip = globalThis.navigator?.clipboard;
  if (typeof clip?.writeText !== "function") return null;
  const b = el("button", { type: "button", class: "copy", text: "Copy" });
  b.addEventListener("click", () => {
    clip.writeText(text).then(() => { b.textContent = "Copied"; }, () => { b.textContent = "Not copied: select the text"; });
  });
  return b;
}

function withField() {
  const input = el("input", { type: "url", inputmode: "url", autocomplete: "off", spellcheck: "false", placeholder: "https://…/", "aria-label": "address of a store of voices" });
  const form = el("form", { class: "who" }, input, el("button", { type: "submit", text: "Read it beside this store" }));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const got = voice.withAdded(params().with, input.value);
    if (got.why) { say(`Not added: ${got.why}.`, true); return; }
    const area = $("with");                               // a cached page of an earlier release may have none
    if (area) area.value = got.with.join("\n");
    go({ with: got.with });
  });
  return form;
}

function objectBlock(t) {
  if (!t) return null;
  const text = t.commands.join("\n");
  const role = t.effective && t.leaf ? "the effective version and the leaf" : t.effective ? "the effective version" : "the leaf, not effective";
  return el("details", { class: "door" },
    el("summary", { text: `Object to this version (${role})` }),
    el("p", { class: "small" }, "From an empty directory, with git and Python ≥ 3.10 (with the package cryptography); the next release of warrant-graph carries ",
      el("code", { text: "warrant say" }), ", 3.0.0a6 does not. ", el("a", { href: "object.html", text: "The steps, explained" }), "."),
    el("pre", { class: "command" }, el("code", { text })),
    copyButton(text),
    (typeof voice.MEANING === "object" ? voice.MEANING : []).map((m) => el("p", { class: "small", text: m })),
    el("p", { class: "small", text: "The address of a store of voices, to read beside this store (added to the list under \"Other stores beside this one\"):" }),
    withField());
}

// ---------------------------------------------------------------- what changed for me
//
// The mark lives in this browser's localStorage, one entry per store address and rules identity (page.mjs markKey,
// shared with the desk; reader.mjs makeMark: compact and exact). Storage can be absent or refuse: the page still draws,
// and says the mark could not be kept; nothing is then presented as changed.

async function markSeen() {
  const c = current;
  const mark = await makeMark(c.r, c.base, c.backend, undefined, { watch: watchValues().values ?? [] });   // the watched floors too
  const why = saveMark(c.key, mark);
  if (why) { say(why, true); return; }
  await compare(c, mark);
  say("Marked: what this store holds now is what you have seen.");
  draw();
}

// The comparison with `mark`, made once (reader.mjs since) and kept, so the watched answer is drawn again without a
// second assessment when the watch list changes; with a reader.mjs of an earlier release, changes() alone.
async function compare(c, mark) {
  const opts = { base: c.base, fetcher: c.tree };
  c.since = typeof reader.since === "function" ? await reader.since(c.r, mark, c.backend, c.source, opts) : null;
  c.changes = c.since ? reader.changesOf(c.r, c.since) : await changes(c.r, mark, c.backend, c.source, opts);
}

// ---------------------------------------------------------------- a watch list
//
// The lineages the reader relies on: named by the address (`watch=ID,ID`, kept as given: reader.mjs parseWatch refuses
// by name what is no root id) or kept in this browser per store (page.mjs keptWatch, the key the desk reads too); the
// address wins. {values, from, why}: values null when there is none.
function watchValues() {
  const p = params();
  if (p.watch) return { values: p.watch, from: "address", why: null };
  if (!current || typeof page.keptWatch !== "function") return { values: null, from: null, why: null };
  const kept = page.keptWatch(current.base);
  return { values: kept.ids.length ? kept.ids : null, from: kept.ids.length ? "kept" : null, why: kept.why };
}

// The watched answer now (reader.mjs watched over the kept comparison), or null without a watch list.
function watchNow() {
  const w = watchValues();
  if (!w.values || !current.since || typeof reader.watched !== "function") return null;
  return { ...reader.watched(current.r, current.since, w.values), from: w.from, storeWhy: w.why };
}

const pieces = (values) => (values ?? []).flatMap((v) => String(v).split(","));

// Watch or stop watching lineage `root`: kept in this browser; carried by the address when it already names the list,
// or when this browser keeps nothing.
function toggleWatch(root, on) {
  const w = watchValues(), list = pieces(w.values).filter((x) => x !== root);
  if (on) list.push(root);
  const why = typeof page.keepWatch === "function" ? page.keepWatch(current.base, list) : "this page's scripts are of two releases: reload it";
  if (why) say(`The watch list is not kept in this browser (${why}); it is in this page's address instead.`, true);
  else say(on ? "Watching this lineage: what changed is said of it first." : "Not watching this lineage any more.");
  if (why || w.from === "address") go({ watch: list.length ? list : null }); else draw();
}

function watchControl(root) {
  if (typeof reader.watched !== "function") return null;
  const on = pieces(watchValues().values).includes(root);
  const b = el("button", { type: "button", class: "watch", text: on ? "Stop watching" : "Watch this lineage" });
  b.addEventListener("click", () => toggleWatch(root, !on));
  return el("p", { class: "small" }, b, on ? " · watched: what changed for you is said of it first" : null);
}

const STEPS_SHOWN = 6;                                    // witness records drawn a lineage; the rest are counted

// One step of a chain, as text: the short ids and the relation.
const stepText = ([a, rel, b]) => `${a.slice(0, 8)} ${rel} ${b.slice(0, 8)}`;

function witnessItem(x, base) {
  return el("li", { class: "small" }, short(x.id), ` · ${x.kind} by ${x.actor} · ${when(x.at)}`,
    x.store === base ? null : el("strong", { text: ` · held at ${x.store}` }),
    ` · ${x.distance} step(s) away: `, el("span", { text: x.chain.map(stepText).join(" · ") }));
}

function drawWatched(w) {
  const k = w.watch.length, touched = w.outcome === "touched";
  return [
    el("h2", { text: `What you watch (${k} lineage${k === 1 ? "" : "s"})` }),
    w.storeWhy ? el("p", { class: "small", text: w.storeWhy }) : null,
    el("p", {}, touched || w.outcome === "not established" ? el("strong", { text: w.line }) : w.line),
    w.refused.length ? el("p", { class: "small", text: `not watched (refused): ${w.refused.map((x) => x.why).join("; ")}` }) : null,
    w.touched.length ? el("ul", { class: "rows" }, w.touched.map((t) => el("li", {},
      link(t.title || "(no statement)", { l: t.lineage }, { class: "row-title" }),
      el("div", { class: "row-meta" }, t.floor.after ? pill(t.floor.after.reliance) : null, ` ${t.schema} · ${t.said}`,
        Object.keys(t.moved).length ? ` · ${movedText(t.moved)}` : null),
      t.witness.length ? el("ul", {}, t.witness.slice(0, STEPS_SHOWN).map((x) => witnessItem(x, current.since?.root)),
        t.witness.length > STEPS_SHOWN ? el("li", { class: "small", text: `and ${t.witness.length - STEPS_SHOWN} more` }) : null) : null))) : null,
    el("p", { class: "small", text: "The frame of a lineage: its versions, what they rest on (lineage, requires, ref, attest, challenge), what was said on any of these, the other versions of their lineages, and what the other stores read say on them. Completeness UNATTESTED." }),
  ];
}

const was = (v) => (v === null ? "none" : Array.isArray(v) ? `${v.length}` : String(v));
function movedText(moved) {
  return Object.entries(moved).map(([k, [a, b]]) =>
    k === "standing" ? `standing challenges ${a.length} → ${b.length}` : k === "effective" ? "another version is effective"
      : k === "leaf" ? "another version is the leaf" : k === "new" ? "new lineage" : `${k} ${was(a)} → ${was(b)}`).join(" · ");
}

function drawChanges() {
  const box = $("changes"), c = current.changes, button = el("button", { type: "button", text: "Mark all as seen" });
  button.addEventListener("click", () => { button.disabled = true; markSeen().catch((e) => say(`Failed: ${e?.message ?? e}`, true)).finally(() => { button.disabled = false; }); });
  const p = params(), w = current.watch;
  if (!c.mark) {
    fill(box, w ? drawWatched(w) : null, el("h2", { text: "What changed for you" }), el("p", { class: "small", text: current.storeWhy || changesLine(c) }),
      current.storeWhy ? null : button);
    box.hidden = false;
    return;
  }
  const all = storeWide(c, p);
  fill(box,
    w ? drawWatched(w) : null,
    w ? el("details", { class: "store-wide" }, el("summary", { text: `Everything that changed at this address: ${c.listed.length} lineage(s)` }), all) : all,
    button,
  );
  box.hidden = false;
}

// The store-wide listing: every lineage whose view differs since the mark.
function storeWide(c, p) {
  return [
    el("h2", { text: "What changed for you" }),
    el("p", {}, `Since your mark of ${when(c.mark.at)}: ${changesLine(c)}.`),
    c.listed.length ? el("ul", { class: "rows" }, c.listed.map((x) => el("li", {},
      link(x.title || "(no statement)", { l: x.lineage }, { class: "row-title" }),
      el("div", { class: "row-meta" }, pill(x.after.reliance),
        ` ${x.schema} · `, x.new ? el("strong", { text: "new lineage" }) : movedText(x.moved) || "its floor did not move",
        x.appeared.length ? ` · appeared: ${x.appeared.map(([i, m]) => `${i.slice(0, 8)} ${m}`).join("; ")}` : null,
        x.vanished.length ? ` · vanished: ${x.vanished.map(([i, m]) => `${i.slice(0, 8)} ${m}`).join("; ")}` : null)))) : null,
    el("p", { class: "small" }, p.changes ? link("show everything", { changes: false }) : link("show only what changed", { changes: true, l: null }),
      " · the past is the records you marked, assessed again here under the same rules; completeness UNATTESTED"),
  ];
}

// ---------------------------------------------------------------- what waits for whom
//
// The actor is named by the address (`actor=NAME`) or by the form drawn here (remembered for both pages, page.mjs
// keepActor); the address wins. The observer mostly asks it of the agents, so the actor is never assumed to be the
// reader. With no actor named, nothing is computed: the section holds the form alone.

const actorOf = (p) => p.actor || keptActor();

// The form that names the actor, made by this script (no page of any release has to hold it).
function actorForm(name) {
  const input = el("input", { id: "actor", type: "text", value: name, autocomplete: "off", spellcheck: "false", placeholder: "an actor, e.g. codex", "aria-label": "actor" });
  const form = el("form", { class: "who" }, el("label", { for: "actor", text: "What waits for" }), input, el("button", { type: "submit", text: "Show" }));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const why = keepActor(input.value);
    if (why) say(`The name is not remembered: ${why}`, true);
    go({ actor: input.value.trim() });
  });
  return form;
}

// One item of the frontier: its lineage's one-line name as a link, and what it is.
function waitItem(x, meta) {
  return el("li", {}, link(x.title || "(no statement)", { l: x.lineage }, { class: "row-title" }),
    el("div", { class: "row-meta" }, `${x.schema} · `, short(x.version ?? x.lineage), meta ? ` · ${meta}` : null));
}

const WAITS_SHOWN = 25;                                   // items drawn a list: a phone's screen, not the whole frontier
let waitsAll = false;                                     // until the reader asks for every item

function waitList(heading, xs, meta) {
  if (!xs.length) return null;
  const rest = waitsAll ? 0 : xs.length - WAITS_SHOWN;
  const more = rest > 0 ? el("button", { type: "button", text: `Show ${rest} more` }) : null;
  if (more) more.addEventListener("click", () => { waitsAll = true; drawWaits(); });
  return [el("h3", { text: `${heading} (${xs.length})` }), el("ul", { class: "rows" }, xs.slice(0, rest > 0 ? WAITS_SHOWN : xs.length).map((x) => waitItem(x, meta?.(x)))), more];
}

function drawWaits() {
  const box = section("waits"), name = actorOf(params());
  if (!name) { fill(box, actorForm("")); box.hidden = false; return; }
  if (typeof reader.waitsFor !== "function") {           // reader.mjs of an earlier release, cached apart from this script
    fill(box, actorForm(name), el("p", { class: "small", text: "This page's scripts are of two releases: reload it to see what waits." }));
    box.hidden = false;
    return;
  }
  const w = reader.waitsFor(current.r, name), rules = current.r.whose === "reader" ? "your rules" : "the publisher's rules";
  fill(box,
    actorForm(name),
    el("h2", { text: `What waits for ${name}` }),
    el("p", { class: "small", text: w.roles.length ? `${name} holds ${w.roles.join(", ")} under ${rules}` : `${name} holds no role under ${rules}` }),
    w.count ? null : el("p", { text: `Nothing waits for ${name} in this store.` }),
    waitList("May attest", w.attest, (x) => `waits for: ${x.waiting.join("; ")}`),
    waitList("Own versions pending", w.pending, () => "its guard waits"),
    waitList("Own lineages challenged", w.challenged, () => "a counted challenge holds it"),
    el("p", { class: "small", text: "warrant.graph frontier: the leaf of each lineage whose guard waits only for a role the actor holds and that it has not attested or challenged; its own pending leaves; its challenged lineages. Completeness UNATTESTED." }),
  );
  box.hidden = false;
}

// The form's section, when the page has one by that name: a cached page of an earlier release has none, and this
// script must still draw there (the two files are fetched apart and a host may cache them apart).
function showForm(yes) {
  const box = $("asking");
  if (box) box.hidden = !yes;
}

function draw() {
  if (!current) return;
  current.watch = watchNow();
  drawChanges();
  drawWaits();
  const onlyChanges = Boolean(params().changes && current.changes?.mark);
  showForm(!onlyChanges);                                 // changes=1 on a phone: what changed comes first, not the form
  if (onlyChanges) $("floor").hidden = true; else drawFloor();
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
    const tree = memoFetch(fetcher);                     // pins of now and of the past: one fetch each
    const store = await fetchStore(base, backend, { full: p.full, fetcher });
    say(`Assessing ${store.lines.length} lines …`);
    const source = new Uint8Array(await (await fetch(new URL("./warrant.mjs", import.meta.url))).arrayBuffer());
    const r = await read(store, receiver(store.doc, mine), backend, source);
    if (p.pins) {
      say(`Comparing pins with the tree at ${base} …`);
      await comparePins(r, base, { fetcher: tree });
    }
    if (p.with.length) {
      say(`Reading ${p.with.length} other store(s) …`);
      r.others = await readOthers(p.with, backend, source, { fetcher });
      await overlay(r, base, backend, source);
    }
    const key = markKey(base, await rulesId(r, backend)), kept = loadMark(key);
    say("Comparing with your mark …");
    const c = { r, base, full: p.full, pins: p.pins, with: p.with, backend, source, tree, key, storeWhy: kept.why };
    await compare(c, kept.mark);
    current = c;
    shownRows = PAGE;
    say(`Read and assessed in ${((performance.now() - started) / 1000).toFixed(1)} s.`);
    draw();
  } catch (e) {
    current = null;
    for (const id of ["changes", "floor", "lineage", "list"]) $(id).hidden = true;
    section("waits").hidden = true;
    showForm(true);                                         // a refusal is said beside the form that can ask again
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
