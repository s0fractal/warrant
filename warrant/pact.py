"""Bilateral/multilateral cryptographic pacts and computed-loss composition (`pact@1`, docs/PACT.md).

In Warrant 3, `claim`, `obligation@1` and `grant@1` are unilateral or hierarchical acts. Two peers
(agent-agent or agent-human) that do not share a master need a mutual, fail-closed commitment protocol
and a mechanical way to compose multi-agent contracts without silently dropping guarantees.

This module adds two composable, pure-Python mechanisms over Warrant 3's existing four-kind envelope
(`schema`, `entity`, `attest`, `challenge`) with zero changes to the core engine:

  1. Bilateral / multilateral pacts (`pact@1`):
     - Unanimous activation: a proposal binds nobody until every named party signs `pact/accept`
       referencing the exact proposal digest before `expires_at` with no prior withdrawal.
     - No unilateral escape after ratification: `pact/withdraw` is refused once unanimous activation holds.
     - Complete fulfillment & equivocation detection: `pact/fulfill` must cover every label in the party's
       `gives` set; signing two distinct `evidence_digest`s for the same pact triggers `EQUIVOCATION`
       with both conflicting record ids captured as cryptographic proof and transitions the pact to `BREACHED`.
     - Deterministic breach & expiry: an `ACTIVE` pact passing `expires_at` without full fulfillment transitions
       to `BREACHED`, attributing exact `defaulters` and `honest_parties`; an optional neutral `arbiter`
       (never a member of `parties`) may attest `pact/settle` or challenge `pact/breach`.
     - Escrow binding with `grant@1`: grants named in `escrow_grants` are executable only while the binding
       pact holds the required state (`ACTIVE` or `SETTLED`) and freeze immediately on breach/withdrawal/expiry.

  2. Computed-loss composition algebra (default-deny frame law):
     - Silence about a prior guarantee is a loss, never preservation:
           L_{12} >= L_1 U L_2 U ((G_1 U P_1) \\ (G_2 U (F_2 & avail_1)))
     - Every silently dropped guarantee is recorded mechanically in `computed_losses` and `silent_drops`
       with exact step provenance (`loss_events`); later re-establishment never erases the historical gap.
"""
from dataclasses import dataclass

from . import delegate as D
from . import jcs as C
from . import keys as K
from . import records as R
from . import shapes as S
from .store import Snapshot

SCHEMA_NAME = "pact@1"
MAX_PARTIES = 64
MAX_LABELS = 128
ESCROW_MODES = ("active", "settled")
STATUSES = (
    "INVALID",
    "PROPOSED",
    "WITHDRAWN",
    "EXPIRED",
    "ACTIVE",
    "SETTLED",
    "BREACHED",
)
SCHEMA = {
    "name": SCHEMA_NAME,
    "fields": {
        "state": "str",
        "parties": "strs",
        "commitments": "dict",
        "expires_at": "int",
        "purpose": "str",
        "arbiter": "str?",
        "escrow_grants": "refs?",
        "escrow_mode": "str?",
        "boundary": "strs?",
    },
    "states": {"proposed": None},
    "closed": [],
    "successors": {},
}


# ---------------------------------------------------------------- helpers


def _canon_labels(raw, name, allow_empty=True):
    """Validate and canonicalize a list of non-empty guarantee/boundary label strings."""
    if not isinstance(raw, list):
        return None, f"{name} must be a list of strings"
    if len(raw) > MAX_LABELS:
        return None, f"{name} exceeds limit {MAX_LABELS}"
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, str) or not item or len(item) > 200:
            return None, f"{name} entries must be non-empty strings <= 200 chars"
        if item != item.strip():
            return None, f"{name} entries must not have leading/trailing whitespace"
        if item in seen:
            return None, f"{name} contains duplicate entry {item!r}"
        seen.add(item)
        out.append(item)
    if not allow_empty and not out:
        return None, f"{name} must be non-empty"
    return tuple(sorted(out)), None


def _sig_ok(rid, env, trust):
    """Verify Warrant 3 Ed25519 signature against `trust.keys[actor]` (fail-closed)."""
    if not isinstance(env, dict):
        return False
    rec = env.get("record")
    sig = env.get("sig")
    if not isinstance(rec, dict) or not isinstance(sig, dict):
        return False
    if not (S.hex64(sig.get("key")) and S.hex128(sig.get("ed25519"))):
        return False
    actor = rec.get("actor")
    if not S.is_actor(actor):
        return False
    keys = (trust.get("keys") or {}).get(actor, [])
    if not keys:
        return False
    for pub in keys:
        if S.hex64(pub) and R.verifies(rid, sig, pub):
            return True
    return False


def _parse_commitment(raw, party):
    """Parse one party's commitment dict, returning (parsed, error)."""
    if not isinstance(raw, dict):
        return None, f"commitment for {party!r} must be an object"
    allowed = {"requires", "gives", "preserves", "declared_losses", "deliverable"}
    extra = sorted(set(raw) - allowed)
    if extra:
        return None, f"commitment for {party!r} has unknown fields {extra}"
    req, err = _canon_labels(raw.get("requires", []), f"{party}.requires", allow_empty=True)
    if err:
        return None, err
    gives, err = _canon_labels(raw.get("gives", []), f"{party}.gives", allow_empty=False)
    if err:
        return None, err
    pres, err = _canon_labels(raw.get("preserves", []), f"{party}.preserves", allow_empty=True)
    if err:
        return None, err
    dloss, err = _canon_labels(raw.get("declared_losses", []), f"{party}.declared_losses", allow_empty=True)
    if err:
        return None, err
    deliv = raw.get("deliverable")
    if deliv is not None and (not isinstance(deliv, str) or len(deliv) > 500):
        return None, f"{party}.deliverable must be a string <= 500 chars"
    return {
        "requires": req,
        "gives": gives,
        "preserves": pres,
        "declared_losses": dloss,
        "deliverable": deliv,
    }, None


def parse_proposal(rec):
    """Parse and validate a `pact@1` proposal entity record, returning (spec, error)."""
    if not isinstance(rec, dict) or rec.get("kind") != "entity" or rec.get("schema") != SCHEMA_NAME:
        return None, "NOT_PACT_PROPOSAL"
    if rec.get("lineage") is not None or rec.get("prev") is not None:
        return None, "PROPOSAL_MUST_BE_ROOT"
    body = rec.get("body")
    if not isinstance(body, dict):
        return None, "BAD_BODY"
    if body.get("state") != "proposed":
        return None, "BAD_STATE"
    parties_raw = body.get("parties")
    if not isinstance(parties_raw, list) or len(parties_raw) < 2 or len(parties_raw) > MAX_PARTIES:
        return None, "BAD_PARTIES_COUNT"
    parties = []
    seen = set()
    for p in parties_raw:
        if not S.is_actor(p):
            return None, "BAD_PARTY_ACTOR"
        if p in seen:
            return None, "DUPLICATE_PARTY"
        seen.add(p)
        parties.append(p)
    parties_sorted = tuple(sorted(parties))

    expires_at = body.get("expires_at")
    if not (R.is_int(expires_at) and expires_at >= 0):
        return None, "BAD_EXPIRES_AT"

    purpose = body.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 500:
        return None, "BAD_PURPOSE"

    arbiter = body.get("arbiter")
    if arbiter is not None:
        if not S.is_actor(arbiter):
            return None, "BAD_ARBITER"
        if arbiter in seen:
            return None, "ARBITER_IS_PARTY"

    escrow_raw = body.get("escrow_grants", [])
    if not isinstance(escrow_raw, list) or len(escrow_raw) > MAX_LABELS:
        return None, "BAD_ESCROW_GRANTS"
    escrow = []
    escrow_seen = set()
    for gid in escrow_raw:
        if not S.hex64(gid) or gid in escrow_seen:
            return None, "BAD_ESCROW_GRANT_ID"
        escrow_seen.add(gid)
        escrow.append(gid)
    escrow_mode = body.get("escrow_mode", "active")
    if escrow_mode not in ESCROW_MODES:
        return None, "BAD_ESCROW_MODE"

    boundary_raw = body.get("boundary", ["default"])
    boundary, berr = _canon_labels(boundary_raw, "boundary", allow_empty=False)
    if berr:
        return None, "BAD_BOUNDARY"

    comms_raw = body.get("commitments")
    if not isinstance(comms_raw, dict) or set(comms_raw) != seen:
        return None, "COMMITMENTS_PARTY_MISMATCH"
    commitments = {}
    for p in parties_sorted:
        parsed, cerr = _parse_commitment(comms_raw[p], p)
        if cerr:
            return None, f"BAD_COMMITMENT:{cerr}"
        commitments[p] = parsed

    return {
        "parties": parties_sorted,
        "commitments": commitments,
        "expires_at": expires_at,
        "purpose": purpose,
        "arbiter": arbiter,
        "escrow_grants": tuple(sorted(escrow)),
        "escrow_mode": escrow_mode,
        "boundary": boundary,
    }, None


# ---------------------------------------------------------------- record builders


def _sign_env(rec, seed_or_key):
    """Sign a Warrant 3 record with a `warrant.keys.Key` or 64-hex seed string, returning the envelope dict."""
    key = seed_or_key if isinstance(seed_or_key, K.Key) else K.Key.from_seed_hex(seed_or_key)
    _, raw = R.line(rec, key)
    return C.loads(raw.rstrip(b"\n"))


def make_proposal(actor, seed_hex, *, parties, commitments, expires_at, purpose,
                  arbiter=None, escrow_grants=None, escrow_mode="active",
                  boundary=None, at=0):
    """Build and sign a `pact@1` proposal entity envelope."""
    body = {
        "state": "proposed",
        "parties": sorted(parties),
        "commitments": commitments,
        "expires_at": expires_at,
        "purpose": purpose,
    }
    if arbiter is not None:
        body["arbiter"] = arbiter
    if escrow_grants:
        body["escrow_grants"] = sorted(escrow_grants)
        body["escrow_mode"] = escrow_mode
    if boundary is not None:
        body["boundary"] = sorted(boundary)
    rec = R.record("entity", actor, at, body, schema=SCHEMA_NAME)
    return _sign_env(rec, seed_hex)


def make_accept(actor, seed_hex, pact_id, *, at=0, pact_digest=None):
    """Build and sign a `pact/accept` attest envelope binding `pact_id`."""
    body = {
        "target": pact_id,
        "verdict": "pact/accept",
        "pact_digest": pact_digest if pact_digest is not None else pact_id,
    }
    rec = R.record("attest", actor, at, body, refs=[pact_id])
    return _sign_env(rec, seed_hex)


def make_withdraw(actor, seed_hex, pact_id, *, at=0, reason="withdrawn"):
    """Build and sign a `pact/withdraw` attest envelope (valid only before activation)."""
    body = {
        "target": pact_id,
        "verdict": "pact/withdraw",
        "reason": reason,
    }
    rec = R.record("attest", actor, at, body, refs=[pact_id])
    return _sign_env(rec, seed_hex)


def make_fulfill(actor, seed_hex, pact_id, *, evidence_digest, delivered, at=0):
    """Build and sign a `pact/fulfill` attest envelope with verifiable evidence digest."""
    body = {
        "target": pact_id,
        "verdict": "pact/fulfill",
        "evidence_digest": evidence_digest,
        "delivered": sorted(delivered),
    }
    rec = R.record("attest", actor, at, body, refs=[pact_id])
    return _sign_env(rec, seed_hex)


def make_settle(arbiter, seed_hex, pact_id, *, at=0, note="verified"):
    """Build and sign an arbiter `pact/settle` attest envelope."""
    body = {
        "target": pact_id,
        "verdict": "pact/settle",
        "note": note,
    }
    rec = R.record("attest", arbiter, at, body, refs=[pact_id])
    return _sign_env(rec, seed_hex)


def make_breach(actor, seed_hex, pact_id, *, defaulter, evidence_digest, reason, at=0):
    """Build and sign a `pact/breach` challenge envelope (admitted only from designated arbiter)."""
    body = {
        "target": pact_id,
        "verdict": "pact/breach",
        "defaulter": defaulter,
        "evidence_digest": evidence_digest,
        "reason": reason,
    }
    rec = R.record("challenge", actor, at, body, refs=[pact_id])
    return _sign_env(rec, seed_hex)


# ---------------------------------------------------------------- deterministic pact reducer


def _extract_verified_records(snap, trust):
    """Return (valid_by_id, raw_by_id) from a Snapshot, keeping only signature-verified records."""
    valid = {}
    all_recs = {}
    for rid, envs in snap.lines.items():
        for env in envs:
            rec = env.get("record")
            if isinstance(rec, dict):
                all_recs[rid] = rec
            if _sig_ok(rid, env, trust):
                valid[rid] = rec
    return valid, all_recs


def resolve_pacts(snap: Snapshot, trust: dict, as_of: int):
    """Resolve every `pact@1` proposal in `snap` deterministically at timestamp `as_of`.

    Returns a dict keyed by proposal record id, each entry carrying:
      status, reason, parties, accepted, fulfilled, defaulters, honest_parties,
      equivocations, activation_at, expires_at, arbiter, escrow_grants, escrow_mode,
      boundary, commitments, refused_events.
    """
    if not (R.is_int(as_of) and as_of >= 0):
        raise ValueError("as_of must be a non-negative integer")
    valid, all_recs = _extract_verified_records(snap, trust)

    # Index all pact@1 proposal entities (including untrusted/invalid ones so they report INVALID)
    proposals = {}
    for rid, rec in sorted(all_recs.items()):
        if rec.get("kind") == "entity" and rec.get("schema") == SCHEMA_NAME:
            proposals[rid] = rec

    # Index verified responses by target pact_id
    by_target = {pid: [] for pid in proposals}
    for rid, rec in sorted(valid.items()):
        kind = rec.get("kind")
        if kind not in ("attest", "challenge"):
            continue
        body = rec.get("body")
        if not isinstance(body, dict):
            continue
        target = body.get("target")
        if target in by_target:
            by_target[target].append((rid, rec))

    out = {}
    for pid, prec in sorted(proposals.items()):
        if pid not in valid:
            out[pid] = {
                "pact_id": pid,
                "status": "INVALID",
                "reason": "UNTRUSTED_OR_BAD_SIGNATURE",
                "parties": [],
                "accepted": {},
                "fulfilled": {},
                "defaulters": [],
                "honest_parties": [],
                "equivocations": {},
                "activation_at": None,
                "expires_at": None,
                "arbiter": None,
                "escrow_grants": [],
                "escrow_mode": "active",
                "boundary": [],
                "commitments": {},
                "refused_events": [],
            }
            continue

        spec, err = parse_proposal(prec)
        if err:
            out[pid] = {
                "pact_id": pid,
                "status": "INVALID",
                "reason": err,
                "parties": [],
                "accepted": {},
                "fulfilled": {},
                "defaulters": [],
                "honest_parties": [],
                "equivocations": {},
                "activation_at": None,
                "expires_at": None,
                "arbiter": None,
                "escrow_grants": [],
                "escrow_mode": "active",
                "boundary": [],
                "commitments": {},
                "refused_events": [],
            }
            continue

        parties = set(spec["parties"])
        expires_at = spec["expires_at"]
        arbiter = spec["arbiter"]
        refused = []

        # Collect candidate events ordered by (at, rid) for deterministic tie-breaking
        events = sorted(by_target[pid], key=lambda pair: (pair[1].get("at", 0), pair[0]))

        accepts = {}        # party -> (at, rid) earliest valid accept
        withdraws = []      # [(at, rid, party)]
        fulfills = {}       # party -> list of (at, rid, evidence_digest, delivered_tuple)
        arbiter_settles = []
        arbiter_breaches = []

        for rid, rec in events:
            actor = rec.get("actor")
            kind = rec.get("kind")
            body = rec.get("body", {})
            verdict = body.get("verdict")
            at = rec.get("at", 0)
            if not (R.is_int(at) and at >= 0):
                refused.append({"id": rid, "actor": actor, "code": "BAD_AT"})
                continue

            if kind == "attest" and verdict == "pact/accept":
                if actor not in parties:
                    refused.append({"id": rid, "actor": actor, "code": "NOT_A_PARTY"})
                    continue
                if body.get("pact_digest") != pid:
                    refused.append({"id": rid, "actor": actor, "code": "DIGEST_MISMATCH"})
                    continue
                if at > expires_at:
                    refused.append({"id": rid, "actor": actor, "code": "ACCEPT_AFTER_EXPIRY"})
                    continue
                if actor not in accepts:
                    accepts[actor] = (at, rid)

            elif kind == "attest" and verdict == "pact/withdraw":
                if actor not in parties:
                    refused.append({"id": rid, "actor": actor, "code": "NOT_A_PARTY"})
                    continue
                withdraws.append((at, rid, actor))

            elif kind == "attest" and verdict == "pact/fulfill":
                if actor not in parties:
                    refused.append({"id": rid, "actor": actor, "code": "NOT_A_PARTY"})
                    continue
                edig = body.get("evidence_digest")
                if not S.hex64(edig):
                    refused.append({"id": rid, "actor": actor, "code": "BAD_EVIDENCE_DIGEST"})
                    continue
                deliv, derr = _canon_labels(body.get("delivered", []), "delivered", allow_empty=True)
                if derr:
                    refused.append({"id": rid, "actor": actor, "code": "BAD_DELIVERED"})
                    continue
                if at > expires_at:
                    refused.append({"id": rid, "actor": actor, "code": "FULFILL_AFTER_EXPIRY"})
                    continue
                fulfills.setdefault(actor, []).append((at, rid, edig, deliv))

            elif kind == "attest" and verdict == "pact/settle":
                if arbiter is None or actor != arbiter:
                    refused.append({"id": rid, "actor": actor, "code": "NOT_ARBITER"})
                    continue
                arbiter_settles.append((at, rid))

            elif kind == "challenge" and verdict == "pact/breach":
                if arbiter is None or actor != arbiter:
                    refused.append({"id": rid, "actor": actor, "code": "NOT_ARBITER"})
                    continue
                defaulter = body.get("defaulter")
                if defaulter not in parties:
                    refused.append({"id": rid, "actor": actor, "code": "BAD_DEFAULTER"})
                    continue
                edig = body.get("evidence_digest")
                if not S.hex64(edig):
                    refused.append({"id": rid, "actor": actor, "code": "BAD_EVIDENCE_DIGEST"})
                    continue
                arbiter_breaches.append((at, rid, defaulter, edig, body.get("reason", "")))

        # Phase 1: Activation vs Pre-activation Withdrawal
        all_accepted = len(accepts) == len(parties)
        raw_activation_at = max(a[0] for a in accepts.values()) if all_accepted else None

        # A withdrawal is valid iff it occurred before unanimous activation (or if unanimous activation never happened)
        valid_withdraw = None
        for w_at, w_rid, w_actor in withdraws:
            if not all_accepted or w_at < raw_activation_at:
                valid_withdraw = (w_at, w_rid, w_actor)
                break
            else:
                refused.append({"id": w_rid, "actor": w_actor, "code": "ALREADY_ACTIVE"})

        if valid_withdraw is not None:
            status = "WITHDRAWN"
            reason = f"WITHDRAWN_BY:{valid_withdraw[2]}"
            activation_at = None
            fulfilled_map = {}
            equivocations = {}
            defaulters = []
            honest_parties = []
        elif not all_accepted:
            activation_at = None
            fulfilled_map = {}
            equivocations = {}
            defaulters = []
            honest_parties = []
            if as_of > expires_at:
                status = "EXPIRED"
                reason = "UNACCEPTED_EXPIRED"
            else:
                status = "PROPOSED"
                reason = "AWAITING_ACCEPTANCE"
        else:
            # Pact reached unanimous activation!
            activation_at = raw_activation_at
            fulfilled_map = {}
            equivocations = {}

            for party in spec["parties"]:
                f_list = fulfills.get(party, [])
                if not f_list:
                    continue
                # Check equivocation across ALL signed fulfillments by this party (distinct evidence_digests)
                seen_digests = {}
                for f_at, f_rid, edig, deliv in f_list:
                    if edig not in seen_digests:
                        seen_digests[edig] = f_rid
                if len(seen_digests) > 1:
                    equivocations[party] = sorted(seen_digests.values())
                    continue

                # Single consistent evidence_digest; verify timing & completeness of gives
                req_gives = set(spec["commitments"][party]["gives"])
                admitted = None
                for f_at, f_rid, edig, deliv in f_list:
                    if f_at < activation_at:
                        refused.append({"id": f_rid, "actor": party, "code": "FULFILL_BEFORE_ACTIVATION"})
                        continue
                    missing = sorted(req_gives - set(deliv))
                    if missing:
                        refused.append({"id": f_rid, "actor": party, "code": "INCOMPLETE_FULFILLMENT", "missing": missing})
                        continue
                    admitted = {"id": f_rid, "at": f_at, "evidence_digest": edig, "delivered": list(deliv)}
                    break
                if admitted is not None:
                    fulfilled_map[party] = admitted

            # Phase 2: Breach / Settlement / Active resolution
            if equivocations:
                status = "BREACHED"
                reason = "EQUIVOCATION"
                defaulters = sorted(equivocations)
                honest_parties = sorted(p for p in fulfilled_map if p not in equivocations)
            elif arbiter_breaches:
                status = "BREACHED"
                reason = "ARBITER_BREACH"
                defaulters = sorted({b[2] for b in arbiter_breaches})
                honest_parties = sorted(p for p in spec["parties"] if p not in defaulters)
            else:
                all_fulfilled = len(fulfilled_map) == len(parties)
                arbiter_ok = (arbiter is None) or (len(arbiter_settles) > 0)
                if all_fulfilled and arbiter_ok:
                    status = "SETTLED"
                    reason = "SETTLED"
                    defaulters = []
                    honest_parties = list(spec["parties"])
                elif as_of > expires_at:
                    status = "BREACHED"
                    reason = "EXPIRED_DEFAULT" if not all_fulfilled else "ARBITER_SETTLE_TIMEOUT"
                    defaulters = sorted(p for p in spec["parties"] if p not in fulfilled_map)
                    honest_parties = sorted(fulfilled_map)
                else:
                    status = "ACTIVE"
                    reason = "AWAITING_ARBITER_SETTLE" if all_fulfilled else "AWAITING_FULFILLMENT"
                    defaulters = []
                    honest_parties = sorted(fulfilled_map)

        out[pid] = {
            "pact_id": pid,
            "status": status,
            "reason": reason,
            "parties": list(spec["parties"]),
            "accepted": {p: {"id": rid, "at": at} for p, (at, rid) in sorted(accepts.items())},
            "fulfilled": fulfilled_map,
            "defaulters": defaulters,
            "honest_parties": honest_parties,
            "equivocations": equivocations,
            "activation_at": activation_at,
            "expires_at": expires_at,
            "arbiter": arbiter,
            "escrow_grants": list(spec["escrow_grants"]),
            "escrow_mode": spec["escrow_mode"],
            "boundary": list(spec["boundary"]),
            "commitments": {
                p: {
                    "requires": list(c["requires"]),
                    "gives": list(c["gives"]),
                    "preserves": list(c["preserves"]),
                    "declared_losses": list(c["declared_losses"]),
                    "deliverable": c["deliverable"],
                }
                for p, c in spec["commitments"].items()
            },
            "refused_events": refused,
        }
    return out


# ---------------------------------------------------------------- escrow bridge with grant@1


def resolve_escrow(snap: Snapshot, trust: dict, profile: dict, as_of: int):
    """Resolve every escrowed `grant@1` bound to any `pact@1` in `snap`.

    Fail-closed: a grant bound to one or more pacts is `escrow_allowed == True` iff the grant itself
    resolves ACTIVE under `warrant.delegate.resolve_grants` AND every binding pact satisfies its
    `escrow_mode` (`ACTIVE` for mode `active`, `SETTLED` for mode `settled`).
    """
    grants = D.resolve_grants(snap, trust, profile, as_of)
    pacts = resolve_pacts(snap, trust, as_of)

    bindings = {}  # grant_id -> list of (pact_id, pact_entry)
    for pid, p in sorted(pacts.items()):
        if p["status"] == "INVALID":
            continue
        for gid in p["escrow_grants"]:
            bindings.setdefault(gid, []).append((pid, p))

    escrow = {}
    for gid, bound_pacts in sorted(bindings.items()):
        g = grants.get(gid)
        g_status = g["status"] if g is not None else "UNKNOWN_GRANT"
        reasons = []
        if g_status != "ACTIVE":
            reasons.append(f"GRANT_{g_status}")
        pact_states = {}
        for pid, p in bound_pacts:
            pact_states[pid] = {"status": p["status"], "escrow_mode": p["escrow_mode"]}
            required = "ACTIVE" if p["escrow_mode"] == "active" else "SETTLED"
            if p["status"] != required:
                reasons.append(f"PACT_{p['status']}:{pid[:12]}")
        escrow[gid] = {
            "grant_id": gid,
            "grant_status": g_status,
            "escrow_allowed": len(reasons) == 0,
            "reasons": reasons,
            "pacts": pact_states,
        }
    return {"as_of": as_of, "pacts": pacts, "grants": grants, "escrow": escrow}


# ---------------------------------------------------------------- computed-loss composition algebra (F1 / D20)


@dataclass(frozen=True)
class Recipe:
    """Guarantee contract R = (id, requires, gives, preserves, declared_losses, boundary)."""
    id: str
    requires: frozenset
    gives: frozenset
    preserves: frozenset = frozenset()
    declared_losses: frozenset = frozenset()
    boundary: frozenset = frozenset({"default"})


def make_recipe(rid, *, requires=(), gives=(), preserves=(), declared_losses=(), boundary=("default",)):
    """Construct a validated `Recipe` from iterables of guarantee/boundary labels."""
    if not isinstance(rid, str) or not rid.strip():
        raise ValueError("recipe id must be a non-empty string")
    req = frozenset(requires)
    gv = frozenset(gives)
    pr = frozenset(preserves)
    dl = frozenset(declared_losses)
    bnd = frozenset(boundary)
    if not bnd:
        raise ValueError("recipe boundary must be non-empty")
    return Recipe(id=rid, requires=req, gives=gv, preserves=pr, declared_losses=dl, boundary=bnd)


def pact_to_recipe(pact_entry):
    """Extract a `Recipe` from a resolved `pact@1` entry (admits ACTIVE or SETTLED pacts only)."""
    status = pact_entry.get("status")
    if status not in ("ACTIVE", "SETTLED"):
        raise ValueError(f"cannot extract recipe from pact in state {status!r}")
    comms = pact_entry.get("commitments", {})
    all_gives = set()
    all_reqs = set()
    all_pres = set()
    all_dloss = set()
    for c in comms.values():
        all_gives.update(c.get("gives", []))
        all_reqs.update(c.get("requires", []))
        all_pres.update(c.get("preserves", []))
        all_dloss.update(c.get("declared_losses", []))
    # Internal handoffs fulfilled by another party inside the same pact are not external prerequisites
    external_reqs = all_reqs - all_gives
    bnd = pact_entry.get("boundary") or ["default"]
    return make_recipe(
        pact_entry["pact_id"],
        requires=external_reqs,
        gives=all_gives,
        preserves=all_pres - all_dloss,
        declared_losses=all_dloss,
        boundary=bnd,
    )


def compose_recipes(recipes):
    """Compose a non-empty sequence of `Recipe`s under the default-deny computed-loss frame law.

    For every step R_i:
      - Compatibility (i >= 2): R_i.requires <= avail_{i-1} and (boundary_{i-1} & R_i.boundary) != empty.
      - Default-deny frame: carried_i = R_i.gives | (R_i.preserves & avail_{i-1}).
        Every label in avail_{i-1} \\ carried_i is mechanically added to `silent_drops` and
        `computed_losses`, even when R_i.declared_losses is empty (silence = loss, never preservation).
      - Anti-laundering: if a later step re-establishes a dropped guarantee g in R_j.gives, `avail`
        recovers g, but the drop event remains permanently recorded in `loss_events` and `silent_drops`.
    """
    steps = list(recipes)
    if not steps:
        raise ValueError("compose_recipes requires at least one recipe")

    errors = []
    loss_events = []
    declared_losses = set()
    silent_drops = set()
    re_established = set()

    first = steps[0]
    initial_requires = set(first.requires)
    boundary = set(first.boundary)
    declared_losses.update(first.declared_losses)

    # Even at step 0, any prerequisite not explicitly given or preserved is dropped
    carried_0 = set(first.gives) | (set(first.preserves) & initial_requires)
    dropped_0 = initial_requires - carried_0
    for g in sorted(dropped_0):
        silent_drops.add(g)
        loss_events.append({"guarantee": g, "step": 0, "recipe_id": first.id, "kind": "silent_drop"})
    avail = carried_0

    for idx, step in enumerate(steps[1:], start=1):
        missing = sorted(step.requires - avail)
        if missing:
            errors.append({
                "code": "PREREQ_UNMET",
                "step": idx,
                "recipe_id": step.id,
                "missing": missing,
            })
        next_boundary = boundary & set(step.boundary)
        if not next_boundary:
            errors.append({
                "code": "BOUNDARY_INCOMPATIBLE",
                "step": idx,
                "recipe_id": step.id,
                "prev_boundary": sorted(boundary),
                "step_boundary": sorted(step.boundary),
            })

        carried = set(step.gives) | (set(step.preserves) & avail)
        dropped = avail - carried
        for g in sorted(dropped):
            silent_drops.add(g)
            loss_events.append({"guarantee": g, "step": idx, "recipe_id": step.id, "kind": "silent_drop"})

        # Track re-establishment without erasing historical drop events (anti-laundering)
        for g in sorted(set(step.gives) & silent_drops):
            if g not in avail:
                re_established.add(g)
                loss_events.append({"guarantee": g, "step": idx, "recipe_id": step.id, "kind": "re_established"})

        declared_losses.update(step.declared_losses)
        avail = carried
        boundary = next_boundary

    computed_losses = declared_losses | silent_drops
    well_typed = len(errors) == 0
    lossless = well_typed and len(computed_losses) == 0 and len(loss_events) == 0

    return {
        "warrant": "composition/1",
        "well_typed": well_typed,
        "lossless": lossless,
        "steps": [s.id for s in steps],
        "requires": sorted(initial_requires),
        "gives": sorted(avail),
        "boundary": sorted(boundary),
        "declared_losses": sorted(declared_losses),
        "silent_drops": sorted(silent_drops),
        "re_established": sorted(re_established),
        "computed_losses": sorted(computed_losses),
        "loss_events": loss_events,
        "errors": errors,
    }


def compose_pacts(snap: Snapshot, trust: dict, pact_ids, as_of: int):
    """Resolve `pact_ids` in `snap` at `as_of` and compose them under the default-deny loss law."""
    pacts = resolve_pacts(snap, trust, as_of)
    recipes = []
    for pid in pact_ids:
        entry = pacts.get(pid)
        if entry is None:
            raise ValueError(f"unknown pact_id: {pid}")
        recipes.append(pact_to_recipe(entry))
    return compose_recipes(recipes)


# ---------------------------------------------------------------- CLI


def main(argv=None):
    import argparse
    import json
    import sys

    from . import repo as RP

    ap = argparse.ArgumentParser(prog="warrant pact", description="Resolve pact@1 contracts, escrow and computed-loss chains.")
    ap.add_argument("--root", default=None, help="Repository root (defaults to checkout around cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_st = sub.add_parser("status", help="Resolve all pact@1 contracts in the store")
    p_st.add_argument("--as-of", type=int, default=None)

    p_es = sub.add_parser("escrow", help="Resolve pact-bound grant@1 escrow permissions")
    p_es.add_argument("--as-of", type=int, default=None)

    p_co = sub.add_parser("compose", help="Compose pact@1 contracts under the default-deny computed-loss frame")
    p_co.add_argument("pact_ids", nargs="+", help="Ordered pact ids to compose")
    p_co.add_argument("--as-of", type=int, default=None)

    args = ap.parse_args(argv)
    rep = RP.Repo(args.root)
    trust, profile, _ = rep.config()
    snap = rep.store.snapshot()
    view = rep.view(snap)
    eff_as_of = args.as_of if args.as_of is not None else view.as_of

    if args.cmd == "status":
        out = {"as_of": eff_as_of, "pacts": resolve_pacts(snap, trust, eff_as_of)}
    elif args.cmd == "escrow":
        out = resolve_escrow(snap, trust, profile, eff_as_of)
    else:
        try:
            out = compose_pacts(snap, trust, args.pact_ids, eff_as_of)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
