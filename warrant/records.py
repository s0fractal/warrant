"""The six record types of SPEC §3: shapes, construction and signing.

Every validator checks JSON types before set membership, and refuses unknown or
missing members, so a record is either exactly one of these shapes or invalid."""
import re

from . import jcs as C
from . import keys as K

VERSION = "2"
TYPES = ("duty", "transition", "accept", "observation", "grant", "challenge")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SUBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})$")
BASES = ("ATTESTED", "OBSERVED", "REPLAYED")
ACTS = ("discharge", "impossible", "release", "delegate", "substitute", "revalidate")
GRANT_ACTS = ("release",)
RUNTIMES = ("sigma-book1-0.6.0/hash-thunk/leftmost-outermost",
            "sigma-resume-draft/ski+Y+M+W/hash-thunk/leftmost-outermost")
TRIGGER_KINDS = ("subject_changed", "duty_not_discharged")
MAX_LIST = 256
MAX_TEXT = 4000


class Invalid(ValueError):
    """A record that is not exactly one of the shapes of SPEC §3."""


# ---------------------------------------------------------------- small checks

def _need(ok, why):
    if not ok:
        raise Invalid(why)


def _fields(obj, required, optional=(), what="object"):
    _need(isinstance(obj, dict), f"{what} must be an object")
    keys = set(obj)
    missing, extra = set(required) - keys, keys - set(required) - set(optional)
    _need(not missing, f"{what} lacks {sorted(missing)}")
    _need(not extra, f"{what} has unknown members {sorted(extra)}")


def _text(v, what, limit=MAX_TEXT, empty=False):
    _need(isinstance(v, str) and (empty or v) and len(v) <= limit, f"{what} must be a string ≤ {limit}")


def _int(v, what, low=None):
    _need(type(v) is int and (low is None or v >= low), f"{what} must be an integer" + (f" ≥ {low}" if low is not None else ""))


def _enum(v, choices, what):
    _need(isinstance(v, str) and v in choices, f"{what} must be one of {list(choices)}")


def _hex(v, what):
    _need(isinstance(v, str) and HEX64.match(v) is not None, f"{what} must be a hex64")


def _list(v, what, item, unique=True, nonempty=False, sorted_=False):
    _need(isinstance(v, list) and len(v) <= MAX_LIST, f"{what} must be a list")
    _need(not nonempty or v, f"{what} must not be empty")
    for x in v:
        item(x, f"{what} item")
    if unique:
        _need(len({C.canon(x) for x in v}) == len(v), f"{what} has duplicates")
    if sorted_:
        _need(v == sorted(v), f"{what} must be sorted")


def _actor(v, what):
    _text(v, what, limit=200)


def _hexes(v, what, **kw):
    _list(v, what, _hex, **kw)


def _actors(v, what, **kw):
    _list(v, what, _actor, **kw)


def _subject(v, what):
    _need(v is None or (isinstance(v, str) and SUBJECT.match(v) is not None), f"{what} must be null or a revision/blob id")


# ---------------------------------------------------------------- bodies

def _condition(c):
    _need(isinstance(c, dict) and len(c) == 1, "condition must have exactly one kind")
    kind, v = next(iter(c.items()))
    _enum(kind, ("attest", "observe", "compute"), "condition kind")
    if kind == "attest":
        _fields(v, (), what="attest condition")
    elif kind == "observe":
        _fields(v, ("observers", "probe", "expect", "fresh_for"), what="observe condition")
        _actors(v["observers"], "observers", nonempty=True)
        _hex(v["probe"], "probe")
        _text(v["expect"], "expect", empty=True)
        _need(v["fresh_for"] is None or (type(v["fresh_for"]) is int and v["fresh_for"] > 0), "fresh_for must be null or > 0")
    else:
        _fields(v, ("runtime", "input", "environment", "expect"), what="compute condition")
        _enum(v["runtime"], RUNTIMES, "runtime")
        for k in ("input", "environment", "expect"):
            _hex(v[k], k)


def _duty(b, actor):
    _fields(b, ("statement", "holder", "owed_to", "accept_by", "release_by", "condition", "schedule",
                "requires", "serves", "answers", "subject"), what="duty")
    _text(b["statement"], "statement", limit=400)
    _actor(b["holder"], "holder")
    _need(b["holder"] == actor, "a duty is filed by its holder")
    _actors(b["owed_to"], "owed_to", nonempty=True)
    _actors(b["accept_by"], "accept_by")
    _actors(b["release_by"], "release_by")
    _condition(b["condition"])
    if "attest" in b["condition"]:
        _need(set(b["accept_by"]) - {b["holder"]}, "an attested duty needs an acceptor other than its holder")
    s = b["schedule"]
    if s is not None:
        _fields(s, ("start", "every"), what="schedule")
        _int(s["start"], "schedule.start", 0)
        _int(s["every"], "schedule.every", 1)
    _hexes(b["requires"], "requires")
    _hexes(b["serves"], "serves")
    _need(b["answers"] is None or (isinstance(b["answers"], str) and QREF.match(b["answers"])), "answers must be null or a question reference")
    _subject(b["subject"], "subject")


def trigger_problem(t):
    try:
        _trigger(t, "trigger")
        return None
    except Invalid as e:
        return str(e)


def _trigger(t, what):
    _need(isinstance(t, dict) and isinstance(t.get("kind"), str), f"{what} needs a kind")
    _enum(t["kind"], TRIGGER_KINDS, f"{what} kind")
    operand = {"subject_changed": "baseline", "duty_not_discharged": "duty"}[t["kind"]]
    _fields(t, ("kind", operand), what=t["kind"])
    _hex(t[operand], operand)


def _item(m, evidence):
    _need(isinstance(m, dict), "item must be an object")
    _enum(m.get("act"), ACTS, "act")
    act = m["act"]
    optional = {"discharge": ("period", "triggers"), "impossible": ("triggers",), "release": (),
                "delegate": (), "substitute": (), "revalidate": ("triggers",)}[act]
    required = ("duty", "act", "evidence") + {"delegate": ("to",), "substitute": ("to",),
                                               "revalidate": ("revalidates",)}.get(act, ())
    _fields(m, required, optional, what=f"{act} item")
    _hex(m["duty"], "item duty")
    _hexes(m["evidence"], "item evidence")
    _need(set(m["evidence"]) <= set(evidence), "an item cites evidence its transition does not carry")
    if "period" in m:
        _int(m["period"], "period", 0)
    if "to" in m:
        _actor(m["to"], "to")
    if "revalidates" in m:
        _hexes(m["revalidates"], "revalidates", nonempty=True)
    if "triggers" in m:
        _list(m["triggers"], "triggers", _trigger, nonempty=False)


def _question(q, what):
    _fields(q, ("text", "scope"), what=what)
    _text(q["text"], "question text")
    _need(q["scope"] is None or (isinstance(q["scope"], str) and q["scope"]), "question scope")


def _transition(b, actor):
    _fields(b, ("basis", "evidence", "relied_on", "established", "residual", "opened", "closes", "subject",
                "supersedes", "triggers"), what="transition")
    _enum(b["basis"], BASES, "basis")
    _hexes(b["evidence"], "evidence")
    _hexes(b["relied_on"], "relied_on")
    _list(b["established"], "established", _text)
    _list(b["residual"], "residual", _text)
    _list(b["opened"], "opened", _question)
    _need(isinstance(b["closes"], list) and len(b["closes"]) <= MAX_LIST, "closes must be a list")
    for m in b["closes"]:
        _item(m, b["evidence"])
    _subject(b["subject"], "subject")
    _hexes(b["supersedes"], "supersedes")
    _list(b["triggers"], "triggers", _trigger)


def _accept(b, actor):
    _fields(b, ("transition", "item", "evidence", "support"), what="accept")
    _hex(b["transition"], "transition")
    _need(b["item"] is None or (type(b["item"]) is int and b["item"] >= 0), "item must be null or an index")
    _hexes(b["evidence"], "evidence")
    _hexes(b["support"], "support")


def _observation(b, actor):
    _fields(b, ("target", "probe", "window", "result", "raw"), what="observation")
    _text(b["target"], "target", limit=400)
    _hex(b["probe"], "probe")
    w = b["window"]
    _need(isinstance(w, list) and len(w) == 2 and all(type(x) is int and x >= 0 for x in w) and w[0] <= w[1],
          "window must be [from, to] with from ≤ to")
    _text(b["result"], "result", empty=True)
    _hexes(b["raw"], "raw")


def _grant(b, actor):
    _fields(b, ("grantee", "acts", "delegable", "duties", "expires", "parent"), what="grant")
    _actor(b["grantee"], "grantee")
    _list(b["acts"], "acts", lambda v, w: _enum(v, GRANT_ACTS, w), nonempty=True, sorted_=True)
    _list(b["delegable"], "delegable", lambda v, w: _enum(v, GRANT_ACTS, w), sorted_=True)
    _need(set(b["delegable"]) <= set(b["acts"]), "delegable must be a subset of acts")
    _hexes(b["duties"], "duties", nonempty=True, sorted_=True)
    _need(b["expires"] is None or (type(b["expires"]) is int and b["expires"] >= 0), "expires")
    _need(b["parent"] is None or (isinstance(b["parent"], str) and HEX64.match(b["parent"])), "parent")


def _challenge(b, actor):
    _fields(b, ("target", "item", "statement", "evidence"), what="challenge")
    _hex(b["target"], "target")
    _need(b["item"] is None or (type(b["item"]) is int and b["item"] >= 0), "item must be null or an index")
    _text(b["statement"], "statement")
    _hexes(b["evidence"], "evidence")


BODIES = {"duty": _duty, "transition": _transition, "accept": _accept, "observation": _observation,
          "grant": _grant, "challenge": _challenge}


def check(record):
    """Raise Invalid unless `record` is exactly one record shape of SPEC §3."""
    _fields(record, ("warrant", "type", "actor", "at", "body"), what="record")
    _need(record["warrant"] == VERSION, "record version must be \"2\"")
    _enum(record["type"], TYPES, "type")
    _actor(record["actor"], "actor")
    _int(record["at"], "at", 0)
    BODIES[record["type"]](record["body"], record["actor"])
    if record["type"] == "observation":
        _need(record["body"]["window"][1] <= record["at"], "an observation cannot be filed before it ended")
    C.canon(record)


# ---------------------------------------------------------------- construction

def record(rtype, actor, at, body):
    r = {"warrant": VERSION, "type": rtype, "actor": actor, "at": at, "body": body}
    check(r)
    return r


def record_id(r):
    return C.doc_id(r)


def sign(r, key):
    """The stored bytes of record `r`, signed by `key`: (id, bytes)."""
    check(r)
    rid = record_id(r)
    env = {"record": r, "sig": {"key": key.id, "ed25519": key.sign(K.sig_message(rid))}}
    return rid, C.canon(env)


def duty(holder, statement, owed_to, condition, accept_by=(), release_by=(), schedule=None, requires=(),
         serves=(), answers=None, subject=None):
    return {"statement": statement, "holder": holder, "owed_to": list(owed_to), "accept_by": list(accept_by),
            "release_by": list(release_by), "condition": condition, "schedule": schedule,
            "requires": list(requires), "serves": list(serves), "answers": answers, "subject": subject}


def item(duty_id, act, evidence=(), **extra):
    m = {"duty": duty_id, "act": act, "evidence": list(evidence)}
    m.update(extra)
    return m


def transition(basis, evidence=(), closes=(), established=(), residual=(), opened=(), relied_on=(),
               subject=None, supersedes=(), triggers=()):
    return {"basis": basis, "evidence": list(evidence), "relied_on": list(relied_on),
            "established": list(established), "residual": list(residual),
            "opened": [dict(q) for q in opened], "closes": list(closes), "subject": subject,
            "supersedes": list(supersedes), "triggers": list(triggers)}


def accept(transition_id, item_index, evidence, support=()):
    return {"transition": transition_id, "item": item_index, "evidence": list(evidence), "support": list(support)}


def observation(target, probe, window, result, raw=()):
    return {"target": target, "probe": probe, "window": list(window), "result": result, "raw": list(raw)}


def grant(grantee, acts, duties, delegable=(), expires=None, parent=None):
    return {"grantee": grantee, "acts": sorted(acts), "delegable": sorted(delegable), "duties": sorted(duties),
            "expires": expires, "parent": parent}


def challenge(target, statement, evidence=(), item_index=None):
    return {"target": target, "item": item_index, "statement": statement, "evidence": list(evidence)}
