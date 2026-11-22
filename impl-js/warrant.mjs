// Warrant 3 assessment (docs/V3.md §§1-10), a second implementation held byte for byte to the Python
// reference (warrant/engine.py, records.py, shapes.py, store.py, jcs.py, keys.py) by tests/impl_js_test.py.
//
// One ES module, no dependencies, no build step. Two phases:
//   1. prepare(input, backend)   async: reads the lines and blobs into a snapshot and computes every
//                                SHA-256 and Ed25519 answer the assessment needs, through `backend`
//                                ({name, sha256(bytes) -> hex, verify(pub, sig, msg) -> bool}, values or
//                                promises): nodeBackend() (node:crypto) or webBackend(crypto.subtle).
//   2. assessPrepared(prep)      pure and synchronous: the report (engine.py View.report()).
// assess(input, backend) runs both. The CLI:
//   node impl-js/warrant.mjs assess --store DIR --config V3JSON [--as-of N]
//   node impl-js/warrant.mjs verify PACKAGE.json --config V3JSON
//   node impl-js/warrant.mjs batch CASES.jsonl        (one case per line, one result per line: the oracle's input)
// Each prints canonical JSON (RFC 8785, this repository's domain: no floats, integers within ±(2^53-1),
// no lone surrogates). A refusal prints {"refused": why} and exits 2.

function surrogatePass(str) {     // UTF-8, with each lone surrogate as its own three bytes (Python's "surrogatepass")
  const out = [];
  for (let i = 0; i < str.length; i++) {
    let c = str.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
      const d = str.charCodeAt(i + 1);
      if (d >= 0xdc00 && d <= 0xdfff) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); i++; }
    }
    if (c < 0x80) out.push(c);
    else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
    else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
  }
  return new Uint8Array(out);
}

export const VERSION = "3";
const MAX_INT = Number.MAX_SAFE_INTEGER;          // 2^53 - 1
const MAX_DEPTH = 256;
const MAX_INT_DIGITS = 4300;                       // CPython's int-to-string conversion limit, which its json reader applies
const BODY_MAX = 16384;
const LINE_MAX = 65536;
export const LIMITS = { records: 200_000, bytes: 256 * 1024 * 1024, refs: 4096, depth: 4096, requires: 128 };
const LIMITS_REPR = "{'records': 200000, 'bytes': 268435456, 'refs': 4096, 'depth': 4096, 'requires': 128}";
const KINDS = ["schema", "entity", "attest", "challenge"];
const MEMBERS = ["warrant", "kind", "actor", "at", "prev", "schema", "lineage", "refs", "guard", "body"];
const GUARD = ["quorum", "roles", "match", "requires"];
const TYPES = ["str", "int", "bool", "strs", "ref", "refs", "obj"];
const MIGRATION = "migration@1";
const SCHEMA_AUTHOR = "schema/author";
const REPLAY = ["reproduces", "does_not_reproduce", "no_result", "does_not_apply"];
const SIG_DOMAIN = "warrant-sig-v3:";
const SCHEMA_MEMBERS = ["name", "fields", "states", "closed", "successors"];
const PACKAGE = "package/3";
const AGENT_API = "warrant-agent/3";
const STORE_BYTES = 64 * 1024 * 1024;             // warrant_agent/config.py DEFAULT_LIMITS["store_bytes"]
const CONTEXT_BYTES = 64 * 1024;                   // ... and ["context_bytes"]

// ---------------------------------------------------------------- errors (Python's exception classes)

export class NotCanonical extends Error {}          // jcs.NotCanonical (a ValueError)
export class Invalid extends Error {}               // records.Invalid (a ValueError)
export class Refused extends Error {}               // store.Refused (a ValueError)
class PyValueError extends Error {}                 // another ValueError a reader raises (an integer too long)
class DecodeError extends Error {}                  // json.JSONDecodeError
export class AgentError extends Error {             // warrant_agent.errors.AgentError
  constructor(code, message) { super(message); this.code = code; }
}
const ORDER = Symbol("members in the order read");
class PyFloat {                                      // a float in a configuration read leniently (Python's json reads it)
  constructor(text) { this.text = text; }
}

// ---------------------------------------------------------------- small helpers

const enc = new TextEncoder();
const utf8 = (s) => enc.encode(s);
const own = (o, k) => (Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined);
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const dict = () => Object.create(null);
const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v) && !(v instanceof PyFloat) && !(v instanceof Uint8Array);
const isInt = (v) => (typeof v === "number" && Number.isInteger(v)) || typeof v === "bigint";
const isStr = (v) => typeof v === "string";
// UTF-16 code unit order (JS's `<` on strings): RFC 8785's member order, so a canonical body's member order, which is
// Python's dict order for a body read from canonical bytes. Not code point order: "\u{1F600}" (D83D DE00) sorts before
// "\uFFFF" here and after it in Python's sorted().
export const utf16 = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
// Byte order of strings whose code units are bytes (bkey): Python's sorted() over bytes.
const byteOrder = utf16;
const keysOf = (o) => Object.keys(o).sort(utf16);
const HEX64 = /^[0-9a-f]{64}$/;
const HEX128 = /^[0-9a-f]{128}$/;
export const hex64 = (v) => isStr(v) && HEX64.test(v);
const hex128 = (v) => isStr(v) && HEX128.test(v);
const hexBytes = (h) => { const b = new Uint8Array(h.length / 2); for (let i = 0; i < b.length; i++) b[i] = parseInt(h.substr(2 * i, 2), 16); return b; };
const bytesHex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
const concat = (parts) => { let n = 0; for (const p of parts) n += p.length; const o = new Uint8Array(n); let k = 0; for (const p of parts) { o.set(p, k); k += p.length; } return o; };
// A string whose UTF-16 units are the bytes: equal keys for equal bytes, and `<` on them is byte order.
const bkey = (b) => { let s = ""; for (let i = 0; i < b.length; i += 8192) s += String.fromCharCode.apply(null, b.subarray(i, i + 8192)); return s; };
const cpLen = (s) => { let n = 0; for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i); if (c >= 0xd800 && c < 0xdc00 && i + 1 < s.length) { const d = s.charCodeAt(i + 1); if (d >= 0xdc00 && d < 0xe000) i++; } n++; } return n; };

// Python's str order: by code point (JS compares UTF-16 units, which differ above U+D7FF).
export function cmp(a, b) {
  if (a === b) return 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    let x = a.charCodeAt(i), y = b.charCodeAt(i);
    if (x !== y) {
      if (x >= 0xd800 && y >= 0xd800) { x = x >= 0xe000 ? x - 0x800 : x + 0x2000; y = y >= 0xe000 ? y - 0x800 : y + 0x2000; }
      return x < y ? -1 : 1;
    }
  }
  return a.length < b.length ? -1 : a.length > b.length ? 1 : 0;
}
// Python's list/tuple order over strings (and nulls only where Python never compares them).
function cmpList(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) { const c = cmp(a[i], b[i]); if (c) return c; }
  return a.length - b.length;
}
const sorted = (xs) => [...xs].sort(cmp);
const uniqSorted = (xs) => sorted(new Set(xs));

// Python's == over JSON values: True == 1 and False == 0, dicts by members, lists by items.
function pyEq(a, b) {
  if (a === undefined) a = null;
  if (b === undefined) b = null;
  const num = (v) => (v === true ? 1 : v === false ? 0 : v);
  if ((typeof a === "boolean" || isInt(a)) && (typeof b === "boolean" || isInt(b))) return BigInt(num(a)) === BigInt(num(b));
  if (a === null || b === null) return a === b;
  if (isStr(a) || isStr(b)) return a === b;
  if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => pyEq(x, b[i]));
  if (a instanceof PyFloat || b instanceof PyFloat) return a instanceof PyFloat && b instanceof PyFloat && Number(a.text) === Number(b.text);
  if (isObj(a) && isObj(b)) { const ka = keysOf(a), kb = keysOf(b); return ka.length === kb.length && ka.every((k, i) => k === kb[i] && pyEq(a[k], b[k])); }
  return false;
}

// Python's repr() and str() of JSON values, for the reasons the engine writes (`!r`, a list's repr, sort keys).
const NONPRINT = /^[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]$/u;
export function pyReprStr(s) {
  const q = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = q;
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if (ch === q || ch === "\\") out += "\\" + ch;
    else if (ch === "\t") out += "\\t";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (c < 0x20 || c === 0x7f) out += "\\x" + c.toString(16).padStart(2, "0");
    else if (c < 0x7f) out += ch;
    else if (!NONPRINT.test(ch)) out += ch;
    else if (c <= 0xff) out += "\\x" + c.toString(16).padStart(2, "0");
    else if (c <= 0xffff) out += "\\u" + c.toString(16).padStart(4, "0");
    else out += "\\U" + c.toString(16).padStart(8, "0");
  }
  return out + q;
}
export function pyRepr(v) {
  if (v === null || v === undefined) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  if (typeof v === "number" || typeof v === "bigint") return String(v);
  if (isStr(v)) return pyReprStr(v);
  if (v instanceof PyFloat) return v.text;
  if (Array.isArray(v)) return "[" + v.map(pyRepr).join(", ") + "]";
  return "{" + keysOf(v).map((k) => pyReprStr(k) + ": " + pyRepr(v[k])).join(", ") + "}";
}
const pyStr = (v) => (isStr(v) ? v : pyRepr(v));
// How a reason quotes a value: Python's json.dumps(v, ensure_ascii=True, separators=(",", ":"), sort_keys=True).
// Every UTF-16 unit outside space..~ is escaped (\\uXXXX, lowercase), so no interpreter's Unicode tables enter
// the bytes (R-INTERPRETER); keys in code point order, as Python sorts them.
const BS = String.fromCodePoint(0x5c);         // the backslash, named once
const ESC = { '"': BS + '"', [BS]: BS + BS, "\b": BS + "b", "\f": BS + "f", "\n": BS + "n", "\r": BS + "r", "\t": BS + "t" };
export function quoteStr(s) {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const ch = s[i], c = s.charCodeAt(i);       // NOSONAR S7758: a UTF-16 unit, as Python's ensure_ascii escapes it
    if (has(ESC, ch)) out += ESC[ch];
    else if (c < 0x20 || c > 0x7e) out += BS + "u" + c.toString(16).padStart(4, "0");
    else out += ch;
  }
  return out + '"';
}
export function quote(v) {
  if (v === null || v === undefined) return "null";
  if (v === true) return "true";
  if (v === false) return "false";
  if (typeof v === "number" || typeof v === "bigint") return String(v);
  if (isStr(v)) return quoteStr(v);
  if (v instanceof PyFloat) return v.text;
  if (Array.isArray(v)) return "[" + v.map(quote).join(",") + "]";
  return "{" + Object.keys(v).sort(cmp).map((k) => quoteStr(k) + ":" + quote(v[k])).join(",") + "}";
}

// ---------------------------------------------------------------- JSON reading (jcs.loads, and json.loads for a configuration)

// Python's json.loads(text) with object_pairs_hook=_pairs (a repeated member refused), parse_constant and parse_float
// refusing (strict), or with Python's defaults (lenient: the last repeated member wins, floats kept as PyFloat).
// Errors are raised where CPython's scanner raises them: a number or a constant when scanned, a repeated member
// when its object closes, a syntax error where it is met.
function parseJSON(s, strict) {
  let i = 0;
  const n = s.length;
  const bad = () => { throw new DecodeError("JSONDecodeError"); };
  const ws = () => { while (i < n) { const c = s.charCodeAt(i); if (c === 32 || c === 9 || c === 10 || c === 13) i++; else break; } };
  const NUM = /-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?/y;
  const constant = (name) => { if (strict) throw new NotCanonical(`not JSON: ${name}`); return new PyFloat(name); };
  function number() {
    NUM.lastIndex = i;
    const m = NUM.exec(s);
    if (!m) bad();
    i += m[0].length;
    if (m[1] !== undefined || m[2] !== undefined) {
      if (strict) throw new NotCanonical("floats are not admitted");
      return new PyFloat(m[0]);
    }
    const digits = m[0][0] === "-" ? m[0].length - 1 : m[0].length;
    if (digits > MAX_INT_DIGITS)
      throw new PyValueError(`Exceeds the limit (${MAX_INT_DIGITS} digits) for integer string conversion: value has ${digits} digits; use sys.set_int_max_str_digits() to increase the limit`);
    if (digits <= 15) return Number(m[0]);
    const big = BigInt(m[0]);
    return big <= BigInt(MAX_INT) && big >= -BigInt(MAX_INT) ? Number(big) : big;
  }
  function string() {
    i++;
    let out = "";
    let start = i;
    for (;;) {
      if (i >= n) bad();
      const c = s.charCodeAt(i);
      if (c === 34) { out += s.slice(start, i); i++; return out; }
      if (c < 0x20) bad();
      if (c !== 92) { i++; continue; }
      out += s.slice(start, i);
      i++;
      if (i >= n) bad();
      const e = s[i];
      const simple = { '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t" }[e];
      if (simple !== undefined && e !== "u") { out += simple; i++; }
      else if (e === "u") {
        const h = s.slice(i + 1, i + 5);
        if (!/^[0-9a-fA-F]{4}$/.test(h)) bad();
        out += String.fromCharCode(parseInt(h, 16));
        i += 5;
      } else bad();
      start = i;
    }
  }
  function value(depth) {
    if (i >= n) bad();
    const c = s[i];
    if (c === '"') return string();
    if (c === "{") return object(depth);
    if (c === "[") return array(depth);
    if (c === "n" && s.startsWith("null", i)) { i += 4; return null; }
    if (c === "t" && s.startsWith("true", i)) { i += 4; return true; }
    if (c === "f" && s.startsWith("false", i)) { i += 5; return false; }
    if (c === "N" && s.startsWith("NaN", i)) { i += 3; return constant("NaN"); }
    if (c === "I" && s.startsWith("Infinity", i)) { i += 8; return constant("Infinity"); }
    if (c === "-" && s.startsWith("-Infinity", i)) { i += 9; return constant("-Infinity"); }
    return number();
  }
  function object(depth) {
    i++;
    ws();
    const pairs = [];
    if (s[i] === "}") { i++; }
    else {
      for (;;) {
        if (s[i] !== '"') bad();
        const k = string();
        ws();
        if (s[i] !== ":") bad();
        i++;
        ws();
        pairs.push([k, value(depth + 1)]);
        ws();
        if (s[i] === "}") { i++; break; }
        if (s[i] !== ",") bad();
        i++;
        ws();
      }
    }
    const o = dict();
    for (const [k, v] of pairs) {
      if (strict && has(o, k)) throw new NotCanonical(`duplicate member ${quoteStr(k)}`);
      o[k] = v;
    }
    if (!strict) Object.defineProperty(o, ORDER, { value: [...new Set(pairs.map(([k]) => k))] });   // a dict's order, where Python's matters
    return o;
  }
  function array(depth) {
    i++;
    ws();
    const out = [];
    if (s[i] === "]") { i++; return out; }
    for (;;) {
      out.push(value(depth + 1));
      ws();
      if (s[i] === "]") { i++; return out; }
      if (s[i] !== ",") bad();
      i++;
      ws();
    }
  }
  if (s.charCodeAt(0) === 0xfeff) bad();          // Python: "Unexpected UTF-8 BOM"
  ws();
  const v = value(0);
  ws();
  if (i !== n) bad();
  return v;
}

const DEC = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

function depthOf(raw) {
  let depth = 0, best = 0, inStr = false, esc = false;
  for (const b of raw) {
    if (inStr) { if (esc) esc = false; else if (b === 0x5c) esc = true; else if (b === 0x22) inStr = false; }
    else if (b === 0x22) inStr = true;
    else if (b === 0x5b || b === 0x7b) { depth++; if (depth > best) best = depth; }
    else if (b === 0x5d || b === 0x7d) depth--;
  }
  return best;
}

// jcs.loads: parse bytes that MUST be the canonical encoding of what they parse to.
export function loads(raw) {
  let count = 0;
  for (const b of raw) if (b === 0x5b || b === 0x7b) count++;
  if (count > MAX_DEPTH * 4 && depthOf(raw) > MAX_DEPTH) throw new NotCanonical("nested too deep");
  let text, value;
  try { text = DEC.decode(raw); } catch { throw new NotCanonical("not JSON: UnicodeDecodeError"); }
  try { value = parseJSON(text, true); } catch (e) {
    if (e instanceof DecodeError) throw new NotCanonical("not JSON: JSONDecodeError");
    throw e;
  }
  if (canonStr(value) !== text) throw new NotCanonical("bytes are not canonical");
  return value;
}

// json.loads of a configuration or a request: Python's own reader, not the canonical one.
export function loadsLenient(text) {
  try { return parseJSON(text.charCodeAt(0) === 0xfeff ? "﻿" + text.slice(1) : text, false); } catch (e) {
    if (e instanceof DecodeError) throw new SyntaxError("not JSON");
    throw e;
  }
}

// ---------------------------------------------------------------- canonical bytes (jcs.canon)

const isWellFormed = (s) => (typeof s.isWellFormed === "function" ? s.isWellFormed() : !/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/.test(s));
const checkText = (s) => { if (!isWellFormed(s)) throw new NotCanonical("lone surrogate"); };
function scalar(v) {
  if (v === null) return "null";
  if (v === true) return "true";
  if (v === false) return "false";
  if (isInt(v)) {
    if (typeof v === "bigint" ? v > BigInt(MAX_INT) || v < -BigInt(MAX_INT) : v > MAX_INT || v < -MAX_INT) throw new NotCanonical("integer outside ±(2^53-1)");
    return String(v);
  }
  if (isStr(v)) { checkText(v); return JSON.stringify(v); }
  return undefined;
}
// The same traversal as jcs.canon (an explicit stack, keys checked as their object is pushed, last first), so
// that the first refusal is the same one.
export function canonStr(value) {
  const out = [];
  const stack = [["v", value, 0]];
  while (stack.length) {
    const [tag, v, depth] = stack.pop();
    if (tag === "s") { out.push(v); continue; }
    if (depth > MAX_DEPTH) throw new NotCanonical("nested too deep");
    const t = scalar(v);
    if (t !== undefined) { out.push(t); continue; }
    if (Array.isArray(v)) {
      stack.push(["s", "]", 0]);
      for (let i = v.length - 1; i >= 0; i--) { stack.push(["v", v[i], depth + 1]); if (i) stack.push(["s", ",", 0]); }
      stack.push(["s", "[", 0]);
      continue;
    }
    if (!isObj(v)) throw new NotCanonical(`not a JSON value of this domain: ${v instanceof PyFloat ? "float" : typeof v}`);
    const keys = Object.keys(v).sort(utf16);        // RFC 8785 §3.2.3: by UTF-16 code units (jcs.py: utf-16-be)
    stack.push(["s", "}", 0]);
    for (let i = keys.length - 1; i >= 0; i--) {
      checkText(keys[i]);
      stack.push(["v", v[keys[i]], depth + 1], ["s", ":", 0], ["s", JSON.stringify(keys[i]), 0]);
      if (i) stack.push(["s", ",", 0]);
    }
    stack.push(["s", "{", 0]);
  }
  return out.join("");
}
export const canon = (v) => utf8(canonStr(v));

// ---------------------------------------------------------------- shapes (shapes.py) and the record (records.py)

// The code points an actor id may use: those assigned in Unicode 14.0.0 (docs/V3.md §2, `actor`; warrant/shapes.py UNICODE14_ASSIGNED,
// generated by tests/unicode14_table.py). With the format's version fixed, NFC and the categories below read the same under
// the runtime's tables when they are 14.0 or later; older tables are refused when this module loads.
export const UNICODE14_ASSIGNED = "0-377,37a-37f,384-38a,38c-38c,38e-3a1,3a3-52f,531-556,559-58a,58d-58f,591-5c7,5d0-5ea,5ef-5f4,600-70d,70f-74a,74d-7b1,7c0-7fa,7fd-82d,830-83e,840-85b,85e-85e,860-86a,870-88e,890-891,898-983,985-98c,98f-990,993-9a8,9aa-9b0,9b2-9b2,9b6-9b9,9bc-9c4,9c7-9c8,9cb-9ce,9d7-9d7,9dc-9dd,9df-9e3,9e6-9fe,a01-a03,a05-a0a,a0f-a10,a13-a28,a2a-a30,a32-a33,a35-a36,a38-a39,a3c-a3c,a3e-a42,a47-a48,a4b-a4d,a51-a51,a59-a5c,a5e-a5e,a66-a76,a81-a83,a85-a8d,a8f-a91,a93-aa8,aaa-ab0,ab2-ab3,ab5-ab9,abc-ac5,ac7-ac9,acb-acd,ad0-ad0,ae0-ae3,ae6-af1,af9-aff,b01-b03,b05-b0c,b0f-b10,b13-b28,b2a-b30,b32-b33,b35-b39,b3c-b44,b47-b48,b4b-b4d,b55-b57,b5c-b5d,b5f-b63,b66-b77,b82-b83,b85-b8a,b8e-b90,b92-b95,b99-b9a,b9c-b9c,b9e-b9f,ba3-ba4,ba8-baa,bae-bb9,bbe-bc2,bc6-bc8,bca-bcd,bd0-bd0,bd7-bd7,be6-bfa,c00-c0c,c0e-c10,c12-c28,c2a-c39,c3c-c44,c46-c48,c4a-c4d,c55-c56,c58-c5a,c5d-c5d,c60-c63,c66-c6f,c77-c8c,c8e-c90,c92-ca8,caa-cb3,cb5-cb9,cbc-cc4,cc6-cc8,cca-ccd,cd5-cd6,cdd-cde,ce0-ce3,ce6-cef,cf1-cf2,d00-d0c,d0e-d10,d12-d44,d46-d48,d4a-d4f,d54-d63,d66-d7f,d81-d83,d85-d96,d9a-db1,db3-dbb,dbd-dbd,dc0-dc6,dca-dca,dcf-dd4,dd6-dd6,dd8-ddf,de6-def,df2-df4,e01-e3a,e3f-e5b,e81-e82,e84-e84,e86-e8a,e8c-ea3,ea5-ea5,ea7-ebd,ec0-ec4,ec6-ec6,ec8-ecd,ed0-ed9,edc-edf,f00-f47,f49-f6c,f71-f97,f99-fbc,fbe-fcc,fce-fda,1000-10c5,10c7-10c7,10cd-10cd,10d0-1248,124a-124d,1250-1256,1258-1258,125a-125d,1260-1288,128a-128d,1290-12b0,12b2-12b5,12b8-12be,12c0-12c0,12c2-12c5,12c8-12d6,12d8-1310,1312-1315,1318-135a,135d-137c,1380-1399,13a0-13f5,13f8-13fd,1400-169c,16a0-16f8,1700-1715,171f-1736,1740-1753,1760-176c,176e-1770,1772-1773,1780-17dd,17e0-17e9,17f0-17f9,1800-1819,1820-1878,1880-18aa,18b0-18f5,1900-191e,1920-192b,1930-193b,1940-1940,1944-196d,1970-1974,1980-19ab,19b0-19c9,19d0-19da,19de-1a1b,1a1e-1a5e,1a60-1a7c,1a7f-1a89,1a90-1a99,1aa0-1aad,1ab0-1ace,1b00-1b4c,1b50-1b7e,1b80-1bf3,1bfc-1c37,1c3b-1c49,1c4d-1c88,1c90-1cba,1cbd-1cc7,1cd0-1cfa,1d00-1f15,1f18-1f1d,1f20-1f45,1f48-1f4d,1f50-1f57,1f59-1f59,1f5b-1f5b,1f5d-1f5d,1f5f-1f7d,1f80-1fb4,1fb6-1fc4,1fc6-1fd3,1fd6-1fdb,1fdd-1fef,1ff2-1ff4,1ff6-1ffe,2000-2064,2066-2071,2074-208e,2090-209c,20a0-20c0,20d0-20f0,2100-218b,2190-2426,2440-244a,2460-2b73,2b76-2b95,2b97-2cf3,2cf9-2d25,2d27-2d27,2d2d-2d2d,2d30-2d67,2d6f-2d70,2d7f-2d96,2da0-2da6,2da8-2dae,2db0-2db6,2db8-2dbe,2dc0-2dc6,2dc8-2dce,2dd0-2dd6,2dd8-2dde,2de0-2e5d,2e80-2e99,2e9b-2ef3,2f00-2fd5,2ff0-2ffb,3000-303f,3041-3096,3099-30ff,3105-312f,3131-318e,3190-31e3,31f0-321e,3220-a48c,a490-a4c6,a4d0-a62b,a640-a6f7,a700-a7ca,a7d0-a7d1,a7d3-a7d3,a7d5-a7d9,a7f2-a82c,a830-a839,a840-a877,a880-a8c5,a8ce-a8d9,a8e0-a953,a95f-a97c,a980-a9cd,a9cf-a9d9,a9de-a9fe,aa00-aa36,aa40-aa4d,aa50-aa59,aa5c-aac2,aadb-aaf6,ab01-ab06,ab09-ab0e,ab11-ab16,ab20-ab26,ab28-ab2e,ab30-ab6b,ab70-abed,abf0-abf9,ac00-d7a3,d7b0-d7c6,d7cb-d7fb,d800-fa6d,fa70-fad9,fb00-fb06,fb13-fb17,fb1d-fb36,fb38-fb3c,fb3e-fb3e,fb40-fb41,fb43-fb44,fb46-fbc2,fbd3-fd8f,fd92-fdc7,fdcf-fdcf,fdf0-fe19,fe20-fe52,fe54-fe66,fe68-fe6b,fe70-fe74,fe76-fefc,feff-feff,ff01-ffbe,ffc2-ffc7,ffca-ffcf,ffd2-ffd7,ffda-ffdc,ffe0-ffe6,ffe8-ffee,fff9-fffd,10000-1000b,1000d-10026,10028-1003a,1003c-1003d,1003f-1004d,10050-1005d,10080-100fa,10100-10102,10107-10133,10137-1018e,10190-1019c,101a0-101a0,101d0-101fd,10280-1029c,102a0-102d0,102e0-102fb,10300-10323,1032d-1034a,10350-1037a,10380-1039d,1039f-103c3,103c8-103d5,10400-1049d,104a0-104a9,104b0-104d3,104d8-104fb,10500-10527,10530-10563,1056f-1057a,1057c-1058a,1058c-10592,10594-10595,10597-105a1,105a3-105b1,105b3-105b9,105bb-105bc,10600-10736,10740-10755,10760-10767,10780-10785,10787-107b0,107b2-107ba,10800-10805,10808-10808,1080a-10835,10837-10838,1083c-1083c,1083f-10855,10857-1089e,108a7-108af,108e0-108f2,108f4-108f5,108fb-1091b,1091f-10939,1093f-1093f,10980-109b7,109bc-109cf,109d2-10a03,10a05-10a06,10a0c-10a13,10a15-10a17,10a19-10a35,10a38-10a3a,10a3f-10a48,10a50-10a58,10a60-10a9f,10ac0-10ae6,10aeb-10af6,10b00-10b35,10b39-10b55,10b58-10b72,10b78-10b91,10b99-10b9c,10ba9-10baf,10c00-10c48,10c80-10cb2,10cc0-10cf2,10cfa-10d27,10d30-10d39,10e60-10e7e,10e80-10ea9,10eab-10ead,10eb0-10eb1,10f00-10f27,10f30-10f59,10f70-10f89,10fb0-10fcb,10fe0-10ff6,11000-1104d,11052-11075,1107f-110c2,110cd-110cd,110d0-110e8,110f0-110f9,11100-11134,11136-11147,11150-11176,11180-111df,111e1-111f4,11200-11211,11213-1123e,11280-11286,11288-11288,1128a-1128d,1128f-1129d,1129f-112a9,112b0-112ea,112f0-112f9,11300-11303,11305-1130c,1130f-11310,11313-11328,1132a-11330,11332-11333,11335-11339,1133b-11344,11347-11348,1134b-1134d,11350-11350,11357-11357,1135d-11363,11366-1136c,11370-11374,11400-1145b,1145d-11461,11480-114c7,114d0-114d9,11580-115b5,115b8-115dd,11600-11644,11650-11659,11660-1166c,11680-116b9,116c0-116c9,11700-1171a,1171d-1172b,11730-11746,11800-1183b,118a0-118f2,118ff-11906,11909-11909,1190c-11913,11915-11916,11918-11935,11937-11938,1193b-11946,11950-11959,119a0-119a7,119aa-119d7,119da-119e4,11a00-11a47,11a50-11aa2,11ab0-11af8,11c00-11c08,11c0a-11c36,11c38-11c45,11c50-11c6c,11c70-11c8f,11c92-11ca7,11ca9-11cb6,11d00-11d06,11d08-11d09,11d0b-11d36,11d3a-11d3a,11d3c-11d3d,11d3f-11d47,11d50-11d59,11d60-11d65,11d67-11d68,11d6a-11d8e,11d90-11d91,11d93-11d98,11da0-11da9,11ee0-11ef8,11fb0-11fb0,11fc0-11ff1,11fff-12399,12400-1246e,12470-12474,12480-12543,12f90-12ff2,13000-1342e,13430-13438,14400-14646,16800-16a38,16a40-16a5e,16a60-16a69,16a6e-16abe,16ac0-16ac9,16ad0-16aed,16af0-16af5,16b00-16b45,16b50-16b59,16b5b-16b61,16b63-16b77,16b7d-16b8f,16e40-16e9a,16f00-16f4a,16f4f-16f87,16f8f-16f9f,16fe0-16fe4,16ff0-16ff1,17000-187f7,18800-18cd5,18d00-18d08,1aff0-1aff3,1aff5-1affb,1affd-1affe,1b000-1b122,1b150-1b152,1b164-1b167,1b170-1b2fb,1bc00-1bc6a,1bc70-1bc7c,1bc80-1bc88,1bc90-1bc99,1bc9c-1bca3,1cf00-1cf2d,1cf30-1cf46,1cf50-1cfc3,1d000-1d0f5,1d100-1d126,1d129-1d1ea,1d200-1d245,1d2e0-1d2f3,1d300-1d356,1d360-1d378,1d400-1d454,1d456-1d49c,1d49e-1d49f,1d4a2-1d4a2,1d4a5-1d4a6,1d4a9-1d4ac,1d4ae-1d4b9,1d4bb-1d4bb,1d4bd-1d4c3,1d4c5-1d505,1d507-1d50a,1d50d-1d514,1d516-1d51c,1d51e-1d539,1d53b-1d53e,1d540-1d544,1d546-1d546,1d54a-1d550,1d552-1d6a5,1d6a8-1d7cb,1d7ce-1da8b,1da9b-1da9f,1daa1-1daaf,1df00-1df1e,1e000-1e006,1e008-1e018,1e01b-1e021,1e023-1e024,1e026-1e02a,1e100-1e12c,1e130-1e13d,1e140-1e149,1e14e-1e14f,1e290-1e2ae,1e2c0-1e2f9,1e2ff-1e2ff,1e7e0-1e7e6,1e7e8-1e7eb,1e7ed-1e7ee,1e7f0-1e7fe,1e800-1e8c4,1e8c7-1e8d6,1e900-1e94b,1e950-1e959,1e95e-1e95f,1ec71-1ecb4,1ed01-1ed3d,1ee00-1ee03,1ee05-1ee1f,1ee21-1ee22,1ee24-1ee24,1ee27-1ee27,1ee29-1ee32,1ee34-1ee37,1ee39-1ee39,1ee3b-1ee3b,1ee42-1ee42,1ee47-1ee47,1ee49-1ee49,1ee4b-1ee4b,1ee4d-1ee4f,1ee51-1ee52,1ee54-1ee54,1ee57-1ee57,1ee59-1ee59,1ee5b-1ee5b,1ee5d-1ee5d,1ee5f-1ee5f,1ee61-1ee62,1ee64-1ee64,1ee67-1ee6a,1ee6c-1ee72,1ee74-1ee77,1ee79-1ee7c,1ee7e-1ee7e,1ee80-1ee89,1ee8b-1ee9b,1eea1-1eea3,1eea5-1eea9,1eeab-1eebb,1eef0-1eef1,1f000-1f02b,1f030-1f093,1f0a0-1f0ae,1f0b1-1f0bf,1f0c1-1f0cf,1f0d1-1f0f5,1f100-1f1ad,1f1e6-1f202,1f210-1f23b,1f240-1f248,1f250-1f251,1f260-1f265,1f300-1f6d7,1f6dd-1f6ec,1f6f0-1f6fc,1f700-1f773,1f780-1f7d8,1f7e0-1f7eb,1f7f0-1f7f0,1f800-1f80b,1f810-1f847,1f850-1f859,1f860-1f887,1f890-1f8ad,1f8b0-1f8b1,1f900-1fa53,1fa60-1fa6d,1fa70-1fa74,1fa78-1fa7c,1fa80-1fa86,1fa90-1faac,1fab0-1faba,1fac0-1fac5,1fad0-1fad9,1fae0-1fae7,1faf0-1faf6,1fb00-1fb92,1fb94-1fbca,1fbf0-1fbf9,20000-2a6df,2a700-2b738,2b740-2b81d,2b820-2cea1,2ceb0-2ebe0,2f800-2fa1d,30000-3134a,e0001-e0001,e0020-e007f,e0100-e01ef,f0000-ffffd,100000-10fffd";
const U14 = UNICODE14_ASSIGNED.split(",").map((r) => r.split("-").map((x) => parseInt(x, 16)));
if (/\p{Cn}/u.test("\u0870")) throw new Error("warrant needs Unicode tables of version 14.0 or later (U+0870 is unassigned here)");
function assigned14(cp) {
  let lo = 0, hi = U14.length - 1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (cp < U14[m][0]) hi = m - 1; else if (cp > U14[m][1]) lo = m + 1; else return true;
  }
  return false;
}
// Cc and the white space outside it (Zs, Zl, Zp) as Unicode 14.0.0 has them, carried as warrant/shapes.py carries them
// (CONTROL14, SPACE14), not read from the runtime's tables (Codex 4fba55d3).
const SPACE14 = new Set([0x20, 0xa0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000]);
const control14 = (cp) => cp <= 0x1f || (cp >= 0x7f && cp <= 0x9f);
export function isActor(v) {
  if (!(isStr(v) && v.length > 0 && cpLen(v) <= 200)) return false;
  for (const c of v) if (!assigned14(c.codePointAt(0))) return false;
  if (v.normalize("NFC") !== v) return false;
  for (const c of v) if (control14(c.codePointAt(0))) return false;
  const cps = [...v];
  return !(SPACE14.has(cps[0].codePointAt(0)) || SPACE14.has(cps[cps.length - 1].codePointAt(0)));
}
function isList(v, item, sortedToo = false) {
  if (!Array.isArray(v) || !v.every((x) => item(x))) return false;
  if (!sortedToo) return true;
  for (let k = 1; k < v.length; k++) if (cmp(v[k - 1], v[k]) >= 0) return false;
  return true;
}
const sameKeys = (o, names) => { const k = Object.keys(o); return k.length === names.length && names.every((x) => has(o, x)); };

function guardProblem(g) {
  if (!(isObj(g) && sameKeys(g, GUARD))) return "a guard has exactly ['quorum', 'roles', 'match', 'requires']";
  if (!(isInt(g.quorum) && g.quorum >= 0 && isList(g.roles, isActor, true) && isObj(g.match) && isList(g.requires, hex64, true)))
    return "guard: quorum >= 0, roles a sorted list of names, match an object, requires sorted ids";
  return null;
}
const need = (ok, why) => { if (!ok) throw new Invalid(why); };

function checkRecord(r) {
  need(isObj(r) && sameKeys(r, MEMBERS), "a record has exactly ['warrant', 'kind', 'actor', 'at', 'prev', 'schema', 'lineage', 'refs', 'guard', 'body']");
  need(r.warrant === VERSION && KINDS.includes(r.kind), 'warrant must be "3" and kind one of schema/entity/attest/challenge');
  need(isActor(r.actor), "actor is not an actor id");
  need(isInt(r.at) && r.at >= 0, "at is a non-negative integer");
  need(r.prev === null || hex64(r.prev), "prev is null or a record id");
  need(r.lineage === null || hex64(r.lineage), "lineage is null or a record id");
  need(isList(r.refs, hex64, true), "refs is a sorted list of distinct hex64");
  need(isObj(r.body) && canon(r.body).length <= BODY_MAX, `body is an object of at most ${BODY_MAX} bytes`);
  need(r.guard === null || guardProblem(r.guard) === null, String(guardProblem(r.guard)));
  if (r.kind === "schema") need(r.schema === null, "a schema record has no schema");
  else need(r.schema === null || (isStr(r.schema) && r.schema.length > 0 && cpLen(r.schema) <= 100), "schema is a name");
  if (r.kind === "entity") need(r.schema !== null, "an entity names its schema");
  if (r.kind === "attest" || r.kind === "challenge")
    need(hex64(own(r.body, "target")) && r.refs.includes(r.body.target) && r.lineage === null && r.guard === null,
      "an attest or challenge names body.target, in refs, and has no lineage or guard");
}

const namedKey = (r) => (r.kind === "challenge" && r.actor.startsWith("key:") ? r.actor.slice(4) : null);

function typeOk(t, v) {
  if (t.endsWith("?")) { if (v === null) return true; t = t.slice(0, -1); }
  switch (t) {
    case "str": return isStr(v);
    case "int": return isInt(v);
    case "bool": return typeof v === "boolean";
    case "strs": return isList(v, isStr);
    case "ref": return hex64(v);
    case "refs": return isList(v, hex64);
    case "obj": return true;
    default: return false;
  }
}
const rstripQ = (t) => t.replace(/\?+$/, "");
function bodyRefs(fields, body) {
  const out = new Set();
  for (const k of keysOf(fields)) {
    const t = rstripQ(fields[k]), v = has(body, k) ? body[k] : null;
    if (t === "ref" && v !== null) out.add(v);
    else if (t === "refs" && v !== null) for (const x of v) out.add(x);
  }
  return out;
}

// ---------------------------------------------------------------- Ed25519 (keys.py: the weak keys, the key id)

const P = (1n << 255n) - 19n;
const WEAK = new Set([
  "0100000000000000000000000000000000000000000000000000000000000000", "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
  "0000000000000000000000000000000000000000000000000000000000000080", "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
  "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f", "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
  "0000000000000000000000000000000000000000000000000000000000000000", "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
  "0100000000000000000000000000000000000000000000000000000000000080", "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
]);
function weakKey(pubHex) {
  if (WEAK.has(pubHex)) return true;
  let x = 0n;
  const b = hexBytes(pubHex);
  for (let i = 31; i >= 0; i--) x = (x << 8n) | BigInt(b[i]);
  return (x & ((1n << 255n) - 1n)) >= P;
}

// keys.verify: a valid Ed25519 signature of `msg` by a strong key (shapes first, the weak keys refused).
export async function verifySig(backend, pubHex, sigHex, msg) {
  if (!(hex64(pubHex) && hex128(sigHex)) || weakKey(pubHex)) return false;
  return Boolean(await backend.verify(pubHex, sigHex, msg));
}

// ---------------------------------------------------------------- backends: SHA-256 and Ed25519 from the platform

export async function nodeBackend() {
  const crypto = await import("node:crypto");
  const keys = new Map();
  return {
    name: `node ${process.version}; openssl ${process.versions.openssl}`,
    sha256: (bytes) => crypto.createHash("sha256").update(bytes).digest("hex"),
    verify(pubHex, sigHex, msg) {
      try {
        let k = keys.get(pubHex);
        if (!k) {
          k = crypto.createPublicKey({ key: { kty: "OKP", crv: "Ed25519", x: Buffer.from(pubHex, "hex").toString("base64url") }, format: "jwk" });
          keys.set(pubHex, k);
        }
        return crypto.verify(null, msg, k, Buffer.from(sigHex, "hex"));
      } catch { return false; }
    },
  };
}

// The same two answers through WebCrypto (a browser, or node's globalThis.crypto.subtle).
export function webBackend(subtle = globalThis.crypto.subtle, name = "webcrypto") {
  const keys = new Map();
  return {
    name,
    async sha256(bytes) { return bytesHex(new Uint8Array(await subtle.digest("SHA-256", bytes))); },
    async verify(pubHex, sigHex, msg) {
      try {
        let k = keys.get(pubHex);
        if (!k) { k = await subtle.importKey("raw", hexBytes(pubHex), { name: "Ed25519" }, false, ["verify"]); keys.set(pubHex, k); }
        return await subtle.verify({ name: "Ed25519" }, k, hexBytes(sigHex), msg);
      } catch { return false; }
    },
  };
}

// ---------------------------------------------------------------- phase 1: the snapshot and every digest and signature

const lineError = (e) => e instanceof NotCanonical || e instanceof Invalid || e instanceof PyValueError;

// store.Snapshot: {id: [distinct lines]}, blobs, what was rejected, the digest; refused beyond LIMITS.
async function snapshotOf(lines, blobs, backend) {
  const H = (b) => backend.sha256(b);
  const rejected = new Map(), byId = new Map(), seen = new Map(), lineId = new Map();
  for (const raw of lines) {
    const k = bkey(raw);
    if (seen.has(k)) continue;
    seen.set(k, raw);
    let env;
    try {
      if (raw.length > LINE_MAX) throw new Invalid(`line longer than ${LINE_MAX} bytes`);
      let end = raw.length;
      while (end > 0 && raw[end - 1] === 0x0a) end--;
      env = loads(raw.subarray(0, end));
      need(isObj(env) && sameKeys(env, ["record", "sig"]), "a line is {record, sig}");
      checkRecord(env.record);
      const sig = env.sig;
      need(sig === null || (isObj(sig) && sameKeys(sig, ["key", "ed25519"]) && hex64(sig.key) && hex128(sig.ed25519)), "sig is null or {key, ed25519}");
    } catch (e) {
      if (!lineError(e)) throw e;
      rejected.set(await H(raw), `line: ${e.message}`);
      continue;
    }
    const id = await H(canon(env.record));
    lineId.set(k, id);
    if (!byId.has(id)) byId.set(id, []);
    byId.get(id).push(env);
  }
  const distinct = [...seen.keys()];
  let canonical = rejected.size === 0 && distinct.length === lines.length;
  if (canonical) {
    const order = lines.map(bkey);
    for (let i = 1; i < order.length && canonical; i++) {
      const a = lineId.get(order[i - 1]), b = lineId.get(order[i]);
      canonical = a < b || (a === b && order[i - 1] < order[i]);
    }
  }
  const names = sorted(blobs.keys());
  const listing = [];
  for (const k of [...distinct].sort(byteOrder)) listing.push(seen.get(k));     // store.py: sorted(seen), raw lines as bytes
  for (const h of names) listing.push(utf8(`b ${h} ${await H(blobs.get(h))}`));
  const parts = [];
  listing.forEach((x, i) => { if (i) parts.push(utf8("\n")); parts.push(x); });
  const digest = await H(concat(parts));
  let bytes = 0;
  for (const raw of seen.values()) bytes += raw.length;
  for (const b of blobs.values()) bytes += b.length;
  if (byId.size > LIMITS.records || bytes > LIMITS.bytes) throw new Refused(`store beyond limits ${LIMITS_REPR}`);
  return { lines: byId, blobs, rejected, canonical, digest, raw: [...seen.values()] };
}

function trustProblem(t) {
  const ok = isObj(t) && sameKeys(t, ["warrant", "keys"]) && t.warrant === "trust/3" && isObj(t.keys)
    && Object.keys(t.keys).every((a) => isActor(a) && isList(t.keys[a], hex64, true));
  return ok ? null : "trust is {warrant: trust/3, keys: {actor: [sorted public hex]}}";
}
function profileProblem(p) {
  const q = isObj(p) && has(p, "quorum") ? p.quorum : dict();
  const ok = isObj(p) && has(p, "warrant") && has(p, "roles") && Object.keys(p).every((k) => ["warrant", "roles", "quorum"].includes(k))
    && p.warrant === "profile/3" && isObj(p.roles) && Object.keys(p.roles).every((k) => isList(p.roles[k], isActor, true))
    && isObj(q) && Object.keys(q).every((k) => isInt(q[k]) && typeof q[k] !== "boolean" && q[k] >= 1);
  return ok ? null : "profile is {warrant: profile/3, roles: {role: [sorted actors]}, quorum?: {role: k >= 1}}";
}

// A digest computed in phase 1 whose canonical bytes may be refused: the refusal is raised where Python raises it.
async function docIdOrError(v, backend) {
  try { return { id: await backend.sha256(canon(v)) }; } catch (e) { if (e instanceof NotCanonical) return { error: e }; throw e; }
}

// input: {lines: [Uint8Array], blobs: Map<name, Uint8Array>, trust, profile, as_of: int|null, code: hex}
export async function prepare(input, backend) {
  const snap = await snapshotOf(input.lines, input.blobs, backend);
  const { trust, profile } = input;
  let asOf = input.as_of ?? null;
  if (asOf === null) { asOf = 0; let any = false; for (const envs of snap.lines.values()) { const at = envs[0].record.at; if (!any || at > asOf) asOf = at; any = true; } }
  const verified = new Set(), keyIds = new Map();
  if (trustProblem(trust) === null) {
    const keyId = async (pub) => { if (!keyIds.has(pub)) keyIds.set(pub, await backend.sha256(hexBytes(pub))); return keyIds.get(pub); };
    for (const [id, envs] of snap.lines) {
      const r = envs[0].record;
      if (r.at > asOf) continue;
      const keys = [...(own(trust.keys, r.actor) || [])];
      if (namedKey(r) !== null) keys.push(namedKey(r));
      const msg = concat([utf8(SIG_DOMAIN), hexBytes(id)]);
      for (const e of envs) {
        if (e.sig === null) continue;
        for (const pub of keys) {
          if (await verifySig(backend, pub, e.sig.ed25519, msg) && e.sig.key === await keyId(pub)) verified.add(`${id} ${e.sig.ed25519} ${e.sig.key} ${pub}`);
        }
      }
    }
  }
  const trustId = await docIdOrError(trust, backend), profileId = await docIdOrError(profile, backend);
  let assessment = null;
  if (trustId.id && profileId.id) {
    const ops = dict();
    Object.assign(ops, { snapshot: snap.digest, trust: trustId.id, profile: profileId.id, as_of: asOf, code: input.code });
    assessment = await docIdOrError(ops, backend);
  }
  return { snap, trust, profile, asOf, verified, trustId, profileId, assessment, code: input.code };
}

// ---------------------------------------------------------------- phase 2: the assessment (engine.py), pure and synchronous

function mapRows(doc) {
  const rows = isObj(doc) && has(doc, "map") ? doc.map : null;
  return Array.isArray(rows) && rows.every((x) => Array.isArray(x) && x.length === 3 && hex64(x[0])) ? rows : null;
}

function schemaProblem(b) {
  const isStates = isObj(b) && isObj(b.states);
  const ok = isObj(b) && SCHEMA_MEMBERS.every((k) => has(b, k)) && Object.keys(b).every((k) => SCHEMA_MEMBERS.includes(k) || k === "pinned")
    && isStr(b.name) && b.name.length > 0 && cpLen(b.name) <= 100 && b.name !== MIGRATION
    && isObj(b.fields) && Object.values(b.fields).every((t) => isStr(t) && TYPES.includes(rstripQ(t)))
    && (b.states === null || (isStates && own(b.fields, "state") === "str" && Object.values(b.states).every((g) => g === null || guardProblem(g) === null)))
    // A closed item that is no string is not a state, so the body is not a schema body (engine.py, since S12).
    && isList(b.closed, (s) => isStates && isStr(s) && has(b.states, s), true)
    && isObj(b.successors) && Object.keys(b.successors).every((st) => isStates && has(b.states, st) && isList(b.successors[st], isActor, true))
    && (!has(b, "pinned") || (isStr(b.pinned) && ["obj", "obj?"].includes(own(b.fields, b.pinned))));
  return ok ? null : "a schema body is {name, fields: {member: type}, states: {state: guard|null}|null, closed, successors: {state: [roles]}, pinned?: a member of type obj}";
}

const NOWHERE = Symbol("missing");
const getOr = (o, k, d) => (has(o, k) ? o[k] : d);

function weaker(g, req) {
  if (g === null) return true;
  return g.quorum < req.quorum || (req.quorum > 0 && !g.roles.every((x) => req.roles.includes(x)))
    || keysOf(req.match).some((k) => getOr(g.match, k, NOWHERE) === NOWHERE || !pyEq(g.match[k], req.match[k]))
    || !req.requires.every((x) => g.requires.includes(x));
}

function bodyProblem(r, s) {
  const b = r.body;
  let f = s.fields;
  if ((r.kind === "attest" || r.kind === "challenge") && !has(f, "target")) { f = Object.assign(dict(), f); f.target = "ref"; }
  const extra = keysOf(b).filter((k) => !has(f, k)), missing = keysOf(f).filter((k) => !f[k].endsWith("?") && !has(b, k));
  if (extra.length || missing.length) return `members ${quote(sorted(extra))} are not in ${s.name}, or ${quote(sorted(missing))} are missing`;
  const badTypes = keysOf(b).filter((k) => !typeOk(f[k], b[k]));
  if (badTypes.length) return `members ${quote(badTypes)} do not have their types in ${s.name}`;
  for (const x of bodyRefs(f, b)) if (!r.refs.includes(x)) return "a reference in the body is not in refs";
  if (r.kind !== "entity") return null;
  const state = getOr(b, "state", null);
  if (!isObj(s.states) || !(isStr(state) && has(s.states, state))) return `state ${quote(state)} is not a state of ${s.name}`;
  const req = s.states[state];
  if (req !== null && weaker(r.guard, req)) return `its guard is weaker than ${s.name}'s for state ${quote(state)}`;
  return null;
}

function settle(rt, lin) {
  const forks = [...lin.succ].filter(([, c]) => c.length > 1).sort((a, b) => cmp(a[0], b[0]));
  lin.forks = forks.map(([p, c]) => [p, c]);
  if (forks.length) { lin.path = []; lin.leaf = null; return; }
  const path = [rt];
  while (lin.succ.has(path[path.length - 1])) path.push(lin.succ.get(path[path.length - 1])[0]);
  lin.path = path;
  lin.leaf = path[path.length - 1];
}

class View {
  constructor(prep) {
    for (const why of [trustProblem(prep.trust), profileProblem(prep.profile)]) if (why) throw new Invalid(why);
    this.prep = prep;
    this.snap = prep.snap;
    this.trust = prep.trust;
    this.profile = prep.profile;
    this.asOf = prep.asOf;
    this.authentic();
    this.problems = [];
    this.lineageDepth();
    this.vouch();
    this.chains();
    this.indexAttests();
    this.schemasOf();
    this.bodies();
    this.pins();
    this.indexAttests();
    const ents = new Set([...this.recs].filter(([, r]) => r.kind === "entity").map(([i]) => i));
    [this.rootOf, this.lineages] = this.lineagesOf(ents, (r, root) => this.maySucceed(r, root));
    this.requiresDepth();
    [this.guards, this.effectiveOf] = this.resolve();
  }

  authentic() {
    this.recs = new Map(); this.basis = new Map(); this.bad = new Map(); this.later = 0;
    for (const [i, envs] of this.snap.lines) {
      const r = envs[0].record;
      if (r.at > this.asOf) { this.later++; continue; }
      const keys = [...(own(this.trust.keys, r.actor) || [])];
      if (namedKey(r) !== null) keys.push(namedKey(r));
      const sigs = envs.filter((e) => e.sig !== null).map((e) => e.sig);
      if (sigs.some((s) => keys.some((k) => this.prep.verified.has(`${i} ${s.ed25519} ${s.key} ${k}`)))) { this.recs.set(i, r); this.basis.set(i, "SIGNED"); }
      else if (envs.some((e) => e.sig === null)) { this.recs.set(i, r); this.basis.set(i, "UNSIGNED"); }
      else this.bad.set(i, "BAD_SIGNATURE: no signature verifies under a key the trust binds to the actor, or a challenge's own");
    }
  }

  sortedRecs() { return [...this.recs].sort((a, b) => cmp(a[0], b[0])); }
  holds(actor, roles) { return roles.some((x) => (own(this.profile.roles, x) || []).includes(actor)); }
  problem(code, rid, detail = "") { this.problems.push([code, rid, detail]); }
  drop(i, why) { this.bad.set(i, why); this.recs.delete(i); this.basis.delete(i); }

  jsonBlob(h) {
    const b = this.snap.blobs.get(h);
    if (b === undefined) return null;
    // An integer of more than 4300 digits makes a map blob no map (Python: ValueError from json.loads, caught).
    try { return loads(b); } catch (e) { if (lineError(e)) return null; throw e; }
  }

  vouch() {
    const vouched = new Map();
    for (const [i, r] of this.sortedRecs()) {
      if (!(r.kind === "attest" && r.schema === MIGRATION && this.basis.get(i) === "SIGNED" && this.holds(r.actor, ["migrator"]))) continue;
      const rows = mapRows(this.jsonBlob(r.body.target));
      if (rows === null) { this.problem("MIGRATION_MAP", i, "its target is not a map blob in the view"); continue; }
      for (const row of rows) if (!vouched.has(row[0])) vouched.set(row[0], i);
    }
    this.vouchedBy = new Map();
    for (const i of [...this.basis].filter(([, b]) => b === "UNSIGNED").map(([i]) => i)) {
      const by = vouched.get(i);
      if (by !== undefined) { this.basis.set(i, "MIGRATED"); this.vouchedBy.set(i, by); }
      else this.drop(i, "UNSIGNED: no signature, and no migration the profile accepts lists it");
    }
  }

  chains() {
    const signed = new Map([...this.recs].filter(([i]) => this.basis.get(i) === "SIGNED"));
    const byPrev = new Map();
    this.unanchored = [];
    for (const [i, r] of [...signed].sort((a, b) => cmp(a[0], b[0]))) {
      const key = JSON.stringify([r.actor, r.prev]);
      if (!byPrev.has(key)) byPrev.set(key, { actor: r.actor, prev: r.prev, ids: [] });
      byPrev.get(key).ids.push(i);
      const p = r.prev ? signed.get(r.prev) : undefined;
      if (r.prev !== null && !(p && p.actor === r.actor && p.at <= r.at)) this.unanchored.push(i);
    }
    this.chainForks = [...byPrev.values()].sort((a, b) => cmp(a.actor, b.actor) || cmp(a.prev ?? "", b.prev ?? ""))
      .filter((x) => x.ids.length > 1).map((x) => [x.actor, x.prev, x.ids]);
  }

  indexAttests() {
    this.attests = new Map();
    for (const [i, r] of [...this.recs].sort((a, b) => (a[1].at - b[1].at) || cmp(a[0], b[0]))) {
      if (r.kind !== "attest") continue;
      if (!this.attests.has(r.body.target)) this.attests.set(r.body.target, []);
      this.attests.get(r.body.target).push(i);
    }
  }

  quorum(role) { const q = has(this.profile, "quorum") ? this.profile.quorum : dict(); return has(q, role) ? q[role] : 1; }

  backers(i) {
    const out = new Set();
    for (const a of this.attests.get(i) || []) {
      const x = this.recs.get(a);
      if (x.schema === null && getOr(x.body, "verdict", null) === "accept") out.add(x.actor);
    }
    out.add(this.recs.get(i).actor);
    return sorted([...out].filter((a) => this.holds(a, [SCHEMA_AUTHOR])));
  }

  schemasOf() {
    this.schemas = new Map(); this.pending = [];
    const cand = new Set();
    for (const [i, r] of this.sortedRecs()) {
      if (r.kind !== "schema") continue;
      const why = schemaProblem(r.body);
      if (why) this.problem("SCHEMA_NOT_COUNTED", i, why);
      else if (this.backers(i).length < this.quorum(SCHEMA_AUTHOR)) this.pending.push(i);
      else cand.add(i);
    }
    const [, lins] = this.lineagesOf(cand, (r, root) => r.actor === root.actor);
    const byName = new Map();
    for (const [root, lin] of lins) {
      if (lin.leaf === null) { this.problem("SCHEMA_CONFLICT", root, "its lineage forks"); continue; }
      const name = this.recs.get(lin.leaf).body.name;
      if (!byName.has(name)) byName.set(name, []);
      byName.get(name).push(lin.leaf);
    }
    for (const name of sorted(byName.keys())) {
      const leaves = byName.get(name);
      if (leaves.length > 1) this.problem("SCHEMA_CONFLICT", name, `${leaves.length} schema lineages name it`);
      else this.schemas.set(name, { id: leaves[0], ...this.recs.get(leaves[0]).body });
    }
  }

  pins() {
    const bad = new Map();
    for (const [i, r] of this.sortedRecs()) {
      const s = r.kind === "entity" ? this.schemas.get(r.schema) : undefined;
      if (s === undefined || !has(s, "pinned")) continue;     // by presence: "" is a member name too
      let root = r;
      const seen = new Set([i]);
      while (root.lineage !== null && this.recs.has(root.lineage) && !seen.has(root.lineage)) { seen.add(root.lineage); root = this.recs.get(root.lineage); }
      const pin = getOr(root.body, s.pinned, null);
      const match = (r.guard || { match: dict() }).match;
      if (pin !== null && !isObj(pin)) bad.set(i, `the root's ${s.pinned} is not an object`);
      else if (pin !== null && Object.keys(pin).length && s.closed.includes(getOr(r.body, "state", null))
        && keysOf(pin).some((k) => getOr(match, k, NOWHERE) === NOWHERE || !pyEq(match[k], pin[k])))
        bad.set(i, `its guard matches less than its root's ${s.pinned}`);
      else if (pin !== null && Object.keys(pin).length && s.closed.includes(getOr(r.body, "state", null)) && r.guard.quorum < 1)
        bad.set(i, `its guard needs no attest under its root's ${s.pinned}`);
    }
    for (const [i, why] of bad) { this.problem("INVALID", i, why); this.drop(i, `INVALID: ${why}`); }
  }

  bodies() {
    for (const [i, r] of this.sortedRecs()) {
      if (r.kind === "schema" || (r.schema === null && r.kind !== "entity") || (r.schema === MIGRATION && r.kind === "attest")) continue;
      const s = this.schemas.get(r.schema);
      const why = s === undefined ? `schema ${quote(r.schema)} is not one this receiver counts` : bodyProblem(r, s);
      if (why) { this.problem("INVALID", i, why); this.drop(i, `INVALID: ${why}`); }
    }
  }

  maySucceed(r, root) {
    const roles = own(this.schemas.get(r.schema).successors, getOr(r.body, "state", null));
    return roles === undefined || roles === null ? r.actor === root.actor : this.holds(r.actor, roles);
  }

  lineagesOf(ids, maySucceed) {
    const rootOf = new Map();
    for (const i of sorted(ids)) {
      const path = this.climb(i, ids, rootOf);
      for (let k = path.length - 1; k >= 0; k--) this.succeed(path[k], rootOf, maySucceed);
    }
    const lins = new Map();
    for (const i of [...ids].sort((a, b) => (this.recs.get(a).at - this.recs.get(b).at) || cmp(a, b))) {
      const rt = rootOf.get(i);
      if (rt === undefined || rt === null) continue;
      if (!lins.has(rt)) lins.set(rt, { versions: [], succ: new Map() });
      const lin = lins.get(rt);
      lin.versions.push(i);
      if (i !== rt) { const p = this.recs.get(i).lineage; if (!lin.succ.has(p)) lin.succ.set(p, []); lin.succ.get(p).push(i); }
    }
    for (const [rt, lin] of lins) settle(rt, lin);
    const out = new Map();
    for (const [i, rt] of rootOf) if (rt !== null && ids.has(i)) out.set(i, rt);
    return [out, lins];
  }

  climb(i, ids, rootOf) {
    const path = [];
    let cur = i;
    while (!rootOf.has(cur) && ids.has(cur) && this.recs.get(cur).lineage !== null && path.length < 4096) { path.push(cur); cur = this.recs.get(cur).lineage; }
    if (!rootOf.has(cur)) rootOf.set(cur, ids.has(cur) && this.recs.get(cur).lineage === null ? cur : null);
    return path;
  }

  succeed(x, rootOf, maySucceed) {
    const r = this.recs.get(x), p = r.lineage, rt = rootOf.get(p);
    if (rt === null || this.recs.get(p).kind !== r.kind || this.recs.get(p).schema !== r.schema) {
      rootOf.set(x, null);
      this.problem("LINEAGE_BROKEN", x, `it succeeds ${p.slice(0, 12)}, which is no admitted version of its kind and schema`);
    } else if (!maySucceed(r, this.recs.get(rt))) {
      rootOf.set(x, null);
      this.problem("LINEAGE_NOT_AUTHOR", x, `filed by ${quote(r.actor)}; the lineage is ${quote(this.recs.get(rt).actor)}'s`);
    } else {
      rootOf.set(x, rt);
      if (r.at < this.recs.get(p).at) this.problem("LINEAGE_BACKDATED", x, "dated before the version it succeeds");
    }
  }

  // engine.py _lineage_depth: a lineage longer than LIMITS.depth links refuses the store before it is assessed (§8).
  lineageDepth() {
    const depth = new Map();
    for (const [i] of this.sortedRecs()) {
      const path = [];
      let cur = i;
      while (this.recs.has(cur) && !depth.has(cur) && this.recs.get(cur).lineage !== null) { path.push(cur); cur = this.recs.get(cur).lineage; }
      let d = depth.has(cur) ? depth.get(cur) : 0;
      for (let k = path.length - 1; k >= 0; k--) { d += 1; depth.set(path[k], d); }
      if (d > LIMITS.depth) throw new Invalid(`store beyond limits: a lineage ${d} links deep, more than ${LIMITS.depth}`);
    }
  }

  requiresDepth() {
    const deps = new Map();
    for (const [L, lin] of this.lineages) {
      const s = new Set();
      for (const v of lin.versions) for (const x of (this.recs.get(v).guard || { requires: [] }).requires) if (this.lineages.has(x)) s.add(x);
      deps.set(L, sorted(s));
    }
    const depth = new Map();
    for (const start of sorted(deps.keys())) {
      if (depth.has(start)) continue;
      const stack = [[start, 0]], on = new Set([start]);
      while (stack.length) {
        const top = stack[stack.length - 1], ch = deps.get(top[0]);
        if (top[1] >= ch.length) {
          stack.pop(); on.delete(top[0]);
          let m = 0;
          for (const c of ch) if (depth.has(c) && depth.get(c) > m) m = depth.get(c);
          depth.set(top[0], 1 + m);
        } else {
          const nxt = ch[top[1]++];
          if (!depth.has(nxt) && !on.has(nxt)) { on.add(nxt); stack.push([nxt, 0]); }
        }
      }
    }
    let max = 0;
    for (const d of depth.values()) if (d > max) max = d;
    if (max > LIMITS.requires) throw new Invalid(`store beyond limits: lineages require lineages ${max} deep, more than ${LIMITS.requires}`);
  }

  schemaOf(i) { return this.schemas.get(this.recs.get(i).schema); }

  requires(v) {
    const out = new Set();
    for (let cur = v; cur !== null; cur = this.recs.get(cur).lineage) for (const x of (this.recs.get(cur).guard || { requires: [] }).requires) out.add(x);
    return sorted(out);
  }

  attested() {
    const part = new Map(), closing = new Map();
    for (const v of sorted(this.rootOf.keys())) {
      const r = this.recs.get(v), g = r.guard;
      let acc = [];
      const waiting = [];
      if (g !== null) {
        const s = new Set();
        for (const a of this.attests.get(v) || []) {
          const x = this.recs.get(a);
          if (x.actor !== r.actor && this.holds(x.actor, g.roles) && keysOf(g.match).every((k) => getOr(x.body, k, NOWHERE) !== NOWHERE && pyEq(x.body[k], g.match[k]))) s.add(x.actor);
        }
        acc = sorted(s);
        if (acc.length < g.quorum) waiting.push(`${g.quorum - acc.length} attest(s) by ${g.roles.join(", ")} matching ${canonStr(g.match)}`);
      }
      part.set(v, [acc, waiting]);
      if ((this.schemaOf(v).closed || []).includes(getOr(r.body, "state", null))) closing.set(v, this.requires(v));
    }
    return [part, closing];
  }

  resolve() {
    const [part, closing] = this.attested();
    const users = new Map(), short = new Map();
    for (const [v, ls] of closing) { short.set(v, ls.length); for (const L of ls) { if (!users.has(L)) users.set(L, []); users.get(L).push(v); } }
    const met = new Set([...part].filter(([v, [, w]]) => !w.length && !short.get(v)).map(([v]) => v));
    const at = new Map();
    for (const lin of this.lineages.values()) lin.path.forEach((v, n) => at.set(v, n));
    const eff = new Map();
    for (const [L, lin] of this.lineages) { let e = null; for (let k = lin.path.length - 1; k >= 0; k--) if (met.has(lin.path[k])) { e = lin.path[k]; break; } eff.set(L, e); }
    const shut = new Set(), todo = sorted(eff.keys());
    while (todo.length) {
      const L = todo.pop();
      if (shut.has(L) || eff.get(L) === null || !(this.schemaOf(L).closed || []).includes(getOr(this.recs.get(eff.get(L)).body, "state", null))) continue;
      shut.add(L);
      for (const u of users.get(L) || []) {
        short.set(u, short.get(u) - 1);
        if (short.get(u) === 0 && !part.get(u)[1].length) {
          met.add(u);
          const U = this.rootOf.get(u);
          if (at.has(u) && (eff.get(U) === null || at.get(u) > at.get(eff.get(U)))) { eff.set(U, u); todo.push(U); }
        }
      }
    }
    const guards = new Map();
    for (const [v, [acc, waiting]] of part) {
      const g = this.recs.get(v).guard, stillOpen = (closing.get(v) || []).filter((L) => !shut.has(L));
      const w = [...waiting, ...stillOpen.map((L) => `requires ${L} closed`)];
      guards.set(v, { guard: w.length ? "PENDING" : g === null ? "NONE" : "MET", waiting: w, accepted_by: acc, roles: g ? g.roles : [],
        short: g ? Math.max(0, g.quorum - acc.length) : 0, open: stillOpen });
    }
    return [guards, eff];
  }

  challenge(c) {
    const r = this.recs.get(c), x = r.body.target, t = this.recs.get(x);
    const replays = [];
    for (const a of this.attests.get(c) || []) {
      const y = this.recs.get(a), verdict = getOr(y.body, "verdict", null);
      if (this.holds(y.actor, ["replayer"]) && REPLAY.some((w) => pyEq(w, verdict))) replays.push([getOr(y.body, "on", null), verdict, y.actor]);
    }
    let why = null;
    if (t !== undefined && r.actor === t.actor) why = "its target's actor";
    else if (t !== undefined && t.guard && this.holds(r.actor, t.guard.roles)) why = "holds a role of its target's guard";
    else if (this.holds(r.actor, ["challenger"])) why = "holds the challenger role";
    else if (replays.some(([on, v]) => pyEq(on, x) && v === "reproduces")) why = "reproduced by a replayer";
    let stands = why !== null && t !== undefined;
    if (stands && this.rootOf.has(x)) {
      const lin = this.lineages.get(this.rootOf.get(x)), eff = this.effectiveOf.get(this.rootOf.get(x));
      stands = eff === null || (lin.path.includes(x) && lin.path.indexOf(eff) <= lin.path.indexOf(x));   // §5: a fork has no effective version
    }
    const key = (z) => [pyStr(z[0]), pyStr(z[1]), z[2]];
    return { target: x, counted: why !== null, why: why || "thesis: its actor's challenge does not count here",
      replays: replays.sort((a, b) => cmpList(key(a), key(b))), stands };
  }

  graph() {
    const nodes = [], edges = [];
    for (const [i, r] of this.sortedRecs()) {
      nodes.push([i, r.kind, r.schema, r.actor, r.at, this.basis.get(i)]);
      const t = r.kind === "attest" || r.kind === "challenge" ? getOr(r.body, "target", null) : null;
      if (r.lineage) edges.push([i, "lineage", r.lineage]);
      if (r.prev) edges.push([i, "prev", r.prev]);
      if (t) edges.push([i, r.kind, t]);
      for (const x of (r.guard || { requires: [] }).requires) edges.push([i, "requires", x]);
      for (const x of r.refs) if (x !== t) edges.push([i, "ref", x]);
    }
    return { nodes, edges: edges.sort(cmpList) };
  }

  report() {
    const challenges = dict(), standing = new Map();
    for (const [c, r] of this.sortedRecs()) if (r.kind === "challenge") challenges[c] = this.challenge(c);
    for (const c of sorted(Object.keys(challenges))) {
      const x = challenges[c];
      if (x.stands) { if (!standing.has(x.target)) standing.set(x.target, []); standing.get(x.target).push(c); }
    }
    const versions = dict();
    for (const v of sorted(this.rootOf.keys())) versions[v] = { ...this.guards.get(v), challenged_by: standing.get(v) || [] };
    const lineages = dict();
    for (const L of sorted(this.lineages.keys())) {
      const lin = this.lineages.get(L), eff = this.effectiveOf.get(L);
      const reliance = lin.leaf === null ? "FORK" : eff === null ? "PENDING" : (standing.get(eff) || []).length ? "CHALLENGED" : "ELIGIBLE";
      lineages[L] = { schema: this.recs.get(L).schema, actor: this.recs.get(L).actor, versions: lin.versions, path: lin.path, leaf: lin.leaf,
        effective: eff, state: eff ? getOr(this.recs.get(eff).body, "state", null) : null, verdict: lin.forks.length ? "FORK" : "OK",
        forks: lin.forks, reliance };
    }
    for (const x of [this.prep.trustId, this.prep.profileId, this.prep.assessment]) if (x && x.error) throw x.error;
    const rejected = dict();
    for (const k of sorted([...new Set([...this.snap.rejected.keys(), ...this.bad.keys()])])) rejected[k] = this.bad.has(k) ? this.bad.get(k) : this.snap.rejected.get(k);
    const schemas = dict();
    for (const n of sorted(this.schemas.keys())) schemas[n] = this.schemas.get(n).id;
    const pending = dict();
    for (const i of this.pending) pending[i] = { name: this.recs.get(i).body.name, backed_by: this.backers(i), need: this.quorum(SCHEMA_AUTHOR) };
    let signed = 0, migrated = 0;
    for (const b of this.basis.values()) { if (b === "SIGNED") signed++; else if (b === "MIGRATED") migrated++; }
    return { warrant: "3", assessment: this.prep.assessment.id, snapshot: this.snap.digest, trust: this.prep.trustId.id, profile: this.prep.profileId.id,
      as_of: this.asOf, code: this.prep.code, completeness: "UNATTESTED", canonical: this.snap.canonical, later: this.later,
      basis: { SIGNED: signed, MIGRATED: migrated }, rejected,
      duplicates: sorted([...this.snap.lines].filter(([i, e]) => e.length > 1 && this.recs.has(i)).map(([i]) => i)),
      chains: { forks: this.chainForks, unanchored: this.unanchored }, schemas, schemas_pending: pending,
      lineages, versions, challenges, problems: [...this.problems].sort(cmpList), graph: this.graph() };
  }
}

export function assessPrepared(prep) { return new View(prep).report(); }
export async function assess(input, backend) { return assessPrepared(await prepare(input, backend)); }

// ---------------------------------------------------------------- read with no checkout (warrant/drift.py not_checked)

// docs/V3.md §10: a reader that compared no checkout shows a lineage the freshness gate covers, ELIGIBLE by the engine,
// as PINS_NOT_CHECKED, never ELIGIBLE: whether its acceptances still name the bytes they accepted needs a tree nobody
// compared. The predicate is warrant/drift.py's (pinned, counted, covered), the one site/reader.mjs ports too; the
// engine's report is otherwise unchanged and `assessment` stays the engine's digest. `lines` is the snapshot's
// {id: [envelope]}. Returns the lineages it lowered (Codex 77961f39: read.mjs and this command's assess and verify
// printed ELIGIBLE on the unchanged pins-not-checked vector).
export const PINS_NOT_CHECKED = "PINS_NOT_CHECKED";
const CHECKER = "claims-checker", CLAIM = "claim@1";

export function notChecked(rep, lines) {
  const rec = (i) => (lines.has(i) ? lines.get(i)[0].record : undefined);
  const basis = new Map(rep.graph.nodes.map((n) => [n[0], n[5]]));
  const counted = (r) => {                               // drift.counted: the version's guard counts this attest
    const t = r.body.target, v = has(rep.versions, t) ? rep.versions[t] : undefined, x = rec(t), g = x?.guard;
    if (!v || !isObj(g) || r.actor === x.actor || !(v.accepted_by || []).includes(r.actor)) return false;
    return Object.entries(g.match || {}).every(([k, m]) => has(r.body, k) && canonStr(r.body[k]) === canonStr(m));
  };
  const done = new Set();                                // drift.pinned: the versions a pinned acceptance targets
  for (const [i] of [...lines].sort((a, b) => utf16(a[0], b[0]))) {
    const r = rec(i);
    if (r.kind !== "attest" || basis.get(i) !== "SIGNED" || !isObj(r.body) || r.body.verdict !== "accept") continue;
    if (r.actor === CHECKER || (isObj(r.body.files) && counted(r))) done.add(r.body.target);
  }
  const out = [];
  for (const [L, lin] of Object.entries(rep.lineages)) {  // drift.covered, then not_checked
    if (lin.schema === CLAIM && (lin.leaf ? rec(lin.leaf)?.body?.state : null) === "retired") continue;
    if (lin.effective && done.has(lin.effective) && lin.reliance === "ELIGIBLE") out.push(L);
  }
  out.sort(utf16);
  for (const L of out) rep.lineages[L].reliance = PINS_NOT_CHECKED;
  return out;
}

// assess, then read as a reader with no checkout beside it: what `warrant.mjs assess` and impl-js/read.mjs print.
export async function assessRead(input, backend) {
  const prep = await prepare(input, backend);
  const rep = assessPrepared(prep);
  notChecked(rep, prep.snap.lines);
  return rep;
}

// The engine's identity: the digest of this file and of the platform that answers SHA-256 and Ed25519.
export async function codeIdentity(source, backend) {
  const files = dict();
  files["impl-js/warrant.mjs"] = await backend.sha256(source);
  return backend.sha256(canon({ files, runtime: backend.name }));
}

// ---------------------------------------------------------------- handoff inspect, alone (warrant_agent/api.py)

// A blob in a package: base64 of RFC 4648 §4 in its one padded form (warrant/verify.py _BASE64), a rule of the format and
// not of any interpreter's decoder (R-INTERPRETER): a length that is a multiple of four, the alphabet only, then at most
// two `=`. Read by a loop, not a regexp: V8 backtracks a repeated group on a stack that grows with the blob, and a
// valid 12-MiB blob overflowed it (Codex F1 on #342 at 3efb118a).
function isBase64(s) {
  if (!isStr(s) || s.length % 4 !== 0) return false;
  let end = s.length;
  if (s.endsWith("==")) end -= 2;
  else if (s.endsWith("=")) end -= 1;
  for (let i = 0; i < end; i++) {
    const c = s.codePointAt(i);
    if (!((c >= 65 && c <= 90) || (c >= 97 && c <= 122) || (c >= 48 && c <= 57) || c === 43 || c === 47)) return false;
  }
  return true;
}
function b64decode(s) {
  if (!isBase64(s)) throw new AgentError("BAD_REQUEST", "a blob is not base64");
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// The length of Python's json.dumps(v): ensure_ascii, ", " and ": " separators.
function pyDumpsLen(v) {
  if (v === null) return 4;
  if (v === true) return 4;
  if (v === false) return 5;
  if (isInt(v)) return String(v).length;
  if (isStr(v)) {
    let n = 2;
    for (let i = 0; i < v.length; i++) {
      const c = v.charCodeAt(i);
      n += c === 34 || c === 92 || c === 8 || c === 9 || c === 10 || c === 12 || c === 13 ? 2 : c < 0x20 || c > 0x7e ? 6 : 1;
    }
    return n;
  }
  if (Array.isArray(v)) return v.length ? 1 + v.reduce((a, x) => a + pyDumpsLen(x), 0) + 2 * (v.length - 1) + 1 : 2;
  const ks = Object.keys(v);
  return ks.length ? 1 + ks.reduce((a, k) => a + pyDumpsLen(k) + 2 + pyDumpsLen(v[k]), 0) + 2 * (ks.length - 1) + 1 : 2;
}

function lineageOf(rep, i) {
  for (const root of Object.keys(rep.lineages)) if (rep.lineages[root].versions.includes(i)) return root;
  return null;
}

function describe(rep, nodes, i) {
  const n = nodes.has(i) ? { ...nodes.get(i) } : { id: i, kind: "unavailable" };
  if (has(rep.versions, i)) {
    n.guard = rep.versions[i];
    const root = lineageOf(rep, i), lin = rep.lineages[root];
    n.lineage = { root, state: lin.state, reliance: lin.reliance, leaf: lin.leaf, effective: lin.effective, verdict: lin.verdict };
  }
  if (has(rep.challenges, i)) n.challenge = rep.challenges[i];
  return n;
}

// handoff {op: inspect, package, alone: true} under the receiver (trust, profile): the same members, `adapter` this
// module's identity. AgentError carries the agent interface's error code.
export async function inspectAlone(pkg, trust, profile, backend, code) {
  const ok = isObj(pkg) && own(pkg, "warrant") === PACKAGE && sameKeys(pkg, ["warrant", "roots", "lines", "blobs"])
    && Array.isArray(pkg.lines) && pkg.lines.every(isStr) && isObj(pkg.blobs) && Array.isArray(pkg.roots) && pkg.roots.every(hex64);
  if (!ok) throw new AgentError("BAD_REQUEST", `a package is {warrant: ${PACKAGE}, roots, lines, blobs}`);
  const blobs = new Map();
  for (const h of pkg.blobs[ORDER] || Object.keys(pkg.blobs)) blobs.set(h, b64decode(pkg.blobs[h]));     // Python's dict order: as read
  // As warrant/verify.py: a lone surrogate is encoded as Python's "surrogatepass" does, bytes no reader takes for a record,
  // so the snapshot counts the line as rejected.
  const lines = pkg.lines.map((x) => (isWellFormed(x) ? utf8(x + "\n") : surrogatePass(x + "\n")));
  let size = 0;
  for (const x of lines) size += x.length;
  for (const b of blobs.values()) size += b.length;
  if (size > STORE_BYTES) throw new AgentError("RESOURCE_LIMIT", "the package exceeds the workspace's store_bytes");
  for (const [h, b] of blobs) if (!(hex64(h) && (await backend.sha256(b)) === h)) throw new AgentError("BAD_REQUEST", "a blob is not named by its hash");
  let prep;
  try { prep = await prepare({ lines, blobs, trust, profile, as_of: null, code }, backend); } catch (e) {
    if (e instanceof Refused) throw new AgentError(e.message.includes("limit") ? "RESOURCE_LIMIT" : "REFUSED", e.message);
    throw e;
  }
  if (prep.snap.rejected.size) throw new AgentError("BAD_REQUEST", `${prep.snap.rejected.size} line(s) of the package are not records`);
  let rep;
  try { rep = assessPrepared(prep); } catch (e) {
    if (e instanceof Invalid) throw new AgentError(e.message.includes("limit") ? "RESOURCE_LIMIT" : "BAD_REQUEST", e.message);
    throw e;
  }
  notChecked(rep, prep.snap.lines);                // api.py: a package is read with no tree beside it (§10)
  const nodes = new Map(rep.graph.nodes.map((x) => [x[0], { id: x[0], kind: x[1], schema: x[2], actor: x[3], at: x[4], basis: x[5] }]));
  const roots = dict();
  for (const r of pkg.roots) roots[r] = describe(rep, nodes, r);
  const rejected = dict();
  for (const i of Object.keys(rep.rejected)) if (prep.snap.lines.has(i)) rejected[i] = rep.rejected[i];
  const out = dict();
  for (const k of ["assessment", "snapshot", "trust", "profile", "as_of", "code", "completeness", "canonical", "basis"]) out[k] = rep[k];
  Object.assign(out, { adapter: code, agent_api: AGENT_API, rejected, problems: rep.problems.length, package: prep.snap.digest, roots });
  const dumped = pyDumpsLen(out);                   // api._budget: json.dumps(out, sort_keys=True), the workspace's context_bytes
  if (dumped > CONTEXT_BYTES) throw new AgentError("RESOURCE_LIMIT", `the result is ${dumped} bytes; this workspace answers ${CONTEXT_BYTES} (name fewer targets, or read one)`);
  return out;
}

// ---------------------------------------------------------------- the store directory, a case, the CLI

async function readStore(dir, backend) {
  const fs = await import("node:fs");
  const path = await import("node:path");
  const file = path.join(dir, "records.jsonl"), bdir = path.join(dir, "blobs");
  const raw = fs.existsSync(file) ? new Uint8Array(fs.readFileSync(file)) : new Uint8Array();
  const lines = [];
  let start = 0;
  for (let i = 0; i <= raw.length; i++) {
    if (i === raw.length || raw[i] === 0x0a) {
      if (i > start) { const l = new Uint8Array(i - start + 1); l.set(raw.subarray(start, i)); l[i - start] = 0x0a; lines.push(l); }
      start = i + 1;
    }
  }
  const blobs = new Map();
  if (fs.existsSync(bdir) && fs.statSync(bdir).isDirectory()) for (const n of sorted(fs.readdirSync(bdir))) blobs.set(n, new Uint8Array(fs.readFileSync(path.join(bdir, n))));
  const bad = [];
  for (const [h, b] of blobs) if ((await backend.sha256(b)) !== h) bad.push(h);
  if (bad.length) throw new Refused(`blobs not named by their hash: ${quote(bad.slice(0, 3))}`);
  return { lines, blobs };
}

const b64bytes = (s) => { const bin = atob(s); const o = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) o[i] = bin.charCodeAt(i); return o; };

// A case of the oracle and the vectors: {lines: [base64], blobs: {name: base64}, trust, profile, as_of}, the
// report or {refused}; or {package, trust, profile}, handoff inspect's result alone or {error, message}.
export async function runCase(c, backend, code) {
  if (has(c, "package")) {
    try { return await inspectAlone(c.package, c.trust, c.profile, backend, code); } catch (e) {
      if (e instanceof AgentError) return { error: e.code, message: e.message };
      throw e;
    }
  }
  try {
    const rep = await assess({ lines: c.lines.map(b64bytes), blobs: new Map(Object.keys(c.blobs).map((h) => [h, b64bytes(c.blobs[h])])),
      trust: c.trust, profile: c.profile, as_of: c.as_of ?? null, code }, backend);
    return rep;
  } catch (e) {
    if (e instanceof Refused || e instanceof Invalid || e instanceof NotCanonical) return { refused: e.message };
    throw e;
  }
}

function receiverOf(text) {
  const doc = loadsLenient(text);
  if (!(isObj(doc) && isObj(own(doc, "trust")) && isObj(own(doc, "profile")))) throw new Refused("the configuration is not a receiver configuration {repository, trust, profile}");
  for (const why of [trustProblem(doc.trust), profileProblem(doc.profile)]) if (why) throw new Refused(why);
  return doc;
}

async function main(argv) {
  const fs = await import("node:fs");
  const backend = argv.includes("--webcrypto") ? webBackend() : await nodeBackend();
  argv = argv.filter((a) => a !== "--webcrypto");
  const code = await codeIdentity(new Uint8Array(fs.readFileSync(new URL(import.meta.url))), backend);
  const opt = (name) => { const k = argv.indexOf(name); return k >= 0 ? argv[k + 1] : undefined; };
  const out = (v) => process.stdout.write(canonStr(v) + "\n");
  const [cmd] = argv;
  try {
    if (cmd === "assess") {
      const doc = receiverOf(fs.readFileSync(opt("--config"), "utf8"));
      const asOf = opt("--as-of") === undefined ? null : Number(opt("--as-of"));
      const st = await readStore(opt("--store"), backend);
      const input = { ...st, trust: doc.trust, profile: doc.profile, as_of: asOf, code };
      out(argv.includes("--engine") ? await assess(input, backend) : await assessRead(input, backend));
    } else if (cmd === "verify") {
      const doc = receiverOf(fs.readFileSync(opt("--config"), "utf8"));
      const pkg = loadsLenient(fs.readFileSync(argv[1], "utf8"));
      try { out(await inspectAlone(pkg, doc.trust, doc.profile, backend, code)); } catch (e) {
        if (e instanceof AgentError) { out({ error: e.code, message: e.message }); return 1; }
        throw e;
      }
    } else if (cmd === "batch") {
      const text = fs.readFileSync(argv[1], "utf8");
      for (const line of text.split("\n")) {
        if (!line) continue;
        let res;
        try { res = await runCase(loadsLenient(line), backend, code); } catch (e) { res = { crash: `JS ${e.name}: ${e.message}` }; }
        out(res);
      }
    } else if (cmd === "code") {
      out({ code, runtime: backend.name });
    } else {
      process.stderr.write("usage: warrant.mjs assess --store DIR --config V3JSON [--as-of N] [--engine] | verify PACKAGE.json --config V3JSON | batch CASES.jsonl\n");
      return 2;
    }
  } catch (e) {
    if (e instanceof Refused || e instanceof Invalid || e instanceof NotCanonical || e instanceof SyntaxError) { out({ refused: e.message }); return 2; }
    throw e;
  }
  return 0;
}

if (typeof process !== "undefined" && process.argv && import.meta.url === (await import("node:url")).pathToFileURL(process.argv[1] || "").href) {
  process.exitCode = await main(process.argv.slice(2));
}
