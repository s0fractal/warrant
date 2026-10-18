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
import triggers as TR  # noqa: E402  (WRT-022 S1)
import replay as RP    # noqa: E402  (WRT-022 S2)
import grants as GR    # noqa: E402  (WRT-022 S3)

DUTY = "warrant.duty@draft-2"
TRANSITION = "warrant.transition@draft-2"
ACCEPTANCE = "warrant.acceptance@draft-2"
REPORT = "warrant.loops-report@draft-2"

KINDS = {"obligation", "goal", "commitment", "purpose"}
IMPLEMENTED_KINDS = {"obligation"}
SHAPES = {"one_shot", "recurring", "invariant"}
BASES = {"ATTESTED", "RUNNER_ATTESTED", "RECIPIENT_REEXECUTED", "REPLAYED"}
# The bases this profile can actually validate. A transition may CLAIM any basis
# in BASES; only these become an assessed basis. Runner, re-execution and replay
# evidence have no validator yet, so a candidate claiming them closes nothing
# (review WL01: a label is not a replay).
VALIDATED_BASES = {"ATTESTED"}
CLOSING = {"DISCHARGED", "DECLARED_IMPOSSIBLE", "RELEASED"}
ADMITTABLE = {"DISCHARGED", "DECLARED_IMPOSSIBLE", "OBSERVED"}
DISPOSITIONS = CLOSING | {"ABANDONED", "DELEGATED", "SUBSTITUTED", "OBSERVED", "REVALIDATED"}
ENDED = {"RELEASED", "ABANDONED", "DECLARED_IMPOSSIBLE"}
FLAGS = {"CONTESTED", "ORPHANED", "LAPSED", "BREACHED", "UNOBSERVED", "MISSING", "UNVERIFIED_CANDIDATE",
         "PENDING_ACCEPTANCE", "OVERCLAIMED_CANDIDATE"}

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SUBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")    # a git SHA-1 or a blob hash
EVALUATOR = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
PROFILE = "warrant.loops-profile@draft-2"
TRIGGER_DISPOSITIONS = {"DISCHARGED", "DECLARED_IMPOSSIBLE", "REVALIDATED"}
RELIANCE = {"ELIGIBLE", "STALE", "UNASSESSED", "NOT_CLOSED", "CONTESTED", "MISSING"}

DUTY_FIELDS = {"schema", "kind", "shape", "holder", "owed_to", "statement", "scope", "serves",
               "admits", "acceptance", "release_by"}
DUTY_OPTIONAL = {"period", "freshness", "answers", "closure_requires", "computation"}
TRANSITION_FIELDS = {"schema", "relied_on", "addresses", "did", "established", "closes", "opened",
                     "not_established", "scope"}
MAPPING_FIELDS = {"duty", "disposition", "evidence"}
MAPPING_OPTIONAL = {"instance", "to", "holds", "triggers", "revalidates"}
ACCEPTANCE_FIELDS = {"schema", "duty", "transition", "mapping", "evidence"}
ACCEPTANCE_OPTIONAL = {"support"}


def canon(doc):
    return W.canon(doc)


def blob_id(doc):
    return hashlib.sha256(canon(doc)).hexdigest()


# ---------------------------------------------------------------- authoring

def duty(holder, owed_to, statement, scope_subject, admits, acceptance=(), release_by=(),
         serves=(), kind="obligation", shape="one_shot", period=None, freshness=None, answers=None,
         closure_requires=None, computation=None):
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
    if closure_requires is not None:
        d["closure_requires"] = list(closure_requires)
    if computation is not None:
        d["computation"] = dict(computation)
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


def acceptance(duty_id, transition_id, index, evidence, support=None):
    a = {"schema": ACCEPTANCE, "duty": duty_id, "transition": transition_id, "mapping": index,
         "evidence": list(evidence)}
    if support is not None:
        a["support"] = list(support)
    return a


# ---------------------------------------------------------------- shapes

def _actors(v):
    return isinstance(v, list) and all(isinstance(a, str) and a for a in v)


def _hexes(v):
    return isinstance(v, list) and all(isinstance(h, str) and HEX64.match(h) for h in v)


def _int(v):
    return type(v) is int


def _enum(value, choices):
    """Check JSON types before set membership; arrays/objects are not enum values."""
    return isinstance(value, str) and value in choices


def duty_problem(d):
    """None if `d` is a well-formed duty blob, else the reason."""
    if not isinstance(d, dict) or d.get("schema") != DUTY:
        return "not a duty"
    keys = set(d)
    if not DUTY_FIELDS <= keys or keys - DUTY_FIELDS - DUTY_OPTIONAL:
        return "duty fields"
    if not _enum(d["kind"], KINDS) or not _enum(d["shape"], SHAPES):
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
            isinstance(p, list) and len(p) == 2 and _enum(p[0], ADMITTABLE) and _enum(p[1], BASES)
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
    if "closure_requires" in d and not (_hexes(d["closure_requires"]) and d["closure_requires"]):
        return "closure_requires"
    if "computation" in d:
        why = RP.computation_problem(d["computation"])
        if why:
            return why
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
            and _enum(did["basis"], BASES) and _hexes(did["evidence"])):
        return "did"
    if not isinstance(t["scope"], dict) or set(t["scope"]) - {"subject"}:
        return "scope"
    if "subject" in t["scope"] and not (isinstance(t["scope"]["subject"], str)
                                        and SUBJECT.fullmatch(t["scope"]["subject"])):
        return "scope subject"
    if not isinstance(t["closes"], list):
        return "closes"
    for m in t["closes"]:
        if not (isinstance(m, dict) and MAPPING_FIELDS <= set(m) <= MAPPING_FIELDS | MAPPING_OPTIONAL):
            return "mapping fields"
        if not (isinstance(m["duty"], str) and HEX64.match(m["duty"]) and _enum(m["disposition"], DISPOSITIONS)
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
        # A revalidation names exactly the earlier closures it revalidates; nothing else does.
        if (m["disposition"] == "REVALIDATED") != ("revalidates" in m):
            return "revalidates"
        if "revalidates" in m and not (_hexes(m["revalidates"]) and m["revalidates"]
                                       and len(set(m["revalidates"])) == len(m["revalidates"])):
            return "revalidates"
        if m["disposition"] == "REVALIDATED" and "instance" in m:
            return "a recurring instance is not revalidated"
        if "triggers" in m:
            why = TR.triggers_problem(m["triggers"])
            if why:
                return why
            # S1 assesses triggers on one-shot closures only. A recurring instance, an
            # observation, a transfer or a release that declared triggers is refused
            # explicitly, never accepted with its triggers dropped (S1-03).
            if m["triggers"] and (m["disposition"] not in TRIGGER_DISPOSITIONS or "instance" in m):
                return "triggers are supported on one-shot DISCHARGED or DECLARED_IMPOSSIBLE mappings only"
    return None


def acceptance_problem(a):
    if not (isinstance(a, dict) and a.get("schema") == ACCEPTANCE
            and ACCEPTANCE_FIELDS <= set(a) <= ACCEPTANCE_FIELDS | ACCEPTANCE_OPTIONAL):
        return "acceptance fields"
    if "support" in a and not (_hexes(a["support"]) and a["support"]):
        return "support"
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




def _resolves(store, h):
    """Evidence is available iff a blob with exactly these bytes is in the view."""
    p = store.blobs / h
    try:
        return p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest() == h
    except OSError:
        return False


# ---------------------------------------------------------------- assessment

VERDICTS = {"ADMITTED", "PENDING", "OVERCLAIMED", "UNVERIFIED_BASIS", "MISSING_EVIDENCE", "UNMET_CONDITION"}


class _View:
    def __init__(self, store, valid, as_of):
        self.store = store
        self.bodies = {}
        for wid in valid:
            env = W._loads_plain((store.records / f"{wid}.json").read_text())
            if env["body"]["ts"] <= as_of:          # the view ends at as_of
                self.bodies[wid] = env["body"]
        self.duties, self.transitions, self.acceptances = {}, {}, {}
        self.labels = {}          # (transition, mapping) -> validated replay label (S2)
        self.crossing_targets = []  # crossing targets the recipient's profile accepts (S2-01)
        self.verifiers = {}         # this assessment's verifier observation (S2-03)
        self.verifier_dir = None    # the captured bytes that observation is of, and that run (S2-04)
        self.grant_records = {}     # grant record -> (ts, grant) (S3)
        self.grants = GR.Grants({}, ())
        self.refused = {}
        for wid, body in sorted(self.bodies.items(), key=lambda kv: (kv[1]["ts"], kv[0])):
            self._admit(wid, body)

    def _admit(self, wid, body):
        doc = _blob(self.store, body["subject"]["hash"])
        schema = doc.get("schema") if doc else None
        kind = (body["decision"], schema)
        if kind == ("propose", DUTY):
            why = duty_problem(doc)
            if why is None and body["actor"]["id"] != doc["holder"]:
                why = "opened by someone other than the holder"
            self._file(wid, why, self.duties, doc)
        elif kind == ("propose", TRANSITION):
            self._file(wid, transition_problem(doc), self.transitions, (body, doc))
        elif kind == ("propose", GR.GRANT):
            why = GR.grant_problem(doc)
            if why is None and body["actor"]["id"] != doc["grantor"]:
                why = "a grant is signed by its grantor"
            if why:
                self.refused[wid] = why
            else:
                self.grant_records[wid] = (body["ts"], doc)
        elif kind == ("accept", ACCEPTANCE):
            why = acceptance_problem(doc)
            if why is None and not all(_resolves(self.store, h) for h in doc.get("support", [])):
                why = "the acceptor's support does not resolve"
            self._file(wid, why, self.acceptances, (body, doc))

    def _file(self, wid, why, table, value):
        if why:
            self.refused[wid] = why
        else:
            table[wid] = value

    def accepted_by(self, duty_id, t_id, index, evidence):
        """Actors whose acceptance binds exactly this duty, transition, mapping and evidence."""
        return {body["actor"]["id"] for body, a in self.acceptances.values()
                if a["duty"] == duty_id and a["transition"] == t_id and a["mapping"] == index
                and sorted(a["evidence"]) == sorted(evidence)}

    def accepted_at(self, duty_id, t_id, index, evidence):
        """{actor: position} of the EARLIEST acceptance by each actor that binds exactly
        this duty, transition, mapping and evidence. A position is (ts, record id)."""
        out = {}
        for wid, (body, a) in self.acceptances.items():
            if (a["duty"], a["transition"], a["mapping"]) == (duty_id, t_id, index) and \
                    sorted(a["evidence"]) == sorted(evidence):
                pos = (body["ts"], wid)
                actor = body["actor"]["id"]
                if actor not in out or pos < out[actor]:
                    out[actor] = pos
        return out

    def support(self, duty_id, t_id, index):
        return {body["actor"]["id"]: a["support"] for body, a in self.acceptances.values()
                if a["duty"] == duty_id and a["transition"] == t_id and a["mapping"] == index and "support" in a}


def _judge_transfer(view, did, d, state, actor, t_id, i, m):
    """DELEGATED and SUBSTITUTED. The outgoing holder files it, and the incoming
    actor accepts this exact mapping; a substitution also needs the creditor or
    release_by (review WL02: nobody acquires a duty they did not accept)."""
    if actor != state["holder"]:
        return "OVERCLAIMED", "only the holder transfers or delegates"
    accepted = view.accepted_by(did, t_id, i, m["evidence"])
    missing = []
    if m["to"] not in accepted:
        missing.append(f"{m['to']} (incoming)")
    if m["disposition"] == "SUBSTITUTED" and not accepted & (set(d["owed_to"]) | set(d["release_by"])):
        missing.append("the creditor or release_by")
    return ("PENDING", "waiting for " + ", ".join(missing)) if missing else ("ADMITTED", "")


def _shape_problem(d, m):
    disp = m["disposition"]
    if d["shape"] == "recurring" and "instance" not in m:
        return "a recurring duty is closed per instance"
    if disp == "OBSERVED" and d["shape"] != "invariant":
        return "only an invariant duty is observed"
    if disp != "OBSERVED" and d["shape"] == "invariant":
        return "an invariant duty is observed, not discharged"
    return None


def _unmet_children(d, done):
    """F5: a parent's closure condition may NAME child duties; it is evaluated,
    never inferred from `serves` or from whichever children exist."""
    unmet = [c for c in d.get("closure_requires", []) if done.get(c) != "DISCHARGED"]
    return ("UNMET_CONDITION", "named child duties not discharged: " + ", ".join(u[:12] for u in unmet)) \
        if unmet else None


def _judge_closure(view, did, d, state, actor, t, i, t_id, m, done):
    """DISCHARGED, DECLARED_IMPOSSIBLE, OBSERVED, and REVALIDATED, which is admitted
    exactly as a discharge on the same basis would be."""
    disp, claimed = m["disposition"], t["did"]["basis"]
    admit_as = "DISCHARGED" if disp == "REVALIDATED" else disp
    if actor not in {state["holder"]} | state["delegates"]:
        return "OVERCLAIMED", "filed by someone who does not hold the duty"
    if [admit_as, claimed] not in d["admits"]:
        return "OVERCLAIMED", f"{admit_as} on {claimed} is not admitted by this duty"
    if claimed == "REPLAYED":
        # WRT-022 S2: the recipient re-runs the receipt's computation with a pinned
        # verifier, in this view; the receipt's word is never the basis.
        label, why = RP.validate(view.store, lambda h: _blob(view.store, h), d.get("computation"), m["evidence"],
                                 view.crossing_targets, view.verifiers, view.verifier_dir)
        if label is None:
            return "UNVERIFIED_BASIS", f"REPLAYED is claimed and not validated here: {why}"
        view.labels[(t_id, i)] = label
    elif claimed not in VALIDATED_BASES:
        return "UNVERIFIED_BASIS", f"{claimed} is claimed; this profile cannot validate it, and a label is not the act"
    if not m["evidence"]:
        return "MISSING_EVIDENCE", "an attestation names the evidence it attests"
    shape = _shape_problem(d, m)
    if shape:
        return "OVERCLAIMED", shape
    if admit_as == "DISCHARGED":
        unmet = _unmet_children(d, done)
        if unmet:
            return unmet
    missing = set(d["acceptance"]) - view.accepted_by(did, t_id, i, m["evidence"])
    if missing:
        return "PENDING", "waiting for " + ", ".join(sorted(missing))
    return "ADMITTED", ""


def _judge(view, did, d, state, t_id, tbody, t, i, m, done):
    """Is mapping `m` of transition `t_id` admitted for duty `did`? One verdict from VERDICTS."""
    actor = tbody["actor"]["id"]
    disp = m["disposition"]
    if not all(_resolves(view.store, h) for h in m["evidence"]):
        return "MISSING_EVIDENCE", "cited evidence is not in the view, or its bytes do not match"
    if disp == "RELEASED":
        if actor in set(d["owed_to"]) | set(d["release_by"]):
            return "ADMITTED", ""
        # S3: a grant from an accepted root, attenuated at every edge, valid at the
        # release's own position. A key binding alone authorizes nothing.
        gid, why = GR.authorized(view.grants, actor, "release", did, tbody["ts"])
        return ("ADMITTED", f"by grant {gid[:12]}") if gid else ("OVERCLAIMED", f"not authorized to release: {why}")
    if disp == "ABANDONED":
        return "OVERCLAIMED", "an obligation cannot be abandoned by its holder"
    if disp in ("DELEGATED", "SUBSTITUTED"):
        return _judge_transfer(view, did, d, state, actor, t_id, i, m)
    if disp == "REVALIDATED":
        # It revalidates closures that are admitted, for this duty, earlier in
        # admission order; it never creates a closure of its own.
        if not state["admitted"]:
            return "OVERCLAIMED", "nothing admitted to revalidate"
        if not set(m["revalidates"]) <= set(state["admitted"]):
            return "OVERCLAIMED", "revalidates something that is not an admitted closure of this duty"
    return _judge_closure(view, did, d, state, actor, t, i, t_id, m, done)


def _admission_pos(view, did, d, t_id, tbody, i, m):
    """The position at which a mapping became admissible: the latest of its own
    transition and the earliest acceptance by each actor the duty requires, each as
    (ts, record id); None while a required acceptance is missing. Ties are broken by
    record id, so the order is total and the same in every view of the same records."""
    pos = (tbody["ts"], t_id)
    got = view.accepted_at(did, t_id, i, m["evidence"])
    for actor in d["acceptance"]:
        if actor not in got:
            return None
        pos = max(pos, got[actor])
    return pos


def _transfer_pos(view, did, d, t_id, tbody, i, m):
    """The position at which an admitted transfer took effect: the latest of its own
    transition, the incoming actor's earliest consent and, for a substitution, the
    earliest consent by the creditor or release_by (each as (ts, record id))."""
    got = view.accepted_at(did, t_id, i, m["evidence"])
    pos = max((tbody["ts"], t_id), got.get(m["to"], (tbody["ts"], t_id)))
    creditors = [got[a] for a in set(d["owed_to"]) | set(d["release_by"]) if a in got]
    if m["disposition"] == "SUBSTITUTED" and creditors:
        pos = max(pos, min(creditors))
    return pos


def _revalidation_order(view, did, d, state, t_id, tbody, i, m):
    """RV-01: a revalidation that is otherwise admissible is admitted only if every
    closure it names has an admission position strictly before its own."""
    mine = _admission_pos(view, did, d, t_id, tbody, i, m)
    late = [x for x in m["revalidates"] if not (state["admitted"].get(x) and state["admitted"][x] < mine)]
    if late:
        return "OVERCLAIMED", "revalidates a closure not admitted before it (admission order): " + \
            ", ".join(x[:12] for x in late)
    return "ADMITTED", ""


def _apply(d, state, acc, tbody, t_id, t, m, label):
    disp = m["disposition"]
    if disp == "DELEGATED":
        state["delegates"].add(m["to"])
    elif disp == "SUBSTITUTED":
        state["holder"], state["delegates"] = m["to"], set()
    elif disp == "OBSERVED":
        acc["observations"].append((tbody["ts"], m["holds"], t_id))
    elif d["shape"] == "recurring" and disp == "DISCHARGED":
        acc["instances"].setdefault(m["instance"], t_id)
    elif disp == "REVALIDATED":
        acc["revalidations"].append((t_id, tbody["actor"]["id"], t["scope"].get("subject"),
                                     m.get("triggers", []), label, m["revalidates"]))
    else:
        acc["closures"].append((disp, t_id, tbody["actor"]["id"], t["scope"].get("subject"),
                                m.get("triggers", []), label))



def _recurring(d, out, instances, as_of):
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


def _invariant(d, out, observations, as_of):
    out["disposition"] = "STANDING"
    fresh = [o for o in observations if as_of - o[0] <= d["freshness"]]
    if not fresh:
        out["flags"].append("UNOBSERVED")
    elif not max(fresh)[1]:
        out["flags"].append("BREACHED")
    out["observed"] = [{"ts": o[0], "holds": o[1], "transition": o[2]} for o in observations]


def _settle_disposition(out, closures, revalidations=()):
    kinds = sorted({c[0] for c in closures})
    if len(kinds) > 1:
        out["flags"].append("CONTESTED")
        out["disposition"] = None
        out["dispositions"] = kinds
    elif kinds:
        out["disposition"] = kinds[0]
        chosen = [c for c in closures if c[0] == kinds[0]]
        # The assessed basis says what was validated: whose attestation, or whose release.
        # Validated replays carry their own label (REPLAYED:<runtime>:<pinned verifier>,
        # valid in this view only); anything else is the actor's attestation or release.
        label = "RELEASE_BY" if kinds[0] == "RELEASED" else "ACTOR_ATTESTATION"
        out["assessed_basis"] = sorted({c[5] or f"{label}:{c[2]}" for c in chosen})
        # Revalidation: an admitted REVALIDATED supersedes, for PRESENT eligibility only,
        # the earlier closures it names. Their trigger DECLARATIONS stay in the report and
        # are re-evaluated in this view (current: false); that is not a frozen record of
        # what an earlier assessment observed. Nothing is erased (WRT-022 rev 2 §4.2).
        superseded = {x for rv in revalidations for x in rv[5]} if kinds[0] == "DISCHARGED" else set()
        items = [(c[1], c[3], c[4]) for c in chosen]
        if kinds[0] == "DISCHARGED":
            items += [(rv[0], rv[2], rv[3]) for rv in revalidations]
            out["revalidations"] = [{"transition": rv[0], "revalidates": rv[5],
                                     "assessed_basis": rv[4] or f"ACTOR_ATTESTATION:{rv[1]}"} for rv in revalidations]
        out["closure_scope"] = sorted({sc for tid, sc, _ in items if sc and tid not in superseded})
        out["declared_triggers"] = [{"closure": tid, "trigger": tr, "current": tid not in superseded}
                                    for tid, _, trs in items for tr in trs]
    out["closed_by"] = [c[1] for c in closures]


def _applicability(out, current):
    """F2: a closure is applicable to the revision it was ESTABLISHED on, not the
    revision the defect was found on; anything else is UNASSESSED, never invalid."""
    if current is None:
        return "NOT_ASKED"
    scopes = out.get("closure_scope") if out["closed_by"] else [out["scope"]]
    return "CURRENT" if any(s in current for s in scopes or []) else "UNASSESSED"


def _assess_duty(view, did, d, as_of, current, done):
    out = {"kind": d["kind"], "shape": d["shape"], "holder": d["holder"], "owed_to": d["owed_to"],
           "scope": d["scope"]["subject"], "disposition": "OPEN", "assessed_basis": [], "flags": [],
           "closed_by": [], "candidates": [], "delegates": [], "acceptance": d["acceptance"],
           "release_by": d["release_by"]}
    if d["kind"] not in IMPLEMENTED_KINDS:
        out["disposition"] = "NOT_IMPLEMENTED"
        return out
    state = {"holder": d["holder"], "delegates": set(), "admitted": {}}
    acc = {"closures": [], "instances": {}, "observations": [], "revalidations": []}
    mine = [(t_id, tbody, t, i, m) for t_id, (tbody, t) in sorted(view.transitions.items(),
                                                                   key=lambda kv: (kv[1][0]["ts"], kv[0]))
            for i, m in enumerate(t["closes"]) if m["duty"] == did]
    # Revalidations are judged after everything else, in the order of their OWN
    # admission positions (review RV-01): a revalidation is admitted only if every
    # closure it names was admitted strictly before it, by admission position.
    first = [x for x in mine if x[4]["disposition"] != "REVALIDATED"]
    reval = sorted((x for x in mine if x[4]["disposition"] == "REVALIDATED"),
                   key=lambda x: _admission_pos(view, did, d, x[0], x[1], x[3], x[4]) or (float("inf"), x[0]))
    # RV-02: who holds the duty is a function of position. The first pass records the
    # holder and delegates after each admitted transfer, at that transfer's admission
    # position; a revalidation is judged against the holder at its OWN position, so a
    # later transfer neither authorizes an earlier non-holder nor un-admits the then
    # holder's revalidation.
    timeline = [((-1, ""), d["holder"], frozenset())]
    final = None
    for t_id, tbody, t, i, m in first + reval:
        if m["disposition"] == "REVALIDATED":
            if final is None:
                final = (state["holder"], set(state["delegates"]))
            at = (tbody["ts"], t_id)
            _, h, dl = max((e for e in timeline if e[0] <= at), key=lambda e: e[0])
            state["holder"], state["delegates"] = h, set(dl)
        verdict, why = _judge(view, did, d, state, t_id, tbody, t, i, m, done)
        if verdict == "ADMITTED" and m["disposition"] == "REVALIDATED":
            verdict, why = _revalidation_order(view, did, d, state, t_id, tbody, i, m)
        cand = {"transition": t_id, "mapping": i, "disposition": m["disposition"],
                "claimed_basis": t["did"]["basis"], "verdict": verdict, "why": why}
        support = view.support(did, t_id, i)
        if support:
            cand["acceptor_support"] = support      # F4: the acceptor's own references, resolved
        out["candidates"].append(cand)
        if verdict == "ADMITTED":
            if m["disposition"] in ("DISCHARGED", "REVALIDATED"):
                state["admitted"][t_id] = _admission_pos(view, did, d, t_id, tbody, i, m)
            _apply(d, state, acc, tbody, t_id, t, m, view.labels.get((t_id, i)))
            if m["disposition"] in ("DELEGATED", "SUBSTITUTED"):
                timeline.append((_transfer_pos(view, did, d, t_id, tbody, i, m), state["holder"],
                                 frozenset(state["delegates"])))
    if final is not None:
        state["holder"], state["delegates"] = final
    out["holder"], out["delegates"] = state["holder"], sorted(state["delegates"])
    _settle_disposition(out, acc["closures"], acc["revalidations"])
    if d["shape"] == "recurring" and out["disposition"] == "OPEN":
        _recurring(d, out, acc["instances"], as_of)
    if d["shape"] == "invariant" and out["disposition"] == "OPEN":
        _invariant(d, out, acc["observations"], as_of)
    verdicts = {c["verdict"] for c in out["candidates"]}
    for verdict, flag in (("PENDING", "PENDING_ACCEPTANCE"), ("OVERCLAIMED", "OVERCLAIMED_CANDIDATE"),
                          ("UNVERIFIED_BASIS", "UNVERIFIED_CANDIDATE")):
        if verdict in verdicts:
            out["flags"].append(flag)
    out["applicability"] = _applicability(out, current)
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


def _assess_all(view, as_of, current):
    """Children named by closure_requires are assessed before their parent; a
    cycle leaves the condition unmet instead of recursing."""
    report, done, busy = {}, {}, set()

    def visit(did):
        if did in report or did in busy:
            return
        busy.add(did)
        for c in view.duties[did].get("closure_requires", []):
            if c in view.duties:
                visit(c)
        report[did] = _assess_duty(view, did, view.duties[did], as_of, current, done)
        done[did] = report[did]["disposition"]
        busy.discard(did)

    for did in sorted(view.duties):
        visit(did)
    return report


def _crossings(view):
    """S2: every crossing a transition cites, with its state or the reason it is refused.
    Being listed here gives a crossing no credit; only a validated replay does."""
    out = {}
    for _, t in view.transitions.values():
        for h in set(t["did"]["evidence"]):
            doc = _blob(view.store, h)
            if isinstance(doc, dict) and doc.get("schema") == RP.CROSSING:
                why = RP.crossing_problem(doc)
                out[h] = f"REFUSED: {why}" if why else RP.state(doc)
    return dict(sorted(out.items()))


def _questions(view):
    """F3: questions opened by transitions and taken on by no duty, with where they came from."""
    taken = {d["answers"] for d in view.duties.values() if "answers" in d}
    out = []
    for t_id, (tbody, t) in sorted(view.transitions.items()):
        for q in t["opened"]:
            if q not in taken:
                out.append({"question": q, "opened_by": t_id, "actor": tbody["actor"]["id"],
                            "scope": t["scope"].get("subject")})
    return out


def profile_problem(prof):
    """None if `prof` is a well-formed recipient profile, else the reason. A profile
    names the uses a recipient may rely on closures for, and what each use needs."""
    if not (isinstance(prof, dict) and {"schema", "uses"} <= set(prof) <= {"schema", "uses", "crossing_targets",
                                                                           "grant_roots"}
            and prof["schema"] == PROFILE):
        return "profile fields"
    gr = prof.get("grant_roots", [])
    if not (isinstance(gr, list) and all(isinstance(g, str) and HEX64.match(g) for g in gr) and len(set(gr)) == len(gr)):
        return "grant_roots"
    ct = prof.get("crossing_targets", [])
    if not (isinstance(ct, list) and all(isinstance(t, str) and t for t in ct) and len(set(ct)) == len(ct)):
        return "crossing_targets"
    uses = prof["uses"]
    if not (isinstance(uses, dict) and uses and all(isinstance(k, str) and k for k in uses)):
        return "profile uses"
    for need in uses.values():
        if not (isinstance(need, dict) and set(need) == {"requires_declared_triggers"}
                and type(need["requires_declared_triggers"]) is bool):
            return "use requirements"
    return None


def _evaluate_triggers(view, report, workspace):
    """After every duty is assessed: each declared trigger of each admitted closure,
    in this view. Results are kept per trigger, so several causes stay visible."""
    dispositions = {did: r["disposition"] for did, r in report.items()}
    for r in report.values():
        declared = r.pop("declared_triggers", [])
        r["triggers"] = []
        for item in declared:
            result, detail = TR.evaluate(item["trigger"], lambda h: _blob(view.store, h), workspace, dispositions)
            if result not in TR.RESULTS:
                raise ValueError(f"trigger result outside its vocabulary: {result}")
            r["triggers"].append({"closure": item["closure"], **item["trigger"], "result": result, "detail": detail,
                                  "current": item["current"]})
        if r["disposition"] == "DISCHARGED":
            cur = [t for t in r["triggers"] if t["current"]]
            r["trigger_coverage"] = "NO_DECLARED_TRIGGERS" if not cur else \
                {k: sum(t["result"] == k for t in cur) for k in sorted(TR.RESULTS)}


def assess(store_root, trust_path, as_of, current=None, workspace=None, profile=None):
    """Assess every duty in ONE snapshot of the store, under the recipient's trust
    snapshot, at `as_of`. `current`, if given, is the set of subjects the recipient
    treats as current (F2, review R5). `workspace` is (repo, commit): the recipient's
    current revision, against which `subject_changed` triggers are evaluated (WRT-022
    S1). `profile` is the recipient's named uses. Every operand that can change a
    result is in `view.assessment_id`."""
    if profile is not None and profile_problem(profile):
        raise ValueError(f"profile: {profile_problem(profile)}")
    trust_bytes = Path(trust_path).read_bytes()
    ws = TR.Workspace(*workspace) if workspace is not None else None
    with tempfile.TemporaryDirectory() as tmp:
        store, store_sha = _snapshot(store_root, Path(tmp) / "store")
        snap_trust = Path(tmp) / "trust.json"
        with snap_trust.open("wb") as f:
            f.write(trust_bytes)
        store_ok, bad = _integrity(store, snap_trust)
        ids = store_ids(store)
        valid = [w for w in ids if w not in bad] if store_ok else []
        view = _View(store, valid, as_of)
        view.crossing_targets = list((profile or {}).get("crossing_targets", []))
        view.grants = GR.Grants(view.grant_records, (profile or {}).get("grant_roots", []))
        view.verifiers, view.verifier_dir = RP.capture(Path(tmp) / "verifier")
        report = _assess_all(view, as_of, current)
        _orphan_and_missing(view, report)
        _evaluate_triggers(view, report, ws)
        dangling = sorted({m["duty"] for _, t in view.transitions.values() for m in t["closes"]
                           if m["duty"] not in view.duties})
        for r in report.values():
            unknown = (set(r["flags"]) - FLAGS) | ({c["verdict"] for c in r["candidates"]} - VERDICTS)
            if unknown:
                raise ValueError(f"value outside its vocabulary: {sorted(unknown)}")
        v = {"store_snapshot_sha256": store_sha,
             "trust_sha256": hashlib.sha256(trust_bytes).hexdigest(),
             "as_of": as_of, "evaluator": EVALUATOR, "trigger_evaluator": TR.EVALUATOR,
             "replay_evaluator": RP.EVALUATOR, "replay_verifiers": view.verifiers,
             "grant_evaluator": GR.EVALUATOR,
             "validated_bases": sorted(VALIDATED_BASES),
             "current": sorted(current) if current is not None else None,
             "workspace": ws.identity() if ws is not None else None,
             "profile_sha256": hashlib.sha256(canon(profile)).hexdigest() if profile is not None else None,
             "completeness": "UNATTESTED", "store_integrity": "VERIFIED" if store_ok else "INVALID"}
        v["assessment_id"] = hashlib.sha256(canon(v)).hexdigest()
        return {"schema": REPORT, "view": v, "profile": profile,
                "duties": report, "invalid_records": sorted(set(ids) - set(valid)),
                "refused_events": view.refused, "missing_duties": dangling,
                "unowned_questions": _questions(view), "crossings": _crossings(view),
                "grants": {g: view.grants.state(g, as_of)[0] for g in sorted(view.grant_records)},
                "questions_taken": {did: d["answers"] for did, d in view.duties.items() if "answers" in d}}


def frontier(rep, actor):
    """The actor's present (0010): duties it holds, is delegated, is owed, may
    release or must accept, that are open or flagged. Unowned questions are never
    in anyone's frontier; `questions()` shows them without making them anyone's."""
    out = []
    for did, r in sorted(rep["duties"].items()):
        involved = (actor == r["holder"] or actor in r["delegates"] or actor in r["owed_to"]
                    or actor in r["release_by"] or actor in r["acceptance"])
        if not involved:
            continue
        # A closed duty leaves the frontier unless a flag still asks for action; an
        # overclaimed candidate on a closed duty is history, kept in the report.
        open_like = r["disposition"] in ("OPEN", "RECURRING", "STANDING", None)
        live = open_like or bool(set(r["flags"]) - {"OVERCLAIMED_CANDIDATE", "UNVERIFIED_CANDIDATE"})
        if live:
            out.append({"duty": did, "disposition": r["disposition"], "flags": sorted(set(r["flags"])),
                        "question": rep["questions_taken"].get(did)})
    return out


def questions(rep, scope=None):
    """F3: the shared, read-only view of unowned questions, optionally for one scope.
    Listing a question here gives nobody a duty and nobody persistence authority."""
    return [q for q in rep["unowned_questions"] if scope is None or q["scope"] == scope]


def reliance_detail(rep, did, use=None):
    """WRT-022 S1: may a current action rely on this duty's closure, for `use`?

    Three judgments stay apart: the closure's historical validity (its disposition,
    never rewritten here), present eligibility (this answer) and trigger coverage.
    ELIGIBLE needs an uncontested DISCHARGED, a revision basis, and no trigger that
    FIRED or is UNEVALUABLE. The revision basis is either the closure being
    established on a revision the recipient treats as current, or a scoped
    `subject_changed` trigger that evaluated NOT_FIRED. NO_DECLARED_TRIGGERS is
    neutral: it neither satisfies nor skips the other requirements. Absence from
    someone's frontier is not this answer."""
    out = {"duty": did, "use": use, "assessment_id": rep["view"]["assessment_id"], "causes": []}
    r = rep["duties"].get(did)
    if r is None:
        return dict(out, state="MISSING")
    out["coverage"] = r.get("trigger_coverage")
    if "CONTESTED" in r["flags"]:
        return dict(out, state="CONTESTED")
    if r["disposition"] != "DISCHARGED":
        return dict(out, state="NOT_CLOSED")
    if use is not None:
        uses = (rep.get("profile") or {}).get("uses", {})
        if use not in uses:
            return dict(out, state="UNASSESSED", causes=[f"use {use!r} is not in the recipient profile"])
    # Present eligibility reads only the CURRENT closures' triggers: those no admitted
    # revalidation superseded. Superseded results remain in r["triggers"] as history.
    cur = [t for t in r["triggers"] if t.get("current", True)]
    if use is not None and uses[use]["requires_declared_triggers"] and not cur:
        return dict(out, state="UNASSESSED", causes=[f"use {use!r} requires declared triggers"])
    fired = [f"{t['kind']}: {t['detail']}" for t in cur if t["result"] == "FIRED"]
    if fired:
        return dict(out, state="STALE", causes=fired)
    unknown = [f"{t['kind']}: {t['detail']}" for t in cur if t["result"] == "UNEVALUABLE"]
    if unknown:
        return dict(out, state="UNASSESSED", causes=unknown)
    scoped = any(t["kind"] == "subject_changed" and t["result"] == "NOT_FIRED" for t in cur)
    if r["applicability"] != "CURRENT" and not scoped:
        return dict(out, state="UNASSESSED",
                    causes=["no revision basis: not established on a current revision, and no scoped subject trigger"])
    return dict(out, state="ELIGIBLE")


def reliance(rep, did, use=None):
    """The state of reliance_detail: one of RELIANCE."""
    state = reliance_detail(rep, did, use)["state"]
    if state not in RELIANCE:
        raise ValueError(f"reliance outside its vocabulary: {state}")
    return state
