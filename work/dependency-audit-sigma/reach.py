#!/usr/bin/env python3
"""Dependency-policy workload for Sigma-Glyph 0.8.0 (Book I, C1 -> SKI): amendment 1.

For s0fractal/sigma-glyph#68 over the frozen #150 input (warrant 67e0031, manifest
7d722e26…). Input is the `warrant-dependency-input-evidence/1` document that
`examples/dependency-audit/evidence.py` prints for one case; this module rebuilds and
checks its graph/evaluation/binding digests before encoding anything.

    input = P C R F Q        (P is fixed; C R F Q are the case's numeric evaluation)
    C     = columns of the reflexive adjacency, DESCENDING column order:
            C[j][i] = TRUE iff i == j or [i, j] in edges
    R     = root indicator;  F = forbidden indicator;  Q = required indicator
    P C R F Q -> K   iff no forbidden vertex is reachable AND every required one is
              -> K I otherwise

Sigma performs reachability AND the whole policy predicate. The host computes no
verdict; `reference()` is an independent traversal used only to check the answer.
A workload is ADMITTED only after a capped (VERIFIER_LIMITS) run reaches a normal
form that is exactly K or K I; anything else is INCONCLUSIVE and gets no pause
credit (review finding 1).

    python3 reach.py selftest  EVIDENCE_DIR      # controls (synthetic + real cases)
    python3 reach.py workload  EVIDENCE.json     # admission + identities (JSON)
    python3 reach.py resume    EVIDENCE.json     # PAUSED -> checked resume via sigma_provider
    python3 reach.py measure                     # synthetic scaling/limit shapes

EVIDENCE_DIR holds kit-evidence-<case>.json for base, compute, transitive-prohibited.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import sigma_glyph as G  # the installed provider's kernel (sigma-glyph 0.8.0)

ENCODER_ID = "warrant-dep-policy/amend-1"
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
PROVIDER_ID = "0caff793d00dd798fa0af89517674c2ca562e1d517e7c969cc40617778c776c5"
MANIFEST_SHA256 = "7d722e2664dc57f1618b3bd7c47d3ffbb77d775f770315a8ebc1dcf0b6645653"
TRUE_T, FALSE_T = ("lit", G.sha(b"K")), ("app", ("lit", G.sha(b"K")), ("lit", G.sha(b"I")))
VERDICT = {G.K_H: True, G.FALSE_H: False}           # the only recognized normal forms
N_STRUCT = 7          # structural pre-check only; admission is the capped run below
ATP_CAP = G.VERIFIER_LIMITS["max_atp"]                # 10,000,000: replayable from the root


class Refused(Exception):
    """Input outside the contract or a broken binding. Never a FALSE verdict."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# ----------------------------------------------------------------- lambda frontend
_ATOMS = {"S": ("lit", G.sha(b"S")), "K": ("lit", G.sha(b"K")), "I": ("lit", G.sha(b"I")),
          "TRUE": TRUE_T, "FALSE": FALSE_T}
DEFS = {}


def _parse(src):
    toks = re.findall(r"\\|\.|\(|\)|[A-Za-z_][A-Za-z0-9_]*", src)
    pos = 0

    def expr(bound):
        nonlocal pos
        if toks[pos] == "\\":
            pos += 1
            names = []
            while toks[pos] != ".":
                names.append(toks[pos])
                pos += 1
            pos += 1
            body = expr(bound | set(names))
            for nm in reversed(names):
                body = ("lam", nm, body)
            return body
        f = atom(bound)
        while pos < len(toks) and toks[pos] != ")":
            f = ("lapp", f, atom(bound))
        return f

    def atom(bound):
        nonlocal pos
        t = toks[pos]
        pos += 1
        if t == "(":
            e = expr(bound)
            assert toks[pos] == ")"
            pos += 1
            return e
        if t in bound:
            return ("var", t)
        if t in DEFS:
            return DEFS[t]
        return _ATOMS[t]

    e = expr(frozenset())
    assert pos == len(toks), toks[pos:]
    return e


def define(name, src):
    DEFS[name] = _parse(src)


# Encoding rules (DESIGN.md §2.1): R1 lambda-lifted; R2 the state vector is the LAST
# parameter and only the last argument; R3 bits are decided in head position before a
# continuation is chosen; R4 the next state is accumulated forward.
define("snil",    r"\c n. n")
define("scons",   r"\h t c n. c h t")
# EXISTS i: col[i] AND r[i]
define("AA_hit",  r"\rec b r2. b TRUE (rec r2)")
define("AA_miss", r"\rec b r2. rec r2")
define("AA_step", r"\c rec r. r (c AA_hit AA_miss rec) FALSE")
define("AA_fin",  r"\r. FALSE")
define("anyAnd",  r"\col r. col AA_step AA_fin r")
# FORALL i: q[i] -> r[i]
define("AR_need", r"\rec b r2. b (rec r2) FALSE")
define("AR_skip", r"\rec b r2. rec r2")
define("AR_step", r"\q rec r. r (q AR_need AR_skip rec) TRUE")
define("AR_fin",  r"\r. TRUE")
define("allReq",  r"\Q r. Q AR_step AR_fin r")
# one round: r'[j] = anyAnd(C[j], r)
define("RD_step", r"\col rest k acc r. (anyAnd col r) (rest k (scons TRUE acc)) (rest k (scons FALSE acc)) r")
define("RD_fin",  r"\k acc r. k acc")
define("round",   r"\C k r. C RD_step RD_fin k snil r")
# n-1 rounds driven by C; its first element only sets the flag
define("IT_k",    r"\rec k r2. rec TRUE k r2")
define("IT_step", r"\C x rec f k r. f (round C (IT_k rec k) r) (rec TRUE k r)")
define("IT_fin",  r"\f k r. k r")
define("iter",    r"\C k0 r0. C (IT_step C) IT_fin FALSE k0 r0")
# the policy over the reached set: NOT (some forbidden reached) AND (all required reached)
define("policy",  r"\F Q r. (anyAnd F r) FALSE (allReq Q r)")
define("P",       r"\C R F Q. iter C (policy F Q) (R scons snil)")

PROGRAM = G.c1(DEFS["P"])


# ----------------------------------------------------------------- #150 input
def canon(doc):
    """The #150 application byte encoding (sorted keys, compact, ASCII)."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha(doc):
    return hashlib.sha256(canon(doc)).hexdigest()


def _sorted_unique_ints(xs, n, what):
    if not (isinstance(xs, list) and all(type(x) is int and 0 <= x < n for x in xs)):
        raise Refused("MALFORMED", f"{what} must be indices in 0..{n - 1}")
    if xs != sorted(set(xs)):
        raise Refused("MALFORMED", f"{what} must be sorted and unique")
    return xs


def evaluation_of(evidence):
    """Check one input-evidence document and return (evaluation, binding).

    Every digest the evidence carries is recomputed here; a mismatch refuses."""
    if not isinstance(evidence, dict) or evidence.get("schema") != "warrant-dependency-input-evidence/1":
        raise Refused("SCHEMA", "not warrant-dependency-input-evidence/1")
    if evidence.get("state") != "INPUT_VERIFIED_ENCODING_PENDING" \
            or evidence.get("artifact_binding") != "WHEEL_BYTES_VERIFIED":
        raise Refused("INPUT_STATE", "input is not wheel-byte verified")
    if evidence.get("expected_provider") != PROVIDER_ID:
        raise Refused("PROVIDER", "unexpected provider identity")
    b, graph = evidence["binding"], evidence["graph"]
    if b.get("manifest_sha256") != MANIFEST_SHA256:
        raise Refused("MANIFEST_PIN", "not the frozen #150 instance")
    if sha(b) != evidence.get("binding_id"):
        raise Refused("BINDING", "binding_id does not hash the binding")
    if sha(graph) != b.get("graph_sha256"):
        raise Refused("GRAPH_DIGEST", "graph bytes are not the bound graph")
    ev = graph.get("evaluation")
    if sha(ev) != b.get("evaluation_sha256"):
        raise Refused("EVALUATION_DIGEST", "evaluation is not the bound evaluation")
    if graph.get("schema") != "warrant-dependency-graph/1":
        raise Refused("SCHEMA", "graph schema")
    nodes = graph.get("nodes")
    check_evaluation(ev)
    if not isinstance(nodes, list) or len(nodes) != ev["n"]:
        raise Refused("MALFORMED", "node list does not have n entries")
    names = [x.get("name") for x in nodes]
    if names != sorted(set(names)):
        raise Refused("MALFORMED", "nodes are not sorted unique names")
    return ev, b


def check_evaluation(ev):
    if not isinstance(ev, dict) or set(ev) != {"n", "edges", "root", "forbidden", "required"}:
        raise Refused("MALFORMED", "evaluation fields are not exactly n/edges/root/forbidden/required")
    n = ev["n"]
    if type(n) is not int or not 1 <= n <= N_STRUCT:
        raise Refused("LIMIT_NODES", f"n={n!r}, structural limit 1..{N_STRUCT}")
    if type(ev["root"]) is not int or not 0 <= ev["root"] < n:
        raise Refused("MALFORMED", "root")
    edges = ev["edges"]
    if not (isinstance(edges, list) and all(isinstance(e, list) and len(e) == 2 for e in edges)):
        raise Refused("MALFORMED", "edges must be [i, j] pairs")
    if not all(type(x) is int and 0 <= x < n for e in edges for x in e):
        raise Refused("MALFORMED", f"edge endpoints must be indices in 0..{n - 1}")
    if [tuple(e) for e in edges] != sorted(set(tuple(e) for e in edges)):
        raise Refused("MALFORMED", "edges must be sorted and unique")
    _sorted_unique_ints(ev["forbidden"], n, "forbidden")
    _sorted_unique_ints(ev["required"], n, "required")
    return ev


# ----------------------------------------------------------------- data terms
def _church(items):
    body = ("var", "n")
    for x in reversed(items):
        body = ("lapp", ("lapp", ("var", "c"), x), body)
    return G.c1(("lam", "c", ("lam", "n", body)))


def _bits(n, members):
    s = set(members)
    return _church([TRUE_T if i in s else FALSE_T for i in range(n)])


def data_terms(ev):
    n, E = ev["n"], {tuple(e) for e in ev["edges"]}
    C = _church([_church([TRUE_T if (i == j or (i, j) in E) else FALSE_T for i in range(n)])
                 for j in reversed(range(n))])
    return C, _bits(n, [ev["root"]]), _bits(n, ev["forbidden"]), _bits(n, ev["required"])


def _app(*ts):
    t = ts[0]
    for u in ts[1:]:
        t = ("app", t, u)
    return t


def build(ev, program=None):
    """-> (input term, term identities). `program` lets a control substitute P."""
    check_evaluation(ev)
    C, R, F, Q = data_terms(ev)
    prog = PROGRAM if program is None else program
    inp = _app(prog, C, R, F, Q)
    hx = lambda t: G.term_hash(t).hex()
    return inp, {"program": hx(prog), "C": hx(C), "R": hx(R), "F": hx(F), "Q": hx(Q), "input": hx(inp)}


def nodes_of(t):
    out, stack = {}, [t]
    while stack:
        x = stack.pop()
        if x[0] == "app":
            b = G.term_bytes(x)
            h = G.node_hash(b)
            if h not in out:
                out[h] = b
                stack += [x[1], x[2]]
    return out


def ski_text(t):
    out, stack, names = [], [t], {G.S_H: "S", G.K_H: "K", G.I_H: "I"}
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            out.append(x)
        elif x[0] == "app":
            stack += [")", x[2], " ", x[1], "("]
        else:
            out.append(names[G.term_hash(x)])
    return "".join(out)


# ----------------------------------------------------------------- evaluation and reference
def evaluate(inp, atp=ATP_CAP, limits=None):
    env = nodes_of(inp)
    t0 = time.perf_counter()
    try:
        rc = G.eval_receipt(G.term_hash(inp), atp, env, limits or G.VERIFIER_LIMITS)
    except G.ResourceFault as e:
        return {"exit": "resource_fault", "detail": str(e), "verdict": None, "atp": None,
                "wall_s": round(time.perf_counter() - t0, 3), "env_nodes": len(env)}
    wall = time.perf_counter() - t0
    verdict = VERDICT.get(rc.result_hash) if rc.exit == "normal_form" else None
    return {"exit": rc.exit, "verdict": verdict, "result": rc.result_hash.hex(),
            "atp": rc.atp_spent, "wall_s": round(wall, 3), "env_nodes": len(env)}


def reference(ev):
    """Independent traversal (the check, not the answer)."""
    adj = {}
    for i, j in ev["edges"]:
        adj.setdefault(i, []).append(j)
    seen, stack = {ev["root"]}, [ev["root"]]
    while stack:
        for j in adj.get(stack.pop(), []):
            if j not in seen:
                seen.add(j)
                stack.append(j)
    return (not (seen & set(ev["forbidden"])) and set(ev["required"]) <= seen), sorted(seen)


def environment_id(inp):
    import sigma_resume as RS
    return RS.Environment(set(nodes_of(inp)), {}).environment_id


def workload(evidence):
    """Admission + the full identity document for one case. Never raises on a
    capped-run failure: that is ADMITTED=false / INCONCLUSIVE."""
    import sigma_resume as RS
    ev, b = evaluation_of(evidence)
    inp, ids = build(ev)
    r = evaluate(inp)
    admitted = r["exit"] == "normal_form" and r["verdict"] is not None and r["atp"] <= ATP_CAP
    root_doc, computation_id = RS.root(G.term_hash(inp), RS.Environment(set(nodes_of(inp)), {}))
    doc = {"schema": "warrant-dep-policy-workload/1", "encoder": ENCODER_ID,
           "encoder_source_sha256": SOURCE_SHA256, "provider": PROVIDER_ID,
           "runtime": RS.RUNTIME_SEMANTICS_ID, "cost_model": RS.COST_MODEL_ID,
           "input_binding_id": evidence["binding_id"], "input_binding": b,
           "terms": ids, "environment_id": root_doc["environment_id"], "computation_id": computation_id,
           "env_nodes": r["env_nodes"], "admission": {
               "state": "ADMITTED" if admitted else "INCONCLUSIVE",
               "cap_atp": ATP_CAP, "exit": r["exit"], "total_atp": r["atp"],
               "expected_result": r.get("result") if admitted else None,
               "verdict": r["verdict"] if admitted else None,
               "pause_credit": r["atp"] // 2 if admitted else None,
               "oracle_wall_s": r["wall_s"]}}
    doc["workload_id"] = sha({k: v for k, v in doc.items() if k != "admission"} |
                             {"admission": {k: v for k, v in doc["admission"].items() if k != "oracle_wall_s"}})
    return doc


def resume_run(evidence, workload_doc=None):
    """PAUSED prefix at the frozen pause credit, then a checked resume (REPLAYED)."""
    import sigma_provider as SP
    import sigma_resume as RS
    w = workload_doc or workload(evidence)
    if w["admission"]["state"] != "ADMITTED":
        return {"state": "INCONCLUSIVE", "reason": "not admitted; no pause credit derived"}
    ev, _ = evaluation_of(evidence)
    inp, ids = build(ev)
    tm = SP.term(ski_text(inp))
    if tm["input"] != ids["input"]:
        raise Refused("IDENTITY", "provider parse does not reproduce the input")
    hashes, blobs = sorted(tm["nodes"]), tm["nodes"]
    total, pause = w["admission"]["total_atp"], w["admission"]["pause_credit"]
    s = SP.start(RS.RUNTIME_SEMANTICS_ID, tm["input"], hashes)
    t0 = time.perf_counter()
    a = SP.advance(RS.RUNTIME_SEMANTICS_ID, hashes, blobs, s["checkpoint"], s["state"], pause)
    t1 = time.perf_counter()
    b = SP.resume(RS.RUNTIME_SEMANTICS_ID, tm["input"], hashes, blobs, a["checkpoint"], a["state"],
                  total - pause)
    t2 = time.perf_counter()
    seg = b.get("segment", {})
    ck = json.loads(seg["checkpoint"]) if seg.get("checkpoint") else {}
    pk = json.loads(a["checkpoint"])
    return {"workload_id": w["workload_id"], "input": tm["input"], "computation_id": s["computation_id"],
            "first": {"outcome": a["outcome"], "spent": pk["spent_total"], "credit": pk["credit_total"],
                      "checkpoint_sha256": hashlib.sha256(a["checkpoint"] if isinstance(a["checkpoint"], bytes)
                                                          else a["checkpoint"].encode()).hexdigest(),
                      "wall_s": round(t1 - t0, 2)},
            "resume": {"status": b.get("status"), "basis": b.get("base_verification", {}).get("basis"),
                       "outcome": seg.get("outcome"), "result": seg.get("result"),
                       "verdict": VERDICT.get(bytes.fromhex(seg["result"])) if seg.get("result") else None,
                       "spent_total": ck.get("spent_total"), "peak_semantic_size": ck.get("peak_semantic_size"),
                       "wall_s_incl_replay": round(t2 - t1, 2)},
            "matches_admission": seg.get("result") == w["admission"]["expected_result"]
                                 and ck.get("spent_total") == total}


# ----------------------------------------------------------------- controls
def _check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""), flush=True)
    return cond


def _chain(n, reverse=False, cycle=False):
    edges = [[i + 1, i] for i in range(n - 1)] if reverse else [[i, i + 1] for i in range(n - 1)]
    if cycle:
        edges.append([0, n - 1] if reverse else [n - 1, 0])
    return sorted(edges)


# SYNTHETIC evaluation objects (numeric only; labelled; no real wheel is described)
SYNTHETIC = {
    "SYN-all-required-one-missing": ({"n": 3, "edges": [[0, 1]], "root": 0, "forbidden": [], "required": [1, 2]}, False),
    "SYN-all-required-present": ({"n": 3, "edges": [[0, 1], [1, 2]], "root": 0, "forbidden": [], "required": [1, 2]}, True),
    "SYN-forbidden-indirect": ({"n": 4, "edges": [[0, 1], [1, 2], [2, 3]], "root": 0, "forbidden": [3], "required": []}, False),
    "SYN-forbidden-isolated-required-met": ({"n": 4, "edges": [[0, 1]], "root": 0, "forbidden": [3], "required": [1]}, True),
    "SYN-cycle-required": ({"n": 4, "edges": [[0, 1], [1, 2], [2, 1], [2, 3]], "root": 0, "forbidden": [], "required": [3]}, True),
    "SYN-root-is-forbidden": ({"n": 2, "edges": [], "root": 1, "forbidden": [1], "required": []}, False),
    "SYN-empty-policy": ({"n": 2, "edges": [], "root": 0, "forbidden": [], "required": []}, True),
}

# limit shapes at n = N_STRUCT: each must be ADMITTED with the right answer, or INCONCLUSIVE
LIMIT_SHAPES = {
    "SYN-n7-chain-forward": {"n": 7, "edges": _chain(7), "root": 0, "forbidden": [6], "required": []},
    "SYN-n7-chain-reverse": {"n": 7, "edges": _chain(7, reverse=True), "root": 6, "forbidden": [0], "required": []},
    "SYN-n7-edgeless": {"n": 7, "edges": [], "root": 0, "forbidden": [6], "required": []},
    "SYN-n7-cycle-reverse": {"n": 7, "edges": _chain(7, reverse=True, cycle=True), "root": 6, "forbidden": [0], "required": []},
    "SYN-n7-required-all": {"n": 7, "edges": _chain(7), "root": 0, "forbidden": [], "required": list(range(7))},
}


def _load_cases(evidence_dir):
    out = {}
    for case in ("base", "compute", "transitive-prohibited"):
        out[case] = json.loads(Path(evidence_dir, f"kit-evidence-{case}.json").read_text())
    return out


def selftest(evidence_dir):
    ok = True
    print(f"encoder {ENCODER_ID} source {SOURCE_SHA256}")
    print(f"program {G.term_hash(PROGRAM).hex()}  (C1 size {G.size(PROGRAM)})")
    # 1. synthetic predicate cases: Sigma == reference == expected
    for label, (ev, want) in SYNTHETIC.items():
        r = evaluate(build(ev)[0])
        ref = reference(ev)[0]
        ok &= _check(f"{label}: Sigma {r['verdict']} == reference {ref} == expected {want}",
                     r["exit"] == "normal_form" and r["verdict"] is ref is want, r)
    # 2. the three frozen #150 cases, unchanged
    cases = _load_cases(evidence_dir)
    expect = {"base": True, "compute": True, "transitive-prohibited": False}
    shape = {"base": (6, 3), "compute": (6, 4), "transitive-prohibited": (4, 2)}
    for case, evidence in cases.items():
        w = workload(evidence)
        ev, _ = evaluation_of(evidence)
        a = w["admission"]
        ok &= _check(f"real {case} n{ev['n']}/e{len(ev['edges'])}: ADMITTED, Sigma {a['verdict']} "
                     f"== reference == frozen {expect[case]}  ({a['total_atp']} ATP)",
                     (ev["n"], len(ev["edges"])) == shape[case] and a["state"] == "ADMITTED"
                     and a["verdict"] is reference(ev)[0] is evidence["reference_only"]["predicate"] is expect[case], a)
    # 3. per-instance admission at the structural limit (review finding 1)
    for label, ev in LIMIT_SHAPES.items():
        r = evaluate(build(ev)[0])
        state = "ADMITTED" if r["exit"] == "normal_form" and r["verdict"] is not None else "INCONCLUSIVE"
        good = (state == "ADMITTED" and r["verdict"] is reference(ev)[0]) or \
               (state == "INCONCLUSIVE" and r["verdict"] is None)
        ok &= _check(f"{label}: {state} ({r['exit']}, {r['atp']} ATP); never a wrong or uncapped verdict", good, r)
    # 4. binding: digests are rechecked, and absent policy names change the binding (finding 2)
    base = cases["base"]
    forged = copy.deepcopy(base)
    forged["graph"]["evaluation"]["forbidden"] = [2]          # drop sigma-glyph from policy
    for nm, doc, code in (
            ("forged evaluation", forged, "GRAPH_DIGEST"),
            ("forged evaluation, graph/binding rehashed, evaluation digest stale", _rebind(forged),
             "EVALUATION_DIGEST"),
            ("renamed absent policy vertex", _renamed(base, "mcp", "mcq"), "GRAPH_DIGEST"),
            ("changed binding field", _with(base, ["binding", "case"], "compute"), "BINDING"),
            ("other manifest", _with(base, ["binding", "manifest_sha256"], "0" * 64), "MANIFEST_PIN"),
            ("metadata-only input", _with(base, ["artifact_binding"], "METADATA_ONLY_UNVERIFIED"), "INPUT_STATE")):
        try:
            evaluation_of(doc)
            got = "accepted"
        except Refused as e:
            got = e.code
        ok &= _check(f"refused before Sigma: {nm} -> {code}", got == code, got)
    w0 = workload(base)
    rebound = _rebind(_renamed(base, "mcp", "mcq"))
    w1 = workload(rebound)
    ok &= _check("absent policy name rebound consistently: same term/answer, DIFFERENT workload binding",
                 w1["terms"]["input"] == w0["terms"]["input"] and w1["admission"]["verdict"] == w0["admission"]["verdict"]
                 and w1["input_binding"]["graph_sha256"] != w0["input_binding"]["graph_sha256"]
                 and w1["workload_id"] != w0["workload_id"])
    # 5. constant-verdict programs: other identity, and blind to a changed edge
    ev_b, _ = evaluation_of(base)
    cut = dict(ev_b, edges=[[0, 3], [1, 0]])                  # cut warrant-loops -> cryptography
    viol = dict(ev_b, edges=sorted(ev_b["edges"] + [[3, 4]]))  # pycparser -> sigma-glyph (forbidden)
    ok &= _check("mutation: added path to a forbidden vertex flips Sigma to FALSE == reference",
                 evaluate(build(viol)[0])["verdict"] is False is reference(viol)[0])
    ev_c, _ = evaluation_of(cases["compute"])
    unreq = dict(ev_c, edges=[[0, 3], [1, 0], [5, 1]])         # drop warrant-loops -> sigma-glyph
    ok &= _check("mutation: required vertex made unreachable flips Sigma to FALSE == reference",
                 evaluate(build(unreq)[0])["verdict"] is False is reference(unreq)[0])
    for nm, src in (("const-TRUE", r"\C R F Q. TRUE"), ("const-FALSE", r"\C R F Q. FALSE")):
        prog = G.c1(_parse(src))
        a = evaluate(build(ev_b, prog)[0])["verdict"]
        v = evaluate(build(viol, prog)[0])["verdict"]
        ok &= _check(f"{nm} program: identity differs from P and ignores the forbidden-path mutation",
                     G.term_hash(prog) != G.term_hash(PROGRAM) and a == v and reference(ev_b)[0] != reference(viol)[0])
    del cut
    # 6. malformed numeric input refused, never FALSE
    for nm, ev, code in (
            ("unsorted edges", dict(ev_b, edges=[[5, 1], [0, 3]]), "MALFORMED"),
            ("duplicate edge", dict(ev_b, edges=[[0, 3], [0, 3]]), "MALFORMED"),
            ("edge out of range", dict(ev_b, edges=[[0, 9]]), "MALFORMED"),
            ("root out of range", dict(ev_b, root=6), "MALFORMED"),
            ("unsorted forbidden", dict(ev_b, forbidden=[4, 2]), "MALFORMED"),
            ("extra field", dict(ev_b, extras=[]), "MALFORMED"),
            ("over the structural limit", {"n": N_STRUCT + 1, "edges": [], "root": 0, "forbidden": [], "required": []},
             "LIMIT_NODES")):
        try:
            build(ev)
            got = "accepted"
        except Refused as e:
            got = e.code
        ok &= _check(f"refused, not FALSE: {nm} -> {code}", got == code, got)
    # 7. insufficient budget is an exit, never a verdict
    short = evaluate(build(ev_b)[0], atp=1000)
    ok &= _check("insufficient budget -> atp_exhausted, no verdict", short["exit"] == "atp_exhausted"
                 and short["verdict"] is None, short)
    print("SELFTEST: " + ("ALL PASS" if ok else "FAILURES"))
    return ok


def _with(doc, path, value):
    d = copy.deepcopy(doc)
    x = d
    for k in path[:-1]:
        x = x[k]
    x[path[-1]] = value
    return d


def _renamed(doc, old, new):
    d = copy.deepcopy(doc)
    for node in d["graph"]["nodes"]:
        if node["name"] == old:
            node["name"] = new
    return d


def _rebind(doc):
    """What a producer would publish for a changed policy name: consistent digests."""
    d = copy.deepcopy(doc)
    d["binding"]["graph_sha256"] = sha(d["graph"])
    d["binding_id"] = sha(d["binding"])
    return d


def measure():
    rows = []
    for n in range(2, N_STRUCT + 1):
        for label, ev in (
                ("chain-forward", {"n": n, "edges": _chain(n), "root": 0, "forbidden": [n - 1], "required": []}),
                ("chain-reverse", {"n": n, "edges": _chain(n, reverse=True), "root": n - 1, "forbidden": [0], "required": []}),
                ("edgeless", {"n": n, "edges": [], "root": 0, "forbidden": [n - 1], "required": []}),
                ("cycle-reverse", {"n": n, "edges": _chain(n, reverse=True, cycle=True), "root": n - 1, "forbidden": [0], "required": []}),
                ("required-all-chain", {"n": n, "edges": _chain(n), "root": 0, "forbidden": [], "required": list(range(n))})):
            r = evaluate(build(ev)[0])
            row = {"n": n, "shape": label, "reference": reference(ev)[0], **r,
                   "admission": "ADMITTED" if r["exit"] == "normal_form" and r["verdict"] is not None else "INCONCLUSIVE"}
            rows.append(row)
            print(json.dumps(row), flush=True)
    return rows


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    try:
        if cmd == "selftest":
            sys.exit(0 if selftest(sys.argv[2]) else 1)
        elif cmd == "workload":
            print(json.dumps(workload(json.loads(Path(sys.argv[2]).read_text())), indent=2, sort_keys=True))
        elif cmd == "resume":
            print(json.dumps(resume_run(json.loads(Path(sys.argv[2]).read_text())), indent=2, sort_keys=True))
        elif cmd == "measure":
            measure()
        else:
            sys.exit(f"unknown command {cmd!r}")
    except Refused as e:
        print(json.dumps({"state": "REFUSED", "code": e.code, "detail": str(e)}))
        sys.exit(2)
