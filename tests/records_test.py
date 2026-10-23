#!/usr/bin/env python3
"""SPEC §2 Encoding and §3 Records, one case per sentence or field line (pilot W4).

A refusal is asserted by its type only (records.Invalid, jcs.NotCanonical, or an
invalid record in the store's own listing), never by its message, so a mutant is
killed only when a refused value becomes accepted or the refusal stops being one
(a crash where the store should list an invalid record and go on). Every
string-shape rule gets a trailing "\\n", a "\\r\\n" and non-ASCII vectors; free-text
members get the same values as accepted controls.

    python3 tests/records_test.py
"""
import copy
import hashlib
import sys

from world import CODEX, HOLDER, OBSERVER, OWNER, STRANGER, E, R, W, World, check, finish
from warrant import jcs as C
from warrant import keys as K
from warrant import shapes as S
from warrant.store import Snapshot, Store, Trust

H1, H2, H3 = "a1" * 32, "b2" * 32, "c3" * 32
SHA40 = "d4" * 20

# Values a hex64 member must refuse: wrong case, length and alphabet, non-ASCII digits
# (`\d` matches them), and whitespace around a valid value.
BAD_HEX64 = {
    "upper": H1.upper(), "mixed": "A" + H1[1:], "63": H1[:63], "65": H1 + "a", "non-hex": "g" * 64,
    "arabic-indic digits": "١" * 64, "fullwidth digits": "０" * 64, "trailing \\n": H1 + "\n",
    "trailing \\r\\n": H1 + "\r\n", "63 + \\n": H1[:63] + "\n", "leading space": " " + H1[:63], "empty": "",
    "integer": 5, "null": None, "list": [H1],
}


def outcome(fn):
    """"accepted", "invalid" (a refusal of SPEC §2/§3), or the exception that is neither."""
    try:
        fn()
        return "accepted"
    except (R.Invalid, C.NotCanonical):
        return "invalid"
    except Exception as e:      # noqa: BLE001
        return f"raised {type(e).__name__}"


def rec(rtype, body, actor=HOLDER, at=100, **top):
    r = {"warrant": "2", "type": rtype, "actor": actor, "at": at, "body": body}
    r.update(top)
    return outcome(lambda: (R.check(r), C.canon(r)))


def put(body, **kv):
    b = copy.deepcopy(body)
    b.update(kv)
    return b


def drop(body, key):
    b = copy.deepcopy(body)
    del b[key]
    return b


DUTY = R.duty(HOLDER, "do the thing", [OWNER], {"attest": {}}, accept_by=[OWNER])
OBS_DUTY = R.duty(HOLDER, "watch it", [OWNER], {"observe": {"observers": [OBSERVER], "probe": H1, "expect": "ok",
                                                            "fresh_for": None}})
TRANSITION = R.transition("ATTESTED", [H1])
CLOSING = R.transition("ATTESTED", [H1], closes=[R.item(H2, "discharge", [H1])])
ACCEPT = R.accept(H3, 0, [H1])
OBSERVATION = R.observation("service", H1, [10, 20], "ok", [H2])
GRANT = R.grant(STRANGER, ["release"], [H2])
CHALLENGE = R.challenge(H3, "a counterexample", [H1], 0)
BASES = {"duty": DUTY, "transition": CLOSING, "accept": ACCEPT, "observation": OBSERVATION, "grant": GRANT,
         "challenge": CHALLENGE}
ACTOR_OF = {"duty": HOLDER, "transition": HOLDER, "accept": OWNER, "observation": OBSERVER, "grant": OWNER,
            "challenge": STRANGER}


def table(rows):
    """[(label, got, want)] -> (all as wanted, the rows that are not)."""
    bad = [(label, got, want) for label, got, want in rows if got != want]
    return not bad, bad


def item_transition(m, evidence=(H1,)):
    return R.transition("ATTESTED", list(evidence), closes=[m])


def stored(w, r, key, tamper=None):
    """Write a signed envelope for `r` by hand (no shape check), optionally tampered; its id."""
    rid = C.doc_id(r)
    env = {"record": r, "sig": {"key": key.id, "ed25519": key.sign(K.sig_message(rid))}}
    data = C.canon(env)
    name = rid
    if tamper:
        data, name = tamper(env, data, rid)
    (w.store.root / "records" / f"{name}.json").write_bytes(data)
    return name


def listing(w):
    """The store's own verdict on every record: ({id: reason} of invalid ones) or the exception."""
    try:
        good, bad = w.store.snapshot().authentic(w.trust)
        return good, bad
    except Exception as e:      # noqa: BLE001
        return None, f"raised {type(e).__name__}: {e}"


# ---------------------------------------------------------------- SPEC §2

def encoding_cases():
    big = 2**53 - 1
    # E1: the JSON domain: objects with string keys, arrays, strings, booleans, null and
    # integers within ±(2^53-1); one beyond either bound, and a non-string key, are refused
    rows = [
        ("every kind", outcome(lambda: C.canon({"o": {}, "a": [1, "s", True, False, None]})), "accepted"),
        ("2^53-1", outcome(lambda: C.canon(big)), "accepted"),
        ("-(2^53-1)", outcome(lambda: C.canon(-big)), "accepted"),
        ("2^53", outcome(lambda: C.canon(big + 1)), "invalid"),
        ("-(2^53)", outcome(lambda: C.canon(-big - 1)), "invalid"),
        ("read 2^53", outcome(lambda: C.loads(b"9007199254740992")), "invalid"),
        ("read -(2^53)", outcome(lambda: C.loads(b"-9007199254740992")), "invalid"),
        ("read 2^53-1", outcome(lambda: C.loads(b"9007199254740991")), "accepted"),
        ("integer key", outcome(lambda: C.canon({1: "x"})), "invalid"),
        ("boolean key", outcome(lambda: C.canon({True: "x"})), "invalid"),
        ("record at 2^53", rec("duty", DUTY, at=big + 1), "invalid"),
    ]
    ok, bad = table(rows)
    check("E1", ok, "JSON values: string keys, integers within ±(2^53-1)", bad)
    # E2: no floats, written or read, integral or not
    rows = [
        ("write 1.5", outcome(lambda: C.canon(1.5)), "invalid"),
        ("write 2.0", outcome(lambda: C.canon({"a": 2.0})), "invalid"),
        ("read 1.5", outcome(lambda: C.loads(b"1.5")), "invalid"),
        ("read 2.0", outcome(lambda: C.loads(b'{"a":2.0}')), "invalid"),
        ("read 1e2", outcome(lambda: C.loads(b"1e2")), "invalid"),
        ("record at 100.0", rec("duty", DUTY, at=100.0), "invalid"),
    ]
    ok, bad = table(rows)
    check("E2", ok, "no floats", bad)
    # E3: no lone surrogates, in values or keys, written or read; a pair is one character;
    # a stored record carrying one is listed invalid and the rest of the store is read
    w = World()
    good = w.duty(statement="a valid duty")
    lone = stored(w, R.record("duty", HOLDER, 101, put(DUTY, statement="x")), w.keys[HOLDER],
                  tamper=lambda env, data, rid: (data.replace(b'"x"', b'"\\ud800"'), rid))
    got_good, got_bad = listing(w)
    rows = [
        ("value", outcome(lambda: C.canon("a\ud800")), "invalid"),
        ("low half", outcome(lambda: C.canon("\udc00b")), "invalid"),
        ("key", outcome(lambda: C.canon({"\ud83d": 1})), "invalid"),
        ("read escape", outcome(lambda: C.loads(b'"\\ud800"')), "invalid"),
        ("pair as one character", outcome(lambda: C.canon("\U0001f600")), "accepted"),
        ("record statement", rec("duty", put(DUTY, statement="\udfff")), "invalid"),
        ("stored record listed invalid, the rest read",
         (got_good is not None and good in got_good and lone in got_bad), True),
    ]
    ok, bad = table(rows)
    check("E3", ok, "strings never contain lone surrogates", (bad, got_bad))
    # E4: closed member sets: an unknown member, a missing required member, or a value of
    # the wrong JSON type makes the record invalid, for the record and every body; a
    # stored record missing a member is listed invalid and the store is still read
    wrong = {str: 5, list: "x", dict: [], int: "1", bool: "true", type(None): []}
    rows = [("record + unknown", rec("duty", DUTY, extra=1), "invalid")]
    for k in ("warrant", "type", "actor", "at", "body"):
        r = {"warrant": "2", "type": "duty", "actor": HOLDER, "at": 100, "body": DUTY}
        del r[k]
        rows.append((f"record - {k}", outcome(lambda r=r: R.check(r)), "invalid"))
    rows += [("record at true", rec("duty", DUTY, at=True), "invalid"), ("record at \"100\"", rec("duty", DUTY, at="100"), "invalid")]
    for rtype, body in BASES.items():
        actor = ACTOR_OF[rtype]
        rows.append((f"{rtype} + unknown", rec(rtype, put(body, unknown=None), actor), "invalid"))
        for k, v in body.items():
            rows.append((f"{rtype} - {k}", rec(rtype, drop(body, k), actor), "invalid"))
            rows.append((f"{rtype}.{k} wrong type", rec(rtype, put(body, **{k: wrong[type(v)]}), actor), "invalid"))
    for k in ("duty", "act", "evidence"):
        rows.append((f"item - {k}", rec("transition", item_transition(drop(R.item(H2, "discharge", [H1]), k))), "invalid"))
    rows += [("item period true", rec("transition", item_transition(R.item(H2, "discharge", [H1], period=True))), "invalid"),
             ("accept item true", rec("accept", put(ACCEPT, item=True), OWNER), "invalid"),
             ("grant expires true", rec("grant", put(GRANT, expires=True), OWNER), "invalid")]
    w = World()
    good = w.duty(statement="a valid duty")
    missing = stored(w, {"warrant": "2", "type": "duty", "actor": HOLDER, "at": 101, "body": drop(DUTY, "subject")},
                     w.keys[HOLDER])
    got_good, got_bad = listing(w)
    rows.append(("stored, a member missing: listed invalid, the rest read",
                 got_good is not None and good in got_good and missing in got_bad, True))
    rows += [(f"{rtype} control", rec(rtype, body, ACTOR_OF[rtype]), "accepted") for rtype, body in BASES.items()]
    ok, bad = table(rows)
    check("E4", ok, "closed member sets: unknown, missing and wrong-typed members are invalid", bad)
    # E6: canonical bytes are RFC 8785: members by UTF-16 code units (U+1F600 is D83D DE00,
    # before U+FB01), no whitespace, JCS string escapes, UTF-8 otherwise; other bytes are refused
    rows = [
        ("UTF-16 order", C.canon({"ﬁ": 1, "\U0001f600": 2, "a": 3}),
         '{"a":3,"\U0001f600":2,"ﬁ":1}'.encode()),
        ("no whitespace", C.canon({"b": [1, {"c": None}], "a": True}), b'{"a":true,"b":[1,{"c":null}]}'),
        ("escapes", C.canon("q\"\\/\n\t\b\f\r\x1fé "), '"q\\"\\\\/\\n\\t\\b\\f\\r\\u001fé "'.encode()),
        ("read with a space", outcome(lambda: C.loads(b'{"a": 1}')), "invalid"),
        ("read out of order", outcome(lambda: C.loads(b'{"b":1,"a":2}')), "invalid"),
        ("read \\u00e9 escaped", outcome(lambda: C.loads(b'"\\u00e9"')), "invalid"),
        ("read code-point order", outcome(lambda: C.loads('{"ﬁ":1,"\U0001f600":2}'.encode())), "invalid"),
        ("read UTF-16 order", outcome(lambda: C.loads('{"\U0001f600":2,"ﬁ":1}'.encode())), "accepted"),
    ]
    ok, bad = table(rows)
    check("E6", ok, "canonical bytes: RFC 8785, UTF-16 member order, no whitespace", bad)
    # E7: a hash is lowercase hex SHA-256 of 64 characters, on the shared predicate and in a record
    rows = [(f"predicate {k}", S.hex64(v), False) for k, v in BAD_HEX64.items()]
    rows += [(f"evidence {k}", rec("transition", R.transition("ATTESTED", [v])), "invalid") for k, v in BAD_HEX64.items()]
    rows += [("digest", C.digest(b"x"), hashlib.sha256(b"x").hexdigest()),
             ("control", rec("transition", R.transition("ATTESTED", [C.digest(b"x")])), "accepted")]
    ok, bad = table(rows)
    check("E7", ok, "hashes are lowercase hex SHA-256, 64 characters", bad)
    # E8: a blob is any byte string, empty or not UTF-8, kept under sha256(bytes) and only there
    w = World()
    datas = [b"", b"\xff\xfe\x00", "é\n".encode()]
    hs = [w.store.put_blob(d) for d in datas]
    (w.store.root / "blobs" / H1).write_bytes(b"not the bytes of H1")
    snap = w.store.snapshot()
    rows = [("addresses", hs, [hashlib.sha256(d).hexdigest() for d in datas]),
            ("kept", [snap.blob(h) for h in hs], datas),
            ("misnamed kept out", H1 in snap.blobs, False)]
    ok, bad = table(rows)
    check("E8", ok, "a blob is any byte string, addressed by sha256(bytes)", bad)
    # E9: time is an integer: not a boolean, a float or a string
    rows = [(k, rec("duty", DUTY, at=v), want) for k, v, want in (
        ("0", 0, "accepted"), ("2^53-1", 2**53 - 1, "accepted"), ("true", True, "invalid"), ("false", False, "invalid"),
        ("100.0", 100.0, "invalid"), ("\"100\"", "100", "invalid"), ("null", None, "invalid"))]
    rows += [("observation window true", rec("observation", put(OBSERVATION, window=[True, 20]), OBSERVER), "invalid"),
             ("schedule start true", rec("duty", put(DUTY, schedule={"start": True, "every": 10})), "invalid")]
    ok, bad = table(rows)
    check("E9", ok, "time is integer seconds", bad)
    # E10 (G7): nesting is bounded: the innermost value may lie MAX_DEPTH (256) containers deep,
    # not 257, written or read, also through loads' bracket pre-count (taken past 4 x MAX_DEPTH
    # brackets), which must skip brackets inside strings and escaped quotes. Found by the
    # generated-mutant hunt: `>` -> `>=` on the depth, MAX_DEPTH +-1 and loads' depth scan survived.
    def nest(n):
        v = 0
        for _ in range(n):
            v = [v]
        return v

    def deep(n, pad):           # bytes: one list holding n - 1 more around 0, then `pad` empty lists
        return b"[" + b"[" * (n - 1) + b"0" + b"]" * (n - 1) + b",[]" * pad + b"]"
    quoted = C.canon({"a": "\"" + "[" * 1100 + "{", "b": [[1]]})
    rows = [
        ("write depth 256", outcome(lambda: C.canon(nest(256))), "accepted"),
        ("write depth 257", outcome(lambda: C.canon(nest(257))), "invalid"),
        ("read depth 256", outcome(lambda: C.loads(deep(256, 0))), "accepted"),
        ("read depth 257", outcome(lambda: C.loads(deep(257, 0))), "invalid"),
        ("read depth 256, 1100 brackets", outcome(lambda: C.loads(deep(256, 850))), "accepted"),
        ("read depth 257, 1100 brackets", outcome(lambda: C.loads(deep(257, 850))), "invalid"),
        ("brackets and an escaped quote inside a string", outcome(lambda: C.loads(quoted)), "accepted"),
    ]
    ok, bad = table(rows)
    check("E10", ok, "nesting: 256 containers deep is read and written, 257 is refused", bad)


# ---------------------------------------------------------------- SPEC §3

def record_cases():
    # K1: the record object: version "2", one of the types, an actor string, an integer time, a body
    rows = [(k, rec(t, DUTY, **({} if v is None else {"warrant": v})), want) for k, t, v, want in (
        ("version 2 (integer)", "duty", 2, "invalid"), ("version \"3\"", "duty", "3", "invalid"),
        ("version \"2\\n\"", "duty", "2\n", "invalid"), ("version fullwidth", "duty", "２", "invalid"),
        ("type Duty", "Duty", None, "invalid"), ("type duty\\n", "duty\n", None, "invalid"),
        ("control", "duty", None, "accepted"))]
    rows += [("actor 5", rec("duty", put(DUTY, holder=5), actor=5), "invalid"),
             ("actor non-ASCII", rec("duty", put(DUTY, holder="ówner"), actor="ówner"), "accepted"),
             ("body a list", rec("duty", []), "invalid")]
    ok, bad = table(rows)
    check("K1", ok, "a record is {warrant: \"2\", type, actor, at, body}", bad)
    # K2: the id is sha256 of the canonical bytes, written here by hand
    r = R.record("challenge", HOLDER, 1, R.challenge(H3, "xé", []))
    by_hand = ('{"actor":"claude","at":1,"body":{"evidence":[],"item":null,"statement":"xé","target":"'
               + H3 + '"},"type":"challenge","warrant":"2"}').encode()
    rows = [("id", R.record_id(r), hashlib.sha256(by_hand).hexdigest())]
    w = World()
    rid = w.store.put_record(r, w.keys[HOLDER])
    rows.append(("stored under it", rid, hashlib.sha256(by_hand).hexdigest()))
    ok, bad = table(rows)
    check("K2", ok, "a record's id is sha256(canon(record))", bad)
    # K3: stored as canon({"record", "sig": {"key", "ed25519"}}) in records/<id>.json; any
    # other envelope member, or a sig member of another shape, is an invalid record
    w = World()
    key = w.keys[HOLDER]
    r = R.record("duty", HOLDER, 101, DUTY)
    rid = w.store.put_record(r, key)
    data = (w.store.root / "records" / f"{rid}.json").read_bytes()
    want = C.canon({"record": r, "sig": {"key": key.id, "ed25519": key.sign(K.sig_message(rid))}})

    def envelope(fn):
        def t(env, data, rid):
            env = copy.deepcopy(env)
            fn(env)
            return C.canon(env), rid
        return t
    extra = stored(w, R.record("duty", HOLDER, 102, put(DUTY, statement="two")), key,
                   envelope(lambda e: e.update(note="x")))
    sig_extra = stored(w, R.record("duty", HOLDER, 103, put(DUTY, statement="three")), key,
                       envelope(lambda e: e["sig"].update(note="x")))
    sig_nl = stored(w, R.record("duty", HOLDER, 104, put(DUTY, statement="four")), key,
                    envelope(lambda e: e["sig"].update(ed25519=e["sig"]["ed25519"] + "\n")))
    sig_upper = stored(w, R.record("duty", HOLDER, 105, put(DUTY, statement="five")), key,
                       envelope(lambda e: e["sig"].update(key=e["sig"]["key"].upper())))
    good, bad_ = listing(w)
    rows = [("bytes", data, want), ("good", sorted(good or {}), [rid]),
            ("invalid", sorted(bad_) if isinstance(bad_, dict) else bad_, sorted([extra, sig_extra, sig_nl, sig_upper]))]
    ok, bad = table(rows)
    check("K3", ok, "stored as the canonical envelope in records/<id>.json", bad)
    # K4: the signature is Ed25519 over the 47 bytes "warrant-sig-v1:" || id_raw, checked
    # here with the library directly, not through keys.sig_message
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    msg = b"warrant-sig-v1:" + bytes.fromhex(rid)
    env = C.loads(data)
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key.public)).verify(bytes.fromhex(env["sig"]["ed25519"]), msg)
        direct = True
    except Exception:       # noqa: BLE001
        direct = False
    rows = [("47 bytes", len(K.sig_message(rid)), 47), ("message", K.sig_message(rid), msg), ("verifies directly", direct, True)]
    ok, bad = table(rows)
    check("K4", ok, "the signature covers exactly \"warrant-sig-v1:\" || id_raw", bad)
    # K5: a key id is sha256 of the 32 raw public key bytes, not of their hex text
    raw = bytes.fromhex(key.public)
    rows = [("raw", len(raw), 32), ("key id", key.id, hashlib.sha256(raw).hexdigest()),
            ("envelope key", env["sig"]["key"], hashlib.sha256(raw).hexdigest()),
            ("trust", sorted(Trust(Trust.document([(HOLDER, key.public)])).keys), [hashlib.sha256(raw).hexdigest()])]
    ok, bad = table(rows)
    check("K5", ok, "a key id is the SHA-256 of the 32-byte public key", bad)
    # K6: authentic iff canonical bytes, matching id, and a signature that verifies under a key
    # the trust binds to the record's actor; each failure alone makes it unauthentic
    w = World()
    key = w.keys[HOLDER]
    control = w.duty(statement="control")
    import json as _json
    spaced = stored(w, R.record("duty", HOLDER, 102, put(DUTY, statement="spaced")), key,
                    lambda env, data, rid: (_json.dumps(env, sort_keys=True).encode(), rid))
    renamed = stored(w, R.record("duty", HOLDER, 103, put(DUTY, statement="renamed")), key,
                     lambda env, data, rid: (data, H2))
    # signed by the bound key for the name it is stored under: only the id check refuses it
    resigned = stored(w, R.record("duty", HOLDER, 106, put(DUTY, statement="re-signed")), key,
                      lambda env, data, rid: (C.canon(put(env, sig={"key": key.id, "ed25519": key.sign(K.sig_message(H3))})), H3))
    other_msg = R.record("duty", HOLDER, 104, put(DUTY, statement="other message"))
    forged = stored(w, other_msg, key, lambda env, data, rid: (C.canon(put(env, sig={"key": key.id, "ed25519": key.sign(
        K.sig_message(H1))})), rid))
    unbound = stored(w, R.record("duty", HOLDER, 105, put(DUTY, statement="unbound")), W.Key.generate())
    good, bad_ = listing(w)
    rows = [("authentic", sorted(good or {}), [control]),
            ("unauthentic", sorted(bad_) if isinstance(bad_, dict) else bad_, sorted([spaced, renamed, resigned, forged, unbound]))]
    ok, bad = table(rows)
    check("K6", ok, "authentic iff canonical, id matches, signature verifies under a key bound to the actor", bad)
    # K18 (G7): a trust file is trust/2 and binds each key once: one key bound to two actors,
    # or another version, is not a trust file. Found by the generated-mutant hunt: deleting either
    # refusal survived every case.
    k1, k2 = W.Key.generate().public, W.Key.generate().public
    rows = [
        ("control", outcome(lambda: Trust(Trust.document([(HOLDER, k1), (OWNER, k2)]))), "accepted"),
        ("one key, two actors", outcome(lambda: Trust(Trust.document([(HOLDER, k1), (OWNER, k1)]))), "invalid"),
        ("one key twice, one actor", outcome(lambda: Trust(Trust.document([(HOLDER, k1), (HOLDER, k1)]))), "invalid"),
        ("trust/1", outcome(lambda: Trust(dict(Trust.document([(HOLDER, k1)]), warrant="trust/1"))), "invalid"),
    ]
    ok, bad = table(rows)
    check("K18", ok, "a trust file is trust/2 and binds each key once", bad)
    # K8: exactly six types; any other name is invalid
    rows = [(t, rec(t, BASES[t], ACTOR_OF[t]), "accepted") for t in BASES]
    rows += [(t, rec(t, TRANSITION), "invalid") for t in ("claim", "note", "Transition", "transition\n", "prior")]
    rows.append(("names", R.TYPES, ("duty", "transition", "accept", "observation", "grant", "challenge")))
    ok, bad = table(rows)
    check("K8", ok, "there are six types", bad)
    # K9: no body is valid under another type: a claim, a permission, an observation and an
    # acceptance cannot be read as one another
    rows = [(f"{b} as {t}", rec(t, body, ACTOR_OF[b]), "invalid") for b, body in BASES.items() for t in BASES if t != b]
    ok, bad = table(rows)
    check("K9", ok, "a body of one type is invalid under every other", bad)
    # K11: no `prior` member anywhere: relations are the typed fields
    rows = [("record", rec("duty", DUTY, prior=[H1]), "invalid")]
    rows += [(t, rec(t, put(body, prior=[H1]), ACTOR_OF[t]), "invalid") for t, body in BASES.items()]
    ok, bad = table(rows)
    check("K11", ok, "prior edges do not exist", bad)
    actor_id_cases()


# W5: an actor id has one canonical shape, whatever the actor is.
GOOD_ACTORS = {
    "claude": "claude", "codex": "codex", "readers": "readers", "owner": "owner",
    "a person, non-ASCII, inner space": "Сергій Глова", "a model": "claude-opus-5-5",
    "a program by the hash of its code": "checker sha256:" + hashlib.sha256(b"def check(view): ...").hexdigest(),
    "a rule": "rule §4.2: release on expiry", "one code point": "x", "NFC é": "é",
    "200 code points": "a" * 200, "200 non-BMP code points": "\U0001F600" * 200,
}
BAD_ACTORS = {
    "empty": "", "201 code points": "a" * 201, "trailing \\n": "claude\n", "trailing \\r\\n": "claude\r\n",
    "leading \\n": "\nclaude", "leading space": " claude", "trailing space": "claude ",
    "trailing no-break space (Zs)": "claude ", "leading ideographic space (Zs)": "　claude",
    "trailing line separator (Zl)": "claude ", "trailing paragraph separator (Zp)": "claude ",
    "inner NUL (Cc)": "cla\x00ude", "inner tab (Cc)": "cla\tude", "inner NEL (Cc)": "cla\x85ude",
    "NFD é": "é", "Angstrom sign (NFC is U+00C5)": "Å", "integer": 5, "null": None, "list": ["claude"],
}


def actor_id_cases():
    # K12: an actor id is a non-empty string of at most 200 code points, in NFC, with no
    # control character and no white space at either end; the shape holds wherever an actor
    # is named (the record's actor, a list of actors, a trust binding)
    def trust_with(a):
        try:
            Trust(Trust.document([(a, W.Key.generate().public)]))
            return "accepted"
        except (R.Invalid, C.NotCanonical):
            return "invalid"
        except Exception as e:      # noqa: BLE001
            return f"raised {type(e).__name__}"
    rows = []
    for k, v in list(GOOD_ACTORS.items()) + list(BAD_ACTORS.items()):
        want = "accepted" if k in GOOD_ACTORS else "invalid"
        rows += [(f"record actor {k}", rec("duty", put(DUTY, holder=v, owed_to=[STRANGER], accept_by=[STRANGER]), actor=v), want),
                 (f"owed_to {k}", rec("duty", put(DUTY, owed_to=[v])), want),
                 (f"trust actor {k}", trust_with(v), want)]
    ok, bad = table(rows)
    check("K12", ok, "an actor id: ≤ 200 code points, NFC, no Cc, no white space at either end", bad)
    # K13: Warrant does not assess what an actor is: a duty held by a program (named by the
    # hash of its code), owed to a person and accepted by a rule closes exactly as one among
    # "claude", "owner" and "codex" does
    def closes(holder, owner, acceptor):
        try:
            w = World(actors=(holder, owner, acceptor))
            d = w.duty(holder=holder, owed_to=(owner,), accept_by=(acceptor,))
            w.accept(acceptor, w.close(d, actor=holder))
            rep = w.assess()
        except (R.Invalid, C.NotCanonical):
            return "refused", None
        return rep["duties"][d]["disposition"], len(rep["invalid_records"])
    kinds = (GOOD_ACTORS["a program by the hash of its code"], GOOD_ACTORS["a person, non-ASCII, inner space"],
             GOOD_ACTORS["a rule"])
    got = {"names": closes(HOLDER, OWNER, CODEX), "kinds": closes(*kinds)}
    check("K13", got == {"names": ("DISCHARGED", 0), "kinds": ("DISCHARGED", 0)},
          "a program, a person and a rule act as named actors do", got)


def chain_cases():
    # K14 (§3, F43): `prev` is optional, null or a record id; without it the record is unchained
    rows = [("no prev (unchained)", rec("duty", DUTY), "accepted"), ("prev null (a genesis)", rec("duty", DUTY, prev=None), "accepted"),
            ("prev a record id", rec("duty", DUTY, prev=H1), "accepted")]
    rows += bad_hex_rows("prev", lambda v: rec("duty", DUTY, prev=v), nullable=True)
    ok, bad = table(rows)
    check("K14", ok, "prev is absent (unchained), null or a hex64 record id", bad)

    # K15 (§3): a writer extends its actor's chain from the head in the store, under a lock:
    # the first record names no prev, the next the first; one dated before the head is refused
    # and nothing is written; a draft whose prev is no longer the head is refused (ChainMoved);
    # unchained records are no head, and with two tips (a fork) the later one is.
    from warrant.store import ChainMoved
    w = World()
    st, k = w.store, w.keys[HOLDER]
    st.put_record(R.record("duty", HOLDER, 90, put(DUTY, statement="unchained")), k)     # not a head
    none_yet = st.head(HOLDER, w.trust)
    a = st.append("duty", HOLDER, 100, DUTY, k)
    b = st.append("transition", HOLDER, 100, TRANSITION, k)
    n = len(list((st.root / "records").iterdir()))
    early = outcome(lambda: st.append("transition", HOLDER, 99, CLOSING, k))
    stale = R.record("transition", HOLDER, 120, CLOSING, prev=a)
    try:
        st.extend(stale, k)
        moved = "filed"
    except ChainMoved:
        moved = "ChainMoved"
    unchanged = len(list((st.root / "records").iterdir())) == n
    prevs = [C.loads((st.root / "records" / f"{x}.json").read_bytes())["record"]["prev"] for x in (a, b)]
    tip = st.put_record(R.record("transition", HOLDER, 300, CLOSING, prev=a), k)     # a fork beside b, dated later
    got = (none_yet, prevs, early, moved, unchanged, st.head(HOLDER, w.trust))
    check("K15", got == (None, [None, a], "raised ValueError", "ChainMoved", True, (tip, 300)),
          "Store.append names the head as prev, refuses to date before it, and extends only from the head", got)

    # K16 (§3): two writers of one store never read the same head: append waits for the lock
    # another writer holds on records/, and extends the head that writer left
    import fcntl
    import os
    import threading
    w = World()
    st, k = w.store, w.keys[HOLDER]
    a = st.append("duty", HOLDER, 100, DUTY, k)
    fd = os.open(st.root / "records", os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX)                      # another writer, between reading the head and filing
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("id", st.append("transition", HOLDER, 101, TRANSITION, k)))
    th.start()
    th.join(0.5)
    waited = th.is_alive()
    b = st.put_record(R.record("transition", HOLDER, 100, CLOSING, prev=a), k)     # that writer's record
    os.close(fd)
    th.join(10)
    prev = C.loads((st.root / "records" / f"{out.get('id')}.json").read_bytes())["record"]["prev"] if "id" in out else None
    check("K16", (waited, prev) == (True, b), "an append waits for another writer's lock and names the head it left",
          (waited, prev))

    # K17 (§3; AMEND 1 of #174, Codex P2): only records the reader admits as the actor's own are
    # a head. Planted, all dated after HOLDER's real head and naming it as prev: a record for
    # HOLDER signed by STRANGER's bound key, one signed by a key bound to nobody, a genuine
    # HOLDER record stored under another id's name, and a HOLDER-signed envelope whose prev is
    # not an id. The reader rejects all four; none is a head; HOLDER's append at an ordinary time
    # names the real head. HOLDER's own authentic record whose prev is not in the store is no head
    # either: extending it would leave the new record with no ancestor before it.
    w = World()
    st, k = w.store, w.keys[HOLDER]
    a = st.append("duty", HOLDER, 100, DUTY, k, w.trust)
    far = 10 ** 10

    def plant(r, key, tamper=None):
        return stored(w, r, key, tamper)
    forged = [plant(R.record("transition", HOLDER, far, TRANSITION, prev=a), w.keys[STRANGER]),
              plant(R.record("transition", HOLDER, far + 1, CLOSING, prev=a), W.Key.generate()),
              plant(R.record("transition", HOLDER, far + 2, put(TRANSITION, established=["misnamed"]), prev=a), k,
                    tamper=lambda env, data, rid: (data, "f" * 64)),
              plant({"warrant": "2", "type": "transition", "actor": HOLDER, "at": far + 3, "prev": "zz", "body": TRANSITION}, k)]
    loose = plant(R.record("transition", HOLDER, far + 4, put(TRANSITION, established=["loose"]), prev="e" * 64), k)
    _, rejected = st.snapshot().authentic(w.trust)
    head = st.head(HOLDER, w.trust)
    try:                                     # a poisoned head refuses this append (Codex's reproduction)
        b = st.append("transition", HOLDER, 200, CLOSING, k, w.trust)
    except ValueError as e:
        b = f"refused: {e}"
    try:                                     # the default (the `warrant` CLI): the signing key's own trust
        c = st.append("transition", HOLDER, 300, put(CLOSING, established=["default trust"]), k)
    except ValueError as e:
        c = f"refused: {e}"
    recs = st.snapshot().authentic(w.trust)[0]
    rep = w.assess(as_of=2 * far)
    got = (sorted(rejected) == sorted(forged), head, recs[b]["prev"] if b in recs else b, b in rep["chains"]["unanchored"],
           rep["chains"]["unanchored"].get(loose), any(r.get("prev") in forged for r in recs.values()),
           recs[c]["prev"] if c in recs else c)
    check("K17", got == (True, (a, 100), a, False, "its prev is not in the view", False, b),
          "a record the reader rejects, or an unanchored one, is never a writer's head", got)


def bad_hex_rows(label, make, nullable=False):
    """[(label, outcome, "invalid")] for every BAD_HEX64 value put where `make` puts it."""
    return [(f"{label} {k}", make(v), "invalid") for k, v in BAD_HEX64.items() if not (nullable and v is None)]


def duty_cases():
    # D1: statement is a string of at most 400 code points: not bytes, not UTF-16 units
    rows = [(k, rec("duty", put(DUTY, statement=v)), want) for k, v, want in (
        ("400 ASCII", "a" * 400, "accepted"), ("401 ASCII", "a" * 401, "invalid"),
        ("400 two-byte", "é" * 400, "accepted"), ("400 astral", "\U0001f600" * 400, "accepted"),
        ("401 astral", "\U0001f600" * 401, "invalid"), ("399 + \\n", "a" * 399 + "\n", "accepted"),
        ("400 + \\n", "a" * 400 + "\n", "invalid"), ("398 + \\r\\n", "a" * 398 + "\r\n", "accepted"),
        ("integer", 400, "invalid"))]
    ok, bad = table(rows)
    check("D1", ok, "statement ≤ 400 code points", bad)
    # D2: the holder is the record's actor, exactly
    rows = [(f"{h!r} by {a!r}", rec("duty", put(DUTY, holder=h), actor=a), want) for h, a, want in (
        (HOLDER, HOLDER, "accepted"), (HOLDER + "\n", HOLDER, "invalid"), (HOLDER, HOLDER + "\r\n", "invalid"),
        ("Claude", HOLDER, "invalid"), ("claudé", "claude", "invalid"), ("ówner", "ówner", "accepted"),
        (OWNER, HOLDER, "invalid"))]
    ok, bad = table(rows)
    check("D2", ok, "holder MUST equal the record's actor", bad)
    # D3: owed_to is a non-empty list of actors
    rows = [(k, rec("duty", put(DUTY, owed_to=v)), want) for k, v, want in (
        ("[]", [], "invalid"), ("a string", OWNER, "invalid"), ("[5]", [5], "invalid"), ("[null]", [None], "invalid"),
        ("one", [OWNER], "accepted"), ("non-ASCII", ["ówner"], "accepted"),
        ("trailing \\n (W5: actor id shape)", ["ówner\n"], "invalid"))]
    ok, bad = table(rows)
    check("D3", ok, "owed_to is a non-empty list of actors", bad)
    # D4: accept_by is a list of actors (an observe duty may name none)
    rows = [(k, rec("duty", put(OBS_DUTY, accept_by=v)), want) for k, v, want in (
        ("[]", [], "accepted"), ("a string", OWNER, "invalid"), ("[5]", [5], "invalid"), ("[[owner]]", [[OWNER]], "invalid"),
        ("two", [OWNER, CODEX], "accepted"))]
    ok, bad = table(rows)
    check("D4", ok, "accept_by is a list of actors", bad)
    # D5: release_by is a list of actors; owed_to may always release, release_by may, others not
    rows = [(k, rec("duty", put(DUTY, release_by=v)), want) for k, v, want in (
        ("a string", CODEX, "invalid"), ("[5]", [5], "invalid"), ("[]", [], "accepted"), ("one", [CODEX], "accepted"))]
    w = World()
    d1 = w.duty(statement="one")
    d2 = w.duty(statement="two", release_by=(CODEX,))
    d3 = w.duty(statement="three", release_by=(CODEX,))
    w.close(d1, actor=OWNER, act="release")
    w.close(d2, actor=OWNER, act="release")
    w.close(d3, actor=STRANGER, act="release")
    rep = w.assess()
    rows.append(("dispositions", [rep["duties"][d]["disposition"] for d in (d1, d2, d3)], ["RELEASED", "RELEASED", "OPEN"]))
    ok, bad = table(rows)
    check("D5", ok, "release_by is a list of actors; owed_to may always release", bad)
    # D6: condition is exactly one of the three kinds
    rows = [(k, rec("duty", put(DUTY, condition=v)), want) for k, v, want in (
        ("{}", {}, "invalid"), ("two kinds", {"attest": {}, "observe": OBS_DUTY["condition"]["observe"]}, "invalid"),
        ("Attest", {"Attest": {}}, "invalid"), ("attest\\n", {"attest\n": {}}, "invalid"), ("a list", [{"attest": {}}], "invalid"),
        ("attest", {"attest": {}}, "accepted"))]
    ok, bad = table(rows)
    check("D6", ok, "condition is one of attest, observe, compute", bad)
    # D7: attest is the empty object
    rows = [(k, rec("duty", put(DUTY, condition={"attest": v})), want) for k, v, want in (
        ("a member", {"by": OWNER}, "invalid"), ("[]", [], "invalid"), ("null", None, "invalid"), ("{}", {}, "accepted"))]
    ok, bad = table(rows)
    check("D7", ok, "{\"attest\": {}}", bad)
    # D8: observe: observers, a hex64 probe, a string expect, fresh_for int|null
    base = OBS_DUTY["condition"]["observe"]

    def obs(**kv):
        return rec("duty", put(OBS_DUTY, condition={"observe": put(base, **kv)}))
    rows = bad_hex_rows("probe", lambda v: obs(probe=v))
    rows += [(k, obs(**kv), want) for k, kv, want in (
        ("observers a string", {"observers": OBSERVER}, "invalid"), ("observers [5]", {"observers": [5]}, "invalid"),
        ("expect 5", {"expect": 5}, "invalid"), ("expect null", {"expect": None}, "invalid"),
        ("expect empty", {"expect": ""}, "accepted"), ("expect \\n and non-ASCII", {"expect": "é\n"}, "accepted"),
        ("fresh_for 10", {"fresh_for": 10}, "accepted"), ("fresh_for true", {"fresh_for": True}, "invalid"),
        ("fresh_for \"10\"", {"fresh_for": "10"}, "invalid"), ("control", {}, "accepted"))]
    rows += [("missing fresh_for", rec("duty", put(OBS_DUTY, condition={"observe": drop(base, "fresh_for")})), "invalid"),
             ("unknown member", obs(window=[1, 2]), "invalid")]
    ok, bad = table(rows)
    check("D8", ok, "observe condition members", bad)
    # D9: compute: a runtime id of §7 and three hex64 members
    cbase = {"runtime": R.RUNTIMES[0], "input": H1, "environment": H2, "expect": H3}

    def comp(**kv):
        return rec("duty", put(DUTY, condition={"compute": put(cbase, **kv)}))
    rows = [row for k in ("input", "environment", "expect") for row in bad_hex_rows(k, lambda v, k=k: comp(**{k: v}))]
    rows += [(k, comp(runtime=v), want) for k, v, want in (
        ("runtime unknown", "sigma/other", "invalid"), ("runtime + \\n", R.RUNTIMES[0] + "\n", "invalid"),
        ("runtime 5", 5, "invalid"), ("runtime draft", R.RUNTIMES[1], "accepted"))]
    rows.append(("control", comp(), "accepted"))
    ok, bad = table(rows)
    check("D9", ok, "compute condition members", bad)
    # D10: schedule is null or {start: int, every: int > 0}
    rows = [(k, rec("duty", put(DUTY, schedule=v)), want) for k, v, want in (
        ("null", None, "accepted"), ("start 0 every 1", {"start": 0, "every": 1}, "accepted"),
        ("every 0", {"start": 0, "every": 0}, "invalid"), ("every -1", {"start": 0, "every": -1}, "invalid"),
        ("every true", {"start": 0, "every": True}, "invalid"), ("every \"10\"", {"start": 0, "every": "10"}, "invalid"),
        ("start \"0\"", {"start": "0", "every": 10}, "invalid"), ("no every", {"start": 0}, "invalid"),
        ("unknown member", {"start": 0, "every": 1, "until": 9}, "invalid"), ("a list", [0, 10], "invalid"))]
    ok, bad = table(rows)
    check("D10", ok, "schedule null | {start: int, every: int > 0}", bad)
    # D11-D12: requires and serves are lists of duty ids
    for cid, k in (("D11", "requires"), ("D12", "serves")):
        rows = bad_hex_rows(k, lambda v, k=k: rec("duty", put(DUTY, **{k: [v]})))
        rows += [(f"{k} a string", rec("duty", put(DUTY, **{k: H1})), "invalid"),
                 (f"{k} control", rec("duty", put(DUTY, **{k: [H1, H2]})), "accepted")]
        ok, bad = table(rows)
        check(cid, ok, f"{k} is a list of duty ids", bad)
    # D13: answers is null or <transition id>:<index>: ASCII digits, no leading zero
    rows = [(k, rec("duty", put(DUTY, answers=v)), want) for k, v, want in (
        ("null", None, "accepted"), (":0", H1 + ":0", "accepted"), (":12", H1 + ":12", "accepted"),
        (":00", H1 + ":00", "invalid"), (":01", H1 + ":01", "invalid"), (":-1", H1 + ":-1", "invalid"),
        (": arabic-indic 1", H1 + ":١", "invalid"), (":1 arabic-indic 2", H1 + ":1٢", "invalid"),
        (":0\\n", H1 + ":0\n", "invalid"), (":0\\r\\n", H1 + ":0\r\n", "invalid"), ("upper id", H1.upper() + ":0", "invalid"),
        ("no index", H1 + ":", "invalid"), ("no colon", H1, "invalid"), ("two indexes", H1 + ":0:1", "invalid"),
        ("63 hex", H1[:63] + ":0", "invalid"), ("integer", 0, "invalid"))]
    ok, bad = table(rows)
    check("D13", ok, "answers is null or a question reference", bad)
    # D14: subject is null or hex40 or hex64
    ok, bad = table(subject_rows(lambda v: rec("duty", put(DUTY, subject=v))))
    check("D14", ok, "a duty's subject is null | hex40 | hex64", bad)


def subject_rows(make):
    rows = [(k, make(v), want) for k, v, want in (
        ("null", None, "accepted"), ("hex40", SHA40, "accepted"), ("hex64", H1, "accepted"),
        ("hex41", SHA40 + "a", "invalid"), ("hex39", SHA40[:39], "invalid"), ("hex63", H1[:63], "invalid"),
        ("hex50", H1[:50], "invalid"), ("upper hex40", SHA40.upper(), "invalid"), ("hex40 + \\n", SHA40 + "\n", "invalid"),
        ("hex40 + \\r\\n", SHA40 + "\r\n", "invalid"), ("arabic-indic 40", "١" * 40, "invalid"))]
    return rows + bad_hex_rows("hex64", make, nullable=True)


def transition_cases():
    # T1: basis is one of three exact names
    rows = [(repr(v), rec("transition", put(TRANSITION, basis=v)), want) for v, want in (
        ("ATTESTED", "accepted"), ("OBSERVED", "accepted"), ("REPLAYED", "accepted"), ("attested", "invalid"),
        ("ATTESTED\n", "invalid"), ("ATTESTED\r\n", "invalid"), ("ATTESTED ", "invalid"), ("АTTESTED", "invalid"),
        ("CLAIMED", "invalid"), (1, "invalid"), (None, "invalid"))]
    ok, bad = table(rows)
    check("T1", ok, "basis ATTESTED | OBSERVED | REPLAYED", bad)
    # T2: evidence is a list of hex64
    rows = bad_hex_rows("evidence", lambda v: rec("transition", put(TRANSITION, evidence=[v])))
    rows += [("a string", rec("transition", put(TRANSITION, evidence=H1)), "invalid"),
             ("control", rec("transition", put(TRANSITION, evidence=[H1, H2])), "accepted")]
    ok, bad = table(rows)
    check("T2", ok, "evidence is a list of hex64", bad)
    # T4-T5: established and residual are lists of strings
    for cid, k in (("T4", "established"), ("T5", "residual")):
        rows = [(f"{k} {n}", rec("transition", put(TRANSITION, **{k: v})), want) for n, v, want in (
            ("[5]", [5], "invalid"), ("a string", "done", "invalid"), ("[[x]]", [["x"]], "invalid"), ("[null]", [None], "invalid"),
            ("\\n and non-ASCII", ["été\n", "two\r\n"], "accepted"))]
        ok, bad = table(rows)
        check(cid, ok, f"{k} is a list of strings", bad)
    # T6: opened is a list of {text: string, scope: null|string}
    rows = [(k, rec("transition", put(TRANSITION, opened=[v])), want) for k, v, want in (
        ("scope null", {"text": "why?", "scope": None}, "accepted"), ("scope string", {"text": "why?\n", "scope": "é"}, "accepted"),
        ("scope 5", {"text": "why?", "scope": 5}, "invalid"), ("scope []", {"text": "why?", "scope": []}, "invalid"),
        ("no scope", {"text": "why?"}, "invalid"), ("text 5", {"text": 5, "scope": None}, "invalid"),
        ("unknown member", {"text": "why?", "scope": None, "owner": OWNER}, "invalid"), ("a string", "why?", "invalid"))]
    ok, bad = table(rows)
    check("T6", ok, "opened is a list of {text, scope}", bad)
    # T7: closes is a list of items
    rows = [(k, rec("transition", put(TRANSITION, closes=v)), want) for k, v, want in (
        ("a string", "x", "invalid"), ("[5]", [5], "invalid"), ("[{}]", [{}], "invalid"), ("[[item]]", [[R.item(H2, "discharge", [H1])]], "invalid"),
        ("one item", [R.item(H2, "discharge", [H1])], "accepted"))]
    ok, bad = table(rows)
    check("T7", ok, "closes is a list of items", bad)
    # T9: a transition's subject is null or hex40 or hex64
    ok, bad = table(subject_rows(lambda v: rec("transition", put(TRANSITION, subject=v))))
    check("T9", ok, "a transition's subject is null | hex40 | hex64", bad)
    # T10: supersedes is a list of transition ids
    rows = bad_hex_rows("supersedes", lambda v: rec("transition", put(TRANSITION, supersedes=[v])))
    rows.append(("control", rec("transition", put(TRANSITION, supersedes=[H2])), "accepted"))
    ok, bad = table(rows)
    check("T10", ok, "supersedes is a list of transition ids", bad)
    # T11: triggers is a list of the triggers of §5
    rows = [(k, rec("transition", put(TRANSITION, triggers=v)), want) for k, v, want in (
        ("subject_changed", [{"kind": "subject_changed", "baseline": H1}], "accepted"),
        ("duty_not_discharged", [{"kind": "duty_not_discharged", "duty": H1}], "accepted"),
        ("unknown kind", [{"kind": "always_fine", "duty": H1}], "invalid"),
        ("wrong operand", [{"kind": "subject_changed", "duty": H1}], "invalid"),
        ("unknown member", [{"kind": "subject_changed", "baseline": H1, "path": "x"}], "invalid"),
        ("baseline \\n", [{"kind": "subject_changed", "baseline": H1 + "\n"}], "invalid"),
        ("duty upper", [{"kind": "duty_not_discharged", "duty": H1.upper()}], "invalid"),
        ("[5]", [5], "invalid"), ("a string", "subject_changed", "invalid"))]
    ok, bad = table(rows)
    check("T11", ok, "triggers is a list of §5 triggers", bad)
    # T12: a question reference is <transition id>:<index into opened>
    w = World()
    t = w.act(HOLDER, [], opened=[{"text": "first?", "scope": None}, {"text": "second?", "scope": None}])
    d0 = w.duty(statement="answer the first", answers=f"{t}:0")
    w.duty(statement="answer none", answers=f"{t}:2")
    qs = {q["question"]: q["taken_by"] for q in E.questions(w.assess(), owned=True)}
    rows = [("references", sorted(qs), [f"{t}:0", f"{t}:1"]), ("taken", (qs.get(f"{t}:0"), qs.get(f"{t}:1")), ([d0], []))]
    ok, bad = table(rows)
    check("T12", ok, "a question reference is <transition id>:<index into opened>", bad)


def item_cases():
    def item(**kv):
        return rec("transition", item_transition(put(R.item(H2, "discharge", [H1]), **kv)))
    # I1: an item names one duty by id
    rows = bad_hex_rows("duty", lambda v: item(duty=v))
    rows += [("a list", item(duty=[H2]), "invalid"), ("control", item(), "accepted")]
    ok, bad = table(rows)
    check("I1", ok, "an item's duty is a duty id", bad)
    # I2: act is one of six exact names
    acts = {"discharge": {}, "impossible": {}, "release": {}, "delegate": {"to": CODEX}, "substitute": {"to": CODEX},
            "revalidate": {"revalidates": [H3]}}
    rows = [(a, item(act=a, **kv), "accepted") for a, kv in acts.items()]
    rows += [(repr(a), item(act=a), "invalid") for a in ("close", "Discharge", "discharge\n", "discharge\r\n", "dıscharge", 1, None)]
    ok, bad = table(rows)
    check("I2", ok, "act is one of discharge, impossible, release, delegate, substitute, revalidate", bad)
    # I3: an item's evidence is a subset of its transition's
    rows = [(k, rec("transition", R.transition("ATTESTED", ev, closes=[R.item(H2, "discharge", iev)])), want)
            for k, ev, iev, want in (("subset", [H1, H3], [H1], "accepted"), ("equal", [H1], [H1], "accepted"),
                                     ("empty", [H1], [], "accepted"), ("outside", [H1], [H3], "invalid"),
                                     ("partly outside", [H1], [H1, H3], "invalid"), ("none carried", [], [H1], "invalid"))]
    ok, bad = table(rows)
    check("I3", ok, "item evidence is a subset of the transition's evidence", bad)
    # I4: period is an integer on a discharge, and a scheduled duty is discharged per period,
    # an unscheduled one never
    rows = [(k, item(**kv), want) for k, kv, want in (
        ("discharge period 0", {"period": 0}, "accepted"), ("impossible period", {"act": "impossible", "period": 0}, "invalid"),
        ("release period", {"act": "release", "period": 0}, "invalid"), ("period \"0\"", {"period": "0"}, "invalid"),
        ("period null", {"period": None}, "invalid"))]
    w = World()
    plain = w.duty(statement="plain")
    sched = w.duty(statement="scheduled", schedule={"start": 100, "every": 100}, at=100)
    a = w.close(plain, period=0, at=150)
    b = w.close(sched, at=150)
    c = w.close(sched, period=0, at=160)
    for t in (a, b, c):
        w.accept(OWNER, t)
    rep = w.assess(as_of=180)
    v = {c_["transition"]: c_["verdict"] for d in (plain, sched) for c_ in rep["duties"][d]["candidates"]}
    rows.append(("admitted", (v[a] == "ADMITTED", v[b] == "ADMITTED", v[c] == "ADMITTED"), (False, False, True)))
    ok, bad = table(rows)
    check("I4", ok, "period: an integer, required iff the duty is scheduled and the act is discharge", (bad, v))
    # I5: to is an actor on delegate and substitute, and only there
    rows = [(k, item(**kv), want) for k, kv, want in (
        ("delegate without to", {"act": "delegate"}, "invalid"), ("substitute without to", {"act": "substitute"}, "invalid"),
        ("delegate to 5", {"act": "delegate", "to": 5}, "invalid"), ("delegate to", {"act": "delegate", "to": "códex"}, "accepted"),
        ("delegate to \\n (W5: actor id shape)", {"act": "delegate", "to": "códex\n"}, "invalid"),
        ("discharge to", {"to": CODEX}, "invalid"), ("release to", {"act": "release", "to": CODEX}, "invalid"),
        ("revalidate to", {"act": "revalidate", "revalidates": [H3], "to": CODEX}, "invalid"))]
    ok, bad = table(rows)
    check("I5", ok, "to: an actor, required iff delegate or substitute", bad)
    # I6: revalidates is a non-empty list of transition ids, on revalidate only
    rows = bad_hex_rows("revalidates", lambda v: item(act="revalidate", revalidates=[v]))
    rows += [(k, item(**kv), want) for k, kv, want in (
        ("[]", {"act": "revalidate", "revalidates": []}, "invalid"), ("missing", {"act": "revalidate"}, "invalid"),
        ("on discharge", {"revalidates": [H3]}, "invalid"), ("control", {"act": "revalidate", "revalidates": [H3]}, "accepted"))]
    ok, bad = table(rows)
    check("I6", ok, "revalidates: non-empty, required iff revalidate", bad)
    # I7: an item's triggers on discharge, impossible and revalidate only
    tr = [{"kind": "duty_not_discharged", "duty": H3}]
    rows = [(a, item(act=a, triggers=tr, **kv), want) for a, kv, want in (
        ("discharge", {}, "accepted"), ("impossible", {}, "accepted"), ("revalidate", {"revalidates": [H3]}, "accepted"),
        ("release", {}, "invalid"), ("delegate", {"to": CODEX}, "invalid"), ("substitute", {"to": CODEX}, "invalid"))]
    rows.append(("bad trigger", item(triggers=[{"kind": "duty_not_discharged", "duty": H3 + "\n"}]), "invalid"))
    ok, bad = table(rows)
    check("I7", ok, "item triggers: discharge, impossible, revalidate only", bad)


def accept_cases():
    # A1: transition is a transition id
    rows = bad_hex_rows("transition", lambda v: rec("accept", put(ACCEPT, transition=v), OWNER))
    rows.append(("control", rec("accept", ACCEPT, OWNER), "accepted"))
    ok, bad = table(rows)
    check("A1", ok, "an acceptance names a transition id", bad)
    # A2: item is a non-negative integer index, or null
    rows = [(repr(v), rec("accept", put(ACCEPT, item=v), OWNER), want) for v, want in (
        (0, "accepted"), (3, "accepted"), (None, "accepted"), (-1, "invalid"), (True, "invalid"), (False, "invalid"),
        ("0", "invalid"), ([0], "invalid"))]
    ok, bad = table(rows)
    check("A2", ok, "item: int index into closes, or null", bad)
    # A3: a results acceptance (item null) binds the transition's exact evidence list
    w = World()
    t = w.act(HOLDER, [], evidence=[w.evidence("one"), w.evidence("two")], established=["it holds"])
    t2 = w.act(HOLDER, [], evidence=[w.evidence("three")], established=["so does this"])
    w.accept(OWNER, t, None, evidence=[w.evidence("one")])
    w.accept(OWNER, t2, None)
    rep = w.assess(prof=E.profile(results_by=[OWNER]))
    rows = [("other evidence set", rep["results"][t]["accepted"], False), ("exact", rep["results"][t2]["accepted"], True)]
    ok, bad = table(rows)
    check("A3", ok, "a results acceptance binds the transition's exact evidence", bad)
    # A4: support is a list of hex64
    rows = bad_hex_rows("support", lambda v: rec("accept", put(ACCEPT, support=[v]), OWNER))
    rows.append(("control", rec("accept", put(ACCEPT, support=[H2]), OWNER), "accepted"))
    ok, bad = table(rows)
    check("A4", ok, "support is a list of hex64", bad)
    # A6: an acceptance of another transition, with the same item index and evidence, is not this one
    w = World()
    d = w.duty()
    ev = [w.evidence("same")]
    t = w.close(d, evidence=ev)
    other = w.act(HOLDER, [], evidence=ev, established=["unrelated"])
    w.accept(OWNER, other, 0, evidence=ev)
    rep = w.assess()
    rows = [("disposition", rep["duties"][d]["disposition"], "OPEN")]
    w.accept(OWNER, t, 0)
    rows.append(("control", w.assess()["duties"][d]["disposition"], "DISCHARGED"))
    ok, bad = table(rows)
    check("A6", ok, "an acceptance of another transition is not this one", bad)
    # A7: an acceptance of item 0 is not an acceptance of the transition's results (item
    # null), nor the other way round, with the same evidence list (Gemini deep review
    # 2026-10-22, counter against SPEC-3.3-8: X1 and A6 never accept a null item)
    w = World()
    d = w.duty()
    ev = [w.evidence("same")]
    t = w.act(HOLDER, [R.item(d, "discharge", ev)], evidence=ev, established=["it holds"])
    w.accept(OWNER, t, 0)
    prof = E.profile(results_by=[OWNER])
    rep = w.assess(prof=prof)
    w2 = World()
    d2 = w2.duty()
    t2 = w2.act(HOLDER, [R.item(d2, "discharge", [w2.evidence("same")])], evidence=[w2.evidence("same")],
                established=["it holds"])
    w2.accept(OWNER, t2, None)
    rep2 = w2.assess(prof=prof)
    w2.accept(OWNER, t2, 0)
    rep3 = w2.assess(prof=prof)
    rows = [("item 0 accepted: the item", rep["duties"][d]["disposition"], "DISCHARGED"),
            ("item 0 accepted: the results", rep["results"][t]["accepted"], False),
            ("results accepted: the item", rep2["duties"][d2]["disposition"], "OPEN"),
            ("results accepted: the results", rep2["results"][t2]["accepted"], True),
            ("both accepted", (rep3["duties"][d2]["disposition"], rep3["results"][t2]["accepted"]), ("DISCHARGED", True))]
    ok, bad = table(rows)
    check("A7", ok, "an acceptance of an item is not one of the results, nor the other way round", bad)


def observation_cases():
    def obs(at=100, **kv):
        return rec("observation", put(OBSERVATION, **kv), OBSERVER, at=at)
    # O1: target is a string
    rows = [(k, obs(target=v), want) for k, v, want in (
        ("5", 5, "invalid"), ("null", None, "invalid"), ("[s]", ["service"], "invalid"),
        ("\\n and non-ASCII", "sérvice\n", "accepted"))]
    ok, bad = table(rows)
    check("O1", ok, "target is a string", bad)
    # O2: probe is a hex64
    rows = bad_hex_rows("probe", lambda v: obs(probe=v)) + [("control", obs(), "accepted")]
    ok, bad = table(rows)
    check("O2", ok, "probe is a hex64", bad)
    # O3: window [from, to], from ≤ to ≤ the record's at
    rows = [(k, obs(at=at, window=v), want) for k, at, v, want in (
        ("from = to = at", 20, [20, 20], "accepted"), ("from < to < at", 100, [10, 20], "accepted"),
        ("from > to", 100, [21, 20], "invalid"), ("to > at", 19, [10, 20], "invalid"), ("one", 100, [10], "invalid"),
        ("three", 100, [1, 2, 3], "invalid"), ("strings", 100, ["10", "20"], "invalid"), ("an object", 100, {"from": 1, "to": 2}, "invalid"))]
    ok, bad = table(rows)
    check("O3", ok, "window [from, to], from ≤ to ≤ at", bad)
    # O4: result is a string, compared verbatim: a trailing newline or another case is another result
    rows = [(k, obs(result=v), want) for k, v, want in (("5", 5, "invalid"), ("null", None, "invalid"), ("empty", "", "accepted"))]
    w = World()
    probe = w.evidence("GET /health")
    got = {}
    for k, result in (("exact", "ok"), ("\\n", "ok\n"), ("\\r\\n", "ok\r\n"), ("case", "OK"), ("space", " ok"), ("non-ASCII", "оk")):
        d = w.duty(condition={"observe": {"observers": [OBSERVER], "probe": probe, "expect": "ok", "fresh_for": None}},
                   statement=f"watch {k}", accept_by=())
        o = w.file("observation", OBSERVER, R.observation("health", probe, [w.t, w.t], result))
        w.close(d, basis="OBSERVED", evidence=[o])
        got[k] = d
    rep = w.assess()
    disp = {k: rep["duties"][d]["disposition"] for k, d in got.items()}
    rows.append(("dispositions", disp, {k: "DISCHARGED" if k == "exact" else "OPEN" for k in got}))
    ok, bad = table(rows)
    check("O4", ok, "result is a string, taken verbatim", bad)
    # O5: raw is a list of hex64
    rows = bad_hex_rows("raw", lambda v: obs(raw=[v])) + [("control", obs(raw=[H1, H2]), "accepted")]
    ok, bad = table(rows)
    check("O5", ok, "raw is a list of hex64", bad)


def grant_cases():
    def g(**kv):
        return rec("grant", put(GRANT, **kv), OWNER)
    # G2: grantee is an actor
    rows = [(k, g(grantee=v), want) for k, v, want in (
        ("5", 5, "invalid"), ("null", None, "invalid"), ("[s]", [STRANGER], "invalid"), ("non-ASCII", "stränger", "accepted"),
        ("trailing \\n (W5: actor id shape)", "stränger\n", "invalid"))]
    ok, bad = table(rows)
    check("G2", ok, "grantee is an actor", bad)
    # G3: acts is a non-empty sorted list from {release}
    rows = [(k, g(acts=v), want) for k, v, want in (
        ("[]", [], "invalid"), ("discharge", ["discharge"], "invalid"), ("twice", ["release", "release"], "invalid"),
        ("release\\n", ["release\n"], "invalid"), ("a string", "release", "invalid"), ("release", ["release"], "accepted"))]
    ok, bad = table(rows)
    check("G3", ok, "acts: non-empty sorted list from {release}", bad)
    # G4: delegable is a sorted list of acts within acts
    rows = [(k, g(delegable=v), want) for k, v, want in (
        ("[]", [], "accepted"), ("release", ["release"], "accepted"), ("discharge", ["discharge"], "invalid"),
        ("release\\n", ["release\n"], "invalid"), ("twice", ["release", "release"], "invalid"), ("a string", "release", "invalid"))]
    ok, bad = table(rows)
    check("G4", ok, "delegable: a sorted subset of acts", bad)
    # G5: duties is a non-empty sorted list of duty ids
    rows = bad_hex_rows("duties", lambda v: g(duties=[v]))
    rows += [(k, g(duties=v), want) for k, v, want in (
        ("[]", [], "invalid"), ("unsorted", [H2, H1], "invalid"), ("twice", [H1, H1], "invalid"), ("sorted", [H1, H2], "accepted"))]
    ok, bad = table(rows)
    check("G5", ok, "duties: non-empty sorted list of duty ids", bad)
    # G6: expires is an integer or null
    rows = [(repr(v), g(expires=v), want) for v, want in ((None, "accepted"), (300, "accepted"), ("300", "invalid"),
                                                         (True, "invalid"), ([300], "invalid"))]
    ok, bad = table(rows)
    check("G6", ok, "expires: int | null", bad)
    # G7: parent is null or a grant id
    rows = bad_hex_rows("parent", lambda v: g(parent=v), nullable=True)
    rows += [("null", g(parent=None), "accepted"), ("id", g(parent=H3), "accepted")]
    ok, bad = table(rows)
    check("G7", ok, "parent: null | grant id", bad)


def challenge_cases():
    def c(**kv):
        return rec("challenge", put(CHALLENGE, **kv), STRANGER)
    rows = bad_hex_rows("target", lambda v: c(target=v)) + [("control", c(), "accepted")]
    ok, bad = table(rows)
    check("C1", ok, "a challenge's target is a transition id", bad)
    rows = [(repr(v), c(item=v), want) for v, want in ((None, "accepted"), (0, "accepted"), (7, "accepted"), (-1, "invalid"),
                                                     (True, "invalid"), ("0", "invalid"))]
    ok, bad = table(rows)
    check("C2", ok, "a challenge's item: int | null", bad)
    rows = [(k, c(statement=v), want) for k, v, want in (("5", 5, "invalid"), ("null", None, "invalid"), ("[s]", ["x"], "invalid"),
                                                         ("\\n and non-ASCII", "fails on é\n", "accepted"))]
    ok, bad = table(rows)
    check("C3", ok, "a challenge's statement is a string", bad)
    rows = bad_hex_rows("evidence", lambda v: c(evidence=[v])) + [("control", c(evidence=[H1, H2]), "accepted")]
    ok, bad = table(rows)
    check("C4", ok, "a challenge's evidence is a list of hex64", bad)


def main():
    # The chain cases run first and every later group is guarded: a mutant that makes every
    # unchained record invalid (M419) fails K14 on its assertion instead of losing the results
    # file when a later group builds an unchained record.
    for group in (chain_cases, encoding_cases, record_cases, duty_cases, transition_cases, item_cases, accept_cases,
                  observation_cases, grant_cases, challenge_cases):
        try:
            group()
        except Exception as e:      # noqa: BLE001
            check(f"RAISED-{group.__name__}", False, f"{group.__name__} ran to its end", f"{type(e).__name__}: {e}")
    return finish("RECORDS")


if __name__ == "__main__":
    sys.exit(main())
