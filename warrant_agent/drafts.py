"""prepare / commit of exact record bytes under the configured signer (PROPOSAL §7,
CONTRACT C.4-C.5). A draft freezes the record (actor, at, body); commit signs
exactly that record. Ed25519 signatures are deterministic, so a retried commit
reproduces the same envelope; an existing envelope under the record id is
recognized before anything is signed again."""
import copy
import re
import time

from warrant import jcs as C
from warrant import records as R
from warrant import shapes as S
from warrant.cli import fill
from warrant.keys import Key
from warrant.store import ChainMoved, Store, _authenticate

from . import views
from .errors import AgentError, need


def _draft(ws, draft_id):
    """The draft file of THIS workspace: the id is a full hex64 address before any
    path is built, and the stored draft must name this workspace."""
    need(S.hex64(draft_id), "BAD_REQUEST", "draft_id is a hex64 address")
    path = ws.state / "drafts" / f"{draft_id}.json"
    need(path.is_file(), "NOT_FOUND", "no such draft")
    d = views.read_json(path)
    need(d.get("workspace") == ws.name and d.get("draft_id") == draft_id, "NOT_FOUND", "no such draft")
    return path, d


def _signer(ws):
    need(ws.signer is not None, "NO_SIGNER", "this workspace has no configured signer")
    actor, keyfile = ws.signer
    return actor, Key.from_seed_hex(keyfile.read_text())


def _accept_body(meta_vdir, body):
    """The typed accept convenience: {transition, item, evidence?, support?}; a
    missing evidence set is the exact evidence of that item in the frozen view."""
    need(isinstance(body, dict) and set(body) <= {"transition", "item", "evidence", "support"}
         and "transition" in body and "item" in body, "BAD_REQUEST", "accept is {transition, item, evidence?, support?}")
    need(S.hex64(body["transition"]), "BAD_REQUEST", "transition is a hex64 record id")
    if "evidence" in body:
        return R.accept(body["transition"], body["item"], body["evidence"], body.get("support", []))
    p = meta_vdir / "records" / f"{body['transition']}.json"
    need(p.is_file(), "NOT_FOUND", "the transition is not in this view")
    try:                                        # the view's bytes are untrusted: a malformed record is no transition
        t = C.loads(p.read_bytes())["record"]["body"]
        closes, evidence = t["closes"], t["evidence"]
    except (C.NotCanonical, ValueError, KeyError, TypeError):
        raise AgentError("BAD_REQUEST", "the record is not a well-formed transition") from None
    item = body["item"]
    need(isinstance(closes, list) and (item is None or (type(item) is int and 0 <= item < len(closes))),
         "BAD_REQUEST", "no such item")
    ev = evidence if item is None else closes[item].get("evidence") if isinstance(closes[item], dict) else None
    need(isinstance(ev, list), "BAD_REQUEST", "the record is not a well-formed transition")
    return R.accept(body["transition"], item, ev, body.get("support", []))


# The smallest body of each type an agent writes, as the refusal of an invalid body shows it.
ACTOR_SLOT, DUTY_SLOT = "<actor>", "<duty id>"
TEMPLATES = {
    "transition": {"basis": "ATTESTED", "established": ["what is now true, in one sentence each"],
                   "residual": ["what this does not establish or what is still open"],
                   "closes": "optional: [{duty: <duty id>, act: discharge, evidence: [<blob id>]}] only for duties "
                             "this work completes",
                   "evidence": "optional: [<blob id in the store>, or blob:<i> for blobs[i] of this prepare]"},
    "duty": {"holder": ACTOR_SLOT, "statement": "what is owed", "owed_to": [ACTOR_SLOT], "condition": {"attest": {}},
             "accept_by": ["<actor whose acceptance closes it>"]},
    "accept": {"transition": "<transition id>", "item": 0},
    "challenge": {"target": "<transition id>", "item": 0, "statement": "what is wrong", "evidence": []},
    "observation": {"target": DUTY_SLOT, "probe": "<hex64 the duty's observe condition names>",
                    "window": [0, 1], "result": "<observed value>", "raw": []},
    "grant": {"grantee": ACTOR_SLOT, "acts": ["release"], "delegable": [], "duties": [DUTY_SLOT],
              "expires": None, "parent": None},
}


BLOB_REF = re.compile(r"^blob:(0|[1-9]\d{0,3})\Z", re.ASCII)    # \Z: `$` admits a trailing newline; ASCII: \d is 0-9


def _evidence_lists(rtype, body):
    """The lists of a body that cite blobs by id: a transition's evidence and each item's, an
    accept's or a challenge's evidence, an observation's raw."""
    keys = {"transition": ("evidence",), "accept": ("evidence",), "challenge": ("evidence",), "observation": ("raw",)}
    out = [(body, k) for k in keys.get(rtype, ()) if isinstance(body.get(k), list)]
    if rtype == "transition" and isinstance(body.get("closes"), list):
        out += [(m, "evidence") for m in body["closes"] if isinstance(m, dict) and isinstance(m.get("evidence"), list)]
    return out


def _with_blobs(ws, rtype, body, blobs):
    """(body, [blob ids]): the JSON documents given with a prepare are stored at commit as their
    canonical bytes (JCS); in the body's evidence lists `blob:<i>` names the id of blobs[i]. Each
    blob is cited, and nothing but a blob given here is named so."""
    need(isinstance(blobs, list) and blobs, "BAD_REQUEST", "blobs is a non-empty list of JSON documents")
    try:
        data = [C.canon(doc) for doc in blobs]
    except (C.NotCanonical, ValueError, TypeError) as e:
        raise AgentError("BAD_REQUEST", f"blobs: a blob is not a canonical JSON document: {e}") from None
    total, bound = sum(len(b) for b in data), ws.limits["transfer_bytes"]
    need(total <= bound, "RESOURCE_LIMIT", f"blobs: {total} bytes, beyond transfer_bytes",
         limit="transfer_bytes", value=total, bound=bound)
    ids, cited = [C.digest(b) for b in data], set()
    body = copy.deepcopy(body)
    for holder, k in _evidence_lists(rtype, body):
        out = []
        for v in holder[k]:
            m = BLOB_REF.match(v) if isinstance(v, str) else None
            if m:
                i = int(m.group(1))
                need(i < len(ids), "BAD_REQUEST", f"{v} names no blob: {len(ids)} given")
                cited.add(i)
                v = ids[i]
            out.append(v)
        holder[k] = out
    need(len(cited) == len(ids), "BAD_REQUEST", "every blob given is cited as blob:<i> in an evidence list: "
         f"blobs {sorted(set(range(len(ids))) - cited)} are not")
    return body, ids


def _inputs(ws, rtype, body, blobs):
    """(what the request gave, the body with its blobs cited by id, the blob ids)."""
    given = {"type": rtype, "body": body, **({"blobs": blobs} if blobs is not None else {})}
    if blobs is None:
        return given, body, []
    return (given, *_with_blobs(ws, rtype, body, blobs))


def prepare(ws, based_on, request_id, rtype, body, blobs=None):
    ws.permit("prepare")
    need(isinstance(rtype, str) and rtype in R.TYPES, "BAD_REQUEST", f"type is one of {list(R.TYPES)}")
    need(isinstance(body, dict), "BAD_REQUEST", "body is an object", template=TEMPLATES[rtype])
    given, body, blob_ids = _inputs(ws, rtype, body, blobs)
    if rtype == "transition" and "closes" not in body:
        body = dict(body, closes=[], **({} if "evidence" in body else {"evidence": []}))
    if request_id is None:
        # Without a request id the draft is named by what it would file: the same type and body give the
        # same draft (a retry), whatever view a later call would have captured.
        request_id = "auto:" + C.doc_id(given)
    need(isinstance(request_id, str) and 0 < len(request_id) <= 128, "BAD_REQUEST", "request_id")
    actor, key = _signer(ws)
    draft_id = C.doc_id({"workspace": ws.name, "request_id": request_id})
    path = ws.state / "drafts" / f"{draft_id}.json"
    inputs = C.doc_id(dict(given, based_on=based_on))
    if path.is_file():
        d = views.read_json(path)
        need(d["inputs"] == inputs, "CONFLICT", "request_id was prepared with other inputs")
        return d
    _, report, vdir = views.load(ws, views.capture(ws)["token"] if based_on is None else based_on)
    full = _accept_body(vdir, body) if rtype == "accept" else fill(rtype, body)
    # The signer's chain (SPEC §3): `prev` is its head in the live store, and `at` is never
    # before the head's; commit refuses the draft if the head has moved by then. The head is
    # read under the workspace's own trust: a record this workspace's reader rejects is never
    # a predecessor, and never moves the head (AMEND 1 of #174).
    head = Store(ws.store, verdicts=ws.state / "verdicts").head(actor, ws.trust())
    try:
        rec = R.record(rtype, actor, max(int(time.time()), head[1] if head else 0), full, prev=head[0] if head else None)
    except R.Invalid as e:
        raise AgentError("BAD_REQUEST", f"invalid {rtype}: {e}", template=TEMPLATES[rtype]) from None
    rid = R.record_id(rec)
    preview = {"type": rtype, "shape": "valid"}
    if rtype == "accept":
        t = report["results"].get(full["transition"])
        preview.update(accepts={"transition": full["transition"], "item": full["item"], "evidence": full["evidence"]},
                       transition_in_view=t is not None)
    d = {"draft_id": draft_id, "request_id": request_id, "workspace": ws.name, "inputs": inputs, "actor": actor,
         "key": key.id, "at": rec["at"], "record": rec, "record_id": rid,
         "basis_assessment_id": report["assessment_id"], "preview": preview, "status": "PREPARED"}
    if blobs is not None:                       # stored at commit, under the ids the record cites
        d["blobs"], preview["blobs"] = blobs, blob_ids
    views.write_json(path, d)
    return d


def _put_blobs(store, d):
    """The draft's blobs into the store, each under the id the draft's record cites. Content
    addressed: a commit refused after this (CHAIN_MOVED) leaves bytes no record names."""
    for doc, h in zip(d.get("blobs", []), d["preview"].get("blobs", [])):
        need(store.put_json(doc) == h, "CONFLICT", "a draft's blob is not the bytes it was prepared with")


def commit(ws, draft_id):
    ws.permit("commit")
    path, d = _draft(ws, draft_id)
    actor, key = _signer(ws)
    dst = ws.store / "records" / f"{d['record_id']}.json"
    store = Store(ws.store, verdicts=ws.state / "verdicts").init()
    if dst.is_file():
        why, rec = _authenticate(d["record_id"], dst.read_bytes(), ws.trust())
        if why or rec != d["record"]:
            raise AgentError("CONFLICT", "the store holds other bytes under this record id")
        _put_blobs(store, d)                    # a retry after a lost response finds them; stored again if not
    else:
        if (actor, key.id) != (d["actor"], d["key"]):
            raise AgentError("SIGNER_CHANGED", "the configured signer is not the one this draft was prepared for")
        _put_blobs(store, d)                    # before the record that cites them
        try:
            store.extend(d["record"], key, ws.trust())
        except ChainMoved as e:
            raise AgentError("CONFLICT", f"the signer's chain moved since this draft was prepared ({e}); "
                                         "prepare it again", reason="CHAIN_MOVED") from None
        except ValueError as e:         # a draft dated before the head it names: never filed unanchored
            raise AgentError("CONFLICT", f"{e}; prepare it again", reason="DATED_BEFORE_HEAD") from None
    if d["status"] != "COMMITTED":
        d["status"] = "COMMITTED"
        views.write_json(path, d)
    return {"draft_id": draft_id, "record_id": d["record_id"], "status": "COMMITTED",
            "basis_assessment_id": d["basis_assessment_id"]}


def status(ws, kind, target):
    need(isinstance(target, str) and target, "BAD_REQUEST", "target")
    if kind == "draft":
        _, d = _draft(ws, target)
        return {k: d[k] for k in ("draft_id", "record_id", "actor", "at", "status", "basis_assessment_id")}
    path = ws.state / "imports" / f"{C.digest(target.encode())}.json"
    need(path.is_file(), "NOT_FOUND", "no such operation")
    return views.read_json(path)
