// canon.mjs
import { createHash } from 'node:crypto';

// Custom JSON parser that detects duplicate keys
function parseJSONWithDupCheck(str) {
  let pos = 0;
  const s = str;

  function error(msg) {
    throw new Error(msg);
  }

  function skipWhitespace() {
    while (pos < s.length && /\s/.test(s[pos])) pos++;
  }

  function parseValue() {
    skipWhitespace();
    if (pos >= s.length) error('Unexpected end of input');
    const c = s[pos];
    if (c === '{') return parseObject();
    if (c === '[') return parseArray();
    if (c === '"') return parseString();
    if (c === 't' || c === 'f') return parseBool();
    if (c === 'n') return parseNull();
    if (c === '-' || (c >= '0' && c <= '9')) return parseNumber();
    error('Unexpected character: ' + c);
  }

  function parseObject() {
    pos++; // skip {
    const obj = {};
    const keys = new Set();
    skipWhitespace();
    if (s[pos] === '}') {
      pos++;
      return obj;
    }
    while (true) {
      skipWhitespace();
      if (s[pos] !== '"') error('Expected string key');
      const key = parseString();
      if (keys.has(key)) {
        error('Duplicate key: ' + key);
      }
      keys.add(key);
      skipWhitespace();
      if (s[pos] !== ':') error('Expected colon');
      pos++; // skip :
      const val = parseValue();
      obj[key] = val;
      skipWhitespace();
      if (s[pos] === ',') {
        pos++;
        continue;
      }
      if (s[pos] === '}') {
        pos++;
        break;
      }
      error('Expected comma or closing brace');
    }
    return obj;
  }

  function parseArray() {
    pos++; // skip [
    const arr = [];
    skipWhitespace();
    if (s[pos] === ']') {
      pos++;
      return arr;
    }
    while (true) {
      const val = parseValue();
      arr.push(val);
      skipWhitespace();
      if (s[pos] === ',') {
        pos++;
        continue;
      }
      if (s[pos] === ']') {
        pos++;
        break;
      }
      error('Expected comma or closing bracket');
    }
    return arr;
  }

  function parseString() {
    pos++; // skip opening quote
    let result = '';
    while (pos < s.length) {
      const c = s[pos];
      if (c === '"') {
        pos++;
        return result;
      }
      if (c === '\\') {
        pos++;
        const esc = s[pos];
        switch (esc) {
          case '"': result += '"'; break;
          case '\\': result += '\\'; break;
          case '/': result += '/'; break;
          case 'b': result += '\b'; break;
          case 'f': result += '\f'; break;
          case 'n': result += '\n'; break;
          case 'r': result += '\r'; break;
          case 't': result += '\t'; break;
          case 'u': {
            const hex = s.slice(pos + 1, pos + 5);
            if (hex.length !== 4 || !/^[0-9a-fA-F]{4}$/.test(hex)) {
              error('Invalid unicode escape');
            }
            const code = parseInt(hex, 16);
            // Handle surrogate pairs
            if (code >= 0xD800 && code <= 0xDBFF) {
              // High surrogate, check for low surrogate
              if (s[pos + 5] === '\\' && s[pos + 6] === 'u') {
                const hex2 = s.slice(pos + 7, pos + 11);
                if (hex2.length === 4 && /^[0-9a-fA-F]{4}$/.test(hex2)) {
                  const code2 = parseInt(hex2, 16);
                  if (code2 >= 0xDC00 && code2 <= 0xDFFF) {
                    const cp = 0x10000 + ((code - 0xD800) << 10) + (code2 - 0xDC00);
                    result += String.fromCodePoint(cp);
                    pos += 10; // skip \uXXXX\uXXXX
                    continue;
                  }
                }
              }
              result += String.fromCodePoint(code);
            } else {
              result += String.fromCodePoint(code);
            }
            pos += 4;
            break;
          }
          default:
            error('Invalid escape character: ' + esc);
        }
        pos++;
      } else {
        result += c;
        pos++;
      }
    }
    error('Unterminated string');
  }

  function parseNumber() {
    const start = pos;
    if (s[pos] === '-') pos++;
    while (pos < s.length && s[pos] >= '0' && s[pos] <= '9') pos++;
    let isFloat = false;
    if (s[pos] === '.') {
      isFloat = true;
      pos++;
      while (pos < s.length && s[pos] >= '0' && s[pos] <= '9') pos++;
    }
    if (s[pos] === 'e' || s[pos] === 'E') {
      isFloat = true;
      pos++;
      if (s[pos] === '+' || s[pos] === '-') pos++;
      while (pos < s.length && s[pos] >= '0' && s[pos] <= '9') pos++;
    }
    const numStr = s.slice(start, pos);
    const num = Number(numStr);
    if (isFloat) {
      // Mark as float for later validation
      return { __isFloat: true, value: num };
    }
    return num;
  }

  function parseBool() {
    if (s.startsWith('true', pos)) {
      pos += 4;
      return true;
    }
    if (s.startsWith('false', pos)) {
      pos += 5;
      return false;
    }
    error('Invalid boolean');
  }

  function parseNull() {
    if (s.startsWith('null', pos)) {
      pos += 4;
      return null;
    }
    error('Invalid null');
  }

  const result = parseValue();
  skipWhitespace();
  if (pos < s.length) {
    error('Unexpected trailing characters');
  }
  return result;
}

// Recursively check for floats in the parsed structure
function checkForFloats(val, path = 'root') {
  if (val === null || val === undefined) return;
  if (typeof val === 'object') {
    if (Array.isArray(val)) {
      for (let i = 0; i < val.length; i++) {
        checkForFloats(val[i], `${path}[${i}]`);
      }
    } else {
      // Check for float markers
      if (val.__isFloat) {
        throw new Error(`Non-integer number at ${path}`);
      }
      for (const [k, v] of Object.entries(val)) {
        checkForFloats(v, `${path}.${k}`);
      }
    }
  }
}

// JCS canonical JSON serializer
function canonicalize(value) {
  if (value === null) return 'null';
  if (value === undefined) return 'null';
  
  switch (typeof value) {
    case 'boolean':
      return value ? 'true' : 'false';
    case 'number':
      // Integers only - if it's a float, it should have been caught earlier
      if (!Number.isInteger(value)) {
        throw new Error('Non-integer number');
      }
      return String(value);
    case 'string':
      return escapeString(value);
    case 'object':
      if (Array.isArray(value)) {
        return '[' + value.map(canonicalize).join(',') + ']';
      } else {
        // Sort keys by UTF-16 code unit
        const keys = Object.keys(value).sort((a, b) => {
          // Compare by UTF-16 code units
          for (let i = 0; i < a.length && i < b.length; i++) {
            const ca = a.charCodeAt(i);
            const cb = b.charCodeAt(i);
            if (ca !== cb) return ca - cb;
          }
          return a.length - b.length;
        });
        const members = keys.map(k => escapeString(k) + ':' + canonicalize(value[k]));
        return '{' + members.join(',') + '}';
      }
    default:
      throw new Error('Unsupported type: ' + typeof value);
  }
}

function escapeString(str) {
  let result = '"';
  for (let i = 0; i < str.length; i++) {
    const code = str.charCodeAt(i);
    
    // Short escapes
    switch (code) {
      case 0x22: result += '\\"'; break; // "
      case 0x5C: result += '\\\\'; break; // \
      case 0x08: result += '\\b'; break;  // backspace
      case 0x09: result += '\\t'; break;  // tab
      case 0x0A: result += '\\n'; break;  // newline
      case 0x0C: result += '\\f'; break;  // form feed
      case 0x0D: result += '\\r'; break;  // carriage return
      default:
        // Other control characters below U+0020
        if (code < 0x20) {
          result += '\\u' + code.toString(16).padStart(4, '0').toLowerCase();
        } else {
          // Emit raw - including <, >, &, /, U+2028, U+2029, and all non-ASCII
          result += str[i];
        }
    }
  }
  result += '"';
  return result;
}

export function handle(className, input) {
  if (className !== 'canon') {
    return { unsupported: 'Unknown class: ' + className };
  }

  try {
    // Parse the input body
    let body;
    if (typeof input.body === 'string') {
      // Parse JSON string with duplicate key detection
      body = parseJSONWithDupCheck(input.body);
    } else {
      // Already an object
      body = input.body;
    }

    // Check for floats
    checkForFloats(body);

    // Canonicalize
    const canonicalJson = canonicalize(body);
    
    // Convert to UTF-8 bytes
    const utf8Bytes = Buffer.from(canonicalJson, 'utf-8');
    
    // Compute SHA-256
    const hash = createHash('sha256').update(utf8Bytes).digest('hex');
    
    return {
      output: {
        canon_hex: utf8Bytes.toString('hex'),
        warrant_id: hash
      }
    };
  } catch (e) {
    return {
      output: {
        error: e.message || String(e)
      }
    };
  }
}
