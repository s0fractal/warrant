#!/usr/bin/env python3
"""WRT-022 S2: crossings with zero automatic credit, and replay receipts that the
recipient re-verifies itself.

DRAFT profile code, used by impl/loops.py. Nothing `warrant verify` decides changes.

A crossing (`warrant.crossing@draft-2`) carries an artifact from one trajectory into
another with a translation report. It gives no credit by being stored:
  TRANSLATED      complete report, nothing unknown
  BORROWED        complete fields, but something `unknown`: visible, no credit
  UNTRANSLATABLE  a valid first-class outcome; the conflicting invariants are named
A crossing may carry a replay receipt. The receipt never discharges anything on
its own word: the recipient re-runs the computation with a PINNED verifier, in
this view, and only then may a duty that admits REPLAYED and names exactly that
computation be discharged on the basis REPLAYED.

  ski@v1        warrant's own pinned evaluator (warrant.SKI_EVALUATORS)
  sigma-resume  the vendored kernel in impl/sigma_resume_c864d3e/, run by
                impl/replay_sigma_worker.py in an isolated interpreter

Re-verification costs as much as the original run: a signature or an address never
amortizes it across peers (paper §3; WRT-022 rev 2 §4.5).
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import warrant as W

HERE = Path(__file__).resolve().parent
CROSSING = "warrant.crossing@draft-2"
ENVIRONMENT = "warrant.sigma-environment@draft-1"
REPORT_FIELDS = ("preserved", "lost", "introduced", "approximated", "unknown")
OUTCOMES = {"TRANSLATED", "UNTRANSLATABLE"}
STATES = {"TRANSLATED", "BORROWED", "UNTRANSLATABLE"}
RUNTIMES = {"ski@v1", "sigma-resume"}
VERDICTS = {"pass", "fail"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REV = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
WORKER = HERE / "replay_sigma_worker.py"
SIGMA_RESUME_PIN = "575a198d47519f56cb8cf75458d5d9754492433f98650d1ddf1f3580a363e858"
SIGMA_GLYPH_PIN = "f4d9990d40f07c8cfd3aa10512c2195a0a04e8dc78bc955c0f53dfe737d3feb4"
# The assessing side's own commitment to the WHOLE sigma-resume verifier: the
# worker that runs it and both kernel files (review S2-02). Paths are relative to
# the worker's directory. The worker re-checks the kernel pins before import; it
# cannot redefine what is admitted here by reporting one unchanged component.
SIGMA_VERIFIER = {
    "replay_sigma_worker.py": "db6d924369f64d5b6c00860466d76000bf9c49723aecf6f4c9b2bb343d5b513d",
    "sigma_resume_c864d3e/sigma_resume.py": SIGMA_RESUME_PIN,
    "sigma_resume_c864d3e/sigma_glyph.py": SIGMA_GLYPH_PIN,
}
EVALUATOR = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _hex(v):
    return isinstance(v, str) and HEX64.match(v) is not None


def _strs(v):
    return isinstance(v, list) and all(isinstance(s, str) and s for s in v)


def _enum(v, choices):
    """JSON type before set membership (the WL03 and S1-01 class)."""
    return isinstance(v, str) and v in choices


def computation_problem(c):
    """None if `c` names one computation a duty requires, else the reason."""
    if not isinstance(c, dict) or not _enum(c.get("runtime"), RUNTIMES):
        return "computation runtime"
    if c["runtime"] == "ski@v1":
        # The duty binds the ANSWER (the result node hash), never the check's verdict:
        # a compiled check pins its own answer, so `pass` only means "the replay
        # reproduced what was pinned" -- a refusal that pins FALSE passes too
        # (WRT-020 gap 2; caught by X05 while S2 was written).
        if set(c) != {"runtime", "check", "expect"} or not _hex(c["check"]) or not _hex(c["expect"]):
            return "ski@v1 computation takes exactly check and expect (a result node hash)"
    elif set(c) != {"runtime", "input_term_hash", "environment", "expect"} or not all(
            _hex(c[k]) for k in ("input_term_hash", "environment", "expect")):
        return "sigma-resume computation takes exactly input_term_hash, environment and expect"
    return None


def _replay_problem(r):
    if not isinstance(r, dict) or not _enum(r.get("runtime"), RUNTIMES):
        return "replay runtime"
    claimed = r.get("claimed")
    if r["runtime"] == "ski@v1":
        if set(r) != {"runtime", "check", "claimed"} or not _hex(r["check"]):
            return "ski@v1 replay takes exactly check and claimed"
        if not (isinstance(claimed, dict) and set(claimed) == {"verdict", "result_node_hash"}
                and _enum(claimed["verdict"], VERDICTS) and _hex(claimed["result_node_hash"])):
            return "ski@v1 claimed"
        return None
    if set(r) != {"runtime", "input_term_hash", "environment", "checkpoint", "state", "claimed"} or not all(
            _hex(r[k]) for k in ("input_term_hash", "environment", "checkpoint", "state")):
        return "sigma-resume replay fields"
    if not (isinstance(claimed, dict) and set(claimed) == {"outcome", "result_term_hash"}
            and _enum(claimed["outcome"], {"NORMAL_FORM"}) and _hex(claimed["result_term_hash"])):
        return "sigma-resume claimed"
    return None


def crossing_problem(doc):
    """None if `doc` is a well-formed crossing, else the reason."""
    want = {"schema", "source", "target_profile", "mapping", "report", "outcome", "conflicts", "transferred"}
    if not (isinstance(doc, dict) and doc.get("schema") == CROSSING and want <= set(doc) <= want | {"replay"}):
        return "crossing fields"
    src = doc["source"]
    if not (isinstance(src, dict) and set(src) == {"trajectory", "artifact", "revision"}
            and isinstance(src["trajectory"], str) and src["trajectory"]
            and (src["artifact"] is None or _hex(src["artifact"]))
            and (src["revision"] is None or (isinstance(src["revision"], str) and REV.match(src["revision"])))):
        return "crossing source"
    if not (isinstance(doc["target_profile"], str) and doc["target_profile"]
            and isinstance(doc["mapping"], str) and doc["mapping"]):
        return "crossing target or mapping"
    rep = doc["report"]
    if not (isinstance(rep, dict) and set(rep) == set(REPORT_FIELDS) and all(
            isinstance(rep[k], list) and all(isinstance(s, str) and s for s in rep[k]) for k in REPORT_FIELDS)):
        return "translation report"
    if not _enum(doc["outcome"], OUTCOMES) or not isinstance(doc["conflicts"], list) \
            or not all(isinstance(s, str) and s for s in doc["conflicts"]):
        return "crossing outcome"
    if (doc["outcome"] == "UNTRANSLATABLE") != bool(doc["conflicts"]):
        return "UNTRANSLATABLE names its conflicting invariants, and only it does"
    if not (isinstance(doc["transferred"], list) and all(_hex(h) for h in doc["transferred"])):
        return "transferred"
    if "replay" in doc:
        return _replay_problem(doc["replay"])
    return None


def state(doc):
    """TRANSLATED, BORROWED or UNTRANSLATABLE, for a well-formed crossing."""
    if doc["outcome"] == "UNTRANSLATABLE":
        return "UNTRANSLATABLE"
    return "BORROWED" if doc["report"]["unknown"] else "TRANSLATED"


def environment_problem(doc):
    if not (isinstance(doc, dict) and set(doc) == {"schema", "hashes"} and doc["schema"] == ENVIRONMENT):
        return "environment fields"
    hs = doc["hashes"]
    if not (isinstance(hs, list) and hs and all(_hex(h) for h in hs) and hs == sorted(set(hs))):
        return "environment hashes must be sorted unique hex64"
    return None


def _digest(p):
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else "MISSING"
    except OSError:
        return "MISSING"


def observe():
    """What the verifiers on this host actually are, read once per assessment. It
    goes into the assessment identity (review S2-03): a drifted, missing or
    re-pinned verifier changes the id, as it can change the verdict."""
    base = Path(WORKER).parent
    ski = W.bundled_sigma_path("ski@v1")
    return {"sigma-resume": {rel: _digest(base / rel) for rel in sorted(SIGMA_VERIFIER)},
            "ski@v1": {ski.name: _digest(ski)} if ski is not None else {"ski@v1": "MISSING"}}


def _sigma_unpinned(observed):
    # Kernel files first, then the worker: the reason names the first component
    # that is not the committed one, so each lock is observable on its own.
    for rel, want in sorted(SIGMA_VERIFIER.items(), key=lambda kv: (kv[0] == "replay_sigma_worker.py", kv[0])):
        got = observed["sigma-resume"].get(rel, "MISSING")
        if got == "MISSING":
            return f"verifier missing: {rel}"
        if got != want:
            return f"verifier not pinned: {rel}"
    return None


def _ski(store, r, comp):
    if r["check"] != comp["check"]:
        return None, "the receipt replays another computation than the duty requires"
    try:
        verdict, result, _ = W.run_ski_check(store, r["check"])
    except RuntimeError as e:
        return None, f"ski@v1 not re-run here: {e}"
    if verdict != r["claimed"]["verdict"] or result != r["claimed"]["result_node_hash"]:
        return None, "the recipient's replay disagrees with the receipt"
    if result != comp["expect"]:
        return None, "the replayed result is not the one the duty requires"
    pin = W.SKI_EVALUATORS["ski@v1"][1]
    return f"REPLAYED:ski@v1:{pin[:16]}", None


def _sigma(store, r, comp, blob, observed):
    if (r["input_term_hash"], r["environment"]) != (comp["input_term_hash"], comp["environment"]):
        return None, "the receipt replays another computation than the duty requires"
    why = _sigma_unpinned(observed)
    if why:
        return None, why
    env = blob(r["environment"])
    why = environment_problem(env) if env is not None else "environment manifest not in view"
    if why:
        return None, why
    req = json.dumps({"store": str(store.root), "receipt": r})
    p = subprocess.run([sys.executable, "-I", str(WORKER)], input=req, capture_output=True, text=True, check=False)
    try:
        res = json.loads(p.stdout)
    except ValueError:
        return None, f"sigma-resume verifier failed (exit {p.returncode})"
    if "refused" in res:
        return None, res["refused"]
    if res.get("verifier") != {"sigma_resume.py": SIGMA_RESUME_PIN, "sigma_glyph.py": SIGMA_GLYPH_PIN}:
        return None, "verifier not pinned: the worker reports other kernel bytes"
    if res["basis"] != "REPLAYED":
        return None, f"not replayed: {res['code']}"
    if res["code"] != "NORMAL_FORM":
        return None, f"replayed, but {res['code']} is not an answer"
    if res["result_term_hash"] != r["claimed"]["result_term_hash"]:
        return None, "the recipient's replay disagrees with the receipt"
    if res["result_term_hash"] != comp["expect"]:
        return None, "the replayed result is not the one the duty requires"
    return f"REPLAYED:sigma-resume:{SIGMA_RESUME_PIN[:16]}", None


def validate(store, blob, computation, evidence, accepted_targets, observed):
    """May this mapping be discharged on the basis REPLAYED, in this view?
    Returns (label, None) or (None, reason). `blob(h)` reads a canonical JSON blob.
    `accepted_targets` are the crossing targets THIS recipient's profile accepts;
    `observed` is this assessment's verifier observation (observe())."""
    if computation is None:
        return None, "the duty names no computation, so no replay can discharge it"
    crossings = [d for d in (blob(h) for h in evidence) if isinstance(d, dict) and d.get("schema") == CROSSING]
    if len(crossings) != 1:
        return None, "a REPLAYED mapping cites exactly one crossing"
    doc = crossings[0]
    why = crossing_problem(doc)
    if why:
        return None, f"crossing: {why}"
    st = state(doc)
    if st != "TRANSLATED":
        return None, f"crossing is {st}: no credit"
    # A replay establishes the result; it does not establish that THIS recipient
    # accepts a translation into the crossing's target (review S2-01).
    if doc["target_profile"] not in accepted_targets:
        return None, f"crossing into {doc['target_profile']!r} is not accepted by this recipient"
    r = doc.get("replay")
    if r is None:
        return None, "the crossing carries no replay receipt"
    if r["runtime"] != computation["runtime"]:
        return None, "the receipt is for another runtime"
    if r["runtime"] == "ski@v1":
        return _ski(store, r, computation)
    return _sigma(store, r, computation, blob, observed)
