"""Observations: a reader's signed word about a record, one form for every kind.

An observer that signs what it observed becomes a witness: its observation is a record others can read. Every kind
here is an attest `{target, verdict: KIND, ...}` that no guard's match holds, so none of them credits anything:

    react   a reaction: integer dimensions (agree -100..100; confidence, importance, evidence 0..100) and a note
    seen    a view: the reader saw this version, under which lens, at which root of its store
    adopt   an adoption: the reader draws its pages with this lens version (lens.py), wherever the lens lives

Each kind says which fields it carries and where it is filed: `mine` (the reader's own store, whatever store the
record is in; refused when that store is not read; the record's own store when the reader names none) or `record`
(the store holding the record). Every kind here is the reader's, so every one is `mine`: a reader adopts a lens it
cannot write to (Codex's observer pack, OBS-P01). A new kind is one entry here, not a new code path."""
from warrant import shapes as S
from warrant_agent import voices as VC

DIMENSIONS = (("agree", -100, 100, "згода"), ("confidence", 0, 100, "впевненість"),
              ("importance", 0, 100, "важливість"), ("evidence", 0, 100, "якість доказу"))
NOTE_MAX = 4000


def dims(body):
    return {k: body[k] for k, lo, hi, _ in DIMENSIONS if type(body.get(k)) is int and lo <= body[k] <= hi}


def dimensions_text(body):
    d = dims(body)
    return ", ".join(f"{n} {d[x]:+d}" if x == "agree" else f"{n} {d[x]}" for x, _, _, n in DIMENSIONS if x in d)


def _react(rep, target, form):
    out = {}
    for k, lo, hi, _ in DIMENSIONS:
        raw = form.get(k, "")
        if raw == "":
            continue
        try:
            n = int(raw)
        except ValueError:
            return None, f"{k} is not an integer"
        if not lo <= n <= hi:
            return None, f"{k} lies outside {lo}..{hi}"
        out[k] = n
    note = form.get("note", "").strip()
    if len(note) > NOTE_MAX:
        return None, f"a note is at most {NOTE_MAX} characters"
    if note:
        out["note"] = note
    if not out:
        return None, "a reaction names one dimension or a note"
    return out, None


def _seen(rep, target, form):
    lens_id = form.get("lens", "builtin")
    if lens_id != "builtin" and not S.hex64(lens_id):
        return None, "lens is builtin or a lens version's id"
    return {"lens": lens_id, "root": rep["snapshot"]}, None


def _adopt(rep, target, form):
    from warrant_agent import lens as LZ
    r = rep["_recs"][target]
    if r["kind"] != "entity" or r.get("schema") != LZ.LENS:
        return None, "only a lens version is adopted"
    why = LZ.problem(r["body"])
    return ({}, None) if why is None else (None, f"this lens is not drawn: {why}")


class Kind:
    def __init__(self, verb, into, fields, rest=lambda body: ""):
        self.verb, self.into, self.fields, self.rest = verb, into, fields, rest


KINDS = {"react": Kind("відреагував", "mine", _react, dimensions_text),
         "seen": Kind("переглянув", "mine", _seen),
         "adopt": Kind("прийняв для себе лінзу", "mine", _adopt)}


def body(kind, rep, target, form):
    """(the record's body, None) or (None, why not)."""
    extra, why = KINDS[kind].fields(rep, target, form)
    return (None, why) if extra is None else ({"target": target, "verdict": kind, **extra}, None)


def verdict_of(rep, x):
    """The verdict of an item of a lineage page: carried by an item from another store, else its record's."""
    if "verdict" in x:
        return x["verdict"]
    r = rep["_recs"].get(x["id"])
    return r["body"].get("verdict") if r and r["kind"] == "attest" else None


def elsewhere(reports, store, d):
    """{version id: [item]} of the observations and the challenges filed in other stores on this lineage's versions (a
    reader's own store holds observations for records of every other one; the commons holds the voices of agents with
    no rights, commons.py), each naming its store. A challenge from another store is a voice from outside: this store's
    rules do not count it, a reader's overlay may."""
    vs, out = {v["id"] for v in d["versions"]}, {}
    for name, r in sorted(reports.items()):
        if name == store or "_error" in r:
            continue
        for i in sorted({i for v in vs for i in _by_target(r).get(v, [])}):
            signed = r.get("_basis", {}).get(i) == "SIGNED"
            item = _item(name, i, r["_recs"][i], VC.keys_of(r.get("_trust"), r["_recs"][i]["actor"]) if signed else set())
            if item is not None:
                out.setdefault(r["_recs"][i]["body"]["target"], []).append(item)
    return out


def _by_target(r):
    """{target: [record ids]} of a report's attests and challenges, built once and kept on the report."""
    if "_by_target" not in r:
        idx = {}
        for i, x in r["_recs"].items():
            if x["kind"] in ("attest", "challenge") and isinstance(x["body"].get("target"), str):
                idx.setdefault(x["body"]["target"], []).append(i)
        r["_by_target"] = idx
    return r["_by_target"]


def _item(name, i, x, keys=frozenset()):
    """A record of store `name` about a version, as a lineage page's item: an observation, or a challenge (a voice from
    outside, never counted by the page's store); None for anything else."""
    b = x["body"]
    kind = KINDS.get(b.get("verdict"))
    if x["kind"] == "attest" and kind is not None:
        return {"id": i, "at": x["at"], "challenge": None, "note": b.get("note"), "store": name, "verdict": b["verdict"], "keys": sorted(keys),
                "sentence": (x["actor"], f"{kind.verb} (у {name})", "", kind.rest(b))}
    if x["kind"] == "challenge":
        # a voice from outside (the commons, or any other store): shown, never counted by this store's rules
        return {"id": i, "at": x["at"], "note": None, "store": name, "verdict": None, "keys": sorted(keys),
                "challenge": {"target": b["target"], "counted": False, "stands": False, "replays": [], "outside": name},
                "sentence": (x["actor"], f"заперечив (у {name})", "", str(b.get("statement", "")))}
    return None
