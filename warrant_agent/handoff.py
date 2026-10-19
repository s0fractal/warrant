"""Transfer of a frozen slice (PROPOSAL §5, CONTRACT C.3, D).

export   manifest + every declared byte of the configured store, from a frozen view
inspect  check the package, stage it, compute the delivery relation against a
         RECEIVER-configured expectation, assess the union in a frozen view
import   add-only union into the live store, journaled, retryable

A manifest digest carried by a package is never an expectation; expectations
come from the receiver's configuration. MATCH_EXPECTED_SET means only "this is the
selected set"; completeness stays UNATTESTED."""
import base64
import json
import re
import time

from warrant import jcs as C
from warrant import keys as K
from warrant import records as R
from warrant.keys import Key
from warrant.store import Snapshot, Store, _authenticate

from . import views
from .errors import AgentError, need

HEX64 = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_FIELDS = {"warrant_handoff", "source", "selection", "capture", "roots", "records", "blobs",
                   "sender_assessment", "completeness"}
PROMOTE_DEFAULT = ("MATCH_EXPECTED_SET",)
_FAULT_AFTER = None          # tests only: simulate a crash after N promotion writes


def _hex(v):
    return isinstance(v, str) and HEX64.match(v) is not None


def manifest_problem(m):
    if not (isinstance(m, dict) and set(m) == MANIFEST_FIELDS and m["warrant_handoff"] == "1"
            and m["selection"] == "ENTIRE_CONFIGURED_STORE" and m["completeness"] == "UNATTESTED"):
        return "manifest fields"
    cap = m["capture"]
    if not (isinstance(cap, dict) and set(cap) == {"snapshot", "captured_at", "assessed_as_of"} and _hex(cap["snapshot"])
            and type(cap["captured_at"]) is int and type(cap["assessed_as_of"]) is int):
        return "manifest capture"
    if not (isinstance(m["source"], str) and m["source"] and _hex(m["sender_assessment"])):
        return "manifest source"
    if not (isinstance(m["roots"], list) and all(isinstance(r, dict) and set(r) == {"kind", "id"}
                                                 and r["kind"] in ("duty", "transition") and _hex(r["id"]) for r in m["roots"])):
        return "manifest roots"
    recs = m["records"]
    if not (isinstance(recs, list) and all(isinstance(r, dict) and set(r) == {"id", "envelope"} and _hex(r["id"])
                                           and _hex(r["envelope"]) for r in recs)):
        return "manifest records"
    if [r["id"] for r in recs] != sorted({r["id"] for r in recs}) or len({r["id"] for r in recs}) != len(recs):
        return "manifest records must be sorted and unique"
    if not (isinstance(m["blobs"], list) and all(_hex(b) for b in m["blobs"]) and m["blobs"] == sorted(set(m["blobs"]))):
        return "manifest blobs must be sorted, unique hex64"
    return None


def _payload_items(payload, limit):
    """{"records": {id: bytes}, "blobs": {id: bytes}} from the wire payload, refusing
    paths, duplicates, non-hex ids and oversized transfers before any byte is kept."""
    need(isinstance(payload, dict) and set(payload) == {"records", "blobs"}, "BAD_REQUEST", "payload is {records, blobs}")
    out, total = {"records": {}, "blobs": {}}, 0
    for kind in ("records", "blobs"):
        items = payload[kind]
        need(isinstance(items, list), "BAD_REQUEST", f"payload {kind} must be a list")
        for it in items:
            need(isinstance(it, dict) and set(it) == {"id", "bytes_base64"} and _hex(it["id"])
                 and isinstance(it["bytes_base64"], str), "BAD_REQUEST",
                 "a payload item is {id: hex64, bytes_base64}; ids are content addresses, never paths")
            need(it["id"] not in out[kind], "BAD_REQUEST", f"duplicate {kind} id {it['id'][:12]}")
            total += len(it["bytes_base64"]) * 3 // 4
            if total > limit:
                raise AgentError("RESOURCE_LIMIT", f"transfer exceeds the configured {limit} bytes; nothing was staged")
            try:
                out[kind][it["id"]] = base64.b64decode(it["bytes_base64"], validate=True)
            except ValueError:
                raise AgentError("BAD_REQUEST", "bytes_base64 is not base64") from None
    return out


# ---------------------------------------------------------------- export

def export(ws, token, roots, request_id):
    ws.permit("handoff")
    need(isinstance(request_id, str) and 0 < len(request_id) <= 128, "BAD_REQUEST", "request_id")
    meta, report, vdir = views.load(ws, token)
    need(isinstance(roots, list) and all(isinstance(r, dict) and set(r) == {"kind", "id"} for r in roots),
         "BAD_REQUEST", "roots are [{kind, id}]")
    roots = sorted(roots, key=lambda r: (r["kind"], r["id"]))
    rec_path = ws.state / "exports" / f"{C.digest(request_id.encode())}.json"
    if rec_path.is_file():
        prev = views.read_json(rec_path)
        need(prev["view"] == token and prev["roots"] == roots, "CONFLICT", "request_id was used for another export")
        return prev["package"]
    snap = Snapshot.read(vdir)
    size = sum(len(b) for b in snap.records.values()) + sum(len(b) for b in snap.blobs.values())
    if size > ws.limits["transfer_bytes"]:
        raise AgentError("RESOURCE_LIMIT", f"the store is {size} bytes; the configured transfer limit is "
                                           f"{ws.limits['transfer_bytes']}; nothing was exported")
    manifest = {"warrant_handoff": "1", "source": ws.source_name, "selection": "ENTIRE_CONFIGURED_STORE",
                "capture": {"snapshot": snap.digest, "captured_at": meta["created"], "assessed_as_of": meta["as_of"]},
                "roots": roots,
                "records": [{"id": rid, "envelope": C.digest(data)} for rid, data in sorted(snap.records.items())],
                "blobs": sorted(snap.blobs), "sender_assessment": report["assessment_id"], "completeness": "UNATTESTED"}
    assert manifest_problem(manifest) is None
    mhash = C.doc_id(manifest)
    declaration = None
    if ws.signer:
        actor, keyfile = ws.signer
        body = R.transition("ATTESTED", [mhash], established=[f"exported the declared slice {mhash}"],
                            residual=["global completeness of the source is not established"])
        rec = R.record("transition", actor, int(time.time()), body)
        _, env = R.sign(rec, Key.from_seed_hex(keyfile.read_text()))
        declaration = base64.b64encode(env).decode()
    package = {"manifest": manifest, "manifest_bytes": base64.b64encode(C.canon(manifest)).decode(),
               "payload": {"records": [{"id": i, "bytes_base64": base64.b64encode(b).decode()} for i, b in sorted(snap.records.items())],
                           "blobs": [{"id": i, "bytes_base64": base64.b64encode(b).decode()} for i, b in sorted(snap.blobs.items())]},
               "declaration": declaration}
    views.write_json(rec_path, {"view": token, "roots": roots, "package": package})
    return package


# ---------------------------------------------------------------- inspect

def _declaration_actor(ws, declaration, mhash):
    """The actor whose declaration of exactly this manifest verifies under the
    RECEIVER's trust, or None."""
    if declaration is None:
        return None
    try:
        env_bytes = base64.b64decode(declaration, validate=True)
        env = C.loads(env_bytes)
        rid = R.record_id(env["record"])
    except (ValueError, KeyError, TypeError, C.NotCanonical, R.Invalid):
        return None
    why, rec = _authenticate(rid, env_bytes, ws.trust())
    if why or rec["type"] != "transition":
        return None
    b = rec["body"]
    if b["evidence"] != [mhash] or b["closes"] or b["opened"] or b["supersedes"]:
        return None
    return rec["actor"]


def inspect(ws, manifest, payload, expectation=None, declaration=None):
    ws.permit("handoff")
    need(manifest_problem(manifest) is None, "BAD_REQUEST", f"manifest: {manifest_problem(manifest)}")
    items = _payload_items(payload, ws.limits["transfer_bytes"])
    expect = ws.expectation(expectation)
    mhash = C.doc_id(manifest)
    declared = {r["id"]: r["envelope"] for r in manifest["records"]}
    reasons, mismatched = [], []
    for h, data in items["blobs"].items():
        if C.digest(data) != h:
            mismatched.append(h)
            reasons.append(f"blob {h[:12]}: bytes do not hash to their id")
    for rid, data in items["records"].items():
        try:
            env = C.loads(data)
            ok = R.record_id(env["record"]) == rid
        except (C.NotCanonical, KeyError, TypeError, R.Invalid):
            ok = False
        if not ok:
            mismatched.append(rid)
            reasons.append(f"record {rid[:12]}: bytes are not the canonical envelope of this id")
        elif rid in declared and C.digest(data) != declared[rid]:
            mismatched.append(rid)
            reasons.append(f"record {rid[:12]}: envelope differs from the manifest's")
    extra = sorted((set(items["records"]) - set(declared)) | (set(items["blobs"]) - set(manifest["blobs"])))
    missing = sorted((set(declared) - set(items["records"])) | (set(manifest["blobs"]) - set(items["blobs"])))
    if extra:
        reasons.append(f"{len(extra)} undeclared object(s) in the payload")
    if missing:
        reasons.append(f"{len(missing)} declared object(s) missing: " + ", ".join(m[:12] for m in missing[:8]))
    clean = not mismatched and not extra
    if clean and not missing and Snapshot(items["records"], items["blobs"]).digest != manifest["capture"]["snapshot"]:
        clean = False
        reasons.append("the delivered bytes do not reproduce the manifest's snapshot digest")
    exporter = _declaration_actor(ws, declaration, mhash)
    if not clean:
        relation = "CONTENT_MISMATCH"
    elif missing:
        relation = "MISSING_DECLARED_BYTES"
    elif expect is None:
        relation = "UNPINNED"
        reasons.append("no receiver expectation selected; a manifest digest in the package is not one")
    elif expect.get("source") not in (None, manifest["source"]):
        relation = "WRONG_SOURCE"
        reasons.append(f"expected source {expect['source']!r}, manifest names {manifest['source']!r}")
    elif expect["manifest"] != mhash:
        relation = "WRONG_SET"
        reasons.append("the manifest is not the expected commitment (another set or another cut)")
    elif expect.get("exporter") and exporter != expect["exporter"]:
        relation = "UNVERIFIED_EXPORTER"
        reasons.append(f"no declaration of this manifest by {expect['exporter']!r} verifies under the receiver's trust")
    else:
        relation = "MATCH_EXPECTED_SET"
    staged_id = C.doc_id({"manifest": mhash, "payload": C.doc_id({k: sorted([i, C.digest(b)] for i, b in v.items())
                                                                  for k, v in items.items()})})
    sdir = ws.state / "staging" / staged_id
    good = {"records": {i: b for i, b in items["records"].items() if i not in mismatched},
            "blobs": {i: b for i, b in items["blobs"].items() if i not in mismatched}}
    for i, b in good["records"].items():
        views._write(sdir / "records" / f"{i}.json", b)
    for i, b in good["blobs"].items():
        views._write(sdir / "blobs" / i, b)
    delivery = {"relation": relation, "manifest": mhash, "expectation": expect["handle"] if expect else None,
                "source": manifest["source"], "declared_snapshot": manifest["capture"]["snapshot"],
                "exporter": exporter, "missing": missing, "mismatched": sorted(mismatched),
                "source_completeness": "UNATTESTED", "reasons": reasons}
    views.write_json(sdir / "staged.json", {"staged_id": staged_id, "manifest": manifest, "delivery": delivery,
                                            "received_at": int(time.time())})
    meta = views.capture(ws, extra=good, delivery=delivery)
    return staged_id, meta


# ---------------------------------------------------------------- import

def import_(ws, staged_id, request_id):
    ws.permit("handoff")
    need(_hex(staged_id), "BAD_REQUEST", "staged_id")
    need(isinstance(request_id, str) and 0 < len(request_id) <= 128, "BAD_REQUEST", "request_id")
    sdir = ws.state / "staging" / staged_id
    need((sdir / "staged.json").is_file(), "NOT_FOUND", "no such staged package")
    staged = views.read_json(sdir / "staged.json")
    jpath = ws.state / "imports" / f"{C.digest(request_id.encode())}.json"
    journal = views.read_json(jpath) if jpath.is_file() else None
    if journal:
        need(journal["staged_id"] == staged_id, "CONFLICT", "request_id was used for another import")
        if journal["status"] == "COMPLETE":
            return journal
    rel = staged["delivery"]["relation"]
    allowed = tuple(ws.uses.get("import", {}).get("delivery", PROMOTE_DEFAULT))
    if rel not in allowed:
        raise AgentError("IMPORT_BLOCKED", f"delivery {rel} is not one this workspace imports", allowed=list(allowed))
    snap = Snapshot.read(sdir)
    for h, b in snap.blobs.items():
        need(C.digest(b) == h, "CONFLICT", "staged bytes changed since inspection")
    trust = ws.trust()
    invalid = {rid: why for rid, data in snap.records.items() for why, _ in [_authenticate(rid, data, trust)] if why}
    if invalid:
        raise AgentError("IMPORT_BLOCKED", "records that do not authenticate under the receiver's trust stay staged",
                         invalid={k[:16]: v for k, v in sorted(invalid.items())})
    files = [("records", f"{rid}.json", b) for rid, b in sorted(snap.records.items())] + \
            [("blobs", h, b) for h, b in sorted(snap.blobs.items())]
    journal = journal or {"request_id": request_id, "staged_id": staged_id, "status": "STARTED",
                          "relation": rel, "manifest": staged["delivery"]["manifest"], "started": int(time.time())}
    views.write_json(jpath, journal)
    Store(ws.store).init()
    for n, (kind, name, data) in enumerate(files):
        if _FAULT_AFTER is not None and n == _FAULT_AFTER:
            raise RuntimeError("injected crash during promotion")
        dst = ws.store / kind / name
        if dst.exists():
            if dst.read_bytes() != data:
                journal["status"] = "CONFLICT"
                views.write_json(jpath, journal)
                raise AgentError("CONFLICT", f"{kind}/{name[:16]} exists with other bytes; nothing is overwritten")
            continue
        views._write(dst, data)
    for kind, name, data in files:
        need((ws.store / kind / name).read_bytes() == data, "IMPORT_INCOMPLETE", f"{kind}/{name[:16]} not promoted")
    journal.update(status="COMPLETE", completed=int(time.time()), objects=len(files),
                   resulting_snapshot=Snapshot.read(ws.store).digest)
    views.write_json(jpath, journal)
    return journal
