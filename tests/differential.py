#!/usr/bin/env python3
"""Differential canonicalization harness (SPEC line 5: two independent
implementations MUST agree on every WarrantID).

For a battery of adversarial-but-legal bodies, run the Python, Go and Rust
`canon` commands and assert byte-identical canonical bytes and WarrantIDs.
This is the test that catches JCS-escaping and width divergences (the U+0008 /
U+000C split and the note-length byte-vs-codepoint split) that the five §8
example vectors never exercise. Exits nonzero on any disagreement.

THE VECTORS, NOT THIS SCRIPT, ARE NORMATIVE
-------------------------------------------
SPEC §4 used to make this file normative by reference ("a conformant
implementation MUST also agree on the escaping battery in tests/differential.py")
— which asked a third-party implementer to read Python to learn what the format
requires. The battery now lives in `examples/canon-vectors.json` (SPEC §8.4):
each case pins the input body, the canonical UTF-8 bytes (hex) and the
WarrantID, so an implementer can conform without running this harness at all.

This script is the *runner*: it drives each available implementation's `canon`
command over the pinned inputs and asserts (a) all implementations agree with
each other and (b) every one of them reproduces the pinned bytes. Agreement on
a wrong answer is therefore also a failure, which comparison alone could not
catch.

`cases()` below is kept as the generator of record and is cross-checked against
the vector file, so the two cannot silently drift.

Usage:  python3 tests/differential.py
        python3 tests/differential.py --emit   # rewrite examples/canon-vectors.json
Env:    WARRANT_GO=path/to/warrant-go  (default: ./impl-go/warrant-go)
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = [sys.executable, os.path.join(ROOT, "impl", "warrant.py"), "canon"]
GO = [os.environ.get("WARRANT_GO", os.path.join(ROOT, "impl-go", "warrant-go")), "canon"]
# Third independent canonicalizer (Rust); included when built.
_rs = os.environ.get("WARRANT_RS", os.path.join(ROOT, "impl-rs", "target", "release", "warrant-rs"))
RS = [_rs, "canon"]
RS_AVAILABLE = os.path.exists(_rs)

VECTORS = os.path.join(ROOT, "examples", "canon-vectors.json")
VECTORS_TAG = "warrant.canon-vectors@v0"

# Go is REQUIRED here -- a differential suite with one implementation compares
# nothing, so a missing binary must fail. It should fail legibly: this is the
# first command a new implementer runs, and it greeted them with a raw
# FileNotFoundError traceback pointing at a temp path, while the Rust check three
# lines above degrades to a polite skip. Fail loudly is right; fail
# incomprehensibly is not.
if not os.path.exists(GO[0]):
    sys.exit(
        f"warrant-go not found at {GO[0]}\n"
        f"  build it:  (cd {os.path.join(ROOT, 'impl-go')} && go build -o warrant-go .)\n"
        f"  or point:  WARRANT_GO=/path/to/warrant-go python3 tests/differential.py\n"
        f"This suite compares two independent implementations; with one of them "
        f"missing there is nothing to compare, so it stops rather than reporting "
        f"agreement it did not observe.")


def body(note="", actor="agent-x@vendor", extra_reason=None, ts=1751700000):
    b = {
        "warrant": "0.1", "decision": "propose",
        "subject": {"hash": "a" * 64, "note": note},
        "under": ["b" * 64],
        "because": [] if extra_reason is None else [extra_reason],
        "evidence": [], "actor": {"id": actor},
        "prior": [], "ts": ts,
    }
    if not note:
        del b["subject"]["note"]
    return b


def cases():
    # Every control byte 0x00..0x1F in a free-form string — the JCS-escaping surface.
    for cp in range(0x00, 0x20):
        yield (f"ctrl-U+{cp:04X}", body(note="x" + chr(cp) + "y"))
    # The two JCS short-form code points that Go's encoding/json got wrong.
    yield ("backspace+formfeed", body(note="tab" + chr(8) + "in" + chr(12) + "end"))
    # Multibyte / astral / quotes / backslashes.
    yield ("cyrillic-note", body(note="привіт-світ" * 5))
    # Unicode normalization is NOT applied (SPEC §4): NFC vs NFD is different
    # content -> different bytes -> different WarrantID, but every implementation
    # must agree byte-exact on each form (none normalizes).
    import unicodedata as _ud
    _txt = "\u0439 cafe\u0301 \u0133"
    yield ("nfc-precomposed", body(note=_ud.normalize("NFC", _txt)))
    yield ("nfd-decomposed", body(note=_ud.normalize("NFD", _txt)))
    yield ("emoji-astral", body(note="deploy \U0001F680 ship \U0001F525"))
    yield ("quote-backslash", body(note='he said "\\x" \\ end'))
    # SPEC §4 names two escaping traps by name that the battery did not actually
    # exercise until 2026-07-30: Go's encoding/json HTML-escapes < > & by default
    # (it MUST be disabled), and several JS-oriented encoders \u-escape U+2028 /
    # U+2029 (they MUST be emitted raw). A rule stated normatively and vectored
    # nowhere is a rule two implementations can split on silently.
    yield ("html-chars-raw", body(note='<a href="x">1 & 2</a> / done'))
    yield ("line-paragraph-separators", body(note="a\u2028b\u2029c"))
    yield ("del+c1", body(note="a" + chr(0x7F) + "b" + chr(0x9F) + "c"))
    # Control chars in actor id and in a prose reason, not just the note.
    yield ("ctrl-in-actor", body(actor="a\tgent" + chr(11) + "@v"))
    yield ("ctrl-in-prose", body(extra_reason={"kind": "prose", "text": "line1" + chr(8) + "line2"}))
    # Large integer ts (no float — integers only per SPEC §2).
    yield ("large-ts", body(ts=9007199254740991))
    # subject.note at the 200-char boundary in 2-byte code points (400 bytes):
    # the surface of the byte-vs-codepoint length split (F2).
    yield ("note-200-multibyte", body(note="\u0431" * 200))
    yield ("note-201-multibyte", body(note="\u0431" * 201))
    # Key-order insensitivity (canon sorts): same body, keys shuffled.
    b = body(note="order")
    yield ("shuffled-keys", dict(reversed(list(b.items()))))


def run(cmd, path):
    out = subprocess.run(cmd + [path], capture_output=True, text=True)
    if out.returncode != 0:
        return None, out.stderr.strip()
    return json.loads(out.stdout), None


def load_vectors():
    with open(VECTORS, encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("canon_vectors") != VECTORS_TAG:
        sys.exit(f"{VECTORS}: not a {VECTORS_TAG} document")
    return doc["cases"]


def emit():
    """Regenerate examples/canon-vectors.json from cases() using the Python
    canonicalizer. MAINTAINER ACTION: the file is a normative artifact (SPEC
    §8.4) — regenerating it changes what conformance means, so a diff here must
    be reviewed as a spec change, not as test churn."""
    spec = importlib.util.spec_from_file_location(
        "warrant_impl", os.path.join(ROOT, "impl", "warrant.py"))
    W = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(W)
    out = []
    for name, b in cases():
        cb = W.canon(b)
        out.append({"name": name, "body": b, "canon_hex": cb.hex(),
                    "warrant_id": hashlib.sha256(cb).hexdigest()})
    doc = {
        "canon_vectors": VECTORS_TAG,
        "note": ("SPEC §4 escaping/width battery, §8.4. For each case, "
                 "canonical_json(body) MUST equal the bytes in canon_hex and "
                 "SHA-256 of those bytes MUST equal warrant_id. Bodies are "
                 "given with ensure_ascii escaping so this file is pure ASCII; "
                 "the escapes are JSON transport, not canonical output. Every "
                 "control code point U+0000..U+001F appears, plus the JCS "
                 "reimplementation traps: the \\b/\\f short forms, U+2028/29 "
                 "and <>& raw-emission, NFC vs NFD (never normalized), astral "
                 "planes, and the 200-code-point note boundary."),
        "cases": out,
    }
    with open(VECTORS, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=True, indent=2)
        f.write("\n")
    print(f"wrote {VECTORS}: {len(out)} cases")
    return 0


def check_generator_matches_vectors(vectors):
    """The vector file is the normative artifact; cases() is the generator that
    produced it. If they drift, a case added to the code would silently not be
    part of conformance (or vice versa)."""
    gen = {name: b for name, b in cases()}
    vec = {v["name"]: v["body"] for v in vectors}
    if gen == vec:
        return True
    only_gen = sorted(set(gen) - set(vec))
    only_vec = sorted(set(vec) - set(gen))
    changed = sorted(n for n in set(gen) & set(vec) if gen[n] != vec[n])
    print(f"FAIL  generator/vector drift: in cases() only={only_gen} "
          f"in {os.path.basename(VECTORS)} only={only_vec} body-changed={changed}")
    print("      regenerate deliberately:  python3 tests/differential.py --emit")
    return False


def main():
    if "--emit" in sys.argv[1:]:
        return emit()
    vectors = load_vectors()
    fails = 0
    total = 0
    if not check_generator_matches_vectors(vectors):
        fails += 1
    for v in vectors:
        name, b = v["name"], v["body"]
        total += 1
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=True)
            path = f.name
        try:
            py, pyerr = run(PY, path)
            go, goerr = run(GO, path)
            rs, rserr = run(RS, path) if RS_AVAILABLE else (py, None)  # skip if not built
        finally:
            os.unlink(path)
        if py is None or go is None or rs is None:
            print(f"ERROR {name}: py={pyerr!r} go={goerr!r} rs={rserr!r}")
            fails += 1
            continue
        pinned = {"warrant_id": v["warrant_id"], "canon_hex": v["canon_hex"]}
        if py == go == rs == pinned:
            tag = "PY/GO/RS" if RS_AVAILABLE else "PY/GO"
            print(f"OK    {name}  {py['warrant_id'][:16]}…  ({tag} = vector)")
        else:
            fails += 1
            print(f"FAIL  {name}")
            print(f"      PY id={py['warrant_id']}  GO id={go['warrant_id']}  "
                  f"RS id={rs['warrant_id']}  VECTOR id={pinned['warrant_id']}")
            if py == go == rs:
                print("      all implementations AGREE and all disagree with the "
                      "pinned vector — a shared drift comparison alone would miss")
    print(f"\nDIFFERENTIAL: {'ALL AGREE' if not fails else 'DIVERGENCE'} "
          f"({total - fails}/{total} vectors)")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
