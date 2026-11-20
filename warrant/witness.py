"""Proof-carrying guarantee witnesses for Warrant 3 (`warrant.witness`, docs/PACT.md §4).

In plain `pact@1`, guarantee labels such as `"auth"` or `"viable"` are opaque strings:
a party can declare `"viable"` in `pact/fulfill` with an arbitrary 64-hex digest, and two
recipes can compose `"verified"` while attaching different verification semantics to the word.

This module closes that seam (`F4 / D23`) with a pure, fail-closed offline witness layer:

  1. Canonical witness specifications `{"verifier": str, "params": dict}` attached per guarantee
     label in `pact@1` commitments and `Recipe`s.
  2. Built-in deterministic offline verifiers over `Snapshot.blobs` and verified `Snapshot` records:
       - `sha256-blob@1`                — blob exists in `snap.blobs` and SHA-256 matches `digest`
       - `vars1-coalition-viability@1`  — verifies canonical SHA-256, `live_env`, `policy_verified`,
                                          and optional `min_sovereign_bps`, `max_blocked_states`,
                                          and `required_states` against `minds/coalition.py` certs
       - `vars1-spore-receipt@1`        — verifies canonical SHA-256, `status == "SETTLED"`,
                                          strict ATP conservation (`atp_spent + atp_remaining == atp_budget`),
                                          and `partiality_inflated is False` against `minds/spore.py` receipts
       - `warrant-record@1`             — verifies `digest` is a signature-verified record in `snap`
                                          dated `<= as_of`, optionally matching schema/actor/state
  3. Unknown verifiers fail closed (`UNKNOWN_VERIFIER`); tampered digests, missing blobs, failed
     thresholds, or future-dated records fail closed (`UNGROUNDED_GUARANTEE`).
  4. Canonical spec fingerprints (`witness_spec_key`) let `pact.compose_recipes` reject semantic
     equivocation (`VERIFIER_SPEC_MISMATCH`) when a downstream step requires a witnessed guarantee
     under a different verifier or stricter parameters than the upstream step proved.
"""
import hashlib
import json
import math

from . import jcs as C
from . import records as R
from . import shapes as S

MAX_VERIFIER_NAME = 100
MAX_PARAMS_BYTES = 4096


def _is_num(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and math.isfinite(v)


def canonical_json_bytes(obj):
    """Canonical compact UTF-8 JSON matching `minds/coalition.py` and `minds/spore.py` certificates."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_json_digest(obj):
    """SHA-256 hex digest of `canonical_json_bytes(obj)`."""
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def parse_witness_spec(raw, label):
    """Validate a single guarantee witness specification `{"verifier": str, "params"?: dict}`."""
    if not isinstance(raw, dict):
        return None, f"witness spec for {label!r} must be an object"
    extra = sorted(set(raw) - {"verifier", "params"})
    if extra:
        return None, f"witness spec for {label!r} has unknown fields {extra}"
    ver = raw.get("verifier")
    if not isinstance(ver, str) or not ver or len(ver) > MAX_VERIFIER_NAME or ver != ver.strip():
        return None, f"witness verifier for {label!r} must be a trimmed non-empty string <= {MAX_VERIFIER_NAME}"
    params = raw.get("params", {})
    if not isinstance(params, dict):
        return None, f"witness params for {label!r} must be an object"
    try:
        pbytes = C.canon(params)
    except Exception as exc:
        return None, f"witness params for {label!r} are not canonical JSON: {exc}"
    if len(pbytes) > MAX_PARAMS_BYTES:
        return None, f"witness params for {label!r} exceed {MAX_PARAMS_BYTES} bytes"
    return {"verifier": ver, "params": params}, None


def witness_spec_key(spec):
    """Deterministic comparable key `(verifier_id, sha256(canon(params)))` for composition checks."""
    pdig = hashlib.sha256(C.canon(spec.get("params", {}))).hexdigest()
    return (spec["verifier"], pdig)


# ---------------------------------------------------------------- built-in offline verifiers


def _verify_sha256_blob(digest, params, snap, valid_recs, as_of):
    if not S.hex64(digest):
        return False, "BAD_DIGEST"
    blob = snap.blob(digest)
    if blob is None:
        return False, "BLOB_MISSING"
    if hashlib.sha256(blob).hexdigest() != digest:
        return False, "DIGEST_MISMATCH"
    min_bytes = params.get("min_bytes")
    if min_bytes is not None:
        if not (R.is_int(min_bytes) and min_bytes >= 0):
            return False, "BAD_PARAM_MIN_BYTES"
        if len(blob) < min_bytes:
            return False, "BLOB_TOO_SMALL"
    return True, "OK"


def _load_canonical_cert(digest, snap, expected_schema):
    if not S.hex64(digest):
        return None, "BAD_DIGEST"
    blob = snap.blob(digest)
    if blob is None:
        return None, "BLOB_MISSING"
    try:
        body = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, OverflowError, RecursionError):
        return None, "BAD_JSON_BLOB"
    if not isinstance(body, dict):
        return None, "BAD_CERT_OBJECT"
    # Verify content-address integrity over both raw blob and canonical JSON encoding
    raw_ok = hashlib.sha256(blob).hexdigest() == digest
    try:
        canon_ok = canonical_json_digest(body) == digest
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None, "BAD_JSON_BLOB"
    if not (raw_ok and canon_ok):
        return None, "DIGEST_MISMATCH"
    if body.get("schema") != expected_schema:
        return None, "SCHEMA_MISMATCH"
    return body, None


def _unique_state_set(items):
    """Return canonical JSON key set for `items`, or None if any state appears more than once."""
    keys = set()
    for x in items:
        k = json.dumps(x, sort_keys=True, separators=(",", ":"))
        if k in keys:
            return None
        keys.add(k)
    return keys


def _verify_coalition_viability(digest, params, snap, valid_recs, as_of):
    """Verify a `minds/coalition.py` `vars1-coalition-viability@1` certificate blob."""
    body, err = _load_canonical_cert(digest, snap, "vars1-coalition-viability@1")
    if err:
        return False, err
    if body.get("live_env") is not True:
        return False, "ENV_NOT_LIVE"
    if body.get("policy_verified") is not True:
        return False, "POLICY_UNVERIFIED"
    ctrl = body.get("controllable_viability")
    blocked = body.get("blocked_states")
    ang = body.get("angelic_viability")
    ratio = body.get("sovereign_ratio")
    if not (isinstance(ctrl, list) and isinstance(blocked, list) and isinstance(ang, list) and _is_num(ratio)):
        return False, "MALFORMED_VIABILITY_FIELDS"
    if not (0 <= ratio <= 1):
        return False, "BAD_SOVEREIGN_RATIO"

    ctrl_keys = _unique_state_set(ctrl)
    blocked_keys = _unique_state_set(blocked)
    ang_keys = _unique_state_set(ang)
    if ctrl_keys is None or blocked_keys is None or ang_keys is None:
        return False, "DUPLICATE_VIABILITY_STATES"
    if (ctrl_keys & blocked_keys) or (ctrl_keys | blocked_keys) != ang_keys:
        return False, "INCONSISTENT_VIABILITY_SETS"
    expected_ratio = (len(ctrl_keys) / len(ang_keys)) if ang_keys else 1.0
    if abs(ratio - expected_ratio) > 1e-6:
        return False, "INCONSISTENT_SOVEREIGN_RATIO"

    min_bps = params.get("min_sovereign_bps")
    if min_bps is not None:
        if not (R.is_int(min_bps) and 0 <= min_bps <= 10000):
            return False, "BAD_PARAM_MIN_SOVEREIGN_BPS"
        if len(ang_keys) > 0:
            if len(ctrl_keys) * 10000 < min_bps * len(ang_keys):
                return False, "SOVEREIGN_RATIO_BELOW_THRESHOLD"
        elif ratio * 10000.0 + 1e-9 < min_bps:
            return False, "SOVEREIGN_RATIO_BELOW_THRESHOLD"

    max_blocked = params.get("max_blocked_states")
    if max_blocked is not None:
        if not (R.is_int(max_blocked) and max_blocked >= 0):
            return False, "BAD_PARAM_MAX_BLOCKED"
        if len(blocked_keys) > max_blocked:
            return False, "BLOCKED_STATES_EXCEEDED"

    req_states = params.get("required_states")
    if req_states is not None:
        if not isinstance(req_states, list):
            return False, "BAD_PARAM_REQUIRED_STATES"
        for st in req_states:
            if json.dumps(st, sort_keys=True, separators=(",", ":")) not in ctrl_keys:
                return False, "REQUIRED_STATE_NOT_VIABLE"

    return True, "OK"


def _verify_spore_receipt(digest, params, snap, valid_recs, as_of):
    """Verify a `minds/spore.py` `vars1-spore-receipt@1` metered execution receipt blob."""
    body, err = _load_canonical_cert(digest, snap, "vars1-spore-receipt@1")
    if err:
        return False, err
    if body.get("status") != "SETTLED":
        return False, "SPORE_NOT_SETTLED"
    budget = body.get("atp_budget")
    spent = body.get("atp_spent")
    rem = body.get("atp_remaining")
    if not (R.is_int(budget) and R.is_int(spent) and R.is_int(rem)):
        return False, "MALFORMED_ATP_FIELDS"
    if budget < 0 or spent < 0 or rem < 0:
        return False, "NEGATIVE_ATP"
    if spent > budget or spent + rem != budget:
        return False, "ATP_CONSERVATION_VIOLATED"
    if body.get("partiality_inflated") is not False:
        return False, "PARTIALITY_INFLATED"

    max_atp = params.get("max_atp_spent")
    if max_atp is not None:
        if not (R.is_int(max_atp) and max_atp >= 0):
            return False, "BAD_PARAM_MAX_ATP"
        if spent > max_atp:
            return False, "ATP_SPENT_EXCEEDED"

    req_spore = params.get("spore_digest")
    if req_spore is not None:
        if body.get("spore_digest") != req_spore:
            return False, "SPORE_DIGEST_MISMATCH"

    return True, "OK"


def _verify_warrant_record(digest, params, snap, valid_recs, as_of):
    """Verify `digest` names a signature-verified Warrant 3 record dated `<= as_of`."""
    if not S.hex64(digest):
        return False, "BAD_DIGEST"
    rec = valid_recs.get(digest)
    if rec is None:
        return False, "RECORD_NOT_FOUND_OR_UNTRUSTED"
    at = rec.get("at")
    if not (R.is_int(at) and at <= as_of):
        return False, "RECORD_AFTER_AS_OF"
    exp_schema = params.get("schema")
    if exp_schema is not None and rec.get("schema") != exp_schema:
        return False, "RECORD_SCHEMA_MISMATCH"
    exp_actor = params.get("actor")
    if exp_actor is not None and rec.get("actor") != exp_actor:
        return False, "RECORD_ACTOR_MISMATCH"
    exp_state = params.get("state")
    if exp_state is not None and (rec.get("body") or {}).get("state") != exp_state:
        return False, "RECORD_STATE_MISMATCH"
    return True, "OK"


def _trimmed_str(v):
    return isinstance(v, str) and bool(v) and v == v.strip()


def _unique_str_list(items):
    if not isinstance(items, list) or not all(_trimmed_str(x) for x in items):
        return None
    if len(set(items)) != len(items):
        return None
    return items


def _verify_identity_lineage(digest, params, snap, valid_recs, as_of):
    """Verify a `minds/identity.py` `vars1-identity-lineage@1` relational identity & fork certificate."""
    body, err = _load_canonical_cert(digest, snap, "vars1-identity-lineage@1")
    if err:
        return False, err
    node_id = body.get("node_id")
    entity_root = body.get("entity_root")
    birth_kind = body.get("birth_kind")
    atp = body.get("atp")
    invs = body.get("invariants")
    rels = body.get("relations")
    prov = _unique_str_list(body.get("provenance_chain"))
    lin = _unique_str_list(body.get("entity_lineage"))
    if not (_trimmed_str(node_id) and _trimmed_str(entity_root)
            and birth_kind in ("genesis", "step", "fork")
            and R.is_int(atp) and atp >= 0
            and isinstance(invs, list) and isinstance(rels, list)
            and prov and lin):
        return False, "MALFORMED_IDENTITY_FIELDS"
    inv_keys = _unique_state_set(invs)
    rel_keys = _unique_state_set(rels)
    if inv_keys is None or rel_keys is None:
        return False, "DUPLICATE_IDENTITY_ENTRIES"
    if lin[0] != entity_root or lin[-1] != node_id or prov[-1] != node_id:
        return False, "INCONSISTENT_LINEAGE_ENDPOINTS"
    if len(lin) > len(prov) or prov[-len(lin):] != lin:
        return False, "LINEAGE_NOT_PROVENANCE_SUFFIX"
    if birth_kind == "genesis" and (len(prov) != 1 or len(lin) != 1 or entity_root != node_id):
        return False, "INVALID_GENESIS_SHAPE"
    if birth_kind == "fork" and (entity_root != node_id or len(lin) != 1 or len(prov) < 2 or len(rels) != 0):
        return False, "INVALID_FORK_SHAPE"
    if birth_kind == "step" and len(lin) < 2:
        return False, "INVALID_STEP_SHAPE"

    min_atp = params.get("min_atp")
    if min_atp is not None:
        if not (R.is_int(min_atp) and min_atp >= 0):
            return False, "BAD_PARAM_MIN_ATP"
        if atp < min_atp:
            return False, "IDENTITY_ATP_BELOW_MIN"

    req_kind = params.get("require_birth_kind")
    if req_kind is not None:
        if req_kind not in ("genesis", "step", "fork"):
            return False, "BAD_PARAM_BIRTH_KIND"
        if birth_kind != req_kind:
            return False, "BIRTH_KIND_MISMATCH"

    req_anc = params.get("require_ancestor")
    if req_anc is not None:
        if not _trimmed_str(req_anc):
            return False, "BAD_PARAM_ANCESTOR"
        if req_anc not in prov:
            return False, "ANCESTOR_MISSING"

    req_dist = params.get("require_distinct_from")
    if req_dist is not None:
        if not _trimmed_str(req_dist):
            return False, "BAD_PARAM_DISTINCT"
        if req_dist == entity_root or req_dist in lin:
            return False, "SAME_ENTITY_FORBIDDEN"

    if params.get("require_empty_relations") is True and len(rels) != 0:
        return False, "RELATIONS_NOT_ISOLATED"

    req_invs = params.get("required_invariants")
    if req_invs is not None:
        if not isinstance(req_invs, list):
            return False, "BAD_PARAM_REQUIRED_INVARIANTS"
        for item in req_invs:
            if json.dumps(item, sort_keys=True, separators=(",", ":")) not in inv_keys:
                return False, "REQUIRED_INVARIANT_MISSING"

    return True, "OK"


def _verify_trajectory_mass(digest, params, snap, valid_recs, as_of):
    """Verify a `minds/trajectory.py` `vars1-trajectory-mass@1` safety & semantic mass certificate."""
    body, err = _load_canonical_cert(digest, snap, "vars1-trajectory-mass@1")
    if err:
        return False, err
    if body.get("trajectory_safe") is not True:
        return False, "TRAJECTORY_UNSAFE"
    steps = body.get("step_count")
    horizon = body.get("horizon")
    vmass = body.get("verified_mass")
    tweight = body.get("total_weight")
    vacts = body.get("verified_acts")
    ncacts = body.get("non_counting_acts")
    refuted = _unique_str_list(body.get("refuted_ids"))
    if not (R.is_int(steps) and steps >= 0 and R.is_int(horizon) and horizon >= 0
            and R.is_int(vmass) and vmass >= 0 and R.is_int(tweight) and tweight >= 0
            and isinstance(vacts, list) and isinstance(ncacts, list) and refuted is not None):
        return False, "MALFORMED_TRAJECTORY_FIELDS"

    refuted_set = set(refuted)
    seen_ids = set()
    sum_verified = 0
    for act in vacts:
        if not isinstance(act, dict):
            return False, "MALFORMED_ACT"
        aid, sidx, w = act.get("act_id"), act.get("step_idx"), act.get("weight")
        if not (_trimmed_str(aid) and R.is_int(sidx) and sidx >= 0 and R.is_int(w) and w >= 0):
            return False, "MALFORMED_ACT"
        if aid in seen_ids:
            return False, "DUPLICATE_ACT_ID"
        if aid in refuted_set:
            return False, "REFUTED_ACT_COUNTED"
        if sidx > horizon:
            return False, "ACT_EXCEEDS_HORIZON"
        seen_ids.add(aid)
        sum_verified += w

    sum_non_counting = 0
    nc_refuted_ids = set()
    for act in ncacts:
        if not isinstance(act, dict):
            return False, "MALFORMED_ACT"
        aid, origin = act.get("act_id"), act.get("origin")
        is_ref, sidx, w = act.get("refuted"), act.get("step_idx"), act.get("weight")
        if not (_trimmed_str(aid) and origin in ("verified", "retold", "forked")
                and isinstance(is_ref, bool) and R.is_int(sidx) and sidx >= 0
                and R.is_int(w) and w >= 0):
            return False, "MALFORMED_ACT"
        if aid in seen_ids:
            return False, "DUPLICATE_ACT_ID"
        if origin == "verified" and not is_ref and sidx <= horizon:
            return False, "MISCLASSIFIED_NON_COUNTING_ACT"
        if is_ref:
            nc_refuted_ids.add(aid)
        seen_ids.add(aid)
        sum_non_counting += w

    if nc_refuted_ids != refuted_set:
        return False, "REFUTED_IDS_MISMATCH"
    if sum_verified != vmass:
        return False, "MASS_ACCOUNTING_MISMATCH"
    if sum_verified + sum_non_counting != tweight:
        return False, "TOTAL_WEIGHT_MISMATCH"

    min_mass = params.get("min_mass")
    if min_mass is not None:
        if not (R.is_int(min_mass) and min_mass >= 0):
            return False, "BAD_PARAM_MIN_MASS"
        if vmass < min_mass:
            return False, "MASS_BELOW_THRESHOLD"

    min_steps = params.get("min_steps")
    if min_steps is not None:
        if not (R.is_int(min_steps) and min_steps >= 0):
            return False, "BAD_PARAM_MIN_STEPS"
        if steps < min_steps:
            return False, "STEPS_BELOW_MIN"

    max_horizon = params.get("max_horizon")
    if max_horizon is not None:
        if not (R.is_int(max_horizon) and max_horizon >= 0):
            return False, "BAD_PARAM_MAX_HORIZON"
        if horizon > max_horizon:
            return False, "HORIZON_EXCEEDED"

    max_refuted = params.get("max_refuted")
    if max_refuted is not None:
        if not (R.is_int(max_refuted) and max_refuted >= 0):
            return False, "BAD_PARAM_MAX_REFUTED"
        if len(refuted_set) > max_refuted:
            return False, "REFUTED_COUNT_EXCEEDED"

    return True, "OK"


BUILTIN_VERIFIERS = {
    "sha256-blob@1": _verify_sha256_blob,
    "vars1-coalition-viability@1": _verify_coalition_viability,
    "vars1-spore-receipt@1": _verify_spore_receipt,
    "vars1-identity-lineage@1": _verify_identity_lineage,
    "vars1-trajectory-mass@1": _verify_trajectory_mass,
    "warrant-record@1": _verify_warrant_record,
}


def verify_witness(spec, digest, snap, valid_recs, as_of, *, verifiers=None):
    """Verify one guarantee witness `digest` against `spec`, failing closed on unknown verifiers."""
    reg = BUILTIN_VERIFIERS if verifiers is None else {**BUILTIN_VERIFIERS, **verifiers}
    vid = spec.get("verifier")
    fn = reg.get(vid)
    if fn is None:
        return False, "UNKNOWN_VERIFIER"
    return fn(digest, spec.get("params", {}), snap, valid_recs, as_of)


def make_spore_receipt_blob(*, spore_digest, atp_budget, atp_spent, atp_remaining,
                            status="SETTLED", partiality_inflated=False, result_digest=None):
    """Helper producing `(digest, canonical_bytes)` for a `vars1-spore-receipt@1` witness blob."""
    body = {
        "schema": "vars1-spore-receipt@1",
        "spore_digest": spore_digest,
        "status": status,
        "atp_budget": atp_budget,
        "atp_spent": atp_spent,
        "atp_remaining": atp_remaining,
        "partiality_inflated": partiality_inflated,
    }
    if result_digest is not None:
        body["result_digest"] = result_digest
    raw = canonical_json_bytes(body)
    return hashlib.sha256(raw).hexdigest(), raw
