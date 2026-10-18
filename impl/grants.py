#!/usr/bin/env python3
"""WRT-022 S3: minimal grants -- explicit roots and attenuation (rev 2 §4.1).

DRAFT profile code, used by impl/loops.py. Nothing `warrant verify` decides changes.

A grant is an AUTHORIZATION: which acts an actor may perform, on which duties, until
when. It is not a competence record and not a duty. A key that the trust snapshot
binds to an actor authenticates that actor's records; it authorizes nothing.

    warrant.grant@draft-2
      grantor, grantee      actor ids; the grant's record must be signed by the grantor
      acts                  sorted, unique, from ACTS
      delegable             the acts the grantee may grant on (a subset of acts)
      duties                sorted, unique duty WarrantIDs: the scope
      expires               an integer timestamp (exclusive), or null
      parent                the WarrantID of the grant record this one attenuates, or null

A grant is VALID at a position (an admission timestamp) iff its record is in the
view at or before that position, it has not expired there, and either
  - it is a ROOT: parent null, and the recipient's profile lists its record in
    `grant_roots` (an explicit act of the recipient, never inferred), or
  - it attenuates a parent VALID at the child's own position: the child's grantor is
    the parent's grantee, its acts are in the parent's `delegable`, its delegable
    acts are within its own acts and the parent's delegable, its duties are within
    the parent's, and it expires no later than the parent.
Revocation, conflicting grants, quotas, `open_for`, `reassign`, `runner` and
`migrate_profile` are later slices; S3 validates and wires `release` only.
"""
import re

GRANT = "warrant.grant@draft-2"
ACTS = {"release", "contest", "adjudicate", "enrol"}
FIELDS = {"schema", "grantor", "grantee", "acts", "delegable", "duties", "expires", "parent"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_CHAIN = 16
STATES = {"VALID", "UNGROUNDED", "EXPIRED", "NOT_YET", "NOT_ATTENUATED", "BROKEN_CHAIN"}


def _strs_sorted_unique(v, member=None):
    return (isinstance(v, list) and all(isinstance(x, str) and x and (member is None or member(x)) for x in v)
            and v == sorted(set(v)))


def grant_problem(g):
    """None if `g` is a well-formed grant, else the reason (JSON types before membership)."""
    if not (isinstance(g, dict) and g.get("schema") == GRANT and set(g) == FIELDS):
        return "grant fields"
    if not all(isinstance(g[k], str) and g[k] for k in ("grantor", "grantee")):
        return "grantor and grantee"
    if not (_strs_sorted_unique(g["acts"], lambda a: a in ACTS) and g["acts"]):
        return "acts"
    if not (_strs_sorted_unique(g["delegable"], lambda a: a in ACTS) and set(g["delegable"]) <= set(g["acts"])):
        return "delegable must be a subset of acts"
    if not (_strs_sorted_unique(g["duties"], lambda h: HEX64.match(h) is not None) and g["duties"]):
        return "duties"
    if not (g["expires"] is None or type(g["expires"]) is int):
        return "expires"
    if not (g["parent"] is None or (isinstance(g["parent"], str) and HEX64.match(g["parent"]))):
        return "parent"
    return None


class Grants:
    """The grants of one view: {record id: (ts, grant)}, the recipient's accepted roots."""

    def __init__(self, records, roots):
        self.records, self.roots = records, set(roots)

    def state(self, gid, at, depth=0):
        """(state, reason) of grant record `gid` at position `at`."""
        if gid not in self.records:
            return "BROKEN_CHAIN", "grant not in view"
        ts, g = self.records[gid]
        if ts > at:
            return "NOT_YET", "granted after this position"
        if g["expires"] is not None and at >= g["expires"]:
            return "EXPIRED", f"expired at {g['expires']}"
        if g["parent"] is None:
            return ("VALID", "root") if gid in self.roots else ("UNGROUNDED", "a root the recipient has not accepted")
        if depth >= MAX_CHAIN:
            return "BROKEN_CHAIN", "chain too long"
        pst, why = self.state(g["parent"], ts, depth + 1)       # the parent at the CHILD's position
        if pst != "VALID":
            return ("BROKEN_CHAIN" if pst in ("BROKEN_CHAIN", "UNGROUNDED", "NOT_YET") else pst,
                    f"parent {g['parent'][:12]}: {why}")
        p = self.records[g["parent"]][1]
        problem = _attenuation_problem(g, p)
        if problem:
            return "NOT_ATTENUATED", problem
        return "VALID", "attenuated"


def _attenuation_problem(g, p):
    if g["grantor"] != p["grantee"]:
        return "the grantor is not the parent's grantee"
    if not set(g["acts"]) <= set(p["delegable"]):
        return "acts the parent did not make delegable"
    if not set(g["delegable"]) <= set(p["delegable"]):
        return "delegable beyond the parent's"
    if not set(g["duties"]) <= set(p["duties"]):
        return "duties beyond the parent's"
    if p["expires"] is not None and (g["expires"] is None or g["expires"] > p["expires"]):
        return "expires later than the parent"
    return None


def authorized(grants, actor, act, duty, at):
    """The valid grant by which `actor` may perform `act` on `duty` at `at`, or
    (None, reason). Only grants whose grantee is `actor` count."""
    reasons = []
    for gid, (_, g) in sorted(grants.records.items()):
        if g["grantee"] != actor or act not in g["acts"] or duty not in g["duties"]:
            continue
        st, why = grants.state(gid, at)
        if st == "VALID":
            return gid, None
        reasons.append(f"{gid[:12]}: {st} ({why})")
    return None, "; ".join(reasons) if reasons else f"no grant gives {actor} {act} on this duty"
