"""Bindings and roles (the open circle of witnesses, part A, and AMEND 1 of #170): the
repository side. The admission rule itself is warrant.bindings, the one rule a warrant-agent
workspace admits a repository's keys by too; this module adds what only the claims tool does:
write a binding, compare with a base revision, a receiver's own trust file."""
import os

from warrant import jcs as C
from warrant import keys as K
from warrant import records as R
# The rule's names are this module's too: `from .bindings import *` and CL.<name> read them here.
from warrant.bindings import (BINDING, BINDING_FIELDS, BINDINGS, COLLECTIVE, ROLES, _role_name, admit_bindings,
                              binding_message, binding_proof, read_roles, trust_of)
from warrant.store import Trust

from .base import Refused


LOCAL_TRUST = "WARRANT_CLAIMS_TRUST"         # a receiver's own trust/2 file, added to the admitted bindings


def unpinned(roles, names, where):
    """ROLE_UNPINNED for each actor a configuration file names that .warrant/roles.json does not."""
    return [("ROLE_UNPINNED", f"{where} names {a!r}, and .warrant/roles.json gives it no role: a name with a role "
             "is pinned (a key, null for reserved, or collective), never first-come")
            for a in sorted(set(names) - set(roles))]


def local_bindings():
    """[(actor, public)] of the receiver's own trust/2 file named by $WARRANT_CLAIMS_TRUST, if
    any: a receiver may bind whatever keys it chooses for itself (SPEC §4.6); nothing in the
    repository can set it, and CI sets none. The claims selftest binds its ephemeral key here."""
    path = os.environ.get(LOCAL_TRUST)
    return [] if not path else [(a, p) for a, p in Trust.load(path).keys.values()]


def bindings_kept(was, now, rev):
    """BINDING_REMOVED for each binding admitted at the base and not admitted now: the first
    binding of an actor wins only if a later change can neither drop it nor put another
    binding of that actor before it (a binding is never deleted, like a record)."""
    have = set(now)
    return [("BINDING_REMOVED", f"{a} -> key {K.key_id(p)[:12]} is admitted at {rev[:12]} and not now")
            for a, p in was if (a, p) not in have]


def pin_conflicts(was, roles, rev):
    """ROLE_PIN_CONFLICT for each binding admitted at the base that a role pin now contradicts:
    a binding is never removed (BINDING_REMOVED), so a pin may not take its name from it."""
    return [("ROLE_PIN_CONFLICT", f"{a} is bound to key {K.key_id(p)[:12]} at {rev[:12]}; .warrant/roles.json now says "
             f"{_role_name(roles[a])}")
            for a, p in was if a in roles and roles[a] != p]


def bound_document(repo, key, actor):
    """The bindings document with `key` bound to `actor` and its proof (binding_proof): an
    entry of the same actor and key gets the proof, otherwise one is appended. Refused, with
    the code `check` would give, when the result would not admit the binding. A trust/2 file
    (before bindings carried proofs) is read as entries without proofs."""
    try:
        R.check_actor(actor)
    except R.Invalid as e:
        raise Refused(f"{actor!r} is not an actor id (SPEC-3-21): {e}", "BINDING_ACTOR_SHAPE") from e
    doc = C.loads(repo.trust_path.read_bytes()) if repo.trust_path.is_file() else {"bindings": BINDINGS, "keys": []}
    if isinstance(doc, dict) and doc.get("warrant") == "trust/2":
        doc = {"bindings": BINDINGS, "keys": [dict(k) for k in doc.get("keys", [])]}
    entry = {"actor": actor, "public": key.public, "proof": binding_proof(key, actor)}
    keys = [entry if isinstance(k, dict) and k.get("actor") == actor and k.get("public") == key.public else k
            for k in doc.get("keys", [])]
    doc = {"bindings": BINDINGS, "keys": keys if entry in keys else keys + [entry]}
    admitted, problems = admit_bindings(doc, roles=repo.roles()[0])
    if (actor, key.public) not in admitted:
        mine = [(c, w) for c, w in problems if f"keys[{doc['keys'].index(entry)}]" in w]
        code, why = mine[0] if mine else ("BINDINGS_SHAPE", "; ".join(w for _, w in problems))
        raise Refused(why, code)
    return doc


def write_bindings(repo, doc):
    repo.trust_path.parent.mkdir(parents=True, exist_ok=True)
    repo.trust_path.write_bytes(C.canon(doc))

