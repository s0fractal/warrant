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
    "fact_provenance": {"ACCEPTED", "UNATTESTED", "DERIVATION_MISMATCH", "NOT_ASSESSED"},
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

def profile(admitted_programs, obligation, trust_config, fact_issuers, discretionary_reject=True,
            required="policy-decision", evidence_slots=None, semantics_class="ski@v1/wpl@v1"):
    """What THIS recipient requires. Nothing in a record or its store can widen it."""
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


def _record_integrity(store, trust_config):
    r = subprocess.run([sys.executable, str(HERE / "warrant.py"), "--store", str(store.root), "verify",
                        "--settlement", "--require-bound", "--trust-config", str(trust_config), "--json"],
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

def _observed_ok(name, f, facts, prof, trusted_bodies):
    rec = trusted_bodies.get(f.get("attested_by"))
    want = blob_id(observation(facts["obligation"], name, f.get("value")))
    return bool(rec and rec.get("actor", {}).get("id") in prof["fact_issuers"]
                and rec.get("subject", {}).get("hash") == want and rec.get("decision") == "accept")


def _derived_problem(store, records, name, f):
    src = f.get("from", {})
    rec = records.get(src.get("record"), {}).get("body", {})
    if not any(r.get("check") == src.get("check") for r in rec.get("because", [])):
        return f"{name}: the cited record does not run that check"
    comp, ans = replay_answer(store, src["check"])
    if comp != "REPLAYED_NORMAL_FORM" or ans != ("TRUE" if f.get("value") else "FALSE"):
        return f"{name}: the cited check answers {ans}, not {f.get('value')}"
    return None


def _fact_provenance(store, records, facts, prof, trusted_bodies):
    """ACCEPTED only if every fact is attested by an admitted issuer's bound
    record about exactly its value, or derived from a record whose cited check
    replays to that value. An attestation says who vouched, not that the
    observation is true (N46)."""
    for name, f in facts["facts"].items():
        kind = f.get("kind")
        if kind == "observed":
            if not _observed_ok(name, f, facts, prof, trusted_bodies):
                return "UNATTESTED", f"{name}: no admitted issuer attests this value"
        elif kind == "derived":
            problem = _derived_problem(store, records, name, f)
            if problem:
                return "DERIVATION_MISMATCH", problem
        else:
            return "UNATTESTED", f"{name}: unknown fact kind"
    return "ACCEPTED", None


def _compilation_binding(body, prog, facts, pl):
    if pl.get("compiler_id") not in COMPILERS:
        return "UNREGISTERED_COMPILER", f"{pl.get('compiler_id')!r} is not a compiler this verifier runs"
    if set(pl.get("options", {})) - COMPILE_OPTIONS:
        return "COMPILATION_MISMATCH", "unsupported compiler options"
    if pl.get("policy_program_id") != blob_id(prog) or pl.get("fact_set_id") != blob_id(facts):
        return "COMPILATION_MISMATCH", "the plan names another program or fact set"
    try:
        doc, check = _compile(prog, facts, pl["options"], None)
    except (WPL.PolicyError, WPL.CompilerBug) as e:
        return "COMPILATION_MISMATCH", f"does not compile: {str(e)[:80]}"
    if check != pl["emitted"]["check"] or doc["term"] != pl["emitted"]["term"]:
        return "COMPILATION_MISMATCH", "recompiling the plan does not emit its check"
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
    """Fill the policy axes for a record that cites program, facts and plan."""
    (p_id, prog), (_, facts), (_, pl) = typed[SCHEMA_PROGRAM], typed[SCHEMA_FACTS], typed[SCHEMA_PLAN]
    admitted = (p_id in prof["admitted_programs"] and prog.get("obligation") == prof["obligation"]
                and facts.get("obligation") == prof["obligation"])
    axes["policy_authority"] = "ADMITTED" if admitted else "AUTHORITY_UNESTABLISHED"
    trusted_bodies = {k: v["body"] for k, v in records.items()} if integrity == "VERIFIED" else {}
    axes["fact_provenance"], why["fact_provenance"] = _fact_provenance(store, records, facts, prof, trusted_bodies)
    axes["compilation_binding"], why["compilation_binding"] = _compilation_binding(body, prog, facts, pl)
    if axes["compilation_binding"] == "MATCHED_COMPILATION":
        axes["computation_verification"], axes["policy_answer"] = replay_answer(store, pl["emitted"]["check"])
    gates = (integrity == "VERIFIED" and axes["policy_authority"] == "ADMITTED"
             and axes["fact_provenance"] == "ACCEPTED" and axes["compilation_binding"] == "MATCHED_COMPILATION")
    if gates:
        axes["decision_compliance"] = decide(body.get("decision"), axes["policy_answer"], prof["discretionary_reject"])


def assess(store_root, record_id, prof):
    store = W.Store(str(store_root))
    records = _records(store)
    env = records.get(record_id)
    if env is None:
        raise KeyError(record_id)
    body = env["body"]
    axes = dict.fromkeys(("policy_authority", "fact_provenance", "compilation_binding",
                          "computation_verification", "policy_answer", "decision_compliance"), "NOT_ASSESSED")
    why = {}
    integrity, errs = _record_integrity(store, prof["trust_config"])
    axes["record_integrity"] = integrity
    if errs:
        why["record_integrity"] = errs[:3]
    typed = _typed_under(store, body)
    has_all = all(s in typed for s in (SCHEMA_PROGRAM, SCHEMA_FACTS, SCHEMA_PLAN))
    axes["required_profile"] = "SATISFIED" if (has_all or prof["required"] == "witness") else \
        "REQUIRED_PROFILE_NOT_SATISFIED"
    if has_all:
        _assess_typed(store, records, body, typed, prof, integrity, axes, why)
    admitted = (axes["required_profile"] == "SATISFIED" and axes["decision_compliance"] == "COMPLIANT"
                and body.get("decision") == "accept")
    bad = [k for k, v in axes.items() if v not in AXES[k]]
    if bad:
        raise ValueError(f"axis value outside its vocabulary: {bad}")
    return {"schema": SCHEMA_REPORT, "record": record_id, "axes": axes,
            "why": {k: v for k, v in why.items() if v}, "consumer_admits_action": admitted,
            "context_id": context_id(store, prof)}


def context_id(store, prof):
    """Who assessed what under which rules: verifier build, recipient profile,
    and the store's record set. Unsigned; a signature over it would only attest it."""
    build = hashlib.sha256((HERE / "assessment.py").read_bytes() + (HERE / "warrant.py").read_bytes()
                           + (HERE / "policy_lang.py").read_bytes()).hexdigest()
    recs = sorted(p.stem for p in store.records.glob("*.json"))
    return blob_id({"verifier_build": build, "profile": prof, "records": recs, "runtime": RUNTIME})


# ---------------------------------------------------------------- P4: settlement

def consequence(report, prof):
    """The settled meaning of an assessment, or None. Only a replayed answer of a
    matched compilation in the recipient's admitted scope is a consequence; how it
    was reached (term syntax, headroom, budget, checkpoints, claimed verdict) is not
    part of it (§17, D09)."""
    a = report["axes"]
    if a["computation_verification"] != "REPLAYED_NORMAL_FORM" or a["compilation_binding"] != "MATCHED_COMPILATION" \
            or a["policy_authority"] != "ADMITTED" or a["policy_answer"] not in ("TRUE", "FALSE"):
        return None
    return (prof["semantics_class"], prof["obligation"], a["policy_answer"])


def novelty(settled, candidate, prof, candidate_class=None, new_evidence=None):
    """May `candidate` reopen a matter settled as `settled` (a consequence)?

    NEW_CONSEQUENCE   a different replayed answer in the same admitted scope
    NEW_EVIDENCE      a new value in a slot the recipient names, from an admitted issuer
    NO_NEW_CONSEQUENCE everything else in scope: progress, wrappers, more budget,
                      another checkpoint, a claimed expectation, an unnamed blob
    MIGRATION_REQUIRED the candidate runs another semantics class
    SCOPE_MISMATCH    another obligation than the settled one"""
    if candidate_class is not None and candidate_class != prof["semantics_class"]:
        return "MIGRATION_REQUIRED"
    if new_evidence:
        slot, issuer = new_evidence
        if slot in prof["evidence_slots"] and issuer in prof["fact_issuers"]:
            return "NEW_EVIDENCE"
    if candidate is None:
        return "NO_NEW_CONSEQUENCE"
    if candidate[:2] != settled[:2]:
        return "SCOPE_MISMATCH" if candidate[0] == settled[0] else "MIGRATION_REQUIRED"
    return "NEW_CONSEQUENCE" if candidate[2] != settled[2] else "NO_NEW_CONSEQUENCE"


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
