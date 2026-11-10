"""Lenses: how a lineage page is laid out, kept as records, chosen by the reader.

A lens is an entity of `lens@1` ({state: active | retired, name, applies: a schema name, card, why?}). Its `card` is data, never code: a
layout, the body members each version shows and how, the order of versions and where the attests and challenges on
them appear. Nothing in it is evaluated; a card this interpreter does not know is UNSUPPORTED (with the reason) and
the page falls back to the built-in lens.

The reader chooses: a lens version is applied only when the reader filed `{verdict: "adopt"}` on it in the store
that holds it (the latest adoption wins); a lens nobody asked for, or someone else adopted, is not applied, however
new. A page may also name a lens version outright (`?lens=ID`, a portal: the same root and lens give the same page).

What no lens decides (the floor, drawn by the interpreter above any card): the lineage's state and reliance, every
counted challenge that stands against it with its statement, that completeness is UNATTESTED, and which lens drew
the page."""
import re

LENS = "lens@1"
SCHEMA = {"name": LENS, "fields": {"state": "str", "name": "str", "applies": "str", "card": "obj", "why": "str?"},
          "states": {"active": None, "retired": None}, "closed": [], "successors": {}}
LAYOUTS = ("nested", "flat")              # versions as cards with their activity inside; or one stream by time
SHOWS = ("text", "list", "count")
ORDERS = ("newest", "oldest")
ACTIVITY = ("shown", "hidden")
CARD_KEYS = {"layout", "fields", "order", "activity"}
FIELD_KEYS = {"path", "label", "as"}
PATH = re.compile(r"[a-z][a-z_]{0,39}\Z")
MAX_FIELDS, MAX_LABEL, MAX_NAME = 20, 80, 120


def problem(body):
    """None when the lens body is one this interpreter draws; else why not (it is then UNSUPPORTED)."""
    if not isinstance(body, dict):
        return "a lens body is an object"
    if body.get("state") != "active":
        return "a lens is drawn while its state is active"
    if not (isinstance(body.get("name"), str) and 0 < len(body["name"]) <= MAX_NAME):
        return f"name is a string of 1..{MAX_NAME} characters"
    if not isinstance(body.get("applies"), str):
        return "applies names a schema"
    card = body.get("card")
    if not isinstance(card, dict) or set(card) - CARD_KEYS or not {"layout", "fields"} <= set(card):
        return f"a card has layout and fields, and optionally order and activity: nothing else ({sorted(CARD_KEYS)})"
    for k, allowed in (("layout", LAYOUTS), ("order", ORDERS), ("activity", ACTIVITY)):
        if k in card and card[k] not in allowed:
            return f"{k} is one of {list(allowed)}"
    fields = card["fields"]
    if not isinstance(fields, list) or len(fields) > MAX_FIELDS:
        return f"fields is a list of at most {MAX_FIELDS}"
    for f in fields:
        if not isinstance(f, dict) or set(f) != FIELD_KEYS:
            return f"a field is {{{', '.join(sorted(FIELD_KEYS))}}}"
        if not (isinstance(f["path"], str) and PATH.match(f["path"])):
            return "a field's path is one body member's name (lower case, at most 40 characters)"
        if not (isinstance(f["label"], str) and len(f["label"]) <= MAX_LABEL):
            return f"a field's label is a string of at most {MAX_LABEL} characters"
        if f["as"] not in SHOWS:
            return f"a field shows as one of {list(SHOWS)}"
    return None


def card_of(body):
    """The card with its defaults: {layout, fields, order, activity}."""
    c = body["card"]
    return {"layout": c["layout"], "fields": c["fields"], "order": c.get("order", "newest"),
            "activity": c.get("activity", "shown")}


def lenses(rep):
    """The lens versions of one report: {version id: body}."""
    return {i: r["body"] for i, r in rep["_recs"].items() if r["kind"] == "entity" and r.get("schema") == LENS}


def _depths(recs, actor):
    """{record id: its place in the actor's own chain}: each record's `prev` is the actor's record before it, so a
    later adoption is deeper whatever its `at` says (two in one second tie on `at`)."""
    mine = {i: r for i, r in recs.items() if r["actor"] == actor}
    depth = {}
    for i in mine:
        path, x = [], i
        while x in mine and x not in depth:
            path.append(x)
            x = mine[x].get("prev")
        base = depth.get(x, -1) if x in mine else -1
        for y in reversed(path):
            base += 1
            depth[y] = base
    return depth


def adopted(rep, reader):
    """[((depth, at), version id)] of this report's lens versions the reader adopted, each by its latest adoption
    (the deepest in the reader's chain)."""
    lv, out = lenses(rep), {}
    depth = _depths(rep["_recs"], reader)
    for i, r in rep["_recs"].items():
        b = r["body"]
        if r["kind"] == "attest" and r["actor"] == reader and b.get("verdict") == "adopt" and b.get("target") in lv:
            key = (depth[i], r["at"])
            out[b["target"]] = max(out.get(b["target"], key), key)
    return [(key, v) for v, key in out.items()]


def choose(reports, reader, schema):
    """(store, version id, body) of the lens the reader adopted last for `schema` over every report, or None."""
    best = None
    for name, rep in sorted(reports.items()):
        if "_error" in rep or not reader:
            continue
        lv = lenses(rep)
        for at, v in adopted(rep, reader):
            if lv[v].get("applies") in (schema, "*") and (best is None or (at, v) > best[0]):
                best = ((at, v), name, v, lv[v])
    return None if best is None else best[1:]


def visible(d, card):
    """What a card shows of a lineage page (`serve.lineage`'s answer): {(record id, member)} for each body member
    it draws with a value, and {(record id, "")} for each attest or challenge it shows. The floor and every version's
    head are drawn under any lens, so they are not counted here."""
    out = set()
    for v in d["versions"]:
        body = v["record"]["body"]
        for f in card["fields"]:
            if body.get(f["path"]) not in (None, [], ""):
                out.add((v["id"], f["path"]))
        if card["activity"] == "shown":
            out |= {(x["id"], "") for x in v["on"]}
    return out


def diff(d, a, b):
    """(only under card a, only under card b): what one lens shows of the page that the other does not."""
    va, vb = visible(d, card_of(a)), visible(d, card_of(b))
    return sorted(va - vb), sorted(vb - va)


def presentation(a, b):
    """[(what, under a, under b)] of how two cards draw what they both show differently: the layout, the order of
    versions, the activity, the order of the members, and each shared member's label and form. Two lenses that show
    the same members can still differ here, and a reader sees that difference."""
    ca, cb = card_of(a), card_of(b)
    out = [(k, ca[k], cb[k]) for k in ("layout", "order", "activity") if ca[k] != cb[k]]
    fa, fb = {f["path"]: f for f in ca["fields"]}, {f["path"]: f for f in cb["fields"]}
    shared = [p for p in fa if p in fb]
    if shared != [p for p in fb if p in fa]:
        out.append(("порядок полів", ", ".join(shared), ", ".join(p for p in fb if p in fa)))
    for p in shared:
        for k in ("label", "as"):
            if fa[p][k] != fb[p][k]:
                out.append((f"{p}.{k}", fa[p][k], fb[p][k]))
    return out


def find(reports, version):
    """(store, body) of the lens version `version` in any report, or None (`builtin` is the built-in lens)."""
    if version == "builtin":
        return None, BUILTIN
    for name, rep in sorted(reports.items()):
        if "_error" not in rep:
            b = lenses(rep).get(version)
            if b is not None:
                return name, b
    return None


BUILTIN = {"state": "active", "name": "вбудована", "applies": "*", "card": {
    "layout": "nested", "order": "newest", "activity": "shown",
    "fields": [{"path": "statement", "label": "", "as": "text"}, {"path": "text", "label": "", "as": "text"},
               {"path": "established", "label": "Встановлено", "as": "list"},
               {"path": "residual", "label": "Залишки", "as": "list"},
               {"path": "why", "label": "Чому", "as": "text"}]}}
