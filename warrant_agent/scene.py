"""Scenes: a lineage drawn as a map, its geometry a declared function of named fields.

A lens's card may hold a `scene`: which field each visual channel shows. Every channel takes one value from a fixed
list, so every coordinate, size and colour has a named source and the legend is derived from the bindings, never
drawn by hand. The layout is deterministic: the same lineage, receiver and lens give the same SVG, byte for byte.
Nothing is computed by force or chance; "why is this node here" is answered by the legend.

    x      time (the rank of each record's `at`) | order (versions, each followed by what was filed on it)
    y      version (one row per version, its activity around it) | kind (a row per kind of record)
    size   standing (1 + counted challenges standing on a version) | attests (1 + attests on it) | none
    color  reliance (a version's guard, a challenge counted or not) | kind | actor
    shape  kind | none

The floor no scene decides: every node carries its kind's glyph (meaning is never colour alone), a counted challenge
that stands is never drawn smaller than what it stands against, the legend is always drawn, and whatever is folded
away by the node budget is named with its count. The SVG is generated here from data: no script, no external
resource, every text escaped; a scene in a record is never rendered as markup."""
import hashlib
import html

CHANNELS = {"x": ("time", "order"), "y": ("version", "kind"), "size": ("standing", "attests", "none"),
            "color": ("reliance", "kind", "actor"), "shape": ("kind", "none")}
BUILTIN = {"x": "order", "y": "kind", "size": "standing", "color": "reliance", "shape": "kind"}
LEGEND = {"time": "час (порядок за at)", "order": "версії, кожна з поданим на неї", "version": "рядок на версію",
          "kind": "вид запису", "standing": "1 + заперечення, що стоять", "attests": "1 + атестації",
          "none": "однаково", "reliance": "охоронець версії; заперечення зараховане чи ні", "actor": "автор"}
GLYPH = {"entity": "◆", "attest": "✓", "challenge": "✗"}
MAX_NODES = 300
STEP_X, STEP_Y, R = 52, 64, 12
E = html.escape


def problem(scene):
    """None when this interpreter draws the scene; else why not."""
    if not isinstance(scene, dict) or set(scene) - set(CHANNELS):
        return f"a scene binds some of {sorted(CHANNELS)} and nothing else"
    for k, v in scene.items():
        if v not in CHANNELS[k]:
            return f"{k} is one of {list(CHANNELS[k])}"
    return None


def bindings(card):
    """The card's scene with the built-in bindings for what it leaves out."""
    return dict(BUILTIN, **(card.get("scene") or {}))


def nodes_of(rep, d):
    """[{id, kind, at, row, version, actor, standing, attests, counted, stands, target}] of a lineage page: its versions
    and what was filed on each (its `on`, reactions from other stores included), in a fixed order."""
    out = []
    for vi, v in enumerate(sorted(d["versions"], key=lambda v: (v["record"]["at"], v["id"]))):   # left to right in time
        rec, on = v["record"], v["on"]
        held = sum(1 for x in on if x["challenge"] and x["challenge"].get("counted") and x["challenge"].get("stands"))
        out.append({"id": v["id"], "kind": "entity", "at": rec["at"], "version": vi, "actor": rec["actor"],
                    "guard": v["guard"].get("guard", "NONE"), "standing": held,
                    "attests": sum(1 for x in on if not x["challenge"]), "target": None, "counted": False, "stands": False})
        for x in on:
            c = x["challenge"]
            r = rep["_recs"].get(x["id"])
            kind = "challenge" if c is not None else (r["kind"] if r else "attest")
            out.append({"id": x["id"], "kind": kind, "at": x["at"], "version": vi, "actor": x["sentence"][0],
                        "guard": None, "standing": 0, "attests": 0, "target": v["id"],
                        "counted": bool(c and c.get("counted")), "stands": bool(c and c.get("stands"))})
    return out


def _palette(word):
    return "#%06x" % (int(hashlib.sha256(word.encode()).hexdigest()[:6], 16) | 0x404040)


OK, WARN, BAD, MUTE, ACC = "var(--ok)", "var(--warn)", "var(--bad)", "var(--mute)", "var(--acc)"
COLORS = {"MET": OK, "PENDING": WARN, "NONE": MUTE, "INVALID": BAD, "entity": ACC, "attest": OK, "challenge": BAD}


def _color(n, how):
    if how == "kind":
        return COLORS[n["kind"]]
    if how == "actor":
        return _palette(n["actor"])
    if n["kind"] == "entity":
        return COLORS.get(n["guard"], MUTE)
    if n["kind"] == "challenge":
        return BAD if n["counted"] and n["stands"] else MUTE
    return ACC


def layout(nodes, b):
    """{id: (x, y, r)}: each coordinate a function of the bound fields, then the floor's size rule."""
    folded = max(0, len(nodes) - MAX_NODES)
    nodes = nodes[:MAX_NODES]
    rank = {n["id"]: i for i, n in enumerate(sorted(nodes, key=lambda n: (n["at"], n["id"])))}
    rows = {"entity": 0, "attest": 1, "challenge": 2}
    pos = {}
    for i, n in enumerate(nodes):
        x = rank[n["id"]] if b["x"] == "time" else i
        if b["y"] == "version":
            y = n["version"] * 3 + {"entity": 0, "attest": 1}.get(n["kind"], 2)
        else:
            y = rows.get(n["kind"], 1)
        size = {"standing": 1 + n["standing"], "attests": 1 + n["attests"], "none": 1}[b["size"]]
        pos[n["id"]] = [40 + x * STEP_X, 30 + y * STEP_Y, R + 3 * (min(size, 6) - 1)]
    for n in nodes:                     # the floor: a counted challenge that stands is never smaller than its target
        if n["kind"] == "challenge" and n["counted"] and n["stands"] and n["target"] in pos:
            pos[n["id"]][2] = max(pos[n["id"]][2], pos[n["target"]][2])
    return {k: tuple(v) for k, v in pos.items()}, folded


def _edges(shown, pos):
    """The lines, drawn under the nodes: each version to the next, each filed record to its target (dashed for a
    challenge)."""
    out, prev = [], None
    for n in shown:
        if n["kind"] == "entity":
            if prev is not None:
                (x0, y0, _), (x1, y1, _) = pos[prev], pos[n["id"]]
                out.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="var(--fg)" stroke-width="2"/>')
            prev = n["id"]
        elif n["target"] in pos:
            (x0, y0, _), (x1, y1, _) = pos[n["target"]], pos[n["id"]]
            dash = ' stroke-dasharray="4 3"' if n["kind"] == "challenge" else ""
            out.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="var(--mute)"{dash}/>')
    return out


def _shape(n, x, y, r, b):
    fill = _color(n, b["color"])
    if b["shape"] == "kind" and n["kind"] == "entity":
        return f'<rect x="{x - r}" y="{y - r}" width="{2 * r}" height="{2 * r}" rx="3" fill="{fill}"/>'
    if b["shape"] == "kind" and n["kind"] == "challenge":
        return f'<polygon points="{x},{y - r} {x + r},{y + r} {x - r},{y + r}" fill="{fill}"/>'
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"/>'


def _node(n, pos, b, store, describe):
    x, y, r = pos[n["id"]]
    glyph = GLYPH.get(n["kind"], "·")                           # the floor: the kind is never colour alone
    return (f'<a href="/l/{E(store)}/{E(n["id"])}"><g><title>{E(describe(n["id"]))}</title>{_shape(n, x, y, r, b)}'
            f'<text x="{x}" y="{y + 5}" text-anchor="middle" font-size="14" fill="var(--bg)">{glyph}</text></g></a>')


def svg(rep, store, d, card, describe):
    """The scene of a lineage page as a static SVG string, and its legend as HTML; `describe(id)` gives a node's title."""
    b = bindings(card)
    nodes = nodes_of(rep, d)
    pos, folded = layout(nodes, b)
    shown = [n for n in nodes if n["id"] in pos]
    w = max(x for x, _, _ in pos.values()) + 60 if pos else 200
    h = max(y for _, y, _ in pos.values()) + 50 if pos else 80
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
             f'aria-label="карта лінії" class="scene">']
    parts += _edges(shown, pos) + [_node(n, pos, b, store, describe) for n in shown] + ["</svg>"]
    legend = ("<p class='rest legend'>карта: " + " · ".join(f"{k} = {E(LEGEND[v])}" for k, v in b.items())
              + " · ◆ версія ✓ атестація ✗ заперечення"
              + (f" · <b>згорнуто {folded} вузлів</b> (бюджет {MAX_NODES})" if folded else "") + "</p>")
    return "".join(parts), legend


def moved(rep, d, a, b):
    """[(id, from, to)] of the nodes two cards' scenes place differently, and [(channel, a, b)] of their bindings."""
    nodes = nodes_of(rep, d)
    pa, _ = layout(nodes, bindings(a))
    pb, _ = layout(nodes, bindings(b))
    ba, bb = bindings(a), bindings(b)
    return ([(i, pa[i], pb[i]) for i in sorted(pa) if i in pb and pa[i] != pb[i]],
            [(k, ba[k], bb[k]) for k in CHANNELS if ba[k] != bb[k]])
