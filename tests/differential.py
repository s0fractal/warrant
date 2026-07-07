#!/usr/bin/env python3
"""Differential canonicalization harness (SPEC line 5: two independent
implementations MUST agree on every WarrantID).

For a battery of adversarial-but-legal bodies, run BOTH the Python and Go
`canon` commands and assert byte-identical canonical bytes and WarrantIDs.
This is the test that catches JCS-escaping and width divergences (the U+0008 /
U+000C split and the note-length byte-vs-codepoint split) that the five §8
example vectors never exercise. Exits nonzero on any disagreement.

Usage:  python3 tests/differential.py
Env:    WARRANT_GO=path/to/warrant-go  (default: ./impl-go/warrant-go)
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = [sys.executable, os.path.join(ROOT, "impl", "warrant.py"), "canon"]
GO = [os.environ.get("WARRANT_GO", os.path.join(ROOT, "impl-go", "warrant-go")), "canon"]


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
    yield ("emoji-astral", body(note="deploy \U0001F680 ship \U0001F525"))
    yield ("quote-backslash", body(note='he said "\\x" \\ end'))
    yield ("del+c1", body(note="a" + chr(0x7F) + "b" + chr(0x9F) + "c"))
    # Control chars in actor id and in a prose reason, not just the note.
    yield ("ctrl-in-actor", body(actor="a\tgent" + chr(11) + "@v"))
    yield ("ctrl-in-prose", body(extra_reason={"kind": "prose", "text": "line1" + chr(8) + "line2"}))
    # Large integer ts (no float — integers only per SPEC §2).
    yield ("large-ts", body(ts=9007199254740991))
    # Key-order insensitivity (canon sorts): same body, keys shuffled.
    b = body(note="order")
    yield ("shuffled-keys", dict(reversed(list(b.items()))))


def run(cmd, path):
    out = subprocess.run(cmd + [path], capture_output=True, text=True)
    if out.returncode != 0:
        return None, out.stderr.strip()
    return json.loads(out.stdout), None


def main():
    fails = 0
    total = 0
    for name, b in cases():
        total += 1
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=True)
            path = f.name
        try:
            py, pyerr = run(PY, path)
            go, goerr = run(GO, path)
        finally:
            os.unlink(path)
        if py is None or go is None:
            print(f"ERROR {name}: py={pyerr!r} go={goerr!r}")
            fails += 1
            continue
        if py == go:
            print(f"OK    {name}  {py['warrant_id'][:16]}…")
        else:
            fails += 1
            print(f"FAIL  {name}")
            print(f"      PY id={py['warrant_id']}")
            print(f"      GO id={go['warrant_id']}")
            print(f"      PY canon={py['canon_hex']}")
            print(f"      GO canon={go['canon_hex']}")
    print(f"\nDIFFERENTIAL: {'ALL AGREE' if not fails else 'DIVERGENCE'} "
          f"({total - fails}/{total})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
