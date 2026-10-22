"""The lexical shapes of SPEC §2-§3, each defined once.

A value is checked against its shape before anything reads it. Every module that checks one
of these shapes imports it from here: warrant, warrant_agent and the tools. Before this module
existed, fourteen definitions of these four shapes (hex64, hex128, a 32-digit token, a question
reference) and of the actor-id predicate lived in eleven modules, and one defect of the family,
`$` used where `\\Z` was meant, had to be fixed at fourteen sites (AMEND 2 of #164). Each pattern is
anchored with `\\Z`. With `.match`, `$` also matches before a final newline, so a 64-character
id followed by "\\n" passed. Digits are written [0-9], never \\d, because \\d matches any
Unicode digit. Hex is lowercase."""
import re
import unicodedata

HEX = re.compile(r"^[0-9a-f]*\Z")              # lowercase hex of any length (hex_of gives it one)
HEX32 = re.compile(r"^[0-9a-f]{32}\Z")        # a view token (warrant_agent.views)
HEX64 = re.compile(r"^[0-9a-f]{64}\Z")        # a record id, a blob address, an Ed25519 public key
HEX128 = re.compile(r"^[0-9a-f]{128}\Z")      # an Ed25519 signature
# A question reference: "<transition id>:<index of its opened question>", the index without leading zeros.
QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})\Z")
MAX_ACTOR = 200
# Unicode White_Space outside Cc (Cc is refused anywhere in an actor id): Zs, Zl, Zp.
EDGE_SPACE = ("Zs", "Zl", "Zp")


def hex64(v):
    """True iff `v` is a string of exactly 64 lowercase hex digits."""
    return isinstance(v, str) and HEX64.match(v) is not None


def hex128(v):
    """True iff `v` is a string of exactly 128 lowercase hex digits."""
    return isinstance(v, str) and HEX128.match(v) is not None


def hex_of(v, n):
    """True iff `v` is a string of exactly `n` lowercase hex digits (a git object id: n = 40 or 64)."""
    return isinstance(v, str) and len(v) == n and HEX.match(v) is not None


def qref(v):
    """True iff `v` is a question reference (QREF)."""
    return isinstance(v, str) and QREF.match(v) is not None


def actor_problem(v):
    """None if `v` is an actor id (SPEC §3), else the reason it is not, phrased to follow the
    member's name. An actor id is a non-empty string of at most 200 code points, in NFC, with
    no control character (Cc) and no white space at either end. Nothing here asks what the
    actor is: a person, a model, a program and a rule have ids of the same shape."""
    if not (isinstance(v, str) and v and len(v) <= MAX_ACTOR):
        return f"must be a string ≤ {MAX_ACTOR}"
    if not unicodedata.is_normalized("NFC", v):
        return "must be in Unicode NFC"
    if any(unicodedata.category(c) == "Cc" for c in v):
        return "must not contain a control character"
    if unicodedata.category(v[0]) in EDGE_SPACE or unicodedata.category(v[-1]) in EDGE_SPACE:
        return "must not begin or end with white space"
    return None


def is_actor(v):
    """True iff `v` is an actor id (actor_problem)."""
    return actor_problem(v) is None
