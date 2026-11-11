"""A lens's contract, checked on the page it drew (P05 of the observer pack).

A lens card promises what a lineage page shows: each declared member of each version that has a value, and, with
`activity: shown`, every attest and challenge on it (`lens.visible`). The floor promises what no lens decides: the
state, the reliance, every counted challenge that stands, UNATTESTED, the lens's name. The renderer marks what it
drew (`data-f`, `data-a`, `data-c`, `data-floor`); `check` reads the marks back and names every promise the page
does not keep. A broken promise is replayable, so it is a fact about the page, not an opinion about the lens: anyone
with the same store, root and lens gets the same page and the same answer (`python -m warrant_agent.contract`).
What it does not establish: that the marks are where a reader looks, or that a kept promise reads well."""

import argparse
import json
import re
import sys

from warrant import shapes as S
from warrant_agent import lens as LZ

FLOOR = ("state", "reliance", "standing", "unattested", "lens")
_F = re.compile(r'data-f="([^" ]*) ([a-z][a-z_]{0,39})"')       # ids are read as text and kept only if S.hex64
_A = re.compile(r'data-a="([^"]*)"')
_C = re.compile(r'data-c="([^"]*)"')
_FLOOR = re.compile(r'data-floor="([a-z]+)"')


def promise(d, card, standing):
    """What the page must show: (visible as lens.visible names it, the floor's keys, the standing challenge ids)."""
    return LZ.visible(d, card), set(FLOOR), {c for c, _ in standing}


def shown(page):
    """What the page marks as drawn, in the same three parts."""
    return ({(i, k) for i, k in _F.findall(page) if S.hex64(i)} | {(i, "") for i in _A.findall(page) if S.hex64(i)},
            set(_FLOOR.findall(page)), {i for i in _C.findall(page) if S.hex64(i)})


def check(d, card, standing, page):
    """[(part, item)] of every promise the page does not keep; empty when it keeps them all."""
    want, got = promise(d, card, standing), shown(page)
    out = []
    for part, w, g in zip(("visible", "floor", "standing"), want, got):
        out += [(part, x) for x in sorted(w - g)]
    return out


def main(argv=None):
    """Draw the lineage page as the server would (the reader's Home, the lens named or chosen) and check its contract:
    exit 0 when kept, 1 with the broken promises as JSON."""
    from warrant_agent import serve as SV
    ap = argparse.ArgumentParser(prog="python -m warrant_agent.contract")
    ap.add_argument("store")
    ap.add_argument("lineage")
    ap.add_argument("--lens", default=None, help="a lens version id, or builtin (default: the reader's choice)")
    ap.add_argument("--reader", default=None)
    ap.add_argument("--root", action="append", help="a repository to read (repeatable); default: every one Home registers")
    a = ap.parse_args(argv)
    from pathlib import Path
    space = SV.Space({Path(r).resolve().name: str(Path(r).resolve()) for r in a.root}) if a.root else SV.Space.from_home()
    if a.store not in space.roots:
        print(json.dumps({"error": f"no store {a.store!r} is read", "stores": sorted(space.roots)}, ensure_ascii=False))
        return 2
    app = SV.App(space, reader=a.reader)
    code, _ = app.page_lineage(a.store, a.lineage, {"lens": a.lens} if a.lens else {})
    if code != 200:
        print(json.dumps({"error": code}))
        return 2
    broken = app.last_contract
    print(json.dumps({"lens": broken["lens"], "kept": not broken["broken"], "broken": broken["broken"]}, ensure_ascii=False, indent=1))
    return 0 if not broken["broken"] else 1


if __name__ == "__main__":
    sys.exit(main())
