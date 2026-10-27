"""The Warrant 3 record (docs/V3.md §2): one envelope, four kinds, the guard's shape and the
schema field types. Canonical bytes and Ed25519 are Warrant 2's jcs.py and keys.py, unchanged."""
from warrant import jcs as C
from warrant import keys as K
from warrant import shapes as S

VERSION = "3"
KINDS = ("schema", "entity", "attest", "challenge")
MEMBERS = ("warrant", "kind", "actor", "at", "prev", "schema", "lineage", "refs", "guard", "body")
GUARD = ("quorum", "roles", "match", "requires")
SIG_DOMAIN = b"warrant-sig-v3:"
BODY_MAX = 16384
LINE_MAX = 65536
TYPES = ("str", "int", "bool", "strs", "ref", "refs", "obj")
MIGRATION = "migration@1"       # the one schema name the core reserves (§9)


class Invalid(ValueError):
    pass


def need(ok, why):
    if not ok:
        raise Invalid(why)


def is_list(v, item, sorted_=False):
    return isinstance(v, list) and all(item(x) for x in v) and (not sorted_ or v == sorted(set(v)))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def guard_problem(g):
    """Why `g` is not a guard, or None."""
    if not (isinstance(g, dict) and set(g) == set(GUARD)):
        return f"a guard has exactly {list(GUARD)}"
    if not (is_int(g["quorum"]) and g["quorum"] >= 0 and is_list(g["roles"], S.is_actor, True)
            and isinstance(g["match"], dict) and is_list(g["requires"], S.hex64, True)):
        return "guard: quorum >= 0, roles a sorted list of names, match an object, requires sorted ids"
    return None


def check(r):
    """Raise Invalid unless `r` is a well-formed v3 record (its body is checked against its schema
    by the engine, which alone knows the schemas the receiver counts)."""
    need(isinstance(r, dict) and set(r) == set(MEMBERS), f"a record has exactly {list(MEMBERS)}")
    need(r["warrant"] == VERSION and r["kind"] in KINDS, "warrant must be \"3\" and kind one of " + "/".join(KINDS))
    need(S.is_actor(r["actor"]), "actor is not an actor id")
    need(is_int(r["at"]) and r["at"] >= 0, "at is a non-negative integer")
    need(r["prev"] is None or S.hex64(r["prev"]), "prev is null or a record id")
    need(r["lineage"] is None or S.hex64(r["lineage"]), "lineage is null or a record id")
    need(is_list(r["refs"], S.hex64, True), "refs is a sorted list of distinct hex64")
    need(isinstance(r["body"], dict) and len(C.canon(r["body"])) <= BODY_MAX, f"body is an object of at most {BODY_MAX} bytes")
    need(r["guard"] is None or guard_problem(r["guard"]) is None, str(guard_problem(r["guard"])))
    if r["kind"] == "schema":
        need(r["schema"] is None, "a schema record has no schema")
    else:
        need(r["schema"] is None or (isinstance(r["schema"], str) and 0 < len(r["schema"]) <= 100), "schema is a name")
    if r["kind"] == "entity":
        need(r["schema"] is not None, "an entity names its schema")
    if r["kind"] in ("attest", "challenge"):
        need(S.hex64(r["body"].get("target")) and r["body"]["target"] in r["refs"] and r["lineage"] is None
             and r["guard"] is None, "an attest or challenge names body.target, in refs, and has no lineage or guard")


def record(kind, actor, at, body, schema=None, lineage=None, refs=(), guard=None, prev=None):
    r = {"warrant": VERSION, "kind": kind, "actor": actor, "at": at, "prev": prev, "schema": schema,
         "lineage": lineage, "refs": sorted(set(refs)), "guard": guard, "body": body}
    check(r)
    return r


def guard(quorum=0, roles=(), match=None, requires=()):
    return {"quorum": quorum, "roles": sorted(set(roles)), "match": dict(match or {}), "requires": sorted(set(requires))}


def rid(r):
    return C.doc_id(r)


def line(r, key=None):
    """The stored line of `r`, signed by `key` (None: a migrated record, sig null)."""
    i = rid(r)
    sig = None if key is None else {"key": key.id, "ed25519": key.sign(SIG_DOMAIN + bytes.fromhex(i))}
    return i, C.canon({"record": r, "sig": sig}) + b"\n"


def verifies(r_id, sig, public):
    return K.verify(public, sig["ed25519"], SIG_DOMAIN + bytes.fromhex(r_id)) and sig["key"] == K.key_id(public)


def type_ok(t, v):
    """A body value against a schema field type (§4); `?` admits null."""
    if t.endswith("?"):
        if v is None:
            return True
        t = t[:-1]
    return {"str": lambda: isinstance(v, str), "int": lambda: is_int(v), "bool": lambda: isinstance(v, bool),
            "strs": lambda: is_list(v, lambda x: isinstance(x, str)), "ref": lambda: S.hex64(v),
            "refs": lambda: is_list(v, S.hex64), "obj": lambda: True}.get(t, lambda: False)()


def body_refs(fields, body):
    """The ids a body names through reference-typed fields."""
    out = set()
    for k, t in fields.items():
        v = body.get(k)
        if t.rstrip("?") == "ref" and v is not None:
            out.add(v)
        elif t.rstrip("?") == "refs" and v is not None:
            out.update(v)
    return out
