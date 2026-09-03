// parse.mjs
// Warrant conformance class: parse
// Implements RFC 7493 I-JSON parsing with strict rejection rules.

/**
 * @param {string} className
 * @param {object} input
 * @returns {Promise<{output: object} | {unsupported: string}>}
 */
export async function handle(className, input) {
  if (className !== 'parse') {
    return { unsupported: `Unknown class: ${className}` };
  }

  if (!input || typeof input !== 'object' || !('bytes_base64' in input)) {
    return { unsupported: 'Input must contain bytes_base64' };
  }

  const b64 = input.bytes_base64;
  if (typeof b64 !== 'string') {
    return { unsupported: 'bytes_base64 must be a string' };
  }

  let bytes;
  try {
    bytes = Buffer.from(b64, 'base64');
  } catch (e) {
    return { output: { ok: false, error: 'Invalid base64 encoding' } };
  }

  // Check for leading UTF-8 BOM (EF BB BF)
  if (bytes.length >= 3 && bytes[0] === 0xEF && bytes[1] === 0xBB && bytes[2] === 0xBF) {
    return { output: { ok: false, error: 'Leading UTF-8 BOM' } };
  }

  // Validate UTF-8 encoding
  try {
    const text = bytes.toString('utf8');
    // Check for replacement characters which indicate invalid UTF-8
    // Note: Buffer.toString('utf8') replaces invalid sequences with U+FFFD
    // We need to detect if any invalid sequences were present
    // A more robust check: try to encode back and compare
    const reEncoded = Buffer.from(text, 'utf8');
    if (!reEncoded.equals(bytes)) {
      return { output: { ok: false, error: 'Invalid UTF-8' } };
    }
    
    // Now parse the JSON string strictly
    const result = parseStrict(text);
    if (!result.ok) {
      return { output: { ok: false, error: result.error } };
    }
    return { output: { ok: true } };
  } catch (e) {
    return { output: { ok: false, error: e.message || 'Parse error' } };
  }
}

/**
 * Strict JSON parser that rejects:
 * - Duplicate keys
 * - Trailing content
 * - NaN, Infinity, -Infinity
 * - Leading zeros in numbers
 * - Trailing commas
 * - Single quotes
 * - Unescaped control chars in strings
 * - Unpaired surrogates
 * 
 * @param {string} text
 * @returns {{ok: boolean, error?: string}}
 */
function parseStrict(text) {
  let pos = 0;
  const len = text.length;

  function error(msg) {
    return { ok: false, error: msg };
  }

  function skipWhitespace() {
    while (pos < len) {
      const c = text[pos];
      if (c === ' ' || c === '\t' || c === '\n' || c === '\r') {
        pos++;
      } else {
        break;
      }
    }
  }

  function parseValue() {
    skipWhitespace();
    if (pos >= len) {
      return error('Unexpected end of input');
    }
    const c = text[pos];
    if (c === '{') return parseObject();
    if (c === '[') return parseArray();
    if (c === '"') return parseString();
    if (c === 't' || c === 'f') return parseBoolean();
    if (c === 'n') return parseNull();
    if (c === '-' || (c >= '0' && c <= '9')) return parseNumber();
    return error(`Unexpected character: ${c}`);
  }

  function parseObject() {
    pos++; // consume {
    skipWhitespace();
    if (pos >= len) return error('Unexpected end of input in object');
    if (text[pos] === '}') {
      pos++;
      return { ok: true, value: {} };
    }

    const obj = {};
    const keys = new Set();

    while (true) {
      skipWhitespace();
      if (pos >= len) return error('Unexpected end of input in object');
      if (text[pos] !== '"') return error('Expected string key');
      
      const keyResult = parseString();
      if (!keyResult.ok) return keyResult;
      const key = keyResult.value;

      if (keys.has(key)) {
        return error('Duplicate key: ' + key);
      }
      keys.add(key);

      skipWhitespace();
      if (pos >= len || text[pos] !== ':') return error('Expected colon');
      pos++; // consume :

      const valResult = parseValue();
      if (!valResult.ok) return valResult;
      obj[key] = valResult.value;

      skipWhitespace();
      if (pos >= len) return error('Unexpected end of input in object');
      if (text[pos] === ',') {
        pos++;
        skipWhitespace();
        if (pos >= len || text[pos] === '}') {
          return error('Trailing comma in object');
        }
        continue;
      }
      if (text[pos] === '}') {
        pos++;
        return { ok: true, value: obj };
      }
      return error('Expected comma or closing brace');
    }
  }

  function parseArray() {
    pos++; // consume [
    skipWhitespace();
    if (pos >= len) return error('Unexpected end of input in array');
    if (text[pos] === ']') {
      pos++;
      return { ok: true, value: [] };
    }

    const arr = [];

    while (true) {
      const valResult = parseValue();
      if (!valResult.ok) return valResult;
      arr.push(valResult.value);

      skipWhitespace();
      if (pos >= len) return error('Unexpected end of input in array');
      if (text[pos] === ',') {
        pos++;
        skipWhitespace();
        if (pos >= len || text[pos] === ']') {
          return error('Trailing comma in array');
        }
        continue;
      }
      if (text[pos] === ']') {
        pos++;
        return { ok: true, value: arr };
      }
      return error('Expected comma or closing bracket');
    }
  }

  function parseString() {
    pos++; // consume opening quote
    let str = '';
    
    while (pos < len) {
      const c = text[pos];
      if (c === '"') {
        pos++;
        return { ok: true, value: str };
      }
      if (c === '\\') {
        pos++;
        if (pos >= len) return error('Unexpected end of input in string escape');
        const esc = text[pos];
        switch (esc) {
          case '"': str += '"'; pos++; break;
          case '\\': str += '\\'; pos++; break;
          case '/': str += '/'; pos++; break;
          case 'b': str += '\b'; pos++; break;
          case 'f': str += '\f'; pos++; break;
          case 'n': str += '\n'; pos++; break;
          case 'r': str += '\r'; pos++; break;
          case 't': str += '\t'; pos++; break;
          case 'u': {
            pos++;
            if (pos + 4 > len) return error('Invalid unicode escape');
            const hex = text.slice(pos, pos + 4);
            if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
              return error('Invalid unicode escape hex');
            }
            const code = parseInt(hex, 16);
            pos += 4;
            
            // Check for surrogate pairs
            if (code >= 0xD800 && code <= 0xDBFF) {
              // High surrogate, expect low surrogate
              if (pos + 1 >= len || text[pos] !== '\\') {
                return error('Unpaired high surrogate');
              }
              if (text[pos + 1] !== 'u') {
                return error('Unpaired high surrogate');
              }
              pos += 2;
              if (pos + 4 > len) return error('Invalid unicode escape in surrogate pair');
              const hex2 = text.slice(pos, pos + 4);
              if (!/^[0-9a-fA-F]{4}$/.test(hex2)) {
                return error('Invalid unicode escape hex in surrogate pair');
              }
              const code2 = parseInt(hex2, 16);
              pos += 4;
              if (code2 < 0xDC00 || code2 > 0xDFFF) {
                return error('Invalid low surrogate');
              }
              // Combine surrogates
              const cp = 0x10000 + ((code - 0xD800) << 10) + (code2 - 0xDC00);
              str += String.fromCodePoint(cp);
            } else if (code >= 0xDC00 && code <= 0xDFFF) {
              return error('Unpaired low surrogate');
            } else {
              str += String.fromCharCode(code);
            }
            break;
          }
          default:
            return error('Invalid escape character: ' + esc);
        }
      } else if (c === '"') {
        pos++;
        return { ok: true, value: str };
      } else if (c.charCodeAt(0) < 0x20) {
        return error('Unescaped control character in string');
      } else {
        str += c;
        pos++;
      }
    }
    return error('Unterminated string');
  }

  function parseNumber() {
    const start = pos;
    if (text[pos] === '-') pos++;
    
    if (pos >= len) return error('Invalid number');
    
    if (text[pos] === '0') {
      pos++;
      if (pos < len && text[pos] >= '0' && text[pos] <= '9') {
        return error('Leading zero in number');
      }
    } else if (text[pos] >= '1' && text[pos] <= '9') {
      pos++;
      while (pos < len && text[pos] >= '0' && text[pos] <= '9') {
        pos++;
      }
    } else {
      return error('Invalid number');
    }

    if (pos < len && text[pos] === '.') {
      pos++;
      if (pos >= len || text[pos] < '0' || text[pos] > '9') {
        return error('Invalid number fraction');
      }
      while (pos < len && text[pos] >= '0' && text[pos] <= '9') {
        pos++;
      }
    }

    if (pos < len && (text[pos] === 'e' || text[pos] === 'E')) {
      pos++;
      if (pos < len && (text[pos] === '+' || text[pos] === '-')) {
        pos++;
      }
      if (pos >= len || text[pos] < '0' || text[pos] > '9') {
        return error('Invalid number exponent');
      }
      while (pos < len && text[pos] >= '0' && text[pos] <= '9') {
        pos++;
      }
    }

    const numStr = text.slice(start, pos);
    // Check for NaN, Infinity, -Infinity
    if (numStr === 'NaN' || numStr === 'Infinity' || numStr === '-Infinity') {
      return error('Invalid number: ' + numStr);
    }

    const num = Number(numStr);
    if (Number.isNaN(num) || !Number.isFinite(num)) {
      return error('Invalid number: ' + numStr);
    }

    return { ok: true, value: num };
  }

  function parseBoolean() {
    if (text.startsWith('true', pos)) {
      pos += 4;
      return { ok: true, value: true };
    }
    if (text.startsWith('false', pos)) {
      pos += 5;
      return { ok: true, value: false };
    }
    return error('Invalid literal');
  }

  function parseNull() {
    if (text.startsWith('null', pos)) {
      pos += 4;
      return { ok: true, value: null };
    }
    return error('Invalid literal');
  }

  const result = parseValue();
  if (!result.ok) return result;

  skipWhitespace();
  if (pos < len) {
    return error('Trailing content after JSON value');
  }

  return { ok: true, value: result.value };
}
