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
CARD_KEYS = {"layout", "fields", "order", "activity", "scene"}
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
    if "scene" in card:
        from warrant_agent import scene as SC
        why = SC.problem(card["scene"])
        if why:
            return f"scene: {why}"
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
            "activity": c.get("activity", "shown"), "scene": c.get("scene") or {}}


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


def adopted(reports, reader):
    """[(key, store, version id)] of the lens versions the reader adopted, read over every report: an adoption is the
    reader's own record and may live in any store (the reader's own, most often), the lens in another. Each version
    once, by its latest adoption: `key` is (at, the adoption's place in the reader's chain in its store, its id), so
    two adoptions in one second in one store follow the chain, and across stores the dates decide, then the ids."""
    lv = {}
    for name, rep in sorted(reports.items()):
        if "_error" not in rep:
            for v, b in lenses(rep).items():
                lv.setdefault(v, (name, b))
    out = {}
    for name, rep in sorted(reports.items()):
        if "_error" in rep or not reader:
            continue
        depth = _depths(rep["_recs"], reader)
        for i, r in rep["_recs"].items():
            b = r["body"]
            if r["kind"] == "attest" and r["actor"] == reader and b.get("verdict") == "adopt" and b.get("target") in lv:
                key = (r["at"], depth[i], i)
                if b["target"] not in out or key > out[b["target"]][0]:
                    out[b["target"]] = (key, lv[b["target"]][0])
    return [(key, store, v) for v, (key, store) in out.items()]


def choose(reports, reader, schema):
    """(store holding the lens, version id, body) of the lens the reader adopted last for `schema`, or None."""
    best = None
    for key, store, v in adopted(reports, reader):
        body = reports[store] and lenses(reports[store])[v]
        if body.get("applies") in (schema, "*") and (best is None or key > best[0]):
            best = (key, store, v, body)
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
    """(only under card a, only under card b): what one lens shows of the page that the other does not; the general
    comparison of two views (view.py) with the lens varied and the state held."""
    va, vb = {"visible": visible(d, card_of(a)), "floor": {}}, {"visible": visible(d, card_of(b)), "floor": {}}
    from warrant_agent import view as VW
    found = VW.difference(va, vb)
    return found["vanished"], found["appeared"]


def presentation(a, b):
    """[(what, under a, under b)] of how two cards draw what they both show differently: the layout, the order of
    versions, the activity, the order of the members, and each shared member's label and form. Two lenses that show
    the same members can still differ here, and a reader sees that difference."""
    ca, cb = card_of(a), card_of(b)
    out = [(k, ca[k], cb[k]) for k in ("layout", "order", "activity") if ca[k] != cb[k]]
    from warrant_agent import scene as SC
    sa, sb = SC.bindings(ca), SC.bindings(cb)
    out += [(f"scene.{k}", sa[k], sb[k]) for k in SC.CHANNELS if sa[k] != sb[k]]
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
