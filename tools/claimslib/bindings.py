"""Bindings and roles (the open circle of witnesses, part A, and AMEND 1 of #170).

A binding certifies itself: its key signs canon({actor, public, purpose}). `admit_bindings`
admits one mechanically, in file order, under the roles .warrant/roles.json pins; nobody judges
who may join. A binding grants only "this key signs as this actor" (SPEC §6)."""
import os

from warrant import jcs as C
from warrant import keys as K
from warrant import records as R
from warrant import shapes as S
from warrant.store import Trust

from .base import Refused


# Open circle of witnesses: a binding certifies itself (its key signs it); nobody admits anyone.
BINDINGS = "warrant-claims/bindings@1"       # .warrant/trust.json: {"bindings": BINDINGS, "keys": [...]}
BINDING = "warrant-claims/binding@1"         # the purpose a proof signs: canon({actor, public, purpose})
BINDING_FIELDS = ("actor", "public", "proof")
LOCAL_TRUST = "WARRANT_CLAIMS_TRUST"         # a receiver's own trust/2 file, added to the admitted bindings
ROLES = "warrant-claims/roles@1"             # .warrant/roles.json: the actors the configuration gives a role
COLLECTIVE = "collective"                    # a role no key signs as (readers): never bindable


def binding_message(actor, public):
    """The bytes a binding's proof signs: canon({actor, public, purpose}). It starts with `{`,
    so it is never the message of a record signature ("warrant-sig-v1:" || id)."""
    return C.canon({"actor": actor, "public": public, "purpose": BINDING})


def binding_proof(key, actor):
    return key.sign(binding_message(actor, key.public))


def read_roles(doc):
    """({actor: public hex | None | COLLECTIVE}, problems) of a roles document (.warrant/roles.json).

    AMEND 1 of #170: a name the repository's own configuration gives a role (an acceptor, a
    creditor, the claims' author) is not first-come. Its key is pinned here, as a receiver's
    profile pins the keys it trusts: a hex64 public key (a binding of that actor is admitted
    with exactly that key), null (reserved: not bindable until a pin names its key) or
    "collective" (a role no key signs as, such as `readers`: never bindable). Every other
    name stays first-come. Changing who a role is, is a diff of this reviewed file."""
    if not (isinstance(doc, dict) and set(doc) == {"roles", "actors"} and doc["roles"] == ROLES
            and isinstance(doc["actors"], dict)):
        return {}, [("ROLES_SHAPE", f".warrant/roles.json is not {{\"roles\": {ROLES!r}, \"actors\": {{...}}}}")]
    roles, problems = {}, []
    for actor, v in doc["actors"].items():
        try:
            R.check_actor(actor)
        except R.Invalid as e:
            problems.append(("ROLES_SHAPE", f".warrant/roles.json: {actor[:60]!r} is not an actor id: {e}"))
            continue
        if not (v is None or v == COLLECTIVE or S.hex64(v)):
            problems.append(("ROLES_SHAPE", f".warrant/roles.json: {actor}: a role is a hex64 public key, null or "
                             f"{COLLECTIVE!r}, not {str(v)[:70]!r}"))
            continue
        roles[actor] = v
    return roles, problems


def _role_name(v):
    """A role value for a message: 'key <id>' for a key, else what it is (never raises)."""
    return f"key {K.key_id(v)[:12]}" if S.hex64(v) else "collective" if v == COLLECTIVE \
        else "reserved" if v is None else repr(v)[:40]


def unpinned(roles, names, where):
    """ROLE_UNPINNED for each actor a configuration file names that .warrant/roles.json does not."""
    return [("ROLE_UNPINNED", f"{where} names {a!r}, and .warrant/roles.json gives it no role: a name with a role "
             "is pinned (a key, null for reserved, or collective), never first-come")
            for a in sorted(set(names) - set(roles))]


def admit_bindings(doc, legacy=False, roles=None):
    """(admitted [(actor, public)], problems [(code, detail)]) of a bindings document.

    A binding is admitted mechanically, in file order, iff its proof is the signature of its
    own key over binding_message(actor, public), its actor id has SPEC-3-21's shape, its
    actor's role (`roles`, read_roles) admits that key, its key is not bound already, and its
    actor is not bound already to another key: the first binding of a name with no role
    wins, and a second key for it would need a record signed by the first, which this tool
    does not implement (rotation is out of scope), so it is refused. Nobody judges who may
    join; what a binding grants is only "this key signs as this actor" (SPEC §6). `legacy`
    reads a trust/2 document (actor, public, no proof) as admitted: only for a base revision
    written before bindings carried proofs."""
    if legacy and isinstance(doc, dict) and doc.get("warrant") == "trust/2":
        try:
            return [(a, p) for a, p in Trust(doc).keys.values()], []
        except R.Invalid as e:
            return [], [("BINDINGS_SHAPE", f".warrant/trust.json: {e}")]
    if not (isinstance(doc, dict) and set(doc) == {"bindings", "keys"} and doc["bindings"] == BINDINGS
            and isinstance(doc["keys"], list)):
        return [], [("BINDINGS_SHAPE", f".warrant/trust.json is not {{\"bindings\": {BINDINGS!r}, \"keys\": [...]}} "
                                       "(tools/claims.py bind writes it)")]
    admitted, problems = [], []
    publics = [k.get("public") for k in doc["keys"] if isinstance(k, dict)]
    for i, k in enumerate(doc["keys"]):
        code, why = _binding_problem(k, publics, admitted, roles or {})
        if code:
            problems.append((code, f".warrant/trust.json keys[{i}]: {why}"))
        else:
            admitted.append((k["actor"], k["public"]))
    return admitted, problems


def _binding_problem(k, publics, admitted, roles):
    """(code, why) when entry `k` is not admitted after `admitted`, else (None, None)."""
    if not (isinstance(k, dict) and set(k) <= set(BINDING_FIELDS) and {"actor", "public"} <= set(k)
            and S.hex64(k["public"])):
        return "BINDING_SHAPE", f"an entry is {{actor, public: hex64, proof: hex128}}, not {str(k)[:120]}"
    try:
        R.check_actor(k["actor"])
    except R.Invalid as e:
        return "BINDING_ACTOR_SHAPE", f"{str(k['actor'])[:60]!r} is not an actor id (SPEC-3-21): {e}"
    if "proof" not in k:
        return "BINDING_UNPROVEN", f"{k['actor']}: no proof; the key's own signature over the binding is needed"
    msg = binding_message(k["actor"], k["public"])
    if not K.verify(k["public"], k["proof"], msg):
        other = [p for p in publics if p != k["public"] and isinstance(p, str) and K.verify(p, k["proof"], msg)]
        if other:
            return "BINDING_PROOF_OTHER_KEY", (f"{k['actor']}: the proof is signed by key {K.key_id(other[0])[:12]}, "
                                               f"not by the key it binds ({K.key_id(k['public'])[:12]})")
        return "BINDING_PROOF_FORGED", f"{k['actor']}: the proof is not the bound key's signature over this binding"
    role = roles.get(k["actor"], k["public"])
    if role != k["public"]:                 # one rule; the code only says which kind of role refused it
        if role == COLLECTIVE:
            return "BINDING_ROLE_COLLECTIVE", f"{k['actor']} is a collective role in .warrant/roles.json: no key signs as it"
        if role is None:
            return "BINDING_ROLE_RESERVED", (f"{k['actor']} is reserved in .warrant/roles.json: it is bindable once a "
                                             "reviewed pin names its key")
        return "BINDING_ROLE_KEY", (f"{k['actor']}: .warrant/roles.json pins {_role_name(role)}, this binding is of "
                                    f"key {K.key_id(k['public'])[:12]}")
    if any(p == k["public"] for _, p in admitted):
        return "BINDING_KEY_TWICE", f"key {K.key_id(k['public'])[:12]} is bound already"
    first = next((p for a, p in admitted if a == k["actor"]), None)
    if first is not None:
        return "BINDING_ACTOR_TAKEN", (f"{k['actor']} is bound already to key {K.key_id(first)[:12]}; the first "
                                       "binding wins, and rotation (a record signed by the first key) is not "
                                       "implemented, so a second key for an actor is refused")
    return None, None


def local_bindings():
    """[(actor, public)] of the receiver's own trust/2 file named by $WARRANT_CLAIMS_TRUST, if
    any: a receiver may bind whatever keys it chooses for itself (SPEC §4.6); nothing in the
    repository can set it, and CI sets none. The claims selftest binds its ephemeral key here."""
    path = os.environ.get(LOCAL_TRUST)
    return [] if not path else [(a, p) for a, p in Trust.load(path).keys.values()]


def trust_of(bindings):
    """A Trust of (actor, public) pairs, the first binding of each key kept."""
    seen, pairs = set(), []
    for a, p in bindings:
        if p not in seen:
            seen.add(p)
            pairs.append((a, p))
    return Trust(Trust.document(pairs))


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
