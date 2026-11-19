"""Attenuating cryptographic capability delegation for Warrant 3 (`grant@1`, docs/DELEGATION.md).

In static Warrant 3, a receiver's `trust` binds keys to actors and its `profile` grants roles to those actors.
An actor cannot spawn an ephemeral sub-agent or delegate a narrow, time-bounded, revocable capability to a peer
without sharing its master key or editing every receiver's static `v3.json`.

This module defines a pure, fail-closed capability delegation algebra over Warrant 3's existing four-kind
envelope (`schema`, `entity`, `attest`, `challenge`) with no changes to the core engine:

  - Capability meet-semilattice `Cap(roles, kinds, schemas, lineages, not_before, not_after, max_depth)` with
    partial order `a <= b` iff `meet(a, b) == a`.
  - Monotonic attenuation: every hop `parent -> child` must strictly decrease `max_depth` (`0 <= d_child < d_parent`)
    and never widen roles, kinds, schemas, lineages or the validity window (`WIDENING` fails closed).
  - Cryptographic chaining: a root grant is signed by a key the receiver's `trust` binds to an actor holding every
    granted role in `profile`; a child grant is signed by its parent's bound `delegate_key` under `parent.delegate`.
  - Transitive ancestral brake: revoking a grant (a `state: "revoked"` successor signed by the grant's issuer or
    ANY ancestor issuer in its chain), forking its lineage, or standing a counted challenge against it invalidates
    the grant and every descendant in its subtree (`ANCESTOR_INVALID`).
  - Anti-laundering: a delegated `attest` never accepts a version authored by its root issuer, any ancestor in its
    chain, or another delegate anchored to the same root issuer (`DELEGATION_SELF_ACCEPT`).
  - Cross-grant isolation: a delegate holding distinct role subsets on distinct targets never bleeds roles across
    grants (`DELEGATION_OUT_OF_SCOPE`)."""
from dataclasses import dataclass

from . import engine as E
from . import jcs as C
from . import records as R
from . import shapes as S
from .store import Snapshot, _line_id

SCHEMA_NAME = "grant@1"
KINDS = ("attest", "challenge", "entity")
MAX_CHAIN_DEPTH = 32
SCHEMA = {
    "name": SCHEMA_NAME,
    "fields": {
        "state": "str",
        "delegate": "str",
        "delegate_key": "str",
        "roles": "strs",
        "kinds": "strs",
        "schemas": "strs?",
        "lineages": "refs?",
        "not_before": "int",
        "not_after": "int",
        "max_depth": "int",
        "parent": "ref?",
        "reason": "str?",
    },
    "states": {"active": None, "revoked": None},
    "closed": [],
    "successors": {},
}
STATUSES = (
    "ACTIVE",
    "REVOKED",
    "CHALLENGED",
    "FORKED",
    "EXPIRED",
    "NOT_YET_VALID",
    "WIDENING",
    "DEPTH_EXCEEDED",
    "UNANCHORED",
    "CYCLE",
    "INVALID_BODY",
    "ANCESTOR_INVALID",
)
REFUSALS = (
    "DELEGATION_OUT_OF_SCOPE",
    "DELEGATION_SELF_ACCEPT",
    "DELEGATION_QUORUM_INFLATION",
    "DELEGATION_OUTSIDE_WINDOW",
    "DELEGATION_UNKNOWN_TARGET",
    "DELEGATION_NOT_ACTIVE",
)


def _opt_meet(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a & b


def _opt_le(a, b):
    """True iff optional restriction `a` is at least as narrow as `b` (`None` is top)."""
    return True if b is None else (a is not None and a <= b)


@dataclass(frozen=True)
class Cap:
    """An element of the capability meet-semilattice. `schemas=None` and `lineages=None` denote top (unrestricted)."""

    roles: frozenset
    kinds: frozenset
    schemas: frozenset | None
    lineages: frozenset | None
    not_before: int
    not_after: int
    max_depth: int

    def meet(self, other):
        return Cap(
            roles=self.roles & other.roles,
            kinds=self.kinds & other.kinds,
            schemas=_opt_meet(self.schemas, other.schemas),
            lineages=_opt_meet(self.lineages, other.lineages),
            not_before=max(self.not_before, other.not_before),
            not_after=min(self.not_after, other.not_after),
            max_depth=min(self.max_depth, other.max_depth),
        )

    def le(self, other):
        """Partial order: `self <= other` iff `self` is no wider than `other` in every dimension."""
        return (
            self.roles <= other.roles
            and self.kinds <= other.kinds
            and _opt_le(self.schemas, other.schemas)
            and _opt_le(self.lineages, other.lineages)
            and self.not_before >= other.not_before
            and self.not_after <= other.not_after
            and self.max_depth <= other.max_depth
        )

    def widening_from(self, parent):
        """Sorted names of scope dimensions where `self` is wider than `parent` (excluding `max_depth`)."""
        bad = []
        if not (self.roles <= parent.roles):
            bad.append("roles")
        if not (self.kinds <= parent.kinds):
            bad.append("kinds")
        if not _opt_le(self.schemas, parent.schemas):
            bad.append("schemas")
        if not _opt_le(self.lineages, parent.lineages):
            bad.append("lineages")
        if self.not_before < parent.not_before or self.not_after > parent.not_after:
            bad.append("window")
        return bad

    def to_dict(self):
        return {
            "roles": sorted(self.roles),
            "kinds": sorted(self.kinds),
            "schemas": None if self.schemas is None else sorted(self.schemas),
            "lineages": None if self.lineages is None else sorted(self.lineages),
            "not_before": self.not_before,
            "not_after": self.not_after,
            "max_depth": self.max_depth,
        }


# ---------------------------------------------------------------- record builders & body validation

def _sorted_unique(items, name, check_fn):
    if not isinstance(items, list) or not items:
        raise R.Invalid(f"grant {name} must be a non-empty list")
    out = sorted(set(items))
    if not all(check_fn(x) for x in out):
        raise R.Invalid(f"grant {name} contains an invalid entry")
    return out


def _is_str_nonempty(v):
    return isinstance(v, str) and bool(v)


def grant_record(
    issuer,
    delegate,
    delegate_key,
    roles,
    kinds,
    not_before,
    not_after,
    max_depth=0,
    schemas=None,
    lineages=None,
    parent=None,
    at=0,
    prev=None,
    reason=None,
):
    """Build a canonical `grant@1` root entity record (unsigned; sign with `warrant.records.line`)."""
    if not S.is_actor(delegate):
        raise R.Invalid("grant delegate must be a valid actor id")
    if not S.hex64(delegate_key):
        raise R.Invalid("grant delegate_key must be 64 lowercase hex")
    r_list = _sorted_unique(roles, "roles", _is_str_nonempty)
    k_list = _sorted_unique(kinds, "kinds", lambda x: x in KINDS)
    s_list = None if schemas is None else _sorted_unique(schemas, "schemas", _is_str_nonempty)
    l_list = None if lineages is None else _sorted_unique(lineages, "lineages", S.hex64)
    if not (R.is_int(not_before) and R.is_int(not_after) and 0 <= not_before <= not_after):
        raise R.Invalid("grant window requires 0 <= not_before <= not_after")
    if not (R.is_int(max_depth) and 0 <= max_depth <= MAX_CHAIN_DEPTH):
        raise R.Invalid(f"grant max_depth must be 0..{MAX_CHAIN_DEPTH}")
    if parent is not None and not S.hex64(parent):
        raise R.Invalid("grant parent must be a 64-hex grant lineage id")
    body = {
        "state": "active",
        "delegate": delegate,
        "delegate_key": delegate_key,
        "roles": r_list,
        "kinds": k_list,
        "not_before": not_before,
        "not_after": not_after,
        "max_depth": max_depth,
    }
    if s_list is not None:
        body["schemas"] = s_list
    if l_list is not None:
        body["lineages"] = l_list
    if parent is not None:
        body["parent"] = parent
    if reason is not None:
        if not isinstance(reason, str):
            raise R.Invalid("grant reason must be a string")
        body["reason"] = reason
    refs = sorted(set(([parent] if parent is not None else []) + (l_list or [])))
    return R.record("entity", issuer, at, body, SCHEMA_NAME, lineage=None, refs=refs, prev=prev)


def revoke_record(actor, grant_root, leaf_id, at=0, prev=None, reason=None, delegate=None, delegate_key=None,
                  roles=None, kinds=None, not_before=0, not_after=0, max_depth=0, parent=None):
    """Build a canonical `state: "revoked"` successor record for a `grant@1` lineage.

    Carries the schema's required fields so the record is valid under `grant@1` in static `E.View` as well."""
    if not (S.hex64(grant_root) and S.hex64(leaf_id)):
        raise R.Invalid("grant_root and leaf_id must be 64 lowercase hex")
    if delegate is None or delegate_key is None or roles is None or kinds is None:
        raise R.Invalid("revoke_record requires the grant's delegate, delegate_key, roles and kinds")
    body = {
        "state": "revoked",
        "delegate": delegate,
        "delegate_key": delegate_key,
        "roles": sorted(set(roles)),
        "kinds": sorted(set(kinds)),
        "not_before": not_before,
        "not_after": not_after,
        "max_depth": max_depth,
    }
    if parent is not None:
        body["parent"] = parent
    if reason is not None:
        body["reason"] = reason
    refs = sorted(set(([parent] if parent is not None else []) + ([grant_root] if grant_root != leaf_id else [])))
    return R.record("entity", actor, at, body, SCHEMA_NAME, lineage=leaf_id, refs=refs, prev=prev)


def revoke_from(actor, root_rec, leaf_id, at=0, prev=None, reason=None):
    """Build a revocation successor directly from the root `grant@1` record dict."""
    b = root_rec["body"]
    return revoke_record(
        actor,
        R.rid(root_rec),
        leaf_id,
        at=at,
        prev=prev,
        reason=reason,
        delegate=b["delegate"],
        delegate_key=b["delegate_key"],
        roles=b["roles"],
        kinds=b["kinds"],
        not_before=b["not_before"],
        not_after=b["not_after"],
        max_depth=b["max_depth"],
        parent=b.get("parent"),
    )


def _parse_grant_body(body):
    """Return `(state, delegate, delegate_key, Cap, parent)` or `None` if malformed."""
    if not isinstance(body, dict):
        return None
    allowed = set(SCHEMA["fields"])
    if not (set(body) <= allowed):
        return None
    state = body.get("state")
    if state not in ("active", "revoked"):
        return None
    delegate = body.get("delegate")
    dkey = body.get("delegate_key")
    if not (S.is_actor(delegate) and S.hex64(dkey)):
        return None
    roles = body.get("roles")
    kinds = body.get("kinds")
    if not (R.is_list(roles, _is_str_nonempty, True) and roles):
        return None
    if not (R.is_list(kinds, lambda x: x in KINDS, True) and kinds):
        return None
    schemas = body.get("schemas")
    if schemas is not None and not (R.is_list(schemas, _is_str_nonempty, True) and schemas):
        return None
    lineages = body.get("lineages")
    if lineages is not None and not (R.is_list(lineages, S.hex64, True) and lineages):
        return None
    nb, na, md = body.get("not_before"), body.get("not_after"), body.get("max_depth")
    if not (R.is_int(nb) and R.is_int(na) and 0 <= nb <= na):
        return None
    if not (R.is_int(md) and 0 <= md <= MAX_CHAIN_DEPTH):
        return None
    parent = body.get("parent")
    if parent is not None and not S.hex64(parent):
        return None
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        return None
    cap = Cap(
        roles=frozenset(roles),
        kinds=frozenset(kinds),
        schemas=None if schemas is None else frozenset(schemas),
        lineages=None if lineages is None else frozenset(lineages),
        not_before=nb,
        not_after=na,
        max_depth=md,
    )
    return state, delegate, dkey, cap, parent


# ---------------------------------------------------------------- cryptographic grant chain resolution

def _actor_roles(profile, actor):
    return frozenset(role for role, actors in profile.get("roles", {}).items() if actor in actors)


def _verifies_any(rid, envs, keys):
    sigs = [e["sig"] for e in envs if e.get("sig") is not None]
    for s in sigs:
        for k in keys:
            if R.verifies(rid, s, k):
                return k
    return None


def _collect_grant_records(snap, as_of):
    """Raw candidate `grant@1` entity records and `challenge` records within `as_of`."""
    grant_envs, chall_envs = {}, {}
    for rid, envs in snap.lines.items():
        r = envs[0]["record"]
        if as_of is not None and r["at"] > as_of:
            continue
        if r["kind"] == "entity" and r["schema"] == SCHEMA_NAME:
            grant_envs[rid] = (r, envs)
        elif r["kind"] == "challenge":
            chall_envs[rid] = (r, envs)
    return grant_envs, chall_envs


def _resolve_root_authenticity(grant_envs, trust):
    """Iteratively authenticate `grant@1` root records: round 0 via `trust`, round k via parent's `delegate_key`.

    Returns `{root_id: (rec, parsed, signing_key, chain_of_root_ids)}` for cryptographically authentic roots,
    plus `unanchored` for roots that fail signature/parent verification, and `invalid_body` for malformed roots."""
    roots = {rid: item for rid, item in grant_envs.items() if item[0]["lineage"] is None}
    parsed = {}
    invalid_body = {}
    for rid, (r, _envs) in sorted(roots.items()):
        p = _parse_grant_body(r["body"])
        if p is None or p[0] != "active":
            invalid_body[rid] = "grant root must be a valid active grant@1 body"
        else:
            parsed[rid] = p

    auth = {}  # rid -> {"rec", "parsed", "signer_key", "chain"}
    # Round 0: root grants anchored directly in trust
    for rid, p in sorted(parsed.items()):
        r, envs = roots[rid]
        parent = p[4]
        if parent is not None:
            continue
        keys = trust["keys"].get(r["actor"], [])
        sk = _verifies_any(rid, envs, keys)
        if sk is not None:
            auth[rid] = {"rec": r, "parsed": p, "signer_key": sk, "chain": [rid]}

    # Rounds 1..MAX_CHAIN_DEPTH: chained grants signed by parent's bound delegate_key under parent's delegate
    for _ in range(MAX_CHAIN_DEPTH):
        progressed = False
        for rid, p in sorted(parsed.items()):
            if rid in auth:
                continue
            parent = p[4]
            if parent is None or parent not in auth:
                continue
            p_info = auth[parent]
            _, p_del, p_dkey, _, _ = p_info["parsed"]
            r, envs = roots[rid]
            if r["actor"] != p_del:
                continue
            if rid in p_info["chain"]:
                continue
            sk = _verifies_any(rid, envs, [p_dkey])
            if sk is not None:
                auth[rid] = {"rec": r, "parsed": p, "signer_key": sk, "chain": p_info["chain"] + [rid]}
                progressed = True
        if not progressed:
            break

    return roots, parsed, auth, invalid_body


def _detect_cycles(parsed, auth):
    """Identify roots involved in a `parent` cycle (never reached from a root grant)."""
    cyclic = set()
    for rid in parsed:
        if rid in auth:
            continue
        seen, cur = set(), rid
        while cur in parsed and cur not in seen:
            seen.add(cur)
            cur = parsed[cur][4]
        if cur in seen:
            cyclic |= seen
    return cyclic


def _grant_lineage_state(root_id, auth_info, grant_envs, chall_envs, auth_all, trust, profile):
    """Evaluate a single authenticated grant lineage's successors (revocations / forks) and standing challenges.

    Authorized revokers of `root_id`: the grant's own issuer (via its signing key or static trust keys) OR ANY
    ancestor issuer in `auth_info["chain"]` (transitive ancestral brake).
    Authorized challengers: any `challenger` in `profile`, the grant's issuer, or any ancestor issuer."""
    chain = auth_info["chain"]
    # Build map of authorized (actor -> set of keys) for ancestral revocation & challenges
    anc_keys = {}
    for gid in chain:
        g_rec = auth_all[gid]["rec"]
        g_actor = g_rec["actor"]
        anc_keys.setdefault(g_actor, set()).add(auth_all[gid]["signer_key"])
        anc_keys[g_actor] |= set(trust["keys"].get(g_actor, []))

    # Collect successor versions belonging to this grant lineage
    versions = {root_id: auth_info["rec"]}
    succ = {}
    # Fixed-point over successors referencing already-accepted versions in this lineage
    candidates = {rid: item for rid, item in grant_envs.items() if item[0]["lineage"] is not None}
    for _ in range(len(candidates) + 1):
        added = False
        for rid, (r, envs) in sorted(candidates.items()):
            if rid in versions:
                continue
            parent_ver = r["lineage"]
            if parent_ver not in versions:
                continue
            p = _parse_grant_body(r["body"])
            if p is None:
                continue
            allowed_keys = anc_keys.get(r["actor"])
            if not allowed_keys:
                continue
            if _verifies_any(rid, envs, sorted(allowed_keys)) is None:
                continue
            versions[rid] = r
            succ.setdefault(parent_ver, []).append(rid)
            added = True
        if not added:
            break

    forks = {p: sorted(cs) for p, cs in succ.items() if len(cs) > 1}
    if forks:
        return "FORKED", "grant lineage forked", sorted(versions), []

    # Follow linear chain from root to leaf
    cur = root_id
    path = [cur]
    while cur in succ:
        cur = succ[cur][0]
        path.append(cur)
    leaf = path[-1]
    if versions[leaf]["body"]["state"] == "revoked":
        by = versions[leaf]["actor"]
        return "REVOKED", f"revoked by {by} in {leaf[:12]}", path, []

    # Check standing challenges targeting any version in the grant lineage
    challenger_actors = set(profile.get("roles", {}).get("challenger", []))
    standing = []
    for cid, (cr, cenvs) in sorted(chall_envs.items()):
        t = (cr.get("body") or {}).get("target")
        if t not in versions:
            continue
        c_actor = cr["actor"]
        c_keys = set()
        if c_actor in challenger_actors:
            c_keys |= set(trust["keys"].get(c_actor, []))
        if c_actor in anc_keys:
            c_keys |= anc_keys[c_actor]
        if c_keys and _verifies_any(cid, cenvs, sorted(c_keys)) is not None:
            standing.append(cid)
    if standing:
        return "CHALLENGED", f"challenged by {standing[0][:12]}", path, standing

    return "OK", None, path, []


def resolve_grants(snap, trust, profile, as_of=None):
    """Resolve every `grant@1` lineage in `snap` under `trust` and `profile` at `as_of`.

    Returns `{grant_root_id: {...}}` where each entry carries:
      `id`, `issuer`, `delegate`, `delegate_key`, `root_issuer`, `chain`, `depth`, `status`,
      `reason`, `declared`, `effective`, `versions`, `challenges`."""
    for why in (E.trust_problem(trust), E.profile_problem(profile)):
        if why:
            raise R.Invalid(why)
    eff_as_of = as_of if as_of is not None else max((e[0]["record"]["at"] for e in snap.lines.values()), default=0)
    grant_envs, chall_envs = _collect_grant_records(snap, eff_as_of)
    roots, parsed, auth, invalid_body = _resolve_root_authenticity(grant_envs, trust)
    cyclic = _detect_cycles(parsed, auth)

    results = {}
    # 1. Malformed roots
    for rid, why in sorted(invalid_body.items()):
        r = roots[rid][0]
        results[rid] = {
            "id": rid,
            "issuer": r["actor"],
            "delegate": r["body"].get("delegate") if isinstance(r.get("body"), dict) else None,
            "delegate_key": r["body"].get("delegate_key") if isinstance(r.get("body"), dict) else None,
            "root_issuer": None,
            "chain": [rid],
            "depth": 0,
            "status": "INVALID_BODY",
            "reason": why,
            "declared": None,
            "effective": None,
            "versions": [rid],
            "challenges": [],
        }

    # 2. Unauthenticated or cyclic roots
    for rid, p in sorted(parsed.items()):
        if rid in auth:
            continue
        r = roots[rid][0]
        _, delegate, dkey, cap, _parent = p
        st = "CYCLE" if rid in cyclic else "UNANCHORED"
        why = "parent delegation chain contains a cycle" if st == "CYCLE" else "not signed by an anchored issuer or parent delegate_key"
        results[rid] = {
            "id": rid,
            "issuer": r["actor"],
            "delegate": delegate,
            "delegate_key": dkey,
            "root_issuer": None,
            "chain": [rid],
            "depth": 0,
            "status": st,
            "reason": why,
            "declared": cap.to_dict(),
            "effective": None,
            "versions": [rid],
            "challenges": [],
        }

    # 3. Authenticated chains, evaluated top-down by chain length (parents before children)
    eff_caps = {}  # rid -> Cap
    for rid in sorted(auth, key=lambda x: (len(auth[x]["chain"]), x)):
        info = auth[rid]
        r = info["rec"]
        _, delegate, dkey, cap, parent = info["parsed"]
        chain = info["chain"]
        depth = len(chain) - 1
        root_issuer = auth[chain[0]]["rec"]["actor"]

        # Self-delegation with the same signing key is a degenerate cycle
        if delegate == r["actor"] and dkey == info["signer_key"]:
            results[rid] = _entry(rid, r["actor"], delegate, dkey, root_issuer, chain, depth, "CYCLE",
                                  "actor cannot delegate to itself with the same key", cap, None, [rid], [])
            continue

        # Check parent first (transitive invalidation)
        if parent is not None:
            p_res = results[parent]
            if p_res["status"] != "ACTIVE":
                results[rid] = _entry(rid, r["actor"], delegate, dkey, root_issuer, chain, depth, "ANCESTOR_INVALID",
                                      f"parent grant {parent[:12]} is {p_res['status']}", cap, None, [rid], [])
                continue
            p_cap = eff_caps.get(parent) or auth[parent]["parsed"][3]
            if p_cap.max_depth < 1 or cap.max_depth >= p_cap.max_depth:
                results[rid] = _entry(rid, r["actor"], delegate, dkey, root_issuer, chain, depth, "DEPTH_EXCEEDED",
                                      f"child max_depth {cap.max_depth} must be strictly below parent {p_cap.max_depth}",
                                      cap, None, [rid], [])
                continue
            widened = cap.widening_from(p_cap)
            if widened:
                results[rid] = _entry(rid, r["actor"], delegate, dkey, root_issuer, chain, depth, "WIDENING",
                                      f"child widens parent on: {', '.join(widened)}", cap, None, [rid], [])
                continue
            eff = p_cap.meet(cap)
        else:
            # Root grant: issuer must hold every granted role in receiver's profile
            held = _actor_roles(profile, root_issuer)
            if not (cap.roles <= held):
                missing = sorted(cap.roles - held)
                results[rid] = _entry(rid, r["actor"], delegate, dkey, root_issuer, chain, depth, "WIDENING",
                                      f"root issuer {root_issuer} does not hold role(s): {', '.join(missing)}",
                                      cap, None, [rid], [])
                continue
            eff = cap

        # Lineage revocation, fork, or standing challenge
        l_status, l_why, versions, challs = _grant_lineage_state(
            rid, info, grant_envs, chall_envs, auth, trust, profile
        )
        if l_status != "OK":
            results[rid] = _entry(rid, r["actor"], delegate, dkey, root_issuer, chain, depth, l_status,
                                  l_why, cap, None, versions, challs)
            continue

        # Time window check against as_of
        if eff_as_of < eff.not_before:
            results[rid] = _entry(rid, r["actor"], delegate, dkey, root_issuer, chain, depth, "NOT_YET_VALID",
                                  f"as_of {eff_as_of} < not_before {eff.not_before}", cap, None, versions, challs)
            continue
        if eff_as_of > eff.not_after:
            results[rid] = _entry(rid, r["actor"], delegate, dkey, root_issuer, chain, depth, "EXPIRED",
                                  f"as_of {eff_as_of} > not_after {eff.not_after}", cap, None, versions, challs)
            continue

        eff_caps[rid] = eff
        results[rid] = _entry(rid, r["actor"], delegate, dkey, root_issuer, chain, depth, "ACTIVE",
                              None, cap, eff, versions, challs)

    return {k: results[k] for k in sorted(results)}


def _entry(rid, issuer, delegate, dkey, root_issuer, chain, depth, status, reason, declared, effective, versions, challs):
    return {
        "id": rid,
        "issuer": issuer,
        "delegate": delegate,
        "delegate_key": dkey,
        "root_issuer": root_issuer,
        "chain": list(chain),
        "depth": depth,
        "status": status,
        "reason": reason,
        "declared": declared.to_dict() if declared is not None else None,
        "effective": effective.to_dict() if effective is not None else None,
        "versions": list(versions),
        "challenges": list(challs),
    }


# ---------------------------------------------------------------- scoped delegated assessment

def _lineage_root_of(rid, recs):
    """Walk `lineage` pointers to the root entity id (None on cycle or missing parent)."""
    cur, seen = rid, set()
    while cur in recs and cur not in seen:
        seen.add(cur)
        p = recs[cur].get("lineage")
        if p is None:
            return cur
        cur = p
    return None


def _guard_roles_for_version(target_rec, schemas):
    """Roles that matter for attesting or challenging `target_rec` under counted `schemas` (Warrant 3 guard shape)."""
    if target_rec["kind"] == "schema":
        return {E.SCHEMA_AUTHOR}
    s = schemas.get(target_rec["schema"])
    if not s:
        return set()
    gd = target_rec.get("guard") or s["states"].get(target_rec["body"].get("state"))
    if isinstance(gd, dict):
        return set(gd.get("roles", []))
    return set()


class _ScopedView(E.View):
    """`E.View` with exact per-record delegated role binding and root-principal quorum deduplication.

    Prevents both cross-grant role bleed (a delegate holding distinct role subsets on distinct grants never
    combines them on one target) and Sybil quorum inflation (a root principal and any number of its delegates
    count at most once toward a guard's quorum and never accept a version anchored to that same principal)."""

    def __init__(self, snap, trust, profile, as_of, delegated):
        self._delegated = delegated
        super().__init__(snap, trust, profile, as_of)

    def _principal(self, rid):
        info = self._delegated.get(rid)
        return info["root_issuer"] if info is not None else self.recs[rid]["actor"]

    def _record_holds(self, rid, *roles):
        info = self._delegated.get(rid)
        if info is not None:
            return any(x in info["roles"] for x in roles)
        return self.holds(self.recs[rid]["actor"], *roles)

    def _attested(self):
        part, closing = {}, {}
        for v in sorted(self.root_of):
            r, g = self.recs[v], self.recs[v]["guard"]
            acc, waiting = [], []
            if g is not None:
                v_principal = self._principal(v)
                by_principal = {}
                for a in self.attests.get(v, []):
                    ap = self._principal(a)
                    if ap == v_principal or not self._record_holds(a, *g["roles"]):
                        continue
                    if not all(self.recs[a]["body"].get(k, object()) == x for k, x in g["match"].items()):
                        continue
                    # Deterministic first actor per distinct root principal (No-Sybil-Inflation theorem)
                    by_principal.setdefault(ap, self.recs[a]["actor"])
                acc = sorted(by_principal.values())
                if len(acc) < g["quorum"]:
                    waiting.append(f"{g['quorum'] - len(acc)} attest(s) by {', '.join(g['roles'])} matching {C.canon(g['match']).decode()}")
            part[v] = (acc, waiting)
            if r["body"].get("state") in self.schema_of(v).get("closed", []):
                closing[v] = self.requires(v)
        return part, closing

    def challenge(self, c):
        r = self.recs[c]
        x = r["body"]["target"]
        t = self.recs.get(x)
        replays = [[self.recs[a]["body"].get("on"), self.recs[a]["body"].get("verdict"), self.recs[a]["actor"]]
                   for a in self.attests.get(c, []) if self._record_holds(a, "replayer")
                   and self.recs[a]["body"].get("verdict") in E.REPLAY]
        why = None
        if t is not None and self._principal(c) == self._principal(x):
            why = "its target's actor"
        elif t is not None and t["guard"] and self._record_holds(c, *t["guard"]["roles"]):
            why = "holds a role of its target's guard"
        elif self._record_holds(c, "challenger"):
            why = "holds the challenger role"
        elif any(on == x and v == "reproduces" for on, v, _ in replays):
            why = "reproduced by a replayer"
        stands = why is not None and t is not None
        if stands and x in self.root_of:
            lin = self.lineages[self.root_of[x]]
            eff = self.effective(self.root_of[x])
            stands = eff is None or (x in lin["path"] and lin["path"].index(eff) <= lin["path"].index(x))
        return {"target": x, "counted": why is not None, "why": why or "thesis: its actor's challenge does not count here",
                "replays": sorted(replays, key=lambda z: (str(z[0]), str(z[1]), z[2])), "stands": stands}


def _record_matches_grant(r, rid, grant, grants_all, known_recs, schemas, delegated_root_of):
    """Check whether delegated record `r` is within `grant`'s effective scope and anti-laundering rules.

    Returns `(True, None)` or `(False, refusal_code)`."""
    eff = grant["effective"]
    if r["kind"] not in eff["kinds"]:
        return False, "DELEGATION_OUT_OF_SCOPE"
    if not (eff["not_before"] <= r["at"] <= eff["not_after"]):
        return False, "DELEGATION_OUTSIDE_WINDOW"

    if r["kind"] == "entity":
        if eff["schemas"] is not None and r["schema"] not in eff["schemas"]:
            return False, "DELEGATION_OUT_OF_SCOPE"
        lroot = rid if r["lineage"] is None else _lineage_root_of(r["lineage"], known_recs)
        if r["lineage"] is not None and lroot is None:
            return False, "DELEGATION_UNKNOWN_TARGET"
        if eff["lineages"] is not None and lroot not in eff["lineages"]:
            return False, "DELEGATION_OUT_OF_SCOPE"
        # If succeeding an entity whose schema restricts successors by role, verify grant holds a permitted role
        if r["lineage"] is not None:
            s = schemas.get(r["schema"])
            if s:
                allowed_roles = s.get("successors", {}).get(r["body"].get("state"))
                if allowed_roles is not None and not (set(eff["roles"]) & set(allowed_roles)):
                    return False, "DELEGATION_OUT_OF_SCOPE"
        return True, None

    if r["kind"] in ("attest", "challenge"):
        target = (r.get("body") or {}).get("target")
        if not S.hex64(target) or target not in known_recs:
            return False, "DELEGATION_UNKNOWN_TARGET"
        t_rec = known_recs[target]
        if eff["schemas"] is not None and t_rec.get("schema") not in eff["schemas"]:
            return False, "DELEGATION_OUT_OF_SCOPE"
        t_root = _lineage_root_of(target, known_recs) if t_rec["kind"] == "entity" else target
        if eff["lineages"] is not None and t_root not in eff["lineages"]:
            return False, "DELEGATION_OUT_OF_SCOPE"

        # Anti-laundering: a delegate cannot attest/accept a version authored by its root issuer,
        # any ancestor issuer in its delegation chain, or another delegate anchored to the same root issuer.
        if r["kind"] == "attest":
            ancestors = {grants_all[gid]["issuer"] for gid in grant["chain"]} | {grant["delegate"], grant["root_issuer"]}
            if t_rec["actor"] in ancestors:
                return False, "DELEGATION_SELF_ACCEPT"
            t_delegated_root = delegated_root_of.get(target)
            if t_delegated_root is not None and t_delegated_root == grant["root_issuer"]:
                return False, "DELEGATION_SELF_ACCEPT"
            # Cross-grant role isolation: grant must hold at least one role relevant to target's guard (when guarded)
            g_roles = _guard_roles_for_version(t_rec, schemas)
            if g_roles and not (set(eff["roles"]) & g_roles):
                return False, "DELEGATION_OUT_OF_SCOPE"
        else:
            # Challenge counts only if grant carries `challenger` or a guard role on the target
            relevant = {"challenger"} | _guard_roles_for_version(t_rec, schemas)
            if not (set(eff["roles"]) & relevant):
                return False, "DELEGATION_OUT_OF_SCOPE"
        return True, None

    return False, "DELEGATION_OUT_OF_SCOPE"


def _diff_reports(before, after, admitted_by_lineage):
    out = []
    for L in sorted(set(before["lineages"]) | set(after["lineages"])):
        a, b = before["lineages"].get(L), after["lineages"].get(L)
        was = [a["state"], a["reliance"]] if a else None
        now = [b["state"], b["reliance"]] if b else None
        if was != now:
            out.append({
                "lineage": L,
                "schema": (b or a)["schema"],
                "from": was,
                "to": now,
                "via_grants": sorted(admitted_by_lineage.get(L, ())),
            })
    return out


def assess_delegated(snap, trust, profile, as_of=None):
    """Assess `snap` under static `(trust, profile)` extended with verified, scoped `grant@1` delegations.

    Returns canonical dict:
      `as_of`, `grants`, `admitted`, `refused`, `changes`, `provenance`, `static_report`, `delegated_report`."""
    base_view = E.View(snap, trust, profile, as_of)
    base_rep = base_view.report()
    eff_as_of = base_view.as_of
    grants = resolve_grants(snap, trust, profile, eff_as_of)
    from . import pact as P                       # here, not at the top: pact imports this module
    for gid in P.frozen_grants(snap, trust, profile, eff_as_of, grants):
        grants[gid] = dict(grants[gid], status="ESCROW_FROZEN")   # a frozen grant admits nothing (Codex F2)

    # Index ALL grants (active and inactive) by (delegate, delegate_key)
    active_by_pair = {}
    all_by_pair = {}
    for g in grants.values():
        pair = (g["delegate"], g["delegate_key"])
        if g["delegate"] and g["delegate_key"]:
            all_by_pair.setdefault(pair, []).append(g)
            if g["status"] == "ACTIVE":
                active_by_pair.setdefault(pair, []).append(g)

    # Identify candidate delegated records: lines not already SIGNED under static trust (and not grant@1 themselves)
    known_recs = dict(base_view.recs)
    delegated_root_of = {}  # rid -> root_issuer of authorizing grant
    admitted = {}           # rid -> {record_id, actor, kind, grant, chain, root_issuer, roles}
    refused = {}            # rid -> {record_id, actor, kind, code, grants_tried}
    admitted_lines = set()

    # Pre-populate (target, root_principal) pairs already attested by static actors (for No-Sybil-Inflation refusal)
    attested_principals = set()
    for _rid, _rec in base_view.recs.items():
        if _rec["kind"] == "attest":
            _t = (_rec.get("body") or {}).get("target")
            if S.hex64(_t):
                attested_principals.add((_t, _rec["actor"]))

    # Pass 1: delegated entities first (so Pass 2 attests/challenges can target newly admitted entities)
    # Pass 2: delegated attests and challenges
    for pass_kinds in (("entity",), ("attest", "challenge")):
        for rid, envs in sorted(snap.lines.items()):
            if rid in base_view.recs or rid in admitted or rid in refused:
                continue
            r = envs[0]["record"]
            if r["at"] > eff_as_of or r["kind"] not in pass_kinds:
                continue
            if r["kind"] == "entity" and r["schema"] == SCHEMA_NAME:
                continue
            # Match signature against any known delegate_key for r["actor"]
            matched_active, matched_inactive = [], []
            for (d_actor, d_key), gs in sorted(all_by_pair.items()):
                if d_actor != r["actor"]:
                    continue
                if _verifies_any(rid, envs, [d_key]) is not None:
                    for g in gs:
                        (matched_active if g["status"] == "ACTIVE" else matched_inactive).append(g)
            if not matched_active and not matched_inactive:
                continue
            if not matched_active:
                refused[rid] = {
                    "id": rid,
                    "actor": r["actor"],
                    "kind": r["kind"],
                    "code": "DELEGATION_NOT_ACTIVE",
                    "grants_tried": [g["id"] for g in matched_inactive],
                }
                continue

            # Try each active grant; collect matching ones (or sharpest refusal)
            chosen = None
            reasons = []
            for g in matched_active:
                ok, why = _record_matches_grant(r, rid, g, grants, known_recs, base_view.schemas, delegated_root_of)
                if ok and r["kind"] == "attest":
                    t = r["body"]["target"]
                    if (t, g["root_issuer"]) in attested_principals:
                        ok, why = False, "DELEGATION_QUORUM_INFLATION"
                if ok:
                    chosen = g
                    break
                reasons.append(why)

            if chosen is not None:
                admitted[rid] = {
                    "id": rid,
                    "actor": r["actor"],
                    "kind": r["kind"],
                    "grant": chosen["id"],
                    "chain": list(chosen["chain"]),
                    "root_issuer": chosen["root_issuer"],
                    "roles": list(chosen["effective"]["roles"]),
                }
                known_recs[rid] = r
                delegated_root_of[rid] = chosen["root_issuer"]
                if r["kind"] == "attest":
                    attested_principals.add((r["body"]["target"], chosen["root_issuer"]))
                for e in envs:
                    admitted_lines.add(C.canon(e) + b"\n")
            else:
                # Deterministic refusal priority: self-accept > quorum inflation > window > unknown target > out of scope
                prio = ("DELEGATION_SELF_ACCEPT", "DELEGATION_QUORUM_INFLATION", "DELEGATION_OUTSIDE_WINDOW",
                        "DELEGATION_UNKNOWN_TARGET", "DELEGATION_OUT_OF_SCOPE")
                code = next((p for p in prio if p in reasons), reasons[0])
                refused[rid] = {
                    "id": rid,
                    "actor": r["actor"],
                    "kind": r["kind"],
                    "code": code,
                    "grants_tried": [g["id"] for g in matched_active],
                }

    # Build augmented snapshot keeping ONLY static lines + scope-verified delegated lines (no refused delegate lines!)
    refused_ids = set(refused)
    aug_lines = [C.canon(e) + b"\n" for rid, envs in snap.lines.items() if rid not in refused_ids for e in envs]
    aug_snap = Snapshot(sorted(set(aug_lines) | admitted_lines, key=_line_id), snap.blobs)

    aug_keys = {a: list(ks) for a, ks in trust["keys"].items()}
    aug_roles = {role: list(actors) for role, actors in profile["roles"].items()}
    for info in admitted.values():
        g = grants[info["grant"]]
        d_actor, d_key = g["delegate"], g["delegate_key"]
        aug_keys[d_actor] = sorted(set(aug_keys.get(d_actor, [])) | {d_key})
        for role in g["effective"]["roles"]:
            aug_roles[role] = sorted(set(aug_roles.get(role, [])) | {d_actor})
    aug_trust = {"warrant": "trust/3", "keys": aug_keys}
    aug_profile = dict(profile, roles=aug_roles)
    del_view = _ScopedView(aug_snap, aug_trust, aug_profile, eff_as_of, admitted)
    del_rep = del_view.report()

    # Track which grants contributed to which lineage
    admitted_by_lineage = {}
    for rid, info in admitted.items():
        r = known_recs[rid]
        if r["kind"] == "entity":
            L = _lineage_root_of(rid, known_recs)
        else:
            t = r["body"]["target"]
            L = _lineage_root_of(t, known_recs) if t in known_recs and known_recs[t]["kind"] == "entity" else t
        if L:
            admitted_by_lineage.setdefault(L, set()).add(info["grant"])

    changes = _diff_reports(base_rep, del_rep, admitted_by_lineage)
    provenance = {
        rid: {"actor": info["actor"], "root_issuer": info["root_issuer"], "grant": info["grant"], "chain": info["chain"]}
        for rid, info in sorted(admitted.items())
    }
    return {
        "warrant": "delegation/1",
        "as_of": eff_as_of,
        "grants": grants,
        "admitted": [admitted[k] for k in sorted(admitted)],
        "refused": [refused[k] for k in sorted(refused)],
        "changes": changes,
        "provenance": provenance,
        "static_report": base_rep,
        "delegated_report": del_rep,
    }


# ---------------------------------------------------------------- CLI (`warrant delegate ...`)

def run(argv):
    """CLI entrypoint (`python -m warrant.delegate` / `warrant delegate`):
      schema  --actor A --key K                     file the `grant@1` schema record
      grant   --actor A --key K --to D --pub HEX --role R ... --kind K ... --not-before N --not-after N
              [--depth D] [--schema S ...] [--lineage L ...] [--parent G] [--reason TEXT]
      revoke  --actor A --key K GRANT_ROOT [--reason TEXT]
      grants  [--as-of N] [--json]                  resolve all `grant@1` lineages in the store
      assess  [--as-of N] [--json]                  scoped assessment with active delegations and diff vs static"""
    import argparse
    import json
    import sys
    import time

    from .repo import Failed, Repo, dump, env_root, load_key

    ap = argparse.ArgumentParser(prog="warrant delegate", description="Attenuating capability delegation (grant@1)")
    ap.add_argument("--root", default=env_root(argv), help="repository root")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_s = sub.add_parser("schema", help="file the grant@1 schema record")
    p_s.add_argument("--actor", required=True)
    p_s.add_argument("--key", required=True)

    p_g = sub.add_parser("grant", help="file an active grant@1 delegation record")
    p_g.add_argument("--actor", required=True)
    p_g.add_argument("--key", required=True)
    p_g.add_argument("--to", required=True, dest="delegate")
    p_g.add_argument("--pub", required=True, dest="delegate_key")
    p_g.add_argument("--role", action="append", required=True, dest="roles")
    p_g.add_argument("--kind", action="append", required=True, dest="kinds", choices=KINDS)
    p_g.add_argument("--schema", action="append", dest="schemas")
    p_g.add_argument("--lineage", action="append", dest="lineages")
    p_g.add_argument("--not-before", type=int, required=True)
    p_g.add_argument("--not-after", type=int, required=True)
    p_g.add_argument("--depth", type=int, default=0)
    p_g.add_argument("--parent")
    p_g.add_argument("--reason")
    p_g.add_argument("--at", type=int)

    p_r = sub.add_parser("revoke", help="revoke a grant@1 lineage (issuer or any ancestor issuer)")
    p_r.add_argument("grant_root")
    p_r.add_argument("--actor", required=True)
    p_r.add_argument("--key", required=True)
    p_r.add_argument("--reason")
    p_r.add_argument("--at", type=int)

    for name in ("grants", "assess"):
        p = sub.add_parser(name, help="resolve grants" if name == "grants" else "assess store with delegations")
        p.add_argument("--as-of", type=int)
        p.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    repo = Repo(a.root)
    trust, profile, _ = repo.config()
    snap = repo.store.snapshot()

    if a.cmd == "schema":
        key = load_key(a.key)
        rec = R.record("schema", a.actor, int(time.time()), SCHEMA, None, refs=[])
        filed = repo.file(a.actor, key, [rec])[0]
        dump({"schema": filed, "name": SCHEMA_NAME})
        return 0

    if a.cmd == "grant":
        key = load_key(a.key)
        at = a.at if a.at is not None else int(time.time())
        rec = grant_record(
            a.actor, a.delegate, a.delegate_key, a.roles, a.kinds,
            a.not_before, a.not_after, max_depth=a.depth,
            schemas=a.schemas, lineages=a.lineages, parent=a.parent, at=at, reason=a.reason,
        )
        filed = repo.file(a.actor, key, [rec])[0]
        dump({"grant": filed, "delegate": a.delegate, "delegate_key": a.delegate_key})
        return 0

    if a.cmd == "revoke":
        key = load_key(a.key)
        at = a.at if a.at is not None else int(time.time())
        gs = resolve_grants(snap, trust, profile)
        if a.grant_root not in gs:
            raise Failed("GRANT_UNKNOWN", f"{a.grant_root[:12]} is not a grant@1 lineage of this store")
        g = gs[a.grant_root]
        leaf = g["versions"][-1]
        root_rec = snap.lines[a.grant_root][0]["record"]
        rec = revoke_from(a.actor, root_rec, leaf, at=at, reason=a.reason)
        filed = repo.file(a.actor, key, [rec])[0]
        dump({"revoked": a.grant_root, "version": filed, "by": a.actor})
        return 0

    if a.cmd == "grants":
        out = resolve_grants(snap, trust, profile, a.as_of)
        if a.json:
            dump(out)
        else:
            if not out:
                sys.stdout.write("no grant@1 records\n")
            for gid, g in out.items():
                sys.stdout.write(
                    f"{gid[:12]} {g['status']:<16} {g['issuer']} -> {g['delegate']} "
                    f"(root {g['root_issuer']}, depth {g['depth']})"
                    + (f" [{g['reason']}]" if g["reason"] else "") + "\n"
                )
        return 0

    res = assess_delegated(snap, trust, profile, a.as_of)
    summary = {k: res[k] for k in ("warrant", "as_of", "grants", "admitted", "refused", "changes", "provenance")}
    if a.json:
        print(json.dumps(summary, indent=1, sort_keys=True))
    else:
        sys.stdout.write(
            f"as_of {summary['as_of']} · grants {len(summary['grants'])} "
            f"(active {sum(1 for g in summary['grants'].values() if g['status'] == 'ACTIVE')}) · "
            f"admitted {len(summary['admitted'])} · refused {len(summary['refused'])} · "
            f"changes {len(summary['changes'])}\n"
        )
        for ch in summary["changes"]:
            sys.stdout.write(f"  {ch['lineage'][:12]} ({ch['schema']}): {ch['from']} -> {ch['to']}\n")
    return 0


if __name__ == "__main__":
    from .repo import main as _repo_main
    import sys as _sys
    _sys.exit(_repo_main(run, _sys.argv[1:]))
