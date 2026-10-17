#!/usr/bin/env python3
"""Decision assessment: DRAFT reference for phases P3/P4 of the sigma-warrant
redesign (Documents/Codex/2026-10-17/sigma-warrant-redesign, §13-§17).

NOT NORMATIVE. `warrant verify` is unchanged: it answers whether records are
well-formed, signed and bound. This module answers a different question, for a
recipient who names what they require: does this decision follow from a policy
they admit, computed on facts whose origin they accept?

The record of the draft current path cites three typed blobs in `under`:

    PolicyProgram   the reusable rule: typed parameters, one obligation, no fact values
    FactSet         the values for one case, each with its origin (observed / derived)
    CompilationPlan which registered compiler, with which options, emitted which check

and a `ski@v1` reason running that check. Separating rule from facts is D07; the
plan's explicit compiler and options are D08 (headroom no longer reads as "not
this policy"). The answer is replayed through warrant's own `run_ski_check` today
and can be read from a sigma-resume receipt later, through `replay_answer`.

The report has one axis per question (§16), each with a closed vocabulary, so a
signature is never mistaken for compliance and an unfinished run never for FALSE.
P4 adds a consequence identity for settlement (§17): only a replayed answer in an
admitted scope is a consequence; budget, wrappers, checkpoints, claimed verdicts
and arbitrary blobs are not.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import policy_lang as WPL  # noqa: E402
import warrant as W        # noqa: E402

SCHEMA_PROGRAM = "warrant.policy-program@draft-1"
SCHEMA_FACTS = "warrant.fact-set@draft-1"
SCHEMA_PLAN = "warrant.compilation-plan@draft-1"
SCHEMA_REPORT = "warrant.assessment@draft-1"
SCHEMA_OBSERVATION = "warrant.observation@draft-1"
RUNTIME = "ski@v1"

# Registered compilers. A plan that names anything else is refused, and nothing
# a package carries is ever executed (N44).
_POLICY_LANG_DIGEST = hashlib.sha256((HERE / "policy_lang.py").read_bytes()).hexdigest()
WPL_COMPILER_ID = f"wpl@v1/policy_lang.py@{_POLICY_LANG_DIGEST[:16]}"
COMPILERS = {WPL_COMPILER_ID: "wpl"}
COMPILE_OPTIONS = {"atp_headroom"}

# Closed vocabularies, one per axis.
AXES = {
    "record_integrity": {"VERIFIED", "INVALID"},
    "policy_authority": {"ADMITTED", "AUTHORITY_UNESTABLISHED", "NOT_ASSESSED"},
    "fact_provenance": {"ACCEPTED", "UNATTESTED", "DERIVATION_MISMATCH", "TYPE_MISMATCH", "NOT_ASSESSED"},
    "compilation_binding": {"MATCHED_COMPILATION", "COMPILATION_MISMATCH", "UNREGISTERED_COMPILER",
                            "NOT_ASSESSED"},
    "computation_verification": {"REPLAYED_NORMAL_FORM", "PAUSED", "BLOCKED_REFERENCE", "HOST_UNAVAILABLE",
                                 "NOT_ASSESSED"},
    "policy_answer": {"TRUE", "FALSE", "NON_BOOLEAN", "NOT_ASSESSED"},
    "decision_compliance": {"COMPLIANT", "CONTRADICTED_DECISION", "NOT_ASSESSED"},
    "required_profile": {"SATISFIED", "REQUIRED_PROFILE_NOT_SATISFIED"},
}


def _canon(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def blob_id(doc):
    return hashlib.sha256(_canon(doc)).hexdigest()


# ---------------------------------------------------------------- authoring

def program(obligation, params, rule):
    """params: {name: "int" | "bool"}; rule: a WPL check expression over them."""
    return {"schema": SCHEMA_PROGRAM, "obligation": obligation, "params": dict(sorted(params.items())),
            "rule": rule, "output": "boolean"}


def observation(obligation, name, value):
    """What an issuer attests: one value of one fact for one obligation. The
    FactSet then cites the attesting record (no cycle: the record does not
    name the FactSet)."""
    return {"schema": SCHEMA_OBSERVATION, "obligation": obligation, "fact": name, "value": value}


def observed(value, attested_by):
    return {"kind": "observed", "value": value, "attested_by": attested_by}


def derived(value, record, check):
    return {"kind": "derived", "value": value, "from": {"record": record, "check": check}}


def fact_set(obligation, facts):
    return {"schema": SCHEMA_FACTS, "obligation": obligation, "facts": dict(sorted(facts.items()))}


def wpl_source(prog, facts):
    """The WPL text a registered compiler is given: fact lines in name order,
    then the rule. Deterministic, so the check it emits is reproducible."""
    lines = []
    for name, typ in prog["params"].items():
        v = facts["facts"][name]["value"]
        if typ == "bool":
            lit = "true" if v else "false"
        else:
            lit = str(v)
        lines.append(f"fact {name}: {typ} = {lit}")
    return "\n".join(lines) + f"\ncheck {prog['rule']}\n"


def _compile(prog, facts, options, put):
    src = wpl_source(prog, facts)
    seen = {}

    def keep(b):
        h = put(b) if put else hashlib.sha256(b).hexdigest()
        seen[h] = b
        return h
    c = WPL.compile_source(src, keep, atp_headroom=options.get("atp_headroom", 0))
    return json.loads(seen[c.blob]), c.blob


def plan(prog, facts, options=None, put=None, compiler=WPL_COMPILER_ID):
    options = dict(options or {})
    check_doc, check = _compile(prog, facts, options, put)
    return {"schema": SCHEMA_PLAN, "policy_program_id": blob_id(prog), "fact_set_id": blob_id(facts),
            "compiler_id": compiler, "options": options, "runtime": RUNTIME,
            "emitted": {"check": check, "term": check_doc["term"], "expect": check_doc["expect"],
                        "atp": check_doc["atp"]}}


# ---------------------------------------------------------------- profile

def profile(admitted_programs, obligation, trust_config, fact_issuers, discretionary_reject,
            required="policy-decision", evidence_slots=None, semantics_class="ski@v1/wpl@v1"):
    """What THIS recipient requires. Nothing in a record or its store can widen it.

    `discretionary_reject` has no default: whether a rule that is satisfied
    merely PERMITS the action or OBLIGES it is the recipient's to say, every
    time (independent review, reject-when-TRUE)."""
    if type(discretionary_reject) is not bool:
        raise ValueError("discretionary_reject must be chosen explicitly: True or False")
    return {"admitted_programs": sorted(admitted_programs), "obligation": obligation,
            "trust_config": str(trust_config), "fact_issuers": sorted(fact_issuers),
            "discretionary_reject": discretionary_reject, "required": required,
            "evidence_slots": sorted(evidence_slots if evidence_slots is not None else []),
            "semantics_class": semantics_class}


# ---------------------------------------------------------------- reading

def _blob_json(store, h):
    p = store.blobs / h
    if not (isinstance(h, str) and p.is_file()):
        return None
    try:
        doc = json.loads(p.read_bytes())
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _typed_under(store, body):
    found = {}
    for h in body.get("under", []):
        doc = _blob_json(store, h)
        if doc and doc.get("schema") in (SCHEMA_PROGRAM, SCHEMA_FACTS, SCHEMA_PLAN):
            found[doc["schema"]] = (h, doc)
    return found


def _records(store):
    out = {}
    for p in sorted(store.records.glob("*.json")):
        try:
            out[p.stem] = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
    return out


def _record_integrity(store, trust_snapshot_path):
    r = subprocess.run([sys.executable, str(HERE / "warrant.py"), "--store", str(store.root), "verify",
                        "--settlement", "--require-bound", "--trust-config", str(trust_snapshot_path), "--json"],
                       capture_output=True, text=True, check=False)
    try:
        rep = json.loads(r.stdout)
    except ValueError:
        return "INVALID", ["verify produced no report"]
    errs = [f["message"] for f in rep.get("findings", []) if f.get("level") == "ERR"]
    return ("VERIFIED" if rep.get("errors") == 0 else "INVALID"), errs


def replay_answer(store, check):
    """(computation_verification, policy_answer). The one place a runtime is
    consulted: today warrant's pinned ski@v1 evaluator; later a sigma-resume
    receipt can be read here instead, with PAUSED and BLOCKED kept apart."""
    sg = W.load_sigma()
    if sg is None:
        return "HOST_UNAVAILABLE", "NOT_ASSESSED"
    try:
        _verdict, result_hash, _spent = W.run_ski_check(store, check)
    except RuntimeError:
        return "HOST_UNAVAILABLE", "NOT_ASSESSED"
    if result_hash == sg.node_hash(sg.ser(sg.DISSONANCE, sg.F_ATOM, atom=sg.R_ATP)).hex():
        return "PAUSED", "NOT_ASSESSED"
    if result_hash == sg.node_hash(sg.ser(sg.DISSONANCE, sg.F_ATOM, atom=sg.R_UNRES)).hex():
        return "BLOCKED_REFERENCE", "NOT_ASSESSED"
    true_h, false_h = sg.term_hash(sg.KG).hex(), sg.term_hash(("app", sg.KG, sg.IG)).hex()
    answer = {true_h: "TRUE", false_h: "FALSE"}.get(result_hash, "NON_BOOLEAN")
    return "REPLAYED_NORMAL_FORM", answer


# ---------------------------------------------------------------- axes

def _typed(value, typ):
    """Exact WPL types: a bool is not an int (review WA01)."""
    if typ == "bool":
        return type(value) is bool
    if typ == "int":
        return type(value) is int
    return False


def _observed_ok(name, f, facts, prof, trusted_bodies):
    rec = trusted_bodies.get(f.get("attested_by"))
    want = blob_id(observation(facts["obligation"], name, f.get("value")))
    return bool(rec and rec.get("actor", {}).get("id") in prof["fact_issuers"]
                and rec.get("subject", {}).get("hash") == want and rec.get("decision") == "accept")


def _derived_problem(store, records, name, f, typ):
    """Only Boolean derivation is supported: the cited record's own ski@v1 reason,
    claiming pass, must replay to exactly this bool. A number cannot be derived
    from a Boolean answer (review WA01), so a non-bool derived fact is refused."""
    if typ != "bool" or type(f.get("value")) is not bool:
        return f"{name}: only Boolean derived facts are supported; {typ} cannot come from a Boolean answer"
    src = f.get("from", {})
    rec = records.get(src.get("record"), {}).get("body", {})
    if not any(r.get("check") == src.get("check") and r.get("runtime") == RUNTIME and r.get("verdict") == "pass"
               for r in rec.get("because", [])):
        return f"{name}: the cited record does not run that check as a ski@v1 pass"
    comp, ans = replay_answer(store, src["check"])
    if comp != "REPLAYED_NORMAL_FORM" or ans != ("TRUE" if f["value"] is True else "FALSE"):
        return f"{name}: the cited check answers {ans}, not {f['value']}"
    return None


def _fact_provenance(store, records, prog, facts, prof, trusted_bodies):
    """ACCEPTED only if the facts are exactly the program's parameters with their
    exact types, and each is attested by an admitted issuer's bound record about
    exactly its value, or derived (Boolean only) from a record whose cited check
    replays to that value. An attestation says who vouched, not that the
    observation is true (N46)."""
    if set(facts["facts"]) != set(prog["params"]):
        return "TYPE_MISMATCH", "the fact set does not name exactly the program's parameters"
    for name, f in facts["facts"].items():
        typ = prog["params"][name]
        if not _typed(f.get("value"), typ):
            return "TYPE_MISMATCH", f"{name}: {type(f.get('value')).__name__} is not {typ}"
        kind = f.get("kind")
        if kind == "observed":
            if not _observed_ok(name, f, facts, prof, trusted_bodies):
                return "UNATTESTED", f"{name}: no admitted issuer attests this value"
        elif kind == "derived":
            problem = _derived_problem(store, records, name, f, typ)
            if problem:
                return "DERIVATION_MISMATCH", problem
        else:
            return "UNATTESTED", f"{name}: unknown fact kind"
    return "ACCEPTED", None


PLAN_FIELDS = {"schema", "policy_program_id", "fact_set_id", "compiler_id", "options", "runtime", "emitted"}
EMITTED_FIELDS = {"check", "term", "expect", "atp"}


def _plan_shape_problem(pl):
    if set(pl) != PLAN_FIELDS or not isinstance(pl.get("emitted"), dict) or set(pl["emitted"]) != EMITTED_FIELDS:
        return "the plan's fields are not exactly the schema's"
    if pl.get("runtime") != RUNTIME:
        return f"the plan names runtime {pl.get('runtime')!r}; this verifier runs {RUNTIME}"
    opts = pl.get("options")
    if not isinstance(opts, dict) or set(opts) - COMPILE_OPTIONS or any(
            type(v) is not int or v < 0 for v in opts.values()):
        return "unsupported or malformed compiler options"
    return None


def _compilation_binding(body, prog, facts, pl):
    """MATCHED_COMPILATION only if EVERYTHING the plan states is what recompiling
    it emits: runtime, check, term, expect and atp, under its declared options
    (review WA05). A claim the verifier did not check is not left in the plan."""
    if pl.get("compiler_id") not in COMPILERS:
        return "UNREGISTERED_COMPILER", f"{pl.get('compiler_id')!r} is not a compiler this verifier runs"
    shape = _plan_shape_problem(pl)
    if shape:
        return "COMPILATION_MISMATCH", shape
    if pl.get("policy_program_id") != blob_id(prog) or pl.get("fact_set_id") != blob_id(facts):
        return "COMPILATION_MISMATCH", "the plan names another program or fact set"
    try:
        doc, check = _compile(prog, facts, pl["options"], None)
    except (WPL.PolicyError, WPL.CompilerBug) as e:
        return "COMPILATION_MISMATCH", f"does not compile: {str(e)[:80]}"
    emitted = pl["emitted"]
    if (emitted["check"], emitted["term"], emitted["expect"], emitted["atp"]) != (check, doc["term"], doc["expect"], doc["atp"]):
        return "COMPILATION_MISMATCH", "recompiling the plan does not emit what it states"
    if not any(r.get("runtime") == RUNTIME and r.get("check") == check and r.get("verdict") == "pass"
               for r in body.get("because", [])):
        return "COMPILATION_MISMATCH", "no ski@v1 reason runs the plan's check"
    return "MATCHED_COMPILATION", None


def decide(decision, answer, discretionary_reject):
    """The recipient's Boolean profile (§16): answer x decision -> compliance."""
    if answer not in ("TRUE", "FALSE"):
        return "NOT_ASSESSED"
    if decision == "accept":
        return "COMPLIANT" if answer == "TRUE" else "CONTRADICTED_DECISION"
    if decision == "reject":
        return "COMPLIANT" if answer == "FALSE" or discretionary_reject else "CONTRADICTED_DECISION"
    return "NOT_ASSESSED"


def _assess_typed(store, records, body, typed, prof, integrity, axes, why):
    """Fill the policy axes for a record that cites program, facts and plan.
    Returns the record's scope and its named-slot facts, for settlement."""
    (p_id, prog), (_, facts), (_, pl) = typed[SCHEMA_PROGRAM], typed[SCHEMA_FACTS], typed[SCHEMA_PLAN]
    admitted = (p_id in prof["admitted_programs"] and prog.get("obligation") == prof["obligation"]
                and facts.get("obligation") == prof["obligation"])
    axes["policy_authority"] = "ADMITTED" if admitted else "AUTHORITY_UNESTABLISHED"
    trusted_bodies = {k: v["body"] for k, v in records.items()} if integrity == "VERIFIED" else {}
    axes["fact_provenance"], why["fact_provenance"] = _fact_provenance(store, records, prog, facts, prof, trusted_bodies)
    axes["compilation_binding"], why["compilation_binding"] = _compilation_binding(body, prog, facts, pl)
    if axes["compilation_binding"] == "MATCHED_COMPILATION":
        axes["computation_verification"], axes["policy_answer"] = replay_answer(store, pl["emitted"]["check"])
    gates = (integrity == "VERIFIED" and axes["policy_authority"] == "ADMITTED"
             and axes["fact_provenance"] == "ACCEPTED" and axes["compilation_binding"] == "MATCHED_COMPILATION")
    if gates:
        axes["decision_compliance"] = decide(body.get("decision"), axes["policy_answer"], prof["discretionary_reject"])
    scope = {"obligation": prog.get("obligation"), "semantics_class": f"{pl.get('runtime')}/wpl@v1"}
    slots = {name: {"value": f.get("value"), "source": f.get("attested_by") or f.get("from")}
             for name, f in facts.get("facts", {}).items() if name in prof["evidence_slots"]}
    return scope, slots


def assess(store_root, record_id, prof):
    """Assess one record for one recipient. The trust config is read ONCE; that
    snapshot is what verification uses and what the context names, so a change
    of the file after (or during) the assessment cannot be hidden (review WA04)."""
    store = W.Store(str(store_root))
    records = _records(store)
    env = records.get(record_id)
    if env is None:
        raise KeyError(record_id)
    body = env["body"]
    trust_bytes = Path(prof["trust_config"]).read_bytes()
    axes = dict.fromkeys(("policy_authority", "fact_provenance", "compilation_binding",
                          "computation_verification", "policy_answer", "decision_compliance"), "NOT_ASSESSED")
    why = {}
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "trust.json"
        snapshot.write_bytes(trust_bytes)
        integrity, errs = _record_integrity(store, snapshot)
    axes["record_integrity"] = integrity
    if errs:
        why["record_integrity"] = errs[:3]
    typed = _typed_under(store, body)
    has_all = all(s in typed for s in (SCHEMA_PROGRAM, SCHEMA_FACTS, SCHEMA_PLAN))
    axes["required_profile"] = "SATISFIED" if (has_all or prof["required"] == "witness") else \
        "REQUIRED_PROFILE_NOT_SATISFIED"
    scope, slots = (None, {})
    if has_all:
        scope, slots = _assess_typed(store, records, body, typed, prof, integrity, axes, why)
    admitted = (axes["required_profile"] == "SATISFIED" and axes["decision_compliance"] == "COMPLIANT"
                and body.get("decision") == "accept")
    bad = [k for k, v in axes.items() if v not in AXES[k]]
    if bad:
        raise ValueError(f"axis value outside its vocabulary: {bad}")
    trust_sha = hashlib.sha256(trust_bytes).hexdigest()
    return {"schema": SCHEMA_REPORT, "record": record_id, "axes": axes,
            "why": {k: v for k, v in why.items() if v}, "consumer_admits_action": admitted,
            "profile_id": blob_id(prof), "scope": scope, "slots": slots, "trust_sha256": trust_sha,
            "context_id": context_id(store, prof, records, trust_sha)}


def context_id(store, prof, records, trust_sha):
    """What this verdict rests on: the verifier build, the recipient profile, the
    exact trust bytes it used, and each record's envelope snapshot (body AND the
    signatures present), not file names (review WA04). Unsigned; a signature over
    it would only attest it."""
    build = hashlib.sha256((HERE / "assessment.py").read_bytes() + (HERE / "warrant.py").read_bytes()
                           + (HERE / "policy_lang.py").read_bytes()).hexdigest()
    envelopes = sorted(envelope_snapshot_id(e) for e in records.values() if isinstance(e, dict) and "body" in e)
    return blob_id({"verifier_build": build, "profile_id": blob_id(prof), "trust_sha256": trust_sha,
                    "envelopes": envelopes, "runtime": RUNTIME})


# ---------------------------------------------------------------- P4: settlement

def consequence(report, prof):
    """The settled meaning of an assessment, or None.

    Settlement-eligible only if the report was made under THIS recipient's
    profile, the record verified, the facts are accepted, the required profile is
    met, the compilation matched in the admitted scope, and a normal form was
    replayed (review WA02). Compliance is NOT required: a correctly obtained
    FALSE is a consequence even when an accept contradicts it. How the answer was
    reached (term syntax, headroom, budget, checkpoints, claimed verdict) is not
    part of it (§17, D09)."""
    a = report["axes"]
    eligible = (report.get("profile_id") == blob_id(prof) and a["record_integrity"] == "VERIFIED"
                and a["fact_provenance"] == "ACCEPTED" and a["required_profile"] == "SATISFIED"
                and a["policy_authority"] == "ADMITTED" and a["compilation_binding"] == "MATCHED_COMPILATION"
                and a["computation_verification"] == "REPLAYED_NORMAL_FORM"
                and a["policy_answer"] in ("TRUE", "FALSE"))
    if not eligible:
        return None
    return (report["scope"]["semantics_class"], report["scope"]["obligation"], a["policy_answer"])


def novelty(settled_report, candidate_report, prof):
    """May `candidate_report` reopen a matter settled by `settled_report`?

    Checked in this order (review WA03: scope before anything else):
    MIGRATION_REQUIRED  the candidate runs another semantics class
    SCOPE_MISMATCH      another obligation than the recipient's
    NO_NEW_CONSEQUENCE  the candidate is not settlement-eligible (see consequence)
    NEW_CONSEQUENCE     a different replayed answer in the same scope
    NEW_EVIDENCE        the same answer, but an ACCEPTED fact in a slot the
                        recipient names has a new value or source
    NO_NEW_CONSEQUENCE  anything else: progress, wrappers, budget, checkpoints,
                        claimed expectations, unnamed blobs, a renamed tuple"""
    scope = candidate_report.get("scope") or {}
    if scope.get("semantics_class") is not None and scope.get("semantics_class") != prof["semantics_class"]:
        return "MIGRATION_REQUIRED"
    if scope.get("obligation") != prof["obligation"]:
        return "SCOPE_MISMATCH"
    settled, candidate = consequence(settled_report, prof), consequence(candidate_report, prof)
    if candidate is None or settled is None:
        return "NO_NEW_CONSEQUENCE"
    if candidate[2] != settled[2]:
        return "NEW_CONSEQUENCE"
    if candidate_report.get("slots") != settled_report.get("slots"):
        return "NEW_EVIDENCE"
    return "NO_NEW_CONSEQUENCE"


# ---------------------------------------------------------------- P6: one current path

CURRENT_PROFILE = "warrant.decision@draft-1"
UNSUPPORTED_HISTORICAL_PROFILE = "UNSUPPORTED_HISTORICAL_PROFILE"


def write_decision(store, decision, subject, prog, facts, pl, actor, key_path, ts, note="decision"):
    """The ONE writer of the draft current path: a decision cites its program,
    facts and plan, and runs the plan's check. There is no option to write the
    old shape; the old shape is only ever read (D11)."""
    for doc, schema in ((prog, SCHEMA_PROGRAM), (facts, SCHEMA_FACTS), (pl, SCHEMA_PLAN)):
        if doc.get("schema") != schema:
            raise ValueError(f"expected {schema}")
    under = [store.put_blob(_canon(d)) for d in (prog, facts, pl)]
    body = {"warrant": "0.2", "decision": decision, "subject": {"hash": subject, "note": note},
            "under": under, "because": [{"kind": "check", "check": pl["emitted"]["check"],
                                         "runtime": RUNTIME, "verdict": "pass"}],
            "evidence": [], "actor": {"id": actor}, "prior": [], "ts": ts}
    return store.put_record({"body": body, "sigs": [W.sign_envelope(body, actor, str(key_path))]})


def read_current(store, record_id):
    """The current reader. A record of any other shape is refused by name, with
    its exact identity, and its bytes are left as they are: no silent fallback to
    an old evaluator, no re-signing, no reinterpretation (N66)."""
    p = W.Store(str(store.root)).records / f"{record_id}.json"
    raw = p.read_bytes()
    body = json.loads(raw)["body"]
    typed = _typed_under(store, body)
    if all(s in typed for s in (SCHEMA_PROGRAM, SCHEMA_FACTS, SCHEMA_PLAN)):
        return {"profile": CURRENT_PROFILE, "record": record_id}
    return {"profile": UNSUPPORTED_HISTORICAL_PROFILE, "record": record_id,
            "basis": {"warrant_id": W.warrant_id(body), "bytes_sha256": hashlib.sha256(raw).hexdigest()},
            "hint": "verify it with the historical verifier pack; the current path does not run it"}


def envelope_snapshot_id(envelope):
    """Identity of a body AND the signatures present at one moment. The
    WarrantID names the body only, so it cannot show which co-signatures existed
    when an assessment relied on them (§19, N67)."""
    sigs = sorted(envelope.get("sigs", []), key=lambda s: json.dumps(s, sort_keys=True))
    return blob_id({"body_id": W.warrant_id(envelope["body"]), "sigs": sigs})
