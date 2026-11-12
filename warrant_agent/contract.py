"""A lens's contract, checked on the page it drew (P05 of the observer pack).

A lens card promises what a lineage page shows: each declared member of each version that has a value, and, with
`activity: shown`, every attest and challenge on it (`lens.visible`). The floor promises what no lens decides: the
state, the reliance, every counted challenge that stands, UNATTESTED, the lens's name. The renderer marks what it
drew (`data-f`, `data-a`, `data-c`, `data-floor`); `check` reads the marks back and names every promise the page
does not keep. A broken promise is replayable, so it is a fact about the page, not an opinion about the lens: anyone
with the same store, root and lens gets the same page and the same answer (`python -m warrant_agent.contract`).
What it does not establish: that the marks are where a reader looks, or that a kept promise reads well."""

import argparse
import html
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
_N = re.compile(r'data-n="([^"]*)"')
_FOLDED = re.compile(r'data-folded="([0-9]{1,9})"')
_R = re.compile(r'data-r="([^" ]*) ([^"]*)"')           # the record id, then the store's name
_OMIT = re.compile(r'data-omit="([a-z]+) ([0-9]{1,9})"')
_UNREAD = re.compile(r'data-unread="([^"]*)"')


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


def map_check(d, standing_, nodes, page):
    """[(part, item)] the map does not keep: the floor's and the standing challenges' promises as on the lineage page,
    and every node of `nodes` neither drawn nor counted in the fold it names."""
    _, floor, held = shown(page)
    drawn = {i for i in _N.findall(page) if S.hex64(i)}
    folded = max([int(n) for n in _FOLDED.findall(page)] or [0])
    missing = sorted({n["id"] for n in nodes} - drawn)
    out = [("floor", x) for x in sorted(set(FLOOR) - floor)]
    out += [("standing", x) for x in sorted({c for c, _ in standing_} - held)]
    if len(missing) != folded:
        out += [("node", x) for x in missing] or [("folded", str(folded))]
    return out


def feed_promise(reports, store=None, actor=None, machines=False, limit=300):
    """(the (store, id) the feed must draw, {reason: how many it must say it left out}, the stores it must name as
    unread), computed from the records: the newest `limit` of every record in scope, newest first by `at`."""
    from warrant_agent import serve as SV
    rows, omit, unread = [], {"machines": 0, "transition": 0, "limit": 0}, set()
    for n, rep in reports.items():
        if store and n != store:
            continue
        if "_error" in rep:
            unread.add(n)
            continue
        for i, r in rep["_recs"].items():
            if actor and r["actor"] != actor:
                continue
            if r.get("schema") == "v2-transition@1":
                omit["transition"] += 1
            elif not machines and SV.is_machine(r["actor"]):
                omit["machines"] += 1
            else:
                rows.append((-r["at"], n, i))
    rows.sort()
    omit["limit"] = max(0, len(rows) - limit)
    return {(n, i) for _, n, i in rows[:limit]}, {k: v for k, v in omit.items() if v}, unread


def feed_check(reports, page, store=None, actor=None, machines=False, limit=300):
    """[(part, item)] of every promise the feed page does not keep; empty when it keeps them all."""
    want, omit, unread = feed_promise(reports, store, actor, machines, limit)
    got = {(html.unescape(n), i) for i, n in _R.findall(page) if S.hex64(i)}
    said = {k: int(v) for k, v in _OMIT.findall(page)}
    out = [("record", f"{n} {i}") for n, i in sorted(want - got)]
    out += [("extra", f"{n} {i}") for n, i in sorted(got - want)]
    out += [("omit", f"{k} {v}") for k, v in sorted(omit.items()) if said.get(k) != v]
    out += [("unread", n) for n in sorted(unread - {html.unescape(x) for x in _UNREAD.findall(page)})]
    return out


def main(argv=None):
    """Draw a page as the server would (the reader's Home, the lens named or chosen) and check its contract: the
    lineage page, `--map` its map, `--feed` the feed (STORE then limits it, LINEAGE is not given). Exit 0 when kept,
    1 with the broken promises as JSON, 2 when the page cannot be drawn."""
    from pathlib import Path
    from warrant_agent import serve as SV
    ap = argparse.ArgumentParser(prog="python -m warrant_agent.contract")
    ap.add_argument("store", nargs="?")
    ap.add_argument("lineage", nargs="?")
    ap.add_argument("--map", action="store_true", help="the lineage's map (/s/), not its page")
    ap.add_argument("--feed", action="store_true", help="the feed (/), of STORE if named, else of every store")
    ap.add_argument("--actor", default=None, help="the feed of one actor")
    ap.add_argument("--machines", action="store_true", help="the feed with automatic actors")
    ap.add_argument("--lens", default=None, help="a lens version id, or builtin (default: the reader's choice)")
    ap.add_argument("--reader", default=None)
    ap.add_argument("--root", action="append", help="a repository to read (repeatable); default: every one Home registers")
    a = ap.parse_args(argv)
    space = SV.Space({Path(r).resolve().name: str(Path(r).resolve()) for r in a.root}) if a.root else SV.Space.from_home()
    if (a.store or not a.feed) and a.store not in space.roots:
        print(json.dumps({"error": f"no store {a.store!r} is read", "stores": sorted(space.roots)}, ensure_ascii=False))
        return 2
    app = SV.App(space, reader=a.reader)
    if a.feed:
        app.page_feed({"store": a.store, "actor": a.actor, "machines": "1" if a.machines else "0"})
        broken, lens = app.last_feed_contract, None
    else:
        if not a.lineage:
            print(json.dumps({"error": "a lineage is needed (or --feed)"}))
            return 2
        draw = app.page_scene if a.map else app.page_lineage
        code, _ = draw(a.store, a.lineage, {"lens": a.lens} if a.lens else {})
        if code != 200:
            print(json.dumps({"error": code}))
            return 2
        broken, lens = app.last_contract["broken"], app.last_contract["lens"]
    print(json.dumps({"lens": lens, "kept": not broken, "broken": broken}, ensure_ascii=False, indent=1))
    return 0 if not broken else 1


if __name__ == "__main__":
    sys.exit(main())
