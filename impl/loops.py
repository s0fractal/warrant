#!/usr/bin/env python3
"""WRT-021 draft-2 profile: duties, transitions with a residual, and their
assessment under a named view. The obligation slice only (engineering decision
D2, 2026-10-17); goal, commitment and purpose are recognized and reported as
NOT_IMPLEMENTED.

DRAFT. This is a profile over the existing record body: it changes nothing that
`warrant verify` decides. A record is admitted here only if settlement-grade
verification (with --require-bound, under the recipient's trust snapshot) finds
no error attributed to it, or to the store.

Events, each a signed record whose subject is a closed-schema JSON blob:

  open        propose  subject = warrant.duty@draft-2        actor = the holder
  transition  propose  subject = warrant.transition@draft-2  actor = who did it
  acceptance  accept   subject = warrant.acceptance@draft-2  actor = who accepts

`prior` carries traversal only; every relation's meaning is in the typed blob
(proposal §4.4).
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import warrant as W  # noqa: E402

DUTY = "warrant.duty@draft-2"
TRANSITION = "warrant.transition@draft-2"
ACCEPTANCE = "warrant.acceptance@draft-2"
REPORT = "warrant.loops-report@draft-2"

KINDS = {"obligation", "goal", "commitment", "purpose"}
IMPLEMENTED_KINDS = {"obligation"}
SHAPES = {"one_shot", "recurring", "invariant"}
BASES = {"ATTESTED", "RUNNER_ATTESTED", "RECIPIENT_REEXECUTED", "REPLAYED"}
CLOSING = {"DISCHARGED", "DECLARED_IMPOSSIBLE", "RELEASED"}
ADMITTABLE = {"DISCHARGED", "DECLARED_IMPOSSIBLE", "OBSERVED"}
DISPOSITIONS = CLOSING | {"ABANDONED", "DELEGATED", "SUBSTITUTED", "OBSERVED"}
ENDED = {"RELEASED", "ABANDONED", "DECLARED_IMPOSSIBLE"}
FLAGS = {"CONTESTED", "ORPHANED", "LAPSED", "BREACHED", "UNOBSERVED", "MISSING",
         "PENDING_ACCEPTANCE", "OVERCLAIMED_CANDIDATE"}

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SUBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")    # a git SHA-1 or a blob hash
EVALUATOR = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

DUTY_FIELDS = {"schema", "kind", "shape", "holder", "owed_to", "statement", "scope", "serves",
               "admits", "acceptance", "release_by"}
DUTY_OPTIONAL = {"period", "freshness", "answers"}
TRANSITION_FIELDS = {"schema", "relied_on", "addresses", "did", "established", "closes", "opened",
                     "not_established", "scope"}
MAPPING_FIELDS = {"duty", "disposition", "evidence"}
MAPPING_OPTIONAL = {"instance", "to", "holds"}
ACCEPTANCE_FIELDS = {"schema", "duty", "transition", "mapping", "evidence"}


def canon(doc):
    return W.canon(doc)


def blob_id(doc):
    return hashlib.sha256(canon(doc)).hexdigest()


# ---------------------------------------------------------------- authoring

def duty(holder, owed_to, statement, scope_subject, admits, acceptance=(), release_by=(),
         serves=(), kind="obligation", shape="one_shot", period=None, freshness=None, answers=None):
    d = {"schema": DUTY, "kind": kind, "shape": shape, "holder": holder, "owed_to": list(owed_to),
         "statement": statement, "scope": {"subject": scope_subject}, "serves": list(serves),
         "admits": [list(p) for p in admits], "acceptance": list(acceptance),
         "release_by": list(release_by)}
    if period is not None:
        d["period"] = dict(period)
    if freshness is not None:
        d["freshness"] = freshness
    if answers is not None:
        d["answers"] = answers
    return d


def mapping(duty_id, disposition, evidence=(), **extra):
    m = {"duty": duty_id, "disposition": disposition, "evidence": list(evidence)}
    m.update(extra)
    return m


def transition(basis, evidence, closes=(), addresses=(), relied_on=(), established=(), opened=(),
               not_established=(), scope_subject=None, runner=None):
    did = {"basis": basis, "evidence": list(evidence)}
    if runner is not None:
        did["runner"] = runner
    return {"schema": TRANSITION, "relied_on": list(relied_on), "addresses": list(addresses),
            "did": did, "established": list(established), "closes": list(closes),
            "opened": list(opened), "not_established": list(not_established),
            "scope": {"subject": scope_subject} if scope_subject else {}}


def acceptance(duty_id, transition_id, index, evidence):
    return {"schema": ACCEPTANCE, "duty": duty_id, "transition": transition_id, "mapping": index,
            "evidence": list(evidence)}


# ---------------------------------------------------------------- shapes

def _actors(v):
    return isinstance(v, list) and all(isinstance(a, str) and a for a in v)


def _hexes(v):
    return isinstance(v, list) and all(isinstance(h, str) and HEX64.match(h) for h in v)


def _int(v):
    return type(v) is int


def duty_problem(d):
    """None if `d` is a well-formed duty blob, else the reason."""
    if not isinstance(d, dict) or d.get("schema") != DUTY:
        return "not a duty"
    keys = set(d)
    if not DUTY_FIELDS <= keys or keys - DUTY_FIELDS - DUTY_OPTIONAL:
        return "duty fields"
    if d["kind"] not in KINDS or d["shape"] not in SHAPES:
        return "kind or shape"
    if not (isinstance(d["holder"], str) and d["holder"]):
        return "holder"
    if not all(_actors(d[f]) for f in ("owed_to", "acceptance", "release_by")):
        return "actor lists"
    if d["kind"] == "obligation" and not d["owed_to"]:
        return "an obligation is owed to someone"
    if not (isinstance(d["statement"], str) and len(d["statement"]) <= 200):
        return "statement"
    if not (isinstance(d["scope"], dict) and set(d["scope"]) == {"subject"}
            and isinstance(d["scope"]["subject"], str) and SUBJECT.match(d["scope"]["subject"])):
        return "scope must pin an exact subject"
    if not _hexes(d["serves"]):
        return "serves"
    if not (isinstance(d["admits"], list) and all(
            isinstance(p, list) and len(p) == 2 and p[0] in ADMITTABLE and p[1] in BASES
            for p in d["admits"])):
        return "admits"
    if d["shape"] == "recurring":
        p = d.get("period")
        if not (isinstance(p, dict) and set(p) == {"start", "every"} and _int(p["start"])
                and _int(p["every"]) and p["every"] > 0):
            return "a recurring duty needs period {start, every}"
    elif "period" in d:
        return "period on a non-recurring duty"
    if d["shape"] == "invariant":
        if not (_int(d.get("freshness")) and d["freshness"] > 0):
            return "an invariant duty needs freshness"
    elif "freshness" in d:
        return "freshness on a non-invariant duty"
    if "answers" in d and not (isinstance(d["answers"], str) and HEX64.match(d["answers"])):
        return "answers"
    return None


def transition_problem(t):
    if not isinstance(t, dict) or t.get("schema") != TRANSITION or set(t) != TRANSITION_FIELDS:
        return "transition fields"
    for f in ("relied_on", "addresses", "established", "opened"):
        if not _hexes(t[f]):
            return f
    if not (isinstance(t["not_established"], list) and all(isinstance(s, str) for s in t["not_established"])):
        return "not_established"
    did = t["did"]
    if not (isinstance(did, dict) and {"basis", "evidence"} <= set(did) <= {"basis", "evidence", "runner"}
            and did["basis"] in BASES and _hexes(did["evidence"])):
        return "did"
    if not isinstance(t["scope"], dict) or set(t["scope"]) - {"subject"}:
        return "scope"
    if not isinstance(t["closes"], list):
        return "closes"
    for m in t["closes"]:
        if not (isinstance(m, dict) and MAPPING_FIELDS <= set(m) <= MAPPING_FIELDS | MAPPING_OPTIONAL):
            return "mapping fields"
        if not (isinstance(m["duty"], str) and HEX64.match(m["duty"]) and m["disposition"] in DISPOSITIONS
                and _hexes(m["evidence"])):
            return "mapping"
        if not set(m["evidence"]) <= set(did["evidence"]):
            return "a mapping cites evidence the transition does not carry"
        if "instance" in m and not (_int(m["instance"]) and m["instance"] >= 0):
            return "instance"
        if (m["disposition"] in ("DELEGATED", "SUBSTITUTED")) != ("to" in m):
            return "to"
        if "to" in m and not (isinstance(m["to"], str) and m["to"]):
            return "to"
        if (m["disposition"] == "OBSERVED") != ("holds" in m) or ("holds" in m and type(m["holds"]) is not bool):
            return "holds"
    return None


def acceptance_problem(a):
    if not isinstance(a, dict) or a.get("schema") != ACCEPTANCE or set(a) != ACCEPTANCE_FIELDS:
        return "acceptance fields"
    if not (isinstance(a["duty"], str) and HEX64.match(a["duty"]) and isinstance(a["transition"], str)
            and HEX64.match(a["transition"]) and _int(a["mapping"]) and a["mapping"] >= 0
            and _hexes(a["evidence"])):
        return "acceptance values"
    return None


# ---------------------------------------------------------------- the view

def _snapshot(src_root, dst_root):
    """Copy records and blobs, reading each file once; symlinks are not followed.
    Everything after this reads only the snapshot (the #131 N1 lesson)."""
    src, dst = Path(src_root), W.Store(str(dst_root))
    dst.init()
    listing = []
    for kind in ("records", "blobs"):
        folder = src / kind
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if p.is_file() and not p.is_symlink():
                data = p.read_bytes()
                (dst.root / kind / p.name).write_bytes(data)
                listing.append(f"{kind}/{p.name} {hashlib.sha256(data).hexdigest()}")
    return dst, hashlib.sha256("\n".join(listing).encode()).hexdigest()


def _integrity(store, trust_path):
    """Settlement-grade verification under the trust snapshot. Returns
    (store_ok, {wid with an ERR}) -- a store-level ERR invalidates the view."""
    r = subprocess.run([sys.executable, str(Path(W.__file__).resolve()), "--store", str(store.root), "verify",
                        "--settlement", "--require-bound", "--trust-config", str(trust_path), "--json"],
                       capture_output=True, text=True, check=False)
    try:
        rep = json.loads(r.stdout)
    except ValueError:
        return False, set()
    bad = {f["subject"] for f in rep.get("findings", []) if f.get("level") == "ERR"}
    return not (bad - set(store_ids(store))), bad


def store_ids(store):
    return [p.stem for p in sorted(store.records.glob("*.json"))]


def _blob(store, h):
    """A canonical JSON object blob, or None: non-canonical bytes are not read,
    so one document cannot travel under two addresses."""
    if not (isinstance(h, str) and HEX64.match(h)):
        return None
    p = store.blobs / h
    if not p.is_file():
        return None
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != h:
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) and canon(doc) == raw else None


# ---------------------------------------------------------------- assessment

class _View:
    def __init__(self, store, valid, as_of):
        self.store = store
        self.bodies = {}
        for wid in valid:
            env = W._loads_plain((store.records / f"{wid}.json").read_text())
            if env["body"]["ts"] <= as_of:          # the view ends at as_of
                self.bodies[wid] = env["body"]
        self.duties, self.transitions, self.acceptances = {}, {}, {}
        self.refused = {}
        for wid, body in sorted(self.bodies.items(), key=lambda kv: (kv[1]["ts"], kv[0])):
            doc = _blob(store, body["subject"]["hash"])
            schema = doc.get("schema") if doc else None
            if body["decision"] == "propose" and schema == DUTY:
                why = duty_problem(doc)
                if why is None and body["actor"]["id"] != doc["holder"]:
                    why = "opened by someone other than the holder"
                if why:
                    self.refused[wid] = why
                else:
                    self.duties[wid] = doc
            elif body["decision"] == "propose" and schema == TRANSITION:
                why = transition_problem(doc)
                if why:
                    self.refused[wid] = why
                else:
                    self.transitions[wid] = (body, doc)
            elif body["decision"] == "accept" and schema == ACCEPTANCE:
                why = acceptance_problem(doc)
                if why:
                    self.refused[wid] = why
                else:
                    self.acceptances[wid] = (body, doc)

    def accepted_by(self, duty_id, t_id, index, evidence):
        """Actors whose acceptance binds exactly this duty, transition, mapping and evidence."""
        return {body["actor"]["id"] for body, a in self.acceptances.values()
                if a["duty"] == duty_id and a["transition"] == t_id and a["mapping"] == index
                and sorted(a["evidence"]) == sorted(evidence)}


def _judge(view, did, d, state, t_id, tbody, t, i, m):
    """Is mapping `m` of transition `t_id` admitted for duty `did`? Returns
    ("ADMITTED" | "PENDING" | "OVERCLAIMED" | "NOOP", reason)."""
    actor = tbody["actor"]["id"]
    disp = m["disposition"]
    closers = {state["holder"]} | state["delegates"]
    if disp == "RELEASED":
        return ("ADMITTED", "") if actor in set(d["owed_to"]) | set(d["release_by"]) else \
            ("OVERCLAIMED", "not authorized to release")
    if disp == "ABANDONED":
        return "OVERCLAIMED", "an obligation cannot be abandoned by its holder"
    if disp == "DELEGATED":
        return ("ADMITTED", "") if actor == state["holder"] else ("OVERCLAIMED", "only the holder delegates")
    if disp == "SUBSTITUTED":
        authority = set(d["owed_to"]) | set(d["release_by"])
        if view.accepted_by(did, t_id, i, m["evidence"]) & authority:
            return "ADMITTED", ""
        return "PENDING", "substitution needs the creditor or release_by"
    # DISCHARGED, DECLARED_IMPOSSIBLE, OBSERVED
    if actor not in closers:
        return "OVERCLAIMED", "filed by someone who does not hold the duty"
    if [disp, t["did"]["basis"]] not in d["admits"]:
        return "OVERCLAIMED", f"{disp} on {t['did']['basis']} is not admitted by this duty"
    if d["shape"] == "recurring" and "instance" not in m:
        return "OVERCLAIMED", "a recurring duty is closed per instance"
    if disp == "OBSERVED" and d["shape"] != "invariant":
        return "OVERCLAIMED", "only an invariant duty is observed"
    if disp != "OBSERVED" and d["shape"] == "invariant":
        return "OVERCLAIMED", "an invariant duty is observed, not discharged"
    missing = set(d["acceptance"]) - view.accepted_by(did, t_id, i, m["evidence"])
    if missing:
        return "PENDING", "waiting for " + ", ".join(sorted(missing))
    return "ADMITTED", ""


def _assess_duty(view, did, d, as_of, current):
    out = {"kind": d["kind"], "shape": d["shape"], "holder": d["holder"], "owed_to": d["owed_to"],
           "scope": d["scope"]["subject"], "disposition": "OPEN", "basis": None, "flags": [],
           "closed_by": [], "candidates": [], "delegates": [], "acceptance": d["acceptance"],
           "release_by": d["release_by"]}
    if d["kind"] not in IMPLEMENTED_KINDS:
        out["disposition"] = "NOT_IMPLEMENTED"
        return out
    state = {"holder": d["holder"], "delegates": set()}
    closures, instances, observations = [], {}, []
    for t_id, (tbody, t) in sorted(view.transitions.items(), key=lambda kv: (kv[1][0]["ts"], kv[0])):
        for i, m in enumerate(t["closes"]):
            if m["duty"] != did:
                continue
            verdict, why = _judge(view, did, d, state, t_id, tbody, t, i, m)
            out["candidates"].append({"transition": t_id, "mapping": i, "disposition": m["disposition"],
                                      "verdict": verdict, "why": why})
            if verdict != "ADMITTED":
                continue
            disp = m["disposition"]
            if disp == "DELEGATED":
                state["delegates"].add(m["to"])
            elif disp == "SUBSTITUTED":
                state["holder"], state["delegates"] = m["to"], set()
            elif disp == "OBSERVED":
                observations.append((tbody["ts"], m["holds"], t_id))
            elif d["shape"] == "recurring" and disp == "DISCHARGED":
                instances.setdefault(m["instance"], (t_id, t["did"]["basis"]))
            else:
                closures.append((disp, t_id, t["did"]["basis"]))
    out["holder"] = state["holder"]
    out["delegates"] = sorted(state["delegates"])
    kinds = sorted({c[0] for c in closures})
    if len(kinds) > 1:
        out["flags"].append("CONTESTED")
        out["disposition"] = None
        out["dispositions"] = kinds
    elif kinds:
        out["disposition"] = kinds[0]
        out["basis"] = sorted({c[2] for c in closures if c[0] == kinds[0]})
    out["closed_by"] = [c[1] for c in closures]
    if d["shape"] == "recurring" and out["disposition"] == "OPEN":
        out["disposition"] = "RECURRING"
        start, every = d["period"]["start"], d["period"]["every"]
        report = {}
        n = 0
        while start + n * every <= as_of:
            end = start + (n + 1) * every
            if n in instances:
                report[str(n)] = "COVERED"
            else:
                report[str(n)] = "LAPSED" if end <= as_of else "OPEN"
            n += 1
        out["instances"] = report
        if "LAPSED" in report.values():
            out["flags"].append("LAPSED")
    if d["shape"] == "invariant" and out["disposition"] == "OPEN":
        out["disposition"] = "STANDING"
        fresh = [o for o in observations if as_of - o[0] <= d["freshness"]]
        if not fresh:
            out["flags"].append("UNOBSERVED")
        elif not max(fresh)[1]:
            out["flags"].append("BREACHED")
        out["observed"] = [{"ts": o[0], "holds": o[1], "transition": o[2]} for o in observations]
    if any(c["verdict"] == "PENDING" for c in out["candidates"]):
        out["flags"].append("PENDING_ACCEPTANCE")
    if any(c["verdict"] == "OVERCLAIMED" for c in out["candidates"]):
        out["flags"].append("OVERCLAIMED_CANDIDATE")
    if current is None:
        out["applicability"] = "NOT_ASKED"
    else:
        out["applicability"] = "CURRENT" if d["scope"]["subject"] in current else "UNASSESSED"
    return out


def _orphan_and_missing(view, report):
    for did, d in view.duties.items():
        r = report[did]
        parents = d["serves"]
        if not parents:
            continue                    # a root duty is never orphaned (review R2)
        if any(p not in report for p in parents):
            r["flags"].append("MISSING")
            continue
        if all(report[p]["disposition"] in ENDED for p in parents):
            r["flags"].append("ORPHANED")


def assess(store_root, trust_path, as_of, current=None):
    """Assess every duty in ONE snapshot of the store, under the recipient's trust
    snapshot, at `as_of`. `current`, if given, is the set of subjects the recipient
    treats as current; a duty scoped elsewhere keeps its disposition and is
    UNASSESSED for applicability (review R5)."""
    trust_bytes = Path(trust_path).read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        store, store_sha = _snapshot(store_root, Path(tmp) / "store")
        snap_trust = Path(tmp) / "trust.json"
        with snap_trust.open("wb") as f:
            f.write(trust_bytes)
        store_ok, bad = _integrity(store, snap_trust)
        ids = store_ids(store)
        valid = [w for w in ids if w not in bad] if store_ok else []
        view = _View(store, valid, as_of)
        report = {did: _assess_duty(view, did, d, as_of, current) for did, d in view.duties.items()}
        _orphan_and_missing(view, report)
        dangling = sorted({m["duty"] for _, t in view.transitions.values() for m in t["closes"]
                           if m["duty"] not in view.duties})
        unowned = sorted({q for _, t in view.transitions.values() for q in t["opened"]}
                         - {d["answers"] for d in view.duties.values() if "answers" in d})
        for r in report.values():
            unknown = set(r["flags"]) - FLAGS
            if unknown:
                raise ValueError(f"flag outside its vocabulary: {sorted(unknown)}")
        return {"schema": REPORT,
                "view": {"store_snapshot_sha256": store_sha,
                         "trust_sha256": hashlib.sha256(trust_bytes).hexdigest(),
                         "as_of": as_of, "evaluator": EVALUATOR,
                         "completeness": "UNATTESTED", "store_integrity": "VERIFIED" if store_ok else "INVALID"},
                "duties": report, "invalid_records": sorted(set(ids) - set(valid)),
                "refused_events": view.refused, "missing_duties": dangling,
                "unowned_questions": unowned,
                "questions_taken": {did: d["answers"] for did, d in view.duties.items() if "answers" in d}}


def frontier(rep, actor):
    """The actor's present (0010): duties it holds, is delegated, is owed or may
    release that are open or flagged, and candidates waiting for its acceptance.
    Unowned questions are never in anyone's frontier."""
    out = []
    for did, r in sorted(rep["duties"].items()):
        involved = (actor == r["holder"] or actor in r["delegates"] or actor in r["owed_to"]
                    or actor in r["release_by"] or actor in r["acceptance"])
        if not involved:
            continue
        # A closed duty leaves the frontier unless a flag still asks for action; an
        # overclaimed candidate on a closed duty is history, kept in the report.
        open_like = r["disposition"] in ("OPEN", "RECURRING", "STANDING", None)
        live = open_like or bool(set(r["flags"]) - {"OVERCLAIMED_CANDIDATE"})
        if live:
            out.append({"duty": did, "disposition": r["disposition"], "flags": sorted(set(r["flags"])),
                        "question": rep["questions_taken"].get(did)})
    return out
