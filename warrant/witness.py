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
                                          and optional `min_sovereign_ratio`, `max_blocked_states`,
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
    return (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))


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
    except (UnicodeDecodeError, ValueError):
        return None, "BAD_JSON_BLOB"
    if not isinstance(body, dict):
        return None, "BAD_CERT_OBJECT"
    # Verify content-address integrity over both raw blob and canonical JSON encoding
    raw_ok = hashlib.sha256(blob).hexdigest() == digest
    canon_ok = canonical_json_digest(body) == digest
    if not (raw_ok and canon_ok):
        return None, "DIGEST_MISMATCH"
    if body.get("schema") != expected_schema:
        return None, "SCHEMA_MISMATCH"
    return body, None


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
    ratio = body.get("sovereign_ratio")
    if not (isinstance(ctrl, list) and isinstance(blocked, list) and _is_num(ratio)):
        return False, "MALFORMED_VIABILITY_FIELDS"
    if not (0.0 <= ratio <= 1.0):
        return False, "BAD_SOVEREIGN_RATIO"

    min_bps = params.get("min_sovereign_bps")
    if min_bps is not None:
        if not (R.is_int(min_bps) and 0 <= min_bps <= 10000):
            return False, "BAD_PARAM_MIN_SOVEREIGN_BPS"
        ang = body.get("angelic_viability")
        if isinstance(ang, list) and len(ang) > 0:
            if len(ctrl) * 10000 < min_bps * len(ang):
                return False, "SOVEREIGN_RATIO_BELOW_THRESHOLD"
        elif ratio * 10000.0 + 1e-9 < min_bps:
            return False, "SOVEREIGN_RATIO_BELOW_THRESHOLD"

    max_blocked = params.get("max_blocked_states")
    if max_blocked is not None:
        if not (R.is_int(max_blocked) and max_blocked >= 0):
            return False, "BAD_PARAM_MAX_BLOCKED"
        if len(blocked) > max_blocked:
            return False, "BLOCKED_STATES_EXCEEDED"

    req_states = params.get("required_states")
    if req_states is not None:
        if not isinstance(req_states, list):
            return False, "BAD_PARAM_REQUIRED_STATES"
        ctrl_keys = {json.dumps(x, sort_keys=True) for x in ctrl}
        for st in req_states:
            if json.dumps(st, sort_keys=True) not in ctrl_keys:
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


BUILTIN_VERIFIERS = {
    "sha256-blob@1": _verify_sha256_blob,
    "vars1-coalition-viability@1": _verify_coalition_viability,
    "vars1-spore-receipt@1": _verify_spore_receipt,
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
