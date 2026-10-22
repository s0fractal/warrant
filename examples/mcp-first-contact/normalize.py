#!/usr/bin/env python3
"""Replace the view tokens in the committed transcripts with stable placeholders.

    python3 normalize.py [ROUND_DIR ...]        (default: every round-*/ next to this file)

A view token is a 32-hex local selector of a frozen view in a throwaway fixture
world; it grants nothing (AGENT.md) and the worlds are not kept. Secret scanners
read `"view_token": "<32 hex>"` as a generic high-entropy secret, so each
distinct token of a transcript becomes `<view-NN>` (numbered by first
appearance in that file), everywhere it occurs in that file: results, later
arguments (`view_token`, `based_on`), cursors and the export request ids derived
from a view (`export:<token>:...`). Nothing else is changed; the
scorer does not read view tokens, so every score is unchanged. Idempotent.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN = re.compile(r'view_token\\*"\s*:\s*\\*"([0-9a-f]{32})|export:([0-9a-f]{32}):')


def normalize(path):
    text = path.read_text()
    tokens = list(dict.fromkeys(a or b for a, b in TOKEN.findall(text)))
    for n, tok in enumerate(tokens, 1):
        text = text.replace(tok, f"<view-{n:02d}>")
    if tokens:
        path.write_text(text)
    return len(tokens)


def main(argv):
    sys.path.insert(0, str(HERE))
    from paths import confined
    dirs = [confined(d) for d in argv] or sorted(HERE.glob("round-*"))
    total = sum(normalize(p) for d in dirs for p in sorted(Path(d).glob("*.jsonl")))
    print(f"normalized {total} view tokens")


if __name__ == "__main__":
    main(sys.argv[1:])
