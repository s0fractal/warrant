"""Canonical JSON (SPEC §2): RFC 8785 over integers, strings, booleans, null,
arrays and objects, plus a strict reader for the same domain."""
import hashlib
import json

MAX_INT = 2**53 - 1
MAX_DEPTH = 256


class NotCanonical(ValueError):
    """Bytes or values outside the encoding of SPEC §2."""


def canon(value):
    """RFC 8785 bytes. Object members are ordered by UTF-16 code units; integers
    outside ±(2^53-1), floats and lone surrogates are refused."""
    out = []
    stack = [("v", value, 0)]
    while stack:
        tag, v, depth = stack.pop()
        if tag == "s":
            out.append(v)
            continue
        if depth > MAX_DEPTH:
            raise NotCanonical("nested too deep")
        if v is None:
            out.append("null")
        elif v is True:
            out.append("true")
        elif v is False:
            out.append("false")
        elif isinstance(v, int):
            if not -MAX_INT <= v <= MAX_INT:
                raise NotCanonical("integer outside ±(2^53-1)")
            out.append(str(v))
        elif isinstance(v, str):
            _check_text(v)
            out.append(json.dumps(v, ensure_ascii=False))
        elif isinstance(v, list):
            stack.append(("s", "]", 0))
            for i in range(len(v) - 1, -1, -1):
                stack.append(("v", v[i], depth + 1))
                if i:
                    stack.append(("s", ",", 0))
            stack.append(("s", "[", 0))
        elif isinstance(v, dict):
            if not all(isinstance(k, str) for k in v):
                raise NotCanonical("object member names must be strings")
            keys = sorted(v, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
            stack.append(("s", "}", 0))
            for i in range(len(keys) - 1, -1, -1):
                _check_text(keys[i])
                stack.extend((("v", v[keys[i]], depth + 1), ("s", ":", 0), ("s", json.dumps(keys[i], ensure_ascii=False), 0)))
                if i:
                    stack.append(("s", ",", 0))
            stack.append(("s", "{", 0))
        else:
            raise NotCanonical(f"not a JSON value of this domain: {type(v).__name__}")
    return "".join(out).encode("utf-8")


def _check_text(s):
    if any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        raise NotCanonical("lone surrogate")


def _pairs(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise NotCanonical(f"duplicate member {k!r}")
        d[k] = v
    return d


def _constant(name):
    raise NotCanonical(f"not JSON: {name}")


def _float(text):
    raise NotCanonical("floats are not admitted")


def loads(raw):
    """Parse bytes that MUST be the canonical encoding of what they parse to."""
    if not isinstance(raw, (bytes, bytearray)):
        raise NotCanonical("bytes expected")
    raw = bytes(raw)
    if raw.count(b"[") + raw.count(b"{") > MAX_DEPTH * 4 and _depth(raw) > MAX_DEPTH:
        raise NotCanonical("nested too deep")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as e:
        raise NotCanonical(f"not JSON: {type(e).__name__}") from None
    if canon(value) != raw:
        raise NotCanonical("bytes are not canonical")
    return value


def _depth(raw):
    depth = best = 0
    in_str = esc = False
    for b in raw:
        if in_str:
            if esc:
                esc = False
            elif b == 0x5C:
                esc = True
            elif b == 0x22:
                in_str = False
        elif b == 0x22:
            in_str = True
        elif b in (0x5B, 0x7B):
            depth += 1
            best = max(best, depth)
        elif b in (0x5D, 0x7D):
            depth -= 1
    return best


def digest(data):
    return hashlib.sha256(data).hexdigest()


def doc_id(value):
    return digest(canon(value))
