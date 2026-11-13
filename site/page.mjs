// What the reader's pages share (reader-page.mjs, desk-page.mjs): drawing as text only, and the browser's storage.
// Everything a record says reaches the document through textContent (the `text` of el() below) or an attribute set by
// name: no markup is ever built from a string, and each page's policy allows no script but this origin's.
//
// The storage keys are the pages' contract with each other: the desk and the reader keep a store's mark under the same
// key (markKey), in the same representation (reader.mjs makeMark), so a store marked on one is marked on the other.
import { MARK } from "./reader.mjs";

export const $ = (id) => document.getElementById(id);

export function el(tag, attrs, ...kids) {
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
export function fill(box, ...kids) {
  box.replaceChildren(...kids.flat(3).filter((k) => k !== null && k !== undefined && k !== false));
}

export const short = (id) => el("code", { text: String(id).slice(0, 12), title: id });
export const when = (at) => (Number.isInteger(at) ? new Date(at * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC" : "");
export const pill = (word) => el("span", { class: "pill pill-" + String(word || "none").toLowerCase().replace(/[^a-z]/g, "-"), text: word || "none" });
export const counts = (o) => Object.entries(o).map(([k, n]) => `${k} ${n}`).join(" · ") || "none";

// The section `id` of this page, made (hidden, at the end of <main>, or of <body> on a page with none) when the page
// has none: a cached page of an earlier release lacks the sections a later script draws, and the two files are fetched
// apart, so no script assumes an element because the current HTML has it.
export function section(id) {
  const have = $(id);
  if (have) return have;
  const made = el("section", { id, hidden: true });
  (document.querySelector("main") ?? document.body).append(made);
  return made;
}

// ---------------------------------------------------------------- storage
//
// Storage can be absent or refuse (a private window, blocked site data, a quota): the pages still draw and say what
// could not be kept; nothing is then presented as changed.

// The page's localStorage, or null: reading `length` touches the storage itself, so an object whose getters throw
// (storage blocked after the property was read) is caught here too, not at the first use.
export function storage() {
  try {
    const s = globalThis.localStorage;
    return Number.isInteger(s.length) ? s : null;
  } catch { return null; }
}

export const NO_STORAGE = "this browser keeps no storage for this page (a private window, or storage blocked): no mark can be kept";

// The key a store's mark is kept under: one per store address and rules identity (reader.mjs rulesId).
export const markKey = (base, rules) => `warrant-${MARK} ${base.endsWith("/") ? base : base + "/"} ${rules}`;

// {value, why}: the text kept under `key` (null when there is none); `why` when storage cannot be read at all.
export function loadText(key) {
  const s = storage();
  if (!s) return { value: null, why: NO_STORAGE };
  try { return { value: s.getItem(key), why: null }; } catch (e) { return { value: null, why: `storage refused to be read (${e?.name || e})` }; }
}

// null, or why `text` (`what`, in the sentence) was not kept under `key`; a null `text` removes the key.
export function saveText(key, text, what = "it") {
  const s = storage();
  if (!s) return NO_STORAGE;
  try {
    if (text === null) s.removeItem(key); else s.setItem(key, text);
    return null;
  } catch (e) { return `${what} could not be kept (${e?.name || e}): this browser's storage refused it`; }
}

// {mark, why}: the mark kept for `key`, null when there is none; `why` when storage cannot be read at all.
export function loadMark(key) {
  const { value, why } = loadText(key);
  if (why) return { mark: null, why };
  try { return { mark: value === null ? null : JSON.parse(value), why: null }; }
  catch { return { mark: {}, why: null }; }               // not JSON: changes() names it a mark it cannot read
}

export const saveMark = (key, mark) => saveText(key, JSON.stringify(mark), "the mark");   // null, or why it was not kept

// The actor whose frontier the pages show ("what waits for NAME"), remembered across pages; "" for none.
const ACTOR = "warrant-reader-actor/1";
export const keptActor = () => (loadText(ACTOR).value ?? "").trim();
export const keepActor = (name) => saveText(ACTOR, name.trim() ? name.trim() : null);
